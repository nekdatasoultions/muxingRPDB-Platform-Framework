"""Merge helpers for RPDB customer sources."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .customer_model import build_dynamodb_item, parse_customer_source, source_to_dict


def load_yaml_file(path: str | Path) -> Dict[str, Any]:
    """Load a YAML document into a dictionary."""
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _compact(item)
            for key, item in value.items()
            if item not in (None, "", [], {})
        }
    if isinstance(value, list):
        return [_compact(item) for item in value if item not in (None, "", [], {})]
    return value


def _source_to_module_overrides(source) -> Dict[str, Any]:
    customer = source.customer
    raw = source_to_dict(source)
    customer_raw = raw["customer"]
    return _compact(
        {
            "schema_version": source.schema_version,
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "customer_class": customer.customer_class,
            },
            "peer": customer_raw["peer"],
            "transport": customer_raw["transport"],
            "selectors": customer_raw["selectors"],
            "backend": customer_raw.get("backend") or {},
            "protocols": customer_raw.get("protocols") or {},
            "natd_rewrite": customer_raw.get("natd_rewrite") or {},
            "ipsec": customer_raw.get("ipsec") or {},
            "post_ipsec_nat": customer_raw.get("post_ipsec_nat") or {},
        }
    )


def build_customer_module(
    source_doc: Dict[str, Any],
    defaults_doc: Dict[str, Any],
    class_doc: Dict[str, Any],
    *,
    source_ref: str,
    priority_base: Optional[int] = None,
    resolved_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the merged customer module for a single customer."""
    source = parse_customer_source(source_doc)
    defaults = copy.deepcopy(defaults_doc.get("defaults") or {})
    class_name = str(class_doc.get("class") or "").strip()
    class_overrides = copy.deepcopy(class_doc.get("overrides") or {})

    if class_name and class_name != source.customer.customer_class:
        raise ValueError(
            f"class mismatch: source={source.customer.customer_class} class_file={class_name}"
        )

    rpdb_defaults = defaults.get("rpdb") or {}
    resolved_priority_base = int(
        priority_base
        if priority_base is not None
        else (rpdb_defaults.get("priority_base") or 1000)
    )

    merged = _deep_merge(defaults, class_overrides)
    merged = _deep_merge(merged, _source_to_module_overrides(source))
    merged.pop("rpdb", None)

    transport = merged.setdefault("transport", {})
    transport["rpdb_priority"] = transport.get("rpdb_priority") or (
        resolved_priority_base + int(source.customer.id)
    )

    backend = merged.setdefault("backend", {})
    if not backend.get("role"):
        raise ValueError("resolved backend.role is required")

    customer = merged.setdefault("customer", {})
    customer.setdefault("id", source.customer.id)
    customer.setdefault("name", source.customer.name)
    customer.setdefault("customer_class", source.customer.customer_class)

    merged["metadata"] = {
        "source_ref": source_ref,
        "class_name": source.customer.customer_class,
        "resolved_at": resolved_at
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    merged["schema_version"] = source.schema_version
    return merged


def build_customer_item(
    source_doc: Dict[str, Any],
    defaults_doc: Dict[str, Any],
    class_doc: Dict[str, Any],
    *,
    source_ref: str,
    priority_base: Optional[int] = None,
    updated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the DynamoDB item for a single customer."""
    source = parse_customer_source(source_doc)
    module = build_customer_module(
        source_doc,
        defaults_doc,
        class_doc,
        source_ref=source_ref,
        priority_base=priority_base,
        resolved_at=updated_at,
    )
    resolved_priority_base = int(
        priority_base
        if priority_base is not None
        else ((defaults_doc.get("defaults") or {}).get("rpdb") or {}).get("priority_base") or 1000
    )
    return build_dynamodb_item(
        source,
        module,
        source_ref=source_ref,
        priority_base=resolved_priority_base,
        updated_at=updated_at,
    )
