from __future__ import annotations

import argparse
import ipaddress
import sys
from pathlib import Path
from typing import Any


def _framework_src_root() -> Path:
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent.parent / "framework" / "src"


def _selected_backend_entry(bundle: dict[str, Any]) -> dict[str, Any]:
    preferred_class = bundle["sot"]["backend_selection"]["preferred_class"]
    loopback = bundle["sot"]["backend_selection"]["termination_public_loopback"]
    backend_pool = list(bundle["operations"]["backend_vpn_head_ends"].get(preferred_class) or [])
    for entry in backend_pool:
        if isinstance(entry, dict) and entry.get("public_loopback") == loopback:
            normalized = dict(entry)
            normalized["gre_remote"] = str(entry.get("cgnat_handoff_remote") or entry.get("gre_remote") or "").strip()
            return normalized
    return {
        "name": f"unmatched-{preferred_class}-backend",
        "gre_remote": "",
        "cgnat_handoff_remote": "",
        "public_loopback": loopback,
    }


def _router_index(operations: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(router["role"]): router
        for router in list(operations.get("customer_vpn_routers") or [])
        if isinstance(router, dict) and router.get("role")
    }


def _resolved_head_end_public_ip(operations: dict[str, Any]) -> str | None:
    head_end = dict(operations.get("cgnat_head_end") or {})
    for field in ("allocated_public_ip", "resolved_public_ip", "public_ip"):
        value = str(head_end.get(field) or "").strip()
        if value:
            return value
    return None


def _device_outer_identity(bundle: dict[str, Any], device: dict[str, Any]) -> str:
    explicit = str(device.get("outer_tunnel_identity_ref") or "").strip()
    if explicit:
        return explicit
    return f"{device['router_role']}/{bundle['operations']['environment_name']}/{bundle['sot']['customer_id']}"


def _router_outer_certificate_ref(bundle: dict[str, Any], role: str) -> str:
    certificates = dict(bundle["operations"].get("certificates") or {})
    per_router = dict(certificates.get("customer_router_outer_client_cert_refs") or {})
    explicit = str(per_router.get(role) or "").strip()
    if explicit:
        return explicit
    return f"local-pki://{bundle['operations']['environment_name']}/{role}-outer-client"


def _service_reachable_subnets(bundle: dict[str, Any]) -> list[str]:
    backend_selection = dict(bundle["sot"].get("backend_selection") or {})
    configured = list(backend_selection.get("service_reachable_subnets") or [])
    if configured:
        return [str(value) for value in configured]
    return [f"{bundle['sot']['backend_selection']['customer_facing_public_ip']}/32"]


def _customer_facing_public_selector(bundle: dict[str, Any]) -> str:
    return f"{bundle['sot']['backend_selection']['customer_facing_public_ip']}/32"


def _derive_translated_identity(
    *,
    known_inside_identity: str,
    customer_original_inside_space: list[str],
    platform_assigned_inside_space: list[str],
) -> str:
    device_net = ipaddress.ip_network(known_inside_identity, strict=False)
    for source_cidr, target_cidr in zip(customer_original_inside_space, platform_assigned_inside_space):
        source_net = ipaddress.ip_network(source_cidr, strict=False)
        target_net = ipaddress.ip_network(target_cidr, strict=False)
        if device_net.version != source_net.version or source_net.version != target_net.version:
            continue
        if not device_net.subnet_of(source_net):
            continue
        offset = int(device_net.network_address) - int(source_net.network_address)
        translated_network_address = ipaddress.ip_address(int(target_net.network_address) + offset)
        candidate = ipaddress.ip_network(f"{translated_network_address}/{device_net.prefixlen}", strict=False)
        if candidate.subnet_of(target_net):
            return str(candidate)
    return known_inside_identity


