"""Shared helpers for customer-scoped CGNAT head-end staging and validation."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


CGNAT_STATE_ROOT = Path("var") / "lib" / "rpdb-cgnat" / "customers"
CGNAT_CONFIG_ROOT = Path("etc") / "rpdb-cgnat" / "customers"


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


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _customer_name_from_package(package_dir: Path) -> str:
    source_path = package_dir / "customer-source.yaml"
    if not source_path.exists():
        raise ValueError(f"package missing customer-source.yaml: {source_path}")
    source_doc = _load_yaml(source_path)
    customer_name = str(((source_doc.get("customer") or {}).get("name")) or "").strip()
    if not customer_name:
        raise ValueError(f"package customer-source.yaml missing customer.name: {source_path}")
    return customer_name


def load_cgnat_package(package_dir: Path) -> dict[str, Any]:
    resolved_package = package_dir.resolve()
    source_path = resolved_package / "customer-source.yaml"
    module_path = resolved_package / "customer-module.json"
    if not source_path.exists():
        raise ValueError(f"package missing customer-source.yaml: {source_path}")
    if not module_path.exists():
        raise ValueError(f"package missing customer-module.json: {module_path}")

    source_doc = _load_yaml(source_path)
    module_doc = _load_json(module_path)
    customer_name = str(((source_doc.get("customer") or {}).get("name")) or "").strip()
    if not customer_name:
        raise ValueError(f"package customer-source.yaml missing customer.name: {source_path}")

    transport = dict(((source_doc.get("customer") or {}).get("transport")) or {})
    if str(transport.get("mode") or "").strip().lower() != "cgnat":
        raise ValueError("package customer-source.yaml is not a CGNAT customer package")
    cgnat_transport = dict(transport.get("cgnat") or {})
    required = [
        "service_profile",
        "outer_identity_ref",
        "outer_auth_ref",
        "customer_loopback_ip",
        "known_inside_identity",
    ]
    missing = [field for field in required if not str(cgnat_transport.get(field) or "").strip()]
    if missing:
        raise ValueError(
            "package customer-source.yaml is missing required customer.transport.cgnat fields: "
            + ", ".join(missing)
        )

    return {
        "package_dir": resolved_package,
        "customer_name": customer_name,
        "source_path": source_path,
        "module_path": module_path,
        "source_doc": source_doc,
        "module_doc": module_doc,
        "transport": transport,
        "cgnat_transport": cgnat_transport,
    }


def validate_cgnat_package(package_dir: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "package_dir": str(package_dir.resolve()),
        "customer_name": None,
        "errors": [],
        "warnings": [],
        "details": {},
        "valid": False,
    }
    try:
        package = load_cgnat_package(package_dir)
    except Exception as exc:
        report["errors"].append(str(exc))
        return report

    report["customer_name"] = package["customer_name"]
    report["details"]["service_profile"] = package["cgnat_transport"].get("service_profile")
    report["details"]["outer_identity_ref"] = package["cgnat_transport"].get("outer_identity_ref")
    report["details"]["outer_auth_ref"] = package["cgnat_transport"].get("outer_auth_ref")
    report["details"]["customer_loopback_ip"] = package["cgnat_transport"].get("customer_loopback_ip")
    report["details"]["known_inside_identity"] = package["cgnat_transport"].get("known_inside_identity")
    report["details"]["service_reachable_subnets"] = list(
        package["cgnat_transport"].get("service_reachable_subnets") or []
    )
    report["valid"] = not report["errors"]
    return report


def build_install_layout(cgnat_root: Path, customer_name: str) -> dict[str, Path]:
    resolved_root = cgnat_root.resolve()
    customer_root = resolved_root / CGNAT_STATE_ROOT / customer_name
    config_root = resolved_root / CGNAT_CONFIG_ROOT
    return {
        "cgnat_root": resolved_root,
        "customer_root": customer_root,
        "artifacts_root": customer_root / "artifacts",
        "customer_source": customer_root / "customer-source.yaml",
        "customer_module": customer_root / "customer-module.json",
        "transport_json": customer_root / "cgnat-transport.json",
        "config_json": config_root / f"{customer_name}.json",
        "master_apply_script": customer_root / "apply-cgnat-customer.sh",
        "master_remove_script": customer_root / "remove-cgnat-customer.sh",
        "applied_stamp": customer_root / "applied.stamp",
        "state_json": customer_root / "install-state.json",
    }


def _render_master_apply_script(layout: dict[str, Path]) -> str:
    customer_root = "/" + layout["customer_root"].relative_to(layout["cgnat_root"]).as_posix()
    config_json = "/" + layout["config_json"].relative_to(layout["cgnat_root"]).as_posix()
    applied_stamp = "/" + layout["applied_stamp"].relative_to(layout["cgnat_root"]).as_posix()
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -eu",
            'ROOT="${RPDB_CGNAT_ROOT:-/}"',
            'ROOT="${ROOT%/}"',
            f'CUSTOMER_ROOT="${{ROOT}}{customer_root}"',
            f'CONFIG_JSON="${{ROOT}}{config_json}"',
            f'APPLIED_STAMP="${{ROOT}}{applied_stamp}"',
            'test -f "${CUSTOMER_ROOT}/customer-source.yaml"',
            'test -f "${CUSTOMER_ROOT}/customer-module.json"',
            'test -f "${CUSTOMER_ROOT}/cgnat-transport.json"',
            'test -f "${CONFIG_JSON}"',
            'date -u +%Y-%m-%dT%H:%M:%SZ > "${APPLIED_STAMP}"',
            "",
        ]
    )


def _render_master_remove_script(layout: dict[str, Path]) -> str:
    customer_root = "/" + layout["customer_root"].relative_to(layout["cgnat_root"]).as_posix()
    config_json = "/" + layout["config_json"].relative_to(layout["cgnat_root"]).as_posix()
    applied_stamp = "/" + layout["applied_stamp"].relative_to(layout["cgnat_root"]).as_posix()
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -eu",
            'ROOT="${RPDB_CGNAT_ROOT:-/}"',
            'ROOT="${ROOT%/}"',
            f'CUSTOMER_ROOT="${{ROOT}}{customer_root}"',
            f'CONFIG_JSON="${{ROOT}}{config_json}"',
            f'APPLIED_STAMP="${{ROOT}}{applied_stamp}"',
            'rm -f "${APPLIED_STAMP}"',
            'rm -f "${CONFIG_JSON}"',
            'rm -rf "${CUSTOMER_ROOT}"',
            "",
        ]
    )


def install_cgnat_package(package_dir: Path, cgnat_root: Path) -> dict[str, Any]:
    validation = validate_cgnat_package(package_dir)
    if not validation["valid"]:
        raise ValueError("CGNAT package is not installable: " + "; ".join(validation["errors"]))

    package = load_cgnat_package(package_dir)
    layout = build_install_layout(cgnat_root, package["customer_name"])
    if layout["artifacts_root"].exists():
        shutil.rmtree(layout["artifacts_root"])
    layout["artifacts_root"].mkdir(parents=True, exist_ok=True)
    layout["config_json"].parent.mkdir(parents=True, exist_ok=True)

    shutil.copy2(package["source_path"], layout["customer_source"])
    shutil.copy2(package["module_path"], layout["customer_module"])
    shutil.copy2(package["source_path"], layout["artifacts_root"] / "customer-source.yaml")
    shutil.copy2(package["module_path"], layout["artifacts_root"] / "customer-module.json")
    _write_json(layout["transport_json"], package["cgnat_transport"])
    _write_json(layout["config_json"], package["cgnat_transport"])
    _write_text(layout["master_apply_script"], _render_master_apply_script(layout))
    _write_text(layout["master_remove_script"], _render_master_remove_script(layout))
    _make_executable(layout["master_apply_script"])
    _make_executable(layout["master_remove_script"])

    state = {
        "schema_version": 1,
        "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "customer_name": package["customer_name"],
        "package_dir": str(package["package_dir"]),
        "transport": package["cgnat_transport"],
        "paths": {name: str(path) for name, path in layout.items()},
    }
    _write_json(layout["state_json"], state)

    return {
        "customer_name": package["customer_name"],
        "cgnat_root": str(layout["cgnat_root"]),
        "installed": True,
        "state_json": str(layout["state_json"]),
        "config_json": str(layout["config_json"]),
        "transport_json": str(layout["transport_json"]),
        "master_apply_script": str(layout["master_apply_script"]),
        "master_remove_script": str(layout["master_remove_script"]),
    }


def validate_installed_cgnat(package_dir: Path, cgnat_root: Path) -> dict[str, Any]:
    report = validate_cgnat_package(package_dir)
    if not report["valid"]:
        return report

    package = load_cgnat_package(package_dir)
    layout = build_install_layout(cgnat_root, package["customer_name"])
    for key in (
        "customer_source",
        "customer_module",
        "transport_json",
        "config_json",
        "master_apply_script",
        "master_remove_script",
        "state_json",
    ):
        if not layout[key].exists():
            report["errors"].append(f"installed path missing: {layout[key]}")

    if layout["transport_json"].exists():
        installed_transport = _load_json(layout["transport_json"])
        if installed_transport != package["cgnat_transport"]:
            report["errors"].append(f"installed CGNAT transport does not match package: {layout['transport_json']}")
    if layout["config_json"].exists():
        installed_config = _load_json(layout["config_json"])
        if installed_config != package["cgnat_transport"]:
            report["errors"].append(f"installed CGNAT config does not match package: {layout['config_json']}")
    if layout["state_json"].exists():
        state = _load_json(layout["state_json"])
        report["details"]["install_state"] = state
        if state.get("customer_name") != package["customer_name"]:
            report["errors"].append(f"install-state customer mismatch in {layout['state_json']}")

    report["details"]["installed_root"] = str(layout["customer_root"])
    report["details"]["installed_config"] = str(layout["config_json"])
    report["valid"] = not report["errors"]
    return report


def remove_installed_cgnat(customer_name: str, cgnat_root: Path) -> dict[str, Any]:
    layout = build_install_layout(cgnat_root, customer_name)
    removed_paths: list[str] = []
    if layout["config_json"].exists():
        layout["config_json"].unlink()
        removed_paths.append(str(layout["config_json"]))
    if layout["customer_root"].exists():
        shutil.rmtree(layout["customer_root"])
        removed_paths.append(str(layout["customer_root"]))
    return {
        "customer_name": customer_name,
        "cgnat_root": str(layout["cgnat_root"]),
        "removed": True,
        "removed_paths": removed_paths,
        "remaining_customer_root": layout["customer_root"].exists(),
        "remaining_config_json": layout["config_json"].exists(),
    }
