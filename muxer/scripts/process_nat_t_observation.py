#!/usr/bin/env python
"""Process a repo-only dynamic NAT-T observation into staged artifacts."""

from __future__ import annotations

import argparse
import copy
import json
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
from muxerlib.dynamic_provisioning import (
    build_nat_t_observation_idempotency_key,
    build_nat_t_promotion_request,
    customer_name_from_doc,
    normalize_nat_t_observation_event,
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_event(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
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


def main() -> int:
    muxer_dir = Path(__file__).resolve().parents[1]
    repo_root = muxer_dir.parent

    parser = argparse.ArgumentParser(
        description=(
            "Consume one muxer-observed UDP/4500 event and stage a repo-only "
            "NAT-T promotion package with idempotent audit."
        )
    )
    parser.add_argument("customer_input", help="Current dynamic customer request or source YAML")
    parser.add_argument("--observation", required=True, help="Observed NAT-T event JSON or YAML")
    parser.add_argument(
        "--observation-schema",
        default=str(muxer_dir / "config" / "schema" / "dynamic-nat-t-observation.schema.json"),
        help="Path to the dynamic NAT-T observation JSON schema",
    )
    parser.add_argument(
        "--out-dir",
        default=str(repo_root / "build" / "dynamic-provisioning"),
        help="Directory for staged observation, promotion, allocation, and audit artifacts",
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
    event_doc = _load_event(observation_path)
    _maybe_validate_with_jsonschema(event_doc, _load_json(Path(args.observation_schema).resolve()))
    observation = normalize_nat_t_observation_event(
        event_doc,
        default_customer_name=customer_name,
    )
    if observation["customer_name"] != customer_name:
        raise ValueError(
            f"observation customer {observation['customer_name']} does not match input customer {customer_name}"
        )

    idempotency_key = build_nat_t_observation_idempotency_key(observation)
    short_key = idempotency_key[:12]
    artifact_dir = out_dir / customer_name / short_key
    audit_path = artifact_dir / "audit.json"

    if audit_path.exists():
        result = _existing_audit_result(audit_path)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"NAT-T observation already planned: {audit_path}")
        return 0

    if artifact_dir.exists() and any(artifact_dir.iterdir()):
        raise SystemExit(f"artifact directory exists without audit record: {artifact_dir}")

    artifact_dir.mkdir(parents=True, exist_ok=True)
    promoted_request_path = artifact_dir / "promoted-nat-request.yaml"
    promoted_source_path = artifact_dir / "promoted-customer-source.yaml"
    promoted_module_path = artifact_dir / "promoted-customer-module.json"
    promoted_item_path = artifact_dir / "promoted-customer-ddb-item.json"
    promoted_allocation_summary_path = artifact_dir / "promoted-allocation-summary.json"
    promoted_allocation_ddb_items_path = artifact_dir / "promoted-allocation-ddb-items.json"
    observation_out_path = artifact_dir / "observation.json"
    promotion_summary_path = artifact_dir / "promotion-summary.json"

    promoted_request, promotion_summary = build_nat_t_promotion_request(
        customer_doc,
        observed_peer=observation["observed_peer"],
        observed_protocol=observation["observed_protocol"],
        observed_dport=observation["observed_dport"],
        initial_udp500_observed=observation["initial_udp500_observed"],
        observed_at=observation["observed_at"] or None,
    )
    promotion_summary["source_ref"] = customer_input_path.as_posix()
    promotion_summary["observation_ref"] = observation_path.as_posix()
    promotion_summary["observation_idempotency_key"] = idempotency_key
    promotion_summary["promoted_request"] = promoted_request_path.as_posix()

    _write_json(observation_out_path, observation)
    _write_yaml(promoted_request_path, promoted_request)
    _write_json(promotion_summary_path, promotion_summary)

    existing_roots = args.existing_source_root or [str(muxer_dir / "config" / "customer-sources")]
    provisioning_result = _build_provisioning_result(
        promoted_request,
        request_path=promoted_request_path,
        muxer_dir=muxer_dir,
        schema_path=Path(args.schema).resolve(),
        allocation_pools_path=Path(args.allocation_pools).resolve(),
        defaults_path=Path(args.defaults).resolve(),
        existing_source_roots=existing_roots,
        customer_name=customer_name,
    )
    _write_yaml(promoted_source_path, provisioning_result["customer_source"])
    _write_json(promoted_module_path, provisioning_result["customer_module"])
    _write_json(promoted_item_path, provisioning_result["dynamodb_item"])
    _write_json(promoted_allocation_summary_path, provisioning_result["allocation_summary"])
    _write_json(promoted_allocation_ddb_items_path, provisioning_result["allocation_ddb_items"])

    result = {
        "schema_version": 1,
        "action": "process_nat_t_observation",
        "status": "planned",
        "live_apply": False,
        "new_allocation_created": True,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "customer_name": customer_name,
        "idempotency_key": idempotency_key,
        "artifact_dir": artifact_dir.as_posix(),
        "observation": observation,
        "promotion_summary": promotion_summary,
        "allocation_plan": provisioning_result["allocation_plan"],
        "artifacts": {
            "observation": observation_out_path.as_posix(),
            "promoted_request": promoted_request_path.as_posix(),
            "promoted_source": promoted_source_path.as_posix(),
            "promoted_module": promoted_module_path.as_posix(),
            "promoted_item": promoted_item_path.as_posix(),
            "promoted_allocation_summary": promoted_allocation_summary_path.as_posix(),
            "promoted_allocation_ddb_items": promoted_allocation_ddb_items_path.as_posix(),
            "promotion_summary": promotion_summary_path.as_posix(),
            "audit": audit_path.as_posix(),
        },
        "guardrails": [
            "repo_only_no_live_apply",
            "peer_ip_matched",
            "udp4500_trigger_matched",
            "same_customer_replacement_only",
            "duplicate_observations_return_existing_artifacts",
        ],
    }
    _write_json(audit_path, result)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"NAT-T observation planned: {artifact_dir}")
        print(f"Audit: {audit_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