def _downstream_validation_targets(bundle: dict[str, Any]) -> dict[str, Any] | None:
    service_reachable_subnets = _service_reachable_subnets(bundle)
    customer_facing_selector = _customer_facing_public_selector(bundle)
    downstream_subnets = [subnet for subnet in service_reachable_subnets if subnet != customer_facing_selector]
    if not downstream_subnets:
        return None

    customer_original_inside_space = list(bundle["sot"]["addressing"].get("customer_original_inside_space") or [])
    platform_assigned_inside_space = list(bundle["sot"]["addressing"].get("platform_assigned_inside_space") or [])
    translated_sources: list[dict[str, str]] = []
    for device in bundle["sot"]["customer_devices"]:
        known_inside_identity = str(device["known_inside_identity"])
        translated_sources.append(
            {
                "role": str(device["router_role"]),
                "known_inside_identity": known_inside_identity,
                "translated_identity": _derive_translated_identity(
                    known_inside_identity=known_inside_identity,
                    customer_original_inside_space=customer_original_inside_space,
                    platform_assigned_inside_space=platform_assigned_inside_space,
                ),
            }
        )
    return {
        "mode": "smartgateway_encrypts_optional_reply",
        "success_signal": "outbound_encrypts_visible_for_all_translated_sources",
        "reply_required": False,
        "downstream_reachable_subnets": downstream_subnets,
        "translated_sources": translated_sources,
    }


def _render_package_manifest(bundle: dict[str, Any]) -> dict[str, Any]:
    selected_backend = _selected_backend_entry(bundle)
    return {
        "package_type": "cgnat_server_package",
        "version": 1,
        "scenario": "scenario1",
        "service_id": bundle["sot"]["service_id"],
        "customer_id": bundle["sot"]["customer_id"],
        "customer_facing_public_ip": bundle["sot"]["backend_selection"]["customer_facing_public_ip"],
        "termination_public_loopback": bundle["sot"]["backend_selection"]["termination_public_loopback"],
        "selected_backend_name": selected_backend["name"],
        "selected_backend_gre_remote": selected_backend["gre_remote"],
        "customer_router_count": len(bundle["sot"]["customer_devices"]),
    }


def _render_cgnat_head_end(bundle: dict[str, Any]) -> dict[str, Any]:
    framework = bundle["framework"]
    operations = bundle["operations"]
    sot = bundle["sot"]
    selected_backend = _selected_backend_entry(bundle)
    accepted_outer_peers: list[dict[str, Any]] = []
    for device in sot["customer_devices"]:
        role = str(device["router_role"])
        router = _router_index(operations)[role]
        accepted_outer_peers.append(
            {
                "role": role,
                "device_name": str(device["name"]),
                "connection_name": f"{sot['service_id']}-{role}-outer",
                "remote_identity_ref": _device_outer_identity(bundle, device),
                "remote_selector": f"{router['private_ip_address']}/32",
            }
        )
    return {
        "role": "cgnat_head_end",
        "outer_tunnel_listener": {
            "auth_method": framework["topology"]["outer_tunnel"]["auth_method"],
            "peer_ip_mode": framework["topology"]["outer_tunnel"]["peer_ip_mode"],
            "termination_interface": operations["cgnat_head_end"]["outer_tunnel_interface"],
            "server_certificate_ref": operations["certificates"]["cgnat_head_end_server_cert_ref"],
            "local_identity": f"cgnat-head-end/{sot['service_id']}",
            "local_selector": _customer_facing_public_selector(bundle),
        },
        "accepted_outer_peers": accepted_outer_peers,
        "gre_handoff": {
            "transport": framework["topology"]["handoff"]["transport"],
            "inventory_ref": operations["gre_inventory"]["inventory_ref"],
            "assignment_mode": operations["gre_inventory"]["assignment_mode"],
            "source_interface": operations["cgnat_head_end"]["gre_source_interface"],
            "selected_backend_name": selected_backend["name"],
            "selected_backend_gre_remote": selected_backend["gre_remote"],
        },
        "backend_service_target": {
            "preferred_class": sot["backend_selection"]["preferred_class"],
            "customer_facing_public_ip": sot["backend_selection"]["customer_facing_public_ip"],
            "termination_public_loopback": sot["backend_selection"]["termination_public_loopback"],
        },
    }


