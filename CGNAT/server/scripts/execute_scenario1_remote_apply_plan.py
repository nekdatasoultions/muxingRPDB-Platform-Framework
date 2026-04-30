from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def _framework_src_root() -> Path:
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent.parent / "framework" / "src"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _host_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {host["role"]: host for host in manifest["hosts"]}


def _tool_paths() -> dict[str, str | None]:
    return {
        "ssh": shutil.which("ssh"),
        "scp": shutil.which("scp"),
    }


def _normalize_local_path(path_value: str) -> str:
    if path_value.startswith("/") and len(path_value) > 3 and path_value[2] == "/":
        drive_letter = path_value[1].upper()
        remainder = path_value[3:].replace("/", "\\")
        return f"{drive_letter}:\\{remainder}"
    return path_value


def _build_plan(remote_apply_dir: Path, manifest: dict[str, Any], execution_order: dict[str, Any]) -> dict[str, Any]:
    tools = _tool_paths()
    steps: list[dict[str, Any]] = []
    for step in execution_order["steps"]:
        planned_step = dict(step)
        if "script" in step:
            planned_step["absolute_script_path"] = str((remote_apply_dir / step["script"]).resolve())
        steps.append(planned_step)
    return {
        "plan_type": "scenario1_remote_apply_execution_plan",
        "service_id": manifest["service_id"],
        "ssh_available": bool(tools["ssh"]),
        "ssh_path": tools["ssh"],
        "scp_available": bool(tools["scp"]),
        "scp_path": tools["scp"],
        "steps": steps,
    }


def _render_readme(plan: dict[str, Any]) -> str:
    status = "READY" if plan["ssh_available"] and plan["scp_available"] else "NOT_READY"
    return "\n".join(
        [
            "# Scenario 1 Remote Apply Execution Plan",
            "",
            f"- Service ID: `{plan['service_id']}`",
            f"- Local ssh/scp available: `{status}`",
            "",
            "## Notes",
            "",
            "- `plan` mode writes execution artifacts only.",
            "- `apply` mode uses native local `ssh` and `scp` to execute the prepared remote plan.",
            "- This script does not invent remote commands; it executes the prepared remote stage/apply sequence.",
            "",
        ]
    )


def _ssh_target(host: dict[str, Any]) -> str:
    return f"{host['ssh_user']}@{host['target_host']}"


