"""Structured JSON logging for production.

Production log aggregators (Logtail, Datadog, Grafana Loki) index
fields. The default ``logging.basicConfig`` output is a flat
human-readable string with the data hidden in positional formatters;
an aggregator can grep for it but cannot filter on ``level=ERROR``
without a regex against every line.

This module wires a custom :class:`logging.Formatter` that emits one
JSON object per record. The shape is intentionally small — just
timestamp, level, logger, message, and source location — so existing
``logger.info("foo %s", x)`` calls do not need to change. Anything
more structured should be added to ``extra={...}`` and a follow-up
formatter that walks ``record.__dict__`` can fold it in.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from types import TracebackType
from typing import Any

#: Patterns for secret-shaped substrings (issue #313). Applied to the
#: FINAL rendered JSON line, not to individual fields, so it covers the
#: ``message``, the ``exception`` traceback text, and any ``extra={...}``
#: value uniformly — whichever field a future call site happens to log
#: a credential through.
#:
#: This is defense in depth, not a fix to any specific call site: the 9
#: confirmed raw-exception call sites (feedback_store.py:521,
#: run_history_store.py:416, feedback_audit.py:685/691/995,
#: store_reconnect.py:325/366, query_runs.py:2358/2492) log
#: ``str(exception)`` with no scrubbing today. None of those exception
#: types currently carry a real secret (see issue #313 — LATENT, not
#: LIVE), but nothing enforced that property before this filter, and nothing
#: stops a future call site from reusing one of those ``except`` blocks for
#: something that does carry a credential.
#:
#: Order matters: the ``Bearer``/assignment patterns run first because they
#: also match plain-hex or short values that the bare-key-shape pattern
#: below would otherwise miss; the bare-key-shape pattern then catches
#: prefixed keys (``sk-...``, ``AKIA...``) that appear with no label at all.
_REDACTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    # "Bearer <token>" — the exact shape of an Authorization header value,
    # per providers.py/feedback_audit.py/readiness.py's `f"Bearer {key}"`.
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    # "api_key=...", "access_token: ...", "password=...", etc. — a labeled
    # credential assignment, in either query-string (``=``) or
    # structured-log (``: ``) shape, bare OR quoted on either side of the
    # separator: ``password=hunter2``, ``password="hunter2"`` (quoted
    # VALUE), and ``'password': 'hunter2'`` (quoted LABEL and value — the
    # Python-repr/JSON-ish shape a dict's ``__str__`` produces).
    #
    # This pattern is applied both to raw text (the record-factory path,
    # where a literal ``"`` is a single character) AND to the
    # ``json.dumps``-ed final string (``JsonFormatter.format``, where a
    # literal ``"`` from the original text has been escaped to ``\"``) —
    # ``QUOTE`` matches either form. Every quote is captured and its CLOSE
    # is matched via a BACKREFERENCE to the same alternative
    # (``\1``/``\2``), never an independent optional quote on each side.
    # An earlier version used two independent ``["']?`` (unpaired,
    # optional on each side) and it corrupted the output: for an unquoted
    # value sitting at the end of the JSON string (``..."message":
    # "...api_key=abcdef0123456789ZZZtopsecret"``), the optional trailing
    # quote matched the JSON field's own STRUCTURAL closing ``"`` — which
    # is a real ``"`` character at that position, no different from a
    # quote that was genuinely part of the value — and replaced it with
    # ``[REDACTED]``, producing invalid JSON
    # (``tests/unit/test_logging_config_redaction.py::test_key_value_assignment_secret_is_redacted``
    # went from green to a ``JSONDecodeError`` under that version). Pairing
    # every open quote with a same-type close via backreference means an
    # unquoted value never has ANY trailing quote consumed — it falls to
    # the bare (no-quote) alternative instead, which cannot eat a
    # neighbouring structural character because it has no trailing group
    # at all.
    re.compile(
        r"(?i)(?:(\\\"|\"|')\b(api[_-]?key|access[_-]?token|auth[_-]?token|"
        r"secret[_-]?key|client[_-]?secret|password|authorization)\b\1|"
        r"\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|secret[_-]?key|"
        r"client[_-]?secret|password|authorization)\b)"
        r"\s*[:=]\s*"
        r"(?:(\\\"|\"|')[A-Za-z0-9._~+/=-]{6,}\3|[A-Za-z0-9._~+/=-]{6,})"
    ),
    # Bare key-shaped tokens with no label: OpenRouter/OpenAI-style
    # ``sk-...`` keys (the exact shape asserted secret in
    # tests/security/test_release_security_redaction.py) and AWS-style
    # ``AKIA...`` access-key IDs.
    re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)

_REDACTED = "[REDACTED]"

#: Standard ``logging.LogRecord`` attributes — everything else in
#: ``record.__dict__`` came from a call site's ``extra={...}``. Shared by
#: ``JsonFormatter.format`` (which folds extras into the JSON payload) and
#: ``install_redaction_record_factory``'s ``factory`` (which must redact
#: those same extra values before Sentry's breadcrumb/event capture ever
#: sees them — see that function's docstring, "Scope: extra fields" note).
_RESERVED_RECORD_ATTRS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
}

#: Module-level, not "does the CURRENT factory carry a marker attribute"
#: (see the docstring's "Idempotency" section for why the latter is unsafe).
_redaction_factory_installed = False


def _redact_secrets(text: str) -> str:
    """Scrub secret-shaped substrings from a formatted log line.

    Applied to the fully-rendered JSON string (see ``JsonFormatter.format``),
    so it sees the same text an aggregator would — after ``%s``
    interpolation and after the traceback has been flattened to one line.
    """
    for pattern in _REDACTION_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


#: Bounds the recursive walk in ``_redact_extra_value``. Without this, two
#: real ways to crash a log call exist: a SELF-REFERENTIAL container
#: (``d = {}; d["self"] = d; logger.warning("x", extra=d)``) recurses
#: forever, and a merely deep non-cyclic container (~2000 levels) exhausts
#: CPython's recursion limit — both measured live via
#: ``install_redaction_record_factory()`` raising ``RecursionError`` out of
#: ``logger.warning()`` itself (2026-08-14 review finding). #313's own
#: reproduction shapes are 2-3 levels deep; 25 is generous headroom for any
#: real call site while keeping a pathological one bounded rather than
#: fatal. Past the cap the sub-value is replaced by
#: ``_DEPTH_CAP_PLACEHOLDER`` rather than raising — a stalled log call is
#: worse than an edge case a normal call site will never hit. It used to be
#: returned AS-IS, unredacted below that point (ADR-0046); ADR-0056 changed
#: that, because returning the original container is also what let a cycle
#: whose period exceeds the cap reach ``json.dumps`` and drop the line.
_MAX_EXTRA_REDACTION_DEPTH = 25

#: Container types ``_redact_extra_value`` walks into. ``tuple``/``set``/
#: ``frozenset`` were added after a 2026-08-14 review finding: a secret
#: sitting in a tuple nested inside an otherwise-redacted dict/list (e.g.
#: ``extra={"tokens": (secret,)}``) reached a real Sentry breadcrumb in
#: plaintext, because the walk originally only recognised ``dict``/``list``
#: and returned any other value — including a nested tuple — unchanged.
#: ``Mapping`` (not just ``dict``) because ``sentry_sdk``'s serializer has a
#: dedicated ``Mapping`` branch and walks the CONTENTS of anything that
#: satisfies it. A ``Mapping`` subclass with no custom ``__repr__`` — an HTTP
#: header bag, the common shape — therefore has a clean text form, so the
#: object fallback below saw nothing to redact while Sentry serialized the
#: secret inside it. Measured through ``sentry_sdk``'s own serializer in
#: issue #341's round-2 security review:
#: ``{"headers": {"authorization": "sk-or-v1-...LEAK"}}``. Walking it rebuilds
#: it as a plain ``dict``, which is what both sinks emit for it anyway.
_EXTRA_CONTAINER_TYPES = (Mapping, list, tuple, set, frozenset)


def _sentry_repr(value: object) -> str:
    """Render ``value`` the way ``sentry_sdk``'s serializer prefers to."""
    return str(value.__sentry_repr__())  # type: ignore[attr-defined]


