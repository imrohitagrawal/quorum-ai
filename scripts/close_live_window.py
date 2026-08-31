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
    kept serving a spend-capable posture. This script performs both edits
    together so the recipe cannot be half-applied, and refuses loudly rather
    than doing nothing when there is no open window to close.

WHAT IT DOES NOT DO
    It never touches a ``standing`` window — those have no ``expires_at`` to
    close (the field is FORBIDDEN for that mode per the declaration file's own
    README) and ending one is a policy decision, not a mechanical revert.

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

REPO_ROOT = Path(__file__).resolve().parent.parent
FLY_TOML = REPO_ROOT / "fly.toml"
WINDOWS_PATH = REPO_ROOT / "configs" / "live-execution-windows.json"
FLAG = "OPENROUTER_LIVE_EXECUTION_ENABLED"
MODE_STANDING = "standing"
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


def find_open_windows(payload: dict, now: dt.datetime) -> list[dict]:
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
        if entry.get("mode") == MODE_STANDING:
            continue
        opened = _parse_instant(entry.get("opened_at"))
        expires = _parse_instant(entry.get("expires_at"))
        if opened is None or expires is None:
            continue
        if opened <= now < expires:
            open_windows.append(entry)
    return open_windows


def close_windows(payload: dict, now: dt.datetime) -> list[dict]:
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
    """
    match = _FLAG_LINE.search(fly_toml_text)
    if match is None:
        raise ValueError(
            f"{FLAG} not found in fly.toml's [env] block — refusing to edit blind. "
            "Set it by hand and verify /status.live_execution yourself."
        )
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

    windows_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    if flag_changed:
        fly_path.write_text(new_fly_text, encoding="utf-8")

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
