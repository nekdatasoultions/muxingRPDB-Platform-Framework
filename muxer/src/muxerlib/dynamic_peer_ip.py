"""Helpers for device-registry driven peer public IP changes."""

from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
from typing import Any, Dict, Tuple


def _customer_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    customer = doc.get("customer") or {}
    if not isinstance(customer, dict):
        raise ValueError("customer must be a mapping")
    return customer


def _dynamic_doc(customer: Dict[str, Any]) -> Dict[str, Any]:
    dynamic = customer.get("dynamic_peer_ip") or {}
    if not isinstance(dynamic, dict):
        raise ValueError("customer.dynamic_peer_ip must be a mapping")
    return dynamic


def _device_registry_doc(dynamic: Dict[str, Any]) -> Dict[str, Any]:
    registry = dynamic.get("device_registry") or {}
    if not isinstance(registry, dict):
        raise ValueError("customer.dynamic_peer_ip.device_registry must be a mapping")
    return registry


def _reapply_doc(dynamic: Dict[str, Any]) -> Dict[str, Any]:
    reapply = dynamic.get("reapply") or {}
    if not isinstance(reapply, dict):
        raise ValueError("customer.dynamic_peer_ip.reapply must be a mapping")
    return reapply


def _peer_ip(customer: Dict[str, Any]) -> str:
    peer = customer.get("peer") or {}
    peer_ip = str(peer.get("public_ip") or "").strip()
    if not peer_ip:
        raise ValueError("customer.peer.public_ip is required")
    ipaddress.ip_address(peer_ip)
    return peer_ip


def _plain_value(value: Any) -> str:
    if isinstance(value, dict):
        if "S" in value:
            return str(value.get("S") or "")
        if "N" in value:
            return str(value.get("N") or "")
        if "BOOL" in value:
            return str(bool(value.get("BOOL"))).lower()
    if value is None:
        return ""
    return str(value)


def customer_name_from_doc(doc: Dict[str, Any]) -> str:
    customer_name = str(_customer_doc(doc).get("name") or "").strip()
    if not customer_name:
        raise ValueError("customer.name is required")
    return customer_name


def dynamic_peer_ip_enabled(doc: Dict[str, Any]) -> bool:
    customer = _customer_doc(doc)
    dynamic = _dynamic_doc(customer)
    return bool(dynamic.get("enabled"))


def validate_dynamic_peer_ip_request(doc: Dict[str, Any]) -> Dict[str, Any]:
    customer = _customer_doc(doc)
    dynamic = _dynamic_doc(customer)
    if not bool(dynamic.get("enabled")):
        return {"enabled": False, "checks": []}

    source = str(dynamic.get("source") or "device_registry_ddns").strip()
    if source != "device_registry_ddns":
        raise ValueError("customer.dynamic_peer_ip.source must be device_registry_ddns")

    registry = _device_registry_doc(dynamic)
    serial_number = str(registry.get("serial_number") or "").strip()
    if not serial_number:
        raise ValueError("customer.dynamic_peer_ip.device_registry.serial_number is required")
    password_secret_ref = str(registry.get("password_secret_ref") or "").strip()
    if not password_secret_ref:
        raise ValueError("customer.dynamic_peer_ip.device_registry.password_secret_ref is required")

    serial_number_attribute = str(
        registry.get("serial_number_attribute") or "serialNumber"
    ).strip()
    current_ip_attribute = str(registry.get("current_ip_attribute") or "currentIP").strip()
    last_updated_attribute = str(registry.get("last_updated_attribute") or "lastUpdated").strip()
    if not serial_number_attribute:
        raise ValueError("customer.dynamic_peer_ip.device_registry.serial_number_attribute is required")
    if not current_ip_attribute:
        raise ValueError("customer.dynamic_peer_ip.device_registry.current_ip_attribute is required")
    if not last_updated_attribute:
        raise ValueError("customer.dynamic_peer_ip.device_registry.last_updated_attribute is required")

    reapply = _reapply_doc(dynamic)
    reapply_mode = str(reapply.get("mode") or "deploy_only").strip()
    if reapply_mode not in {"deploy_only", "remove_reapply"}:
        raise ValueError("customer.dynamic_peer_ip.reapply.mode must be deploy_only or remove_reapply")

    return {
        "enabled": True,
        "source": source,
        "customer_name": customer_name_from_doc(doc),
        "peer_public_ip": _peer_ip(customer),
        "serial_number": serial_number,
        "password_secret_ref": password_secret_ref,
        "table_name": str(registry.get("table_name") or "").strip(),
        "serial_number_attribute": serial_number_attribute,
        "current_ip_attribute": current_ip_attribute,
        "last_updated_attribute": last_updated_attribute,
        "reapply_mode": reapply_mode,
        "update_remote_id_when_equal_to_peer_ip": bool(
            reapply.get("update_remote_id_when_equal_to_peer_ip", True)
        ),
    }


