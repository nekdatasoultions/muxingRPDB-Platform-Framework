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


def _sanitize_identity(value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return candidate
    candidate = candidate.replace("/", ".")
    return "".join(char if char.isalnum() or char in ("-", ".") else "-" for char in candidate)


def _basename(path_value: str) -> str:
    return Path(str(path_value)).name


def _role_index(role: str) -> int:
    try:
        return int(str(role).rsplit("_", 1)[-1])
    except (TypeError, ValueError):
        return 1


def _xfrm_if_id(role: str) -> int:
    return 100 + _role_index(role)


def _xfrm_interface_name(role: str) -> str:
    return f"cgxfrm-r{_role_index(role)}"


def _service_interface_name(role: str) -> str:
    return f"cglan-r{_role_index(role)}"


def _selector_ip(selector: str) -> str:
    return str(ipaddress.ip_interface(str(selector)).ip)


def _service_public_selector(package: dict[str, Any]) -> str:
    termination_public_loopback = str(package["backend_expectations"]["termination_public_loopback"])
    return str(ipaddress.ip_network(f"{termination_public_loopback}/32", strict=False))


def _strongswan_runtime_style() -> dict[str, str]:
    return {
        "outer_transport": "strongswan_swanctl_xfrmi",
        "inner_vpn": "strongswan_swanctl_psk",
        "routing": "linux_iproute2",
    }


def _head_end_runtime(package: dict[str, Any]) -> dict[str, Any]:
    service_id = _service_id(package)
    head_outer = package["cgnat_head_end"]["outer_tunnel_listener"]
    head_gre = package["cgnat_head_end"]["gre_handoff"]
    backend = package["backend_expectations"]
    accepted_outer_peers = []
    for entry in package["cgnat_head_end"].get("accepted_outer_peers") or []:
        role = str(entry["role"])
        accepted_outer_peers.append(
            {
                "role": role,
                "device_name": entry["device_name"],
                "connection_name": entry["connection_name"],
                "child_name": f"{entry['connection_name']}-transport",
                "remote_identity": _sanitize_identity(entry["remote_identity_ref"]),
                "route_back_selector": entry["remote_selector"],
                "xfrm_interface_name": _xfrm_interface_name(role),
                "xfrm_if_id": _xfrm_if_id(role),
            }
        )
    return {
        "service_id": service_id,
        "runtime_style": _strongswan_runtime_style(),
        "certificate_material": {
            "head_end_server": {
                "certificate_ref": head_outer["server_certificate_ref"],
                "certificate_path": f"/etc/swanctl/x509/{service_id}-head-end.crt",
                "private_key_path": f"/etc/swanctl/private/{service_id}-head-end.key",
                "certificate_name": f"{service_id}-head-end.crt",
                "private_key_name": f"{service_id}-head-end.key",
            },
            "outer_tunnel_ca": {
                "certificate_path": f"/etc/swanctl/x509ca/{service_id}-outer-ca.crt",
                "certificate_name": f"{service_id}-outer-ca.crt",
            },
        },
        "outer_tunnel": {
            "local_identity": _sanitize_identity(head_outer["local_identity"]),
            "local_ts": ["0.0.0.0/0"],
            "remote_ts": ["0.0.0.0/0"],
            "accepted_peers": accepted_outer_peers,
        },
        "outer_transport": {
            "implementation": "strongswan_xfrmi",
            "interface": head_outer["termination_interface"],
            "service_target_selector": _service_public_selector(package),
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
    customer_path = package["cgnat_isp_head_end"]["customer_service_path"]
    return {
        "service_id": service_id,
        "transport_role": package["cgnat_isp_head_end"]["transport_role"],
        "customer_service_path": {
            "uplink_interface": customer_path["uplink_interface"],
            "customer_facing_interface": customer_path["customer_facing_interface"],
            "customer_facing_private_ip": customer_path["customer_facing_private_ip"],
        },
    }


def _customer_router_runtime(package: dict[str, Any], router: dict[str, Any]) -> dict[str, Any]:
    service_id = _service_id(package)
    outer = router["outer_tunnel"]
    inner = router["inner_vpn"]
    role = str(router["role"])
    xfrm_name = _xfrm_interface_name(role)
    xfrm_id = _xfrm_if_id(role)
    return {
        "service_id": service_id,
        "runtime_style": _strongswan_runtime_style(),
        "role": role,
        "outer_connection_name": f"{service_id}-{role}-outer",
        "outer_child_name": f"{service_id}-{role}-outer-transport",
        "inner_connection_name": f"{service_id}-{role}-inner",
        "inner_child_name": f"{service_id}-{role}-inner-service",
        "customer_interface": router["customer_facing_interface"],
        "customer_private_ip_address": router["private_ip_address"],
        "customer_default_gateway_ip": router["default_gateway_ip"],
        "service_ip_interface_name": _service_interface_name(role),
        "service_ip_address": _selector_ip(str(inner["known_inside_identity"])),
        "certificate_material": {
            "outer_client": {
                "certificate_ref": outer["client_certificate_ref"],
                "certificate_path": f"/etc/swanctl/x509/{service_id}-{role}-outer.crt",
                "private_key_path": f"/etc/swanctl/private/{service_id}-{role}-outer.key",
                "certificate_name": f"{service_id}-{role}-outer.crt",
                "private_key_name": f"{service_id}-{role}-outer.key",
            },
            "outer_tunnel_ca": {
                "certificate_path": f"/etc/swanctl/x509ca/{service_id}-outer-ca.crt",
                "certificate_name": f"{service_id}-outer-ca.crt",
            },
        },
        "outer_tunnel": {
            "implementation": "strongswan_xfrmi",
            "local_identity": _sanitize_identity(outer["local_identity_ref"]),
            "remote_identity": _sanitize_identity(outer["remote_identity"]),
            "local_addrs": [router["private_ip_address"]],
            "remote_addrs": [outer.get("remote_public_ip") or HEAD_END_PUBLIC_IP_PLACEHOLDER],
            "local_ts": ["0.0.0.0/0"],
            "remote_ts": ["0.0.0.0/0"],
            "route_target": _service_public_selector(package),
            "xfrm_interface_name": xfrm_name,
            "xfrm_if_id": xfrm_id,
        },
        "inner_vpn": {
            "implementation": "strongswan_swanctl_psk",
            "local_addrs": [str(inner["customer_loopback_ip"])],
            "local_identity": str(inner["customer_loopback_ip"]),
            "local_ts": [str(inner["known_inside_identity"])],
            "remote_addrs": [str(inner["remote_public_ip"])],
            "remote_identity": str(inner["termination_public_loopback"]),
            "remote_ts": [str(selector) for selector in inner.get("remote_selectors") or [f"{inner['remote_public_ip']}/32"]],
            "secret_ref": str(inner["secret_ref"]),
            "raw_secret_stage_name": f"{service_id}-{role}-inner.psk",
            "secret_config_path": f"/etc/swanctl/conf.d/{service_id}-{role}-inner-secrets.conf",
        },
    }


def _render_head_end_config(package: dict[str, Any]) -> dict[str, Any]:
    backend = package["backend_expectations"]
    return {
        "config_type": "scenario1_cgnat_head_end",
        "runtime_style": _strongswan_runtime_style(),
        "outer_tunnel_listener": package["cgnat_head_end"]["outer_tunnel_listener"],
        "accepted_outer_peers": package["cgnat_head_end"]["accepted_outer_peers"],
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
        "transport_role": package["cgnat_isp_head_end"]["transport_role"],
        "customer_service_path": package["cgnat_isp_head_end"]["customer_service_path"],
        "transit_contract": package["cgnat_isp_head_end"]["transit_contract"],
    }


def _render_customer_router_configs(package: dict[str, Any]) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    for router in package["customer_vpn_routers"]:
        configs.append(
            {
                "config_type": "scenario1_customer_vpn_router",
                "runtime_style": _strongswan_runtime_style(),
                "role": router["role"],
                "instance_name": router["instance_name"],
                "outer_tunnel": router["outer_tunnel"],
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


def _render_head_end_swanctl_conf(runtime: dict[str, Any]) -> str:
    cert_material = runtime["certificate_material"]["head_end_server"]
    ca_material = runtime["certificate_material"]["outer_tunnel_ca"]
    lines = [
        f"# Scenario 1 CGNAT HEAD END route-based outer transport for {runtime['service_id']}",
        "# Target syntax: strongSwan swanctl.conf fragment",
        "",
        "connections {",
    ]
    for peer in runtime["outer_tunnel"]["accepted_peers"]:
        lines.extend(
            [
                f"  {peer['connection_name']} {{",
                "    version = 2",
                "    mobike = no",
                "    fragmentation = yes",
                "    proposals = aes256-sha256-modp2048",
                "    local_addrs = 0.0.0.0",
                "    remote_addrs = %any",
                "    local {",
                "      auth = pubkey",
                f"      id = {_sanitize_identity(runtime['outer_tunnel']['local_identity'])}",
                f"      certs = {cert_material['certificate_name']}",
                "    }",
                "    remote {",
                "      auth = pubkey",
                f"      id = {_sanitize_identity(peer['remote_identity'])}",
                "    }",
                "    children {",
                f"      {peer['child_name']} {{",
                "        local_ts = 0.0.0.0/0",
                "        remote_ts = 0.0.0.0/0",
                f"        if_id_in = {peer['xfrm_if_id']}",
                f"        if_id_out = {peer['xfrm_if_id']}",
                "        esp_proposals = aes256-sha256-modp2048",
                "        start_action = trap",
                "        close_action = trap",
                "        dpd_action = restart",
                "        rekey_time = 0s",
                "      }",
                "    }",
                "  }",
            ]
        )
    lines.append("}")
    lines.append("")
    lines.extend(
        [
            "authorities {",
            "  outer-ca {",
            f"    cacert = {ca_material['certificate_name']}",
            "  }",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def _render_isp_head_end_ipsec_conf(package: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Scenario 1 CGNAT ISP HEAD END",
            "# No IPsec daemon terminates on this node in the corrected architecture.",
            "# This node acts as NAT/transit only for customer-router outer tunnel traffic.",
            "",
        ]
    )


def _render_customer_router_outer_swanctl_conf(runtime: dict[str, Any]) -> str:
    cert_material = runtime["certificate_material"]["outer_client"]
    ca_material = runtime["certificate_material"]["outer_tunnel_ca"]
    outer = runtime["outer_tunnel"]
    return "\n".join(
        [
            f"# Scenario 1 customer-router outer transport for {runtime['role']}",
            "# Target syntax: strongSwan swanctl.conf fragment",
            "",
            "connections {",
            f"  {runtime['outer_connection_name']} {{",
            "    version = 2",
            "    mobike = no",
            "    fragmentation = yes",
            "    encap = yes",
            "    proposals = aes256-sha256-modp2048",
            f"    local_addrs = {outer['local_addrs'][0]}",
            f"    remote_addrs = {outer['remote_addrs'][0]}",
            "    local {",
            "      auth = pubkey",
            f"      id = {_sanitize_identity(outer['local_identity'])}",
            f"      certs = {cert_material['certificate_name']}",
            "    }",
            "    remote {",
            "      auth = pubkey",
            f"      id = {_sanitize_identity(outer['remote_identity'])}",
            "    }",
            "    children {",
            f"      {runtime['outer_child_name']} {{",
            "        local_ts = 0.0.0.0/0",
            "        remote_ts = 0.0.0.0/0",
            f"        if_id_in = {outer['xfrm_if_id']}",
            f"        if_id_out = {outer['xfrm_if_id']}",
            "        esp_proposals = aes256-sha256-modp2048",
            "        start_action = start",
            "        dpd_action = restart",
            "        rekey_time = 0s",
            "      }",
            "    }",
            "  }",
            "}",
            "",
            "authorities {",
            "  outer-ca {",
            f"    cacert = {ca_material['certificate_name']}",
            "  }",
            "}",
            "",
        ]
    )


def _render_customer_router_inner_swanctl_conf(runtime: dict[str, Any]) -> str:
    inner = runtime["inner_vpn"]
    remote_ts = ",".join(inner["remote_ts"])
    return "\n".join(
        [
            f"# Scenario 1 customer-router inner service tunnel for {runtime['role']}",
            "# Target syntax: strongSwan swanctl.conf fragment",
            f"# Inner VPN secret reference: {inner['secret_ref']}",
            "",
            "connections {",
            f"  {runtime['inner_connection_name']} {{",
            "    version = 2",
            "    mobike = no",
            "    fragmentation = yes",
            "    proposals = aes256-sha256-modp2048",
            f"    local_addrs = {inner['local_addrs'][0]}",
            f"    remote_addrs = {inner['remote_addrs'][0]}",
            "    local {",
            "      auth = psk",
            f"      id = {_sanitize_identity(inner['local_identity'])}",
            "    }",
            "    remote {",
            "      auth = psk",
            f"      id = {_sanitize_identity(inner['remote_identity'])}",
            "    }",
            "    children {",
            f"      {runtime['inner_child_name']} {{",
            f"        local_ts = {inner['local_ts'][0]}",
            f"        remote_ts = {remote_ts}",
            "        esp_proposals = aes256-sha256-modp2048",
            "        start_action = start",
            "        dpd_action = restart",
            "        rekey_time = 0s",
            "      }",
            "    }",
            "  }",
            "}",
            "",
        ]
    )


def _render_head_end_xfrm_script(runtime: dict[str, Any]) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
        "source \"$SCRIPT_DIR/cgnat-head-end-runtime.env\"",
        "",
    ]
    for peer in runtime["outer_tunnel"]["accepted_peers"]:
        lines.extend(
            [
                f"ip link del \"{peer['xfrm_interface_name']}\" 2>/dev/null || true",
                f"ip link add \"{peer['xfrm_interface_name']}\" type xfrm dev \"$CGNAT_HEAD_END_OUTER_INTERFACE\" if_id {peer['xfrm_if_id']}",
                f"ip link set \"{peer['xfrm_interface_name']}\" up",
                f"ip route replace \"{peer['route_back_selector']}\" dev \"{peer['xfrm_interface_name']}\"",
            ]
        )
    lines.append("")
    return "\n".join(lines)


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


def _render_head_end_forwarding_script(runtime_env_name: str) -> str:
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
            f"source \"$SCRIPT_DIR/{runtime_env_name}\"",
            "",
            "sysctl -w net.ipv4.ip_forward=1",
            "sysctl -w net.ipv4.conf.all.rp_filter=0",
            "sysctl -w net.ipv4.conf.default.rp_filter=0",
            "sysctl -w \"net.ipv4.conf.${CGNAT_HEAD_END_OUTER_INTERFACE}.rp_filter=0\"",
            "sysctl -w \"net.ipv4.conf.${CGNAT_HEAD_END_GRE_SOURCE_INTERFACE}.rp_filter=0\"",
            "",
        ]
    )


def _render_isp_head_end_forwarding_script() -> str:
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\" && pwd",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
            "source \"$SCRIPT_DIR/cgnat-isp-head-end-runtime.env\"",
            "",
            "sysctl -w net.ipv4.ip_forward=1",
            "sysctl -w net.ipv4.conf.all.rp_filter=0",
            "sysctl -w net.ipv4.conf.default.rp_filter=0",
            "sysctl -w \"net.ipv4.conf.${CGNAT_ISP_CUSTOMER_INTERFACE}.rp_filter=0\"",
            "sysctl -w \"net.ipv4.conf.${CGNAT_ISP_UPLINK_INTERFACE}.rp_filter=0\"",
            "",
            "if ! command -v nft >/dev/null; then",
            "  if command -v dnf >/dev/null; then",
            "    dnf -y install nftables",
            "  elif command -v yum >/dev/null; then",
            "    yum -y install nftables",
            "  else",
            "    echo \"nft is required on the CGNAT ISP HEAD END\" >&2",
            "    exit 1",
            "  fi",
            "fi",
            "",
            "install -d /etc/nftables.d",
            "systemctl enable nftables >/dev/null 2>&1 || true",
            "CUSTOMER_SUBNET=\"$(ip -o -f inet addr show dev \"$CGNAT_ISP_CUSTOMER_INTERFACE\" | awk '{print $4; exit}')\"",
            "if [[ -z \"$CUSTOMER_SUBNET\" ]]; then",
            "  echo \"Unable to determine customer subnet for $CGNAT_ISP_CUSTOMER_INTERFACE\" >&2",
            "  exit 1",
            "fi",
            "",
            "nft delete table inet cgnat_scenario1 >/dev/null 2>&1 || true",
            "nft delete table ip cgnat_scenario1_nat >/dev/null 2>&1 || true",
            "cat > /etc/nftables.d/cgnat-scenario1-isp.nft <<EOF",
            "table inet cgnat_scenario1 {",
            "  chain forward {",
            "    type filter hook forward priority 0;",
            "    policy accept;",
            "    iifname \"$CGNAT_ISP_CUSTOMER_INTERFACE\" oifname \"$CGNAT_ISP_UPLINK_INTERFACE\" accept",
            "    iifname \"$CGNAT_ISP_UPLINK_INTERFACE\" oifname \"$CGNAT_ISP_CUSTOMER_INTERFACE\" ct state established,related accept",
            "  }",
            "}",
            "",
            "table ip cgnat_scenario1_nat {",
            "  chain postrouting {",
            "    type nat hook postrouting priority 100;",
            "    policy accept;",
            "    ip saddr $CUSTOMER_SUBNET oifname \"$CGNAT_ISP_UPLINK_INTERFACE\" masquerade",
            "  }",
            "}",
            "EOF",
            "nft -f /etc/nftables.d/cgnat-scenario1-isp.nft",
            "",
        ]
    )


def _render_customer_router_xfrm_script(runtime: dict[str, Any]) -> str:
    outer = runtime["outer_tunnel"]
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
            f"source \"$SCRIPT_DIR/{runtime['role']}-runtime.env\"",
            "",
            "ip link del \"$CGNAT_OUTER_XFRM_INTERFACE\" 2>/dev/null || true",
            "ip link add \"$CGNAT_OUTER_XFRM_INTERFACE\" type xfrm dev \"$CGNAT_CUSTOMER_INTERFACE\" if_id \"$CGNAT_OUTER_XFRM_IF_ID\"",
            "ip link set \"$CGNAT_OUTER_XFRM_INTERFACE\" up",
            "sysctl -w net.ipv4.ip_forward=1",
            "sysctl -w \"net.ipv4.conf.${CGNAT_OUTER_XFRM_INTERFACE}.disable_policy=1\"",
            "ip route replace \"${CGNAT_CUSTOMER_FACING_PUBLIC_IP}/32\" dev \"$CGNAT_OUTER_XFRM_INTERFACE\"",
            "",
        ]
    )


