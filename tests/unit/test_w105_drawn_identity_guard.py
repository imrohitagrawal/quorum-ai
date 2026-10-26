"""W105 guard (plan addendum, revision 3, design points 2 to 5; G1-G7b): a
tab drawn for a known identity never keeps a renewed token for another known
identity.

The test designer's tests, written before the build. Run under Node with the
functions lifted out of the served ``app.js`` by the two existing harnesses
(``tests/unit/test_w105_tabs_share_token.py`` for the renewal, with its fake
Web Locks, IndexedDB and channel, and ``tests/unit/test_late_run_question_rules.py``
for sessionStorage). Every run has the harness's own deadline and exits, so a
hang reports instead of eating the suite's timeout.

The interface:

* ``readDrawnIdentity(doc)`` -> the JSON string in
  ``<script type="application/json" id="drawn-identity">``; ``""`` when the
  island is missing or its JSON is not a string.
* ``keepRenewedToken(session, tab, drawnIdentity)`` -> boolean, the ONE
  function both renewal paths call instead of setting ``tab.csrfToken``. False,
  with ``tab.csrfToken = ""``, when ``tab.drawnMismatch`` is already true, or
  when ``sharedTokenIdentity(session)`` and ``drawnIdentity`` are both
  non-empty and differ (it then sets ``tab.drawnMismatch`` and
  ``tab.pageIdentityChanged``). Otherwise it keeps the token and gives true.
* The locked path still POSTS a refused renewal's token under the ANSWER's
  identity, ``gen`` and ``seq``; a lockless or counterless renewal posts
  nothing.
* ``acceptSharedToken`` refuses when ``drawnMismatch`` is true;
  ``restoreLateRunQuestion`` reads and removes the entry, then restores
  nothing; ``retrySession`` reloads the page with no "Session started" toast.

ONE CHOICE THE INTERFACE LEFT OPEN, made here and stated for the builder:
``renewSessionToken`` takes the drawn identity as a ``drawnIdentity`` option,
and ``initSession`` passes ``readDrawnIdentity(document)``. The tests that
drive a renewal pass it that way; the ``initSession`` tests give the harness
a ``document`` holding the island.
"""

from __future__ import annotations

import json
import shutil
from typing import Any

import pytest
from tests.unit import test_late_run_question_rules as late
from tests.unit.test_w105_tabs_share_token import _accept
from tests.unit.test_w105_tabs_share_token import _node as _w105_node


@pytest.fixture(autouse=True)
def _needs_node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")


GUARD = [
    "sharedTokenIdentity",
    "keepRenewedToken",
    "acceptSharedToken",
    "takeTokenNumber",
    "renewSessionToken",
]
WIRED = ["initSession", "readDrawnIdentity", *GUARD]

#: Harness helpers: a fake document with the island, and a renewal that
#: passes the drawn identity the way the builder is asked to.
_EXTRA = r"""
function __doc(raw) {
  const node = raw === null ? null : { id: "drawn-identity", type: "application/json",
    textContent: raw, innerHTML: raw,
    getAttribute(n) { return n === "type" ? "application/json" : n === "id" ? "drawn-identity"
      : null; } };
  return {
    getElementById: (id) => (id === "drawn-identity" ? node : null),
    querySelector: (sel) => (String(sel).includes("drawn-identity") ? node : null),
  };
}
function __renewDrawn(tab, server, drawn, opts) {
  opts = opts || {};
  document = __doc(JSON.stringify(drawn));
  return renewSessionToken({
    locks: "locks" in opts ? opts.locks : tab.locks,
    indexedDB: "indexedDB" in opts ? opts.indexedDB : tab.idb,
    channel: tab.channel,
    fetchSession: __fetchFor(tab, server, opts),
    state: tab.state,
    lockTimeoutMs: opts.lockTimeoutMs === undefined ? 2000 : opts.lockTimeoutMs,
    counterTimeoutMs: 2000,
    drawnIdentity: drawn,
  });
}
function __view(tab, server) {
  return { token: tab.state.csrfToken, kept: tab.state.csrfToken !== "" &&
      tab.state.csrfToken === server.latest,
    mismatch: tab.state.drawnMismatch === true, changed: tab.state.pageIdentityChanged === true,
    posts: tab.outbox.map((m) => ({ identity: m.identity, gen: m.gen, seq: m.seq,
      isLatest: m.token === server.latest, keys: Object.keys(m).sort() })),
    fetches: tab.fetches };
}
"""


