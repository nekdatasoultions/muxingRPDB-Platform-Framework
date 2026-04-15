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
        },
    }

    def record_step(name: str, details: dict) -> None:
        cast_steps = summary["steps"]
        assert isinstance(cast_steps, list)
        cast_steps.append({"step": name, "status": "passed", "details": details})

    # Step 1: compile the new framework/runtime modules and scripts.
    compile_targets = [
        str(MUXER_DIR / "src" / "muxerlib" / "allocation.py"),
        str(MUXER_DIR / "src" / "muxerlib" / "allocation_sot.py"),
        str(MUXER_DIR / "scripts" / "validate_customer_request.py"),
        str(MUXER_DIR / "scripts" / "validate_customer_allocations.py"),
        str(MUXER_DIR / "scripts" / "provision_customer_request.py"),
        str(MUXER_DIR / "runtime-package" / "src" / "muxerlib" / "nftables.py"),
        str(MUXER_DIR / "runtime-package" / "scripts" / "render_nft_passthrough.py"),
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
    }
    provision_results: dict[str, dict] = {}
    for name, request_path in request_paths.items():
        _run(["python", str(MUXER_DIR / "scripts" / "validate_customer_request.py"), str(request_path)])
        provision_results[name] = _run_json(
            [
                "python",
                str(MUXER_DIR / "scripts" / "provision_customer_request.py"),
                str(request_path),
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