def _render_customer_router_loopback_script(runtime: dict[str, Any]) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
        f"source \"$SCRIPT_DIR/{runtime['role']}-runtime.env\"",
        "",
        "ip link show \"$CGNAT_CUSTOMER_SERVICE_INTERFACE\" >/dev/null 2>&1 || ip link add \"$CGNAT_CUSTOMER_SERVICE_INTERFACE\" type dummy",
        "ip link set \"$CGNAT_CUSTOMER_SERVICE_INTERFACE\" up",
        "ip addr replace \"${CGNAT_CUSTOMER_LOOPBACK_IP}/32\" dev lo",
    ]
    known_inside_identity = str(runtime["inner_vpn"]["local_ts"][0]).strip()
    if known_inside_identity and known_inside_identity != f"{runtime['inner_vpn']['local_identity']}/32":
        lines.append("ip addr del \"$CGNAT_KNOWN_INSIDE_IDENTITY\" dev lo 2>/dev/null || true")
        lines.append("ip addr replace \"$CGNAT_KNOWN_INSIDE_IDENTITY\" dev \"$CGNAT_CUSTOMER_SERVICE_INTERFACE\"")
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
            f"CGNAT_OUTER_LOCAL_IDENTITY=\"{outer_runtime['local_identity']}\"",
            f"CGNAT_OUTER_ACCEPTED_PEER_COUNT=\"{len(outer_runtime['accepted_peers'])}\"",
            f"CGNAT_HEAD_END_OUTER_INTERFACE=\"{runtime['outer_transport']['interface']}\"",
            f"CGNAT_GRE_NAME=\"{gre_runtime['gre_name']}\"",
            f"CGNAT_HEAD_END_GRE_SOURCE_INTERFACE=\"{gre_runtime['source_interface']}\"",
            f"CGNAT_BACKEND_GRE_REMOTE=\"{gre_runtime['remote_ip']}\"",
            f"CGNAT_TERMINATION_PUBLIC_LOOPBACK=\"{gre_runtime['termination_public_loopback']}\"",
            f"CGNAT_HEAD_END_SERVER_CERT_REF=\"{cert_material['head_end_server']['certificate_ref']}\"",
            f"CGNAT_HEAD_END_SERVER_CERT_PATH=\"{cert_material['head_end_server']['certificate_path']}\"",
            f"CGNAT_HEAD_END_SERVER_KEY_PATH=\"{cert_material['head_end_server']['private_key_path']}\"",
            f"CGNAT_OUTER_CA_CERT_PATH=\"{cert_material['outer_tunnel_ca']['certificate_path']}\"",
            "",
        ]
    )


