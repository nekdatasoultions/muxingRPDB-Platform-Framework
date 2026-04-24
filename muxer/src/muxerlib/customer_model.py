"""Customer source and DynamoDB item helpers for the RPDB model."""

from __future__ import annotations

# Standard library imports for JSON serialization, typed dataclasses, IP/CIDR
# validation, and stable UTC timestamps used in the DynamoDB item.
import ipaddress
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
    remote_host_cidrs: Optional[List[str]] = None


@dataclass(frozen=True)
class Backend:
    role: str = ""
    cluster: str = ""
    assignment: str = ""
    underlay_ip: str = ""
    egress_source_ips: Optional[List[str]] = None


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
class DynamicProvisioningTrigger:
    protocol: str = "udp"
    destination_port: int = 4500
    require_initial_udp500_observation: bool = True
    observation_window_seconds: int = 300
    confirmation_packets: int = 1


@dataclass(frozen=True)
class DynamicProvisioningPromotion:
    customer_class: str = "nat"
    backend_cluster: str = "nat"
    backend_assignment: str = ""
    backend_role: str = ""
    protocols: Optional[Protocols] = None


@dataclass(frozen=True)
class DynamicProvisioning:
    enabled: bool
    mode: str = "nat_t_auto_promote"
    initial_customer_class: str = "strict-non-nat"
    initial_backend_cluster: str = "non-nat"
    trigger: Optional[DynamicProvisioningTrigger] = None
    promotion: Optional[DynamicProvisioningPromotion] = None


@dataclass(frozen=True)
class IpsecInitiation:
    mode: str = "bidirectional"
    headend_can_initiate: bool = True
    customer_can_initiate: bool = True
    traffic_can_start_tunnel: bool = True
    bring_up_on_apply: bool = True
    swanctl_start_action: str = "trap|start"


@dataclass(frozen=True)
class Ipsec:
    auto: str = ""
    ike_version: str = ""
    local_id: str = ""
    remote_id: str = ""
    ike: str = ""
    esp: str = ""
    ike_policies: Optional[List[str]] = None
    esp_policies: Optional[List[str]] = None
    dpddelay: str = ""
    dpdtimeout: str = ""
    dpdaction: str = ""
    ikelifetime: str = ""
    lifetime: str = ""
    replay_protection: Optional[bool] = None
    pfs_required: Optional[bool] = None
    pfs_groups: Optional[List[str]] = None
    forceencaps: Optional[bool] = None
    mobike: Optional[bool] = None
    fragmentation: Optional[bool] = None
    clear_df_bit: Optional[bool] = None
    path_mtu: Optional[int] = None
    mark: str = ""
    vti_interface: str = ""
    vti_routing: str = ""
    vti_shared: str = ""
    bidirectional_secret: Optional[bool] = None
    initiation: Optional[IpsecInitiation] = None


@dataclass(frozen=True)
class HostMapping:
    real_ip: str
    translated_ip: str


@dataclass(frozen=True)
class PostIpsecNat:
    enabled: bool
    mode: str = "disabled"
    mapping_strategy: str = ""
    translated_subnets: Optional[List[str]] = None
    translated_source_ip: str = ""
    real_subnets: Optional[List[str]] = None
    host_mappings: Optional[List[HostMapping]] = None
    core_subnets: Optional[List[str]] = None
    interface: str = ""
    output_mark: str = ""
    tcp_mss_clamp: Optional[int] = None
    route_via: str = ""
    route_dev: str = ""


@dataclass(frozen=True)
class OutsideNat:
    enabled: bool
    mode: str = "disabled"
    mapping_strategy: str = ""
    translated_subnets: Optional[List[str]] = None
    real_subnets: Optional[List[str]] = None
    host_mappings: Optional[List[HostMapping]] = None
    customer_sources: Optional[List[str]] = None
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
    dynamic_provisioning: Optional[DynamicProvisioning] = None
    ipsec: Optional[Ipsec] = None
    post_ipsec_nat: Optional[PostIpsecNat] = None
    outside_nat: Optional[OutsideNat] = None


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


