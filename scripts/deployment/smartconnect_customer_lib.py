"""Shared helpers for customer-scoped SmartConnect staging and validation."""

from __future__ import annotations

import ipaddress
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PLACEHOLDER_RE = re.compile(r"\$\{[^}]+\}")
SMARTCONNECT_REQUIRED_FILES = (
    "routing/route-intent.json",
    "routing/ip-route.commands.txt",
)

SMARTCONNECT_STATE_ROOT = Path("var") / "lib" / "rpdb-smartconnect" / "customers"


@dataclass(frozen=True)
class SmartconnectBundle:
    bundle_dir: Path
    customer_name: str
    customer_module: dict[str, Any]
    smartconnect_dir: Path
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


def _expected_route_cidrs(customer_module: dict[str, Any]) -> list[str]:
    selectors = customer_module.get("selectors") or {}
    post_ipsec_nat = customer_module.get("post_ipsec_nat") or {}
    if bool(post_ipsec_nat.get("enabled")):
        route_cidrs = post_ipsec_nat.get("translated_subnets") or []
    else:
        route_cidrs = selectors.get("remote_host_cidrs") or []
    return [str(value).strip() for value in route_cidrs if str(value).strip()]


def load_smartconnect_bundle(bundle_dir: Path) -> SmartconnectBundle:
    resolved_bundle = bundle_dir.resolve()
    customer_module_path = resolved_bundle / "customer" / "customer-module.json"
    if not customer_module_path.exists():
        raise ValueError(f"bundle missing customer/customer-module.json: {customer_module_path}")

    customer_module = _load_json(customer_module_path)
    customer = customer_module.get("customer") or {}
    customer_name = str(customer.get("name") or "").strip()
    if not customer_name:
        raise ValueError(f"bundle customer-module.json missing customer.name: {customer_module_path}")

    smartconnect_dir = resolved_bundle / "smartconnect"
    if not smartconnect_dir.is_dir():
        raise ValueError(f"bundle missing smartconnect directory: {smartconnect_dir}")

    source_files: dict[str, Path] = {}
    text_payloads: dict[str, str] = {}
    json_payloads: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for relative_name in SMARTCONNECT_REQUIRED_FILES:
        source_path = smartconnect_dir / relative_name
        if not source_path.exists():
            missing.append(relative_name)
            continue
        source_files[relative_name] = source_path
        if source_path.suffix == ".json":
            json_payloads[relative_name] = _load_json(source_path)
        else:
            text_payloads[relative_name] = source_path.read_text(encoding="utf-8")

    if missing:
        raise ValueError("bundle missing required SmartConnect files: " + ", ".join(missing))

    return SmartconnectBundle(
        bundle_dir=resolved_bundle,
        customer_name=customer_name,
        customer_module=customer_module,
        smartconnect_dir=smartconnect_dir,
        source_files=source_files,
        text_payloads=text_payloads,
        json_payloads=json_payloads,
    )


