from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any


def _framework_src_root() -> Path:
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent.parent / "framework" / "src"


def _load_json(path: Path) -> dict[str, Any] | list[Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _host_bundle_map(host_apply_dir: Path, package_manifest: dict[str, Any]) -> dict[str, Path]:
    return {
        host["role"]: host_apply_dir / host["bundle_dir"]
        for host in package_manifest["hosts"]
    }


def _validate_access(access: dict[str, Any], required_roles: list[str]) -> None:
    required_fields = ("ssh_user", "target_host", "private_key_path", "remote_stage_dir")
    missing: list[str] = []
    for role in required_roles:
        role_data = access.get(role)
        if not isinstance(role_data, dict):
            missing.append(role)
            continue
        for field_name in required_fields:
            if not role_data.get(field_name):
                missing.append(f"{role}.{field_name}")
        proxy_jump_role = role_data.get("proxy_jump_role")
        if proxy_jump_role and proxy_jump_role not in access:
            missing.append(f"{role}.proxy_jump_role->{proxy_jump_role}")
    if missing:
        raise ValueError(f"Host access config is missing required entries: {', '.join(missing)}")


def _render_manifest(package_manifest: dict[str, Any], access: dict[str, Any]) -> dict[str, Any]:
    hosts = []
    for host in package_manifest["hosts"]:
        role = host["role"]
        host_access = access[role]
        payload = {
            "role": role,
            "ssh_user": host_access["ssh_user"],
            "target_host": host_access["target_host"],
            "remote_stage_dir": host_access["remote_stage_dir"],
        }
        if host_access.get("proxy_jump_role"):
            payload["proxy_jump_role"] = host_access["proxy_jump_role"]
        hosts.append(payload)
    return {
        "package_type": "scenario1_remote_apply_plan",
        "version": 1,
        "service_id": package_manifest["service_id"],
        "hosts": hosts,
    }


def _ssh_opts(role: str, access: dict[str, Any]) -> str:
    role_access = access[role]
    base = f"-i {shlex.quote(role_access['private_key_path'])} -o StrictHostKeyChecking=accept-new"
    proxy_jump_role = role_access.get("proxy_jump_role")
    if proxy_jump_role:
        jump_access = access[proxy_jump_role]
        proxy_target = f"{jump_access['ssh_user']}@{jump_access['target_host']}"
        base += f" -o ProxyJump={shlex.quote(proxy_target)}"
    return base


def _render_stage_commands(role: str, bundle_dir: Path, access: dict[str, Any]) -> str:
    role_access = access[role]
    ssh_target = f"{role_access['ssh_user']}@{role_access['target_host']}"
    remote_dir = shlex.quote(role_access["remote_stage_dir"])
    ssh_opts = _ssh_opts(role, access)
    local_files = " ".join(shlex.quote(path.name) for path in sorted(bundle_dir.iterdir()) if path.is_file())
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
            f"ssh {ssh_opts} {shlex.quote(ssh_target)} \"mkdir -p {remote_dir}\"",
            f"(cd \"$SCRIPT_DIR\" && scp {ssh_opts} {local_files} {shlex.quote(ssh_target)}:{remote_dir}/)",
            "",
        ]
    )


def _render_apply_commands(role: str, access: dict[str, Any]) -> str:
    role_access = access[role]
    ssh_target = f"{role_access['ssh_user']}@{role_access['target_host']}"
    ssh_opts = _ssh_opts(role, access)
    remote_dir = shlex.quote(role_access["remote_stage_dir"])
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            f"ssh {ssh_opts} {shlex.quote(ssh_target)} <<'EOF'",
            f"cd {remote_dir}",
            "chmod +x preflight.sh apply.sh *.sh",
            "./preflight.sh",
            "./apply.sh",
            "EOF",
            "",
        ]
    )


def _render_readme(manifest: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Scenario 1 Remote Apply Plan",
            "",
            f"- Service ID: `{manifest['service_id']}`",
            "- This plan generates remote stage/apply commands only.",
            "- It does not open SSH sessions or execute remote changes by itself.",
            "",
            "## Outputs",
            "",
            "- `package-manifest.json`",
            "- `commands/<role>-stage.sh`",
            "- `commands/<role>-apply.sh`",
            "",
        ]
    )


def _render_execution_order(package_manifest: dict[str, Any]) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    step_id = 1
    for host in package_manifest["hosts"]:
        role = host["role"]
        steps.append({"id": step_id, "role": role, "action": "stage_bundle", "script": f"commands/{role}-stage.sh"})
        step_id += 1
        steps.append({"id": step_id, "role": role, "action": "apply_bundle", "script": f"commands/{role}-apply.sh"})
        step_id += 1
    steps.append({"id": step_id, "role": "operator", "action": "run_validation_checks", "reference": "../host-apply/validation/validation-commands.md"})
    return {"steps": steps}


def main() -> int:
    sys.path.insert(0, str(_framework_src_root()))

    from cgnat.bundle import dump_json, dump_text, ensure_path_within_cgnat

    parser = argparse.ArgumentParser(description="Prepare a no-execution remote apply command plan from a Scenario 1 host-apply package.")
    parser.add_argument("host_apply_dir", help="Path to the Scenario 1 host-apply package directory.")
    parser.add_argument("host_access_json", help="Path to the host access JSON file.")
    parser.add_argument("output_dir", help="Directory to write the remote apply command plan.")
    args = parser.parse_args()

    host_apply_dir = Path(args.host_apply_dir).resolve()
    host_access_path = Path(args.host_access_json).resolve()
    output_dir = ensure_path_within_cgnat(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    package_manifest = _load_json(host_apply_dir / "package-manifest.json")
    access = _load_json(host_access_path)
    required_roles = [host["role"] for host in package_manifest["hosts"]]
    _validate_access(access, required_roles)
    manifest = _render_manifest(package_manifest, access)

    dump_json(output_dir / "package-manifest.json", manifest)
    dump_json(output_dir / "execution-order.json", _render_execution_order(package_manifest))
    dump_text(output_dir / "README.md", _render_readme(manifest))

    commands_dir = output_dir / "commands"
    bundle_map = _host_bundle_map(host_apply_dir, package_manifest)
    for role in required_roles:
        bundle_dir = bundle_map[role]
        dump_text(commands_dir / f"{role}-stage.sh", _render_stage_commands(role, bundle_dir, access))
        dump_text(commands_dir / f"{role}-apply.sh", _render_apply_commands(role, access))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
