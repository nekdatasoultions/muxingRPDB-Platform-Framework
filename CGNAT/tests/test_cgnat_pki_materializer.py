from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path


CGNAT_ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK_SRC = CGNAT_ROOT / "framework" / "src"
MUXER_ROOT = CGNAT_ROOT.parent / "muxer"
sys.path.insert(0, str(FRAMEWORK_SRC))
sys.path.insert(0, str(MUXER_ROOT / "src"))

from cgnat.pki_materializer import materialize_cgnat_pki, resolve_cgnat_pki_spec  # noqa: E402
from muxerlib.customer_merge import load_yaml_file  # noqa: E402


class CgnatPkiMaterializerTests(unittest.TestCase):
    def test_reference_mode_resolves_distinct_headend_and_customer_refs(self) -> None:
        request_doc = load_yaml_file(
            MUXER_ROOT / "config" / "customer-requests" / "examples" / "example-minimal-cgnat.yaml"
        )
        spec = resolve_cgnat_pki_spec(request_doc)

        self.assertEqual(spec["mode"], "reference")
        self.assertEqual(spec["headend"]["identity_ref"], "cgnat-head-end/example-minimal-cgnat")
        self.assertEqual(spec["customer"]["identity_ref"], "customer-router-1/example-minimal-cgnat")
        self.assertEqual(spec["trust"]["ca_ref"], "pki/cgnat/ca/example-minimal-cgnat")

    def test_local_generate_writes_customer_handoff_bundle(self) -> None:
        request_doc = load_yaml_file(
            MUXER_ROOT / "config" / "customer-requests" / "examples" / "example-minimal-cgnat-local-pki.yaml"
        )
        build_root = CGNAT_ROOT / "build"
        build_root.mkdir(parents=True, exist_ok=True)
        output_dir = Path(tempfile.mkdtemp(prefix="pki-materializer-test-", dir=str(build_root)))

        try:
            review = materialize_cgnat_pki(request_doc, output_dir)
        except FileNotFoundError as exc:
            self.skipTest(str(exc))

        self.assertTrue(review["ready_for_review"])
        self.assertEqual(review["mode"], "local_generate")
        self.assertTrue(review["generated_material"])

        customer_manifest = Path(review["artifacts"]["customer_handoff_manifest"])
        customer_readme = Path(review["artifacts"]["customer_handoff_readme"])
        customer_cert = Path(review["artifacts"]["customer_certificate_path"])
        customer_key = Path(review["artifacts"]["customer_private_key_path"])
        ca_cert = Path(review["artifacts"]["ca_certificate_path"])
        headend_cert = Path(review["artifacts"]["headend_certificate_path"])

        self.assertTrue(customer_manifest.exists())
        self.assertTrue(customer_readme.exists())
        self.assertTrue(customer_cert.exists())
        self.assertTrue(customer_key.exists())
        self.assertTrue(ca_cert.exists())
        self.assertTrue(headend_cert.exists())
        shutil.rmtree(output_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
