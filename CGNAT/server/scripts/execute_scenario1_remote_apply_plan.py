from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def _framework_src_root() -> Path:
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent.parent / "framework" / "src"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_plan(remote_apply_dir: Path, manifest: dict[str, Any], execution_order: dict[str, Any]) -> dict[str, Any]:
    bash_path = shutil.which("bash")
    steps: list[dict[str, Any]] = []
    for step in execution_order["steps"]:
        planned_step = dict(step)
        if "script" in step:
            planned_step["absolute_script_path"] = str((remote_apply_dir / step["script"]).resolve())
        steps.append(planned_step)
    return {
        "plan_type": "scenario1_remote_apply_execution_plan",
        "service_id": manifest["service_id"],
        "bash_available": bool(bash_path),
        "bash_path": bash_path,
        "steps": steps,
    }


def _render_readme(plan: dict[str, Any]) -> str:
    status = "READY" if plan["bash_available"] else "NOT_READY"
    return "\n".join(
        [
            "# Scenario 1 Remote Apply Execution Plan",
            "",
            f"- Service ID: `{plan['service_id']}`",
            f"- Bash available: `{status}`",
            "",
            "## Notes",
            "",
            "- `plan` mode writes execution artifacts only.",
            "- `apply` mode runs the generated stage/apply scripts via bash.",
            "- This script does not invent remote commands; it executes the prepared remote plan.",
            "",
        ]
    )


def _execute_plan(plan: dict[str, Any]) -> dict[str, Any]:
    bash_path = plan["bash_path"]
    if not bash_path:
        raise RuntimeError("bash is required for remote apply execution mode.")

    results: list[dict[str, Any]] = []
    for step in plan["steps"]:
        if "absolute_script_path" not in step:
            results.append(
                {
                    "step_id": step["id"],
                    "role": step["role"],
                    "action": step["action"],
                    "status": "skipped_non_script",
                }
            )
            continue

        script_path = step["absolute_script_path"]
        completed = subprocess.run(
            [bash_path, script_path],
            capture_output=True,
            text=True,
            check=False,
        )
        result = {
            "step_id": step["id"],
            "role": step["role"],
            "action": step["action"],
            "script_path": script_path,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "status": "completed" if completed.returncode == 0 else "failed",
        }
        results.append(result)
        if completed.returncode != 0:
            raise RuntimeError(f"Remote apply step failed: {step['script']}")

    return {"results": results}


def main() -> int:
    sys.path.insert(0, str(_framework_src_root()))

    from cgnat.bundle import dump_json, dump_text, ensure_path_within_cgnat

    parser = argparse.ArgumentParser(description="Plan or execute a prepared Scenario 1 remote apply plan.")
    parser.add_argument("remote_apply_dir", help="Path to the prepared remote apply plan directory.")
    parser.add_argument("output_dir", help="Directory to write execution artifacts.")
    parser.add_argument("--mode", choices=("plan", "apply"), default="plan", help="Execution mode.")
    parser.add_argument(
        "--execute-live",
        action="store_true",
        help="When used with --mode apply, execute the stage/apply scripts. Without this flag, apply mode is refused.",
    )
    args = parser.parse_args()

    remote_apply_dir = Path(args.remote_apply_dir).resolve()
    output_dir = ensure_path_within_cgnat(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = _load_json(remote_apply_dir / "package-manifest.json")
    execution_order = _load_json(remote_apply_dir / "execution-order.json")
    plan = _build_plan(remote_apply_dir, manifest, execution_order)

    dump_json(output_dir / "execution-plan.json", plan)
    dump_json(
        output_dir / "execution-readiness.json",
        {
            "mode": args.mode,
            "bash_available": plan["bash_available"],
            "live_execution_allowed": plan["bash_available"] and args.execute_live,
        },
    )
    dump_text(output_dir / "README.md", _render_readme(plan))

    if args.mode == "apply":
        if not args.execute_live:
            print("Apply mode requires --execute-live; refusing to run remote stage/apply scripts.", file=sys.stderr)
            return 1
        result = _execute_plan(plan)
        dump_json(output_dir / "execution-result.json", result)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
