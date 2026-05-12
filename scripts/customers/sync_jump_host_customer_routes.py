#!/usr/bin/env python
"""Keep jump-host customer routes aligned with live RPDB customer placement."""

from __future__ import annotations

import argparse
import json
import re
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
from muxerlib.customer_route_scope import customer_route_cidrs

DEFAULT_STATE_FILE = Path("build/jump-host-routes/state/state.json")
DEFAULT_OUT_DIR = Path("build/jump-host-routes/out")
DEV_PATTERN = re.compile(r"\bdev\s+(\S+)")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def repo_path(value: str | Path) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def resolve_environment_path(value: str) -> Path:
    raw = Path(value)
    candidates = [raw if raw.is_absolute() else (REPO_ROOT / raw).resolve()]
    if raw.suffix.lower() not in {".yaml", ".yml"}:
        candidates.append((REPO_ROOT / "muxer" / "config" / "deployment-environments" / f"{value}.yaml").resolve())
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"deployment environment not found: {value}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_command(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return completed


def run_aws_json(command: list[str]) -> dict[str, Any]:
    completed = run_command(command, check=True)
    if not completed.stdout.strip():
        return {}
    return json.loads(completed.stdout)


def load_previous_state(state_file: Path) -> dict[str, Any]:
    if not state_file.is_file():
        return {"managed_routes": []}
    return json.loads(state_file.read_text(encoding="utf-8"))


def iter_customer_request_files(environment_doc: dict[str, Any]) -> list[Path]:
    allowed_roots = (
        (environment_doc.get("customer_requests") or {}).get("allowed_roots")
        or ["muxer/config/customer-requests/migrated"]
    )
    request_files: list[Path] = []
    for root in allowed_roots:
        candidate_root = repo_path(str(root))
        if not candidate_root.is_dir():
            continue
        if candidate_root.name != "migrated":
            continue
        request_files.extend(sorted(candidate_root.glob("*.yaml")))
    return request_files


