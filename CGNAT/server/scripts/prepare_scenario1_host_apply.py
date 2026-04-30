from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any


HEAD_END_PUBLIC_IP_PLACEHOLDER = "__CGNAT_HEAD_END_PUBLIC_IP__"


def _framework_src_root() -> Path:
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent.parent / "framework" / "src"


def _load_json(path: Path) -> dict[str, Any] | list[Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_server_configs(config_dir: Path) -> dict[str, Any]:
    runtime_inputs = _load_json(config_dir / "runtime-inputs.json")
    customer_router_roles = [router["role"] for router in runtime_inputs["customer_vpn_routers"]]
    return {
        "head_end": _load_json(config_dir / "cgnat-head-end-config.json"),
        "isp_head_end": _load_json(config_dir / "cgnat-isp-head-end-config.json"),
        "customer_vpn_routers": _load_json(config_dir / "customer-vpn-routers-config.json"),
        "backend_validation": _load_json(config_dir / "backend-validation.json"),
        "runtime_inputs": runtime_inputs,
        "head_end_runtime_env": _load_text(config_dir / "cgnat-head-end-runtime.env"),
        "isp_head_end_runtime_env": _load_text(config_dir / "cgnat-isp-head-end-runtime.env"),
        "head_end_swanctl_conf": _load_text(config_dir / "cgnat-head-end-swanctl.conf"),
        "isp_head_end_ipsec_conf": _load_text(config_dir / "cgnat-isp-head-end-swanctl.conf"),
        "head_end_xfrm_script": _load_text(config_dir / "cgnat-head-end-xfrm.sh"),
        "head_end_gre_script": _load_text(config_dir / "cgnat-head-end-gre.sh"),
        "head_end_forwarding_script": _load_text(config_dir / "cgnat-head-end-forwarding.sh"),
        "isp_head_end_forwarding_script": _load_text(config_dir / "cgnat-isp-head-end-forwarding.sh"),
        "head_end_route_script": _load_text(config_dir / "cgnat-head-end-routes.sh"),
        "validation_commands": _load_text(config_dir / "validation-commands.md"),
        "customer_router_runtime_envs": {
            role: _load_text(config_dir / f"{role}-runtime.env")
            for role in customer_router_roles
        },
        "customer_router_outer_confs": {
            role: _load_text(config_dir / f"{role}-outer-swanctl.conf")
            for role in customer_router_roles
        },
        "customer_router_inner_confs": {
            role: _load_text(config_dir / f"{role}-inner-swanctl.conf")
            for role in customer_router_roles
        },
        "customer_router_xfrm_scripts": {
            role: _load_text(config_dir / f"{role}-xfrm.sh")
            for role in customer_router_roles
        },
        "customer_router_loopback_scripts": {
            role: _load_text(config_dir / f"{role}-loopback.sh")
            for role in customer_router_roles
        },
        "customer_router_route_scripts": {
            role: _load_text(config_dir / f"{role}-routes.sh")
            for role in customer_router_roles
        },
    }


def _load_host_access(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return _load_json(path)


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
        {"id": 2, "role": "cgnat_head_end", "action": "stage_and_apply_strongswan_outer_transport", "script": "apply.sh"},
        {"id": 3, "role": "cgnat_isp_head_end", "action": "run_preflight", "script": "preflight.sh"},
        {"id": 4, "role": "cgnat_isp_head_end", "action": "stage_and_apply_transit_only", "script": "apply.sh"},
    ]
    step_id = 5
    for router in server_configs["runtime_inputs"]["customer_vpn_routers"]:
        steps.append({"id": step_id, "role": router["role"], "action": "run_preflight", "script": "preflight.sh"})
        step_id += 1
        steps.append({"id": step_id, "role": router["role"], "action": "stage_and_apply_outer_and_inner_strongswan_tunnels", "script": "apply.sh"})
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
            "command -v ip >/dev/null",
            "command -v openssl >/dev/null",
            "if ! command -v swanctl >/dev/null; then",
            "  command -v dnf >/dev/null || command -v yum >/dev/null",
            "fi",
            "ip link show \"$CGNAT_HEAD_END_OUTER_INTERFACE\" >/dev/null",
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
            "command -v ip >/dev/null",
            "command -v sysctl >/dev/null",
            f"ip link show \"{customer_path['uplink_interface']}\" >/dev/null",
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
            "command -v ip >/dev/null",
            "if ! command -v swanctl >/dev/null; then",
            "  command -v dnf >/dev/null || command -v yum >/dev/null",
            "fi",
            "ip link show \"$CGNAT_CUSTOMER_INTERFACE\" >/dev/null",
            "[[ \"$CGNAT_OUTER_REMOTE_PUBLIC_IP\" != \"" + HEAD_END_PUBLIC_IP_PLACEHOLDER + "\" ]]",
            "[[ -f \"$SCRIPT_DIR/$(basename \"$CGNAT_OUTER_CLIENT_CERT_PATH\")\" ]]",
            "[[ -f \"$SCRIPT_DIR/$(basename \"$CGNAT_OUTER_CLIENT_KEY_PATH\")\" ]]",
            "[[ -f \"$SCRIPT_DIR/$(basename \"$CGNAT_OUTER_CA_CERT_PATH\")\" ]]",
            "[[ -f \"$SCRIPT_DIR/$CGNAT_INNER_VPN_SECRET_STAGE_NAME\" ]]",
            "",
            f"echo \"Preflight OK for {role}\"",
            "",
        ]
    )


