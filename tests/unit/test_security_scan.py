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


@pytest.mark.parametrize(
    ("line", "is_python", "expected"),
    [
        # Keyword-argument / variable pass-throughs in Python source are not
        # secrets: the right-hand side is an already-resolved identifier or
        # attribute access, never a quoted literal.
        ("    openrouter_key=openrouter_key,", True, False),
        ("    token=confirmation.confirmation_token,", True, False),
        ("    secret=self.secret_value,", True, False),
        # A hardcoded, quoted literal in Python source IS a secret.
        ('openrouter_key = "sk-or-v1-abcdef1234567890"', True, True),
        ("api_key = 'AKIA1234567890ABCD'", True, True),
        # Unquoted / env-style assignments in non-Python files are still caught
        # (the pass-through exemption is scoped to ``.py`` files only).
        ("SECRET=abcdef123456789012", False, True),
        # Comments and explicit placeholders are ignored.
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
        ("sk-or-v1-testkey1234567890123456", False),
        # A real key with a long token still trips the scanner.
        ('KEY = "sk-or-v1-4e8a9c0b1d2e3f4a5b6c7d8e9f0a1b2c"', True),
    ],
)
def test_raw_openrouter_key_detection(line: str, expected: bool) -> None:
    assert scanner._contains_raw_openrouter_key(line) is expected
