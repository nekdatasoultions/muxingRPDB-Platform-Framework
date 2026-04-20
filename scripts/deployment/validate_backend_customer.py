#!/usr/bin/env python
"""Validate one customer-scoped backend package and optional staged install root."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend_customer_lib import validate_backend_package, validate_installed_backend


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate one customer-scoped backend package.")
    parser.add_argument("--package-dir", required=True, help="Path to the customer package directory")
    parser.add_argument(
        "--backend-root",
        help="Optional staged backend root to validate after apply_backend_customer.py runs",
    )
    parser.add_argument("--json", action="store_true", help="Print the validation report as JSON")
    args = parser.parse_args()

    package_dir = Path(args.package_dir).resolve()
    report = (
        validate_installed_backend(package_dir, Path(args.backend_root).resolve())
        if args.backend_root
        else validate_backend_package(package_dir)
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Backend customer validation: {'VALID' if report['valid'] else 'INVALID'}")
        print(f"- package: {package_dir}")
        if args.backend_root:
            print(f"- backend root: {Path(args.backend_root).resolve()}")
        for error in report["errors"]:
            print(f"  error: {error}")
        for warning in report["warnings"]:
            print(f"  warning: {warning}")

    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
