from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parent
    src_root = project_root / "src"
    sys.path.insert(0, str(src_root))

    from cgnat.bundle import load_bundle, dump_json
    from cgnat.validate import validate_bundle

    parser = argparse.ArgumentParser(description="Validate a CGNAT deployment bundle.")
    parser.add_argument("bundle", help="Path to the deployment bundle JSON file.")
    parser.add_argument(
        "--output",
        help="Optional path to write validation output JSON.",
    )
    args = parser.parse_args()

    result = validate_bundle(load_bundle(args.bundle))

    if args.output:
        dump_json(args.output, result)
    else:
        import json

        print(json.dumps(result, indent=2, sort_keys=True))

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
