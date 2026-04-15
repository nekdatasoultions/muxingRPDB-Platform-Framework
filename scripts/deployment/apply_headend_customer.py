#!/usr/bin/env python
"""Install one customer's head-end artifacts into a target head-end root."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from headend_customer_lib import install_headend_bundle, validate_headend_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Install one customer-scoped head-end bundle.")
    parser.add_argument("--bundle-dir", required=True, help="Path to the customer bundle directory")
    parser.add_argument(
        "--headend-root",
        required=True,
        help="Target head-end filesystem root. Use a staged root for repo-only verification or / on a target host.",
    )
    parser.add_argument("--json", action="store_true", help="Print the install report as JSON")
    args = parser.parse_args()

    bundle_dir = Path(args.bundle_dir).resolve()
    headend_root = Path(args.headend_root).resolve()

    validation = validate_headend_bundle(bundle_dir)
    if not validation["valid"]:
        if args.json:
            print(json.dumps(validation, indent=2, sort_keys=True))
        else:
            print("Head-end bundle installability: INVALID")
            for error in validation["errors"]:
                print(f"  error: {error}")
        return 1

    report = install_headend_bundle(bundle_dir, headend_root)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Head-end customer installed: {report['customer_name']}")
        print(f"- headend root: {report['headend_root']}")
        print(f"- swanctl conf: {report['swanctl_conf']}")
        print(f"- apply script: {report['master_apply_script']}")
        print(f"- remove script: {report['master_remove_script']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
