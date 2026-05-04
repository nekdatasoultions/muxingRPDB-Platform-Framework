from __future__ import annotations

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


def _sanitize(value: str) -> str:
    return "".join(char if char.isalnum() or char in ("-", "_", ".") else "-" for char in value)


def _runtime_identity(value: str) -> str:
    candidate = str(value or "").strip().replace("/", ".")
    return _sanitize(candidate)


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
    mode = str(pki.get("mode") or "reference").strip().lower()
    provider = str(pki.get("provider") or "").strip()
    customer_package_format = str(pki.get("customer_package_format") or "pem_bundle").strip().lower()
    if customer_package_format not in {"pem_bundle"}:
        raise ValueError(f"Unsupported customer package format: {customer_package_format}")

    headend_doc = dict(pki.get("headend") or {})
    customer_pki_doc = dict(pki.get("customer") or {})
    trust_doc = dict(pki.get("trust") or {})

    customer_identity_ref = (
        str(customer_pki_doc.get("identity_ref") or "").strip()
        or str(cgnat.get("outer_identity_ref") or "").strip()
        or f"customer-router/{customer_name}"
    )
    customer_auth_ref = (
        str(customer_pki_doc.get("auth_ref") or "").strip()
        or str(cgnat.get("outer_auth_ref") or "").strip()
        or f"pki/cgnat/customer/{customer_name}"
    )
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
        or f"{customer_name}-customer-outer"
    )

    return {
        "schema_version": 1,
        "customer_name": customer_name,
        "mode": mode,
        "provider": provider,
        "customer_package_format": customer_package_format,
        "ca_common_name": ca_common_name,
        "headend": {
            "identity_ref": headend_identity_ref,
            "auth_ref": headend_auth_ref,
        },
        "customer": {
            "identity_ref": customer_identity_ref,
            "auth_ref": customer_auth_ref,
            "package_name": customer_package_name,
        },
        "trust": {
            "ca_ref": ca_ref,
        },
        "legacy_transport_refs": {
            "outer_identity_ref": str(cgnat.get("outer_identity_ref") or "").strip(),
            "outer_auth_ref": str(cgnat.get("outer_auth_ref") or "").strip(),
        },
    }


