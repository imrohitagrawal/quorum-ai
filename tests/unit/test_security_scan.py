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
# cases. This file lives under ``tests/``, which the scanner exempts, so it is
# never itself flagged.
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
        # Comments and explicit placeholder values are ignored.
        ("# openrouter_key=openrouter_key", True, False),
        ('api_key = "placeholder-value-1234"', True, False),
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
