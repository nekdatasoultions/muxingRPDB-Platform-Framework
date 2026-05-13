"""Customer source and DynamoDB item helpers for the RPDB model."""

from __future__ import annotations

# Standard library imports for JSON serialization, typed dataclasses, IP/CIDR
# validation, and stable UTC timestamps used in the DynamoDB item.
import copy
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
class CgnatPkiEndpoint:
    identity_ref: str = ""
    auth_ref: str = ""
    package_name: str = ""
    cert_ref: str = ""
    private_key_secret_ref: str = ""
    private_key_passphrase_secret_ref: str = ""


@dataclass(frozen=True)
class CgnatPkiTrust:
    ca_ref: str = ""


@dataclass(frozen=True)
class CgnatPki:
    mode: str = "reference"
    provider: str = ""
    ca_common_name: str = ""
    customer_package_format: str = "pem_bundle"
    headend: Optional[CgnatPkiEndpoint] = None
    customer: Optional[CgnatPkiEndpoint] = None
    gateway: Optional[CgnatPkiEndpoint] = None
    trust: Optional[CgnatPkiTrust] = None


@dataclass(frozen=True)
class CgnatTransport:
    service_profile: str = ""
    outer_topology: str = "per_customer_outer"
    outer_gateway_ref: str = ""
    outer_identity_ref: str = ""
    outer_auth_ref: str = ""
    customer_loopback_ip: str = ""
    known_inside_identity: str = ""
    outer_transport: Optional[Dict[str, Any]] = None
    service_reachable_subnets: Optional[List[str]] = None
    pki: Optional[CgnatPki] = None


@dataclass(frozen=True)
class Peer:
    public_ip: str
    psk_secret_ref: str = ""
    remote_id: str = ""
    psk_source: str = ""
    psk: str = ""


@dataclass(frozen=True)
class Transport:
    mark: str
    table: int
    tunnel_key: int
    interface: str
    overlay: Overlay
    mode: str = ""
    cgnat: Optional[CgnatTransport] = None
    tunnel_type: str = "gre"
    tunnel_ttl: int = 64
    tunnel_mtu: Optional[int] = None
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
class DynamicPeerIpDeviceRegistry:
    serial_number: str = ""
    password_secret_ref: str = ""
    table_name: str = ""
    serial_number_attribute: str = "serialNumber"
    current_ip_attribute: str = "currentIP"
    last_updated_attribute: str = "lastUpdated"


@dataclass(frozen=True)
class DynamicPeerIpReapply:
    mode: str = "deploy_only"
    update_remote_id_when_equal_to_peer_ip: bool = True


@dataclass(frozen=True)
class DynamicPeerIp:
    enabled: bool
    source: str = "device_registry_ddns"
    device_registry: Optional[DynamicPeerIpDeviceRegistry] = None
    reapply: Optional[DynamicPeerIpReapply] = None


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
    auth: Optional[Dict[str, Any]] = None


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
    routed_core_subnets: Optional[List[str]] = None
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
    dynamic_peer_ip: Optional[DynamicPeerIp] = None
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


def _validated_ipv4(value: Any, path: str) -> str:
    raw = str(_require(value, path)).strip()
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError as exc:
        raise ValueError(f"{path} must be a valid IPv4 address") from exc


def _validated_optional_cidr_list(value: Any, path: str) -> Optional[List[str]]:
    items = _as_optional_list(value)
    if not items:
        return None
    normalized: List[str] = []
    seen: set[str] = set()
    for idx, item in enumerate(items):
        candidate = _validated_cidr(item, f"{path}[{idx}]")
        if candidate not in seen:
            normalized.append(candidate)
            seen.add(candidate)
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


def _normalized_transport_mode(value: Any) -> str:
    if value in (None, ""):
        return ""
    normalized = str(value).strip().lower().replace("-", "_")
    allowed = {"direct_non_nat", "direct_nat_t", "cgnat"}
    if normalized not in allowed:
        raise ValueError(f"unsupported customer.transport.mode {value!r}")
    return normalized