def _as_optional_list(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    items = _as_list(value)
    return items or None


def _as_optional_ipv4_list(value: Any, path: str) -> Optional[List[str]]:
    items = _as_optional_list(value)
    if not items:
        return None
    normalized: List[str] = []
    seen: set[str] = set()
    for idx, item in enumerate(items):
        try:
            normalized_ip = str(ipaddress.ip_address(str(item).strip()))
        except ValueError as exc:
            raise ValueError(f"{path}[{idx}] must be a valid IPv4 address") from exc
        if normalized_ip not in seen:
            normalized.append(normalized_ip)
            seen.add(normalized_ip)
    return normalized or None


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


def _normalized_ike_version(value: Any) -> str:
    if value in (None, ""):
        return ""
    normalized = str(value).strip().lower().replace("_", "").replace("-", "")
    aliases = {
        "v1": "ikev1",
        "ikev1": "ikev1",
        "1": "ikev1",
        "v2": "ikev2",
        "ikev2": "ikev2",
        "2": "ikev2",
        "auto": "auto",
    }
    if normalized not in aliases:
        raise ValueError(f"unsupported ike_version {value!r}")
    return aliases[normalized]


def _normalized_swanctl_start_action(value: Any) -> str:
    if value in (None, ""):
        return ""
    normalized = str(value).strip().lower().replace(" ", "")
    if normalized == "start|trap":
        normalized = "trap|start"
    allowed = {"none", "start", "trap", "trap|start"}
    if normalized not in allowed:
        raise ValueError(f"unsupported swanctl_start_action {value!r}")
    return normalized


def _normalize_ipsec_initiation(value: Any) -> Optional[IpsecInitiation]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("customer.ipsec.initiation expected mapping")

    mode = str(value.get("mode") or "bidirectional").strip().lower().replace("-", "_")
    allowed_modes = {"bidirectional", "headend_only", "customer_only", "responder_only"}
    if mode not in allowed_modes:
        raise ValueError(f"unsupported customer.ipsec.initiation.mode {value.get('mode')!r}")

    default_headend = mode in {"bidirectional", "headend_only"}
    default_customer = mode in {"bidirectional", "customer_only", "responder_only"}
    headend_can_initiate = bool(value.get("headend_can_initiate", default_headend))
    customer_can_initiate = bool(value.get("customer_can_initiate", default_customer))
    traffic_can_start_tunnel = bool(value.get("traffic_can_start_tunnel", mode != "headend_only"))
    bring_up_on_apply = bool(value.get("bring_up_on_apply", headend_can_initiate))
    swanctl_start_action = _normalized_swanctl_start_action(value.get("swanctl_start_action"))
    if not swanctl_start_action:
        if bring_up_on_apply and traffic_can_start_tunnel:
            swanctl_start_action = "trap|start"
        elif bring_up_on_apply:
            swanctl_start_action = "start"
        elif traffic_can_start_tunnel:
            swanctl_start_action = "trap"
        else:
            swanctl_start_action = "none"

    if mode == "bidirectional" and (not headend_can_initiate or not customer_can_initiate):
        raise ValueError("customer.ipsec.initiation.mode=bidirectional requires both endpoints to initiate")
    if bring_up_on_apply and not headend_can_initiate:
        raise ValueError("customer.ipsec.initiation.bring_up_on_apply requires headend_can_initiate")
    if bring_up_on_apply and "start" not in swanctl_start_action:
        raise ValueError("customer.ipsec.initiation.bring_up_on_apply requires swanctl_start_action with start")
    if traffic_can_start_tunnel and "trap" not in swanctl_start_action:
        raise ValueError("customer.ipsec.initiation.traffic_can_start_tunnel requires swanctl_start_action with trap")

    return IpsecInitiation(
        mode=mode,
        headend_can_initiate=headend_can_initiate,
        customer_can_initiate=customer_can_initiate,
        traffic_can_start_tunnel=traffic_can_start_tunnel,
        bring_up_on_apply=bring_up_on_apply,
        swanctl_start_action=swanctl_start_action,
    )


def _validated_cidr(value: Any, path: str, *, prefixlen: int | None = None) -> str:
    text = str(_require(value, path))
    try:
        network = ipaddress.ip_network(text, strict=False)
    except ValueError as exc:
        raise ValueError(f"{path} must be a valid CIDR") from exc
    if prefixlen is not None and network.prefixlen != prefixlen:
        raise ValueError(f"{path} must use /{prefixlen}")
    return text


def _validated_path_mtu(value: Any, path: str) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        mtu = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{path} must be an integer") from exc
    if mtu < 576:
        raise ValueError(f"{path} must be at least 576")
    if mtu > 65535:
        raise ValueError(f"{path} must be at most 65535")
    return mtu


def _parse_host_mappings(value: Any, path: str) -> Optional[List[HostMapping]]:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError(f"{path} expected list")
    mappings: List[HostMapping] = []
    for idx, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"{path}[{idx}] expected mapping")
        real_ip = _validated_cidr(item.get("real_ip"), f"{path}[{idx}].real_ip", prefixlen=32)
        translated_ip = _validated_cidr(
            item.get("translated_ip"),
            f"{path}[{idx}].translated_ip",
            prefixlen=32,
        )
        mappings.append(HostMapping(real_ip=real_ip, translated_ip=translated_ip))
    return mappings or None


