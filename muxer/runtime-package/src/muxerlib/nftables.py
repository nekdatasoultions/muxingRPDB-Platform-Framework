#!/usr/bin/env python3
"""Render-first nftables batching helpers for pass-through customers."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .core import norm_int
from .customers import customer_protocol_flags


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


def build_passthrough_nft_model(modules: Iterable[Dict[str, Any]], global_cfg: Dict[str, Any]) -> Dict[str, Any]:
    interfaces = global_cfg.get("interfaces", {}) or {}
    iptables_cfg = global_cfg.get("iptables", {}) or {}
    public_ip = str(global_cfg["public_ip"]).strip()
    public_priv_ip = str(interfaces.get("public_private_ip") or public_ip).strip()
    pub_if = str(interfaces.get("public_if") or "").strip()
    default_drop = bool(iptables_cfg.get("default_drop_ipsec_to_public_ip", True))
    base_mark = norm_int((global_cfg.get("allocation") or {}).get("base_mark", "0x2000"))

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
    legacy_translation_customers: List[Dict[str, Any]] = []

    customer_count = 0
    for module in modules:
        customer_count += 1
        peer = _peer_host(module)
        mark_hex = _customer_mark(module, base_mark)
        udp500, udp4500, esp50, force_4500_to_500 = customer_protocol_flags(module)

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

        legacy_translation_customers.append(
            {
                "customer_name": str(module["name"]),
                "peer_ip": peer,
                "udp500": udp500,
                "udp4500": udp4500,
                "esp50": esp50,
                "force_rewrite_4500_to_500": force_4500_to_500,
            }
        )

    return {
        "schema_version": 1,
        "scope": "pass-through-only",
        "render_mode": "nftables-batch-preview",
        "customer_count": customer_count,
        "notes": [
            "This first nftables layer batches peer classification and fwmark assignment.",
            "DNAT/SNAT rewrite and NFQUEUE bridge stages remain on the legacy per-customer path.",
            "Termination-mode customers are intentionally out of scope for this renderer.",
        ],
        "table": {
            "family": "inet",
            "name": "muxer_passthrough",
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
        "legacy_translation_customers": sorted(
            legacy_translation_customers,
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


def render_passthrough_nft_script(model: Dict[str, Any]) -> str:
    table = model["table"]
    interfaces = model["interfaces"]
    sets = model["sets"]
    maps = model["maps"]
    public_if = interfaces["public_if"]

    lines: List[str] = [
        "# RPDB pass-through nftables batch preview",
        "# This file is render-only today; it is not yet the live apply path.",
    ]
    for note in model.get("notes") or []:
        lines.append(f"# {note}")
    lines.extend(
        [
            f"table {table['family']} {table['name']} {{",
        ]
    )

    lines.extend(_render_set_block("public_destinations", "ipv4_addr", interfaces["public_destinations"]))
    lines.extend(_render_set_block("udp500_accept_peers", "ipv4_addr", sets["udp500_accept_peers"]))
    lines.extend(_render_set_block("udp4500_accept_peers", "ipv4_addr", sets["udp4500_accept_peers"]))
    lines.extend(_render_set_block("esp_accept_peers", "ipv4_addr", sets["esp_accept_peers"]))
    lines.extend(_render_set_block("udp500_mark_peers", "ipv4_addr", sets["udp500_mark_peers"]))
    lines.extend(_render_set_block("udp4500_mark_peers", "ipv4_addr", sets["udp4500_mark_peers"]))
    lines.extend(_render_set_block("esp_mark_peers", "ipv4_addr", sets["esp_mark_peers"]))
    lines.extend(_render_map_block("peer_mark_udp500", "ipv4_addr : mark", maps["peer_mark_udp500"]))
    lines.extend(_render_map_block("peer_mark_udp4500", "ipv4_addr : mark", maps["peer_mark_udp4500"]))
    lines.extend(_render_map_block("peer_mark_esp", "ipv4_addr : mark", maps["peer_mark_esp"]))

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

    if model.get("legacy_translation_customers"):
        lines.append("")
        lines.append("# Remaining legacy per-customer translation customers")
        for entry in model["legacy_translation_customers"]:
            lines.append(
                "# "
                f"{entry['customer_name']}: peer={entry['peer_ip']} "
                f"udp500={entry['udp500']} udp4500={entry['udp4500']} esp50={entry['esp50']} "
                f"force4500to500={entry['force_rewrite_4500_to_500']}"
            )

    return "\n".join(lines) + "\n"
