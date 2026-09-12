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
    on #407). This script performs both edits in one run.

    THE LAPSED CASE IS ONE EDIT, NOT A REFUSAL (#460, ADR-0111). When no window
    covers ``now`` and none is ``standing``, any flag still reading ``"true"``
    is STRANDED — its sanction expired on its own. That is the likelier real
    incident, and until 2026-09-12 this script refused it, changing nothing,
    while its own message named the situation. It now flips the flag alone and
    leaves the declaration file untouched: there is no ``expires_at`` to close,
    and rewriting a lapsed entry's expiry would falsify the record of when the
    window really ended. The gate above is already satisfied in that state,
    which is why one edit is valid there and two are required when a window
    still covers ``now``.

    It still refuses, loudly, in the two cases that are genuinely nothing to
    do: the flag already reads off, or a ``standing`` window is declared.

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
    than once, and (since #460) when a window's ``mode`` is anything other than
    exactly ``"time_boxed"`` or ``"standing"`` — that last one was ASSERTED here
    and not implemented, which was harmless while an unknown mode only produced
    a no-op refusal and became a real defect once the lapsed revert started
    concluding things from an absent window.

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


def _describe_absence(payload: dict[str, Any], now: dt.datetime) -> str:
    """One sentence naming what the declaration actually holds.

    Only reached when nothing covers ``now`` and nothing is standing, so the
    three possibilities are: something lapsed, something has not opened yet, or
    nothing is declared at all. Reported separately because they have different
    causes and an operator mid-incident needs the right one.
    """
    entries = payload.get("windows")
    entries = entries if isinstance(entries, list) else []
    lapsed: list[dt.datetime] = []
    future: list[dt.datetime] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("mode") != MODE_TIME_BOXED:
            continue
        opened = _parse_instant(entry.get("opened_at"))
        expires = _parse_instant(entry.get("expires_at"))
        if expires is not None and expires <= now:
            lapsed.append(expires)
        elif opened is not None and opened > now:
            future.append(opened)
    if lapsed:
        latest = max(lapsed).isoformat().replace("+00:00", "Z")
        return f"The window that authorised it expired at {latest}, on its own."
    if future:
        soonest = min(future).isoformat().replace("+00:00", "Z")
        return f"The only window declared has not started yet (opens {soonest})."
    return (
        "In fact no window is declared at all, so the flag was on with nothing "
        "behind it — check for a fly secrets override."
    )


def unrecognised_modes(payload: dict[str, Any]) -> list[str]:
    """Every ``mode`` value that is neither ``time_boxed`` nor ``standing``.

    The declaration file's own README says an unrecognised mode makes the WHOLE
    FILE untrusted rather than being silently ignored, and
    ``find_open_windows`` already mirrors that by refusing to treat such an
    entry as closeable. This exists so ``main`` mirrors it too.

    It has to, because of #460: the lapsed revert concludes "nothing sanctions
    this posture" from the ABSENCE of a covering or standing window. A
    wrongly-cased ``"Standing"`` is absent from both predicates, so without this
    check that conclusion was drawn from an untrusted file and the flag was
    flipped — silently ending a standing sanction, the one thing the revert must
    never do. Adversarial review demonstrated it.
    """
    windows = payload.get("windows")
    if not isinstance(windows, list):
        return []
    return [
        str(entry.get("mode"))
        for entry in windows
        if isinstance(entry, dict) and entry.get("mode") not in (MODE_TIME_BOXED, MODE_STANDING)
    ]


def has_standing_window(payload: dict[str, Any]) -> bool:
    """Whether any entry declares the ``standing`` mode.

    #460. A standing window has no ``expires_at`` and legitimately sanctions a
    live posture for as long as it stands, so a flag reading ``"true"`` beside
    one is NOT a stranded flag — it is the declared state. Ending a standing
    window is a policy decision, which this script never makes (see the module
    docstring). This is the predicate that keeps the lapsed-window revert below
    from crossing that line.
    """
    windows = payload.get("windows")
    if not isinstance(windows, list):
        return False
    return any(isinstance(entry, dict) and entry.get("mode") == MODE_STANDING for entry in windows)


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

    unknown = unrecognised_modes(payload)
    if unknown:
        print(
            f"{windows_path} declares an unrecognised window mode: "
            f"{sorted(set(unknown))}. Recognised modes are {MODE_TIME_BOXED!r} "
            f"and {MODE_STANDING!r}.\n"
            "The whole file is therefore untrusted and NOTHING is concluded from "
            "it — including 'no window sanctions this'. Fix the mode by hand, "
            "then re-run.",
            file=sys.stderr,
        )
        return 2

    closed = close_windows(payload, now)
    if not closed and not has_standing_window(payload):
        # #460: NOTHING covers `now`, and no standing window sanctions a live
        # posture — so if the flag still reads on, it is STRANDED. That is the
        # most likely real incident, not an edge case: on 2026-09-11 a window
        # lapsed at 07:51:25Z and production kept serving a spend-capable
        # posture for 21.6-25.5h PAST ITS OWN EXPIRY, and this script refused
        # to touch it. (The bracket is what the evidence supports: the watchdog
        # was still failing at 2026-09-12T05:30:30Z and first succeeded at
        # 09:22:51Z, so the posture closed between those. The "10.8h" an
        # earlier draft quoted came from commit 522f8c9's SUBJECT, which was
        # computed ~14h before that commit landed and was never re-measured.)
        # The earlier
        # version's own message named the situation ("the window that
        # sanctioned it has already lapsed on its own") and then declined to
        # act on it.
        #
        # Exactly ONE edit is correct here, and the declaration file must not
        # be touched: nothing covers `now`, so there is no `expires_at` to
        # stamp, and rewriting a lapsed entry's expiry would falsify the record
        # of when the window really ended. The gate this script exists to
        # satisfy (``test_the_shipped_declaration_file_declares_no_window_right_now``)
        # is ALREADY satisfied in this state, which is why the single edit is
        # valid here and is not in the covering-window case.
        stranded_path = Path(args.fly_toml)
        try:
            stranded_text = stranded_path.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            print(f"could not read {stranded_path}: {exc!r}", file=sys.stderr)
            return 2
        try:
            reverted_text, flag_was_on = set_flag_false(stranded_text)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if flag_was_on:
            stranded_path.write_text(reverted_text, encoding="utf-8")
            # Say what was ACTUALLY found. An earlier version asserted "the
            # window has already lapsed" in every branch, which is false for an
            # empty declaration (nothing ever existed — the #357 accidental
            # ``true`` shape) and for a window that has not opened yet. Pointing
            # an operator at a lapse that never happened points them away from
            # the real cause, which fly.toml notes may be a ``fly secrets set``
            # override that no tracked file records.
            print(
                f"{FLAG} was still on with NO window sanctioning it. "
                f"{_describe_absence(payload, now)} Flipped the flag to "
                f'"false" in {stranded_path}.\n'
                f"Left {windows_path} untouched: nothing covers now, so there is "
                "no expires_at to close, and any entry there is the record of "
                "what was declared.\n"
                "Commit it, DEPLOY, then verify /status.live_execution yourself: "
                "editing this file changes nothing in production until it ships, "
                f"and a `fly secrets set {FLAG}` would override it."
            )
            return 0
        print(
            "no live-execution window is currently open — nothing to close.\n"
            f"Checked {windows_path}: every entry is either 'standing', not yet "
            f"started, or already expired, and {FLAG} already reads off in "
            f"{stranded_path}. There is nothing to revert.",
            file=sys.stderr,
        )
        return 1

    if not closed:
        print(
            "no live-execution window is currently open — nothing to close.\n"
            f"Checked {windows_path}: a 'standing' window is declared, which has "
            "no expires_at to close and whose sanction is a POLICY decision this "
            "script never makes. If the live posture should end, retire the "
            "standing declaration deliberately.",
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
