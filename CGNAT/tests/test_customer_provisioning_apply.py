from __future__ import annotations

import json
import hashlib
import shutil
import subprocess
import sys
import tempfile
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
        build_root = CGNAT_ROOT / "build"
        build_root.mkdir(parents=True, exist_ok=True)
        self.test_root = Path(
            tempfile.mkdtemp(prefix="customer-provisioning-apply-test-", dir=str(build_root))
        )

        self.staged_root = self.test_root / "staged-live"
        self.deploy_dir = self.test_root / "deploy"
        self.environment_path = self.test_root / "example-rpdb-staged-live.yaml"
        case_slug = self.id().split(".")[-1].lower()
        case_hash = hashlib.sha1(self.id().encode("utf-8")).hexdigest()[:10]
        self.customer_name = f"cgnat-apply-{case_slug[:20]}-{case_hash}"
        self.request_path = self.test_root / "example-minimal-cgnat-apply-test.yaml"
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

        self._write_request("example-minimal-cgnat.yaml")

        for relative_path in (
            "muxer-root",
            "nat-active-root",
            "nat-standby-root",
            "nonnat-active-root",
            "nonnat-standby-root",
            "cgnat-headend-root",
            "cgnat-isp-gateway-1-root",
            "cgnat-isp-gateway-2-root",
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
            "backups/baseline/cgnat-isp-gateways/isp-cgnat-router-1",
            "backups/baseline/cgnat-isp-gateways/isp-cgnat-router-2",
        ):
            (self.staged_root / relative_path).mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.test_root.exists():
            shutil.rmtree(self.test_root, ignore_errors=True)
        if self.operation_lock_path.exists():
            self.operation_lock_path.unlink()

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

    def _write_request(self, example_name: str) -> None:
        request_doc = yaml.safe_load(
            (MUXER_ROOT / "config" / "customer-requests" / "examples" / example_name).read_text(
                encoding="utf-8"
            )
        ) or {}
        customer = request_doc.setdefault("customer", {})
        original_name = str(customer.get("name") or "").strip()
        customer["name"] = self.customer_name
        request_doc = self._replace_in_doc(request_doc, original_name, self.customer_name)
        customer = request_doc.setdefault("customer", {})
        customer["name"] = self.customer_name
        transport = customer.setdefault("transport", {})
        cgnat_transport = transport.setdefault("cgnat", {})
        outer_identity_ref = str(cgnat_transport.get("outer_identity_ref") or "").strip()
        if outer_identity_ref and original_name:
            cgnat_transport["outer_identity_ref"] = outer_identity_ref.replace(
                original_name,
                self.customer_name,
            )
        self.request_path.write_text(
            yaml.safe_dump(request_doc, sort_keys=False),
            encoding="utf-8",
            newline="\n",
        )

    def _replace_in_doc(self, value: object, old: str, new: str) -> object:
        if isinstance(value, str):
            return value.replace(old, new)
        if isinstance(value, dict):
            return {key: self._replace_in_doc(nested, old, new) for key, nested in value.items()}
        if isinstance(value, list):
            return [self._replace_in_doc(nested, old, new) for nested in value]
        return value

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
        self.assertTrue(execution_plan["cgnat_review"]["ready_for_review"])
        self.assertEqual(execution_plan["cgnat_review"]["pki"]["mode"], "reference")
        self.assertTrue((REPO_ROOT / execution_plan["cgnat_review"]["paths"]["pki_review"]).exists())

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
        self.assertTrue((customer_root / "pki" / "pki-review.json").exists())
        self.assertTrue((customer_root / "pki" / "headend-install" / "headend-install-manifest.json").exists())
        self.assertTrue((customer_root / "apply-cgnat-customer.sh").exists())
        self.assertTrue((customer_root / "remove-cgnat-customer.sh").exists())
        self.assertTrue(config_json.exists())
        install_state = json.loads((customer_root / "install-state.json").read_text(encoding="utf-8"))
        self.assertEqual(install_state["pki_install"]["material_mode"], "reference")

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

    def test_scenario2_shared_gateway_approved_apply_selects_second_gateway(self) -> None:
        self._write_request("example-minimal-cgnat-shared-isp-scenario2-local-pki.yaml")

        execution_plan = self._run_approved_apply()
        self.assertEqual(execution_plan["status"], "applied")
        self.assertEqual(execution_plan["selected_targets"]["cgnat_outer_topology"], "shared_isp_gateway")
        self.assertEqual(execution_plan["selected_targets"]["cgnat_outer_gateway_ref"], "isp-cgnat-router-2")
        self.assertEqual(execution_plan["selected_targets"]["cgnat_isp_gateway"]["name"], "rpdb-staged-cgnat-isp-gateway-2")
        self.assertEqual(
            execution_plan["dry_run_gate"]["backup_refs"]["cgnat_isp_gateway"],
            str((self.staged_root / "backups" / "baseline" / "cgnat-isp-gateways" / "isp-cgnat-router-2").resolve()),
        )
        self.assertEqual(
            execution_plan["touch_plan"]["cgnat_isp_gateway"],
            "rpdb-staged-cgnat-isp-gateway-2",
        )
        self.assertTrue(execution_plan["apply"]["validation"]["cgnat_headend"]["valid"])
        cgnat_customer_root = self.staged_root / "cgnat-headend-root" / "var" / "lib" / "rpdb-cgnat" / "customers" / self.customer_name
        self.assertTrue((cgnat_customer_root / "pki" / "headend-install" / "headend.crt").exists())
        self.assertTrue((cgnat_customer_root / "pki" / "headend-install" / "headend.key").exists())
        self.assertTrue((cgnat_customer_root / "pki" / "headend-install" / "outer-ca.crt").exists())
        install_state = json.loads((cgnat_customer_root / "install-state.json").read_text(encoding="utf-8"))
        installed_files = install_state["pki_install"]["installed_files"]
        self.assertEqual(
            installed_files["headend_certificate"],
            f"/var/lib/rpdb-cgnat/customers/{self.customer_name}/pki/headend-install/headend.crt",
        )
        self.assertEqual(
            installed_files["headend_private_key"],
            f"/var/lib/rpdb-cgnat/customers/{self.customer_name}/pki/headend-install/headend.key",
        )
        self.assertEqual(
            installed_files["ca_certificate"],
            f"/var/lib/rpdb-cgnat/customers/{self.customer_name}/pki/headend-install/outer-ca.crt",
        )

        rollback_plan_path = REPO_ROOT / execution_plan["apply"]["rollback_plan"]
        rollback_results = self._run_rollback(rollback_plan_path)
        self.assertTrue(
            all(
                str(result.get("status") or "").strip().lower() == "rolled_back"
                or bool(result.get("removed"))
                for result in rollback_results
            )
        )


if __name__ == "__main__":
    unittest.main()
