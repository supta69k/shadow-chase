"""Tiny local persistence: best score and rank per difficulty."""

from __future__ import annotations

import json
from pathlib import Path


def _default_path() -> Path:
    return Path(__file__).resolve().parent.parent / "best_scores.json"


def load_best(path: Path | None = None) -> dict:
    """Return {"DIFFICULTY": {"score": int, "rank": str}}; {} when absent/broken."""
    try:
        target = path or _default_path()
        if not target.exists():
            return {}
        with open(target, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def record_best(
    path: Path | None, difficulty: str, score: int, rank: str
) -> tuple[bool, dict]:
    """Store a new best for one difficulty. Returns (is_new_record, all_data)."""
    data = load_best(path)
    entry = data.get(difficulty) or {}
    is_new_record = score > int(entry.get("score", -1))
    if is_new_record:
        data[difficulty] = {"score": int(score), "rank": rank}
        try:
            target = path or _default_path()
            with open(target, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
        except Exception:
            pass
    return is_new_record, data
