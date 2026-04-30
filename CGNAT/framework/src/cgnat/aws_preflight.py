from __future__ import annotations

import ipaddress
from typing import Any


BLOCKING_SEVERITIES = {"error", "blocking_gap", "hard_no_go"}


def blocking_issue_count(issues: list[dict[str, Any]]) -> int:
    return len([issue for issue in issues if issue.get("severity") in BLOCKING_SEVERITIES])


def _append_issue(issues: list[dict[str, Any]], code: str, severity: str, message: str) -> None:
    issues.append({"code": code, "severity": severity, "message": message})


def _subnet_contains_ip(subnet: dict[str, Any] | None, ip_value: str) -> bool:
    if not subnet or not ip_value:
        return False
    return ipaddress.ip_address(ip_value) in ipaddress.ip_network(subnet["CidrBlock"], strict=False)


def _validate_security_groups(
    issues: list[dict[str, Any]],
    *,
    role_name: str,
    role: dict[str, Any],
    security_groups: dict[str, dict[str, Any]],
    expected_vpc_id: str,
) -> None:
    for sg_id in role.get("security_group_ids", []):
        group = security_groups.get(sg_id)
        if not group:
            _append_issue(
                issues,
                f"{role_name}_security_group_missing_{sg_id}",
                "error",
                f"Security group `{sg_id}` required by `{role_name}` was not found.",
            )
            continue
        if group.get("VpcId") != expected_vpc_id:
            _append_issue(
                issues,
                f"{role_name}_security_group_wrong_vpc_{sg_id}",
                "error",
                f"Security group `{sg_id}` is in VPC `{group.get('VpcId')}`, expected `{expected_vpc_id}`.",
            )


def _validate_image_profile_key(
    issues: list[dict[str, Any]],
    *,
    role_name: str,
    role: dict[str, Any],
    image_ids: set[str],
    instance_profiles: set[str],
    key_pairs: set[str],
) -> None:
    if role.get("ami_id") not in image_ids:
        _append_issue(
            issues,
            f"{role_name}_ami_missing",
            "error",
            f"AMI `{role.get('ami_id')}` required by `{role_name}` was not found.",
        )
    if role.get("iam_instance_profile") not in instance_profiles:
        _append_issue(
            issues,
            f"{role_name}_instance_profile_missing",
            "error",
            f"IAM instance profile `{role.get('iam_instance_profile')}` required by `{role_name}` was not found.",
        )
    key_name = role.get("key_pair_name")
    if key_name and key_name not in key_pairs:
        _append_issue(
            issues,
            f"{role_name}_key_pair_missing",
            "error",
            f"EC2 key pair `{key_name}` required by `{role_name}` was not found.",
        )


