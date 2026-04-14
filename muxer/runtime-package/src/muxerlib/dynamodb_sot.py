#!/usr/bin/env python3
"""DynamoDB-backed customer source-of-truth helpers."""

from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .customers import customer_protocol_flags


def _aws_base_cmd(region: str | None = None) -> List[str]:
    cmd = ["aws", "dynamodb"]
    if region:
        cmd.extend(["--region", region])
    return cmd


def customer_sot_settings(global_cfg: Dict[str, Any]) -> Tuple[str, str, str]:
    sot = global_cfg.get("customer_sot", {}) or {}
    backend = str(sot.get("backend") or "variables_file").strip().lower()
    ddb = sot.get("dynamodb", {}) or {}
    table_name = str(ddb.get("table_name") or "").strip()
    region = str(ddb.get("region") or "").strip()
    return backend, table_name, region


def ensure_customer_sot_table(table_name: str, region: str | None = None) -> bool:
    describe = subprocess.run(
        _aws_base_cmd(region) + ["describe-table", "--table-name", table_name],
        text=True,
        capture_output=True,
        check=False,
    )
    if describe.returncode == 0:
        return False

    create = subprocess.run(
        _aws_base_cmd(region)
        + [
            "create-table",
            "--table-name",
            table_name,
            "--attribute-definitions",
            "AttributeName=customer_name,AttributeType=S",
            "--key-schema",
            "AttributeName=customer_name,KeyType=HASH",
            "--billing-mode",
            "PAY_PER_REQUEST",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if create.returncode != 0 and "ResourceInUseException" not in (create.stderr or ""):
        raise subprocess.CalledProcessError(create.returncode, create.args, output=create.stdout, stderr=create.stderr)
    subprocess.run(
        _aws_base_cmd(region) + ["wait", "table-exists", "--table-name", table_name],
        text=True,
        capture_output=True,
        check=True,
    )
    return True


def customer_class(module: Dict[str, Any]) -> str:
    udp500, udp4500, esp50, _force = customer_protocol_flags(module)
    if udp500 and not udp4500 and esp50:
        return "strict_non_nat"
    if udp4500:
        return "nat_t"
    return "custom"


def build_ddb_item(module: Dict[str, Any], source_ref: str) -> Dict[str, Any]:
    payload = json.dumps(module, sort_keys=True, separators=(",", ":"))
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    item = {
        "customer_name": {"S": str(module["name"])},
        "customer_id": {"N": str(int(module["id"]))},
        "customer_class": {"S": customer_class(module)},
        "peer_ip": {"S": str(module["peer_ip"]).split("/")[0]},
        "fwmark": {"S": str(module.get("mark", ""))},
        "route_table": {"N": str(int(module.get("table", 0)))},
        "backend_underlay_ip": {"S": str(module.get("backend_underlay_ip", ""))},
        "source_ref": {"S": source_ref},
        "updated_at": {"S": updated_at},
        "customer_json": {"S": payload},
    }
    backend_role = str(module.get("backend_role", "")).strip()
    backend_role_az = str(module.get("backend_role_az", "")).strip()
    if backend_role:
        item["backend_role"] = {"S": backend_role}
    if backend_role_az:
        item["backend_role_az"] = {"S": backend_role_az}
    return item


def put_customer_modules(
    modules: List[Dict[str, Any]],
    table_name: str,
    region: str | None = None,
    source_ref: str = "config/customers.variables.yaml",
) -> int:
    written = 0
    for module in modules:
        item = build_ddb_item(module, source_ref)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as tf:
            json.dump(item, tf)
            temp_path = Path(tf.name)
        try:
            subprocess.run(
                _aws_base_cmd(region)
                + ["put-item", "--table-name", table_name, "--item", f"file://{temp_path}"],
                text=True,
                capture_output=True,
                check=True,
            )
            written += 1
        finally:
            temp_path.unlink(missing_ok=True)
    return written


def _scan_items(table_name: str, region: str | None = None) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    last_key: Dict[str, Any] | None = None
    while True:
        cmd = _aws_base_cmd(region) + ["scan", "--table-name", table_name]
        if last_key:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as tf:
                json.dump(last_key, tf)
                temp_path = Path(tf.name)
            cmd.extend(["--exclusive-start-key", f"file://{temp_path}"])
        else:
            temp_path = None
        try:
            raw = subprocess.check_output(cmd, text=True)
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)
        data = json.loads(raw)
        items.extend(data.get("Items", []))
        last_key = data.get("LastEvaluatedKey")
        if not last_key:
            break
    return items


def load_customer_modules_from_dynamodb(table_name: str, region: str | None = None) -> List[Dict[str, Any]]:
    if not table_name:
        raise SystemExit("customer_sot.dynamodb.table_name is required for DynamoDB-backed customer loading")

    modules: List[Dict[str, Any]] = []
    for item in _scan_items(table_name, region):
        payload = ((item.get("customer_json") or {}).get("S") or "").strip()
        if not payload:
            continue
        modules.append(json.loads(payload))
    modules.sort(key=lambda item: int(item["id"]))
    return modules
