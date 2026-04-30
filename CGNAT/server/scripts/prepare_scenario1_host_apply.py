from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any


def _framework_src_root() -> Path:
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent.parent / "framework" / "src"


def _load_json(path: Path) -> dict[str, Any] | list[Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_server_configs(config_dir: Path) -> dict[str, Any]:
    return {
        "head_end": _load_json(config_dir / "cgnat-head-end-config.json"),
        "isp_head_end": _load_json(config_dir / "cgnat-isp-head-end-config.json"),
        "customer_vpn_routers": _load_json(config_dir / "customer-vpn-routers-config.json"),
        "backend_validation": _load_json(config_dir / "backend-validation.json"),
        "runtime_inputs": _load_json(config_dir / "runtime-inputs.json"),
        "head_end_runtime_env": _load_text(config_dir / "cgnat-head-end-runtime.env"),
        "isp_head_end_runtime_env": _load_text(config_dir / "cgnat-isp-head-end-runtime.env"),
        "head_end_swanctl": _load_text(config_dir / "cgnat-head-end-swanctl.conf"),
        "isp_head_end_swanctl": _load_text(config_dir / "cgnat-isp-head-end-swanctl.conf"),
        "head_end_gre_script": _load_text(config_dir / "cgnat-head-end-gre.sh"),
        "head_end_forwarding_script": _load_text(config_dir / "cgnat-head-end-forwarding.sh"),
        "isp_head_end_forwarding_script": _load_text(config_dir / "cgnat-isp-head-end-forwarding.sh"),
        "head_end_route_script": _load_text(config_dir / "cgnat-head-end-routes.sh"),
        "validation_commands": _load_text(config_dir / "validation-commands.md"),
    }


def _role_dir_name(role: str) -> str:
    return role.replace("_", "-")


def _render_manifest(server_configs: dict[str, Any], materials_manifest_path: str | None = None) -> dict[str, Any]:
    runtime = server_configs["runtime_inputs"]
    hosts = [
        {"role": "cgnat_head_end", "bundle_dir": "hosts/cgnat-head-end"},
        {"role": "cgnat_isp_head_end", "bundle_dir": "hosts/cgnat-isp-head-end"},
    ]
    for router in runtime["customer_vpn_routers"]:
        hosts.append({"role": router["role"], "bundle_dir": f"hosts/{_role_dir_name(router['role'])}"})
    manifest = {
        "package_type": "scenario1_host_apply_package",
        "version": 1,
        "service_id": runtime["service_id"],
        "runtime_style": runtime["runtime_style"],
        "hosts": hosts,
    }
    if materials_manifest_path:
        manifest["materials_manifest_path"] = materials_manifest_path
    return manifest


def _render_apply_order(server_configs: dict[str, Any]) -> dict[str, Any]:
    steps = [
        {"id": 1, "role": "cgnat_head_end", "action": "run_preflight", "script": "preflight.sh"},
        {"id": 2, "role": "cgnat_head_end", "action": "stage_and_apply_ipsec_gre", "script": "apply.sh"},
        {"id": 3, "role": "cgnat_isp_head_end", "action": "run_preflight", "script": "preflight.sh"},
        {"id": 4, "role": "cgnat_isp_head_end", "action": "stage_and_apply_outer_tunnel", "script": "apply.sh"},
    ]
    step_id = 5
    for router in server_configs["runtime_inputs"]["customer_vpn_routers"]:
        steps.append({"id": step_id, "role": router["role"], "action": "run_preflight", "script": "preflight.sh"})
        step_id += 1
        steps.append({"id": step_id, "role": router["role"], "action": "stage_and_apply_inner_tunnel", "script": "apply.sh"})
        step_id += 1
    steps.append({"id": step_id, "role": "operator", "action": "run_validation_checks", "reference": "validation/validation-commands.md"})
    return {"steps": steps}


def _render_head_end_preflight() -> str:
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
            "source \"$SCRIPT_DIR/cgnat-head-end-runtime.env\"",
            "",
            "command -v swanctl >/dev/null",
            "command -v ip >/dev/null",
            "ip link show \"$CGNAT_HEAD_END_GRE_SOURCE_INTERFACE\" >/dev/null",
            "[[ -f \"$SCRIPT_DIR/$(basename \"$CGNAT_HEAD_END_SERVER_CERT_PATH\")\" ]]",
            "[[ -f \"$SCRIPT_DIR/$(basename \"$CGNAT_HEAD_END_SERVER_KEY_PATH\")\" ]]",
            "[[ -f \"$SCRIPT_DIR/$(basename \"$CGNAT_OUTER_CA_CERT_PATH\")\" ]]",
            "",
            "echo \"Preflight OK for CGNAT HEAD END\"",
            "",
        ]
    )


