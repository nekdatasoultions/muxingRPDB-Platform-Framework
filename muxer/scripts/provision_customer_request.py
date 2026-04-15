#!/usr/bin/env python
"""Provision a minimal RPDB customer request into a fully allocated customer source."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muxerlib.allocation import (
    build_allocation_inventory,
    build_allocation_records,
    build_allocation_summary,
    load_allocation_pools,
    load_customer_source_docs,
    plan_customer_allocations,
    render_allocated_customer_source,
)
from muxerlib.allocation_sot import build_exclusive_allocation_ddb_items
from muxerlib.customer_merge import build_customer_item, build_customer_module, load_yaml_file


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _maybe_validate_with_jsonschema(payload: dict, schema: dict) -> bool:
    try:
        import jsonschema
    except ImportError:
        return False
    jsonschema.validate(instance=payload, schema=schema)
    return True


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def main() -> int:
    repo_muxer_dir = Path(__file__).resolve().parents[1]

    parser = argparse.ArgumentParser(description="Provision one minimal RPDB customer request.")
    parser.add_argument("request", help="Path to the customer request YAML file")
    parser.add_argument(
        "--schema",
        default=str(repo_muxer_dir / "config" / "schema" / "customer-request.schema.json"),
        help="Path to the customer request JSON schema",
    )
    parser.add_argument(
        "--allocation-pools",
        default=str(repo_muxer_dir / "config" / "allocation-pools" / "defaults.yaml"),
        help="Path to the allocation pools YAML",
    )
    parser.add_argument(
        "--defaults",
        default=str(repo_muxer_dir / "config" / "customer-defaults" / "defaults.yaml"),
        help="Path to the shared defaults YAML",
    )
    parser.add_argument(
        "--existing-source-root",
        action="append",
        default=[],
        help="Existing customer source roots used for collision checks. Can be specified multiple times.",
    )
    parser.add_argument("--source-out", help="Optional path to write the fully allocated customer source YAML")
    parser.add_argument("--module-out", help="Optional path to write the merged customer module JSON")
    parser.add_argument("--item-out", help="Optional path to write the customer DynamoDB item JSON")
    parser.add_argument("--allocation-out", help="Optional path to write the allocation summary JSON")
    parser.add_argument("--json", action="store_true", help="Print the full provisioning result as JSON")
    args = parser.parse_args()

    request_path = Path(args.request).resolve()
    request_doc = load_yaml_file(request_path)
    request_schema = _load_json(Path(args.schema).resolve())
    _maybe_validate_with_jsonschema(request_doc, request_schema)

    pools_doc = load_allocation_pools(Path(args.allocation_pools).resolve())
    existing_roots = args.existing_source_root or [str(repo_muxer_dir / "config" / "customer-sources")]
    inventory = build_allocation_inventory(load_customer_source_docs(*existing_roots))
    allocation_plan = plan_customer_allocations(request_doc, pools_doc, inventory=inventory)
    customer_source = render_allocated_customer_source(request_doc, allocation_plan)

    customer_class = str((customer_source.get("customer") or {}).get("customer_class") or "")
    class_file = repo_muxer_dir / "config" / "customer-defaults" / "classes" / f"{customer_class}.yaml"
    defaults_doc = load_yaml_file(args.defaults)
    class_doc = load_yaml_file(class_file)
    source_ref = request_path.as_posix()

    customer_module = build_customer_module(
        customer_source,
        defaults_doc,
        class_doc,
        source_ref=source_ref,
    )
    customer_item = build_customer_item(
        customer_source,
        defaults_doc,
        class_doc,
        source_ref=source_ref,
    )
    allocation_summary = build_allocation_summary(
        request_doc,
        allocation_plan,
        source_ref=source_ref,
    )
    allocation_records = build_allocation_records(
        request_doc,
        allocation_plan,
        source_ref=source_ref,
    )
    allocation_ddb_items = build_exclusive_allocation_ddb_items(allocation_records)

    result = {
        "customer_source": customer_source,
        "allocation_plan": allocation_plan,
        "allocation_summary": allocation_summary,
        "allocation_records": allocation_records,
        "allocation_ddb_items": allocation_ddb_items,
        "customer_module": customer_module,
        "dynamodb_item": customer_item,
    }

    if args.source_out:
        _write_yaml(Path(args.source_out).resolve(), customer_source)
    if args.module_out:
        Path(args.module_out).resolve().write_text(
            json.dumps(customer_module, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.item_out:
        Path(args.item_out).resolve().write_text(
            json.dumps(customer_item, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.allocation_out:
        Path(args.allocation_out).resolve().write_text(
            json.dumps(allocation_summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.json or not any((args.source_out, args.module_out, args.item_out, args.allocation_out)):
        print(json.dumps(result, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
