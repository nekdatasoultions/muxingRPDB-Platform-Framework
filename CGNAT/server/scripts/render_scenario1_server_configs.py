from __future__ import annotations

import argparse
import ipaddress
import json
import sys
from pathlib import Path
from typing import Any


HEAD_END_PUBLIC_IP_PLACEHOLDER = "__CGNAT_HEAD_END_PUBLIC_IP__"


def _framework_src_root() -> Path:
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent.parent / "framework" / "src"


def _load_json(path: Path) -> dict[str, Any] | list[Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_package(package_dir: Path) -> dict[str, Any]:
    return {
        "manifest": _load_json(package_dir / "package-manifest.json"),
        "cgnat_head_end": _load_json(package_dir / "cgnat-head-end.json"),
        "cgnat_isp_head_end": _load_json(package_dir / "cgnat-isp-head-end.json"),
        "customer_vpn_routers": _load_json(package_dir / "customer-vpn-routers.json"),
        "backend_expectations": _load_json(package_dir / "backend-expectations.json"),
        "validation_targets": _load_json(package_dir / "validation-targets.json"),
    }


def _service_id(package: dict[str, Any]) -> str:
    return str(package["manifest"]["service_id"])


def _libreswan_identity(value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return candidate
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return candidate if candidate.startswith("@") else f"@{candidate}"
    return candidate


def _runtime_outer_identity(value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return candidate
    try:
        ipaddress.ip_address(candidate)
        return candidate
    except ValueError:
        sanitized = candidate.replace("/", ".")
        return "".join(char if char.isalnum() or char in ("-", ".") else "-" for char in sanitized)


def _demo_customer_selector(package: dict[str, Any]) -> str:
    customer_private_ip = str(package["cgnat_isp_head_end"]["customer_service_path"]["customer_facing_private_ip"])
    return str(ipaddress.ip_network(f"{customer_private_ip}/24", strict=False))


def _service_public_selector(package: dict[str, Any]) -> str:
    termination_public_loopback = str(package["backend_expectations"]["termination_public_loopback"])
    return str(ipaddress.ip_network(f"{termination_public_loopback}/32", strict=False))


def _head_end_runtime(package: dict[str, Any]) -> dict[str, Any]:
    service_id = _service_id(package)
    head_outer = package["cgnat_head_end"]["outer_tunnel"]
    head_gre = package["cgnat_head_end"]["gre_handoff"]
    backend = package["backend_expectations"]
    connection_name = f"{service_id}-outer"
    return {
        "service_id": service_id,
        "connection_name": connection_name,
        "certificate_material": {
            "head_end_server": {
                "certificate_ref": head_outer["server_certificate_ref"],
                "certificate_path": f"/etc/ipsec.d/certs/{service_id}-head-end.crt",
                "private_key_path": f"/etc/ipsec.d/private/{service_id}-head-end.key",
                "nickname": f"{service_id}-head-end",
            },
            "outer_tunnel_ca": {
                "certificate_path": f"/etc/ipsec.d/cacerts/{service_id}-outer-ca.crt",
                "nickname": f"{service_id}-outer-ca",
            },
        },
        "outer_tunnel": {
            "local_identity": _runtime_outer_identity(head_outer["local_identity"]),
            "remote_identity": _runtime_outer_identity(head_outer["remote_identity_ref"]),
            "local_selector": _service_public_selector(package),
            "remote_selector": _demo_customer_selector(package),
        },
        "gre_runtime": {
            "gre_name": "cgnat-s1-gre1",
            "source_interface": head_gre["source_interface"],
            "remote_ip": head_gre["selected_backend_gre_remote"],
            "termination_public_loopback": backend["termination_public_loopback"],
        },
    }


def _isp_head_end_runtime(package: dict[str, Any]) -> dict[str, Any]:
    service_id = _service_id(package)
    outer = package["cgnat_isp_head_end"]["outer_tunnel"]
    customer_path = package["cgnat_isp_head_end"]["customer_service_path"]
    connection_name = f"{service_id}-outer"
    return {
        "service_id": service_id,
        "connection_name": connection_name,
        "certificate_material": {
            "isp_head_end_client": {
                "certificate_ref": outer["client_certificate_ref"],
                "certificate_path": f"/etc/ipsec.d/certs/{service_id}-isp-client.crt",
                "private_key_path": f"/etc/ipsec.d/private/{service_id}-isp-client.key",
                "nickname": f"{service_id}-isp-client",
            },
            "outer_tunnel_ca": {
                "certificate_path": f"/etc/ipsec.d/cacerts/{service_id}-outer-ca.crt",
                "nickname": f"{service_id}-outer-ca",
            },
        },
        "outer_tunnel": {
            "local_identity": _runtime_outer_identity(outer["local_identity_ref"]),
            "remote_selector": _service_public_selector(package),
            "remote_identity": _runtime_outer_identity(outer["remote_identity"]),
            "remote_public_ip": outer.get("remote_public_ip") or HEAD_END_PUBLIC_IP_PLACEHOLDER,
            "local_selector": _demo_customer_selector(package),
        },
        "customer_service_path": {
            "customer_facing_interface": customer_path["customer_facing_interface"],
            "customer_facing_private_ip": customer_path["customer_facing_private_ip"],
        },
    }


def _customer_router_runtime(package: dict[str, Any], router: dict[str, Any]) -> dict[str, Any]:
    service_id = _service_id(package)
    inner = router["inner_vpn"]
    role = router["role"]
    return {
        "service_id": service_id,
        "role": role,
        "connection_name": f"{service_id}-{role}-inner",
        "customer_interface": router["customer_facing_interface"],
        "customer_private_ip_address": router["private_ip_address"],
        "customer_default_gateway_ip": router["default_gateway_ip"],
        "customer_loopback_ip": inner["customer_loopback_ip"],
        "customer_facing_public_ip": inner["remote_public_ip"],
        "known_inside_identity": inner["known_inside_identity"],
        "secret_ref": inner["secret_ref"],
        "secret_path": f"/etc/ipsec.d/{service_id}-{role}-inner.secrets",
    }


def _render_head_end_config(package: dict[str, Any]) -> dict[str, Any]:
    backend = package["backend_expectations"]
    return {
        "config_type": "scenario1_cgnat_head_end",
        "outer_tunnel": package["cgnat_head_end"]["outer_tunnel"],
        "gre_handoff": package["cgnat_head_end"]["gre_handoff"],
        "backend_service_target": package["cgnat_head_end"]["backend_service_target"],
        "routing_expectations": {
            "selected_backend_name": backend["selected_backend_name"],
            "selected_backend_gre_remote": backend["selected_backend_gre_remote"],
            "termination_public_loopback": backend["termination_public_loopback"],
        },
    }


def _render_isp_head_end_config(package: dict[str, Any]) -> dict[str, Any]:
    return {
        "config_type": "scenario1_cgnat_isp_head_end",
        "outer_tunnel": package["cgnat_isp_head_end"]["outer_tunnel"],
        "customer_service_path": package["cgnat_isp_head_end"]["customer_service_path"],
        "transit_contract": package["cgnat_isp_head_end"]["transit_contract"],
    }


def _render_customer_router_configs(package: dict[str, Any]) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    for router in package["customer_vpn_routers"]:
        configs.append(
            {
                "config_type": "scenario1_customer_vpn_router",
                "role": router["role"],
                "instance_name": router["instance_name"],
                "inner_vpn": router["inner_vpn"],
                "gateway_contract": {
                    "default_gateway_ip": router["default_gateway_ip"],
                    "customer_facing_interface": router["customer_facing_interface"],
                },
            }
        )
    return configs


def _render_backend_validation(package: dict[str, Any]) -> dict[str, Any]:
    return {
        "config_type": "scenario1_backend_validation",
        "backend_expectations": package["backend_expectations"],
        "validation_targets": package["validation_targets"],
    }


def _render_head_end_ipsec_conf(package: dict[str, Any]) -> str:
    runtime = _head_end_runtime(package)
    cert_material = runtime["certificate_material"]["head_end_server"]
    outer_ca = runtime["certificate_material"]["outer_tunnel_ca"]
    outer = runtime["outer_tunnel"]
    return "\n".join(
        [
            f"# Scenario 1 CGNAT HEAD END outer-tunnel config for {runtime['service_id']}",
            "# Target syntax: Libreswan ipsec.conf fragment",
            f"# Certificate reference: {cert_material['certificate_ref']}",
            f"# Outer-tunnel CA path: {outer_ca['certificate_path']}",
            "",
            f"conn {runtime['connection_name']}",
            "    type=tunnel",
            "    ikev2=insist",
            "    authby=rsasig",
            "    left=%defaultroute",
            f"    leftid={_libreswan_identity(outer['local_identity'])}",
            f"    leftcert={cert_material['nickname']}",
            "    leftrsasigkey=%cert",
            "    leftsendcert=always",
            f"    leftsubnet={outer['local_selector']}",
            "    right=%any",
            f"    rightid={_libreswan_identity(outer['remote_identity'])}",
            f"    rightsubnet={outer['remote_selector']}",
            "    dpddelay=30s",
            "    dpdtimeout=120s",
            "    dpdaction=restart",
            "    fragmentation=yes",
            "    mobike=no",
            "    auto=add",
            "",
        ]
    )


def _render_isp_head_end_ipsec_conf(package: dict[str, Any]) -> str:
    runtime = _isp_head_end_runtime(package)
    cert_material = runtime["certificate_material"]["isp_head_end_client"]
    outer_ca = runtime["certificate_material"]["outer_tunnel_ca"]
    outer = runtime["outer_tunnel"]
    return "\n".join(
        [
            f"# Scenario 1 CGNAT ISP HEAD END outer-tunnel config for {runtime['service_id']}",
            "# Target syntax: Libreswan ipsec.conf fragment",
            f"# Certificate reference: {cert_material['certificate_ref']}",
            f"# Outer-tunnel CA path: {outer_ca['certificate_path']}",
            "",
            f"conn {runtime['connection_name']}",
            "    type=tunnel",
            "    ikev2=insist",
            "    authby=rsasig",
            "    left=%defaultroute",
            f"    leftid={_libreswan_identity(outer['local_identity'])}",
            f"    leftcert={cert_material['nickname']}",
            "    leftrsasigkey=%cert",
            "    leftsendcert=always",
            f"    leftsubnet={outer['local_selector']}",
            f"    right={outer['remote_public_ip']}",
            f"    rightid={_libreswan_identity(outer['remote_identity'])}",
            f"    rightsubnet={outer['remote_selector']}",
            "    encapsulation=yes",
            "    dpddelay=30s",
            "    dpdtimeout=120s",
            "    dpdaction=restart",
            "    fragmentation=yes",
            "    mobike=no",
            "    auto=start",
            "",
        ]
    )


def _render_customer_router_inner_ipsec_conf(runtime: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# Scenario 1 customer-router inner-tunnel config for {runtime['role']}",
            "# Target syntax: Libreswan ipsec.conf fragment",
            f"# Inner VPN secret reference: {runtime['secret_ref']}",
            "",
            f"conn {runtime['connection_name']}",
            "    type=tunnel",
            "    ikev2=insist",
            "    authby=secret",
            "    left=%defaultroute",
            f"    leftid={_libreswan_identity(runtime['customer_loopback_ip'])}",
            f"    leftsubnet={runtime['known_inside_identity']}",
            f"    right={runtime['customer_facing_public_ip']}",
            f"    rightid={_libreswan_identity(runtime['customer_facing_public_ip'])}",
            f"    rightsubnet={runtime['customer_facing_public_ip']}/32",
            "    dpddelay=30s",
            "    dpdtimeout=120s",
            "    dpdaction=restart",
            "    fragmentation=yes",
            "    mobike=no",
            "    auto=start",
            "",
        ]
    )


def _render_head_end_gre_script() -> str:
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
            "source \"$SCRIPT_DIR/cgnat-head-end-runtime.env\"",
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


def _render_head_end_route_script() -> str:
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
            "source \"$SCRIPT_DIR/cgnat-head-end-runtime.env\"",
            "",
            "ip route replace \"${CGNAT_TERMINATION_PUBLIC_LOOPBACK}/32\" dev \"$CGNAT_GRE_NAME\"",
            "",
        ]
    )


