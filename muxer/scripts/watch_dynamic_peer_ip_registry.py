#!/usr/bin/env python
"""Watch the device registry for peer public IP changes and trigger reapply."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
CUSTOMERS_DIR = Path(__file__).resolve().parents[2] / "scripts" / "customers"
if str(CUSTOMERS_DIR) not in sys.path:
    sys.path.insert(0, str(CUSTOMERS_DIR))

from customer_operation_lock import is_lock_active, read_lock
from muxerlib.dynamic_peer_ip import (
    build_dynamic_peer_ip_change_idempotency_key,
    normalize_device_registry_record,
    normalize_dynamic_peer_ip_event,
    validate_dynamic_peer_ip_request,
)


@dataclass(frozen=True)
class CustomerWatch:
    name: str
    request_path: Path
    request_peer_ip: str
    serial_number: str
    table_name: str
    serial_number_attribute: str
    current_ip_attribute: str
    last_updated_attribute: str
    reapply_mode: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": 1,
            "customers": {},
            "planned_idempotency_keys": [],
        }
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_environment_path(repo_root: Path, environment: str | None) -> Path | None:
    value = str(environment or "").strip()
    if not value:
        return None
    raw = Path(value)
    candidates = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append((repo_root / raw).resolve())
        if raw.suffix.lower() not in {".yaml", ".yml"}:
            candidates.append(
                (repo_root / "muxer" / "config" / "deployment-environments" / f"{value}.yaml").resolve()
            )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _environment_request_roots(repo_root: Path, environment: str | None) -> list[Path]:
    environment_path = _resolve_environment_path(repo_root, environment)
    if environment_path is None:
        return []
    document = _load_yaml(environment_path)
    roots = ((document.get("customer_requests") or {}).get("allowed_roots") or [])
    return [Path(str(root)) for root in roots if str(root).strip()]


def _environment_blocked_customers(repo_root: Path, environment: str | None) -> set[str]:
    environment_path = _resolve_environment_path(repo_root, environment)
    if environment_path is None:
        return set()
    document = _load_yaml(environment_path)
    blocked = ((document.get("customer_requests") or {}).get("blocked_customers") or [])
    return {str(customer).strip() for customer in blocked if str(customer).strip()}


def _environment_dynamic_peer_ip_config(repo_root: Path, environment: str | None) -> dict[str, Any]:
    environment_path = _resolve_environment_path(repo_root, environment)
    if environment_path is None:
        return {}
    document = _load_yaml(environment_path)
    watcher = document.get("dynamic_peer_ip_watcher") or {}
    return {
        "source": watcher.get("source") or {},
        "state_root": watcher.get("state_root"),
        "output_root": watcher.get("output_root"),
        "package_root": watcher.get("package_root"),
        "automation": watcher.get("automation") or {},
        "reapply": watcher.get("reapply") or {},
        "environment_region": (((document.get("environment") or {}).get("aws") or {}).get("region")),
        "environment_access_method": (((document.get("environment") or {}).get("access") or {}).get("method")),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _discover_request_paths(paths: Iterable[Path], roots: Iterable[Path]) -> list[Path]:
    discovered: dict[str, Path] = {}
    ordered: list[Path] = []

    def add_path(path: Path) -> None:
        resolved = path.resolve()
        key = str(resolved)
        if key in discovered:
            return
        discovered[key] = resolved
        ordered.append(resolved)

    for path in paths:
        resolved = path.resolve()
        if resolved.is_file():
            add_path(resolved)
    for root in roots:
        resolved_root = root.resolve()
        if not resolved_root.exists():
            continue
        if resolved_root.is_file():
            add_path(resolved_root)
            continue
        for candidate in sorted(resolved_root.rglob("*.yaml")):
            if candidate.is_file():
                add_path(candidate)
    return ordered


def _load_customer_watches(
    request_paths: list[Path],
    *,
    blocked_customers: set[str] | None = None,
    reapply_mode_override: str | None = None,
) -> tuple[dict[str, CustomerWatch], list[dict[str, str]]]:
    watches: dict[str, CustomerWatch] = {}
    errors: list[dict[str, str]] = []
    blocked = blocked_customers or set()
    seen_serials: dict[str, str] = {}
    for request_path in request_paths:
        try:
            doc = _load_yaml(request_path)
            validation = validate_dynamic_peer_ip_request(doc)
            if not validation.get("enabled"):
                continue
            customer_name = str(validation["customer_name"])
            if customer_name in blocked:
                errors.append(
                    {
                        "request": str(request_path),
                        "customer_name": customer_name,
                        "error": "customer is blocked by deployment environment policy",
                    }
                )
                continue
            serial_number = str(validation["serial_number"])
            previous_customer = seen_serials.get(serial_number)
            if previous_customer and previous_customer != customer_name:
                errors.append(
                    {
                        "request": str(request_path),
                        "error": f"device registry serial {serial_number} is shared by {previous_customer} and {customer_name}",
                    }
                )
                continue
            seen_serials[serial_number] = customer_name
            reapply_mode = str(reapply_mode_override or validation.get("reapply_mode") or "deploy_only").strip()
            if reapply_mode not in {"deploy_only", "remove_reapply"}:
                raise ValueError("dynamic peer IP watcher reapply mode must be deploy_only or remove_reapply")
            watches[customer_name] = CustomerWatch(
                name=customer_name,
                request_path=request_path,
                request_peer_ip=str(validation["peer_public_ip"]),
                serial_number=serial_number,
                table_name=str(validation.get("table_name") or ""),
                serial_number_attribute=str(validation["serial_number_attribute"]),
                current_ip_attribute=str(validation["current_ip_attribute"]),
                last_updated_attribute=str(validation["last_updated_attribute"]),
                reapply_mode=reapply_mode,
            )
        except Exception as exc:
            errors.append({"request": str(request_path), "error": str(exc)})
    return watches, errors


def _registry_records_from_file(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        payload = payload["records"]

    records: dict[str, dict[str, Any]] = {}
    if isinstance(payload, list):
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            serial = str(entry.get("serialNumber") or entry.get("serial_number") or "").strip()
            if serial:
                records[serial] = entry
        return records

    if isinstance(payload, dict):
        if "serialNumber" in payload or "serial_number" in payload:
            serial = str(payload.get("serialNumber") or payload.get("serial_number") or "").strip()
            if serial:
                records[serial] = payload
            return records
        for serial, entry in payload.items():
            if isinstance(entry, dict):
                record = dict(entry)
                record.setdefault("serialNumber", str(serial))
                records[str(serial)] = record
        return records

    raise ValueError("dynamic peer IP json_file source must be a mapping or list")


def _run_command_json(repo_root: Path, command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    parsed: dict[str, Any] | None = None
    if completed.stdout.strip():
        try:
            parsed = json.loads(completed.stdout)
        except json.JSONDecodeError:
            parsed = None
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "json": parsed,
    }


def _fetch_registry_record_dynamodb(
    watch: CustomerWatch,
    *,
    repo_root: Path,
    source_doc: dict[str, Any],
    environment_region: str,
) -> dict[str, Any] | None:
    region = str(source_doc.get("region") or environment_region or "").strip()
    table_name = watch.table_name or str(source_doc.get("table_name") or "").strip()
    if not region or not table_name:
        raise ValueError("dynamic peer IP watcher requires source.region and table_name for dynamodb_table mode")

    command = [
        "aws",
        "dynamodb",
        "get-item",
        "--region",
        region,
        "--table-name",
        table_name,
        "--key",
        json.dumps(
            {
                watch.serial_number_attribute: {
                    "S": watch.serial_number,
                }
            }
        ),
        "--consistent-read",
        "--output",
        "json",
    ]
    completed = subprocess.run(
        command,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip() or "AWS CLI get-item failed")
    payload = json.loads(completed.stdout or "{}")
    item = payload.get("Item")
    if not isinstance(item, dict):
        return None
    record = normalize_device_registry_record(
        item,
        serial_number=watch.serial_number,
        serial_number_attribute=watch.serial_number_attribute,
        current_ip_attribute=watch.current_ip_attribute,
        last_updated_attribute=watch.last_updated_attribute,
    )
    record["registry_table"] = table_name
    return record


def _customer_state(state: dict[str, Any], watch: CustomerWatch) -> dict[str, Any]:
    customers = state.setdefault("customers", {})
    customer_state = customers.setdefault(
        watch.name,
        {
            "serial_number": watch.serial_number,
            "request": str(watch.request_path),
            "current_peer_ip": watch.request_peer_ip,
            "last_registry_peer_ip": "",
            "last_registry_updated_at": "",
            "last_applied_at": "",
            "planned_idempotency_keys": [],
        },
    )
    customer_state["serial_number"] = watch.serial_number
    customer_state["request"] = str(watch.request_path)
    if not str(customer_state.get("current_peer_ip") or "").strip():
        customer_state["current_peer_ip"] = watch.request_peer_ip
    return customer_state


def _build_change_event(
    *,
    watch: CustomerWatch,
    customer_state: dict[str, Any],
    registry_record: dict[str, Any],
) -> dict[str, Any]:
    observed_at = str(registry_record.get("last_updated") or "").strip() or _utc_now()
    return {
        "schema_version": 1,
        "event_id": f"{watch.name}-auto-peer-ip-{observed_at.replace(':', '').replace('-', '')}",
        "customer_name": watch.name,
        "serial_number": watch.serial_number,
        "previous_peer": str(customer_state.get("current_peer_ip") or "").strip(),
        "observed_peer": str(registry_record["current_ip"]),
        "observed_at": observed_at,
        "registry_last_updated": str(registry_record.get("last_updated") or "").strip(),
        "registry_table": str(registry_record.get("registry_table") or "").strip(),
        "source": "dynamic-peer-ip-watcher",
    }


def _remove_planned_idempotency_key(
    *,
    state_keys: set[str],
    customer_state: dict[str, Any],
    idempotency_key: str,
) -> None:
    state_keys.discard(idempotency_key)
    customer_state["planned_idempotency_keys"] = [
        key
        for key in customer_state.get("planned_idempotency_keys") or []
        if str(key) != idempotency_key
    ]


def _provisioning_failed(provisioning: dict[str, Any] | None) -> bool:
    if provisioning is None:
        return False
    if int(provisioning.get("returncode") or 0) != 0:
        return True
    process_result = provisioning.get("process") or {}
    if int(process_result.get("returncode") or 0) != 0:
        return True
    payload = provisioning.get("json") or {}
    status = str(payload.get("status") or "").strip().lower()
    if status in {"blocked", "rolled_back", "failed"}:
        return True
    apply_status = str(((payload.get("apply") or {}).get("status")) or "").strip().lower()
    return apply_status in {"blocked", "rolled_back", "failed"}


def _remove_plan_customer_missing(plan: dict[str, Any]) -> bool:
    payload = plan.get("json") or {}
    errors = [str(error) for error in payload.get("errors") or []]
    return any("not present in the customer SoT" in error for error in errors)


def _run_pre_reapply_remove(
    *,
    repo_root: Path,
    watch: CustomerWatch,
    output_dir: Path,
    deployment_environment: str,
    approve: bool,
) -> dict[str, Any]:
    plan = _run_command_json(
        repo_root,
        [
            sys.executable,
            "scripts/customers/remove_customer.py",
            "--customer-name",
            watch.name,
            "--environment",
            deployment_environment,
            "--out-dir",
            str(output_dir / "plan"),
            "--json",
        ],
    )
    plan_json = plan.get("json") or {}
    if _remove_plan_customer_missing(plan):
        return {
            "status": "not_present",
            "reason": "customer_not_present_before_peer_ip_reapply",
            "plan": plan,
        }
    if plan.get("returncode") != 0 or plan_json.get("status") != "ready_to_remove":
        return {
            "status": "blocked",
            "reason": "pre_reapply_remove_plan_failed",
            "plan": plan,
        }
    if not approve:
        return {
            "status": "planned",
            "reason": "remove_reapply_requires_approved_run_for_live_remove",
            "plan": plan,
        }

    remove = _run_command_json(
        repo_root,
        [
            sys.executable,
            "scripts/customers/remove_customer.py",
            "--customer-name",
            watch.name,
            "--environment",
            deployment_environment,
            "--approve",
            "--skip-nat-t-watcher-cleanup",
            "--skip-dynamic-peer-ip-watcher-cleanup",
            "--out-dir",
            str(output_dir / "approved"),
            "--json",
        ],
    )
    remove_json = remove.get("json") or {}
    if remove.get("returncode") != 0 or remove_json.get("status") != "removed":
        return {
            "status": "blocked",
            "reason": "pre_reapply_remove_failed",
            "plan": plan,
            "remove": remove,
        }

    return {
        "status": "removed",
        "reason": "existing_customer_removed_before_peer_ip_reapply",
        "plan": plan,
        "remove": remove,
    }


def _run_customer_flow(
    *,
    repo_root: Path,
    watch: CustomerWatch,
    observation_path: Path,
    package_root: Path,
    deployment_environment: str | None,
    approve: bool,
) -> dict[str, Any]:
    output_dir = package_root / watch.name
    process = _run_command_json(
        repo_root,
        [
            sys.executable,
            "muxer/scripts/process_dynamic_peer_ip_change.py",
            str(watch.request_path),
            "--observation",
            str(observation_path),
            "--out-dir",
            str(output_dir / "process"),
            "--environment",
            deployment_environment,
            "--json",
        ],
    )
    process_json = process.get("json") or {}
    if process.get("returncode") != 0 or not process_json:
        return {
            "command": [],
            "returncode": process.get("returncode"),
            "stdout": "",
            "stderr": "",
            "json": None,
            "mode": "process_dynamic_peer_ip_change",
            "process": process,
            "pre_reapply_remove": None,
        }

    updated_request_path = str(((process_json.get("artifacts") or {}).get("updated_request")) or "").strip()
    if not updated_request_path:
        return {
            "command": [],
            "returncode": 1,
            "stdout": "",
            "stderr": "",
            "json": None,
            "mode": "process_dynamic_peer_ip_change",
            "process": process,
            "pre_reapply_remove": None,
        }

    pre_reapply_remove: dict[str, Any] | None = None
    if deployment_environment:
        if watch.reapply_mode == "remove_reapply":
            pre_reapply_remove = _run_pre_reapply_remove(
                repo_root=repo_root,
                watch=watch,
                output_dir=output_dir / "pre-reapply-remove",
                deployment_environment=deployment_environment,
                approve=approve,
            )
            if pre_reapply_remove.get("status") in {"blocked", "planned"}:
                return {
                    "command": [],
                    "returncode": 1 if pre_reapply_remove.get("status") == "blocked" else 0,
                    "stdout": "",
                    "stderr": "",
                    "json": {
                        "status": pre_reapply_remove.get("status"),
                        "live_apply": False,
                        "pre_reapply_remove": pre_reapply_remove,
                    },
                    "mode": "deploy_customer",
                    "process": process,
                    "pre_reapply_remove": pre_reapply_remove,
                }

        command = [
            sys.executable,
            "scripts/customers/deploy_customer.py",
            "--customer-file",
            updated_request_path,
            "--environment",
            deployment_environment,
            "--out-dir",
            str(output_dir),
            "--json",
        ]
        if approve:
            command.append("--approve")
    else:
        command = [
            sys.executable,
            "muxer/scripts/provision_customer_end_to_end.py",
            updated_request_path,
            "--out-dir",
            str(output_dir),
            "--json",
        ]

    execution = _run_command_json(repo_root, command)
    execution["mode"] = "deploy_customer" if deployment_environment else "provision_customer_end_to_end"
    execution["process"] = process
    execution["pre_reapply_remove"] = pre_reapply_remove
    return execution


def _build_summary(
    *,
    repo_root: Path,
    watches: dict[str, CustomerWatch],
    request_errors: list[dict[str, str]],
    state_file: Path,
    out_dir: Path,
    package_root: Path,
    loop_result: dict[str, Any],
    deployment_environment: str | None,
    approve: bool,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "action": "watch_dynamic_peer_ip_registry",
        "live_apply": False,
        "generated_at": _utc_now(),
        "state_file": str(state_file),
        "out_dir": str(out_dir),
        "package_root": str(package_root),
        "deployment_environment": deployment_environment,
        "approved_apply_requested": approve,
        "watched_customers": {
            name: {
                "serial_number": watch.serial_number,
                "request": str(watch.request_path),
                "request_peer_ip": watch.request_peer_ip,
                "reapply_mode": watch.reapply_mode,
            }
            for name, watch in sorted(watches.items())
        },
        "request_errors": request_errors,
        "detected_count": len(loop_result["detected"]),
        "ignored_count": len(loop_result["ignored"]),
        "detected": loop_result["detected"],
        "ignored": loop_result["ignored"],
        "repo_root": str(repo_root),
    }


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]

    parser = argparse.ArgumentParser(
        description=(
            "Watch the dynamic peer IP registry, correlate device updates to "
            "customer requests, write change events, and optionally run reapply."
        )
    )
    parser.add_argument("--customer-request", action="append", default=[], help="Customer request YAML. Can be specified multiple times.")
    parser.add_argument("--customer-request-root", action="append", default=[], help="Directory or file to search for customer requests. Can be specified multiple times.")
    parser.add_argument("--environment", help="Deployment environment name or file")
    parser.add_argument("--state-file", help="Watcher state JSON path")
    parser.add_argument("--out-dir", help="Directory for observation and summary artifacts")
    parser.add_argument("--package-root", help="Directory for staged process/deploy artifacts")
    parser.add_argument("--run-provisioning", action="store_true", help="Run repo-only or environment reapply workflow")
    parser.add_argument("--approve", action="store_true", help="Allow approved apply through the environment orchestrator")
    parser.add_argument("--json", action="store_true", help="Print the watcher summary as JSON")
    args = parser.parse_args()

    env_config = _environment_dynamic_peer_ip_config(repo_root, args.environment)
    request_roots = [Path(value) for value in args.customer_request_root]
    request_roots.extend(_environment_request_roots(repo_root, args.environment))
    request_paths = _discover_request_paths(
        [Path(value) for value in args.customer_request],
        request_roots,
    )
    blocked_customers = _environment_blocked_customers(repo_root, args.environment)
    environment_access_method = str(env_config.get("environment_access_method") or "").strip()
    default_reapply_mode = "remove_reapply" if environment_access_method == "ssh" else "deploy_only"
    reapply_policy = env_config.get("reapply") or {}
    reapply_mode_override = str(reapply_policy.get("mode") or default_reapply_mode).strip()
    watches, request_errors = _load_customer_watches(
        request_paths,
        blocked_customers=blocked_customers,
        reapply_mode_override=reapply_mode_override,
    )

    state_file = (
        Path(args.state_file).resolve()
        if args.state_file
        else (repo_root / str(env_config.get("state_root") or "build/dynamic-peer-ip-watcher/state") / "state.json").resolve()
    )
    out_dir = (
        Path(args.out_dir).resolve()
        if args.out_dir
        else (repo_root / str(env_config.get("output_root") or "build/dynamic-peer-ip-watcher/out")).resolve()
    )
    package_root = (
        Path(args.package_root).resolve()
        if args.package_root
        else (repo_root / str(env_config.get("package_root") or "build/dynamic-peer-ip-watcher/packages")).resolve()
    )
    state = _load_json(state_file)
    source_doc = env_config.get("source") or {}
    source_type = str(source_doc.get("type") or "").strip()
    environment_region = str(env_config.get("environment_region") or "").strip()

    if not source_type:
        summary = _build_summary(
            repo_root=repo_root,
            watches=watches,
            request_errors=request_errors + [{"request": "", "error": "dynamic_peer_ip_watcher.source.type is required"}],
            state_file=state_file,
            out_dir=out_dir,
            package_root=package_root,
            loop_result={"detected": [], "ignored": []},
            deployment_environment=args.environment,
            approve=bool(args.approve),
        )
        if args.json:
            print(json.dumps(summary, indent=2, sort_keys=True))
        else:
            print("Dynamic peer IP watcher: blocked")
        return 1

    file_records: dict[str, dict[str, Any]] | None = None
    if source_type == "json_file":
        source_path = str(source_doc.get("path") or "").strip()
        if not source_path:
            raise SystemExit("dynamic_peer_ip_watcher.source.path is required for json_file mode")
        registry_path = Path(source_path)
        if not registry_path.is_absolute():
            registry_path = (repo_root / registry_path).resolve()
        file_records = _registry_records_from_file(registry_path)

    observations_dir = out_dir / "observations"
    detected: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []
    planned_keys = set(state.setdefault("planned_idempotency_keys", []))

    for watch in watches.values():
        active_lock = read_lock(repo_root, watch.name)
        if is_lock_active(active_lock):
            ignored.append(
                {
                    "reason": "customer_operation_lock_active",
                    "customer_name": watch.name,
                    "lock": active_lock,
                }
            )
            continue

        try:
            if source_type == "dynamodb_table":
                registry_record = _fetch_registry_record_dynamodb(
                    watch,
                    repo_root=repo_root,
                    source_doc=source_doc,
                    environment_region=environment_region,
                )
            elif source_type == "json_file":
                raw_record = (file_records or {}).get(watch.serial_number)
                if raw_record is None:
                    registry_record = None
                else:
                    raw_with_serial = dict(raw_record)
                    raw_with_serial.setdefault(watch.serial_number_attribute, watch.serial_number)
                    registry_record = normalize_device_registry_record(
                        raw_with_serial,
                        serial_number=watch.serial_number,
                        serial_number_attribute=watch.serial_number_attribute,
                        current_ip_attribute=watch.current_ip_attribute,
                        last_updated_attribute=watch.last_updated_attribute,
                    )
                    registry_record["registry_table"] = str(source_doc.get("path") or "").strip()
            else:
                raise ValueError(f"unsupported dynamic peer IP source.type: {source_type}")
        except Exception as exc:
            ignored.append(
                {
                    "reason": "registry_lookup_failed",
                    "customer_name": watch.name,
                    "serial_number": watch.serial_number,
                    "error": str(exc),
                }
            )
            continue

        if registry_record is None:
            ignored.append(
                {
                    "reason": "device_registry_record_missing",
                    "customer_name": watch.name,
                    "serial_number": watch.serial_number,
                }
            )
            continue

        cstate = _customer_state(state, watch)
        cstate["last_registry_peer_ip"] = str(registry_record["current_ip"])
        cstate["last_registry_updated_at"] = str(registry_record.get("last_updated") or "")
        previous_peer = str(cstate.get("current_peer_ip") or watch.request_peer_ip).strip()
        if str(registry_record["current_ip"]) == previous_peer:
            continue

        change_event = normalize_dynamic_peer_ip_event(
            _build_change_event(watch=watch, customer_state=cstate, registry_record=registry_record),
            default_customer_name=watch.name,
            default_serial_number=watch.serial_number,
        )
        idempotency_key = build_dynamic_peer_ip_change_idempotency_key(change_event)
        observation_path = observations_dir / watch.name / f"{idempotency_key[:12]}.json"
        if idempotency_key in planned_keys:
            if not observation_path.exists():
                _remove_planned_idempotency_key(
                    state_keys=planned_keys,
                    customer_state=cstate,
                    idempotency_key=idempotency_key,
                )
            else:
                ignored.append(
                    {
                        "reason": "already_detected",
                        "customer_name": watch.name,
                        "idempotency_key": idempotency_key,
                        "observation": str(observation_path),
                    }
                )
                continue

        change_event["event_id"] = f"{watch.name}-{idempotency_key[:12]}"
        _write_json(observation_path, change_event)
        planned_keys.add(idempotency_key)
        cstate.setdefault("planned_idempotency_keys", []).append(idempotency_key)

        provisioning: dict[str, Any] | None = None
        if args.run_provisioning:
            provisioning = _run_customer_flow(
                repo_root=repo_root,
                watch=watch,
                observation_path=observation_path,
                package_root=package_root,
                deployment_environment=args.environment,
                approve=bool(args.approve),
            )
            if _provisioning_failed(provisioning):
                _remove_planned_idempotency_key(
                    state_keys=planned_keys,
                    customer_state=cstate,
                    idempotency_key=idempotency_key,
                )
            else:
                cstate["current_peer_ip"] = str(registry_record["current_ip"])
                cstate["last_applied_at"] = _utc_now()

        detected.append(
            {
                "customer_name": watch.name,
                "serial_number": watch.serial_number,
                "previous_peer": previous_peer,
                "observed_peer": str(registry_record["current_ip"]),
                "idempotency_key": idempotency_key,
                "observation": str(observation_path),
                "run_provisioning": bool(args.run_provisioning),
                "provisioning": provisioning,
            }
        )

    state["planned_idempotency_keys"] = sorted(planned_keys)
    _write_json(state_file, state)
    summary = _build_summary(
        repo_root=repo_root,
        watches=watches,
        request_errors=request_errors,
        state_file=state_file,
        out_dir=out_dir,
        package_root=package_root,
        loop_result={"detected": detected, "ignored": ignored},
        deployment_environment=args.environment,
        approve=bool(args.approve),
    )
    _write_json(out_dir / "watch-summary.json", summary)

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(
            f"Dynamic peer IP watcher: detected={summary['detected_count']} ignored={summary['ignored_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