def _run(functions: list[str], body: str, **kwargs: Any) -> Any:
    return _w105_node(functions, body, extra=_EXTRA, **kwargs)


# =============================================================================
# 1. readDrawnIdentity
# =============================================================================


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        pytest.param('"acct-X"', "acct-X", id="an-account"),
        pytest.param('"anonymous"', "anonymous", id="anonymous"),
        pytest.param('""', "", id="unknown"),
        pytest.param('"\\u003c/script>"', "</script>", id="escaped-less-than-decodes"),
    ],
)
def test_the_drawn_identity_is_the_islands_json_string(raw: str, want: str) -> None:
    """RED-IF: the island is not read, is read as raw text instead of JSON
    (the escaped ``\\u003c`` would not decode), or a string value is changed."""
    got = _run(["readDrawnIdentity"], f"return readDrawnIdentity(__doc({json.dumps(raw)}));")
    assert got == want


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(None, id="no-island"),
        pytest.param("", id="empty-text"),
        pytest.param("not json", id="not-json"),
        pytest.param("123", id="a-number"),
        pytest.param("null", id="null"),
        pytest.param('{"account_id":"acct-X"}', id="an-object"),
        pytest.param('["acct-X"]', id="an-array"),
        pytest.param("true", id="a-boolean"),
    ],
)
def test_a_missing_or_non_string_island_is_unknown(raw: str | None) -> None:
    """RED-IF: a missing island or a non-string value is given as anything
    but ``""``, or throws (the boot would fail). Partner: the string cases
    above are read."""
    got = _run(["readDrawnIdentity"], f"return readDrawnIdentity(__doc({json.dumps(raw)}));")
    assert got == ""


# =============================================================================
# 2. keepRenewedToken, as a pure function
# =============================================================================

#: (case id, drawn identity, answered identity, kept)
CASES = [
    ("G1-same-account", "acct-X", "acct-X", True),
    ("G2-anonymous-to-anonymous", "anonymous", "anonymous", True),
    ("G3-drawn-X-answered-Y", "acct-X", "acct-Y", False),
    ("G3-drawn-X-answered-anonymous", "acct-X", "anonymous", False),
    ("G4-drawn-anonymous-answered-Y", "anonymous", "acct-Y", False),
    ("G5-drawn-X-answered-unknown", "acct-X", "", True),
    ("G5-drawn-unknown-answered-Y", "", "acct-Y", True),
    ("G5-both-unknown", "", "", True),
]


def _session_js(identity: str, token: str = "NEW_".ljust(32, "n")) -> str:
    if identity == "anonymous":
        return json.dumps({"csrf_token": token, "anonymous": True})
    if identity:
        return json.dumps({"csrf_token": token, "account_id": identity})
    return json.dumps({"csrf_token": token})


