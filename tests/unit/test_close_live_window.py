"""#407: closing a live-execution window has one atomic command, not a two-part
deduction under incident pressure.

Background: the obvious revert (flip the flag, leave the window's ``expires_at``
alone) is refused by
``test_the_shipped_declaration_file_declares_no_window_right_now`` — a window
covering ``now`` may not be committed while the flag is off. The only valid
single-commit form is flag -> "false" AND the open window's ``expires_at`` ->
now, together. This module is that command, built so the two edits cannot be
half-applied.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "close_live_window.py"

_NOW = dt.datetime(2026, 9, 1, 12, 0, tzinfo=dt.UTC)
_NOW_ISO = "2026-09-01T12:00:00+00:00"
_OPEN_START = "2026-09-01T09:00:00Z"
_OPEN_END = "2026-09-01T17:00:00Z"
_EXPIRED_START = "2026-08-19T09:00:00Z"
_EXPIRED_END = "2026-08-19T17:00:00Z"
_FUTURE_START = "2026-09-05T09:00:00Z"
_FUTURE_END = "2026-09-05T17:00:00Z"


@pytest.fixture(scope="module")
def closer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("close_live_window_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _window(*, opened: str, expires: str | None, mode: str = "time_boxed") -> dict[str, Any]:
    entry: dict[str, Any] = {
        "owner": "rohit",
        "reason": "test window",
        "mode": mode,
        "judge": False,
        "opened_at": opened,
    }
    if expires is not None:
        entry["expires_at"] = expires
    else:
        entry["adr"] = "ADR-0099"
    return entry


# --- find_open_windows -------------------------------------------------------


def test_find_open_windows_selects_a_covering_time_boxed_entry(closer: ModuleType) -> None:
    """RED IF: an entry whose span covers ``now`` stops being selected — the
    script would then report "nothing to close" while a window is genuinely
    open, which is silent failure at exactly the moment #407 was about."""
    payload = {"windows": [_window(opened=_OPEN_START, expires=_OPEN_END)]}
    found = closer.find_open_windows(payload, _NOW)
    assert len(found) == 1
    assert found[0]["opened_at"] == _OPEN_START


def test_find_open_windows_excludes_an_expired_entry(closer: ModuleType) -> None:
    """POSITIVE PARTNER for the test above: without this, "select everything"
    would also pass it. RED IF: expiry stops being checked."""
    payload = {"windows": [_window(opened=_EXPIRED_START, expires=_EXPIRED_END)]}
    assert closer.find_open_windows(payload, _NOW) == []


def test_find_open_windows_excludes_a_not_yet_started_entry(closer: ModuleType) -> None:
    """RED IF: only the expiry bound is checked and the opening bound is
    dropped, so a future-dated window is treated as already open."""
    payload = {"windows": [_window(opened=_FUTURE_START, expires=_FUTURE_END)]}
    assert closer.find_open_windows(payload, _NOW) == []


def test_find_open_windows_excludes_a_standing_entry(closer: ModuleType) -> None:
    """A standing window has no ``expires_at`` to close — the closer must not
    touch it. RED IF: the standing exclusion is dropped, since the entry has
    no ``expires_at`` key at all and writing one would corrupt the window's
    shape (``expires_at`` is FORBIDDEN for ``standing`` per the file's README)."""
    payload = {"windows": [_window(opened=_OPEN_START, expires=None, mode="standing")]}
    assert closer.find_open_windows(payload, _NOW) == []


def test_find_open_windows_excludes_standing_even_with_a_stray_expires_at(
    closer: ModuleType,
) -> None:
    """A real ``standing`` entry never carries ``expires_at`` (the file's own
    README forbids it), so the test above is satisfied by the missing-expiry
    branch alone and never actually exercises the ``mode == MODE_STANDING``
    check. This gives that entry a (malformed) ``expires_at`` anyway so the
    mode check is the thing keeping it excluded. RED IF: the ``mode ==
    MODE_STANDING`` skip is deleted — this is the mutation the test above
    cannot see."""
    payload = {
        "windows": [
            {**_window(opened=_OPEN_START, expires=None, mode="standing"), "expires_at": _OPEN_END}
        ]
    }
    assert closer.find_open_windows(payload, _NOW) == []


