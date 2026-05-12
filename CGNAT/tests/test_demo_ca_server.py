from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema


CGNAT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CGNAT_ROOT.parent
MUXER_ROOT = REPO_ROOT / "muxer"
MUXER_SRC = MUXER_ROOT / "src"
CERTIFICATE_SCRIPTS = REPO_ROOT / "scripts" / "certificates"
CGNAT_FRAMEWORK_SRC = CGNAT_ROOT / "framework" / "src"
sys.path.insert(0, str(MUXER_SRC))
sys.path.insert(0, str(CERTIFICATE_SCRIPTS))
sys.path.insert(0, str(CGNAT_FRAMEWORK_SRC))

from demo_ca_server import issue_cgnat_customer_bundle, issue_vpn_customer_bundle  # noqa: E402
from cgnat.pki_materializer import materialize_cgnat_pki  # noqa: E402
from muxerlib.allocation import (  # noqa: E402
    empty_allocation_inventory,
    load_allocation_pools,
    plan_customer_allocations,
    render_allocated_customer_source,
)
from muxerlib.customer_artifacts import build_customer_artifact_tree  # noqa: E402
from muxerlib.customer_merge import build_customer_item, build_customer_module, load_yaml_file  # noqa: E402


class DemoCaServerTests(unittest.TestCase):
    def setUp(self) -> None:
        build_root = CGNAT_ROOT / "build"
        build_root.mkdir(parents=True, exist_ok=True)
        self.test_root = Path(tempfile.mkdtemp(prefix="demo-ca-server-", dir=str(build_root)))
        self.schema = json.loads(
            (MUXER_ROOT / "config" / "schema" / "customer-request.schema.json").read_text(encoding="utf-8")
        )
        self.pools = load_allocation_pools(MUXER_ROOT / "config" / "allocation-pools" / "defaults.yaml")
        self.defaults = load_yaml_file(MUXER_ROOT / "config" / "customer-defaults" / "defaults.yaml")
        self.strict_non_nat_class = load_yaml_file(
            MUXER_ROOT / "config" / "customer-defaults" / "classes" / "strict-non-nat.yaml"
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.test_root, ignore_errors=True)

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
            source_ref="tests/demo-ca-customer.yaml",
        )
        customer_item = build_customer_item(
            source_doc,
            self.defaults,
            self.strict_non_nat_class,
            source_ref="tests/demo-ca-customer.yaml",
        )
        return customer_module, customer_item

    def test_demo_ca_issues_third_party_request_with_encrypted_headend_key(self) -> None:
        try:
            manifest = issue_vpn_customer_bundle(
                ca_root=self.test_root,
                customer_name="demo-ca-third-party-cert",
                profile="third_party_provided",
                encrypt_headend_key=True,
                headend_key_passphrase="test-headend-passphrase",
            )
        except FileNotFoundError as exc:
            self.skipTest(str(exc))

        request_doc = load_yaml_file(manifest["request_path"])
        jsonschema.validate(instance=request_doc, schema=self.schema)
        certificate = request_doc["customer"]["ipsec"]["auth"]["certificate"]

        self.assertEqual(certificate["profile"], "third_party_provided")
        self.assertIn("private_key_passphrase_secret_ref", certificate["headend"])
        self.assertTrue(Path(manifest["headend"]["certificate_path"]).exists())
        self.assertTrue(Path(manifest["headend"]["private_key_path"]).exists())
        self.assertTrue(Path(manifest["remote"]["certificate_path"]).exists())
        self.assertNotIn("psk_secret_ref", request_doc["customer"]["peer"])

        customer_module, customer_item = self._render_customer(request_doc)
        artifacts = build_customer_artifact_tree(customer_module, customer_item)
        headend_conf = artifacts["headend"]["ipsec/swanctl-connection.conf"]

        self.assertIn("auth = pubkey", headend_conf)
        self.assertIn("private-demo-ca-third-party-cert-headend-key", headend_conf)
        self.assertIn("secret = ${PRIVATE_KEY_PASSPHRASE}", headend_conf)
        self.assertIn("certificate-auth/certificate-handoff.json", artifacts["customer"])

    def test_demo_ca_customer_supplied_profile_omits_handoff_by_default(self) -> None:
        try:
            manifest = issue_vpn_customer_bundle(
                ca_root=self.test_root,
                customer_name="demo-ca-customer-supplied-cert",
                profile="customer_supplied",
            )
        except FileNotFoundError as exc:
            self.skipTest(str(exc))

        request_doc = load_yaml_file(manifest["request_path"])
        jsonschema.validate(instance=request_doc, schema=self.schema)
        certificate = request_doc["customer"]["ipsec"]["auth"]["certificate"]

        self.assertEqual(certificate["profile"], "customer_supplied")
        self.assertNotIn("customer_handoff", certificate)
        self.assertEqual(certificate["headend"]["id"], "rpdb-headend.demo-ca-customer-supplied-cert.example")
        self.assertEqual(certificate["remote"]["id"], "demo-ca-customer-supplied-cert.customer.example")

    def test_demo_ca_issues_cgnat_provided_pki_request_for_customer_router(self) -> None:
        try:
            manifest = issue_cgnat_customer_bundle(
                ca_root=self.test_root,
                customer_name="demo-ca-cgnat-customer-router",
                outer_topology="per_customer_outer",
            )
        except FileNotFoundError as exc:
            self.skipTest(str(exc))

        request_doc = load_yaml_file(manifest["request_path"])
        jsonschema.validate(instance=request_doc, schema=self.schema)

        pki = request_doc["customer"]["transport"]["cgnat"]["pki"]
        self.assertEqual(pki["mode"], "provided")
        self.assertEqual(pki["provider"], "rpdb-demo-ca-server")
        self.assertIn("cert_ref", pki["headend"])
        self.assertIn("private_key_secret_ref", pki["headend"])
        self.assertIn("cert_ref", pki["customer"])
        self.assertIn("private_key_secret_ref", pki["customer"])
        self.assertNotIn("outer_gateway_ref", request_doc["customer"]["transport"]["cgnat"])
        self.assertNotIn("gateway", pki)
        self.assertEqual(manifest["outer_gateway_ref"], "")

        pki_review = materialize_cgnat_pki(request_doc, self.test_root / "cgnat-provided-router")

        self.assertTrue(pki_review["ready_for_review"])
        self.assertEqual(pki_review["mode"], "provided")
        self.assertFalse(pki_review["generated_material"])
        self.assertTrue(pki_review["artifacts"]["provided_material"])
        self.assertEqual(pki_review["outer_handoff"]["recipient_type"], "customer_device")
        self.assertTrue(Path(pki_review["artifacts"]["headend_certificate_path"]).exists())
        self.assertTrue(Path(pki_review["artifacts"]["customer_certificate_path"]).exists())
        self.assertTrue(Path(pki_review["artifacts"]["ca_certificate_path"]).exists())

    def test_demo_ca_rejects_per_customer_outer_with_gateway_ref(self) -> None:
        with self.assertRaisesRegex(ValueError, "per_customer_outer must not set outer_gateway_ref"):
            issue_cgnat_customer_bundle(
                ca_root=self.test_root,
                customer_name="demo-ca-cgnat-bad-per-customer",
                outer_topology="per_customer_outer",
                outer_gateway_ref="isp-cgnat-router-2",
            )

    def test_demo_ca_rejects_shared_gateway_without_gateway_ref(self) -> None:
        with self.assertRaisesRegex(ValueError, "shared_isp_gateway requires outer_gateway_ref"):
            issue_cgnat_customer_bundle(
                ca_root=self.test_root,
                customer_name="demo-ca-cgnat-bad-shared",
                outer_topology="shared_isp_gateway",
            )

    def test_demo_ca_issues_cgnat_provided_pki_request_for_shared_gateway(self) -> None:
        try:
            manifest = issue_cgnat_customer_bundle(
                ca_root=self.test_root,
                customer_name="demo-ca-cgnat-shared-gateway",
                outer_topology="shared_isp_gateway",
                outer_gateway_ref="isp-cgnat-router-2",
            )
        except FileNotFoundError as exc:
            self.skipTest(str(exc))

        request_doc = load_yaml_file(manifest["request_path"])
        jsonschema.validate(instance=request_doc, schema=self.schema)

        cgnat = request_doc["customer"]["transport"]["cgnat"]
        pki = cgnat["pki"]
        self.assertEqual(cgnat["outer_topology"], "shared_isp_gateway")
        self.assertEqual(cgnat["outer_gateway_ref"], "isp-cgnat-router-2")
        self.assertEqual(pki["mode"], "provided")
        self.assertIn("gateway", pki)
        self.assertNotIn("customer", pki)

        pki_review = materialize_cgnat_pki(request_doc, self.test_root / "cgnat-provided-gateway")

        self.assertTrue(pki_review["ready_for_review"])
        self.assertEqual(pki_review["mode"], "provided")
        self.assertEqual(pki_review["outer_handoff"]["recipient_type"], "isp_gateway")
        self.assertFalse(pki_review["customer_handoff"]["outer_material_required"])
        self.assertTrue(pki_review["gateway_handoff"]["outer_material_required"])
        self.assertTrue(Path(pki_review["artifacts"]["headend_certificate_path"]).exists())
        self.assertTrue(Path(pki_review["artifacts"]["gateway_certificate_path"]).exists())

    def test_demo_ca_cgnat_nat_shapes_render_backend_headend_nat(self) -> None:
        def inside_nat(real_subnet: str, translated_subnet: str) -> dict:
            return {
                "enabled": True,
                "mode": "netmap",
                "mapping_strategy": "one_to_one",
                "real_subnets": [real_subnet],
                "translated_subnets": [translated_subnet],
                "core_subnets": ["23.20.31.151/32", "194.138.36.86/32"],
            }

        def outside_nat(translated_subnet: str, customer_source: str) -> dict:
            return {
                "enabled": True,
                "mode": "netmap",
                "mapping_strategy": "one_to_one",
                "real_subnets": ["194.138.36.86/32"],
                "translated_subnets": [translated_subnet],
                "customer_sources": [customer_source],
                "route_via": "172.31.63.44",
                "route_dev": "ens36",
            }

        specs = [
            {
                "customer_name": "demo-ca-cgnat-per-outer-inside-nat",
                "outer_topology": "per_customer_outer",
                "peer_public_ip": "203.0.113.201",
                "customer_loopback_ip": "10.250.10.10",
                "real_inside": "10.60.10.10/32",
                "inside_translated": "172.30.10.10/32",
                "outside_translated": "",
            },
            {
                "customer_name": "demo-ca-cgnat-per-outer-inside-outside-nat",
                "outer_topology": "per_customer_outer",
                "peer_public_ip": "203.0.113.202",
                "customer_loopback_ip": "10.250.10.11",
                "real_inside": "10.60.10.11/32",
                "inside_translated": "172.30.10.11/32",
                "outside_translated": "10.60.40.11/32",
            },
            {
                "customer_name": "demo-ca-cgnat-per-outer-outside-nat",
                "outer_topology": "per_customer_outer",
                "peer_public_ip": "203.0.113.203",
                "customer_loopback_ip": "10.250.10.12",
                "real_inside": "10.60.10.12/32",
                "inside_translated": "",
                "outside_translated": "10.60.40.12/32",
            },
            {
                "customer_name": "demo-ca-cgnat-shared-isp-inside-nat",
                "outer_topology": "shared_isp_gateway",
                "peer_public_ip": "203.0.113.211",
                "customer_loopback_ip": "10.250.20.10",
                "real_inside": "10.60.20.10/32",
                "inside_translated": "172.30.20.10/32",
                "outside_translated": "",
            },
            {
                "customer_name": "demo-ca-cgnat-shared-isp-inside-outside-nat",
                "outer_topology": "shared_isp_gateway",
                "peer_public_ip": "203.0.113.212",
                "customer_loopback_ip": "10.250.20.11",
                "real_inside": "10.60.20.11/32",
                "inside_translated": "172.30.20.11/32",
                "outside_translated": "10.60.50.11/32",
            },
            {
                "customer_name": "demo-ca-cgnat-shared-isp-outside-nat",
                "outer_topology": "shared_isp_gateway",
                "peer_public_ip": "203.0.113.213",
                "customer_loopback_ip": "10.250.20.12",
                "real_inside": "10.60.20.12/32",
                "inside_translated": "",
                "outside_translated": "10.60.50.12/32",
            },
        ]

        for spec in specs:
            with self.subTest(spec=spec["customer_name"]):
                local_subnets = (
                    ["23.20.31.151/32", spec["outside_translated"]]
                    if spec["outside_translated"]
                    else ["23.20.31.151/32", "194.138.36.86/32"]
                )
                try:
                    manifest = issue_cgnat_customer_bundle(
                        ca_root=self.test_root,
                        customer_name=spec["customer_name"],
                        peer_public_ip=spec["peer_public_ip"],
                        outer_topology=spec["outer_topology"],
                        outer_gateway_ref=(
                            "isp-cgnat-router-2"
                            if spec["outer_topology"] == "shared_isp_gateway"
                            else ""
                        ),
                        service_profile=(
                            "scenario2"
                            if spec["outer_topology"] == "shared_isp_gateway"
                            else "scenario1"
                        ),
                        customer_loopback_ip=spec["customer_loopback_ip"],
                        known_inside_identity=spec["real_inside"],
                        local_subnets=local_subnets,
                        remote_subnets=[spec["real_inside"]],
                        remote_host_cidrs=[spec["real_inside"]],
                        service_reachable_subnets=["23.20.31.151/32", "194.138.36.86/32"],
                        post_ipsec_nat=(
                            inside_nat(spec["real_inside"], spec["inside_translated"])
                            if spec["inside_translated"]
                            else None
                        ),
                        outside_nat=(
                            outside_nat(spec["outside_translated"], spec["real_inside"])
                            if spec["outside_translated"]
                            else None
                        ),
                    )
                except FileNotFoundError as exc:
                    self.skipTest(str(exc))

                request_doc = load_yaml_file(manifest["request_path"])
                jsonschema.validate(instance=request_doc, schema=self.schema)

                customer_module, customer_item = self._render_customer(request_doc)
                artifacts = build_customer_artifact_tree(customer_module, customer_item)
                post_ipsec_intent = artifacts["headend"]["post-ipsec-nat/post-ipsec-nat-intent.json"]
                outside_intent = artifacts["headend"]["outside-nat/outside-nat-intent.json"]
                ipsec_intent = artifacts["headend"]["ipsec/ipsec-intent.json"]

                self.assertEqual(
                    ipsec_intent["outer_topology"],
                    spec["outer_topology"],
                )
                if spec["outer_topology"] == "shared_isp_gateway":
                    self.assertEqual(ipsec_intent["outer_gateway_ref"], "isp-cgnat-router-2")

                self.assertEqual(post_ipsec_intent["enabled"], bool(spec["inside_translated"]))
                if spec["inside_translated"]:
                    self.assertEqual(post_ipsec_intent["real_subnets"], [spec["real_inside"]])
                    self.assertEqual(
                        post_ipsec_intent["translated_subnets"],
                        [spec["inside_translated"]],
                    )
                    self.assertIn(
                        "table ip rpdb_hn_",
                        artifacts["headend"]["post-ipsec-nat/nftables.apply.nft"],
                    )

                self.assertEqual(outside_intent["enabled"], bool(spec["outside_translated"]))
                if spec["outside_translated"]:
                    self.assertEqual(outside_intent["real_subnets"], ["194.138.36.86/32"])
                    self.assertEqual(
                        outside_intent["translated_subnets"],
                        [spec["outside_translated"]],
                    )
                    self.assertEqual(outside_intent["customer_sources"], [spec["real_inside"]])
                    self.assertEqual(outside_intent["route_via"], "172.31.63.44")
                    self.assertEqual(outside_intent["route_dev"], "ens36")
                    self.assertIn(
                        "table ip rpdb_on_",
                        artifacts["headend"]["outside-nat/nftables.apply.nft"],
                    )


if __name__ == "__main__":
    unittest.main()
