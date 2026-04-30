from __future__ import annotations

import argparse
import json
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


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _render_readme(summary: dict[str, Any]) -> str:
    lines = [
        "# Scenario 1 Backend Integration",
        "",
        f"- Service ID: `{summary['service_id']}`",
        f"- Customer ID: `{summary['customer_id']}`",
        f"- Environment: `{summary['environment']}`",
        f"- Backend dry-run OK: `{summary['deploy_dry_run_ok']}`",
        "",
        "## Generated Requests",
        "",
    ]
    for record in summary["device_summaries"]:
        lines.append(f"- `{record['router_role']}` -> `{record['request_path']}`")
    lines.extend(["", "## Notes", ""])
    lines.extend(f"- {note}" for note in summary["notes"])
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    current_dir = Path(__file__).resolve().parent
    src_root = current_dir.parent / "src"
    sys.path.insert(0, str(src_root))

    from cgnat.backend_integration import build_backend_customer_requests, build_backend_integration_summary
    from cgnat.bundle import dump_json, dump_text, ensure_path_within_cgnat, load_bundle

    parser = argparse.ArgumentParser(
        description="Prepare the Scenario 1 backend reuse integration by generating backend-native requests and running the existing deploy_customer dry-run."
    )
    parser.add_argument("bundle_json", help="Path to the CGNAT deployment bundle JSON.")
    parser.add_argument("integration_json", help="Path to the backend integration config JSON.")
    parser.add_argument("output_dir", help="Directory to write the backend integration artifacts.")
    args = parser.parse_args()

    bundle = load_bundle(args.bundle_json)
    integration = _load_json(Path(args.integration_json).resolve())
    output_dir = ensure_path_within_cgnat(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    request_records: list[dict[str, Any]] = []
    for request_record in build_backend_customer_requests(bundle, integration):
        router_role = request_record["router_role"]
        request = request_record["request"]
        request_path = output_dir / "backend-requests" / router_role / "customer-request.yaml"
        _write_yaml(request_path, request)

        validate_command = [
            sys.executable,
            str(_repo_root() / "muxer" / "scripts" / "validate_customer_request.py"),
            str(request_path),
        ]
        validate_result = subprocess.run(
            validate_command,
            cwd=str(_repo_root()),
            text=True,
            capture_output=True,
            check=False,
        )
        validation_ok = validate_result.returncode == 0

        deploy_dir = output_dir / "backend-deploy" / router_role
        deploy_plan = None
        deploy_stdout = ""
        deploy_stderr = ""
        deploy_returncode = validate_result.returncode
        if validation_ok:
            deploy_command = [
                sys.executable,
                str(_repo_root() / "scripts" / "customers" / "deploy_customer.py"),
                "--customer-file",
                str(request_path),
                "--environment",
                str(integration["environment"]),
                "--out-dir",
                str(deploy_dir),
                "--dry-run",
                "--json",
            ]
            deploy_returncode, deploy_plan, deploy_stdout, deploy_stderr = _run_json(deploy_command)
            if deploy_plan is not None:
                dump_json(output_dir / "backend-deploy-plans" / f"{router_role}.json", deploy_plan)

        request_records.append(
            {
                "device_name": request_record["device_name"],
                "router_role": router_role,
                "customer_name": request_record["customer_name"],
                "customer_loopback_ip": request["customer"]["peer"]["remote_id"],
                "customer_peer_public_ip": request["customer"]["peer"]["public_ip"],
                "request_path": str(request_path),
                "validation_ok": validation_ok,
                "deploy_dry_run_ok": bool(deploy_returncode == 0 and isinstance(deploy_plan, dict) and not deploy_plan.get("errors")),
                "deploy_plan": deploy_plan,
                "request_validation": {
                    "returncode": validate_result.returncode,
                    "stdout": validate_result.stdout,
                    "stderr": validate_result.stderr,
                },
                "deploy_customer": {
                    "returncode": deploy_returncode,
                    "stdout": deploy_stdout,
                    "stderr": deploy_stderr,
                    "status": "dry_run_executed" if validation_ok else "skipped_validation_failed",
                    "backend_deploy_dir": str(deploy_dir),
                },
            }
        )

    summary = build_backend_integration_summary(bundle=bundle, integration=integration, request_records=request_records)
    summary["request_records"] = request_records

    dump_json(output_dir / "backend-integration-summary.json", summary)
    dump_text(output_dir / "README.md", _render_readme(summary))

    if not summary["validation_ok"]:
        return 1
    return 0 if summary["deploy_dry_run_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