def _render_isp_head_end_runtime_env(runtime: dict[str, Any]) -> str:
    customer_path = runtime["customer_service_path"]
    return "\n".join(
        [
            f"CGNAT_SERVICE_ID=\"{runtime['service_id']}\"",
            f"CGNAT_TRANSPORT_ROLE=\"{runtime['transport_role']}\"",
            f"CGNAT_ISP_UPLINK_INTERFACE=\"{customer_path['uplink_interface']}\"",
            f"CGNAT_ISP_CUSTOMER_INTERFACE=\"{customer_path['customer_facing_interface']}\"",
            f"CGNAT_ISP_CUSTOMER_PRIVATE_IP=\"{customer_path['customer_facing_private_ip']}\"",
            "",
        ]
    )


def _render_customer_router_runtime_env(runtime: dict[str, Any]) -> str:
    cert_material = runtime["certificate_material"]
    outer_runtime = runtime["outer_tunnel"]
    inner_runtime = runtime["inner_vpn"]
    return "\n".join(
        [
            f"CGNAT_SERVICE_ID=\"{runtime['service_id']}\"",
            f"CGNAT_ROLE=\"{runtime['role']}\"",
            f"CGNAT_CUSTOMER_INTERFACE=\"{runtime['customer_interface']}\"",
            f"CGNAT_CUSTOMER_PRIVATE_IP=\"{runtime['customer_private_ip_address']}\"",
            f"CGNAT_CUSTOMER_DEFAULT_GATEWAY_IP=\"{runtime['customer_default_gateway_ip']}\"",
            f"CGNAT_CUSTOMER_SERVICE_INTERFACE=\"{runtime['service_ip_interface_name']}\"",
            f"CGNAT_CUSTOMER_SERVICE_IP=\"{runtime['service_ip_address']}\"",
            f"CGNAT_OUTER_CONNECTION_NAME=\"{runtime['outer_connection_name']}\"",
            f"CGNAT_OUTER_CHILD_NAME=\"{runtime['outer_child_name']}\"",
            f"CGNAT_OUTER_LOCAL_IDENTITY=\"{outer_runtime['local_identity']}\"",
            f"CGNAT_OUTER_REMOTE_IDENTITY=\"{outer_runtime['remote_identity']}\"",
            f"CGNAT_OUTER_REMOTE_PUBLIC_IP=\"{outer_runtime['remote_addrs'][0]}\"",
            f"CGNAT_OUTER_XFRM_INTERFACE=\"{outer_runtime['xfrm_interface_name']}\"",
            f"CGNAT_OUTER_XFRM_IF_ID=\"{outer_runtime['xfrm_if_id']}\"",
            f"CGNAT_OUTER_CLIENT_CERT_REF=\"{cert_material['outer_client']['certificate_ref']}\"",
            f"CGNAT_OUTER_CLIENT_CERT_PATH=\"{cert_material['outer_client']['certificate_path']}\"",
            f"CGNAT_OUTER_CLIENT_KEY_PATH=\"{cert_material['outer_client']['private_key_path']}\"",
            f"CGNAT_OUTER_CA_CERT_PATH=\"{cert_material['outer_tunnel_ca']['certificate_path']}\"",
            f"CGNAT_INNER_CONNECTION_NAME=\"{runtime['inner_connection_name']}\"",
            f"CGNAT_INNER_CHILD_NAME=\"{runtime['inner_child_name']}\"",
            f"CGNAT_INNER_VPN_SECRET_REF=\"{inner_runtime['secret_ref']}\"",
            f"CGNAT_INNER_VPN_SECRET_STAGE_NAME=\"{inner_runtime['raw_secret_stage_name']}\"",
            f"CGNAT_INNER_VPN_SECRET_CONF_PATH=\"{inner_runtime['secret_config_path']}\"",
            f"CGNAT_CUSTOMER_LOOPBACK_IP=\"{inner_runtime['local_identity']}\"",
            f"CGNAT_CUSTOMER_FACING_PUBLIC_IP=\"{inner_runtime['remote_addrs'][0]}\"",
            f"CGNAT_INNER_REMOTE_SELECTORS=\"{','.join(str(selector) for selector in inner_runtime['remote_ts'])}\"",
            f"CGNAT_KNOWN_INSIDE_IDENTITY=\"{inner_runtime['local_ts'][0]}\"",
            "",
        ]
    )


