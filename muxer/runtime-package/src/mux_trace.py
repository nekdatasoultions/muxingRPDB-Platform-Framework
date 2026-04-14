#!/usr/bin/env python3
"""
mux_trace.py

Continuous muxer tracing:
- Rotating pcap captures on public and customer IPIP interfaces.
- Periodic snapshots of iptables counters, policy rules, and tunnel stats.
"""

import argparse
import datetime as dt
import ipaddress
import logging
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence, Set, Tuple

import yaml

from muxerlib.variables import load_modules as load_customer_modules

BASE = Path("/etc/muxer")
CFG_GLOBAL = BASE / "config" / "muxer.yaml"


def load_yaml(path: Path) -> Dict[str, Any]:
    return yaml.safe_load(path.read_text())


def parse_bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    return str(v).strip().lower() in {"1", "true", "yes", "on", "enable", "enabled"}


def parse_int(v: Any, default: int) -> int:
    if v is None:
        return default
    return int(str(v), 0)


def trace_settings(global_cfg: Dict[str, Any]) -> Dict[str, Any]:
    exp = global_cfg.get("experimental", {}) or {}
    trace = exp.get("trace", {}) or {}
    return {
        "enabled": parse_bool(trace.get("enabled", False), False),
        "log_dir": str(trace.get("log_dir", "/var/log/muxer-trace")),
        "snapshot_interval_sec": max(5, parse_int(trace.get("snapshot_interval_sec", 15), 15)),
        "pcap_file_mb": max(1, parse_int(trace.get("pcap_file_mb", 50), 50)),
        "pcap_ring_files": max(2, parse_int(trace.get("pcap_ring_files", 16), 16)),
        "bridge_log_lines": max(0, parse_int(trace.get("bridge_log_lines", 8), 8)),
    }


def cmd_output(cmd: Sequence[str]) -> str:
    p = subprocess.run(cmd, text=True, capture_output=True)
    if p.returncode == 0:
        return p.stdout
    return f"[exit={p.returncode}] {p.stderr or p.stdout}"


def chain_exists(table: str, chain: str) -> bool:
    p = subprocess.run(["iptables", "-t", table, "-S", chain], text=True, capture_output=True)
    return p.returncode == 0


def safe_name(ifname: str) -> str:
    return ifname.replace("/", "_")


