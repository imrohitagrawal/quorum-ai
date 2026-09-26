"""W31 — the session-limit allow-list (CHG-022 item 2, ADR-0133).

Named, dated addresses or ranges that lift ONLY the two per-network session
limits (the per-minute limiter and the daily new-session cap), never a spend
limit. Failure modes first:
``docs/analysis/2026-09-26-w31-session-limit-allow-list-failure-modes.md``.
"""

from __future__ import annotations

import json
import logging
from datetime import date

import pytest

from product_app import session_exemptions
from product_app.session_exemptions import (
    MAX_ENTRIES,
    MAX_IPV4_PREFIX,
    MAX_IPV6_PREFIX,
    MAX_VALID_DAYS,
    Exemption,
    exemption_for,
    parse_exemptions,
    summarise,
)

TODAY = date(2026, 9, 26)


def _raw(*entries: dict[str, object]) -> str:
    return json.dumps(list(entries))


def _entry(
    name: str = "Acme hiring", network: str = "81.2.69.0/24", until: str = "2026-10-31"
) -> dict[str, object]:
    return {"name": name, "network": network, "until": until}


def test_the_bounds_are_pinned() -> None:
    """Bucket A. Turns red if a bound moves. /24 and /48 are the owner's
    (CHG-022 item 2); 366 days and 50 entries are the session's PROPOSED
    defaults (ADR-0133)."""
    assert MAX_IPV4_PREFIX == 24
    assert MAX_IPV6_PREFIX == 48
    assert MAX_VALID_DAYS == 366
    assert MAX_ENTRIES == 50
    assert session_exemptions.MAX_NAME_LENGTH == 80


def test_an_empty_setting_is_an_empty_list() -> None:
    """Turns red if an unset secret is refused (the shipped default is unset)."""
    assert parse_exemptions("", today=TODAY) == ()
    assert parse_exemptions("   ", today=TODAY) == ()


def test_a_good_list_parses() -> None:
    """Turns red if a valid single address, IPv4 /24 or IPv6 /48 is refused."""
    got = parse_exemptions(
        _raw(
            _entry(),
            _entry(name="One laptop", network="89.160.20.7", until="2026-09-26"),
            _entry(name="Acme v6", network="2a02:26f0:aa::/48", until="2027-09-27"),
        ),
        today=TODAY,
    )
    assert [(e.name, str(e.network), e.until.isoformat()) for e in got] == [
        ("Acme hiring", "81.2.69.0/24", "2026-10-31"),
        ("One laptop", "89.160.20.7/32", "2026-09-26"),
        ("Acme v6", "2a02:26f0:aa::/48", "2027-09-27"),
    ]


@pytest.mark.parametrize(
    ("network", "why"),
    [
        ("81.2.68.0/23", "wider than /24"),
        ("0.0.0.0/0", "wider than /24"),
        ("2a02:26f0::/47", "wider than /48"),
        ("81.2.69.7/24", "host bits"),
        ("10.1.2.0/24", "not a public"),
        ("172.19.4.0/24", "not a public"),
        ("127.0.0.1", "not a public"),
        ("169.254.1.0/24", "not a public"),
        ("fdaa:87::/48", "not a public"),
        ("192.0.2.0/24", "not a public"),
        ("2001:db8:aa::/48", "not a public"),
        ("::ffff:81.2.69.7", "IPv4-mapped"),
        ("not-a-network", "not an address"),
    ],
)
def test_a_bad_network_is_refused(network: str, why: str) -> None:
    """Turns red if a too-wide, ambiguous, private or malformed entry loads.
    A private range is refused because the Fly proxy's own range would exempt
    every visitor."""
    with pytest.raises(ValueError, match=why):
        parse_exemptions(_raw(_entry(network=network)), today=TODAY)


def test_the_width_bound_is_exact() -> None:
    """Literals on both sides: /24 and /48 load; /23 and /47 do not."""
    parse_exemptions(_raw(_entry(network="81.2.69.0/24")), today=TODAY)
    parse_exemptions(_raw(_entry(network="2a02:26f0:aa::/48")), today=TODAY)
    with pytest.raises(ValueError):
        parse_exemptions(_raw(_entry(network="81.2.68.0/23")), today=TODAY)
    with pytest.raises(ValueError):
        parse_exemptions(_raw(_entry(network="2a02:26f0::/47")), today=TODAY)


