from __future__ import annotations

import ipaddress
from typing import Any


def _sanitize(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in value)


def _as_host_cidr(ip_or_cidr: str) -> str:
    value = str(ip_or_cidr).strip()
    if not value:
        raise ValueError("expected non-empty IP or CIDR value")
    return value if "/" in value else f"{value}/32"


def _resolve_selected_backend_public_loopback(bundle: dict[str, Any]) -> str:
    backend_selection = dict(bundle["sot"]["backend_selection"])
    preferred_class = str(backend_selection.get("preferred_class") or "").strip()
    if not preferred_class:
        raise ValueError("bundle.sot.backend_selection.preferred_class is required")

    explicit_public_ip = str(backend_selection.get("customer_facing_public_ip") or "").strip()
    explicit_loopback = str(backend_selection.get("termination_public_loopback") or "").strip()
    operations_candidates = list((bundle["operations"]["backend_vpn_head_ends"] or {}).get(preferred_class) or [])
    derived_loopback = ""
    if operations_candidates:
        derived_loopback = str(operations_candidates[0].get("public_loopback") or "").strip()

    chosen = explicit_public_ip or explicit_loopback or derived_loopback
    if not chosen:
        raise ValueError("unable to resolve backend public loopback from bundle")

    for label, candidate in {
        "customer_facing_public_ip": explicit_public_ip,
        "termination_public_loopback": explicit_loopback,
        "operations.backend_vpn_head_ends public_loopback": derived_loopback,
    }.items():
        if candidate and candidate != chosen:
            raise ValueError(f"backend public loopback mismatch: selected {chosen!r} but {label} is {candidate!r}")
    return chosen


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = _as_host_cidr(value)
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _resolve_bundle_service_reachable_subnets(bundle: dict[str, Any]) -> list[str]:
    backend_selection = dict(bundle["sot"].get("backend_selection") or {})
    configured = list(backend_selection.get("service_reachable_subnets") or [])
    if configured:
        return _dedupe_preserve_order(configured)
    return [_as_host_cidr(_resolve_selected_backend_public_loopback(bundle))]


def _resolve_service_local_subnets(bundle: dict[str, Any], integration: dict[str, Any]) -> list[str]:
    explicit = list(integration.get("service_local_subnets") or [])
    if explicit:
        return _dedupe_preserve_order(explicit)

    mode = str(integration.get("service_local_subnets_mode") or "customer_facing_public_ip_loopback").strip()
    if mode == "customer_facing_public_ip_loopback":
        return _resolve_bundle_service_reachable_subnets(bundle)
    raise ValueError(f"unsupported integration.service_local_subnets_mode: {mode}")


def _device_loopback_ip(bundle: dict[str, Any], device: dict[str, Any]) -> str:
    return str(device.get("customer_loopback_ip") or bundle["sot"]["identities"]["customer_loopback_ip"])


def _device_peer_public_ip(bundle: dict[str, Any], device: dict[str, Any], loopback_ip: str) -> str:
    candidate = str(device.get("customer_private_ip_address") or "").strip()
    if candidate:
        return candidate
    router_role = str(device.get("router_role") or "").strip()
    for router in list(bundle["operations"].get("customer_vpn_routers") or []):
        if str(router.get("role") or "").strip() != router_role:
            continue
        candidate = str(router.get("private_ip_address") or "").strip()
        if candidate:
            return candidate
    return candidate or loopback_ip


def _device_real_subnets(bundle: dict[str, Any], device: dict[str, Any]) -> list[str]:
    known_inside_identity = str(device.get("known_inside_identity") or "").strip()
    if known_inside_identity:
        return [known_inside_identity]
    return list(bundle["sot"]["addressing"]["customer_original_inside_space"] or [])


def _derive_translated_subnets(
    *,
    device_real_subnets: list[str],
    customer_original_inside_space: list[str],
    platform_assigned_inside_space: list[str],
) -> list[str]:
    if not device_real_subnets or not customer_original_inside_space or not platform_assigned_inside_space:
        return list(platform_assigned_inside_space)

    derived: list[str] = []
    for device_cidr in device_real_subnets:
        device_net = ipaddress.ip_network(device_cidr, strict=False)
        mapped_cidr = ""
        for source_cidr, target_cidr in zip(customer_original_inside_space, platform_assigned_inside_space):
            source_net = ipaddress.ip_network(source_cidr, strict=False)
            target_net = ipaddress.ip_network(target_cidr, strict=False)
            if device_net.version != source_net.version or source_net.version != target_net.version:
                continue
            if not device_net.subnet_of(source_net):
                continue
            offset = int(device_net.network_address) - int(source_net.network_address)
            mapped_network_address = ipaddress.ip_address(int(target_net.network_address) + offset)
            candidate = ipaddress.ip_network(f"{mapped_network_address}/{device_net.prefixlen}", strict=False)
            if candidate.subnet_of(target_net):
                mapped_cidr = str(candidate)
                break
        derived.append(mapped_cidr or device_cidr)
    return derived


