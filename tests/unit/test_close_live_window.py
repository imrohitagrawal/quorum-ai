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
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from tests.repo_root import find_repo_root

REPO_ROOT = find_repo_root(Path(__file__))
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
    tmp_path: Path,
    *,
    flag_value: str,
    windows: list[dict[str, Any]],
    peer_value: str | None = "true",
) -> tuple[Path, Path]:
    """``peer_value=None`` writes a fly.toml WITHOUT the peer key, for the
    tests that prove the closer refuses to edit blind (#458)."""
    fly = tmp_path / "fly.toml"
    peer_line = "" if peer_value is None else f'  PEER_CRITIQUE_ENABLED = "{peer_value}"\n'
    fly.write_text(
        f'app = "x"\n\n[env]\n  OPENROUTER_LIVE_EXECUTION_ENABLED = "{flag_value}"\n{peer_line}',
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
        tmp_path,
        flag_value="false",
        peer_value="false",
        windows=[_window(opened=_EXPIRED_START, expires=_EXPIRED_END)],
    )
    before = windows_file.read_text(encoding="utf-8")
    rc = closer.main(
        ["--fly-toml", str(fly), "--windows-file", str(windows_file), "--now", _NOW_ISO]
    )
    assert rc == 1
    assert "nothing to close" in capsys.readouterr().err
    assert windows_file.read_text(encoding="utf-8") == before


def test_main_flips_the_flag_when_the_window_ALREADY_LAPSED(
    closer: ModuleType, tmp_path: Path, capsys: Any
) -> None:
    """#460, and the most likely real incident: the window expired on its own
    while the flag stayed ``"true"``.

    That is exactly the 2026-09-11 shape — the window lapsed at 07:51:25Z and
    production kept serving a spend-capable posture for 21.6-25.5h past its
    own expiry (bracketed by the watchdog's last failure at
    2026-09-12T05:30:30Z and its first success at 09:22:51Z). Before this
    fix the script refused (exit 1) and changed NOTHING, leaving the flag
    ``"true"``, so the purpose-built revert tool did nothing in the case where
    it was most needed and its own message even named the situation ("the
    window that sanctioned it has already lapsed on its own").

    Only ONE edit is correct here, and the window file must NOT be touched:
    nothing covers ``now``, so there is no ``expires_at`` to stamp, and
    rewriting a lapsed entry's expiry would falsify the record of when the
    window actually ended.

    RED IF: the script refuses on a lapsed window while the flag is still on,
    or flips the flag but also rewrites the lapsed window's ``expires_at``.
    """
    fly, windows_file = _write_fixture(
        tmp_path, flag_value="true", windows=[_window(opened=_EXPIRED_START, expires=_EXPIRED_END)]
    )
    windows_before = windows_file.read_text(encoding="utf-8")
    rc = closer.main(
        ["--fly-toml", str(fly), "--windows-file", str(windows_file), "--now", _NOW_ISO]
    )
    assert rc == 0
    assert 'OPENROUTER_LIVE_EXECUTION_ENABLED = "false"' in fly.read_text(encoding="utf-8")
    # The lapsed declaration is a historical record; it must survive verbatim.
    assert windows_file.read_text(encoding="utf-8") == windows_before
    # Assert the message names the REAL expiry instant, not just that it uses
    # the word "lapsed". The wording is what tells an operator which of the
    # three absence causes they are in, so pin the datum rather than the phrase.
    out = capsys.readouterr().out
    assert "2026-08-19T17:00:00Z" in out
    assert "expired at" in out


