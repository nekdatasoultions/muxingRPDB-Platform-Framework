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
            return entry
    return {
        "name": f"unmatched-{preferred_class}-backend",
        "gre_remote": "",
        "public_loopback": loopback,
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
        },
        "customer_service_path": {
            "customer_facing_interface": operations["cgnat_isp_head_end"]["customer_facing_interface"],
            "customer_devices": sot["customer_devices"],
            "inner_customer_identity": sot["identities"]["inner_customer_identity"],
            "customer_loopback_ip": sot["identities"]["customer_loopback_ip"],
        },
        "inner_vpn_contract": {
            "auth_method": framework["topology"]["inner_vpn"]["auth_method"],
            "required_initiator": "customer_device",
            "required_responder": "backend_vpn_head_end",
        },
    }


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
    return {
        "scenario": "scenario1",
        "required_checks": [
            "outer_tunnel_established",
            "inner_tunnel_established_customer_initiated",
            "backend_responder_behavior_confirmed",
            "request_path_visible_on_outer_tunnel",
            "request_path_visible_on_gre_handoff",
            "reply_path_visible_on_outer_tunnel",
            "reply_path_visible_on_gre_handoff",
            "customer_facing_public_ip_matches_termination_public_loopback",
        ],
        "observability_points": [
            "customer_device",
            "cgnat_isp_head_end",
            "cgnat_head_end_outer_tunnel_path",
            "cgnat_head_end_gre_path",
            "selected_backend_head_end",
        ],
        "customer_loopback_ip": bundle["sot"]["identities"]["customer_loopback_ip"],
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
            "- `cgnat-isp-head-end.json`: ISP-side path and inner VPN role shape",
            "- `backend-expectations.json`: backend target and translation expectations",
            "- `validation-targets.json`: required validation checks and observability points",
            "",
            "## Notes",
            "",
            "- This package is server-side only.",
            "- It does not create AWS resources.",
            "- It assumes the current Scenario 1 contract and existing backend public target.",
            "",
        ]
    )


def main() -> int:
    sys.path.insert(0, str(_framework_src_root()))

    from cgnat.bundle import dump_json, dump_text, load_bundle
    from cgnat.validate import validate_bundle

    parser = argparse.ArgumentParser(description="Render server-side configuration package artifacts from a CGNAT bundle.")
    parser.add_argument("bundle", help="Path to the deployment bundle JSON file.")
    parser.add_argument("output_dir", help="Directory to write the server-side package.")
    args = parser.parse_args()

    bundle = load_bundle(args.bundle)
    validation = validate_bundle(bundle)
    if not validation["ok"]:
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    dump_json(output_dir / "package-manifest.json", _render_package_manifest(bundle))
    dump_json(output_dir / "cgnat-head-end.json", _render_cgnat_head_end(bundle))
    dump_json(output_dir / "cgnat-isp-head-end.json", _render_cgnat_isp_head_end(bundle))
    dump_json(output_dir / "backend-expectations.json", _render_backend_expectations(bundle))
    dump_json(output_dir / "validation-targets.json", _render_validation_targets(bundle))
    dump_text(output_dir / "README.md", _render_readme(bundle))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
