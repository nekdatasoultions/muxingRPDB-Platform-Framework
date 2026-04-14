#!/usr/bin/env python
"""Generate safe empty-platform parameter files from the current production shape."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGION = "us-east-1"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "build" / "empty-platform" / "current-prod-shape-rpdb-empty"
DEFAULT_MUXER_PARAMS = REPO_ROOT / "infra" / "cfn" / "parameters.single-muxer.us-east-1.json"
DEFAULT_NAT_PARAMS = REPO_ROOT / "infra" / "cfn" / "parameters.vpn-headend.nat.graviton-efs.us-east-1.json"
DEFAULT_NONNAT_PARAMS = REPO_ROOT / "infra" / "cfn" / "parameters.vpn-headend.non-nat.graviton-efs.us-east-1.json"


def _load_parameter_array(path: Path) -> List[Dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"expected CloudFormation parameter array in {path}")
    return payload


def _normalize_suffix(raw: str) -> str:
    value = raw.strip().lower().replace("_", "-")
    value = "-".join(part for part in value.split("-") if part)
    if not value:
        raise ValueError("suffix must not be empty")
    return value


def _suffix_name(base: str, suffix: str) -> str:
    if base.endswith(f"-{suffix}"):
        return base
    return f"{base}-{suffix}"


def _transform_muxer(params: List[Dict[str, str]], suffix: str) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    for item in params:
        updated = dict(item)
        key = updated.get("ParameterKey")
        if key == "ClusterName":
            updated["ParameterValue"] = _suffix_name(str(updated.get("ParameterValue") or ""), suffix)
        elif key == "CustomerSotTableName":
            updated["ParameterValue"] = _suffix_name(str(updated.get("ParameterValue") or ""), suffix)
        elif key == "EipAllocationId":
            updated["ParameterValue"] = ""
        elif key == "AllowEipReassociation":
            updated["ParameterValue"] = "false"
        result.append(updated)
    return result


def _transform_headend(params: List[Dict[str, str]], suffix: str) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    for item in params:
        updated = dict(item)
        key = updated.get("ParameterKey")
        if key == "ClusterName":
            updated["ParameterValue"] = _suffix_name(str(updated.get("ParameterValue") or ""), suffix)
        elif key == "EipAllocationId":
            updated["ParameterValue"] = ""
        result.append(updated)
    return result


def _parameter_map(payload: List[Dict[str, str]]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for item in payload:
        key = str(item.get("ParameterKey") or "").strip()
        if key:
            result[key] = str(item.get("ParameterValue") or "").strip()
    return result


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare safe empty-platform parameter files from the current production shape.")
    parser.add_argument("--muxer-params", default=str(DEFAULT_MUXER_PARAMS), help="Path to the source single-muxer parameter file")
    parser.add_argument("--nat-headend-params", default=str(DEFAULT_NAT_PARAMS), help="Path to the source NAT head-end parameter file")
    parser.add_argument(
        "--nonnat-headend-params",
        default=str(DEFAULT_NONNAT_PARAMS),
        help="Path to the source non-NAT head-end parameter file",
    )
    parser.add_argument("--region", default=DEFAULT_REGION, help="Region suffix to use in the generated stack names summary")
    parser.add_argument("--suffix", default="rpdb-empty", help="Suffix to append to cluster names and the customer SoT table")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory to write the prepared parameter files")
    args = parser.parse_args()

    suffix = _normalize_suffix(args.suffix)
    output_dir = Path(args.output_dir).resolve()

    muxer_source = Path(args.muxer_params).resolve()
    nat_source = Path(args.nat_headend_params).resolve()
    nonnat_source = Path(args.nonnat_headend_params).resolve()

    muxer_payload = _transform_muxer(_load_parameter_array(muxer_source), suffix)
    nat_payload = _transform_headend(_load_parameter_array(nat_source), suffix)
    nonnat_payload = _transform_headend(_load_parameter_array(nonnat_source), suffix)

    muxer_out = output_dir / muxer_source.name
    nat_out = output_dir / nat_source.name
    nonnat_out = output_dir / nonnat_source.name

    _write_json(muxer_out, muxer_payload)
    _write_json(nat_out, nat_payload)
    _write_json(nonnat_out, nonnat_payload)

    muxer_map = _parameter_map(muxer_payload)
    nat_map = _parameter_map(nat_payload)
    nonnat_map = _parameter_map(nonnat_payload)

    summary = {
        "region": args.region,
        "suffix": suffix,
        "generated_from": {
            "muxer": str(muxer_source),
            "nat_headend": str(nat_source),
            "nonnat_headend": str(nonnat_source),
        },
        "generated_files": {
            "muxer": str(muxer_out),
            "nat_headend": str(nat_out),
            "nonnat_headend": str(nonnat_out),
        },
        "result": {
            "muxer_cluster_name": muxer_map.get("ClusterName"),
            "muxer_stack_name": muxer_map.get("ClusterName"),
            "nat_cluster_name": nat_map.get("ClusterName"),
            "nat_stack_name": f"{nat_map.get('ClusterName', '')}-{args.region}",
            "nonnat_cluster_name": nonnat_map.get("ClusterName"),
            "nonnat_stack_name": f"{nonnat_map.get('ClusterName', '')}-{args.region}",
            "customer_sot_table": muxer_map.get("CustomerSotTableName"),
        },
        "safety_changes": {
            "muxer_eip_cleared": muxer_map.get("EipAllocationId", "") == "",
            "nat_headend_eip_cleared": nat_map.get("EipAllocationId", "") == "",
            "nonnat_headend_eip_cleared": nonnat_map.get("EipAllocationId", "") == "",
            "allow_eip_reassociation": muxer_map.get("AllowEipReassociation"),
        },
    }
    _write_json(output_dir / "preparation-summary.json", summary)

    readme = output_dir / "README.txt"
    readme.write_text(
        "\n".join(
            [
                "Prepared empty-platform parameter set",
                "",
                f"region: {args.region}",
                f"suffix: {suffix}",
                "",
                "Generated files:",
                f"- {muxer_out.name}",
                f"- {nat_out.name}",
                f"- {nonnat_out.name}",
                "- preparation-summary.json",
                "",
                "Safety changes applied:",
                "- EipAllocationId cleared in all three parameter files",
                f"- CustomerSotTableName suffixed to {muxer_map.get('CustomerSotTableName')}",
                "",
                "Next step:",
                "Run deploy_empty_platform.py with --muxer-params, --nat-headend-params, and --nonnat-headend-params",
                "pointing at these generated files.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