#: Every way a sink is known to turn an object into text. See
#: ``_redact_text_form``.
_TEXT_RENDERERS = (str, repr, _sentry_repr)

#: Types whose text form cannot carry a secret-shaped substring. Every
#: redaction pattern needs a specific ASCII token — ``Bearer``, ``sk-``,
#: ``AKIA``, or a labelled ``api_key=`` — and no ``str()`` of these types
#: produces one: the letters they can produce at all are ``inf``, ``nan``,
#: ``j``, ``True``, ``False`` and ``None``. (An earlier version of this
#: comment claimed digits and punctuation ONLY, which
#: ``str(float("inf"))`` refutes; the conclusion is unaffected.) Listed so
#: the object fallback below never pays a ``str()`` + four regex passes for
#: the scalars real ``extra={...}`` call sites actually use — issue #341 (e)
#: found no call site in ``src/`` passing a container or an object, only
#: strings, numbers, booleans and ``None``.
_SECRET_FREE_SCALAR_TYPES = (bool, int, float, complex, type(None))

#: Substituted for a container that is its own ancestor. Issue #341 §2: the
#: cycle guard used to return the ORIGINAL container, which (a) spliced an
#: untouched plaintext subtree into the redacted result and (b) left
#: ``record.__dict__`` cyclic, so ``JsonFormatter``'s ``json.dumps`` raised
#: ``ValueError: Circular reference detected`` and ``handleError`` swallowed
#: it — the operator's line was dropped entirely.
_CYCLE_PLACEHOLDER = "<cycle>"

