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

    def _write_module(self, *, transport_mode: str = "cgnat", pki_mode: str = "local_generate") -> None:
        module = {
            "customer": {
                "name": "test-cgnat-customer",
            },
            "peer": {
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


if __name__ == "__main__":
    unittest.main()
