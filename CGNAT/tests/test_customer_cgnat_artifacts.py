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
        customer1_request["customer"]["transport"]["cgnat"]["outer_topology"] = "shared_isp_gateway"
        customer1_request["customer"]["transport"]["cgnat"]["outer_gateway_ref"] = "isp-cgnat-router-1"
        customer2_request["customer"]["transport"]["cgnat"]["outer_topology"] = "shared_isp_gateway"
        customer2_request["customer"]["transport"]["cgnat"]["outer_gateway_ref"] = "isp-cgnat-router-1"

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
        self.assertEqual(customer1_ipsec_intent["outer_topology"], "shared_isp_gateway")
        self.assertEqual(customer2_ipsec_intent["outer_topology"], "shared_isp_gateway")
        self.assertEqual(customer1_ipsec_intent["outer_gateway_ref"], "isp-cgnat-router-1")
        self.assertEqual(customer2_ipsec_intent["outer_gateway_ref"], "isp-cgnat-router-1")

    def test_cgnat_muxer_artifacts_disable_direct_public_peer_snat_rules(self) -> None:
        request_doc = deepcopy(self._load_request("example-cgnat-customer-1-local-pki.yaml"))
        request_doc["customer"]["peer"]["public_ip"] = "203.0.113.61"
        request_doc["customer"]["transport"]["cgnat"]["outer_topology"] = "shared_isp_gateway"
        request_doc["customer"]["transport"]["cgnat"]["outer_gateway_ref"] = "isp-cgnat-router-1"

        customer_module, customer_item = self._render_customer(request_doc)
        artifacts = build_customer_artifact_tree(customer_module, customer_item)

        firewall_intent = artifacts["muxer"]["firewall/firewall-intent.json"]
        firewall_state = artifacts["muxer"]["firewall/nftables-state.json"]
        firewall_manifest = artifacts["muxer"]["firewall/activation-manifest.json"]
        firewall_apply = artifacts["muxer"]["firewall/nftables.apply.nft"]

        self.assertEqual(firewall_intent["transport_mode"], "cgnat")
        self.assertEqual(firewall_intent["outer_topology"], "shared_isp_gateway")
        self.assertEqual(firewall_intent["outer_gateway_ref"], "isp-cgnat-router-1")
        self.assertFalse(firewall_intent["snat_coverage"]["required"])
        self.assertEqual(
            firewall_intent["snat_coverage"]["disabled_reason"],
            "cgnat_shared_outer_peer_uses_customer_specific_headend_transport_path",
        )
        self.assertEqual(firewall_state["rule_count"], 0)
        self.assertEqual(firewall_manifest["apply_command_count"], 0)
        self.assertNotIn("203.0.113.61/32", firewall_apply)
        self.assertNotIn("snat to", firewall_apply.lower())

    def test_certificate_auth_headend_artifacts_render_pubkey_without_psk_secret(self) -> None:
        request_doc = deepcopy(self._load_request("example-certificate-auth-nonnat.yaml"))

        customer_module, customer_item = self._render_customer(request_doc)
        artifacts = build_customer_artifact_tree(customer_module, customer_item)

        headend_conf = artifacts["headend"]["ipsec/swanctl-connection.conf"]
        ipsec_intent = artifacts["headend"]["ipsec/ipsec-intent.json"]
        cert_handoff = artifacts["customer"]["certificate-auth/certificate-handoff.json"]

        self.assertIn("auth = pubkey", headend_conf)
        self.assertIn("certs = rpdb-customers/example-certificate-auth-nonnat-headend-cert.pem", headend_conf)
        self.assertIn("cacerts = rpdb-customers/example-certificate-auth-nonnat-remote-trust.pem", headend_conf)
        self.assertNotIn("auth = psk", headend_conf)
        self.assertNotIn("secrets {", headend_conf)
        self.assertIn("headend-key.pem", ipsec_intent["auth"]["certificate_material_paths"]["headend_private_key"])
        self.assertNotIn(
            "rpdb-customers/",
            ipsec_intent["auth"]["certificate_material_paths"]["headend_private_key"],
        )
        self.assertEqual(ipsec_intent["auth"]["method"], "certificate")
        self.assertEqual(ipsec_intent["local_id"], "rpdb-headend.example")
        self.assertEqual(ipsec_intent["remote_id"], "customer-cert-70.example")
        self.assertEqual(
            ipsec_intent["auth"]["certificate_material_paths"]["headend_cert"],
            "rpdb-customers/example-certificate-auth-nonnat-headend-cert.pem",
        )
        self.assertEqual(cert_handoff["auth_method"], "certificate")
        self.assertEqual(cert_handoff["customer_identity"], "customer-cert-70.example")

    def test_certificate_auth_passphrase_renders_private_key_secret_block(self) -> None:
        request_doc = deepcopy(self._load_request("example-certificate-auth-nonnat.yaml"))
        request_doc["customer"]["ipsec"]["auth"]["certificate"]["headend"][
            "private_key_passphrase_secret_ref"
        ] = "/muxingrpdb/demo/certs/example-certificate-auth-nonnat/headend-key-passphrase"

        customer_module, customer_item = self._render_customer(request_doc)
        artifacts = build_customer_artifact_tree(customer_module, customer_item)

        headend_conf = artifacts["headend"]["ipsec/swanctl-connection.conf"]

        self.assertIn("auth = pubkey", headend_conf)
        self.assertIn("private-example-certificate-auth-nonnat-headend-key", headend_conf)
        self.assertIn("file = example-certificate-auth-nonnat-headend-key.pem", headend_conf)
        self.assertIn("secret = ${PRIVATE_KEY_PASSPHRASE}", headend_conf)
        self.assertNotIn("auth = psk", headend_conf)

    def test_customer1_dual_nat_artifacts_render_expected_inside_and_outside_nat(self) -> None:
        request_doc = deepcopy(self._load_request("example-cgnat-customer-1-local-pki.yaml"))

        customer_module, customer_item = self._render_customer(request_doc)
        artifacts = build_customer_artifact_tree(customer_module, customer_item)

        headend_conf = artifacts["headend"]["ipsec/swanctl-connection.conf"]
        post_ipsec_nat_intent = artifacts["headend"]["post-ipsec-nat/post-ipsec-nat-intent.json"]
        outside_nat_intent = artifacts["headend"]["outside-nat/outside-nat-intent.json"]
        routing_intent = artifacts["headend"]["routing/routing-intent.json"]
        route_commands = artifacts["headend"]["routing/ip-route.commands.txt"]

        self.assertIn("local_ts = 23.20.31.151/32,10.20.40.10/32", headend_conf)

        self.assertTrue(post_ipsec_nat_intent["enabled"])
        self.assertEqual(post_ipsec_nat_intent["mode"], "netmap")
        self.assertEqual(post_ipsec_nat_intent["mapping_strategy"], "one_to_one")
        self.assertEqual(post_ipsec_nat_intent["real_subnets"], ["10.20.30.10/32"])
        self.assertEqual(post_ipsec_nat_intent["translated_subnets"], ["10.20.20.10/32"])
        self.assertEqual(
            post_ipsec_nat_intent["core_subnets"],
            ["23.20.31.151/32", "194.138.36.86/32"],
        )

        self.assertTrue(outside_nat_intent["enabled"])
        self.assertEqual(outside_nat_intent["mode"], "netmap")
        self.assertEqual(outside_nat_intent["mapping_strategy"], "one_to_one")
        self.assertEqual(outside_nat_intent["real_subnets"], ["194.138.36.86/32"])
        self.assertEqual(outside_nat_intent["translated_subnets"], ["10.20.40.10/32"])
        self.assertEqual(outside_nat_intent["route_via"], "172.31.63.44")
        self.assertEqual(outside_nat_intent["route_dev"], "ens36")
        self.assertEqual(outside_nat_intent["customer_sources"], ["10.20.30.10/32"])

        self.assertEqual(
            routing_intent["outside_nat"]["presented_local_subnets"],
            ["10.20.40.10/32"],
        )
        self.assertEqual(
            routing_intent["outside_nat"]["real_local_subnets"],
            ["194.138.36.86/32"],
        )
        self.assertIn("ip route replace 194.138.36.86/32 via 172.31.63.44 dev ens36", route_commands)


if __name__ == "__main__":
    unittest.main()
