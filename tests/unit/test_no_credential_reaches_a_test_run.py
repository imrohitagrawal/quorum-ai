"""No real credential may reach a test run, in any form.

MEASURED INCIDENT, 2026-08-07. A developer put a real
``QUORUM_EVAL_JUDGE_API_KEY`` in ``.env``. ``config.py`` loads ``.env``, and
``tests/unit/test_evaluation_judge.py`` asserted
``settings.quorum_eval_judge_api_key == ""``. The assertion failed and pytest's
assertion rewriting **printed the key in full**:

    E  AssertionError: assert 'sk-or-v1-FAKE...' == ''

From there it reached the terminal, the session transcript, and — via
``make test-report`` — ``build/test-results/pytest.xml``, whose CI sibling is an
uploaded artifact. Three amplifiers from one assertion.

**CI could never have caught it.** CI has no ``.env``, so the value is ``""``,
the assertion passes, and the leak path is not exercised. This defect could
only ever fire on a developer's machine — precisely where no gate was looking.

THE FIX IS TO REMOVE THE SECRET FROM THE PROCESS, not to hide it at the print
site. ``tests/conftest.py`` blanks every credential env var before any
``product_app`` module is imported, using the same mechanism and for the same
reason as the pre-existing ``OPENROUTER_LIVE_EXECUTION_ENABLED`` override
beside it: an explicit ``os.environ`` value beats the ``.env`` file in
pydantic-settings, so it covers BOTH sources.

Redaction hooks were considered and rejected as the primary fix: measured, a
``pytest_runtest_makereport`` scrubber works against an exported env var and
still leaks a ``.env``-only secret, because it would have to parse ``.env`` —
i.e. handle the secret in order to hide it.

WHAT TURNS EACH TEST RED is stated on the test.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from product_app.config import Settings, settings

#: Every environment variable that can carry a credential into this process.
#: Kept in sync with ``config.py`` mechanically by
#: ``test_every_credential_field_is_blanked_by_conftest`` — adding a new
#: credential field to config without adding it here fails that test.
CREDENTIAL_ENV_VARS = (
    "OPENROUTER_API_KEY",
    "TAVILY_API_KEY",
    "QUORUM_EVAL_JUDGE_API_KEY",
    "QUORUM_TOKEN_SECRET",
    "SENTRY_DSN",
)

_CONFTEST = Path(__file__).resolve().parents[1] / "conftest.py"
_CONFIG = Path(__file__).resolve().parents[2] / "src" / "product_app" / "config.py"

#: The operator's deliberate opt-in for the paid live tests (see
#: ``tests/conftest.py``). When it is set the blanking is skipped ON PURPOSE,
#: so the two runtime guards below would fire on a correct run. They skip
#: instead of failing; the STATIC guards keep running either way.
_LIVE_OPT_IN = os.environ.get("QUORUM_TEST_LIVE_CREDENTIALS", "") == "1"
_opt_in_skip = pytest.mark.skipif(
    _LIVE_OPT_IN,
    reason="QUORUM_TEST_LIVE_CREDENTIALS=1: credentials are present by explicit operator opt-in",
)

#: Assertion forms that make pytest print a credential when they fail.
#:
#: pytest's assertion rewriting reports INTERMEDIATE values, so wrapping a
#: credential in ``not``, ``len()`` or ``bool()`` does NOT hide it. MEASURED
#: 2026-08-07 on a 40-char canary, after an adversarial review refuted an
#: earlier version of this file that listed two of these as safe:
#:
#:   assert not SECRET             LEAKS  assert not 'CANARY…'
#:   assert len(SECRET) == 0       LEAKS  where 40 = len('CANARY…')
#:   assert bool(SECRET) is False  LEAKS  where True = bool('CANARY…')
#:   n = len(SECRET); assert n == 0        safe
#:   present = bool(SECRET); assert not present   safe
#:
#: The rule that falls out: REDUCE THE CREDENTIAL TO A NON-SECRET IN ITS OWN
#: STATEMENT, then assert on that. Inline wrapping never works, because the
#: rewriter walks the whole expression. Reading the code default
#: (``Settings.model_fields[...].default``) is safe for the same reason —
#: the value it yields cannot be a real credential whatever sits in ``.env``.
#:
#: The pattern therefore matches only a credential attribute appearing ON an
#: ``assert`` line, which is precisely what makes the safe two-statement form
#: pass while every inline form is caught.
#: Deliberately NOT an enumeration of wrappers. A first version allowed only
#: ``not`` and ``len(``, and ``bool(...)`` walked straight through it —
#: enumerating wrappers is a losing game, since any callable reached inline is
#: reported by the rewriter. So the rule is the general one: a credential
#: attribute must not appear ON an ``assert`` line, whatever surrounds it.
#: ``Settings.model_fields[...]`` is unaffected (capital ``S``, and the
#: attribute is ``model_fields``), and so is a non-credential setting such as
#: ``settings.max_cost_usd``.
_LEAKY_ASSERTION = re.compile(
    r"^\s*assert\b.*\bsettings\.(\w*(?:api_key|token_secret|dsn|secret))\b"
)


@_opt_in_skip
def test_no_credential_env_var_survives_into_the_test_process() -> None:
    """The primary guarantee: the secret is not here to be printed.

    WHAT TURNS THIS RED: remove the credential-blanking loop from
    ``tests/conftest.py`` while a real key sits in ``.env`` — which is exactly
    the state that produced the incident.
    """
    leaked = {name: len(os.environ.get(name, "")) for name in CREDENTIAL_ENV_VARS}
    assert not any(leaked.values()), (
        f"a credential env var is non-empty inside the test process: "
        f"{ {k: v for k, v in leaked.items() if v} } (lengths only, never values)"
    )


@_opt_in_skip
def test_the_settings_object_carries_no_credential_either() -> None:
    """Blanking the env var is only useful if ``Settings`` agrees.

    ``Settings`` reads ``.env`` as well as the environment, so this asserts the
    property that actually matters — the one the incident's assertion was
    reaching for, expressed so that a failure cannot print the value.

    WHAT TURNS THIS RED: same as above. Note the assertion reports LENGTHS,
    never values, so even its own failure output is safe.
    """
    lengths = {
        "openrouter_api_key": len(settings.openrouter_api_key),
        "tavily_api_key": len(settings.tavily_api_key),
        "quorum_eval_judge_api_key": len(settings.quorum_eval_judge_api_key),
        "sentry_dsn": len(settings.sentry_dsn),
    }
    assert not any(lengths.values()), (
        f"Settings carries a credential during tests: {lengths} (lengths only)"
    )


def test_every_credential_field_is_blanked_by_conftest() -> None:
    """The mechanical link between ``config.py`` and the blanking list.

    Rule 1a: pin what is derivable offline rather than restating it. Every
    credential field in ``config.py`` is marked ``repr=False``; every one of
    them must appear in the conftest blanking loop. Adding a sixth credential
    field therefore fails HERE until it is also blanked, rather than silently
    creating a new leak path.

    WHAT TURNS THIS RED: add a ``repr=False`` field to ``config.py`` without
    adding its env var to ``tests/conftest.py``.
    """
    config_src = _CONFIG.read_text(encoding="utf-8")
    marked = set(re.findall(r"^\s{4}(\w+): str = Field\([^)]*repr=False", config_src, re.M))
    assert marked, "no repr=False credential fields found — the detector is broken"

    conftest_src = _CONFTEST.read_text(encoding="utf-8")
    for field in sorted(marked):
        env_var = field.upper()
        assert env_var in conftest_src, (
            f"config.py marks `{field}` as a credential (repr=False) but "
            f"tests/conftest.py does not blank {env_var} — a real value there "
            "would reach the test process and could be printed on failure"
        )


def test_sentry_dsn_is_marked_as_a_credential() -> None:
    """``sentry_dsn`` is a credential and was the one field not marked as one.

    It is a URL containing a public key, and — measured during the incident
    review — a real value in ``.env`` activates a LIVE Sentry client on every
    pytest run, whose redaction hook does not cover exception or log text.

    Marking it keeps the detector above complete: the credential set becomes
    derivable from ``config.py`` rather than maintained by hand.

    WHAT TURNS THIS RED: drop ``repr=False`` from ``sentry_dsn``.
    """
    config_src = _CONFIG.read_text(encoding="utf-8")
    assert re.search(r"^\s{4}sentry_dsn: str = Field\([^)]*repr=False", config_src, re.M), (
        "sentry_dsn is no longer marked repr=False, so it drops out of the "
        "credential set that test_every_credential_field_is_blanked_by_conftest checks"
    )


def test_no_test_asserts_on_a_raw_credential_value() -> None:
    """The specific shape that caused the incident, banned repo-wide.

    Comparing a credential-bearing settings attribute against a literal makes
    pytest print the real value when it fails. Assert on
    ``Settings.model_fields[...].default``, or on a boolean, or on the LENGTH —
    never on the value.

    WHAT TURNS THIS RED: reintroduce
    ``assert settings.quorum_eval_judge_api_key == ""`` anywhere under tests/.
    """
    offenders: list[str] = []
    pattern = _LEAKY_ASSERTION
    for path in (Path(__file__).resolve().parents[1]).rglob("test_*.py"):
        # Skip this file: it carries the banned form as STRING LITERALS, which
        # is what test_the_ban_would_catch_the_original_incident asserts on.
        if path.resolve() == Path(__file__).resolve():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(
                    f"{path.relative_to(Path(__file__).resolve().parents[2])}:{lineno}"
                )
    assert not offenders, (
        "these tests compare a credential-bearing setting against a literal, so "
        "a failure prints the real value: " + ", ".join(offenders)
    )


def test_the_ban_would_catch_the_original_incident() -> None:
    """POSITIVE PARTNER (rule 7): prove the detector above is not vacuous.

    The banned line is gone from the tree, so the check has nothing to find —
    which is exactly the state in which a negative check is worthless. This
    feeds the real incident line to the same pattern and requires a match.

    The last two "offending" entries were listed as SAFE in the first version
    of this file. An adversarial review refuted that with a canary, and the
    verbatim output is quoted beside ``_LEAKY_ASSERTION``: pytest's rewriting
    prints intermediate values, so ``not`` and ``len()`` hide nothing.
    """
    pattern = _LEAKY_ASSERTION
    for offending in (
        '    assert settings.quorum_eval_judge_api_key == ""',
        '    assert settings.openrouter_api_key == ""',
        "    assert settings.tavily_api_key != 'x'",
        '    assert not settings.sentry_dsn == ""',
        # Refuted-as-safe forms — each measured printing a 40-char canary.
        "    assert not settings.openrouter_api_key",
        "    assert len(settings.openrouter_api_key) == 0",
        "    assert bool(settings.openrouter_api_key) is False",
        # The real second offender this broader pattern found in the tree,
        # at tests/integration/test_query_run_evaluation_endpoint.py:345.
        # The narrow first version of this detector missed it, because it
        # required a == or != that this line does not have.
        "    assert not settings.quorum_eval_judge_api_key",
    ):
        assert pattern.search(offending), f"the detector no longer catches: {offending!r}"

    for allowed in (
        # Reads the code default, never the live value.
        '    assert Settings.model_fields["openrouter_api_key"].default == ""',
        '    assert Settings.model_fields["sentry_dsn"].default == ""',
        # The two-statement reduction: the credential is not on the assert line.
        "    assert judge_key_present is False",
        "    assert key_length == 0",
        # Not a credential attribute at all.
        "    assert settings.max_cost_usd == 1.0",
    ):
        assert not pattern.search(allowed), f"the detector now fires on a safe form: {allowed!r}"


@pytest.mark.parametrize("field", ["openrouter_api_key", "quorum_eval_judge_api_key"])
def test_the_correct_form_of_the_default_assertion_still_works(field: str) -> None:
    """The replacement the incident's assertion should have used.

    Reads the CODE DEFAULT, which cannot be a real value whatever is in
    ``.env``. Documented here so the next author has the safe form to hand.
    """
    assert Settings.model_fields[field].default == ""
