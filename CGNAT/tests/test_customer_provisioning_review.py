from __future__ import annotations

import sys
import unittest
from pathlib import Path


CGNAT_ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK_SRC = CGNAT_ROOT / "framework" / "src"
MUXER_ROOT = CGNAT_ROOT.parent / "muxer"
sys.path.insert(0, str(FRAMEWORK_SRC))
sys.path.insert(0, str(MUXER_ROOT / "src"))

from cgnat.customer_provisioning import (  # noqa: E402
    build_backend_surface_review,
    build_cgnat_combined_review,
    build_cgnat_headend_surface_review,
    build_cgnat_live_execution_plan,
    build_cgnat_live_test_bed_plan,
    build_cgnat_pki_surface_review,
    build_cgnat_rollback_plan,
    build_muxer_surface_review,
    render_cgnat_live_execution_checklist,
    validate_cgnat_request,
)
from muxerlib.customer_merge import load_yaml_file  # noqa: E402


class CustomerProvisioningReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request_doc = load_yaml_file(
            MUXER_ROOT / "config" / "customer-requests" / "examples" / "example-minimal-cgnat.yaml"
        )
        self.readiness = {
            "customer": {
                "name": "example-minimal-cgnat",
                "customer_class": "strict-non-nat",
                "transport_mode": "cgnat",
                "backend_cluster": "non-nat",
                "peer_ip": "203.0.113.51",
                "local_subnets": ["23.20.31.151/32", "194.138.36.86/32"],
                "remote_subnets": ["10.20.30.10/32"],
                "remote_host_cidrs": [],
            },
            "package_paths": {
                "bundle": "build/customer-pilots/example-minimal-cgnat/bundle",
                "bundle-validation.json": "build/customer-pilots/example-minimal-cgnat/bundle-validation.json",
            },
        }
        self.execution_plan = {
            "status": "dry_run_ready",
            "customer_name": "example-minimal-cgnat",
            "package": {
                "package_dir": "build/customer-deploy/example-minimal-cgnat/package",
                "readiness_path": "build/customer-deploy/example-minimal-cgnat/package/pilot-readiness.json",
            },
            "selected_targets": {
                "headend_family": "non_nat",
                "muxer": {"name": "muxer-single-prod-rpdb-empty-node"},
                "headend_active": {"name": "vpn-headend-non-nat-graviton-dev-rpdb-empty-headend-a"},
                "headend_standby": {"name": "vpn-headend-non-nat-graviton-dev-rpdb-empty-headend-b"},
                "cgnat_headend_active": {"name": "cgnat-head-end-rpdb-empty-a"},
            },
            "dry_run_gate": {
                "backup_refs": {
                    "muxer": "s3://demo/backups/muxer",
                    "non_nat_headend": "s3://demo/backups/non-nat-headend",
                    "selected_headend": "s3://demo/backups/non-nat-headend",
                    "selected_headend_key": "non_nat_headend",
                    "cgnat_headend": "s3://demo/backups/cgnat-headend",
                }
            },
        }
        self.shared_deploy_dir = CGNAT_ROOT / "build" / "review-test" / "shared-dry-run"

    def test_validate_cgnat_request_accepts_example(self) -> None:
        validate_cgnat_request(self.request_doc, request_path="example-minimal-cgnat.yaml")

    def test_surface_reviews_capture_expected_targets_and_metadata(self) -> None:
        backend = build_backend_surface_review(
            request_doc=self.request_doc,
            readiness=self.readiness,
            execution_plan=self.execution_plan,
            shared_deploy_dir=self.shared_deploy_dir,
        )
        muxer = build_muxer_surface_review(
            request_doc=self.request_doc,
            readiness=self.readiness,
            execution_plan=self.execution_plan,
        )
        cgnat_headend = build_cgnat_headend_surface_review(
            request_doc=self.request_doc,
            execution_plan=self.execution_plan,
        )
        pki_review = build_cgnat_pki_surface_review(
            request_doc=self.request_doc,
            output_dir=CGNAT_ROOT / "build" / "review-test" / "pki-reference",
        )

        self.assertEqual(backend["headend_family"], "non_nat")
        self.assertEqual(backend["targets"]["active"], "vpn-headend-non-nat-graviton-dev-rpdb-empty-headend-a")
        self.assertEqual(muxer["target"], "muxer-single-prod-rpdb-empty-node")
        self.assertEqual(muxer["backup_ref"], "s3://demo/backups/muxer")
        self.assertEqual(cgnat_headend["target"], "cgnat-head-end-rpdb-empty-a")
        self.assertEqual(cgnat_headend["transport_profile"]["customer_loopback_ip"], "10.250.1.10")
        self.assertEqual(cgnat_headend["transport_profile"]["known_inside_identity"], "10.20.30.10/32")
        self.assertEqual(pki_review["mode"], "reference")
        self.assertTrue(pki_review["ready_for_review"])
        self.assertEqual(
            pki_review["headend"]["identity_ref"],
            "cgnat-head-end/example-minimal-cgnat",
        )
        self.assertEqual(
            pki_review["customer_handoff"]["package_name"],
            "example-minimal-cgnat-customer-router-1",
        )

    def test_combined_review_and_rollback_plan_stay_ready(self) -> None:
        backend = build_backend_surface_review(
            request_doc=self.request_doc,
            readiness=self.readiness,
            execution_plan=self.execution_plan,
            shared_deploy_dir=self.shared_deploy_dir,
        )
        muxer = build_muxer_surface_review(
            request_doc=self.request_doc,
            readiness=self.readiness,
            execution_plan=self.execution_plan,
        )
        cgnat_headend = build_cgnat_headend_surface_review(
            request_doc=self.request_doc,
            execution_plan=self.execution_plan,
        )
        pki_review = build_cgnat_pki_surface_review(
            request_doc=self.request_doc,
            output_dir=CGNAT_ROOT / "build" / "review-test" / "pki-reference-combined",
        )
        rollback = build_cgnat_rollback_plan(
            execution_plan=self.execution_plan,
            test_bed_customer="CGNAT customer 1",
        )
        live_test_bed = build_cgnat_live_test_bed_plan(
            request_doc=self.request_doc,
            execution_plan=self.execution_plan,
            rollback_plan=rollback,
            test_bed_customer="CGNAT customer 1",
        )
        live_execution = build_cgnat_live_execution_plan(
            request_doc=self.request_doc,
            execution_plan=self.execution_plan,
            pki_review=pki_review,
            rollback_plan=rollback,
            live_test_bed_plan=live_test_bed,
        )
        combined = build_cgnat_combined_review(
            request_doc=self.request_doc,
            readiness=self.readiness,
            execution_plan=self.execution_plan,
            backend_review=backend,
            muxer_review=muxer,
            cgnat_headend_review=cgnat_headend,
            pki_review=pki_review,
            rollback_plan=rollback,
            live_test_bed_plan=live_test_bed,
            live_execution_plan=live_execution,
            shared_deploy_dir=self.shared_deploy_dir,
        )
        checklist = render_cgnat_live_execution_checklist(
            live_execution_plan=live_execution,
        )

        self.assertTrue(combined["ready_for_review"])
        self.assertEqual(combined["surface_status"]["shared_dry_run"], "dry_run_ready")
        self.assertTrue(rollback["preconditions"]["backup_before_remove_required"])
        self.assertIn("CGNAT customer 1", " ".join(rollback["notes"]))
        self.assertEqual(live_test_bed["test_bed_customer"], "CGNAT customer 1")
        self.assertTrue(live_test_bed["backup_gate"]["required"])
        self.assertEqual(
            live_test_bed["backup_gate"]["references"]["backend_headend"],
            "s3://demo/backups/non-nat-headend",
        )
        self.assertEqual(combined["surface_status"]["pki"], "ready_for_review")
        self.assertIn("pki", combined["surfaces"])
        self.assertIn("live_execution_plan", combined["surfaces"])
        self.assertIn("LIVE_EXECUTION_CHECKLIST.md", combined["surfaces"]["live_execution_checklist"])
        self.assertTrue(live_execution["customer_device_backup_required"])
        self.assertEqual(
            live_execution["customer_handoff"]["package_name"],
            "example-minimal-cgnat-customer-router-1",
        )
        self.assertIn("capture_customer_device_backups", " ".join(live_execution["customer_device_apply_order"]))
        self.assertIn("Package name", checklist)
        self.assertIn("live_test_bed_plan", combined["surfaces"])
        self.assertIn("CGNAT customer 1", " ".join(combined["notes"]))


if __name__ == "__main__":
    unittest.main()
