#!/usr/bin/env python3
"""Inspect and safely repair muxer customer runtime state."""

from __future__ import annotations

import argparse
import copy
import ipaddress
import json
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muxerlib.core import load_yaml
from muxerlib.dataplane import (
    derive_customer_transport,
    derive_headend_return_path,
    derive_passthrough_dataplane,
    derive_post_ipsec_nat,
)
from muxerlib.dynamodb_sot import (
    customer_sot_settings,
    normalize_customer_sot_backend,
    put_customer_module,
)
from muxerlib.variables import load_module, load_modules, select_customer_module, strict_non_nat_customer

EXPLAIN_TEXT = """\
muxer_customer_doctor.py

Purpose
  Inspect one customer's muxer state, compare expected vs observed runtime,
  and run the safest normal repair path when muxer drift is detected.

What it checks
  - customer identity and protocol class
  - mark and route table
  - tunnel interface, local/remote underlay, overlay IP
  - ip rule and route table state
  - customer-specific iptables rules derived from the muxer config
  - expected head-end return controls
  - expected post-IPsec NAT model

What repair does
  - runs the normal muxer control path: muxctl.py apply
  - optionally flushes peer-specific conntrack entries after a head-end move
  - does not try to invent ad hoc rule edits before proving apply is insufficient

What update-sot does
  - updates the active customer source of truth when live migrated runtime is
    internally consistent and only the expected backend config is stale
  - currently supports DynamoDB-backed customer SoT
  - refuses to write when the customer still looks truly broken

How to run it
  List all customers:
    sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py list

  List customers from staged local RPDB customer-module files:
    sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py --source customer_modules list

  Show one customer:
    sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py show legacy-cust0001

  Check one customer for drift:
    sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py check legacy-cust0001

  Repair one customer through the normal muxer apply path:
    sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py repair legacy-cust0001

  Repair and also clear peer-specific conntrack after a migration:
    sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py repair legacy-cust0001 --flush-peer-conntrack

  Preview a source-of-truth update after a clean migration:
    sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py update-sot legacy-cust0001 --dry-run

  Write the observed backend underlay into the active customer SoT:
    sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py update-sot legacy-cust0001

  Emit JSON:
    sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py --json show legacy-cust0001

Customer selectors
  You can identify a customer by:
  - exact name
  - numeric id
  - peer IP
  - unique partial name

Good first-response workflow
  1. list
  2. show <customer>
  3. check <customer>
  4. repair <customer>
  5. repair <customer> --flush-peer-conntrack    if the customer was moved to a new head end
  6. update-sot <customer> --dry-run             if runtime looks migrated but SoT is stale
  7. update-sot <customer>                       after dry-run looks correct

Migration awareness
  The doctor tries to distinguish:
  - true muxer failure
  - migrated live runtime with stale expected config

  If the tunnel remote and backend-side NAT rules consistently point at a new
  head end, the script will classify that as migration drift instead of telling
  you the customer is simply broken.
"""


def run(cmd: List[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, check=check, text=True, capture_output=True)
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, 127, "", f"command not found: {cmd[0]}")


def output_or_error(result: subprocess.CompletedProcess[str]) -> str:
    text = (result.stdout or "").strip()
    if text:
        return text
    return (result.stderr or "").strip()


def extract_ipv4(pattern: str, text: str) -> str:
    match = re.search(pattern, text or "")
    if not match:
        return ""
    return str(match.group(1))


def default_config_root() -> Path:
    installed = Path("/etc/muxer")
    if installed.exists():
        return installed
    return REPO_ROOT


