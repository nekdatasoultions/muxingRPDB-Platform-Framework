#!/usr/bin/env python
"""Detect NAT-T from muxer logs and trigger repo-only promotion packaging."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muxerlib.dynamic_provisioning import (
    build_nat_t_observation_idempotency_key,
    normalize_nat_t_observation_event,
    validate_dynamic_initial_request,
)


IPTABLES_FIELD_RE = re.compile(r"\b(?P<key>[A-Z]+)=(?P<value>[^ ]+)")


@dataclass(frozen=True)
class CustomerWatch:
    name: str
    peer_ip: str
    request_path: Path
    confirmation_packets: int
    require_initial_udp500_observation: bool
    observation_window_seconds: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_event_time(value: str) -> datetime | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": 1,
            "customers": {},
            "log_offsets": {},
            "planned_idempotency_keys": [],
        }
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _discover_request_paths(paths: Iterable[Path], roots: Iterable[Path]) -> list[Path]:
    discovered: dict[str, Path] = {}
    for path in paths:
        resolved = path.resolve()
        if resolved.is_file():
            discovered[str(resolved)] = resolved
    for root in roots:
        resolved_root = root.resolve()
        if not resolved_root.exists():
            continue
        if resolved_root.is_file():
            discovered[str(resolved_root)] = resolved_root
            continue
        for candidate in sorted(resolved_root.rglob("*.yaml")):
            if candidate.is_file():
                discovered[str(candidate.resolve())] = candidate.resolve()
    return [discovered[key] for key in sorted(discovered)]


def _load_customer_watches(request_paths: list[Path]) -> tuple[dict[str, CustomerWatch], list[dict[str, str]]]:
    watches: dict[str, CustomerWatch] = {}
    errors: list[dict[str, str]] = []
    seen_peers: dict[str, str] = {}
    for request_path in request_paths:
        try:
            doc = _load_yaml(request_path)
            customer = doc.get("customer") or {}
            customer_name = str(customer.get("name") or "").strip()
            peer_ip = str(((customer.get("peer") or {}).get("public_ip") or "")).strip()
            if not customer_name or not peer_ip:
                continue
            ipaddress.ip_address(peer_ip)
            dynamic = validate_dynamic_initial_request(doc)
            if not dynamic.get("enabled"):
                continue
            previous_customer = seen_peers.get(peer_ip)
            if previous_customer and previous_customer != customer_name:
                errors.append(
                    {
                        "request": str(request_path),
                        "error": f"peer {peer_ip} is shared by {previous_customer} and {customer_name}",
                    }
                )
                continue
            seen_peers[peer_ip] = customer_name
            trigger = dynamic.get("trigger") or {}
            watches[customer_name] = CustomerWatch(
                name=customer_name,
                peer_ip=peer_ip,
                request_path=request_path,
                confirmation_packets=int(trigger.get("confirmation_packets") or 1),
                require_initial_udp500_observation=bool(
                    trigger.get("require_initial_udp500_observation", True)
                ),
                observation_window_seconds=int(trigger.get("observation_window_seconds") or 300),
            )
        except Exception as exc:
            errors.append({"request": str(request_path), "error": str(exc)})
    return watches, errors


def _parse_json_event(line: str) -> dict[str, Any] | None:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    peer = (
        raw.get("observed_peer")
        or raw.get("observed_peer_ip")
        or raw.get("peer_ip")
        or raw.get("src")
        or raw.get("source_ip")
        or raw.get("SRC")
    )
    dport = raw.get("observed_dport") or raw.get("destination_port") or raw.get("dport") or raw.get("DPT")
    protocol = raw.get("observed_protocol") or raw.get("protocol") or raw.get("PROTO") or "udp"
    if not peer or dport in (None, ""):
        return None
    return {
        "customer_name": str(raw.get("customer_name") or "").strip(),
        "peer": str(peer).strip(),
        "protocol": str(protocol).strip().lower(),
        "dport": int(dport),
        "observed_at": str(raw.get("observed_at") or raw.get("timestamp") or "").strip(),
        "raw": raw,
    }


def _parse_iptables_event(line: str) -> dict[str, Any] | None:
    fields = {match.group("key"): match.group("value") for match in IPTABLES_FIELD_RE.finditer(line)}
    peer = fields.get("SRC")
    dport = fields.get("DPT")
    protocol = fields.get("PROTO") or "udp"
    if not peer or not dport:
        return None
    return {
        "customer_name": "",
        "peer": peer.strip(),
        "protocol": protocol.strip().lower(),
        "dport": int(dport),
        "observed_at": "",
        "raw": line,
    }


def _parse_log_event(line: str) -> dict[str, Any] | None:
    stripped = line.strip().lstrip("\ufeff")
    if not stripped:
        return None
    event = _parse_json_event(stripped) if stripped.startswith("{") else None
    if event is None:
        event = _parse_iptables_event(stripped)
    if event is None:
        return None
    try:
        event["peer"] = str(ipaddress.ip_address(str(event["peer"])))
    except ValueError:
        return None
    if event["protocol"] != "udp" or int(event["dport"]) not in {500, 4500}:
        return None
    return event


def _read_new_lines(log_file: Path, state: dict[str, Any], *, reprocess: bool) -> list[str]:
    offsets = state.setdefault("log_offsets", {})
    key = str(log_file.resolve())
    offset = 0 if reprocess else int(offsets.get(key) or 0)
    lines: list[str] = []
    with log_file.open("r", encoding="utf-8") as handle:
        handle.seek(offset)
        lines = handle.readlines()
        offsets[key] = handle.tell()
    return lines


def _customer_state(state: dict[str, Any], watch: CustomerWatch) -> dict[str, Any]:
    customers = state.setdefault("customers", {})
    return customers.setdefault(
        watch.name,
        {
            "peer_ip": watch.peer_ip,
            "request": str(watch.request_path),
            "udp500_observed": False,
            "udp500_count": 0,
            "udp4500_count": 0,
            "last_udp500_observed_at": "",
            "last_udp4500_observed_at": "",
            "planned_idempotency_keys": [],
        },
    )


def _match_watch(
    event: dict[str, Any],
    *,
    watches: dict[str, CustomerWatch],
    watches_by_peer: dict[str, CustomerWatch],
) -> CustomerWatch | None:
    if event.get("customer_name"):
        watch = watches.get(str(event["customer_name"]))
        if watch and watch.peer_ip == event["peer"]:
            return watch
        return None
    return watches_by_peer.get(str(event["peer"]))


def _build_observation_event(
    *,
    watch: CustomerWatch,
    customer_state: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    observed_at = str(event.get("observed_at") or "").strip() or _utc_now()
    return {
        "schema_version": 1,
        "event_id": f"{watch.name}-auto-udp4500-{observed_at.replace(':', '').replace('-', '')}",
        "customer_name": watch.name,
        "observed_peer": watch.peer_ip,
        "observed_protocol": "udp",
        "observed_dport": 4500,
        "initial_udp500_observed": bool(customer_state.get("udp500_observed")),
        "packet_count": int(customer_state.get("udp4500_count") or 1),
        "observed_at": observed_at,
        "source": "nat-t-log-watcher",
    }


def _run_end_to_end_provisioning(
    *,
    repo_root: Path,
    watch: CustomerWatch,
    observation_path: Path,
    package_root: Path,
) -> dict[str, Any]:
    package_dir = package_root / watch.name
    command = [
        sys.executable,
        "muxer/scripts/provision_customer_end_to_end.py",
        str(watch.request_path),
        "--observation",
        str(observation_path),
        "--out-dir",
        str(package_dir),
        "--json",
    ]
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


def _process_events(
    *,
    repo_root: Path,
    watches: dict[str, CustomerWatch],
    log_files: list[Path],
    state: dict[str, Any],
    out_dir: Path,
    package_root: Path,
    run_provisioning: bool,
    reprocess: bool,
) -> dict[str, Any]:
    watches_by_peer = {watch.peer_ip: watch for watch in watches.values()}
    observations_dir = out_dir / "observations"
    detected: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []
    planned_keys = set(state.setdefault("planned_idempotency_keys", []))

    for log_file in log_files:
        for line in _read_new_lines(log_file, state, reprocess=reprocess):
            event = _parse_log_event(line)
            if event is None:
                continue
            watch = _match_watch(event, watches=watches, watches_by_peer=watches_by_peer)
            if watch is None:
                ignored.append({"reason": "no_matching_dynamic_customer", "event": event})
                continue

            cstate = _customer_state(state, watch)
            observed_at = str(event.get("observed_at") or "").strip() or _utc_now()
            if int(event["dport"]) == 500:
                cstate["udp500_observed"] = True
                cstate["udp500_count"] = int(cstate.get("udp500_count") or 0) + 1
                cstate["last_udp500_observed_at"] = observed_at
                continue

            cstate["udp4500_count"] = int(cstate.get("udp4500_count") or 0) + 1
            cstate["last_udp4500_observed_at"] = observed_at
            if watch.require_initial_udp500_observation and not cstate.get("udp500_observed"):
                ignored.append({"reason": "udp500_not_observed_first", "customer_name": watch.name, "event": event})
                continue
            if watch.require_initial_udp500_observation:
                first_seen = _parse_event_time(str(cstate.get("last_udp500_observed_at") or ""))
                current_seen = _parse_event_time(observed_at)
                if first_seen and current_seen:
                    delta_seconds = (current_seen - first_seen).total_seconds()
                    if delta_seconds < 0 or delta_seconds > watch.observation_window_seconds:
                        ignored.append(
                            {
                                "reason": "observation_window_not_met",
                                "customer_name": watch.name,
                                "window_seconds": watch.observation_window_seconds,
                                "delta_seconds": delta_seconds,
                                "event": event,
                            }
                        )
                        continue
            if int(cstate.get("udp4500_count") or 0) < watch.confirmation_packets:
                ignored.append({"reason": "confirmation_threshold_not_met", "customer_name": watch.name, "event": event})
                continue

            observation = normalize_nat_t_observation_event(
                _build_observation_event(watch=watch, customer_state=cstate, event=event),
                default_customer_name=watch.name,
            )
            idempotency_key = build_nat_t_observation_idempotency_key(observation)
            observation_path = observations_dir / watch.name / f"{idempotency_key[:12]}.json"
            if idempotency_key in planned_keys:
                ignored.append(
                    {
                        "reason": "already_detected",
                        "customer_name": watch.name,
                        "idempotency_key": idempotency_key,
                        "observation": str(observation_path),
                    }
                )
                continue

            observation["event_id"] = f"{watch.name}-{idempotency_key[:12]}"
            _write_json(observation_path, observation)
            planned_keys.add(idempotency_key)
            cstate.setdefault("planned_idempotency_keys", []).append(idempotency_key)
            provisioning: dict[str, Any] | None = None
            if run_provisioning:
                provisioning = _run_end_to_end_provisioning(
                    repo_root=repo_root,
                    watch=watch,
                    observation_path=observation_path,
                    package_root=package_root,
                )
            detected.append(
                {
                    "customer_name": watch.name,
                    "peer_ip": watch.peer_ip,
                    "idempotency_key": idempotency_key,
                    "observation": str(observation_path),
                    "run_provisioning": run_provisioning,
                    "provisioning": provisioning,
                }
            )

    state["planned_idempotency_keys"] = sorted(planned_keys)
    return {
        "detected": detected,
        "ignored": ignored,
    }


def _build_summary(
    *,
    repo_root: Path,
    watches: dict[str, CustomerWatch],
    request_errors: list[dict[str, str]],
    state_file: Path,
    out_dir: Path,
    package_root: Path,
    loop_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "action": "watch_nat_t_logs",
        "live_apply": False,
        "generated_at": _utc_now(),
        "state_file": str(state_file),
        "out_dir": str(out_dir),
        "package_root": str(package_root),
        "watched_customers": {
            name: {
                "peer_ip": watch.peer_ip,
                "request": str(watch.request_path),
                "confirmation_packets": watch.confirmation_packets,
                "require_initial_udp500_observation": watch.require_initial_udp500_observation,
                "observation_window_seconds": watch.observation_window_seconds,
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
    muxer_dir = repo_root / "muxer"

    parser = argparse.ArgumentParser(
        description=(
            "Watch muxer NAT-T log events, correlate them to dynamic customer "
            "requests, write observation files, and optionally run repo-only "
            "promotion provisioning."
        )
    )
    parser.add_argument("--log-file", action="append", required=True, help="Muxer log file or JSONL event file")
    parser.add_argument("--customer-request", action="append", default=[], help="Customer request YAML to watch")
    parser.add_argument(
        "--customer-request-root",
        action="append",
        default=[],
        help="Root containing customer request YAMLs to watch",
    )
    parser.add_argument(
        "--state-file",
        default=str(repo_root / "build" / "nat-t-log-watcher" / "state.json"),
        help="State file tracking log offsets and already planned observations",
    )
    parser.add_argument(
        "--out-dir",
        default=str(repo_root / "build" / "nat-t-log-watcher"),
        help="Output directory for observation events and watcher summary",
    )
    parser.add_argument(
        "--package-root",
        default=str(repo_root / "build" / "customer-provisioning"),
        help="Package root used when --run-provisioning is enabled",
    )
    parser.add_argument("--run-provisioning", action="store_true", help="Run one-file provisioning after detection")
    parser.add_argument("--reprocess", action="store_true", help="Read logs from the beginning instead of stored offsets")
    parser.add_argument("--follow", action="store_true", help="Continue polling log files instead of exiting")
    parser.add_argument("--poll-interval-seconds", type=float, default=5.0, help="Polling interval for --follow")
    parser.add_argument("--json", action="store_true", help="Print watcher summary as JSON")
    args = parser.parse_args()

    log_files = [Path(path).resolve() for path in args.log_file]
    request_paths = _discover_request_paths(
        [Path(path) for path in args.customer_request],
        [Path(path) for path in args.customer_request_root],
    )
    if not request_paths:
        request_paths = _discover_request_paths(
            [],
            [
                muxer_dir / "config" / "customer-requests" / "examples",
                muxer_dir / "config" / "customer-requests" / "migrated",
            ],
        )
    watches, request_errors = _load_customer_watches(request_paths)
    state_file = Path(args.state_file).resolve()
    out_dir = Path(args.out_dir).resolve()
    package_root = Path(args.package_root).resolve()

    while True:
        state = _load_json(state_file)
        loop_result = _process_events(
            repo_root=repo_root,
            watches=watches,
            log_files=log_files,
            state=state,
            out_dir=out_dir,
            package_root=package_root,
            run_provisioning=bool(args.run_provisioning),
            reprocess=bool(args.reprocess),
        )
        _write_json(state_file, state)
        summary = _build_summary(
            repo_root=repo_root,
            watches=watches,
            request_errors=request_errors,
            state_file=state_file,
            out_dir=out_dir,
            package_root=package_root,
            loop_result=loop_result,
        )
        _write_json(out_dir / "watch-summary.json", summary)
        if args.json:
            print(json.dumps(summary, indent=2, sort_keys=True))
        elif loop_result["detected"]:
            for item in loop_result["detected"]:
                print(f"Detected NAT-T for {item['customer_name']}: {item['observation']}")
        if not args.follow:
            return 0
        time.sleep(max(float(args.poll_interval_seconds), 0.1))


if __name__ == "__main__":
    raise SystemExit(main())
