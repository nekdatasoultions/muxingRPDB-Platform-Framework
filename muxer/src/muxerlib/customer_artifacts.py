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


def _normalized_swanctl_start_action(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "")
    if text == "start|trap":
        return "trap|start"
    if text in {"none", "start", "trap", "trap|start"}:
        return text
    return ""


def _render_ipsec_initiation(ipsec: Dict[str, Any]) -> Dict[str, Any]:
    initiation = ipsec.get("initiation") or {}
    mode = str(initiation.get("mode") or "bidirectional").strip().lower().replace("-", "_")
    if mode not in {"bidirectional", "headend_only", "customer_only", "responder_only"}:
        mode = "bidirectional"

    default_headend = mode in {"bidirectional", "headend_only"}
    default_customer = mode in {"bidirectional", "customer_only", "responder_only"}
    headend_can_initiate = bool(initiation.get("headend_can_initiate", default_headend))
    customer_can_initiate = bool(initiation.get("customer_can_initiate", default_customer))
    traffic_can_start_tunnel = bool(initiation.get("traffic_can_start_tunnel", mode != "headend_only"))
    bring_up_on_apply = bool(initiation.get("bring_up_on_apply", headend_can_initiate))
    swanctl_start_action = _normalized_swanctl_start_action(initiation.get("swanctl_start_action"))

    if not swanctl_start_action:
        legacy_auto = _normalized_swanctl_start_action(ipsec.get("auto"))
        if legacy_auto == "trap|start":
            swanctl_start_action = legacy_auto
        elif bring_up_on_apply and traffic_can_start_tunnel:
            swanctl_start_action = "trap|start"
        elif bring_up_on_apply:
            swanctl_start_action = "start"
        elif traffic_can_start_tunnel:
            swanctl_start_action = "trap"
        else:
            swanctl_start_action = legacy_auto or "none"

    return {
        "mode": mode,
        "headend_can_initiate": headend_can_initiate,
        "customer_can_initiate": customer_can_initiate,
        "traffic_can_start_tunnel": traffic_can_start_tunnel,
        "bring_up_on_apply": bring_up_on_apply,
        "swanctl_start_action": swanctl_start_action,
        "minimum_strongswan_version_for_trap_start": (
            "5.9.6" if swanctl_start_action == "trap|start" else None
        ),
        "legacy_auto": ipsec.get("auto"),
    }


def _render_initiation_script(customer_name: str, initiation: Dict[str, Any]) -> str:
    child_name = f"{customer_name}-child"
    if not bool(initiation.get("headend_can_initiate")):
        return "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -eu",
                f'echo "head-end initiation is disabled for {customer_name}"',
            ]
        ) + "\n"

    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -eu",
            f'CONNECTION="{customer_name}"',
            f'CHILD="{child_name}"',
            'if ! command -v swanctl >/dev/null 2>&1; then',
            '  echo "swanctl not found; cannot initiate $CONNECTION" >&2',
            "  exit 1",
            "fi",
            'INITIATE_TIMEOUT_SECONDS="$(printenv RPDB_HEADEND_INITIATE_TIMEOUT_SECONDS || true)"',
            'if [ -z "$INITIATE_TIMEOUT_SECONDS" ]; then',
            "  INITIATE_TIMEOUT_SECONDS=30",
            "fi",
            'if command -v timeout >/dev/null 2>&1; then',
            '  timeout "$INITIATE_TIMEOUT_SECONDS"s swanctl --initiate --child "$CHILD"',
            "else",
            '  swanctl --initiate --child "$CHILD" --timeout "$INITIATE_TIMEOUT_SECONDS"',
            "fi",
        ]
    ) + "\n"


def _effective_remote_ts(selectors: Dict[str, Any]) -> List[str]:
    # The encryption domain stays customer-declared. remote_host_cidrs is a
    # platform-scoped routing/NAT inventory inside that broader domain.
    return [str(value) for value in (selectors.get("remote_subnets") or []) if str(value).strip()]


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
                    "peer_cidr": peer_cidr,
                    "nft_protocol": protocol_spec["protocol"],
                    "nft_sport": protocol_spec["sport"],
                }
            )
    return {
        "required": True,
        "egress_sources": egress_sources,
        "protocols": [spec["name"] for spec in protocol_specs],
        "rules": rules,
    }


