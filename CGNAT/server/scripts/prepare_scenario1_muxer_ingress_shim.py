from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _server_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _cgnat_root() -> Path:
    return _server_dir().parent


def _framework_src() -> Path:
    return _cgnat_root() / "framework" / "src"


def _load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _extract_head_end_private_ip(aws_apply: dict[str, Any]) -> str:
    instances = (((aws_apply.get("head_end") or {}).get("response") or {}).get("Instances") or [])
    if not instances:
        raise ValueError("aws apply result is missing head_end response instances")
    private_ip = str(instances[0].get("PrivateIpAddress") or "").strip()
    if not private_ip:
        raise ValueError("aws apply result is missing head_end private IP")
    return private_ip


def _extract_selected_targets(summary: dict[str, Any]) -> dict[str, Any]:
    for record in list(summary.get("request_records") or []):
        targets = ((record.get("deploy_plan") or {}).get("selected_targets") or {})
        if targets:
            return targets
    raise ValueError("backend integration summary is missing selected target metadata")


def _extract_backend_head_end_private_ip(summary: dict[str, Any]) -> str:
    targets = _extract_selected_targets(summary)
    private_ip = str((((targets.get("headend_active") or {}).get("selector") or {}).get("private_ip")) or "").strip()
    if not private_ip:
        raise ValueError("backend integration summary is missing headend active private IP")
    return private_ip


def _extract_muxer_addresses(bundle: dict[str, Any], summary: dict[str, Any]) -> tuple[str, str]:
    targets = _extract_selected_targets(summary)
    selector = (targets.get("muxer") or {}).get("selector") or {}
    backend_selection = dict(bundle["sot"]["backend_selection"])
    preferred_class = str(backend_selection.get("preferred_class") or "").strip()
    operations_candidates = list((bundle["operations"]["backend_vpn_head_ends"] or {}).get(preferred_class) or [])
    handoff_remote = ""
    if operations_candidates:
        handoff_remote = str(operations_candidates[0].get("cgnat_handoff_remote") or "").strip()
    private_ip = handoff_remote or str(selector.get("private_ip") or "").strip()
    public_ip = str(selector.get("public_ip") or "").strip()
    if not private_ip or not public_ip:
        raise ValueError("backend integration summary is missing muxer private/public IP metadata")
    return private_ip, public_ip


def _extract_customer_peers(bundle: dict[str, Any]) -> list[dict[str, str]]:
    routers = {str(router.get("role") or "").strip(): router for router in list(bundle["operations"].get("customer_vpn_routers") or [])}
    peers: list[dict[str, str]] = []
    for device in list(bundle["sot"].get("customer_devices") or []):
        router_role = str(device.get("router_role") or "").strip()
        router = routers.get(router_role) or {}
        peer_ip = str(router.get("private_ip_address") or "").strip()
        if not peer_ip:
            raise ValueError(f"missing private_ip_address for customer router role {router_role!r}")
        peers.append(
            {
                "router_role": router_role,
                "peer_ip": peer_ip,
                "customer_loopback_ip": str(device.get("customer_loopback_ip") or "").strip(),
            }
        )
    if not peers:
        raise ValueError("bundle contains no customer devices")
    return peers


def _render_runtime_inputs(bundle: dict[str, Any], summary: dict[str, Any], aws_apply: dict[str, Any]) -> dict[str, Any]:
    muxer_private_ip, muxer_public_ip = _extract_muxer_addresses(bundle, summary)
    backend_head_end_private_ip = _extract_backend_head_end_private_ip(summary)
    return {
        "service_id": bundle["sot"]["service_id"],
        "muxer": {
            "inside_ip": muxer_private_ip,
            "public_ip": muxer_public_ip,
            "shim_interface": "cgs1mi0",
            "shim_table_inet": "cgnat_muxer_ingress_s1",
            "shim_table_ip": "cgnat_muxer_ingress_s1_nat",
        },
        "cgnat_head_end": {
            "private_ip": _extract_head_end_private_ip(aws_apply),
        },
        "backend_head_end": {
            "private_ip": backend_head_end_private_ip,
        },
        "customer_peers": _extract_customer_peers(bundle),
    }