#: Substituted for a container sitting past ``_MAX_EXTRA_REDACTION_DEPTH``.
#: Same reasoning as ``_CYCLE_PLACEHOLDER``: returning the original container
#: is what makes an unredacted subtree reachable, and a cycle whose period
#: exceeds the depth cap trips the cap before the cycle guard ever sees a
#: repeated id, so leaving this one as-is would keep the dropped-line failure
#: alive for that shape. See ADR-0056.
_DEPTH_CAP_PLACEHOLDER = "<max-depth>"


#: Per-thread set of ``id()``s currently being rendered by
#: ``_redact_text_form``. An object whose ``__str__`` logs (a lazy proxy, a
#: debug helper) re-enters this module from inside the very ``str()`` call
#: that was inspecting it. Measured 2026-08-18 with no guard at all, on an
#: object whose ``__str__`` logs ITSELF via ``extra=``, under a
#: ``NullHandler`` in a standalone script: 166 nested ``__str__`` calls
#: before CPython's recursion limit stopped it — caught by the
#: ``except Exception`` below and returned cleanly (``RecursionError`` is a
#: ``RuntimeError``), so ``logger.warning()`` never raised, but 166 spurious
#: records were emitted for one call. The exact count is stack-depth
#: dependent and moves with the harness; inside a pytest test the same
#: mutation prints 160. With the guard: 1.
#:
#: Keyed on the OBJECT, not a single per-thread flag. A flag was the first
#: form, and issue #341's round-2 security review measured what it cost: it
#: was held for the whole ``str``/``repr`` window, so a log call made from
#: inside one object's ``__str__`` skipped object-text redaction for a
#: DIFFERENT object, and a secret in that object's text form reached a
#: Sentry breadcrumb in plaintext. An id-keyed set stops only the genuine
#: self-reference, which is the case that cannot be rendered anyway.
_text_form_in_progress = threading.local()


def _rendering_ids() -> set[int]:
    """The set of object ids this thread is currently rendering."""
    ids = getattr(_text_form_in_progress, "ids", None)
    if ids is None:
        ids = set()
        _text_form_in_progress.ids = ids
    return ids


def _redact_text_form(value: object) -> object:
    """Redact an object that is neither a ``str`` nor a walkable container.

    Issue #341 C3: ``extra={"error": exc}`` — the exception OBJECT rather
    than ``str(exc)``, one keystroke from ``synthesis.py``'s real call shape
    — used to be skipped entirely, so Sentry received the live object with
    the credential in its ``args``. ``bytes`` leaked the same way.

    ``str``, ``repr`` AND ``__sentry_repr__`` are all inspected, because the
    sinks disagree about which one they render: ``JsonFormatter`` passes
    ``default=str``; ``sentry_sdk``'s serializer prefers an object's
    ``__sentry_repr__`` and otherwise falls back to a ``repr``. An object
    whose ``__repr__`` (or ``__sentry_repr__``) carries the secret but whose
    ``__str__`` does not would otherwise reach Sentry in plaintext — the
    ``__sentry_repr__`` case was measured doing exactly that in issue #341's
    round-2 security review.

    This covers the serializer's OBJECT rendering paths only. Its
    ``Mapping`` and sequence branches walk contents instead of rendering
    text, and are handled upstream by ``_redact_extra_value`` walking those
    containers rather than reaching this function at all.

    When neither form carries a secret the ORIGINAL object is returned
    untouched — the common case, and what keeps a non-secret extra's type
    (and any downstream consumer's expectations) intact. When one does, the
    value is replaced by the redacted ``str`` form, which is byte-identical
    to what ``JsonFormatter``'s ``default=str`` plus its final-string scrub
    already produced on the stdout path, so that sink's output does not move.

    Every renderer is called defensively: a ``__str__`` that raises must not
    take down the log call it was only decorating.
    """
    rendering = _rendering_ids()
    if id(value) in rendering:
        return value
    rendering.add(id(value))
    try:
        forms: list[str] = []
        for render in _TEXT_RENDERERS:
            try:
                forms.append(render(value))
            except Exception:  # noqa: BLE001 - a bad __str__ must not break logging
                continue
        # An object no renderer can turn into text leaves ``forms`` empty;
        # ``all()`` over an empty list is True, so it takes the "nothing to
        # redact" branch below and the object is returned untouched. No
        # separate guard — an explicit ``if not forms`` was proven equivalent
        # and therefore untestable (it survived being deleted with every test
        # still green). Note ``_sentry_repr`` raises ``AttributeError`` for
        # any object without the dunder, which is nearly all of them, so an
        # absent renderer and a broken one take the same path.
        if all(_redact_secrets(form) == form for form in forms):
            return value
        # ``forms[0]`` is the FIRST form that rendered, not the one that
        # carried the secret: whichever renderer leaked it, the value is
        # replaced by the redacted primary text, so the leaking form is
        # discarded rather than published.
        return _redact_secrets(forms[0])
    finally:
        rendering.discard(id(value))