def normalize_dynamic_peer_ip_event(
    event_doc: Dict[str, Any],
    *,
    default_customer_name: str = "",
    default_serial_number: str = "",
) -> Dict[str, Any]:
    if not isinstance(event_doc, dict):
        raise ValueError("dynamic peer IP change event must be a mapping")

    customer_name = str(event_doc.get("customer_name") or default_customer_name).strip()
    if not customer_name:
        raise ValueError("dynamic peer IP change event must include customer_name")

    serial_number = str(event_doc.get("serial_number") or default_serial_number).strip()
    if not serial_number:
        raise ValueError("dynamic peer IP change event must include serial_number")

    observed_peer_raw = event_doc.get("observed_peer") or event_doc.get("current_ip") or event_doc.get("peer_ip")
    if not observed_peer_raw:
        raise ValueError("dynamic peer IP change event must include observed_peer")
    observed_peer = str(ipaddress.ip_address(str(observed_peer_raw).strip()))

    previous_peer_raw = event_doc.get("previous_peer")
    previous_peer = ""
    if previous_peer_raw not in (None, ""):
        previous_peer = str(ipaddress.ip_address(str(previous_peer_raw).strip()))

    return {
        "schema_version": int(event_doc.get("schema_version") or 1),
        "event_id": str(event_doc.get("event_id") or "").strip(),
        "customer_name": customer_name,
        "serial_number": serial_number,
        "observed_peer": observed_peer,
        "previous_peer": previous_peer,
        "observed_at": str(event_doc.get("observed_at") or "").strip(),
        "registry_last_updated": str(event_doc.get("registry_last_updated") or "").strip(),
        "registry_table": str(event_doc.get("registry_table") or "").strip(),
        "source": str(event_doc.get("source") or "").strip(),
    }


def build_dynamic_peer_ip_change_idempotency_key(event: Dict[str, Any]) -> str:
    key_doc = {
        "schema_version": 1,
        "action": "dynamic_peer_ip_reapply",
        "customer_name": str(event["customer_name"]).strip(),
        "serial_number": str(event["serial_number"]).strip(),
        "previous_peer": str(event.get("previous_peer") or "").strip(),
        "observed_peer": str(event["observed_peer"]).strip(),
        "registry_last_updated": str(event.get("registry_last_updated") or "").strip(),
    }
    encoded = json.dumps(key_doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_dynamic_peer_ip_reapply_request(
    doc: Dict[str, Any],
    *,
    observed_peer: str,
    observed_at: str | None = None,
    registry_last_updated: str = "",
    registry_table: str = "",
    source: str = "dynamic-peer-ip-watcher",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    validation = validate_dynamic_peer_ip_request(doc)
    if not validation.get("enabled"):
        raise ValueError("customer.dynamic_peer_ip.enabled must be true for peer IP reapply planning")

    customer = _customer_doc(doc)
    previous_peer = _peer_ip(customer)
    updated_peer = str(ipaddress.ip_address(str(observed_peer).strip()))
    if updated_peer == previous_peer:
        raise ValueError("observed peer matches the current customer peer public IP")

    updated_doc = copy.deepcopy(doc)
    updated_customer = updated_doc.setdefault("customer", {})
    updated_peer_doc = dict(updated_customer.get("peer") or {})
    updated_ipsec_doc = dict(updated_customer.get("ipsec") or {})
    existing_remote_id = str(updated_peer_doc.get("remote_id") or "").strip()
    existing_ipsec_remote_id = str(updated_ipsec_doc.get("remote_id") or "").strip()
    remote_id_updated = False
    ipsec_remote_id_updated = False

    updated_peer_doc["public_ip"] = updated_peer
    if validation["update_remote_id_when_equal_to_peer_ip"] and existing_remote_id in {"", previous_peer}:
        updated_peer_doc["remote_id"] = updated_peer
        remote_id_updated = True
    updated_customer["peer"] = updated_peer_doc
    if (
        updated_ipsec_doc
        and validation["update_remote_id_when_equal_to_peer_ip"]
        and existing_ipsec_remote_id in {"", previous_peer}
    ):
        updated_ipsec_doc["remote_id"] = updated_peer
        updated_customer["ipsec"] = updated_ipsec_doc
        ipsec_remote_id_updated = True

    summary = {
        "schema_version": 1,
        "action": "dynamic_peer_ip_reapply",
        "status": "planned",
        "live_apply": False,
        "customer_name": validation["customer_name"],
        "serial_number": validation["serial_number"],
        "previous_peer": previous_peer,
        "observed_peer": updated_peer,
        "observed_at": str(observed_at or "").strip(),
        "registry_last_updated": str(registry_last_updated or "").strip(),
        "registry_table": str(registry_table or validation.get("table_name") or "").strip(),
        "source": str(source or "").strip() or "dynamic-peer-ip-watcher",
        "reapply_mode": validation["reapply_mode"],
        "remote_id_updated": remote_id_updated or ipsec_remote_id_updated,
        "updated_remote_id": str(updated_peer_doc.get("remote_id") or "").strip(),
        "ipsec_remote_id_updated": ipsec_remote_id_updated,
        "updated_ipsec_remote_id": str(updated_ipsec_doc.get("remote_id") or "").strip(),
    }
    return updated_doc, summary


def normalize_device_registry_record(
    record_doc: Dict[str, Any],
    *,
    serial_number: str,
    serial_number_attribute: str = "serialNumber",
    current_ip_attribute: str = "currentIP",
    last_updated_attribute: str = "lastUpdated",
) -> Dict[str, Any]:
    if not isinstance(record_doc, dict):
        raise ValueError("device registry record must be a mapping")

    record_serial = str(
        _plain_value(record_doc.get(serial_number_attribute)) or serial_number
    ).strip()
    if not record_serial:
        raise ValueError("device registry record serial number is required")
    current_ip_raw = _plain_value(record_doc.get(current_ip_attribute)).strip()
    if not current_ip_raw:
        raise ValueError("device registry record current IP is required")
    current_ip = str(ipaddress.ip_address(current_ip_raw))

    return {
        "serial_number": record_serial,
        "current_ip": current_ip,
        "last_updated": _plain_value(record_doc.get(last_updated_attribute)).strip(),
        "raw": record_doc,
    }
