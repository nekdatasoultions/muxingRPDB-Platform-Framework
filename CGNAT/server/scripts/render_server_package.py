from __future__ import annotations

import argparse
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
    return {
        "role": "cgnat_head_end",
        "outer_tunnel": {
            "auth_method": framework["topology"]["outer_tunnel"]["auth_method"],
            "peer_ip_mode": framework["topology"]["outer_tunnel"]["peer_ip_mode"],
            "termination_interface": operations["cgnat_head_end"]["outer_tunnel_interface"],
            "server_certificate_ref": operations["certificates"]["cgnat_head_end_server_cert_ref"],
            "local_identity": f"cgnat-head-end/{sot['service_id']}",
            "remote_identity_ref": sot["identities"]["outer_tunnel_identity_ref"],
        },
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
    framework = bundle["framework"]
    operations = bundle["operations"]
    sot = bundle["sot"]
    return {
        "role": "cgnat_isp_head_end",
        "outer_tunnel": {
            "auth_method": framework["topology"]["outer_tunnel"]["auth_method"],
            "peer_ip_mode": framework["topology"]["outer_tunnel"]["peer_ip_mode"],
            "source_interface": operations["cgnat_isp_head_end"]["outer_tunnel_source_interface"],
            "client_certificate_ref": operations["certificates"]["cgnat_isp_head_end_client_cert_ref"],
            "local_identity_ref": sot["identities"]["outer_tunnel_identity_ref"],
            "remote_identity": f"cgnat-head-end/{sot['service_id']}",
            "remote_public_ip": _resolved_head_end_public_ip(operations),
        },
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
    return {
        "scenario": "scenario1",
        "required_checks": [
            "outer_tunnel_established",
            "customer_router_inner_tunnels_established",
            "backend_responder_behavior_confirmed",
            "request_path_visible_on_outer_tunnel",
            "request_path_visible_on_gre_handoff",
            "reply_path_visible_on_outer_tunnel",
            "reply_path_visible_on_gre_handoff",
            "customer_facing_public_ip_matches_termination_public_loopback",
        ],
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
            "- `customer-vpn-routers.json`: customer-router inner tunnel shapes",
            "- `backend-expectations.json`: backend target and translation expectations",
            "- `validation-targets.json`: required validation checks and observability points",
            "",
            "## Notes",
            "",
            "- This package is server-side only.",
            "- It does not create AWS resources.",
            "- The ISP node owns the outer tunnel; the customer routers own the inner tunnels.",
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
