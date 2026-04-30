from __future__ import annotations

from typing import Any


def build_deployment_stage_review(
    *,
    bundle: dict[str, Any],
    cgnat_review: dict[str, Any],
    backend_integration: dict[str, Any],
) -> dict[str, Any]:
    backend_deploy_ok = bool(backend_integration.get("validation_ok") and backend_integration.get("deploy_dry_run_ok"))
    backend_live_gate_ok = bool(((backend_integration.get("live_gate") or {}).get("allow_live_apply_now")))
    ready = bool(cgnat_review.get("ready_for_hard_review") and backend_deploy_ok and backend_live_gate_ok)
    return {
        "review_type": "scenario1_deployment_stage_review",
        "service_id": bundle["sot"]["service_id"],
        "environment_name": bundle["operations"]["environment_name"],
        "ready_for_deployment_stage_review": ready,
        "status_summary": {
            "cgnat_ready_for_hard_review": bool(cgnat_review.get("ready_for_hard_review")),
            "backend_request_validation_ok": bool(backend_integration.get("validation_ok")),
            "backend_deploy_dry_run_ok": bool(backend_integration.get("deploy_dry_run_ok")),
            "backend_live_gate_allow_live_apply_now": backend_live_gate_ok,
        },
        "deployment_model": {
            "hosted_cgnat_head_end": True,
            "customer_facing_public_ip": bundle["sot"]["backend_selection"]["customer_facing_public_ip"],
            "preferred_backend_class": bundle["sot"]["backend_selection"]["preferred_class"],
            "backend_reuse_path": "existing_deploy_customer_dry_run",
            "backend_headend_family": backend_integration.get("backend_headend_family"),
            "backend_customer_name": backend_integration.get("backend_customer_name"),
            "backend_customer_names": list(backend_integration.get("backend_customer_names") or []),
            "backend_service_local_subnets": list(backend_integration.get("service_local_subnets") or []),
            "customer_router_count": len(bundle["sot"]["customer_devices"]),
        },
        "notes": [
            "CGNAT ingress and transport stay owned in CGNAT/.",
            "Existing deploy_customer dry-run is reused for backend customer planning on a per-customer-router basis.",
            "Backend live apply remains a later reviewed step after infrastructure create approval.",
            "Confirm the selected customer-facing public loopback remains the intended existing VPN public endpoint before backend live apply.",
        ],
    }
