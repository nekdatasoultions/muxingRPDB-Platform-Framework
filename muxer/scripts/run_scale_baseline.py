#!/usr/bin/env python
"""Run a repo-only synthetic scale baseline for the RPDB runtime."""

from __future__ import annotations

import argparse
import gc
import ipaddress
import json
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any, Dict, List

RUNTIME_ROOT = Path(__file__).resolve().parents[1] / "runtime-package"
RUNTIME_SRC = RUNTIME_ROOT / "src"
if str(RUNTIME_SRC) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SRC))

from muxerlib.core import load_yaml
from muxerlib.dataplane import derive_customer_transport, derive_passthrough_dataplane, derive_post_ipsec_nat
from muxerlib.nftables import build_passthrough_nft_model, render_passthrough_nft_script
from muxerlib.nftables import passthrough_nft_settings


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "build" / "scale-baseline" / "scale-baseline-summary.json"
DEFAULT_COUNTS = [100, 1000, 5000, 10000, 20000]
DEFAULT_PROFILES = ["strict_non_nat", "nat_t", "nat_t_netmap", "mixed", "force4500_bridge", "natd_bridge"]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_counts(raw: str) -> List[int]:
    values = []
    for token in str(raw).split(","):
        token = token.strip()
        if not token:
            continue
        values.append(int(token))
    if not values:
        raise SystemExit("At least one count is required")
    return values


def _parse_profiles(raw: str) -> List[str]:
    values = []
    for token in str(raw).split(","):
        token = token.strip().lower()
        if token:
            values.append(token)
    if not values:
        raise SystemExit("At least one profile is required")
    return values


def _indexed_ipv4(base: str, index: int) -> str:
    start = int(ipaddress.ip_address(base))
    return str(ipaddress.ip_address(start + index))


def _peer_ip(index: int) -> str:
    return f"{_indexed_ipv4('198.18.0.1', index)}/32"


def _backend_underlay(index: int) -> str:
    return _indexed_ipv4("172.31.200.10", index)


def _egress_sources(index: int, *, count: int) -> List[str]:
    return [_indexed_ipv4("172.31.210.10", index * max(count, 1) + offset) for offset in range(count)]