class TcpdumpProc:
    def __init__(
        self,
        ifname: str,
        filter_tokens: List[str],
        log_dir: Path,
        pcap_file_mb: int,
        pcap_ring_files: int,
        logger: logging.Logger,
    ) -> None:
        self.ifname = ifname
        self.filter_tokens = filter_tokens
        self.log_dir = log_dir
        self.pcap_file_mb = pcap_file_mb
        self.pcap_ring_files = pcap_ring_files
        self.log = logger
        self.proc: subprocess.Popen | None = None
        self.err_fh = None

    def start(self) -> None:
        if self.proc and self.proc.poll() is None:
            return
        self.stop()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        pcap_prefix = self.log_dir / f"{safe_name(self.ifname)}.pcap"
        err_path = self.log_dir / f"{safe_name(self.ifname)}.tcpdump.log"
        self.err_fh = err_path.open("ab")
        cmd = [
            "tcpdump",
            "-ni",
            self.ifname,
            "-s",
            "0",
            "-Z",
            "root",
            "-U",
            "-C",
            str(self.pcap_file_mb),
            "-W",
            str(self.pcap_ring_files),
            "-w",
            str(pcap_prefix),
        ] + self.filter_tokens
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=self.err_fh)
        self.log.info("started tcpdump on %s pid=%s", self.ifname, self.proc.pid)

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        if self.err_fh:
            self.err_fh.close()
            self.err_fh = None

    def ensure(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            self.start()


def build_peer_filter_tokens(peers: Set[str]) -> List[str]:
    proto = ["(", "udp", "port", "500", "or", "udp", "port", "4500", "or", "esp", ")"]
    if not peers:
        return proto
    host_tokens: List[str] = ["("]
    first = True
    for peer in sorted(peers):
        if not first:
            host_tokens.extend(["or"])
        host_tokens.extend(["host", peer])
        first = False
    host_tokens.append(")")
    return host_tokens + ["and"] + proto


def snapshot(
    log_path: Path,
    global_cfg: Dict[str, Any],
    ipip_ifs: List[str],
    bridge_log_lines: int,
) -> None:
    chains = global_cfg.get("iptables", {}).get("chains", {}) or {}
    mangle_chain = str(chains.get("mangle_chain", "MUXER_MANGLE"))
    mangle_post = str(chains.get("mangle_postrouting_chain", "MUXER_MANGLE_POST"))
    nat_pre = str(chains.get("nat_prerouting_chain", "MUXER_NAT_PRE"))
    nat_post = str(chains.get("nat_postrouting_chain", "MUXER_NAT_POST"))
    filter_chain = str(chains.get("filter_chain", "MUXER_FILTER"))
    input_chain = str(chains.get("input_chain", "MUXER_INPUT"))

    with log_path.open("a", encoding="utf-8") as fh:
        ts = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        fh.write(f"\n===== {ts} =====\n")
        fh.write(cmd_output(["ip", "rule", "show"]))
        fh.write(cmd_output(["ip", "route", "show", "table", "all"]))
        fh.write(cmd_output(["iptables", "-t", "mangle", "-vnL", mangle_chain]))
        fh.write(cmd_output(["iptables", "-t", "mangle", "-vnL", mangle_post]))
        fh.write(cmd_output(["iptables", "-t", "nat", "-vnL", nat_pre]))
        fh.write(cmd_output(["iptables", "-t", "nat", "-vnL", nat_post]))
        if chain_exists("filter", filter_chain):
            fh.write(cmd_output(["iptables", "-vnL", filter_chain]))
        else:
            fh.write(f"[skip] missing filter chain {filter_chain}\n")
        if chain_exists("filter", input_chain):
            fh.write(cmd_output(["iptables", "-vnL", input_chain]))
        else:
            fh.write(f"[skip] missing filter chain {input_chain}\n")
        for ifname in ipip_ifs:
            fh.write(cmd_output(["ip", "-s", "link", "show", "dev", ifname]))
        if bridge_log_lines > 0:
            fh.write(cmd_output(["journalctl", "-u", "ike-nat-bridge", "-n", str(bridge_log_lines), "--no-pager"]))
        fh.flush()


def setup_logging(level: str) -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    return logging.getLogger("mux-trace")


def main() -> None:
    ap = argparse.ArgumentParser(description="muxer pcap+counter tracing daemon")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    log = setup_logging(args.log_level)
    if not CFG_GLOBAL.exists():
        raise SystemExit(f"Missing config: {CFG_GLOBAL}")

    global_cfg = load_yaml(CFG_GLOBAL)
    settings = trace_settings(global_cfg)
    if not settings["enabled"]:
        log.info("experimental.trace.enabled=false; exiting")
        return

    overlay_pool = ipaddress.ip_network(str(global_cfg["overlay_pool"]), strict=False)
    modules = load_customer_modules(overlay_pool)
    pub_if = str(global_cfg.get("interfaces", {}).get("public_if", "ens5"))
    peers: Set[str] = set()
    ipip_ifs: List[str] = []
    for m in modules:
        peer = str(m.get("peer_ip", "")).split("/")[0].strip()
        if peer:
            peers.add(peer)
        ipip_if = str(m.get("ipip_ifname") or f"ipip-{m.get('name', '')}")
        if ipip_if and ipip_if not in ipip_ifs:
            ipip_ifs.append(ipip_if)

    log_dir = Path(str(settings["log_dir"]))
    log_dir.mkdir(parents=True, exist_ok=True)
    counters_log = log_dir / "counters.log"

    filter_tokens = build_peer_filter_tokens(peers)
    workers: List[TcpdumpProc] = []
    workers.append(
        TcpdumpProc(
            ifname=pub_if,
            filter_tokens=filter_tokens,
            log_dir=log_dir,
            pcap_file_mb=int(settings["pcap_file_mb"]),
            pcap_ring_files=int(settings["pcap_ring_files"]),
            logger=log,
        )
    )
    for ifname in ipip_ifs:
        workers.append(
            TcpdumpProc(
                ifname=ifname,
                filter_tokens=filter_tokens,
                log_dir=log_dir,
                pcap_file_mb=int(settings["pcap_file_mb"]),
                pcap_ring_files=int(settings["pcap_ring_files"]),
                logger=log,
            )
        )

    stop = {"v": False}

    def _sig(_s, _f) -> None:  # noqa: ANN001
        stop["v"] = True

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    log.info(
        "trace enabled log_dir=%s pub_if=%s ipip_ifs=%s peers=%s",
        log_dir,
        pub_if,
        ipip_ifs,
        sorted(peers),
    )

    for w in workers:
        w.start()

    interval = int(settings["snapshot_interval_sec"])
    last = 0.0

    try:
        while not stop["v"]:
            now = time.time()
            for w in workers:
                w.ensure()
            if now - last >= interval:
                snapshot(counters_log, global_cfg, ipip_ifs, int(settings["bridge_log_lines"]))
                last = now
            time.sleep(1.0)
    finally:
        for w in workers:
            w.stop()
        log.info("stopped")


if __name__ == "__main__":
    main()
