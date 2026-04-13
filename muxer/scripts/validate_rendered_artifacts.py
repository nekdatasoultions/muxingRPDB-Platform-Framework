#!/usr/bin/env python
"""Validate a rendered customer artifact tree."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED_ROOTS = ["muxer", "headend"]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a rendered customer artifact tree.")
    parser.add_argument("render_dir", help="Path to the rendered customer artifact directory")
    parser.add_argument("--json", action="store_true", help="Print the validation report as JSON")
    args = parser.parse_args()

    render_dir = Path(args.render_dir).resolve()
    report = {
        "render_dir": str(render_dir),
        "errors": [],
        "warnings": [],
    }

    if not render_dir.exists():
        report["errors"].append(f"render directory not found: {render_dir}")
    else:
        manifest_path = render_dir / "render-manifest.json"
        if not manifest_path.exists():
            report["errors"].append("missing required file: render-manifest.json")
        else:
            manifest = _load_json(manifest_path)
            roots = manifest.get("roots") or {}
            for root_name in REQUIRED_ROOTS:
                root_dir = render_dir / root_name
                if not root_dir.is_dir():
                    report["errors"].append(f"missing required directory: {root_name}/")
                    continue

                expected_files = roots.get(root_name)
                if not expected_files:
                    report["errors"].append(f"render-manifest.json missing root listing for {root_name}")
                    continue

                for relative_name in expected_files:
                    if not (root_dir / relative_name).exists():
                        report["errors"].append(
                            f"missing rendered file: {root_name}/{relative_name}"
                        )

            customer_name = manifest.get("customer_name")
            customer_class = manifest.get("customer_class")
            if not customer_name:
                report["warnings"].append("render-manifest.json missing customer_name")
            if not customer_class:
                report["warnings"].append("render-manifest.json missing customer_class")

        file_count = sum(1 for path in render_dir.rglob("*") if path.is_file())
        if file_count == 0:
            report["errors"].append("render directory contains no files")

    report["valid"] = not report["errors"]

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Rendered artifact tree: {'VALID' if report['valid'] else 'INVALID'}")
        print(f"- render dir: {render_dir}")
        for error in report["errors"]:
            print(f"  error: {error}")
        for warning in report["warnings"]:
            print(f"  warning: {warning}")

    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