def _remote_subnet(index: int) -> str:
    third_octet = (index // 250) % 256
    fourth_octet = (index % 250) + 1
    return f"10.200.{third_octet}.{fourth_octet}/32"


def _translated_subnet(index: int) -> str:
    third_octet = (index // 250) % 256
    fourth_octet = (index % 250) + 1
    return f"172.30.{third_octet}.{fourth_octet}/32"


def _natd_inner_ip(index: int) -> str:
    return _indexed_ipv4("10.250.0.10", index)


def _build_base_module(index: int, profile: str) -> Dict[str, Any]:
    cid = index + 1
    if profile == "strict_non_nat":
        protocols = {"udp500": True, "udp4500": False, "esp50": True}
        egress_count = 1
    elif profile in {"nat_t", "nat_t_netmap"}:
        protocols = {"udp500": True, "udp4500": True, "esp50": True}
        egress_count = 2
    elif profile == "force4500_bridge":
        protocols = {
            "udp500": True,
            "udp4500": False,
            "esp50": True,
            "force_rewrite_4500_to_500": True,
        }
        egress_count = 1
    elif profile == "natd_bridge":
        protocols = {"udp500": True, "udp4500": False, "esp50": False}
        egress_count = 1
    else:
        raise SystemExit(f"Unsupported profile {profile}")

    module: Dict[str, Any] = {
        "id": cid,
        "name": f"{profile}-scale-{cid:05d}",
        "peer_ip": _peer_ip(index),
        "protocols": protocols,
        "backend_underlay_ip": _backend_underlay(index),
        "headend_egress_sources": _egress_sources(index, count=egress_count),
        "ipip_ifname": f"gre-scale-{cid:05d}",
        "tunnel_type": "gre",
        "tunnel_key": 500000 + cid,
        "rpdb_priority": 100000 + cid,
        "overlay": {
            "mux_ip": f"169.254.{(cid // 255) % 255}.{((cid * 2) % 252) + 1}/30",
            "router_ip": f"169.254.{(cid // 255) % 255}.{((cid * 2) % 252) + 2}/30",
        },
    }

    if profile == "nat_t_netmap":
        module["ipsec"] = {
            "remote_subnets": [_remote_subnet(index)],
            "mark_out": hex(0x500000 + cid),
        }
        module["post_ipsec_nat"] = {
            "enabled": True,
            "mode": "netmap",
            "real_subnets": [_remote_subnet(index)],
            "translated_subnets": [_translated_subnet(index)],
            "core_subnets": ["172.31.54.39/32"],
            "output_mark": hex(0x500000 + cid),
        }
    elif profile == "natd_bridge":
        module["natd_rewrite"] = {
            "enabled": True,
            "initiator_inner_ip": _natd_inner_ip(index),
        }

    return module


def _build_modules(count: int, profile: str) -> List[Dict[str, Any]]:
    modules: List[Dict[str, Any]] = []
    for index in range(count):
        if profile == "mixed":
            effective_profile = "strict_non_nat" if index % 2 == 0 else "nat_t"
        else:
            effective_profile = profile
        modules.append(_build_base_module(index, effective_profile))
    return modules


def _count_protocol_customers(modules: List[Dict[str, Any]]) -> dict[str, int]:
    strict_non_nat = 0
    nat_t = 0
    for module in modules:
        protocols = module.get("protocols") or {}
        if bool(protocols.get("udp500")) and not bool(protocols.get("udp4500")) and bool(protocols.get("esp50")):
            strict_non_nat += 1
        if bool(protocols.get("udp4500")):
            nat_t += 1
    return {
        "strict_non_nat": strict_non_nat,
        "nat_t": nat_t,
    }


def _start_measurement() -> tuple[float, float]:
    gc.collect()
    tracemalloc.start()
    return time.perf_counter(), time.process_time()


def _finish_measurement(started_at: tuple[float, float]) -> dict[str, Any]:
    wall_start, cpu_start = started_at
    _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "wall_ms": round((time.perf_counter() - wall_start) * 1000, 3),
        "cpu_ms": round((time.process_time() - cpu_start) * 1000, 3),
        "peak_memory_bytes": int(peak_bytes),
    }


def _render_plan_metrics(modules: List[Dict[str, Any]], muxer_doc: Dict[str, Any]) -> dict[str, Any]:
    started_at = _start_measurement()
    nft_model = build_passthrough_nft_model(modules, muxer_doc)
    nft_script = render_passthrough_nft_script(nft_model)
    metrics = _finish_measurement(started_at)
    return {
        "metrics": metrics,
        "model": nft_model,
        "script": nft_script,
    }


def _summarize_profile(modules: List[Dict[str, Any]], muxer_doc: Dict[str, Any]) -> dict[str, Any]:
    transport_command_count = 0
    muxer_counts = {
        "filter_accept_rules": 0,
        "mangle_mark_rules": 0,
        "nat_prerouting_rules": 0,
        "nat_postrouting_rules": 0,
        "mangle_postrouting_rules": 0,
        "bridge_prerouting_rules": 0,
        "bridge_postrouting_rules": 0,
        "default_drop_rules": 0,
    }
    headend_apply_command_count = 0
    headend_rollback_command_count = 0
    max_headend_apply_commands_per_customer = 0
    blocked_headend_apply_command_count = 0
    blocked_headend_rollback_command_count = 0
    max_blocked_headend_apply_commands_per_customer = 0

    derive_started = _start_measurement()
    for module in modules:
        transport = derive_customer_transport(module, muxer_doc)
        passthrough = derive_passthrough_dataplane(module, muxer_doc)
        post_ipsec_nat = derive_post_ipsec_nat(module)

        transport_command_count += 3  # tunnel create, address, link up
        transport_command_count += 1  # ip rule
        transport_command_count += len((passthrough.get("routing") or {}).get("table_routes") or [])

        nat_framework = passthrough.get("nat_framework") or {}
        muxer_counts["filter_accept_rules"] += len(nat_framework.get("filter_accept_rules") or [])
        muxer_counts["mangle_mark_rules"] += len(nat_framework.get("mangle_mark_rules") or [])
        muxer_counts["nat_prerouting_rules"] += len(nat_framework.get("nat_prerouting_rules") or [])
        muxer_counts["nat_postrouting_rules"] += len(nat_framework.get("nat_postrouting_rules") or [])
        muxer_counts["mangle_postrouting_rules"] += len(nat_framework.get("mangle_postrouting_rules") or [])
        muxer_counts["bridge_prerouting_rules"] += len(nat_framework.get("bridge_prerouting_rules") or [])
        muxer_counts["bridge_postrouting_rules"] += len(nat_framework.get("bridge_postrouting_rules") or [])
        muxer_counts["default_drop_rules"] += len(nat_framework.get("default_drop_rules") or [])

        apply_commands = list(post_ipsec_nat.get("apply_commands") or [])
        rollback_commands = list(post_ipsec_nat.get("rollback_commands") or [])
        blocked_apply_commands = list(post_ipsec_nat.get("blocked_apply_commands") or [])
        blocked_rollback_commands = list(post_ipsec_nat.get("blocked_rollback_commands") or [])
        headend_apply_command_count += len(apply_commands)
        headend_rollback_command_count += len(rollback_commands)
        max_headend_apply_commands_per_customer = max(max_headend_apply_commands_per_customer, len(apply_commands))
        blocked_headend_apply_command_count += len(blocked_apply_commands)
        blocked_headend_rollback_command_count += len(blocked_rollback_commands)
        max_blocked_headend_apply_commands_per_customer = max(
            max_blocked_headend_apply_commands_per_customer,
            len(blocked_apply_commands),
        )

        _ = transport["table_id"]
    derive_metrics = _finish_measurement(derive_started)

    apply_plan = _render_plan_metrics(modules, muxer_doc)
    previous_modules = modules[:-1] if modules else []
    remove_plan = _render_plan_metrics(previous_modules, muxer_doc)
    nft_model = apply_plan["model"]
    nft_script = apply_plan["script"]

    nft_sets = nft_model.get("sets") or {}
    nft_maps = nft_model.get("maps") or {}
    bridge = nft_model.get("bridge") or {}
    bridge_sets = bridge.get("sets") or {}
    bridge_manifest = bridge.get("manifest") or {}
    bridge_hooks = bridge.get("queue_hooks") or {}
    nft_set_entry_count = sum(len(value or []) for value in nft_sets.values())
    nft_map_entry_count = sum(len(value or {}) for value in nft_maps.values())
    bridge_set_entry_count = sum(len(value or []) for value in bridge_sets.values())
    bridge_manifest_entry_count = sum(len(value or []) for value in bridge_manifest.values())
    bridge_queue_hook_count = sum(
        1 for hook in bridge_hooks.values() if int((hook or {}).get("selector_count") or 0) > 0
    )

    muxer_total_rules = sum(muxer_counts.values())
    bridge_total_rules = muxer_counts["bridge_prerouting_rules"] + muxer_counts["bridge_postrouting_rules"]

    return {
        "customer_mix": _count_protocol_customers(modules),
        "muxer_blocked_rule_model": {
            **muxer_counts,
            "total_rules": muxer_total_rules,
            "bridge_total_rules": bridge_total_rules,
            "transport_command_count": transport_command_count,
            "shell_command_count_estimate": muxer_total_rules + transport_command_count,
            "rules_per_customer": round(muxer_total_rules / len(modules), 3) if modules else 0.0,
            "shell_commands_per_customer": round((muxer_total_rules + transport_command_count) / len(modules), 3)
            if modules
            else 0.0,
        },
        "headend_post_ipsec_nat_runtime": {
            "activation_backend": "nftables",
            "apply_command_count": headend_apply_command_count,
            "rollback_command_count": headend_rollback_command_count,
            "max_apply_commands_per_customer": max_headend_apply_commands_per_customer,
            "blocked_apply_command_count": blocked_headend_apply_command_count,
            "blocked_rollback_command_count": blocked_headend_rollback_command_count,
            "blocked_max_apply_commands_per_customer": max_blocked_headend_apply_commands_per_customer,
        },
        "nftables_preview": {
            "render_mode": nft_model.get("render_mode"),
            "table_name": ((nft_model.get("table") or {}).get("name")),
            "set_count": len([value for value in nft_sets.values() if value]),
            "map_count": len([value for value in nft_maps.values() if value]),
            "set_entry_count": nft_set_entry_count,
            "map_entry_count": nft_map_entry_count,
            "deferred_translation_customer_count": len(nft_model.get("deferred_translation_customers") or []),
            "bridge_backend": bridge.get("backend"),
            "bridge_enabled": bool(bridge.get("enabled")),
            "bridge_set_entry_count": bridge_set_entry_count,
            "bridge_manifest_entry_count": bridge_manifest_entry_count,
            "bridge_queue_hook_count": bridge_queue_hook_count,
            "deferred_bridge_customer_count": len(nft_model.get("deferred_bridge_customers") or []),
            "script_line_count": len(nft_script.splitlines()),
        },
        "timing_ms": {
            "derive_runtime": derive_metrics["wall_ms"],
            "render_nftables_preview": apply_plan["metrics"]["wall_ms"],
            "apply_plan_build": apply_plan["metrics"]["wall_ms"],
            "remove_plan_build": remove_plan["metrics"]["wall_ms"],
            "rollback_plan_build": remove_plan["metrics"]["wall_ms"],
        },
        "cpu_ms": {
            "derive_runtime": derive_metrics["cpu_ms"],
            "apply_plan_build": apply_plan["metrics"]["cpu_ms"],
            "remove_plan_build": remove_plan["metrics"]["cpu_ms"],
            "rollback_plan_build": remove_plan["metrics"]["cpu_ms"],
        },
        "memory_bytes": {
            "derive_runtime_peak": derive_metrics["peak_memory_bytes"],
            "apply_plan_peak": apply_plan["metrics"]["peak_memory_bytes"],
            "remove_plan_peak": remove_plan["metrics"]["peak_memory_bytes"],
            "rollback_plan_peak": remove_plan["metrics"]["peak_memory_bytes"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a synthetic repo-only RPDB scale baseline.")
    parser.add_argument("--counts", default="100,1000,5000,10000,20000", help="Comma-separated customer counts")
    parser.add_argument(
        "--profiles",
        default=",".join(DEFAULT_PROFILES),
        help="Comma-separated profiles: " + ", ".join(DEFAULT_PROFILES),
    )
    parser.add_argument(
        "--muxer-config",
        default=str(RUNTIME_ROOT / "config" / "muxer.yaml"),
        help="Path to runtime muxer config",
    )
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="Path to write the JSON summary")
    parser.add_argument("--json", action="store_true", help="Print the JSON summary to stdout")
    args = parser.parse_args()

    counts = _parse_counts(args.counts)
    profiles = _parse_profiles(args.profiles)
    allowed_profiles = set(DEFAULT_PROFILES)
    unknown_profiles = [profile for profile in profiles if profile not in allowed_profiles]
    if unknown_profiles:
        raise SystemExit("Unsupported profile(s): " + ", ".join(unknown_profiles))

    muxer_doc = load_yaml(Path(args.muxer_config).resolve())
    nft_settings = passthrough_nft_settings(muxer_doc)
    summary: dict[str, Any] = {
        "schema_version": 1,
        "generated_from": "muxer/scripts/run_scale_baseline.py",
        "counts": counts,
        "profiles": profiles,
        "muxer_config": str(Path(args.muxer_config).resolve()),
        "classification_backend": str(nft_settings["classification_backend"]),
        "translation_backend": str(nft_settings["translation_backend"]),
        "bridge_backend": str(nft_settings["bridge_backend"]),
        "scenarios": [],
    }

    for profile in profiles:
        for count in counts:
            modules = _build_modules(count, profile)
            details = _summarize_profile(modules, muxer_doc)
            summary["scenarios"].append(
                {
                    "profile": profile,
                    "customer_count": count,
                    **details,
                }
            )

    if args.out:
        _write_json(Path(args.out).resolve(), summary)

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(f"Scale baseline completed: {len(summary['scenarios'])} scenario(s)")
        if args.out:
            print(f"Summary: {Path(args.out).resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
