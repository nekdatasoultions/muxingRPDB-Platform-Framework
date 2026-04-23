"""Shared helpers for customer-scoped head-end staging and validation."""

from __future__ import annotations

import json
import ipaddress
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PLACEHOLDER_RE = re.compile(r"\$\{[^}]+\}")
HEADEND_REQUIRED_FILES = (
    "ipsec/ipsec-intent.json",
    "ipsec/swanctl-connection.conf",
    "ipsec/initiation-intent.json",
    "ipsec/initiate-tunnel.sh",
    "transport/transport-intent.json",
    "transport/apply-transport.sh",
    "transport/remove-transport.sh",
    "public-identity/public-identity-intent.json",
    "public-identity/apply-public-identity.sh",
    "public-identity/remove-public-identity.sh",
    "routing/routing-intent.json",
    "routing/ip-route.commands.txt",
    "post-ipsec-nat/post-ipsec-nat-intent.json",
    "post-ipsec-nat/nftables.apply.nft",
    "post-ipsec-nat/nftables.remove.nft",
    "post-ipsec-nat/nftables-state.json",
    "post-ipsec-nat/activation-manifest.json",
    "outside-nat/outside-nat-intent.json",
    "outside-nat/nftables.apply.nft",
    "outside-nat/nftables.remove.nft",
    "outside-nat/nftables-state.json",
    "outside-nat/activation-manifest.json",
)

HEADEND_STATE_ROOT = Path("var") / "lib" / "rpdb-headend" / "customers"
SWANCTL_CONF_ROOT = Path("etc") / "swanctl" / "conf.d" / "rpdb-customers"


@dataclass(frozen=True)
class HeadendBundle:
    bundle_dir: Path
    customer_name: str
    customer_module: dict[str, Any]
    headend_dir: Path
    source_files: dict[str, Path]
    text_payloads: dict[str, str]
    json_payloads: dict[str, dict[str, Any]]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload if payload.endswith("\n") else payload + "\n")


def _make_executable(path: Path) -> None:
    try:
        path.chmod(path.stat().st_mode | 0o111)
    except OSError:
        pass


def load_headend_bundle(bundle_dir: Path) -> HeadendBundle:
    resolved_bundle = bundle_dir.resolve()
    customer_module_path = resolved_bundle / "customer" / "customer-module.json"
    if not customer_module_path.exists():
        raise ValueError(f"bundle missing customer/customer-module.json: {customer_module_path}")

    customer_module = _load_json(customer_module_path)
    customer = customer_module.get("customer") or {}
    customer_name = str(customer.get("name") or "").strip()
    if not customer_name:
        raise ValueError(f"bundle customer-module.json missing customer.name: {customer_module_path}")

    headend_dir = resolved_bundle / "headend"
    if not headend_dir.is_dir():
        raise ValueError(f"bundle missing headend directory: {headend_dir}")

    source_files: dict[str, Path] = {}
    text_payloads: dict[str, str] = {}
    json_payloads: dict[str, dict[str, Any]] = {}
    missing: list[str] = []

    for relative_name in HEADEND_REQUIRED_FILES:
        source_path = headend_dir / relative_name
        if not source_path.exists():
            missing.append(relative_name)
            continue
        source_files[relative_name] = source_path
        if source_path.suffix == ".json":
            json_payloads[relative_name] = _load_json(source_path)
        else:
            text_payloads[relative_name] = source_path.read_text(encoding="utf-8")

    if missing:
        raise ValueError("bundle missing required headend files: " + ", ".join(missing))

    return HeadendBundle(
        bundle_dir=resolved_bundle,
        customer_name=customer_name,
        customer_module=customer_module,
        headend_dir=headend_dir,
        source_files=source_files,
        text_payloads=text_payloads,
        json_payloads=json_payloads,
    )


def _find_placeholders(text: str) -> list[str]:
    return sorted(set(PLACEHOLDER_RE.findall(text)))


def _find_json_placeholders(payload: dict[str, Any]) -> list[str]:
    return _find_placeholders(json.dumps(payload, sort_keys=True))


