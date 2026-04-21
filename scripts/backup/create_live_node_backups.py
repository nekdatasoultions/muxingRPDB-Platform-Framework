#!/usr/bin/env python
"""Create read-only pre-change backups from RPDB live nodes."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CUSTOMER_SCRIPT_ROOT = REPO_ROOT / "scripts" / "customers"
sys.path.insert(0, str(CUSTOMER_SCRIPT_ROOT))

from live_access_lib import (  # noqa: E402
    build_ssh_access_context,
    cleanup_ssh_access_context,
    copy_remote_file_to_local,
    run_local,
    run_remote_command,
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _resolve_environment(value: str) -> Path:
    candidate = Path(value)
    if candidate.exists():
        return candidate.resolve()
    named = REPO_ROOT / "muxer" / "config" / "deployment-environments" / f"{value}.yaml"
    if named.exists():
        return named.resolve()
    raise FileNotFoundError(f"deployment environment not found: {value}")


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _s3_parts(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"expected s3 URI: {uri}")
    remainder = uri[5:]
    bucket, _, prefix = remainder.partition("/")
    if not bucket or not prefix:
        raise ValueError(f"expected bucket and prefix in s3 URI: {uri}")
    return bucket, prefix.strip("/")


def _s3_join(uri: str, *parts: str) -> str:
    bucket, prefix = _s3_parts(uri)
    cleaned = [prefix, *[part.strip("/") for part in parts if part.strip("/")]]
    return "s3://" + "/".join([bucket, *cleaned])


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _target_inventory(environment_doc: dict[str, Any]) -> list[dict[str, Any]]:
    targets = environment_doc.get("targets") or {}
    muxer = targets.get("muxer") or {}
    headends = targets.get("headends") or {}
    inventory: list[dict[str, Any]] = [
        {
            "name": str(muxer.get("name") or "muxer"),
            "component": "muxer",
            "s3_key": "muxer",
            "instance_id": str(((muxer.get("selector") or {}).get("value")) or ""),
            "via_bastion": False,
        }
    ]
    for family, s3_key in (("nat", "nat_headend"), ("non_nat", "non_nat_headend")):
        pair = headends.get(family) or {}
        for role in ("active", "standby"):
            target = pair.get(role) or {}
            inventory.append(
                {
                    "name": str(target.get("name") or f"{family}-{role}"),
                    "component": f"{family}-{role}",
                    "s3_key": s3_key,
                    "instance_id": str(((target.get("selector") or {}).get("value")) or ""),
                    "via_bastion": True,
                }
            )
    missing = [item["name"] for item in inventory if not item["instance_id"]]
    if missing:
        raise ValueError("environment targets missing instance IDs: " + ", ".join(missing))
    return inventory


def _remote_backup_command(snapshot_name: str) -> str:
    # The iptables-save snapshot is observational only. Runtime/apply artifacts remain nftables-only.
    return f"""
set -u
SNAP=/tmp/{snapshot_name}
ARCHIVE=/tmp/{snapshot_name}.tgz
rm -rf "$SNAP" "$ARCHIVE"
mkdir -p "$SNAP/config"
cd "$SNAP"
date -u +%Y-%m-%dT%H:%M:%SZ > captured-at.txt
hostname > hostname.txt 2>&1 || true
uname -a > uname.txt 2>&1 || true
id > id.txt 2>&1 || true
ip addr show > ip-addr.txt 2>&1 || true
ip rule show > ip-rule.txt 2>&1 || true
ip route show table all > ip-route-all.txt 2>&1 || true
ip -d link show > ip-link-detail.txt 2>&1 || true
sudo nft list ruleset > nft-ruleset.txt 2>&1 || true
sudo iptables-save > iptables-save.txt 2>&1 || true
sudo conntrack -S > conntrack-stats.txt 2>&1 || true
ip xfrm state > ip-xfrm-state.txt 2>&1 || true
ip xfrm policy > ip-xfrm-policy.txt 2>&1 || true
systemctl list-units --type=service --all > systemctl-list-units.txt 2>&1 || true
systemctl status muxer strongswan strongswan-swanctl swanctl charon-systemd --no-pager > systemctl-status-selected.txt 2>&1 || true
for item in \\
  /etc/muxer \\
  /etc/swanctl \\
  /etc/strongswan \\
  /etc/strongswan.d \\
  /etc/ipsec.d \\
  /var/lib/rpdb-muxer \\
  /var/lib/rpdb-headend \\
  /etc/sysctl.d \\
  /etc/systemd/system
do
  if [ -e "$item" ]; then
    safe="$(printf '%s' "$item" | sed 's#^/##; s#[^A-Za-z0-9._-]#_#g')"
    sudo tar -C / -czf "config/${{safe}}.tgz" "${{item#/}}" >/dev/null 2>&1 || true
  fi
done
find . -type f ! -name manifest.txt ! -name sha256sums.txt -printf '%P\\n' | sort > manifest.txt
if command -v sha256sum >/dev/null 2>&1; then
  while IFS= read -r file; do sha256sum "$file"; done < manifest.txt > sha256sums.txt
else
  echo "sha256sum unavailable" > sha256sums.txt