@pytest.mark.parametrize(("case", "drawn", "answered", "kept"), CASES, ids=[c[0] for c in CASES])
def test_keep_renewed_token_keeps_only_a_matching_or_unknown_identity(
    case: str, drawn: str, answered: str, kept: bool
) -> None:
    """RED-IF: a refusing branch is removed (G3/G4 keep the token), the guard
    refuses a match or an unknown side (G1/G2/G5), it compares anything but
    ``sharedTokenIdentity(session)``, or a refusal does not set BOTH flags.
    G9: a kept token never sets ``pageIdentityChanged``."""
    token = "NEW_".ljust(32, "n")
    got = _run(
        GUARD,
        'const tab = { csrfToken: "OLD_".padEnd(32, "o"), pageIdentityChanged: false };\n'
        f"const out = keepRenewedToken({_session_js(answered, token)}, tab, {json.dumps(drawn)});\n"
        "return { out, token: tab.csrfToken, mismatch: tab.drawnMismatch === true,"
        " changed: tab.pageIdentityChanged === true };",
    )
    if kept:
        assert got == {"out": True, "token": token, "mismatch": False, "changed": False}
    else:
        assert got == {"out": False, "token": "", "mismatch": True, "changed": True}


@pytest.mark.parametrize(
    "answered",
    ["acct-X", "acct-Y", "anonymous", ""],
    ids=["drawn", "other", "anonymous", "unknown"],
)
def test_keep_renewed_token_refuses_every_answer_after_a_mismatch(answered: str) -> None:
    """Codex finding 3 (``RETRY_AFTER_FIRST_MISMATCH`` kept the token). RED-IF:
    the ``drawnMismatch`` check is removed, or reads only the current answer
    (the answer matching the drawn X, or an unknown one, would then be kept).
    The flag stays set."""
    got = _run(
        GUARD,
        'const tab = { csrfToken: "OLD_".padEnd(32, "o"), drawnMismatch: true,'
        " pageIdentityChanged: true };\n"
        f'const out = keepRenewedToken({_session_js(answered)}, tab, "acct-X");\n'
        "return { out, token: tab.csrfToken, mismatch: tab.drawnMismatch === true };",
    )
    assert got == {"out": False, "token": "", "mismatch": True}


# =============================================================================
# 3. Both renewal paths, with their posts counted
# =============================================================================


def _renewal(drawn: str, answered: str, locks: str) -> Any:
    return _run(
        GUARD,
        "const world = __world(); const server = __server();\n"
        f'const tab = __tab("A", "acct-X", world, {locks});\n'
        "tab.state.pageIdentity = null;\n"
        f"await __renewDrawn(tab, server, {json.dumps(drawn)}, "
        f"{{ answerIdentity: {json.dumps(answered)} }});\n"
        "return __view(tab, server);",
    )


@pytest.mark.parametrize(("case", "drawn", "answered", "kept"), CASES, ids=[c[0] for c in CASES])
def test_the_locked_path_checks_the_drawn_identity_and_still_posts_the_answer(
    case: str, drawn: str, answered: str, kept: bool
) -> None:
    """Design points 2 and 4. RED-IF: the locked path sets the token without
    ``keepRenewedToken`` (G3/G4 keep it: S1), refuses a match, or a refused
    renewal stops posting (the answer's other tabs would hold a retired
    token, Codex finding 5) or posts under the DRAWN identity. One post when
    the answer's identity is known, none when it is unknown, as before."""
    got = _renewal(drawn, answered, "__makeLocks()")
    assert got["fetches"] == 1
    assert got["kept"] is kept
    assert got["mismatch"] is (not kept)
    assert got["changed"] is (not kept)
    if not kept:
        assert got["token"] == ""
    if answered:
        assert got["posts"] == [
            {
                "identity": answered,
                "gen": "gen-1",
                "seq": 1,
                "isLatest": True,
                "keys": ["gen", "identity", "kind", "seq", "token"],
            }
        ]
    else:
        assert got["posts"] == []


@pytest.mark.parametrize(("case", "drawn", "answered", "kept"), CASES, ids=[c[0] for c in CASES])
def test_the_lockless_path_checks_the_drawn_identity_and_posts_nothing(
    case: str, drawn: str, answered: str, kept: bool
) -> None:
    """Codex finding 2: ``renewAlone`` (no lock API). RED-IF: ``renewAlone``
    sets the token without ``keepRenewedToken`` (the older slow-``app.js``
    case, G4b, survives), refuses a match, or posts anything."""
    got = _renewal(drawn, answered, "undefined")
    assert got["fetches"] == 1
    assert got["kept"] is kept
    assert got["mismatch"] is (not kept)
    assert got["changed"] is (not kept)
    assert got["posts"] == []