def _executable_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def validate_headend_bundle(bundle_dir: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "bundle_dir": str(bundle_dir.resolve()),
        "customer_name": None,
        "errors": [],
        "warnings": [],
        "details": {},
        "valid": False,
    }

    try:
        bundle = load_headend_bundle(bundle_dir)
    except Exception as exc:
        report["errors"].append(str(exc))
        return report

    report["customer_name"] = bundle.customer_name

    swanctl_text = bundle.text_payloads["ipsec/swanctl-connection.conf"]
    initiate_script_text = bundle.text_payloads["ipsec/initiate-tunnel.sh"]
    transport_apply_text = bundle.text_payloads["transport/apply-transport.sh"]
    transport_remove_text = bundle.text_payloads["transport/remove-transport.sh"]
    public_identity_apply_text = bundle.text_payloads["public-identity/apply-public-identity.sh"]
    public_identity_remove_text = bundle.text_payloads["public-identity/remove-public-identity.sh"]
    route_text = bundle.text_payloads["routing/ip-route.commands.txt"]
    nft_apply_text = bundle.text_payloads["post-ipsec-nat/nftables.apply.nft"]
    nft_remove_text = bundle.text_payloads["post-ipsec-nat/nftables.remove.nft"]
    outside_nft_apply_text = bundle.text_payloads["outside-nat/nftables.apply.nft"]
    outside_nft_remove_text = bundle.text_payloads["outside-nat/nftables.remove.nft"]
    ipsec_intent = bundle.json_payloads["ipsec/ipsec-intent.json"]
    initiation_intent = bundle.json_payloads["ipsec/initiation-intent.json"]
    transport_intent = bundle.json_payloads["transport/transport-intent.json"]
    public_identity_intent = bundle.json_payloads["public-identity/public-identity-intent.json"]
    routing_intent = bundle.json_payloads["routing/routing-intent.json"]
    nat_intent = bundle.json_payloads["post-ipsec-nat/post-ipsec-nat-intent.json"]
    activation_manifest = bundle.json_payloads["post-ipsec-nat/activation-manifest.json"]
    nft_state = bundle.json_payloads["post-ipsec-nat/nftables-state.json"]
    outside_nat_intent = bundle.json_payloads["outside-nat/outside-nat-intent.json"]
    outside_activation_manifest = bundle.json_payloads["outside-nat/activation-manifest.json"]
    outside_nft_state = bundle.json_payloads["outside-nat/nftables-state.json"]

    text_checks = {
        "ipsec/swanctl-connection.conf": swanctl_text,
        "ipsec/initiate-tunnel.sh": initiate_script_text,
        "transport/apply-transport.sh": transport_apply_text,
        "transport/remove-transport.sh": transport_remove_text,
        "public-identity/apply-public-identity.sh": public_identity_apply_text,
        "public-identity/remove-public-identity.sh": public_identity_remove_text,
        "routing/ip-route.commands.txt": route_text,
        "post-ipsec-nat/nftables.apply.nft": nft_apply_text,
        "post-ipsec-nat/nftables.remove.nft": nft_remove_text,
        "outside-nat/nftables.apply.nft": outside_nft_apply_text,
        "outside-nat/nftables.remove.nft": outside_nft_remove_text,
    }

    for relative_name, payload in text_checks.items():
        unresolved = _find_placeholders(payload)
        if unresolved:
            report["errors"].append(
                f"headend file has unresolved placeholders: {relative_name} -> {', '.join(unresolved)}"
            )
        lowered = payload.lower()
        if "iptables" in lowered or "iptables-restore" in lowered:
            report["errors"].append(
                f"headend file contains banned runtime token: {relative_name}"
            )

    for relative_name, payload in bundle.json_payloads.items():
        unresolved = _find_json_placeholders(payload)
        if unresolved:
            report["errors"].append(
                f"headend JSON file has unresolved placeholders: {relative_name} -> {', '.join(unresolved)}"
            )

    if "connections {" not in swanctl_text or "secrets {" not in swanctl_text:
        report["errors"].append("swanctl-connection.conf is missing required connections/secrets blocks")
    expected_secret_section = f"  ike-{bundle.customer_name}-psk {{"
    unsupported_secret_section = f"  {bundle.customer_name}-psk {{"
    if expected_secret_section not in swanctl_text:
        report["errors"].append(
            "swanctl-connection.conf must render IKE PSK secrets under secrets.ike<suffix>"
        )
    if unsupported_secret_section in swanctl_text:
        report["errors"].append(
            "swanctl-connection.conf renders an unsupported non-ike PSK secret section"
        )

    initiation = ipsec_intent.get("initiation") or {}
    start_action = str(initiation_intent.get("swanctl_start_action") or "").strip()
    if initiation and initiation != initiation_intent:
        comparable_intent = {
            key: initiation_intent.get(key)
            for key in initiation
        }
        if comparable_intent != initiation:
            report["errors"].append("ipsec initiation intent does not match ipsec-intent.json")
    if initiation_intent.get("mode") == "bidirectional":
        if not initiation_intent.get("headend_can_initiate"):
            report["errors"].append("bidirectional IPsec requires headend_can_initiate=true")
        if not initiation_intent.get("customer_can_initiate"):
            report["errors"].append("bidirectional IPsec requires customer_can_initiate=true")
    if initiation_intent.get("traffic_can_start_tunnel") and "trap" not in start_action:
        report["errors"].append(
            "traffic-triggered tunnel initiation requires swanctl start_action to include trap"
        )
    if initiation_intent.get("bring_up_on_apply") and "start" not in start_action:
        report["errors"].append(
            "head-end bring-up on apply requires swanctl start_action to include start"
        )
    expected_start_action = f"start_action = {start_action}"
    if start_action and expected_start_action not in swanctl_text:
        report["errors"].append(
            f"swanctl-connection.conf missing rendered initiation action: {expected_start_action}"
        )
    if initiation_intent.get("customer_can_initiate"):
        expected_remote = f"remote_addrs = {ipsec_intent.get('peer_public_ip')}"
        if expected_remote not in swanctl_text:
            report["errors"].append(
                "customer-initiated tunnel bring-up requires swanctl remote_addrs to match the peer"
            )
    if initiation_intent.get("headend_can_initiate"):
        if "swanctl --initiate --child" not in initiate_script_text:
            report["errors"].append(
                "head-end initiation script must call swanctl --initiate --child"
            )
        if str(initiation_intent.get("child") or "") not in initiate_script_text:
            report["errors"].append("head-end initiation script must target the rendered child name")

    selector_intent = ipsec_intent.get("selectors") or {}
    effective_remote_ts = [
        str(value)
        for value in (selector_intent.get("effective_remote_ts") or [])
        if str(value).strip()
    ]
    if not effective_remote_ts:
        effective_remote_ts = [
            str(value)
            for value in (selector_intent.get("remote_subnets") or [])
            if str(value).strip()
        ]
    expected_remote_ts = f"remote_ts = {','.join(effective_remote_ts)}"
    if effective_remote_ts and expected_remote_ts not in swanctl_text:
        report["errors"].append(
            f"swanctl-connection.conf missing effective remote_ts selector: {expected_remote_ts}"
        )
    if selector_intent.get("remote_host_cidrs"):
        report["details"]["effective_remote_ts_source"] = selector_intent.get("effective_remote_ts_source")
        report["details"]["scoped_customer_cidrs"] = selector_intent.get("scoped_customer_cidrs") or []
        if selector_intent.get("effective_remote_ts_source") != "remote_subnets":
            report["errors"].append(
                "remote_host_cidrs must not override the customer encryption-domain remote_subnets"
            )
        if selector_intent.get("scoped_customer_cidrs") != selector_intent.get("remote_host_cidrs"):
            report["errors"].append("remote_host_cidrs must be preserved as scoped customer CIDRs")

    route_lines = _executable_lines(route_text)
    transport_apply_lines = _executable_lines(transport_apply_text)
    transport_remove_lines = _executable_lines(transport_remove_text)
    public_identity_apply_lines = _executable_lines(public_identity_apply_text)
    public_identity_remove_lines = _executable_lines(public_identity_remove_text)
    nft_apply_lines = _executable_lines(nft_apply_text)
    nft_remove_lines = _executable_lines(nft_remove_text)
    outside_nft_apply_lines = _executable_lines(outside_nft_apply_text)
    outside_nft_remove_lines = _executable_lines(outside_nft_remove_text)
    report["details"]["route_command_count"] = len(route_lines)
    report["details"]["headend_transport_enabled"] = transport_intent.get("enabled")
    report["details"]["headend_transport_interface"] = transport_intent.get("interface")
    report["details"]["headend_transport_type"] = transport_intent.get("type")
    report["details"]["headend_transport_peer_route"] = transport_intent.get("peer_public_cidr")
    report["details"]["public_identity_enabled"] = public_identity_intent.get("enabled")
    report["details"]["public_identity_cidr"] = public_identity_intent.get("cidr")
    report["details"]["post_ipsec_nat_command_count"] = int(activation_manifest.get("apply_command_count") or 0)
    report["details"]["post_ipsec_nat_rollback_command_count"] = int(activation_manifest.get("rollback_command_count") or 0)
    report["details"]["outside_nat_command_count"] = int(outside_activation_manifest.get("apply_command_count") or 0)
    report["details"]["outside_nat_rollback_command_count"] = int(outside_activation_manifest.get("rollback_command_count") or 0)
    report["details"]["ipsec_ike_version"] = ipsec_intent.get("ike_version")
    report["details"]["ipsec_initiation_mode"] = initiation_intent.get("mode")
    report["details"]["ipsec_start_action"] = initiation_intent.get("swanctl_start_action")
    report["details"]["headend_can_initiate"] = initiation_intent.get("headend_can_initiate")
    report["details"]["customer_can_initiate"] = initiation_intent.get("customer_can_initiate")
    report["details"]["post_ipsec_nat_mapping_strategy"] = nat_intent.get("mapping_strategy")
    report["details"]["post_ipsec_nat_command_model"] = nat_intent.get("rendered_command_model")
    report["details"]["post_ipsec_nat_activation_backend"] = activation_manifest.get("backend")
    report["details"]["post_ipsec_nat_table_name"] = activation_manifest.get("table_name")
    report["details"]["outside_nat_mapping_strategy"] = outside_nat_intent.get("mapping_strategy")
    report["details"]["outside_nat_command_model"] = outside_nat_intent.get("rendered_command_model")
    report["details"]["outside_nat_activation_backend"] = outside_activation_manifest.get("backend")
    report["details"]["outside_nat_table_name"] = outside_activation_manifest.get("table_name")

    module_transport = (bundle.customer_module.get("transport") or {})
    module_overlay = module_transport.get("overlay") or {}
    if not transport_intent.get("enabled"):
        report["errors"].append("head-end transport intent must be enabled for customer-scoped GRE return path")
    if transport_intent.get("type") != "gre":
        report["errors"].append("head-end transport intent must use GRE")
    transport_expectations = {
        "interface": module_transport.get("interface"),
        "tunnel_key": module_transport.get("tunnel_key"),
        "tunnel_ttl": module_transport.get("tunnel_ttl"),
        "router_overlay_ip": module_overlay.get("router_ip"),
        "mux_overlay_ip": module_overlay.get("mux_ip"),
    }
    for key, expected in transport_expectations.items():
        if expected not in (None, "") and str(transport_intent.get(key)) != str(expected):
            report["errors"].append(
                f"head-end transport intent {key} does not match customer module transport"
            )
    mux_overlay_ip = str(transport_intent.get("mux_overlay_ip") or "").strip()
    if mux_overlay_ip:
        expected_mux_overlay_host = str(ipaddress.ip_interface(mux_overlay_ip).ip)
        if transport_intent.get("mux_overlay_host") != expected_mux_overlay_host:
            report["errors"].append("head-end transport intent mux_overlay_host does not match mux_overlay_ip")
    transport_payload = "\n".join([*transport_apply_lines, *transport_remove_lines])
    for expected_fragment in (
        'ip tunnel add "$IFNAME" mode gre local "$LOCAL_UL" remote "$REMOTE_UL" key "$KEY" ttl "$TTL"',
        'ip addr replace "$ROUTER_IP" dev "$IFNAME"',
        'ip link set "$IFNAME" up',
        'ip route replace "$PEER_CIDR" via "$MUX_OVERLAY_HOST" dev "$IFNAME"',
        'ip route del "$PEER_CIDR" dev "$IFNAME" 2>/dev/null || true',
        'ip link del "$IFNAME" 2>/dev/null || true',
    ):
        if expected_fragment not in transport_payload:
            report["errors"].append(
                f"head-end transport scripts missing required GRE operation: {expected_fragment}"
            )

    if not public_identity_intent.get("enabled"):
        report["errors"].append("public identity intent must be enabled for RPDB head-end IPsec identity")
    public_identity_cidr = str(public_identity_intent.get("cidr") or "").strip()
    public_identity_ip = str(public_identity_intent.get("public_ip") or "").strip()
    public_identity_device = str(public_identity_intent.get("device") or "").strip()
    if public_identity_cidr:
        try:
            parsed_public_identity = ipaddress.ip_interface(public_identity_cidr)
        except ValueError:
            report["errors"].append(f"public identity CIDR is invalid: {public_identity_cidr}")
        else:
            if str(parsed_public_identity.network.prefixlen) != "32":
                report["errors"].append("public identity CIDR must be a /32 loopback address")
            if public_identity_ip and str(parsed_public_identity.ip) != public_identity_ip:
                report["errors"].append("public identity CIDR does not match public_ip")
    if public_identity_device != "lo":
        report["errors"].append("public identity must be installed on lo")
    public_identity_payload = "\n".join([*public_identity_apply_lines, *public_identity_remove_lines])
    if 'ip addr replace "$PUBLIC_CIDR" dev "$DEVICE"' not in public_identity_payload:
        report["errors"].append(
            'public identity scripts missing required loopback operation: ip addr replace "$PUBLIC_CIDR" dev "$DEVICE"'
        )
    if "Shared head-end public identity is retained on customer removal." not in public_identity_remove_text:
        report["errors"].append("public identity remove script must retain the shared head-end loopback identity")
    if public_identity_intent.get("remove_policy") != "retain_shared_identity":
        report["errors"].append("public identity remove policy must retain the shared head-end loopback identity")
    if public_identity_ip and ipsec_intent.get("local_id") not in (None, "", public_identity_ip):
        report["errors"].append("IPsec local_id must match the rendered public identity IP")

    if not route_lines:
        report["warnings"].append("routing/ip-route.commands.txt contains no executable route commands")
    peer_public_ip = str(ipsec_intent.get("peer_public_ip") or "").strip()
    if peer_public_ip:
        peer_public_cidr = peer_public_ip if "/" in peer_public_ip else f"{peer_public_ip}/32"
        return_route_lines = [
            line
            for line in route_lines
            if line.startswith(f"ip route replace {peer_public_cidr} via ")
            and " dev " in line
        ]
        edge_return_path = routing_intent.get("edge_return_path") or {}
        report["details"]["edge_return_route"] = return_route_lines[0] if return_route_lines else None
        if not edge_return_path.get("enabled"):
            report["errors"].append("routing-intent.json must mark the muxer edge return path as enabled")
        expected_return_next_hop = str(transport_intent.get("mux_overlay_host") or "").strip()
        expected_return_interface = str(transport_intent.get("interface") or "").strip()
        expected_return_route = (
            f"ip route replace {peer_public_cidr} via {expected_return_next_hop} dev {expected_return_interface}"
        )
        if expected_return_next_hop and expected_return_interface and expected_return_route not in route_lines:
            report["errors"].append(
                f"routing/ip-route.commands.txt missing GRE muxer edge return route: {expected_return_route}"
            )
        if not return_route_lines:
            report["errors"].append(
                f"routing/ip-route.commands.txt missing muxer edge return route for peer {peer_public_cidr}"
            )

    swanctl_expectations = {
        "swanctl_version": f"version = {ipsec_intent.get('swanctl_version')}",
        "local_addrs": f"local_addrs = {ipsec_intent.get('local_addrs')}",
        "rendered_ike_proposals": f"proposals = {ipsec_intent.get('rendered_ike_proposals')}",
        "rendered_esp_proposals": f"esp_proposals = {ipsec_intent.get('rendered_esp_proposals')}",
        "rendered_replay_window": f"replay_window = {ipsec_intent.get('rendered_replay_window')}",
        "rendered_copy_df": f"copy_df = {ipsec_intent.get('rendered_copy_df')}",
    }
    for intent_key, expected_line in swanctl_expectations.items():
        if ipsec_intent.get(intent_key) not in (None, "", []):
            if expected_line not in swanctl_text:
                report["errors"].append(
                    f"swanctl-connection.conf missing rendered {intent_key}: {expected_line}"
                )

    bool_swanctl_expectations = {
        "forceencaps": "encap",
        "mobike": "mobike",
        "fragmentation": "fragmentation",
    }
    for intent_key, swanctl_key in bool_swanctl_expectations.items():
        if ipsec_intent.get(intent_key) is not None:
            expected = f"{swanctl_key} = {'yes' if bool(ipsec_intent.get(intent_key)) else 'no'}"
            if expected not in swanctl_text:
                report["errors"].append(
                    f"swanctl-connection.conf missing rendered {intent_key}: {expected}"
                )

    dpd_expectations = {
        "dpddelay": "dpd_delay",
        "dpdtimeout": "dpd_timeout",
        "dpdaction": "dpd_action",
    }
    for intent_key, swanctl_key in dpd_expectations.items():
        if ipsec_intent.get(intent_key) not in (None, ""):
            expected = f"{swanctl_key} = {ipsec_intent.get(intent_key)}"
            if expected not in swanctl_text:
                report["errors"].append(
                    f"swanctl-connection.conf missing rendered {intent_key}: {expected}"
                )

    if bool(nat_intent.get("enabled")):
        if activation_manifest.get("backend") != "nftables" or nft_state.get("backend") != "nftables":
            report["errors"].append(
                "post-IPsec NAT must use nftables activation artifacts"
            )
        if not nft_apply_lines:
            report["errors"].append(
                "post-IPsec NAT is enabled in the intent, but nftables.apply.nft contains no executable nftables state"
            )
        if not nft_remove_lines:
            report["errors"].append(
                "post-IPsec NAT is enabled in the intent, but nftables.remove.nft contains no executable nftables state"
            )
        nft_payload = "\n".join([*nft_apply_lines, *nft_remove_lines]).lower()
        if "iptables" in nft_payload or "iptables-restore" in nft_payload:
            report["errors"].append("post-IPsec NAT nftables artifacts must not contain iptables fallback commands")
        if "dnat to" not in nft_payload or "snat to" not in nft_payload:
            report["errors"].append("post-IPsec NAT nftables artifacts must include DNAT and SNAT statements")

    if bool(outside_nat_intent.get("enabled")):
        if outside_activation_manifest.get("backend") != "nftables" or outside_nft_state.get("backend") != "nftables":
            report["errors"].append(
                "outside NAT must use nftables activation artifacts"
            )
        if not outside_nft_apply_lines:
            report["errors"].append(
                "outside NAT is enabled in the intent, but nftables.apply.nft contains no executable nftables state"
            )
        if not outside_nft_remove_lines:
            report["errors"].append(
                "outside NAT is enabled in the intent, but nftables.remove.nft contains no executable nftables state"
            )
        outside_nft_payload = "\n".join([*outside_nft_apply_lines, *outside_nft_remove_lines]).lower()
        if "iptables" in outside_nft_payload or "iptables-restore" in outside_nft_payload:
            report["errors"].append("outside NAT nftables artifacts must not contain iptables fallback commands")
        if "dnat to" not in outside_nft_payload or "snat to" not in outside_nft_payload:
            report["errors"].append("outside NAT nftables artifacts must include DNAT and SNAT statements")

    report["valid"] = not report["errors"]
    return report


