#!/usr/bin/env python
"""Remove one previously installed customer from a staged backend root."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend_customer_lib import load_backend_package, remove_installed_backend


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove one installed customer-scoped backend package.")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--package-dir", help="Path to the customer package directory")
    selector.add_argument("--customer-name", help="Customer name to remove")
    parser.add_argument(
        "--backend-root",
        required=True,
        help="Target backend filesystem root. Use a staged root for repo-only verification or / on a target host.",
    )
    parser.add_argument("--json", action="store_true", help="Print the removal report as JSON")
    args = parser.parse_args()

    customer_name = args.customer_name
    if args.package_dir:
        customer_name = load_backend_package(Path(args.package_dir).resolve()).customer_name

    assert customer_name is not None
    report = remove_installed_backend(str(customer_name), Path(args.backend_root).resolve())

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Backend customer removed: {report['customer_name']}")
        print(f"- backend root: {report['backend_root']}")
        if report["removed_paths"]:
            print(f"- removed paths: {len(report['removed_paths'])}")
        else:
            print("- nothing to remove")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
