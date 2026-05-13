#!/usr/bin/env python
"""Show one customer's live RPDB state across muxer, head ends, and SmartConnect."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MUXER_SRC = REPO_ROOT / "muxer" / "src"
for path in (REPO_ROOT, MUXER_SRC, Path(__file__).resolve().parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from muxerlib.customer_merge import load_yaml_file  # noqa: E402
from muxerlib.customer_route_scope import customer_route_cidrs  # noqa: E402

from live_access_lib import (  # noqa: E402
    build_ssh_access_context,
    cleanup_ssh_access_context,
    run_remote_command,
)
from live_backend_lib import inspect_customer_backend_records  # noqa: E402
from remove_customer import (  # noqa: E402
    customer_metadata,
    headend_family_from_metadata,
    resolve_selector_instance_id,
    selected_cgnat_headend,
    selected_cgnat_isp_gateway,
    selected_headends,
    selected_smartconnect_gateway,
    selector_instance_id,
    target_ssh_user,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_json(command: list[str]) -> tuple[int, dict[str, Any] | None, str, str]:
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    payload = None
    if completed.stdout.strip():
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            payload = None
    return completed.returncode, payload, completed.stdout, completed.stderr


def environment_validation(environment: str) -> tuple[int, dict[str, Any] | None, str, str]:
    return run_json(
        [
            sys.executable,
            "scripts/customers/validate_deployment_environment.py",
            environment,
            "--allow-live-apply",
            "--json",
        ]
    )


def load_environment_doc(environment: str) -> dict[str, Any]:
    code, validation, stdout, stderr = environment_validation(environment)
    if code != 0 or not validation or not validation.get("valid"):
        raise RuntimeError(f"deployment environment validation failed: {stderr or stdout}".strip())
    return load_yaml_file(Path(str(validation["environment_file"])))


def repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_customer_request(path: str) -> dict[str, Any]:
    if not path:
        return {}
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = (REPO_ROOT / candidate).resolve()
    if not candidate.exists():
        return {}
    return load_yaml_file(candidate)


def customer_name_from_request(request_doc: dict[str, Any]) -> str:
    return str(((request_doc.get("customer") or {}).get("name")) or "").strip()


def request_metadata(request_doc: dict[str, Any]) -> dict[str, Any]:
    customer = request_doc.get("customer") or {}
    backend = customer.get("backend") or {}
    transport = customer.get("transport") or {}
    cgnat = transport.get("cgnat") or {}
    peer = customer.get("peer") or {}
    return {
        "customer_name": customer.get("name"),
        "customer_class": customer.get("customer_class"),
        "backend_cluster": backend.get("cluster"),
        "backend_assignment": backend.get("assignment"),
        "peer_ip": peer.get("public_ip"),
        "transport_mode": transport.get("mode"),
        "cgnat_outer_topology": cgnat.get("outer_topology") or "per_customer_outer",
        "cgnat_outer_gateway_ref": cgnat.get("outer_gateway_ref"),
        "customer_json": {},
    }


def route_cidrs_from_request(request_doc: dict[str, Any]) -> tuple[list[str], str]:
    customer = request_doc.get("customer") or {}
    cidrs, source = customer_route_cidrs(customer)
    if source == "remote_host_cidrs":
        source = "selectors.remote_host_cidrs"
    return cidrs, source


def route_cidrs_from_metadata(metadata: dict[str, Any]) -> tuple[list[str], str]:
    module = metadata.get("customer_json") or {}
    if not isinstance(module, dict) or not module:
        return [], ""
    cidrs, source = customer_route_cidrs(module)
    if source == "remote_host_cidrs":
        source = "selectors.remote_host_cidrs"
    return cidrs, source


def _text_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _host_text(value: Any) -> str:
    interface = ipaddress.ip_interface(str(value))
    return str(interface.ip)


def _network_text(value: Any) -> tuple[ipaddress.IPv4Network, str]:
    network = ipaddress.ip_network(str(value), strict=False)
    if network.prefixlen == 32:
        return network, str(network.network_address)
    return network, str(network)


def _netmap_translation_pairs(nat_config: dict[str, Any]) -> list[dict[str, str]]:
    real_subnets = _text_list(nat_config.get("real_subnets"))
    translated_subnets = _text_list(nat_config.get("translated_subnets"))
    translations: list[dict[str, str]] = []
    for real_value, translated_value in zip(real_subnets, translated_subnets):
        real_network, real_text = _network_text(real_value)
        translated_network, translated_text = _network_text(translated_value)
        translations.append(
            {
                "presented": translated_text,
                "real": real_text,
                "kind": "host"
                if real_network.prefixlen == 32 and translated_network.prefixlen == 32
                else "pool",
            }
        )
    return translations


def _explicit_translation_pairs(nat_config: dict[str, Any]) -> list[dict[str, str]]:
    translations: list[dict[str, str]] = []
    for host_mapping in nat_config.get("host_mappings") or []:
        if not isinstance(host_mapping, dict):
            continue
        translated_ip = str(host_mapping.get("translated_ip") or "").strip()
        real_ip = str(host_mapping.get("real_ip") or "").strip()
        if translated_ip and real_ip:
            translations.append(
                {
                    "presented": _host_text(translated_ip),
                    "real": _host_text(real_ip),
                    "kind": "host",
                }
            )
    return translations


def _generic_translation_pairs(nat_config: dict[str, Any]) -> list[dict[str, str]]:
    translated_source_ip = str(nat_config.get("translated_source_ip") or "").strip()
    if not translated_source_ip:
        return []
    translations: list[dict[str, str]] = []
    for real_value in _text_list(nat_config.get("real_subnets")):
        _real_network, real_text = _network_text(real_value)
        translations.append(
            {
                "presented": _host_text(translated_source_ip),
                "real": real_text,
                "kind": "source_ip",
            }
        )
    return translations


def nat_translation_pairs(nat_config: dict[str, Any]) -> list[dict[str, str]]:
    strategy = str(nat_config.get("mapping_strategy") or "").strip()
    mode = str(nat_config.get("mode") or "").strip()
    if strategy == "explicit_host_map" or mode == "explicit_map":
        return _explicit_translation_pairs(nat_config)
    if strategy == "one_to_one" or mode == "netmap":
        return _netmap_translation_pairs(nat_config)
    return _generic_translation_pairs(nat_config)


def outside_nat_customer_sources(outside_nat: dict[str, Any], selectors: dict[str, Any]) -> list[str]:
    explicit_sources = _text_list(outside_nat.get("customer_sources"))
    if explicit_sources:
        return explicit_sources
    remote_hosts = _text_list(selectors.get("remote_host_cidrs"))
    if remote_hosts:
        return remote_hosts
    return _text_list(selectors.get("remote_subnets"))


def nat_translation_summary(customer_module: dict[str, Any]) -> dict[str, Any]:
    selectors = customer_module.get("selectors") or {}
    post_ipsec_nat = customer_module.get("post_ipsec_nat") or {}
    outside_nat = customer_module.get("outside_nat") or {}
    summary: dict[str, Any] = {}

    if bool(post_ipsec_nat.get("enabled")):
        summary["inside"] = {
            "enabled": True,
            "mode": post_ipsec_nat.get("mode"),
            "mapping_strategy": post_ipsec_nat.get("mapping_strategy"),
            "translations": nat_translation_pairs(post_ipsec_nat),
            "core_subnets": _text_list(post_ipsec_nat.get("core_subnets")),
        }

    if bool(outside_nat.get("enabled")):
        summary["outside"] = {
            "enabled": True,
            "mode": outside_nat.get("mode"),
            "mapping_strategy": outside_nat.get("mapping_strategy"),
            "translations": nat_translation_pairs(outside_nat),
            "customer_sources": outside_nat_customer_sources(outside_nat, selectors),
            "route_via": outside_nat.get("route_via"),
            "route_dev": outside_nat.get("route_dev"),
        }

    return summary


def nat_translation_summary_from_metadata(
    metadata: dict[str, Any],
    request_doc: dict[str, Any],
) -> dict[str, Any]:
    module = metadata.get("customer_json") or {}
    if isinstance(module, dict) and module:
        return nat_translation_summary(module)
    customer = request_doc.get("customer") or {}
    if isinstance(customer, dict) and customer:
        return nat_translation_summary(customer)
    return {}


def merged_metadata(sot_metadata: dict[str, Any], request_doc: dict[str, Any]) -> dict[str, Any]:
    if sot_metadata.get("customer_name"):
        return sot_metadata
    fallback = request_metadata(request_doc)
    return fallback if fallback.get("customer_name") else sot_metadata


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def as_shell_json(payload: Any) -> str:
    return shlex.quote(json.dumps(payload, separators=(",", ":")))


REMOTE_PROBE = r'''
import json
import os
import pathlib
import re
import subprocess

cust = os.environ["RPDB_CUSTOMER"]
role = os.environ["RPDB_ROLE"]
expected_route_cidrs = json.loads(os.environ.get("RPDB_EXPECTED_ROUTE_CIDRS") or "[]")

def run(command):
    completed = subprocess.run(command, shell=True, text=True, capture_output=True)
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "success": completed.returncode == 0,
    }

def exists(path):
    return pathlib.Path(path).exists()

def read_json(path):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}

def nft_name(value, prefix):
    normalized = re.sub(r"[^a-z0-9_]+", "_", str(value).lower()).strip("_")
    normalized = (normalized[:48] or "customer")
    return f"{prefix}_{normalized}"

def check_nft_table(table):
    if not table:
        return {"table": table, "present": False, "line_count": 0}
    result = run("nft list table ip " + shlex_quote(table))
    return {
        "table": table,
        "present": result["success"],
        "line_count": len(result["stdout"].splitlines()) if result["stdout"] else 0,
        "stderr": result["stderr"],
    }

def shlex_quote(value):
    return "'" + str(value).replace("'", "'\"'\"'") + "'"

def status_from(required_present, stale_present=False):
    if required_present:
        return "deployed"
    if stale_present:
        return "partial"
    return "clean"

def muxer():
    root = f"/var/lib/rpdb-muxer/customers/{cust}"
    module = f"/etc/muxer/config/customer-modules/{cust}/customer-module.json"
    routing = read_json(f"{root}/routing/rpdb-routing.json")
    state = read_json(f"{root}/firewall/nftables-state.json")
    table = state.get("table_name") or nft_name(cust, "rpdb_mx")
    fwmark = str(routing.get("fwmark") or "")
    route_table = str(routing.get("route_table") or "")
    nft = check_nft_table(table)
    ip_rule = run("ip rule show | grep -F " + shlex_quote(fwmark)) if fwmark else {"success": False, "stdout": ""}
    routes = run("ip route show table " + shlex_quote(route_table)) if route_table else {"success": False, "stdout": ""}
    root_present = exists(root)
    module_present = exists(module)
    return {
        "role": "muxer",
        "status": status_from(root_present and module_present, nft["present"] or root_present or module_present),
        "root_present": root_present,
        "module_present": module_present,
        "fwmark": fwmark,
        "route_table": route_table,
        "ip_rule_seen": bool(ip_rule.get("success")),
        "route_table_line_count": len((routes.get("stdout") or "").splitlines()),
        "nft_table": nft,
    }

def headend():
    root = f"/var/lib/rpdb-headend/customers/{cust}"
    conf = f"/etc/swanctl/conf.d/rpdb-customers/{cust}.conf"
    post_state = read_json(f"{root}/post-ipsec-nat/nftables-state.json")
    outside_state = read_json(f"{root}/outside-nat/nftables-state.json")
    post_table = post_state.get("table_name") or nft_name(cust, "rpdb_hn")
    outside_table = outside_state.get("table_name") or nft_name(cust, "rpdb_on")
    conns = run("swanctl --list-conns 2>/dev/null | grep -F " + shlex_quote(cust))
    sas = run("swanctl --list-sas 2>/dev/null | grep -F " + shlex_quote(cust))
    post_nft = check_nft_table(post_table)
    outside_nft = check_nft_table(outside_table)
    root_present = exists(root)
    conf_present = exists(conf)
    return {
        "role": "headend",
        "status": status_from(root_present and conf_present, root_present or conf_present or post_nft["present"] or outside_nft["present"]),
        "root_present": root_present,
        "swanctl_conf_present": conf_present,
        "swanctl_connection_seen": bool(conns.get("success")),
        "swanctl_sa_seen": bool(sas.get("success")),
        "post_ipsec_nat_table": post_nft,
        "outside_nat_table": outside_nft,
    }

def smartconnect():
    root = f"/var/lib/rpdb-smartconnect/customers/{cust}"
    intent = read_json(f"{root}/routing/route-intent.json")
    route_cidrs = [str(value) for value in (intent.get("customer_route_cidrs") or expected_route_cidrs) if str(value).strip()]
    route_checks = []
    for cidr in route_cidrs:
        result = run("ip route show " + shlex_quote(cidr))
        route_checks.append({"cidr": cidr, "present": bool(result["stdout"]), "route": result["stdout"]})
    root_present = exists(root)
    stale_routes = any(item["present"] for item in route_checks)
    deployed_routes = bool(route_cidrs) and all(item["present"] for item in route_checks)
    if root_present and (deployed_routes or not route_cidrs):
        status = "deployed"
    elif root_present or stale_routes:
        status = "partial"
    else:
        status = "clean"
    return {
        "role": "smartconnect",
        "status": status,
        "root_present": root_present,
        "route_intent_present": bool(intent),
        "route_source": intent.get("customer_route_cidrs_source") or os.environ.get("RPDB_EXPECTED_ROUTE_SOURCE") or "",
        "expected_route_cidrs": route_cidrs,
        "route_checks": route_checks,
    }

def cgnat_headend():
    root = f"/var/lib/rpdb-cgnat/customers/{cust}"
    config = f"/etc/rpdb-cgnat/customers/{cust}.json"
    conns = run("swanctl --list-conns 2>/dev/null | grep -F " + shlex_quote(cust))
    sas = run("swanctl --list-sas 2>/dev/null | grep -F " + shlex_quote(cust))
    root_present = exists(root)
    config_present = exists(config)
    return {
        "role": "cgnat-headend",
        "status": status_from(root_present and config_present, root_present or config_present),
        "root_present": root_present,
        "config_present": config_present,
        "swanctl_connection_seen": bool(conns.get("success")),
        "swanctl_sa_seen": bool(sas.get("success")),
    }

def cgnat_gateway():
    root = f"/var/lib/rpdb-cgnat/customers/{cust}"
    config = f"/etc/rpdb-cgnat/customers/{cust}-gateway-handoff.json"
    conns = run("swanctl --list-conns 2>/dev/null | grep -F " + shlex_quote(cust))
    sas = run("swanctl --list-sas 2>/dev/null | grep -F " + shlex_quote(cust))
    root_present = exists(root)
    config_present = exists(config)
    return {
        "role": "cgnat-isp-gateway",
        "status": status_from(root_present and config_present, root_present or config_present),
        "root_present": root_present,
        "gateway_handoff_present": config_present,
        "swanctl_connection_seen": bool(conns.get("success")),
        "swanctl_sa_seen": bool(sas.get("success")),
    }

handlers = {
    "muxer": muxer,
    "headend": headend,
    "smartconnect": smartconnect,
    "cgnat-headend": cgnat_headend,
    "cgnat-isp-gateway": cgnat_gateway,
}
print(json.dumps(handlers[role](), indent=2, sort_keys=True))
'''


def remote_probe_command(
    *,
    role: str,
    customer_name: str,
    route_cidrs: list[str],
    route_source: str,
) -> str:
    exports = " ".join(
        [
            f"RPDB_ROLE={shlex.quote(role)}",
            f"RPDB_CUSTOMER={shlex.quote(customer_name)}",
            f"RPDB_EXPECTED_ROUTE_CIDRS={as_shell_json(route_cidrs)}",
            f"RPDB_EXPECTED_ROUTE_SOURCE={shlex.quote(route_source)}",
        ]
    )
    payload = f"{exports} python3 - <<'PY'\n{REMOTE_PROBE}\nPY"
    return "sudo bash -lc " + shlex.quote(payload)


def target_record(
    *,
    role: str,
    target: dict[str, Any],
    instance_id: str,
    via_bastion: bool,
    family: str = "",
    ha_role: str = "",
) -> dict[str, Any]:
    return {
        "role": role,
        "target_name": target.get("name"),
        "target_role": target.get("role"),
        "instance_id": instance_id,
        "via_bastion": via_bastion,
        "family": family,
        "ha_role": ha_role,
        "ssh_user": target_ssh_user(target),
    }


def build_targets(
    *,
    environment_doc: dict[str, Any],
    metadata: dict[str, Any],
    region: str,
    headend_family: str,
    include_cgnat: str,
) -> list[dict[str, Any]]:
    targets_doc = environment_doc.get("targets") or {}
    muxer = targets_doc.get("muxer") or {}
    muxer_instance_id = selector_instance_id(muxer)
    records = [
        target_record(role="muxer", target=muxer, instance_id=muxer_instance_id, via_bastion=False)
    ]

    for headend in selected_headends(environment_doc, headend_family):
        records.append(
            target_record(
                role="headend",
                target=headend,
                instance_id=selector_instance_id(headend),
                via_bastion=True,
                family=str(headend.get("family") or ""),
                ha_role=str(headend.get("ha_role") or ""),
            )
        )

    smartconnect = selected_smartconnect_gateway(environment_doc)
    if smartconnect:
        records.append(
            target_record(
                role="smartconnect",
                target=smartconnect,
                instance_id=selector_instance_id(smartconnect),
                via_bastion=True,
            )
        )

    cgnat_targets = (targets_doc.get("cgnat") or {})
    should_inspect_cgnat = include_cgnat == "all" or (
        include_cgnat == "auto" and str(metadata.get("transport_mode") or "").strip().lower() == "cgnat"
    )
    if should_inspect_cgnat:
        cgnat_headend = selected_cgnat_headend(environment_doc, metadata)
        if not cgnat_headend and include_cgnat == "all":
            cgnat_headend = ((cgnat_targets.get("headend") or {}).get("active") or {})
        if cgnat_headend:
            records.append(
                target_record(
                    role="cgnat-headend",
                    target=cgnat_headend,
                    instance_id=selector_instance_id(cgnat_headend),
                    via_bastion=True,
                )
            )

        selected_gateway = selected_cgnat_isp_gateway(environment_doc, metadata)
        gateways: list[dict[str, Any]] = []
        if selected_gateway:
            gateways = [selected_gateway]
        elif include_cgnat == "all":
            gateways = [
                gateway
                for gateway in ((cgnat_targets.get("isp_gateways") or {}).values())
                if isinstance(gateway, dict)
            ]
        for gateway in gateways:
            instance_id = resolve_selector_instance_id(gateway, region=region)
            if instance_id:
                records.append(
                    target_record(
                        role="cgnat-isp-gateway",
                        target=gateway,
                        instance_id=instance_id,
                        via_bastion=True,
                    )
                )

    return records


def expected_from_statuses(expected: str, backend: dict[str, Any], surfaces: list[dict[str, Any]]) -> dict[str, Any]:
    if expected == "any":
        return {"status": "observed", "ok": True, "errors": []}

    errors: list[str] = []
    customer_present = bool(backend.get("customer_present"))
    allocation_count = int(backend.get("allocation_count") or 0)
    if expected == "clean":
        if customer_present:
            errors.append("SoT customer item is still present")
        if allocation_count:
            errors.append(f"SoT allocation records still present: {allocation_count}")
        for surface in surfaces:
            if surface.get("status") != "clean":
                errors.append(
                    f"{surface.get('target_name') or surface.get('role')} is {surface.get('status')}"
                )
    elif expected == "deployed":
        if not customer_present:
            errors.append("SoT customer item is missing")
        if allocation_count <= 0:
            errors.append("SoT allocation records are missing")
        muxer_ok = any(surface.get("role") == "muxer" and surface.get("status") == "deployed" for surface in surfaces)
        headend_ok = any(surface.get("role") == "headend" and surface.get("status") == "deployed" for surface in surfaces)
        smartconnect_surfaces = [surface for surface in surfaces if surface.get("role") == "smartconnect"]
        smartconnect_ok = not smartconnect_surfaces or any(
            surface.get("status") == "deployed" for surface in smartconnect_surfaces
        )
        if not muxer_ok:
            errors.append("muxer is not deployed")
        if not headend_ok:
            errors.append("no VPN head end shows deployed state")
        if not smartconnect_ok:
            errors.append("SmartConnectGateway3 is not deployed")
        cgnat_surfaces = [surface for surface in surfaces if str(surface.get("role") or "").startswith("cgnat")]
        if cgnat_surfaces and not any(surface.get("status") == "deployed" for surface in cgnat_surfaces):
            errors.append("CGNAT surfaces were inspected but none are deployed")
    else:
        errors.append(f"unsupported expected state: {expected}")
    return {"status": "ok" if not errors else "mismatch", "ok": not errors, "errors": errors}


def print_human(result: dict[str, Any]) -> None:
    print(f"customer: {result['customer_name']}")
    print(f"expected: {result['expected']}")
    print(f"overall: {result['overall']['status']}")
    backend = result.get("backend") or {}
    print(
        "sot: "
        f"customer_present={str(bool(backend.get('customer_present'))).lower()} "
        f"allocations={backend.get('allocation_count')}"
    )
    metadata = result.get("metadata") or {}
    if metadata.get("backend_cluster") or metadata.get("transport_mode"):
        print(
            "resolved: "
            f"headend_family={result.get('headend_family') or ''} "
            f"backend={metadata.get('backend_cluster') or ''} "
            f"transport={metadata.get('transport_mode') or ''}"
        )
    print_nat_translation_summary(result.get("nat_translations") or {})
    for surface in result.get("surfaces") or []:
        label = surface.get("target_name") or surface.get("role")
        if surface.get("family"):
            label = f"{label} [{surface.get('family')}/{surface.get('ha_role')}]"
        print(f"- {label}: {surface.get('status')}")
        if surface.get("role") == "muxer":
            print(
                f"  muxer root={surface.get('root_present')} module={surface.get('module_present')} "
                f"fwmark={surface.get('fwmark') or ''} ip_rule={surface.get('ip_rule_seen')} "
                f"nft={((surface.get('nft_table') or {}).get('present'))}"
            )
        elif surface.get("role") == "headend":
            print(
                f"  headend root={surface.get('root_present')} swanctl_conf={surface.get('swanctl_conf_present')} "
                f"conn={surface.get('swanctl_connection_seen')} sa={surface.get('swanctl_sa_seen')} "
                f"inside_nat_nft={((surface.get('post_ipsec_nat_table') or {}).get('present'))} "
                f"outside_nat_nft={((surface.get('outside_nat_table') or {}).get('present'))}"
            )
        elif surface.get("role") == "smartconnect":
            route_bits = ", ".join(
                f"{item.get('cidr')}:{'yes' if item.get('present') else 'no'}"
                for item in surface.get("route_checks") or []
            )
            print(
                f"  sg3 root={surface.get('root_present')} source={surface.get('route_source') or ''} "
                f"routes=[{route_bits}]"
            )
        elif str(surface.get("role") or "").startswith("cgnat"):
            print(
                f"  cgnat root={surface.get('root_present')} "
                f"config={surface.get('config_present', surface.get('gateway_handoff_present'))} "
                f"conn={surface.get('swanctl_connection_seen')} sa={surface.get('swanctl_sa_seen')}"
            )
    for error in result.get("overall", {}).get("errors") or []:
        print(f"error: {error}")


def _format_nat_translations(translations: list[dict[str, str]]) -> str:
    if not translations:
        return "-"
    rendered: list[str] = []
    for translation in translations:
        suffix = " pool" if translation.get("kind") == "pool" else ""
        rendered.append(f"{translation.get('presented')}->{translation.get('real')}{suffix}")
    return ", ".join(rendered)


def print_nat_translation_summary(summary: dict[str, Any]) -> None:
    inside = summary.get("inside") or {}
    outside = summary.get("outside") or {}
    if not inside and not outside:
        return
    print("nat translations:")
    if inside:
        core = ",".join(inside.get("core_subnets") or []) or "-"
        print(
            "  inside: "
            f"mode={inside.get('mode') or ''} "
            f"mapping={inside.get('mapping_strategy') or ''} "
            f"presented->real=[{_format_nat_translations(inside.get('translations') or [])}] "
            f"core=[{core}]"
        )
    if outside:
        customer_sources = ",".join(outside.get("customer_sources") or []) or "-"
        route_via = outside.get("route_via") or "-"
        route_dev = outside.get("route_dev") or "-"
        print(
            "  outside: "
            f"mode={outside.get('mode') or ''} "
            f"mapping={outside.get('mapping_strategy') or ''} "
            f"presented->real=[{_format_nat_translations(outside.get('translations') or [])}] "
            f"customer_sources=[{customer_sources}] "
            f"route={route_via} dev {route_dev}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only live-state inspection for one RPDB customer."
    )
    parser.add_argument("--customer-name", help="Customer name. Optional when --customer-file is provided.")
    parser.add_argument("--customer-file", default="", help="Customer request file used to infer route/CGNAT intent.")
    parser.add_argument("--environment", default="rpdb-empty-live")
    parser.add_argument("--expected", choices=["any", "clean", "deployed"], default="any")
    parser.add_argument(
        "--headend-family",
        choices=["auto", "nat", "non_nat", "all"],
        default="all",
        help="Head-end family to inspect. Default all shows stale NAT/non-NAT state clearly.",
    )
    parser.add_argument(
        "--include-cgnat",
        choices=["auto", "all", "none"],
        default="auto",
        help="Inspect CGNAT targets when metadata or the customer file says transport.mode=cgnat.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON only.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    request_doc = load_customer_request(args.customer_file)
    customer_name = str(args.customer_name or customer_name_from_request(request_doc)).strip()
    if not customer_name:
        raise SystemExit("--customer-name is required when --customer-file is missing or has no customer.name")

    environment_doc = load_environment_doc(args.environment)
    environment = environment_doc.get("environment") or {}
    region = str((environment.get("aws") or {}).get("region") or "").strip()
    ssh_user = str(((environment.get("access") or {}).get("ssh") or {}).get("user") or "").strip()
    if not region or not ssh_user:
        raise SystemExit("environment must define environment.aws.region and environment.access.ssh.user")

    datastores = environment_doc.get("datastores") or {}
    backend = inspect_customer_backend_records(
        region=region,
        customer_table=str(datastores.get("customer_sot_table") or ""),
        allocation_table=str(datastores.get("allocation_table") or ""),
        customer_name=customer_name,
    )
    sot_metadata = customer_metadata(backend.get("customer_item"))
    metadata = merged_metadata(sot_metadata, request_doc)
    nat_translations = nat_translation_summary_from_metadata(metadata, request_doc)
    route_cidrs, route_source = route_cidrs_from_metadata(sot_metadata)
    if not route_cidrs:
        route_cidrs, route_source = route_cidrs_from_request(request_doc)

    headend_family = args.headend_family
    if headend_family == "auto":
        headend_family = headend_family_from_metadata(metadata, "auto") or "all"

    target_records = build_targets(
        environment_doc=environment_doc,
        metadata=metadata,
        region=region,
        headend_family=headend_family,
        include_cgnat=args.include_cgnat,
    )
    muxer_record = next(record for record in target_records if record["role"] == "muxer")
    ssh_user_overrides = {
        record["instance_id"]: record["ssh_user"]
        for record in target_records
        if record.get("instance_id") and record.get("ssh_user")
    }
    context = build_ssh_access_context(
        region=region,
        ssh_user=ssh_user,
        bastion_instance_id=muxer_record["instance_id"],
        target_instance_ids=unique([record["instance_id"] for record in target_records if record.get("instance_id")]),
        ssh_user_overrides=ssh_user_overrides,
    )
    surfaces: list[dict[str, Any]] = []
    try:
        for record in target_records:
            remote_result = run_remote_command(
                context=context,
                target_instance_id=record["instance_id"],
                via_bastion=bool(record["via_bastion"]),
                remote_command=remote_probe_command(
                    role=record["role"],
                    customer_name=customer_name,
                    route_cidrs=route_cidrs,
                    route_source=route_source,
                ),
                timeout_seconds=180,
            )
            payload: dict[str, Any]
            try:
                payload = json.loads(remote_result.get("stdout") or "{}")
            except json.JSONDecodeError:
                payload = {
                    "status": "unknown",
                    "parse_error": "remote probe did not return JSON",
                    "stdout": remote_result.get("stdout"),
                    "stderr": remote_result.get("stderr"),
                }
            surfaces.append(
                {
                    **record,
                    **payload,
                    "probe_success": bool(remote_result.get("success")),
                    "probe_stderr": remote_result.get("stderr"),
                }
            )
    finally:
        cleanup_ssh_access_context(context)

    overall = expected_from_statuses(args.expected, backend, surfaces)
    result = {
        "schema_version": 1,
        "action": "show_customer_live_state",
        "generated_at": utc_now(),
        "customer_name": customer_name,
        "environment": args.environment,
        "expected": args.expected,
        "headend_family": headend_family,
        "include_cgnat": args.include_cgnat,
        "route_expectation": {
            "source": route_source,
            "cidrs": route_cidrs,
        },
        "backend": {
            "customer_present": bool(backend.get("customer_present")),
            "allocation_count": int(backend.get("allocation_count") or 0),
        },
        "metadata": {
            key: value
            for key, value in metadata.items()
            if key != "customer_json"
        },
        "nat_translations": nat_translations,
        "surfaces": surfaces,
        "overall": overall,
    }

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_human(result)
    return 0 if overall.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