def build_install_layout(headend_root: Path, customer_name: str) -> dict[str, Path]:
    resolved_root = headend_root.resolve()
    customer_root = resolved_root / HEADEND_STATE_ROOT / customer_name
    return {
        "headend_root": resolved_root,
        "customer_root": customer_root,
        "artifacts_root": customer_root / "artifacts",
        "swanctl_conf": resolved_root / SWANCTL_CONF_ROOT / f"{customer_name}.conf",
        "ipsec_initiation_intent": customer_root / "ipsec" / "initiation-intent.json",
        "ipsec_initiate_script": customer_root / "ipsec" / "initiate-tunnel.sh",
        "transport_intent": customer_root / "transport" / "transport-intent.json",
        "transport_apply_script": customer_root / "transport" / "apply-transport.sh",
        "transport_remove_script": customer_root / "transport" / "remove-transport.sh",
        "public_identity_intent": customer_root / "public-identity" / "public-identity-intent.json",
        "public_identity_apply_script": customer_root / "public-identity" / "apply-public-identity.sh",
        "public_identity_remove_script": customer_root / "public-identity" / "remove-public-identity.sh",
        "route_commands": customer_root / "routing" / "ip-route.commands.txt",
        "route_apply_script": customer_root / "routing" / "apply-routes.sh",
        "route_remove_script": customer_root / "routing" / "remove-routes.sh",
        "nft_apply": customer_root / "post-ipsec-nat" / "nftables.apply.nft",
        "nft_remove": customer_root / "post-ipsec-nat" / "nftables.remove.nft",
        "nft_state": customer_root / "post-ipsec-nat" / "nftables-state.json",
        "activation_manifest": customer_root / "post-ipsec-nat" / "activation-manifest.json",
        "nat_apply_script": customer_root / "post-ipsec-nat" / "apply-post-ipsec-nat.sh",
        "nat_remove_script": customer_root / "post-ipsec-nat" / "remove-post-ipsec-nat.sh",
        "outside_nft_apply": customer_root / "outside-nat" / "nftables.apply.nft",
        "outside_nft_remove": customer_root / "outside-nat" / "nftables.remove.nft",
        "outside_nft_state": customer_root / "outside-nat" / "nftables-state.json",
        "outside_activation_manifest": customer_root / "outside-nat" / "activation-manifest.json",
        "outside_nat_apply_script": customer_root / "outside-nat" / "apply-outside-nat.sh",
        "outside_nat_remove_script": customer_root / "outside-nat" / "remove-outside-nat.sh",
        "master_apply_script": customer_root / "apply-headend-customer.sh",
        "master_remove_script": customer_root / "remove-headend-customer.sh",
        "state_json": customer_root / "install-state.json",
    }


