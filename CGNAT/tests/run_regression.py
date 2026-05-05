from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


CGNAT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CGNAT_ROOT.parent
PYTHON = sys.executable


def _run(*command: str) -> None:
    subprocess.run([PYTHON, *command], cwd=str(REPO_ROOT), check=True)


def _compile(*paths: Path) -> None:
    script = (
        "import compileall, sys; "
        "ok = all(compileall.compile_dir(path, quiet=1) for path in sys.argv[1:]); "
        "raise SystemExit(0 if ok else 1)"
    )
    subprocess.run([PYTHON, "-c", script, *[str(path) for path in paths]], cwd=str(REPO_ROOT), check=True)


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _run_json_command(command: list[str]) -> dict:
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    return json.loads(completed.stdout)


def _replace_text(value: object, old: str, new: str) -> object:
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, dict):
        return {key: _replace_text(nested, old, new) for key, nested in value.items()}
    if isinstance(value, list):
        return [_replace_text(nested, old, new) for nested in value]
    return value


def _prepare_staged_customer_request(
    source_path: Path,
    output_path: Path,
    staged_name: str,
    *,
    peer_public_ip: str | None = None,
) -> dict:
    request_doc = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
    customer = request_doc.setdefault("customer", {})
    original_name = str(customer.get("name") or "").strip()
    rewritten = _replace_text(request_doc, original_name, staged_name)
    rewritten_customer = rewritten.setdefault("customer", {})
    rewritten_customer["name"] = staged_name
    if peer_public_ip:
        rewritten_peer = rewritten_customer.setdefault("peer", {})
        rewritten_peer["public_ip"] = peer_public_ip
    output_path.write_text(
        yaml.safe_dump(rewritten, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    return rewritten


def main() -> int:
    regression_root = CGNAT_ROOT / "build" / "regression"
    if regression_root.exists():
        shutil.rmtree(regression_root)
    regression_root.mkdir(parents=True, exist_ok=True)

    sample_bundle = CGNAT_ROOT / "framework" / "config" / "deployment-bundle.example.json"
    live_bundle = CGNAT_ROOT / "framework" / "config" / "deployment-bundle.rpdb-empty-live.json"
    backend_integration = CGNAT_ROOT / "framework" / "config" / "scenario1-backend-integration.rpdb-empty-live.json"
    host_access_strategy = CGNAT_ROOT / "server" / "config" / "host-access-strategy.rpdb-empty-live.json"
    request_examples = REPO_ROOT / "muxer" / "config" / "customer-requests" / "examples"

    sample_prep = regression_root / "sample-prep"
    live_materials = regression_root / "live-demo-materials"
    live_prep = regression_root / "live-prep"
    live_predeploy = regression_root / "live-predeploy-review"
    live_backend = regression_root / "live-backend-integration"
    deployment_stage = regression_root / "deployment-stage-review"
    shared_nonnat = regression_root / "shared-nonnat-package"
    shared_nat = regression_root / "shared-nat-package"
    cgnat_review = regression_root / "cgnat-customer-review"
    cgnat_shared_gateway_review = regression_root / "cgnat-shared-gateway-review"
    cgnat_scenario2_shared_gateway_review = regression_root / "cgnat-scenario2-shared-gateway-review"
    cgnat_customer1_live_review = regression_root / "cgnat-customer1-live-review"
    cgnat_local_pki_review = regression_root / "cgnat-customer-local-pki-review"
    cgnat_staged_apply = regression_root / "cgnat-customer-staged-apply"
    cgnat_shared_gateway_staged_apply = regression_root / "cgnat-shared-gateway-staged-apply"
    cgnat_dual_customer1_staged_apply = regression_root / "cgnat-customer1-staged-apply"
    cgnat_dual_customer2_staged_apply = regression_root / "cgnat-customer2-staged-apply"
    cgnat_staged_request = regression_root / "example-minimal-cgnat-staged-apply.yaml"
    cgnat_shared_gateway_staged_request = regression_root / "example-minimal-cgnat-shared-gateway-staged-apply.yaml"
    cgnat_dual_customer1_request = regression_root / "example-cgnat-customer-1-staged-apply.yaml"
    cgnat_dual_customer2_request = regression_root / "example-cgnat-customer-2-staged-apply.yaml"
    staged_env_path = regression_root / "example-rpdb-staged-live.yaml"

    _run(str(CGNAT_ROOT / "tests" / "run_tests.py"))
    _compile(CGNAT_ROOT)
    _compile(REPO_ROOT / "muxer" / "src", REPO_ROOT / "muxer" / "scripts", REPO_ROOT / "scripts" / "customers")

    _run(
        str(REPO_ROOT / "muxer" / "scripts" / "provision_customer_end_to_end.py"),
        str(request_examples / "example-minimal-nonnat.yaml"),
        "--out-dir",
        str(shared_nonnat),
        "--json",
    )
    _run(
        str(REPO_ROOT / "muxer" / "scripts" / "provision_customer_end_to_end.py"),
        str(request_examples / "example-minimal-nat.yaml"),
        "--out-dir",
        str(shared_nat),
        "--json",
    )
    _run(
        str(CGNAT_ROOT / "framework" / "scripts" / "prepare_cgnat_customer_pilot.py"),
        str(request_examples / "example-minimal-cgnat.yaml"),
        "--environment",
        "rpdb-empty-live",
        "--out-dir",
        str(cgnat_review),
        "--json",
    )
    _run(
        str(CGNAT_ROOT / "framework" / "scripts" / "prepare_cgnat_customer_pilot.py"),
        str(request_examples / "example-cgnat-customer-1-local-pki.yaml"),
        "--environment",
        "rpdb-empty-live",
        "--out-dir",
        str(cgnat_customer1_live_review),
        "--test-bed-customer",
        "CGNAT customer 1",
        "--json",
    )
    _run(
        str(CGNAT_ROOT / "framework" / "scripts" / "prepare_cgnat_customer_pilot.py"),
        str(request_examples / "example-minimal-cgnat-local-pki.yaml"),
        "--environment",
        "rpdb-empty-live",
        "--out-dir",
        str(cgnat_local_pki_review),
        "--json",
    )
    _run(
        str(CGNAT_ROOT / "framework" / "scripts" / "prepare_cgnat_customer_pilot.py"),
        str(request_examples / "example-minimal-cgnat-shared-isp-local-pki.yaml"),
        "--environment",
        "rpdb-empty-live",
        "--out-dir",
        str(cgnat_shared_gateway_review),
        "--json",
    )
    _run(
        str(CGNAT_ROOT / "framework" / "scripts" / "prepare_cgnat_customer_pilot.py"),
        str(request_examples / "example-minimal-cgnat-shared-isp-scenario2-local-pki.yaml"),
        "--environment",
        "rpdb-empty-live",
        "--out-dir",
        str(cgnat_scenario2_shared_gateway_review),
        "--json",
    )

    base_staged_env = REPO_ROOT / "muxer" / "config" / "deployment-environments" / "example-rpdb-staged-live.yaml"
    staged_env_doc = yaml.safe_load(base_staged_env.read_text(encoding="utf-8")) or {}
    staged_root = regression_root / "staged-live"

    def _rewrite_staged_paths(value: object) -> object:
        if isinstance(value, str) and value.startswith("build/staged-live"):
            suffix = value[len("build/staged-live") :].lstrip("/\\")
            return str((staged_root / suffix).resolve())
        if isinstance(value, dict):
            return {key: _rewrite_staged_paths(nested) for key, nested in value.items()}
        if isinstance(value, list):
            return [_rewrite_staged_paths(nested) for nested in value]
        return value

    staged_env_path.write_text(
        yaml.safe_dump(_rewrite_staged_paths(staged_env_doc), sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    _prepare_staged_customer_request(
        request_examples / "example-minimal-cgnat.yaml",
        cgnat_staged_request,
        "example-minimal-cgnat-staged-apply",
    )
    _prepare_staged_customer_request(
        request_examples / "example-minimal-cgnat-shared-isp-local-pki.yaml",
        cgnat_shared_gateway_staged_request,
        "example-minimal-cgnat-shared-gateway-staged-apply",
    )
    _prepare_staged_customer_request(
        request_examples / "example-cgnat-customer-1-local-pki.yaml",
        cgnat_dual_customer1_request,
        "example-cgnat-customer-1-staged-apply",
        peer_public_ip="203.0.113.61",
    )
    _prepare_staged_customer_request(
        request_examples / "example-minimal-cgnat-local-pki.yaml",
        cgnat_dual_customer2_request,
        "example-cgnat-customer-2-staged-apply",
        peer_public_ip="203.0.113.61",
    )
    for relative_path in (
        "muxer-root",
        "nat-active-root",
        "nat-standby-root",
        "nonnat-active-root",
        "nonnat-standby-root",
        "cgnat-headend-root",
        "cgnat-isp-gateway-1-root",
        "cgnat-isp-gateway-2-root",
        "datastores",
        "artifacts",
        "logs",
        "nat-t-watcher/state",
        "nat-t-watcher/out",
        "nat-t-watcher/packages",
        "nat-t-watcher/synced",
        "backups/baseline/muxer",
        "backups/baseline/nat-headend",
        "backups/baseline/non-nat-headend",
        "backups/baseline/cgnat-headend",
        "backups/baseline/cgnat-isp-gateways/isp-cgnat-router-1",
        "backups/baseline/cgnat-isp-gateways/isp-cgnat-router-2",
    ):
        (staged_root / relative_path).mkdir(parents=True, exist_ok=True)
    _run(
        str(REPO_ROOT / "scripts" / "customers" / "deploy_customer.py"),
        "--customer-file",
        str(cgnat_staged_request),
        "--environment",
        str(staged_env_path),
        "--out-dir",
        str(cgnat_staged_apply),
        "--approve",
        "--json",
    )
    cgnat_staged_apply_summary = _load_json(cgnat_staged_apply / "execution-plan.json")
    rollback_plan = _load_json(REPO_ROOT / cgnat_staged_apply_summary["apply"]["rollback_plan"])
    rollback_results = [
        _run_json_command(step["command"])
        for step in reversed(rollback_plan["steps"])
    ]
    rollback_execution_summary = {
        "schema_version": 1,
        "customer_name": "example-minimal-cgnat-staged-apply",
        "rollback_results": rollback_results,
    }
    (cgnat_staged_apply / "rollback-execution-summary.json").write_text(
        json.dumps(rollback_execution_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    rollback_cleanup_ok = not any(
        path.exists()
        for path in (
            staged_root / "datastores" / "var" / "lib" / "rpdb-backend" / "customers" / "example-minimal-cgnat-staged-apply",
            staged_root / "datastores" / "var" / "lib" / "rpdb-backend" / "allocations" / "example-minimal-cgnat-staged-apply",
            staged_root / "muxer-root" / "var" / "lib" / "rpdb-muxer" / "customers" / "example-minimal-cgnat-staged-apply",
            staged_root / "muxer-root" / "etc" / "muxer" / "config" / "customer-modules" / "example-minimal-cgnat-staged-apply",
            staged_root / "nonnat-active-root" / "var" / "lib" / "rpdb-headend" / "customers" / "example-minimal-cgnat-staged-apply",
            staged_root / "nonnat-active-root" / "etc" / "swanctl" / "conf.d" / "rpdb-customers" / "example-minimal-cgnat-staged-apply.conf",
            staged_root / "nonnat-standby-root" / "var" / "lib" / "rpdb-headend" / "customers" / "example-minimal-cgnat-staged-apply",
            staged_root / "nonnat-standby-root" / "etc" / "swanctl" / "conf.d" / "rpdb-customers" / "example-minimal-cgnat-staged-apply.conf",
            staged_root / "cgnat-headend-root" / "var" / "lib" / "rpdb-cgnat" / "customers" / "example-minimal-cgnat-staged-apply",
            staged_root / "cgnat-headend-root" / "etc" / "rpdb-cgnat" / "customers" / "example-minimal-cgnat-staged-apply.json",
        )
    )
    _run(
        str(REPO_ROOT / "scripts" / "customers" / "deploy_customer.py"),
        "--customer-file",
        str(cgnat_shared_gateway_staged_request),
        "--environment",
        str(staged_env_path),
        "--out-dir",
        str(cgnat_shared_gateway_staged_apply),
        "--approve",
        "--json",
    )
    cgnat_shared_gateway_staged_apply_summary = _load_json(cgnat_shared_gateway_staged_apply / "execution-plan.json")
    cgnat_shared_gateway_rollback_plan = _load_json(
        REPO_ROOT / cgnat_shared_gateway_staged_apply_summary["apply"]["rollback_plan"]
    )
    cgnat_shared_gateway_rollback_results = [
        _run_json_command(step["command"])
        for step in reversed(cgnat_shared_gateway_rollback_plan["steps"])
    ]
    cgnat_shared_gateway_rollback_summary = {
        "schema_version": 1,
        "customer_name": "example-minimal-cgnat-shared-gateway-staged-apply",
        "rollback_results": cgnat_shared_gateway_rollback_results,
    }
    (cgnat_shared_gateway_staged_apply / "rollback-execution-summary.json").write_text(
        json.dumps(cgnat_shared_gateway_rollback_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    cgnat_shared_gateway_rollback_cleanup_ok = not any(
        path.exists()
        for path in (
            staged_root / "datastores" / "var" / "lib" / "rpdb-backend" / "customers" / "example-minimal-cgnat-shared-gateway-staged-apply",
            staged_root / "datastores" / "var" / "lib" / "rpdb-backend" / "allocations" / "example-minimal-cgnat-shared-gateway-staged-apply",
            staged_root / "muxer-root" / "var" / "lib" / "rpdb-muxer" / "customers" / "example-minimal-cgnat-shared-gateway-staged-apply",
            staged_root / "muxer-root" / "etc" / "muxer" / "config" / "customer-modules" / "example-minimal-cgnat-shared-gateway-staged-apply",
            staged_root / "nonnat-active-root" / "var" / "lib" / "rpdb-headend" / "customers" / "example-minimal-cgnat-shared-gateway-staged-apply",
            staged_root / "nonnat-active-root" / "etc" / "swanctl" / "conf.d" / "rpdb-customers" / "example-minimal-cgnat-shared-gateway-staged-apply.conf",
            staged_root / "nonnat-standby-root" / "var" / "lib" / "rpdb-headend" / "customers" / "example-minimal-cgnat-shared-gateway-staged-apply",
            staged_root / "nonnat-standby-root" / "etc" / "swanctl" / "conf.d" / "rpdb-customers" / "example-minimal-cgnat-shared-gateway-staged-apply.conf",
            staged_root / "cgnat-headend-root" / "var" / "lib" / "rpdb-cgnat" / "customers" / "example-minimal-cgnat-shared-gateway-staged-apply",
            staged_root / "cgnat-headend-root" / "etc" / "rpdb-cgnat" / "customers" / "example-minimal-cgnat-shared-gateway-staged-apply.json",
        )
    )

    _run(
        str(REPO_ROOT / "scripts" / "customers" / "deploy_customer.py"),
        "--customer-file",
        str(cgnat_dual_customer1_request),
        "--environment",
        str(staged_env_path),
        "--out-dir",
        str(cgnat_dual_customer1_staged_apply),
        "--approve",
        "--json",
    )
    _run(
        str(REPO_ROOT / "scripts" / "customers" / "deploy_customer.py"),
        "--customer-file",
        str(cgnat_dual_customer2_request),
        "--environment",
        str(staged_env_path),
        "--out-dir",
        str(cgnat_dual_customer2_staged_apply),
        "--approve",
        "--json",
    )
    dual_customer1_summary = _load_json(cgnat_dual_customer1_staged_apply / "execution-plan.json")
    dual_customer2_summary = _load_json(cgnat_dual_customer2_staged_apply / "execution-plan.json")
    dual_customer_names = [
        "example-cgnat-customer-1-staged-apply",
        "example-cgnat-customer-2-staged-apply",
    ]
    dual_customer_installed_ok = all(
        (staged_root / "cgnat-headend-root" / "var" / "lib" / "rpdb-cgnat" / "customers" / customer_name).exists()
        and (staged_root / "muxer-root" / "var" / "lib" / "rpdb-muxer" / "customers" / customer_name).exists()
        and (staged_root / "nonnat-active-root" / "var" / "lib" / "rpdb-headend" / "customers" / customer_name).exists()
        for customer_name in dual_customer_names
    )
    dual_rollback_results: list[dict] = []
    for summary in (dual_customer2_summary, dual_customer1_summary):
        dual_rollback_plan = _load_json(REPO_ROOT / summary["apply"]["rollback_plan"])
        dual_rollback_results.extend(
            _run_json_command(step["command"])
            for step in reversed(dual_rollback_plan["steps"])
        )
    dual_rollback_cleanup_ok = not any(
        path.exists()
        for customer_name in dual_customer_names
        for path in (
            staged_root / "datastores" / "var" / "lib" / "rpdb-backend" / "customers" / customer_name,
            staged_root / "datastores" / "var" / "lib" / "rpdb-backend" / "allocations" / customer_name,
            staged_root / "muxer-root" / "var" / "lib" / "rpdb-muxer" / "customers" / customer_name,
            staged_root / "muxer-root" / "etc" / "muxer" / "config" / "customer-modules" / customer_name,
            staged_root / "nonnat-active-root" / "var" / "lib" / "rpdb-headend" / "customers" / customer_name,
            staged_root / "nonnat-active-root" / "etc" / "swanctl" / "conf.d" / "rpdb-customers" / f"{customer_name}.conf",
            staged_root / "nonnat-standby-root" / "var" / "lib" / "rpdb-headend" / "customers" / customer_name,
            staged_root / "nonnat-standby-root" / "etc" / "swanctl" / "conf.d" / "rpdb-customers" / f"{customer_name}.conf",
            staged_root / "cgnat-headend-root" / "var" / "lib" / "rpdb-cgnat" / "customers" / customer_name,
            staged_root / "cgnat-headend-root" / "etc" / "rpdb-cgnat" / "customers" / f"{customer_name}.json",
        )
    )
    (regression_root / "dual-customer-rollback-summary.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "customer_names": dual_customer_names,
                "rollback_results": dual_rollback_results,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    _run(
        str(CGNAT_ROOT / "framework" / "scripts" / "prepare_scenario1.py"),
        str(sample_bundle),
        str(sample_prep),
    )

    _run(
        str(CGNAT_ROOT / "server" / "scripts" / "materialize_scenario1_demo_materials.py"),
        str(live_bundle),
        str(live_materials),
    )
    materials_manifest = live_materials / "materials-manifest.json"

    _run(
        str(CGNAT_ROOT / "framework" / "scripts" / "prepare_scenario1.py"),
        str(live_bundle),
        str(live_prep),
        "--materials-manifest-json",
        str(materials_manifest),
        "--aws-preflight",
    )
    _run(
        str(CGNAT_ROOT / "aws" / "scripts" / "deploy_scenario1_aws.py"),
        str(live_prep / "aws-package"),
        str(live_prep / "aws-apply-dryrun"),
        "--mode",
        "apply",
    )
    _run(
        str(CGNAT_ROOT / "framework" / "scripts" / "prepare_scenario1_predeploy_review.py"),
        str(live_bundle),
        str(live_prep),
        str(live_prep / "aws-apply-dryrun"),
        str(live_predeploy),
        "--host-access-strategy-json",
        str(host_access_strategy),
        "--materials-manifest-json",
        str(materials_manifest),
    )
    _run(
        str(CGNAT_ROOT / "framework" / "scripts" / "prepare_scenario1_backend_integration.py"),
        str(live_bundle),
        str(backend_integration),
        str(live_backend),
    )
    _run(
        str(CGNAT_ROOT / "framework" / "scripts" / "prepare_scenario1_deployment_stage_review.py"),
        str(live_bundle),
        str(live_predeploy / "predeploy-review-summary.json"),
        str(live_backend / "backend-integration-summary.json"),
        str(deployment_stage),
    )

    sample_summary = _load_json(sample_prep / "scenario1-preparation-summary.json")
    live_summary = _load_json(live_prep / "scenario1-preparation-summary.json")
    predeploy_summary = _load_json(live_predeploy / "predeploy-review-summary.json")
    backend_summary = _load_json(live_backend / "backend-integration-summary.json")
    deployment_summary = _load_json(deployment_stage / "deployment-stage-review-summary.json")
    shared_nonnat_summary = _load_json(shared_nonnat / "provisioning-run.json")
    shared_nat_summary = _load_json(shared_nat / "provisioning-run.json")
    cgnat_review_summary = _load_json(cgnat_review / "combined-review-summary.json")
    cgnat_profile_override_report = _load_json(
        cgnat_review / "shared-dry-run" / "package" / "cgnat-profile-override-report.json"
    )
    cgnat_review_source = yaml.safe_load(
        (cgnat_review / "shared-dry-run" / "package" / "customer-source.yaml").read_text(encoding="utf-8")
    ) or {}
    cgnat_shared_gateway_review_summary = _load_json(cgnat_shared_gateway_review / "combined-review-summary.json")
    cgnat_shared_gateway_live_execution_plan = _load_json(cgnat_shared_gateway_review / "live-execution-plan.json")
    cgnat_scenario2_shared_gateway_review_summary = _load_json(
        cgnat_scenario2_shared_gateway_review / "combined-review-summary.json"
    )
    cgnat_scenario2_shared_gateway_live_execution_plan = _load_json(
        cgnat_scenario2_shared_gateway_review / "live-execution-plan.json"
    )
    cgnat_customer1_live_review_summary = _load_json(cgnat_customer1_live_review / "combined-review-summary.json")
    cgnat_customer1_live_execution_plan = _load_json(cgnat_customer1_live_review / "live-execution-plan.json")
    cgnat_local_pki_review_summary = _load_json(cgnat_local_pki_review / "combined-review-summary.json")
    cgnat_local_pki_surface = _load_json(cgnat_local_pki_review / "pki" / "pki-review.json")
    cgnat_review_outside_nat = dict((cgnat_review_source.get("customer") or {}).get("outside_nat") or {})

    regression_summary = {
        "regression_type": "cgnat_full_regression",
        "shared_nonnat_ready_for_review": bool(shared_nonnat_summary.get("ready_for_review")),
        "shared_nat_ready_for_review": bool(shared_nat_summary.get("ready_for_review")),
        "cgnat_customer_review_ready_for_review": bool(cgnat_review_summary.get("ready_for_review")),
        "cgnat_profile_override_applied": bool(cgnat_profile_override_report.get("applied")),
        "cgnat_profile_override_route_via_ok": (
            cgnat_review_outside_nat.get("route_via") == "172.31.63.44"
            and cgnat_review_outside_nat.get("route_dev") == "ens36"
            and cgnat_review_outside_nat.get("real_subnets") == ["194.138.36.86/32"]
        ),
        "cgnat_shared_gateway_review_ready_for_review": bool(
            cgnat_shared_gateway_review_summary.get("ready_for_review")
        ),
        "cgnat_shared_gateway_live_execution_plan_ready": bool(
            cgnat_shared_gateway_live_execution_plan.get("gateway_device_backup_required")
            and (cgnat_shared_gateway_live_execution_plan.get("outer_handoff") or {}).get("recipient_type")
            == "isp_gateway"
        ),
        "cgnat_scenario2_shared_gateway_review_ready_for_review": bool(
            cgnat_scenario2_shared_gateway_review_summary.get("ready_for_review")
        ),
        "cgnat_scenario2_gateway_target_selected": bool(
            cgnat_scenario2_shared_gateway_live_execution_plan.get("gateway_target")
            and cgnat_scenario2_shared_gateway_live_execution_plan.get("gateway_target")
            == "isp-cgnat-router-2"
            and cgnat_scenario2_shared_gateway_live_execution_plan.get("outer_topology")
            == "shared_isp_gateway"
        ),
        "cgnat_customer1_live_review_ready_for_review": bool(
            cgnat_customer1_live_review_summary.get("ready_for_review")
        ),
        "cgnat_customer1_live_execution_plan_ready": bool(
            cgnat_customer1_live_execution_plan.get("customer_device_backup_required")
            and (cgnat_customer1_live_execution_plan.get("customer_handoff") or {}).get("package_name")
        ),
        "cgnat_customer_local_pki_review_ready_for_review": bool(
            cgnat_local_pki_review_summary.get("ready_for_review")
        ),
        "cgnat_customer_local_pki_material_generated": bool(
            cgnat_local_pki_surface.get("generated_material")
        ),
        "cgnat_staged_apply_ok": str(cgnat_staged_apply_summary.get("status") or "").strip().lower() == "applied",
        "cgnat_staged_rollback_ok": rollback_cleanup_ok and all(
            (
                str(result.get("status") or "").strip().lower() == "rolled_back"
                or bool(result.get("removed"))
            )
            for result in rollback_results
        ),
        "cgnat_shared_gateway_staged_apply_ok": str(
            cgnat_shared_gateway_staged_apply_summary.get("status") or ""
        ).strip().lower() == "applied",
        "cgnat_shared_gateway_staged_rollback_ok": cgnat_shared_gateway_rollback_cleanup_ok
        and all(
            (
                str(result.get("status") or "").strip().lower() == "rolled_back"
                or bool(result.get("removed"))
            )
            for result in cgnat_shared_gateway_rollback_results
        ),
        "cgnat_dual_customer_staged_apply_ok": dual_customer_installed_ok
        and str(dual_customer1_summary.get("status") or "").strip().lower() == "applied"
        and str(dual_customer2_summary.get("status") or "").strip().lower() == "applied",
        "cgnat_dual_customer_staged_rollback_ok": dual_rollback_cleanup_ok
        and all(
            (
                str(result.get("status") or "").strip().lower() == "rolled_back"
                or bool(result.get("removed"))
            )
            for result in dual_rollback_results
        ),
        "sample_validation_ok": bool(sample_summary.get("validation_ok")),
        "live_validation_ok": bool(live_summary.get("validation_ok")),
        "aws_live_create_allowed": bool(live_summary.get("aws_live_create_allowed")),
        "aws_preflight_ready_for_live_apply": bool(live_summary.get("aws_preflight_ready_for_live_apply")),
        "predeploy_ready_for_hard_review": bool(predeploy_summary.get("ready_for_hard_review")),
        "backend_validation_ok": bool(backend_summary.get("validation_ok")),
        "backend_deploy_dry_run_ok": bool(backend_summary.get("deploy_dry_run_ok")),
        "deployment_stage_ready": bool(deployment_summary.get("ready_for_deployment_stage_review")),
        "artifacts": {
            "shared_nonnat_package": str(shared_nonnat),
            "shared_nat_package": str(shared_nat),
            "cgnat_customer_review": str(cgnat_review),
            "cgnat_profile_override_report": str(
                cgnat_review / "shared-dry-run" / "package" / "cgnat-profile-override-report.json"
            ),
            "cgnat_shared_gateway_review": str(cgnat_shared_gateway_review),
            "cgnat_scenario2_shared_gateway_review": str(cgnat_scenario2_shared_gateway_review),
            "cgnat_customer1_live_review": str(cgnat_customer1_live_review),
            "cgnat_customer_local_pki_review": str(cgnat_local_pki_review),
            "cgnat_customer_staged_apply": str(cgnat_staged_apply),
            "cgnat_customer_staged_rollback": str(cgnat_staged_apply / "rollback-execution-summary.json"),
            "cgnat_shared_gateway_staged_apply": str(cgnat_shared_gateway_staged_apply),
            "cgnat_shared_gateway_staged_rollback": str(
                cgnat_shared_gateway_staged_apply / "rollback-execution-summary.json"
            ),
            "cgnat_dual_customer1_staged_apply": str(cgnat_dual_customer1_staged_apply),
            "cgnat_dual_customer2_staged_apply": str(cgnat_dual_customer2_staged_apply),
            "cgnat_dual_customer_rollback": str(regression_root / "dual-customer-rollback-summary.json"),
            "sample_prep": str(sample_prep),
            "live_prep": str(live_prep),
            "live_predeploy_review": str(live_predeploy),
            "live_backend_integration": str(live_backend),
            "deployment_stage_review": str(deployment_stage),
        },
    }
    (regression_root / "regression-summary.json").write_text(
        json.dumps(regression_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
