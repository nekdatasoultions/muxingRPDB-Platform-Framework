from __future__ import annotations

import sys
import unittest
from pathlib import Path


CGNAT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CGNAT_ROOT.parent
MUXER_ROOT = REPO_ROOT / "muxer"
MUXER_SRC = MUXER_ROOT / "src"
sys.path.insert(0, str(MUXER_SRC))

from muxerlib.allocation import (  # noqa: E402
    empty_allocation_inventory,
    load_allocation_pools,
    plan_customer_allocations,
    render_allocated_customer_source,
)
from muxerlib.cgnat_profile_overrides import apply_cgnat_service_profile_overrides  # noqa: E402
from muxerlib.customer_merge import load_yaml_file  # noqa: E402


class CgnatProfileOverridesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pools = load_allocation_pools(MUXER_ROOT / "config" / "allocation-pools" / "defaults.yaml")
        self.environment_doc = load_yaml_file(
            MUXER_ROOT / "config" / "deployment-environments" / "rpdb-empty-live.yaml"
        )

    def test_scenario1_override_applies_route_via_only_to_routed_service_subnets(self) -> None:
        request_doc = load_yaml_file(
            MUXER_ROOT / "config" / "customer-requests" / "examples" / "example-minimal-cgnat.yaml"
        )
        allocation_plan = plan_customer_allocations(
            request_doc,
            self.pools,
            inventory=empty_allocation_inventory(),
        )
        customer_source = render_allocated_customer_source(request_doc, allocation_plan)

        updated_source, report = apply_cgnat_service_profile_overrides(
            customer_source,
            deployment_environment="rpdb-empty-live",
            environment_doc=self.environment_doc,
        )

        outside_nat = dict((updated_source.get("customer") or {}).get("outside_nat") or {})
        self.assertTrue(report["applied"])
        self.assertEqual(report["reason"], "scenario_profile_route_via_applied")
        self.assertEqual(outside_nat["route_via"], "172.31.63.44")
        self.assertEqual(outside_nat["route_dev"], "ens36")
        self.assertEqual(outside_nat["real_subnets"], ["194.138.36.86/32"])
        self.assertEqual(outside_nat["translated_subnets"], ["194.138.36.86/32"])
        self.assertEqual(report["excluded_real_subnets"], ["23.20.31.151/32"])


if __name__ == "__main__":
    unittest.main()
