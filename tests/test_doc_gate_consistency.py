"""Docs must agree with the CI workflows and the enforced thresholds (ledger EN-7).

Why this file exists
--------------------
The existing consistency gates check *structure* — a DONE row cites a file, a
BUILD row names a slice — and are blind to two classes of prose drift that have
both already shipped on this repo and were caught by a human, not a test:

1. **Blocking/advisory drift.** A doc calls a gate "blocking" while its CI job
   carries ``continue-on-error: true`` (the perf-gate downgrade), or a doc still
   says a gate is waiting to be "flipped to blocking" long after it became hard.
2. **Numeric drift.** A threshold quoted in prose (coverage floor, changed-lines
   floor, mutation floor, perf budgets) disagrees with the value actually
   enforced in ``pyproject.toml`` / ``Makefile`` / the gate module — the stale
   mutmut ``96.5``/``90`` numbers survived a fully green suite this way.

Design constraints that are load-bearing here
---------------------------------------------
* **"Blocking == no continue-on-error" is false on this repo.** ``diff-cover``
  has no ``continue-on-error`` but is gated on ``if: github.event_name ==
  'pull_request'``, so a direct push to ``main`` is ungated. (``codex-review``
  used to be the standing example of the fourth status, VACUOUS — no
  ``continue-on-error`` yet always passing because its only real step was
  commented out — until it was removed in #166 for exactly that reason; the
  ``VACUOUS``/``_is_vacuous`` machinery below stays, since a future gate could
  regress into that same shape, but nothing in the current ``GATES`` registry
  exercises it.) Effective status is therefore a four-valued model
  (blocking / blocking-on-pull-requests-only / advisory / vacuous) and docs are
  asked to state the *qualified* truth. ``continue-on-error`` is read at BOTH
  levels: a flag on the step that does the gate's real work downgrades the gate
  just as surely as one on the job, while a flag on checkout/setup/artifact
  plumbing does not.
* **Never key off the bare word "blocking".** It appears in ~20 docs with
  nothing to do with CI (a non-blocking persistence AC, async blocking calls,
  high-stakes topic blocking). Every claim here is anchored to a gate/job
  identifier and read from a bounded window after that identifier, per the
  AGENTS.md rule "key off the matched token, never a whole-line substring".
* **All workflows, not just ci.yml** — ``docs/analysis/03-enforcement-machinery.md``
  makes a claim about ``e2e.yml``.
* Job names use an ASCII hyphen (``Mutation score (ADVISORY - non-blocking)``)
  while docs quote them with an em dash; dashes are normalised before matching.
* This module runs unconditionally: it reads only tracked files, never a build
  artifact that exists in one CI job.

``QUORUM_DOC_GATE_WORKFLOWS`` / ``QUORUM_DOC_GATE_DOCS`` override the workflow
directory and the doc corpus. They exist so the check can be proven RED against
a mutated *copy* of a workflow or doc tree without dirtying the working tree
(same idiom as ``QUORUM_FINDINGS_LEDGER_PATH`` in
``tests/test_findings_ledger_perf_numbers.py``).
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Only ``docs/`` is scanned. The root build prompts deliberately contain
#: counter-examples ("re-prove it BITES by running once with
#: ``--cov-fail-under=95`` -> must fail"), which are instructions, not claims.
DEFAULT_DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

BLOCKING = "blocking"
PR_ONLY = "blocking-on-pull-requests-only"
ADVISORY = "advisory"
VACUOUS = "vacuous (no executable step)"

#: Which claim words are honest for a given effective status.
_ALLOWED_CLAIM = {
    BLOCKING: {"blocking"},
    PR_ONLY: {"blocking"},  # qualification is enforced separately, see below
    ADVISORY: {"advisory"},
    VACUOUS: {"advisory"},
}

#: Statuses that are NOT plain "blocking" and must be recorded somewhere durable.
_QUALIFIED = {PR_ONLY, ADVISORY, VACUOUS}

MACHINERY_DOC = DEFAULT_DOCS_DIR / "analysis" / "03-enforcement-machinery.md"


def _docs_dir() -> Path:
    return Path(os.environ.get("QUORUM_DOC_GATE_DOCS", DEFAULT_DOCS_DIR))


def _workflow_dir() -> Path:
    return Path(os.environ.get("QUORUM_DOC_GATE_WORKFLOWS", DEFAULT_WORKFLOW_DIR))


def _display(path: Path) -> str:
    """Repo-relative when possible, absolute otherwise.

    The override env vars exist so this check can be proven RED against a
    mutated copy *outside* the working tree; a bare ``relative_to(REPO_ROOT)``
    at a reporting site raises ``ValueError`` there and destroys the very
    assertion message the RED proof needs to show.
    """
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _normalise(text: str) -> str:
    """Fold en/em/minus dashes to ASCII so quoted job names compare equal."""
    return text.replace("—", "-").replace("–", "-").replace("−", "-")


def _doc_lines() -> Iterator[tuple[Path, int, str]]:
    for path in sorted(_docs_dir().rglob("*.md")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            yield path, number, _normalise(line)


# --------------------------------------------------------------------------
# Part A — effective blocking status of the real workflow jobs
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Gate:
    """A CI gate, and how docs refer to it."""

    key: str
    workflow: str
    job: str
    #: Regexes (case-insensitive) that name this gate in prose. Anchors for
    #: every claim below — never the bare word "blocking".
    identifiers: tuple[str, ...]


GATES: tuple[Gate, ...] = (
    Gate("perf-gate", "ci.yml", "perf-gate", (r"perf-gate", r"Hermetic perf p50/p95")),
    Gate("api-contract", "ci.yml", "api-contract", (r"Schemathesis API contract",)),
    Gate("diff-cover", "ci.yml", "diff-cover", (r"Changed-lines coverage",)),
    Gate(
        "mutation-baseline",
        "ci.yml",
        "mutation-baseline",
        (r"Mutation score", r"mutation[- ]baseline"),
    ),
    Gate(
        "fr-completeness",
        "ci.yml",
        "fr-completeness",
        (r"FR traceability completeness", r"fr-completeness"),
    ),
    Gate(
        "e2e-invariants",
        "e2e.yml",
        "e2e",
        (r"rendering-invariants", r"visual-snapshots", r"real-integration-smoke"),
    ),
)


def _load_workflow(name: str) -> dict[str, Any]:
    text = (_workflow_dir() / name).read_text(encoding="utf-8")
    document = yaml.safe_load(text)
    assert isinstance(document, dict), f"{name} did not parse as a mapping"
    return document


def _job(gate: Gate) -> dict[str, Any]:
    jobs = _load_workflow(gate.workflow).get("jobs", {})
    assert gate.job in jobs, (
        f"workflow {gate.workflow} has no job {gate.job!r} — the EN-7 gate registry "
        "is stale, so its doc checks would pass vacuously. Update GATES."
    )
    job = jobs[gate.job]
    assert isinstance(job, dict)
    return job


def _is_vacuous(job: dict[str, Any]) -> bool:
    """True when nothing in the job can fail: no ``run``, no action but checkout."""
    for step in job.get("steps") or []:
        if "run" in step:
            return False
        uses = str(step.get("uses", ""))
        if uses and not uses.startswith("actions/checkout"):
            return False
    return True


#: Actions that are plumbing, never the gate's own assertion. A
#: ``continue-on-error`` on one of these does not stop the gate step from
#: failing the job, so it is not a downgrade — treating it as one would be a
#: false alarm that pushes docs into stating something untrue.
_INCIDENTAL_ACTION_PREFIXES = (
    "actions/checkout",
    "actions/setup-",
    "actions/cache",
    "actions/upload-artifact",
    "actions/download-artifact",
    "astral-sh/setup-uv",
)


def _is_gate_bearing(step: dict[str, Any]) -> bool:
    """True when this step can actually fail the gate.

    A job's conclusion is the AND of its steps that are NOT
    ``continue-on-error``. Gate-bearing means the step runs repo commands
    (``run:``) or a non-plumbing action — i.e. it is where the gate's check
    actually happens.
    """
    if "run" in step:
        return True
    uses = str(step.get("uses", ""))
    return bool(uses) and not uses.startswith(_INCIDENTAL_ACTION_PREFIXES)


def _has_step_level_downgrade(job: dict[str, Any]) -> bool:
    """A gate-bearing step marked ``continue-on-error`` cannot fail the job.

    Mirrors :func:`test_e2e_workflow_has_no_effective_continue_on_error`,
    which already knows step level matters: without this, moving the flag
    from the job onto its ``make …`` step evades the whole EN-7 gate while
    every doc still calls it blocking.
    """
    return any(
        step.get("continue-on-error") is True
        for step in (job.get("steps") or [])
        if _is_gate_bearing(step)
    )


def _effective_status(job: dict[str, Any]) -> str:
    if job.get("continue-on-error") is True:
        return ADVISORY
    if _has_step_level_downgrade(job):
        return ADVISORY
    if _is_vacuous(job):
        return VACUOUS
    if "pull_request" in str(job.get("if", "")):
        return PR_ONLY
    return BLOCKING


#: A status word in prose. ``non-blocking`` must win over ``blocking``.
#: #141: the verbs "blocks"/"blocked" carry the same claim as the adjective
#: "blocking" ("Since #130 the job blocks" passed silently before this).
_STATUS_RE = re.compile(
    r"\bnon-blocking\b|\bblocking\b|\bblocks\b|\bblocked\b|\badvisory\b", re.IGNORECASE
)

#: Matched words that assert BLOCKING. Anything else `_STATUS_RE` matches
#: (``advisory``, ``non-blocking``) asserts advisory. #141: a naive fix that
#: only widened `_STATUS_RE` without also widening this set would classify
#: "blocks"/"blocked" as advisory, since neither literally equals "blocking".
_BLOCKING_WORDS = {"blocking", "blocks", "blocked"}

#: Context immediately before a status word that makes it hypothetical, negated
#: or historical ("the gate ran BLOCKING", "NOT blocking", "then flip
#: advisory->blocking"). Such wording is not a present-tense claim.
_NOT_A_CLAIM_RE = re.compile(
    r"(?:\bnot\b|\bnever\b|\bno longer\b|\bran\b|\bwas\b|\bwere\b|\buntil\b|\bonce\b"
    r"|\bbefore\b|\bthen\b|\bflip\w*\b|\bconvert\w*\b|\bpromot\w*\b|\bdowngrad\w*\b"
    r"|\brestor\w*\b|->)[^.]{0,25}$",
    re.IGNORECASE,
)

#: A claim that a gate is still *waiting* to become blocking.
_PENDING_PROMOTION_RE = re.compile(
    r"(?:flip\w*|convert\w*|promot\w*|re-promot\w*)\b[^.|]{0,40}?\bblocking\b",
    re.IGNORECASE,
)

#: How far after the gate identifier a status word still describes that gate.
_WINDOW = 90


def _window(line: str, end: int) -> str:
    """Text after an identifier that still talks about it.

    Bounded by length and by a clause break: ``changed-lines coverage
    (`diff-cover` >=95%), advisory mutation baseline`` must not attribute
    "advisory" to diff-cover.

    #141: a comma immediately after the identifier's own closing markdown
    punctuation — the idiomatic ``(`gate`, blocking)`` shape — is part of
    that same parenthetical, not a clause break, so it must not end the
    window early. Confirmed by execution: this hid 7 real "blocking" claims.
    Skip past a short run of closing punctuation first, and only exempt the
    comma immediately following it; any LATER comma in the window still
    cuts, which is what protects the diff-cover list-item case above.
    """
    chunk = line[end : end + _WINDOW]
    i = 0
    while i < len(chunk) and chunk[i] in "`)]\"'":
        i += 1
    comma_search_start = i + 1 if i < len(chunk) and chunk[i] == "," else 0
    for boundary, start in ((",", comma_search_start), (";", 0), (". ", 0)):
        cut = chunk.find(boundary, start)
        if cut != -1:
            chunk = chunk[:cut]
    return chunk


def _claims(gate: Gate, line: str) -> list[str]:
    """Present-tense status claims about ``gate`` on this line."""
    found: list[str] = []
    for identifier in gate.identifiers:
        for anchor in re.finditer(identifier, line, re.IGNORECASE):
            chunk = _window(line, anchor.end())
            for status in _STATUS_RE.finditer(chunk):
                if _NOT_A_CLAIM_RE.search(chunk[: status.start()]):
                    continue
                word = status.group(0).lower()
                found.append("blocking" if word in _BLOCKING_WORDS else "advisory")
    return found


@pytest.fixture(scope="module")
def effective_statuses() -> dict[str, str]:
    return {gate.key: _effective_status(_job(gate)) for gate in GATES}


def test_gate_registry_resolves_to_real_jobs() -> None:
    """Every registered gate must exist, or its doc checks pass vacuously."""
    for gate in GATES:
        assert _job(gate) is not None


def test_doc_status_claims_match_the_workflows(effective_statuses: dict[str, str]) -> None:
    """No doc may call an advisory gate blocking, or a blocking gate advisory."""
    problems: list[str] = []
    for path, number, line in _doc_lines():
        for gate in GATES:
            status = effective_statuses[gate.key]
            for claim in _claims(gate, line):
                if claim not in _ALLOWED_CLAIM[status]:
                    problems.append(
                        f"{_display(path)}:{number} calls the {gate.key!r} "
                        f"gate {claim!r}, but its {gate.workflow} job is effectively "
                        f"{status!r}: {line.strip()[:160]}"
                    )
    assert not problems, "doc status claims contradict the workflows:\n" + "\n".join(problems)


def test_no_doc_still_waits_to_flip_an_already_blocking_gate(
    effective_statuses: dict[str, str],
) -> None:
    """The other direction: "flip to blocking on fix" after the flip happened."""
    problems: list[str] = []
    for path, number, line in _doc_lines():
        for gate in GATES:
            if effective_statuses[gate.key] not in {BLOCKING, PR_ONLY}:
                continue
            for identifier in gate.identifiers:
                for anchor in re.finditer(identifier, line, re.IGNORECASE):
                    tail = line[anchor.end() : anchor.end() + 140]
                    if _PENDING_PROMOTION_RE.search(tail):
                        problems.append(
                            f"{_display(path)}:{number} still describes "
                            f"{gate.key!r} as pending a flip to blocking, but its "
                            f"{gate.workflow} job already blocks "
                            f"({effective_statuses[gate.key]}): {line.strip()[:160]}"
                        )
    assert not problems, "stale pending-promotion claims:\n" + "\n".join(problems)


def test_qualified_gates_are_recorded_in_the_machinery_doc(
    effective_statuses: dict[str, str],
) -> None:
    """A gate that does not simply block must have that qualification written down."""
    text = _normalise(MACHINERY_DOC.read_text(encoding="utf-8"))
    for gate in GATES:
        status = effective_statuses[gate.key]
        if status not in _QUALIFIED:
            continue
        row = [line for line in text.splitlines() if gate.job in line and status in line]
        assert row, (
            f"the {gate.key!r} job is effectively {status!r}, but "
            f"{_display(MACHINERY_DOC)} has no line recording that. "
            "A qualified gate that is documented nowhere reads as a hard gate."
        )


def test_e2e_workflow_has_no_effective_continue_on_error() -> None:
    """Mechanises the prose claim that the e2e invariants are hard gates.

    ``docs/analysis/03-enforcement-machinery.md`` asserts ``continue-on-error``
    appears nowhere in ``e2e.yml`` except in comments describing its removal.
    Parsed YAML drops comments, so this reads the real, effective setting.
    """
    for name, job in _load_workflow("e2e.yml").get("jobs", {}).items():
        assert job.get("continue-on-error") is not True, (
            f"e2e.yml job {name!r} is continue-on-error, but "
            "docs/analysis/03-enforcement-machinery.md calls the invariants BLOCKING"
        )
        for step in job.get("steps") or []:
            assert step.get("continue-on-error") is not True, (
                f"e2e.yml step {step.get('name', '?')!r} is continue-on-error, but "
                "docs/analysis/03-enforcement-machinery.md calls the invariants BLOCKING"
            )


# --------------------------------------------------------------------------
# Part A2 — #141: the comma-shaped hole in _window(), and the missing verb
# --------------------------------------------------------------------------
#
# Found by adversarial review of PR #140: 7 real doc claims shaped like
# ``(`make mutation-baseline`, blocking on pull requests)`` were invisible to
# this gate, because `_window()` cut at the FIRST comma unconditionally — and
# that comma sits right after the identifier's own closing backtick in the
# idiomatic doc form. Confirmed by execution:
#
#     "(`make mutation-baseline`, blocking on pull requests)"   -> []
#     "the mutation-baseline gate is blocking on pull requests" -> ['blocking']
#
# A second, independent cause: `_STATUS_RE` matched the adjective "blocking"
# but not the verb "blocks", so "Since #130 the job blocks" also passed
# silently.


def _gate(key: str) -> Gate:
    return next(g for g in GATES if g.key == key)


def test_a_comma_right_after_the_identifier_does_not_hide_the_status() -> None:
    """The exact string from the issue that shipped 7 missed claims.

    Turns red if: `_window()` reverts to cutting at the first comma
    unconditionally.
    """
    line = "(`make mutation-baseline`, blocking on pull requests)"
    assert _claims(_gate("mutation-baseline"), line) == ["blocking"], (
        "a comma immediately after the gate identifier's closing backtick "
        f"hid a real blocking claim: {_window(line, line.index('baseline`') + len('baseline'))!r}"
    )


def test_the_same_claim_written_without_the_comma_is_still_caught() -> None:
    """Positive partner: the un-mangled phrasing must keep working exactly as
    before — this is the shape the original (buggy) window already caught.
    """
    line = "the mutation-baseline gate is blocking on pull requests"
    assert _claims(_gate("mutation-baseline"), line) == ["blocking"]


def test_the_comma_rule_still_stops_a_status_leaking_across_a_list_item() -> None:
    """The property the first-comma cut existed to protect, restated as its
    own test so widening the window cannot silently lose it: a LATER,
    unrelated status in the same line must not attach to an earlier gate.

    Turns red if: the comma-skip is widened to skip every comma, not just
    one immediately following closing markdown punctuation.
    """
    line = "changed-lines coverage (`diff-cover` >=95%), advisory mutation baseline"
    assert _claims(_gate("diff-cover"), line) == [], (
        "widening the window let a later item's status attach to diff-cover, "
        "which the comma-cut exists to prevent"
    )


def test_the_verb_blocks_is_recognised_same_as_the_adjective_blocking() -> None:
    """#141's second cause: "Since #130 the job blocks" passed silently
    because `_STATUS_RE` only matched the adjective, not the verb.

    Turns red if: `blocks`/`blocked` are removed from `_STATUS_RE`, or the
    classification logic maps them to "advisory" instead of "blocking"
    (a real risk of a naive fix: `_claims` used to classify anything whose
    matched text was not the literal string "blocking" as "advisory").
    """
    line = "Since #130 the mutation-baseline job blocks a below-threshold PR."
    assert _claims(_gate("mutation-baseline"), line) == ["blocking"]


def test_the_verb_blocked_past_tense_is_also_recognised() -> None:
    line = "The mutation-baseline gate blocked this PR until the score improved."
    assert _claims(_gate("mutation-baseline"), line) == ["blocking"]


# --------------------------------------------------------------------------
# Part B — numbers quoted in prose vs the numbers actually enforced
# --------------------------------------------------------------------------

PERF_GATE_PATH = REPO_ROOT / "tests" / "perf" / "test_workflow_latency_percentiles.py"


def _single(pattern: str, path: Path, *, label: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, f"could not parse {label} out of {_display(path)} ({pattern})"
    return match.group(1)


def _enforced_numbers() -> dict[str, tuple[str, ...]]:
    """The live values, parsed from the files that actually enforce them."""
    return {
        "coverage floor": (
            _single(
                r"--cov-fail-under=(\d+)", REPO_ROOT / "pyproject.toml", label="coverage floor"
            ),
        ),
        "changed-lines floor": (
            _single(
                r"^DIFF_COVER_MIN \?= (\d+)", REPO_ROOT / "Makefile", label="changed-lines floor"
            ),
        ),
        "mutation floor": (
            _single(
                r"^MUTATION_MIN_SCORE \?= (\d+)", REPO_ROOT / "Makefile", label="mutation floor"
            ),
        ),
        "perf budgets": tuple(
            _single(rf"^{name} = ([\d.]+)", PERF_GATE_PATH, label=name).rstrip("0").rstrip(".")
            for name in (
                "SEQUENTIAL_P50_BUDGET_MS",
                "SEQUENTIAL_P95_BUDGET_MS",
                "CONCURRENT_P95_BUDGET_MS",
            )
        ),
    }


#: Prose forms that restate an enforced number, per threshold. Each pattern's
#: capture groups must equal the live value(s) in order.
_QUOTED: dict[str, tuple[str, ...]] = {
    "coverage floor": (r"--cov-fail-under=(\d+)", r"[Cc]overage floor\D{0,20}?(\d{2})\b"),
    "changed-lines floor": (
        r"diff-cover[^\n]{0,40}?--fail-under=(\d+)",
        r"(?:changed-lines coverage|diff-cover)[^\n]{0,30}?[≥>]=?\s*(\d+)\s*%",
    ),
    "mutation floor": (r"MUTATION_MIN_SCORE\s*\??=\s*(\d+)",),
    "perf budgets": (r"(\d+)/(\d+)/(\d+)\s*ms",),
}


def test_prose_thresholds_match_the_enforced_values() -> None:
    """Every threshold a doc quotes must be the one the repo actually enforces."""
    enforced = _enforced_numbers()
    problems: list[str] = []
    for path, number, line in _doc_lines():
        for label, patterns in _QUOTED.items():
            for pattern in patterns:
                for match in re.finditer(pattern, line):
                    quoted = tuple(match.groups())
                    if quoted != enforced[label]:
                        problems.append(
                            f"{_display(path)}:{number} quotes {label} as "
                            f"{'/'.join(quoted)} but the enforced value is "
                            f"{'/'.join(enforced[label])}: {line.strip()[:160]}"
                        )
    assert not problems, "prose thresholds contradict the enforced values:\n" + "\n".join(problems)


# --------------------------------------------------------------------------
# Part C — the gate's own escape hatches, exercised as documented
# --------------------------------------------------------------------------


def _mutated_workflows(tmp_path: Path, mutate: Any) -> Path:
    """A copy of the real workflow dir with ``mutate`` applied to ci.yml.

    Never touches ``.github/workflows``: the copy lives under ``tmp_path``,
    which is outside the repo, exactly as the module docstring prescribes.
    """
    workflows = tmp_path / "workflows"
    shutil.copytree(DEFAULT_WORKFLOW_DIR, workflows)
    document = yaml.safe_load((workflows / "ci.yml").read_text(encoding="utf-8"))
    mutate(document)
    (workflows / "ci.yml").write_text(yaml.safe_dump(document), encoding="utf-8")
    return workflows


FR_COMPLETENESS = next(gate for gate in GATES if gate.key == "fr-completeness")


def test_a_step_level_downgrade_of_the_gate_step_is_reported_advisory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EN-7 evasion: ``continue-on-error`` moved from the job onto its step.

    A gate whose real work cannot fail the job does not block, however clean
    the job-level setting looks. Reading only the job level would let this
    downgrade ship while every doc still called the gate blocking — the exact
    drift class this module exists to catch.
    """

    def _downgrade_the_run_step(document: dict[str, Any]) -> None:
        for step in document["jobs"]["fr-completeness"]["steps"]:
            if "run" in step:
                step["continue-on-error"] = True

    monkeypatch.setenv(
        "QUORUM_DOC_GATE_WORKFLOWS", str(_mutated_workflows(tmp_path, _downgrade_the_run_step))
    )

    assert _effective_status(_job(FR_COMPLETENESS)) == ADVISORY


