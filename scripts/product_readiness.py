#!/usr/bin/env python3
"""Write ``docs/product-readiness.md`` from production's ``/status`` and ``/ready`` (ADR-0161).

The file states facts plus a verdict: when it was generated and from which
build; what production has in effect; what is switched on but idle because live
execution is off; what is built but switched off; and the verdict. The verdict
is "Ready" only when live execution is on, ``/ready`` reports ``ready``, and its
``live_readiness`` lists no reasons and says the global spending ceiling is not
reached. Anything else is "Not ready", with the reasons, and so is a ``/ready``
without those ``live_readiness`` fields. When either endpoint cannot be read,
the file says "unavailable" and the verdict is "unknown". A release decision is
a CHG row, not this file.

THE FILE CARRIES ITS OWN INPUT. The two responses are embedded at its end, in a
fenced JSON block, with the time and the URL they came from. The file must equal
:func:`render` over that block (``tests/unit/test_one_status_review_round_1.py``),
so a verdict typed by hand fails a test.

``make readiness`` runs this, and so does ``make handoff``. Each endpoint gets
ONE attempt with a short timeout, and a failure never fails the caller
(ADR-0045): the file is still written, saying what could not be read. Both
endpoints are free to call (AGENTS.md rule 18).

The file is in the completion check's scope (ADR-0162), so every "in
production" it writes sits in a unit that cites the build commit.

``--out PATH`` writes somewhere else; ``--base-url URL`` reads another server.
Only :data:`DEFAULT_BASE_URL` is called production: another server is named by
its URL, and its verdict says it is not production.
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = "https://quorum-ai.fly.dev"
DEFAULT_OUT = ROOT / "docs" / "product-readiness.md"
TIMEOUT_SECONDS = 8.0
#: An error body is read only this far: a reason, not a page.
_MAX_BODY_BYTES = 65536

#: Plain names for the ``/status`` switches a reader asks about. A switch not
#: named here is still listed, under its own key.
_SWITCH_NAMES = {
    "live_execution": "Live execution (paid model calls)",
    "judge_enabled": "The judge",
    "peer_critique_enabled": "Peer critique (setting)",
    "peer_critique_in_effect": "Peer critique (in effect)",
    "source_fetch_enabled": "Source page fetching (setting)",
    "source_pages_in_effect": "Source pages read (in effect)",
    "sign_in_enabled": "Sign-in",
    "invite_links.enabled": "Invite links",
    "model_catalog_loaded": "Model catalog loaded",
}


#: Switches that act only inside a live run: the judge judges real answers, and
#: pages are fetched and read for it. With live execution off no run reaches
#: them, so they are listed as idle, not as in effect (review round 1 of package B).
_NEEDS_LIVE = ("judge_enabled", "source_fetch_enabled", "source_pages_in_effect")
IDLE_HEADING = "Built and switched on, but idle while live execution is off: no run reaches them"


def _switches(status: dict[str, Any]) -> list[tuple[str, bool, str]]:
    """Every boolean in ``/status`` (one level of nesting): (key, value, its line)."""
    found: list[tuple[str, bool, str]] = []
    for key, value in status.items():
        pairs = (
            [(f"{key}.{inner}", item) for inner, item in value.items()]
            if isinstance(value, dict)
            else [(key, value)]
        )
        for name, item in pairs:
            if isinstance(item, bool):
                found.append((name, item, f"- {_SWITCH_NAMES.get(name, name)} (`{name}`)"))
    return found


def _facts(status: dict[str, Any]) -> list[str]:
    """The non-switch values of ``/status``, each as a quoted key and value."""
    lines = []
    for key, value in status.items():
        if isinstance(value, bool) or key == "build_sha":
            continue
        if isinstance(value, dict) and all(isinstance(v, bool) for v in value.values()):
            continue
        lines.append(f"- `{key}`: `{json.dumps(value, sort_keys=True)}`")
    return lines


def _live_readiness_reasons(ready: dict[str, Any]) -> list[str]:
    """What ``/ready``'s ``live_readiness`` says against live runs, or that it is missing."""
    live = ready.get("live_readiness")
    if not isinstance(live, dict):
        return [
            "`/ready` has no `live_readiness` object, so whether a live run can happen is "
            "not known."
        ]
    reasons: list[str] = []
    listed = live.get("reasons")
    if isinstance(listed, list):
        reasons.extend(str(reason) for reason in listed)
    else:
        reasons.append(
            "`/ready` has no `live_readiness.reasons` list, so what stands against a live "
            "run is not known."
        )
    ceiling = live.get("global_spend_ceiling_reached")
    if ceiling is True:
        reasons.append(
            "The global daily spending ceiling is reached "
            "(`live_readiness.global_spend_ceiling_reached` is true in `/ready`): new runs "
            "are answered by the local simulation, not by real models, while it stays so."
        )
    elif ceiling is not False:
        reasons.append(
            "`/ready` has no true-or-false `live_readiness.global_spend_ceiling_reached`, so "
            "whether spending is at the ceiling is not known."
        )
    return reasons


