from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
WATCH_SCRIPT = REPO_ROOT / "muxer" / "scripts" / "watch_nat_t_logs.py"
CUSTOMER_NAME = "vpn-customer-stage1-15-cust-0005"


def load_watch_module():
    spec = importlib.util.spec_from_file_location("watch_nat_t_logs", WATCH_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {WATCH_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_nat_t_request(path: Path, *, peer_ip: str, translated_ip: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "customer": {
                    "name": CUSTOMER_NAME,
                    "peer": {"public_ip": peer_ip},
                    "selectors": {
                        "local_subnets": ["194.138.36.80/28"],
                        "remote_subnets": ["10.129.3.131/32"],
                        "remote_host_cidrs": ["10.129.3.131/32"],
                    },
                    "dynamic_provisioning": {
                        "enabled": True,
                        "mode": "nat_t_auto_promote",
                        "trigger": {
                            "protocol": "udp",
                            "destination_port": 4500,
                            "confirmation_packets": 1,
                            "require_initial_udp500_observation": True,
                        },
                    },
                    "post_ipsec_nat": {
                        "enabled": True,
                        "mode": "explicit_map",
                        "mapping_strategy": "explicit_host_map",
                        "real_subnets": ["10.129.3.131/32"],
                        "translated_subnets": ["172.30.0.128/27"],
                        "host_mappings": [
                            {
                                "real_ip": "10.129.3.131/32",
                                "translated_ip": f"{translated_ip}/32",
                            }
                        ],
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


class NatTWatcherRequestRootTests(unittest.TestCase):
    def setUp(self) -> None:
        build_root = REPO_ROOT / "build"
        build_root.mkdir(parents=True, exist_ok=True)
        self.test_root = Path(tempfile.mkdtemp(prefix="nat-t-roots-", dir=str(build_root)))

    def tearDown(self) -> None:
        shutil.rmtree(self.test_root, ignore_errors=True)

    def test_later_allowed_root_overrides_canonical_customer_request(self) -> None:
        module = load_watch_module()
        canonical_root = self.test_root / "canonical"
        demo_root = self.test_root / "demo"
        canonical_request = canonical_root / "vpn-customer-stage1-15-cust-0005.yaml"
        demo_request = demo_root / "vpn-customer-stage1-15-cust-0005-explicit-inside-nat.yaml"
        write_nat_t_request(canonical_request, peer_ip="35.169.124.144", translated_ip="172.30.0.128")
        write_nat_t_request(demo_request, peer_ip="35.169.124.144", translated_ip="172.30.0.133")

        paths = module._discover_request_paths([], [canonical_root, demo_root])
        watches, errors = module._load_customer_watches(paths)

        self.assertEqual(errors, [])
        self.assertEqual(watches[CUSTOMER_NAME].request_path, demo_request.resolve())


if __name__ == "__main__":
    unittest.main()
