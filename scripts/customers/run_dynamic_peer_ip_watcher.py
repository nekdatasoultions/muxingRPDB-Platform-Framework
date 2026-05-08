#!/usr/bin/env python
"""Run the RPDB dynamic peer IP watcher from an environment contract."""

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


def build_watcher_command(
    *,
    environment_ref: str,
    environment_doc: dict[str, Any],
    approve: bool,
    json_output: bool,
) -> list[str]:
    watcher = environment_doc.get("dynamic_peer_ip_watcher") or {}
    automation = watcher.get("automation") or {}
    command = [
        sys.executable,
        "muxer/scripts/watch_dynamic_peer_ip_registry.py",
        "--environment",
        environment_ref,
        "--state-file",
        str(repo_path(str(watcher.get("state_root") or "build/dynamic-peer-ip-watcher/state")) / "state.json"),
        "--out-dir",
        str(repo_path(str(watcher.get("output_root") or "build/dynamic-peer-ip-watcher/out"))),
        "--package-root",
        str(repo_path(str(watcher.get("package_root") or "build/dynamic-peer-ip-watcher/packages"))),
    ]
    if bool(automation.get("run_provisioning", True)):
        command.append("--run-provisioning")
    if approve:
        command.append("--approve")
    if json_output:
        command.append("--json")
    return command


def run_once(args: argparse.Namespace, environment_path: Path, environment_doc: dict[str, Any]) -> dict[str, Any]:
    watcher = environment_doc.get("dynamic_peer_ip_watcher") or {}
    approve = bool(args.approve)
    watcher_command = build_watcher_command(
        environment_ref=str(environment_path),
        environment_doc=environment_doc,
        approve=approve,
        json_output=True,
    )
    watcher_result = run_json(watcher_command)
    status = "ok" if watcher_result.get("returncode") == 0 else "blocked"
    return {
        "schema_version": 1,
        "action": "run_dynamic_peer_ip_watcher",
        "status": status,
        "generated_at": utc_now(),
        "environment_file": str(environment_path),
        "approve": approve,
        "follow": bool(args.follow),
        "watcher": watcher_result,
        "detected_count": ((watcher_result.get("json") or {}).get("detected_count")),
        "ignored_count": ((watcher_result.get("json") or {}).get("ignored_count")),
        "errors": [] if status == "ok" else ["watcher command failed"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RPDB dynamic peer IP watcher from a deployment environment.")
    parser.add_argument("--environment", required=True, help="Deployment environment name or YAML path")
    parser.add_argument("--approve", action="store_true", help="Allow the watcher to execute approved reapply")
    parser.add_argument("--follow", action="store_true", help="Keep polling instead of running once")
    parser.add_argument("--poll-interval-seconds", type=float, help="Override environment poll interval")
    parser.add_argument("--json", action="store_true", help="Print runner reports as JSON")
    args = parser.parse_args()

    environment_path = resolve_environment_path(args.environment)
    environment_doc = load_yaml_file(environment_path)
    automation = (environment_doc.get("dynamic_peer_ip_watcher") or {}).get("automation") or {}
    if not bool(automation.get("enabled", True)):
        report = {
            "schema_version": 1,
            "action": "run_dynamic_peer_ip_watcher",
            "status": "disabled",
            "generated_at": utc_now(),
            "environment_file": str(environment_path),
            "errors": ["dynamic_peer_ip_watcher.automation.enabled is false"],
        }
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print("Dynamic peer IP watcher automation is disabled")
        return 0

    follow = bool(args.follow or automation.get("follow"))
    poll_interval = float(args.poll_interval_seconds or automation.get("poll_interval_seconds") or 30)
    final_report: dict[str, Any] | None = None
    while True:
        final_report = run_once(args, environment_path, environment_doc)
        runner_out = repo_path(
            str((environment_doc.get("dynamic_peer_ip_watcher") or {}).get("output_root") or "build/dynamic-peer-ip-watcher/out")
        )
        write_json(runner_out / "runner-summary.json", final_report)
        if args.json:
            print(json.dumps(final_report, indent=2, sort_keys=True))
        elif final_report["status"] != "ok":
            print(f"Dynamic peer IP watcher runner: {final_report['status']}")
        if not follow:
            return 0 if final_report["status"] in {"ok", "disabled"} else 1
        time.sleep(max(poll_interval, 1.0))


if __name__ == "__main__":
    raise SystemExit(main())
