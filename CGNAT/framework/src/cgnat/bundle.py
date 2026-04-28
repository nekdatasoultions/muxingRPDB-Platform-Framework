from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_bundle(path: str | Path) -> dict[str, Any]:
    bundle_path = Path(path)
    with bundle_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path: str | Path, payload: Any) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def dump_text(path: str | Path, text: str) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
