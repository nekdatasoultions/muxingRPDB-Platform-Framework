from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


CGNAT_ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK_SRC = CGNAT_ROOT / "framework" / "src"
sys.path.insert(0, str(FRAMEWORK_SRC))

from cgnat.bundle import cgnat_root, ensure_path_within_cgnat  # noqa: E402


class WorkspaceBoundaryTests(unittest.TestCase):
    def test_cgnat_root_matches_workspace(self) -> None:
        self.assertEqual(cgnat_root(), CGNAT_ROOT)

    def test_ensure_path_within_cgnat_accepts_build_output(self) -> None:
        candidate = CGNAT_ROOT / "build" / "test-runs" / "accepted-output.json"
        resolved = ensure_path_within_cgnat(candidate)
        self.assertEqual(resolved, candidate.resolve())

    def test_ensure_path_within_cgnat_rejects_outside_path(self) -> None:
        outside_candidate = CGNAT_ROOT.parent / "outside-cgnat-output.json"
        with self.assertRaises(ValueError):
            ensure_path_within_cgnat(outside_candidate)


class PackageRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp(prefix="cgnat-test-", dir=str(CGNAT_ROOT / "build"))
        self.tempdir_path = Path(self.tempdir)
        self.bundle_path = CGNAT_ROOT / "build" / "sample-from-split" / "deployment-bundle.json"
        self.python = sys.executable

    def tearDown(self) -> None:
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def _run(self, *args: str) -> None:
        subprocess.run([self.python, *args], check=True, cwd=str(CGNAT_ROOT.parent))

    def test_render_framework_and_lane_packages(self) -> None:
        framework_output = self.tempdir_path / "framework-render"
        aws_output = self.tempdir_path / "aws-package"
        server_output = self.tempdir_path / "server-package"

        self._run(
            str(CGNAT_ROOT / "framework" / "scripts" / "render_bundle.py"),
            str(self.bundle_path),
            str(framework_output),
        )
        self._run(
            str(CGNAT_ROOT / "aws" / "scripts" / "render_aws_package.py"),
            str(self.bundle_path),
            str(aws_output),
        )
        self._run(
            str(CGNAT_ROOT / "server" / "scripts" / "render_server_package.py"),
            str(self.bundle_path),
            str(server_output),
        )

        validation = json.loads((framework_output / "framework" / "validation-result.json").read_text(encoding="utf-8"))
        aws_manifest = json.loads((aws_output / "package-manifest.json").read_text(encoding="utf-8"))
        server_manifest = json.loads((server_output / "package-manifest.json").read_text(encoding="utf-8"))
        validation_targets = json.loads((server_output / "validation-targets.json").read_text(encoding="utf-8"))

        self.assertTrue(validation["ok"])
        self.assertEqual(aws_manifest["package_type"], "cgnat_aws_package")
        self.assertEqual(server_manifest["package_type"], "cgnat_server_package")
        self.assertIn("inner_tunnel_established_customer_initiated", validation_targets["required_checks"])
        self.assertIn("customer_facing_public_ip_matches_termination_public_loopback", validation_targets["required_checks"])

    def test_aws_deploy_plan_mode_reports_known_launch_gaps(self) -> None:
        aws_output = self.tempdir_path / "aws-package"
        deploy_output = self.tempdir_path / "aws-deploy-plan"

        self._run(
            str(CGNAT_ROOT / "aws" / "scripts" / "render_aws_package.py"),
            str(self.bundle_path),
            str(aws_output),
        )
        self._run(
            str(CGNAT_ROOT / "aws" / "scripts" / "deploy_scenario1_aws.py"),
            str(aws_output),
            str(deploy_output),
            "--mode",
            "plan",
        )

        plan = json.loads((deploy_output / "deployment-plan.json").read_text(encoding="utf-8"))
        readiness = json.loads((deploy_output / "deployment-readiness.json").read_text(encoding="utf-8"))
        issue_codes = {issue["code"] for issue in plan["open_issues"]}
        head_request = json.loads((deploy_output / "head-end-run-instances-request.json").read_text(encoding="utf-8"))
        isp_request = json.loads((deploy_output / "isp-head-end-run-instances-request.json").read_text(encoding="utf-8"))

        self.assertTrue(plan["deployment_ready_for_live_create"])
        self.assertTrue(readiness["live_create_allowed"])
        self.assertNotIn("missing_head_end_launch_field_ami_id", issue_codes)
        self.assertNotIn("missing_head_end_launch_field_security_group_ids", issue_codes)
        self.assertNotIn("missing_head_end_launch_field_iam_instance_profile", issue_codes)
        self.assertTrue((deploy_output / "head-end-run-instances-request.json").exists())
        self.assertTrue((deploy_output / "isp-head-end-run-instances-request.json").exists())
        self.assertIn("BlockDeviceMappings", head_request)
        self.assertIn("TagSpecifications", head_request)
        self.assertIn("BlockDeviceMappings", isp_request)
        self.assertIn("TagSpecifications", isp_request)

    def test_aws_deploy_plan_mode_rejects_missing_launch_fields(self) -> None:
        aws_output = self.tempdir_path / "aws-package-missing-launch"
        deploy_output = self.tempdir_path / "aws-deploy-plan-missing-launch"

        self._run(
            str(CGNAT_ROOT / "aws" / "scripts" / "render_aws_package.py"),
            str(self.bundle_path),
            str(aws_output),
        )

        head_end_path = aws_output / "cgnat-head-end.json"
        head_end = json.loads(head_end_path.read_text(encoding="utf-8"))
        del head_end["ami_id"]
        head_end_path.write_text(json.dumps(head_end, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self._run(
            str(CGNAT_ROOT / "aws" / "scripts" / "deploy_scenario1_aws.py"),
            str(aws_output),
            str(deploy_output),
            "--mode",
            "plan",
        )

        plan = json.loads((deploy_output / "deployment-plan.json").read_text(encoding="utf-8"))
        readiness = json.loads((deploy_output / "deployment-readiness.json").read_text(encoding="utf-8"))
        issue_codes = {issue["code"] for issue in plan["open_issues"]}

        self.assertFalse(plan["deployment_ready_for_live_create"])
        self.assertFalse(readiness["live_create_allowed"])
        self.assertIn("missing_head_end_launch_field_ami_id", issue_codes)

    def test_aws_deploy_plan_mode_rejects_missing_root_volume_fields(self) -> None:
        aws_output = self.tempdir_path / "aws-package-missing-root-volume"
        deploy_output = self.tempdir_path / "aws-deploy-plan-missing-root-volume"

        self._run(
            str(CGNAT_ROOT / "aws" / "scripts" / "render_aws_package.py"),
            str(self.bundle_path),
            str(aws_output),
        )

        head_end_path = aws_output / "cgnat-head-end.json"
        head_end = json.loads(head_end_path.read_text(encoding="utf-8"))
        del head_end["root_volume"]["delete_on_termination"]
        head_end_path.write_text(json.dumps(head_end, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self._run(
            str(CGNAT_ROOT / "aws" / "scripts" / "deploy_scenario1_aws.py"),
            str(aws_output),
            str(deploy_output),
            "--mode",
            "plan",
        )

        plan = json.loads((deploy_output / "deployment-plan.json").read_text(encoding="utf-8"))
        readiness = json.loads((deploy_output / "deployment-readiness.json").read_text(encoding="utf-8"))
        issue_codes = {issue["code"] for issue in plan["open_issues"]}

        self.assertFalse(plan["deployment_ready_for_live_create"])
        self.assertFalse(readiness["live_create_allowed"])
        self.assertIn("missing_head_end_root_volume_field_delete_on_termination", issue_codes)

    def test_server_config_renderer_outputs_scenario1_artifacts(self) -> None:
        server_output = self.tempdir_path / "server-package"
        config_output = self.tempdir_path / "server-configs"

        self._run(
            str(CGNAT_ROOT / "server" / "scripts" / "render_server_package.py"),
            str(self.bundle_path),
            str(server_output),
        )
        self._run(
            str(CGNAT_ROOT / "server" / "scripts" / "render_scenario1_server_configs.py"),
            str(server_output),
            str(config_output),
        )

        head_end = json.loads((config_output / "cgnat-head-end-config.json").read_text(encoding="utf-8"))
        isp_head_end = json.loads((config_output / "cgnat-isp-head-end-config.json").read_text(encoding="utf-8"))
        backend_validation = json.loads((config_output / "backend-validation.json").read_text(encoding="utf-8"))
        runtime_inputs = json.loads((config_output / "runtime-inputs.json").read_text(encoding="utf-8"))
        validation_commands = (config_output / "validation-commands.md").read_text(encoding="utf-8")
        head_end_swanctl = (config_output / "cgnat-head-end-swanctl.conf").read_text(encoding="utf-8")
        isp_head_end_swanctl = (config_output / "cgnat-isp-head-end-swanctl.conf").read_text(encoding="utf-8")
        gre_script = (config_output / "cgnat-head-end-gre.sh").read_text(encoding="utf-8")
        route_script = (config_output / "cgnat-head-end-routes.sh").read_text(encoding="utf-8")
        runtime_env = (config_output / "scenario1-runtime.env").read_text(encoding="utf-8")

        self.assertEqual(head_end["config_type"], "scenario1_cgnat_head_end")
        self.assertEqual(isp_head_end["config_type"], "scenario1_cgnat_isp_head_end")
        self.assertEqual(backend_validation["config_type"], "scenario1_backend_validation")
        self.assertEqual(runtime_inputs["runtime_style"]["ipsec"], "strongswan_swanctl")
        self.assertIn("customer loopback identity", validation_commands.lower())
        self.assertIn("connections {", head_end_swanctl)
        self.assertIn("connections {", isp_head_end_swanctl)
        self.assertIn("ip tunnel add", gre_script)
        self.assertIn("scenario1-runtime.env", gre_script)
        self.assertIn("ip route replace", route_script)
        self.assertIn("CGNAT_BACKEND_GRE_REMOTE", runtime_env)
        self.assertNotIn("<resolve", head_end_swanctl)
        self.assertNotIn("<resolve", isp_head_end_swanctl)
        self.assertNotIn("placeholder", route_script.lower())


if __name__ == "__main__":
    unittest.main()
