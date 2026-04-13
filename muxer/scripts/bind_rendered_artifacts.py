#!/usr/bin/env python
"""Bind rendered artifacts or handoff exports to environment-specific values."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muxerlib.environment_binding import (
    build_binding_context,
    find_unresolved_placeholders,
    iter_text_files,
    load_environment_bindings,
    load_optional_customer_module,
    replace_placeholders,
)


def main() -> int:
    repo_muxer_dir = Path(__file__).resolve().parents[1]

    parser = argparse.ArgumentParser(description="Bind rendered artifacts to environment-specific values.")
    parser.add_argument("input_dir", help="Rendered artifact directory or handoff export directory")
    parser.add_argument(
        "--environment-file",
        default=str(repo_muxer_dir / "config" / "environment-defaults" / "example-environment.yaml"),
        help="Path to the environment bindings YAML file",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        help="Destination directory for the bound artifacts",
    )
    parser.add_argument(
        "--customer-module",
        help="Optional explicit path to customer-module.json for derived bindings",
    )
    parser.add_argument(
        "--allow-unresolved",
        action="store_true",
        help="Allow unresolved placeholders to remain in the output",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    environment_doc = load_environment_bindings(args.environment_file)
    schema_path = repo_muxer_dir / "config" / "schema" / "environment-bindings.schema.json"
    try:
        import jsonschema

        environment_schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(instance=environment_doc, schema=environment_schema)
    except ImportError:
        pass
    customer_module = load_optional_customer_module(input_dir, args.customer_module)
    bindings = build_binding_context(environment_doc, customer_module)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(input_dir, out_dir)

    report = {
        "input_dir": str(input_dir),
        "out_dir": str(out_dir),
        "environment_file": str(Path(args.environment_file).resolve()),
        "binding_keys": sorted(bindings.keys()),
        "files": {},
        "unresolved": {},
    }

    for path in iter_text_files(out_dir):
        original_text = path.read_text(encoding="utf-8")
        replaced_text, missing = replace_placeholders(original_text, bindings)
        path.write_text(replaced_text, encoding="utf-8")
        relative_name = str(path.relative_to(out_dir))
        report["files"][relative_name] = {
            "replaced": original_text != replaced_text,
            "unresolved_after_bind": find_unresolved_placeholders(replaced_text),
        }
        if missing:
            report["unresolved"][relative_name] = missing

    (out_dir / "binding-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if report["unresolved"] and not args.allow_unresolved:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1

    print(f"Bound artifacts written: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
