#!/usr/bin/env python
"""Run the repo-only RPDB completion verification suite."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
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
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(yaml.safe_dump(payload, sort_keys=False))


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload if payload.endswith("\n") else payload + "\n")


def _generated_files_with_crlf(root: Path, suffixes: set[str]) -> list[str]:
    matches: list[str] = []
    if not root.exists():
        return matches
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        if b"\r\n" in path.read_bytes():
            matches.append(str(path))
    return matches


def _is_linux_activation_artifact(path: Path) -> bool:
    if path.suffix.lower() in {".conf", ".nft", ".sh"}:
        return True
    return path.name.endswith((".command.txt", ".commands.txt"))


def _generated_activation_files_with_windows_paths(root: Path) -> list[str]:
    matches: list[str] = []
    windows_path_re = re.compile(rb"[A-Za-z]:[\\/]")
    if not root.exists():
        return matches
    for path in root.rglob("*"):
        if not path.is_file() or not _is_linux_activation_artifact(path):
            continue
        if windows_path_re.search(path.read_bytes()):
            matches.append(str(path))
    return matches


def _tracked_files_with_forbidden_local_paths() -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files"],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    local_drive_path_re = re.compile(r"E:[\\/]")
    forbidden_tokens = ("Code" + "1", "LOCAL" + "_NOTES", "shared" + "_chat", "chat" + ".html")
    matches: list[str] = []
    for relative_name in completed.stdout.splitlines():
        path = REPO_ROOT / relative_name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if local_drive_path_re.search(text) or any(token in text for token in forbidden_tokens):
            matches.append(relative_name)
    return matches


def _resolve_repo_path(path_like: str) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def _assert_headend_transport_and_identity(
    package_dir: Path,
    *,
    customer_name: str,
    peer_public_ip: str,
    headend_public_ip: str,
) -> str:
    peer_public_cidr = peer_public_ip if "/" in peer_public_ip else f"{peer_public_ip}/32"
    bundle_dir = package_dir / "bundle"
    customer_module_path = bundle_dir / "customer" / "customer-module.json"
    if not customer_module_path.exists():
        raise SystemExit(f"{customer_name} customer module is missing: {customer_module_path}")
    customer_module = json.loads(customer_module_path.read_text(encoding="utf-8"))
    transport = customer_module.get("transport") or {}
    overlay = transport.get("overlay") or {}
    interface = str(transport.get("interface") or "").strip()
    mux_overlay_ip = str(overlay.get("mux_ip") or "").strip()
    router_overlay_ip = str(overlay.get("router_ip") or "").strip()
    mux_overlay_host = str(ipaddress.ip_interface(mux_overlay_ip).ip) if mux_overlay_ip else ""
    tunnel_key = str(transport.get("tunnel_key") or "").strip()
    tunnel_ttl = str(transport.get("tunnel_ttl") or "").strip()
    expected_route = f"ip route replace {peer_public_cidr} via {mux_overlay_host} dev {interface}"
    route_path = package_dir / "bundle" / "headend" / "routing" / "ip-route.commands.txt"
    if not route_path.exists():
        raise SystemExit(f"{customer_name} head-end route artifact is missing: {route_path}")
    route_text = route_path.read_text(encoding="utf-8")
    if expected_route not in route_text:
        raise SystemExit(
            f"{customer_name} head-end route artifact is missing GRE muxer edge return route: {expected_route}"
        )

    transport_intent_path = bundle_dir / "headend" / "transport" / "transport-intent.json"
    transport_apply_path = bundle_dir / "headend" / "transport" / "apply-transport.sh"
    transport_remove_path = bundle_dir / "headend" / "transport" / "remove-transport.sh"
    public_identity_intent_path = bundle_dir / "headend" / "public-identity" / "public-identity-intent.json"
    public_identity_apply_path = bundle_dir / "headend" / "public-identity" / "apply-public-identity.sh"
    public_identity_remove_path = bundle_dir / "headend" / "public-identity" / "remove-public-identity.sh"
    for path in (
        transport_intent_path,
        transport_apply_path,
        transport_remove_path,
        public_identity_intent_path,
        public_identity_apply_path,
        public_identity_remove_path,
    ):
        if not path.exists():
            raise SystemExit(f"{customer_name} head-end transport/public identity artifact is missing: {path}")

    transport_intent = json.loads(transport_intent_path.read_text(encoding="utf-8"))
    if not transport_intent.get("enabled"):
        raise SystemExit(f"{customer_name} head-end transport intent is not enabled")
    if transport_intent.get("type") != "gre":
        raise SystemExit(f"{customer_name} head-end transport intent is not GRE")
    expected_transport_values = {
        "interface": interface,
        "tunnel_key": tunnel_key,
        "tunnel_ttl": tunnel_ttl,
        "router_overlay_ip": router_overlay_ip,
        "mux_overlay_ip": mux_overlay_ip,
        "mux_overlay_host": mux_overlay_host,
        "peer_public_cidr": peer_public_cidr,
    }
    for key, expected_value in expected_transport_values.items():
        if str(transport_intent.get(key) or "") != expected_value:
            raise SystemExit(
                f"{customer_name} head-end transport intent {key} mismatch: expected {expected_value}"
            )

    transport_script_text = "\n".join(
        [
            transport_apply_path.read_text(encoding="utf-8"),
            transport_remove_path.read_text(encoding="utf-8"),
        ]
    )
    for required_fragment in (
        'ip tunnel add "$IFNAME" mode gre local "$LOCAL_UL" remote "$REMOTE_UL" key "$KEY" ttl "$TTL"',
        'ip addr replace "$ROUTER_IP" dev "$IFNAME"',
        'ip link set "$IFNAME" up',
        'ip route replace "$PEER_CIDR" via "$MUX_OVERLAY_HOST" dev "$IFNAME"',
        'ip link del "$IFNAME" 2>/dev/null || true',
    ):
        if required_fragment not in transport_script_text:
            raise SystemExit(f"{customer_name} head-end transport scripts missing: {required_fragment}")

    public_identity_intent = json.loads(public_identity_intent_path.read_text(encoding="utf-8"))
    expected_public_cidr = f"{headend_public_ip}/32"
    if public_identity_intent.get("public_ip") != headend_public_ip:
        raise SystemExit(f"{customer_name} public identity IP mismatch")
    if public_identity_intent.get("cidr") != expected_public_cidr:
        raise SystemExit(f"{customer_name} public identity CIDR mismatch")
    if public_identity_intent.get("device") != "lo":
        raise SystemExit(f"{customer_name} public identity must bind on lo")
    public_identity_script_text = "\n".join(
        [
            public_identity_apply_path.read_text(encoding="utf-8"),
            public_identity_remove_path.read_text(encoding="utf-8"),
        ]
    )
    if 'ip addr replace "$PUBLIC_CIDR" dev "$DEVICE"' not in public_identity_script_text:
        raise SystemExit(f"{customer_name} public identity apply script does not add the loopback /32")
    if "Shared head-end public identity is retained on customer removal." not in public_identity_script_text:
        raise SystemExit(f"{customer_name} public identity remove script must retain the shared /32")
    banned = "iptables"
    generated_payload = "\n".join([route_text, transport_script_text, public_identity_script_text]).lower()
    if banned in generated_payload or "iptables-restore" in generated_payload:
        raise SystemExit(f"{customer_name} generated head-end transport artifacts contain iptables tokens")
    return expected_route


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
            "translation_bridge_scale_decisions": str(MUXER_DIR / "docs" / "TRANSLATION_AND_BRIDGE_SCALE_DECISIONS.md"),
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
        str(MUXER_DIR / "scripts" / "run_scale_baseline.py"),
        str(RUNTIME_ROOT / "src" / "muxerlib" / "cli.py"),
        str(RUNTIME_ROOT / "src" / "muxerlib" / "dataplane.py"),
        str(RUNTIME_ROOT / "src" / "muxerlib" / "modes.py"),
        str(RUNTIME_ROOT / "src" / "nat_t_event_listener.py"),
        str(MUXER_DIR / "runtime-package" / "src" / "muxerlib" / "nftables.py"),
        str(MUXER_DIR / "runtime-package" / "scripts" / "render_nft_passthrough.py"),
        str(REPO_ROOT / "scripts" / "customers" / "validate_deployment_environment.py"),
        str(REPO_ROOT / "scripts" / "customers" / "deploy_customer.py"),
        str(REPO_ROOT / "scripts" / "customers" / "run_nat_t_watcher.py"),
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
        str(REPO_ROOT / "scripts" / "platform" / "prepare_empty_platform_params.py"),
        str(REPO_ROOT / "scripts" / "platform" / "deploy_empty_platform.py"),
        str(REPO_ROOT / "scripts" / "platform" / "verify_headend_bootstrap.py"),
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
    customer2_package_dir = _resolve_repo_path(str((customer2_deploy.get("package") or {}).get("package_dir") or ""))
    customer2_edge_return_route = _assert_headend_transport_and_identity(
        customer2_package_dir,
        customer_name="legacy-cust0002",
        peer_public_ip="166.213.153.39",
        headend_public_ip="23.20.31.151",
    )

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
    customer4_package_dir = _resolve_repo_path(str((customer4_deploy.get("package") or {}).get("package_dir") or ""))
    customer4_edge_return_route = _assert_headend_transport_and_identity(
        customer4_package_dir,
        customer_name="vpn-customer-stage1-15-cust-0004",
        peer_public_ip="3.237.201.84",
        headend_public_ip="23.20.31.151",
    )
    customer4_swanctl = (
        customer4_package_dir / "bundle" / "headend" / "ipsec" / "swanctl-connection.conf"
    ).read_text(encoding="utf-8")
    if "local_addrs = 172.31.40.222" not in customer4_swanctl:
        raise SystemExit("Customer 4 NAT-T head-end config must listen on the NAT head-end primary IP")

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
            "customer2_edge_return_route": customer2_edge_return_route,
            "customer4_status": customer4_deploy["status"],
            "customer4_headend_family": customer4_deploy["selected_targets"]["headend_family"],
            "customer4_gate": customer4_deploy["dry_run_gate"]["status"],
            "customer4_edge_return_route": customer4_edge_return_route,
            "customer4_headend_local_addrs": "172.31.40.222",
            "synthetic_blocked_status": blocked_report["status"],
            "missing_backup_status": missing_backup_report["status"],
            "missing_backup_gate": missing_backup_report["dry_run_gate"]["status"],
            "invalid_environment_status": invalid_env_report["status"],
            "live_apply": False,
        },
    )

    # Step 3f: verify the live muxer runtime now contains the NAT-T event
    # producer, not only the repo-side watcher/consumer.
    listener_source = RUNTIME_ROOT / "src" / "nat_t_event_listener.py"
    listener_unit = RUNTIME_ROOT / "systemd" / "rpdb-nat-t-listener.service"
    installer_path = RUNTIME_ROOT / "scripts" / "install-local.sh"
    listener_self_test = _run_json(["python", str(listener_source), "--self-test", "--json"])
    if not listener_self_test.get("valid"):
        raise SystemExit("NAT-T runtime listener self-test failed")
    listener_text = listener_source.read_text(encoding="utf-8")
    listener_unit_text = listener_unit.read_text(encoding="utf-8")
    installer_text = installer_path.read_text(encoding="utf-8")
    single_muxer_template_text = (REPO_ROOT / "infra" / "cfn" / "muxer-single-asg.yaml").read_text(
        encoding="utf-8"
    )
    cluster_muxer_template_text = (REPO_ROOT / "infra" / "cfn" / "muxer-cluster.yaml").read_text(
        encoding="utf-8"
    )
    live_apply_lib_text = (REPO_ROOT / "scripts" / "customers" / "live_apply_lib.py").read_text(
        encoding="utf-8"
    )
    rpdb_empty_environment_text = (
        MUXER_DIR / "config" / "deployment-environments" / "rpdb-empty-live.yaml"
    ).read_text(encoding="utf-8")
    muxer_runtime_config_text = (RUNTIME_ROOT / "config" / "muxer.yaml").read_text(encoding="utf-8")
    required_listener_tokens = {
        "listener_source": [
            "rpdb-muxer-nat-t-listener",
            "/var/log/rpdb/muxer-events.jsonl",
            "tcpdump",
            "observed_dport",
            "observed_peer",
        ],
        "listener_unit": [
            "ExecStart=/usr/bin/python3 /etc/muxer/src/nat_t_event_listener.py",
            "Restart=always",
        ],
        "installer": [
            "rpdb-nat-t-listener.service",
            "/etc/systemd/system/rpdb-nat-t-listener.service",
        ],
        "single_muxer_template": [
            "systemctl enable --now rpdb-nat-t-listener.service",
        ],
        "cluster_muxer_template": [
            "systemctl enable --now rpdb-nat-t-listener.service",
        ],
        "ssh_live_apply": [
            "nat_t_event_listener.py",
            "rpdb-nat-t-listener.service",
            "/var/log/rpdb/muxer-events.jsonl",
            "systemctl restart rpdb-nat-t-listener.service",
            "systemctl is-active --quiet rpdb-nat-t-listener.service",
        ],
        "runtime_config": [
            "nat_t_listener:",
            "event_log: /var/log/rpdb/muxer-events.jsonl",
            "bpf_filter: udp and (port 500 or port 4500)",
        ],
        "deployment_environment": [
            "nat_t_watcher:",
            "path: /var/log/rpdb/muxer-events.jsonl",
        ],
    }
    token_sources = {
        "listener_source": listener_text,
        "listener_unit": listener_unit_text,
        "installer": installer_text,
        "single_muxer_template": single_muxer_template_text,
        "cluster_muxer_template": cluster_muxer_template_text,
        "ssh_live_apply": live_apply_lib_text,
        "runtime_config": muxer_runtime_config_text,
        "deployment_environment": rpdb_empty_environment_text,
    }
    for source_name, tokens in required_listener_tokens.items():
        text = token_sources[source_name]
        for token in tokens:
            if token not in text:
                raise SystemExit(f"NAT-T runtime listener contract missing {source_name} token: {token}")
    record_step(
        "muxer_nat_t_runtime_listener_contract",
        {
            "listener_source": str(listener_source),
            "listener_unit": str(listener_unit),
            "installer": str(installer_path),
            "event_log": "/var/log/rpdb/muxer-events.jsonl",
            "self_test": listener_self_test,
            "fresh_single_muxer_enables_service": True,
            "fresh_cluster_muxer_enables_service": True,
            "ssh_live_apply_syncs_service": True,
            "runtime_uses_iptables": False,
        },
    )

    # Step 3g: verify automated NAT-T log watching can detect UDP/4500,
    # correlate it to a customer request, and launch the one-file provisioning
    # workflow without touching live systems.
    watcher_root = BUILD_ROOT / "ntw"
    if watcher_root.exists():
        shutil.rmtree(watcher_root)
    watcher_root.mkdir(parents=True, exist_ok=True)
    watcher_env_path = watcher_root / "e.yaml"
    watcher_env_doc = _build_staged_live_environment(
        watcher_env_path,
        name="repo-verification-phase8-watcher",
        root=watcher_root / "roots",
    )
    watcher_log = Path(str(watcher_env_doc["nat_t_watcher"]["log_source"]["path"]))
    watcher_tcpdump_log = watcher_root / "tcpdump.txt"
    _write_text(
        watcher_tcpdump_log,
        "\n".join(
            [
                "2026-04-15 22:45:00.000000 IP 3.237.201.84.500 > 172.31.33.150.500: UDP, length 292",
                "2026-04-15 22:45:02.000000 IP 3.237.201.84.4500 > 172.31.33.150.4500: UDP, length 108",
                "2026-04-15 22:45:03.000000 IP 172.31.33.150.4500 > 3.237.201.84.4500: UDP, length 108",
            ]
        ),
    )
    listener_emit_report = _run_json(
        [
            "python",
            str(RUNTIME_ROOT / "src" / "nat_t_event_listener.py"),
            "--input-file",
            str(watcher_tcpdump_log),
            "--event-log",
            str(watcher_log),
            "--interface",
            "ens5",
            "--local-address",
            "172.31.33.150",
            "--json",
        ]
    )
    if listener_emit_report.get("emitted") != 2 or listener_emit_report.get("ignored") != 1:
        raise SystemExit("NAT-T runtime listener did not emit the expected watcher JSONL events")
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
            "environment_log_source": str(watcher_log),
            "deploy_mode": provisioning["mode"],
            "deploy_status": provisioning_json["status"],
            "live_apply": provisioning_json["live_apply"],
            "listener_emit_report": listener_emit_report,
            "second_pass_detected_count": second_pass["detected_count"],
            "watch_summary": watcher_report["out_dir"] + "/watch-summary.json",
        },
    )

    # Step 3h: verify the control-plane runner consumes the environment
    # contract, discovers customer request roots from that contract, and calls
    # the watcher without operator-selected customer files.
    runner_root = BUILD_ROOT / "nr"
    if runner_root.exists():
        shutil.rmtree(runner_root)
    runner_root.mkdir(parents=True, exist_ok=True)
    runner_env_path = runner_root / "e.yaml"
    runner_env_doc = _build_staged_live_environment(
        runner_env_path,
        name="repo-verification-phase8-watcher-runner",
        root=runner_root / "roots",
    )
    runner_env_doc["nat_t_watcher"]["state_root"] = str(runner_root / "s")
    runner_env_doc["nat_t_watcher"]["output_root"] = str(runner_root / "o")
    runner_env_doc["nat_t_watcher"]["package_root"] = str(runner_root / "p")
    runner_env_doc["nat_t_watcher"]["log_sync"]["local_copy"] = str(runner_root / "synced.jsonl")
    _write_yaml(runner_env_path, runner_env_doc)
    runner_log = Path(str(runner_env_doc["nat_t_watcher"]["log_source"]["path"]))
    runner_tcpdump_log = runner_root / "tcpdump.txt"
    _write_text(
        runner_tcpdump_log,
        "\n".join(
            [
                "2026-04-15 22:45:00.000000 IP 3.237.201.84.500 > 172.31.33.150.500: UDP, length 292",
                "2026-04-15 22:45:02.000000 IP 3.237.201.84.4500 > 172.31.33.150.4500: UDP, length 108",
                "2026-04-15 22:45:03.000000 IP 172.31.33.150.4500 > 3.237.201.84.4500: UDP, length 108",
            ]
        ),
    )
    runner_listener_emit_report = _run_json(
        [
            "python",
            str(RUNTIME_ROOT / "src" / "nat_t_event_listener.py"),
            "--input-file",
            str(runner_tcpdump_log),
            "--event-log",
            str(runner_log),
            "--interface",
            "ens5",
            "--local-address",
            "172.31.33.150",
            "--json",
        ]
    )
    if runner_listener_emit_report.get("emitted") != 2 or runner_listener_emit_report.get("ignored") != 1:
        raise SystemExit("NAT-T runner listener fixture did not emit the expected JSONL events")
    runner_report = _run_json(
        [
            "python",
            str(REPO_ROOT / "scripts" / "customers" / "run_nat_t_watcher.py"),
            "--environment",
            str(runner_env_path),
            "--log-sync-mode",
            "local_file",
            "--approve",
            "--json",
        ]
    )
    runner_watcher = runner_report.get("watcher") or {}
    runner_watcher_json = runner_watcher.get("json") or {}
    runner_command = runner_watcher.get("command") or []
    if runner_report.get("status") != "ok":
        raise SystemExit("NAT-T watcher runner did not complete successfully")
    if "--customer-request" in runner_command:
        raise SystemExit("NAT-T watcher runner must not require operator-selected customer files")
    if runner_watcher_json.get("detected_count") != 1:
        raise SystemExit("NAT-T watcher runner did not detect exactly one promotion event")
    runner_detected = runner_watcher_json["detected"][0]
    runner_provisioning = runner_detected.get("provisioning") or {}
    runner_provisioning_json = runner_provisioning.get("json") or {}
    if runner_provisioning_json.get("status") != "applied":
        raise SystemExit("NAT-T watcher runner did not drive the staged orchestrator apply path")
    runner_second_pass = _run_json(
        [
            "python",
            str(REPO_ROOT / "scripts" / "customers" / "run_nat_t_watcher.py"),
            "--environment",
            str(runner_env_path),
            "--log-sync-mode",
            "local_file",
            "--approve",
            "--json",
        ]
    )
    runner_second_watcher_json = ((runner_second_pass.get("watcher") or {}).get("json") or {})
    if runner_second_watcher_json.get("detected_count") != 0:
        raise SystemExit("NAT-T watcher runner was not idempotent on second pass")
    watcher_service_path = REPO_ROOT / "scripts" / "customers" / "systemd" / "rpdb-nat-t-watcher.service"
    watcher_service_text = watcher_service_path.read_text(encoding="utf-8")
    for token in (
        "scripts/customers/run_nat_t_watcher.py",
        "--environment ${RPDB_ENVIRONMENT}",
        "--follow",
        "--approve",
        "Restart=always",
    ):
        if token not in watcher_service_text:
            raise SystemExit(f"NAT-T watcher service contract missing token: {token}")
    record_step(
        "automatic_nat_t_control_plane_runner",
        {
            "detected_customer": runner_detected["customer_name"],
            "environment_file": str(runner_env_path),
            "environment_request_roots_used": True,
            "operator_selected_customer_file": False,
            "deploy_status": runner_provisioning_json["status"],
            "second_pass_detected_count": runner_second_watcher_json["detected_count"],
            "service_template": str(watcher_service_path),
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

    live_backend_idempotency = _run_python_json(
        r'''
import copy
import json

import live_backend_lib as lib

stores = {"customers": {}, "allocations": {}}
put_calls = []
delete_calls = []


def key_names(region, table):
    return ["customer_name"] if table == "customers" else ["customer_name", "resource_key"]


def key_id(key):
    return json.dumps(key, sort_keys=True)


def get_item(region, table, key):
    item = stores[table].get(key_id(key))
    return copy.deepcopy(item) if item is not None else None


def put_item(region, table, item):
    key = lib.extract_key(item, key_names(region, table))
    stores[table][key_id(key)] = copy.deepcopy(item)
    put_calls.append({"table": table, "key": key})


def delete_item(region, table, key):
    stores[table].pop(key_id(key), None)
    delete_calls.append({"table": table, "key": key})


lib.table_key_names = key_names
lib.get_typed_item = get_item
lib.put_typed_item = put_item
lib.delete_typed_item = delete_item

customer_existing_plain = {
    "customer_name": "vpn-customer-stage1-15-cust-0004",
    "customer_id": 41000,
    "fwmark": "0x41000",
    "source_ref": "build/old/request.yaml",
    "updated_at": "2026-04-20T08:00:00Z",
    "customer_json": json.dumps(
        {
            "customer": {"id": 41000, "name": "vpn-customer-stage1-15-cust-0004"},
            "metadata": {
                "class_name": "nat",
                "source_ref": "build/old/request.yaml",
                "resolved_at": "2026-04-20T08:00:00Z",
            },
            "transport": {"mark": "0x41000"},
        },
        sort_keys=True,
        separators=(",", ":"),
    ),
}
customer_expected_plain = {
    **customer_existing_plain,
    "source_ref": "build/new/request.yaml",
    "updated_at": "2026-04-20T09:00:00Z",
}
customer_expected_payload = json.loads(customer_existing_plain["customer_json"])
customer_expected_payload["metadata"]["source_ref"] = "build/new/request.yaml"
customer_expected_payload["metadata"]["resolved_at"] = "2026-04-20T09:00:00Z"
customer_expected_plain["customer_json"] = json.dumps(customer_expected_payload, sort_keys=True, separators=(",", ":"))

allocation_existing = lib.serialize_plain_item(
    {
        "customer_name": "vpn-customer-stage1-15-cust-0004",
        "resource_key": "fwmark#0x41000",
        "resource_type": "fwmark",
        "resource_value": "0x41000",
        "source_ref": "build/old/request.yaml",
        "allocated_at": "2026-04-20T08:00:00Z",
    }
)
allocation_expected = lib.serialize_plain_item(
    {
        "customer_name": "vpn-customer-stage1-15-cust-0004",
        "resource_key": "fwmark#0x41000",
        "resource_type": "fwmark",
        "resource_value": "0x41000",
        "source_ref": "build/new/request.yaml",
        "allocated_at": "2026-04-20T09:00:00Z",
    }
)
stores["customers"][key_id({"customer_name": {"S": "vpn-customer-stage1-15-cust-0004"}})] = (
    lib.serialize_plain_item(customer_existing_plain)
)
stores["allocations"][key_id(
    {
        "customer_name": {"S": "vpn-customer-stage1-15-cust-0004"},
        "resource_key": {"S": "fwmark#0x41000"},
    }
)] = allocation_existing

apply_result = lib.apply_backend_payloads(
    region="us-east-1",
    customer_table="customers",
    allocation_table="allocations",
    customer_item_plain=customer_expected_plain,
    allocation_items_typed=[allocation_expected],
)
validation_result = lib.validate_backend_payloads(
    region="us-east-1",
    customer_table="customers",
    allocation_table="allocations",
    customer_item_plain=customer_expected_plain,
    allocation_items_typed=[allocation_expected],
)
rollback_result = lib.rollback_backend_payloads(
    region="us-east-1",
    customer_table="customers",
    allocation_table="allocations",
    customer_item_plain=customer_expected_plain,
    allocation_items_typed=[allocation_expected],
    customer_action=apply_result["customer_action"],
    allocation_results=apply_result["allocation_results"],
)
conflict_plain = {**customer_expected_plain, "fwmark": "0x99999"}
try:
    lib.apply_backend_payloads(
        region="us-east-1",
        customer_table="customers",
        allocation_table="allocations",
        customer_item_plain=conflict_plain,
        allocation_items_typed=[allocation_expected],
    )
    conflict_blocked = False
except RuntimeError:
    conflict_blocked = True

print(
    json.dumps(
        {
            "customer_action": apply_result["customer_action"],
            "allocation_actions": [item["action"] for item in apply_result["allocation_results"]],
            "put_call_count": len(put_calls),
            "delete_call_count": len(delete_calls),
            "validation_valid": validation_result["valid"],
            "customer_stable_match": validation_result["customer_stable_match"],
            "rollback_status": rollback_result["status"],
            "customer_still_present": bool(stores["customers"]),
            "allocation_still_present": bool(stores["allocations"]),
            "conflict_blocked": conflict_blocked,
        },
        sort_keys=True,
    )
)
''',
        pythonpath=REPO_ROOT / "scripts" / "customers",
    )
    if live_backend_idempotency.get("customer_action") != "already_present_metadata_diff":
        raise SystemExit("Live backend idempotency must accept customer metadata-only differences")
    if live_backend_idempotency.get("allocation_actions") != ["already_present_metadata_diff"]:
        raise SystemExit("Live backend idempotency must accept allocation metadata-only differences")
    if live_backend_idempotency.get("put_call_count") != 0:
        raise SystemExit("Metadata-only live backend reapply must not rewrite DynamoDB records")
    if live_backend_idempotency.get("delete_call_count") != 0:
        raise SystemExit("Metadata-only live backend rollback must not delete pre-existing records")
    if not live_backend_idempotency.get("validation_valid"):
        raise SystemExit("Live backend validation must accept metadata-only differences")
    if not live_backend_idempotency.get("customer_stable_match"):
        raise SystemExit("Live backend validation must report stable customer match")
    if not live_backend_idempotency.get("customer_still_present"):
        raise SystemExit("Live backend idempotent rollback removed the customer record")
    if not live_backend_idempotency.get("allocation_still_present"):
        raise SystemExit("Live backend idempotent rollback removed the allocation record")
    if not live_backend_idempotency.get("conflict_blocked"):
        raise SystemExit("Live backend idempotency allowed a real customer conflict")
    live_apply_source = (REPO_ROOT / "scripts" / "customers" / "live_apply_lib.py").read_text(encoding="utf-8")
    if "_backend_apply_created_records" not in live_apply_source:
        raise SystemExit("Live apply must gate rollback on records created by the current apply")
    if "_inject_live_headend_secret" not in live_apply_source or "resolve_headend_psk_secret" not in live_apply_source:
        raise SystemExit("Live SSH apply must resolve head-end PSK secrets before copying customer artifacts")
    record_step("live_backend_idempotent_reapply_gate", live_backend_idempotency)

    live_secret_root = BUILD_ROOT / "live-secret-injection"
    if live_secret_root.exists():
        shutil.rmtree(live_secret_root)
    live_secret_root.mkdir(parents=True, exist_ok=True)
    live_secret_injection = _run_python_json(
        r'''
import hashlib
import json
import os
from pathlib import Path

import live_apply_lib


secret_value = 'repo-verification-psk-"quoted"-with-backslash\\'
secret_ref = "/rpdb/test/customer/psk"
root = Path(os.environ["RPDB_VERIFY_SECRET_ROOT"])
package_dir = root / "package"
package_dir.mkdir(parents=True, exist_ok=True)
(package_dir / "customer-module.json").write_text(
    json.dumps({"peer": {"psk_secret_ref": secret_ref}}, sort_keys=True),
    encoding="utf-8",
)
swanctl_conf = root / "headend" / "etc" / "swanctl" / "conf.d" / "rpdb-customers" / "customer.conf"
swanctl_conf.parent.mkdir(parents=True, exist_ok=True)
with swanctl_conf.open("w", encoding="utf-8", newline="\n") as handle:
    handle.write(
        "connections { }\n"
        "secrets {\n"
        "    ike-customer-psk {\n"
        "        id-1 = 198.51.100.10\n"
        "        secret = \"resolved-via-secret-store\"\n"
        "    }\n"
        "}\n"
    )


class Completed:
    returncode = 0
    stdout = secret_value + "\n"
    stderr = ""


def fake_run_local(command):
    if command[:3] != ["aws", "secretsmanager", "get-secret-value"]:
        raise AssertionError(f"unexpected command: {command}")
    if command[command.index("--region") + 1] != "us-east-1":
        raise AssertionError("secret resolution used the wrong region")
    if command[command.index("--secret-id") + 1] != secret_ref:
        raise AssertionError("secret resolution used the wrong secret ref")
    return Completed()


journal = []
live_apply_lib.run_local = fake_run_local
report = live_apply_lib._inject_live_headend_secret(
    journal,
    package_dir=package_dir,
    headend_prepared={"apply": {"swanctl_conf": str(swanctl_conf)}},
    region="us-east-1",
)
rendered = swanctl_conf.read_text(encoding="utf-8")
expected_hash = hashlib.sha256(secret_value.encode("utf-8")).hexdigest()
print(
    json.dumps(
        {
            "injected": report["injected"],
            "secret_ref": report["secret_ref"],
            "secret_hash_matches": report["secret_sha256"] == expected_hash,
            "secret_length_matches": report["secret_length"] == len(secret_value),
            "placeholder_removed": "resolved-via-secret-store" not in rendered,
            "rendered_contains_quoted_secret": "repo-verification-psk-\\\"quoted\\\"-with-backslash\\\\" in rendered,
            "journal_redacted": secret_value not in json.dumps(journal, sort_keys=True),
        },
        sort_keys=True,
    )
)
''',
        pythonpath=REPO_ROOT / "scripts" / "customers",
        extra_env={"RPDB_VERIFY_SECRET_ROOT": str(live_secret_root)},
    )
    if not live_secret_injection.get("injected"):
        raise SystemExit("Live head-end PSK secret injection did not report injected")
    if live_secret_injection.get("secret_ref") != "/rpdb/test/customer/psk":
        raise SystemExit("Live head-end PSK secret injection used the wrong secret ref")
    if not live_secret_injection.get("secret_hash_matches"):
        raise SystemExit("Live head-end PSK secret injection reported the wrong secret hash")
    if not live_secret_injection.get("secret_length_matches"):
        raise SystemExit("Live head-end PSK secret injection reported the wrong secret length")
    if not live_secret_injection.get("placeholder_removed"):
        raise SystemExit("Live head-end PSK secret injection left the placeholder secret")
    if not live_secret_injection.get("rendered_contains_quoted_secret"):
        raise SystemExit("Live head-end PSK secret injection did not swanctl-quote the secret")
    if not live_secret_injection.get("journal_redacted"):
        raise SystemExit("Live head-end PSK secret injection leaked the PSK into the journal")
    record_step("live_headend_secret_resolution_gate", live_secret_injection)

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

    vpn_headend_template = (REPO_ROOT / "infra" / "cfn" / "vpn-headend-unit.yaml").read_text(encoding="utf-8")
    resume_headend_bootstrap = (REPO_ROOT / "scripts" / "platform" / "resume_headend_bootstrap.sh").read_text(
        encoding="utf-8"
    )
    headend_bootstrap_probe = (REPO_ROOT / "scripts" / "platform" / "verify_headend_bootstrap.py").read_text(
        encoding="utf-8"
    )
    headend_install_lines = [
        line.strip()
        for line in vpn_headend_template.splitlines()
        if "dnf install -y awscli unzip jq conntrack-tools" in line
    ]
    if len(headend_install_lines) != 2:
        raise SystemExit("VPN head-end template must define exactly two base package install lines")
    if any("nftables" not in line for line in headend_install_lines):
        raise SystemExit("VPN head-end template must install nftables on both nodes")
    if any("iptables" in line for line in headend_install_lines):
        raise SystemExit("VPN head-end base package install must not include iptables packages")
    if "dnf install -y amazon-efs-utils unzip jq awscli conntrack-tools nftables" not in resume_headend_bootstrap:
        raise SystemExit("resume_headend_bootstrap.sh must install nftables")
    for required_probe_token in ("NFT_PRESENT=true", "nft --version", '"nft_present": nft_present'):
        if required_probe_token not in headend_bootstrap_probe:
            raise SystemExit(f"head-end bootstrap verifier is missing nftables probe token: {required_probe_token}")
    record_step(
        "headend_nftables_bootstrap_contract",
        {
            "vpn_headend_template": str(REPO_ROOT / "infra" / "cfn" / "vpn-headend-unit.yaml"),
            "install_line_count": len(headend_install_lines),
            "resume_bootstrap_requires_nftables": True,
            "readiness_probe_requires_nftables": True,
            "iptables_base_packages": 0,
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

    # Step 6b: verify customer-scoped DynamoDB lookup does not fall back to fleet scan,
    # while explicit fleet inventory still uses the scan path.
    runtime_ddb_boundary_code = textwrap.dedent(
        """
        import ipaddress
        import json
        import os
        from pathlib import Path

        from muxerlib.core import load_yaml
        from muxerlib.variables import load_module, load_modules
        import muxerlib.variables as variables

        module_dir = Path(os.environ["RPDB_VERIFY_MODULE_DIR"])
        cfg_path = Path(os.environ["RPDB_VERIFY_CFG"])
        global_cfg = load_yaml(cfg_path)
        global_cfg["customer_sot"] = {
            "backend": "dynamodb",
            "dynamodb": {
                "table_name": "rpdb-scale-boundary-test",
                "region": "us-east-1",
            },
        }
        overlay_pool = ipaddress.ip_network(str(global_cfg["overlay_pool"]), strict=False)

        counters = {"get_calls": 0, "scan_calls": 0}

        def fake_get(table_name, customer_name, region=None):
            counters["get_calls"] += 1
            if customer_name != "ddb-customer-scale":
                return None
            return {
                "id": 7100,
                "name": "ddb-customer-scale",
                "peer_ip": "198.18.220.10/32",
                "protocols": {"udp500": True, "udp4500": False, "esp50": True},
                "backend_underlay_ip": "172.31.220.10",
                "headend_egress_sources": ["172.31.221.10"],
                "rpdb_priority": 17100,
            }

        def fake_scan(table_name, region=None):
            counters["scan_calls"] += 1
            return [
                {
                    "id": 7100,
                    "name": "ddb-customer-scale",
                    "peer_ip": "198.18.220.10/32",
                    "protocols": {"udp500": True, "udp4500": False, "esp50": True},
                    "backend_underlay_ip": "172.31.220.10",
                    "headend_egress_sources": ["172.31.221.10"],
                    "rpdb_priority": 17100,
                }
            ]

        variables.load_customer_module_from_dynamodb = fake_get
        variables.load_customer_modules_from_dynamodb = fake_scan

        customer = load_module(
            "ddb-customer-scale",
            overlay_pool,
            cfg_dir=module_dir,
            customer_modules_dir=module_dir,
            customers_vars_path=module_dir / "customers.variables.yaml",
            global_cfg=global_cfg,
            source_backend="auto",
            allow_scan_fallback=False,
        )

        missing_error = ""
        try:
            load_module(
                "missing-customer",
                overlay_pool,
                cfg_dir=module_dir,
                customer_modules_dir=module_dir,
                customers_vars_path=module_dir / "customers.variables.yaml",
                global_cfg=global_cfg,
                source_backend="auto",
                allow_scan_fallback=False,
            )
        except SystemExit as exc:
            missing_error = str(exc)

        global_cfg["customer_sot"]["backend"] = "dynamodb_inventory"
        modules = load_modules(
            overlay_pool,
            cfg_dir=module_dir,
            customer_modules_dir=module_dir,
            customers_vars_path=module_dir / "customers.variables.yaml",
            global_cfg=global_cfg,
            source_backend="auto",
        )

        print(
            json.dumps(
                {
                    "customer_name": customer["name"],
                    "get_calls": counters["get_calls"],
                    "scan_calls": counters["scan_calls"],
                    "explicit_fleet_count": len(modules),
                    "missing_customer_error": missing_error,
                }
            )
        )
        """
    )
    runtime_ddb_boundary = _run_python_json(
        runtime_ddb_boundary_code,
        pythonpath=RUNTIME_SRC,
        extra_env={
            "RPDB_VERIFY_CFG": str(pass_cfg_path),
            "RPDB_VERIFY_MODULE_DIR": str(module_root),
        },
    )
    if runtime_ddb_boundary.get("customer_name") != "ddb-customer-scale":
        raise SystemExit("DynamoDB customer-scoped lookup did not return the expected customer")
    if runtime_ddb_boundary.get("get_calls") != 2:
        raise SystemExit("DynamoDB customer-scoped lookup did not use direct get-item semantics twice")
    if runtime_ddb_boundary.get("scan_calls") != 1:
        raise SystemExit("Explicit fleet inventory path did not exercise exactly one scan-backed load")
    if runtime_ddb_boundary.get("explicit_fleet_count") != 1:
        raise SystemExit("Explicit fleet inventory path did not return the expected module count")
    if "fleet scan fallback is disabled" not in str(runtime_ddb_boundary.get("missing_customer_error") or ""):
        raise SystemExit("Missing DynamoDB customer did not return the strict no-scan boundary error")
    record_step("runtime_dynamodb_boundary", runtime_ddb_boundary)

    # Step 7: verify customer-scoped delta apply/remove in pass-through mode without
    # full chain flush while the pass-through runtime remains nftables-only.
    delta_apply_state_root = BUILD_ROOT / "delta-apply-nft"
    if delta_apply_state_root.exists():
        shutil.rmtree(delta_apply_state_root)
    delta_apply_state_root.mkdir(parents=True, exist_ok=True)
    delta_apply_code = textwrap.dedent(
        """
        import builtins
        import ipaddress
        import json
        import os
        from pathlib import Path
        from muxerlib.core import load_yaml
        from muxerlib.variables import load_module, load_modules
        import muxerlib.modes as modes
        import muxerlib.nftables as nftables

        cfg_path = Path(os.environ["RPDB_VERIFY_CFG"])
        module_dir = Path(os.environ["RPDB_VERIFY_MODULE_DIR"])
        state_root = Path(os.environ["RPDB_VERIFY_NFT_STATE_ROOT"])
        global_cfg = load_yaml(cfg_path)
        global_cfg.setdefault("nftables", {}).setdefault("pass_through", {})
        global_cfg["nftables"]["pass_through"]["classification_backend"] = "nftables"
        global_cfg["nftables"]["pass_through"]["translation_backend"] = "nftables"
        global_cfg["nftables"]["pass_through"]["state_root"] = str(state_root)
        global_cfg["nftables"]["pass_through"]["nat_table_name"] = "muxer_passthrough_nat"
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
        classification_modules = load_modules(
            overlay_pool,
            cfg_dir=module_dir,
            customer_modules_dir=module_dir,
            customers_vars_path=module_dir / "customers.variables.yaml",
            global_cfg=global_cfg,
            source_backend="customer_modules",
        )

        counts = {
            "flush_chain": 0,
            "ensure_policy": 0,
            "remove_policy": 0,
            "remove_tunnel": 0,
            "nft_apply_calls": 0,
            "nft_delete_calls": 0,
        }

        modes.ensure_chain = lambda *args, **kwargs: None
        modes.ensure_jump = lambda *args, **kwargs: None
        modes.remove_jump = lambda *args, **kwargs: None
        modes.ensure_local_ipv4 = lambda *args, **kwargs: None
        modes.remove_local_ipv4 = lambda *args, **kwargs: None
        modes.ensure_tunnel = lambda *args, **kwargs: None
        modes.flush_chain = lambda *args, **kwargs: counts.__setitem__("flush_chain", counts["flush_chain"] + 1)
        modes.ensure_policy = lambda *args, **kwargs: counts.__setitem__("ensure_policy", counts["ensure_policy"] + 1)
        modes.remove_policy = lambda *args, **kwargs: counts.__setitem__("remove_policy", counts["remove_policy"] + 1)
        modes.flush_route_table = lambda *args, **kwargs: None
        modes.remove_tunnel = lambda *args, **kwargs: counts.__setitem__("remove_tunnel", counts["remove_tunnel"] + 1)

        def record_nft_must(args, *unused_args, **unused_kwargs):
            cmd = list(args)
            if cmd[:2] == ["nft", "-f"]:
                counts["nft_apply_calls"] += 1

        def record_nft_sh(args, *unused_args, **unused_kwargs):
            cmd = list(args)
            if cmd[:3] == ["nft", "delete", "table"]:
                counts["nft_delete_calls"] += 1

        nftables.must = record_nft_must
        nftables.sh = record_nft_sh
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
            classification_backend="nftables",
            translation_backend="nftables",
            classification_state_root=str(state_root),
            classification_table_name="muxer_passthrough",
            translation_table_name="muxer_passthrough_nat",
            classification_modules=classification_modules,
        )
        model_path = state_root / "pass-through-state-model.json"
        script_path = state_root / "pass-through-state.nft"
        apply_model = json.loads(model_path.read_text(encoding="utf-8"))
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
            classification_backend="nftables",
            translation_backend="nftables",
            classification_state_root=str(state_root),
            classification_table_name="muxer_passthrough",
            translation_table_name="muxer_passthrough_nat",
            classification_modules=classification_modules,
            pub_if="ens34",
            public_ip=str(global_cfg["public_ip"]),
            public_priv_ip=str((global_cfg.get("interfaces") or {}).get("public_private_ip") or global_cfg["public_ip"]),
            default_drop=True,
        )
        remove_model = json.loads(model_path.read_text(encoding="utf-8"))
        import sys
        sys.stdout.write(
            json.dumps(
                {
                    **counts,
                    "classification_module_count": len(classification_modules),
                    "artifact_script_exists": script_path.exists(),
                    "artifact_model_exists": model_path.exists(),
                    "apply_render_mode": apply_model["render_mode"],
                    "apply_customer_count": apply_model["customer_count"],
                    "remove_customer_count": remove_model["customer_count"],
                }
            )
        )
        """
    )
    delta_apply_result = _run_python_json(
        delta_apply_code,
        pythonpath=RUNTIME_SRC,
        extra_env={
            "RPDB_VERIFY_CFG": str(pass_cfg_path),
            "RPDB_VERIFY_MODULE_DIR": str(module_root),
            "RPDB_VERIFY_NFT_STATE_ROOT": str(delta_apply_state_root),
        },
    )
    if delta_apply_result["flush_chain"] != 0:
        raise SystemExit("customer-scoped delta apply unexpectedly flushed chains")
    if delta_apply_result["nft_apply_calls"] != 2:
        raise SystemExit("customer-scoped delta apply/remove did not program nftables classification twice")
    if delta_apply_result["nft_delete_calls"] != 4:
        raise SystemExit("customer-scoped delta apply/remove did not replace both shared nftables tables on each render")
    if not delta_apply_result["artifact_script_exists"] or not delta_apply_result["artifact_model_exists"]:
        raise SystemExit("customer-scoped delta apply/remove did not write nftables artifacts")
    if delta_apply_result["apply_render_mode"] != "nftables-live-pass-through":
        raise SystemExit("customer-scoped delta apply/remove did not use the live nftables classification render mode")
    if delta_apply_result["apply_customer_count"] != delta_apply_result["classification_module_count"]:
        raise SystemExit("customer-scoped delta apply/remove did not render the full classification inventory on apply")
    if delta_apply_result["remove_customer_count"] != (delta_apply_result["classification_module_count"] - 1):
        raise SystemExit("customer-scoped delta apply/remove did not rebuild the remaining classification inventory on remove")
    record_step("pass_through_delta_apply_remove", delta_apply_result)

    # Step 7b: verify the explicit fleet apply path also switches pass-through
    # classification, translation, and bridge activation to nftables.
    full_apply_state_root = BUILD_ROOT / "full-apply-nft"
    if full_apply_state_root.exists():
        shutil.rmtree(full_apply_state_root)
    full_apply_state_root.mkdir(parents=True, exist_ok=True)
    full_apply_code = textwrap.dedent(
        """
        import builtins
        import ipaddress
        import json
        import os
        from pathlib import Path
        from muxerlib.core import load_yaml
        from muxerlib.variables import load_modules
        import muxerlib.modes as modes
        import muxerlib.nftables as nftables

        cfg_path = Path(os.environ["RPDB_VERIFY_CFG"])
        module_dir = Path(os.environ["RPDB_VERIFY_MODULE_DIR"])
        state_root = Path(os.environ["RPDB_VERIFY_NFT_STATE_ROOT"])
        global_cfg = load_yaml(cfg_path)
        global_cfg.setdefault("nftables", {}).setdefault("pass_through", {})
        global_cfg["nftables"]["pass_through"]["classification_backend"] = "nftables"
        global_cfg["nftables"]["pass_through"]["translation_backend"] = "nftables"
        global_cfg["nftables"]["pass_through"]["state_root"] = str(state_root)
        global_cfg["nftables"]["pass_through"]["nat_table_name"] = "muxer_passthrough_nat"
        overlay_pool = ipaddress.ip_network(str(global_cfg["overlay_pool"]), strict=False)
        modules = load_modules(
            overlay_pool,
            cfg_dir=module_dir,
            customer_modules_dir=module_dir,
            customers_vars_path=module_dir / "customers.variables.yaml",
            global_cfg=global_cfg,
            source_backend="customer_modules",
        )

        counts = {
            "flush_chain": 0,
            "nft_apply_calls": 0,
            "nft_delete_calls": 0,
        }

        modes.ensure_chain = lambda *args, **kwargs: None
        modes.ensure_jump = lambda *args, **kwargs: None
        modes.remove_jump = lambda *args, **kwargs: None
        modes.ensure_local_ipv4 = lambda *args, **kwargs: None
        modes.remove_local_ipv4 = lambda *args, **kwargs: None
        modes.ensure_tunnel = lambda *args, **kwargs: None
        modes.ensure_policy = lambda *args, **kwargs: None
        modes.flush_route_table = lambda *args, **kwargs: None
        modes.flush_chain = lambda *args, **kwargs: counts.__setitem__("flush_chain", counts["flush_chain"] + 1)

        def record_nft_must(args, *unused_args, **unused_kwargs):
            cmd = list(args)
            if cmd[:2] == ["nft", "-f"]:
                counts["nft_apply_calls"] += 1

        def record_nft_sh(args, *unused_args, **unused_kwargs):
            cmd = list(args)
            if cmd[:3] == ["nft", "delete", "table"]:
                counts["nft_delete_calls"] += 1

        nftables.must = record_nft_must
        nftables.sh = record_nft_sh
        builtins.print = lambda *args, **kwargs: None

        modes.apply_passthrough(
            modules,
            "ens34",
            "ens35",
            str(global_cfg["public_ip"]),
            str((global_cfg.get("interfaces") or {}).get("public_private_ip") or global_cfg["public_ip"]),
            str((global_cfg.get("interfaces") or {}).get("inside_ip")),
            str(global_cfg.get("backend_underlay_ip") or "172.31.40.220"),
            "interface_ip",
            overlay_pool,
            int((global_cfg.get("allocation") or {}).get("base_table", 2000)),
            int(str((global_cfg.get("allocation") or {}).get("base_mark", "0x2000")), 0),
            "MUXER_MANGLE",
            "MUXER_FILTER",
            True,
            "MUXER_NAT_PRE",
            "MUXER_NAT_POST",
            "MUXER_MANGLE_POST",
            False,
            2101,
            2102,
            True,
            False,
            2111,
            2112,
            True,
            True,
            "nftables",
            "nftables",
            "nftables",
            str(state_root),
            "muxer_passthrough",
            "muxer_passthrough_nat",
        )
        model_path = state_root / "pass-through-state-model.json"
        script_path = state_root / "pass-through-state.nft"
        model = json.loads(model_path.read_text(encoding="utf-8"))
        import sys
        sys.stdout.write(
            json.dumps(
                {
                    **counts,
                    "module_count": len(modules),
                    "artifact_script_exists": script_path.exists(),
                    "artifact_model_exists": model_path.exists(),
                    "render_mode": model["render_mode"],
                    "customer_count": model["customer_count"],
                }
            )
        )
        """
    )
    full_apply_result = _run_python_json(
        full_apply_code,
        pythonpath=RUNTIME_SRC,
        extra_env={
            "RPDB_VERIFY_CFG": str(pass_cfg_path),
            "RPDB_VERIFY_MODULE_DIR": str(module_root),
            "RPDB_VERIFY_NFT_STATE_ROOT": str(full_apply_state_root),
        },
    )
    if full_apply_result["nft_apply_calls"] != 1:
        raise SystemExit("fleet apply did not program the nftables classification backend exactly once")
    if full_apply_result["nft_delete_calls"] != 2:
        raise SystemExit("fleet apply did not replace both shared nftables tables before rendering")
    if not full_apply_result["artifact_script_exists"] or not full_apply_result["artifact_model_exists"]:
        raise SystemExit("fleet apply did not write nftables classification artifacts")
    if full_apply_result["render_mode"] != "nftables-live-pass-through":
        raise SystemExit("fleet apply did not render the live nftables classification backend")
    if full_apply_result["customer_count"] != full_apply_result["module_count"]:
        raise SystemExit("fleet apply did not render the full module set into nftables classification state")
    record_step("pass_through_nftables_full_apply", full_apply_result)

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

    # Step 9: verify the repo still emits the reviewable nftables artifacts for
    # pass-through classification outside the live apply path.
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

    # Step 9b: run the synthetic scale baseline harness against the current
    # nftables classification backend.
    scale_baseline_path = BUILD_ROOT / "scale-baseline-summary.json"
    scale_baseline = _run_json(
        [
            "python",
            str(MUXER_DIR / "scripts" / "run_scale_baseline.py"),
            "--muxer-config",
            str(pass_cfg_path),
            "--out",
            str(scale_baseline_path),
            "--json",
        ]
    )
    scenarios = scale_baseline.get("scenarios") or []
    expected_scenarios = len(scale_baseline.get("counts") or []) * len(scale_baseline.get("profiles") or [])
    if len(scenarios) != expected_scenarios:
        raise SystemExit("Scale baseline did not produce the expected number of scenarios")

    def _scenario(profile: str, customer_count: int) -> dict:
        for item in scenarios:
            if item.get("profile") == profile and int(item.get("customer_count") or 0) == customer_count:
                return item
        raise SystemExit(f"Scale baseline scenario missing: {profile}/{customer_count}")

    strict_100 = _scenario("strict_non_nat", 100)
    strict_20000 = _scenario("strict_non_nat", 20000)
    nat_100 = _scenario("nat_t", 100)
    nat_20000 = _scenario("nat_t", 20000)
    mixed_20000 = _scenario("mixed", 20000)
    netmap_20000 = _scenario("nat_t_netmap", 20000)
    force4500_100 = _scenario("force4500_bridge", 100)
    force4500_20000 = _scenario("force4500_bridge", 20000)
    natd_bridge_100 = _scenario("natd_bridge", 100)
    natd_bridge_20000 = _scenario("natd_bridge", 20000)

    if int(strict_20000["muxer_blocked_rule_model"]["transport_command_count"]) <= int(strict_100["muxer_blocked_rule_model"]["transport_command_count"]):
        raise SystemExit("Scale baseline did not preserve expected strict_non_nat transport command growth")
    if int(nat_20000["muxer_blocked_rule_model"]["transport_command_count"]) <= int(nat_100["muxer_blocked_rule_model"]["transport_command_count"]):
        raise SystemExit("Scale baseline did not preserve expected nat_t transport command growth")
    if int(strict_20000["muxer_blocked_rule_model"]["total_rules"]) != 0:
        raise SystemExit("Scale baseline strict_non_nat profile still emitted blocked muxer rules")
    if int(nat_20000["muxer_blocked_rule_model"]["total_rules"]) != 0:
        raise SystemExit("Scale baseline nat_t profile still emitted blocked muxer rules")
    if int(strict_20000["nftables_preview"]["deferred_translation_customer_count"]) != 0:
        raise SystemExit("Scale baseline strict_non_nat profile still reports deferred translation customers")
    if int(nat_20000["nftables_preview"]["deferred_translation_customer_count"]) != 0:
        raise SystemExit("Scale baseline nat_t profile still reports deferred translation customers")
    if int(force4500_20000["muxer_blocked_rule_model"]["bridge_total_rules"]) != 0:
        raise SystemExit("Scale baseline force4500 bridge profile still emitted blocked bridge rules")
    if int(natd_bridge_20000["muxer_blocked_rule_model"]["bridge_total_rules"]) != 0:
        raise SystemExit("Scale baseline natd bridge profile still emitted blocked bridge rules")
    if int(force4500_20000["nftables_preview"]["deferred_bridge_customer_count"]) != 0:
        raise SystemExit("Scale baseline force4500 bridge profile still reports deferred bridge customers")
    if int(natd_bridge_20000["nftables_preview"]["deferred_bridge_customer_count"]) != 0:
        raise SystemExit("Scale baseline natd bridge profile still reports deferred bridge customers")
    if int(force4500_20000["nftables_preview"]["bridge_set_entry_count"]) <= int(
        force4500_100["nftables_preview"]["bridge_set_entry_count"]
    ):
        raise SystemExit("Scale baseline force4500 bridge selector growth did not scale with customer count")
    if int(natd_bridge_20000["nftables_preview"]["bridge_set_entry_count"]) <= int(
        natd_bridge_100["nftables_preview"]["bridge_set_entry_count"]
    ):
        raise SystemExit("Scale baseline natd bridge selector growth did not scale with customer count")
    if int(force4500_20000["nftables_preview"]["bridge_manifest_entry_count"]) <= int(
        force4500_100["nftables_preview"]["bridge_manifest_entry_count"]
    ):
        raise SystemExit("Scale baseline force4500 bridge manifest growth did not scale with customer count")
    if int(natd_bridge_20000["nftables_preview"]["bridge_manifest_entry_count"]) <= int(
        natd_bridge_100["nftables_preview"]["bridge_manifest_entry_count"]
    ):
        raise SystemExit("Scale baseline natd bridge manifest growth did not scale with customer count")
    netmap_headend_runtime = netmap_20000["headend_post_ipsec_nat_runtime"]
    if netmap_headend_runtime.get("activation_backend") != "nftables":
        raise SystemExit("Scale baseline post-IPsec NAT activation backend must be nftables")
    if int(netmap_headend_runtime["apply_command_count"]) <= 0:
        raise SystemExit("Scale baseline did not produce post-IPsec NAT command growth for the netmap profile")
    if int(netmap_headend_runtime.get("blocked_apply_command_count") or 0) != 0:
        raise SystemExit("Scale baseline still reports blocked post-IPsec NAT apply commands")
    mixed_mix = mixed_20000.get("customer_mix") or {}
    if int(mixed_mix.get("strict_non_nat") or 0) != 10000 or int(mixed_mix.get("nat_t") or 0) != 10000:
        raise SystemExit("Scale baseline mixed profile did not produce the expected 50/50 customer mix")
    if not scale_baseline_path.exists():
        raise SystemExit("Scale baseline summary path was not written")
    record_step(
        "synthetic_scale_baseline",
        {
            "summary_path": str(scale_baseline_path),
            "scenario_count": len(scenarios),
            "classification_backend": scale_baseline.get("classification_backend"),
            "translation_backend": scale_baseline.get("translation_backend"),
            "bridge_backend": scale_baseline.get("bridge_backend"),
            "strict_non_nat_20000_blocked_rules": strict_20000["muxer_blocked_rule_model"]["total_rules"],
            "nat_t_20000_blocked_rules": nat_20000["muxer_blocked_rule_model"]["total_rules"],
            "force4500_bridge_20000_blocked_bridge_rules": force4500_20000["muxer_blocked_rule_model"]["bridge_total_rules"],
            "natd_bridge_20000_blocked_bridge_rules": natd_bridge_20000["muxer_blocked_rule_model"]["bridge_total_rules"],
            "force4500_bridge_20000_selector_entries": force4500_20000["nftables_preview"]["bridge_set_entry_count"],
            "natd_bridge_20000_selector_entries": natd_bridge_20000["nftables_preview"]["bridge_set_entry_count"],
            "force4500_bridge_20000_manifest_entries": force4500_20000["nftables_preview"]["bridge_manifest_entry_count"],
            "natd_bridge_20000_manifest_entries": natd_bridge_20000["nftables_preview"]["bridge_manifest_entry_count"],
            "nat_t_20000_nft_set_entries": nat_20000["nftables_preview"]["set_entry_count"],
            "nat_t_20000_nft_map_entries": nat_20000["nftables_preview"]["map_entry_count"],
            "nat_t_netmap_20000_headend_activation_backend": netmap_headend_runtime["activation_backend"],
            "nat_t_netmap_20000_headend_apply_commands": netmap_headend_runtime["apply_command_count"],
            "nat_t_netmap_20000_blocked_headend_apply_commands": netmap_headend_runtime["blocked_apply_command_count"],
        },
    )

    record_step(
        "synthetic_scale_nftables_only_gate",
        {
            "current_backend": scale_baseline.get("classification_backend"),
            "current_translation_backend": scale_baseline.get("translation_backend"),
            "current_bridge_backend": scale_baseline.get("bridge_backend"),
            "current_summary_path": str(scale_baseline_path),
            "strict_non_nat_20000_blocked_rules": strict_20000["muxer_blocked_rule_model"]["total_rules"],
            "nat_t_20000_blocked_rules": nat_20000["muxer_blocked_rule_model"]["total_rules"],
            "force4500_bridge_20000_blocked_bridge_rules": force4500_20000["muxer_blocked_rule_model"]["bridge_total_rules"],
            "natd_bridge_20000_blocked_bridge_rules": natd_bridge_20000["muxer_blocked_rule_model"]["bridge_total_rules"],
        },
    )

    # Step 9d: verify the RPDB translation, NFQUEUE bridge, and head-end NAT
    # design decisions exist in both human-readable and machine-checkable form,
    # and that they are anchored to the current measured baseline.
    scale_decision_manifest_path = MUXER_DIR / "config" / "scale-decisions.yaml"
    scale_decision_doc_path = MUXER_DIR / "docs" / "TRANSLATION_AND_BRIDGE_SCALE_DECISIONS.md"
    scale_decision_manifest = yaml.safe_load(scale_decision_manifest_path.read_text(encoding="utf-8"))
    scale_decision_doc = scale_decision_doc_path.read_text(encoding="utf-8")
    if int(scale_decision_manifest.get("schema_version") or 0) != 1:
        raise SystemExit("Scale decision manifest schema_version must be 1")
    if int(scale_decision_manifest.get("phase") or 0) != 2:
        raise SystemExit("Scale decision manifest must describe the Phase 2 design gate")

    translation_decision = ((scale_decision_manifest.get("translation") or {}).get("decision") or "").strip()
    bridge_decision = ((scale_decision_manifest.get("nfqueue_bridge") or {}).get("decision") or "").strip()
    headend_decision = ((scale_decision_manifest.get("headend_post_ipsec_nat") or {}).get("decision") or "").strip()
    if translation_decision != "nftables_nat_maps":
        raise SystemExit("Scale decision manifest translation strategy is missing or incorrect")
    if bridge_decision != "nftables_selector_sets_plus_manifested_bridge_worker":
        raise SystemExit("Scale decision manifest NFQUEUE bridge strategy is missing or incorrect")
    if headend_decision != "nftables_nat_artifacts":
        raise SystemExit("Scale decision manifest head-end NAT strategy is missing or incorrect")

    headend_manifest = scale_decision_manifest.get("headend_post_ipsec_nat") or {}
    prohibited_headend_paths = set(headend_manifest.get("prohibited_paths") or [])
    required_prohibited_headend_paths = {
        "muxer3_runtime_or_deploy_fallback",
        "non_nft_firewall_activation",
        "non_nft_restore_activation",
    }
    if not required_prohibited_headend_paths.issubset(prohibited_headend_paths):
        missing_paths = sorted(required_prohibited_headend_paths - prohibited_headend_paths)
        raise SystemExit(f"Scale decision manifest is missing prohibited head-end paths: {missing_paths}")
    fallback_policy = headend_manifest.get("fallback_policy") or {}
    if fallback_policy.get("non_nft_firewall_allowed") is not False:
        raise SystemExit("Scale decision manifest must prohibit non-nft firewall fallback")
    if fallback_policy.get("non_nft_restore_allowed") is not False:
        raise SystemExit("Scale decision manifest must prohibit non-nft restore activation")
    if fallback_policy.get("muxer3_allowed") is not False:
        raise SystemExit("Scale decision manifest must prohibit MUXER3 as a head-end fallback")
    if fallback_policy.get("requires_stop_and_redesign") is not True:
        raise SystemExit("Scale decision manifest must require stop-and-redesign instead of fallback")

    translation_baseline = (scale_decision_manifest.get("translation") or {}).get("baseline_mapping") or {}
    bridge_baseline = (scale_decision_manifest.get("nfqueue_bridge") or {}).get("baseline_mapping") or {}
    headend_baseline = headend_manifest.get("baseline_mapping") or {}
    if int(translation_baseline.get("strict_non_nat_20000_blocked_rules") or 0) != int(strict_20000["muxer_blocked_rule_model"]["total_rules"]):
        raise SystemExit("Scale decision manifest strict non-NAT blocked-rule baseline is out of sync")
    if int(translation_baseline.get("nat_t_20000_blocked_rules") or 0) != int(nat_20000["muxer_blocked_rule_model"]["total_rules"]):
        raise SystemExit("Scale decision manifest NAT-T blocked-rule baseline is out of sync")
    if int(bridge_baseline.get("force4500_bridge_20000_blocked_bridge_rules") or 0) != int(
        force4500_20000["muxer_blocked_rule_model"]["bridge_total_rules"]
    ):
        raise SystemExit("Scale decision manifest force4500 blocked bridge baseline is out of sync")
    if int(bridge_baseline.get("natd_bridge_20000_blocked_bridge_rules") or 0) != int(
        natd_bridge_20000["muxer_blocked_rule_model"]["bridge_total_rules"]
    ):
        raise SystemExit("Scale decision manifest natd blocked bridge baseline is out of sync")
    if int(headend_baseline.get("nat_t_netmap_20000_headend_apply_commands") or 0) != int(
        netmap_headend_runtime["apply_command_count"]
    ):
        raise SystemExit("Scale decision manifest head-end NAT baseline is out of sync with the measured scale harness")
    if int(headend_baseline.get("nat_t_netmap_20000_blocked_headend_apply_commands") or 0) != int(
        netmap_headend_runtime.get("blocked_apply_command_count") or 0
    ):
        raise SystemExit("Scale decision manifest blocked head-end NAT apply baseline is out of sync")
    if int(headend_baseline.get("nat_t_netmap_20000_blocked_headend_rollback_commands") or 0) != int(
        netmap_headend_runtime.get("blocked_rollback_command_count") or 0
    ):
        raise SystemExit("Scale decision manifest blocked head-end NAT rollback baseline is out of sync")

    for required_heading in (
        "## 1. Muxer Translation Decision",
        "## 2. NFQUEUE Bridge Decision",
        "## 3. Head-End Post-IPsec NAT Decision",
    ):
        if required_heading not in scale_decision_doc:
            raise SystemExit(f"Scale decision doc is missing required section heading: {required_heading}")
    record_step(
        "translation_bridge_scale_decisions",
        {
            "manifest_path": str(scale_decision_manifest_path),
            "doc_path": str(scale_decision_doc_path),
            "translation_strategy": translation_decision,
            "nfqueue_bridge_strategy": bridge_decision,
            "headend_nat_strategy": headend_decision,
            "headend_nat_prohibited_paths": sorted(prohibited_headend_paths),
            "translation_baseline_source": "synthetic_scale_baseline",
            "bridge_baseline_source": "synthetic_scale_baseline",
        },
    )

    # Step 9d2: generate an explicit scale gate report from the measured summary
    # and the committed threshold manifest, then verify repeated generation
    # produces the same pass/fail matrix.
    scale_threshold_path = MUXER_DIR / "config" / "scale-thresholds.json"
    scale_report_path_a = BUILD_ROOT / "scale-gate-report-a.json"
    scale_report_path_b = BUILD_ROOT / "scale-gate-report-b.json"
    scale_report_md_path = BUILD_ROOT / "scale-gate-report.md"
    scale_report_a = _run_json(
        [
            "python",
            str(MUXER_DIR / "scripts" / "generate_scale_report.py"),
            "--summary",
            str(scale_baseline_path),
            "--thresholds",
            str(scale_threshold_path),
            "--out-json",
            str(scale_report_path_a),
            "--out-md",
            str(scale_report_md_path),
            "--json",
        ]
    )
    scale_report_b = _run_json(
        [
            "python",
            str(MUXER_DIR / "scripts" / "generate_scale_report.py"),
            "--summary",
            str(scale_baseline_path),
            "--thresholds",
            str(scale_threshold_path),
            "--out-json",
            str(scale_report_path_b),
            "--json",
        ]
    )
    if not scale_report_path_a.exists() or not scale_report_path_b.exists() or not scale_report_md_path.exists():
        raise SystemExit("Scale gate report outputs were not written")

    def _normalize_scale_report(report: dict) -> list[dict]:
        normalized: list[dict] = []
        for item in report.get("evaluations") or []:
            normalized.append(
                {
                    "profile": item.get("profile"),
                    "customer_count": int(item.get("customer_count") or 0),
                    "status": item.get("status"),
                    "failed_checks": list(item.get("failed_checks") or []),
                }
            )
        return sorted(normalized, key=lambda item: (str(item["profile"]), int(item["customer_count"])))

    normalized_report_a = _normalize_scale_report(scale_report_a)
    normalized_report_b = _normalize_scale_report(scale_report_b)
    if normalized_report_a != normalized_report_b:
        raise SystemExit("Repeated scale gate reports did not agree on pass/fail outcomes")
    if scale_report_a.get("missing_targets") or scale_report_b.get("missing_targets"):
        raise SystemExit("Scale gate report is missing one or more target scenarios")
    failed_scale_evaluations = [item for item in normalized_report_a if item["status"] != "passed"]
    record_step(
        "explicit_scale_gate_report",
        {
            "threshold_path": str(scale_threshold_path),
            "summary_path": str(scale_baseline_path),
            "report_json": str(scale_report_path_a),
            "report_markdown": str(scale_report_md_path),
            "overall_status": scale_report_a.get("overall_status"),
            "failed_evaluation_count": len(failed_scale_evaluations),
            "failed_evaluations": failed_scale_evaluations,
        },
    )

    # Step 9e: verify the NFQUEUE bridge path uses the shared nftables selector
    # sets plus manifest model in customer-scoped delta operations.
    bridge_delta_state_root = BUILD_ROOT / "bridge-delta-nft"
    if bridge_delta_state_root.exists():
        shutil.rmtree(bridge_delta_state_root)
    bridge_delta_state_root.mkdir(parents=True, exist_ok=True)
    bridge_delta_code = textwrap.dedent(
        """
        import builtins
        import json
        import os
        from pathlib import Path

        from muxerlib.core import load_yaml
        import muxerlib.modes as modes
        import muxerlib.nftables as nftables

        cfg_path = Path(os.environ["RPDB_VERIFY_CFG"])
        state_root = Path(os.environ["RPDB_VERIFY_NFT_STATE_ROOT"])
        global_cfg = load_yaml(cfg_path)
        global_cfg.setdefault("nftables", {}).setdefault("pass_through", {})
        global_cfg["nftables"]["pass_through"]["classification_backend"] = "nftables"
        global_cfg["nftables"]["pass_through"]["translation_backend"] = "nftables"
        global_cfg["nftables"]["pass_through"]["bridge_backend"] = "nftables"
        global_cfg["nftables"]["pass_through"]["state_root"] = str(state_root)
        global_cfg["nftables"]["pass_through"]["nat_table_name"] = "muxer_passthrough_nat"

        modules = [
            {
                "id": 501,
                "name": "bridge-force4500",
                "peer_ip": "198.18.60.1/32",
                "protocols": {
                    "udp500": True,
                    "udp4500": False,
                    "esp50": True,
                    "force_rewrite_4500_to_500": True,
                },
                "backend_underlay_ip": "172.31.200.51",
                "headend_egress_sources": ["172.31.210.51"],
                "ipip_ifname": "gre-bridge-0501",
                "tunnel_type": "gre",
                "tunnel_key": 60501,
                "rpdb_priority": 90501,
                "overlay": {
                    "mux_ip": "169.254.60.1/30",
                    "router_ip": "169.254.60.2/30",
                },
            },
            {
                "id": 502,
                "name": "bridge-natd",
                "peer_ip": "198.18.60.2/32",
                "protocols": {
                    "udp500": True,
                    "udp4500": False,
                    "esp50": False,
                },
                "natd_rewrite": {
                    "enabled": True,
                    "initiator_inner_ip": "10.250.0.20",
                },
                "backend_underlay_ip": "172.31.200.52",
                "headend_egress_sources": ["172.31.210.52"],
                "ipip_ifname": "gre-bridge-0502",
                "tunnel_type": "gre",
                "tunnel_key": 60502,
                "rpdb_priority": 90502,
                "overlay": {
                    "mux_ip": "169.254.61.1/30",
                    "router_ip": "169.254.61.2/30",
                },
            },
        ]

        counts = {
            "flush_chain": 0,
            "remove_policy": 0,
            "remove_tunnel": 0,
            "nft_apply_calls": 0,
            "nft_delete_calls": 0,
        }

        modes.ensure_chain = lambda *args, **kwargs: None
        modes.ensure_jump = lambda *args, **kwargs: None
        modes.remove_jump = lambda *args, **kwargs: None
        modes.ensure_local_ipv4 = lambda *args, **kwargs: None
        modes.remove_local_ipv4 = lambda *args, **kwargs: None
        modes.ensure_tunnel = lambda *args, **kwargs: None
        modes.ensure_policy = lambda *args, **kwargs: None
        modes.flush_route_table = lambda *args, **kwargs: None
        modes.flush_chain = lambda *args, **kwargs: counts.__setitem__("flush_chain", counts["flush_chain"] + 1)
        modes.remove_policy = lambda *args, **kwargs: counts.__setitem__("remove_policy", counts["remove_policy"] + 1)
        modes.remove_tunnel = lambda *args, **kwargs: counts.__setitem__("remove_tunnel", counts["remove_tunnel"] + 1)

        def record_nft_must(args, *unused_args, **unused_kwargs):
            cmd = list(args)
            if cmd[:2] == ["nft", "-f"]:
                counts["nft_apply_calls"] += 1

        def record_nft_sh(args, *unused_args, **unused_kwargs):
            cmd = list(args)
            if cmd[:3] == ["nft", "delete", "table"]:
                counts["nft_delete_calls"] += 1

        nftables.must = record_nft_must
        nftables.sh = record_nft_sh
        builtins.print = lambda *args, **kwargs: None

        modes.apply_customer_passthrough(
            modules[0],
            pub_if="ens34",
            inside_if="ens35",
            public_ip=str(global_cfg["public_ip"]),
            public_priv_ip=str((global_cfg.get("interfaces") or {}).get("public_private_ip") or global_cfg["public_ip"]),
            inside_ip=str((global_cfg.get("interfaces") or {}).get("inside_ip")),
            backend_ul=str(global_cfg.get("backend_underlay_ip") or "172.31.40.220"),
            transport_local_mode="interface_ip",
            overlay_pool=None,
            base_table=int((global_cfg.get("allocation") or {}).get("base_table", 2000)),
            base_mark=int(str((global_cfg.get("allocation") or {}).get("base_mark", "0x2000")), 0),
            mangle_chain="MUXER_MANGLE",
            filter_chain="MUXER_FILTER",
            nat_rewrite=True,
            nat_pre_chain="MUXER_NAT_PRE",
            nat_post_chain="MUXER_NAT_POST",
            mangle_post_chain="MUXER_MANGLE_POST",
            nfqueue_enabled=True,
            nfqueue_queue_in=2101,
            nfqueue_queue_out=2102,
            nfqueue_queue_bypass=True,
            natd_dpi_enabled=True,
            natd_dpi_queue_in=2111,
            natd_dpi_queue_out=2112,
            natd_dpi_queue_bypass=True,
            default_drop=True,
            classification_backend="nftables",
            translation_backend="nftables",
            bridge_backend="nftables",
            classification_state_root=str(state_root),
            classification_table_name="muxer_passthrough",
            translation_table_name="muxer_passthrough_nat",
            classification_modules=modules,
        )

        model_path = state_root / "pass-through-state-model.json"
        script_path = state_root / "pass-through-state.nft"
        bridge_manifest_path = state_root / "pass-through-bridge-manifest.json"
        apply_model = json.loads(model_path.read_text(encoding="utf-8"))
        apply_bridge_manifest = json.loads(bridge_manifest_path.read_text(encoding="utf-8"))

        modes.remove_customer_passthrough(
            modules[0],
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
            nfqueue_enabled=True,
            nfqueue_queue_in=2101,
            nfqueue_queue_out=2102,
            nfqueue_queue_bypass=True,
            natd_dpi_enabled=True,
            natd_dpi_queue_in=2111,
            natd_dpi_queue_out=2112,
            natd_dpi_queue_bypass=True,
            classification_backend="nftables",
            translation_backend="nftables",
            bridge_backend="nftables",
            classification_state_root=str(state_root),
            classification_table_name="muxer_passthrough",
            translation_table_name="muxer_passthrough_nat",
            classification_modules=modules,
            pub_if="ens34",
            public_ip=str(global_cfg["public_ip"]),
            public_priv_ip=str((global_cfg.get("interfaces") or {}).get("public_private_ip") or global_cfg["public_ip"]),
            default_drop=True,
        )

        remove_model = json.loads(model_path.read_text(encoding="utf-8"))
        remove_bridge_manifest = json.loads(bridge_manifest_path.read_text(encoding="utf-8"))

        def selector_total(payload, *keys):
            hooks = ((payload.get("bridge") or payload).get("queue_hooks") or {})
            return sum(int(((hooks.get(key) or {}).get("selector_count")) or 0) for key in keys)

        def manifest_total(payload):
            manifest = ((payload.get("bridge") or payload).get("manifest") or {})
            return sum(len(value or []) for value in manifest.values())

        import sys
        sys.stdout.write(
            json.dumps(
                {
                    **counts,
                    "artifact_script_exists": script_path.exists(),
                    "artifact_model_exists": model_path.exists(),
                    "bridge_manifest_exists": bridge_manifest_path.exists(),
                    "classification_module_count": len(modules),
                    "apply_render_mode": apply_model["render_mode"],
                    "apply_customer_count": apply_model["customer_count"],
                    "apply_bridge_backend": apply_model["bridge_backend"],
                    "apply_bridge_enabled": bool((apply_model.get("bridge") or {}).get("enabled")),
                    "apply_force4500_selector_count": selector_total(apply_model, "force4500_in", "force4500_out"),
                    "apply_natd_selector_count": selector_total(apply_model, "natd_in", "natd_out"),
                    "apply_manifest_entry_count": manifest_total(apply_bridge_manifest),
                    "apply_deferred_bridge_customer_count": len(apply_model.get("deferred_bridge_customers") or []),
                    "remove_customer_count": remove_model["customer_count"],
                    "remove_force4500_selector_count": selector_total(remove_model, "force4500_in", "force4500_out"),
                    "remove_natd_selector_count": selector_total(remove_model, "natd_in", "natd_out"),
                    "remove_manifest_entry_count": manifest_total(remove_bridge_manifest),
                    "remove_deferred_bridge_customer_count": len(remove_model.get("deferred_bridge_customers") or []),
                }
            )
        )
        """
    )
    bridge_delta_result = _run_python_json(
        bridge_delta_code,
        pythonpath=RUNTIME_SRC,
        extra_env={
            "RPDB_VERIFY_CFG": str(pass_cfg_path),
            "RPDB_VERIFY_NFT_STATE_ROOT": str(bridge_delta_state_root),
        },
    )
    if bridge_delta_result["flush_chain"] != 0:
        raise SystemExit("bridge delta apply unexpectedly flushed chains")
    if bridge_delta_result["nft_apply_calls"] != 2:
        raise SystemExit("bridge delta apply/remove did not program nftables state twice")
    if bridge_delta_result["nft_delete_calls"] != 4:
        raise SystemExit("bridge delta apply/remove did not replace both shared nftables tables on each render")
    if not (
        bridge_delta_result["artifact_script_exists"]
        and bridge_delta_result["artifact_model_exists"]
        and bridge_delta_result["bridge_manifest_exists"]
    ):
        raise SystemExit("bridge delta apply/remove did not write the expected nftables bridge artifacts")
    if bridge_delta_result["apply_render_mode"] != "nftables-live-pass-through":
        raise SystemExit("bridge delta apply/remove did not use the live nftables render mode")
    if bridge_delta_result["apply_customer_count"] != bridge_delta_result["classification_module_count"]:
        raise SystemExit("bridge delta apply/remove did not render the full bridge inventory on apply")
    if bridge_delta_result["remove_customer_count"] != (bridge_delta_result["classification_module_count"] - 1):
        raise SystemExit("bridge delta apply/remove did not rebuild the remaining bridge inventory on remove")
    if bridge_delta_result["apply_bridge_backend"] != "nftables" or not bridge_delta_result["apply_bridge_enabled"]:
        raise SystemExit("bridge delta apply/remove did not select the nftables bridge backend")
    if bridge_delta_result["apply_force4500_selector_count"] <= 0 or bridge_delta_result["apply_natd_selector_count"] <= 0:
        raise SystemExit("bridge delta apply/remove did not render both force4500 and natd selector groups")
    if bridge_delta_result["remove_force4500_selector_count"] != 0 or bridge_delta_result["remove_natd_selector_count"] <= 0:
        raise SystemExit("bridge delta apply/remove did not remove only the selected bridge customer inventory")
    if bridge_delta_result["remove_manifest_entry_count"] >= bridge_delta_result["apply_manifest_entry_count"]:
        raise SystemExit("bridge delta apply/remove did not shrink the bridge manifest after remove")
    if bridge_delta_result["apply_deferred_bridge_customer_count"] != 0 or bridge_delta_result["remove_deferred_bridge_customer_count"] != 0:
        raise SystemExit("bridge delta apply/remove still reported deferred bridge customers under the nftables bridge backend")
    record_step("pass_through_bridge_delta_apply_remove", bridge_delta_result)

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

    headend_customer_lib_text = (REPO_ROOT / "scripts" / "deployment" / "headend_customer_lib.py").read_text(
        encoding="utf-8"
    )
    if "systemctl is-active --quiet strongswan" not in headend_customer_lib_text:
        raise SystemExit("head-end customer apply/remove must tolerate inactive standby strongSwan services")
    if "strongswan is not active; staged config remains" not in headend_customer_lib_text:
        raise SystemExit("head-end customer apply must stage configs when standby strongSwan is inactive")
    if "head-end is standby; staged config remains" not in headend_customer_lib_text:
        raise SystemExit("head-end customer apply must stage customer payloads without activating standby dataplane")
    if "RPDB_HEADEND_APPLY_RUNTIME" not in headend_customer_lib_text:
        raise SystemExit("head-end customer apply must allow HA promotion to activate staged payloads")
    if "head-end initiate did not complete; customer config remains loaded" not in headend_customer_lib_text:
        raise SystemExit("head-end customer apply must not fail deployment when the peer is not yet responding")
    if "RPDB_HEADEND_RESET_IPSEC_ON_APPLY" not in headend_customer_lib_text:
        raise SystemExit("head-end customer apply must support customer-scoped IPsec reset on reapply/promotion")
    if 'swanctl --terminate --ike "${CUST}"' not in headend_customer_lib_text:
        raise SystemExit("head-end customer apply must reset same-customer IKE SAs before reloading")
    if 'swanctl --terminate --child "${CUST}-child"' not in headend_customer_lib_text:
        raise SystemExit("head-end customer apply must reset same-customer Child SAs before reloading")
    if "strongswan is not active; removed staged config" not in headend_customer_lib_text:
        raise SystemExit("head-end customer remove must tolerate inactive standby strongSwan services")
    if "include conf.d/rpdb-customers/*.conf" not in headend_customer_lib_text:
        raise SystemExit("head-end customer apply must ensure swanctl includes RPDB customer snippets")
    if 'nft list table "${NFT_FAMILY}" "${NFT_TABLE}"' not in headend_customer_lib_text:
        raise SystemExit("head-end post-IPsec NAT apply must detect an existing customer nftables table")
    if 'nft delete table "${NFT_FAMILY}" "${NFT_TABLE}"' not in headend_customer_lib_text:
        raise SystemExit("head-end post-IPsec NAT apply must replace existing customer nftables table before loading")
    ha_promote_text = (REPO_ROOT / "ops" / "headend-ha-active-standby" / "scripts" / "ha-promote.sh").read_text(
        encoding="utf-8"
    )
    if "RPDB_HEADEND_APPLY_RUNTIME=true" not in ha_promote_text:
        raise SystemExit("HA promote must activate staged RPDB customer dataplane payloads")
    vpn_headend_template_text = (REPO_ROOT / "infra" / "cfn" / "vpn-headend-unit.yaml").read_text(
        encoding="utf-8"
    )
    if vpn_headend_template_text.count("include conf.d/rpdb-customers/*.conf") < 4:
        raise SystemExit("VPN head-end bootstrap must include RPDB customer swanctl snippets on both nodes")
    record_step(
        "headend_standby_swanctl_reload_guard",
        {
            "source": str(REPO_ROOT / "scripts" / "deployment" / "headend_customer_lib.py"),
            "apply_stages_when_strongswan_inactive": True,
            "peer_initiate_failure_is_non_fatal": True,
            "remove_tolerates_inactive_strongswan": True,
            "customer_swanctl_include_enforced": True,
            "post_ipsec_nat_apply_replaces_existing_table": True,
            "standby_dataplane_activation_deferred": True,
            "ha_promote_loads_swanctl": "swanctl --load-all"
            in ha_promote_text,
            "ha_promote_activates_staged_customers": "RPDB_HEADEND_APPLY_RUNTIME=true" in ha_promote_text,
        },
    )

    muxer_customer_lib_text = (REPO_ROOT / "scripts" / "deployment" / "muxer_customer_lib.py").read_text(
        encoding="utf-8"
    )
    if "python3 /etc/muxer/src/muxctl.py flush" not in muxer_customer_lib_text:
        raise SystemExit("muxer customer apply must flush shared nftables state before runtime apply")
    if "python3 /etc/muxer/src/muxctl.py apply-customer" not in muxer_customer_lib_text:
        raise SystemExit("muxer customer apply must invoke the live muxer runtime customer apply path")
    if "python3 /etc/muxer/src/muxctl.py remove-customer" not in muxer_customer_lib_text:
        raise SystemExit("muxer customer remove must invoke the live muxer runtime customer remove path")
    if 'conntrack -D -p udp -s "${PEER_IP}" --dport "${PORT}"' not in muxer_customer_lib_text:
        raise SystemExit("muxer customer apply/remove must clear customer-scoped UDP conntrack state")
    if 'conntrack -D -p udp -d "${PEER_IP}" --sport "${PORT}"' not in muxer_customer_lib_text:
        raise SystemExit("muxer customer apply/remove must clear customer-scoped UDP return conntrack state")
    if 'Path("etc") / "muxer" / "config" / "customer-modules"' not in muxer_customer_lib_text:
        raise SystemExit("muxer customer modules must install under the runtime config/customer-modules inventory")
    if 'nft list table "${NFT_FAMILY}" "${NFT_TABLE}"' not in muxer_customer_lib_text:
        raise SystemExit("muxer customer firewall apply must detect an existing customer nftables table")
    if 'nft delete table "${NFT_FAMILY}" "${NFT_TABLE}"' not in muxer_customer_lib_text:
        raise SystemExit("muxer customer firewall apply must replace existing customer nftables table before loading")
    live_apply_lib_text = (REPO_ROOT / "scripts" / "customers" / "live_apply_lib.py").read_text(encoding="utf-8")
    for required_live_runtime_token in (
        "prepare_muxer_runtime_payload",
        "copy_muxer_runtime_payload",
        "validate_muxer_runtime_payload",
        '"runtime-package"',
        "/etc/muxer/src/muxerlib/nftables.py",
        "test -x /etc/muxer/src/muxctl.py",
        "dnat to ip saddr map",
        "snat to ip saddr . ip daddr map",
        "ipv4_addr : verdict",
    ):
        if required_live_runtime_token not in live_apply_lib_text:
            raise SystemExit(
                f"SSH live apply must sync and validate muxer runtime before customer apply: {required_live_runtime_token}"
            )
    runtime_nftables_text = (RUNTIME_ROOT / "src" / "muxerlib" / "nftables.py").read_text(encoding="utf-8")
    runtime_py39_incompatible_writes: list[str] = []
    for runtime_python in RUNTIME_SRC.rglob("*.py"):
        for line_number, line in enumerate(runtime_python.read_text(encoding="utf-8").splitlines(), 1):
            if "write_text(" in line and "newline=" in line:
                runtime_py39_incompatible_writes.append(f"{runtime_python}:{line_number}")
    if runtime_py39_incompatible_writes:
        raise SystemExit(
            "runtime package must avoid Path.write_text(newline=...) for Python 3.9 nodes: "
            + ", ".join(runtime_py39_incompatible_writes)
        )
    if 'sh(["nft", "delete", "table", "inet"' not in runtime_nftables_text:
        raise SystemExit("runtime nftables apply must replace the shared classifier table before loading")
    if 'sh(["nft", "delete", "table", "ip"' not in runtime_nftables_text:
        raise SystemExit("runtime nftables apply must replace the shared NAT table before loading")
    nft_nat_render_contract = _run_python_json(
        textwrap.dedent(
            """
            import json
            import sys
            from muxerlib.nftables import build_passthrough_nft_model, render_passthrough_nft_script

            nonnat_peer = "203.0.113.44"
            nat_t_peer = "203.0.113.45"
            nonnat_headend = "172.31.40.223"
            nat_t_headend = "172.31.40.222"
            modules = [
                {
                    "name": "contract-non-nat-customer",
                    "id": 4,
                    "peer_ip": f"{nonnat_peer}/32",
                    "backend_underlay_ip": nonnat_headend,
                    "protocols": {
                        "udp500": True,
                        "udp4500": False,
                        "esp50": True,
                        "force_rewrite_4500_to_500": False,
                    },
                    "headend_egress_sources": [nonnat_headend],
                },
                {
                    "name": "contract-nat-t-customer",
                    "id": 5,
                    "peer_ip": f"{nat_t_peer}/32",
                    "backend_underlay_ip": nat_t_headend,
                    "protocols": {
                        "udp500": True,
                        "udp4500": True,
                        "esp50": True,
                        "force_rewrite_4500_to_500": False,
                    },
                    "headend_egress_sources": [nat_t_headend],
                },
            ]
            global_cfg = {
                "public_ip": "23.20.31.151",
                "interfaces": {
                    "public_if": "ens34",
                    "public_private_ip": "172.31.33.150",
                },
                "firewall_policy": {
                    "default_drop_ipsec_to_public_ip": True,
                    "use_nat_rewrite": True,
                },
                "allocation": {
                    "base_mark": "0x2000",
                },
                "nftables": {
                    "pass_through": {
                        "classification_backend": "nftables",
                        "translation_backend": "nftables",
                        "bridge_backend": "nftables",
                        "state_root": "/tmp/rpdb-verify-nft",
                        "table_name": "muxer_passthrough",
                        "nat_table_name": "muxer_passthrough_nat",
                    },
                },
            }
            model = build_passthrough_nft_model(
                modules,
                global_cfg,
                render_mode="nftables-live-pass-through",
            )
            script = render_passthrough_nft_script(model)
            translation_maps = (model.get("translation") or {}).get("maps") or {}
            muxer_identities = {
                global_cfg["public_ip"],
                global_cfg["interfaces"]["public_private_ip"],
            }
            dnat_values = []
            for map_name in ("udp500_dnat", "udp4500_dnat", "esp_dnat"):
                dnat_values.extend((translation_maps.get(map_name) or {}).values())
            checks = {
                "dnat_uses_address_map": "dnat to ip saddr map @udp500_dnat" in script,
                "snat_uses_concat_address_map": "snat to ip saddr . ip daddr map @udp500_snat" in script,
                "dnat_map_type_is_address": "type ipv4_addr : ipv4_addr" in script,
                "snat_map_type_is_concat_address": "type ipv4_addr . ipv4_addr : ipv4_addr" in script,
                "strict_non_nat_udp500_dnat_targets_headend": (translation_maps.get("udp500_dnat") or {}).get(nonnat_peer) == f"dnat to {nonnat_headend}",
                "strict_non_nat_esp_dnat_targets_headend": (translation_maps.get("esp_dnat") or {}).get(nonnat_peer) == f"dnat to {nonnat_headend}",
                "nat_t_udp500_dnat_targets_headend": (translation_maps.get("udp500_dnat") or {}).get(nat_t_peer) == f"dnat to {nat_t_headend}",
                "nat_t_udp4500_dnat_targets_headend": (translation_maps.get("udp4500_dnat") or {}).get(nat_t_peer) == f"dnat to {nat_t_headend}",
                "nat_t_esp_dnat_targets_headend": (translation_maps.get("esp_dnat") or {}).get(nat_t_peer) == f"dnat to {nat_t_headend}",
                "no_pass_through_dnat_targets_muxer_identity": all(
                    str(value).replace("dnat to ", "").strip() not in muxer_identities
                    for value in dnat_values
                ),
                "no_verdict_nat_maps": "type ipv4_addr : verdict" not in script,
                "no_dnat_statements_inside_map": ": dnat to" not in script,
                "no_snat_statements_inside_map": ": snat to" not in script,
                "no_transport_fwmark_rules": "meta mark set" not in script,
                "script_lines": len(script.splitlines()),
            }
            sys.stdout.write(json.dumps(checks))
            """
        ),
        pythonpath=RUNTIME_SRC,
    )
    for check_name, passed in nft_nat_render_contract.items():
        if check_name != "script_lines" and not passed:
            raise SystemExit(f"runtime nftables NAT render contract failed: {check_name}")
    record_step(
        "muxer_runtime_customer_apply_gate",
        {
            "muxer_apply_invokes_runtime": True,
            "muxer_remove_invokes_runtime": True,
            "module_root_matches_runtime_inventory": True,
            "customer_nftables_tables_replaced": True,
            "shared_nftables_tables_replaced": True,
            "python39_runtime_write_text_compatible": True,
            "ssh_live_apply_syncs_muxer_runtime": True,
            "nft_nat_render_contract": nft_nat_render_contract,
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
            muxer_root / "etc" / "muxer" / "config" / "customer-modules" / customer_name,
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
    if ((phase6_customer2_apply.get("apply") or {}).get("mode")) != "staged_activation_apply":
        raise SystemExit("Phase 6 Customer 2 staged approved apply did not use the staged activation contract")
    if (((phase6_customer2_apply.get("apply") or {}).get("activation_contract") or {}).get("strategy")) != "node_local_activation_bundle":
        raise SystemExit("Phase 6 Customer 2 staged approved apply did not record the node-local activation strategy")

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
    if ((phase6_customer4_apply.get("apply") or {}).get("mode")) != "staged_activation_apply":
        raise SystemExit("Phase 6 Customer 4 staged approved apply did not use the staged activation contract")
    if (((phase6_customer4_apply.get("apply") or {}).get("activation_contract") or {}).get("strategy")) != "node_local_activation_bundle":
        raise SystemExit("Phase 6 Customer 4 staged approved apply did not record the node-local activation strategy")

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
        activation_bundles = apply.get("activation_bundles") or {}
        activation_artifacts: dict[str, dict[str, str]] = {}
        for component_name, activation in activation_bundles.items():
            request_path = _resolve_repo_path(str(activation.get("request_path") or ""))
            rollback_request_path = _resolve_repo_path(str(activation.get("rollback_request_path") or ""))
            activation_journal = _resolve_repo_path(str(activation.get("activation_journal") or ""))
            activation_result = _resolve_repo_path(str(activation.get("activation_result") or ""))
            if not request_path.exists():
                raise SystemExit(f"Phase 6 activation request missing for {customer_name}/{component_name}")
            if not rollback_request_path.exists():
                raise SystemExit(f"Phase 6 rollback request missing for {customer_name}/{component_name}")
            if not activation_journal.exists():
                raise SystemExit(f"Phase 6 activation journal missing for {customer_name}/{component_name}")
            if not activation_result.exists():
                raise SystemExit(f"Phase 6 activation result missing for {customer_name}/{component_name}")
            activation_artifacts[component_name] = {
                "request_path": str(request_path),
                "rollback_request_path": str(rollback_request_path),
                "activation_journal": str(activation_journal),
                "activation_result": str(activation_result),
            }
        phase6_artifacts[customer_name] = {
            "apply_journal": str(journal_path),
            "rollback_plan": str(rollback_plan_path),
            "published_root": str(published_root),
            "activation_contract": ((apply.get("activation_contract") or {}).get("strategy")),
            "activation_artifacts": activation_artifacts,
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
        phase7_root / "r" / "muxer-root" / "etc" / "muxer" / "config" / "customer-modules" / "legacy-cust0002",
        phase7_root / "r" / "nonnat-active-root" / "var" / "lib" / "rpdb-headend" / "customers" / "legacy-cust0002",
        phase7_root / "r" / "nonnat-standby-root" / "var" / "lib" / "rpdb-headend" / "customers" / "legacy-cust0002",
    ):
        if path.exists():
            raise SystemExit(f"Phase 7 auto-rollback left customer state behind: {path}")
    phase7_failure_result_second = _run_python_json(
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
            "RPDB_DEPLOY_DIR": str(phase7_root / "fr2"),
            "RPDB_EXECUTION_PLAN": str(_resolve_repo_path(failure_prep["artifacts"]["execution_plan"])),
            "RPDB_TARGET_SELECTION": json.dumps(failure_prep["selected_targets"]),
        },
    )
    if phase7_failure_result_second.get("status") != "rolled_back":
        raise SystemExit("Phase 7 repeated staged failure did not roll back automatically")
    for path in (
        phase7_root / "r" / "datastores" / "var" / "lib" / "rpdb-backend" / "customers" / "legacy-cust0002",
        phase7_root / "r" / "datastores" / "var" / "lib" / "rpdb-backend" / "allocations" / "legacy-cust0002",
        phase7_root / "r" / "muxer-root" / "var" / "lib" / "rpdb-muxer" / "customers" / "legacy-cust0002",
        phase7_root / "r" / "muxer-root" / "etc" / "muxer" / "config" / "customer-modules" / "legacy-cust0002",
        phase7_root / "r" / "nonnat-active-root" / "var" / "lib" / "rpdb-headend" / "customers" / "legacy-cust0002",
        phase7_root / "r" / "nonnat-standby-root" / "var" / "lib" / "rpdb-headend" / "customers" / "legacy-cust0002",
    ):
        if path.exists():
            raise SystemExit(f"Phase 7 repeated auto-rollback left customer state behind: {path}")
    record_step(
        "post_apply_auto_rollback_gate",
        {
            "environment_file": str(phase7_env_path),
            "status": phase7_failure_result["status"],
            "error": phase7_failure_result["error"],
            "rollback_plan": _resolve_repo_path(phase7_failure_result["rollback_plan"]).as_posix(),
            "apply_journal": _resolve_repo_path(phase7_failure_result["apply_journal"]).as_posix(),
            "repeat_status": phase7_failure_result_second["status"],
            "repeat_rollback_plan": _resolve_repo_path(phase7_failure_result_second["rollback_plan"]).as_posix(),
            "repeat_apply_journal": _resolve_repo_path(phase7_failure_result_second["apply_journal"]).as_posix(),
        },
    )

    crlf_matches = _generated_files_with_crlf(BUILD_ROOT, {".sh", ".nft", ".txt"})
    if crlf_matches:
        raise SystemExit("generated Linux activation artifacts contain CRLF line endings: " + ", ".join(crlf_matches[:20]))
    record_step(
        "generated_linux_artifact_line_endings",
        {
            "root": str(BUILD_ROOT),
            "checked_suffixes": [".nft", ".sh", ".txt"],
            "crlf_match_count": 0,
        },
    )

    host_path_matches = _generated_activation_files_with_windows_paths(BUILD_ROOT)
    if host_path_matches:
        raise SystemExit(
            "generated Linux activation artifacts contain host Windows paths: "
            + ", ".join(host_path_matches[:20])
        )
    record_step(
        "generated_linux_artifact_host_path_boundary",
        {
            "root": str(BUILD_ROOT),
            "checked_artifacts": [".conf", ".nft", ".sh", "*.command.txt", "*.commands.txt"],
            "windows_path_match_count": 0,
        },
    )

    local_path_matches = _tracked_files_with_forbidden_local_paths()
    if local_path_matches:
        raise SystemExit(
            "tracked repo files contain local workspace/chat path references: "
            + ", ".join(local_path_matches[:20])
        )
    record_step(
        "tracked_repo_local_path_scrub_boundary",
        {
            "checked_scope": "git ls-files",
            "forbidden_tokens": ["local workspace drive paths", "workspace-root tokens", "chat artifact names"],
            "match_count": 0,
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
