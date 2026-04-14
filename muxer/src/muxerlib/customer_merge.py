"""Merge helpers for RPDB customer sources."""

from __future__ import annotations

# Standard library imports for deep-copy merge behavior, timestamps, and path
# handling used by the early workflow scripts.
import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .customer_model import build_dynamodb_item, parse_customer_source, source_to_dict


# Shared YAML loader used by the scaffold scripts and future workflow commands.
def load_yaml_file(path: str | Path) -> Dict[str, Any]:
    """Load a YAML document into a dictionary."""
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


# Recursive dictionary merge where later layers win.
# This is the core mechanism behind defaults -> class -> source layering.
def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


# Remove empty values so the merged module stays compact and only contains
# sections/fields that actually matter for that customer.
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


# Convert a typed customer source into the flattened override shape used by the
# merged customer module. The source file keeps everything nested under
# `customer`, but the runtime module exposes peer/transport/selectors/etc.
# as top-level sections for simpler downstream consumption.
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

    # Parse and normalize the source first, then load the shared defaults and
    # class-level overrides that will be layered beneath the customer source.
    source = parse_customer_source(source_doc)
    defaults = copy.deepcopy(defaults_doc.get("defaults") or {})
    class_name = str(class_doc.get("class") or "").strip()
    class_overrides = copy.deepcopy(class_doc.get("overrides") or {})

    # Guardrail: the selected class file must actually match the customer's
    # declared class so we do not merge a NAT customer with strict-non-nat
    # defaults by mistake.
    if class_name and class_name != source.customer.customer_class:
        raise ValueError(
            f"class mismatch: source={source.customer.customer_class} class_file={class_name}"
        )

    # Resolve the RPDB priority base from the explicit argument first, then
    # shared defaults, then the hard fallback of 1000.
    rpdb_defaults = defaults.get("rpdb") or {}
    resolved_priority_base = int(
        priority_base
        if priority_base is not None
        else (rpdb_defaults.get("priority_base") or 1000)
    )

    # Layer the merged module in the intended order:
    # 1. shared defaults
    # 2. class defaults
    # 3. customer-specific overrides
    merged = _deep_merge(defaults, class_overrides)
    merged = _deep_merge(merged, _source_to_module_overrides(source))

    # `rpdb.priority_base` is a control-plane default, not part of the final
    # per-customer module once the concrete priority has been resolved.
    merged.pop("rpdb", None)

    # Ensure every merged customer has an explicit RPDB priority on the
    # transport section, even if the source file omitted one.
    transport = merged.setdefault("transport", {})
    transport["rpdb_priority"] = transport.get("rpdb_priority") or (
        resolved_priority_base + int(source.customer.id)
    )

    # The backend role is required in the resolved module, but it may come from
    # class defaults rather than the source file itself.
    backend = merged.setdefault("backend", {})
    if not backend.get("role"):
        raise ValueError("resolved backend.role is required")
    if not backend.get("cluster"):
        backend["cluster"] = "nat" if source.customer.customer_class == "nat" else "non-nat"
    # Keep physical backend IPs out of the canonical merged module whenever the
    # customer is expressed in logical placement terms. The environment/apply
    # layer or runtime backend-role map is responsible for resolving the active
    # underlay IP later.
    if backend.get("role") or backend.get("cluster") or backend.get("assignment"):
        backend.pop("underlay_ip", None)

    # Ensure the identity fields are always present in the resolved customer
    # section, even if downstream code later depends only on the merged module.
    customer = merged.setdefault("customer", {})
    customer.setdefault("id", source.customer.id)
    customer.setdefault("name", source.customer.name)
    customer.setdefault("customer_class", source.customer.customer_class)

    # Add provenance metadata so operators and later tooling can tell where the
    # merged module came from and when it was resolved.
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

    # Build the merged customer module first, then derive the compact
    # DynamoDB item from that canonical resolved record.
    source = parse_customer_source(source_doc)
    module = build_customer_module(
        source_doc,
        defaults_doc,
        class_doc,
        source_ref=source_ref,
        priority_base=priority_base,
        resolved_at=updated_at,
    )

    # Re-resolve the priority base here so the DynamoDB item builder can
    # compute the same explicit RPDB priority deterministically.
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