def _render_strongswan_bootstrap() -> list[str]:
    return [
        "install_strongswan() {",
        "  if command -v swanctl >/dev/null; then",
        "    return 0",
        "  fi",
        "  if command -v dnf >/dev/null; then",
        "    dnf -y install strongswan strongswan-swanctl || dnf -y install strongswan",
        "  elif command -v yum >/dev/null; then",
        "    yum -y install strongswan strongswan-swanctl || yum -y install strongswan",
        "  else",
        "    echo \"No supported package manager found for strongSwan installation\" >&2",
        "    exit 1",
        "  fi",
        "}",
        "",
        "strongswan_service_name() {",
        "  local candidate",
        "  for candidate in strongswan-starter strongswan charon-systemd; do",
        "    if systemctl list-unit-files \"${candidate}.service\" >/dev/null 2>&1; then",
        "      printf '%s\\n' \"$candidate\"",
        "      return 0",
        "    fi",
        "  done",
        "  printf '%s\\n' strongswan",
        "}",
        "",
        "install_strongswan",
        "STRONGSWAN_SERVICE=\"$(strongswan_service_name)\"",
    ]


def _render_head_end_apply() -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
        "source \"$SCRIPT_DIR/cgnat-head-end-runtime.env\"",
        "",
    ]
    lines.extend(_render_strongswan_bootstrap())
    lines.extend(
        [
            "install -d /etc/swanctl/conf.d /etc/swanctl/x509 /etc/swanctl/private /etc/swanctl/x509ca",
            "install -m 0644 \"$SCRIPT_DIR/$(basename \"$CGNAT_HEAD_END_SERVER_CERT_PATH\")\" \"$CGNAT_HEAD_END_SERVER_CERT_PATH\"",
            "install -m 0600 \"$SCRIPT_DIR/$(basename \"$CGNAT_HEAD_END_SERVER_KEY_PATH\")\" \"$CGNAT_HEAD_END_SERVER_KEY_PATH\"",
            "install -m 0644 \"$SCRIPT_DIR/$(basename \"$CGNAT_OUTER_CA_CERT_PATH\")\" \"$CGNAT_OUTER_CA_CERT_PATH\"",
            "install -m 0644 \"$SCRIPT_DIR/cgnat-head-end-swanctl.conf\" \"/etc/swanctl/conf.d/${CGNAT_SERVICE_ID}-outer.conf\"",
            "bash \"$SCRIPT_DIR/cgnat-head-end-forwarding.sh\"",
            "bash \"$SCRIPT_DIR/cgnat-head-end-xfrm.sh\"",
            "bash \"$SCRIPT_DIR/cgnat-head-end-gre.sh\"",
            "bash \"$SCRIPT_DIR/cgnat-head-end-routes.sh\"",
            "systemctl enable \"$STRONGSWAN_SERVICE\" >/dev/null 2>&1 || true",
            "systemctl restart \"$STRONGSWAN_SERVICE\"",
            "swanctl --load-all",
            "",
        ]
    )
    return "\n".join(lines)


