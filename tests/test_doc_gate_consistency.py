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

from product_app.config import Settings

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
    """Yield lines from live docs, skipping ``docs/archive/``.

    Archived files are historical session output, not current guidance — a
    past proof narrative can legitimately quote an old or deliberately-wrong
    number (e.g. "re-prove it BITES with --cov-fail-under=95 -> must fail")
    without that being a live claim this gate should hold to today's
    enforced value.
    """
    archive_dir = _docs_dir() / "archive"
    for path in sorted(_docs_dir().rglob("*.md")):
        if archive_dir in path.parents:
            continue
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


def _skip_leading_parenthetical(chunk: str, i: int) -> int:
    """Advance past a balanced ``(...)`` aside that opens before any clause
    break, so the comma right after it (e.g. ``job (see #130), blocking``)
    is treated the same as one right after the identifier's own closing
    punctuation.

    #224: #141 only exempted a comma immediately after the identifier's
    closing markdown punctuation. It left a real gap where a short
    parenthetical cross-reference sits between the identifier and the
    status comma — ``the `mutation-baseline` job (see #130), blocking`` was
    still cut before "blocking". Confirmed by execution.

    A naive "skip a comma within N characters" fix breaks the counter-example
    ``the `perf-gate` job, unrelated commentary, blocking since June`` (#224),
    where a real clause-break comma sits at a similarly short distance and
    must still cut. Parenthesis balance, not distance, is what tells the two
    apart: a "(" is only treated as a skippable aside if it opens BEFORE any
    comma/semicolon/". " boundary — i.e. before any text that would otherwise
    have cut the window anyway. An unbalanced "(" (no matching ")" in the
    chunk) is left alone; the caller's existing clause-break scan then
    applies unchanged.

    A second counter-example, found reasoning about the diff-cover doc row
    itself: ``changed-lines coverage (`diff-cover` >=95%), advisory mutation
    baseline`` has the identical shape — identifier, balanced parenthetical,
    comma, adjective — but here the comma DOES start a new clause about a
    different gate, and skipping it would wrongly attribute "advisory" to
    diff-cover. What tells the two apart is content, not position: the
    diff-cover parenthetical itself quotes another backtick-wrapped
    identifier (its own threshold detail); a plain cross-reference aside like
    ``(see #130)`` or ``(in passing)`` never does. So a parenthetical
    containing a backtick is treated as a second, self-contained claim
    (leave it to the normal clause-break scan) rather than a skippable aside.
    """
    paren_start = chunk.find("(", i)
    if paren_start == -1:
        return i
    for boundary in (",", ";", ". "):
        cut = chunk.find(boundary, i)
        if cut != -1 and cut < paren_start:
            return i  # a real clause break precedes the parenthetical
    depth = 0
    for j in range(paren_start, len(chunk)):
        if chunk[j] == "(":
            depth += 1
        elif chunk[j] == ")":
            depth -= 1
            if depth == 0:
                if "`" in chunk[paren_start:j]:
                    return i  # quotes another identifier: a claim, not an aside
                return j + 1
    return i  # unbalanced parenthesis: leave the window untouched


