#!/usr/bin/env python
"""Verify fresh head-end bootstrap health for an empty-platform deployment."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGION = "us-east-1"
DEFAULT_PREPARED_DIR = REPO_ROOT / "build" / "empty-platform" / "current-prod-shape-rpdb-empty"
DEFAULT_NAT_PARAMS = DEFAULT_PREPARED_DIR / "parameters.vpn-headend.nat.graviton-efs.us-east-1.json"
DEFAULT_NONNAT_PARAMS = DEFAULT_PREPARED_DIR / "parameters.vpn-headend.non-nat.graviton-efs.us-east-1.json"


def _aws_env() -> Dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("AWS_CLI_FILE_ENCODING", "utf-8")
    return env


def _run_aws(args: List[str]) -> Any:
    completed = subprocess.run(
        ["aws", *args],
        check=True,
        capture_output=True,
        env=_aws_env(),
    )
    stdout = completed.stdout.decode("utf-8", errors="replace").strip()
    return json.loads(stdout or "{}")


def _load_parameter_map(path: Path) -> Dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"expected CloudFormation parameter array in {path}")

    result: Dict[str, str] = {}
    for item in payload:
        key = str(item.get("ParameterKey") or "").strip()
        if key:
            result[key] = str(item.get("ParameterValue") or "").strip()
    return result


def _stack_name_from_params(path: Path, region: str) -> str:
    params = _load_parameter_map(path)
    cluster_name = params.get("ClusterName")
    if not cluster_name:
        raise ValueError(f"ClusterName missing from {path}")
    return f"{cluster_name}-{region}"


def _stack_outputs(region: str, stack_name: str) -> Dict[str, str]:
    payload = _run_aws(
        [
            "cloudformation",
            "describe-stacks",
            "--region",
            region,
            "--stack-name",
            stack_name,
            "--output",
            "json",
        ]
    )
    stack = payload["Stacks"][0]
    outputs = {}
    for item in stack.get("Outputs") or []:
        outputs[str(item["OutputKey"])] = str(item["OutputValue"])
    return outputs


def _instance_status_map(region: str, instance_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    ids = list(instance_ids)
    payload = _run_aws(
        [
            "ec2",
            "describe-instance-status",
            "--region",
            region,
            "--instance-ids",
            *ids,
            "--include-all-instances",
            "--output",
            "json",
        ]
    )
    result: Dict[str, Dict[str, Any]] = {}
    for item in payload.get("InstanceStatuses") or []:
        result[str(item["InstanceId"])] = {
            "instance_state": item.get("InstanceState", {}).get("Name"),
            "instance_status": item.get("InstanceStatus", {}).get("Status"),
            "system_status": item.get("SystemStatus", {}).get("Status"),
            "ebs_status": item.get("AttachedEbsStatus", {}).get("Status"),
            "ec2_ok": (
                item.get("InstanceState", {}).get("Name") == "running"
                and item.get("InstanceStatus", {}).get("Status") == "ok"
                and item.get("SystemStatus", {}).get("Status") == "ok"
            ),
        }
    return result


def _ssm_inventory_map(region: str, instance_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    ids = set(instance_ids)
    payload = _run_aws(
        [
            "ssm",
            "describe-instance-information",
            "--region",
            region,
            "--output",
            "json",
        ]
    )
    result: Dict[str, Dict[str, Any]] = {}
    for item in payload.get("InstanceInformationList") or []:
        instance_id = str(item.get("InstanceId") or "")
        if instance_id not in ids:
            continue
        result[instance_id] = {
            "ping_status": item.get("PingStatus"),
            "association_status": item.get("AssociationStatus"),
            "last_ping": item.get("LastPingDateTime"),
            "agent_version": item.get("AgentVersion"),
            "online": item.get("PingStatus") == "Online",
        }
    return result


def _console_summary(region: str, instance_id: str) -> Dict[str, Any]:
    payload = _run_aws(
        [
            "ec2",
            "get-console-output",
            "--region",
            region,
            "--latest",
            "--instance-id",
            instance_id,
            "--output",
            "json",
        ]
    )
    output = str(payload.get("Output") or "")
    checks = {
        "cloudinit_finished": "Cloud-init v." in output and "finished" in output,
        "strongswan_swanctl_installed": "/opt/strongswan/sbin/swanctl" in output,
        "ha_install_marker": "Installed. Edit /etc/muxingplus-ha/ha.env then run:" in output,
        "conntrack_enabled": "multi-user.target.wants/conntrackd.service" in output,
        "ha_enabled": "multi-user.target.wants/muxingplus-ha.service" in output,
        "failure_marker": any(
            marker in output
            for marker in [
                "Failed to start",
                "Failed to run module scripts-user",
                "Unable to download strongSwan",
                "No such file or directory",
            ]
        ),
    }
    checks["bootstrap_ok"] = (
        checks["cloudinit_finished"]
        and checks["strongswan_swanctl_installed"]
        and checks["ha_install_marker"]
        and checks["conntrack_enabled"]
        and checks["ha_enabled"]
        and not checks["failure_marker"]
    )
    return checks


def _send_ssm_service_probe(region: str, instance_ids: List[str]) -> str:
    commands = [
        "echo HOST=$(hostname)",
        "command -v swanctl >/dev/null 2>&1 && echo SWANCTL_PRESENT=true || echo SWANCTL_PRESENT=false",
        (
            'for s in strongswan conntrackd muxingplus-ha; do '
            'printf "SERVICE:%s:enabled=%s\\n" "$s" "$(systemctl is-enabled \\"$s\\" 2>/dev/null || echo unknown)"; '
            'printf "SERVICE:%s:active=%s\\n" "$s" "$(systemctl is-active \\"$s\\" 2>/dev/null || echo unknown)"; '
            'printf "SERVICE:%s:failed=%s\\n" "$s" "$(systemctl is-failed \\"$s\\" 2>/dev/null || echo unknown)"; '
            "done"
        ),
        'for mp in /Shared /LOG /Application; do findmnt "$mp" >/dev/null 2>&1 && echo "MOUNT:$mp=true" || echo "MOUNT:$mp=false"; done',
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="ascii") as handle:
        json.dump({"commands": commands}, handle)
        temp_path = handle.name
    try:
        payload = _run_aws(
            [
                "ssm",
                "send-command",
                "--region",
                region,
                "--document-name",
                "AWS-RunShellScript",
                "--instance-ids",
                *instance_ids,
                "--comment",
                "rpdb post-bootstrap verification",
                "--parameters",
                f"file://{temp_path}",
                "--output",
                "json",
            ]
        )
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass
    return str(payload["Command"]["CommandId"])


def _poll_ssm_results(region: str, command_id: str, timeout_seconds: int) -> Dict[str, Any]:
    deadline = time.time() + max(timeout_seconds, 0)
    last_payload: Dict[str, Any] = {}
    while True:
        payload = _run_aws(
            [
                "ssm",
                "list-command-invocations",
                "--region",
                region,
                "--command-id",
                command_id,
                "--details",
                "--output",
                "json",
            ]
        )
        last_payload = payload
        invocations = payload.get("CommandInvocations") or []
        if invocations and all(
            item.get("Status") in {"Success", "Cancelled", "Failed", "TimedOut", "DeliveryTimedOut", "Undeliverable", "Terminated"}
            for item in invocations
        ):
            return payload
        if time.time() >= deadline:
            return payload
        time.sleep(10)


def _parse_ssm_plugin_output(output: str) -> Dict[str, Any]:
    services: Dict[str, Dict[str, str]] = {}
    mounts: Dict[str, bool] = {}
    swanctl_present = False
    host = ""
    for line in output.splitlines():
        if line.startswith("HOST="):
            host = line.partition("=")[2].strip()
        elif line.startswith("SWANCTL_PRESENT="):
            swanctl_present = line.partition("=")[2].strip().lower() == "true"
        elif line.startswith("SERVICE:"):
            _, service_name, key_value = line.split(":", 2)
            key, _, value = key_value.partition("=")
            services.setdefault(service_name, {})[key] = value.strip()
        elif line.startswith("MOUNT:"):
            _, mount_point, value = line.partition("=")[0].split(":", 1)[0], line.partition(":")[2].split("=", 1)[0], line.partition("=")[2]
            # Re-parse cleanly for readability.
            name = line.split(":", 1)[1].split("=", 1)[0]
            mounts[name] = line.partition("=")[2].strip().lower() == "true"

    strongswan = services.get("strongswan", {})
    conntrackd = services.get("conntrackd", {})
    muxingplus_ha = services.get("muxingplus-ha", {})

    checks = {
        "host": host,
        "swanctl_present": swanctl_present,
        "strongswan_service_known": strongswan.get("active") not in {None, "unknown"},
        "strongswan_not_failed": strongswan.get("failed") not in {"failed", "unknown"},
        "conntrackd_active": conntrackd.get("active") == "active",
        "muxingplus_ha_active": muxingplus_ha.get("active") == "active",
        "shared_mounted": mounts.get("/Shared", False),
        "log_mounted": mounts.get("/LOG", False),
        "application_mounted": mounts.get("/Application", False),
    }
    checks["service_probe_ok"] = all(checks.values())
    return {
        "services": services,
        "mounts": mounts,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify post-bootstrap health for empty-platform head ends.")
    parser.add_argument("--region", default=DEFAULT_REGION, help="AWS region")
    parser.add_argument("--nat-stack-name", help="NAT head-end stack name")
    parser.add_argument("--nonnat-stack-name", help="Non-NAT head-end stack name")
    parser.add_argument("--nat-params", default=str(DEFAULT_NAT_PARAMS), help="Prepared NAT parameter file used to infer the stack name")
    parser.add_argument(
        "--nonnat-params",
        default=str(DEFAULT_NONNAT_PARAMS),
        help="Prepared non-NAT parameter file used to infer the stack name",
    )
    parser.add_argument(
        "--ssm-timeout-seconds",
        type=int,
        default=180,
        help="How long to wait for the SSM service probe to complete",
    )
    parser.add_argument("--json", action="store_true", help="Emit the full verification document as JSON")
    args = parser.parse_args()

    nat_stack_name = args.nat_stack_name or _stack_name_from_params(Path(args.nat_params), args.region)
    nonnat_stack_name = args.nonnat_stack_name or _stack_name_from_params(Path(args.nonnat_params), args.region)

    stack_definitions = [
        ("nat", nat_stack_name),
        ("nonnat", nonnat_stack_name),
    ]

    nodes: List[Dict[str, Any]] = []
    for cluster_kind, stack_name in stack_definitions:
        outputs = _stack_outputs(args.region, stack_name)
        nodes.append(
            {
                "cluster_kind": cluster_kind,
                "cluster_name": outputs.get("ClusterName"),
                "node_name": "a",
                "instance_id": outputs["HeadendAInstanceId"],
            }
        )
        nodes.append(
            {
                "cluster_kind": cluster_kind,
                "cluster_name": outputs.get("ClusterName"),
                "node_name": "b",
                "instance_id": outputs["HeadendBInstanceId"],
            }
        )

    instance_ids = [node["instance_id"] for node in nodes]
    instance_status = _instance_status_map(args.region, instance_ids)
    ssm_inventory = _ssm_inventory_map(args.region, instance_ids)

    for node in nodes:
        node["ec2"] = instance_status.get(node["instance_id"], {})
        node["console"] = _console_summary(args.region, node["instance_id"])
        node["ssm"] = ssm_inventory.get(node["instance_id"], {"online": False})

    online_ids = [node["instance_id"] for node in nodes if node["ssm"].get("online")]
    service_results: Dict[str, Dict[str, Any]] = {}
    service_probe_status = {
        "sent": False,
        "command_id": "",
        "timed_out": False,
    }

    if online_ids:
        service_probe_status["sent"] = True
        command_id = _send_ssm_service_probe(args.region, online_ids)
        service_probe_status["command_id"] = command_id
        payload = _poll_ssm_results(args.region, command_id, args.ssm_timeout_seconds)
        invocations = payload.get("CommandInvocations") or []
        terminal_statuses = {"Success", "Cancelled", "Failed", "TimedOut", "DeliveryTimedOut", "Undeliverable", "Terminated"}
        service_probe_status["timed_out"] = any(item.get("Status") not in terminal_statuses for item in invocations)
        for item in invocations:
            instance_id = str(item["InstanceId"])
            plugin = (item.get("CommandPlugins") or [{}])[0]
            service_results[instance_id] = {
                "status": item.get("Status"),
                "status_details": item.get("StatusDetails"),
                "response_code": plugin.get("ResponseCode"),
                "parsed": _parse_ssm_plugin_output(str(plugin.get("Output") or "")) if plugin.get("Output") else {},
            }

    overall_ok = True
    for node in nodes:
        node["service_probe"] = service_results.get(node["instance_id"], {})
        checks = {
            "ec2_ok": bool(node["ec2"].get("ec2_ok")),
            "bootstrap_ok": bool(node["console"].get("bootstrap_ok")),
            "ssm_online": bool(node["ssm"].get("online")),
        }
        if node["ssm"].get("online"):
            checks["service_probe_ok"] = bool(
                node["service_probe"].get("parsed", {}).get("checks", {}).get("service_probe_ok")
            )
        else:
            checks["service_probe_ok"] = False
        node["checks"] = checks
        node["healthy"] = all(checks.values())
        overall_ok = overall_ok and node["healthy"]

    summary = {
        "region": args.region,
        "nat_stack_name": nat_stack_name,
        "nonnat_stack_name": nonnat_stack_name,
        "service_probe": service_probe_status,
        "overall_ok": overall_ok,
        "nodes": nodes,
    }

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(f"Overall healthy: {overall_ok}")
        for node in nodes:
            print(
                f"{node['cluster_kind']}:{node['node_name']} {node['instance_id']} "
                f"ec2_ok={node['checks']['ec2_ok']} "
                f"bootstrap_ok={node['checks']['bootstrap_ok']} "
                f"ssm_online={node['checks']['ssm_online']} "
                f"service_probe_ok={node['checks']['service_probe_ok']}"
            )

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
