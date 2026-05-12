#!/usr/bin/env python
"""Install a generated certificate handoff on a customer-side Libreswan node."""

from __future__ import annotations

import argparse
import json
import re
import secrets
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MUXER_SRC = REPO_ROOT / "muxer" / "src"
for import_path in (REPO_ROOT, MUXER_SRC, Path(__file__).resolve().parent):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from muxerlib.customer_merge import load_yaml_file  # noqa: E402

from live_access_lib import (  # noqa: E402
    build_ssh_access_context,
    cleanup_ssh_access_context,
    copy_paths_to_remote_root,
    run_aws_json,
    run_remote_command,
)


DEFAULT_CUSTOMER_FILE = (
    REPO_ROOT
    / "build"
    / "live-validation"
    / "requests"
    / "vpn-customer-stage1-15-cust-0004-certificate.yaml"
)
DEFAULT_ENVIRONMENT = REPO_ROOT / "build" / "live-validation" / "rpdb-empty-live-local-psk.yaml"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_json(command: list[str]) -> tuple[int, dict[str, Any] | None, str, str]:
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    payload = None
    if completed.stdout.strip():
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            payload = None
    return completed.returncode, payload, completed.stdout, completed.stderr


def environment_validation(environment: str) -> tuple[int, dict[str, Any] | None, str, str]:
    return run_json(
        [
            sys.executable,
            "scripts/customers/validate_deployment_environment.py",
            environment,
            "--allow-live-apply",
            "--json",
        ]
    )


def load_environment_doc(environment: str) -> dict[str, Any]:
    code, validation, stdout, stderr = environment_validation(environment)
    if code != 0 or not validation or not validation.get("valid"):
        raise RuntimeError(f"deployment environment validation failed: {stderr or stdout}".strip())
    return load_yaml_file(Path(str(validation["environment_file"])))


def repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def redact_sensitive_text(value: str) -> str:
    return re.sub(r"(P12_PASSWORD=)[^\s\"']+", r"\1<redacted>", value)