def _render_nftables_apply(runtime: dict[str, Any]) -> str:
    muxer = runtime["muxer"]
    backend_ip = runtime["backend_head_end"]["private_ip"]
    public_ip = muxer["public_ip"]
    peers = runtime["customer_peers"]

    peer_list = ", ".join(peer["peer_ip"] for peer in peers)
    natd_in_pairs = ", ".join(f"{peer['peer_ip']} . {public_ip}" for peer in peers)
    natd_out_pairs = ", ".join(f"{backend_ip} . {peer['peer_ip']}" for peer in peers)
    dnat_map = ", ".join(f"{peer['peer_ip']} : {backend_ip}" for peer in peers)
    snat_map = ", ".join(f"{backend_ip} . {peer['peer_ip']} : {public_ip}" for peer in peers)

    return "\n".join(
        [
            f"table inet {muxer['shim_table_inet']} {{",
            "  set public_destinations {",
            "    type ipv4_addr",
            f"    elements = {{ {public_ip} }}",
            "  }",
            "  set udp500_accept_peers {",
            "    type ipv4_addr",
            f"    elements = {{ {peer_list} }}",
            "  }",
            "  set udp4500_accept_peers {",
            "    type ipv4_addr",
            f"    elements = {{ {peer_list} }}",
            "  }",
            "  set esp_accept_peers {",
            "    type ipv4_addr",
            f"    elements = {{ {peer_list} }}",
            "  }",
            "  set natd_in_pairs {",
            "    type ipv4_addr . ipv4_addr",
            f"    elements = {{ {natd_in_pairs} }}",
            "  }",
            "  set natd_out_pairs {",
            "    type ipv4_addr . ipv4_addr",
            f"    elements = {{ {natd_out_pairs} }}",
            "  }",
            "  chain prerouting_bridge {",
            "    type filter hook prerouting priority -151; policy accept;",
            f"    iifname \"{muxer['shim_interface']}\" udp dport 500 ip saddr . ip daddr @natd_in_pairs queue num 2111 bypass",
            "  }",
            "  chain postrouting_bridge {",
            "    type filter hook postrouting priority -151; policy accept;",
            f"    oifname \"{muxer['shim_interface']}\" udp sport 500 udp dport 500 ip saddr . ip daddr @natd_out_pairs queue num 2112 bypass",
            "  }",
            "  chain forward_filter {",
            "    type filter hook forward priority filter; policy accept;",
            "    ct state established,related accept",
            f"    iifname \"{muxer['shim_interface']}\" ip daddr @public_destinations udp dport 500 ip saddr @udp500_accept_peers accept",
            f"    iifname \"{muxer['shim_interface']}\" ip daddr @public_destinations udp dport 4500 ip saddr @udp4500_accept_peers accept",
            f"    iifname \"{muxer['shim_interface']}\" ip daddr @public_destinations ip protocol esp ip saddr @esp_accept_peers accept",
            f"    iifname \"{muxer['shim_interface']}\" ip daddr @public_destinations udp dport 500 drop",
            f"    iifname \"{muxer['shim_interface']}\" ip daddr @public_destinations udp dport 4500 drop",
            f"    iifname \"{muxer['shim_interface']}\" ip daddr @public_destinations ip protocol esp drop",
            "  }",
            "}",
            "",
            f"table ip {muxer['shim_table_ip']} {{",
            "  set public_destinations {",
            "    type ipv4_addr",
            f"    elements = {{ {public_ip} }}",
            "  }",
            "  map udp500_dnat {",
            "    type ipv4_addr : ipv4_addr",
            f"    elements = {{ {dnat_map} }}",
            "  }",
            "  map udp4500_dnat {",
            "    type ipv4_addr : ipv4_addr",
            f"    elements = {{ {dnat_map} }}",
            "  }",
            "  map esp_dnat {",
            "    type ipv4_addr : ipv4_addr",
            f"    elements = {{ {dnat_map} }}",
            "  }",
            "  map udp500_snat {",
            "    type ipv4_addr . ipv4_addr : ipv4_addr",
            f"    elements = {{ {snat_map} }}",
            "  }",
            "  map udp4500_snat {",
            "    type ipv4_addr . ipv4_addr : ipv4_addr",
            f"    elements = {{ {snat_map} }}",
            "  }",
            "  map esp_snat {",
            "    type ipv4_addr . ipv4_addr : ipv4_addr",
            f"    elements = {{ {snat_map} }}",
            "  }",
            "  chain prerouting_nat {",
            "    type nat hook prerouting priority dstnat; policy accept;",
            f"    iifname \"{muxer['shim_interface']}\" ip daddr @public_destinations udp dport 500 dnat to ip saddr map @udp500_dnat",
            f"    iifname \"{muxer['shim_interface']}\" ip daddr @public_destinations udp dport 4500 dnat to ip saddr map @udp4500_dnat",
            f"    iifname \"{muxer['shim_interface']}\" ip daddr @public_destinations ip protocol esp dnat to ip saddr map @esp_dnat",
            "  }",
            "  chain postrouting_nat {",
            "    type nat hook postrouting priority srcnat; policy accept;",
            f"    oifname \"{muxer['shim_interface']}\" udp sport 500 snat to ip saddr . ip daddr map @udp500_snat",
            f"    oifname \"{muxer['shim_interface']}\" udp sport 4500 snat to ip saddr . ip daddr map @udp4500_snat",
            f"    oifname \"{muxer['shim_interface']}\" ip protocol esp snat to ip saddr . ip daddr map @esp_snat",
            "  }",
            "}",
            "",
        ]
    )


