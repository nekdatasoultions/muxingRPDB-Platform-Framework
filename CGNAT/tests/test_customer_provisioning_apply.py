from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import yaml


CGNAT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CGNAT_ROOT.parent
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


class CustomerProvisioningApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_root = CGNAT_ROOT / "build" / "customer-provisioning-apply-test"
        if self.test_root.exists():
            shutil.rmtree(self.test_root)
        self.test_root.mkdir(parents=True, exist_ok=True)

        self.staged_root = self.test_root / "staged-live"
        self.deploy_dir = self.test_root / "deploy"
        self.environment_path = self.test_root / "example-rpdb-staged-live.yaml"
        self.customer_name = "example-minimal-cgnat-apply-test"
        self.request_path = self.test_root / "example-minimal-cgnat-apply-test.yaml"

        base_environment_path = MUXER_ROOT / "config" / "deployment-environments" / "example-rpdb-staged-live.yaml"
        environment_doc = yaml.safe_load(base_environment_path.read_text(encoding="utf-8")) or {}
        rewritten = _rewrite_staged_paths(environment_doc, self.staged_root)
        self.environment_path.write_text(
            yaml.safe_dump(rewritten, sort_keys=False),
            encoding="utf-8",
            newline="\n",
        )

        request_doc = yaml.safe_load(
            (MUXER_ROOT / "config" / "customer-requests" / "examples" / "example-minimal-cgnat.yaml").read_text(
                encoding="utf-8"
            )
        ) or {}
        customer = request_doc.setdefault("customer", {})
        customer["name"] = self.customer_name
        transport = customer.setdefault("transport", {})
        cgnat_transport = transport.setdefault("cgnat", {})
        outer_identity_ref = str(cgnat_transport.get("outer_identity_ref") or "").strip()
        if outer_identity_ref:
            cgnat_transport["outer_identity_ref"] = outer_identity_ref.replace(
                "example-minimal-cgnat",
                self.customer_name,
            )
        self.request_path.write_text(
            yaml.safe_dump(request_doc, sort_keys=False),
            encoding="utf-8",
            newline="\n",
        )

        for relative_path in (
            "muxer-root",
            "nat-active-root",
            "nat-standby-root",
            "nonnat-active-root",
            "nonnat-standby-root",
            "cgnat-headend-root",
            "datastores",
            "artifacts",
            "logs",
            "nat-t-watcher/state",
            "nat-t-watcher/out",
            "nat-t-watcher/packages",
            "nat-t-watcher/synced",
            "backups/baseline/muxer",
            "backups/baseline/nat-headend",
            "backups/baseline/non-nat-headend",
            "backups/baseline/cgnat-headend",
        ):
            (self.staged_root / relative_path).mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.test_root.exists():
            shutil.rmtree(self.test_root)

    def _run_approved_apply(self) -> dict:
        completed = subprocess.run(
            [
                PYTHON,
                str(REPO_ROOT / "scripts" / "customers" / "deploy_customer.py"),
                "--customer-file",
                str(self.request_path),
                "--environment",
                str(self.environment_path),
                "--out-dir",
                str(self.deploy_dir),
                "--approve",
                "--json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, msg=completed.stderr or completed.stdout)
        return json.loads(completed.stdout)

    def _run_rollback(self, rollback_plan_path: Path) -> list[dict]:
        rollback_plan = json.loads(rollback_plan_path.read_text(encoding="utf-8"))
        results: list[dict] = []
        for step in reversed(rollback_plan["steps"]):
            completed = subprocess.run(
                step["command"],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr or completed.stdout)
            payload = json.loads(completed.stdout)
            results.append(payload)
        return results

    def test_cgnat_customer_approved_apply_installs_rich_staged_surface(self) -> None:
        execution_plan = self._run_approved_apply()
        self.assertEqual(execution_plan["status"], "applied")
        self.assertTrue(execution_plan["approved"])
        self.assertTrue(execution_plan["live_apply"])
        self.assertIn("verify_backup_gate", execution_plan["execution_order"])
        self.assertIn("apply_cgnat_headend_customer", execution_plan["execution_order"])
        self.assertIn("validate_cgnat_headend_customer", execution_plan["execution_order"])

        apply_result = execution_plan["apply"]
        self.assertEqual(apply_result["status"], "applied")
        self.assertEqual(apply_result["mode"], "staged_activation_apply")
        self.assertIsNotNone(apply_result["validation"]["cgnat_headend"])
        self.assertTrue(apply_result["validation"]["cgnat_headend"]["valid"])
        self.assertIsNotNone(apply_result["applies"]["cgnat_headend"])
        self.assertEqual(apply_result["applies"]["cgnat_headend"]["status"], "applied")
        self.assertIn("cgnat_headend", apply_result["backup_gate"]["references"])

        customer_root = self.staged_root / "cgnat-headend-root" / "var" / "lib" / "rpdb-cgnat" / "customers" / self.customer_name
        config_json = self.staged_root / "cgnat-headend-root" / "etc" / "rpdb-cgnat" / "customers" / f"{self.customer_name}.json"
        self.assertTrue((customer_root / "customer-summary.json").exists())
        self.assertTrue((customer_root / "install-state.json").exists())
        self.assertTrue((customer_root / "cgnat-transport.json").exists())
        self.assertTrue((customer_root / "transport" / "transport-profile.json").exists())
        self.assertTrue((customer_root / "transport" / "apply-transport.sh").exists())
        self.assertTrue((customer_root / "transport" / "remove-transport.sh").exists())
        self.assertTrue((customer_root / "validation" / "validation-intent.json").exists())
        self.assertTrue((customer_root / "validation" / "activation-manifest.json").exists())
        self.assertTrue((customer_root / "apply-cgnat-customer.sh").exists())
        self.assertTrue((customer_root / "remove-cgnat-customer.sh").exists())
        self.assertTrue(config_json.exists())

        rollback_plan_path = REPO_ROOT / apply_result["rollback_plan"]
        rollback_plan = json.loads(rollback_plan_path.read_text(encoding="utf-8"))
        self.assertIn("backup_gate", rollback_plan)
        self.assertTrue(any(step.get("action") == "rollback_cgnat_headend_activation_bundle" for step in rollback_plan["steps"]))

    def test_cgnat_customer_approved_apply_rollback_cleans_all_surfaces(self) -> None:
        execution_plan = self._run_approved_apply()
        apply_result = execution_plan["apply"]
        rollback_plan_path = REPO_ROOT / apply_result["rollback_plan"]
        rollback_results = self._run_rollback(rollback_plan_path)

        self.assertGreaterEqual(len(rollback_results), 4)

        backend_customer_root = self.staged_root / "datastores" / "var" / "lib" / "rpdb-backend" / "customers" / self.customer_name
        backend_allocation_root = self.staged_root / "datastores" / "var" / "lib" / "rpdb-backend" / "allocations" / self.customer_name
        muxer_customer_root = self.staged_root / "muxer-root" / "var" / "lib" / "rpdb-muxer" / "customers" / self.customer_name
        muxer_module_root = self.staged_root / "muxer-root" / "etc" / "muxer" / "config" / "customer-modules" / self.customer_name
        headend_active_customer_root = self.staged_root / "nonnat-active-root" / "var" / "lib" / "rpdb-headend" / "customers" / self.customer_name
        headend_active_conf = self.staged_root / "nonnat-active-root" / "etc" / "swanctl" / "conf.d" / "rpdb-customers" / f"{self.customer_name}.conf"
        headend_standby_customer_root = self.staged_root / "nonnat-standby-root" / "var" / "lib" / "rpdb-headend" / "customers" / self.customer_name
        headend_standby_conf = self.staged_root / "nonnat-standby-root" / "etc" / "swanctl" / "conf.d" / "rpdb-customers" / f"{self.customer_name}.conf"
        cgnat_customer_root = self.staged_root / "cgnat-headend-root" / "var" / "lib" / "rpdb-cgnat" / "customers" / self.customer_name
        cgnat_config_json = self.staged_root / "cgnat-headend-root" / "etc" / "rpdb-cgnat" / "customers" / f"{self.customer_name}.json"

        for path in (
            backend_customer_root,
            backend_allocation_root,
            muxer_customer_root,
            muxer_module_root,
            headend_active_customer_root,
            headend_active_conf,
            headend_standby_customer_root,
            headend_standby_conf,
            cgnat_customer_root,
            cgnat_config_json,
        ):
            self.assertFalse(path.exists(), msg=f"expected rollback to remove {path}")


if __name__ == "__main__":
    unittest.main()
