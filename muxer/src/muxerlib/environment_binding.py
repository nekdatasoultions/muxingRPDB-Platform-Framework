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


def build_binding_context(environment_doc: Dict[str, Any], customer_module: Dict[str, Any] | None = None) -> Dict[str, str]:
    bindings = {
        key: str(value)
        for key, value in ((environment_doc.get("environment") or {}).get("bindings") or {}).items()
    }

    module = customer_module or {}
    customer = module.get("customer") or {}
    peer = module.get("peer") or {}
    backend = module.get("backend") or {}
    transport = module.get("transport") or {}

    derived = {
        "CUSTOMER_NAME": customer.get("name"),
        "CUSTOMER_ID": customer.get("id"),
        "CUSTOMER_CLASS": customer.get("customer_class"),
        "PEER_PUBLIC_IP": peer.get("public_ip"),
        "PEER_REMOTE_ID": peer.get("remote_id"),
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
