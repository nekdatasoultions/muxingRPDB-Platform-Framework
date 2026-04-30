from __future__ import annotations

import argparse
import secrets
import shutil
import subprocess
import sys
from pathlib import Path


def _framework_src_root() -> Path:
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent.parent / "framework" / "src"


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
    raise FileNotFoundError("Unable to locate an openssl binary for demo material generation.")


def _run(openssl_bin: str, *args: str) -> None:
    subprocess.run([openssl_bin, *args], check=True, capture_output=True, text=True)


def _sanitize(name: str) -> str:
    return "".join(char if char.isalnum() or char in ("-", "_") else "-" for char in name)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _runtime_outer_identity(value: str) -> str:
    candidate = str(value or "").strip()
    sanitized = candidate.replace("/", ".")
    return "".join(char if char.isalnum() or char in ("-", ".") else "-" for char in sanitized)


def _device_outer_identity(bundle: dict, device: dict) -> str:
    explicit = str(device.get("outer_tunnel_identity_ref") or "").strip()
    if explicit:
        return explicit
    return f"{device['router_role']}/{bundle['operations']['environment_name']}/{bundle['sot']['customer_id']}"


def _router_outer_certificate_ref(bundle: dict, role: str) -> str:
    certificates = dict(bundle["operations"].get("certificates") or {})
    per_router = dict(certificates.get("customer_router_outer_client_cert_refs") or {})
    explicit = str(per_router.get(role) or "").strip()
    if explicit:
        return explicit
    return f"local-pki://{bundle['operations']['environment_name']}/{role}-outer-client"


def main() -> int:
    sys.path.insert(0, str(_framework_src_root()))

    from cgnat.bundle import dump_json, dump_text, ensure_path_within_cgnat, load_bundle

    parser = argparse.ArgumentParser(description="Materialize demo PKI and inner-VPN secret inputs for Scenario 1.")
    parser.add_argument("bundle_json", help="Path to the deployment bundle JSON.")
    parser.add_argument("output_dir", help="Directory to write the generated demo materials.")
    args = parser.parse_args()

    bundle = load_bundle(args.bundle_json)
    output_dir = ensure_path_within_cgnat(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    openssl_bin = _find_openssl()
    service_id = bundle["sot"]["service_id"]
    safe_service_id = _sanitize(service_id)
    head_end_identity = _runtime_outer_identity(f"cgnat-head-end/{service_id}")
    customer_router_outer_materials: list[dict[str, str]] = []

    pki_dir = output_dir / "pki"
    secrets_dir = output_dir / "secrets"
    pki_dir.mkdir(parents=True, exist_ok=True)
    secrets_dir.mkdir(parents=True, exist_ok=True)

    ca_key = pki_dir / f"{safe_service_id}-outer-ca.key"
    ca_crt = pki_dir / f"{safe_service_id}-outer-ca.crt"
    head_key = pki_dir / f"{safe_service_id}-head-end.key"
    head_csr = pki_dir / f"{safe_service_id}-head-end.csr"
    head_crt = pki_dir / f"{safe_service_id}-head-end.crt"
    head_ext = pki_dir / f"{safe_service_id}-head-end.ext"
    inner_vpn_materials: list[dict[str, str]] = []

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
        f"/CN={safe_service_id}-outer-ca",
    )
    _run(
        openssl_bin,
        "req",
        "-new",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(head_key),
        "-out",
        str(head_csr),
        "-subj",
        f"/CN={safe_service_id}-head-end",
    )
    _write_text(
        head_ext,
        "\n".join(
            [
                "basicConstraints=CA:FALSE",
                "keyUsage=digitalSignature,keyEncipherment",
                "extendedKeyUsage=serverAuth,clientAuth",
                f"subjectAltName=DNS:{head_end_identity}",
                "",
            ]
        ),
    )
    _run(
        openssl_bin,
        "x509",
        "-req",
        "-in",
        str(head_csr),
        "-CA",
        str(ca_crt),
        "-CAkey",
        str(ca_key),
        "-CAcreateserial",
        "-out",
        str(head_crt),
        "-days",
        "365",
        "-sha256",
        "-extfile",
        str(head_ext),
    )
    for device in bundle["sot"]["customer_devices"]:
        router_role = str(device["router_role"])
        role_slug = _sanitize(router_role)
        router_identity = _runtime_outer_identity(_device_outer_identity(bundle, device))
        router_key = pki_dir / f"{safe_service_id}-{role_slug}-outer.key"
        router_csr = pki_dir / f"{safe_service_id}-{role_slug}-outer.csr"
        router_crt = pki_dir / f"{safe_service_id}-{role_slug}-outer.crt"
        router_ext = pki_dir / f"{safe_service_id}-{role_slug}-outer.ext"
        _run(
            openssl_bin,
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(router_key),
            "-out",
            str(router_csr),
            "-subj",
            f"/CN={safe_service_id}-{role_slug}-outer",
        )
        _write_text(
            router_ext,
            "\n".join(
                [
                    "basicConstraints=CA:FALSE",
                    "keyUsage=digitalSignature,keyEncipherment",
                    "extendedKeyUsage=serverAuth,clientAuth",
                    f"subjectAltName=DNS:{router_identity}",
                    "",
                ]
            ),
        )
        _run(
            openssl_bin,
            "x509",
            "-req",
            "-in",
            str(router_csr),
            "-CA",
            str(ca_crt),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(router_crt),
            "-days",
            "365",
            "-sha256",
            "-extfile",
            str(router_ext),
        )
        customer_router_outer_materials.append(
            {
                "router_role": router_role,
                "customer_device_name": str(device["name"]),
                "outer_tunnel_identity_ref": _device_outer_identity(bundle, device),
                "certificate_ref": _router_outer_certificate_ref(bundle, router_role),
                "certificate_path": str(router_crt),
                "private_key_path": str(router_key),
            }
        )
        inner_psk = secrets_dir / f"{safe_service_id}-{role_slug}-inner.psk"
        explicit_inner_psk = str(device.get("inner_vpn_psk") or "").strip()
        _write_text(inner_psk, (explicit_inner_psk or secrets.token_hex(24)) + "\n")
        inner_vpn_materials.append(
            {
                "router_role": router_role,
                "customer_device_name": str(device["name"]),
                "secret_ref": str(device["inner_vpn_auth_ref"]),
                "secret_path": str(inner_psk),
            }
        )

    manifest = {
        "package_type": "scenario1_demo_materials",
        "version": 1,
        "service_id": service_id,
        "openssl_path": openssl_bin,
        "certificate_material": {
            "outer_tunnel_ca": {
                "certificate_path": str(ca_crt),
                "private_key_path": str(ca_key),
            },
            "head_end_server": {
                "certificate_ref": bundle["operations"]["certificates"]["cgnat_head_end_server_cert_ref"],
                "certificate_path": str(head_crt),
                "private_key_path": str(head_key),
            },
            "customer_router_outer_clients": customer_router_outer_materials,
        },
        "inner_vpn_materials": inner_vpn_materials,
    }

    dump_json(output_dir / "materials-manifest.json", manifest)
    dump_text(
        output_dir / "README.md",
        "\n".join(
            [
                "# Scenario 1 Demo Materials",
                "",
                f"- Service ID: `{service_id}`",
                f"- OpenSSL path: `{openssl_bin}`",
                "- Contains demo outer-tunnel CA/server/client material.",
                "- Contains one demo inner-VPN PSK per customer router.",
                "- Intended for local staging into host-apply bundles only.",
                "",
            ]
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