def test_find_open_windows_returns_every_covering_entry(closer: ModuleType) -> None:
    """RED IF: the function stops after the first match, e.g. via ``next()``
    instead of a full scan — two open windows must both be reported."""
    payload = {
        "windows": [
            _window(opened=_OPEN_START, expires=_OPEN_END),
            {**_window(opened=_OPEN_START, expires=_OPEN_END), "owner": "other"},
        ]
    }
    assert len(closer.find_open_windows(payload, _NOW)) == 2


# --- close_windows ------------------------------------------------------------


def test_close_windows_stamps_expires_at_to_now(closer: ModuleType) -> None:
    """RED IF: the stamped value is not ``now`` (e.g. left unchanged, or the
    wrong window's field is written) — the whole point is the entry no longer
    covers ``now`` afterward."""
    payload = {"windows": [_window(opened=_OPEN_START, expires=_OPEN_END)]}
    closed = closer.close_windows(payload, _NOW)
    assert len(closed) == 1
    assert payload["windows"][0]["expires_at"] == closer._parse_instant(
        payload["windows"][0]["expires_at"]
    ).isoformat().replace("+00:00", "Z")
    # And the window is no longer open at the instant it was closed at.
    assert closer.find_open_windows(payload, _NOW) == []


def test_close_windows_leaves_other_fields_untouched(closer: ModuleType) -> None:
    """RED IF: the closer rewrites the whole entry rather than one field — the
    file's README says "leave expired entries in place" as the record of what
    was sanctioned, so owner/reason/judge must survive verbatim."""
    payload = {"windows": [_window(opened=_OPEN_START, expires=_OPEN_END)]}
    closer.close_windows(payload, _NOW)
    entry = payload["windows"][0]
    assert entry["owner"] == "rohit"
    assert entry["reason"] == "test window"
    assert entry["judge"] is False


def test_close_windows_is_a_noop_when_nothing_is_open(closer: ModuleType) -> None:
    """POSITIVE PARTNER / empty-input floor: RED IF this reports something
    closed when nothing was open."""
    payload = {"windows": [_window(opened=_EXPIRED_START, expires=_EXPIRED_END)]}
    assert closer.close_windows(payload, _NOW) == []
    assert payload["windows"][0]["expires_at"] == _EXPIRED_END


# --- set_flag_false -----------------------------------------------------------


def test_set_flag_false_flips_a_true_flag(closer: ModuleType) -> None:
    """RED IF: the substitution stops matching the real key, or flips the
    wrong value."""
    text = 'title = "x"\n\n[env]\n  OPENROUTER_LIVE_EXECUTION_ENABLED = "true"\n  OTHER = "true"\n'
    new_text, changed = closer.set_flag_false(text)
    assert changed is True
    assert 'OPENROUTER_LIVE_EXECUTION_ENABLED = "false"' in new_text
    # The unrelated key with the same value must survive untouched — proves
    # the substitution is scoped to the flag's own key, not to any `"true"`.
    assert 'OTHER = "true"' in new_text


def test_set_flag_false_is_a_noop_when_already_false(closer: ModuleType) -> None:
    """RED IF: the function rewrites the line even when it is already
    ``"false"`` — the caller uses ``changed`` to decide whether to write the
    file at all, so a false positive here means an unwarranted write every
    time the closer is re-run."""
    text = '[env]\n  OPENROUTER_LIVE_EXECUTION_ENABLED = "false"\n'
    new_text, changed = closer.set_flag_false(text)
    assert changed is False
    assert new_text == text


def test_set_flag_false_refuses_when_the_key_is_absent(closer: ModuleType) -> None:
    """RED IF: a missing key is silently ignored instead of refused — a caller
    that writes ``payload`` (closing the window) without also flipping the
    flag would recreate exactly the sanctioned-but-unattended posture #407 is
    about."""
    with pytest.raises(ValueError, match="OPENROUTER_LIVE_EXECUTION_ENABLED"):
        closer.set_flag_false('title = "x"\n[env]\n  OTHER = "1"\n')