def _as_optional_remote_selector_cidr_list(
    value: Any,
    path: str,
    remote_subnets: List[str],
) -> Optional[List[str]]:
    items = _as_optional_list(value)
    if not items:
        return None
    parent_networks = [
        ipaddress.ip_network(str(subnet), strict=False)
        for subnet in remote_subnets
    ]
    normalized: List[str] = []
    seen: set[str] = set()
    for idx, item in enumerate(items):
        candidate = ipaddress.ip_network(
            _validated_cidr(item, f"{path}[{idx}]"),
            strict=False,
        )
        if not any(candidate.subnet_of(parent) for parent in parent_networks):
            raise ValueError(
                f"{path}[{idx}] must be contained by customer.selectors.remote_subnets"
            )
        candidate_text = str(candidate)
        if candidate_text not in seen:
            normalized.append(candidate_text)
            seen.add(candidate_text)
    return normalized or None


def _ensure_same_prefix_size(real_subnets: List[str], translated_subnets: List[str], path: str) -> None:
    if len(real_subnets) != len(translated_subnets):
        raise ValueError(
            f"{path} one_to_one mapping requires the same number of real_subnets and translated_subnets"
        )
    for idx, (real_subnet, translated_subnet) in enumerate(zip(real_subnets, translated_subnets)):
        real_network = ipaddress.ip_network(real_subnet, strict=False)
        translated_network = ipaddress.ip_network(translated_subnet, strict=False)
        if real_network.num_addresses != translated_network.num_addresses:
            raise ValueError(
                f"{path} one_to_one mapping requires matching block sizes at index {idx}"
            )


def _address_in_any_subnet(ip_text: str, subnet_texts: List[str]) -> bool:
    address = ipaddress.ip_network(ip_text, strict=False).network_address
    return any(address in ipaddress.ip_network(subnet_text, strict=False) for subnet_text in subnet_texts)


