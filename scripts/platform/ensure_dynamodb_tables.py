#!/usr/bin/env python
"""Inspect and optionally create the DynamoDB tables used by the platform."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MUXER_PARAMS = REPO_ROOT / "infra" / "cfn" / "parameters.single-muxer.us-east-1.json"
DEFAULT_NAT_PARAMS = REPO_ROOT / "infra" / "cfn" / "parameters.vpn-headend.nat.graviton-efs.us-east-1.json"
DEFAULT_NONNAT_PARAMS = REPO_ROOT / "infra" / "cfn" / "parameters.vpn-headend.non-nat.graviton-efs.us-east-1.json"


def _load_parameter_map(path: Path) -> Dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"expected CloudFormation parameter array in {path}")
    result: Dict[str, str] = {}
    for item in payload:
        key = str(item.get("ParameterKey") or "").strip()
        if not key:
            continue
        result[key] = str(item.get("ParameterValue") or "").strip()
    return result


def _aws_dynamodb_base(region: str | None = None) -> List[str]:
    command = ["aws", "dynamodb"]
    if region:
        command.extend(["--region", region])
    return command


def _describe_table(table_name: str, region: str | None = None) -> Dict[str, Any]:
    completed = subprocess.run(
        _aws_dynamodb_base(region) + ["describe-table", "--table-name", table_name],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode == 0:
        payload = json.loads(completed.stdout or "{}")
        return {
            "exists": True,
            "table_status": ((payload.get("Table") or {}).get("TableStatus") or ""),
            "billing_mode": (((payload.get("Table") or {}).get("BillingModeSummary") or {}).get("BillingMode") or ""),
        }

    stderr = completed.stderr or ""
    if "ResourceNotFoundException" in stderr:
        return {
            "exists": False,
            "table_status": "",
            "billing_mode": "",
        }

    raise subprocess.CalledProcessError(
        completed.returncode,
        completed.args,
        output=completed.stdout,
        stderr=completed.stderr,
    )


def _ensure_table(table_name: str, hash_key: str, region: str | None = None) -> bool:
    described = _describe_table(table_name, region=region)
    if described["exists"]:
        return False

    create = subprocess.run(
        _aws_dynamodb_base(region)
        + [
            "create-table",
            "--table-name",
            table_name,
            "--attribute-definitions",
            f"AttributeName={hash_key},AttributeType=S",
            "--key-schema",
            f"AttributeName={hash_key},KeyType=HASH",
            "--billing-mode",
            "PAY_PER_REQUEST",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if create.returncode != 0 and "ResourceInUseException" not in (create.stderr or ""):
        raise subprocess.CalledProcessError(
            create.returncode,
            create.args,
            output=create.stdout,
            stderr=create.stderr,
        )

    subprocess.run(
        _aws_dynamodb_base(region) + ["wait", "table-exists", "--table-name", table_name],
        text=True,
        capture_output=True,
        check=True,
    )
    return True


def _lease_entry(role: str, path: Path, params: Dict[str, str]) -> Dict[str, Any]:
    table_name = params.get("LeaseTableName", "").strip()
    cluster_name = params.get("ClusterName", "").strip()
    explicit = bool(table_name)
    return {
        "role": role,
        "source_params": str(path),
        "cluster_name": cluster_name,
        "table_name": table_name or None,
        "key_schema": "cluster_id (HASH, String)",
        "mode": "explicit-name" if explicit else "stack-managed-by-cloudformation",
        "note": (
            "Table will be created or validated by this helper."
            if explicit
            else "Current production-shaped params leave LeaseTableName empty, so CloudFormation creates a stack-managed table."
        ),
    }


def _default_allocation_table_name(customer_sot_table: str) -> str:
    return f"{customer_sot_table}-allocations"


def _build_report(
    muxer_params_path: Path,
    nat_params_path: Path,
    nonnat_params_path: Path,
    region: str | None,
    allocation_table_name: str,
) -> Dict[str, Any]:
    muxer_params = _load_parameter_map(muxer_params_path)
    nat_params = _load_parameter_map(nat_params_path)
    nonnat_params = _load_parameter_map(nonnat_params_path)

    customer_sot_table = muxer_params.get("CustomerSotTableName", "").strip()
    if not customer_sot_table:
        raise ValueError(f"CustomerSotTableName is missing in {muxer_params_path}")

    return {
        "region": region or "default",
        "customer_sot": {
            "source_params": str(muxer_params_path),
            "table_name": customer_sot_table,
            "key_schema": "customer_name (HASH, String)",
            "mode": "explicit-name-from-muxer-params",
            "note": "This table is not auto-created by the imported single-muxer template and should be ensured before customer sync.",
        },
        "resource_allocations": {
            "source_params": str(muxer_params_path),
            "table_name": allocation_table_name or _default_allocation_table_name(customer_sot_table),
            "key_schema": "resource_key (HASH, String)",
            "mode": "explicit-name-derived-from-customer-sot",
            "note": "This table tracks exclusive namespace reservations such as fwmark, route_table, rpdb_priority, tunnel_key, overlay_block, and interface names.",
        },
        "lease_tables": [
            _lease_entry("nat_headend_pair", nat_params_path, nat_params),
            _lease_entry("nonnat_headend_pair", nonnat_params_path, nonnat_params),
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect and optionally create platform DynamoDB tables.")
    parser.add_argument("--muxer-params", default=str(DEFAULT_MUXER_PARAMS), help="Path to the single-muxer parameter file")
    parser.add_argument("--nat-headend-params", default=str(DEFAULT_NAT_PARAMS), help="Path to the NAT head-end parameter file")
    parser.add_argument(
        "--nonnat-headend-params",
        default=str(DEFAULT_NONNAT_PARAMS),
        help="Path to the non-NAT head-end parameter file",
    )
    parser.add_argument("--region", default="", help="Optional AWS region override for DynamoDB calls")
    parser.add_argument("--check-aws", action="store_true", help="Describe the tables in AWS and include existence/status in the report")
    parser.add_argument("--create-customer-sot", action="store_true", help="Create the customer SoT table if it does not exist")
    parser.add_argument(
        "--allocation-table-name",
        default="",
        help="Optional explicit name for the resource allocation table. Defaults to <customer_sot>-allocations.",
    )
    parser.add_argument(
        "--create-resource-allocation-table",
        action="store_true",
        help="Create the resource allocation table if it does not exist",
    )
    parser.add_argument(
        "--create-explicit-lease-tables",
        action="store_true",
        help="Create any explicitly named lease tables if they do not exist",
    )
    parser.add_argument("--json", action="store_true", help="Print the report as JSON")
    args = parser.parse_args()

    region = args.region or None
    report = _build_report(
        Path(args.muxer_params).resolve(),
        Path(args.nat_headend_params).resolve(),
        Path(args.nonnat_headend_params).resolve(),
        region,
        str(args.allocation_table_name or "").strip(),
    )

    customer_sot = report["customer_sot"]
    resource_allocations = report["resource_allocations"]
    lease_tables = report["lease_tables"]

    if args.check_aws or args.create_customer_sot:
        customer_sot["aws"] = _describe_table(customer_sot["table_name"], region=region)
    if args.create_customer_sot:
        customer_sot["created"] = _ensure_table(customer_sot["table_name"], hash_key="customer_name", region=region)
        customer_sot["aws"] = _describe_table(customer_sot["table_name"], region=region)

    if args.check_aws or args.create_resource_allocation_table:
        resource_allocations["aws"] = _describe_table(resource_allocations["table_name"], region=region)
    if args.create_resource_allocation_table:
        resource_allocations["created"] = _ensure_table(
            resource_allocations["table_name"],
            hash_key="resource_key",
            region=region,
        )
        resource_allocations["aws"] = _describe_table(resource_allocations["table_name"], region=region)

    for entry in lease_tables:
        table_name = entry["table_name"]
        if not table_name:
            entry["created"] = False
            entry["aws"] = None
            continue
        if args.check_aws or args.create_explicit_lease_tables:
            entry["aws"] = _describe_table(table_name, region=region)
        else:
            entry["aws"] = None
        if args.create_explicit_lease_tables:
            entry["created"] = _ensure_table(table_name, hash_key="cluster_id", region=region)
            entry["aws"] = _describe_table(table_name, region=region)
        else:
            entry["created"] = False

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("DynamoDB bootstrap plan")
        print(f"- region: {report['region']}")
        print(f"- customer_sot: {customer_sot['table_name']} [{customer_sot['key_schema']}]")
        print(f"  note: {customer_sot['note']}")
        if customer_sot.get("aws") is not None:
            print(f"  aws: exists={customer_sot['aws']['exists']} status={customer_sot['aws']['table_status'] or 'n/a'}")
        if "created" in customer_sot:
            print(f"  created: {customer_sot['created']}")

        print(f"- resource_allocations: {resource_allocations['table_name']} [{resource_allocations['key_schema']}]")
        print(f"  note: {resource_allocations['note']}")
        if resource_allocations.get("aws") is not None:
            print(
                "  aws: exists="
                f"{resource_allocations['aws']['exists']} "
                f"status={resource_allocations['aws']['table_status'] or 'n/a'}"
            )
        if "created" in resource_allocations:
            print(f"  created: {resource_allocations['created']}")

        for entry in lease_tables:
            table_label = entry["table_name"] or "<stack-managed>"
            print(f"- {entry['role']}: {table_label} [{entry['key_schema']}]")
            print(f"  cluster: {entry['cluster_name']}")
            print(f"  mode: {entry['mode']}")
            print(f"  note: {entry['note']}")
            if entry.get("aws") is not None:
                print(f"  aws: exists={entry['aws']['exists']} status={entry['aws']['table_status'] or 'n/a'}")
            if "created" in entry:
                print(f"  created: {entry['created']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
