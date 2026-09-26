"""W32 — the invite link (CHG-022 item 4, ADR-0134).

A signed, dated link the operator mints locally and sends to a firm. It
moves the daily new-session cap from the visitor's address to the link.
Failure modes first: ``docs/analysis/2026-09-26-w32-invite-link-failure-modes.md``.
"""

from __future__ import annotations

import io
from datetime import date

import pytest

from product_app import invite_links
from product_app.invite_links import (
    DAILY_SESSIONS_PER_LINK,
    MAX_VALID_DAYS,
    MIN_KEY_LENGTH,
    mint_token,
    parse_revoked_ids,
    verify_token,
)

KEY = "k" * 40
TODAY = date(2026, 9, 26)
LINK_ID = "0123456789ab"


def _token(until: str = "2026-10-31", link_id: str = LINK_ID, key: str = KEY) -> str:
    return mint_token(key=key, link_id=link_id, until=date.fromisoformat(until), today=TODAY)


def test_the_bounds_are_pinned() -> None:
    """Bucket A. All are the session's PROPOSED defaults (ADR-0134).
    Turns red if one moves."""
    assert MAX_VALID_DAYS == 90
    assert DAILY_SESSIONS_PER_LINK == 12
    assert MIN_KEY_LENGTH == 32
    assert invite_links.COOKIE_NAME == "quorum_invite"


def test_a_minted_token_verifies_and_names_its_link() -> None:
    """Turns red if a genuine token is refused."""
    token = _token()
    assert token.startswith("v1.0123456789ab.2026-10-31.")
    assert verify_token(token, key=KEY, revoked=frozenset(), today=TODAY) == LINK_ID


@pytest.mark.parametrize(
    "mangle",
    [
        lambda t: t[:-1] + ("0" if t[-1] != "0" else "1"),  # signature changed
        lambda t: t.replace("2026-10-31", "2026-12-24"),  # end date changed
        lambda t: t.replace(LINK_ID, "ffffffffffff"),  # id changed
        lambda t: t.replace("v1.", "v2.", 1),  # version changed
        lambda t: t + "0",  # too long
        lambda t: "",
        lambda t: "v1.x.y.z",
        lambda t: t.upper(),
    ],
    ids=["sig", "until", "id", "version", "long", "empty", "shape", "upper"],
)
def test_a_changed_token_is_refused(mangle: object) -> None:
    """Forgery. Turns red if any part of the token can change and still
    verify."""
    bad = mangle(_token())  # type: ignore[operator]
    assert verify_token(bad, key=KEY, revoked=frozenset(), today=TODAY) is None


def test_another_key_does_not_verify() -> None:
    """Rotating the key revokes every link. Turns red if it does not."""
    assert verify_token(_token(), key="z" * 40, revoked=frozenset(), today=TODAY) is None


def test_the_end_date_is_inclusive_in_utc() -> None:
    """A link ending 2026-10-31 works on that day and not the next."""
    token = _token("2026-10-31")
    assert verify_token(token, key=KEY, revoked=frozenset(), today=date(2026, 10, 31)) == LINK_ID
    assert verify_token(token, key=KEY, revoked=frozenset(), today=date(2026, 11, 1)) is None


def test_a_revoked_link_is_refused() -> None:
    """Turns red if the revoked list is not consulted."""
    token = _token()
    assert verify_token(token, key=KEY, revoked=frozenset({LINK_ID}), today=TODAY) is None
    assert verify_token(token, key=KEY, revoked=frozenset({"ffffffffffff"}), today=TODAY) == LINK_ID


def test_minting_refuses_a_far_end_date_and_verifying_refuses_one_too() -> None:
    """Literals on both sides: 90 days ahead mints; 91 does not. A token
    somehow signed for longer is refused when verified."""
    _token("2026-12-25")  # 90 days after 2026-09-26
    with pytest.raises(ValueError, match="90 days"):
        _token("2026-12-26")
    long_lived = mint_token(
        key=KEY, link_id=LINK_ID, until=date(2027, 6, 1), today=date(2027, 3, 10)
    )
    assert verify_token(long_lived, key=KEY, revoked=frozenset(), today=TODAY) is None


