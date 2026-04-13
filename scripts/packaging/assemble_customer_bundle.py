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


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_export_inputs(export_dir: Path) -> dict:
    metadata_path = export_dir / "export-metadata.json"
    module_path = export_dir / "customer-module.json"
    item_path = export_dir / "customer-ddb-item.json"
    source_path = export_dir / "customer-source.yaml"
    muxer_dir = export_dir / "muxer"
    headend_dir = export_dir / "headend"

    errors = []
    if not export_dir.exists():
        errors.append(f"export directory not found: {export_dir}")
    if not module_path.exists():
        errors.append(f"export missing customer-module.json: {module_path}")
    if not item_path.exists():
        errors.append(f"export missing customer-ddb-item.json: {item_path}")
    if errors:
        raise ValueError("; ".join(errors))

    metadata = _load_json(metadata_path) if metadata_path.exists() else {}
    item = _load_json(item_path)

    return {
        "customer_name": metadata.get("customer_name") or item.get("customer_name"),
        "customer_module": module_path,
        "customer_ddb_item": item_path,
        "customer_source": source_path if source_path.exists() else None,
        "muxer_dir": muxer_dir if muxer_dir.exists() else None,
        "headend_dir": headend_dir if headend_dir.exists() else None,
        "export_metadata": metadata_path if metadata_path.exists() else None,
        "export_dir": export_dir,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble a customer-scoped deployment bundle.")
    parser.add_argument("--customer-name", help="Customer name for the bundle")
    parser.add_argument("--bundle-dir", required=True, help="Destination bundle directory")
    parser.add_argument(
        "--export-dir",
        help="Framework-side handoff export directory containing customer-module.json and customer-ddb-item.json",
    )
    parser.add_argument("--customer-module", help="Path to the merged customer module JSON")
    parser.add_argument("--customer-ddb-item", help="Path to the DynamoDB item JSON")
    parser.add_argument("--customer-source", help="Optional path to the source YAML for this customer")
    parser.add_argument("--muxer-dir", help="Optional directory containing muxer customer artifacts")
    parser.add_argument("--headend-dir", help="Optional directory containing head-end customer artifacts")
    args = parser.parse_args()

    export_inputs = None
    if args.export_dir:
        export_inputs = _resolve_export_inputs(Path(args.export_dir).resolve())

    customer_module_path = (
        export_inputs["customer_module"]
        if export_inputs
        else (Path(args.customer_module).resolve() if args.customer_module else None)
    )
    customer_ddb_item_path = (
        export_inputs["customer_ddb_item"]
        if export_inputs
        else (Path(args.customer_ddb_item).resolve() if args.customer_ddb_item else None)
    )
    customer_source_path = (
        export_inputs["customer_source"]
        if export_inputs and args.customer_source is None
        else (Path(args.customer_source).resolve() if args.customer_source else None)
    )
    muxer_input_dir = (
        export_inputs["muxer_dir"]
        if export_inputs and args.muxer_dir is None
        else (Path(args.muxer_dir).resolve() if args.muxer_dir else None)
    )
    headend_input_dir = (
        export_inputs["headend_dir"]
        if export_inputs and args.headend_dir is None
        else (Path(args.headend_dir).resolve() if args.headend_dir else None)
    )
    customer_name = args.customer_name or (export_inputs["customer_name"] if export_inputs else None)

    missing = []
    if not customer_name:
        missing.append("--customer-name or export metadata customer_name")
    if customer_module_path is None:
        missing.append("--customer-module or --export-dir")
    if customer_ddb_item_path is None:
        missing.append("--customer-ddb-item or --export-dir")
    if missing:
        raise ValueError("missing required inputs: " + ", ".join(missing))

    bundle_dir = Path(args.bundle_dir).resolve()
    customer_dir = bundle_dir / "customer"
    muxer_dir = bundle_dir / "muxer"
    headend_dir = bundle_dir / "headend"

    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    customer_dir.mkdir(parents=True, exist_ok=True)
    muxer_dir.mkdir(parents=True, exist_ok=True)
    headend_dir.mkdir(parents=True, exist_ok=True)

    _copy_file(customer_module_path, customer_dir / "customer-module.json")
    _copy_file(customer_ddb_item_path, customer_dir / "customer-ddb-item.json")

    if customer_source_path:
        _copy_file(customer_source_path, customer_dir / "customer-source.yaml")

    muxer_copied = _copy_tree_contents(muxer_input_dir, muxer_dir) if muxer_input_dir else 0
    headend_copied = _copy_tree_contents(headend_input_dir, headend_dir) if headend_input_dir else 0

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
        "customer_name": customer_name,
        "assembled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs": {
            "export_dir": str(export_inputs["export_dir"]) if export_inputs else None,
            "export_metadata": str(export_inputs["export_metadata"]) if export_inputs and export_inputs["export_metadata"] else None,
            "customer_module": str(customer_module_path),
            "customer_ddb_item": str(customer_ddb_item_path),
            "customer_source": str(customer_source_path) if customer_source_path else None,
            "muxer_dir": str(muxer_input_dir) if muxer_input_dir else None,
            "headend_dir": str(headend_input_dir) if headend_input_dir else None,
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
