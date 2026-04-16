#!/usr/bin/env python3
"""DynamoDB-backed customer source-of-truth helpers."""

from __future__ import annotations

import copy
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .customers import customer_protocol_flags


def normalize_customer_sot_backend(value: str | None, *, default: str = "customer_modules") -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return default
    aliases = {
        "ddb": "dynamodb",
        "modules": "customer_modules",
        "module_dir": "customer_modules",
        "local": "customer_modules",
        "local_modules": "customer_modules",
        "variables": "legacy_variables",
        "variables_file": "legacy_variables",
        "legacy": "legacy_variables",
        "legacy_file": "legacy_variables",
        "tunnels": "legacy_tunnels",
        "tunnels_dir": "legacy_tunnels",
    }
    return aliases.get(raw, raw)


def _aws_base_cmd(region: str | None = None) -> List[str]:
    cmd = ["aws", "dynamodb"]
    if region:
        cmd.extend(["--region", region])
    return cmd


def _write_temp_json(payload: Dict[str, Any]) -> Path:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as tf:
        json.dump(payload, tf)
        return Path(tf.name)


def customer_sot_settings(global_cfg: Dict[str, Any]) -> Tuple[str, str, str]:
    sot = global_cfg.get("customer_sot", {}) or {}
    backend = normalize_customer_sot_backend(sot.get("backend"))
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
    original = module.get("_rpdb_original") or {}
    customer_doc = original.get("customer") if isinstance(original, dict) else {}
    explicit = str((customer_doc or {}).get("customer_class") or "").strip()
    if explicit:
        return explicit
    udp500, udp4500, esp50, _force = customer_protocol_flags(module)
    if udp500 and not udp4500 and esp50:
        return "strict_non_nat"
    if udp4500:
        return "nat_t"
    return "custom"


def _peer_cidr(value: str) -> str:
    raw = str(value).strip()
    if not raw:
        return ""
    if "/" not in raw:
        raw = f"{raw}/32"
    return raw


def _compat_module_from_rpdb(module: Dict[str, Any]) -> Dict[str, Any]:
    customer = module.get("customer") or {}
    peer = module.get("peer") or {}
    transport = module.get("transport") or {}
    backend = module.get("backend") or {}
    selectors = module.get("selectors") or {}

    compat: Dict[str, Any] = {
        "id": int(customer["id"]),
        "name": str(customer["name"]),
        "peer_ip": _peer_cidr(str(peer.get("public_ip") or "")),
        "protocols": copy.deepcopy(module.get("protocols") or {}),
        "natd_rewrite": copy.deepcopy(module.get("natd_rewrite") or {}),
        "post_ipsec_nat": copy.deepcopy(module.get("post_ipsec_nat") or {}),
        "customer_class": str(customer.get("customer_class") or ""),
    }

    ipsec_cfg = copy.deepcopy(module.get("ipsec") or {})
    if selectors.get("local_subnets") and not ipsec_cfg.get("local_subnets"):
        ipsec_cfg["local_subnets"] = copy.deepcopy(selectors.get("local_subnets") or [])
    if selectors.get("remote_subnets") and not ipsec_cfg.get("remote_subnets"):
        ipsec_cfg["remote_subnets"] = copy.deepcopy(selectors.get("remote_subnets") or [])
    if ipsec_cfg:
        compat["ipsec"] = ipsec_cfg

    backend_role = str(backend.get("role") or "").strip()
    if backend_role:
        compat["backend_role"] = backend_role

    backend_underlay_ip = str(backend.get("underlay_ip") or "").strip()
    if backend_underlay_ip:
        compat["backend_underlay_ip"] = backend_underlay_ip

    egress_source_ips = [
        str(source_ip).strip()
        for source_ip in (backend.get("egress_source_ips") or [])
        if str(source_ip).strip()
    ]
    if egress_source_ips:
        compat["headend_egress_sources"] = egress_source_ips

    interface = str(transport.get("interface") or "").strip()
    if interface:
        compat["ipip_ifname"] = interface

    tunnel_type = str(transport.get("tunnel_type") or "").strip()
    if tunnel_type:
        compat["tunnel_type"] = tunnel_type

    if transport.get("tunnel_ttl") is not None:
        compat["tunnel_ttl"] = int(transport["tunnel_ttl"])

    if transport.get("tunnel_key") is not None:
        compat["tunnel_key"] = int(transport["tunnel_key"])

    mark = str(transport.get("mark") or "").strip()
    if mark:
        compat["mark"] = mark

    if transport.get("table") is not None:
        compat["table"] = int(transport["table"])

    if transport.get("rpdb_priority") is not None:
        compat["rpdb_priority"] = int(transport["rpdb_priority"])

    overlay = copy.deepcopy(transport.get("overlay") or {})
    if overlay:
        compat["overlay"] = overlay

    compat["_rpdb_original"] = copy.deepcopy(module)
    return compat