def _render_forwarding_script(runtime_env_name: str) -> str:
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
            f"source \"$SCRIPT_DIR/{runtime_env_name}\"",
            "",
            "sysctl -w net.ipv4.ip_forward=1",
            "",
        ]
    )


def _render_customer_router_loopback_script(runtime: dict[str, Any]) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        f"ip addr replace \"{runtime['customer_loopback_ip']}/32\" dev lo",
    ]
    known_inside_identity = str(runtime.get("known_inside_identity") or "").strip()
    if known_inside_identity and known_inside_identity != f"{runtime['customer_loopback_ip']}/32":
        lines.append(f"ip addr replace \"{known_inside_identity}\" dev lo")
    lines.append("")
    return "\n".join(lines)


def _render_customer_router_route_script(runtime: dict[str, Any]) -> str:
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
            f"source \"$SCRIPT_DIR/{runtime['role']}-runtime.env\"",
            "",
            "ip route replace default via \"$CGNAT_CUSTOMER_DEFAULT_GATEWAY_IP\" dev \"$CGNAT_CUSTOMER_INTERFACE\"",
            "",
        ]
    )


def _render_head_end_runtime_env(runtime: dict[str, Any]) -> str:
    cert_material = runtime["certificate_material"]
    gre_runtime = runtime["gre_runtime"]
    outer_runtime = runtime["outer_tunnel"]
    return "\n".join(
        [
            f"CGNAT_SERVICE_ID=\"{runtime['service_id']}\"",
            f"CGNAT_OUTER_CONNECTION_NAME=\"{runtime['connection_name']}\"",
            f"CGNAT_OUTER_LOCAL_IDENTITY=\"{outer_runtime['local_identity']}\"",
            f"CGNAT_OUTER_REMOTE_IDENTITY=\"{outer_runtime['remote_identity']}\"",
            f"CGNAT_GRE_NAME=\"{gre_runtime['gre_name']}\"",
            f"CGNAT_HEAD_END_GRE_SOURCE_INTERFACE=\"{gre_runtime['source_interface']}\"",
            f"CGNAT_BACKEND_GRE_REMOTE=\"{gre_runtime['remote_ip']}\"",
            f"CGNAT_TERMINATION_PUBLIC_LOOPBACK=\"{gre_runtime['termination_public_loopback']}\"",
            f"CGNAT_HEAD_END_SERVER_CERT_REF=\"{cert_material['head_end_server']['certificate_ref']}\"",
            f"CGNAT_HEAD_END_SERVER_CERT_PATH=\"{cert_material['head_end_server']['certificate_path']}\"",
            f"CGNAT_HEAD_END_SERVER_KEY_PATH=\"{cert_material['head_end_server']['private_key_path']}\"",
            f"CGNAT_HEAD_END_CERT_NICKNAME=\"{cert_material['head_end_server']['nickname']}\"",
            f"CGNAT_OUTER_CA_CERT_PATH=\"{cert_material['outer_tunnel_ca']['certificate_path']}\"",
            f"CGNAT_OUTER_CA_NICKNAME=\"{cert_material['outer_tunnel_ca']['nickname']}\"",
            "",
        ]
    )


