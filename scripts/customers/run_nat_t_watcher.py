#!/usr/bin/env python
"""Run the RPDB NAT-T control-plane watcher from an environment contract."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MUXER_SRC = REPO_ROOT / "muxer" / "src"
if str(MUXER_SRC) not in sys.path:
    sys.path.insert(0, str(MUXER_SRC))

from muxerlib.customer_merge import load_yaml_file

from live_access_lib import (
    build_ssh_access_context,
    cleanup_ssh_access_context,
    copy_remote_file_to_local,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_json(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    parsed: dict[str, Any] | None = None
    if completed.stdout.strip():
        try:
            parsed = json.loads(completed.stdout)
        except json.JSONDecodeError:
            parsed = None
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "json": parsed,
    }


def resolve_environment_path(value: str) -> Path:
    raw = Path(value)
    candidates = [raw if raw.is_absolute() else (REPO_ROOT / raw).resolve()]
    if raw.suffix.lower() not in {".yaml", ".yml"}:
        candidates.append((REPO_ROOT / "muxer" / "config" / "deployment-environments" / f"{value}.yaml").resolve())
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"deployment environment not found: {value}")


def repo_path(value: str) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def selector_instance_id(target: dict[str, Any]) -> str:
    selector = target.get("selector") or {}
    if str(selector.get("type") or "").strip() != "instance_id":
        raise ValueError(f"target {target.get('name')} does not use an instance_id selector")
    instance_id = str(selector.get("value") or "").strip()
    if not instance_id:
        raise ValueError(f"target {target.get('name')} is missing selector.value")
    return instance_id


def should_sync_log(environment_doc: dict[str, Any], log_path: Path, sync_mode: str) -> bool:
    if sync_mode == "local_file":
        return False
    if sync_mode == "ssh_muxer":
        return True
    access_method = str((((environment_doc.get("environment") or {}).get("access") or {}).get("method")) or "").strip()
    return access_method == "ssh" and log_path.is_absolute() and not log_path.exists()


def sync_muxer_log(
    *,
    environment_doc: dict[str, Any],
    remote_path: str,
    local_copy: Path,
) -> dict[str, Any]:
    environment = environment_doc.get("environment") or {}
    region = str((environment.get("aws") or {}).get("region") or "").strip()
    ssh_user = str(((environment.get("access") or {}).get("ssh") or {}).get("user") or "").strip()
    muxer = (environment_doc.get("targets") or {}).get("muxer") or {}
    muxer_instance_id = selector_instance_id(muxer)
    if not region or not ssh_user:
        raise ValueError("environment.aws.region and environment.access.ssh.user are required for muxer log sync")

    context = build_ssh_access_context(
        region=region,
        ssh_user=ssh_user,
        bastion_instance_id=muxer_instance_id,
        target_instance_ids=[muxer_instance_id],
    )
    try:
        return copy_remote_file_to_local(
            context=context,
            target_instance_id=muxer_instance_id,
            remote_path=remote_path,
            local_path=local_copy,
            via_bastion=False,
            timeout_seconds=180,
        )
    finally:
        cleanup_ssh_access_context(context)


def build_watcher_command(
    *,
    environment_ref: str,
    environment_doc: dict[str, Any],
    log_file: Path,
    approve: bool,
    reprocess: bool,
    json_output: bool,
) -> list[str]:
    watcher = environment_doc.get("nat_t_watcher") or {}
    automation = watcher.get("automation") or {}
    promotion = watcher.get("promotion") or {}
    customer_requests = environment_doc.get("customer_requests") or {}
    access_method = str((((environment_doc.get("environment") or {}).get("access") or {}).get("method")) or "").strip()
    default_promotion_mode = "remove_reapply" if access_method == "ssh" else "deploy_only"

    command = [
        sys.executable,
        "muxer/scripts/watch_nat_t_logs.py",
        "--log-file",
        str(log_file),
        "--state-file",
        str(repo_path(str(watcher.get("state_root") or "build/nat-t-watcher/state")) / "state.json"),
        "--out-dir",
        str(repo_path(str(watcher.get("output_root") or "build/nat-t-watcher/out"))),
        "--package-root",
        str(repo_path(str(watcher.get("package_root") or "build/nat-t-watcher/packages"))),
        "--environment",
        environment_ref,
        "--promotion-mode",
        str(promotion.get("mode") or default_promotion_mode),
    ]
    for root in customer_requests.get("allowed_roots") or []:
        command.extend(["--customer-request-root", str(repo_path(str(root)))])
    if bool(automation.get("run_provisioning", True)):
        command.append("--run-provisioning")
    if approve:
        command.append("--approve")
    if reprocess:
        command.append("--reprocess")
    if json_output:
        command.append("--json")
    return command


def run_once(args: argparse.Namespace, environment_path: Path, environment_doc: dict[str, Any]) -> dict[str, Any]:
    watcher = environment_doc.get("nat_t_watcher") or {}
    log_source = watcher.get("log_source") or {}
    log_sync = watcher.get("log_sync") or {}
    automation = watcher.get("automation") or {}

    source_path = str(log_source.get("path") or "").strip()
    if not source_path:
        raise ValueError("nat_t_watcher.log_source.path is required")

    sync_mode = str(args.log_sync_mode or log_sync.get("mode") or "auto").strip()
    source_log = Path(source_path)
    local_log = repo_path(str(args.local_log or log_sync.get("local_copy") or source_path))
    sync_report: dict[str, Any] | None = None
    if should_sync_log(environment_doc, source_log, sync_mode):
        sync_report = sync_muxer_log(
            environment_doc=environment_doc,
            remote_path=source_path,
            local_copy=local_log,
        )
        if not sync_report.get("success"):
            return {
                "schema_version": 1,
                "action": "run_nat_t_watcher",
                "status": "blocked",
                "generated_at": utc_now(),
                "environment_file": str(environment_path),
                "sync": sync_report,
                "watcher": None,
                "errors": ["failed to sync muxer NAT-T event log"],
            }
    else:
        local_log = source_log if source_log.is_absolute() else repo_path(str(source_log))

    approve = bool(args.approve)

    watcher_command = build_watcher_command(
        environment_ref=str(environment_path),
        environment_doc=environment_doc,
        log_file=local_log,
        approve=approve,
        reprocess=bool(args.reprocess),
        json_output=True,
    )
    watcher_result = run_json(watcher_command)
    watcher_json = watcher_result.get("json") or {}
    status = "ok" if watcher_result.get("returncode") == 0 else "blocked"
    return {
        "schema_version": 1,
        "action": "run_nat_t_watcher",
        "status": status,
        "generated_at": utc_now(),
        "environment_file": str(environment_path),
        "approve": approve,
        "follow": bool(args.follow),
        "sync": sync_report,
        "watcher": watcher_result,
        "detected_count": watcher_json.get("detected_count"),
        "ignored_count": watcher_json.get("ignored_count"),
        "errors": [] if status == "ok" else ["watcher command failed"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RPDB NAT-T watcher from a deployment environment.")
    parser.add_argument("--environment", required=True, help="Deployment environment name or YAML path")
    parser.add_argument("--approve", action="store_true", help="Allow the watcher to execute approved promotion apply")
    parser.add_argument("--follow", action="store_true", help="Keep polling instead of running once")
    parser.add_argument("--reprocess", action="store_true", help="Reprocess the copied/local event log from the beginning")
    parser.add_argument("--poll-interval-seconds", type=float, help="Override environment poll interval")
    parser.add_argument("--log-sync-mode", choices=["auto", "local_file", "ssh_muxer"], help="Override environment log sync mode")
    parser.add_argument("--local-log", help="Override local synced log path")
    parser.add_argument("--json", action="store_true", help="Print runner reports as JSON")
    args = parser.parse_args()

    environment_path = resolve_environment_path(args.environment)
    environment_doc = load_yaml_file(environment_path)
    automation = (environment_doc.get("nat_t_watcher") or {}).get("automation") or {}
    if not bool(automation.get("enabled", True)):
        report = {
            "schema_version": 1,
            "action": "run_nat_t_watcher",
            "status": "disabled",
            "generated_at": utc_now(),
            "environment_file": str(environment_path),
            "errors": ["nat_t_watcher.automation.enabled is false"],
        }
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print("NAT-T watcher automation is disabled")
        return 0

    follow = bool(args.follow or automation.get("follow"))
    poll_interval = float(args.poll_interval_seconds or automation.get("poll_interval_seconds") or 15)
    final_report: dict[str, Any] | None = None
    while True:
        final_report = run_once(args, environment_path, environment_doc)
        runner_out = repo_path(str((environment_doc.get("nat_t_watcher") or {}).get("output_root") or "build/nat-t-watcher/out"))
        write_json(runner_out / "runner-summary.json", final_report)
        if args.json:
            print(json.dumps(final_report, indent=2, sort_keys=True))
        elif final_report["status"] != "ok":
            print(f"NAT-T watcher runner: {final_report['status']}")
        if not follow:
            return 0 if final_report["status"] in {"ok", "disabled"} else 1
        time.sleep(max(poll_interval, 1.0))


if __name__ == "__main__":
    raise SystemExit(main())
