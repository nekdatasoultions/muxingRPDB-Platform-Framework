#!/usr/bin/env python
"""Run demo-friendly customer lifecycle operations for validated RPDB profiles."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "customers" / "deploy_customer.py"
REMOVE_SCRIPT = REPO_ROOT / "scripts" / "customers" / "remove_customer.py"


@dataclass(frozen=True)
class DemoProfile:
    key: str
    description: str
    customer_name: str
    customer_file: Path
    observation: Path | None = None
    notes: str | None = None


def _repo_file(*parts: str) -> Path:
    return (REPO_ROOT / Path(*parts)).resolve()


PROFILES: dict[str, DemoProfile] = {
    "customer4-non-nat": DemoProfile(
        key="customer4-non-nat",
        description="Regular non-NAT VPN demo using the base Customer 4 request.",
        customer_name="vpn-customer-stage1-15-cust-0004",
        customer_file=_repo_file(
            "muxer",
            "config",
            "customer-requests",
            "migrated",
            "vpn-customer-stage1-15-cust-0004.yaml",
        ),
        notes="Validated dry run resolves to the non-NAT head-end family on rpdb-empty-live.",
    ),
    "customer7-nat-t": DemoProfile(
        key="customer7-nat-t",
        description="NAT-T VPN demo using Customer 7 plus the tracked NAT-T observation event.",
        customer_name="vpn-customer-stage1-15-cust-0007",
        customer_file=_repo_file(
            "muxer",
            "config",
            "customer-requests",
            "migrated",
            "vpn-customer-stage1-15-cust-0007.yaml",
        ),
        observation=_repo_file(
            "muxer",
            "config",
            "customer-requests",
            "migrated",
            "vpn-customer-stage1-15-cust-0007-nat-t-observation.json",
        ),
        notes="Validated dry run resolves to the NAT head-end family when the observation is supplied.",
    ),
    "cgnat-per-customer-outer": DemoProfile(
        key="cgnat-per-customer-outer",
        description="CGNAT demo with per-customer outer certificate negotiation.",
        customer_name="example-minimal-cgnat-local-pki",
        customer_file=_repo_file(
            "muxer",
            "config",
            "customer-requests",
            "examples",
            "example-minimal-cgnat-local-pki.yaml",
        ),
        notes="Validated dry run resolves to the CGNAT head-end plus the non-NAT backend head-end.",
    ),
    "cgnat-shared-isp-gateway": DemoProfile(
        key="cgnat-shared-isp-gateway",
        description="CGNAT demo with the shared ISP gateway outer topology.",
        customer_name="example-minimal-cgnat-shared-isp-scenario2-local-pki",
        customer_file=_repo_file(
            "muxer",
            "config",
            "customer-requests",
            "examples",
            "example-minimal-cgnat-shared-isp-scenario2-local-pki.yaml",
        ),
        notes="Validated dry run resolves to the CGNAT head-end, the non-NAT backend head-end, and isp-cgnat-router-2.",
    ),
}

def repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def quote_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def resolve_profile(key: str) -> DemoProfile:
    try:
        return PROFILES[key]
    except KeyError as exc:
        choices = ", ".join(sorted(PROFILES))
        raise SystemExit(f"Unknown profile '{key}'. Choose one of: {choices}") from exc


def build_action_command(
    *,
    profile: DemoProfile,
    action: str,
    environment: str,
    out_root: Path,
    json_output: bool,
) -> list[str]:
    out_dir = out_root / profile.key / action
    if action in {"plan-provision", "provision", "reapply"}:
        command = [
            sys.executable,
            repo_relative(DEPLOY_SCRIPT),
            "--customer-file",
            repo_relative(profile.customer_file),
            "--environment",
            environment,
            "--out-dir",
            repo_relative(out_dir),
        ]
        if profile.observation is not None:
            command.extend(["--observation", repo_relative(profile.observation)])
        command.append("--dry-run" if action == "plan-provision" else "--approve")
    elif action in {"plan-remove", "remove"}:
        command = [
            sys.executable,
            repo_relative(REMOVE_SCRIPT),
            "--customer-name",
            profile.customer_name,
            "--environment",
            environment,
            "--out-dir",
            repo_relative(out_dir),
            "--dry-run" if action == "plan-remove" else "--approve",
        ]
    else:
        raise SystemExit(f"Unsupported action '{action}'")

    if json_output:
        command.append("--json")
    return command


def print_profile_summary(profile: DemoProfile, environment: str, out_root: Path) -> None:
    print(f"profile: {profile.key}")
    print(f"description: {profile.description}")
    print(f"customer_name: {profile.customer_name}")
    print(f"customer_file: {repo_relative(profile.customer_file)}")
    print(f"observation: {repo_relative(profile.observation) if profile.observation else '(none)'}")
    print(f"default_environment: {environment}")
    print(f"default_out_root: {repo_relative(out_root)}")
    if profile.notes:
        print(f"notes: {profile.notes}")
    print("actions:")
    for action in ("plan-provision", "provision", "reapply", "plan-remove", "remove"):
        command = build_action_command(
            profile=profile,
            action=action,
            environment=environment,
            out_root=out_root,
            json_output=False,
        )
        print(f"  {action}: {quote_command(command)}")


def list_profiles() -> None:
    for key in sorted(PROFILES):
        profile = PROFILES[key]
        print(f"{profile.key}: {profile.description}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run demo customer lifecycle flows for validated RPDB demo profiles."
    )
    parser.add_argument(
        "action",
        choices=["list-profiles", "show", "plan-provision", "provision", "reapply", "plan-remove", "remove"],
        help="Operation to perform.",
    )
    parser.add_argument("profile", nargs="?", help="Demo profile name. Not required for list-profiles.")
    parser.add_argument(
        "--environment",
        default="rpdb-empty-live",
        help="Deployment environment name or file. Defaults to rpdb-empty-live.",
    )
    parser.add_argument(
        "--out-root",
        default=str(REPO_ROOT / "build" / "demo-customer-lifecycle"),
        help="Root output directory for generated execution plans and packages.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Pass --json through to the underlying deploy/remove script.",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print the resolved command without executing it.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_root = Path(args.out_root).resolve()

    if args.action == "list-profiles":
        if args.profile:
            raise SystemExit("list-profiles does not take a profile name")
        list_profiles()
        return 0

    if not args.profile:
        raise SystemExit(f"{args.action} requires a profile name")

    profile = resolve_profile(args.profile)
    if args.action == "show":
        print_profile_summary(profile, args.environment, out_root)
        return 0

    command = build_action_command(
        profile=profile,
        action=args.action,
        environment=args.environment,
        out_root=out_root,
        json_output=args.json,
    )
    print(quote_command(command), file=sys.stderr)
    if args.print_only:
        return 0

    completed = subprocess.run(command, cwd=str(REPO_ROOT), check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
