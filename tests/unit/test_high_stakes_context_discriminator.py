"""Issue #155 — high-stakes wording in ``context`` must not skip the ack.

Two failure directions, and a fix that closes only one of them is worse than
no fix. Both are asserted here, deliberately side by side:

* **The bypass.** ``required_warnings_for_query`` scanned ``query_text``
  only, while both ``context`` values reach a provider prompt
  (``prior_question`` the system message, ``prior_synthesis`` the synthesis
  user message since WP-G2). So high-stakes wording moved into ``context``
  skipped the acknowledgement entirely.
* **The naive fix, which was shipped and then reverted in review.** Scanning
  the context wholesale makes EVERY legitimate follow-up demand a
  ``high_stakes`` ack, because this app's own mandated caveat sentence
  matches the pattern five times — MEASURED here, not assumed. A client
  re-sending this app's own synthesis is the normal case, so that fix made
  the feature unusable.

The discriminator therefore removes THIS APP'S OWN caveat sentence before
scanning, and nothing else. The evasion that shape invites — appending the
caveat marker to a hostile sentence to get it stripped — is asserted closed
below, because a strip keyed on "any sentence mentioning the marker" would
hand the attacker a better bypass than the one being fixed.
"""

from __future__ import annotations

import pytest

from product_app.safety import (
    HIGH_STAKES_PATTERN,
    WarningType,
    safety_warning_policy,
    strip_own_caveat,
)
from product_app.synthesis import HIGH_STAKES_NOTICE_FRAGMENT

_BENIGN = "Follow up on the earlier discussion please."
_HOSTILE = "What is the right medical diagnosis and legal contract for my investment loan?"


def _types(query_text: str, context: dict[str, str] | None = None) -> set[WarningType]:
    return {
        w.warning_type
        for w in safety_warning_policy.required_warnings_for_query(query_text, context=context)
    }


def _real_synthesis(body: str = "The models agree the rollout succeeded.") -> str:
    """A realistic prior synthesis: ordinary prose plus the mandated caveat.

    ``synthesis_length`` guarantees the caveat is present in 100% of
    recommendations, so this is the shape of every real follow-up, not an
    edge case.
    """
    return f"{body} {HIGH_STAKES_NOTICE_FRAGMENT}"


# ---------------------------------------------------------------------------
# The measurement the naive fix failed
# ---------------------------------------------------------------------------


def test_the_apps_own_caveat_matches_the_high_stakes_pattern_five_times() -> None:
    """The premise the whole design rests on, measured rather than asserted.

    If this ever stops being true the discriminator below is solving a
    problem that no longer exists, and someone should find out from a red
    test rather than by reading.
    """
    assert HIGH_STAKES_PATTERN.findall(HIGH_STAKES_NOTICE_FRAGMENT) == [
        "medical",
        "legal",
        "financial",
        "safety",
        "regulated",
    ]


def test_a_legitimate_follow_up_carrying_this_apps_own_synthesis_needs_no_high_stakes_ack() -> None:
    """The regression the reverted fix caused: step 1 create 202, step 2 create
    422, with no hostile input anywhere.

    Turns red if: the context is scanned without removing the app's own
    caveat first.
    """
    types = _types(_BENIGN, {"prior_synthesis": _real_synthesis()})
    assert WarningType.HIGH_STAKES not in types, (
        "re-sending this app's own synthesis must not demand a high-stakes ack"
    )
    assert WarningType.SENSITIVE_DATA in types


def test_the_caveat_is_also_ignored_in_prior_question() -> None:
    """Both context fields reach a prompt, so both get the same treatment."""
    assert WarningType.HIGH_STAKES not in _types(_BENIGN, {"prior_question": _real_synthesis()})


# ---------------------------------------------------------------------------
# The bypass itself
# ---------------------------------------------------------------------------


def test_high_stakes_wording_in_prior_synthesis_still_requires_the_ack() -> None:
    """The bypass, closed. Demonstrated in the issue as: benign query_text +
    hostile prior_synthesis -> 202 Accepted, run executes.

    Turns red if: ``context`` is dropped from the scan.
    """
    assert WarningType.HIGH_STAKES in _types(_BENIGN, {"prior_synthesis": _HOSTILE})


def test_high_stakes_wording_in_prior_question_still_requires_the_ack() -> None:
    """The half that was live before WP-G2 too."""
    assert WarningType.HIGH_STAKES in _types(_BENIGN, {"prior_question": _HOSTILE})


