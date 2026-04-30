from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


CGNAT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CGNAT_ROOT.parent
PYTHON = sys.executable


def _run(*command: str) -> None:
    subprocess.run([PYTHON, *command], cwd=str(REPO_ROOT), check=True)


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    regression_root = CGNAT_ROOT / "build" / "regression"
    if regression_root.exists():
        shutil.rmtree(regression_root)
    regression_root.mkdir(parents=True, exist_ok=True)

    sample_bundle = CGNAT_ROOT / "framework" / "config" / "deployment-bundle.example.json"
    live_bundle = CGNAT_ROOT / "framework" / "config" / "deployment-bundle.rpdb-empty-live.json"
    backend_integration = CGNAT_ROOT / "framework" / "config" / "scenario1-backend-integration.rpdb-empty-live.json"
    host_access_strategy = CGNAT_ROOT / "server" / "config" / "host-access-strategy.rpdb-empty-live.json"

    sample_prep = regression_root / "sample-prep"
    live_materials = regression_root / "live-demo-materials"
    live_prep = regression_root / "live-prep"
    live_predeploy = regression_root / "live-predeploy-review"
    live_backend = regression_root / "live-backend-integration"
    deployment_stage = regression_root / "deployment-stage-review"

    _run(str(CGNAT_ROOT / "tests" / "run_tests.py"))
    _run("-m", "compileall", str(CGNAT_ROOT))

    _run(
        str(CGNAT_ROOT / "framework" / "scripts" / "prepare_scenario1.py"),
        str(sample_bundle),
        str(sample_prep),
    )

    _run(
        str(CGNAT_ROOT / "server" / "scripts" / "materialize_scenario1_demo_materials.py"),
        str(live_bundle),
        str(live_materials),
    )
    materials_manifest = live_materials / "materials-manifest.json"

    _run(
        str(CGNAT_ROOT / "framework" / "scripts" / "prepare_scenario1.py"),
        str(live_bundle),
        str(live_prep),
        "--materials-manifest-json",
        str(materials_manifest),
        "--aws-preflight",
    )
    _run(
        str(CGNAT_ROOT / "aws" / "scripts" / "deploy_scenario1_aws.py"),
        str(live_prep / "aws-package"),
        str(live_prep / "aws-apply-dryrun"),
        "--mode",
        "apply",
    )
    _run(
        str(CGNAT_ROOT / "framework" / "scripts" / "prepare_scenario1_predeploy_review.py"),
        str(live_bundle),
        str(live_prep),
        str(live_prep / "aws-apply-dryrun"),
        str(live_predeploy),
        "--host-access-strategy-json",
        str(host_access_strategy),
        "--materials-manifest-json",
        str(materials_manifest),
    )
    _run(
        str(CGNAT_ROOT / "framework" / "scripts" / "prepare_scenario1_backend_integration.py"),
        str(live_bundle),
        str(backend_integration),
        str(live_backend),
    )
    _run(
        str(CGNAT_ROOT / "framework" / "scripts" / "prepare_scenario1_deployment_stage_review.py"),
        str(live_bundle),
        str(live_predeploy / "predeploy-review-summary.json"),
        str(live_backend / "backend-integration-summary.json"),
        str(deployment_stage),
    )

    sample_summary = _load_json(sample_prep / "scenario1-preparation-summary.json")
    live_summary = _load_json(live_prep / "scenario1-preparation-summary.json")
    predeploy_summary = _load_json(live_predeploy / "predeploy-review-summary.json")
    backend_summary = _load_json(live_backend / "backend-integration-summary.json")
    deployment_summary = _load_json(deployment_stage / "deployment-stage-review-summary.json")

    regression_summary = {
        "regression_type": "cgnat_full_regression",
        "sample_validation_ok": bool(sample_summary.get("validation_ok")),
        "live_validation_ok": bool(live_summary.get("validation_ok")),
        "aws_live_create_allowed": bool(live_summary.get("aws_live_create_allowed")),
        "aws_preflight_ready_for_live_apply": bool(live_summary.get("aws_preflight_ready_for_live_apply")),
        "predeploy_ready_for_hard_review": bool(predeploy_summary.get("ready_for_hard_review")),
        "backend_validation_ok": bool(backend_summary.get("validation_ok")),
        "backend_deploy_dry_run_ok": bool(backend_summary.get("deploy_dry_run_ok")),
        "deployment_stage_ready": bool(deployment_summary.get("ready_for_deployment_stage_review")),
        "artifacts": {
            "sample_prep": str(sample_prep),
            "live_prep": str(live_prep),
            "live_predeploy_review": str(live_predeploy),
            "live_backend_integration": str(live_backend),
            "deployment_stage_review": str(deployment_stage),
        },
    }
    (regression_root / "regression-summary.json").write_text(
        json.dumps(regression_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
