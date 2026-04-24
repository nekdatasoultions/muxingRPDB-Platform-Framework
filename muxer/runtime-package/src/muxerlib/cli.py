#!/usr/bin/env python3
"""CLI entrypoint for modular muxer control."""

from __future__ import annotations

import argparse
import ipaddress
from typing import Any, Dict, List

from .core import (
    CFG_DIR,
    CFG_GLOBAL,
    ensure_sysctl,
    iface_primary_ipv4,
    load_yaml,
    natd_dpi_settings,
    nfqueue_bridge_settings,
    norm_int,
)
from .customers import (
    calc_overlay,
    customer_natd_flags,
    customer_protocol_flags,
    customer_tunnel_settings,
    subnet_list,
)
from .modes import (
    apply_customer_passthrough,
    apply_passthrough,
    remove_customer_passthrough,
)
from .nftables import flush_passthrough_nft_classification, passthrough_nft_settings
from .strongswan import render_strongswan
from .variables import CUSTOMER_MODULES_DIR, load_module, load_modules


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
    tunnel_mode, tunnel_ifname, _tunnel_ttl, tunnel_key, _tunnel_mtu = customer_tunnel_settings(
        module, name, cid
    )
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
    ap.add_argument("cmd", choices=["apply", "flush", "show", "show-customer", "apply-customer", "remove-customer", "render-ipsec"])
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

    legacy_firewall_key = "ip" + "tables"
    if legacy_firewall_key in global_cfg:
        raise SystemExit("RPDB runtime config must use firewall_policy; legacy firewall sections are blocked")
    firewall_policy = global_cfg.get("firewall_policy", {}) or {}
    firewall_chains = firewall_policy.get("chains", {}) or {}
    mangle_chain = str(firewall_chains.get("mangle_chain", "MUXER_MANGLE"))
    mangle_post_chain = str(firewall_chains.get("mangle_postrouting_chain", "MUXER_MANGLE_POST"))
    filter_chain = str(firewall_chains.get("filter_chain", "MUXER_FILTER"))
    nat_pre_chain = str(firewall_chains.get("nat_prerouting_chain", "MUXER_NAT_PRE"))
    nat_post_chain = str(firewall_chains.get("nat_postrouting_chain", "MUXER_NAT_POST"))
    default_drop = bool(firewall_policy.get("default_drop_ipsec_to_public_ip", True))
    nat_rewrite = bool(firewall_policy.get("use_nat_rewrite", True))
    nfqueue_enabled, nfqueue_queue_in, nfqueue_queue_out, nfqueue_queue_bypass = nfqueue_bridge_settings(global_cfg)
    natd_dpi_enabled, natd_dpi_queue_in, natd_dpi_queue_out, natd_dpi_queue_bypass = natd_dpi_settings(global_cfg)
    mode = str(global_cfg.get("mode", "pass_through")).lower()
    nft_settings = passthrough_nft_settings(global_cfg)
    classification_backend = str(nft_settings["classification_backend"])
    translation_backend = str(nft_settings["translation_backend"])
    bridge_backend = str(nft_settings["bridge_backend"])

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
        print(f"pass_through_classification_backend={classification_backend}")
        print(f"pass_through_translation_backend={translation_backend}")
        print(f"pass_through_bridge_backend={bridge_backend}")
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
            allow_scan_fallback=False,
        )
        print_module_summary(module, base_mark=base_mark, base_table=base_table, overlay_pool=overlay_pool)
        print(f"mode={mode}")
        return

    if args.cmd in {"apply-customer", "remove-customer"}:
        if not str(args.customer or "").strip():
            raise SystemExit(f"{args.cmd} requires a customer selector")
        module = load_module(
            str(args.customer),
            overlay_pool,
            cfg_dir=CFG_DIR,
            global_cfg=global_cfg,
            source_backend="auto",
            allow_scan_fallback=False,
        )
        ensure_sysctl()
        if mode in {"terminate", "termination", "ipsec_termination", "mux_terminate"}:
            raise SystemExit(f"{args.cmd} is not implemented yet for muxer termination mode")
        classification_modules: List[Dict[str, Any]] | None = None
        if classification_backend == "nftables" or translation_backend == "nftables" or bridge_backend == "nftables":
            classification_modules = load_modules(
                overlay_pool,
                cfg_dir=CFG_DIR,
                customer_modules_dir=CUSTOMER_MODULES_DIR,
                global_cfg=global_cfg,
                source_backend="customer_modules",
            )
            if not classification_modules:
                raise SystemExit(
                    "nftables pass-through backends require local customer inventory in config/customer-modules"
                )
        if args.cmd == "apply-customer":
            apply_customer_passthrough(
                module,
                pub_if=pub_if,
                inside_if=inside_if,
                public_ip=public_ip,
                public_priv_ip=public_priv_ip,
                inside_ip=inside_ip,
                backend_ul=backend_ul,
                transport_local_mode=transport_local_mode,
                overlay_pool=overlay_pool,
                base_table=base_table,
                base_mark=base_mark,
                mangle_chain=mangle_chain,
                filter_chain=filter_chain,
                nat_rewrite=nat_rewrite,
                nat_pre_chain=nat_pre_chain,
                nat_post_chain=nat_post_chain,
                mangle_post_chain=mangle_post_chain,
                nfqueue_enabled=nfqueue_enabled,
                nfqueue_queue_in=nfqueue_queue_in,
                nfqueue_queue_out=nfqueue_queue_out,
                nfqueue_queue_bypass=nfqueue_queue_bypass,
                natd_dpi_enabled=natd_dpi_enabled,
                natd_dpi_queue_in=natd_dpi_queue_in,
                natd_dpi_queue_out=natd_dpi_queue_out,
                natd_dpi_queue_bypass=natd_dpi_queue_bypass,
                default_drop=default_drop,
                classification_backend=classification_backend,
                translation_backend=translation_backend,
                bridge_backend=bridge_backend,
                classification_state_root=str(nft_settings["state_root"]),
                classification_table_name=str(nft_settings["table_name"]),
                translation_table_name=str(nft_settings["nat_table_name"]),
                classification_modules=classification_modules,
            )
        else:
            remove_customer_passthrough(
                module,
                inside_if=inside_if,
                inside_ip=inside_ip,
                transport_local_mode=transport_local_mode,
                base_table=base_table,
                base_mark=base_mark,
                mangle_chain=mangle_chain,
                mangle_post_chain=mangle_post_chain,
                filter_chain=filter_chain,
                nat_pre_chain=nat_pre_chain,
                nat_post_chain=nat_post_chain,
                nfqueue_enabled=nfqueue_enabled,
                nfqueue_queue_in=nfqueue_queue_in,
                nfqueue_queue_out=nfqueue_queue_out,
                nfqueue_queue_bypass=nfqueue_queue_bypass,
                natd_dpi_enabled=natd_dpi_enabled,
                natd_dpi_queue_in=natd_dpi_queue_in,
                natd_dpi_queue_out=natd_dpi_queue_out,
                natd_dpi_queue_bypass=natd_dpi_queue_bypass,
                classification_backend=classification_backend,
                translation_backend=translation_backend,
                bridge_backend=bridge_backend,
                classification_state_root=str(nft_settings["state_root"]),
                classification_table_name=str(nft_settings["table_name"]),
                translation_table_name=str(nft_settings["nat_table_name"]),
                classification_modules=classification_modules,
                pub_if=pub_if,
                public_ip=public_ip,
                public_priv_ip=public_priv_ip,
                default_drop=default_drop,
            )
        return

    if args.cmd == "render-ipsec":
        modules = load_modules(overlay_pool, cfg_dir=CFG_DIR, global_cfg=global_cfg)
        conf_path, secrets_path, conn_count = render_strongswan(global_cfg, modules)
        print(f"Rendered {conn_count} connection(s) to {conf_path} and {secrets_path}")
        return

    if args.cmd == "flush":
        flush_passthrough_nft_classification(global_cfg)
        print("Flushed RPDB nftables pass-through state. Note: ip rules/tunnels are not removed automatically.")
        return

    ensure_sysctl()

    if mode in {"terminate", "termination", "ipsec_termination", "mux_terminate"}:
        raise SystemExit("RPDB runtime blocks termination mode until it is implemented with nftables-only activation")
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
            classification_backend,
            translation_backend,
            bridge_backend,
            str(nft_settings["state_root"]),
            str(nft_settings["table_name"]),
            str(nft_settings["nat_table_name"]),
        )
