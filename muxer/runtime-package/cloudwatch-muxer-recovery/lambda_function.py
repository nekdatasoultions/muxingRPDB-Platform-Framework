import json
import logging
import os
import time
from typing import Dict, List, Tuple

import boto3

LOG = logging.getLogger()
LOG.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

autoscaling = boto3.client("autoscaling")
ec2 = boto3.client("ec2")
ssm = boto3.client("ssm")

ASG_NAME = os.environ["ASG_NAME"]
EIP_ALLOCATION_ID = os.environ["EIP_ALLOCATION_ID"]
TRANSPORT_ENI_A = os.environ["TRANSPORT_ENI_A"]
TRANSPORT_ENI_B = os.environ["TRANSPORT_ENI_B"]
CUSTOMER_SOT_TABLE = os.environ["CUSTOMER_SOT_TABLE"]
TRANSPORT_DEVICE_INDEX = int(os.getenv("TRANSPORT_DEVICE_INDEX", "1"))
MUXER_SERVICE_NAME = os.getenv("MUXER_SERVICE_NAME", "muxer.service")
SSM_TIMEOUT_SEC = int(os.getenv("SSM_TIMEOUT_SEC", "180"))
ALLOW_EIP_REASSOCIATION = os.getenv("ALLOW_EIP_REASSOCIATION", "false").strip().lower() == "true"


def _describe_asg() -> dict:
    resp = autoscaling.describe_auto_scaling_groups(AutoScalingGroupNames=[ASG_NAME])
    groups = resp.get("AutoScalingGroups", [])
    if not groups:
        raise RuntimeError(f"Auto Scaling Group not found: {ASG_NAME}")
    return groups[0]


def _describe_instances(instance_ids: List[str]) -> Dict[str, dict]:
    if not instance_ids:
        return {}
    resp = ec2.describe_instances(InstanceIds=instance_ids)
    out: Dict[str, dict] = {}
    for reservation in resp.get("Reservations", []):
        for instance in reservation.get("Instances", []):
            out[instance["InstanceId"]] = instance
    return out


def _describe_enis(eni_ids: List[str]) -> Dict[str, dict]:
    resp = ec2.describe_network_interfaces(NetworkInterfaceIds=eni_ids)
    return {eni["NetworkInterfaceId"]: eni for eni in resp.get("NetworkInterfaces", [])}


def _candidate_score(asg_item: dict, instance: dict) -> Tuple[int, float]:
    lifecycle = asg_item.get("LifecycleState", "")
    health = asg_item.get("HealthStatus", "")
    state = instance.get("State", {}).get("Name", "")
    launch_time = instance.get("LaunchTime")
    ts = launch_time.timestamp() if launch_time else 0.0

    score = 0
    if lifecycle == "InService":
        score += 100
    elif lifecycle == "Pending":
        score += 50
    if health == "Healthy":
        score += 20
    if state == "running":
        score += 10
    return score, ts


def _select_candidate(asg_group: dict, instances: Dict[str, dict]) -> dict:
    candidates = []
    for item in asg_group.get("Instances", []):
        instance_id = item["InstanceId"]
        instance = instances.get(instance_id)
        if not instance:
            continue
        score, ts = _candidate_score(item, instance)
        candidates.append((score, ts, item, instance))
    if not candidates:
        raise RuntimeError(f"No instances found for ASG {ASG_NAME}")
    candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return {"asg": candidates[0][2], "instance": candidates[0][3]}


def _primary_network_interface(instance: dict) -> dict:
    for eni in instance.get("NetworkInterfaces", []):
        if eni.get("Attachment", {}).get("DeviceIndex") == 0:
            return eni
    raise RuntimeError(f"No primary ENI found on {instance['InstanceId']}")


def _secondary_network_interface(instance: dict) -> dict | None:
    for eni in instance.get("NetworkInterfaces", []):
        if eni.get("Attachment", {}).get("DeviceIndex") == TRANSPORT_DEVICE_INDEX:
            return eni
    return None


def _ssm_managed(instance_id: str) -> bool:
    resp = ssm.describe_instance_information(
        Filters=[{"Key": "InstanceIds", "Values": [instance_id]}]
    )
    return bool(resp.get("InstanceInformationList"))


