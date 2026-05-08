#!/usr/bin/env python
"""Install one customer's SmartConnect artifacts into a target SmartConnect root."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from smartconnect_customer_lib import install_smartconnect_bundle, validate_smartconnect_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Install one customer-scoped SmartConnect bundle.")
    parser.add_argument("--bundle-dir", required=True, help="Path to the customer bundle directory")
    parser.add_argument(
        "--smartconnect-root",
        required=True,
        help="Target SmartConnect filesystem root. Use a staged root for repo-only verification or / on a target host.",
    )
    parser.add_argument("--json", action="store_true", help="Print the install report as JSON")
    args = parser.parse_args()

    bundle_dir = Path(args.bundle_dir).resolve()
    smartconnect_root = Path(args.smartconnect_root).resolve()

    validation = validate_smartconnect_bundle(bundle_dir)
    if not validation["valid"]:
        if args.json:
            print(json.dumps(validation, indent=2, sort_keys=True))
        else:
            print("SmartConnect bundle installability: INVALID")
            for error in validation["errors"]:
                print(f"  error: {error}")
        return 1

    report = install_smartconnect_bundle(bundle_dir, smartconnect_root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"SmartConnect customer installed: {report['customer_name']}")
        print(f"- smartconnect root: {report['smartconnect_root']}")
        print(f"- apply script: {report['master_apply_script']}")
        print(f"- remove script: {report['master_remove_script']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
