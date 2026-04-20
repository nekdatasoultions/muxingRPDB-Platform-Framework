#!/usr/bin/env python
"""Create rollout and rollback note templates for one customer-scoped change."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path


def _write_rollout_note(path: Path, customer_name: str, operator: str, bundle_dir: str, summary: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"# Rollout Note: {customer_name}",
        "",
        f"- Generated at: {timestamp}",
        f"- Customer: {customer_name}",
        f"- Operator: {operator}",
        f"- Bundle dir: {bundle_dir}",
        f"- Change summary: {summary}",
        "",
        "## Preconditions",
        "",
        "- [ ] Customer source validated",
        "- [ ] Bundle manifest/checksums generated",
        "- [ ] Backup baseline verified",
        "- [ ] Purpose-built pre-change backup completed",
        "- [ ] Rollback note reviewed",
        "",
        "## Apply Plan",
        "",
        "1. TODO: muxer apply steps",
        "2. TODO: active head-end apply steps",
        "3. TODO: standby head-end staging steps",
        "",
        "## Validation Plan",
        "",
        "- TODO: control-plane checks",
        "- TODO: dataplane checks",
        "- TODO: customer-specific packet/counter checks",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_rollback_note(path: Path, customer_name: str, operator: str, summary: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"# Rollback Note: {customer_name}",
        "",
        f"- Generated at: {timestamp}",
        f"- Customer: {customer_name}",
        f"- Rollback operator: {operator}",
        f"- Change summary: {summary}",
        "",
        "## Rollback Triggers",
        "",
        "- TODO: control-plane failure condition",
        "- TODO: dataplane failure condition",
        "- TODO: validation timeout condition",
        "",
        "## Restore Inputs",
        "",
        "- Shared baseline snapshot(s): TODO",
        "- Purpose-built pre-change backup path: TODO",
        "- Customer bundle path: TODO",
        "",
        "## Rollback Steps",
        "",
        "1. TODO: stop or revert customer-scoped apply",
        "2. TODO: restore prior muxer/customer artifacts",
        "3. TODO: restore head-end state if required",
        "4. TODO: re-run validation against prior state",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create rollout and rollback note templates.")
    parser.add_argument("--customer-name", required=True, help="Customer name for the rollout")
    parser.add_argument("--operator", default="TBD", help="Operator or owner for this rollout")
    parser.add_argument("--bundle-dir", default="TBD", help="Customer-scoped bundle directory")
    parser.add_argument(
        "--change-summary",
        default="Document rollout and rollback steps before live RPDB apply.",
        help="Short summary of the intended change",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        help="Directory where rollout.md and rollback.md should be created",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    rollout_path = out_dir / "rollout.md"
    rollback_path = out_dir / "rollback.md"

    _write_rollout_note(rollout_path, args.customer_name, args.operator, args.bundle_dir, args.change_summary)
    _write_rollback_note(rollback_path, args.customer_name, args.operator, args.change_summary)

    print(f"Rollout note written: {rollout_path}")
    print(f"Rollback note written: {rollback_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
