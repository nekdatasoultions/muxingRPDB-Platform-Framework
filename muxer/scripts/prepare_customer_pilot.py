#!/usr/bin/env python
"""Prepare one complete repo-only RPDB customer pilot review package."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


REQUIRED_PACKAGE_PATHS = [
    "customer-source.yaml",
    "customer-module.json",
    "customer-ddb-item.json",
    "allocation-summary.json",
    "allocation-ddb-items.json",
    "rendered",
    "handoff",
    "bound",
    "bundle",
    "bundle-validation.json",
    "double-verification.json",
    "pilot-readiness.json",
    "README.md",
]


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload if payload.endswith("\n") else payload + "\n")


def _copy_file(source: str | Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(source), destination)


def _customer_name_from_request(path: Path) -> str:
    doc = _load_yaml(path)
    customer_name = str((doc.get("customer") or {}).get("name") or "").strip()
    if not customer_name:
        raise ValueError(f"customer.name missing in {path}")
    return customer_name


def _repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _ensure_repo_local_output(path: Path, repo_root: Path) -> None:
    resolved = path.resolve()
    repo = repo_root.resolve()
    try:
        relative = resolved.relative_to(repo)
    except ValueError as exc:
        raise ValueError(f"pilot output directory must be inside the RPDB repo: {resolved}") from exc
    if not relative.parts:
        raise ValueError("pilot output directory cannot be the repo root")
    if relative.parts[0] in {".git", "muxer", "scripts", "docs"}:
        raise ValueError(f"pilot output directory must be a generated repo-local path, not {relative.parts[0]}/")


def _staged_headend_root(repo_root: Path, package_dir: Path) -> Path:
    digest = hashlib.sha1(str(package_dir.resolve()).encode("utf-8")).hexdigest()[:12]
    return repo_root / "build" / "pilot-he" / digest


def _run_step(
    name: str,
    command: list[str],
    *,
    cwd: Path,
    steps: list[dict[str, Any]],
    expect_json: bool = False,
) -> dict[str, Any] | None:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    step: dict[str, Any] = {
        "name": name,
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    if expect_json and completed.stdout.strip():
        try:
            step["json"] = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            step["json_error"] = str(exc)
    steps.append(step)
    if completed.returncode != 0:
        raise RuntimeError(f"pilot preparation step failed: {name}")
    return step.get("json") if expect_json else None


def _run_double_verification(
    *,
    repo_root: Path,
    source_path: Path,
    render_dir: Path,
    handoff_dir: Path,
    bound_dir: Path,
    bundle_dir: Path,
    environment_file: Path,
    customer_name: str,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    python = sys.executable
    headend_root = _staged_headend_root(repo_root, bundle_dir.parent)
    if headend_root.exists():
        shutil.rmtree(headend_root)

    _run_step(
        "validate_customer_source",
        [python, "muxer/scripts/validate_customer_source.py", str(source_path)],
        cwd=repo_root,
        steps=steps,
    )
    _run_step(
        "render_customer_artifacts",
        [
            python,
            "muxer/scripts/render_customer_artifacts.py",
            str(source_path),
            "--out-dir",
            str(render_dir),
            "--source-ref",
            str(source_path),
        ],
        cwd=repo_root,
        steps=steps,
    )
    render_validation = _run_step(
        "validate_rendered_artifacts",
        [python, "muxer/scripts/validate_rendered_artifacts.py", str(render_dir), "--json"],
        cwd=repo_root,
        steps=steps,
        expect_json=True,
    )
    _run_step(
        "validate_environment_bindings",
        [python, "muxer/scripts/validate_environment_bindings.py", str(environment_file)],
        cwd=repo_root,
        steps=steps,
    )
    _run_step(
        "export_customer_handoff",
        [
            python,
            "muxer/scripts/export_customer_handoff.py",
            str(source_path),
            "--export-dir",
            str(handoff_dir),
            "--muxer-dir",
            str(render_dir / "muxer"),
            "--headend-dir",
            str(render_dir / "headend"),
            "--source-ref",
            str(source_path),
        ],
        cwd=repo_root,
        steps=steps,
    )
    _run_step(
        "bind_rendered_artifacts",
        [
            python,
            "muxer/scripts/bind_rendered_artifacts.py",
            str(handoff_dir),
            "--environment-file",
            str(environment_file),
            "--out-dir",
            str(bound_dir),
        ],
        cwd=repo_root,
        steps=steps,
    )
    bound_validation = _run_step(
        "validate_bound_artifacts",
        [python, "muxer/scripts/validate_bound_artifacts.py", str(bound_dir), "--json"],
        cwd=repo_root,
        steps=steps,
        expect_json=True,
    )
    _run_step(
        "assemble_customer_bundle",
        [
            python,
            "scripts/packaging/assemble_customer_bundle.py",
            "--customer-name",
            customer_name,
            "--export-dir",
            str(bound_dir),
            "--bundle-dir",
            str(bundle_dir),
        ],
        cwd=repo_root,
        steps=steps,
    )
    bundle_validation = _run_step(
        "validate_customer_bundle",
        [python, "scripts/packaging/validate_customer_bundle.py", str(bundle_dir), "--json"],
        cwd=repo_root,
        steps=steps,
        expect_json=True,
    )
    headend_bundle_validation = _run_step(
        "validate_headend_bundle",
        [python, "scripts/deployment/validate_headend_customer.py", "--bundle-dir", str(bundle_dir), "--json"],
        cwd=repo_root,
        steps=steps,
        expect_json=True,
    )
    _run_step(
        "apply_headend_customer_staged",
        [
            python,
            "scripts/deployment/apply_headend_customer.py",
            "--bundle-dir",
            str(bundle_dir),
            "--headend-root",
            str(headend_root),
        ],
        cwd=repo_root,
        steps=steps,
    )
    installed_headend_validation = _run_step(
        "validate_installed_headend_staged",
        [
            python,
            "scripts/deployment/validate_headend_customer.py",
            "--bundle-dir",
            str(bundle_dir),
            "--headend-root",
            str(headend_root),
            "--json",
        ],
        cwd=repo_root,
        steps=steps,
        expect_json=True,
    )
    removal_report = _run_step(
        "remove_headend_customer_staged",
        [
            python,
            "scripts/deployment/remove_headend_customer.py",
            "--bundle-dir",
            str(bundle_dir),
            "--headend-root",
            str(headend_root),
            "--json",
        ],
        cwd=repo_root,
        steps=steps,
        expect_json=True,
    )

    return {
        "schema_version": 1,
        "customer_name": customer_name,
        "ready": True,
        "live_apply": False,
        "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "paths": {
            "source": str(source_path),
            "rendered": str(render_dir),
            "handoff": str(handoff_dir),
            "bound": str(bound_dir),
            "bundle": str(bundle_dir),
            "staged_headend_root": str(headend_root),
        },
        "reports": {
            "render_validation": render_validation,
            "bound_validation": bound_validation,
            "bundle_validation": bundle_validation,
            "headend_bundle_validation": headend_bundle_validation,
            "installed_headend_validation": installed_headend_validation,
            "headend_removal": removal_report,
        },
        "steps": steps,
    }


def _build_readiness_report(
    *,
    customer_name: str,
    package_dir: Path,
    repo_root: Path,
    request_path: Path,
    environment_file: Path,
    source_doc: dict[str, Any],
    module: dict[str, Any],
    allocation_summary: dict[str, Any],
    allocation_ddb_items: list[dict[str, Any]],
    bundle_validation: dict[str, Any],
    double_verification: dict[str, Any],
    dynamic_result: dict[str, Any] | None,
) -> dict[str, Any]:
    customer_doc = source_doc.get("customer") or {}
    peer_doc = customer_doc.get("peer") or {}
    selectors_doc = customer_doc.get("selectors") or {}
    backend_doc = customer_doc.get("backend") or {}
    ipsec_doc = module.get("ipsec") or {}
    allocation_plan = allocation_summary.get("allocation_plan") or {}
    transport_doc = customer_doc.get("transport") or {}
    exclusive_resources = allocation_summary.get("exclusive_resources") or []

    def resource_value(resource_type: str) -> Any:
        for resource in exclusive_resources:
            if resource.get("resource_type") == resource_type:
                return resource.get("resource_value")
        return None

    id_doc = customer_doc.get("id")
    if isinstance(id_doc, dict):
        customer_id = id_doc.get("customer_id") or allocation_plan.get("customer_id")
    else:
        customer_id = id_doc or allocation_plan.get("customer_id") or resource_value("customer_id")

    errors = []
    if not bundle_validation.get("valid"):
        errors.append("bundle validation did not pass")
    if not double_verification.get("ready"):
        errors.append("double verification did not pass")
    for relative_path in REQUIRED_PACKAGE_PATHS:
        if not (package_dir / relative_path).exists():
            errors.append(f"missing package artifact: {relative_path}")

    return {
        "schema_version": 1,
        "status": "blocked" if errors else "ready_for_review",
        "ready_for_review": not errors,
        "live_apply": False,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "customer": {
            "name": customer_name,
            "customer_class": customer_doc.get("customer_class"),
            "backend_cluster": backend_doc.get("cluster"),
            "backend_assignment": backend_doc.get("assignment"),
            "backend_role": backend_doc.get("role") or module.get("backend_role"),
            "peer_ip": peer_doc.get("public_ip"),
            "local_subnets": selectors_doc.get("local_subnets") or [],
            "remote_subnets": selectors_doc.get("remote_subnets") or [],
            "remote_host_cidrs": selectors_doc.get("remote_host_cidrs") or [],
            "outside_nat_enabled": bool((customer_doc.get("outside_nat") or {}).get("enabled")),
            "ipsec_initiation": ipsec_doc.get("initiation") or {},
        },
        "allocated_resources": {
            "customer_id": customer_id,
            "fwmark": transport_doc.get("mark") or allocation_plan.get("fwmark") or resource_value("fwmark"),
            "route_table": transport_doc.get("table") or allocation_plan.get("route_table") or resource_value("route_table"),
            "rpdb_priority": (
                transport_doc.get("rpdb_priority")
                or allocation_plan.get("rpdb_priority")
                or resource_value("rpdb_priority")
            ),
            "tunnel_key": transport_doc.get("tunnel_key") or allocation_plan.get("tunnel_key") or resource_value("tunnel_key"),
            "interface": (
                transport_doc.get("interface")
                or allocation_plan.get("transport_interface")
                or resource_value("transport_interface")
            ),
            "overlay_block": transport_doc.get("overlay_block") or allocation_plan.get("overlay_block") or resource_value("overlay_block"),
        },
        "inputs": {
            "request": str(request_path),
            "environment_file": str(environment_file),
        },
        "package_paths": {
            name: _repo_relative(package_dir / name, repo_root)
            for name in REQUIRED_PACKAGE_PATHS
        },
        "dynamic_nat_t": {
            "used": dynamic_result is not None,
            "status": dynamic_result.get("status") if dynamic_result else "not_used",
            "idempotency_key": dynamic_result.get("idempotency_key") if dynamic_result else None,
            "audit": dynamic_result.get("artifacts", {}).get("audit") if dynamic_result else None,
        },
        "validation": {
            "bundle_valid": bool(bundle_validation.get("valid")),
            "double_verification_ready": bool(double_verification.get("ready")),
            "allocation_ddb_item_count": len(allocation_ddb_items),
            "errors": errors,
        },
        "live_gate": {
            "status": "stopped_before_live",
            "requires_separate_approval": True,
            "no_live_nodes_touched": True,
            "no_production_dynamodb_writes": True,
        },
        "rollback_review": {
            "required_before_live": True,
            "backup_owner_required": True,
            "rollback_owner_required": True,
            "validation_owner_required": True,
            "notes": [
                "Review old and new allocations before live work.",
                "Keep prior allocations reserved until live cutover succeeds or rollback owner releases them.",
                "Do not apply this package live without a separately approved deployment plan.",
            ],
        },
    }


def _build_readme(
    *,
    customer_name: str,
    readiness: dict[str, Any],
    dynamic_result: dict[str, Any] | None,
) -> str:
    customer = readiness["customer"]
    dynamic_text = (
        f"Dynamic NAT-T promotion was used. Audit: {readiness['dynamic_nat_t']['audit']}"
        if dynamic_result
        else "Dynamic NAT-T promotion was not used for this package."
    )
    return f"""# RPDB Pilot Package: {customer_name}