def _disambiguated_key(key: object, taken: Mapping[object, object]) -> object:
    """Return ``key``, or a free variant of it if ``taken`` already has it.

    Redacting keys introduces a way to LOSE data that redacting values never
    had: two distinct secret-shaped keys both become ``[REDACTED]``, and a
    plain dict comprehension keeps only the last. Measured 2026-08-18 with
    ``python -c`` over ``_redact_secrets``: ``{S1: "a", S2: "b"}`` collapsed
    from two entries to ``{'[REDACTED]': 'b'}`` — one entry, no signal. A
    silent overwrite inside a redactor is unacceptable, so a collision gets a
    numeric discriminator instead.

    Non-``str`` keys (a tuple of strings is a legal, redactable key) are
    disambiguated through their ``repr``, which turns the colliding entry's
    key into a ``str``. That only happens on a collision, which already means
    the original key text is gone; keeping the VALUE is what matters.
    """
    if key not in taken:
        return key
    base = key if isinstance(key, str) else repr(key)
    suffix = 2
    while f"{base}.{suffix}" in taken:
        suffix += 1
    return f"{base}.{suffix}"


#: Key types ``json.dumps`` accepts. Anything else raises
#: ``TypeError: keys must be str, int, float, bool or None, not <type>``.
_JSON_KEY_TYPES = (str, int, float, type(None))


def _serializable_key(key: object) -> object:
    """Return ``key`` in a form the stdout sink can actually write.

    Issue #341 round 2: the ``isinstance(key, str)`` guards added earlier on
    this branch stopped an ``AttributeError``, but ``json.dumps`` still
    refuses a ``tuple`` key, and that ``TypeError`` is raised INSIDE
    ``JsonFormatter.format`` where ``logging.Handler.handleError`` swallows
    it — the operator's whole line vanished, at the top level and nested
    alike. The commit that added those guards said in its own body that
    fixing one crash site alone converts a loud crash into a silent drop;
    this is that drop, closed at the one place every mapping is already
    rebuilt.

    Only keys ``json`` cannot take are touched, so no existing line moves.
    ``sentry_sdk``'s serializer already renders such a key as its ``str``, so
    this makes the two sinks agree rather than changing what Sentry shows.
    """
    return key if isinstance(key, _JSON_KEY_TYPES) else str(key)


def _differs(redacted: object, original: object) -> bool:
    """Did redaction change this value? Never trusting the caller's ``__eq__``.

    Issue #341 round 2, found independently by all three review lenses: the
    record factory used a bare ``redacted_value != value``. Since
    ``_redact_text_form`` returns the SAME object when it finds nothing, that
    is ``value != value`` on a caller-supplied object — and an ``__eq__`` /
    ``__ne__`` that raises (or returns a non-bool, the numpy/pandas
    elementwise shape) took ``logger.warning()`` down with it, where
    ``origin/main`` had emitted the line normally because it never compared
    such a value at all. Measured before this helper existed:
    ``ValueError: ne exploded`` and ``ValueError: truth value of an array is
    ambiguous`` raised straight out of ``logger.warning``.

    The identity test comes first and carries the common case: every clean
    path returns the original object itself. ``bool(...)`` forces a non-bool
    ``__ne__`` result to resolve here, inside the guard, rather than in the
    caller's ``if``. On any failure the answer is "changed", which writes the
    redacted form back — the safe direction for a redactor.
    """
    if redacted is original:
        return False
    try:
        return bool(redacted != original)
    except Exception:  # noqa: BLE001 - a bad __eq__ must not break logging
        return True


