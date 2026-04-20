#!/usr/bin/env python
"""Generate safe empty-platform parameter files from the current production shape."""

from __future__ import annotations

import argparse
import ipaddress
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Set


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGION = "us-east-1"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "build" / "empty-platform" / "current-prod-shape-rpdb-empty"
DEFAULT_S3_BUCKET = "baines-networking"
DEFAULT_S3_PREFIX_ROOT = "Code/muxingRPDB-Platform-Framework/empty-platform"
DEFAULT_STRONGSWAN_ARCHIVE_NAME = "strongswan-6.0.4.tar.bz2"
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
        elif key == "RecoveryScheduleState":
            updated["ParameterValue"] = "ENABLED"
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


def _update_parameter(payload: List[Dict[str, str]], key: str, value: str) -> None:
    for item in payload:
        if item.get("ParameterKey") == key:
            item["ParameterValue"] = value
            return
    payload.append({"ParameterKey": key, "ParameterValue": value})


def _parameter_map(payload: List[Dict[str, str]]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for item in payload:
        key = str(item.get("ParameterKey") or "").strip()
        if key:
            result[key] = str(item.get("ParameterValue") or "").strip()
    return result


def _aws_ec2_base(region: str | None = None) -> List[str]:
    command = ["aws", "ec2"]
    if region:
        command.extend(["--region", region])
    return command


def _describe_subnets(subnet_ids: List[str], region: str | None = None) -> Dict[str, ipaddress.IPv4Network]:
    if not subnet_ids:
        return {}

    completed = subprocess.run(
        _aws_ec2_base(region)
        + [
            "describe-subnets",
            "--subnet-ids",
            *subnet_ids,
            "--query",
            "Subnets[].{SubnetId:SubnetId,CidrBlock:CidrBlock}",
            "--output",
            "json",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout or "[]")
    result: Dict[str, ipaddress.IPv4Network] = {}
    for item in payload:
        result[str(item["SubnetId"])] = ipaddress.ip_network(str(item["CidrBlock"]))
    return result


def _describe_used_ips(subnet_ids: List[str], region: str | None = None) -> Dict[str, Set[ipaddress.IPv4Address]]:
    if not subnet_ids:
        return {}

    completed = subprocess.run(
        _aws_ec2_base(region)
        + [
            "describe-network-interfaces",
            "--filters",
            f"Name=subnet-id,Values={','.join(subnet_ids)}",
            "--query",
            "NetworkInterfaces[].{SubnetId:SubnetId,PrivateIp:PrivateIpAddress}",
            "--output",
            "json",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout or "[]")
    result: Dict[str, Set[ipaddress.IPv4Address]] = {subnet_id: set() for subnet_id in subnet_ids}
    for item in payload:
        subnet_id = str(item["SubnetId"])
        result.setdefault(subnet_id, set()).add(ipaddress.ip_address(str(item["PrivateIp"])))
    return result


def _reserved_ips(network: ipaddress.IPv4Network) -> Set[ipaddress.IPv4Address]:
    base = int(network.network_address)
    return {
        ipaddress.ip_address(base + 0),
        ipaddress.ip_address(base + 1),
        ipaddress.ip_address(base + 2),
        ipaddress.ip_address(base + 3),
        network.broadcast_address,
    }


def _pick_next_free_ip(
    current_ip: str,
    subnet_id: str,
    subnet_networks: Dict[str, ipaddress.IPv4Network],
    used_by_subnet: Dict[str, Set[ipaddress.IPv4Address]],
) -> str:
    network = subnet_networks[subnet_id]
    current = ipaddress.ip_address(current_ip)
    used = set(used_by_subnet.get(subnet_id, set()))
    used.update(_reserved_ips(network))

    upper = int(network.broadcast_address) - 1
    lower = int(network.network_address) + 4
    start = int(current)

    for candidate in range(start + 1, upper + 1):
        address = ipaddress.ip_address(candidate)
        if address not in used:
            used_by_subnet.setdefault(subnet_id, set()).add(address)
            return str(address)

    for candidate in range(start - 1, lower - 1, -1):
        address = ipaddress.ip_address(candidate)
        if address not in used:
            used_by_subnet.setdefault(subnet_id, set()).add(address)
            return str(address)

    raise ValueError(f"no free IP found in {subnet_id} ({network}) for source {current_ip}")


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
    parser.add_argument("--artifact-s3-bucket", default=DEFAULT_S3_BUCKET, help="Bucket to use for rehearsal artifact uploads")
    parser.add_argument(
        "--artifact-s3-prefix-root",
        default=DEFAULT_S3_PREFIX_ROOT,
        help="S3 prefix root to use for rehearsal artifact uploads",
    )
    parser.add_argument(
        "--auto-select-private-ips-from-aws",
        action="store_true",
        help="Query AWS and replace the imported static private IPs with unused addresses in the same subnets",
    )
    args = parser.parse_args()

    suffix = _normalize_suffix(args.suffix)
    output_dir = Path(args.output_dir).resolve()

    muxer_source = Path(args.muxer_params).resolve()
    nat_source = Path(args.nat_headend_params).resolve()
    nonnat_source = Path(args.nonnat_headend_params).resolve()

    muxer_payload = _transform_muxer(_load_parameter_array(muxer_source), suffix)
    nat_payload = _transform_headend(_load_parameter_array(nat_source), suffix)
    nonnat_payload = _transform_headend(_load_parameter_array(nonnat_source), suffix)

    bucket = args.artifact_s3_bucket.strip()
    prefix_root = args.artifact_s3_prefix_root.strip().strip("/")
    prefix = f"{prefix_root}/{suffix}"
    muxer_bundle_uri = f"s3://{bucket}/{prefix}/rpdb-muxer-runtime-bundle.zip"
    deployment_bundle_uri = f"s3://{bucket}/{prefix}/rpdb-platform-bundle.zip"
    strongswan_archive_uri = f"s3://{bucket}/{prefix}/{DEFAULT_STRONGSWAN_ARCHIVE_NAME}"
    recovery_lambda_key = f"{prefix}/muxer-recovery-lambda.zip"

    _update_parameter(muxer_payload, "ProjectPackageS3Uri", muxer_bundle_uri)
    _update_parameter(muxer_payload, "RecoveryLambdaS3Bucket", bucket)
    _update_parameter(muxer_payload, "RecoveryLambdaS3Key", recovery_lambda_key)
    _update_parameter(nat_payload, "ProjectPackageS3Uri", deployment_bundle_uri)
    _update_parameter(nonnat_payload, "ProjectPackageS3Uri", deployment_bundle_uri)
    _update_parameter(nat_payload, "StrongswanArchiveUri", strongswan_archive_uri)
    _update_parameter(nonnat_payload, "StrongswanArchiveUri", strongswan_archive_uri)

    selected_private_ips: Dict[str, str] = {}
    if args.auto_select_private_ips_from_aws:
        muxer_map = _parameter_map(muxer_payload)
        nat_map = _parameter_map(nat_payload)
        nonnat_map = _parameter_map(nonnat_payload)

        subnet_ids = [
            muxer_map["TransportSubnetAId"],
            muxer_map["TransportSubnetBId"],
            nat_map["SubnetAId"],
            nat_map["SubnetBId"],
            nat_map["HaSyncSubnetAId"],
            nat_map["HaSyncSubnetBId"],
            nat_map["CoreSubnetAId"],
            nat_map["CoreSubnetBId"],
            nonnat_map["SubnetAId"],
            nonnat_map["SubnetBId"],
            nonnat_map["HaSyncSubnetAId"],
            nonnat_map["HaSyncSubnetBId"],
            nonnat_map["CoreSubnetAId"],
            nonnat_map["CoreSubnetBId"],
        ]
        subnet_ids = list(dict.fromkeys(subnet_ids))
        subnet_networks = _describe_subnets(subnet_ids, region=args.region)
        used_by_subnet = _describe_used_ips(subnet_ids, region=args.region)

        replacements = [
            (muxer_payload, "muxer.TransportEniAIp", "TransportEniAIp", muxer_map["TransportSubnetAId"]),
            (muxer_payload, "muxer.TransportEniBIp", "TransportEniBIp", muxer_map["TransportSubnetBId"]),
            (nat_payload, "nat.NodeAPrivateIp", "NodeAPrivateIp", nat_map["SubnetAId"]),
            (nat_payload, "nat.NodeBPrivateIp", "NodeBPrivateIp", nat_map["SubnetBId"]),
            (nat_payload, "nat.NodeAHaSyncIp", "NodeAHaSyncIp", nat_map["HaSyncSubnetAId"]),
            (nat_payload, "nat.NodeBHaSyncIp", "NodeBHaSyncIp", nat_map["HaSyncSubnetBId"]),
            (nat_payload, "nat.NodeACoreIp", "NodeACoreIp", nat_map["CoreSubnetAId"]),
            (nat_payload, "nat.NodeBCoreIp", "NodeBCoreIp", nat_map["CoreSubnetBId"]),
            (nonnat_payload, "non_nat.NodeAPrivateIp", "NodeAPrivateIp", nonnat_map["SubnetAId"]),
            (nonnat_payload, "non_nat.NodeBPrivateIp", "NodeBPrivateIp", nonnat_map["SubnetBId"]),
            (nonnat_payload, "non_nat.NodeAHaSyncIp", "NodeAHaSyncIp", nonnat_map["HaSyncSubnetAId"]),
            (nonnat_payload, "non_nat.NodeBHaSyncIp", "NodeBHaSyncIp", nonnat_map["HaSyncSubnetBId"]),
            (nonnat_payload, "non_nat.NodeACoreIp", "NodeACoreIp", nonnat_map["CoreSubnetAId"]),
            (nonnat_payload, "non_nat.NodeBCoreIp", "NodeBCoreIp", nonnat_map["CoreSubnetBId"]),
        ]

        for payload, summary_key, parameter_key, subnet_id in replacements:
            for item in payload:
                if item.get("ParameterKey") == parameter_key:
                    original = str(item.get("ParameterValue") or "").strip()
                    replacement = _pick_next_free_ip(original, subnet_id, subnet_networks, used_by_subnet)
                    item["ParameterValue"] = replacement
                    selected_private_ips[summary_key] = replacement
                    break

    nat_map = _parameter_map(nat_payload)
    nonnat_map = _parameter_map(nonnat_payload)
    _update_parameter(muxer_payload, "NatActiveAUnderlayIp", nat_map["NodeAPrivateIp"])
    _update_parameter(muxer_payload, "NatActiveBUnderlayIp", nat_map["NodeBPrivateIp"])
    _update_parameter(muxer_payload, "NonNatActiveAUnderlayIp", nonnat_map["NodeAPrivateIp"])
    _update_parameter(muxer_payload, "NonNatActiveBUnderlayIp", nonnat_map["NodeBPrivateIp"])

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
            "artifact_upload_prefix": f"s3://{bucket}/{prefix}/",
            "strongswan_archive_s3_uri": strongswan_archive_uri,
        },
        "muxer_backend_role_map": {
            "nat-active": {
                "us-east-1a": nat_map.get("NodeAPrivateIp"),
                "us-east-1b": nat_map.get("NodeBPrivateIp"),
            },
            "nonnat-active": {
                "us-east-1a": nonnat_map.get("NodeAPrivateIp"),
                "us-east-1b": nonnat_map.get("NodeBPrivateIp"),
            },
        },
        "selected_private_ips": selected_private_ips,
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
                f"- Artifact uploads redirected to s3://{bucket}/{prefix}/",
                f"- StrongswanArchiveUri pinned to {strongswan_archive_uri}",
                (
                    "- Static private IPs replaced with currently unused addresses in the same subnets"
                    if selected_private_ips
                    else "- Static private IPs preserved from the imported parameter files"
                ),
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
