#!/usr/bin/env python
"""Assemble the Phase 5 empty-platform readiness report."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PREPARED_DIR = REPO_ROOT / "build" / "empty-platform" / "current-prod-shape-rpdb-empty"
DEFAULT_BASELINE_DIR = REPO_ROOT / "build" / "verification-fixtures" / "pre-rpdb-baseline"


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


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT).as_posix())
    except ValueError:
        return str(path.resolve())


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the empty-platform readiness report.")
    parser.add_argument(
        "--prepared-dir",
        default=str(DEFAULT_PREPARED_DIR),
        help="Directory holding the prepared empty-platform parameter files",
    )
    parser.add_argument(
        "--baseline-dir",
        default=str(DEFAULT_BASELINE_DIR),
        help="Backup baseline directory to verify",
    )
    parser.add_argument(
        "--prepare-params",
        action="store_true",
        help="Run prepare_empty_platform_params.py before assembling the report",
    )
    parser.add_argument(
        "--check-aws",
        action="store_true",
        help="Include AWS-backed DynamoDB and head-end bootstrap checks",
    )
    parser.add_argument(
        "--verify-headends",
        action="store_true",
        help="Run verify_headend_bootstrap.py. Implies --check-aws.",
    )
    parser.add_argument(
        "--ssh-fallback-bastion-instance-id",
        help="Optional bastion instance ID for verify_headend_bootstrap.py",
    )
    parser.add_argument("--json", action="store_true", help="Print the full report as JSON")
    args = parser.parse_args()

    prepared_dir = Path(args.prepared_dir).resolve()
    muxer_params = prepared_dir / "parameters.single-muxer.us-east-1.json"
    nat_params = prepared_dir / "parameters.vpn-headend.nat.graviton-efs.us-east-1.json"
    nonnat_params = prepared_dir / "parameters.vpn-headend.non-nat.graviton-efs.us-east-1.json"

    report: dict[str, Any] = {
        "schema_version": 1,
        "action": "verify_empty_platform_readiness",
        "repo_root": str(REPO_ROOT),
        "prepared_dir": str(prepared_dir),
        "baseline_dir": str(Path(args.baseline_dir).resolve()),
        "checks": {},
        "errors": [],
        "warnings": [],
    }

    if args.prepare_params:
        code, payload, stdout, stderr = _run_json(
            [sys.executable, "scripts/platform/prepare_empty_platform_params.py"]
        )
        if code != 0 or payload is None:
            report["errors"].append(
                f"prepare_empty_platform_params.py failed: {stderr or stdout}".strip()
            )
        else:
            report["checks"]["prepared_parameters"] = payload

    missing_prepared = [
        _relative(path) for path in (muxer_params, nat_params, nonnat_params) if not path.exists()
    ]
    if missing_prepared:
        report["errors"].append("prepared parameter file(s) missing: " + ", ".join(missing_prepared))
    else:
        plan_code, plan_payload, plan_stdout, plan_stderr = _run_json(
            [
                sys.executable,
                "scripts/platform/deploy_empty_platform.py",
                "--muxer-params",
                str(muxer_params),
                "--nat-headend-params",
                str(nat_params),
                "--nonnat-headend-params",
                str(nonnat_params),
                "--json",
            ]
        )
        if plan_code != 0 or plan_payload is None:
            report["errors"].append(
                f"deploy_empty_platform.py planning failed: {plan_stderr or plan_stdout}".strip()
            )
        else:
            report["checks"]["deploy_plan"] = plan_payload

        db_command = [
            sys.executable,
            "scripts/platform/ensure_dynamodb_tables.py",
            "--muxer-params",
            str(muxer_params),
            "--nat-headend-params",
            str(nat_params),
            "--nonnat-headend-params",
            str(nonnat_params),
            "--json",
        ]
        if args.check_aws or args.verify_headends:
            db_command.append("--check-aws")
        db_code, db_payload, db_stdout, db_stderr = _run_json(db_command)
        if db_code != 0 or db_payload is None:
            report["errors"].append(
                f"ensure_dynamodb_tables.py failed: {db_stderr or db_stdout}".strip()
            )
        else:
            report["checks"]["database"] = db_payload

    backup_code, backup_payload, backup_stdout, backup_stderr = _run_json(
        [
            sys.executable,
            "scripts/backup/verify_backup_baseline.py",
            "--baseline-dir",
            str(Path(args.baseline_dir).resolve()),
            "--json",
        ]
    )
    if backup_code != 0 and backup_payload is None:
        report["errors"].append(
            f"verify_backup_baseline.py failed: {backup_stderr or backup_stdout}".strip()
        )
    else:
        report["checks"]["backup_baseline"] = backup_payload

    if args.verify_headends:
        command = [
            sys.executable,
            "scripts/platform/verify_headend_bootstrap.py",
            "--nat-params",
            str(nat_params),
            "--nonnat-params",
            str(nonnat_params),
            "--json",
        ]
        if args.ssh_fallback_bastion_instance_id:
            command.extend(
                [
                    "--ssh-fallback-bastion-instance-id",
                    args.ssh_fallback_bastion_instance_id,
                    "--allow-ssm-degraded-with-ssh-fallback",
                ]
            )
        headend_code, headend_payload, headend_stdout, headend_stderr = _run_json(command)
        if headend_code != 0 and headend_payload is None:
            report["errors"].append(
                f"verify_headend_bootstrap.py failed: {headend_stderr or headend_stdout}".strip()
            )
        else:
            report["checks"]["headend_bootstrap"] = headend_payload

    ready = not report["errors"]
    report["ready"] = ready

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Empty platform readiness: {'READY' if ready else 'BLOCKED'}")
        print(f"- prepared_dir: {prepared_dir}")
        print(f"- baseline_dir: {Path(args.baseline_dir).resolve()}")
        for error in report["errors"]:
            print(f"  error: {error}")
        for warning in report["warnings"]:
            print(f"  warning: {warning}")

    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