def test_minting_refuses_a_past_end_date() -> None:
    """Turns red if a link can be minted already expired."""
    with pytest.raises(ValueError, match="already"):
        _token("2026-09-25")


def test_minting_refuses_a_short_key() -> None:
    """Literals: 32 characters mints; 31 does not."""
    _token(key="k" * 32)
    with pytest.raises(ValueError, match="at least 32"):
        _token(key="k" * 31)


def test_a_short_key_never_verifies() -> None:
    """Turns red if a key below the minimum is accepted when verifying. The
    token is signed with that same short key, so only the length check can
    refuse it; the 32-character partner shows the same shape verifies."""
    short = "k" * 31
    until = date(2026, 10, 31)
    token = f"v1.{LINK_ID}.{until.isoformat()}.{invite_links._signature(short, LINK_ID, until)}"
    assert verify_token(token, key=short, revoked=frozenset(), today=TODAY) is None
    ok = "k" * 32
    good = f"v1.{LINK_ID}.{until.isoformat()}.{invite_links._signature(ok, LINK_ID, until)}"
    assert verify_token(good, key=ok, revoked=frozenset(), today=TODAY) == LINK_ID


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", frozenset()),
        ("  ", frozenset()),
        ("0123456789ab", frozenset({"0123456789ab"})),
        ("0123456789ab, ffffffffffff", frozenset({"0123456789ab", "ffffffffffff"})),
    ],
)
def test_revoked_ids_parse(raw: str, expected: frozenset[str]) -> None:
    """Turns red if a valid list of ids is refused or misread."""
    assert parse_revoked_ids(raw) == expected


def test_an_upper_case_revoked_id_is_read_as_lower_case() -> None:
    """The likely typo. Turns red if it is refused (stopping the app over a
    routine revocation) or kept upper-case (revoking nothing)."""
    assert parse_revoked_ids("0123456789AB") == frozenset({"0123456789ab"})


def test_one_leaked_link_cannot_use_up_the_sites_daily_ceiling() -> None:
    """Each new session is a new account that may spend DAILY_CAP_USD. Turns
    red if a link's daily sessions times that cap reaches the site-wide
    ceiling, so that one leaked link could shut every other visitor out
    (review measured 50 x 0.40 = 20.00 against 5.00)."""
    from product_app.costs import DAILY_CAP_USD, GLOBAL_DAILY_CEILING_USD

    assert DAILY_SESSIONS_PER_LINK * DAILY_CAP_USD < GLOBAL_DAILY_CEILING_USD


@pytest.mark.parametrize("raw", ["xyz", "0123456789", "0123456789ab,", "0123456789abz"])
def test_a_malformed_revoked_id_is_refused(raw: str) -> None:
    """A typo here would leave a link live that the operator meant to
    revoke. Turns red if a malformed id is accepted silently."""
    with pytest.raises(ValueError, match="INVITE_LINK_REVOKED_IDS"):
        parse_revoked_ids(raw)


