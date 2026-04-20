"""DynamoDB helpers for RPDB exclusive allocation tracking."""

from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List


def _aws_dynamodb_base(region: str | None = None) -> List[str]:
    command = ["aws", "dynamodb"]
    if region:
        command.extend(["--region", region])
    return command


def _write_temp_json(payload: Dict[str, Any]) -> Path:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(payload, handle)
        return Path(handle.name)


def build_resource_key(record: Dict[str, Any]) -> str:
    return f"{record['resource_type']}#{record['resource_value']}"


def build_allocation_ddb_item(
    record: Dict[str, Any],
    *,
    allocated_at: str | None = None,
) -> Dict[str, Any]:
    timestamp = allocated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    item: Dict[str, Any] = {
        "resource_key": {"S": build_resource_key(record)},
        "resource_type": {"S": str(record["resource_type"])},
        "resource_value": {"S": str(record["resource_value"])},
        "pool_name": {"S": str(record["pool_name"])},
        "customer_name": {"S": str(record["customer_name"])},
        "customer_id": {"N": str(int(record["customer_id"]))},
        "customer_class": {"S": str(record["customer_class"])},
        "status": {"S": "allocated"},
        "allocated_at": {"S": timestamp},
        "source_ref": {"S": str(record["source_ref"])},
        "exclusive": {"BOOL": bool(record["exclusive"])},
    }
    return item


def build_exclusive_allocation_ddb_items(
    records: Iterable[Dict[str, Any]],
    *,
    allocated_at: str | None = None,
) -> List[Dict[str, Any]]:
    return [
        build_allocation_ddb_item(record, allocated_at=allocated_at)
        for record in records
        if bool(record.get("exclusive"))
    ]


def get_allocation_item(
    table_name: str,
    resource_type: str,
    resource_value: str,
    region: str | None = None,
) -> Dict[str, Any] | None:
    key_doc = {"resource_key": {"S": f"{resource_type}#{resource_value}"}}
    temp_path = _write_temp_json(key_doc)
    try:
        raw = subprocess.check_output(
            _aws_dynamodb_base(region)
            + ["get-item", "--table-name", table_name, "--key", f"file://{temp_path}"],
            text=True,
        )
    finally:
        temp_path.unlink(missing_ok=True)

    item = json.loads(raw).get("Item")
    if not isinstance(item, dict):
        return None
    return item


def put_exclusive_allocation_records(
    records: Iterable[Dict[str, Any]],
    table_name: str,
    region: str | None = None,
) -> int:
    written = 0
    for item in build_exclusive_allocation_ddb_items(records):
        temp_path = _write_temp_json(item)
        try:
            subprocess.run(
                _aws_dynamodb_base(region)
                + [
                    "put-item",
                    "--table-name",
                    table_name,
                    "--item",
                    f"file://{temp_path}",
                    "--condition-expression",
                    "attribute_not_exists(resource_key)",
                ],
                text=True,
                capture_output=True,
                check=True,
            )
            written += 1
        finally:
            temp_path.unlink(missing_ok=True)
    return written


def delete_exclusive_allocation_records(
    records: Iterable[Dict[str, Any]],
    table_name: str,
    region: str | None = None,
) -> int:
    deleted = 0
    for record in records:
        if not bool(record.get("exclusive")):
            continue
        key_doc = {"resource_key": {"S": build_resource_key(record)}}
        temp_path = _write_temp_json(key_doc)
        try:
            subprocess.run(
                _aws_dynamodb_base(region)
                + [
                    "delete-item",
                    "--table-name",
                    table_name,
                    "--key",
                    f"file://{temp_path}",
                ],
                text=True,
                capture_output=True,
                check=True,
            )
            deleted += 1
        finally:
            temp_path.unlink(missing_ok=True)
    return deleted
