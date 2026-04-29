from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _framework_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _cgnat_root() -> Path:
    return _framework_dir().parent


def _script_path(*parts: str) -> Path:
    return _cgnat_root().joinpath(*parts)


def _run_script(*args: str) -> None:
    subprocess.run(
        [sys.executable, *args],
        check=True,
        cwd=str(_cgnat_root().parent),
    )


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _render_readme(summary: dict[str, Any]) -> str:
    steps = summary["steps"]
    remote_line = ""
    if steps.get("remote_apply_output"):
        remote_line = f"- Remote apply plan: `{steps['remote_apply_output']}`"
    return "\n".join(
        [
            "# Scenario 1 Preparation Output",
            "",
            f"- Service ID: `{summary['service_id']}`",
            f"- Customer ID: `{summary['customer_id']}`",
            f"- Environment: `{summary['environment_name']}`",
            f"- Validation OK: `{summary['validation_ok']}`",
            f"- AWS plan live-create ready: `{summary['aws_live_create_allowed']}`",
            "",
            "## Generated Paths",
            "",
            f"- Framework render: `{steps['framework_render_output']}`",
            f"- AWS package: `{steps['aws_package_output']}`",
            f"- AWS deploy plan: `{steps['aws_deploy_plan_output']}`",
            f"- Server package: `{steps['server_package_output']}`",
            f"- Server configs: `{steps['server_config_output']}`",
            f"- Host apply package: `{steps['host_apply_output']}`",
            remote_line,
            "",
            "## Notes",
            "",
            "- This orchestration does not deploy infrastructure.",
            "- AWS planning remains in plan mode only.",
            "- Server-side artifacts remain generated-only until a later apply step is approved.",
            "",
        ]
    )


def main() -> int:
    current_dir = Path(__file__).resolve().parent
    src_root = current_dir.parent / "src"
    sys.path.insert(0, str(src_root))

    from cgnat.bundle import dump_json, dump_text, ensure_path_within_cgnat, load_bundle

    parser = argparse.ArgumentParser(
        description="Prepare the full local Scenario 1 artifact set without deploying infrastructure."
    )
    parser.add_argument("bundle", help="Path to the deployment bundle JSON file.")
    parser.add_argument("output_dir", help="Directory to write the orchestrated preparation outputs.")
    parser.add_argument(
        "--host-access-json",
        help="Optional host access JSON file. When supplied, also render a no-execution remote apply plan.",
    )
    args = parser.parse_args()

    bundle_path = Path(args.bundle).resolve()
    output_dir = ensure_path_within_cgnat(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    framework_render_dir = output_dir / "framework-render"
    aws_package_dir = output_dir / "aws-package"
    aws_deploy_plan_dir = output_dir / "aws-deploy-plan"
    server_package_dir = output_dir / "server-package"
    server_config_dir = output_dir / "server-configs"
    host_apply_dir = output_dir / "host-apply"
    remote_apply_dir = output_dir / "remote-apply-plan"

    _run_script(
        str(_script_path("framework", "scripts", "render_bundle.py")),
        str(bundle_path),
        str(framework_render_dir),
    )
    _run_script(
        str(_script_path("aws", "scripts", "render_aws_package.py")),
        str(bundle_path),
        str(aws_package_dir),
    )
    _run_script(
        str(_script_path("aws", "scripts", "deploy_scenario1_aws.py")),
        str(aws_package_dir),
        str(aws_deploy_plan_dir),
        "--mode",
        "plan",
    )
    _run_script(
        str(_script_path("server", "scripts", "render_server_package.py")),
        str(bundle_path),
        str(server_package_dir),
    )
    _run_script(
        str(_script_path("server", "scripts", "render_scenario1_server_configs.py")),
        str(server_package_dir),
        str(server_config_dir),
    )
    _run_script(
        str(_script_path("server", "scripts", "prepare_scenario1_host_apply.py")),
        str(server_config_dir),
        str(host_apply_dir),
    )
    if args.host_access_json:
        _run_script(
            str(_script_path("server", "scripts", "prepare_scenario1_remote_apply_plan.py")),
            str(host_apply_dir),
            str(Path(args.host_access_json).resolve()),
            str(remote_apply_dir),
        )

    bundle = load_bundle(bundle_path)
    validation = _load_json(framework_render_dir / "framework" / "validation-result.json")
    aws_readiness = _load_json(aws_deploy_plan_dir / "deployment-readiness.json")

    steps = {
        "framework_render_output": str(framework_render_dir),
        "aws_package_output": str(aws_package_dir),
        "aws_deploy_plan_output": str(aws_deploy_plan_dir),
        "server_package_output": str(server_package_dir),
        "server_config_output": str(server_config_dir),
        "host_apply_output": str(host_apply_dir),
    }
    if args.host_access_json:
        steps["remote_apply_output"] = str(remote_apply_dir)

    summary = {
        "orchestration_type": "scenario1_preparation",
        "service_id": bundle["sot"]["service_id"],
        "customer_id": bundle["sot"]["customer_id"],
        "environment_name": bundle["operations"]["environment_name"],
        "validation_ok": validation["ok"],
        "validation_error_count": validation["error_count"],
        "validation_warning_count": validation["warning_count"],
        "aws_live_create_allowed": aws_readiness["live_create_allowed"],
        "aws_blocking_issue_count": aws_readiness["blocking_issue_count"],
        "steps": steps,
    }

    dump_json(output_dir / "scenario1-preparation-summary.json", summary)
    dump_text(output_dir / "README.md", _render_readme(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
