"""Helpers for approved customer deploy flows."""

from __future__ import annotations

import json
import hashlib
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from live_access_lib import (
    build_ssh_access_context,
    cleanup_ssh_access_context,
    copy_paths_to_remote_root,
    run_local,
    run_remote_command,
)
from live_backend_lib import (
    apply_backend_payloads,
    load_customer_backend_payloads,
    rollback_backend_payloads,
    validate_backend_payloads,
)


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


def _execute_local(
    journal: list[dict[str, Any]],
    *,
    action: str,
    target: str,
    command: list[str],
) -> subprocess.CompletedProcess[str]:
    completed = run_local(command, cwd=REPO_ROOT)
    _record_action(
        journal,
        action=action,
        target=target,
        command=command,
        payload=None,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{action} failed for {target}: {completed.stderr or completed.stdout}".strip())
    return completed


def _record_structured(
    journal: list[dict[str, Any]],
    *,
    action: str,
    target: str,
    payload: dict[str, Any],
) -> None:
    _record_action(
        journal,
        action=action,
        target=target,
        command=[],
        payload=payload,
        returncode=0,
        stdout="",
        stderr="",
    )


def _backend_apply_created_records(payload: dict[str, Any]) -> bool:
    if payload.get("customer_action") == "created":
        return True
    return any(
        result.get("action") == "created"
        for result in (payload.get("allocation_results") or [])
        if isinstance(result, dict)
    )


def _aws_secret_string(region: str, secret_id: str) -> str:
    completed = run_local(
        [
            "aws",
            "secretsmanager",
            "get-secret-value",
            "--region",
            region,
            "--secret-id",
            secret_id,
            "--query",
            "SecretString",
            "--output",
            "text",
        ]
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"unable to resolve customer PSK secret {secret_id}: "
            f"{(completed.stderr or completed.stdout).strip()}"
        )
    secret = completed.stdout.rstrip("\r\n")
    if not secret or secret == "None":
        raise RuntimeError(f"customer PSK secret {secret_id} did not contain SecretString")
    return secret


def _swanctl_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _inject_live_headend_secret(
    journal: list[dict[str, Any]],
    *,
    package_dir: Path,
    headend_prepared: dict[str, Any],
    region: str,
) -> dict[str, Any]:
    module_path = package_dir / "customer-module.json"
    module = json.loads(module_path.read_text(encoding="utf-8"))
    peer = module.get("peer") or {}
    secret_ref = str(peer.get("psk_secret_ref") or "").strip()
    if not secret_ref:
        raise RuntimeError("customer module is missing peer.psk_secret_ref for live head-end apply")

    secret = _aws_secret_string(region, secret_ref)
    swanctl_conf = Path(str((headend_prepared.get("apply") or {}).get("swanctl_conf") or "")).resolve()
    if not swanctl_conf.exists():
        raise RuntimeError(f"prepared head-end swanctl config not found: {swanctl_conf}")
    original = swanctl_conf.read_text(encoding="utf-8")
    replaced = re.sub(
        r"(?m)^(\s*secret\s*=\s*).*$",
        lambda match: match.group(1) + _swanctl_quote(secret),
        original,
        count=1,
    )
    if replaced == original:
        raise RuntimeError(f"prepared head-end swanctl config did not contain a PSK secret line: {swanctl_conf}")
    swanctl_conf.write_text(replaced, encoding="utf-8", newline="\n")

    report = {
        "secret_ref": secret_ref,
        "secret_sha256": hashlib.sha256(secret.encode("utf-8")).hexdigest(),
        "secret_length": len(secret),
        "swanctl_conf": repo_relative(swanctl_conf),
        "injected": True,
    }
    _record_structured(
        journal,
        action="resolve_headend_psk_secret",
        target="aws-secretsmanager",
        payload=report,
    )
    return report


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


def _s3_uri(bucket: str, *parts: str) -> str:
    cleaned = [part.strip("/").replace("\\", "/") for part in parts if str(part).strip("/")]
    return "s3://" + "/".join([bucket, *cleaned])


def _remote_path(prepared_root: Path, local_path: str | Path) -> str:
    resolved_root = prepared_root.resolve()
    resolved_path = Path(local_path).resolve()
    relative_path = resolved_path.relative_to(resolved_root)
    return "/" + relative_path.as_posix()


def _sudo_shell(command_text: str, *, strict: bool = True) -> str:
    prefix = "set -eu; " if strict else "set +e; "
    return "sudo bash -lc " + shlex.quote(prefix + command_text)


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
    apply_dir = deploy_dir / "a"
    apply_dir.mkdir(parents=True, exist_ok=True)

    journal: list[dict[str, Any]] = []
    rollback_steps: list[dict[str, Any]] = []

    try:
        artifact_run_root.mkdir(parents=True, exist_ok=True)
        _copy_tree(package_dir, artifact_package_root)
        shutil.copy2(execution_plan_path, artifact_execution_plan)

        muxer_prepared = _prepare_muxer_root(
            journal,
            customer_name=customer_name,
            bundle_dir=bundle_dir,
            apply_dir=apply_dir,
        )
        headend_prepared = _prepare_headend_root(
            journal,
            customer_name=customer_name,
            bundle_dir=bundle_dir,
            apply_dir=apply_dir,
        )

        muxer_prepared_root = Path(muxer_prepared["root"]).resolve()
        muxer_customer_root = Path(muxer_prepared["apply"]["state_json"]).resolve().parent
        muxer_module_root = Path(muxer_prepared["apply"]["customer_module"]).resolve().parent
        muxer_activation = _build_activation_bundle(
            journal,
            customer_name=customer_name,
            component_name="muxer",
            target_name=str((target_selection.get("muxer") or {}).get("name") or "muxer"),
            apply_dir=apply_dir,
            prepared_root=muxer_prepared_root,
            target_root=muxer_root,
            relative_paths=[
                muxer_customer_root.relative_to(muxer_prepared_root),
                muxer_module_root.relative_to(muxer_prepared_root),
            ],
            validate_paths=[
                Path(muxer_prepared["apply"]["state_json"]).resolve().relative_to(muxer_prepared_root),
                Path(muxer_prepared["apply"]["customer_module"]).resolve().relative_to(muxer_prepared_root),
                Path(muxer_prepared["apply"]["master_apply_script"]).resolve().relative_to(muxer_prepared_root),
            ],
            cleanup_paths=[
                muxer_customer_root.relative_to(muxer_prepared_root),
                muxer_module_root.relative_to(muxer_prepared_root),
            ],
            cleanup_files=[],
            apply_script=Path(muxer_prepared["apply"]["master_apply_script"]).resolve(),
            remove_script=Path(muxer_prepared["apply"]["master_remove_script"]).resolve(),
        )

        headend_prepared_root = Path(headend_prepared["root"]).resolve()
        headend_customer_root = Path(headend_prepared["apply"]["state_json"]).resolve().parent
        headend_swanctl_conf = Path(headend_prepared["apply"]["swanctl_conf"]).resolve()
        headend_relative_paths = [
            headend_customer_root.relative_to(headend_prepared_root),
            headend_swanctl_conf.relative_to(headend_prepared_root),
        ]
        headend_validate_paths = [
            Path(headend_prepared["apply"]["state_json"]).resolve().relative_to(headend_prepared_root),
            headend_swanctl_conf.relative_to(headend_prepared_root),
            Path(headend_prepared["apply"]["master_apply_script"]).resolve().relative_to(headend_prepared_root),
        ]
        headend_cleanup_paths = [headend_customer_root.relative_to(headend_prepared_root)]
        headend_cleanup_files = [headend_swanctl_conf.relative_to(headend_prepared_root)]
        active_activation = _build_activation_bundle(
            journal,
            customer_name=customer_name,
            component_name="headend",
            target_name=str((target_selection.get("headend_active") or {}).get("name") or "headend-active"),
            apply_dir=apply_dir,
            prepared_root=headend_prepared_root,
            target_root=headend_active_root,
            relative_paths=headend_relative_paths,
            validate_paths=headend_validate_paths,
            cleanup_paths=headend_cleanup_paths,
            cleanup_files=headend_cleanup_files,
            apply_script=Path(headend_prepared["apply"]["master_apply_script"]).resolve(),
            remove_script=Path(headend_prepared["apply"]["master_remove_script"]).resolve(),
        )
        standby_activation = _build_activation_bundle(
            journal,
            customer_name=customer_name,
            component_name="headend",
            target_name=str((target_selection.get("headend_standby") or {}).get("name") or "headend-standby"),
            apply_dir=apply_dir,
            prepared_root=headend_prepared_root,
            target_root=headend_standby_root,
            relative_paths=headend_relative_paths,
            validate_paths=headend_validate_paths,
            cleanup_paths=headend_cleanup_paths,
            cleanup_files=headend_cleanup_files,
            apply_script=Path(headend_prepared["apply"]["master_apply_script"]).resolve(),
            remove_script=Path(headend_prepared["apply"]["master_remove_script"]).resolve(),
        )

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
            action="apply_muxer_activation_bundle",
            target=str((target_selection.get("muxer") or {}).get("name") or "muxer"),
            command=[
                sys.executable,
                "scripts/customers/node_activation_runner.py",
                "--request",
                str(muxer_activation["request_path_obj"]),
                "--json",
            ],
        )
        rollback_steps.append(
            {
                "action": "rollback_muxer_activation_bundle",
                "target": str((target_selection.get("muxer") or {}).get("name") or "muxer"),
                "command": [
                    sys.executable,
                    "scripts/customers/node_activation_runner.py",
                    "--rollback-request",
                    str(muxer_activation["rollback_request_path_obj"]),
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
            action="apply_headend_activation_bundle",
            target=str((target_selection.get("headend_active") or {}).get("name") or "headend-active"),
            command=[
                sys.executable,
                "scripts/customers/node_activation_runner.py",
                "--request",
                str(active_activation["request_path_obj"]),
                "--json",
            ],
        )
        rollback_steps.append(
            {
                "action": "rollback_headend_activation_bundle",
                "target": str((target_selection.get("headend_active") or {}).get("name") or "headend-active"),
                "command": [
                    sys.executable,
                    "scripts/customers/node_activation_runner.py",
                    "--rollback-request",
                    str(active_activation["rollback_request_path_obj"]),
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
            action="apply_headend_activation_bundle",
            target=str((target_selection.get("headend_standby") or {}).get("name") or "headend-standby"),
            command=[
                sys.executable,
                "scripts/customers/node_activation_runner.py",
                "--request",
                str(standby_activation["request_path_obj"]),
                "--json",
            ],
        )
        rollback_steps.append(
            {
                "action": "rollback_headend_activation_bundle",
                "target": str((target_selection.get("headend_standby") or {}).get("name") or "headend-standby"),
                "command": [
                    sys.executable,
                    "scripts/customers/node_activation_runner.py",
                    "--rollback-request",
                    str(standby_activation["rollback_request_path_obj"]),
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
            "mode": "staged_activation_apply",
            "activation_contract": {
                "strategy": "node_local_activation_bundle",
                "primary_backend": "staged_runner",
                "break_glass_compatibility": "ssh_live_apply",
            },
            "roots": {
                "artifacts": repo_relative(staged_artifact_root),
                "datastores": repo_relative(staged_datastore_root),
                "muxer": repo_relative(muxer_root),
                "headend_active": repo_relative(headend_active_root),
                "headend_standby": repo_relative(headend_standby_root),
            },
            "activation_bundles": {
                "muxer": {
                    "bundle_root": muxer_activation["bundle_root"],
                    "request_path": muxer_activation["request_path"],
                    "rollback_request_path": muxer_activation["rollback_request_path"],
                    "payload_root": muxer_activation["payload_root"],
                    "activation_journal": repo_relative(muxer_activation["bundle_root_path"] / "activation-journal.json"),
                    "activation_result": repo_relative(muxer_activation["bundle_root_path"] / "activation-result.json"),
                    "rollback_journal": repo_relative(muxer_activation["bundle_root_path"] / "rollback-journal.json"),
                    "rollback_result": repo_relative(muxer_activation["bundle_root_path"] / "rollback-result.json"),
                },
                "headend_active": {
                    "bundle_root": active_activation["bundle_root"],
                    "request_path": active_activation["request_path"],
                    "rollback_request_path": active_activation["rollback_request_path"],
                    "payload_root": active_activation["payload_root"],
                    "activation_journal": repo_relative(active_activation["bundle_root_path"] / "activation-journal.json"),
                    "activation_result": repo_relative(active_activation["bundle_root_path"] / "activation-result.json"),
                    "rollback_journal": repo_relative(active_activation["bundle_root_path"] / "rollback-journal.json"),
                    "rollback_result": repo_relative(active_activation["bundle_root_path"] / "rollback-result.json"),
                },
                "headend_standby": {
                    "bundle_root": standby_activation["bundle_root"],
                    "request_path": standby_activation["request_path"],
                    "rollback_request_path": standby_activation["rollback_request_path"],
                    "payload_root": standby_activation["payload_root"],
                    "activation_journal": repo_relative(standby_activation["bundle_root_path"] / "activation-journal.json"),
                    "activation_result": repo_relative(standby_activation["bundle_root_path"] / "activation-result.json"),
                    "rollback_journal": repo_relative(standby_activation["bundle_root_path"] / "rollback-journal.json"),
                    "rollback_result": repo_relative(standby_activation["bundle_root_path"] / "rollback-result.json"),
                },
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
            "mode": "staged_activation_apply",
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


def _publish_artifacts_to_s3(
    journal: list[dict[str, Any]],
    *,
    customer_name: str,
    run_id: str,
    package_dir: Path,
    execution_plan_path: Path,
    environment_doc: dict[str, Any],
) -> dict[str, Any]:
    artifacts = environment_doc.get("artifacts") or {}
    bucket = str(artifacts.get("bucket") or "").strip()
    prefix = str(artifacts.get("prefix") or "").strip()
    if not bucket or not prefix:
        raise RuntimeError("artifact bucket/prefix missing from deployment environment")

    run_root = _s3_uri(bucket, prefix, customer_name, run_id)
    package_root = _s3_uri(bucket, prefix, customer_name, run_id, "package")
    execution_plan_uri = _s3_uri(bucket, prefix, customer_name, run_id, "execution-plan.json")

    _execute_local(
        journal,
        action="publish_execution_plan",
        target=execution_plan_uri,
        command=["aws", "s3", "cp", str(execution_plan_path), execution_plan_uri],
    )
    _execute_local(
        journal,
        action="publish_customer_package",
        target=package_root,
        command=["aws", "s3", "cp", str(package_dir), package_root, "--recursive"],
    )
    return {
        "run_root": run_root,
        "package_root": package_root,
        "execution_plan": execution_plan_uri,
    }


def _prepare_backend_root(
    journal: list[dict[str, Any]],
    *,
    customer_name: str,
    package_dir: Path,
    apply_dir: Path,
) -> dict[str, Any]:
    backend_root = apply_dir / "pb"
    if backend_root.exists():
        shutil.rmtree(backend_root)
    backend_root.mkdir(parents=True, exist_ok=True)

    apply_report = _execute_json(
        journal,
        action="prepare_backend_customer",
        target=customer_name,
        command=[
            sys.executable,
            "scripts/deployment/apply_backend_customer.py",
            "--package-dir",
            str(package_dir),
            "--backend-root",
            str(backend_root),
            "--json",
        ],
    )
    validate_report = _execute_json(
        journal,
        action="validate_prepared_backend_customer",
        target=customer_name,
        command=[
            sys.executable,
            "scripts/deployment/validate_backend_customer.py",
            "--package-dir",
            str(package_dir),
            "--backend-root",
            str(backend_root),
            "--json",
        ],
    )
    return {"root": backend_root, "apply": apply_report, "validate": validate_report}


def _prepare_muxer_root(
    journal: list[dict[str, Any]],
    *,
    customer_name: str,
    bundle_dir: Path,
    apply_dir: Path,
) -> dict[str, Any]:
    muxer_root = apply_dir / "pm"
    if muxer_root.exists():
        shutil.rmtree(muxer_root)
    muxer_root.mkdir(parents=True, exist_ok=True)

    apply_report = _execute_json(
        journal,
        action="prepare_muxer_customer",
        target=customer_name,
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
    validate_report = _execute_json(
        journal,
        action="validate_prepared_muxer_customer",
        target=customer_name,
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
    return {"root": muxer_root, "apply": apply_report, "validate": validate_report}


def _prepare_muxer_runtime_root(journal: list[dict[str, Any]], *, apply_dir: Path) -> dict[str, Any]:
    runtime_source = REPO_ROOT / "muxer" / "runtime-package" / "src"
    if not runtime_source.is_dir():
        raise RuntimeError(f"muxer runtime source is missing: {runtime_source}")

    runtime_root = apply_dir / "pr"
    if runtime_root.exists():
        shutil.rmtree(runtime_root)
    destination = runtime_root / "etc" / "muxer" / "src"
    shutil.copytree(
        runtime_source,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for script in ("muxctl.py", "mux_trace.py", "ike_nat_bridge.py"):
        script_path = destination / script
        if script_path.exists():
            try:
                script_path.chmod(script_path.stat().st_mode | 0o111)
            except OSError:
                pass

    payload = {
        "runtime_source": repo_relative(runtime_source),
        "runtime_root": repo_relative(runtime_root),
        "destination": repo_relative(destination),
        "relative_paths": ["etc/muxer/src"],
    }
    _record_structured(
        journal,
        action="prepare_muxer_runtime_payload",
        target="muxer-runtime",
        payload=payload,
    )
    return {
        **payload,
        "root": runtime_root,
        "destination_path": destination,
        "relative_paths_obj": [Path("etc") / "muxer" / "src"],
    }


def _prepare_headend_root(
    journal: list[dict[str, Any]],
    *,
    customer_name: str,
    bundle_dir: Path,
    apply_dir: Path,
) -> dict[str, Any]:
    headend_root = apply_dir / "ph"
    if headend_root.exists():
        shutil.rmtree(headend_root)
    headend_root.mkdir(parents=True, exist_ok=True)

    apply_report = _execute_json(
        journal,
        action="prepare_headend_customer",
        target=customer_name,
        command=[
            sys.executable,
            "scripts/deployment/apply_headend_customer.py",
            "--bundle-dir",
            str(bundle_dir),
            "--headend-root",
            str(headend_root),
            "--json",
        ],
    )
    validate_report = _execute_json(
        journal,
        action="validate_prepared_headend_customer",
        target=customer_name,
        command=[
            sys.executable,
            "scripts/deployment/validate_headend_customer.py",
            "--bundle-dir",
            str(bundle_dir),
            "--headend-root",
            str(headend_root),
            "--json",
        ],
    )
    return {"root": headend_root, "apply": apply_report, "validate": validate_report}


def _copy_relative_paths(source_root: Path, destination_root: Path, relative_paths: list[Path]) -> None:
    for relative_path in relative_paths:
        source_path = (source_root / relative_path).resolve()
        destination_path = (destination_root / relative_path).resolve()
        if not source_path.exists():
            raise RuntimeError(f"prepared activation payload path missing: {source_path}")
        if source_path.is_dir():
            if destination_path.exists():
                shutil.rmtree(destination_path)
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_path, destination_path)
        else:
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination_path)


def _build_activation_bundle(
    journal: list[dict[str, Any]],
    *,
    customer_name: str,
    component_name: str,
    target_name: str,
    apply_dir: Path,
    prepared_root: Path,
    target_root: Path,
    relative_paths: list[Path],
    validate_paths: list[Path],
    cleanup_paths: list[Path],
    cleanup_files: list[Path],
    apply_script: Path | None = None,
    remove_script: Path | None = None,
    execute_apply_command: bool = False,
    execute_remove_command: bool = False,
) -> dict[str, Any]:
    target_slug = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in target_name).strip("-") or component_name
    target_slug = f"{target_slug[:6]}-{hashlib.sha1(target_name.encode('utf-8')).hexdigest()[:6]}"
    component_slug = (component_name[:1] or "c").lower()
    bundle_root = apply_dir / "b" / component_slug / target_slug
    if bundle_root.exists():
        shutil.rmtree(bundle_root)
    payload_root = bundle_root / "p"
    payload_root.mkdir(parents=True, exist_ok=True)
    _copy_relative_paths(prepared_root, payload_root, relative_paths)

    apply_script_rel = (
        str(apply_script.resolve().relative_to(prepared_root.resolve())).replace("\\", "/")
        if apply_script is not None
        else ""
    )
    remove_script_rel = (
        str(remove_script.resolve().relative_to(prepared_root.resolve())).replace("\\", "/")
        if remove_script is not None
        else ""
    )
    request = {
        "schema_version": 1,
        "customer_name": customer_name,
        "component_name": component_name,
        "target_name": target_name,
        "target_root": str(target_root.resolve()),
        "payload_root": "p",
        "copy_paths": [str(path).replace("\\", "/") for path in relative_paths],
        "validate_paths": [str(path).replace("\\", "/") for path in validate_paths],
        "execute_apply_command": execute_apply_command,
        "apply_command": [],
        "apply_script_relative": apply_script_rel,
    }
    rollback_request = {
        "schema_version": 1,
        "customer_name": customer_name,
        "component_name": component_name,
        "target_name": target_name,
        "target_root": str(target_root.resolve()),
        "cleanup_paths": [str(path).replace("\\", "/") for path in cleanup_paths],
        "cleanup_files": [str(path).replace("\\", "/") for path in cleanup_files],
        "execute_remove_command": execute_remove_command,
        "remove_command": [],
        "remove_script_relative": remove_script_rel,
    }
    request_path = bundle_root / "r.json"
    rollback_request_path = bundle_root / "rr.json"
    write_json(request_path, request)
    write_json(rollback_request_path, rollback_request)
    payload = {
        "bundle_root": repo_relative(bundle_root),
        "request_path": repo_relative(request_path),
        "rollback_request_path": repo_relative(rollback_request_path),
        "payload_root": repo_relative(payload_root),
        "component_name": component_name,
        "target_name": target_name,
    }
    _record_structured(
        journal,
        action=f"build_{component_name}_activation_bundle",
        target=target_name,
        payload=payload,
    )
    return {
        **payload,
        "bundle_root_path": bundle_root,
        "request_path_obj": request_path,
        "rollback_request_path_obj": rollback_request_path,
    }


def _record_remote_result(
    journal: list[dict[str, Any]],
    *,
    action: str,
    target: str,
    result: dict[str, Any],
) -> None:
    command = list(result.get("command") or result.get("copy_command") or [])
    stdout = "\n".join(
        [part for part in (result.get("stdout"), result.get("copy_stdout"), result.get("extract_stdout")) if part]
    )
    stderr = "\n".join(
        [part for part in (result.get("stderr"), result.get("copy_stderr"), result.get("extract_stderr")) if part]
    )
    _record_action(
        journal,
        action=action,
        target=target,
        command=command,
        payload=result,
        returncode=0 if result.get("success") else 1,
        stdout=stdout,
        stderr=stderr,
    )


def _apply_remote_component(
    journal: list[dict[str, Any]],
    *,
    context: Any,
    component_name: str,
    target_name: str,
    target_instance_id: str,
    via_bastion: bool,
    prepared_root: Path,
    relative_paths: list[Path],
    remote_apply_script: str,
    remote_remove_script: str,
    remote_checks: list[str],
    remote_cleanup_paths: list[str],
    remote_cleanup_files: list[str],
    remote_name: str,
) -> dict[str, Any]:
    copy_result = copy_paths_to_remote_root(
        context=context,
        target_instance_id=target_instance_id,
        source_root=prepared_root,
        relative_paths=relative_paths,
        remote_name=remote_name,
        via_bastion=via_bastion,
    )
    _record_remote_result(
        journal,
        action=f"copy_{component_name}_payload",
        target=target_name,
        result=copy_result,
    )
    if not copy_result.get("success"):
        raise RuntimeError(f"copy_{component_name}_payload failed for {target_name}")

    cleanup_parts: list[str] = [
        f"if [ -f {shlex.quote(remote_remove_script)} ]; then bash {shlex.quote(remote_remove_script)}; fi"
    ]
    if remote_cleanup_paths:
        cleanup_parts.append("rm -rf " + " ".join(shlex.quote(path) for path in remote_cleanup_paths))
    if remote_cleanup_files:
        cleanup_parts.append("rm -f " + " ".join(shlex.quote(path) for path in remote_cleanup_files))
    cleanup_command = "; ".join(cleanup_parts)

    apply_result = run_remote_command(
        context=context,
        target_instance_id=target_instance_id,
        via_bastion=via_bastion,
        remote_command=_sudo_shell(f"bash {shlex.quote(remote_apply_script)}"),
    )
    _record_remote_result(
        journal,
        action=f"apply_{component_name}_customer",
        target=target_name,
        result=apply_result,
    )
    if not apply_result.get("success"):
        cleanup_result = run_remote_command(
            context=context,
            target_instance_id=target_instance_id,
            via_bastion=via_bastion,
            remote_command=_sudo_shell(cleanup_command, strict=False),
        )
        _record_remote_result(
            journal,
            action=f"cleanup_{component_name}_payload_after_failed_apply",
            target=target_name,
            result=cleanup_result,
        )
        raise RuntimeError(f"apply_{component_name}_customer failed for {target_name}")

    validate_result = run_remote_command(
        context=context,
        target_instance_id=target_instance_id,
        via_bastion=via_bastion,
        remote_command=_sudo_shell("; ".join(f"test -f {shlex.quote(path)}" for path in remote_checks)),
    )
    _record_remote_result(
        journal,
        action=f"validate_{component_name}_customer",
        target=target_name,
        result=validate_result,
    )
    if not validate_result.get("success"):
        cleanup_result = run_remote_command(
            context=context,
            target_instance_id=target_instance_id,
            via_bastion=via_bastion,
            remote_command=_sudo_shell(cleanup_command, strict=False),
        )
        _record_remote_result(
            journal,
            action=f"cleanup_{component_name}_payload_after_failed_validate",
            target=target_name,
            result=cleanup_result,
        )
        raise RuntimeError(f"validate_{component_name}_customer failed for {target_name}")

    return {
        "copy": copy_result,
        "apply": apply_result,
        "validate": validate_result,
        "rollback": {
            "kind": "remote",
            "action": f"remove_{component_name}_customer",
            "target": target_name,
            "target_instance_id": target_instance_id,
            "via_bastion": via_bastion,
            "command_text": cleanup_command,
        },
    }


def _sync_muxer_runtime(
    journal: list[dict[str, Any]],
    *,
    context: Any,
    target_name: str,
    target_instance_id: str,
    runtime_prepared: dict[str, Any],
) -> dict[str, Any]:
    copy_result = copy_paths_to_remote_root(
        context=context,
        target_instance_id=target_instance_id,
        source_root=Path(runtime_prepared["root"]),
        relative_paths=list(runtime_prepared["relative_paths_obj"]),
        remote_name="rpdb-muxer-runtime",
        via_bastion=False,
    )
    _record_remote_result(
        journal,
        action="copy_muxer_runtime_payload",
        target=target_name,
        result=copy_result,
    )
    if not copy_result.get("success"):
        raise RuntimeError(f"copy_muxer_runtime_payload failed for {target_name}")

    validation_script = " && ".join(
        [
            "python3 -m py_compile /etc/muxer/src/muxctl.py /etc/muxer/src/muxerlib/*.py",
            "grep -q 'dnat to ip saddr map' /etc/muxer/src/muxerlib/nftables.py",
            "grep -q 'snat to ip saddr . ip daddr map' /etc/muxer/src/muxerlib/nftables.py",
            "! grep -q 'ipv4_addr : verdict' /etc/muxer/src/muxerlib/nftables.py",
            "! grep -q 'vmap @udp500_dnat' /etc/muxer/src/muxerlib/nftables.py",
        ]
    )
    validate_result = run_remote_command(
        context=context,
        target_instance_id=target_instance_id,
        via_bastion=False,
        remote_command=_sudo_shell(validation_script),
    )
    _record_remote_result(
        journal,
        action="validate_muxer_runtime_payload",
        target=target_name,
        result=validate_result,
    )
    if not validate_result.get("success"):
        raise RuntimeError(f"validate_muxer_runtime_payload failed for {target_name}")

    return {
        "copy": copy_result,
        "validate": validate_result,
    }


def _rollback_ssh_live(
    *,
    context: Any | None,
    rollback_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    rollback_errors: list[str] = []
    for step in reversed(rollback_steps):
        try:
            if step["kind"] == "backend":
                payload = rollback_backend_payloads(
                    region=step["region"],
                    customer_table=step["customer_table"],
                    allocation_table=step["allocation_table"],
                    customer_item_plain=step["customer_item_plain"],
                    allocation_items_typed=step["allocation_items_typed"],
                    customer_action=str(step.get("customer_action") or "created"),
                    allocation_results=list(step.get("allocation_results") or []),
                )
                results.append(
                    {
                        "recorded_at": utc_now(),
                        "action": step["action"],
                        "target": step["target"],
                        "payload": payload,
                        "success": payload.get("status") == "rolled_back",
                    }
                )
                if payload.get("status") != "rolled_back":
                    rollback_errors.extend(payload.get("errors") or [])
                continue

            if context is None:
                raise RuntimeError("SSH rollback context is not available")

            result = run_remote_command(
                context=context,
                target_instance_id=step["target_instance_id"],
                via_bastion=bool(step.get("via_bastion")),
                remote_command=_sudo_shell(str(step["command_text"]), strict=False),
            )
            results.append(
                {
                    "recorded_at": utc_now(),
                    "action": step["action"],
                    "target": step["target"],
                    "command": result.get("command"),
                    "stdout": result.get("stdout"),
                    "stderr": result.get("stderr"),
                    "success": bool(result.get("success")),
                }
            )
            if not result.get("success"):
                rollback_errors.append(
                    f"{step['action']} failed for {step['target']}: {result.get('stderr') or result.get('stdout')}"
                )
        except Exception as exc:  # pragma: no cover - rollback best effort
            rollback_errors.append(f"{step['action']} failed for {step['target']}: {exc}")
    return {
        "status": "rolled_back" if not rollback_errors else "rollback_failed",
        "errors": rollback_errors,
        "steps": results,
    }


def execute_ssh_live_apply(
    *,
    customer_name: str,
    package_dir: Path,
    bundle_dir: Path,
    deploy_dir: Path,
    target_selection: dict[str, Any],
    environment_doc: dict[str, Any],
    execution_plan_path: Path,
) -> dict[str, Any]:
    apply_dir = deploy_dir / "approved-apply"
    apply_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    journal: list[dict[str, Any]] = []
    rollback_steps: list[dict[str, Any]] = []
    context: Any | None = None

    try:
        region = str(((environment_doc.get("environment") or {}).get("aws") or {}).get("region") or "").strip()
        if not region:
            raise RuntimeError("environment.aws.region is required for live apply")

        backend_prepared = _prepare_backend_root(
            journal,
            customer_name=customer_name,
            package_dir=package_dir,
            apply_dir=apply_dir,
        )
        muxer_prepared = _prepare_muxer_root(
            journal,
            customer_name=customer_name,
            bundle_dir=bundle_dir,
            apply_dir=apply_dir,
        )
        muxer_runtime_prepared = _prepare_muxer_runtime_root(
            journal,
            apply_dir=apply_dir,
        )
        headend_prepared = _prepare_headend_root(
            journal,
            customer_name=customer_name,
            bundle_dir=bundle_dir,
            apply_dir=apply_dir,
        )
        headend_secret = _inject_live_headend_secret(
            journal,
            package_dir=package_dir,
            headend_prepared=headend_prepared,
            region=region,
        )
        headend_prepared["secret_resolution"] = headend_secret

        published_artifacts = _publish_artifacts_to_s3(
            journal,
            customer_name=customer_name,
            run_id=run_id,
            package_dir=package_dir,
            execution_plan_path=execution_plan_path,
            environment_doc=environment_doc,
        )

        customer_item_plain, allocation_items_typed = load_customer_backend_payloads(package_dir)

        datastores = environment_doc.get("datastores") or {}
        customer_table = str(datastores.get("customer_sot_table") or "").strip()
        allocation_table = str(datastores.get("allocation_table") or "").strip()
        if not customer_table or not allocation_table:
            raise RuntimeError("deployment environment datastores are incomplete")

        backend_apply = apply_backend_payloads(
            region=region,
            customer_table=customer_table,
            allocation_table=allocation_table,
            customer_item_plain=customer_item_plain,
            allocation_items_typed=allocation_items_typed,
        )
        _record_structured(
            journal,
            action="apply_backend_customer",
            target="dynamodb",
            payload=backend_apply,
        )
        rollback_preexisting_remote_customer = not _backend_apply_created_records(backend_apply)
        if not rollback_preexisting_remote_customer:
            rollback_steps.append(
                {
                    "kind": "backend",
                    "action": "remove_backend_customer",
                    "target": "dynamodb",
                    "region": region,
                    "customer_table": customer_table,
                    "allocation_table": allocation_table,
                    "customer_item_plain": customer_item_plain,
                    "allocation_items_typed": allocation_items_typed,
                    "customer_action": backend_apply.get("customer_action"),
                    "allocation_results": backend_apply.get("allocation_results") or [],
                }
            )

        backend_validation = validate_backend_payloads(
            region=region,
            customer_table=customer_table,
            allocation_table=allocation_table,
            customer_item_plain=customer_item_plain,
            allocation_items_typed=allocation_items_typed,
        )
        _record_structured(
            journal,
            action="validate_backend_customer",
            target="dynamodb",
            payload=backend_validation,
        )
        if not backend_validation.get("valid"):
            raise RuntimeError("backend validation failed after DynamoDB apply")

        environment_access = ((environment_doc.get("environment") or {}).get("access") or {})
        ssh_user = str(((environment_access.get("ssh") or {}).get("user")) or "").strip()
        if not ssh_user:
            raise RuntimeError("environment.access.ssh.user is required for SSH live apply")

        muxer_target = target_selection.get("muxer") or {}
        muxer_selector = muxer_target.get("selector") or {}
        muxer_instance_id = str(muxer_selector.get("value") or "").strip()
        if not muxer_instance_id:
            raise RuntimeError("selected muxer target is missing an instance_id selector")

        headend_active = target_selection.get("headend_active") or {}
        headend_standby = target_selection.get("headend_standby") or {}
        active_instance_id = str(((headend_active.get("selector") or {}).get("value")) or "").strip()
        standby_instance_id = str(((headend_standby.get("selector") or {}).get("value")) or "").strip()
        if not active_instance_id or not standby_instance_id:
            raise RuntimeError("selected head-end targets are missing instance_id selectors")

        context = build_ssh_access_context(
            region=region,
            ssh_user=ssh_user,
            bastion_instance_id=muxer_instance_id,
            target_instance_ids=[muxer_instance_id, active_instance_id, standby_instance_id],
        )

        muxer_root = Path(muxer_prepared["root"]).resolve()
        headend_root = Path(headend_prepared["root"]).resolve()

        muxer_runtime_remote = _sync_muxer_runtime(
            journal,
            context=context,
            target_name=str(muxer_target.get("name") or "muxer"),
            target_instance_id=muxer_instance_id,
            runtime_prepared=muxer_runtime_prepared,
        )

        muxer_customer_root = Path(muxer_prepared["apply"]["state_json"]).resolve().parent
        muxer_module_root = Path(muxer_prepared["apply"]["customer_module"]).resolve().parent
        muxer_remote = _apply_remote_component(
            journal,
            context=context,
            component_name="muxer",
            target_name=str(muxer_target.get("name") or "muxer"),
            target_instance_id=muxer_instance_id,
            via_bastion=False,
            prepared_root=muxer_root,
            relative_paths=[
                muxer_customer_root.relative_to(muxer_root),
                muxer_module_root.relative_to(muxer_root),
            ],
            remote_apply_script=_remote_path(muxer_root, muxer_prepared["apply"]["master_apply_script"]),
            remote_remove_script=_remote_path(muxer_root, muxer_prepared["apply"]["master_remove_script"]),
            remote_checks=[
                _remote_path(muxer_root, muxer_prepared["apply"]["state_json"]),
                _remote_path(muxer_root, muxer_prepared["apply"]["customer_module"]),
                _remote_path(muxer_root, muxer_prepared["apply"]["master_apply_script"]),
            ],
            remote_cleanup_paths=[
                _remote_path(muxer_root, muxer_customer_root),
                _remote_path(muxer_root, muxer_module_root),
            ],
            remote_cleanup_files=[],
            remote_name=f"{customer_name}-muxer",
        )
        if not rollback_preexisting_remote_customer:
            rollback_steps.append(muxer_remote["rollback"])

        headend_customer_root = Path(headend_prepared["apply"]["state_json"]).resolve().parent
        headend_swanctl_conf = Path(headend_prepared["apply"]["swanctl_conf"]).resolve()
        headend_relative_paths = [
            headend_customer_root.relative_to(headend_root),
            headend_swanctl_conf.relative_to(headend_root),
        ]
        headend_remote_apply = _remote_path(headend_root, headend_prepared["apply"]["master_apply_script"])
        headend_remote_remove = _remote_path(headend_root, headend_prepared["apply"]["master_remove_script"])
        headend_remote_checks = [
            _remote_path(headend_root, headend_prepared["apply"]["state_json"]),
            _remote_path(headend_root, headend_prepared["apply"]["swanctl_conf"]),
            _remote_path(headend_root, headend_prepared["apply"]["master_apply_script"]),
        ]
        headend_cleanup_paths = [_remote_path(headend_root, headend_customer_root)]
        headend_cleanup_files = [_remote_path(headend_root, headend_swanctl_conf)]

        active_remote = _apply_remote_component(
            journal,
            context=context,
            component_name="headend",
            target_name=str(headend_active.get("name") or "headend-active"),
            target_instance_id=active_instance_id,
            via_bastion=True,
            prepared_root=headend_root,
            relative_paths=headend_relative_paths,
            remote_apply_script=headend_remote_apply,
            remote_remove_script=headend_remote_remove,
            remote_checks=headend_remote_checks,
            remote_cleanup_paths=headend_cleanup_paths,
            remote_cleanup_files=headend_cleanup_files,
            remote_name=f"{customer_name}-headend-active",
        )
        if not rollback_preexisting_remote_customer:
            rollback_steps.append(active_remote["rollback"])

        standby_remote = _apply_remote_component(
            journal,
            context=context,
            component_name="headend",
            target_name=str(headend_standby.get("name") or "headend-standby"),
            target_instance_id=standby_instance_id,
            via_bastion=True,
            prepared_root=headend_root,
            relative_paths=headend_relative_paths,
            remote_apply_script=headend_remote_apply,
            remote_remove_script=headend_remote_remove,
            remote_checks=headend_remote_checks,
            remote_cleanup_paths=headend_cleanup_paths,
            remote_cleanup_files=headend_cleanup_files,
            remote_name=f"{customer_name}-headend-standby",
        )
        if not rollback_preexisting_remote_customer:
            rollback_steps.append(standby_remote["rollback"])

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
            "mode": "ssh_live_apply",
            "roots": {
                "prepared_backend": repo_relative(Path(backend_prepared["root"])),
                "prepared_muxer": repo_relative(Path(muxer_prepared["root"])),
                "prepared_headend": repo_relative(Path(headend_prepared["root"])),
            },
            "published_artifacts": published_artifacts,
            "validation": {
                "backend": backend_validation,
                "prepared_backend": backend_prepared["validate"],
                "prepared_muxer": muxer_prepared["validate"],
                "muxer_runtime": muxer_runtime_remote["validate"],
                "prepared_headend": headend_prepared["validate"],
                "headend_secret": headend_secret,
                "muxer": muxer_remote["validate"],
                "headend_active": active_remote["validate"],
                "headend_standby": standby_remote["validate"],
            },
            "applies": {
                "backend": backend_apply,
                "muxer_runtime": muxer_runtime_remote["copy"],
                "muxer": muxer_remote["apply"],
                "headend_active": active_remote["apply"],
                "headend_standby": standby_remote["apply"],
            },
            "rollback_plan": repo_relative(apply_dir / "rollback-plan.json"),
            "apply_journal": repo_relative(apply_dir / "apply-journal.json"),
        }
        write_json(apply_dir / "rollback-plan.json", rollback_plan)
        write_json(apply_dir / "apply-journal.json", journal_payload)
        write_json(apply_dir / "apply-result.json", result)
        return result
    except Exception as exc:
        rollback_result = _rollback_ssh_live(context=context, rollback_steps=rollback_steps)
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
            "mode": "ssh_live_apply",
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
    finally:
        if context is not None:
            cleanup_ssh_access_context(context)


def execute_live_apply(
    *,
    customer_name: str,
    package_dir: Path,
    bundle_dir: Path,
    deploy_dir: Path,
    target_selection: dict[str, Any],
    environment_doc: dict[str, Any],
    execution_plan_path: Path,
) -> dict[str, Any]:
    access_method = str(
        (((environment_doc.get("environment") or {}).get("access") or {}).get("method") or "")
    ).strip()
    if access_method == "staged":
        return execute_staged_live_apply(
            customer_name=customer_name,
            package_dir=package_dir,
            bundle_dir=bundle_dir,
            deploy_dir=deploy_dir,
            target_selection=target_selection,
            environment_doc=environment_doc,
            execution_plan_path=execution_plan_path,
        )
    if access_method == "ssh":
        return execute_ssh_live_apply(
            customer_name=customer_name,
            package_dir=package_dir,
            bundle_dir=bundle_dir,
            deploy_dir=deploy_dir,
            target_selection=target_selection,
            environment_doc=environment_doc,
            execution_plan_path=execution_plan_path,
        )
    raise ValueError(f"approved live apply is not implemented for access method {access_method or 'unknown'}")
