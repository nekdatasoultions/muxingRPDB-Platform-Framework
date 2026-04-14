#!/usr/bin/env python3
"""Derived muxer and head-end dataplane artifacts."""

from __future__ import annotations

import ipaddress
from typing import Any, Dict, List

from .customers import calc_overlay, customer_natd_flags, customer_protocol_flags, customer_tunnel_settings
from .variables import strict_non_nat_customer


def _iptables_cli(table: str | None, parts: List[str]) -> str:
    cmd = ["iptables"]
    if table:
        cmd.extend(["-t", table])
    cmd.extend(parts)
    return " ".join(cmd)


def _append_rule(rules: List[Dict[str, str]], purpose: str, table: str | None, parts: List[str]) -> None:
    rules.append(
        {
            "purpose": purpose,
            "cli": _iptables_cli(table, parts),
        }
    )


def _normalize_networks(values: List[Any]) -> List[str]:
    normalized: List[str] = []
    for value in values or []:
        raw = str(value).strip()
        if not raw:
            continue
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
    net = ipaddress.ip_network(str(cidr), strict=False)
    if net.num_addresses == 1:
        return f"{net.network_address}/{net.max_prefixlen}"
    return f"{next(net.hosts())}/{net.max_prefixlen}"


def _merge_overlay(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base or {})
    for key, value in (override or {}).items():
        if value is None:
            continue
        merged[key] = value
    return merged


def _compat_post_ipsec_nat(module: Dict[str, Any]) -> Dict[str, Any]:
    ipsec_cfg = module.get("ipsec", {}) or {}
    _udp500, udp4500, _esp50, _force = customer_protocol_flags(module)
    translated_subnets = _normalize_networks(ipsec_cfg.get("local_subnets") or [])
    if not translated_subnets:
        return {}

    mark_out = str(ipsec_cfg.get("mark_out") or "").strip()
    if not udp4500 or not mark_out:
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


