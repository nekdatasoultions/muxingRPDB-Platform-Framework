from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parent
    src_root = project_root / "src"
    sys.path.insert(0, str(src_root))

    from cgnat.bundle import load_bundle, dump_json, dump_text
    from cgnat.render import (
        render_backend_contract,
        render_deployment_summary,
        render_field_categories,
        render_go_no_go_checklist,
        render_infra_deployables,
        render_server_side_shapes,
        render_sot_record_shape,
        render_topology_markdown,
    )
    from cgnat.validate import validate_bundle

    parser = argparse.ArgumentParser(description="Render deployable shapes from a CGNAT deployment bundle.")
    parser.add_argument("bundle", help="Path to the deployment bundle JSON file.")
    parser.add_argument("output_dir", help="Directory to write rendered artifacts.")
    args = parser.parse_args()

    bundle = load_bundle(args.bundle)
    validation = validate_bundle(bundle)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    framework_dir = output_dir / "framework"
    aws_dir = output_dir / "aws"
    server_dir = output_dir / "server"
    sot_dir = output_dir / "sot"

    dump_json(framework_dir / "validation-result.json", validation)
    dump_json(framework_dir / "deployment-summary.json", render_deployment_summary(bundle, validation))
    dump_json(framework_dir / "field-categories.json", render_field_categories(bundle))
    dump_json(framework_dir / "go-no-go-checklist.json", render_go_no_go_checklist(bundle, validation))
    dump_text(framework_dir / "topology-summary.md", render_topology_markdown(bundle, validation))
    dump_json(aws_dir / "infra-deployables.json", render_infra_deployables(bundle))
    dump_json(server_dir / "server-side-shapes.json", render_server_side_shapes(bundle))
    dump_json(server_dir / "backend-contract.json", render_backend_contract(bundle))
    dump_json(sot_dir / "sot-record-shape.json", render_sot_record_shape(bundle))

    return 0 if validation["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