def _normalized_cgnat_pki_mode(value: Any) -> str:
    if value in (None, ""):
        return "reference"
    normalized = str(value).strip().lower()
    aliases = {
        "provided_material": "provided",
        "third_party_provided": "provided",
        "external": "provided",
    }
    normalized = aliases.get(normalized, normalized)
    allowed = {"reference", "local_generate", "provided", "provider_api"}
    if normalized not in allowed:
        raise ValueError(f"unsupported customer.transport.cgnat.pki.mode {value!r}")
    return normalized


def _normalize_peer_psk(peer: Dict[str, Any]) -> Dict[str, str]:
    psk_secret_ref = str(peer.get("psk_secret_ref") or "").strip()
    psk = str(peer.get("psk") or "")
    raw_source = str(peer.get("psk_source") or "").strip().lower().replace("-", "_")
    if not raw_source and not psk_secret_ref and not psk:
        return {"psk_source": "", "psk_secret_ref": "", "psk": ""}
    if raw_source in {"", "aws_secrets_manager"}:
        psk_source = "local" if psk and not psk_secret_ref else "secrets_manager"
    elif raw_source in {"secrets_manager", "local"}:
        psk_source = raw_source
    else:
        raise ValueError(f"unsupported customer.peer.psk_source {raw_source!r}")

    if psk_source == "local":
        if not psk:
            raise ValueError("customer.peer.psk_source=local requires customer.peer.psk")
        if psk_secret_ref:
            raise ValueError("customer.peer.psk_secret_ref must not be set when psk_source is local")
    else:
        if not psk_secret_ref:
            raise ValueError("customer.peer.psk_secret_ref is required when psk_source is secrets_manager")
        if psk:
            raise ValueError("customer.peer.psk must not be set when psk_source is secrets_manager")

    return {
        "psk_source": "local" if psk_source == "local" else (raw_source if raw_source else ""),
        "psk_secret_ref": psk_secret_ref,
        "psk": psk,
    }


