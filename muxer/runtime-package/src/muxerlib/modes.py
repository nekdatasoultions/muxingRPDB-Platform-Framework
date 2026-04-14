#!/usr/bin/env python3
"""Apply handlers for pass-through and termination modes."""

from __future__ import annotations

import ipaddress
from typing import Any, Dict, List

from .core import (
    ensure_chain,
    ensure_jump,
    flush_chain,
    must,
    remove_jump,
    ensure_tunnel,
    ensure_policy,
    ensure_local_ipv4,
    remove_local_ipv4,
)
from .customers import (
    calc_overlay,
    customer_natd_flags,
    customer_protocol_flags,
    customer_tunnel_settings,
    subnet_list,
)
from .strongswan import render_strongswan


def apply_passthrough(
    modules: List[Dict[str, Any]],
    pub_if: str,
    inside_if: str,
    public_ip: str,
    public_priv_ip: str,
    inside_ip: str,
    backend_ul: str,
    transport_local_mode: str,
    overlay_pool: ipaddress.IPv4Network,
    base_table: int,
    base_mark: int,
    mangle_chain: str,
    filter_chain: str,
    nat_rewrite: bool,
    nat_pre_chain: str,
    nat_post_chain: str,
    mangle_post_chain: str,
    nfqueue_enabled: bool,
    nfqueue_queue_in: int,
    nfqueue_queue_out: int,
    nfqueue_queue_bypass: bool,
    natd_dpi_enabled: bool,
    natd_dpi_queue_in: int,
    natd_dpi_queue_out: int,
    natd_dpi_queue_bypass: bool,
    default_drop: bool,
) -> None:
    ensure_chain("mangle", mangle_chain)
    ensure_chain("mangle", mangle_post_chain)
    ensure_chain("filter", filter_chain)
    ensure_jump("mangle", "PREROUTING", mangle_chain, position=1)
    ensure_jump("mangle", "POSTROUTING", mangle_post_chain, position=1)
    ensure_jump("filter", "FORWARD", filter_chain, position=1)
    if nat_rewrite:
        ensure_chain("nat", nat_pre_chain)
        ensure_chain("nat", nat_post_chain)
        ensure_jump("nat", "PREROUTING", nat_pre_chain, position=1)
        ensure_jump("nat", "POSTROUTING", nat_post_chain, position=1)
    else:
        remove_jump("nat", "PREROUTING", nat_pre_chain)
        remove_jump("nat", "POSTROUTING", nat_post_chain)

    flush_chain("mangle", mangle_chain)
    flush_chain("mangle", mangle_post_chain)
    flush_chain("filter", filter_chain)
    flush_chain("nat", nat_pre_chain)
    flush_chain("nat", nat_post_chain)

    for module in modules:
        cid = int(module["id"])
        name = str(module["name"])
        peer_cidr = str(module["peer_ip"])
        ipaddress.ip_network(peer_cidr, strict=False)
        udp500, udp4500, esp50, force_4500_to_500 = customer_protocol_flags(module)
        natd_rewrite_enabled, _natd_inner_ip = customer_natd_flags(module)
        if force_4500_to_500 and not udp500:
            raise SystemExit(f"{name}: protocols.force_rewrite_4500_to_500 requires protocols.udp500=true")
        if force_4500_to_500 and not nat_rewrite:
            raise SystemExit(f"{name}: protocols.force_rewrite_4500_to_500 requires iptables.use_nat_rewrite=true")
        if natd_rewrite_enabled and not udp500:
            raise SystemExit(f"{name}: natd_rewrite.enabled requires protocols.udp500=true")
        if natd_rewrite_enabled and force_4500_to_500:
            raise SystemExit(f"{name}: natd_rewrite.enabled conflicts with protocols.force_rewrite_4500_to_500")
        if natd_rewrite_enabled and public_priv_ip != public_ip and not nat_rewrite:
            raise SystemExit(f"{name}: natd_rewrite.enabled requires iptables.use_nat_rewrite=true when public_private_ip != public_ip")

        tunnel_mode, tunnel_ifname, tunnel_ttl, tunnel_key = customer_tunnel_settings(module, name, cid)
        module_inside_ip = str(module.get("inside_ip", inside_ip)).strip()
        if transport_local_mode == "interface_ip":
            cust_inside_ip = inside_ip
            if module_inside_ip != inside_ip:
                remove_local_ipv4(inside_if, module_inside_ip)
        else:
            cust_inside_ip = module_inside_ip
        cust_backend_ul = str(module.get("backend_underlay_ip", backend_ul)).strip()
        ipaddress.ip_address(cust_inside_ip)
        ipaddress.ip_address(cust_backend_ul)
        if transport_local_mode != "interface_ip" and cust_inside_ip != inside_ip:
            ensure_local_ipv4(inside_if, cust_inside_ip, prefix_len=32)
        mark_hex = hex(base_mark + cid) if "mark" not in module else hex(int(str(module["mark"]), 0))
        table_id = base_table + cid if "table" not in module else int(module["table"])

        if "overlay" in module and module["overlay"]:
            mux_overlay = str(module["overlay"]["mux_ip"])
        else:
            mux_overlay, _ = calc_overlay(overlay_pool, cid)

        ensure_tunnel(
            tunnel_ifname,
            cust_inside_ip,
            cust_backend_ul,
            mux_overlay,
            mode=tunnel_mode,
            ttl=tunnel_ttl,
            key=tunnel_key,
        )
        ensure_policy(mark_hex, table_id, tunnel_ifname, priority=module.get("rpdb_priority"))

        nat_preroute_targets: List[str] = []
        if public_priv_ip != public_ip:
            nat_preroute_targets.append(public_priv_ip)
            nat_preroute_targets.append(public_ip)
        else:
            nat_preroute_targets.append(public_ip)

        # True NAT-T customers need inbound encrypted traffic handed to the
        # backend head-end private IP. Forced 4500->500 bridge customers are
        # different: UDP/500 and ESP must still preserve the shared public
        # identity semantics expected by the strict backend/head-end config.
        nat_preroute_dst = cust_backend_ul if udp4500 else public_ip

        if udp500:
            must(["iptables", "-A", filter_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_ip, "-p", "udp", "--dport", "500", "-j", "ACCEPT"])
            must(["iptables", "-t", "mangle", "-A", mangle_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_ip, "-p", "udp", "--dport", "500", "-j", "MARK", "--set-mark", mark_hex])
            if public_priv_ip != public_ip:
                must(["iptables", "-t", "mangle", "-A", mangle_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_priv_ip, "-p", "udp", "--dport", "500", "-j", "MARK", "--set-mark", mark_hex])
                if nat_rewrite:
                    for nat_pre_target in nat_preroute_targets:
                        must(["iptables", "-t", "nat", "-A", nat_pre_chain, "-i", pub_if, "-s", peer_cidr, "-d", nat_pre_target, "-p", "udp", "--dport", "500", "-j", "DNAT", "--to-destination", nat_preroute_dst])
                    if force_4500_to_500:
                        must(["iptables", "-t", "nat", "-A", nat_post_chain, "-o", pub_if, "-s", cust_backend_ul, "-d", peer_cidr, "-p", "udp", "--sport", "500", "-j", "SNAT", "--to-source", f"{public_priv_ip}:4500"])
                    else:
                        must(["iptables", "-t", "nat", "-A", nat_post_chain, "-o", pub_if, "-s", cust_backend_ul, "-d", peer_cidr, "-p", "udp", "--sport", "500", "-j", "SNAT", "--to-source", public_priv_ip])

            if natd_dpi_enabled and natd_rewrite_enabled:
                qnat_in = [
                    "iptables",
                    "-t",
                    "mangle",
                    "-A",
                    mangle_chain,
                    "-i",
                    pub_if,
                    "-s",
                    peer_cidr,
                    "-d",
                    cust_backend_ul,
                    "-p",
                    "udp",
                    "--dport",
                    "500",
                    "-j",
                    "NFQUEUE",
                    "--queue-num",
                    str(natd_dpi_queue_in),
                ]
                if natd_dpi_queue_bypass:
                    qnat_in.append("--queue-bypass")
                must(qnat_in)

                if public_priv_ip != public_ip:
                    qnat_in_priv = [
                        "iptables",
                        "-t",
                        "mangle",
                        "-A",
                        mangle_chain,
                        "-i",
                        pub_if,
                        "-s",
                        peer_cidr,
                        "-d",
                        public_priv_ip,
                        "-p",
                        "udp",
                        "--dport",
                        "500",
                        "-j",
                        "NFQUEUE",
                        "--queue-num",
                        str(natd_dpi_queue_in),
                    ]
                    if natd_dpi_queue_bypass:
                        qnat_in_priv.append("--queue-bypass")
                    must(qnat_in_priv)

                qnat_out = [
                    "iptables",
                    "-t",
                    "mangle",
                    "-A",
                    mangle_post_chain,
                    "-o",
                    pub_if,
                    "-s",
                    cust_backend_ul,
                    "-d",
                    peer_cidr,
                    "-p",
                    "udp",
                    "--sport",
                    "500",
                    "--dport",
                    "500",
                    "-j",
                    "NFQUEUE",
                    "--queue-num",
                    str(natd_dpi_queue_out),
                ]
                if natd_dpi_queue_bypass:
                    qnat_out.append("--queue-bypass")
                must(qnat_out)

        if force_4500_to_500:
            must(["iptables", "-t", "mangle", "-A", mangle_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_ip, "-p", "udp", "--dport", "4500", "-j", "MARK", "--set-mark", mark_hex])
            if public_priv_ip != public_ip:
                must(["iptables", "-t", "mangle", "-A", mangle_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_priv_ip, "-p", "udp", "--dport", "4500", "-j", "MARK", "--set-mark", mark_hex])
                if nat_rewrite:
                    for nat_pre_target in nat_preroute_targets:
                        must(["iptables", "-t", "nat", "-A", nat_pre_chain, "-i", pub_if, "-s", peer_cidr, "-d", nat_pre_target, "-p", "udp", "--dport", "4500", "-j", "DNAT", "--to-destination", f"{nat_preroute_dst}:500"])
                    must(["iptables", "-t", "nat", "-A", nat_post_chain, "-o", pub_if, "-s", cust_backend_ul, "-d", peer_cidr, "-p", "udp", "--sport", "4500", "-j", "SNAT", "--to-source", f"{public_priv_ip}:4500"])
            if nfqueue_enabled:
                qin = [
                    "iptables",
                    "-t",
                    "mangle",
                    "-A",
                    mangle_chain,
                    "-i",
                    pub_if,
                    "-s",
                    peer_cidr,
                    "-d",
                    public_ip,
                    "-p",
                    "udp",
                    "--dport",
                    "4500",
                    "-j",
                    "NFQUEUE",
                    "--queue-num",
                    str(nfqueue_queue_in),
                ]
                if nfqueue_queue_bypass:
                    qin.append("--queue-bypass")
                must(qin)
                # Some kernels/userspace NFQUEUE paths can lose skb mark after
                # payload mutation. Re-assert the per-customer fwmark so the
                # bridged packet still hits the GRE policy route.
                must(["iptables", "-t", "mangle", "-A", mangle_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_ip, "-p", "udp", "--dport", "4500", "-j", "MARK", "--set-mark", mark_hex])

                if public_priv_ip != public_ip:
                    qin_priv = [
                        "iptables",
                        "-t",
                        "mangle",
                        "-A",
                        mangle_chain,
                        "-i",
                        pub_if,
                        "-s",
                        peer_cidr,
                        "-d",
                        public_priv_ip,
                        "-p",
                        "udp",
                        "--dport",
                        "4500",
                        "-j",
                        "NFQUEUE",
                        "--queue-num",
                        str(nfqueue_queue_in),
                    ]
                    if nfqueue_queue_bypass:
                        qin_priv.append("--queue-bypass")
                    must(qin_priv)
                    must(["iptables", "-t", "mangle", "-A", mangle_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_priv_ip, "-p", "udp", "--dport", "4500", "-j", "MARK", "--set-mark", mark_hex])

                qout = [
                    "iptables",
                    "-t",
                    "mangle",
                    "-A",
                    mangle_post_chain,
                    "-o",
                    pub_if,
                    "-s",
                    cust_backend_ul,
                    "-d",
                    peer_cidr,
                    "-p",
                    "udp",
                    "--sport",
                    "500",
                    "-j",
                    "NFQUEUE",
                    "--queue-num",
                    str(nfqueue_queue_out),
                ]
                if nfqueue_queue_bypass:
                    qout.append("--queue-bypass")
                must(qout)
                if public_ip != cust_backend_ul:
                    qout_pub = [
                        "iptables",
                        "-t",
                        "mangle",
                        "-A",
                        mangle_post_chain,
                        "-o",
                        pub_if,
                        "-s",
                        public_ip,
                        "-d",
                        peer_cidr,
                        "-p",
                        "udp",
                        "--sport",
                        "500",
                        "-j",
                        "NFQUEUE",
                        "--queue-num",
                        str(nfqueue_queue_out),
                    ]
                    if nfqueue_queue_bypass:
                        qout_pub.append("--queue-bypass")
                    must(qout_pub)

        if udp4500:
            must(["iptables", "-A", filter_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_ip, "-p", "udp", "--dport", "4500", "-j", "ACCEPT"])
            must(["iptables", "-t", "mangle", "-A", mangle_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_ip, "-p", "udp", "--dport", "4500", "-j", "MARK", "--set-mark", mark_hex])
            if public_priv_ip != public_ip:
                must(["iptables", "-t", "mangle", "-A", mangle_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_priv_ip, "-p", "udp", "--dport", "4500", "-j", "MARK", "--set-mark", mark_hex])
                if nat_rewrite:
                    for nat_pre_target in nat_preroute_targets:
                        must(["iptables", "-t", "nat", "-A", nat_pre_chain, "-i", pub_if, "-s", peer_cidr, "-d", nat_pre_target, "-p", "udp", "--dport", "4500", "-j", "DNAT", "--to-destination", nat_preroute_dst])
                    must(["iptables", "-t", "nat", "-A", nat_post_chain, "-o", pub_if, "-s", cust_backend_ul, "-d", peer_cidr, "-p", "udp", "--sport", "4500", "-j", "SNAT", "--to-source", public_priv_ip])

        if esp50:
            must(["iptables", "-A", filter_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_ip, "-p", "50", "-j", "ACCEPT"])
            must(["iptables", "-t", "mangle", "-A", mangle_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_ip, "-p", "50", "-j", "MARK", "--set-mark", mark_hex])
            if public_priv_ip != public_ip:
                must(["iptables", "-t", "mangle", "-A", mangle_chain, "-i", pub_if, "-s", peer_cidr, "-d", public_priv_ip, "-p", "50", "-j", "MARK", "--set-mark", mark_hex])
                if nat_rewrite:
                    for nat_pre_target in nat_preroute_targets:
                        must(["iptables", "-t", "nat", "-A", nat_pre_chain, "-i", pub_if, "-s", peer_cidr, "-d", nat_pre_target, "-p", "50", "-j", "DNAT", "--to-destination", nat_preroute_dst])
                    must(["iptables", "-t", "nat", "-A", nat_post_chain, "-o", pub_if, "-s", cust_backend_ul, "-d", peer_cidr, "-p", "50", "-j", "SNAT", "--to-source", public_priv_ip])

    if default_drop:
        for drop_dst in sorted({public_ip, public_priv_ip}):
            must(["iptables", "-A", filter_chain, "-i", pub_if, "-d", drop_dst, "-p", "udp", "--dport", "500", "-j", "DROP"])
            must(["iptables", "-A", filter_chain, "-i", pub_if, "-d", drop_dst, "-p", "udp", "--dport", "4500", "-j", "DROP"])
            must(["iptables", "-A", filter_chain, "-i", pub_if, "-d", drop_dst, "-p", "50", "-j", "DROP"])

    print(f"Applied {len(modules)} customer module(s).")
    print("Mode: pass-through (IPsec terminated on backend).")