def test_main_still_refuses_a_standing_window_even_though_the_flag_is_on(
    closer: ModuleType, tmp_path: Path, capsys: Any
) -> None:
    """The boundary the #460 fix must NOT cross.

    A standing window has no ``expires_at`` and legitimately sanctions a live
    posture, so a flag reading ``"true"`` beside one is not a stranded flag —
    ending a standing window is a policy decision, which this script's own
    docstring says it never makes. The lapsed-window fix keys on "no window
    covers now AND none is standing", not merely "no window covers now".

    RED IF: the #460 fix flips the flag whenever nothing covers ``now``,
    which would silently end a standing window's sanction.
    """
    fly, windows_file = _write_fixture(
        tmp_path,
        flag_value="true",
        windows=[_window(opened=_OPEN_START, expires=None, mode="standing")],
    )
    rc = closer.main(
        ["--fly-toml", str(fly), "--windows-file", str(windows_file), "--now", _NOW_ISO]
    )
    assert rc == 1
    assert 'OPENROUTER_LIVE_EXECUTION_ENABLED = "true"' in fly.read_text(encoding="utf-8")
    assert 'PEER_CRITIQUE_ENABLED = "true"' in fly.read_text(encoding="utf-8")  # #458
    # The two refusals must be DISTINGUISHABLE. Adversarial review showed that
    # making the standing refusal print the lapsed/already-off text instead
    # survived the whole suite, because nothing read this message. ``capsys``
    # was requested here and never used — the dead fixture parameter was
    # exactly where this assertion belonged.
    #
    # A first version asserted only ``"standing" in err`` and STILL survived
    # that mutation, because the word appears later in the same message. So
    # assert the clause that is unique to this branch, and assert the OTHER
    # refusal's text is absent — the point is that an operator can tell them
    # apart, which one shared substring does not establish.
    err = capsys.readouterr().err
    assert "POLICY decision" in err
    assert "nothing to revert" not in err


@pytest.mark.parametrize(
    ("label", "windows"),
    [
        # Each of these is a declaration the POSTURE CHECKER refuses to parse, so
        # nothing may be concluded from it. The first two are the dangerous ones:
        # the window COVERS `now`, so an operator told "no window is declared at
        # all" would go looking at `fly secrets` while the real cause is a typo in
        # the file in front of them.
        (
            "naive expires_at, and it covers now",
            [
                {
                    "mode": "time_boxed",
                    "opened_at": _OPEN_START,
                    "expires_at": "2026-09-01T17:00:00",
                    "owner": "o",
                    "reason": "r",
                }
            ],
        ),
        (
            "expires_at missing, and it covers now",
            [{"mode": "time_boxed", "opened_at": _OPEN_START, "owner": "o", "reason": "r"}],
        ),
        (
            "an unrecognised mode",
            [{"mode": "Standing", "opened_at": _OPEN_START, "owner": "o", "reason": "r"}],
        ),
        ("an entry that is not a dict", ["oops"]),
    ],
)
def test_main_refuses_a_declaration_the_POSTURE_CHECKER_cannot_trust(
    closer: ModuleType, tmp_path: Path, capsys: Any, label: str, windows: list[Any]
) -> None:
    """An UNREADABLE declaration is not the same as an EMPTY one.

    The lapsed revert concludes "nothing sanctions this posture" from an ABSENCE,
    so it must first establish that the file can be trusted to say so.
    ``parse_windows`` is the posture checker's own predicate and its docstring
    states the distinction: None means "this file did not tell me anything I may
    rely on", which every caller must turn into UNKNOWN, never into "nothing is
    declared".

    A first version of this guard checked only ``mode``, so the first two rows
    here fell straight through and a window that COVERS NOW was reported as "no
    window is declared at all". Adversarial review demonstrated it.

    RED IF: any untrusted shape reaches the revert branch, or the flag is touched
    while the declaration cannot be read.
    """
    fly, windows_file = _write_fixture(tmp_path, flag_value="true", windows=windows)
    before = windows_file.read_text(encoding="utf-8")
    rc = closer.main(
        ["--fly-toml", str(fly), "--windows-file", str(windows_file), "--now", _NOW_ISO]
    )
    assert rc == 2, label
    assert 'OPENROUTER_LIVE_EXECUTION_ENABLED = "true"' in fly.read_text(encoding="utf-8")
    assert 'PEER_CRITIQUE_ENABLED = "true"' in fly.read_text(encoding="utf-8")  # #458
    assert windows_file.read_text(encoding="utf-8") == before
    assert "cannot be trusted" in capsys.readouterr().err


