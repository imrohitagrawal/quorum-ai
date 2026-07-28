"""The mutation baseline doc must match the gate's own output artifact.

`docs/metrics/mutation-baseline.md` is the single place in the repo that states
the measured mutation score, and `docs/metrics/quality-ledger.md` copies that
number under a binding honesty rule. So the doc is only trustworthy if it agrees
with `build/mutation/score.txt` — the file `make mutation-baseline` actually
writes — and if any reproducibility claim it makes survives the recorded spread.

These are documentation-consistency gates, in the same family as
`tests/test_quality_ledger_consistency.py`.

They come in two tiers, because the two kinds of claim do not travel equally:

* **Machine-independent** (`test_every_recorded_run_…`,
  `test_threshold_is_below_every_score_the_doc_records`,
  `test_section_3_total_row_…`) read only the doc and the `Makefile`, so they
  run in CI and in a fresh clone. They are what catches a *stale* doc: a
  re-derivation that moved the doc but not `MUTATION_MIN_SCORE`, a floor raised
  above the evidence, or a run row whose counts and score disagree.
* **Machine-dependent** (`test_doc_records_the_numbers_…`,
  `test_reproducibility_claim_…`) compare against `build/mutation/score.txt` and
  **skip** when it is absent. They cannot be blocking CI checks: the
  killed/timeout split is hardware- and load-dependent (mutation-baseline.md §5),
  so a Linux runner legitimately produces different counts for an unchanged
  tree. The `mutation-baseline` job is advisory, but these two no longer LEAN on
  that: they skip unless the run is on the machine profile the doc records
  (macOS, §2), so they would stay harmless even if the job were promoted. On the Linux
  CI runner they report SKIPPED, which is the honest outcome: comparing Linux
  counts against macOS-recorded ones was never a signal to begin with. The step
  deliberately carries no `continue-on-error`, because
  `tests/test_doc_gate_consistency.py` treats any downgraded `run:` step as a
  downgraded gate and would then report the whole job advisory.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

#: §2 records every number in this doc as measured on macOS (Apple M-series).
#: The killed/timeout split does not travel to other hardware, so an artifact
#: produced anywhere else cannot be compared against those rows — see the
#: module docstring. Guard, not a preference: without it these two tiers block
#: merges on a difference the doc itself calls expected.
_DOC_HARDWARE_PROFILE = "darwin"


def _skip_unless_comparable(artifact: Path) -> str:
    """The reason this artifact cannot be compared, or "" when it can."""
    if not artifact.exists():
        return "no local `make mutation-baseline` artifact to compare against"
    if sys.platform != _DOC_HARDWARE_PROFILE:
        return (
            f"artifact produced on {sys.platform!r}, but the doc records macOS "
            "numbers (§2) — the killed/timeout split is hardware-dependent"
        )
    if "UNMEASURED" in artifact.read_text(encoding="utf-8"):
        # An all-timeout run records no score by design (§5), so there is
        # nothing for the doc to match. Skipping is right; falling through
        # would report the file "unparseable" and send the reader after a
        # corruption that does not exist.
        return "the local artifact is an UNMEASURED all-timeout run — no score to compare"
    return ""


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "metrics" / "mutation-baseline.md"
MAKEFILE = REPO_ROOT / "Makefile"
SCORE_ARTIFACT = REPO_ROOT / "build" / "mutation" / "score.txt"

# "| R1 | 2026-07-19 | 504 | 336 | 43 | 123 | 2 | 88.7% |"
_RUN_ROW = re.compile(
    r"^\|\s*(R\d+[a-z]?)\s*\|[^|]*\|" + r"".join([r"\s*(\d+)\s*\|"] * 5) + r"\s*(\d+\.\d)%\s*\|",
    re.MULTILINE,
)

# "mutants scored: 336 killed, 43 survived, 123 timeout (excluded), 2 no-tests"
_ARTIFACT_COUNTS = re.compile(
    r"mutants scored:\s*(\d+) killed,\s*(\d+) survived,\s*(\d+) timeout",
)
# "mutation score (killed / (killed+survived)) = 88.7% (threshold 80%)"
_ARTIFACT_SCORE = re.compile(r"mutation score \([^)]*\)+\s*=\s*(\d+\.\d)%")


def _doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def _total_row(text: str) -> tuple[int, int, int, int, int]:
    """The §3 `**total**` row: mutants, killed, survived, timeout, no-tests."""
    match = re.search(
        r"\|\s*\*\*total\*\*\s*\|" + r"".join([r"\s*\*?\*?(\d+)\*?\*?\s*\|"] * 5),
        text,
    )
    assert match, "§3 must keep a `**total**` row with 5 numeric columns"
    return tuple(int(group) for group in match.groups())  # type: ignore[return-value]


def test_section_3_total_row_is_arithmetically_self_consistent() -> None:
    mutants, killed, survived, timeout, no_tests = _total_row(_doc_text())
    assert killed + survived + timeout + no_tests == mutants
    expected = round(killed / (killed + survived) * 100, 1)
    assert f"{expected}%" in _doc_text(), (
        f"§3 states {killed} killed / {survived} survived, so the score must be "
        f"recorded as {expected}%"
    )


def _recorded_runs() -> list[tuple[str, int, int, int, int, int, float]]:
    """The §3 per-run table: (id, mutants, killed, survived, timeout, no-tests, score)."""
    rows: list[tuple[str, int, int, int, int, int, float]] = [
        (
            match.group(1),
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4)),
            int(match.group(5)),
            int(match.group(6)),
            float(match.group(7)),
        )
        for match in _RUN_ROW.finditer(_doc_text())
    ]
    assert rows, "§3 must keep a per-run table with rows `| R<n> | date | 5 counts | score% |`"
    return rows


def _makefile_threshold() -> int:
    match = re.search(r"^MUTATION_MIN_SCORE \?= (\d+)", MAKEFILE.read_text("utf-8"), re.M)
    assert match, "MUTATION_MIN_SCORE is not defined in the Makefile"
    return int(match.group(1))


def test_every_recorded_run_is_arithmetically_self_consistent() -> None:
    """A per-run row may not report counts and a score that disagree.

    Machine-independent: it reads only the doc, so it runs in CI and in a fresh
    clone, where no `build/mutation/score.txt` exists.
    """
    for run_id, mutants, killed, survived, timeout, no_tests, score in _recorded_runs():
        assert killed + survived + timeout + no_tests == mutants, (
            f"run {run_id}: {killed}+{survived}+{timeout}+{no_tests} != {mutants}"
        )
        expected = round(killed / (killed + survived) * 100, 1)
        assert expected == score, (
            f"run {run_id} reports {killed} killed / {survived} survived, "
            f"so its score must be {expected}%, not {score}%"
        )


def test_threshold_is_below_every_score_the_doc_records() -> None:
    """The gate's floor must sit under the worst measurement, and match the doc.

    This is the check that catches a *stale* doc without needing a mutation run:
    a re-derivation that forgets the Makefile, or a floor raised above the
    evidence, fails here in ordinary CI.
    """
    threshold = _makefile_threshold()
    assert f"MUTATION_MIN_SCORE ?= {threshold}" in _doc_text(), (
        f"§4 does not record the Makefile's MUTATION_MIN_SCORE ?= {threshold}"
    )
    assert f"(threshold {threshold}%)" in _doc_text(), (
        f"§3's quoted gate output does not use the Makefile threshold {threshold}%"
    )
    worst = min(row[6] for row in _recorded_runs())
    assert threshold < worst, (
        f"MUTATION_MIN_SCORE = {threshold} is not below the lowest recorded run "
        f"score ({worst}%) — the floor must be derived from the measurement"
    )


def test_doc_records_the_numbers_the_shipped_gate_produced() -> None:
    """The local run artifact must be one of the runs the doc actually records.

    Not "the numbers appear somewhere in the file": that is satisfied by any
    stale table that happens to reuse the same integers. The artifact's
    (killed, survived, timeout) triple has to match a specific row of §3's
    per-run table, and its survivor count has to match the `**total**` row.

    Going red here is the intended outcome when a fresh `make mutation-baseline`
    stops reproducing the recorded baseline — that is precisely the defect this
    file exists to surface. The fix is to re-measure and add the run, never to
    edit the prose to match.
    """
    if reason := _skip_unless_comparable(SCORE_ARTIFACT):
        pytest.skip(reason)
    artifact = SCORE_ARTIFACT.read_text(encoding="utf-8")
    counts = _ARTIFACT_COUNTS.search(artifact)
    score = _ARTIFACT_SCORE.search(artifact)
    assert counts and score, f"unparseable artifact: {SCORE_ARTIFACT}"

    killed, survived, timeout = (int(group) for group in counts.groups())
    recorded = {(row[2], row[3], row[4]): row[0] for row in _recorded_runs()}
    assert (killed, survived, timeout) in recorded, (
        f"{DOC.name} §3 records no run matching the local artifact "
        f"({killed} killed / {survived} survived / {timeout} timeout, "
        f"{score.group(1)}%); recorded runs are "
        f"{sorted(f'{name}: {k}/{s}/{t}' for (k, s, t), name in recorded.items())} "
        "— re-measure and record this run, do not edit the prose to match"
    )
    assert survived == _total_row(_doc_text())[2], (
        f"the artifact reports {survived} survivors but §3's `**total**` row "
        "reports a different number — the survivor set is the stable signal and "
        "must not drift from the gate's own output"
    )


def test_reproducibility_claim_matches_the_recorded_spread() -> None:
    """No "identical counts" claim while the doc records two different runs."""
    text = _doc_text()
    doc_killed = _total_row(text)[1]
    if reason := _skip_unless_comparable(SCORE_ARTIFACT):
        pytest.skip(reason)
    artifact = SCORE_ARTIFACT.read_text(encoding="utf-8")
    counts = _ARTIFACT_COUNTS.search(artifact)
    assert counts
    if int(counts.group(1)) == doc_killed:
        return
    for claim in ("identical counts", "reproduced §3 exactly"):
        assert claim not in text, (
            f"§7 claims {claim!r} but the run artifact reports "
            f"{counts.group(1)} killed against §3's {doc_killed}"
        )
