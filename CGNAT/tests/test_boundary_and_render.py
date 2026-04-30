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
        self.bundle_path = CGNAT_ROOT / "framework" / "config" / "deployment-bundle.example.json"
        self.python = sys.executable

    def tearDown(self) -> None:
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def _run(self, *args: str) -> None:
        subprocess.run([self.python, *args], check=True, cwd=str(CGNAT_ROOT.parent))

    def test_render_framework_and_lane_packages(self) -> None:
        framework_output = self.tempdir_path / "framework-render"
        aws_output = self.tempdir_path / "aws-package"
        server_output = self.tempdir_path / "server-package"

        self._run(str(CGNAT_ROOT / "framework" / "scripts" / "render_bundle.py"), str(self.bundle_path), str(framework_output))
        self._run(str(CGNAT_ROOT / "aws" / "scripts" / "render_aws_package.py"), str(self.bundle_path), str(aws_output))
        self._run(str(CGNAT_ROOT / "server" / "scripts" / "render_server_package.py"), str(self.bundle_path), str(server_output))

        validation = json.loads((framework_output / "framework" / "validation-result.json").read_text(encoding="utf-8"))
        aws_manifest = json.loads((aws_output / "package-manifest.json").read_text(encoding="utf-8"))
        server_manifest = json.loads((server_output / "package-manifest.json").read_text(encoding="utf-8"))
        validation_targets = json.loads((server_output / "validation-targets.json").read_text(encoding="utf-8"))
        customer_routers = json.loads((server_output / "customer-vpn-routers.json").read_text(encoding="utf-8"))

        self.assertTrue(validation["ok"])
        self.assertEqual(aws_manifest["deployment_model"]["customer_model"], "many_to_one_via_isp_cgnat")
        self.assertEqual(aws_manifest["deployment_model"]["customer_router_count"], 2)
        self.assertEqual(server_manifest["customer_router_count"], 2)
        self.assertEqual(len(customer_routers), 2)
        self.assertIn("customer_router_inner_tunnels_established", validation_targets["required_checks"])

    def test_aws_deploy_plan_includes_customer_router_requests(self) -> None:
        aws_output = self.tempdir_path / "aws-package"
        deploy_output = self.tempdir_path / "aws-deploy-plan"

        self._run(str(CGNAT_ROOT / "aws" / "scripts" / "render_aws_package.py"), str(self.bundle_path), str(aws_output))
        self._run(str(CGNAT_ROOT / "aws" / "scripts" / "deploy_scenario1_aws.py"), str(aws_output), str(deploy_output), "--mode", "plan")

        plan = json.loads((deploy_output / "deployment-plan.json").read_text(encoding="utf-8"))
        readiness = json.loads((deploy_output / "deployment-readiness.json").read_text(encoding="utf-8"))
        router_requests = json.loads((deploy_output / "customer-vpn-router-run-instances-requests.json").read_text(encoding="utf-8"))
        action_names = {action["name"] for action in plan["post_create_actions"]["actions"]}

        self.assertTrue(plan["deployment_ready_for_live_create"])
        self.assertTrue(readiness["live_create_allowed"])
        self.assertEqual(len(router_requests), 2)
        self.assertEqual(router_requests[0]["role"], "customer_vpn_router_1")
        self.assertEqual(router_requests[1]["role"], "customer_vpn_router_2")
        self.assertIn("disable_source_dest_check_head_end", action_names)
        self.assertIn("disable_source_dest_check_isp_head_end", action_names)

    def test_server_config_renderer_outputs_per_router_artifacts(self) -> None:
        server_output = self.tempdir_path / "server-package"
        config_output = self.tempdir_path / "server-configs"

        self._run(str(CGNAT_ROOT / "server" / "scripts" / "render_server_package.py"), str(self.bundle_path), str(server_output))
        self._run(str(CGNAT_ROOT / "server" / "scripts" / "render_scenario1_server_configs.py"), str(server_output), str(config_output))

        runtime_inputs = json.loads((config_output / "runtime-inputs.json").read_text(encoding="utf-8"))
        customer_router_configs = json.loads((config_output / "customer-vpn-routers-config.json").read_text(encoding="utf-8"))
        router1_conf = (config_output / "customer_vpn_router_1-inner-swanctl.conf").read_text(encoding="utf-8")
        router2_conf = (config_output / "customer_vpn_router_2-inner-swanctl.conf").read_text(encoding="utf-8")
        router1_env = (config_output / "customer_vpn_router_1-runtime.env").read_text(encoding="utf-8")
        isp_runtime = (config_output / "cgnat-isp-head-end-runtime.env").read_text(encoding="utf-8")

        self.assertEqual(len(runtime_inputs["customer_vpn_routers"]), 2)
        self.assertEqual(len(customer_router_configs), 2)
        self.assertIn("__CGNAT_INNER_PSK__", router1_conf)
        self.assertIn("__CGNAT_INNER_PSK__", router2_conf)
        self.assertIn("CGNAT_CUSTOMER_DEFAULT_GATEWAY_IP", router1_env)
        self.assertIn("CGNAT_ISP_CUSTOMER_PRIVATE_IP", isp_runtime)
        self.assertFalse((config_output / "cgnat-isp-head-end-inner-swanctl.conf").exists())

    def test_prepare_scenario1_host_apply_outputs_four_host_bundles(self) -> None:
        server_output = self.tempdir_path / "server-package"
        config_output = self.tempdir_path / "server-configs"
        host_apply_output = self.tempdir_path / "host-apply"

        self._run(str(CGNAT_ROOT / "server" / "scripts" / "render_server_package.py"), str(self.bundle_path), str(server_output))
        self._run(str(CGNAT_ROOT / "server" / "scripts" / "render_scenario1_server_configs.py"), str(server_output), str(config_output))
        self._run(str(CGNAT_ROOT / "server" / "scripts" / "prepare_scenario1_host_apply.py"), str(config_output), str(host_apply_output))

        manifest = json.loads((host_apply_output / "package-manifest.json").read_text(encoding="utf-8"))
        apply_order = json.loads((host_apply_output / "apply-order.json").read_text(encoding="utf-8"))

        self.assertEqual(len(manifest["hosts"]), 4)
        self.assertTrue((host_apply_output / "hosts" / "customer-vpn-router-1" / "apply.sh").exists())
        self.assertTrue((host_apply_output / "hosts" / "customer-vpn-router-2" / "preflight.sh").exists())
        self.assertEqual(apply_order["steps"][0]["role"], "cgnat_head_end")
        self.assertIn("customer_vpn_router_1", [step["role"] for step in apply_order["steps"] if "role" in step])

    def test_materialize_demo_materials_stages_per_router_psks(self) -> None:
        materials_output = self.tempdir_path / "demo-materials"
        server_output = self.tempdir_path / "server-package"
        config_output = self.tempdir_path / "server-configs"
        host_apply_output = self.tempdir_path / "host-apply-with-materials"

        self._run(str(CGNAT_ROOT / "server" / "scripts" / "materialize_scenario1_demo_materials.py"), str(self.bundle_path), str(materials_output))
        self._run(str(CGNAT_ROOT / "server" / "scripts" / "render_server_package.py"), str(self.bundle_path), str(server_output))
        self._run(str(CGNAT_ROOT / "server" / "scripts" / "render_scenario1_server_configs.py"), str(server_output), str(config_output))
        self._run(
            str(CGNAT_ROOT / "server" / "scripts" / "prepare_scenario1_host_apply.py"),
            str(config_output),
            str(host_apply_output),
            "--materials-manifest-json",
            str(materials_output / "materials-manifest.json"),
        )

        materials_manifest = json.loads((materials_output / "materials-manifest.json").read_text(encoding="utf-8"))
        router1_conf = (host_apply_output / "hosts" / "customer-vpn-router-1" / "customer_vpn_router_1-inner-swanctl.conf").read_text(encoding="utf-8")
        router2_conf = (host_apply_output / "hosts" / "customer-vpn-router-2" / "customer_vpn_router_2-inner-swanctl.conf").read_text(encoding="utf-8")

        self.assertEqual(len(materials_manifest["inner_vpn_materials"]), 2)
        self.assertNotIn("__CGNAT_INNER_PSK__", router1_conf)
        self.assertNotIn("__CGNAT_INNER_PSK__", router2_conf)
        self.assertTrue((host_apply_output / "hosts" / "customer-vpn-router-1" / f"{materials_manifest['service_id']}-customer_vpn_router_1-inner.psk").exists())

    def test_prepare_scenario1_remote_apply_plan_outputs_proxyjump_roles(self) -> None:
        server_output = self.tempdir_path / "server-package"
        config_output = self.tempdir_path / "server-configs"
        host_apply_output = self.tempdir_path / "host-apply"
        remote_apply_output = self.tempdir_path / "remote-apply-plan"
        host_access_path = self.tempdir_path / "host-access.json"

        host_access = {
            "cgnat_head_end": {
                "ssh_user": "ec2-user",
                "target_host": "203.0.113.10",
                "private_key_path": "/keys/shared.pem",
                "remote_stage_dir": "/var/tmp/cgnat-head-end",
            },
            "cgnat_isp_head_end": {
                "ssh_user": "ec2-user",
                "target_host": "203.0.113.20",
                "private_key_path": "/keys/shared.pem",
                "remote_stage_dir": "/var/tmp/cgnat-isp-head-end",
            },
            "customer_vpn_router_1": {
                "ssh_user": "ec2-user",
                "target_host": "172.31.48.20",
                "private_key_path": "/keys/shared.pem",
                "remote_stage_dir": "/var/tmp/customer-vpn-router-1",
                "proxy_jump_role": "cgnat_isp_head_end",
            },
            "customer_vpn_router_2": {
                "ssh_user": "ec2-user",
                "target_host": "172.31.48.21",
                "private_key_path": "/keys/shared.pem",
                "remote_stage_dir": "/var/tmp/customer-vpn-router-2",
                "proxy_jump_role": "cgnat_isp_head_end",
            },
        }
        host_access_path.write_text(json.dumps(host_access, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self._run(str(CGNAT_ROOT / "server" / "scripts" / "render_server_package.py"), str(self.bundle_path), str(server_output))
        self._run(str(CGNAT_ROOT / "server" / "scripts" / "render_scenario1_server_configs.py"), str(server_output), str(config_output))
        self._run(str(CGNAT_ROOT / "server" / "scripts" / "prepare_scenario1_host_apply.py"), str(config_output), str(host_apply_output))
        self._run(
            str(CGNAT_ROOT / "server" / "scripts" / "prepare_scenario1_remote_apply_plan.py"),
            str(host_apply_output),
            str(host_access_path),
            str(remote_apply_output),
        )

        manifest = json.loads((remote_apply_output / "package-manifest.json").read_text(encoding="utf-8"))
        router1_stage = (remote_apply_output / "commands" / "customer_vpn_router_1-stage.sh").read_text(encoding="utf-8")

        self.assertEqual(len(manifest["hosts"]), 4)
        self.assertIn("ProxyJump", router1_stage)
        self.assertIn("172.31.48.20", router1_stage)

    def test_derive_host_access_from_aws_apply_uses_private_ips_for_customer_routers(self) -> None:
        apply_result_path = self.tempdir_path / "apply-result.json"
        strategy_path = self.tempdir_path / "host-access-strategy.json"
        output_path = self.tempdir_path / "derived-host-access.json"

        apply_result = {
            "mode": "live_apply",
            "head_end": {"response": {"Instances": [{"InstanceId": "i-head", "PrivateIpAddress": "172.31.32.10"}]}},
            "isp_head_end": {"response": {"Instances": [{"InstanceId": "i-isp", "PrivateIpAddress": "172.31.48.10"}]}},
            "customer_vpn_routers": [
                {"role": "customer_vpn_router_1", "response": {"Instances": [{"InstanceId": "i-router-1", "PrivateIpAddress": "172.31.48.20"}]}},
                {"role": "customer_vpn_router_2", "response": {"Instances": [{"InstanceId": "i-router-2", "PrivateIpAddress": "172.31.48.21"}]}},
            ],
            "post_create_actions": [
                {
                    "name": "allocate_and_associate_head_end_eip",
                    "service_role": "cgnat_head_end",
                    "status": "completed",
                    "response": {"allocation": {"PublicIp": "54.10.10.10", "AllocationId": "eipalloc-head"}},
                },
                {
                    "name": "allocate_and_associate_isp_head_end_eip",
                    "service_role": "cgnat_isp_head_end",
                    "status": "completed",
                    "response": {"allocation": {"PublicIp": "54.10.10.11", "AllocationId": "eipalloc-isp"}},
                },
            ],
        }
        strategy = {
            "cgnat_head_end": {
                "ssh_user": "ec2-user",
                "private_key_path": "/keys/shared.pem",
                "remote_stage_dir": "/var/tmp/cgnat-head-end",
                "address_source": "associated_public_ip",
            },
            "cgnat_isp_head_end": {
                "ssh_user": "ec2-user",
                "private_key_path": "/keys/shared.pem",
                "remote_stage_dir": "/var/tmp/cgnat-isp-head-end",
                "address_source": "associated_public_ip",
            },
            "customer_vpn_router_1": {
                "ssh_user": "ec2-user",
                "private_key_path": "/keys/shared.pem",
                "remote_stage_dir": "/var/tmp/customer-vpn-router-1",
                "address_source": "private_ip",
                "proxy_jump_role": "cgnat_isp_head_end",
            },
            "customer_vpn_router_2": {
                "ssh_user": "ec2-user",
                "private_key_path": "/keys/shared.pem",
                "remote_stage_dir": "/var/tmp/customer-vpn-router-2",
                "address_source": "private_ip",
                "proxy_jump_role": "cgnat_isp_head_end",
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
        self.assertEqual(derived["customer_vpn_router_1"]["target_host"], "172.31.48.20")
        self.assertEqual(derived["customer_vpn_router_1"]["proxy_jump_role"], "cgnat_isp_head_end")

    def test_aws_live_preflight_detects_router_private_ip_outside_subnet(self) -> None:
        package = {
            "manifest": {"service_id": "cgnat-service-example", "customer_id": "customer-example", "environment_name": "rpdb-empty-live"},
            "cgnat_head_end": {
                "subnet_id": "subnet-a",
                "security_group_ids": ["sg-a"],
                "ami_id": "ami-a",
                "iam_instance_profile": "profile-a",
                "key_pair_name": "muxer",
                "public_eip_strategy": "allocate_new",
            },
            "cgnat_isp_head_end": {
                "subnets": {"transit_subnet_id": "subnet-a", "customer_subnet_id": "subnet-b"},
                "customer_facing_private_ip": "172.31.48.10",
                "security_group_ids": ["sg-a"],
                "ami_id": "ami-a",
                "iam_instance_profile": "profile-a",
                "key_pair_name": "muxer",
                "public_eip_strategy": "allocate_new",
            },
            "customer_vpn_routers": [
                {
                    "role": "customer_vpn_router_1",
                    "subnet_id": "subnet-b",
                    "private_ip_address": "192.168.1.10",
                    "security_group_ids": ["sg-a"],
                    "ami_id": "ami-a",
                    "iam_instance_profile": "profile-a",
                    "key_pair_name": "muxer",
                }
            ],
            "dependencies": {"aws": {"vpc_id": "vpc-a"}},
        }
        inventory = {
            "sts_identity": {"Account": "123456789012"},
            "subnets": [
                {"SubnetId": "subnet-a", "VpcId": "vpc-a", "AvailabilityZone": "us-east-1a", "CidrBlock": "172.31.32.0/20"},
                {"SubnetId": "subnet-b", "VpcId": "vpc-a", "AvailabilityZone": "us-east-1a", "CidrBlock": "172.31.48.0/20"},
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
        self.assertIn("customer_vpn_router_1_private_ip_outside_subnet", issue_codes)

    def test_build_predeploy_review_reports_ready_state_with_customer_router_count(self) -> None:
        bundle = json.loads((CGNAT_ROOT / "framework" / "config" / "deployment-bundle.example.json").read_text(encoding="utf-8"))
        prep_summary = {"validation_ok": True, "aws_live_create_allowed": True, "aws_preflight_ready_for_live_apply": True}
        preflight_result = {"issues": []}
        aws_apply_result = {
            "head_end": {"status": "dry_run_ok"},
            "isp_head_end": {"status": "dry_run_ok"},
            "customer_vpn_routers": [
                {"role": "customer_vpn_router_1", "status": "dry_run_ok"},
                {"role": "customer_vpn_router_2", "status": "dry_run_ok"},
            ],
            "post_create_actions": [
                {"status": "dry_run_ok"},
                {"status": "dry_run_ok"},
                {"status": "deferred_until_live_create"},
                {"status": "deferred_until_live_create"},
            ],
        }

        review = build_predeploy_review(
            bundle,
            prep_summary,
            preflight_result,
            aws_apply_result,
            host_access_strategy_path=str(CGNAT_ROOT / "server" / "config" / "host-access-strategy.example.json"),
            materials_manifest_path=str(CGNAT_ROOT / "build" / "sample-from-split" / "materials.json"),
        )

        self.assertTrue(review["ready_for_hard_review"])
        self.assertEqual(review["deployment_model"]["customer_router_count"], 2)
        self.assertGreaterEqual(len(review["open_items_before_host_apply"]), 2)


if __name__ == "__main__":
    unittest.main()