def _run_ssm(instance_id: str, commands: List[str]) -> dict:
    if not _ssm_managed(instance_id):
        return {"status": "PendingSsm", "stdout": "", "stderr": "instance not yet managed by SSM"}

    resp = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": commands},
    )
    command_id = resp["Command"]["CommandId"]
    deadline = time.time() + SSM_TIMEOUT_SEC

    while time.time() < deadline:
        try:
            inv = ssm.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
        except ssm.exceptions.InvocationDoesNotExist:
            time.sleep(2)
            continue
        status = inv.get("Status", "Unknown")
        if status in {
            "Success",
            "Cancelled",
            "Failed",
            "TimedOut",
            "Undeliverable",
            "Terminated",
            "InvalidPlatform",
            "AccessDenied",
        }:
            return {
                "status": status,
                "stdout": inv.get("StandardOutputContent", ""),
                "stderr": inv.get("StandardErrorContent", ""),
            }
        time.sleep(3)

    return {"status": "TimedOut", "stdout": "", "stderr": "SSM command timed out"}


def _ensure_transport_eni(instance: dict, transport_enis: Dict[str, dict]) -> dict:
    instance_id = instance["InstanceId"]
    az = instance["Placement"]["AvailabilityZone"]
    target_eni = None
    for eni in transport_enis.values():
        if eni.get("AvailabilityZone") == az:
            target_eni = eni
            break
    if not target_eni:
        raise RuntimeError(f"No transport ENI mapped for AZ {az}")

    target_eni_id = target_eni["NetworkInterfaceId"]
    current_secondary = _secondary_network_interface(instance)
    if current_secondary and current_secondary["NetworkInterfaceId"] == target_eni_id:
        return {"action": "noop", "transport_eni": target_eni_id}

    if target_eni.get("Attachment"):
        attached_instance = target_eni["Attachment"].get("InstanceId", "")
        if attached_instance and attached_instance != instance_id:
            raise RuntimeError(
                f"Transport ENI {target_eni_id} is attached to {attached_instance}, expected {instance_id}"
            )

    attachment = ec2.attach_network_interface(
        NetworkInterfaceId=target_eni_id,
        InstanceId=instance_id,
        DeviceIndex=TRANSPORT_DEVICE_INDEX,
    )
    attachment_id = attachment["AttachmentId"]
    ec2.modify_network_interface_attribute(
        NetworkInterfaceId=target_eni_id,
        Attachment={"AttachmentId": attachment_id, "DeleteOnTermination": False},
    )
    return {"action": "attached", "transport_eni": target_eni_id, "attachment_id": attachment_id}


def _ensure_eip(instance: dict) -> dict:
    primary_eni = _primary_network_interface(instance)
    primary_eni_id = primary_eni["NetworkInterfaceId"]
    if not EIP_ALLOCATION_ID.strip():
        return {
            "action": "skipped",
            "reason": "EIP_ALLOCATION_ID is empty",
            "target_network_interface_id": primary_eni_id,
        }

    describe = ec2.describe_addresses(AllocationIds=[EIP_ALLOCATION_ID])
    addr = describe["Addresses"][0]
    current_eni = addr.get("NetworkInterfaceId", "")
    if current_eni == primary_eni_id:
        return {"action": "noop", "network_interface_id": primary_eni_id}

    if not ALLOW_EIP_REASSOCIATION:
        return {
            "action": "skipped",
            "reason": "ALLOW_EIP_REASSOCIATION=false",
            "current_network_interface_id": current_eni,
            "target_network_interface_id": primary_eni_id,
        }

    ec2.associate_address(
        AllocationId=EIP_ALLOCATION_ID,
        NetworkInterfaceId=primary_eni_id,
        AllowReassociation=True,
    )
    return {"action": "associated", "network_interface_id": primary_eni_id}


