from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _framework_src_root() -> Path:
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent.parent / "framework" / "src"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_server_configs(config_dir: Path) -> dict[str, Any]:
    return {
        "head_end": _load_json(config_dir / "cgnat-head-end-config.json"),
        "isp_head_end": _load_json(config_dir / "cgnat-isp-head-end-config.json"),
        "backend_validation": _load_json(config_dir / "backend-validation.json"),
        "runtime_inputs": _load_json(config_dir / "runtime-inputs.json"),
        "runtime_env": _load_text(config_dir / "scenario1-runtime.env"),
        "head_end_swanctl": _load_text(config_dir / "cgnat-head-end-swanctl.conf"),
        "isp_head_end_swanctl": _load_text(config_dir / "cgnat-isp-head-end-swanctl.conf"),
        "head_end_gre_script": _load_text(config_dir / "cgnat-head-end-gre.sh"),
        "head_end_route_script": _load_text(config_dir / "cgnat-head-end-routes.sh"),
        "validation_commands": _load_text(config_dir / "validation-commands.md"),
    }


def _render_manifest(server_configs: dict[str, Any]) -> dict[str, Any]:
    runtime = server_configs["runtime_inputs"]
    return {
        "package_type": "scenario1_host_apply_package",
        "version": 1,
        "service_id": runtime["service_id"],
        "runtime_style": runtime["runtime_style"],
        "hosts": [
            {
                "role": "cgnat_head_end",
                "bundle_dir": "hosts/cgnat-head-end",
            },
            {
                "role": "cgnat_isp_head_end",
                "bundle_dir": "hosts/cgnat-isp-head-end",
            },
        ],
    }


def _render_apply_order() -> dict[str, Any]:
    return {
        "steps": [
            {
                "id": 1,
                "role": "cgnat_head_end",
                "action": "run_preflight",
                "script": "preflight.sh",
            },
            {
                "id": 2,
                "role": "cgnat_head_end",
                "action": "stage_and_apply_ipsec",
                "script": "apply.sh",
            },
            {
                "id": 3,
                "role": "cgnat_head_end",
                "action": "configure_gre_and_route",
                "script": "apply.sh",
            },
            {
                "id": 4,
                "role": "cgnat_isp_head_end",
                "action": "run_preflight",
                "script": "preflight.sh",
            },
            {
                "id": 5,
                "role": "cgnat_isp_head_end",
                "action": "stage_and_apply_ipsec",
                "script": "apply.sh",
            },
            {
                "id": 6,
                "role": "operator",
                "action": "run_validation_checks",
                "reference": "validation/validation-commands.md",
            },
        ]
    }


def _render_head_end_preflight(server_configs: dict[str, Any]) -> str:
    runtime = server_configs["runtime_inputs"]
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
            "source \"$SCRIPT_DIR/scenario1-runtime.env\"",
            "",
            "command -v swanctl >/dev/null",
            "command -v ip >/dev/null",
            "ip link show \"$CGNAT_HEAD_END_GRE_SOURCE_INTERFACE\" >/dev/null",
            "[[ -f \"$CGNAT_HEAD_END_SERVER_CERT_PATH\" ]]",
            "[[ -f \"$CGNAT_HEAD_END_SERVER_KEY_PATH\" ]]",
            "[[ -f \"$CGNAT_OUTER_CA_CERT_PATH\" ]]",
            "",
            f"echo \"Preflight OK for {runtime['service_id']} on CGNAT HEAD END\"",
            "",
        ]
    )


def _render_isp_head_end_preflight(server_configs: dict[str, Any]) -> str:
    runtime = server_configs["runtime_inputs"]
    customer_path = server_configs["isp_head_end"]["customer_service_path"]
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
            "source \"$SCRIPT_DIR/scenario1-runtime.env\"",
            "",
            "command -v swanctl >/dev/null",
            "command -v ip >/dev/null",
            "[[ -f \"$CGNAT_ISP_HEAD_END_CLIENT_CERT_PATH\" ]]",
            "[[ -f \"$CGNAT_ISP_HEAD_END_CLIENT_KEY_PATH\" ]]",
            "[[ -f \"$CGNAT_OUTER_CA_CERT_PATH\" ]]",
            f"ip link show \"{customer_path['customer_facing_interface']}\" >/dev/null",
            "",
            f"echo \"Preflight OK for {runtime['service_id']} on CGNAT ISP HEAD END\"",
            "",
        ]
    )


