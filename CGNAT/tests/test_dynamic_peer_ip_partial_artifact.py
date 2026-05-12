from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESS_SCRIPT = REPO_ROOT / "muxer" / "scripts" / "process_dynamic_peer_ip_change.py"


def load_process_module():
    spec = importlib.util.spec_from_file_location("process_dynamic_peer_ip_change", PROCESS_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {PROCESS_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DynamicPeerIpPartialArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        build_root = REPO_ROOT / "build"
        build_root.mkdir(parents=True, exist_ok=True)
        self.test_root = Path(tempfile.mkdtemp(prefix="dynamic-peer-ip-partial-", dir=str(build_root)))

    def tearDown(self) -> None:
        shutil.rmtree(self.test_root, ignore_errors=True)

    def test_incomplete_artifact_dir_is_quarantined_before_retry(self) -> None:
        module = load_process_module()
        artifact_dir = self.test_root / "vpn-customer-demo" / "abc123"
        artifact_dir.mkdir(parents=True)
        partial_file = artifact_dir / "updated-request.yaml"
        partial_content = "schema_version: 1\n"
        partial_file.write_text(partial_content, encoding="utf-8")

        quarantined = module._quarantine_incomplete_artifact_dir(artifact_dir)

        self.assertFalse(artifact_dir.exists())
        self.assertTrue(quarantined.exists())
        self.assertTrue(quarantined.name.startswith("abc123.incomplete-"))
        self.assertEqual(partial_content, (quarantined / "updated-request.yaml").read_text(encoding="utf-8"))

    def test_redacted_local_psk_is_restored_from_fallback_request_peer(self) -> None:
        module = load_process_module()
        request_doc = module._module_to_request(
            {
                "schema_version": 1,
                "customer": {
                    "name": "vpn-customer-demo",
                    "customer_class": "strict-non-nat",
                },
                "peer": {
                    "public_ip": "44.213.128.193",
                    "remote_id": "3.236.161.125",
                    "psk_source": "local",
                    "psk": "<redacted-local-psk>",
                    "psk_redacted": True,
                },
                "selectors": {
                    "local_subnets": ["194.138.36.80/28"],
                    "remote_subnets": ["10.129.3.128/32"],
                    "remote_host_cidrs": ["10.129.3.128/32"],
                },
            },
            fallback_peer={
                "public_ip": "3.236.161.125",
                "remote_id": "3.236.161.125",
                "psk_source": "local",
                "psk": "demo-local-psk",
            },
        )

        peer = request_doc["customer"]["peer"]
        self.assertEqual(peer["public_ip"], "44.213.128.193")
        self.assertEqual(peer["remote_id"], "3.236.161.125")
        self.assertEqual(peer["psk_source"], "local")
        self.assertEqual(peer["psk"], "demo-local-psk")
        self.assertNotIn("psk_redacted", peer)


if __name__ == "__main__":
    unittest.main()
