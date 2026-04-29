from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _framework_src_root() -> Path:
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent.parent / "framework" / "src"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_package(package_dir: Path) -> dict[str, Any]:
    return {
        "manifest": _load_json(package_dir / "package-manifest.json"),
        "cgnat_head_end": _load_json(package_dir / "cgnat-head-end.json"),
        "cgnat_isp_head_end": _load_json(package_dir / "cgnat-isp-head-end.json"),
        "backend_expectations": _load_json(package_dir / "backend-expectations.json"),
        "validation_targets": _load_json(package_dir / "validation-targets.json"),
    }


def _service_id(package: dict[str, Any]) -> str:
    return package["manifest"]["service_id"]


def _runtime_inputs(package: dict[str, Any]) -> dict[str, Any]:
    service_id = _service_id(package)
    head_outer = package["cgnat_head_end"]["outer_tunnel"]
    isp_outer = package["cgnat_isp_head_end"]["outer_tunnel"]
    head_gre = package["cgnat_head_end"]["gre_handoff"]
    backend = package["backend_expectations"]

    return {
        "service_id": service_id,
        "runtime_style": {
            "ipsec": "strongswan_swanctl",
            "routing": "linux_iproute2",
        },
        "certificate_material": {
            "head_end_server": {
                "certificate_ref": head_outer["server_certificate_ref"],
                "certificate_path": f"/etc/swanctl/x509/{service_id}-head-end.crt",
                "private_key_path": f"/etc/swanctl/private/{service_id}-head-end.key",
            },
            "isp_head_end_client": {
                "certificate_ref": isp_outer["client_certificate_ref"],
                "certificate_path": f"/etc/swanctl/x509/{service_id}-isp-client.crt",
                "private_key_path": f"/etc/swanctl/private/{service_id}-isp-client.key",
            },
            "outer_tunnel_ca": {
                "certificate_path": f"/etc/swanctl/x509ca/{service_id}-outer-ca.crt",
            },
        },
        "gre_runtime": {
            "gre_name": f"{service_id}-gre1",
            "source_interface": head_gre["source_interface"],
            "remote_ip": head_gre["selected_backend_gre_remote"],
            "termination_public_loopback": backend["termination_public_loopback"],
        },
    }


def _render_head_end_config(package: dict[str, Any]) -> dict[str, Any]:
    head_end = package["cgnat_head_end"]
    backend = package["backend_expectations"]
    return {
        "config_type": "scenario1_cgnat_head_end",
        "outer_tunnel": head_end["outer_tunnel"],
        "gre_handoff": head_end["gre_handoff"],
        "backend_service_target": head_end["backend_service_target"],
        "routing_expectations": {
            "selected_backend_name": backend["selected_backend_name"],
            "selected_backend_gre_remote": backend["selected_backend_gre_remote"],
            "termination_public_loopback": backend["termination_public_loopback"],
        },
    }


def _render_isp_head_end_config(package: dict[str, Any]) -> dict[str, Any]:
    isp_head_end = package["cgnat_isp_head_end"]
    return {
        "config_type": "scenario1_cgnat_isp_head_end",
        "outer_tunnel": isp_head_end["outer_tunnel"],
        "customer_service_path": isp_head_end["customer_service_path"],
        "inner_vpn_contract": isp_head_end["inner_vpn_contract"],
    }


def _render_backend_validation(package: dict[str, Any]) -> dict[str, Any]:
    return {
        "config_type": "scenario1_backend_validation",
        "backend_expectations": package["backend_expectations"],
        "validation_targets": package["validation_targets"],
    }


def _render_head_end_swanctl(package: dict[str, Any]) -> str:
    outer = package["cgnat_head_end"]["outer_tunnel"]
    runtime_inputs = _runtime_inputs(package)
    service_id = runtime_inputs["service_id"]
    cert_material = runtime_inputs["certificate_material"]["head_end_server"]
    return "\n".join(
        [
            f"# Scenario 1 CGNAT HEAD END outer-tunnel config for {service_id}",
            "# Target syntax: strongSwan swanctl.conf fragment",
            f"# Certificate reference: {cert_material['certificate_ref']}",
            f"# Outer-tunnel CA path: {runtime_inputs['certificate_material']['outer_tunnel_ca']['certificate_path']}",
            "",
            "secrets {",
            f"  {service_id}-head-end-rsa {{",
            f"    file = {cert_material['private_key_path']}",
            "  }",
            "}",
            "",
            "connections {",
            f"  {service_id}-outer {{",
            "    version = 2",
            "    local_addrs = %any",
            "    remote_addrs = %any",
            "    proposals = default",
            "    local {",
            "      auth = pubkey",
            f"      id = {outer['local_identity']}",
            f"      certs = {cert_material['certificate_path']}",
            "    }",
            "    remote {",
            "      auth = pubkey",
            f"      id = {outer['remote_identity_ref']}",
            "    }",
            "    children {",
            f"      {service_id}-outer-child {{",
            "        local_ts = 0.0.0.0/0",
            "        remote_ts = 0.0.0.0/0",
            "        start_action = trap",
            "      }",
            "    }",
            "  }",
            "}",
            "",
        ]
    )