def _render_cgnat_isp_head_end(bundle: dict[str, Any]) -> dict[str, Any]:
    operations = bundle["operations"]
    sot = bundle["sot"]
    return {
        "role": "cgnat_isp_head_end",
        "transport_role": "nat_and_forwarding_only",
        "customer_service_path": {
            "customer_facing_interface": operations["cgnat_isp_head_end"]["customer_facing_interface"],
            "customer_facing_private_ip": operations["cgnat_isp_head_end"]["customer_facing_private_ip"],
            "customer_devices": sot["customer_devices"],
            "router_roles": [device["router_role"] for device in sot["customer_devices"]],
        },
        "transit_contract": {
            "required_forwarding": True,
            "required_source_dest_check_disabled": True,
        },
    }


def _render_customer_vpn_routers(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    framework = bundle["framework"]
    operations = bundle["operations"]
    sot = bundle["sot"]
    router_by_role = _router_index(operations)
    remote_selectors = _service_reachable_subnets(bundle)
    routers: list[dict[str, Any]] = []
    for device in sot["customer_devices"]:
        role = device["router_role"]
        router = router_by_role[role]
        routers.append(
            {
                "role": role,
                "instance_name": router["instance_name"],
                "customer_facing_interface": router["customer_facing_interface"],
                "private_ip_address": router["private_ip_address"],
                "default_gateway_ip": operations["cgnat_isp_head_end"]["customer_facing_private_ip"],
                "outer_tunnel": {
                    "auth_method": framework["topology"]["outer_tunnel"]["auth_method"],
                    "peer_ip_mode": framework["topology"]["outer_tunnel"]["peer_ip_mode"],
                    "source_interface": router["customer_facing_interface"],
                    "client_certificate_ref": _router_outer_certificate_ref(bundle, role),
                    "local_identity_ref": _device_outer_identity(bundle, device),
                    "local_selector": f"{router['private_ip_address']}/32",
                    "remote_identity": f"cgnat-head-end/{sot['service_id']}",
                    "remote_public_ip": _resolved_head_end_public_ip(operations),
                    "remote_selector": _customer_facing_public_selector(bundle),
                },
                "inner_vpn": {
                    "auth_method": framework["topology"]["inner_vpn"]["auth_method"],
                    "required_initiator": "customer_vpn_router",
                    "required_responder": "backend_vpn_head_end",
                    "customer_device_name": device["name"],
                    "customer_loopback_ip": device.get("customer_loopback_ip") or sot["identities"]["customer_loopback_ip"],
                    "known_inside_identity": device["known_inside_identity"],
                    "secret_ref": device["inner_vpn_auth_ref"],
                    "remote_public_ip": sot["backend_selection"]["customer_facing_public_ip"],
                    "termination_public_loopback": sot["backend_selection"]["termination_public_loopback"],
                    "remote_selectors": remote_selectors,
                },
            }
        )
    return routers


def _render_backend_expectations(bundle: dict[str, Any]) -> dict[str, Any]:
    sot = bundle["sot"]
    selected_backend = _selected_backend_entry(bundle)
    return {
        "preferred_class": sot["backend_selection"]["preferred_class"],
        "selected_backend_name": selected_backend["name"],
        "selected_backend_public_loopback": selected_backend["public_loopback"],
        "selected_backend_gre_remote": selected_backend["gre_remote"],
        "termination_public_loopback": sot["backend_selection"]["termination_public_loopback"],
        "customer_facing_public_ip": sot["backend_selection"]["customer_facing_public_ip"],
        "service_reachable_subnets": _service_reachable_subnets(bundle),
        "translation": {
            "mode": sot["addressing"]["translation_mode"],
            "customer_original_inside_space": sot["addressing"]["customer_original_inside_space"],
            "platform_assigned_inside_space": sot["addressing"]["platform_assigned_inside_space"],
        },
    }


def _render_validation_targets(bundle: dict[str, Any]) -> dict[str, Any]:
    customer_routers = [
        {
            "role": device["router_role"],
            "name": device["name"],
            "customer_loopback_ip": device.get("customer_loopback_ip") or bundle["sot"]["identities"]["customer_loopback_ip"],
            "known_inside_identity": device["known_inside_identity"],
        }
        for device in bundle["sot"]["customer_devices"]
    ]
    required_checks = [
        "customer_router_outer_tunnels_established",
        "customer_router_inner_tunnels_established",
        "backend_responder_behavior_confirmed",
        "request_path_visible_on_outer_tunnel",
        "request_path_visible_on_gre_handoff",
        "reply_path_visible_on_outer_tunnel",
        "reply_path_visible_on_gre_handoff",
        "customer_facing_public_ip_matches_termination_public_loopback",
    ]
    downstream_validation = _downstream_validation_targets(bundle)
    if downstream_validation:
        required_checks.append("smartgateway_downstream_encrypts_visible_for_translated_sources")

    rendered = {
        "scenario": "scenario1",
        "required_checks": required_checks,
        "observability_points": [
            "customer_vpn_router_1",
            "customer_vpn_router_2",
            "cgnat_isp_head_end",
            "cgnat_head_end_outer_tunnel_path",
            "cgnat_head_end_gre_path",
            "selected_backend_head_end",
        ],
        "customer_routers": customer_routers,
        "customer_facing_public_ip": bundle["sot"]["backend_selection"]["customer_facing_public_ip"],
    }
    if downstream_validation:
        rendered["downstream_validation"] = downstream_validation
    return rendered


def _render_readme(bundle: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# CGNAT Server Package",
            "",
            f"- Service ID: `{bundle['sot']['service_id']}`",
            f"- Environment: `{bundle['operations']['environment_name']}`",
            "- Scenario: `scenario1`",
            "",
            "## Contents",
            "",
            "- `package-manifest.json`: server-side package summary",
            "- `cgnat-head-end.json`: outer tunnel and GRE handoff shape",
            "- `cgnat-isp-head-end.json`: ISP-side outer tunnel and transit role shape",
            "- `customer-vpn-routers.json`: customer-router outer and inner tunnel shapes",
            "- `backend-expectations.json`: backend target and translation expectations",
            "- `validation-targets.json`: required validation checks and observability points",
            "",
            "## Notes",
            "",
            "- This package is server-side only.",
            "- It does not create AWS resources.",
            "- Customer routers own both the outer cert tunnel and the inner PSK tunnel.",
            "- The ISP node acts as NAT/transit only in the corrected Scenario 1 model.",
            "",
        ]
    )


