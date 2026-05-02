from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _customer_doc(request_doc: dict[str, Any]) -> dict[str, Any]:
    return dict(request_doc.get("customer") or {})


def _transport_doc(request_doc: dict[str, Any]) -> dict[str, Any]:
    return dict((_customer_doc(request_doc).get("transport") or {}))


def validate_cgnat_request(request_doc: dict[str, Any], *, request_path: str = "request") -> None:
    transport = _transport_doc(request_doc)
    mode = str(transport.get("mode") or "").strip().lower()
    if mode != "cgnat":
        raise ValueError(f"{request_path} must declare customer.transport.mode = cgnat")
    cgnat = dict(transport.get("cgnat") or {})
    required = [
        "service_profile",
        "outer_identity_ref",
        "outer_auth_ref",
        "customer_loopback_ip",
        "known_inside_identity",
    ]
    missing = [field for field in required if not str(cgnat.get(field) or "").strip()]
    if missing:
        raise ValueError(
            f"{request_path} is missing required customer.transport.cgnat fields: {', '.join(missing)}"
        )


def _package_paths(readiness: dict[str, Any]) -> dict[str, Any]:
    return dict(readiness.get("package_paths") or {})


def _selected_targets(execution_plan: dict[str, Any]) -> dict[str, Any]:
    return dict(execution_plan.get("selected_targets") or {})


def _dry_run_gate(execution_plan: dict[str, Any]) -> dict[str, Any]:
    return dict(execution_plan.get("dry_run_gate") or {})


def _path_ref(path: Path | None) -> str | None:
    return str(path) if path is not None else None


def build_backend_surface_review(
    *,
    request_doc: dict[str, Any],
    readiness: dict[str, Any],
    execution_plan: dict[str, Any],
    shared_deploy_dir: Path,
) -> dict[str, Any]:
    customer = dict(readiness.get("customer") or {})
    package = dict(execution_plan.get("package") or {})
    targets = _selected_targets(execution_plan)
    package_paths = _package_paths(readiness)
    active = dict(targets.get("headend_active") or {})
    standby = dict(targets.get("headend_standby") or {})
    return {
        "surface": "backend",
        "status": "ready_for_review" if execution_plan.get("status") == "dry_run_ready" else "blocked",
        "generated_at": _now_utc(),
        "customer_name": str((_customer_doc(request_doc).get("name") or "")),
        "backend_cluster": customer.get("backend_cluster"),
        "headend_family": targets.get("headend_family"),
        "targets": {
            "active": active.get("name"),
            "standby": standby.get("name"),
        },
        "selectors": {
            "local_subnets": list(customer.get("local_subnets") or []),
            "remote_subnets": list(customer.get("remote_subnets") or []),
            "remote_host_cidrs": list(customer.get("remote_host_cidrs") or []),
        },
        "shared_package": {
            "package_dir": package.get("package_dir"),
            "readiness_path": package.get("readiness_path"),
            "bundle_dir": package_paths.get("bundle"),
            "bundle_validation_path": package_paths.get("bundle-validation.json"),
        },
        "shared_deploy_review": {
            "deploy_dir": _path_ref(shared_deploy_dir),
            "execution_plan": _path_ref(shared_deploy_dir / "execution-plan.json"),
        },
        "notes": [
            "Backend provisioning remains owned by the shared RPDB customer package flow.",
            "This review surface summarizes which backend head-end family and targets the shared dry-run selected.",
        ],
    }