def _ssh_base_command(hosts: dict[str, dict[str, Any]], role: str) -> list[str]:
    host = hosts[role]
    command = [
        shutil.which("ssh") or "ssh",
        "-i",
        _normalize_local_path(host["private_key_path"]),
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    proxy_jump_role = host.get("proxy_jump_role")
    if proxy_jump_role:
        jump_host = hosts[proxy_jump_role]
        jump_key = _normalize_local_path(jump_host["private_key_path"])
        proxy_command = (
            f'ssh -i "{jump_key}" -o StrictHostKeyChecking=accept-new -W %h:%p {_ssh_target(jump_host)}'
        )
        command.extend(["-o", f"ProxyCommand={proxy_command}"])
    command.append(_ssh_target(host))
    return command


def _scp_base_command(hosts: dict[str, dict[str, Any]], role: str) -> list[str]:
    host = hosts[role]
    command = [
        shutil.which("scp") or "scp",
        "-i",
        _normalize_local_path(host["private_key_path"]),
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    proxy_jump_role = host.get("proxy_jump_role")
    if proxy_jump_role:
        jump_host = hosts[proxy_jump_role]
        jump_key = _normalize_local_path(jump_host["private_key_path"])
        proxy_command = (
            f'ssh -i "{jump_key}" -o StrictHostKeyChecking=accept-new -W %h:%p {_ssh_target(jump_host)}'
        )
        command.extend(["-o", f"ProxyCommand={proxy_command}"])
    return command


def _stage_bundle(hosts: dict[str, dict[str, Any]], role: str) -> dict[str, Any]:
    host = hosts[role]
    local_bundle_dir = Path(host["local_bundle_dir"]).resolve()
    if not local_bundle_dir.exists():
        raise RuntimeError(f"Local bundle directory does not exist for {role}: {local_bundle_dir}")

    stage_mkdir = _ssh_base_command(hosts, role) + [f"mkdir -p {host['remote_stage_dir']}"]
    stage_result = subprocess.run(stage_mkdir, capture_output=True, text=True, check=False)
    if stage_result.returncode != 0:
        raise RuntimeError(f"Remote stage mkdir failed for {role}: {stage_result.stderr}")

    local_files = [str(path) for path in sorted(local_bundle_dir.iterdir()) if path.is_file()]
    scp_command = _scp_base_command(hosts, role) + local_files + [f"{_ssh_target(host)}:{host['remote_stage_dir']}/"]
    scp_result = subprocess.run(scp_command, capture_output=True, text=True, check=False)
    if scp_result.returncode != 0:
        raise RuntimeError(f"Remote stage scp failed for {role}: {scp_result.stderr}")

    return {
        "mkdir_command": stage_mkdir,
        "mkdir_stdout": stage_result.stdout,
        "mkdir_stderr": stage_result.stderr,
        "scp_command": scp_command,
        "scp_stdout": scp_result.stdout,
        "scp_stderr": scp_result.stderr,
    }


def _apply_bundle(hosts: dict[str, dict[str, Any]], role: str) -> dict[str, Any]:
    host = hosts[role]
    apply_command = _ssh_base_command(hosts, role) + [
        (
            f"cd {host['remote_stage_dir']} && "
            "for f in *.sh *.env *.conf; do [ -f \"$f\" ] && sed -i 's/\\r$//' \"$f\"; done && "
            "chmod +x preflight.sh apply.sh *.sh && "
            "sudo bash ./preflight.sh && "
            "sudo bash ./apply.sh"
        )
    ]
    completed = subprocess.run(apply_command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"Remote apply failed for {role}: {completed.stderr}")
    return {
        "command": apply_command,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _execute_plan(plan: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    if not plan["ssh_available"] or not plan["scp_available"]:
        raise RuntimeError("Native ssh/scp are required for remote apply execution mode.")

    hosts = _host_map(manifest)
    results: list[dict[str, Any]] = []
    for step in plan["steps"]:
        role = step["role"]
        action = step["action"]
        if action == "run_validation_checks":
            results.append(
                {
                    "step_id": step["id"],
                    "role": role,
                    "action": action,
                    "status": "skipped_operator_step",
                }
            )
            continue

        try:
            if action == "stage_bundle":
                response = _stage_bundle(hosts, role)
            elif action == "apply_bundle":
                response = _apply_bundle(hosts, role)
            else:
                response = {}
            results.append(
                {
                    "step_id": step["id"],
                    "role": role,
                    "action": action,
                    "status": "completed",
                    "response": response,
                }
            )
        except RuntimeError as exc:
            results.append(
                {
                    "step_id": step["id"],
                    "role": role,
                    "action": action,
                    "status": "failed",
                    "error": str(exc),
                }
            )
            return {"results": results, "failed_step_id": step["id"]}

    return {"results": results}


def main() -> int:
    sys.path.insert(0, str(_framework_src_root()))

    from cgnat.bundle import dump_json, dump_text, ensure_path_within_cgnat

    parser = argparse.ArgumentParser(description="Plan or execute a prepared Scenario 1 remote apply plan.")
    parser.add_argument("remote_apply_dir", help="Path to the prepared remote apply plan directory.")
    parser.add_argument("output_dir", help="Directory to write execution artifacts.")
    parser.add_argument("--mode", choices=("plan", "apply"), default="plan", help="Execution mode.")
    parser.add_argument(
        "--execute-live",
        action="store_true",
        help="When used with --mode apply, execute the stage/apply steps. Without this flag, apply mode is refused.",
    )
    args = parser.parse_args()

    remote_apply_dir = Path(args.remote_apply_dir).resolve()
    output_dir = ensure_path_within_cgnat(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = _load_json(remote_apply_dir / "package-manifest.json")
    execution_order = _load_json(remote_apply_dir / "execution-order.json")
    plan = _build_plan(remote_apply_dir, manifest, execution_order)

    dump_json(output_dir / "execution-plan.json", plan)
    dump_json(
        output_dir / "execution-readiness.json",
        {
            "mode": args.mode,
            "ssh_available": plan["ssh_available"],
            "scp_available": plan["scp_available"],
            "live_execution_allowed": plan["ssh_available"] and plan["scp_available"] and args.execute_live,
        },
    )
    dump_text(output_dir / "README.md", _render_readme(plan))

    if args.mode == "apply":
        if not args.execute_live:
            print("Apply mode requires --execute-live; refusing to run remote stage/apply steps.", file=sys.stderr)
            return 1
        result = _execute_plan(plan, manifest)
        dump_json(output_dir / "execution-result.json", result)
        if result.get("failed_step_id"):
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
