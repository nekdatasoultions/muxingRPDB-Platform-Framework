"""Helpers for binding rendered artifacts to environment-specific values."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from .customer_merge import load_yaml_file

PLACEHOLDER_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")
TEXT_SUFFIXES = {".txt", ".conf", ".json", ".yaml", ".yml", ".md"}


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_environment_bindings(path: str | Path) -> Dict[str, Any]:
    return load_yaml_file(path)


def _stringify_bindings(mapping: Dict[str, Any]) -> Dict[str, str]:
    return {key: str(value) for key, value in mapping.items()}


def _resolve_backend_bindings(environment_doc: Dict[str, Any], customer_module: Dict[str, Any]) -> Dict[str, str]:
    environment = environment_doc.get("environment") or {}
    resolver = environment.get("backend_resolver") or {}
    backend = (customer_module.get("backend") or {}) if customer_module else {}

    role = str(backend.get("role") or "").strip()
    cluster = str(backend.get("cluster") or "").strip()
    assignment = str(backend.get("assignment") or "").strip()

    resolved: Dict[str, str] = {}

    role_bindings = (resolver.get("roles") or {}).get(role)
    if isinstance(role_bindings, dict):
        resolved.update(_stringify_bindings(role_bindings))

    cluster_doc = (resolver.get("clusters") or {}).get(cluster)
    if isinstance(cluster_doc, dict):
        assignment_bindings = cluster_doc.get(assignment)
        if isinstance(assignment_bindings, dict):
            resolved.update(_stringify_bindings(assignment_bindings))

    return resolved


def build_binding_context(environment_doc: Dict[str, Any], customer_module: Dict[str, Any] | None = None) -> Dict[str, str]:
    bindings = _stringify_bindings(((environment_doc.get("environment") or {}).get("bindings") or {}))

    module = customer_module or {}
    customer = module.get("customer") or {}
    peer = module.get("peer") or {}
    backend = module.get("backend") or {}
    transport = module.get("transport") or {}

    bindings.update(_resolve_backend_bindings(environment_doc, module))

    derived = {
        "CUSTOMER_NAME": customer.get("name"),
        "CUSTOMER_ID": customer.get("id"),
        "CUSTOMER_CLASS": customer.get("customer_class"),
        "PEER_PUBLIC_IP": peer.get("public_ip"),
        "PEER_REMOTE_ID": peer.get("remote_id"),
        "BACKEND_CLUSTER": backend.get("cluster"),
        "BACKEND_ASSIGNMENT": backend.get("assignment"),
        "BACKEND_ROLE": backend.get("role"),
        "BACKEND_UNDERLAY_IP": backend.get("underlay_ip"),
        "CUSTOMER_FWMARK": transport.get("mark"),
        "CUSTOMER_ROUTE_TABLE": transport.get("table"),
        "CUSTOMER_RPDB_PRIORITY": transport.get("rpdb_priority"),
    }
    for key, value in derived.items():
        if key not in bindings and value not in (None, ""):
            bindings[key] = str(value)
    return bindings


def replace_placeholders(text: str, bindings: Dict[str, str]) -> Tuple[str, list[str]]:
    missing: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in bindings:
            return bindings[name]
        missing.append(name)
        return match.group(0)

    return PLACEHOLDER_PATTERN.sub(_replace, text), sorted(set(missing))


def find_unresolved_placeholders(text: str) -> list[str]:
    return sorted(set(match.group(1) for match in PLACEHOLDER_PATTERN.finditer(text)))


def iter_text_files(root_dir: Path) -> Iterable[Path]:
    for path in sorted(root_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            yield path


def load_optional_customer_module(input_dir: Path, explicit_module_path: str | Path | None = None) -> Dict[str, Any] | None:
    candidate = Path(explicit_module_path).resolve() if explicit_module_path else None
    if candidate is None:
        root_candidate = input_dir / "customer-module.json"
        nested_candidate = input_dir / "customer" / "customer-module.json"
        if root_candidate.exists():
            candidate = root_candidate
        elif nested_candidate.exists():
            candidate = nested_candidate
    if candidate and candidate.exists():
        return _load_json(candidate)
    return None
