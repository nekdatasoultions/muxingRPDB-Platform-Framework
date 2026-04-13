"""Customer source and DynamoDB item helpers for the RPDB model."""

from __future__ import annotations

# Standard library imports for JSON serialization, typed dataclasses, and
# stable UTC timestamps used in the DynamoDB item.
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# Typed building blocks for the customer source model.
# These map directly to the major sections we expect in the source YAML.
@dataclass(frozen=True)
class Overlay:
    mux_ip: str
    router_ip: str


@dataclass(frozen=True)
class Peer:
    public_ip: str
    psk_secret_ref: str
    remote_id: str = ""


@dataclass(frozen=True)
class Transport:
    mark: str
    table: int
    tunnel_key: int
    interface: str
    overlay: Overlay
    tunnel_type: str = "gre"
    tunnel_ttl: int = 64
    rpdb_priority: Optional[int] = None


@dataclass(frozen=True)
class Selectors:
    local_subnets: List[str]
    remote_subnets: List[str]


@dataclass(frozen=True)
class Backend:
    role: str = ""
    underlay_ip: str = ""


@dataclass(frozen=True)
class Protocols:
    udp500: Optional[bool] = None
    udp4500: Optional[bool] = None
    esp50: Optional[bool] = None
    force_rewrite_4500_to_500: Optional[bool] = None


@dataclass(frozen=True)
class NatdRewrite:
    enabled: Optional[bool] = None
    initiator_inner_ip: str = ""


@dataclass(frozen=True)
class Ipsec:
    auto: str = ""
    local_id: str = ""
    remote_id: str = ""
    ike: str = ""
    esp: str = ""
    dpddelay: str = ""
    dpdtimeout: str = ""
    dpdaction: str = ""
    ikelifetime: str = ""
    lifetime: str = ""
    forceencaps: Optional[bool] = None
    mobike: Optional[bool] = None
    fragmentation: Optional[bool] = None
    mark: str = ""
    vti_interface: str = ""
    vti_routing: str = ""
    vti_shared: str = ""
    bidirectional_secret: Optional[bool] = None


@dataclass(frozen=True)
class PostIpsecNat:
    enabled: bool
    mode: str = "disabled"
    translated_subnets: Optional[List[str]] = None
    translated_source_ip: str = ""
    real_subnets: Optional[List[str]] = None
    core_subnets: Optional[List[str]] = None
    interface: str = ""
    output_mark: str = ""
    tcp_mss_clamp: Optional[int] = None
    route_via: str = ""
    route_dev: str = ""


@dataclass(frozen=True)
class Customer:
    id: int
    name: str
    customer_class: str
    peer: Peer
    transport: Transport
    selectors: Selectors
    backend: Optional[Backend] = None
    protocols: Optional[Protocols] = None
    natd_rewrite: Optional[NatdRewrite] = None
    ipsec: Optional[Ipsec] = None
    post_ipsec_nat: Optional[PostIpsecNat] = None


@dataclass(frozen=True)
class CustomerSource:
    schema_version: int
    customer: Customer


# Small validation helper used by the parser to fail fast on required fields.
def _require(value: Any, path: str) -> Any:
    if value in (None, "", []):
        raise ValueError(f"{path} is required")
    return value


# Normalize list-based fields such as selectors and translated subnet lists.
def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("expected list")
    return [str(item) for item in value]


# YAML will happily parse an unquoted hex mark like `0x41001` as an integer.
# We normalize it back into a hex string so the rest of the control plane sees
# a consistent representation.
def _as_hex_mark(value: Any, path: str) -> str:
    raw = _require(value, path)
    if isinstance(raw, int):
        return hex(raw)
    return str(raw)


