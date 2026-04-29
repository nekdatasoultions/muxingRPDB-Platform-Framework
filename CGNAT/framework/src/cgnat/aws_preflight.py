from __future__ import annotations

from typing import Any


BLOCKING_SEVERITIES = {"error", "blocking_gap", "hard_no_go"}


def blocking_issue_count(issues: list[dict[str, Any]]) -> int:
    return len([issue for issue in issues if issue.get("severity") in BLOCKING_SEVERITIES])


def analyze_aws_inventory(package: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []

    manifest = package["manifest"]
    head_end = package["cgnat_head_end"]
    isp_head_end = package["cgnat_isp_head_end"]
    dependencies = package["dependencies"]
    expected_vpc_id = dependencies["aws"]["vpc_id"]

    sts_identity = inventory.get("sts_identity") or {}
    if not sts_identity.get("Account"):
        issues.append(
            {
                "code": "missing_sts_identity",
                "severity": "error",
                "message": "Unable to resolve AWS caller identity for live preflight.",
            }
        )

    subnets = {entry["SubnetId"]: entry for entry in inventory.get("subnets", []) if isinstance(entry, dict)}
    head_subnet = subnets.get(head_end["subnet_id"])
    transit_subnet = subnets.get(isp_head_end["subnets"]["transit_subnet_id"])
    customer_subnet = subnets.get(isp_head_end["subnets"]["customer_subnet_id"])

    for code_prefix, subnet_id, subnet in (
        ("head_end_subnet", head_end["subnet_id"], head_subnet),
        ("isp_transit_subnet", isp_head_end["subnets"]["transit_subnet_id"], transit_subnet),
        ("isp_customer_subnet", isp_head_end["subnets"]["customer_subnet_id"], customer_subnet),
    ):
        if not subnet:
            issues.append(
                {
                    "code": f"{code_prefix}_missing",
                    "severity": "error",
                    "message": f"Required subnet `{subnet_id}` was not found in AWS.",
                }
            )
            continue
        if subnet.get("VpcId") != expected_vpc_id:
            issues.append(
                {
                    "code": f"{code_prefix}_wrong_vpc",
                    "severity": "error",
                    "message": f"Subnet `{subnet_id}` is in VPC `{subnet.get('VpcId')}`, expected `{expected_vpc_id}`.",
                }
            )

    if transit_subnet and customer_subnet:
        transit_az = transit_subnet.get("AvailabilityZone")
        customer_az = customer_subnet.get("AvailabilityZone")
        if transit_az != customer_az:
            issues.append(
                {
                    "code": "isp_head_end_subnet_az_mismatch",
                    "severity": "hard_no_go",
                    "message": (
                        "CGNAT ISP HEAD END transit and customer subnets are in different availability zones "
                        f"(`{transit_az}` vs `{customer_az}`). A single EC2 instance cannot attach ENIs across AZs."
                    ),
                }
            )

    security_groups = {entry["GroupId"]: entry for entry in inventory.get("security_groups", []) if isinstance(entry, dict)}
    for role_name, role in (("cgnat_head_end", head_end), ("cgnat_isp_head_end", isp_head_end)):
        for sg_id in role.get("security_group_ids", []):
            group = security_groups.get(sg_id)
            if not group:
                issues.append(
                    {
                        "code": f"{role_name}_security_group_missing_{sg_id}",
                        "severity": "error",
                        "message": f"Security group `{sg_id}` required by `{role_name}` was not found.",
                    }
                )
                continue
            if group.get("VpcId") != expected_vpc_id:
                issues.append(
                    {
                        "code": f"{role_name}_security_group_wrong_vpc_{sg_id}",
                        "severity": "error",
                        "message": f"Security group `{sg_id}` is in VPC `{group.get('VpcId')}`, expected `{expected_vpc_id}`.",
                    }
                )

    image_ids = {entry["ImageId"] for entry in inventory.get("images", []) if isinstance(entry, dict)}
    for role_name, role in (("cgnat_head_end", head_end), ("cgnat_isp_head_end", isp_head_end)):
        if role.get("ami_id") not in image_ids:
            issues.append(
                {
                    "code": f"{role_name}_ami_missing",
                    "severity": "error",
                    "message": f"AMI `{role.get('ami_id')}` required by `{role_name}` was not found.",
                }
            )

    instance_profiles = set(inventory.get("instance_profiles", []))
    for role_name, role in (("cgnat_head_end", head_end), ("cgnat_isp_head_end", isp_head_end)):
        if role.get("iam_instance_profile") not in instance_profiles:
            issues.append(
                {
                    "code": f"{role_name}_instance_profile_missing",
                    "severity": "error",
                    "message": (
                        f"IAM instance profile `{role.get('iam_instance_profile')}` required by `{role_name}` "
                        "was not found."
                    ),
                }
            )

    key_pairs = set(inventory.get("key_pairs", []))
    for role_name, role in (("cgnat_head_end", head_end), ("cgnat_isp_head_end", isp_head_end)):
        key_name = role.get("key_pair_name")
        if key_name and key_name not in key_pairs:
            issues.append(
                {
                    "code": f"{role_name}_key_pair_missing",
                    "severity": "error",
                    "message": f"EC2 key pair `{key_name}` required by `{role_name}` was not found.",
                }
            )

    addresses = {entry["AllocationId"]: entry for entry in inventory.get("addresses", []) if isinstance(entry, dict)}
    if head_end.get("public_eip_strategy") == "existing_allocation":
        allocation_id = head_end.get("public_eip_allocation_id")
        if allocation_id not in addresses:
            issues.append(
                {
                    "code": "head_end_eip_missing",
                    "severity": "error",
                    "message": f"Existing head-end EIP allocation `{allocation_id}` was not found.",
                }
            )
    if isp_head_end.get("public_eip_strategy") == "existing_allocation":
        allocation_id = isp_head_end.get("public_eip_allocation_id")
        if allocation_id not in addresses:
            issues.append(
                {
                    "code": "isp_head_end_eip_missing",
                    "severity": "error",
                    "message": f"Existing ISP head-end EIP allocation `{allocation_id}` was not found.",
                }
            )

    return {
        "preflight_type": "scenario1_live_aws_preflight",
        "service_id": manifest["service_id"],
        "customer_id": manifest["customer_id"],
        "environment_name": manifest["environment_name"],
        "issues": issues,
        "inventory_summary": {
            "account_id": sts_identity.get("Account"),
            "head_end_subnet_az": head_subnet.get("AvailabilityZone") if head_subnet else None,
            "isp_transit_subnet_az": transit_subnet.get("AvailabilityZone") if transit_subnet else None,
            "isp_customer_subnet_az": customer_subnet.get("AvailabilityZone") if customer_subnet else None,
            "expected_vpc_id": expected_vpc_id,
        },
        "ready_for_live_apply": blocking_issue_count(issues) == 0,
    }
