"""Customer-scoped operation locks for live RPDB orchestration."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_STALE_AFTER_SECONDS = 60 * 60
LOCK_ROOT = Path("build") / "customer-operation-locks"


class CustomerOperationLockError(RuntimeError):
    """Raised when a customer operation is already in progress."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_name(customer_name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", customer_name).strip("._-")
    return safe or "customer"


def lock_path(repo_root: Path, customer_name: str) -> Path:
    return repo_root / LOCK_ROOT / f"{_safe_name(customer_name)}.json"


def read_lock(repo_root: Path, customer_name: str) -> dict[str, Any] | None:
    path = lock_path(repo_root, customer_name)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {"schema_version": 1, "customer_name": customer_name, "unreadable": True}
    payload["path"] = str(path)
    return payload


def lock_age_seconds(payload: dict[str, Any]) -> float | None:
    created_at = _parse_time(str(payload.get("created_at") or ""))
    if created_at is None:
        return None
    return (datetime.now(timezone.utc) - created_at).total_seconds()


def is_lock_active(payload: dict[str, Any] | None, *, stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS) -> bool:
    if not payload:
        return False
    age = lock_age_seconds(payload)
    return age is None or age < stale_after_seconds


def acquire_lock(
    repo_root: Path,
    customer_name: str,
    *,
    owner: str,
    mode: str,
    detail: dict[str, Any] | None = None,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> Path:
    path = lock_path(repo_root, customer_name)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = read_lock(repo_root, customer_name)
    if existing:
        if is_lock_active(existing, stale_after_seconds=stale_after_seconds):
            raise CustomerOperationLockError(
                f"customer operation already in progress for {customer_name}: {existing.get('path')}"
            )
        path.unlink(missing_ok=True)

    payload = {
        "schema_version": 1,
        "customer_name": customer_name,
        "owner": owner,
        "mode": mode,
        "pid": os.getpid(),
        "created_at": utc_now(),
        "stale_after_seconds": stale_after_seconds,
        "detail": detail or {},
    }
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError as exc:
        raise CustomerOperationLockError(
            f"customer operation already in progress for {customer_name}: {path}"
        ) from exc
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded)
    return path


def release_lock(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
