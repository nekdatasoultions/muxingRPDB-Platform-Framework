from __future__ import annotations

import sys
import unittest
from pathlib import Path


CGNAT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CGNAT_ROOT.parent
MUXER_SRC = REPO_ROOT / "muxer" / "src"
sys.path.insert(0, str(MUXER_SRC))

from muxerlib.customer_artifacts import (  # noqa: E402
    _render_post_ipsec_nat_nftables,
    build_smartconnect_artifacts,
)
from muxerlib.customer_route_scope import (  # noqa: E402
    customer_cleanup_route_cidrs,
    customer_route_cidrs,
)


def base_module() -> dict:
    return {
        "customer": {
            "name": "route-scope-customer",
        },
        "backend": {
            "cluster": "nat",
            "assignment": "nat-pool-01",
            "role": "nat-active",
        },
        "selectors": {
            "remote_subnets": ["10.129.3.0/24"],
            "remote_host_cidrs": ["10.129.3.131/32"],
        },
        "post_ipsec_nat": {
            "enabled": False,
            "mode": "disabled",
        },
    }


class CustomerRouteScopeTests(unittest.TestCase):
    def test_non_nat_routes_remote_host_cidrs_not_remote_subnets(self) -> None:
        module = base_module()

        route_cidrs, source = customer_route_cidrs(module)

        self.assertEqual(route_cidrs, ["10.129.3.131/32"])
        self.assertEqual(source, "remote_host_cidrs")

    def test_pool_dnat_routes_translated_pool(self) -> None:
        module = base_module()
        module["post_ipsec_nat"] = {
            "enabled": True,
            "mode": "netmap",
            "mapping_strategy": "one_to_one",
            "real_subnets": ["10.129.3.128/27"],
            "translated_subnets": ["172.30.0.128/27"],
        }

        route_cidrs, source = customer_route_cidrs(module)
        smartconnect = build_smartconnect_artifacts(module)
        route_intent = smartconnect["routing/route-intent.json"]

        self.assertEqual(route_cidrs, ["172.30.0.128/27"])
        self.assertEqual(source, "post_ipsec_nat.translated_subnets")
        self.assertEqual(route_intent["customer_route_cidrs"], ["172.30.0.128/27"])
        self.assertEqual(
            route_intent["customer_route_cidrs_source"],
            "post_ipsec_nat.translated_subnets",
        )
        self.assertIn(
            "ip route replace table ${SMARTCONNECT_ROUTE_TABLE} 172.30.0.128/27",
            smartconnect["routing/ip-route.commands.txt"],
        )

    def test_distinct_netmap_routes_generated_translated_hosts(self) -> None:
        module = base_module()
        module["post_ipsec_nat"] = {
            "enabled": True,
            "mode": "netmap",
            "mapping_strategy": "one_to_one",
            "real_subnets": ["10.129.3.131/32"],
            "translated_subnets": ["172.30.0.128/27"],
        }

        route_cidrs, source = customer_route_cidrs(module)
        smartconnect = build_smartconnect_artifacts(module)
        route_intent = smartconnect["routing/route-intent.json"]
        nftables = _render_post_ipsec_nat_nftables(
            "route-scope-customer",
            module["post_ipsec_nat"],
        )

        self.assertEqual(route_cidrs, ["172.30.0.128/32"])
        self.assertEqual(source, "post_ipsec_nat.netmap_translated_hosts")
        self.assertEqual(route_intent["customer_route_cidrs"], ["172.30.0.128/32"])
        self.assertEqual(
            route_intent["customer_route_cidrs_source"],
            "post_ipsec_nat.netmap_translated_hosts",
        )
        self.assertIn("172.30.0.128 : 10.129.3.131", nftables["apply"])
        self.assertIn(
            "ip route replace table ${SMARTCONNECT_ROUTE_TABLE} 172.30.0.128/32",
            smartconnect["routing/ip-route.commands.txt"],
        )
        self.assertNotIn(
            "ip route replace table ${SMARTCONNECT_ROUTE_TABLE} 172.30.0.128/27",
            smartconnect["routing/ip-route.commands.txt"],
        )

    def test_explicit_dnat_routes_translated_host_mappings(self) -> None:
        module = base_module()
        module["post_ipsec_nat"] = {
            "enabled": True,
            "mode": "explicit_map",
            "mapping_strategy": "explicit_host_map",
            "real_subnets": ["10.129.3.131/32", "10.129.3.132/32"],
            "translated_subnets": ["172.30.0.128/27"],
            "host_mappings": [
                {
                    "real_ip": "10.129.3.131/32",
                    "translated_ip": "172.30.0.133/32",
                },
                {
                    "real_ip": "10.129.3.132/32",
                    "translated_ip": "172.30.0.134/32",
                },
            ],
        }

        route_cidrs, source = customer_route_cidrs(module)
        smartconnect = build_smartconnect_artifacts(module)
        route_intent = smartconnect["routing/route-intent.json"]
        nftables = _render_post_ipsec_nat_nftables(
            "route-scope-customer",
            module["post_ipsec_nat"],
        )

        self.assertEqual(route_cidrs, ["172.30.0.133/32", "172.30.0.134/32"])
        self.assertEqual(source, "post_ipsec_nat.host_mappings.translated_ip")
        self.assertEqual(route_intent["customer_route_cidrs"], route_cidrs)
        self.assertEqual(
            route_intent["customer_route_cidrs_source"],
            "post_ipsec_nat.host_mappings.translated_ip",
        )
        self.assertIn(
            "ip route replace table ${SMARTCONNECT_ROUTE_TABLE} 172.30.0.133/32",
            smartconnect["routing/ip-route.commands.txt"],
        )
        self.assertNotIn(
            "ip route replace table ${SMARTCONNECT_ROUTE_TABLE} 172.30.0.128/27",
            smartconnect["routing/ip-route.commands.txt"],
        )
        self.assertIn("172.30.0.133 : 10.129.3.131", nftables["apply"])
        self.assertIn("172.30.0.134 : 10.129.3.132", nftables["apply"])
        self.assertNotIn("172.30.0.128 : 10.129.3.131", nftables["apply"])

    def test_cleanup_includes_pool_and_explicit_routes_for_mode_changes(self) -> None:
        module = base_module()
        module["post_ipsec_nat"] = {
            "enabled": True,
            "mode": "explicit_map",
            "mapping_strategy": "explicit_host_map",
            "real_subnets": ["10.129.3.131/32"],
            "translated_subnets": ["172.30.0.128/27"],
            "host_mappings": [
                {
                    "real_ip": "10.129.3.131/32",
                    "translated_ip": "172.30.0.133/32",
                }
            ],
        }

        self.assertEqual(
            customer_cleanup_route_cidrs(module),
            ["10.129.3.131/32", "172.30.0.128/27", "172.30.0.133/32"],
        )

    def test_cleanup_includes_distinct_netmap_route_for_mode_changes(self) -> None:
        module = base_module()
        module["post_ipsec_nat"] = {
            "enabled": True,
            "mode": "netmap",
            "mapping_strategy": "one_to_one",
            "real_subnets": ["10.129.3.131/32"],
            "translated_subnets": ["172.30.0.128/27"],
        }

        self.assertEqual(
            customer_cleanup_route_cidrs(module),
            ["10.129.3.131/32", "172.30.0.128/27", "172.30.0.128/32"],
        )


if __name__ == "__main__":
    unittest.main()
