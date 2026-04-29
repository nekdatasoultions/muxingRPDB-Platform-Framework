from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _framework_src_root() -> Path:
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent.parent / "framework" / "src"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_package(package_dir: Path) -> dict[str, Any]:
    return {
        "manifest": _load_json(package_dir / "package-manifest.json"),
        "cgnat_head_end": _load_json(package_dir / "cgnat-head-end.json"),
        "cgnat_isp_head_end": _load_json(package_dir / "cgnat-isp-head-end.json"),
        "dependencies": _load_json(package_dir / "dependencies.json"),
        "deployment_order": _load_json(package_dir / "deployment-order.json"),
    }


def _detect_issues(package: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    manifest = package["manifest"]
    dependencies = package["dependencies"]
    cgnat_head_end = package["cgnat_head_end"]
    cgnat_isp_head_end = package["cgnat_isp_head_end"]

    if manifest.get("scenario") != "scenario1":
        issues.append(
            {
                "code": "unsupported_scenario",
                "severity": "error",
                "message": "This deploy script currently supports Scenario 1 only.",
            }
        )

    aws_section = dependencies.get("aws") or {}
    if not aws_section.get("region") or not aws_section.get("vpc_id"):
        issues.append(
            {
                "code": "missing_aws_context",
                "severity": "error",
                "message": "AWS region and VPC ID are required for deployment planning.",
            }
        )

    default_tags = dependencies.get("default_tags")
    if not isinstance(default_tags, dict) or not default_tags:
        issues.append(
            {
                "code": "missing_default_tags",
                "severity": "blocking_gap",
                "message": "Default AWS tags are required for live EC2 creation.",
            }
        )

    if not cgnat_head_end.get("public_eip_allocation_id"):
        issues.append(
            {
                "code": "missing_head_end_eip",
                "severity": "error",
                "message": "CGNAT HEAD END public EIP allocation is required.",
            }
        )

    if not dependencies.get("certificates", {}).get("cgnat_head_end_server_cert_ref"):
        issues.append(
            {
                "code": "missing_head_end_cert_ref",
                "severity": "error",
                "message": "CGNAT HEAD END server certificate reference is required.",
            }
        )

    if not dependencies.get("certificates", {}).get("cgnat_isp_head_end_client_cert_ref"):
        issues.append(
            {
                "code": "missing_isp_cert_ref",
                "severity": "error",
                "message": "CGNAT ISP HEAD END client certificate reference is required.",
            }
        )

    if not dependencies.get("gre_inventory", {}).get("inventory_ref"):
        issues.append(
            {
                "code": "missing_gre_inventory",
                "severity": "error",
                "message": "GRE inventory reference is required.",
            }
        )

    head_launch_checks = {
        "ami_id": cgnat_head_end.get("ami_id"),
        "security_group_ids": cgnat_head_end.get("security_group_ids"),
        "iam_instance_profile": cgnat_head_end.get("iam_instance_profile"),
    }
    for field_name, field_value in head_launch_checks.items():
        if not field_value:
            issues.append(
                {
                    "code": f"missing_head_end_launch_field_{field_name}",
                    "severity": "blocking_gap",
                    "message": f"CGNAT HEAD END package is missing `{field_name}` for live EC2 creation.",
                }
            )

    head_root = cgnat_head_end.get("root_volume") or {}
    for field_name in ("device_name", "size_gb", "volume_type", "delete_on_termination"):
        if field_name not in head_root or head_root.get(field_name) in (None, ""):
            issues.append(
                {
                    "code": f"missing_head_end_root_volume_field_{field_name}",
                    "severity": "blocking_gap",
                    "message": f"CGNAT HEAD END package is missing root_volume.`{field_name}` for live EC2 creation.",
                }
            )
    if not cgnat_head_end.get("subnet_id"):
        issues.append(
            {
                "code": "missing_head_end_subnet_id",
                "severity": "blocking_gap",
                "message": "CGNAT HEAD END package is missing `subnet_id` for live EC2 creation.",
            }
        )

    isp_launch_checks = {
        "ami_id": cgnat_isp_head_end.get("ami_id"),
        "security_group_ids": cgnat_isp_head_end.get("security_group_ids"),
        "iam_instance_profile": cgnat_isp_head_end.get("iam_instance_profile"),
    }
    for field_name, field_value in isp_launch_checks.items():
        if not field_value:
            issues.append(
                {
                    "code": f"missing_isp_head_end_launch_field_{field_name}",
                    "severity": "blocking_gap",
                    "message": f"CGNAT ISP HEAD END package is missing `{field_name}` for live EC2 creation.",
                }
            )

    isp_root = cgnat_isp_head_end.get("root_volume") or {}
    for field_name in ("device_name", "size_gb", "volume_type", "delete_on_termination"):
        if field_name not in isp_root or isp_root.get(field_name) in (None, ""):
            issues.append(
                {
                    "code": f"missing_isp_head_end_root_volume_field_{field_name}",
                    "severity": "blocking_gap",
                    "message": f"CGNAT ISP HEAD END package is missing root_volume.`{field_name}` for live EC2 creation.",
                }
            )
    isp_subnets = cgnat_isp_head_end.get("subnets") or {}
    for field_name in ("transit_subnet_id", "customer_subnet_id"):
        if not isp_subnets.get(field_name):
            issues.append(
                {
                    "code": f"missing_isp_head_end_subnet_field_{field_name}",
                    "severity": "blocking_gap",
                    "message": f"CGNAT ISP HEAD END package is missing subnets.`{field_name}` for live EC2 creation.",
                }
            )

    if cgnat_head_end.get("placement_rule") != "must_run_only_in_subnet-04a6b7f3a3855d438":
        issues.append(
            {
                "code": "unexpected_head_end_placement_rule",
                "severity": "error",
                "message": "CGNAT HEAD END placement rule does not match Scenario 1 expectations.",
            }
        )

    if cgnat_isp_head_end.get("placement_rule") != "must_span_transit_and_customer_subnets":
        issues.append(
            {
                "code": "unexpected_isp_placement_rule",
                "severity": "error",
                "message": "CGNAT ISP HEAD END placement rule does not match Scenario 1 expectations.",
            }
        )

    return issues


def _build_head_end_run_instances_request(package: dict[str, Any]) -> dict[str, Any]:
    manifest = package["manifest"]
    head_end = package["cgnat_head_end"]
    dependencies = package["dependencies"]
    tags = dict(dependencies["default_tags"])
    tags.update(
        {
            "Name": head_end["instance_name"],
            "ServiceId": manifest["service_id"],
            "CustomerId": manifest["customer_id"],
            "Role": "cgnat_head_end",
        }
    )
    request = {
        "ImageId": head_end["ami_id"],
        "InstanceType": head_end["instance_type"],
        "MinCount": 1,
        "MaxCount": 1,
        "IamInstanceProfile": {
            "Name": head_end["iam_instance_profile"],
        },
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
        "TagSpecifications": [
            {
                "ResourceType": "instance",
                "Tags": [{"Key": key, "Value": str(value)} for key, value in tags.items()],
            }
        ],
    }
    if head_end.get("key_pair_name"):
        request["KeyName"] = head_end["key_pair_name"]
    return request


def _build_isp_head_end_run_instances_request(package: dict[str, Any]) -> dict[str, Any]:
    manifest = package["manifest"]
    isp_head_end = package["cgnat_isp_head_end"]
    dependencies = package["dependencies"]
    tags = dict(dependencies["default_tags"])
    tags.update(
        {
            "Name": isp_head_end["instance_name"],
            "ServiceId": manifest["service_id"],
            "CustomerId": manifest["customer_id"],
            "Role": "cgnat_isp_head_end",
        }
    )
    request = {
        "ImageId": isp_head_end["ami_id"],
        "InstanceType": isp_head_end["instance_type"],
        "MinCount": 1,
        "MaxCount": 1,
        "IamInstanceProfile": {
            "Name": isp_head_end["iam_instance_profile"],
        },
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
                "Groups": isp_head_end["security_group_ids"],
                "DeleteOnTermination": True,
            },
        ],
        "TagSpecifications": [
            {
                "ResourceType": "instance",
                "Tags": [{"Key": key, "Value": str(value)} for key, value in tags.items()],
            }
        ],
    }
    if isp_head_end.get("key_pair_name"):
        request["KeyName"] = isp_head_end["key_pair_name"]
    return request