def normalize_customer_module(module: Dict[str, Any]) -> Dict[str, Any]:
    if "customer" in module and "peer" in module and "transport" in module:
        return _compat_module_from_rpdb(module)
    return module


def _runtime_local_subnets(module: Dict[str, Any]) -> List[str]:
    ipsec_cfg = module.get("ipsec") or {}
    return list(ipsec_cfg.get("local_subnets") or [])


def _runtime_remote_subnets(module: Dict[str, Any]) -> List[str]:
    ipsec_cfg = module.get("ipsec") or {}
    return list(ipsec_cfg.get("remote_subnets") or [])


def _build_rpdb_customer_json(module: Dict[str, Any], source_ref: str, updated_at: str) -> Dict[str, Any]:
    original = copy.deepcopy(module.get("_rpdb_original") or {})
    if not original:
        raise ValueError("RPDB reconstruction requires _rpdb_original")

    customer_doc = original.setdefault("customer", {})
    customer_doc["id"] = int(module["id"])
    customer_doc["name"] = str(module["name"])
    if module.get("customer_class"):
        customer_doc["customer_class"] = str(module["customer_class"])

    peer_doc = original.setdefault("peer", {})
    peer_doc["public_ip"] = str(module["peer_ip"]).split("/")[0]
    if not str(peer_doc.get("remote_id") or "").strip():
        peer_doc["remote_id"] = peer_doc["public_ip"]

    backend_doc = original.setdefault("backend", {})
    if module.get("backend_role"):
        backend_doc["role"] = str(module["backend_role"])
    if module.get("backend_underlay_ip"):
        backend_doc["underlay_ip"] = str(module["backend_underlay_ip"])
    if module.get("headend_egress_sources"):
        backend_doc["egress_source_ips"] = list(module["headend_egress_sources"])

    transport_doc = original.setdefault("transport", {})
    if module.get("ipip_ifname"):
        transport_doc["interface"] = str(module["ipip_ifname"])
    if module.get("mark"):
        transport_doc["mark"] = str(module["mark"])
    if module.get("table") is not None:
        transport_doc["table"] = int(module["table"])
    if module.get("tunnel_key") is not None:
        transport_doc["tunnel_key"] = int(module["tunnel_key"])
    if module.get("tunnel_ttl") is not None:
        transport_doc["tunnel_ttl"] = int(module["tunnel_ttl"])
    if module.get("tunnel_type"):
        transport_doc["tunnel_type"] = str(module["tunnel_type"])
    if module.get("rpdb_priority") is not None:
        transport_doc["rpdb_priority"] = int(module["rpdb_priority"])
    if module.get("overlay"):
        transport_doc["overlay"] = copy.deepcopy(module["overlay"])

    if module.get("protocols"):
        original["protocols"] = copy.deepcopy(module["protocols"])
    if module.get("natd_rewrite"):
        original["natd_rewrite"] = copy.deepcopy(module["natd_rewrite"])
    if module.get("post_ipsec_nat"):
        original["post_ipsec_nat"] = copy.deepcopy(module["post_ipsec_nat"])

    ipsec_cfg = copy.deepcopy(module.get("ipsec") or {})
    if ipsec_cfg:
        original["ipsec"] = ipsec_cfg

    selectors_doc = original.setdefault("selectors", {})
    local_subnets = _runtime_local_subnets(module)
    remote_subnets = _runtime_remote_subnets(module)
    if local_subnets:
        selectors_doc["local_subnets"] = copy.deepcopy(local_subnets)
    if remote_subnets:
        selectors_doc["remote_subnets"] = copy.deepcopy(remote_subnets)

    metadata = original.setdefault("metadata", {})
    metadata["source_ref"] = source_ref
    metadata["resolved_at"] = updated_at

    return original


