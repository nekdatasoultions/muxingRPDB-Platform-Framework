#!/usr/bin/env python
"""Validate that a bound artifact tree has no unresolved placeholders."""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muxerlib.environment_binding import find_unresolved_placeholders, iter_text_files

PROTOCOL_FIELD_MAP = {
    "udp500": ("udp500",),
    "udp4500": ("udp4500",),
    "esp50": ("esp50",),
}
BANNED_GENERATED_RUNTIME_TOKENS = [
    "iptables",
    "iptables-restore",
]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_bound_snat_coverage(report: dict, bound_dir: Path) -> None:
    firewall_intent_path = bound_dir / "muxer" / "firewall" / "firewall-intent.json"
    if not firewall_intent_path.exists():
        report["errors"].append("missing required file: muxer/firewall/firewall-intent.json")
        return

    intent = _load_json(firewall_intent_path)
    protocols = intent.get("protocols") or {}
    coverage = intent.get("snat_coverage") or {}
    sources = [str(value).strip() for value in coverage.get("egress_sources") or [] if str(value).strip()]
    rules = coverage.get("rules") or []
    if not sources:
        report["errors"].append("SNAT coverage missing head-end egress sources")
        return

    for source in sources:
        try:
            ipaddress.ip_address(source)
        except ValueError:
            report["errors"].append(f"SNAT coverage source is not a concrete IPv4 address: {source}")

    rule_pairs = {
        (str(rule.get("source_ip") or "").strip(), str(rule.get("protocol") or "").strip())
        for rule in rules
    }
    for protocol_name, field_names in PROTOCOL_FIELD_MAP.items():
        enabled = any(bool(protocols.get(field_name)) for field_name in field_names)
        if not enabled:
            continue
        for source in sources:
            if (source, protocol_name) not in rule_pairs:
                report["errors"].append(
                    f"SNAT coverage missing {protocol_name} for head-end egress source {source}"
                )


def _validate_no_legacy_firewall_tokens(report: dict, bound_dir: Path) -> None:
    for path in iter_text_files(bound_dir):
        text = path.read_text(encoding="utf-8")
        for token in BANNED_GENERATED_RUNTIME_TOKENS:
            if token in text:
                report["errors"].append(
                    f"{path.relative_to(bound_dir)} contains banned runtime token: {token}"
                )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a bound artifact tree.")
    parser.add_argument("bound_dir", help="Path to the bound artifact directory")
    parser.add_argument("--json", action="store_true", help="Print the validation report as JSON")
    args = parser.parse_args()

    bound_dir = Path(args.bound_dir).resolve()
    report = {
        "bound_dir": str(bound_dir),
        "errors": [],
    }

    if not bound_dir.exists():
        report["errors"].append(f"bound directory not found: {bound_dir}")
    else:
        report_path = bound_dir / "binding-report.json"
        if not report_path.exists():
            report["errors"].append("missing required file: binding-report.json")
        for path in iter_text_files(bound_dir):
            unresolved = find_unresolved_placeholders(path.read_text(encoding="utf-8"))
            if unresolved:
                report["errors"].append(
                    f"{path.relative_to(bound_dir)} still has unresolved placeholders: {', '.join(unresolved)}"
                )
        _validate_bound_snat_coverage(report, bound_dir)
        _validate_no_legacy_firewall_tokens(report, bound_dir)

    report["valid"] = not report["errors"]

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Bound artifact tree: {'VALID' if report['valid'] else 'INVALID'}")
        print(f"- bound dir: {bound_dir}")
        for error in report["errors"]:
            print(f"  error: {error}")

    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