def _normalize_material_ref(value: Any, field_name: str, *, required: bool = False) -> str:
    normalized = str(value or "").strip()
    if required and not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _normalize_ipsec_auth(auth: Any) -> Dict[str, Any]:
    if auth in (None, ""):
        return {"method": "psk"}
    if not isinstance(auth, dict):
        raise ValueError("customer.ipsec.auth must be an object")

    method = str(auth.get("method") or "psk").strip().lower().replace("-", "_")
    aliases = {
        "cert": "certificate",
        "certificates": "certificate",
        "pubkey": "certificate",
        "public_key": "certificate",
    }
    method = aliases.get(method, method)
    if method not in {"psk", "certificate"}:
        raise ValueError(f"unsupported customer.ipsec.auth.method {method!r}")
    if method == "psk":
        return {"method": "psk"}

    certificate = auth.get("certificate") or {}
    if not isinstance(certificate, dict):
        raise ValueError("customer.ipsec.auth.certificate must be an object")
    headend = certificate.get("headend") or {}
    remote = certificate.get("remote") or {}
    handoff = certificate.get("customer_handoff") or {}
    if not isinstance(headend, dict) or not isinstance(remote, dict) or not isinstance(handoff, dict):
        raise ValueError("customer.ipsec.auth.certificate sections must be objects")

    profile = str(certificate.get("profile") or "third_party_provided").strip().lower().replace("-", "_")
    if profile not in {"third_party_provided", "customer_supplied"}:
        raise ValueError(f"unsupported customer.ipsec.auth.certificate.profile {profile!r}")

    normalized_headend = {
        "id": _normalize_material_ref(headend.get("id"), "customer.ipsec.auth.certificate.headend.id"),
        "cert_ref": _normalize_material_ref(
            headend.get("cert_ref"),
            "customer.ipsec.auth.certificate.headend.cert_ref",
            required=True,
        ),
        "private_key_secret_ref": _normalize_material_ref(
            headend.get("private_key_secret_ref"),
            "customer.ipsec.auth.certificate.headend.private_key_secret_ref",
            required=True,
        ),
        "private_key_passphrase_secret_ref": _normalize_material_ref(
            headend.get("private_key_passphrase_secret_ref"),
            "customer.ipsec.auth.certificate.headend.private_key_passphrase_secret_ref",
        ),
    }
    normalized_remote = {
        "id": _normalize_material_ref(
            remote.get("id"),
            "customer.ipsec.auth.certificate.remote.id",
            required=True,
        ),
        "trust_ref": _normalize_material_ref(
            remote.get("trust_ref"),
            "customer.ipsec.auth.certificate.remote.trust_ref",
            required=True,
        ),
        "cert_ref": _normalize_material_ref(
            remote.get("cert_ref"),
            "customer.ipsec.auth.certificate.remote.cert_ref",
        ),
    }
    normalized_handoff = {
        "enabled": bool(handoff.get("enabled")) if handoff else False,
        "cert_ref": _normalize_material_ref(handoff.get("cert_ref"), "customer.ipsec.auth.certificate.customer_handoff.cert_ref"),
        "private_key_secret_ref": _normalize_material_ref(
            handoff.get("private_key_secret_ref"),
            "customer.ipsec.auth.certificate.customer_handoff.private_key_secret_ref",
        ),
        "trust_ref": _normalize_material_ref(handoff.get("trust_ref"), "customer.ipsec.auth.certificate.customer_handoff.trust_ref"),
        "notes": _normalize_material_ref(handoff.get("notes"), "customer.ipsec.auth.certificate.customer_handoff.notes"),
    }

    if normalized_handoff["enabled"]:
        missing = [
            key
            for key in ("cert_ref", "private_key_secret_ref", "trust_ref")
            if not normalized_handoff.get(key)
        ]
        if missing:
            raise ValueError(
                "customer.ipsec.auth.certificate.customer_handoff enabled requires "
                + ", ".join(missing)
            )

    return {
        "method": "certificate",
        "certificate": {
            "profile": profile,
            "material_source": "provided",
            "headend": normalized_headend,
            "remote": normalized_remote,
            "customer_handoff": normalized_handoff,
        },
    }


def _normalized_cgnat_outer_topology(value: Any) -> str:
    if value in (None, ""):
        return "per_customer_outer"
    normalized = str(value).strip().lower().replace("-", "_")
    allowed = {"per_customer_outer", "shared_isp_gateway"}
    if normalized not in allowed:
        raise ValueError(f"unsupported customer.transport.cgnat.outer_topology {value!r}")
    return normalized


def _normalize_cgnat_pki_endpoint(doc: Dict[str, Any]) -> CgnatPkiEndpoint:
    return CgnatPkiEndpoint(
        identity_ref=str(doc.get("identity_ref") or ""),
        auth_ref=str(doc.get("auth_ref") or ""),
        package_name=str(doc.get("package_name") or ""),
        cert_ref=_normalize_material_ref(doc.get("cert_ref"), "customer.transport.cgnat.pki.*.cert_ref"),
        private_key_secret_ref=_normalize_material_ref(
            doc.get("private_key_secret_ref"),
            "customer.transport.cgnat.pki.*.private_key_secret_ref",
        ),
        private_key_passphrase_secret_ref=_normalize_material_ref(
            doc.get("private_key_passphrase_secret_ref"),
            "customer.transport.cgnat.pki.*.private_key_passphrase_secret_ref",
        ),
    )