@pytest.mark.parametrize(
    "how",
    [
        pytest.param("none", id="no-lock-api"),
        pytest.param("throws", id="request-throws"),
        pytest.param("rejects", id="request-rejects"),
        pytest.param("timeout", id="wait-times-out"),
    ],
)
def test_every_lockless_fallback_refuses_g4(how: str) -> None:
    """Codex finding 2 names four ways into ``renewAlone``. RED-IF: any one
    of them keeps Y's token in a tab drawn anonymous, or posts. Partner: the
    same fallback with the anonymous answer keeps its token."""
    locks = {
        "none": "undefined",
        "throws": '__makeLocks({ throwSync: "SecurityError" })',
        "rejects": '__makeLocks({ reject: "SecurityError" })',
        "timeout": "__makeLocks()",
    }[how]
    body = (
        "const out = {};\n"
        'for (const answered of ["acct-Y", "anonymous"]) {\n'
        "  const world = __world(); const server = __server();\n"
        f'  const tab = __tab("A", "anonymous", world, {locks});\n'
        + (
            '  const release = tab.locks.hold("quorum-session-token");\n'
            if how == "timeout"
            else ""
        )
        + '  await __renewDrawn(tab, server, "anonymous", { answerIdentity: answered,'
        " lockTimeoutMs: 40 });\n"
        + ("  release();\n" if how == "timeout" else "")
        + "  out[answered] = __view(tab, server);\n}\nreturn out;"
    )
    got = _run(GUARD, body)
    refused, partner = got["acct-Y"], got["anonymous"]
    assert refused["fetches"] == 1 and refused["kept"] is False and refused["token"] == ""
    assert refused["mismatch"] is True and refused["posts"] == []
    assert partner["fetches"] == 1 and partner["kept"] is True and partner["mismatch"] is False


# =============================================================================
# 4. G7 and G7b: the refusal sticks, and the answer's own tabs still work
# =============================================================================


@pytest.mark.parametrize("path", ["locked", "lockless"])
@pytest.mark.parametrize(
    "retry", ["acct-Y", "acct-X", "acct-Z", ""], ids=["same", "drawn", "different", "unknown"]
)
def test_after_a_mismatch_every_retry_stays_refused(path: str, retry: str) -> None:
    """G7b (Codex finding 3). Drawn X, answered Y, then ``retrySession``'s
    renewal answers ``retry``. RED-IF: any retry keeps a token (the check
    reads only the current answer, or the flag is cleared). Posts: the locked
    path posts each known answer (2, or 1 when the retry is unknown); the
    lockless path posts none."""
    locks = "__makeLocks()" if path == "locked" else "undefined"
    got = _run(
        GUARD,
        f'const tab = __tab("A", "acct-X", __world(), {locks}); const server = __server();\n'
        'await __renewDrawn(tab, server, "acct-X", { answerIdentity: "acct-Y" });\n'
        f'await __renewDrawn(tab, server, "acct-X", {{ answerIdentity: {json.dumps(retry)} }});\n'
        "return __view(tab, server);",
    )
    assert got["fetches"] == 2
    assert got["token"] == ""
    assert got["mismatch"] is True and got["changed"] is True
    if path == "lockless":
        assert got["posts"] == []
    else:
        want = ["acct-Y", retry] if retry else ["acct-Y"]
        assert [p["identity"] for p in got["posts"]] == want
        assert [p["seq"] for p in got["posts"]] == list(range(1, len(want) + 1))


