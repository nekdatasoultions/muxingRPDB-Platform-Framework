#!/usr/bin/env python
"""Install one customer's muxer artifacts into a target muxer root."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from muxer_customer_lib import install_muxer_bundle, validate_muxer_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Install one customer-scoped muxer bundle.")
    parser.add_argument("--bundle-dir", required=True, help="Path to the customer bundle directory")
    parser.add_argument(
        "--muxer-root",
        required=True,
        help="Target muxer filesystem root. Use a staged root for repo-only verification or / on a target host.",
    )
    parser.add_argument("--json", action="store_true", help="Print the install report as JSON")
    args = parser.parse_args()

    bundle_dir = Path(args.bundle_dir).resolve()
    muxer_root = Path(args.muxer_root).resolve()

    validation = validate_muxer_bundle(bundle_dir)
    if not validation["valid"]:
        if args.json:
            print(json.dumps(validation, indent=2, sort_keys=True))
        else:
            print("Muxer bundle installability: INVALID")
            for error in validation["errors"]:
                print(f"  error: {error}")
        return 1

    report = install_muxer_bundle(bundle_dir, muxer_root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Muxer customer installed: {report['customer_name']}")
        print(f"- muxer root: {report['muxer_root']}")
        print(f"- customer module: {report['customer_module']}")
        print(f"- apply script: {report['master_apply_script']}")
        print(f"- remove script: {report['master_remove_script']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