def _configure_muxer(instance: dict, transport_eni_id: str) -> dict:
    instance_id = instance["InstanceId"]
    primary_eni = _primary_network_interface(instance)
    primary_mac = primary_eni["MacAddress"].lower()
    primary_ip = primary_eni["PrivateIpAddress"]
    transport_eni = None
    for eni in instance.get("NetworkInterfaces", []):
        if eni["NetworkInterfaceId"] == transport_eni_id:
            transport_eni = eni
            break
    if not transport_eni:
        refreshed = _describe_instances([instance_id])[instance_id]
        for eni in refreshed.get("NetworkInterfaces", []):
            if eni["NetworkInterfaceId"] == transport_eni_id:
                transport_eni = eni
                break
    if not transport_eni:
        raise RuntimeError(f"Transport ENI {transport_eni_id} not present on {instance_id}")

    transport_mac = transport_eni["MacAddress"].lower()
    transport_ip = transport_eni["PrivateIpAddress"]
    commands = [
        "set -euo pipefail",
        f"export PRIMARY_MAC='{primary_mac}'",
        f"export PRIMARY_IP='{primary_ip}'",
        f"export TRANSPORT_MAC='{transport_mac}'",
        f"export TRANSPORT_IP='{transport_ip}'",
        f"export TRANSPORT_LOCAL_MODE='{'module_inside_ip' if ALLOW_EIP_REASSOCIATION else 'interface_ip'}'",
        f"export CUSTOMER_SOT_TABLE='{CUSTOMER_SOT_TABLE}'",
        f"export AWS_REGION='{os.environ.get('AWS_REGION', os.environ.get('AWS_DEFAULT_REGION', 'us-east-1'))}'",
        "iface_for_mac() { local target=\"$1\"; for path in /sys/class/net/*/address; do current=$(cat \"$path\"); if [[ \"$current\" == \"$target\" ]]; then basename \"$(dirname \"$path\")\"; return 0; fi; done; return 1; }",
        "export PUB_IF=$(iface_for_mac \"$PRIMARY_MAC\")",
        "export INSIDE_IF=$(iface_for_mac \"$TRANSPORT_MAC\")",
        "python3 - <<'PY'\n"
        "import os\n"
        "from pathlib import Path\n"
        "import yaml\n"
        "path = Path('/etc/muxer/config/muxer.yaml')\n"
        "doc = yaml.safe_load(path.read_text(encoding='utf-8')) or {}\n"
        "ifs = doc.setdefault('interfaces', {})\n"
        "ifs['public_if'] = os.environ['PUB_IF']\n"
        "ifs['public_private_ip'] = os.environ['PRIMARY_IP']\n"
        "ifs['inside_if'] = os.environ['INSIDE_IF']\n"
        "ifs['inside_ip'] = os.environ['TRANSPORT_IP']\n"
        "sot = doc.setdefault('customer_sot', {})\n"
        "sot['backend'] = 'dynamodb'\n"
        "sot['sync_from_variables_on_render'] = False\n"
        "ddb = sot.setdefault('dynamodb', {})\n"
        "ddb['region'] = os.environ['AWS_REGION']\n"
        "ddb['table_name'] = os.environ['CUSTOMER_SOT_TABLE']\n"
        "transport = doc.setdefault('transport_identity', {})\n"
        "transport['local_underlay_mode'] = os.environ['TRANSPORT_LOCAL_MODE']\n"
        "path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding='utf-8')\n"
        "PY",
        f"systemctl enable {MUXER_SERVICE_NAME} || true",
        f"systemctl restart {MUXER_SERVICE_NAME}",
        f"systemctl status {MUXER_SERVICE_NAME} --no-pager || true",
    ]
    return _run_ssm(instance_id, commands)


def lambda_handler(event, context):
    LOG.info("event=%s", json.dumps(event))
    asg_group = _describe_asg()
    instance_ids = [item["InstanceId"] for item in asg_group.get("Instances", [])]
    instances = _describe_instances(instance_ids)
    transport_enis = _describe_enis([TRANSPORT_ENI_A, TRANSPORT_ENI_B])

    candidate = _select_candidate(asg_group, instances)
    instance = candidate["instance"]
    instance_id = instance["InstanceId"]

    transport_result = _ensure_transport_eni(instance, transport_enis)
    refreshed = _describe_instances([instance_id])[instance_id]
    eip_result = _ensure_eip(refreshed)
    configured = _configure_muxer(refreshed, transport_result["transport_eni"])

    result = {
        "asg_name": ASG_NAME,
        "instance_id": instance_id,
        "availability_zone": refreshed["Placement"]["AvailabilityZone"],
        "transport": transport_result,
        "eip": eip_result,
        "ssm": configured,
    }
    LOG.info("result=%s", json.dumps(result))
    return result
