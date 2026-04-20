"""Shared helpers for customer-scoped muxer staging and validation."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PLACEHOLDER_RE = re.compile(r"\$\{[^}]+\}")
MUXER_REQUIRED_FILES = (
    "customer/customer-summary.json",
    "firewall/firewall-intent.json",
    "firewall/nftables.apply.nft",
    "firewall/nftables.remove.nft",
    "firewall/nftables-state.json",
    "firewall/activation-manifest.json",
    "routing/ip-rule.command.txt",
    "routing/ip-route-default.command.txt",
    "routing/rpdb-routing.json",
    "tunnel/ip-link.command.txt",
    "tunnel/tunnel-intent.json",
)

MUXER_STATE_ROOT = Path("var") / "lib" / "rpdb-muxer" / "customers"
MUXER_MODULE_ROOT = Path("etc") / "muxer" / "customer-modules"


@dataclass(frozen=True)
class MuxerBundle:
    bundle_dir: Path
    customer_name: str
    customer_module: dict[str, Any]
    muxer_dir: Path
    source_files: dict[str, Path]
    text_payloads: dict[str, str]
    json_payloads: dict[str, dict[str, Any]]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if payload.endswith("\n") else payload + "\n", encoding="utf-8", newline="\n")


def _make_executable(path: Path) -> None:
    try:
        path.chmod(path.stat().st_mode | 0o111)
    except OSError:
        pass


def load_muxer_bundle(bundle_dir: Path) -> MuxerBundle:
    resolved_bundle = bundle_dir.resolve()
    customer_module_path = resolved_bundle / "customer" / "customer-module.json"
    if not customer_module_path.exists():
        raise ValueError(f"bundle missing customer/customer-module.json: {customer_module_path}")

    customer_module = _load_json(customer_module_path)
    customer = customer_module.get("customer") or {}
    customer_name = str(customer.get("name") or "").strip()
    if not customer_name:
        raise ValueError(f"bundle customer-module.json missing customer.name: {customer_module_path}")

    muxer_dir = resolved_bundle / "muxer"
    if not muxer_dir.is_dir():
        raise ValueError(f"bundle missing muxer directory: {muxer_dir}")

    source_files: dict[str, Path] = {}
    text_payloads: dict[str, str] = {}
    json_payloads: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for relative_name in MUXER_REQUIRED_FILES:
        source_path = muxer_dir / relative_name
        if not source_path.exists():
            missing.append(relative_name)
            continue
        source_files[relative_name] = source_path
        if source_path.suffix == ".json":
            json_payloads[relative_name] = _load_json(source_path)
        else:
            text_payloads[relative_name] = source_path.read_text(encoding="utf-8")

    if missing:
        raise ValueError("bundle missing required muxer files: " + ", ".join(missing))

    return MuxerBundle(
        bundle_dir=resolved_bundle,
        customer_name=customer_name,
        customer_module=customer_module,
        muxer_dir=muxer_dir,
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


def validate_muxer_bundle(bundle_dir: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "bundle_dir": str(bundle_dir.resolve()),
        "customer_name": None,
        "errors": [],
        "warnings": [],
        "details": {},
        "valid": False,
    }

    try:
        bundle = load_muxer_bundle(bundle_dir)
    except Exception as exc:
        report["errors"].append(str(exc))
        return report

    report["customer_name"] = bundle.customer_name

    for relative_name, payload in bundle.text_payloads.items():
        unresolved = _find_placeholders(payload)
        if unresolved:
            report["errors"].append(
                f"muxer file has unresolved placeholders: {relative_name} -> {', '.join(unresolved)}"
            )

    for relative_name, payload in bundle.json_payloads.items():
        unresolved = _find_json_placeholders(payload)
        if unresolved:
            report["errors"].append(
                f"muxer JSON file has unresolved placeholders: {relative_name} -> {', '.join(unresolved)}"
            )

    customer_summary = bundle.json_payloads["customer/customer-summary.json"]
    summary_customer_name = str(customer_summary.get("customer_name") or "").strip()
    if not summary_customer_name:
        summary_customer_name = str((customer_summary.get("customer") or {}).get("name") or "").strip()
    if summary_customer_name != bundle.customer_name:
        report["errors"].append("muxer customer-summary.json does not match customer-module.json name")

    rule_lines = _executable_lines(bundle.text_payloads["routing/ip-rule.command.txt"])
    route_lines = _executable_lines(bundle.text_payloads["routing/ip-route-default.command.txt"])
    tunnel_lines = _executable_lines(bundle.text_payloads["tunnel/ip-link.command.txt"])
    firewall_apply_text = bundle.text_payloads["firewall/nftables.apply.nft"]
    firewall_remove_text = bundle.text_payloads["firewall/nftables.remove.nft"]
    firewall_manifest = bundle.json_payloads["firewall/activation-manifest.json"]
    firewall_state = bundle.json_payloads["firewall/nftables-state.json"]
    report["details"]["rule_command_count"] = len(rule_lines)
    report["details"]["route_command_count"] = len(route_lines)
    report["details"]["tunnel_command_count"] = len(tunnel_lines)
    report["details"]["firewall_activation_backend"] = firewall_manifest.get("backend")
    report["details"]["firewall_command_count"] = int(firewall_manifest.get("apply_command_count") or 0)
    report["details"]["firewall_rollback_command_count"] = int(firewall_manifest.get("rollback_command_count") or 0)
    report["details"]["firewall_rule_count"] = int(firewall_manifest.get("rule_count") or 0)
    report["details"]["transport_interface"] = (
        bundle.customer_module.get("transport") or {}
    ).get("interface")
    report["details"]["fwmark"] = (bundle.customer_module.get("transport") or {}).get("mark")
    nft_payload = "\n".join([firewall_apply_text, firewall_remove_text, json.dumps(firewall_manifest), json.dumps(firewall_state)])
    if "iptables" in nft_payload:
        report["errors"].append("muxer firewall nftables artifacts must not contain iptables commands")
    if firewall_manifest.get("backend") != "nftables" or firewall_state.get("backend") != "nftables":
        report["errors"].append("muxer firewall activation backend must be nftables")

    if not rule_lines:
        report["warnings"].append("routing/ip-rule.command.txt contains no executable commands")
    if not route_lines:
        report["warnings"].append("routing/ip-route-default.command.txt contains no executable commands")
    for line in route_lines:
        if line.startswith("ip route replace table ") and " default via " in line and "onlink" not in line.split():
            report["errors"].append("muxer backend default routes must include onlink for cross-subnet head-end gateways")
    if not tunnel_lines:
        report["warnings"].append("tunnel/ip-link.command.txt contains no executable commands")
    if "table ip " not in firewall_apply_text:
        report["warnings"].append("firewall/nftables.apply.nft contains no nftables table")

    report["valid"] = not report["errors"]
    return report


def build_install_layout(muxer_root: Path, customer_name: str) -> dict[str, Path]:
    resolved_root = muxer_root.resolve()
    customer_root = resolved_root / MUXER_STATE_ROOT / customer_name
    module_root = resolved_root / MUXER_MODULE_ROOT / customer_name
    return {
        "muxer_root": resolved_root,
        "customer_root": customer_root,
        "artifacts_root": customer_root / "artifacts",
        "module_root": module_root,
        "customer_module": module_root / "customer-module.json",
        "customer_summary": customer_root / "customer" / "customer-summary.json",
        "firewall_intent": customer_root / "firewall" / "firewall-intent.json",
        "firewall_apply_nft": customer_root / "firewall" / "nftables.apply.nft",
        "firewall_remove_nft": customer_root / "firewall" / "nftables.remove.nft",
        "firewall_state": customer_root / "firewall" / "nftables-state.json",
        "firewall_activation_manifest": customer_root / "firewall" / "activation-manifest.json",
        "rule_commands": customer_root / "routing" / "ip-rule.command.txt",
        "route_commands": customer_root / "routing" / "ip-route-default.command.txt",
        "routing_intent": customer_root / "routing" / "rpdb-routing.json",
        "tunnel_intent": customer_root / "tunnel" / "tunnel-intent.json",
        "tunnel_commands": customer_root / "tunnel" / "ip-link.command.txt",
        "firewall_apply_script": customer_root / "firewall" / "apply-firewall.sh",
        "firewall_remove_script": customer_root / "firewall" / "remove-firewall.sh",
        "routing_apply_script": customer_root / "routing" / "apply-routing.sh",
        "routing_remove_script": customer_root / "routing" / "remove-routing.sh",
        "tunnel_apply_script": customer_root / "tunnel" / "apply-tunnel.sh",
        "tunnel_remove_script": customer_root / "tunnel" / "remove-tunnel.sh",
        "master_apply_script": customer_root / "apply-muxer-customer.sh",
        "master_remove_script": customer_root / "remove-muxer-customer.sh",
        "state_json": customer_root / "install-state.json",
    }


def _derive_routing_remove_lines(rule_text: str, route_text: str) -> list[str]:
    removals: list[str] = []
    for line in _executable_lines(rule_text):
        if line.startswith("ip rule add "):
            removals.append("ip rule del " + line.removeprefix("ip rule add ") + " || true")
        else:
            removals.append(f"# manual rule cleanup required: {line}")
    for line in _executable_lines(route_text):
        if line.startswith("ip route replace "):
            removals.append("ip route del " + line.removeprefix("ip route replace ") + " || true")
        elif line.startswith("ip route add "):
            removals.append("ip route del " + line.removeprefix("ip route add ") + " || true")
        else:
            removals.append(f"# manual route cleanup required: {line}")
    return removals


def _derive_routing_apply_lines(rule_text: str, route_text: str) -> list[str]:
    apply_lines: list[str] = []
    for line in _executable_lines(rule_text):
        if line.startswith("ip rule add "):
            rule_spec = line.removeprefix("ip rule add ")
            apply_lines.append("ip rule del " + rule_spec + " 2>/dev/null || true")
            apply_lines.append(line)
        else:
            apply_lines.append(line)
    apply_lines.extend(_executable_lines(route_text))
    return apply_lines


def _derive_tunnel_remove_lines(bundle: MuxerBundle) -> list[str]:
    intent = bundle.json_payloads["tunnel/tunnel-intent.json"]
    interface = str(intent.get("interface") or "").strip()
    if interface:
        return [f"ip link del {interface} || true"]
    return ["true"]


def _derive_tunnel_apply_lines(bundle: MuxerBundle) -> list[str]:
    intent = bundle.json_payloads["tunnel/tunnel-intent.json"]
    interface = str(intent.get("interface") or "").strip()
    apply_lines: list[str] = []
    for line in _executable_lines(bundle.text_payloads["tunnel/ip-link.command.txt"]):
        if interface and line.startswith(f"ip link add {interface} "):
            apply_lines.append(
                f"if ip link show {interface} >/dev/null 2>&1; then ip link del {interface}; fi"
            )
        apply_lines.append(line)
    return apply_lines


def _render_shell_script(lines: list[str]) -> str:
    return "\n".join(["#!/usr/bin/env bash", "set -eu", *lines]) + "\n"


def _render_nft_apply_script() -> str:
    return _render_shell_script(
        [
            'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
            'NFT_APPLY="${SCRIPT_DIR}/nftables.apply.nft"',
            'nft -c -f "${NFT_APPLY}"',
            'nft -f "${NFT_APPLY}"',
        ]
    )


def _render_nft_remove_script() -> str:
    return _render_shell_script(
        [
            'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
            'NFT_REMOVE="${SCRIPT_DIR}/nftables.remove.nft"',
            'nft -f "${NFT_REMOVE}" || true',
        ]
    )


def _render_master_apply_script(customer_name: str) -> str:
    customer_root = f"/{MUXER_STATE_ROOT.as_posix()}/{customer_name}"
    module_json = f"/{MUXER_MODULE_ROOT.as_posix()}/{customer_name}/customer-module.json"
    return _render_shell_script(
        [
            'ROOT="${RPDB_MUXER_ROOT:-/}"',
            'ROOT="${ROOT%/}"',
            f'CUSTOMER_ROOT="${{ROOT}}{customer_root}"',
            f'MODULE_JSON="${{ROOT}}{module_json}"',
            'test -f "${MODULE_JSON}"',
            'bash "${CUSTOMER_ROOT}/tunnel/apply-tunnel.sh"',
            'bash "${CUSTOMER_ROOT}/routing/apply-routing.sh"',
            'bash "${CUSTOMER_ROOT}/firewall/apply-firewall.sh"',
        ]
    )


def _render_master_remove_script(customer_name: str) -> str:
    customer_root = f"/{MUXER_STATE_ROOT.as_posix()}/{customer_name}"
    module_json = f"/{MUXER_MODULE_ROOT.as_posix()}/{customer_name}/customer-module.json"
    return _render_shell_script(
        [
            'ROOT="${RPDB_MUXER_ROOT:-/}"',
            'ROOT="${ROOT%/}"',
            f'CUSTOMER_ROOT="${{ROOT}}{customer_root}"',
            f'MODULE_JSON="${{ROOT}}{module_json}"',
            'bash "${CUSTOMER_ROOT}/firewall/remove-firewall.sh"',
            'bash "${CUSTOMER_ROOT}/routing/remove-routing.sh"',
            'bash "${CUSTOMER_ROOT}/tunnel/remove-tunnel.sh"',
            'rm -f "${MODULE_JSON}"',
        ]
    )


def install_muxer_bundle(bundle_dir: Path, muxer_root: Path) -> dict[str, Any]:
    validation = validate_muxer_bundle(bundle_dir)
    if not validation["valid"]:
        raise ValueError("muxer bundle is not installable: " + "; ".join(validation["errors"]))

    bundle = load_muxer_bundle(bundle_dir)
    layout = build_install_layout(muxer_root, bundle.customer_name)
    layout["customer_root"].mkdir(parents=True, exist_ok=True)
    layout["module_root"].mkdir(parents=True, exist_ok=True)

    if layout["artifacts_root"].exists():
        shutil.rmtree(layout["artifacts_root"])
    layout["artifacts_root"].mkdir(parents=True, exist_ok=True)

    for path in bundle.muxer_dir.rglob("*"):
        if path.is_dir():
            continue
        relative_name = path.relative_to(bundle.muxer_dir)
        destination = layout["artifacts_root"] / relative_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)

    _write_json(layout["customer_module"], bundle.customer_module)
    _write_json(layout["customer_summary"], bundle.json_payloads["customer/customer-summary.json"])
    _write_json(layout["firewall_intent"], bundle.json_payloads["firewall/firewall-intent.json"])
    _write_text(layout["firewall_apply_nft"], bundle.text_payloads["firewall/nftables.apply.nft"])
    _write_text(layout["firewall_remove_nft"], bundle.text_payloads["firewall/nftables.remove.nft"])
    _write_json(layout["firewall_state"], bundle.json_payloads["firewall/nftables-state.json"])
    _write_json(layout["firewall_activation_manifest"], bundle.json_payloads["firewall/activation-manifest.json"])
    _write_text(layout["rule_commands"], bundle.text_payloads["routing/ip-rule.command.txt"])
    _write_text(layout["route_commands"], bundle.text_payloads["routing/ip-route-default.command.txt"])
    _write_json(layout["routing_intent"], bundle.json_payloads["routing/rpdb-routing.json"])
    _write_json(layout["tunnel_intent"], bundle.json_payloads["tunnel/tunnel-intent.json"])
    _write_text(layout["tunnel_commands"], bundle.text_payloads["tunnel/ip-link.command.txt"])

    _write_text(
        layout["firewall_apply_script"],
        _render_nft_apply_script(),
    )
    _write_text(
        layout["firewall_remove_script"],
        _render_nft_remove_script(),
    )
    _write_text(
        layout["routing_apply_script"],
        _render_shell_script(
            _derive_routing_apply_lines(
                bundle.text_payloads["routing/ip-rule.command.txt"],
                bundle.text_payloads["routing/ip-route-default.command.txt"],
            )
            or ["true"]
        ),
    )
    _write_text(
        layout["routing_remove_script"],
        _render_shell_script(
            _derive_routing_remove_lines(
                bundle.text_payloads["routing/ip-rule.command.txt"],
                bundle.text_payloads["routing/ip-route-default.command.txt"],
            )
            or ["true"]
        ),
    )
    _write_text(
        layout["tunnel_apply_script"],
        _render_shell_script(_derive_tunnel_apply_lines(bundle) or ["true"]),
    )
    _write_text(
        layout["tunnel_remove_script"],
        _render_shell_script(_derive_tunnel_remove_lines(bundle)),
    )
    _write_text(layout["master_apply_script"], _render_master_apply_script(bundle.customer_name))
    _write_text(layout["master_remove_script"], _render_master_remove_script(bundle.customer_name))

    for key in (
        "firewall_apply_script",
        "firewall_remove_script",
        "routing_apply_script",
        "routing_remove_script",
        "tunnel_apply_script",
        "tunnel_remove_script",
        "master_apply_script",
        "master_remove_script",
    ):
        _make_executable(layout[key])

    state = {
        "schema_version": 1,
        "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "customer_name": bundle.customer_name,
        "bundle_dir": str(bundle.bundle_dir),
        "module_root": str(layout["module_root"]),
        "customer_module": str(layout["customer_module"]),
        "artifacts_root": str(layout["artifacts_root"]),
        "paths": {name: str(path) for name, path in layout.items()},
    }
    _write_json(layout["state_json"], state)

    return {
        "customer_name": bundle.customer_name,
        "muxer_root": str(layout["muxer_root"]),
        "installed": True,
        "state_json": str(layout["state_json"]),
        "customer_module": str(layout["customer_module"]),
        "master_apply_script": str(layout["master_apply_script"]),
        "master_remove_script": str(layout["master_remove_script"]),
    }


def validate_installed_muxer(bundle_dir: Path, muxer_root: Path) -> dict[str, Any]:
    report = validate_muxer_bundle(bundle_dir)
    if not report["valid"]:
        return report

    bundle = load_muxer_bundle(bundle_dir)
    layout = build_install_layout(muxer_root, bundle.customer_name)
    for key in (
        "customer_module",
        "customer_summary",
        "firewall_intent",
        "firewall_apply_nft",
        "firewall_remove_nft",
        "firewall_state",
        "firewall_activation_manifest",
        "rule_commands",
        "route_commands",
        "routing_intent",
        "tunnel_intent",
        "tunnel_commands",
        "firewall_apply_script",
        "firewall_remove_script",
        "routing_apply_script",
        "routing_remove_script",
        "tunnel_apply_script",
        "tunnel_remove_script",
        "master_apply_script",
        "master_remove_script",
        "state_json",
    ):
        if not layout[key].exists():
            report["errors"].append(f"installed path missing: {layout[key]}")

    if layout["customer_module"].exists():
        installed_module = _load_json(layout["customer_module"])
        if installed_module != bundle.customer_module:
            report["errors"].append(f"installed customer-module does not match bundle: {layout['customer_module']}")

    json_checks = {
        "customer_summary": "customer/customer-summary.json",
        "firewall_intent": "firewall/firewall-intent.json",
        "routing_intent": "routing/rpdb-routing.json",
        "tunnel_intent": "tunnel/tunnel-intent.json",
    }
    for layout_key, relative_name in json_checks.items():
        if layout[layout_key].exists():
            installed_json = _load_json(layout[layout_key])
            if installed_json != bundle.json_payloads[relative_name]:
                report["errors"].append(f"installed JSON does not match bundle: {layout[layout_key]}")

    text_checks = {
        "firewall_apply_nft": "firewall/nftables.apply.nft",
        "firewall_remove_nft": "firewall/nftables.remove.nft",
        "rule_commands": "routing/ip-rule.command.txt",
        "route_commands": "routing/ip-route-default.command.txt",
        "tunnel_commands": "tunnel/ip-link.command.txt",
    }
    for layout_key, relative_name in text_checks.items():
        if layout[layout_key].exists():
            installed_text = layout[layout_key].read_text(encoding="utf-8")
            if installed_text != bundle.text_payloads[relative_name]:
                report["errors"].append(f"installed text does not match bundle: {layout[layout_key]}")

    if layout["state_json"].exists():
        state = _load_json(layout["state_json"])
        report["details"]["install_state"] = state
        if state.get("customer_name") != bundle.customer_name:
            report["errors"].append(f"install-state customer mismatch in {layout['state_json']}")

    report["details"]["installed_root"] = str(layout["customer_root"])
    report["details"]["installed_customer_module"] = str(layout["customer_module"])
    report["valid"] = not report["errors"]
    return report


def remove_installed_muxer(customer_name: str, muxer_root: Path) -> dict[str, Any]:
    layout = build_install_layout(muxer_root, customer_name)
    removed_paths: list[str] = []

    if layout["module_root"].exists():
        shutil.rmtree(layout["module_root"])
        removed_paths.append(str(layout["module_root"]))

    if layout["customer_root"].exists():
        shutil.rmtree(layout["customer_root"])
        removed_paths.append(str(layout["customer_root"]))

    return {
        "customer_name": customer_name,
        "muxer_root": str(layout["muxer_root"]),
        "removed": True,
        "removed_paths": removed_paths,
        "remaining_customer_root": layout["customer_root"].exists(),
        "remaining_module_root": layout["module_root"].exists(),
    }
