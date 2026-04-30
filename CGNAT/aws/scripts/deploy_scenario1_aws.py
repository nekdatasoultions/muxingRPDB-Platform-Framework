from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _framework_src_root() -> Path:
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent.parent / "framework" / "src"


def _load_json(path: Path) -> dict[str, Any] | list[Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_package(package_dir: Path) -> dict[str, Any]:
    return {
        "manifest": _load_json(package_dir / "package-manifest.json"),
        "cgnat_head_end": _load_json(package_dir / "cgnat-head-end.json"),
        "cgnat_isp_head_end": _load_json(package_dir / "cgnat-isp-head-end.json"),
        "customer_vpn_routers": _load_json(package_dir / "customer-vpn-routers.json"),
        "dependencies": _load_json(package_dir / "dependencies.json"),
        "deployment_order": _load_json(package_dir / "deployment-order.json"),
    }


def _append_issue(issues: list[dict[str, Any]], code: str, severity: str, message: str) -> None:
    issues.append({"code": code, "severity": severity, "message": message})


def _detect_issues(package: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    manifest = package["manifest"]
    dependencies = package["dependencies"]
    cgnat_head_end = package["cgnat_head_end"]
    cgnat_isp_head_end = package["cgnat_isp_head_end"]
    customer_vpn_routers = list(package.get("customer_vpn_routers") or [])

    if manifest.get("scenario") != "scenario1":
        _append_issue(issues, "unsupported_scenario", "error", "This deploy script currently supports Scenario 1 only.")

    aws_section = dependencies.get("aws") or {}
    if not aws_section.get("region") or not aws_section.get("vpc_id"):
        _append_issue(issues, "missing_aws_context", "error", "AWS region and VPC ID are required for deployment planning.")

    default_tags = dependencies.get("default_tags")
    if not isinstance(default_tags, dict) or not default_tags:
        _append_issue(issues, "missing_default_tags", "blocking_gap", "Default AWS tags are required for live EC2 creation.")

    head_eip_strategy = cgnat_head_end.get("public_eip_strategy") or "existing_allocation"
    if head_eip_strategy not in {"existing_allocation", "allocate_new"}:
        _append_issue(
            issues,
            "invalid_head_end_eip_strategy",
            "error",
            "CGNAT HEAD END public_eip_strategy must be `existing_allocation` or `allocate_new`.",
        )
    if head_eip_strategy == "existing_allocation" and not cgnat_head_end.get("public_eip_allocation_id"):
        _append_issue(
            issues,
            "missing_head_end_eip",
            "error",
            "CGNAT HEAD END public EIP allocation is required when using `existing_allocation`.",
        )

    if not dependencies.get("certificates", {}).get("cgnat_head_end_server_cert_ref"):
        _append_issue(issues, "missing_head_end_cert_ref", "error", "CGNAT HEAD END server certificate reference is required.")

    if not dependencies.get("certificates", {}).get("cgnat_isp_head_end_client_cert_ref"):
        _append_issue(issues, "missing_isp_cert_ref", "error", "CGNAT ISP HEAD END client certificate reference is required.")

    if not dependencies.get("gre_inventory", {}).get("inventory_ref"):
        _append_issue(issues, "missing_gre_inventory", "error", "GRE inventory reference is required.")

    head_launch_checks = {
        "ami_id": cgnat_head_end.get("ami_id"),
        "security_group_ids": cgnat_head_end.get("security_group_ids"),
        "iam_instance_profile": cgnat_head_end.get("iam_instance_profile"),
    }
    for field_name, field_value in head_launch_checks.items():
        if not field_value:
            _append_issue(
                issues,
                f"missing_head_end_launch_field_{field_name}",
                "blocking_gap",
                f"CGNAT HEAD END package is missing `{field_name}` for live EC2 creation.",
            )

    head_root = cgnat_head_end.get("root_volume") or {}
    for field_name in ("device_name", "size_gb", "volume_type", "delete_on_termination"):
        if field_name not in head_root or head_root.get(field_name) in (None, ""):
            _append_issue(
                issues,
                f"missing_head_end_root_volume_field_{field_name}",
                "blocking_gap",
                f"CGNAT HEAD END package is missing root_volume.`{field_name}` for live EC2 creation.",
            )
    if not cgnat_head_end.get("subnet_id"):
        _append_issue(issues, "missing_head_end_subnet_id", "blocking_gap", "CGNAT HEAD END package is missing `subnet_id` for live EC2 creation.")

    isp_launch_checks = {
        "ami_id": cgnat_isp_head_end.get("ami_id"),
        "security_group_ids": cgnat_isp_head_end.get("security_group_ids"),
        "iam_instance_profile": cgnat_isp_head_end.get("iam_instance_profile"),
        "customer_facing_private_ip": cgnat_isp_head_end.get("customer_facing_private_ip"),
    }
    for field_name, field_value in isp_launch_checks.items():
        if not field_value:
            _append_issue(
                issues,
                f"missing_isp_head_end_launch_field_{field_name}",
                "blocking_gap",
                f"CGNAT ISP HEAD END package is missing `{field_name}` for live EC2 creation.",
            )

    isp_root = cgnat_isp_head_end.get("root_volume") or {}
    for field_name in ("device_name", "size_gb", "volume_type", "delete_on_termination"):
        if field_name not in isp_root or isp_root.get(field_name) in (None, ""):
            _append_issue(
                issues,
                f"missing_isp_head_end_root_volume_field_{field_name}",
                "blocking_gap",
                f"CGNAT ISP HEAD END package is missing root_volume.`{field_name}` for live EC2 creation.",
            )
    isp_subnets = cgnat_isp_head_end.get("subnets") or {}
    for field_name in ("transit_subnet_id", "customer_subnet_id"):
        if not isp_subnets.get(field_name):
            _append_issue(
                issues,
                f"missing_isp_head_end_subnet_field_{field_name}",
                "blocking_gap",
                f"CGNAT ISP HEAD END package is missing subnets.`{field_name}` for live EC2 creation.",
            )

    isp_eip_strategy = cgnat_isp_head_end.get("public_eip_strategy") or "none"
    if isp_eip_strategy not in {"none", "existing_allocation", "allocate_new"}:
        _append_issue(
            issues,
            "invalid_isp_head_end_eip_strategy",
            "error",
            "CGNAT ISP HEAD END public_eip_strategy must be `none`, `existing_allocation`, or `allocate_new`.",
        )
    if isp_eip_strategy == "existing_allocation" and not cgnat_isp_head_end.get("public_eip_allocation_id"):
        _append_issue(
            issues,
            "missing_isp_head_end_eip",
            "blocking_gap",
            "CGNAT ISP HEAD END public EIP allocation is required when using `existing_allocation`.",
        )

    if cgnat_head_end.get("placement_rule") != "must_run_only_in_subnet-04a6b7f3a3855d438":
        _append_issue(
            issues,
            "unexpected_head_end_placement_rule",
            "error",
            "CGNAT HEAD END placement rule does not match Scenario 1 expectations.",
        )

    if cgnat_isp_head_end.get("placement_rule") != "must_span_transit_and_customer_subnets":
        _append_issue(
            issues,
            "unexpected_isp_placement_rule",
            "error",
            "CGNAT ISP HEAD END placement rule does not match Scenario 1 expectations.",
        )

    if len(customer_vpn_routers) < 2:
        _append_issue(
            issues,
            "missing_customer_vpn_routers",
            "error",
            "Scenario 1 AWS package must define at least two customer VPN routers.",
        )

    seen_roles: set[str] = set()
    seen_private_ips: set[str] = set()
    isp_customer_private_ip = str(cgnat_isp_head_end.get("customer_facing_private_ip") or "").strip()
    for index, router in enumerate(customer_vpn_routers, start=1):
        role = str(router.get("role") or "").strip()
        if not role:
            _append_issue(issues, f"customer_vpn_router_role_missing_{index}", "blocking_gap", f"Customer VPN router {index} is missing `role`.")
        elif role in seen_roles:
            _append_issue(issues, f"customer_vpn_router_duplicate_role_{index}", "error", f"Customer VPN router role `{role}` is duplicated.")
        else:
            seen_roles.add(role)

        for field_name in ("ami_id", "security_group_ids", "iam_instance_profile", "subnet_id", "private_ip_address"):
            if not router.get(field_name):
                _append_issue(
                    issues,
                    f"{role or f'customer_vpn_router_{index}'}_missing_{field_name}",
                    "blocking_gap",
                    f"Customer VPN router {index} package is missing `{field_name}` for live EC2 creation.",
                )

        router_root = router.get("root_volume") or {}
        for field_name in ("device_name", "size_gb", "volume_type", "delete_on_termination"):
            if field_name not in router_root or router_root.get(field_name) in (None, ""):
                _append_issue(
                    issues,
                    f"{role or f'customer_vpn_router_{index}'}_missing_root_volume_field_{field_name}",
                    "blocking_gap",
                    f"Customer VPN router {index} package is missing root_volume.`{field_name}` for live EC2 creation.",
                )

        private_ip = str(router.get("private_ip_address") or "").strip()
        if private_ip:
            if private_ip == isp_customer_private_ip:
                _append_issue(
                    issues,
                    f"{role or f'customer_vpn_router_{index}'}_private_ip_conflicts_with_isp",
                    "error",
                    f"Customer VPN router {index} private IP overlaps the ISP customer-facing private IP `{isp_customer_private_ip}`.",
                )
            elif private_ip in seen_private_ips:
                _append_issue(
                    issues,
                    f"{role or f'customer_vpn_router_{index}'}_duplicate_private_ip",
                    "error",
                    f"Customer VPN router private IP `{private_ip}` is duplicated.",
                )
            else:
                seen_private_ips.add(private_ip)

        if router.get("placement_rule") != "must_run_only_in_customer_subnet":
            _append_issue(
                issues,
                f"{role or f'customer_vpn_router_{index}'}_unexpected_placement_rule",
                "error",
                f"Customer VPN router {index} placement rule does not match Scenario 1 expectations.",
            )
        if (router.get("public_eip_strategy") or "none") != "none":
            _append_issue(
                issues,
                f"{role or f'customer_vpn_router_{index}'}_public_eip_strategy_invalid",
                "error",
                "Customer VPN routers must not request public EIPs in the Scenario 1 demo.",
            )

    return issues


def _tag_specifications(default_tags: dict[str, Any], **extra_tags: str) -> list[dict[str, Any]]:
    tags = dict(default_tags)
    tags.update(extra_tags)
    return [
        {
            "ResourceType": "instance",
            "Tags": [{"Key": key, "Value": str(value)} for key, value in tags.items()],
        }
    ]


def _build_head_end_run_instances_request(package: dict[str, Any]) -> dict[str, Any]:
    manifest = package["manifest"]
    head_end = package["cgnat_head_end"]
    dependencies = package["dependencies"]
    request = {
        "ImageId": head_end["ami_id"],
        "InstanceType": head_end["instance_type"],
        "MinCount": 1,
        "MaxCount": 1,
        "IamInstanceProfile": {"Name": head_end["iam_instance_profile"]},
        "BlockDeviceMappings": [
            {
                "DeviceName": head_end["root_volume"]["device_name"],
                "Ebs": {
                    "VolumeSize": head_end["root_volume"]["size_gb"],
                    "VolumeType": head_end["root_volume"]["volume_type"],
                    "DeleteOnTermination": head_end["root_volume"]["delete_on_termination"],
                },
            }
        ],
        "NetworkInterfaces": [
            {
                "DeviceIndex": 0,
                "SubnetId": head_end["subnet_id"],
                "Groups": head_end["security_group_ids"],
                "DeleteOnTermination": True,
            }
        ],
        "TagSpecifications": _tag_specifications(
            dependencies["default_tags"],
            Name=head_end["instance_name"],
            ServiceId=manifest["service_id"],
            CustomerId=manifest["customer_id"],
            Role="cgnat_head_end",
        ),
    }
    if head_end.get("key_pair_name"):
        request["KeyName"] = head_end["key_pair_name"]
    return request


def _build_isp_head_end_run_instances_request(package: dict[str, Any]) -> dict[str, Any]:
    manifest = package["manifest"]
    isp_head_end = package["cgnat_isp_head_end"]
    dependencies = package["dependencies"]
    request = {
        "ImageId": isp_head_end["ami_id"],
        "InstanceType": isp_head_end["instance_type"],
        "MinCount": 1,
        "MaxCount": 1,
        "IamInstanceProfile": {"Name": isp_head_end["iam_instance_profile"]},
        "BlockDeviceMappings": [
            {
                "DeviceName": isp_head_end["root_volume"]["device_name"],
                "Ebs": {
                    "VolumeSize": isp_head_end["root_volume"]["size_gb"],
                    "VolumeType": isp_head_end["root_volume"]["volume_type"],
                    "DeleteOnTermination": isp_head_end["root_volume"]["delete_on_termination"],
                },
            }
        ],
        "NetworkInterfaces": [
            {
                "DeviceIndex": 0,
                "SubnetId": isp_head_end["subnets"]["transit_subnet_id"],
                "Groups": isp_head_end["security_group_ids"],
                "DeleteOnTermination": True,
            },
            {
                "DeviceIndex": 1,
                "SubnetId": isp_head_end["subnets"]["customer_subnet_id"],
                "PrivateIpAddress": isp_head_end["customer_facing_private_ip"],
                "Groups": isp_head_end["security_group_ids"],
                "DeleteOnTermination": True,
            },
        ],
        "TagSpecifications": _tag_specifications(
            dependencies["default_tags"],
            Name=isp_head_end["instance_name"],
            ServiceId=manifest["service_id"],
            CustomerId=manifest["customer_id"],
            Role="cgnat_isp_head_end",
        ),
    }
    if isp_head_end.get("key_pair_name"):
        request["KeyName"] = isp_head_end["key_pair_name"]
    return request


def _build_customer_vpn_router_run_instances_requests(package: dict[str, Any]) -> list[dict[str, Any]]:
    manifest = package["manifest"]
    dependencies = package["dependencies"]
    requests: list[dict[str, Any]] = []
    for router in package.get("customer_vpn_routers") or []:
        request = {
            "role": router["role"],
            "request": {
                "ImageId": router["ami_id"],
                "InstanceType": router["instance_type"],
                "MinCount": 1,
                "MaxCount": 1,
                "IamInstanceProfile": {"Name": router["iam_instance_profile"]},
                "BlockDeviceMappings": [
                    {
                        "DeviceName": router["root_volume"]["device_name"],
                        "Ebs": {
                            "VolumeSize": router["root_volume"]["size_gb"],
                            "VolumeType": router["root_volume"]["volume_type"],
                            "DeleteOnTermination": router["root_volume"]["delete_on_termination"],
                        },
                    }
                ],
                "NetworkInterfaces": [
                    {
                        "DeviceIndex": 0,
                        "SubnetId": router["subnet_id"],
                        "PrivateIpAddress": router["private_ip_address"],
                        "Groups": router["security_group_ids"],
                        "DeleteOnTermination": True,
                    }
                ],
                "TagSpecifications": _tag_specifications(
                    dependencies["default_tags"],
                    Name=router["instance_name"],
                    ServiceId=manifest["service_id"],
                    CustomerId=manifest["customer_id"],
                    Role=router["role"],
                ),
            },
        }
        if router.get("key_pair_name"):
            request["request"]["KeyName"] = router["key_pair_name"]
        requests.append(request)
    return requests


def _build_post_create_actions(package: dict[str, Any]) -> dict[str, Any]:
    head_end = package["cgnat_head_end"]
    isp_head_end = package["cgnat_isp_head_end"]
    actions: list[dict[str, Any]] = []

    head_strategy = head_end.get("public_eip_strategy") or "existing_allocation"
    if head_strategy == "existing_allocation":
        actions.append(
            {
                "name": "associate_head_end_eip",
                "service_role": "cgnat_head_end",
                "allocation_id": head_end["public_eip_allocation_id"],
                "association_target": "primary_network_interface",
            }
        )
    elif head_strategy == "allocate_new":
        actions.append(
            {
                "name": "allocate_and_associate_head_end_eip",
                "service_role": "cgnat_head_end",
                "association_target": "primary_network_interface",
            }
        )

    isp_strategy = isp_head_end.get("public_eip_strategy") or "none"
    if isp_strategy == "existing_allocation":
        actions.append(
            {
                "name": "associate_isp_head_end_eip",
                "service_role": "cgnat_isp_head_end",
                "allocation_id": isp_head_end["public_eip_allocation_id"],
                "association_target": "transit_network_interface",
            }
        )
    elif isp_strategy == "allocate_new":
        actions.append(
            {
                "name": "allocate_and_associate_isp_head_end_eip",
                "service_role": "cgnat_isp_head_end",
                "association_target": "transit_network_interface",
            }
        )

    actions.extend(
        [
            {"name": "disable_source_dest_check_head_end", "service_role": "cgnat_head_end"},
            {"name": "disable_source_dest_check_isp_head_end", "service_role": "cgnat_isp_head_end"},
        ]
    )
    return {"actions": actions}


def _build_plan(package: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, Any]:
    manifest = package["manifest"]
    dependencies = package["dependencies"]
    cgnat_head_end = package["cgnat_head_end"]
    cgnat_isp_head_end = package["cgnat_isp_head_end"]
    customer_vpn_routers = list(package.get("customer_vpn_routers") or [])

    blocking = [issue for issue in issues if issue["severity"] in {"error", "blocking_gap"}]
    ec2_requests: dict[str, Any] = {}
    post_create_actions: dict[str, Any] = {"actions": []}
    if not blocking:
        ec2_requests = {
            "cgnat_head_end": _build_head_end_run_instances_request(package),
            "cgnat_isp_head_end": _build_isp_head_end_run_instances_request(package),
            "customer_vpn_routers": _build_customer_vpn_router_run_instances_requests(package),
        }
        post_create_actions = _build_post_create_actions(package)
    return {
        "plan_type": "cgnat_scenario1_aws_deploy_plan",
        "service_id": manifest["service_id"],
        "customer_id": manifest["customer_id"],
        "environment_name": manifest["environment_name"],
        "scenario": manifest["scenario"],
        "deployment_ready_for_live_create": not blocking,
        "aws_context": dependencies["aws"],
        "roles": {
            "cgnat_head_end": cgnat_head_end,
            "cgnat_isp_head_end": cgnat_isp_head_end,
            "customer_vpn_routers": customer_vpn_routers,
        },
        "external_dependencies": {
            "backend_vpn_head_ends": dependencies["backend_vpn_head_ends"],
            "gre_inventory": dependencies["gre_inventory"],
            "certificates": dependencies["certificates"],
        },
        "ec2_requests": ec2_requests,
        "post_create_actions": post_create_actions,
        "steps": package["deployment_order"]["steps"],
        "open_issues": issues,
    }


def _render_readme(plan: dict[str, Any]) -> str:
    status = "READY" if plan["deployment_ready_for_live_create"] else "NOT_READY"
    return "\n".join(
        [
            "# Scenario 1 AWS Deploy Plan",
            "",
            f"- Service ID: `{plan['service_id']}`",
            f"- Environment: `{plan['environment_name']}`",
            f"- Scenario: `{plan['scenario']}`",
            f"- Live create readiness: `{status}`",
            "",
            "## Summary",
            "",
            "- This plan is generated from the AWS package lane.",
            "- It is safe for planning and dry-run review.",
            "- AWS apply mode uses EC2 DryRun by default.",
            "- Real creation requires explicit live execution approval.",
            "",
            "## Outputs",
            "",
            "- `deployment-plan.json`",
            "- `deployment-issues.json`",
            "- `deployment-readiness.json`",
            "- `head-end-run-instances-request.json`",
            "- `isp-head-end-run-instances-request.json`",
            "- `customer-vpn-router-run-instances-requests.json`",
            "- `post-create-actions.json`",
            "",
        ]
    )


def _instance_id(role_result: dict[str, Any]) -> str | None:
    instances = role_result.get("response", {}).get("Instances", [])
    if not instances:
        return None
    return instances[0].get("InstanceId")


def _primary_eni_id(role_result: dict[str, Any]) -> str | None:
    instances = role_result.get("response", {}).get("Instances", [])
    if not instances:
        return None
    return instances[0].get("NetworkInterfaces", [{}])[0].get("NetworkInterfaceId")


def _network_interface_id_by_device_index(role_result: dict[str, Any], device_index: int) -> str | None:
    instances = role_result.get("response", {}).get("Instances", [])
    if not instances:
        return None
    for network_interface in instances[0].get("NetworkInterfaces", []):
        attachment = network_interface.get("Attachment") or {}
        if attachment.get("DeviceIndex") == device_index:
            return network_interface.get("NetworkInterfaceId")
    return None


def _network_interface_ids(role_result: dict[str, Any]) -> list[str]:
    instances = role_result.get("response", {}).get("Instances", [])
    if not instances:
        return []
    network_interfaces = instances[0].get("NetworkInterfaces", [])
    return [eni.get("NetworkInterfaceId") for eni in network_interfaces if eni.get("NetworkInterfaceId")]


def _apply_plan_with_boto3(plan: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    try:
        import boto3  # type: ignore
        from botocore.exceptions import ClientError  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError("boto3 unavailable") from exc

    region = plan["aws_context"]["region"]
    ec2 = boto3.client("ec2", region_name=region)

    result: dict[str, Any] = {
        "mode": "aws_dry_run" if dry_run else "live_apply",
        "head_end": {},
        "isp_head_end": {},
        "customer_vpn_routers": [],
        "post_create_actions": [],
    }

    def _run_instance_request(name: str, request: dict[str, Any]) -> dict[str, Any]:
        try:
            response = ec2.run_instances(DryRun=dry_run, **request)
            return {"status": "created" if not dry_run else "accepted", "response": response}
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if dry_run and error_code == "DryRunOperation":
                return {"status": "dry_run_ok", "response": exc.response}
            raise RuntimeError(f"{name} EC2 run_instances failed: {exc}") from exc

    result["head_end"] = _run_instance_request("cgnat_head_end", plan["ec2_requests"]["cgnat_head_end"])
    result["isp_head_end"] = _run_instance_request("cgnat_isp_head_end", plan["ec2_requests"]["cgnat_isp_head_end"])
    for router in plan["ec2_requests"].get("customer_vpn_routers", []):
        router_result = _run_instance_request(router["role"], router["request"])
        router_result["role"] = router["role"]
        result["customer_vpn_routers"].append(router_result)

    def _record_action(name: str, service_role: str, status: str, response: dict[str, Any]) -> None:
        result["post_create_actions"].append(
            {"name": name, "service_role": service_role, "status": status, "response": response}
        )

    if dry_run:
        for action in plan["post_create_actions"]["actions"]:
            if action["name"].startswith("allocate_and_associate_"):
                try:
                    response = ec2.allocate_address(DryRun=True, Domain="vpc")
                    _record_action(action["name"], action["service_role"], "accepted", response)
                except ClientError as exc:
                    error_code = exc.response.get("Error", {}).get("Code")
                    if error_code == "DryRunOperation":
                        _record_action(action["name"], action["service_role"], "dry_run_ok", exc.response)
                    else:
                        raise RuntimeError(f"{action['name']} allocate_address failed: {exc}") from exc
            elif action["name"].startswith("disable_source_dest_check_"):
                _record_action(
                    action["name"],
                    action["service_role"],
                    "deferred_until_live_create",
                    {"message": "Source/dest check can only be modified after an instance is created."},
                )
        return result

    role_to_eni = {
        "cgnat_head_end": _primary_eni_id(result["head_end"]),
        "cgnat_isp_head_end": _primary_eni_id(result["isp_head_end"]),
    }
    role_to_transit_eni = {
        "cgnat_head_end": _network_interface_id_by_device_index(result["head_end"], 0),
        "cgnat_isp_head_end": _network_interface_id_by_device_index(result["isp_head_end"], 0),
    }
    role_to_enis = {
        "cgnat_head_end": _network_interface_ids(result["head_end"]),
        "cgnat_isp_head_end": _network_interface_ids(result["isp_head_end"]),
    }

    for action in plan["post_create_actions"]["actions"]:
        if action["name"] in {"associate_head_end_eip", "associate_isp_head_end_eip"}:
            role_eni = (
                role_to_transit_eni.get(action["service_role"])
                if action.get("association_target") == "transit_network_interface"
                else role_to_eni.get(action["service_role"])
            )
            if not role_eni:
                continue
            association = ec2.associate_address(
                AllocationId=action["allocation_id"],
                NetworkInterfaceId=role_eni,
                AllowReassociation=False,
            )
            described = ec2.describe_addresses(AllocationIds=[action["allocation_id"]])
            _record_action(action["name"], action["service_role"], "completed", {"association": association, "address": described})
        elif action["name"] in {"allocate_and_associate_head_end_eip", "allocate_and_associate_isp_head_end_eip"}:
            role_eni = (
                role_to_transit_eni.get(action["service_role"])
                if action.get("association_target") == "transit_network_interface"
                else role_to_eni.get(action["service_role"])
            )
            if not role_eni:
                continue
            allocation = ec2.allocate_address(Domain="vpc")
            association = ec2.associate_address(
                AllocationId=allocation["AllocationId"],
                NetworkInterfaceId=role_eni,
                AllowReassociation=False,
            )
            _record_action(action["name"], action["service_role"], "completed", {"allocation": allocation, "association": association})
        elif action["name"] in {"disable_source_dest_check_head_end", "disable_source_dest_check_isp_head_end"}:
            network_interface_ids = role_to_enis.get(action["service_role"]) or []
            if not network_interface_ids:
                continue
            responses: list[dict[str, Any]] = []
            for network_interface_id in network_interface_ids:
                response = ec2.modify_network_interface_attribute(
                    NetworkInterfaceId=network_interface_id,
                    SourceDestCheck={"Value": False},
                )
                responses.append({"network_interface_id": network_interface_id, "response": response})
            _record_action(action["name"], action["service_role"], "completed", {"network_interfaces": responses})

    return result


def _aws_cli_json(
    region: str,
    service_args: list[str],
    *,
    input_payload: dict[str, Any] | None = None,
    dry_run_expected: bool = False,
) -> tuple[str, dict[str, Any]]:
    cmd = ["aws", "--region", region, *service_args, "--output", "json"]
    temp_path: str | None = None
    if input_payload is not None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(input_payload, handle)
            handle.flush()
            temp_path = handle.name
        cmd.extend(["--cli-input-json", f"file://{temp_path}"])

    try:
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if completed.returncode == 0:
        return "ok", json.loads(stdout) if stdout else {}
    if dry_run_expected and "DryRunOperation" in stderr:
        return "dry_run_ok", {"stderr": stderr}
    raise RuntimeError(f"AWS CLI command failed: {' '.join(cmd)}\n{stderr}")


def _apply_plan_with_aws_cli(plan: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    region = plan["aws_context"]["region"]
    result: dict[str, Any] = {
        "mode": "aws_dry_run" if dry_run else "live_apply",
        "engine": "aws_cli",
        "head_end": {},
        "isp_head_end": {},
        "customer_vpn_routers": [],
        "post_create_actions": [],
    }

    def _run_instance_request(name: str, request: dict[str, Any]) -> dict[str, Any]:
        args = ["ec2", "run-instances"]
        if dry_run:
            args.append("--dry-run")
        status, response = _aws_cli_json(region, args, input_payload=request, dry_run_expected=dry_run)
        return {"status": "created" if not dry_run else status, "response": response}

    result["head_end"] = _run_instance_request("cgnat_head_end", plan["ec2_requests"]["cgnat_head_end"])
    result["isp_head_end"] = _run_instance_request("cgnat_isp_head_end", plan["ec2_requests"]["cgnat_isp_head_end"])
    for router in plan["ec2_requests"].get("customer_vpn_routers", []):
        router_result = _run_instance_request(router["role"], router["request"])
        router_result["role"] = router["role"]
        result["customer_vpn_routers"].append(router_result)

    def _record_action(name: str, service_role: str, status: str, response: dict[str, Any]) -> None:
        result["post_create_actions"].append(
            {"name": name, "service_role": service_role, "status": status, "response": response}
        )

    if dry_run:
        for action in plan["post_create_actions"]["actions"]:
            if action["name"].startswith("allocate_and_associate_"):
                status, response = _aws_cli_json(
                    region,
                    ["ec2", "allocate-address", "--domain", "vpc", "--dry-run"],
                    dry_run_expected=True,
                )
                _record_action(action["name"], action["service_role"], status, response)
            elif action["name"].startswith("disable_source_dest_check_"):
                _record_action(
                    action["name"],
                    action["service_role"],
                    "deferred_until_live_create",
                    {"message": "Source/dest check can only be modified after an instance is created."},
                )
        return result

    role_to_eni = {
        "cgnat_head_end": _primary_eni_id(result["head_end"]),
        "cgnat_isp_head_end": _primary_eni_id(result["isp_head_end"]),
    }
    role_to_transit_eni = {
        "cgnat_head_end": _network_interface_id_by_device_index(result["head_end"], 0),
        "cgnat_isp_head_end": _network_interface_id_by_device_index(result["isp_head_end"], 0),
    }
    role_to_enis = {
        "cgnat_head_end": _network_interface_ids(result["head_end"]),
        "cgnat_isp_head_end": _network_interface_ids(result["isp_head_end"]),
    }

    for action in plan["post_create_actions"]["actions"]:
        if action["name"] in {"associate_head_end_eip", "associate_isp_head_end_eip"}:
            role_eni = (
                role_to_transit_eni.get(action["service_role"])
                if action.get("association_target") == "transit_network_interface"
                else role_to_eni.get(action["service_role"])
            )
            if not role_eni:
                continue
            _, association = _aws_cli_json(
                region,
                [
                    "ec2",
                    "associate-address",
                    "--allocation-id",
                    action["allocation_id"],
                    "--network-interface-id",
                    role_eni,
                    "--no-allow-reassociation",
                ],
            )
            _, address = _aws_cli_json(region, ["ec2", "describe-addresses", "--allocation-ids", action["allocation_id"]])
            _record_action(action["name"], action["service_role"], "completed", {"association": association, "address": address})
        elif action["name"] in {"allocate_and_associate_head_end_eip", "allocate_and_associate_isp_head_end_eip"}:
            role_eni = (
                role_to_transit_eni.get(action["service_role"])
                if action.get("association_target") == "transit_network_interface"
                else role_to_eni.get(action["service_role"])
            )
            if not role_eni:
                continue
            _, allocation = _aws_cli_json(region, ["ec2", "allocate-address", "--domain", "vpc"])
            _, association = _aws_cli_json(
                region,
                [
                    "ec2",
                    "associate-address",
                    "--allocation-id",
                    allocation["AllocationId"],
                    "--network-interface-id",
                    role_eni,
                    "--no-allow-reassociation",
                ],
            )
            _record_action(action["name"], action["service_role"], "completed", {"allocation": allocation, "association": association})
        elif action["name"] in {"disable_source_dest_check_head_end", "disable_source_dest_check_isp_head_end"}:
            network_interface_ids = role_to_enis.get(action["service_role"]) or []
            if not network_interface_ids:
                continue
            responses: list[dict[str, Any]] = []
            for network_interface_id in network_interface_ids:
                _, response = _aws_cli_json(
                    region,
                    [
                        "ec2",
                        "modify-network-interface-attribute",
                        "--network-interface-id",
                        network_interface_id,
                        "--source-dest-check",
                        "{\"Value\": false}",
                    ],
                )
                responses.append({"network_interface_id": network_interface_id, "response": response})
            _record_action(action["name"], action["service_role"], "completed", {"network_interfaces": responses})

    return result


def _apply_plan(plan: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    try:
        result = _apply_plan_with_boto3(plan, dry_run)
        result["engine"] = "boto3"
        return result
    except RuntimeError as exc:
        if "boto3 unavailable" not in str(exc):
            raise
    return _apply_plan_with_aws_cli(plan, dry_run)


def main() -> int:
    sys.path.insert(0, str(_framework_src_root()))

    from cgnat.bundle import dump_json, dump_text, ensure_path_within_cgnat

    parser = argparse.ArgumentParser(description="Plan or apply Scenario 1 AWS deployment from a rendered CGNAT AWS package.")
    parser.add_argument("package_dir", help="Path to the rendered AWS package directory.")
    parser.add_argument("output_dir", help="Directory to write plan/apply artifacts.")
    parser.add_argument(
        "--mode",
        choices=("plan", "apply"),
        default="plan",
        help="Execution mode. `apply` performs AWS DryRun by default unless --execute-live is supplied.",
    )
    parser.add_argument(
        "--execute-live",
        action="store_true",
        help="When used with --mode apply, execute real AWS create calls instead of EC2 DryRun.",
    )
    args = parser.parse_args()

    package_dir = Path(args.package_dir).resolve()
    output_dir = ensure_path_within_cgnat(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    package = _load_package(package_dir)
    issues = _detect_issues(package)
    plan = _build_plan(package, issues)

    dump_json(output_dir / "deployment-plan.json", plan)
    dump_json(output_dir / "deployment-issues.json", {"issues": issues})
    if plan["ec2_requests"]:
        dump_json(output_dir / "head-end-run-instances-request.json", plan["ec2_requests"]["cgnat_head_end"])
        dump_json(output_dir / "isp-head-end-run-instances-request.json", plan["ec2_requests"]["cgnat_isp_head_end"])
        dump_json(output_dir / "customer-vpn-router-run-instances-requests.json", plan["ec2_requests"]["customer_vpn_routers"])
        dump_json(output_dir / "post-create-actions.json", plan["post_create_actions"])
    dump_json(
        output_dir / "deployment-readiness.json",
        {
            "mode": args.mode,
            "live_create_allowed": plan["deployment_ready_for_live_create"],
            "blocking_issue_count": len([issue for issue in issues if issue["severity"] in {"error", "blocking_gap"}]),
        },
    )
    dump_text(output_dir / "README.md", _render_readme(plan))

    if args.mode == "apply":
        if not plan["deployment_ready_for_live_create"]:
            print("Apply mode is not allowed: blocking issues remain in the AWS package or deployment plan.", file=sys.stderr)
            return 1
        apply_result = _apply_plan(plan, dry_run=not args.execute_live)
        dump_json(output_dir / "apply-result.json", apply_result)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
