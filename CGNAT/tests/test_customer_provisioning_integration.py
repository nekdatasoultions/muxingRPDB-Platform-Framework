from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

import jsonschema


CGNAT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CGNAT_ROOT.parent
MUXER_ROOT = REPO_ROOT / "muxer"
MUXER_SRC = MUXER_ROOT / "src"
CUSTOMER_SCRIPTS = REPO_ROOT / "scripts" / "customers"
sys.path.insert(0, str(MUXER_SRC))
sys.path.insert(0, str(CUSTOMER_SCRIPTS))

from deploy_customer import _target_selection  # noqa: E402
from muxerlib.allocation import (  # noqa: E402
    empty_allocation_inventory,
    load_allocation_pools,
    plan_customer_allocations,
    render_allocated_customer_source,
)
from muxerlib.customer_merge import build_customer_module, load_yaml_file  # noqa: E402


class CustomerProvisioningIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(
            (MUXER_ROOT / "config" / "schema" / "customer-request.schema.json").read_text(encoding="utf-8")
        )
        self.pools = load_allocation_pools(MUXER_ROOT / "config" / "allocation-pools" / "defaults.yaml")
        self.defaults = load_yaml_file(MUXER_ROOT / "config" / "customer-defaults" / "defaults.yaml")
        self.strict_non_nat_class = load_yaml_file(
            MUXER_ROOT / "config" / "customer-defaults" / "classes" / "strict-non-nat.yaml"
        )
        self.environment_doc = load_yaml_file(
            MUXER_ROOT / "config" / "deployment-environments" / "rpdb-empty-live.yaml"
        )

    def _load_request(self, name: str) -> dict:
        return load_yaml_file(MUXER_ROOT / "config" / "customer-requests" / "examples" / name)

    def _render_source(self, request_doc: dict) -> dict:
        allocation_plan = plan_customer_allocations(
            request_doc,
            self.pools,
            inventory=empty_allocation_inventory(),
        )
        return render_allocated_customer_source(request_doc, allocation_plan)

    def test_legacy_request_preserves_existing_transport_shape(self) -> None:
        request_doc = self._load_request("example-minimal-nonnat.yaml")
        jsonschema.validate(instance=request_doc, schema=self.schema)

        customer_source = self._render_source(request_doc)
        customer_module = build_customer_module(
            customer_source,
            self.defaults,
            self.strict_non_nat_class,
            source_ref="tests/example-minimal-nonnat.yaml",
        )

        transport = customer_source["customer"]["transport"]
        self.assertNotIn("mode", transport)
        self.assertNotIn("cgnat", transport)
        self.assertNotIn("mode", customer_module["transport"])
        self.assertNotIn("cgnat", customer_module["transport"])

    def test_cgnat_request_survives_request_source_and_module_layers(self) -> None:
        request_doc = self._load_request("example-minimal-cgnat.yaml")
        jsonschema.validate(instance=request_doc, schema=self.schema)

        customer_source = self._render_source(request_doc)
        customer_module = build_customer_module(
            customer_source,
            self.defaults,
            self.strict_non_nat_class,
            source_ref="tests/example-minimal-cgnat.yaml",
        )

        source_transport = customer_source["customer"]["transport"]
        module_transport = customer_module["transport"]

        self.assertEqual(source_transport["mode"], "cgnat")
        self.assertEqual(source_transport["tunnel_mtu"], 1436)
        self.assertEqual(source_transport["cgnat"]["service_profile"], "scenario1")
        self.assertEqual(source_transport["cgnat"]["outer_identity_ref"], "customer-router-1/example-minimal-cgnat")
        self.assertEqual(source_transport["cgnat"]["outer_auth_ref"], "pki/cgnat/customer-router-1")
        self.assertEqual(source_transport["cgnat"]["customer_loopback_ip"], "10.250.1.10")
        self.assertEqual(source_transport["cgnat"]["known_inside_identity"], "10.20.30.10/32")
        self.assertEqual(
            source_transport["cgnat"]["service_reachable_subnets"],
            ["23.20.31.151/32", "194.138.36.86/32"],
        )

        self.assertEqual(module_transport["mode"], "cgnat")
        self.assertEqual(module_transport["cgnat"]["customer_loopback_ip"], "10.250.1.10")
        self.assertEqual(module_transport["cgnat"]["known_inside_identity"], "10.20.30.10/32")
        self.assertEqual(
            module_transport["cgnat"]["service_reachable_subnets"],
            ["23.20.31.151/32", "194.138.36.86/32"],
        )

    def test_target_selection_adds_cgnat_headend_only_for_cgnat_transport(self) -> None:
        direct_targets = _target_selection(
            environment_doc=self.environment_doc,
            readiness={
                "customer": {
                    "customer_class": "strict-non-nat",
                    "backend_cluster": "non-nat",
                    "transport_mode": "",
                },
                "dynamic_nat_t": {"used": False},
            },
        )
        cgnat_targets = _target_selection(
            environment_doc=self.environment_doc,
            readiness={
                "customer": {
                    "customer_class": "strict-non-nat",
                    "backend_cluster": "non-nat",
                    "transport_mode": "cgnat",
                },
                "dynamic_nat_t": {"used": False},
            },
        )

        self.assertEqual(direct_targets["headend_family"], "non_nat")
        self.assertFalse(direct_targets["cgnat_required"])
        self.assertIsNone(direct_targets["cgnat_headend_active"])

        self.assertEqual(cgnat_targets["headend_family"], "non_nat")
        self.assertTrue(cgnat_targets["cgnat_required"])
        self.assertEqual(
            (cgnat_targets["cgnat_headend_active"] or {}).get("name"),
            "cgnat-head-end-rpdb-empty-a",
        )

    def test_deployment_environment_validator_accepts_cgnat_target_extension(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "customers" / "validate_deployment_environment.py"),
                "rpdb-empty-live",
                "--allow-live-apply",
                "--json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, msg=completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertTrue(report["valid"])
        self.assertEqual(report["targets"]["cgnat_headend_active"], "cgnat-head-end-rpdb-empty-a")


if __name__ == "__main__":
    unittest.main()