def main() -> int:
    sys.path.insert(0, str(_framework_src_root()))

    from cgnat.bundle import dump_json, dump_text, ensure_path_within_cgnat, load_bundle
    from cgnat.validate import validate_bundle

    parser = argparse.ArgumentParser(description="Render server-side configuration package artifacts from a CGNAT bundle.")
    parser.add_argument("bundle", help="Path to the deployment bundle JSON file.")
    parser.add_argument("output_dir", help="Directory to write the server-side package.")
    args = parser.parse_args()

    bundle = load_bundle(args.bundle)
    validation = validate_bundle(bundle)
    if not validation["ok"]:
        return 1

    output_dir = ensure_path_within_cgnat(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    dump_json(output_dir / "package-manifest.json", _render_package_manifest(bundle))
    dump_json(output_dir / "cgnat-head-end.json", _render_cgnat_head_end(bundle))
    dump_json(output_dir / "cgnat-isp-head-end.json", _render_cgnat_isp_head_end(bundle))
    dump_json(output_dir / "customer-vpn-routers.json", _render_customer_vpn_routers(bundle))
    dump_json(output_dir / "backend-expectations.json", _render_backend_expectations(bundle))
    dump_json(output_dir / "validation-targets.json", _render_validation_targets(bundle))
    dump_text(output_dir / "README.md", _render_readme(bundle))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
