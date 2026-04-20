#!/usr/bin/env python
"""Verify that the RPDB backup baseline exists and is structurally usable."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

DEFAULT_BASELINE_DIR = "/Shared/backups/pre-rpdb-baseline"

DEFAULT_SNAPSHOTS = {
    "muxer": "ip-172-31-34-89-20260413T203353Z",
    "nat_headend_a": "ip-172-31-40-221-20260413T203353Z",
    "nat_headend_b": "ip-172-31-141-221-20260413T203353Z",
    "nonnat_headend_a": "ip-172-31-40-220-20260413T203353Z",
    "nonnat_headend_b": "ip-172-31-141-220-20260413T203353Z",
}

ROOT_REQUIRED_FILES = [
    "manifest.txt",
    "sha256sums.txt",
    "ip-addr.txt",
    "ip-rule.txt",
    "ip-route-all.txt",
    "ip-link-detail.txt",
    "iptables-save.txt",
    "nft-ruleset.txt",
    "conntrack-stats.txt",
    "ip-xfrm-state.txt",
    "ip-xfrm-policy.txt",
    "systemctl-list-units.txt",
]


def _snapshot_report(snapshot_dir: Path) -> Dict[str, object]:
    missing: List[str] = []
    warnings: List[str] = []

    if not snapshot_dir.exists():
        return {
            "exists": False,
            "missing": ["snapshot directory"],
            "warnings": [],
        }

    for relative_name in ROOT_REQUIRED_FILES:
        if not (snapshot_dir / relative_name).exists():
            missing.append(relative_name)

    config_dir = snapshot_dir / "config"
    if not config_dir.exists():
        missing.append("config/")
    else:
        config_candidates = [
            config_dir / "muxer-node-config.tgz",
            config_dir / "vpn-headend-node-config.tgz",
        ]
        if not any(candidate.exists() for candidate in config_candidates):
            missing.append("config archive (*.tgz)")

    manifest_path = snapshot_dir / "manifest.txt"
    if manifest_path.exists():
        manifest_text = manifest_path.read_text(encoding="utf-8", errors="replace")
        if "config" not in manifest_text:
            warnings.append("manifest.txt does not mention config artifacts")
    else:
        warnings.append("manifest.txt unavailable for content inspection")

    return {
        "exists": True,
        "missing": missing,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the RPDB backup baseline.")
    parser.add_argument(
        "--baseline-dir",
        default=DEFAULT_BASELINE_DIR,
        help="Path to the shared backup baseline directory",
    )
    parser.add_argument(
        "--snapshot",
        action="append",
        dest="snapshots",
        help="Explicit snapshot directory name to require. Can be supplied multiple times.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full report as JSON",
    )
    args = parser.parse_args()

    baseline_dir = Path(args.baseline_dir)
    snapshot_names = args.snapshots or list(DEFAULT_SNAPSHOTS.values())

    report = {
        "baseline_dir": str(baseline_dir),
        "snapshots": {},
    }
    failures = 0

    for snapshot_name in snapshot_names:
        snapshot_dir = baseline_dir / snapshot_name
        snapshot_report = _snapshot_report(snapshot_dir)
        report["snapshots"][snapshot_name] = snapshot_report
        if not snapshot_report["exists"] or snapshot_report["missing"]:
            failures += 1

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Backup baseline: {baseline_dir}")
        for snapshot_name, snapshot_report in report["snapshots"].items():
            status = "OK" if snapshot_report["exists"] and not snapshot_report["missing"] else "FAIL"
            print(f"- {snapshot_name}: {status}")
            for missing_item in snapshot_report["missing"]:
                print(f"  missing: {missing_item}")
            for warning in snapshot_report["warnings"]:
                print(f"  warning: {warning}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
