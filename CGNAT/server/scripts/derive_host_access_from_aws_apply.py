from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _framework_src_root() -> Path:
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent.parent / "framework" / "src"


def _load_json(path: Path) -> dict[str, Any] | list[Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _role_results(apply_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    payload = {
        "cgnat_head_end": apply_result.get("head_end", {}),
        "cgnat_isp_head_end": apply_result.get("isp_head_end", {}),
    }
    for router in apply_result.get("customer_vpn_routers", []):
        role = router.get("role")
        if role:
            payload[role] = router
    return payload


def _instance_record(apply_result: dict[str, Any], role: str) -> dict[str, Any]:
    role_result = _role_results(apply_result).get(role) or {}
    return role_result.get("response", {}).get("Instances", [{}])[0]


def _associated_public_ip(apply_result: dict[str, Any], service_role: str) -> str | None:
    for action in apply_result.get("post_create_actions", []):
        if action.get("service_role") != service_role:
            continue
        response = action.get("response") or {}
        allocation = response.get("allocation") or {}
        if allocation.get("PublicIp"):
            return allocation["PublicIp"]
        address_set = response.get("address", {}).get("Addresses") or []
        if address_set and address_set[0].get("PublicIp"):
            return address_set[0]["PublicIp"]
    return None


def _resolve_target_host(apply_result: dict[str, Any], strategy: dict[str, Any], service_role: str) -> str:
    instance = _instance_record(apply_result, service_role)
    address_source = strategy.get("address_source")

    if address_source == "associated_public_ip":
        public_ip = _associated_public_ip(apply_result, service_role)
        if public_ip:
            return public_ip
        raise ValueError(f"No associated public IP found for {service_role}.")
    if address_source == "instance_public_ip":
        public_ip = instance.get("PublicIpAddress")
        if public_ip:
            return public_ip
        raise ValueError(f"No instance public IP found for {service_role}.")
    if address_source == "private_ip":
        private_ip = instance.get("PrivateIpAddress")
        if private_ip:
            return private_ip
        raise ValueError(f"No private IP found for {service_role}.")
    raise ValueError(f"Unsupported address_source `{address_source}` for {service_role}.")


def _validate_strategy(strategy: dict[str, Any]) -> None:
    required_fields = ("ssh_user", "private_key_path", "remote_stage_dir", "address_source")
    missing: list[str] = []
    for role, role_data in strategy.items():
        if not isinstance(role_data, dict):
            missing.append(role)
            continue
        for field_name in required_fields:
            if not role_data.get(field_name):
                missing.append(f"{role}.{field_name}")
        proxy_jump_role = role_data.get("proxy_jump_role")
        if proxy_jump_role and proxy_jump_role not in strategy:
            missing.append(f"{role}.proxy_jump_role->{proxy_jump_role}")
    if missing:
        raise ValueError(f"Host access strategy is missing required entries: {', '.join(missing)}")


def main() -> int:
    sys.path.insert(0, str(_framework_src_root()))

    from cgnat.bundle import dump_json, ensure_path_within_cgnat

    parser = argparse.ArgumentParser(description="Derive remote host access inputs from a successful AWS apply result.")
    parser.add_argument("apply_result_json", help="Path to the AWS apply-result.json artifact.")
    parser.add_argument("host_access_strategy_json", help="Path to the host access strategy JSON file.")
    parser.add_argument("output_json", help="Path to write the derived host access JSON.")
    args = parser.parse_args()

    apply_result = _load_json(Path(args.apply_result_json).resolve())
    strategy = _load_json(Path(args.host_access_strategy_json).resolve())
    _validate_strategy(strategy)

    payload = {}
    for role, role_strategy in strategy.items():
        payload[role] = {
            "ssh_user": role_strategy["ssh_user"],
            "target_host": _resolve_target_host(apply_result, role_strategy, role),
            "private_key_path": role_strategy["private_key_path"],
            "remote_stage_dir": role_strategy["remote_stage_dir"],
        }
        if role_strategy.get("proxy_jump_role"):
            payload[role]["proxy_jump_role"] = role_strategy["proxy_jump_role"]

    dump_json(ensure_path_within_cgnat(args.output_json), payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
