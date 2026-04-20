#!/usr/bin/env python3
"""Apply handlers for the RPDB nftables-only pass-through runtime."""

from __future__ import annotations

import ipaddress
from typing import Any, Dict, List

from .core import (
    ensure_local_ipv4,
    ensure_policy,
    ensure_tunnel,
    flush_route_table,
    remove_local_ipv4,
    remove_policy,
    remove_tunnel,
)
from .customers import (
    calc_overlay,
    customer_natd_flags,
    customer_protocol_flags,
    customer_tunnel_settings,
)
from .nftables import apply_passthrough_nft_state


def _use_nft_backend(backend: str) -> bool:
    return str(backend or "").strip().lower() == "nftables"


def _require_nft_only(
    *,
    classification_backend: str,
    translation_backend: str,
    bridge_backend: str,
) -> None:
    blocked = {
        "classification_backend": classification_backend,
        "translation_backend": translation_backend,
        "bridge_backend": bridge_backend,
    }
    invalid = {
        name: value
        for name, value in blocked.items()
        if not _use_nft_backend(str(value))
    }
    if invalid:
        detail = ", ".join(f"{name}={value}" for name, value in sorted(invalid.items()))
        raise SystemExit(f"RPDB runtime requires nftables-only pass-through backends: {detail}")


def _passthrough_nft_global_cfg(
    *,
    public_ip: str,
    public_priv_ip: str,
    pub_if: str,
    default_drop: bool,
    nat_rewrite: bool,
    base_mark: int,
    classification_backend: str,
    translation_backend: str,
    bridge_backend: str,
    nfqueue_enabled: bool,
    nfqueue_queue_in: int,
    nfqueue_queue_out: int,
    nfqueue_queue_bypass: bool,
    natd_dpi_enabled: bool,
    natd_dpi_queue_in: int,
    natd_dpi_queue_out: int,
    natd_dpi_queue_bypass: bool,
    classification_state_root: str,
    classification_table_name: str,
    translation_table_name: str,
) -> Dict[str, Any]:
    return {
        "public_ip": public_ip,
        "interfaces": {
            "public_private_ip": public_priv_ip,
            "public_if": pub_if,
        },
        "firewall_policy": {
            "default_drop_ipsec_to_public_ip": default_drop,
            "use_nat_rewrite": nat_rewrite,
        },
        "allocation": {
            "base_mark": hex(int(base_mark)),
        },
        "nftables": {
            "pass_through": {
                "classification_backend": classification_backend,
                "translation_backend": translation_backend,
                "bridge_backend": bridge_backend,
                "state_root": classification_state_root,
                "table_name": classification_table_name,
                "nat_table_name": translation_table_name,
            }
        },
        "experimental": {
            "nfqueue_ike_bridge": {
                "enabled": nfqueue_enabled,
                "queue_in": nfqueue_queue_in,
                "queue_out": nfqueue_queue_out,
                "queue_bypass": nfqueue_queue_bypass,
            },
            "natd_dpi_rewrite": {
                "enabled": natd_dpi_enabled,
                "queue_in": natd_dpi_queue_in,
                "queue_out": natd_dpi_queue_out,
                "queue_bypass": natd_dpi_queue_bypass,
            },
        },
    }


def _merge_classification_modules(
    modules: List[Dict[str, Any]] | None,
    *,
    selected_module: Dict[str, Any] | None = None,
    remove_name: str = "",
) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for module in modules or []:
        merged[str(module["name"])] = module
    if selected_module is not None:
        merged[str(selected_module["name"])] = selected_module
    if remove_name:
        merged.pop(str(remove_name), None)
    return sorted(merged.values(), key=lambda item: (int(item["id"]), str(item["name"])))


def _validate_passthrough_module(
    module: Dict[str, Any],
    *,
    name: str,
    peer_cidr: str,
    nat_rewrite: bool,
    public_ip: str,
    public_priv_ip: str,
) -> None:
    ipaddress.ip_network(peer_cidr, strict=False)
    udp500, _udp4500, _esp50, force_4500_to_500 = customer_protocol_flags(module)
    natd_rewrite_enabled, _natd_inner_ip = customer_natd_flags(module)
    if force_4500_to_500 and not udp500:
        raise SystemExit(f"{name}: protocols.force_rewrite_4500_to_500 requires protocols.udp500=true")
    if force_4500_to_500 and not nat_rewrite:
        raise SystemExit(f"{name}: protocols.force_rewrite_4500_to_500 requires firewall_policy.use_nat_rewrite=true")
    if natd_rewrite_enabled and not udp500:
        raise SystemExit(f"{name}: natd_rewrite.enabled requires protocols.udp500=true")
    if natd_rewrite_enabled and force_4500_to_500:
        raise SystemExit(f"{name}: natd_rewrite.enabled conflicts with protocols.force_rewrite_4500_to_500")
    if natd_rewrite_enabled and public_priv_ip != public_ip and not nat_rewrite:
        raise SystemExit(
            f"{name}: natd_rewrite.enabled requires firewall_policy.use_nat_rewrite=true "
            "when public_private_ip != public_ip"
        )