def test_the_mint_command_reads_the_key_from_stdin(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The operator's only way to make a link. Turns red if the key is taken
    from anywhere but stdin, or the printed link does not verify."""
    monkeypatch.setattr("sys.stdin", io.StringIO(KEY + "\n"))
    # A different key in the environment must be ignored.
    monkeypatch.setenv("INVITE_LINK_SIGNING_KEY", "e" * 40)
    code = invite_links.main(
        ["mint", "--until", "2026-10-31", "--base-url", "https://quorum.stackclimb.com"],
        today=TODAY,
    )
    assert code == 0
    out = capsys.readouterr().out.splitlines()
    link = next(line for line in out if line.startswith("link: "))[len("link: ") :]
    link_id = next(line for line in out if line.startswith("id: "))[len("id: ") :]
    assert link.startswith("https://quorum.stackclimb.com/ui/invite#v1.")
    token = link.split("#", 1)[1]
    assert verify_token(token, key=KEY, revoked=frozenset(), today=TODAY) == link_id
    assert verify_token(token, key="e" * 40, revoked=frozenset(), today=TODAY) is None
    assert KEY not in "\n".join(out)


def test_two_minted_links_have_different_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turns red if ids repeat, which would make revoking one revoke both."""
    ids = set()
    for _ in range(20):
        monkeypatch.setattr("sys.stdin", io.StringIO(KEY))
        buf = io.StringIO()
        monkeypatch.setattr("sys.stdout", buf)
        invite_links.main(
            ["mint", "--until", "2026-10-31", "--base-url", "https://x.test"], today=TODAY
        )
        ids.add(next(line for line in buf.getvalue().splitlines() if line.startswith("id: ")))
    assert len(ids) == 20


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["mint"],
        ["mint", "--until", "2026-10-31"],
        ["mint", "--until", "31/10/2026", "--base-url", "https://x.test"],
        ["mint", "--until", "20261031", "--base-url", "https://x.test"],
        ["mint", "--until", "2026-10-31", "--base-url", "http://x.test"],
    ],
)
def test_the_mint_command_refuses_bad_arguments(
    argv: list[str], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turns red if the command mints with a missing or malformed end date,
    or a base URL that is not https."""
    monkeypatch.setattr("sys.stdin", io.StringIO(KEY))
    assert invite_links.main(argv, today=TODAY) == 2
    assert "link:" not in capsys.readouterr().out


def test_the_mint_command_refuses_a_short_key(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("short"))
    assert (
        invite_links.main(
            ["mint", "--until", "2026-10-31", "--base-url", "https://x.test"], today=TODAY
        )
        == 2
    )
    assert "at least 32" in capsys.readouterr().err


def test_the_module_runs_as_the_mint_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """``python -m product_app.invite_links mint`` is what the operator runs.
    Turns red if the module stops being runnable that way."""
    import runpy
    import sys

    monkeypatch.setattr(sys, "argv", ["invite_links"])
    with pytest.raises(SystemExit) as done:
        runpy.run_module("product_app.invite_links", run_name="__main__")
    assert done.value.code == 2


def test_the_counter_counts_requests_with_an_invite() -> None:
    """Cardinality: one call, one count."""
    before = invite_links.invite_request_count()
    invite_links.record_invite_request()
    assert invite_links.invite_request_count() == before + 1


@pytest.mark.parametrize(
    ("env", "exit_ok", "shown"),
    [
        ({"INVITE_LINK_SIGNING_KEY": "short-key-9"}, False, "at least 32 characters"),
        ({"INVITE_LINK_REVOKED_IDS": "not-an-id"}, False, "INVITE_LINK_REVOKED_IDS item 1"),
        (
            {"INVITE_LINK_SIGNING_KEY": "k" * 40, "INVITE_LINK_REVOKED_IDS": "0123456789ab"},
            True,
            "",
        ),
    ],
    ids=["short-key", "bad-revoked-id", "good"],
)
def test_the_app_refuses_to_start_on_a_bad_invite_setting(
    env: dict[str, str], exit_ok: bool, shown: str
) -> None:
    """End to end in a fresh interpreter. Turns red if main.py stops
    checking the invite settings at import. The key is never quoted."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    done = subprocess.run(
        [sys.executable, "-c", "import product_app.main"],
        env={**os.environ, **env, "PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert (done.returncode == 0) is exit_ok, done.stderr[-2000:]
    if not exit_ok:
        assert shown in done.stderr
        assert "short-key-9" not in done.stderr


@pytest.mark.parametrize("bad_id", ["0123456789", "0123456789AB", "0123456789abc", "zzzzzzzzzzzz"])
def test_minting_refuses_a_malformed_link_id(bad_id: str) -> None:
    """Turns red if a token can be minted with an id the verifier and the
    revoked list would never accept."""
    with pytest.raises(ValueError, match="12 lower-case hex digits"):
        mint_token(key=KEY, link_id=bad_id, until=date(2026, 10, 31), today=TODAY)