def _render_isp_head_end_swanctl(package: dict[str, Any]) -> str:
    outer = package["cgnat_isp_head_end"]["outer_tunnel"]
    runtime_inputs = _runtime_inputs(package)
    service_id = runtime_inputs["service_id"]
    cert_material = runtime_inputs["certificate_material"]["isp_head_end_client"]
    return "\n".join(
        [
            f"# Scenario 1 CGNAT ISP HEAD END outer-tunnel config for {service_id}",
            "# Target syntax: strongSwan swanctl.conf fragment",
            f"# Certificate reference: {cert_material['certificate_ref']}",
            f"# Outer-tunnel CA path: {runtime_inputs['certificate_material']['outer_tunnel_ca']['certificate_path']}",
            "",
            "secrets {",
            f"  {service_id}-isp-client-rsa {{",
            f"    file = {cert_material['private_key_path']}",
            "  }",
            "}",
            "",
            "connections {",
            f"  {service_id}-outer {{",
            "    version = 2",
            "    local_addrs = %any",
            "    remote_addrs = %any",
            "    proposals = default",
            "    local {",
            "      auth = pubkey",
            f"      id = {outer['local_identity_ref']}",
            f"      certs = {cert_material['certificate_path']}",
            "    }",
            "    remote {",
            "      auth = pubkey",
            f"      id = {outer['remote_identity']}",
            "    }",
            "    children {",
            f"      {service_id}-outer-child {{",
            "        local_ts = 0.0.0.0/0",
            "        remote_ts = 0.0.0.0/0",
            "        start_action = start",
            "      }",
            "    }",
            "  }",
            "}",
            "",
        ]
    )


def _render_gre_script(package: dict[str, Any]) -> str:
    runtime_inputs = _runtime_inputs(package)
    gre = runtime_inputs["gre_runtime"]
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "# Scenario 1 GRE handoff setup",
            "# Target syntax: Linux iproute2 commands",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
            "source \"$SCRIPT_DIR/scenario1-runtime.env\"",
            "",
            "LOCAL_ADDR=\"$(ip -4 -o addr show dev \"$CGNAT_HEAD_END_GRE_SOURCE_INTERFACE\" | awk '{print $4}' | cut -d/ -f1 | head -n 1)\"",
            "if [[ -z \"$LOCAL_ADDR\" ]]; then",
            "  echo \"Unable to resolve IPv4 address for interface $CGNAT_HEAD_END_GRE_SOURCE_INTERFACE\" >&2",
            "  exit 1",
            "fi",
            "",
            "ip tunnel del \"$CGNAT_GRE_NAME\" 2>/dev/null || true",
            "ip tunnel add \"$CGNAT_GRE_NAME\" mode gre local \"$LOCAL_ADDR\" remote \"$CGNAT_BACKEND_GRE_REMOTE\" ttl 255",
            "ip link set \"$CGNAT_GRE_NAME\" up",
            "",
        ]
    )


def _render_route_script(package: dict[str, Any]) -> str:
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "# Scenario 1 backend route expectations",
            "# Target syntax: Linux iproute2 commands",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
            "source \"$SCRIPT_DIR/scenario1-runtime.env\"",
            "",
            "ip route replace \"${CGNAT_TERMINATION_PUBLIC_LOOPBACK}/32\" dev \"$CGNAT_GRE_NAME\"",
            "",
        ]
    )


