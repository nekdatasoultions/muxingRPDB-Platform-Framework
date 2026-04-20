#!/usr/bin/env python3
"""Customer module loader for the RPDB runtime, with explicit legacy fallbacks."""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Any, Dict, List

from .core import BASE, CFG_DIR, load_yaml
from .customers import calc_overlay, customer_protocol_flags
from .dynamodb_sot import (
    customer_sot_settings,
    load_customer_module_from_dynamodb,
    load_customer_modules_from_dynamodb,
    normalize_customer_module,
    normalize_customer_sot_backend,
)

CUSTOMER_MODULES_DIR = BASE / "config" / "customer-modules"
LEGACY_CUSTOMERS_VARS = BASE / "config" / "customers.variables.yaml"


def _merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged.get(key, {}), value)
        else:
            merged[key] = value
    return merged


def _load_json_or_yaml(path: Path) -> Dict[str, Any]:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return load_yaml(path) or {}


def _iter_customer_module_paths(customer_modules_dir: Path) -> List[Path]:
    if not customer_modules_dir.exists():
        return []

    candidates: Dict[str, Path] = {}
    for pattern in ("*.json", "*.yaml", "*.yml"):
        for path in sorted(customer_modules_dir.glob(pattern)):
            if not path.is_file():
                continue
            lowered = path.name.lower()
            if lowered in {"readme.md", "readme.txt"}:
                continue
            if lowered.startswith(("customer-ddb-item", "export-metadata", "binding-report")):
                continue
            candidates[str(path.resolve())] = path

    for pattern in ("*/customer-module.json", "*/customer-module.yaml", "*/customer-module.yml"):
        for path in sorted(customer_modules_dir.glob(pattern)):
            if path.is_file():
                candidates[str(path.resolve())] = path

    return [candidates[key] for key in sorted(candidates)]


def load_customer_modules_from_directory(customer_modules_dir: Path) -> List[Dict[str, Any]]:
    modules: List[Dict[str, Any]] = []
    for path in _iter_customer_module_paths(customer_modules_dir):
        module = normalize_customer_module(_load_json_or_yaml(path))
        if not {"id", "name", "peer_ip"}.issubset(module):
            continue
        modules.append(module)
    modules.sort(key=lambda item: int(item["id"]))
    return modules


def select_customer_module(modules: List[Dict[str, Any]], selector: str) -> Dict[str, Any]:
    raw = str(selector).strip()
    if not raw:
        raise SystemExit("Customer selector cannot be empty")

    by_name = [module for module in modules if str(module.get("name", "")).strip() == raw]
    if len(by_name) == 1:
        return by_name[0]

    if raw.isdigit():
        by_id = [module for module in modules if int(module.get("id", -1)) == int(raw)]
        if len(by_id) == 1:
            return by_id[0]

    raw_ip = raw.split("/")[0]
    by_peer = [module for module in modules if str(module.get("peer_ip", "")).split("/")[0] == raw_ip]
    if len(by_peer) == 1:
        return by_peer[0]

    lowered = raw.lower()
    partial = [module for module in modules if lowered in str(module.get("name", "")).lower()]
    if len(partial) == 1:
        return partial[0]

    names = ", ".join(str(module.get("name")) for module in modules)
    raise SystemExit(f"Unable to uniquely resolve customer '{selector}'. Known customers: {names}")


def _default_tunnel_ifname(cust_id: int, tunnel_type: str) -> str:
    if tunnel_type == "gre":
        return f"gre-cust-{cust_id:04d}"
    return f"ipip-cust-{cust_id:04d}"


def _peer_cidr(value: str) -> str:
    raw = str(value).strip()
    if "/" not in raw:
        raw = f"{raw}/32"
    ipaddress.ip_network(raw, strict=False)
    return raw


def backend_role_catalog(muxer_doc: Dict[str, Any]) -> Dict[str, Any]:
    return muxer_doc.get("backend_roles", {}) or {}


