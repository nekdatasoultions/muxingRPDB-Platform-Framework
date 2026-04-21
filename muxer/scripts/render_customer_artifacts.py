#!/usr/bin/env python
"""Render customer-scoped muxer and head-end artifacts for one customer."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muxerlib.customer_artifacts import build_customer_artifact_tree
from muxerlib.customer_merge import build_customer_item, build_customer_module, load_yaml_file
from muxerlib.customer_model import parse_customer_source


def _write_artifact(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, dict):
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    else:
        text = str(payload)
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text if text.endswith("\n") else text + "\n")


def main() -> int:
    repo_muxer_dir = Path(__file__).resolve().parents[1]

    parser = argparse.ArgumentParser(description="Render customer-scoped muxer and head-end artifacts.")
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
        "--out-dir",
        required=True,
        help="Destination directory for rendered customer artifacts",
    )
    parser.add_argument(
        "--source-ref",
        help="Override source_ref stored in the merged module and DynamoDB item",
    )
    args = parser.parse_args()

    source_path = Path(args.source).resolve()
    source_doc = load_yaml_file(source_path)
    source = parse_customer_source(source_doc)
    class_file = (
        Path(args.class_file).resolve()
        if args.class_file
        else repo_muxer_dir / "config" / "customer-defaults" / "classes" / f"{source.customer.customer_class}.yaml"
    )
    defaults_doc = load_yaml_file(args.defaults)
    class_doc = load_yaml_file(class_file)
    source_ref = args.source_ref or source_path.as_posix()

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

    out_dir = Path(args.out_dir).resolve()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tree = build_customer_artifact_tree(module, item)
    for root_name, files in tree.items():
        for relative_name, payload in files.items():
            _write_artifact(out_dir / root_name / relative_name, payload)

    _write_artifact(
        out_dir / "render-manifest.json",
        {
            "customer_name": source.customer.name,
            "customer_class": source.customer.customer_class,
            "source_ref": source_ref,
            "roots": {
                root_name: sorted(files.keys())
                for root_name, files in tree.items()
            },
        },
    )

    print(f"Rendered customer artifacts: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