def redact_sensitive_report(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: redact_sensitive_report(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_sensitive_report(item) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def resolve_repo_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def resolve_file_ref(ref: str) -> Path:
    value = str(ref or "").strip()
    if not value:
        raise ValueError("empty certificate material reference")
    if value.startswith("file://"):
        value = value[len("file://") :]
        if re.match(r"^/[A-Za-z]:/", value):
            value = value[1:]
    path = Path(value)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def require_file(path: Path, label: str) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"{label} is not a file: {path}")
    return path


def normalize_identity(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text if text.startswith("@") else f"@{text}"


def libreswan_ike_policy(policy: str) -> str:
    parts = [part.strip().lower() for part in str(policy or "").split("-") if part.strip()]
    if not parts:
        return ""
    cipher = parts[0].replace("aes256gcm", "aes_gcm256").replace("aes256", "aes256")
    integrity = ""
    dh = ""
    for part in parts[1:]:
        if part.startswith("sha"):
            integrity = part.replace("sha256", "sha2_256").replace("sha384", "sha2_384").replace("sha512", "sha2_512")
        elif part.startswith("modp"):
            dh = part
    if integrity and dh:
        return f"{cipher}-{integrity};{dh}"
    if integrity:
        return f"{cipher}-{integrity}"
    return cipher


def libreswan_esp_policy(policy: str) -> str:
    ike_policy = libreswan_ike_policy(policy)
    return ike_policy.split(";", 1)[0] if ike_policy else ""


def render_libreswan_config(
    *,
    customer_name: str,
    nickname: str,
    request_doc: dict[str, Any],
    muxer_public_ip: str,
) -> str:
    customer = request_doc.get("customer") or {}
    selectors = customer.get("selectors") or {}
    ipsec = customer.get("ipsec") or {}
    auth = ((ipsec.get("auth") or {}).get("certificate") or {})
    headend = auth.get("headend") or {}
    remote = auth.get("remote") or {}
    left_id = normalize_identity(str(remote.get("id") or ""))
    right_id = normalize_identity(str(headend.get("id") or ""))
    remote_subnets = [str(value) for value in (selectors.get("remote_subnets") or []) if str(value).strip()]
    local_subnets = [str(value) for value in (selectors.get("local_subnets") or []) if str(value).strip()]
    if not remote_subnets:
        raise ValueError("customer selectors.remote_subnets is required for customer-side Libreswan config")
    if not local_subnets:
        raise ValueError("customer selectors.local_subnets is required for customer-side Libreswan config")
    if not left_id or not right_id:
        raise ValueError("certificate remote.id and headend.id are required")
    if not muxer_public_ip:
        raise ValueError("muxer public IP is required")

    left_selector_key = "leftsubnet" if len(remote_subnets) == 1 else "leftsubnets"
    left_selector_value = remote_subnets[0] if len(remote_subnets) == 1 else "{" + ",".join(remote_subnets) + "}"
    right_selector_key = "rightsubnet" if len(local_subnets) == 1 else "rightsubnets"
    right_selector_value = local_subnets[0] if len(local_subnets) == 1 else "{" + ",".join(local_subnets) + "}"
    ike_values = [
        converted
        for converted in (libreswan_ike_policy(value) for value in (ipsec.get("ike_policies") or []))
        if converted
    ]
    esp_values = [
        converted
        for converted in (libreswan_esp_policy(value) for value in (ipsec.get("esp_policies") or []))
        if converted
    ]
    ike_line = ",".join(ike_values)
    esp_line = ",".join(dict.fromkeys(esp_values))
    encapsulation = "yes" if bool(ipsec.get("forceencaps") or ipsec.get("fragmentation")) else "yes"
    dpdaction = str(ipsec.get("dpdaction") or "restart")
    dpddelay = str(ipsec.get("dpddelay") or "10s")
    auto = str(ipsec.get("auto") or "start")

    lines = [
        f"conn {customer_name}",
        "    type=tunnel",
        "    ikev2=insist",
        "    authby=rsasig",
        "",
        "    left=%defaultroute",
        f"    leftid={left_id}",
        f"    leftcert={nickname}",
        f"    {left_selector_key}={left_selector_value}",
        "",
        f"    right={muxer_public_ip}",
        f"    rightid={right_id}",
        f"    {right_selector_key}={right_selector_value}",
        "",
    ]
    if ike_line:
        lines.append(f"    ike={ike_line}")
    if esp_line:
        lines.append(f"    phase2alg={esp_line}")
    lines.extend(
        [
            f"    encapsulation={encapsulation}",
            "",
            f"    dpdaction={dpdaction}",
            f"    dpddelay={dpddelay}",
            "    keyingtries=%forever",
            f"    auto={auto}",
            "",
        ]
    )
    return "\n".join(lines)


def render_secrets(customer_name: str, nickname: str) -> str:
    return "\n".join(
        [
            f"# {customer_name} uses certificate authentication.",
            f"# Private key is imported into Libreswan NSS DB under nickname {nickname}.",
            "",
        ]
    )


def certificate_handoff(request_doc: dict[str, Any]) -> dict[str, Any]:
    cert_auth = ((((request_doc.get("customer") or {}).get("ipsec") or {}).get("auth") or {}).get("certificate") or {})
    handoff = cert_auth.get("customer_handoff") or {}
    remote = cert_auth.get("remote") or {}
    if not handoff.get("enabled"):
        raise ValueError("customer_handoff.enabled must be true in the customer certificate request")
    return {
        "cert_ref": handoff.get("cert_ref") or remote.get("cert_ref"),
        "private_key_ref": handoff.get("private_key_secret_ref"),
        "trust_ref": handoff.get("trust_ref") or remote.get("trust_ref"),
    }


def resolve_customer_instance_id(customer_name: str, *, region: str) -> str:
    payload = run_aws_json(
        [
            "ec2",
            "describe-instances",
            "--region",
            region,
            "--filters",
            f"Name=tag:Name,Values={customer_name}",
            "Name=instance-state-name,Values=running",
            "--query",
            "Reservations[].Instances[].InstanceId",
            "--output",
            "json",
        ]
    )
    matches = [str(item) for item in payload if str(item).strip()] if isinstance(payload, list) else []
    if len(matches) != 1:
        raise RuntimeError(f"expected one running EC2 instance tagged Name={customer_name}, found {len(matches)}")
    return matches[0]


def staging_root(customer_name: str) -> Path:
    return REPO_ROOT / "build" / "customer-certificate-handoff" / customer_name / "copy-root"


def prepare_staging_tree(
    *,
    customer_name: str,
    nickname: str,
    request_doc: dict[str, Any],
    muxer_public_ip: str,
) -> tuple[Path, list[Path], dict[str, Any]]:
    handoff = certificate_handoff(request_doc)
    cert_path = require_file(resolve_file_ref(str(handoff["cert_ref"])), "customer certificate")
    key_path = require_file(resolve_file_ref(str(handoff["private_key_ref"])), "customer private key")
    trust_path = require_file(resolve_file_ref(str(handoff["trust_ref"])), "customer trust certificate")

    root = staging_root(customer_name)
    if root.exists():
        shutil.rmtree(root)
    remote_rel_root = Path("tmp") / "rpdb-customer-cert-handoff" / customer_name
    material_dir = root / remote_rel_root
    material_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cert_path, material_dir / "customer.crt")
    shutil.copyfile(key_path, material_dir / "customer.key")
    shutil.copyfile(trust_path, material_dir / "trust.crt")
    (material_dir / "ipsec.conf").write_text(
        render_libreswan_config(
            customer_name=customer_name,
            nickname=nickname,
            request_doc=request_doc,
            muxer_public_ip=muxer_public_ip,
        ),
        encoding="utf-8",
        newline="\n",
    )
    (material_dir / "ipsec.secrets").write_text(
        render_secrets(customer_name, nickname),
        encoding="utf-8",
        newline="\n",
    )
    metadata = {
        "customer_name": customer_name,
        "nickname": nickname,
        "source_files": {
            "certificate": str(cert_path),
            "private_key": str(key_path),
            "trust": str(trust_path),
        },
        "remote_stage": "/" + remote_rel_root.as_posix(),
    }
    (material_dir / "install-metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return root, [remote_rel_root], metadata


def remote_install_command(
    *,
    customer_name: str,
    nickname: str,
    ca_nickname: str,
    initiate: bool,
) -> str:
    stage = f"/tmp/rpdb-customer-cert-handoff/{customer_name}"
    p12_password = secrets.token_urlsafe(24)
    payload = f"""
set -euo pipefail
export LC_ALL=C LANG=C
CUSTOMER={shlex.quote(customer_name)}
NICK={shlex.quote(nickname)}
CA_NICK={shlex.quote(ca_nickname)}
STAGE={shlex.quote(stage)}
NSS_DIR=/var/lib/ipsec/nss
MATERIAL_ROOT=/etc/ipsec.d/rpdb-certauth/${{CUSTOMER}}
CONF=/etc/ipsec.d/${{CUSTOMER}}.conf
SECRETS=/etc/ipsec.d/${{CUSTOMER}}.secrets
BACKUP_SUFFIX=$(date -u +%Y%m%dT%H%M%SZ)
P12_PASSWORD={shlex.quote(p12_password)}

test -f "${{STAGE}}/customer.crt"
test -f "${{STAGE}}/customer.key"
test -f "${{STAGE}}/trust.crt"
test -f "${{STAGE}}/ipsec.conf"
test -f "${{STAGE}}/ipsec.secrets"
command -v openssl >/dev/null
command -v certutil >/dev/null
command -v pk12util >/dev/null
command -v ipsec >/dev/null

mkdir -p "${{MATERIAL_ROOT}}" /etc/ipsec.d/cacerts "${{NSS_DIR}}"
install -m 0644 "${{STAGE}}/customer.crt" "${{MATERIAL_ROOT}}/${{NICK}}.crt"
install -m 0600 "${{STAGE}}/customer.key" "${{MATERIAL_ROOT}}/${{NICK}}.key"
install -m 0644 "${{STAGE}}/trust.crt" "${{MATERIAL_ROOT}}/${{CA_NICK}}.crt"
install -m 0644 "${{STAGE}}/trust.crt" "/etc/ipsec.d/cacerts/${{CA_NICK}}.crt"

if [ ! -f "${{NSS_DIR}}/cert9.db" ]; then
  certutil -N -d "sql:${{NSS_DIR}}" --empty-password
fi

openssl pkcs12 -export \\
  -name "${{NICK}}" \\
  -in "${{MATERIAL_ROOT}}/${{NICK}}.crt" \\
  -inkey "${{MATERIAL_ROOT}}/${{NICK}}.key" \\
  -certfile "${{MATERIAL_ROOT}}/${{CA_NICK}}.crt" \\
  -out "${{MATERIAL_ROOT}}/${{NICK}}.p12" \\
  -passout "pass:${{P12_PASSWORD}}"
chmod 0600 "${{MATERIAL_ROOT}}/${{NICK}}.p12"

certutil -D -d "sql:${{NSS_DIR}}" -n "${{NICK}}" >/dev/null 2>&1 || true
pk12util -i "${{MATERIAL_ROOT}}/${{NICK}}.p12" -d "sql:${{NSS_DIR}}" -W "${{P12_PASSWORD}}"
certutil -D -d "sql:${{NSS_DIR}}" -n "${{CA_NICK}}" >/dev/null 2>&1 || true
certutil -A -d "sql:${{NSS_DIR}}" -n "${{CA_NICK}}" -t "CT,," -i "${{MATERIAL_ROOT}}/${{CA_NICK}}.crt"

[ ! -f "${{CONF}}" ] || cp -a "${{CONF}}" "${{CONF}}.pre-certinstall-${{BACKUP_SUFFIX}}"
[ ! -f "${{SECRETS}}" ] || cp -a "${{SECRETS}}" "${{SECRETS}}.pre-certinstall-${{BACKUP_SUFFIX}}"
install -m 0644 "${{STAGE}}/ipsec.conf" "${{CONF}}"
install -m 0600 "${{STAGE}}/ipsec.secrets" "${{SECRETS}}"

systemctl enable --now ipsec >/dev/null 2>&1 || systemctl start ipsec
ipsec auto --replace "${{CUSTOMER}}"
INITIATE={1 if initiate else 0}
if [ "${{INITIATE}}" = "1" ]; then
  ipsec auto --up "${{CUSTOMER}}"
fi

printf 'installed_customer=%s\\n' "${{CUSTOMER}}"
printf 'nickname=%s\\n' "${{NICK}}"
printf 'config=%s\\n' "${{CONF}}"
printf 'secrets=%s\\n' "${{SECRETS}}"
printf 'material_root=%s\\n' "${{MATERIAL_ROOT}}"
printf 'ipsec_active=%s\\n' "$(systemctl is-active ipsec 2>/dev/null || true)"
ipsec auto --status 2>/dev/null | grep -E "${{CUSTOMER}}|RSASIG|newest IKE SA" | sed -n '1,80p' || true
"""
    return "sudo bash -lc " + shlex.quote(payload)


def remote_verify_command(customer_name: str, nickname: str) -> str:
    payload = f"""
set -euo pipefail
export LC_ALL=C LANG=C
CUSTOMER={shlex.quote(customer_name)}
NICK={shlex.quote(nickname)}
CONF=/etc/ipsec.d/${{CUSTOMER}}.conf
SECRETS=/etc/ipsec.d/${{CUSTOMER}}.secrets
NSS_DIR=/var/lib/ipsec/nss
echo verify_customer="${{CUSTOMER}}"
test -f "${{CONF}}" && echo conf_present=true || echo conf_present=false
test -f "${{SECRETS}}" && echo secrets_present=true || echo secrets_present=false
grep -q 'authby=rsasig' "${{CONF}}" && echo authby_rsasig=true || echo authby_rsasig=false
grep -q "leftcert=${{NICK}}" "${{CONF}}" && echo leftcert_match=true || echo leftcert_match=false
certutil -L -d "sql:${{NSS_DIR}}" -n "${{NICK}}" >/dev/null 2>&1 && echo nss_cert_present=true || echo nss_cert_present=false
systemctl is-active ipsec 2>/dev/null | sed 's/^/ipsec_active=/'
ipsec auto --status 2>/dev/null | grep -E "${{CUSTOMER}}|RSASIG|newest IKE SA" | sed -n '1,80p' || true
"""
    return "sudo bash -lc " + shlex.quote(payload)


def muxer_public_ip(environment_doc: dict[str, Any]) -> str:
    muxer = ((environment_doc.get("targets") or {}).get("muxer") or {})
    selector = muxer.get("selector") or {}
    return str(selector.get("public_ip") or "").strip()


def muxer_instance_id(environment_doc: dict[str, Any]) -> str:
    muxer = ((environment_doc.get("targets") or {}).get("muxer") or {})
    selector = muxer.get("selector") or {}
    instance_id = str(selector.get("value") or "").strip()
    if not instance_id:
        raise RuntimeError("environment targets.muxer.selector.value is required")
    return instance_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install generated certificate handoff material on a customer-side Libreswan node."
    )
    parser.add_argument("--customer-file", default=str(DEFAULT_CUSTOMER_FILE))
    parser.add_argument("--environment", default=str(DEFAULT_ENVIRONMENT))
    parser.add_argument("--customer-instance-id", default="")
    parser.add_argument("--ssh-user", default="ec2-user")
    parser.add_argument("--nickname", default="")
    parser.add_argument("--ca-nickname", default="rpdb-demo-third-party-ca")
    parser.add_argument("--approve", action="store_true", help="Actually copy material and update the customer node.")
    parser.add_argument("--initiate", action="store_true", help="Run ipsec auto --up after installing the config.")
    parser.add_argument("--verify-only", action="store_true", help="Only verify the customer-side certificate state.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    request_path = resolve_repo_path(args.customer_file)
    request_doc = load_yaml_file(request_path)
    customer = request_doc.get("customer") or {}
    customer_name = str(customer.get("name") or "").strip()
    if not customer_name:
        raise SystemExit("customer.name is required in --customer-file")
    nickname = str(args.nickname or f"{customer_name}-customer").strip()
    environment_doc = load_environment_doc(args.environment)
    environment = environment_doc.get("environment") or {}
    region = str((environment.get("aws") or {}).get("region") or "").strip()
    if not region:
        raise SystemExit("environment.aws.region is required")
    target_instance_id = str(args.customer_instance_id or "").strip() or resolve_customer_instance_id(customer_name, region=region)
    bastion_instance_id = muxer_instance_id(environment_doc)

    stage_root, relative_paths, material_metadata = prepare_staging_tree(
        customer_name=customer_name,
        nickname=nickname,
        request_doc=request_doc,
        muxer_public_ip=muxer_public_ip(environment_doc),
    )
    plan = {
        "schema_version": 1,
        "action": "install_customer_certificate_handoff",
        "generated_at": utc_now(),
        "approved": bool(args.approve),
        "verify_only": bool(args.verify_only),
        "customer_name": customer_name,
        "customer_file": repo_relative(request_path),
        "environment": args.environment,
        "target_instance_id": target_instance_id,
        "bastion_instance_id": bastion_instance_id,
        "ssh_user": args.ssh_user,
        "nickname": nickname,
        "ca_nickname": args.ca_nickname,
        "initiate": bool(args.initiate),
        "staging": {
            "root": repo_relative(stage_root),
            **material_metadata,
        },
    }
    if not args.approve and not args.verify_only:
        plan["status"] = "planned"
        if args.json:
            print(json.dumps(plan, indent=2, sort_keys=True))
        else:
            print(f"planned customer certificate install for {customer_name}")
            print(f"- target instance: {target_instance_id}")
            print(f"- customer file: {repo_relative(request_path)}")
            print(f"- staging root: {repo_relative(stage_root)}")
            print("rerun with --approve to install")
        return 0

    context = build_ssh_access_context(
        region=region,
        ssh_user=args.ssh_user,
        bastion_instance_id=bastion_instance_id,
        target_instance_ids=[target_instance_id],
    )
    try:
        copy_result: dict[str, Any] | None = None
        install_result: dict[str, Any] | None = None
        if not args.verify_only:
            copy_result = copy_paths_to_remote_root(
                context=context,
                target_instance_id=target_instance_id,
                source_root=stage_root,
                relative_paths=relative_paths,
                remote_name=f"{customer_name}-cert-handoff",
                via_bastion=True,
                timeout_seconds=240,
            )
            if not copy_result.get("success"):
                raise RuntimeError(copy_result.get("extract_stderr") or copy_result.get("copy_stderr") or "remote copy failed")
            install_result = run_remote_command(
                context=context,
                target_instance_id=target_instance_id,
                via_bastion=True,
                remote_command=remote_install_command(
                    customer_name=customer_name,
                    nickname=nickname,
                    ca_nickname=args.ca_nickname,
                    initiate=bool(args.initiate),
                ),
                timeout_seconds=300,
            )
            if not install_result.get("success"):
                raise RuntimeError(install_result.get("stderr") or install_result.get("stdout") or "remote install failed")
        verify_result = run_remote_command(
            context=context,
            target_instance_id=target_instance_id,
            via_bastion=True,
            remote_command=remote_verify_command(customer_name, nickname),
            timeout_seconds=180,
        )
        plan.update(
            {
                "status": "installed" if not args.verify_only else "verified",
                "copy": redact_sensitive_report(copy_result),
                "install": redact_sensitive_report(install_result),
                "verify": redact_sensitive_report(verify_result),
            }
        )
    finally:
        cleanup_ssh_access_context(context)

    if args.json:
        print(json.dumps(plan, indent=2, sort_keys=True))
    else:
        if plan.get("install"):
            print((plan["install"].get("stdout") or "").strip())
        print((plan["verify"].get("stdout") or "").strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
