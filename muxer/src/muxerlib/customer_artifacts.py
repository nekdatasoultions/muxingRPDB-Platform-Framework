"""Render customer-scoped muxer and head-end artifacts."""

from __future__ import annotations

# These helpers turn the merged customer module into small, reviewable intent
# documents. They are not live apply artifacts yet; they are the concrete
# handoff outputs the deployment branch can package and validate.
from typing import Any, Dict


def build_muxer_artifacts(module: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    customer = module.get("customer") or {}
    peer = module.get("peer") or {}
    transport = module.get("transport") or {}
    selectors = module.get("selectors") or {}
    protocols = module.get("protocols") or {}
    natd_rewrite = module.get("natd_rewrite") or {}
    backend = module.get("backend") or {}
    post_ipsec_nat = module.get("post_ipsec_nat") or {}

    return {
        "customer/customer-summary.json": {
            "customer_name": customer.get("name"),
            "customer_id": customer.get("id"),
            "customer_class": customer.get("customer_class"),
            "peer_ip": peer.get("public_ip"),
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
            "post_ipsec_nat_enabled": bool(post_ipsec_nat.get("enabled")),
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
        "ipsec/ipsec-intent.json": {
            "customer_name": customer.get("name"),
            "peer_public_ip": peer.get("public_ip"),
            "remote_id": peer.get("remote_id"),
            "ike": ipsec.get("ike"),
            "esp": ipsec.get("esp"),
            "auto": ipsec.get("auto"),
            "dpddelay": ipsec.get("dpddelay"),
            "dpdtimeout": ipsec.get("dpdtimeout"),
            "dpdaction": ipsec.get("dpdaction"),
            "encapsulation_model": "nat-t" if protocols.get("udp4500") else "strict-non-nat",
        },
        "ipsec/swanctl-connection.conf": "\n".join(
            [
                f"connections {{",
                f"  {customer.get('name')} {{",
                "    version = 2",
                f"    local_addrs = ${'{HEADEND_PUBLIC_IP}'}",
                f"    remote_addrs = {peer.get('public_ip')}",
                "    local {",
                "      auth = psk",
                f"      id = ${'{HEADEND_ID}'}",
                "    }",
                "    remote {",
                "      auth = psk",
                f"      id = {peer.get('remote_id')}",
                "    }",
                "    children {",
                f"      {customer.get('name')}-child {{",
                f"        local_ts = {','.join(selectors.get('local_subnets') or [])}",
                f"        remote_ts = {','.join(selectors.get('remote_subnets') or [])}",
                f"        start_action = {ipsec.get('auto') or 'start'}",
                f"      }}",
                "    }",
                "  }",
                "}",
                "",
                "secrets {",
                f"  {customer.get('name')}-psk {{",
                f"    id-1 = ${'{HEADEND_ID}'}",
                f"    id-2 = {peer.get('remote_id')}",
                f"    secret = ${'{PSK_FROM_SECRET_REF}'}",
                "  }",
                "}",
            ]
        )
        + "\n",
        "routing/routing-intent.json": {
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
        "post-ipsec-nat/post-ipsec-nat-intent.json": {
            "enabled": bool(post_ipsec_nat.get("enabled")),
            "mode": post_ipsec_nat.get("mode"),
            "translated_subnets": post_ipsec_nat.get("translated_subnets") or [],
            "translated_source_ip": post_ipsec_nat.get("translated_source_ip"),
            "real_subnets": post_ipsec_nat.get("real_subnets") or [],
            "core_subnets": post_ipsec_nat.get("core_subnets") or [],
            "interface": post_ipsec_nat.get("interface"),
            "output_mark": post_ipsec_nat.get("output_mark"),
            "route_via": post_ipsec_nat.get("route_via"),
            "route_dev": post_ipsec_nat.get("route_dev"),
        },
        "post-ipsec-nat/iptables-snippet.txt": "\n".join(
            [
                "# Customer-scoped post-IPsec NAT snippet",
                f"# enabled={bool(post_ipsec_nat.get('enabled'))} mode={post_ipsec_nat.get('mode')}",
                f"# translated_subnets={','.join(post_ipsec_nat.get('translated_subnets') or [])}",
                f"# real_subnets={','.join(post_ipsec_nat.get('real_subnets') or [])}",
            ]
        )
        + "\n",
    }


def build_customer_artifact_tree(module: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    return {
        "muxer": build_muxer_artifacts(module, item),
        "headend": build_headend_artifacts(module),
    }
