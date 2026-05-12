"""Helpers for customer-scoped CGNAT ISP gateway handoff installation."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CGNAT_STATE_ROOT = Path("var") / "lib" / "rpdb-cgnat" / "customers"
CGNAT_CONFIG_ROOT = Path("etc") / "rpdb-cgnat" / "customers"


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


def _runtime_path(gateway_root: Path, path: Path) -> str:
    return "/" + path.resolve().relative_to(gateway_root.resolve()).as_posix()


def _runtime_path_exists(gateway_root: Path, raw_path: str) -> bool:
    normalized = str(raw_path).replace("\\", "/")
    path = Path(raw_path)
    candidates = [path]
    if normalized.startswith("/"):
        candidates.append(gateway_root.resolve() / normalized.lstrip("/"))
    elif path.is_absolute():
        try:
            candidates.append(gateway_root.resolve() / path.relative_to("/"))
        except ValueError:
            pass
    else:
        candidates.append(gateway_root.resolve() / path)
    return any(candidate.exists() for candidate in candidates)


def _resolve_artifact_path(search_root: Path, value: Any, *, required: bool = True) -> Path | None:
    text = str(value or "").strip()
    candidates: list[Path] = []
    if text:
        raw = Path(text)
        candidates.append(raw)
        if not raw.is_absolute():
            candidates.append((search_root / raw).resolve())
        if raw.name:
            candidates.extend(sorted(search_root.rglob(raw.name)))
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    if required:
        raise ValueError(f"CGNAT gateway handoff artifact does not exist: {text or '<missing>'}")
    return None


def _copy_optional(source: Path | None, destination: Path) -> str:
    if source is None:
        return ""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return str(destination)


def _render_shell_script(lines: list[str]) -> str:
    return "\n".join(["#!/usr/bin/env bash", "set -eu", *lines]) + "\n"


def _load_gateway_handoff(pki_review_dir: Path) -> dict[str, Any]:
    review_path = pki_review_dir / "pki-review.json"
    if not review_path.exists():
        raise ValueError(f"CGNAT PKI review is missing pki-review.json: {review_path}")
    review = _load_json(review_path)
    if not bool(review.get("ready_for_review")):
        raise ValueError(f"CGNAT PKI review is not ready: {review_path}")
    gateway_handoff = dict(review.get("gateway_handoff") or {})
    artifacts = dict(review.get("artifacts") or {})
    if str(gateway_handoff.get("recipient_type") or "").strip() != "isp_gateway":
        raise ValueError("CGNAT PKI review does not contain an ISP gateway handoff")

    manifest_path = _resolve_artifact_path(
        pki_review_dir,
        artifacts.get("gateway_handoff_manifest") or gateway_handoff.get("manifest"),
    )
    readme_path = _resolve_artifact_path(
        pki_review_dir,
        artifacts.get("gateway_handoff_readme") or gateway_handoff.get("readme"),
        required=False,
    )
    assert manifest_path is not None
    manifest = _load_json(manifest_path)
    if str(manifest.get("recipient_type") or "").strip() != "isp_gateway":
        raise ValueError(f"CGNAT handoff manifest is not for an ISP gateway: {manifest_path}")

    cert_path = _resolve_artifact_path(pki_review_dir, manifest.get("certificate_path"))
    key_path = _resolve_artifact_path(pki_review_dir, manifest.get("private_key_path"))
    ca_path = _resolve_artifact_path(pki_review_dir, manifest.get("ca_certificate_path"))
    passphrase_path = _resolve_artifact_path(
        pki_review_dir,
        manifest.get("private_key_passphrase_path"),
        required=False,
    )
    return {
        "review": review,
        "review_path": review_path,
        "gateway_handoff": gateway_handoff,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "readme_path": readme_path,
        "cert_path": cert_path,
        "key_path": key_path,
        "ca_path": ca_path,
        "passphrase_path": passphrase_path,
    }


def build_install_layout(gateway_root: Path, customer_name: str) -> dict[str, Path]:
    resolved_root = gateway_root.resolve()
    customer_root = resolved_root / CGNAT_STATE_ROOT / customer_name
    handoff_root = customer_root / "gateway-handoff"
    config_root = resolved_root / CGNAT_CONFIG_ROOT
    return {
        "gateway_root": resolved_root,
        "customer_root": customer_root,
        "handoff_root": handoff_root,
        "manifest": handoff_root / "gateway-handoff-manifest.json",
        "readme": handoff_root / "README.md",
        "gateway_certificate": handoff_root / "gateway-outer.crt",
        "gateway_private_key": handoff_root / "gateway-outer.key",
        "ca_certificate": handoff_root / "outer-ca.crt",
        "private_key_passphrase": handoff_root / "gateway-outer-key.passphrase",
        "config_json": config_root / f"{customer_name}-gateway-handoff.json",
        "state_json": customer_root / "gateway-install-state.json",
        "master_apply_script": customer_root / "apply-cgnat-gateway-customer.sh",
        "master_remove_script": customer_root / "remove-cgnat-gateway-customer.sh",
        "applied_stamp": customer_root / "gateway-applied.stamp",
    }


def _expected_payload(customer_name: str, handoff: dict[str, Any], installed_files: dict[str, str]) -> dict[str, Any]:
    manifest = dict(handoff["manifest"])
    gateway_handoff = dict(handoff["gateway_handoff"])
    return {
        "schema_version": 1,
        "component": "cgnat_isp_gateway",
        "customer_name": customer_name,
        "outer_topology": manifest.get("outer_topology"),
        "outer_gateway_ref": manifest.get("outer_gateway_ref"),
        "identity_ref": manifest.get("identity_ref") or gateway_handoff.get("identity_ref"),
        "auth_ref": manifest.get("auth_ref") or gateway_handoff.get("auth_ref"),
        "package_name": manifest.get("package_name") or gateway_handoff.get("package_name"),
        "material_mode": manifest.get("material_mode"),
        "installed_files": installed_files,
    }


def _render_master_apply_script(layout: dict[str, Path]) -> str:
    customer_root = _runtime_path(layout["gateway_root"], layout["customer_root"])
    applied_stamp = _runtime_path(layout["gateway_root"], layout["applied_stamp"])
    config_json = _runtime_path(layout["gateway_root"], layout["config_json"])
    manifest = _runtime_path(layout["gateway_root"], layout["manifest"])
    return _render_shell_script(
        [
            'ROOT="${RPDB_CGNAT_ROOT:-/}"',
            'ROOT="${ROOT%/}"',
            f'CUSTOMER_ROOT="${{ROOT}}{customer_root}"',
            f'APPLIED_STAMP="${{ROOT}}{applied_stamp}"',
            f'CONFIG_JSON="${{ROOT}}{config_json}"',
            f'MANIFEST="${{ROOT}}{manifest}"',
            'test -f "${CUSTOMER_ROOT}/gateway-install-state.json"',
            'test -f "${CONFIG_JSON}"',
            'test -f "${MANIFEST}"',
            'date -u +%Y-%m-%dT%H:%M:%SZ > "${APPLIED_STAMP}"',
            'echo "cgnat_gateway_customer_staged=${CUSTOMER_ROOT}"',
        ]
    )


def _render_master_remove_script(layout: dict[str, Path]) -> str:
    customer_root = _runtime_path(layout["gateway_root"], layout["customer_root"])
    config_json = _runtime_path(layout["gateway_root"], layout["config_json"])
    return _render_shell_script(
        [
            'ROOT="${RPDB_CGNAT_ROOT:-/}"',
            'ROOT="${ROOT%/}"',
            f'CUSTOMER_ROOT="${{ROOT}}{customer_root}"',
            f'CONFIG_JSON="${{ROOT}}{config_json}"',
            'rm -f "${CONFIG_JSON}"',
            'rm -rf "${CUSTOMER_ROOT}"',
            'echo "removed_cgnat_gateway_customer=${CUSTOMER_ROOT}"',
        ]
    )


def install_gateway_handoff(*, customer_name: str, gateway_root: Path, pki_review_dir: Path) -> dict[str, Any]:
    handoff = _load_gateway_handoff(pki_review_dir.resolve())
    layout = build_install_layout(gateway_root, customer_name)
    if layout["customer_root"].exists():
        shutil.rmtree(layout["customer_root"])
    layout["handoff_root"].mkdir(parents=True, exist_ok=True)
    layout["config_json"].parent.mkdir(parents=True, exist_ok=True)

    shutil.copy2(handoff["manifest_path"], layout["manifest"])
    if handoff["readme_path"]:
        shutil.copy2(handoff["readme_path"], layout["readme"])
    else:
        _write_text(layout["readme"], "# CGNAT ISP Gateway Handoff\n")
    copied = {
        "gateway_certificate": _copy_optional(handoff["cert_path"], layout["gateway_certificate"]),
        "gateway_private_key": _copy_optional(handoff["key_path"], layout["gateway_private_key"]),
        "ca_certificate": _copy_optional(handoff["ca_path"], layout["ca_certificate"]),
        "private_key_passphrase": _copy_optional(handoff["passphrase_path"], layout["private_key_passphrase"]),
    }
    installed_files = {
        key: _runtime_path(layout["gateway_root"], Path(value))
        for key, value in copied.items()
        if value
    }
    payload = _expected_payload(customer_name, handoff, installed_files)
    _write_json(layout["config_json"], payload)
    _write_text(layout["master_apply_script"], _render_master_apply_script(layout))
    _write_text(layout["master_remove_script"], _render_master_remove_script(layout))
    _make_executable(layout["master_apply_script"])
    _make_executable(layout["master_remove_script"])
    state = {
        "schema_version": 1,
        "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "customer_name": customer_name,
        "pki_review": str((pki_review_dir / "pki-review.json").resolve()),
        "gateway_handoff": payload,
        "paths": {
            key: _runtime_path(layout["gateway_root"], path)
            for key, path in layout.items()
            if key != "gateway_root"
        },
    }
    _write_json(layout["state_json"], state)
    return {
        "customer_name": customer_name,
        "gateway_root": str(layout["gateway_root"]),
        "installed": True,
        "state_json": str(layout["state_json"]),
        "config_json": str(layout["config_json"]),
        "manifest": str(layout["manifest"]),
        "handoff_root": str(layout["handoff_root"]),
        "master_apply_script": str(layout["master_apply_script"]),
        "master_remove_script": str(layout["master_remove_script"]),
        "installed_files": installed_files,
    }


def validate_installed_gateway_handoff(*, customer_name: str, gateway_root: Path, pki_review_dir: Path) -> dict[str, Any]:
    report = {
        "customer_name": customer_name,
        "gateway_root": str(gateway_root.resolve()),
        "valid": False,
        "errors": [],
        "warnings": [],
        "details": {},
    }
    try:
        handoff = _load_gateway_handoff(pki_review_dir.resolve())
    except Exception as exc:
        report["errors"].append(str(exc))
        return report
    layout = build_install_layout(gateway_root, customer_name)
    required_paths = [
        "customer_root",
        "handoff_root",
        "manifest",
        "readme",
        "gateway_certificate",
        "gateway_private_key",
        "ca_certificate",
        "config_json",
        "state_json",
        "master_apply_script",
        "master_remove_script",
    ]
    for key in required_paths:
        if not layout[key].exists():
            report["errors"].append(f"installed gateway handoff path missing: {layout[key]}")
    if layout["state_json"].exists():
        state = _load_json(layout["state_json"])
        report["details"]["install_state"] = state
        installed_files = ((state.get("gateway_handoff") or {}).get("installed_files") or {})
        for label, path in installed_files.items():
            if not _runtime_path_exists(gateway_root, str(path)):
                report["errors"].append(f"installed gateway PKI file missing for {label}: {path}")
    if layout["config_json"].exists():
        config = _load_json(layout["config_json"])
        expected_files = {
            "gateway_certificate": _runtime_path(layout["gateway_root"], layout["gateway_certificate"]),
            "gateway_private_key": _runtime_path(layout["gateway_root"], layout["gateway_private_key"]),
            "ca_certificate": _runtime_path(layout["gateway_root"], layout["ca_certificate"]),
        }
        if layout["private_key_passphrase"].exists():
            expected_files["private_key_passphrase"] = _runtime_path(
                layout["gateway_root"],
                layout["private_key_passphrase"],
            )
        expected = _expected_payload(
            customer_name,
            handoff,
            expected_files,
        )
        if config != expected:
            report["errors"].append(f"installed gateway handoff config does not match expected payload: {layout['config_json']}")
    report["valid"] = not report["errors"]
    return report


def remove_installed_gateway_handoff(customer_name: str, gateway_root: Path) -> dict[str, Any]:
    layout = build_install_layout(gateway_root, customer_name)
    removed_paths: list[str] = []
    if layout["config_json"].exists():
        layout["config_json"].unlink()
        removed_paths.append(str(layout["config_json"]))
    if layout["customer_root"].exists():
        shutil.rmtree(layout["customer_root"])
        removed_paths.append(str(layout["customer_root"]))
    return {
        "customer_name": customer_name,
        "gateway_root": str(layout["gateway_root"]),
        "removed": True,
        "removed_paths": removed_paths,
        "remaining_customer_root": layout["customer_root"].exists(),
        "remaining_config_json": layout["config_json"].exists(),
    }