def validate_smartconnect_bundle(bundle_dir: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "bundle_dir": str(bundle_dir.resolve()),
        "customer_name": None,
        "errors": [],
        "warnings": [],
        "details": {},
        "valid": False,
    }

    try:
        bundle = load_smartconnect_bundle(bundle_dir)
    except Exception as exc:
        report["errors"].append(str(exc))
        return report

    report["customer_name"] = bundle.customer_name
    route_intent = bundle.json_payloads["routing/route-intent.json"]
    route_text = bundle.text_payloads["routing/ip-route.commands.txt"]

    unresolved = _find_json_placeholders(route_intent)
    if unresolved:
        report["errors"].append(
            "SmartConnect route intent has unresolved placeholders: " + ", ".join(unresolved)
        )
    unresolved = _find_placeholders(route_text)
    if unresolved:
        report["errors"].append(
            "SmartConnect route commands have unresolved placeholders: " + ", ".join(unresolved)
        )

    route_cidrs = [str(value).strip() for value in (route_intent.get("customer_route_cidrs") or []) if str(value).strip()]
    expected_route_cidrs = _expected_route_cidrs(bundle.customer_module)
    if route_cidrs != expected_route_cidrs:
        report["errors"].append("SmartConnect route CIDRs do not match the expected customer-side route scope")
    for cidr in route_cidrs:
        try:
            ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            report["errors"].append(f"SmartConnect route CIDR is not a valid IPv4 network: {cidr}")

    next_hop = str(route_intent.get("next_hop") or "").strip()
    route_device = str(route_intent.get("route_device") or "").strip()
    route_table = str(route_intent.get("route_table") or "").strip()
    if not route_table:
        report["errors"].append("SmartConnect route intent is missing route_table")
    if not route_device:
        report["errors"].append("SmartConnect route intent is missing route_device")
    if not next_hop:
        report["errors"].append("SmartConnect route intent is missing next_hop")
    else:
        try:
            ipaddress.ip_address(next_hop)
        except ValueError:
            report["errors"].append(f"SmartConnect next_hop is not a valid IPv4 address: {next_hop}")

    route_lines = _executable_lines(route_text)
    if len(route_lines) != len(route_cidrs):
        report["errors"].append("SmartConnect route command count does not match the intended CIDR count")
    for cidr in route_cidrs:
        expected_line = f"ip route replace table {route_table} {cidr} via {next_hop} dev {route_device}"
        if expected_line not in route_lines:
            report["errors"].append(f"SmartConnect route commands missing expected line: {expected_line}")

    report["details"]["route_count"] = len(route_cidrs)
    report["details"]["route_table"] = route_table
    report["details"]["route_device"] = route_device
    report["details"]["next_hop"] = next_hop
    report["details"]["customer_route_cidrs_source"] = route_intent.get("customer_route_cidrs_source")
    report["valid"] = not report["errors"]
    return report


def build_install_layout(smartconnect_root: Path, customer_name: str) -> dict[str, Path]:
    resolved_root = smartconnect_root.resolve()
    customer_root = resolved_root / SMARTCONNECT_STATE_ROOT / customer_name
    return {
        "smartconnect_root": resolved_root,
        "customer_root": customer_root,
        "artifacts_root": customer_root / "artifacts",
        "route_intent": customer_root / "routing" / "route-intent.json",
        "route_commands": customer_root / "routing" / "ip-route.commands.txt",
        "route_apply_script": customer_root / "routing" / "apply-routes.sh",
        "route_remove_script": customer_root / "routing" / "remove-routes.sh",
        "master_apply_script": customer_root / "apply-smartconnect-customer.sh",
        "master_remove_script": customer_root / "remove-smartconnect-customer.sh",
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


def _render_master_apply_script(customer_name: str) -> str:
    customer_root = f"/{SMARTCONNECT_STATE_ROOT.as_posix()}/{customer_name}"
    return _render_shell_script(
        [
            f'CUSTOMER_ROOT="{customer_root}"',
            'bash "${CUSTOMER_ROOT}/routing/apply-routes.sh"',
            'echo "applied_smartconnect_customer=' + customer_name + '"',
        ]
    )


def _render_master_remove_script(customer_name: str) -> str:
    customer_root = f"/{SMARTCONNECT_STATE_ROOT.as_posix()}/{customer_name}"
    return _render_shell_script(
        [
            f'CUSTOMER_ROOT="{customer_root}"',
            'if [ -f "${CUSTOMER_ROOT}/routing/remove-routes.sh" ]; then',
            '  bash "${CUSTOMER_ROOT}/routing/remove-routes.sh"',
            "fi",
            'rm -rf "${CUSTOMER_ROOT}"',
            'echo "removed_smartconnect_customer=' + customer_name + '"',
        ]
    )


def install_smartconnect_bundle(bundle_dir: Path, smartconnect_root: Path) -> dict[str, Any]:
    validation = validate_smartconnect_bundle(bundle_dir)
    if not validation["valid"]:
        raise ValueError("SmartConnect bundle is not installable: " + "; ".join(validation["errors"]))

    bundle = load_smartconnect_bundle(bundle_dir)
    layout = build_install_layout(smartconnect_root, bundle.customer_name)
    layout["customer_root"].mkdir(parents=True, exist_ok=True)
    if layout["artifacts_root"].exists():
        shutil.rmtree(layout["artifacts_root"])
    layout["artifacts_root"].mkdir(parents=True, exist_ok=True)

    for path in bundle.smartconnect_dir.rglob("*"):
        if path.is_dir():
            continue
        relative_name = path.relative_to(bundle.smartconnect_dir)
        destination = layout["artifacts_root"] / relative_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)

    _write_json(layout["route_intent"], bundle.json_payloads["routing/route-intent.json"])
    _write_text(layout["route_commands"], bundle.text_payloads["routing/ip-route.commands.txt"])
    _write_text(
        layout["route_apply_script"],
        _render_shell_script(_executable_lines(bundle.text_payloads["routing/ip-route.commands.txt"]) or ["true"]),
    )
    _write_text(
        layout["route_remove_script"],
        _render_shell_script(_derive_route_remove_lines(bundle.text_payloads["routing/ip-route.commands.txt"]) or ["true"]),
    )
    _write_text(layout["master_apply_script"], _render_master_apply_script(bundle.customer_name))
    _write_text(layout["master_remove_script"], _render_master_remove_script(bundle.customer_name))
    _write_json(
        layout["state_json"],
        {
            "schema_version": 1,
            "customer_name": bundle.customer_name,
            "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "route_count": len(bundle.json_payloads["routing/route-intent.json"].get("customer_route_cidrs") or []),
            "route_table": bundle.json_payloads["routing/route-intent.json"].get("route_table"),
            "route_device": bundle.json_payloads["routing/route-intent.json"].get("route_device"),
            "next_hop": bundle.json_payloads["routing/route-intent.json"].get("next_hop"),
        },
    )
    for key in ("route_apply_script", "route_remove_script", "master_apply_script", "master_remove_script"):
        _make_executable(layout[key])

    return {
        "customer_name": bundle.customer_name,
        "smartconnect_root": str(layout["smartconnect_root"]),
        "route_intent": str(layout["route_intent"]),
        "route_commands": str(layout["route_commands"]),
        "master_apply_script": str(layout["master_apply_script"]),
        "master_remove_script": str(layout["master_remove_script"]),
        "state_json": str(layout["state_json"]),
    }