def _normalize_cgnat_pki(doc: Dict[str, Any]) -> CgnatPki:
    headend_doc = doc.get("headend") or {}
    customer_doc = doc.get("customer") or {}
    gateway_doc = doc.get("gateway") or {}
    trust_doc = doc.get("trust") or {}
    customer_package_format = str(doc.get("customer_package_format") or "pem_bundle").strip().lower()
    if customer_package_format not in {"pem_bundle"}:
        raise ValueError(
            f"unsupported customer.transport.cgnat.pki.customer_package_format {customer_package_format!r}"
        )
    return CgnatPki(
        mode=_normalized_cgnat_pki_mode(doc.get("mode")),
        provider=str(doc.get("provider") or ""),
        ca_common_name=str(doc.get("ca_common_name") or ""),
        customer_package_format=customer_package_format,
        headend=(
            _normalize_cgnat_pki_endpoint(headend_doc)
            if isinstance(headend_doc, dict) and headend_doc
            else None
        ),
        customer=(
            _normalize_cgnat_pki_endpoint(customer_doc)
            if isinstance(customer_doc, dict) and customer_doc
            else None
        ),
        gateway=(
            _normalize_cgnat_pki_endpoint(gateway_doc)
            if isinstance(gateway_doc, dict) and gateway_doc
            else None
        ),
        trust=(
            CgnatPkiTrust(ca_ref=str(trust_doc.get("ca_ref") or ""))
            if isinstance(trust_doc, dict) and trust_doc
            else None
        ),
    )


def _normalize_cgnat_outer_transport(value: Any) -> Optional[Dict[str, Any]]:
    if value in (None, ""):
        return None
    if not isinstance(value, dict):
        raise ValueError("customer.transport.cgnat.outer_transport must be a mapping")

    normalized: Dict[str, Any] = {}
    for key in ("headend_underlay_interface", "headend_xfrm_interface", "gateway_customer_interface"):
        text = str(value.get(key) or "").strip()
        if text:
            normalized[key] = text

    if value.get("headend_if_id") not in (None, ""):
        normalized["headend_if_id"] = int(value["headend_if_id"])

    if value.get("customer_router_private_ip") not in (None, ""):
        normalized["customer_router_private_ip"] = _validated_ipv4(
            value.get("customer_router_private_ip"),
            "customer.transport.cgnat.outer_transport.customer_router_private_ip",
        )

    return normalized or None


def _normalize_cgnat_transport(doc: Dict[str, Any]) -> CgnatTransport:
    pki_doc = doc.get("pki") or {}
    return CgnatTransport(
        service_profile=str(doc.get("service_profile") or ""),
        outer_topology=_normalized_cgnat_outer_topology(doc.get("outer_topology")),
        outer_gateway_ref=str(doc.get("outer_gateway_ref") or ""),
        outer_identity_ref=str(doc.get("outer_identity_ref") or ""),
        outer_auth_ref=str(doc.get("outer_auth_ref") or ""),
        customer_loopback_ip=(
            _validated_ipv4(doc.get("customer_loopback_ip"), "customer.transport.cgnat.customer_loopback_ip")
            if doc.get("customer_loopback_ip") not in (None, "")
            else ""
        ),
        known_inside_identity=(
            _validated_cidr(
                doc.get("known_inside_identity"),
                "customer.transport.cgnat.known_inside_identity",
                prefixlen=32,
            )
            if doc.get("known_inside_identity") not in (None, "")
            else ""
        ),
        outer_transport=_normalize_cgnat_outer_transport(doc.get("outer_transport")),
        service_reachable_subnets=_validated_optional_cidr_list(
            doc.get("service_reachable_subnets"),
            "customer.transport.cgnat.service_reachable_subnets",
        ),
        pki=(
            _normalize_cgnat_pki(pki_doc)
            if isinstance(pki_doc, dict) and pki_doc
            else None
        ),
    )


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


