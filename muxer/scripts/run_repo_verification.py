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
        str(MUXER_DIR / "scripts" / "prepare_customer_pilot.py"),
        str(MUXER_DIR / "runtime-package" / "src" / "muxerlib" / "nftables.py"),
        str(MUXER_DIR / "runtime-package" / "scripts" / "render_nft_passthrough.py"),
        str(REPO_ROOT / "scripts" / "packaging" / "validate_customer_bundle.py"),
        str(REPO_ROOT / "scripts" / "deployment" / "headend_customer_lib.py"),
        str(REPO_ROOT / "scripts" / "deployment" / "apply_headend_customer.py"),
        str(REPO_ROOT / "scripts" / "deployment" / "remove_headend_customer.py"),
        str(REPO_ROOT / "scripts" / "deployment" / "validate_headend_customer.py"),
        str(REPO_ROOT / "scripts" / "deployment" / "run_double_verification.py"),
    ]
    _run(["python", "-m", "py_compile", *compile_targets])
    record_step("compile_targets", {"count": len(compile_targets)})

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
    }
    pilot_reports: dict[str, dict] = {}
    environment_file = MUXER_DIR / "config" / "environment-defaults" / "example-environment.yaml"
    for pilot_name, spec in pilot_specs.items():
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
