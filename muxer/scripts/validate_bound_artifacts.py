#!/usr/bin/env python
"""Validate that a bound artifact tree has no unresolved placeholders."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muxerlib.environment_binding import find_unresolved_placeholders, iter_text_files


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a bound artifact tree.")
    parser.add_argument("bound_dir", help="Path to the bound artifact directory")
    parser.add_argument("--json", action="store_true", help="Print the validation report as JSON")
    args = parser.parse_args()

    bound_dir = Path(args.bound_dir).resolve()
    report = {
        "bound_dir": str(bound_dir),
        "errors": [],
    }

    if not bound_dir.exists():
        report["errors"].append(f"bound directory not found: {bound_dir}")
    else:
        report_path = bound_dir / "binding-report.json"
        if not report_path.exists():
            report["errors"].append("missing required file: binding-report.json")
        for path in iter_text_files(bound_dir):
            unresolved = find_unresolved_placeholders(path.read_text(encoding="utf-8"))
            if unresolved:
                report["errors"].append(
                    f"{path.relative_to(bound_dir)} still has unresolved placeholders: {', '.join(unresolved)}"
                )

    report["valid"] = not report["errors"]

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Bound artifact tree: {'VALID' if report['valid'] else 'INVALID'}")
        print(f"- bound dir: {bound_dir}")
        for error in report["errors"]:
            print(f"  error: {error}")

    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
