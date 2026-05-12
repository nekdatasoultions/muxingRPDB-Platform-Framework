#!/usr/bin/env python
"""Install one customer-scoped CGNAT ISP gateway handoff package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cgnat_gateway_customer_lib import install_gateway_handoff, validate_installed_gateway_handoff


def main() -> int:
    parser = argparse.ArgumentParser(description="Install one CGNAT ISP gateway handoff.")
    parser.add_argument("--customer-name", required=True)
    parser.add_argument("--gateway-root", required=True)
    parser.add_argument("--pki-review-dir", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = install_gateway_handoff(
        customer_name=args.customer_name,
        gateway_root=Path(args.gateway_root).resolve(),
        pki_review_dir=Path(args.pki_review_dir).resolve(),
    )
    validation = validate_installed_gateway_handoff(
        customer_name=args.customer_name,
        gateway_root=Path(args.gateway_root).resolve(),
        pki_review_dir=Path(args.pki_review_dir).resolve(),
    )
    report["validation"] = validation
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"CGNAT ISP gateway handoff installed: {report['customer_name']}")
    return 0 if validation.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
