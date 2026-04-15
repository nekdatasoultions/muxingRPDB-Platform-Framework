"""Render customer-scoped muxer and head-end artifacts."""

from __future__ import annotations

# These helpers turn the merged customer module into small, reviewable intent
# documents. They are the concrete handoff outputs the deployment path can
# package, stage, and validate before any live apply.
import ipaddress
from typing import Any, Dict, Iterable, List


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


def _render_one_to_one_nat_commands(post_ipsec_nat: Dict[str, Any]) -> List[str]:
    interface = _effective_nat_interface(post_ipsec_nat)
    commands: List[str] = []
    real_subnets = [str(value) for value in (post_ipsec_nat.get("real_subnets") or [])]
    translated_subnets = [str(value) for value in (post_ipsec_nat.get("translated_subnets") or [])]
    for real_subnet, translated_subnet in zip(real_subnets, translated_subnets):
        for core_subnet in _iter_core_subnets(post_ipsec_nat):
            core_src = f" -s {core_subnet}" if core_subnet else ""
            core_dst = f" -d {core_subnet}" if core_subnet else ""
            commands.append(
                f"iptables -t nat -A PREROUTING -i {interface}{core_src} -d {translated_subnet} -j NETMAP --to {real_subnet}"
            )
            commands.append(
                f"iptables -t nat -A POSTROUTING -o {interface} -s {real_subnet}{core_dst} -j NETMAP --to {translated_subnet}"
            )
    return commands


def _render_explicit_map_commands(post_ipsec_nat: Dict[str, Any]) -> List[str]:
    interface = _effective_nat_interface(post_ipsec_nat)
    commands: List[str] = []
    for host_mapping in post_ipsec_nat.get("host_mappings") or []:
        real_ip = _cidr_to_host(host_mapping["real_ip"])
        translated_ip = _cidr_to_host(host_mapping["translated_ip"])
        for core_subnet in _iter_core_subnets(post_ipsec_nat):
            core_src = f" -s {core_subnet}" if core_subnet else ""
            core_dst = f" -d {core_subnet}" if core_subnet else ""
            commands.append(
                f"iptables -t nat -A PREROUTING -i {interface}{core_src} -d {translated_ip} -j DNAT --to-destination {real_ip}"
            )
            commands.append(
                f"iptables -t nat -A POSTROUTING -o {interface} -s {real_ip}{core_dst} -j SNAT --to-source {translated_ip}"
            )
    return commands


def _render_generic_nat_commands(post_ipsec_nat: Dict[str, Any]) -> List[str]:
    interface = _effective_nat_interface(post_ipsec_nat)
    translated_source_ip = str(post_ipsec_nat.get("translated_source_ip") or "")
    commands: List[str] = []
    if translated_source_ip:
        for real_subnet in post_ipsec_nat.get("real_subnets") or []:
            for core_subnet in _iter_core_subnets(post_ipsec_nat):
                core_dst = f" -d {core_subnet}" if core_subnet else ""
                commands.append(
                    f"iptables -t nat -A POSTROUTING -o {interface} -s {real_subnet}{core_dst} -j SNAT --to-source {translated_source_ip}"
                )
    return commands


def _render_post_ipsec_nat_commands(post_ipsec_nat: Dict[str, Any]) -> List[str]:
    if not bool(post_ipsec_nat.get("enabled")):
        return []

    strategy = str(post_ipsec_nat.get("mapping_strategy") or "").strip()
    mode = str(post_ipsec_nat.get("mode") or "").strip()
    if strategy == "one_to_one" or mode == "netmap":
        commands = _render_one_to_one_nat_commands(post_ipsec_nat)
    elif strategy == "explicit_host_map" or mode == "explicit_map":
        commands = _render_explicit_map_commands(post_ipsec_nat)
    else:
        commands = _render_generic_nat_commands(post_ipsec_nat)

    if post_ipsec_nat.get("tcp_mss_clamp") is not None:
        interface = _effective_nat_interface(post_ipsec_nat)
        commands.append(
            "iptables -t mangle -A FORWARD "
            f"-o {interface} -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss {int(post_ipsec_nat['tcp_mss_clamp'])}"
        )

    translated_targets = [str(value) for value in (post_ipsec_nat.get("translated_subnets") or [])]
    route_via = str(post_ipsec_nat.get("route_via") or "")
    route_dev = str(post_ipsec_nat.get("route_dev") or "")
    if translated_targets and (route_via or route_dev):
        for translated_subnet in translated_targets:
            if route_via and route_dev:
                commands.append(f"ip route replace {translated_subnet} via {route_via} dev {route_dev}")
            elif route_via:
                commands.append(f"ip route replace {translated_subnet} via {route_via}")
            else:
                commands.append(f"ip route replace {translated_subnet} dev {route_dev}")

    if post_ipsec_nat.get("output_mark"):
        commands.append(f"# output_mark = {post_ipsec_nat.get('output_mark')}")
    return commands