def _clear_passthrough_customer_transport(
    module: Dict[str, Any],
    *,
    inside_if: str,
    inside_ip: str,
    transport_local_mode: str,
    base_table: int,
    base_mark: int,
) -> None:
    cid = int(module["id"])
    name = str(module["name"])
    _tunnel_mode, tunnel_ifname, _tunnel_ttl, _tunnel_key = customer_tunnel_settings(module, name, cid)
    mark_hex = hex(base_mark + cid) if "mark" not in module else hex(int(str(module["mark"]), 0))
    table_id = base_table + cid if "table" not in module else int(module["table"])

    remove_policy(mark_hex, table_id, priority=module.get("rpdb_priority"))
    flush_route_table(table_id)
    remove_tunnel(tunnel_ifname)

    module_inside_ip = str(module.get("inside_ip", inside_ip)).strip()
    if transport_local_mode != "interface_ip" and module_inside_ip != inside_ip:
        remove_local_ipv4(inside_if, module_inside_ip)


def _apply_passthrough_customer_transport(
    module: Dict[str, Any],
    *,
    inside_if: str,
    inside_ip: str,
    backend_ul: str,
    transport_local_mode: str,
    overlay_pool: ipaddress.IPv4Network,
    base_table: int,
    base_mark: int,
) -> None:
    cid = int(module["id"])
    name = str(module["name"])
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
    classification_backend: str = "nftables",
    translation_backend: str = "nftables",
    bridge_backend: str = "nftables",
    classification_state_root: str = "/var/lib/rpdb-muxer/nftables",
    classification_table_name: str = "muxer_passthrough",
    translation_table_name: str = "muxer_passthrough_nat",
) -> None:
    _require_nft_only(
        classification_backend=classification_backend,
        translation_backend=translation_backend,
        bridge_backend=bridge_backend,
    )
    nft_global_cfg = _passthrough_nft_global_cfg(
        public_ip=public_ip,
        public_priv_ip=public_priv_ip,
        pub_if=pub_if,
        default_drop=default_drop,
        nat_rewrite=nat_rewrite,
        base_mark=base_mark,
        classification_backend=classification_backend,
        translation_backend=translation_backend,
        bridge_backend=bridge_backend,
        nfqueue_enabled=nfqueue_enabled,
        nfqueue_queue_in=nfqueue_queue_in,
        nfqueue_queue_out=nfqueue_queue_out,
        nfqueue_queue_bypass=nfqueue_queue_bypass,
        natd_dpi_enabled=natd_dpi_enabled,
        natd_dpi_queue_in=natd_dpi_queue_in,
        natd_dpi_queue_out=natd_dpi_queue_out,
        natd_dpi_queue_bypass=natd_dpi_queue_bypass,
        classification_state_root=classification_state_root,
        classification_table_name=classification_table_name,
        translation_table_name=translation_table_name,
    )
    for module in modules:
        cid = int(module["id"])
        name = str(module["name"])
        peer_cidr = str(module["peer_ip"])
        _validate_passthrough_module(
            module,
            name=name,
            peer_cidr=peer_cidr,
            nat_rewrite=nat_rewrite,
            public_ip=public_ip,
            public_priv_ip=public_priv_ip,
        )
        _apply_passthrough_customer_transport(
            module,
            inside_if=inside_if,
            inside_ip=inside_ip,
            backend_ul=backend_ul,
            transport_local_mode=transport_local_mode,
            overlay_pool=overlay_pool,
            base_table=base_table,
            base_mark=base_mark,
        )
    apply_passthrough_nft_state(modules, nft_global_cfg)
    print(f"Applied {len(modules)} customer module(s).")
    print("Mode: pass-through (IPsec terminated on backend).")


