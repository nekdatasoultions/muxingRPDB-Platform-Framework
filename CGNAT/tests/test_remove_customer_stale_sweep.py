from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
MUXER_ROOT = REPO_ROOT / "muxer"
PYTHON = sys.executable


def _rewrite_staged_paths(value: object, staged_root: Path) -> object:
    if isinstance(value, str) and value.startswith("build/staged-live"):
        suffix = value[len("build/staged-live") :].lstrip("/\\")
        return str((staged_root / suffix).resolve())
    if isinstance(value, dict):
        return {key: _rewrite_staged_paths(nested, staged_root) for key, nested in value.items()}
    if isinstance(value, list):
        return [_rewrite_staged_paths(nested, staged_root) for nested in value]
    return value


class RemoveCustomerStaleSweepTests(unittest.TestCase):
    def setUp(self) -> None:
        build_root = REPO_ROOT / "CGNAT" / "build"
        build_root.mkdir(parents=True, exist_ok=True)
        self.test_root = Path(tempfile.mkdtemp(prefix="remove-stale-sweep-", dir=str(build_root)))
        self.staged_root = self.test_root / "staged-live"
        self.environment_path = self.test_root / "example-rpdb-staged-live.yaml"
        case_hash = hashlib.sha1(self.id().encode("utf-8")).hexdigest()[:10]
        self.customer_name = f"remove-sweep-{case_hash}"
        self.operation_lock_path = REPO_ROOT / "build" / "customer-operation-locks" / f"{self.customer_name}.json"
        if self.operation_lock_path.exists():
            self.operation_lock_path.unlink()

        base_environment_path = MUXER_ROOT / "config" / "deployment-environments" / "example-rpdb-staged-live.yaml"
        environment_doc = yaml.safe_load(base_environment_path.read_text(encoding="utf-8")) or {}
        rewritten = _rewrite_staged_paths(environment_doc, self.staged_root)
        self.environment_path.write_text(
            yaml.safe_dump(rewritten, sort_keys=False),
            encoding="utf-8",
            newline="\n",
        )

    def tearDown(self) -> None:
        if self.test_root.exists():
            shutil.rmtree(self.test_root, ignore_errors=True)
        if self.operation_lock_path.exists():
            self.operation_lock_path.unlink()

    def _backend_customer_root(self) -> Path:
        return (
            self.staged_root
            / "datastores"
            / "var"
            / "lib"
            / "rpdb-backend"
            / "customers"
            / self.customer_name
        )

    def _backend_allocation_root(self) -> Path:
        return (
            self.staged_root
            / "datastores"
            / "var"
            / "lib"
            / "rpdb-backend"
            / "allocations"
            / self.customer_name
        )

    def _headend_customer_root(self, family: str, role: str) -> Path:
        root_name = {
            ("nat", "active"): "nat-active-root",
            ("nat", "standby"): "nat-standby-root",
            ("non_nat", "active"): "nonnat-active-root",
            ("non_nat", "standby"): "nonnat-standby-root",
        }[(family, role)]
        return (
            self.staged_root
            / root_name
            / "var"
            / "lib"
            / "rpdb-headend"
            / "customers"
            / self.customer_name
        )

    def _headend_conf(self, family: str, role: str) -> Path:
        root_name = {
            ("nat", "active"): "nat-active-root",
            ("nat", "standby"): "nat-standby-root",
            ("non_nat", "active"): "nonnat-active-root",
            ("non_nat", "standby"): "nonnat-standby-root",
        }[(family, role)]
        return (
            self.staged_root
            / root_name
            / "etc"
            / "swanctl"
            / "conf.d"
            / "rpdb-customers"
            / f"{self.customer_name}.conf"
        )

    def _write_backend_customer(self, backend_cluster: str) -> None:
        customer_root = self._backend_customer_root()
        allocation_root = self._backend_allocation_root()
        customer_root.mkdir(parents=True, exist_ok=True)
        allocation_root.mkdir(parents=True, exist_ok=True)
        customer_module = {
            "customer": {
                "name": self.customer_name,
                "customer_class": "nat-t" if backend_cluster == "nat" else "strict-non-nat",
            },
            "backend": {"cluster": backend_cluster, "assignment": f"{backend_cluster}-pool-test"},
            "peer": {"public_ip": "203.0.113.20"},
            "transport": {"mode": ""},
        }
        customer_item = {
            "customer_name": self.customer_name,
            "customer_class": customer_module["customer"]["customer_class"],
            "backend_cluster": backend_cluster,
            "backend_assignment": customer_module["backend"]["assignment"],
            "peer_ip": customer_module["peer"]["public_ip"],
            "customer_json": json.dumps(customer_module, separators=(",", ":")),
        }
        (customer_root / "customer-ddb-item.json").write_text(
            json.dumps(customer_item, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (customer_root / "customer-module.json").write_text(
            json.dumps(customer_module, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (allocation_root / "allocation-ddb-items.json").write_text("[]\n", encoding="utf-8")

    def _write_headend_install(self, family: str, role: str) -> None:
        customer_root = self._headend_customer_root(family, role)
        conf_path = self._headend_conf(family, role)
        customer_root.mkdir(parents=True, exist_ok=True)
        conf_path.parent.mkdir(parents=True, exist_ok=True)
        (customer_root / "install-state.json").write_text(
            json.dumps({"customer_name": self.customer_name, "family": family, "role": role}) + "\n",
            encoding="utf-8",
        )
        conf_path.write_text(f"# stale or active config for {self.customer_name}\n", encoding="utf-8")

    def _run_remove(self, *extra_args: str) -> dict:
        out_dir = self.test_root / ("remove-" + hashlib.sha1(" ".join(extra_args).encode()).hexdigest()[:8])
        completed = subprocess.run(
            [
                PYTHON,
                str(REPO_ROOT / "scripts" / "customers" / "remove_customer.py"),
                "--customer-name",
                self.customer_name,
                "--environment",
                str(self.environment_path),
                "--out-dir",
                str(out_dir),
                "--approve",
                "--json",
                *extra_args,
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, msg=completed.stderr or completed.stdout)
        return json.loads(completed.stdout)

    def test_auto_remove_sweeps_nat_and_non_nat_headends_before_sot_delete(self) -> None:
        self._write_backend_customer("nat")
        for family in ("nat", "non_nat"):
            for role in ("active", "standby"):
                self._write_headend_install(family, role)

        result = self._run_remove()

        self.assertEqual(result["status"], "removed")
        self.assertEqual(result["current_headend_family"], "nat")
        self.assertEqual(result["headend_family"], "all")
        self.assertTrue(result["sweep_stale_headends"])
        touched = {
            (headend["family"], headend["ha_role"])
            for headend in result["touch_plan"]["headends"]
        }
        self.assertEqual(
            touched,
            {("nat", "active"), ("nat", "standby"), ("non_nat", "active"), ("non_nat", "standby")},
        )
        for family in ("nat", "non_nat"):
            for role in ("active", "standby"):
                self.assertFalse(self._headend_customer_root(family, role).exists())
                self.assertFalse(self._headend_conf(family, role).exists())
        self.assertFalse(self._backend_customer_root().exists())
        self.assertFalse(self._backend_allocation_root().exists())

    def test_explicit_headend_family_remains_surgical(self) -> None:
        self._write_backend_customer("nat")
        self._write_headend_install("nat", "active")
        self._write_headend_install("non_nat", "active")

        result = self._run_remove("--headend-family", "nat")

        self.assertEqual(result["status"], "removed")
        self.assertEqual(result["current_headend_family"], "nat")
        self.assertEqual(result["headend_family"], "nat")
        self.assertTrue(result["sweep_stale_headends"])
        touched = {
            (headend["family"], headend["ha_role"])
            for headend in result["touch_plan"]["headends"]
        }
        self.assertEqual(touched, {("nat", "active"), ("nat", "standby")})
        self.assertFalse(self._headend_customer_root("nat", "active").exists())
        self.assertFalse(self._headend_conf("nat", "active").exists())
        self.assertTrue(self._headend_customer_root("non_nat", "active").exists())
        self.assertTrue(self._headend_conf("non_nat", "active").exists())


if __name__ == "__main__":
    unittest.main()
