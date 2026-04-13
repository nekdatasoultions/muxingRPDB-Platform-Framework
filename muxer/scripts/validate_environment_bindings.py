#!/usr/bin/env python
"""Validate an environment bindings file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muxerlib.environment_binding import load_environment_bindings


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    repo_muxer_dir = Path(__file__).resolve().parents[1]

    parser = argparse.ArgumentParser(description="Validate an environment bindings file.")
    parser.add_argument(
        "environment_file",
        help="Path to the environment bindings YAML file",
    )
    parser.add_argument("--json", action="store_true", help="Print the validation report as JSON")
    args = parser.parse_args()

    environment_path = Path(args.environment_file).resolve()
    report = {
        "environment_file": str(environment_path),
        "errors": [],
        "warnings": [],
    }

    if not environment_path.exists():
        report["errors"].append(f"environment file not found: {environment_path}")
    else:
        document = load_environment_bindings(environment_path)
        schema_path = repo_muxer_dir / "config" / "schema" / "environment-bindings.schema.json"
        schema = _load_json(schema_path)
        try:
            import jsonschema

            jsonschema.validate(instance=document, schema=schema)
            report["validator"] = "jsonschema"
        except ImportError:
            report["warnings"].append("jsonschema not installed; schema validation skipped")
        except Exception as exc:
            report["errors"].append(str(exc))

    report["valid"] = not report["errors"]

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Environment bindings: {'VALID' if report['valid'] else 'INVALID'}")
        print(f"- file: {environment_path}")
        if report.get("validator"):
            print(f"- validator: {report['validator']}")
        for error in report["errors"]:
            print(f"  error: {error}")
        for warning in report["warnings"]:
            print(f"  warning: {warning}")

    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
