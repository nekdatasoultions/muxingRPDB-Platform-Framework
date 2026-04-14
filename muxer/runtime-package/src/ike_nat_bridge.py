#!/usr/bin/env python3
"""
ike_nat_bridge.py

Userspace NFQUEUE helper for the forced-rewrite experiment:
- Inbound customer UDP/4500 -> strip NONESP marker (0x00000000) so backend sees native IKE payload.
- Outbound backend UDP/500 -> prepend NONESP marker so customer-side NAT-T peer can parse it.
- Optional UDP/500 deep-packet rewrite of IKEv2 NAT_DETECTION_* hashes in IKE_SA_INIT.

This does not fully normalize all NAT side effects. It is an experiment bridge for strict peers.
"""

import argparse
import hashlib
import ipaddress
import logging
import signal
import struct
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml
from netfilterqueue import NetfilterQueue
from scapy.all import IP, UDP  # type: ignore

from muxerlib.variables import load_modules

BASE = Path("/etc/muxer")
CFG_GLOBAL = BASE / "config" / "muxer.yaml"

IKEV2_SA_INIT = 34
IKEV2_PAYLOAD_NOTIFY = 41
NATD_SOURCE = 16388
NATD_DEST = 16389


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


def load_runtime() -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    g = load_yaml(CFG_GLOBAL)
    overlay_pool = ipaddress.ip_network(str(g["overlay_pool"]), strict=False)
    modules = load_modules(overlay_pool, global_cfg=g)
    return g, modules


def bridge_settings(g: Dict[str, Any]) -> Dict[str, Any]:
    exp = g.get("experimental", {}) or {}
    bridge = exp.get("nfqueue_ike_bridge", {}) or {}
    natd = exp.get("natd_dpi_rewrite", {}) or {}
    return {
        "enabled": parse_bool(bridge.get("enabled", False), False),
        "queue_in": parse_int(bridge.get("queue_in", 2101), 2101),
        "queue_out": parse_int(bridge.get("queue_out", 2102), 2102),
        "queue_bypass": parse_bool(bridge.get("queue_bypass", True), True),
        "drop_nat_keepalive": parse_bool(bridge.get("drop_nat_keepalive", True), True),
        "flow_ttl_sec": parse_int(bridge.get("flow_ttl_sec", 300), 300),
        "log_interval_sec": parse_int(bridge.get("log_interval_sec", 30), 30),
        "natd_enabled": parse_bool(natd.get("enabled", False), False),
        "natd_queue_in": parse_int(natd.get("queue_in", 2111), 2111),
        "natd_queue_out": parse_int(natd.get("queue_out", 2112), 2112),
        "natd_queue_bypass": parse_bool(natd.get("queue_bypass", True), True),
        "natd_log_interval_sec": parse_int(natd.get("log_interval_sec", 30), 30),
    }


def customer_features(modules: List[Dict[str, Any]]) -> Tuple[Set[str], Dict[str, Dict[str, str]]]:
    force_peers: Set[str] = set()
    natd_peers: Dict[str, Dict[str, str]] = {}
    for m in modules:
        name = str(m.get("name", "unnamed"))
        protocols = m.get("protocols", {}) or {}
        peer = str(m.get("peer_ip", "")).split("/")[0].strip()
        if not peer:
            continue
        ipaddress.ip_address(peer)
        if parse_bool(protocols.get("force_rewrite_4500_to_500", False), False):
            force_peers.add(peer)

        natd_cfg = m.get("natd_rewrite", {}) or {}
        if parse_bool(natd_cfg.get("enabled", False), False):
            inner = str(natd_cfg.get("initiator_inner_ip", "")).strip()
            if inner:
                try:
                    ipaddress.ip_address(inner)
                except ValueError as exc:
                    raise SystemExit(f"{name}: natd_rewrite.initiator_inner_ip invalid: {inner}") from exc
            natd_peers[peer] = {"initiator_inner_ip": inner}
    return force_peers, natd_peers


def is_likely_ike(payload: bytes) -> bool:
    if len(payload) < 28:
        return False
    ver = payload[17]
    if ver not in (0x10, 0x20):
        return False
    msg_len = int.from_bytes(payload[24:28], byteorder="big")
    if msg_len < 28:
        return False
    return msg_len <= len(payload)


def natd_hash(spii: bytes, spir: bytes, ip_text: str, port: int) -> bytes:
    ip_packed = ipaddress.ip_address(ip_text).packed
    return hashlib.sha1(spii + spir + ip_packed + struct.pack("!H", int(port))).digest()


