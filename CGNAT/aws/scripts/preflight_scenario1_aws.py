from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _framework_src_root() -> Path:
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent.parent / "framework" / "src"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_package(package_dir: Path) -> dict[str, Any]:
    return {
        "manifest": _load_json(package_dir / "package-manifest.json"),
        "cgnat_head_end": _load_json(package_dir / "cgnat-head-end.json"),
        "cgnat_isp_head_end": _load_json(package_dir / "cgnat-isp-head-end.json"),
        "dependencies": _load_json(package_dir / "dependencies.json"),
        "deployment_order": _load_json(package_dir / "deployment-order.json"),
    }


def _aws_json(args: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        ["aws", *args, "--output", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"AWS CLI command failed: {' '.join(args)}\n{completed.stderr.strip()}")
    stdout = completed.stdout.strip()
    return json.loads(stdout) if stdout else {}


def _collect_inventory(package: dict[str, Any]) -> dict[str, Any]:
    region = package["dependencies"]["aws"]["region"]
    head_end = package["cgnat_head_end"]
    isp_head_end = package["cgnat_isp_head_end"]

    subnet_ids = [
        head_end["subnet_id"],
        isp_head_end["subnets"]["transit_subnet_id"],
        isp_head_end["subnets"]["customer_subnet_id"],
    ]
    security_group_ids = sorted(set(head_end["security_group_ids"] + isp_head_end["security_group_ids"]))
    image_ids = sorted({head_end["ami_id"], isp_head_end["ami_id"]})
    key_names = sorted({name for name in [head_end.get("key_pair_name"), isp_head_end.get("key_pair_name")] if name})
    instance_profiles = sorted(
        {
            head_end["iam_instance_profile"],
            isp_head_end["iam_instance_profile"],
        }
    )

    inventory: dict[str, Any] = {
        "sts_identity": _aws_json(["--region", region, "sts", "get-caller-identity"]),
        "subnets": _aws_json(["--region", region, "ec2", "describe-subnets", "--subnet-ids", *subnet_ids]).get("Subnets", []),
        "security_groups": _aws_json(
            ["--region", region, "ec2", "describe-security-groups", "--group-ids", *security_group_ids]
        ).get("SecurityGroups", []),
        "images": _aws_json(["--region", region, "ec2", "describe-images", "--image-ids", *image_ids]).get("Images", []),
        "instance_profiles": [],
        "key_pairs": [],
        "addresses": [],
    }

    for instance_profile in instance_profiles:
        profile = _aws_json(["iam", "get-instance-profile", "--instance-profile-name", instance_profile])
        inventory["instance_profiles"].append(profile["InstanceProfile"]["InstanceProfileName"])

    if key_names:
        key_pairs = _aws_json(["--region", region, "ec2", "describe-key-pairs", "--key-names", *key_names]).get("KeyPairs", [])
        inventory["key_pairs"] = [entry["KeyName"] for entry in key_pairs]

    allocation_ids: list[str] = []
    if head_end.get("public_eip_strategy") == "existing_allocation" and head_end.get("public_eip_allocation_id"):
        allocation_ids.append(head_end["public_eip_allocation_id"])
    if isp_head_end.get("public_eip_strategy") == "existing_allocation" and isp_head_end.get("public_eip_allocation_id"):
        allocation_ids.append(isp_head_end["public_eip_allocation_id"])
    if allocation_ids:
        inventory["addresses"] = _aws_json(
            ["--region", region, "ec2", "describe-addresses", "--allocation-ids", *allocation_ids]
        ).get("Addresses", [])

    return inventory


def _render_readme(result: dict[str, Any]) -> str:
    status = "READY" if result["ready_for_live_apply"] else "NOT_READY"
    return "\n".join(
        [
            "# Scenario 1 AWS Live Preflight",
            "",
            f"- Service ID: `{result['service_id']}`",
            f"- Environment: `{result['environment_name']}`",
            f"- Live apply readiness: `{status}`",
            "",
            "## Notes",
            "",
            "- This preflight checks the real AWS environment against the rendered AWS package.",
            "- It does not create or modify infrastructure.",
            "- Treat `hard_no_go` findings as true stop conditions for live apply.",
            "",
        ]
    )


def main() -> int:
    sys.path.insert(0, str(_framework_src_root()))

    from cgnat.aws_preflight import analyze_aws_inventory, blocking_issue_count
    from cgnat.bundle import dump_json, dump_text, ensure_path_within_cgnat

    parser = argparse.ArgumentParser(description="Run a live AWS preflight for the rendered Scenario 1 AWS package.")
    parser.add_argument("package_dir", help="Path to the rendered AWS package directory.")
    parser.add_argument("output_dir", help="Directory to write the live preflight artifacts.")
    args = parser.parse_args()

    package_dir = Path(args.package_dir).resolve()
    output_dir = ensure_path_within_cgnat(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    package = _load_package(package_dir)
    inventory = _collect_inventory(package)
    result = analyze_aws_inventory(package, inventory)

    dump_json(output_dir / "preflight-result.json", result)
    dump_json(output_dir / "preflight-issues.json", {"issues": result["issues"]})
    dump_json(
        output_dir / "preflight-readiness.json",
        {
            "ready_for_live_apply": result["ready_for_live_apply"],
            "blocking_issue_count": blocking_issue_count(result["issues"]),
        },
    )
    dump_text(output_dir / "README.md", _render_readme(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
