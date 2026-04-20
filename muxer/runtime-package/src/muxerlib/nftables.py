#!/usr/bin/env python3
"""nftables helpers for pass-through customers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .core import must, natd_dpi_settings, nfqueue_bridge_settings, norm_int, sh
from .customers import customer_headend_egress_sources, customer_natd_flags, customer_protocol_flags

DEFAULT_PASS_THROUGH_TABLE = "muxer_passthrough"
DEFAULT_PASS_THROUGH_NAT_TABLE = "muxer_passthrough_nat"
DEFAULT_PASS_THROUGH_STATE_ROOT = Path("/var/lib/rpdb-muxer/nftables")


def _normalize_backend(value: Any, *, default: str = "nftables") -> str:
    raw = str(value or default).strip().lower()
    aliases = {
        "nft": "nftables",
        "nftables": "nftables",
    }
    if raw not in aliases:
        raise ValueError(f"unsupported RPDB firewall backend: {raw}")
    return aliases[raw]


def normalize_passthrough_classification_backend(value: Any, *, default: str = "nftables") -> str:
    return _normalize_backend(value, default=default)


def normalize_passthrough_translation_backend(value: Any, *, default: str = "nftables") -> str:
    return _normalize_backend(value, default=default)


def normalize_passthrough_bridge_backend(value: Any, *, default: str = "nftables") -> str:
    return _normalize_backend(value, default=default)


def passthrough_nft_settings(global_cfg: Dict[str, Any]) -> Dict[str, Any]:
    nft_cfg = (global_cfg.get("nftables") or {}).get("pass_through", {}) or {}
    classification_backend = normalize_passthrough_classification_backend(
        nft_cfg.get("classification_backend", "nftables")
    )
    translation_backend = normalize_passthrough_translation_backend(
        nft_cfg.get("translation_backend", "nftables")
    )
    bridge_backend = normalize_passthrough_bridge_backend(
        nft_cfg.get("bridge_backend", "nftables")
    )
    table_name = str(nft_cfg.get("table_name") or DEFAULT_PASS_THROUGH_TABLE).strip() or DEFAULT_PASS_THROUGH_TABLE
    nat_table_name = str(nft_cfg.get("nat_table_name") or f"{table_name}_nat").strip() or DEFAULT_PASS_THROUGH_NAT_TABLE
    state_root = Path(str(nft_cfg.get("state_root") or DEFAULT_PASS_THROUGH_STATE_ROOT)).expanduser()
    return {
        "classification_backend": classification_backend,
        "translation_backend": translation_backend,
        "bridge_backend": bridge_backend,
        "table_name": table_name,
        "nat_table_name": nat_table_name,
        "state_root": state_root,
    }


def _peer_host(module: Dict[str, Any]) -> str:
    return str(module["peer_ip"]).split("/")[0]


def _customer_mark(module: Dict[str, Any], base_mark: int) -> str:
    if "mark" in module:
        return hex(norm_int(module["mark"]))
    return hex(base_mark + int(module["id"]))


def _append_unique(items: List[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _sorted_map_items(mapping: Dict[str, str]) -> Dict[str, str]:
    return {key: mapping[key] for key in sorted(mapping)}


def _translation_key(left: str, right: str) -> str:
    return f"{left} . {right}"


def _sorted_manifest_entries(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            str(item.get("customer_name") or ""),
            str(item.get("peer_ip") or ""),
        ),
    )


def build_passthrough_nft_model(
    modules: Iterable[Dict[str, Any]],
    global_cfg: Dict[str, Any],
    *,
    render_mode: str = "nftables-batch-preview",
) -> Dict[str, Any]:
    settings = passthrough_nft_settings(global_cfg)
    interfaces = global_cfg.get("interfaces", {}) or {}
    firewall_policy = global_cfg.get("firewall_policy", {}) or {}
    public_ip = str(global_cfg["public_ip"]).strip()
    public_priv_ip = str(interfaces.get("public_private_ip") or public_ip).strip()
    pub_if = str(interfaces.get("public_if") or "").strip()
    default_drop = bool(firewall_policy.get("default_drop_ipsec_to_public_ip", True))
    nat_rewrite = bool(firewall_policy.get("use_nat_rewrite", True))
    base_mark = norm_int((global_cfg.get("allocation") or {}).get("base_mark", "0x2000"))
    backend_ul_default = str(global_cfg.get("backend_underlay_ip") or "").strip()
    nfqueue_enabled, nfqueue_queue_in, nfqueue_queue_out, nfqueue_queue_bypass = nfqueue_bridge_settings(global_cfg)
    natd_enabled, natd_dpi_queue_in, natd_dpi_queue_out, natd_dpi_queue_bypass = natd_dpi_settings(global_cfg)

    public_destinations: List[str] = []
    _append_unique(public_destinations, public_ip)
    _append_unique(public_destinations, public_priv_ip)

    udp500_accept_peers: List[str] = []
    udp4500_accept_peers: List[str] = []
    esp_accept_peers: List[str] = []
    udp500_mark_peers: List[str] = []
    udp4500_mark_peers: List[str] = []
    esp_mark_peers: List[str] = []
    peer_mark_udp500: Dict[str, str] = {}
    peer_mark_udp4500: Dict[str, str] = {}
    peer_mark_esp: Dict[str, str] = {}

    udp500_dnat: Dict[str, str] = {}
    udp4500_dnat: Dict[str, str] = {}
    udp4500_force500_dnat: Dict[str, str] = {}
    esp_dnat: Dict[str, str] = {}
    udp500_snat: Dict[str, str] = {}
    udp500_force4500_snat: Dict[str, str] = {}
    udp4500_snat: Dict[str, str] = {}
    udp4500_force4500_snat: Dict[str, str] = {}
    esp_snat: Dict[str, str] = {}

    force4500_in_pairs: List[str] = []
    force4500_out_pairs: List[str] = []
    natd_in_pairs: List[str] = []
    natd_out_pairs: List[str] = []

    bridge_manifest_force4500_in: List[Dict[str, Any]] = []
    bridge_manifest_force4500_out: List[Dict[str, Any]] = []
    bridge_manifest_natd_in: List[Dict[str, Any]] = []
    bridge_manifest_natd_out: List[Dict[str, Any]] = []

    deferred_translation_customers: List[Dict[str, Any]] = []
    deferred_bridge_customers: List[Dict[str, Any]] = []

    customer_count = 0
    translation_enabled = settings["translation_backend"] == "nftables" and nat_rewrite and public_priv_ip != public_ip
    bridge_enabled = settings["bridge_backend"] == "nftables"

    for module in modules:
        customer_count += 1
        peer = _peer_host(module)
        mark_hex = _customer_mark(module, base_mark)
        udp500, udp4500, esp50, force_4500_to_500 = customer_protocol_flags(module)
        natd_rewrite_enabled, _natd_inner_ip = customer_natd_flags(module)
        backend_underlay_ip = str(module.get("backend_underlay_ip") or backend_ul_default).strip()
        headend_egress_sources = customer_headend_egress_sources(module, backend_underlay_ip)
        nat_preroute_dst = backend_underlay_ip if udp4500 else public_ip

        if udp500:
            _append_unique(udp500_accept_peers, peer)
            _append_unique(udp500_mark_peers, peer)
            peer_mark_udp500[peer] = mark_hex

        if udp4500:
            _append_unique(udp4500_accept_peers, peer)

        if udp4500 or force_4500_to_500:
            _append_unique(udp4500_mark_peers, peer)
            peer_mark_udp4500[peer] = mark_hex

        if esp50:
            _append_unique(esp_accept_peers, peer)
            _append_unique(esp_mark_peers, peer)
            peer_mark_esp[peer] = mark_hex

        if translation_enabled:
            if udp500:
                udp500_dnat[peer] = f"dnat to {nat_preroute_dst}"
                for egress_source in headend_egress_sources:
                    key = _translation_key(egress_source, peer)
                    if force_4500_to_500:
                        udp500_force4500_snat[key] = f"snat to {public_priv_ip}:4500"
                    else:
                        udp500_snat[key] = f"snat to {public_priv_ip}"

            if force_4500_to_500:
                udp4500_force500_dnat[peer] = f"dnat to {nat_preroute_dst}:500"
                for egress_source in headend_egress_sources:
                    udp4500_force4500_snat[_translation_key(egress_source, peer)] = f"snat to {public_priv_ip}:4500"

            if udp4500:
                udp4500_dnat[peer] = f"dnat to {nat_preroute_dst}"
                for egress_source in headend_egress_sources:
                    udp4500_snat[_translation_key(egress_source, peer)] = f"snat to {public_priv_ip}"

            if esp50:
                esp_dnat[peer] = f"dnat to {nat_preroute_dst}"
                for egress_source in headend_egress_sources:
                    esp_snat[_translation_key(egress_source, peer)] = f"snat to {public_priv_ip}"
        else:
            deferred_translation_customers.append(
                {
                    "customer_name": str(module["name"]),
                    "peer_ip": peer,
                    "udp500": udp500,
                    "udp4500": udp4500,
                    "esp50": esp50,
                    "force_rewrite_4500_to_500": force_4500_to_500,
                }
            )

        bridge_handled = False
        if bridge_enabled and force_4500_to_500 and nfqueue_enabled:
            _append_unique(force4500_in_pairs, _translation_key(peer, public_ip))
            if public_priv_ip != public_ip:
                _append_unique(force4500_in_pairs, _translation_key(peer, public_priv_ip))
            _append_unique(force4500_out_pairs, _translation_key(backend_underlay_ip, peer))
            if public_ip != backend_underlay_ip:
                _append_unique(force4500_out_pairs, _translation_key(public_ip, peer))
            bridge_manifest_force4500_in.append(
                {
                    "customer_name": str(module["name"]),
                    "peer_ip": peer,
                    "destinations": sorted({public_ip, public_priv_ip}),
                    "queue_num": nfqueue_queue_in,
                    "queue_bypass": nfqueue_queue_bypass,
                }
            )
            bridge_manifest_force4500_out.append(
                {
                    "customer_name": str(module["name"]),
                    "peer_ip": peer,
                    "sources": sorted({backend_underlay_ip, public_ip}),
                    "queue_num": nfqueue_queue_out,
                    "queue_bypass": nfqueue_queue_bypass,
                }
            )
            bridge_handled = True
        elif bridge_enabled and natd_rewrite_enabled and natd_enabled:
            _append_unique(natd_in_pairs, _translation_key(peer, backend_underlay_ip))
            if public_priv_ip != public_ip:
                _append_unique(natd_in_pairs, _translation_key(peer, public_priv_ip))
            _append_unique(natd_out_pairs, _translation_key(backend_underlay_ip, peer))
            bridge_manifest_natd_in.append(
                {
                    "customer_name": str(module["name"]),
                    "peer_ip": peer,
                    "destinations": sorted({backend_underlay_ip, public_priv_ip}),
                    "queue_num": natd_dpi_queue_in,
                    "queue_bypass": natd_dpi_queue_bypass,
                }
            )
            bridge_manifest_natd_out.append(
                {
                    "customer_name": str(module["name"]),
                    "peer_ip": peer,
                    "sources": [backend_underlay_ip],
                    "queue_num": natd_dpi_queue_out,
                    "queue_bypass": natd_dpi_queue_bypass,
                }
            )
            bridge_handled = True

        if (force_4500_to_500 or natd_rewrite_enabled) and not bridge_handled:
            deferred_bridge_customers.append(
                {
                    "customer_name": str(module["name"]),
                    "peer_ip": peer,
                    "force_rewrite_4500_to_500": force_4500_to_500,
                    "natd_dpi_rewrite": natd_rewrite_enabled,
                }
            )

    notes = [
        "This nftables layer batches peer classification and fwmark assignment.",
    ]
    if translation_enabled:
        notes.append("Pass-through DNAT and SNAT rewrite now use the repo-modeled nftables NAT backend.")
    else:
        notes.append("DNAT/SNAT rewrite remains on the legacy per-customer path.")
    bridge_selector_entry_count = (
        len(force4500_in_pairs)
        + len(force4500_out_pairs)
        + len(natd_in_pairs)
        + len(natd_out_pairs)
    )
    if bridge_selector_entry_count:
        notes.append("NFQUEUE bridge selectors now use shared nftables set-based hooks plus a manifest artifact.")
    elif deferred_bridge_customers:
        notes.append("NFQUEUE bridge stages were not rendered into the shared nftables model.")
    else:
        notes.append("No customers in this render require the legacy NFQUEUE bridge path.")
    notes.append("Termination-mode customers are intentionally out of scope for this renderer.")

    return {
        "schema_version": 2,
        "scope": "pass-through-only",
        "render_mode": str(render_mode).strip() or "nftables-batch-preview",
        "classification_backend": settings["classification_backend"],
        "translation_backend": settings["translation_backend"],
        "bridge_backend": settings["bridge_backend"],
        "customer_count": customer_count,
        "notes": notes,
        "table": {
            "family": "inet",
            "name": settings["table_name"],
        },
        "translation": {
            "enabled": translation_enabled,
            "backend": settings["translation_backend"],
            "nat_table": {
                "family": "ip",
                "name": settings["nat_table_name"],
            },
            "public_destinations": sorted(public_destinations),
            "maps": {
                "udp500_dnat": _sorted_map_items(udp500_dnat),
                "udp4500_dnat": _sorted_map_items(udp4500_dnat),
                "udp4500_force500_dnat": _sorted_map_items(udp4500_force500_dnat),
                "esp_dnat": _sorted_map_items(esp_dnat),
                "udp500_snat": _sorted_map_items(udp500_snat),
                "udp500_force4500_snat": _sorted_map_items(udp500_force4500_snat),
                "udp4500_snat": _sorted_map_items(udp4500_snat),
                "udp4500_force4500_snat": _sorted_map_items(udp4500_force4500_snat),
                "esp_snat": _sorted_map_items(esp_snat),
            },
        },
        "bridge": {
            "enabled": bridge_selector_entry_count > 0,
            "backend": settings["bridge_backend"],
            "queue_hooks": {
                "force4500_in": {
                    "queue_num": nfqueue_queue_in,
                    "queue_bypass": nfqueue_queue_bypass,
                    "selector_count": len(force4500_in_pairs),
                },
                "force4500_out": {
                    "queue_num": nfqueue_queue_out,
                    "queue_bypass": nfqueue_queue_bypass,
                    "selector_count": len(force4500_out_pairs),
                },
                "natd_in": {
                    "queue_num": natd_dpi_queue_in,
                    "queue_bypass": natd_dpi_queue_bypass,
                    "selector_count": len(natd_in_pairs),
                },
                "natd_out": {
                    "queue_num": natd_dpi_queue_out,
                    "queue_bypass": natd_dpi_queue_bypass,
                    "selector_count": len(natd_out_pairs),
                },
            },
            "sets": {
                "force4500_in_pairs": sorted(force4500_in_pairs),
                "force4500_out_pairs": sorted(force4500_out_pairs),
                "natd_in_pairs": sorted(natd_in_pairs),
                "natd_out_pairs": sorted(natd_out_pairs),
            },
            "manifest": {
                "force4500_in": _sorted_manifest_entries(bridge_manifest_force4500_in),
                "force4500_out": _sorted_manifest_entries(bridge_manifest_force4500_out),
                "natd_in": _sorted_manifest_entries(bridge_manifest_natd_in),
                "natd_out": _sorted_manifest_entries(bridge_manifest_natd_out),
            },
        },
        "interfaces": {
            "public_if": pub_if,
            "public_destinations": sorted(public_destinations),
        },
        "default_drop": default_drop,
        "sets": {
            "udp500_accept_peers": sorted(udp500_accept_peers),
            "udp4500_accept_peers": sorted(udp4500_accept_peers),
            "esp_accept_peers": sorted(esp_accept_peers),
            "udp500_mark_peers": sorted(udp500_mark_peers),
            "udp4500_mark_peers": sorted(udp4500_mark_peers),
            "esp_mark_peers": sorted(esp_mark_peers),
        },
        "maps": {
            "peer_mark_udp500": _sorted_map_items(peer_mark_udp500),
            "peer_mark_udp4500": _sorted_map_items(peer_mark_udp4500),
            "peer_mark_esp": _sorted_map_items(peer_mark_esp),
        },
        "deferred_translation_customers": sorted(
            deferred_translation_customers,
            key=lambda item: item["customer_name"],
        ),
        "deferred_bridge_customers": sorted(
            deferred_bridge_customers,
            key=lambda item: item["customer_name"],
        ),
    }


def _render_set_block(name: str, type_name: str, elements: List[str]) -> List[str]:
    if not elements:
        return []
    return [
        f"  set {name} {{",
        f"    type {type_name}",
        f"    elements = {{ {', '.join(elements)} }}",
        "  }",
    ]


def _render_map_block(name: str, type_name: str, elements: Dict[str, str]) -> List[str]:
    if not elements:
        return []
    rendered = ", ".join(f"{key} : {value}" for key, value in elements.items())
    return [
        f"  map {name} {{",
        f"    type {type_name}",
        f"    elements = {{ {rendered} }}",
        "  }",
    ]


def _nat_statement_target(statement: str, prefix: str) -> str:
    raw = str(statement or "").strip()
    if raw.startswith(prefix):
        raw = raw[len(prefix) :].strip()
    return raw


def _address_nat_map(elements: Dict[str, str], prefix: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for key, value in elements.items():
        target = _nat_statement_target(value, prefix)
        if ":" in target:
            continue
        result[key] = target
    return result


def _complex_nat_items(elements: Dict[str, str], prefix: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for key, value in elements.items():
        target = _nat_statement_target(value, prefix)
        if ":" in target:
            result[key] = target
    return result


def _concat_key_parts(key: str) -> List[str]:
    return [part.strip() for part in str(key).split(".")]


def _queue_statement(queue_num: Any, queue_bypass: Any) -> str:
    statement = f"queue num {int(queue_num)}"
    if bool(queue_bypass):
        statement += " bypass"
    return statement


def render_passthrough_nft_script(model: Dict[str, Any]) -> str:
    classification_table = model["table"]
    translation = model.get("translation") or {}
    bridge = model.get("bridge") or {}
    interfaces = model["interfaces"]
    sets = model["sets"]
    maps = model["maps"]
    public_if = interfaces["public_if"]
    render_mode = str(model.get("render_mode") or "nftables-batch-preview")
    classification_backend = str(model.get("classification_backend") or "nftables")
    translation_backend = str(model.get("translation_backend") or "nftables")
    bridge_backend = str(model.get("bridge_backend") or "nftables")

    if render_mode == "nftables-live-pass-through":
        header = [
            "# RPDB pass-through nftables apply script",
            "# This script is the repo-modeled live dataplane backend for pass-through customers.",
        ]
    else:
        header = [
            "# RPDB pass-through nftables review script",
            "# This file remains reviewable as a diff artifact for the pass-through dataplane model.",
        ]

    lines: List[str] = list(header)
    for note in model.get("notes") or []:
        lines.append(f"# {note}")

    if classification_backend == "nftables" or render_mode != "nftables-live-pass-through":
        lines.extend([f"table {classification_table['family']} {classification_table['name']} {{"])
        lines.extend(_render_set_block("public_destinations", "ipv4_addr", interfaces["public_destinations"]))
        lines.extend(_render_set_block("udp500_accept_peers", "ipv4_addr", sets["udp500_accept_peers"]))
        lines.extend(_render_set_block("udp4500_accept_peers", "ipv4_addr", sets["udp4500_accept_peers"]))
        lines.extend(_render_set_block("esp_accept_peers", "ipv4_addr", sets["esp_accept_peers"]))
        lines.extend(_render_set_block("udp500_mark_peers", "ipv4_addr", sets["udp500_mark_peers"]))
        lines.extend(_render_set_block("udp4500_mark_peers", "ipv4_addr", sets["udp4500_mark_peers"]))
        lines.extend(_render_set_block("esp_mark_peers", "ipv4_addr", sets["esp_mark_peers"]))
        bridge_sets = bridge.get("sets") or {}
        lines.extend(_render_set_block("force4500_in_pairs", "ipv4_addr . ipv4_addr", bridge_sets.get("force4500_in_pairs") or []))
        lines.extend(_render_set_block("force4500_out_pairs", "ipv4_addr . ipv4_addr", bridge_sets.get("force4500_out_pairs") or []))
        lines.extend(_render_set_block("natd_in_pairs", "ipv4_addr . ipv4_addr", bridge_sets.get("natd_in_pairs") or []))
        lines.extend(_render_set_block("natd_out_pairs", "ipv4_addr . ipv4_addr", bridge_sets.get("natd_out_pairs") or []))
        lines.extend(_render_map_block("peer_mark_udp500", "ipv4_addr : mark", maps["peer_mark_udp500"]))
        lines.extend(_render_map_block("peer_mark_udp4500", "ipv4_addr : mark", maps["peer_mark_udp4500"]))
        lines.extend(_render_map_block("peer_mark_esp", "ipv4_addr : mark", maps["peer_mark_esp"]))

        bridge_hooks = bridge.get("queue_hooks") or {}
        if bridge_backend == "nftables" and bridge.get("enabled"):
            lines.extend(
                [
                    "  chain prerouting_bridge {",
                    "    type filter hook prerouting priority -151; policy accept;",
                ]
            )
            if bridge_sets.get("force4500_in_pairs"):
                lines.append(
                    f'    iifname "{public_if}" udp dport 4500 ip saddr . ip daddr @force4500_in_pairs '
                    f'{_queue_statement((bridge_hooks.get("force4500_in") or {}).get("queue_num", 2101), (bridge_hooks.get("force4500_in") or {}).get("queue_bypass", True))}'
                )
            if bridge_sets.get("natd_in_pairs"):
                lines.append(
                    f'    iifname "{public_if}" udp dport 500 ip saddr . ip daddr @natd_in_pairs '
                    f'{_queue_statement((bridge_hooks.get("natd_in") or {}).get("queue_num", 2111), (bridge_hooks.get("natd_in") or {}).get("queue_bypass", True))}'
                )
            lines.append("  }")

            lines.extend(
                [
                    "  chain postrouting_bridge {",
                    "    type filter hook postrouting priority -151; policy accept;",
                ]
            )
            if bridge_sets.get("force4500_out_pairs"):
                lines.append(
                    f'    oifname "{public_if}" udp sport 500 ip saddr . ip daddr @force4500_out_pairs '
                    f'{_queue_statement((bridge_hooks.get("force4500_out") or {}).get("queue_num", 2102), (bridge_hooks.get("force4500_out") or {}).get("queue_bypass", True))}'
                )
            if bridge_sets.get("natd_out_pairs"):
                lines.append(
                    f'    oifname "{public_if}" udp sport 500 udp dport 500 ip saddr . ip daddr @natd_out_pairs '
                    f'{_queue_statement((bridge_hooks.get("natd_out") or {}).get("queue_num", 2112), (bridge_hooks.get("natd_out") or {}).get("queue_bypass", True))}'
                )
            lines.append("  }")

        lines.extend(
            [
                "  chain prerouting_mangle {",
                "    type filter hook prerouting priority mangle; policy accept;",
            ]
        )
        if sets["udp500_mark_peers"]:
            lines.append(
                f'    iifname "{public_if}" ip daddr @public_destinations udp dport 500 '
                "ip saddr @udp500_mark_peers meta mark set ip saddr map @peer_mark_udp500"
            )
        if sets["udp4500_mark_peers"]:
            lines.append(
                f'    iifname "{public_if}" ip daddr @public_destinations udp dport 4500 '
                "ip saddr @udp4500_mark_peers meta mark set ip saddr map @peer_mark_udp4500"
            )
        if sets["esp_mark_peers"]:
            lines.append(
                f'    iifname "{public_if}" ip daddr @public_destinations ip protocol esp '
                "ip saddr @esp_mark_peers meta mark set ip saddr map @peer_mark_esp"
            )
        lines.append("  }")

        lines.extend(
            [
                "  chain forward_filter {",
                "    type filter hook forward priority filter; policy accept;",
                "    ct state established,related accept",
            ]
        )
        if sets["udp500_accept_peers"]:
            lines.append(
                f'    iifname "{public_if}" ip daddr @public_destinations udp dport 500 '
                "ip saddr @udp500_accept_peers accept"
            )
        if sets["udp4500_accept_peers"]:
            lines.append(
                f'    iifname "{public_if}" ip daddr @public_destinations udp dport 4500 '
                "ip saddr @udp4500_accept_peers accept"
            )
        if sets["esp_accept_peers"]:
            lines.append(
                f'    iifname "{public_if}" ip daddr @public_destinations ip protocol esp '
                "ip saddr @esp_accept_peers accept"
            )
        if model.get("default_drop"):
            lines.append(f'    iifname "{public_if}" ip daddr @public_destinations udp dport 500 drop')
            lines.append(f'    iifname "{public_if}" ip daddr @public_destinations udp dport 4500 drop')
            lines.append(f'    iifname "{public_if}" ip daddr @public_destinations ip protocol esp drop')
        lines.append("  }")
        lines.append("}")

    if translation_backend == "nftables" or render_mode != "nftables-live-pass-through":
        translation_table = (translation.get("nat_table") or {})
        translation_maps = (translation.get("maps") or {})
        if translation_table:
            udp500_dnat_map = _address_nat_map(translation_maps.get("udp500_dnat") or {}, "dnat to ")
            udp4500_dnat_map = _address_nat_map(translation_maps.get("udp4500_dnat") or {}, "dnat to ")
            udp4500_force500_dnat_direct = _complex_nat_items(
                translation_maps.get("udp4500_force500_dnat") or {}, "dnat to "
            )
            esp_dnat_map = _address_nat_map(translation_maps.get("esp_dnat") or {}, "dnat to ")
            udp500_snat_map = _address_nat_map(translation_maps.get("udp500_snat") or {}, "snat to ")
            udp500_force4500_snat_direct = _complex_nat_items(
                translation_maps.get("udp500_force4500_snat") or {}, "snat to "
            )
            udp4500_snat_map = _address_nat_map(translation_maps.get("udp4500_snat") or {}, "snat to ")
            udp4500_force4500_snat_direct = _complex_nat_items(
                translation_maps.get("udp4500_force4500_snat") or {}, "snat to "
            )
            esp_snat_map = _address_nat_map(translation_maps.get("esp_snat") or {}, "snat to ")
            lines.append("")
            lines.extend([f"table {translation_table['family']} {translation_table['name']} {{"])
            lines.extend(_render_set_block("public_destinations", "ipv4_addr", translation.get("public_destinations") or []))
            lines.extend(_render_map_block("udp500_dnat", "ipv4_addr : ipv4_addr", udp500_dnat_map))
            lines.extend(_render_map_block("udp4500_dnat", "ipv4_addr : ipv4_addr", udp4500_dnat_map))
            lines.extend(_render_map_block("esp_dnat", "ipv4_addr : ipv4_addr", esp_dnat_map))
            lines.extend(_render_map_block("udp500_snat", "ipv4_addr . ipv4_addr : ipv4_addr", udp500_snat_map))
            lines.extend(_render_map_block("udp4500_snat", "ipv4_addr . ipv4_addr : ipv4_addr", udp4500_snat_map))
            lines.extend(_render_map_block("esp_snat", "ipv4_addr . ipv4_addr : ipv4_addr", esp_snat_map))

            lines.extend(
                [
                    "  chain prerouting_nat {",
                    "    type nat hook prerouting priority dstnat; policy accept;",
                ]
            )
            if udp500_dnat_map:
                lines.append(
                    f'    iifname "{public_if}" ip daddr @public_destinations udp dport 500 '
                    "dnat to ip saddr map @udp500_dnat"
                )
            if udp4500_dnat_map:
                lines.append(
                    f'    iifname "{public_if}" ip daddr @public_destinations udp dport 4500 '
                    "dnat to ip saddr map @udp4500_dnat"
                )
            for peer, target in udp4500_force500_dnat_direct.items():
                lines.append(f'    iifname "{public_if}" ip daddr @public_destinations udp dport 4500 ip saddr {peer} dnat to {target}')
            if esp_dnat_map:
                lines.append(
                    f'    iifname "{public_if}" ip daddr @public_destinations ip protocol esp '
                    "dnat to ip saddr map @esp_dnat"
                )
            lines.append("  }")

            lines.extend(
                [
                    "  chain postrouting_nat {",
                    "    type nat hook postrouting priority srcnat; policy accept;",
                ]
            )
            if udp500_snat_map:
                lines.append(f'    oifname "{public_if}" udp sport 500 snat to ip saddr . ip daddr map @udp500_snat')
            for key, target in udp500_force4500_snat_direct.items():
                parts = _concat_key_parts(key)
                if len(parts) == 2:
                    lines.append(f'    oifname "{public_if}" udp sport 500 ip saddr {parts[0]} ip daddr {parts[1]} snat to {target}')
            if udp4500_snat_map:
                lines.append(f'    oifname "{public_if}" udp sport 4500 snat to ip saddr . ip daddr map @udp4500_snat')
            for key, target in udp4500_force4500_snat_direct.items():
                parts = _concat_key_parts(key)
                if len(parts) == 2:
                    lines.append(f'    oifname "{public_if}" udp sport 4500 ip saddr {parts[0]} ip daddr {parts[1]} snat to {target}')
            if esp_snat_map:
                lines.append(f'    oifname "{public_if}" ip protocol esp snat to ip saddr . ip daddr map @esp_snat')
            lines.append("  }")
            lines.append("}")

    if model.get("deferred_translation_customers"):
        lines.append("")
        lines.append("# Translation customers not rendered into the shared nftables model")
        for entry in model["deferred_translation_customers"]:
            lines.append(
                "# "
                f"{entry['customer_name']}: peer={entry['peer_ip']} "
                f"udp500={entry['udp500']} udp4500={entry['udp4500']} esp50={entry['esp50']} "
                f"force4500to500={entry['force_rewrite_4500_to_500']}"
            )

    if model.get("deferred_bridge_customers"):
        lines.append("")
        lines.append("# Bridge customers not rendered into the shared nftables model")
        for entry in model["deferred_bridge_customers"]:
            lines.append(
                "# "
                f"{entry['customer_name']}: peer={entry['peer_ip']} "
                f"force4500to500={entry['force_rewrite_4500_to_500']} "
                f"natd_dpi_rewrite={entry['natd_dpi_rewrite']}"
            )

    return "\n".join(lines) + "\n"


def _artifact_paths(global_cfg: Dict[str, Any]) -> Dict[str, Path]:
    settings = passthrough_nft_settings(global_cfg)
    root = settings["state_root"]
    return {
        "root": root,
        "script_path": root / "pass-through-state.nft",
        "model_path": root / "pass-through-state-model.json",
        "bridge_manifest_path": root / "pass-through-bridge-manifest.json",
    }


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)


def apply_passthrough_nft_state(
    modules: Iterable[Dict[str, Any]],
    global_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    model = build_passthrough_nft_model(
        modules,
        global_cfg,
        render_mode="nftables-live-pass-through",
    )
    script = render_passthrough_nft_script(model)
    paths = _artifact_paths(global_cfg)
    _write_text(paths["script_path"], script)
    _write_json(paths["model_path"], model)
    _write_json(paths["bridge_manifest_path"], model.get("bridge") or {})
    sh(["nft", "delete", "table", "inet", model["table"]["name"]], check=False)
    nat_table_name = str(((model.get("translation") or {}).get("nat_table") or {}).get("name") or "")
    if nat_table_name:
        sh(["nft", "delete", "table", "ip", nat_table_name], check=False)
    must(["nft", "-f", str(paths["script_path"])])
    return {
        "customer_count": model["customer_count"],
        "script_path": str(paths["script_path"]),
        "model_path": str(paths["model_path"]),
        "bridge_manifest_path": str(paths["bridge_manifest_path"]),
        "table_name": model["table"]["name"],
        "nat_table_name": str(((model.get("translation") or {}).get("nat_table") or {}).get("name") or ""),
        "render_mode": model["render_mode"],
        "classification_backend": model["classification_backend"],
        "translation_backend": model["translation_backend"],
        "bridge_backend": model["bridge_backend"],
    }


def apply_passthrough_nft_classification(
    modules: Iterable[Dict[str, Any]],
    global_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    return apply_passthrough_nft_state(modules, global_cfg)


def flush_passthrough_nft_classification(global_cfg: Dict[str, Any]) -> Dict[str, Any]:
    settings = passthrough_nft_settings(global_cfg)
    paths = _artifact_paths(global_cfg)
    sh(["nft", "delete", "table", "inet", settings["table_name"]], check=False)
    sh(["nft", "delete", "table", "ip", settings["nat_table_name"]], check=False)
    for path in (paths["script_path"], paths["model_path"], paths["bridge_manifest_path"]):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return {
        "table_name": settings["table_name"],
        "nat_table_name": settings["nat_table_name"],
        "bridge_manifest_path": str(paths["bridge_manifest_path"]),
        "artifact_root": str(paths["root"]),
    }
