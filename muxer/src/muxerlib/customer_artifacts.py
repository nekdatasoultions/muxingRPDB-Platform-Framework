"""Render customer-scoped muxer and head-end intent artifacts."""

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
        "customer-summary.json": {
            "customer_name": customer.get("name"),
            "customer_id": customer.get("id"),
            "customer_class": customer.get("customer_class"),
            "peer_ip": peer.get("public_ip"),
            "backend_role": backend.get("role"),
            "backend_underlay_ip": backend.get("underlay_ip"),
            "local_subnets": selectors.get("local_subnets") or [],
            "remote_subnets": selectors.get("remote_subnets") or [],
        },
        "rpdb-routing.json": {
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
        "tunnel-intent.json": {
            "interface": transport.get("interface"),
            "tunnel_type": transport.get("tunnel_type"),
            "tunnel_key": transport.get("tunnel_key"),
            "tunnel_ttl": transport.get("tunnel_ttl"),
            "overlay": transport.get("overlay") or {},
            "peer_public_ip": peer.get("public_ip"),
            "backend_underlay_ip": backend.get("underlay_ip"),
        },
        "firewall-intent.json": {
            "protocols": {
                "udp500": protocols.get("udp500"),
                "udp4500": protocols.get("udp4500"),
                "esp50": protocols.get("esp50"),
                "force_rewrite_4500_to_500": protocols.get("force_rewrite_4500_to_500"),
            },
            "natd_rewrite": natd_rewrite,
            "post_ipsec_nat_enabled": bool(post_ipsec_nat.get("enabled")),
        },
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
        "ipsec-intent.json": {
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
        "routing-intent.json": {
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
        "post-ipsec-nat-intent.json": {
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
    }
