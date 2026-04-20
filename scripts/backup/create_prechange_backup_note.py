#!/usr/bin/env python
"""Create a rollout-specific pre-change backup note from the RPDB baseline."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_SNAPSHOTS = [
    "ip-172-31-34-89-20260413T203353Z",
    "ip-172-31-40-221-20260413T203353Z",
    "ip-172-31-141-221-20260413T203353Z",
    "ip-172-31-40-220-20260413T203353Z",
    "ip-172-31-141-220-20260413T203353Z",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a rollout-specific pre-change backup note.")
    parser.add_argument("--customer-name", required=True, help="Customer name for the rollout")
    parser.add_argument(
        "--baseline-dir",
        default="/Shared/backups/pre-rpdb-baseline",
        help="Path to the shared backup baseline directory",
    )
    parser.add_argument(
        "--snapshot",
        action="append",
        dest="snapshots",
        help="Snapshot directory name to reference. Can be supplied multiple times.",
    )
    parser.add_argument(
        "--target-node",
        action="append",
        dest="target_nodes",
        help="Target node for this rollout. Can be supplied multiple times.",
    )
    parser.add_argument(
        "--change-summary",
        default="Document rollout scope before any live RPDB change.",
        help="Short summary of the intended change",
    )
    parser.add_argument(
        "--operator",
        default="TBD",
        help="Operator or owner for this rollout",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Path to write the pre-change backup note",
    )
    args = parser.parse_args()

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshots = args.snapshots or DEFAULT_SNAPSHOTS
    target_nodes = args.target_nodes or ["TBD"]
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# Pre-Change Backup Note: {args.customer_name}",
        "",
        f"- Generated at: {timestamp}",
        f"- Customer: {args.customer_name}",
        f"- Operator: {args.operator}",
        f"- Change summary: {args.change_summary}",
        f"- Shared baseline dir: {args.baseline_dir}",
        "",
        "## Target Nodes",
        "",
    ]
    for node in target_nodes:
        lines.append(f"- {node}")

    lines.extend(
        [
            "",
            "## Referenced Baseline Snapshots",
            "",
        ]
    )
    for snapshot in snapshots:
        lines.append(f"- {snapshot}")

    lines.extend(
        [
            "",
            "## Purpose-Built Pre-Change Backup",
            "",
            "- Status: TODO",
            "- Storage path: TODO",
            "- Manifest verified: TODO",
            "- Checksums verified: TODO",
            "",
            "## Runtime Areas Expected To Change",
            "",
            "- TODO: muxer artifacts",
            "- TODO: head-end artifacts",
            "- TODO: services or routes that may need restore",
            "",
            "## Rollback Reference",
            "",
            "- Rollback note path: TODO",
            "- Rollback operator: TODO",
        ]
    )

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Pre-change backup note written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
