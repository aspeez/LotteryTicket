from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data"
CONFIG_DIR = REPO_ROOT / "config"


def load_yaml(name: str) -> dict[str, Any]:
    """Load a YAML file from config/ by filename, e.g. load_yaml('leagues.yaml')."""
    path = CONFIG_DIR / name
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_raw_json(
    source: str,
    league: str,
    payload: Any,
    date_stamp: str,
    time_stamp: str,
    name: str | None = None,
) -> Path:
    """Write an immutable raw API response under data/raw/{source}/{league}/{date}/{time}.json.gz
    (or {time}_{name}.json.gz when `name` is given, e.g. an event id — used so a per-game
    fetch, like a box score, can be deduplicated later by scanning filenames)."""
    out_dir = DATA_DIR / "raw" / source / league / date_stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{time_stamp}_{name}.json.gz" if name else f"{time_stamp}.json.gz"
    path = out_dir / filename
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f)
    return path


def latest_raw_json(source: str, league: str) -> Path | None:
    """Return the most recently written raw file for a source/league, or None."""
    base = DATA_DIR / "raw" / source / league
    if not base.exists():
        return None
    files = sorted(base.glob("*/*.json.gz"))
    return files[-1] if files else None


def list_raw_json(source: str, league: str) -> list[Path]:
    """Return every raw file written for a source/league, oldest first."""
    base = DATA_DIR / "raw" / source / league
    if not base.exists():
        return []
    return sorted(base.glob("*/*.json.gz"))


def read_raw_json(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def curated_path(table: str, league: str) -> Path:
    """Directory for one curated table's partition for a league; caller writes files into it."""
    path = DATA_DIR / "curated" / table / f"league={league}"
    path.mkdir(parents=True, exist_ok=True)
    return path