def verdict(status: dict[str, Any] | None, ready: dict[str, Any] | None) -> tuple[str, list[str]]:
    """("Ready" | "Not ready" | "unknown", the reasons)."""
    if status is None or ready is None:
        return "unknown", []
    reasons: list[str] = []
    if status.get("live_execution") is not True:
        reasons.append(
            "Live execution is off (`live_execution` is not true in `/status`): every query "
            "is answered by the local simulation, not by real models."
        )
    if ready.get("status") != "ready":
        reasons.append(f"`/ready` reports `{ready.get('status')}`, not `ready`.")
    reasons.extend(_live_readiness_reasons(ready))
    return ("Ready" if not reasons else "Not ready"), reasons


def _embedded(
    status: dict[str, Any] | None,
    ready: dict[str, Any] | None,
    generated_at: str,
    base: str,
) -> list[str]:
    """The fenced block holding what this file was rendered from.

    Keys keep the order the server sent them in (no ``sort_keys``): the lists
    above follow that order, and ``json.loads`` keeps it, so re-rendering the
    block gives the same file.
    """
    data = {"base_url": base, "generated_at": generated_at, "status": status, "ready": ready}
    return [
        "## The responses this file was generated from",
        "",
        "`render()` in `scripts/product_readiness.py`, run over this block, must give this"
        " file exactly; a test checks it. Do not edit the file by hand: run"
        " `make readiness`.",
        "",
        "```json",
        json.dumps(data, indent=2),
        "```",
        "",
    ]


def render(
    status: dict[str, Any] | None,
    ready: dict[str, Any] | None,
    generated_at: str,
    base_url: str = DEFAULT_BASE_URL,
) -> str:
    """The text of the readiness file, for the responses read from ``base_url``."""
    base = base_url.rstrip("/")
    production = base == DEFAULT_BASE_URL
    build = str(status.get("build_sha") or "unknown") if status is not None else None
    short = build[:7] if build else None
    said, reasons = verdict(status, ready)
    if production:
        source = (
            f"Generated by `make readiness` at {generated_at}, from production's `GET /status`"
            f" and `GET /ready` ({base}). It is true when generated and ages after:"
            " production moves after every merge. For the current value, run `make readiness`"
            f" again, or `GET /status` on {base}."
        )
    else:
        source = (
            f"Generated by `scripts/product_readiness.py` at {generated_at}, from `GET /status`"
            f" and `GET /ready` on {base}. That server is not production ({DEFAULT_BASE_URL}),"
            " so nothing here describes production."
        )
    out = [
        "# Product readiness",
        "",
        source + " A release decision is a CHG row in `docs/19-change-control-log.md`, not"
        " this file (ADR-0161).",
        "",
        "## Verdict",
        "",
    ]
    if said == "unknown":
        missing = [
            name
            for name, value in (("GET /status", status), ("GET /ready", ready))
            if value is None
        ]
        out += [
            "Verdict: unknown" + ("" if production else f" for {base}, which is not production"),
            "",
            f"{' and '.join(missing)} unavailable when this was generated, so the verdict"
            " cannot be known. Run `make readiness` again with the network.",
        ]
    elif production:
        out.append(f"Verdict: {said} (production build {short}, generated {generated_at})")
        out += [f"- {reason}" for reason in reasons]
    else:
        out.append(
            f"Verdict: {said} for {base}, which is not production"
            f" (build {short}, generated {generated_at})"
        )
        out += [f"- {reason}" for reason in reasons]
    out += [""]

    if status is None:
        out += [
            "## In effect: unavailable",
            "",
            "`GET /status` could not be read, so neither what is in effect nor what is"
            " switched off is known.",
            "",
        ]
        return "\n".join(out + _embedded(status, ready, generated_at, base))

    live_off = status.get("live_execution") is not True
    switches = _switches(status)
    idle = [line for name, on, line in switches if on and live_off and name in _NEEDS_LIVE]
    on = [
        line for name, value, line in switches if value and not (live_off and name in _NEEDS_LIVE)
    ]
    off = [line for _name, value, line in switches if not value]
    runs = "Production runs" if production else f"The server at {base} runs"
    out += [
        f"## In effect in production at build {short}"
        if production
        else f"## In effect at {base} (not production), build {short}",
        "",
        f"{runs} build `{build}`"
        f" (version `{status.get('version')}`, environment `{status.get('environment')}`).",
        *(on or ["- None"]),
        "",
    ]
    if idle:
        out += [f"## {IDLE_HEADING}", "", *idle, ""]
    out += [
        "## Built but switched off",
        "",
        *(off or ["- None"]),
        "",
        "## Other values from `/status`",
        "",
        *_facts(status),
        "",
    ]
    if ready is None:
        out += ["`GET /ready` was unavailable when this was generated.", ""]
    return "\n".join(out + _embedded(status, ready, generated_at, base))