def _render_post_ipsec_nat_intent(post_ipsec_nat: Dict[str, Any]) -> Dict[str, Any]:
    commands = _render_post_ipsec_nat_commands(post_ipsec_nat)
    command_model = "disabled"
    if bool(post_ipsec_nat.get("enabled")):
        if str(post_ipsec_nat.get("mapping_strategy") or "") == "one_to_one":
            command_model = "netmap_one_to_one"
        elif str(post_ipsec_nat.get("mode") or "") == "netmap":
            command_model = "legacy_netmap"
        elif str(post_ipsec_nat.get("mapping_strategy") or "") == "explicit_host_map" or str(post_ipsec_nat.get("mode") or "") == "explicit_map":
            command_model = "explicit_host_map"
        else:
            command_model = "generic_post_ipsec_nat"

    return {
        "enabled": bool(post_ipsec_nat.get("enabled")),
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
        "rendered_command_count": len([line for line in commands if line.strip() and not line.startswith("#")]),
    }


def _render_post_ipsec_nat_snippet(post_ipsec_nat: Dict[str, Any]) -> str:
    commands = _render_post_ipsec_nat_commands(post_ipsec_nat)
    lines = [
        "# Customer-scoped post-IPsec NAT snippet",
        f"# enabled={bool(post_ipsec_nat.get('enabled'))} mode={post_ipsec_nat.get('mode')}",
        f"# mapping_strategy={post_ipsec_nat.get('mapping_strategy') or ''}",
        f"# translated_subnets={','.join(post_ipsec_nat.get('translated_subnets') or [])}",
        f"# real_subnets={','.join(post_ipsec_nat.get('real_subnets') or [])}",
    ]
    if post_ipsec_nat.get("host_mappings"):
        rendered_mappings = [
            f"{item['real_ip']}->{item['translated_ip']}"
            for item in (post_ipsec_nat.get("host_mappings") or [])
        ]
        lines.append(f"# host_mappings={','.join(rendered_mappings)}")
    if commands:
        lines.extend(commands)
    return "\n".join(lines) + "\n"


def build_muxer_artifacts(module: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    customer = module.get("customer") or {}
    peer = module.get("peer") or {}
    transport = module.get("transport") or {}
    selectors = module.get("selectors") or {}
    protocols = module.get("protocols") or {}
    natd_rewrite = module.get("natd_rewrite") or {}
    dynamic_provisioning = module.get("dynamic_provisioning") or {}
    backend = module.get("backend") or {}
    post_ipsec_nat = module.get("post_ipsec_nat") or {}

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
        },
        "firewall/iptables-snippet.txt": "\n".join(
            [
                "# Customer-scoped muxer firewall snippet",
                f"# peer: {peer.get('public_ip')}",
                f"# fwmark: {transport.get('mark')}",
                f"# udp500={protocols.get('udp500')} udp4500={protocols.get('udp4500')} esp50={protocols.get('esp50')}",
            ]
        )
        + "\n",
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
        "post-ipsec-nat/post-ipsec-nat-intent.json": _render_post_ipsec_nat_intent(post_ipsec_nat),
        "post-ipsec-nat/iptables-snippet.txt": _render_post_ipsec_nat_snippet(post_ipsec_nat),
    }


def build_customer_artifact_tree(module: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    return {
        "muxer": build_muxer_artifacts(module, item),
        "headend": build_headend_artifacts(module),
    }
