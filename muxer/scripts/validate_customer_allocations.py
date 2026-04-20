#!/usr/bin/env python
"""Validate exclusive RPDB allocation namespaces across customer sources."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muxerlib.allocation import load_customer_source_docs, validate_customer_allocations


def main() -> int:
    repo_muxer_dir = Path(__file__).resolve().parents[1]

    parser = argparse.ArgumentParser(description="Validate allocation collisions across RPDB customer sources.")
    parser.add_argument(
        "--source-root",
        action="append",
        default=[],
        help="Customer source root directory or customer.yaml file. Can be specified multiple times.",
    )
    parser.add_argument("--json", action="store_true", help="Print the report as JSON")
    args = parser.parse_args()

    roots = args.source_root or [str(repo_muxer_dir / "config" / "customer-sources")]
    source_docs = load_customer_source_docs(*roots)
    report = validate_customer_allocations(source_docs)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Validated allocations across {report['customer_count']} customer source(s)")
        print(f"Exclusive resources checked: {', '.join(report['exclusive_resources_checked'])}")
        print(f"Allocation collisions: {len(report['collisions'])}")
        if report["backend_assignment_counts"]:
            print(
                "Backend assignment usage: "
                + ", ".join(f"{name}={count}" for name, count in report["backend_assignment_counts"].items())
            )

    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