@pytest.mark.parametrize("path", ["locked", "lockless"])
def test_the_same_account_at_every_renewal_is_kept(path: str) -> None:
    """G1, the positive partner of the test above. RED-IF: a second renewal
    of the same account is refused."""
    locks = "__makeLocks()" if path == "locked" else "undefined"
    got = _run(
        GUARD,
        f'const tab = __tab("A", "acct-X", __world(), {locks}); const server = __server();\n'
        'await __renewDrawn(tab, server, "acct-X", { answerIdentity: "acct-X" });\n'
        'await __renewDrawn(tab, server, "acct-X", { answerIdentity: "acct-X" });\n'
        "return __view(tab, server);",
    )
    assert got["kept"] is True and got["mismatch"] is False and got["changed"] is False
    assert len(got["posts"]) == (2 if path == "locked" else 0)


@pytest.mark.parametrize("path", ["locked", "lockless"])
def test_a_failed_first_fetch_then_a_mismatching_answer_is_refused(path: str) -> None:
    """G7b. RED-IF: a first renewal that throws leaves the guard unarmed (the
    next, first successful, answer for Y is kept in a tab drawn X). Partner:
    the failure itself is thrown out, as today."""
    locks = "__makeLocks()" if path == "locked" else "undefined"
    got = _run(
        GUARD,
        f'const tab = __tab("A", "acct-X", __world(), {locks}); const server = __server();\n'
        "let threw = false;\n"
        'try { await __renewDrawn(tab, server, "acct-X", { fail: new Error("offline") }); }'
        " catch (_) { threw = true; }\n"
        'await __renewDrawn(tab, server, "acct-X", { answerIdentity: "acct-Y" });\n'
        "return Object.assign(__view(tab, server), { threw });",
    )
    assert got["threw"] is True
    assert got["fetches"] == 2
    assert got["token"] == "" and got["mismatch"] is True
    assert [p["identity"] for p in got["posts"]] == (["acct-Y"] if path == "locked" else [])


def test_a_refused_tab_passes_the_token_to_the_answers_tab_and_to_no_other() -> None:
    """G7 (design point 4). X and Y renew first; A, drawn anonymous, is
    answered Y and refused. RED-IF: A posts nothing (Y's tab B keeps a
    retired token), posts under the drawn identity (X or anonymous tabs would
    take it), or A takes Y's later token from C (``drawnMismatch`` alone must
    refuse it: A's ``pageIdentity`` is set to Y here, as ``initSession``
    would). Partner: B takes A's token, which is the server's newest."""
    got = _run(
        GUARD,
        "const world = __world(); const locks = __makeLocks(); const server = __server();\n"
        'const x = __tab("X", "acct-X", world, locks); const b = __tab("B", "acct-Y", world, '
        "locks);\n"
        'const a = __tab("A", "anonymous", world, locks); const c = __tab("C", "acct-Y", world, '
        "locks);\n"
        'await __renewDrawn(x, server, "acct-X"); await __renewDrawn(b, server, "acct-Y");\n'
        'await __renewDrawn(a, server, "anonymous", { answerIdentity: "acct-Y" });\n'
        "const aToken = server.latest;\n"
        "const toX = a.outbox.map((m) => __deliver(m, x));\n"
        "const toB = a.outbox.map((m) => __deliver(m, b));\n"
        'a.state.pageIdentity = "acct-Y"; a.state.pageIdentityChanged = false;\n'
        'await __renewDrawn(c, server, "acct-Y");\n'
        "const toA = c.outbox.map((m) => __deliver(m, a));\n"
        "return { toX, toB, toA, bHasA: b.state.csrfToken === aToken, aToken: a.state.csrfToken,\n"
        "  aPosts: a.outbox.map((m) => m.identity) };",
    )
    assert got["aPosts"] == ["acct-Y"]
    assert got["toX"] == [False]
    assert got["toB"] == [True]
    assert got["bHasA"] is True
    assert got["toA"] == [False]
    assert got["aToken"] == ""


# =============================================================================
# 5. acceptSharedToken
# =============================================================================