def test_a_continue_on_error_on_an_incidental_step_is_still_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other direction: not every step-level flag is a downgrade.

    ``continue-on-error`` on checkout/setup/cache/artifact plumbing leaves the
    gate's own assertion able to fail the job, so the gate still blocks.
    Calling it advisory would be a false alarm that pushes docs into stating
    something untrue.
    """

    def _downgrade_the_plumbing(document: dict[str, Any]) -> None:
        steps = document["jobs"]["fr-completeness"]["steps"]
        for step in steps:
            if "uses" in step:
                step["continue-on-error"] = True
        steps.append({"uses": "actions/upload-artifact@v4", "continue-on-error": True})

    monkeypatch.setenv(
        "QUORUM_DOC_GATE_WORKFLOWS", str(_mutated_workflows(tmp_path, _downgrade_the_plumbing))
    )

    assert _effective_status(_job(FR_COMPLETENESS)) == BLOCKING


def test_the_documented_out_of_tree_red_proof_reports_instead_of_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``QUORUM_DOC_GATE_DOCS`` must work when it points outside the repo.

    That is the only way to prove the check RED without dirtying the working
    tree, which is what the module docstring promises. Reporting a drift in
    such a doc must produce the assertion message, not a ``ValueError`` from
    ``Path.relative_to``.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    drift = docs / "drift.md"
    drift.write_text("The coverage floor is 42.\n", encoding="utf-8")
    monkeypatch.setenv("QUORUM_DOC_GATE_DOCS", str(docs))

    with pytest.raises(AssertionError) as caught:
        test_prose_thresholds_match_the_enforced_values()

    assert str(drift) in str(caught.value)


# --------------------------------------------------------------------------
# Part D — countable claims: a number a doc states ABOUT THE REPO ITSELF
#
# Part B above pins a threshold quoted in prose against the value the repo
# enforces. This part pins the other kind of number: a COUNT of things that
# exist in the tree.
#
# Why it exists. ``AGENTS.md`` said "That directory holds **twelve** specs"
# about ``e2e/tests/invariants/``. Three specs were added over time and the
# sentence never moved. Nothing failed — the suite was fully green throughout,
# because no check existed. Measured 2026-08-04: the directory held **15**.
#
# The likely origin of the wrong number, and the reason this is worth a gate
# rather than a careful re-read: ``e2e.yml``'s FIRST blocking lane runs exactly
# 12 invariant specs. The count was almost certainly correct about the lane and
# then written down about the directory. That is not a mistake a reader catches
# by being careful; it is one an arithmetic check catches every time.
#
# SCOPE, deliberately narrow. Only numbers DERIVABLE FROM THE TREE, OFFLINE,
# belong here. The rule-14 table of required merge contexts is NOT a candidate:
# it comes from the GitHub branch-protection API, and these tests are hermetic.
# Re-deriving that one stays a human step (AGENTS.md rule 14 says so, and gives
# the command). Adding brittle regexes over every figure in every doc would
# break on innocent rewording and be switched off within a week — the same
# reasoning ``tests/code_text.py`` records for not banning substring assertions
# outright.
# --------------------------------------------------------------------------

AGENTS_MD = REPO_ROOT / "AGENTS.md"

#: The prose form the count must appear in. A DIGIT, not a spelled-out word:
#: "twelve" is not machine-readable, and the whole point is that a machine
#: re-checks it. Bold so the sentence still reads naturally to a human.
_INVARIANT_COUNT_PATTERN = r"That directory holds \*\*(\d+)\*\* specs"


def _invariant_spec_files() -> list[Path]:
    return sorted((REPO_ROOT / "e2e" / "tests" / "invariants").glob("*.spec.ts"))


def _check_countable_claim(*, text: str, pattern: str, actual: int, label: str) -> None:
    """Raise ``AssertionError`` unless ``text`` states ``actual`` for ``label``.

    Split out from the test so the bite-proof below can drive it with mutated
    text without touching the real ``AGENTS.md`` — the same shape Part C uses
    for the workflow guards.
    """
    match = re.search(pattern, text)
    assert match, (
        f"AGENTS.md no longer states the {label} in the form this gate checks "
        f"({pattern!r}). Restore the sentence or update the pattern — do not "
        f"delete the check, which would let the number drift again."
    )
    quoted = int(match.group(1))
    assert quoted == actual, (
        f"AGENTS.md says {quoted} {label}; there are {actual}. "
        f"Update the sentence (the command that produces the real number is "
        f"`ls -1 e2e/tests/invariants/*.spec.ts | wc -l`)."
    )


def test_agents_md_states_the_real_invariant_spec_count() -> None:
    """The count AGENTS.md gives for ``e2e/tests/invariants/`` must be the truth.

    What turns it red: add or delete a spec in that directory without editing
    the sentence in AGENTS.md.
    """
    specs = _invariant_spec_files()
    # Positive partner. Every assertion below compares two numbers, and both
    # would be 0 over a glob that matched nothing — a moved directory or a typo
    # in the pattern would otherwise make this gate pass while measuring
    # nothing, which is the failure mode most of this repo's gates were built
    # to avoid.
    assert specs, (
        "no *.spec.ts found under e2e/tests/invariants/ — the directory moved "
        "or the glob is wrong. This gate refuses to pass over an empty input."
    )
    _check_countable_claim(
        text=AGENTS_MD.read_text(encoding="utf-8"),
        pattern=_INVARIANT_COUNT_PATTERN,
        actual=len(specs),
        label="invariant specs",
    )


def test_the_countable_claim_guard_bites() -> None:
    """The guard must FAIL on a wrong number, not merely pass on a right one.

    Without this, ``test_agents_md_states_the_real_invariant_spec_count`` could
    be satisfied by a pattern that never matches anything real.

    What turns it red: make ``_check_countable_claim`` stop comparing.
    """
    real = len(_invariant_spec_files())
    wrong = f"That directory holds **{real + 1}** specs"

    with pytest.raises(AssertionError) as caught:
        _check_countable_claim(
            text=wrong, pattern=_INVARIANT_COUNT_PATTERN, actual=real, label="invariant specs"
        )
    assert f"says {real + 1}" in str(caught.value)
    assert f"there are {real}" in str(caught.value)

    # And it must fail LOUDLY when the sentence is gone entirely, rather than
    # silently finding nothing to check.
    with pytest.raises(AssertionError) as removed:
        _check_countable_claim(
            text="the sentence was deleted",
            pattern=_INVARIANT_COUNT_PATTERN,
            actual=real,
            label="invariant specs",
        )
    assert "no longer states" in str(removed.value)


# Part D2 — a CAPABILITY claim, pinned the same way a count is (#120 session).
#
# AGENTS.md rule 13b tells the next agent that `pytest-randomly` is not
# installed, so `-p no:randomly` disables a plugin that is not there and test
# order is deterministic. That claim was measured, and it is exactly the kind
# that rots silently: the day someone adds the plugin to `pyproject.toml`, the
# rule becomes actively misleading advice about how to reproduce an ordering
# bug, and nothing goes red to say so.
#
# Unlike the rule-14 contexts table this needs no network, so per AGENTS.md
# rule 1a it gets a gate instead of a careful re-read.


def test_agents_md_is_right_that_pytest_randomly_is_absent() -> None:
    """RED IF: `pytest-randomly` is installed while rule 13b still says it is not.

    The fix when this fires is to correct rule 13b, not to uninstall anything —
    the gate pins the DOC to the tree, not the tree to the doc.
    """
    text = AGENTS_MD.read_text(encoding="utf-8")
    claims_absent = "**`pytest-randomly` is NOT installed**" in text
    assert claims_absent, (
        "AGENTS.md no longer states rule 13b in the form this gate checks. "
        "Restore the sentence or update this pattern — do not delete the gate."
    )

    installed = importlib.util.find_spec("pytest_randomly") is not None
    assert not installed, (
        "`pytest-randomly` IS installed, but AGENTS.md rule 13b tells the next "
        "agent it is not — and therefore that `--randomly-seed` is unavailable "
        "and test order is deterministic. Both halves are now false. Correct "
        "rule 13b."
    )


def test_the_capability_claim_guard_bites() -> None:
    """The partner proving the check above is not vacuous.

    It asserts the *absence* of a module, which is trivially true in an
    environment where nothing is installed. This drives the same predicate
    against a module that certainly IS importable, and requires it to fail — so
    a `find_spec` that always returned ``None`` could not go unnoticed.
    """
    assert importlib.util.find_spec("pytest") is not None, (
        "find_spec cannot see `pytest` itself, so the absence check above "
        "proves nothing about `pytest_randomly`"
    )
