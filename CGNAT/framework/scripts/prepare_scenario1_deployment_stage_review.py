from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    import json

    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _render_markdown(review: dict[str, Any]) -> str:
    lines = [
        "# Scenario 1 Deployment Stage Review",
        "",
        f"- Service ID: `{review['service_id']}`",
        f"- Environment: `{review['environment_name']}`",
        f"- Ready for deployment-stage review: `{review['ready_for_deployment_stage_review']}`",
        "",
        "## Status Summary",
        "",
    ]
    for key, value in review["status_summary"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Notes", ""])
    lines.extend(f"- {note}" for note in review["notes"])
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    current_dir = Path(__file__).resolve().parent
    src_root = current_dir.parent / "src"
    sys.path.insert(0, str(src_root))

    from cgnat.bundle import dump_json, dump_text, ensure_path_within_cgnat, load_bundle
    from cgnat.deployment_stage_review import build_deployment_stage_review

    parser = argparse.ArgumentParser(description="Combine the CGNAT predeploy review and backend integration dry-run into one deployment-stage review package.")
    parser.add_argument("bundle_json", help="Path to the CGNAT deployment bundle JSON.")
    parser.add_argument("cgnat_review_json", help="Path to the CGNAT predeploy review summary JSON.")
    parser.add_argument("backend_integration_json", help="Path to the backend integration summary JSON.")
    parser.add_argument("output_dir", help="Directory to write the deployment-stage review package.")
    args = parser.parse_args()

    bundle = load_bundle(args.bundle_json)
    cgnat_review = _load_json(Path(args.cgnat_review_json).resolve())
    backend_integration = _load_json(Path(args.backend_integration_json).resolve())

    review = build_deployment_stage_review(
        bundle=bundle,
        cgnat_review=cgnat_review,
        backend_integration=backend_integration,
    )

    output_dir = ensure_path_within_cgnat(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    dump_json(output_dir / "deployment-stage-review-summary.json", review)
    dump_text(output_dir / "DEPLOYMENT_STAGE_REVIEW.md", _render_markdown(review))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
