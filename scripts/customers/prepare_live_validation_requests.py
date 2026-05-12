#!/usr/bin/env python
"""Prepare jump-host-only request files for the live RPDB validation demo."""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.certificates.demo_ca_server import (  # noqa: E402
    DEFAULT_CA_NAME,
    issue_cgnat_customer_bundle,
    issue_vpn_customer_bundle,
)

DEFAULT_ENVIRONMENT = REPO_ROOT / "muxer" / "config" / "deployment-environments" / "rpdb-empty-live.yaml"
DEFAULT_REQUEST_DIR = REPO_ROOT / "build" / "live-validation" / "requests"
DEFAULT_ENVIRONMENT_OUT = REPO_ROOT / "build" / "live-validation" / "rpdb-empty-live-local-psk.yaml"
DEFAULT_CA_ROOT = REPO_ROOT / "build" / "live-validation" / "demo-ca"

CUSTOMER2_SOURCE = (
    REPO_ROOT
    / "muxer"
    / "config"
    / "customer-requests"
    / "migrated"
    / "vpn-customer-stage1-15-cust-0002.yaml"
)
CUSTOMER4_SOURCE = (
    REPO_ROOT
    / "muxer"
    / "config"
    / "customer-requests"
    / "migrated"
    / "vpn-customer-stage1-15-cust-0004.yaml"
)
CUSTOMER5_SOURCE = (
    REPO_ROOT
    / "muxer"
    / "config"
    / "customer-requests"
    / "migrated"
    / "vpn-customer-stage1-15-cust-0005.yaml"
)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def secret_id_from_ref(secret_ref: str) -> str:
    value = str(secret_ref or "").strip()
    if value.startswith("aws-secretsmanager:"):
        value = value.split(":", 1)[1]
    return value


