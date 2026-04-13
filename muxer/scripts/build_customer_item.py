#!/usr/bin/env python
"""Build the merged customer module and DynamoDB item for one customer."""

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


def main() -> int:
    repo_muxer_dir = Path(__file__).resolve().parents[1]
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

    module_json = json.dumps(module, indent=2, sort_keys=True)
    item_json = json.dumps(item, indent=2, sort_keys=True)

    if args.module_out:
        Path(args.module_out).write_text(module_json + "\n", encoding="utf-8")
    elif args.item_out:
        print(module_json)

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


if __name__ == "__main__":
    raise SystemExit(main())
