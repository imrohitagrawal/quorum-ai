"""Review round 2 of package B (one status): a regression test for each reproduced finding.

ADR-0161 and ADR-0162. Each section names the finding it pins. Every test was
run against the code BEFORE its fix and its failure recorded.

1. The status-field negation "<word>: no" was a prefix, so "Merged: no doubt."
   and "In production: no issues detected." were read as negations. It is a
   negation only when "no" or "not yet" is the WHOLE field value.
2. A line break hidden inside an image (its alt text) or inside an inline
   link's destination-and-title part did not move the line counter, so a later
   claim was credited to an earlier line, possibly one written before the
   cut-off, and so never checked.
3. Production reports ``build_sha`` "unknown" when ``BUILD_SHA`` is unset; the
   readiness file then wrote an uncited "in production at build unknown".
4. Readiness labels said "(in effect)" under the idle and switched-off headings.
5. A production build that holds the last ``src/`` commit but is not on main (a
   hotfix) was called "in sync".
6. ``_gather_live_state`` passing ``main_tip`` and the ancestry answers to the
   build line was untested.

GATE CHARTER
------------
WHY THIS EXISTS: review round 2 of package B reproduced each of these with an
input that every existing test accepted.

WHAT IT CANNOT SEE: wordings and Markdown shapes other than the ones here.

FALSE-POSITIVE COST: none beyond the checks under test.

WHEN TO REMOVE: with the checks under test.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import pytest
from tests.repo_root import find_repo_root
from tests.status_clone import load_script

ROOT = find_repo_root(Path(__file__))


def _completion() -> Any:
    return load_script(ROOT, "check_completion_claims")


class _NoCitation:
    """A citation source that supports nothing, so every counted claim is reported."""

    def supports(self, _text: str) -> bool:
        return False

    def fetch_hint(self, _text: str) -> str:
        return ""


def _reported(text: str, lines: set[int]) -> tuple[list[tuple[int, str]], int]:
    """(line, word) for every claim reported on ``lines``, and how many claims were counted."""
    problems, claims = _completion().problems_in_text("x.md", text, lines, _NoCitation())
    found = []
    for problem in problems:
        match = re.match(r"x\.md:(\d+): '([^']+)'", problem)
        assert match, problem
        found.append((int(match.group(1)), match.group(2).lower()))
    return sorted(found), claims


# ---------------------------------------------------------------------------
# 1. "<word>: no" is a negation only as the whole field value.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "word"),
    [
        ("Merged: no doubt.", "merged"),
        ("In production: no issues detected.", "in production"),
        ("Verified: no regressions in the e2e lane.", "verified"),
        ("W55 and W56 merged: no conflicts.", "merged"),
        ("Release 1 is complete: no open blockers.", "complete"),
    ],
)
def test_a_field_value_that_only_starts_with_no_is_a_claim(text: str, word: str) -> None:
    # Red when: "<word>: no" or "<word>: not yet" cancels the word although more words follow
    # "no" in the same field ("Merged: no doubt.").
    assert _reported(text, {1}) == ([(1, word)], 1)


@pytest.mark.parametrize(
    "text",
    ["Merged: no.", "Merged: not yet", "Pushed: yes. Merged: no. In production: no."],
)
def test_a_field_whose_whole_value_is_no_is_not_a_claim(text: str) -> None:
    # Red when: "Merged: no." or "Merged: not yet", the whole field value, stops being a negation.
    assert _reported(text, {1}) == ([], 0)


# ---------------------------------------------------------------------------
# 2. Line breaks hidden inside images and inline links still count.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "changed", "expected"),
    [
        # The orchestrator's reproduction: a line break between the destination and the title.
        (
            '[W55](https://example.org\n"title") merged and in production.',
            {2},
            [(2, "in production"), (2, "merged")],
        ),
        # A line break inside the title itself.
        ('[W55](https://example.org "a\nb") merged.', {2}, [(2, "merged")]),
        # A line break in the link text and another before the title.
        ('[W\n55](https://example.org\n"t") merged.', {3}, [(3, "merged")]),
        # The reviewer's image: a line break inside the alt text.
        ("old ![a\nb](x.png) old\nmerged new", {3}, [(3, "merged")]),
        # Two wrapped images on the way to the claim.
        ("old ![a\nb](x.png) and ![c\nd](y.png)\nmerged new", {4}, [(4, "merged")]),
    ],
)
def test_a_line_break_inside_an_image_or_link_moves_later_claims_down(
    text: str, changed: set[int], expected: list[tuple[int, str]]
) -> None:
    # Red when: a line break inside an image's alt text or an inline link's destination-and-title
    # is not counted, so a claim after it is credited to an earlier, unchanged line.
    assert _reported(text, changed) == (expected, len(expected))


def test_an_old_claim_before_a_wrapped_image_stays_exempt() -> None:
    # Red when: the line counter jumps too far, so a claim on an unchanged line BEFORE a wrapped
    # image is credited to a later, changed line. The partner shows the same claim is seen.
    text = "W54 merged ![a\nb](x.png)\nnew text"
    assert _reported(text, {2, 3}) == ([], 0)
    assert _reported(text, {1}) == ([(1, "merged")], 1)


def test_a_reference_link_title_does_not_move_the_line() -> None:
    # Red when: a line break in a reference definition's title is counted at the place the
    # reference is used, so the claim beside it moves off its own line.
    text = '[W55][r] merged.\n\n[r]: https://example.org "a\nb"'
    assert _reported(text, {1}) == ([(1, "merged")], 1)
    assert _reported(text, {2, 3, 4}) == ([], 0)


# ---------------------------------------------------------------------------
# 3. A build production did not report is named as a gap, not "in production".
# ---------------------------------------------------------------------------

GENERATED_AT = "2026-10-11T18:37:09Z"

#: Production on 2026-10-11, trimmed to the keys the render reads (literal).
STATUS: dict[str, Any] = {
    "app": "Quorum-AI",
    "version": "0.2.0",
    "build_sha": "b66b107f3f36eeaeb943ce93776b4fd4ef72095a",
    "environment": "production",
    "live_execution": False,
    "judge_enabled": True,
    "peer_critique_enabled": False,
    "source_fetch_enabled": True,
    "source_pages_in_effect": True,
    "sign_in_enabled": True,
    "peer_critique_in_effect": False,
}
READY: dict[str, Any] = {
    "status": "ready",
    "environment": "production",
    "live_readiness": {
        "state": "offline_by_config",
        "reasons": ["OPENROUTER_LIVE_EXECUTION_ENABLED is not set to 'true'."],
        "catalog_drift_ids": [],
        "global_spend_ceiling_reached": False,
    },
}


def _readiness() -> Any:
    return load_script(ROOT, "product_readiness")


def _prose(text: str) -> str:
    return re.sub(r"```json\n.*?\n```", "", text, flags=re.DOTALL)


@pytest.mark.parametrize("build", ["unknown", None])
def test_an_unreported_build_is_named_as_a_gap(build: str | None) -> None:
    # Red when: with /status.build_sha "unknown" (BUILD_SHA unset) or missing, the readiness file
    # writes "in production" with no commit to cite, which the completion check refuses.
    status = copy.deepcopy(STATUS)
    if build is None:
        del status["build_sha"]
    else:
        status["build_sha"] = build
    module = _readiness()
    text = str(module.render(status, READY, GENERATED_AT))
    assert "production did not report its build" in _prose(text), text
    problems, _claims = _completion().problems_in_text(
        "docs/product-readiness.md", text, range(1, len(text.splitlines()) + 1), _NoCitation()
    )
    assert problems == [], problems
    # The verdict logic is unchanged.
    assert module.verdict(status, READY) == module.verdict(STATUS, READY)
    # PARTNER: with a known build, the file does say "in production", and the same check counts
    # it (here against a citation source that supports nothing).
    known = str(module.render(STATUS, READY, GENERATED_AT))
    assert "In effect in production at build b66b107" in known, known
    problems, claims = _completion().problems_in_text(
        "docs/product-readiness.md", known, range(1, len(known.splitlines()) + 1), _NoCitation()
    )
    assert claims > 0 and problems, (claims, problems)


# ---------------------------------------------------------------------------
# 4. Labels read true under their headings.
# ---------------------------------------------------------------------------

IDLE_HEADING = "Built and switched on, but idle while live execution is off: no run reaches them"


def _section(text: str, heading_start: str) -> str:
    match = re.search(rf"^## {re.escape(heading_start)}.*?(?=^## |\Z)", text, re.M | re.S)
    assert match, f"no section starting {heading_start!r}:\n{text}"
    return match.group(0)


def _labels(section: str) -> dict[str, str]:
    """``key -> label`` for every switch line ``- <label> (`key`)`` in ``section``."""
    return dict(
        (m.group(2), m.group(1)) for m in re.finditer(r"^- (.*) \(`([\w.]+)`\)$", section, re.M)
    )


def test_no_label_says_in_effect_under_the_idle_or_switched_off_heading() -> None:
    # Red when: a switch listed as idle ("Source pages read (in effect)") or switched off
    # ("Peer critique (in effect)") is labelled "in effect".
    text = str(_readiness().render(STATUS, READY, GENERATED_AT))
    idle = _labels(_section(text, IDLE_HEADING))
    off = _labels(_section(text, "Built but switched off"))
    # PARTNER: the two switches the finding named are in those sections.
    assert "source_pages_in_effect" in idle, idle
    assert "peer_critique_in_effect" in off, off
    for key, label in {**idle, **off}.items():
        assert "in effect" not in label.lower(), (key, label)


# ---------------------------------------------------------------------------
# 5 and 6. A hotfix build not on main is not "in sync", and the wiring is tested.
# ---------------------------------------------------------------------------

SRC = "a" * 40
BUILD = "b" * 40
TIP = "c" * 40


def _handoff() -> Any:
    return load_script(ROOT, "session_handoff")


def test_a_build_holding_the_last_src_commit_but_not_on_main_is_named() -> None:
    # Red when: a production build that holds the last src/ commit but is not on main (a hotfix
    # deployed from a branch) is called "in sync".
    module = _handoff()
    line = module._build_sha_drift_line(
        last_src_commit=SRC,
        prod_build_sha=BUILD,
        main_tip=TIP,
        src_commit_in_build=True,
        build_on_main=False,
    )
    assert "in sync" not in line.lower(), line
    assert f"production build_sha {BUILD[:7]} is not on main" in line, line
    # PARTNER: the same build on main is in sync.
    on_main = module._build_sha_drift_line(
        last_src_commit=SRC,
        prod_build_sha=BUILD,
        main_tip=TIP,
        src_commit_in_build=True,
        build_on_main=True,
    )
    assert "in sync" in on_main.lower() and "not on main" not in on_main, on_main


def test_gather_live_state_passes_the_tip_and_both_ancestry_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Red when: _gather_live_state stops passing main_tip, the "build holds the last src/ commit"
    # answer, or the "build is on main" answer to _build_sha_drift_line.
    module = _handoff()

    def fake_run(cmd: list[str]) -> str:
        if cmd[:2] == ["git", "rev-parse"]:
            return TIP
        if cmd[:2] == ["git", "log"]:
            return SRC
        return "unavailable: stub"

    asked: list[tuple[str, str]] = []
    answers = {(SRC, BUILD): True, (BUILD, TIP): False}

    def fake_is_ancestor(older: str, newer: str, root: Path = ROOT) -> bool:
        asked.append((older, newer))
        return answers.get((older, newer), False)

    seen: dict[str, Any] = {}
    real_line = module._build_sha_drift_line

    def spy(**kwargs: Any) -> str:
        seen.update(kwargs)
        return str(real_line(**kwargs))

    monkeypatch.setattr(module, "run", fake_run)
    monkeypatch.setattr(module, "_fetch_prod_build_sha", lambda *a, **k: BUILD)
    monkeypatch.setattr(module, "_is_ancestor", fake_is_ancestor)
    monkeypatch.setattr(module, "_build_sha_drift_line", spy)
    state = module._gather_live_state()
    assert sorted(asked) == sorted(answers), asked
    assert seen == {
        "last_src_commit": SRC,
        "prod_build_sha": BUILD,
        "main_tip": TIP,
        "src_commit_in_build": True,
        "build_on_main": False,
    }, seen
    assert "not on main" in state["build_sha_drift_line"], state["build_sha_drift_line"]
