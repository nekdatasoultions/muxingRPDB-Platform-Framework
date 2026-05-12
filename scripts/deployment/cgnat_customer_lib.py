"""Shared helpers for customer-scoped CGNAT head-end staging and validation."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


PLACEHOLDER_RE = re.compile(r"\$\{[^}]+\}")
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


def _find_placeholders(text: str) -> list[str]:
    return sorted(set(PLACEHOLDER_RE.findall(text)))


def _find_json_placeholders(payload: dict[str, Any]) -> list[str]:
    return _find_placeholders(json.dumps(payload, sort_keys=True))


def _render_shell_script(lines: list[str]) -> str:
    return "\n".join(["#!/usr/bin/env bash", "set -eu", *lines]) + "\n"


def load_cgnat_package(package_dir: Path) -> dict[str, Any]:
    resolved_package = package_dir.resolve()
    source_path = resolved_package / "customer-source.yaml"
    module_path = resolved_package / "customer-module.json"
    if not source_path.exists():
        raise ValueError(f"package missing customer-source.yaml: {source_path}")
    if not module_path.exists():
        raise ValueError(f"package missing customer-module.json: {module_path}")

    source_text = source_path.read_text(encoding="utf-8")
    source_doc = _load_yaml(source_path)
    module_doc = _load_json(module_path)
    customer_name = str(((source_doc.get("customer") or {}).get("name")) or "").strip()
    if not customer_name:
        raise ValueError(f"package customer-source.yaml missing customer.name: {source_path}")

    transport = dict(((source_doc.get("customer") or {}).get("transport")) or {})
    module_transport = dict(module_doc.get("transport") or {})
    if str(transport.get("mode") or "").strip().lower() != "cgnat":
        raise ValueError("package customer-source.yaml is not a CGNAT customer package")
    if str(module_transport.get("mode") or "").strip().lower() != "cgnat":
        raise ValueError("package customer-module.json is not a CGNAT customer module")

    cgnat_transport = dict(transport.get("cgnat") or {})
    module_cgnat = dict(module_transport.get("cgnat") or {})
    required = [
        "service_profile",
        "outer_topology",
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
    for field in required:
        if str(module_cgnat.get(field) or "").strip() != str(cgnat_transport.get(field) or "").strip():
            raise ValueError(f"package customer-module.json transport.cgnat.{field} does not match customer-source.yaml")
    if str(cgnat_transport.get("outer_topology") or "").strip() == "shared_isp_gateway":
        if not str(cgnat_transport.get("outer_gateway_ref") or "").strip():
            raise ValueError("package customer-source.yaml shared_isp_gateway requires customer.transport.cgnat.outer_gateway_ref")
        if str(module_cgnat.get("outer_gateway_ref") or "").strip() != str(cgnat_transport.get("outer_gateway_ref") or "").strip():
            raise ValueError(
                "package customer-module.json transport.cgnat.outer_gateway_ref does not match customer-source.yaml"
            )

    return {
        "package_dir": resolved_package,
        "customer_name": customer_name,
        "source_path": source_path,
        "module_path": module_path,
        "source_text": source_text,
        "source_doc": source_doc,
        "module_doc": module_doc,
        "transport": transport,
        "module_transport": module_transport,
        "cgnat_transport": cgnat_transport,
        "module_cgnat": module_cgnat,
    }


def _build_runtime_payloads(package: dict[str, Any]) -> dict[str, dict[str, Any]]:
    customer = dict((package["source_doc"].get("customer") or {}))
    module = dict(package["module_doc"] or {})
    cgnat_transport = dict(package["cgnat_transport"] or {})
    module_transport = dict(package["module_transport"] or {})
    backend = dict(module.get("backend") or {})
    peer = dict(module.get("peer") or {})
    selectors = dict(module.get("selectors") or {})
    protocols = dict(module.get("protocols") or {})
    ipsec = dict(module.get("ipsec") or {})
    overlay = dict(module_transport.get("overlay") or {})

    customer_summary = {
        "schema_version": 1,
        "customer_name": package["customer_name"],
        "customer_class": customer.get("customer_class"),
        "backend_cluster": backend.get("cluster"),
        "backend_role": backend.get("role"),
        "transport_mode": module_transport.get("mode"),
        "peer_ip": peer.get("public_ip"),
        "generated_from_package": str(package["package_dir"]),
    }
    transport_profile = {
        "schema_version": 1,
        "customer_name": package["customer_name"],
        "service_profile": cgnat_transport.get("service_profile"),
        "outer_topology": cgnat_transport.get("outer_topology"),
        "outer_gateway_ref": cgnat_transport.get("outer_gateway_ref"),
        "outer_identity_ref": cgnat_transport.get("outer_identity_ref"),
        "outer_auth_ref": cgnat_transport.get("outer_auth_ref"),
        "customer_loopback_ip": cgnat_transport.get("customer_loopback_ip"),
        "known_inside_identity": cgnat_transport.get("known_inside_identity"),
        "service_reachable_subnets": list(cgnat_transport.get("service_reachable_subnets") or []),
        "transport_interface": module_transport.get("interface"),
        "transport_mark": module_transport.get("mark"),
        "transport_table": module_transport.get("table"),
        "tunnel_type": module_transport.get("tunnel_type"),
        "tunnel_key": module_transport.get("tunnel_key"),
        "tunnel_ttl": module_transport.get("tunnel_ttl"),
        "tunnel_mtu": module_transport.get("tunnel_mtu"),
        "overlay_mux_ip": overlay.get("mux_ip"),
        "overlay_router_ip": overlay.get("router_ip"),
        "peer_public_ip": peer.get("public_ip"),
        "peer_remote_id": peer.get("remote_id"),
        "local_selectors": list(selectors.get("local_subnets") or []),
        "remote_selectors": list(selectors.get("remote_subnets") or []),
        "protocols": protocols,
        "ipsec_initiation": ipsec.get("initiation") or {},
    }
    outer_transport = dict(cgnat_transport.get("outer_transport") or {})
    if outer_transport:
        transport_profile["outer_transport"] = outer_transport
    validation_intent = {
        "schema_version": 1,
        "customer_name": package["customer_name"],
        "required_transport_mode": "cgnat",
        "expected_peer_public_ip": peer.get("public_ip"),
        "expected_outer_topology": cgnat_transport.get("outer_topology"),
        "expected_outer_gateway_ref": cgnat_transport.get("outer_gateway_ref"),
        "expected_outer_identity_ref": cgnat_transport.get("outer_identity_ref"),
        "expected_outer_auth_ref": cgnat_transport.get("outer_auth_ref"),
        "expected_known_inside_identity": cgnat_transport.get("known_inside_identity"),
        "expected_service_reachable_subnets": list(cgnat_transport.get("service_reachable_subnets") or []),
    }
    activation_manifest = {
        "schema_version": 1,
        "backend": "live_cgnat_headend" if outer_transport else "staged_cgnat_headend",
        "component": "cgnat_headend",
        "customer_name": package["customer_name"],
        "apply_command_count": 1 if outer_transport else 0,
        "rollback_command_count": 1 if outer_transport else 0,
    }
    return {
        "customer_summary": customer_summary,
        "transport_profile": transport_profile,
        "validation_intent": validation_intent,
        "activation_manifest": activation_manifest,
    }


def validate_cgnat_package(package_dir: Path, pki_review_dir: Path | None = None) -> dict[str, Any]:
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

    runtime_payloads = _build_runtime_payloads(package)
    report["customer_name"] = package["customer_name"]
    profile = runtime_payloads["transport_profile"]
    report["details"]["service_profile"] = profile.get("service_profile")
    report["details"]["outer_topology"] = profile.get("outer_topology")
    report["details"]["outer_gateway_ref"] = profile.get("outer_gateway_ref")
    report["details"]["outer_identity_ref"] = profile.get("outer_identity_ref")
    report["details"]["outer_auth_ref"] = profile.get("outer_auth_ref")
    report["details"]["customer_loopback_ip"] = profile.get("customer_loopback_ip")
    report["details"]["known_inside_identity"] = profile.get("known_inside_identity")
    report["details"]["service_reachable_subnets"] = list(profile.get("service_reachable_subnets") or [])
    report["details"]["transport_interface"] = profile.get("transport_interface")
    report["details"]["transport_table"] = profile.get("transport_table")
    report["details"]["tunnel_mtu"] = profile.get("tunnel_mtu")

    if pki_review_dir is not None:
        try:
            pki_review = _validate_pki_review_dir(pki_review_dir)
            headend_manifest = _load_pki_headend_manifest(pki_review_dir, pki_review)
        except Exception as exc:
            report["errors"].append(str(exc))
        else:
            pki_customer_name = str(pki_review.get("customer_name") or "").strip()
            if pki_customer_name != package["customer_name"]:
                report["errors"].append(
                    f"CGNAT PKI review customer mismatch: {pki_customer_name or 'missing'} != {package['customer_name']}"
                )
            report["details"]["pki_review_dir"] = str(pki_review_dir.resolve())
            report["details"]["pki_mode"] = pki_review.get("mode")
            report["details"]["pki_provider"] = pki_review.get("provider")
            report["details"]["pki_material_mode"] = headend_manifest.get("material_mode")

    for relative_name, payload in {
        "customer_summary": runtime_payloads["customer_summary"],
        "transport_profile": runtime_payloads["transport_profile"],
        "validation_intent": runtime_payloads["validation_intent"],
        "activation_manifest": runtime_payloads["activation_manifest"],
    }.items():
        unresolved = _find_json_placeholders(payload)
        if unresolved:
            report["errors"].append(
                f"derived CGNAT runtime JSON has unresolved placeholders: {relative_name} -> {', '.join(unresolved)}"
            )

    if not report["details"]["service_reachable_subnets"]:
        report["warnings"].append("customer.transport.cgnat.service_reachable_subnets is empty")

    report["valid"] = not report["errors"]
    return report


def _validate_pki_review_dir(pki_review_dir: Path | None) -> dict[str, Any] | None:
    if pki_review_dir is None:
        return None
    review_path = pki_review_dir / "pki-review.json"
    if not review_path.exists():
        raise ValueError(f"CGNAT PKI review is missing pki-review.json: {review_path}")
    review = _load_json(review_path)
    if not bool(review.get("ready_for_review")):
        raise ValueError(f"CGNAT PKI review is not ready: {review_path}")
    return review


def _resolve_pki_artifact_path(
    pki_review_dir: Path,
    value: Any,
    *,
    default_relative: str,
) -> Path:
    candidates: list[Path] = []
    value_text = str(value or "").strip()
    if value_text:
        raw_path = Path(value_text)
        candidates.append(raw_path)
        if not raw_path.is_absolute():
            candidates.append((pki_review_dir / raw_path).resolve())
        if raw_path.name:
            candidates.extend(sorted(pki_review_dir.rglob(raw_path.name)))

    candidates.append((pki_review_dir / default_relative).resolve())
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[-1]


def _load_pki_headend_manifest(pki_review_dir: Path, pki_review: dict[str, Any] | None) -> dict[str, Any]:
    artifacts = dict((pki_review or {}).get("artifacts") or {})
    manifest_path = _resolve_pki_artifact_path(
        pki_review_dir,
        artifacts.get("headend_install_manifest"),
        default_relative="headend-install/headend-install-manifest.json",
    )
    if not manifest_path.exists():
        raise ValueError(f"CGNAT PKI head-end install manifest is missing: {manifest_path}")
    return _load_json(manifest_path)


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
        "customer_summary": customer_root / "customer-summary.json",
        "transport_json": customer_root / "cgnat-transport.json",
        "transport_profile": customer_root / "transport" / "transport-profile.json",
        "transport_apply_script": customer_root / "transport" / "apply-transport.sh",
        "transport_remove_script": customer_root / "transport" / "remove-transport.sh",
        "validation_intent": customer_root / "validation" / "validation-intent.json",
        "activation_manifest": customer_root / "validation" / "activation-manifest.json",
        "pki_root": customer_root / "pki",
        "pki_review": customer_root / "pki" / "pki-review.json",
        "pki_headend_root": customer_root / "pki" / "headend-install",
        "pki_headend_manifest": customer_root / "pki" / "headend-install" / "headend-install-manifest.json",
        "config_json": config_root / f"{customer_name}.json",
        "master_apply_script": customer_root / "apply-cgnat-customer.sh",
        "master_remove_script": customer_root / "remove-cgnat-customer.sh",
        "applied_stamp": customer_root / "applied.stamp",
        "state_json": customer_root / "install-state.json",
    }


def _runtime_path(cgnat_root: Path, path: Path) -> str:
    """Return the path as it should exist after activation on a real target."""
    return "/" + path.resolve().relative_to(cgnat_root.resolve()).as_posix()


def _runtime_path_exists(cgnat_root: Path, raw_path: str) -> bool:
    normalized = str(raw_path).replace("\\", "/")
    path = Path(raw_path)
    candidates = [path]
    if normalized.startswith("/"):
        candidates.append(cgnat_root.resolve() / normalized.lstrip("/"))
    elif path.is_absolute():
        try:
            candidates.append(cgnat_root.resolve() / path.relative_to("/"))
        except ValueError:
            pass
    else:
        candidates.append(cgnat_root.resolve() / path)
    return any(candidate.exists() for candidate in candidates)


def _copy_pki_material_file(
    source_value: Any,
    destination: Path,
    *,
    label: str,
    required: bool,
    search_root: Path,
) -> str:
    source_text = str(source_value or "").strip()
    if not source_text:
        if required:
            raise ValueError(f"CGNAT PKI head-end material is missing {label}")
        return ""
    source_path = Path(source_text)
    if not source_path.exists() and not source_path.is_absolute():
        repo_relative = (search_root / source_path).resolve()
        if repo_relative.exists():
            source_path = repo_relative
    if not source_path.exists() and source_path.name:
        matches = sorted(search_root.rglob(source_path.name))
        if len(matches) == 1:
            source_path = matches[0]
    if not source_path.exists():
        if required:
            raise ValueError(f"CGNAT PKI head-end material does not exist for {label}: {source_path}")
        return ""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination)
    return str(destination)


def _install_cgnat_pki_review(
    *,
    pki_review_dir: Path | None,
    layout: dict[str, Path],
) -> dict[str, Any] | None:
    pki_review = _validate_pki_review_dir(pki_review_dir)
    if pki_review is None or pki_review_dir is None:
        return None

    manifest = _load_pki_headend_manifest(pki_review_dir, pki_review)
    material_mode = str(manifest.get("material_mode") or pki_review.get("mode") or "").strip()
    requires_local_material = material_mode in {"local_generate", "provided"}

    layout["pki_root"].mkdir(parents=True, exist_ok=True)
    layout["pki_headend_root"].mkdir(parents=True, exist_ok=True)
    _write_json(layout["pki_review"], pki_review)
    _write_json(layout["pki_headend_manifest"], manifest)

    installed_files = {
        "headend_certificate": _copy_pki_material_file(
            manifest.get("certificate_path"),
            layout["pki_headend_root"] / "headend.crt",
            label="headend certificate",
            required=requires_local_material,
            search_root=pki_review_dir,
        ),
        "headend_private_key": _copy_pki_material_file(
            manifest.get("private_key_path"),
            layout["pki_headend_root"] / "headend.key",
            label="headend private key",
            required=requires_local_material,
            search_root=pki_review_dir,
        ),
        "ca_certificate": _copy_pki_material_file(
            manifest.get("ca_certificate_path"),
            layout["pki_headend_root"] / "outer-ca.crt",
            label="CA certificate",
            required=requires_local_material,
            search_root=pki_review_dir,
        ),
        "headend_private_key_passphrase": _copy_pki_material_file(
            manifest.get("private_key_passphrase_path"),
            layout["pki_headend_root"] / "headend-key.passphrase",
            label="headend private key passphrase",
            required=False,
            search_root=pki_review_dir,
        ),
    }
    return {
        "mode": pki_review.get("mode"),
        "provider": pki_review.get("provider"),
        "material_mode": material_mode,
        "pki_review": _runtime_path(layout["cgnat_root"], layout["pki_review"]),
        "headend_install_manifest": _runtime_path(layout["cgnat_root"], layout["pki_headend_manifest"]),
        "installed_files": {
            key: _runtime_path(layout["cgnat_root"], Path(value))
            for key, value in installed_files.items()
            if value
        },
        "outer_handoff": pki_review.get("outer_handoff"),
        "customer_handoff": pki_review.get("customer_handoff"),
        "gateway_handoff": pki_review.get("gateway_handoff"),
    }


def _render_transport_apply_script(layout: dict[str, Path]) -> str:
    customer_root = "/" + layout["customer_root"].relative_to(layout["cgnat_root"]).as_posix()
    config_json = "/" + layout["config_json"].relative_to(layout["cgnat_root"]).as_posix()
    transport_profile = "/" + layout["transport_profile"].relative_to(layout["cgnat_root"]).as_posix()
    validation_intent = "/" + layout["validation_intent"].relative_to(layout["cgnat_root"]).as_posix()
    return _render_shell_script(
        [
            'ROOT="${RPDB_CGNAT_ROOT:-/}"',
            'ROOT="${ROOT%/}"',
            f'CUSTOMER_ROOT="${{ROOT}}{customer_root}"',
            f'CONFIG_JSON="${{ROOT}}{config_json}"',
            f'TRANSPORT_PROFILE="${{ROOT}}{transport_profile}"',
            f'VALIDATION_INTENT="${{ROOT}}{validation_intent}"',
            'test -f "${CONFIG_JSON}"',
            'test -f "${TRANSPORT_PROFILE}"',
            'test -f "${VALIDATION_INTENT}"',
            'ACTIVATION_ENV="$(mktemp)"',
            'python3 - "${TRANSPORT_PROFILE}" "${CUSTOMER_ROOT}/pki/headend-install/headend-install-manifest.json" > "${ACTIVATION_ENV}" <<\'PY\'',
            'import json, os, re, shlex, sys',
            'profile = json.load(open(sys.argv[1], encoding="utf-8"))',
            'manifest_path = sys.argv[2]',
            'manifest = json.load(open(manifest_path, encoding="utf-8")) if os.path.exists(manifest_path) else {}',
            'outer = dict(profile.get("outer_transport") or {})',
            'topology = str(profile.get("outer_topology") or "per_customer_outer").strip()',
            'customer = str(profile.get("customer_name") or "").strip()',
            'safe_customer = re.sub(r"[^A-Za-z0-9_.-]+", "-", customer).strip("-") or "customer"',
            'def emit(name, value):',
            '    print(f"{name}={shlex.quote(str(value or \'\'))}")',
            'headend_if_id = str(outer.get("headend_if_id") or "").strip()',
            'install_swanctl = bool(outer) and topology == "per_customer_outer"',
            'emit("ACTIVATION_ENABLED", "1" if outer else "0")',
            'emit("INSTALL_SWANCTL", "1" if install_swanctl else "0")',
            'emit("OUTER_TOPOLOGY", topology)',
            'emit("CUSTOMER_NAME", customer)',
            'emit("SAFE_CUSTOMER", safe_customer)',
            'emit("CONN_NAME", f"{safe_customer}-outer")',
            'emit("CHILD_NAME", f"{safe_customer}-outer-transport")',
            'emit("HEADEND_IDENTITY_REF", manifest.get("identity_ref") or "")',
            'emit("REMOTE_IDENTITY_REF", profile.get("outer_identity_ref") or "")',
            'emit("HEADEND_UNDERLAY_INTERFACE", outer.get("headend_underlay_interface") or "")',
            'emit("HEADEND_XFRM_INTERFACE", outer.get("headend_xfrm_interface") or "")',
            'emit("HEADEND_IF_ID", headend_if_id)',
            'emit("CUSTOMER_ROUTER_PRIVATE_IP", outer.get("customer_router_private_ip") or "")',
            'emit("CUSTOMER_LOOPBACK_IP", profile.get("customer_loopback_ip") or "")',
            'emit("CERT_BASENAME", f"{safe_customer}-headend.crt")',
            'emit("KEY_BASENAME", f"{safe_customer}-headend.key")',
            'emit("CA_BASENAME", f"{safe_customer}-outer-ca.crt")',
            'PY',
            '. "${ACTIVATION_ENV}"',
            'rm -f "${ACTIVATION_ENV}"',
            'if [ "${ACTIVATION_ENABLED}" != "1" ]; then',
            '  echo "cgnat_customer_staged=${CUSTOMER_ROOT}"',
            '  echo "cgnat_transport_profile=${TRANSPORT_PROFILE}"',
            '  exit 0',
            'fi',
            'if [ -z "${HEADEND_XFRM_INTERFACE}" ]; then',
            '  echo "CGNAT activation requires outer_transport.headend_xfrm_interface" >&2',
            '  exit 1',
            'fi',
            'if ! ip link show "${HEADEND_XFRM_INTERFACE}" >/dev/null 2>&1; then',
            '  if [ -z "${HEADEND_UNDERLAY_INTERFACE}" ] || [ -z "${HEADEND_IF_ID}" ]; then',
            '    echo "CGNAT activation requires headend_underlay_interface and headend_if_id to create ${HEADEND_XFRM_INTERFACE}" >&2',
            '    exit 1',
            '  fi',
            '  ip link add "${HEADEND_XFRM_INTERFACE}" type xfrm dev "${HEADEND_UNDERLAY_INTERFACE}" if_id "${HEADEND_IF_ID}"',
            'fi',
            'ip link set "${HEADEND_XFRM_INTERFACE}" up',
            'if [ -n "${CUSTOMER_LOOPBACK_IP}" ]; then',
            '  ip route replace "${CUSTOMER_LOOPBACK_IP}/32" dev "${HEADEND_XFRM_INTERFACE}"',
            'fi',
            'if [ -n "${CUSTOMER_ROUTER_PRIVATE_IP}" ]; then',
            '  ip route replace "${CUSTOMER_ROUTER_PRIVATE_IP}/32" dev "${HEADEND_XFRM_INTERFACE}"',
            'fi',
            'if [ "${INSTALL_SWANCTL}" = "1" ]; then',
            '  for required in HEADEND_IF_ID HEADEND_IDENTITY_REF REMOTE_IDENTITY_REF; do',
            '    eval "required_value=\\${${required}}"',
            '    if [ -z "${required_value}" ]; then',
            '      echo "CGNAT swanctl activation missing ${required}" >&2',
            '      exit 1',
            '    fi',
            '  done',
            '  HEADEND_CERT_SOURCE="${CUSTOMER_ROOT}/pki/headend-install/headend.crt"',
            '  HEADEND_KEY_SOURCE="${CUSTOMER_ROOT}/pki/headend-install/headend.key"',
            '  CA_CERT_SOURCE="${CUSTOMER_ROOT}/pki/headend-install/outer-ca.crt"',
            '  test -f "${HEADEND_CERT_SOURCE}"',
            '  test -f "${HEADEND_KEY_SOURCE}"',
            '  test -f "${CA_CERT_SOURCE}"',
            '  install -d /etc/swanctl/conf.d /etc/swanctl/x509 /etc/swanctl/private /etc/swanctl/x509ca',
            '  install -m 0644 "${HEADEND_CERT_SOURCE}" "/etc/swanctl/x509/${CERT_BASENAME}"',
            '  install -m 0600 "${HEADEND_KEY_SOURCE}" "/etc/swanctl/private/${KEY_BASENAME}"',
            '  install -m 0644 "${CA_CERT_SOURCE}" "/etc/swanctl/x509ca/${CA_BASENAME}"',
            '  SWANCTL_CONF="/etc/swanctl/conf.d/${CONN_NAME}.conf"',
            '  cat > "${SWANCTL_CONF}" <<EOF',
            'connections {',
            '  ${CONN_NAME} {',
            '    version = 2',
            '    mobike = no',
            '    fragmentation = yes',
            '    proposals = aes256-sha256-modp2048',
            '    local_addrs = 0.0.0.0',
            '    remote_addrs = %any',
            '    local {',
            '      auth = pubkey',
            '      id = ${HEADEND_IDENTITY_REF}',
            '      certs = ${CERT_BASENAME}',
            '    }',
            '    remote {',
            '      auth = pubkey',
            '      id = ${REMOTE_IDENTITY_REF}',
            '    }',
            '    children {',
            '      ${CHILD_NAME} {',
            '        local_ts = 0.0.0.0/0',
            '        remote_ts = 0.0.0.0/0',
            '        if_id_in = ${HEADEND_IF_ID}',
            '        if_id_out = ${HEADEND_IF_ID}',
            '        esp_proposals = aes256-sha256-modp2048',
            '        start_action = trap',
            '        close_action = trap',
            '        dpd_action = restart',
            '        rekey_time = 0s',
            '      }',
            '    }',
            '  }',
            '}',
            '',
            'authorities {',
            '  ${CONN_NAME}-ca {',
            '    cacert = ${CA_BASENAME}',
            '  }',
            '}',
            'EOF',
            '  if command -v swanctl >/dev/null 2>&1; then',
            '    swanctl --load-all',
            '  fi',
            'fi',
            'echo "cgnat_customer_staged=${CUSTOMER_ROOT}"',
            'echo "cgnat_transport_profile=${TRANSPORT_PROFILE}"',
            'echo "cgnat_transport_activation=${OUTER_TOPOLOGY}:${HEADEND_XFRM_INTERFACE}"',
        ]
    )


def _render_transport_remove_script(layout: dict[str, Path]) -> str:
    customer_root = "/" + layout["customer_root"].relative_to(layout["cgnat_root"]).as_posix()
    applied_stamp = "/" + layout["applied_stamp"].relative_to(layout["cgnat_root"]).as_posix()
    transport_profile = "/" + layout["transport_profile"].relative_to(layout["cgnat_root"]).as_posix()
    return _render_shell_script(
        [
            'ROOT="${RPDB_CGNAT_ROOT:-/}"',
            'ROOT="${ROOT%/}"',
            f'CUSTOMER_ROOT="${{ROOT}}{customer_root}"',
            f'APPLIED_STAMP="${{ROOT}}{applied_stamp}"',
            f'TRANSPORT_PROFILE="${{ROOT}}{transport_profile}"',
            'if [ -f "${TRANSPORT_PROFILE}" ]; then',
            '  ACTIVATION_ENV="$(mktemp)"',
            '  python3 - "${TRANSPORT_PROFILE}" > "${ACTIVATION_ENV}" <<\'PY\'',
            'import json, re, shlex, sys',
            'profile = json.load(open(sys.argv[1], encoding="utf-8"))',
            'outer = dict(profile.get("outer_transport") or {})',
            'topology = str(profile.get("outer_topology") or "per_customer_outer").strip()',
            'customer = str(profile.get("customer_name") or "").strip()',
            'safe_customer = re.sub(r"[^A-Za-z0-9_.-]+", "-", customer).strip("-") or "customer"',
            'def emit(name, value):',
            '    print(f"{name}={shlex.quote(str(value or \'\'))}")',
            'emit("ACTIVATION_ENABLED", "1" if outer else "0")',
            'emit("INSTALL_SWANCTL", "1" if outer and topology == "per_customer_outer" else "0")',
            'emit("CONN_NAME", f"{safe_customer}-outer")',
            'emit("CHILD_NAME", f"{safe_customer}-outer-transport")',
            'emit("HEADEND_XFRM_INTERFACE", outer.get("headend_xfrm_interface") or "")',
            'emit("CUSTOMER_ROUTER_PRIVATE_IP", outer.get("customer_router_private_ip") or "")',
            'emit("CUSTOMER_LOOPBACK_IP", profile.get("customer_loopback_ip") or "")',
            'emit("CERT_BASENAME", f"{safe_customer}-headend.crt")',
            'emit("KEY_BASENAME", f"{safe_customer}-headend.key")',
            'emit("CA_BASENAME", f"{safe_customer}-outer-ca.crt")',
            'PY',
            '  . "${ACTIVATION_ENV}"',
            '  rm -f "${ACTIVATION_ENV}"',
            '  if [ "${ACTIVATION_ENABLED}" = "1" ] && [ -n "${HEADEND_XFRM_INTERFACE}" ]; then',
            '    if [ -n "${CUSTOMER_LOOPBACK_IP}" ]; then',
            '      ip route del "${CUSTOMER_LOOPBACK_IP}/32" dev "${HEADEND_XFRM_INTERFACE}" 2>/dev/null || true',
            '    fi',
            '    if [ -n "${CUSTOMER_ROUTER_PRIVATE_IP}" ]; then',
            '      ip route del "${CUSTOMER_ROUTER_PRIVATE_IP}/32" dev "${HEADEND_XFRM_INTERFACE}" 2>/dev/null || true',
            '    fi',
            '    if [ "${INSTALL_SWANCTL}" = "1" ]; then',
            '      if command -v swanctl >/dev/null 2>&1; then',
            '        swanctl --terminate --child "${CHILD_NAME}" --force --timeout 10 2>/dev/null || true',
            '        swanctl --terminate --ike "${CONN_NAME}" --force --timeout 10 2>/dev/null || true',
            '      fi',
            '      rm -f "/etc/swanctl/conf.d/${CONN_NAME}.conf"',
            '      rm -f "/etc/swanctl/x509/${CERT_BASENAME}"',
            '      rm -f "/etc/swanctl/private/${KEY_BASENAME}"',
            '      rm -f "/etc/swanctl/x509ca/${CA_BASENAME}"',
            '      if command -v swanctl >/dev/null 2>&1; then',
            '        swanctl --load-all || true',
            '      fi',
            '      ip link del "${HEADEND_XFRM_INTERFACE}" 2>/dev/null || true',
            '    fi',
            '  fi',
            'fi',
            'rm -f "${APPLIED_STAMP}"',
            'echo "cgnat_customer_removed=${CUSTOMER_ROOT}"',
        ]
    )


def _render_master_apply_script(layout: dict[str, Path]) -> str:
    customer_root = "/" + layout["customer_root"].relative_to(layout["cgnat_root"]).as_posix()
    applied_stamp = "/" + layout["applied_stamp"].relative_to(layout["cgnat_root"]).as_posix()
    return _render_shell_script(
        [
            'ROOT="${RPDB_CGNAT_ROOT:-/}"',
            'ROOT="${ROOT%/}"',
            f'CUSTOMER_ROOT="${{ROOT}}{customer_root}"',
            f'APPLIED_STAMP="${{ROOT}}{applied_stamp}"',
            'test -f "${CUSTOMER_ROOT}/customer-source.yaml"',
            'test -f "${CUSTOMER_ROOT}/customer-module.json"',
            'test -f "${CUSTOMER_ROOT}/cgnat-transport.json"',
            'test -f "${CUSTOMER_ROOT}/transport/transport-profile.json"',
            'bash "${CUSTOMER_ROOT}/transport/apply-transport.sh"',
            'date -u +%Y-%m-%dT%H:%M:%SZ > "${APPLIED_STAMP}"',
        ]
    )


def _render_master_remove_script(layout: dict[str, Path]) -> str:
    customer_root = "/" + layout["customer_root"].relative_to(layout["cgnat_root"]).as_posix()
    config_json = "/" + layout["config_json"].relative_to(layout["cgnat_root"]).as_posix()
    applied_stamp = "/" + layout["applied_stamp"].relative_to(layout["cgnat_root"]).as_posix()
    return _render_shell_script(
        [
            'ROOT="${RPDB_CGNAT_ROOT:-/}"',
            'ROOT="${ROOT%/}"',
            f'CUSTOMER_ROOT="${{ROOT}}{customer_root}"',
            f'CONFIG_JSON="${{ROOT}}{config_json}"',
            f'APPLIED_STAMP="${{ROOT}}{applied_stamp}"',
            'bash "${CUSTOMER_ROOT}/transport/remove-transport.sh"',
            'rm -f "${APPLIED_STAMP}"',
            'rm -f "${CONFIG_JSON}"',
            'rm -rf "${CUSTOMER_ROOT}"',
        ]
    )


def install_cgnat_package(package_dir: Path, cgnat_root: Path, pki_review_dir: Path | None = None) -> dict[str, Any]:
    validation = validate_cgnat_package(package_dir, pki_review_dir=pki_review_dir)
    if not validation["valid"]:
        raise ValueError("CGNAT package is not installable: " + "; ".join(validation["errors"]))

    package = load_cgnat_package(package_dir)
    runtime_payloads = _build_runtime_payloads(package)
    layout = build_install_layout(cgnat_root, package["customer_name"])
    if layout["artifacts_root"].exists():
        shutil.rmtree(layout["artifacts_root"])
    if layout["pki_root"].exists():
        shutil.rmtree(layout["pki_root"])
    layout["artifacts_root"].mkdir(parents=True, exist_ok=True)
    layout["config_json"].parent.mkdir(parents=True, exist_ok=True)

    shutil.copy2(package["source_path"], layout["customer_source"])
    shutil.copy2(package["module_path"], layout["customer_module"])
    shutil.copy2(package["source_path"], layout["artifacts_root"] / "customer-source.yaml")
    shutil.copy2(package["module_path"], layout["artifacts_root"] / "customer-module.json")
    _write_json(layout["customer_summary"], runtime_payloads["customer_summary"])
    _write_json(layout["transport_json"], package["cgnat_transport"])
    _write_json(layout["transport_profile"], runtime_payloads["transport_profile"])
    _write_json(layout["validation_intent"], runtime_payloads["validation_intent"])
    _write_json(layout["activation_manifest"], runtime_payloads["activation_manifest"])
    _write_json(layout["config_json"], runtime_payloads["transport_profile"])
    _write_text(layout["transport_apply_script"], _render_transport_apply_script(layout))
    _write_text(layout["transport_remove_script"], _render_transport_remove_script(layout))
    _write_text(layout["master_apply_script"], _render_master_apply_script(layout))
    _write_text(layout["master_remove_script"], _render_master_remove_script(layout))
    pki_install = _install_cgnat_pki_review(
        pki_review_dir=pki_review_dir,
        layout=layout,
    )
    for key in (
        "transport_apply_script",
        "transport_remove_script",
        "master_apply_script",
        "master_remove_script",
    ):
        _make_executable(layout[key])

    state = {
        "schema_version": 1,
        "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "customer_name": package["customer_name"],
        "package_dir": str(package["package_dir"]),
        "transport": package["cgnat_transport"],
        "transport_profile": runtime_payloads["transport_profile"],
        "pki_install": pki_install,
        "paths": {name: str(path) for name, path in layout.items()},
    }
    _write_json(layout["state_json"], state)

    return {
        "customer_name": package["customer_name"],
        "cgnat_root": str(layout["cgnat_root"]),
        "installed": True,
        "state_json": str(layout["state_json"]),
        "config_json": str(layout["config_json"]),
        "customer_summary": str(layout["customer_summary"]),
        "transport_json": str(layout["transport_json"]),
        "transport_profile": str(layout["transport_profile"]),
        "validation_intent": str(layout["validation_intent"]),
        "activation_manifest": str(layout["activation_manifest"]),
        "pki_install": pki_install,
        "transport_apply_script": str(layout["transport_apply_script"]),
        "transport_remove_script": str(layout["transport_remove_script"]),
        "master_apply_script": str(layout["master_apply_script"]),
        "master_remove_script": str(layout["master_remove_script"]),
    }


def validate_installed_cgnat(package_dir: Path, cgnat_root: Path, pki_review_dir: Path | None = None) -> dict[str, Any]:
    report = validate_cgnat_package(package_dir, pki_review_dir=pki_review_dir)
    if not report["valid"]:
        return report

    package = load_cgnat_package(package_dir)
    runtime_payloads = _build_runtime_payloads(package)
    layout = build_install_layout(cgnat_root, package["customer_name"])
    for key in (
        "customer_source",
        "customer_module",
        "customer_summary",
        "transport_json",
        "transport_profile",
        "validation_intent",
        "activation_manifest",
        "config_json",
        "transport_apply_script",
        "transport_remove_script",
        "master_apply_script",
        "master_remove_script",
        "state_json",
    ):
        if not layout[key].exists():
            report["errors"].append(f"installed path missing: {layout[key]}")

    if layout["customer_source"].exists():
        installed_source = layout["customer_source"].read_text(encoding="utf-8")
        if installed_source != str(package["source_text"]):
            report["errors"].append(f"installed source does not match package: {layout['customer_source']}")

    json_checks = {
        "customer_summary": runtime_payloads["customer_summary"],
        "transport_json": package["cgnat_transport"],
        "transport_profile": runtime_payloads["transport_profile"],
        "validation_intent": runtime_payloads["validation_intent"],
        "activation_manifest": runtime_payloads["activation_manifest"],
        "config_json": runtime_payloads["transport_profile"],
    }
    for layout_key, expected_payload in json_checks.items():
        if layout[layout_key].exists():
            installed_payload = _load_json(layout[layout_key])
            if installed_payload != expected_payload:
                report["errors"].append(f"installed CGNAT JSON does not match expected payload: {layout[layout_key]}")

    text_checks = {
        "transport_apply_script": _render_transport_apply_script(layout),
        "transport_remove_script": _render_transport_remove_script(layout),
        "master_apply_script": _render_master_apply_script(layout),
        "master_remove_script": _render_master_remove_script(layout),
    }
    for layout_key, expected_text in text_checks.items():
        if layout[layout_key].exists():
            installed_text = layout[layout_key].read_text(encoding="utf-8")
            if installed_text != expected_text:
                report["errors"].append(
                    f"installed CGNAT script does not match expected payload: {layout[layout_key]}"
                )

    if layout["state_json"].exists():
        state = _load_json(layout["state_json"])
        report["details"]["install_state"] = state
        if state.get("customer_name") != package["customer_name"]:
            report["errors"].append(f"install-state customer mismatch in {layout['state_json']}")
        pki_install = state.get("pki_install")
        if isinstance(pki_install, dict):
            for label, installed_path in dict(pki_install.get("installed_files") or {}).items():
                if installed_path and not _runtime_path_exists(cgnat_root, str(installed_path)):
                    report["errors"].append(f"installed CGNAT PKI file missing for {label}: {installed_path}")
            for required_path in (layout["pki_review"], layout["pki_headend_manifest"]):
                if not required_path.exists():
                    report["errors"].append(f"installed CGNAT PKI path missing: {required_path}")

    report["details"]["installed_root"] = str(layout["customer_root"])
    report["details"]["installed_config"] = str(layout["config_json"])
    report["details"]["installed_transport_profile"] = str(layout["transport_profile"])
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
