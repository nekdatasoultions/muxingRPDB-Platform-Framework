"""Repo-only helpers for dynamic NAT-T promotion planning."""

from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from .allocation import effective_customer_class, normalize_pool_class


INITIAL_PROTOCOLS = {
    "udp500": True,
    "udp4500": False,
    "esp50": True,
    "force_rewrite_4500_to_500": False,
}

PROMOTED_NAT_T_PROTOCOLS = {
    "udp500": True,
    "udp4500": True,
    "esp50": False,
    "force_rewrite_4500_to_500": False,
}


def _customer_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    customer = doc.get("customer") or {}
    if not isinstance(customer, dict):
        raise ValueError("customer must be a mapping")
    return customer


def _dynamic_doc(customer: Dict[str, Any]) -> Dict[str, Any]:
    dynamic = customer.get("dynamic_provisioning") or {}
    if not isinstance(dynamic, dict):
        raise ValueError("customer.dynamic_provisioning must be a mapping")
    return dynamic


def _effective_protocols(defaults: Dict[str, bool], override: Dict[str, Any] | None) -> Dict[str, bool]:
    effective = dict(defaults)
    for key, value in (override or {}).items():
        if key in effective:
            effective[key] = bool(value)
    return effective


def _peer_ip(customer: Dict[str, Any]) -> str:
    peer = customer.get("peer") or {}
    peer_ip = str(peer.get("public_ip") or "").strip()
    if not peer_ip:
        raise ValueError("customer.peer.public_ip is required")
    ipaddress.ip_address(peer_ip)
    return peer_ip


def _trigger_doc(dynamic: Dict[str, Any]) -> Dict[str, Any]:
    trigger = dynamic.get("trigger") or {}
    if not isinstance(trigger, dict):
        raise ValueError("customer.dynamic_provisioning.trigger must be a mapping")
    return trigger


def _promotion_doc(dynamic: Dict[str, Any]) -> Dict[str, Any]:
    promotion = dynamic.get("promotion") or {}
    if not isinstance(promotion, dict):
        raise ValueError("customer.dynamic_provisioning.promotion must be a mapping")
    return promotion


def _request_transport_overrides(customer_doc: Dict[str, Any]) -> Dict[str, Any]:
    transport = customer_doc.get("transport") or {}
    if not isinstance(transport, dict):
        return {}
    overrides: Dict[str, Any] = {}
    if transport.get("tunnel_mtu") not in (None, ""):
        overrides["tunnel_mtu"] = int(transport["tunnel_mtu"])
    return overrides


def _request_has_explicit_stack(customer: Dict[str, Any]) -> bool:
    backend = customer.get("backend") or {}
    return bool(str(customer.get("customer_class") or "").strip()) or bool(
        str(backend.get("cluster") or "").strip()
    )


def _dynamic_enabled(customer: Dict[str, Any], dynamic: Dict[str, Any]) -> bool:
    if "enabled" in dynamic:
        return bool(dynamic.get("enabled"))
    return not _request_has_explicit_stack(customer)


def dynamic_provisioning_enabled(doc: Dict[str, Any]) -> bool:
    customer = _customer_doc(doc)
    return _dynamic_enabled(customer, _dynamic_doc(customer))


def customer_name_from_doc(doc: Dict[str, Any]) -> str:
    customer_name = str(_customer_doc(doc).get("name") or "").strip()
    if not customer_name:
        raise ValueError("customer.name is required")
    return customer_name


def normalize_nat_t_observation_event(
    event_doc: Dict[str, Any],
    *,
    default_customer_name: str = "",
) -> Dict[str, Any]:
    """Normalize a muxer-observed UDP/4500 event for repo-only processing."""

    if not isinstance(event_doc, dict):
        raise ValueError("NAT-T observation event must be a mapping")

    customer_name = str(event_doc.get("customer_name") or default_customer_name).strip()
    if not customer_name:
        raise ValueError("NAT-T observation event must include customer_name")

    peer_value = (
        event_doc.get("observed_peer")
        or event_doc.get("observed_peer_ip")
        or event_doc.get("peer_ip")
    )
    if not peer_value:
        raise ValueError("NAT-T observation event must include observed_peer")
    observed_peer = str(ipaddress.ip_address(str(peer_value).strip()))

    observed_protocol = str(event_doc.get("observed_protocol") or event_doc.get("protocol") or "udp")
    observed_protocol = observed_protocol.strip().lower()
    observed_dport = int(
        event_doc.get("observed_dport")
        or event_doc.get("destination_port")
        or event_doc.get("dport")
        or 4500
    )
    packet_count = int(event_doc.get("packet_count") or 1)
    if packet_count < 1:
        raise ValueError("NAT-T observation event packet_count must be positive")

    normalized = {
        "schema_version": int(event_doc.get("schema_version") or 1),
        "event_id": str(event_doc.get("event_id") or "").strip(),
        "customer_name": customer_name,
        "observed_peer": observed_peer,
        "observed_protocol": observed_protocol,
        "observed_dport": observed_dport,
        "initial_udp500_observed": bool(event_doc.get("initial_udp500_observed")),
        "packet_count": packet_count,
        "observed_at": str(event_doc.get("observed_at") or "").strip(),
        "source": str(event_doc.get("source") or "").strip(),
    }
    if normalized["observed_protocol"] != "udp":
        raise ValueError("NAT-T observation event observed_protocol must be udp")
    if normalized["observed_dport"] != 4500:
        raise ValueError("NAT-T observation event observed_dport must be 4500")
    return normalized


