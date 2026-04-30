from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _framework_src_root() -> Path:
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent / "src"


def _load_json(path: Path) -> dict[str, Any] | list[Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _associated_public_ip(apply_result: dict[str, Any], service_role: str) -> tuple[str | None, str | None]:
    for action in apply_result.get("post_create_actions", []):
        if action.get("service_role") != service_role:
            continue
        response = action.get("response") or {}
        allocation = response.get("allocation") or {}
        if allocation.get("PublicIp"):
            return allocation.get("PublicIp"), allocation.get("AllocationId")
        address_set = response.get("address", {}).get("Addresses") or []
        if address_set and address_set[0].get("PublicIp"):
            return address_set[0].get("PublicIp"), address_set[0].get("AllocationId")
    return None, None


def _update_bundle_public_ips(bundle: dict[str, Any], apply_result: dict[str, Any]) -> dict[str, Any]:
    head_public_ip, head_allocation_id = _associated_public_ip(apply_result, "cgnat_head_end")
    isp_public_ip, isp_allocation_id = _associated_public_ip(apply_result, "cgnat_isp_head_end")

    if not head_public_ip:
        raise ValueError("Unable to resolve associated public IP for cgnat_head_end from apply result.")
    if not isp_public_ip:
        raise ValueError("Unable to resolve associated public IP for cgnat_isp_head_end from apply result.")

    bundle["operations"]["cgnat_head_end"]["allocated_public_ip"] = head_public_ip
    bundle["operations"]["cgnat_isp_head_end"]["allocated_public_ip"] = isp_public_ip
    bundle["operations"]["cgnat_head_end"]["public_eip_allocation_id"] = head_allocation_id
    bundle["operations"]["cgnat_isp_head_end"]["public_eip_allocation_id"] = isp_allocation_id
    return bundle


def main() -> int:
    sys.path.insert(0, str(_framework_src_root()))

    from cgnat.bundle import dump_json, ensure_path_within_cgnat

    parser = argparse.ArgumentParser(
        description="Update a deployment bundle with the actual public IPs allocated during a live AWS apply."
    )
    parser.add_argument("bundle_json", help="Path to the source deployment bundle JSON.")
    parser.add_argument("apply_result_json", help="Path to the successful AWS apply-result.json artifact.")
    parser.add_argument("output_json", help="Path to write the updated deployment bundle JSON.")
    args = parser.parse_args()

    bundle = _load_json(Path(args.bundle_json).resolve())
    apply_result = _load_json(Path(args.apply_result_json).resolve())
    updated_bundle = _update_bundle_public_ips(bundle, apply_result)
    dump_json(ensure_path_within_cgnat(args.output_json), updated_bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
