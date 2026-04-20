#!/usr/bin/env python
"""Plan or execute the current production-shaped empty platform deploy flow."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


# Repo and current-state defaults.
# The wrapper stays intentionally thin and drives the imported scripts/params
# that already match the current production shape.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGION = "us-east-1"
DEFAULT_MUXER_RUNTIME_ROOT = REPO_ROOT / "muxer" / "runtime-package"
DEFAULT_BASH_SHIMS = REPO_ROOT / "scripts" / "platform" / "bash-shims"
DEFAULT_MUXER_PARAMS = REPO_ROOT / "infra" / "cfn" / "parameters.single-muxer.us-east-1.json"
DEFAULT_NAT_PARAMS = REPO_ROOT / "infra" / "cfn" / "parameters.vpn-headend.nat.graviton-efs.us-east-1.json"
DEFAULT_NONNAT_PARAMS = REPO_ROOT / "infra" / "cfn" / "parameters.vpn-headend.non-nat.graviton-efs.us-east-1.json"


def _load_parameter_map(path: Path) -> Dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list):
        raise ValueError(f"expected CloudFormation parameter array in {path}")

    result: Dict[str, str] = {}
    for item in payload:
        key = str(item.get("ParameterKey") or "").strip()
        if not key:
            continue
        result[key] = str(item.get("ParameterValue") or "").strip()
    return result


def _relative_posix(path: Path, base: Path) -> str:
    return os.path.relpath(path, start=base).replace("\\", "/")


def _shell_join(argv: List[str]) -> str:
    return " ".join(shlex.quote(part) for part in argv)


def _step(
    phase: str,
    name: str,
    cwd: Path,
    argv: List[str],
    *,
    automatic: bool = True,
    note: str = "",
) -> Dict[str, Any]:
    return {
        "phase": phase,
        "name": name,
        "cwd": str(cwd),
        "argv": argv,
        "automatic": automatic,
        "note": note,
    }


def _build_plan(args: argparse.Namespace) -> Dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    muxer_runtime_root = Path(args.muxer_repo).resolve()
    muxer_params_path = Path(args.muxer_params).resolve()
    nat_params_path = Path(args.nat_headend_params).resolve()
    nonnat_params_path = Path(args.nonnat_headend_params).resolve()

    muxer_params = _load_parameter_map(muxer_params_path)
    nat_params = _load_parameter_map(nat_params_path)
    nonnat_params = _load_parameter_map(nonnat_params_path)

    muxer_bundle_uri = muxer_params["ProjectPackageS3Uri"]
    deployment_bundle_uri_nat = nat_params["ProjectPackageS3Uri"]
    deployment_bundle_uri_nonnat = nonnat_params["ProjectPackageS3Uri"]
    if deployment_bundle_uri_nat != deployment_bundle_uri_nonnat:
        raise ValueError(
            "NAT and non-NAT head-end parameter files reference different ProjectPackageS3Uri values; "
            "review and align them before using the shared deploy wrapper."
        )

    recovery_lambda_uri = (
        f"s3://{muxer_params['RecoveryLambdaS3Bucket']}/{muxer_params['RecoveryLambdaS3Key']}"
    )
    region = args.region

    muxer_stack_name = args.muxer_stack_name or muxer_params["ClusterName"]
    nat_stack_name = args.nat_stack_name or f"{nat_params['ClusterName']}-{region}"
    nonnat_stack_name = args.nonnat_stack_name or f"{nonnat_params['ClusterName']}-{region}"

    muxer_param_rel = _relative_posix(muxer_params_path, repo_root)
    nat_param_rel = _relative_posix(nat_params_path, repo_root)
    nonnat_param_rel = _relative_posix(nonnat_params_path, repo_root)
    muxer_lambda_source_rel = _relative_posix(
        muxer_runtime_root / "cloudwatch-muxer-recovery",
        repo_root,
    )

    steps: List[Dict[str, Any]] = [
        _step(
            "preflight",
            "Verify AWS credentials",
            repo_root,
            ["aws", "sts", "get-caller-identity"],
        ),
        _step(
            "package",
            "Package the RPDB muxer runtime bundle",
            muxer_runtime_root,
            ["bash", "scripts/package_project_to_s3.sh", muxer_bundle_uri],
            note="This packages the copied-and-evolving runtime from muxer/runtime-package in the RPDB repo.",
        ),
        _step(
            "package",
            "Package the muxer recovery Lambda",
            repo_root,
            [
                "bash",
                "scripts/platform/package_muxer_recovery_lambda_to_s3.sh",
                recovery_lambda_uri,
                muxer_lambda_source_rel,
            ],
        ),
        _step(
            "validate",
            "Validate the single-muxer CloudFormation template",
            repo_root,
            ["bash", "scripts/platform/cfn_validate_single_muxer.sh"],
        ),
        _step(
            "deploy",
            "Deploy the muxer stack",
            repo_root,
            [
                "bash",
                "scripts/platform/cfn_deploy_single_muxer.sh",
                muxer_stack_name,
                muxer_param_rel,
                region,
            ],
            note="Pause and review the EIP settings in the parameter file before any real cutover.",
        ),
        _step(
            "package",
            "Package the RPDB platform artifact for the VPN head ends",
            repo_root,
            [
                "bash",
                "scripts/platform/package_project_to_s3.sh",
                deployment_bundle_uri_nat,
                ".",
            ],
            note="This packages the new RPDB repo itself as the current deployment artifact source.",
        ),
        _step(
            "validate",
            "Validate the VPN head-end CloudFormation template",
            repo_root,
            ["bash", "scripts/platform/cfn_validate_vpn_headend.sh"],
        ),
        _step(
            "deploy",
            "Deploy the NAT VPN head-end pair",
            repo_root,
            [
                "bash",
                "scripts/platform/cfn_deploy_vpn_headend.sh",
                nat_stack_name,
                nat_param_rel,
                region,
            ],
            note="This keeps the same three-ENI current production shape.",
        ),
        _step(
            "deploy",
            "Deploy the non-NAT VPN head-end pair",
            repo_root,
            [
                "bash",
                "scripts/platform/cfn_deploy_vpn_headend.sh",
                nonnat_stack_name,
                nonnat_param_rel,
                region,
            ],
            note="This also keeps the same three-ENI current production shape.",
        ),
        _step(
            "database",
            "Ensure the RPDB customer tables exist",
            repo_root,
            [
                sys.executable,
                "scripts/platform/ensure_dynamodb_tables.py",
                "--muxer-params",
                muxer_param_rel,
                "--nat-headend-params",
                nat_param_rel,
                "--nonnat-headend-params",
                nonnat_param_rel,
                "--region",
                region,
                "--create-customer-sot",
                "--create-resource-allocation-table",
                "--check-aws",
            ],
            note="The imported head-end lease tables are currently stack-managed because LeaseTableName is blank.",
        ),
    ]

    manual_validation = [
        {
            "name": "Validate the muxer runtime",
            "commands": [
                "sudo systemctl status muxer.service --no-pager",
                "sudo ip addr",
                "sudo ip rule",
                "sudo ip route show table all",
                "sudo nft list ruleset",
            ],
        },
        {
            "name": "Validate each VPN head-end node",
            "commands": [
                f"{sys.executable} scripts/platform/verify_headend_bootstrap.py --region {region} --nat-params {nat_param_rel} --nonnat-params {nonnat_param_rel} --json",
                "ip addr",
                "findmnt /LOG",
                "findmnt /Application",
                "findmnt /Shared",
                "sudo systemctl status muxingplus-ha --no-pager",
                "sudo systemctl status conntrackd --no-pager",
                "sudo systemctl status strongswan --no-pager",
            ],
        },
        {
            "name": "Validate the database state",
            "commands": [
                f"{sys.executable} scripts/platform/ensure_dynamodb_tables.py --muxer-params {muxer_param_rel} --nat-headend-params {nat_param_rel} --nonnat-headend-params {nonnat_param_rel} --region {region} --check-aws",
            ],
        },
    ]

    return {
        "region": region,
        "repo_root": str(repo_root),
        "muxer_runtime_root": str(muxer_runtime_root),
        "production_shape": {
            "muxer_instance_type": muxer_params.get("InstanceType"),
            "nat_headend_instance_type": nat_params.get("InstanceType"),
            "nonnat_headend_instance_type": nonnat_params.get("InstanceType"),
            "headend_eni_shape": "primary + ha/sync + core",
            "customer_sot_table": muxer_params.get("CustomerSotTableName"),
            "nat_cluster_name": nat_params.get("ClusterName"),
            "nonnat_cluster_name": nonnat_params.get("ClusterName"),
        },
        "stack_names": {
            "muxer": muxer_stack_name,
            "nat_headend": nat_stack_name,
            "nonnat_headend": nonnat_stack_name,
        },
        "artifact_targets": {
            "muxer_bundle_s3_uri": muxer_bundle_uri,
            "deployment_bundle_s3_uri": deployment_bundle_uri_nat,
            "recovery_lambda_s3_uri": recovery_lambda_uri,
        },
        "eip_review": {
            "required_before_execute": True,
            "entries": [
                {
                    "role": "muxer",
                    "parameter_file": str(muxer_params_path),
                    "allocation_id": muxer_params.get("EipAllocationId", ""),
                },
                {
                    "role": "nat_headend_pair",
                    "parameter_file": str(nat_params_path),
                    "allocation_id": nat_params.get("EipAllocationId", ""),
                },
                {
                    "role": "nonnat_headend_pair",
                    "parameter_file": str(nonnat_params_path),
                    "allocation_id": nonnat_params.get("EipAllocationId", ""),
                },
            ],
        },
        "steps": steps,
        "manual_validation": manual_validation,
    }


def _guard_execute(plan: Dict[str, Any], args: argparse.Namespace) -> None:
    eip_entries = [entry for entry in plan["eip_review"]["entries"] if entry["allocation_id"]]
    if eip_entries and not args.allow_production_eip:
        raise SystemExit(
            "Refusing to execute because the imported parameter files still contain EipAllocationId values. "
            "Review those settings first, then rerun with --allow-production-eip if this is an intentional cutover."
        )


def _print_plan(plan: Dict[str, Any]) -> None:
    print("Fresh empty platform deploy plan")
    print(f"- region: {plan['region']}")
    print(f"- muxer runtime root: {plan['muxer_runtime_root']}")
    print(
        "- production shape: "
        f"muxer={plan['production_shape']['muxer_instance_type']}, "
        f"nat={plan['production_shape']['nat_headend_instance_type']}, "
        f"nonnat={plan['production_shape']['nonnat_headend_instance_type']}"
    )
    print(
        "- stack names: "
        f"muxer={plan['stack_names']['muxer']}, "
        f"nat={plan['stack_names']['nat_headend']}, "
        f"nonnat={plan['stack_names']['nonnat_headend']}"
    )
    print("- EIP review is required before execute if the imported parameter files still point at live allocations.")
    print("")

    for index, step in enumerate(plan["steps"], start=1):
        print(f"{index}. [{step['phase']}] {step['name']}")
        print(f"   cwd: {step['cwd']}")
        print(f"   cmd: {_shell_join(step['argv'])}")
        if step["note"]:
            print(f"   note: {step['note']}")

    print("")
    print("Manual validation after deploy:")
    for item in plan["manual_validation"]:
        print(f"- {item['name']}")
        for command in item["commands"]:
            print(f"  {command}")


def _execute_plan(plan: Dict[str, Any]) -> None:
    base_env = os.environ.copy()
    shim_dir = str(DEFAULT_BASH_SHIMS)
    for index, step in enumerate(plan["steps"], start=1):
        print(f"[{index}/{len(plan['steps'])}] {step['name']}")
        env = base_env.copy()
        if step["argv"] and step["argv"][0] == "bash":
            env["PATH"] = f"{shim_dir};{env.get('PATH', '')}"
        subprocess.run(step["argv"], cwd=step["cwd"], check=True, env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or execute the current production-shaped empty platform deploy flow.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT), help="Path to the RPDB repo root")
    parser.add_argument(
        "--muxer-repo",
        default=str(DEFAULT_MUXER_RUNTIME_ROOT),
        help="Path to the RPDB muxer runtime package root",
    )
    parser.add_argument("--region", default=DEFAULT_REGION, help="AWS region to use for deploy and DynamoDB checks")
    parser.add_argument("--muxer-params", default=str(DEFAULT_MUXER_PARAMS), help="Path to the single-muxer parameter file")
    parser.add_argument("--nat-headend-params", default=str(DEFAULT_NAT_PARAMS), help="Path to the NAT head-end parameter file")
    parser.add_argument(
        "--nonnat-headend-params",
        default=str(DEFAULT_NONNAT_PARAMS),
        help="Path to the non-NAT head-end parameter file",
    )
    parser.add_argument("--muxer-stack-name", default="", help="Optional override for the muxer stack name")
    parser.add_argument("--nat-stack-name", default="", help="Optional override for the NAT head-end stack name")
    parser.add_argument("--nonnat-stack-name", default="", help="Optional override for the non-NAT head-end stack name")
    parser.add_argument("--execute", action="store_true", help="Execute the automatic steps instead of only printing the plan")
    parser.add_argument(
        "--allow-production-eip",
        action="store_true",
        help="Allow execute mode even when EipAllocationId values are populated in the imported parameter files",
    )
    parser.add_argument("--json", action="store_true", help="Print the plan as JSON")
    args = parser.parse_args()

    plan = _build_plan(args)

    if args.json:
        print(json.dumps(plan, indent=2, sort_keys=True))
    else:
        _print_plan(plan)

    if args.execute:
        _guard_execute(plan, args)
        _execute_plan(plan)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