def parse_ike_header(payload: bytes) -> Optional[Dict[str, Any]]:
    if len(payload) < 28 or not is_likely_ike(payload):
        return None
    return {
        "spii": payload[0:8],
        "spir": payload[8:16],
        "next_payload": payload[16],
        "version": payload[17],
        "exchange": payload[18],
        "flags": payload[19],
        "msg_id": int.from_bytes(payload[20:24], byteorder="big"),
        "length": int.from_bytes(payload[24:28], byteorder="big"),
    }


def rewrite_natd_hashes(
    payload: bytes,
    src_ip: str,
    src_port: int,
    dst_ip: str,
    dst_port: int,
) -> Tuple[bytes, bool, Dict[str, Any]]:
    meta: Dict[str, Any] = {"parsed": False, "rewrites": 0}
    hdr = parse_ike_header(payload)
    if hdr is None:
        return payload, False, meta
    meta["parsed"] = True
    meta["spii"] = hdr["spii"]
    meta["spir"] = hdr["spir"]
    meta["msg_id"] = hdr["msg_id"]
    meta["exchange"] = hdr["exchange"]

    # NAT detection payloads are visible only in unencrypted IKE_SA_INIT (msg-id 0).
    if hdr["exchange"] != IKEV2_SA_INIT or hdr["msg_id"] != 0:
        return payload, False, meta

    want_src = natd_hash(hdr["spii"], hdr["spir"], src_ip, src_port)
    want_dst = natd_hash(hdr["spii"], hdr["spir"], dst_ip, dst_port)
    raw = bytearray(payload)
    changed = False
    rewrites = 0

    next_payload = int(hdr["next_payload"])
    off = 28
    while next_payload != 0:
        if off + 4 > len(raw):
            break
        current_payload = next_payload
        next_payload = int(raw[off])
        p_len = int.from_bytes(raw[off + 2 : off + 4], byteorder="big")
        if p_len < 4 or (off + p_len) > len(raw):
            break

        if current_payload == IKEV2_PAYLOAD_NOTIFY and p_len >= 8:
            spi_size = int(raw[off + 5])
            notify_type = int.from_bytes(raw[off + 6 : off + 8], byteorder="big")
            data_start = off + 8 + spi_size
            data_end = off + p_len
            if data_start <= data_end and notify_type in (NATD_SOURCE, NATD_DEST):
                if (data_end - data_start) == 20:
                    want = want_src if notify_type == NATD_SOURCE else want_dst
                    if bytes(raw[data_start:data_end]) != want:
                        raw[data_start:data_end] = want
                        changed = True
                        rewrites += 1

        off += p_len

    meta["rewrites"] = rewrites
    return (bytes(raw), changed, meta)


