from __future__ import annotations

import hashlib
import secrets
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cgnat.bundle import dump_json, dump_text, ensure_path_within_cgnat


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _customer_doc(request_doc: dict[str, Any]) -> dict[str, Any]:
    return dict(request_doc.get("customer") or {})


def _transport_doc(request_doc: dict[str, Any]) -> dict[str, Any]:
    return dict((_customer_doc(request_doc).get("transport") or {}))


def _cgnat_doc(request_doc: dict[str, Any]) -> dict[str, Any]:
    return dict((_transport_doc(request_doc).get("cgnat") or {}))


def _pki_doc(request_doc: dict[str, Any]) -> dict[str, Any]:
    return dict((_cgnat_doc(request_doc).get("pki") or {}))


def _outer_topology(request_doc: dict[str, Any]) -> str:
    topology = str((_cgnat_doc(request_doc).get("outer_topology") or "")).strip().lower().replace("-", "_")
    return topology or "per_customer_outer"


def _sanitize(value: str) -> str:
    return "".join(char if char.isalnum() or char in ("-", "_", ".") else "-" for char in value)


def _runtime_identity(value: str) -> str:
    candidate = str(value or "").strip().replace("/", ".")
    return _sanitize(candidate)


def _subject_common_name(value: str, *, max_length: int = 64) -> str:
    candidate = _runtime_identity(value)
    if len(candidate) <= max_length:
        return candidate
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:8]
    keep = max_length - len(digest) - 1
    return f"{candidate[:keep]}-{digest}"


