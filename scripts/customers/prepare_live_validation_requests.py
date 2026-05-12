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


CGNAT_SERVICE_REACHABLE_SUBNETS = ["23.20.31.151/32", "194.138.36.86/32"]
CGNAT_OUTSIDE_NAT_ROUTE_VIA = "172.31.63.44"
CGNAT_OUTSIDE_NAT_ROUTE_DEV = "ens36"


def cgnat_inside_nat(real_subnet: str, translated_subnet: str) -> dict[str, Any]:
    return {
        "enabled": True,
        "mode": "netmap",
        "mapping_strategy": "one_to_one",
        "real_subnets": [real_subnet],
        "translated_subnets": [translated_subnet],
        "core_subnets": list(CGNAT_SERVICE_REACHABLE_SUBNETS),
    }


def cgnat_outside_nat(translated_subnet: str, customer_source: str) -> dict[str, Any]:
    return {
        "enabled": True,
        "mode": "netmap",
        "mapping_strategy": "one_to_one",
        "real_subnets": ["194.138.36.86/32"],
        "translated_subnets": [translated_subnet],
        "customer_sources": [customer_source],
        "route_via": CGNAT_OUTSIDE_NAT_ROUTE_VIA,
        "route_dev": CGNAT_OUTSIDE_NAT_ROUTE_DEV,
    }


