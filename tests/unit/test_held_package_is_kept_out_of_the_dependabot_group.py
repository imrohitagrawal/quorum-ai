"""A package held below a version in pyproject.toml is kept out of Dependabot's
grouped Python update (ADR-0190).

Without the exclusion, Dependabot bundles the held package's next release with
every other minor and patch update, and the test that guards the hold turns the
whole group red each month.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
HELD = "prometheus-fastapi-instrumentator"


def _python_group() -> dict[str, Any]:
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    uv = next(u for u in config["updates"] if u["package-ecosystem"] == "uv")
    return dict(uv["groups"]["python"])


def _requirement(name: str) -> str:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return str(next(r for r in project["dependencies"] if r.split(">")[0].split("<")[0] == name))


def test_the_held_package_still_carries_an_upper_bound() -> None:
    # Red when: the cap is dropped from pyproject.toml; then this file's other
    # test guards nothing and the exclusion should go too.
    assert "<8.1" in _requirement(HELD)


def test_the_held_package_is_excluded_from_the_grouped_python_update() -> None:
    # Red when: the exclusion is removed from .github/dependabot.yml while the
    # cap stays, so the held release rejoins (and turns red) the whole group.
    assert HELD in _python_group().get("exclude-patterns", [])
