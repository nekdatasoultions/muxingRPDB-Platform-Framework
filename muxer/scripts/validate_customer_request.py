#!/usr/bin/env python
"""Validate a minimal RPDB customer provisioning request."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muxerlib.allocation import effective_customer_class, normalize_pool_class
from muxerlib.customer_merge import load_yaml_file
from muxerlib.dynamic_provisioning import validate_dynamic_initial_request


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

    parser = argparse.ArgumentParser(description="Validate one minimal RPDB customer provisioning request.")
    parser.add_argument("request", help="Path to the customer request YAML file")
    parser.add_argument(
        "--schema",
        default=str(repo_muxer_dir / "config" / "schema" / "customer-request.schema.json"),
        help="Path to the customer request JSON schema",
    )
    parser.add_argument("--show-request", action="store_true", help="Print the validated request")
    args = parser.parse_args()

    request_path = Path(args.request).resolve()
    request_doc = load_yaml_file(request_path)
    request_schema = _load_json(Path(args.schema).resolve())
    used_jsonschema = _maybe_validate_with_jsonschema(request_doc, request_schema)

    customer_doc = request_doc.get("customer") or {}
    backend_doc = customer_doc.get("backend") or {}
    pool_class = normalize_pool_class(
        str(customer_doc.get("customer_class") or ""),
        str(backend_doc.get("cluster") or ""),
    )
    customer_class = effective_customer_class(
        str(customer_doc.get("customer_class") or ""),
        str(backend_doc.get("cluster") or ""),
    )
    dynamic_validation = validate_dynamic_initial_request(request_doc)

    print(
        f"Validated request {customer_doc.get('name')} "
        f"(effective_class={customer_class}, pool_class={pool_class})"
    )
    print(f"Schema validation: {'jsonschema' if used_jsonschema else 'schema-package-missing'}")
    if dynamic_validation.get("enabled"):
        print("Dynamic provisioning: nat_t_auto_promote")

    if args.show_request:
        print(json.dumps(request_doc, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
