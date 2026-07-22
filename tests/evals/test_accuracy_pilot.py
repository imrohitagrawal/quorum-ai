"""P2: the measured-accuracy PILOT harness (n = 7, operator-authored labels).

This suite makes ``docs/metrics/accuracy-pilot.md`` a *measurement* instead of
an assertion. The pilot's integrity spine, mechanised:

1. **The labels are operator-authored and read-only.** The 7 subject-matter
   correctness labels in ``pilot/operator_labels.json`` were authored by the
   operator (Rohit Agrawal, 2026-07-22) and transcribed verbatim. The harness
   authors ZERO labels; it only scores the engine against them. The loader
   REJECTS an empty label set (an unlabeled pilot must never silently report
   100%), a ``correctness`` outside the engine's own three-value enum, and a
   label whose ``case_id`` has no golden case.

2. **Engine verdicts are RE-DERIVED, never read.** Agreement is computed by
   running the real Layer-A engine (``evaluate_layer_a``) over the golden
   fixtures — the pilot cannot quote a hard-coded accuracy, and the fixture's
   own ``label`` field is deliberately not consulted.

3. **The mapping was fixed BEFORE computing.** Engine ``faithfulness_label``
   and operator ``correctness`` share the same three-value vocabulary
   ({faithful, unfaithful, partial} — the operator queue defines ``correctness``
   in exactly these terms), so agreement is the IDENTITY comparison
   ``engine.faithfulness_label == label.correctness``. No re-bucketing exists
   that could be tuned post-hoc to force a result.

4. **The doc cannot drift from the measurement.** Every per-case verdict and
   the aggregate recorded in ``docs/metrics/accuracy-pilot.md`` are asserted
   against the freshly computed values — whatever they are. If the engine ever
   disagrees with a human label, the doc must record the real number or this
   suite goes red; it must never be "fixed" by editing a label.

This pilot is PROCESS-ADJACENT scope: n = 7 human-labeled verdicts on
hand-authored golden fixtures. It is NOT the quality-ledger Part 2 measurement
(real captured runs), and ``quality-ledger.md`` Part 2 stays em-dash.

Zero I/O beyond reading tracked files. No network, no judge, $0.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_PILOT_LOADER_PATH = Path(__file__).resolve().parent / "pilot" / "loader.py"
_spec = importlib.util.spec_from_file_location("p2_pilot_loader", _PILOT_LOADER_PATH)
assert _spec is not None and _spec.loader is not None
pilot = importlib.util.module_from_spec(_spec)
sys.modules["p2_pilot_loader"] = pilot
_spec.loader.exec_module(pilot)

PILOT_DOC = Path(__file__).resolve().parents[2] / "docs" / "metrics" / "accuracy-pilot.md"
QUALITY_LEDGER = Path(__file__).resolve().parents[2] / "docs" / "metrics" / "quality-ledger.md"

#: The exact scope the operator labeled on 2026-07-22. Pins the pilot's n so a
#: silently dropped or smuggled-in label cannot change the denominator unnoticed.
#: …and pins each label's CORRECTNESS value (transcribed from the same verbatim
#: operator handoff, 2026-07-22) so a silently flipped label cannot keep the
#: suite green — an intentional operator re-label must edit this pin in the
#: same reviewed diff, making the change visible. (Review finding CT-F1.)
EXPECTED_CORRECTNESS = {
    "grounded-consensus": "faithful",
    "fabricated-citation-launder": "unfaithful",
    "wholly-refused": "partial",
    "partial-live-two-failed": "partial",
    "human-as-of-date-fact": "partial",
    "preserved-false-consensus": "faithful",
    "partial-grounding-medium": "faithful",
}
EXPECTED_CASE_IDS = frozenset(EXPECTED_CORRECTNESS)


# --------------------------------------------------------------------------
# The label loader REJECTS anything that could corrupt the measurement
# --------------------------------------------------------------------------


def test_the_committed_label_set_is_exactly_the_operator_authored_pilot() -> None:
    labels = pilot.load_operator_labels()
    assert {label.case_id for label in labels} == EXPECTED_CASE_IDS
    assert len(labels) == 7
    for label in labels:
        assert label.correctness == EXPECTED_CORRECTNESS[label.case_id], (
            f"{label.case_id}: committed correctness {label.correctness!r} does not match "
            "the operator's verbatim label — never flip a label; if the operator re-labels, "
            "update this pin in the same reviewed diff"
        )
        # Provenance fields must be present and non-empty on every label.
        assert label.reviewer.strip(), label.case_id
        assert label.source.strip(), label.case_id
        assert label.error_if_any.strip(), label.case_id
        assert label.note.strip(), label.case_id


def test_rejects_a_correctness_value_outside_the_enum(tmp_path: Path) -> None:
    rows = _committed_rows()
    rows[0]["correctness"] = "mostly-right"
    with pytest.raises(ValueError, match="mostly-right"):
        pilot.load_operator_labels(_write(tmp_path, rows))


def test_rejects_an_empty_label_set_instead_of_reporting_vacuous_agreement(
    tmp_path: Path,
) -> None:
    """An unlabeled pilot must never silently report 100% over nothing."""
    with pytest.raises(ValueError, match="empty"):
        pilot.load_operator_labels(_write(tmp_path, []))


def test_rejects_a_label_whose_case_id_has_no_golden_case(tmp_path: Path) -> None:
    rows = _committed_rows()
    rows[0]["case_id"] = "no-such-golden-case"
    with pytest.raises(ValueError, match="no-such-golden-case"):
        pilot.load_operator_labels(_write(tmp_path, rows))


def test_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    rows = _committed_rows()
    rows.append(dict(rows[0]))
    with pytest.raises(ValueError, match="duplicate"):
        pilot.load_operator_labels(_write(tmp_path, rows))


def test_rejects_a_label_missing_a_provenance_field(tmp_path: Path) -> None:
    rows = _committed_rows()
    del rows[0]["reviewer"]
    # ValueError ONLY — an incidental KeyError from a later line must not mask
    # removal of the loader's own provenance check (review finding EA-F1).
    with pytest.raises(ValueError, match="reviewer"):
        pilot.load_operator_labels(_write(tmp_path, rows))


@pytest.mark.parametrize("bad_value", ["", "   ", None], ids=["empty", "blank", "null"])
def test_rejects_a_blank_or_null_provenance_field(tmp_path: Path, bad_value: Any) -> None:
    """JSON null must not slip through as the string 'None' (review finding IC-F2)."""
    rows = _committed_rows()
    rows[0]["reviewer"] = bad_value
    with pytest.raises(ValueError, match="reviewer"):
        pilot.load_operator_labels(_write(tmp_path, rows))


# --------------------------------------------------------------------------
# Agreement is computed through the real engine, never read from anywhere
# --------------------------------------------------------------------------


def test_agreement_is_derived_by_running_the_real_engine() -> None:
    result = pilot.compute_pilot()
    assert result.n == 7
    assert 0 <= result.agreed <= result.n
    for row in result.rows:
        # Every engine verdict must come from the engine's own vocabulary…
        assert row.engine_verdict in ("faithful", "unfaithful", "partial")
        # …and agreement must be exactly the pre-declared identity mapping.
        assert row.agree is (row.engine_verdict == row.operator_correctness)
    assert result.agreed == sum(1 for row in result.rows if row.agree)


def test_the_engine_verdict_is_recomputed_not_copied_from_the_fixture() -> None:
    """The harness must go through ``evaluate_layer_a``, not the fixture label.

    The golden gate separately guarantees engine == fixture label, so the
    VALUES coincide — this pins the mechanism instead: a perturbed engine
    (monkeypatched here) must change the computed agreement, which is only
    possible if the harness actually calls the engine.
    """
    result = pilot.compute_pilot(
        evaluate=lambda **_kwargs: _FixedVerdict("unfaithful"),
    )
    # Under an engine that says 'unfaithful' for everything, only the one
    # operator-labeled 'unfaithful' case can agree.
    assert result.agreed == 1
    assert result.n == 7


def test_agreement_consults_the_operator_label_not_the_fixture_label(tmp_path: Path) -> None:
    """The comparison target must be the OPERATOR's label (review finding CT-F2).

    On the committed set the operator labels coincide with the golden fixtures'
    own ``label`` fields, so a harness bug comparing engine-vs-fixture would
    stay green everywhere else. Flipping ONE operator label in a throwaway copy
    must drop agreement to 6/7 — only possible if the harness scores against
    the operator file it was given.
    """
    rows = _committed_rows()
    flipped = next(row for row in rows if row["case_id"] == "grounded-consensus")
    flipped["correctness"] = "partial"  # test-only perturbation, never committed
    result = pilot.compute_pilot(labels_path=_write(tmp_path, rows))
    assert result.n == 7
    assert result.agreed == 6
    (disagreement,) = [row for row in result.rows if not row.agree]
    assert disagreement.case_id == "grounded-consensus"
    assert disagreement.operator_correctness == "partial"


class _FixedVerdict:
    def __init__(self, label: str) -> None:
        self.faithfulness_label = label


# --------------------------------------------------------------------------
# The pilot doc cannot drift from the measurement
# --------------------------------------------------------------------------


def test_the_pilot_doc_records_exactly_the_computed_verdicts() -> None:
    text = PILOT_DOC.read_text(encoding="utf-8")
    result = pilot.compute_pilot()
    for row in result.rows:
        expected = (
            f"| `{row.case_id}` | {row.engine_verdict} | "
            f"{row.operator_correctness} | {'yes' if row.agree else 'NO'} |"
        )
        assert expected in text, (
            f"docs/metrics/accuracy-pilot.md has drifted from the measurement for "
            f"{row.case_id!r}: expected row {expected!r}. Re-derive the table from "
            "the harness; never edit a label or the mapping to force agreement."
        )
    assert f"**{result.agreed} / {result.n}**" in text, (
        f"the doc must record the computed aggregate {result.agreed}/{result.n} "
        "verbatim — whatever it is"
    )


def test_the_pilot_doc_carries_its_scoping_caveats_on_its_face() -> None:
    """The number and its limits must live on the same page (integrity spine)."""
    # Normalise the doc's 80-column line wrapping so a phrase can't dodge the
    # check by wrapping across a newline.
    text = " ".join(PILOT_DOC.read_text(encoding="utf-8").split())
    for required in (
        "n = 7",
        "human-labeled",
        "hand-authored golden fixtures",
        "pilot — not a population estimate",
        "do not extrapolate",
    ):
        assert required in text, f"missing scoping caveat {required!r} in accuracy-pilot.md"
    # The pilot must explicitly disclaim being the Part 2 measurement.
    assert "Part 2" in text and "em-dash" in text


def test_the_quality_ledger_part_2_stays_unmeasured() -> None:
    """The pilot must never leak into the ledger's measured-quality table.

    Part 2 requires real captured four-model runs with human labels; the pilot
    runs on hand-authored fixtures. Every S-row cell in Part 2 must still be an
    em-dash (optionally annotated, e.g. ``— (pending S4)``).
    """
    text = QUALITY_LEDGER.read_text(encoding="utf-8")
    part2 = text.split("## Part 2")[1].split("### Why")[0]
    slice_rows = [
        line
        for line in part2.splitlines()
        if line.startswith("| S") and line.split("|")[1].strip() in ("S1", "S2", "S3", "S4")
    ]
    assert len(slice_rows) == 4, f"expected the 4 S-rows in Part 2, found {len(slice_rows)}"
    for line in slice_rows:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")][1:]
        assert cells, line
        for cell in cells:
            assert cell == "—" or cell.startswith("— ("), (
                f"quality-ledger Part 2 carries a measured-looking value {cell!r} in "
                f"{line!r}; the pilot must never populate Part 2"
            )


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _committed_rows() -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = json.loads(pilot.OPERATOR_LABELS_PATH.read_text(encoding="utf-8"))
    return raw


def _write(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    path = tmp_path / "operator_labels.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path
