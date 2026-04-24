#!/usr/bin/env python3
"""Customer model parsing and derived values."""

from __future__ import annotations

import ipaddress
from typing import Any, Dict, List, Tuple

from .core import parse_bool, parse_int


def calc_overlay(pool: ipaddress.IPv4Network, cust_id: int) -> Tuple[str, str]:
    base = int(pool.network_address)
    offset = (cust_id - 1) * 4
    net = ipaddress.IPv4Network((base + offset, 30))
    mux_ip = f"{ipaddress.IPv4Address(int(net.network_address) + 1)}/30"
    rtr_ip = f"{ipaddress.IPv4Address(int(net.network_address) + 2)}/30"
    return mux_ip, rtr_ip


def subnet_list(value: Any) -> List[str]:
    if isinstance(value, str):
        vals = [value]
    elif isinstance(value, list):
        vals = [str(x) for x in value]
    else:
        vals = []
    out_subnets: List[str] = []
    for subnet in vals:
        ipaddress.ip_network(subnet, strict=False)
        out_subnets.append(subnet)
    return out_subnets


def customer_protocol_flags(module: Dict[str, Any]) -> Tuple[bool, bool, bool, bool]:
    protocols = module.get("protocols", {}) or {}
    udp500 = parse_bool(protocols.get("udp500", True), True)
    udp4500 = parse_bool(protocols.get("udp4500", True), True)
    esp50 = parse_bool(protocols.get("esp50", True), True)
    force_4500_to_500 = parse_bool(protocols.get("force_rewrite_4500_to_500", False), False)
    return udp500, udp4500, esp50, force_4500_to_500


def customer_natd_flags(module: Dict[str, Any]) -> Tuple[bool, str]:
    natd = module.get("natd_rewrite", {}) or {}
    enabled = parse_bool(natd.get("enabled", False), False)
    inner_ip = str(natd.get("initiator_inner_ip", "")).strip()
    if inner_ip:
        ipaddress.ip_address(inner_ip)
    return enabled, inner_ip


def _append_source_ip(sources: List[str], value: Any) -> None:
    raw = str(value or "").strip()
    if not raw or raw == "%defaultroute":
        return
    normalized = str(ipaddress.ip_address(raw))
    if normalized not in sources:
        sources.append(normalized)


def customer_headend_egress_sources(module: Dict[str, Any], backend_underlay_ip: str) -> List[str]:
    """Return every encrypted-source IP the muxer must SNAT for this customer."""

    sources: List[str] = []
    _append_source_ip(sources, backend_underlay_ip)
    for field_name in ("headend_egress_sources", "headend_egress_source_ips"):
        for source_ip in module.get(field_name) or []:
            _append_source_ip(sources, source_ip)

    backend = module.get("backend") or {}
    for source_ip in backend.get("egress_source_ips") or []:
        _append_source_ip(sources, source_ip)

    original_backend = ((module.get("_rpdb_original") or {}).get("backend") or {})
    for source_ip in original_backend.get("egress_source_ips") or []:
        _append_source_ip(sources, source_ip)

    ipsec_cfg = module.get("ipsec", {}) or {}
    _append_source_ip(sources, ipsec_cfg.get("left_public"))
    return sources


def customer_tunnel_settings(
    module: Dict[str, Any],
    name: str,
    cid: int,
) -> Tuple[str, str, int, int | None, int | None]:
    mode = str(module.get("tunnel_type", "ipip")).strip().lower()
    if mode not in {"ipip", "gre"}:
        raise SystemExit(f"{name}: unsupported tunnel_type '{mode}'")

    ifname = str(module.get("ipip_ifname", f"{mode}-{name}"))
    ttl = parse_int(module.get("tunnel_ttl", 64), 64)

    key_raw = module.get("tunnel_key", None)
    key: int | None = None
    if key_raw is not None:
        key = parse_int(key_raw, 0)
    mtu_raw = module.get("tunnel_mtu", None)
    mtu: int | None = None
    if mtu_raw not in (None, ""):
        mtu = parse_int(mtu_raw, 0)
        if mtu < 576 or mtu > 65535:
            raise SystemExit(f"{name}: tunnel_mtu must be between 576 and 65535")
    if mode == "ipip" and key is not None:
        raise SystemExit(f"{name}: tunnel_key is valid only for GRE tunnel_type")
    if mode == "gre" and key is None:
        key = 1000 + cid

    return mode, ifname, ttl, key, mtu
