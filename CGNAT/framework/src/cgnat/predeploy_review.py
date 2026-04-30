from __future__ import annotations

from pathlib import Path
from typing import Any


def _all_statuses_ok(apply_result: dict[str, Any]) -> bool:
    role_statuses = [
        apply_result.get("head_end", {}).get("status"),
        apply_result.get("isp_head_end", {}).get("status"),
    ]
    role_statuses.extend(router.get("status") for router in apply_result.get("customer_vpn_routers", []))
    action_statuses = [action.get("status") for action in apply_result.get("post_create_actions", [])]
    allowed = {"dry_run_ok", "accepted", "completed", "deferred_until_live_create"}
    return all(status in allowed for status in role_statuses + action_statuses if status is not None)


def build_predeploy_review(
    bundle: dict[str, Any],
    prep_summary: dict[str, Any],
    preflight_result: dict[str, Any],
    aws_apply_result: dict[str, Any],
    host_access_strategy_path: str | None = None,
    materials_manifest_path: str | None = None,
) -> dict[str, Any]:
    service_id = bundle["sot"]["service_id"]
    environment_name = bundle["operations"]["environment_name"]

    open_items = []
    if materials_manifest_path and Path(materials_manifest_path).exists():
        open_items.append(
            {
                "code": "demo_materials_ready",
                "type": "prepared_input",
                "message": f"Demo PKI and inner VPN secret material are prepared at `{materials_manifest_path}` and can be staged through the host-apply package.",
            }
        )
    else:
        open_items.extend(
            [
                {
                    "code": "materialize_outer_pki",
                    "type": "operator_input",
                    "message": "Demo PKI references are defined, but certificate/key material must still be generated and staged on hosts before server apply.",
                },
                {
                    "code": "materialize_inner_vpn_secret",
                    "type": "operator_input",
                    "message": "Inner VPN auth references exist in SoT, but the real key material must still be provided for the demo customer side.",
                },
            ]
        )
    open_items.append(
        {
            "code": "derive_host_access_after_create",
            "type": "post_create_step",
            "message": "Final remote host-access targets depend on created instance/EIP results and should be derived after live AWS create completes.",
        }
    )
    if host_access_strategy_path:
        open_items.append(
            {
                "code": "host_access_strategy_ready",
                "type": "prepared_input",
                "message": f"Host access strategy is prepared at `{host_access_strategy_path}` and can be used with derive_host_access_from_aws_apply.py after create.",
            }
        )

    ready_for_hard_review = (
        prep_summary.get("validation_ok")
        and prep_summary.get("aws_live_create_allowed")
        and prep_summary.get("aws_preflight_ready_for_live_apply")
        and _all_statuses_ok(aws_apply_result)
    )

    return {
        "review_type": "scenario1_predeploy_review",
        "service_id": service_id,
        "environment_name": environment_name,
        "ready_for_hard_review": bool(ready_for_hard_review),
        "status_summary": {
            "bundle_validation_ok": prep_summary.get("validation_ok"),
            "aws_plan_live_create_allowed": prep_summary.get("aws_live_create_allowed"),
            "aws_preflight_ready_for_live_apply": prep_summary.get("aws_preflight_ready_for_live_apply"),
            "aws_dry_run_ok": _all_statuses_ok(aws_apply_result),
        },
        "deployment_model": {
            "hosted_cgnat_head_end": True,
            "multi_peer_direction_preserved": True,
            "customer_facing_public_ip": bundle["sot"]["backend_selection"]["customer_facing_public_ip"],
            "preferred_backend_class": bundle["sot"]["backend_selection"]["preferred_class"],
            "customer_router_count": len(bundle["sot"]["customer_devices"]),
        },
        "open_items_before_host_apply": open_items,
        "next_commands_after_approval": [
            "Run deploy_scenario1_aws.py with --mode apply --execute-live against the reviewed AWS package.",
            "Run derive_host_access_from_aws_apply.py using the live apply-result and the host access strategy JSON.",
            "Generate the remote apply plan from the host-apply package and derived host access JSON.",
            "Review host-side artifacts one last time, then execute the remote apply plan.",
        ],
        "preflight_issues": preflight_result.get("issues", []),
    }