def _render_muxer_firewall_nftables(customer_name: str, snat_coverage: Dict[str, Any]) -> Dict[str, Any]:
    table_name = _nft_name(customer_name, prefix="rpdb_mx")
    rules = list(snat_coverage.get("rules") or [])
    apply_lines = [
        f"# RPDB customer-scoped muxer firewall/SNAT for {customer_name}",
        "# Backend: nftables only.",
        f"table ip {table_name} {{",
        "  chain postrouting {",
        "    type nat hook postrouting priority srcnat; policy accept;",
    ]
    rendered_rules: List[Dict[str, Any]] = []
    for rule in rules:
        source_ip = str(rule.get("source_ip") or "").strip()
        peer_cidr = str(rule.get("peer_cidr") or "").strip()
        protocol = str(rule.get("protocol") or "").strip()
        nft_protocol = str(rule.get("nft_protocol") or "").strip()
        nft_sport = str(rule.get("nft_sport") or "").strip()
        if not source_ip or not peer_cidr or not protocol or not nft_protocol:
            continue
        if nft_protocol == "udp":
            statement = (
                f'    oifname "{_placeholder("MUXER_PUBLIC_IFACE")}" '
                f"ip saddr {source_ip} ip daddr {peer_cidr} "
                f"udp sport {nft_sport} snat to {_placeholder('MUXER_PUBLIC_PRIVATE_IP')}"
            )
        elif nft_protocol == "50":
            statement = (
                f'    oifname "{_placeholder("MUXER_PUBLIC_IFACE")}" '
                f"ip saddr {source_ip} ip daddr {peer_cidr} "
                f"ip protocol esp snat to {_placeholder('MUXER_PUBLIC_PRIVATE_IP')}"
            )
        else:
            statement = (
                f'    oifname "{_placeholder("MUXER_PUBLIC_IFACE")}" '
                f"ip saddr {source_ip} ip daddr {peer_cidr} "
                f"meta l4proto {nft_protocol} snat to {_placeholder('MUXER_PUBLIC_PRIVATE_IP')}"
            )
        apply_lines.append(statement)
        rendered_rules.append(
            {
                "source_ip": source_ip,
                "peer_cidr": peer_cidr,
                "protocol": protocol,
                "nft_statement": statement.strip(),
            }
        )
    apply_lines.extend(["  }", "}"])
    remove_text = "\n".join(
        [
            f"# Remove RPDB customer-scoped muxer firewall/SNAT for {customer_name}",
            f"delete table ip {table_name}",
        ]
    ) + "\n"
    state = {
        "schema_version": 1,
        "backend": "nftables",
        "table_family": "ip",
        "table_name": table_name,
        "customer_name": customer_name,
        "snat_coverage": snat_coverage,
        "rule_count": len(rendered_rules),
        "activation_units": {
            "apply": 2 if rendered_rules else 0,
            "rollback": 1 if rendered_rules else 0,
        },
        "fallback_policy": {
            "backend": "nftables_only",
            "non_nft_fallbacks_allowed": False,
            "external_repo_fallbacks_allowed": False,
        },
    }
    return {
        "apply": "\n".join(apply_lines) + "\n",
        "remove": remove_text,
        "state": state,
        "manifest": {
            **state,
            "artifact_files": [
                "firewall/nftables.apply.nft",
                "firewall/nftables.remove.nft",
                "firewall/nftables-state.json",
            ],
            "rendered_rules": rendered_rules,
            "apply_command_count": state["activation_units"]["apply"],
            "rollback_command_count": state["activation_units"]["rollback"],
        },
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
    local_addrs = ipsec.get("local_addrs") or _placeholder("HEADEND_PRIMARY_IP")
    initiation = _render_ipsec_initiation(ipsec)
    effective_remote_ts = _effective_remote_ts(selectors)
    return {
        "customer_name": customer.get("name"),
        "peer_public_ip": peer.get("public_ip"),
        "local_addrs": local_addrs,
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
        "initiation": initiation,
        "rendered_start_action": initiation["swanctl_start_action"],
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
            "remote_host_cidrs": selectors.get("remote_host_cidrs") or [],
            "effective_remote_ts": effective_remote_ts,
            "effective_remote_ts_source": "remote_subnets",
            "scoped_customer_cidrs": selectors.get("remote_host_cidrs") or [],
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
    secret_name = f"ike-{customer_name}-psk"
    remote_id = str(ipsec.get("remote_id") or peer.get("remote_id") or peer.get("public_ip") or "")
    local_id = str(ipsec.get("local_id") or "")
    local_addrs = str(ipsec.get("local_addrs") or _placeholder("HEADEND_PRIMARY_IP"))
    ike_proposals = _render_ike_proposals(ipsec)
    esp_proposals = _render_esp_proposals(ipsec)
    initiation = _render_ipsec_initiation(ipsec)
    effective_remote_ts = _effective_remote_ts(selectors)
    lines: List[str] = [
        "connections {",
        f"  {customer_name} {{",
        f"    version = {_render_swanctl_version(ipsec)}",
        f"    local_addrs = {local_addrs}",
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
            f"        remote_ts = {','.join(effective_remote_ts)}",
            "        mode = tunnel",
            f"        start_action = {initiation['swanctl_start_action']}",
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
            f"  {secret_name} {{",
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
        "fallback_policy": {
            "backend": "nftables_only",
            "non_nft_fallbacks_allowed": False,
            "external_repo_fallbacks_allowed": False,
        },
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
            command_model = "nftables_netmap_compat"
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
            "fallback_policy": manifest.get("fallback_policy"),
        },
    }


def _outside_nat_customer_sources(outside_nat: Dict[str, Any], selectors: Dict[str, Any]) -> List[str]:
    explicit_sources = [str(value) for value in (outside_nat.get("customer_sources") or []) if str(value).strip()]
    if explicit_sources:
        return explicit_sources
    host_sources = [str(value) for value in (selectors.get("remote_host_cidrs") or []) if str(value).strip()]
    if host_sources:
        return host_sources
    return [str(value) for value in (selectors.get("remote_subnets") or []) if str(value).strip()]


def _render_outside_nat_nftables(
    customer_name: str,
    outside_nat: Dict[str, Any],
    selectors: Dict[str, Any],
) -> Dict[str, Any]:
    enabled = bool(outside_nat.get("enabled"))
    safe_customer = _nft_name(customer_name, prefix="cust")
    table_name = _nft_name(customer_name, prefix="rpdb_on")
    dnat_map = f"{safe_customer}_outside_dnat_v4"
    snat_map = f"{safe_customer}_outside_snat_v4"
    translated_set = f"{safe_customer}_outside_translated_v4"
    real_set = f"{safe_customer}_outside_real_v4"
    customer_sources_set = f"{safe_customer}_outside_customer_sources_v4"
    output_mark = str(outside_nat.get("output_mark") or "").strip()
    tcp_mss_clamp = outside_nat.get("tcp_mss_clamp")

    host_mappings, warnings = _build_nft_host_mappings(outside_nat)
    dnat_entries = _nft_map_entries(host_mappings)
    snat_entries = _nft_map_entries([(real_ip, translated_ip) for translated_ip, real_ip in host_mappings])
    translated_values = sorted({translated_ip for translated_ip, _real_ip in host_mappings})
    real_values = sorted({real_ip for _translated_ip, real_ip in host_mappings})
    customer_source_values = _nft_set_values(_outside_nat_customer_sources(outside_nat, selectors))
    if not customer_source_values:
        customer_source_values = ["0.0.0.0/0"]

    state = {
        "schema_version": 1,
        "backend": "nftables",
        "table_family": "ip",
        "table_name": table_name,
        "enabled": enabled,
        "mode": outside_nat.get("mode"),
        "mapping_strategy": outside_nat.get("mapping_strategy"),
        "customer_name": customer_name,
        "purpose": "outside_nat_local_presentation",
        "chains": {
            "prerouting": "prerouting",
            "postrouting": "postrouting",
            "mangle_prerouting": "mangle_prerouting",
            "mangle_forward": "mangle_forward",
        },
        "sets": {
            "customer_sources": customer_sources_set,
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
        "fallback_policy": {
            "backend": "nftables_only",
            "non_nft_fallbacks_allowed": False,
            "external_repo_fallbacks_allowed": False,
        },
    }

    if not enabled:
        disabled_text = "# outside NAT disabled; no nftables state required\n"
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
        f"# RPDB customer-scoped outside NAT for {customer_name}",
        "# Backend: nftables only.",
        "# Direction: customer-visible translated local space <-> real local/core space.",
        f"table ip {table_name} {{",
        f"  set {customer_sources_set} {{",
        "    type ipv4_addr",
        "    flags interval",
        f"    elements = { _nft_inline_elements(customer_source_values) }",
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
        f"    ip saddr @{customer_sources_set} ip daddr @{translated_set} dnat to ip daddr map @{dnat_map}",
        "  }",
        "  chain postrouting {",
        "    type nat hook postrouting priority srcnat; policy accept;",
        f"    ip saddr @{real_set} ip daddr @{customer_sources_set} snat to ip saddr map @{snat_map}",
        "  }",
    ]
    if output_mark:
        lines.extend(
            [
                "  chain mangle_prerouting {",
                "    type filter hook prerouting priority mangle; policy accept;",
                f"    ip saddr @{customer_sources_set} ip daddr @{translated_set} meta mark set {output_mark}",
                "  }",
            ]
        )
    if tcp_mss_clamp not in {None, ""}:
        lines.extend(
            [
                "  chain mangle_forward {",
                "    type filter hook forward priority mangle; policy accept;",
                f"    ip saddr @{customer_sources_set} ip daddr @{real_set} tcp flags syn / syn,rst tcp option maxseg size set {int(tcp_mss_clamp)}",
                "  }",
            ]
        )
    lines.extend(["}", ""])

    remove_lines = [
        f"# Remove RPDB customer-scoped outside NAT for {customer_name}",
        f"delete table ip {table_name}",
        "",
    ]
    manifest = {
        **state,
        "artifact_files": [
            "outside-nat/nftables.apply.nft",
            "outside-nat/nftables.remove.nft",
            "outside-nat/nftables-state.json",
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


def _render_outside_nat_intent(
    customer_name: str,
    outside_nat: Dict[str, Any],
    selectors: Dict[str, Any],
) -> Dict[str, Any]:
    nftables = _render_outside_nat_nftables(customer_name, outside_nat, selectors)
    manifest = nftables["manifest"]
    command_model = "disabled"
    if bool(outside_nat.get("enabled")):
        if str(outside_nat.get("mapping_strategy") or "") == "one_to_one":
            command_model = "nftables_outside_nat_netmap_one_to_one"
        elif str(outside_nat.get("mode") or "") == "netmap":
            command_model = "nftables_outside_nat_netmap_compat"
        elif str(outside_nat.get("mapping_strategy") or "") == "explicit_host_map" or str(outside_nat.get("mode") or "") == "explicit_map":
            command_model = "nftables_outside_nat_explicit_host_map"
        else:
            command_model = "nftables_generic_outside_nat"

    return {
        "enabled": bool(outside_nat.get("enabled")),
        "activation_backend": "nftables",
        "mode": outside_nat.get("mode"),
        "mapping_strategy": outside_nat.get("mapping_strategy"),
        "translated_subnets": outside_nat.get("translated_subnets") or [],
        "real_subnets": outside_nat.get("real_subnets") or [],
        "host_mappings": outside_nat.get("host_mappings") or [],
        "customer_sources": _outside_nat_customer_sources(outside_nat, selectors),
        "selector_remote_subnets": selectors.get("remote_subnets") or [],
        "selector_remote_host_cidrs": selectors.get("remote_host_cidrs") or [],
        "interface": _effective_nat_interface(outside_nat),
        "output_mark": outside_nat.get("output_mark"),
        "tcp_mss_clamp": outside_nat.get("tcp_mss_clamp"),
        "route_via": outside_nat.get("route_via"),
        "route_dev": outside_nat.get("route_dev"),
        "deferred": bool(outside_nat.get("deferred")),
        "defer_reason": outside_nat.get("defer_reason"),
        "rendered_command_model": command_model,
        "rendered_command_count": int(manifest.get("apply_command_count") or 0),
        "activation_manifest": {
            "backend": manifest.get("backend"),
            "table_name": manifest.get("table_name"),
            "apply_command_count": manifest.get("apply_command_count"),
            "rollback_command_count": manifest.get("rollback_command_count"),
            "host_mapping_count": manifest.get("host_mapping_count"),
            "fallback_policy": manifest.get("fallback_policy"),
        },
    }


def _is_dynamic_nat_t_initial_headend(
    customer: Dict[str, Any],
    backend: Dict[str, Any],
    dynamic_provisioning: Dict[str, Any],
) -> bool:
    if not bool(dynamic_provisioning.get("enabled")):
        return False
    mode = str(dynamic_provisioning.get("mode") or "nat_t_auto_promote").strip()
    if mode != "nat_t_auto_promote":
        return False
    customer_class = str(customer.get("customer_class") or "").strip().lower().replace("_", "-")
    backend_cluster = str(backend.get("cluster") or "").strip().lower().replace("_", "-")
    return customer_class in {"strict-non-nat", "non-nat"} or backend_cluster in {"non-nat"}


def _effective_headend_outside_nat(
    customer: Dict[str, Any],
    backend: Dict[str, Any],
    dynamic_provisioning: Dict[str, Any],
    outside_nat: Dict[str, Any],
) -> Dict[str, Any]:
    if bool(outside_nat.get("enabled")) and _is_dynamic_nat_t_initial_headend(
        customer,
        backend,
        dynamic_provisioning,
    ):
        # The initial dynamic package runs on the non-NAT head end only to
        # observe UDP/4500. NAT-head-end clear-side routes are applied after
        # promotion, when the NAT package is rendered against the NAT backend.
        deferred = dict(outside_nat)
        deferred["enabled"] = False
        deferred["deferred"] = True
        deferred["defer_reason"] = "dynamic_nat_t_initial_non_nat"
        return deferred
    return outside_nat


def _render_clear_route_command(subnet: str, outside_nat: Dict[str, Any]) -> str:
    route_via = str(outside_nat.get("route_via") or "").strip()
    route_dev = str(outside_nat.get("route_dev") or "").strip() or "${HEADEND_CLEAR_IFACE}"
    if route_via:
        return f"ip route replace {subnet} via {route_via} dev {route_dev}"
    return f"ip route replace {subnet} dev {route_dev}"


def _interface_host(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return str(ipaddress.ip_interface(text).ip)


def _render_headend_transport_artifacts(
    *,
    customer_name: str,
    peer_public_cidr: str,
    transport: Dict[str, Any],
    backend: Dict[str, Any],
) -> Dict[str, Any]:
    overlay = transport.get("overlay") or {}
    interface = str(transport.get("interface") or "").strip()
    tunnel_type = str(transport.get("tunnel_type") or "gre").strip().lower()
    tunnel_key = transport.get("tunnel_key")
    tunnel_ttl = transport.get("tunnel_ttl") or 64
    router_overlay_ip = str(overlay.get("router_ip") or "").strip()
    mux_overlay_ip = str(overlay.get("mux_ip") or "").strip()
    mux_overlay_host = _interface_host(mux_overlay_ip) if mux_overlay_ip else ""
    enabled = bool(
        interface
        and tunnel_type == "gre"
        and tunnel_key not in (None, "")
        and router_overlay_ip
        and mux_overlay_host
        and peer_public_cidr
    )

    intent = {
        "customer_name": customer_name,
        "enabled": enabled,
        "type": tunnel_type,
        "interface": interface or None,
        "tunnel_key": tunnel_key,
        "tunnel_ttl": tunnel_ttl,
        "local_underlay": _placeholder("HEADEND_PRIMARY_IP"),
        "remote_underlay": _placeholder("MUXER_TRANSPORT_IP"),
        "backend_underlay_ip": backend.get("underlay_ip"),
        "router_overlay_ip": router_overlay_ip or None,
        "mux_overlay_ip": mux_overlay_ip or None,
        "mux_overlay_host": mux_overlay_host or None,
        "peer_public_cidr": peer_public_cidr or None,
        "purpose": "customer-scoped GRE return path from the head-end back to the muxer edge",
    }

    apply_script = "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -eu",
            'SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"',
            'INTENT="$SCRIPT_DIR/transport-intent.json"',
            "json_get() {",
            "  python3 -c 'import json,sys; data=json.load(open(sys.argv[1])); value=data.get(sys.argv[2]); print(str(value).lower() if isinstance(value, bool) else (\"\" if value is None else value))' \"$INTENT\" \"$1\"",
            "}",
            'ENABLED="$(json_get enabled)"',
            'if [ "$ENABLED" != "true" ]; then',
            "  exit 0",
            "fi",
            'IFNAME="$(json_get interface)"',
            'LOCAL_UL="$(json_get local_underlay)"',
            'REMOTE_UL="$(json_get remote_underlay)"',
            'ROUTER_IP="$(json_get router_overlay_ip)"',
            'MUX_OVERLAY_HOST="$(json_get mux_overlay_host)"',
            'PEER_CIDR="$(json_get peer_public_cidr)"',
            'KEY="$(json_get tunnel_key)"',
            'TTL="$(json_get tunnel_ttl)"',
            'if ip link show "$IFNAME" >/dev/null 2>&1; then',
            '  ip link del "$IFNAME"',
            "fi",
            'ip tunnel add "$IFNAME" mode gre local "$LOCAL_UL" remote "$REMOTE_UL" key "$KEY" ttl "$TTL"',
            'ip addr replace "$ROUTER_IP" dev "$IFNAME"',
            'ip link set "$IFNAME" up',
            'ip route replace "$PEER_CIDR" via "$MUX_OVERLAY_HOST" dev "$IFNAME"',
            "",
        ]
    )

    remove_script = "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -eu",
            'SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"',
            'INTENT="$SCRIPT_DIR/transport-intent.json"',
            "json_get() {",
            "  python3 -c 'import json,sys; data=json.load(open(sys.argv[1])); value=data.get(sys.argv[2]); print(str(value).lower() if isinstance(value, bool) else (\"\" if value is None else value))' \"$INTENT\" \"$1\"",
            "}",
            'IFNAME="$(json_get interface)"',
            'PEER_CIDR="$(json_get peer_public_cidr)"',
            'if [ -n "$PEER_CIDR" ] && [ -n "$IFNAME" ]; then',
            '  ip route del "$PEER_CIDR" dev "$IFNAME" 2>/dev/null || true',
            "fi",
            'if [ -n "$IFNAME" ]; then',
            '  ip link del "$IFNAME" 2>/dev/null || true',
            "fi",
            "",
        ]
    )

    return {
        "transport/transport-intent.json": intent,
        "transport/apply-transport.sh": apply_script,
        "transport/remove-transport.sh": remove_script,
    }