# Normalize legacy-style boolean or YAML yes/no inputs into the strongSwan
# string shape we want in the merged customer model.
def _as_yes_no(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    normalized = str(value).strip().lower()
    if normalized in {"yes", "true"}:
        return "yes"
    if normalized in {"no", "false"}:
        return "no"
    raise ValueError(f"expected yes/no boolean-like value, got {value!r}")


# Parse a raw customer source document into the typed RPDB customer model.
# This is the main normalization step before defaults/class merge happens.
def parse_customer_source(raw: Dict[str, Any]) -> CustomerSource:
    customer = raw.get("customer") or {}
    peer = customer.get("peer") or {}
    transport = customer.get("transport") or {}
    overlay = transport.get("overlay") or {}
    selectors = customer.get("selectors") or {}
    backend = customer.get("backend") or {}
    protocols = customer.get("protocols") or {}
    natd_rewrite = customer.get("natd_rewrite") or {}
    ipsec = customer.get("ipsec") or {}
    post_ipsec_nat = customer.get("post_ipsec_nat")

    return CustomerSource(
        schema_version=int(_require(raw.get("schema_version"), "schema_version")),
        customer=Customer(
            id=int(_require(customer.get("id"), "customer.id")),
            name=str(_require(customer.get("name"), "customer.name")),
            customer_class=str(_require(customer.get("customer_class"), "customer.customer_class")),
            peer=Peer(
                public_ip=str(_require(peer.get("public_ip"), "customer.peer.public_ip")),
                psk_secret_ref=str(_require(peer.get("psk_secret_ref"), "customer.peer.psk_secret_ref")),
                remote_id=str(peer.get("remote_id") or peer.get("public_ip") or ""),
            ),
            transport=Transport(
                mark=_as_hex_mark(transport.get("mark"), "customer.transport.mark"),
                table=int(_require(transport.get("table"), "customer.transport.table")),
                tunnel_key=int(_require(transport.get("tunnel_key"), "customer.transport.tunnel_key")),
                interface=str(_require(transport.get("interface"), "customer.transport.interface")),
                tunnel_type=str(transport.get("tunnel_type") or "gre"),
                tunnel_ttl=int(transport.get("tunnel_ttl") or 64),
                rpdb_priority=(
                    int(transport["rpdb_priority"])
                    if transport.get("rpdb_priority") is not None
                    else None
                ),
                overlay=Overlay(
                    mux_ip=str(_require(overlay.get("mux_ip"), "customer.transport.overlay.mux_ip")),
                    router_ip=str(_require(overlay.get("router_ip"), "customer.transport.overlay.router_ip")),
                ),
            ),
            selectors=Selectors(
                local_subnets=_as_list(
                    _require(selectors.get("local_subnets"), "customer.selectors.local_subnets")
                ),
                remote_subnets=_as_list(
                    _require(selectors.get("remote_subnets"), "customer.selectors.remote_subnets")
                ),
            ),
            backend=(
                Backend(
                    role=str(backend.get("role") or ""),
                    underlay_ip=str(backend.get("underlay_ip") or ""),
                )
                if isinstance(backend, dict) and backend
                else None
            ),
            protocols=(
                Protocols(
                    udp500=protocols.get("udp500"),
                    udp4500=protocols.get("udp4500"),
                    esp50=protocols.get("esp50"),
                    force_rewrite_4500_to_500=protocols.get("force_rewrite_4500_to_500"),
                )
                if isinstance(protocols, dict) and protocols
                else None
            ),
            natd_rewrite=(
                NatdRewrite(
                    enabled=natd_rewrite.get("enabled"),
                    initiator_inner_ip=str(natd_rewrite.get("initiator_inner_ip") or ""),
                )
                if isinstance(natd_rewrite, dict) and natd_rewrite
                else None
            ),
            ipsec=(
                Ipsec(
                    auto=str(ipsec.get("auto") or ""),
                    local_id=str(ipsec.get("local_id") or ""),
                    remote_id=str(ipsec.get("remote_id") or ""),
                    ike=str(ipsec.get("ike") or ""),
                    esp=str(ipsec.get("esp") or ""),
                    dpddelay=str(ipsec.get("dpddelay") or ""),
                    dpdtimeout=str(ipsec.get("dpdtimeout") or ""),
                    dpdaction=str(ipsec.get("dpdaction") or ""),
                    ikelifetime=str(ipsec.get("ikelifetime") or ""),
                    lifetime=str(ipsec.get("lifetime") or ""),
                    forceencaps=ipsec.get("forceencaps"),
                    mobike=ipsec.get("mobike"),
                    fragmentation=ipsec.get("fragmentation"),
                    mark=str(ipsec.get("mark") or ""),
                    vti_interface=str(ipsec.get("vti_interface") or ""),
                    vti_routing=_as_yes_no(ipsec.get("vti_routing")),
                    vti_shared=_as_yes_no(ipsec.get("vti_shared")),
                    bidirectional_secret=ipsec.get("bidirectional_secret"),
                )
                if isinstance(ipsec, dict) and ipsec
                else None
            ),
            post_ipsec_nat=(
                PostIpsecNat(
                    enabled=bool(post_ipsec_nat.get("enabled")),
                    mode=str(post_ipsec_nat.get("mode") or "disabled"),
                    translated_subnets=_as_list(post_ipsec_nat.get("translated_subnets")),
                    translated_source_ip=str(post_ipsec_nat.get("translated_source_ip") or ""),
                    real_subnets=_as_list(post_ipsec_nat.get("real_subnets")),
                    core_subnets=_as_list(post_ipsec_nat.get("core_subnets")),
                    interface=str(post_ipsec_nat.get("interface") or ""),
                    output_mark=str(post_ipsec_nat.get("output_mark") or ""),
                    tcp_mss_clamp=(
                        int(post_ipsec_nat["tcp_mss_clamp"])
                        if post_ipsec_nat.get("tcp_mss_clamp") is not None
                        else None
                    ),
                    route_via=str(post_ipsec_nat.get("route_via") or ""),
                    route_dev=str(post_ipsec_nat.get("route_dev") or ""),
                )
                if isinstance(post_ipsec_nat, dict)
                else None
            ),
        ),
    )


# Resolve the final per-customer RPDB priority. If the customer source
# explicitly provides one, keep it. Otherwise use the configured priority base
# plus the customer ID.
def compute_rpdb_priority(priority_base: int, customer_id: int, override: Optional[int] = None) -> int:
    if override is not None:
        return int(override)
    return int(priority_base) + int(customer_id)


# Convert the merged customer module into the compact DynamoDB item shape.
# The top-level fields keep routing metadata easy to inspect, while
# `customer_json` stores the canonical merged customer module.
def build_dynamodb_item(
    source: CustomerSource,
    merged_customer_module: Dict[str, Any],
    *,
    source_ref: str,
    priority_base: int,
    updated_at: Optional[str] = None,
) -> Dict[str, Any]:
    customer = merged_customer_module.get("customer") or {}
    peer = merged_customer_module.get("peer") or {}
    transport = merged_customer_module.get("transport") or {}
    backend = merged_customer_module.get("backend") or {}
    rpdb_priority = int(
        transport.get("rpdb_priority")
        or compute_rpdb_priority(priority_base, source.customer.id, source.customer.transport.rpdb_priority)
    )
    timestamp = updated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "customer_name": customer["name"],
        "customer_id": customer["id"],
        "customer_class": customer["customer_class"],
        "peer_ip": peer["public_ip"],
        "fwmark": transport["mark"],
        "route_table": transport["table"],
        "rpdb_priority": rpdb_priority,
        "backend_role": backend.get("role"),
        "backend_underlay_ip": backend.get("underlay_ip") or None,
        "source_ref": source_ref,
        "schema_version": source.schema_version,
        "updated_at": timestamp,
        "customer_json": json.dumps(merged_customer_module, sort_keys=True, separators=(",", ":")),
    }


# Convert the typed dataclass tree back into a plain dictionary. This is used
# by the merge layer when it needs a regular dict structure to overlay.
def source_to_dict(source: CustomerSource) -> Dict[str, Any]:
    return asdict(source)