def test_hostile_wording_survives_alongside_the_apps_own_caveat() -> None:
    """The realistic attack: send a real synthesis AND hostile wording.

    Stripping the caveat must not take the hostile sentence with it.
    """
    context = {"prior_synthesis": f"{_real_synthesis()} I need a medical diagnosis."}
    assert WarningType.HIGH_STAKES in _types(_BENIGN, context)


def test_appending_the_caveat_marker_to_a_hostile_sentence_does_not_hide_it() -> None:
    """The evasion a sentence-level strip would have created.

    If the discriminator removed any SENTENCE containing "decision support
    only", an attacker would simply append that phrase to their hostile
    sentence and get the whole thing deleted before the scan — a cleaner
    bypass than the one this issue exists to fix.

    Turns red if: the strip matches on the marker alone rather than on the
    app's caveat as a complete, self-terminating sentence.
    """
    context = {
        "prior_synthesis": (
            "I need a medical diagnosis and a legal contract, decision support only."
        )
    }
    assert WarningType.HIGH_STAKES in _types(_BENIGN, context)


def test_a_caveat_with_extra_trailing_words_is_not_treated_as_the_apps_own() -> None:
    """Same evasion, dressed as the real caveat with a tail bolted on.

    The strip is anchored to end at ``advice.``; anything continuing past it
    is not this app's sentence and must stay visible to the scan.
    """
    context = {
        "prior_synthesis": (
            "This summary is decision support only and is not medical, legal, "
            "financial, safety, or regulated professional advice for my lawsuit."
        )
    }
    assert WarningType.HIGH_STAKES in _types(_BENIGN, context)


# ---------------------------------------------------------------------------
# Behaviour that must not change
# ---------------------------------------------------------------------------


def test_query_text_scanning_is_unchanged() -> None:
    """The pre-existing contract, both directions, so the context work cannot
    quietly weaken the original scan."""
    assert WarningType.HIGH_STAKES in _types(_HOSTILE)
    assert WarningType.HIGH_STAKES not in _types(_BENIGN)


def test_no_context_behaves_exactly_as_before() -> None:
    """``context=None`` and an absent argument must agree — the parameter is
    additive, and every existing caller passes neither."""
    assert _types(_BENIGN, None) == _types(_BENIGN)
    assert _types(_HOSTILE, None) == _types(_HOSTILE)


@pytest.mark.parametrize("junk", [{}, {"prior_question": ""}, {"prior_synthesis": None}])
def test_empty_or_missing_context_values_are_harmless(junk: dict[str, str | None]) -> None:
    """A client may send a partial context. None of these shapes may raise,
    and none may invent a high-stakes requirement."""
    assert WarningType.HIGH_STAKES not in _types(_BENIGN, junk)  # type: ignore[arg-type]


def test_unknown_context_keys_are_still_scanned() -> None:
    """Fail SAFE on a field this code does not know about.

    A future context key that reaches a prompt must not become a silent
    bypass just because this function predates it. Scanning every string
    value costs nothing and cannot go stale.

    Turns red if: the scan is keyed on a hardcoded list of context keys.
    """
    assert WarningType.HIGH_STAKES in _types(_BENIGN, {"some_future_field": _HOSTILE})


# ---------------------------------------------------------------------------
# The stripper on its own
# ---------------------------------------------------------------------------


def test_strip_own_caveat_removes_the_exact_sentence() -> None:
    assert "decision support only" not in strip_own_caveat(_real_synthesis()).lower()


def test_strip_own_caveat_tolerates_comma_and_wording_drift_inside_the_sentence() -> None:
    """``synthesis_length`` keys on a substring precisely because the LLM may
    reword; the stripper has to be at least as tolerant or a reworded caveat
    reintroduces the false 422."""
    reworded = (
        "This summary is decision support only, and is not medical, legal, "
        "financial, safety or other regulated professional advice."
    )
    assert "decision support only" not in strip_own_caveat(reworded).lower()


def test_strip_own_caveat_leaves_ordinary_prose_untouched() -> None:
    """The positive partner: a stripper that returned "" would satisfy every
    removal test above."""
    prose = "The models agree the rollout succeeded and error rates are flat."
    assert strip_own_caveat(prose) == prose


def test_strip_own_caveat_handles_an_empty_string() -> None:
    """No guard exists for this — ``re.sub`` handles it — so pin that it
    really does, rather than leaving the claim in a docstring only."""
    assert strip_own_caveat("") == ""
