"""Config, JSON, and city-path helpers for the verifier.

City/zone path resolution lives here too (formerly ``cities.py``): the
verifier is city-agnostic, and adding a new BC municipality is a drop-in of
data files resolved by naming convention:

    configs/<city_key>.json
    benchmark/gold/<city_key>_gold_rules.json
    benchmark/gold/<city_key>_proposal_cases.json
    benchmark/gold/<city_key>_adversarial_cases.json      (optional)
    outputs/<city_key>_slim_pipeline5_registry/

``<city_key>`` is a lowercase slug such as ``burnaby_r1`` or ``vancouver_rt1``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).expanduser()
    with config_path.open("r", encoding="utf-8") as file:
        config = json.load(file)
    config["_config_path"] = str(config_path.resolve())
    return config


def write_json(path: str | Path, data: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.write("\n")


@dataclass(frozen=True)
class CityPaths:
    city_key: str
    config: Path
    gold_rules: Path
    proposal_cases: Path
    adversarial_cases: Path
    output_dir: Path


def normalize_city_key(city: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(city or "").lower()).strip("_")


def upstream_city_segment(city: str) -> str:
    """Return the upstream extraction folder segment for a city/zone key.

    Pipeline 5 writes its registry under ``outputs/<city>/`` keyed by the bare
    city (e.g. ``burnaby``), while this project keys configs/outputs by
    city+zone (``burnaby_r1``). Strip a trailing zone token so default upstream
    paths resolve per-city instead of hardcoding ``burnaby``:
    ``burnaby_r1`` -> ``burnaby``, ``vancouver_rt1`` -> ``vancouver``. A key with
    no recognizable zone suffix is returned unchanged.
    """
    key = normalize_city_key(city)
    return re.sub(r"_[a-z]*\d+[a-z]*$", "", key) or key


def resolve_city_paths(root: Path, city: str) -> CityPaths:
    """Resolve the conventional file paths for a city/zone key."""
    key = normalize_city_key(city)
    gold = root / "benchmark" / "gold"
    return CityPaths(
        city_key=key,
        config=root / "configs" / f"{key}.json",
        gold_rules=gold / f"{key}_gold_rules.json",
        proposal_cases=gold / f"{key}_proposal_cases.json",
        adversarial_cases=gold / f"{key}_adversarial_cases.json",
        output_dir=root / "outputs" / f"{key}_slim_pipeline5_registry",
    )