def _render_isp_head_end_apply() -> str:
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
            "source \"$SCRIPT_DIR/cgnat-isp-head-end-runtime.env\"",
            "",
            "bash \"$SCRIPT_DIR/cgnat-isp-head-end-forwarding.sh\"",
            "",
        ]
    )


def _render_customer_router_apply(role: str) -> str:
    env_name = f"{role}-runtime.env"
    outer_conf_name = f"{role}-outer-swanctl.conf"
    inner_conf_name = f"{role}-inner-swanctl.conf"
    xfrm_script_name = f"{role}-xfrm.sh"
    loop_name = f"{role}-loopback.sh"
    route_name = f"{role}-routes.sh"
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
        f"source \"$SCRIPT_DIR/{env_name}\"",
        "",
    ]
    lines.extend(_render_strongswan_bootstrap())
    lines.extend(
        [
            "install -d /etc/swanctl/conf.d /etc/swanctl/x509 /etc/swanctl/private /etc/swanctl/x509ca",
            f"bash \"$SCRIPT_DIR/{loop_name}\"",
            f"bash \"$SCRIPT_DIR/{route_name}\"",
            f"bash \"$SCRIPT_DIR/{xfrm_script_name}\"",
            "install -m 0644 \"$SCRIPT_DIR/$(basename \"$CGNAT_OUTER_CLIENT_CERT_PATH\")\" \"$CGNAT_OUTER_CLIENT_CERT_PATH\"",
            "install -m 0600 \"$SCRIPT_DIR/$(basename \"$CGNAT_OUTER_CLIENT_KEY_PATH\")\" \"$CGNAT_OUTER_CLIENT_KEY_PATH\"",
            "install -m 0644 \"$SCRIPT_DIR/$(basename \"$CGNAT_OUTER_CA_CERT_PATH\")\" \"$CGNAT_OUTER_CA_CERT_PATH\"",
            f"install -m 0644 \"$SCRIPT_DIR/{outer_conf_name}\" \"/etc/swanctl/conf.d/${{CGNAT_OUTER_CONNECTION_NAME}}.conf\"",
            f"install -m 0644 \"$SCRIPT_DIR/{inner_conf_name}\" \"/etc/swanctl/conf.d/${{CGNAT_INNER_CONNECTION_NAME}}.conf\"",
            "RAW_SECRET_FILE=\"$SCRIPT_DIR/$CGNAT_INNER_VPN_SECRET_STAGE_NAME\"",
            "SECRET_VALUE=\"$(tr -d '\\r\\n' < \"$RAW_SECRET_FILE\")\"",
            "cat > \"$CGNAT_INNER_VPN_SECRET_CONF_PATH\" <<EOF",
            "secrets {",
            "  ${CGNAT_INNER_CONNECTION_NAME} {",
            "    id-1 = ${CGNAT_CUSTOMER_LOOPBACK_IP}",
            "    id-2 = ${CGNAT_CUSTOMER_FACING_PUBLIC_IP}",
            "    secret = \"$SECRET_VALUE\"",
            "  }",
            "}",
            "EOF",
            "chmod 600 \"$CGNAT_INNER_VPN_SECRET_CONF_PATH\"",
            "systemctl enable \"$STRONGSWAN_SERVICE\" >/dev/null 2>&1 || true",
            "systemctl restart \"$STRONGSWAN_SERVICE\"",
            "swanctl --load-all",
            "swanctl --initiate --ike \"$CGNAT_OUTER_CONNECTION_NAME\"",
            "swanctl --initiate --ike \"$CGNAT_INNER_CONNECTION_NAME\"",
            "",
        ]
    )
    return "\n".join(lines)