def _derive_route_remove_lines(route_text: str) -> list[str]:
    removals: list[str] = []
    for line in _executable_lines(route_text):
        if line.startswith("ip route replace "):
            removals.append("ip route del " + line.removeprefix("ip route replace ") + " || true")
        elif line.startswith("ip route add "):
            removals.append("ip route del " + line.removeprefix("ip route add ") + " || true")
        else:
            removals.append(f"# manual route cleanup required: {line}")
    return removals


def _render_shell_script(lines: list[str]) -> str:
    return "\n".join(["#!/usr/bin/env bash", "set -eu", *lines]) + "\n"


def _render_nft_apply_script(enabled: bool) -> str:
    if not enabled:
        return _render_shell_script(["true"])
    return _render_shell_script(
        [
            'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
            'NFT_APPLY="${SCRIPT_DIR}/nftables.apply.nft"',
            'NFT_STATE="${SCRIPT_DIR}/nftables-state.json"',
            'NFT_FAMILY="$(python3 -c \'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("table_family") or "ip")\' "${NFT_STATE}")"',
            'NFT_TABLE="$(python3 -c \'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("table_name") or "")\' "${NFT_STATE}")"',
            'if [ -n "${NFT_TABLE}" ] && nft list table "${NFT_FAMILY}" "${NFT_TABLE}" >/dev/null 2>&1; then',
            '  nft delete table "${NFT_FAMILY}" "${NFT_TABLE}"',
            'fi',
            'nft -c -f "${NFT_APPLY}"',
            'nft -f "${NFT_APPLY}"',
        ]
    )


