#!/usr/bin/env python3
"""CLI entrypoint for modular muxer control."""

from __future__ import annotations

import argparse
import ipaddress
from typing import Any, Dict, List

from .core import (
    CFG_DIR,
    CFG_GLOBAL,
    delete_chain,
    ensure_sysctl,
    iface_primary_ipv4,
    load_yaml,
    natd_dpi_settings,
    nfqueue_bridge_settings,
    norm_int,
    remove_jump,
)
from .customers import (
    calc_overlay,
    customer_natd_flags,
    customer_protocol_flags,
    customer_tunnel_settings,
    subnet_list,
)
from .modes import apply_passthrough, apply_termination
from .strongswan import render_strongswan
from .variables import load_module, load_modules


def print_module_summary(
    module: Dict[str, Any],
    *,
    base_mark: int,
    base_table: int,
    overlay_pool: ipaddress.IPv4Network,
) -> None:
    cid = int(module["id"])
    name = str(module["name"])
    peer = str(module["peer_ip"])
    mark = hex(base_mark + cid) if "mark" not in module else hex(norm_int(module["mark"]))
    table = base_table + cid if "table" not in module else int(module["table"])
    tunnel_mode, tunnel_ifname, _tunnel_ttl, tunnel_key = customer_tunnel_settings(module, name, cid)
    if "overlay" in module and module["overlay"]:
        mux_ip = str(module["overlay"]["mux_ip"])
        rtr_ip = str(module["overlay"]["router_ip"])
    else:
        mux_ip, rtr_ip = calc_overlay(overlay_pool, cid)
    udp500, udp4500, esp50, force_4500_to_500 = customer_protocol_flags(module)
    natd_rewrite_enabled, natd_inner_ip = customer_natd_flags(module)
    ipsec_cfg = module.get("ipsec", {}) or {}
    local_subnets = subnet_list(ipsec_cfg.get("local_subnets", []))
    remote_subnets = subnet_list(ipsec_cfg.get("remote_subnets", []))
    natd_label = (
        f"natd_rewrite={natd_rewrite_enabled}({natd_inner_ip}) "
        if natd_inner_ip
        else f"natd_rewrite={natd_rewrite_enabled} "
    )
    print(
        f"{name}: peer={peer} mark={mark} table={table} "
        f"tunnel({tunnel_mode},if={tunnel_ifname},key={tunnel_key if tunnel_key is not None else '-'}) "
        f"overlay_mux={mux_ip} overlay_rtr={rtr_ip} "
        f"proto(500={udp500},4500={udp4500},esp={esp50}) "
        f"force4500to500={force_4500_to_500} "
        f"{natd_label}"
        f"local={','.join(local_subnets) if local_subnets else '-'} "
        f"remote={','.join(remote_subnets) if remote_subnets else '-'}"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["apply", "flush", "show", "show-customer", "render-ipsec"])
    ap.add_argument("customer", nargs="?")
    args = ap.parse_args()

    if not CFG_GLOBAL.exists():
        raise SystemExit(f"Missing {CFG_GLOBAL}. Copy this project to /etc/muxer.")

    global_cfg = load_yaml(CFG_GLOBAL)
    public_ip = str(global_cfg["public_ip"])
    ipaddress.ip_address(public_ip)

    pub_if = str(global_cfg["interfaces"]["public_if"])
    inside_ip = str(global_cfg["interfaces"]["inside_ip"])
    inside_if = str(global_cfg["interfaces"]["inside_if"])
    backend_ul = str(global_cfg["backend_underlay_ip"])

    public_priv_ip = str(global_cfg["interfaces"].get("public_private_ip") or iface_primary_ipv4(pub_if))
    ipaddress.ip_address(public_priv_ip)
    transport_local_mode = str(
        ((global_cfg.get("transport_identity", {}) or {}).get("local_underlay_mode", "module_inside_ip"))
    ).strip().lower()
    if transport_local_mode not in {"module_inside_ip", "interface_ip"}:
        raise SystemExit(
            "transport_identity.local_underlay_mode must be one of: module_inside_ip, interface_ip"
        )

    overlay_pool = ipaddress.ip_network(str(global_cfg["overlay_pool"]), strict=False)
    base_table = int(global_cfg["allocation"]["base_table"])
    base_mark = norm_int(global_cfg["allocation"]["base_mark"])

    mangle_chain = global_cfg["iptables"]["chains"]["mangle_chain"]
    mangle_post_chain = global_cfg["iptables"]["chains"].get("mangle_postrouting_chain", "MUXER_MANGLE_POST")
    filter_chain = global_cfg["iptables"]["chains"]["filter_chain"]
    nat_pre_chain = global_cfg["iptables"]["chains"].get("nat_prerouting_chain", "MUXER_NAT_PRE")
    nat_post_chain = global_cfg["iptables"]["chains"].get("nat_postrouting_chain", "MUXER_NAT_POST")
    input_chain = str(global_cfg["iptables"]["chains"].get("input_chain", "MUXER_INPUT"))
    default_drop = bool(global_cfg["iptables"].get("default_drop_ipsec_to_public_ip", True))
    nat_rewrite = bool(global_cfg["iptables"].get("use_nat_rewrite", True))
    nfqueue_enabled, nfqueue_queue_in, nfqueue_queue_out, nfqueue_queue_bypass = nfqueue_bridge_settings(global_cfg)
    natd_dpi_enabled, natd_dpi_queue_in, natd_dpi_queue_out, natd_dpi_queue_bypass = natd_dpi_settings(global_cfg)
    mode = str(global_cfg.get("mode", "pass_through")).lower()

    if args.cmd == "show":
        modules: List[Dict[str, Any]] = load_modules(overlay_pool, cfg_dir=CFG_DIR, global_cfg=global_cfg)
        for module in modules:
            print_module_summary(module, base_mark=base_mark, base_table=base_table, overlay_pool=overlay_pool)
        print(f"mode={mode}")
        print(
            f"nfqueue_ike_bridge(enabled={nfqueue_enabled},queue_in={nfqueue_queue_in},"
            f"queue_out={nfqueue_queue_out},queue_bypass={nfqueue_queue_bypass})"
        )
        print(
            f"natd_dpi_rewrite(enabled={natd_dpi_enabled},queue_in={natd_dpi_queue_in},"
            f"queue_out={natd_dpi_queue_out},queue_bypass={natd_dpi_queue_bypass})"
        )
        return

    if args.cmd == "show-customer":
        if not str(args.customer or "").strip():
            raise SystemExit("show-customer requires a customer selector")
        module = load_module(
            str(args.customer),
            overlay_pool,
            cfg_dir=CFG_DIR,
            global_cfg=global_cfg,
            source_backend="auto",
        )
        print_module_summary(module, base_mark=base_mark, base_table=base_table, overlay_pool=overlay_pool)
        print(f"mode={mode}")
        return

    if args.cmd == "render-ipsec":
        modules = load_modules(overlay_pool, cfg_dir=CFG_DIR, global_cfg=global_cfg)
        conf_path, secrets_path, conn_count = render_strongswan(global_cfg, modules)
        print(f"Rendered {conn_count} connection(s) to {conf_path} and {secrets_path}")
        return

    if args.cmd == "flush":
        remove_jump("mangle", "PREROUTING", mangle_chain)
        remove_jump("mangle", "POSTROUTING", mangle_post_chain)
        remove_jump("filter", "FORWARD", filter_chain)
        remove_jump("filter", "INPUT", input_chain)
        remove_jump("nat", "PREROUTING", nat_pre_chain)
        remove_jump("nat", "POSTROUTING", nat_post_chain)

        delete_chain("mangle", mangle_chain)
        delete_chain("mangle", mangle_post_chain)
        delete_chain("filter", filter_chain)
        delete_chain("filter", input_chain)
        delete_chain("nat", nat_pre_chain)
        delete_chain("nat", nat_post_chain)

        print("Removed MUXER iptables chains (if present). Note: ip rules/tunnels are not removed automatically.")
        return

    ensure_sysctl()

    if mode in {"terminate", "termination", "ipsec_termination", "mux_terminate"}:
        modules = load_modules(overlay_pool, cfg_dir=CFG_DIR, global_cfg=global_cfg)
        apply_termination(
            global_cfg,
            modules,
            pub_if,
            inside_if,
            public_ip,
            public_priv_ip,
            inside_ip,
            backend_ul,
            transport_local_mode,
            overlay_pool,
            mangle_chain,
            mangle_post_chain,
            filter_chain,
            nat_pre_chain,
            nat_post_chain,
            default_drop,
        )
    else:
        modules = load_modules(overlay_pool, cfg_dir=CFG_DIR, global_cfg=global_cfg)
        apply_passthrough(
            modules,
            pub_if,
            inside_if,
            public_ip,
            public_priv_ip,
            inside_ip,
            backend_ul,
            transport_local_mode,
            overlay_pool,
            base_table,
            base_mark,
            mangle_chain,
            filter_chain,
            nat_rewrite,
            nat_pre_chain,
            nat_post_chain,
            mangle_post_chain,
            nfqueue_enabled,
            nfqueue_queue_in,
            nfqueue_queue_out,
            nfqueue_queue_bypass,
            natd_dpi_enabled,
            natd_dpi_queue_in,
            natd_dpi_queue_out,
            natd_dpi_queue_bypass,
            default_drop,
        )
