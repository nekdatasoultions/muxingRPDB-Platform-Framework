#!/usr/bin/env python
"""Demo CA issuer for certificate-auth customer testing.

This is a lab/test helper. It intentionally writes PEM material to a local
artifact directory and returns file refs that the customer provisioning path
can consume without needing a real external CA or Secrets Manager upload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import shutil
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CA_NAME = "rpdb-demo-third-party-ca"
DEFAULT_LOCAL_SUBNETS = ["172.31.54.39/32", "194.138.36.80/28"]
DEFAULT_REMOTE_SUBNETS = ["10.200.70.70/32"]
DEFAULT_CGNAT_LOCAL_SUBNETS = ["23.20.31.151/32", "194.138.36.86/32"]
DEFAULT_CGNAT_REMOTE_SUBNETS = ["10.20.30.10/32"]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload if payload.endswith("\n") else payload + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True))


def chmod_private(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass


def safe_name(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value).strip()).strip("-._")
    return sanitized or "customer"


def runtime_identity(value: str) -> str:
    return safe_name(str(value).replace("/", "."))


def subject_common_name(value: str, *, max_length: int = 64) -> str:
    candidate = runtime_identity(value)
    if len(candidate) <= max_length:
        return candidate
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:8]
    keep = max_length - len(digest) - 1
    return f"{candidate[:keep]}-{digest}"


def file_ref(path: Path) -> str:
    return "file://" + path.resolve().as_posix()


def find_openssl() -> str:
    candidates = [
        shutil.which("openssl"),
        r"C:\Program Files\OpenSSL-Win64\bin\openssl.exe",
        r"C:\Program Files\Git\usr\bin\openssl.exe",
        r"C:\Program Files\Git\mingw64\bin\openssl.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(Path(candidate))
    raise FileNotFoundError("Unable to locate openssl for demo CA material generation.")


def run_openssl(openssl_bin: str, *args: str) -> None:
    completed = subprocess.run(
        [openssl_bin, *args],
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "openssl command failed: "
            + " ".join(args)
            + f"\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


def ensure_demo_ca(ca_root: Path, *, ca_name: str = DEFAULT_CA_NAME, days: int = 3650) -> dict[str, Any]:
    ca_dir = ca_root.resolve() / safe_name(ca_name)
    ca_material_dir = ca_dir / "ca"
    ca_key = ca_material_dir / "ca.key"
    ca_cert = ca_material_dir / "ca.crt"
    manifest_path = ca_dir / "ca-manifest.json"
    openssl_bin = find_openssl()

    if not ca_key.exists() or not ca_cert.exists():
        ca_material_dir.mkdir(parents=True, exist_ok=True)
        run_openssl(
            openssl_bin,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(ca_key),
            "-out",
            str(ca_cert),
            "-days",
            str(days),
            "-subj",
            f"/CN={subject_common_name(ca_name)}",
        )
        chmod_private(ca_key)

    manifest = {
        "schema_version": 1,
        "ca_name": ca_name,
        "ca_root": str(ca_dir),
        "generated_at": utc_now(),
        "openssl_path": openssl_bin,
        "ca_certificate_path": str(ca_cert),
        "ca_private_key_path": str(ca_key),
        "ca_certificate_ref": file_ref(ca_cert),
        "purpose": "Lab-only CA that mimics a third-party issuer for RPDB certificate-auth testing.",
    }
    write_json(manifest_path, manifest)
    return manifest


def write_leaf_ext(path: Path, *, identity: str) -> None:
    san_identity = runtime_identity(identity)
    write_text(
        path,
        "\n".join(
            [
                "basicConstraints=CA:FALSE",
                "keyUsage=digitalSignature,keyEncipherment",
                "extendedKeyUsage=serverAuth,clientAuth",
                f"subjectAltName=DNS:{san_identity}",
                "",
            ]
        ),
    )


def issue_leaf_certificate(
    *,
    openssl_bin: str,
    ca_cert: Path,
    ca_key: Path,
    output_dir: Path,
    basename: str,
    identity: str,
    days: int,
    encrypted_key: bool = False,
    key_passphrase: str = "",
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    key_path = output_dir / f"{basename}.key"
    passphrase_path = output_dir / f"{basename}.passphrase.txt"
    csr_path = output_dir / f"{basename}.csr"
    cert_path = output_dir / f"{basename}.crt"
    ext_path = output_dir / f"{basename}.ext"

    if encrypted_key:
        resolved_passphrase = key_passphrase or secrets.token_urlsafe(24)
        write_text(passphrase_path, resolved_passphrase)
        chmod_private(passphrase_path)
        run_openssl(
            openssl_bin,
            "genrsa",
            "-aes256",
            "-passout",
            f"file:{passphrase_path}",
            "-out",
            str(key_path),
            "2048",
        )
        run_openssl(
            openssl_bin,
            "req",
            "-new",
            "-key",
            str(key_path),
            "-passin",
            f"file:{passphrase_path}",
            "-out",
            str(csr_path),
            "-subj",
            f"/CN={subject_common_name(identity)}",
        )
    else:
        run_openssl(
            openssl_bin,
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key_path),
            "-out",
            str(csr_path),
            "-subj",
            f"/CN={subject_common_name(identity)}",
        )
    chmod_private(key_path)
    write_leaf_ext(ext_path, identity=identity)
    run_openssl(
        openssl_bin,
        "x509",
        "-req",
        "-in",
        str(csr_path),
        "-CA",
        str(ca_cert),
        "-CAkey",
        str(ca_key),
        "-CAcreateserial",
        "-out",
        str(cert_path),
        "-days",
        str(days),
        "-sha256",
        "-extfile",
        str(ext_path),
    )
    return {
        "identity": identity,
        "certificate_path": str(cert_path),
        "certificate_ref": file_ref(cert_path),
        "private_key_path": str(key_path),
        "private_key_ref": file_ref(key_path),
        "csr_path": str(csr_path),
        "ext_path": str(ext_path),
        "private_key_encrypted": encrypted_key,
        "private_key_passphrase_path": str(passphrase_path) if encrypted_key else "",
        "private_key_passphrase_ref": file_ref(passphrase_path) if encrypted_key else "",
    }


def yaml_list(values: list[str], *, indent: int) -> list[str]:
    prefix = " " * indent
    return [f"{prefix}- {value}" for value in values]


def render_customer_request_yaml(
    *,
    customer_name: str,
    profile: str,
    peer_public_ip: str,
    headend_id: str,
    remote_id: str,
    local_subnets: list[str],
    remote_subnets: list[str],
    headend_cert_ref: str,
    headend_key_ref: str,
    headend_passphrase_ref: str,
    remote_cert_ref: str,
    remote_key_ref: str,
    trust_ref: str,
    customer_handoff_enabled: bool,
) -> str:
    lines = [
        "schema_version: 1",
        "",
        "customer:",
        f"  name: {customer_name}",
        "  customer_class: strict-non-nat",
        "  peer:",
        f"    public_ip: {peer_public_ip}",
        "  selectors:",
        "    local_subnets:",
        *yaml_list(local_subnets, indent=6),
        "    remote_subnets:",
        *yaml_list(remote_subnets, indent=6),
        "  backend:",
        "    cluster: non-nat",
        "  protocols:",
        "    udp500: true",
        "    udp4500: false",
        "    esp50: true",
        "  natd_rewrite:",
        "    enabled: true",
        "  ipsec:",
        "    ike_version: ikev2",
        "    auth:",
        "      method: certificate",
        "      certificate:",
        f"        profile: {profile}",
        "        headend:",
        f"          id: {headend_id}",
        f"          cert_ref: {headend_cert_ref}",
        f"          private_key_secret_ref: {headend_key_ref}",
    ]
    if headend_passphrase_ref:
        lines.append(f"          private_key_passphrase_secret_ref: {headend_passphrase_ref}")
    lines.extend(
        [
            "        remote:",
            f"          id: {remote_id}",
            f"          trust_ref: {trust_ref}",
            f"          cert_ref: {remote_cert_ref}",
        ]
    )
    if customer_handoff_enabled:
        lines.extend(
            [
                "        customer_handoff:",
                "          enabled: true",
                f"          cert_ref: {remote_cert_ref}",
                f"          private_key_secret_ref: {remote_key_ref}",
                f"          trust_ref: {trust_ref}",
                "          notes: Demo CA generated handoff material. Do not use this CA for production.",
            ]
        )
    return "\n".join(lines) + "\n"


def render_cgnat_customer_request_yaml(
    *,
    customer_name: str,
    peer_public_ip: str,
    local_subnets: list[str],
    remote_subnets: list[str],
    service_profile: str,
    outer_topology: str,
    outer_gateway_ref: str,
    customer_loopback_ip: str,
    known_inside_identity: str,
    service_reachable_subnets: list[str],
    headend_id: str,
    headend_cert_ref: str,
    headend_key_ref: str,
    headend_passphrase_ref: str,
    outer_id: str,
    outer_cert_ref: str,
    outer_key_ref: str,
    outer_passphrase_ref: str,
    trust_ref: str,
) -> str:
    pki_edge_key = "gateway" if outer_topology == "shared_isp_gateway" else "customer"
    pki_edge_package = (
        f"{customer_name}-{safe_name(outer_gateway_ref or 'isp-gateway')}-outer-gateway"
        if pki_edge_key == "gateway"
        else f"{customer_name}-customer-outer"
    )
    lines = [
        "schema_version: 1",
        "",
        "customer:",
        f"  name: {customer_name}",
        "  customer_class: strict-non-nat",
        "  peer:",
        f"    public_ip: {peer_public_ip}",
        "    psk_source: local",
        f"    psk: demo-inner-{customer_name}-psk",
        "  selectors:",
        "    local_subnets:",
        *yaml_list(local_subnets, indent=6),
        "    remote_subnets:",
        *yaml_list(remote_subnets, indent=6),
        "  backend:",
        "    cluster: non-nat",
        "  protocols:",
        "    udp500: true",
        "    udp4500: false",
        "    esp50: true",
        "  natd_rewrite:",
        "    enabled: true",
        "  transport:",
        "    mode: cgnat",
        "    tunnel_mtu: 1436",
        "    cgnat:",
        f"      service_profile: {service_profile}",
    ]
    if outer_topology == "shared_isp_gateway":
        lines.extend(
            [
                "      outer_topology: shared_isp_gateway",
                f"      outer_gateway_ref: {outer_gateway_ref}",
            ]
        )
    lines.extend(
        [
            f"      outer_identity_ref: {outer_id}",
            f"      outer_auth_ref: pki/cgnat/{pki_edge_key}/{customer_name}",
            f"      customer_loopback_ip: {customer_loopback_ip}",
            f"      known_inside_identity: {known_inside_identity}",
            "      service_reachable_subnets:",
            *yaml_list(service_reachable_subnets, indent=8),
            "      pki:",
            "        mode: provided",
            "        provider: rpdb-demo-ca-server",
            "        headend:",
            f"          identity_ref: {headend_id}",
            f"          auth_ref: pki/cgnat/headend/{customer_name}",
            f"          cert_ref: {headend_cert_ref}",
            f"          private_key_secret_ref: {headend_key_ref}",
        ]
    )
    if headend_passphrase_ref:
        lines.append(f"          private_key_passphrase_secret_ref: {headend_passphrase_ref}")
    lines.extend(
        [
            f"        {pki_edge_key}:",
            f"          identity_ref: {outer_id}",
            f"          auth_ref: pki/cgnat/{pki_edge_key}/{customer_name}",
            f"          package_name: {pki_edge_package}",
            f"          cert_ref: {outer_cert_ref}",
            f"          private_key_secret_ref: {outer_key_ref}",
        ]
    )
    if outer_passphrase_ref:
        lines.append(f"          private_key_passphrase_secret_ref: {outer_passphrase_ref}")
    lines.extend(
        [
            "        trust:",
            f"          ca_ref: {trust_ref}",
        ]
    )
    return "\n".join(lines) + "\n"


def issue_vpn_customer_bundle(
    *,
    ca_root: Path,
    customer_name: str,
    profile: str = "third_party_provided",
    ca_name: str = DEFAULT_CA_NAME,
    peer_public_ip: str = "203.0.113.70",
    headend_id: str = "",
    remote_id: str = "",
    local_subnets: list[str] | None = None,
    remote_subnets: list[str] | None = None,
    encrypt_headend_key: bool = False,
    headend_key_passphrase: str = "",
    days: int = 825,
    customer_handoff_enabled: bool | None = None,
    request_out: Path | None = None,
) -> dict[str, Any]:
    normalized_profile = profile.strip().lower().replace("-", "_")
    if normalized_profile not in {"third_party_provided", "customer_supplied"}:
        raise ValueError("profile must be third_party_provided or customer_supplied")

    ca_manifest = ensure_demo_ca(ca_root, ca_name=ca_name)
    ca_dir = Path(ca_manifest["ca_root"])
    ca_cert = Path(ca_manifest["ca_certificate_path"])
    ca_key = Path(ca_manifest["ca_private_key_path"])
    openssl_bin = ca_manifest["openssl_path"]
    safe_customer = safe_name(customer_name)
    issued_dir = ca_dir / "issued" / safe_customer / run_id()
    materials_dir = issued_dir / "materials"
    handoff_dir = issued_dir / "customer-handoff"
    request_path = request_out.resolve() if request_out else issued_dir / f"{safe_customer}-customer-request.yaml"

    resolved_headend_id = headend_id or f"rpdb-headend.{safe_customer}.example"
    resolved_remote_id = remote_id or f"{safe_customer}.customer.example"
    resolved_local_subnets = local_subnets or list(DEFAULT_LOCAL_SUBNETS)
    resolved_remote_subnets = remote_subnets or list(DEFAULT_REMOTE_SUBNETS)
    resolved_handoff_enabled = (
        normalized_profile == "third_party_provided"
        if customer_handoff_enabled is None
        else customer_handoff_enabled
    )

    headend = issue_leaf_certificate(
        openssl_bin=openssl_bin,
        ca_cert=ca_cert,
        ca_key=ca_key,
        output_dir=materials_dir,
        basename=f"{safe_customer}-headend",
        identity=resolved_headend_id,
        days=days,
        encrypted_key=encrypt_headend_key,
        key_passphrase=headend_key_passphrase,
    )
    remote = issue_leaf_certificate(
        openssl_bin=openssl_bin,
        ca_cert=ca_cert,
        ca_key=ca_key,
        output_dir=handoff_dir,
        basename=f"{safe_customer}-customer",
        identity=resolved_remote_id,
        days=days,
    )
    trust_ref = file_ref(ca_cert)

    request_text = render_customer_request_yaml(
        customer_name=safe_customer,
        profile=normalized_profile,
        peer_public_ip=peer_public_ip,
        headend_id=resolved_headend_id,
        remote_id=resolved_remote_id,
        local_subnets=resolved_local_subnets,
        remote_subnets=resolved_remote_subnets,
        headend_cert_ref=headend["certificate_ref"],
        headend_key_ref=headend["private_key_ref"],
        headend_passphrase_ref=headend["private_key_passphrase_ref"],
        remote_cert_ref=remote["certificate_ref"],
        remote_key_ref=remote["private_key_ref"],
        trust_ref=trust_ref,
        customer_handoff_enabled=resolved_handoff_enabled,
    )
    write_text(request_path, request_text)

    manifest = {
        "schema_version": 1,
        "issuer": "rpdb-demo-ca-server",
        "generated_at": utc_now(),
        "ca_name": ca_manifest["ca_name"],
        "profile": normalized_profile,
        "customer_name": safe_customer,
        "peer_public_ip": peer_public_ip,
        "request_path": str(request_path),
        "request_ref": file_ref(request_path),
        "ca_certificate_path": str(ca_cert),
        "trust_ref": trust_ref,
        "headend": headend,
        "remote": remote,
        "customer_handoff_enabled": resolved_handoff_enabled,
        "customer_handoff_dir": str(handoff_dir),
        "issued_dir": str(issued_dir),
        "notes": [
            "Lab-only material for certificate-auth workflow testing.",
            "Use the generated request with scripts/customers/deploy_customer.py for dry-run validation.",
            "Do not use this CA or generated keys for production customers.",
        ],
    }
    write_json(issued_dir / "issued-bundle-manifest.json", manifest)
    return manifest


def issue_cgnat_customer_bundle(
    *,
    ca_root: Path,
    customer_name: str,
    ca_name: str = DEFAULT_CA_NAME,
    peer_public_ip: str = "203.0.113.72",
    outer_topology: str = "per_customer_outer",
    outer_gateway_ref: str = "isp-cgnat-router-1",
    service_profile: str = "scenario1",
    customer_loopback_ip: str = "10.250.9.10",
    known_inside_identity: str = "10.20.30.10/32",
    local_subnets: list[str] | None = None,
    remote_subnets: list[str] | None = None,
    service_reachable_subnets: list[str] | None = None,
    headend_id: str = "",
    outer_id: str = "",
    encrypt_headend_key: bool = False,
    headend_key_passphrase: str = "",
    encrypt_outer_key: bool = False,
    outer_key_passphrase: str = "",
    days: int = 825,
    request_out: Path | None = None,
) -> dict[str, Any]:
    normalized_topology = outer_topology.strip().lower().replace("-", "_")
    if normalized_topology not in {"per_customer_outer", "shared_isp_gateway"}:
        raise ValueError("outer_topology must be per_customer_outer or shared_isp_gateway")

    ca_manifest = ensure_demo_ca(ca_root, ca_name=ca_name)
    ca_dir = Path(ca_manifest["ca_root"])
    ca_cert = Path(ca_manifest["ca_certificate_path"])
    ca_key = Path(ca_manifest["ca_private_key_path"])
    openssl_bin = ca_manifest["openssl_path"]
    safe_customer = safe_name(customer_name)
    issued_dir = ca_dir / "issued-cgnat" / safe_customer / run_id()
    materials_dir = issued_dir / "materials"
    handoff_dir = issued_dir / "outer-handoff"
    request_path = request_out.resolve() if request_out else issued_dir / f"{safe_customer}-cgnat-customer-request.yaml"

    resolved_headend_id = headend_id or f"cgnat-head-end.{safe_customer}.example"
    if outer_id:
        resolved_outer_id = outer_id
    elif normalized_topology == "shared_isp_gateway":
        resolved_outer_id = f"{outer_gateway_ref}.{safe_customer}.example"
    else:
        resolved_outer_id = f"{safe_customer}.customer-router.example"
    resolved_local_subnets = local_subnets or list(DEFAULT_CGNAT_LOCAL_SUBNETS)
    resolved_remote_subnets = remote_subnets or list(DEFAULT_CGNAT_REMOTE_SUBNETS)
    resolved_service_reachable = service_reachable_subnets or list(resolved_local_subnets)

    headend = issue_leaf_certificate(
        openssl_bin=openssl_bin,
        ca_cert=ca_cert,
        ca_key=ca_key,
        output_dir=materials_dir,
        basename=f"{safe_customer}-cgnat-headend",
        identity=resolved_headend_id,
        days=days,
        encrypted_key=encrypt_headend_key,
        key_passphrase=headend_key_passphrase,
    )
    outer = issue_leaf_certificate(
        openssl_bin=openssl_bin,
        ca_cert=ca_cert,
        ca_key=ca_key,
        output_dir=handoff_dir,
        basename=f"{safe_customer}-cgnat-outer",
        identity=resolved_outer_id,
        days=days,
        encrypted_key=encrypt_outer_key,
        key_passphrase=outer_key_passphrase,
    )
    trust_ref = file_ref(ca_cert)

    request_text = render_cgnat_customer_request_yaml(
        customer_name=safe_customer,
        peer_public_ip=peer_public_ip,
        local_subnets=resolved_local_subnets,
        remote_subnets=resolved_remote_subnets,
        service_profile=service_profile,
        outer_topology=normalized_topology,
        outer_gateway_ref=outer_gateway_ref,
        customer_loopback_ip=customer_loopback_ip,
        known_inside_identity=known_inside_identity,
        service_reachable_subnets=resolved_service_reachable,
        headend_id=resolved_headend_id,
        headend_cert_ref=headend["certificate_ref"],
        headend_key_ref=headend["private_key_ref"],
        headend_passphrase_ref=headend["private_key_passphrase_ref"],
        outer_id=resolved_outer_id,
        outer_cert_ref=outer["certificate_ref"],
        outer_key_ref=outer["private_key_ref"],
        outer_passphrase_ref=outer["private_key_passphrase_ref"],
        trust_ref=trust_ref,
    )
    write_text(request_path, request_text)

    manifest = {
        "schema_version": 1,
        "issuer": "rpdb-demo-ca-server",
        "generated_at": utc_now(),
        "ca_name": ca_manifest["ca_name"],
        "customer_name": safe_customer,
        "request_path": str(request_path),
        "request_ref": file_ref(request_path),
        "transport_mode": "cgnat",
        "outer_topology": normalized_topology,
        "outer_gateway_ref": outer_gateway_ref if normalized_topology == "shared_isp_gateway" else "",
        "headend": headend,
        "outer": outer,
        "trust_ref": trust_ref,
        "outer_handoff_dir": str(handoff_dir),
        "issued_dir": str(issued_dir),
        "notes": [
            "Lab-only material for CGNAT outer certificate-auth workflow testing.",
            "The generated request uses pki.mode=provided and local inner-VPN PSK for dry-run convenience.",
            "Do not use this CA or generated keys for production customers.",
        ],
    }
    write_json(issued_dir / "issued-cgnat-bundle-manifest.json", manifest)
    return manifest


class DemoCaRequestHandler(BaseHTTPRequestHandler):
    server_version = "RPDBDemoCA/1.0"

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "service": "rpdb-demo-ca-server"})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/v1/issue/vpn-customer", "/v1/issue/cgnat-customer"}:
            self._send_json(404, {"error": "not found"})
            return
        try:
            content_length = int(self.headers.get("Content-Length") or "0")
            payload = json.loads(self.rfile.read(content_length).decode("utf-8") or "{}")
            ca_root = Path(str(payload.get("ca_root") or self.server.ca_root))  # type: ignore[attr-defined]
            if self.path == "/v1/issue/cgnat-customer":
                manifest = issue_cgnat_customer_bundle(
                    ca_root=ca_root,
                    ca_name=str(payload.get("ca_name") or DEFAULT_CA_NAME),
                    customer_name=str(payload["customer_name"]),
                    peer_public_ip=str(payload.get("peer_public_ip") or "203.0.113.72"),
                    outer_topology=str(payload.get("outer_topology") or "per_customer_outer"),
                    outer_gateway_ref=str(payload.get("outer_gateway_ref") or "isp-cgnat-router-1"),
                    service_profile=str(payload.get("service_profile") or "scenario1"),
                    customer_loopback_ip=str(payload.get("customer_loopback_ip") or "10.250.9.10"),
                    known_inside_identity=str(payload.get("known_inside_identity") or "10.20.30.10/32"),
                    local_subnets=[str(item) for item in payload.get("local_subnets") or DEFAULT_CGNAT_LOCAL_SUBNETS],
                    remote_subnets=[str(item) for item in payload.get("remote_subnets") or DEFAULT_CGNAT_REMOTE_SUBNETS],
                    service_reachable_subnets=[
                        str(item) for item in payload.get("service_reachable_subnets") or DEFAULT_CGNAT_LOCAL_SUBNETS
                    ],
                    headend_id=str(payload.get("headend_id") or ""),
                    outer_id=str(payload.get("outer_id") or ""),
                    encrypt_headend_key=bool(payload.get("encrypt_headend_key")),
                    headend_key_passphrase=str(payload.get("headend_key_passphrase") or ""),
                    encrypt_outer_key=bool(payload.get("encrypt_outer_key")),
                    outer_key_passphrase=str(payload.get("outer_key_passphrase") or ""),
                    days=int(payload.get("days") or 825),
                )
            else:
                manifest = issue_vpn_customer_bundle(
                    ca_root=ca_root,
                    ca_name=str(payload.get("ca_name") or DEFAULT_CA_NAME),
                    customer_name=str(payload["customer_name"]),
                    profile=str(payload.get("profile") or "third_party_provided"),
                    peer_public_ip=str(payload.get("peer_public_ip") or "203.0.113.70"),
                    headend_id=str(payload.get("headend_id") or ""),
                    remote_id=str(payload.get("remote_id") or ""),
                    local_subnets=[str(item) for item in payload.get("local_subnets") or DEFAULT_LOCAL_SUBNETS],
                    remote_subnets=[str(item) for item in payload.get("remote_subnets") or DEFAULT_REMOTE_SUBNETS],
                    encrypt_headend_key=bool(payload.get("encrypt_headend_key")),
                    headend_key_passphrase=str(payload.get("headend_key_passphrase") or ""),
                    days=int(payload.get("days") or 825),
                    customer_handoff_enabled=payload.get("customer_handoff_enabled"),
                )
        except Exception as exc:  # pragma: no cover - exercised manually
            self._send_json(500, {"error": str(exc)})
            return
        self._send_json(201, manifest)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


def serve_ca(*, ca_root: Path, host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), DemoCaRequestHandler)
    server.ca_root = str(ca_root.resolve())  # type: ignore[attr-defined]
    print(f"RPDB demo CA server listening on http://{host}:{port}")
    print("POST /v1/issue/vpn-customer to issue a lab VPN certificate bundle.")
    print("POST /v1/issue/cgnat-customer to issue a lab CGNAT outer certificate bundle.")
    server.serve_forever()


def add_issue_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ca-root", default=str(REPO_ROOT / "build" / "demo-ca"))
    parser.add_argument("--ca-name", default=DEFAULT_CA_NAME)
    parser.add_argument("--customer-name", required=True)
    parser.add_argument("--profile", choices=["third_party_provided", "customer_supplied"], default="third_party_provided")
    parser.add_argument("--peer-public-ip", default="203.0.113.70")
    parser.add_argument("--headend-id", default="")
    parser.add_argument("--remote-id", default="")
    parser.add_argument("--local-subnet", action="append", dest="local_subnets")
    parser.add_argument("--remote-subnet", action="append", dest="remote_subnets")
    parser.add_argument("--encrypt-headend-key", action="store_true")
    parser.add_argument("--headend-key-passphrase", default="")
    parser.add_argument("--days", type=int, default=825)
    parser.add_argument("--request-out")


def main() -> int:
    parser = argparse.ArgumentParser(description="RPDB demo CA server and certificate issuer.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize the demo CA.")
    init_parser.add_argument("--ca-root", default=str(REPO_ROOT / "build" / "demo-ca"))
    init_parser.add_argument("--ca-name", default=DEFAULT_CA_NAME)
    init_parser.add_argument("--days", type=int, default=3650)

    issue_parser = subparsers.add_parser("issue-vpn-customer", help="Issue a VPN certificate-auth demo bundle.")
    add_issue_args(issue_parser)

    cgnat_issue_parser = subparsers.add_parser("issue-cgnat-customer", help="Issue a CGNAT provided-PKI demo bundle.")
    cgnat_issue_parser.add_argument("--ca-root", default=str(REPO_ROOT / "build" / "demo-ca"))
    cgnat_issue_parser.add_argument("--ca-name", default=DEFAULT_CA_NAME)
    cgnat_issue_parser.add_argument("--customer-name", required=True)
    cgnat_issue_parser.add_argument(
        "--outer-topology",
        choices=["per_customer_outer", "shared_isp_gateway"],
        default="per_customer_outer",
    )
    cgnat_issue_parser.add_argument("--outer-gateway-ref", default="isp-cgnat-router-1")
    cgnat_issue_parser.add_argument("--peer-public-ip", default="203.0.113.72")
    cgnat_issue_parser.add_argument("--service-profile", default="scenario1")
    cgnat_issue_parser.add_argument("--customer-loopback-ip", default="10.250.9.10")
    cgnat_issue_parser.add_argument("--known-inside-identity", default="10.20.30.10/32")
    cgnat_issue_parser.add_argument("--local-subnet", action="append", dest="local_subnets")
    cgnat_issue_parser.add_argument("--remote-subnet", action="append", dest="remote_subnets")
    cgnat_issue_parser.add_argument("--service-reachable-subnet", action="append", dest="service_reachable_subnets")
    cgnat_issue_parser.add_argument("--headend-id", default="")
    cgnat_issue_parser.add_argument("--outer-id", default="")
    cgnat_issue_parser.add_argument("--encrypt-headend-key", action="store_true")
    cgnat_issue_parser.add_argument("--headend-key-passphrase", default="")
    cgnat_issue_parser.add_argument("--encrypt-outer-key", action="store_true")
    cgnat_issue_parser.add_argument("--outer-key-passphrase", default="")
    cgnat_issue_parser.add_argument("--days", type=int, default=825)
    cgnat_issue_parser.add_argument("--request-out")

    serve_parser = subparsers.add_parser("serve", help="Run a local HTTP CA issuer.")
    serve_parser.add_argument("--ca-root", default=str(REPO_ROOT / "build" / "demo-ca"))
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)

    args = parser.parse_args()

    if args.command == "init":
        manifest = ensure_demo_ca(Path(args.ca_root), ca_name=args.ca_name, days=args.days)
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    if args.command == "issue-vpn-customer":
        manifest = issue_vpn_customer_bundle(
            ca_root=Path(args.ca_root),
            ca_name=args.ca_name,
            customer_name=args.customer_name,
            profile=args.profile,
            peer_public_ip=args.peer_public_ip,
            headend_id=args.headend_id,
            remote_id=args.remote_id,
            local_subnets=args.local_subnets,
            remote_subnets=args.remote_subnets,
            encrypt_headend_key=args.encrypt_headend_key,
            headend_key_passphrase=args.headend_key_passphrase,
            days=args.days,
            request_out=Path(args.request_out) if args.request_out else None,
        )
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    if args.command == "issue-cgnat-customer":
        manifest = issue_cgnat_customer_bundle(
            ca_root=Path(args.ca_root),
            ca_name=args.ca_name,
            customer_name=args.customer_name,
            peer_public_ip=args.peer_public_ip,
            outer_topology=args.outer_topology,
            outer_gateway_ref=args.outer_gateway_ref,
            service_profile=args.service_profile,
            customer_loopback_ip=args.customer_loopback_ip,
            known_inside_identity=args.known_inside_identity,
            local_subnets=args.local_subnets,
            remote_subnets=args.remote_subnets,
            service_reachable_subnets=args.service_reachable_subnets,
            headend_id=args.headend_id,
            outer_id=args.outer_id,
            encrypt_headend_key=args.encrypt_headend_key,
            headend_key_passphrase=args.headend_key_passphrase,
            encrypt_outer_key=args.encrypt_outer_key,
            outer_key_passphrase=args.outer_key_passphrase,
            days=args.days,
            request_out=Path(args.request_out) if args.request_out else None,
        )
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    if args.command == "serve":
        serve_ca(ca_root=Path(args.ca_root), host=args.host, port=args.port)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