def build_nat_t_observation_idempotency_key(event: Dict[str, Any]) -> str:
    """Return a stable key so repeat UDP/4500 observations reuse one plan."""

    key_doc = {
        "schema_version": 1,
        "action": "nat_t_auto_promote",
        "customer_name": str(event["customer_name"]).strip(),
        "observed_peer": str(event["observed_peer"]).strip(),
        "observed_protocol": str(event["observed_protocol"]).strip().lower(),
        "observed_dport": int(event["observed_dport"]),
    }
    encoded = json.dumps(key_doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_dynamic_initial_request(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the repo-only default strict non-NAT dynamic provisioning shape."""

    customer = _customer_doc(doc)
    dynamic = _dynamic_doc(customer)
    if not _dynamic_enabled(customer, dynamic):
        return {
            "enabled": False,
            "checks": [],
        }

    mode = str(dynamic.get("mode") or "nat_t_auto_promote").strip()
    if mode != "nat_t_auto_promote":
        raise ValueError("customer.dynamic_provisioning.mode must be nat_t_auto_promote")

    initial_class = str(dynamic.get("initial_customer_class") or "strict-non-nat")
    initial_backend = str(dynamic.get("initial_backend_cluster") or "non-nat")
    customer_class = str(customer.get("customer_class") or "")
    backend_cluster = str((customer.get("backend") or {}).get("cluster") or "")
    effective_initial_class = effective_customer_class(customer_class, backend_cluster)
    effective_initial_pool = normalize_pool_class(customer_class, backend_cluster)
    if initial_class != "strict-non-nat" or effective_initial_class != "strict-non-nat":
        raise ValueError(
            "dynamic NAT-T discovery must start as customer_class=strict-non-nat "
            "or omit the stack so strict non-NAT is selected by default"
        )
    if initial_backend != "non-nat":
        raise ValueError("dynamic NAT-T discovery must start with initial_backend_cluster=non-nat")
    if backend_cluster and effective_initial_pool != "non-nat":
        raise ValueError("dynamic NAT-T discovery initial backend.cluster must be non-nat")

    protocols = _effective_protocols(INITIAL_PROTOCOLS, customer.get("protocols") or {})
    if protocols["udp500"] is not True or protocols["udp4500"] is not False or protocols["esp50"] is not True:
        raise ValueError("dynamic NAT-T discovery must start with UDP/500 and ESP/50, with UDP/4500 disabled")

    trigger = _trigger_doc(dynamic)
    if str(trigger.get("protocol") or "udp").strip().lower() != "udp":
        raise ValueError("dynamic NAT-T trigger protocol must be udp")
    if int(trigger.get("destination_port") or 4500) != 4500:
        raise ValueError("dynamic NAT-T trigger destination_port must be 4500")
    if int(trigger.get("observation_window_seconds") or 300) < 1:
        raise ValueError("dynamic NAT-T trigger observation_window_seconds must be positive")
    if int(trigger.get("confirmation_packets") or 1) < 1:
        raise ValueError("dynamic NAT-T trigger confirmation_packets must be positive")

    promotion = _promotion_doc(dynamic)
    promotion_class = str(promotion.get("customer_class") or "nat")
    promotion_backend = str(promotion.get("backend_cluster") or "nat")
    if promotion_class != "nat" or promotion_backend != "nat":
        raise ValueError("dynamic NAT-T promotion target must be customer_class=nat and backend_cluster=nat")
    promoted_protocols = _effective_protocols(
        PROMOTED_NAT_T_PROTOCOLS,
        promotion.get("protocols") or {},
    )
    if promoted_protocols["udp500"] is not True or promoted_protocols["udp4500"] is not True:
        raise ValueError("dynamic NAT-T promotion must keep UDP/500 and enable UDP/4500")

    return {
        "enabled": True,
        "mode": mode,
        "defaulted": not _request_has_explicit_stack(customer) and "enabled" not in dynamic,
        "initial_customer_class": effective_initial_class,
        "initial_backend_cluster": effective_initial_pool,
        "initial_protocols": protocols,
        "trigger": {
            "protocol": "udp",
            "destination_port": 4500,
            "require_initial_udp500_observation": bool(
                trigger.get("require_initial_udp500_observation", True)
            ),
            "observation_window_seconds": int(trigger.get("observation_window_seconds") or 300),
            "confirmation_packets": int(trigger.get("confirmation_packets") or 1),
        },
        "promotion_protocols": promoted_protocols,
    }


def build_nat_t_promotion_request(
    doc: Dict[str, Any],
    *,
    observed_peer: str,
    observed_protocol: str = "udp",
    observed_dport: int = 4500,
    initial_udp500_observed: bool = False,
    observed_at: str | None = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build a NAT-T promotion request from a dynamic strict non-NAT request/source."""

    validation = validate_dynamic_initial_request(doc)
    if not validation.get("enabled"):
        raise ValueError("customer.dynamic_provisioning.enabled must be true for NAT-T promotion planning")

    customer = _customer_doc(doc)
    dynamic = _dynamic_doc(customer)
    trigger = validation["trigger"]
    peer_ip = _peer_ip(customer)
    observed_peer_ip = str(ipaddress.ip_address(str(observed_peer).strip()))
    if observed_peer_ip != peer_ip:
        raise ValueError(f"observed peer {observed_peer_ip} does not match customer peer {peer_ip}")
    if str(observed_protocol).strip().lower() != trigger["protocol"]:
        raise ValueError("observed protocol does not match the dynamic NAT-T trigger")
    if int(observed_dport) != int(trigger["destination_port"]):
        raise ValueError("observed destination port does not match the dynamic NAT-T trigger")
    if trigger["require_initial_udp500_observation"] and not initial_udp500_observed:
        raise ValueError("initial UDP/500 observation is required before NAT-T promotion")

    promotion = _promotion_doc(dynamic)
    promoted_customer = copy.deepcopy(customer)
    promoted_customer["customer_class"] = "nat"

    backend = dict(promoted_customer.get("backend") or {})
    backend["cluster"] = "nat"
    if promotion.get("backend_assignment"):
        backend["assignment"] = str(promotion["backend_assignment"])
    else:
        backend.pop("assignment", None)
    if promotion.get("backend_role"):
        backend["role"] = str(promotion["backend_role"])
    else:
        backend.pop("role", None)
    promoted_customer["backend"] = backend

    promoted_customer["protocols"] = _effective_protocols(
        PROMOTED_NAT_T_PROTOCOLS,
        promotion.get("protocols") or {},
    )
    promoted_customer["natd_rewrite"] = {"enabled": False}

    ipsec = copy.deepcopy(promoted_customer.get("ipsec") or {})
    if ipsec:
        ipsec["forceencaps"] = True
        promoted_customer["ipsec"] = ipsec

    if "post_ipsec_nat" not in promoted_customer:
        promoted_customer["post_ipsec_nat"] = {
            "enabled": False,
            "mode": "disabled",
        }

    promoted_customer["dynamic_provisioning"] = {
        "enabled": False,
        "mode": "nat_t_auto_promote",
        "initial_customer_class": "strict-non-nat",
        "initial_backend_cluster": "non-nat",
    }

    for allocator_owned in ("id", "transport"):
        promoted_customer.pop(allocator_owned, None)
    transport_overrides = _request_transport_overrides(customer)
    if transport_overrides:
        promoted_customer["transport"] = transport_overrides

    promoted_request = {
        "schema_version": int(doc.get("schema_version") or 1),
        "customer": promoted_customer,
    }
    observed_timestamp = observed_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    summary = {
        "schema_version": 1,
        "action": "plan_nat_t_promotion",
        "live_apply": False,
        "customer_name": str(customer.get("name") or ""),
        "source_customer_class": effective_customer_class(
            str(customer.get("customer_class") or ""),
            str((customer.get("backend") or {}).get("cluster") or ""),
        ),
        "target_customer_class": "nat",
        "source_backend_cluster": normalize_pool_class(
            str(customer.get("customer_class") or ""),
            str((customer.get("backend") or {}).get("cluster") or ""),
        ),
        "target_backend_cluster": "nat",
        "observed_event": {
            "peer_ip": observed_peer_ip,
            "protocol": "udp",
            "destination_port": 4500,
            "initial_udp500_observed": bool(initial_udp500_observed),
            "observed_at": observed_timestamp,
        },
        "initial_protocols": validation["initial_protocols"],
        "promoted_protocols": promoted_customer["protocols"],
        "guardrails": [
            "peer_ip_matched",
            "udp4500_trigger_matched",
            "initial_strict_non_nat",
            "target_nat",
            "repo_only_no_live_apply",
        ],
        "next_repo_only_command": (
            "python muxer\\scripts\\provision_customer_request.py <promoted-request.yaml> "
            "--replace-customer "
            + str(customer.get("name") or "")
        ),
    }
    return promoted_request, summary