class Bridge:
    def __init__(
        self,
        force_peers: Set[str],
        natd_peers: Dict[str, Dict[str, str]],
        public_ip: str,
        drop_nat_keepalive: bool,
        flow_ttl_sec: int,
        logger: logging.Logger,
    ) -> None:
        self.force_peers = force_peers
        self.natd_peers = natd_peers
        self.public_ip = public_ip
        self.drop_nat_keepalive = drop_nat_keepalive
        self.flow_ttl_sec = max(30, int(flow_ttl_sec))
        self.log = logger
        self.lock = threading.Lock()
        self.nat_t_reply_ports: Dict[Tuple[str, int], float] = {}
        self.spi_to_peer: Dict[bytes, Tuple[str, float]] = {}
        self.stats: Dict[str, int] = {
            "in_total": 0,
            "in_strip_marker": 0,
            "in_drop_keepalive": 0,
            "in_passthrough": 0,
            "out_total": 0,
            "out_add_marker": 0,
            "out_passthrough": 0,
            "natd_in_total": 0,
            "natd_in_rewrite": 0,
            "natd_in_passthrough": 0,
            "natd_out_total": 0,
            "natd_out_rewrite": 0,
            "natd_out_passthrough": 0,
        }

    def _bump(self, key: str) -> None:
        with self.lock:
            self.stats[key] = self.stats.get(key, 0) + 1

    def snapshot(self) -> Dict[str, int]:
        with self.lock:
            return dict(self.stats)

    def _track_nat_t_flow(self, peer_ip: str, peer_src_port: int) -> None:
        now = time.time()
        expires = now + self.flow_ttl_sec
        with self.lock:
            self.nat_t_reply_ports[(peer_ip, peer_src_port)] = expires

    def _track_spi_peer(self, spii: bytes, peer_ip: str) -> None:
        now = time.time()
        expires = now + self.flow_ttl_sec
        with self.lock:
            self.spi_to_peer[spii] = (peer_ip, expires)

    def _peer_from_spi(self, spii: bytes) -> Optional[str]:
        now = time.time()
        with self.lock:
            stale_spi = [k for k, (_, exp) in self.spi_to_peer.items() if exp <= now]
            for k in stale_spi:
                self.spi_to_peer.pop(k, None)
            entry = self.spi_to_peer.get(spii)
            if entry is None:
                return None
            return entry[0]

    def _should_add_marker(self, peer_ip: str, peer_dst_port: int) -> bool:
        now = time.time()
        key = (peer_ip, peer_dst_port)
        with self.lock:
            # Opportunistic cleanup
            stale = [k for k, exp in self.nat_t_reply_ports.items() if exp <= now]
            for k in stale:
                self.nat_t_reply_ports.pop(k, None)
            exp = self.nat_t_reply_ports.get(key)
            if exp is None:
                return False
            if exp <= now:
                self.nat_t_reply_ports.pop(key, None)
                return False
            return True

    def inbound(self, packet) -> None:
        # Legacy forced 4500->500 payload marker strip.
        try:
            ip_pkt = IP(packet.get_payload())
            if UDP not in ip_pkt:
                packet.accept()
                return

            udp = ip_pkt[UDP]
            src = str(ip_pkt.src)
            src_port = int(udp.sport)
            if src not in self.force_peers or int(udp.dport) != 4500:
                packet.accept()
                return

            self._bump("in_total")
            udp_payload = bytes(udp.payload)

            if self.drop_nat_keepalive and udp_payload == b"\xff":
                self._bump("in_drop_keepalive")
                packet.drop()
                return

            if len(udp_payload) >= 4 and udp_payload[:4] == b"\x00\x00\x00\x00":
                ike_payload = udp_payload[4:]
                if is_likely_ike(ike_payload):
                    udp.remove_payload()
                    udp.add_payload(ike_payload)
                    if hasattr(udp, "len"):
                        del udp.len
                    if hasattr(udp, "chksum"):
                        del udp.chksum
                    if hasattr(ip_pkt, "len"):
                        del ip_pkt.len
                    if hasattr(ip_pkt, "chksum"):
                        del ip_pkt.chksum
                    packet.set_payload(bytes(ip_pkt))
                    self._bump("in_strip_marker")
                    self._track_nat_t_flow(src, src_port)
                else:
                    self._bump("in_passthrough")
            else:
                self._bump("in_passthrough")

            packet.accept()
        except Exception as exc:  # noqa: BLE001
            self.log.warning("inbound callback error: %s", exc)
            packet.accept()

    def outbound(self, packet) -> None:
        # Legacy forced 4500->500 payload marker add.
        try:
            ip_pkt = IP(packet.get_payload())
            if UDP not in ip_pkt:
                packet.accept()
                return

            udp = ip_pkt[UDP]
            dst = str(ip_pkt.dst)
            dst_port = int(udp.dport)
            if dst not in self.force_peers or int(udp.sport) != 500:
                packet.accept()
                return

            self._bump("out_total")
            udp_payload = bytes(udp.payload)

            if not self._should_add_marker(dst, dst_port):
                self._bump("out_passthrough")
                packet.accept()
                return

            if len(udp_payload) >= 4 and udp_payload[:4] == b"\x00\x00\x00\x00":
                self._bump("out_passthrough")
                packet.accept()
                return

            if is_likely_ike(udp_payload):
                udp.remove_payload()
                udp.add_payload(b"\x00\x00\x00\x00" + udp_payload)
                if hasattr(udp, "len"):
                    del udp.len
                if hasattr(udp, "chksum"):
                    del udp.chksum
                if hasattr(ip_pkt, "len"):
                    del ip_pkt.len
                if hasattr(ip_pkt, "chksum"):
                    del ip_pkt.chksum
                packet.set_payload(bytes(ip_pkt))
                self._bump("out_add_marker")
            else:
                self._bump("out_passthrough")

            packet.accept()
        except Exception as exc:  # noqa: BLE001
            self.log.warning("outbound callback error: %s", exc)
            packet.accept()

    def natd_inbound(self, packet) -> None:
        # DPI rewrite for IKE_SA_INIT NAT_DETECTION payloads on inbound UDP/500.
        try:
            ip_pkt = IP(packet.get_payload())
            if UDP not in ip_pkt:
                packet.accept()
                return
            udp = ip_pkt[UDP]
            src = str(ip_pkt.src)
            if src not in self.natd_peers or int(udp.dport) != 500:
                packet.accept()
                return
            self._bump("natd_in_total")
            raw = bytes(udp.payload)
            rewritten, changed, meta = rewrite_natd_hashes(
                raw,
                src_ip=src,
                src_port=int(udp.sport),
                dst_ip=self.public_ip,
                dst_port=500,
            )
            if meta.get("parsed") and meta.get("exchange") == IKEV2_SA_INIT and meta.get("msg_id") == 0:
                spii = meta.get("spii")
                if isinstance(spii, (bytes, bytearray)) and len(spii) == 8:
                    self._track_spi_peer(bytes(spii), src)
            if changed:
                udp.remove_payload()
                udp.add_payload(rewritten)
                if hasattr(udp, "len"):
                    del udp.len
                if hasattr(udp, "chksum"):
                    del udp.chksum
                if hasattr(ip_pkt, "len"):
                    del ip_pkt.len
                if hasattr(ip_pkt, "chksum"):
                    del ip_pkt.chksum
                packet.set_payload(bytes(ip_pkt))
                self._bump("natd_in_rewrite")
                self.log.info(
                    "natd-in rewrite peer=%s sport=%s msg_id=%s rewrites=%s spii=%s",
                    src,
                    int(udp.sport),
                    meta.get("msg_id"),
                    meta.get("rewrites"),
                    bytes(meta.get("spii", b"")).hex(),
                )
            else:
                self._bump("natd_in_passthrough")
            packet.accept()
        except Exception as exc:  # noqa: BLE001
            self.log.warning("natd inbound callback error: %s", exc)
            packet.accept()

    def natd_outbound(self, packet) -> None:
        # DPI rewrite for IKE_SA_INIT NAT_DETECTION payloads on outbound UDP/500.
        try:
            ip_pkt = IP(packet.get_payload())
            if UDP not in ip_pkt:
                packet.accept()
                return
            udp = ip_pkt[UDP]
            dst = str(ip_pkt.dst)
            if dst not in self.natd_peers or int(udp.sport) != 500:
                packet.accept()
                return

            self._bump("natd_out_total")
            raw = bytes(udp.payload)
            hdr = parse_ike_header(raw)
            peer_hint = dst
            if hdr is not None and hdr["exchange"] == IKEV2_SA_INIT and hdr["msg_id"] == 0:
                peer_from_spi = self._peer_from_spi(hdr["spii"])
                if peer_from_spi:
                    peer_hint = peer_from_spi
            peer_cfg = self.natd_peers.get(peer_hint, self.natd_peers.get(dst, {}))
            initiator_inner_ip = str(peer_cfg.get("initiator_inner_ip", "")).strip()
            # Without explicit inner IP, fallback to public peer IP.
            # This may still trigger NAT detection on peers truly behind NAT.
            dst_hash_ip = initiator_inner_ip if initiator_inner_ip else dst

            rewritten, changed, meta = rewrite_natd_hashes(
                raw,
                src_ip=self.public_ip,
                src_port=500,
                dst_ip=dst_hash_ip,
                dst_port=500,
            )
            if changed:
                udp.remove_payload()
                udp.add_payload(rewritten)
                if hasattr(udp, "len"):
                    del udp.len
                if hasattr(udp, "chksum"):
                    del udp.chksum
                if hasattr(ip_pkt, "len"):
                    del ip_pkt.len
                if hasattr(ip_pkt, "chksum"):
                    del ip_pkt.chksum
                packet.set_payload(bytes(ip_pkt))
                self._bump("natd_out_rewrite")
                self.log.info(
                    "natd-out rewrite peer=%s inner=%s msg_id=%s rewrites=%s spii=%s",
                    dst,
                    dst_hash_ip,
                    meta.get("msg_id"),
                    meta.get("rewrites"),
                    bytes(meta.get("spii", b"")).hex(),
                )
            else:
                self._bump("natd_out_passthrough")
            packet.accept()
        except Exception as exc:  # noqa: BLE001
            self.log.warning("natd outbound callback error: %s", exc)
            packet.accept()