def build_muxer_surface_review(
    *,
    request_doc: dict[str, Any],
    readiness: dict[str, Any],
    execution_plan: dict[str, Any],
) -> dict[str, Any]:
    customer = dict(readiness.get("customer") or {})
    targets = _selected_targets(execution_plan)
    gate = _dry_run_gate(execution_plan)
    muxer = dict(targets.get("muxer") or {})
    transport = _transport_doc(request_doc)
    cgnat = dict(transport.get("cgnat") or {})
    return {
        "surface": "muxer",
        "status": "ready_for_review" if execution_plan.get("status") == "dry_run_ready" else "blocked",
        "generated_at": _now_utc(),
        "customer_name": str((_customer_doc(request_doc).get("name") or "")),
        "target": muxer.get("name"),
        "backup_ref": (gate.get("backup_refs") or {}).get("muxer"),
        "service_inputs": {
            "peer_ip": customer.get("peer_ip"),
            "service_reachable_subnets": list(cgnat.get("service_reachable_subnets") or []),
            "known_inside_identity": cgnat.get("known_inside_identity"),
            "backend_family": targets.get("headend_family"),
        },
        "notes": [
            "Muxer host selection continues to come from the deployment environment YAML.",
            "This phase records the CGNAT-carrying service inputs that the muxer-facing runtime will need during live integration.",
        ],
    }


def build_cgnat_headend_surface_review(
    *,
    request_doc: dict[str, Any],
    execution_plan: dict[str, Any],
) -> dict[str, Any]:
    targets = _selected_targets(execution_plan)
    gate = _dry_run_gate(execution_plan)
    transport = _transport_doc(request_doc)
    cgnat = dict(transport.get("cgnat") or {})
    headend = dict(targets.get("cgnat_headend_active") or {})
    service_reachable_subnets = list(cgnat.get("service_reachable_subnets") or [])
    return {
        "surface": "cgnat_headend",
        "status": "ready_for_review" if headend and execution_plan.get("status") == "dry_run_ready" else "blocked",
        "generated_at": _now_utc(),
        "customer_name": str((_customer_doc(request_doc).get("name") or "")),
        "target": headend.get("name"),
        "backup_ref": (gate.get("backup_refs") or {}).get("cgnat_headend"),
        "transport_profile": {
            "service_profile": cgnat.get("service_profile"),
            "outer_identity_ref": cgnat.get("outer_identity_ref"),
            "outer_auth_ref": cgnat.get("outer_auth_ref"),
            "customer_loopback_ip": cgnat.get("customer_loopback_ip"),
            "known_inside_identity": cgnat.get("known_inside_identity"),
            "service_reachable_subnets": service_reachable_subnets,
        },
        "notes": [
            "The CGNAT head-end remains an explicit deployment surface with its own target and backup reference.",
            "This review surface captures the customer-specific outer transport identity and service selectors needed for live integration.",
        ],
    }


def build_cgnat_rollback_plan(
    *,
    execution_plan: dict[str, Any],
    test_bed_customer: str | None = None,
) -> dict[str, Any]:
    targets = _selected_targets(execution_plan)
    gate = _dry_run_gate(execution_plan)
    selected_family = str(targets.get("headend_family") or "").strip()
    selected_headend_backup_key = "nat_headend" if selected_family == "nat" else "non_nat_headend"
    backup_refs = dict(gate.get("backup_refs") or {})
    notes = [
        "Before removing, replacing, or reapplying live configuration for testing, capture and verify backups for every touched surface.",
        "Rollback should remove CGNAT head-end customer state before muxer runtime changes and before backend customer removal.",
        "Backend rollback is optional only when the backend customer already exists and the operation is limited to CGNAT enablement.",
    ]
    if test_bed_customer:
        notes.append(f"Use {test_bed_customer} as the first live CGNAT test bed unless a later review explicitly changes that choice.")
    return {
        "schema_version": 1,
        "status": "review_required",
        "generated_at": _now_utc(),
        "preconditions": {
            "backup_before_remove_required": True,
            "shared_deploy_gate_must_be_green": True,
            "rollback_owner_required": True,
            "validation_owner_required": True,
        },
        "backup_refs": {
            "muxer": backup_refs.get("muxer"),
            "backend_headend": backup_refs.get(selected_headend_backup_key),
            "backend_headend_key": selected_headend_backup_key,
            "cgnat_headend": backup_refs.get("cgnat_headend"),
        },
        "rollback_order": [
            "remove_cgnat_headend_customer_state",
            "remove_muxer_cgnat_runtime_changes",
            "remove_backend_customer_state_if_required",
        ],
        "notes": notes,
    }


