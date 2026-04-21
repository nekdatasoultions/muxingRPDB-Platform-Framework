"""Shared helpers for customer-scoped backend staging and validation."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PLACEHOLDER_RE = re.compile(r"\$\{[^}]+\}")
BACKEND_REQUIRED_FILES = (
    "customer-module.json",
    "customer-ddb-item.json",
    "allocation-summary.json",
    "allocation-ddb-items.json",
)

BACKEND_CUSTOMER_ROOT = Path("var") / "lib" / "rpdb-backend" / "customers"
BACKEND_ALLOCATION_ROOT = Path("var") / "lib" / "rpdb-backend" / "allocations"


@dataclass(frozen=True)
class BackendPackage:
    package_dir: Path
    customer_name: str
    customer_module: dict[str, Any]
    customer_ddb_item: dict[str, Any]
    allocation_summary: dict[str, Any]
    allocation_ddb_items: list[dict[str, Any]]
    customer_source_text: str | None


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
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


def _find_json_placeholders(payload: Any) -> list[str]:
    return _find_placeholders(json.dumps(payload, sort_keys=True))


def load_backend_package(package_dir: Path) -> BackendPackage:
    resolved_package = package_dir.resolve()
    missing = [
        relative_name
        for relative_name in BACKEND_REQUIRED_FILES
        if not (resolved_package / relative_name).exists()
    ]
    if missing:
        raise ValueError("package missing required backend files: " + ", ".join(missing))

    customer_module = _load_json(resolved_package / "customer-module.json")
    customer = customer_module.get("customer") or {}
    customer_name = str(customer.get("name") or "").strip()
    if not customer_name:
        raise ValueError(f"package customer-module.json missing customer.name: {resolved_package}")

    customer_ddb_item = _load_json(resolved_package / "customer-ddb-item.json")
    allocation_summary = _load_json(resolved_package / "allocation-summary.json")
    allocation_ddb_items = _load_json(resolved_package / "allocation-ddb-items.json")
    if not isinstance(allocation_ddb_items, list):
        raise ValueError("allocation-ddb-items.json must contain a JSON array")

    customer_source_path = resolved_package / "customer-source.yaml"
    customer_source_text = (
        customer_source_path.read_text(encoding="utf-8") if customer_source_path.exists() else None
    )

    return BackendPackage(
        package_dir=resolved_package,
        customer_name=customer_name,
        customer_module=customer_module,
        customer_ddb_item=customer_ddb_item,
        allocation_summary=allocation_summary,
        allocation_ddb_items=allocation_ddb_items,
        customer_source_text=customer_source_text,
    )


def validate_backend_package(package_dir: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "package_dir": str(package_dir.resolve()),
        "customer_name": None,
        "errors": [],
        "warnings": [],
        "details": {},
        "valid": False,
    }

    try:
        package = load_backend_package(package_dir)
    except Exception as exc:
        report["errors"].append(str(exc))
        return report

    report["customer_name"] = package.customer_name
    customer_name = package.customer_name

    if str(package.customer_ddb_item.get("customer_name") or "").strip() != customer_name:
        report["errors"].append("customer-ddb-item.json customer_name does not match customer-module.json")
    if str(package.allocation_summary.get("customer_name") or "").strip() != customer_name:
        report["errors"].append("allocation-summary.json customer_name does not match customer-module.json")

    if not package.allocation_ddb_items:
        report["errors"].append("allocation-ddb-items.json contains no allocation records")

    placeholder_checks = {
        "customer-module.json": package.customer_module,
        "customer-ddb-item.json": package.customer_ddb_item,
        "allocation-summary.json": package.allocation_summary,
        "allocation-ddb-items.json": package.allocation_ddb_items,
    }
    for relative_name, payload in placeholder_checks.items():
        unresolved = _find_json_placeholders(payload)
        if unresolved:
            report["errors"].append(
                f"backend JSON file has unresolved placeholders: {relative_name} -> {', '.join(unresolved)}"
            )

    if package.customer_source_text is not None:
        unresolved = _find_placeholders(package.customer_source_text)
        if unresolved:
            report["errors"].append(
                "backend source file has unresolved placeholders: " + ", ".join(unresolved)
            )

    allocation_customer_names = {
        str((item.get("customer_name") or {}).get("S") or "").strip()
        for item in package.allocation_ddb_items
    }
    if allocation_customer_names != {customer_name}:
        report["errors"].append("allocation-ddb-items.json contains records for unexpected customers")

    report["details"]["allocation_count"] = len(package.allocation_ddb_items)
    report["details"]["resource_types"] = sorted(
        {
            str((item.get("resource_type") or {}).get("S") or "").strip()
            for item in package.allocation_ddb_items
            if str((item.get("resource_type") or {}).get("S") or "").strip()
        }
    )
    report["details"]["backend_cluster"] = (
        package.customer_module.get("backend") or {}
    ).get("cluster")
    report["details"]["backend_assignment"] = (
        package.customer_module.get("backend") or {}
    ).get("assignment")
    report["valid"] = not report["errors"]
    return report


def build_install_layout(backend_root: Path, customer_name: str) -> dict[str, Path]:
    resolved_root = backend_root.resolve()
    customer_root = resolved_root / BACKEND_CUSTOMER_ROOT / customer_name
    allocation_root = resolved_root / BACKEND_ALLOCATION_ROOT / customer_name
    return {
        "backend_root": resolved_root,
        "customer_root": customer_root,
        "allocation_root": allocation_root,
        "customer_module": customer_root / "customer-module.json",
        "customer_ddb_item": customer_root / "customer-ddb-item.json",
        "customer_source": customer_root / "customer-source.yaml",
        "allocation_summary": allocation_root / "allocation-summary.json",
        "allocation_ddb_items": allocation_root / "allocation-ddb-items.json",
        "apply_script": customer_root / "apply-backend-customer.sh",
        "remove_script": customer_root / "remove-backend-customer.sh",
        "state_json": customer_root / "install-state.json",
    }


def _render_shell_script(lines: list[str]) -> str:
    return "\n".join(["#!/usr/bin/env bash", "set -eu", *lines]) + "\n"


def _render_apply_script(customer_name: str) -> str:
    customer_root = f"/{BACKEND_CUSTOMER_ROOT.as_posix()}/{customer_name}"
    allocation_root = f"/{BACKEND_ALLOCATION_ROOT.as_posix()}/{customer_name}"
    return _render_shell_script(
        [
            'ROOT="${RPDB_BACKEND_ROOT:-/}"',
            'ROOT="${ROOT%/}"',
            f'CUSTOMER_ROOT="${{ROOT}}{customer_root}"',
            f'ALLOCATION_ROOT="${{ROOT}}{allocation_root}"',
            'test -f "${CUSTOMER_ROOT}/customer-ddb-item.json"',
            'test -f "${ALLOCATION_ROOT}/allocation-ddb-items.json"',
            'echo "staged backend customer payload ready at ${CUSTOMER_ROOT}"',
        ]
    )


def _render_remove_script(customer_name: str) -> str:
    customer_root = f"/{BACKEND_CUSTOMER_ROOT.as_posix()}/{customer_name}"
    allocation_root = f"/{BACKEND_ALLOCATION_ROOT.as_posix()}/{customer_name}"
    return _render_shell_script(
        [
            'ROOT="${RPDB_BACKEND_ROOT:-/}"',
            'ROOT="${ROOT%/}"',
            f'CUSTOMER_ROOT="${{ROOT}}{customer_root}"',
            f'ALLOCATION_ROOT="${{ROOT}}{allocation_root}"',
            'rm -rf "${CUSTOMER_ROOT}"',
            'rm -rf "${ALLOCATION_ROOT}"',
        ]
    )


def install_backend_package(package_dir: Path, backend_root: Path) -> dict[str, Any]:
    validation = validate_backend_package(package_dir)
    if not validation["valid"]:
        raise ValueError("backend package is not installable: " + "; ".join(validation["errors"]))

    package = load_backend_package(package_dir)
    layout = build_install_layout(backend_root, package.customer_name)
    layout["customer_root"].mkdir(parents=True, exist_ok=True)
    layout["allocation_root"].mkdir(parents=True, exist_ok=True)

    _write_json(layout["customer_module"], package.customer_module)
    _write_json(layout["customer_ddb_item"], package.customer_ddb_item)
    if package.customer_source_text is not None:
        _write_text(layout["customer_source"], package.customer_source_text)
    _write_json(layout["allocation_summary"], package.allocation_summary)
    _write_json(layout["allocation_ddb_items"], package.allocation_ddb_items)
    _write_text(layout["apply_script"], _render_apply_script(package.customer_name))
    _write_text(layout["remove_script"], _render_remove_script(package.customer_name))
    _make_executable(layout["apply_script"])
    _make_executable(layout["remove_script"])

    state = {
        "schema_version": 1,
        "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "customer_name": package.customer_name,
        "package_dir": str(package.package_dir),
        "customer_root": str(layout["customer_root"]),
        "allocation_root": str(layout["allocation_root"]),
        "paths": {name: str(path) for name, path in layout.items()},
    }
    _write_json(layout["state_json"], state)

    return {
        "customer_name": package.customer_name,
        "backend_root": str(layout["backend_root"]),
        "installed": True,
        "customer_root": str(layout["customer_root"]),
        "allocation_root": str(layout["allocation_root"]),
        "state_json": str(layout["state_json"]),
    }


def validate_installed_backend(package_dir: Path, backend_root: Path) -> dict[str, Any]:
    report = validate_backend_package(package_dir)
    if not report["valid"]:
        return report

    package = load_backend_package(package_dir)
    layout = build_install_layout(backend_root, package.customer_name)
    for key in (
        "customer_module",
        "customer_ddb_item",
        "allocation_summary",
        "allocation_ddb_items",
        "apply_script",
        "remove_script",
        "state_json",
    ):
        if not layout[key].exists():
            report["errors"].append(f"installed path missing: {layout[key]}")

    json_checks = {
        "customer_module": package.customer_module,
        "customer_ddb_item": package.customer_ddb_item,
        "allocation_summary": package.allocation_summary,
        "allocation_ddb_items": package.allocation_ddb_items,
    }
    for layout_key, expected in json_checks.items():
        if layout[layout_key].exists():
            actual = _load_json(layout[layout_key])
            if actual != expected:
                report["errors"].append(f"installed JSON does not match package: {layout[layout_key]}")

    if package.customer_source_text is not None:
        if not layout["customer_source"].exists():
            report["errors"].append(f"installed path missing: {layout['customer_source']}")
        else:
            actual_source = layout["customer_source"].read_text(encoding="utf-8")
            if actual_source != package.customer_source_text:
                report["errors"].append(
                    f"installed source does not match package: {layout['customer_source']}"
                )

    if layout["state_json"].exists():
        state = _load_json(layout["state_json"])
        report["details"]["install_state"] = state
        if state.get("customer_name") != package.customer_name:
            report["errors"].append(f"install-state customer mismatch in {layout['state_json']}")

    report["details"]["installed_customer_root"] = str(layout["customer_root"])
    report["details"]["installed_allocation_root"] = str(layout["allocation_root"])
    report["valid"] = not report["errors"]
    return report


def remove_installed_backend(customer_name: str, backend_root: Path) -> dict[str, Any]:
    layout = build_install_layout(backend_root, customer_name)
    removed_paths: list[str] = []

    if layout["customer_root"].exists():
        shutil.rmtree(layout["customer_root"])
        removed_paths.append(str(layout["customer_root"]))

    if layout["allocation_root"].exists():
        shutil.rmtree(layout["allocation_root"])
        removed_paths.append(str(layout["allocation_root"]))

    return {
        "customer_name": customer_name,
        "backend_root": str(layout["backend_root"]),
        "removed": True,
        "removed_paths": removed_paths,
        "remaining_customer_root": layout["customer_root"].exists(),
        "remaining_allocation_root": layout["allocation_root"].exists(),
    }