def validate_installed_smartconnect(bundle_dir: Path, smartconnect_root: Path) -> dict[str, Any]:
    report = validate_smartconnect_bundle(bundle_dir)
    if not report["valid"]:
        return report

    bundle = load_smartconnect_bundle(bundle_dir)
    layout = build_install_layout(smartconnect_root, bundle.customer_name)
    for key in (
        "route_intent",
        "route_commands",
        "route_apply_script",
        "route_remove_script",
        "master_apply_script",
        "master_remove_script",
        "state_json",
    ):
        if not layout[key].exists():
            report["errors"].append(f"installed path missing: {layout[key]}")

    if layout["route_intent"].exists() and _load_json(layout["route_intent"]) != bundle.json_payloads["routing/route-intent.json"]:
        report["errors"].append(f"installed SmartConnect route intent does not match bundle: {layout['route_intent']}")
    if layout["route_commands"].exists():
        installed_text = layout["route_commands"].read_text(encoding="utf-8")
        if installed_text != bundle.text_payloads["routing/ip-route.commands.txt"]:
            report["errors"].append(f"installed SmartConnect route commands do not match bundle: {layout['route_commands']}")

    report["valid"] = not report["errors"]
    return report


def remove_installed_smartconnect(customer_name: str, smartconnect_root: Path) -> dict[str, Any]:
    layout = build_install_layout(smartconnect_root, customer_name)
    removed_paths: list[str] = []
    if layout["customer_root"].exists():
        shutil.rmtree(layout["customer_root"])
        removed_paths.append(str(layout["customer_root"]))
    return {
        "customer_name": customer_name,
        "smartconnect_root": str(layout["smartconnect_root"]),
        "removed": True,
        "removed_paths": removed_paths,
        "remaining_customer_root": layout["customer_root"].exists(),
    }