def _customer_name_for_device(bundle: dict[str, Any], integration: dict[str, Any], device: dict[str, Any], index: int) -> str:
    base_name = str(integration.get("customer_name") or f"{bundle['sot']['service_id']}-backend")
    template = str(integration.get("customer_name_template") or "").strip()
    context = {
        "service_id": bundle["sot"]["service_id"],
        "customer_id": bundle["sot"]["customer_id"],
        "device_name": device["name"],
        "router_role": device["router_role"],
        "index": index,
    }
    if template:
        return template.format(**context)
    devices = list(bundle["sot"]["customer_devices"] or [])
    if len(devices) == 1:
        return base_name
    return f"{base_name}-{_sanitize(str(device['router_role']))}"


def _backend_psk_secret_ref_for_device(bundle: dict[str, Any], integration: dict[str, Any], device: dict[str, Any], index: int, customer_name: str) -> str:
    template = str(integration.get("backend_psk_secret_ref_template") or "").strip()
    context = {
        "service_id": bundle["sot"]["service_id"],
        "customer_id": bundle["sot"]["customer_id"],
        "device_name": device["name"],
        "router_role": device["router_role"],
        "index": index,
        "customer_name": customer_name,
    }
    if template:
        return template.format(**context)
    base_ref = str(integration.get("backend_psk_secret_ref") or "").strip()
    if not base_ref:
        raise ValueError("integration.backend_psk_secret_ref or backend_psk_secret_ref_template is required")
    devices = list(bundle["sot"]["customer_devices"] or [])
    if len(devices) == 1:
        return base_ref
    return f"{base_ref}-{_sanitize(str(device['router_role']))}"


def build_backend_customer_request(
    bundle: dict[str, Any],
    integration: dict[str, Any],
    *,
    device: dict[str, Any] | None = None,
    index: int = 1,
) -> dict[str, Any]:
    selected_device = device or list(bundle["sot"]["customer_devices"] or [])[0]
    customer_name = _customer_name_for_device(bundle, integration, selected_device, index)
    service_local_subnets = _resolve_service_local_subnets(bundle, integration)
    backend_public_loopback = _resolve_selected_backend_public_loopback(bundle)
    psk_secret_ref = _backend_psk_secret_ref_for_device(bundle, integration, selected_device, index, customer_name)
    customer_loopback_ip = _device_loopback_ip(bundle, selected_device)
    customer_peer_public_ip = _device_peer_public_ip(bundle, selected_device, customer_loopback_ip)
    customer_original_inside_space = list(bundle["sot"]["addressing"]["customer_original_inside_space"] or [])
    platform_assigned_inside_space = list(bundle["sot"]["addressing"]["platform_assigned_inside_space"] or [])
    device_real_subnets = _device_real_subnets(bundle, selected_device)
    device_translated_subnets = _derive_translated_subnets(
        device_real_subnets=device_real_subnets,
        customer_original_inside_space=customer_original_inside_space,
        platform_assigned_inside_space=platform_assigned_inside_space,
    )
    translation_mode = str(bundle["sot"]["addressing"]["translation_mode"] or "no_translation")
    backend_public_loopback_cidr = _as_host_cidr(backend_public_loopback)
    downstream_service_subnets = [subnet for subnet in service_local_subnets if _as_host_cidr(subnet) != backend_public_loopback_cidr]
    downstream_route_via = str(integration.get("outside_nat_route_via") or "").strip()
    downstream_route_dev = str(integration.get("outside_nat_route_dev") or "").strip()

    request: dict[str, Any] = {
        "schema_version": 1,
        "customer": {
            "name": customer_name,
            "peer": {
                "public_ip": customer_peer_public_ip,
                "remote_id": customer_loopback_ip,
                "psk_secret_ref": psk_secret_ref,
            },
            "selectors": {
                "local_subnets": service_local_subnets,
                "remote_subnets": device_real_subnets,
            },
            "ipsec": dict(integration.get("ipsec") or {}),
            "dynamic_provisioning": {
                "enabled": False,
            },
        },
    }

    request["customer"]["ipsec"].setdefault("local_id", backend_public_loopback)

    ipsec_initiation = integration.get("ipsec_initiation")
    if isinstance(ipsec_initiation, dict) and ipsec_initiation:
        request["customer"]["ipsec"]["initiation"] = ipsec_initiation

    if translation_mode not in {"disabled", "no_translation"}:
        request["customer"]["post_ipsec_nat"] = {
            "enabled": True,
            "mode": str((integration.get("post_ipsec_nat") or {}).get("mode") or "netmap"),
            "mapping_strategy": str((integration.get("post_ipsec_nat") or {}).get("mapping_strategy") or "one_to_one"),
            "real_subnets": device_real_subnets,
            "translated_subnets": device_translated_subnets,
            "core_subnets": service_local_subnets,
            "tcp_mss_clamp": int((integration.get("post_ipsec_nat") or {}).get("tcp_mss_clamp") or 1360),
        }
    else:
        request["customer"]["post_ipsec_nat"] = {"enabled": False, "mode": "disabled"}
        if downstream_route_via and downstream_service_subnets:
            request["customer"]["outside_nat"] = {
                "enabled": True,
                "mode": "netmap",
                "mapping_strategy": "one_to_one",
                "real_subnets": downstream_service_subnets,
                "translated_subnets": downstream_service_subnets,
                "route_via": downstream_route_via,
                "route_dev": downstream_route_dev or "ens36",
            }
        else:
            request["customer"]["outside_nat"] = {"enabled": False, "mode": "disabled"}

    return request