def _find_openssl() -> str:
    candidates = [
        shutil.which("openssl"),
        r"C:\Program Files\OpenSSL-Win64\bin\openssl.exe",
        r"C:\Program Files\Git\usr\bin\openssl.exe",
        r"C:\Program Files\Git\mingw64\bin\openssl.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(Path(candidate))
    raise FileNotFoundError("Unable to locate an openssl binary for CGNAT PKI material generation.")


def _run(openssl_bin: str, *args: str) -> None:
    completed = subprocess.run(
        [openssl_bin, *args],
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"openssl command failed: {' '.join(args)}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


def resolve_cgnat_pki_spec(request_doc: dict[str, Any]) -> dict[str, Any]:
    customer = _customer_doc(request_doc)
    cgnat = _cgnat_doc(request_doc)
    pki = _pki_doc(request_doc)

    customer_name = str(customer.get("name") or "").strip()
    outer_topology = _outer_topology(request_doc)
    outer_gateway_ref = str(cgnat.get("outer_gateway_ref") or "").strip()
    mode = str(pki.get("mode") or "reference").strip().lower()
    provider = str(pki.get("provider") or "").strip()
    customer_package_format = str(pki.get("customer_package_format") or "pem_bundle").strip().lower()
    if customer_package_format not in {"pem_bundle"}:
        raise ValueError(f"Unsupported customer package format: {customer_package_format}")

    headend_doc = dict(pki.get("headend") or {})
    customer_pki_doc = dict(pki.get("customer") or {})
    gateway_pki_doc = dict(pki.get("gateway") or {})
    trust_doc = dict(pki.get("trust") or {})

    customer_identity_ref = str(customer_pki_doc.get("identity_ref") or "").strip()
    customer_auth_ref = str(customer_pki_doc.get("auth_ref") or "").strip()
    if outer_topology != "shared_isp_gateway":
        customer_identity_ref = (
            customer_identity_ref
            or str(cgnat.get("outer_identity_ref") or "").strip()
            or f"customer-router/{customer_name}"
        )
        customer_auth_ref = (
            customer_auth_ref
            or str(cgnat.get("outer_auth_ref") or "").strip()
            or f"pki/cgnat/customer/{customer_name}"
        )
    else:
        customer_identity_ref = customer_identity_ref or f"customer-inner/{customer_name}"
        customer_auth_ref = customer_auth_ref or f"inner-psk/{customer_name}"
    headend_identity_ref = (
        str(headend_doc.get("identity_ref") or "").strip()
        or f"cgnat-head-end/{customer_name}"
    )
    headend_auth_ref = (
        str(headend_doc.get("auth_ref") or "").strip()
        or f"pki/cgnat/headend/{customer_name}"
    )
    ca_ref = str(trust_doc.get("ca_ref") or "").strip() or f"pki/cgnat/ca/{customer_name}"
    ca_common_name = str(pki.get("ca_common_name") or "").strip() or f"{customer_name}-outer-ca"
    customer_package_name = (
        str(customer_pki_doc.get("package_name") or "").strip()
        or (
            f"{customer_name}-customer-inner"
            if outer_topology == "shared_isp_gateway"
            else f"{customer_name}-customer-outer"
        )
    )
    gateway_identity_ref = (
        str(gateway_pki_doc.get("identity_ref") or "").strip()
        or str(cgnat.get("outer_identity_ref") or "").strip()
        or f"{outer_gateway_ref or 'isp-gateway'}/{customer_name}"
    )
    gateway_auth_ref = (
        str(gateway_pki_doc.get("auth_ref") or "").strip()
        or str(cgnat.get("outer_auth_ref") or "").strip()
        or f"pki/cgnat/gateway/{outer_gateway_ref or customer_name}"
    )
    gateway_package_name = (
        str(gateway_pki_doc.get("package_name") or "").strip()
        or f"{customer_name}-{_sanitize(outer_gateway_ref or 'isp-gateway')}-outer-gateway"
    )

    return {
        "schema_version": 1,
        "customer_name": customer_name,
        "mode": mode,
        "provider": provider,
        "customer_package_format": customer_package_format,
        "outer_topology": outer_topology,
        "outer_gateway_ref": outer_gateway_ref,
        "ca_common_name": ca_common_name,
        "headend": {
            "identity_ref": headend_identity_ref,
            "auth_ref": headend_auth_ref,
            "cert_ref": str(headend_doc.get("cert_ref") or "").strip(),
            "private_key_secret_ref": str(headend_doc.get("private_key_secret_ref") or "").strip(),
            "private_key_passphrase_secret_ref": str(
                headend_doc.get("private_key_passphrase_secret_ref") or ""
            ).strip(),
        },
        "customer": {
            "identity_ref": customer_identity_ref,
            "auth_ref": customer_auth_ref,
            "package_name": customer_package_name,
            "cert_ref": str(customer_pki_doc.get("cert_ref") or "").strip(),
            "private_key_secret_ref": str(customer_pki_doc.get("private_key_secret_ref") or "").strip(),
            "private_key_passphrase_secret_ref": str(
                customer_pki_doc.get("private_key_passphrase_secret_ref") or ""
            ).strip(),
        },
        "gateway": {
            "identity_ref": gateway_identity_ref,
            "auth_ref": gateway_auth_ref,
            "package_name": gateway_package_name,
            "cert_ref": str(gateway_pki_doc.get("cert_ref") or "").strip(),
            "private_key_secret_ref": str(gateway_pki_doc.get("private_key_secret_ref") or "").strip(),
            "private_key_passphrase_secret_ref": str(
                gateway_pki_doc.get("private_key_passphrase_secret_ref") or ""
            ).strip(),
        },
        "trust": {
            "ca_ref": ca_ref,
        },
        "legacy_transport_refs": {
            "outer_identity_ref": str(cgnat.get("outer_identity_ref") or "").strip(),
            "outer_auth_ref": str(cgnat.get("outer_auth_ref") or "").strip(),
        },
    }


def _required_ref(value: str, label: str) -> str:
    if not str(value or "").strip():
        raise ValueError(f"CGNAT provided PKI material is missing {label}")
    return str(value).strip()


def _local_material_path(material_ref: str) -> Path | None:
    ref = str(material_ref or "").strip()
    if not ref:
        return None
    if ref.startswith("file://"):
        raw_path = ref[len("file://") :]
        if raw_path.startswith("/") and len(raw_path) >= 4 and raw_path[2] == ":":
            raw_path = raw_path[1:]
        candidate = Path(raw_path)
    else:
        candidate = Path(ref)
    if candidate.exists():
        return candidate.resolve()
    if ref.startswith("file://"):
        raise FileNotFoundError(f"CGNAT provided PKI file ref does not exist: {material_ref}")
    return None


def _stage_material_ref(material_ref: str, destination: Path, *, label: str) -> dict[str, Any]:
    ref = _required_ref(material_ref, label)
    staged: dict[str, Any] = {
        "ref": ref,
        "resolved_local_file": False,
    }
    local_path = _local_material_path(ref)
    if local_path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, destination)
        staged.update(
            {
                "resolved_local_file": True,
                "source_path": str(local_path),
                "staged_path": str(destination),
            }
        )
    return staged


def _write_provided_handoff(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    handoff_key, recipient_type, handoff_spec = _outer_handoff_target(spec)
    headend_dir = ensure_path_within_cgnat(root / "headend-install")
    handoff_dir = ensure_path_within_cgnat(root / f"{handoff_key}-handoff")
    headend_dir.mkdir(parents=True, exist_ok=True)
    handoff_dir.mkdir(parents=True, exist_ok=True)

    trust_ref = _required_ref(spec["trust"]["ca_ref"], "trust.ca_ref")
    headend_cert = _stage_material_ref(
        spec["headend"].get("cert_ref") or "",
        headend_dir / "headend.crt",
        label="headend.cert_ref",
    )
    headend_key = _stage_material_ref(
        spec["headend"].get("private_key_secret_ref") or spec["headend"].get("auth_ref") or "",
        headend_dir / "headend.key",
        label="headend.private_key_secret_ref",
    )
    headend_ca = _stage_material_ref(
        trust_ref,
        headend_dir / "outer-ca.crt",
        label="trust.ca_ref",
    )
    outer_cert = _stage_material_ref(
        handoff_spec.get("cert_ref") or "",
        handoff_dir / f"{handoff_key}-outer.crt",
        label=f"{handoff_key}.cert_ref",
    )
    outer_key = _stage_material_ref(
        handoff_spec.get("private_key_secret_ref") or handoff_spec.get("auth_ref") or "",
        handoff_dir / f"{handoff_key}-outer.key",
        label=f"{handoff_key}.private_key_secret_ref",
    )
    outer_ca = _stage_material_ref(
        trust_ref,
        handoff_dir / "outer-ca.crt",
        label="trust.ca_ref",
    )

    headend_passphrase = {}
    if spec["headend"].get("private_key_passphrase_secret_ref"):
        headend_passphrase = _stage_material_ref(
            spec["headend"]["private_key_passphrase_secret_ref"],
            headend_dir / "headend-key.passphrase",
            label="headend.private_key_passphrase_secret_ref",
        )
    outer_passphrase = {}
    if handoff_spec.get("private_key_passphrase_secret_ref"):
        outer_passphrase = _stage_material_ref(
            handoff_spec["private_key_passphrase_secret_ref"],
            handoff_dir / f"{handoff_key}-outer-key.passphrase",
            label=f"{handoff_key}.private_key_passphrase_secret_ref",
        )

    headend_manifest = {
        "material_mode": "provided",
        "identity_ref": spec["headend"]["identity_ref"],
        "auth_ref": spec["headend"]["auth_ref"],
        "ca_ref": spec["trust"]["ca_ref"],
        "certificate_ref": headend_cert["ref"],
        "private_key_ref": headend_key["ref"],
        "ca_certificate_ref": headend_ca["ref"],
        "certificate_path": headend_cert.get("staged_path"),
        "private_key_path": headend_key.get("staged_path"),
        "ca_certificate_path": headend_ca.get("staged_path"),
        "private_key_passphrase_ref": headend_passphrase.get("ref", ""),
        "private_key_passphrase_path": headend_passphrase.get("staged_path", ""),
    }
    outer_manifest = {
        "material_mode": "provided",
        "package_name": handoff_spec["package_name"],
        "package_format": spec["customer_package_format"],
        "identity_ref": handoff_spec["identity_ref"],
        "auth_ref": handoff_spec["auth_ref"],
        "ca_ref": spec["trust"]["ca_ref"],
        "recipient_type": recipient_type,
        "outer_topology": spec["outer_topology"],
        "outer_gateway_ref": spec["outer_gateway_ref"],
        "certificate_ref": outer_cert["ref"],
        "private_key_ref": outer_key["ref"],
        "ca_certificate_ref": outer_ca["ref"],
        "certificate_path": outer_cert.get("staged_path"),
        "private_key_path": outer_key.get("staged_path"),
        "ca_certificate_path": outer_ca.get("staged_path"),
        "private_key_passphrase_ref": outer_passphrase.get("ref", ""),
        "private_key_passphrase_path": outer_passphrase.get("staged_path", ""),
    }
    dump_json(headend_dir / "headend-install-manifest.json", headend_manifest)
    dump_json(handoff_dir / f"{handoff_key}-handoff-manifest.json", outer_manifest)
    dump_text(
        handoff_dir / "README.md",
        "\n".join(
            [
                "# CGNAT Outer-Tunnel Handoff",
                "",
                f"- Recipient type: `{recipient_type}`",
                f"- Package name: `{handoff_spec['package_name']}`",
                f"- Package format: `{spec['customer_package_format']}`",
                f"- Identity ref: `{handoff_spec['identity_ref']}`",
                f"- Auth ref: `{handoff_spec['auth_ref']}`",
                f"- Trust CA ref: `{spec['trust']['ca_ref']}`",
                "",
                "Files included in this handoff package when refs resolve locally:",
                f"- `{handoff_key}-outer.crt`",
                f"- `{handoff_key}-outer.key`",
                "- `outer-ca.crt`",
                f"- `{handoff_key}-handoff-manifest.json`",
                "",
                "This package consumes provided certificate material. It does not mint a local CGNAT CA.",
                "",
            ]
        ),
    )
    artifacts = {
        "generated_material": False,
        "provided_material": True,
        "headend_install_manifest": str(headend_dir / "headend-install-manifest.json"),
        "outer_handoff_manifest": str(handoff_dir / f"{handoff_key}-handoff-manifest.json"),
        "outer_handoff_readme": str(handoff_dir / "README.md"),
        "headend_certificate_ref": headend_cert["ref"],
        "headend_private_key_ref": headend_key["ref"],
        "outer_certificate_ref": outer_cert["ref"],
        "outer_private_key_ref": outer_key["ref"],
        "ca_certificate_ref": headend_ca["ref"],
    }
    if headend_cert.get("staged_path"):
        artifacts["headend_certificate_path"] = headend_cert["staged_path"]
    if headend_key.get("staged_path"):
        artifacts["headend_private_key_path"] = headend_key["staged_path"]
    if outer_cert.get("staged_path"):
        artifacts["outer_certificate_path"] = outer_cert["staged_path"]
    if outer_key.get("staged_path"):
        artifacts["outer_private_key_path"] = outer_key["staged_path"]
    if headend_ca.get("staged_path"):
        artifacts["ca_certificate_path"] = headend_ca["staged_path"]
    if recipient_type == "customer_device":
        artifacts["customer_handoff_manifest"] = artifacts["outer_handoff_manifest"]
        artifacts["customer_handoff_readme"] = artifacts["outer_handoff_readme"]
        artifacts["customer_certificate_ref"] = outer_cert["ref"]
        artifacts["customer_private_key_ref"] = outer_key["ref"]
        if outer_cert.get("staged_path"):
            artifacts["customer_certificate_path"] = outer_cert["staged_path"]
        if outer_key.get("staged_path"):
            artifacts["customer_private_key_path"] = outer_key["staged_path"]
    else:
        artifacts["gateway_handoff_manifest"] = artifacts["outer_handoff_manifest"]
        artifacts["gateway_handoff_readme"] = artifacts["outer_handoff_readme"]
        artifacts["gateway_certificate_ref"] = outer_cert["ref"]
        artifacts["gateway_private_key_ref"] = outer_key["ref"]
        if outer_cert.get("staged_path"):
            artifacts["gateway_certificate_path"] = outer_cert["staged_path"]
        if outer_key.get("staged_path"):
            artifacts["gateway_private_key_path"] = outer_key["staged_path"]
    return artifacts


def _outer_handoff_target(spec: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    if spec["outer_topology"] == "shared_isp_gateway":
        return "gateway", "isp_gateway", dict(spec["gateway"])
    return "customer", "customer_device", dict(spec["customer"])


def _write_reference_handoff(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    handoff_key, recipient_type, handoff_spec = _outer_handoff_target(spec)
    headend_dir = ensure_path_within_cgnat(root / "headend-install")
    handoff_dir = ensure_path_within_cgnat(root / f"{handoff_key}-handoff")
    headend_manifest = {
        "material_mode": "reference",
        "identity_ref": spec["headend"]["identity_ref"],
        "auth_ref": spec["headend"]["auth_ref"],
        "ca_ref": spec["trust"]["ca_ref"],
    }
    outer_manifest = {
        "material_mode": "reference",
        "package_name": handoff_spec["package_name"],
        "package_format": spec["customer_package_format"],
        "identity_ref": handoff_spec["identity_ref"],
        "auth_ref": handoff_spec["auth_ref"],
        "ca_ref": spec["trust"]["ca_ref"],
        "recipient_type": recipient_type,
        "outer_topology": spec["outer_topology"],
        "outer_gateway_ref": spec["outer_gateway_ref"],
    }
    dump_json(headend_dir / "headend-install-manifest.json", headend_manifest)
    dump_json(handoff_dir / f"{handoff_key}-handoff-manifest.json", outer_manifest)
    dump_text(
        handoff_dir / "README.md",
        "\n".join(
            [
                "# CGNAT Outer-Tunnel Handoff",
                "",
                f"- Recipient type: `{recipient_type}`",
                f"- Package name: `{handoff_spec['package_name']}`",
                f"- Package format: `{spec['customer_package_format']}`",
                f"- Identity ref: `{handoff_spec['identity_ref']}`",
                f"- Auth ref: `{handoff_spec['auth_ref']}`",
                f"- Trust CA ref: `{spec['trust']['ca_ref']}`",
                "",
                "This package is reference-only. Resolve the referenced materials before customer-device installation.",
                "",
            ]
        ),
    )
    artifacts = {
        "generated_material": False,
        "headend_install_manifest": str(headend_dir / "headend-install-manifest.json"),
        "outer_handoff_manifest": str(handoff_dir / f"{handoff_key}-handoff-manifest.json"),
        "outer_handoff_readme": str(handoff_dir / "README.md"),
    }
    if recipient_type == "customer_device":
        artifacts["customer_handoff_manifest"] = artifacts["outer_handoff_manifest"]
        artifacts["customer_handoff_readme"] = artifacts["outer_handoff_readme"]
    else:
        artifacts["gateway_handoff_manifest"] = artifacts["outer_handoff_manifest"]
        artifacts["gateway_handoff_readme"] = artifacts["outer_handoff_readme"]
    return artifacts


def _write_local_handoff(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    openssl_bin = _find_openssl()
    materials_dir = ensure_path_within_cgnat(root / "generated-materials")
    headend_dir = ensure_path_within_cgnat(root / "headend-install")
    handoff_key, recipient_type, handoff_spec = _outer_handoff_target(spec)
    handoff_dir = ensure_path_within_cgnat(root / f"{handoff_key}-handoff")
    materials_dir.mkdir(parents=True, exist_ok=True)
    headend_dir.mkdir(parents=True, exist_ok=True)
    handoff_dir.mkdir(parents=True, exist_ok=True)

    safe_customer = _sanitize(spec["customer_name"])
    safe_headend = _sanitize(spec["headend"]["identity_ref"])
    safe_handoff_identity = _sanitize(handoff_spec["identity_ref"])

    ca_key = materials_dir / f"{safe_customer}-outer-ca.key"
    ca_crt = materials_dir / f"{safe_customer}-outer-ca.crt"
    headend_key = materials_dir / f"{safe_customer}-headend.key"
    headend_csr = materials_dir / f"{safe_customer}-headend.csr"
    headend_crt = materials_dir / f"{safe_customer}-headend.crt"
    headend_ext = materials_dir / f"{safe_customer}-headend.ext"
    outer_key = handoff_dir / f"{handoff_key}-outer.key"
    outer_csr = materials_dir / f"{safe_customer}-{handoff_key}.csr"
    outer_crt = handoff_dir / f"{handoff_key}-outer.crt"
    outer_ext = materials_dir / f"{safe_customer}-{handoff_key}.ext"
    outer_ca = handoff_dir / "outer-ca.crt"

    _run(
        openssl_bin,
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(ca_key),
        "-out",
        str(ca_crt),
        "-days",
        "365",
        "-subj",
        f"/CN={_subject_common_name(spec['ca_common_name'])}",
    )
    _run(
        openssl_bin,
        "req",
        "-new",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(headend_key),
        "-out",
        str(headend_csr),
        "-subj",
        f"/CN={_subject_common_name(safe_headend)}",
    )
    dump_text(
        headend_ext,
        "\n".join(
            [
                "basicConstraints=CA:FALSE",
                "keyUsage=digitalSignature,keyEncipherment",
                "extendedKeyUsage=serverAuth,clientAuth",
                f"subjectAltName=DNS:{_runtime_identity(spec['headend']['identity_ref'])}",
                "",
            ]
        ),
    )
    _run(
        openssl_bin,
        "x509",
        "-req",
        "-in",
        str(headend_csr),
        "-CA",
        str(ca_crt),
        "-CAkey",
        str(ca_key),
        "-CAcreateserial",
        "-out",
        str(headend_crt),
        "-days",
        "365",
        "-sha256",
        "-extfile",
        str(headend_ext),
    )
    _run(
        openssl_bin,
        "req",
        "-new",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(outer_key),
        "-out",
        str(outer_csr),
        "-subj",
        f"/CN={_subject_common_name(safe_handoff_identity)}",
    )
    dump_text(
        outer_ext,
        "\n".join(
            [
                "basicConstraints=CA:FALSE",
                "keyUsage=digitalSignature,keyEncipherment",
                "extendedKeyUsage=serverAuth,clientAuth",
                f"subjectAltName=DNS:{_runtime_identity(handoff_spec['identity_ref'])}",
                "",
            ]
        ),
    )
    _run(
        openssl_bin,
        "x509",
        "-req",
        "-in",
        str(outer_csr),
        "-CA",
        str(ca_crt),
        "-CAkey",
        str(ca_key),
        "-CAcreateserial",
        "-out",
        str(outer_crt),
        "-days",
        "365",
        "-sha256",
        "-extfile",
        str(outer_ext),
    )
    shutil.copyfile(ca_crt, outer_ca)

    headend_manifest = {
        "material_mode": "local_generate",
        "identity_ref": spec["headend"]["identity_ref"],
        "auth_ref": spec["headend"]["auth_ref"],
        "ca_ref": spec["trust"]["ca_ref"],
        "certificate_path": str(headend_crt),
        "private_key_path": str(headend_key),
        "ca_certificate_path": str(ca_crt),
    }
    outer_manifest = {
        "material_mode": "local_generate",
        "package_name": handoff_spec["package_name"],
        "package_format": spec["customer_package_format"],
        "identity_ref": handoff_spec["identity_ref"],
        "auth_ref": handoff_spec["auth_ref"],
        "ca_ref": spec["trust"]["ca_ref"],
        "recipient_type": recipient_type,
        "outer_topology": spec["outer_topology"],
        "outer_gateway_ref": spec["outer_gateway_ref"],
        "certificate_path": str(outer_crt),
        "private_key_path": str(outer_key),
        "ca_certificate_path": str(outer_ca),
        "bundle_password_ref": f"generated://{spec['customer_name']}/{handoff_key}-handoff-password",
        "bundle_password": secrets.token_urlsafe(18),
    }
    dump_json(headend_dir / "headend-install-manifest.json", headend_manifest)
    dump_json(handoff_dir / f"{handoff_key}-handoff-manifest.json", outer_manifest)
    dump_text(
        handoff_dir / "README.md",
        "\n".join(
            [
                "# CGNAT Outer-Tunnel Handoff",
                "",
                f"- Recipient type: `{recipient_type}`",
                f"- Package name: `{handoff_spec['package_name']}`",
                f"- Package format: `{spec['customer_package_format']}`",
                f"- Identity ref: `{handoff_spec['identity_ref']}`",
                f"- Auth ref: `{handoff_spec['auth_ref']}`",
                f"- Trust CA ref: `{spec['trust']['ca_ref']}`",
                "",
                "Files included in this handoff package:",
                f"- `{handoff_key}-outer.crt`",
                f"- `{handoff_key}-outer.key`",
                "- `outer-ca.crt`",
                f"- `{handoff_key}-handoff-manifest.json`",
                "",
                "This package was locally generated for lab or test-bed use.",
                "",
            ]
        ),
    )
    artifacts = {
        "generated_material": True,
        "openssl_path": openssl_bin,
        "headend_install_manifest": str(headend_dir / "headend-install-manifest.json"),
        "outer_handoff_manifest": str(handoff_dir / f"{handoff_key}-handoff-manifest.json"),
        "outer_handoff_readme": str(handoff_dir / "README.md"),
        "headend_certificate_path": str(headend_crt),
        "headend_private_key_path": str(headend_key),
        "outer_certificate_path": str(outer_crt),
        "outer_private_key_path": str(outer_key),
        "ca_certificate_path": str(ca_crt),
    }
    if recipient_type == "customer_device":
        artifacts["customer_handoff_manifest"] = artifacts["outer_handoff_manifest"]
        artifacts["customer_handoff_readme"] = artifacts["outer_handoff_readme"]
        artifacts["customer_certificate_path"] = str(outer_crt)
        artifacts["customer_private_key_path"] = str(outer_key)
    else:
        artifacts["gateway_handoff_manifest"] = artifacts["outer_handoff_manifest"]
        artifacts["gateway_handoff_readme"] = artifacts["outer_handoff_readme"]
        artifacts["gateway_certificate_path"] = str(outer_crt)
        artifacts["gateway_private_key_path"] = str(outer_key)
    return artifacts


def materialize_cgnat_pki(request_doc: dict[str, Any], output_dir: str | Path) -> dict[str, Any]:
    root = ensure_path_within_cgnat(output_dir)
    spec = resolve_cgnat_pki_spec(request_doc)

    review: dict[str, Any] = {
        "schema_version": 1,
        "surface": "pki",
        "generated_at": _now_utc(),
        "customer_name": spec["customer_name"],
        "mode": spec["mode"],
        "provider": spec["provider"],
        "outer_topology": spec["outer_topology"],
        "outer_gateway_ref": spec["outer_gateway_ref"],
        "customer_package_format": spec["customer_package_format"],
        "headend": dict(spec["headend"]),
        "customer_handoff": {
            "package_name": spec["customer"]["package_name"],
            "identity_ref": spec["customer"]["identity_ref"],
            "auth_ref": spec["customer"]["auth_ref"],
        },
        "gateway_handoff": {
            "package_name": spec["gateway"]["package_name"],
            "identity_ref": spec["gateway"]["identity_ref"],
            "auth_ref": spec["gateway"]["auth_ref"],
        },
        "trust": dict(spec["trust"]),
        "artifacts_root": str(root),
    }

    if spec["mode"] == "provider_api":
        review.update(
            {
                "status": "provider_integration_required",
                "ready_for_review": False,
                "notes": [
                    "provider_api mode is modeled but not implemented yet.",
                    "Use reference or local_generate until a real PKI provider adapter is added.",
                ],
            }
        )
        return review

    if spec["mode"] == "local_generate":
        artifacts = _write_local_handoff(root, spec)
    elif spec["mode"] == "provided":
        artifacts = _write_provided_handoff(root, spec)
    else:
        artifacts = _write_reference_handoff(root, spec)

    review.update(
        {
            "status": "ready_for_review",
            "ready_for_review": True,
            "generated_material": artifacts.get("generated_material", False),
            "artifacts": artifacts,
            "outer_handoff": {
                "recipient_type": "isp_gateway" if spec["outer_topology"] == "shared_isp_gateway" else "customer_device",
                "package_name": (
                    spec["gateway"]["package_name"]
                    if spec["outer_topology"] == "shared_isp_gateway"
                    else spec["customer"]["package_name"]
                ),
                "identity_ref": (
                    spec["gateway"]["identity_ref"]
                    if spec["outer_topology"] == "shared_isp_gateway"
                    else spec["customer"]["identity_ref"]
                ),
                "auth_ref": (
                    spec["gateway"]["auth_ref"]
                    if spec["outer_topology"] == "shared_isp_gateway"
                    else spec["customer"]["auth_ref"]
                ),
                "manifest": artifacts.get("outer_handoff_manifest"),
                "readme": artifacts.get("outer_handoff_readme"),
            },
            "notes": [
                "The shared provisioning flow remains platform-side only; customer-device installation stays outside this scope.",
                "Head-end material is resolved or generated here, and customer-device material is emitted as a handoff package.",
            ],
        }
    )
    if spec["outer_topology"] == "shared_isp_gateway":
        review["customer_handoff"] = {
            "package_name": f"{spec['customer_name']}-inner-only",
            "identity_ref": spec["customer"]["identity_ref"],
            "auth_ref": spec["customer"]["auth_ref"],
            "outer_material_required": False,
            "recipient_type": "customer_device",
        }
        review["gateway_handoff"].update(
            {
                "outer_material_required": True,
                "recipient_type": "isp_gateway",
                "manifest": artifacts.get("gateway_handoff_manifest") or artifacts.get("outer_handoff_manifest"),
                "readme": artifacts.get("gateway_handoff_readme") or artifacts.get("outer_handoff_readme"),
            }
        )
    else:
        review["customer_handoff"].update(
            {
                "outer_material_required": True,
                "recipient_type": "customer_device",
                "manifest": artifacts.get("customer_handoff_manifest") or artifacts.get("outer_handoff_manifest"),
                "readme": artifacts.get("customer_handoff_readme") or artifacts.get("outer_handoff_readme"),
            }
        )
    return review
