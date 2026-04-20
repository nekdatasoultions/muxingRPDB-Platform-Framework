#!/usr/bin/env python
"""Validate one customer-scoped muxer bundle and optional staged install root."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from muxer_customer_lib import validate_installed_muxer, validate_muxer_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate one customer-scoped muxer bundle.")
    parser.add_argument("--bundle-dir", required=True, help="Path to the customer bundle directory")
    parser.add_argument(
        "--muxer-root",
        help="Optional staged muxer root to validate after apply_muxer_customer.py runs",
    )
    parser.add_argument("--json", action="store_true", help="Print the validation report as JSON")
    args = parser.parse_args()

    bundle_dir = Path(args.bundle_dir).resolve()
    report = (
        validate_installed_muxer(bundle_dir, Path(args.muxer_root).resolve())
        if args.muxer_root
        else validate_muxer_bundle(bundle_dir)
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Muxer customer validation: {'VALID' if report['valid'] else 'INVALID'}")
        print(f"- bundle: {bundle_dir}")
        if args.muxer_root:
            print(f"- muxer root: {Path(args.muxer_root).resolve()}")
        for error in report["errors"]:
            print(f"  error: {error}")
        for warning in report["warnings"]:
            print(f"  warning: {warning}")

    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
