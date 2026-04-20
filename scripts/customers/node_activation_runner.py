#!/usr/bin/env python
"""Apply or roll back a node-local activation bundle."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _copy_path(source: Path, destination: Path) -> None:
    if source.is_dir():
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _run_command(command: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "success": completed.returncode == 0,
    }


def _bundle_root(request_path: Path) -> Path:
    return request_path.resolve().parent


def apply_request(request_path: Path) -> dict[str, Any]:
    request = load_json(request_path)
    bundle_root = _bundle_root(request_path)
    payload_root = (bundle_root / str(request.get("payload_root") or "payload")).resolve()
    target_root = Path(str(request["target_root"])).resolve()

    copied_paths: list[str] = []
    journal: list[dict[str, Any]] = []
    request_paths = [Path(path_str) for path_str in request.get("copy_paths") or []]

    for relative_path in request_paths:
        source_path = (payload_root / relative_path).resolve()
        destination_path = (target_root / relative_path).resolve()
        if not source_path.exists():
            raise RuntimeError(f"activation bundle is missing payload path: {source_path}")
        _copy_path(source_path, destination_path)
        copied_paths.append(str(destination_path))
        journal.append(
            {
                "recorded_at": utc_now(),
                "action": "copy_payload_path",
                "source": str(source_path),
                "destination": str(destination_path),
            }
        )

    apply_command = list(request.get("apply_command") or [])
    execute_apply = bool(request.get("execute_apply_command"))
    apply_result: dict[str, Any] | None = None
    if execute_apply and apply_command:
        apply_result = _run_command(apply_command, cwd=target_root)
        journal.append(
            {
                "recorded_at": utc_now(),
                "action": "execute_apply_command",
                **apply_result,
            }
        )
        if not apply_result["success"]:
            raise RuntimeError((apply_result["stderr"] or apply_result["stdout"]).strip() or "activation apply command failed")
    else:
        journal.append(
            {
                "recorded_at": utc_now(),
                "action": "skip_apply_command",
                "reason": "execute_apply_command=false",
            }
        )

    validated_paths: list[str] = []
    for relative_path in request.get("validate_paths") or []:
        target_path = (target_root / relative_path).resolve()
        if not target_path.exists():
            raise RuntimeError(f"activation validation missing path: {target_path}")
        validated_paths.append(str(target_path))
    journal.append(
        {
            "recorded_at": utc_now(),
            "action": "validate_target_paths",
            "validated_paths": validated_paths,
        }
    )

    journal_path = bundle_root / "activation-journal.json"
    result_path = bundle_root / "activation-result.json"
    result = {
        "schema_version": 1,
        "status": "applied",
        "generated_at": utc_now(),
        "request_path": str(request_path.resolve()),
        "bundle_root": str(bundle_root),
        "target_root": str(target_root),
        "copied_paths": copied_paths,
        "validated_paths": validated_paths,
        "apply_command_executed": execute_apply and bool(apply_command),
        "apply_command": apply_command,
        "apply_command_result": apply_result,
        "journal_path": str(journal_path),
        "result_path": str(result_path),
    }
    write_json(journal_path, {"schema_version": 1, "generated_at": utc_now(), "steps": journal})
    write_json(result_path, result)
    return result


def rollback_request(rollback_request_path: Path) -> dict[str, Any]:
    request = load_json(rollback_request_path)
    bundle_root = _bundle_root(rollback_request_path)
    target_root = Path(str(request["target_root"])).resolve()

    journal: list[dict[str, Any]] = []
    remove_command = list(request.get("remove_command") or [])
    execute_remove = bool(request.get("execute_remove_command"))
    remove_result: dict[str, Any] | None = None
    if execute_remove and remove_command:
        remove_result = _run_command(remove_command, cwd=target_root)
        journal.append(
            {
                "recorded_at": utc_now(),
                "action": "execute_remove_command",
                **remove_result,
            }
        )
    else:
        journal.append(
            {
                "recorded_at": utc_now(),
                "action": "skip_remove_command",
                "reason": "execute_remove_command=false",
            }
        )

    removed_paths: list[str] = []
    for relative_path in request.get("cleanup_paths") or []:
        target_path = (target_root / relative_path).resolve()
        if target_path.exists():
            if target_path.is_dir():
                shutil.rmtree(target_path)
            else:
                target_path.unlink()
            removed_paths.append(str(target_path))
    for relative_path in request.get("cleanup_files") or []:
        target_path = (target_root / relative_path).resolve()
        if target_path.exists():
            target_path.unlink()
            removed_paths.append(str(target_path))
    journal.append(
        {
            "recorded_at": utc_now(),
            "action": "cleanup_target_paths",
            "removed_paths": removed_paths,
        }
    )

    journal_path = bundle_root / "rollback-journal.json"
    result_path = bundle_root / "rollback-result.json"
    success = (remove_result is None or remove_result.get("success", False)) and True
    result = {
        "schema_version": 1,
        "status": "rolled_back" if success else "rollback_failed",
        "generated_at": utc_now(),
        "request_path": str(rollback_request_path.resolve()),
        "bundle_root": str(bundle_root),
        "target_root": str(target_root),
        "removed_paths": removed_paths,
        "remove_command_executed": execute_remove and bool(remove_command),
        "remove_command": remove_command,
        "remove_command_result": remove_result,
        "journal_path": str(journal_path),
        "result_path": str(result_path),
    }
    write_json(journal_path, {"schema_version": 1, "generated_at": utc_now(), "steps": journal})
    write_json(result_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply or roll back a node-local activation bundle.")
    parser.add_argument("--request", help="Path to activation-request.json")
    parser.add_argument("--rollback-request", help="Path to rollback-request.json")
    parser.add_argument("--json", action="store_true", help="Print the result as JSON")
    args = parser.parse_args()

    if bool(args.request) == bool(args.rollback_request):
        raise SystemExit("Specify exactly one of --request or --rollback-request")

    result = (
        apply_request(Path(args.request).resolve())
        if args.request
        else rollback_request(Path(args.rollback_request).resolve())
    )

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"applied", "rolled_back"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