fi
sudo tar -C "$SNAP" -czf "$ARCHIVE" .
sudo chown "$USER":"$USER" "$ARCHIVE" 2>/dev/null || sudo chown ec2-user:ec2-user "$ARCHIVE" 2>/dev/null || true
printf '%s\\n' "$ARCHIVE"
"""


def _extract_archive(archive_path: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(destination, filter="data")


def _aws_s3_sync(local_dir: Path, s3_uri: str) -> dict[str, Any]:
    completed = run_local(
        ["aws", "s3", "sync", str(local_dir), s3_uri, "--only-show-errors"],
        cwd=REPO_ROOT,
        timeout=300,
    )
    return {
        "command": completed.args,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "success": completed.returncode == 0,
        "s3_uri": s3_uri,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create read-only RPDB live node backups.")
    parser.add_argument("--environment", required=True, help="Deployment environment name or YAML file")
    parser.add_argument("--out-dir", help="Local output directory")
    parser.add_argument("--upload-s3", action="store_true", help="Upload extracted snapshots to configured S3 backup prefixes")
    parser.add_argument("--json", action="store_true", help="Print the backup report as JSON")
    args = parser.parse_args()

    environment_file = _resolve_environment(args.environment)
    environment_doc = _load_yaml(environment_file)
    environment = environment_doc.get("environment") or {}
    aws = environment.get("aws") or {}
    access = environment.get("access") or {}
    ssh = access.get("ssh") or {}
    region = str(aws.get("region") or "").strip()
    ssh_user = str(ssh.get("user") or "").strip()
    if not region:
        raise SystemExit("environment.aws.region is required")
    if not ssh_user:
        raise SystemExit("environment.access.ssh.user is required")

    run_id = _utc_timestamp()
    out_dir = Path(args.out_dir or (REPO_ROOT / "build" / "live-backups" / run_id)).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    inventory = _target_inventory(environment_doc)
    muxer = next(item for item in inventory if item["component"] == "muxer")
    backups = environment_doc.get("backups") or {}
    context = None
    report: dict[str, Any] = {
        "schema_version": 1,
        "environment": str(environment.get("name") or args.environment),
        "environment_file": str(environment_file),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": run_id,
        "out_dir": str(out_dir),
        "upload_s3": bool(args.upload_s3),
        "nodes": [],
        "valid": False,
        "errors": [],
    }

    try:
        context = build_ssh_access_context(
            region=region,
            ssh_user=ssh_user,
            bastion_instance_id=muxer["instance_id"],
            target_instance_ids=[item["instance_id"] for item in inventory],
        )
        for item in inventory:
            snapshot_name = f"{item['component']}-{item['instance_id']}-{run_id}"
            archive_path = out_dir / f"{snapshot_name}.tgz"
            snapshot_dir = out_dir / snapshot_name
            remote = run_remote_command(
                context=context,
                target_instance_id=item["instance_id"],
                via_bastion=bool(item["via_bastion"]),
                timeout_seconds=180,
                remote_command="sudo bash -lc " + _shell_quote(_remote_backup_command(snapshot_name)),
            )
            node_report: dict[str, Any] = {
                "name": item["name"],
                "component": item["component"],
                "instance_id": item["instance_id"],
                "via_bastion": bool(item["via_bastion"]),
                "snapshot_name": snapshot_name,
                "archive": str(archive_path),
                "snapshot_dir": str(snapshot_dir),
                "remote_success": remote["success"],
                "remote_stderr": remote["stderr"],
            }
            if not remote["success"]:
                node_report["success"] = False
                report["errors"].append(f"remote backup failed for {item['name']}")
                report["nodes"].append(node_report)
                continue
            remote_archive = remote["stdout"].strip().splitlines()[-1]
            copied = copy_remote_file_to_local(
                context=context,
                target_instance_id=item["instance_id"],
                via_bastion=bool(item["via_bastion"]),
                remote_path=remote_archive,
                local_path=archive_path,
                timeout_seconds=180,
            )
            node_report["copy"] = copied
            if not copied["success"]:
                node_report["success"] = False
                report["errors"].append(f"copy backup failed for {item['name']}")
                report["nodes"].append(node_report)
                continue
            cleanup = run_remote_command(
                context=context,
                target_instance_id=item["instance_id"],
                via_bastion=bool(item["via_bastion"]),
                timeout_seconds=60,
                remote_command=(
                    "sudo bash -lc "
                    + _shell_quote(
                        f"rm -rf /tmp/{snapshot_name} /tmp/{snapshot_name}.tgz"
                    )
                ),
            )
            node_report["remote_cleanup"] = {
                "success": cleanup["success"],
                "stderr": cleanup["stderr"],
                "stdout": cleanup["stdout"],
            }
            _extract_archive(archive_path, snapshot_dir)
            node_report["extracted"] = True
            if args.upload_s3:
                backup_root = str(backups.get(item["s3_key"]) or "").strip()
                if not backup_root:
                    node_report["success"] = False
                    report["errors"].append(f"S3 backup root missing for {item['name']}")
                    report["nodes"].append(node_report)
                    continue
                s3_uri = _s3_join(backup_root, snapshot_name)
                upload = _aws_s3_sync(snapshot_dir, s3_uri)
                node_report["s3"] = upload
                if not upload["success"]:
                    node_report["success"] = False
                    report["errors"].append(f"S3 upload failed for {item['name']}")
                    report["nodes"].append(node_report)
                    continue
            node_report["success"] = True
            report["nodes"].append(node_report)
    finally:
        if context is not None:
            cleanup_ssh_access_context(context)

    report["valid"] = not report["errors"] and all(node.get("success") for node in report["nodes"])
    _write_json(out_dir / "backup-report.json", report)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Backup report: {out_dir / 'backup-report.json'}")
        for node in report["nodes"]:
            status = "OK" if node.get("success") else "FAIL"
            print(f"- {node['component']} {node['instance_id']}: {status}")
        for error in report["errors"]:
            print(f"error: {error}")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