def test_a_covering_window_still_reverts_even_beside_an_UNTRUSTED_entry(
    closer: ModuleType, tmp_path: Path
) -> None:
    """The regression this guard caused, pinned so it cannot come back.

    A first version ran the trust check BEFORE selecting open windows, so a typo
    on ANY entry — including a long-expired historical one the declaration file's
    own README says to leave in place — aborted the command and left the flag
    "true", in a state the PREVIOUS code reverted correctly. A guard against
    concluding-from-absence was applied to a path that had positively FOUND a
    covering window, which made the revert tool worse rather than safer.

    RED IF: the trust check moves back ahead of ``close_windows``, or otherwise
    blocks a revert that has a covering window to close.
    """
    fly, windows_file = _write_fixture(
        tmp_path,
        flag_value="true",
        windows=[
            _window(opened=_OPEN_START, expires=_OPEN_END),
            {"mode": "standng", "opened_at": _EXPIRED_START, "owner": "o", "reason": "typo"},
        ],
    )
    rc = closer.main(
        ["--fly-toml", str(fly), "--windows-file", str(windows_file), "--now", _NOW_ISO]
    )
    assert rc == 0
    assert 'OPENROUTER_LIVE_EXECUTION_ENABLED = "false"' in fly.read_text(encoding="utf-8")
    payload = json.loads(windows_file.read_text(encoding="utf-8"))
    assert closer.find_open_windows(payload, _NOW) == []


def test_main_refuses_an_unrecognised_window_mode_and_leaves_the_flag_ALONE(
    closer: ModuleType, tmp_path: Path, capsys: Any
) -> None:
    """A mode that is neither ``time_boxed`` nor ``standing`` makes the WHOLE
    FILE untrusted, so nothing may be concluded from it — including "no window
    sanctions this".

    That is the declaration file's own README stance ("an unrecognised mode
    makes the whole file untrusted rather than [being] silently ignored") and
    ``find_open_windows`` already mirrors it by refusing to treat such an entry
    as closeable. Before this test, ``has_standing_window`` did NOT: it matched
    ``mode == "standing"`` exactly, so a wrongly-cased ``"Standing"`` was
    invisible to it, fell through into the #460 lapsed-revert branch, and the
    flag was flipped — SILENTLY ENDING A STANDING SANCTION, which is the one
    thing that branch must never do.

    RED IF: an unrecognised mode is treated as "no window", which lets the
    lapsed revert fire on a file nobody should be drawing conclusions from.
    """
    fly, windows_file = _write_fixture(
        tmp_path,
        flag_value="true",
        windows=[
            {**_window(opened=_OPEN_START, expires=None, mode="standing"), "mode": "Standing"}
        ],
    )
    rc = closer.main(
        ["--fly-toml", str(fly), "--windows-file", str(windows_file), "--now", _NOW_ISO]
    )
    assert rc == 2
    assert 'OPENROUTER_LIVE_EXECUTION_ENABLED = "true"' in fly.read_text(encoding="utf-8")
    assert 'PEER_CRITIQUE_ENABLED = "true"' in fly.read_text(encoding="utf-8")  # #458
    assert "unrecognised" in capsys.readouterr().err


