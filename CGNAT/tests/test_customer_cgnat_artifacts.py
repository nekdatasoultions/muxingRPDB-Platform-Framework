from __future__ import annotations

import sys
import unittest
from copy import deepcopy
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
from muxerlib.customer_artifacts import build_customer_artifact_tree  # noqa: E402
from muxerlib.customer_merge import build_customer_item, build_customer_module, load_yaml_file  # noqa: E402


class CgnatCustomerArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pools = load_allocation_pools(MUXER_ROOT / "config" / "allocation-pools" / "defaults.yaml")
        self.defaults = load_yaml_file(MUXER_ROOT / "config" / "customer-defaults" / "defaults.yaml")
        self.strict_non_nat_class = load_yaml_file(
            MUXER_ROOT / "config" / "customer-defaults" / "classes" / "strict-non-nat.yaml"
        )

    def _load_request(self, name: str) -> dict:
        return load_yaml_file(MUXER_ROOT / "config" / "customer-requests" / "examples" / name)

    def _render_customer(self, request_doc: dict) -> tuple[dict, dict]:
        allocation_plan = plan_customer_allocations(
            request_doc,
            self.pools,
            inventory=empty_allocation_inventory(),
        )
        source_doc = render_allocated_customer_source(request_doc, allocation_plan)
        customer_module = build_customer_module(
            source_doc,
            self.defaults,
            self.strict_non_nat_class,
            source_ref="tests/cgnat-artifacts.yaml",
        )
        customer_item = build_customer_item(
            source_doc,
            self.defaults,
            self.strict_non_nat_class,
            source_ref="tests/cgnat-artifacts.yaml",
        )
        return customer_module, customer_item

    def test_cgnat_headend_artifacts_key_off_customer_loopback_when_outer_peer_is_shared(self) -> None:
        customer1_request = deepcopy(self._load_request("example-cgnat-customer-1-local-pki.yaml"))
        customer2_request = deepcopy(self._load_request("example-minimal-cgnat-local-pki.yaml"))
        shared_outer_peer = "203.0.113.61"
        customer1_request["customer"]["peer"]["public_ip"] = shared_outer_peer
        customer2_request["customer"]["peer"]["public_ip"] = shared_outer_peer

        customer1_module, customer1_item = self._render_customer(customer1_request)
        customer2_module, customer2_item = self._render_customer(customer2_request)

        customer1_artifacts = build_customer_artifact_tree(customer1_module, customer1_item)
        customer2_artifacts = build_customer_artifact_tree(customer2_module, customer2_item)

        customer1_headend_conf = customer1_artifacts["headend"]["ipsec/swanctl-connection.conf"]
        customer2_headend_conf = customer2_artifacts["headend"]["ipsec/swanctl-connection.conf"]
        customer1_routes = customer1_artifacts["headend"]["routing/ip-route.commands.txt"]
        customer2_routes = customer2_artifacts["headend"]["routing/ip-route.commands.txt"]
        customer1_ipsec_intent = customer1_artifacts["headend"]["ipsec/ipsec-intent.json"]
        customer2_ipsec_intent = customer2_artifacts["headend"]["ipsec/ipsec-intent.json"]
        customer1_overlay_host = str(customer1_module["transport"]["overlay"]["mux_ip"]).split("/")[0]
        customer2_overlay_host = str(customer2_module["transport"]["overlay"]["mux_ip"]).split("/")[0]
        customer1_transport_interface = str(customer1_module["transport"]["interface"])
        customer2_transport_interface = str(customer2_module["transport"]["interface"])

        self.assertIn("remote_addrs = 10.250.1.10", customer1_headend_conf)
        self.assertIn("remote_addrs = 10.250.1.11", customer2_headend_conf)
        self.assertNotIn(f"remote_addrs = {shared_outer_peer}", customer1_headend_conf)
        self.assertNotIn(f"remote_addrs = {shared_outer_peer}", customer2_headend_conf)

        self.assertIn(
            f"ip route replace 10.250.1.10/32 via {customer1_overlay_host} dev {customer1_transport_interface}",
            customer1_routes,
        )
        self.assertIn(
            f"ip route replace 10.250.1.11/32 via {customer2_overlay_host} dev {customer2_transport_interface}",
            customer2_routes,
        )
        self.assertNotIn(f"ip route replace {shared_outer_peer}/32", customer1_routes)
        self.assertNotIn(f"ip route replace {shared_outer_peer}/32", customer2_routes)

        self.assertEqual(customer1_ipsec_intent["peer_public_ip"], "10.250.1.10")
        self.assertEqual(customer2_ipsec_intent["peer_public_ip"], "10.250.1.11")
        self.assertEqual(customer1_ipsec_intent["outer_peer_public_ip"], shared_outer_peer)
        self.assertEqual(customer2_ipsec_intent["outer_peer_public_ip"], shared_outer_peer)
        self.assertEqual(customer1_ipsec_intent["remote_id"], "10.250.1.10")
        self.assertEqual(customer2_ipsec_intent["remote_id"], "10.250.1.11")

    def test_cgnat_muxer_artifacts_disable_direct_public_peer_snat_rules(self) -> None:
        request_doc = deepcopy(self._load_request("example-cgnat-customer-1-local-pki.yaml"))
        request_doc["customer"]["peer"]["public_ip"] = "203.0.113.61"

        customer_module, customer_item = self._render_customer(request_doc)
        artifacts = build_customer_artifact_tree(customer_module, customer_item)

        firewall_intent = artifacts["muxer"]["firewall/firewall-intent.json"]
        firewall_state = artifacts["muxer"]["firewall/nftables-state.json"]
        firewall_manifest = artifacts["muxer"]["firewall/activation-manifest.json"]
        firewall_apply = artifacts["muxer"]["firewall/nftables.apply.nft"]

        self.assertEqual(firewall_intent["transport_mode"], "cgnat")
        self.assertFalse(firewall_intent["snat_coverage"]["required"])
        self.assertEqual(
            firewall_intent["snat_coverage"]["disabled_reason"],
            "cgnat_shared_outer_peer_uses_customer_specific_headend_transport_path",
        )
        self.assertEqual(firewall_state["rule_count"], 0)
        self.assertEqual(firewall_manifest["apply_command_count"], 0)
        self.assertNotIn("203.0.113.61/32", firewall_apply)
        self.assertNotIn("snat to", firewall_apply.lower())


if __name__ == "__main__":
    unittest.main()
