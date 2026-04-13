#!/usr/bin/env python
"""Validate that a customer bundle has the expected basic structure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED_TOP_LEVEL_FILES = [
    "manifest.txt",
    "sha256sums.txt",
]

REQUIRED_DIRECTORIES = [
    "customer",
    "muxer",
    "headend",
]

RECOMMENDED_FILES = [
    "customer/customer.yaml",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a customer bundle structure.")
    parser.add_argument("bundle_dir", help="Path to the customer bundle directory")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the validation report as JSON",
    )
    args = parser.parse_args()

    bundle_dir = Path(args.bundle_dir).resolve()
    report = {
        "bundle_dir": str(bundle_dir),
        "errors": [],
        "warnings": [],
    }

    if not bundle_dir.exists():
        report["errors"].append(f"bundle directory not found: {bundle_dir}")
    else:
        for name in REQUIRED_TOP_LEVEL_FILES:
            if not (bundle_dir / name).exists():
                report["errors"].append(f"missing required file: {name}")

        for name in REQUIRED_DIRECTORIES:
            if not (bundle_dir / name).is_dir():
                report["errors"].append(f"missing required directory: {name}/")

        for name in RECOMMENDED_FILES:
            if not (bundle_dir / name).exists():
                report["warnings"].append(f"missing recommended file: {name}")

        file_count = sum(1 for path in bundle_dir.rglob("*") if path.is_file())
        if file_count == 0:
            report["errors"].append("bundle contains no files")

    report["valid"] = not report["errors"]

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Bundle structure: {'VALID' if report['valid'] else 'INVALID'}")
        print(f"- bundle: {bundle_dir}")
        for error in report["errors"]:
            print(f"  error: {error}")
        for warning in report["warnings"]:
            print(f"  warning: {warning}")

    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
