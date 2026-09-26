"""The session-limit allow-list (W31, CHG-022 item 2, ADR-0133).

Named, dated addresses or ranges whose visitors are not held to the two
per-network session limits: the per-minute session limiter and the daily
new-session cap. Nothing here is read by a spend limit; ``DAILY_CAP_USD``
and ``GLOBAL_DAILY_CEILING_USD`` count accounts and the site, never
addresses.

The list is one setting, ``SESSION_CAP_EXEMPT_NETWORKS``, a JSON list::

    [{"name": "Acme hiring", "network": "81.2.69.0/24", "until": "2026-10-31"}]

An entry applies through the end of its ``until`` day in UTC. A malformed
list stops the app at startup; check a value first, from the repository
root, with::

    pbpaste | PYTHONPATH=src uv run python -m product_app.session_exemptions --check

which reads the value from standard input (never shell history) and prints
only counts and end dates, or the refusal. The package is not installed into
the virtual environment, so ``PYTHONPATH=src`` is required. Failure modes:
``docs/analysis/2026-09-26-w31-session-limit-allow-list-failure-modes.md``.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import sys
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

logger = logging.getLogger(__name__)

#: The owner's bounds (CHG-022 item 2): no entry wider than these.
MAX_IPV4_PREFIX = 24
MAX_IPV6_PREFIX = 48
#: PROPOSED — AWAITING OWNER: the session's bounds (ADR-0133), built at the
#: safe default until the owner decides otherwise: an end date at most this
#: far ahead, at most this many entries, names at most this long. Refusing
#: non-public ranges (``_network``) is the fourth.
MAX_VALID_DAYS = 366
MAX_ENTRIES = 50
MAX_NAME_LENGTH = 80

_KEYS = frozenset({"name", "network", "until"})
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class Exemption:
    name: str
    network: ipaddress.IPv4Network | ipaddress.IPv6Network
    until: date


def _today() -> date:
    return datetime.now(UTC).date()


def _network(value: object, where: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    if not isinstance(value, str):
        raise ValueError(f"{where}: network is not an address or range")
    try:
        network = ipaddress.ip_network(value.strip(), strict=True)
    except ValueError as exc:
        if "host bits" in str(exc):
            raise ValueError(
                f"{where}: network has host bits set; give the range's start"
            ) from None
        raise ValueError(f"{where}: network is not an address or range") from None
    limit = MAX_IPV4_PREFIX if network.version == 4 else MAX_IPV6_PREFIX
    if network.prefixlen < limit:
        raise ValueError(f"{where}: network is wider than /{limit}")
    if not network.is_global:
        raise ValueError(f"{where}: network is not a public range")
    return network


def _until(value: object, where: str, today: date) -> date:
    try:
        # fullmatch first: fromisoformat also takes 20261031 and 2026-W44-5.
        if not isinstance(value, str) or not _DATE.fullmatch(value):
            raise ValueError
        until = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{where}: until is not a date written YYYY-MM-DD") from None
    if until > today + timedelta(days=MAX_VALID_DAYS):
        raise ValueError(f"{where}: until is more than {MAX_VALID_DAYS} days ahead")
    return until


def parse_exemptions(raw: str, *, today: date) -> tuple[Exemption, ...]:
    """Parse the setting, or raise ``ValueError`` naming the entry's position.

    Messages never quote an address or a name: they reach the startup log.
    """
    if not raw.strip():
        return ()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        # exc.msg is the parser's generic message; it never quotes the input.
        hint = ""
        if any(q in raw for q in "\u201c\u201d\u2018\u2019"):
            hint = "; it contains curly quotes, use straight double quotes"
        raise ValueError(
            f"SESSION_CAP_EXEMPT_NETWORKS is not JSON ({exc.msg} at column {exc.colno}){hint}"
        ) from None
    if not isinstance(data, list):
        raise ValueError("SESSION_CAP_EXEMPT_NETWORKS must be a JSON list")
    if len(data) > MAX_ENTRIES:
        raise ValueError(f"SESSION_CAP_EXEMPT_NETWORKS holds at most {MAX_ENTRIES} entries")
    entries: list[Exemption] = []
    names: set[str] = set()
    for position, item in enumerate(data, start=1):
        where = f"entry {position}"
        if not isinstance(item, dict) or set(item) != _KEYS:
            raise ValueError(f"{where}: needs exactly name, network and until")
        name = item["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{where}: needs a name")
        if len(name) > MAX_NAME_LENGTH:
            raise ValueError(f"{where}: name is longer than {MAX_NAME_LENGTH} characters")
        if name.strip() in names:
            raise ValueError(f"{where}: name is used twice")
        names.add(name.strip())
        entries.append(
            Exemption(
                name=name.strip(),
                network=_network(item["network"], where),
                until=_until(item["until"], where, today),
            )
        )
    return tuple(entries)


def exemption_for(address: str, entries: tuple[Exemption, ...], *, today: date) -> Exemption | None:
    """The active entry covering ``address`` (the visitor's full address)."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    for entry in entries:
        if entry.until >= today and ip in entry.network:
            return entry
    return None


def summarise(entries: tuple[Exemption, ...], *, today: date) -> str:
    """Counts and end dates only: no name, no address."""
    active = sorted({e.until.isoformat() for e in entries if e.until >= today})
    expired = sum(1 for e in entries if e.until < today)
    text = f"{len(entries)} entries: {len(entries) - expired} active, {expired} expired"
    if active:
        text += "; active until " + ", ".join(active)
    return text


# The parsed setting, keyed on its raw text so a changed setting is re-read.
_cache: tuple[str, tuple[Exemption, ...]] | None = None
_lock = threading.Lock()
_exempted = 0


def reset_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def configured() -> tuple[Exemption, ...]:
    """The configured list. Raises ``ValueError`` if it is malformed."""
    global _cache
    from product_app.config import settings  # late: tests patch the setting

    raw = settings.session_cap_exempt_networks
    with _lock:
        if _cache is not None and _cache[0] == raw:
            return _cache[1]
    entries = parse_exemptions(raw, today=_today())
    with _lock:
        _cache = (raw, entries)
    return entries


def is_exempt(address: str | None) -> bool:
    """Whether the visitor at ``address`` is on the active allow-list."""
    if address is None:
        return False
    return exemption_for(address, configured(), today=_today()) is not None


def record_exempted_request() -> None:
    global _exempted
    with _lock:
        _exempted += 1


def exempted_request_count() -> int:
    with _lock:
        return _exempted


def status() -> dict[str, int]:
    """The operations-page figures: entry counts and exempted requests."""
    entries = configured()
    today = _today()
    expired = sum(1 for e in entries if e.until < today)
    return {
        "active_entries": len(entries) - expired,
        "expired_entries": expired,
        "exempted_requests": exempted_request_count(),
    }


def log_configuration(entries: tuple[Exemption, ...], *, today: date) -> None:
    logger.info("session-limit allow-list: %s", summarise(entries, today=today))


def main(argv: list[str], *, today: date | None = None) -> int:
    """``--check``: parse standard input and print the summary, or the error."""
    if argv != ["--check"]:
        print("usage: python -m product_app.session_exemptions --check < value", file=sys.stderr)
        return 2
    day = today or _today()
    try:
        entries = parse_exemptions(sys.stdin.read(), today=day)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(f"would load {summarise(entries, today=day)}")
    ended = sum(1 for e in entries if e.until < day)
    if ended:
        print(f"warning: {ended} of them already ended and will not apply", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
