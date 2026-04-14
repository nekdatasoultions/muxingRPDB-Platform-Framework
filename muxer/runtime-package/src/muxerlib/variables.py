#!/usr/bin/env python3
"""Shared customer variables loader for muxer and VPN-HUB rendering."""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any, Dict, List

from .core import BASE, CFG_DIR, load_yaml
from .customers import calc_overlay, customer_protocol_flags
from .dynamodb_sot import customer_sot_settings, load_customer_modules_from_dynamodb

CUSTOMERS_VARS = BASE / "config" / "customers.variables.yaml"


def _merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged.get(key, {}), value)
        else:
            merged[key] = value
    return merged


def _default_tunnel_ifname(cust_id: int, tunnel_type: str) -> str:
    if tunnel_type == "gre":
        return f"gre-cust-{cust_id:04d}"
    return f"ipip-cust-{cust_id:04d}"


def _peer_cidr(value: str) -> str:
    raw = str(value).strip()
    if "/" not in raw:
        raw = f"{raw}/32"
    ipaddress.ip_network(raw, strict=False)
    return raw


def backend_role_catalog(muxer_doc: Dict[str, Any]) -> Dict[str, Any]:
    return muxer_doc.get("backend_roles", {}) or {}


def _coerce_backend_ip(value: Any, context: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise SystemExit(f"{context}: backend underlay IP is empty")
    ipaddress.ip_address(raw)
    return raw


def resolve_backend_role(role_name: str, muxer_doc: Dict[str, Any], *, preferred_az: str = "") -> str:
    role = str(role_name or "").strip()
    if not role:
        return ""

    catalog = backend_role_catalog(muxer_doc)
    role_doc = catalog.get(role)
    if role_doc is None:
        known = ", ".join(sorted(str(name) for name in catalog)) or "(none)"
        raise SystemExit(f"Unknown backend_role '{role}'. Known roles: {known}")

    if isinstance(role_doc, str):
        return _coerce_backend_ip(role_doc, f"backend_roles.{role}")

    if not isinstance(role_doc, dict):
        raise SystemExit(f"backend_roles.{role}: expected mapping or IPv4 string")

    ip_by_az = role_doc.get("ip_by_az") or role_doc.get("az_map") or {}
    active_az = str(role_doc.get("active_az") or preferred_az or "").strip()
    if active_az and isinstance(ip_by_az, dict):
        az_entry = ip_by_az.get(active_az)
        if isinstance(az_entry, dict):
            candidate = az_entry.get("underlay_ip") or az_entry.get("backend_underlay_ip") or az_entry.get("ip")
        else:
            candidate = az_entry
        if str(candidate or "").strip():
            return _coerce_backend_ip(candidate, f"backend_roles.{role}.ip_by_az.{active_az}")

    direct = (
        role_doc.get("underlay_ip")
        or role_doc.get("backend_underlay_ip")
        or role_doc.get("ip")
        or ""
    )
    if str(direct or "").strip():
        return _coerce_backend_ip(direct, f"backend_roles.{role}")

    if isinstance(ip_by_az, dict) and len(ip_by_az) == 1:
        only_az, only_entry = next(iter(ip_by_az.items()))
        if isinstance(only_entry, dict):
            only_entry = only_entry.get("underlay_ip") or only_entry.get("backend_underlay_ip") or only_entry.get("ip")
        return _coerce_backend_ip(only_entry, f"backend_roles.{role}.ip_by_az.{only_az}")

    raise SystemExit(
        f"backend_roles.{role}: no usable underlay IP found. Define underlay_ip directly or set "
        "active_az plus ip_by_az."
    )


def resolve_backend_identity(module: Dict[str, Any], muxer_doc: Dict[str, Any]) -> Dict[str, Any]:
    resolved = dict(module)
    backend_role = str(resolved.get("backend_role") or "").strip()
    preferred_az = str(resolved.get("backend_role_az") or "").strip()

    if backend_role:
        resolved["backend_underlay_ip"] = resolve_backend_role(backend_role, muxer_doc, preferred_az=preferred_az)
    elif "backend_underlay_ip" in resolved:
        resolved["backend_underlay_ip"] = _coerce_backend_ip(
            resolved.get("backend_underlay_ip"),
            f"{resolved.get('name', 'customer')}.backend_underlay_ip",
        )

    return resolved


def resolve_backend_identities(modules: List[Dict[str, Any]], muxer_doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [resolve_backend_identity(module, muxer_doc) for module in modules]


def strict_non_nat_customer(module: Dict[str, Any]) -> bool:
    udp500, udp4500, esp50, _force = customer_protocol_flags(module)
    return udp500 and not udp4500 and esp50


def public_edge_mode(muxer_doc: Dict[str, Any]) -> str:
    public_edge = muxer_doc.get("public_edge", {}) or {}
    return str(public_edge.get("mode") or "aws_eip_association").strip()


def strict_non_nat_edge_supported(muxer_doc: Dict[str, Any]) -> bool:
    public_edge = muxer_doc.get("public_edge", {}) or {}
    if "strict_non_nat_supported" in public_edge:
        return bool(public_edge.get("strict_non_nat_supported"))

    mode = public_edge_mode(muxer_doc)
    return mode in {"igw_ingress_byoip", "native_public_l3"}


def validate_public_edge_compatibility(
    module: Dict[str, Any],
    muxer_doc: Dict[str, Any],
    *,
    allow_incompatible: bool = False,
) -> None:
    if not strict_non_nat_customer(module):
        return

    if strict_non_nat_edge_supported(muxer_doc) or allow_incompatible:
        return

    name = str(module.get("name", "unknown"))
    mode = public_edge_mode(muxer_doc)
    raise SystemExit(
        f"{name}: strict non-NAT customers are not deployable on muxer public_edge.mode="
        f"{mode}. The current edge still presents NAT-like behavior to peers. "
        "Use a strict-compatible ingress mode such as igw_ingress_byoip, reclassify the "
        "customer as NAT-T, or pass an explicit lab override if you are only reproducing the "
        "failure."
    )


def validate_customer_module(module: Dict[str, Any]) -> None:
    if not strict_non_nat_customer(module):
        return

    name = str(module.get("name", "unknown"))
    ipsec_cfg = module.get("ipsec", {}) or {}
    left_public = str(ipsec_cfg.get("left_public") or "").strip()
    local_id = str(ipsec_cfg.get("local_id") or "").strip()

    if not left_public or left_public == "%defaultroute":
        raise SystemExit(
            f"{name}: strict non-NAT customers must declare ipsec.left_public so the "
            "head-end terminates IKE as the shared public VPN identity"
        )

    ipaddress.ip_address(left_public)

    if local_id and local_id != left_public:
        raise SystemExit(
            f"{name}: strict non-NAT customers must keep ipsec.local_id aligned with "
            f"ipsec.left_public ({left_public})"
        )


def build_modules_from_variables(
    vars_doc: Dict[str, Any],
    overlay_pool: ipaddress.IPv4Network | None,
    muxer_doc: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    defaults = vars_doc.get("defaults", {}) or {}
    default_muxer = defaults.get("muxer", {}) or {}
    default_protocols = defaults.get("protocols", {}) or {}
    default_natd = defaults.get("natd_rewrite", {}) or {}
    default_ipsec = defaults.get("ipsec", {}) or {}
    default_post_ipsec_nat = defaults.get("post_ipsec_nat", {}) or {}
    customers = vars_doc.get("customers", []) or []

    modules: List[Dict[str, Any]] = []
    for customer in customers:
        if not isinstance(customer, dict):
            raise SystemExit("customers.variables.yaml: each customer entry must be a mapping")

        if "id" not in customer or "name" not in customer or "peer_ip" not in customer:
            raise SystemExit("customers.variables.yaml: each customer requires id, name, and peer_ip")

        cust_id = int(customer["id"])
        name = str(customer["name"]).strip()
        peer_ip = _peer_cidr(str(customer["peer_ip"]))

        module: Dict[str, Any] = {
            "id": cust_id,
            "name": name,
            "peer_ip": peer_ip,
        }

        protocols = _merge_dict(default_protocols, customer.get("protocols", {}) or {})
        module["protocols"] = protocols

        natd_rewrite = _merge_dict(default_natd, customer.get("natd_rewrite", {}) or {})
        if natd_rewrite:
            module["natd_rewrite"] = natd_rewrite

        ipsec_cfg = _merge_dict(default_ipsec, customer.get("ipsec", {}) or {})
        if ipsec_cfg:
            ipsec_cfg.setdefault("remote_id", peer_ip.split("/")[0])
            module["ipsec"] = ipsec_cfg

        post_ipsec_nat_cfg = _merge_dict(default_post_ipsec_nat, customer.get("post_ipsec_nat", {}) or {})
        if post_ipsec_nat_cfg:
            module["post_ipsec_nat"] = post_ipsec_nat_cfg

        if "mark" in customer:
            module["mark"] = customer["mark"]
        if "table" in customer:
            module["table"] = customer["table"]

        tunnel_type = str(customer.get("tunnel_type", default_muxer.get("tunnel_type", "ipip"))).strip().lower()
        module["tunnel_type"] = tunnel_type

        if "tunnel_ttl" in customer:
            module["tunnel_ttl"] = customer["tunnel_ttl"]
        elif "tunnel_ttl" in default_muxer:
            module["tunnel_ttl"] = default_muxer["tunnel_ttl"]

        if "inside_ip" in customer:
            module["inside_ip"] = customer["inside_ip"]
        elif "inside_ip" in default_muxer:
            module["inside_ip"] = default_muxer["inside_ip"]

        if "backend_role" in customer:
            module["backend_role"] = customer["backend_role"]
        elif "backend_role" in default_muxer:
            module["backend_role"] = default_muxer["backend_role"]

        if "backend_role_az" in customer:
            module["backend_role_az"] = customer["backend_role_az"]
        elif "backend_role_az" in default_muxer:
            module["backend_role_az"] = default_muxer["backend_role_az"]

        if "backend_underlay_ip" in customer:
            module["backend_underlay_ip"] = customer["backend_underlay_ip"]
        elif "backend_underlay_ip" in default_muxer:
            module["backend_underlay_ip"] = default_muxer["backend_underlay_ip"]

        if "ipip_ifname" in customer:
            module["ipip_ifname"] = customer["ipip_ifname"]
        else:
            module["ipip_ifname"] = _default_tunnel_ifname(cust_id, tunnel_type)

        if "tunnel_key" in customer:
            module["tunnel_key"] = customer["tunnel_key"]
        elif "tunnel_key" in default_muxer:
            module["tunnel_key"] = default_muxer["tunnel_key"]
        elif tunnel_type == "gre":
            module["tunnel_key"] = 1000 + cust_id

        if customer.get("overlay"):
            module["overlay"] = customer["overlay"]
        elif overlay_pool is not None:
            mux_ip, router_ip = calc_overlay(overlay_pool, cust_id)
            module["overlay"] = {"mux_ip": mux_ip, "router_ip": router_ip}

        validate_customer_module(module)
        modules.append(module)

    modules.sort(key=lambda item: int(item["id"]))
    if muxer_doc:
        return resolve_backend_identities(modules, muxer_doc)
    return modules


def load_modules(
    overlay_pool: ipaddress.IPv4Network | None,
    cfg_dir: Path = CFG_DIR,
    customers_vars_path: Path = CUSTOMERS_VARS,
    global_cfg: Dict[str, Any] | None = None,
    source_backend: str = "auto",
) -> List[Dict[str, Any]]:
    chosen_backend = str(source_backend or "auto").strip().lower()
    if chosen_backend == "auto" and global_cfg:
        chosen_backend, table_name, region = customer_sot_settings(global_cfg)
    elif global_cfg:
        _backend, table_name, region = customer_sot_settings(global_cfg)
    else:
        table_name = ""
        region = ""

    if chosen_backend in {"dynamodb", "ddb"}:
        modules = load_customer_modules_from_dynamodb(table_name=table_name, region=region or None)
        if global_cfg:
            return resolve_backend_identities(modules, global_cfg)
        return modules

    if customers_vars_path.exists():
        vars_doc = load_yaml(customers_vars_path) or {}
        return build_modules_from_variables(vars_doc, overlay_pool, global_cfg)

    modules: List[Dict[str, Any]] = []
    for path in sorted(cfg_dir.glob("*.y*ml")):
        data = load_yaml(path) or {}
        data["_path"] = str(path)
        modules.append(data)
    return modules
