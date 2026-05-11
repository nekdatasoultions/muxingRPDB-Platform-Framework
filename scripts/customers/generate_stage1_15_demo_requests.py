#!/usr/bin/env python3
"""Generate the stage1-15 demo customer request set.

This generator normalizes the 1-15 demo customers so they:

- keep dynamic NAT-T auto-promotion by omitting explicit class/backend pinning
- enable dynamic peer IP check-in for every customer router
- alternate inside NAT and outside NAT across the customer set
- use unique customer loopback /32s instead of the legacy shared 10.129.3.154/32
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
REQUESTS_DIR = REPO_ROOT / "muxer" / "config" / "customer-requests" / "migrated"

CORE_LOCAL_SUBNETS = [
    "172.31.54.39/32",
    "194.138.36.80/28",
]

LOOPBACKS: dict[int, str] = {
    1: "10.129.3.127/32",
    2: "10.129.3.128/32",
    3: "10.129.3.129/32",
    4: "10.129.3.130/32",
    5: "10.129.3.131/32",
    6: "10.129.3.132/32",
    7: "10.129.3.133/32",
    8: "10.129.3.134/32",
    9: "10.129.3.135/32",
    10: "10.129.3.136/32",
    11: "10.129.3.137/32",
    12: "10.129.3.138/32",
    13: "10.129.3.139/32",
    14: "10.129.3.140/32",
    15: "10.129.3.141/32",
}

PEER_IPS: dict[int, str] = {
    1: "34.201.23.168",
    2: "3.236.161.125",
    3: "3.215.115.178",
    4: "32.197.31.22",
    5: "35.169.124.144",
    6: "100.54.120.200",
    7: "35.171.133.225",
    8: "44.211.86.250",
    9: "98.91.185.196",
    10: "3.239.168.24",
    11: "3.235.101.38",
    12: "44.222.157.42",
    13: "44.223.83.35",
    14: "100.55.58.139",
    15: "3.236.195.175",
}

INSIDE_NAT_BLOCKS: dict[int, str] = {
    1: "172.30.0.0/27",
    3: "172.30.0.64/27",
    5: "172.30.0.128/27",
    7: "172.30.0.192/27",
    9: "172.30.1.0/27",
    11: "172.30.1.64/27",
    13: "172.30.1.128/27",
    15: "172.30.1.192/27",
}

OUTSIDE_NAT_ALIASES: dict[int, str] = {
    2: "10.128.4.2/32",
    4: "10.128.4.4/32",
    6: "10.128.4.6/32",
    8: "10.128.4.8/32",
    10: "10.128.4.10/32",
    12: "10.128.4.12/32",
    14: "10.128.4.14/32",
}


def customer_name(number: int) -> str:
    return f"vpn-customer-stage1-15-cust-{number:04d}"


def psk_secret_ref(number: int) -> str:
    return f"/muxingrpdb/dev/customers/{customer_name(number)}/psk"


def dynamic_peer_ip_secret_ref(number: int) -> str:
    return f"/muxingrpdb/dev/customers/{customer_name(number)}/dynamic-peer-ip-password"


def dynamic_peer_ip_doc(number: int) -> dict[str, Any]:
    name = customer_name(number)
    return {
        "enabled": True,
        "source": "device_registry_ddns",
        "device_registry": {
            "serial_number": name,
            "password_secret_ref": dynamic_peer_ip_secret_ref(number),
        },
        "reapply": {
            "mode": "remove_reapply",
            "update_remote_id_when_equal_to_peer_ip": False,
        },
    }


def ipsec_doc(number: int) -> dict[str, Any]:
    return {
        "auto": "start",
        "remote_id": PEER_IPS[number],
        "ike_version": "ikev2",
        "ike_policies": [
            "aes256-sha256-modp2048",
            "aes256-sha256-modp4096",
        ],
        "esp_policies": [
            "aes256-sha256-modp2048",
            "aes256-sha256-modp4096",
        ],
        "dpddelay": "10s",
        "dpdtimeout": "120s",
        "dpdaction": "restart",
        "replay_protection": True,
        "pfs_required": False,
        "pfs_groups": [
            "modp2048",
            "modp4096",
        ],
        "mobike": False,
        "fragmentation": True,
        "clear_df_bit": True,
        "path_mtu": 1400,
    }


def build_request(number: int) -> dict[str, Any]:
    name = customer_name(number)
    loopback = LOOPBACKS[number]
    customer_doc: dict[str, Any] = {
        "name": name,
        "peer": {
            "public_ip": PEER_IPS[number],
            "remote_id": PEER_IPS[number],
            "psk_secret_ref": psk_secret_ref(number),
        },
        "selectors": {
            "local_subnets": list(CORE_LOCAL_SUBNETS),
            "remote_subnets": [loopback],
            "remote_host_cidrs": [loopback],
        },
        "transport": {
            "tunnel_mtu": 1436,
        },
        "dynamic_peer_ip": dynamic_peer_ip_doc(number),
        "ipsec": ipsec_doc(number),
    }

    if number % 2 == 1:
        customer_doc["post_ipsec_nat"] = {
            "enabled": True,
            "mode": "netmap",
            "translated_subnets": [INSIDE_NAT_BLOCKS[number]],
            "real_subnets": [loopback],
            "core_subnets": list(CORE_LOCAL_SUBNETS),
            "tcp_mss_clamp": 1360,
        }
        customer_doc["outside_nat"] = {
            "enabled": False,
            "mode": "disabled",
        }
    else:
        alias = OUTSIDE_NAT_ALIASES[number]
        customer_doc["selectors"]["local_subnets"] = [*CORE_LOCAL_SUBNETS, alias]
        customer_doc["post_ipsec_nat"] = {
            "enabled": False,
            "mode": "disabled",
        }
        customer_doc["outside_nat"] = {
            "enabled": True,
            "mode": "netmap",
            "mapping_strategy": "one_to_one",
            "real_subnets": ["194.138.36.86/32"],
            "translated_subnets": [alias],
            "tcp_mss_clamp": 1360,
            "route_via": "172.31.63.44",
            "route_dev": "ens36",
        }

    return {
        "schema_version": 1,
        "customer": customer_doc,
    }


def write_request(number: int, out_dir: Path) -> Path:
    path = out_dir / f"{customer_name(number)}.yaml"
    document = build_request(number)
    rendered = yaml.safe_dump(document, sort_keys=False, default_flow_style=False)
    path.write_text(rendered, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate stage1-15 demo customer request files.")
    parser.add_argument(
        "--out-dir",
        default=str(REQUESTS_DIR),
        help="Output directory for generated customer request YAML files.",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    written = [write_request(number, out_dir) for number in range(1, 16)]
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