def _render_nftables_remove(runtime: dict[str, Any]) -> str:
    muxer = runtime["muxer"]
    return "\n".join(
        [
            f"delete table ip {muxer['shim_table_ip']}",
            f"delete table inet {muxer['shim_table_inet']}",
            "",
        ]
    )


def _render_apply_sh(runtime: dict[str, Any]) -> str:
    route_lines = []
    for peer in runtime["customer_peers"]:
        route_lines.append(f"ip route replace {peer['peer_ip']}/32 dev \"$CGNAT_MUXER_SHIM_INTERFACE\"")
    routes = "\n".join(route_lines)
    return f"""#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
. "$SCRIPT_DIR/runtime.env"

ip tunnel del "$CGNAT_MUXER_SHIM_INTERFACE" 2>/dev/null || true
ip tunnel add "$CGNAT_MUXER_SHIM_INTERFACE" mode gre local "$CGNAT_MUXER_INSIDE_IP" remote "$CGNAT_HEAD_END_PRIVATE_IP" ttl 255
ip link set "$CGNAT_MUXER_SHIM_INTERFACE" up mtu 8973
{routes}
nft -f "$SCRIPT_DIR/nftables.apply.nft"
"""


def _render_rollback_sh(runtime: dict[str, Any]) -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/runtime.env"

nft -f "$SCRIPT_DIR/nftables.remove.nft" 2>/dev/null || true
for peer in $CGNAT_CUSTOMER_PEER_IPS; do
  ip route del "$peer/32" dev "$CGNAT_MUXER_SHIM_INTERFACE" 2>/dev/null || true
done
ip tunnel del "$CGNAT_MUXER_SHIM_INTERFACE" 2>/dev/null || true
"""


def _render_preflight_sh(runtime: dict[str, Any]) -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/runtime.env"

command -v ip >/dev/null
command -v nft >/dev/null
python3 - <<'PY'
import ipaddress
import os
for value in (
    os.environ["CGNAT_MUXER_INSIDE_IP"],
    os.environ["CGNAT_MUXER_PUBLIC_IP"],
    os.environ["CGNAT_HEAD_END_PRIVATE_IP"],
    os.environ["CGNAT_BACKEND_HEAD_END_PRIVATE_IP"],
):
    ipaddress.ip_address(value)
for value in os.environ["CGNAT_CUSTOMER_PEER_IPS"].split():
    ipaddress.ip_address(value)
PY
echo "Preflight OK for muxer ingress shim"
"""


