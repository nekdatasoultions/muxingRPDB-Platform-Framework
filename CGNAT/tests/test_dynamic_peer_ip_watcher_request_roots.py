from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
WATCH_SCRIPT = REPO_ROOT / "muxer" / "scripts" / "watch_dynamic_peer_ip_registry.py"
CUSTOMER_NAME = "vpn-customer-stage1-15-cust-0002"


def load_watch_module():
    spec = importlib.util.spec_from_file_location("watch_dynamic_peer_ip_registry", WATCH_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {WATCH_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_dynamic_request(path: Path, *, peer_ip: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "customer": {
                    "name": CUSTOMER_NAME,
                    "peer": {"public_ip": peer_ip},
                    "dynamic_peer_ip": {
                        "enabled": True,
                        "source": "device_registry_ddns",
                        "device_registry": {
                            "serial_number": CUSTOMER_NAME,
                            "password_secret_ref": "/demo/ddns-password",
                        },
                        "reapply": {"mode": "remove_reapply"},
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


class DynamicPeerIpWatcherRequestRootTests(unittest.TestCase):
    def setUp(self) -> None:
        build_root = REPO_ROOT / "build"
        build_root.mkdir(parents=True, exist_ok=True)
        self.test_root = Path(tempfile.mkdtemp(prefix="dynamic-peer-ip-roots-", dir=str(build_root)))

    def tearDown(self) -> None:
        shutil.rmtree(self.test_root, ignore_errors=True)

    def test_later_allowed_root_overrides_canonical_customer_request(self) -> None:
        module = load_watch_module()
        canonical_root = self.test_root / "canonical"
        demo_root = self.test_root / "demo"
        canonical_request = canonical_root / "vpn-customer-stage1-15-cust-0002.yaml"
        demo_request = demo_root / "vpn-customer-stage1-15-cust-0002-local-psk.yaml"
        write_dynamic_request(canonical_request, peer_ip="3.236.161.125")
        write_dynamic_request(demo_request, peer_ip="44.213.128.193")

        paths = module._discover_request_paths([], [canonical_root, demo_root])
        watches, errors = module._load_customer_watches(paths)

        self.assertEqual(errors, [])
        self.assertEqual(watches[CUSTOMER_NAME].request_path, demo_request.resolve())
        self.assertEqual(watches[CUSTOMER_NAME].request_peer_ip, "44.213.128.193")


if __name__ == "__main__":
    unittest.main()