def build_ddb_item(module: Dict[str, Any], source_ref: str) -> Dict[str, Any]:
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if module.get("_rpdb_original"):
        customer_json_doc = _build_rpdb_customer_json(module, source_ref, updated_at)
        payload = json.dumps(customer_json_doc, sort_keys=True, separators=(",", ":"))
        customer_id = int((customer_json_doc.get("customer") or {}).get("id"))
        customer_name = str((customer_json_doc.get("customer") or {}).get("name"))
        transport_doc = customer_json_doc.get("transport") or {}
        backend_doc = customer_json_doc.get("backend") or {}
        peer_doc = customer_json_doc.get("peer") or {}
        schema_version = customer_json_doc.get("schema_version")
    else:
        customer_json_doc = module
        payload = json.dumps(module, sort_keys=True, separators=(",", ":"))
        customer_id = int(module["id"])
        customer_name = str(module["name"])
        transport_doc = {}
        backend_doc = {}
        peer_doc = {}
        schema_version = None

    item = {
        "customer_name": {"S": customer_name},
        "customer_id": {"N": str(customer_id)},
        "customer_class": {"S": customer_class(module)},
        "peer_ip": {"S": str(peer_doc.get("public_ip") or module["peer_ip"]).split("/")[0]},
        "fwmark": {"S": str(transport_doc.get("mark") or module.get("mark", ""))},
        "route_table": {"N": str(int(transport_doc.get("table") or module.get("table", 0)))},
        "backend_underlay_ip": {"S": str(backend_doc.get("underlay_ip") or module.get("backend_underlay_ip", ""))},
        "source_ref": {"S": source_ref},
        "updated_at": {"S": updated_at},
        "customer_json": {"S": payload},
    }
    backend_role = str(backend_doc.get("role") or module.get("backend_role", "")).strip()
    backend_role_az = str(module.get("backend_role_az", "")).strip()
    rpdb_priority = transport_doc.get("rpdb_priority") or module.get("rpdb_priority")
    if backend_role:
        item["backend_role"] = {"S": backend_role}
    if backend_role_az:
        item["backend_role_az"] = {"S": backend_role_az}
    if rpdb_priority is not None:
        item["rpdb_priority"] = {"N": str(int(rpdb_priority))}
    if schema_version is not None:
        item["schema_version"] = {"N": str(int(schema_version))}
    return item


def put_customer_modules(
    modules: List[Dict[str, Any]],
    table_name: str,
    region: str | None = None,
    source_ref: str = "muxer/runtime-package/runtime-update",
) -> int:
    written = 0
    for module in modules:
        written += put_customer_module(
            module,
            table_name=table_name,
            region=region,
            source_ref=source_ref,
        )
    return written


def put_customer_module(
    module: Dict[str, Any],
    table_name: str,
    region: str | None = None,
    source_ref: str = "muxer/runtime-package/runtime-update",
) -> int:
    item = build_ddb_item(module, source_ref)
    temp_path = _write_temp_json(item)
    try:
        subprocess.run(
            _aws_base_cmd(region)
            + ["put-item", "--table-name", table_name, "--item", f"file://{temp_path}"],
            text=True,
            capture_output=True,
            check=True,
        )
        return 1
    finally:
        temp_path.unlink(missing_ok=True)


def get_customer_item(table_name: str, customer_name: str, region: str | None = None) -> Dict[str, Any] | None:
    if not table_name:
        raise SystemExit("customer_sot.dynamodb.table_name is required for DynamoDB-backed customer loading")
    if not str(customer_name or "").strip():
        raise SystemExit("customer_name is required for DynamoDB-backed customer lookup")

    key_doc = {"customer_name": {"S": str(customer_name).strip()}}
    temp_path = _write_temp_json(key_doc)
    try:
        raw = subprocess.check_output(
            _aws_base_cmd(region)
            + ["get-item", "--table-name", table_name, "--key", f"file://{temp_path}"],
            text=True,
        )
    finally:
        temp_path.unlink(missing_ok=True)

    item = json.loads(raw).get("Item")
    if not isinstance(item, dict):
        return None
    return item


def delete_customer_module_from_dynamodb(table_name: str, customer_name: str, region: str | None = None) -> bool:
    existing = get_customer_item(table_name, customer_name, region)
    if not existing:
        return False

    key_doc = {"customer_name": {"S": str(customer_name).strip()}}
    temp_path = _write_temp_json(key_doc)
    try:
        subprocess.run(
            _aws_base_cmd(region)
            + ["delete-item", "--table-name", table_name, "--key", f"file://{temp_path}"],
            text=True,
            capture_output=True,
            check=True,
        )
        return True
    finally:
        temp_path.unlink(missing_ok=True)


def scan_customer_items(table_name: str, region: str | None = None) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    last_key: Dict[str, Any] | None = None
    while True:
        cmd = _aws_base_cmd(region) + ["scan", "--table-name", table_name]
        if last_key:
            temp_path = _write_temp_json(last_key)
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


def _item_to_customer_module(item: Dict[str, Any]) -> Dict[str, Any] | None:
    payload = ((item.get("customer_json") or {}).get("S") or "").strip()
    if not payload:
        return None
    return normalize_customer_module(json.loads(payload))


def load_customer_module_from_dynamodb(
    table_name: str,
    customer_name: str,
    region: str | None = None,
) -> Dict[str, Any] | None:
    item = get_customer_item(table_name, customer_name, region)
    if not item:
        return None
    return _item_to_customer_module(item)


def load_customer_modules_from_dynamodb(table_name: str, region: str | None = None) -> List[Dict[str, Any]]:
    if not table_name:
        raise SystemExit("customer_sot.dynamodb.table_name is required for DynamoDB-backed customer loading")

    modules: List[Dict[str, Any]] = []
    for item in scan_customer_items(table_name, region):
        module = _item_to_customer_module(item)
        if module is None:
            continue
        modules.append(module)
    modules.sort(key=lambda item: int(item["id"]))
    return modules
