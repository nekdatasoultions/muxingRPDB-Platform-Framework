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


VOLATILE_TOP_LEVEL_ATTRIBUTES = {"allocated_at", "source_ref", "updated_at"}
VOLATILE_CUSTOMER_JSON_METADATA = {"resolved_at", "source_ref"}


def _normalize_customer_json_attribute(attribute: Any) -> Any:
    if not isinstance(attribute, dict):
        return attribute
    raw = attribute.get("S")
    if not isinstance(raw, str):
        return attribute
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return attribute
    if not isinstance(payload, dict):
        return attribute
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        for key in VOLATILE_CUSTOMER_JSON_METADATA:
            metadata.pop(key, None)
    return {"S": json.dumps(payload, sort_keys=True, separators=(",", ":"))}


def stable_typed_item(item: dict[str, Any]) -> dict[str, Any]:
    """Return the DynamoDB item fields that define customer/resource ownership.

    Live applies are intentionally re-runnable. Timestamps and repo-local source
    paths change each run, so they must not turn an otherwise identical customer
    into a false conflict.
    """
    stable: dict[str, Any] = {}
    for key, value in item.items():
        if key in VOLATILE_TOP_LEVEL_ATTRIBUTES:
            continue
        stable[key] = _normalize_customer_json_attribute(value) if key == "customer_json" else value
    return stable


def typed_items_stably_equal(left: dict[str, Any] | None, right: dict[str, Any]) -> bool:
    if left is None:
        return False
    return stable_typed_item(left) == stable_typed_item(right)


def _classify_existing_item(
    *,
    existing: dict[str, Any] | None,
    expected: dict[str, Any],
    table_label: str,
    key: dict[str, Any],
) -> str:
    if existing is None:
        return "created"
    if existing == expected:
        return "already_present"
    if typed_items_stably_equal(existing, expected):
        return "already_present_metadata_diff"
    raise RuntimeError(f"{table_label} table already contains conflicting item for key {sorted(key)}")


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
    customer_action = _classify_existing_item(
        existing=customer_existing,
        expected=customer_item_typed,
        table_label="customer",
        key=customer_key,
    )

    allocation_results: list[dict[str, Any]] = []
    for item in allocation_items_typed:
        allocation_key = extract_key(item, allocation_key_names)
        existing = get_typed_item(region, allocation_table, allocation_key)
        action = _classify_existing_item(
            existing=existing,
            expected=item,
            table_label="allocation",
            key=allocation_key,
        )
        allocation_results.append(
            {
                "action": action,
                "key": allocation_key,
                "resource_key": (allocation_key.get("resource_key") or {}).get("S"),
            }
        )

    if customer_action == "created":
        put_typed_item(region, customer_table, customer_item_typed)
    for item, result in zip(allocation_items_typed, allocation_results, strict=True):
        if result["action"] == "created":
            put_typed_item(region, allocation_table, item)

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
    customer_exact_match = customer_actual == customer_item_typed
    customer_stable_match = typed_items_stably_equal(customer_actual, customer_item_typed)
    if not customer_exact_match and not customer_stable_match:
        errors.append("customer SoT item does not match expected package payload")

    allocation_key_names = table_key_names(region, allocation_table)
    allocation_checks: list[dict[str, Any]] = []
    for item in allocation_items_typed:
        key = extract_key(item, allocation_key_names)
        actual = get_typed_item(region, allocation_table, key)
        exact_match = actual == item
        stable_match = typed_items_stably_equal(actual, item)
        valid = exact_match or stable_match
        if not valid:
            errors.append(f"allocation item missing or mismatched for key {key}")
        allocation_checks.append(
            {
                "key": key,
                "resource_key": (key.get("resource_key") or {}).get("S"),
                "exact_match": exact_match,
                "stable_match": stable_match,
                "valid": valid,
            }
        )

    return {
        "valid": not errors,
        "errors": errors,
        "customer_key": customer_key,
        "customer_exact_match": customer_exact_match,
        "customer_stable_match": customer_stable_match,
        "allocation_checks": allocation_checks,
    }


def rollback_backend_payloads(
    *,
    region: str,
    customer_table: str,
    allocation_table: str,
    customer_item_plain: dict[str, Any],
    allocation_items_typed: list[dict[str, Any]],
    customer_action: str = "created",
    allocation_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    customer_item_typed = serialize_plain_item(customer_item_plain)
    customer_key = extract_key(customer_item_typed, table_key_names(region, customer_table))
    allocation_key_names = table_key_names(region, allocation_table)
    created_allocation_keys: set[str] | None = None
    if allocation_results is not None:
        created_allocation_keys = {
            json.dumps(result.get("key") or {}, sort_keys=True)
            for result in allocation_results
            if result.get("action") == "created"
        }

    deleted_allocations: list[dict[str, Any]] = []
    allocation_errors: list[str] = []
    for item in reversed(allocation_items_typed):
        key = extract_key(item, allocation_key_names)
        if created_allocation_keys is not None and json.dumps(key, sort_keys=True) not in created_allocation_keys:
            continue
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
    if customer_action == "created":
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
