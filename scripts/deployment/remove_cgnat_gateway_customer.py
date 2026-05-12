#!/usr/bin/env python
"""Remove one installed CGNAT ISP gateway handoff."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cgnat_gateway_customer_lib import remove_installed_gateway_handoff


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove one CGNAT ISP gateway handoff.")
    parser.add_argument("--customer-name", required=True)
    parser.add_argument("--gateway-root", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = remove_installed_gateway_handoff(args.customer_name, Path(args.gateway_root).resolve())
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"CGNAT ISP gateway handoff removed: {report['customer_name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