def _render_runtime_env(runtime: dict[str, Any]) -> str:
    peer_ips = " ".join(peer["peer_ip"] for peer in runtime["customer_peers"])
    muxer = runtime["muxer"]
    return "\n".join(
        [
            f'export CGNAT_SERVICE_ID="{runtime["service_id"]}"',
            f'export CGNAT_MUXER_INSIDE_IP="{muxer["inside_ip"]}"',
            f'export CGNAT_MUXER_PUBLIC_IP="{muxer["public_ip"]}"',
            f'export CGNAT_MUXER_SHIM_INTERFACE="{muxer["shim_interface"]}"',
            f'export CGNAT_HEAD_END_PRIVATE_IP="{runtime["cgnat_head_end"]["private_ip"]}"',
            f'export CGNAT_BACKEND_HEAD_END_PRIVATE_IP="{runtime["backend_head_end"]["private_ip"]}"',
            f'export CGNAT_CUSTOMER_PEER_IPS="{peer_ips}"',
            "",
        ]
    )


def _render_readme(runtime: dict[str, Any]) -> str:
    lines = [
        "# Scenario 1 Muxer Ingress Shim",
        "",
        "This bundle installs the CGNAT-owned muxer ingress shim for Scenario 1.",
        "",
        "It adds:",
        f"- a receive GRE interface from the CGNAT head end (`{runtime['muxer']['shim_interface']}`)",
        "- host routes for the customer router WAN IPs back through that interface",
        "- nftables bridge/NAT rules scoped to those customer peers only",
        "",
        "Generated customer peers:",
        "",
    ]
    for peer in runtime["customer_peers"]:
        lines.append(f"- `{peer['router_role']}` -> `{peer['peer_ip']}` (loopback `{peer['customer_loopback_ip']}`)")
    lines.extend(
        [
            "",
            "Apply order:",
            "",
            "1. `sudo bash ./preflight.sh`",
            "2. `sudo bash ./apply.sh`",
            "3. validate inner IKE on the backend and return traffic on the shim interface",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    sys.path.insert(0, str(_framework_src()))
    from cgnat.bundle import dump_json, dump_text, ensure_path_within_cgnat  # noqa: WPS433

    parser = argparse.ArgumentParser(description="Prepare the Scenario 1 muxer ingress shim host bundle.")
    parser.add_argument("bundle_json", help="Path to the CGNAT deployment bundle JSON.")
    parser.add_argument("backend_integration_summary_json", help="Path to backend-integration-summary.json.")
    parser.add_argument("aws_apply_result_json", help="Path to the live AWS apply result JSON.")
    parser.add_argument("output_dir", help="Output directory for the muxer shim bundle.")
    args = parser.parse_args()

    bundle = _load_json(args.bundle_json)
    summary = _load_json(args.backend_integration_summary_json)
    aws_apply = _load_json(args.aws_apply_result_json)

    runtime = _render_runtime_inputs(bundle, summary, aws_apply)
    output_dir = ensure_path_within_cgnat(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    dump_json(output_dir / "runtime-inputs.json", runtime)
    dump_text(output_dir / "runtime.env", _render_runtime_env(runtime))
    dump_text(output_dir / "nftables.apply.nft", _render_nftables_apply(runtime))
    dump_text(output_dir / "nftables.remove.nft", _render_nftables_remove(runtime))
    dump_text(output_dir / "preflight.sh", _render_preflight_sh(runtime))
    dump_text(output_dir / "apply.sh", _render_apply_sh(runtime))
    dump_text(output_dir / "rollback.sh", _render_rollback_sh(runtime))
    dump_text(output_dir / "README.md", _render_readme(runtime))
    dump_json(
        output_dir / "package-manifest.json",
        {
            "service_id": runtime["service_id"],
            "target_role": "muxer_ingress_shim",
            "customer_peer_count": len(runtime["customer_peers"]),
            "shim_interface": runtime["muxer"]["shim_interface"],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
