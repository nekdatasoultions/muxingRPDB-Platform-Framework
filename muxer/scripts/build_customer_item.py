#!/usr/bin/env python
"""Build the merged customer module and DynamoDB item for one customer."""

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


def main() -> int:
    # Resolve the muxer repo root so relative config paths are stable.
    repo_muxer_dir = Path(__file__).resolve().parents[1]

    # CLI definition for building one merged customer module and its
    # corresponding DynamoDB item.
    parser = argparse.ArgumentParser(description="Build one customer module and DynamoDB item.")
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
        "--source-ref",
        help="Override source_ref stored in the merged module and DynamoDB item",
    )
    parser.add_argument(
        "--module-out",
        help="Optional path to write the merged customer module JSON",
    )
    parser.add_argument(
        "--item-out",
        help="Optional path to write the DynamoDB item JSON",
    )
    args = parser.parse_args()

    # Load and parse the customer source first so we can discover the
    # customer class and choose the matching class defaults automatically.
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

    # Build the two main artifacts:
    # - the merged customer module
    # - the DynamoDB item that stores the canonical runtime record
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

    # Pre-render both payloads to pretty JSON so they can either be written
    # to files or printed to stdout.
    module_json = json.dumps(module, indent=2, sort_keys=True)
    item_json = json.dumps(item, indent=2, sort_keys=True)

    # Output behavior:
    # - if `--module-out` is given, write the module to disk
    # - if only `--item-out` is given, still print the module so the operator
    #   can see what was built
    if args.module_out:
        Path(args.module_out).write_text(module_json + "\n", encoding="utf-8")
    elif args.item_out:
        print(module_json)

    # Output behavior for the DynamoDB item:
    # - write to disk when `--item-out` is provided
    # - otherwise print either the item alone or a combined object containing
    #   both the merged module and the item
    if args.item_out:
        Path(args.item_out).write_text(item_json + "\n", encoding="utf-8")
    else:
        if args.module_out:
            print(item_json)
        else:
            print(
                json.dumps(
                    {
                        "customer_module": module,
                        "dynamodb_item": item,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )

    return 0


# Standard Python entrypoint.
if __name__ == "__main__":
    raise SystemExit(main())
