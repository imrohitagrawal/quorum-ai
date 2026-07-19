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
  'pull_request'``, so a direct push to ``main`` is ungated; ``codex-review``
  has no ``continue-on-error`` and always passes because its only real step is
  commented out. Effective status is therefore a four-valued model
  (blocking / blocking-on-pull-requests-only / advisory / vacuous) and docs are
  asked to state the *qualified* truth.
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

import os
import re
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
    Gate("codex-review", "ci.yml", "codex-review", (r"codex-review",)),
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


def _effective_status(job: dict[str, Any]) -> str:
    if job.get("continue-on-error") is True:
        return ADVISORY
    if _is_vacuous(job):
        return VACUOUS
    if "pull_request" in str(job.get("if", "")):
        return PR_ONLY
    return BLOCKING


#: A status word in prose. ``non-blocking`` must win over ``blocking``.
_STATUS_RE = re.compile(r"\bnon-blocking\b|\bblocking\b|\badvisory\b", re.IGNORECASE)

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
    """
    chunk = line[end : end + _WINDOW]
    for boundary in (",", ";", ". "):
        cut = chunk.find(boundary)
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
                found.append("advisory" if word != "blocking" else "blocking")
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
                        f"{path.relative_to(REPO_ROOT)}:{number} calls the {gate.key!r} "
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
                            f"{path.relative_to(REPO_ROOT)}:{number} still describes "
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
            f"{MACHINERY_DOC.relative_to(REPO_ROOT)} has no line recording that. "
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
# Part B — numbers quoted in prose vs the numbers actually enforced
# --------------------------------------------------------------------------

PERF_GATE_PATH = REPO_ROOT / "tests" / "perf" / "test_workflow_latency_percentiles.py"


def _single(pattern: str, path: Path, *, label: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, f"could not parse {label} out of {path.relative_to(REPO_ROOT)} ({pattern})"
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
                            f"{path.relative_to(REPO_ROOT)}:{number} quotes {label} as "
                            f"{'/'.join(quoted)} but the enforced value is "
                            f"{'/'.join(enforced[label])}: {line.strip()[:160]}"
                        )
    assert not problems, "prose thresholds contradict the enforced values:\n" + "\n".join(problems)
