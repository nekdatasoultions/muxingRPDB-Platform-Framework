#!/usr/bin/env python
"""Build a manifest and checksum file for one customer-scoped bundle."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _iter_bundle_files(bundle_dir: Path):
    for path in sorted(bundle_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name in {"manifest.txt", "sha256sums.txt"}:
            continue
        yield path


def build_bundle_manifest(bundle_dir: Path, manifest_path: Path, sha_path: Path) -> int:
    """Write manifest and checksum files for a customer bundle."""
    files = list(_iter_bundle_files(bundle_dir))
    if not files:
        raise ValueError(f"No bundle files found under {bundle_dir}")

    manifest_lines = [
        f"# Customer bundle manifest",
        f"# bundle_dir={bundle_dir.as_posix()}",
        f"# file_count={len(files)}",
        "",
    ]
    sha_lines = []

    for path in files:
        relative_path = path.relative_to(bundle_dir).as_posix()
        size = path.stat().st_size
        manifest_lines.append(f"{relative_path}\t{size}")
        sha_lines.append(f"{_sha256(path)}  {relative_path}")

    with manifest_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(manifest_lines) + "\n")
    with sha_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(sha_lines) + "\n")
    return len(files)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build manifest and checksums for a customer bundle.")
    parser.add_argument("bundle_dir", help="Path to the customer bundle directory")
    parser.add_argument(
        "--manifest-out",
        help="Optional explicit manifest output path (defaults to <bundle>/manifest.txt)",
    )
    parser.add_argument(
        "--sha-out",
        help="Optional explicit checksum output path (defaults to <bundle>/sha256sums.txt)",
    )
    args = parser.parse_args()

    bundle_dir = Path(args.bundle_dir).resolve()
    if not bundle_dir.exists():
        raise SystemExit(f"Bundle directory not found: {bundle_dir}")

    manifest_path = Path(args.manifest_out).resolve() if args.manifest_out else bundle_dir / "manifest.txt"
    sha_path = Path(args.sha_out).resolve() if args.sha_out else bundle_dir / "sha256sums.txt"

    try:
        file_count = build_bundle_manifest(bundle_dir, manifest_path, sha_path)
    except ValueError as exc:
        raise SystemExit(str(exc))

    print(f"Bundle manifest written: {manifest_path}")
    print(f"Bundle checksums written: {sha_path}")
    print(f"Bundle files indexed: {file_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
