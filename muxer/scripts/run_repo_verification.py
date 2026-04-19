#!/usr/bin/env python
"""Run the repo-only RPDB completion verification suite."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
MUXER_DIR = REPO_ROOT / "muxer"
RUNTIME_ROOT = MUXER_DIR / "runtime-package"
FRAMEWORK_SRC = MUXER_DIR / "src"
RUNTIME_SRC = RUNTIME_ROOT / "src"
BUILD_ROOT = REPO_ROOT / "build" / "repo-verification"


def _run(args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )


def _run_json(args: list[str], *, env: dict[str, str] | None = None) -> dict:
    completed = _run(args, env=env)
    return json.loads(completed.stdout)


def _run_python_json(code: str, *, pythonpath: Path | None = None, extra_env: dict[str, str] | None = None) -> dict:
    env = os.environ.copy()
    if pythonpath is not None:
        env["PYTHONPATH"] = str(pythonpath)
    if extra_env:
        env.update(extra_env)
    completed = _run(["python", "-c", code], env=env)
    return json.loads(completed.stdout)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if payload.endswith("\n") else payload + "\n", encoding="utf-8")


def _resolve_repo_path(path_like: str) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def _build_staged_live_environment(environment_path: Path, *, name: str, root: Path) -> dict:
    document = yaml.safe_load(
        (
            MUXER_DIR / "config" / "deployment-environments" / "example-rpdb-staged-live.yaml"
        ).read_text(encoding="utf-8")
    )
    document["environment"]["name"] = name
    document["environment"]["aws"]["account_hint"] = name
    document["targets"]["muxer"]["selector"]["value"] = str(root / "muxer-root")
    document["targets"]["headends"]["nat"]["active"]["selector"]["value"] = str(root / "nat-active-root")
    document["targets"]["headends"]["nat"]["standby"]["selector"]["value"] = str(root / "nat-standby-root")
    document["targets"]["headends"]["non_nat"]["active"]["selector"]["value"] = str(root / "nonnat-active-root")
    document["targets"]["headends"]["non_nat"]["standby"]["selector"]["value"] = str(root / "nonnat-standby-root")
    document["datastores"]["staged_root"] = str(root / "datastores")
    document["artifacts"]["staged_root"] = str(root / "artifacts")
    document["backups"]["baseline_root"] = str(root / "backups" / "baseline")
    document["backups"]["muxer"] = str(root / "backups" / "baseline" / "muxer")
    document["backups"]["nat_headend"] = str(root / "backups" / "baseline" / "nat-headend")
    document["backups"]["non_nat_headend"] = str(root / "backups" / "baseline" / "non-nat-headend")
    document["nat_t_watcher"]["log_source"]["path"] = str(root / "logs" / "muxer-events.jsonl")
    document["nat_t_watcher"]["state_root"] = str(root / "nat-t-watcher" / "state")
    document["nat_t_watcher"]["output_root"] = str(root / "nat-t-watcher" / "out")
    document["nat_t_watcher"]["package_root"] = str(root / "nat-t-watcher" / "packages")
    for path in (
        root / "backups" / "baseline" / "muxer",
        root / "backups" / "baseline" / "nat-headend",
        root / "backups" / "baseline" / "non-nat-headend",
        root / "logs",
    ):
        path.mkdir(parents=True, exist_ok=True)
    _write_yaml(environment_path, document)
    return document


def _stage_customer_modules(build_dir: Path, provision_results: dict[str, dict]) -> Path:
    module_root = build_dir / "customer-modules"
    if module_root.exists():
        shutil.rmtree(module_root)
    module_root.mkdir(parents=True, exist_ok=True)

    for name, result in provision_results.items():
        customer_dir = module_root / name
        customer_dir.mkdir(parents=True, exist_ok=True)
        _write_json(customer_dir / "customer-module.json", result["customer_module"])
    return module_root


def _stage_runtime_configs(build_dir: Path) -> tuple[Path, Path]:
    base_cfg = yaml.safe_load((RUNTIME_ROOT / "config" / "muxer.yaml").read_text(encoding="utf-8"))

    pass_cfg = dict(base_cfg)
    pass_cfg["customer_sot"] = {
        "backend": "customer_modules",
        "dynamodb": {
            "region": "us-east-1",
            "table_name": "unused-in-repo-verification",
        },
    }

    term_cfg = dict(pass_cfg)
    term_cfg["mode"] = "termination"

    pass_cfg_path = build_dir / "runtime-pass-through.yaml"
    term_cfg_path = build_dir / "runtime-termination.yaml"
    _write_yaml(pass_cfg_path, pass_cfg)
    _write_yaml(term_cfg_path, term_cfg)
    return pass_cfg_path, term_cfg_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the repo-only RPDB completion verification suite.")
    parser.add_argument("--json", action="store_true", help="Print the verification summary as JSON")
    args = parser.parse_args()

    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    summary: dict[str, object] = {
        "schema_version": 1,
        "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo_root": str(REPO_ROOT),
        "steps": [],
        "docs": {
            "runtime_plan": str(MUXER_DIR / "docs" / "RUNTIME_COMPLETION_PLAN.md"),
            "provisioning_input_model": str(MUXER_DIR / "docs" / "PROVISIONING_INPUT_MODEL.md"),
            "resource_allocation_model": str(MUXER_DIR / "docs" / "RESOURCE_ALLOCATION_MODEL.md"),
            "dynamic_nat_t_provisioning": str(MUXER_DIR / "docs" / "DYNAMIC_NAT_T_PROVISIONING.md"),
        },
    }

    def record_step(name: str, details: dict) -> None:
        cast_steps = summary["steps"]
        assert isinstance(cast_steps, list)
        cast_steps.append({"step": name, "status": "passed", "details": details})

    # Step 1: compile the new framework/runtime modules and scripts.
    compile_targets = [
        str(MUXER_DIR / "src" / "muxerlib" / "customer_model.py"),
        str(MUXER_DIR / "src" / "muxerlib" / "customer_artifacts.py"),
        str(MUXER_DIR / "src" / "muxerlib" / "allocation.py"),
        str(MUXER_DIR / "src" / "muxerlib" / "allocation_sot.py"),
        str(MUXER_DIR / "src" / "muxerlib" / "dynamic_provisioning.py"),
        str(MUXER_DIR / "scripts" / "validate_customer_request.py"),
        str(MUXER_DIR / "scripts" / "validate_customer_allocations.py"),
        str(MUXER_DIR / "scripts" / "provision_customer_request.py"),
        str(MUXER_DIR / "scripts" / "plan_nat_t_promotion.py"),
        str(MUXER_DIR / "scripts" / "process_nat_t_observation.py"),
        str(MUXER_DIR / "scripts" / "provision_customer_end_to_end.py"),
        str(MUXER_DIR / "scripts" / "watch_nat_t_logs.py"),
        str(MUXER_DIR / "scripts" / "prepare_customer_pilot.py"),
        str(MUXER_DIR / "runtime-package" / "src" / "muxerlib" / "nftables.py"),
        str(MUXER_DIR / "runtime-package" / "scripts" / "render_nft_passthrough.py"),
        str(REPO_ROOT / "scripts" / "customers" / "validate_deployment_environment.py"),
        str(REPO_ROOT / "scripts" / "customers" / "deploy_customer.py"),
        str(REPO_ROOT / "scripts" / "customers" / "live_access_lib.py"),
        str(REPO_ROOT / "scripts" / "customers" / "live_backend_lib.py"),
        str(REPO_ROOT / "scripts" / "customers" / "live_apply_lib.py"),
        str(REPO_ROOT / "scripts" / "packaging" / "validate_customer_bundle.py"),
        str(REPO_ROOT / "scripts" / "deployment" / "backend_customer_lib.py"),
        str(REPO_ROOT / "scripts" / "deployment" / "apply_backend_customer.py"),
        str(REPO_ROOT / "scripts" / "deployment" / "remove_backend_customer.py"),
        str(REPO_ROOT / "scripts" / "deployment" / "validate_backend_customer.py"),
        str(REPO_ROOT / "scripts" / "deployment" / "headend_customer_lib.py"),
        str(REPO_ROOT / "scripts" / "deployment" / "apply_headend_customer.py"),
        str(REPO_ROOT / "scripts" / "deployment" / "remove_headend_customer.py"),
        str(REPO_ROOT / "scripts" / "deployment" / "validate_headend_customer.py"),
        str(REPO_ROOT / "scripts" / "deployment" / "muxer_customer_lib.py"),
        str(REPO_ROOT / "scripts" / "deployment" / "apply_muxer_customer.py"),
        str(REPO_ROOT / "scripts" / "deployment" / "remove_muxer_customer.py"),
        str(REPO_ROOT / "scripts" / "deployment" / "validate_muxer_customer.py"),
        str(REPO_ROOT / "scripts" / "deployment" / "run_double_verification.py"),
        str(REPO_ROOT / "scripts" / "platform" / "verify_empty_platform_readiness.py"),
    ]
    _run(["python", "-m", "py_compile", *compile_targets])
    record_step("compile_targets", {"count": len(compile_targets)})

    # Step 1b: validate the repo-only deployment environment contract.
    environment_validation = _run_json(
        [
            "python",
            str(REPO_ROOT / "scripts" / "customers" / "validate_deployment_environment.py"),
            str(MUXER_DIR / "config" / "deployment-environments" / "example-rpdb.yaml"),
            "--json",
        ]
    )
    if not environment_validation.get("valid"):
        raise SystemExit("deployment environment contract validation failed")
    record_step(
        "deployment_environment_contract_validation",
        {
            "environment_name": environment_validation.get("environment_name"),
            "targets": environment_validation.get("targets"),
            "aws_calls": environment_validation.get("aws_calls"),
            "live_node_access": environment_validation.get("live_node_access"),
        },
    )

    staged_environment_validation = _run_json(
        [
            "python",
            str(REPO_ROOT / "scripts" / "customers" / "validate_deployment_environment.py"),
            str(MUXER_DIR / "config" / "deployment-environments" / "example-rpdb-staged-live.yaml"),
            "--allow-live-apply",
            "--json",
        ]
    )
    if not staged_environment_validation.get("valid"):
        raise SystemExit("staged deployment environment contract validation failed")
    record_step(
        "staged_live_deployment_environment_contract_validation",
        {
            "environment_name": staged_environment_validation.get("environment_name"),
            "targets": staged_environment_validation.get("targets"),
            "aws_calls": staged_environment_validation.get("aws_calls"),
            "live_node_access": staged_environment_validation.get("live_node_access"),
        },
    )

    current_live_environment_validation = _run_json(
        [
            "python",
            str(REPO_ROOT / "scripts" / "customers" / "validate_deployment_environment.py"),
            str(MUXER_DIR / "config" / "deployment-environments" / "rpdb-empty-live.yaml"),
            "--allow-live-apply",
            "--json",
        ]
    )
    if not current_live_environment_validation.get("valid"):
        raise SystemExit("current live deployment environment contract validation failed")
    record_step(
        "current_live_deployment_environment_contract_validation",
        {
            "environment_name": current_live_environment_validation.get("environment_name"),
            "targets": current_live_environment_validation.get("targets"),
            "aws_calls": current_live_environment_validation.get("aws_calls"),
            "live_node_access": current_live_environment_validation.get("live_node_access"),
        },
    )

    current_live_customer2_dry_run = _run_json(
        [
            "python",
            str(REPO_ROOT / "scripts" / "customers" / "deploy_customer.py"),
            "--customer-file",
            str(MUXER_DIR / "config" / "customer-requests" / "migrated" / "legacy-cust0002.yaml"),
            "--environment",
            str(MUXER_DIR / "config" / "deployment-environments" / "rpdb-empty-live.yaml"),
            "--out-dir",
            str(BUILD_ROOT / "current-live-customer2"),
            "--dry-run",
            "--json",
        ]
    )
    if current_live_customer2_dry_run.get("status") != "dry_run_ready":
        raise SystemExit("current live Customer 2 dry-run did not report dry_run_ready")
    if not ((current_live_customer2_dry_run.get("live_gate") or {}).get("allow_live_apply_now")):
        raise SystemExit("current live Customer 2 dry-run did not become approval-ready")
    if (current_live_customer2_dry_run.get("selected_targets") or {}).get("environment_access_method") != "ssh":
        raise SystemExit("current live Customer 2 dry-run did not resolve the SSH live environment")
    record_step(
        "current_live_approval_boundary",
        {
            "environment_file": str(MUXER_DIR / "config" / "deployment-environments" / "rpdb-empty-live.yaml"),
            "status": current_live_customer2_dry_run["status"],
            "approve_supported": current_live_customer2_dry_run["live_gate"]["allow_live_apply_now"],
            "headend_family": current_live_customer2_dry_run["selected_targets"]["headend_family"],
            "execution_plan": current_live_customer2_dry_run["artifacts"]["execution_plan"],
        },
    )

    # Step 2: validate existing full customer sources for collision-free namespaces.
    allocation_validation = _run_json(
        ["python", str(MUXER_DIR / "scripts" / "validate_customer_allocations.py"), "--json"]
    )
    if not allocation_validation.get("valid"):
        raise SystemExit("existing customer allocation validation failed")
    record_step(
        "existing_customer_allocation_validation",
        {
            "customer_count": allocation_validation["customer_count"],
            "collisions": len(allocation_validation["collisions"]),
        },
    )

    # Step 3: validate and provision the minimal NAT and non-NAT requests.
    request_paths = {
        "example-minimal-nonnat": MUXER_DIR / "config" / "customer-requests" / "examples" / "example-minimal-nonnat.yaml",
        "example-minimal-nat": MUXER_DIR / "config" / "customer-requests" / "examples" / "example-minimal-nat.yaml",
        "example-dynamic-default-nonnat": MUXER_DIR / "config" / "customer-requests" / "examples" / "example-dynamic-default-nonnat.yaml",
        "example-service-intent-netmap": MUXER_DIR / "config" / "customer-requests" / "examples" / "example-service-intent-netmap.yaml",
        "example-service-intent-explicit-host-map": MUXER_DIR / "config" / "customer-requests" / "examples" / "example-service-intent-explicit-host-map.yaml",
    }
    provision_results: dict[str, dict] = {}
    generated_sources_root = BUILD_ROOT / "generated-customer-sources"
    if generated_sources_root.exists():
        shutil.rmtree(generated_sources_root)
    generated_sources_root.mkdir(parents=True, exist_ok=True)
    for name, request_path in request_paths.items():
        _run(["python", str(MUXER_DIR / "scripts" / "validate_customer_request.py"), str(request_path)])
        source_out = generated_sources_root / name / "customer.yaml"
        provision_results[name] = _run_json(
            [
                "python",
                str(MUXER_DIR / "scripts" / "provision_customer_request.py"),
                str(request_path),
                "--existing-source-root",
                str(MUXER_DIR / "config" / "customer-sources"),
                "--existing-source-root",
                str(generated_sources_root),
                "--source-out",
                str(source_out),
                "--json",
            ]
        )
    record_step(
        "minimal_request_provisioning",
        {
            "customers": sorted(provision_results),
            "customer_ids": {
                name: result["allocation_plan"]["customer_id"]
                for name, result in provision_results.items()
            },
            "generated_sources_root": str(generated_sources_root),
        },
    )

    # Step 3b: verify the repo-only dynamic NAT-T promotion planner.
    dynamic_name = "example-dynamic-default-nonnat"
    dynamic_promotion_dir = BUILD_ROOT / "dynamic-promotion"
    if dynamic_promotion_dir.exists():
        shutil.rmtree(dynamic_promotion_dir)
    dynamic_promotion_dir.mkdir(parents=True, exist_ok=True)
    observation_path = (
        MUXER_DIR
        / "config"
        / "customer-requests"
        / "examples"
        / "example-dynamic-nat-t-observation.json"
    )
    workflow_result = _run_json(
        [
            "python",
            str(MUXER_DIR / "scripts" / "process_nat_t_observation.py"),
            str(request_paths[dynamic_name]),
            "--observation",
            str(observation_path),
            "--out-dir",
            str(dynamic_promotion_dir),
            "--existing-source-root",
            str(MUXER_DIR / "config" / "customer-sources"),
            "--existing-source-root",
            str(generated_sources_root),
            "--json",
        ]
    )
    duplicate_workflow_result = _run_json(
        [
            "python",
            str(MUXER_DIR / "scripts" / "process_nat_t_observation.py"),
            str(request_paths[dynamic_name]),
            "--observation",
            str(observation_path),
            "--out-dir",
            str(dynamic_promotion_dir),
            "--existing-source-root",
            str(MUXER_DIR / "config" / "customer-sources"),
            "--existing-source-root",
            str(generated_sources_root),
            "--json",
        ]
    )
    artifacts = workflow_result["artifacts"]
    _run(["python", str(MUXER_DIR / "scripts" / "validate_customer_request.py"), artifacts["promoted_request"]])
    _run(["python", str(MUXER_DIR / "scripts" / "validate_customer_source.py"), artifacts["promoted_source"]])
    if provision_results[dynamic_name]["allocation_plan"]["pool_class"] != "non-nat":
        raise SystemExit("dynamic initial request did not allocate from the non-NAT pool")
    if workflow_result["allocation_plan"]["pool_class"] != "nat":
        raise SystemExit("dynamic NAT-T promotion did not allocate from the NAT pool")
    if duplicate_workflow_result["status"] != "already_planned":
        raise SystemExit("duplicate dynamic NAT-T observation was not idempotent")
    if duplicate_workflow_result["new_allocation_created"]:
        raise SystemExit("duplicate dynamic NAT-T observation unexpectedly allocated again")
    record_step(
        "dynamic_nat_t_observation_processing",
        {
            "customer_name": dynamic_name,
            "initial_pool_class": provision_results[dynamic_name]["allocation_plan"]["pool_class"],
            "promoted_pool_class": workflow_result["allocation_plan"]["pool_class"],
            "promoted_customer_id": workflow_result["allocation_plan"]["customer_id"],
            "idempotency_key": workflow_result["idempotency_key"],
            "duplicate_status": duplicate_workflow_result["status"],
            "promoted_request": artifacts["promoted_request"],
            "audit": artifacts["audit"],
            "promotion_summary": workflow_result["promotion_summary"],
        },
    )

    # Step 3c: verify the one-command repo-only pilot package builder for
    # standalone NAT, strict non-NAT, and dynamic NAT-T promotion packages.
    pilot_root = BUILD_ROOT / "pilot-packages"
    if pilot_root.exists():
        shutil.rmtree(pilot_root)
    pilot_root.mkdir(parents=True, exist_ok=True)
    pilot_specs = {
        "strict-non-nat": {
            "request": request_paths["example-minimal-nonnat"],
            "out_dir": pilot_root / "strict-non-nat",
        },
        "nat": {
            "request": request_paths["example-service-intent-netmap"],
            "out_dir": pilot_root / "nat",
        },
        "dynamic-nat-t": {
            "request": request_paths[dynamic_name],
            "out_dir": pilot_root / "dynamic-nat-t",
            "observation": observation_path,
        },
        "pilot-legacy-cust0002": {
            "request": MUXER_DIR
            / "config"
            / "customer-requests"
            / "migrated"
            / "legacy-cust0002.yaml",
            "out_dir": pilot_root / "legacy-cust0002",
            "environment_file": MUXER_DIR
            / "config"
            / "environment-defaults"
            / "rpdb-empty-nonnat-active-a.yaml",
        },
        "pilot-vpn-customer-stage1-15-cust-0004": {
            "request": MUXER_DIR
            / "config"
            / "customer-requests"
            / "migrated"
            / "vpn-customer-stage1-15-cust-0004.yaml",
            "out_dir": pilot_root / "vpn-customer-stage1-15-cust-0004",
            "environment_file": MUXER_DIR
            / "config"
            / "environment-defaults"
            / "rpdb-empty-nat-active-a.yaml",
            "observation": MUXER_DIR
            / "config"
            / "customer-requests"
            / "migrated"
            / "vpn-customer-stage1-15-cust-0004-nat-t-observation.json",
        },
    }
    pilot_reports: dict[str, dict] = {}
    default_environment_file = MUXER_DIR / "config" / "environment-defaults" / "example-environment.yaml"
    for pilot_name, spec in pilot_specs.items():
        environment_file = spec.get("environment_file", default_environment_file)
        pilot_command = [
            "python",
            str(MUXER_DIR / "scripts" / "prepare_customer_pilot.py"),
            str(spec["request"]),
            "--out-dir",
            str(spec["out_dir"]),
            "--environment-file",
            str(environment_file),
            "--json",
        ]
        if spec.get("observation"):
            pilot_command.extend(["--observation", str(spec["observation"])])
        report = _run_json(pilot_command)
        if report["status"] != "ready_for_review":
            raise SystemExit(f"pilot package builder did not produce a ready package: {pilot_name}")
        if report["live_apply"] is not False:
            raise SystemExit(f"pilot package builder live_apply guard failed: {pilot_name}")
        if pilot_name == "dynamic-nat-t":
            if not report["dynamic_nat_t"]["used"]:
                raise SystemExit("dynamic pilot package did not include NAT-T audit")
            if report["customer"]["customer_class"] != "nat":
                raise SystemExit("dynamic pilot package did not promote to NAT")
        pilot_reports[pilot_name] = {
            "customer_name": report["customer"]["name"],
            "customer_class": report["customer"]["customer_class"],
            "backend_cluster": report["customer"]["backend_cluster"],
            "package_dir": str(spec["out_dir"]),
            "ready_for_review": report["ready_for_review"],
            "live_apply": report["live_apply"],
            "dynamic_nat_t_used": report["dynamic_nat_t"]["used"],
        }
    record_step(
        "customer_pilot_package_builder",
        {
            "pilot_packages": pilot_reports,
        },
    )

    # Step 3d: verify the operator-facing one-file provisioning entrypoint.
    e2e_root = BUILD_ROOT / "end-to-end-provisioning"
    if e2e_root.exists():
        shutil.rmtree(e2e_root)
    e2e_root.mkdir(parents=True, exist_ok=True)
    e2e_specs = {
        "legacy-cust0002": {
            "request": MUXER_DIR
            / "config"
            / "customer-requests"
            / "migrated"
            / "legacy-cust0002.yaml",
            "out_dir": e2e_root / "legacy-cust0002",
        },
        "vpn-customer-stage1-15-cust-0004": {
            "request": MUXER_DIR
            / "config"
            / "customer-requests"
            / "migrated"
            / "vpn-customer-stage1-15-cust-0004.yaml",
            "observation": MUXER_DIR
            / "config"
            / "customer-requests"
            / "migrated"
            / "vpn-customer-stage1-15-cust-0004-nat-t-observation.json",
            "out_dir": e2e_root / "vpn-customer-stage1-15-cust-0004",
        },
    }
    e2e_reports: dict[str, dict] = {}
    for customer_name, spec in e2e_specs.items():
        e2e_command = [
            "python",
            str(MUXER_DIR / "scripts" / "provision_customer_end_to_end.py"),
            str(spec["request"]),
            "--out-dir",
            str(spec["out_dir"]),
            "--json",
        ]
        if spec.get("observation"):
            e2e_command.extend(["--observation", str(spec["observation"])])
        report = _run_json(e2e_command)
        if report["status"] != "ready_for_review":
            raise SystemExit(f"end-to-end provisioning entrypoint did not produce a ready package: {customer_name}")
        if report["live_apply"] is not False:
            raise SystemExit(f"end-to-end provisioning live_apply guard failed: {customer_name}")
        e2e_reports[customer_name] = {
            "status": report["status"],
            "ready_for_review": report["ready_for_review"],
            "live_apply": report["live_apply"],
            "package_dir": report["package_dir"],
            "readiness_path": report["readiness_path"],
            "dynamic_nat_t_used": report["readiness"]["dynamic_nat_t"]["used"],
        }
    record_step(
        "one_file_end_to_end_provisioning_entrypoint",
        {
            "customers": e2e_reports,
        },
    )

    # Step 3e: verify the Phase 3 dry-run customer deploy orchestrator,
    # including target resolution and backup gating.
    deploy_root = BUILD_ROOT / "deploy-customer"
    if deploy_root.exists():
        shutil.rmtree(deploy_root)
    deploy_root.mkdir(parents=True, exist_ok=True)
    customer2_deploy = _run_json(
        [
            "python",
            str(REPO_ROOT / "scripts" / "customers" / "deploy_customer.py"),
            "--customer-file",
            str(MUXER_DIR / "config" / "customer-requests" / "migrated" / "legacy-cust0002.yaml"),
            "--environment",
            "example-rpdb",
            "--out-dir",
            str(deploy_root / "legacy-cust0002"),
            "--dry-run",
            "--json",
        ]
    )
    if customer2_deploy.get("status") != "dry_run_ready":
        raise SystemExit("Customer 2 dry-run deploy orchestration failed")
    if customer2_deploy.get("live_apply") is not False:
        raise SystemExit("Customer 2 dry-run deploy attempted live apply")
    if (customer2_deploy.get("selected_targets") or {}).get("headend_family") != "non_nat":
        raise SystemExit("Customer 2 dry-run did not select non-NAT head end")
    if ((customer2_deploy.get("dry_run_gate") or {}).get("status")) != "dry_run_ready":
        raise SystemExit("Customer 2 dry-run gate did not report dry_run_ready")

    customer4_deploy = _run_json(
        [
            "python",
            str(REPO_ROOT / "scripts" / "customers" / "deploy_customer.py"),
            "--customer-file",
            str(
                MUXER_DIR
                / "config"
                / "customer-requests"
                / "migrated"
                / "vpn-customer-stage1-15-cust-0004.yaml"
            ),
            "--environment",
            "example-rpdb",
            "--observation",
            str(
                MUXER_DIR
                / "config"
                / "customer-requests"
                / "migrated"
                / "vpn-customer-stage1-15-cust-0004-nat-t-observation.json"
            ),
            "--out-dir",
            str(deploy_root / "vpn-customer-stage1-15-cust-0004"),
            "--dry-run",
            "--json",
        ]
    )
    if customer4_deploy.get("status") != "dry_run_ready":
        raise SystemExit("Customer 4 NAT-T dry-run deploy orchestration failed")
    if customer4_deploy.get("live_apply") is not False:
        raise SystemExit("Customer 4 dry-run deploy attempted live apply")
    if (customer4_deploy.get("selected_targets") or {}).get("headend_family") != "nat":
        raise SystemExit("Customer 4 NAT-T dry-run did not select NAT head end")
    if ((customer4_deploy.get("dry_run_gate") or {}).get("status")) != "dry_run_ready":
        raise SystemExit("Customer 4 NAT-T dry-run gate did not report dry_run_ready")

    blocked_environment = yaml.safe_load(
        (MUXER_DIR / "config" / "deployment-environments" / "example-rpdb.yaml").read_text(
            encoding="utf-8"
        )
    )
    blocked_environment["customer_requests"]["blocked_customers"].append("phase2-blocked-smoke")
    blocked_environment_path = deploy_root / "phase2-blocked-environment.yaml"
    _write_yaml(blocked_environment_path, blocked_environment)
    blocked_request = yaml.safe_load(
        (MUXER_DIR / "config" / "customer-requests" / "migrated" / "legacy-cust0002.yaml").read_text(
            encoding="utf-8"
        )
    )
    blocked_request["customer"]["name"] = "phase2-blocked-smoke"
    blocked_request_path = deploy_root / "phase2-blocked-request.yaml"
    _write_yaml(blocked_request_path, blocked_request)
    blocked_completed = subprocess.run(
        [
            "python",
            str(REPO_ROOT / "scripts" / "customers" / "deploy_customer.py"),
            "--customer-file",
            str(blocked_request_path),
            "--environment",
            str(blocked_environment_path),
            "--out-dir",
            str(deploy_root / "phase2-blocked-smoke"),
            "--dry-run",
            "--json",
        ],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if blocked_completed.returncode == 0:
        raise SystemExit("synthetic blocked customer dry-run did not fail")
    blocked_report = json.loads(blocked_completed.stdout)
    if blocked_report.get("status") != "blocked":
        raise SystemExit("synthetic blocked customer dry-run did not report blocked")
    missing_backup_environment = yaml.safe_load(
        (MUXER_DIR / "config" / "deployment-environments" / "example-rpdb.yaml").read_text(
            encoding="utf-8"
        )
    )
    missing_backup_environment["backups"]["nat_headend"] = "missing"
    missing_backup_environment_path = deploy_root / "phase3-missing-backup-environment.yaml"
    _write_yaml(missing_backup_environment_path, missing_backup_environment)
    missing_backup_completed = subprocess.run(
        [
            "python",
            str(REPO_ROOT / "scripts" / "customers" / "deploy_customer.py"),
            "--customer-file",
            str(
                MUXER_DIR
                / "config"
                / "customer-requests"
                / "migrated"
                / "vpn-customer-stage1-15-cust-0004.yaml"
            ),
            "--environment",
            str(missing_backup_environment_path),
            "--observation",
            str(
                MUXER_DIR
                / "config"
                / "customer-requests"
                / "migrated"
                / "vpn-customer-stage1-15-cust-0004-nat-t-observation.json"
            ),
            "--out-dir",
            str(deploy_root / "phase3-missing-backup"),
            "--dry-run",
            "--json",
        ],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if missing_backup_completed.returncode == 0:
        raise SystemExit("missing backup dry-run did not fail")
    missing_backup_report = json.loads(missing_backup_completed.stdout)
    if missing_backup_report.get("status") != "blocked":
        raise SystemExit("missing backup dry-run did not report blocked")
    if ((missing_backup_report.get("dry_run_gate") or {}).get("status")) != "blocked":
        raise SystemExit("missing backup dry-run gate did not report blocked")
    invalid_env_completed = subprocess.run(
        [
            "python",
            str(REPO_ROOT / "scripts" / "customers" / "deploy_customer.py"),
            "--customer-file",
            str(MUXER_DIR / "config" / "customer-requests" / "migrated" / "legacy-cust0002.yaml"),
            "--environment",
            "missing-rpdb-environment",
            "--out-dir",
            str(deploy_root / "invalid-environment"),
            "--dry-run",
            "--json",
        ],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if invalid_env_completed.returncode == 0:
        raise SystemExit("invalid deployment environment dry-run did not fail")
    invalid_env_report = json.loads(invalid_env_completed.stdout)
    if invalid_env_report.get("status") != "blocked":
        raise SystemExit("invalid deployment environment dry-run did not report blocked")
    record_step(
        "dry_run_target_resolution_and_backup_gate",
        {
            "customer2_status": customer2_deploy["status"],
            "customer2_headend_family": customer2_deploy["selected_targets"]["headend_family"],
            "customer2_gate": customer2_deploy["dry_run_gate"]["status"],
            "customer4_status": customer4_deploy["status"],
            "customer4_headend_family": customer4_deploy["selected_targets"]["headend_family"],
            "customer4_gate": customer4_deploy["dry_run_gate"]["status"],
            "synthetic_blocked_status": blocked_report["status"],
            "missing_backup_status": missing_backup_report["status"],
            "missing_backup_gate": missing_backup_report["dry_run_gate"]["status"],
            "invalid_environment_status": invalid_env_report["status"],
            "live_apply": False,
        },
    )

    # Step 3f: verify automated NAT-T log watching can detect UDP/4500,
    # correlate it to a customer request, and launch the one-file provisioning
    # workflow without touching live systems.
    watcher_root = BUILD_ROOT / "ntw"
    if watcher_root.exists():
        shutil.rmtree(watcher_root)
    watcher_root.mkdir(parents=True, exist_ok=True)
    watcher_log = watcher_root / "l.jsonl"
    _write_text(
        watcher_log,
        "\n".join(
            [
                json.dumps(
                    {
                        "observed_peer": "3.237.201.84",
                        "observed_protocol": "udp",
                        "observed_dport": 500,
                        "observed_at": "2026-04-15T22:45:00Z",
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "observed_peer": "3.237.201.84",
                        "observed_protocol": "udp",
                        "observed_dport": 4500,
                        "observed_at": "2026-04-15T22:45:02Z",
                    },
                    sort_keys=True,
                ),
            ]
        ),
    )
    watcher_env_path = watcher_root / "e.yaml"
    _build_staged_live_environment(
        watcher_env_path,
        name="repo-verification-phase8-watcher",
        root=watcher_root / "roots",
    )
    watcher_command = [
        "python",
        str(MUXER_DIR / "scripts" / "watch_nat_t_logs.py"),
        "--customer-request",
        str(
            MUXER_DIR
            / "config"
            / "customer-requests"
            / "migrated"
            / "vpn-customer-stage1-15-cust-0004.yaml"
        ),
        "--log-file",
        str(watcher_log),
        "--out-dir",
        str(watcher_root / "o"),
        "--state-file",
        str(watcher_root / "s.json"),
        "--package-root",
        str(watcher_root / "p"),
        "--environment",
        str(watcher_env_path),
        "--run-provisioning",
        "--approve",
        "--json",
    ]
    watcher_report = _run_json(watcher_command)
    if watcher_report["detected_count"] != 1:
        raise SystemExit("NAT-T watcher did not detect exactly one promotion event")
    detected = watcher_report["detected"][0]
    provisioning = detected.get("provisioning") or {}
    provisioning_json = provisioning.get("json") or {}
    if provisioning.get("mode") != "deploy_customer":
        raise SystemExit("NAT-T watcher did not call the customer deploy orchestrator")
    if provisioning_json.get("status") != "applied":
        raise SystemExit("NAT-T watcher orchestrator flow did not apply the staged customer")
    if provisioning_json.get("live_apply") is not True:
        raise SystemExit("NAT-T watcher orchestrator flow did not enter the approved staged path")

    second_pass = _run_json(watcher_command)
    if second_pass["detected_count"] != 0:
        raise SystemExit("NAT-T watcher was not idempotent on second pass")
    record_step(
        "automated_nat_t_log_watcher",
        {
            "detected_customer": detected["customer_name"],
            "observation": detected["observation"],
            "environment_file": str(watcher_env_path),
            "deploy_mode": provisioning["mode"],
            "deploy_status": provisioning_json["status"],
            "live_apply": provisioning_json["live_apply"],
            "second_pass_detected_count": second_pass["detected_count"],
            "watch_summary": watcher_report["out_dir"] + "/watch-summary.json",
        },
    )

    # Step 4: verify the allocation DDB item view and the bootstrap plan now include resource allocations.
    allocation_item_counts = {
        name: len(result["allocation_ddb_items"])
        for name, result in provision_results.items()
    }
    bootstrap_report = _run_json(
        ["python", str(REPO_ROOT / "scripts" / "platform" / "ensure_dynamodb_tables.py"), "--json"]
    )
    if "resource_allocations" not in bootstrap_report:
        raise SystemExit("database bootstrap report is missing resource_allocations")
    record_step(
        "allocation_tracking_model",
        {
            "allocation_ddb_items": allocation_item_counts,
            "resource_allocation_table": bootstrap_report["resource_allocations"]["table_name"],
        },
    )

    empty_platform_readiness = _run_json(
        [
            "python",
            str(REPO_ROOT / "scripts" / "platform" / "verify_empty_platform_readiness.py"),
            "--prepare-params",
            "--json",
        ]
    )
    if not empty_platform_readiness.get("ready"):
        raise SystemExit("empty platform readiness wrapper did not report ready")
    record_step(
        "empty_platform_readiness_gate",
        {
            "ready": empty_platform_readiness["ready"],
            "prepared_dir": empty_platform_readiness["prepared_dir"],
            "baseline_dir": empty_platform_readiness["baseline_dir"],
            "customer_sot_table": (
                ((empty_platform_readiness.get("checks") or {}).get("database") or {}).get("customer_sot") or {}
            ).get("table_name"),
        },
    )

    # Step 5: stage the provisioned modules for runtime-only verification.
    staged_dir = BUILD_ROOT / "staged"
    if staged_dir.exists():
        shutil.rmtree(staged_dir)
    staged_dir.mkdir(parents=True, exist_ok=True)
    module_root = _stage_customer_modules(staged_dir, provision_results)
    pass_cfg_path, term_cfg_path = _stage_runtime_configs(staged_dir)
    record_step(
        "staged_runtime_inputs",
        {
            "customer_module_dir": str(module_root),
            "pass_through_config": str(pass_cfg_path),
            "termination_config": str(term_cfg_path),
        },
    )

    # Step 6: verify customer-scoped runtime load against the staged modules.
    runtime_load_code = textwrap.dedent(
        """
        import ipaddress
        import json
        import os
        from pathlib import Path
        from muxerlib.core import load_yaml
        from muxerlib.variables import load_module

        cfg_path = Path(os.environ["RPDB_VERIFY_CFG"])
        module_dir = Path(os.environ["RPDB_VERIFY_MODULE_DIR"])
        selector = os.environ["RPDB_VERIFY_SELECTOR"]
        global_cfg = load_yaml(cfg_path)
        overlay_pool = ipaddress.ip_network(str(global_cfg["overlay_pool"]), strict=False)
        module = load_module(
            selector,
            overlay_pool,
            cfg_dir=module_dir,
            customer_modules_dir=module_dir,
            customers_vars_path=module_dir / "customers.variables.yaml",
            global_cfg=global_cfg,
            source_backend="customer_modules",
            allow_scan_fallback=False,
        )
        print(json.dumps({
            "name": module["name"],
            "backend_role": module.get("backend_role"),
            "backend_underlay_ip": module.get("backend_underlay_ip"),
            "rpdb_priority": module.get("rpdb_priority"),
        }))
        """
    )
    runtime_load_result = _run_python_json(
        runtime_load_code,
        pythonpath=RUNTIME_SRC,
        extra_env={
            "RPDB_VERIFY_CFG": str(pass_cfg_path),
            "RPDB_VERIFY_MODULE_DIR": str(module_root),
            "RPDB_VERIFY_SELECTOR": "example-minimal-nonnat",
        },
    )
    record_step("runtime_single_customer_load", runtime_load_result)

    # Step 7: verify customer-scoped delta apply/remove in pass-through mode without full chain flush.
    delta_apply_code = textwrap.dedent(
        """
        import builtins
        import ipaddress
        import json
        import os
        from pathlib import Path
        from muxerlib.core import load_yaml
        from muxerlib.variables import load_module
        import muxerlib.modes as modes

        cfg_path = Path(os.environ["RPDB_VERIFY_CFG"])
        module_dir = Path(os.environ["RPDB_VERIFY_MODULE_DIR"])
        global_cfg = load_yaml(cfg_path)
        overlay_pool = ipaddress.ip_network(str(global_cfg["overlay_pool"]), strict=False)
        module = load_module(
            "example-minimal-nonnat",
            overlay_pool,
            cfg_dir=module_dir,
            customer_modules_dir=module_dir,
            customers_vars_path=module_dir / "customers.variables.yaml",
            global_cfg=global_cfg,
            source_backend="customer_modules",
            allow_scan_fallback=False,
        )

        counts = {
            "flush_chain": 0,
            "delete_peer_rules": 0,
            "ensure_policy": 0,
            "remove_policy": 0,
            "remove_tunnel": 0,
            "must": 0,
        }

        modes.ensure_chain = lambda *args, **kwargs: None
        modes.ensure_jump = lambda *args, **kwargs: None
        modes.remove_jump = lambda *args, **kwargs: None
        modes.ensure_iptables_rule = lambda *args, **kwargs: None
        modes.ensure_local_ipv4 = lambda *args, **kwargs: None
        modes.remove_local_ipv4 = lambda *args, **kwargs: None
        modes.ensure_tunnel = lambda *args, **kwargs: None
        modes.flush_chain = lambda *args, **kwargs: counts.__setitem__("flush_chain", counts["flush_chain"] + 1)
        modes.delete_iptables_rules_by_peer = lambda *args, **kwargs: counts.__setitem__("delete_peer_rules", counts["delete_peer_rules"] + 1) or 1
        modes.ensure_policy = lambda *args, **kwargs: counts.__setitem__("ensure_policy", counts["ensure_policy"] + 1)
        modes.remove_policy = lambda *args, **kwargs: counts.__setitem__("remove_policy", counts["remove_policy"] + 1)
        modes.flush_route_table = lambda *args, **kwargs: None
        modes.remove_tunnel = lambda *args, **kwargs: counts.__setitem__("remove_tunnel", counts["remove_tunnel"] + 1)
        modes.must = lambda *args, **kwargs: counts.__setitem__("must", counts["must"] + 1)
        builtins.print = lambda *args, **kwargs: None

        modes.apply_customer_passthrough(
            module,
            pub_if="ens34",
            inside_if="ens35",
            public_ip=str(global_cfg["public_ip"]),
            public_priv_ip=str((global_cfg.get("interfaces") or {}).get("public_private_ip") or global_cfg["public_ip"]),
            inside_ip=str((global_cfg.get("interfaces") or {}).get("inside_ip")),
            backend_ul=str(global_cfg.get("backend_underlay_ip") or "172.31.40.220"),
            transport_local_mode="interface_ip",
            overlay_pool=overlay_pool,
            base_table=int((global_cfg.get("allocation") or {}).get("base_table", 2000)),
            base_mark=int(str((global_cfg.get("allocation") or {}).get("base_mark", "0x2000")), 0),
            mangle_chain="MUXER_MANGLE",
            filter_chain="MUXER_FILTER",
            nat_rewrite=True,
            nat_pre_chain="MUXER_NAT_PRE",
            nat_post_chain="MUXER_NAT_POST",
            mangle_post_chain="MUXER_MANGLE_POST",
            nfqueue_enabled=False,
            nfqueue_queue_in=2101,
            nfqueue_queue_out=2102,
            nfqueue_queue_bypass=True,
            natd_dpi_enabled=False,
            natd_dpi_queue_in=2111,
            natd_dpi_queue_out=2112,
            natd_dpi_queue_bypass=True,
            default_drop=True,
        )
        modes.remove_customer_passthrough(
            module,
            inside_if="ens35",
            inside_ip=str((global_cfg.get("interfaces") or {}).get("inside_ip")),
            transport_local_mode="interface_ip",
            base_table=int((global_cfg.get("allocation") or {}).get("base_table", 2000)),
            base_mark=int(str((global_cfg.get("allocation") or {}).get("base_mark", "0x2000")), 0),
            mangle_chain="MUXER_MANGLE",
            mangle_post_chain="MUXER_MANGLE_POST",
            filter_chain="MUXER_FILTER",
            nat_pre_chain="MUXER_NAT_PRE",
            nat_post_chain="MUXER_NAT_POST",
        )
        import sys
        sys.stdout.write(json.dumps(counts))
        """
    )
    delta_apply_result = _run_python_json(
        delta_apply_code,
        pythonpath=RUNTIME_SRC,
        extra_env={
            "RPDB_VERIFY_CFG": str(pass_cfg_path),
            "RPDB_VERIFY_MODULE_DIR": str(module_root),
        },
    )
    if delta_apply_result["flush_chain"] != 0:
        raise SystemExit("customer-scoped delta apply unexpectedly flushed chains")
    record_step("pass_through_delta_apply_remove", delta_apply_result)

    # Step 8: verify the termination-mode guard remains explicit.
    termination_guard_code = textwrap.dedent(
        """
        import json
        import os
        import sys
        from pathlib import Path
        import muxerlib.cli as cli

        cfg_path = Path(os.environ["RPDB_VERIFY_CFG"])
        module_path = Path(os.environ["RPDB_VERIFY_MODULE"])
        cli.CFG_GLOBAL = cfg_path
        cli.CFG_DIR = module_path.parent
        cli.ensure_sysctl = lambda: None
        cli.load_module = lambda *args, **kwargs: json.loads(module_path.read_text(encoding="utf-8"))
        sys.argv = ["muxctl.py", "apply-customer", "example-minimal-nonnat"]
        try:
            cli.main()
        except SystemExit as exc:
            print(json.dumps({"message": str(exc)}))
            raise
        """
    )
    module_path = module_root / "example-minimal-nonnat" / "customer-module.json"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(RUNTIME_SRC)
    env["RPDB_VERIFY_CFG"] = str(term_cfg_path)
    env["RPDB_VERIFY_MODULE"] = str(module_path)
    completed = subprocess.run(
        ["python", "-c", termination_guard_code],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    if completed.returncode == 0:
        raise SystemExit("termination guard verification unexpectedly succeeded")
    termination_payload = json.loads(completed.stdout or "{}")
    record_step("termination_mode_boundary", termination_payload)

    # Step 9: verify the first batched nftables render path.
    nft_model = _run_json(
        [
            "python",
            str(RUNTIME_ROOT / "scripts" / "render_nft_passthrough.py"),
            "--global-config",
            str(pass_cfg_path),
            "--customer-module-dir",
            str(module_root),
            "--json",
        ],
        env={**os.environ, "PYTHONPATH": str(RUNTIME_SRC)},
    )
    nft_script = _run(
        [
            "python",
            str(RUNTIME_ROOT / "scripts" / "render_nft_passthrough.py"),
            "--global-config",
            str(pass_cfg_path),
            "--customer-module-dir",
            str(module_root),
        ],
        env={**os.environ, "PYTHONPATH": str(RUNTIME_SRC)},
    ).stdout
    if "table inet muxer_passthrough" not in nft_script:
        raise SystemExit("nftables render did not produce the expected table header")
    record_step(
        "nftables_batch_render",
        {
            "customer_count": nft_model["customer_count"],
            "script_lines": len(nft_script.splitlines()),
            "table_name": nft_model["table"]["name"],
        },
    )

    # Step 10: verify the customer-scoped head-end staging/apply/remove flow
    # against staged filesystem roots, including the richer VPN service intent
    # examples for one-to-one netmap and explicit host mapping.
    # Keep these paths intentionally short so Windows repo verification does
    # not fail on long staged artifact paths for descriptive customer names.
    headend_stage_dir = BUILD_ROOT / "he"
    if headend_stage_dir.exists():
        shutil.rmtree(headend_stage_dir)
    headend_stage_dir.mkdir(parents=True, exist_ok=True)
    environment_file = MUXER_DIR / "config" / "environment-defaults" / "example-environment.yaml"
    headend_targets = [
        "example-minimal-nonnat",
        "example-service-intent-netmap",
        "example-service-intent-explicit-host-map",
    ]
    headend_reports: dict[str, dict] = {}
    for idx, customer_name in enumerate(headend_targets, start=1):
        customer_stage_dir = headend_stage_dir / f"c{idx}"
        source_path = customer_stage_dir / "customer.yaml"
        export_dir = customer_stage_dir / "x"
        bound_dir = customer_stage_dir / "y"
        bundle_dir = customer_stage_dir / "b"
        headend_root = customer_stage_dir / "r"
        _write_yaml(source_path, provision_results[customer_name]["customer_source"])

        _run(
            [
                "python",
                str(MUXER_DIR / "scripts" / "export_customer_handoff.py"),
                str(source_path),
                "--export-dir",
                str(export_dir),
            ]
        )
        _run(
            [
                "python",
                str(MUXER_DIR / "scripts" / "bind_rendered_artifacts.py"),
                str(export_dir),
                "--environment-file",
                str(environment_file),
                "--out-dir",
                str(bound_dir),
            ]
        )
        _run(
            [
                "python",
                str(REPO_ROOT / "scripts" / "packaging" / "assemble_customer_bundle.py"),
                "--customer-name",
                customer_name,
                "--export-dir",
                str(bound_dir),
                "--bundle-dir",
                str(bundle_dir),
            ]
        )
        bundle_validation = _run_json(
            [
                "python",
                str(REPO_ROOT / "scripts" / "packaging" / "validate_customer_bundle.py"),
                str(bundle_dir),
                "--json",
            ]
        )
        if not bundle_validation.get("valid"):
            raise SystemExit(f"customer bundle validation failed during repo verification: {customer_name}")
        headend_bundle_validation = _run_json(
            [
                "python",
                str(REPO_ROOT / "scripts" / "deployment" / "validate_headend_customer.py"),
                "--bundle-dir",
                str(bundle_dir),
                "--json",
            ]
        )
        if not headend_bundle_validation.get("valid"):
            raise SystemExit(f"head-end bundle validation failed during repo verification: {customer_name}")
        _run(
            [
                "python",
                str(REPO_ROOT / "scripts" / "deployment" / "apply_headend_customer.py"),
                "--bundle-dir",
                str(bundle_dir),
                "--headend-root",
                str(headend_root),
            ]
        )
        installed_headend_validation = _run_json(
            [
                "python",
                str(REPO_ROOT / "scripts" / "deployment" / "validate_headend_customer.py"),
                "--bundle-dir",
                str(bundle_dir),
                "--headend-root",
                str(headend_root),
                "--json",
            ]
        )
        if not installed_headend_validation.get("valid"):
            raise SystemExit(f"installed head-end validation failed during repo verification: {customer_name}")
        removal_report = _run_json(
            [
                "python",
                str(REPO_ROOT / "scripts" / "deployment" / "remove_headend_customer.py"),
                "--bundle-dir",
                str(bundle_dir),
                "--headend-root",
                str(headend_root),
                "--json",
            ]
        )
        installed_root = headend_root / "var" / "lib" / "rpdb-headend" / "customers" / customer_name
        staged_conf = headend_root / "etc" / "swanctl" / "conf.d" / "rpdb-customers" / f"{customer_name}.conf"
        if installed_root.exists() or staged_conf.exists():
            raise SystemExit(f"head-end remove left installed customer state behind: {customer_name}")

        details = headend_bundle_validation["details"]
        headend_reports[customer_name] = {
            "bundle_dir": str(bundle_dir),
            "headend_root": str(headend_root),
            "route_command_count": details["route_command_count"],
            "post_ipsec_nat_command_count": details["post_ipsec_nat_command_count"],
            "post_ipsec_nat_mapping_strategy": details["post_ipsec_nat_mapping_strategy"],
            "post_ipsec_nat_command_model": details["post_ipsec_nat_command_model"],
            "ipsec_ike_version": details["ipsec_ike_version"],
            "installed_swanctl_conf": installed_headend_validation["details"]["installed_swanctl_conf"],
            "removed_paths": len(removal_report["removed_paths"]),
        }
    record_step(
        "headend_customer_orchestration",
        {
            "customers": headend_reports,
        },
    )

    # Step 11: prove staged backend, muxer, and selected head-end installs can
    # coexist per customer, and that rollback removes only the target customer.
    phase4_stage_dir = BUILD_ROOT / "phase4"
    if phase4_stage_dir.exists():
        shutil.rmtree(phase4_stage_dir)
    phase4_stage_dir.mkdir(parents=True, exist_ok=True)
    backend_root = phase4_stage_dir / "be"
    muxer_root = phase4_stage_dir / "mx"
    non_nat_headend_root = phase4_stage_dir / "hn"
    nat_headend_root = phase4_stage_dir / "ht"

    customer2_package_dir = _resolve_repo_path(str(customer2_deploy["package"]["package_dir"]))
    customer4_package_dir = _resolve_repo_path(str(customer4_deploy["package"]["package_dir"]))
    phase4_specs = {
        "legacy-cust0002": {
            "package_dir": customer2_package_dir,
            "bundle_dir": customer2_package_dir / "bundle",
            "headend_root": non_nat_headend_root,
        },
        "vpn-customer-stage1-15-cust-0004": {
            "package_dir": customer4_package_dir,
            "bundle_dir": customer4_package_dir / "bundle",
            "headend_root": nat_headend_root,
        },
    }

    def _phase4_validate(customer_name: str) -> dict[str, dict]:
        spec = phase4_specs[customer_name]
        backend_validation = _run_json(
            [
                "python",
                str(REPO_ROOT / "scripts" / "deployment" / "validate_backend_customer.py"),
                "--package-dir",
                str(spec["package_dir"]),
                "--backend-root",
                str(backend_root),
                "--json",
            ]
        )
        if not backend_validation.get("valid"):
            raise SystemExit(f"installed backend validation failed during repo verification: {customer_name}")

        muxer_validation = _run_json(
            [
                "python",
                str(REPO_ROOT / "scripts" / "deployment" / "validate_muxer_customer.py"),
                "--bundle-dir",
                str(spec["bundle_dir"]),
                "--muxer-root",
                str(muxer_root),
                "--json",
            ]
        )
        if not muxer_validation.get("valid"):
            raise SystemExit(f"installed muxer validation failed during repo verification: {customer_name}")

        headend_validation = _run_json(
            [
                "python",
                str(REPO_ROOT / "scripts" / "deployment" / "validate_headend_customer.py"),
                "--bundle-dir",
                str(spec["bundle_dir"]),
                "--headend-root",
                str(spec["headend_root"]),
                "--json",
            ]
        )
        if not headend_validation.get("valid"):
            raise SystemExit(f"installed head-end validation failed during repo verification: {customer_name}")

        return {
            "backend": backend_validation,
            "muxer": muxer_validation,
            "headend": headend_validation,
        }

    def _phase4_apply(customer_name: str) -> dict[str, dict]:
        spec = phase4_specs[customer_name]
        backend_bundle_validation = _run_json(
            [
                "python",
                str(REPO_ROOT / "scripts" / "deployment" / "validate_backend_customer.py"),
                "--package-dir",
                str(spec["package_dir"]),
                "--json",
            ]
        )
        if not backend_bundle_validation.get("valid"):
            raise SystemExit(f"backend package validation failed during repo verification: {customer_name}")

        muxer_bundle_validation = _run_json(
            [
                "python",
                str(REPO_ROOT / "scripts" / "deployment" / "validate_muxer_customer.py"),
                "--bundle-dir",
                str(spec["bundle_dir"]),
                "--json",
            ]
        )
        if not muxer_bundle_validation.get("valid"):
            raise SystemExit(f"muxer bundle validation failed during repo verification: {customer_name}")

        headend_bundle_validation = _run_json(
            [
                "python",
                str(REPO_ROOT / "scripts" / "deployment" / "validate_headend_customer.py"),
                "--bundle-dir",
                str(spec["bundle_dir"]),
                "--json",
            ]
        )
        if not headend_bundle_validation.get("valid"):
            raise SystemExit(f"head-end bundle validation failed during repo verification: {customer_name}")

        backend_apply = _run_json(
            [
                "python",
                str(REPO_ROOT / "scripts" / "deployment" / "apply_backend_customer.py"),
                "--package-dir",
                str(spec["package_dir"]),
                "--backend-root",
                str(backend_root),
                "--json",
            ]
        )
        muxer_apply = _run_json(
            [
                "python",
                str(REPO_ROOT / "scripts" / "deployment" / "apply_muxer_customer.py"),
                "--bundle-dir",
                str(spec["bundle_dir"]),
                "--muxer-root",
                str(muxer_root),
                "--json",
            ]
        )
        headend_apply = _run_json(
            [
                "python",
                str(REPO_ROOT / "scripts" / "deployment" / "apply_headend_customer.py"),
                "--bundle-dir",
                str(spec["bundle_dir"]),
                "--headend-root",
                str(spec["headend_root"]),
                "--json",
            ]
        )
        installed = _phase4_validate(customer_name)
        return {
            "bundle_backend": backend_bundle_validation,
            "bundle_muxer": muxer_bundle_validation,
            "bundle_headend": headend_bundle_validation,
            "apply_backend": backend_apply,
            "apply_muxer": muxer_apply,
            "apply_headend": headend_apply,
            "installed": installed,
        }

    def _phase4_remove(customer_name: str) -> dict[str, dict]:
        spec = phase4_specs[customer_name]
        return {
            "backend": _run_json(
                [
                    "python",
                    str(REPO_ROOT / "scripts" / "deployment" / "remove_backend_customer.py"),
                    "--customer-name",
                    customer_name,
                    "--backend-root",
                    str(backend_root),
                    "--json",
                ]
            ),
            "muxer": _run_json(
                [
                    "python",
                    str(REPO_ROOT / "scripts" / "deployment" / "remove_muxer_customer.py"),
                    "--customer-name",
                    customer_name,
                    "--muxer-root",
                    str(muxer_root),
                    "--json",
                ]
            ),
            "headend": _run_json(
                [
                    "python",
                    str(REPO_ROOT / "scripts" / "deployment" / "remove_headend_customer.py"),
                    "--customer-name",
                    customer_name,
                    "--headend-root",
                    str(spec["headend_root"]),
                    "--json",
                ]
            ),
        }

    def _phase4_assert_customer_absent(customer_name: str) -> None:
        for path in (
            backend_root / "var" / "lib" / "rpdb-backend" / "customers" / customer_name,
            backend_root / "var" / "lib" / "rpdb-backend" / "allocations" / customer_name,
            muxer_root / "var" / "lib" / "rpdb-muxer" / "customers" / customer_name,
            muxer_root / "etc" / "muxer" / "customer-modules" / customer_name,
            non_nat_headend_root / "var" / "lib" / "rpdb-headend" / "customers" / customer_name,
            nat_headend_root / "var" / "lib" / "rpdb-headend" / "customers" / customer_name,
        ):
            if path.exists():
                raise SystemExit(f"staged rollback left customer state behind: {path}")

    phase4_reports: dict[str, dict] = {}
    customer2_first_apply = _phase4_apply("legacy-cust0002")
    _phase4_assert_customer_absent("vpn-customer-stage1-15-cust-0004")
    customer2_second_apply = _phase4_apply("legacy-cust0002")
    customer4_first_apply = _phase4_apply("vpn-customer-stage1-15-cust-0004")
    customer4_second_apply = _phase4_apply("vpn-customer-stage1-15-cust-0004")
    customer4_remove = _phase4_remove("vpn-customer-stage1-15-cust-0004")
    _phase4_assert_customer_absent("vpn-customer-stage1-15-cust-0004")
    customer2_after_customer4_remove = _phase4_validate("legacy-cust0002")
    customer2_remove = _phase4_remove("legacy-cust0002")
    _phase4_assert_customer_absent("legacy-cust0002")

    phase4_reports["legacy-cust0002"] = {
        "first_apply": {
            "backend_root": customer2_first_apply["installed"]["backend"]["details"]["installed_customer_root"],
            "allocation_root": customer2_first_apply["installed"]["backend"]["details"]["installed_allocation_root"],
            "muxer_root": customer2_first_apply["installed"]["muxer"]["details"]["installed_root"],
            "headend_root": customer2_first_apply["installed"]["headend"]["details"]["installed_root"],
            "allocation_count": customer2_first_apply["bundle_backend"]["details"]["allocation_count"],
            "route_command_count": customer2_first_apply["bundle_headend"]["details"]["route_command_count"],
            "firewall_command_count": customer2_first_apply["bundle_muxer"]["details"]["firewall_command_count"],
        },
        "idempotent_reapply": {
            "backend_root": customer2_second_apply["installed"]["backend"]["details"]["installed_customer_root"],
            "muxer_root": customer2_second_apply["installed"]["muxer"]["details"]["installed_root"],
            "headend_root": customer2_second_apply["installed"]["headend"]["details"]["installed_root"],
        },
        "final_cleanup": {
            "backend_removed_paths": len(customer2_remove["backend"]["removed_paths"]),
            "muxer_removed_paths": len(customer2_remove["muxer"]["removed_paths"]),
            "headend_removed_paths": len(customer2_remove["headend"]["removed_paths"]),
        },
    }
    phase4_reports["vpn-customer-stage1-15-cust-0004"] = {
        "first_apply": {
            "backend_root": customer4_first_apply["installed"]["backend"]["details"]["installed_customer_root"],
            "allocation_root": customer4_first_apply["installed"]["backend"]["details"]["installed_allocation_root"],
            "muxer_root": customer4_first_apply["installed"]["muxer"]["details"]["installed_root"],
            "headend_root": customer4_first_apply["installed"]["headend"]["details"]["installed_root"],
            "allocation_count": customer4_first_apply["bundle_backend"]["details"]["allocation_count"],
            "route_command_count": customer4_first_apply["bundle_headend"]["details"]["route_command_count"],
            "firewall_command_count": customer4_first_apply["bundle_muxer"]["details"]["firewall_command_count"],
        },
        "idempotent_reapply": {
            "backend_root": customer4_second_apply["installed"]["backend"]["details"]["installed_customer_root"],
            "muxer_root": customer4_second_apply["installed"]["muxer"]["details"]["installed_root"],
            "headend_root": customer4_second_apply["installed"]["headend"]["details"]["installed_root"],
        },
        "targeted_rollback": {
            "backend_removed_paths": len(customer4_remove["backend"]["removed_paths"]),
            "muxer_removed_paths": len(customer4_remove["muxer"]["removed_paths"]),
            "headend_removed_paths": len(customer4_remove["headend"]["removed_paths"]),
            "customer2_still_present": customer2_after_customer4_remove["backend"]["valid"]
            and customer2_after_customer4_remove["muxer"]["valid"]
            and customer2_after_customer4_remove["headend"]["valid"],
        },
    }
    record_step(
        "staged_apply_and_targeted_rollback_gate",
        {
            "backend_root": str(backend_root),
            "muxer_root": str(muxer_root),
            "non_nat_headend_root": str(non_nat_headend_root),
            "nat_headend_root": str(nat_headend_root),
            "customers": phase4_reports,
        },
    )

    phase6_root = BUILD_ROOT / "p6"
    if phase6_root.exists():
        shutil.rmtree(phase6_root)
    phase6_root.mkdir(parents=True, exist_ok=True)
    phase6_env_path = phase6_root / "e.yaml"
    _build_staged_live_environment(
        phase6_env_path,
        name="repo-verification-phase6-staged-live",
        root=phase6_root / "r",
    )
    phase6_env_validation = _run_json(
        [
            "python",
            str(REPO_ROOT / "scripts" / "customers" / "validate_deployment_environment.py"),
            str(phase6_env_path),
            "--allow-live-apply",
            "--json",
        ]
    )
    if not phase6_env_validation.get("valid"):
        raise SystemExit("Phase 6 staged-live environment validation failed")

    phase6_customer2_dry_run = _run_json(
        [
            "python",
            str(REPO_ROOT / "scripts" / "customers" / "deploy_customer.py"),
            "--customer-file",
            str(MUXER_DIR / "config" / "customer-requests" / "migrated" / "legacy-cust0002.yaml"),
            "--environment",
            str(phase6_env_path),
            "--out-dir",
            str(phase6_root / "c2d"),
            "--dry-run",
            "--json",
        ]
    )
    if phase6_customer2_dry_run.get("status") != "dry_run_ready":
        raise SystemExit("Phase 6 Customer 2 staged dry-run did not report dry_run_ready")
    if not ((phase6_customer2_dry_run.get("live_gate") or {}).get("allow_live_apply_now")):
        raise SystemExit("Phase 6 Customer 2 staged dry-run did not become approval-ready")

    phase6_customer2_apply = _run_json(
        [
            "python",
            str(REPO_ROOT / "scripts" / "customers" / "deploy_customer.py"),
            "--customer-file",
            str(MUXER_DIR / "config" / "customer-requests" / "migrated" / "legacy-cust0002.yaml"),
            "--environment",
            str(phase6_env_path),
            "--out-dir",
            str(phase6_root / "c2a"),
            "--approve",
            "--json",
        ]
    )
    if phase6_customer2_apply.get("status") != "applied" or phase6_customer2_apply.get("live_apply") is not True:
        raise SystemExit("Phase 6 Customer 2 staged approved apply did not succeed")
    if (phase6_customer2_apply.get("selected_targets") or {}).get("headend_family") != "non_nat":
        raise SystemExit("Phase 6 Customer 2 staged approved apply chose the wrong head-end family")

    phase6_customer4_apply = _run_json(
        [
            "python",
            str(REPO_ROOT / "scripts" / "customers" / "deploy_customer.py"),
            "--customer-file",
            str(
                MUXER_DIR
                / "config"
                / "customer-requests"
                / "migrated"
                / "vpn-customer-stage1-15-cust-0004.yaml"
            ),
            "--environment",
            str(phase6_env_path),
            "--observation",
            str(
                MUXER_DIR
                / "config"
                / "customer-requests"
                / "migrated"
                / "vpn-customer-stage1-15-cust-0004-nat-t-observation.json"
            ),
            "--out-dir",
            str(phase6_root / "c4a"),
            "--approve",
            "--json",
        ]
    )
    if phase6_customer4_apply.get("status") != "applied" or phase6_customer4_apply.get("live_apply") is not True:
        raise SystemExit("Phase 6 Customer 4 staged approved apply did not succeed")
    if (phase6_customer4_apply.get("selected_targets") or {}).get("headend_family") != "nat":
        raise SystemExit("Phase 6 Customer 4 staged approved apply chose the wrong head-end family")

    phase6_artifacts: dict[str, dict[str, str]] = {}
    for customer_name, report in (
        ("legacy-cust0002", phase6_customer2_apply),
        ("vpn-customer-stage1-15-cust-0004", phase6_customer4_apply),
    ):
        apply = report.get("apply") or {}
        journal_path = _resolve_repo_path(str(apply.get("apply_journal") or ""))
        rollback_plan_path = _resolve_repo_path(str(apply.get("rollback_plan") or ""))
        published_root = _resolve_repo_path(str((apply.get("published_artifacts") or {}).get("run_root") or ""))
        if not journal_path.exists():
            raise SystemExit(f"Phase 6 apply journal missing for {customer_name}")
        if not rollback_plan_path.exists():
            raise SystemExit(f"Phase 6 rollback plan missing for {customer_name}")
        if not published_root.exists():
            raise SystemExit(f"Phase 6 published artifact root missing for {customer_name}")
        phase6_artifacts[customer_name] = {
            "apply_journal": str(journal_path),
            "rollback_plan": str(rollback_plan_path),
            "published_root": str(published_root),
        }
    record_step(
        "approved_staged_live_apply_gate",
        {
            "environment_file": str(phase6_env_path),
            "customer2_status": phase6_customer2_apply["status"],
            "customer2_headend_family": phase6_customer2_apply["selected_targets"]["headend_family"],
            "customer4_status": phase6_customer4_apply["status"],
            "customer4_headend_family": phase6_customer4_apply["selected_targets"]["headend_family"],
            "artifacts": phase6_artifacts,
        },
    )

    phase7_root = BUILD_ROOT / "p7"
    if phase7_root.exists():
        shutil.rmtree(phase7_root)
    phase7_root.mkdir(parents=True, exist_ok=True)
    phase7_env_path = phase7_root / "e.yaml"
    _build_staged_live_environment(
        phase7_env_path,
        name="repo-verification-phase7-auto-rollback",
        root=phase7_root / "r",
    )
    failure_prep = _run_json(
        [
            "python",
            str(REPO_ROOT / "scripts" / "customers" / "deploy_customer.py"),
            "--customer-file",
            str(MUXER_DIR / "config" / "customer-requests" / "migrated" / "legacy-cust0002.yaml"),
            "--environment",
            str(phase7_env_path),
            "--out-dir",
            str(phase7_root / "f"),
            "--dry-run",
            "--json",
        ]
    )
    if failure_prep.get("status") != "dry_run_ready":
        raise SystemExit("Phase 7 failure preparation dry-run did not succeed")
    failure_package_dir = _resolve_repo_path(str((failure_prep.get("package") or {}).get("package_dir") or ""))
    broken_headend_file = failure_package_dir / "bundle" / "headend" / "ipsec" / "swanctl-connection.conf"
    if not broken_headend_file.exists():
        raise SystemExit("Phase 7 failure preparation could not find head-end swanctl bundle input")
    broken_headend_file.unlink()

    phase7_failure_result = _run_python_json(
        textwrap.dedent(
            """
            import json
            import os
            import sys
            from pathlib import Path

            import yaml

            repo_root = Path(os.environ["RPDB_REPO_ROOT"]).resolve()
            sys.path.insert(0, str((repo_root / "scripts" / "customers").resolve()))

            from live_apply_lib import execute_staged_live_apply

            environment_doc = yaml.safe_load(
                Path(os.environ["RPDB_ENVIRONMENT"]).read_text(encoding="utf-8")
            )
            result = execute_staged_live_apply(
                customer_name=os.environ["RPDB_CUSTOMER_NAME"],
                package_dir=Path(os.environ["RPDB_PACKAGE_DIR"]).resolve(),
                bundle_dir=Path(os.environ["RPDB_BUNDLE_DIR"]).resolve(),
                deploy_dir=Path(os.environ["RPDB_DEPLOY_DIR"]).resolve(),
                target_selection=json.loads(os.environ["RPDB_TARGET_SELECTION"]),
                environment_doc=environment_doc,
                execution_plan_path=Path(os.environ["RPDB_EXECUTION_PLAN"]).resolve(),
            )
            print(json.dumps(result))
            """
        ),
        extra_env={
            "RPDB_REPO_ROOT": str(REPO_ROOT),
            "RPDB_ENVIRONMENT": str(phase7_env_path),
            "RPDB_CUSTOMER_NAME": "legacy-cust0002",
            "RPDB_PACKAGE_DIR": str(failure_package_dir),
            "RPDB_BUNDLE_DIR": str(failure_package_dir / "bundle"),
            "RPDB_DEPLOY_DIR": str(phase7_root / "fr"),
            "RPDB_EXECUTION_PLAN": str(_resolve_repo_path(failure_prep["artifacts"]["execution_plan"])),
            "RPDB_TARGET_SELECTION": json.dumps(failure_prep["selected_targets"]),
        },
    )
    if phase7_failure_result.get("status") != "rolled_back":
        raise SystemExit("Phase 7 staged failure did not roll back automatically")
    for path in (
        phase7_root / "r" / "datastores" / "var" / "lib" / "rpdb-backend" / "customers" / "legacy-cust0002",
        phase7_root / "r" / "datastores" / "var" / "lib" / "rpdb-backend" / "allocations" / "legacy-cust0002",
        phase7_root / "r" / "muxer-root" / "var" / "lib" / "rpdb-muxer" / "customers" / "legacy-cust0002",
        phase7_root / "r" / "muxer-root" / "etc" / "muxer" / "customer-modules" / "legacy-cust0002",
        phase7_root / "r" / "nonnat-active-root" / "var" / "lib" / "rpdb-headend" / "customers" / "legacy-cust0002",
        phase7_root / "r" / "nonnat-standby-root" / "var" / "lib" / "rpdb-headend" / "customers" / "legacy-cust0002",
    ):
        if path.exists():
            raise SystemExit(f"Phase 7 auto-rollback left customer state behind: {path}")
    record_step(
        "post_apply_auto_rollback_gate",
        {
            "environment_file": str(phase7_env_path),
            "status": phase7_failure_result["status"],
            "error": phase7_failure_result["error"],
            "rollback_plan": _resolve_repo_path(phase7_failure_result["rollback_plan"]).as_posix(),
            "apply_journal": _resolve_repo_path(phase7_failure_result["apply_journal"]).as_posix(),
        },
    )

    summary_path = BUILD_ROOT / "repo-verification-summary.json"
    _write_json(summary_path, summary)

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(f"Repo verification completed: {len(summary['steps'])} step(s) passed")
        print(f"Summary: {summary_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
