from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
CUSTOMER_NAME = "vpn-customer-stage1-15-cust-0002"
CURRENT_PEER_IP = "44.211.95.93"


class NatTWatcherCurrentPeerTests(unittest.TestCase):
    def test_watcher_uses_current_staged_sot_peer_when_request_peer_is_stale(self) -> None:
        with tempfile.TemporaryDirectory(prefix="nat-t-current-peer-", dir=REPO_ROOT / "build") as raw_root:
            root = Path(raw_root)
            staged_customer_root = (
                root
                / "staged"
                / "var"
                / "lib"
                / "rpdb-backend"
                / "customers"
                / CUSTOMER_NAME
            )
            staged_customer_root.mkdir(parents=True)
            (staged_customer_root / "customer-ddb-item.json").write_text(
                json.dumps(
                    {
                        "customer_name": CUSTOMER_NAME,
                        "peer_ip": CURRENT_PEER_IP,
                        "customer_json": json.dumps({"peer": {"public_ip": CURRENT_PEER_IP}}),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            environment_path = root / "env.yaml"
            environment_path.write_text(
                yaml.safe_dump(
                    {
                        "environment": {"name": "nat-t-current-peer-watch-test", "access": {"method": "staged"}},
                        "datastores": {"mode": "staged", "staged_root": str(root / "staged")},
                        "nat_t_watcher": {"promotion": {"mode": "deploy_only"}},
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            log_path = root / "muxer-events.jsonl"
            with log_path.open("w", encoding="utf-8") as handle:
                for dport in (500, 4500):
                    handle.write(
                        json.dumps(
                            {
                                "schema_version": 1,
                                "source": "test",
                                "observed_peer": CURRENT_PEER_IP,
                                "observed_protocol": "udp",
                                "observed_dport": dport,
                                "observed_at": f"2026-05-12T04:30:0{dport // 4500}Z",
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    )

            completed = subprocess.run(
                [
                    sys.executable,
                    "muxer/scripts/watch_nat_t_logs.py",
                    "--customer-request",
                    "muxer/config/customer-requests/migrated/vpn-customer-stage1-15-cust-0002.yaml",
                    "--environment",
                    str(environment_path),
                    "--log-file",
                    str(log_path),
                    "--state-file",
                    str(root / "state.json"),
                    "--out-dir",
                    str(root / "out"),
                    "--package-root",
                    str(root / "packages"),
                    "--json",
                ],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr or completed.stdout)
            report = json.loads(completed.stdout)

            watch = report["watched_customers"][CUSTOMER_NAME]
            self.assertEqual(watch["peer_ip"], CURRENT_PEER_IP)
            self.assertIn("effective-requests", watch["request"])
            self.assertEqual(report["detected_count"], 1)
            self.assertEqual(report["detected"][0]["peer_ip"], CURRENT_PEER_IP)

            updated_request = Path(watch["request"])
            self.assertTrue(updated_request.exists())
            updated_doc = yaml.safe_load(updated_request.read_text(encoding="utf-8"))
            self.assertEqual(updated_doc["customer"]["peer"]["public_ip"], CURRENT_PEER_IP)


if __name__ == "__main__":
    unittest.main()
