#!/usr/bin/env python
"""Export one customer's framework-side handoff artifacts for deployment."""

from __future__ import annotations

# Standard library imports for CLI handling, JSON output, file copying, and
# stable timestamps in the export metadata.
import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make the local `src` package importable when this script is run directly.
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Project helpers used to build the merged customer module and DynamoDB item.
from muxerlib.customer_merge import build_customer_item, build_customer_module, load_yaml_file
from muxerlib.customer_model import parse_customer_source


def _copy_tree_contents(source_dir: Path, destination_dir: Path) -> int:
    copied = 0
    if not source_dir.exists():
        return copied
    for path in sorted(source_dir.rglob("*")):
        if path.is_dir():
            continue
        relative_path = path.relative_to(source_dir)
        destination_path = destination_dir / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination_path)
        copied += 1
    return copied


def _write_placeholder(path: Path, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")


def main() -> int:
    # Resolve the muxer repo root so default config paths stay stable.
    repo_muxer_dir = Path(__file__).resolve().parents[1]

    # CLI definition for exporting one customer handoff directory.
    parser = argparse.ArgumentParser(description="Export one customer handoff directory.")
    parser.add_argument("source", help="Path to the customer source YAML file")
    parser.add_argument(
        "--defaults",
        default=str(repo_muxer_dir / "config" / "customer-defaults" / "defaults.yaml"),
        help="Path to shared defaults YAML",
    )
    parser.add_argument(
        "--class-file",
        help="Path to the customer class YAML. Defaults to classes/<customer_class>.yaml",
    )
    parser.add_argument(
        "--export-dir",
        required=True,
        help="Destination export directory",
    )
    parser.add_argument(
        "--source-ref",
        help="Override source_ref stored in the merged module and DynamoDB item",
    )
    parser.add_argument(
        "--muxer-dir",
        help="Optional directory containing customer-scoped muxer artifacts",
    )
    parser.add_argument(
        "--headend-dir",
        help="Optional directory containing customer-scoped head-end artifacts",
    )
    args = parser.parse_args()

    # Load and parse the source first so we can automatically select the
    # matching class defaults.
    source_path = Path(args.source).resolve()
    source_doc = load_yaml_file(source_path)
    source = parse_customer_source(source_doc)
    class_file = (
        Path(args.class_file).resolve()
        if args.class_file
        else repo_muxer_dir / "config" / "customer-defaults" / "classes" / f"{source.customer.customer_class}.yaml"
    )

    # Load the shared defaults and class defaults, then compute the source_ref
    # that will be embedded into metadata and the DynamoDB item.
    defaults_doc = load_yaml_file(args.defaults)
    class_doc = load_yaml_file(class_file)
    source_ref = args.source_ref or source_path.as_posix()

    # Build the two canonical handoff artifacts.
    module = build_customer_module(
        source_doc,
        defaults_doc,
        class_doc,
        source_ref=source_ref,
    )
    item = build_customer_item(
        source_doc,
        defaults_doc,
        class_doc,
        source_ref=source_ref,
    )

    # Create the export directory fresh so repeated runs stay deterministic.
    export_dir = Path(args.export_dir).resolve()
    muxer_dir = export_dir / "muxer"
    headend_dir = export_dir / "headend"
    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    muxer_dir.mkdir(parents=True, exist_ok=True)
    headend_dir.mkdir(parents=True, exist_ok=True)

    # Write the required export files.
    (export_dir / "customer-module.json").write_text(
        json.dumps(module, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (export_dir / "customer-ddb-item.json").write_text(
        json.dumps(item, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    shutil.copy2(source_path, export_dir / "customer-source.yaml")

    # Copy optional muxer/head-end artifact directories when available.
    muxer_copied = _copy_tree_contents(Path(args.muxer_dir).resolve(), muxer_dir) if args.muxer_dir else 0
    headend_copied = _copy_tree_contents(Path(args.headend_dir).resolve(), headend_dir) if args.headend_dir else 0

    # Placeholders make the contract shape explicit even when no generated
    # muxer/head-end artifacts exist yet.
    if muxer_copied == 0:
        _write_placeholder(
            muxer_dir / "README.md",
            "Muxer Artifacts",
            "No muxer artifacts were supplied for this handoff export.",
        )
    if headend_copied == 0:
        _write_placeholder(
            headend_dir / "README.md",
            "Headend Artifacts",
            "No head-end artifacts were supplied for this handoff export.",
        )

    metadata = {
        "customer_name": source.customer.name,
        "customer_class": source.customer.customer_class,
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "customer_source": str(source_path),
            "defaults": str(Path(args.defaults).resolve()),
            "class_file": str(class_file),
            "source_ref": source_ref,
        },
        "artifact_inputs": {
            "muxer_dir": str(Path(args.muxer_dir).resolve()) if args.muxer_dir else None,
            "headend_dir": str(Path(args.headend_dir).resolve()) if args.headend_dir else None,
        },
    }
    (export_dir / "export-metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"Customer handoff export written: {export_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
