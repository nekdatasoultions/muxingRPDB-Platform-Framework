#!/usr/bin/env python
"""Provision one RPDB customer file into a complete repo-only review package."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muxerlib.allocation import normalize_pool_class


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _customer_name_from_request(path: Path) -> str:
    doc = _load_yaml(path)
    customer_name = str((doc.get("customer") or {}).get("name") or "").strip()
    if not customer_name:
        raise ValueError(f"customer.name missing in {path}")
    return customer_name


def _request_pool_class(path: Path) -> str:
    doc = _load_yaml(path)
    customer = doc.get("customer") or {}
    backend = customer.get("backend") or {}
    return normalize_pool_class(
        str(customer.get("customer_class") or ""),
        str(backend.get("cluster") or ""),
    )


def _default_environment_file(
    *,
    muxer_dir: Path,
    request_path: Path,
    observation_path: Path | None,
) -> Path:
    if observation_path is not None:
        return muxer_dir / "config" / "environment-defaults" / "rpdb-empty-nat-active-a.yaml"
    if _request_pool_class(request_path) == "nat":
        return muxer_dir / "config" / "environment-defaults" / "rpdb-empty-nat-active-a.yaml"
    return muxer_dir / "config" / "environment-defaults" / "rpdb-empty-nonnat-active-a.yaml"


def _repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _run_prepare_customer_pilot(command: list[str], *, repo_root: Path) -> tuple[int, str, str, dict[str, Any] | None]:
    completed = subprocess.run(
        command,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    parsed: dict[str, Any] | None = None
    if completed.stdout.strip():
        try:
            parsed = json.loads(completed.stdout)
        except json.JSONDecodeError:
            parsed = None
    return completed.returncode, completed.stdout, completed.stderr, parsed


def _build_run_report(
    *,
    status: str,
    repo_root: Path,
    request_path: Path,
    observation_path: Path | None,
    package_dir: Path,
    environment_file: Path,
    command: list[str],
    readiness: dict[str, Any] | None,
    stdout: str,
    stderr: str,
    returncode: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "action": "provision_customer_end_to_end",
        "status": status,
        "ready_for_review": bool((readiness or {}).get("ready_for_review")),
        "live_apply": bool((readiness or {}).get("live_apply")),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "request": _repo_relative(request_path, repo_root),
        "observation": _repo_relative(observation_path, repo_root) if observation_path else None,
        "package_dir": _repo_relative(package_dir, repo_root),
        "environment_file": _repo_relative(environment_file, repo_root),
        "readiness_path": _repo_relative(package_dir / "pilot-readiness.json", repo_root),
        "run_report_path": _repo_relative(package_dir / "provisioning-run.json", repo_root),
        "delegated_command": command,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "readiness": readiness,
    }


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    muxer_dir = repo_root / "muxer"

    parser = argparse.ArgumentParser(
        description=(
            "One-file RPDB customer provisioning entrypoint. Given a customer "
            "request YAML, produce the full repo-only provisioning package, "
            "readiness report, bundle, and double-verification artifacts."
        )
    )
    parser.add_argument("request", help="Customer request YAML")
    parser.add_argument(
        "--observation",
        help="Optional NAT-T UDP/4500 observation JSON/YAML. Supplying this promotes the package to NAT-T.",
    )
    parser.add_argument(
        "--out-dir",
        help="Repo-local output directory. Defaults to build/customer-provisioning/<customer-name>.",
    )
    parser.add_argument(
        "--environment-file",
        help=(
            "Environment binding YAML. Defaults to rpdb-empty-nonnat-active-a "
            "for normal requests and rpdb-empty-nat-active-a when --observation is supplied."
        ),
    )
    parser.add_argument(
        "--existing-source-root",
        action="append",
        default=[],
        help=(
            "Existing customer source roots for collision checks. Defaults to "
            "examples and migrated source roots."
        ),
    )
    parser.add_argument(
        "--replace-customer",
        action="append",
        default=[],
        help="Ignore an existing same-name customer during repo-only planning.",
    )
    parser.add_argument("--json", action="store_true", help="Print the provisioning run report as JSON")
    args = parser.parse_args()

    request_path = Path(args.request).resolve()
    observation_path = Path(args.observation).resolve() if args.observation else None
    customer_name = _customer_name_from_request(request_path)
    package_dir = (
        Path(args.out_dir).resolve()
        if args.out_dir
        else (repo_root / "build" / "customer-provisioning" / customer_name).resolve()
    )
    environment_file = (
        Path(args.environment_file).resolve()
        if args.environment_file
        else _default_environment_file(
            muxer_dir=muxer_dir,
            request_path=request_path,
            observation_path=observation_path,
        ).resolve()
    )
    existing_roots = args.existing_source_root or [
        str(muxer_dir / "config" / "customer-sources" / "examples"),
        str(muxer_dir / "config" / "customer-sources" / "migrated"),
    ]

    command = [
        sys.executable,
        "muxer/scripts/prepare_customer_pilot.py",
        str(request_path),
        "--out-dir",
        str(package_dir),
        "--environment-file",
        str(environment_file),
        "--json",
    ]
    if observation_path:
        command.extend(["--observation", str(observation_path)])
    for root in existing_roots:
        command.extend(["--existing-source-root", root])
    for customer in args.replace_customer:
        command.extend(["--replace-customer", customer])

    returncode, stdout, stderr, readiness = _run_prepare_customer_pilot(command, repo_root=repo_root)
    status = "ready_for_review" if returncode == 0 and readiness and readiness.get("ready_for_review") else "blocked"
    run_report = _build_run_report(
        status=status,
        repo_root=repo_root,
        request_path=request_path,
        observation_path=observation_path,
        package_dir=package_dir,
        environment_file=environment_file,
        command=command,
        readiness=readiness,
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
    )
    _write_json(package_dir / "provisioning-run.json", run_report)

    if args.json:
        print(json.dumps(run_report, indent=2, sort_keys=True))
    else:
        print(f"Provisioning package status: {status}")
        print(f"- customer: {customer_name}")
        print(f"- request: {_repo_relative(request_path, repo_root)}")
        if observation_path:
            print(f"- observation: {_repo_relative(observation_path, repo_root)}")
        print(f"- package: {_repo_relative(package_dir, repo_root)}")
        print(f"- readiness: {_repo_relative(package_dir / 'pilot-readiness.json', repo_root)}")
        print(f"- run report: {_repo_relative(package_dir / 'provisioning-run.json', repo_root)}")

    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
