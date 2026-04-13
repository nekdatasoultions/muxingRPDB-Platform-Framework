#!/usr/bin/env python
"""Run a deployment readiness check for one customer-scoped rollout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

DEFAULT_BASELINE_DIR = "/Shared/backups/pre-rpdb-baseline"
DEFAULT_REQUIRED_SNAPSHOTS = [
    "ip-172-31-34-89-20260413T203353Z",
    "ip-172-31-40-221-20260413T203353Z",
    "ip-172-31-141-221-20260413T203353Z",
    "ip-172-31-40-220-20260413T203353Z",
    "ip-172-31-141-220-20260413T203353Z",
]


def _check_bundle(bundle_dir: Path) -> List[str]:
    errors: List[str] = []
    if not bundle_dir.exists():
        return [f"bundle directory not found: {bundle_dir}"]
    for relative_name in ("manifest.txt", "sha256sums.txt"):
        if not (bundle_dir / relative_name).exists():
            errors.append(f"bundle missing {relative_name}")
    for relative_name in ("customer", "muxer", "headend"):
        if not (bundle_dir / relative_name).is_dir():
            errors.append(f"bundle missing directory {relative_name}/")
    return errors


def _check_backups(baseline_dir: Path, snapshots: List[str]) -> List[str]:
    errors: List[str] = []
    if not baseline_dir.exists():
        return [f"baseline directory not found: {baseline_dir}"]
    for snapshot_name in snapshots:
        snapshot_dir = baseline_dir / snapshot_name
        if not snapshot_dir.exists():
            errors.append(f"missing snapshot: {snapshot_name}")
            continue
        for relative_name in ("manifest.txt", "sha256sums.txt"):
            if not (snapshot_dir / relative_name).exists():
                errors.append(f"snapshot {snapshot_name} missing {relative_name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether one customer rollout is ready to deploy.")
    parser.add_argument("--customer-name", required=True, help="Customer name for the rollout")
    parser.add_argument(
        "--bundle-dir",
        required=True,
        help="Path to the customer-scoped bundle directory",
    )
    parser.add_argument(
        "--baseline-dir",
        default=DEFAULT_BASELINE_DIR,
        help="Path to the shared backup baseline directory",
    )
    parser.add_argument(
        "--required-snapshot",
        action="append",
        dest="required_snapshots",
        help="Explicit baseline snapshot directory name to require. Can be supplied multiple times.",
    )
    parser.add_argument(
        "--prechange-backup-note",
        help="Optional path to rollout-specific pre-change notes or inventory",
    )
    parser.add_argument(
        "--rollback-notes",
        help="Optional path to rollout-specific rollback notes",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the readiness report as JSON",
    )
    args = parser.parse_args()

    bundle_dir = Path(args.bundle_dir).resolve()
    baseline_dir = Path(args.baseline_dir)
    required_snapshots = args.required_snapshots or DEFAULT_REQUIRED_SNAPSHOTS

    report = {
        "customer_name": args.customer_name,
        "bundle_dir": str(bundle_dir),
        "baseline_dir": str(baseline_dir),
        "required_snapshots": required_snapshots,
        "errors": [],
        "warnings": [],
    }

    report["errors"].extend(_check_bundle(bundle_dir))
    report["errors"].extend(_check_backups(baseline_dir, required_snapshots))

    if args.prechange_backup_note:
        prechange_path = Path(args.prechange_backup_note).resolve()
        if not prechange_path.exists():
            report["errors"].append(f"pre-change note not found: {prechange_path}")
    else:
        report["warnings"].append("no rollout-specific pre-change note supplied")

    if args.rollback_notes:
        rollback_path = Path(args.rollback_notes).resolve()
        if not rollback_path.exists():
            report["errors"].append(f"rollback notes not found: {rollback_path}")
    else:
        report["warnings"].append("no rollout-specific rollback notes supplied")

    report["ready"] = not report["errors"]

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Deployment readiness for {args.customer_name}: {'READY' if report['ready'] else 'NOT READY'}")
        print(f"- bundle: {bundle_dir}")
        print(f"- baseline: {baseline_dir}")
        if report["errors"]:
            for error in report["errors"]:
                print(f"  error: {error}")
        if report["warnings"]:
            for warning in report["warnings"]:
                print(f"  warning: {warning}")

    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