def apply_customer_passthrough(
    module: Dict[str, Any],
    *,
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
    classification_backend: str = "nftables",
    translation_backend: str = "nftables",
    bridge_backend: str = "nftables",
    classification_state_root: str = "/var/lib/rpdb-muxer/nftables",
    classification_table_name: str = "muxer_passthrough",
    translation_table_name: str = "muxer_passthrough_nat",
    classification_modules: List[Dict[str, Any]] | None = None,
) -> None:
    _require_nft_only(
        classification_backend=classification_backend,
        translation_backend=translation_backend,
        bridge_backend=bridge_backend,
    )
    if classification_modules is None:
        raise SystemExit("nftables pass-through backends require local customer inventory for customer-scoped apply")

    name = str(module["name"])
    peer_cidr = str(module["peer_ip"])
    _validate_passthrough_module(
        module,
        name=name,
        peer_cidr=peer_cidr,
        nat_rewrite=nat_rewrite,
        public_ip=public_ip,
        public_priv_ip=public_priv_ip,
    )
    _clear_passthrough_customer_transport(
        module,
        inside_if=inside_if,
        inside_ip=inside_ip,
        transport_local_mode=transport_local_mode,
        base_table=base_table,
        base_mark=base_mark,
    )
    _apply_passthrough_customer_transport(
        module,
        inside_if=inside_if,
        inside_ip=inside_ip,
        backend_ul=backend_ul,
        transport_local_mode=transport_local_mode,
        overlay_pool=overlay_pool,
        base_table=base_table,
        base_mark=base_mark,
    )

    nft_global_cfg = _passthrough_nft_global_cfg(
        public_ip=public_ip,
        public_priv_ip=public_priv_ip,
        pub_if=pub_if,
        default_drop=default_drop,
        nat_rewrite=nat_rewrite,
        base_mark=base_mark,
        classification_backend=classification_backend,
        translation_backend=translation_backend,
        bridge_backend=bridge_backend,
        nfqueue_enabled=nfqueue_enabled,
        nfqueue_queue_in=nfqueue_queue_in,
        nfqueue_queue_out=nfqueue_queue_out,
        nfqueue_queue_bypass=nfqueue_queue_bypass,
        natd_dpi_enabled=natd_dpi_enabled,
        natd_dpi_queue_in=natd_dpi_queue_in,
        natd_dpi_queue_out=natd_dpi_queue_out,
        natd_dpi_queue_bypass=natd_dpi_queue_bypass,
        classification_state_root=classification_state_root,
        classification_table_name=classification_table_name,
        translation_table_name=translation_table_name,
    )
    merged_modules = _merge_classification_modules(classification_modules, selected_module=module)
    apply_passthrough_nft_state(merged_modules, nft_global_cfg)
    print(f"Applied customer module {module['name']}.")
    print("Mode: pass-through (customer-scoped delta apply).")


def remove_customer_passthrough(
    module: Dict[str, Any],
    *,
    inside_if: str,
    inside_ip: str,
    transport_local_mode: str,
    base_table: int,
    base_mark: int,
    mangle_chain: str,
    mangle_post_chain: str,
    filter_chain: str,
    nat_pre_chain: str,
    nat_post_chain: str,
    nfqueue_enabled: bool = False,
    nfqueue_queue_in: int = 2101,
    nfqueue_queue_out: int = 2102,
    nfqueue_queue_bypass: bool = True,
    natd_dpi_enabled: bool = False,
    natd_dpi_queue_in: int = 2111,
    natd_dpi_queue_out: int = 2112,
    natd_dpi_queue_bypass: bool = True,
    classification_backend: str = "nftables",
    translation_backend: str = "nftables",
    bridge_backend: str = "nftables",
    classification_state_root: str = "/var/lib/rpdb-muxer/nftables",
    classification_table_name: str = "muxer_passthrough",
    translation_table_name: str = "muxer_passthrough_nat",
    classification_modules: List[Dict[str, Any]] | None = None,
    pub_if: str = "",
    public_ip: str = "",
    public_priv_ip: str = "",
    default_drop: bool = True,
) -> None:
    _require_nft_only(
        classification_backend=classification_backend,
        translation_backend=translation_backend,
        bridge_backend=bridge_backend,
    )
    if classification_modules is None:
        raise SystemExit("nftables pass-through backends require local customer inventory for customer-scoped remove")

    _clear_passthrough_customer_transport(
        module,
        inside_if=inside_if,
        inside_ip=inside_ip,
        transport_local_mode=transport_local_mode,
        base_table=base_table,
        base_mark=base_mark,
    )
    nft_global_cfg = _passthrough_nft_global_cfg(
        public_ip=public_ip,
        public_priv_ip=public_priv_ip,
        pub_if=pub_if,
        default_drop=default_drop,
        nat_rewrite=True,
        base_mark=base_mark,
        classification_backend=classification_backend,
        translation_backend=translation_backend,
        bridge_backend=bridge_backend,
        nfqueue_enabled=nfqueue_enabled,
        nfqueue_queue_in=nfqueue_queue_in,
        nfqueue_queue_out=nfqueue_queue_out,
        nfqueue_queue_bypass=nfqueue_queue_bypass,
        natd_dpi_enabled=natd_dpi_enabled,
        natd_dpi_queue_in=natd_dpi_queue_in,
        natd_dpi_queue_out=natd_dpi_queue_out,
        natd_dpi_queue_bypass=natd_dpi_queue_bypass,
        classification_state_root=classification_state_root,
        classification_table_name=classification_table_name,
        translation_table_name=translation_table_name,
    )
    remaining_modules = _merge_classification_modules(classification_modules, remove_name=str(module["name"]))
    apply_passthrough_nft_state(remaining_modules, nft_global_cfg)
    print(f"Removed customer module {module['name']}.")
    print("Mode: pass-through (customer-scoped delta remove).")


def apply_termination(*args: Any, **kwargs: Any) -> None:
    raise SystemExit("RPDB runtime blocks termination mode until it is implemented with nftables-only activation")
