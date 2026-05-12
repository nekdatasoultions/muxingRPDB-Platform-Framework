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
        self.assertIn("customer_router_outer_tunnels_established", validation_targets["required_checks"])
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
        isp_eip_action = next(
            (
                action
                for action in plan["post_create_actions"]["actions"]
                if action["name"] in {"associate_isp_head_end_eip", "allocate_and_associate_isp_head_end_eip"}
            ),
            None,
        )

        self.assertTrue(plan["deployment_ready_for_live_create"])
        self.assertTrue(readiness["live_create_allowed"])
        self.assertEqual(len(router_requests), 2)
        self.assertEqual(router_requests[0]["role"], "customer_vpn_router_1")
        self.assertEqual(router_requests[1]["role"], "customer_vpn_router_2")
        self.assertIn("disable_source_dest_check_head_end", action_names)
        self.assertIn("disable_source_dest_check_isp_head_end", action_names)
        if isp_eip_action is not None:
            self.assertEqual(isp_eip_action["association_target"], "transit_network_interface")

    def test_aws_deploy_plan_can_scope_to_customer_router_requests_only(self) -> None:
        aws_output = self.tempdir_path / "aws-package"
        deploy_output = self.tempdir_path / "aws-deploy-plan-routers-only"

        self._run(str(CGNAT_ROOT / "aws" / "scripts" / "render_aws_package.py"), str(self.bundle_path), str(aws_output))
        self._run(
            str(CGNAT_ROOT / "aws" / "scripts" / "deploy_scenario1_aws.py"),
            str(aws_output),
            str(deploy_output),
            "--mode",
            "plan",
            "--role-scope",
            "customer-vpn-routers",
        )

        plan = json.loads((deploy_output / "deployment-plan.json").read_text(encoding="utf-8"))
        readiness = json.loads((deploy_output / "deployment-readiness.json").read_text(encoding="utf-8"))
        router_requests = json.loads((deploy_output / "customer-vpn-router-run-instances-requests.json").read_text(encoding="utf-8"))

        self.assertTrue(plan["deployment_ready_for_live_create"])
        self.assertEqual(plan["role_scope"], "customer-vpn-routers")
        self.assertEqual(readiness["role_scope"], "customer-vpn-routers")
        self.assertEqual(set(plan["ec2_requests"]), {"customer_vpn_routers"})
        self.assertEqual(len(router_requests), 2)
        self.assertEqual(plan["post_create_actions"]["actions"], [])
        self.assertFalse((deploy_output / "head-end-run-instances-request.json").exists())
        self.assertFalse((deploy_output / "isp-head-end-run-instances-request.json").exists())

    def test_server_config_renderer_outputs_per_router_artifacts(self) -> None:
        server_output = self.tempdir_path / "server-package"
        config_output = self.tempdir_path / "server-configs"

        self._run(str(CGNAT_ROOT / "server" / "scripts" / "render_server_package.py"), str(self.bundle_path), str(server_output))
        self._run(str(CGNAT_ROOT / "server" / "scripts" / "render_scenario1_server_configs.py"), str(server_output), str(config_output))

        runtime_inputs = json.loads((config_output / "runtime-inputs.json").read_text(encoding="utf-8"))
        customer_router_configs = json.loads((config_output / "customer-vpn-routers-config.json").read_text(encoding="utf-8"))
        router1_conf = (config_output / "customer_vpn_router_1-inner-swanctl.conf").read_text(encoding="utf-8")
        router2_conf = (config_output / "customer_vpn_router_2-inner-swanctl.conf").read_text(encoding="utf-8")
        router1_outer_conf = (config_output / "customer_vpn_router_1-outer-swanctl.conf").read_text(encoding="utf-8")
        router2_outer_conf = (config_output / "customer_vpn_router_2-outer-swanctl.conf").read_text(encoding="utf-8")
        router1_env = (config_output / "customer_vpn_router_1-runtime.env").read_text(encoding="utf-8")
        router1_loopback = (config_output / "customer_vpn_router_1-loopback.sh").read_text(encoding="utf-8")
        router1_xfrm = (config_output / "customer_vpn_router_1-xfrm.sh").read_text(encoding="utf-8")
        router1_strongswan_conf = (config_output / "customer_vpn_router_1-strongswan.conf").read_text(encoding="utf-8")
        head_conf = (config_output / "cgnat-head-end-swanctl.conf").read_text(encoding="utf-8")
        head_strongswan_conf = (config_output / "cgnat-head-end-strongswan.conf").read_text(encoding="utf-8")
        head_xfrm = (config_output / "cgnat-head-end-xfrm.sh").read_text(encoding="utf-8")
        isp_runtime = (config_output / "cgnat-isp-head-end-runtime.env").read_text(encoding="utf-8")
        isp_conf = (config_output / "cgnat-isp-head-end-swanctl.conf").read_text(encoding="utf-8")
        isp_forwarding = (config_output / "cgnat-isp-head-end-forwarding.sh").read_text(encoding="utf-8")
        expected_peer_count = len(runtime_inputs["head_end"]["outer_tunnel"]["accepted_peers"])
        expected_router1_remote = runtime_inputs["customer_vpn_routers"][0]["outer_tunnel"]["remote_addrs"][0]
        expected_router2_remote = runtime_inputs["customer_vpn_routers"][1]["outer_tunnel"]["remote_addrs"][0]

        self.assertEqual(len(runtime_inputs["customer_vpn_routers"]), 2)
        self.assertEqual(len(customer_router_configs), 2)
        self.assertEqual(runtime_inputs["runtime_style"]["outer_transport"], "strongswan_swanctl_xfrmi")
        self.assertEqual(runtime_inputs["runtime_style"]["inner_vpn"], "strongswan_swanctl_psk")
        self.assertEqual(runtime_inputs["customer_vpn_routers"][0]["outer_tunnel"]["xfrm_if_id"], 101)
        self.assertEqual(runtime_inputs["customer_vpn_routers"][1]["outer_tunnel"]["xfrm_if_id"], 102)
        self.assertEqual(runtime_inputs["customer_vpn_routers"][0]["service_ip_interface_name"], "cglan-r1")
        self.assertEqual(runtime_inputs["customer_vpn_routers"][0]["service_ip_address"], "10.20.30.10")
        self.assertIn("auth = psk", router1_conf)
        self.assertIn("auth = psk", router2_conf)
        self.assertIn("local_addrs = 10.250.1.10", router1_conf)
        self.assertIn("local_addrs = 10.250.1.11", router2_conf)
        self.assertIn("auth = pubkey", router1_outer_conf)
        self.assertIn("auth = pubkey", router2_outer_conf)
        self.assertIn("authorities {", head_conf)
        self.assertIn(f"cacert = {runtime_inputs['service_id']}-outer-ca.crt", head_conf)
        self.assertIn("authorities {", router1_outer_conf)
        self.assertIn(f"cacert = {runtime_inputs['service_id']}-outer-ca.crt", router1_outer_conf)
        self.assertIn("local_ts = 0.0.0.0/0", head_conf)
        self.assertIn("remote_addrs = %any", head_conf)
        self.assertEqual(head_conf.count("version = 2"), expected_peer_count)
        self.assertIn(f"remote_addrs = {expected_router1_remote}", router1_outer_conf)
        self.assertIn(f"remote_addrs = {expected_router2_remote}", router2_outer_conf)
        self.assertIn("ip link add \"$CGNAT_OUTER_XFRM_INTERFACE\" type xfrm", router1_xfrm)
        self.assertIn("sysctl -w net.ipv4.ip_forward=1", router1_xfrm)
        self.assertIn("disable_policy=1", router1_xfrm)
        self.assertIn("ip route replace \"${CGNAT_TERMINATION_PUBLIC_LOOPBACK}/32\" dev \"$CGNAT_GRE_NAME\"", (config_output / "cgnat-head-end-routes.sh").read_text(encoding="utf-8"))
        self.assertIn("ip route replace \"172.31.48.20/32\" dev \"cgxfrm-r1\"", head_xfrm)
        self.assertIn("install_routes = no", head_strongswan_conf)
        self.assertIn("install_routes = no", router1_strongswan_conf)
        self.assertIn("CGNAT_CUSTOMER_DEFAULT_GATEWAY_IP", router1_env)
        self.assertIn("CGNAT_CUSTOMER_SERVICE_INTERFACE=\"cglan-r1\"", router1_env)
        self.assertIn("CGNAT_CUSTOMER_SERVICE_IP=\"10.20.30.10\"", router1_env)
        self.assertIn("CGNAT_OUTER_REMOTE_PUBLIC_IP", router1_env)
        self.assertIn("CGNAT_OUTER_XFRM_INTERFACE", router1_env)
        self.assertIn("CGNAT_INNER_VPN_SECRET_CONF_PATH", router1_env)
        self.assertIn("ip link add \"$CGNAT_CUSTOMER_SERVICE_INTERFACE\" type dummy", router1_loopback)
        self.assertIn("ip addr replace \"${CGNAT_CUSTOMER_LOOPBACK_IP}/32\" dev lo", router1_loopback)
        self.assertIn("ip addr replace \"$CGNAT_KNOWN_INSIDE_IDENTITY\" dev \"$CGNAT_CUSTOMER_SERVICE_INTERFACE\"", router1_loopback)
        self.assertIn("CGNAT_ISP_CUSTOMER_PRIVATE_IP", isp_runtime)
        self.assertIn("CGNAT_ISP_UPLINK_INTERFACE", isp_runtime)
        self.assertIn("CGNAT_TRANSPORT_ROLE=", isp_runtime)
        self.assertNotIn("CGNAT_OUTER_LOCAL_IDENTITY=", isp_runtime)
        self.assertIn("NAT/transit only", isp_conf)
        self.assertIn("No IPsec daemon terminates on this node", isp_conf)
        self.assertIn("table ip cgnat_scenario1_nat", isp_forwarding)
        self.assertIn("masquerade", isp_forwarding)
        self.assertIn('ip saddr $CUSTOMER_SUBNET oifname "$CGNAT_ISP_UPLINK_INTERFACE" masquerade', isp_forwarding)
        self.assertIn("nft -f /etc/nftables.d/cgnat-scenario1-isp.nft", isp_forwarding)
        self.assertFalse((config_output / "cgnat-isp-head-end-inner-swanctl.conf").exists())

    def test_server_config_renderer_prefers_explicit_cgnat_handoff_remote(self) -> None:
        bundle = json.loads(self.bundle_path.read_text(encoding="utf-8"))
        preferred_class = bundle["sot"]["backend_selection"]["preferred_class"]
        bundle["operations"]["backend_vpn_head_ends"][preferred_class][0]["cgnat_handoff_remote"] = "172.31.69.214"
        bundle_path = self.tempdir_path / "deployment-bundle.override.json"
        bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        server_output = self.tempdir_path / "server-package-override"
        config_output = self.tempdir_path / "server-configs-override"

        self._run(str(CGNAT_ROOT / "server" / "scripts" / "render_server_package.py"), str(bundle_path), str(server_output))
        self._run(str(CGNAT_ROOT / "server" / "scripts" / "render_scenario1_server_configs.py"), str(server_output), str(config_output))

        runtime_inputs = json.loads((config_output / "runtime-inputs.json").read_text(encoding="utf-8"))
        self.assertEqual(runtime_inputs["head_end"]["gre_runtime"]["remote_ip"], "172.31.69.214")

    def test_server_config_renderer_uses_service_reachable_subnets_for_inner_tunnel_selectors(self) -> None:
        bundle = json.loads(self.bundle_path.read_text(encoding="utf-8"))
        bundle["sot"]["backend_selection"]["service_reachable_subnets"] = [
            "198.51.100.10/32",
            "194.138.36.80/28",
        ]
        bundle_path = self.tempdir_path / "deployment-bundle.reachable-subnets.json"
        bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        server_output = self.tempdir_path / "server-package-reachable-subnets"
        config_output = self.tempdir_path / "server-configs-reachable-subnets"

        self._run(str(CGNAT_ROOT / "server" / "scripts" / "render_server_package.py"), str(bundle_path), str(server_output))
        self._run(str(CGNAT_ROOT / "server" / "scripts" / "render_scenario1_server_configs.py"), str(server_output), str(config_output))

        router1_conf = (config_output / "customer_vpn_router_1-inner-swanctl.conf").read_text(encoding="utf-8")
        router1_env = (config_output / "customer_vpn_router_1-runtime.env").read_text(encoding="utf-8")
        backend_expectations = json.loads((server_output / "backend-expectations.json").read_text(encoding="utf-8"))
        validation_targets = json.loads((server_output / "validation-targets.json").read_text(encoding="utf-8"))
        validation_commands = (config_output / "validation-commands.md").read_text(encoding="utf-8")

        self.assertIn("remote_ts = 198.51.100.10/32,194.138.36.80/28", router1_conf)
        self.assertIn('CGNAT_INNER_REMOTE_SELECTORS="198.51.100.10/32,194.138.36.80/28"', router1_env)
        self.assertEqual(
            backend_expectations["service_reachable_subnets"],
            ["198.51.100.10/32", "194.138.36.80/28"],
        )
        self.assertIn("smartgateway_downstream_encrypts_visible_for_customer_identities", validation_targets["required_checks"])
        self.assertEqual(validation_targets["downstream_validation"]["success_signal"], "outbound_encrypts_visible_for_all_customer_identities")
        self.assertFalse(validation_targets["downstream_validation"]["reply_required"])
        source_identities = {
            entry["role"]: entry["source_identity"]
            for entry in validation_targets["downstream_validation"]["source_identities"]
        }
        self.assertEqual(source_identities["customer_vpn_router_1"], "10.20.30.10/32")
        self.assertEqual(source_identities["customer_vpn_router_2"], "10.20.30.11/32")
        self.assertIn("Replies are optional for this downstream check", validation_commands)

    def test_prepare_scenario1_host_apply_outputs_four_host_bundles(self) -> None:
        server_output = self.tempdir_path / "server-package"
        config_output = self.tempdir_path / "server-configs"
        host_apply_output = self.tempdir_path / "host-apply"

        self._run(str(CGNAT_ROOT / "server" / "scripts" / "render_server_package.py"), str(self.bundle_path), str(server_output))
        self._run(str(CGNAT_ROOT / "server" / "scripts" / "render_scenario1_server_configs.py"), str(server_output), str(config_output))
        self._run(str(CGNAT_ROOT / "server" / "scripts" / "prepare_scenario1_host_apply.py"), str(config_output), str(host_apply_output))

        manifest = json.loads((host_apply_output / "package-manifest.json").read_text(encoding="utf-8"))
        apply_order = json.loads((host_apply_output / "apply-order.json").read_text(encoding="utf-8"))
        head_apply = (host_apply_output / "hosts" / "cgnat-head-end" / "apply.sh").read_text(encoding="utf-8")
        isp_apply = (host_apply_output / "hosts" / "cgnat-isp-head-end" / "apply.sh").read_text(encoding="utf-8")
        router_apply = (host_apply_output / "hosts" / "customer-vpn-router-1" / "apply.sh").read_text(encoding="utf-8")

        self.assertEqual(len(manifest["hosts"]), 4)
        self.assertTrue((host_apply_output / "hosts" / "customer-vpn-router-1" / "apply.sh").exists())
        self.assertTrue((host_apply_output / "hosts" / "customer-vpn-router-2" / "preflight.sh").exists())
        self.assertTrue((host_apply_output / "hosts" / "customer-vpn-router-1" / "customer_vpn_router_1-outer-swanctl.conf").exists())
        self.assertTrue((host_apply_output / "hosts" / "customer-vpn-router-1" / "customer_vpn_router_1-strongswan.conf").exists())
        self.assertEqual(apply_order["steps"][0]["role"], "cgnat_head_end")
        self.assertIn("customer_vpn_router_1", [step["role"] for step in apply_order["steps"] if "role" in step])
        self.assertIn("swanctl --load-all", head_apply)
        self.assertIn("cgnat-head-end-xfrm.sh", head_apply)
        self.assertIn("install_strongswan_from_source()", head_apply)
        self.assertIn("if (( ${#deps[@]} )); then", head_apply)
        self.assertNotIn("curl tar gzip", head_apply)
        self.assertIn("command -v curl >/dev/null || deps+=(curl)", head_apply)
        self.assertIn("trap \"rm -rf '$workdir'\" RETURN", head_apply)
        self.assertIn("cat > /etc/swanctl/swanctl.conf <<'EOF'", head_apply)
        self.assertIn("include conf.d/*.conf", head_apply)
        self.assertIn("systemctl stop \"$service\" >/dev/null 2>&1 || true", head_apply)
        self.assertIn("pkill -x pluto >/dev/null 2>&1 || true", head_apply)
        self.assertIn("install -m 0644 \"$SCRIPT_DIR/cgnat-head-end-strongswan.conf\"", head_apply)
        self.assertIn("stage_and_apply_transit_only", json.dumps(apply_order))
        self.assertIn("CGNAT_OUTER_CLIENT_CERT_PATH", router_apply)
        self.assertIn("swanctl --initiate --ike \"$CGNAT_OUTER_CONNECTION_NAME\"", router_apply)
        self.assertIn("swanctl --initiate --ike \"$CGNAT_INNER_CONNECTION_NAME\"", router_apply)
        self.assertIn("RAW_SECRET_FILE=", router_apply)
        self.assertIn("CGNAT_INNER_VPN_SECRET_CONF_PATH", router_apply)
        self.assertIn("install -m 0644 \"$SCRIPT_DIR/customer_vpn_router_1-strongswan.conf\"", router_apply)
        self.assertIn("cat > /etc/swanctl/swanctl.conf <<'EOF'", router_apply)
        self.assertIn("pkill -x pluto >/dev/null 2>&1 || true", router_apply)
        self.assertNotIn("CGNAT_ISP_HEAD_END_CLIENT_CERT_PATH", isp_apply)
        self.assertNotIn("ipsec auto --up", isp_apply)
        self.assertNotIn("certutil", router_apply)
        self.assertNotIn(b"\r\n", (host_apply_output / "hosts" / "cgnat-head-end" / "apply.sh").read_bytes())

    def test_prepare_scenario1_host_apply_overrides_router_outer_remote_ip_from_host_access(self) -> None:
        server_output = self.tempdir_path / "server-package"
        config_output = self.tempdir_path / "server-configs"
        host_apply_output = self.tempdir_path / "host-apply-live"
        host_access_path = self.tempdir_path / "host-access.json"

        host_access = {
            "cgnat_head_end": {
                "ssh_user": "ec2-user",
                "target_host": "44.198.245.90",
                "private_key_path": "/keys/shared.pem",
                "remote_stage_dir": "/var/tmp/cgnat-head-end",
            }
        }
        host_access_path.write_text(json.dumps(host_access, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self._run(str(CGNAT_ROOT / "server" / "scripts" / "render_server_package.py"), str(self.bundle_path), str(server_output))
        self._run(str(CGNAT_ROOT / "server" / "scripts" / "render_scenario1_server_configs.py"), str(server_output), str(config_output))
        self._run(
            str(CGNAT_ROOT / "server" / "scripts" / "prepare_scenario1_host_apply.py"),
            str(config_output),
            str(host_apply_output),
            "--host-access-json",
            str(host_access_path),
        )

        router1_env = (host_apply_output / "hosts" / "customer-vpn-router-1" / "customer_vpn_router_1-runtime.env").read_text(encoding="utf-8")
        router1_outer_conf = (host_apply_output / "hosts" / "customer-vpn-router-1" / "customer_vpn_router_1-outer-swanctl.conf").read_text(encoding="utf-8")

        self.assertIn('CGNAT_OUTER_REMOTE_PUBLIC_IP="44.198.245.90"', router1_env)
        self.assertIn("remote_addrs = 44.198.245.90", router1_outer_conf)

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
        router1_outer_conf = (host_apply_output / "hosts" / "customer-vpn-router-1" / "customer_vpn_router_1-outer-swanctl.conf").read_text(encoding="utf-8")
        router1_secret = (host_apply_output / "hosts" / "customer-vpn-router-1" / f"{materials_manifest['service_id']}-customer_vpn_router_1-inner.psk").read_text(encoding="utf-8").strip()
        router2_secret = (host_apply_output / "hosts" / "customer-vpn-router-2" / f"{materials_manifest['service_id']}-customer_vpn_router_2-inner.psk").read_text(encoding="utf-8").strip()

        self.assertEqual(len(materials_manifest["inner_vpn_materials"]), 2)
        self.assertEqual(len(materials_manifest["certificate_material"]["customer_router_outer_clients"]), 2)
        self.assertIn("auth = psk", router1_conf)
        self.assertIn("auth = psk", router2_conf)
        self.assertIn("auth = pubkey", router1_outer_conf)
        self.assertTrue(router1_secret)
        self.assertTrue(router2_secret)
        self.assertTrue((host_apply_output / "hosts" / "customer-vpn-router-1" / f"{materials_manifest['service_id']}-customer_vpn_router_1-inner.psk").exists())
        self.assertTrue((host_apply_output / "hosts" / "customer-vpn-router-1" / f"{materials_manifest['service_id']}-customer_vpn_router_1-outer.crt").exists())
        self.assertTrue((host_apply_output / "hosts" / "customer-vpn-router-1" / f"{materials_manifest['service_id']}-outer-ca.crt").exists())

    def test_materialize_demo_materials_prefers_explicit_inner_vpn_psk(self) -> None:
        materials_output = self.tempdir_path / "demo-materials-explicit-psk"
        bundle = json.loads(self.bundle_path.read_text(encoding="utf-8"))
        bundle["sot"]["customer_devices"][0]["inner_vpn_psk"] = "router1-live-psk"
        bundle["sot"]["customer_devices"][1]["inner_vpn_psk"] = "router2-live-psk"
        explicit_bundle_path = self.tempdir_path / "deployment-bundle.explicit-psk.json"
        explicit_bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self._run(str(CGNAT_ROOT / "server" / "scripts" / "materialize_scenario1_demo_materials.py"), str(explicit_bundle_path), str(materials_output))

        materials_manifest = json.loads((materials_output / "materials-manifest.json").read_text(encoding="utf-8"))
        router1_secret = Path(materials_manifest["inner_vpn_materials"][0]["secret_path"]).read_text(encoding="utf-8").strip()
        router2_secret = Path(materials_manifest["inner_vpn_materials"][1]["secret_path"]).read_text(encoding="utf-8").strip()

        self.assertEqual(router1_secret, "router1-live-psk")
        self.assertEqual(router2_secret, "router2-live-psk")

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
        self.assertIn("ProxyCommand", router1_stage)
        self.assertIn("172.31.48.20", router1_stage)
        self.assertIn("LOCAL_BUNDLE_DIR=", router1_stage)
        self.assertNotIn("SCRIPT_DIR=", router1_stage)

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

    def test_update_bundle_public_ips_from_aws_apply_updates_effective_live_bundle(self) -> None:
        apply_result_path = self.tempdir_path / "apply-result.json"
        output_bundle_path = self.tempdir_path / "deployment-bundle.updated.json"

        apply_result = {
            "post_create_actions": [
                {
                    "service_role": "cgnat_head_end",
                    "response": {"allocation": {"PublicIp": "54.10.10.10", "AllocationId": "eipalloc-head"}},
                },
                {
                    "service_role": "cgnat_isp_head_end",
                    "response": {"allocation": {"PublicIp": "54.10.10.11", "AllocationId": "eipalloc-isp"}},
                },
            ]
        }
        apply_result_path.write_text(json.dumps(apply_result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self._run(
            str(CGNAT_ROOT / "framework" / "scripts" / "update_bundle_public_ips_from_aws_apply.py"),
            str(self.bundle_path),
            str(apply_result_path),
            str(output_bundle_path),
        )

        updated_bundle = json.loads(output_bundle_path.read_text(encoding="utf-8"))
        self.assertEqual(updated_bundle["operations"]["cgnat_head_end"]["allocated_public_ip"], "54.10.10.10")
        self.assertEqual(updated_bundle["operations"]["cgnat_head_end"]["public_eip_allocation_id"], "eipalloc-head")
        self.assertEqual(updated_bundle["operations"]["cgnat_isp_head_end"]["allocated_public_ip"], "54.10.10.11")
        self.assertEqual(updated_bundle["operations"]["cgnat_isp_head_end"]["public_eip_allocation_id"], "eipalloc-isp")

    def test_prepare_scenario1_muxer_ingress_shim_outputs_peer_specific_rules(self) -> None:
        bundle = json.loads(self.bundle_path.read_text(encoding="utf-8"))
        preferred_class = bundle["sot"]["backend_selection"]["preferred_class"]
        bundle["operations"]["backend_vpn_head_ends"][preferred_class][0]["cgnat_handoff_remote"] = "172.31.69.214"
        bundle_path = self.tempdir_path / "deployment-bundle.muxer-shim.json"
        summary_path = self.tempdir_path / "backend-integration-summary.json"
        aws_apply_path = self.tempdir_path / "aws-apply-result.json"
        output_dir = self.tempdir_path / "muxer-ingress-shim"

        backend_summary = {
            "request_records": [
                {
                    "deploy_plan": {
                        "selected_targets": {
                            "muxer": {
                                "selector": {
                                    "private_ip": "172.31.69.214",
                                    "public_ip": "23.20.31.151",
                                }
                            },
                            "headend_active": {
                                "selector": {
                                    "private_ip": "172.31.40.223",
                                }
                            },
                        }
                    }
                }
            ]
        }
        aws_apply = {
            "head_end": {
                "response": {
                    "Instances": [
                        {"PrivateIpAddress": "172.31.38.227"}
                    ]
                }
            }
        }
        bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        summary_path.write_text(json.dumps(backend_summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        aws_apply_path.write_text(json.dumps(aws_apply, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self._run(
            str(CGNAT_ROOT / "server" / "scripts" / "prepare_scenario1_muxer_ingress_shim.py"),
            str(bundle_path),
            str(summary_path),
            str(aws_apply_path),
            str(output_dir),
        )

        runtime = json.loads((output_dir / "runtime-inputs.json").read_text(encoding="utf-8"))
        nft_apply = (output_dir / "nftables.apply.nft").read_text(encoding="utf-8")
        runtime_env = (output_dir / "runtime.env").read_text(encoding="utf-8")
        apply_sh = (output_dir / "apply.sh").read_text(encoding="utf-8")

        self.assertEqual(runtime["cgnat_head_end"]["private_ip"], "172.31.38.227")
        self.assertEqual(runtime["backend_head_end"]["private_ip"], "172.31.40.223")
        self.assertEqual(runtime["muxer"]["inside_ip"], "172.31.69.214")
        self.assertEqual(runtime["muxer"]["public_ip"], "23.20.31.151")
        self.assertIn("172.31.48.20", nft_apply)
        self.assertIn("172.31.48.21", nft_apply)
        self.assertIn("23.20.31.151", nft_apply)
        self.assertIn("172.31.40.223", nft_apply)
        self.assertIn("udp dport 4500", nft_apply)
        self.assertIn("udp sport 4500", nft_apply)
        self.assertIn('CGNAT_HEAD_END_PRIVATE_IP="172.31.38.227"', runtime_env)
        self.assertIn('ip tunnel add "$CGNAT_MUXER_SHIM_INTERFACE" mode gre local "$CGNAT_MUXER_INSIDE_IP" remote "$CGNAT_HEAD_END_PRIVATE_IP"', apply_sh)

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
