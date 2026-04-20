#!/usr/bin/env python
"""Evaluate synthetic scale output against explicit repo-only thresholds."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUMMARY = REPO_ROOT / "build" / "scale-baseline" / "scale-baseline-summary.json"
DEFAULT_THRESHOLDS = REPO_ROOT / "muxer" / "config" / "scale-thresholds.json"
DEFAULT_JSON_OUT = REPO_ROOT / "build" / "scale-baseline" / "scale-gate-report.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if payload.endswith("\n") else payload + "\n", encoding="utf-8")


def _scenario_index(summary: dict[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
    indexed: dict[tuple[str, int], dict[str, Any]] = {}
    for scenario in summary.get("scenarios") or []:
        indexed[(str(scenario.get("profile") or ""), int(scenario.get("customer_count") or 0))] = scenario
    return indexed


def _check(name: str, actual: int | float, expected: int | float) -> dict[str, Any]:
    passed = actual <= expected
    return {
        "name": name,
        "status": "passed" if passed else "failed",
        "actual": actual,
        "expected_max": expected,
    }


def _check_exact(name: str, actual: int | float, expected: int | float) -> dict[str, Any]:
    passed = actual == expected
    return {
        "name": name,
        "status": "passed" if passed else "failed",
        "actual": actual,
        "expected_exact": expected,
    }


def _evaluate_scenario(profile: str, count: int, scenario: dict[str, Any], profile_thresholds: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    legacy_rules = int(((scenario.get("muxer_legacy_runtime") or {}).get("total_rules")) or 0)
    bridge_rules = int(((scenario.get("muxer_legacy_runtime") or {}).get("bridge_total_rules")) or 0)
    headend = scenario.get("headend_post_ipsec_nat_runtime") or {}
    apply_commands = int(headend.get("apply_command_count") or 0)
    rollback_commands = int(headend.get("rollback_command_count") or 0)
    max_per_customer = int(headend.get("max_apply_commands_per_customer") or 0)
    timing = scenario.get("timing_ms") or {}
    cpu = scenario.get("cpu_ms") or {}
    memory = scenario.get("memory_bytes") or {}
    count_key = str(count)

    checks.append(_check_exact("legacy_rules", legacy_rules, int(profile_thresholds.get("max_legacy_rules") or 0)))
    checks.append(_check_exact("bridge_rules", bridge_rules, int(profile_thresholds.get("max_bridge_rules") or 0)))

    if "max_headend_apply_commands" in profile_thresholds:
        checks.append(
            _check_exact(
                "headend_apply_commands",
                apply_commands,
                int(profile_thresholds.get("max_headend_apply_commands") or 0),
            )
        )
    else:
        checks.append(
            _check(
                "headend_apply_commands",
                apply_commands,
                int(profile_thresholds.get("max_headend_apply_commands_multiplier") or 0) * count,
            )
        )

    if "max_headend_rollback_commands" in profile_thresholds:
        checks.append(
            _check_exact(
                "headend_rollback_commands",
                rollback_commands,
                int(profile_thresholds.get("max_headend_rollback_commands") or 0),
            )
        )
    else:
        checks.append(
            _check(
                "headend_rollback_commands",
                rollback_commands,
                int(profile_thresholds.get("max_headend_rollback_commands_multiplier") or 0) * count,
            )
        )

    checks.append(
        _check_exact(
            "headend_max_apply_per_customer",
            max_per_customer,
            int(profile_thresholds.get("max_headend_apply_commands_per_customer") or 0),
        )
    )

    max_plan_build_ms = float((profile_thresholds.get("max_plan_build_ms") or {}).get(count_key) or 0.0)
    max_plan_cpu_ms = float((profile_thresholds.get("max_plan_cpu_ms") or {}).get(count_key) or 0.0)
    max_plan_peak_memory = int((profile_thresholds.get("max_plan_peak_memory_bytes") or {}).get(count_key) or 0)
    for metric_name in ("apply_plan_build", "remove_plan_build", "rollback_plan_build"):
        checks.append(_check(metric_name, float(timing.get(metric_name) or 0.0), max_plan_build_ms))
    for metric_name in ("apply_plan_build", "remove_plan_build", "rollback_plan_build"):
        checks.append(_check(f"{metric_name}_cpu", float(cpu.get(metric_name) or 0.0), max_plan_cpu_ms))
    for metric_name in ("apply_plan_peak", "remove_plan_peak", "rollback_plan_peak"):
        checks.append(_check(metric_name, int(memory.get(metric_name) or 0), max_plan_peak_memory))

    failures = [check for check in checks if check["status"] != "passed"]
    return {
        "profile": profile,
        "customer_count": count,
        "status": "passed" if not failures else "failed",
        "failed_checks": [check["name"] for check in failures],
        "checks": checks,
        "scenario_metrics": {
            "legacy_rules": legacy_rules,
            "bridge_rules": bridge_rules,
            "headend_apply_commands": apply_commands,
            "headend_rollback_commands": rollback_commands,
            "headend_max_apply_per_customer": max_per_customer,
            "timing_ms": timing,
            "cpu_ms": cpu,
            "memory_bytes": memory,
        },
    }


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# RPDB Repo-Only Scale Gate Report",
        "",
        f"- Overall status: `{report['overall_status']}`",
        f"- Summary source: `{report['summary_path']}`",
        f"- Threshold source: `{report['threshold_path']}`",
        f"- Generated at: `{report['generated_at']}`",
        "",
        "## Results",
        "",
        "| Profile | Count | Status | Failed Checks |",
        "| --- | ---: | --- | --- |",
    ]
    for evaluation in report.get("evaluations") or []:
        failed = ", ".join(evaluation.get("failed_checks") or []) or "-"
        lines.append(
            f"| `{evaluation['profile']}` | `{evaluation['customer_count']}` | `{evaluation['status']}` | `{failed}` |"
        )
    failures = [item for item in (report.get("evaluations") or []) if item.get("status") != "passed"]
    lines.extend(["", "## Failure Details", ""])
    if not failures:
        lines.append("No failing scale checks were recorded.")
    else:
        for failure in failures:
            lines.append(f"### `{failure['profile']}` at `{failure['customer_count']}`")
            lines.append("")
            for check in failure.get("checks") or []:
                if check.get("status") == "passed":
                    continue
                if "expected_exact" in check:
                    expectation = f"expected `{check['expected_exact']}`"
                else:
                    expectation = f"expected <= `{check['expected_max']}`"
                lines.append(
                    f"- `{check['name']}` failed: actual `{check['actual']}`, {expectation}"
                )
            lines.append("")
    return "\n".join(lines) + "\n"


def build_report(summary: dict[str, Any], thresholds: dict[str, Any], *, summary_path: Path, threshold_path: Path) -> dict[str, Any]:
    indexed = _scenario_index(summary)
    evaluations: list[dict[str, Any]] = []
    missing_targets: list[str] = []
    for profile, profile_thresholds in (thresholds.get("profiles") or {}).items():
        for count in thresholds.get("target_counts") or []:
            scenario = indexed.get((profile, int(count)))
            if scenario is None:
                missing_targets.append(f"{profile}:{count}")
                continue
            evaluations.append(_evaluate_scenario(profile, int(count), scenario, profile_thresholds))
    overall_status = "passed" if not any(item.get("status") != "passed" for item in evaluations) and not missing_targets else "failed"
    return {
        "schema_version": 1,
        "generated_from": "muxer/scripts/generate_scale_report.py",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary_path": str(summary_path.resolve()),
        "threshold_path": str(threshold_path.resolve()),
        "overall_status": overall_status,
        "target_counts": thresholds.get("target_counts") or [],
        "missing_targets": missing_targets,
        "evaluations": evaluations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate synthetic scale output against explicit thresholds.")
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY), help="Path to the scale summary JSON")
    parser.add_argument("--thresholds", default=str(DEFAULT_THRESHOLDS), help="Path to the scale threshold JSON")
    parser.add_argument("--out-json", default=str(DEFAULT_JSON_OUT), help="Path to write the evaluated report JSON")
    parser.add_argument("--out-md", help="Optional path to write the evaluated report as Markdown")
    parser.add_argument("--json", action="store_true", help="Print the evaluated report JSON")
    args = parser.parse_args()

    summary_path = Path(args.summary).resolve()
    threshold_path = Path(args.thresholds).resolve()
    report = build_report(
        _load_json(summary_path),
        _load_json(threshold_path),
        summary_path=summary_path,
        threshold_path=threshold_path,
    )

    if args.out_json:
        _write_json(Path(args.out_json).resolve(), report)
    if args.out_md:
        _write_text(Path(args.out_md).resolve(), _render_markdown(report))

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Scale report: {report['overall_status']}")
        if args.out_json:
            print(f"JSON: {Path(args.out_json).resolve()}")
        if args.out_md:
            print(f"Markdown: {Path(args.out_md).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