def _build_post_create_actions(package: dict[str, Any]) -> dict[str, Any]:
    head_end = package["cgnat_head_end"]
    return {
        "actions": [
            {
                "name": "associate_head_end_eip",
                "service_role": "cgnat_head_end",
                "allocation_id": head_end["public_eip_allocation_id"],
                "association_target": "primary_network_interface",
            }
        ]
    }


def _build_plan(package: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, Any]:
    manifest = package["manifest"]
    dependencies = package["dependencies"]
    cgnat_head_end = package["cgnat_head_end"]
    cgnat_isp_head_end = package["cgnat_isp_head_end"]

    blocking = [issue for issue in issues if issue["severity"] in {"error", "blocking_gap"}]
    ec2_requests: dict[str, Any] = {}
    post_create_actions: dict[str, Any] = {"actions": []}
    if not blocking:
        ec2_requests = {
            "cgnat_head_end": _build_head_end_run_instances_request(package),
            "cgnat_isp_head_end": _build_isp_head_end_run_instances_request(package),
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
            "- `post-create-actions.json`",
            "",
        ]
    )


def _apply_plan(plan: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    try:
        import boto3  # type: ignore
        from botocore.exceptions import ClientError  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError("boto3 and botocore are required for apply mode.") from exc

    region = plan["aws_context"]["region"]
    ec2 = boto3.client("ec2", region_name=region)

    result: dict[str, Any] = {
        "mode": "aws_dry_run" if dry_run else "live_apply",
        "head_end": {},
        "isp_head_end": {},
        "post_create_actions": [],
    }

    def _run_instance_request(name: str, request: dict[str, Any]) -> dict[str, Any]:
        try:
            response = ec2.run_instances(DryRun=dry_run, **request)
            return {
                "status": "created" if not dry_run else "accepted",
                "response": response,
            }
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if dry_run and error_code == "DryRunOperation":
                return {
                    "status": "dry_run_ok",
                    "response": exc.response,
                }
            raise RuntimeError(f"{name} EC2 run_instances failed: {exc}") from exc

    result["head_end"] = _run_instance_request("cgnat_head_end", plan["ec2_requests"]["cgnat_head_end"])
    result["isp_head_end"] = _run_instance_request("cgnat_isp_head_end", plan["ec2_requests"]["cgnat_isp_head_end"])

    if not dry_run:
        head_instances = result["head_end"].get("response", {}).get("Instances", [])
        if head_instances:
            primary_eni_id = head_instances[0].get("NetworkInterfaces", [{}])[0].get("NetworkInterfaceId")
            if primary_eni_id:
                for action in plan["post_create_actions"]["actions"]:
                    if action["name"] == "associate_head_end_eip":
                        association = ec2.associate_address(
                            AllocationId=action["allocation_id"],
                            NetworkInterfaceId=primary_eni_id,
                            AllowReassociation=False,
                        )
                        result["post_create_actions"].append(
                            {
                                "name": action["name"],
                                "status": "completed",
                                "response": association,
                            }
                        )

    return result


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