def apply_termination(
    global_cfg: Dict[str, Any],
    modules: List[Dict[str, Any]],
    pub_if: str,
    inside_if: str,
    public_ip: str,
    public_priv_ip: str,
    inside_ip: str,
    backend_ul: str,
    transport_local_mode: str,
    overlay_pool: ipaddress.IPv4Network,
    mangle_chain: str,
    mangle_post_chain: str,
    filter_chain: str,
    nat_pre_chain: str,
    nat_post_chain: str,
    default_drop: bool,
) -> None:
    input_chain = str(global_cfg["iptables"]["chains"].get("input_chain", "MUXER_INPUT"))

    remove_jump("mangle", "PREROUTING", mangle_chain)
    remove_jump("mangle", "POSTROUTING", mangle_post_chain)
    remove_jump("nat", "PREROUTING", nat_pre_chain)
    remove_jump("nat", "POSTROUTING", nat_post_chain)
    flush_chain("mangle", mangle_chain)
    flush_chain("mangle", mangle_post_chain)
    flush_chain("nat", nat_pre_chain)
    flush_chain("nat", nat_post_chain)

    ensure_chain("filter", filter_chain)
    ensure_chain("filter", input_chain)
    ensure_jump("filter", "FORWARD", filter_chain, position=1)
    ensure_jump("filter", "INPUT", input_chain, position=1)

    flush_chain("filter", filter_chain)
    flush_chain("filter", input_chain)

    must(["iptables", "-A", filter_chain, "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT"])
    must(["iptables", "-A", input_chain, "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT"])

    for module in modules:
        cid = int(module["id"])
        name = str(module["name"])
        peer_cidr = str(module["peer_ip"])
        ipaddress.ip_network(peer_cidr, strict=False)
        udp500, udp4500, esp50, _force_4500_to_500 = customer_protocol_flags(module)

        tunnel_mode, tunnel_ifname, tunnel_ttl, tunnel_key = customer_tunnel_settings(module, name, cid)
        module_inside_ip = str(module.get("inside_ip", inside_ip)).strip()
        if transport_local_mode == "interface_ip":
            cust_inside_ip = inside_ip
            if module_inside_ip != inside_ip:
                remove_local_ipv4(inside_if, module_inside_ip)
        else:
            cust_inside_ip = module_inside_ip
        cust_backend_ul = str(module.get("backend_underlay_ip", backend_ul)).strip()
        ipaddress.ip_address(cust_inside_ip)
        ipaddress.ip_address(cust_backend_ul)
        if transport_local_mode != "interface_ip" and cust_inside_ip != inside_ip:
            ensure_local_ipv4(inside_if, cust_inside_ip, prefix_len=32)
        if "overlay" in module and module["overlay"]:
            mux_overlay = str(module["overlay"]["mux_ip"])
        else:
            mux_overlay, _ = calc_overlay(overlay_pool, cid)
        ensure_tunnel(
            tunnel_ifname,
            cust_inside_ip,
            cust_backend_ul,
            mux_overlay,
            mode=tunnel_mode,
            ttl=tunnel_ttl,
            key=tunnel_key,
        )

        ipsec_cfg = module.get("ipsec", {}) or {}
        local_subnets = subnet_list(ipsec_cfg.get("local_subnets", []))
        remote_subnets = subnet_list(ipsec_cfg.get("remote_subnets", []))

        for local_subnet in local_subnets:
            must(["ip", "route", "replace", local_subnet, "dev", tunnel_ifname])

        for remote_subnet in remote_subnets:
            for local_subnet in local_subnets:
                must(["iptables", "-A", filter_chain, "-s", remote_subnet, "-d", local_subnet, "-o", tunnel_ifname, "-j", "ACCEPT"])
                must(["iptables", "-A", filter_chain, "-i", tunnel_ifname, "-s", local_subnet, "-d", remote_subnet, "-j", "ACCEPT"])

        for dst in sorted({public_ip, public_priv_ip}):
            if udp500:
                must(["iptables", "-A", input_chain, "-i", pub_if, "-s", peer_cidr, "-d", dst, "-p", "udp", "--dport", "500", "-j", "ACCEPT"])
            if udp4500:
                must(["iptables", "-A", input_chain, "-i", pub_if, "-s", peer_cidr, "-d", dst, "-p", "udp", "--dport", "4500", "-j", "ACCEPT"])
            if esp50:
                must(["iptables", "-A", input_chain, "-i", pub_if, "-s", peer_cidr, "-d", dst, "-p", "50", "-j", "ACCEPT"])

    if default_drop:
        for drop_dst in sorted({public_ip, public_priv_ip}):
            must(["iptables", "-A", input_chain, "-i", pub_if, "-d", drop_dst, "-p", "udp", "--dport", "500", "-j", "DROP"])
            must(["iptables", "-A", input_chain, "-i", pub_if, "-d", drop_dst, "-p", "udp", "--dport", "4500", "-j", "DROP"])
            must(["iptables", "-A", input_chain, "-i", pub_if, "-d", drop_dst, "-p", "50", "-j", "DROP"])

    conf_path, secrets_path, conn_count = render_strongswan(global_cfg, modules)
    print(f"Applied {len(modules)} customer module(s).")
    print("Mode: muxer-termination (IPsec terminated locally; cleartext routed over per-customer IPIP).")
    print(f"Rendered strongSwan: {conf_path} and {secrets_path} with {conn_count} connection(s).")