def _render_head_end_rollback() -> str:
    return "\n".join(
        [
            "# CGNAT HEAD END Rollback Notes",
            "",
            "1. Remove the staged strongSwan fragment from `/etc/swanctl/conf.d/`.",
            "2. Remove the staged cert/key/CA material from `/etc/swanctl/` if needed.",
            "3. Remove the xfrm interfaces created for each customer router.",
            "4. Remove the GRE interface created by `cgnat-head-end-gre.sh`.",
            "5. Remove the route installed by `cgnat-head-end-routes.sh`.",
            "6. Restart the strongSwan service to unload the transport config.",
            "",
        ]
    )


def _render_isp_head_end_rollback() -> str:
    return "\n".join(
        [
            "# CGNAT ISP HEAD END Rollback Notes",
            "",
            "1. Disable forwarding if this host should no longer transit customer-router traffic.",
            "2. Remove any demo-only NAT changes if they were applied out of band.",
            "3. Re-run transit validation to confirm customer-router traffic no longer crosses this node.",
            "",
        ]
    )


def _render_customer_router_rollback(role: str) -> str:
    return "\n".join(
        [
            f"# {role} Rollback Notes",
            "",
            "1. Remove the staged strongSwan outer and inner fragments from `/etc/swanctl/conf.d/`.",
            "2. Remove the staged PSK secret fragment from `/etc/swanctl/conf.d/`.",
            "3. Remove the client cert, key, and CA from `/etc/swanctl/` if needed.",
            "4. Remove the xfrm interface and route to the customer-facing public IP.",
            "5. Remove the demo loopback identity if it was demo-only.",
            "6. Restore the pre-demo default route if needed.",
            "7. Restart the strongSwan service to unload the Scenario 1 tunnels.",
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
    return str(runtime["inner_vpn"]["raw_secret_stage_name"])


def _apply_live_host_access_overrides(
    server_configs: dict[str, Any],
    host_access: dict[str, Any] | None,
) -> None:
    if not host_access:
        return
    head_end = dict(host_access.get("cgnat_head_end") or {})
    target_host = str(head_end.get("target_host") or "").strip()
    if not target_host:
        return

    runtime_inputs = server_configs["runtime_inputs"]
    for router in runtime_inputs["customer_vpn_routers"]:
        router["outer_tunnel"]["remote_addrs"] = [target_host]
        role = router["role"]
        env_text = server_configs["customer_router_runtime_envs"][role]
        env_text = env_text.replace(HEAD_END_PUBLIC_IP_PLACEHOLDER, target_host)
        env_text = re.sub(
            r'^CGNAT_OUTER_REMOTE_PUBLIC_IP="[^"]*"$',
            f'CGNAT_OUTER_REMOTE_PUBLIC_IP="{target_host}"',
            env_text,
            flags=re.MULTILINE,
        )
        server_configs["customer_router_runtime_envs"][role] = env_text

        outer_conf = server_configs["customer_router_outer_confs"][role]
        outer_conf = outer_conf.replace(HEAD_END_PUBLIC_IP_PLACEHOLDER, target_host)
        outer_conf = re.sub(
            r"^(\s*remote_addrs = ).*$",
            rf"\g<1>{target_host}",
            outer_conf,
            flags=re.MULTILINE,
        )
        server_configs["customer_router_outer_confs"][role] = outer_conf


def _stage_materials(
    host_dirs: dict[str, Path],
    server_configs: dict[str, Any],
    materials_manifest: dict[str, Any],
) -> None:
    runtime = server_configs["runtime_inputs"]
    certs = materials_manifest["certificate_material"]
    inner_materials = list(materials_manifest.get("inner_vpn_materials") or [])
    inner_by_role = {entry["router_role"]: entry for entry in inner_materials}
    outer_materials = list(certs.get("customer_router_outer_clients") or [])
    outer_by_role = {entry["router_role"]: entry for entry in outer_materials}

    head_dir = host_dirs["cgnat_head_end"]
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

    for router_runtime in runtime["customer_vpn_routers"]:
        role = router_runtime["role"]
        router_dir = host_dirs[role]
        outer_material = outer_by_role.get(role)
        if outer_material is None:
            raise ValueError(f"materials manifest is missing customer_router_outer_clients entry for router role `{role}`")
        _copy_material(
            Path(outer_material["certificate_path"]),
            router_dir / Path(router_runtime["certificate_material"]["outer_client"]["certificate_path"]).name,
        )
        _copy_material(
            Path(outer_material["private_key_path"]),
            router_dir / Path(router_runtime["certificate_material"]["outer_client"]["private_key_path"]).name,
        )
        _copy_material(
            Path(certs["outer_tunnel_ca"]["certificate_path"]),
            router_dir / Path(router_runtime["certificate_material"]["outer_tunnel_ca"]["certificate_path"]).name,
        )
        material = inner_by_role.get(role)
        if material is None:
            raise ValueError(f"materials manifest is missing inner_vpn_materials entry for router role `{role}`")
        _copy_material(Path(material["secret_path"]), router_dir / _inner_secret_name(router_runtime))


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
    parser.add_argument(
        "--host-access-json",
        help="Optional path to a derived host-access JSON file. When provided, live host values are applied to the host bundles.",
    )
    args = parser.parse_args()

    server_config_dir = Path(args.server_config_dir).resolve()
    output_dir = ensure_path_within_cgnat(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    server_configs = _load_server_configs(server_config_dir)
    host_access = _load_host_access(Path(args.host_access_json).resolve()) if args.host_access_json else None
    _apply_live_host_access_overrides(server_configs, host_access)

    materials_manifest = None
    if args.materials_manifest_json:
        materials_manifest = _load_materials_manifest(Path(args.materials_manifest_json).resolve())

    manifest = _render_manifest(
        server_configs,
        materials_manifest_path=str(Path(args.materials_manifest_json).resolve()) if args.materials_manifest_json else None,
    )
    if host_access:
        manifest["host_access_path"] = str(Path(args.host_access_json).resolve())

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
    dump_text(head_dir / "cgnat-head-end-swanctl.conf", server_configs["head_end_swanctl_conf"])
    dump_text(head_dir / "cgnat-head-end-xfrm.sh", server_configs["head_end_xfrm_script"])
    dump_text(head_dir / "cgnat-head-end-gre.sh", server_configs["head_end_gre_script"])
    dump_text(head_dir / "cgnat-head-end-forwarding.sh", server_configs["head_end_forwarding_script"])
    dump_text(head_dir / "cgnat-head-end-routes.sh", server_configs["head_end_route_script"])
    dump_text(head_dir / "preflight.sh", _render_head_end_preflight())
    dump_text(head_dir / "apply.sh", _render_head_end_apply())
    dump_text(head_dir / "rollback-notes.md", _render_head_end_rollback())

    isp_dir = host_dirs["cgnat_isp_head_end"]
    dump_text(isp_dir / "cgnat-isp-head-end-runtime.env", server_configs["isp_head_end_runtime_env"])
    dump_text(isp_dir / "cgnat-isp-head-end-swanctl.conf", server_configs["isp_head_end_ipsec_conf"])
    dump_text(isp_dir / "cgnat-isp-head-end-forwarding.sh", server_configs["isp_head_end_forwarding_script"])
    dump_text(isp_dir / "preflight.sh", _render_isp_head_end_preflight(server_configs))
    dump_text(isp_dir / "apply.sh", _render_isp_head_end_apply())
    dump_text(isp_dir / "rollback-notes.md", _render_isp_head_end_rollback())

    for router_runtime in server_configs["runtime_inputs"]["customer_vpn_routers"]:
        role = router_runtime["role"]
        router_dir = host_dirs[role]
        dump_text(router_dir / f"{role}-runtime.env", server_configs["customer_router_runtime_envs"][role])
        dump_text(router_dir / f"{role}-outer-swanctl.conf", server_configs["customer_router_outer_confs"][role])
        dump_text(router_dir / f"{role}-inner-swanctl.conf", server_configs["customer_router_inner_confs"][role])
        dump_text(router_dir / f"{role}-xfrm.sh", server_configs["customer_router_xfrm_scripts"][role])
        dump_text(router_dir / f"{role}-loopback.sh", server_configs["customer_router_loopback_scripts"][role])
        dump_text(router_dir / f"{role}-routes.sh", server_configs["customer_router_route_scripts"][role])
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