def _render_nft_remove_script(enabled: bool) -> str:
    if not enabled:
        return _render_shell_script(["true"])
    return _render_shell_script(
        [
            'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
            'NFT_REMOVE="${SCRIPT_DIR}/nftables.remove.nft"',
            'nft -f "${NFT_REMOVE}" || true',
        ]
    )


def _render_master_apply_script(layout: dict[str, Path], customer_name: str) -> str:
    customer_root = f"/{HEADEND_STATE_ROOT.as_posix()}/{customer_name}"
    swanctl_conf = f"/{SWANCTL_CONF_ROOT.as_posix()}/{customer_name}.conf"
    swanctl_main = "/etc/swanctl/swanctl.conf"
    return _render_shell_script(
        [
            'ROOT="${RPDB_HEADEND_ROOT:-/}"',
            'ROOT="${ROOT%/}"',
            f'CUSTOMER_ROOT="${{ROOT}}{customer_root}"',
            'CUST="${CUSTOMER_ROOT##*/}"',
            f'SWANCTL_CONF="${{ROOT}}{swanctl_conf}"',
            f'SWANCTL_MAIN="${{ROOT}}{swanctl_main}"',
            'mkdir -p "$(dirname "${SWANCTL_MAIN}")"',
            'if [ ! -f "${SWANCTL_MAIN}" ]; then',
            "  printf 'connections {}\\n\\nsecrets {}\\n\\ninclude conf.d/*.conf\\n' > \"${SWANCTL_MAIN}\"",
            'fi',
            'if ! grep -qxF "include conf.d/rpdb-customers/*.conf" "${SWANCTL_MAIN}"; then',
            "  printf '\\ninclude conf.d/rpdb-customers/*.conf\\n' >> \"${SWANCTL_MAIN}\"",
            'fi',
            'HA_ROLE="$(cat /run/muxingplus-ha/role.state 2>/dev/null || true)"',
            'APPLY_RUNTIME="${RPDB_HEADEND_APPLY_RUNTIME:-auto}"',
            'if [ "${APPLY_RUNTIME}" != "true" ] && [ "${HA_ROLE}" = "standby" ]; then',
            '  echo "head-end is standby; staged config remains at ${SWANCTL_CONF}"',
            '  exit 0',
            'fi',
            'if [ "${APPLY_RUNTIME}" != "true" ] && command -v systemctl >/dev/null 2>&1 && ! systemctl is-active --quiet strongswan && [ "${HA_ROLE}" != "active" ]; then',
            '  echo "strongswan is not active; staged config remains at ${SWANCTL_CONF}"',
            '  exit 0',
            'fi',
            'bash "${CUSTOMER_ROOT}/public-identity/apply-public-identity.sh"',
            'bash "${CUSTOMER_ROOT}/transport/apply-transport.sh"',
            'bash "${CUSTOMER_ROOT}/routing/apply-routes.sh"',
            'bash "${CUSTOMER_ROOT}/outside-nat/apply-outside-nat.sh"',
            'bash "${CUSTOMER_ROOT}/post-ipsec-nat/apply-post-ipsec-nat.sh"',
            'if command -v swanctl >/dev/null 2>&1 && systemctl is-active --quiet strongswan; then',
            '  RESET_IPSEC="${RPDB_HEADEND_RESET_IPSEC_ON_APPLY:-true}"',
            '  if [ "${RESET_IPSEC}" != "false" ]; then',
            '    echo "resetting same-customer strongSwan SAs before apply: ${CUST}"',
            '    swanctl --terminate --child "${CUST}-child" --force --timeout 10 2>/dev/null || true',
            '    swanctl --terminate --ike "${CUST}" --force --timeout 10 2>/dev/null || true',
            "  fi",
            '  swanctl --load-all',
            '  if ! bash "${CUSTOMER_ROOT}/ipsec/initiate-tunnel.sh"; then',
            '    echo "head-end initiate did not complete; customer config remains loaded for traffic-triggered or later manual initiation" >&2',
            "  fi",
            'elif command -v swanctl >/dev/null 2>&1; then',
            '  echo "strongswan is not active; staged config remains at ${SWANCTL_CONF}"',
            'else',
            '  echo "swanctl not found; staged config remains at ${SWANCTL_CONF}"',
            'fi',
        ]
    )