def _coerce_backend_ip(value: Any, context: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise SystemExit(f"{context}: backend underlay IP is empty")
    ipaddress.ip_address(raw)
    return raw


def _append_egress_source(sources: List[str], value: Any, context: str) -> None:
    raw = str(value or "").strip()
    if not raw or raw == "%defaultroute":
        return
    try:
        normalized = str(ipaddress.ip_address(raw))
    except ValueError as exc:
        raise SystemExit(f"{context}: invalid egress source IP {raw!r}") from exc
    if normalized not in sources:
        sources.append(normalized)


def _append_egress_sources(sources: List[str], values: Any, context: str) -> None:
    if values in (None, ""):
        return
    if isinstance(values, str):
        values = [item.strip() for item in values.split(",") if item.strip()]
    if not isinstance(values, list):
        raise SystemExit(f"{context}: egress sources must be a list or comma-separated string")
    for idx, value in enumerate(values):
        _append_egress_source(sources, value, f"{context}[{idx}]")


def resolve_backend_role_egress_sources(role_name: str, muxer_doc: Dict[str, Any], *, preferred_az: str = "") -> List[str]:
    role = str(role_name or "").strip()
    if not role:
        return []

    catalog = backend_role_catalog(muxer_doc)
    role_doc = catalog.get(role)
    if not isinstance(role_doc, dict):
        return []

    sources: List[str] = []
    _append_egress_sources(sources, role_doc.get("egress_source_ips"), f"backend_roles.{role}.egress_source_ips")
    _append_egress_sources(sources, role_doc.get("egress_sources"), f"backend_roles.{role}.egress_sources")
    _append_egress_sources(sources, role_doc.get("source_aliases"), f"backend_roles.{role}.source_aliases")

    ip_by_az = role_doc.get("ip_by_az") or role_doc.get("az_map") or {}
    active_az = str(role_doc.get("active_az") or preferred_az or "").strip()
    if active_az and isinstance(ip_by_az, dict):
        az_entry = ip_by_az.get(active_az)
        if isinstance(az_entry, dict):
            _append_egress_sources(
                sources,
                az_entry.get("egress_source_ips"),
                f"backend_roles.{role}.ip_by_az.{active_az}.egress_source_ips",
            )
            _append_egress_sources(
                sources,
                az_entry.get("egress_sources"),
                f"backend_roles.{role}.ip_by_az.{active_az}.egress_sources",
            )
            _append_egress_sources(
                sources,
                az_entry.get("source_aliases"),
                f"backend_roles.{role}.ip_by_az.{active_az}.source_aliases",
            )
    return sources


def resolve_backend_role(role_name: str, muxer_doc: Dict[str, Any], *, preferred_az: str = "") -> str:
    role = str(role_name or "").strip()
    if not role:
        return ""

    catalog = backend_role_catalog(muxer_doc)
    role_doc = catalog.get(role)
    if role_doc is None:
        known = ", ".join(sorted(str(name) for name in catalog)) or "(none)"
        raise SystemExit(f"Unknown backend_role '{role}'. Known roles: {known}")

    if isinstance(role_doc, str):
        return _coerce_backend_ip(role_doc, f"backend_roles.{role}")

    if not isinstance(role_doc, dict):
        raise SystemExit(f"backend_roles.{role}: expected mapping or IPv4 string")

    ip_by_az = role_doc.get("ip_by_az") or role_doc.get("az_map") or {}
    active_az = str(role_doc.get("active_az") or preferred_az or "").strip()
    if active_az and isinstance(ip_by_az, dict):
        az_entry = ip_by_az.get(active_az)
        if isinstance(az_entry, dict):
            candidate = az_entry.get("underlay_ip") or az_entry.get("backend_underlay_ip") or az_entry.get("ip")
        else:
            candidate = az_entry
        if str(candidate or "").strip():
            return _coerce_backend_ip(candidate, f"backend_roles.{role}.ip_by_az.{active_az}")

    direct = (
        role_doc.get("underlay_ip")
        or role_doc.get("backend_underlay_ip")
        or role_doc.get("ip")
        or ""
    )
    if str(direct or "").strip():
        return _coerce_backend_ip(direct, f"backend_roles.{role}")

    if isinstance(ip_by_az, dict) and len(ip_by_az) == 1:
        only_az, only_entry = next(iter(ip_by_az.items()))
        if isinstance(only_entry, dict):
            only_entry = only_entry.get("underlay_ip") or only_entry.get("backend_underlay_ip") or only_entry.get("ip")
        return _coerce_backend_ip(only_entry, f"backend_roles.{role}.ip_by_az.{only_az}")

    raise SystemExit(
        f"backend_roles.{role}: no usable underlay IP found. Define underlay_ip directly or set "
        "active_az plus ip_by_az."
    )


def resolve_backend_identity(module: Dict[str, Any], muxer_doc: Dict[str, Any]) -> Dict[str, Any]:
    resolved = dict(module)
    backend_role = str(resolved.get("backend_role") or "").strip()
    preferred_az = str(resolved.get("backend_role_az") or "").strip()

    if backend_role:
        resolved["backend_underlay_ip"] = resolve_backend_role(backend_role, muxer_doc, preferred_az=preferred_az)
    elif "backend_underlay_ip" in resolved:
        resolved["backend_underlay_ip"] = _coerce_backend_ip(
            resolved.get("backend_underlay_ip"),
            f"{resolved.get('name', 'customer')}.backend_underlay_ip",
        )

    egress_sources: List[str] = []
    _append_egress_sources(
        egress_sources,
        resolved.get("headend_egress_sources") or resolved.get("headend_egress_source_ips"),
        f"{resolved.get('name', 'customer')}.headend_egress_sources",
    )
    original_backend = ((resolved.get("_rpdb_original") or {}).get("backend") or {})
    _append_egress_sources(
        egress_sources,
        original_backend.get("egress_source_ips"),
        f"{resolved.get('name', 'customer')}._rpdb_original.backend.egress_source_ips",
    )
    if backend_role:
        for source_ip in resolve_backend_role_egress_sources(
            backend_role,
            muxer_doc,
            preferred_az=preferred_az,
        ):
            _append_egress_source(
                egress_sources,
                source_ip,
                f"backend_roles.{backend_role}.egress_source_ips",
            )
    if egress_sources:
        resolved["headend_egress_sources"] = egress_sources

    return resolved


def resolve_backend_identities(modules: List[Dict[str, Any]], muxer_doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [resolve_backend_identity(module, muxer_doc) for module in modules]


def strict_non_nat_customer(module: Dict[str, Any]) -> bool:
    udp500, udp4500, esp50, _force = customer_protocol_flags(module)
    return udp500 and not udp4500 and esp50


def public_edge_mode(muxer_doc: Dict[str, Any]) -> str:
    public_edge = muxer_doc.get("public_edge", {}) or {}
    return str(public_edge.get("mode") or "aws_eip_association").strip()


def strict_non_nat_edge_supported(muxer_doc: Dict[str, Any]) -> bool:
    public_edge = muxer_doc.get("public_edge", {}) or {}
    if "strict_non_nat_supported" in public_edge:
        return bool(public_edge.get("strict_non_nat_supported"))

    mode = public_edge_mode(muxer_doc)
    return mode in {"igw_ingress_byoip", "native_public_l3"}


def validate_public_edge_compatibility(
    module: Dict[str, Any],
    muxer_doc: Dict[str, Any],
    *,
    allow_incompatible: bool = False,
) -> None:
    if not strict_non_nat_customer(module):
        return

    if strict_non_nat_edge_supported(muxer_doc) or allow_incompatible:
        return

    name = str(module.get("name", "unknown"))
    mode = public_edge_mode(muxer_doc)
    raise SystemExit(
        f"{name}: strict non-NAT customers are not deployable on muxer public_edge.mode="
        f"{mode}. The current edge still presents NAT-like behavior to peers. "
        "Use a strict-compatible ingress mode such as igw_ingress_byoip, reclassify the "
        "customer as NAT-T, or pass an explicit lab override if you are only reproducing the "
        "failure."
    )


def validate_customer_module(module: Dict[str, Any]) -> None:
    if not strict_non_nat_customer(module):
        return

    name = str(module.get("name", "unknown"))
    ipsec_cfg = module.get("ipsec", {}) or {}
    left_public = str(ipsec_cfg.get("left_public") or "").strip()
    local_id = str(ipsec_cfg.get("local_id") or "").strip()

    if not left_public or left_public == "%defaultroute":
        raise SystemExit(
            f"{name}: strict non-NAT customers must declare ipsec.left_public so the "
            "head-end terminates IKE as the shared public VPN identity"
        )

    ipaddress.ip_address(left_public)

    if local_id and local_id != left_public:
        raise SystemExit(
            f"{name}: strict non-NAT customers must keep ipsec.local_id aligned with "
            f"ipsec.left_public ({left_public})"
        )


def build_modules_from_variables(
    vars_doc: Dict[str, Any],
    overlay_pool: ipaddress.IPv4Network | None,
    muxer_doc: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    defaults = vars_doc.get("defaults", {}) or {}
    default_muxer = defaults.get("muxer", {}) or {}
    default_protocols = defaults.get("protocols", {}) or {}
    default_natd = defaults.get("natd_rewrite", {}) or {}
    default_ipsec = defaults.get("ipsec", {}) or {}
    default_post_ipsec_nat = defaults.get("post_ipsec_nat", {}) or {}
    customers = vars_doc.get("customers", []) or []

    modules: List[Dict[str, Any]] = []
    for customer in customers:
        if not isinstance(customer, dict):
            raise SystemExit("legacy customers.variables.yaml: each customer entry must be a mapping")

        if "id" not in customer or "name" not in customer or "peer_ip" not in customer:
            raise SystemExit("legacy customers.variables.yaml: each customer requires id, name, and peer_ip")

        cust_id = int(customer["id"])
        name = str(customer["name"]).strip()
        peer_ip = _peer_cidr(str(customer["peer_ip"]))

        module: Dict[str, Any] = {
            "id": cust_id,
            "name": name,
            "peer_ip": peer_ip,
        }

        protocols = _merge_dict(default_protocols, customer.get("protocols", {}) or {})
        module["protocols"] = protocols

        natd_rewrite = _merge_dict(default_natd, customer.get("natd_rewrite", {}) or {})
        if natd_rewrite:
            module["natd_rewrite"] = natd_rewrite

        ipsec_cfg = _merge_dict(default_ipsec, customer.get("ipsec", {}) or {})
        if ipsec_cfg:
            ipsec_cfg.setdefault("remote_id", peer_ip.split("/")[0])
            module["ipsec"] = ipsec_cfg

        post_ipsec_nat_cfg = _merge_dict(default_post_ipsec_nat, customer.get("post_ipsec_nat", {}) or {})
        if post_ipsec_nat_cfg:
            module["post_ipsec_nat"] = post_ipsec_nat_cfg

        if "mark" in customer:
            module["mark"] = customer["mark"]
        if "table" in customer:
            module["table"] = customer["table"]

        tunnel_type = str(customer.get("tunnel_type", default_muxer.get("tunnel_type", "ipip"))).strip().lower()
        module["tunnel_type"] = tunnel_type

        if "tunnel_ttl" in customer:
            module["tunnel_ttl"] = customer["tunnel_ttl"]
        elif "tunnel_ttl" in default_muxer:
            module["tunnel_ttl"] = default_muxer["tunnel_ttl"]

        if "inside_ip" in customer:
            module["inside_ip"] = customer["inside_ip"]
        elif "inside_ip" in default_muxer:
            module["inside_ip"] = default_muxer["inside_ip"]

        if "backend_role" in customer:
            module["backend_role"] = customer["backend_role"]
        elif "backend_role" in default_muxer:
            module["backend_role"] = default_muxer["backend_role"]

        if "backend_role_az" in customer:
            module["backend_role_az"] = customer["backend_role_az"]
        elif "backend_role_az" in default_muxer:
            module["backend_role_az"] = default_muxer["backend_role_az"]

        if "backend_underlay_ip" in customer:
            module["backend_underlay_ip"] = customer["backend_underlay_ip"]
        elif "backend_underlay_ip" in default_muxer:
            module["backend_underlay_ip"] = default_muxer["backend_underlay_ip"]

        if "ipip_ifname" in customer:
            module["ipip_ifname"] = customer["ipip_ifname"]
        else:
            module["ipip_ifname"] = _default_tunnel_ifname(cust_id, tunnel_type)

        if "tunnel_key" in customer:
            module["tunnel_key"] = customer["tunnel_key"]
        elif "tunnel_key" in default_muxer:
            module["tunnel_key"] = default_muxer["tunnel_key"]
        elif tunnel_type == "gre":
            module["tunnel_key"] = 1000 + cust_id

        if customer.get("overlay"):
            module["overlay"] = customer["overlay"]
        elif overlay_pool is not None:
            mux_ip, router_ip = calc_overlay(overlay_pool, cust_id)
            module["overlay"] = {"mux_ip": mux_ip, "router_ip": router_ip}

        validate_customer_module(module)
        modules.append(module)

    modules.sort(key=lambda item: int(item["id"]))
    if muxer_doc:
        return resolve_backend_identities(modules, muxer_doc)
    return modules


def load_modules(
    overlay_pool: ipaddress.IPv4Network | None,
    cfg_dir: Path = CFG_DIR,
    customer_modules_dir: Path = CUSTOMER_MODULES_DIR,
    customers_vars_path: Path = LEGACY_CUSTOMERS_VARS,
    global_cfg: Dict[str, Any] | None = None,
    source_backend: str = "auto",
) -> List[Dict[str, Any]]:
    raw_backend = str(source_backend or "auto").strip().lower()
    if raw_backend == "auto" and global_cfg:
        chosen_backend, table_name, region = customer_sot_settings(global_cfg)
    elif raw_backend == "auto":
        table_name = ""
        region = ""
        if _iter_customer_module_paths(customer_modules_dir):
            chosen_backend = "customer_modules"
        elif sorted(cfg_dir.glob("*.y*ml")):
            chosen_backend = "legacy_tunnels"
        elif customers_vars_path.exists():
            chosen_backend = "legacy_variables"
        else:
            chosen_backend = "customer_modules"
    elif global_cfg:
        _backend, table_name, region = customer_sot_settings(global_cfg)
        chosen_backend = normalize_customer_sot_backend(raw_backend, default="customer_modules")
    else:
        chosen_backend = normalize_customer_sot_backend(raw_backend, default="customer_modules")
        table_name = ""
        region = ""

    if chosen_backend in {"dynamodb", "dynamodb_inventory"}:
        modules = load_customer_modules_from_dynamodb(table_name=table_name, region=region or None)
        if global_cfg:
            return resolve_backend_identities(modules, global_cfg)
        return modules

    if chosen_backend == "customer_modules":
        modules = load_customer_modules_from_directory(customer_modules_dir)
        if global_cfg:
            return resolve_backend_identities(modules, global_cfg)
        return modules

    if chosen_backend == "legacy_variables":
        if not customers_vars_path.exists():
            raise SystemExit(f"Legacy variables backend selected but file is missing: {customers_vars_path}")
        vars_doc = load_yaml(customers_vars_path) or {}
        return build_modules_from_variables(vars_doc, overlay_pool, global_cfg)

    if chosen_backend == "legacy_tunnels":
        modules: List[Dict[str, Any]] = []
        for path in sorted(cfg_dir.glob("*.y*ml")):
            data = load_yaml(path) or {}
            data["_path"] = str(path)
            modules.append(data)
        if global_cfg:
            return resolve_backend_identities(modules, global_cfg)
        return modules

    raise SystemExit(
        "Unsupported customer source backend "
        f"'{chosen_backend}'. Use one of: dynamodb, dynamodb_inventory, customer_modules, legacy_variables, legacy_tunnels."
    )


def load_module(
    selector: str,
    overlay_pool: ipaddress.IPv4Network | None,
    cfg_dir: Path = CFG_DIR,
    customer_modules_dir: Path = CUSTOMER_MODULES_DIR,
    customers_vars_path: Path = LEGACY_CUSTOMERS_VARS,
    global_cfg: Dict[str, Any] | None = None,
    source_backend: str = "auto",
    allow_scan_fallback: bool = True,
) -> Dict[str, Any]:
    raw_backend = str(source_backend or "auto").strip().lower()
    if raw_backend == "auto" and global_cfg:
        chosen_backend, table_name, region = customer_sot_settings(global_cfg)
    elif raw_backend == "auto":
        table_name = ""
        region = ""
        if _iter_customer_module_paths(customer_modules_dir):
            chosen_backend = "customer_modules"
        elif sorted(cfg_dir.glob("*.y*ml")):
            chosen_backend = "legacy_tunnels"
        elif customers_vars_path.exists():
            chosen_backend = "legacy_variables"
        else:
            chosen_backend = "customer_modules"
    elif global_cfg:
        _backend, table_name, region = customer_sot_settings(global_cfg)
        chosen_backend = normalize_customer_sot_backend(raw_backend, default="customer_modules")
    else:
        chosen_backend = normalize_customer_sot_backend(raw_backend, default="customer_modules")
        table_name = ""
        region = ""

    if chosen_backend in {"dynamodb", "dynamodb_inventory"}:
        module = load_customer_module_from_dynamodb(table_name=table_name, customer_name=selector, region=region or None)
        if module is not None:
            if global_cfg:
                return resolve_backend_identity(module, global_cfg)
            return module
        if not allow_scan_fallback:
            raise SystemExit(
                f"Customer '{selector}' was not found in DynamoDB table {table_name}; "
                "fleet scan fallback is disabled for customer-scoped operations"
            )

    modules = load_modules(
        overlay_pool,
        cfg_dir=cfg_dir,
        customer_modules_dir=customer_modules_dir,
        customers_vars_path=customers_vars_path,
        global_cfg=global_cfg,
        source_backend=chosen_backend,
    )
    return select_customer_module(modules, selector)