def _normalize_nat_mapping_fields(doc: Dict[str, Any], path: str) -> Dict[str, Any]:
    translated_subnets = _as_list(doc.get("translated_subnets"))
    real_subnets = _as_list(doc.get("real_subnets"))
    host_mappings = _parse_host_mappings(doc.get("host_mappings"), f"{path}.host_mappings")

    raw_mode = str(doc.get("mode") or "").strip()
    raw_strategy = str(doc.get("mapping_strategy") or "").strip()
    mode = raw_mode or "disabled"
    mapping_strategy = raw_strategy

    if host_mappings and not mapping_strategy:
        mapping_strategy = "explicit_host_map"

    if mapping_strategy == "one_to_one" and host_mappings:
        raise ValueError(f"{path} one_to_one mapping does not use host_mappings")

    if mapping_strategy == "one_to_one":
        if not real_subnets or not translated_subnets:
            raise ValueError(
                f"{path}.mapping_strategy=one_to_one requires real_subnets and translated_subnets"
            )
        _ensure_same_prefix_size(real_subnets, translated_subnets, path)
        if raw_mode and mode != "netmap":
            raise ValueError(f"{path} one_to_one mapping requires mode=netmap")
        mode = "netmap"

    if mapping_strategy == "explicit_host_map":
        if not host_mappings:
            raise ValueError(
                f"{path}.mapping_strategy=explicit_host_map requires host_mappings"
            )
        if not translated_subnets:
            raise ValueError(
                f"{path}.mapping_strategy=explicit_host_map requires translated_subnets"
            )
        translated_seen: set[str] = set()
        real_seen: set[str] = set()
        for idx, host_mapping in enumerate(host_mappings):
            if host_mapping.real_ip in real_seen:
                raise ValueError(
                    f"{path}.host_mappings[{idx}].real_ip is duplicated"
                )
            if host_mapping.translated_ip in translated_seen:
                raise ValueError(
                    f"{path}.host_mappings[{idx}].translated_ip is duplicated"
                )
            real_seen.add(host_mapping.real_ip)
            translated_seen.add(host_mapping.translated_ip)

            if real_subnets and not _address_in_any_subnet(host_mapping.real_ip, real_subnets):
                raise ValueError(
                    f"{path}.host_mappings[{idx}].real_ip is outside real_subnets"
                )
            if not _address_in_any_subnet(host_mapping.translated_ip, translated_subnets):
                raise ValueError(
                    f"{path}.host_mappings[{idx}].translated_ip is outside translated_subnets"
                )
        if raw_mode and mode != "explicit_map":
            raise ValueError(f"{path} explicit host mappings require mode=explicit_map")
        mode = "explicit_map"

    if mode == "explicit_map":
        if not host_mappings:
            raise ValueError(f"{path} mode=explicit_map requires host_mappings")
        if not translated_subnets:
            raise ValueError(f"{path} mode=explicit_map requires translated_subnets")
        if not mapping_strategy:
            mapping_strategy = "explicit_host_map"

    return {
        "mode": mode,
        "mapping_strategy": mapping_strategy,
        "translated_subnets": translated_subnets,
        "real_subnets": real_subnets,
        "host_mappings": host_mappings,
    }


def _normalize_post_ipsec_nat(doc: Dict[str, Any]) -> PostIpsecNat:
    mapping = _normalize_nat_mapping_fields(doc, "customer.post_ipsec_nat")
    core_subnets = _as_list(doc.get("core_subnets"))

    return PostIpsecNat(
        enabled=bool(doc.get("enabled")),
        mode=mapping["mode"],
        mapping_strategy=mapping["mapping_strategy"],
        translated_subnets=mapping["translated_subnets"] or None,
        translated_source_ip=str(doc.get("translated_source_ip") or ""),
        real_subnets=mapping["real_subnets"] or None,
        host_mappings=mapping["host_mappings"],
        core_subnets=core_subnets or None,
        interface=str(doc.get("interface") or ""),
        output_mark=str(doc.get("output_mark") or ""),
        tcp_mss_clamp=(
            int(doc["tcp_mss_clamp"])
            if doc.get("tcp_mss_clamp") is not None
            else None
        ),
        route_via=str(doc.get("route_via") or ""),
        route_dev=str(doc.get("route_dev") or ""),
    )


