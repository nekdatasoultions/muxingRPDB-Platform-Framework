"""AWS-backed customer backend apply helpers."""

from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def aws_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("AWS_CLI_FILE_ENCODING", "utf-8")
    return env


def _run_aws(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["aws", *args],
        text=True,
        capture_output=True,
        check=False,
        env=aws_env(),
    )


def _run_aws_json(args: list[str]) -> dict[str, Any]:
    completed = _run_aws(args)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip() or "AWS CLI command failed")
    stdout = completed.stdout.strip()
    return json.loads(stdout or "{}")


def _write_temp_json(payload: Any) -> Path:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        suffix=".json",
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        return Path(handle.name)


def _serialize_attribute(value: Any) -> dict[str, Any]:
    if value is None:
        return {"NULL": True}
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, int):
        return {"N": str(value)}
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError("DynamoDB number values must be finite")
        return {"N": format(value, ".15g")}
    if isinstance(value, str):
        return {"S": value}
    if isinstance(value, list):
        return {"L": [_serialize_attribute(item) for item in value]}
    if isinstance(value, dict):
        return {"M": {str(key): _serialize_attribute(nested) for key, nested in value.items()}}
    raise TypeError(f"unsupported DynamoDB attribute type: {type(value).__name__}")


def serialize_plain_item(item: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _serialize_attribute(value) for key, value in item.items()}


def describe_table(region: str, table_name: str) -> dict[str, Any]:
    payload = _run_aws_json(
        [
            "dynamodb",
            "describe-table",
            "--region",
            region,
            "--table-name",
            table_name,
            "--output",
            "json",
        ]
    )
    return payload.get("Table") or {}


def table_key_names(region: str, table_name: str) -> list[str]:
    table = describe_table(region, table_name)
    key_schema = table.get("KeySchema") or []
    key_names = [str(item.get("AttributeName") or "").strip() for item in key_schema]
    return [name for name in key_names if name]


def extract_key(item: dict[str, Any], key_names: list[str]) -> dict[str, Any]:
    key = {name: item[name] for name in key_names if name in item}
    missing = [name for name in key_names if name not in key]
    if missing:
        raise ValueError("item missing DynamoDB key attribute(s): " + ", ".join(missing))
    return key


def get_typed_item(region: str, table_name: str, key: dict[str, Any]) -> dict[str, Any] | None:
    key_path = _write_temp_json(key)
    try:
        payload = _run_aws_json(
            [
                "dynamodb",
                "get-item",
                "--region",
                region,
                "--table-name",
                table_name,
                "--key",
                f"file://{key_path}",
                "--consistent-read",
                "--output",
                "json",
            ]
        )
    finally:
        try:
            key_path.unlink()
        except OSError:
            pass
    item = payload.get("Item")
    return item if isinstance(item, dict) else None


def put_typed_item(region: str, table_name: str, item: dict[str, Any]) -> None:
    item_path = _write_temp_json(item)
    try:
        completed = _run_aws(
            [
                "dynamodb",
                "put-item",
                "--region",
                region,
                "--table-name",
                table_name,
                "--item",
                f"file://{item_path}",
                "--output",
                "json",
            ]
        )
    finally:
        try:
            item_path.unlink()
        except OSError:
            pass
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip() or "AWS put-item failed")


def delete_typed_item(region: str, table_name: str, key: dict[str, Any]) -> None:
    key_path = _write_temp_json(key)
    try:
        completed = _run_aws(
            [
                "dynamodb",
                "delete-item",
                "--region",
                region,
                "--table-name",
                table_name,
                "--key",
                f"file://{key_path}",
                "--output",
                "json",
            ]
        )
    finally:
        try:
            key_path.unlink()
        except OSError:
            pass
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip() or "AWS delete-item failed")