def _tls_context() -> ssl.SSLContext:
    """The default TLS context, with ``certifi``'s certificates when it is installed.

    A python.org build on macOS ships no certificate store until its "Install
    Certificates" step runs, and every fetch then fails certificate checks.
    ``certifi`` is in this project's environment; without it, the default stands.
    """
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def fetch(url: str, timeout: float = TIMEOUT_SECONDS) -> tuple[dict[str, Any] | None, str]:
    """One GET of a JSON endpoint: (the body, "") or (None, why it failed). Never raises.

    ``/ready`` may answer 503 with a JSON body when production is not ready; that
    body is still the answer, so an HTTP error with a JSON body is read.
    """
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(  # noqa: S310
            request, timeout=timeout, context=_tls_context()
        ) as response:
            raw = response.read(_MAX_BODY_BYTES)
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read(_MAX_BODY_BYTES)
        except Exception as inner:  # noqa: BLE001 — ADR-0045: degrade, never abort
            return None, f"HTTP {exc.code}, body unreadable: {inner!r}"
        finally:
            exc.close()
    except Exception as exc:  # noqa: BLE001 — ADR-0045: degrade, never abort
        return None, repr(exc)
    try:
        body = json.loads(raw)
    except ValueError as exc:
        return None, f"not JSON: {exc}"
    if not isinstance(body, dict):
        return None, "not a JSON object"
    return body, ""


def now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write(out: Path = DEFAULT_OUT, base_url: str = DEFAULT_BASE_URL) -> tuple[str, list[str]]:
    """Fetch both endpoints and write the file. Returns its verdict and any fetch failures."""
    base = base_url.rstrip("/")
    status, status_error = fetch(f"{base}/status")
    ready, ready_error = fetch(f"{base}/ready")
    text = render(status, ready, now_utc(), base_url=base)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    failures = [
        f"{name}: {error}"
        for name, error in (("/status", status_error), ("/ready", ready_error))
        if error
    ]
    return verdict(status, ready)[0], failures


def _shown(path: Path) -> str:
    """``path`` relative to the repository when it is inside it.

    The handoff quotes this line, and a home-directory path must not land in a
    committed file.
    """
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where to write the file")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="the server to read")
    args = parser.parse_args(argv)
    try:
        said, failures = write(args.out, args.base_url)
    except Exception as exc:  # noqa: BLE001 — ADR-0045: never fail the caller
        print(f"product readiness: unavailable: could not write {_shown(args.out)}: {exc!r}")
        return 0
    for failure in failures:
        print(f"product readiness: unavailable: {failure}", file=sys.stderr)
    print(f"product readiness: verdict {said}, written to {_shown(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