def _render_isp_head_end_runtime_env(runtime: dict[str, Any]) -> str:
    cert_material = runtime["certificate_material"]
    customer_path = runtime["customer_service_path"]
    outer_runtime = runtime["outer_tunnel"]
    return "\n".join(
        [
            f"CGNAT_SERVICE_ID=\"{runtime['service_id']}\"",
            f"CGNAT_OUTER_CONNECTION_NAME=\"{runtime['connection_name']}\"",
            f"CGNAT_OUTER_LOCAL_IDENTITY=\"{outer_runtime['local_identity']}\"",
            f"CGNAT_OUTER_REMOTE_IDENTITY=\"{outer_runtime['remote_identity']}\"",
            f"CGNAT_OUTER_REMOTE_PUBLIC_IP=\"{outer_runtime['remote_public_ip']}\"",
            f"CGNAT_ISP_HEAD_END_CLIENT_CERT_REF=\"{cert_material['isp_head_end_client']['certificate_ref']}\"",
            f"CGNAT_ISP_HEAD_END_CLIENT_CERT_PATH=\"{cert_material['isp_head_end_client']['certificate_path']}\"",
            f"CGNAT_ISP_HEAD_END_CLIENT_KEY_PATH=\"{cert_material['isp_head_end_client']['private_key_path']}\"",
            f"CGNAT_ISP_HEAD_END_CERT_NICKNAME=\"{cert_material['isp_head_end_client']['nickname']}\"",
            f"CGNAT_OUTER_CA_CERT_PATH=\"{cert_material['outer_tunnel_ca']['certificate_path']}\"",
            f"CGNAT_OUTER_CA_NICKNAME=\"{cert_material['outer_tunnel_ca']['nickname']}\"",
            f"CGNAT_ISP_CUSTOMER_INTERFACE=\"{customer_path['customer_facing_interface']}\"",
            f"CGNAT_ISP_CUSTOMER_PRIVATE_IP=\"{customer_path['customer_facing_private_ip']}\"",
            "",
        ]
    )


