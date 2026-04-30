from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _framework_src_root() -> Path:
    script_dir = Path(__file__).resolve().parent.parent / "src"
    return script_dir


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _render_markdown(review: dict[str, Any], prep_dir: Path, aws_apply_dir: Path) -> str:
    lines = [
        "# Scenario 1 Pre-Deploy Review",
        "",
        f"- Service ID: `{review['service_id']}`",
        f"- Environment: `{review['environment_name']}`",
        f"- Ready for hard review: `{review['ready_for_hard_review']}`",
        "",
        "## Status Summary",
        "",
    ]
    for key, value in review["status_summary"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(
        [
            "",
            "## Key Artifacts",
            "",
            f"- Prep directory: `{prep_dir}`",
            f"- AWS dry-run apply directory: `{aws_apply_dir}`",
            "",
            "## Open Items Before Host Apply",
            "",
        ]
    )
    for item in review["open_items_before_host_apply"]:
        lines.append(f"- `{item['code']}`: {item['message']}")
    lines.extend(
        [
            "",
            "## Next Commands After Approval",
            "",
        ]
    )
    for step in review["next_commands_after_approval"]:
        lines.append(f"- {step}")
    return "\n".join(lines) + "\n"


def main() -> int:
    sys.path.insert(0, str(_framework_src_root()))

    from cgnat.bundle import dump_json, dump_text, ensure_path_within_cgnat, load_bundle
    from cgnat.predeploy_review import build_predeploy_review

    parser = argparse.ArgumentParser(description="Assemble a Scenario 1 pre-deploy review package from generated artifacts.")
    parser.add_argument("bundle_json", help="Path to the deployment bundle JSON.")
    parser.add_argument("prep_dir", help="Path to the scenario1-prep directory.")
    parser.add_argument("aws_apply_dir", help="Path to the aws-apply-dryrun directory.")
    parser.add_argument("output_dir", help="Directory to write the pre-deploy review package.")
    parser.add_argument(
        "--host-access-strategy-json",
        help="Optional path to the host access strategy JSON that will be used after live create.",
    )
    parser.add_argument(
        "--materials-manifest-json",
        help="Optional path to the materialized Scenario 1 demo materials manifest.",
    )
    args = parser.parse_args()

    bundle = load_bundle(Path(args.bundle_json).resolve())
    prep_dir = Path(args.prep_dir).resolve()
    aws_apply_dir = Path(args.aws_apply_dir).resolve()
    output_dir = ensure_path_within_cgnat(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    prep_summary = _load_json(prep_dir / "scenario1-preparation-summary.json")
    preflight_result = _load_json(prep_dir / "aws-preflight" / "preflight-result.json")
    aws_apply_result = _load_json(aws_apply_dir / "apply-result.json")

    review = build_predeploy_review(
        bundle,
        prep_summary,
        preflight_result,
        aws_apply_result,
        host_access_strategy_path=str(Path(args.host_access_strategy_json).resolve())
        if args.host_access_strategy_json
        else None,
        materials_manifest_path=str(Path(args.materials_manifest_json).resolve())
        if args.materials_manifest_json
        else None,
    )

    dump_json(output_dir / "predeploy-review-summary.json", review)
    dump_text(output_dir / "PREDEPLOY_REVIEW.md", _render_markdown(review, prep_dir, aws_apply_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
