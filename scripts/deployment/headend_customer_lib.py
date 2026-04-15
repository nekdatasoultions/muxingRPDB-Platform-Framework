"""Shared helpers for customer-scoped head-end staging and validation."""

from __future__ import annotations

import json
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
    "routing/routing-intent.json",
    "routing/ip-route.commands.txt",
    "post-ipsec-nat/post-ipsec-nat-intent.json",
    "post-ipsec-nat/iptables-snippet.txt",
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
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if payload.endswith("\n") else payload + "\n", encoding="utf-8")


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
    route_text = bundle.text_payloads["routing/ip-route.commands.txt"]
    nat_text = bundle.text_payloads["post-ipsec-nat/iptables-snippet.txt"]
    nat_intent = bundle.json_payloads["post-ipsec-nat/post-ipsec-nat-intent.json"]

    text_checks = {
        "ipsec/swanctl-connection.conf": swanctl_text,
        "routing/ip-route.commands.txt": route_text,
        "post-ipsec-nat/iptables-snippet.txt": nat_text,
    }

    for relative_name, payload in text_checks.items():
        unresolved = _find_placeholders(payload)
        if unresolved:
            report["errors"].append(
                f"headend file has unresolved placeholders: {relative_name} -> {', '.join(unresolved)}"
            )

    if "connections {" not in swanctl_text or "secrets {" not in swanctl_text:
        report["errors"].append("swanctl-connection.conf is missing required connections/secrets blocks")

    route_lines = _executable_lines(route_text)
    nat_lines = _executable_lines(nat_text)
    report["details"]["route_command_count"] = len(route_lines)
    report["details"]["post_ipsec_nat_command_count"] = len(nat_lines)

    if not route_lines:
        report["warnings"].append("routing/ip-route.commands.txt contains no executable route commands")

    if bool(nat_intent.get("enabled")) and not nat_lines:
        report["warnings"].append(
            "post-IPsec NAT is enabled in the intent, but iptables-snippet.txt contains no executable commands"
        )

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
        "route_commands": customer_root / "routing" / "ip-route.commands.txt",
        "route_apply_script": customer_root / "routing" / "apply-routes.sh",
        "route_remove_script": customer_root / "routing" / "remove-routes.sh",
        "nat_snippet": customer_root / "post-ipsec-nat" / "iptables-snippet.txt",
        "nat_apply_script": customer_root / "post-ipsec-nat" / "apply-post-ipsec-nat.sh",
        "nat_remove_script": customer_root / "post-ipsec-nat" / "remove-post-ipsec-nat.sh",
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


def _derive_iptables_remove_lines(nat_text: str) -> list[str]:
    removals: list[str] = []
    for line in _executable_lines(nat_text):
        if " -A " in line:
            removals.append(line.replace(" -A ", " -D ", 1) + " || true")
        elif " -I " in line:
            removals.append(line.replace(" -I ", " -D ", 1) + " || true")
        elif line.startswith("ip rule add "):
            removals.append("ip rule del " + line.removeprefix("ip rule add ") + " || true")
        else:
            removals.append(f"# manual firewall cleanup required: {line}")
    return removals


def _render_shell_script(lines: list[str]) -> str:
    return "\n".join(["#!/usr/bin/env bash", "set -eu", *lines]) + "\n"


def _render_master_apply_script(layout: dict[str, Path], customer_name: str) -> str:
    customer_root = f"/{HEADEND_STATE_ROOT.as_posix()}/{customer_name}"
    swanctl_conf = f"/{SWANCTL_CONF_ROOT.as_posix()}/{customer_name}.conf"
    return _render_shell_script(
        [
            'ROOT="${RPDB_HEADEND_ROOT:-/}"',
            'ROOT="${ROOT%/}"',
            f'CUSTOMER_ROOT="${{ROOT}}{customer_root}"',
            f'SWANCTL_CONF="${{ROOT}}{swanctl_conf}"',
            'bash "${CUSTOMER_ROOT}/routing/apply-routes.sh"',
            'bash "${CUSTOMER_ROOT}/post-ipsec-nat/apply-post-ipsec-nat.sh"',
            'if command -v swanctl >/dev/null 2>&1; then',
            '  swanctl --load-all',
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
            'if command -v swanctl >/dev/null 2>&1; then',
            '  swanctl --load-all',
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
    _write_text(layout["route_commands"], bundle.text_payloads["routing/ip-route.commands.txt"])
    _write_text(layout["nat_snippet"], bundle.text_payloads["post-ipsec-nat/iptables-snippet.txt"])

    route_remove_lines = _derive_route_remove_lines(bundle.text_payloads["routing/ip-route.commands.txt"])
    nat_remove_lines = _derive_iptables_remove_lines(bundle.text_payloads["post-ipsec-nat/iptables-snippet.txt"])

    route_apply_script = _render_shell_script(_executable_lines(bundle.text_payloads["routing/ip-route.commands.txt"]) or ["true"])
    route_remove_script = _render_shell_script(route_remove_lines or ["true"])
    nat_apply_script = _render_shell_script(_executable_lines(bundle.text_payloads["post-ipsec-nat/iptables-snippet.txt"]) or ["true"])
    nat_remove_script = _render_shell_script(nat_remove_lines or ["true"])

    _write_text(layout["route_apply_script"], route_apply_script)
    _write_text(layout["route_remove_script"], route_remove_script)
    _write_text(layout["nat_apply_script"], nat_apply_script)
    _write_text(layout["nat_remove_script"], nat_remove_script)
    _write_text(layout["master_apply_script"], _render_master_apply_script(layout, bundle.customer_name))
    _write_text(layout["master_remove_script"], _render_master_remove_script(layout, bundle.customer_name))

    for key in ("route_apply_script", "route_remove_script", "nat_apply_script", "nat_remove_script", "master_apply_script", "master_remove_script"):
        _make_executable(layout[key])

    state = {
        "schema_version": 1,
        "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "customer_name": bundle.customer_name,
        "bundle_dir": str(bundle.bundle_dir),
        "swanctl_conf": str(layout["swanctl_conf"]),
        "artifacts_root": str(layout["artifacts_root"]),
        "route_command_count": len(_executable_lines(bundle.text_payloads["routing/ip-route.commands.txt"])),
        "post_ipsec_nat_command_count": len(_executable_lines(bundle.text_payloads["post-ipsec-nat/iptables-snippet.txt"])),
        "paths": {name: str(path) for name, path in layout.items()},
    }
    _write_json(layout["state_json"], state)

    return {
        "customer_name": bundle.customer_name,
        "headend_root": str(layout["headend_root"]),
        "installed": True,
        "state_json": str(layout["state_json"]),
        "swanctl_conf": str(layout["swanctl_conf"]),
        "route_apply_script": str(layout["route_apply_script"]),
        "route_remove_script": str(layout["route_remove_script"]),
        "post_ipsec_nat_apply_script": str(layout["nat_apply_script"]),
        "post_ipsec_nat_remove_script": str(layout["nat_remove_script"]),
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
        "route_commands",
        "nat_snippet",
        "route_apply_script",
        "route_remove_script",
        "nat_apply_script",
        "nat_remove_script",
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

    if layout["nat_snippet"].exists():
        installed_nat_text = layout["nat_snippet"].read_text(encoding="utf-8")
        if installed_nat_text != bundle.text_payloads["post-ipsec-nat/iptables-snippet.txt"]:
            report["errors"].append(f"installed NAT snippet does not match bundle: {layout['nat_snippet']}")

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