def test_main_refuses_a_standing_window_sitting_beside_a_LAPSED_one(
    closer: ModuleType, tmp_path: Path
) -> None:
    """The MIXED payload, which is the shape the shipped file takes the moment
    a standing window is added beside the entries that have already expired.

    Adversarial review defeated the single-window fixtures with
    ``not any(mode == time_boxed ...)``: green on all 266 tests, and on this
    exact payload it reported "NO window sanctioning it" and flipped the flag
    while a standing window still stood.

    RED IF: ``has_standing_window`` is derived from the absence of a
    ``time_boxed`` entry, or from anything else that a lapsed sibling defeats.
    """
    fly, windows_file = _write_fixture(
        tmp_path,
        flag_value="true",
        windows=[
            _window(opened=_EXPIRED_START, expires=_EXPIRED_END),
            _window(opened=_OPEN_START, expires=None, mode="standing"),
        ],
    )
    rc = closer.main(
        ["--fly-toml", str(fly), "--windows-file", str(windows_file), "--now", _NOW_ISO]
    )
    assert rc == 1
    assert 'OPENROUTER_LIVE_EXECUTION_ENABLED = "true"' in fly.read_text(encoding="utf-8")
    assert 'PEER_CRITIQUE_ENABLED = "true"' in fly.read_text(encoding="utf-8")  # #458


def test_main_says_NO_WINDOW_DECLARED_rather_than_inventing_a_lapse(
    closer: ModuleType, tmp_path: Path, capsys: Any
) -> None:
    """An empty declaration with the flag on is the #357 accidental-``true``
    shape: no window ever existed, so nothing lapsed.

    Flipping the flag is still right — nothing sanctions the posture — but the
    message must not assert a lapse that never happened, and must not tell the
    operator that "the lapsed entry is the record of when the window ended"
    when there is no entry. Getting this wrong points them away from the real
    cause, which per ``fly.toml`` may be a ``fly secrets set`` override that no
    tracked file records.

    RED IF: the success message claims a window lapsed in a state where none is
    declared.
    """
    fly, windows_file = _write_fixture(tmp_path, flag_value="true", windows=[])
    rc = closer.main(
        ["--fly-toml", str(fly), "--windows-file", str(windows_file), "--now", _NOW_ISO]
    )
    assert rc == 0
    assert 'OPENROUTER_LIVE_EXECUTION_ENABLED = "false"' in fly.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "no window is declared" in out
    assert "lapsed" not in out


