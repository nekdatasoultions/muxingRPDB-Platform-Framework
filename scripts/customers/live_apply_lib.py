"""Helpers for approved customer deploy flows."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def resolve_repo_path(path_like: str) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def run_json(command: list[str]) -> tuple[int, dict[str, Any] | None, str, str]:
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
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


def staged_target_root(target: dict[str, Any]) -> Path:
    selector = target.get("selector") or {}
    if str(selector.get("type") or "").strip() != "staged":
        raise ValueError(f"target is not staged: {target.get('name')}")
    root = str(selector.get("value") or "").strip()
    if not root:
        raise ValueError(f"staged target has no selector.value: {target.get('name')}")
    return resolve_repo_path(root)


def _copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def _record_action(
    journal: list[dict[str, Any]],
    *,
    action: str,
    target: str,
    command: list[str],
    payload: dict[str, Any] | None,
    returncode: int,
    stdout: str,
    stderr: str,
) -> None:
    journal.append(
        {
            "recorded_at": utc_now(),
            "action": action,
            "target": target,
            "command": command,
            "returncode": returncode,
            "payload": payload,
            "stdout": stdout,
            "stderr": stderr,
            "success": returncode == 0,
        }
    )


def _execute_json(
    journal: list[dict[str, Any]],
    *,
    action: str,
    target: str,
    command: list[str],
) -> dict[str, Any]:
    returncode, payload, stdout, stderr = run_json(command)
    _record_action(
        journal,
        action=action,
        target=target,
        command=command,
        payload=payload,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )
    if returncode != 0:
        raise RuntimeError(f"{action} failed for {target}: {stderr or stdout}".strip())
    return payload or {}


def _rollback_staged(
    *,
    rollback_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    rollback_errors: list[str] = []
    for step in reversed(rollback_steps):
        returncode, payload, stdout, stderr = run_json(step["command"])
        results.append(
            {
                "recorded_at": utc_now(),
                "action": step["action"],
                "target": step["target"],
                "command": step["command"],
                "returncode": returncode,
                "payload": payload,
                "stdout": stdout,
                "stderr": stderr,
                "success": returncode == 0,
            }
        )
        if returncode != 0:
            rollback_errors.append(
                f"{step['action']} failed for {step['target']}: {stderr or stdout}".strip()
            )
    return {
        "status": "rolled_back" if not rollback_errors else "rollback_failed",
        "errors": rollback_errors,
        "steps": results,
    }


def execute_staged_live_apply(
    *,
    customer_name: str,
    package_dir: Path,
    bundle_dir: Path,
    deploy_dir: Path,
    target_selection: dict[str, Any],
    environment_doc: dict[str, Any],
    execution_plan_path: Path,
) -> dict[str, Any]:
    staged_datastore_root = resolve_repo_path(
        str(((environment_doc.get("datastores") or {}).get("staged_root") or "")).strip()
    )
    staged_artifact_root = resolve_repo_path(
        str(((environment_doc.get("artifacts") or {}).get("staged_root") or "")).strip()
    )
    muxer_root = staged_target_root(target_selection.get("muxer") or {})
    headend_active_root = staged_target_root(target_selection.get("headend_active") or {})
    headend_standby_root = staged_target_root(target_selection.get("headend_standby") or {})

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_run_root = staged_artifact_root / customer_name / run_id
    artifact_package_root = artifact_run_root / "package"
    artifact_execution_plan = artifact_run_root / "execution-plan.json"
    apply_dir = deploy_dir / "approved-apply"
    apply_dir.mkdir(parents=True, exist_ok=True)

    journal: list[dict[str, Any]] = []
    rollback_steps: list[dict[str, Any]] = []

    try:
        artifact_run_root.mkdir(parents=True, exist_ok=True)
        _copy_tree(package_dir, artifact_package_root)
        shutil.copy2(execution_plan_path, artifact_execution_plan)

        backend_apply = _execute_json(
            journal,
            action="apply_backend_customer",
            target="datastores",
            command=[
                sys.executable,
                "scripts/deployment/apply_backend_customer.py",
                "--package-dir",
                str(package_dir),
                "--backend-root",
                str(staged_datastore_root),
                "--json",
            ],
        )
        rollback_steps.append(
            {
                "action": "remove_backend_customer",
                "target": "datastores",
                "command": [
                    sys.executable,
                    "scripts/deployment/remove_backend_customer.py",
                    "--customer-name",
                    customer_name,
                    "--backend-root",
                    str(staged_datastore_root),
                    "--json",
                ],
            }
        )

        backend_validation = _execute_json(
            journal,
            action="validate_backend_customer",
            target="datastores",
            command=[
                sys.executable,
                "scripts/deployment/validate_backend_customer.py",
                "--package-dir",
                str(package_dir),
                "--backend-root",
                str(staged_datastore_root),
                "--json",
            ],
        )

        muxer_apply = _execute_json(
            journal,
            action="apply_muxer_customer",
            target=str((target_selection.get("muxer") or {}).get("name") or "muxer"),
            command=[
                sys.executable,
                "scripts/deployment/apply_muxer_customer.py",
                "--bundle-dir",
                str(bundle_dir),
                "--muxer-root",
                str(muxer_root),
                "--json",
            ],
        )
        rollback_steps.append(
            {
                "action": "remove_muxer_customer",
                "target": str((target_selection.get("muxer") or {}).get("name") or "muxer"),
                "command": [
                    sys.executable,
                    "scripts/deployment/remove_muxer_customer.py",
                    "--customer-name",
                    customer_name,
                    "--muxer-root",
                    str(muxer_root),
                    "--json",
                ],
            }
        )

        muxer_validation = _execute_json(
            journal,
            action="validate_muxer_customer",
            target=str((target_selection.get("muxer") or {}).get("name") or "muxer"),
            command=[
                sys.executable,
                "scripts/deployment/validate_muxer_customer.py",
                "--bundle-dir",
                str(bundle_dir),
                "--muxer-root",
                str(muxer_root),
                "--json",
            ],
        )

        active_apply = _execute_json(
            journal,
            action="apply_headend_customer",
            target=str((target_selection.get("headend_active") or {}).get("name") or "headend-active"),
            command=[
                sys.executable,
                "scripts/deployment/apply_headend_customer.py",
                "--bundle-dir",
                str(bundle_dir),
                "--headend-root",
                str(headend_active_root),
                "--json",
            ],
        )
        rollback_steps.append(
            {
                "action": "remove_headend_customer",
                "target": str((target_selection.get("headend_active") or {}).get("name") or "headend-active"),
                "command": [
                    sys.executable,
                    "scripts/deployment/remove_headend_customer.py",
                    "--customer-name",
                    customer_name,
                    "--headend-root",
                    str(headend_active_root),
                    "--json",
                ],
            }
        )

        active_validation = _execute_json(
            journal,
            action="validate_headend_customer",
            target=str((target_selection.get("headend_active") or {}).get("name") or "headend-active"),
            command=[
                sys.executable,
                "scripts/deployment/validate_headend_customer.py",
                "--bundle-dir",
                str(bundle_dir),
                "--headend-root",
                str(headend_active_root),
                "--json",
            ],
        )

        standby_apply = _execute_json(
            journal,
            action="apply_headend_customer",
            target=str((target_selection.get("headend_standby") or {}).get("name") or "headend-standby"),
            command=[
                sys.executable,
                "scripts/deployment/apply_headend_customer.py",
                "--bundle-dir",
                str(bundle_dir),
                "--headend-root",
                str(headend_standby_root),
                "--json",
            ],
        )
        rollback_steps.append(
            {
                "action": "remove_headend_customer",
                "target": str((target_selection.get("headend_standby") or {}).get("name") or "headend-standby"),
                "command": [
                    sys.executable,
                    "scripts/deployment/remove_headend_customer.py",
                    "--customer-name",
                    customer_name,
                    "--headend-root",
                    str(headend_standby_root),
                    "--json",
                ],
            }
        )

        standby_validation = _execute_json(
            journal,
            action="validate_headend_customer",
            target=str((target_selection.get("headend_standby") or {}).get("name") or "headend-standby"),
            command=[
                sys.executable,
                "scripts/deployment/validate_headend_customer.py",
                "--bundle-dir",
                str(bundle_dir),
                "--headend-root",
                str(headend_standby_root),
                "--json",
            ],
        )

        rollback_plan = {
            "schema_version": 1,
            "customer_name": customer_name,
            "generated_at": utc_now(),
            "steps": rollback_steps,
        }
        journal_payload = {
            "schema_version": 1,
            "customer_name": customer_name,
            "generated_at": utc_now(),
            "steps": journal,
        }
        result = {
            "schema_version": 1,
            "customer_name": customer_name,
            "status": "applied",
            "generated_at": utc_now(),
            "mode": "staged_live_apply",
            "roots": {
                "artifacts": repo_relative(staged_artifact_root),
                "datastores": repo_relative(staged_datastore_root),
                "muxer": repo_relative(muxer_root),
                "headend_active": repo_relative(headend_active_root),
                "headend_standby": repo_relative(headend_standby_root),
            },
            "published_artifacts": {
                "run_root": repo_relative(artifact_run_root),
                "package_root": repo_relative(artifact_package_root),
                "execution_plan": repo_relative(artifact_execution_plan),
            },
            "validation": {
                "backend": backend_validation,
                "muxer": muxer_validation,
                "headend_active": active_validation,
                "headend_standby": standby_validation,
            },
            "applies": {
                "backend": backend_apply,
                "muxer": muxer_apply,
                "headend_active": active_apply,
                "headend_standby": standby_apply,
            },
            "rollback_plan": repo_relative(apply_dir / "rollback-plan.json"),
            "apply_journal": repo_relative(apply_dir / "apply-journal.json"),
        }
        write_json(apply_dir / "rollback-plan.json", rollback_plan)
        write_json(apply_dir / "apply-journal.json", journal_payload)
        write_json(apply_dir / "apply-result.json", result)
        return result
    except Exception as exc:
        rollback_result = _rollback_staged(rollback_steps=rollback_steps)
        journal_payload = {
            "schema_version": 1,
            "customer_name": customer_name,
            "generated_at": utc_now(),
            "steps": journal,
        }
        failure_result = {
            "schema_version": 1,
            "customer_name": customer_name,
            "status": rollback_result["status"],
            "generated_at": utc_now(),
            "mode": "staged_live_apply",
            "error": str(exc),
            "rollback": rollback_result,
            "rollback_plan": repo_relative(apply_dir / "rollback-plan.json"),
            "apply_journal": repo_relative(apply_dir / "apply-journal.json"),
        }
        write_json(
            apply_dir / "rollback-plan.json",
            {
                "schema_version": 1,
                "customer_name": customer_name,
                "generated_at": utc_now(),
                "steps": rollback_steps,
            },
        )
        write_json(apply_dir / "apply-journal.json", journal_payload)
        write_json(apply_dir / "apply-result.json", failure_result)
        return failure_result