def _render_isp_head_end_preflight(server_configs: dict[str, Any]) -> str:
    customer_path = server_configs["isp_head_end"]["customer_service_path"]
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
            "source \"$SCRIPT_DIR/cgnat-isp-head-end-runtime.env\"",
            "",
            "command -v swanctl >/dev/null",
            "command -v ip >/dev/null",
            "[[ -f \"$SCRIPT_DIR/$(basename \"$CGNAT_ISP_HEAD_END_CLIENT_CERT_PATH\")\" ]]",
            "[[ -f \"$SCRIPT_DIR/$(basename \"$CGNAT_ISP_HEAD_END_CLIENT_KEY_PATH\")\" ]]",
            "[[ -f \"$SCRIPT_DIR/$(basename \"$CGNAT_OUTER_CA_CERT_PATH\")\" ]]",
            f"ip link show \"{customer_path['customer_facing_interface']}\" >/dev/null",
            "",
            "echo \"Preflight OK for CGNAT ISP HEAD END\"",
            "",
        ]
    )


def _render_customer_router_preflight(role: str) -> str:
    env_name = f"{role}-runtime.env"
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
            f"source \"$SCRIPT_DIR/{env_name}\"",
            "",
            "command -v swanctl >/dev/null",
            "command -v ip >/dev/null",
            "ip link show \"$CGNAT_CUSTOMER_INTERFACE\" >/dev/null",
            "[[ -f \"$SCRIPT_DIR/$(basename \"$CGNAT_INNER_VPN_SECRET_PATH\")\" ]]",
            "",
            f"echo \"Preflight OK for {role}\"",
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
            "source \"$SCRIPT_DIR/cgnat-head-end-runtime.env\"",
            "",
            "install -d /etc/swanctl/conf.d /etc/swanctl/x509 /etc/swanctl/private /etc/swanctl/x509ca",
            "install -m 0644 \"$SCRIPT_DIR/$(basename \"$CGNAT_HEAD_END_SERVER_CERT_PATH\")\" \"$CGNAT_HEAD_END_SERVER_CERT_PATH\"",
            "install -m 0600 \"$SCRIPT_DIR/$(basename \"$CGNAT_HEAD_END_SERVER_KEY_PATH\")\" \"$CGNAT_HEAD_END_SERVER_KEY_PATH\"",
            "install -m 0644 \"$SCRIPT_DIR/$(basename \"$CGNAT_OUTER_CA_CERT_PATH\")\" \"$CGNAT_OUTER_CA_CERT_PATH\"",
            "install -m 0644 \"$SCRIPT_DIR/cgnat-head-end-swanctl.conf\" \"/etc/swanctl/conf.d/${CGNAT_SERVICE_ID}-outer.conf\"",
            "swanctl --load-creds",
            "swanctl --load-conns",
            "bash \"$SCRIPT_DIR/cgnat-head-end-forwarding.sh\"",
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
            "source \"$SCRIPT_DIR/cgnat-isp-head-end-runtime.env\"",
            "",
            "install -d /etc/swanctl/conf.d /etc/swanctl/x509 /etc/swanctl/private /etc/swanctl/x509ca",
            "install -m 0644 \"$SCRIPT_DIR/$(basename \"$CGNAT_ISP_HEAD_END_CLIENT_CERT_PATH\")\" \"$CGNAT_ISP_HEAD_END_CLIENT_CERT_PATH\"",
            "install -m 0600 \"$SCRIPT_DIR/$(basename \"$CGNAT_ISP_HEAD_END_CLIENT_KEY_PATH\")\" \"$CGNAT_ISP_HEAD_END_CLIENT_KEY_PATH\"",
            "install -m 0644 \"$SCRIPT_DIR/$(basename \"$CGNAT_OUTER_CA_CERT_PATH\")\" \"$CGNAT_OUTER_CA_CERT_PATH\"",
            "install -m 0644 \"$SCRIPT_DIR/cgnat-isp-head-end-swanctl.conf\" \"/etc/swanctl/conf.d/${CGNAT_SERVICE_ID}-outer.conf\"",
            "swanctl --load-creds",
            "swanctl --load-conns",
            "bash \"$SCRIPT_DIR/cgnat-isp-head-end-forwarding.sh\"",
            "",
        ]
    )