def _build_post_ipsec_rule(
    purpose: str,
    add_cli: str,
    del_cli: str,
) -> Dict[str, str]:
    return {
        "purpose": purpose,
        "add_cli": add_cli,
        "del_cli": del_cli,
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
            "apply_commands": [],
            "rollback_commands": [],
        }

    mode = str(merged_cfg.get("mode") or "snat_pool").strip().lower()
    translated_subnets = _normalize_networks(merged_cfg.get("translated_subnets") or [])
    if explicit_cfg:
        raw_translated_source_ip = explicit_cfg.get("translated_source_ip")
    else:
        raw_translated_source_ip = merged_cfg.get("translated_source_ip")
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

    local_identity_rules: List[Dict[str, str]] = []
    output_mark_rules: List[Dict[str, str]] = []
    prerouting_mark_rules: List[Dict[str, str]] = []
    tcp_mss_rules: List[Dict[str, str]] = []
    forward_tcp_mss_rules: List[Dict[str, str]] = []
    core_reply_mark_rules: List[Dict[str, str]] = []
    core_reply_tcp_mss_rules: List[Dict[str, str]] = []
    netmap_prerouting_rules: List[Dict[str, str]] = []
    netmap_postrouting_rules: List[Dict[str, str]] = []
    route_rules: List[Dict[str, str]] = []
    apply_commands: List[str] = []
    rollback_commands: List[str] = []

    if translated_source_ip:
        local_identity_rules.append(
            _build_post_ipsec_rule(
                "Assign translated source identity on the dedicated NAT pool interface or loopback fallback",
                f'if ip link show "{interface}" >/dev/null 2>&1; then ip addr replace {translated_source_ip} dev "{interface}"; else ip addr replace {translated_source_ip} dev lo; fi',
                f'ip addr del {translated_source_ip} dev "{interface}" 2>/dev/null || true; ip addr del {translated_source_ip} dev lo 2>/dev/null || true',
            )
        )

    if mode != "netmap" and output_mark and translated_source_ip:
        for remote_subnet in remote_subnets:
            output_mark_rules.append(
                _build_post_ipsec_rule(
                    "Mark translated source traffic so replies leave via the correct customer IPsec context",
                    f"iptables -t mangle -C OUTPUT -s {translated_source_ip} -d {remote_subnet} -j MARK --set-xmark {output_mark} 2>/dev/null || iptables -t mangle -I OUTPUT 1 -s {translated_source_ip} -d {remote_subnet} -j MARK --set-xmark {output_mark}",
                    f"iptables -t mangle -D OUTPUT -s {translated_source_ip} -d {remote_subnet} -j MARK --set-xmark {output_mark} 2>/dev/null || true",
                )
            )
    if mode != "netmap" and output_mark:
        for translated_subnet in translated_subnets:
            for remote_subnet in remote_subnets:
                prerouting_mark_rules.append(
                    _build_post_ipsec_rule(
                        "Mark forwarded translated traffic so replies leave via the correct customer IPsec context",
                        f"iptables -t mangle -C PREROUTING -s {translated_subnet} -d {remote_subnet} -j MARK --set-xmark {output_mark} 2>/dev/null || iptables -t mangle -I PREROUTING 1 -s {translated_subnet} -d {remote_subnet} -j MARK --set-xmark {output_mark}",
                        f"iptables -t mangle -D PREROUTING -s {translated_subnet} -d {remote_subnet} -j MARK --set-xmark {output_mark} 2>/dev/null || true",
                    )
                )

    if mode != "netmap" and tcp_mss_value is not None:
        for translated_subnet in translated_subnets:
            for remote_subnet in remote_subnets:
                tcp_mss_rules.append(
                    _build_post_ipsec_rule(
                        "Clamp TCP MSS for translated traffic leaving the post-IPsec NAT block",
                        f"iptables -t mangle -C OUTPUT -p tcp -s {translated_subnet} -d {remote_subnet} --tcp-flags SYN,RST SYN -j TCPMSS --set-mss {tcp_mss_value} 2>/dev/null || iptables -t mangle -I OUTPUT 1 -p tcp -s {translated_subnet} -d {remote_subnet} --tcp-flags SYN,RST SYN -j TCPMSS --set-mss {tcp_mss_value}",
                        f"iptables -t mangle -D OUTPUT -p tcp -s {translated_subnet} -d {remote_subnet} --tcp-flags SYN,RST SYN -j TCPMSS --set-mss {tcp_mss_value} 2>/dev/null || true",
                    )
                )
                forward_tcp_mss_rules.append(
                    _build_post_ipsec_rule(
                        "Clamp TCP MSS for translated traffic forwarded toward the customer IPsec peer",
                        f"iptables -t mangle -C FORWARD -p tcp -s {translated_subnet} -d {remote_subnet} --tcp-flags SYN,RST SYN -j TCPMSS --set-mss {tcp_mss_value} 2>/dev/null || iptables -t mangle -I FORWARD 1 -p tcp -s {translated_subnet} -d {remote_subnet} --tcp-flags SYN,RST SYN -j TCPMSS --set-mss {tcp_mss_value}",
                        f"iptables -t mangle -D FORWARD -p tcp -s {translated_subnet} -d {remote_subnet} --tcp-flags SYN,RST SYN -j TCPMSS --set-mss {tcp_mss_value} 2>/dev/null || true",
                    )
                )

    if mode == "netmap" and real_subnets and translated_subnets and core_subnets:
        if output_mark:
            for core_subnet in core_subnets:
                for translated_subnet in translated_subnets:
                    core_reply_mark_rules.append(
                        _build_post_ipsec_rule(
                            "Mark forwarded core reply traffic destined to the translated customer block so it returns through the correct IPsec context",
                            f"iptables -t mangle -C PREROUTING -s {core_subnet} -d {translated_subnet} -j MARK --set-xmark {output_mark} 2>/dev/null || iptables -t mangle -I PREROUTING 1 -s {core_subnet} -d {translated_subnet} -j MARK --set-xmark {output_mark}",
                            f"iptables -t mangle -D PREROUTING -s {core_subnet} -d {translated_subnet} -j MARK --set-xmark {output_mark} 2>/dev/null || true",
                        )
                    )
        if tcp_mss_value is not None:
            for core_subnet in core_subnets:
                for real_subnet in real_subnets:
                    core_reply_tcp_mss_rules.append(
                        _build_post_ipsec_rule(
                            "Clamp TCP MSS for forwarded core reply traffic heading back toward the customer real subnet",
                            f"iptables -t mangle -C FORWARD -p tcp -s {core_subnet} -d {real_subnet} --tcp-flags SYN,RST SYN -j TCPMSS --set-mss {tcp_mss_value} 2>/dev/null || iptables -t mangle -I FORWARD 1 -p tcp -s {core_subnet} -d {real_subnet} --tcp-flags SYN,RST SYN -j TCPMSS --set-mss {tcp_mss_value}",
                            f"iptables -t mangle -D FORWARD -p tcp -s {core_subnet} -d {real_subnet} --tcp-flags SYN,RST SYN -j TCPMSS --set-mss {tcp_mss_value} 2>/dev/null || true",
                        )
                    )
        for real_subnet, translated_subnet in zip(real_subnets, translated_subnets):
            for core_subnet in core_subnets:
                netmap_prerouting_rules.append(
                    _build_post_ipsec_rule(
                        "Map translated customer space back to the customer's real subnet before delivery",
                        f"iptables -t nat -C PREROUTING -s {core_subnet} -d {translated_subnet} -j NETMAP --to {real_subnet} 2>/dev/null || iptables -t nat -A PREROUTING -s {core_subnet} -d {translated_subnet} -j NETMAP --to {real_subnet}",
                        f"iptables -t nat -D PREROUTING -s {core_subnet} -d {translated_subnet} -j NETMAP --to {real_subnet} 2>/dev/null || true",
                    )
                )
                netmap_postrouting_rules.append(
                    _build_post_ipsec_rule(
                        "Translate the customer's real subnet into its unique internal block for the core",
                        f"iptables -t nat -C POSTROUTING -s {real_subnet} -d {core_subnet} -j NETMAP --to {translated_subnet} 2>/dev/null || iptables -t nat -A POSTROUTING -s {real_subnet} -d {core_subnet} -j NETMAP --to {translated_subnet}",
                        f"iptables -t nat -D POSTROUTING -s {real_subnet} -d {core_subnet} -j NETMAP --to {translated_subnet} 2>/dev/null || true",
                    )
                )

    if route_via or route_dev:
        for translated_subnet in translated_subnets:
            if route_via:
                add_cli = f"ip route replace {translated_subnet} via {route_via}" + (f" dev {route_dev}" if route_dev else "")
                del_cli = f"ip route del {translated_subnet} via {route_via}" + (f" dev {route_dev}" if route_dev else "") + " 2>/dev/null || true"
            else:
                add_cli = f"ip route replace {translated_subnet} dev {route_dev}"
                del_cli = f"ip route del {translated_subnet} dev {route_dev} 2>/dev/null || true"
            route_rules.append(
                _build_post_ipsec_rule(
                    "Install a southbound route for the translated post-IPsec block",
                    add_cli,
                    del_cli,
                )
            )

    if mode == "netmap" and (netmap_prerouting_rules or netmap_postrouting_rules):
        apply_commands.append("modprobe xt_NETMAP >/dev/null 2>&1 || true")

    for rule_group in (
        local_identity_rules,
        output_mark_rules,
        prerouting_mark_rules,
        tcp_mss_rules,
        forward_tcp_mss_rules,
        core_reply_mark_rules,
        core_reply_tcp_mss_rules,
        netmap_prerouting_rules,
        netmap_postrouting_rules,
        route_rules,
    ):
        for rule in rule_group:
            apply_commands.append(rule["add_cli"])

    for rule_group in (
        route_rules,
        netmap_postrouting_rules,
        netmap_prerouting_rules,
        forward_tcp_mss_rules,
        tcp_mss_rules,
        prerouting_mark_rules,
        output_mark_rules,
        local_identity_rules,
        core_reply_tcp_mss_rules,
        core_reply_mark_rules,
    ):
        for rule in rule_group:
            rollback_commands.append(rule["del_cli"])

    return {
        "enabled": True,
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
        "apply_commands": apply_commands,
        "rollback_commands": rollback_commands,
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
    mark_hex = hex(int(str(module["mark"]), 0)) if "mark" in module else hex(int(allocation["base_mark"], 0) + cid)
    table_id = int(module["table"]) if "table" in module else int(allocation["base_table"]) + cid

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
    iptables_cfg = muxer_doc.get("iptables", {}) or {}
    chains = iptables_cfg.get("chains", {}) or {}
    public_ip = str(muxer_doc["public_ip"]).strip()
    public_priv_ip = str(interfaces.get("public_private_ip") or public_ip).strip()
    pub_if = str(interfaces.get("public_if", "")).strip()
    mangle_chain = str(chains.get("mangle_chain", "MUXER_MANGLE"))
    mangle_post_chain = str(chains.get("mangle_postrouting_chain", "MUXER_MANGLE_POST"))
    filter_chain = str(chains.get("filter_chain", "MUXER_FILTER"))
    nat_pre_chain = str(chains.get("nat_prerouting_chain", "MUXER_NAT_PRE"))
    nat_post_chain = str(chains.get("nat_postrouting_chain", "MUXER_NAT_POST"))
    nat_rewrite = bool(iptables_cfg.get("use_nat_rewrite", True))
    default_drop = bool(iptables_cfg.get("default_drop_ipsec_to_public_ip", True))
    peer_cidr = str(module["peer_ip"])

    transport = derive_customer_transport(module, muxer_doc)
    udp500, udp4500, esp50, force_4500_to_500 = customer_protocol_flags(module)
    natd_rewrite_enabled, natd_inner_ip = customer_natd_flags(module)
    nat_preroute_targets = [public_priv_ip, public_ip] if public_priv_ip != public_ip else [public_ip]
    # Forced 4500->500 bridge mode still preserves the strict customer's
    # backend delivery identity on UDP/500 and ESP; only true NAT-T customers
    # are delivered to the backend underlay IP by default.
    nat_preroute_dst = transport["backend_underlay_ip"] if udp4500 else public_ip

    filter_accept: List[Dict[str, str]] = []
    mangle_mark: List[Dict[str, str]] = []
    nat_prerouting: List[Dict[str, str]] = []
    nat_postrouting: List[Dict[str, str]] = []
    mangle_postrouting: List[Dict[str, str]] = []
    default_drop_rules: List[Dict[str, str]] = []

    if udp500:
        _append_rule(
            filter_accept,
            "Allow inbound IKE on UDP/500 to the muxer public identity",
            None,
            ["-A", filter_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_ip, "-p", "udp", "--dport", "500", "-j", "ACCEPT"],
        )
        _append_rule(
            mangle_mark,
            "Mark inbound UDP/500 for the customer-specific route table",
            "mangle",
            ["-A", mangle_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_ip, "-p", "udp", "--dport", "500", "-j", "MARK", "--set-mark", transport["mark_hex"]],
        )
        if public_priv_ip != public_ip:
            _append_rule(
                mangle_mark,
                "Also mark UDP/500 addressed to the ENI private IP used behind the EIP edge",
                "mangle",
                ["-A", mangle_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_priv_ip, "-p", "udp", "--dport", "500", "-j", "MARK", "--set-mark", transport["mark_hex"]],
            )
            if nat_rewrite:
                for nat_pre_target in nat_preroute_targets:
                    _append_rule(
                        nat_prerouting,
                        "DNAT inbound UDP/500 to the derived backend delivery destination",
                        "nat",
                        ["-A", nat_pre_chain, "-i", pub_if, "-s", peer_cidr, "-d", nat_pre_target, "-p", "udp", "--dport", "500", "-j", "DNAT", "--to-destination", nat_preroute_dst],
                    )
                post_src = transport["backend_underlay_ip"]
                if force_4500_to_500:
                    _append_rule(
                        nat_postrouting,
                        "Present backend UDP/500 replies as UDP/4500 toward the NAT-T peer",
                        "nat",
                        ["-A", nat_post_chain, "-o", pub_if, "-s", post_src, "-d", peer_cidr, "-p", "udp", "--sport", "500", "-j", "SNAT", "--to-source", f"{public_priv_ip}:4500"],
                    )
                else:
                    _append_rule(
                        nat_postrouting,
                        "SNAT backend UDP/500 replies back to the muxer public-side identity",
                        "nat",
                        ["-A", nat_post_chain, "-o", pub_if, "-s", post_src, "-d", peer_cidr, "-p", "udp", "--sport", "500", "-j", "SNAT", "--to-source", public_priv_ip],
                    )

    if force_4500_to_500:
        _append_rule(
            mangle_mark,
            "Mark inbound UDP/4500 for a forced 4500->500 bridge customer",
            "mangle",
            ["-A", mangle_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_ip, "-p", "udp", "--dport", "4500", "-j", "MARK", "--set-mark", transport["mark_hex"]],
        )
        if public_priv_ip != public_ip:
            _append_rule(
                mangle_mark,
                "Also mark inbound UDP/4500 addressed to the ENI private IP",
                "mangle",
                ["-A", mangle_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_priv_ip, "-p", "udp", "--dport", "4500", "-j", "MARK", "--set-mark", transport["mark_hex"]],
            )
            if nat_rewrite:
                for nat_pre_target in nat_preroute_targets:
                    _append_rule(
                        nat_prerouting,
                        "DNAT inbound UDP/4500 to backend UDP/500 for forced bridge mode",
                        "nat",
                        ["-A", nat_pre_chain, "-i", pub_if, "-s", peer_cidr, "-d", nat_pre_target, "-p", "udp", "--dport", "4500", "-j", "DNAT", "--to-destination", f"{nat_preroute_dst}:500"],
                    )
                _append_rule(
                    nat_postrouting,
                    "SNAT backend UDP/4500 replies back to muxer public identity in forced bridge mode",
                    "nat",
                    ["-A", nat_post_chain, "-o", pub_if, "-s", transport["backend_underlay_ip"], "-d", peer_cidr, "-p", "udp", "--sport", "4500", "-j", "SNAT", "--to-source", f"{public_priv_ip}:4500"],
                )
        _append_rule(
            mangle_postrouting,
            "Userspace bridge queue for translating outbound backend UDP/500 replies into customer NAT-T format",
            "mangle",
            ["-A", mangle_post_chain, "-o", pub_if, "-s", transport["backend_underlay_ip"], "-d", peer_cidr, "-p", "udp", "--sport", "500", "-j", "NFQUEUE", "--queue-num", "<queue_out>"],
        )

    if udp4500:
        _append_rule(
            filter_accept,
            "Allow inbound NAT-T on UDP/4500",
            None,
            ["-A", filter_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_ip, "-p", "udp", "--dport", "4500", "-j", "ACCEPT"],
        )
        _append_rule(
            mangle_mark,
            "Mark inbound UDP/4500 for the customer-specific route table",
            "mangle",
            ["-A", mangle_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_ip, "-p", "udp", "--dport", "4500", "-j", "MARK", "--set-mark", transport["mark_hex"]],
        )
        if public_priv_ip != public_ip:
            _append_rule(
                mangle_mark,
                "Also mark NAT-T traffic addressed to the ENI private IP",
                "mangle",
                ["-A", mangle_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_priv_ip, "-p", "udp", "--dport", "4500", "-j", "MARK", "--set-mark", transport["mark_hex"]],
            )
            if nat_rewrite:
                for nat_pre_target in nat_preroute_targets:
                    _append_rule(
                        nat_prerouting,
                        "DNAT inbound UDP/4500 to the backend head-end",
                        "nat",
                        ["-A", nat_pre_chain, "-i", pub_if, "-s", peer_cidr, "-d", nat_pre_target, "-p", "udp", "--dport", "4500", "-j", "DNAT", "--to-destination", nat_preroute_dst],
                    )
                _append_rule(
                    nat_postrouting,
                    "SNAT backend UDP/4500 replies back to the muxer public identity",
                    "nat",
                    ["-A", nat_post_chain, "-o", pub_if, "-s", transport["backend_underlay_ip"], "-d", peer_cidr, "-p", "udp", "--sport", "4500", "-j", "SNAT", "--to-source", public_priv_ip],
                )

    if esp50:
        _append_rule(
            filter_accept,
            "Allow inbound ESP for native IPsec peers",
            None,
            ["-A", filter_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_ip, "-p", "50", "-j", "ACCEPT"],
        )
        _append_rule(
            mangle_mark,
            "Mark inbound ESP for the customer-specific route table",
            "mangle",
            ["-A", mangle_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_ip, "-p", "50", "-j", "MARK", "--set-mark", transport["mark_hex"]],
        )
        if public_priv_ip != public_ip:
            _append_rule(
                mangle_mark,
                "Also mark ESP addressed to the ENI private IP",
                "mangle",
                ["-A", mangle_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_priv_ip, "-p", "50", "-j", "MARK", "--set-mark", transport["mark_hex"]],
            )
            if nat_rewrite:
                for nat_pre_target in nat_preroute_targets:
                    _append_rule(
                        nat_prerouting,
                        "DNAT inbound ESP to the derived backend delivery destination",
                        "nat",
                        ["-A", nat_pre_chain, "-i", pub_if, "-s", peer_cidr, "-d", nat_pre_target, "-p", "50", "-j", "DNAT", "--to-destination", nat_preroute_dst],
                    )
                _append_rule(
                    nat_postrouting,
                    "SNAT outbound ESP from the backend back to the muxer public identity",
                    "nat",
                    ["-A", nat_post_chain, "-o", pub_if, "-s", transport["backend_underlay_ip"], "-d", peer_cidr, "-p", "50", "-j", "SNAT", "--to-source", public_priv_ip],
                )

    if default_drop:
        for drop_dst in sorted({public_ip, public_priv_ip}):
            _append_rule(
                default_drop_rules,
                "Drop unclassified UDP/500 to the muxer public edge",
                None,
                ["-A", filter_chain, "-i", pub_if, "-d", drop_dst, "-p", "udp", "--dport", "500", "-j", "DROP"],
            )
            _append_rule(
                default_drop_rules,
                "Drop unclassified UDP/4500 to the muxer public edge",
                None,
                ["-A", filter_chain, "-i", pub_if, "-d", drop_dst, "-p", "udp", "--dport", "4500", "-j", "DROP"],
            )
            _append_rule(
                default_drop_rules,
                "Drop unclassified ESP to the muxer public edge",
                None,
                ["-A", filter_chain, "-i", pub_if, "-d", drop_dst, "-p", "50", "-j", "DROP"],
            )

    return {
        "customer_class": "strict_non_nat" if strict_non_nat_customer(module) else "nat_t_or_custom",
        "protocols": {
            "udp500": udp500,
            "udp4500": udp4500,
            "esp50": esp50,
            "force_rewrite_4500_to_500": force_4500_to_500,
            "natd_rewrite_enabled": natd_rewrite_enabled,
            "natd_inner_ip": natd_inner_ip,
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
            "rewrite_enabled": nat_rewrite,
            "public_identity": public_ip,
            "eni_private_identity": public_priv_ip,
            "inbound_match_destinations": nat_preroute_targets,
            "backend_delivery_destination": nat_preroute_dst,
            "filter_accept_rules": filter_accept,
            "mangle_mark_rules": mangle_mark,
            "nat_prerouting_rules": nat_prerouting,
            "nat_postrouting_rules": nat_postrouting,
            "mangle_postrouting_rules": mangle_postrouting,
            "default_drop_rules": default_drop_rules,
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