def analyze_aws_inventory(package: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []

    manifest = package["manifest"]
    head_end = package["cgnat_head_end"]
    isp_head_end = package["cgnat_isp_head_end"]
    customer_vpn_routers = list(package.get("customer_vpn_routers") or [])
    dependencies = package["dependencies"]
    expected_vpc_id = dependencies["aws"]["vpc_id"]

    sts_identity = inventory.get("sts_identity") or {}
    if not sts_identity.get("Account"):
        _append_issue(issues, "missing_sts_identity", "error", "Unable to resolve AWS caller identity for live preflight.")

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
            _append_issue(issues, f"{code_prefix}_missing", "error", f"Required subnet `{subnet_id}` was not found in AWS.")
            continue
        if subnet.get("VpcId") != expected_vpc_id:
            _append_issue(
                issues,
                f"{code_prefix}_wrong_vpc",
                "error",
                f"Subnet `{subnet_id}` is in VPC `{subnet.get('VpcId')}`, expected `{expected_vpc_id}`.",
            )

    if transit_subnet and customer_subnet:
        transit_az = transit_subnet.get("AvailabilityZone")
        customer_az = customer_subnet.get("AvailabilityZone")
        if transit_az != customer_az:
            _append_issue(
                issues,
                "isp_head_end_subnet_az_mismatch",
                "hard_no_go",
                (
                    "CGNAT ISP HEAD END transit and customer subnets are in different availability zones "
                    f"(`{transit_az}` vs `{customer_az}`). A single EC2 instance cannot attach ENIs across AZs."
                ),
            )

    isp_customer_private_ip = str(isp_head_end.get("customer_facing_private_ip") or "").strip()
    if customer_subnet and isp_customer_private_ip and not _subnet_contains_ip(customer_subnet, isp_customer_private_ip):
        _append_issue(
            issues,
            "isp_customer_private_ip_outside_subnet",
            "error",
            (
                f"CGNAT ISP HEAD END customer_facing_private_ip `{isp_customer_private_ip}` is not inside "
                f"customer subnet `{customer_subnet['SubnetId']}` ({customer_subnet['CidrBlock']})."
            ),
        )

    security_groups = {entry["GroupId"]: entry for entry in inventory.get("security_groups", []) if isinstance(entry, dict)}
    image_ids = {entry["ImageId"] for entry in inventory.get("images", []) if isinstance(entry, dict)}
    instance_profiles = set(inventory.get("instance_profiles", []))
    key_pairs = set(inventory.get("key_pairs", []))

    _validate_security_groups(issues, role_name="cgnat_head_end", role=head_end, security_groups=security_groups, expected_vpc_id=expected_vpc_id)
    _validate_security_groups(issues, role_name="cgnat_isp_head_end", role=isp_head_end, security_groups=security_groups, expected_vpc_id=expected_vpc_id)
    _validate_image_profile_key(issues, role_name="cgnat_head_end", role=head_end, image_ids=image_ids, instance_profiles=instance_profiles, key_pairs=key_pairs)
    _validate_image_profile_key(issues, role_name="cgnat_isp_head_end", role=isp_head_end, image_ids=image_ids, instance_profiles=instance_profiles, key_pairs=key_pairs)

    seen_router_private_ips: set[str] = set()
    router_inventory_summary: list[dict[str, Any]] = []
    for router in customer_vpn_routers:
        role_name = str(router.get("role") or "customer_vpn_router")
        router_subnet = subnets.get(router["subnet_id"])
        if not router_subnet:
            _append_issue(issues, f"{role_name}_subnet_missing", "error", f"Customer VPN router subnet `{router['subnet_id']}` was not found in AWS.")
        elif router_subnet.get("VpcId") != expected_vpc_id:
            _append_issue(
                issues,
                f"{role_name}_subnet_wrong_vpc",
                "error",
                f"Customer VPN router subnet `{router['subnet_id']}` is in VPC `{router_subnet.get('VpcId')}`, expected `{expected_vpc_id}`.",
            )

        private_ip = str(router.get("private_ip_address") or "").strip()
        if router_subnet and private_ip and not _subnet_contains_ip(router_subnet, private_ip):
            _append_issue(
                issues,
                f"{role_name}_private_ip_outside_subnet",
                "error",
                (
                    f"Customer VPN router private_ip_address `{private_ip}` is not inside subnet "
                    f"`{router_subnet['SubnetId']}` ({router_subnet['CidrBlock']})."
                ),
            )
        if private_ip:
            if private_ip == isp_customer_private_ip:
                _append_issue(
                    issues,
                    f"{role_name}_private_ip_conflicts_with_isp",
                    "error",
                    f"Customer VPN router private_ip_address `{private_ip}` conflicts with the ISP customer-facing private IP.",
                )
            elif private_ip in seen_router_private_ips:
                _append_issue(
                    issues,
                    f"{role_name}_duplicate_private_ip",
                    "error",
                    f"Customer VPN router private_ip_address `{private_ip}` is duplicated.",
                )
            else:
                seen_router_private_ips.add(private_ip)

        _validate_security_groups(issues, role_name=role_name, role=router, security_groups=security_groups, expected_vpc_id=expected_vpc_id)
        _validate_image_profile_key(issues, role_name=role_name, role=router, image_ids=image_ids, instance_profiles=instance_profiles, key_pairs=key_pairs)

        router_inventory_summary.append(
            {
                "role": role_name,
                "subnet_id": router.get("subnet_id"),
                "subnet_az": router_subnet.get("AvailabilityZone") if router_subnet else None,
                "private_ip_address": private_ip,
            }
        )

    addresses = {entry["AllocationId"]: entry for entry in inventory.get("addresses", []) if isinstance(entry, dict)}
    if head_end.get("public_eip_strategy") == "existing_allocation":
        allocation_id = head_end.get("public_eip_allocation_id")
        if allocation_id not in addresses:
            _append_issue(issues, "head_end_eip_missing", "error", f"Existing head-end EIP allocation `{allocation_id}` was not found.")
    if isp_head_end.get("public_eip_strategy") == "existing_allocation":
        allocation_id = isp_head_end.get("public_eip_allocation_id")
        if allocation_id not in addresses:
            _append_issue(issues, "isp_head_end_eip_missing", "error", f"Existing ISP head-end EIP allocation `{allocation_id}` was not found.")

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
            "customer_vpn_routers": router_inventory_summary,
        },
        "ready_for_live_apply": blocking_issue_count(issues) == 0,
    }
