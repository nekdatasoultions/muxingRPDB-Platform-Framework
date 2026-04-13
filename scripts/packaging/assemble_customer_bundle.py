#!/usr/bin/env python
"""Assemble a customer-scoped deployment bundle from generated artifacts."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from build_customer_bundle_manifest import build_bundle_manifest


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _copy_tree_contents(source_dir: Path, destination_dir: Path) -> int:
    copied = 0
    if not source_dir.exists():
        return copied
    for path in sorted(source_dir.rglob("*")):
        if path.is_dir():
            continue
        relative_path = path.relative_to(source_dir)
        _copy_file(path, destination_dir / relative_path)
        copied += 1
    return copied


def _write_placeholder(path: Path, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble a customer-scoped deployment bundle.")
    parser.add_argument("--customer-name", required=True, help="Customer name for the bundle")
    parser.add_argument("--bundle-dir", required=True, help="Destination bundle directory")
    parser.add_argument("--customer-module", required=True, help="Path to the merged customer module JSON")
    parser.add_argument("--customer-ddb-item", required=True, help="Path to the DynamoDB item JSON")
    parser.add_argument("--customer-source", help="Optional path to the source YAML for this customer")
    parser.add_argument("--muxer-dir", help="Optional directory containing muxer customer artifacts")
    parser.add_argument("--headend-dir", help="Optional directory containing head-end customer artifacts")
    args = parser.parse_args()

    bundle_dir = Path(args.bundle_dir).resolve()
    customer_dir = bundle_dir / "customer"
    muxer_dir = bundle_dir / "muxer"
    headend_dir = bundle_dir / "headend"

    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    customer_dir.mkdir(parents=True, exist_ok=True)
    muxer_dir.mkdir(parents=True, exist_ok=True)
    headend_dir.mkdir(parents=True, exist_ok=True)

    _copy_file(Path(args.customer_module).resolve(), customer_dir / "customer-module.json")
    _copy_file(Path(args.customer_ddb_item).resolve(), customer_dir / "customer-ddb-item.json")

    if args.customer_source:
        _copy_file(Path(args.customer_source).resolve(), customer_dir / "customer-source.yaml")

    muxer_copied = _copy_tree_contents(Path(args.muxer_dir).resolve(), muxer_dir) if args.muxer_dir else 0
    headend_copied = _copy_tree_contents(Path(args.headend_dir).resolve(), headend_dir) if args.headend_dir else 0

    if muxer_copied == 0:
        _write_placeholder(
            muxer_dir / "README.md",
            "Muxer Artifacts",
            "No muxer artifacts were supplied when this bundle was assembled.",
        )
    if headend_copied == 0:
        _write_placeholder(
            headend_dir / "README.md",
            "Headend Artifacts",
            "No head-end artifacts were supplied when this bundle was assembled.",
        )

    metadata = {
        "customer_name": args.customer_name,
        "assembled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs": {
            "customer_module": str(Path(args.customer_module).resolve()),
            "customer_ddb_item": str(Path(args.customer_ddb_item).resolve()),
            "customer_source": str(Path(args.customer_source).resolve()) if args.customer_source else None,
            "muxer_dir": str(Path(args.muxer_dir).resolve()) if args.muxer_dir else None,
            "headend_dir": str(Path(args.headend_dir).resolve()) if args.headend_dir else None,
        },
    }
    (bundle_dir / "bundle-metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest_path = bundle_dir / "manifest.txt"
    sha_path = bundle_dir / "sha256sums.txt"
    file_count = build_bundle_manifest(bundle_dir, manifest_path, sha_path)

    print(f"Customer bundle assembled: {bundle_dir}")
    print(f"Bundle files indexed: {file_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
