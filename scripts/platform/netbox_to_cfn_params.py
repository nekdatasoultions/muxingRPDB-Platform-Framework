#!/usr/bin/env python3
"""Generate CloudFormation parameter JSON from NetBox (SoT)."""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


def _http_get(url: str, token: str) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Token {token}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_paginated(base_url: str, token: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    next_url: Optional[str] = base_url
    while next_url:
        page = _http_get(next_url, token)
        results = page.get("results", [])
        if not isinstance(results, list):
            raise RuntimeError(f"Unexpected NetBox payload at {next_url}: no list 'results'")
        items.extend(results)
        next_url = page.get("next")
    return items


def _extract_primary_ip(raw: Any) -> str:
    if raw is None:
        raise ValueError("primary_ip4 is missing")
    if isinstance(raw, dict):
        address = raw.get("address")
    else:
        address = str(raw)
    if not address:
        raise ValueError("primary_ip4 address empty")
    return str(ipaddress.ip_interface(address).ip)


def _infer_node(name: str) -> Optional[str]:
    lower = name.lower()
    if lower.endswith("-a") or "headend-a" in lower:
        return "a"
    if lower.endswith("-b") or "headend-b" in lower:
        return "b"
    return None


def _find_nodes(
    objects: List[Dict[str, Any]],
    node_field: str,
    subnet_field: str,
    vpc_field: str,
) -> Dict[str, Dict[str, Any]]:
    nodes: Dict[str, Dict[str, Any]] = {}
    for obj in objects:
        name = str(obj.get("name", "")).strip()
        cfs = obj.get("custom_fields", {}) or {}
        node = str(cfs.get(node_field, "")).strip().lower() or _infer_node(name)
        if node not in {"a", "b"}:
            continue

        subnet_id = str(cfs.get(subnet_field, "")).strip()
        if not subnet_id:
            continue
        primary_ip = _extract_primary_ip(obj.get("primary_ip4"))
        vpc_id = str(cfs.get(vpc_field, "")).strip()

        nodes[node] = {
            "name": name,
            "primary_ip": primary_ip,
            "subnet_id": subnet_id,
            "vpc_id": vpc_id,
        }
    return nodes


def _param(key: str, value: str) -> Dict[str, str]:
    return {"ParameterKey": key, "ParameterValue": value}


def main() -> int:
    ap = argparse.ArgumentParser(description="Build CFN params from NetBox devices")
    ap.add_argument("--netbox-url", required=True, help="Base URL, e.g. https://netbox.example.com")
    ap.add_argument("--netbox-token", required=True, help="NetBox API token")
    ap.add_argument("--cluster-tag", required=True, help="NetBox tag selecting HA node objects")
    ap.add_argument("--cluster-name", required=True, help="CloudFormation ClusterName")
    ap.add_argument("--ami-id", required=True)
    ap.add_argument("--instance-type", default="t3.small")
    ap.add_argument("--key-name", required=True)
    ap.add_argument("--project-package-s3-uri", required=True)
    ap.add_argument("--lease-table-name", default="")
    ap.add_argument("--allowed-ingress-cidr", default="0.0.0.0/0")
    ap.add_argument("--allow-gre-ingress", default="true", choices=["true", "false"])
    ap.add_argument("--gre-ingress-cidr", default="")
    ap.add_argument("--core-ingress-cidr", default="")
    ap.add_argument("--eip-allocation-id", default="")
    ap.add_argument("--flow-sync-mode", default="conntrackd", choices=["none", "conntrackd"])
    ap.add_argument(
        "--sa-sync-mode",
        default="libreswan-no-sa-sync",
        choices=["none", "libreswan-no-sa-sync", "strongswan-ha"],
    )
    ap.add_argument("--ipsec-service", default="ipsec")
    ap.add_argument("--ipsec-backend", default="libreswan", choices=["libreswan", "strongswan"])
    ap.add_argument("--node-field", default="ha_node", help="NetBox custom field name for node role (a/b)")
    ap.add_argument("--subnet-field", default="aws_subnet_id", help="NetBox custom field containing subnet-id")
    ap.add_argument("--vpc-field", default="aws_vpc_id", help="NetBox custom field containing vpc-id")
    ap.add_argument("--ha-sync-subnet-a-id", default="")
    ap.add_argument("--ha-sync-subnet-b-id", default="")
    ap.add_argument("--node-a-ha-sync-ip", default="")
    ap.add_argument("--node-b-ha-sync-ip", default="")
    ap.add_argument("--core-subnet-a-id", default="")
    ap.add_argument("--core-subnet-b-id", default="")
    ap.add_argument("--node-a-core-ip", default="")
    ap.add_argument("--node-b-core-ip", default="")
    ap.add_argument("--output", required=True, help="Path to output parameter JSON file")
    args = ap.parse_args()

    base = args.netbox_url.rstrip("/")
    tag_q = urllib.parse.quote(args.cluster_tag)

    dcim_url = f"{base}/api/dcim/devices/?tag={tag_q}&status=active&limit=100"
    vm_url = f"{base}/api/virtualization/virtual-machines/?tag={tag_q}&status=active&limit=100"

    objects = _get_paginated(dcim_url, args.netbox_token)
    objects.extend(_get_paginated(vm_url, args.netbox_token))
    if not objects:
        raise SystemExit(f"No NetBox devices/VMs found for tag '{args.cluster_tag}'")

    nodes = _find_nodes(objects, args.node_field, args.subnet_field, args.vpc_field)
    if "a" not in nodes or "b" not in nodes:
        raise SystemExit(
            "Could not resolve both HA nodes from NetBox. "
            "Ensure custom field mapping includes node role (a/b), subnet ID, and primary_ip4."
        )

    vpc_id = nodes["a"]["vpc_id"] or nodes["b"]["vpc_id"]
    if not vpc_id:
        raise SystemExit(
            f"VPC id missing in custom field '{args.vpc_field}' on both node objects."
        )

    params = [
        _param("ClusterName", args.cluster_name),
        _param("VpcId", vpc_id),
        _param("SubnetAId", nodes["a"]["subnet_id"]),
        _param("SubnetBId", nodes["b"]["subnet_id"]),
        _param("NodeAPrivateIp", nodes["a"]["primary_ip"]),
        _param("NodeBPrivateIp", nodes["b"]["primary_ip"]),
        _param("AllowedIngressCidr", args.allowed_ingress_cidr),
        _param("AllowGreIngress", args.allow_gre_ingress),
        _param("AmiId", args.ami_id),
        _param("InstanceType", args.instance_type),
        _param("KeyName", args.key_name),
        _param("ProjectPackageS3Uri", args.project_package_s3_uri),
        _param("EipAllocationId", args.eip_allocation_id),
        _param("LeaseTableName", args.lease_table_name),
        _param("FlowSyncMode", args.flow_sync_mode),
        _param("SaSyncMode", args.sa_sync_mode),
        _param("IpsecService", args.ipsec_service),
        _param("IpsecBackend", args.ipsec_backend),
    ]

    optional_params = [
        ("GreIngressCidr", args.gre_ingress_cidr),
        ("CoreIngressCidr", args.core_ingress_cidr),
        ("HaSyncSubnetAId", args.ha_sync_subnet_a_id),
        ("HaSyncSubnetBId", args.ha_sync_subnet_b_id),
        ("NodeAHaSyncIp", args.node_a_ha_sync_ip),
        ("NodeBHaSyncIp", args.node_b_ha_sync_ip),
        ("CoreSubnetAId", args.core_subnet_a_id),
        ("CoreSubnetBId", args.core_subnet_b_id),
        ("NodeACoreIp", args.node_a_core_ip),
        ("NodeBCoreIp", args.node_b_core_ip),
    ]
    for key, value in optional_params:
        if value:
            params.append(_param(key, value))

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(params, fh, indent=2)
        fh.write("\n")

    print(f"Wrote {len(params)} CloudFormation parameters to {args.output}")
    print(f"Node A: {nodes['a']['name']} {nodes['a']['primary_ip']} {nodes['a']['subnet_id']}")
    print(f"Node B: {nodes['b']['name']} {nodes['b']['primary_ip']} {nodes['b']['subnet_id']}")
    print(f"VPC: {vpc_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