def _render_customer_router_apply(role: str) -> str:
    env_name = f"{role}-runtime.env"
    conf_name = f"{role}-inner-swanctl.conf"
    loop_name = f"{role}-loopback.sh"
    route_name = f"{role}-routes.sh"
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
            f"source \"$SCRIPT_DIR/{env_name}\"",
            "",
            "install -d /etc/swanctl/conf.d /etc/swanctl/secrets",
            "install -m 0600 \"$SCRIPT_DIR/$(basename \"$CGNAT_INNER_VPN_SECRET_PATH\")\" \"$CGNAT_INNER_VPN_SECRET_PATH\"",
            f"install -m 0644 \"$SCRIPT_DIR/{conf_name}\" \"/etc/swanctl/conf.d/${{CGNAT_INNER_CONNECTION_NAME}}.conf\"",
            f"bash \"$SCRIPT_DIR/{loop_name}\"",
            f"bash \"$SCRIPT_DIR/{route_name}\"",
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
            "5. Disable forwarding if the host should no longer carry the Scenario 1 path.",
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
            "3. Disable forwarding if this host should no longer transit customer-router traffic.",
            "4. Re-run transit validation to confirm the outer tunnel path is gone.",
            "",
        ]
    )


def _render_customer_router_rollback(role: str) -> str:
    return "\n".join(
        [
            f"# {role} Rollback Notes",
            "",
            "1. Remove or disable the staged swanctl inner-tunnel config.",
            "2. Reload strongSwan connections if needed.",
            "3. Remove the loopback identity if it was demo-only.",
            "4. Restore the pre-demo default route if needed.",
            "",
        ]
    )


def _render_top_level_readme(manifest: dict[str, Any]) -> str:
    lines = [
        "# Scenario 1 Host Apply Package",
        "",
        f"- Service ID: `{manifest['service_id']}`",
        "- This package contains per-host staged artifacts only.",
        "- It does not connect to hosts or run commands remotely.",
        "",
        "## Layout",
        "",
    ]
    for host in manifest["hosts"]:
        lines.append(f"- `{host['bundle_dir']}/`")
    lines.extend(["- `validation/`", "- `apply-order.json`", ""])
    return "\n".join(lines)


def _load_materials_manifest(path: Path) -> dict[str, Any]:
    return _load_json(path)