def _render_headend_public_identity_artifacts(customer_name: str) -> Dict[str, Any]:
    intent = {
        "customer_name": customer_name,
        "enabled": True,
        "public_ip": _placeholder("HEADEND_PUBLIC_IP"),
        "cidr": f"{_placeholder('HEADEND_PUBLIC_IP')}/32",
        "device": "lo",
        "local_id": _placeholder("HEADEND_ID"),
        "remove_policy": "retain_shared_identity",
        "purpose": "make the muxer EIP identity locally present for IPsec validation and symmetric initiation",
    }

    apply_script = "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -eu",
            'SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"',
            'INTENT="$SCRIPT_DIR/public-identity-intent.json"',
            'PUBLIC_CIDR="$(python3 -c \'import json,sys; print(json.load(open(sys.argv[1])).get("cidr") or "")\' "$INTENT")"',
            'DEVICE="$(python3 -c \'import json,sys; print(json.load(open(sys.argv[1])).get("device") or "lo")\' "$INTENT")"',
            'if [ -n "$PUBLIC_CIDR" ]; then',
            '  ip addr replace "$PUBLIC_CIDR" dev "$DEVICE"',
            "fi",
            "",
        ]
    )

    remove_script = "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -eu",
            "# Shared head-end public identity is retained on customer removal.",
            "# Platform teardown, not per-customer rollback, should remove it.",
            "true",
            "",
        ]
    )

    return {
        "public-identity/public-identity-intent.json": intent,
        "public-identity/apply-public-identity.sh": apply_script,
        "public-identity/remove-public-identity.sh": remove_script,
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
    outside_nat = module.get("outside_nat") or {}
    snat_coverage = _build_snat_coverage(
        peer_ip=str(peer.get("public_ip") or ""),
        backend=backend,
        protocols=protocols,
        ipsec=ipsec,
    )
    muxer_firewall_nftables = _render_muxer_firewall_nftables(str(customer.get("name") or ""), snat_coverage)

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
            "remote_host_cidrs": selectors.get("remote_host_cidrs") or [],
            "effective_remote_ts": _effective_remote_ts(selectors),
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
                f"ip route replace table {transport.get('table')} default via ${'{BACKEND_UNDERLAY_IP}'} dev ${'{MUXER_UNDERLAY_IFACE}'} onlink",
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
            "outside_nat_enabled": bool(outside_nat.get("enabled")),
            "outside_nat_mapping_strategy": outside_nat.get("mapping_strategy"),
            "headend_egress_sources": snat_coverage["egress_sources"],
            "snat_coverage": snat_coverage,
            "activation_backend": "nftables",
            "activation_manifest": {
                "backend": "nftables",
                "table_name": muxer_firewall_nftables["manifest"].get("table_name"),
                "apply_command_count": muxer_firewall_nftables["manifest"].get("apply_command_count"),
                "rollback_command_count": muxer_firewall_nftables["manifest"].get("rollback_command_count"),
                "rule_count": muxer_firewall_nftables["manifest"].get("rule_count"),
                "fallback_policy": muxer_firewall_nftables["manifest"].get("fallback_policy"),
            },
        },
        "firewall/nftables.apply.nft": muxer_firewall_nftables["apply"],
        "firewall/nftables.remove.nft": muxer_firewall_nftables["remove"],
        "firewall/nftables-state.json": muxer_firewall_nftables["state"],
        "firewall/activation-manifest.json": muxer_firewall_nftables["manifest"],
    }