## Purpose

This is a repo-only RPDB pilot review package. It was generated for human
review before any live muxer, VPN head-end, or production DynamoDB work.

## Customer

- Name: {customer_name}
- Class: {customer.get("customer_class")}
- Backend cluster: {customer.get("backend_cluster")}
- Peer IP: {customer.get("peer_ip")}
- Status: {readiness.get("status")}

## Dynamic NAT-T

{dynamic_text}

## Review Artifacts

- `customer-source.yaml`
- `customer-module.json`
- `customer-ddb-item.json`
- `allocation-summary.json`
- `allocation-ddb-items.json`
- `rendered/`
- `handoff/`
- `bound/`
- `bundle/`
- `bundle-validation.json`
- `double-verification.json`
- `pilot-readiness.json`

## Stop Gate

Do not apply this package live without a separately approved deployment plan,
current backups, rollback owner, validation owner, and exact live commands.

This package has `live_apply: false`.
"""


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    muxer_dir = repo_root / "muxer"

    parser = argparse.ArgumentParser(description="Prepare one repo-only RPDB customer pilot package.")
    parser.add_argument("request", help="Customer request YAML")
    parser.add_argument(
        "--out-dir",
        help="Repo-local output directory. Defaults to build/customer-pilots/<customer-name>.",
    )
    parser.add_argument(
        "--environment-file",
        default=str(muxer_dir / "config" / "environment-defaults" / "example-environment.yaml"),
        help="Environment binding YAML used for repo-only package binding.",
    )
    parser.add_argument(
        "--existing-source-root",
        action="append",
        default=[],
        help="Existing customer source roots used for collision checks. Can be specified multiple times.",
    )
    parser.add_argument(
        "--replace-customer",
        action="append",
        default=[],
        help="Ignore an existing same-name customer during repo-only planning.",
    )
    parser.add_argument(
        "--observation",
        help="Optional dynamic NAT-T UDP/4500 observation event JSON/YAML.",
    )
    parser.add_argument("--json", action="store_true", help="Print pilot readiness as JSON")
    args = parser.parse_args()

    request_path = Path(args.request).resolve()
    environment_file = Path(args.environment_file).resolve()
    customer_name = _customer_name_from_request(request_path)
    package_dir = (
        Path(args.out_dir).resolve()
        if args.out_dir
        else (repo_root / "build" / "customer-pilots" / customer_name).resolve()
    )
    _ensure_repo_local_output(package_dir, repo_root)

    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)

    source_path = package_dir / "customer-source.yaml"
    module_path = package_dir / "customer-module.json"
    item_path = package_dir / "customer-ddb-item.json"
    allocation_summary_path = package_dir / "allocation-summary.json"
    allocation_ddb_items_path = package_dir / "allocation-ddb-items.json"
    render_dir = package_dir / "rendered"
    handoff_dir = package_dir / "handoff"
    bound_dir = package_dir / "bound"
    bundle_dir = package_dir / "bundle"
    bundle_validation_path = package_dir / "bundle-validation.json"
    double_verification_path = package_dir / "double-verification.json"
    readiness_path = package_dir / "pilot-readiness.json"
    readme_path = package_dir / "README.md"

    existing_roots = args.existing_source_root or [str(muxer_dir / "config" / "customer-sources")]
    steps: list[dict[str, Any]] = []
    python = sys.executable
    dynamic_result: dict[str, Any] | None = None

    try:
        _run_step(
            "validate_customer_request",
            [python, "muxer/scripts/validate_customer_request.py", str(request_path)],
            cwd=repo_root,
            steps=steps,
        )

        if args.observation:
            dynamic_out_dir = package_dir / "dynamic-nat-t"
            command = [
                python,
                "muxer/scripts/process_nat_t_observation.py",
                str(request_path),
                "--observation",
                str(Path(args.observation).resolve()),
                "--out-dir",
                str(dynamic_out_dir),
                "--json",
            ]
            for root in existing_roots:
                command.extend(["--existing-source-root", root])
            dynamic_result = _run_step(
                "process_nat_t_observation",
                command,
                cwd=repo_root,
                steps=steps,
                expect_json=True,
            )
            assert dynamic_result is not None
            artifacts = dynamic_result["artifacts"]
            _copy_file(artifacts["promoted_source"], source_path)
            _copy_file(artifacts["promoted_module"], module_path)
            _copy_file(artifacts["promoted_item"], item_path)
            _copy_file(artifacts["promoted_allocation_summary"], allocation_summary_path)
            _copy_file(artifacts["promoted_allocation_ddb_items"], allocation_ddb_items_path)
        else:
            command = [
                python,
                "muxer/scripts/provision_customer_request.py",
                str(request_path),
                "--source-out",
                str(source_path),
                "--module-out",
                str(module_path),
                "--item-out",
                str(item_path),
                "--allocation-out",
                str(allocation_summary_path),
                "--json",
            ]
            for root in existing_roots:
                command.extend(["--existing-source-root", root])
            for customer in args.replace_customer:
                command.extend(["--replace-customer", customer])
            provisioning_result = _run_step(
                "provision_customer_request",
                command,
                cwd=repo_root,
                steps=steps,
                expect_json=True,
            )
            assert provisioning_result is not None
            _write_json(allocation_ddb_items_path, provisioning_result["allocation_ddb_items"])

        double_verification = _run_double_verification(
            repo_root=repo_root,
            source_path=source_path,
            render_dir=render_dir,
            handoff_dir=handoff_dir,
            bound_dir=bound_dir,
            bundle_dir=bundle_dir,
            environment_file=environment_file,
            customer_name=customer_name,
        )
        _write_json(double_verification_path, double_verification)

        bundle_validation = double_verification["reports"]["bundle_validation"]
        _write_json(bundle_validation_path, bundle_validation)
        _write_json(
            readiness_path,
            {
                "schema_version": 1,
                "status": "building",
                "ready_for_review": False,
                "live_apply": False,
                "customer": {"name": customer_name},
            },
        )
        _write_text(
            readme_path,
            f"# RPDB Pilot Package: {customer_name}\n\nReadiness report is being generated.\n",
        )

        source_doc = _load_yaml(source_path)
        module = _load_json(module_path)
        allocation_summary = _load_json(allocation_summary_path)
        allocation_ddb_items = json.loads(allocation_ddb_items_path.read_text(encoding="utf-8"))
        readiness = _build_readiness_report(
            customer_name=customer_name,
            package_dir=package_dir,
            repo_root=repo_root,
            request_path=request_path,
            environment_file=environment_file,
            source_doc=source_doc,
            module=module,
            allocation_summary=allocation_summary,
            allocation_ddb_items=allocation_ddb_items,
            bundle_validation=bundle_validation,
            double_verification=double_verification,
            dynamic_result=dynamic_result,
        )
        _write_json(readiness_path, readiness)
        _write_text(readme_path, _build_readme(customer_name=customer_name, readiness=readiness, dynamic_result=dynamic_result))

        if readiness["status"] == "blocked":
            raise RuntimeError("pilot package readiness is blocked")
    except Exception as exc:
        failure_report = {
            "schema_version": 1,
            "status": "blocked",
            "ready_for_review": False,
            "live_apply": False,
            "customer": {"name": customer_name},
            "error": str(exc),
            "steps": steps,
            "package_dir": str(package_dir),
        }
        _write_json(readiness_path, failure_report)
        if args.json:
            print(json.dumps(failure_report, indent=2, sort_keys=True))
        else:
            print(f"Pilot package preparation failed: {customer_name}")
            print(f"- readiness: {readiness_path}")
            print(f"- error: {exc}")
        return 1

    if args.json:
        print(json.dumps(readiness, indent=2, sort_keys=True))
    else:
        print(f"Pilot package ready for review: {customer_name}")
        print(f"- package: {package_dir}")
        print(f"- readiness: {readiness_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