def _boundary_search_start(chunk: str, i: int, boundary: str) -> int:
    """Where `_window` starts looking for `boundary` when a boundary sitting
    EXACTLY at `i` is exempt.

    Such a boundary belongs to the identifier's own phrase, not to a
    following clause, so it is stepped over. Anything later is a genuine
    clause break and still cuts the window.

    #141 established this for "," alone (``(`gate`, blocking)``). #326
    extends the identical rule to ";" and ". ", which had no exemption and so
    lost the status word in ``job (see #130); blocking``. The step is
    ``len(boundary)`` so the two-character ". " boundary is stepped over in
    full rather than leaving the trailing space to re-match.

    **Which boundaries get the exemption is the caller's decision, not this
    function's** — see `_window`. "," gets it unconditionally (that is #141's
    pre-existing rule); ";" and ". " get it only when a parenthetical aside
    was actually skipped, because a bare ";" or "." straight after an
    identifier is ordinary sentence punctuation and a real clause break.
    """
    return i + len(boundary) if chunk.startswith(boundary, i) else i


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

    #224: the same exemption applies when a short balanced parenthetical
    aside — not just a punctuation run — sits between the identifier and
    the status comma. See `_skip_leading_parenthetical`.

    #317: `_skip_leading_parenthetical` only advances past ONE aside. A
    second consecutive aside (``job (a) (b), blocking``) left `i` sitting
    right after the first ``)`` — not a comma — so the exemption above never
    applied, and the comma search fell back to scanning the WHOLE chunk from
    index 0, finding the comma after the second aside and cutting the window
    there, before the status word. Confirmed by execution: `_claims` on
    ``the `mutation-baseline` job (a) (b), blocking`` returned ``[]``, not
    ``["blocking"]``. Call `_skip_leading_parenthetical` in a loop so any
    RUN of consecutive skippable asides is passed over, not just the first;
    it already refuses to advance past a real clause-break comma, so this
    still stops at the first non-skippable one.

    PR #317 review: the fix above only rebased the COMMA boundary's search
    start on `i`; the ";" and ". " boundary scans still searched from index
    0 of the whole chunk unconditionally. `_skip_leading_parenthetical`
    treats a balanced ``(...)`` as opaque while deciding whether to skip
    it, so a ";" or ". " *inside* an otherwise-skippable aside does not
    stop the skip — but it was still there, at a position before `i`, for
    the old unconditional scan to re-find and cut on, discarding the status
    word the skip had just protected. Confirmed by execution:
    ``the `mutation-baseline` job (see #130; still pending), blocking``
    returned ``[]``, not ``["blocking"]``. All three boundaries now search
    from `i` (the position after any skip), not from 0; a real clause-break
    ";" or ". " outside any skipped aside still cuts there, same as before.

    #326: searching from `i` is INCLUSIVE of `i`, so a boundary character
    sitting exactly at `i` — the first character after the skip — still cut.
    Only the comma carried an exemption for that position (the #141
    ``comma_search_start``); ";" and ". " did not, so
    ``the `mutation-baseline` job (see #130); blocking`` returned ``[]``
    while the comma spelling of the same sentence returned
    ``["blocking"]``. Confirmed by direct execution. ";" and ". " now get the
    same step-over-a-boundary-at-`i` treatment via `_boundary_search_start`.

    #326 review round: that exemption must be gated on an ASIDE actually
    having been skipped, not merely on the character sitting at `i`. `i` is
    also `0` when the line has no closing punctuation at all, and `1` when it
    only stepped over the identifier's own closing backtick — in both of
    those a ";" or ". " at `i` is ordinary sentence punctuation and a real
    clause break. Exempting it there attributed the NEXT clause's status word
    to this gate. Confirmed by direct execution against the ungated version:

        "the `perf-gate`; blocking since June"                    -> ['blocking']
        "run make fr-completeness. It is blocking."               -> ['blocking']
        "Two advisory jobs: mutation-baseline; the diff-cover
         gate is blocking."                                       -> ['blocking']

    all three of which `origin/main` correctly returned ``[]`` for. So
    `skipped_an_aside` gates the ";"/". " exemption. The "," exemption is
    left exactly as #141 wrote it — unconditional at `i` — because
    ``(`gate`, blocking)`` needs it after a bare punctuation run and that
    shape has carried the same exposure since #141 without misfiring.
    ADR-0047 records the decision and its cost.
    """
    chunk = line[end : end + _WINDOW]
    i = 0
    while i < len(chunk) and chunk[i] in "`)]\"'":
        i += 1
    after_punct = i
    while True:
        skipped = _skip_leading_parenthetical(chunk, i)
        if skipped == i:
            break
        i = skipped
    skipped_an_aside = i != after_punct
    for boundary in (",", ";", ". "):
        exempt_at_i = boundary == "," or skipped_an_aside
        start = _boundary_search_start(chunk, i, boundary) if exempt_at_i else i
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
# Part A3 — #224: a parenthetical aside between the identifier and the
# status comma still hides the claim.
# --------------------------------------------------------------------------
#
# #141 only exempted a comma that sits immediately after the identifier's own
# closing markdown punctuation. It does not help when a short parenthetical
# aside — e.g. a cross-reference to another issue — sits between the
# identifier and the status comma: `_window()` still cuts at that comma,
# because it is not the FIRST character after the punctuation-run skip.
# Confirmed by direct execution against the real `_window`/`_claims`
# functions before this fix:
#
#     "the `mutation-baseline` job (see #130), blocking" -> []


def test_a_parenthetical_aside_before_the_status_comma_does_not_hide_it() -> None:
    """The exact shape from #224: a short ``(...)`` aside between the
    identifier and the status comma must not cut the window early.

    Turns red if: `_window()` reverts to cutting at the first comma
    regardless of an intervening balanced parenthetical.
    """
    line = "the `mutation-baseline` job (see #130), blocking"
    assert _claims(_gate("mutation-baseline"), line) == ["blocking"], (
        "a parenthetical aside between the identifier and the status comma "
        f"hid a real blocking claim: {_window(line, line.index('baseline`') + len('baseline'))!r}"
    )


def test_a_real_clause_break_before_a_later_parenthetical_still_cuts() -> None:
    """The counter-example from #224 that a naive distance-based skip would
    break: a real clause-break comma that happens to precede an unrelated
    parenthetical must still cut the window there, not skip past it.

    Turns red if: the parenthetical-skip is applied even when a real,
    independent-clause comma appears BEFORE the parenthetical.
    """
    line = "the `perf-gate` job, mentioned (in passing), blocking since June"
    end = line.index("perf-gate`") + len("perf-gate")
    assert _claims(_gate("perf-gate"), line) == [], (
        "a comma before an unrelated parenthetical wrongly let a later "
        f"clause's status attach to perf-gate: {_window(line, end)!r}"
    )


def test_the_original_141_no_leak_case_still_holds_with_the_224_fix() -> None:
    """The #141 regression test's own counter-example, restated here so the
    #224 fix cannot silently regress it: no parenthetical at all, and the
    first comma still ends an unrelated clause.
    """
    line = "the `perf-gate` job, unrelated commentary, blocking since June"
    assert _claims(_gate("perf-gate"), line) == []


# --------------------------------------------------------------------------
# Part A4 — #317: a SECOND consecutive parenthetical aside before the status
# comma still hides the claim.
# --------------------------------------------------------------------------
#
# `_skip_leading_parenthetical` only advances past one aside. After that, `i`
# points right after the first aside's closing ``)`` — not a comma — so the
# #141 same-comma exemption never applies, and the comma search restarts from
# index 0 of the whole chunk, finding the comma after the SECOND aside and
# cutting the window there, before the status word ever appears. Confirmed by
# direct execution against the real `_window`/`_claims` functions before this
# fix:
#
#     "the `mutation-baseline` job (a) (b), blocking" -> []


def test_two_consecutive_parenthetical_asides_before_the_status_comma_do_not_hide_it() -> None:
    """The exact shape from #317: two short ``(...)`` asides back to back,
    both before the status comma, must not cut the window early.

    Turns red if: `_window()` reverts to skipping only the first
    parenthetical aside.
    """
    line = "the `mutation-baseline` job (a) (b), blocking"
    assert _claims(_gate("mutation-baseline"), line) == ["blocking"], (
        "a second parenthetical aside between the identifier and the status "
        f"comma hid a real blocking claim: "
        f"{_window(line, line.index('baseline`') + len('baseline'))!r}"
    )


def test_two_consecutive_cross_reference_asides_are_also_skipped() -> None:
    """The finding's own reproduction: two ``(see #N)`` cross-references."""
    line = "the `mutation-baseline` job (see #1) (see #2), advisory"
    assert _claims(_gate("mutation-baseline"), line) == ["advisory"], (
        "two consecutive cross-reference asides hid a real advisory claim: "
        f"{_window(line, line.index('baseline`') + len('baseline'))!r}"
    )


def test_three_consecutive_parenthetical_asides_are_also_skipped() -> None:
    """A run longer than two must be skipped in full, not just the first two.

    Turns red if: the loop in `_window()` is replaced by a single fixed
    number of skip attempts instead of running until no more asides skip.
    """
    line = "the `mutation-baseline` job (x) (y) (z), blocking"
    assert _claims(_gate("mutation-baseline"), line) == ["blocking"]


def test_a_real_clause_break_between_two_consecutive_asides_still_cuts() -> None:
    """Counter-example for the #317 fix: a real clause-break comma sitting
    BETWEEN two asides must still stop the window at the later status word
    the clause break protects, mirroring
    `test_a_real_clause_break_before_a_later_parenthetical_still_cuts` one
    level deeper.

    Turns red if: the loop is widened to skip a second aside even when a
    real, independent-clause comma separates it from the first.
    """
    line = "the `perf-gate` job (see #1), unrelated (see #2), blocking since June"
    assert _claims(_gate("perf-gate"), line) == [], (
        "a real clause break between two asides wrongly let a later "
        f"clause's status attach to perf-gate: "
        f"{_window(line, line.index('perf-gate`') + len('perf-gate'))!r}"
    )


# --------------------------------------------------------------------------
# Part A5 — PR #317 review: a ";" or ". " sitting INSIDE an otherwise
# skippable parenthetical still truncates the window before the status word.
# --------------------------------------------------------------------------
#
# `_skip_leading_parenthetical` correctly treats the whole balanced ``(...)``
# as opaque when deciding whether to skip it — a ";" or ". " *inside* the
# parens does not stop the balance scan, so `i` ends up past the aside, right
# where #224/#317 intend. But `_window`'s own boundary scan for ";" and ". "
# unconditionally searched the chunk from index 0, not from `i`, so it found
# that same internal ";"/". " again — a position BEFORE the skip — and cut
# the window there, discarding everything the skip had just protected,
# including the status word after it. The comma boundary already used
# `comma_search_start` keyed off `i`; ";" and ". " did not. Confirmed by
# direct execution against the real `_window`/`_claims` functions before this
# fix:
#
#     "the `mutation-baseline` job (see #130; still pending), blocking" -> []
#     "the `mutation-baseline` job (see notes. more detail), blocking"  -> []


def test_a_semicolon_inside_a_skipped_parenthetical_does_not_hide_the_status() -> None:
    """The exact shape from the #317 review finding: a ";" inside an
    otherwise-skippable ``(...)`` aside must not truncate the window before
    the status word that follows the aside.

    Turns red if: the ";" boundary scan in `_window()` reverts to searching
    from index 0 of the chunk instead of from the position after the skip.
    """
    line = "the `mutation-baseline` job (see #130; still pending), blocking"
    assert _claims(_gate("mutation-baseline"), line) == ["blocking"], (
        "a semicolon inside a skipped parenthetical aside hid a real "
        f"blocking claim: "
        f"{_window(line, line.index('baseline`') + len('baseline'))!r}"
    )


def test_a_sentence_break_inside_a_skipped_parenthetical_does_not_hide_the_status() -> None:
    """The same finding's second shape: a ". " sentence break inside the
    aside, rather than a ";".

    Turns red if: the ". " boundary scan in `_window()` reverts to searching
    from index 0 of the chunk instead of from the position after the skip.
    """
    line = "the `mutation-baseline` job (see notes. more detail), blocking"
    assert _claims(_gate("mutation-baseline"), line) == ["blocking"], (
        "a sentence break inside a skipped parenthetical aside hid a real "
        f"blocking claim: "
        f"{_window(line, line.index('baseline`') + len('baseline'))!r}"
    )


def test_an_explicit_status_claim_inside_a_skipped_parenthetical_shape_is_also_seen() -> None:
    """The finding's third shape: the vanishing claim is an explicit
    "advisory", not just "blocking" — confirms the fix is not accidentally
    specific to one status word.
    """
    line = "the `mutation-baseline` job (rationale; deprecated), advisory"
    assert _claims(_gate("mutation-baseline"), line) == ["advisory"], (
        "a semicolon inside a skipped parenthetical aside hid a real "
        f"advisory claim: "
        f"{_window(line, line.index('baseline`') + len('baseline'))!r}"
    )


def test_a_real_semicolon_clause_break_outside_any_aside_still_cuts() -> None:
    """Counter-example: a semicolon that is a genuine clause break — not
    inside any parenthetical — must still end the window there, mirroring
    the existing comma counter-examples one boundary character over.

    Turns red if: the ";" boundary is widened to skip past `i` blindly,
    losing the clause-break protection it exists to provide.
    """
    line = "the `perf-gate` job; unrelated commentary; blocking since June"
    assert _claims(_gate("perf-gate"), line) == []


def test_a_real_sentence_break_outside_any_aside_still_cuts() -> None:
    """Counter-example for ". ": a genuine sentence break outside any
    parenthetical must still end the window there.

    Turns red if: the ". " boundary is widened to skip past `i` blindly,
    losing the clause-break protection it exists to provide.
    """
    line = "the `perf-gate` job. Unrelated sentence. blocking since June"
    assert _claims(_gate("perf-gate"), line) == []


def test_a_comma_inside_a_skipped_parenthetical_does_not_hide_the_status() -> None:
    """PR #317 rebase review: a "," inside an otherwise-skippable ``(...)``
    aside must not truncate the window before the status word that follows
    the aside — the same shape as the ";"/". " findings above, one boundary
    character over.

    Before this class of fix, `comma_search_start` defaulted to 0 whenever
    `chunk[i]` was not itself a comma, so the comma-search fallback re-scanned
    the WHOLE chunk from index 0 and re-found the comma sitting INSIDE the
    just-skipped aside — cutting the window there, before the status word.

    Turns red if: the comma boundary's search-start reverts to 0 instead of
    `i` (the position after any skip).
    """
    line = "the `mutation-baseline` job (see #130, #131) is blocking"
    assert _claims(_gate("mutation-baseline"), line) == ["blocking"], (
        "a comma inside a skipped parenthetical aside hid a real "
        f"blocking claim: "
        f"{_window(line, line.index('baseline`') + len('baseline'))!r}"
    )


def test_a_second_comma_inside_a_skipped_parenthetical_is_also_no_problem() -> None:
    """The finding's second shape: a plain adjective pair (no cross-reference
    numbers) inside the aside, confirming the fix is not accidentally
    specific to ``#N, #N`` content.
    """
    line = "the `mutation-baseline` job (flaky, retrying) blocking"
    assert _claims(_gate("mutation-baseline"), line) == ["blocking"], (
        "a comma inside a skipped parenthetical aside hid a real "
        f"blocking claim: "
        f"{_window(line, line.index('baseline`') + len('baseline'))!r}"
    )


# --------------------------------------------------------------------------
# Part A6 — #326: a ";" or ". " sitting EXACTLY where a skip ended still
# truncates the window before the status word.
# --------------------------------------------------------------------------
#
# Part A5 rebased all three boundary scans on `i`, the position after the
# leading punctuation run and any skipped parenthetical asides. That fixed a
# boundary character sitting INSIDE a skipped aside (a position before `i`).
# It did not fix a boundary character sitting AT `i` — the first character
# after the skip — because `str.find(boundary, i)` is inclusive of `i`. The
# comma has carried an explicit exemption for exactly that position since
# #141 (`comma_search_start = i + 1 if chunk[i] == ","`); ";" and ". " did
# not, so the idiomatic ``job (see #130); blocking`` shape lost its status
# word. Confirmed by direct execution against the real `_window`/`_claims`
# functions before this fix:
#
#     "the `mutation-baseline` job (a b), blocking" -> ["blocking"]
#     "the `mutation-baseline` job (a b); blocking" -> []
#     "the `mutation-baseline` job (a b). blocking" -> []
#
# The exemption is deliberately NARROW — position `i` only. A ";" or ". "
# anywhere later in the chunk is still a clause break and still cuts, which
# is what keeps a status word belonging to a *different* clause from being
# attributed to this gate. See ADR-0047.


def test_a_semicolon_immediately_after_a_skipped_aside_does_not_hide_the_status() -> None:
    """The exact shape from #326: a ";" as the very first character after a
    skipped parenthetical aside must be exempt, the same as a "," there.

    Turns red if: the ";" boundary scan in `_window()` reverts to searching
    from `i` inclusive instead of skipping a ";" that sits at `i`.
    """
    line = "the `mutation-baseline` job (see #130); blocking"
    assert _claims(_gate("mutation-baseline"), line) == ["blocking"], (
        "a semicolon immediately after a skipped aside hid a real blocking "
        f"claim: {_window(line, line.index('baseline`') + len('baseline'))!r}"
    )


def test_a_sentence_break_immediately_after_a_skipped_aside_does_not_hide_the_status() -> None:
    """#326's second boundary: a ". " as the very first characters after a
    skipped parenthetical aside must be exempt too.

    Turns red if: the ". " boundary scan in `_window()` reverts to searching
    from `i` inclusive instead of skipping a ". " that sits at `i`.
    """
    line = "the `mutation-baseline` job (see #130). blocking"
    assert _claims(_gate("mutation-baseline"), line) == ["blocking"], (
        "a sentence break immediately after a skipped aside hid a real "
        f"blocking claim: {_window(line, line.index('baseline`') + len('baseline'))!r}"
    )


def test_a_semicolon_after_a_run_of_asides_does_not_hide_the_status() -> None:
    """The #317 multi-aside run and the #326 boundary exemption compose: `i`
    lands after the LAST aside, and the ";" sitting there must be exempt.

    Turns red if: the ";" exemption is keyed off the first aside's end rather
    than the loop's final `i`.
    """
    line = "the `mutation-baseline` job (a) (b); advisory"
    assert _claims(_gate("mutation-baseline"), line) == ["advisory"], (
        "a semicolon after a run of skipped asides hid a real advisory "
        f"claim: {_window(line, line.index('baseline`') + len('baseline'))!r}"
    )


def test_a_bare_semicolon_clause_break_with_no_aside_still_cuts() -> None:
    """NEGATIVE PARTNER for #326 (rule 7). With no aside to skip, `i` sits on
    the space after the identifier's closing backtick, so a later ";" is a
    genuine clause break and MUST still cut. Without this partner the two
    positive tests above would pass over a `_window()` that had simply
    stopped treating ";" as a boundary at all.

    Turns red if: the ";" exemption is widened beyond position `i` — e.g. to
    "skip the first ";" anywhere in the chunk".
    """
    line = "the `perf-gate` job; blocking since June"
    assert _claims(_gate("perf-gate"), line) == [], (
        "a bare semicolon clause break stopped cutting the window: "
        f"{_window(line, line.index('perf-gate`') + len('perf-gate'))!r}"
    )


def test_a_bare_sentence_break_with_no_aside_still_cuts() -> None:
    """NEGATIVE PARTNER for #326, ". " boundary (rule 7).

    Turns red if: the ". " exemption is widened beyond position `i`.
    """
    line = "the `perf-gate` job. blocking since June"
    assert _claims(_gate("perf-gate"), line) == [], (
        "a bare sentence break stopped cutting the window: "
        f"{_window(line, line.index('perf-gate`') + len('perf-gate'))!r}"
    )


def test_a_semicolon_after_an_aside_that_quotes_an_identifier_still_cuts() -> None:
    """NEGATIVE PARTNER for #326: the `_skip_leading_parenthetical` guard
    that refuses to skip an aside quoting ANOTHER backtick identifier must
    still hold on the ";" path. Nothing is skipped, so `i` never reaches the
    ";" and the exemption must not fire.

    Turns red if: the ";" exemption is applied before, or independently of,
    the skip that establishes `i`.
    """
    line = "the `mutation-baseline` job (`diff-cover` >=95%); advisory elsewhere"
    assert _claims(_gate("mutation-baseline"), line) == [], (
        "a semicolon after a self-contained second claim stopped cutting: "
        f"{_window(line, line.index('baseline`') + len('baseline'))!r}"
    )


# --------------------------------------------------------------------------
# Part A6b — #326 review round: the exemption must require a SKIPPED ASIDE,
# not merely a boundary character sitting at `i`.
# --------------------------------------------------------------------------
#
# The three negative partners above all put the word "job" between the
# identifier and the boundary, so `i` lands on the space after the closing
# backtick and the boundary is never AT `i`. They therefore stay green under
# an exemption that fires whenever the boundary happens to sit at `i` —
# including when `i` is 0 (no punctuation at all) or 1 (only the identifier's
# own closing backtick was stepped over). Those are exactly the shapes below.
# Measured against the ungated version: all three returned ["blocking"],
# while `origin/main` returned [] for all three.
#
# Every one of these is ordinary English punctuation, not a parenthetical
# aside, so the status word belongs to the NEXT clause and must not be
# attributed to this gate.


def test_a_semicolon_straight_after_the_identifier_backtick_still_cuts() -> None:
    """NEGATIVE PARTNER for #326 with NO spacer word: `i` sits at 1, having
    only stepped over the identifier's own closing backtick. No aside was
    skipped, so the ";" there is a real clause break and must still cut.

    Turns red if: the ";"/". " exemption stops requiring `skipped_an_aside`
    and fires on any boundary sitting at `i`.
    """
    line = "the `perf-gate`; blocking since June"
    assert _claims(_gate("perf-gate"), line) == [], (
        "a semicolon straight after the identifier's backtick stopped "
        f"cutting: {_window(line, line.index('perf-gate`') + len('perf-gate'))!r}"
    )


def test_a_full_stop_straight_after_the_identifier_backtick_still_cuts() -> None:
    """NEGATIVE PARTNER for #326, ". " boundary, NO spacer word.

    Turns red if: the ";"/". " exemption stops requiring `skipped_an_aside`
    and fires on any boundary sitting at `i`.
    """
    line = "the `perf-gate`. blocking since June"
    assert _claims(_gate("perf-gate"), line) == [], (
        "a full stop straight after the identifier's backtick stopped "
        f"cutting: {_window(line, line.index('perf-gate`') + len('perf-gate'))!r}"
    )


def test_a_semicolon_straight_after_a_bare_identifier_still_cuts() -> None:
    """NEGATIVE PARTNER for #326 at `i == 0`: an identifier written WITHOUT
    backticks has no closing punctuation to step over, so `i` is 0 and the
    ";" is the very first character of the chunk. It is a sentence's clause
    break and the following clause is about a DIFFERENT gate.

    Turns red if: the ";"/". " exemption stops requiring `skipped_an_aside`
    and fires on any boundary sitting at `i`.
    """
    line = "Two advisory jobs: mutation-baseline; the diff-cover gate is blocking."
    assert _claims(_gate("mutation-baseline"), line) == [], (
        "a semicolon at position 0 stopped cutting, attributing the next "
        "clause's status to mutation-baseline: "
        f"{_window(line, line.index('mutation-baseline') + len('mutation-baseline'))!r}"
    )


def test_a_full_stop_straight_after_a_bare_identifier_still_cuts() -> None:
    """NEGATIVE PARTNER for #326 at `i == 0`, ". " boundary. The idiomatic
    ``run make fr-completeness. It is blocking.`` shape, where the status
    word is in the next SENTENCE and says nothing about this gate.

    Turns red if: the ";"/". " exemption stops requiring `skipped_an_aside`
    and fires on any boundary sitting at `i`.
    """
    line = "run make fr-completeness. It is blocking."
    assert _claims(_gate("fr-completeness"), line) == [], (
        "a full stop at position 0 stopped cutting, pulling the next "
        "sentence into the window: "
        f"{_window(line, line.index('fr-completeness') + len('fr-completeness'))!r}"
    )


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


# Part D3 — the SAME count, stated by three files about ONE list (#257 session).
#
# `buildMarkdownRenderer()` in app.js numbers its deviations from stock
# markdown-it `(1)` … `(8)`. In one commit, three documents described that list:
#
#   app.js                    "SIX deliberate deviations"    wrong
#   static/vendor/README.md   "seven deliberate deviations"  wrong
#   docs/adr/0015-*.md        "Eight deviations"             right
#
# Nothing compared any of them to the code. Two independent review lenses each
# found the disagreement by grepping — which is the tell that a machine should
# be doing it. Same shape as Part D above: a number derivable from the tree,
# offline, so it gets a check rather than a corrected sentence (rule 1a).
# --------------------------------------------------------------------------

APP_JS = REPO_ROOT / "src" / "product_app" / "static" / "app.js"
VENDOR_README = REPO_ROOT / "src" / "product_app" / "static" / "vendor" / "README.md"
ADR_0015 = REPO_ROOT / "docs" / "adr" / "0015-how-the-vendored-markdown-parser-is-configured.md"

#: The numbered deviation comments inside `buildMarkdownRenderer`, e.g. "// (3) ".
_DEVIATION_MARKER = re.compile(r"^    // \((\d)\) ", re.MULTILINE)

#: How each document spells the count. Words, because those sentences read as
#: prose; mapped rather than banned, since "eight deviations" is the natural
#: English and a gate nobody can read around gets switched off.
_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

_DEVIATION_CLAIMS = {
    "app.js": (APP_JS, r"//\s+([A-Za-z]+) deliberate deviations from stock markdown-it"),
    "static/vendor/README.md": (VENDOR_README, r"plus ([A-Za-z]+) deliberate deviations"),
    "docs/adr/0015": (ADR_0015, r"### 3\. ([A-Za-z]+) deviations from stock"),
}


def _deviation_numbers() -> list[int]:
    return [int(n) for n in _DEVIATION_MARKER.findall(APP_JS.read_text(encoding="utf-8"))]


def test_the_deviation_count_matches_the_code() -> None:
    """Every document stating how many deviations there are must be right.

    What turns it red: add or remove a ``// (n)`` deviation in
    ``buildMarkdownRenderer`` without editing all three sentences.
    """
    numbers = _deviation_numbers()
    # Positive partner: an empty list would satisfy every comparison below while
    # measuring nothing, so a renamed function or a reformatted comment would
    # silently switch this gate off.
    assert numbers, (
        "no `// (n)` deviation comments found in app.js. The block moved or was "
        "reformatted — restore the marker shape or update _DEVIATION_MARKER; do "
        "not delete this check, which is what let three files disagree."
    )
    # They must be a clean 1..N run, or "how many" is not well defined.
    assert numbers == list(range(1, len(numbers) + 1)), (
        f"the deviation comments are numbered {numbers}, which is not 1..N"
    )
    actual = len(numbers)

    for label, (path, pattern) in _DEVIATION_CLAIMS.items():
        match = re.search(pattern, path.read_text(encoding="utf-8"))
        assert match, (
            f"{label} no longer states the deviation count in the form this gate "
            f"reads ({pattern!r}). Restore the sentence or update the pattern."
        )
        word = match.group(1).lower()
        quoted = _NUMBER_WORDS.get(word)
        assert quoted is not None, (
            f"{label} spells the deviation count {match.group(1)!r}, which this "
            f"gate cannot read. Use one of: {sorted(_NUMBER_WORDS)}"
        )
        assert quoted == actual, (
            f"{label} says {word} ({quoted}) deviations; app.js implements {actual}."
        )


def test_the_deviation_count_guard_bites() -> None:
    """The guard must FAIL on a wrong number, not merely pass on a right one.

    What turns it red: make the comparison above stop comparing.
    """
    actual = len(_deviation_numbers())
    assert actual > 0

    pattern = _DEVIATION_CLAIMS["static/vendor/README.md"][1]
    wrong_word = next(w for w, n in _NUMBER_WORDS.items() if n != actual)
    right_word = next(w for w, n in _NUMBER_WORDS.items() if n == actual)

    wrong = re.search(pattern, f"`html: false` plus {wrong_word} deliberate deviations — recorded")
    assert wrong is not None
    assert _NUMBER_WORDS[wrong.group(1).lower()] != actual, "a wrong number read as agreeing"

    # And a sentence with the RIGHT number must read as agreeing, or the guard
    # would be red no matter what anyone wrote.
    ok = re.search(pattern, f"plus {right_word} deliberate deviations")
    assert ok is not None
    assert _NUMBER_WORDS[ok.group(1).lower()] == actual

    # A deleted sentence must be caught, not skipped.
    assert re.search(pattern, "the sentence was deleted") is None


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


# --------------------------------------------------------------------------
# Part E — the CONFIGURATION surface: every knob the app reads must be
# discoverable in `.env.example`.
#
# Why it exists. Measured 2026-08-05 on `bc38bbb`: `Settings` had **44**
# fields and `.env.example` documented **19** of them. The 25 undocumented
# ones included both halves of the LLM-as-judge
# (`QUORUM_EVAL_JUDGE_API_KEY`, `QUORUM_EVAL_JUDGE_MODEL_ID`) and the whole
# Tavily web-search block — three capabilities a contributor could not learn
# existed from the file whose entire job is to tell them.
#
# SCOPE: every field, not a hand-picked "capability-gating" subset. `Settings`
# has no `env_prefix`, so pydantic-settings reads EVERY field from the
# environment under its uppercased name — there is no such thing as a field
# that cannot be set this way. A hand-written subset would have to be kept in
# step by a human, and its failure mode is the silent omission this gate
# exists to stop (AGENTS.md rule 1a: prefer a check over a corrected
# sentence). Deriving the list from `Settings.model_fields` cannot go stale.
# --------------------------------------------------------------------------

ENV_EXAMPLE = REPO_ROOT / ".env.example"

#: An ASSIGNMENT in `.env.example`, commented out or not. Some knobs are
#: deliberately shown commented (`# SENTRY_DSN=`) because an empty value and
#: an absent one differ — a commented assignment still counts as discoverable.
#:
#: The `#? ?` — at most ONE space after an optional `#` — is load-bearing and
#: was written after the looser `#?\s*` failed its own mutation test. This
#: file's header explains the three capability gates in prose, indented:
#:
#:     #   Web search (Tavily) — no flag; a non-empty key alone turns it on
#:     #       TAVILY_API_KEY=...
#:
#: Under `#?\s*` that prose line COUNTED as documentation, so deleting the
#: real `TAVILY_API_KEY=` assignment left the gate green. That is exactly the
#: substring-instead-of-structure trap AGENTS.md rule 8 describes — living
#: inside a gate written to enforce rule 8. Pinned by
#: `test_a_name_mentioned_only_in_prose_is_not_documentation`.
_ENV_NAME_PATTERN = r"^#? ?([A-Z][A-Z0-9_]*)="


#: The first section banner. Everything above it is the explanatory header,
#: which is PROSE and may never be read as documentation — see
#: `test_the_header_cannot_vouch_for_any_knob`.
_FIRST_SECTION_BANNER = r"^# --- "


def _env_example_body(text: str) -> str:
    """The part of `.env.example` below its explanatory header.

    Tightening `_ENV_NAME_PATTERN` alone was not enough. Adversarial review
    reflowed the header's indentation from seven spaces to one — turning a
    prose line into `# TAVILY_API_KEY=...` — deleted the real assignment, and
    all 24 doc-gate tests stayed green. The pattern was pinned; the FILE was
    not. Reading only the body removes the header from the question entirely,
    so it can be reflowed freely and can never vouch for anything.
    """
    match = re.search(_FIRST_SECTION_BANNER, text, re.MULTILINE)
    return text[match.start() :] if match else text


def _env_example_documented_names(text: str) -> set[str]:
    return set(re.findall(_ENV_NAME_PATTERN, _env_example_body(text), re.MULTILINE))


def _check_every_field_is_documented(*, text: str, field_names: list[str]) -> None:
    """Raise ``AssertionError`` unless every field in ``field_names`` is in ``text``.

    Split out from the test so the bite-proof below can drive it with mutated
    text without touching the real `.env.example` — the same shape Parts C and
    D use.
    """
    # Positive partner. Both sides of the comparison below would be empty over
    # a `Settings` whose fields could not be read, and "no field is missing"
    # is trivially true over no fields at all (AGENTS.md rule 7).
    assert field_names, (
        "no Settings fields were enumerated — `Settings.model_fields` moved or "
        "is empty. This gate refuses to pass over an empty input."
    )
    documented = _env_example_documented_names(text)
    missing = sorted(name.upper() for name in field_names if name.upper() not in documented)
    assert not missing, (
        f"{len(missing)} Settings field(s) are readable from the environment but "
        f"undocumented in .env.example, so a contributor cannot discover them: "
        f"{', '.join(missing)}. Add a line for each (commented out is fine when "
        f"an empty value would be invalid) — do not delete this gate."
    )


def test_env_example_documents_every_settings_field() -> None:
    """RED IF: a `Settings` field exists that `.env.example` never mentions.

    What turns it red: add a field to `Settings` without adding a line for it
    to `.env.example`.
    """
    _check_every_field_is_documented(
        text=ENV_EXAMPLE.read_text(encoding="utf-8"),
        field_names=sorted(Settings.model_fields),
    )


def test_the_env_example_guard_bites() -> None:
    """The guard must FAIL on a real omission, not merely pass on a full file.

    Without this, `_check_every_field_is_documented` could be satisfied by a
    pattern that matched everything, or by a field list that was always empty.

    What turns it red: make `_check_every_field_is_documented` stop comparing,
    or make its positive partner stop firing on an empty field list.
    """
    fields = sorted(Settings.model_fields)
    full = ENV_EXAMPLE.read_text(encoding="utf-8")

    # 1. A file that documents nothing must be rejected, and must NAME the
    #    fields it is missing rather than failing with a bare count.
    with pytest.raises(AssertionError) as empty_file:
        _check_every_field_is_documented(text="# nothing here", field_names=fields)
    assert "QUORUM_EVAL_JUDGE_API_KEY" in str(empty_file.value)
    assert "undocumented in .env.example" in str(empty_file.value)

    # 2. Deleting exactly ONE real line must be caught. This is the mutation
    #    that matters: a gate that only notices a wholly empty file would miss
    #    the single silent omission that is the actual failure mode here.
    victim = "QUORUM_EVAL_JUDGE_MODEL_ID"
    holed = re.sub(rf"^#?\s*{victim}=.*$", "", full, flags=re.MULTILINE)
    assert holed != full, (
        f"{victim} is not present in .env.example in the form this bite-proof "
        f"removes, so the mutation below would be a no-op and prove nothing"
    )
    with pytest.raises(AssertionError) as one_hole:
        _check_every_field_is_documented(text=holed, field_names=fields)
    assert victim in str(one_hole.value)

    # 3. And the positive partner must fire on an empty field list rather than
    #    letting "nothing is missing" pass as success.
    with pytest.raises(AssertionError) as no_fields:
        _check_every_field_is_documented(text=full, field_names=[])
    assert "empty input" in str(no_fields.value)


#: Uncommented example values that DELIBERATELY differ from the field's
#: default, with the reason. `.env.example` is a local-development template,
#: so a local-only convenience may legitimately not match a
#: production-safe default — but each one has to be named here, not assumed.
_DELIBERATE_VALUE_DEVIATIONS = {
    # The field defaults False for security. The example turns it on because
    # the legacy `X-Account-Id` header is how the local test fixture
    # authenticates, and `auth` refuses it outside `RUNTIME_ENVIRONMENT=local`
    # anyway. Pre-dates this gate (`git log -S` → bca4ba6).
    "ACCOUNT_LEGACY_HEADER_ENABLED": "local dev authenticates via the legacy header",
}


def _env_example_live_lines(text: str) -> list[str]:
    """Uncommented assignments — the lines a copied `.env` would really parse."""
    return [line for line in text.splitlines() if re.match(r"^[A-Z][A-Z0-9_]*=", line)]


def test_env_example_is_a_loadable_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED IF: `.env.example`, used as a real `.env`, cannot boot the app.

    `.env.example` says "copy this file to .env", so every uncommented line in
    it is a value the app will actually parse. That is not free: `Settings`
    already carries a validator (`_blank_expose_api_docs_is_unset`) written
    because a blank `EXPOSE_API_DOCS=` crashed startup with a ValidationError.
    Part E above forces new fields INTO this file; this test is the partner
    that stops it being satisfied with a line that would break a boot.

    THE `delenv` LOOP IS LOAD-BEARING. `Settings(_env_file=...)` gives the
    real `os.environ` PRIORITY over the dotenv file, and `tests/conftest.py`
    pins `ACCOUNT_LEGACY_HEADER_ENABLED` and `OPENROUTER_LIVE_EXECUTION_ENABLED`
    into the environment before collection (CI sets the latter too). Without
    the loop this test was silently vacuous for exactly those two fields:
    adversarial review set `ACCOUNT_LEGACY_HEADER_ENABLED=totally-not-a-bool`
    in `.env.example` and it stayed green, while the same file with those two
    names unset raised `ValidationError`. One of the two is the
    live-execution switch.

    What turns it red: add `TAVILY_MAX_RESULTS=` (blank, int-typed, no
    before-validator) uncommented to `.env.example` — MEASURED to raise
    `ValidationError`. Note that `SESSION_MINT_CAP_OVERRIDE=` blank does NOT
    turn it red despite also being int-typed: it carries
    `_blank_mint_cap_override_is_unset`, which absorbs a blank into `None`.
    Both were executed before this line was written; the difference between
    them is the whole reason this test is worth having.
    """
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    live_lines = _env_example_live_lines(text)
    # Positive partner: an `.env.example` of nothing but comments would load
    # perfectly and prove nothing about any field.
    assert len(live_lines) >= 20, (
        f".env.example has only {len(live_lines)} uncommented assignments; this "
        f"test would be near-vacuous. Did the file get commented out wholesale?"
    )

    # Take the ambient environment out of the question, so the file under test
    # is the only input.
    for line in live_lines:
        monkeypatch.delenv(line.split("=", 1)[0], raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text("\n".join(live_lines) + "\n", encoding="utf-8")
    # Constructing Settings against the file is the whole assertion: pydantic
    # raises ValidationError on any value its field cannot parse.
    Settings(_env_file=str(env_file))  # type: ignore[call-arg]


def test_env_example_values_match_the_real_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED IF: an example value silently disagrees with the field's default.

    Documenting all 44 fields turned `.env.example` into a 40-line hard pin of
    default values, and nothing made those track the code: adversarial review
    changed `soft_threshold_usd`'s default from 0.15 to 0.99 with the example
    untouched and every doc gate stayed green. A stale example value is worse
    than no example — an operator copies it and silently pins the old
    behaviour.

    Deviations are allowed but must be DECLARED, in
    `_DELIBERATE_VALUE_DEVIATIONS`, with a reason.

    What turns it red: change any default in `config.py` without updating
    `.env.example` (or vice versa).
    """
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    live_lines = _env_example_live_lines(text)
    for line in live_lines:
        monkeypatch.delenv(line.split("=", 1)[0], raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text("\n".join(live_lines) + "\n", encoding="utf-8")
    loaded = Settings(_env_file=str(env_file))  # type: ignore[call-arg]
    defaults = Settings.model_construct()

    documented = {line.split("=", 1)[0] for line in live_lines}
    # Positive partner: no documented name means nothing is compared below.
    assert len(documented) >= 20, f"only {len(documented)} names to compare"

    mismatches = {}
    for field in Settings.model_fields:
        name = field.upper()
        if name not in documented or name in _DELIBERATE_VALUE_DEVIATIONS:
            continue
        actual, expected = getattr(loaded, field), getattr(defaults, field)
        if actual != expected:
            mismatches[name] = (actual, expected)
    assert not mismatches, (
        f".env.example documents values that are no longer the code's defaults: "
        f"{ {k: f'example={v[0]!r} default={v[1]!r}' for k, v in mismatches.items()} }. "
        f"Update the example, or declare the deviation in "
        f"_DELIBERATE_VALUE_DEVIATIONS with a reason."
    )

    # The allowlist must not rot either: a declared deviation that no longer
    # deviates is a stale exemption hiding a future drift.
    stale = [
        name
        for name in _DELIBERATE_VALUE_DEVIATIONS
        if name in documented and getattr(loaded, name.lower()) == getattr(defaults, name.lower())
    ]
    assert not stale, (
        f"{stale} are listed as deliberate deviations but now MATCH the "
        f"default. Remove them from _DELIBERATE_VALUE_DEVIATIONS."
    )


# --------------------------------------------------------------------------
# Part E2 — the MIRROR check: `.env.example` must not document knobs that
# nothing reads.
#
# Part E stops a real field going undocumented. This stops the opposite and
# more dangerous drift: a documented name that the app ignores. `Settings`
# sets `extra="ignore"`, so an unrecognised variable in a `.env` is silently
# discarded — the operator sets it, sees no error, and believes it took.
#
# Measured 2026-08-05 on `bc38bbb`, FOUR such names were live in the file:
#
# * `ENVIRONMENT` — documented as "Runtime environment: local, staging, or
#   production. Controls security defaults and validation behavior". The
#   field is `runtime_environment`, so the variable is `RUNTIME_ENVIRONMENT`
#   and `ENVIRONMENT` is read by nothing. MEASURED: a `.env` containing
#   `ENVIRONMENT=production` yields `runtime_environment=local` and
#   `session_cookie_secure=False` — i.e. an operator who followed this file
#   to harden a deployment got LOCAL security defaults, and
#   `validate_production_environment()`'s refusal to start misconfigured
#   never fired. Production itself was never exposed: `fly.toml` sets BOTH
#   names. The exposure was anyone configuring from `.env`.
# * `COST_OUTPUT_TOKEN_MULTIPLIER`, `COST_INNER_CALL_MULTIPLIER`,
#   `COST_INNER_CALL_CAP_USD` — the pre-#16 cost model's knobs, still
#   documented with tuning advice ("Higher values = more conservative
#   estimates") after the model that read them was replaced. The estimate
#   they claim to tune is what the cost guardrail keys off.
#
# THE RULE, fully mechanical: a documented name must either be a `Settings`
# field or be read from the environment by an ACTUAL `os.environ` call in
# `src/` (which is how `QUORUM_TOKEN_SECRET`, read at `config.py:541`, is
# vouched for). No hand-written allowlist.
#
# "An `os.environ` call", NOT "the token appears in `src/`". The looser
# free-text version was written first and adversarial review defeated it two
# ways, both demonstrated:
#   * a name surviving only in a COMMENT or docstring vouched for itself, so
#     documenting a knob deleted from the code stayed green;
#   * every module CONSTANT vouched for itself — `DAILY_CAP_USD`,
#     `GLOBAL_DAILY_CEILING_USD`, `DEBATE_ROUND_MAX_TOKENS` and friends are
#     hardcoded in `costs.py`/`debate.py` and are NOT env-readable, yet all
#     passed. That is precisely the failure this part exists to catch, and
#     `.env.example` already discusses `GLOBAL_DAILY_CEILING_USD` in prose,
#     so the edit that would have walked into the trap was one line away.
# The whole-token boundary is still load-bearing inside the `os.environ`
# match: a substring match would let `RUNTIME_ENVIRONMENT` vouch for the dead
# `ENVIRONMENT` and the headline finding would have been missed.
# --------------------------------------------------------------------------

#: An actual read of the environment in `src/`: `os.environ["X"]`,
#: `os.environ.get("X")`, or `os.getenv("X")`.
_ENV_READ_PATTERN = r"""os\.(?:environ(?:\.get)?\(|getenv\()\s*['"]([A-Z][A-Z0-9_]*)['"]"""


def _env_names_read_in_src(src_text: str) -> set[str]:
    return set(re.findall(_ENV_READ_PATTERN, src_text))


def _is_read_anywhere(name: str, *, field_names: set[str], src_text: str) -> bool:
    if name in field_names:
        return True
    return name in _env_names_read_in_src(src_text)


def _check_no_documented_knob_is_dead(*, text: str, field_names: set[str], src_text: str) -> None:
    documented = sorted(_env_example_documented_names(text))
    # Positive partner: "none of them is dead" is trivially true over none.
    assert documented, (
        "no variable names were parsed out of .env.example — the file moved or "
        "the pattern is wrong. This gate refuses to pass over an empty input."
    )
    assert src_text.strip(), (
        "src/ read as empty, so every documented name would look dead. This "
        "gate refuses to pass over an empty input."
    )
    dead = [
        name
        for name in documented
        if not _is_read_anywhere(name, field_names=field_names, src_text=src_text)
    ]
    assert not dead, (
        f"{len(dead)} name(s) documented in .env.example are read by NOTHING: "
        f'{", ".join(dead)}. `Settings` sets extra="ignore", so setting one of '
        f"these in a .env is silently discarded and the operator gets no error. "
        f"Delete the line, or point it at the name the code really reads."
    )


def _src_text() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((REPO_ROOT / "src").rglob("*.py"))
    )


def test_env_example_documents_no_knob_that_nothing_reads() -> None:
    """RED IF: `.env.example` names a variable the app ignores.

    What turns it red: add `FOO_BAR=1` to `.env.example` without a matching
    `Settings` field or an `os.environ` read in `src/`.
    """
    _check_no_documented_knob_is_dead(
        text=ENV_EXAMPLE.read_text(encoding="utf-8"),
        field_names={name.upper() for name in Settings.model_fields},
        src_text=_src_text(),
    )


def test_the_dead_knob_guard_bites() -> None:
    """The guard must FAIL on a dead knob, and must not be fooled by a prefix.

    The second half is the one that matters. The real finding this gate was
    built from — `ENVIRONMENT` — is a strict substring of the very field that
    supersedes it, `RUNTIME_ENVIRONMENT`. A substring-based reader would have
    reported the file clean.

    What turns it red: relax `_is_read_anywhere` to a substring match, or make
    `_check_no_documented_knob_is_dead` stop comparing.
    """
    fields = {name.upper() for name in Settings.model_fields}
    src = _src_text()

    # 1. An invented knob is caught and NAMED.
    with pytest.raises(AssertionError) as dead:
        _check_no_documented_knob_is_dead(
            text="NOT_A_REAL_KNOB=1\n", field_names=fields, src_text=src
        )
    assert "NOT_A_REAL_KNOB" in str(dead.value)

    # 2. The substring trap: `ENVIRONMENT` must NOT be vouched for by
    #    `RUNTIME_ENVIRONMENT` appearing in the source. This is the exact
    #    mutation that would have hidden the measured finding.
    assert "RUNTIME_ENVIRONMENT" in src, (
        "RUNTIME_ENVIRONMENT is absent from src/, so the substring trap below "
        "would not be a trap and this bite-proof would prove nothing"
    )
    assert not _is_read_anywhere("ENVIRONMENT", field_names=fields, src_text=src), (
        "`ENVIRONMENT` was accepted as read, but only `RUNTIME_ENVIRONMENT` "
        "exists — the whole-token boundary in `_is_read_anywhere` has been lost"
    )

    # 3. And a name that IS genuinely read only via os.environ must pass, so
    #    the gate cannot be satisfied by rejecting everything.
    assert _is_read_anywhere("QUORUM_TOKEN_SECRET", field_names=fields, src_text=src), (
        "QUORUM_TOKEN_SECRET is read by config.py via os.environ but the gate "
        "no longer recognises it — the check has become too strict to be true"
    )

    # 4. The positive partners fire on empty inputs.
    with pytest.raises(AssertionError) as no_names:
        _check_no_documented_knob_is_dead(text="# only comments", field_names=fields, src_text=src)
    assert "empty input" in str(no_names.value)
    with pytest.raises(AssertionError) as no_src:
        _check_no_documented_knob_is_dead(text="APP_NAME=x\n", field_names=fields, src_text="  ")
    assert "empty input" in str(no_src.value)


def test_a_name_mentioned_only_in_prose_is_not_documentation() -> None:
    """RED IF: an indented mention inside a comment counts as a documented knob.

    This is the regression guard for a hole found in this gate's OWN mutation
    test. `.env.example`'s header explains the capability gates in prose,
    indented under a bullet:

        #   Web search (Tavily) — no flag; a non-empty key alone turns it on
        #       TAVILY_API_KEY=...

    With the original `^#?\\s*NAME=` pattern that line satisfied Part E, so
    deleting the REAL `TAVILY_API_KEY=` assignment left the gate green — the
    gate passed while the file no longer documented the knob. AGENTS.md rule 8
    (assert structure, not substrings) describes exactly this, and the gate
    that broke it exists to enforce rule 1a.

    What turns it red: widen `_ENV_NAME_PATTERN`'s `#? ?` back to `#?\\s*`.
    """
    prose = "#   Web search (Tavily)\n#       TAVILY_API_KEY=...\n"
    assert _env_example_documented_names(prose) == set(), (
        "an indented mention inside a comment was read as a documented "
        "assignment; _ENV_NAME_PATTERN has been widened and Part E can now "
        "pass over a knob that is only talked about"
    )

    # The positive partner: the two forms that ARE documentation still count,
    # so the tightened pattern has not become too strict to be useful.
    assert _env_example_documented_names("TAVILY_API_KEY=\n") == {"TAVILY_API_KEY"}
    assert _env_example_documented_names("# SENTRY_DSN=\n") == {"SENTRY_DSN"}

    # And the real file must still satisfy Part E under the tightened pattern —
    # i.e. the fix above was to the GATE, not achieved by loosening the file.
    _check_every_field_is_documented(
        text=ENV_EXAMPLE.read_text(encoding="utf-8"),
        field_names=sorted(Settings.model_fields),
    )


def test_the_header_cannot_vouch_for_any_knob() -> None:
    """RED IF: `.env.example`'s explanatory header contains an assignment line.

    Part E reads only the body (below the first `# --- ` banner), so a header
    mention cannot vouch for a knob. This is the other half of that guarantee:
    it keeps the header free of assignment-SHAPED lines, so nobody can later
    "document" a knob up there and believe it counts.

    Why both halves exist: tightening `_ENV_NAME_PATTERN` alone was defeated
    by reflowing the header's indentation from seven spaces to one, which
    turned prose into `# TAVILY_API_KEY=...` and let the real assignment be
    deleted with every doc-gate test still green.

    What turns it red: add `# FOO=bar` (one space or none) above the first
    `# --- ` section banner in `.env.example`.
    """
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    match = re.search(_FIRST_SECTION_BANNER, text, re.MULTILINE)
    assert match, (
        ".env.example has no `# --- ` section banner, so the header/body split "
        "Part E depends on has collapsed and the whole file is being read as "
        "documentation. Restore the banners."
    )
    header = text[: match.start()]
    # Positive partner: an empty header would satisfy any "contains no X".
    assert header.strip(), ".env.example has no header at all — the split is meaningless"
    stray = re.findall(_ENV_NAME_PATTERN, header, re.MULTILINE)
    assert not stray, (
        f"{stray} look like assignments but sit in .env.example's explanatory "
        f"header, which Part E does not read. Move them below the first "
        f"`# --- ` banner, or indent them further so they read as prose."
    )


def test_the_dead_knob_guard_requires_a_real_environment_read() -> None:
    """RED IF: a name is vouched for by mere textual presence in `src/`.

    The first version of `_is_read_anywhere` searched the concatenated text of
    `src/**/*.py`, so a name surviving only in a COMMENT vouched for itself,
    and so did every hardcoded module constant. Both were demonstrated against
    the real tree: `DAILY_CAP_USD`, `GLOBAL_DAILY_CEILING_USD` and
    `DEBATE_ROUND_MAX_TOKENS` all passed the gate despite being constants that
    `Settings` cannot read from the environment at all — and `.env.example`
    already mentions `GLOBAL_DAILY_CEILING_USD` in prose.

    What turns it red: widen `_is_read_anywhere` back to a free-text search.
    """
    fields = {name.upper() for name in Settings.model_fields}
    src = _src_text()

    # 1. A hardcoded constant is NOT an environment read, even though its name
    #    certainly appears in src/.
    for constant in ("DAILY_CAP_USD", "GLOBAL_DAILY_CEILING_USD"):
        assert re.search(rf"(?<![A-Za-z0-9_]){constant}(?![A-Za-z0-9_])", src), (
            f"{constant} no longer appears in src/ at all, so it cannot "
            f"demonstrate the free-text trap this test guards"
        )
        assert not _is_read_anywhere(constant, field_names=fields, src_text=src), (
            f"{constant} was accepted as a documentable knob, but it is a "
            f"hardcoded constant with no os.environ read — documenting it "
            f"would be silently discarded by Settings(extra='ignore')"
        )

    # 2. A name that appears ONLY in a comment must not vouch for itself.
    assert not _is_read_anywhere(
        "OBSOLETE_KNOB_XYZ",
        field_names=fields,
        src_text="# historical note: OBSOLETE_KNOB_XYZ was removed in 2025\n",
    )

    # 3. Positive partner: a genuine os.environ read IS recognised, so the
    #    tightened rule has not become too strict to be true.
    assert _is_read_anywhere("QUORUM_TOKEN_SECRET", field_names=fields, src_text=src), (
        "QUORUM_TOKEN_SECRET is read via os.environ.get in config.py but the "
        "gate no longer recognises it"
    )
    assert _env_names_read_in_src(src), "no os.environ reads found in src/ at all"


# --------------------------------------------------------------------------
# Part F — a doc claim about WHAT A SECRET PROTECTS, pinned to the code.
#
# Measured 2026-08-07. `DEPLOY.md` said `QUORUM_TOKEN_SECRET` was "used to sign
# session tokens", and that rotating it meant "all existing sessions are
# invalidated (users get logged out)". Both were false. The secret is the HMAC
# key for COST-CONFIRMATION tokens (`CostEstimationService`, `costs.py`), and
# sessions do not use a signing key at all — `auth.py` mints opaque random IDs
# with `secrets.token_urlsafe(24)` and stores them server-side.
#
# The second error was the costly one. It told an operator that rotating a
# leaked secret would log every user out, when the real blast radius is the
# outstanding confirmation tokens inside a 5-minute TTL. A doc that overstates
# the cost of a security action discourages that action.
#
# Per rule 1a this gets a gate rather than a corrected sentence: the fact is
# derivable from the tree OFFLINE, so nothing needs to re-read the prose.

_DEPLOY_MD = REPO_ROOT / "DEPLOY.md"
#: `auth` is a MODULE, not a package. Spelling this as a directory is not a
#: hypothetical slip: while preparing this gate,
#: `git grep -- src/product_app/auth/` returned nothing and was briefly read as
#: "auth does not sign anything". It returned nothing because THE PATH DOES NOT
#: EXIST — the same shape as AGENTS.md rule 1's "the location was recalled, not
#: grepped". The positive partner below is what caught it, which is the whole
#: argument for requiring one.
_AUTH_PY = REPO_ROOT / "src" / "product_app" / "auth.py"
_COSTS_PY = REPO_ROOT / "src" / "product_app" / "costs.py"


def test_the_token_secret_is_still_a_cost_token_key_not_a_session_key() -> None:
    """RED IF: `auth.py` starts using `QUORUM_TOKEN_SECRET`.

    Pins the CODE side of the claim `DEPLOY.md` now makes. If auth ever does
    start using it, this fires and the doc must be corrected — the fix is to
    update the prose, not to delete the gate.
    """
    auth_src = _AUTH_PY.read_text(encoding="utf-8")
    assert "QUORUM_TOKEN_SECRET" not in auth_src, (
        "auth.py now reads QUORUM_TOKEN_SECRET, so DEPLOY.md's statement that "
        "the secret is 'not sessions' is no longer true. Correct DEPLOY.md."
    )
    assert "hmac" not in auth_src, (
        "auth.py now uses hmac, so sessions may no longer be opaque random "
        "IDs. DEPLOY.md's rotation guidance ('does NOT log anyone out') turns "
        "on sessions carrying no signature — re-verify it before shipping."
    )


def test_the_token_secret_guard_is_not_vacuous() -> None:
    """POSITIVE PARTNER (rule 7) for the check above.

    Two absence checks over one file are trivially true if the file were empty,
    renamed, or unreadable. This proves `auth.py` was really read and really is
    the session module, and that the secret genuinely IS consumed where the doc
    says it is.
    """
    auth_src = _AUTH_PY.read_text(encoding="utf-8")
    assert "secrets.token_urlsafe(24)" in auth_src, (
        "auth.py no longer mints opaque random session ids with "
        "secrets.token_urlsafe(24) — the absence checks above would pass over "
        "a file that is no longer the session module"
    )
    assert "csrf_token" in auth_src, "auth.py does not look like the session module any more"

    costs_src = _COSTS_PY.read_text(encoding="utf-8")
    assert "QUORUM_TOKEN_SECRET" in costs_src, (
        "costs.py no longer reads QUORUM_TOKEN_SECRET, so DEPLOY.md's claim "
        "that it is the cost-confirmation HMAC key is now wrong"
    )
    assert "hmac.new(self._binding_secret" in costs_src, (
        "costs.py no longer HMACs with the binding secret — DEPLOY.md calls it "
        "an HMAC key, and that is the sentence this gate exists to protect"
    )


def test_deploy_md_does_not_claim_rotation_logs_users_out() -> None:
    """RED IF: the refuted 'users get logged out' sentence comes back.

    Kept as a distinct check from the code-side gate above because this one
    guards the OPERATIONAL advice, which is what actually misleads a human
    deciding whether to rotate a leaked secret.
    """
    text = _DEPLOY_MD.read_text(encoding="utf-8")
    assert "users get logged out" not in text, (
        "DEPLOY.md again claims rotating QUORUM_TOKEN_SECRET logs users out. "
        "Measured 2026-08-07: it signs cost-confirmation tokens with a "
        "5-minute TTL and sessions do not use it, so rotation is nearly free. "
        "Overstating the cost of rotating a leaked secret discourages doing it."
    )
    assert "Used to sign session tokens" not in text, (
        "DEPLOY.md again describes QUORUM_TOKEN_SECRET as signing session "
        "tokens. It is the cost-confirmation HMAC key (costs.py)."
    )
    # Positive partner: prove the file really is DEPLOY.md and was read.
    assert "QUORUM_TOKEN_SECRET" in text, (
        "DEPLOY.md no longer mentions QUORUM_TOKEN_SECRET at all — the two "
        "absence checks above would pass vacuously"
    )


# --------------------------------------------------------------------------
# Part G — the DEFAULT MODEL SLOT IDS a doc names, pinned to the code.
#
# Measured 2026-09-01 (board row W17). `docs/10-functional-requirements.md`
# (FR-004) and `docs/12-acceptance-criteria.md` (AC-007) both named
# `deepseek/deepseek-chat-v3.1` as the fourth default model slot. deepseek left
# `DEFAULT_MODEL_IDS` on 2026-07-25 in commit f25696e (as
# `nvidia/nemotron-3-super-120b-a12b`); 3bf13a6 narrowed it two days later to
# the shipped `nvidia/nemotron-3-nano-30b-a3b`. Eight further live documents
# carried the same stale id. Nothing failed for five weeks, because nothing
# compared the sentence to the constant.
#
# Per AGENTS.md rule 1a this gets a GATE rather than ten corrected sentences:
# the four ids are derivable from the tree OFFLINE.
#
# WHY THIS READS A BLOCK, NOT A WHOLE FILE. The first version of this gate
# extracted every backticked `vendor/model` token in the file and compared the
# lot. Adversarial review broke it twice:
#   * `README.md` — the repo's front door, and the highest-traffic statement of
#     the defaults — could not be covered at all, because line 42 names
#     `anthropic/claude-haiku-4.5` a second time when describing
#     `settings.debate_model_id`. Whole-file extraction read five ids and failed
#     on a correct document.
#   * A backticked MIME type (`application/json`, `text/event-stream`) added to
#     any covered doc turned the gate red with a message blaming the model
#     slots. Eight docs were one ordinary sentence away from a misleading
#     failure.
# So extraction is scoped to a DEFAULT-CLAIM BLOCK: a line carrying a "default"
# cue (or sitting under a heading that does), plus any list items directly
# beneath it that consist solely of one backticked id. A block counts only if it
# names at least two ids, because a default-slot claim names a SET — that is
# what keeps `README.md:42`'s single-id aside out of the comparison.
#
# WHAT THIS GATE CANNOT SEE, stated rather than implied (both reproduced by
# review, both inherent to a markup-anchored check):
#   * an id written WITHOUT backticks ("the fourth slot is
#     deepseek/deepseek-chat-v3.1") — `_model_ids_in` requires the markup that
#     makes a token an identifier rather than prose, and
#     `test_the_model_id_extractor_ignores_repo_paths` pins that on purpose;
#   * an id inside a fenced code block that carries no "default" cue line.
# Both would be NEW contradicting prose rather than the existing sentence going
# stale, which is the drift this gate exists to stop. Closing them needs a
# meaning-level check, not a tighter regex.
#
# SCOPE, deliberately narrow — only documents that assert, in the present
# tense, what the SHIPPED product defaults to. Deliberately NOT covered:
#   * `PRODUCT_IDEA.md` and `docs/04-problem-statement.md` record the product
#     owner's 2026-06-16 intake answer (D-010). That answer really was
#     deepseek; rewriting it would falsify a dated decision record.
#   * `docs/13-open-questions.md` records the same answer against OQ-005.
#   * `docs/design-handoff/Quorum Final Review.dc.html` is an approved visual
#     mock that predates the swap and genuinely shows DeepSeek. (Its sibling
#     `AC-CROSSWALK.md` is NOT a mock — it is live traceability evidence, and it
#     IS covered below. The first version of this comment excluded the whole
#     directory on the mock's rationale, and review found the crosswalk still
#     asserting the retired id.)
#   * `docs/archive/`, `docs/validation/` — records of runs that happened.
#   * `tests/`, and the `_FALLBACK_CATALOG` row in
#     `src/product_app/catalog_fetcher.py` (defined at line 127, deepseek row at
#     line 244 — NOT in `model_slots.py`, which only imports it) — deepseek is
#     still a real, selectable OpenRouter model. 3bf13a6 retained that row
#     deliberately.
#   * `docs/faq/index.html` and `docs/readme-verification-appendix.md` state the
#     defaults in `<code>` tags rather than backticks, so this extractor cannot
#     read them. They are correct today; covering them needs an HTML-aware
#     reader and is recorded as follow-on debt in ADR-0088.
# --------------------------------------------------------------------------

#: Live documents that state the shipped default slot set. Each must carry at
#: least one default-claim block, and those blocks must name exactly the ids of
#: ``DEFAULT_MODEL_IDS``, in slot order.
_DEFAULT_SLOT_SPEC_DOCS: tuple[str, ...] = (
    "README.md",
    "docs/01-product-brief.md",
    "docs/08-prioritization.md",
    "docs/10-functional-requirements.md",
    "docs/118-qa-test-charter-jira.md",
    "docs/12-acceptance-criteria.md",
    "docs/20-architecture.md",
    "docs/35-confluence-operational-guide.md",
    "docs/51-test-data-strategy.md",
    "docs/design-handoff/AC-CROSSWALK.md",
)

#: The smallest corpus this gate is allowed to measure. Without it,
#: ``_DEFAULT_SLOT_SPEC_DOCS = ()`` makes every assertion below vacuously true
#: and the suite stays green having read nothing — reproduced by review on the
#: first version of this gate. AGENTS.md: every gate reports what it counted and
#: refuses to pass on an empty input.
_MIN_SPEC_DOCS = 10

#: A backticked ``vendor/name`` token. Structure, not substring (rule 8): the
#: backticks are the markup that marks it as an identifier rather than prose, so
#: this cannot match the sentence that *explains* a model id.
_BACKTICKED_SLASH_TOKEN_RE = re.compile(r"`([a-z][a-z0-9-]*/[a-z0-9][a-z0-9._-]*)`")

#: First segments that make a backticked ``a/b`` token something other than a
#: model id. Two families, both measured in the covered docs or their
#: neighbours: repository paths (these docs cross-reference each other
#: constantly — ``docs/22-api-contract.md``, ``src/product_app``) and MIME types
#: (``application/json``, ``text/event-stream``), which review demonstrated
#: would otherwise be counted as models.
_NON_MODEL_PREFIXES: frozenset[str] = frozenset(
    {
        "docs",
        "src",
        "tests",
        "e2e",
        "scripts",
        "build",
        "configs",
        "infra",
        "policies",
        "schemas",
        "templates",
        "profiles",
        "application",
        "text",
        "image",
        "audio",
        "video",
        "multipart",
        "origin",
        "refs",
    }
)

#: A file extension is never part of an OpenRouter model id. Kept as
#: defence-in-depth on top of the prefix set; note that it is NOT independently
#: load-bearing today — review showed every current token it would reject is
#: already rejected by ``_NON_MODEL_PREFIXES``. (An earlier version of this
#: comment justified it with the claim that ``docs/07-open-questions.md`` "no
#: longer exists on disk". That was FALSE — ``git ls-files
#: docs/07-open-questions.md`` returns it, 10 lines, tracked. It was a location
#: recalled rather than grepped, which is the exact failure mode AGENTS.md
#: rule 1 names, committed inside a gate written to satisfy that rule.)
_FILE_SUFFIX_RE = re.compile(r"\.(md|py|ts|tsx|js|mjs|css|html|ya?ml|json|toml|sh|txt)$")

#: The word that marks a line as CLAIMING a default set, rather than merely
#: mentioning a model. Matched case-insensitively so "Defaults are", "Default
#: models populated" and "defaulting to" all anchor.
_DEFAULT_CUE_RE = re.compile(r"default", re.I)

#: A list item that is nothing but one backticked model id — the shape
#: `README.md`, `docs/01-product-brief.md` and `docs/08-prioritization.md` use
#: to enumerate the slots under a lead-in line.
_SOLE_ID_ITEM_RE = re.compile(r"^\s*[-*]\s*`[a-z][a-z0-9-]*/[a-z0-9][a-z0-9._-]*`\s*$")

#: A block must name at least this many ids to count as a default-SET claim.
#: Two, not four: four would make "the doc names some but not all of them"
#: invisible instead of red, which is the cardinality hole rule 6b warns about.
_MIN_IDS_PER_BLOCK = 2


def _model_ids_in(text: str) -> list[str]:
    """Every backticked OpenRouter model id in ``text``, in order of appearance."""
    found: list[str] = []
    for token in _BACKTICKED_SLASH_TOKEN_RE.findall(text):
        vendor = token.split("/", 1)[0]
        if vendor in _NON_MODEL_PREFIXES or _FILE_SUFFIX_RE.search(token):
            continue
        found.append(token)
    return found


def _default_claim_blocks(text: str) -> list[tuple[int, list[str]]]:
    """``(1-based line number, ids)`` for each default-SET claim in ``text``.

    Split out from the tests so the bite-proofs below can drive it with
    synthetic text, without touching the real docs (the same shape Part C and
    Part D use).
    """
    lines = text.splitlines()
    blocks: list[tuple[int, list[str]]] = []
    heading_cues = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("#"):
            # A heading carries its cue down to the lines it introduces. This is
            # load-bearing: `docs/12-acceptance-criteria.md:51` — one of the two
            # documents at the centre of the defect — states the slot set
            # without the word "default" anywhere in the sentence. Its heading
            # two lines up is `## AC-007 Default models populated`.
            heading_cues = bool(_DEFAULT_CUE_RE.search(line))
            i += 1
            continue
        if _DEFAULT_CUE_RE.search(line) or heading_cues:
            ids = _model_ids_in(line)
            j = i + 1
            # A lead-in line ("The four model slots default to:") may be
            # separated from its list by one blank line.
            while j < len(lines) and not ids and not lines[j].strip():
                j += 1
            while j < len(lines) and _SOLE_ID_ITEM_RE.match(lines[j]):
                ids += _model_ids_in(lines[j])
                j += 1
            if len(ids) >= _MIN_IDS_PER_BLOCK:
                blocks.append((i + 1, ids))
                i = max(j, i + 1)
                continue
        i += 1
    return blocks


def _check_default_slot_ids(*, text: str, expected: tuple[str, ...], label: str) -> None:
    """Raise ``AssertionError`` unless ``text``'s default claims name ``expected``.

    Three assertions, in this order, because they fail for three different
    reasons and one combined equality would report the wrong one:

    1. **Refuse an empty input** (AGENTS.md: every gate reports what it counted
       and refuses to pass on nothing). "No wrong model named" is trivially true
       of a document that claims no defaults at all.
    2. **Cardinality** (rule 6b) — how MANY ids, not merely that no bad one
       appeared. A doc that dropped three of the four slots would otherwise
       satisfy a set-subset check.
    3. **Ordered equality** — the docs list the ids in slot order, so this pins
       which model is in which slot, not merely which four are present.
    """
    blocks = _default_claim_blocks(text)
    assert blocks, (
        f"{label} makes no default-model-slot claim this gate can read. It "
        f"refuses to pass over an empty input — it exists to compare the ids a "
        f"document states against product_app.model_slots.DEFAULT_MODEL_IDS, "
        f"and it cannot do that over nothing. Restore the claim (a line "
        f"carrying the word 'default', or a heading that does, naming at least "
        f"{_MIN_IDS_PER_BLOCK} backticked `vendor/model` ids), or remove the "
        f"document from _DEFAULT_SLOT_SPEC_DOCS with a stated reason."
    )
    found = [model_id for _, ids in blocks for model_id in ids]
    where = ", ".join(f"line {line}" for line, _ in blocks)
    assert len(found) == len(expected), (
        f"{label} claims {len(found)} default model id(s) ({found}) at {where}; "
        f"the product ships {len(expected)} default slots ({list(expected)}). "
        f'The command that produces the real list is `python -c "from '
        f"product_app.model_slots import DEFAULT_MODEL_IDS; "
        f'print(DEFAULT_MODEL_IDS)"`.'
    )
    assert tuple(found) == expected, (
        f"{label} claims default model slots {found} at {where}; the product "
        f"ships {list(expected)} (product_app.model_slots.DEFAULT_MODEL_IDS), "
        f"in that slot order. Update the document — or, if the product genuinely "
        f"changed slots, update every document in _DEFAULT_SLOT_SPEC_DOCS to "
        f"match the new constant. Do not delete this gate: it exists because "
        f"FR-004 and AC-007 named a model this repo had not shipped for five "
        f"weeks and nothing noticed."
    )


def test_the_default_model_ids_are_a_usable_reference_set() -> None:
    """POSITIVE PARTNER for the doc checks: the CODE side is real and readable.

    Every assertion in ``_check_default_slot_ids`` compares the docs against
    ``DEFAULT_MODEL_IDS``. If that tuple were malformed or duplicated, the
    comparisons could pass while measuring nothing useful.

    What turns it red: give ``DEFAULT_MODEL_IDS`` a duplicate slot, or an entry
    that is not a ``vendor/model`` identifier. (Emptying the tuple is NOT a
    valid mutation proof for this test — it breaks collection in
    ``tests/conftest.py`` via ``costs.py`` with ``ValueError: max() iterable
    argument is empty``, and per rule 6 a mutation that breaks collection proves
    nothing.)
    """
    from product_app.model_slots import DEFAULT_MODEL_IDS

    assert DEFAULT_MODEL_IDS, "product_app.model_slots.DEFAULT_MODEL_IDS is empty"
    assert len(set(DEFAULT_MODEL_IDS)) == len(DEFAULT_MODEL_IDS), (
        f"DEFAULT_MODEL_IDS has a duplicate slot: {list(DEFAULT_MODEL_IDS)}"
    )
    for model_id in DEFAULT_MODEL_IDS:
        assert _model_ids_in(f"`{model_id}`") == [model_id], (
            f"{model_id!r} is not shaped like an OpenRouter model id, so the "
            f"doc extractor would never match it and the doc gates below would "
            f"silently stop comparing anything"
        )


def test_the_default_slot_corpus_is_not_empty() -> None:
    """EMPTY-INPUT FLOOR for the corpus itself (AGENTS.md gate rule).

    ``test_spec_docs_name_the_default_model_ids_the_app_actually_ships`` loops
    over ``_DEFAULT_SLOT_SPEC_DOCS``. Emptying that tuple makes every assertion
    inside the loop vacuously true and the gate green over nothing — reproduced
    by review against the first version of this Part. The per-document floor
    does not catch it, because no document is read.

    What turns it red: delete an entry from ``_DEFAULT_SLOT_SPEC_DOCS`` without
    lowering ``_MIN_SPEC_DOCS``, which forces the deletion to be a deliberate,
    reviewable edit rather than a silent one.
    """
    assert len(_DEFAULT_SLOT_SPEC_DOCS) >= _MIN_SPEC_DOCS, (
        f"_DEFAULT_SLOT_SPEC_DOCS holds {len(_DEFAULT_SLOT_SPEC_DOCS)} "
        f"documents; this gate refuses to measure fewer than {_MIN_SPEC_DOCS}. "
        f"If a document genuinely stopped stating the defaults, lower "
        f"_MIN_SPEC_DOCS in the same commit and say why."
    )
    assert len(set(_DEFAULT_SLOT_SPEC_DOCS)) == len(_DEFAULT_SLOT_SPEC_DOCS), (
        "_DEFAULT_SLOT_SPEC_DOCS lists the same document twice, which would "
        "inflate the corpus count without measuring anything more"
    )


def test_spec_docs_name_the_default_model_ids_the_app_actually_ships() -> None:
    """Every covered doc's default-slot claim must equal ``DEFAULT_MODEL_IDS``.

    What turns it red: change a slot in ``src/product_app/model_slots.py``
    without editing the ten documents, or put
    ``deepseek/deepseek-chat-v3.1`` back into any of them.
    """
    from product_app.model_slots import DEFAULT_MODEL_IDS

    counted: dict[str, int] = {}
    for rel in _DEFAULT_SLOT_SPEC_DOCS:
        path = REPO_ROOT / rel
        assert path.is_file(), (
            f"{rel} is listed in _DEFAULT_SLOT_SPEC_DOCS but does not exist. "
            f"The gate would otherwise skip it and pass having read nothing."
        )
        text = path.read_text(encoding="utf-8")
        _check_default_slot_ids(text=text, expected=DEFAULT_MODEL_IDS, label=rel)
        counted[rel] = len(_default_claim_blocks(text))

    # Report what was counted. Every document must contribute at least one
    # default-claim block; a file that silently stopped making the claim is the
    # way this corpus would rot without anything going red.
    silent = sorted(rel for rel, blocks in counted.items() if blocks < 1)
    assert not silent, f"documents contributing no default-claim block: {silent}"
    assert sum(counted.values()) >= len(_DEFAULT_SLOT_SPEC_DOCS), (
        f"read {sum(counted.values())} default-claim blocks across "
        f"{len(_DEFAULT_SLOT_SPEC_DOCS)} documents: {counted}"
    )


def test_the_default_slot_gate_bites_on_a_stale_id() -> None:
    """The guard must FAIL on the exact drift it was written for.

    What turns it red: make ``_check_default_slot_ids`` stop comparing, or make
    ``_model_ids_in`` stop matching backticked identifiers.
    """
    expected = ("openai/gpt-4o-mini", "vendor-b/model-b", "vendor-c/model-c", "vendor-d/model-d")
    stale = (
        "Defaults are `openai/gpt-4o-mini`, `vendor-b/model-b`, "
        "`vendor-c/model-c`, and `deepseek/deepseek-chat-v3.1`."
    )
    with pytest.raises(AssertionError) as caught:
        _check_default_slot_ids(text=stale, expected=expected, label="synthetic.md")
    assert "deepseek/deepseek-chat-v3.1" in str(caught.value)
    assert "vendor-d/model-d" in str(caught.value)
    assert "line 1" in str(caught.value)


def test_the_default_slot_gate_refuses_an_empty_input() -> None:
    """A doc claiming NO defaults must fail, not pass (rule 7 / empty-input floor).

    This is the vacuity case: "no wrong model is named" is trivially true over a
    document that names no models at all, and that is precisely how a negative
    doc check rots.

    What turns it red: delete the ``assert blocks`` floor in
    ``_check_default_slot_ids``.
    """
    expected = ("vendor-a/model-a", "vendor-b/model-b")
    with pytest.raises(AssertionError) as empty:
        _check_default_slot_ids(
            text="This document explains model slots but names none of them.",
            expected=expected,
            label="empty.md",
        )
    assert "makes no default-model-slot claim" in str(empty.value)

    # A doc that names SOME but not all of them must fail on CARDINALITY, not
    # slip through a set-subset comparison (rule 6b).
    with pytest.raises(AssertionError) as short:
        _check_default_slot_ids(
            text="Defaults are `vendor-a/model-a` and `vendor-b/model-b`, `vendor-c/model-c`.",
            expected=("vendor-a/model-a", "vendor-b/model-b"),
            label="long.md",
        )
    assert "claims 3 default model id(s)" in str(short.value)


def test_a_default_claim_is_read_from_a_block_not_the_whole_file() -> None:
    """The scoping that lets `README.md` be covered at all.

    `README.md:42` names `anthropic/claude-haiku-4.5` a second time while
    describing `settings.debate_model_id`. Whole-file extraction read five ids
    and failed on a correct document; a MIME type anywhere in a covered doc did
    the same. Both were reproduced by review against the first version.

    What turns it red: make ``_default_claim_blocks`` scan the whole file again,
    drop ``_MIN_IDS_PER_BLOCK``, or drop the heading-cue rule.
    """
    # 1. A single-id aside near the word "default" is NOT a default-set claim.
    aside = "By default this is the same model as slot 2 (`anthropic/claude-haiku-4.5`)."
    assert _default_claim_blocks(aside) == []

    # 2. A lead-in line plus its bulleted list IS one block, across a blank line.
    listed = "The four model slots default to:\n\n- `openai/gpt-4o-mini`\n- `vendor-b/model-b`\n"
    assert _default_claim_blocks(listed) == [(1, ["openai/gpt-4o-mini", "vendor-b/model-b"])]

    # 3. A heading carries the cue to a sentence that lacks it — the AC-007
    #    shape, and the reason a line-scoped cue anchor was rejected.
    headed = (
        "## AC-007 Default models populated\n"
        "\n"
        "Then four slots are populated with `openai/gpt-4o-mini` and `vendor-b/model-b`.\n"
    )
    assert _default_claim_blocks(headed) == [(3, ["openai/gpt-4o-mini", "vendor-b/model-b"])]

    # 4. NEGATIVE PARTNER: the same sentence under a heading with no cue, and no
    #    cue of its own, is not read at all.
    unheaded = (
        "## Response shape\n"
        "\n"
        "Then four slots are populated with `openai/gpt-4o-mini` and `vendor-b/model-b`.\n"
    )
    assert _default_claim_blocks(unheaded) == []


def test_the_model_id_extractor_ignores_paths_and_mime_types() -> None:
    """POSITIVE + NEGATIVE partner for ``_model_ids_in``'s filters.

    The covered docs cross-reference each other with backticked paths
    (``docs/22-api-contract.md``, ``src/product_app``) and describe HTTP content
    types. If those were read as model ids the cardinality check above would
    fail on correct documents, and the usual "fix" would be to loosen the gate.

    What turns it red: drop ``_NON_MODEL_PREFIXES``, or tighten
    ``_BACKTICKED_SLASH_TOKEN_RE`` so real ids stop matching. (``_FILE_SUFFIX_RE``
    is deliberately NOT named here — review measured that removing it turns
    nothing red today, because every token it would reject is already rejected
    by the prefix set. It is defence-in-depth, and saying otherwise would be an
    unverified red-line.)
    """
    mixed = (
        "See `docs/22-api-contract.md` and `src/product_app`; the body is "
        "`application/json` and the stream is `text/event-stream`. The slot is "
        "`nvidia/nemotron-3-nano-30b-a3b` and the retired one was "
        "`deepseek/deepseek-chat-v3.1`. Also `docs/07-open-questions.md`."
    )
    assert _model_ids_in(mixed) == [
        "nvidia/nemotron-3-nano-30b-a3b",
        "deepseek/deepseek-chat-v3.1",
    ]
    # Negative partner: an unbackticked mention is prose, not an identifier.
    # This is a KNOWN blind spot, asserted so it is a stated design limit rather
    # than an accident — see the Part G header and ADR-0088's Consequences.
    assert _model_ids_in("the slot defaults to nvidia/nemotron-3-nano-30b-a3b") == []
