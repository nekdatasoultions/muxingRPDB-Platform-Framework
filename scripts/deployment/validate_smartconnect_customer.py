#!/usr/bin/env python
"""Validate one customer-scoped SmartConnect bundle and optional staged install root."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from smartconnect_customer_lib import validate_installed_smartconnect, validate_smartconnect_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate one customer-scoped SmartConnect bundle.")
    parser.add_argument("--bundle-dir", required=True, help="Path to the customer bundle directory")
    parser.add_argument(
        "--smartconnect-root",
        help="Optional staged SmartConnect root to validate after apply_smartconnect_customer.py runs",
    )
    parser.add_argument("--json", action="store_true", help="Print the validation report as JSON")
    args = parser.parse_args()

    bundle_dir = Path(args.bundle_dir).resolve()
    report = (
        validate_installed_smartconnect(bundle_dir, Path(args.smartconnect_root).resolve())
        if args.smartconnect_root
        else validate_smartconnect_bundle(bundle_dir)
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"SmartConnect customer validation: {'VALID' if report['valid'] else 'INVALID'}")
        print(f"- bundle: {bundle_dir}")
        if args.smartconnect_root:
            print(f"- smartconnect root: {Path(args.smartconnect_root).resolve()}")
        for error in report["errors"]:
            print(f"  error: {error}")
        for warning in report["warnings"]:
            print(f"  warning: {warning}")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
