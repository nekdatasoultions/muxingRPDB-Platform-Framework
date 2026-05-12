"""Customer route-scope helpers shared by provisioning and validation."""

from __future__ import annotations

import ipaddress
from typing import Any


def _append_unique(values: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in values:
        values.append(text)


def _host_cidr(value: Any) -> str:
    address = ipaddress.ip_interface(str(value)).ip
    return f"{address}/32"


def _ip_networks(values: list[Any]) -> list[ipaddress.IPv4Network]:
    return [ipaddress.ip_network(str(value), strict=False) for value in values if str(value).strip()]


def _network_addresses(network: ipaddress.IPv4Network) -> list[ipaddress.IPv4Address]:
    # nftables rendering uses the complete declared network, including /32s and
    # pool boundary addresses, so route derivation follows the same address set.
    return [ipaddress.ip_address(value) for value in network]


def _uses_explicit_host_map(post_ipsec_nat: dict[str, Any]) -> bool:
    strategy = str(post_ipsec_nat.get("mapping_strategy") or "").strip()
    mode = str(post_ipsec_nat.get("mode") or "").strip()
    return strategy == "explicit_host_map" or mode == "explicit_map"


def _uses_netmap(post_ipsec_nat: dict[str, Any]) -> bool:
    strategy = str(post_ipsec_nat.get("mapping_strategy") or "").strip()
    mode = str(post_ipsec_nat.get("mode") or "").strip()
    return strategy == "one_to_one" or mode == "netmap"


def _netmap_route_cidrs(post_ipsec_nat: dict[str, Any]) -> list[str]:
    real_networks = _ip_networks(post_ipsec_nat.get("real_subnets") or [])
    translated_networks = _ip_networks(post_ipsec_nat.get("translated_subnets") or [])
    route_cidrs: list[str] = []
    use_distinct_routes = False

    if len(real_networks) != len(translated_networks):
        use_distinct_routes = True
    for real_network, translated_network in zip(real_networks, translated_networks):
        if real_network.num_addresses != translated_network.num_addresses:
            use_distinct_routes = True

    if not use_distinct_routes:
        for value in post_ipsec_nat.get("translated_subnets") or []:
            _append_unique(route_cidrs, value)
        return route_cidrs

    for real_network, translated_network in zip(real_networks, translated_networks):
        real_hosts = _network_addresses(real_network)
        translated_hosts = _network_addresses(translated_network)
        for translated_ip in translated_hosts[: len(real_hosts)]:
            _append_unique(route_cidrs, f"{translated_ip}/32")
    return route_cidrs


def post_ipsec_nat_route_cidrs(post_ipsec_nat: dict[str, Any]) -> tuple[list[str], str]:
    """Return SmartConnect/jump-host route CIDRs for enabled inside NAT.

    Pool/netmap NAT routes the declared translated pool when the real and
    translated blocks match. Distinct netmap and explicit host-map NAT route
    the translated hosts that actually have DNAT entries.
    """

    if not bool(post_ipsec_nat.get("enabled")):
        return [], ""

    route_cidrs: list[str] = []
    if _uses_explicit_host_map(post_ipsec_nat):
        for host_mapping in post_ipsec_nat.get("host_mappings") or []:
            if isinstance(host_mapping, dict):
                _append_unique(route_cidrs, _host_cidr(host_mapping.get("translated_ip")))
        if route_cidrs:
            return route_cidrs, "post_ipsec_nat.host_mappings.translated_ip"

    if _uses_netmap(post_ipsec_nat):
        route_cidrs = _netmap_route_cidrs(post_ipsec_nat)
        if route_cidrs:
            source = (
                "post_ipsec_nat.netmap_translated_hosts"
                if all(cidr.endswith("/32") for cidr in route_cidrs)
                else "post_ipsec_nat.translated_subnets"
            )
            return route_cidrs, source

    for value in post_ipsec_nat.get("translated_subnets") or []:
        _append_unique(route_cidrs, value)
    return route_cidrs, "post_ipsec_nat.translated_subnets"


def customer_route_cidrs(customer_module: dict[str, Any]) -> tuple[list[str], str]:
    """Return the non-overlapping customer-side route scope for one customer."""

    selectors = customer_module.get("selectors") or {}
    post_ipsec_nat = customer_module.get("post_ipsec_nat") or {}
    if bool(post_ipsec_nat.get("enabled")):
        return post_ipsec_nat_route_cidrs(post_ipsec_nat)

    route_cidrs: list[str] = []
    for value in selectors.get("remote_host_cidrs") or []:
        _append_unique(route_cidrs, value)
    return route_cidrs, "remote_host_cidrs"


def customer_cleanup_route_cidrs(customer_module: dict[str, Any]) -> list[str]:
    """Return all route CIDRs that may need cleanup for this customer.

    Cleanup deliberately includes both old pool routes and newer explicit host
    routes so a customer can safely move between DNAT mapping modes.
    """

    selectors = customer_module.get("selectors") or {}
    post_ipsec_nat = customer_module.get("post_ipsec_nat") or {}
    cidrs: list[str] = []

    for value in selectors.get("remote_host_cidrs") or []:
        _append_unique(cidrs, value)
    for value in post_ipsec_nat.get("translated_subnets") or []:
        _append_unique(cidrs, value)
    for host_mapping in post_ipsec_nat.get("host_mappings") or []:
        if isinstance(host_mapping, dict):
            _append_unique(cidrs, _host_cidr(host_mapping.get("translated_ip")))
    route_cidrs, _source = post_ipsec_nat_route_cidrs(post_ipsec_nat)
    for cidr in route_cidrs:
        _append_unique(cidrs, cidr)

    return cidrs