def _render_master_remove_script(layout: dict[str, Path], customer_name: str) -> str:
    customer_root = f"/{HEADEND_STATE_ROOT.as_posix()}/{customer_name}"
    swanctl_conf = f"/{SWANCTL_CONF_ROOT.as_posix()}/{customer_name}.conf"
    return _render_shell_script(
        [
            'ROOT="${RPDB_HEADEND_ROOT:-/}"',
            'ROOT="${ROOT%/}"',
            f'CUSTOMER_ROOT="${{ROOT}}{customer_root}"',
            f'SWANCTL_CONF="${{ROOT}}{swanctl_conf}"',
            'rm -f "${SWANCTL_CONF}"',
            'bash "${CUSTOMER_ROOT}/routing/remove-routes.sh"',
            'bash "${CUSTOMER_ROOT}/post-ipsec-nat/remove-post-ipsec-nat.sh"',
            'bash "${CUSTOMER_ROOT}/outside-nat/remove-outside-nat.sh"',
            'bash "${CUSTOMER_ROOT}/transport/remove-transport.sh"',
            'bash "${CUSTOMER_ROOT}/public-identity/remove-public-identity.sh"',
            'if command -v swanctl >/dev/null 2>&1 && systemctl is-active --quiet strongswan; then',
            '  swanctl --load-all',
            'elif command -v swanctl >/dev/null 2>&1; then',
            '  echo "strongswan is not active; removed staged config ${SWANCTL_CONF}"',
            'else',
            '  echo "swanctl not found; removed staged config ${SWANCTL_CONF}"',
            'fi',
        ]
    )


