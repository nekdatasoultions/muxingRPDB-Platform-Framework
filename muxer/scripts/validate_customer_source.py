#!/usr/bin/env python
"""Validate a single RPDB customer source file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muxerlib.customer_merge import build_customer_item, build_customer_module, load_yaml_file
from muxerlib.customer_model import parse_customer_source


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _maybe_validate_with_jsonschema(payload: dict, schema: dict) -> bool:
    try:
        import jsonschema
    except ImportError:
        return False
    jsonschema.validate(instance=payload, schema=schema)
    return True


def main() -> int:
    repo_muxer_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Validate one customer source file.")
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
        "--show-merged",
        action="store_true",
        help="Print the merged customer module",
    )
    args = parser.parse_args()

    source_path = Path(args.source).resolve()
    source_doc = load_yaml_file(source_path)
    source_schema = _load_json(repo_muxer_dir / "config" / "schema" / "customer-source.schema.json")
    source_schema_used = _maybe_validate_with_jsonschema(source_doc, source_schema)

    source = parse_customer_source(source_doc)
    class_file = (
        Path(args.class_file).resolve()
        if args.class_file
        else repo_muxer_dir / "config" / "customer-defaults" / "classes" / f"{source.customer.customer_class}.yaml"
    )
    defaults_doc = load_yaml_file(args.defaults)
    class_doc = load_yaml_file(class_file)
    source_ref = source_path.as_posix()

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

    item_schema = _load_json(repo_muxer_dir / "config" / "schema" / "customer-ddb-item.schema.json")
    item_schema_used = _maybe_validate_with_jsonschema(item, item_schema)

    print(
        f"Validated {source.customer.name} "
        f"(class={source.customer.customer_class}, rpdb_priority={module['transport']['rpdb_priority']})"
    )
    print(
        "Schema validation: "
        f"source={'jsonschema' if source_schema_used else 'parser-only'}, "
        f"ddb_item={'jsonschema' if item_schema_used else 'builder-only'}"
    )

    if args.show_merged:
        print(json.dumps(module, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
