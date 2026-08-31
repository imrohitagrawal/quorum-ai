#!/usr/bin/env python3
"""Close an open live-execution window in one atomic edit (#407).

WHAT THIS IS FOR
    The obvious revert of a live-execution window — flip
    ``OPENROUTER_LIVE_EXECUTION_ENABLED`` back to ``"false"`` in ``fly.toml``
    and leave ``configs/live-execution-windows.json`` alone — is REFUSED by
    ``tests/unit/test_live_posture_check.py::
    test_the_shipped_declaration_file_declares_no_window_right_now``. That gate
    is correct: a window still covering ``now`` may not be committed while the
    flag reads off, because a dangling open declaration would silently sanction
    the next accidental ``true``.

    The only valid single-commit form is therefore TWO edits together:
        1. the flag -> ``"false"`` in ``fly.toml``
        2. the open window's ``expires_at`` -> now, in
           ``configs/live-execution-windows.json``

    On 2026-08-31 (#407) that two-part deduction was not made under incident
    pressure, and the gate blocked the revert for ~4.5 hours while production
    kept serving a spend-capable posture (#407's own title; the same incident's
    total live-posture exposure was ~9.5h, ~8.6h of it past the window's own
    expiry — a different, larger measurement of the same event, both recorded
    on #407). This script performs both edits in one run, and refuses loudly
    rather than doing nothing when there is no open window to close.

    The two file writes are not a single filesystem transaction — if the
    second write fails partway (disk full, permissions), the flag is written
    FIRST specifically so the worst surviving state is "flag off, window still
    open in the file", which the gate above still refuses to let merge. The
    reverse order risks the opposite and worse failure: a window marked closed
    while the flag is still ``"true"``, which that gate would not catch.

WHAT IT DOES NOT DO
    It never touches a ``standing`` window — those have no ``expires_at`` to
    close (the field is FORBIDDEN for that mode per the declaration file's own
    README) and ending one is a policy decision, not a mechanical revert. It
    also refuses rather than guesses when ``fly.toml`` declares the flag more
    than once, or when a window's ``mode`` is anything other than exactly
    ``"time_boxed"`` or ``"standing"``.

USAGE
    python3 scripts/close_live_window.py
    # or:
    make close-window
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
FLY_TOML = REPO_ROOT / "fly.toml"
WINDOWS_PATH = REPO_ROOT / "configs" / "live-execution-windows.json"
FLAG = "OPENROUTER_LIVE_EXECUTION_ENABLED"
MODE_STANDING = "standing"
MODE_TIME_BOXED = "time_boxed"
_FLAG_OFF_VALUES = frozenset({"false", "0", "no", "off", ""})

# Scoped to the flag's own key so a coincidentally-identical value elsewhere in
# the file (e.g. another flag also set to "true") is never touched.
_FLAG_LINE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)" + re.escape(FLAG) + r'[ \t]*=[ \t]*"(?P<value>[^"]*)"'
)


def _parse_instant(value: object) -> dt.datetime | None:
    """Same shape as ``live_posture_check._parse_instant``: ISO-8601 with an
    explicit offset only. A naive timestamp is refused rather than assigned a
    zone, same reasoning as the checker this script exists to satisfy."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.UTC)


def find_open_windows(payload: dict[str, Any], now: dt.datetime) -> list[dict[str, Any]]:
    """The raw JSON entries in ``payload["windows"]`` that cover ``now``.

    Mirrors ``live_posture_check.DeclaredWindow.covers`` / ``is_standing``
    against the RAW dict shape (rather than the parsed dataclass) so the
    caller can edit the matched entries and write them straight back — the
    dataclass has no path back to the JSON it came from.

    Deliberately independent of what the flag currently says: a window is
    "open" by its own declared span, regardless of whether fly.toml has
    already been reverted.
    """
    windows = payload.get("windows")
    if not isinstance(windows, list):
        return []
    open_windows = []
    for entry in windows:
        if not isinstance(entry, dict):
            continue
        # Exact match against the one recognised time-boxed spelling, not
        # "anything that isn't 'standing'". A malformed or wrongly-cased mode
        # (e.g. "Standing") must not fall through into being treated as
        # closeable — the declaration file's own README says an unrecognised
        # mode makes the WHOLE FILE untrusted rather than silently ignored;
        # this mirrors that fail-closed stance instead of contradicting it.
        if entry.get("mode") != MODE_TIME_BOXED:
            continue
        opened = _parse_instant(entry.get("opened_at"))
        expires = _parse_instant(entry.get("expires_at"))
        if opened is None or expires is None:
            continue
        if opened <= now < expires:
            open_windows.append(entry)
    return open_windows


