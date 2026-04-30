from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


CGNAT_ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK_SRC = CGNAT_ROOT / "framework" / "src"
sys.path.insert(0, str(FRAMEWORK_SRC))

from cgnat.backend_integration import build_backend_customer_request, build_backend_customer_requests, build_backend_integration_summary  # noqa: E402
from cgnat.deployment_stage_review import build_deployment_stage_review  # noqa: E402


class BackendIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bundle = json.loads(
            (CGNAT_ROOT / "framework" / "config" / "deployment-bundle.example.json").read_text(encoding="utf-8")
        )
        self.integration = {
            "environment": "rpdb-empty-live",
            "customer_name": "scenario1-backend",
            "customer_name_template": "scenario1-backend-{router_role}",
            "backend_psk_secret_ref": "/demo/backend/psk",
            "backend_psk_secret_ref_template": "/demo/backend/{customer_name}/psk",
            "service_local_subnets_mode": "customer_facing_public_ip_loopback",
            "ipsec": {"ike_version": "ikev2"},
            "ipsec_initiation": {
                "mode": "customer_only",
                "headend_can_initiate": False,
                "customer_can_initiate": True,
            },
            "post_ipsec_nat": {
                "mode": "netmap",
                "mapping_strategy": "one_to_one",
                "tcp_mss_clamp": 1360,
            },
        }

    def test_build_backend_customer_request_uses_device_loopback_and_translation(self) -> None:
        device = self.bundle["sot"]["customer_devices"][0]
        request = build_backend_customer_request(self.bundle, self.integration, device=device, index=1)

        self.assertEqual(request["customer"]["peer"]["public_ip"], "10.250.1.10")
        self.assertEqual(request["customer"]["peer"]["remote_id"], "10.250.1.10")
        self.assertEqual(request["customer"]["selectors"]["local_subnets"], ["198.51.100.10/32"])
        self.assertEqual(request["customer"]["selectors"]["remote_subnets"], ["10.20.30.0/24"])
        self.assertTrue(request["customer"]["post_ipsec_nat"]["enabled"])
        self.assertEqual(request["customer"]["post_ipsec_nat"]["translated_subnets"], ["10.128.10.0/24"])

    def test_build_backend_customer_requests_returns_one_request_per_customer_router(self) -> None:
        requests = build_backend_customer_requests(self.bundle, self.integration)

        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]["router_role"], "customer_vpn_router_1")
        self.assertEqual(requests[1]["router_role"], "customer_vpn_router_2")
        self.assertEqual(requests[0]["request"]["customer"]["peer"]["public_ip"], "10.250.1.10")
        self.assertEqual(requests[1]["request"]["customer"]["peer"]["public_ip"], "10.250.1.11")
        self.assertEqual(requests[0]["customer_name"], "scenario1-backend-customer_vpn_router_1")
        self.assertEqual(requests[1]["customer_name"], "scenario1-backend-customer_vpn_router_2")
        self.assertEqual(requests[0]["request"]["customer"]["peer"]["psk_secret_ref"], "/demo/backend/scenario1-backend-customer_vpn_router_1/psk")
        self.assertEqual(requests[1]["request"]["customer"]["peer"]["psk_secret_ref"], "/demo/backend/scenario1-backend-customer_vpn_router_2/psk")

    def test_build_backend_integration_summary_reports_multiple_devices(self) -> None:
        request_records = [
            {
                "device_name": "customer-device-1",
                "router_role": "customer_vpn_router_1",
                "customer_name": "scenario1-backend-customer_vpn_router_1",
                "customer_loopback_ip": "10.250.1.10",
                "request_path": "E:/fake/customer1.yaml",
                "validation_ok": True,
                "deploy_dry_run_ok": True,
                "deploy_plan": {
                    "selected_targets": {"headend_family": "non_nat"},
                    "live_gate": {"allow_live_apply_now": True},
                },
            },
            {
                "device_name": "customer-device-2",
                "router_role": "customer_vpn_router_2",
                "customer_name": "scenario1-backend-customer_vpn_router_2",
                "customer_loopback_ip": "10.250.1.11",
                "request_path": "E:/fake/customer2.yaml",
                "validation_ok": True,
                "deploy_dry_run_ok": True,
                "deploy_plan": {
                    "selected_targets": {"headend_family": "non_nat"},
                    "live_gate": {"allow_live_apply_now": True},
                },
            },
        ]

        summary = build_backend_integration_summary(
            bundle=self.bundle,
            integration=self.integration,
            request_records=request_records,
        )

        self.assertTrue(summary["validation_ok"])
        self.assertTrue(summary["deploy_dry_run_ok"])
        self.assertEqual(summary["customer_router_count"], 2)
        self.assertEqual(summary["backend_customer_names"], ["scenario1-backend-customer_vpn_router_1", "scenario1-backend-customer_vpn_router_2"])
        self.assertEqual(summary["customer_loopback_backend_identities"], ["10.250.1.10", "10.250.1.11"])
        self.assertEqual(summary["service_local_subnets"], ["198.51.100.10/32"])


class DeploymentStageReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bundle = json.loads(
            (CGNAT_ROOT / "framework" / "config" / "deployment-bundle.example.json").read_text(encoding="utf-8")
        )

    def test_build_deployment_stage_review_requires_backend_live_gate(self) -> None:
        cgnat_review = {"ready_for_hard_review": True}
        backend_integration = {
            "validation_ok": True,
            "deploy_dry_run_ok": True,
            "live_gate": {"allow_live_apply_now": False},
            "backend_headend_family": "non_nat",
            "backend_customer_name": "scenario1-backend-customer_vpn_router_1",
            "backend_customer_names": ["scenario1-backend-customer_vpn_router_1", "scenario1-backend-customer_vpn_router_2"],
        }

        review = build_deployment_stage_review(
            bundle=self.bundle,
            cgnat_review=cgnat_review,
            backend_integration=backend_integration,
        )

        self.assertFalse(review["ready_for_deployment_stage_review"])
        self.assertFalse(review["status_summary"]["backend_live_gate_allow_live_apply_now"])
        self.assertEqual(review["deployment_model"]["customer_router_count"], 2)
        self.assertEqual(
            review["deployment_model"]["backend_customer_names"],
            ["scenario1-backend-customer_vpn_router_1", "scenario1-backend-customer_vpn_router_2"],
        )

    def test_build_deployment_stage_review_reports_ready_when_all_inputs_are_green(self) -> None:
        cgnat_review = {"ready_for_hard_review": True}
        backend_integration = {
            "validation_ok": True,
            "deploy_dry_run_ok": True,
            "live_gate": {"allow_live_apply_now": True},
            "backend_headend_family": "non_nat",
            "backend_customer_name": "scenario1-backend-customer_vpn_router_1",
            "backend_customer_names": ["scenario1-backend-customer_vpn_router_1", "scenario1-backend-customer_vpn_router_2"],
        }

        review = build_deployment_stage_review(
            bundle=self.bundle,
            cgnat_review=cgnat_review,
            backend_integration=backend_integration,
        )

        self.assertTrue(review["ready_for_deployment_stage_review"])
        self.assertTrue(review["status_summary"]["backend_live_gate_allow_live_apply_now"])


if __name__ == "__main__":
    unittest.main()