def test_main_says_NOT_YET_STARTED_for_a_future_only_window(
    closer: ModuleType, tmp_path: Path, capsys: Any
) -> None:
    """A window that has not opened yet has not lapsed either. Same reasoning
    as the empty case: flip the flag, describe what was actually found.

    RED IF: a future window is reported as having lapsed.
    """
    fly, windows_file = _write_fixture(
        tmp_path, flag_value="true", windows=[_window(opened=_FUTURE_START, expires=_FUTURE_END)]
    )
    rc = closer.main(
        ["--fly-toml", str(fly), "--windows-file", str(windows_file), "--now", _NOW_ISO]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "has not started yet" in out
    assert "lapsed" not in out


def test_the_lapsed_revert_tells_the_operator_to_DEPLOY_and_verify(
    closer: ModuleType, tmp_path: Path, capsys: Any
) -> None:
    """Editing a tracked file changes NOTHING in production until it is
    deployed, and ``fly secrets set`` can override ``fly.toml``'s ``[env]``
    entirely — so a green exit here is not a closed posture.

    The pre-existing two-edit path already ends with "Commit both files
    together, deploy, then verify /status.live_execution yourself." The #460
    path was built for the incident and shipped without it, which is a false
    completion signal at the worst moment.

    RED IF: the one-edit success path stops telling the operator to deploy and
    verify.
    """
    fly, windows_file = _write_fixture(
        tmp_path, flag_value="true", windows=[_window(opened=_EXPIRED_START, expires=_EXPIRED_END)]
    )
    rc = closer.main(
        ["--fly-toml", str(fly), "--windows-file", str(windows_file), "--now", _NOW_ISO]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "deploy" in out.lower()
    assert "/status.live_execution" in out


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


# --- fixes made after adversarial review (2026-08-31) ------------------------


def test_find_open_windows_excludes_a_wrongly_cased_mode(closer: ModuleType) -> None:
    """A mode of ``"Standing"`` (wrong case) is not the recognised
    ``"standing"`` OR ``"time_boxed"`` spelling. The declaration file's own
    README says an unrecognised mode makes the WHOLE FILE untrusted rather
    than silently ignored — this closer must not fall the other way and treat
    an unrecognised mode as closeable. RED IF: the exclusion narrows back to
    "anything that isn't exactly 'standing'", which a wrongly-cased mode
    slips past."""
    payload = {"windows": [{**_window(opened=_OPEN_START, expires=_OPEN_END), "mode": "Standing"}]}
    assert closer.find_open_windows(payload, _NOW) == []


def test_set_flag_false_refuses_when_the_key_appears_twice(closer: ModuleType) -> None:
    """TOML allows the same key name in different tables. Fixing only the
    first occurrence would report success while a second copy of the flag
    stayed live — exactly the false-success shape #407 is about. RED IF: the
    duplicate check is dropped and only the first match is edited."""
    text = (
        '[env]\n  OPENROUTER_LIVE_EXECUTION_ENABLED = "true"\n'
        '[env2]\n  OPENROUTER_LIVE_EXECUTION_ENABLED = "true"\n'
    )
    with pytest.raises(ValueError, match="appears 2 times"):
        closer.set_flag_false(text)


def test_main_refuses_on_a_non_dict_windows_payload(
    closer: ModuleType, tmp_path: Path, capsys: Any
) -> None:
    """A syntactically valid JSON file whose top level is a list (or any
    non-object) must be refused cleanly, not crash with a raw traceback. RED
    IF: the type guard is removed and this raises AttributeError instead of
    returning 2 with a clear message."""
    fly, windows_file = _write_fixture(tmp_path, flag_value="true", windows=[])
    windows_file.write_text("[]", encoding="utf-8")
    rc = closer.main(
        ["--fly-toml", str(fly), "--windows-file", str(windows_file), "--now", _NOW_ISO]
    )
    assert rc == 2
    assert "does not contain a JSON object" in capsys.readouterr().err


def test_main_writes_the_flag_before_the_window_declaration(
    closer: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the second write fails partway, the worst surviving state must be
    "flag off, window still open" (still refused by the shipped gate, forcing
    a retry) rather than "window closed, flag still true" (which the shipped
    gate would NOT catch — a false-success state). RED IF: the write order is
    reversed, since this test asserts the windows file write happens strictly
    after the fly.toml write by making the SECOND write of two calls raise."""
    fly, windows_file = _write_fixture(
        tmp_path, flag_value="true", windows=[_window(opened=_OPEN_START, expires=_OPEN_END)]
    )
    write_calls: list[Path] = []
    original_write_text = Path.write_text

    def _tracking_write_text(self: Path, *args: Any, **kwargs: Any) -> int:
        write_calls.append(self)
        if len(write_calls) == 2:
            raise OSError("simulated failure on the second write")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _tracking_write_text)
    with pytest.raises(OSError, match="simulated failure"):
        closer.main(
            ["--fly-toml", str(fly), "--windows-file", str(windows_file), "--now", _NOW_ISO]
        )
    assert write_calls == [fly, windows_file]


# --- #458 / ADR-0122: the peer-critique flag closes with the window ----------


def _env(fly: Path) -> dict[str, Any]:
    """Parse rather than substring-match the written file (AGENTS rule 8)."""
    env = tomllib.loads(fly.read_text(encoding="utf-8"))["env"]
    assert isinstance(env, dict) and env, "fixture fly.toml has no [env] block"
    return env


def test_main_closes_an_open_window_and_flips_BOTH_flags(
    closer: ModuleType, tmp_path: Path
) -> None:
    """The coupling on the covering-window path.

    RED IF: closing a window flips the live flag and leaves
    ``PEER_CRITIQUE_ENABLED`` reading ``"true"`` — the state issue #458 named,
    where re-opening a window turns peer critique back on unread.
    """
    fly, windows_file = _write_fixture(
        tmp_path, flag_value="true", windows=[_window(opened=_OPEN_START, expires=_OPEN_END)]
    )
    rc = closer.main(
        ["--fly-toml", str(fly), "--windows-file", str(windows_file), "--now", _NOW_ISO]
    )
    assert rc == 0
    env = _env(fly)
    assert env["OPENROUTER_LIVE_EXECUTION_ENABLED"] == "false"
    assert env["PEER_CRITIQUE_ENABLED"] == "false"


def test_the_lapsed_revert_flips_the_peer_flag_too_and_leaves_the_declaration_alone(
    closer: ModuleType, tmp_path: Path, capsys: Any
) -> None:
    """The coupling on the #460 lapsed path.

    RED IF: the lapsed revert flips only the live flag, or the peer edit adds
    a write to the declaration file (mutation 06 of the proof harness).
    """
    fly, windows_file = _write_fixture(
        tmp_path, flag_value="true", windows=[_window(opened=_EXPIRED_START, expires=_EXPIRED_END)]
    )
    windows_before = windows_file.read_text(encoding="utf-8")
    rc = closer.main(
        ["--fly-toml", str(fly), "--windows-file", str(windows_file), "--now", _NOW_ISO]
    )
    assert rc == 0
    env = _env(fly)
    assert env["OPENROUTER_LIVE_EXECUTION_ENABLED"] == "false"
    assert env["PEER_CRITIQUE_ENABLED"] == "false"
    assert windows_file.read_text(encoding="utf-8") == windows_before
    assert "PEER_CRITIQUE_ENABLED" in capsys.readouterr().out


def test_a_stranded_peer_flag_is_reverted_even_when_live_is_already_off(
    closer: ModuleType, tmp_path: Path, capsys: Any
) -> None:
    """The shape production shipped from 2026-09-12 until this change: live
    execution already reverted, peer critique still ``"true"``, no window.
    Before #458 the closer answered "nothing to close" (exit 1) and changed
    nothing; under the coupling the peer flag is stranded in exactly the way
    a live flag is, so it is one edit, exit 0.

    RED IF: the command exits 1 or leaves the peer flag ``"true"`` when only
    the peer flag is on.
    """
    fly, windows_file = _write_fixture(
        tmp_path, flag_value="false", windows=[_window(opened=_EXPIRED_START, expires=_EXPIRED_END)]
    )
    windows_before = windows_file.read_text(encoding="utf-8")
    rc = closer.main(
        ["--fly-toml", str(fly), "--windows-file", str(windows_file), "--now", _NOW_ISO]
    )
    assert rc == 0
    env = _env(fly)
    assert env["OPENROUTER_LIVE_EXECUTION_ENABLED"] == "false"
    assert env["PEER_CRITIQUE_ENABLED"] == "false"
    assert windows_file.read_text(encoding="utf-8") == windows_before
    out = capsys.readouterr().out
    assert "PEER_CRITIQUE_ENABLED was still on" in out
    assert "DEPLOY" in out
    # The trailing instruction names the field and the secret of the flag
    # that MOVED, not the live flag (review finding, round 1).
    assert "verify /status.peer_critique_enabled yourself" in out
    assert "`fly secrets set PEER_CRITIQUE_ENABLED`" in out
    assert "/status.live_execution" not in out


def test_main_refuses_to_edit_blind_when_the_peer_key_is_absent(
    closer: ModuleType, tmp_path: Path, capsys: Any
) -> None:
    """Same rule as the live flag: an absent key is a refusal, never a silent
    skip, because a skip would report a closed window while peer critique
    stayed exactly as armed as it was.

    RED IF: a fly.toml without ``PEER_CRITIQUE_ENABLED`` closes cleanly.
    """
    fly, windows_file = _write_fixture(
        tmp_path,
        flag_value="true",
        peer_value=None,
        windows=[_window(opened=_OPEN_START, expires=_OPEN_END)],
    )
    fly_before = fly.read_text(encoding="utf-8")
    windows_before = windows_file.read_text(encoding="utf-8")
    rc = closer.main(
        ["--fly-toml", str(fly), "--windows-file", str(windows_file), "--now", _NOW_ISO]
    )
    assert rc == 2
    assert "PEER_CRITIQUE_ENABLED" in capsys.readouterr().err
    assert fly.read_text(encoding="utf-8") == fly_before
    assert windows_file.read_text(encoding="utf-8") == windows_before


def test_set_flag_false_edits_the_peer_key_by_name_and_nothing_else(closer: ModuleType) -> None:
    """The one text helper serves both keys, scoped to the key it was given.

    RED IF: ``set_flag_false`` cannot be pointed at the peer key, or editing
    the peer key touches the live key (or the reverse).
    """
    text = (
        'app = "x"\n[env]\n  OPENROUTER_LIVE_EXECUTION_ENABLED = "true"\n'
        '  PEER_CRITIQUE_ENABLED = "true"\n  OTHER = "true"\n'
    )
    new_text, changed = closer.set_flag_false(text, key=closer.PEER_FLAG)
    assert changed is True
    env = tomllib.loads(new_text)["env"]
    assert env == {
        "OPENROUTER_LIVE_EXECUTION_ENABLED": "true",
        "PEER_CRITIQUE_ENABLED": "false",
        "OTHER": "true",
    }
    again, changed_again = closer.set_flag_false(new_text, key=closer.PEER_FLAG)
    assert changed_again is False
    assert again == new_text


def test_the_flag_names_the_closer_writes_are_exactly_the_two_coupled_keys(
    closer: ModuleType,
) -> None:
    """Positive partner for the allowlist test below, and the pin that
    ``PEER_FLAG`` is the key ``fly.toml`` actually carries.

    RED IF: the closer's peer constant drifts from the key name production
    reads, or a third flag is coupled here without a decision.
    """
    assert closer.FLAG == "OPENROUTER_LIVE_EXECUTION_ENABLED"
    assert closer.PEER_FLAG == "PEER_CRITIQUE_ENABLED"


_PEER_FLAG_MENTIONS_ALLOWED = frozenset(
    {
        # The two halves of the mechanism: the closer writes it, the checker
        # refuses a committed stranded value and reports the served one.
        "scripts/close_live_window.py",
        "scripts/live_posture_check.py",
        # Proof scripts that SET the environment variable for a local sweep;
        # they write no file.
        "scripts/proofs/debate_output_band_sweep.py",
        # Names the key in the alert body it posts (operator instructions);
        # its token is read-only and it writes nothing (its own :1655 test).
        ".github/workflows/live-posture-watchdog.yml",
        # The local-development template; sets the variable for a developer's
        # shell, never fly.toml.
        ".env.example",
        # The operator procedure that names the Fly-secret route (the one
        # writer this test cannot see, stated below).
        "DEPLOY.md",
    }
)


def test_no_file_outside_the_window_mechanism_names_the_peer_flag() -> None:
    """ "No other writer of the flag exists" — pinned as the population of
    files that so much as NAME the key, so a new writer cannot appear
    without this test naming it (AGENTS rule 1a: a check, not a sentence).

    Set equality is deliberate: a new mention is triaged, not tolerated.
    What this cannot see, stated: a ``fly secrets set PEER_CRITIQUE_ENABLED``
    (no tracked file records one); a hand edit of ``fly.toml`` (which the
    pre-merge gate in ``test_live_execution_posture_declaration.py`` refuses
    when it strands the flag); and ``docs/``, ``e2e/`` and ``tests/``, which
    are deliberately outside the scan because they describe the flag in
    prose and pin it in tests rather than write it — except their ``*.sh``
    files, because the ``*.sh`` pathspec matches every tracked shell script
    at any depth (a nested deploy script is exactly the writer to catch).
    ``fly.toml`` itself is the target, not a writer, and is outside the scan
    for that reason. A lower-case ASSIGNMENT (``ENV peer_critique_enabled=``,
    ``export peer_critique_enabled=``) counts too, because the app's
    ``Settings`` is ``case_sensitive=False`` and such a line would set the
    flag; the attribute ``settings.peer_critique_enabled`` does not count.

    RED IF: a tracked file under ``scripts/``, ``src/``, ``.github/``,
    ``configs/``, the ``Makefile``, the ``Dockerfile``, ``docker-compose.yml``,
    ``.env.example``, ``DEPLOY.md`` or any tracked ``*.sh`` starts or stops
    naming ``PEER_CRITIQUE_ENABLED`` in any letter case.
    """
    listed = subprocess.run(
        [
            "git",
            "ls-files",
            "--",
            "scripts",
            "src",
            ".github",
            "configs",
            "Makefile",
            "Dockerfile",
            "docker-compose.yml",
            ".env.example",
            "DEPLOY.md",
            "*.sh",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert len(listed) > 50, "git ls-files returned too little to be the repository"
    # The exact key anywhere, OR a lower-case ASSIGNMENT at line start
    # (``ENV x=``, ``export x=``, ``x=``) — the shapes a writer takes. The
    # attribute ``settings.peer_critique_enabled`` and printed strings are
    # not assignments and are not writers.
    exact = re.compile(r"\bPEER_CRITIQUE_ENABLED\b")
    assigned = re.compile(r"(?im)^\s*(?:ENV\s+|export\s+|set\s+)?peer_critique_enabled\s*=")
    naming = set()
    for path in listed:
        text = (REPO_ROOT / path).read_text(encoding="utf-8", errors="replace")
        if exact.search(text) or assigned.search(text):
            naming.add(path)
    # Positive partner: the mechanism itself must be in the population.
    assert "scripts/close_live_window.py" in naming
    assert naming == _PEER_FLAG_MENTIONS_ALLOWED, (
        "files naming PEER_CRITIQUE_ENABLED changed: added "
        f"{sorted(naming - _PEER_FLAG_MENTIONS_ALLOWED)}, gone "
        f"{sorted(_PEER_FLAG_MENTIONS_ALLOWED - naming)}. A new writer of the flag is a "
        "decision (ADR-0122); a new mention is triaged here, not tolerated."
    )


def test_a_lower_case_copy_of_the_key_is_a_duplicate_not_a_second_flag(closer: ModuleType) -> None:
    """The app's ``Settings`` is ``case_sensitive=False``, so a lower-case
    ``peer_critique_enabled = "true"`` line sets the flag exactly as the
    upper-case one does. The closer's key match is therefore case-insensitive,
    which turns that shape into the duplicate-key refusal instead of a
    silent "already off".

    RED IF: the key match is case-sensitive, so the lower-case copy is never
    seen and the closer reports success with the flag still on.
    """
    text = (
        'app = "x"\n[env]\n  OPENROUTER_LIVE_EXECUTION_ENABLED = "false"\n'
        '  PEER_CRITIQUE_ENABLED = "false"\n  peer_critique_enabled = "true"\n'
    )
    with pytest.raises(ValueError, match="appears 2 times"):
        closer.set_flag_false(text, key=closer.PEER_FLAG)
    # Positive partner: a lower-case key ALONE is found and flipped.
    lone = 'app = "x"\n[env]\n  peer_critique_enabled = "true"\n'
    new_text, changed = closer.set_flag_false(lone, key=closer.PEER_FLAG)
    assert changed is True
    assert tomllib.loads(new_text)["env"] == {"PEER_CRITIQUE_ENABLED": "false"}
