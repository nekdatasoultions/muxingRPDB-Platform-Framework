#!/usr/bin/env python
"""Process one device-registry peer IP change into staged reapply artifacts."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muxerlib.allocation import (
    build_allocation_inventory,
    build_allocation_records,
    build_allocation_summary,
    load_allocation_pools,
    load_customer_source_docs,
    plan_customer_allocations,
    render_allocated_customer_source,
)
from muxerlib.allocation_sot import build_exclusive_allocation_ddb_items
from muxerlib.customer_merge import build_customer_item, build_customer_module, load_yaml_file
from muxerlib.dynamic_peer_ip import (
    build_dynamic_peer_ip_change_idempotency_key,
    build_dynamic_peer_ip_reapply_request,
    customer_name_from_doc,
    normalize_dynamic_peer_ip_event,
    validate_dynamic_peer_ip_request,
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_event(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    return yaml.safe_load(text) or {}


def _maybe_validate_with_jsonschema(payload: dict[str, Any], schema: dict[str, Any]) -> bool:
    try:
        import jsonschema
    except ImportError:
        return False
    jsonschema.validate(instance=payload, schema=schema)
    return True


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _resolve_environment_path(repo_root: Path, environment: str | None) -> Path | None:
    value = str(environment or "").strip()
    if not value:
        return None
    raw = Path(value)
    candidates = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append((repo_root / raw).resolve())
        if raw.suffix.lower() not in {".yaml", ".yml"}:
            candidates.append(
                (repo_root / "muxer" / "config" / "deployment-environments" / f"{value}.yaml").resolve()
            )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _run_aws_json(repo_root: Path, command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        ["aws", *command],
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip() or "AWS CLI command failed")
    return json.loads(completed.stdout or "{}")


def _typed_value(attribute: Any) -> Any:
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
        return [_typed_value(item) for item in attribute["L"]]
    if "M" in attribute:
        return {str(key): _typed_value(value) for key, value in attribute["M"].items()}
    return attribute


def _plain_item(typed_item: dict[str, Any] | None) -> dict[str, Any]:
    if not typed_item:
        return {}
    return {str(key): _typed_value(value) for key, value in typed_item.items()}


def _prune_empty_values(value: Any) -> Any:
    if isinstance(value, dict):
        pruned: dict[str, Any] = {}
        for key, nested in value.items():
            cleaned = _prune_empty_values(nested)
            if cleaned in (None, "", [], {}):
                continue
            pruned[str(key)] = cleaned
        return pruned
    if isinstance(value, list):
        items = [_prune_empty_values(item) for item in value]
        return [item for item in items if item not in (None, "", [], {})]
    return value


def _request_peer_from_module(
    module_peer: dict[str, Any],
    *,
    fallback_peer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    peer = copy.deepcopy(module_peer or {})
    fallback = copy.deepcopy(fallback_peer or {})
    local_psk_redacted = bool(peer.pop("psk_redacted", False)) or str(peer.get("psk") or "") == "<redacted-local-psk>"

    if local_psk_redacted:
        for key in ("psk_source", "psk_secret_ref", "psk"):
            peer.pop(key, None)
        for key in ("psk_source", "psk_secret_ref", "psk"):
            value = fallback.get(key)
            if value not in (None, ""):
                peer[key] = value

    return _prune_empty_values(peer)


def _module_to_request(
    module: dict[str, Any],
    *,
    fallback_peer: dict[str, Any] | None = None,
    fallback_dynamic_provisioning: dict[str, Any] | None = None,
    fallback_dynamic_peer_ip: dict[str, Any] | None = None,
) -> dict[str, Any]:
    customer = dict(module.get("customer") or {})
    request_customer: dict[str, Any] = {
        "name": customer.get("name"),
        "peer": _request_peer_from_module(
            module.get("peer") or {},
            fallback_peer=fallback_peer,
        ),
        "selectors": copy.deepcopy(module.get("selectors") or {}),
    }

    if customer.get("customer_class") not in (None, ""):
        request_customer["customer_class"] = customer.get("customer_class")

    transport = dict(module.get("transport") or {})
    request_transport: dict[str, Any] = {}
    if transport.get("mode") not in (None, ""):
        request_transport["mode"] = transport.get("mode")
    if transport.get("tunnel_mtu") is not None:
        request_transport["tunnel_mtu"] = transport.get("tunnel_mtu")
    cgnat = transport.get("cgnat")
    if isinstance(cgnat, dict) and cgnat:
        request_transport["cgnat"] = copy.deepcopy(cgnat)
    if request_transport:
        request_customer["transport"] = request_transport

    for key in (
        "backend",
        "protocols",
        "natd_rewrite",
        "ipsec",
        "post_ipsec_nat",
        "outside_nat",
    ):
        value = module.get(key)
        if isinstance(value, dict) and value:
            request_customer[key] = _prune_empty_values(copy.deepcopy(value))

    dynamic_provisioning = module.get("dynamic_provisioning")
    if isinstance(dynamic_provisioning, dict) and dynamic_provisioning:
        request_customer["dynamic_provisioning"] = _prune_empty_values(copy.deepcopy(dynamic_provisioning))
    elif isinstance(fallback_dynamic_provisioning, dict) and fallback_dynamic_provisioning:
        request_customer["dynamic_provisioning"] = _prune_empty_values(copy.deepcopy(fallback_dynamic_provisioning))

    dynamic_peer_ip = module.get("dynamic_peer_ip")
    if isinstance(dynamic_peer_ip, dict) and dynamic_peer_ip:
        request_customer["dynamic_peer_ip"] = _prune_empty_values(copy.deepcopy(dynamic_peer_ip))
    elif isinstance(fallback_dynamic_peer_ip, dict) and fallback_dynamic_peer_ip:
        request_customer["dynamic_peer_ip"] = _prune_empty_values(copy.deepcopy(fallback_dynamic_peer_ip))

    return {
        "schema_version": int(module.get("schema_version") or 1),
        "customer": request_customer,
    }


def _load_live_customer_module(
    *,
    repo_root: Path,
    environment: str | None,
    customer_name: str,
) -> dict[str, Any] | None:
    environment_path = _resolve_environment_path(repo_root, environment)
    if environment_path is None:
        return None
    environment_doc = load_yaml_file(environment_path)
    datastores = environment_doc.get("datastores") or {}
    if str(datastores.get("mode") or "").strip() != "dynamodb":
        return None
    environment_cfg = environment_doc.get("environment") or {}
    region = str((environment_cfg.get("aws") or {}).get("region") or "").strip()
    customer_table = str(datastores.get("customer_sot_table") or "").strip()
    if not region or not customer_table:
        return None
    payload = _run_aws_json(
        repo_root,
        [
            "dynamodb",
            "get-item",
            "--region",
            region,
            "--table-name",
            customer_table,
            "--key",
            json.dumps({"customer_name": {"S": customer_name}}),
            "--consistent-read",
            "--output",
            "json",
        ],
    )
    item = _plain_item(payload.get("Item"))
    raw_module = str(item.get("customer_json") or "").strip()
    if not raw_module:
        return None
    module = json.loads(raw_module)
    if not isinstance(module, dict):
        return None
    return module


def _filter_replaced_customer(
    docs: list[dict[str, Any]],
    *,
    customer_name: str,
) -> list[dict[str, Any]]:
    return [
        doc
        for doc in docs
        if str((doc.get("customer") or {}).get("name") or "").strip() != customer_name
    ]


def _build_provisioning_result(
    request_doc: dict[str, Any],
    *,
    request_path: Path,
    muxer_dir: Path,
    schema_path: Path,
    allocation_pools_path: Path,
    defaults_path: Path,
    existing_source_roots: list[str],
    customer_name: str,
) -> dict[str, Any]:
    request_schema = _load_json(schema_path)
    _maybe_validate_with_jsonschema(request_doc, request_schema)

    pools_doc = load_allocation_pools(allocation_pools_path)
    existing_source_docs = load_customer_source_docs(*existing_source_roots)
    existing_source_docs = _filter_replaced_customer(
        existing_source_docs,
        customer_name=customer_name,
    )
    inventory = build_allocation_inventory(existing_source_docs)
    allocation_plan = plan_customer_allocations(request_doc, pools_doc, inventory=inventory)
    customer_source = render_allocated_customer_source(request_doc, allocation_plan)

    customer_class = str((customer_source.get("customer") or {}).get("customer_class") or "")
    class_file = muxer_dir / "config" / "customer-defaults" / "classes" / f"{customer_class}.yaml"
    defaults_doc = load_yaml_file(defaults_path)
    class_doc = load_yaml_file(class_file)
    source_ref = request_path.as_posix()

    customer_module = build_customer_module(
        customer_source,
        defaults_doc,
        class_doc,
        source_ref=source_ref,
    )
    customer_item = build_customer_item(
        customer_source,
        defaults_doc,
        class_doc,
        source_ref=source_ref,
    )
    allocation_summary = build_allocation_summary(
        request_doc,
        allocation_plan,
        source_ref=source_ref,
    )
    allocation_records = build_allocation_records(
        request_doc,
        allocation_plan,
        source_ref=source_ref,
    )
    allocation_ddb_items = build_exclusive_allocation_ddb_items(allocation_records)

    return {
        "customer_source": customer_source,
        "allocation_plan": allocation_plan,
        "allocation_summary": allocation_summary,
        "allocation_records": allocation_records,
        "allocation_ddb_items": allocation_ddb_items,
        "customer_module": customer_module,
        "dynamodb_item": customer_item,
    }


def _existing_audit_result(audit_path: Path) -> dict[str, Any]:
    audit = _load_json(audit_path)
    result = copy.deepcopy(audit)
    result["status"] = "already_planned"
    result["new_allocation_created"] = False
    missing = [
        value
        for value in (audit.get("artifacts") or {}).values()
        if isinstance(value, str) and not Path(value).exists()
    ]
    result["missing_artifacts"] = missing
    if missing:
        result["status"] = "audit_exists_artifacts_missing"
    return result


def _quarantine_incomplete_artifact_dir(artifact_dir: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_candidate = artifact_dir.with_name(f"{artifact_dir.name}.incomplete-{timestamp}")
    candidate = base_candidate
    counter = 1
    while candidate.exists():
        candidate = artifact_dir.with_name(f"{base_candidate.name}-{counter}")
        counter += 1
    shutil.move(str(artifact_dir), str(candidate))
    return candidate


def main() -> int:
    muxer_dir = Path(__file__).resolve().parents[1]
    repo_root = muxer_dir.parent

    parser = argparse.ArgumentParser(
        description=(
            "Consume one device-registry peer IP change event and stage a repo-only "
            "reapply package with idempotent audit."
        )
    )
    parser.add_argument("customer_input", help="Current customer request or source YAML")
    parser.add_argument("--observation", required=True, help="Observed dynamic peer IP change JSON or YAML")
    parser.add_argument(
        "--observation-schema",
        default=str(muxer_dir / "config" / "schema" / "dynamic-peer-ip-change.schema.json"),
        help="Path to the dynamic peer IP change JSON schema",
    )
    parser.add_argument(
        "--out-dir",
        default=str(repo_root / "build" / "dynamic-peer-ip"),
        help="Directory for staged observation, updated request, allocation, and audit artifacts",
    )
    parser.add_argument(
        "--schema",
        default=str(muxer_dir / "config" / "schema" / "customer-request.schema.json"),
        help="Path to the customer request JSON schema",
    )
    parser.add_argument(
        "--allocation-pools",
        default=str(muxer_dir / "config" / "allocation-pools" / "defaults.yaml"),
        help="Path to the allocation pools YAML",
    )
    parser.add_argument(
        "--defaults",
        default=str(muxer_dir / "config" / "customer-defaults" / "defaults.yaml"),
        help="Path to the shared defaults YAML",
    )
    parser.add_argument(
        "--environment",
        help="Optional deployment environment name or file used to source the current live customer module",
    )
    parser.add_argument(
        "--existing-source-root",
        action="append",
        default=[],
        help="Existing customer source roots used for collision checks. Can be specified multiple times.",
    )
    parser.add_argument("--json", action="store_true", help="Print the workflow result as JSON")
    args = parser.parse_args()

    customer_input_path = Path(args.customer_input).resolve()
    observation_path = Path(args.observation).resolve()
    out_dir = Path(args.out_dir).resolve()

    customer_doc = load_yaml_file(customer_input_path)
    customer_name = customer_name_from_doc(customer_doc)
    live_module = _load_live_customer_module(
        repo_root=repo_root,
        environment=args.environment,
        customer_name=customer_name,
    )
    base_request_doc = (
        _module_to_request(
            live_module,
            fallback_peer=((customer_doc.get("customer") or {}).get("peer")),
            fallback_dynamic_provisioning=((customer_doc.get("customer") or {}).get("dynamic_provisioning")),
            fallback_dynamic_peer_ip=((customer_doc.get("customer") or {}).get("dynamic_peer_ip")),
        )
        if isinstance(live_module, dict)
        else customer_doc
    )
    validation = validate_dynamic_peer_ip_request(base_request_doc)
    event_doc = _load_event(observation_path)
    _maybe_validate_with_jsonschema(event_doc, _load_json(Path(args.observation_schema).resolve()))
    observation = normalize_dynamic_peer_ip_event(
        event_doc,
        default_customer_name=customer_name,
        default_serial_number=str(validation.get("serial_number") or ""),
    )
    if observation["customer_name"] != customer_name:
        raise ValueError(
            f"observation customer {observation['customer_name']} does not match input customer {customer_name}"
        )

    updated_request, change_summary = build_dynamic_peer_ip_reapply_request(
        base_request_doc,
        observed_peer=observation["observed_peer"],
        observed_at=observation["observed_at"] or None,
        registry_last_updated=observation["registry_last_updated"],
        registry_table=observation["registry_table"],
        source=observation["source"] or "dynamic-peer-ip-change",
    )
    change_summary["source_ref"] = customer_input_path.as_posix()
    change_summary["observation_ref"] = observation_path.as_posix()
    key_event = dict(observation)
    key_event["previous_peer"] = change_summary["previous_peer"]
    idempotency_key = build_dynamic_peer_ip_change_idempotency_key(key_event)
    short_key = idempotency_key[:12]
    artifact_dir = out_dir / customer_name / short_key
    audit_path = artifact_dir / "audit.json"
    recovered_artifact_dir = ""

    if audit_path.exists():
        result = _existing_audit_result(audit_path)
        if result["status"] != "audit_exists_artifacts_missing":
            if args.json:
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(f"Dynamic peer IP change already planned: {audit_path}")
            return 0
        recovered_artifact_dir = _quarantine_incomplete_artifact_dir(artifact_dir).as_posix()

    if artifact_dir.exists() and any(artifact_dir.iterdir()):
        recovered_artifact_dir = _quarantine_incomplete_artifact_dir(artifact_dir).as_posix()

    artifact_dir.mkdir(parents=True, exist_ok=True)
    updated_request_path = artifact_dir / "updated-request.yaml"
    updated_source_path = artifact_dir / "updated-customer-source.yaml"
    updated_module_path = artifact_dir / "updated-customer-module.json"
    updated_item_path = artifact_dir / "updated-customer-ddb-item.json"
    updated_allocation_summary_path = artifact_dir / "updated-allocation-summary.json"
    updated_allocation_ddb_items_path = artifact_dir / "updated-allocation-ddb-items.json"
    observation_out_path = artifact_dir / "observation.json"
    change_summary_path = artifact_dir / "change-summary.json"

    change_summary["observation_idempotency_key"] = idempotency_key
    change_summary["updated_request"] = updated_request_path.as_posix()

    _write_json(observation_out_path, observation)
    _write_yaml(updated_request_path, updated_request)
    _write_json(change_summary_path, change_summary)

    existing_roots = args.existing_source_root or [str(muxer_dir / "config" / "customer-sources")]
    provisioning_result = _build_provisioning_result(
        updated_request,
        request_path=updated_request_path,
        muxer_dir=muxer_dir,
        schema_path=Path(args.schema).resolve(),
        allocation_pools_path=Path(args.allocation_pools).resolve(),
        defaults_path=Path(args.defaults).resolve(),
        existing_source_roots=existing_roots,
        customer_name=customer_name,
    )
    _write_yaml(updated_source_path, provisioning_result["customer_source"])
    _write_json(updated_module_path, provisioning_result["customer_module"])
    _write_json(updated_item_path, provisioning_result["dynamodb_item"])
    _write_json(updated_allocation_summary_path, provisioning_result["allocation_summary"])
    _write_json(updated_allocation_ddb_items_path, provisioning_result["allocation_ddb_items"])

    result = {
        "schema_version": 1,
        "action": "process_dynamic_peer_ip_change",
        "status": "planned",
        "live_apply": False,
        "new_allocation_created": True,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "customer_name": customer_name,
        "idempotency_key": idempotency_key,
        "artifact_dir": artifact_dir.as_posix(),
        "recovered_incomplete_artifact_dir": recovered_artifact_dir,
        "live_customer_base_used": bool(live_module),
        "observation": observation,
        "change_summary": change_summary,
        "allocation_plan": provisioning_result["allocation_plan"],
        "artifacts": {
            "observation": observation_out_path.as_posix(),
            "updated_request": updated_request_path.as_posix(),
            "updated_source": updated_source_path.as_posix(),
            "updated_module": updated_module_path.as_posix(),
            "updated_item": updated_item_path.as_posix(),
            "updated_allocation_summary": updated_allocation_summary_path.as_posix(),
            "updated_allocation_ddb_items": updated_allocation_ddb_items_path.as_posix(),
            "change_summary": change_summary_path.as_posix(),
            "audit": audit_path.as_posix(),
        },
        "guardrails": [
            "repo_only_no_live_apply",
            "same_customer_reapply_only",
            "duplicate_peer_change_events_return_existing_artifacts",
            "incomplete_artifacts_are_quarantined_before_retry",
        ],
    }
    _write_json(audit_path, result)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Dynamic peer IP change planned: {artifact_dir}")
        print(f"Audit: {audit_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