@pytest.mark.parametrize(
    ("raw", "why"),
    [
        ("{", "not JSON"),
        ('{"name": "x"}', "a JSON list"),
        (json.dumps(["x"]), "entry 1"),
        (json.dumps([{"name": "a", "network": "81.2.69.0/24"}]), "name, network and until"),
        (json.dumps([{**_entry(), "note": "x"}]), "name, network and until"),
        (_raw(_entry(name="")), "a name"),
        (_raw(_entry(name="   ")), "a name"),
        (_raw(_entry(name="x" * 81)), "80 characters"),
        (_raw(_entry(until="31/10/2026")), "YYYY-MM-DD"),
        (json.dumps([{**_entry(), "until": 20261031}]), "YYYY-MM-DD"),
        (_raw(_entry(until="2027-09-28")), "366 days"),
        (_raw(_entry(), _entry(network="89.160.20.0/24")), "used twice"),
    ],
)
def test_a_malformed_list_is_refused(raw: str, why: str) -> None:
    """Turns red if a malformed list loads instead of stopping the start."""
    with pytest.raises(ValueError, match=why):
        parse_exemptions(raw, today=TODAY)


def test_the_end_date_bound_is_exact() -> None:
    """366 days ahead loads; 367 does not (literals, not the constant)."""
    parse_exemptions(_raw(_entry(until="2027-09-27")), today=TODAY)
    with pytest.raises(ValueError):
        parse_exemptions(_raw(_entry(until="2027-09-28")), today=TODAY)


def test_the_entry_count_bound_is_exact() -> None:
    """50 entries load; 51 do not."""

    def many(n: int) -> str:
        return _raw(*[_entry(name=f"n{i}", network=f"89.160.20.{i}") for i in range(n)])

    assert len(parse_exemptions(many(50), today=TODAY)) == 50
    with pytest.raises(ValueError, match="at most 50"):
        parse_exemptions(many(51), today=TODAY)


def test_an_expired_entry_loads_but_does_not_apply() -> None:
    """Expired entries must not stop the app. Turns red if one is refused
    at startup, or still matches."""
    (entry,) = parse_exemptions(_raw(_entry(until="2026-09-25")), today=TODAY)
    assert exemption_for("81.2.69.9", (entry,), today=TODAY) is None


def test_an_error_names_the_position_not_the_address() -> None:
    """Turns red if a refusal message quotes the address (it reaches logs)."""
    with pytest.raises(ValueError) as caught:
        parse_exemptions(_raw(_entry(), _entry(name="b", network="81.2.68.0/23")), today=TODAY)
    assert "entry 2" in str(caught.value)
    assert "81.2.68" not in str(caught.value)


def _one(network: str, until: str = "2026-10-31") -> tuple[Exemption, ...]:
    return parse_exemptions(_raw(_entry(network=network, until=until)), today=TODAY)


@pytest.mark.parametrize(
    ("address", "network", "hit"),
    [
        ("81.2.69.9", "81.2.69.0/24", True),
        ("81.2.70.9", "81.2.69.0/24", False),
        ("89.160.20.7", "89.160.20.7", True),
        ("89.160.20.8", "89.160.20.7", False),
        ("2a02:26f0:aa:ff::1", "2a02:26f0:aa::/48", True),
        ("2a02:26f0:ab::1", "2a02:26f0:aa::/48", False),
        ("::ffff:81.2.69.9", "81.2.69.0/24", True),
        ("testclient", "81.2.69.0/24", False),
    ],
)
def test_matching_uses_the_visitors_full_address(address: str, network: str, hit: bool) -> None:
    """Turns red if matching uses W30's /64 key (a /128 entry would then match
    a whole /64) or misses an IPv4-mapped visitor."""
    assert (exemption_for(address, _one(network), today=TODAY) is not None) is hit


def test_the_end_date_is_inclusive_in_utc() -> None:
    """An entry ending 2026-10-31 applies on that day and not the next."""
    entries = _one("81.2.69.0/24", until="2026-10-31")
    assert exemption_for("81.2.69.9", entries, today=date(2026, 10, 31)) is not None
    assert exemption_for("81.2.69.9", entries, today=date(2026, 11, 1)) is None


def test_the_summary_names_counts_and_dates_only() -> None:
    """Turns red if the startup summary carries a name or an address."""
    entries = parse_exemptions(
        _raw(_entry(), _entry(name="Old", network="89.160.20.0/24", until="2026-09-01")),
        today=TODAY,
    )
    text = summarise(entries, today=TODAY)
    assert text == "2 entries: 1 active, 1 expired; active until 2026-10-31"
    for secret in ("Acme", "Old", "81.2.69", "89.160.20"):
        assert secret not in text


