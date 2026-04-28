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
        "package_type": "cgnat_aws_package",
        "version": 1,
        "scenario": "scenario1",
        "environment_name": bundle["operations"]["environment_name"],
        "service_id": bundle["sot"]["service_id"],
        "customer_id": bundle["sot"]["customer_id"],
        "customer_facing_public_ip": bundle["sot"]["backend_selection"]["customer_facing_public_ip"],
        "termination_public_loopback": bundle["sot"]["backend_selection"]["termination_public_loopback"],
        "preferred_backend_class": bundle["sot"]["backend_selection"]["preferred_class"],
        "selected_backend_name": selected_backend["name"],
        "selected_backend_gre_remote": selected_backend["gre_remote"],
        "deployment_model": {
            "cgnat_head_end": "single_instance",
            "cgnat_isp_head_end": "single_instance",
            "customer_model": "collapsed_1_to_1",
        },
    }


def _render_cgnat_head_end(bundle: dict[str, Any]) -> dict[str, Any]:
    operations = bundle["operations"]
    return {
        "role": "cgnat_head_end",
        "instance_name": operations["cgnat_head_end"]["instance_name"],
        "instance_type": operations["cgnat_head_end"]["instance_type"],
        "subnet_id": operations["cgnat_head_end"]["subnet_id"],
        "public_eip_allocation_id": operations["cgnat_head_end"]["public_eip_allocation_id"],
        "interfaces": {
            "outer_tunnel_interface": operations["cgnat_head_end"]["outer_tunnel_interface"],
            "gre_source_interface": operations["cgnat_head_end"]["gre_source_interface"],
        },
        "placement_rule": "must_run_only_in_subnet-04a6b7f3a3855d438",
    }


def _render_cgnat_isp_head_end(bundle: dict[str, Any]) -> dict[str, Any]:
    operations = bundle["operations"]
    return {
        "role": "cgnat_isp_head_end",
        "instance_name": operations["cgnat_isp_head_end"]["instance_name"],
        "instance_type": operations["cgnat_isp_head_end"]["instance_type"],
        "subnets": {
            "transit_subnet_id": operations["cgnat_isp_head_end"]["transit_subnet_id"],
            "customer_subnet_id": operations["cgnat_isp_head_end"]["customer_subnet_id"],
        },
        "interfaces": {
            "outer_tunnel_source_interface": operations["cgnat_isp_head_end"]["outer_tunnel_source_interface"],
            "customer_facing_interface": operations["cgnat_isp_head_end"]["customer_facing_interface"],
        },
        "placement_rule": "must_span_transit_and_customer_subnets",
    }


def _render_dependencies(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "aws": bundle["operations"]["aws"],
        "backend_vpn_head_ends": bundle["operations"]["backend_vpn_head_ends"],
        "gre_inventory": bundle["operations"]["gre_inventory"],
        "certificates": bundle["operations"]["certificates"],
    }


def _render_deployment_order() -> dict[str, Any]:
    return {
        "steps": [
            {
                "id": 1,
                "name": "deploy_cgnat_head_end",
                "description": "Create the CGNAT HEAD END instance in the approved transit subnet and attach the public EIP.",
            },
            {
                "id": 2,
                "name": "deploy_cgnat_isp_head_end",
                "description": "Create the CGNAT ISP HEAD END instance across the approved transit and customer-facing subnets.",
            },
            {
                "id": 3,
                "name": "prepare_server_side_configuration",
                "description": "Hand off to the server-side package to configure the outer tunnel, GRE handoff, and service path.",
            },
        ]
    }


def _render_readme(bundle: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# CGNAT AWS Package",
            "",
            f"- Service ID: `{bundle['sot']['service_id']}`",
            f"- Environment: `{bundle['operations']['environment_name']}`",
            "- Scenario: `scenario1`",
            "",
            "## Contents",
            "",
            "- `package-manifest.json`: AWS deployment package summary",
            "- `cgnat-head-end.json`: CGNAT HEAD END infra shape",
            "- `cgnat-isp-head-end.json`: CGNAT ISP HEAD END infra shape",
            "- `dependencies.json`: required external inventory and certificate refs",
            "- `deployment-order.json`: recommended deployment sequence",
            "",
            "## Notes",
            "",
            "- This package is AWS-side only.",
            "- It does not apply server-side tunnel or GRE configuration.",
            "- It assumes Scenario 1 and the existing backend VPN public target model.",
            "",
        ]
    )


def main() -> int:
    sys.path.insert(0, str(_framework_src_root()))

    from cgnat.bundle import dump_json, dump_text, load_bundle
    from cgnat.validate import validate_bundle

    parser = argparse.ArgumentParser(description="Render AWS-side deployment package artifacts from a CGNAT bundle.")
    parser.add_argument("bundle", help="Path to the deployment bundle JSON file.")
    parser.add_argument("output_dir", help="Directory to write the AWS deployment package.")
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
    dump_json(output_dir / "dependencies.json", _render_dependencies(bundle))
    dump_json(output_dir / "deployment-order.json", _render_deployment_order())
    dump_text(output_dir / "README.md", _render_readme(bundle))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
