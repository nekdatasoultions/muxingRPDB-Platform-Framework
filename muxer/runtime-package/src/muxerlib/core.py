#!/usr/bin/env python3
"""Core primitives for muxer operations."""

from __future__ import annotations

import ipaddress
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import yaml

BASE = Path("/etc/muxer")
CFG_GLOBAL = BASE / "config" / "muxer.yaml"
CFG_DIR = BASE / "config" / "tunnels.d"


def sh(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, capture_output=True)


def must(cmd: List[str]) -> None:
    sh(cmd, check=True)


def out(cmd: List[str]) -> str:
    return subprocess.check_output(cmd, text=True)


def load_yaml(path: Path) -> Dict[str, Any]:
    return yaml.safe_load(path.read_text())


def norm_int(value: Any) -> int:
    return int(str(value), 0)


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    raw = str(value).strip().lower()
    return raw in {"1", "true", "yes", "on", "enable", "enabled"}


def parse_int(value: Any, default: int) -> int:
    if value is None:
        return default
    return int(str(value), 0)


def nfqueue_bridge_settings(global_cfg: Dict[str, Any]) -> tuple[bool, int, int, bool]:
    exp = global_cfg.get("experimental", {}) or {}
    bridge = exp.get("nfqueue_ike_bridge", {}) or {}
    enabled = parse_bool(bridge.get("enabled", False), False)
    queue_in = parse_int(bridge.get("queue_in", 2101), 2101)
    queue_out = parse_int(bridge.get("queue_out", 2102), 2102)
    queue_bypass = parse_bool(bridge.get("queue_bypass", True), True)
    return enabled, queue_in, queue_out, queue_bypass


def natd_dpi_settings(global_cfg: Dict[str, Any]) -> tuple[bool, int, int, bool]:
    exp = global_cfg.get("experimental", {}) or {}
    natd = exp.get("natd_dpi_rewrite", {}) or {}
    enabled = parse_bool(natd.get("enabled", False), False)
    queue_in = parse_int(natd.get("queue_in", 2111), 2111)
    queue_out = parse_int(natd.get("queue_out", 2112), 2112)
    queue_bypass = parse_bool(natd.get("queue_bypass", True), True)
    return enabled, queue_in, queue_out, queue_bypass


def iface_primary_ipv4(ifname: str) -> str:
    lines = out(["ip", "-o", "-4", "addr", "show", "dev", ifname, "scope", "global"]).splitlines()
    for line in lines:
        parts = line.split()
        if "inet" in parts:
            idx = parts.index("inet")
            if idx + 1 < len(parts):
                cidr = parts[idx + 1]
                return str(ipaddress.ip_interface(cidr).ip)
    raise SystemExit(f"No global IPv4 found on interface {ifname}")


def ensure_local_ipv4(ifname: str, ip_text: str, prefix_len: int = 32) -> None:
    want_ip = str(ipaddress.ip_address(ip_text))
    lines = out(["ip", "-o", "-4", "addr", "show", "dev", ifname]).splitlines()
    for line in lines:
        parts = line.split()
        if "inet" not in parts:
            continue
        idx = parts.index("inet")
        if idx + 1 >= len(parts):
            continue
        have_ip = str(ipaddress.ip_interface(parts[idx + 1]).ip)
        if have_ip == want_ip:
            return
    must(["ip", "addr", "add", f"{want_ip}/{prefix_len}", "dev", ifname])


def remove_local_ipv4(ifname: str, ip_text: str) -> None:
    want_ip = str(ipaddress.ip_address(ip_text))
    lines = out(["ip", "-o", "-4", "addr", "show", "dev", ifname]).splitlines()
    for line in lines:
        parts = line.split()
        if "inet" not in parts:
            continue
        idx = parts.index("inet")
        if idx + 1 >= len(parts):
            continue
        cidr = parts[idx + 1]
        have_ip = str(ipaddress.ip_interface(cidr).ip)
        if have_ip == want_ip:
            must(["ip", "addr", "del", cidr, "dev", ifname])


def ensure_sysctl() -> None:
    must(["sysctl", "-w", "net.ipv4.ip_forward=1"])
    must(["sysctl", "-w", "net.ipv4.conf.all.rp_filter=0"])
    must(["sysctl", "-w", "net.ipv4.conf.default.rp_filter=0"])


def ensure_chain(table: str, chain: str) -> None:
    result = sh(["iptables", "-t", table, "-S", chain], check=False)
    if result.returncode != 0:
        must(["iptables", "-t", table, "-N", chain])


def ensure_jump(table: str, parent_chain: str, chain: str, position: int = 1) -> None:
    rules = out(["iptables", "-t", table, "-S", parent_chain]).splitlines()
    want = f"-A {parent_chain} -j {chain}"
    if not any(want in rule for rule in rules):
        must(["iptables", "-t", table, "-I", parent_chain, str(position), "-j", chain])


def flush_chain(table: str, chain: str) -> None:
    sh(["iptables", "-t", table, "-F", chain], check=False)


def delete_chain(table: str, chain: str) -> None:
    sh(["iptables", "-t", table, "-F", chain], check=False)
    sh(["iptables", "-t", table, "-X", chain], check=False)


def remove_jump(table: str, parent_chain: str, chain: str) -> None:
    while True:
        rules = out(["iptables", "-t", table, "-S", parent_chain]).splitlines()
        found = False
        for rule in rules:
            if rule.strip() == f"-A {parent_chain} -j {chain}":
                must(["iptables", "-t", table, "-D", parent_chain, "-j", chain])
                found = True
                break
        if not found:
            break


def ensure_tunnel(
    ifname: str,
    local_ul: str,
    remote_ul: str,
    overlay_ip: str,
    mode: str = "ipip",
    ttl: int = 64,
    key: int | None = None,
) -> None:
    mode = str(mode).strip().lower()
    if mode not in {"ipip", "gre"}:
        raise SystemExit(f"Unsupported tunnel mode '{mode}' for interface {ifname}")

    if key is not None and mode != "gre":
        raise SystemExit(f"Tunnel key is supported only for GRE mode (interface {ifname})")

    tunnels = out(["ip", "-d", "tunnel", "show"]).splitlines()
    current = ""
    for tunnel in tunnels:
        if tunnel.startswith(f"{ifname}:"):
            current = tunnel
            break

    if current:
        want_local = f"local {local_ul}"
        want_remote = f"remote {remote_ul}"
        want_mode = "ip/ip" if mode == "ipip" else "gre/ip"
        mode_ok = want_mode in current
        key_ok = True
        if mode == "gre":
            if key is None:
                key_ok = " key " not in f" {current} "
            else:
                key_ok = f" key {key}" in current
        if not mode_ok or not key_ok or want_local not in current or want_remote not in current:
            must(["ip", "tunnel", "del", ifname])
            current = ""

    if not current:
        cmd = ["ip", "tunnel", "add", ifname, "mode", mode, "local", local_ul, "remote", remote_ul, "ttl", str(ttl)]
        if mode == "gre" and key is not None:
            cmd.extend(["key", str(key)])
        must(cmd)

    must(["ip", "link", "set", ifname, "up"])
    must(["ip", "addr", "replace", overlay_ip, "dev", ifname])


def ensure_policy(mark_hex: str, table_id: int, ifname: str) -> None:
    must(["ip", "route", "replace", "default", "dev", ifname, "table", str(table_id)])
    rules = out(["ip", "rule", "show"]).splitlines()
    want = f"fwmark {mark_hex} lookup {table_id}"
    if not any(want in rule for rule in rules):
        must(["ip", "rule", "add", "fwmark", mark_hex, "lookup", str(table_id)])
