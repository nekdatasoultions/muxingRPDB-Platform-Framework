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
) -> dict[str, Any]:
    readiness = (package_report or {}).get("readiness") or {}
    return {
        "schema_version": 1,
        "action": "deploy_customer",
        "phase": "phase2_dry_run_orchestrator",
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
        "execution_order": [
            "validate_customer_request",
            "validate_deployment_environment",
            "enforce_blocked_customers",
            "provision_repo_only_package",
            "resolve_dry_run_targets",
            "write_execution_plan",
        ],
        "live_gate": {
            "status": "disabled_in_phase2",
            "approve_supported": False,
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

    if args.approve:
        errors.append("--approve is not enabled in Phase 2; live apply remains disabled")

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