def load_muxer_state(config_root: Path, source_backend: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    muxer_cfg = config_root / "config" / "muxer.yaml"
    if not muxer_cfg.exists():
        raise SystemExit(f"Missing muxer config at {muxer_cfg}")

    muxer_doc = load_yaml(muxer_cfg)
    overlay_pool = ipaddress.ip_network(str(muxer_doc["overlay_pool"]), strict=False)
    modules = load_modules(
        overlay_pool,
        cfg_dir=config_root / "config" / "tunnels.d",
        customer_modules_dir=config_root / "config" / "customer-modules",
        customers_vars_path=config_root / "config" / "customers.variables.yaml",
        global_cfg=muxer_doc,
        source_backend=source_backend,
    )
    return muxer_doc, modules


def load_muxer_customer(config_root: Path, source_backend: str, selector: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    muxer_cfg = config_root / "config" / "muxer.yaml"
    if not muxer_cfg.exists():
        raise SystemExit(f"Missing muxer config at {muxer_cfg}")

    muxer_doc = load_yaml(muxer_cfg)
    overlay_pool = ipaddress.ip_network(str(muxer_doc["overlay_pool"]), strict=False)
    customer = load_module(
        selector,
        overlay_pool,
        cfg_dir=config_root / "config" / "tunnels.d",
        customer_modules_dir=config_root / "config" / "customer-modules",
        customers_vars_path=config_root / "config" / "customers.variables.yaml",
        global_cfg=muxer_doc,
        source_backend=source_backend,
    )
    return muxer_doc, customer


def local_customer_module_path(config_root: Path, customer_name: str) -> Path:
    base = config_root / "config" / "customer-modules"
    candidates = (
        base / customer_name / "customer-module.json",
        base / customer_name / "customer-module.yaml",
        base / customer_name / "customer-module.yml",
        base / f"{customer_name}.json",
        base / f"{customer_name}.yaml",
        base / f"{customer_name}.yml",
    )
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def resolve_customer(modules: List[Dict[str, Any]], selector: str) -> Dict[str, Any]:
    return select_customer_module(modules, selector)


def iptables_check(cli: str) -> Tuple[bool, str]:
    parts = shlex.split(cli)
    if not parts or parts[0] != "iptables":
        return False, "unsupported rule format"

    args = parts[1:]
    if len(args) < 2:
        return False, "rule is too short"

    if args[0] == "-t":
        table = args[1]
        rest = args[2:]
        cmd = ["iptables", "-t", table]
    else:
        rest = args
        cmd = ["iptables"]

    if not rest or rest[0] != "-A" or len(rest) < 2:
        return False, "rule is not an append-form rule"

    cmd.extend(["-C", rest[1]])
    cmd.extend(rest[2:])
    result = run(cmd, check=False)
    return result.returncode == 0, output_or_error(result)


def runtime_issue(
    status: str,
    area: str,
    summary: str,
    *,
    command: str = "",
    repair_hint: str = "",
) -> Dict[str, str]:
    return {
        "status": status,
        "area": area,
        "summary": summary,
        "command": command,
        "repair_hint": repair_hint,
    }


def check_tunnel_runtime(transport: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    tunnel = transport["tunnel"]
    ifname = str(tunnel["interface"])
    overlay_ip = str(ipaddress.ip_interface(str(tunnel["overlay"]["mux_ip"])).ip)
    result = run(["ip", "-d", "tunnel", "show", ifname], check=False)
    addr_result = run(["ip", "-o", "-4", "addr", "show", "dev", ifname], check=False)
    link_result = run(["ip", "-o", "link", "show", "dev", ifname], check=False)

    issues: List[Dict[str, str]] = []
    observed: Dict[str, Any] = {
        "interface": ifname,
        "tunnel_show": output_or_error(result),
        "addr_show": output_or_error(addr_result),
        "link_show": output_or_error(link_result),
        "observed_local_ip": "",
        "observed_remote_ip": "",
    }

    if result.returncode != 0:
        issues.append(
            runtime_issue(
                "fail",
                "tunnel",
                f"Tunnel interface {ifname} is missing",
                command=f"ip -d tunnel show {ifname}",
                repair_hint="Re-run muxer apply to recreate the customer tunnel",
            )
        )
        return observed, issues

    tunnel_text = observed["tunnel_show"]
    observed["observed_local_ip"] = extract_ipv4(r"\blocal ([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)\b", tunnel_text)
    observed["observed_remote_ip"] = extract_ipv4(r"\bremote ([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)\b", tunnel_text)

    want_local = f"local {transport['local_underlay_ip']}"
    if want_local not in tunnel_text:
        issues.append(
            runtime_issue(
                "fail",
                "tunnel",
                f"Tunnel local underlay drift detected on {ifname}",
                command=f"ip -d tunnel show {ifname}",
                repair_hint="Re-run muxer apply to rebuild the tunnel with the expected local underlay IP",
            )
        )

    if tunnel["mode"] == "gre" and tunnel["key"] is not None and f"key {tunnel['key']}" not in tunnel_text:
        issues.append(
            runtime_issue(
                "fail",
                "tunnel",
                f"GRE key drift detected on {ifname}",
                command=f"ip -d tunnel show {ifname}",
                repair_hint="Re-run muxer apply to rebuild the GRE interface with the expected key",
            )
        )

    if addr_result.returncode != 0 or overlay_ip not in observed["addr_show"]:
        issues.append(
            runtime_issue(
                "fail",
                "tunnel",
                f"Overlay address {tunnel['overlay']['mux_ip']} is missing on {ifname}",
                command=f"ip -o -4 addr show dev {ifname}",
                repair_hint="Re-run muxer apply to restore the overlay address",
            )
        )

    if link_result.returncode != 0 or "UP" not in observed["link_show"]:
        issues.append(
            runtime_issue(
                "warn",
                "tunnel",
                f"Tunnel interface {ifname} is not reporting UP",
                command=f"ip -o link show dev {ifname}",
                repair_hint="Confirm the interface was recreated and brought up by muxer apply",
            )
        )

    return observed, issues


def check_policy_runtime(transport: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    rule_result = run(["ip", "rule", "show"], check=False)
    route_result = run(["ip", "route", "show", "table", str(transport["table_id"])], check=False)

    observed = {
        "ip_rule_show": output_or_error(rule_result),
        "route_table_show": output_or_error(route_result),
    }
    issues: List[Dict[str, str]] = []

    want_rule = f"fwmark {transport['mark_hex']} lookup {transport['table_id']}"
    if rule_result.returncode != 0 or want_rule not in observed["ip_rule_show"]:
        issues.append(
            runtime_issue(
                "fail",
                "policy",
                f"Missing ip rule for mark {transport['mark_hex']} -> table {transport['table_id']}",
                command="ip rule show",
                repair_hint="Re-run muxer apply to restore policy routing",
            )
        )

    want_route = f"default dev {transport['tunnel']['interface']}"
    if route_result.returncode != 0 or want_route not in observed["route_table_show"]:
        issues.append(
            runtime_issue(
                "fail",
                "policy",
                f"Missing default route in table {transport['table_id']} via {transport['tunnel']['interface']}",
                command=f"ip route show table {transport['table_id']}",
                repair_hint="Re-run muxer apply to restore the customer route table",
            )
        )

    return observed, issues


def collect_rule_checks(passthrough: Dict[str, Any]) -> List[Dict[str, str]]:
    nat_framework = passthrough.get("nat_framework", {}) or {}
    checks: List[Dict[str, str]] = []
    for group_name in (
        "filter_accept_rules",
        "mangle_mark_rules",
        "nat_prerouting_rules",
        "nat_postrouting_rules",
        "mangle_postrouting_rules",
    ):
        for rule in nat_framework.get(group_name, []):
            checks.append(
                {
                    "group": group_name,
                    "purpose": str(rule.get("purpose", "")),
                    "cli": str(rule.get("cli", "")),
                }
            )
    return checks


def check_iptables_runtime(
    passthrough: Dict[str, Any],
    *,
    expected_backend_ip: str,
    observed_backend_ip: str,
) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    checks = collect_rule_checks(passthrough)
    observed_rules: List[Dict[str, str]] = []
    issues: List[Dict[str, str]] = []
    migration_notes: List[Dict[str, str]] = []
    backend_rule_candidates = 0
    backend_rule_migrations = 0

    for rule in checks:
        ok, detail = iptables_check(rule["cli"])
        present = "yes" if ok else "no"
        matched_cli = rule["cli"]
        effective_detail = detail

        backend_rule_candidate = (
            not ok
            and expected_backend_ip
            and observed_backend_ip
            and expected_backend_ip != observed_backend_ip
            and expected_backend_ip in rule["cli"]
        )
        if backend_rule_candidate:
            backend_rule_candidates += 1
            migrated_cli = rule["cli"].replace(expected_backend_ip, observed_backend_ip)
            migrated_ok, migrated_detail = iptables_check(migrated_cli)
            if migrated_ok:
                present = "migrated"
                matched_cli = migrated_cli
                effective_detail = migrated_detail
                backend_rule_migrations += 1
                migration_notes.append(
                    {
                        "purpose": rule["purpose"],
                        "expected_backend_ip": expected_backend_ip,
                        "observed_backend_ip": observed_backend_ip,
                        "expected_cli": rule["cli"],
                        "observed_cli": migrated_cli,
                    }
                )

        observed_rules.append(
            {
                "group": rule["group"],
                "purpose": rule["purpose"],
                "present": present,
                "cli": rule["cli"],
                "matched_cli": matched_cli,
                "detail": effective_detail,
            }
        )
        if not ok and present != "migrated":
            issues.append(
                runtime_issue(
                    "fail",
                    "iptables",
                    f"Missing or mismatched iptables rule: {rule['purpose']}",
                    command=rule["cli"],
                    repair_hint="Re-run muxer apply to rebuild customer iptables state",
                )
            )

    return {
        "rules": observed_rules,
        "migration_notes": migration_notes,
        "backend_rule_candidates": backend_rule_candidates,
        "backend_rule_migrations": backend_rule_migrations,
    }, issues


def build_report(module: Dict[str, Any], muxer_doc: Dict[str, Any], config_root: Path) -> Dict[str, Any]:
    transport = derive_customer_transport(module, muxer_doc)
    passthrough = derive_passthrough_dataplane(module, muxer_doc)
    headend = derive_headend_return_path(module, str(muxer_doc.get("public_ip", "")).strip())
    post_ipsec_nat = derive_post_ipsec_nat(module)
    customer_module_path = local_customer_module_path(config_root, str(module["name"]))

    tunnel_observed, tunnel_issues = check_tunnel_runtime(transport)
    observed_backend_ip = str(tunnel_observed.get("observed_remote_ip") or "").strip()
    policy_observed, policy_issues = check_policy_runtime(transport)
    iptables_observed, iptables_issues = check_iptables_runtime(
        passthrough,
        expected_backend_ip=str(transport["backend_underlay_ip"]).strip(),
        observed_backend_ip=observed_backend_ip,
    )

    issues = list(tunnel_issues) + policy_issues + iptables_issues

    migration_consistent = bool(
        observed_backend_ip
        and observed_backend_ip != str(transport["backend_underlay_ip"]).strip()
        and iptables_observed.get("backend_rule_candidates", 0) > 0
        and iptables_observed.get("backend_rule_candidates", 0) == iptables_observed.get("backend_rule_migrations", 0)
    )

    if observed_backend_ip and observed_backend_ip != str(transport["backend_underlay_ip"]).strip():
        if migration_consistent:
            issues.insert(
                0,
                runtime_issue(
                    "warn",
                    "migration_drift",
                    (
                        "Expected backend config still points at "
                        f"{transport['backend_underlay_ip']}, but live runtime is consistently using "
                        f"{observed_backend_ip}"
                    ),
                    command=f"ip -d tunnel show {transport['tunnel']['interface']}",
                    repair_hint="Update the muxer customer source of truth so expected backend state matches the migrated live runtime",
                ),
            )
        else:
            issues.insert(
                0,
                runtime_issue(
                    "fail",
                    "tunnel",
                    f"Tunnel underlay drift detected on {transport['tunnel']['interface']}",
                    command=f"ip -d tunnel show {transport['tunnel']['interface']}",
                    repair_hint="Re-run muxer apply to rebuild the tunnel with the expected local/remote underlay IPs",
                ),
            )

    repairable = any(issue["status"] == "fail" for issue in issues)

    return {
        "customer": {
            "id": int(module["id"]),
            "name": str(module["name"]),
            "peer_ip": str(module["peer_ip"]),
            "class": "strict_non_nat" if strict_non_nat_customer(module) else "nat_t_or_custom",
            "protocols": module.get("protocols", {}) or {},
        },
        "muxer": {
            "config_root": str(config_root),
            "mode": str(muxer_doc.get("mode", "pass_through")),
            "public_ip": str(muxer_doc.get("public_ip", "")),
            "public_if": str(((muxer_doc.get("interfaces", {}) or {}).get("public_if", ""))),
            "inside_if": str(((muxer_doc.get("interfaces", {}) or {}).get("inside_if", ""))),
        },
        "transport": transport,
        "passthrough": passthrough,
        "headend_return": headend,
        "post_ipsec_nat": post_ipsec_nat,
        "artifacts": {
            "customer_module_path": str(customer_module_path),
            "present": customer_module_path.exists(),
        },
        "runtime": {
            "tunnel": tunnel_observed,
            "policy": policy_observed,
            "iptables": iptables_observed,
        },
        "diagnosis": {
            "expected_backend_underlay_ip": str(transport["backend_underlay_ip"]).strip(),
            "observed_backend_underlay_ip": observed_backend_ip,
            "migration_consistent": migration_consistent,
            "config_stale_after_migration": migration_consistent,
        },
        "issues": issues,
        "repairable": repairable,
    }


def print_list(modules: List[Dict[str, Any]], muxer_doc: Dict[str, Any]) -> None:
    rows: List[str] = []
    for module in modules:
        transport = derive_customer_transport(module, muxer_doc)
        protocols = module.get("protocols", {}) or {}
        proto_text = (
            f"500={bool(protocols.get('udp500', False))},"
            f"4500={bool(protocols.get('udp4500', False))},"
            f"esp={bool(protocols.get('esp50', False))}"
        )
        rows.append(
            f"{module['name']}: peer={module['peer_ip']} class="
            f"{'strict_non_nat' if strict_non_nat_customer(module) else 'nat_t_or_custom'} "
            f"mark={transport['mark_hex']} table={transport['table_id']} "
            f"tunnel={transport['tunnel']['interface']} backend={transport['backend_underlay_ip']} "
            f"proto({proto_text})"
        )
    for row in rows:
        print(row)


def print_report(report: Dict[str, Any]) -> None:
    customer = report["customer"]
    transport = report["transport"]
    passthrough = report["passthrough"]
    headend = report["headend_return"]
    post_ipsec_nat = report["post_ipsec_nat"]
    diagnosis = report["diagnosis"]
    issues = report["issues"]

    print(f"Customer: {customer['name']} (id={customer['id']})")
    print(f"Peer: {customer['peer_ip']}")
    print(f"Class: {customer['class']}")
    print(
        "Protocols: "
        f"udp500={customer['protocols'].get('udp500')} "
        f"udp4500={customer['protocols'].get('udp4500')} "
        f"esp50={customer['protocols'].get('esp50')}"
    )
    print("")
    print("Muxer role:")
    print(
        f"  public_ip={report['muxer']['public_ip']} "
        f"public_if={report['muxer']['public_if']} "
        f"inside_if={report['muxer']['inside_if']}"
    )
    print(f"  config_root={report['muxer']['config_root']}")
    print("")
    print("Derived transport:")
    print(f"  mark={transport['mark_hex']} table={transport['table_id']}")
    print(
        f"  tunnel={transport['tunnel']['interface']} mode={transport['tunnel']['mode']} "
        f"local={transport['local_underlay_ip']} remote={transport['backend_underlay_ip']}"
    )
    print(
        f"  overlay_mux={transport['tunnel']['overlay']['mux_ip']} "
        f"overlay_router={transport['tunnel']['overlay']['router_ip']}"
    )
    print("")
    print("Derived muxer delivery:")
    print(
        f"  public_identity={passthrough['nat_framework']['public_identity']} "
        f"eni_private_identity={passthrough['nat_framework']['eni_private_identity']}"
    )
    print(f"  backend_delivery_destination={passthrough['nat_framework']['backend_delivery_destination']}")
    print(
        f"  expected_backend_underlay={diagnosis['expected_backend_underlay_ip']} "
        f"observed_backend_underlay={diagnosis['observed_backend_underlay_ip'] or '-'}"
    )
    print(f"  customer_artifacts_present={report['artifacts']['present']}")
    print("")
    print("Head-end expectation:")
    print(f"  cluster_profile={headend['cluster_profile']}")
    print(f"  virtual_public_identity={headend['virtual_public_identity']}")
    print(f"  post_ipsec_nat_mode={post_ipsec_nat.get('mode')}")
    if post_ipsec_nat.get("enabled"):
        print(
            f"  translated_subnets={','.join(post_ipsec_nat.get('translated_subnets', [])) or '-'} "
            f"translated_source_ip={post_ipsec_nat.get('translated_source_ip') or '-'}"
        )
    print("")
    print("Runtime checks:")
    print(f"  tunnel_show={report['runtime']['tunnel']['tunnel_show'] or '-'}")
    print(f"  policy_rule_present={'no issues' if not [i for i in issues if i['area'] == 'policy'] else 'issues detected'}")
    missing_rules = [rule for rule in report["runtime"]["iptables"]["rules"] if rule["present"] == "no"]
    print(f"  iptables_missing_rules={len(missing_rules)}")
    if diagnosis["migration_consistent"]:
        print("  diagnosis=migrated runtime is internally consistent; expected backend config is stale")
    print("")
    if issues:
        print("Issues:")
        for issue in issues:
            print(f"  [{issue['status'].upper()}] {issue['area']}: {issue['summary']}")
            if issue["repair_hint"]:
                print(f"    repair_hint: {issue['repair_hint']}")
            if issue["command"]:
                print(f"    command: {issue['command']}")
    else:
        print("Issues: none")


def muxctl_entrypoint(config_root: Path) -> Path:
    installed = config_root / "src" / "muxctl.py"
    if installed.exists():
        return installed
    local = REPO_ROOT / "src" / "muxctl.py"
    if local.exists():
        return local
    raise SystemExit("Unable to find muxctl.py for repair actions")


def targeted_conntrack_flush(peer_ip: str) -> List[Dict[str, str]]:
    if not shutil.which("conntrack"):
        return [
            {
                "command": "conntrack",
                "result": "skipped",
                "detail": "conntrack command is not installed on this host",
            }
        ]

    events: List[Dict[str, str]] = []
    for cmd in (
        ["conntrack", "-D", "-s", peer_ip],
        ["conntrack", "-D", "-d", peer_ip],
    ):
        result = run(cmd, check=False)
        events.append(
            {
                "command": " ".join(cmd),
                "result": "ok" if result.returncode == 0 else "warn",
                "detail": output_or_error(result),
            }
        )
    return events


def do_repair(config_root: Path, report: Dict[str, Any], flush_peer_conntrack: bool) -> Dict[str, Any]:
    actions: List[Dict[str, Any]] = []
    if not report["repairable"]:
        actions.append({"action": "muxctl_apply", "result": "skipped", "detail": "No repairable muxer drift detected"})
    else:
        muxctl = muxctl_entrypoint(config_root)
        cmd = [sys.executable, str(muxctl), "apply"]
        result = run(cmd, check=False)
        actions.append(
            {
                "action": "muxctl_apply",
                "command": " ".join(cmd),
                "result": "ok" if result.returncode == 0 else "fail",
                "detail": output_or_error(result),
            }
        )

    if flush_peer_conntrack:
        peer_ip = str(report["customer"]["peer_ip"]).split("/")[0]
        actions.append(
            {
                "action": "conntrack_flush",
                "peer_ip": peer_ip,
                "events": targeted_conntrack_flush(peer_ip),
            }
        )

    return {"actions": actions}


def do_update_sot(
    module: Dict[str, Any],
    report: Dict[str, Any],
    muxer_doc: Dict[str, Any],
    source_backend: str,
    *,
    dry_run: bool,
) -> Dict[str, Any]:
    actions: List[Dict[str, Any]] = []
    diagnosis = report.get("diagnosis", {}) or {}
    effective_backend = normalize_source_backend(source_backend, muxer_doc)
    expected_backend_ip = str(diagnosis.get("expected_backend_underlay_ip") or "").strip()
    observed_backend_ip = str(diagnosis.get("observed_backend_underlay_ip") or "").strip()

    if not diagnosis.get("config_stale_after_migration"):
        actions.append(
            {
                "action": "update_sot",
                "result": "skipped",
                "detail": "Customer does not currently look like clean migration drift with stale SoT",
            }
        )
        return {
            "actions": actions,
            "eligible": False,
            "effective_backend": effective_backend,
        }

    if report.get("repairable"):
        actions.append(
            {
                "action": "update_sot",
                "result": "skipped",
                "detail": "Customer still has repairable muxer failures; refusing to write SoT",
            }
        )
        return {
            "actions": actions,
            "eligible": False,
            "effective_backend": effective_backend,
        }

    if not observed_backend_ip:
        actions.append(
            {
                "action": "update_sot",
                "result": "skipped",
                "detail": "Observed backend underlay IP is empty; nothing safe to write",
            }
        )
        return {
            "actions": actions,
            "eligible": False,
            "effective_backend": effective_backend,
        }

    if effective_backend != "dynamodb":
        actions.append(
            {
                "action": "update_sot",
                "result": "skipped",
                "detail": (
                    "update-sot currently supports only DynamoDB-backed customer SoT. "
                    f"Active backend is '{effective_backend}'."
                ),
            }
        )
        return {
            "actions": actions,
            "eligible": False,
            "effective_backend": effective_backend,
        }

    _backend, table_name, region = customer_sot_settings(muxer_doc)
    if not table_name:
        actions.append(
            {
                "action": "update_sot",
                "result": "skipped",
                "detail": "customer_sot.dynamodb.table_name is not configured in muxer.yaml",
            }
        )
        return {
            "actions": actions,
            "eligible": False,
            "effective_backend": effective_backend,
        }

    updated_module = copy.deepcopy(module)
    updated_module["backend_underlay_ip"] = observed_backend_ip
    source_ref = (
        "muxer_customer_doctor:update-sot:"
        + datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    action = {
        "action": "update_sot",
        "result": "dry_run" if dry_run else "ok",
        "detail": (
            f"backend_underlay_ip {expected_backend_ip} -> {observed_backend_ip} "
            f"in table {table_name}"
        ),
        "table_name": table_name,
        "region": region or "default",
        "customer": str(module.get("name", "")),
        "source_ref": source_ref,
        "before": expected_backend_ip,
        "after": observed_backend_ip,
    }

    if not dry_run:
        written = put_customer_module(
            updated_module,
            table_name=table_name,
            region=region or None,
            source_ref=source_ref,
        )
        action["items_written"] = written

    actions.append(action)
    return {
        "actions": actions,
        "eligible": True,
        "effective_backend": effective_backend,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect and repair muxer customer runtime state",
        epilog=(
            "Examples:\n"
            "  muxer_customer_doctor.py explain\n"
            "  muxer_customer_doctor.py list\n"
            "  muxer_customer_doctor.py show legacy-cust0001\n"
            "  muxer_customer_doctor.py repair legacy-cust0001 --flush-peer-conntrack\n"
            "  muxer_customer_doctor.py update-sot legacy-cust0001 --dry-run\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config-root",
        default=str(default_config_root()),
        help="Muxer install/config root. Defaults to /etc/muxer when present, otherwise the repo root.",
    )
    parser.add_argument(
        "--source",
        default="auto",
        choices=[
            "auto",
            "dynamodb",
            "ddb",
            "customer_modules",
            "modules",
            "local",
            "legacy_variables",
            "variables",
            "variables_file",
            "legacy_tunnels",
            "tunnels",
        ],
        help="Customer source backend override",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable output")

    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("explain", help="Explain what the script does and show copy/paste examples")
    sub.add_parser("list", help="List customers with key transport details")

    show_parser = sub.add_parser("show", help="Show the expected and observed state for one customer")
    show_parser.add_argument("customer")

    check_parser = sub.add_parser("check", help="Check one customer and report runtime drift")
    check_parser.add_argument("customer")

    repair_parser = sub.add_parser("repair", help="Run safe muxer repair for one customer")
    repair_parser.add_argument("customer")
    repair_parser.add_argument(
        "--flush-peer-conntrack",
        action="store_true",
        help="Also delete conntrack entries for the customer peer after muxer apply",
    )

    update_parser = sub.add_parser(
        "update-sot",
        help="Write a migrated backend underlay into the active customer source of truth",
    )
    update_parser.add_argument("customer")
    update_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the SoT change that would be written without modifying DynamoDB",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_root = Path(args.config_root).resolve()

    if args.cmd == "explain":
        print(EXPLAIN_TEXT)
        return

    muxer_doc, modules = load_muxer_state(config_root, args.source)

    if args.cmd == "list":
        if args.json:
            payload = []
            for module in modules:
                transport = derive_customer_transport(module, muxer_doc)
                payload.append(
                    {
                        "name": module["name"],
                        "peer_ip": module["peer_ip"],
                        "class": "strict_non_nat" if strict_non_nat_customer(module) else "nat_t_or_custom",
                        "mark": transport["mark_hex"],
                        "table": transport["table_id"],
                        "tunnel": transport["tunnel"]["interface"],
                        "backend_underlay_ip": transport["backend_underlay_ip"],
                        "protocols": module.get("protocols", {}) or {},
                    }
                )
            print(json.dumps(payload, indent=2))
            return

        print_list(modules, muxer_doc)
        return

    muxer_doc, customer = load_muxer_customer(config_root, args.source, args.customer)
    report = build_report(customer, muxer_doc, config_root)

    if args.cmd == "repair":
        repair_info = do_repair(config_root, report, args.flush_peer_conntrack)
        report = build_report(customer, muxer_doc, config_root)
        report["repair"] = repair_info
    elif args.cmd == "update-sot":
        customer_name = str(customer["name"])
        update_info = do_update_sot(customer, report, muxer_doc, args.source, dry_run=args.dry_run)
        if update_info.get("eligible") and not args.dry_run:
            muxer_doc, customer = load_muxer_customer(config_root, args.source, customer_name)
            report = build_report(customer, muxer_doc, config_root)
        report["update_sot"] = update_info

    if args.json:
        print(json.dumps(report, indent=2))
        return

    print_report(report)
    if args.cmd == "repair":
        print("")
        print("Repair actions:")
        for action in report["repair"]["actions"]:
            if action.get("action") == "conntrack_flush":
                print(f"  conntrack_flush peer={action['peer_ip']}")
                for event in action["events"]:
                    print(f"    {event['result']}: {event['command']} -> {event['detail'] or '-'}")
            else:
                print(f"  {action['action']}: {action['result']}")
                if action.get("command"):
                    print(f"    command: {action['command']}")
                if action.get("detail"):
                    print(f"    detail: {action['detail']}")
    elif args.cmd == "update-sot":
        print("")
        print("SoT update:")
        for action in report["update_sot"]["actions"]:
            print(f"  {action['action']}: {action['result']}")
            if action.get("detail"):
                print(f"    detail: {action['detail']}")
            if action.get("table_name"):
                print(f"    table_name: {action['table_name']}")
            if action.get("region"):
                print(f"    region: {action['region']}")
            if action.get("source_ref"):
                print(f"    source_ref: {action['source_ref']}")


if __name__ == "__main__":
    main()
