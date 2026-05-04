from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


def _framework_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _cgnat_root() -> Path:
    return _framework_dir().parent


def _repo_root() -> Path:
    return _cgnat_root().parent


def _src_root() -> Path:
    return _framework_dir() / "src"


if str(_src_root()) not in sys.path:
    sys.path.insert(0, str(_src_root()))

from cgnat.bundle import dump_json, dump_text, ensure_path_within_cgnat  # noqa: E402
from cgnat.customer_provisioning import (  # noqa: E402
    build_backend_surface_review,
    build_cgnat_combined_review,
    build_cgnat_headend_surface_review,
    build_cgnat_live_execution_plan,
    build_cgnat_live_test_bed_plan,
    build_cgnat_pki_surface_review,
    build_cgnat_rollback_plan,
    build_muxer_surface_review,
    render_cgnat_live_execution_checklist,
    render_cgnat_combined_readme,
    validate_cgnat_request,
)


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _customer_name_from_request(path: Path) -> str:
    doc = _load_yaml(path)
    customer_name = str((doc.get("customer") or {}).get("name") or "").strip()
    if not customer_name:
        raise ValueError(f"customer.name missing in {path}")
    return customer_name


def _run_json(command: list[str]) -> tuple[int, dict[str, Any] | None, str, str]:
    completed = subprocess.run(
        command,
        cwd=str(_repo_root()),
        text=True,
        capture_output=True,
        check=False,
    )
    payload = None
    if completed.stdout.strip():
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            payload = None
    return completed.returncode, payload, completed.stdout, completed.stderr


def _write_surface(output_dir: Path, relative_path: str, payload: dict[str, Any]) -> None:
    dump_json(output_dir / relative_path, payload)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a combined repo-only CGNAT customer review package by "
            "reusing the shared deploy dry-run path and adding CGNAT-specific "
            "surface reviews."
        )
    )
    parser.add_argument("request", help="CGNAT customer request YAML")
    parser.add_argument(
        "--environment",
        default="rpdb-empty-live",
        help="Deployment environment name or file passed to deploy_customer.py",
    )
    parser.add_argument(
        "--out-dir",
        help="Output directory inside CGNAT/. Defaults to CGNAT/build/customer-provisioning/<customer-name>.",
    )
    parser.add_argument(
        "--test-bed-customer",
        help="Optional note for the preferred first live CGNAT test bed customer.",
    )
    parser.add_argument("--json", action="store_true", help="Print the combined review summary as JSON")
    args = parser.parse_args()

    request_path = Path(args.request).resolve()
    request_doc = _load_yaml(request_path)
    validate_cgnat_request(request_doc, request_path=str(request_path))

    customer_name = _customer_name_from_request(request_path)
    output_dir = (
        ensure_path_within_cgnat(Path(args.out_dir).resolve())
        if args.out_dir
        else ensure_path_within_cgnat(_cgnat_root() / "build" / "customer-provisioning" / customer_name)
    )
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    shared_deploy_dir = output_dir / "shared-dry-run"
    command = [
        sys.executable,
        str(_repo_root() / "scripts" / "customers" / "deploy_customer.py"),
        "--customer-file",
        str(request_path),
        "--environment",
        str(args.environment),
        "--out-dir",
        str(shared_deploy_dir),
        "--dry-run",
        "--json",
    ]

    returncode, execution_plan, stdout, stderr = _run_json(command)
    if returncode != 0 or not isinstance(execution_plan, dict):
        failure = {
            "schema_version": 1,
            "integration_type": "cgnat_customer_repo_only_review",
            "status": "blocked",
            "ready_for_review": False,
            "customer_name": customer_name,
            "request": str(request_path),
            "environment": args.environment,
            "delegated_command": command,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
        dump_json(output_dir / "combined-review-summary.json", failure)
        if args.json:
            print(json.dumps(failure, indent=2, sort_keys=True))
        else:
            print(f"CGNAT customer review blocked: {customer_name}")
            print(f"- review summary: {output_dir / 'combined-review-summary.json'}")
        return 1

    readiness_path = shared_deploy_dir / "package" / "pilot-readiness.json"
    readiness = _load_json(readiness_path)

    backend_review = build_backend_surface_review(
        request_doc=request_doc,
        readiness=readiness,
        execution_plan=execution_plan,
        shared_deploy_dir=shared_deploy_dir,
    )
    muxer_review = build_muxer_surface_review(
        request_doc=request_doc,
        readiness=readiness,
        execution_plan=execution_plan,
    )
    cgnat_headend_review = build_cgnat_headend_surface_review(
        request_doc=request_doc,
        execution_plan=execution_plan,
    )
    pki_review = build_cgnat_pki_surface_review(
        request_doc=request_doc,
        output_dir=output_dir / "pki",
    )
    rollback_plan = build_cgnat_rollback_plan(
        execution_plan=execution_plan,
        test_bed_customer=args.test_bed_customer,
    )
    live_test_bed_plan = build_cgnat_live_test_bed_plan(
        request_doc=request_doc,
        execution_plan=execution_plan,
        rollback_plan=rollback_plan,
        test_bed_customer=args.test_bed_customer,
    )
    live_execution_plan = build_cgnat_live_execution_plan(
        request_doc=request_doc,
        execution_plan=execution_plan,
        pki_review=pki_review,
        rollback_plan=rollback_plan,
        live_test_bed_plan=live_test_bed_plan,
    )
    combined_review = build_cgnat_combined_review(
        request_doc=request_doc,
        readiness=readiness,
        execution_plan=execution_plan,
        backend_review=backend_review,
        muxer_review=muxer_review,
        cgnat_headend_review=cgnat_headend_review,
        pki_review=pki_review,
        rollback_plan=rollback_plan,
        live_test_bed_plan=live_test_bed_plan,
        live_execution_plan=live_execution_plan,
        shared_deploy_dir=shared_deploy_dir,
    )

    _write_surface(output_dir, "backend/backend-review.json", backend_review)
    _write_surface(output_dir, "muxer/muxer-review.json", muxer_review)
    _write_surface(output_dir, "cgnat/cgnat-headend-review.json", cgnat_headend_review)
    _write_surface(output_dir, "pki/pki-review.json", pki_review)
    _write_surface(output_dir, "rollback-plan.json", rollback_plan)
    _write_surface(output_dir, "live-test-bed-plan.json", live_test_bed_plan)
    _write_surface(output_dir, "live-execution-plan.json", live_execution_plan)
    _write_surface(output_dir, "combined-review-summary.json", combined_review)
    dump_text(
        output_dir / "LIVE_EXECUTION_CHECKLIST.md",
        render_cgnat_live_execution_checklist(
            live_execution_plan=live_execution_plan,
        ),
    )
    dump_text(
        output_dir / "README.md",
        render_cgnat_combined_readme(
            combined_review=combined_review,
            backend_review=backend_review,
            muxer_review=muxer_review,
            cgnat_headend_review=cgnat_headend_review,
            pki_review=pki_review,
        ),
    )

    if args.json:
        print(json.dumps(combined_review, indent=2, sort_keys=True))
    else:
        print(f"CGNAT customer review ready: {combined_review['status']}")
        print(f"- customer: {customer_name}")
        print(f"- review root: {output_dir}")
        print(f"- summary: {output_dir / 'combined-review-summary.json'}")

    return 0 if combined_review.get("ready_for_review") else 1


if __name__ == "__main__":
    raise SystemExit(main())