def build_headend_artifacts(module: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    customer = module.get("customer") or {}
    peer = module.get("peer") or {}
    selectors = module.get("selectors") or {}
    transport = module.get("transport") or {}
    backend = module.get("backend") or {}
    protocols = module.get("protocols") or {}
    dynamic_provisioning = module.get("dynamic_provisioning") or {}
    ipsec = module.get("ipsec") or {}
    post_ipsec_nat = module.get("post_ipsec_nat") or {}
    raw_outside_nat = module.get("outside_nat") or {}
    customer_name = str(customer.get("name") or "")
    outside_nat = _effective_headend_outside_nat(
        customer,
        backend,
        dynamic_provisioning,
        raw_outside_nat,
    )
    peer_public_ip = str(peer.get("public_ip") or "").strip()
    peer_public_cidr = f"{peer_public_ip}/32" if peer_public_ip and "/" not in peer_public_ip else peer_public_ip
    overlay = transport.get("overlay") or {}
    mux_overlay_ip = str(overlay.get("mux_ip") or "").strip()
    mux_overlay_host = _interface_host(mux_overlay_ip) if mux_overlay_ip else ""
    transport_interface = str(transport.get("interface") or "").strip()
    post_ipsec_nftables = _render_post_ipsec_nat_nftables(customer_name, post_ipsec_nat)
    outside_nat_nftables = _render_outside_nat_nftables(customer_name, outside_nat, selectors)
    transport_artifacts = _render_headend_transport_artifacts(
        customer_name=customer_name,
        peer_public_cidr=peer_public_cidr,
        transport=transport,
        backend=backend,
    )
    public_identity_artifacts = _render_headend_public_identity_artifacts(customer_name)
    ipsec_initiation = _render_ipsec_initiation(ipsec)
    effective_remote_ts = _effective_remote_ts(selectors)
    clear_route_subnets = (
        outside_nat.get("real_subnets")
        if bool(outside_nat.get("enabled")) and outside_nat.get("real_subnets")
        else selectors.get("local_subnets")
    ) or []
    route_commands = [
        "# Customer-scoped head-end routes",
        *[
            _render_clear_route_command(str(subnet), outside_nat if bool(outside_nat.get("enabled")) else {})
            for subnet in clear_route_subnets
        ],
    ]
    if peer_public_cidr and mux_overlay_host and transport_interface:
        route_commands.extend(
            [
                "# Return IPsec transport traffic through the customer-scoped GRE path to the muxer edge",
                f"ip route replace {peer_public_cidr} via {mux_overlay_host} dev {transport_interface}",
            ]
        )

    return {
        "ipsec/ipsec-intent.json": _render_ipsec_intent(customer, peer, selectors, protocols, ipsec),
        "ipsec/swanctl-connection.conf": _render_swanctl_connection(customer, peer, selectors, ipsec),
        "ipsec/initiation-intent.json": {
            **ipsec_initiation,
            "customer_name": customer_name,
            "connection": customer_name,
            "child": f"{customer_name}-child",
            "manual_headend_command": (
                f"swanctl --initiate --child {customer_name}-child"
                if bool(ipsec_initiation.get("headend_can_initiate"))
                else None
            ),
            "responder_capability": {
                "customer_can_initiate": bool(ipsec_initiation.get("customer_can_initiate")),
                "requires_loaded_connection": True,
                "requires_matching_remote_id": True,
                "requires_matching_traffic_selectors": True,
            },
        },
        "ipsec/initiate-tunnel.sh": _render_initiation_script(customer_name, ipsec_initiation),
        "routing/routing-intent.json": {
            "backend_cluster": backend.get("cluster"),
            "backend_assignment": backend.get("assignment"),
            "backend_role": backend.get("role"),
            "backend_underlay_ip": backend.get("underlay_ip"),
            "selectors": {
                "local_subnets": selectors.get("local_subnets") or [],
                "remote_subnets": selectors.get("remote_subnets") or [],
                "remote_host_cidrs": selectors.get("remote_host_cidrs") or [],
                "effective_remote_ts": effective_remote_ts,
                "effective_remote_ts_source": "remote_subnets",
                "scoped_customer_cidrs": selectors.get("remote_host_cidrs") or [],
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
            "edge_return_path": {
                "enabled": bool(peer_public_cidr and mux_overlay_host and transport_interface),
                "peer_public_cidr": peer_public_cidr or None,
                "next_hop": mux_overlay_host if peer_public_cidr else None,
                "interface": transport_interface if peer_public_cidr else None,
                "transport": {
                    "type": transport.get("tunnel_type"),
                    "requires_headend_tunnel": True,
                },
                "purpose": "force head-end IPsec transport replies back through the customer-scoped GRE tunnel to the muxer edge",
            },
            "outside_nat": {
                "enabled": bool(outside_nat.get("enabled")),
                "deferred": bool(outside_nat.get("deferred")),
                "defer_reason": outside_nat.get("defer_reason"),
                "presented_local_subnets": outside_nat.get("translated_subnets") or selectors.get("local_subnets") or [],
                "real_local_subnets": outside_nat.get("real_subnets") or [],
                "customer_sources": _outside_nat_customer_sources(outside_nat, selectors),
                "clear_route_subnets": clear_route_subnets,
                "purpose": "translate customer-visible far-end space to real local/core space",
            },
        },
        "routing/ip-route.commands.txt": "\n".join(route_commands) + "\n",
        **transport_artifacts,
        **public_identity_artifacts,
        "post-ipsec-nat/post-ipsec-nat-intent.json": _render_post_ipsec_nat_intent(customer_name, post_ipsec_nat),
        "post-ipsec-nat/nftables.apply.nft": post_ipsec_nftables["apply"],
        "post-ipsec-nat/nftables.remove.nft": post_ipsec_nftables["remove"],
        "post-ipsec-nat/nftables-state.json": post_ipsec_nftables["state"],
        "post-ipsec-nat/activation-manifest.json": post_ipsec_nftables["manifest"],
        "outside-nat/outside-nat-intent.json": _render_outside_nat_intent(customer_name, outside_nat, selectors),
        "outside-nat/nftables.apply.nft": outside_nat_nftables["apply"],
        "outside-nat/nftables.remove.nft": outside_nat_nftables["remove"],
        "outside-nat/nftables-state.json": outside_nat_nftables["state"],
        "outside-nat/activation-manifest.json": outside_nat_nftables["manifest"],
    }


def build_customer_artifact_tree(module: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    return {
        "muxer": build_muxer_artifacts(module, item),
        "headend": build_headend_artifacts(module),
    }
