"""The findings ledger must not lie about what is built (Phase-0 self-check).

`docs/analysis/R2-plan-review-findings.md` is the durable per-item status record
the reconciling session verifies Phase-0 completion against
(`PHASE-0-BUILD-PROMPT.md` §0/§4.4). Its whole value is that it is *below the
line*: if it drifts from the repo, the reconciler falls back to chat text — the
exact above-the-line evidence the ledger exists to replace.

Prose cannot enforce that. These tests do, mechanically:

1. every row uses a status token from the ledger's own legend;
2. an item whose Phase-0 artifacts all exist on disk (and are non-empty) MUST
   read ``DONE`` — a built-and-proven gate may not still read ``BUILD``/``DOC-FIX``;
3. every ``DONE`` row must cite a proof pointer *registered for that item* and
   pointing at a non-empty file — so ``DONE`` cannot be claimed without an
   artifact of its own ("done = artifact + proven");
4. every still-open ``BUILD`` row must name the slice that owns it, so the
   out-of-scope confirmation the brief demands is unambiguous;
5. a row that quotes a MEASUREMENT must quote today's measurement — the
   numbers are re-derived from the frozen corpus through the real engine.

Rule 5 exists because rules 1-4 read status tokens and proof pointers only.
Measured: the OC-2 row kept asserting the pre-DEBT-011 grounding separation
in the present tense ("1.000 vs 0.038") for a full commit after the same
slice re-measured it to 0.850 vs 0.059 elsewhere in the repo, and every gate
stayed green.

Rule 3 originally accepted *any* existing path, which made it decorative: a
session that built nothing could rewrite all 27 status cells to
``DONE — `pyproject.toml``` and stay green (measured: 0 failures on that
mutant). It is now keyed to the item — the cited path must be one of the paths
registered for that row below, and it must be non-empty — and the build
artifacts are additionally checked to be *new since the S1 baseline*
(:data:`S1_BASELINE_SHA`), so the registry cannot be pointed at pre-existing
files either.

Rules 2, 3 and 4 have each been RED on a real defect or an injected mutant.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = REPO_ROOT / "docs" / "analysis" / "R2-plan-review-findings.md"

#: The commit Phase 0 started from (end of S1). Anything listed in
#: :data:`PHASE0_ARTIFACTS` must be absent there — otherwise the "artifact
#: proves the item" claim is being made with a file that predates the work.
S1_BASELINE_SHA = "5ccd6f9"

#: The legend at the top of the ledger. Any other token is a typo or an
#: invented status nobody can act on.
ALLOWED_STATUS_TOKENS = {
    "OPEN",
    "DECIDED",
    "DOC-FIX",
    "BUILD",
    "DONE",
    "WONTFIX",
}

#: Item ID -> the artifact(s) whose existence proves the item was built.
#: Only files *created* by Phase 0 are listed: a pre-existing file proves
#: nothing about the item. When every path exists, the row must read DONE.
PHASE0_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "EN-2": (
        "scripts/validate_fr_completeness.py",
        "tests/test_fr_completeness_gate.py",
    ),
    "OC-4": ("docs/metrics/quality-ledger.md",),
    "RB-1": ("docs/metrics/diff-cover.md",),
    "RB-2": ("tests/perf/test_workflow_latency_percentiles.py",),
    "RB-3": (
        "tests/test_store_lifecycle.py",
        "tests/test_store_concurrency.py",
        "docs/adr/0002-sqlite-single-writer-ceiling.md",
    ),
    "RB-7": ("docs/metrics/mutation-baseline.md",),
    "P0-F": ("tests/contract/test_api_contract_schemathesis.py",),
    "P0-H": ("docs/analysis/09-enforcement-hooks.md",),
}

#: Item ID -> the artifact(s) whose existence proves an **R2-S2** item was
#: built. Same contract as :data:`PHASE0_ARTIFACTS` (and the same
#: absent-at-``S1_BASELINE_SHA`` check applies): only files *created* by the
#: slice are listed, because a pre-existing file proves nothing about the item.
#: Kept as its own mapping so a reader can tell which phase paid for which row.
S2_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "OC-1": (
        "tests/evals/test_output_correctness_gate.py",
        "tests/evals/corpus/loader.py",
    ),
    "OC-2": (
        "src/product_app/evaluation.py",
        "tests/evals/test_trust_calibration.py",
    ),
    "EN-7": ("tests/test_doc_gate_consistency.py",),
}

#: Item ID -> the file(s) a *doc-fix* item legitimately proves itself with.
#: These are edits to pre-existing docs, so existence proves nothing on its own
#: — their job here is to key the proof pointer to the item, so a row cannot
#: borrow some unrelated file's existence. Adding a path here is a claim that
#: the item's fix actually landed in that file; keep it specific, never add a
#: catch-all like ``pyproject.toml``.
DOC_FIX_PROOFS: dict[str, tuple[str, ...]] = {
    "EN-1": ("docs/DAY-ONE-PROMPT.md", "docs/R2-comprehensive-plan.md"),
    "EN-3": ("docs/DAY-ONE-PROMPT.md", "docs/R2-comprehensive-plan.md"),
    "EN-4": ("docs/DAY-ONE-PROMPT.md",),
    "EN-5": ("docs/R2-comprehensive-plan.md", "docs/metrics/quality-ledger.md"),
    "EN-6": (
        "docs/analysis/03-enforcement-machinery.md",
        ".github/workflows/e2e.yml",
    ),
    "RB-8": ("docs/DAY-ONE-PROMPT.md", "tests/contract/test_api_contract_schemathesis.py"),
    "FS-1": ("docs/R2-comprehensive-plan.md",),
    "FS-2": ("docs/DAY-ONE-PROMPT.md",),
    "FS-3": ("docs/R2-comprehensive-plan.md",),
    "FS-4": ("docs/00-factory-console.md", "docs/session-handoff.md"),
    "FS-5": (
        "R2-S2-S4-ULTRACODE-PROMPT.md",
        "docs/R2-comprehensive-plan.md",
        "tests/test_ultracode_prompt_enforcement_contract.py",
        "tests/test_findings_ledger_fs5_status.py",
    ),
    "FS-6": ("docs/DAY-ONE-PROMPT.md", "docs/R2-comprehensive-plan.md"),
    "FS-7": ("docs/DAY-ONE-PROMPT.md",),
    "FS-8": ("docs/DAY-ONE-PROMPT.md",),
    "FS-9": ("docs/R2-comprehensive-plan.md",),
    "FS-10": ("docs/DAY-ONE-PROMPT.md",),
    "CF-1": ("docs/day-one-quality-standard.md",),
    "CF-2": ("docs/DAY-ONE-PROMPT.md",),
    "CF-3": ("docs/DAY-ONE-PROMPT.md",),
}

#: A path-shaped backtick span in a status cell, e.g. `tests/perf/x.py`.
_PROOF_POINTER_RE = re.compile(r"`([^`]+?\.(?:py|md|toml|json|ya?ml))`")
_ROW_ID_RE = re.compile(r"^[A-Z][A-Z0-9]-[0-9A-Z]+$")
_SLICE_RE = re.compile(r"\bS[234]\b")


def _registered_proofs(item: str) -> tuple[str, ...]:
    """Every path that may stand as proof for ``item`` (build + doc-fix)."""
    merged = (
        PHASE0_ARTIFACTS.get(item, ()) + S2_ARTIFACTS.get(item, ()) + DOC_FIX_PROOFS.get(item, ())
    )
    return tuple(dict.fromkeys(merged))


def _is_real_artifact(rel_path: str) -> bool:
    """Exists *and* has content — ``touch docs/metrics/x.md`` proves nothing."""
    path = REPO_ROOT / rel_path
    return path.is_file() and path.stat().st_size > 0


def _rows() -> dict[str, str]:
    """Ledger item ID -> its Status cell (the last column)."""
    rows: dict[str, str] = {}
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or not _ROW_ID_RE.match(cells[0]):
            continue
        rows[cells[0]] = cells[-1]
    return rows


@pytest.fixture(scope="module")
def ledger_rows() -> dict[str, str]:
    rows = _rows()
    assert rows, f"no parsable item rows in {LEDGER_PATH}"
    return rows


def test_every_status_uses_a_legend_token(ledger_rows: dict[str, str]) -> None:
    """A status nobody defined is a status nobody can act on."""
    bad = {
        item: status
        for item, status in ledger_rows.items()
        if not any(token in status for token in ALLOWED_STATUS_TOKENS)
    }
    assert not bad, f"status cells with no legend token: {bad}"


@pytest.mark.parametrize("item", sorted(PHASE0_ARTIFACTS | S2_ARTIFACTS))
def test_built_items_read_done(item: str, ledger_rows: dict[str, str]) -> None:
    """If the artifacts exist, the ledger may not still say BUILD/DOC-FIX."""
    assert item in ledger_rows, f"{item} has no row in the ledger"
    built = PHASE0_ARTIFACTS.get(item, ()) + S2_ARTIFACTS.get(item, ())
    missing = [p for p in built if not _is_real_artifact(p)]
    if missing:
        pytest.skip(f"{item} artifacts not built yet: {missing}")
    status = ledger_rows[item]
    assert "DONE" in status, (
        f"{item}: every artifact exists ({', '.join(built)}) but the ledger still reads {status!r}"
    )


def test_every_done_row_registers_its_own_proof_paths(
    ledger_rows: dict[str, str],
) -> None:
    """A row may not go ``DONE`` until someone records what would prove it.

    Without this, rule 3 can be satisfied by inventing a new DONE row and
    citing any file in the repo — the registry is what ties status to work.
    """
    unregistered = sorted(
        item
        for item, status in ledger_rows.items()
        if "DONE" in status and not _registered_proofs(item)
    )
    assert not unregistered, (
        "DONE rows with no registered proof path — add the item's real "
        f"artifact(s) to PHASE0_ARTIFACTS/DOC_FIX_PROOFS: {unregistered}"
    )


def test_done_rows_cite_an_existing_proof_pointer(
    ledger_rows: dict[str, str],
) -> None:
    """``DONE`` without a real artifact *of its own* is the claim this replaces.

    The pointer must be registered for **this** item and resolve to a non-empty
    file; citing an unrelated pre-existing path (``pyproject.toml``) or an empty
    placeholder is exactly the gaming this ledger exists to prevent.
    """
    offenders: dict[str, str] = {}
    for item, status in ledger_rows.items():
        if "DONE" not in status:
            continue
        registered = set(_registered_proofs(item))
        if not registered:
            continue  # reported by the registration test above
        cited = [p for p in _PROOF_POINTER_RE.findall(status) if p in registered]
        if not any(_is_real_artifact(p) for p in cited):
            offenders[item] = status
    assert not offenders, (
        f"DONE rows citing no registered, non-empty proof path for their own item: {offenders}"
    )


@pytest.mark.parametrize("item", sorted(PHASE0_ARTIFACTS | S2_ARTIFACTS))
def test_phase0_artifacts_are_new_since_the_s1_baseline(item: str) -> None:
    """The registry may only claim files the slice actually created.

    Covers the Phase-0 and the R2-S2 registries alike: a row may not prove
    itself with a file that already existed before the work it claims credit
    for. ``git cat-file -e`` on the baseline tree is the cheap, deterministic
    form of "added since ``S1_BASELINE_SHA``" — the artifacts are still
    untracked while a slice runs, so ``git log --diff-filter=A`` cannot see
    them yet.
    """
    preexisting = []
    for rel_path in PHASE0_ARTIFACTS.get(item, ()) + S2_ARTIFACTS.get(item, ()):
        probe = subprocess.run(
            ["git", "cat-file", "-e", f"{S1_BASELINE_SHA}:{rel_path}"],
            cwd=REPO_ROOT,
            capture_output=True,
        )
        if probe.returncode == 0:
            preexisting.append(rel_path)
    assert not preexisting, (
        f"{item}: these already existed at {S1_BASELINE_SHA}, so they prove "
        f"nothing about the work the row claims credit for: {preexisting}"
    )


def test_open_build_rows_name_their_slice(ledger_rows: dict[str, str]) -> None:
    """An unbuilt BUILD item must say which slice owns it (S2/S3/S4)."""
    offenders = {
        item: status
        for item, status in ledger_rows.items()
        if "BUILD" in status and "DONE" not in status and not _SLICE_RE.search(status)
    }
    assert not offenders, f"BUILD rows with no owning slice: {offenders}"


# ---------------------------------------------------------------------------
# Rule 5 — a quoted MEASUREMENT must be the measurement
# ---------------------------------------------------------------------------

#: Item -> the corpus case ids whose ``citation_marker_grounding`` its status
#: cell quotes. Rules 1-4 check status TOKENS and proof-pointer existence;
#: none of them reads numeric prose, so a row could (and did) keep asserting
#: a superseded measurement in the present tense while every gate stayed
#: green. Measured defect: OC-2 quoted "1.000 vs 0.038" — the pre-DEBT-011
#: endpoints — for a full commit after the same slice re-measured them to
#: 0.850 vs 0.059 in ``docs/metrics/quality-ledger.md`` and wrote "the old
#: comment's 1.0000 / 0.0385 are dead numbers and must not be quoted again"
#: into ``src/product_app/evaluation.py``.
GROUNDING_CLAIMS: dict[str, tuple[str, ...]] = {
    "OC-2": ("faithful-consensus", "fluent-unfaithful"),
}


def _measured_grounding(case_id: str) -> float:
    """Re-derive one corpus case's grounding through the real engine."""
    import importlib.util
    import sys

    loader_path = REPO_ROOT / "tests" / "evals" / "corpus" / "loader.py"
    spec = importlib.util.spec_from_file_location("ledger_corpus_loader", loader_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ledger_corpus_loader"] = module
    spec.loader.exec_module(module)

    from product_app.evaluation import evaluate_layer_a

    case = module.load_case(case_id)
    grounding = evaluate_layer_a(
        initial_answers=case.initial_answers,
        final_synthesis=case.final_synthesis,
        agreement=case.agreement,
    ).signals.citation_marker_grounding
    assert grounding is not None, case_id
    return grounding


@pytest.mark.parametrize("item", sorted(GROUNDING_CLAIMS))
def test_quoted_grounding_separations_are_the_measured_ones(
    item: str, ledger_rows: dict[str, str]
) -> None:
    """A row that quotes a separation must quote TODAY's separation.

    The engine is the oracle, not the prose: the expected strings are
    re-derived from the frozen corpus on every run, so the day the corpus or
    the grounding rules move, this row goes red instead of going stale.
    """
    status = ledger_rows[item]
    measured = [_measured_grounding(case_id) for case_id in GROUNDING_CLAIMS[item]]
    quoted = f"{measured[0]:.3f} vs {measured[1]:.3f}"
    assert quoted in status, (
        f"{item} quotes a grounding separation that is no longer the measured one; "
        f"the corpus now separates the pair {quoted}. Status cell: {status!r}"
    )


# ---------------------------------------------------------------------------
# Rule 6 — the DEBT register's proof pointers must exist (round 3)
# ---------------------------------------------------------------------------

DEBT_REGISTER_PATH = REPO_ROOT / "docs" / "63-technical-debt-register.md"

#: A backticked repo path in a register cell, with an optional ``::test``
#: suffix and optional trailing ``.py`` member chain. Only tokens containing
#: a ``/`` are treated as paths, so ``pyproject.toml [tool.mutmut]`` (a
#: section reference, not a file claim) is left alone.
_DEBT_PROOF_PATH_RE = re.compile(r"`([A-Za-z0-9_./-]+\.(?:py|md|toml|json|ya?ml|js|css|html))\b")

#: The row-ID shape used by ``docs/63`` (``DEBT-011``), which is not the
#: findings-ledger shape parsed above.
_DEBT_ROW_ID_RE = re.compile(r"^DEBT-\d+$")


def _debt_rows() -> dict[str, str]:
    """Debt ID -> the whole row text."""
    rows: dict[str, str] = {}
    for line in DEBT_REGISTER_PATH.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or not _DEBT_ROW_ID_RE.match(cells[0].strip("* ")):
            continue
        rows[cells[0].strip("* ")] = line
    return rows


def test_the_debt_register_cites_only_proof_pointers_that_exist() -> None:
    """``docs/63`` had NO existence gate on its Evidence/proof column.

    Measured (adversarial review round 3): rule 3 above reads only
    ``docs/analysis/R2-plan-review-findings.md``, ``tests/test_doc_gate_consistency.py``
    does not read ``docs/63`` at all, and the single gate that does
    (``test_the_debt_register_quotes_todays_separation_interval``) checks one
    numeric interval string. So a DEBT row could read RESOLVED/REPAID while
    citing a test module that does not exist — the exact "DONE without an
    artifact" gaming the R2 ledger gate was built to stop — with every gate
    green (repro: rewrite DEBT-011's sole INV proof pointer to
    ``tests/unit/test_totally_invented_does_not_exist.py``; measured 258
    passed).

    A resolved-debt row is where a reader goes to find out what was proved,
    so a pointer at a file that is not there is worse than none.
    """
    rows = _debt_rows()
    assert rows, f"no parsable debt rows in {DEBT_REGISTER_PATH}"

    missing: dict[str, list[str]] = {}
    for debt_id, row in rows.items():
        cited = [p for p in _DEBT_PROOF_PATH_RE.findall(row) if "/" in p]
        absent = sorted({p for p in cited if not _is_real_artifact(p)})
        if absent:
            missing[debt_id] = absent
    assert not missing, (
        "debt rows citing proof pointers that do not exist (or are empty). "
        "Fix the pointer or do the work; do not leave a closure argument "
        f"resting on a missing file: {missing}"
    )


def test_the_debt_register_proof_gate_sees_the_rows_it_claims_to() -> None:
    """Anti-vacuity for the gate above: it must actually parse real rows.

    A row-parsing bug would make the existence check pass by finding
    nothing, which is how this class of gate fails open.
    """
    rows = _debt_rows()
    assert len(rows) >= 12, f"only {len(rows)} debt rows parsed: {sorted(rows)}"
    cited = {p for row in rows.values() for p in _DEBT_PROOF_PATH_RE.findall(row) if "/" in p}
    assert len(cited) >= 10, f"only {len(cited)} proof paths found in the register: {cited}"
    assert any(p.startswith("tests/") for p in cited), (
        "no test module is cited anywhere in the register; the parse is wrong"
    )
