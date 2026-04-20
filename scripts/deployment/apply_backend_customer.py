#!/usr/bin/env python
"""Install one customer's backend payload into a staged backend root."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend_customer_lib import install_backend_package, validate_backend_package


def main() -> int:
    parser = argparse.ArgumentParser(description="Install one customer-scoped backend package.")
    parser.add_argument("--package-dir", required=True, help="Path to the customer package directory")
    parser.add_argument(
        "--backend-root",
        required=True,
        help="Target backend filesystem root. Use a staged root for repo-only verification or / on a target host.",
    )
    parser.add_argument("--json", action="store_true", help="Print the install report as JSON")
    args = parser.parse_args()

    package_dir = Path(args.package_dir).resolve()
    backend_root = Path(args.backend_root).resolve()

    validation = validate_backend_package(package_dir)
    if not validation["valid"]:
        if args.json:
            print(json.dumps(validation, indent=2, sort_keys=True))
        else:
            print("Backend package installability: INVALID")
            for error in validation["errors"]:
                print(f"  error: {error}")
        return 1

    report = install_backend_package(package_dir, backend_root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Backend customer installed: {report['customer_name']}")
        print(f"- backend root: {report['backend_root']}")
        print(f"- customer root: {report['customer_root']}")
        print(f"- allocation root: {report['allocation_root']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
