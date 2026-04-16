#!/usr/bin/env python
"""Dry-run one-command RPDB customer deploy orchestrator."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MUXER_SRC = REPO_ROOT / "muxer" / "src"
if str(MUXER_SRC) not in sys.path:
    sys.path.insert(0, str(MUXER_SRC))

from muxerlib.customer_merge import load_yaml_file

PLACEHOLDER_VALUES = {
    "",
    "missing",
    "todo",
    "tbd",
    "placeholder",
    "unset",
    "none",
    "n/a",
}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _customer_name_from_request(path: Path) -> str:
    document = load_yaml_file(path)
    customer_name = str((document.get("customer") or {}).get("name") or "").strip()
    if not customer_name:
        raise ValueError(f"customer.name missing in {path}")
    return customer_name


def _run_json(command: list[str]) -> tuple[int, dict[str, Any] | None, str, str]:
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    payload = None
    if completed.stdout.strip():
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            payload = None
    return completed.returncode, payload, completed.stdout, completed.stderr


def _environment_validation(environment: str) -> tuple[int, dict[str, Any] | None, str, str]:
    return _run_json(
        [
            sys.executable,
            "scripts/customers/validate_deployment_environment.py",
            environment,
            "--json",
        ]
    )


def _validate_customer_request(customer_file: Path) -> tuple[int, str, str]:
    completed = subprocess.run(
        [
            sys.executable,
            "muxer/scripts/validate_customer_request.py",
            str(customer_file),
        ],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _blocked_customers(environment_doc: dict[str, Any]) -> set[str]:
    customer_requests = environment_doc.get("customer_requests") or {}
    return {
        str(customer).strip()
        for customer in customer_requests.get("blocked_customers") or []
        if str(customer).strip()
    }


def _target_selection(*, environment_doc: dict[str, Any], readiness: dict[str, Any]) -> dict[str, Any]:
    customer = readiness.get("customer") or {}
    dynamic_nat_t = readiness.get("dynamic_nat_t") or {}
    backend_cluster = str(customer.get("backend_cluster") or "").strip()
    customer_class = str(customer.get("customer_class") or "").strip()
    use_nat = backend_cluster == "nat" or customer_class == "nat" or bool(dynamic_nat_t.get("used"))
    headend_key = "nat" if use_nat else "non_nat"
    targets = environment_doc.get("targets") or {}
    headends = targets.get("headends") or {}
    selected_pair = headends.get(headend_key) or {}
    return {
        "mode": "dry_run",
        "muxer": targets.get("muxer"),
        "headend_family": headend_key,
        "headend_active": selected_pair.get("active"),
        "headend_standby": selected_pair.get("standby"),
        "datastores": environment_doc.get("datastores"),
        "artifacts": environment_doc.get("artifacts"),
        "backups": environment_doc.get("backups"),
    }


def _reference_is_concrete(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and text.lower() not in PLACEHOLDER_VALUES


def _resolve_repo_path(path_like: str) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def _evaluate_dry_run_gate(
    *,
    environment_doc: dict[str, Any] | None,
    target_selection: dict[str, Any] | None,
    package_report: dict[str, Any] | None,
) -> dict[str, Any]:
    errors: list[str] = []
    readiness = (package_report or {}).get("readiness") or {}
    package_paths = readiness.get("package_paths") or {}
    bundle_rel = str(package_paths.get("bundle") or "").strip()
    bundle_dir = _resolve_repo_path(bundle_rel) if bundle_rel else None
    manifest_path = bundle_dir / "manifest.txt" if bundle_dir else None
    checksum_path = bundle_dir / "sha256sums.txt" if bundle_dir else None

    bundle_checks = {
        "bundle_dir": _repo_relative(bundle_dir) if bundle_dir else None,
        "manifest_path": _repo_relative(manifest_path) if manifest_path else None,
        "checksum_path": _repo_relative(checksum_path) if checksum_path else None,
        "manifest_present": bool(manifest_path and manifest_path.exists()),
        "checksums_present": bool(checksum_path and checksum_path.exists()),
    }
    if not bundle_checks["manifest_present"]:
        errors.append("bundle manifest is missing")
    if not bundle_checks["checksums_present"]:
        errors.append("bundle checksums are missing")

    backups = ((environment_doc or {}).get("backups") or {})
    selected_family = str((target_selection or {}).get("headend_family") or "").strip()
    selected_headend_backup_key = "nat_headend" if selected_family == "nat" else "non_nat_headend"
    backup_refs = {
        "baseline_root": backups.get("baseline_root"),
        "muxer": backups.get("muxer"),
        "selected_headend": backups.get(selected_headend_backup_key),
        "selected_headend_key": selected_headend_backup_key,
    }
    backup_status = {
        key: _reference_is_concrete(value)
        for key, value in backup_refs.items()
        if key != "selected_headend_key"
    }
    for key, present in backup_status.items():
        if not present:
            errors.append(f"backup reference missing or placeholder for {key}")

    owners = ((environment_doc or {}).get("owners") or {})
    owner_status = {
        "validation": _reference_is_concrete(owners.get("validation")),
        "rollback": _reference_is_concrete(owners.get("rollback")),
    }
    for key, present in owner_status.items():
        if not present:
            errors.append(f"owner reference missing for {key}")

    environment_live_apply = (((environment_doc or {}).get("environment") or {}).get("live_apply") or {})
    allow_live_apply_now = bool(environment_live_apply.get("enabled")) and False
    live_apply_reasons = ["Phase 3 remains dry-run only"]
    if not bool(environment_live_apply.get("enabled")):
        live_apply_reasons.append("environment live_apply.enabled is false")

    status = "dry_run_ready" if not errors else "blocked"
    return {
        "status": status,
        "errors": errors,
        "bundle_checks": bundle_checks,
        "backup_refs": backup_refs,
        "backup_status": backup_status,
        "owners": {
            "validation": owners.get("validation"),
            "rollback": owners.get("rollback"),
        },
        "owner_status": owner_status,
        "allow_live_apply_now": allow_live_apply_now,
        "live_apply_reasons": live_apply_reasons,
    }


def _build_execution_plan(
    *,
    status: str,
    errors: list[str],
    customer_name: str,
    customer_file: Path,
    environment_ref: str,
    env_validation: dict[str, Any] | None,
    environment_doc: dict[str, Any] | None,
    observation: Path | None,
    deploy_dir: Path,
    package_report: dict[str, Any] | None,
    target_selection: dict[str, Any] | None,
    dry_run_gate: dict[str, Any] | None,
) -> dict[str, Any]:
    readiness = (package_report or {}).get("readiness") or {}
    return {
        "schema_version": 1,
        "action": "deploy_customer",
        "phase": "phase3_target_resolution_and_backup_gate",
        "status": status,
        "dry_run": True,
        "approved": False,
        "live_apply": False,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "customer_name": customer_name,
        "errors": errors,
        "inputs": {
            "customer_file": _repo_relative(customer_file),
            "environment": environment_ref,
            "environment_file": (env_validation or {}).get("environment_file"),
            "observation": _repo_relative(observation) if observation else None,
        },
        "environment": {
            "name": (environment_doc or {}).get("environment", {}).get("name"),
            "validation": env_validation,
        },
        "package": {
            "status": (package_report or {}).get("status"),
            "ready_for_review": (package_report or {}).get("ready_for_review"),
            "package_dir": (package_report or {}).get("package_dir"),
            "readiness_path": (package_report or {}).get("readiness_path"),
            "run_report_path": (package_report or {}).get("run_report_path"),
            "customer": readiness.get("customer"),
            "allocated_resources": readiness.get("allocated_resources"),
            "dynamic_nat_t": readiness.get("dynamic_nat_t"),
        },
        "selected_targets": target_selection,
        "dry_run_gate": dry_run_gate,
        "touch_plan": {
            "muxer": ((target_selection or {}).get("muxer") or {}).get("name"),
            "headend_family": (target_selection or {}).get("headend_family"),
            "headend_active": ((target_selection or {}).get("headend_active") or {}).get("name"),
            "headend_standby": ((target_selection or {}).get("headend_standby") or {}).get("name"),
            "customer_sot_table": (((target_selection or {}).get("datastores") or {}).get("customer_sot_table")),
            "allocation_table": (((target_selection or {}).get("datastores") or {}).get("allocation_table")),
            "artifact_bucket": (((target_selection or {}).get("artifacts") or {}).get("bucket")),
            "artifact_prefix": (((target_selection or {}).get("artifacts") or {}).get("prefix")),
            "bundle_dir": (((dry_run_gate or {}).get("bundle_checks") or {}).get("bundle_dir")),
        },
        "execution_order": [
            "validate_customer_request",
            "validate_deployment_environment",
            "enforce_blocked_customers",
            "provision_repo_only_package",
            "resolve_dry_run_targets",
            "validate_bundle_manifest_and_checksums",
            "validate_backup_references",
            "validate_rollout_owners",
            "write_execution_plan",
        ],
        "live_gate": {
            "status": (dry_run_gate or {}).get("status") or "blocked",
            "approve_supported": False,
            "allow_live_apply_now": False,
            "reasons": (dry_run_gate or {}).get("live_apply_reasons") or ["Phase 3 remains dry-run only"],
            "no_live_nodes_touched": True,
            "no_aws_calls": True,
            "no_dynamodb_writes": True,
        },
        "artifacts": {
            "deploy_dir": _repo_relative(deploy_dir),
            "execution_plan": _repo_relative(deploy_dir / "execution-plan.json"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run one-command RPDB customer deploy orchestrator.")
    parser.add_argument("--customer-file", required=True, help="Customer request YAML")
    parser.add_argument("--environment", required=True, help="Deployment environment name or file")
    parser.add_argument("--observation", help="Optional NAT-T observation JSON/YAML")
    parser.add_argument("--out-dir", help="Output directory for execution plan and package")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run only; this is the Phase 2 default")
    parser.add_argument("--approve", action="store_true", help="Reserved for a later live-apply phase")
    parser.add_argument("--json", action="store_true", help="Print the execution plan as JSON")
    args = parser.parse_args()

    customer_file = Path(args.customer_file).resolve()
    observation = Path(args.observation).resolve() if args.observation else None
    customer_name = _customer_name_from_request(customer_file)
    deploy_dir = (
        Path(args.out_dir).resolve()
        if args.out_dir
        else (REPO_ROOT / "build" / "customer-deploy" / customer_name).resolve()
    )
    package_dir = deploy_dir / "package"
    errors: list[str] = []
    dry_run_gate = None

    if args.approve:
        errors.append("--approve is not enabled in Phase 3; live apply remains disabled")

    request_code, request_stdout, request_stderr = _validate_customer_request(customer_file)
    if request_code != 0:
        errors.append(f"customer request validation failed: {request_stderr or request_stdout}".strip())

    env_code, env_validation, env_stdout, env_stderr = _environment_validation(args.environment)
    environment_doc = None
    if env_code != 0 or not env_validation or not env_validation.get("valid"):
        errors.append(f"deployment environment validation failed: {env_stderr or env_stdout}".strip())
    else:
        environment_doc = load_yaml_file(Path(str(env_validation["environment_file"])))

    if environment_doc and customer_name in _blocked_customers(environment_doc):
        errors.append(f"customer {customer_name} is blocked by deployment environment policy")

    package_report = None
    target_selection = None
    if not errors:
        command = [
            sys.executable,
            "muxer/scripts/provision_customer_end_to_end.py",
            str(customer_file),
            "--out-dir",
            str(package_dir),
            "--json",
        ]
        if observation:
            command.extend(["--observation", str(observation)])
        package_code, package_report, package_stdout, package_stderr = _run_json(command)
        if package_code != 0 or not package_report or package_report.get("status") != "ready_for_review":
            errors.append(f"repo-only package provisioning failed: {package_stderr or package_stdout}".strip())
        else:
            target_selection = _target_selection(
                environment_doc=environment_doc or {},
                readiness=package_report.get("readiness") or {},
            )
            dry_run_gate = _evaluate_dry_run_gate(
                environment_doc=environment_doc,
                target_selection=target_selection,
                package_report=package_report,
            )
            errors.extend(dry_run_gate.get("errors") or [])

    status = "dry_run_ready" if not errors else "blocked"
    execution_plan = _build_execution_plan(
        status=status,
        errors=errors,
        customer_name=customer_name,
        customer_file=customer_file,
        environment_ref=args.environment,
        env_validation=env_validation,
        environment_doc=environment_doc,
        observation=observation,
        deploy_dir=deploy_dir,
        package_report=package_report,
        target_selection=target_selection,
        dry_run_gate=dry_run_gate,
    )
    _write_json(deploy_dir / "execution-plan.json", execution_plan)

    if args.json:
        print(json.dumps(execution_plan, indent=2, sort_keys=True))
    else:
        print(f"Customer deploy dry-run: {status}")
        print(f"- customer: {customer_name}")
        print(f"- execution plan: {_repo_relative(deploy_dir / 'execution-plan.json')}")
        for error in errors:
            print(f"  error: {error}")

    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