def _render_validation_commands(package: dict[str, Any]) -> str:
    lines = [
        "# Scenario 1 Validation Commands",
        "",
        "These commands align with the corrected Scenario 1 runtime style:",
        "- outer transport: strongSwan `swanctl` with xfrm interfaces",
        "- inner service tunnel: strongSwan `swanctl` with PSK auth",
        "- routing: Linux iproute2",
        "",
        "## Required Validation Areas",
        "",
        "- both customer-router outer tunnels established",
        "- both customer-router inner tunnels established",
        "- CGNAT ISP node forwarding/transit behavior confirmed",
        "- backend responder behavior confirmed",
        "- GRE handoff visible on the hosted CGNAT HEAD END",
        "- request and reply path visible for the base customer-facing public IP",
        "",
        "## Example Checks",
        "",
        "On the CGNAT HEAD END:",
        "```bash",
        "sudo swanctl --list-sas",
        "ip -d link show type xfrm",
        "ip tunnel show",
        "ip route get " + package["validation_targets"]["customer_facing_public_ip"],
        "```",
        "",
        "On the CGNAT ISP HEAD END:",
        "```bash",
        "sysctl net.ipv4.ip_forward",
        "sudo nft list ruleset | sed -n '/cgnat_scenario1/,$p'",
        "```",
        "",
    ]
    for router in package["validation_targets"]["customer_routers"]:
        lines.extend(
            [
                f"On `{router['role']}`:",
                "```bash",
                "sudo swanctl --list-sas",
                "ip -d link show type xfrm",
                "ip -d link show type dummy",
                f"# customer loopback identity: {router['customer_loopback_ip']}",
                f"# interesting traffic identity: {router['known_inside_identity']}",
                f"# destination public IP: {package['validation_targets']['customer_facing_public_ip']}",
                f"# reachable inner-tunnel destinations: {', '.join(package['backend_expectations'].get('service_reachable_subnets') or [])}",
                "```",
                "",
            ]
        )
    downstream_validation = package["validation_targets"].get("downstream_validation")
    if isinstance(downstream_validation, dict):
        source_identities = list(downstream_validation.get("source_identities") or [])
        downstream_subnets = ", ".join(str(value) for value in downstream_validation.get("downstream_reachable_subnets") or [])
        source_labels = ", ".join(
            f"{entry['role']}={entry['source_identity']}"
            for entry in source_identities
            if isinstance(entry, dict) and entry.get("role") and entry.get("source_identity")
        )
        lines.extend(
            [
                "For downstream SmartGateway validation:",
                "```bash",
                f"# downstream reachable subnets: {downstream_subnets}",
                f"# customer source identities: {source_labels}",
                "# On SmartGateway 3, confirm outbound IPsec/xfrm encrypt counters increase",
                "# for each original customer identity while traffic is generated.",
                "# Replies are optional for this downstream check as long as encrypts move",
                "# for every customer identity listed above.",
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


def _render_strongswan_settings() -> str:
    return "\n".join(
        [
            "# Scenario 1 strongSwan runtime settings",
            "# Route ownership stays with the explicit xfrm/route scripts.",
            "charon {",
            "  install_routes = no",
            "}",
            "charon-systemd {",
            "  install_routes = no",
            "}",
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
            "runtime_style": _strongswan_runtime_style(),
            "head_end": head_runtime,
            "isp_head_end": isp_runtime,
            "customer_vpn_routers": customer_router_runtimes,
        },
    )
    dump_text(output_dir / "cgnat-head-end-swanctl.conf", _render_head_end_swanctl_conf(head_runtime))
    dump_text(output_dir / "cgnat-head-end-strongswan.conf", _render_strongswan_settings())
    dump_text(output_dir / "cgnat-isp-head-end-swanctl.conf", _render_isp_head_end_ipsec_conf(package))
    dump_text(output_dir / "cgnat-head-end-xfrm.sh", _render_head_end_xfrm_script(head_runtime))
    dump_text(output_dir / "cgnat-head-end-gre.sh", _render_head_end_gre_script())
    dump_text(output_dir / "cgnat-head-end-routes.sh", _render_head_end_route_script())
    dump_text(output_dir / "cgnat-head-end-forwarding.sh", _render_head_end_forwarding_script("cgnat-head-end-runtime.env"))
    dump_text(output_dir / "cgnat-isp-head-end-forwarding.sh", _render_isp_head_end_forwarding_script())
    dump_text(output_dir / "cgnat-head-end-runtime.env", _render_head_end_runtime_env(head_runtime))
    dump_text(output_dir / "cgnat-isp-head-end-runtime.env", _render_isp_head_end_runtime_env(isp_runtime))
    for router_runtime in customer_router_runtimes:
        role = router_runtime["role"]
        dump_text(output_dir / f"{role}-outer-swanctl.conf", _render_customer_router_outer_swanctl_conf(router_runtime))
        dump_text(output_dir / f"{role}-inner-swanctl.conf", _render_customer_router_inner_swanctl_conf(router_runtime))
        dump_text(output_dir / f"{role}-strongswan.conf", _render_strongswan_settings())
        dump_text(output_dir / f"{role}-xfrm.sh", _render_customer_router_xfrm_script(router_runtime))
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
                "- strongSwan `swanctl.conf` fragments for the hosted head end and both customer routers",
                "- xfrm-interface scripts for route-based outer transport",
                "- customer-router scripts that keep loopback tunnel identity separate from the service IP owner interface",
                "- CGNAT ISP head-end transit-only config and route scripts",
                "- runtime input manifests and per-role environment files for apply-time values",
                "- validation guidance included",
                "",
            ]
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
