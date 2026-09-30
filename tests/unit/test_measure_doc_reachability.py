"""``scripts/measure_doc_reachability.py`` is a measurement, not a gate; this
proves it measures something and that the map is reachable from the entry
point.

What turns it red: removing the `docs/README.md` pointer from `AGENTS.md`
(the map must be one hop from the entry point), or a change that makes the
script count nothing.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tests.repo_root import find_repo_root

#: The REAL repository root (see test_docs_map_matches_tree.py): inside mutmut's
#: ``./mutants/`` copy ``git ls-files`` lists nothing.
ROOT = find_repo_root(Path(__file__))
SCRIPT = ROOT / "scripts" / "measure_doc_reachability.py"

#: Reads the repository through git and imports nothing from the application;
#: deselected under mutmut by this marker.
pytestmark = pytest.mark.repo_introspection

if (
    subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, cwd=ROOT
    ).returncode
    != 0
):
    pytest.skip(
        "not inside a git work tree (a bare `git archive` copy): the script enumerates with "
        "`git ls-files`; run `git init && git add -A` in the copy first",
        allow_module_level=True,
    )


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("measure_doc_reachability", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_map_is_one_hop_from_agents_md() -> None:
    module = _load()
    files = module.tracked_docs(ROOT)
    assert len(files) > 100, f"expected the real repository, found {len(files)} tracked .md files"
    assert "docs/README.md" in module.references(ROOT, "AGENTS.md", files), (
        "AGENTS.md no longer links docs/README.md, so a new session cannot find the map"
    )


def test_the_measurement_counts_something_and_adds_up() -> None:
    module = _load()
    result = module.measure(ROOT)
    assert result["tracked"] > 100
    assert result["hop_0"] == 2, "AGENTS.md and CLAUDE.md are the two starting files"
    assert result["hop_1"] > 0
    reachable = sum(v for k, v in result.items() if k.startswith("hop_"))
    assert reachable + result["unreachable"] == result["tracked"]