def _normalize_outside_nat(doc: Dict[str, Any]) -> OutsideNat:
    mapping = _normalize_nat_mapping_fields(doc, "customer.outside_nat")
    customer_sources = _as_list(doc.get("customer_sources"))
    return OutsideNat(
        enabled=bool(doc.get("enabled")),
        mode=mapping["mode"],
        mapping_strategy=mapping["mapping_strategy"],
        translated_subnets=mapping["translated_subnets"] or None,
        real_subnets=mapping["real_subnets"] or None,
        host_mappings=mapping["host_mappings"],
        customer_sources=customer_sources or None,
        interface=str(doc.get("interface") or ""),
        output_mark=str(doc.get("output_mark") or ""),
        tcp_mss_clamp=(
            int(doc["tcp_mss_clamp"])
            if doc.get("tcp_mss_clamp") is not None
            else None
        ),
        route_via=str(doc.get("route_via") or ""),
        route_dev=str(doc.get("route_dev") or ""),
    )


def _normalize_dynamic_provisioning(doc: Dict[str, Any]) -> DynamicProvisioning:
    trigger_doc = doc.get("trigger") or {}
    promotion_doc = doc.get("promotion") or {}
    promotion_protocols = promotion_doc.get("protocols") or {}
    mode = str(doc.get("mode") or "nat_t_auto_promote").strip()
    initial_customer_class = str(doc.get("initial_customer_class") or "strict-non-nat")
    initial_backend_cluster = str(doc.get("initial_backend_cluster") or "non-nat")
    if mode != "nat_t_auto_promote":
        raise ValueError("customer.dynamic_provisioning.mode must be nat_t_auto_promote")
    if initial_customer_class != "strict-non-nat":
        raise ValueError("customer.dynamic_provisioning.initial_customer_class must be strict-non-nat")
    if initial_backend_cluster != "non-nat":
        raise ValueError("customer.dynamic_provisioning.initial_backend_cluster must be non-nat")

    trigger = DynamicProvisioningTrigger(
        protocol=str(trigger_doc.get("protocol") or "udp").strip().lower(),
        destination_port=int(trigger_doc.get("destination_port") or 4500),
        require_initial_udp500_observation=bool(
            trigger_doc.get("require_initial_udp500_observation", True)
        ),
        observation_window_seconds=int(trigger_doc.get("observation_window_seconds") or 300),
        confirmation_packets=int(trigger_doc.get("confirmation_packets") or 1),
    )
    if trigger.protocol != "udp":
        raise ValueError("customer.dynamic_provisioning.trigger.protocol must be udp")
    if trigger.destination_port != 4500:
        raise ValueError("customer.dynamic_provisioning.trigger.destination_port must be 4500")
    if trigger.observation_window_seconds < 1:
        raise ValueError("customer.dynamic_provisioning.trigger.observation_window_seconds must be positive")
    if trigger.confirmation_packets < 1:
        raise ValueError("customer.dynamic_provisioning.trigger.confirmation_packets must be positive")

    promotion = DynamicProvisioningPromotion(
        customer_class=str(promotion_doc.get("customer_class") or "nat"),
        backend_cluster=str(promotion_doc.get("backend_cluster") or "nat"),
        backend_assignment=str(promotion_doc.get("backend_assignment") or ""),
        backend_role=str(promotion_doc.get("backend_role") or ""),
        protocols=(
            Protocols(
                udp500=promotion_protocols.get("udp500"),
                udp4500=promotion_protocols.get("udp4500"),
                esp50=promotion_protocols.get("esp50"),
                force_rewrite_4500_to_500=promotion_protocols.get("force_rewrite_4500_to_500"),
            )
            if isinstance(promotion_protocols, dict) and promotion_protocols
            else None
        ),
    )
    if promotion.customer_class != "nat":
        raise ValueError("customer.dynamic_provisioning.promotion.customer_class must be nat")
    if promotion.backend_cluster != "nat":
        raise ValueError("customer.dynamic_provisioning.promotion.backend_cluster must be nat")

    return DynamicProvisioning(
        enabled=bool(doc.get("enabled")),
        mode=mode,
        initial_customer_class=initial_customer_class,
        initial_backend_cluster=initial_backend_cluster,
        trigger=trigger,
        promotion=promotion,
    )


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
    dynamic_provisioning = customer.get("dynamic_provisioning")
    ipsec = customer.get("ipsec") or {}
    post_ipsec_nat = customer.get("post_ipsec_nat")
    outside_nat = customer.get("outside_nat")
    selector_local_subnets = _as_list(
        _require(selectors.get("local_subnets"), "customer.selectors.local_subnets")
    )
    selector_remote_subnets = _as_list(
        _require(selectors.get("remote_subnets"), "customer.selectors.remote_subnets")
    )
    selector_remote_host_cidrs = _as_optional_remote_selector_cidr_list(
        selectors.get("remote_host_cidrs"),
        "customer.selectors.remote_host_cidrs",
        selector_remote_subnets,
    )

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
                local_subnets=selector_local_subnets,
                remote_subnets=selector_remote_subnets,
                remote_host_cidrs=selector_remote_host_cidrs,
            ),
            backend=(
                Backend(
                    role=str(backend.get("role") or ""),
                    cluster=str(backend.get("cluster") or ""),
                    assignment=str(backend.get("assignment") or ""),
                    underlay_ip=str(backend.get("underlay_ip") or ""),
                    egress_source_ips=_as_optional_ipv4_list(
                        backend.get("egress_source_ips"),
                        "customer.backend.egress_source_ips",
                    ),
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
            dynamic_provisioning=(
                _normalize_dynamic_provisioning(dynamic_provisioning)
                if isinstance(dynamic_provisioning, dict)
                else None
            ),
            ipsec=(
                Ipsec(
                    auto=str(ipsec.get("auto") or ""),
                    ike_version=_normalized_ike_version(ipsec.get("ike_version")),
                    local_id=str(ipsec.get("local_id") or ""),
                    remote_id=str(ipsec.get("remote_id") or ""),
                    ike=str(ipsec.get("ike") or ""),
                    esp=str(ipsec.get("esp") or ""),
                    ike_policies=_as_optional_list(ipsec.get("ike_policies")),
                    esp_policies=_as_optional_list(ipsec.get("esp_policies")),
                    dpddelay=str(ipsec.get("dpddelay") or ""),
                    dpdtimeout=str(ipsec.get("dpdtimeout") or ""),
                    dpdaction=str(ipsec.get("dpdaction") or ""),
                    ikelifetime=str(ipsec.get("ikelifetime") or ""),
                    lifetime=str(ipsec.get("lifetime") or ""),
                    replay_protection=ipsec.get("replay_protection"),
                    pfs_required=ipsec.get("pfs_required"),
                    pfs_groups=_as_optional_list(ipsec.get("pfs_groups")),
                    forceencaps=ipsec.get("forceencaps"),
                    mobike=ipsec.get("mobike"),
                    fragmentation=ipsec.get("fragmentation"),
                    clear_df_bit=ipsec.get("clear_df_bit"),
                    path_mtu=_validated_path_mtu(ipsec.get("path_mtu"), "customer.ipsec.path_mtu"),
                    mark=str(ipsec.get("mark") or ""),
                    vti_interface=str(ipsec.get("vti_interface") or ""),
                    vti_routing=_as_yes_no(ipsec.get("vti_routing")),
                    vti_shared=_as_yes_no(ipsec.get("vti_shared")),
                    bidirectional_secret=ipsec.get("bidirectional_secret"),
                    initiation=_normalize_ipsec_initiation(ipsec.get("initiation")),
                )
                if isinstance(ipsec, dict) and ipsec
                else None
            ),
            post_ipsec_nat=(
                _normalize_post_ipsec_nat(post_ipsec_nat)
                if isinstance(post_ipsec_nat, dict)
                else None
            ),
            outside_nat=(
                _normalize_outside_nat(outside_nat)
                if isinstance(outside_nat, dict)
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
        "backend_cluster": backend.get("cluster") or None,
        "backend_assignment": backend.get("assignment") or None,
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
