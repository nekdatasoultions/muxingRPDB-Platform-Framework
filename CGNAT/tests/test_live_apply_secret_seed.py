from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


CGNAT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CGNAT_ROOT.parent
CUSTOMERS_ROOT = REPO_ROOT / "scripts" / "customers"
if str(CUSTOMERS_ROOT) not in sys.path:
    sys.path.insert(0, str(CUSTOMERS_ROOT))

import live_apply_lib  # noqa: E402


class LiveApplySecretSeedTests(unittest.TestCase):
    def setUp(self) -> None:
        build_root = CGNAT_ROOT / "build"
        build_root.mkdir(parents=True, exist_ok=True)
        self.test_root = Path(tempfile.mkdtemp(prefix="live-apply-secret-seed-", dir=str(build_root)))
        self.package_dir = self.test_root / "package"
        self.apply_dir = self.test_root / "apply"
        self.package_dir.mkdir(parents=True, exist_ok=True)
        self.apply_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.test_root.exists():
            shutil.rmtree(self.test_root, ignore_errors=True)

    def _write_module(
        self,
        *,
        transport_mode: str = "cgnat",
        pki_mode: str = "local_generate",
        peer: dict | None = None,
        ipsec: dict | None = None,
    ) -> None:
        module = {
            "customer": {
                "name": "test-cgnat-customer",
            },
            "peer": peer
            or {
                "psk_secret_ref": "/muxingrpdb/customers/test-cgnat-customer/psk",
            },
            "transport": {
                "mode": transport_mode,
                "cgnat": {
                    "pki": {
                        "mode": pki_mode,
                    }
                },
            },
        }
        if ipsec is not None:
            module["ipsec"] = ipsec
        (self.package_dir / "customer-module.json").write_text(
            json.dumps(module, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_existing_secret_is_reused_without_local_handoff(self) -> None:
        self._write_module()
        with mock.patch.object(
            live_apply_lib,
            "run_local",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="existing-psk\n", stderr=""),
        ):
            report = live_apply_lib._resolve_or_seed_customer_psk_secret(
                package_dir=self.package_dir,
                region="us-east-1",
                apply_dir=self.apply_dir,
            )

        self.assertFalse(report["created"])
        self.assertIsNone(report["local_handoff_path"])
        self.assertEqual(report["secret"], "existing-psk")

    def test_missing_local_generate_secret_is_created_and_written(self) -> None:
        self._write_module()
        responses = [
            subprocess.CompletedProcess(
                args=[],
                returncode=255,
                stdout="",
                stderr="An error occurred (ResourceNotFoundException) when calling the GetSecretValue operation",
            ),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="{}", stderr=""),
        ]
        with mock.patch.object(live_apply_lib, "run_local", side_effect=responses), mock.patch.object(
            live_apply_lib.secrets,
            "token_urlsafe",
            return_value="generated-test-psk",
        ):
            report = live_apply_lib._resolve_or_seed_customer_psk_secret(
                package_dir=self.package_dir,
                region="us-east-1",
                apply_dir=self.apply_dir,
            )

        self.assertTrue(report["created"])
        self.assertEqual(report["secret"], "generated-test-psk")
        self.assertIsNotNone(report["local_handoff_path"])
        handoff_path = REPO_ROOT / str(report["local_handoff_path"])
        self.assertTrue(handoff_path.exists())
        self.assertEqual(handoff_path.read_text(encoding="utf-8").strip(), "generated-test-psk")

    def test_missing_non_local_generate_secret_still_fails(self) -> None:
        self._write_module(pki_mode="reference")
        with mock.patch.object(
            live_apply_lib,
            "run_local",
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=255,
                stdout="",
                stderr="An error occurred (ResourceNotFoundException) when calling the GetSecretValue operation",
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "automatic seeding is only enabled"):
                live_apply_lib._resolve_or_seed_customer_psk_secret(
                    package_dir=self.package_dir,
                    region="us-east-1",
                    apply_dir=self.apply_dir,
                )

    def test_local_psk_requires_environment_opt_in(self) -> None:
        self._write_module(peer={"psk_source": "local", "psk": "inline-test-psk"})

        with self.assertRaisesRegex(RuntimeError, "secrets.allow_local_psk=true"):
            live_apply_lib._resolve_or_seed_customer_psk_secret(
                package_dir=self.package_dir,
                region="us-east-1",
                apply_dir=self.apply_dir,
            )

    def test_local_psk_allowed_without_aws_lookup(self) -> None:
        self._write_module(peer={"psk_source": "local", "psk": "inline-test-psk"})

        with mock.patch.object(live_apply_lib, "run_local") as run_local:
            report = live_apply_lib._resolve_or_seed_customer_psk_secret(
                package_dir=self.package_dir,
                region="us-east-1",
                apply_dir=self.apply_dir,
                allow_local_psk=True,
            )

        run_local.assert_not_called()
        self.assertFalse(report["created"])
        self.assertEqual(report["source"], "local")
        self.assertEqual(report["secret_ref"], "local:customer.peer.psk")
        self.assertEqual(report["secret"], "inline-test-psk")

    def test_certificate_auth_material_is_staged_from_local_files_without_aws_lookup(self) -> None:
        cert_dir = self.test_root / "certs"
        cert_dir.mkdir(parents=True, exist_ok=True)
        headend_cert = cert_dir / "headend-cert.pem"
        headend_key = cert_dir / "headend-key.pem"
        headend_passphrase = cert_dir / "headend-key-passphrase.txt"
        remote_trust = cert_dir / "remote-trust.pem"
        remote_cert = cert_dir / "remote-cert.pem"
        headend_cert.write_text("-----BEGIN CERTIFICATE-----\nheadend\n-----END CERTIFICATE-----\n", encoding="utf-8")
        headend_key.write_text("-----BEGIN PRIVATE KEY-----\nheadend-key\n-----END PRIVATE KEY-----\n", encoding="utf-8")
        headend_passphrase.write_text("test-passphrase\n", encoding="utf-8")
        remote_trust.write_text("-----BEGIN CERTIFICATE-----\nremote-trust\n-----END CERTIFICATE-----\n", encoding="utf-8")
        remote_cert.write_text("-----BEGIN CERTIFICATE-----\nremote-cert\n-----END CERTIFICATE-----\n", encoding="utf-8")
        self._write_module(
            peer={"public_ip": "203.0.113.70"},
            ipsec={
                "auth": {
                    "method": "certificate",
                    "certificate": {
                        "profile": "customer_supplied",
                        "headend": {
                            "id": "rpdb-headend.example",
                            "cert_ref": f"file://{headend_cert.as_posix()}",
                            "private_key_secret_ref": f"file://{headend_key.as_posix()}",
                            "private_key_passphrase_secret_ref": f"file://{headend_passphrase.as_posix()}",
                        },
                        "remote": {
                            "id": "customer-cert.example",
                            "trust_ref": f"file://{remote_trust.as_posix()}",
                            "cert_ref": f"file://{remote_cert.as_posix()}",
                        },
                    },
                },
            },
        )
        headend_root = self.test_root / "headend-root"
        swanctl_conf = headend_root / "etc" / "swanctl" / "conf.d" / "rpdb-customers" / "test-cgnat-customer.conf"
        swanctl_conf.parent.mkdir(parents=True, exist_ok=True)
        swanctl_conf.write_text(
            "\n".join(
                [
                    "connections { test-cgnat-customer { local { auth = pubkey } } }",
                    "secrets {",
                    "  private-test-cgnat-customer-headend-key {",
                    "    file = rpdb-customers/test-cgnat-customer-headend-key.pem",
                    "    secret = resolved-via-secret-store",
                    "  }",
                    "}",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        with mock.patch.object(live_apply_lib, "run_local") as run_local:
            report = live_apply_lib._prepare_live_headend_auth_material(
                [],
                package_dir=self.package_dir,
                headend_prepared={
                    "root": str(headend_root),
                    "apply": {"swanctl_conf": str(swanctl_conf)},
                },
                region="us-east-1",
                apply_dir=self.apply_dir,
            )

        run_local.assert_not_called()
        self.assertEqual(report["source"], "certificate")
        self.assertEqual(report["profile"], "customer_supplied")
        self.assertEqual(
            sorted(report["relative_paths"]),
            sorted(
                [
                    "etc/swanctl/x509/rpdb-customers/test-cgnat-customer-headend-cert.pem",
                    "etc/swanctl/private/rpdb-customers/test-cgnat-customer-headend-key.pem",
                    "etc/swanctl/x509ca/rpdb-customers/test-cgnat-customer-remote-trust.pem",
                    "etc/swanctl/x509/rpdb-customers/test-cgnat-customer-remote-cert.pem",
                ]
            ),
        )
        self.assertTrue((headend_root / "etc" / "swanctl" / "x509" / "rpdb-customers" / "test-cgnat-customer-headend-cert.pem").exists())
        self.assertTrue((headend_root / "etc" / "swanctl" / "private" / "rpdb-customers" / "test-cgnat-customer-headend-key.pem").exists())
        self.assertTrue((headend_root / "etc" / "swanctl" / "x509ca" / "rpdb-customers" / "test-cgnat-customer-remote-trust.pem").exists())
        self.assertEqual(report["private_key_passphrase"]["secret_length"], len("test-passphrase"))
        self.assertIn('secret = "test-passphrase"', swanctl_conf.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