def _redact_extra_value(value: object, _ancestors: frozenset[int] = frozenset()) -> object:
    """Recursively redact an ``extra={...}`` value (issue #313 residual gap).

    ``make_record_with_extra_redaction`` originally only redacted a
    top-level extra whose value was itself a ``str`` — a real call shape,
    ``logger.warning(..., extra={"error": {"api_key": "sk-..."}})``, skipped
    the whole value because ``isinstance(value, str)`` is ``False`` for a
    dict, so the raw key reached the Sentry breadcrumb untouched. Containers
    (``dict``, ``list``, ``tuple``, ``set``, ``frozenset`` — see
    ``_EXTRA_CONTAINER_TYPES``) are walked recursively, up to
    ``_MAX_EXTRA_REDACTION_DEPTH`` levels, so a secret nested inside a
    dict-in-list-in-dict (or a tuple sitting inside either) is caught too.
    A dict's KEYS are redacted as well as its values (issue #341 §1), with
    ``_disambiguated_key`` making sure two keys that redact to the same text
    do not collapse into one entry. Numbers, booleans and ``None`` are
    returned unchanged (``_SECRET_FREE_SCALAR_TYPES`` — their text form
    cannot match any pattern); every OTHER non-container value goes through
    ``_redact_text_form``, which inspects its ``str`` and ``repr`` (issue
    #341 C3).

    ``_ancestors`` tracks the ``id()`` of every container currently on the
    recursion PATH (not every container ever seen — two sibling branches
    legitimately referencing the same object is normal aliasing, not a
    cycle, and must still be walked twice). A container whose id is already
    on that path is a genuine cycle; it is replaced by
    ``_CYCLE_PLACEHOLDER`` rather than recursed into again, which is what
    makes a self-referential dict safe instead of an infinite recursion. It
    used to be returned UNCHANGED, which spliced the original plaintext
    subtree back into the redacted result and left ``record.__dict__``
    cyclic — see issue #341 §2 and ADR-0056. Each level passes a NEW frozenset
    (``_ancestors | {id(value)}``) to its children rather than mutating a
    shared set, so sibling branches never see each other's ancestry.

    Always returns a NEW value rather than mutating ``value`` in place —
    the incoming container came from the call site's own ``extra={...}``
    literal (or a variable the caller may reuse/log again later), and
    mutating it would leak the redaction into whatever the caller does with
    that object next. Rebuilding new containers is what keeps this a pure
    function of ``value``.
    """
    if isinstance(value, str):
        return _redact_secrets(value)
    if isinstance(value, _SECRET_FREE_SCALAR_TYPES):
        return value
    if not isinstance(value, _EXTRA_CONTAINER_TYPES):
        return _redact_text_form(value)
    if len(_ancestors) >= _MAX_EXTRA_REDACTION_DEPTH:
        return _DEPTH_CAP_PLACEHOLDER
    obj_id = id(value)
    if obj_id in _ancestors:
        # Genuine cycle (this container is its own ancestor on this path,
        # directly or indirectly) — stop descending rather than recurse
        # forever.
        return _CYCLE_PLACEHOLDER
    ancestors = _ancestors | {obj_id}
    if isinstance(value, Mapping):
        redacted: dict[object, object] = {}
        for key, item in value.items():
            # The KEY is redacted too (issue #341 §1). Disambiguation is
            # unconditional, not "only when the key changed": an untouched
            # literal ``"[REDACTED]"`` key can collide with a redacted one.
            placed = _disambiguated_key(
                _serializable_key(_redact_extra_value(key, ancestors)), redacted
            )
            redacted[placed] = _redact_extra_value(item, ancestors)
        return redacted
    if isinstance(value, list):
        return [_redact_extra_value(item, ancestors) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_extra_value(item, ancestors) for item in value)
    # set / frozenset — elements of a set are necessarily hashable already
    # (str, int, tuple-of-hashables, frozenset), and redaction preserves
    # that: a redacted str is still a str, a redacted tuple/frozenset is
    # still built from redacted (still-hashable) elements.
    redacted_items = {_redact_extra_value(item, ancestors) for item in value}
    return redacted_items if isinstance(value, set) else frozenset(redacted_items)


