#!/usr/bin/env python3
"""Derived RPDB dataplane artifacts for nftables-only runtime planning."""

from __future__ import annotations

import ipaddress
from typing import Any, Dict, List

from .customers import (
    calc_overlay,
    customer_headend_egress_sources,
    customer_protocol_flags,
    customer_tunnel_settings,
)
from .nftables import (
    normalize_passthrough_bridge_backend,
    normalize_passthrough_classification_backend,
    normalize_passthrough_translation_backend,
)
from .variables import strict_non_nat_customer


def _normalize_networks(values: List[Any]) -> List[str]:
    normalized: List[str] = []
    for value in values or []:
        raw = str(value).strip()
        if raw:
            normalized.append(str(ipaddress.ip_network(raw, strict=False)))
    return normalized


def _normalize_host_ip(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "/" in raw:
        return str(ipaddress.ip_interface(raw))
    return f"{ipaddress.ip_address(raw)}/32"


def _first_host_ip(cidr: str) -> str:
    network = ipaddress.ip_network(str(cidr), strict=False)
    if network.num_addresses == 1:
        return f"{network.network_address}/{network.max_prefixlen}"
    return f"{next(network.hosts())}/{network.max_prefixlen}"


def _merge_overlay(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base or {})
    for key, value in (override or {}).items():
        if value is not None:
            merged[key] = value
    return merged


def _compat_post_ipsec_nat(module: Dict[str, Any]) -> Dict[str, Any]:
    ipsec_cfg = module.get("ipsec", {}) or {}
    _udp500, udp4500, _esp50, _force = customer_protocol_flags(module)
    translated_subnets = _normalize_networks(ipsec_cfg.get("local_subnets") or [])
    mark_out = str(ipsec_cfg.get("mark_out") or "").strip()
    if not translated_subnets or not udp4500 or not mark_out:
        return {}
    return {
        "enabled": True,
        "mode": "snat_pool",
        "source": "compatibility_from_ipsec_local_subnets",
        "interface": "nat-pool0",
        "translated_subnets": translated_subnets,
        "translated_source_ip": _first_host_ip(translated_subnets[0]),
        "remote_subnets": _normalize_networks(ipsec_cfg.get("remote_subnets") or []),
        "output_mark": mark_out,
        "tcp_mss_clamp": 1360,
        "apply_context": "root",
    }


def _post_ipsec_rule(purpose: str, details: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "purpose": purpose,
        "activation_backend": "nftables",
        "details": details,
    }


def derive_post_ipsec_nat(module: Dict[str, Any]) -> Dict[str, Any]:
    ipsec_cfg = module.get("ipsec", {}) or {}
    compat_cfg = _compat_post_ipsec_nat(module)
    explicit_cfg = module.get("post_ipsec_nat", {}) or {}
    merged_cfg = _merge_overlay(compat_cfg, explicit_cfg)

    raw_enabled = merged_cfg.get("enabled")
    enabled = bool(merged_cfg) if raw_enabled is None else bool(raw_enabled)
    if not enabled:
        return {
            "enabled": False,
            "mode": "disabled",
            "source": "not_configured",
            "compatibility_mode": False,
            "translated_subnets": [],
            "translated_source_ip": "",
            "remote_subnets": [],
            "real_subnets": [],
            "core_subnets": [],
            "output_mark": "",
            "interface": "",
            "tcp_mss_clamp": None,
            "apply_context": "",
            "rules": {
                "local_identity_rules": [],
                "output_mark_rules": [],
                "prerouting_mark_rules": [],
                "tcp_mss_rules": [],
                "forward_tcp_mss_rules": [],
                "core_reply_mark_rules": [],
                "core_reply_tcp_mss_rules": [],
                "netmap_prerouting_rules": [],
                "netmap_postrouting_rules": [],
                "route_rules": [],
            },
            "activation_backend": "nftables",
            "apply_commands": [],
            "rollback_commands": [],
            "blocked_apply_commands": [],
            "blocked_rollback_commands": [],
        }

    mode = str(merged_cfg.get("mode") or "snat_pool").strip().lower()
    translated_subnets = _normalize_networks(merged_cfg.get("translated_subnets") or [])
    raw_translated_source_ip = (
        explicit_cfg.get("translated_source_ip")
        if explicit_cfg
        else merged_cfg.get("translated_source_ip")
    )
    if raw_translated_source_ip is None:
        translated_source_default = "" if mode == "netmap" else ((translated_subnets and _first_host_ip(translated_subnets[0])) or "")
    else:
        translated_source_default = raw_translated_source_ip
    translated_source_ip = _normalize_host_ip(translated_source_default)
    remote_subnets = _normalize_networks(merged_cfg.get("remote_subnets") or ipsec_cfg.get("remote_subnets") or [])
    real_subnets = _normalize_networks(merged_cfg.get("real_subnets") or [])
    core_subnets = _normalize_networks(merged_cfg.get("core_subnets") or [])
    output_mark = str(merged_cfg.get("output_mark") or ipsec_cfg.get("mark_out") or "").strip()
    interface = str(merged_cfg.get("interface") or "nat-pool0").strip()
    apply_context = str(merged_cfg.get("apply_context") or "root").strip()
    route_via = str(merged_cfg.get("route_via") or "").strip()
    route_dev = str(merged_cfg.get("route_dev") or "").strip()
    tcp_mss_clamp = merged_cfg.get("tcp_mss_clamp")
    tcp_mss_value = int(tcp_mss_clamp) if tcp_mss_clamp not in {None, ""} else None

    local_identity_rules: List[Dict[str, Any]] = []
    output_mark_rules: List[Dict[str, Any]] = []
    prerouting_mark_rules: List[Dict[str, Any]] = []
    tcp_mss_rules: List[Dict[str, Any]] = []
    forward_tcp_mss_rules: List[Dict[str, Any]] = []
    core_reply_mark_rules: List[Dict[str, Any]] = []
    core_reply_tcp_mss_rules: List[Dict[str, Any]] = []
    netmap_prerouting_rules: List[Dict[str, Any]] = []
    netmap_postrouting_rules: List[Dict[str, Any]] = []
    route_rules: List[Dict[str, Any]] = []

    if translated_source_ip:
        local_identity_rules.append(
            _post_ipsec_rule(
                "Assign translated source identity before nftables post-IPsec NAT activation",
                {
                    "interface": interface,
                    "translated_source_ip": translated_source_ip,
                },
            )
        )
    if mode != "netmap" and output_mark:
        for translated_subnet in translated_subnets:
            for remote_subnet in remote_subnets:
                output_mark_rules.append(
                    _post_ipsec_rule(
                        "Mark translated egress traffic with the customer IPsec mark",
                        {
                            "translated_subnet": translated_subnet,
                            "remote_subnet": remote_subnet,
                            "output_mark": output_mark,
                        },
                    )
                )
                prerouting_mark_rules.append(
                    _post_ipsec_rule(
                        "Mark forwarded translated traffic with the customer IPsec mark",
                        {
                            "translated_subnet": translated_subnet,
                            "remote_subnet": remote_subnet,
                            "output_mark": output_mark,
                        },
                    )
                )
    if mode != "netmap" and tcp_mss_value is not None:
        for translated_subnet in translated_subnets:
            for remote_subnet in remote_subnets:
                tcp_mss_rules.append(
                    _post_ipsec_rule(
                        "Clamp translated egress TCP MSS through nftables",
                        {
                            "translated_subnet": translated_subnet,
                            "remote_subnet": remote_subnet,
                            "tcp_mss": tcp_mss_value,
                        },
                    )
                )
                forward_tcp_mss_rules.append(
                    _post_ipsec_rule(
                        "Clamp translated forward TCP MSS through nftables",
                        {
                            "translated_subnet": translated_subnet,
                            "remote_subnet": remote_subnet,
                            "tcp_mss": tcp_mss_value,
                        },
                    )
                )
    if mode == "netmap" and real_subnets and translated_subnets and core_subnets:
        for real_subnet, translated_subnet in zip(real_subnets, translated_subnets):
            for core_subnet in core_subnets:
                if output_mark:
                    core_reply_mark_rules.append(
                        _post_ipsec_rule(
                            "Mark core replies for the customer IPsec context through nftables",
                            {
                                "core_subnet": core_subnet,
                                "translated_subnet": translated_subnet,
                                "output_mark": output_mark,
                            },
                        )
                    )
                if tcp_mss_value is not None:
                    core_reply_tcp_mss_rules.append(
                        _post_ipsec_rule(
                            "Clamp core reply TCP MSS through nftables",
                            {
                                "core_subnet": core_subnet,
                                "real_subnet": real_subnet,
                                "tcp_mss": tcp_mss_value,
                            },
                        )
                    )
                netmap_prerouting_rules.append(
                    _post_ipsec_rule(
                        "Map translated customer space back to real customer space through nftables",
                        {
                            "core_subnet": core_subnet,
                            "translated_subnet": translated_subnet,
                            "real_subnet": real_subnet,
                        },
                    )
                )
                netmap_postrouting_rules.append(
                    _post_ipsec_rule(
                        "Map real customer space into translated customer space through nftables",
                        {
                            "real_subnet": real_subnet,
                            "core_subnet": core_subnet,
                            "translated_subnet": translated_subnet,
                        },
                    )
                )

    if route_via or route_dev:
        for translated_subnet in translated_subnets:
            route_rules.append(
                _post_ipsec_rule(
                    "Install a route for the translated post-IPsec block",
                    {
                        "translated_subnet": translated_subnet,
                        "route_via": route_via,
                        "route_dev": route_dev,
                    },
                )
            )

    return {
        "enabled": True,
        "activation_backend": "nftables",
        "mode": mode,
        "source": str((explicit_cfg.get("source") if explicit_cfg else merged_cfg.get("source")) or ("explicit" if explicit_cfg else compat_cfg.get("source", "derived"))),
        "compatibility_mode": bool(compat_cfg) and not bool(explicit_cfg),
        "translated_subnets": translated_subnets,
        "translated_source_ip": translated_source_ip,
        "remote_subnets": remote_subnets,
        "real_subnets": real_subnets,
        "core_subnets": core_subnets,
        "output_mark": output_mark,
        "interface": interface,
        "tcp_mss_clamp": tcp_mss_value,
        "apply_context": apply_context,
        "route_via": route_via,
        "route_dev": route_dev,
        "rules": {
            "local_identity_rules": local_identity_rules,
            "output_mark_rules": output_mark_rules,
            "prerouting_mark_rules": prerouting_mark_rules,
            "tcp_mss_rules": tcp_mss_rules,
            "forward_tcp_mss_rules": forward_tcp_mss_rules,
            "core_reply_mark_rules": core_reply_mark_rules,
            "core_reply_tcp_mss_rules": core_reply_tcp_mss_rules,
            "netmap_prerouting_rules": netmap_prerouting_rules,
            "netmap_postrouting_rules": netmap_postrouting_rules,
            "route_rules": route_rules,
        },
        "apply_commands": [
            "nft -c -f post-ipsec-nat/nftables.apply.nft",
            "nft -f post-ipsec-nat/nftables.apply.nft",
        ],
        "rollback_commands": [
            "nft -f post-ipsec-nat/nftables.remove.nft",
        ],
        "blocked_apply_commands": [],
        "blocked_rollback_commands": [],
    }


def derive_customer_transport(
    module: Dict[str, Any],
    muxer_doc: Dict[str, Any],
) -> Dict[str, Any]:
    interfaces = muxer_doc.get("interfaces", {}) or {}
    allocation = muxer_doc.get("allocation", {}) or {}
    overlay_pool = ipaddress.ip_network(str(muxer_doc["overlay_pool"]), strict=False)
    inside_ip = str(interfaces.get("inside_ip", "")).strip()
    backend_ul = str(muxer_doc.get("backend_underlay_ip", "")).strip()
    transport_local_mode = str(
        ((muxer_doc.get("transport_identity", {}) or {}).get("local_underlay_mode", "module_inside_ip"))
    ).strip().lower()

    cid = int(module["id"])
    name = str(module["name"])
    tunnel_mode, tunnel_ifname, tunnel_ttl, tunnel_key = customer_tunnel_settings(module, name, cid)
    module_inside_ip = str(module.get("inside_ip", inside_ip)).strip()
    cust_inside_ip = inside_ip if transport_local_mode == "interface_ip" else module_inside_ip
    cust_backend_ul = str(module.get("backend_underlay_ip", backend_ul)).strip()
    mark_hex = hex(int(str(module["mark"]), 0)) if "mark" in module else hex(int(str(allocation["base_mark"]), 0) + cid)
    table_id = int(module["table"]) if "table" in module else int(allocation["base_table"]) + cid
    headend_egress_sources = customer_headend_egress_sources(module, cust_backend_ul)

    if "overlay" in module and module["overlay"]:
        mux_overlay = str(module["overlay"]["mux_ip"])
        router_overlay = str(module["overlay"]["router_ip"])
    else:
        mux_overlay, router_overlay = calc_overlay(overlay_pool, cid)

    return {
        "customer_id": cid,
        "customer_name": name,
        "transport_local_mode": transport_local_mode,
        "local_underlay_ip": cust_inside_ip,
        "backend_underlay_ip": cust_backend_ul,
        "headend_egress_sources": headend_egress_sources,
        "mark_hex": mark_hex,
        "table_id": table_id,
        "tunnel": {
            "mode": tunnel_mode,
            "interface": tunnel_ifname,
            "ttl": tunnel_ttl,
            "key": tunnel_key,
            "overlay": {
                "mux_ip": mux_overlay,
                "router_ip": router_overlay,
            },
            "create_cli": (
                f"ip tunnel add {tunnel_ifname} mode {tunnel_mode} "
                f"local {cust_inside_ip} remote {cust_backend_ul} ttl {tunnel_ttl}"
                + (f" key {tunnel_key}" if tunnel_mode == "gre" and tunnel_key is not None else "")
            ),
            "address_cli": f"ip addr replace {mux_overlay} dev {tunnel_ifname}",
            "up_cli": f"ip link set {tunnel_ifname} up",
        },
    }


def derive_passthrough_dataplane(
    module: Dict[str, Any],
    muxer_doc: Dict[str, Any],
) -> Dict[str, Any]:
    interfaces = muxer_doc.get("interfaces", {}) or {}
    firewall_policy = muxer_doc.get("firewall_policy", {}) or {}
    nft_cfg = (muxer_doc.get("nftables") or {}).get("pass_through", {}) or {}
    public_ip = str(muxer_doc["public_ip"]).strip()
    public_priv_ip = str(interfaces.get("public_private_ip") or public_ip).strip()
    nat_rewrite = bool(firewall_policy.get("use_nat_rewrite", True))
    classification_backend = normalize_passthrough_classification_backend(
        nft_cfg.get("classification_backend", "nftables")
    )
    translation_backend = normalize_passthrough_translation_backend(
        nft_cfg.get("translation_backend", "nftables")
    )
    bridge_backend = normalize_passthrough_bridge_backend(
        nft_cfg.get("bridge_backend", "nftables")
    )
    if {classification_backend, translation_backend, bridge_backend} != {"nftables"}:
        raise ValueError("RPDB dataplane derivation requires nftables-only pass-through backends")

    transport = derive_customer_transport(module, muxer_doc)
    udp500, udp4500, esp50, force_4500_to_500 = customer_protocol_flags(module)
    nat_preroute_targets = [public_priv_ip, public_ip] if public_priv_ip != public_ip else [public_ip]
    nat_preroute_dst = str(transport["backend_underlay_ip"] or "").strip()
    if nat_rewrite and not nat_preroute_dst:
        raise ValueError(f"{module.get('name')}: pass-through DNAT requires backend_underlay_ip")

    return {
        "customer_class": "strict_non_nat" if strict_non_nat_customer(module) else "nat_t_or_custom",
        "protocols": {
            "udp500": udp500,
            "udp4500": udp4500,
            "esp50": esp50,
            "force_rewrite_4500_to_500": force_4500_to_500,
            "natd_rewrite_enabled": bool((module.get("natd_rewrite") or {}).get("enabled")),
            "natd_inner_ip": str((module.get("natd_rewrite") or {}).get("initiator_inner_ip") or ""),
        },
        "transport": transport,
        "routing": {
            "ip_rule": {
                "fwmark": transport["mark_hex"],
                "table": transport["table_id"],
                "cli": f"ip rule add fwmark {transport['mark_hex']} lookup {transport['table_id']}",
            },
            "table_routes": [
                {
                    "table": transport["table_id"],
                    "destination": "default",
                    "device": transport["tunnel"]["interface"],
                    "cli": f"ip route replace default dev {transport['tunnel']['interface']} table {transport['table_id']}",
                }
            ],
        },
        "nat_framework": {
            "classification_backend": classification_backend,
            "translation_backend": translation_backend,
            "rewrite_enabled": nat_rewrite,
            "public_identity": public_ip,
            "eni_private_identity": public_priv_ip,
            "inbound_match_destinations": nat_preroute_targets,
            "backend_delivery_destination": nat_preroute_dst,
            "filter_accept_rules": [],
            "mangle_mark_rules": [],
            "nat_prerouting_rules": [],
            "nat_postrouting_rules": [],
            "mangle_postrouting_rules": [],
            "bridge_prerouting_rules": [],
            "bridge_postrouting_rules": [],
            "default_drop_rules": [],
            "bridge_backend": bridge_backend,
        },
    }


def derive_headend_return_path(
    module: Dict[str, Any],
    public_ip: str,
) -> Dict[str, Any]:
    name = str(module["name"])
    cid = int(module["id"])
    tunnel_mode, tunnel_ifname, tunnel_ttl, tunnel_key = customer_tunnel_settings(module, name, cid)
    overlay = module.get("overlay") or {}
    router_ip = str(overlay.get("router_ip", "")).strip()
    mux_ip = str(overlay.get("mux_ip", "")).strip()
    mux_overlay_ip = str(ipaddress.ip_interface(mux_ip).ip) if mux_ip else ""
    peer_ip = str(module["peer_ip"]).split("/")[0]
    ipsec_cfg = module.get("ipsec", {}) or {}
    udp500, udp4500, esp50, _force = customer_protocol_flags(module)

    return {
        "cluster_profile": "nat" if udp4500 else "non-nat",
        "peer_public_ip": peer_ip,
        "gre": {
            "mode": tunnel_mode,
            "interface": tunnel_ifname,
            "ttl": tunnel_ttl,
            "key": tunnel_key,
            "router_overlay_ip": router_ip,
            "mux_overlay_ip": mux_ip,
            "apply_cli": [
                f"ip addr replace {router_ip} dev {tunnel_ifname}",
                f"ip link set {tunnel_ifname} up",
                f"ip route replace {peer_ip}/32 via {mux_overlay_ip} dev {tunnel_ifname}" if mux_overlay_ip else "",
            ],
        },
        "virtual_public_identity": f"{public_ip}/32",
        "ipsec_return_controls": {
            "left_public": str(ipsec_cfg.get("left_public") or "%defaultroute").strip(),
            "leftid": str(ipsec_cfg.get("local_id") or public_ip).strip(),
            "encapsulation": "yes" if udp4500 else "no",
            "mark": str(ipsec_cfg.get("mark") or "").strip(),
            "mark_in": str(ipsec_cfg.get("mark_in") or "").strip(),
            "mark_out": str(ipsec_cfg.get("mark_out") or "").strip(),
            "vti_interface": str(ipsec_cfg.get("vti_interface") or "").strip(),
            "vti_routing": ipsec_cfg.get("vti_routing"),
            "vti_shared": ipsec_cfg.get("vti_shared"),
            "selectors": {
                "local_subnets": [str(x) for x in (ipsec_cfg.get("local_subnets") or [])],
                "remote_subnets": [str(x) for x in (ipsec_cfg.get("remote_subnets") or [])],
            },
            "protocols": {
                "udp500": udp500,
                "udp4500": udp4500,
                "esp50": esp50,
            },
        },
    }