def test_the_check_command_reads_stdin_and_prints_only_the_summary(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The owner's pre-flight check. Turns red if it echoes the list or
    takes the value from its arguments (shell history)."""
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(_raw(_entry())))
    assert session_exemptions.main(["--check"], today=TODAY) == 0
    out = capsys.readouterr().out
    assert "1 entries: 1 active, 0 expired" in out
    assert "81.2.69" not in out and "Acme" not in out

    monkeypatch.setattr("sys.stdin", io.StringIO(_raw(_entry(network="81.2.68.0/23"))))
    assert session_exemptions.main(["--check"], today=TODAY) == 2
    assert "wider than /24" in capsys.readouterr().err


def test_the_startup_log_is_the_summary(caplog: pytest.LogCaptureFixture) -> None:
    """Turns red if startup logs anything but counts and dates."""
    caplog.set_level(logging.INFO, logger="product_app.session_exemptions")
    session_exemptions.log_configuration(_one("81.2.69.0/24"), today=TODAY)
    assert "session-limit allow-list: 1 entries: 1 active, 0 expired" in caplog.text
    assert "81.2.69" not in caplog.text


def test_the_counter_counts_exempted_requests() -> None:
    """Cardinality: one call, one count. Turns red if the counter does not
    move, or moves by more than one."""
    before = session_exemptions.exempted_request_count()
    session_exemptions.record_exempted_request()
    assert session_exemptions.exempted_request_count() == before + 1


def test_the_module_runs_as_the_check_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """``python -m product_app.session_exemptions --check`` is what the owner
    runs. Turns red if the module stops being runnable that way."""
    import io
    import runpy
    import sys

    monkeypatch.setattr(sys, "argv", ["session_exemptions", "--check"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    with pytest.raises(SystemExit) as done:
        runpy.run_module("product_app.session_exemptions", run_name="__main__")
    assert done.value.code == 0


@pytest.mark.parametrize(
    ("value", "exit_ok"),
    [
        ('[{"name": "a", "network": "81.2.68.0/23", "until": "2026-10-31"}]', False),
        ('[{"name": "a", "network": "81.2.69.0/24", "until": "2026-10-31"}]', True),
    ],
    ids=["too-wide", "good"],
)
def test_the_app_refuses_to_start_on_a_bad_list(value: str, exit_ok: bool) -> None:
    """The approved "refused at startup", end to end: a fresh interpreter
    imports the app with the setting. Turns red if main.py stops checking the
    list at import (the parser alone would still pass its own tests)."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "SESSION_CAP_EXEMPT_NETWORKS": value, "PYTHONPATH": str(root / "src")}
    done = subprocess.run(
        [sys.executable, "-c", "import product_app.main"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert (done.returncode == 0) is exit_ok, done.stderr[-2000:]
    if not exit_ok:
        assert "entry 1: network is wider than /24" in done.stderr
        assert "81.2.68" not in done.stderr


def test_status_counts_active_and_expired_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turns red if expired entries are reported as active, or not counted."""
    from product_app.config import settings

    raw = _raw(_entry(), _entry(name="Old", network="89.160.20.0/24", until="2026-09-01"))
    monkeypatch.setattr(settings, "session_cap_exempt_networks", raw)
    monkeypatch.setattr(session_exemptions, "_today", lambda: TODAY)
    session_exemptions.reset_cache()
    try:
        got = session_exemptions.status()
    finally:
        session_exemptions.reset_cache()
    assert got["active_entries"] == 1
    assert got["expired_entries"] == 1


def test_a_changed_setting_is_read_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turns red if the parsed list is cached regardless of the setting."""
    from product_app.config import settings

    monkeypatch.setattr(session_exemptions, "_today", lambda: TODAY)
    session_exemptions.reset_cache()
    try:
        monkeypatch.setattr(settings, "session_cap_exempt_networks", _raw(_entry()))
        assert len(session_exemptions.configured()) == 1
        monkeypatch.setattr(settings, "session_cap_exempt_networks", "")
        assert session_exemptions.configured() == ()
    finally:
        session_exemptions.reset_cache()


def test_the_check_command_refuses_other_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    """Turns red if the command accepts a value as an argument (shell
    history) instead of printing its usage."""
    assert session_exemptions.main(["[]"], today=TODAY) == 2
    assert "usage:" in capsys.readouterr().err