def _render_runtime_env(package: dict[str, Any]) -> str:
    runtime_inputs = _runtime_inputs(package)
    cert_material = runtime_inputs["certificate_material"]
    gre_runtime = runtime_inputs["gre_runtime"]
    return "\n".join(
        [
            f"CGNAT_SERVICE_ID=\"{runtime_inputs['service_id']}\"",
            f"CGNAT_GRE_NAME=\"{gre_runtime['gre_name']}\"",
            f"CGNAT_HEAD_END_GRE_SOURCE_INTERFACE=\"{gre_runtime['source_interface']}\"",
            f"CGNAT_BACKEND_GRE_REMOTE=\"{gre_runtime['remote_ip']}\"",
            f"CGNAT_TERMINATION_PUBLIC_LOOPBACK=\"{gre_runtime['termination_public_loopback']}\"",
            f"CGNAT_HEAD_END_SERVER_CERT_REF=\"{cert_material['head_end_server']['certificate_ref']}\"",
            f"CGNAT_HEAD_END_SERVER_CERT_PATH=\"{cert_material['head_end_server']['certificate_path']}\"",
            f"CGNAT_HEAD_END_SERVER_KEY_PATH=\"{cert_material['head_end_server']['private_key_path']}\"",
            f"CGNAT_ISP_HEAD_END_CLIENT_CERT_REF=\"{cert_material['isp_head_end_client']['certificate_ref']}\"",
            f"CGNAT_ISP_HEAD_END_CLIENT_CERT_PATH=\"{cert_material['isp_head_end_client']['certificate_path']}\"",
            f"CGNAT_ISP_HEAD_END_CLIENT_KEY_PATH=\"{cert_material['isp_head_end_client']['private_key_path']}\"",
            f"CGNAT_OUTER_CA_CERT_PATH=\"{cert_material['outer_tunnel_ca']['certificate_path']}\"",
            "",
        ]
    )


def _render_validation_commands(package: dict[str, Any]) -> str:
    customer_loopback_ip = package["validation_targets"]["customer_loopback_ip"]
    customer_facing_public_ip = package["validation_targets"]["customer_facing_public_ip"]
    return "\n".join(
        [
            "# Scenario 1 Validation Commands",
            "",
            "These commands align with the chosen Scenario 1 runtime style: strongSwan for IPsec and Linux iproute2 for GRE/routing.",
            "",
            "## Required Validation Areas",
            "",
            "- outer tunnel established",
            "- customer-initiated inner tunnel established",
            "- backend responder behavior confirmed",
            "- GRE handoff visible",
            "- request and reply path visible",
            "",
            "## Example Checks",
            "",
            "On the CGNAT HEAD END:",
            "```powershell",
            "# verify outer tunnel state",
            "# verify GRE interface state",
            "# apply runtime inputs from scenario1-runtime.env before using host-side scripts",
            "# capture traffic for the customer-facing public IP",
            f"# target public IP: {customer_facing_public_ip}",
            "```",
            "",
            "On the customer side:",
            "```powershell",
            "# verify inner tunnel established from the customer side",
            f"# customer loopback identity: {customer_loopback_ip}",
            f"# destination public IP: {customer_facing_public_ip}",
            "```",
            "",
            "On the selected backend head end:",
            "```powershell",
            "# verify responder behavior",
            "# verify traffic arrives on the expected backend loopback/service target",
            "```",
            "",
        ]
    )


def main() -> int:
    sys.path.insert(0, str(_framework_src_root()))

    from cgnat.bundle import dump_json, dump_text, ensure_path_within_cgnat

    parser = argparse.ArgumentParser(description="Render concrete Scenario 1 server-side config artifacts from a CGNAT server package.")
    parser.add_argument("package_dir", help="Path to the rendered server package directory.")
    parser.add_argument("output_dir", help="Directory to write the Scenario 1 server config artifacts.")
    args = parser.parse_args()

    package_dir = Path(args.package_dir).resolve()
    output_dir = ensure_path_within_cgnat(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    package = _load_package(package_dir)

    dump_json(output_dir / "cgnat-head-end-config.json", _render_head_end_config(package))
    dump_json(output_dir / "cgnat-isp-head-end-config.json", _render_isp_head_end_config(package))
    dump_json(output_dir / "backend-validation.json", _render_backend_validation(package))
    dump_json(output_dir / "runtime-inputs.json", _runtime_inputs(package))
    dump_text(output_dir / "cgnat-head-end-swanctl.conf", _render_head_end_swanctl(package))
    dump_text(output_dir / "cgnat-isp-head-end-swanctl.conf", _render_isp_head_end_swanctl(package))
    dump_text(output_dir / "cgnat-head-end-gre.sh", _render_gre_script(package))
    dump_text(output_dir / "cgnat-head-end-routes.sh", _render_route_script(package))
    dump_text(output_dir / "scenario1-runtime.env", _render_runtime_env(package))
    dump_text(output_dir / "validation-commands.md", _render_validation_commands(package))
    dump_text(
        output_dir / "README.md",
        "\n".join(
            [
                "# Scenario 1 Server Config Artifacts",
                "",
                "- structured host-side artifacts generated from the server package",
                "- concrete strongSwan swanctl fragments for the outer tunnel",
                "- concrete Linux iproute2 scripts for GRE and route handling",
                "- runtime input manifest and shell environment file for apply-time values",
                "- validation guidance included",
                "- Scenario 1 runtime syntax is frozen to strongSwan + iproute2",
                "",
            ]
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