def install_redaction_record_factory() -> None:
    """Scrub secret-shaped substrings from every log record at CREATION time.

    ADR-0040 scrubs the fully-rendered JSON string inside
    ``JsonFormatter.format()`` — which is correct for the stdout sink, but
    that is the only place it runs. ``sentry_sdk``'s ``LoggingIntegration``
    is on by default (``main.py`` passes no ``integrations=``) and captures
    breadcrumbs/events by patching ``logging.Logger.callHandlers``, which
    runs on the ORIGINATING logger. It never reaches ``JsonFormatter`` at
    all — that class is only wired to a ``StreamHandler`` on the ROOT
    logger, and ``callHandlers`` calls Sentry's patched hook directly against
    the record, independent of which handlers exist. Measured 2026-08-14 with
    a real ``sentry_sdk`` client on an in-memory ``before_breadcrumb`` hook:
    a secret logged via ``logger.warning("...: %s", exc)`` at any of the 9
    call sites named in ADR-0040 reached the breadcrumb in full plaintext —
    see ``tests/unit/test_logging_config_sentry_redaction.py``. This is the
    exact bypass ``telemetry_sink.py``'s ``_configure_token_logger`` docstring
    already documents for a different logger (the token stream), which is why
    that one needs ``ignore_logger`` instead: it wants those records kept out
    of Sentry ENTIRELY. This logger's records should still reach Sentry —
    just with secrets scrubbed first — so ``ignore_logger`` is the wrong tool
    here.

    A :func:`logging.setLogRecordFactory` hook is the only stage that runs
    BEFORE ``Logger.handle()`` calls ``callHandlers`` at all: the record is
    built by the factory inside ``Logger.makeRecord()``, prior to any
    filter, handler, or Sentry's patched dispatch. Mutating the record here
    — not in a ``logging.Filter`` — is what makes every consumer (stdout via
    ``JsonFormatter``, Sentry breadcrumbs/events, pytest's ``caplog``, any
    future handler) see the same redacted text. This mirrors
    ``request_id.install_request_id_record_factory``'s use of the same hook
    for the same reason (visible to every handler, not just one).

    Scope: this redacts ``record.getMessage()`` — the ``msg %% args``
    interpolated text, which is exactly how the 9 named call sites and any
    future ``logger.warning("...: %%s", exc)`` call leak a secret — AND every
    string-valued ``extra={...}`` field on the record (PR #315 review
    follow-up). ``synthesis.py:1462`` logs
    ``logger.error("synthesis_section_failed", extra={"error": str(exc), ...})``
    — a real call site, not a hypothetical one — and a record factory that
    only touched ``getMessage()`` would leave that ``error`` value (which can
    carry the same secret-shaped text a raw exception does) sitting in
    ``record.__dict__["error"]`` in plaintext: ``JsonFormatter`` folds it into
    the stdout JSON where the final-string scrub would still catch it, but
    Sentry's breadcrumb/event capture reads ``record.__dict__`` directly and
    never goes through ``JsonFormatter`` at all — the same bypass this
    function exists to close for the message. Each extra value is redacted
    with ``_redact_extra_value``, matching ``JsonFormatter``'s own
    reserved-attribute set (``_RESERVED_RECORD_ATTRS``) so the standard
    ``LogRecord`` fields (``name``, ``pathname``, ``thread``, ...) are never
    mistaken for call-site extras. A container-valued extra (``dict``,
    ``list``, ``tuple``, ``set``, ``frozenset`` — see
    ``_EXTRA_CONTAINER_TYPES``) is walked RECURSIVELY, bounded by
    ``_MAX_EXTRA_REDACTION_DEPTH`` and a cycle guard (issue #313 residual
    gap, found live via a real reproduction: ``logger.warning(...,
    extra={"error": {"api_key": "sk-..."}})`` reached a real Sentry
    breadcrumb capture in plaintext, because the original check was
    ``isinstance(value, str)`` and skipped the dict entirely) — every string
    found at any depth inside a nested container is redacted, and a fresh
    container is built rather than the original mutated in place, so a
    caller that logs the same object again later still sees its own
    unmodified data. Numbers, booleans and ``None`` are left alone —
    redaction operates on text and none of their text forms can match a
    pattern. Every other non-container value (an exception object, a
    ``bytes``, any object with a custom ``__str__``/``__repr__``) is checked
    through ``_redact_text_form`` and replaced only if its text form
    actually carries a secret (issue #341 C3). Extra KEYS are redacted as
    well as values, here and at every nested level (issue #341 §1 and C2).
    See ``_redact_extra_value``'s own docstring for the depth cap and
    cycle-guard details.

    This still does NOT touch ``record.exc_info`` (a full traceback passed
    via ``exc_info=True``) — none of the 9 call sites use that form today, and
    scrubbing a traceback string would require rendering it here (duplicating
    ``Formatter.formatException``) for a case with no current call site. The
    stdout path still catches that case via ``JsonFormatter``'s existing
    final-string scrub; the Sentry path does not, and that gap is unfixed —
    tracked in ADR-0040's follow-up, not silently repaired here.

    Idempotent: re-installing is a no-op — but see the "Idempotency" note
    below for why this is a MODULE-level flag rather than the
    marker-attribute-on-``current`` pattern ``install_request_id_record_factory``
    uses, which this function used originally too and which has a real gap.

    REENTRANCY AND UNBOUNDED CHAIN GROWTH (PR #315 round-2 review
    follow-up, both closed by the same fix): two separate but related
    defects, both measured 2026-08-14 against this exact function.

    1. **Chain growth.** The original idempotency check read
       ``getattr(logging.getLogRecordFactory(), "_i313_redaction_factory", False)``
       — true only when THIS function's own factory is the OUTERMOST one
       currently installed. ``setup_json_logging`` calls this function and
       THEN ``install_request_id_record_factory()``, which wraps its own
       factory on top — so after one call, the outermost factory carries
       the request-id marker, not this one. A second call to
       ``setup_json_logging`` (documented as safe to do, and done by both
       the app and the audit script) therefore finds no marker, wraps a
       SECOND redaction factory on top of the existing chain, and the
       following ``install_request_id_record_factory()`` call does the same
       for a second request-id factory. Measured: 3 layers after the first
       ``setup_json_logging()``, 5 after the second, 7 after the third —
       growing by 2 on every re-call, forever, with no bound. Every later
       log call in the process pays for the whole chain: N redundant
       ``getMessage()`` + regex passes per record instead of 1.
    2. **Reentrancy interacting with that growth.** With two redaction
       layers chained (one wrapping the other, with the request-id factory
       in between), a message argument whose ``__str__`` logs — the same
       shape as the reentrancy case above — recurses through BOTH layers,
       each with its own independent ``in_progress`` state, because the
       original guard checked ``in_progress`` only AFTER already calling
       ``current(*args, **kwargs)``: the outer layer's own reentrant
       invocation could occur DURING that inner call, before the outer
       layer had set its own flag. Measured: a single level of
       ``__str__``-that-logs recursed to depth 2 instead of the intended 1
       once a second layer was chained on. A single call to
       ``install_redaction_record_factory()`` (this module's own test
       fixtures, or two ``setup_json_logging()`` calls in a real process)
       does not reproduce this alone; it needs the chain-growth defect
       above to produce a second layer first — which is why the same fix
       (never installing a second layer, and checking the guard before
       ``current()`` runs) closes both.

    The fix: track installation with a plain module-level boolean, checked
    and set BEFORE anything about ``current`` is inspected, so a second
    call — from anywhere, at any point in the ``setup_json_logging``
    sequence — is a true no-op rather than depending on which factory
    happens to be outermost right now. And the per-thread reentrancy guard
    is checked and set BEFORE ``current(*args, **kwargs)`` runs, not after,
    so a reentrant call arriving from inside that inner call is caught by
    THIS layer's own flag rather than slipping through the gap.
    """
    global _redaction_factory_installed
    if _redaction_factory_installed:
        return
    _redaction_factory_installed = True

    current = logging.getLogRecordFactory()
    in_progress = threading.local()

    def factory(*args: object, **kwargs: object) -> logging.LogRecord:
        if getattr(in_progress, "active", False):
            # Reentrant call on this thread — a message argument's string
            # conversion logged something while THIS record's message was
            # being redacted. Skip redaction here rather than recursing;
            # see the reentrancy note in this function's docstring. The
            # guard is checked and set BEFORE calling ``current`` so a
            # reentrant call triggered from inside ``current`` itself
            # (e.g. a chained factory further down) is caught too.
            return current(*args, **kwargs)
        in_progress.active = True
        try:
            record = current(*args, **kwargs)
            try:
                rendered = record.getMessage()
            except Exception:  # noqa: BLE001 - never let a bad %-format crash logging
                return record
            redacted = _redact_secrets(rendered)
            if redacted != rendered:
                # Replace msg/args with the already-interpolated,
                # already-redacted text so every later call to getMessage()
                # (JsonFormatter, Sentry's BreadcrumbHandler, caplog) sees
                # the redacted string and does not re-apply %-formatting
                # against the original args.
                record.msg = redacted
                record.args = None
            return record
        finally:
            in_progress.active = False

    logging.setLogRecordFactory(factory)

    # Also redact string-valued extra={...} fields (PR #315 review
    # follow-up) — see this function's docstring, "Scope" paragraph. These
    # CANNOT be handled by the record factory above: ``Logger.makeRecord``
    # calls the record factory first and only attaches ``extra`` to
    # ``record.__dict__`` AFTER the factory returns (stdlib
    # ``logging.Logger.makeRecord``), so a record-factory hook never sees
    # them. ``Logger.makeRecord`` itself runs before ``Logger.handle()``
    # calls ``callHandlers`` — the same stage Sentry's patched dispatch
    # reads from — so wrapping ``makeRecord`` closes the gap the record
    # factory cannot reach. Guarded by the same idempotency flag as the
    # record factory above so this also installs at most once.
    original_make_record = logging.Logger.makeRecord

    def make_record_with_extra_redaction(
        self: logging.Logger,
        name: str,
        level: int,
        fn: str,
        lno: int,
        msg: object,
        args: tuple[object, ...] | Mapping[str, object],
        exc_info: tuple[type[BaseException], BaseException, TracebackType | None]
        | tuple[None, None, None]
        | None,
        func: str | None = None,
        extra: Mapping[str, object] | None = None,
        sinfo: str | None = None,
    ) -> logging.LogRecord:
        record = original_make_record(
            self, name, level, fn, lno, msg, args, exc_info, func, extra, sinfo
        )
        # ``record.__dict__`` is typed ``dict[str, Any]``, but ``makeRecord``
        # copies ``extra`` in verbatim and a caller can put a non-``str`` key
        # there — see the ``isinstance(key, str)`` note below. Bound to a
        # loosely-typed alias so the key rewrite below type-checks.
        attrs: dict[Any, Any] = record.__dict__
        for key, value in list(attrs.items()):
            if key in _RESERVED_RECORD_ATTRS:
                continue
            # ``isinstance(key, str)`` guard: ``extra={1: "v"}`` is legal for
            # the stdlib (``makeRecord`` copies the mapping into
            # ``record.__dict__`` verbatim) and a bare ``key.startswith``
            # raised ``AttributeError: 'int' object has no attribute
            # 'startswith'`` straight out of ``logger.warning`` — this
            # redaction hook, not the stdlib, was crashing the log call.
            if isinstance(key, str) and key.startswith("_"):
                continue
            # The KEY is redacted too (issue #341 C2) — the same key-position
            # gap as the nested dict, one level up. Written through
            # ``record.__dict__`` rather than ``setattr``/``delattr`` because
            # a key here is not guaranteed to be a ``str``.
            redacted_key = _serializable_key(_redact_extra_value(key))
            redacted_value = _redact_extra_value(value)
            if _differs(redacted_key, key):
                # Same discriminator as the nested dict branch, for the same
                # reason: two secret-shaped keys both redact to
                # ``[REDACTED]`` and the second write would drop the first
                # extra from every sink at once.
                del attrs[key]
                attrs[_disambiguated_key(redacted_key, attrs)] = redacted_value
            else:
                # Written unconditionally rather than behind a
                # ``redacted_value != value`` test: the comparison bought
                # nothing (assigning an unchanged value is a no-op) and cost
                # a crash on any object with an awkward ``__eq__``.
                attrs[key] = redacted_value
        return record

    logging.Logger.makeRecord = make_record_with_extra_redaction  # type: ignore[method-assign]


