from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


CGNAT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CGNAT_ROOT.parent
RUNTIME_MUXERLIB = REPO_ROOT / "muxer" / "runtime-package" / "src" / "muxerlib"
RUNTIME_PACKAGE = "_rpdb_runtime_muxerlib"


def _runtime_module(name: str):
    if RUNTIME_PACKAGE not in sys.modules:
        package = types.ModuleType(RUNTIME_PACKAGE)
        package.__path__ = [str(RUNTIME_MUXERLIB)]
        sys.modules[RUNTIME_PACKAGE] = package

    module_name = f"{RUNTIME_PACKAGE}.{name}"
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, RUNTIME_MUXERLIB / f"{name}.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load runtime muxerlib module: {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _cgnat_module() -> dict:
    return {
        "schema_version": 1,
        "customer": {
            "id": 2008,
            "name": "demo-ca-cgnat-per-outer-inside-nat",
            "customer_class": "strict-non-nat",
        },
        "peer": {
            "public_ip": "203.0.113.201",
            "remote_id": "203.0.113.201",
        },
        "backend": {
            "role": "nonnat-active",
            "underlay_ip": "172.31.40.223",
        },
        "protocols": {
            "udp500": True,
            "udp4500": False,
            "esp50": True,
        },
        "selectors": {
            "local_subnets": ["23.20.31.151/32", "194.138.36.86/32"],
            "remote_subnets": ["10.60.10.10/32"],
            "remote_host_cidrs": ["10.60.10.10/32"],
        },
        "transport": {
            "mode": "cgnat",
            "interface": "gre-cust-2008",
            "tunnel_type": "gre",
            "tunnel_key": 2008,
            "table": 2008,
            "mark": "0x2008",
            "rpdb_priority": 1008,
            "overlay": {
                "mux_ip": "169.254.0.33/30",
                "router_ip": "169.254.0.34/30",
            },
            "cgnat": {
                "outer_topology": "per_customer_outer",
                "customer_loopback_ip": "10.250.10.10",
                "outer_transport": {
                    "customer_router_private_ip": "172.31.48.30",
                    "muxer_ingress_interface": "cgs1mi0",
                },
            },
        },
    }


class CgnatRuntimeMuxerPathTests(unittest.TestCase):
    def test_cgnat_runtime_peer_uses_inner_loopback_not_outer_placeholder(self) -> None:
        dynamodb_sot = _runtime_module("dynamodb_sot")

        compat = dynamodb_sot.normalize_customer_module(_cgnat_module())

        self.assertEqual(compat["peer_ip"], "10.250.10.10/32")
        self.assertEqual(compat["_rpdb_original"]["peer"]["public_ip"], "203.0.113.201")

    def test_cgnat_runtime_installs_muxer_ingress_routes(self) -> None:
        dynamodb_sot = _runtime_module("dynamodb_sot")
        modes = _runtime_module("modes")

        compat = dynamodb_sot.normalize_customer_module(_cgnat_module())
        interface, routes = modes._cgnat_ingress_routes(compat)

        self.assertEqual(interface, "cgs1mi0")
        self.assertEqual(routes, ["10.250.10.10", "172.31.48.30"])

    def test_cgnat_runtime_nft_hooks_include_muxer_ingress_interface(self) -> None:
        dynamodb_sot = _runtime_module("dynamodb_sot")
        nftables = _runtime_module("nftables")

        compat = dynamodb_sot.normalize_customer_module(_cgnat_module())
        model = nftables.build_passthrough_nft_model(
            [compat],
            {
                "public_ip": "23.20.31.151",
                "backend_underlay_ip": "172.31.40.223",
                "interfaces": {
                    "public_if": "ens34",
                    "public_private_ip": "172.31.33.150",
                },
                "firewall_policy": {
                    "default_drop_ipsec_to_public_ip": True,
                    "use_nat_rewrite": True,
                },
                "nftables": {
                    "pass_through": {
                        "classification_backend": "nftables",
                        "translation_backend": "nftables",
                        "bridge_backend": "nftables",
                    },
                },
            },
            render_mode="nftables-live-pass-through",
        )
        script = nftables.render_passthrough_nft_script(model)

        self.assertEqual(model["interfaces"]["traffic_ifs"], ["cgs1mi0", "ens34"])
        self.assertIn("10.250.10.10", model["sets"]["udp4500_accept_peers"])
        self.assertEqual(
            model["translation"]["maps"]["udp4500_dnat"]["10.250.10.10"],
            "dnat to 172.31.40.223",
        )
        self.assertIn('iifname { "cgs1mi0", "ens34" } ip daddr @public_destinations udp dport 500', script)
        self.assertIn('iifname { "cgs1mi0", "ens34" } ip daddr @public_destinations udp dport 4500', script)
        self.assertIn('oifname { "cgs1mi0", "ens34" } udp sport 500', script)
        self.assertIn('oifname { "cgs1mi0", "ens34" } udp sport 4500', script)
        self.assertIn("10.250.10.10 : 172.31.40.223", script)


if __name__ == "__main__":
    unittest.main()
