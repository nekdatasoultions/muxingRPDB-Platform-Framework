from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cgnat.pki_materializer import materialize_cgnat_pki, resolve_cgnat_pki_spec


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _customer_doc(request_doc: dict[str, Any]) -> dict[str, Any]:
    return dict(request_doc.get("customer") or {})


def _transport_doc(request_doc: dict[str, Any]) -> dict[str, Any]:
    return dict((_customer_doc(request_doc).get("transport") or {}))


def _cgnat_doc(request_doc: dict[str, Any]) -> dict[str, Any]:
    return dict((_transport_doc(request_doc).get("cgnat") or {}))


def _outer_topology(request_doc: dict[str, Any]) -> str:
    topology = str((_cgnat_doc(request_doc).get("outer_topology") or "")).strip().lower().replace("-", "_")
    return topology or "per_customer_outer"


def validate_cgnat_request(request_doc: dict[str, Any], *, request_path: str = "request") -> None:
    transport = _transport_doc(request_doc)
    mode = str(transport.get("mode") or "").strip().lower()
    if mode != "cgnat":
        raise ValueError(f"{request_path} must declare customer.transport.mode = cgnat")
    cgnat = _cgnat_doc(request_doc)
    pki = dict(cgnat.get("pki") or {})
    customer_pki = dict(pki.get("customer") or {})
    gateway_pki = dict(pki.get("gateway") or {})
    topology = _outer_topology(request_doc)
    required = [
        "service_profile",
        "customer_loopback_ip",
        "known_inside_identity",
    ]
    missing = [field for field in required if not str(cgnat.get(field) or "").strip()]
    if topology == "shared_isp_gateway" and not str(cgnat.get("outer_gateway_ref") or "").strip():
        missing.append("outer_gateway_ref")
    if topology == "shared_isp_gateway":
        if not (str(cgnat.get("outer_identity_ref") or "").strip() or str(gateway_pki.get("identity_ref") or "").strip()):
            missing.append("outer_identity_ref|customer.transport.cgnat.pki.gateway.identity_ref")
        if not (str(cgnat.get("outer_auth_ref") or "").strip() or str(gateway_pki.get("auth_ref") or "").strip()):
            missing.append("outer_auth_ref|customer.transport.cgnat.pki.gateway.auth_ref")
    else:
        if not (str(cgnat.get("outer_identity_ref") or "").strip() or str(customer_pki.get("identity_ref") or "").strip()):
            missing.append("outer_identity_ref|customer.transport.cgnat.pki.customer.identity_ref")
        if not (str(cgnat.get("outer_auth_ref") or "").strip() or str(customer_pki.get("auth_ref") or "").strip()):
            missing.append("outer_auth_ref|customer.transport.cgnat.pki.customer.auth_ref")
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
            "outer_topology": cgnat.get("outer_topology") or "per_customer_outer",
            "outer_gateway_ref": cgnat.get("outer_gateway_ref"),
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
    pki_spec = resolve_cgnat_pki_spec(request_doc)
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
            "outer_topology": cgnat.get("outer_topology") or "per_customer_outer",
            "outer_gateway_ref": cgnat.get("outer_gateway_ref"),
            "outer_identity_ref": cgnat.get("outer_identity_ref"),
            "outer_auth_ref": cgnat.get("outer_auth_ref"),
            "customer_loopback_ip": cgnat.get("customer_loopback_ip"),
            "known_inside_identity": cgnat.get("known_inside_identity"),
            "service_reachable_subnets": service_reachable_subnets,
        },
        "pki_binding": {
            "headend_identity_ref": pki_spec["headend"]["identity_ref"],
            "headend_auth_ref": pki_spec["headend"]["auth_ref"],
            "customer_identity_ref": pki_spec["customer"]["identity_ref"],
            "customer_auth_ref": pki_spec["customer"]["auth_ref"],
            "gateway_identity_ref": pki_spec["gateway"]["identity_ref"],
            "gateway_auth_ref": pki_spec["gateway"]["auth_ref"],
            "trust_ca_ref": pki_spec["trust"]["ca_ref"],
        },
        "notes": [
            "The CGNAT head-end remains an explicit deployment surface with its own target and backup reference.",
            "This review surface captures the customer-specific outer transport identity and service selectors needed for live integration.",
        ],
    }