def _render_customer_router_runtime_env(runtime: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"CGNAT_SERVICE_ID=\"{runtime['service_id']}\"",
            f"CGNAT_ROLE=\"{runtime['role']}\"",
            f"CGNAT_CUSTOMER_INTERFACE=\"{runtime['customer_interface']}\"",
            f"CGNAT_CUSTOMER_PRIVATE_IP=\"{runtime['customer_private_ip_address']}\"",
            f"CGNAT_CUSTOMER_DEFAULT_GATEWAY_IP=\"{runtime['customer_default_gateway_ip']}\"",
            f"CGNAT_INNER_CONNECTION_NAME=\"{runtime['connection_name']}\"",
            f"CGNAT_INNER_VPN_SECRET_REF=\"{runtime['secret_ref']}\"",
            f"CGNAT_INNER_VPN_SECRET_PATH=\"{runtime['secret_path']}\"",
            f"CGNAT_CUSTOMER_LOOPBACK_IP=\"{runtime['customer_loopback_ip']}\"",
            f"CGNAT_CUSTOMER_FACING_PUBLIC_IP=\"{runtime['customer_facing_public_ip']}\"",
            f"CGNAT_KNOWN_INSIDE_IDENTITY=\"{runtime['known_inside_identity']}\"",
            "",
        ]
    )