def load_customer_backend_payloads(package_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    customer_item = json.loads((package_dir / "customer-ddb-item.json").read_text(encoding="utf-8"))
    allocation_items = json.loads((package_dir / "allocation-ddb-items.json").read_text(encoding="utf-8"))
    if not isinstance(customer_item, dict):
        raise ValueError("customer-ddb-item.json must contain a JSON object")
    if not isinstance(allocation_items, list):
        raise ValueError("allocation-ddb-items.json must contain a JSON array")
    return customer_item, allocation_items


def apply_backend_payloads(
    *,
    region: str,
    customer_table: str,
    allocation_table: str,
    customer_item_plain: dict[str, Any],
    allocation_items_typed: list[dict[str, Any]],
) -> dict[str, Any]:
    customer_item_typed = serialize_plain_item(customer_item_plain)
    customer_key_names = table_key_names(region, customer_table)
    allocation_key_names = table_key_names(region, allocation_table)

    customer_key = extract_key(customer_item_typed, customer_key_names)
    customer_existing = get_typed_item(region, customer_table, customer_key)
    customer_action = "created"
    if customer_existing is None:
        put_typed_item(region, customer_table, customer_item_typed)
    elif customer_existing == customer_item_typed:
        customer_action = "already_present"
    else:
        raise RuntimeError(
            f"customer table already contains conflicting item for key {sorted(customer_key)}"
        )

    allocation_results: list[dict[str, Any]] = []
    for item in allocation_items_typed:
        allocation_key = extract_key(item, allocation_key_names)
        existing = get_typed_item(region, allocation_table, allocation_key)
        action = "created"
        if existing is None:
            put_typed_item(region, allocation_table, item)
        elif existing == item:
            action = "already_present"
        else:
            raise RuntimeError(
                f"allocation table already contains conflicting item for key {sorted(allocation_key)}"
            )
        allocation_results.append(
            {
                "action": action,
                "key": allocation_key,
                "resource_key": (allocation_key.get("resource_key") or {}).get("S"),
            }
        )

    return {
        "customer_item_typed": customer_item_typed,
        "customer_key": customer_key,
        "customer_action": customer_action,
        "allocation_results": allocation_results,
        "allocation_key_names": allocation_key_names,
    }


def validate_backend_payloads(
    *,
    region: str,
    customer_table: str,
    allocation_table: str,
    customer_item_plain: dict[str, Any],
    allocation_items_typed: list[dict[str, Any]],
) -> dict[str, Any]:
    customer_item_typed = serialize_plain_item(customer_item_plain)
    customer_key = extract_key(customer_item_typed, table_key_names(region, customer_table))
    customer_actual = get_typed_item(region, customer_table, customer_key)

    errors: list[str] = []
    if customer_actual != customer_item_typed:
        errors.append("customer SoT item does not match expected package payload")

    allocation_key_names = table_key_names(region, allocation_table)
    allocation_checks: list[dict[str, Any]] = []
    for item in allocation_items_typed:
        key = extract_key(item, allocation_key_names)
        actual = get_typed_item(region, allocation_table, key)
        valid = actual == item
        if not valid:
            errors.append(f"allocation item missing or mismatched for key {key}")
        allocation_checks.append(
            {
                "key": key,
                "resource_key": (key.get("resource_key") or {}).get("S"),
                "valid": valid,
            }
        )

    return {
        "valid": not errors,
        "errors": errors,
        "customer_key": customer_key,
        "allocation_checks": allocation_checks,
    }


def rollback_backend_payloads(
    *,
    region: str,
    customer_table: str,
    allocation_table: str,
    customer_item_plain: dict[str, Any],
    allocation_items_typed: list[dict[str, Any]],
) -> dict[str, Any]:
    customer_item_typed = serialize_plain_item(customer_item_plain)
    customer_key = extract_key(customer_item_typed, table_key_names(region, customer_table))
    allocation_key_names = table_key_names(region, allocation_table)

    deleted_allocations: list[dict[str, Any]] = []
    allocation_errors: list[str] = []
    for item in reversed(allocation_items_typed):
        key = extract_key(item, allocation_key_names)
        try:
            if get_typed_item(region, allocation_table, key) is not None:
                delete_typed_item(region, allocation_table, key)
                deleted_allocations.append(
                    {
                        "key": key,
                        "resource_key": (key.get("resource_key") or {}).get("S"),
                    }
                )
        except Exception as exc:  # pragma: no cover - rollback best effort
            allocation_errors.append(str(exc))

    customer_deleted = False
    customer_error = ""
    try:
        if get_typed_item(region, customer_table, customer_key) is not None:
            delete_typed_item(region, customer_table, customer_key)
            customer_deleted = True
    except Exception as exc:  # pragma: no cover - rollback best effort
        customer_error = str(exc)

    errors = allocation_errors + ([customer_error] if customer_error else [])
    return {
        "status": "rolled_back" if not errors else "rollback_failed",
        "errors": errors,
        "customer_deleted": customer_deleted,
        "customer_key": customer_key,
        "deleted_allocations": deleted_allocations,
    }