class QueueWorker(threading.Thread):
    def __init__(self, queue_num: int, callback, name: str, logger: logging.Logger, queue_bypass: bool = True) -> None:
        super().__init__(daemon=True, name=name)
        self.queue_num = queue_num
        self.callback = callback
        self.log = logger
        self.nfq = NetfilterQueue()
        self.queue_bypass = queue_bypass

    def run(self) -> None:
        self.log.info("binding queue %s (%s)", self.queue_num, self.name)
        self.nfq.bind(self.queue_num, self.callback, max_len=4096)
        try:
            self.nfq.run()
        except Exception as exc:  # noqa: BLE001
            self.log.warning("queue %s stopped: %s", self.queue_num, exc)
        finally:
            try:
                self.nfq.unbind()
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        try:
            self.nfq.unbind()
        except Exception:  # noqa: BLE001
            pass


def setup_logging(level: str) -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return logging.getLogger("ike-nat-bridge")


def main() -> None:
    ap = argparse.ArgumentParser(description="NFQUEUE NAT-T payload bridge for muxer2")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    log = setup_logging(args.log_level)

    if not CFG_GLOBAL.exists():
        raise SystemExit(f"Missing config: {CFG_GLOBAL}")

    g, modules = load_runtime()
    settings = bridge_settings(g)
    force_peers, natd_peers = customer_features(modules)
    if not settings["enabled"] and not settings["natd_enabled"]:
        log.info("all NFQUEUE experiments disabled; exiting")
        return
    if settings["enabled"] and not force_peers and (not settings["natd_enabled"] or not natd_peers):
        log.info("enabled but no matching customer features found; exiting")
        return

    public_ip = str(g.get("public_ip", "")).strip()
    if not public_ip:
        raise SystemExit("Missing global public_ip for NATD rewrite mode")
    ipaddress.ip_address(public_ip)

    used_queues: Set[int] = set()

    workers: List[QueueWorker] = []
    bridge = Bridge(
        force_peers=force_peers,
        natd_peers=natd_peers,
        public_ip=public_ip,
        drop_nat_keepalive=settings["drop_nat_keepalive"],
        flow_ttl_sec=settings["flow_ttl_sec"],
        logger=log,
    )
    if settings["enabled"] and force_peers:
        q_in = int(settings["queue_in"])
        q_out = int(settings["queue_out"])
        if q_in in used_queues or q_out in used_queues:
            raise SystemExit("Queue collision in nfqueue_ike_bridge")
        used_queues.update({q_in, q_out})
        workers.append(QueueWorker(q_in, bridge.inbound, "nfq-in", log, settings["queue_bypass"]))
        workers.append(QueueWorker(q_out, bridge.outbound, "nfq-out", log, settings["queue_bypass"]))
        log.info("force4500 peers=%s queue_in=%s queue_out=%s", sorted(force_peers), q_in, q_out)

    if settings["natd_enabled"] and natd_peers:
        n_in = int(settings["natd_queue_in"])
        n_out = int(settings["natd_queue_out"])
        if n_in in used_queues or n_out in used_queues:
            raise SystemExit("Queue collision in natd_dpi_rewrite")
        used_queues.update({n_in, n_out})
        workers.append(QueueWorker(n_in, bridge.natd_inbound, "natd-in", log, settings["natd_queue_bypass"]))
        workers.append(QueueWorker(n_out, bridge.natd_outbound, "natd-out", log, settings["natd_queue_bypass"]))
        log.info("natd peers=%s queue_in=%s queue_out=%s", sorted(natd_peers.keys()), n_in, n_out)

    if not workers:
        log.info("no active workers after feature resolution; exiting")
        return

    stop_event = threading.Event()

    def _stop(_sig, _frame) -> None:  # noqa: ANN001
        stop_event.set()
        for w in workers:
            w.stop()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    for w in workers:
        w.start()

    interval = max(5, min(int(settings["log_interval_sec"]), int(settings["natd_log_interval_sec"])))
    while not stop_event.is_set():
        time.sleep(interval)
        s = bridge.snapshot()
        log.info(
            "stats in(total=%s strip=%s drop_keepalive=%s pass=%s) "
            "out(total=%s add=%s pass=%s) "
            "natd-in(total=%s rewrite=%s pass=%s) "
            "natd-out(total=%s rewrite=%s pass=%s)",
            s["in_total"],
            s["in_strip_marker"],
            s["in_drop_keepalive"],
            s["in_passthrough"],
            s["out_total"],
            s["out_add_marker"],
            s["out_passthrough"],
            s["natd_in_total"],
            s["natd_in_rewrite"],
            s["natd_in_passthrough"],
            s["natd_out_total"],
            s["natd_out_rewrite"],
            s["natd_out_passthrough"],
        )

    for w in workers:
        w.join(timeout=2.0)
    log.info("stopped")


if __name__ == "__main__":
    main()
