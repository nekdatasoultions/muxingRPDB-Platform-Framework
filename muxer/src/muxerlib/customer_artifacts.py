"""Render customer-scoped muxer and head-end artifacts."""

from __future__ import annotations

# These helpers turn the merged customer module into small, reviewable intent
# documents. They are the concrete handoff outputs the deployment path can
# package, stage, and validate before any live apply.
import ipaddress
import re
from typing import Any, Dict, Iterable, List, Tuple


def _yes_no(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return "yes" if bool(value) else "no"


def _placeholder(name: str) -> str:
    return f"${{{name}}}"


def _render_ipsec_id(value: str, fallback_placeholder: str) -> str:
    return value or _placeholder(fallback_placeholder)


def _render_swanctl_version(ipsec: Dict[str, Any]) -> str:
    version = str(ipsec.get("ike_version") or "").strip().lower()
    if version in {"ikev1", "v1"}:
        return "1"
    if version == "auto":
        return "0"
    return "2"


def _render_ike_proposals(ipsec: Dict[str, Any]) -> str:
    policies = [str(value) for value in (ipsec.get("ike_policies") or []) if str(value).strip()]
    if policies:
        return ",".join(policies)
    return str(ipsec.get("ike") or "").strip()


def _render_esp_proposals(ipsec: Dict[str, Any]) -> str:
    policies = [str(value) for value in (ipsec.get("esp_policies") or []) if str(value).strip()]
    if policies:
        return ",".join(policies)
    return str(ipsec.get("esp") or "").strip()


def _render_replay_window(ipsec: Dict[str, Any]) -> str | None:
    if ipsec.get("replay_protection") is None:
        return None
    return "32" if bool(ipsec.get("replay_protection")) else "0"


def _render_copy_df(ipsec: Dict[str, Any]) -> str | None:
    if ipsec.get("clear_df_bit") is None:
        return None
    return "no" if bool(ipsec.get("clear_df_bit")) else "yes"


def _append_unique(values: List[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in values:
        values.append(text)


def _render_headend_egress_sources(backend: Dict[str, Any], ipsec: Dict[str, Any]) -> List[str]:
    sources: List[str] = []
    for value in backend.get("egress_source_ips") or []:
        _append_unique(sources, value)
    _append_unique(sources, backend.get("underlay_ip") or _placeholder("BACKEND_UNDERLAY_IP"))
    left_public = str(ipsec.get("left_public") or "").strip()
    if left_public and left_public != "%defaultroute":
        _append_unique(sources, left_public)
    _append_unique(sources, _placeholder("HEADEND_PUBLIC_IP"))
    return sources


def _enabled_snat_protocols(protocols: Dict[str, Any]) -> List[Dict[str, str]]:
    enabled: List[Dict[str, str]] = []
    if bool(protocols.get("udp500")):
        enabled.append({"name": "udp500", "protocol": "udp", "sport": "500"})
    if bool(protocols.get("udp4500")):
        enabled.append({"name": "udp4500", "protocol": "udp", "sport": "4500"})
    if bool(protocols.get("esp50")):
        enabled.append({"name": "esp50", "protocol": "50", "sport": ""})
    return enabled


def _build_snat_coverage(
    *,
    peer_ip: str,
    backend: Dict[str, Any],
    protocols: Dict[str, Any],
    ipsec: Dict[str, Any],
) -> Dict[str, Any]:
    egress_sources = _render_headend_egress_sources(backend, ipsec)
    protocol_specs = _enabled_snat_protocols(protocols)
    rules: List[Dict[str, str]] = []
    peer_cidr = f"{peer_ip}/32" if peer_ip and "/" not in peer_ip else peer_ip
    for source_ip in egress_sources:
        for protocol_spec in protocol_specs:
            parts = [
                "-A",
                "MUXER_NAT_POST",
                "-o",
                _placeholder("MUXER_PUBLIC_IFACE"),
                "-s",
                source_ip,
                "-d",
                peer_cidr,
                "-p",
                protocol_spec["protocol"],
            ]
            if protocol_spec["sport"]:
                parts.extend(["--sport", protocol_spec["sport"]])
            parts.extend(["-j", "SNAT", "--to-source", _placeholder("MUXER_PUBLIC_PRIVATE_IP")])
            rules.append(
                {
                    "source_ip": source_ip,
                    "protocol": protocol_spec["name"],
                    "iptables": "iptables -t nat " + " ".join(parts),
                }
            )
    return {
        "required": True,
        "egress_sources": egress_sources,
        "protocols": [spec["name"] for spec in protocol_specs],
        "rules": rules,
    }


def _cidr_to_host(cidr_text: str) -> str:
    network = ipaddress.ip_network(str(cidr_text), strict=False)
    return str(network.network_address)


def _render_ipsec_intent(
    customer: Dict[str, Any],
    peer: Dict[str, Any],
    selectors: Dict[str, Any],
    protocols: Dict[str, Any],
    ipsec: Dict[str, Any],
) -> Dict[str, Any]:
    ike_proposals = _render_ike_proposals(ipsec)
    esp_proposals = _render_esp_proposals(ipsec)
    return {
        "customer_name": customer.get("name"),
        "peer_public_ip": peer.get("public_ip"),
        "remote_id": ipsec.get("remote_id") or peer.get("remote_id"),
        "local_id": ipsec.get("local_id") or _placeholder("HEADEND_ID"),
        "ike_version": str(ipsec.get("ike_version") or "ikev2"),
        "swanctl_version": _render_swanctl_version(ipsec),
        "ike": ipsec.get("ike"),
        "esp": ipsec.get("esp"),
        "ike_policies": ipsec.get("ike_policies") or [],
        "esp_policies": ipsec.get("esp_policies") or [],
        "rendered_ike_proposals": ike_proposals or None,
        "rendered_esp_proposals": esp_proposals or None,
        "auto": ipsec.get("auto"),
        "dpddelay": ipsec.get("dpddelay"),
        "dpdtimeout": ipsec.get("dpdtimeout"),
        "dpdaction": ipsec.get("dpdaction"),
        "ikelifetime": ipsec.get("ikelifetime"),
        "lifetime": ipsec.get("lifetime"),
        "replay_protection": ipsec.get("replay_protection"),
        "rendered_replay_window": _render_replay_window(ipsec),
        "pfs_required": ipsec.get("pfs_required"),
        "pfs_groups": ipsec.get("pfs_groups") or [],
        "forceencaps": ipsec.get("forceencaps"),
        "mobike": ipsec.get("mobike"),
        "fragmentation": ipsec.get("fragmentation"),
        "clear_df_bit": ipsec.get("clear_df_bit"),
        "rendered_copy_df": _render_copy_df(ipsec),
        "mark": ipsec.get("mark"),
        "vti_interface": ipsec.get("vti_interface"),
        "vti_routing": ipsec.get("vti_routing"),
        "vti_shared": ipsec.get("vti_shared"),
        "bidirectional_secret": ipsec.get("bidirectional_secret"),
        "encapsulation_model": "nat-t" if protocols.get("udp4500") else "strict-non-nat",
        "selectors": {
            "local_subnets": selectors.get("local_subnets") or [],
            "remote_subnets": selectors.get("remote_subnets") or [],
        },
    }


def _append_if(lines: List[str], key: str, value: str | None) -> None:
    if value not in (None, ""):
        lines.append(f"    {key} = {value}")


def _append_child_if(lines: List[str], key: str, value: str | None) -> None:
    if value not in (None, ""):
        lines.append(f"        {key} = {value}")


def _render_swanctl_connection(
    customer: Dict[str, Any],
    peer: Dict[str, Any],
    selectors: Dict[str, Any],
    ipsec: Dict[str, Any],
) -> str:
    customer_name = str(customer.get("name") or "")
    remote_id = str(ipsec.get("remote_id") or peer.get("remote_id") or peer.get("public_ip") or "")
    local_id = str(ipsec.get("local_id") or "")
    ike_proposals = _render_ike_proposals(ipsec)
    esp_proposals = _render_esp_proposals(ipsec)
    lines: List[str] = [
        "connections {",
        f"  {customer_name} {{",
        f"    version = {_render_swanctl_version(ipsec)}",
        f"    local_addrs = {_placeholder('HEADEND_PUBLIC_IP')}",
        f"    remote_addrs = {peer.get('public_ip')}",
    ]
    _append_if(lines, "proposals", ike_proposals or None)
    _append_if(lines, "encap", _yes_no(ipsec.get("forceencaps")))
    _append_if(lines, "mobike", _yes_no(ipsec.get("mobike")))
    _append_if(lines, "fragmentation", _yes_no(ipsec.get("fragmentation")))
    _append_if(lines, "dpd_delay", str(ipsec.get("dpddelay") or ""))
    _append_if(lines, "dpd_timeout", str(ipsec.get("dpdtimeout") or ""))
    _append_if(lines, "rekey_time", str(ipsec.get("ikelifetime") or ""))
    lines.extend(
        [
            "    local {",
            "      auth = psk",
            f"      id = {_render_ipsec_id(local_id, 'HEADEND_ID')}",
            "    }",
            "    remote {",
            "      auth = psk",
            f"      id = {remote_id}",
            "    }",
            "    children {",
            f"      {customer_name}-child {{",
            f"        local_ts = {','.join(selectors.get('local_subnets') or [])}",
            f"        remote_ts = {','.join(selectors.get('remote_subnets') or [])}",
            "        mode = tunnel",
            f"        start_action = {ipsec.get('auto') or 'start'}",
        ]
    )
    _append_child_if(lines, "esp_proposals", esp_proposals or None)
    _append_child_if(lines, "dpd_action", str(ipsec.get("dpdaction") or ""))
    _append_child_if(lines, "life_time", str(ipsec.get("lifetime") or ""))
    _append_child_if(lines, "replay_window", _render_replay_window(ipsec))
    _append_child_if(lines, "copy_df", _render_copy_df(ipsec))
    if ipsec.get("mark"):
        _append_child_if(lines, "mark_in", str(ipsec.get("mark")))
        _append_child_if(lines, "mark_out", str(ipsec.get("mark")))
    if ipsec.get("vti_interface"):
        lines.append(f"        # requested_vti_interface = {ipsec.get('vti_interface')}")
    if ipsec.get("pfs_groups"):
        lines.append(f"        # requested_pfs_groups = {','.join(ipsec.get('pfs_groups') or [])}")
    if ipsec.get("pfs_required") is not None:
        lines.append(f"        # requested_pfs_required = {_yes_no(ipsec.get('pfs_required'))}")
    lines.extend(
        [
            "      }",
            "    }",
            "  }",
            "}",
            "",
            "secrets {",
            f"  {customer_name}-psk {{",
            f"    id-1 = {_render_ipsec_id(local_id, 'HEADEND_ID')}",
            f"    id-2 = {remote_id}",
            f"    secret = {_placeholder('PSK_FROM_SECRET_REF')}",
            "  }",
            "}",
        ]
    )
    return "\n".join(lines) + "\n"


def _iter_core_subnets(post_ipsec_nat: Dict[str, Any]) -> Iterable[str | None]:
    core_subnets = [str(value) for value in (post_ipsec_nat.get("core_subnets") or []) if str(value).strip()]
    return core_subnets or [None]


def _effective_nat_interface(post_ipsec_nat: Dict[str, Any]) -> str:
    return str(post_ipsec_nat.get("interface") or _placeholder("HEADEND_CLEAR_IFACE"))


def _nft_name(value: str, *, prefix: str = "rpdb") -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", str(value).lower()).strip("_")
    normalized = normalized[:48] or "customer"
    return f"{prefix}_{normalized}"


def _ip_networks(values: Iterable[Any]) -> List[ipaddress.IPv4Network]:
    return [ipaddress.ip_network(str(value), strict=False) for value in values or []]


def _ip_hosts(network: ipaddress.IPv4Network) -> List[ipaddress.IPv4Address]:
    return [ipaddress.ip_address(value) for value in network]


def _nft_set_values(values: Iterable[Any]) -> List[str]:
    return [str(ipaddress.ip_network(str(value), strict=False)) for value in values or [] if str(value).strip()]


def _nft_host(value: Any) -> str:
    return str(ipaddress.ip_interface(str(value)).ip)


def _nft_map_entries(entries: List[Tuple[str, str]]) -> List[str]:
    return [f"{source} : {target}" for source, target in entries]


def _nft_inline_elements(values: Iterable[str]) -> str:
    value_list = [str(value) for value in values if str(value).strip()]
    if not value_list:
        return "{ }"
    return "{ " + ", ".join(value_list) + " }"


def _build_nft_host_mappings(post_ipsec_nat: Dict[str, Any]) -> tuple[List[Tuple[str, str]], List[str]]:
    strategy = str(post_ipsec_nat.get("mapping_strategy") or "").strip()
    mode = str(post_ipsec_nat.get("mode") or "").strip()
    warnings: List[str] = []
    mappings: List[Tuple[str, str]] = []

    if strategy == "explicit_host_map" or mode == "explicit_map":
        for host_mapping in post_ipsec_nat.get("host_mappings") or []:
            translated_ip = _nft_host(host_mapping["translated_ip"])
            real_ip = _nft_host(host_mapping["real_ip"])
            mappings.append((translated_ip, real_ip))
        return mappings, warnings

    if strategy == "one_to_one" or mode == "netmap":
        real_networks = _ip_networks(post_ipsec_nat.get("real_subnets") or [])
        translated_networks = _ip_networks(post_ipsec_nat.get("translated_subnets") or [])
        for real_network, translated_network in zip(real_networks, translated_networks):
            real_hosts = _ip_hosts(real_network)
            translated_hosts = _ip_hosts(translated_network)
            pair_count = min(len(real_hosts), len(translated_hosts))
            if len(real_hosts) != len(translated_hosts):
                warnings.append(
                    "netmap subnet sizes differ; generated nftables maps use the first "
                    f"{pair_count} address pair(s) from {translated_network} to {real_network}"
                )
            mappings.extend((str(translated_hosts[index]), str(real_hosts[index])) for index in range(pair_count))
        return mappings, warnings

    translated_source_ip = str(post_ipsec_nat.get("translated_source_ip") or "").strip()
    if translated_source_ip:
        translated_ip = _nft_host(translated_source_ip)
        for real_network in _ip_networks(post_ipsec_nat.get("real_subnets") or []):
            for real_ip in _ip_hosts(real_network):
                mappings.append((translated_ip, str(real_ip)))
    return mappings, warnings


def _render_post_ipsec_nat_nftables(customer_name: str, post_ipsec_nat: Dict[str, Any]) -> Dict[str, Any]:
    enabled = bool(post_ipsec_nat.get("enabled"))
    safe_customer = _nft_name(customer_name, prefix="cust")
    table_name = _nft_name(customer_name, prefix="rpdb_hn")
    dnat_map = f"{safe_customer}_dnat_v4"
    snat_map = f"{safe_customer}_snat_v4"
    translated_set = f"{safe_customer}_translated_v4"
    real_set = f"{safe_customer}_real_v4"
    core_set = f"{safe_customer}_core_v4"
    output_mark = str(post_ipsec_nat.get("output_mark") or "").strip()
    tcp_mss_clamp = post_ipsec_nat.get("tcp_mss_clamp")

    host_mappings, warnings = _build_nft_host_mappings(post_ipsec_nat)
    dnat_entries = _nft_map_entries(host_mappings)
    snat_entries = _nft_map_entries([(real_ip, translated_ip) for translated_ip, real_ip in host_mappings])
    translated_values = sorted({translated_ip for translated_ip, _real_ip in host_mappings})
    real_values = sorted({real_ip for _translated_ip, real_ip in host_mappings})
    core_values = _nft_set_values(post_ipsec_nat.get("core_subnets") or [])
    if not core_values:
        core_values = ["0.0.0.0/0"]

    state = {
        "schema_version": 1,
        "backend": "nftables",
        "table_family": "ip",
        "table_name": table_name,
        "enabled": enabled,
        "mode": post_ipsec_nat.get("mode"),
        "mapping_strategy": post_ipsec_nat.get("mapping_strategy"),
        "customer_name": customer_name,
        "chains": {
            "prerouting": "prerouting",
            "postrouting": "postrouting",
            "mangle_prerouting": "mangle_prerouting",
            "mangle_forward": "mangle_forward",
        },
        "sets": {
            "core": core_set,
            "real": real_set,
            "translated": translated_set,
        },
        "maps": {
            "dnat": dnat_map,
            "snat": snat_map,
        },
        "host_mapping_count": len(host_mappings),
        "warnings": warnings,
        "activation_units": {
            "apply": 2 if enabled else 0,
            "rollback": 1 if enabled else 0,
        },
        "prohibited_fallbacks": [
            "iptables-restore",
            "MUXER3",
            "legacy_headend_iptables_activation",
        ],
    }

    if not enabled:
        disabled_text = "# post-IPsec NAT disabled; no nftables state required\n"
        return {
            "state": state,
            "manifest": {
                **state,
                "artifact_files": [],
                "apply_command_count": 0,
                "rollback_command_count": 0,
            },
            "apply": disabled_text,
            "remove": disabled_text,
        }

    lines = [
        f"# RPDB customer-scoped post-IPsec NAT for {customer_name}",
        "# Backend: nftables only.",
        f"table ip {table_name} {{",
        f"  set {core_set} {{",
        "    type ipv4_addr",
        "    flags interval",
        f"    elements = { _nft_inline_elements(core_values) }",
        "  }",
        f"  set {translated_set} {{",
        "    type ipv4_addr",
        f"    elements = { _nft_inline_elements(translated_values) }",
        "  }",
        f"  set {real_set} {{",
        "    type ipv4_addr",
        f"    elements = { _nft_inline_elements(real_values) }",
        "  }",
        f"  map {dnat_map} {{",
        "    type ipv4_addr : ipv4_addr",
        f"    elements = { _nft_inline_elements(dnat_entries) }",
        "  }",
        f"  map {snat_map} {{",
        "    type ipv4_addr : ipv4_addr",
        f"    elements = { _nft_inline_elements(snat_entries) }",
        "  }",
        "  chain prerouting {",
        "    type nat hook prerouting priority dstnat; policy accept;",
        f"    ip saddr @{core_set} ip daddr @{translated_set} dnat to ip daddr map @{dnat_map}",
        "  }",
        "  chain postrouting {",
        "    type nat hook postrouting priority srcnat; policy accept;",
        f"    ip saddr @{real_set} ip daddr @{core_set} snat to ip saddr map @{snat_map}",
        "  }",
    ]
    if output_mark:
        lines.extend(
            [
                "  chain mangle_prerouting {",
                "    type filter hook prerouting priority mangle; policy accept;",
                f"    ip saddr @{core_set} ip daddr @{translated_set} meta mark set {output_mark}",
                "  }",
            ]
        )
    if tcp_mss_clamp not in {None, ""}:
        lines.extend(
            [
                "  chain mangle_forward {",
                "    type filter hook forward priority mangle; policy accept;",
                f"    ip saddr @{core_set} ip daddr @{real_set} tcp flags syn / syn,rst tcp option maxseg size set {int(tcp_mss_clamp)}",
                "  }",
            ]
        )
    lines.extend(["}", ""])

    remove_lines = [
        f"# Remove RPDB customer-scoped post-IPsec NAT for {customer_name}",
        f"delete table ip {table_name}",
        "",
    ]
    manifest = {
        **state,
        "artifact_files": [
            "post-ipsec-nat/nftables.apply.nft",
            "post-ipsec-nat/nftables.remove.nft",
            "post-ipsec-nat/nftables-state.json",
        ],
        "apply_command_count": state["activation_units"]["apply"],
        "rollback_command_count": state["activation_units"]["rollback"],
    }
    return {
        "state": state,
        "manifest": manifest,
        "apply": "\n".join(lines),
        "remove": "\n".join(remove_lines),
    }


def _render_post_ipsec_nat_intent(customer_name: str, post_ipsec_nat: Dict[str, Any]) -> Dict[str, Any]:
    nftables = _render_post_ipsec_nat_nftables(customer_name, post_ipsec_nat)
    manifest = nftables["manifest"]
    command_model = "disabled"
    if bool(post_ipsec_nat.get("enabled")):
        if str(post_ipsec_nat.get("mapping_strategy") or "") == "one_to_one":
            command_model = "nftables_netmap_one_to_one"
        elif str(post_ipsec_nat.get("mode") or "") == "netmap":
            command_model = "nftables_legacy_netmap"
        elif str(post_ipsec_nat.get("mapping_strategy") or "") == "explicit_host_map" or str(post_ipsec_nat.get("mode") or "") == "explicit_map":
            command_model = "nftables_explicit_host_map"
        else:
            command_model = "nftables_generic_post_ipsec_nat"

    return {
        "enabled": bool(post_ipsec_nat.get("enabled")),
        "activation_backend": "nftables",
        "mode": post_ipsec_nat.get("mode"),
        "mapping_strategy": post_ipsec_nat.get("mapping_strategy"),
        "translated_subnets": post_ipsec_nat.get("translated_subnets") or [],
        "translated_source_ip": post_ipsec_nat.get("translated_source_ip"),
        "real_subnets": post_ipsec_nat.get("real_subnets") or [],
        "host_mappings": post_ipsec_nat.get("host_mappings") or [],
        "core_subnets": post_ipsec_nat.get("core_subnets") or [],
        "interface": _effective_nat_interface(post_ipsec_nat),
        "output_mark": post_ipsec_nat.get("output_mark"),
        "tcp_mss_clamp": post_ipsec_nat.get("tcp_mss_clamp"),
        "route_via": post_ipsec_nat.get("route_via"),
        "route_dev": post_ipsec_nat.get("route_dev"),
        "rendered_command_model": command_model,
        "rendered_command_count": int(manifest.get("apply_command_count") or 0),
        "activation_manifest": {
            "backend": manifest.get("backend"),
            "table_name": manifest.get("table_name"),
            "apply_command_count": manifest.get("apply_command_count"),
            "rollback_command_count": manifest.get("rollback_command_count"),
            "host_mapping_count": manifest.get("host_mapping_count"),
            "prohibited_fallbacks": manifest.get("prohibited_fallbacks"),
        },
    }


def build_muxer_artifacts(module: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    customer = module.get("customer") or {}
    peer = module.get("peer") or {}
    transport = module.get("transport") or {}
    selectors = module.get("selectors") or {}
    protocols = module.get("protocols") or {}
    natd_rewrite = module.get("natd_rewrite") or {}
    dynamic_provisioning = module.get("dynamic_provisioning") or {}
    backend = module.get("backend") or {}
    ipsec = module.get("ipsec") or {}
    post_ipsec_nat = module.get("post_ipsec_nat") or {}
    snat_coverage = _build_snat_coverage(
        peer_ip=str(peer.get("public_ip") or ""),
        backend=backend,
        protocols=protocols,
        ipsec=ipsec,
    )
    snat_lines = [
        "# Customer-scoped muxer firewall snippet",
        f"# peer: {peer.get('public_ip')}",
        f"# fwmark: {transport.get('mark')}",
        f"# udp500={protocols.get('udp500')} udp4500={protocols.get('udp4500')} esp50={protocols.get('esp50')}",
        "# head-end egress SNAT coverage",
    ]
    snat_lines.extend(rule["iptables"] for rule in snat_coverage["rules"])

    return {
        "customer/customer-summary.json": {
            "customer_name": customer.get("name"),
            "customer_id": customer.get("id"),
            "customer_class": customer.get("customer_class"),
            "peer_ip": peer.get("public_ip"),
            "backend_cluster": backend.get("cluster"),
            "backend_assignment": backend.get("assignment"),
            "backend_role": backend.get("role"),
            "backend_underlay_ip": backend.get("underlay_ip"),
            "local_subnets": selectors.get("local_subnets") or [],
            "remote_subnets": selectors.get("remote_subnets") or [],
        },
        "routing/rpdb-routing.json": {
            "fwmark": transport.get("mark"),
            "route_table": transport.get("table"),
            "rpdb_priority": transport.get("rpdb_priority"),
            "lookup_selector": {
                "type": "fwmark",
                "value": transport.get("mark"),
            },
            "lookup_target": {
                "type": "routing-table",
                "value": transport.get("table"),
            },
            "ddb_projection": {
                "customer_name": item.get("customer_name"),
                "peer_ip": item.get("peer_ip"),
                "fwmark": item.get("fwmark"),
                "route_table": item.get("route_table"),
                "rpdb_priority": item.get("rpdb_priority"),
            },
        },
        "routing/ip-rule.command.txt": "\n".join(
            [
                "# Customer-scoped RPDB rule for the muxer",
                f"ip rule add pref {transport.get('rpdb_priority')} fwmark {transport.get('mark')} lookup {transport.get('table')}",
            ]
        )
        + "\n",
        "routing/ip-route-default.command.txt": "\n".join(
            [
                "# Per-customer table default route on the muxer",
                f"ip route replace table {transport.get('table')} default via ${'{BACKEND_UNDERLAY_IP}'} dev ${'{MUXER_UNDERLAY_IFACE}'}",
            ]
        )
        + "\n",
        "tunnel/tunnel-intent.json": {
            "interface": transport.get("interface"),
            "tunnel_type": transport.get("tunnel_type"),
            "tunnel_key": transport.get("tunnel_key"),
            "tunnel_ttl": transport.get("tunnel_ttl"),
            "overlay": transport.get("overlay") or {},
            "peer_public_ip": peer.get("public_ip"),
            "backend_cluster": backend.get("cluster"),
            "backend_assignment": backend.get("assignment"),
            "backend_role": backend.get("role"),
            "backend_underlay_ip": backend.get("underlay_ip"),
        },
        "tunnel/ip-link.command.txt": "\n".join(
            [
                "# Customer-scoped muxer tunnel create",
                f"ip link add {transport.get('interface')} type {transport.get('tunnel_type')} "
                f"local ${'{MUXER_TRANSPORT_IP}'} remote ${'{BACKEND_UNDERLAY_IP}'} "
                f"ttl {transport.get('tunnel_ttl')} key {transport.get('tunnel_key')}",
                f"ip addr replace {((transport.get('overlay') or {}).get('mux_ip') or '')} dev {transport.get('interface')}",
                f"ip link set {transport.get('interface')} up",
            ]
        )
        + "\n",
        "firewall/firewall-intent.json": {
            "protocols": {
                "udp500": protocols.get("udp500"),
                "udp4500": protocols.get("udp4500"),
                "esp50": protocols.get("esp50"),
                "force_rewrite_4500_to_500": protocols.get("force_rewrite_4500_to_500"),
            },
            "natd_rewrite": natd_rewrite,
            "dynamic_provisioning": dynamic_provisioning,
            "post_ipsec_nat_enabled": bool(post_ipsec_nat.get("enabled")),
            "post_ipsec_nat_mapping_strategy": post_ipsec_nat.get("mapping_strategy"),
            "headend_egress_sources": snat_coverage["egress_sources"],
            "snat_coverage": snat_coverage,
        },
        "firewall/iptables-snippet.txt": "\n".join(snat_lines) + "\n",
    }


def build_headend_artifacts(module: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    customer = module.get("customer") or {}
    peer = module.get("peer") or {}
    selectors = module.get("selectors") or {}
    transport = module.get("transport") or {}
    backend = module.get("backend") or {}
    protocols = module.get("protocols") or {}
    ipsec = module.get("ipsec") or {}
    post_ipsec_nat = module.get("post_ipsec_nat") or {}
    customer_name = str(customer.get("name") or "")
    post_ipsec_nftables = _render_post_ipsec_nat_nftables(customer_name, post_ipsec_nat)

    return {
        "ipsec/ipsec-intent.json": _render_ipsec_intent(customer, peer, selectors, protocols, ipsec),
        "ipsec/swanctl-connection.conf": _render_swanctl_connection(customer, peer, selectors, ipsec),
        "routing/routing-intent.json": {
            "backend_cluster": backend.get("cluster"),
            "backend_assignment": backend.get("assignment"),
            "backend_role": backend.get("role"),
            "backend_underlay_ip": backend.get("underlay_ip"),
            "selectors": {
                "local_subnets": selectors.get("local_subnets") or [],
                "remote_subnets": selectors.get("remote_subnets") or [],
            },
            "transport_binding": {
                "fwmark": transport.get("mark"),
                "route_table": transport.get("table"),
                "interface": transport.get("interface"),
            },
            "vti_binding": {
                "mark": ipsec.get("mark"),
                "vti_interface": ipsec.get("vti_interface"),
                "vti_routing": ipsec.get("vti_routing"),
                "vti_shared": ipsec.get("vti_shared"),
            },
        },
        "routing/ip-route.commands.txt": "\n".join(
            [
                "# Customer-scoped head-end routes",
                *[
                    f"ip route replace {subnet} dev ${'{HEADEND_CLEAR_IFACE}'}"
                    for subnet in (selectors.get("local_subnets") or [])
                ],
            ]
        )
        + "\n",
        "post-ipsec-nat/post-ipsec-nat-intent.json": _render_post_ipsec_nat_intent(customer_name, post_ipsec_nat),
        "post-ipsec-nat/nftables.apply.nft": post_ipsec_nftables["apply"],
        "post-ipsec-nat/nftables.remove.nft": post_ipsec_nftables["remove"],
        "post-ipsec-nat/nftables-state.json": post_ipsec_nftables["state"],
        "post-ipsec-nat/activation-manifest.json": post_ipsec_nftables["manifest"],
    }


def build_customer_artifact_tree(module: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    return {
        "muxer": build_muxer_artifacts(module, item),
        "headend": build_headend_artifacts(module),
    }
