"""CGNAT service-profile-specific customer-source enrichments."""

from __future__ import annotations

import copy
import json
import ipaddress
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _as_host_cidr(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "/" in text:
        return text
    return f"{text}/32"


def _normalized_cidrs(values: list[Any]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _as_host_cidr(str(value or "").strip())
        if not text:
            continue
        try:
            network = ipaddress.ip_network(text, strict=False)
        except ValueError:
            continue
        rendered = str(network)
        if rendered not in seen:
            normalized.append(rendered)
            seen.add(rendered)
    return normalized


def _profile_config_root() -> Path:
    return _repo_root() / "CGNAT" / "framework" / "config"


def _profile_integration_path(*, service_profile: str, deployment_environment: str) -> Path:
    return _profile_config_root() / f"{service_profile}-backend-integration.{deployment_environment}.json"


def _resolve_profile_integration_path(*, service_profile: str, deployment_environment: str) -> Path | None:
    direct = _profile_integration_path(
        service_profile=service_profile,
        deployment_environment=deployment_environment,
    )
    if direct.exists():
        return direct
    pattern = f"{service_profile}-backend-integration.*.json"
    for candidate in sorted(_profile_config_root().glob(pattern)):
        try:
            candidate_doc = _load_json(candidate)
        except Exception:
            continue
        aliases = [str(value).strip() for value in candidate_doc.get("environment_aliases") or [] if str(value).strip()]
        if deployment_environment in aliases:
            return candidate
    return None


def _headend_public_loopback(environment_doc: dict[str, Any]) -> str:
    environment = dict(environment_doc.get("environment") or {})
    bindings = dict(environment.get("bindings") or {})
    return str(bindings.get("HEADEND_PUBLIC_IP") or "").strip()


def _excluded_real_subnets(integration: dict[str, Any], environment_doc: dict[str, Any]) -> list[str]:
    explicit = _normalized_cidrs(list(integration.get("outside_nat_excluded_real_subnets") or []))
    if explicit:
        return explicit
    headend_public_ip = _headend_public_loopback(environment_doc or {})
    headend_public_loopback = _as_host_cidr(headend_public_ip)
    return _normalized_cidrs([headend_public_loopback] if headend_public_loopback else [])


def apply_cgnat_service_profile_overrides(
    source_doc: dict[str, Any],
    *,
    deployment_environment: str = "",
    environment_doc: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    updated = copy.deepcopy(source_doc)
    customer = dict(updated.get("customer") or {})
    transport = dict(customer.get("transport") or {})
    cgnat = dict(transport.get("cgnat") or {})
    outside_nat = dict(customer.get("outside_nat") or {})
    post_ipsec_nat = dict(customer.get("post_ipsec_nat") or {})

    report: dict[str, Any] = {
        "applied": False,
        "reason": "",
        "service_profile": str(cgnat.get("service_profile") or "").strip(),
        "deployment_environment": str(deployment_environment or "").strip(),
        "integration_path": None,
        "outside_nat": None,
    }

    if str(transport.get("mode") or "").strip().lower() != "cgnat":
        report["reason"] = "transport_mode_not_cgnat"
        return updated, report

    service_profile = str(cgnat.get("service_profile") or "").strip()
    if not service_profile:
        report["reason"] = "missing_service_profile"
        return updated, report

    if bool(post_ipsec_nat.get("enabled")):
        report["reason"] = "post_ipsec_nat_enabled"
        return updated, report

    if bool(outside_nat.get("enabled")) and str(outside_nat.get("route_via") or "").strip():
        report["reason"] = "outside_nat_already_explicit"
        report["outside_nat"] = outside_nat
        return updated, report

    deployment_environment = str(deployment_environment or "").strip()
    if not deployment_environment:
        report["reason"] = "missing_deployment_environment"
        return updated, report

    integration_path = _resolve_profile_integration_path(
        service_profile=service_profile,
        deployment_environment=deployment_environment,
    )
    report["integration_path"] = str(integration_path) if integration_path is not None else None
    if integration_path is None:
        report["reason"] = "profile_integration_not_found"
        return updated, report

    integration = _load_json(integration_path)
    route_via = str(integration.get("outside_nat_route_via") or "").strip()
    route_dev = str(integration.get("outside_nat_route_dev") or "").strip()
    if not route_via:
        report["reason"] = "profile_integration_missing_route_via"
        return updated, report

    service_local_subnets = _normalized_cidrs(
        list(integration.get("service_local_subnets") or [])
        or list(cgnat.get("service_reachable_subnets") or [])
        or list((customer.get("selectors") or {}).get("local_subnets") or [])
    )
    if not service_local_subnets:
        report["reason"] = "missing_service_local_subnets"
        return updated, report

    excluded_subnets = set(_excluded_real_subnets(integration, environment_doc or {}))
    routed_subnets = [subnet for subnet in service_local_subnets if subnet not in excluded_subnets]
    if not routed_subnets:
        report["reason"] = "no_routed_service_subnets"
        return updated, report

    route_dev = route_dev or str(((environment_doc or {}).get("environment") or {}).get("bindings", {}).get("HEADEND_CLEAR_IFACE") or "ens36")
    rendered_outside_nat = {
        "enabled": True,
        "mode": "netmap",
        "mapping_strategy": "one_to_one",
        "real_subnets": routed_subnets,
        "translated_subnets": routed_subnets,
        "route_via": route_via,
        "route_dev": route_dev,
    }
    customer["outside_nat"] = rendered_outside_nat
    updated["customer"] = customer
    report["applied"] = True
    report["reason"] = "scenario_profile_route_via_applied"
    report["outside_nat"] = rendered_outside_nat
    report["excluded_real_subnets"] = sorted(excluded_subnets)
    return updated, report