def build_backend_customer_requests(bundle: dict[str, Any], integration: dict[str, Any]) -> list[dict[str, Any]]:
    requests = []
    for index, device in enumerate(bundle["sot"]["customer_devices"], start=1):
        customer_name = _customer_name_for_device(bundle, integration, device, index)
        requests.append(
            {
                "device_name": device["name"],
                "router_role": device["router_role"],
                "customer_name": customer_name,
                "request": build_backend_customer_request(bundle, integration, device=device, index=index),
            }
        )
    return requests


def build_backend_integration_summary(
    *,
    bundle: dict[str, Any],
    integration: dict[str, Any],
    request_records: list[dict[str, Any]],
) -> dict[str, Any]:
    service_local_subnets = _resolve_service_local_subnets(bundle, integration)
    validation_ok = all(record.get("validation_ok") for record in request_records)
    deploy_dry_run_ok = all(record.get("deploy_dry_run_ok") for record in request_records)
    live_gate_allow = all(((record.get("deploy_plan") or {}).get("live_gate") or {}).get("allow_live_apply_now") for record in request_records)
    backend_headend_family = next(
        (
            ((record.get("deploy_plan") or {}).get("selected_targets") or {}).get("headend_family")
            or ((((record.get("deploy_plan") or {}).get("package") or {}).get("customer")) or {}).get("backend_cluster")
            for record in request_records
            if record.get("deploy_plan")
        ),
        None,
    )
    generated_request_paths = [record["request_path"] for record in request_records]
    backend_customer_names = [record["customer_name"] for record in request_records]
    customer_loopbacks = [record["customer_loopback_ip"] for record in request_records]
    customer_peer_public_ips = [record["customer_peer_public_ip"] for record in request_records]
    device_summaries = [
        {
            "device_name": record["device_name"],
            "router_role": record["router_role"],
            "customer_name": record["customer_name"],
            "customer_loopback_ip": record["customer_loopback_ip"],
            "customer_peer_public_ip": record["customer_peer_public_ip"],
            "request_path": record["request_path"],
            "validation_ok": record["validation_ok"],
            "deploy_dry_run_ok": record["deploy_dry_run_ok"],
        }
        for record in request_records
    ]
    return {
        "integration_type": "scenario1_backend_reuse",
        "service_id": bundle["sot"]["service_id"],
        "customer_id": bundle["sot"]["customer_id"],
        "environment": integration.get("environment"),
        "generated_request_path": generated_request_paths[0] if generated_request_paths else None,
        "generated_request_paths": generated_request_paths,
        "validation_ok": validation_ok,
        "deploy_dry_run_ok": deploy_dry_run_ok,
        "deploy_status": "dry_run_ready" if deploy_dry_run_ok else "failed",
        "backend_headend_family": backend_headend_family,
        "backend_customer_name": backend_customer_names[0] if backend_customer_names else None,
        "backend_customer_names": backend_customer_names,
        "service_local_subnets": service_local_subnets,
        "customer_loopback_backend_identity": customer_loopbacks[0] if customer_loopbacks else None,
        "customer_loopback_backend_identities": customer_loopbacks,
        "customer_peer_public_ip": customer_peer_public_ips[0] if customer_peer_public_ips else None,
        "customer_peer_public_ips": customer_peer_public_ips,
        "customer_facing_public_ip": _resolve_selected_backend_public_loopback(bundle),
        "customer_router_count": len(request_records),
        "device_summaries": device_summaries,
        "notes": [
            "Backend customer requests are generated per customer router and handed to the existing deploy_customer dry-run flow.",
            "peer.public_ip follows the customer router WAN address while peer.remote_id stays pinned to the customer loopback identity.",
            "No muxer/backend code changes are required for this reuse seam.",
            "Backend local_subnets are derived from the selected customer-facing public loopback unless explicitly overridden.",
        ],
        "live_gate": {"allow_live_apply_now": live_gate_allow},
    }