class JsonFormatter(logging.Formatter):
    """Emit each :class:`logging.LogRecord` as a single-line JSON object.

    Stdlib-only. Fields: ``timestamp`` (ISO8601 UTC), ``level``,
    ``logger`` (the channel name, e.g. ``product_app.main``),
    ``message`` (the rendered, args-substituted text), ``module``,
    ``function``, and ``line``. ``exc_info`` is captured as a
    pre-formatted string under ``exception`` so the JSON stays a
    single line.
    """

    _RESERVED = _RESERVED_RECORD_ATTRS

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=UTC).isoformat()
        payload: dict[str, object] = {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Fold any custom ``extra={...}`` fields into the payload so
        # call sites can attach context (run id, account id, etc.)
        # without touching this formatter.
        for key, value in record.__dict__.items():
            # Same non-``str`` key guard as the redaction hook above: an
            # ``extra={1: "v"}`` key reaching a bare ``key.startswith`` raised
            # ``AttributeError`` inside ``format()``, which
            # ``logging.Handler.handleError`` swallows — the line vanished
            # instead of crashing loudly. Fixing only one of the two call
            # sites would have converted a loud crash into a silent drop.
            if key in self._RESERVED or key in payload:
                continue
            if isinstance(key, str) and key.startswith("_"):
                continue
            payload[key] = value
        return _redact_secrets(json.dumps(payload, default=str))


def setup_json_logging(log_level: str = "INFO") -> None:
    """Replace the root logger's handlers with a single JSON stream handler.

    Idempotent: re-running drops any handlers we previously added so
    calling this from both the app and the audit script never
    doubles the output. Existing handlers from libraries (uvicorn,
    httpx) are left alone unless they are already wired to the root
    logger — uvicorn installs its own loggers, which is the right
    place for them.
    """
    # Issue #313 (Sentry-bypass follow-up): must run before any log call, and
    # is independent of the JsonFormatter/StreamHandler wiring below — this
    # is what closes the gap for Sentry breadcrumbs/events, which never go
    # through JsonFormatter at all. See install_redaction_record_factory's
    # docstring for why this needs a record factory and not a Filter.
    install_redaction_record_factory()

    root = logging.getLogger()
    formatter = JsonFormatter()
    # Remove only the handlers we previously added so we don't trample
    # handlers a third-party library might have installed.
    #
    # The type check is EXACT (``type(...) is``), not ``isinstance``, and that
    # matters: ``telemetry_sink`` puts ``RotatingFileHandler``s on the root
    # logger wearing this very formatter — deliberately, so the on-disk shape
    # equals the stdout shape — and a ``RotatingFileHandler`` IS a
    # ``StreamHandler``. An ``isinstance`` test here would silently tear the
    # durable #105 sink down on any later call to this function, and the only
    # symptom would be an empty file in production.
    for handler in list(root.handlers):
        if type(handler) is logging.StreamHandler and isinstance(handler.formatter, JsonFormatter):
            root.removeHandler(handler)
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root.addHandler(handler)
    # OD-3: stamp the per-request id (bound by RequestIdMiddleware) onto
    # every record created while a request is in flight — a record-factory
    # hook so ALL handlers see it, not just this one. A no-op outside
    # request context, so scripts that reuse this setup (e.g. the feedback
    # audit) keep the exact pre-OD-3 record shape. Imported here (not at
    # module top) to keep the import graph acyclic; both modules are
    # stdlib-only.
    from product_app.request_id import install_request_id_record_factory

    install_request_id_record_factory()
    try:
        root.setLevel(getattr(logging, log_level.upper()))
    except AttributeError:
        root.setLevel(logging.INFO)
