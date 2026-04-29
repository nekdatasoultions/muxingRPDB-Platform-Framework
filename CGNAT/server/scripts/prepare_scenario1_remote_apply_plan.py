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


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _role_bundle_dir(host_apply_dir: Path, role: str) -> Path:
    mapping = {
        "cgnat_head_end": host_apply_dir / "hosts" / "cgnat-head-end",
        "cgnat_isp_head_end": host_apply_dir / "hosts" / "cgnat-isp-head-end",
    }
    return mapping[role]


def _validate_access(access: dict[str, Any]) -> None:
    required_roles = ("cgnat_head_end", "cgnat_isp_head_end")
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
    if missing:
        raise ValueError(f"Host access config is missing required entries: {', '.join(missing)}")


def _render_manifest(package_manifest: dict[str, Any], access: dict[str, Any]) -> dict[str, Any]:
    return {
        "package_type": "scenario1_remote_apply_plan",
        "version": 1,
        "service_id": package_manifest["service_id"],
        "hosts": [
            {
                "role": role,
                "ssh_user": access[role]["ssh_user"],
                "target_host": access[role]["target_host"],
                "remote_stage_dir": access[role]["remote_stage_dir"],
            }
            for role in ("cgnat_head_end", "cgnat_isp_head_end")
        ],
    }


def _render_stage_commands(role: str, bundle_dir: Path, access: dict[str, Any]) -> str:
    role_access = access[role]
    ssh_target = f"{role_access['ssh_user']}@{role_access['target_host']}"
    key_path = shlex.quote(role_access["private_key_path"])
    remote_dir = shlex.quote(role_access["remote_stage_dir"])
    local_files = " ".join(shlex.quote(path.name) for path in sorted(bundle_dir.iterdir()) if path.is_file())
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
            f"ssh -i {key_path} -o StrictHostKeyChecking=accept-new {shlex.quote(ssh_target)} \"mkdir -p {remote_dir}\"",
            f"(cd \"$SCRIPT_DIR\" && scp -i {key_path} -o StrictHostKeyChecking=accept-new {local_files} {shlex.quote(ssh_target)}:{remote_dir}/)",
            "",
        ]
    )


def _render_apply_commands(role: str, access: dict[str, Any]) -> str:
    role_access = access[role]
    ssh_target = f"{role_access['ssh_user']}@{role_access['target_host']}"
    key_path = shlex.quote(role_access["private_key_path"])
    remote_dir = shlex.quote(role_access["remote_stage_dir"])
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            f"ssh -i {key_path} -o StrictHostKeyChecking=accept-new {shlex.quote(ssh_target)} <<'EOF'",
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


def _render_execution_order() -> dict[str, Any]:
    return {
        "steps": [
            {
                "id": 1,
                "role": "cgnat_head_end",
                "action": "stage_bundle",
                "script": "commands/cgnat_head_end-stage.sh",
            },
            {
                "id": 2,
                "role": "cgnat_head_end",
                "action": "apply_bundle",
                "script": "commands/cgnat_head_end-apply.sh",
            },
            {
                "id": 3,
                "role": "cgnat_isp_head_end",
                "action": "stage_bundle",
                "script": "commands/cgnat_isp_head_end-stage.sh",
            },
            {
                "id": 4,
                "role": "cgnat_isp_head_end",
                "action": "apply_bundle",
                "script": "commands/cgnat_isp_head_end-apply.sh",
            },
            {
                "id": 5,
                "role": "operator",
                "action": "run_validation_checks",
                "reference": "../host-apply/validation/validation-commands.md",
            },
        ]
    }


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
    _validate_access(access)
    manifest = _render_manifest(package_manifest, access)

    dump_json(output_dir / "package-manifest.json", manifest)
    dump_json(output_dir / "execution-order.json", _render_execution_order())
    dump_text(output_dir / "README.md", _render_readme(manifest))

    commands_dir = output_dir / "commands"
    for role in ("cgnat_head_end", "cgnat_isp_head_end"):
        bundle_dir = _role_bundle_dir(host_apply_dir, role)
        dump_text(commands_dir / f"{role}-stage.sh", _render_stage_commands(role, bundle_dir, access))
        dump_text(commands_dir / f"{role}-apply.sh", _render_apply_commands(role, access))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