def _validated_optional_mtu(value: Any, path: str) -> Optional[int]:
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
    routed_core_subnets = _as_list(doc.get("routed_core_subnets"))

    return PostIpsecNat(
        enabled=bool(doc.get("enabled")),
        mode=mapping["mode"],
        mapping_strategy=mapping["mapping_strategy"],
        translated_subnets=mapping["translated_subnets"] or None,
        translated_source_ip=str(doc.get("translated_source_ip") or ""),
        real_subnets=mapping["real_subnets"] or None,
        host_mappings=mapping["host_mappings"],
        core_subnets=core_subnets or None,
        routed_core_subnets=routed_core_subnets or None,
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


def _normalize_dynamic_peer_ip(doc: Dict[str, Any]) -> DynamicPeerIp:
    source = str(doc.get("source") or "device_registry_ddns").strip()
    if source != "device_registry_ddns":
        raise ValueError("customer.dynamic_peer_ip.source must be device_registry_ddns")

    device_registry_doc = doc.get("device_registry") or {}
    if not isinstance(device_registry_doc, dict):
        raise ValueError("customer.dynamic_peer_ip.device_registry must be a mapping")
    enabled = bool(doc.get("enabled"))
    serial_number = str(device_registry_doc.get("serial_number") or "").strip()
    password_secret_ref = str(device_registry_doc.get("password_secret_ref") or "").strip()
    if enabled and not serial_number:
        raise ValueError(
            "customer.dynamic_peer_ip.device_registry.serial_number is required when enabled"
        )
    if enabled and not password_secret_ref:
        raise ValueError(
            "customer.dynamic_peer_ip.device_registry.password_secret_ref is required when enabled"
        )

    serial_number_attribute = str(
        device_registry_doc.get("serial_number_attribute") or "serialNumber"
    ).strip()
    current_ip_attribute = str(device_registry_doc.get("current_ip_attribute") or "currentIP").strip()
    last_updated_attribute = str(
        device_registry_doc.get("last_updated_attribute") or "lastUpdated"
    ).strip()
    if not serial_number_attribute:
        raise ValueError("customer.dynamic_peer_ip.device_registry.serial_number_attribute is required")
    if not current_ip_attribute:
        raise ValueError("customer.dynamic_peer_ip.device_registry.current_ip_attribute is required")
    if not last_updated_attribute:
        raise ValueError("customer.dynamic_peer_ip.device_registry.last_updated_attribute is required")

    reapply_doc = doc.get("reapply") or {}
    if not isinstance(reapply_doc, dict):
        raise ValueError("customer.dynamic_peer_ip.reapply must be a mapping")
    reapply_mode = str(reapply_doc.get("mode") or "deploy_only").strip()
    if reapply_mode not in {"deploy_only", "remove_reapply"}:
        raise ValueError("customer.dynamic_peer_ip.reapply.mode must be deploy_only or remove_reapply")

    return DynamicPeerIp(
        enabled=enabled,
        source=source,
        device_registry=(
            DynamicPeerIpDeviceRegistry(
                serial_number=serial_number,
                password_secret_ref=password_secret_ref,
                table_name=str(device_registry_doc.get("table_name") or "").strip(),
                serial_number_attribute=serial_number_attribute,
                current_ip_attribute=current_ip_attribute,
                last_updated_attribute=last_updated_attribute,
            )
            if device_registry_doc or enabled
            else None
        ),
        reapply=DynamicPeerIpReapply(
            mode=reapply_mode,
            update_remote_id_when_equal_to_peer_ip=bool(
                reapply_doc.get("update_remote_id_when_equal_to_peer_ip", True)
            ),
        ),
    )


# Parse a raw customer source document into the typed RPDB customer model.
# This is the main normalization step before defaults/class merge happens.
def parse_customer_source(raw: Dict[str, Any]) -> CustomerSource:
    customer = raw.get("customer") or {}
    peer = customer.get("peer") or {}
    transport = customer.get("transport") or {}
    transport_mode = _normalized_transport_mode(transport.get("mode"))
    transport_cgnat_doc = transport.get("cgnat") or {}
    if isinstance(transport_cgnat_doc, dict) and transport_cgnat_doc and not transport_mode:
        transport_mode = "cgnat"
    if transport_mode and transport_mode != "cgnat" and transport_cgnat_doc:
        raise ValueError("customer.transport.cgnat requires customer.transport.mode=cgnat")
    overlay = transport.get("overlay") or {}
    selectors = customer.get("selectors") or {}
    backend = customer.get("backend") or {}
    protocols = customer.get("protocols") or {}
    natd_rewrite = customer.get("natd_rewrite") or {}
    dynamic_provisioning = customer.get("dynamic_provisioning")
    dynamic_peer_ip = customer.get("dynamic_peer_ip")
    ipsec = customer.get("ipsec") or {}
    ipsec_auth = _normalize_ipsec_auth(ipsec.get("auth") if isinstance(ipsec, dict) else None)
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
    peer_psk = _normalize_peer_psk(peer)
    if ipsec_auth.get("method") == "certificate":
        if peer_psk["psk_secret_ref"] or peer_psk["psk"]:
            raise ValueError("customer.peer PSK fields must not be set when customer.ipsec.auth.method is certificate")
    elif not peer_psk["psk_secret_ref"] and not peer_psk["psk"]:
        raise ValueError("customer.peer.psk_secret_ref is required when customer.ipsec.auth.method is psk")

    return CustomerSource(
        schema_version=int(_require(raw.get("schema_version"), "schema_version")),
        customer=Customer(
            id=int(_require(customer.get("id"), "customer.id")),
            name=str(_require(customer.get("name"), "customer.name")),
            customer_class=str(_require(customer.get("customer_class"), "customer.customer_class")),
            peer=Peer(
                public_ip=str(_require(peer.get("public_ip"), "customer.peer.public_ip")),
                psk_secret_ref=peer_psk["psk_secret_ref"],
                remote_id=str(peer.get("remote_id") or peer.get("public_ip") or ""),
                psk_source=peer_psk["psk_source"],
                psk=peer_psk["psk"],
            ),
            transport=Transport(
                mark=_as_hex_mark(transport.get("mark"), "customer.transport.mark"),
                table=int(_require(transport.get("table"), "customer.transport.table")),
                tunnel_key=int(_require(transport.get("tunnel_key"), "customer.transport.tunnel_key")),
                interface=str(_require(transport.get("interface"), "customer.transport.interface")),
                mode=transport_mode,
                cgnat=(
                    _normalize_cgnat_transport(transport_cgnat_doc)
                    if isinstance(transport_cgnat_doc, dict) and transport_cgnat_doc
                    else None
                ),
                tunnel_type=str(transport.get("tunnel_type") or "gre"),
                tunnel_ttl=int(transport.get("tunnel_ttl") or 64),
                tunnel_mtu=_validated_optional_mtu(
                    transport.get("tunnel_mtu"),
                    "customer.transport.tunnel_mtu",
                ),
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
            dynamic_peer_ip=(
                _normalize_dynamic_peer_ip(dynamic_peer_ip)
                if isinstance(dynamic_peer_ip, dict)
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
                    path_mtu=_validated_optional_mtu(
                        ipsec.get("path_mtu"),
                        "customer.ipsec.path_mtu",
                    ),
                    mark=str(ipsec.get("mark") or ""),
                    vti_interface=str(ipsec.get("vti_interface") or ""),
                    vti_routing=_as_yes_no(ipsec.get("vti_routing")),
                    vti_shared=_as_yes_no(ipsec.get("vti_shared")),
                    bidirectional_secret=ipsec.get("bidirectional_secret"),
                    initiation=_normalize_ipsec_initiation(ipsec.get("initiation")),
                    auth=ipsec_auth if ipsec_auth.get("method") != "psk" else None,
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


def _redact_inline_peer_psk(customer_module: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = copy.deepcopy(customer_module)
    peer = sanitized.get("peer") or {}
    psk_source = str(peer.get("psk_source") or "").strip().lower().replace("-", "_")
    if psk_source == "local" and "psk" in peer:
        peer["psk"] = "<redacted-local-psk>"
        peer["psk_redacted"] = True
    return sanitized


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
    customer_json = _redact_inline_peer_psk(merged_customer_module)

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
        "customer_json": json.dumps(customer_json, sort_keys=True, separators=(",", ":")),
    }


# Convert the typed dataclass tree back into a plain dictionary. This is used
# by the merge layer when it needs a regular dict structure to overlay.
def source_to_dict(source: CustomerSource) -> Dict[str, Any]:
    return asdict(source)
