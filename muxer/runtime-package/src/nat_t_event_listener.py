#!/usr/bin/env python3
"""Emit RPDB NAT-T observation events from passive muxer packet capture.

This listener is intentionally passive. It does not program firewall state and
does not call iptables. Runtime steering stays in nftables/RPDB; this process
only turns observed UDP/500 and UDP/4500 packets into JSONL events that the
control-plane watcher can consume.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml


DEFAULT_CONFIG = Path("/etc/muxer/config/muxer.yaml")
DEFAULT_EVENT_LOG = Path("/var/log/rpdb/muxer-events.jsonl")
DEFAULT_BPF_FILTER = "udp and (port 500 or port 4500)"
TCPDUMP_IP_RE = re.compile(r"(?:^|\s)IP\s+(?P<src>\S+)\s+>\s+(?P<dst>[^:]+):")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def write_jsonl(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
        handle.flush()


def _safe_ip(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return ""


def _local_addresses(config: dict[str, Any], explicit: list[str]) -> set[str]:
    interfaces = config.get("interfaces") or {}
    candidates = [
        config.get("public_ip"),
        interfaces.get("public_private_ip"),
        interfaces.get("inside_ip"),
        config.get("backend_underlay_ip"),
        *explicit,
    ]
    output: set[str] = set()
    for candidate in candidates:
        parsed = _safe_ip(candidate)
        if parsed:
            output.add(parsed)
    return output


def _resolve_interface(config: dict[str, Any], requested: str) -> str:
    interfaces = config.get("interfaces") or {}
    value = str(requested or "").strip()
    if value and value in interfaces:
        return str(interfaces[value]).strip()
    if value:
        return value
    return str(interfaces.get("public_if") or "eth0").strip()


def _split_endpoint(endpoint: str) -> Optional[tuple[str, int]]:
    cleaned = endpoint.strip().rstrip(":").rstrip(",")
    if "." not in cleaned:
        return None
    address, port_text = cleaned.rsplit(".", 1)
    try:
        ip_text = str(ipaddress.ip_address(address))
        port = int(port_text)
    except ValueError:
        return None
    return ip_text, port


def parse_tcpdump_line(
    line: str,
    *,
    interface: str,
    local_addresses: set[str],
) -> Optional[dict[str, Any]]:
    match = TCPDUMP_IP_RE.search(line.strip())
    if not match:
        return None
    src = _split_endpoint(match.group("src"))
    dst = _split_endpoint(match.group("dst"))
    if src is None or dst is None:
        return None

    src_ip, src_port = src
    dst_ip, dst_port = dst
    if dst_port not in {500, 4500}:
        return None
    if src_ip in local_addresses:
        return None

    return {
        "schema_version": 1,
        "source": "rpdb-muxer-nat-t-listener",
        "observed_at": utc_now(),
        "observed_peer": src_ip,
        "observed_protocol": "udp",
        "observed_dport": dst_port,
        "observed_source_port": src_port,
        "destination_ip": dst_ip,
        "destination_port": dst_port,
        "interface": interface,
        "raw": line.strip(),
    }


def _tcpdump_path(config: dict[str, Any], override: str) -> str:
    listener_cfg = config.get("nat_t_listener") or {}
    requested = str(override or listener_cfg.get("tcpdump_path") or "").strip()
    if requested:
        return requested
    return shutil.which("tcpdump") or "/usr/sbin/tcpdump"


def _listener_config(args: argparse.Namespace) -> dict[str, Any]:
    config = load_yaml(Path(args.config))
    listener_cfg = config.get("nat_t_listener") or {}
    requested_interface = str(
        args.interface
        or listener_cfg.get("capture_interface")
        or listener_cfg.get("interface")
        or "public_if"
    )
    event_log = Path(str(args.event_log or listener_cfg.get("event_log") or DEFAULT_EVENT_LOG))
    bpf_filter = str(args.bpf_filter or listener_cfg.get("bpf_filter") or DEFAULT_BPF_FILTER)
    return {
        "config": config,
        "interface": _resolve_interface(config, requested_interface),
        "event_log": event_log,
        "bpf_filter": bpf_filter,
        "tcpdump_path": _tcpdump_path(config, args.tcpdump_path),
        "local_addresses": _local_addresses(config, list(args.local_address or [])),
        "inbound_only": bool(args.inbound_only or listener_cfg.get("inbound_only", False)),
    }


def process_input_file(
    *,
    input_file: Path,
    event_log: Path,
    interface: str,
    local_addresses: set[str],
) -> dict[str, Any]:
    emitted = 0
    ignored = 0
    for line in input_file.read_text(encoding="utf-8").splitlines():
        event = parse_tcpdump_line(line, interface=interface, local_addresses=local_addresses)
        if event is None:
            ignored += 1
            continue
        write_jsonl(event_log, event)
        emitted += 1
    return {
        "schema_version": 1,
        "action": "nat_t_event_listener_process_input",
        "input_file": str(input_file),
        "event_log": str(event_log),
        "emitted": emitted,
        "ignored": ignored,
    }


def run_listener(settings: dict[str, Any], *, stderr_log: Optional[Path]) -> int:
    command = [
        str(settings["tcpdump_path"]),
        "-l",
        "-nn",
        "-tttt",
    ]
    if settings["inbound_only"]:
        command.extend(["-Q", "in"])
    command.extend(["-i", str(settings["interface"]), str(settings["bpf_filter"])])

    event_log = Path(settings["event_log"])
    event_log.parent.mkdir(parents=True, exist_ok=True)

    stderr_handle = None
    if stderr_log is not None:
        stderr_log.parent.mkdir(parents=True, exist_ok=True)
        stderr_handle = stderr_log.open("ab")

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=stderr_handle or subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )

    def stop(_signum: int, _frame: Any) -> None:
        if process.poll() is None:
            process.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    try:
        assert process.stdout is not None
        for line in process.stdout:
            event = parse_tcpdump_line(
                line,
                interface=str(settings["interface"]),
                local_addresses=set(settings["local_addresses"]),
            )
            if event is not None:
                write_jsonl(event_log, event)
    finally:
        if stderr_handle is not None:
            stderr_handle.close()
    return int(process.wait())


def self_test() -> dict[str, Any]:
    local_addresses = {"172.31.33.150", "23.20.31.151"}
    samples = [
        "2026-04-21 22:01:01.000000 IP 198.51.100.10.500 > 172.31.33.150.500: UDP, length 292",
        "2026-04-21 22:01:02.000000 IP 198.51.100.10.500 > 172.31.33.150.500: isakmp: parent_sa ikev2_init[I]",
        "2026-04-21 22:01:03.000000 IP 198.51.100.10.4500 > 172.31.33.150.4500: NONESP-encap: isakmp: child_sa ikev2_auth[I]",
        "2026-04-21 22:01:04.000000 IP 198.51.100.10.4500 > 172.31.33.150.4500: UDP-encap: ESP(spi=0x00000001,seq=0x00000001), length 108",
        "2026-04-21 22:01:05.000000 IP 172.31.33.150.4500 > 198.51.100.10.4500: UDP, length 108",
    ]
    events = [
        parse_tcpdump_line(line, interface="ens5", local_addresses=local_addresses)
        for line in samples
    ]
    emitted = [event for event in events if event is not None]
    return {
        "schema_version": 1,
        "action": "nat_t_event_listener_self_test",
        "valid": len(emitted) == 4 and [event["observed_dport"] for event in emitted] == [500, 500, 4500, 4500],
        "emitted_count": len(emitted),
        "ignored_local_source": events[4] is None,
        "observed_dports": [event["observed_dport"] for event in emitted],
        "uses_iptables": False,
        "capture_source": "tcpdump-passive",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Emit RPDB NAT-T muxer events as JSONL.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Muxer runtime config path")
    parser.add_argument("--interface", help="Capture interface or interface key from muxer.yaml")
    parser.add_argument("--event-log", help="JSONL output file for observed events")
    parser.add_argument("--bpf-filter", help="tcpdump BPF filter")
    parser.add_argument("--tcpdump-path", default="", help="Path to tcpdump binary")
    parser.add_argument("--stderr-log", default="/var/log/rpdb/nat-t-listener.tcpdump.log")
    parser.add_argument("--local-address", action="append", default=[], help="Local IP to ignore as source")
    parser.add_argument("--inbound-only", action="store_true", help="Pass -Q in to tcpdump on Linux")
    parser.add_argument("--input-file", help="Parse an existing tcpdump text file and exit")
    parser.add_argument("--self-test", action="store_true", help="Run parser self-test and exit")
    parser.add_argument("--json", action="store_true", help="Print JSON summary for one-shot modes")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.self_test:
        result = self_test()
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["valid"] else 1

    settings = _listener_config(args)
    if args.input_file:
        result = process_input_file(
            input_file=Path(args.input_file),
            event_log=Path(settings["event_log"]),
            interface=str(settings["interface"]),
            local_addresses=set(settings["local_addresses"]),
        )
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    stderr_log = Path(args.stderr_log) if str(args.stderr_log or "").strip() else None
    return run_listener(settings, stderr_log=stderr_log)


if __name__ == "__main__":
    raise SystemExit(main())
