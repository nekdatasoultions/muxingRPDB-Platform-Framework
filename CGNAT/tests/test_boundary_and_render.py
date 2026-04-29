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
from cgnat.aws_preflight import analyze_aws_inventory  # noqa: E402
from cgnat.predeploy_review import build_predeploy_review  # noqa: E402


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

    def test_aws_deploy_plan_mode_allows_allocate_new_eip_strategy(self) -> None:
        aws_output = self.tempdir_path / "aws-package-allocate-new-eip"
        deploy_output = self.tempdir_path / "aws-deploy-plan-allocate-new-eip"

        self._run(
            str(CGNAT_ROOT / "aws" / "scripts" / "render_aws_package.py"),
            str(self.bundle_path),
            str(aws_output),
        )

        head_end_path = aws_output / "cgnat-head-end.json"
        head_end = json.loads(head_end_path.read_text(encoding="utf-8"))
        head_end["public_eip_strategy"] = "allocate_new"
        head_end["public_eip_allocation_id"] = None
        head_end_path.write_text(json.dumps(head_end, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        isp_head_end_path = aws_output / "cgnat-isp-head-end.json"
        isp_head_end = json.loads(isp_head_end_path.read_text(encoding="utf-8"))
        isp_head_end["public_eip_strategy"] = "allocate_new"
        isp_head_end["public_eip_allocation_id"] = None
        isp_head_end_path.write_text(json.dumps(isp_head_end, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self._run(
            str(CGNAT_ROOT / "aws" / "scripts" / "deploy_scenario1_aws.py"),
            str(aws_output),
            str(deploy_output),
            "--mode",
            "plan",
        )

        plan = json.loads((deploy_output / "deployment-plan.json").read_text(encoding="utf-8"))
        readiness = json.loads((deploy_output / "deployment-readiness.json").read_text(encoding="utf-8"))
        action_names = {action["name"] for action in plan["post_create_actions"]["actions"]}

        self.assertTrue(plan["deployment_ready_for_live_create"])
        self.assertTrue(readiness["live_create_allowed"])
        self.assertIn("allocate_and_associate_head_end_eip", action_names)
        self.assertIn("allocate_and_associate_isp_head_end_eip", action_names)

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

    def test_prepare_scenario1_orchestrates_local_artifacts(self) -> None:
        prep_output = self.tempdir_path / "scenario1-prep"

        self._run(
            str(CGNAT_ROOT / "framework" / "scripts" / "prepare_scenario1.py"),
            str(self.bundle_path),
            str(prep_output),
        )

        summary = json.loads((prep_output / "scenario1-preparation-summary.json").read_text(encoding="utf-8"))
        readme = (prep_output / "README.md").read_text(encoding="utf-8")

        self.assertEqual(summary["orchestration_type"], "scenario1_preparation")
        self.assertTrue(summary["validation_ok"])
        self.assertTrue(summary["aws_live_create_allowed"])
        self.assertTrue((prep_output / "framework-render" / "framework" / "validation-result.json").exists())
        self.assertTrue((prep_output / "aws-package" / "package-manifest.json").exists())
        self.assertTrue((prep_output / "aws-deploy-plan" / "deployment-plan.json").exists())
        self.assertTrue((prep_output / "server-package" / "package-manifest.json").exists())
        self.assertTrue((prep_output / "server-configs" / "scenario1-runtime.env").exists())
        self.assertTrue((prep_output / "host-apply" / "package-manifest.json").exists())
        self.assertTrue((prep_output / "host-apply" / "hosts" / "cgnat-head-end" / "apply.sh").exists())
        self.assertTrue((prep_output / "host-apply" / "hosts" / "cgnat-isp-head-end" / "preflight.sh").exists())
        self.assertIn("does not deploy infrastructure", readme)

    def test_prepare_scenario1_can_include_remote_apply_plan(self) -> None:
        prep_output = self.tempdir_path / "scenario1-prep-remote"
        host_access_path = self.tempdir_path / "host-access-for-prep.json"

        host_access = {
            "cgnat_head_end": {
                "ssh_user": "ec2-user",
                "target_host": "203.0.113.10",
                "private_key_path": "/keys/cgnat-head-end.pem",
                "remote_stage_dir": "/var/tmp/cgnat-head-end",
            },
            "cgnat_isp_head_end": {
                "ssh_user": "ec2-user",
                "target_host": "203.0.113.20",
                "private_key_path": "/keys/cgnat-isp-head-end.pem",
                "remote_stage_dir": "/var/tmp/cgnat-isp-head-end",
            },
        }
        host_access_path.write_text(json.dumps(host_access, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self._run(
            str(CGNAT_ROOT / "framework" / "scripts" / "prepare_scenario1.py"),
            str(self.bundle_path),
            str(prep_output),
            "--host-access-json",
            str(host_access_path),
        )

        summary = json.loads((prep_output / "scenario1-preparation-summary.json").read_text(encoding="utf-8"))
        readme = (prep_output / "README.md").read_text(encoding="utf-8")

        self.assertIn("remote_apply_output", summary["steps"])
        self.assertTrue((prep_output / "remote-apply-plan" / "commands" / "cgnat_head_end-stage.sh").exists())
        self.assertIn("Remote apply plan", readme)

    def test_prepare_scenario1_host_apply_outputs_per_host_bundles(self) -> None:
        server_output = self.tempdir_path / "server-package"
        config_output = self.tempdir_path / "server-configs"
        host_apply_output = self.tempdir_path / "host-apply"

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
        self._run(
            str(CGNAT_ROOT / "server" / "scripts" / "prepare_scenario1_host_apply.py"),
            str(config_output),
            str(host_apply_output),
        )

        manifest = json.loads((host_apply_output / "package-manifest.json").read_text(encoding="utf-8"))
        apply_order = json.loads((host_apply_output / "apply-order.json").read_text(encoding="utf-8"))
        head_apply = (host_apply_output / "hosts" / "cgnat-head-end" / "apply.sh").read_text(encoding="utf-8")
        head_preflight = (host_apply_output / "hosts" / "cgnat-head-end" / "preflight.sh").read_text(encoding="utf-8")
        isp_preflight = (host_apply_output / "hosts" / "cgnat-isp-head-end" / "preflight.sh").read_text(encoding="utf-8")
        isp_config = json.loads((config_output / "cgnat-isp-head-end-config.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["package_type"], "scenario1_host_apply_package")
        self.assertEqual(apply_order["steps"][0]["role"], "cgnat_head_end")
        self.assertIn("swanctl --load-conns", head_apply)
        self.assertIn("bash \"$SCRIPT_DIR/cgnat-head-end-gre.sh\"", head_apply)
        self.assertIn("command -v swanctl", head_preflight)
        self.assertIn("customer_facing_interface", json.dumps(isp_config))
        self.assertIn("ip link show", isp_preflight)

    def test_prepare_scenario1_remote_apply_plan_outputs_command_scripts(self) -> None:
        server_output = self.tempdir_path / "server-package"
        config_output = self.tempdir_path / "server-configs"
        host_apply_output = self.tempdir_path / "host-apply"
        remote_apply_output = self.tempdir_path / "remote-apply-plan"
        host_access_path = self.tempdir_path / "host-access.json"

        host_access = {
            "cgnat_head_end": {
                "ssh_user": "ec2-user",
                "target_host": "203.0.113.10",
                "private_key_path": "/keys/cgnat-head-end.pem",
                "remote_stage_dir": "/var/tmp/cgnat-head-end",
            },
            "cgnat_isp_head_end": {
                "ssh_user": "ec2-user",
                "target_host": "203.0.113.20",
                "private_key_path": "/keys/cgnat-isp-head-end.pem",
                "remote_stage_dir": "/var/tmp/cgnat-isp-head-end",
            },
        }
        host_access_path.write_text(json.dumps(host_access, indent=2, sort_keys=True) + "\n", encoding="utf-8")

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
        self._run(
            str(CGNAT_ROOT / "server" / "scripts" / "prepare_scenario1_host_apply.py"),
            str(config_output),
            str(host_apply_output),
        )
        self._run(
            str(CGNAT_ROOT / "server" / "scripts" / "prepare_scenario1_remote_apply_plan.py"),
            str(host_apply_output),
            str(host_access_path),
            str(remote_apply_output),
        )

        manifest = json.loads((remote_apply_output / "package-manifest.json").read_text(encoding="utf-8"))
        head_stage = (remote_apply_output / "commands" / "cgnat_head_end-stage.sh").read_text(encoding="utf-8")
        isp_apply = (remote_apply_output / "commands" / "cgnat_isp_head_end-apply.sh").read_text(encoding="utf-8")

        self.assertEqual(manifest["package_type"], "scenario1_remote_apply_plan")
        self.assertIn("scp -i", head_stage)
        self.assertIn("203.0.113.10", head_stage)
        self.assertIn("./apply.sh", isp_apply)
        self.assertIn("/var/tmp/cgnat-isp-head-end", isp_apply)

    def test_execute_scenario1_remote_apply_plan_plan_mode(self) -> None:
        server_output = self.tempdir_path / "server-package"
        config_output = self.tempdir_path / "server-configs"
        host_apply_output = self.tempdir_path / "host-apply"
        remote_apply_output = self.tempdir_path / "remote-apply-plan"
        execution_output = self.tempdir_path / "remote-apply-execution"
        host_access_path = self.tempdir_path / "host-access-execution.json"

        host_access = {
            "cgnat_head_end": {
                "ssh_user": "ec2-user",
                "target_host": "203.0.113.10",
                "private_key_path": "/keys/cgnat-head-end.pem",
                "remote_stage_dir": "/var/tmp/cgnat-head-end",
            },
            "cgnat_isp_head_end": {
                "ssh_user": "ec2-user",
                "target_host": "203.0.113.20",
                "private_key_path": "/keys/cgnat-isp-head-end.pem",
                "remote_stage_dir": "/var/tmp/cgnat-isp-head-end",
            },
        }
        host_access_path.write_text(json.dumps(host_access, indent=2, sort_keys=True) + "\n", encoding="utf-8")

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
        self._run(
            str(CGNAT_ROOT / "server" / "scripts" / "prepare_scenario1_host_apply.py"),
            str(config_output),
            str(host_apply_output),
        )
        self._run(
            str(CGNAT_ROOT / "server" / "scripts" / "prepare_scenario1_remote_apply_plan.py"),
            str(host_apply_output),
            str(host_access_path),
            str(remote_apply_output),
        )
        self._run(
            str(CGNAT_ROOT / "server" / "scripts" / "execute_scenario1_remote_apply_plan.py"),
            str(remote_apply_output),
            str(execution_output),
            "--mode",
            "plan",
        )

        plan = json.loads((execution_output / "execution-plan.json").read_text(encoding="utf-8"))
        readiness = json.loads((execution_output / "execution-readiness.json").read_text(encoding="utf-8"))

        self.assertEqual(plan["plan_type"], "scenario1_remote_apply_execution_plan")
        self.assertEqual(readiness["mode"], "plan")
        self.assertIn("steps", plan)
        self.assertFalse(readiness["live_execution_allowed"])

    def test_derive_host_access_from_aws_apply_uses_associated_public_ips(self) -> None:
        apply_result_path = self.tempdir_path / "apply-result.json"
        strategy_path = self.tempdir_path / "host-access-strategy.json"
        output_path = self.tempdir_path / "derived-host-access.json"

        apply_result = {
            "mode": "live_apply",
            "head_end": {
                "response": {
                    "Instances": [
                        {
                            "InstanceId": "i-head",
                            "PrivateIpAddress": "172.31.40.250",
                        }
                    ]
                }
            },
            "isp_head_end": {
                "response": {
                    "Instances": [
                        {
                            "InstanceId": "i-isp",
                            "PrivateIpAddress": "172.31.40.251",
                        }
                    ]
                }
            },
            "post_create_actions": [
                {
                    "name": "allocate_and_associate_head_end_eip",
                    "service_role": "cgnat_head_end",
                    "status": "completed",
                    "response": {
                        "allocation": {
                            "PublicIp": "54.10.10.10",
                            "AllocationId": "eipalloc-head",
                        }
                    },
                },
                {
                    "name": "allocate_and_associate_isp_head_end_eip",
                    "service_role": "cgnat_isp_head_end",
                    "status": "completed",
                    "response": {
                        "allocation": {
                            "PublicIp": "54.10.10.11",
                            "AllocationId": "eipalloc-isp",
                        }
                    },
                },
            ],
        }
        strategy = {
            "cgnat_head_end": {
                "ssh_user": "ec2-user",
                "private_key_path": "/keys/cgnat-head-end.pem",
                "remote_stage_dir": "/var/tmp/cgnat-head-end",
                "address_source": "associated_public_ip",
            },
            "cgnat_isp_head_end": {
                "ssh_user": "ec2-user",
                "private_key_path": "/keys/cgnat-isp-head-end.pem",
                "remote_stage_dir": "/var/tmp/cgnat-isp-head-end",
                "address_source": "associated_public_ip",
            },
        }
        apply_result_path.write_text(json.dumps(apply_result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        strategy_path.write_text(json.dumps(strategy, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self._run(
            str(CGNAT_ROOT / "server" / "scripts" / "derive_host_access_from_aws_apply.py"),
            str(apply_result_path),
            str(strategy_path),
            str(output_path),
        )

        derived = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(derived["cgnat_head_end"]["target_host"], "54.10.10.10")
        self.assertEqual(derived["cgnat_isp_head_end"]["target_host"], "54.10.10.11")

    def test_aws_live_preflight_detects_cross_az_isp_subnets(self) -> None:
        package = {
            "manifest": {
                "service_id": "cgnat-service-example",
                "customer_id": "customer-example",
                "environment_name": "rpdb-empty-live",
            },
            "cgnat_head_end": {
                "subnet_id": "subnet-a",
                "security_group_ids": ["sg-a"],
                "ami_id": "ami-a",
                "iam_instance_profile": "profile-a",
                "key_pair_name": "muxer",
                "public_eip_strategy": "allocate_new",
            },
            "cgnat_isp_head_end": {
                "subnets": {
                    "transit_subnet_id": "subnet-a",
                    "customer_subnet_id": "subnet-b",
                },
                "security_group_ids": ["sg-a"],
                "ami_id": "ami-a",
                "iam_instance_profile": "profile-a",
                "key_pair_name": "muxer",
                "public_eip_strategy": "allocate_new",
            },
            "dependencies": {
                "aws": {
                    "vpc_id": "vpc-a",
                }
            },
        }
        inventory = {
            "sts_identity": {"Account": "123456789012"},
            "subnets": [
                {"SubnetId": "subnet-a", "VpcId": "vpc-a", "AvailabilityZone": "us-east-1a"},
                {"SubnetId": "subnet-b", "VpcId": "vpc-a", "AvailabilityZone": "us-east-1b"},
            ],
            "security_groups": [{"GroupId": "sg-a", "VpcId": "vpc-a"}],
            "images": [{"ImageId": "ami-a"}],
            "instance_profiles": ["profile-a"],
            "key_pairs": ["muxer"],
            "addresses": [],
        }

        result = analyze_aws_inventory(package, inventory)
        issue_codes = {issue["code"] for issue in result["issues"]}

        self.assertFalse(result["ready_for_live_apply"])
        self.assertIn("isp_head_end_subnet_az_mismatch", issue_codes)

    def test_build_predeploy_review_reports_ready_state_and_open_items(self) -> None:
        bundle = json.loads((CGNAT_ROOT / "framework" / "config" / "deployment-bundle.example.json").read_text(encoding="utf-8"))
        prep_summary = {
            "validation_ok": True,
            "aws_live_create_allowed": True,
            "aws_preflight_ready_for_live_apply": True,
        }
        preflight_result = {"issues": []}
        aws_apply_result = {
            "head_end": {"status": "dry_run_ok"},
            "isp_head_end": {"status": "dry_run_ok"},
            "post_create_actions": [
                {"status": "dry_run_ok"},
                {"status": "dry_run_ok"},
            ],
        }

        review = build_predeploy_review(
            bundle,
            prep_summary,
            preflight_result,
            aws_apply_result,
            host_access_strategy_path=str(CGNAT_ROOT / "server" / "config" / "host-access-strategy.example.json"),
        )

        self.assertTrue(review["ready_for_hard_review"])
        self.assertTrue(review["status_summary"]["aws_dry_run_ok"])
        self.assertEqual(review["deployment_model"]["customer_facing_public_ip"], "198.51.100.10")
        self.assertGreaterEqual(len(review["open_items_before_host_apply"]), 3)


if __name__ == "__main__":
    unittest.main()