def _render_head_end_apply() -> str:
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
            "source \"$SCRIPT_DIR/scenario1-runtime.env\"",
            "",
            "install -d /etc/swanctl/conf.d",
            "install -m 0644 \"$SCRIPT_DIR/cgnat-head-end-swanctl.conf\" \"/etc/swanctl/conf.d/${CGNAT_SERVICE_ID}-outer.conf\"",
            "swanctl --load-creds",
            "swanctl --load-conns",
            "bash \"$SCRIPT_DIR/cgnat-head-end-gre.sh\"",
            "bash \"$SCRIPT_DIR/cgnat-head-end-routes.sh\"",
            "",
        ]
    )


def _render_isp_head_end_apply() -> str:
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
            "source \"$SCRIPT_DIR/scenario1-runtime.env\"",
            "",
            "install -d /etc/swanctl/conf.d",
            "install -m 0644 \"$SCRIPT_DIR/cgnat-isp-head-end-swanctl.conf\" \"/etc/swanctl/conf.d/${CGNAT_SERVICE_ID}-outer.conf\"",
            "swanctl --load-creds",
            "swanctl --load-conns",
            "",
        ]
    )


def _render_head_end_rollback() -> str:
    return "\n".join(
        [
            "# CGNAT HEAD END Rollback Notes",
            "",
            "1. Remove or disable the staged swanctl connection file.",
            "2. Reload strongSwan connections and credentials if needed.",
            "3. Remove the GRE interface created by `cgnat-head-end-gre.sh`.",
            "4. Remove the route installed by `cgnat-head-end-routes.sh`.",
            "5. Re-run validation captures to confirm no traffic still enters the Scenario 1 path.",
            "",
        ]
    )


def _render_isp_head_end_rollback() -> str:
    return "\n".join(
        [
            "# CGNAT ISP HEAD END Rollback Notes",
            "",
            "1. Remove or disable the staged swanctl connection file.",
            "2. Reload strongSwan connections and credentials if needed.",
            "3. Confirm the customer-facing interface path returns to its pre-test state.",
            "4. Re-run customer-side validation to confirm the outer tunnel is no longer active.",
            "",
        ]
    )


def _render_top_level_readme(manifest: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Scenario 1 Host Apply Package",
            "",
            f"- Service ID: `{manifest['service_id']}`",
            "- This package contains per-host staged artifacts only.",
            "- It does not connect to hosts or run commands remotely.",
            "",
            "## Layout",
            "",
            "- `hosts/cgnat-head-end/`",
            "- `hosts/cgnat-isp-head-end/`",
            "- `validation/`",
            "- `apply-order.json`",
            "",
        ]
    )


def main() -> int:
    sys.path.insert(0, str(_framework_src_root()))

    from cgnat.bundle import dump_json, dump_text, ensure_path_within_cgnat

    parser = argparse.ArgumentParser(description="Prepare per-host Scenario 1 apply bundles from rendered server config artifacts.")
    parser.add_argument("server_config_dir", help="Path to the rendered Scenario 1 server-config directory.")
    parser.add_argument("output_dir", help="Directory to write the host apply package.")
    args = parser.parse_args()

    server_config_dir = Path(args.server_config_dir).resolve()
    output_dir = ensure_path_within_cgnat(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    server_configs = _load_server_configs(server_config_dir)
    manifest = _render_manifest(server_configs)

    head_dir = output_dir / "hosts" / "cgnat-head-end"
    isp_dir = output_dir / "hosts" / "cgnat-isp-head-end"
    validation_dir = output_dir / "validation"

    dump_json(output_dir / "package-manifest.json", manifest)
    dump_json(output_dir / "apply-order.json", _render_apply_order())
    dump_text(output_dir / "README.md", _render_top_level_readme(manifest))

    dump_text(head_dir / "scenario1-runtime.env", server_configs["runtime_env"])
    dump_text(head_dir / "cgnat-head-end-swanctl.conf", server_configs["head_end_swanctl"])
    dump_text(head_dir / "cgnat-head-end-gre.sh", server_configs["head_end_gre_script"])
    dump_text(head_dir / "cgnat-head-end-routes.sh", server_configs["head_end_route_script"])
    dump_text(head_dir / "preflight.sh", _render_head_end_preflight(server_configs))
    dump_text(head_dir / "apply.sh", _render_head_end_apply())
    dump_text(head_dir / "rollback-notes.md", _render_head_end_rollback())

    dump_text(isp_dir / "scenario1-runtime.env", server_configs["runtime_env"])
    dump_text(isp_dir / "cgnat-isp-head-end-swanctl.conf", server_configs["isp_head_end_swanctl"])
    dump_text(isp_dir / "preflight.sh", _render_isp_head_end_preflight(server_configs))
    dump_text(isp_dir / "apply.sh", _render_isp_head_end_apply())
    dump_text(isp_dir / "rollback-notes.md", _render_isp_head_end_rollback())

    dump_json(validation_dir / "backend-validation.json", server_configs["backend_validation"])
    dump_text(validation_dir / "validation-commands.md", server_configs["validation_commands"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