def build_cgnat_combined_review(
    *,
    request_doc: dict[str, Any],
    readiness: dict[str, Any],
    execution_plan: dict[str, Any],
    backend_review: dict[str, Any],
    muxer_review: dict[str, Any],
    cgnat_headend_review: dict[str, Any],
    rollback_plan: dict[str, Any],
    shared_deploy_dir: Path,
) -> dict[str, Any]:
    validate_cgnat_request(request_doc)
    statuses = {
        "shared_dry_run": execution_plan.get("status"),
        "backend": backend_review.get("status"),
        "muxer": muxer_review.get("status"),
        "cgnat_headend": cgnat_headend_review.get("status"),
    }
    ready = all(status == "ready_for_review" or status == "dry_run_ready" for status in statuses.values())
    customer = dict(readiness.get("customer") or {})
    return {
        "schema_version": 1,
        "integration_type": "cgnat_customer_repo_only_review",
        "status": "ready_for_review" if ready else "blocked",
        "ready_for_review": ready,
        "generated_at": _now_utc(),
        "customer": {
            "name": str((_customer_doc(request_doc).get("name") or "")),
            "customer_class": customer.get("customer_class"),
            "transport_mode": customer.get("transport_mode"),
            "backend_cluster": customer.get("backend_cluster"),
        },
        "shared_deploy_review": {
            "deploy_dir": _path_ref(shared_deploy_dir),
            "execution_plan": _path_ref(shared_deploy_dir / "execution-plan.json"),
            "package_dir": execution_plan.get("package", {}).get("package_dir"),
            "readiness_path": execution_plan.get("package", {}).get("readiness_path"),
        },
        "surface_status": statuses,
        "surfaces": {
            "backend": "backend/backend-review.json",
            "muxer": "muxer/muxer-review.json",
            "cgnat_headend": "cgnat/cgnat-headend-review.json",
            "rollback_plan": "rollback-plan.json",
        },
        "notes": [
            "This review package layers CGNAT-specific deployment surfaces on top of the shared RPDB repo-only package and dry-run deploy plan.",
            "No live nodes were touched while building this review package.",
            "Future live testing must honor the backup-before-remove rule captured in the rollback plan.",
        ],
    }


def render_cgnat_combined_readme(
    *,
    combined_review: dict[str, Any],
    backend_review: dict[str, Any],
    muxer_review: dict[str, Any],
    cgnat_headend_review: dict[str, Any],
) -> str:
    customer = dict(combined_review.get("customer") or {})
    shared = dict(combined_review.get("shared_deploy_review") or {})
    lines = [
        f"# CGNAT Customer Review: {customer.get('name')}",
        "",
        "## Status",
        "",
        f"- Review status: `{combined_review.get('status')}`",
        f"- Transport mode: `{customer.get('transport_mode')}`",
        f"- Backend cluster: `{customer.get('backend_cluster')}`",
        "",
        "## Shared Review Roots",
        "",
        f"- Shared deploy review: `{shared.get('deploy_dir')}`",
        f"- Shared execution plan: `{shared.get('execution_plan')}`",
        f"- Shared package: `{shared.get('package_dir')}`",
        "",
        "## Surfaces",
        "",
        f"- Backend target family: `{backend_review.get('headend_family')}`",
        f"- Muxer target: `{muxer_review.get('target')}`",
        f"- CGNAT head-end target: `{cgnat_headend_review.get('target')}`",
        "",
        "## Safety",
        "",
        "- No live nodes were touched while generating this review package.",
        "- Before removing or replacing any live configuration for testing, capture and verify backups for every touched surface.",
        "",
    ]
    return "\n".join(lines)
