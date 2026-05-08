"""Helpers for RPDB dynamic peer IP registry bootstrap and cleanup."""

from __future__ import annotations

import hashlib
import json
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from live_backend_lib import (
    aws_env,
    delete_typed_item,
    extract_key,
    get_typed_item,
    put_typed_item,
    serialize_plain_item,
    table_key_names,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _load_customer_module(package_dir: Path) -> dict[str, Any]:
    return json.loads((package_dir / "customer-module.json").read_text(encoding="utf-8"))


def _run_aws(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["aws", *command],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
        env=aws_env(),
    )


def _try_aws_secret_string(region: str, secret_id: str) -> tuple[str | None, bool]:
    completed = _run_aws(
        [
            "secretsmanager",
            "get-secret-value",
            "--region",
            region,
            "--secret-id",
            secret_id,
            "--query",
            "SecretString",
            "--output",
            "text",
        ]
    )
    if completed.returncode == 0:
        secret = completed.stdout.rstrip("\r\n")
        if not secret or secret == "None":
            raise RuntimeError(f"dynamic peer IP password secret {secret_id} did not contain SecretString")
        return secret, True
    output = (completed.stderr or completed.stdout).strip()
    if "ResourceNotFoundException" in output:
        return None, False
    raise RuntimeError(
        f"unable to resolve dynamic peer IP password secret {secret_id}: "
        f"{output or 'AWS CLI command failed'}"
    )


def _write_password_handoff(
    *,
    apply_dir: Path,
    customer_name: str,
    serial_number: str,
    secret_ref: str,
    password: str,
    generated_locally: bool,
) -> dict[str, str]:
    handoff_dir = apply_dir / "customer-handoff" / "dynamic-peer-ip"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    password_path = handoff_dir / "ddns-password.txt"
    manifest_path = handoff_dir / "ddns-password-manifest.json"
    password_path.write_text(password + "\n", encoding="utf-8")
    write_json(
        manifest_path,
        {
            "schema_version": 1,
            "customer_name": customer_name,
            "serial_number": serial_number,
            "secret_ref": secret_ref,
            "generated_locally": generated_locally,
            "generated_at": utc_now(),
            "password_path": repo_relative(password_path),
            "password_sha256": hashlib.sha256(password.encode("utf-8")).hexdigest(),
        },
    )
    return {
        "password_path": repo_relative(password_path),
        "manifest_path": repo_relative(manifest_path),
    }


def _dynamic_peer_ip_registry_config(
    module: dict[str, Any],
    environment_doc: dict[str, Any],
) -> dict[str, Any] | None:
    dynamic = module.get("dynamic_peer_ip") or {}
    if not isinstance(dynamic, dict) or not bool(dynamic.get("enabled")):
        return None

    registry = dynamic.get("device_registry") or {}
    if not isinstance(registry, dict):
        raise RuntimeError("customer module dynamic_peer_ip.device_registry must be a mapping")

    watcher_source = ((environment_doc.get("dynamic_peer_ip_watcher") or {}).get("source") or {})
    environment_region = str(((environment_doc.get("environment") or {}).get("aws") or {}).get("region") or "").strip()

    customer = module.get("customer") or {}
    peer = module.get("peer") or {}
    metadata = module.get("metadata") or {}
    customer_name = str(customer.get("name") or "").strip()
    serial_number = str(registry.get("serial_number") or "").strip()
    password_secret_ref = str(registry.get("password_secret_ref") or "").strip()
    region = str(watcher_source.get("region") or environment_region or "").strip()
    table_name = str(registry.get("table_name") or watcher_source.get("table_name") or "").strip()
    serial_number_attribute = str(
        registry.get("serial_number_attribute") or watcher_source.get("serial_number_attribute") or "serialNumber"
    ).strip()
    current_ip_attribute = str(
        registry.get("current_ip_attribute") or watcher_source.get("current_ip_attribute") or "currentIP"
    ).strip()
    last_updated_attribute = str(
        registry.get("last_updated_attribute") or watcher_source.get("last_updated_attribute") or "lastUpdated"
    ).strip()
    peer_public_ip = str(peer.get("public_ip") or "").strip()

    if not customer_name:
        raise RuntimeError("customer module is missing customer.name for dynamic peer IP registry")
    if not serial_number:
        raise RuntimeError("customer module is missing dynamic_peer_ip.device_registry.serial_number")
    if not password_secret_ref:
        raise RuntimeError("customer module is missing dynamic_peer_ip.device_registry.password_secret_ref")
    if not region:
        raise RuntimeError("dynamic peer IP registry region is not configured")
    if not table_name:
        raise RuntimeError("dynamic peer IP registry table name is not configured")
    if not serial_number_attribute or not current_ip_attribute or not last_updated_attribute:
        raise RuntimeError("dynamic peer IP registry attribute mapping is incomplete")
    if not peer_public_ip:
        raise RuntimeError("customer module is missing peer.public_ip for dynamic peer IP registry")

    return {
        "customer_name": customer_name,
        "serial_number": serial_number,
        "password_secret_ref": password_secret_ref,
        "region": region,
        "table_name": table_name,
        "serial_number_attribute": serial_number_attribute,
        "current_ip_attribute": current_ip_attribute,
        "last_updated_attribute": last_updated_attribute,
        "peer_public_ip": peer_public_ip,
        "source_ref": str(metadata.get("source_ref") or "").strip(),
    }


def _resolve_or_seed_password_secret(
    *,
    config: dict[str, Any],
    apply_dir: Path,
) -> dict[str, Any]:
    secret_ref = str(config["password_secret_ref"])
    region = str(config["region"])
    customer_name = str(config["customer_name"])
    serial_number = str(config["serial_number"])

    secret, existed = _try_aws_secret_string(region, secret_ref)
    generated = False
    if not existed or secret is None:
        secret = secrets.token_urlsafe(24)
        completed = _run_aws(
            [
                "secretsmanager",
                "create-secret",
                "--region",
                region,
                "--name",
                secret_ref,
                "--secret-string",
                secret,
            ]
        )
        if completed.returncode != 0:
            output = (completed.stderr or completed.stdout).strip()
            if "ResourceExistsException" not in output:
                raise RuntimeError(
                    f"unable to create dynamic peer IP password secret {secret_ref}: "
                    f"{output or 'AWS CLI command failed'}"
                )
            secret, existed = _try_aws_secret_string(region, secret_ref)
            if not existed or secret is None:
                raise RuntimeError(
                    f"dynamic peer IP password secret {secret_ref} appeared to exist after create race but could not be read"
                )
        else:
            generated = True

    handoff = _write_password_handoff(
        apply_dir=apply_dir,
        customer_name=customer_name,
        serial_number=serial_number,
        secret_ref=secret_ref,
        password=str(secret),
        generated_locally=generated,
    )
    return {
        "password": str(secret),
        "secret_ref": secret_ref,
        "created": generated,
        "secret_sha256": hashlib.sha256(str(secret).encode("utf-8")).hexdigest(),
        "secret_length": len(str(secret)),
        "handoff": handoff,
    }


def ensure_dynamic_peer_ip_registry_state(
    *,
    package_dir: Path,
    environment_doc: dict[str, Any],
    apply_dir: Path,
) -> dict[str, Any]:
    module = _load_customer_module(package_dir)
    config = _dynamic_peer_ip_registry_config(module, environment_doc)
    if config is None:
        return {
            "schema_version": 1,
            "action": "ensure_dynamic_peer_ip_registry_state",
            "status": "not_configured",
            "generated_at": utc_now(),
        }

    secret_report = _resolve_or_seed_password_secret(config=config, apply_dir=apply_dir)
    key_plain = {str(config["serial_number_attribute"]): str(config["serial_number"])}
    key_typed = extract_key(
        serialize_plain_item(key_plain),
        table_key_names(str(config["region"]), str(config["table_name"])),
    )
    existing_item = get_typed_item(str(config["region"]), str(config["table_name"]), key_typed)

    managed_plain = {
        str(config["serial_number_attribute"]): str(config["serial_number"]),
        "password": str(secret_report["password"]),
        str(config["current_ip_attribute"]): str(config["peer_public_ip"]),
        str(config["last_updated_attribute"]): utc_now(),
        "sourceIP": str(config["peer_public_ip"]),
        "customerName": str(config["customer_name"]),
        "managedBy": "muxingRPDB-Platform-Framework",
        "sourceRef": str(config["source_ref"]),
    }
    managed_typed = serialize_plain_item(managed_plain)
    changed = existing_item is None or any(existing_item.get(key) != value for key, value in managed_typed.items())
    action = "created" if existing_item is None else ("updated" if changed else "already_present")
    if changed:
        merged_item = dict(existing_item or {})
        merged_item.update(managed_typed)
        put_typed_item(str(config["region"]), str(config["table_name"]), merged_item)

    return {
        "schema_version": 1,
        "action": "ensure_dynamic_peer_ip_registry_state",
        "status": "ready",
        "generated_at": utc_now(),
        "customer_name": str(config["customer_name"]),
        "serial_number": str(config["serial_number"]),
        "region": str(config["region"]),
        "table_name": str(config["table_name"]),
        "registry_action": action,
        "password_secret_ref": str(secret_report["secret_ref"]),
        "password_secret_created": bool(secret_report["created"]),
        "password_secret_sha256": str(secret_report["secret_sha256"]),
        "password_secret_length": int(secret_report["secret_length"]),
        "peer_public_ip": str(config["peer_public_ip"]),
        "handoff": secret_report["handoff"],
    }


def remove_dynamic_peer_ip_registry_state(
    *,
    customer_module: dict[str, Any],
    environment_doc: dict[str, Any],
) -> dict[str, Any]:
    config = _dynamic_peer_ip_registry_config(customer_module, environment_doc)
    if config is None:
        return {
            "schema_version": 1,
            "action": "remove_dynamic_peer_ip_registry_state",
            "status": "not_configured",
            "generated_at": utc_now(),
        }

    key_plain = {str(config["serial_number_attribute"]): str(config["serial_number"])}
    key_typed = extract_key(
        serialize_plain_item(key_plain),
        table_key_names(str(config["region"]), str(config["table_name"])),
    )
    existing_item = get_typed_item(str(config["region"]), str(config["table_name"]), key_typed)
    if existing_item is None:
        return {
            "schema_version": 1,
            "action": "remove_dynamic_peer_ip_registry_state",
            "status": "not_present",
            "generated_at": utc_now(),
            "customer_name": str(config["customer_name"]),
            "serial_number": str(config["serial_number"]),
            "region": str(config["region"]),
            "table_name": str(config["table_name"]),
        }

    delete_typed_item(str(config["region"]), str(config["table_name"]), key_typed)
    return {
        "schema_version": 1,
        "action": "remove_dynamic_peer_ip_registry_state",
        "status": "removed",
        "generated_at": utc_now(),
        "customer_name": str(config["customer_name"]),
        "serial_number": str(config["serial_number"]),
        "region": str(config["region"]),
        "table_name": str(config["table_name"]),
    }