def build_cgnat_pki_surface_review(
    *,
    request_doc: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    return materialize_cgnat_pki(request_doc, output_dir)


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


def build_cgnat_live_test_bed_plan(
    *,
    request_doc: dict[str, Any],
    execution_plan: dict[str, Any],
    rollback_plan: dict[str, Any],
    test_bed_customer: str | None = None,
) -> dict[str, Any]:
    customer_name = str((_customer_doc(request_doc).get("name") or ""))
    targets = _selected_targets(execution_plan)
    gate = _dry_run_gate(execution_plan)
    selected_family = str(targets.get("headend_family") or "").strip()
    headend_backup_key = "nat_headend" if selected_family == "nat" else "non_nat_headend"
    backup_refs = dict(gate.get("backup_refs") or {})
    backend_headend_backup_ref = (
        backup_refs.get(headend_backup_key)
        or backup_refs.get("selected_headend")
    )
    backend_headend_backup_key = str(
        backup_refs.get("selected_headend_key") or headend_backup_key
    )
    test_bed = str(test_bed_customer or customer_name).strip()
    return {
        "schema_version": 1,
        "status": "review_required",
        "generated_at": _now_utc(),
        "customer_name": customer_name,
        "test_bed_customer": test_bed,
        "transport_mode": str((_transport_doc(request_doc).get("mode") or "")),
        "target_summary": {
            "muxer": dict(targets.get("muxer") or {}).get("name"),
            "backend_headend_family": selected_family,
            "backend_headend_active": dict(targets.get("headend_active") or {}).get("name"),
            "backend_headend_standby": dict(targets.get("headend_standby") or {}).get("name"),
            "cgnat_headend_active": dict(targets.get("cgnat_headend_active") or {}).get("name"),
        },
        "backup_gate": {
            "required": True,
            "references": {
                "muxer": backup_refs.get("muxer"),
                "backend_headend": backend_headend_backup_ref,
                "backend_headend_key": backend_headend_backup_key,
                "cgnat_headend": backup_refs.get("cgnat_headend"),
            },
        },
        "pre_change_capture_order": [
            "capture_cgnat_headend_backup",
            "capture_muxer_backup",
            "capture_backend_headend_backup",
            "verify_backup_artifacts_before_remove_or_replace",
        ],
        "staged_apply_order": [
            "apply_backend_customer_state",
            "validate_backend_customer_state",
            "apply_muxer_customer_state",
            "validate_muxer_customer_state",
            "apply_cgnat_headend_customer_state",
            "validate_cgnat_headend_customer_state",
        ],
        "rollback_order": list(rollback_plan.get("rollback_order") or []),
        "notes": [
            "This plan is for the first controlled live CGNAT test-bed run and must remain backup-first.",
            "Do not remove or replace any live configuration until the referenced backups are captured and verified.",
            f"Use {test_bed} as the preferred first live test-bed customer unless a later review explicitly changes that choice.",
        ],
    }


def build_cgnat_live_execution_plan(
    *,
    request_doc: dict[str, Any],
    execution_plan: dict[str, Any],
    pki_review: dict[str, Any],
    rollback_plan: dict[str, Any],
    live_test_bed_plan: dict[str, Any],
) -> dict[str, Any]:
    customer_name = str((_customer_doc(request_doc).get("name") or ""))
    cgnat = _cgnat_doc(request_doc)
    topology = _outer_topology(request_doc)
    outer_handoff = dict(pki_review.get("outer_handoff") or {})
    customer_handoff = dict(pki_review.get("customer_handoff") or {})
    gateway_handoff = dict(pki_review.get("gateway_handoff") or {})
    artifacts = dict(pki_review.get("artifacts") or {})
    edge_is_gateway = topology == "shared_isp_gateway"
    edge_role = "isp_gateway" if edge_is_gateway else "customer_device"
    edge_backup_items = [
        "existing outer tunnel connection config",
        "existing certificate and private key",
        "existing CA/trust bundle",
        "existing service status and loaded SAs",
        "existing routes and interface addresses",
    ]
    if edge_is_gateway:
        edge_backup_items[0] = "existing ISP gateway outer tunnel connection config"
    return {
        "schema_version": 1,
        "status": "review_required",
        "generated_at": _now_utc(),
        "customer_name": customer_name,
        "test_bed_customer": live_test_bed_plan.get("test_bed_customer"),
        "outer_topology": cgnat.get("outer_topology") or "per_customer_outer",
        "outer_gateway_ref": cgnat.get("outer_gateway_ref"),
        "platform_backup_refs": dict((live_test_bed_plan.get("backup_gate") or {}).get("references") or {}),
        "edge_device_backup_required": True,
        "edge_device_role": edge_role,
        "customer_device_backup_required": not edge_is_gateway,
        "gateway_device_backup_required": edge_is_gateway,
        "edge_device_backup_items": edge_backup_items,
        "customer_device_backup_items": edge_backup_items if not edge_is_gateway else [],
        "gateway_device_backup_items": edge_backup_items if edge_is_gateway else [],
        "outer_handoff": {
            "recipient_type": outer_handoff.get("recipient_type"),
            "package_name": outer_handoff.get("package_name"),
            "identity_ref": outer_handoff.get("identity_ref"),
            "auth_ref": outer_handoff.get("auth_ref"),
            "manifest": outer_handoff.get("manifest"),
            "readme": outer_handoff.get("readme"),
            "generated_material": bool(pki_review.get("generated_material")),
            "certificate_path": artifacts.get("outer_certificate_path")
            or artifacts.get("customer_certificate_path")
            or artifacts.get("gateway_certificate_path"),
            "private_key_path": artifacts.get("outer_private_key_path")
            or artifacts.get("customer_private_key_path")
            or artifacts.get("gateway_private_key_path"),
            "ca_certificate_path": artifacts.get("ca_certificate_path"),
        },
        "customer_handoff": {
            "package_name": customer_handoff.get("package_name"),
            "identity_ref": customer_handoff.get("identity_ref"),
            "auth_ref": customer_handoff.get("auth_ref"),
            "manifest": artifacts.get("customer_handoff_manifest"),
            "readme": artifacts.get("customer_handoff_readme"),
            "outer_material_required": bool(customer_handoff.get("outer_material_required")),
            "generated_material": bool(pki_review.get("generated_material")),
            "certificate_path": artifacts.get("customer_certificate_path"),
            "private_key_path": artifacts.get("customer_private_key_path"),
            "ca_certificate_path": artifacts.get("ca_certificate_path"),
        },
        "gateway_handoff": {
            "package_name": gateway_handoff.get("package_name"),
            "identity_ref": gateway_handoff.get("identity_ref"),
            "auth_ref": gateway_handoff.get("auth_ref"),
            "manifest": artifacts.get("gateway_handoff_manifest"),
            "readme": artifacts.get("gateway_handoff_readme"),
            "outer_material_required": bool(gateway_handoff.get("outer_material_required")),
            "generated_material": bool(pki_review.get("generated_material")),
            "certificate_path": artifacts.get("gateway_certificate_path"),
            "private_key_path": artifacts.get("gateway_private_key_path"),
            "ca_certificate_path": artifacts.get("ca_certificate_path"),
        },
        "platform_apply_order": list(live_test_bed_plan.get("staged_apply_order") or []),
        "customer_device_apply_order": (
            [
                "capture_customer_device_backups",
                "stage_new_outer_tunnel_cert_bundle",
                "stage_new_outer_tunnel_config_without_removing_previous_state",
                "load_or_reload_customer_outer_tunnel_config",
                "bring_up_new_outer_tunnel",
                "validate_customer_outer_tunnel_certificate_identity",
                "validate_inner_tunnel_and_service_path",
                "retire_previous_customer_outer_tunnel_state_only_after_validation",
            ]
            if not edge_is_gateway
            else [
                "capture_customer_device_backups",
                "validate_inner_tunnel_and_service_path",
            ]
        ),
        "gateway_device_apply_order": (
            [
                "capture_gateway_device_backups",
                "stage_new_outer_tunnel_cert_bundle",
                "stage_new_outer_tunnel_config_without_removing_previous_state",
                "load_or_reload_gateway_outer_tunnel_config",
                "bring_up_new_outer_tunnel",
                "validate_gateway_outer_tunnel_certificate_identity",
                "validate_inner_tunnel_and_service_path",
                "retire_previous_gateway_outer_tunnel_state_only_after_validation",
            ]
            if edge_is_gateway
            else []
        ),
        "validation_order": [
            "validate_platform_state_after_backend_muxer_cgnat_apply",
            (
                "validate_gateway_outer_tunnel_on_isp_gateway_and_cgnat_headend"
                if edge_is_gateway
                else "validate_customer_outer_tunnel_on_customer_and_cgnat_headend"
            ),
            "validate_inner_tunnel_on_backend_headend",
            "validate_service_path_and_bidirectional counters",
        ],
        "rollback_order": [
            (
                "restore_previous_gateway_device_cert_and_config"
                if edge_is_gateway
                else "restore_previous_customer_device_cert_and_config"
            ),
            *list(rollback_plan.get("rollback_order") or []),
        ],
        "guard_rails": [
            (
                "Do not remove previous gateway cert or config until the new outer tunnel is established and validated."
                if edge_is_gateway
                else "Do not remove previous customer-device cert or config until the new outer tunnel is established and validated."
            ),
            "Stop after each platform surface if validation fails; do not continue to the next surface on partial success.",
            (
                "Rollback immediately if the gateway outer tunnel does not establish with the expected identity and trust chain."
                if edge_is_gateway
                else "Rollback immediately if the customer outer tunnel does not establish with the expected identity and trust chain."
            ),
            "Rollback immediately if customer-1 traffic validation fails after a platform or customer-device change.",
        ],
        "execution_plan_ref": execution_plan.get("artifacts", {}).get("execution_plan"),
        "notes": [
            "The shared provisioning flow still owns platform-side state only; customer-device installation uses the generated handoff package.",
            "This checklist is intended for the first controlled customer-1 live run and should be reused for customer 2 only after customer 1 is green.",
        ],
    }


def build_cgnat_combined_review(
    *,
    request_doc: dict[str, Any],
    readiness: dict[str, Any],
    execution_plan: dict[str, Any],
    backend_review: dict[str, Any],
    muxer_review: dict[str, Any],
    cgnat_headend_review: dict[str, Any],
    pki_review: dict[str, Any],
    rollback_plan: dict[str, Any],
    live_test_bed_plan: dict[str, Any],
    live_execution_plan: dict[str, Any],
    shared_deploy_dir: Path,
) -> dict[str, Any]:
    validate_cgnat_request(request_doc)
    statuses = {
        "shared_dry_run": execution_plan.get("status"),
        "backend": backend_review.get("status"),
        "muxer": muxer_review.get("status"),
        "cgnat_headend": cgnat_headend_review.get("status"),
        "pki": pki_review.get("status"),
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
            "pki": "pki/pki-review.json",
            "rollback_plan": "rollback-plan.json",
            "live_test_bed_plan": "live-test-bed-plan.json",
            "live_execution_plan": "live-execution-plan.json",
            "live_execution_checklist": "LIVE_EXECUTION_CHECKLIST.md",
        },
        "notes": [
            "This review package layers CGNAT-specific deployment surfaces on top of the shared RPDB repo-only package and dry-run deploy plan.",
            "No live nodes were touched while building this review package.",
            "Future live testing must honor the backup-before-remove rule captured in the rollback plan.",
            f"PKI material mode: {pki_review.get('mode')}",
            f"Preferred first live test bed: {live_test_bed_plan.get('test_bed_customer')}",
            f"Customer handoff package: {(live_execution_plan.get('customer_handoff') or {}).get('package_name')}",
        ],
    }


