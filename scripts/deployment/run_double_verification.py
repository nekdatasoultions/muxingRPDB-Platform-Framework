#!/usr/bin/env python
"""Run the full repo-only pre-deploy double-verification flow for one customer."""

from __future__ import annotations

# Standard library imports for CLI parsing, JSON summary output, subprocess
# execution, and stable path handling across the framework and deployment repos.
import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

import yaml


# Run one step, print the exact command for traceability, and stop on the first
# failure so we never pretend a full verification passed when an early stage did
# not.
def _run_step(name: str, command: List[str], cwd: Path, summary: List[Dict[str, object]]) -> None:
    print(f"[{name}] {' '.join(command)}")
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    summary.append(
        {
            "name": name,
            "cwd": str(cwd),
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    )
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="" if completed.stderr.endswith("\n") else "\n")
    if completed.returncode != 0:
        raise RuntimeError(f"step failed: {name}")


# Read the customer name from the framework-side source YAML so the operator
# only has to point at the source file and environment bindings.
def _load_customer_name(source_path: Path) -> str:
    payload = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
    customer = payload.get("customer") or {}
    customer_name = customer.get("name")
    if not customer_name:
        raise ValueError(f"customer.name missing in {source_path}")
    return str(customer_name)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run framework + deployment double verification for one customer."
    )
    parser.add_argument(
        "--framework-repo",
        required=True,
        help="Path to the rpdb-framework-scaffold checkout or worktree",
    )
    parser.add_argument(
        "--deployment-repo",
        default=".",
        help="Path to the rpdb-deployment-model checkout or worktree",
    )
    parser.add_argument(
        "--customer-source",
        required=True,
        help="Framework-side customer source YAML path, absolute or relative to --framework-repo",
    )
    parser.add_argument(
        "--environment-file",
        required=True,
        help="Framework-side environment bindings YAML path, absolute or relative to --framework-repo",
    )
    parser.add_argument(
        "--baseline-dir",
        required=True,
        help="Path to the verified backup baseline directory",
    )
    parser.add_argument(
        "--operator",
        default="TBD",
        help="Operator name for generated rollout notes",
    )
    parser.add_argument(
        "--change-summary",
        default="Run repo-only RPDB double verification before any live change.",
        help="Short summary included in generated notes",
    )
    parser.add_argument(
        "--work-dir",
        help="Optional shared output root. Defaults to build\\double-verification\\<customer-name> in each repo.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the final verification report as JSON",
    )
    args = parser.parse_args()

    framework_repo = Path(args.framework_repo).resolve()
    deployment_repo = Path(args.deployment_repo).resolve()

    customer_source = Path(args.customer_source)
    if not customer_source.is_absolute():
        customer_source = (framework_repo / customer_source).resolve()

    environment_file = Path(args.environment_file)
    if not environment_file.is_absolute():
        environment_file = (framework_repo / environment_file).resolve()

    baseline_dir = Path(args.baseline_dir).resolve()
    customer_name = _load_customer_name(customer_source)

    if args.work_dir:
        shared_root = Path(args.work_dir).resolve()
        framework_root = shared_root / "framework"
        deployment_root = shared_root / "deployment"
    else:
        framework_root = framework_repo / "build" / "double-verification" / customer_name
        deployment_root = deployment_repo / "build" / "double-verification" / customer_name

    render_dir = framework_root / "render"
    handoff_dir = framework_root / "handoff"
    bound_dir = framework_root / "bound-handoff"
    bundle_dir = deployment_root / "bundle"
    headend_root = deployment_root / "headend-root"
    notes_dir = deployment_root / "notes"
    prechange_note = notes_dir / "prechange.md"
    rollback_note = notes_dir / "rollback.md"
    summary_path = deployment_root / "double-verification-summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    steps: List[Dict[str, object]] = []
    python = sys.executable

    try:
        # Framework-side validation, render, export, and environment binding.
        _run_step(
            "validate_customer_source",
            [python, "muxer/scripts/validate_customer_source.py", str(customer_source)],
            framework_repo,
            steps,
        )
        _run_step(
            "render_customer_artifacts",
            [
                python,
                "muxer/scripts/render_customer_artifacts.py",
                str(customer_source),
                "--out-dir",
                str(render_dir),
            ],
            framework_repo,
            steps,
        )
        _run_step(
            "validate_rendered_artifacts",
            [python, "muxer/scripts/validate_rendered_artifacts.py", str(render_dir)],
            framework_repo,
            steps,
        )
        _run_step(
            "validate_environment_bindings",
            [python, "muxer/scripts/validate_environment_bindings.py", str(environment_file)],
            framework_repo,
            steps,
        )
        _run_step(
            "export_customer_handoff",
            [
                python,
                "muxer/scripts/export_customer_handoff.py",
                str(customer_source),
                "--export-dir",
                str(handoff_dir),
            ],
            framework_repo,
            steps,
        )
        _run_step(
            "bind_rendered_artifacts",
            [
                python,
                "muxer/scripts/bind_rendered_artifacts.py",
                str(handoff_dir),
                "--environment-file",
                str(environment_file),
                "--out-dir",
                str(bound_dir),
            ],
            framework_repo,
            steps,
        )
        _run_step(
            "validate_bound_artifacts",
            [python, "muxer/scripts/validate_bound_artifacts.py", str(bound_dir)],
            framework_repo,
            steps,
        )

        # Deployment-side package, notes, and readiness gates.
        _run_step(
            "assemble_customer_bundle",
            [
                python,
                "scripts/packaging/assemble_customer_bundle.py",
                "--customer-name",
                customer_name,
                "--export-dir",
                str(bound_dir),
                "--bundle-dir",
                str(bundle_dir),
            ],
            deployment_repo,
            steps,
        )
        _run_step(
            "validate_customer_bundle",
            [python, "scripts/packaging/validate_customer_bundle.py", str(bundle_dir)],
            deployment_repo,
            steps,
        )
        _run_step(
            "apply_headend_customer",
            [
                python,
                "scripts/deployment/apply_headend_customer.py",
                "--bundle-dir",
                str(bundle_dir),
                "--headend-root",
                str(headend_root),
            ],
            deployment_repo,
            steps,
        )
        _run_step(
            "validate_headend_customer",
            [
                python,
                "scripts/deployment/validate_headend_customer.py",
                "--bundle-dir",
                str(bundle_dir),
                "--headend-root",
                str(headend_root),
            ],
            deployment_repo,
            steps,
        )
        _run_step(
            "remove_headend_customer",
            [
                python,
                "scripts/deployment/remove_headend_customer.py",
                "--bundle-dir",
                str(bundle_dir),
                "--headend-root",
                str(headend_root),
            ],
            deployment_repo,
            steps,
        )
        _run_step(
            "verify_backup_baseline",
            [
                python,
                "scripts/backup/verify_backup_baseline.py",
                "--baseline-dir",
                str(baseline_dir),
            ],
            deployment_repo,
            steps,
        )
        _run_step(
            "create_prechange_backup_note",
            [
                python,
                "scripts/backup/create_prechange_backup_note.py",
                "--customer-name",
                customer_name,
                "--baseline-dir",
                str(baseline_dir),
                "--change-summary",
                args.change_summary,
                "--operator",
                args.operator,
                "--out",
                str(prechange_note),
            ],
            deployment_repo,
            steps,
        )
        _run_step(
            "create_rollout_notes",
            [
                python,
                "scripts/deployment/create_rollout_notes.py",
                "--customer-name",
                customer_name,
                "--operator",
                args.operator,
                "--bundle-dir",
                str(bundle_dir),
                "--change-summary",
                args.change_summary,
                "--out-dir",
                str(notes_dir),
            ],
            deployment_repo,
            steps,
        )
        _run_step(
            "deployment_readiness_check",
            [
                python,
                "scripts/deployment/deployment_readiness_check.py",
                "--customer-name",
                customer_name,
                "--bundle-dir",
                str(bundle_dir),
                "--baseline-dir",
                str(baseline_dir),
                "--prechange-backup-note",
                str(prechange_note),
                "--rollback-notes",
                str(rollback_note),
            ],
            deployment_repo,
            steps,
        )
    except Exception as exc:
        report = {
            "customer_name": customer_name,
            "ready": False,
            "error": str(exc),
            "framework_repo": str(framework_repo),
            "deployment_repo": str(deployment_repo),
            "customer_source": str(customer_source),
            "environment_file": str(environment_file),
            "baseline_dir": str(baseline_dir),
            "steps": steps,
        }
        summary_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(f"Double verification for {customer_name}: FAILED")
            print(f"- summary: {summary_path}")
            print(f"- error: {exc}")
        return 1

    report = {
        "customer_name": customer_name,
        "ready": True,
        "framework_repo": str(framework_repo),
        "deployment_repo": str(deployment_repo),
        "customer_source": str(customer_source),
        "environment_file": str(environment_file),
        "baseline_dir": str(baseline_dir),
        "paths": {
            "render_dir": str(render_dir),
            "handoff_dir": str(handoff_dir),
            "bound_dir": str(bound_dir),
            "bundle_dir": str(bundle_dir),
            "notes_dir": str(notes_dir),
            "prechange_note": str(prechange_note),
            "rollback_note": str(rollback_note),
        },
        "steps": steps,
    }
    summary_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Double verification for {customer_name}: READY")
        print(f"- summary: {summary_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
