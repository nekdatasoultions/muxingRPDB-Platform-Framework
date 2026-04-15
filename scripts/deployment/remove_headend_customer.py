#!/usr/bin/env python
"""Remove one previously installed customer from a staged head-end root."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from headend_customer_lib import load_headend_bundle, remove_installed_headend


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove one installed customer-scoped head-end bundle.")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--bundle-dir", help="Path to the customer bundle directory")
    selector.add_argument("--customer-name", help="Customer name to remove")
    parser.add_argument(
        "--headend-root",
        required=True,
        help="Target head-end filesystem root. Use a staged root for repo-only verification or / on a target host.",
    )
    parser.add_argument("--json", action="store_true", help="Print the removal report as JSON")
    args = parser.parse_args()

    customer_name = args.customer_name
    if args.bundle_dir:
        customer_name = load_headend_bundle(Path(args.bundle_dir).resolve()).customer_name

    assert customer_name is not None
    report = remove_installed_headend(str(customer_name), Path(args.headend_root).resolve())

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Head-end customer removed: {report['customer_name']}")
        print(f"- headend root: {report['headend_root']}")
        if report["removed_paths"]:
            print(f"- removed paths: {len(report['removed_paths'])}")
        else:
            print("- nothing to remove")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
