"""Enforcement-contract gate for `R2-S2-S4-ULTRACODE-PROMPT.md` (ledger FS-5).

That file is the **actual S2–S4 executable** — the text a future session pastes
to run the remaining slices. `docs/R2-comprehensive-plan.md` Part J item 6
requires the Phase-0 enforcement contract to live *there*, not only in the plan:
otherwise "Phase 0 before S2" is asserted in a document the executing agent
never reads.

These tests key the prompt against the machinery that actually exists (real
`Makefile` targets), so the prompt cannot satisfy the gate by naming a gate that
was never built — the same both-directions discipline as
`tests/test_r2_plan_status_honesty.py`.

They are also **structurally scoped**, not keyword matching over the whole
document: a review found that a 295-byte stub which merely contained the magic
phrases — while telling the agent to ignore the contract — passed every
assertion. So each requirement is asserted *where it has to live*: the required
gate commands inside the Precondition's runnable block AND inside the per-slice
DoD checklist, the bounded-loop and advisory-threshold rules inside their own
prime directive, the docs-before-code paths inside the S2 slice. Gutting or
rewriting the executable now turns the gate RED.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPT = REPO_ROOT / "R2-S2-S4-ULTRACODE-PROMPT.md"
MAKEFILE = REPO_ROOT / "Makefile"

# Part J item 6(b): the per-slice DoD must name these real gate commands rather
# than the unfalsifiable "all gates green".
REQUIRED_GATE_TARGETS = (
    "validate",
    "fr-completeness",
    "perf-gate",
    "api-contract",
    "diff-cover",
    "mutation-baseline",
)

# The executable's load-bearing shape. Wholesale replacement must be RED.
REQUIRED_SECTIONS = (
    ("precondition", r"(?i)precondition"),
    ("prime directives", r"(?i)prime directives"),
    ("slice S2", r"(?i)slice\s+S2\b"),
    ("slice S3", r"(?i)slice\s+S3\b"),
    ("slice S4", r"(?i)slice\s+S4\b"),
    ("definition of done", r"(?i)definition of done"),
)


@pytest.fixture(scope="module")
def prompt_text() -> str:
    return PROMPT.read_text(encoding="utf-8")


def _makefile_targets() -> set[str]:
    return set(re.findall(r"^([a-z][a-z0-9_-]*):", MAKEFILE.read_text(encoding="utf-8"), re.M))


def _sections(prompt_text: str) -> list[tuple[str, str]]:
    """(heading, body) for every `##`/`###` section, in document order."""
    parts = re.split(r"(?m)^(#{2,3})\s+(.*)$", prompt_text)
    # parts = [preamble, hashes, heading, body, hashes, heading, body, ...]
    return [(parts[i + 1], parts[i + 2]) for i in range(1, len(parts) - 2, 3)]


def _section_body(prompt_text: str, heading_pattern: str) -> str | None:
    for heading, body in _sections(prompt_text):
        if re.search(heading_pattern, heading):
            return body
    return None


def _numbered_items(body: str) -> list[str]:
    """Split a numbered directive list into one string per `N.` item."""
    items: list[str] = []
    current: list[str] | None = None
    for line in body.splitlines():
        if re.match(r"^\d+\.\s", line):
            if current is not None:
                items.append("\n".join(current))
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        items.append("\n".join(current))
    return items


def _bullet_lines(body: str) -> list[str]:
    """Checklist/bullet lines of a section, each joined with its continuations."""
    lines: list[str] = []
    current: list[str] | None = None
    for line in body.splitlines():
        if re.match(r"^\s*[-*]\s", line):
            if current is not None:
                lines.append(" ".join(current))
            current = [line.strip()]
        elif current is not None and line.strip():
            current.append(line.strip())
        elif current is not None:
            lines.append(" ".join(current))
            current = None
    if current is not None:
        lines.append(" ".join(current))
    return lines


def _named_make_targets(text: str) -> set[str]:
    """Every `make <target>` the text tells the executing agent to run."""
    return set(re.findall(r"\bmake ([a-z][a-z0-9_-]*)", text))


@pytest.mark.parametrize("label,pattern", REQUIRED_SECTIONS, ids=[s[0] for s in REQUIRED_SECTIONS])
def test_executable_keeps_its_structural_shape(prompt_text: str, label: str, pattern: str) -> None:
    """A gutted/rewritten S2-S4 executable must not satisfy the contract (FS-5)."""
    assert _section_body(prompt_text, pattern) is not None, (
        f"R2-S2-S4-ULTRACODE-PROMPT.md has no `{label}` section — the S2-S4 "
        "executable has been replaced or gutted, so the Phase-0 enforcement "
        "contract no longer binds the executing agent (FS-5)"
    )


def test_phase_zero_is_a_literal_precondition(prompt_text: str) -> None:
    """FS-5(a): S2 may not start until the Phase-0 gates exist and are RED-proven."""
    body = _section_body(prompt_text, r"(?i)precondition")
    assert body is not None, "no Phase-0 precondition section in the S2-S4 executable"
    assert re.search(r"Phase[- ]0", body), (
        "the precondition section never mentions Phase 0 — the enforcement "
        "contract is absent from the file that actually executes S2-S4 (FS-5)."
    )
    # The precondition must be checked by RUNNING the gates, not by reading a plan.
    assert re.search(r"(?i)RED[- ]proven|proven RED", body), (
        "the Phase-0 precondition does not require the gates to be RED-proven"
    )


def test_precondition_is_a_runnable_command_list(prompt_text: str) -> None:
    """FS-5(a): the precondition is satisfied by *running* gates, so it ships commands."""
    body = _section_body(prompt_text, r"(?i)precondition")
    assert body is not None, "no Phase-0 precondition section in the S2-S4 executable"
    blocks = re.findall(r"(?ms)^```(?:bash|sh|console)\n(.*?)^```", body)
    assert blocks, (
        "the Phase-0 precondition has no runnable command block — it can only be "
        "satisfied by believing a document, which is exactly what FS-5 forbids"
    )
    ran = _named_make_targets("\n".join(blocks))
    missing = sorted(set(REQUIRED_GATE_TARGETS) - ran)
    assert not missing, (
        f"the precondition's command block never runs: {missing} — the executing "
        "agent could declare Phase 0 complete without exercising those gates"
    )


@pytest.mark.parametrize("target", REQUIRED_GATE_TARGETS)
def test_dod_names_the_required_gate_command(prompt_text: str, target: str) -> None:
    """FS-5(b): the DoD names each real gate, not the unfalsifiable "all gates green"."""
    body = _section_body(prompt_text, r"(?i)definition of done")
    assert body is not None, "the S2-S4 executable has no Definition of Done section"
    named = {t for line in _bullet_lines(body) for t in _named_make_targets(line)}
    assert target in named, (
        f"the DoD checklist never tells the agent to run `make {target}` — its "
        'DoD stays unfalsifiable ("all gates green")'
    )


def test_every_named_make_target_exists(prompt_text: str) -> None:
    """A named gate that the Makefile does not define is worse than none."""
    missing = sorted(_named_make_targets(prompt_text) - _makefile_targets())
    assert not missing, (
        f"the prompt names make target(s) the Makefile does not define: {missing} "
        "— the DoD would point at a gate that does not exist"
    )


def test_bounded_review_loop(prompt_text: str) -> None:
    """FS-7: the review-fixpoint loop is bounded with a human override."""
    body = _section_body(prompt_text, r"(?i)prime directives")
    assert body is not None, "the S2-S4 executable has no prime-directives section"
    bounded = [
        item
        for item in _numbered_items(body)
        if re.search(r"(?i)max(?:imum)?\W{0,3}3\s+(?:review\s+)?rounds", item)
    ]
    assert bounded, (
        "no prime directive bounds the review loop at max 3 rounds (FS-7) — it can run forever"
    )
    assert any(re.search(r"(?i)human override|escalate", item) for item in bounded), (
        "the bounded review loop has no human-override/escalation exit (FS-7)"
    )


def test_s2_thresholds_are_advisory_until_s4(prompt_text: str) -> None:
    """FS-6: S2 ships thresholds advisory/OFF until the S4 golden set calibrates them."""
    body = _section_body(prompt_text, r"(?i)prime directives")
    assert body is not None, "the S2-S4 executable has no prime-directives section"
    advisory = [
        item
        for item in _numbered_items(body)
        if re.search(r"(?is)advisory.{0,200}?until.{0,200}?S4|advisory.{0,400}?S4", item)
    ]
    assert advisory, (
        "no prime directive states that every S2 threshold ships advisory "
        "until calibrated after S4 (FS-6)"
    )
    assert any(re.search(r"(?i)non-blocking|never used to fail|OFF", item) for item in advisory), (
        "the advisory-threshold directive never says the threshold is non-blocking in S2 (FS-6)"
    )


def test_s2_docs_before_code(prompt_text: str) -> None:
    """FS-9: the mandatory AGENTS.md docs land before the S2 judge code."""
    scopes = [
        body
        for heading, body in _sections(prompt_text)
        if re.search(r"(?i)slice\s+S2\b", heading) or re.search(r"(?i)prime directives", heading)
    ]
    assert scopes, "the S2-S4 executable has no Slice S2 / prime-directives section"
    for doc in ("docs/40", "docs/42", "docs/20", "docs/21"):
        assert any(doc in body for body in scopes), (
            f"S2's docs-before-code requirement omits {doc} (FS-9)"
        )
    assert any(
        re.search(r"(?i)docs before code|docs \(first|before\*\* the S2 judge code", body)
        for body in scopes
    ), "nothing states the docs land BEFORE the S2 judge code (FS-9)"