def _copy_material(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _inner_secret_name(runtime: dict[str, Any]) -> str:
    return Path(runtime["secret_path"]).name


def _stage_materials(
    host_dirs: dict[str, Path],
    server_configs: dict[str, Any],
    materials_manifest: dict[str, Any],
) -> None:
    runtime = server_configs["runtime_inputs"]
    certs = materials_manifest["certificate_material"]
    inner_materials = list(materials_manifest.get("inner_vpn_materials") or [])
    inner_by_role = {entry["router_role"]: entry for entry in inner_materials}

    head_dir = host_dirs["cgnat_head_end"]
    isp_dir = host_dirs["cgnat_isp_head_end"]
    _copy_material(
        Path(certs["head_end_server"]["certificate_path"]),
        head_dir / Path(runtime["head_end"]["certificate_material"]["head_end_server"]["certificate_path"]).name,
    )
    _copy_material(
        Path(certs["head_end_server"]["private_key_path"]),
        head_dir / Path(runtime["head_end"]["certificate_material"]["head_end_server"]["private_key_path"]).name,
    )
    _copy_material(
        Path(certs["outer_tunnel_ca"]["certificate_path"]),
        head_dir / Path(runtime["head_end"]["certificate_material"]["outer_tunnel_ca"]["certificate_path"]).name,
    )

    _copy_material(
        Path(certs["isp_head_end_client"]["certificate_path"]),
        isp_dir / Path(runtime["isp_head_end"]["certificate_material"]["isp_head_end_client"]["certificate_path"]).name,
    )
    _copy_material(
        Path(certs["isp_head_end_client"]["private_key_path"]),
        isp_dir / Path(runtime["isp_head_end"]["certificate_material"]["isp_head_end_client"]["private_key_path"]).name,
    )
    _copy_material(
        Path(certs["outer_tunnel_ca"]["certificate_path"]),
        isp_dir / Path(runtime["isp_head_end"]["certificate_material"]["outer_tunnel_ca"]["certificate_path"]).name,
    )

    for router_runtime in runtime["customer_vpn_routers"]:
        role = router_runtime["role"]
        router_dir = host_dirs[role]
        material = inner_by_role.get(role)
        if material is None:
            raise ValueError(f"materials manifest is missing inner_vpn_materials entry for router role `{role}`")
        _copy_material(Path(material["secret_path"]), router_dir / _inner_secret_name(router_runtime))
        conf_path = router_dir / f"{role}-inner-swanctl.conf"
        psk_value = Path(material["secret_path"]).read_text(encoding="utf-8").strip()
        rendered_conf = conf_path.read_text(encoding="utf-8").replace("__CGNAT_INNER_PSK__", psk_value)
        conf_path.write_text(rendered_conf, encoding="utf-8")


def main() -> int:
    sys.path.insert(0, str(_framework_src_root()))

    from cgnat.bundle import dump_json, dump_text, ensure_path_within_cgnat

    parser = argparse.ArgumentParser(description="Prepare per-host Scenario 1 apply bundles from rendered server config artifacts.")
    parser.add_argument("server_config_dir", help="Path to the rendered Scenario 1 server-config directory.")
    parser.add_argument("output_dir", help="Directory to write the host apply package.")
    parser.add_argument(
        "--materials-manifest-json",
        help="Optional path to the materialized Scenario 1 demo materials manifest.",
    )
    args = parser.parse_args()

    server_config_dir = Path(args.server_config_dir).resolve()
    output_dir = ensure_path_within_cgnat(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    server_configs = _load_server_configs(server_config_dir)
    materials_manifest = None
    if args.materials_manifest_json:
        materials_manifest = _load_materials_manifest(Path(args.materials_manifest_json).resolve())

    manifest = _render_manifest(
        server_configs,
        materials_manifest_path=str(Path(args.materials_manifest_json).resolve()) if args.materials_manifest_json else None,
    )

    host_dirs = {
        "cgnat_head_end": output_dir / "hosts" / "cgnat-head-end",
        "cgnat_isp_head_end": output_dir / "hosts" / "cgnat-isp-head-end",
    }
    for router in server_configs["runtime_inputs"]["customer_vpn_routers"]:
        host_dirs[router["role"]] = output_dir / "hosts" / _role_dir_name(router["role"])
    validation_dir = output_dir / "validation"

    dump_json(output_dir / "package-manifest.json", manifest)
    dump_json(output_dir / "apply-order.json", _render_apply_order(server_configs))
    dump_text(output_dir / "README.md", _render_top_level_readme(manifest))

    head_dir = host_dirs["cgnat_head_end"]
    dump_text(head_dir / "cgnat-head-end-runtime.env", server_configs["head_end_runtime_env"])
    dump_text(head_dir / "cgnat-head-end-swanctl.conf", server_configs["head_end_swanctl"])
    dump_text(head_dir / "cgnat-head-end-gre.sh", server_configs["head_end_gre_script"])
    dump_text(head_dir / "cgnat-head-end-forwarding.sh", server_configs["head_end_forwarding_script"])
    dump_text(head_dir / "cgnat-head-end-routes.sh", server_configs["head_end_route_script"])
    dump_text(head_dir / "preflight.sh", _render_head_end_preflight())
    dump_text(head_dir / "apply.sh", _render_head_end_apply())
    dump_text(head_dir / "rollback-notes.md", _render_head_end_rollback())

    isp_dir = host_dirs["cgnat_isp_head_end"]
    dump_text(isp_dir / "cgnat-isp-head-end-runtime.env", server_configs["isp_head_end_runtime_env"])
    dump_text(isp_dir / "cgnat-isp-head-end-swanctl.conf", server_configs["isp_head_end_swanctl"])
    dump_text(isp_dir / "cgnat-isp-head-end-forwarding.sh", server_configs["isp_head_end_forwarding_script"])
    dump_text(isp_dir / "preflight.sh", _render_isp_head_end_preflight(server_configs))
    dump_text(isp_dir / "apply.sh", _render_isp_head_end_apply())
    dump_text(isp_dir / "rollback-notes.md", _render_isp_head_end_rollback())

    for router_runtime in server_configs["runtime_inputs"]["customer_vpn_routers"]:
        role = router_runtime["role"]
        router_dir = host_dirs[role]
        dump_text(router_dir / f"{role}-runtime.env", _load_text(server_config_dir / f"{role}-runtime.env"))
        dump_text(router_dir / f"{role}-inner-swanctl.conf", _load_text(server_config_dir / f"{role}-inner-swanctl.conf"))
        dump_text(router_dir / f"{role}-loopback.sh", _load_text(server_config_dir / f"{role}-loopback.sh"))
        dump_text(router_dir / f"{role}-routes.sh", _load_text(server_config_dir / f"{role}-routes.sh"))
        dump_text(router_dir / "preflight.sh", _render_customer_router_preflight(role))
        dump_text(router_dir / "apply.sh", _render_customer_router_apply(role))
        dump_text(router_dir / "rollback-notes.md", _render_customer_router_rollback(role))

    if materials_manifest is not None:
        _stage_materials(host_dirs, server_configs, materials_manifest)

    dump_json(validation_dir / "backend-validation.json", server_configs["backend_validation"])
    dump_text(validation_dir / "validation-commands.md", server_configs["validation_commands"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