def test_a_tab_with_a_drawn_mismatch_takes_no_token() -> None:
    """Design point 3. ``pageIdentityChanged`` is false here, so only
    ``drawnMismatch`` can refuse. RED-IF: ``acceptSharedToken`` does not read
    ``drawnMismatch``. Partner: the same message and state with the flag false
    are accepted."""
    assert _accept(state_patch="{ drawnMismatch: true }") is False
    assert _accept(state_patch="{ drawnMismatch: false }") is True


# =============================================================================
# 6. The page's wiring: initSession, retrySession
# =============================================================================


def _bootstrap(identity: str, token: str) -> dict[str, Any]:
    body: dict[str, Any] = {"csrf_token": token, "expires_at": "2026-10-26T00:00:00+00:00"}
    if identity == "anonymous":
        body["anonymous"] = True
    elif identity:
        body["account_id"] = identity
    return body


@pytest.mark.parametrize("locks", ["__makeLocks()", "undefined"], ids=["locked", "lockless"])
@pytest.mark.parametrize(
    ("drawn", "refused"),
    [("anonymous", True), ("acct-Y", False)],
    ids=["S1-drawn-anonymous", "partner-drawn-Y"],
)
def test_init_session_reads_the_island_and_passes_it_to_the_guard(
    locks: str, drawn: str, refused: bool
) -> None:
    """RED-IF: ``initSession`` does not read the page's island (or passes it
    nowhere), so the guard never sees the drawn identity and S1 is kept.
    Partner: drawn Y and answered Y is kept, with no flag set."""
    token = "Y1".ljust(32, "q")
    got = _run(
        WIRED,
        f"navigator.locks = {locks}; indexedDB = __makeIDB({{}}, __world());\n"
        f"document = __doc({json.dumps(json.dumps(drawn))});\n"
        "await initSession();\n"
        "return { token: state.csrfToken, mismatch: state.drawnMismatch === true,"
        " changed: state.pageIdentityChanged === true, fetch: __log.fetch,"
        " posts: __log.posts.map((p) => p.identity) };",
        answers=[_bootstrap("acct-Y", token)],
    )
    assert got["fetch"] == 1
    assert got["token"] == ("" if refused else token)
    assert got["mismatch"] is refused
    assert got["changed"] is refused
    assert got["posts"] == (["acct-Y"] if locks != "undefined" else [])


_TOAST = (
    "const toasts = []; toast = (o) => { toasts.push(o && o.message); };\n"
    "clearError = () => {}; refreshDefaults = async () => {};\n"
)


@pytest.mark.parametrize(
    ("setup", "refused"),
    [
        pytest.param(
            "state.drawnMismatch = true; initSession = async () => {};", True, id="before"
        ),
        pytest.param(
            "state.drawnMismatch = false;"
            " initSession = async () => { state.drawnMismatch = true; };",
            True,
            id="during-the-retry",
        ),
        pytest.param(
            "state.drawnMismatch = false; initSession = async () => {};", False, id="partner"
        ),
    ],
)
def test_start_a_session_reloads_instead_of_saying_it_started(setup: str, refused: bool) -> None:
    """Codex re-check advisory (``RETRY_REFUSAL_COPY`` showed "Session
    started" with the token cleared). RED-IF: a refused tab's "Start a
    session" shows the success toast, or does not reload. Partner: an
    unrefused retry shows the toast once and does not reload."""
    got = _run(
        ["retrySession"],
        _TOAST + setup + "\nawait retrySession();\nreturn { toasts, reloads: __log.reloads };",
    )
    if refused:
        assert got == {"toasts": [], "reloads": 1}
    else:
        assert got == {"toasts": ["Session started. You can run a query now."], "reloads": 0}


