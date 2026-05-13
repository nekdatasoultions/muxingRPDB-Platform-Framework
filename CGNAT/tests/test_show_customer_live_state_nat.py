from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.customers.show_customer_live_state import (  # noqa: E402
    nat_translation_summary,
    print_human,
)


class ShowCustomerLiveStateNatTests(unittest.TestCase):
    def test_nat_translation_summary_reports_inside_and_outside_mappings(self) -> None:
        summary = nat_translation_summary(
            {
                "selectors": {
                    "remote_host_cidrs": ["10.60.20.11/32"],
                },
                "post_ipsec_nat": {
                    "enabled": True,
                    "mode": "netmap",
                    "mapping_strategy": "one_to_one",
                    "real_subnets": ["10.60.20.11/32"],
                    "translated_subnets": ["172.30.20.11/32"],
                    "core_subnets": ["23.20.31.151/32", "194.138.36.86/32"],
                },
                "outside_nat": {
                    "enabled": True,
                    "mode": "netmap",
                    "mapping_strategy": "one_to_one",
                    "real_subnets": ["194.138.36.86/32"],
                    "translated_subnets": ["10.60.50.11/32"],
                    "customer_sources": ["10.60.20.11/32"],
                    "route_via": "172.31.63.44",
                    "route_dev": "ens36",
                },
            }
        )

        self.assertEqual(
            summary["inside"]["translations"],
            [{"presented": "172.30.20.11", "real": "10.60.20.11", "kind": "host"}],
        )
        self.assertEqual(
            summary["outside"]["translations"],
            [{"presented": "10.60.50.11", "real": "194.138.36.86", "kind": "host"}],
        )
        self.assertEqual(summary["outside"]["customer_sources"], ["10.60.20.11/32"])

    def test_print_human_includes_demo_nat_translation_lines(self) -> None:
        result = {
            "customer_name": "demo-customer",
            "expected": "deployed",
            "overall": {"status": "ok", "errors": []},
            "backend": {"customer_present": True, "allocation_count": 7},
            "metadata": {"backend_cluster": "non-nat", "transport_mode": "cgnat"},
            "headend_family": "all",
            "nat_translations": {
                "inside": {
                    "mode": "netmap",
                    "mapping_strategy": "one_to_one",
                    "translations": [
                        {"presented": "172.30.20.11", "real": "10.60.20.11", "kind": "host"}
                    ],
                    "core_subnets": ["23.20.31.151/32", "194.138.36.86/32"],
                },
                "outside": {
                    "mode": "netmap",
                    "mapping_strategy": "one_to_one",
                    "translations": [
                        {"presented": "10.60.50.11", "real": "194.138.36.86", "kind": "host"}
                    ],
                    "customer_sources": ["10.60.20.11/32"],
                    "route_via": "172.31.63.44",
                    "route_dev": "ens36",
                },
            },
            "surfaces": [],
        }
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            print_human(result)

        rendered = output.getvalue()
        self.assertIn("nat translations:", rendered)
        self.assertIn("inside: mode=netmap mapping=one_to_one", rendered)
        self.assertIn("presented->real=[172.30.20.11->10.60.20.11]", rendered)
        self.assertIn("outside: mode=netmap mapping=one_to_one", rendered)
        self.assertIn("presented->real=[10.60.50.11->194.138.36.86]", rendered)


if __name__ == "__main__":
    unittest.main()