def fetch_secret_string(secret_ref: str, *, region: str) -> str:
    secret_id = secret_id_from_ref(secret_ref)
    if not secret_id:
        raise RuntimeError("cannot fetch a PSK because the source request does not define psk_secret_ref")
    aws = shutil.which("aws")
    if not aws:
        raise RuntimeError("aws CLI was not found; pass --customer2-psk or set RPDB_CUSTOMER2_LOCAL_PSK")
    completed = subprocess.run(
        [
            aws,
            "secretsmanager",
            "get-secret-value",
            "--region",
            region,
            "--secret-id",
            secret_id,
            "--output",
            "json",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"unable to fetch PSK secret {secret_id}: {completed.stderr or completed.stdout}".strip()
        )
    payload = json.loads(completed.stdout or "{}")
    secret_string = str(payload.get("SecretString") or "")
    if not secret_string:
        raise RuntimeError(f"PSK secret {secret_id} did not return SecretString")
    return secret_string


def resolve_customer2_psk(customer2_doc: dict[str, Any], *, region: str, explicit_psk: str) -> str:
    if explicit_psk:
        return explicit_psk
    env_psk = os.environ.get("RPDB_CUSTOMER2_LOCAL_PSK", "")
    if env_psk:
        return env_psk
    peer = ((customer2_doc.get("customer") or {}).get("peer") or {})
    return fetch_secret_string(str(peer.get("psk_secret_ref") or ""), region=region)


def prepare_environment_copy(environment_path: Path, output_path: Path, *, request_dir: Path | None = None) -> dict[str, Any]:
    environment_doc = load_yaml(environment_path)
    secrets_doc = environment_doc.setdefault("secrets", {})
    if not isinstance(secrets_doc, dict):
        raise RuntimeError("deployment environment secrets section must be an object")
    secrets_doc["allow_local_psk"] = True
    if request_dir is not None:
        customer_requests = environment_doc.setdefault("customer_requests", {})
        if not isinstance(customer_requests, dict):
            raise RuntimeError("deployment environment customer_requests section must be an object")
        allowed_roots = customer_requests.setdefault("allowed_roots", [])
        if not isinstance(allowed_roots, list):
            raise RuntimeError("deployment environment customer_requests.allowed_roots must be a list")
        request_ref = repo_relative(request_dir)
        customer_requests["allowed_roots"] = [
            str(root) for root in allowed_roots if str(root).strip() != request_ref
        ] + [request_ref]
    description = ((environment_doc.get("environment") or {}).get("description") or "").strip()
    if description:
        environment_doc["environment"]["description"] = (
            description + " Live-validation copy with local PSK enabled for generated demo requests."
        )
    write_yaml(output_path, environment_doc)
    return environment_doc


def prepare_customer2_local_psk(
    *,
    request_dir: Path,
    region: str,
    customer2_psk: str,
    customer2_peer_ip: str,
) -> dict[str, Any]:
    doc = load_yaml(CUSTOMER2_SOURCE)
    psk = resolve_customer2_psk(doc, region=region, explicit_psk=customer2_psk)
    customer = doc.setdefault("customer", {})
    peer = customer.setdefault("peer", {})
    if customer2_peer_ip:
        peer["public_ip"] = customer2_peer_ip
    peer["psk_source"] = "local"
    peer["psk"] = psk
    peer.pop("psk_secret_ref", None)
    output_path = request_dir / "vpn-customer-stage1-15-cust-0002-local-psk.yaml"
    write_yaml(output_path, doc)
    return {
        "profile": "customer2-local-psk",
        "customer_name": customer.get("name"),
        "request_path": str(output_path),
        "request_ref": repo_relative(output_path),
        "source_path": repo_relative(CUSTOMER2_SOURCE),
        "peer_public_ip": peer.get("public_ip"),
        "psk_source": "local",
    }


def prepare_customer4_certificate(
    *,
    request_dir: Path,
    ca_root: Path,
    ca_name: str,
    customer4_peer_ip: str,
    encrypt_headend_key: bool,
    headend_key_passphrase: str,
) -> dict[str, Any]:
    doc = load_yaml(CUSTOMER4_SOURCE)
    customer = doc.setdefault("customer", {})
    peer = customer.setdefault("peer", {})
    selectors = customer.setdefault("selectors", {})
    peer_ip = customer4_peer_ip or str(peer.get("public_ip") or "")
    if peer_ip:
        peer["public_ip"] = peer_ip
    manifest = issue_vpn_customer_bundle(
        ca_root=ca_root,
        ca_name=ca_name,
        customer_name=str(customer.get("name") or "vpn-customer-stage1-15-cust-0004"),
        profile="third_party_provided",
        peer_public_ip=peer_ip,
        headend_id="rpdb-headend.vpn-customer-stage1-15-cust-0004.example",
        remote_id="vpn-customer-stage1-15-cust-0004.customer.example",
        local_subnets=[str(value) for value in (selectors.get("local_subnets") or [])],
        remote_subnets=[str(value) for value in (selectors.get("remote_subnets") or [])],
        encrypt_headend_key=encrypt_headend_key,
        headend_key_passphrase=headend_key_passphrase,
        request_out=request_dir / "vpn-customer-stage1-15-cust-0004-certificate-issued-only.yaml",
    )
    peer.pop("psk_secret_ref", None)
    peer.pop("psk_source", None)
    peer.pop("psk", None)
    ipsec = customer.setdefault("ipsec", {})
    ipsec["auth"] = {
        "method": "certificate",
        "certificate": {
            "profile": "third_party_provided",
            "headend": {
                "id": manifest["headend"]["identity"],
                "cert_ref": manifest["headend"]["certificate_ref"],
                "private_key_secret_ref": manifest["headend"]["private_key_ref"],
                **(
                    {
                        "private_key_passphrase_secret_ref": manifest["headend"][
                            "private_key_passphrase_ref"
                        ]
                    }
                    if manifest["headend"].get("private_key_passphrase_ref")
                    else {}
                ),
            },
            "remote": {
                "id": manifest["remote"]["identity"],
                "trust_ref": manifest["trust_ref"],
                "cert_ref": manifest["remote"]["certificate_ref"],
            },
            "customer_handoff": {
                "enabled": True,
                "cert_ref": manifest["remote"]["certificate_ref"],
                "private_key_secret_ref": manifest["remote"]["private_key_ref"],
                "trust_ref": manifest["trust_ref"],
                "notes": "Demo CA generated handoff material. Do not use this CA for production.",
            },
        },
    }
    output_path = request_dir / "vpn-customer-stage1-15-cust-0004-certificate.yaml"
    write_yaml(output_path, doc)
    return {
        "profile": "customer4-certificate",
        "customer_name": customer.get("name"),
        "request_path": str(output_path),
        "request_ref": repo_relative(output_path),
        "source_path": repo_relative(CUSTOMER4_SOURCE),
        "peer_public_ip": peer.get("public_ip"),
        "certificate_manifest": manifest,
    }


def first_host_cidr(cidr: str, *, offset: int = 1) -> str:
    import ipaddress

    network = ipaddress.ip_network(str(cidr), strict=False)
    hosts = list(network.hosts())
    if not hosts:
        return f"{network.network_address}/32"
    index = min(max(offset, 0), len(hosts) - 1)
    return f"{hosts[index]}/32"


def prepare_customer5_explicit_inside_nat(*, request_dir: Path) -> dict[str, Any]:
    doc = load_yaml(CUSTOMER5_SOURCE)
    customer = doc.setdefault("customer", {})
    post_nat = customer.setdefault("post_ipsec_nat", {})
    real_subnets = [str(value) for value in (post_nat.get("real_subnets") or []) if str(value).strip()]
    translated_subnets = [
        str(value) for value in (post_nat.get("translated_subnets") or []) if str(value).strip()
    ]
    if not real_subnets:
        raise RuntimeError("Customer 5 source does not define post_ipsec_nat.real_subnets")
    if not translated_subnets:
        raise RuntimeError("Customer 5 source does not define post_ipsec_nat.translated_subnets")
    post_nat["enabled"] = True
    post_nat["mode"] = "explicit_map"
    post_nat["mapping_strategy"] = "explicit_host_map"
    post_nat["host_mappings"] = [
        {
            "real_ip": real_subnets[0],
            "translated_ip": first_host_cidr(translated_subnets[0], offset=4),
        }
    ]
    output_path = request_dir / "vpn-customer-stage1-15-cust-0005-explicit-inside-nat.yaml"
    write_yaml(output_path, doc)
    return {
        "profile": "customer5-inside-nat-explicit-map",
        "customer_name": customer.get("name"),
        "request_path": str(output_path),
        "request_ref": repo_relative(output_path),
        "source_path": repo_relative(CUSTOMER5_SOURCE),
        "host_mappings": copy.deepcopy(post_nat["host_mappings"]),
        "translated_subnets": translated_subnets,
    }


def prepare_cgnat_requests(
    *,
    request_dir: Path,
    ca_root: Path,
    ca_name: str,
    encrypt_headend_key: bool,
    headend_key_passphrase: str,
) -> list[dict[str, Any]]:
    per_customer = issue_cgnat_customer_bundle(
        ca_root=ca_root,
        ca_name=ca_name,
        customer_name="demo-ca-cgnat-customer-router",
        outer_topology="per_customer_outer",
        service_profile="scenario1",
        customer_loopback_ip="10.250.9.10",
        known_inside_identity="10.20.30.10/32",
        encrypt_headend_key=encrypt_headend_key,
        headend_key_passphrase=headend_key_passphrase,
        request_out=request_dir / "demo-ca-cgnat-customer-router.yaml",
    )
    shared_gateway = issue_cgnat_customer_bundle(
        ca_root=ca_root,
        ca_name=ca_name,
        customer_name="demo-ca-cgnat-shared-gateway",
        outer_topology="shared_isp_gateway",
        outer_gateway_ref="isp-cgnat-router-2",
        service_profile="scenario2",
        customer_loopback_ip="10.250.9.11",
        known_inside_identity="10.20.30.11/32",
        remote_subnets=["10.20.30.11/32"],
        encrypt_headend_key=encrypt_headend_key,
        headend_key_passphrase=headend_key_passphrase,
        request_out=request_dir / "demo-ca-cgnat-shared-gateway.yaml",
    )
    return [
        {
            "profile": "cgnat-provided-per-customer-outer",
            "customer_name": per_customer["customer_name"],
            "request_path": per_customer["request_path"],
            "request_ref": repo_relative(Path(per_customer["request_path"])),
            "outer_topology": per_customer["outer_topology"],
            "certificate_manifest": per_customer,
        },
        {
            "profile": "cgnat-provided-shared-isp-gateway",
            "customer_name": shared_gateway["customer_name"],
            "request_path": shared_gateway["request_path"],
            "request_ref": repo_relative(Path(shared_gateway["request_path"])),
            "outer_topology": shared_gateway["outer_topology"],
            "outer_gateway_ref": shared_gateway["outer_gateway_ref"],
            "certificate_manifest": shared_gateway,
        },
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate jump-host-only live validation requests for the RPDB demo set."
    )
    parser.add_argument("--environment", default=str(DEFAULT_ENVIRONMENT))
    parser.add_argument("--environment-out", default=str(DEFAULT_ENVIRONMENT_OUT))
    parser.add_argument("--request-dir", default=str(DEFAULT_REQUEST_DIR))
    parser.add_argument("--manifest-out", default=str(DEFAULT_REQUEST_DIR / "live-validation-manifest.json"))
    parser.add_argument("--ca-root", default=str(DEFAULT_CA_ROOT))
    parser.add_argument("--ca-name", default=DEFAULT_CA_NAME)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument(
        "--customer2-psk",
        default="",
        help="Inline Customer 2 PSK. If omitted, RPDB_CUSTOMER2_LOCAL_PSK or AWS Secrets Manager is used.",
    )
    parser.add_argument("--customer2-peer-ip", default="", help="Optional current Customer 2 public IP override.")
    parser.add_argument("--customer4-peer-ip", default="", help="Optional current Customer 4 public IP override.")
    parser.add_argument("--encrypt-headend-key", action="store_true")
    parser.add_argument("--headend-key-passphrase", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    request_dir = Path(args.request_dir).resolve()
    environment_out = Path(args.environment_out).resolve()
    ca_root = Path(args.ca_root).resolve()
    manifest_out = Path(args.manifest_out).resolve()

    environment_doc = prepare_environment_copy(
        Path(args.environment).resolve(),
        environment_out,
        request_dir=request_dir,
    )
    entries: list[dict[str, Any]] = [
        prepare_customer2_local_psk(
            request_dir=request_dir,
            region=args.region,
            customer2_psk=args.customer2_psk,
            customer2_peer_ip=args.customer2_peer_ip,
        ),
        prepare_customer4_certificate(
            request_dir=request_dir,
            ca_root=ca_root,
            ca_name=args.ca_name,
            customer4_peer_ip=args.customer4_peer_ip,
            encrypt_headend_key=bool(args.encrypt_headend_key),
            headend_key_passphrase=args.headend_key_passphrase,
        ),
        prepare_customer5_explicit_inside_nat(request_dir=request_dir),
        *prepare_cgnat_requests(
            request_dir=request_dir,
            ca_root=ca_root,
            ca_name=args.ca_name,
            encrypt_headend_key=bool(args.encrypt_headend_key),
            headend_key_passphrase=args.headend_key_passphrase,
        ),
    ]
    manifest = {
        "schema_version": 1,
        "purpose": "Jump-host-only live validation inputs for Customer 2, Customer 4, Customer 5, and CGNAT demos.",
        "environment": {
            "source": repo_relative(Path(args.environment).resolve()),
            "generated": repo_relative(environment_out),
            "allow_local_psk": bool(((environment_doc.get("secrets") or {}).get("allow_local_psk"))),
        },
        "request_dir": repo_relative(request_dir),
        "requests": entries,
        "secret_handling": [
            "Generated request files may contain local PSK or private-key file references.",
            "The default output lives under build/live-validation, which is gitignored.",
            "Do not commit generated files or copy them outside the approved demo host.",
        ],
    }
    write_json(manifest_out, manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