def _render_validation_commands(package: dict[str, Any]) -> str:
    lines = [
        "# Scenario 1 Validation Commands",
        "",
        "These commands align with the chosen Scenario 1 runtime style: libreswan for IPsec and Linux iproute2 for routing.",
        "",
        "## Required Validation Areas",
        "",
        "- outer tunnel established on the ISP CGNAT device",
        "- both customer-router inner tunnels established",
        "- backend responder behavior confirmed",
        "- GRE handoff visible",
        "- request and reply path visible",
        "",
        "## Example Checks",
        "",
        "On the CGNAT HEAD END:",
        "```bash",
        "sudo ipsec trafficstatus",
        "ip tunnel show",
        "ip route get " + package["validation_targets"]["customer_facing_public_ip"],
        "```",
        "",
        "On the CGNAT ISP HEAD END:",
        "```bash",
        "sudo ipsec trafficstatus",
        "sysctl net.ipv4.ip_forward",
        "```",
        "",
    ]
    for router in package["validation_targets"]["customer_routers"]:
        lines.extend(
            [
                f"On `{router['role']}`:",
                "```bash",
                "sudo ipsec trafficstatus",
                f"# customer loopback identity: {router['customer_loopback_ip']}",
                f"# interesting traffic identity: {router['known_inside_identity']}",
                f"# destination public IP: {package['validation_targets']['customer_facing_public_ip']}",
                "```",
                "",
            ]
        )
    lines.extend(
        [
            "On the selected backend head end:",
            "```bash",
            "# verify responder behavior",
            "# verify traffic arrives on the expected backend loopback/service target",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


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
    head_runtime = _head_end_runtime(package)
    isp_runtime = _isp_head_end_runtime(package)
    customer_router_runtimes = [_customer_router_runtime(package, router) for router in package["customer_vpn_routers"]]

    dump_json(output_dir / "cgnat-head-end-config.json", _render_head_end_config(package))
    dump_json(output_dir / "cgnat-isp-head-end-config.json", _render_isp_head_end_config(package))
    dump_json(output_dir / "customer-vpn-routers-config.json", _render_customer_router_configs(package))
    dump_json(output_dir / "backend-validation.json", _render_backend_validation(package))
    dump_json(
        output_dir / "runtime-inputs.json",
        {
            "service_id": _service_id(package),
            "runtime_style": {
                "ipsec": "libreswan_ipsec_conf",
                "routing": "linux_iproute2",
            },
            "head_end": head_runtime,
            "isp_head_end": isp_runtime,
            "customer_vpn_routers": customer_router_runtimes,
        },
    )
    dump_text(output_dir / "cgnat-head-end-swanctl.conf", _render_head_end_ipsec_conf(package))
    dump_text(output_dir / "cgnat-isp-head-end-swanctl.conf", _render_isp_head_end_ipsec_conf(package))
    dump_text(output_dir / "cgnat-head-end-gre.sh", _render_head_end_gre_script())
    dump_text(output_dir / "cgnat-head-end-routes.sh", _render_head_end_route_script())
    dump_text(output_dir / "cgnat-head-end-forwarding.sh", _render_forwarding_script("cgnat-head-end-runtime.env"))
    dump_text(output_dir / "cgnat-isp-head-end-forwarding.sh", _render_forwarding_script("cgnat-isp-head-end-runtime.env"))
    dump_text(output_dir / "cgnat-head-end-runtime.env", _render_head_end_runtime_env(head_runtime))
    dump_text(output_dir / "cgnat-isp-head-end-runtime.env", _render_isp_head_end_runtime_env(isp_runtime))
    for router_runtime in customer_router_runtimes:
        role = router_runtime["role"]
        dump_text(output_dir / f"{role}-inner-swanctl.conf", _render_customer_router_inner_ipsec_conf(router_runtime))
        dump_text(output_dir / f"{role}-loopback.sh", _render_customer_router_loopback_script(router_runtime))
        dump_text(output_dir / f"{role}-routes.sh", _render_customer_router_route_script(router_runtime))
        dump_text(output_dir / f"{role}-runtime.env", _render_customer_router_runtime_env(router_runtime))
    dump_text(output_dir / "validation-commands.md", _render_validation_commands(package))
    dump_text(
        output_dir / "README.md",
        "\n".join(
            [
                "# Scenario 1 Server Config Artifacts",
                "",
                "- structured host-side artifacts generated from the server package",
                "- Libreswan `ipsec.conf` fragments for the hosted head end and ISP outer tunnel",
                "- per-customer-router inner-tunnel configs, loopback scripts, and route scripts",
                "- runtime input manifests and per-role environment files for apply-time values",
                "- validation guidance included",
                "",
            ]
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
