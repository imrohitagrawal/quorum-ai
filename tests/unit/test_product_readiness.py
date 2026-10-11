"""The readiness file states facts plus a verdict (ADR-0161, decision 2; failures H1-H3).

``product_readiness.render(status, ready, generated_at)`` turns production's
``/status`` and ``/ready`` into the text of the readiness file. The verdict is
"Ready" only when live execution is on and ``/ready`` says ``ready`` with no
reasons; anything else is "Not ready" with the reasons; a missing response is
"unknown".

THE FIXTURES ARE PRODUCTION at about 2026-10-11T18:37Z UTC (one GET each of
``https://quorum-ai.fly.dev/status`` and ``/ready``, both HTTP 200), copied
verbatim. Live execution was off, so the true verdict that day was "Not ready".

The rendered file is a scoped file of the completion check (ADR-0162), so the
text must pass it: "in production" has to sit in a paragraph that cites the
build commit. That is checked by running the completion check over a clone that
holds the rendered text.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.repo_root import find_repo_root
from tests.status_clone import append_paragraph, load_script, make_clone, planted, rel

# No repo_introspection mark: ROOT comes from find_repo_root, so inside mutmut's
# ./mutants/ copy it still names the real repository, which the clone is made from.

ROOT = find_repo_root(Path(__file__))
GENERATED_AT = "2026-10-11T18:37:09Z"
READINESS_FILE = rel("docs", "product-readiness.md")

STATUS_2026_10_11: dict[str, Any] = {
    "app": "Quorum-AI",
    "version": "0.2.0",
    "build_sha": "b66b107f3f36eeaeb943ce93776b4fd4ef72095a",
    "environment": "production",
    "live_execution": False,
    "feedback_db": "connected",
    "feedback_writes": "unverified",
    "feedback_lost_billed_writes": 0,
    "feedback_events_total": 956,
    "latest_audit": None,
    "global_daily_spend_usd": "0",
    "global_daily_ceiling_usd": "5.00",
    "global_daily_simulated_spend_usd": "0",
    "last_live_charge_at": "2026-09-10T06:36:55.020418+00:00",
    "judge_enabled": True,
    "peer_critique_enabled": False,
    "source_fetch_enabled": True,
    "source_pages_in_effect": True,
    "sign_in_enabled": True,
    "session_limit_allow_list": {"active_entries": 0, "expired_entries": 0, "exempted_requests": 0},
    "invite_links": {"enabled": False, "revoked_links": 0, "requests_with_invite": 0},
    "peer_critique_in_effect": False,
    "model_catalog_loaded": True,
    "moderator_slot_overlap": [2],
    "error_tracking": "active",
    "uptime_seconds": 1068.3,
}

LIVE_REASON = (
    "OPENROUTER_LIVE_EXECUTION_ENABLED is not set to 'true'. Every query will fall back to "
    "local_simulation. Set it to 'true' in the environment (or .env) and restart to enable "
    "live execution."
)

READY_2026_10_11: dict[str, Any] = {
    "status": "ready",
    "environment": "production",
    "live_readiness": {
        "state": "offline_by_config",
        "reasons": [LIVE_REASON],
        "catalog_drift_ids": [],
        "global_spend_ceiling_reached": False,
    },
}


def _render(status: dict[str, Any] | None, ready: dict[str, Any] | None) -> str:
    module = load_script(ROOT, "product_readiness")
    return str(module.render(status, ready, GENERATED_AT))


def _live_and_ready() -> tuple[dict[str, Any], dict[str, Any]]:
    status = copy.deepcopy(STATUS_2026_10_11)
    status["live_execution"] = True
    ready = copy.deepcopy(READY_2026_10_11)
    ready["live_readiness"]["state"] = "live"
    ready["live_readiness"]["reasons"] = []
    return status, ready


def test_production_on_2026_10_11_is_not_ready_and_says_why() -> None:
    # Red when: simulated production renders "Ready", or the reason is dropped.
    text = _render(STATUS_2026_10_11, READY_2026_10_11)
    assert "Verdict: Not ready" in text, text
    assert "Verdict: Ready" not in text, text
    assert LIVE_REASON in text, text


def test_live_execution_off_is_named_even_when_ready_gives_no_reason() -> None:
    # Red when: live execution off renders "Ready" because /ready happened to list no reason.
    status = copy.deepcopy(STATUS_2026_10_11)
    ready = copy.deepcopy(READY_2026_10_11)
    ready["live_readiness"]["reasons"] = []
    text = _render(status, ready)
    assert "Verdict: Not ready" in text, text
    assert "live execution" in text.lower(), text


@pytest.mark.parametrize("what", ["status not ready", "a reason listed"])
def test_live_execution_on_is_not_enough_on_its_own(what: str) -> None:
    # Red when: "Ready" is given with /ready not "ready", or with a reason still listed.
    status, ready = _live_and_ready()
    if what == "status not ready":
        ready["status"] = "not_ready"
    else:
        ready["live_readiness"]["reasons"] = ["the model catalog has drifted"]
    text = _render(status, ready)
    assert "Verdict: Not ready" in text, text
    assert "Verdict: Ready" not in text, text


def test_live_and_ready_with_no_reasons_is_ready() -> None:
    # Red when: the one combination ADR-0161 calls ready is not rendered "Ready" (the partner).
    status, ready = _live_and_ready()
    text = _render(status, ready)
    assert "Verdict: Ready" in text, text
    assert "Verdict: Not ready" not in text, text


@pytest.mark.parametrize(
    ("has_status", "has_ready"), [(False, True), (True, False), (False, False)]
)
def test_a_missing_response_is_unavailable_and_the_verdict_unknown(
    has_status: bool, has_ready: bool
) -> None:
    # Red when: a failed fetch renders a verdict it cannot know, or no "unavailable".
    text = _render(
        STATUS_2026_10_11 if has_status else None, READY_2026_10_11 if has_ready else None
    )
    assert "unavailable" in text.lower(), text
    assert "verdict: unknown" in text.lower(), text
    assert "Verdict: Ready" not in text and "Verdict: Not ready" not in text, text


def test_the_text_names_its_build_its_time_its_lists_and_how_to_refresh() -> None:
    # Red when: the file stops saying when and from which build it was made, or how to get now.
    text = _render(STATUS_2026_10_11, READY_2026_10_11)
    assert GENERATED_AT in text, text
    assert "b66b107" in text, text
    assert "In effect in production" in text, text
    assert "Built but switched off" in text, text
    assert "GET /status" in text, text


@pytest.fixture(scope="module")
def clone(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    yield make_clone(ROOT, tmp_path_factory.mktemp("readiness") / "repo")


@pytest.mark.parametrize("case", ["not ready", "ready", "unknown"])
def test_the_rendered_text_passes_the_completion_check(clone: Path, case: str) -> None:
    # Red when: the generated file would fail make validate's completion check (an uncited
    # "in production"), online or offline.
    if case == "not ready":
        text = _render(STATUS_2026_10_11, READY_2026_10_11)
    elif case == "ready":
        text = _render(*_live_and_ready())
    else:
        text = _render(None, None)
    checker = load_script(ROOT, "check_completion_claims")
    tracked = (clone / READINESS_FILE).is_file()
    with planted(clone, {READINESS_FILE: text}, stage=() if tracked else (READINESS_FILE,)):
        problems, _counts = checker.check(clone)
    assert [p for p in problems if p.startswith(f"{READINESS_FILE}:")] == [], problems

    # PARTNER: the file is in scope, so an uncited claim added to it IS reported.
    bad, number = append_paragraph(text, "Every feature is in production.")
    with planted(clone, {READINESS_FILE: bad}, stage=() if tracked else (READINESS_FILE,)):
        problems, _counts = checker.check(clone)
    assert [p for p in problems if p.startswith(f"{READINESS_FILE}:{number}:")], problems
