"""Repo-only helpers for dynamic NAT-T promotion planning."""

from __future__ import annotations

import copy
import ipaddress
from datetime import datetime, timezone
from typing import Any, Dict, Tuple


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


def dynamic_provisioning_enabled(doc: Dict[str, Any]) -> bool:
    return bool(_dynamic_doc(_customer_doc(doc)).get("enabled"))


def validate_dynamic_initial_request(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the repo-only default strict non-NAT dynamic provisioning shape."""

    customer = _customer_doc(doc)
    dynamic = _dynamic_doc(customer)
    if not bool(dynamic.get("enabled")):
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
    if initial_class != "strict-non-nat" or customer_class != "strict-non-nat":
        raise ValueError("dynamic NAT-T discovery must start as customer_class=strict-non-nat")
    if initial_backend != "non-nat":
        raise ValueError("dynamic NAT-T discovery must start with initial_backend_cluster=non-nat")
    if backend_cluster and backend_cluster != "non-nat":
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
        "source_customer_class": str(customer.get("customer_class") or ""),
        "target_customer_class": "nat",
        "source_backend_cluster": str((customer.get("backend") or {}).get("cluster") or "non-nat"),
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