@pytest.mark.parametrize(
    ("drawn", "refused"), [("anonymous", True), ("acct-Y", False)], ids=["S1", "partner"]
)
def test_the_whole_retry_after_a_refused_boot_reloads(drawn: str, refused: bool) -> None:
    """The real ``initSession`` and renewal inside ``retrySession``. RED-IF: a
    refused page's retry keeps a token or shows "Session started". Partner:
    drawn Y keeps both tokens and shows the toast. Both make two fetches, so
    the reload is not a harness failure caught by ``retrySession``."""
    t1, t2 = "Y1".ljust(32, "q"), "Y2".ljust(32, "q")
    got = _run(
        ["retrySession", *WIRED],
        _TOAST + "navigator.locks = __makeLocks(); indexedDB = __makeIDB({}, __world());\n"
        f"document = __doc({json.dumps(json.dumps(drawn))});\n"
        "await initSession(); await retrySession();\n"
        "return { toasts, reloads: __log.reloads, fetch: __log.fetch, token: state.csrfToken,"
        " mismatch: state.drawnMismatch === true };",
        answers=[_bootstrap("acct-Y", t1), _bootstrap("acct-Y", t2)],
    )
    assert got["fetch"] == 2
    if refused:
        assert got == {"toasts": [], "reloads": 1, "fetch": 2, "token": "", "mismatch": True}
    else:
        assert got["toasts"] == ["Session started. You can run a query now."]
        assert got["reloads"] == 0 and got["token"] == t2 and got["mismatch"] is False


# =============================================================================
# 7. restoreLateRunQuestion
# =============================================================================

_RESTORE = ["restoreLateRunQuestion", "lateRunQuestionToRestore"]


def _restore(entry_js: str, *, mismatch: bool, account: str = "acct-Y") -> Any:
    body = (
        "queryTextarea.value = '';\n"
        f"window.sessionStorage.setItem(LATE_RUN_QUESTION_KEY, JSON.stringify({entry_js}));\n"
        f"state.sessionAccountId = {json.dumps(account)}; state.drawnMismatch = "
        f"{'true' if mismatch else 'false'};\n"
        "let notices = 0; showQuestionNotKeptNotice = async () => { notices += 1; };\n"
        "await restoreLateRunQuestion();\n"
        "return { value: queryTextarea.value,"
        " left: window.sessionStorage.getItem(LATE_RUN_QUESTION_KEY), notices };"
    )
    return late._node(_RESTORE, body)


_ENTRIES = {
    "signed-in": '{ account: "acct-Y", question: "asked as Y" }',
    "anonymous": '{ anonymous: true, saved_at: Date.now() - 1000, question: "asked as Y" }',
}


@pytest.mark.parametrize("kind", list(_ENTRIES))
def test_a_refused_page_removes_the_saved_question_and_restores_nothing(kind: str) -> None:
    """Codex finding 4 (``RESTORE_WITH_CHANGED_IDENTITY`` restored "saved by
    Y"). RED-IF: a page with ``drawnMismatch`` puts Y's question back, or the
    check comes before the entry is removed (it would stay for the next
    load). Partner: the test below restores the same entry."""
    got = _restore(_ENTRIES[kind], mismatch=True)
    assert got == {"value": "", "left": None, "notices": 0}


@pytest.mark.parametrize("kind", list(_ENTRIES))
def test_an_unrefused_page_restores_the_saved_question(kind: str) -> None:
    """The positive partner. RED-IF: the guard blocks a matching page's
    restore (W87-2's rule, G9)."""
    got = _restore(_ENTRIES[kind], mismatch=False)
    assert got == {"value": "asked as Y", "left": None, "notices": 0}


def test_a_refused_page_shows_no_other_account_line() -> None:
    """Reading "restores nothing" as nothing at all: the other-account line
    would print the CURRENT account's email (Y) on a page drawn for someone
    else. RED-IF: the refused page shows it. Partner: an unrefused page shows
    it once for the same entry."""
    entry = '{ account: "acct-X", question: "asked as X" }'
    assert _restore(entry, mismatch=True) == {"value": "", "left": None, "notices": 0}
    assert _restore(entry, mismatch=False) == {"value": "", "left": None, "notices": 1}
