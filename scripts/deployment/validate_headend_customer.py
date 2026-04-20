#!/usr/bin/env python
"""Validate one customer-scoped head-end bundle and optional staged install root."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from headend_customer_lib import validate_headend_bundle, validate_installed_headend


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate one customer-scoped head-end bundle.")
    parser.add_argument("--bundle-dir", required=True, help="Path to the customer bundle directory")
    parser.add_argument(
        "--headend-root",
        help="Optional staged head-end root to validate after apply_headend_customer.py runs",
    )
    parser.add_argument("--json", action="store_true", help="Print the validation report as JSON")
    args = parser.parse_args()

    bundle_dir = Path(args.bundle_dir).resolve()
    report = (
        validate_installed_headend(bundle_dir, Path(args.headend_root).resolve())
        if args.headend_root
        else validate_headend_bundle(bundle_dir)
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"Head-end customer validation: {'VALID' if report['valid'] else 'INVALID'}"
        )
        print(f"- bundle: {bundle_dir}")
        if args.headend_root:
            print(f"- headend root: {Path(args.headend_root).resolve()}")
        for error in report["errors"]:
            print(f"  error: {error}")
        for warning in report["warnings"]:
            print(f"  warning: {warning}")

    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
