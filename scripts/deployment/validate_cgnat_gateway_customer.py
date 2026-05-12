#!/usr/bin/env python
"""Validate one installed CGNAT ISP gateway handoff."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cgnat_gateway_customer_lib import validate_installed_gateway_handoff


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate one CGNAT ISP gateway handoff.")
    parser.add_argument("--customer-name", required=True)
    parser.add_argument("--gateway-root", required=True)
    parser.add_argument("--pki-review-dir", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = validate_installed_gateway_handoff(
        customer_name=args.customer_name,
        gateway_root=Path(args.gateway_root).resolve(),
        pki_review_dir=Path(args.pki_review_dir).resolve(),
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"CGNAT ISP gateway handoff validation: {'VALID' if report['valid'] else 'INVALID'}")
        for error in report["errors"]:
            print(f"  error: {error}")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