def render_cgnat_live_execution_checklist(*, live_execution_plan: dict[str, Any]) -> str:
    handoff = dict(live_execution_plan.get("customer_handoff") or {})
    outer_handoff = dict(live_execution_plan.get("outer_handoff") or {})
    edge_role = str(live_execution_plan.get("edge_device_role") or "customer_device")
    lines = [
        f"# CGNAT Live Execution Checklist: {live_execution_plan.get('customer_name')}",
        "",
        "## Guard Rails",
        "",
    ]
    for item in live_execution_plan.get("guard_rails") or []:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Platform Backups",
            "",
        ]
    )
    for key, value in dict(live_execution_plan.get("platform_backup_refs") or {}).items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            f"## Outer Peer Backups ({edge_role})",
            "",
        ]
    )
    for item in live_execution_plan.get("edge_device_backup_items") or []:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Outer Handoff Package",
            "",
            f"- Recipient type: `{outer_handoff.get('recipient_type')}`",
            f"- Package name: `{outer_handoff.get('package_name')}`",
            f"- Manifest: `{outer_handoff.get('manifest')}`",
            f"- README: `{outer_handoff.get('readme')}`",
            f"- Certificate path: `{outer_handoff.get('certificate_path')}`",
            f"- Private key path: `{outer_handoff.get('private_key_path')}`",
            f"- CA path: `{outer_handoff.get('ca_certificate_path')}`",
            "",
            "## Customer Handoff Package",
            "",
            f"- Package name: `{handoff.get('package_name')}`",
            f"- Manifest: `{handoff.get('manifest')}`",
            f"- README: `{handoff.get('readme')}`",
            f"- Generated material: `{handoff.get('generated_material')}`",
            f"- Certificate path: `{handoff.get('certificate_path')}`",
            f"- Private key path: `{handoff.get('private_key_path')}`",
            f"- CA path: `{handoff.get('ca_certificate_path')}`",
            "",
            "## Platform Apply Order",
            "",
        ]
    )
    for step in live_execution_plan.get("platform_apply_order") or []:
        lines.append(f"1. `{step}`")
    lines.extend(
        [
            "",
            "## Customer Device Apply Order",
            "",
        ]
    )
    for step in live_execution_plan.get("customer_device_apply_order") or []:
        lines.append(f"1. `{step}`")
    if live_execution_plan.get("gateway_device_apply_order"):
        lines.extend(["", "## Gateway Device Apply Order", ""])
        for step in live_execution_plan.get("gateway_device_apply_order") or []:
            lines.append(f"1. `{step}`")
    lines.extend(
        [
            "",
            "## Validation Order",
            "",
        ]
    )
    for step in live_execution_plan.get("validation_order") or []:
        lines.append(f"1. `{step}`")
    lines.extend(
        [
            "",
            "## Rollback Order",
            "",
        ]
    )
    for step in live_execution_plan.get("rollback_order") or []:
        lines.append(f"1. `{step}`")
    return "\n".join(lines) + "\n"


def render_cgnat_combined_readme(
    *,
    combined_review: dict[str, Any],
    backend_review: dict[str, Any],
    muxer_review: dict[str, Any],
    cgnat_headend_review: dict[str, Any],
    pki_review: dict[str, Any],
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
        f"- PKI mode: `{pki_review.get('mode')}`",
        f"- Customer handoff package: `{(pki_review.get('customer_handoff') or {}).get('package_name')}`",
        "",
        "## Safety",
        "",
        "- No live nodes were touched while generating this review package.",
        "- Before removing or replacing any live configuration for testing, capture and verify backups for every touched surface.",
        "",
    ]
    return "\n".join(lines)
