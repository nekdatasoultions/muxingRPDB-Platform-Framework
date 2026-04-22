#!/usr/bin/env python
"""Validate that a customer bundle has the expected basic structure."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REQUIRED_TOP_LEVEL_FILES = [
    "bundle-metadata.json",
    "manifest.txt",
    "sha256sums.txt",
]

REQUIRED_DIRECTORIES = [
    "customer",
    "muxer",
    "headend",
]

RECOMMENDED_FILES = [
    "customer/customer-source.yaml",
]

REQUIRED_CUSTOMER_FILES = [
    "customer/customer-module.json",
    "customer/customer-ddb-item.json",
]

REQUIRED_MUXER_FILES = [
    "muxer/customer/customer-summary.json",
    "muxer/firewall/firewall-intent.json",
    "muxer/firewall/nftables.apply.nft",
    "muxer/firewall/nftables.remove.nft",
    "muxer/firewall/nftables-state.json",
    "muxer/firewall/activation-manifest.json",
    "muxer/routing/ip-rule.command.txt",
    "muxer/routing/ip-route-default.command.txt",
    "muxer/routing/rpdb-routing.json",
    "muxer/tunnel/ip-link.command.txt",
    "muxer/tunnel/tunnel-intent.json",
]

REQUIRED_HEADEND_FILES = [
    "headend/ipsec/ipsec-intent.json",
    "headend/ipsec/swanctl-connection.conf",
    "headend/ipsec/initiation-intent.json",
    "headend/ipsec/initiate-tunnel.sh",
    "headend/transport/transport-intent.json",
    "headend/transport/apply-transport.sh",
    "headend/transport/remove-transport.sh",
    "headend/public-identity/public-identity-intent.json",
    "headend/public-identity/apply-public-identity.sh",
    "headend/public-identity/remove-public-identity.sh",
    "headend/routing/routing-intent.json",
    "headend/routing/ip-route.commands.txt",
    "headend/post-ipsec-nat/post-ipsec-nat-intent.json",
    "headend/post-ipsec-nat/nftables.apply.nft",
    "headend/post-ipsec-nat/nftables.remove.nft",
    "headend/post-ipsec-nat/nftables-state.json",
    "headend/post-ipsec-nat/activation-manifest.json",
    "headend/outside-nat/outside-nat-intent.json",
    "headend/outside-nat/nftables.apply.nft",
    "headend/outside-nat/nftables.remove.nft",
    "headend/outside-nat/nftables-state.json",
    "headend/outside-nat/activation-manifest.json",
]

HEADEND_TEXT_FILES = [
    "headend/ipsec/swanctl-connection.conf",
    "headend/ipsec/initiate-tunnel.sh",
    "headend/transport/apply-transport.sh",
    "headend/transport/remove-transport.sh",
    "headend/public-identity/apply-public-identity.sh",
    "headend/public-identity/remove-public-identity.sh",
    "headend/routing/ip-route.commands.txt",
    "headend/post-ipsec-nat/nftables.apply.nft",
    "headend/post-ipsec-nat/nftables.remove.nft",
    "headend/outside-nat/nftables.apply.nft",
    "headend/outside-nat/nftables.remove.nft",
]

MUXER_TEXT_FILES = [
    "muxer/firewall/nftables.apply.nft",
    "muxer/firewall/nftables.remove.nft",
    "muxer/routing/ip-rule.command.txt",
    "muxer/routing/ip-route-default.command.txt",
    "muxer/tunnel/ip-link.command.txt",
]

BANNED_GENERATED_RUNTIME_TOKENS = [
    "iptables",
    "iptables-restore",
]

PLACEHOLDER_RE = re.compile(r"\$\{[^}]+\}")


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

        for name in REQUIRED_CUSTOMER_FILES:
            if not (bundle_dir / name).exists():
                report["errors"].append(f"missing required file: {name}")

        for name in REQUIRED_MUXER_FILES:
            path = bundle_dir / name
            if not path.exists():
                report["errors"].append(f"missing required file: {name}")

        for name in REQUIRED_HEADEND_FILES:
            path = bundle_dir / name
            if not path.exists():
                report["errors"].append(f"missing required file: {name}")

        for name in MUXER_TEXT_FILES + HEADEND_TEXT_FILES:
            path = bundle_dir / name
            if not path.exists():
                continue
            unresolved = sorted(set(PLACEHOLDER_RE.findall(path.read_text(encoding="utf-8"))))
            if unresolved:
                report["errors"].append(
                    f"bundle file has unresolved placeholders: {name} -> {', '.join(unresolved)}"
                )

        for path in sorted(bundle_dir.rglob("*")):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            rel = path.relative_to(bundle_dir).as_posix()
            for token in BANNED_GENERATED_RUNTIME_TOKENS:
                if token in text:
                    report["errors"].append(
                        f"generated bundle file contains banned runtime token: {rel} -> {token}"
                    )

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