def install_headend_bundle(bundle_dir: Path, headend_root: Path) -> dict[str, Any]:
    validation = validate_headend_bundle(bundle_dir)
    if not validation["valid"]:
        raise ValueError("headend bundle is not installable: " + "; ".join(validation["errors"]))

    bundle = load_headend_bundle(bundle_dir)
    layout = build_install_layout(headend_root, bundle.customer_name)
    customer_root = layout["customer_root"]
    customer_root.mkdir(parents=True, exist_ok=True)

    if layout["artifacts_root"].exists():
        shutil.rmtree(layout["artifacts_root"])
    layout["artifacts_root"].mkdir(parents=True, exist_ok=True)

    for path in bundle.headend_dir.rglob("*"):
        if path.is_dir():
            continue
        relative_name = path.relative_to(bundle.headend_dir)
        destination = layout["artifacts_root"] / relative_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)

    _write_text(layout["swanctl_conf"], bundle.text_payloads["ipsec/swanctl-connection.conf"])
    _write_json(layout["ipsec_initiation_intent"], bundle.json_payloads["ipsec/initiation-intent.json"])
    _write_text(layout["ipsec_initiate_script"], bundle.text_payloads["ipsec/initiate-tunnel.sh"])
    _write_json(layout["transport_intent"], bundle.json_payloads["transport/transport-intent.json"])
    _write_text(layout["transport_apply_script"], bundle.text_payloads["transport/apply-transport.sh"])
    _write_text(layout["transport_remove_script"], bundle.text_payloads["transport/remove-transport.sh"])
    _write_json(layout["public_identity_intent"], bundle.json_payloads["public-identity/public-identity-intent.json"])
    _write_text(layout["public_identity_apply_script"], bundle.text_payloads["public-identity/apply-public-identity.sh"])
    _write_text(layout["public_identity_remove_script"], bundle.text_payloads["public-identity/remove-public-identity.sh"])
    _write_text(layout["route_commands"], bundle.text_payloads["routing/ip-route.commands.txt"])
    _write_text(layout["nft_apply"], bundle.text_payloads["post-ipsec-nat/nftables.apply.nft"])
    _write_text(layout["nft_remove"], bundle.text_payloads["post-ipsec-nat/nftables.remove.nft"])
    _write_json(layout["nft_state"], bundle.json_payloads["post-ipsec-nat/nftables-state.json"])
    _write_json(layout["activation_manifest"], bundle.json_payloads["post-ipsec-nat/activation-manifest.json"])
    _write_text(layout["outside_nft_apply"], bundle.text_payloads["outside-nat/nftables.apply.nft"])
    _write_text(layout["outside_nft_remove"], bundle.text_payloads["outside-nat/nftables.remove.nft"])
    _write_json(layout["outside_nft_state"], bundle.json_payloads["outside-nat/nftables-state.json"])
    _write_json(layout["outside_activation_manifest"], bundle.json_payloads["outside-nat/activation-manifest.json"])

    route_remove_lines = _derive_route_remove_lines(bundle.text_payloads["routing/ip-route.commands.txt"])
    nat_enabled = bool(bundle.json_payloads["post-ipsec-nat/post-ipsec-nat-intent.json"].get("enabled"))
    outside_nat_enabled = bool(bundle.json_payloads["outside-nat/outside-nat-intent.json"].get("enabled"))

    route_apply_script = _render_shell_script(_executable_lines(bundle.text_payloads["routing/ip-route.commands.txt"]) or ["true"])
    route_remove_script = _render_shell_script(route_remove_lines or ["true"])
    nat_apply_script = _render_nft_apply_script(nat_enabled)
    nat_remove_script = _render_nft_remove_script(nat_enabled)
    outside_nat_apply_script = _render_nft_apply_script(outside_nat_enabled)
    outside_nat_remove_script = _render_nft_remove_script(outside_nat_enabled)

    _write_text(layout["route_apply_script"], route_apply_script)
    _write_text(layout["route_remove_script"], route_remove_script)
    _write_text(layout["nat_apply_script"], nat_apply_script)
    _write_text(layout["nat_remove_script"], nat_remove_script)
    _write_text(layout["outside_nat_apply_script"], outside_nat_apply_script)
    _write_text(layout["outside_nat_remove_script"], outside_nat_remove_script)
    _write_text(layout["master_apply_script"], _render_master_apply_script(layout, bundle.customer_name))
    _write_text(layout["master_remove_script"], _render_master_remove_script(layout, bundle.customer_name))

    for key in (
        "route_apply_script",
        "route_remove_script",
        "transport_apply_script",
        "transport_remove_script",
        "public_identity_apply_script",
        "public_identity_remove_script",
        "nat_apply_script",
        "nat_remove_script",
        "outside_nat_apply_script",
        "outside_nat_remove_script",
        "ipsec_initiate_script",
        "master_apply_script",
        "master_remove_script",
    ):
        _make_executable(layout[key])

    state = {
        "schema_version": 1,
        "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "customer_name": bundle.customer_name,
        "bundle_dir": str(bundle.bundle_dir),
        "swanctl_conf": str(layout["swanctl_conf"]),
        "artifacts_root": str(layout["artifacts_root"]),
        "route_command_count": len(_executable_lines(bundle.text_payloads["routing/ip-route.commands.txt"])),
        "transport": bundle.json_payloads["transport/transport-intent.json"],
        "public_identity": bundle.json_payloads["public-identity/public-identity-intent.json"],
        "post_ipsec_nat_command_count": int(
            bundle.json_payloads["post-ipsec-nat/activation-manifest.json"].get("apply_command_count") or 0
        ),
        "outside_nat_command_count": int(
            bundle.json_payloads["outside-nat/activation-manifest.json"].get("apply_command_count") or 0
        ),
        "ipsec_initiation": bundle.json_payloads["ipsec/initiation-intent.json"],
        "paths": {name: str(path) for name, path in layout.items()},
    }
    _write_json(layout["state_json"], state)

    return {
        "customer_name": bundle.customer_name,
        "headend_root": str(layout["headend_root"]),
        "installed": True,
        "state_json": str(layout["state_json"]),
        "swanctl_conf": str(layout["swanctl_conf"]),
        "ipsec_initiate_script": str(layout["ipsec_initiate_script"]),
        "transport_apply_script": str(layout["transport_apply_script"]),
        "transport_remove_script": str(layout["transport_remove_script"]),
        "public_identity_apply_script": str(layout["public_identity_apply_script"]),
        "public_identity_remove_script": str(layout["public_identity_remove_script"]),
        "route_apply_script": str(layout["route_apply_script"]),
        "route_remove_script": str(layout["route_remove_script"]),
        "post_ipsec_nat_apply_script": str(layout["nat_apply_script"]),
        "post_ipsec_nat_remove_script": str(layout["nat_remove_script"]),
        "outside_nat_apply_script": str(layout["outside_nat_apply_script"]),
        "outside_nat_remove_script": str(layout["outside_nat_remove_script"]),
        "master_apply_script": str(layout["master_apply_script"]),
        "master_remove_script": str(layout["master_remove_script"]),
    }


