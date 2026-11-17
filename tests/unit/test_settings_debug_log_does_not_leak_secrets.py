"""Building ``Settings`` must never write a secret value to the logs.

pydantic-settings 2.16 added a debug dump: when the ``PYDANTIC_SETTINGS_DEBUG``
environment variable is truthy and the ``pydantic_settings`` logger is enabled
for DEBUG, every source's raw values (environment, ``.env``, secret files) are
logged in one record, secrets included. A root logger at DEBUG is enough to
enable it, because that logger has no level of its own.

The secret fields are found from ``Settings.model_fields`` (every field declared
with ``repr=False``), never hand-listed, so a new secret is covered the day it
is added. Assertion messages name the leaked FIELDS only. Pytest's captured-log
section still shows the dump on a failure, but every secret value in it is one
of this file's fake values, so a failing run cannot print a real credential.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.mutmut_cwd import mutmut_can_run_in

from product_app.config import Settings

_LIBRARY_LOGGER = "pydantic_settings"


def _secret_env_names() -> dict[str, str]:
    """Field name -> environment variable name, for every ``repr=False`` field."""
    names: dict[str, str] = {}
    for field_name, field in Settings.model_fields.items():
        if field.repr:
            continue
        alias = field.validation_alias or field.alias
        env_name = alias if isinstance(alias, str) else field_name
        names[field_name] = env_name.upper()
    return names


@pytest.fixture
def fake_secrets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    """Debug dump switched on, and a unique fake value in every secret field.

    Runs from an empty directory so no real ``.env`` is ever read into the dump.
    """
    monkeypatch.chdir(mutmut_can_run_in(tmp_path))
    monkeypatch.setenv("PYDANTIC_SETTINGS_DEBUG", "1")
    values: dict[str, str] = {}
    for field_name, env_name in _secret_env_names().items():
        value = f"fake-{field_name}-7f3c9a21e4b6"
        monkeypatch.setenv(env_name, value)
        values[field_name] = value
    return values


def _leaked_fields(texts: list[str], values: dict[str, str]) -> list[str]:
    return sorted(name for name, value in values.items() if any(value in t for t in texts))


@pytest.fixture
def library_logger_forced_to_debug() -> Iterator[list[logging.LogRecord]]:
    """Force the library logger to DEBUG with its own handler, then restore it.

    Clears ``disabled`` and filters as well as the level, so whatever guard the
    app installs is bypassed for the duration of the test only.
    """
    logger = logging.getLogger(_LIBRARY_LOGGER)
    saved = (logger.level, logger.disabled, list(logger.filters), list(logger.handlers))
    records: list[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Collect(level=logging.DEBUG)
    logger.disabled = False
    logger.filters.clear()
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(saved[0])
        logger.disabled = saved[1]
        logger.filters[:] = saved[2]
        logger.handlers[:] = saved[3]


def test_secret_field_enumeration_is_not_empty() -> None:
    # Red when: no Settings field carries repr=False any more (or the
    # enumeration breaks), so the leak test below would check nothing.
    names = _secret_env_names()
    assert names, "no repr=False field found on Settings"
    assert "TAVILY_API_KEY" in names.values()


def test_building_settings_with_debug_env_and_root_at_debug_logs_no_secret(
    fake_secrets: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    # Red when: building Settings with PYDANTIC_SETTINGS_DEBUG=1 and the root
    # logger at DEBUG lets the pydantic_settings debug dump emit a secret
    # (pydantic-settings 2.16.2 with no guard in product_app.config).
    caplog.set_level(logging.DEBUG)  # root logger
    Settings()
    texts = [r.getMessage() for r in caplog.records] + [caplog.text]
    leaked = _leaked_fields(texts, fake_secrets)
    assert not leaked, f"secret values reached the log for fields: {leaked}"


def test_debug_dump_is_live_when_the_library_logger_is_forced_to_debug(
    fake_secrets: dict[str, str],
    library_logger_forced_to_debug: list[logging.LogRecord],
) -> None:
    # Red when: the installed pydantic-settings no longer has a debug dump that
    # carries source values (then the leak test above passes over a path that
    # does not exist, and this file can be retired).
    Settings()
    texts = [r.getMessage() for r in library_logger_forced_to_debug]
    assert texts, "the pydantic_settings logger emitted nothing at DEBUG"
    leaked = _leaked_fields(texts, fake_secrets)
    assert leaked == sorted(fake_secrets), f"only these fields appeared: {leaked}"