def cgnat_demo_spec(
    *,
    profile: str,
    customer_name: str,
    outer_topology: str,
    peer_public_ip: str,
    customer_loopback_ip: str,
    real_inside_subnet: str,
    inside_translated_subnet: str = "",
    outside_translated_subnet: str = "",
    outer_gateway_ref: str = "",
    outer_transport: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_topology = outer_topology.strip().lower().replace("-", "_")
    normalized_gateway_ref = outer_gateway_ref.strip()
    if normalized_topology == "per_customer_outer" and normalized_gateway_ref:
        raise ValueError("per_customer_outer demo profiles must not set outer_gateway_ref")
    if normalized_topology == "shared_isp_gateway" and not normalized_gateway_ref:
        raise ValueError("shared_isp_gateway demo profiles must pin an ISP outer_gateway_ref")
    has_inside_nat = bool(inside_translated_subnet)
    has_outside_nat = bool(outside_translated_subnet)
    local_subnets = (
        ["23.20.31.151/32", outside_translated_subnet]
        if has_outside_nat
        else list(CGNAT_SERVICE_REACHABLE_SUBNETS)
    )
    return {
        "profile": profile,
        "customer_name": customer_name,
        "outer_topology": normalized_topology,
        "outer_gateway_ref": normalized_gateway_ref,
        "service_profile": "scenario2" if normalized_topology == "shared_isp_gateway" else "scenario1",
        "peer_public_ip": peer_public_ip,
        "customer_loopback_ip": customer_loopback_ip,
        "known_inside_identity": real_inside_subnet,
        "local_subnets": local_subnets,
        "remote_subnets": [real_inside_subnet],
        "remote_host_cidrs": [real_inside_subnet],
        "service_reachable_subnets": list(CGNAT_SERVICE_REACHABLE_SUBNETS),
        "outer_transport": dict(outer_transport or {}),
        "post_ipsec_nat": (
            cgnat_inside_nat(real_inside_subnet, inside_translated_subnet) if has_inside_nat else None
        ),
        "outside_nat": cgnat_outside_nat(outside_translated_subnet, real_inside_subnet) if has_outside_nat else None,
        "inside_nat_enabled": has_inside_nat,
        "outside_nat_enabled": has_outside_nat,
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
    entries = [
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
    cgnat_nat_specs = [
        cgnat_demo_spec(
            profile="cgnat-per-customer-outer-inside-nat",
            customer_name="demo-ca-cgnat-per-outer-inside-nat",
            outer_topology="per_customer_outer",
            peer_public_ip="203.0.113.201",
            customer_loopback_ip="10.250.10.10",
            real_inside_subnet="10.60.10.10/32",
            inside_translated_subnet="172.30.10.10/32",
            outer_transport={
                "headend_underlay_interface": "ens34",
                "headend_xfrm_interface": "cgxfrm-r3",
                "headend_if_id": 103,
                "customer_router_private_ip": "172.31.48.30",
            },
        ),
        cgnat_demo_spec(
            profile="cgnat-per-customer-outer-inside-outside-nat",
            customer_name="demo-ca-cgnat-per-outer-inside-outside-nat",
            outer_topology="per_customer_outer",
            peer_public_ip="203.0.113.202",
            customer_loopback_ip="10.250.10.11",
            real_inside_subnet="10.60.10.11/32",
            inside_translated_subnet="172.30.10.11/32",
            outside_translated_subnet="10.60.40.11/32",
            outer_transport={
                "headend_underlay_interface": "ens34",
                "headend_xfrm_interface": "cgxfrm-r4",
                "headend_if_id": 104,
                "customer_router_private_ip": "172.31.48.31",
            },
        ),
        cgnat_demo_spec(
            profile="cgnat-per-customer-outer-outside-nat",
            customer_name="demo-ca-cgnat-per-outer-outside-nat",
            outer_topology="per_customer_outer",
            peer_public_ip="203.0.113.203",
            customer_loopback_ip="10.250.10.12",
            real_inside_subnet="10.60.10.12/32",
            outside_translated_subnet="10.60.40.12/32",
            outer_transport={
                "headend_underlay_interface": "ens34",
                "headend_xfrm_interface": "cgxfrm-r5",
                "headend_if_id": 105,
                "customer_router_private_ip": "172.31.48.32",
            },
        ),
        cgnat_demo_spec(
            profile="cgnat-shared-isp-gateway-inside-nat",
            customer_name="demo-ca-cgnat-shared-isp-inside-nat",
            outer_topology="shared_isp_gateway",
            outer_gateway_ref="isp-cgnat-router-2",
            peer_public_ip="203.0.113.211",
            customer_loopback_ip="10.250.20.10",
            real_inside_subnet="10.60.20.10/32",
            inside_translated_subnet="172.30.20.10/32",
            outer_transport={
                "headend_xfrm_interface": "cgxfrm-gw2",
                "customer_router_private_ip": "172.31.48.33",
                "gateway_customer_interface": "ens34",
            },
        ),
        cgnat_demo_spec(
            profile="cgnat-shared-isp-gateway-inside-outside-nat",
            customer_name="demo-ca-cgnat-shared-isp-inside-outside-nat",
            outer_topology="shared_isp_gateway",
            outer_gateway_ref="isp-cgnat-router-2",
            peer_public_ip="203.0.113.212",
            customer_loopback_ip="10.250.20.11",
            real_inside_subnet="10.60.20.11/32",
            inside_translated_subnet="172.30.20.11/32",
            outside_translated_subnet="10.60.50.11/32",
            outer_transport={
                "headend_xfrm_interface": "cgxfrm-gw2",
                "customer_router_private_ip": "172.31.48.34",
                "gateway_customer_interface": "ens34",
            },
        ),
        cgnat_demo_spec(
            profile="cgnat-shared-isp-gateway-outside-nat",
            customer_name="demo-ca-cgnat-shared-isp-outside-nat",
            outer_topology="shared_isp_gateway",
            outer_gateway_ref="isp-cgnat-router-2",
            peer_public_ip="203.0.113.213",
            customer_loopback_ip="10.250.20.12",
            real_inside_subnet="10.60.20.12/32",
            outside_translated_subnet="10.60.50.12/32",
            outer_transport={
                "headend_xfrm_interface": "cgxfrm-gw2",
                "customer_router_private_ip": "172.31.48.35",
                "gateway_customer_interface": "ens34",
            },
        ),
    ]
    for spec in cgnat_nat_specs:
        manifest = issue_cgnat_customer_bundle(
            ca_root=ca_root,
            ca_name=ca_name,
            customer_name=spec["customer_name"],
            peer_public_ip=spec["peer_public_ip"],
            outer_topology=spec["outer_topology"],
            outer_gateway_ref=spec["outer_gateway_ref"],
            service_profile=spec["service_profile"],
            customer_loopback_ip=spec["customer_loopback_ip"],
            known_inside_identity=spec["known_inside_identity"],
            local_subnets=spec["local_subnets"],
            remote_subnets=spec["remote_subnets"],
            remote_host_cidrs=spec["remote_host_cidrs"],
            service_reachable_subnets=spec["service_reachable_subnets"],
            post_ipsec_nat=spec["post_ipsec_nat"],
            outside_nat=spec["outside_nat"],
            encrypt_headend_key=encrypt_headend_key,
            headend_key_passphrase=headend_key_passphrase,
            request_out=request_dir / f"{spec['customer_name']}.yaml",
        )
        if spec["outer_transport"]:
            request_path = Path(manifest["request_path"])
            request_doc = yaml.safe_load(request_path.read_text(encoding="utf-8")) or {}
            cgnat = request_doc.setdefault("customer", {}).setdefault("transport", {}).setdefault("cgnat", {})
            cgnat["outer_transport"] = spec["outer_transport"]
            write_yaml(request_path, request_doc)
        entries.append(
            {
                "profile": spec["profile"],
                "customer_name": manifest["customer_name"],
                "request_path": manifest["request_path"],
                "request_ref": repo_relative(Path(manifest["request_path"])),
                "outer_topology": manifest["outer_topology"],
                "outer_gateway_ref": manifest["outer_gateway_ref"],
                "inside_nat_enabled": spec["inside_nat_enabled"],
                "outside_nat_enabled": spec["outside_nat_enabled"],
                "certificate_manifest": manifest,
            }
        )
    return entries


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