# --- main(): the whole command, against real files in a tmp_path -------------


def _write_fixture(
    tmp_path: Path, *, flag_value: str, windows: list[dict[str, Any]]
) -> tuple[Path, Path]:
    fly = tmp_path / "fly.toml"
    fly.write_text(
        f'app = "x"\n\n[env]\n  OPENROUTER_LIVE_EXECUTION_ENABLED = "{flag_value}"\n',
        encoding="utf-8",
    )
    windows_file = tmp_path / "windows.json"
    windows_file.write_text(json.dumps({"windows": windows}), encoding="utf-8")
    return fly, windows_file


def test_main_refuses_when_nothing_is_open(closer: ModuleType, tmp_path: Path, capsys: Any) -> None:
    """RED IF: ``main`` returns 0 (or writes anything) when no window covers
    ``now`` — a silent no-op success here would let an operator believe they
    closed a window that was never open."""
    fly, windows_file = _write_fixture(
        tmp_path, flag_value="false", windows=[_window(opened=_EXPIRED_START, expires=_EXPIRED_END)]
    )
    before = windows_file.read_text(encoding="utf-8")
    rc = closer.main(
        ["--fly-toml", str(fly), "--windows-file", str(windows_file), "--now", _NOW_ISO]
    )
    assert rc == 1
    assert "nothing to close" in capsys.readouterr().err
    assert windows_file.read_text(encoding="utf-8") == before


def test_main_closes_an_open_window_and_flips_the_flag(closer: ModuleType, tmp_path: Path) -> None:
    """The end-to-end case #407 exists for. RED IF: either file is left
    unedited, or the resulting state would still fail the shipped gate
    (``test_the_shipped_declaration_file_declares_no_window_right_now`` in
    ``test_live_posture_check.py``) — i.e. a non-standing window still covers
    ``now`` after this runs."""
    fly, windows_file = _write_fixture(
        tmp_path, flag_value="true", windows=[_window(opened=_OPEN_START, expires=_OPEN_END)]
    )
    rc = closer.main(
        ["--fly-toml", str(fly), "--windows-file", str(windows_file), "--now", _NOW_ISO]
    )
    assert rc == 0
    assert 'OPENROUTER_LIVE_EXECUTION_ENABLED = "false"' in fly.read_text(encoding="utf-8")
    payload = json.loads(windows_file.read_text(encoding="utf-8"))
    assert closer.find_open_windows(payload, _NOW) == []


def test_main_closes_the_window_even_if_the_flag_was_already_false(
    closer: ModuleType, tmp_path: Path
) -> None:
    """The exact incident shape in #407: the flag had already reverted to
    "false" by the time the fix runs (the window merely outlived it), so the
    only remaining edit is the window. RED IF: the script treats an
    already-false flag as "nothing to do" and skips closing the window."""
    fly, windows_file = _write_fixture(
        tmp_path, flag_value="false", windows=[_window(opened=_OPEN_START, expires=_OPEN_END)]
    )
    rc = closer.main(
        ["--fly-toml", str(fly), "--windows-file", str(windows_file), "--now", _NOW_ISO]
    )
    assert rc == 0
    payload = json.loads(windows_file.read_text(encoding="utf-8"))
    assert closer.find_open_windows(payload, _NOW) == []


def test_main_leaves_a_standing_window_alone_and_still_refuses(
    closer: ModuleType, tmp_path: Path, capsys: Any
) -> None:
    """RED IF: the script tries to write ``expires_at`` onto a standing entry
    (which has none) and either crashes or corrupts the file, instead of
    correctly reporting nothing to close."""
    fly, windows_file = _write_fixture(
        tmp_path,
        flag_value="true",
        windows=[_window(opened=_OPEN_START, expires=None, mode="standing")],
    )
    rc = closer.main(
        ["--fly-toml", str(fly), "--windows-file", str(windows_file), "--now", _NOW_ISO]
    )
    assert rc == 1
    payload = json.loads(windows_file.read_text(encoding="utf-8"))
    assert "expires_at" not in payload["windows"][0]
