#!/usr/bin/env python
"""Plan a repo-only strict non-NAT to NAT-T customer promotion."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muxerlib.customer_merge import load_yaml_file
from muxerlib.dynamic_provisioning import build_nat_t_promotion_request


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a reviewed NAT-T promotion request when a dynamic strict "
            "non-NAT customer is observed on UDP/4500."
        )
    )
    parser.add_argument("customer_input", help="Current customer request or allocated source YAML")
    parser.add_argument("--observed-peer", required=True, help="Observed customer peer public IP")
    parser.add_argument("--observed-protocol", default="udp", help="Observed packet protocol")
    parser.add_argument("--observed-dport", type=int, default=4500, help="Observed destination port")
    parser.add_argument(
        "--initial-udp500-observed",
        action="store_true",
        help="Confirm that UDP/500 was observed before the UDP/4500 promotion trigger",
    )
    parser.add_argument("--observed-at", default="", help="Optional observed event timestamp")
    parser.add_argument("--request-out", help="Path to write the promoted NAT customer request YAML")
    parser.add_argument("--summary-out", help="Path to write the promotion summary JSON")
    parser.add_argument("--json", action="store_true", help="Print the promotion summary as JSON")
    args = parser.parse_args()

    input_path = Path(args.customer_input).resolve()
    customer_doc = load_yaml_file(input_path)
    promoted_request, summary = build_nat_t_promotion_request(
        customer_doc,
        observed_peer=args.observed_peer,
        observed_protocol=args.observed_protocol,
        observed_dport=args.observed_dport,
        initial_udp500_observed=args.initial_udp500_observed,
        observed_at=args.observed_at or None,
    )
    summary["source_ref"] = input_path.as_posix()
    if args.request_out:
        request_out = Path(args.request_out).resolve()
        _write_yaml(request_out, promoted_request)
        summary["promoted_request"] = request_out.as_posix()
    if args.summary_out:
        _write_json(Path(args.summary_out).resolve(), summary)

    if args.json or not (args.request_out or args.summary_out):
        print(json.dumps(summary, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
