from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def cgnat_root() -> Path:
    return Path(__file__).resolve().parents[3]


def ensure_path_within_cgnat(path: str | Path) -> Path:
    candidate = Path(path).resolve()
    root = cgnat_root().resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Refusing to write outside CGNAT workspace: {candidate}")
    return candidate


def load_bundle(path: str | Path) -> dict[str, Any]:
    bundle_path = Path(path)
    with bundle_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path: str | Path, payload: Any) -> None:
    output_path = ensure_path_within_cgnat(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def dump_text(path: str | Path, text: str) -> None:
    output_path = ensure_path_within_cgnat(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