def _write_reference_handoff(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    headend_dir = ensure_path_within_cgnat(root / "headend-install")
    customer_dir = ensure_path_within_cgnat(root / "customer-handoff")
    headend_manifest = {
        "material_mode": "reference",
        "identity_ref": spec["headend"]["identity_ref"],
        "auth_ref": spec["headend"]["auth_ref"],
        "ca_ref": spec["trust"]["ca_ref"],
    }
    customer_manifest = {
        "material_mode": "reference",
        "package_name": spec["customer"]["package_name"],
        "package_format": spec["customer_package_format"],
        "identity_ref": spec["customer"]["identity_ref"],
        "auth_ref": spec["customer"]["auth_ref"],
        "ca_ref": spec["trust"]["ca_ref"],
    }
    dump_json(headend_dir / "headend-install-manifest.json", headend_manifest)
    dump_json(customer_dir / "customer-handoff-manifest.json", customer_manifest)
    dump_text(
        customer_dir / "README.md",
        "\n".join(
            [
                "# CGNAT Customer Outer-Tunnel Handoff",
                "",
                f"- Package name: `{spec['customer']['package_name']}`",
                f"- Package format: `{spec['customer_package_format']}`",
                f"- Customer identity ref: `{spec['customer']['identity_ref']}`",
                f"- Customer auth ref: `{spec['customer']['auth_ref']}`",
                f"- Trust CA ref: `{spec['trust']['ca_ref']}`",
                "",
                "This package is reference-only. Resolve the referenced materials before customer-device installation.",
                "",
            ]
        ),
    )
    return {
        "generated_material": False,
        "headend_install_manifest": str(headend_dir / "headend-install-manifest.json"),
        "customer_handoff_manifest": str(customer_dir / "customer-handoff-manifest.json"),
        "customer_handoff_readme": str(customer_dir / "README.md"),
    }


def _write_local_handoff(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    openssl_bin = _find_openssl()
    materials_dir = ensure_path_within_cgnat(root / "generated-materials")
    headend_dir = ensure_path_within_cgnat(root / "headend-install")
    customer_dir = ensure_path_within_cgnat(root / "customer-handoff")
    materials_dir.mkdir(parents=True, exist_ok=True)
    headend_dir.mkdir(parents=True, exist_ok=True)
    customer_dir.mkdir(parents=True, exist_ok=True)

    safe_customer = _sanitize(spec["customer_name"])
    safe_headend = _sanitize(spec["headend"]["identity_ref"])
    safe_customer_identity = _sanitize(spec["customer"]["identity_ref"])

    ca_key = materials_dir / f"{safe_customer}-outer-ca.key"
    ca_crt = materials_dir / f"{safe_customer}-outer-ca.crt"
    headend_key = materials_dir / f"{safe_customer}-headend.key"
    headend_csr = materials_dir / f"{safe_customer}-headend.csr"
    headend_crt = materials_dir / f"{safe_customer}-headend.crt"
    headend_ext = materials_dir / f"{safe_customer}-headend.ext"
    customer_key = customer_dir / "customer-outer.key"
    customer_csr = materials_dir / f"{safe_customer}-customer.csr"
    customer_crt = customer_dir / "customer-outer.crt"
    customer_ext = materials_dir / f"{safe_customer}-customer.ext"
    customer_ca = customer_dir / "outer-ca.crt"

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
        f"/CN={spec['ca_common_name']}",
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
        f"/CN={safe_headend}",
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
        str(customer_key),
        "-out",
        str(customer_csr),
        "-subj",
        f"/CN={safe_customer_identity}",
    )
    dump_text(
        customer_ext,
        "\n".join(
            [
                "basicConstraints=CA:FALSE",
                "keyUsage=digitalSignature,keyEncipherment",
                "extendedKeyUsage=serverAuth,clientAuth",
                f"subjectAltName=DNS:{_runtime_identity(spec['customer']['identity_ref'])}",
                "",
            ]
        ),
    )
    _run(
        openssl_bin,
        "x509",
        "-req",
        "-in",
        str(customer_csr),
        "-CA",
        str(ca_crt),
        "-CAkey",
        str(ca_key),
        "-CAcreateserial",
        "-out",
        str(customer_crt),
        "-days",
        "365",
        "-sha256",
        "-extfile",
        str(customer_ext),
    )
    shutil.copyfile(ca_crt, customer_ca)

    headend_manifest = {
        "material_mode": "local_generate",
        "identity_ref": spec["headend"]["identity_ref"],
        "auth_ref": spec["headend"]["auth_ref"],
        "ca_ref": spec["trust"]["ca_ref"],
        "certificate_path": str(headend_crt),
        "private_key_path": str(headend_key),
        "ca_certificate_path": str(ca_crt),
    }
    customer_manifest = {
        "material_mode": "local_generate",
        "package_name": spec["customer"]["package_name"],
        "package_format": spec["customer_package_format"],
        "identity_ref": spec["customer"]["identity_ref"],
        "auth_ref": spec["customer"]["auth_ref"],
        "ca_ref": spec["trust"]["ca_ref"],
        "certificate_path": str(customer_crt),
        "private_key_path": str(customer_key),
        "ca_certificate_path": str(customer_ca),
        "bundle_password_ref": f"generated://{spec['customer_name']}/customer-handoff-password",
        "bundle_password": secrets.token_urlsafe(18),
    }
    dump_json(headend_dir / "headend-install-manifest.json", headend_manifest)
    dump_json(customer_dir / "customer-handoff-manifest.json", customer_manifest)
    dump_text(
        customer_dir / "README.md",
        "\n".join(
            [
                "# CGNAT Customer Outer-Tunnel Handoff",
                "",
                f"- Package name: `{spec['customer']['package_name']}`",
                f"- Package format: `{spec['customer_package_format']}`",
                f"- Customer identity ref: `{spec['customer']['identity_ref']}`",
                f"- Customer auth ref: `{spec['customer']['auth_ref']}`",
                f"- Trust CA ref: `{spec['trust']['ca_ref']}`",
                "",
                "Files included in this handoff package:",
                "- `customer-outer.crt`",
                "- `customer-outer.key`",
                "- `outer-ca.crt`",
                "- `customer-handoff-manifest.json`",
                "",
                "This package was locally generated for lab or test-bed use.",
                "",
            ]
        ),
    )
    return {
        "generated_material": True,
        "openssl_path": openssl_bin,
        "headend_install_manifest": str(headend_dir / "headend-install-manifest.json"),
        "customer_handoff_manifest": str(customer_dir / "customer-handoff-manifest.json"),
        "customer_handoff_readme": str(customer_dir / "README.md"),
        "headend_certificate_path": str(headend_crt),
        "headend_private_key_path": str(headend_key),
        "customer_certificate_path": str(customer_crt),
        "customer_private_key_path": str(customer_key),
        "ca_certificate_path": str(ca_crt),
    }


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
        "customer_package_format": spec["customer_package_format"],
        "headend": dict(spec["headend"]),
        "customer_handoff": {
            "package_name": spec["customer"]["package_name"],
            "identity_ref": spec["customer"]["identity_ref"],
            "auth_ref": spec["customer"]["auth_ref"],
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
    else:
        artifacts = _write_reference_handoff(root, spec)

    review.update(
        {
            "status": "ready_for_review",
            "ready_for_review": True,
            "generated_material": artifacts.get("generated_material", False),
            "artifacts": artifacts,
            "notes": [
                "The shared provisioning flow remains platform-side only; customer-device installation stays outside this scope.",
                "Head-end material is resolved or generated here, and customer-device material is emitted as a handoff package.",
            ],
        }
    )
    return review