def validate_installed_headend(bundle_dir: Path, headend_root: Path) -> dict[str, Any]:
    report = validate_headend_bundle(bundle_dir)
    if not report["valid"]:
        return report

    bundle = load_headend_bundle(bundle_dir)
    layout = build_install_layout(headend_root, bundle.customer_name)

    for key in (
        "swanctl_conf",
        "ipsec_initiation_intent",
        "ipsec_initiate_script",
        "transport_intent",
        "transport_apply_script",
        "transport_remove_script",
        "public_identity_intent",
        "public_identity_apply_script",
        "public_identity_remove_script",
        "route_commands",
        "nft_apply",
        "nft_remove",
        "nft_state",
        "activation_manifest",
        "outside_nft_apply",
        "outside_nft_remove",
        "outside_nft_state",
        "outside_activation_manifest",
        "route_apply_script",
        "route_remove_script",
        "nat_apply_script",
        "nat_remove_script",
        "outside_nat_apply_script",
        "outside_nat_remove_script",
        "master_apply_script",
        "master_remove_script",
        "state_json",
    ):
        if not layout[key].exists():
            report["errors"].append(f"installed path missing: {layout[key]}")

    if layout["swanctl_conf"].exists():
        installed_text = layout["swanctl_conf"].read_text(encoding="utf-8")
        if installed_text != bundle.text_payloads["ipsec/swanctl-connection.conf"]:
            report["errors"].append(f"installed swanctl conf does not match bundle: {layout['swanctl_conf']}")

    if layout["route_commands"].exists():
        installed_route_text = layout["route_commands"].read_text(encoding="utf-8")
        if installed_route_text != bundle.text_payloads["routing/ip-route.commands.txt"]:
            report["errors"].append(f"installed route commands do not match bundle: {layout['route_commands']}")

    if layout["ipsec_initiate_script"].exists():
        installed_initiate_script = layout["ipsec_initiate_script"].read_text(encoding="utf-8")
        if installed_initiate_script != bundle.text_payloads["ipsec/initiate-tunnel.sh"]:
            report["errors"].append(
                f"installed IPsec initiate script does not match bundle: {layout['ipsec_initiate_script']}"
            )

    if layout["ipsec_initiation_intent"].exists():
        installed_initiation_intent = _load_json(layout["ipsec_initiation_intent"])
        if installed_initiation_intent != bundle.json_payloads["ipsec/initiation-intent.json"]:
            report["errors"].append(
                f"installed IPsec initiation intent does not match bundle: {layout['ipsec_initiation_intent']}"
            )

    if layout["transport_intent"].exists():
        installed_transport_intent = _load_json(layout["transport_intent"])
        if installed_transport_intent != bundle.json_payloads["transport/transport-intent.json"]:
            report["errors"].append(
                f"installed transport intent does not match bundle: {layout['transport_intent']}"
            )

    if layout["transport_apply_script"].exists():
        installed_transport_apply = layout["transport_apply_script"].read_text(encoding="utf-8")
        if installed_transport_apply != bundle.text_payloads["transport/apply-transport.sh"]:
            report["errors"].append(
                f"installed transport apply script does not match bundle: {layout['transport_apply_script']}"
            )

    if layout["transport_remove_script"].exists():
        installed_transport_remove = layout["transport_remove_script"].read_text(encoding="utf-8")
        if installed_transport_remove != bundle.text_payloads["transport/remove-transport.sh"]:
            report["errors"].append(
                f"installed transport remove script does not match bundle: {layout['transport_remove_script']}"
            )

    if layout["public_identity_intent"].exists():
        installed_public_identity_intent = _load_json(layout["public_identity_intent"])
        if installed_public_identity_intent != bundle.json_payloads["public-identity/public-identity-intent.json"]:
            report["errors"].append(
                f"installed public identity intent does not match bundle: {layout['public_identity_intent']}"
            )

    if layout["public_identity_apply_script"].exists():
        installed_public_identity_apply = layout["public_identity_apply_script"].read_text(encoding="utf-8")
        if installed_public_identity_apply != bundle.text_payloads["public-identity/apply-public-identity.sh"]:
            report["errors"].append(
                f"installed public identity apply script does not match bundle: {layout['public_identity_apply_script']}"
            )

    if layout["public_identity_remove_script"].exists():
        installed_public_identity_remove = layout["public_identity_remove_script"].read_text(encoding="utf-8")
        if installed_public_identity_remove != bundle.text_payloads["public-identity/remove-public-identity.sh"]:
            report["errors"].append(
                f"installed public identity remove script does not match bundle: {layout['public_identity_remove_script']}"
            )

    if layout["nft_apply"].exists():
        installed_nft_apply = layout["nft_apply"].read_text(encoding="utf-8")
        if installed_nft_apply != bundle.text_payloads["post-ipsec-nat/nftables.apply.nft"]:
            report["errors"].append(f"installed nftables apply file does not match bundle: {layout['nft_apply']}")

    if layout["nft_remove"].exists():
        installed_nft_remove = layout["nft_remove"].read_text(encoding="utf-8")
        if installed_nft_remove != bundle.text_payloads["post-ipsec-nat/nftables.remove.nft"]:
            report["errors"].append(f"installed nftables remove file does not match bundle: {layout['nft_remove']}")

    if layout["outside_nft_apply"].exists():
        installed_outside_nft_apply = layout["outside_nft_apply"].read_text(encoding="utf-8")
        if installed_outside_nft_apply != bundle.text_payloads["outside-nat/nftables.apply.nft"]:
            report["errors"].append(
                f"installed outside NAT nftables apply file does not match bundle: {layout['outside_nft_apply']}"
            )

    if layout["outside_nft_remove"].exists():
        installed_outside_nft_remove = layout["outside_nft_remove"].read_text(encoding="utf-8")
        if installed_outside_nft_remove != bundle.text_payloads["outside-nat/nftables.remove.nft"]:
            report["errors"].append(
                f"installed outside NAT nftables remove file does not match bundle: {layout['outside_nft_remove']}"
            )

    if layout["state_json"].exists():
        state = _load_json(layout["state_json"])
        report["details"]["install_state"] = state
        if state.get("customer_name") != bundle.customer_name:
            report["errors"].append(f"install-state customer mismatch in {layout['state_json']}")

    report["details"]["installed_root"] = str(layout["customer_root"])
    report["details"]["installed_swanctl_conf"] = str(layout["swanctl_conf"])
    report["valid"] = not report["errors"]
    return report


def remove_installed_headend(customer_name: str, headend_root: Path) -> dict[str, Any]:
    layout = build_install_layout(headend_root, customer_name)
    removed_paths: list[str] = []

    if layout["swanctl_conf"].exists():
        layout["swanctl_conf"].unlink()
        removed_paths.append(str(layout["swanctl_conf"]))

    if layout["customer_root"].exists():
        shutil.rmtree(layout["customer_root"])
        removed_paths.append(str(layout["customer_root"]))

    return {
        "customer_name": customer_name,
        "headend_root": str(layout["headend_root"]),
        "removed": True,
        "removed_paths": removed_paths,
        "remaining_customer_root": layout["customer_root"].exists(),
        "remaining_swanctl_conf": layout["swanctl_conf"].exists(),
    }
