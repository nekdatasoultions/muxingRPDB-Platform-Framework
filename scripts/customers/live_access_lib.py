"""AWS EC2 Instance Connect and SSH helpers for live RPDB apply flows."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def aws_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("AWS_CLI_FILE_ENCODING", "utf-8")
    return env


def run_local(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        text=True,
        capture_output=True,
        check=False,
        cwd=str(cwd) if cwd else None,
        timeout=timeout,
        env=aws_env(),
    )


def run_aws_json(args: list[str]) -> dict[str, Any]:
    completed = run_local(["aws", *args])
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip() or "AWS CLI command failed")
    return json.loads(completed.stdout.strip() or "{}")


def _restrict_private_key(path: Path) -> None:
    if os.name == "nt":
        identity = run_local(["whoami"]).stdout.strip()
        if not identity:
            raise RuntimeError("unable to determine current Windows identity for private-key ACL")
        completed = run_local(["icacls", str(path), "/inheritance:r", "/grant:r", f"{identity}:F"])
        if completed.returncode != 0:
            raise RuntimeError(f"failed to restrict private-key ACL: {completed.stderr.strip()}")
        return
    path.chmod(0o600)


def _generate_eic_key(key_dir: Path) -> dict[str, str]:
    key_name = "rpdb-live-apply"
    private_key = key_dir / key_name
    public_key = key_dir / f"{key_name}.pub"
    completed = run_local(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", key_name, "-C", "rpdb-live-apply"],
        cwd=key_dir,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"ssh-keygen failed: {completed.stderr.strip()}")
    _restrict_private_key(private_key)
    return {
        "key_name": key_name,
        "private_key": str(private_key),
        "public_key": public_key.read_text(encoding="ascii").strip(),
    }


def _send_eic_key(region: str, instance_id: str, availability_zone: str, ssh_user: str, public_key: str) -> None:
    run_aws_json(
        [
            "ec2-instance-connect",
            "send-ssh-public-key",
            "--region",
            region,
            "--instance-id",
            instance_id,
            "--availability-zone",
            availability_zone,
            "--instance-os-user",
            ssh_user,
            "--ssh-public-key",
            public_key,
            "--output",
            "json",
        ]
    )


def instance_details_map(region: str, instance_ids: list[str]) -> dict[str, dict[str, Any]]:
    payload = run_aws_json(
        [
            "ec2",
            "describe-instances",
            "--region",
            region,
            "--instance-ids",
            *instance_ids,
            "--output",
            "json",
        ]
    )
    result: dict[str, dict[str, Any]] = {}
    for reservation in payload.get("Reservations") or []:
        for item in reservation.get("Instances") or []:
            result[str(item["InstanceId"])] = {
                "instance_id": str(item["InstanceId"]),
                "availability_zone": item.get("Placement", {}).get("AvailabilityZone"),
                "private_ip": item.get("PrivateIpAddress"),
                "public_ip": item.get("PublicIpAddress"),
                "state": item.get("State", {}).get("Name"),
            }
    return result


def ensure_ssh_tools() -> None:
    missing = [name for name in ("ssh", "scp", "ssh-keygen") if shutil.which(name) is None]
    if missing:
        raise RuntimeError("required SSH tooling is not available: " + ", ".join(missing))


@dataclass(frozen=True)
class SshAccessContext:
    region: str
    ssh_user: str
    bastion_instance_id: str
    key_dir: Path
    key_name: str
    public_key: str
    details: dict[str, dict[str, Any]]
    known_hosts: str


def build_ssh_access_context(
    *,
    region: str,
    ssh_user: str,
    bastion_instance_id: str,
    target_instance_ids: list[str],
) -> SshAccessContext:
    ensure_ssh_tools()
    details = instance_details_map(region, [bastion_instance_id, *target_instance_ids])
    if bastion_instance_id not in details:
        raise RuntimeError(f"bastion instance details not found: {bastion_instance_id}")
    missing = [instance_id for instance_id in target_instance_ids if instance_id not in details]
    if missing:
        raise RuntimeError("target instance details not found: " + ", ".join(missing))

    key_dir = Path(tempfile.mkdtemp(prefix="rpdb-live-ssh-"))
    key = _generate_eic_key(key_dir)
    return SshAccessContext(
        region=region,
        ssh_user=ssh_user,
        bastion_instance_id=bastion_instance_id,
        key_dir=key_dir,
        key_name=key["key_name"],
        public_key=key["public_key"],
        details=details,
        known_hosts="NUL" if os.name == "nt" else "/dev/null",
    )


def cleanup_ssh_access_context(context: SshAccessContext) -> None:
    shutil.rmtree(context.key_dir, ignore_errors=True)


def _proxy_command(context: SshAccessContext) -> str:
    bastion = context.details.get(context.bastion_instance_id) or {}
    bastion_public_ip = str(bastion.get("public_ip") or "").strip()
    if not bastion_public_ip:
        raise RuntimeError(f"bastion {context.bastion_instance_id} is missing a public IP")
    return (
        f"ssh -i {context.key_name} -o BatchMode=yes -o StrictHostKeyChecking=no "
        f"-o UserKnownHostsFile={context.known_hosts} -o ConnectTimeout=8 "
        f"-W %h:%p {context.ssh_user}@{bastion_public_ip}"
    )


def _target_host(context: SshAccessContext, target_instance_id: str, *, via_bastion: bool) -> str:
    target = context.details.get(target_instance_id) or {}
    host_key = "private_ip" if via_bastion else "public_ip"
    host = str(target.get(host_key) or "").strip()
    if not host:
        raise RuntimeError(f"target {target_instance_id} is missing {host_key}")
    return host


def _prime_eic_keys(context: SshAccessContext, target_instance_id: str, *, via_bastion: bool) -> None:
    target = context.details.get(target_instance_id) or {}
    target_az = str(target.get("availability_zone") or "").strip()
    if not target_az:
        raise RuntimeError(f"target {target_instance_id} is missing availability zone")
    _send_eic_key(context.region, target_instance_id, target_az, context.ssh_user, context.public_key)
    if via_bastion:
        bastion = context.details.get(context.bastion_instance_id) or {}
        bastion_az = str(bastion.get("availability_zone") or "").strip()
        if not bastion_az:
            raise RuntimeError(f"bastion {context.bastion_instance_id} is missing availability zone")
        _send_eic_key(
            context.region,
            context.bastion_instance_id,
            bastion_az,
            context.ssh_user,
            context.public_key,
        )


def run_remote_command(
    *,
    context: SshAccessContext,
    target_instance_id: str,
    remote_command: str,
    via_bastion: bool,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    _prime_eic_keys(context, target_instance_id, via_bastion=via_bastion)
    host = _target_host(context, target_instance_id, via_bastion=via_bastion)
    command = [
        "ssh",
        "-i",
        context.key_name,
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        f"UserKnownHostsFile={context.known_hosts}",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "ServerAliveInterval=5",
        "-o",
        "ServerAliveCountMax=2",
    ]
    if via_bastion:
        command.extend(["-o", f"ProxyCommand={_proxy_command(context)}"])
    command.extend([f"{context.ssh_user}@{host}", remote_command])
    completed = run_local(command, cwd=context.key_dir, timeout=timeout_seconds)
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "success": completed.returncode == 0,
        "transport": "ssh-bastion" if via_bastion else "ssh-direct",
        "target_instance_id": target_instance_id,
    }


def copy_paths_to_remote_root(
    *,
    context: SshAccessContext,
    target_instance_id: str,
    source_root: Path,
    relative_paths: list[Path],
    remote_name: str,
    via_bastion: bool,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    archive_path = context.key_dir / f"{remote_name}.tar"
    with tarfile.open(archive_path, "w") as archive:
        for relative_path in relative_paths:
            source_path = source_root / relative_path
            if not source_path.exists():
                raise RuntimeError(f"local staged path missing before remote copy: {source_path}")
            archive.add(source_path, arcname=relative_path.as_posix(), recursive=True)

    _prime_eic_keys(context, target_instance_id, via_bastion=via_bastion)
    host = _target_host(context, target_instance_id, via_bastion=via_bastion)
    remote_tar = f"/tmp/{remote_name}.tar"
    scp_command = [
        "scp",
        "-i",
        context.key_name,
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        f"UserKnownHostsFile={context.known_hosts}",
        "-o",
        "ConnectTimeout=8",
    ]
    if via_bastion:
        scp_command.extend(["-o", f"ProxyCommand={_proxy_command(context)}"])
    scp_command.extend([str(archive_path), f"{context.ssh_user}@{host}:{remote_tar}"])
    scp_completed = run_local(scp_command, cwd=context.key_dir, timeout=timeout_seconds)
    if scp_completed.returncode != 0:
        return {
            "success": False,
            "transport": "ssh-bastion" if via_bastion else "ssh-direct",
            "target_instance_id": target_instance_id,
            "command": scp_command,
            "stdout": scp_completed.stdout,
            "stderr": scp_completed.stderr,
            "remote_tar": remote_tar,
        }

    extract_result = run_remote_command(
        context=context,
        target_instance_id=target_instance_id,
        via_bastion=via_bastion,
        timeout_seconds=timeout_seconds,
        remote_command=(
            "sudo bash -lc "
            + json.dumps(f"set -eu; tar -xf {remote_tar} -C /; rm -f {remote_tar}")
        ),
    )
    return {
        "success": extract_result["success"],
        "transport": extract_result["transport"],
        "target_instance_id": target_instance_id,
        "copy_command": scp_command,
        "copy_stdout": scp_completed.stdout,
        "copy_stderr": scp_completed.stderr,
        "extract_command": extract_result["command"],
        "extract_stdout": extract_result["stdout"],
        "extract_stderr": extract_result["stderr"],
        "remote_tar": remote_tar,
    }


def copy_remote_file_to_local(
    *,
    context: SshAccessContext,
    target_instance_id: str,
    remote_path: str,
    local_path: Path,
    via_bastion: bool,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    _prime_eic_keys(context, target_instance_id, via_bastion=via_bastion)
    host = _target_host(context, target_instance_id, via_bastion=via_bastion)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    scp_command = [
        "scp",
        "-i",
        context.key_name,
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        f"UserKnownHostsFile={context.known_hosts}",
        "-o",
        "ConnectTimeout=8",
    ]
    if via_bastion:
        scp_command.extend(["-o", f"ProxyCommand={_proxy_command(context)}"])
    scp_command.extend([f"{context.ssh_user}@{host}:{remote_path}", str(local_path)])
    completed = run_local(scp_command, cwd=context.key_dir, timeout=timeout_seconds)
    return {
        "success": completed.returncode == 0,
        "transport": "ssh-bastion" if via_bastion else "ssh-direct",
        "target_instance_id": target_instance_id,
        "command": scp_command,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "remote_path": remote_path,
        "local_path": str(local_path),
        "returncode": completed.returncode,
    }
