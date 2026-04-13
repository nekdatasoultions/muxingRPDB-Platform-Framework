#!/usr/bin/env python
"""Validate a single RPDB customer source file."""

from __future__ import annotations

# Standard library imports for CLI handling, JSON output, and path management.
import argparse
import json
import sys
from pathlib import Path

# Make the local `src` package importable when this script is run directly.
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Project helpers:
# - `load_yaml_file` reads YAML inputs
# - `build_customer_module` assembles the merged per-customer runtime module
# - `build_customer_item` assembles the DynamoDB item shape
# - `parse_customer_source` validates and normalizes the raw customer source
from muxerlib.customer_merge import build_customer_item, build_customer_module, load_yaml_file
from muxerlib.customer_model import parse_customer_source


def _load_json(path: Path) -> dict:
    """Load a JSON schema file from disk."""
    return json.loads(path.read_text(encoding="utf-8"))


def _maybe_validate_with_jsonschema(payload: dict, schema: dict) -> bool:
    """Use jsonschema when available, but keep a parser-only fallback."""
    try:
        import jsonschema
    except ImportError:
        return False
    jsonschema.validate(instance=payload, schema=schema)
    return True


def main() -> int:
    # Resolve the muxer repo root so we can find defaults, classes, and schemas
    # without depending on the caller's current working directory.
    repo_muxer_dir = Path(__file__).resolve().parents[1]

    # CLI definition for validating one customer source file. The source file is
    # required, while defaults/class files can be overridden for testing.
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

    # Load the raw customer source and validate it against the source schema.
    source_path = Path(args.source).resolve()
    source_doc = load_yaml_file(source_path)
    source_schema = _load_json(repo_muxer_dir / "config" / "schema" / "customer-source.schema.json")
    source_schema_used = _maybe_validate_with_jsonschema(source_doc, source_schema)

    # Parse the source first so we can discover the customer class and select
    # the matching class defaults automatically when none are provided.
    source = parse_customer_source(source_doc)
    class_file = (
        Path(args.class_file).resolve()
        if args.class_file
        else repo_muxer_dir / "config" / "customer-defaults" / "classes" / f"{source.customer.customer_class}.yaml"
    )

    # Load the shared defaults and class defaults, then keep a stable source_ref
    # for metadata and DynamoDB provenance.
    defaults_doc = load_yaml_file(args.defaults)
    class_doc = load_yaml_file(class_file)
    source_ref = source_path.as_posix()

    # Build both derived artifacts:
    # - the merged customer module that renderers/operators will consume
    # - the compact DynamoDB item that will hold the canonical runtime record
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

    # Validate the generated DynamoDB item against its own schema too.
    item_schema = _load_json(repo_muxer_dir / "config" / "schema" / "customer-ddb-item.schema.json")
    item_schema_used = _maybe_validate_with_jsonschema(item, item_schema)

    # Print a short operator summary so validation results are easy to scan.
    print(
        f"Validated {source.customer.name} "
        f"(class={source.customer.customer_class}, rpdb_priority={module['transport']['rpdb_priority']})"
    )
    print(
        "Schema validation: "
        f"source={'jsonschema' if source_schema_used else 'parser-only'}, "
        f"ddb_item={'jsonschema' if item_schema_used else 'builder-only'}"
    )

    # Optionally print the full merged module for debugging or review.
    if args.show_merged:
        print(json.dumps(module, indent=2, sort_keys=True))
    return 0


# Standard Python entrypoint.
if __name__ == "__main__":
    raise SystemExit(main())
