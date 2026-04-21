#!/usr/bin/env python
"""Plan and execute a one-customer RPDB removal."""

from __future__ import annotations

import argparse
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
if str(MUXER_SRC) not in sys.path:
    sys.path.insert(0, str(MUXER_SRC))

from muxerlib.customer_merge import load_yaml_file

from live_access_lib import (
    build_ssh_access_context,
    cleanup_ssh_access_context,
    run_remote_command,
)
from live_backend_lib import (
    delete_customer_backend_records,
    inspect_customer_backend_records,
)


PLACEHOLDER_VALUES = {
    "",
    "missing",
    "todo",
    "tbd",
    "placeholder",
    "unset",
    "none",
    "n/a",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


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


def environment_validation(environment: str, *, allow_live_apply: bool = False) -> tuple[int, dict[str, Any] | None, str, str]:
    command = [
        sys.executable,
        "scripts/customers/validate_deployment_environment.py",
        environment,
        "--json",
    ]
    if allow_live_apply:
        command.append("--allow-live-apply")
    return run_json(command)


def blocked_customers(environment_doc: dict[str, Any]) -> set[str]:
    customer_requests = environment_doc.get("customer_requests") or {}
    return {
        str(customer).strip()
        for customer in customer_requests.get("blocked_customers") or []
        if str(customer).strip()
    }


def reference_is_concrete(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and text.lower() not in PLACEHOLDER_VALUES


def typed_value(attribute: Any) -> Any:
    if not isinstance(attribute, dict):
        return attribute
    if "S" in attribute:
        return attribute["S"]
    if "N" in attribute:
        raw = str(attribute["N"])
        return int(raw) if raw.isdigit() else float(raw)
    if "BOOL" in attribute:
        return bool(attribute["BOOL"])
    if "NULL" in attribute:
        return None
    if "L" in attribute:
        return [typed_value(item) for item in attribute["L"]]
    if "M" in attribute:
        return {str(key): typed_value(value) for key, value in attribute["M"].items()}
    return attribute


def plain_item(typed_item: dict[str, Any] | None) -> dict[str, Any]:
    if not typed_item:
        return {}
    return {str(key): typed_value(value) for key, value in typed_item.items()}


def customer_metadata(typed_item: dict[str, Any] | None) -> dict[str, Any]:
    plain = plain_item(typed_item)
    customer_json: dict[str, Any] = {}
    raw_customer_json = plain.get("customer_json")
    if isinstance(raw_customer_json, str) and raw_customer_json.strip():
        try:
            parsed = json.loads(raw_customer_json)
            if isinstance(parsed, dict):
                customer_json = parsed
        except json.JSONDecodeError:
            customer_json = {}

    backend = customer_json.get("backend") or {}
    customer = customer_json.get("customer") or {}
    return {
        "customer_name": plain.get("customer_name"),
        "customer_class": plain.get("customer_class") or customer.get("customer_class"),
        "backend_cluster": plain.get("backend_cluster") or backend.get("cluster"),
        "backend_assignment": plain.get("backend_assignment") or backend.get("assignment"),
        "peer_ip": plain.get("peer_ip") or ((customer_json.get("peer") or {}).get("public_ip")),
        "fwmark": plain.get("fwmark"),
        "route_table": plain.get("route_table"),
        "rpdb_priority": plain.get("rpdb_priority"),
    }


def normalize_headend_family(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    if normalized in {"nat", "nat_t", "natt"}:
        return "nat"
    if normalized in {"non_nat", "nonnat", "strict_non_nat"}:
        return "non_nat"
    if normalized == "all":
        return "all"
    if normalized == "auto":
        return "auto"
    return ""


def headend_family_from_metadata(metadata: dict[str, Any], override: str) -> str:
    override_family = normalize_headend_family(override)
    if override_family and override_family != "auto":
        return override_family

    backend_cluster = normalize_headend_family(str(metadata.get("backend_cluster") or ""))
    customer_class = normalize_headend_family(str(metadata.get("customer_class") or ""))
    if backend_cluster in {"nat", "non_nat"}:
        return backend_cluster
    if customer_class == "nat":
        return "nat"
    if customer_class == "non_nat":
        return "non_nat"
    return ""


def nft_name(value: str, *, prefix: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", str(value).lower()).strip("_")
    normalized = normalized[:48] or "customer"
    return f"{prefix}_{normalized}"


def validate_customer_name(customer_name: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", customer_name):
        raise ValueError("customer name may only contain letters, numbers, dot, underscore, and dash")


def selected_headends(environment_doc: dict[str, Any], headend_family: str) -> list[dict[str, Any]]:
    headends = ((environment_doc.get("targets") or {}).get("headends") or {})
    if headend_family == "all":
        selected: list[dict[str, Any]] = []
        for family in ("nat", "non_nat"):
            pair = headends.get(family) or {}
            for ha_role in ("active", "standby"):
                node = pair.get(ha_role)
                if isinstance(node, dict):
                    selected.append({**node, "family": family, "ha_role": ha_role})
        return selected

    pair = headends.get(headend_family) or {}
    return [
        {**node, "family": headend_family, "ha_role": ha_role}
        for ha_role in ("active", "standby")
        for node in [pair.get(ha_role)]
        if isinstance(node, dict)
    ]


def selector_instance_id(target: dict[str, Any]) -> str:
    selector = target.get("selector") or {}
    if str(selector.get("type") or "").strip() != "instance_id":
        raise ValueError(f"target {target.get('name')} does not use an instance_id selector")
    instance_id = str(selector.get("value") or "").strip()
    if not instance_id:
        raise ValueError(f"target {target.get('name')} is missing selector.value")
    return instance_id


def sudo_shell(command_text: str, *, strict: bool = True) -> str:
    prefix = "set -eu; " if strict else "set +e; "
    return "sudo bash -lc " + shlex.quote(prefix + command_text)


def muxer_remove_command(customer_name: str) -> str:
    customer_q = shlex.quote(customer_name)
    mx_table = shlex.quote(nft_name(customer_name, prefix="rpdb_mx"))
    return "\n".join(
        [
            f"CUST={customer_q}",
            f"MX_TABLE={mx_table}",
            'CUSTOMER_ROOT="/var/lib/rpdb-muxer/customers/${CUST}"',
            'MODULE_ROOT="/etc/muxer/customer-modules/${CUST}"',
            'if [ -f "${CUSTOMER_ROOT}/remove-muxer-customer.sh" ]; then',
            '  bash "${CUSTOMER_ROOT}/remove-muxer-customer.sh"',
            'elif [ -f "${MODULE_ROOT}/customer-module.json" ] && [ -f /etc/muxer/src/muxctl.py ]; then',
            '  python3 /etc/muxer/src/muxctl.py remove-customer "${CUST}"',
            "fi",
            'nft delete table ip "${MX_TABLE}" 2>/dev/null || true',
            'rm -rf "${CUSTOMER_ROOT}" "${MODULE_ROOT}"',
            'test ! -e "${CUSTOMER_ROOT}"',
            'test ! -e "${MODULE_ROOT}"',
            'if nft list table ip "${MX_TABLE}" >/dev/null 2>&1; then',
            '  echo "muxer nftables table still exists: ${MX_TABLE}"',
            "  exit 31",
            "fi",
            'echo "removed_muxer_customer=${CUST}"',
        ]
    )


def headend_remove_command(customer_name: str) -> str:
    customer_q = shlex.quote(customer_name)
    hn_table = shlex.quote(nft_name(customer_name, prefix="rpdb_hn"))
    on_table = shlex.quote(nft_name(customer_name, prefix="rpdb_on"))
    return "\n".join(
        [
            f"CUST={customer_q}",
            f"HN_TABLE={hn_table}",
            f"ON_TABLE={on_table}",
            'CUSTOMER_ROOT="/var/lib/rpdb-headend/customers/${CUST}"',
            'SWANCTL_CONF="/etc/swanctl/conf.d/rpdb-customers/${CUST}.conf"',
            'if [ -f "${CUSTOMER_ROOT}/remove-headend-customer.sh" ]; then',
            '  bash "${CUSTOMER_ROOT}/remove-headend-customer.sh"',
            "else",
            '  rm -f "${SWANCTL_CONF}"',
            '  nft delete table ip "${HN_TABLE}" 2>/dev/null || true',
            '  nft delete table ip "${ON_TABLE}" 2>/dev/null || true',
            "fi",
            'rm -rf "${CUSTOMER_ROOT}"',
            'rm -f "${SWANCTL_CONF}"',
            'nft delete table ip "${HN_TABLE}" 2>/dev/null || true',
            'nft delete table ip "${ON_TABLE}" 2>/dev/null || true',
            'if command -v swanctl >/dev/null 2>&1 && systemctl is-active --quiet strongswan; then',
            "  swanctl --load-all",
            "fi",
            'test ! -e "${CUSTOMER_ROOT}"',
            'test ! -e "${SWANCTL_CONF}"',
            'if nft list table ip "${HN_TABLE}" >/dev/null 2>&1; then',
            '  echo "head-end post-IPsec NAT nftables table still exists: ${HN_TABLE}"',
            "  exit 41",
            "fi",
            'if nft list table ip "${ON_TABLE}" >/dev/null 2>&1; then',
            '  echo "head-end outside NAT nftables table still exists: ${ON_TABLE}"',
            "  exit 42",
            "fi",
            'echo "removed_headend_customer=${CUST}"',
        ]
    )


def build_touch_plan(
    *,
    environment_doc: dict[str, Any],
    customer_name: str,
    headend_family: str,
    backend: dict[str, Any],
) -> dict[str, Any]:
    datastores = environment_doc.get("datastores") or {}
    targets = environment_doc.get("targets") or {}
    muxer = targets.get("muxer") or {}
    headends = selected_headends(environment_doc, headend_family)
    return {
        "customer_name": customer_name,
        "customer_sot_table": datastores.get("customer_sot_table"),
        "allocation_table": datastores.get("allocation_table"),
        "customer_present": backend.get("customer_present"),
        "allocation_count": backend.get("allocation_count"),
        "headend_family": headend_family,
        "muxer": muxer.get("name"),
        "headends": [
            {
                "family": headend.get("family"),
                "ha_role": headend.get("ha_role"),
                "target_role": headend.get("role"),
                "name": headend.get("name"),
                "instance_id": ((headend.get("selector") or {}).get("value")),
            }
            for headend in headends
        ],
    }


def execute_live_remove(
    *,
    customer_name: str,
    environment_doc: dict[str, Any],
    headend_family: str,
    out_dir: Path,
) -> dict[str, Any]:
    environment = environment_doc.get("environment") or {}
    region = str((environment.get("aws") or {}).get("region") or "").strip()
    if not region:
        raise RuntimeError("environment.aws.region is required")
    ssh_user = str(((environment.get("access") or {}).get("ssh") or {}).get("user") or "").strip()
    if not ssh_user:
        raise RuntimeError("environment.access.ssh.user is required")

    datastores = environment_doc.get("datastores") or {}
    customer_table = str(datastores.get("customer_sot_table") or "").strip()
    allocation_table = str(datastores.get("allocation_table") or "").strip()
    if not customer_table or not allocation_table:
        raise RuntimeError("deployment environment datastores are incomplete")

    targets = environment_doc.get("targets") or {}
    muxer = targets.get("muxer") or {}
    muxer_instance_id = selector_instance_id(muxer)
    headends = selected_headends(environment_doc, headend_family)
    headend_instance_ids = [selector_instance_id(headend) for headend in headends]

    journal: list[dict[str, Any]] = []
    context = build_ssh_access_context(
        region=region,
        ssh_user=ssh_user,
        bastion_instance_id=muxer_instance_id,
        target_instance_ids=[muxer_instance_id, *headend_instance_ids],
    )
    try:
        for headend in reversed(headends):
            instance_id = selector_instance_id(headend)
            result = run_remote_command(
                context=context,
                target_instance_id=instance_id,
                via_bastion=True,
                remote_command=sudo_shell(headend_remove_command(customer_name), strict=True),
                timeout_seconds=300,
            )
            journal.append(
                {
                    "recorded_at": utc_now(),
                    "action": "remove_headend_customer",
                    "target": headend.get("name"),
                    "instance_id": instance_id,
                    "family": headend.get("family"),
                    "ha_role": headend.get("ha_role"),
                    "target_role": headend.get("role"),
                    "success": result.get("success"),
                    "stdout": result.get("stdout"),
                    "stderr": result.get("stderr"),
                }
            )
            if not result.get("success"):
                raise RuntimeError(f"head-end remove failed for {headend.get('name')}: {result.get('stderr') or result.get('stdout')}")

        muxer_result = run_remote_command(
            context=context,
            target_instance_id=muxer_instance_id,
            via_bastion=False,
            remote_command=sudo_shell(muxer_remove_command(customer_name), strict=True),
            timeout_seconds=300,
        )
        journal.append(
            {
                "recorded_at": utc_now(),
                "action": "remove_muxer_customer",
                "target": muxer.get("name"),
                "instance_id": muxer_instance_id,
                "success": muxer_result.get("success"),
                "stdout": muxer_result.get("stdout"),
                "stderr": muxer_result.get("stderr"),
            }
        )
        if not muxer_result.get("success"):
            raise RuntimeError(f"muxer remove failed for {muxer.get('name')}: {muxer_result.get('stderr') or muxer_result.get('stdout')}")

        backend_result = delete_customer_backend_records(
            region=region,
            customer_table=customer_table,
            allocation_table=allocation_table,
            customer_name=customer_name,
        )
        journal.append(
            {
                "recorded_at": utc_now(),
                "action": "remove_backend_customer",
                "target": "dynamodb",
                "success": backend_result.get("status") == "removed",
                "payload": backend_result,
            }
        )
        if backend_result.get("status") != "removed":
            raise RuntimeError("backend removal failed: " + "; ".join(backend_result.get("errors") or []))

        result = {
            "schema_version": 1,
            "action": "remove_customer",
            "customer_name": customer_name,
            "status": "removed",
            "generated_at": utc_now(),
            "headend_family": headend_family,
            "backend": backend_result,
            "journal": repo_relative(out_dir / "remove-journal.json"),
        }
        write_json(out_dir / "remove-journal.json", {"schema_version": 1, "customer_name": customer_name, "steps": journal})
        write_json(out_dir / "remove-result.json", result)
        return result
    except Exception as exc:
        result = {
            "schema_version": 1,
            "action": "remove_customer",
            "customer_name": customer_name,
            "status": "blocked",
            "generated_at": utc_now(),
            "headend_family": headend_family,
            "error": str(exc),
            "journal": repo_relative(out_dir / "remove-journal.json"),
        }
        write_json(out_dir / "remove-journal.json", {"schema_version": 1, "customer_name": customer_name, "steps": journal})
        write_json(out_dir / "remove-result.json", result)
        return result
    finally:
        cleanup_ssh_access_context(context)


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or execute one RPDB customer removal.")
    parser.add_argument("--customer-name", required=True, help="Customer name to remove")
    parser.add_argument("--environment", required=True, help="Deployment environment name or file")
    parser.add_argument(
        "--headend-family",
        default="auto",
        choices=["auto", "nat", "non_nat", "all"],
        help="Override head-end target selection. Default reads the live SoT.",
    )
    parser.add_argument("--out-dir", help="Output directory for execution plan and removal journal")
    parser.add_argument("--dry-run", action="store_true", help="Plan only. This is the default.")
    parser.add_argument("--approve", action="store_true", help="Execute the approved live removal")
    parser.add_argument("--json", action="store_true", help="Print the execution plan or removal result as JSON")
    args = parser.parse_args()

    customer_name = args.customer_name.strip()
    validate_customer_name(customer_name)
    out_dir = (
        Path(args.out_dir).resolve()
        if args.out_dir
        else (REPO_ROOT / "build" / "customer-remove" / customer_name).resolve()
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    env_code, env_validation, env_stdout, env_stderr = environment_validation(
        args.environment,
        allow_live_apply=True,
    )
    environment_doc: dict[str, Any] | None = None
    if env_code != 0 or not env_validation or not env_validation.get("valid"):
        errors.append(f"deployment environment validation failed: {env_stderr or env_stdout}".strip())
    else:
        environment_doc = load_yaml_file(Path(str(env_validation["environment_file"])))

    if environment_doc and customer_name in blocked_customers(environment_doc):
        errors.append(f"customer {customer_name} is blocked by deployment environment policy")

    backend: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    headend_family = ""
    if environment_doc and not errors:
        environment = environment_doc.get("environment") or {}
        datastores = environment_doc.get("datastores") or {}
        region = str((environment.get("aws") or {}).get("region") or "").strip()
        customer_table = str(datastores.get("customer_sot_table") or "").strip()
        allocation_table = str(datastores.get("allocation_table") or "").strip()
        if str(datastores.get("mode") or "").strip() != "dynamodb":
            errors.append("remove_customer currently supports datastores.mode=dynamodb only")
        elif not region or not customer_table or not allocation_table:
            errors.append("deployment environment AWS/datastore settings are incomplete")
        else:
            backend = inspect_customer_backend_records(
                region=region,
                customer_table=customer_table,
                allocation_table=allocation_table,
                customer_name=customer_name,
            )
            metadata = customer_metadata(backend.get("customer_item"))
            if not backend.get("customer_present"):
                errors.append(f"customer {customer_name} is not present in the customer SoT")
            headend_family = headend_family_from_metadata(metadata, args.headend_family)
            if not headend_family:
                errors.append("unable to determine head-end family from SoT; use --headend-family nat|non_nat|all")

    owners = ((environment_doc or {}).get("owners") or {})
    backup_refs = ((environment_doc or {}).get("backups") or {})
    owner_status = {
        "validation": reference_is_concrete(owners.get("validation")),
        "rollback": reference_is_concrete(owners.get("rollback")),
    }
    backup_status = {
        "baseline_root": reference_is_concrete(backup_refs.get("baseline_root")),
        "muxer": reference_is_concrete(backup_refs.get("muxer")),
        "selected_headend": reference_is_concrete(
            backup_refs.get("nat_headend" if headend_family == "nat" else "non_nat_headend")
        )
        if headend_family in {"nat", "non_nat"}
        else reference_is_concrete(backup_refs.get("nat_headend")) and reference_is_concrete(backup_refs.get("non_nat_headend")),
    }
    for key, present in owner_status.items():
        if not present:
            errors.append(f"owner reference missing for {key}")
    for key, present in backup_status.items():
        if not present:
            errors.append(f"backup reference missing for {key}")

    environment_live_apply = (((environment_doc or {}).get("environment") or {}).get("live_apply") or {})
    environment_access_method = str(
        (((environment_doc or {}).get("environment") or {}).get("access") or {}).get("method") or ""
    ).strip()
    if args.approve:
        if environment_access_method != "ssh":
            errors.append("approved remove currently supports environment.access.method=ssh only")
        if not bool(environment_live_apply.get("enabled")):
            errors.append("environment live_apply.enabled is false")

    status = "ready_to_remove" if not errors else "blocked"
    touch_plan = (
        build_touch_plan(
            environment_doc=environment_doc or {},
            customer_name=customer_name,
            headend_family=headend_family,
            backend=backend,
        )
        if environment_doc and headend_family
        else {}
    )
    execution_plan = {
        "schema_version": 1,
        "action": "remove_customer",
        "phase": "phase_remove_customer",
        "status": status,
        "dry_run": not bool(args.approve),
        "approved": bool(args.approve),
        "live_remove": False,
        "generated_at": utc_now(),
        "customer_name": customer_name,
        "errors": errors,
        "environment": {
            "name": ((environment_doc or {}).get("environment") or {}).get("name"),
            "validation": env_validation,
        },
        "backend": {
            "customer_present": backend.get("customer_present"),
            "allocation_count": backend.get("allocation_count"),
            "metadata": metadata,
        },
        "headend_family": headend_family,
        "owner_status": owner_status,
        "backup_status": backup_status,
        "touch_plan": touch_plan,
        "execution_order": [
            "validate_deployment_environment",
            "enforce_blocked_customers",
            "inspect_customer_sot",
            "resolve_headend_family",
            "validate_backup_and_owner_references",
            "write_execution_plan",
            "remove_headend_customer_standby",
            "remove_headend_customer_active",
            "remove_muxer_customer",
            "remove_backend_customer",
            "write_remove_journal",
        ],
        "live_gate": {
            "status": status,
            "approve_supported": environment_access_method == "ssh",
            "allow_live_remove_now": status == "ready_to_remove",
            "no_live_nodes_touched": not bool(args.approve),
            "no_dynamodb_writes": not bool(args.approve),
        },
        "artifacts": {
            "remove_dir": repo_relative(out_dir),
            "execution_plan": repo_relative(out_dir / "execution-plan.json"),
            "remove_journal": repo_relative(out_dir / "remove-journal.json"),
            "remove_result": repo_relative(out_dir / "remove-result.json"),
        },
    }
    write_json(out_dir / "execution-plan.json", execution_plan)

    if args.approve and not errors:
        remove_result = execute_live_remove(
            customer_name=customer_name,
            environment_doc=environment_doc or {},
            headend_family=headend_family,
            out_dir=out_dir,
        )
        execution_plan["status"] = remove_result.get("status")
        execution_plan["live_remove"] = remove_result.get("status") == "removed"
        execution_plan["live_gate"] = {
            "status": remove_result.get("status"),
            "approve_supported": True,
            "allow_live_remove_now": remove_result.get("status") == "removed",
            "no_live_nodes_touched": False,
            "no_dynamodb_writes": False,
        }
        execution_plan["remove"] = remove_result
        if remove_result.get("status") != "removed":
            execution_plan["errors"] = [str(remove_result.get("error") or "approved remove did not complete")]
        write_json(out_dir / "execution-plan.json", execution_plan)

    if args.json:
        print(json.dumps(execution_plan, indent=2, sort_keys=True))
    else:
        mode = "approved remove" if args.approve else "dry-run remove"
        print(f"Customer {mode}: {execution_plan['status']}")
        print(f"- customer: {customer_name}")
        print(f"- execution plan: {repo_relative(out_dir / 'execution-plan.json')}")
        for error in execution_plan.get("errors") or []:
            print(f"  error: {error}")

    return 0 if not execution_plan.get("errors") and execution_plan.get("status") in {"ready_to_remove", "removed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
