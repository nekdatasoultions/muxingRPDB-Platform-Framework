from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parent
    src_root = project_root / "src"
    sys.path.insert(0, str(src_root))

    from cgnat.bundle import dump_json, load_bundle

    parser = argparse.ArgumentParser(description="Assemble a CGNAT deployment bundle from framework, operations, and SoT files.")
    parser.add_argument("framework", help="Path to framework JSON.")
    parser.add_argument("operations", help="Path to operations JSON.")
    parser.add_argument("sot", help="Path to SoT JSON.")
    parser.add_argument("output", help="Path to write the combined deployment bundle JSON.")
    args = parser.parse_args()

    payload = {
        "framework": load_bundle(args.framework),
        "operations": load_bundle(args.operations),
        "sot": load_bundle(args.sot),
    }
    dump_json(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