def collect_customer_route_targets(environment_doc: dict[str, Any]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for path in iter_customer_request_files(environment_doc):
        document = load_yaml_file(path)
        customer = document.get("customer") or {}
        name = str(customer.get("name") or "").strip()
        if not name:
            continue
        route_cidrs, route_source = customer_route_cidrs(customer)
        if route_source == "post_ipsec_nat.host_mappings.translated_ip":
            route_kind = "inside_nat_explicit"
        elif route_source == "post_ipsec_nat.netmap_translated_hosts":
            route_kind = "inside_nat_distinct"
        elif route_source == "post_ipsec_nat.translated_subnets":
            route_kind = "inside_nat_pool"
        else:
            route_kind = "loopback"
        for cidr in route_cidrs:
            targets.append(
                {
                    "customer_name": name,
                    "cidr": cidr,
                    "route_kind": route_kind,
                    "route_source": route_source,
                    "source_file": str(path),
                }
            )
    return targets


def load_customer_placement_map(environment_doc: dict[str, Any]) -> dict[str, str]:
    aws_region = str(((environment_doc.get("environment") or {}).get("aws") or {}).get("region") or (environment_doc.get("aws") or {}).get("region") or "us-east-1")
    datastores = environment_doc.get("datastores") or {}
    table_name = str(datastores.get("customer_sot_table") or "").strip()
    if not table_name:
        raise ValueError("deployment environment missing datastores.customer_sot_table")
    payload = run_aws_json(
        [
            "aws",
            "dynamodb",
            "scan",
            "--region",
            aws_region,
            "--table-name",
            table_name,
            "--output",
            "json",
        ]
    )
    placement: dict[str, str] = {}
    for item in payload.get("Items") or []:
        customer_name = str((item.get("customer_name") or {}).get("S") or "").strip()
        backend_cluster = str((item.get("backend_cluster") or {}).get("S") or "").strip()
        if customer_name and backend_cluster:
            placement[customer_name] = backend_cluster
    return placement


def headend_private_ips(environment_doc: dict[str, Any]) -> dict[str, str]:
    targets = environment_doc.get("targets") or {}
    headends = targets.get("headends") or {}
    nat_private_ip = str((((headends.get("nat") or {}).get("active") or {}).get("selector") or {}).get("private_ip") or "").strip()
    non_nat_private_ip = str((((headends.get("non_nat") or {}).get("active") or {}).get("selector") or {}).get("private_ip") or "").strip()
    if not nat_private_ip or not non_nat_private_ip:
        raise ValueError("deployment environment missing active headend private_ip selectors")
    return {
        "nat": nat_private_ip,
        "non-nat": non_nat_private_ip,
        "non_nat": non_nat_private_ip,
    }


def resolve_route_device(next_hop: str) -> str:
    completed = run_command(["ip", "route", "get", next_hop], check=True)
    match = DEV_PATTERN.search(completed.stdout)
    if not match:
        raise RuntimeError(f"unable to determine route device for next hop {next_hop!r}: {completed.stdout}")
    return match.group(1)


def delete_route(cidr: str) -> dict[str, Any]:
    completed = run_command(["sudo", "-n", "ip", "route", "del", cidr], check=False)
    return {
        "cidr": cidr,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "deleted": completed.returncode == 0,
        "missing": completed.returncode != 0 and "No such process" in completed.stderr,
    }


def replace_route(cidr: str, *, next_hop: str, device: str) -> dict[str, Any]:
    completed = run_command(
        ["sudo", "-n", "ip", "route", "replace", cidr, "via", next_hop, "dev", device, "proto", "static"],
        check=True,
    )
    return {
        "cidr": cidr,
        "next_hop": next_hop,
        "device": device,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def sync_routes_once(
    *,
    environment_path: Path,
    environment_doc: dict[str, Any],
    state_file: Path,
    out_dir: Path,
) -> dict[str, Any]:
    previous_state = load_previous_state(state_file)
    previous_routes = {
        str(item.get("cidr")): item
        for item in (previous_state.get("managed_routes") or [])
        if str(item.get("cidr") or "").strip()
    }
    customer_targets = collect_customer_route_targets(environment_doc)
    placement_map = load_customer_placement_map(environment_doc)
    headend_ips = headend_private_ips(environment_doc)

    skipped_customers: list[dict[str, Any]] = []
    desired_routes: list[dict[str, Any]] = []
    device_cache: dict[str, str] = {}

    for target in customer_targets:
        customer_name = target["customer_name"]
        backend_cluster = placement_map.get(customer_name)
        if not backend_cluster:
            skipped_customers.append(
                {
                    "customer_name": customer_name,
                    "cidr": target["cidr"],
                    "route_kind": target["route_kind"],
                    "reason": "customer not present in live SoT",
                }
            )
            continue
        next_hop = headend_ips.get(backend_cluster)
        if not next_hop:
            skipped_customers.append(
                {
                    "customer_name": customer_name,
                    "cidr": target["cidr"],
                    "route_kind": target["route_kind"],
                    "reason": f"unsupported backend_cluster: {backend_cluster}",
                }
            )
            continue
        device = device_cache.setdefault(next_hop, resolve_route_device(next_hop))
        desired_routes.append(
            {
                **target,
                "backend_cluster": backend_cluster,
                "next_hop": next_hop,
                "device": device,
            }
        )

    desired_by_cidr = {item["cidr"]: item for item in desired_routes}
    stale_cidrs = sorted(set(previous_routes) - set(desired_by_cidr))
    deleted_routes = [delete_route(cidr) for cidr in stale_cidrs]

    applied_routes: list[dict[str, Any]] = []
    for cidr, route in sorted(desired_by_cidr.items()):
        applied = replace_route(cidr, next_hop=route["next_hop"], device=route["device"])
        applied_routes.append(
            {
                **route,
                **applied,
            }
        )

    state_payload = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "environment_file": str(environment_path),
        "managed_routes": [
            {
                "cidr": item["cidr"],
                "customer_name": item["customer_name"],
                "route_kind": item["route_kind"],
                "backend_cluster": item["backend_cluster"],
                "next_hop": item["next_hop"],
                "device": item["device"],
            }
            for item in applied_routes
        ],
    }
    write_json(state_file, state_payload)

    report = {
        "schema_version": 1,
        "action": "sync_jump_host_customer_routes",
        "status": "ok",
        "generated_at": utc_now(),
        "environment_file": str(environment_path),
        "state_file": str(state_file),
        "applied_route_count": len(applied_routes),
        "deleted_route_count": len([item for item in deleted_routes if item.get("deleted")]),
        "skipped_count": len(skipped_customers),
        "applied_routes": applied_routes,
        "deleted_routes": deleted_routes,
        "skipped_customers": skipped_customers,
    }
    write_json(out_dir / "route-sync-summary.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync jump-host routes for live RPDB customer loopbacks and inside NAT prefixes.")
    parser.add_argument("--environment", required=True, help="Deployment environment name or YAML path")
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_FILE), help="State file path")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Summary output directory")
    parser.add_argument("--follow", action="store_true", help="Keep resyncing routes on an interval")
    parser.add_argument("--poll-interval-seconds", type=float, default=30.0, help="Polling interval when --follow is used")
    parser.add_argument("--json", action="store_true", help="Print sync summaries as JSON")
    args = parser.parse_args()

    environment_path = resolve_environment_path(args.environment)
    environment_doc = load_yaml_file(environment_path)
    state_file = repo_path(args.state_file)
    out_dir = repo_path(args.out_dir)

    while True:
        report = sync_routes_once(
            environment_path=environment_path,
            environment_doc=environment_doc,
            state_file=state_file,
            out_dir=out_dir,
        )
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(
                "Jump-host route sync: "
                f"{report['applied_route_count']} applied, "
                f"{report['deleted_route_count']} deleted, "
                f"{report['skipped_count']} skipped"
            )
        if not args.follow:
            return 0
        time.sleep(max(args.poll_interval_seconds, 5.0))


if __name__ == "__main__":
    raise SystemExit(main())