def close_windows(payload: dict[str, Any], now: dt.datetime) -> list[dict[str, Any]]:
    """Mutate ``payload`` in place: stamp every currently-open window's
    ``expires_at`` to ``now``. Returns the entries closed (empty if none were
    open). Only ``expires_at`` is written — every other field, including
    ``owner`` and ``reason``, survives verbatim, because the file's own README
    asks to "leave expired entries in place" as the record of what was
    sanctioned.
    """
    closed = find_open_windows(payload, now)
    stamp = now.isoformat().replace("+00:00", "Z")
    for entry in closed:
        entry["expires_at"] = stamp
    return closed


def set_flag_false(fly_toml_text: str) -> tuple[str, bool]:
    """Set ``FLAG`` to ``"false"`` in ``fly.toml``'s text.

    Returns ``(new_text, changed)``. ``changed`` is ``False`` when the flag
    already read an off-spelling, so a caller can skip an unwarranted write
    (and a diff with nothing in it) on a re-run.

    Raises ``ValueError`` if the key is not present at all — silently doing
    nothing there would let a caller close the window's declaration while the
    flag itself stays exactly as risky as it was.

    Also raises ``ValueError`` if the key appears MORE than once (TOML allows
    the same key name in different tables). Fixing only the first occurrence
    would report success while a second copy of the flag stayed live — fail
    loud instead, since a silent partial fix here is worse than a refusal.
    """
    matches = list(_FLAG_LINE.finditer(fly_toml_text))
    if not matches:
        raise ValueError(
            f"{FLAG} not found in fly.toml's [env] block — refusing to edit blind. "
            "Set it by hand and verify /status.live_execution yourself."
        )
    if len(matches) > 1:
        raise ValueError(
            f"{FLAG} appears {len(matches)} times in fly.toml — refusing to edit "
            "blind, since fixing only one occurrence would report success while "
            "another copy stays live. Resolve the duplicate by hand and verify "
            "/status.live_execution yourself."
        )
    match = matches[0]
    if match.group("value").strip().lower() in _FLAG_OFF_VALUES:
        return fly_toml_text, False
    new_line = f'{match.group("indent")}{FLAG} = "false"'
    new_text = fly_toml_text[: match.start()] + new_line + fly_toml_text[match.end() :]
    return new_text, True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fly-toml", default=str(FLY_TOML))
    parser.add_argument("--windows-file", default=str(WINDOWS_PATH))
    parser.add_argument(
        "--now",
        default=None,
        help="ISO-8601 instant to treat as 'now' (tests only). Defaults to the real clock.",
    )
    args = parser.parse_args(argv)

    if args.now:
        now = _parse_instant(args.now)
        if now is None:
            print(f"--now {args.now!r} did not parse as an ISO-8601 instant", file=sys.stderr)
            return 2
    else:
        now = dt.datetime.now(dt.UTC)

    windows_path = Path(args.windows_file)
    try:
        payload = json.loads(windows_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"could not read {windows_path}: {exc!r}", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print(
            f"{windows_path} does not contain a JSON object at the top level "
            f"(got {type(payload).__name__}) — refusing to edit blind.",
            file=sys.stderr,
        )
        return 2

    closed = close_windows(payload, now)
    if not closed:
        print(
            "no live-execution window is currently open — nothing to close.\n"
            f"Checked {windows_path}: every entry is either 'standing', not yet "
            "started, or already expired. If you intended to revert a live "
            "posture, the flag may already be off, or the window that "
            "sanctioned it has already lapsed on its own.",
            file=sys.stderr,
        )
        return 1

    fly_path = Path(args.fly_toml)
    try:
        fly_text = fly_path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"could not read {fly_path}: {exc!r}", file=sys.stderr)
        return 2

    try:
        new_fly_text, flag_changed = set_flag_false(fly_text)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    # Write the FLAG first, the window declaration second. If the second
    # write fails partway (disk full, permissions, a concurrent edit), the
    # worst surviving state is "flag off, window still open in the file" —
    # which is exactly the state
    # test_the_shipped_declaration_file_declares_no_window_right_now refuses
    # to let merge, so a retry is forced rather than silently accepted. The
    # reverse order risks the opposite: a window marked closed while the flag
    # is still "true", which that same gate would NOT catch.
    if flag_changed:
        fly_path.write_text(new_fly_text, encoding="utf-8")
    windows_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )

    for entry in closed:
        print(
            f"closed window owner={entry.get('owner')!r} "
            f"reason={entry.get('reason')!r} expires_at -> {entry['expires_at']}"
        )
    if flag_changed:
        print(f'{FLAG} set to "false" in {fly_path}')
    else:
        print(f'{FLAG} was already "false" in {fly_path}')
    print("Commit both files together, deploy, then verify /status.live_execution yourself.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
