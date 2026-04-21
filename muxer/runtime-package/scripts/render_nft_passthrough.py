#!/usr/bin/env python3
"""Render the pass-through nftables classification model for review."""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = RUNTIME_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muxerlib.core import load_yaml
from muxerlib.nftables import build_passthrough_nft_model, render_passthrough_nft_script
from muxerlib.variables import load_modules


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a batched nftables preview for pass-through customers.")
    parser.add_argument(
        "--global-config",
        default=str(RUNTIME_ROOT / "config" / "muxer.yaml"),
        help="Path to the runtime muxer.yaml file",
    )
    parser.add_argument(
        "--customer-module-dir",
        default=str(RUNTIME_ROOT / "config" / "customer-modules"),
        help="Path to the customer module directory",
    )
    parser.add_argument(
        "--source-backend",
        default="customer_modules",
        help="Customer source backend passed to the runtime loader",
    )
    parser.add_argument("--json", action="store_true", help="Print the nft model as JSON instead of script text")
    parser.add_argument("--out", help="Optional output path")
    args = parser.parse_args()

    global_cfg = load_yaml(Path(args.global_config).resolve())
    overlay_pool = ipaddress.ip_network(str(global_cfg["overlay_pool"]), strict=False)
    modules = load_modules(
        overlay_pool,
        cfg_dir=RUNTIME_ROOT / "config" / "tunnels.d",
        customer_modules_dir=Path(args.customer_module_dir).resolve(),
        customers_vars_path=RUNTIME_ROOT / "config" / "customers.variables.yaml",
        global_cfg=global_cfg,
        source_backend=args.source_backend,
    )
    model = build_passthrough_nft_model(modules, global_cfg)

    if args.json:
        payload = json.dumps(model, indent=2, sort_keys=True) + "\n"
    else:
        payload = render_passthrough_nft_script(model)

    if args.out:
        with Path(args.out).resolve().open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
    else:
        print(payload, end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
