#!/usr/bin/env python
"""Validate an RPDB deployment environment contract without touching live systems."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
MUXER_SRC = REPO_ROOT / "muxer" / "src"
if str(MUXER_SRC) not in sys.path:
    sys.path.insert(0, str(MUXER_SRC))

from muxerlib.customer_merge import load_yaml_file


ENVIRONMENT_ROOT = REPO_ROOT / "muxer" / "config" / "deployment-environments"
DEFAULT_SCHEMA = REPO_ROOT / "muxer" / "config" / "schema" / "deployment-environment.schema.json"
REQUIRED_BLOCKED_CUSTOMERS = {
    "vpn-customer-stage1-15-cust-0003",
}
FORBIDDEN_TARGET_MARKERS = (
    "muxer3",
    "e:\\code1\\muxer3",
    "/muxer3",
    "\\muxer3",
    "legacy",
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_environment_path(raw: str) -> Path:
    supplied = Path(raw)
    if supplied.exists():
        return supplied.resolve()

    candidates = []
    if supplied.suffix:
        candidates.append(ENVIRONMENT_ROOT / supplied.name)
    else:
        candidates.append(ENVIRONMENT_ROOT / f"{raw}.yaml")
        candidates.append(ENVIRONMENT_ROOT / f"{raw}.yml")
        candidates.append(ENVIRONMENT_ROOT / raw)

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return supplied.resolve()


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _walk_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_strings(nested)


def _target_docs(document: dict[str, Any]) -> list[dict[str, Any]]:
    targets = document.get("targets") or {}
    headends = targets.get("headends") or {}
    docs = []
    muxer = targets.get("muxer")
    if isinstance(muxer, dict):
        docs.append(muxer)
    for pair_name in ("nat", "non_nat"):
        pair = headends.get(pair_name) or {}
        for node_name in ("active", "standby"):
            node = pair.get(node_name)
            if isinstance(node, dict):
                docs.append(node)
    return docs


def _uses_staged_access(document: dict[str, Any]) -> bool:
    environment_access = ((document.get("environment") or {}).get("access") or {}).get("method")
    if environment_access == "staged":
        return True
    for target in _target_docs(document):
        if ((target.get("access") or {}).get("method")) == "staged":
            return True
        if ((target.get("selector") or {}).get("type")) == "staged":
            return True
    return False


def _validate_schema(report: dict[str, Any], document: dict[str, Any], schema_path: Path) -> None:
    if not schema_path.exists():
        report["errors"].append(f"schema file not found: {schema_path}")
        return

    schema = _load_json(schema_path)
    try:
        import jsonschema

        jsonschema.validate(instance=document, schema=schema)
        report["validator"] = "jsonschema"
    except ImportError:
        report["warnings"].append("jsonschema not installed; schema validation skipped")
    except Exception as exc:
        report["errors"].append(str(exc))


def _validate_guardrails(report: dict[str, Any], document: dict[str, Any], *, allow_live_apply: bool) -> None:
    environment = document.get("environment") or {}
    customer_requests = document.get("customer_requests") or {}
    owners = document.get("owners") or {}
    datastores = document.get("datastores") or {}
    artifacts = document.get("artifacts") or {}

    live_apply = environment.get("live_apply") or {}
    if bool(live_apply.get("enabled")) and not allow_live_apply:
        report["errors"].append(
            "live_apply.enabled is true; pass --allow-live-apply only after the live gate exists"
        )

    blocked_customers = {
        str(customer).strip()
        for customer in customer_requests.get("blocked_customers") or []
        if str(customer).strip()
    }
    missing_blocked = sorted(REQUIRED_BLOCKED_CUSTOMERS - blocked_customers)
    if missing_blocked:
        report["errors"].append(
            "blocked_customers missing required blocked customer(s): "
            + ", ".join(missing_blocked)
        )

    for idx, root in enumerate(customer_requests.get("allowed_roots") or []):
        normalized_root = str(root).strip().lower()
        if "muxer3" in normalized_root:
            report["errors"].append(
                f"customer_requests.allowed_roots[{idx}] points at a MUXER3 path"
            )

    for target in _target_docs(document):
        target_name = str(target.get("name") or "<unnamed-target>")
        if target.get("rpdb_managed") is not True:
            report["errors"].append(f"target {target_name} is not marked rpdb_managed=true")
        for value in _walk_strings(target):
            lowered = value.lower()
            if any(marker in lowered for marker in FORBIDDEN_TARGET_MARKERS):
                report["errors"].append(
                    f"target {target_name} contains forbidden legacy/MUXER3 marker: {value}"
                )

    if not str(owners.get("validation") or "").strip():
        report["errors"].append("owners.validation is required")
    if not str(owners.get("rollback") or "").strip():
        report["errors"].append("owners.rollback is required")

    if _uses_staged_access(document):
        if str(datastores.get("mode") or "").strip() != "staged":
            report["errors"].append("datastores.mode must be staged when staged access is used")
        if not str(datastores.get("staged_root") or "").strip():
            report["errors"].append("datastores.staged_root is required when staged access is used")
        if str(artifacts.get("mode") or "").strip() != "staged":
            report["errors"].append("artifacts.mode must be staged when staged access is used")
        if not str(artifacts.get("staged_root") or "").strip():
            report["errors"].append("artifacts.staged_root is required when staged access is used")


def _target_summary(document: dict[str, Any]) -> dict[str, Any]:
    targets = document.get("targets") or {}
    headends = targets.get("headends") or {}
    return {
        "muxer": (targets.get("muxer") or {}).get("name"),
        "nat_active": (((headends.get("nat") or {}).get("active") or {}).get("name")),
        "nat_standby": (((headends.get("nat") or {}).get("standby") or {}).get("name")),
        "non_nat_active": (((headends.get("non_nat") or {}).get("active") or {}).get("name")),
        "non_nat_standby": (((headends.get("non_nat") or {}).get("standby") or {}).get("name")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an RPDB deployment environment contract.")
    parser.add_argument(
        "environment",
        help="Environment file path or name under muxer/config/deployment-environments",
    )
    parser.add_argument(
        "--schema",
        default=str(DEFAULT_SCHEMA),
        help="Path to the deployment environment JSON schema",
    )
    parser.add_argument(
        "--allow-live-apply",
        action="store_true",
        help="Allow live_apply.enabled=true. Do not use before the live gate is implemented.",
    )
    parser.add_argument("--json", action="store_true", help="Print the validation report as JSON")
    args = parser.parse_args()

    environment_path = _resolve_environment_path(args.environment)
    schema_path = Path(args.schema).resolve()
    report: dict[str, Any] = {
        "environment_file": str(environment_path),
        "schema_file": str(schema_path),
        "errors": [],
        "warnings": [],
        "aws_calls": False,
        "live_node_access": False,
    }

    if not environment_path.exists():
        report["errors"].append(f"environment file not found: {environment_path}")
    else:
        document = load_yaml_file(environment_path)
        report["environment_name"] = ((document.get("environment") or {}).get("name"))
        report["targets"] = _target_summary(document)
        _validate_schema(report, document, schema_path)
        _validate_guardrails(report, document, allow_live_apply=args.allow_live_apply)

    report["valid"] = not report["errors"]

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Deployment environment: {'VALID' if report['valid'] else 'INVALID'}")
        print(f"- file: {environment_path}")
        if report.get("environment_name"):
            print(f"- environment: {report['environment_name']}")
        if report.get("validator"):
            print(f"- validator: {report['validator']}")
        print("- aws_calls: false")
        print("- live_node_access: false")
        for error in report["errors"]:
            print(f"  error: {error}")
        for warning in report["warnings"]:
            print(f"  warning: {warning}")

    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
