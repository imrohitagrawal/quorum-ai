"""Guard the secret-scanner heuristics in ``scripts/security_scan.py``.

The scanner decides what counts as a leaked secret, so its false-positive
suppressions must never silently start hiding a genuine secret. These tests
lock in both directions: the known pass-through / placeholder false positives
stay ignored, and real hardcoded secrets still trip every relevant check.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_SCANNER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "security_scan.py"


def _load_scanner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("security_scan_under_test", _SCANNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so the module's dataclass can resolve its own module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scanner: Any = _load_scanner()


# A fake, well-formed key (``sk-or-v1-`` + 64 hex chars) for the "real key"
# cases.
#
# It is built by CONCATENATION, and that is load-bearing, not style. Since
# 2026-08-07 the scanner NO LONGER EXEMPTS ``tests/`` from
# ``raw_openrouter_key_pattern``, so it now reads this file like any other.
# No single SOURCE LINE here holds ``sk-or-v1-`` followed by 40+ characters,
# so nothing in it matches. Measured: the longest ``sk-or-v1-`` suffix on one
# line anywhere under ``tests/`` (excluding ``EXCLUDED_DIRS``) is 16 chars,
# against the pattern's 40-char floor. Writing this key as a single literal
# would make ``make security-scan`` fail on this very file.
_REAL_KEY = "sk-or-v1-" + "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6" * 2


@pytest.mark.parametrize(
    ("line", "is_python", "expected"),
    [
        # Keyword-argument / variable pass-throughs in Python source are not
        # secrets: the right-hand side is an already-resolved identifier or
        # attribute access, never a quoted literal.
        ("    openrouter_key=openrouter_key,", True, False),
        ("    token=confirmation.confirmation_token,", True, False),
        ("    secret=self.secret_value,", True, False),
        # A pass-through can also terminate with a closing paren.
        ("    secret=resolved_secret_value)", True, False),
        # A hardcoded, quoted literal in Python source IS a secret.
        ('openrouter_key = "sk-or-v1-abcdef1234567890"', True, True),
        ("api_key = 'AKIA1234567890ABCD'", True, True),
        # Unquoted / env-style assignments in non-Python files are still caught
        # (the pass-through exemption is scoped to ``.py`` files only) — even
        # when the RHS is identifier-shaped like a Python pass-through.
        ("SECRET=abcdef123456789012", False, True),
        ("openrouter_key=openrouter_key", False, True),
        # Comments and explicit placeholder *values* are ignored.
        ("# openrouter_key=openrouter_key", True, False),
        ('api_key = "placeholder-value-1234"', True, False),
        # ...but a genuine secret VALUE is still caught when the word
        # "placeholder" only appears elsewhere on the line (comment / name).
        ('api_key = "AKIAREALSECRET1234"  # not a placeholder', True, True),
        ("secret=AKIAREALSECRET1234  # placeholder note", False, True),
    ],
)
def test_env_secret_assignment_detection(line: str, is_python: bool, expected: bool) -> None:
    assert scanner._contains_env_secret_assignment(line, is_python=is_python) is expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        # Documentation placeholders carry no key material after the prefix.
        ('fly secrets set OPENROUTER_API_KEY="sk-or-v1-..."', False),
        ("sk-or-v1-xxx", False),
        # A real 64-char key trips the scanner...
        (f'KEY = "{_REAL_KEY}"', True),
        # ...and is still caught when the line also mentions "placeholder" or
        # "test": the check keys off the token shape, not surrounding words.
        (f'OPENROUTER_KEY_PLACEHOLDER = "{_REAL_KEY}"', True),
        (f'key = "{_REAL_KEY}"  # TODO: swap the test key for prod', True),
    ],
)
def test_raw_openrouter_key_detection(line: str, expected: bool) -> None:
    assert scanner._contains_raw_openrouter_key(line) is expected


def test_a_real_key_committed_under_tests_is_flagged(tmp_path: Path) -> None:
    """The ``tests/`` exemption removal (2026-08-07), proven end to end.

    Until this change ``_run_checks`` skipped ``raw_openrouter_key_pattern``
    for every path under ``tests/``, so a REAL key committed there sailed past
    a BLOCKING gate. The unit test above only exercises the line predicate; it
    stayed green throughout and could not see the exemption, because the
    exemption lives in the caller.

    Driven through ``_run_checks()`` — the whole gate, walking the real tree —
    rather than the predicate, since the caller is what changed.

    WHAT TURNS THIS RED: restore ``if not relative.startswith("tests/")`` in
    front of the ``_contains_raw_openrouter_key`` call in
    ``scripts/security_scan.py``.
    """
    planted = Path(scanner.ROOT) / "tests" / "unit" / "_zz_planted_key_probe.py"
    # Single literal on ONE line: this is the shape a leaked key really takes,
    # and the shape the concatenated ``_REAL_KEY`` above deliberately avoids.
    body = 'KEY = "sk-or-v1-' + "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6" * 2 + '"\n'
    planted.write_text(body, encoding="utf-8")
    try:
        findings, scanned = scanner._run_checks()
    finally:
        planted.unlink(missing_ok=True)

    assert scanned > 0, "the scanner measured nothing — a negative result would be vacuous"
    hits = [
        f
        for f in findings
        if f.check_id == "raw_openrouter_key_pattern" and "_zz_planted_key_probe" in f.path
    ]
    assert hits, (
        "a real-shaped OpenRouter key planted under tests/ was NOT flagged, so "
        "the tests/ exemption is back and a committed key would pass the gate"
    )


def test_the_tree_is_clean_once_the_planted_key_is_gone() -> None:
    """POSITIVE PARTNER (rule 7) for the test above, in the other direction.

    The check above proves the gate FIRES on a planted key. This proves it does
    not fire on the tree as committed — i.e. removing the ``tests/`` exemption
    introduced no false positive, which is the half that would break CI for
    everyone. Both halves are needed: the first alone permits a scanner that
    flags everything, the second alone permits one that flags nothing.

    WHAT TURNS THIS RED: write ``_REAL_KEY`` above as a single string literal
    instead of a concatenation.
    """
    findings, scanned = scanner._run_checks()
    assert scanned > 0, "the scanner measured nothing — this assertion would be vacuous"
    raw_key_hits = [f for f in findings if f.check_id == "raw_openrouter_key_pattern"]
    assert not raw_key_hits, (
        "removing the tests/ exemption introduced false positives: "
        + ", ".join(f"{f.path}:{f.line}" for f in raw_key_hits)
    )
