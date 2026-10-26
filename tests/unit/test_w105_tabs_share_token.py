"""W105 (CHG-071, CHG-089): open tabs share a renewed anti-forgery token.

The test designer's tests, written before the build against the agreed
interface (plan revision 5, the Tests section). Every function is lifted out
of the served ``app.js`` by brace count, as
``tests/unit/test_late_run_question_rules.py`` does, and run under Node.

The interface the builder implements in ``src/product_app/static/app.js``:

* ``acceptSharedToken(message, state)`` -> boolean. ``state`` holds
  ``pageIdentity``, ``pageIdentityChanged``, ``sharingOff``, ``renewing``,
  ``tokenGen`` and ``tokenSeq``. True only when ALL hold: a non-null object
  with ``kind === "csrf-token"``; ``token`` a string matching
  ``^[A-Za-z0-9_-]{16,128}$``; ``identity`` a non-empty string equal to
  ``state.pageIdentity``; the page's identity has not changed; sharing is
  not off; the tab is not renewing; ``gen`` a string equal to
  ``state.tokenGen``; ``seq`` a safe integer greater than ``state.tokenSeq``.
* ``sharedTokenIdentity(session)`` -> the ``account_id`` when it is a string,
  else ``"anonymous"`` only when ``session.anonymous === true``, else ``""``.
* ``takeTokenNumber(indexedDB, timeoutMs)`` -> Promise of ``{gen, seq}`` or
  ``null``. Database ``quorum-session-token``, store ``counter``, one record
  under the key ``"counter"`` holding exactly ``{gen, seq}``; one
  ``readwrite`` transaction, resolved on its ``complete`` event; a missing
  record is created as ``{gen: crypto.randomUUID(), seq: 1}``.
* ``renewSessionToken({locks, indexedDB, channel, fetchSession, state,
  lockTimeoutMs, counterTimeoutMs})``: the Web Lock ``quorum-session-token``,
  its wait bounded by ``AbortSignal.timeout(lockTimeoutMs)``; inside it the
  number, then exactly one ``fetchSession()``, then the token, then one post
  ``{kind: "csrf-token", token, identity, gen, seq}``. Both time limits
  default to 10000 ms.
* ``initSession()`` calls ``renewSessionToken``; the channel
  ``quorum-session-token`` is opened once at script start; its message
  handler calls ``acceptSharedToken`` and, when it is true, sets
  ``state.csrfToken`` and ``state.tokenSeq`` and does nothing else.

What the harness provides, stated (FM-13): ``BroadcastChannel``,
``navigator.locks``, ``indexedDB`` and ``crypto.randomUUID`` are FAKES in the
scope the functions run in, never Node's own, so no real channel keeps Node
alive and the result does not depend on Node 22 versus 26.
``crypto.randomUUID`` answers ``gen-1``, ``gen-2``, ... so a created ``gen``
can be compared exactly. ``setTimeout`` and ``AbortSignal.timeout`` are the
real ones, wrapped to record the time each is given. Any other name that is
neither the harness's nor Node's resolves to a no-op function that also has a
``postMessage`` which records, so a module-level channel binding the builder
names is seen, whatever its name. Every run ends with ``process.exit`` and
has its own 8 s deadline, so a hang reports instead of eating the 30 s
timeout. An unhandled promise rejection fails the test.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP_JS = ROOT / "src" / "product_app" / "static" / "app.js"
TEMPLATES = ROOT / "src" / "product_app" / "templates"

INTERFACE = ["acceptSharedToken", "sharedTokenIdentity", "takeTokenNumber", "renewSessionToken"]


@pytest.fixture(autouse=True)
def _needs_node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")


def _function(source: str, name: str) -> str:
    """The text of ``function name(...) {...}``, with a leading ``async``."""
    match = re.search(r"(async\s+)?function " + re.escape(name) + r"\(", source)
    assert match is not None, f"app.js defines function {name} (the W105 interface)"
    start = match.start()
    i = source.index("(", match.end() - 1)
    depth = 0
    while True:
        if source[i] == "(":
            depth += 1
        elif source[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    i = source.index("{", i)
    return source[start : _close(source, i) + 1]


def _close(source: str, i: int) -> int:
    """The index of the ``}`` that closes the ``{`` at ``i``."""
    depth = 0
    while True:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1


def _constants(source: str, functions: list[str]) -> str:
    """One-line ``const NAME = ...;`` declarations the functions name."""
    names = sorted({n for text in functions for n in re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", text)})
    lines = []
    for name in names:
        found = re.search(r"^\s*const " + re.escape(name) + r" = [^\n]*;\s*$", source, re.M)
        if found:
            lines.append(found.group(0).strip())
    return "\n".join(lines)


def _skip_ws_back(source: str, i: int) -> int:
    while i >= 0 and source[i].isspace():
        i -= 1
    return i


def _open_paren(source: str, i: int) -> int:
    """The index of the ``(`` that opens the ``)`` at ``i``."""
    depth = 0
    while True:
        if source[i] == ")":
            depth += 1
        elif source[i] == "(":
            depth -= 1
            if depth == 0:
                return i
        i -= 1


def _function_start(source: str, brace: int) -> int | None:
    """Where the function whose body opens at ``brace`` starts, or None when
    the ``{`` opens a block that is not a function body (if, for, catch...)."""
    j = _skip_ws_back(source, brace - 1)
    if source[j - 1 : j + 1] == "=>":
        k = _skip_ws_back(source, j - 2)
        if source[k] == ")":
            start = _open_paren(source, k)
        else:
            start = k
            while start > 0 and (source[start - 1].isalnum() or source[start - 1] in "_$"):
                start -= 1
        before = source[max(0, start - 6) : start]
        return start - 6 if before == "async " else start
    if source[j] != ")":
        return None
    paren = _open_paren(source, j)
    head = source[max(0, paren - 80) : paren]
    found = re.search(r"(async\s+)?function(\s+[A-Za-z_$][\w$]*)?\s*$", head)
    if found is None:
        return None
    return paren - len(head) + found.start()


def _message_handler(source: str) -> str:
    """The function that calls ``acceptSharedToken`` outside the interface
    functions: the channel's message handler, as an expression."""
    inside = []
    for name in INTERFACE:
        text = _function(source, name)
        begin = source.index(text)
        inside.append((begin, begin + len(text)))
    calls = [
        m.start()
        for m in re.finditer(r"\bacceptSharedToken\(", source)
        if not source[max(0, m.start() - 9) : m.start()].endswith("function ")
        and not any(a <= m.start() < b for a, b in inside)
    ]
    assert calls, "app.js calls acceptSharedToken from the channel's message handler"
    i = calls[0]
    depth = 0
    while i > 0:
        i -= 1
        if source[i] == "}":
            depth += 1
        elif source[i] == "{":
            if depth > 0:
                depth -= 1
                continue
            start = _function_start(source, i)
            if start is not None:
                return source[start : _close(source, i) + 1]
    raise AssertionError("the acceptSharedToken call is inside a function")


#: The harness: fakes for the browser APIs, a counting fetch, and the scope
#: every extracted function runs in. ``__`` names are the harness's own and
#: are never looked up in the scope.
_PRELUDE = r"""
const __answers = __ANSWERS__;
const __log = { fetch: 0, fetchUrls: [], posts: [], channels: [], timers: [], abortTimeouts: [],
  unhandled: [], reloads: 0 };
process.on("unhandledRejection", (e) => { __log.unhandled.push(String(e && e.stack || e)); });
const __realSetTimeout = globalThis.setTimeout;
const __RealAbortSignal = globalThis.AbortSignal;
const __sleep = (ms) => new Promise((r) => __realSetTimeout(r, ms));
const __clone = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)));
const __tok = (n) => ("T" + n + "_").padEnd(32, "x");
let __uuid = 0;
function __unknown() { return undefined; }
__unknown.postMessage = function (m) { __log.posts.push(__clone(m)); };

class __T {
  constructor() { this.__l = {}; }
  addEventListener(t, f) { (this.__l[t] = this.__l[t] || []).push(f); }
  removeEventListener(t, f) {
    const a = this.__l[t] || []; const i = a.indexOf(f); if (i >= 0) a.splice(i, 1);
  }
  __fire(t, extra) {
    const ev = Object.assign({ type: t, target: this, currentTarget: this,
      preventDefault() {}, stopPropagation() {} }, extra || {});
    const run = (f) => { try { f.call(this, ev); } catch (e) {
      __log.unhandled.push("handler: " + e); } };
    if (typeof this["on" + t] === "function") run(this["on" + t]);
    for (const f of (this.__l[t] || []).slice()) run(f);
  }
}

/** A fake Web Locks manager: one holder per name, a FIFO queue, the
 *  ``signal`` honoured while waiting. ``reject``/``throwSync`` fail the
 *  request before any callback. */
function __makeLocks(opts) {
  opts = opts || {};
  const queues = new Map();
  const api = { requests: [], held: new Set() };
  api.request = function (name, options, callback) {
    if (typeof options === "function") { callback = options; options = {}; }
    options = options || {};
    api.requests.push({ name, hasSignal: !!options.signal, mode: options.mode || "exclusive" });
    if (opts.throwSync) throw new Error(opts.throwSync);
    if (opts.reject) return Promise.reject(new Error(opts.reject));
    return new Promise((resolve, reject) => {
      const q = queues.get(name) || []; queues.set(name, q);
      const signal = options.signal;
      const entry = { started: false };
      let onAbort = null;
      entry.run = () => {
        entry.started = true;
        if (signal && onAbort) signal.removeEventListener("abort", onAbort);
        api.held.add(name);
        let p;
        try { p = Promise.resolve(callback({ name, mode: "exclusive" })); } catch (e) {
          p = Promise.reject(e); }
        p.then(resolve, reject).finally(() => {
          api.held.delete(name);
          q.shift();
          if (q.length) __realSetTimeout(() => q[0].run(), 0);
        });
      };
      if (signal) {
        if (signal.aborted) { reject(signal.reason); return; }
        onAbort = () => {
          if (entry.started) return;
          const i = q.indexOf(entry); if (i >= 0) q.splice(i, 1);
          reject(signal.reason);
        };
        signal.addEventListener("abort", onAbort);
      }
      q.push(entry);
      if (q.length === 1) __realSetTimeout(() => entry.run(), 0);
    });
  };
  /** Hold ``name`` from outside until the returned function is called. */
  api.hold = function (name) {
    let release; const p = new Promise((r) => { release = r; });
    api.request(name, {}, () => p).catch(() => {});
    return release;
  };
  return api;
}

/** One browser profile's IndexedDB storage, shared by its tabs. */
function __world() { return { dbs: new Map(), queue: [] }; }

/** A fake IndexedDB factory over ``world``. Failure modes: ``openThrows``,
 *  ``openError``, ``blocked`` (then success after ``lateMs`` if given),
 *  ``never``, ``lateMs``, ``txError`` (the put succeeds, then the transaction
 *  aborts instead of completing), ``completeDelayMs``, and
 *  ``versionchangeAfterOpen``. ``log`` records what the page did. */
function __makeIDB(opts, world) {
  opts = opts || {}; world = world || __world();
  const log = { opens: [], txModes: [], txStores: [], created: [], completed: 0, closeCalls: 0,
    closedOnVersionchange: null, putKeys: [] };
  function runQueue() {
    if (!world.queue.length || world.queue[0].__active) return;
    const tx = world.queue[0]; tx.__active = true;
    __realSetTimeout(() => tx.__step(), 0);
  }
  function makeDb(name, rec) {
    const db = new __T();
    db.name = name; db.version = rec.version;
    db.objectStoreNames = { contains: (n) => rec.stores.has(n), get length() {
      return rec.stores.size; } };
    db.createObjectStore = (n, o) => { log.created.push({ name: n, options: o || null });
      rec.stores.set(n, new Map()); return {}; };
    db.close = () => { log.closeCalls += 1; };
    db.transaction = (names, mode) => {
      const list = Array.isArray(names) ? names : [names];
      log.txModes.push(mode || "readonly"); log.txStores.push(list.slice());
      const tx = new __T(); tx.mode = mode || "readonly"; tx.error = null; tx.db = db;
      const ops = []; let staged = null; let aborted = false;
      const stage = (n) => {
        if (!staged) staged = new Map([...rec.stores].map(([k, v]) => [k, new Map(v)]));
        if (!staged.has(n)) throw new Error("NotFoundError: no store " + n);
        return staged.get(n);
      };
      const op = (fn) => { const r = new __T(); r.transaction = tx; ops.push({ fn, r });
        return r; };
      tx.objectStore = (n) => ({
        name: n,
        get: (k) => op(() => __clone(stage(n).get(k))),
        put: (v, k) => op(() => {
          if (tx.mode !== "readwrite") throw new Error("ReadOnlyError");
          if (k === undefined) throw new Error("DataError: this store has out-of-line keys");
          log.putKeys.push(k); stage(n).set(k, __clone(v)); return k;
        }),
        add: (v, k) => op(() => {
          if (stage(n).has(k)) throw new Error("ConstraintError");
          stage(n).set(k, __clone(v)); return k;
        }),
        delete: (k) => op(() => { stage(n).delete(k); return undefined; }),
      });
      tx.abort = () => { aborted = true; };
      tx.commit = () => {};
      tx.__step = () => {
        if (aborted) return finish(false);
        const next = ops.shift();
        if (!next) return finish(!opts.txError);
        try { next.r.result = next.fn(); next.r.readyState = "done"; next.r.__fire("success"); }
        catch (e) { next.r.error = e; next.r.__fire("error"); aborted = true; }
        __realSetTimeout(() => tx.__step(), 0);
      };
      function finish(ok) {
        const done = () => {
          if (ok) {
            if (staged) for (const [k, v] of staged) rec.stores.set(k, v);
            log.completed += 1; tx.__fire("complete");
          } else {
            tx.error = new Error("AbortError"); tx.__fire("error"); tx.__fire("abort");
          }
          world.queue.shift(); runQueue();
        };
        if (ok && opts.completeDelayMs) __realSetTimeout(done, opts.completeDelayMs); else done();
      }
      world.queue.push(tx); runQueue();
      return tx;
    };
    return db;
  }
  const factory = {
    log, world,
    open(name, version) {
      log.opens.push({ name, version: version === undefined ? null : version });
      if (opts.openThrows) throw new Error("SecurityError: the operation is insecure");
      const req = new __T(); req.result = undefined; req.error = null; req.readyState = "pending";
      const go = () => {
        if (opts.openError) { req.error = new Error("UnknownError"); req.__fire("error"); return; }
        let rec = world.dbs.get(name);
        if (!rec) { rec = { version: 0, stores: new Map() }; world.dbs.set(name, rec); }
        const want = version === undefined ? Math.max(rec.version, 1) : version;
        if (want < rec.version) { req.error = new Error("VersionError"); req.__fire("error");
          return; }
        const db = makeDb(name, rec);
        req.result = db;
        if (want > rec.version) {
          const old = rec.version; rec.version = want; db.version = want;
          req.__fire("upgradeneeded", { oldVersion: old, newVersion: want });
        }
        req.readyState = "done";
        req.__fire("success");
        if (opts.versionchangeAfterOpen) {
          __realSetTimeout(() => {
            const before = log.closeCalls;
            db.__fire("versionchange", { oldVersion: want, newVersion: want + 1 });
            log.closedOnVersionchange = log.closeCalls > before;
          }, 0);
        }
      };
      if (opts.never) return req;
      if (opts.blocked) {
        __realSetTimeout(() => {
          req.__fire("blocked", { oldVersion: 1, newVersion: 2 });
          if (opts.lateMs !== undefined) __realSetTimeout(go, opts.lateMs);
        }, 0);
        return req;
      }
      __realSetTimeout(go, opts.lateMs || 0);
      return req;
    },
  };
  return factory;
}

/** The record the page keeps, read straight from the fake storage. */
function __record(world) {
  const rec = world.dbs.get("quorum-session-token");
  if (!rec || !rec.stores.has("counter")) return null;
  const v = rec.stores.get("counter").get("counter");
  return v === undefined ? null : __clone(v);
}
function __seed(world, value) {
  world.dbs.set("quorum-session-token", { version: 1, stores: new Map([["counter",
    new Map([["counter", value]])]]) });
}

class __FakeChannel {
  constructor(name) { this.name = name; __log.channels.push(name); }
  postMessage(m) { __log.posts.push(__clone(m)); }
  addEventListener() {}
  removeEventListener() {}
  close() {}
}

const __stubs = {
  state: { csrfToken: "", sessionAccountId: "", sessionAnonymous: false, pageIdentity: null,
    pageIdentityChanged: false },
  STATUS_COPY: {},
  ApiError: class ApiError extends Error {
    constructor(o) { super((o && o.message) || ""); Object.assign(this, o || {}); }
  },
  fetch: async function (url) {
    __log.fetch += 1; __log.fetchUrls.push(String(url));
    const body = __answers.shift();
    if (body && body.__networkError) throw new TypeError("Failed to fetch");
    if (body && body.__status) return { ok: false, status: body.__status, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => body };
  },
  el: function () { return { textContent: "", dataset: {}, hidden: false, focus() {} }; },
  crypto: { randomUUID: () => { __uuid += 1; return "gen-" + __uuid; } },
  navigator: { locks: undefined },
  indexedDB: undefined,
  BroadcastChannel: __FakeChannel,
  setTimeout: function (f, ms, ...rest) { __log.timers.push(ms); return __realSetTimeout(f, ms,
    ...rest); },
  AbortSignal: {
    timeout: (ms) => { __log.abortTimeouts.push(ms); return __RealAbortSignal.timeout(ms); },
    abort: (r) => __RealAbortSignal.abort(r),
    any: (list) => __RealAbortSignal.any(list),
  },
  location: { reload() { __log.reloads += 1; }, assign() {} },
};
__stubs.window = {
  get crypto() { return __stubs.crypto; },
  get navigator() { return __stubs.navigator; },
  get indexedDB() { return __stubs.indexedDB; },
  get BroadcastChannel() { return __stubs.BroadcastChannel; },
  get location() { return __stubs.location; },
};
const __scope = new Proxy(__stubs, {
  has(target, key) {
    if (typeof key !== "string" || key.startsWith("__")) return false;
    return key in target || !(key in globalThis);
  },
  get(target, key) {
    if (key === Symbol.unscopables) return undefined;
    if (key in target) return target[key];
    return __unknown;
  },
  set(target, key, value) { target[key] = value; return true; },
});
"""

#: Helpers that call the extracted functions, so they run INSIDE the scope.
_TAB_HELPERS = r"""
function __tabState(identity) {
  return { csrfToken: "", pageIdentity: identity, pageIdentityChanged: false, sharingOff: false,
    renewing: false, tokenGen: null, tokenSeq: 0 };
}
/** A tab: its own state and outbox, the profile's shared storage and locks. */
function __tab(name, identity, world, locks) {
  const tab = { name, identity, state: __tabState(identity), outbox: [], fetches: 0, world, locks };
  tab.channel = { postMessage(m) { tab.outbox.push(__clone(m)); __log.posts.push(__clone(m)); } };
  tab.idb = __makeIDB({}, world);
  return tab;
}
/** The server: one strict order of tokens; ``latest`` is the one it holds. */
function __server() {
  const s = { n: 0, latest: null };
  s.issue = () => { s.n += 1; s.latest = __tok(s.n); return s.latest; };
  return s;
}
function __sessionFor(identity, token) {
  if (identity === "anonymous") return { csrf_token: token, anonymous: true };
  if (!identity) return { csrf_token: token };
  return { csrf_token: token, account_id: identity };
}
/** The tab's ``/v1/session``: the server issues at once, the answer comes
 *  back after ``opts.wait`` (a promise) or ``opts.delayMs``. */
function __fetchFor(tab, server, opts) {
  return async () => {
    tab.fetches += 1;
    const token = server.issue();
    if (opts.wait) await opts.wait; else if (opts.delayMs) await __sleep(opts.delayMs);
    if (opts.fail) throw opts.fail;
    return __sessionFor(opts.answerIdentity === undefined ? tab.identity : opts.answerIdentity,
      token);
  };
}
function __renew(tab, server, opts) {
  opts = opts || {};
  return renewSessionToken({
    locks: "locks" in opts ? opts.locks : tab.locks,
    indexedDB: "indexedDB" in opts ? opts.indexedDB : tab.idb,
    channel: "channel" in opts ? opts.channel : tab.channel,
    fetchSession: __fetchFor(tab, server, opts),
    state: tab.state,
    lockTimeoutMs: opts.lockTimeoutMs === undefined ? 2000 : opts.lockTimeoutMs,
    counterTimeoutMs: opts.counterTimeoutMs === undefined ? 2000 : opts.counterTimeoutMs,
  });
}
/** What the channel's handler does with a message, per the interface. */
function __deliver(message, tab) {
  if (acceptSharedToken(message, tab.state)) {
    tab.state.csrfToken = message.token; tab.state.tokenSeq = message.seq; return true;
  }
  return false;
}
"""


def _node(
    functions: list[str],
    body: str,
    *,
    answers: list[Any] | None = None,
    extra: str = "",
) -> Any:
    """Run ``body`` (an async function body) with ``functions`` lifted from
    app.js; returns what it returns. Fails on a thrown error, an unhandled
    rejection, or the 8 s deadline."""
    source = APP_JS.read_text(encoding="utf-8")
    texts = [_function(source, name) for name in functions]
    script = (
        _PRELUDE.replace("__ANSWERS__", json.dumps(answers or []))
        + "with (__scope) {\n"
        + _constants(source, texts)
        + "\n"
        + "\n".join(texts)
        + "\n"
        + extra
        + "\n"
        + _TAB_HELPERS
        + "\nPromise.race([(async () => {\n"
        + body
        + "\n})(), __sleep(8000).then(() => { throw new Error('harness deadline: 8 s'); })])"
        + ".then((out) => __sleep(20).then(() => {"
        + " console.log(JSON.stringify({ out: out === undefined ? null : out,"
        + " unhandled: __log.unhandled })); process.exit(0); }),"
        + " (e) => { console.log(JSON.stringify({ __error: String(e && e.stack || e) }));"
        + " process.exit(0); });\n}\n"
    )
    out = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=30, check=False
    )
    assert out.returncode == 0, out.stderr
    lines = out.stdout.strip().splitlines()
    assert lines, f"node printed nothing; stderr: {out.stderr}"
    decoded = json.loads(lines[-1])
    assert "__error" not in decoded, decoded["__error"]
    assert decoded["unhandled"] == [], decoded["unhandled"]
    return decoded["out"]


# =============================================================================
# 1. sharedTokenIdentity: the identity the message carries
# =============================================================================


def _identity(session_js: str) -> Any:
    return _node(["sharedTokenIdentity"], f"return sharedTokenIdentity({session_js});")


def test_the_identity_is_the_account_id_when_the_server_names_one() -> None:
    """Red when: a signed-in session's identity is not its account id, or
    ``anonymous: true`` beside an account wins over the account."""
    assert _identity('{ csrf_token: "t", account_id: "acct-X" }') == "acct-X"
    assert _identity('{ csrf_token: "t", account_id: "acct-X", anonymous: true }') == "acct-X"


def test_the_identity_is_anonymous_only_when_the_server_says_anonymous_true() -> None:
    """Red when: ``"anonymous"`` is given for anything but ``anonymous: true``
    (a missing account alone is not proof: a failed read gives neither,
    ADR-0175), or a non-string account id is used as an identity."""
    assert _identity('{ csrf_token: "t", anonymous: true }') == "anonymous"
    assert _identity('{ csrf_token: "t" }') == ""
    assert _identity('{ csrf_token: "t", anonymous: "true" }') == ""
    assert _identity('{ csrf_token: "t", anonymous: 1 }') == ""
    assert _identity('{ csrf_token: "t", account_id: 7, anonymous: false }') == ""


# =============================================================================
# 2. acceptSharedToken: the acceptance table, one condition per case
# =============================================================================

#: A message every condition accepts, and the state of the tab receiving it.
#: Each refused case below changes exactly ONE thing from these.
BASE_MESSAGE = (
    '{ kind: "csrf-token", token: "Ab-_9".padEnd(32, "z"), identity: "acct-X", gen: "G1", seq: 5 }'
)
BASE_STATE = (
    '{ pageIdentity: "acct-X", pageIdentityChanged: false, sharingOff: false, renewing: false,'
    ' tokenGen: "G1", tokenSeq: 4 }'
)


def _accept(
    message_patch: str = "{}", state_patch: str = "{}", *, message: str | None = None
) -> Any:
    msg = message if message is not None else f"Object.assign({BASE_MESSAGE}, {message_patch})"
    body = (
        f"const message = {msg};\n"
        f"const state = Object.assign({BASE_STATE}, {state_patch});\n"
        "return acceptSharedToken(message, state);"
    )
    return _node(["acceptSharedToken"], body)


def test_the_same_account_is_accepted() -> None:
    """X to X. Red when: a valid message from the same account is refused
    (the owner's case: Asha in two tabs, CHG-071). The positive partner of
    every refused case below."""
    assert _accept() is True


def test_anonymous_to_anonymous_is_accepted() -> None:
    """Case 3, "Accept it (Recommended)". Red when: two anonymous tabs do not
    share."""
    got = _accept('{ identity: "anonymous" }', '{ pageIdentity: "anonymous" }')
    assert got is True


def test_a_newer_number_is_accepted_however_far_ahead() -> None:
    """Red when: the comparison is ``seq === tokenSeq + 1`` rather than
    ``seq > tokenSeq`` (a tab that missed a message would then refuse every
    later one)."""
    assert _accept("{ seq: 900 }") is True


@pytest.mark.parametrize(
    ("message_patch", "state_patch"),
    [
        pytest.param('{ identity: "acct-Y" }', "{}", id="X-to-Y"),
        pytest.param('{ identity: "anonymous" }', "{}", id="anonymous-sender-to-X"),
        pytest.param(
            '{ identity: "acct-X" }', '{ pageIdentity: "anonymous" }', id="X-sender-to-anonymous"
        ),
        pytest.param('{ identity: "" }', "{}", id="unknown-sender-to-X"),
        pytest.param("{}", '{ pageIdentity: "" }', id="X-sender-to-unknown-page"),
        pytest.param('{ identity: "" }', '{ pageIdentity: "" }', id="unknown-to-unknown"),
        pytest.param("{ identity: null }", "{ pageIdentity: null }", id="null-to-null"),
        pytest.param("{ identity: 7 }", "{ pageIdentity: 7 }", id="number-identity"),
    ],
)
def test_another_or_an_unknown_identity_is_refused(message_patch: str, state_patch: str) -> None:
    """Case 1, "Do not share (Recommended)" (FM-1). Red when: the identity
    comparison is removed or loosened, or an empty identity is let through
    (``"" to ""`` is reachable: an unknown identity is stored as ``""``,
    Codex finding 3). Partner: X to X is accepted (above)."""
    assert _accept(message_patch, state_patch) is False


def test_a_page_whose_identity_changed_is_refused() -> None:
    """Red when: the ``pageIdentityChanged`` condition is removed (W87-2's
    rule: after a change nothing is shared into this page load)."""
    assert _accept("{}", "{ pageIdentityChanged: true }") is False


@pytest.mark.parametrize(
    "message",
    [
        pytest.param(
            f'Object.assign({BASE_MESSAGE}, {{ kind: "csrf-token-v2" }})', id="wrong-kind"
        ),
        pytest.param(
            f"(() => {{ const m = {BASE_MESSAGE}; delete m.kind; return m; }})()", id="no-kind"
        ),
        pytest.param("null", id="null"),
        pytest.param("undefined", id="undefined"),
        pytest.param("42", id="number"),
        pytest.param('"csrf-token"', id="string"),
        pytest.param("true", id="boolean"),
        pytest.param("[]", id="array"),
        pytest.param('{ kind: "csrf-token" }', id="kind-only"),
    ],
)
def test_a_malformed_message_is_refused_and_never_throws(message: str) -> None:
    """FM-9. Red when: the shape check is removed, or a malformed message
    throws in the handler (the harness fails on a thrown error). The result
    is exactly ``false``, not merely falsy."""
    assert _accept(message=message) is False


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("1234567890123456", id="number-not-string"),
        pytest.param('{ toString() { return "a".repeat(32); } }', id="object-with-toString"),
        pytest.param('""', id="empty"),
        pytest.param('"a".repeat(15)', id="15-chars-too-short"),
        pytest.param('"a".repeat(129)', id="129-chars-too-long"),
        pytest.param('"a".repeat(31) + "\\n"', id="trailing-newline"),
        pytest.param('"a".repeat(16) + "\\n" + "a".repeat(16)', id="inner-newline"),
        pytest.param('"a".repeat(31) + " "', id="space"),
        pytest.param('"a".repeat(31) + "+"', id="plus"),
        pytest.param('"a".repeat(31) + "/"', id="slash"),
        pytest.param('"a".repeat(31) + "="', id="equals"),
        pytest.param("null", id="null"),
        pytest.param('["a".repeat(32)]', id="array"),
    ],
)
def test_a_token_that_cannot_be_a_server_token_is_refused(token: str) -> None:
    """Codex finding 2. Red when: the token check is removed or loosened (a
    token with a newline cannot be an HTTP header; ``secrets.token_urlsafe``
    gives only ``[A-Za-z0-9_-]``), or the 16 or 128 bound moves outward.
    Partner: the boundary lengths below are accepted."""
    assert _accept(f"{{ token: {token} }}") is False


@pytest.mark.parametrize("length", [16, 32, 128])
def test_a_token_at_either_bound_is_accepted(length: int) -> None:
    """Red when: the 16 or 128 bound moves inward (literals on both sides
    of each bound: 15 and 129 are refused above), or ``-``/``_`` are not
    allowed."""
    token = f'"-_".concat("a".repeat({length - 2}))'
    assert _accept(f"{{ token: {token} }}") is True


def test_a_tab_whose_sharing_is_off_is_refused() -> None:
    """Item 5. Red when: a tab that renewed without the lock (or without the
    counter) still accepts."""
    assert _accept("{}", "{ sharingOff: true }") is False


def test_a_tab_in_the_middle_of_its_own_renewal_is_refused() -> None:
    """Red when: the ``renewing`` condition is removed (a message that lands
    while the tab's own answer is on its way would be overwritten by it, or
    would overwrite it)."""
    assert _accept("{}", "{ renewing: true }") is False


@pytest.mark.parametrize(
    "seq",
    [
        pytest.param("4", id="equal"),
        pytest.param("3", id="lower"),
        pytest.param("5.5", id="fraction"),
        pytest.param('"5"', id="string"),
        pytest.param("Number.MAX_SAFE_INTEGER + 1", id="not-safe"),
        pytest.param("Infinity", id="infinity"),
        pytest.param("NaN", id="nan"),
        pytest.param("null", id="null"),
    ],
)
def test_a_number_that_is_not_newer_or_not_a_safe_integer_is_refused(seq: str) -> None:
    """The order (FM-3). Red when: the ``seq > tokenSeq`` comparison is
    removed or made ``>=``, or the safe-integer check is removed. Partner:
    ``seq 5`` over ``tokenSeq 4`` is accepted (the base case)."""
    assert _accept(f"{{ seq: {seq} }}") is False


@pytest.mark.parametrize(
    ("message_patch", "state_patch"),
    [
        pytest.param('{ gen: "G2" }', "{}", id="other-gen"),
        pytest.param("{}", '{ tokenGen: "G2" }', id="tab-on-other-gen"),
        pytest.param("{ gen: null }", "{ tokenGen: null }", id="no-gen-either-side"),
        pytest.param("{}", "{ tokenGen: null, tokenSeq: 0 }", id="tab-never-held-a-number"),
        pytest.param("{}", "{ tokenGen: undefined, tokenSeq: undefined }", id="tab-never-renewed"),
        pytest.param("{ gen: 1 }", "{ tokenGen: 1 }", id="number-gen"),
    ],
)
def test_a_message_from_another_generation_is_refused(message_patch: str, state_patch: str) -> None:
    """The per-reset id (revision 5). Red when: the ``gen`` check is removed
    (a message from before the browser cleared the site's storage would be
    accepted: Codex's model printed ``{"oldSeq":41,...,"B":"Told"}``), or a
    tab that has not yet held a number accepts."""
    assert _accept(message_patch, state_patch) is False


# =============================================================================
# 3. takeTokenNumber: the shared counter
# =============================================================================

_COUNTER = ["takeTokenNumber"]


def test_a_missing_record_is_created_with_a_new_gen_and_seq_1() -> None:
    """Red when: the first number is not 1, ``gen`` is not a fresh
    ``crypto.randomUUID()``, the record holds anything but ``gen`` and
    ``seq`` (FM-8: never the token), or the names differ from
    ``quorum-session-token`` / ``counter`` / ``"counter"``."""
    got = _node(
        _COUNTER,
        "const world = __world(); const idb = __makeIDB({}, world);\n"
        "const n = await takeTokenNumber(idb, 1000);\n"
        "return { n, record: __record(world), opens: idb.log.opens.map((o) => o.name),"
        " stores: idb.log.txStores, keys: idb.log.putKeys };",
    )
    assert got["n"] == {"gen": "gen-1", "seq": 1}
    assert got["record"] == {"gen": "gen-1", "seq": 1}
    assert set(got["opens"]) == {"quorum-session-token"}
    assert got["stores"] and all(s == ["counter"] for s in got["stores"])
    assert got["keys"] == ["counter"]


def test_every_counter_transaction_is_readwrite() -> None:
    """Red when: the number is read in a ``readonly`` transaction and
    written in another (two tabs could then read the same number: read-only
    transactions overlap). Partner: at least one transaction ran."""
    got = _node(
        _COUNTER,
        "const idb = __makeIDB({}, __world()); await takeTokenNumber(idb, 1000);\n"
        "await takeTokenNumber(idb, 1000); return idb.log.txModes;",
    )
    assert got
    assert set(got) == {"readwrite"}


def test_two_renewals_take_two_different_numbers() -> None:
    """Red when: the counter is not written back, or two tabs that ask at
    once get the same number. One tab after another, then two at once on the
    same storage (a second factory = a second tab)."""
    got = _node(
        _COUNTER,
        "const world = __world(); const a = __makeIDB({}, world); const b = __makeIDB({}, world);\n"
        "const first = await takeTokenNumber(a, 1000); const second = await takeTokenNumber(b, "
        "1000);\n"
        "const both = await Promise.all([takeTokenNumber(a, 1000), takeTokenNumber(b, 1000)]);\n"
        "return { first, second, both, record: __record(world) };",
    )
    assert got["first"] == {"gen": "gen-1", "seq": 1}
    assert got["second"] == {"gen": "gen-1", "seq": 2}
    assert sorted(n["seq"] for n in got["both"]) == [3, 4]
    assert {n["gen"] for n in got["both"]} == {"gen-1"}
    assert got["record"] == {"gen": "gen-1", "seq": 4}


def test_an_existing_record_is_counted_on() -> None:
    """Red when: an existing record's ``gen`` is replaced, or its ``seq``
    is not raised by exactly one."""
    got = _node(
        _COUNTER,
        'const world = __world(); __seed(world, { gen: "G7", seq: 41 });\n'
        "const n = await takeTokenNumber(__makeIDB({}, world), 1000);\n"
        "return { n, record: __record(world) };",
    )
    assert got == {"n": {"gen": "G7", "seq": 42}, "record": {"gen": "G7", "seq": 42}}


def test_the_last_safe_number_is_taken_and_the_one_after_is_refused() -> None:
    """The exhausted counter, pinned with literals on both sides (rule 8b).
    Red when: the bound moves (a stored ``MAX_SAFE_INTEGER - 1`` must still
    give ``MAX_SAFE_INTEGER``; a stored ``MAX_SAFE_INTEGER`` must give
    ``null``), or the counter wraps."""
    got = _node(
        _COUNTER,
        'const w1 = __world(); __seed(w1, { gen: "G7", seq: 9007199254740990 });\n'
        'const w2 = __world(); __seed(w2, { gen: "G7", seq: 9007199254740991 });\n'
        "const last = await takeTokenNumber(__makeIDB({}, w1), 1000);\n"
        "const after = await takeTokenNumber(__makeIDB({}, w2), 1000);\n"
        "return { last: last && last.seq === Number.MAX_SAFE_INTEGER, lastGen: last && "
        "last.gen, after };",
    )
    assert got == {"last": True, "lastGen": "G7", "after": None}


@pytest.mark.parametrize(
    "record",
    [
        pytest.param('{ gen: "G7", seq: "41" }', id="seq-string"),
        pytest.param('{ gen: "G7", seq: 41.5 }', id="seq-fraction"),
        pytest.param('{ gen: "G7" }', id="seq-missing"),
        pytest.param('{ gen: "G7", seq: null }', id="seq-null"),
        pytest.param('"garbage"', id="not-an-object"),
    ],
)
def test_a_malformed_record_gives_no_number(record: str) -> None:
    """Red when: a malformed ``seq`` is counted on (``"41" + 1`` is
    ``"411"``) instead of falling back. Partner: a well-formed record is
    counted on (above)."""
    got = _node(
        _COUNTER,
        f"const world = __world(); __seed(world, {record});\n"
        "return await takeTokenNumber(__makeIDB({}, world), 1000);",
    )
    assert got is None


@pytest.mark.parametrize(
    "factory",
    [
        pytest.param("undefined", id="no-indexedDB"),
        pytest.param("null", id="null-indexedDB"),
        pytest.param("__makeIDB({ openThrows: true })", id="open-throws"),
        pytest.param("__makeIDB({ openError: true })", id="open-error"),
        pytest.param("__makeIDB({ txError: true })", id="transaction-fails"),
        pytest.param("__makeIDB({ blocked: true })", id="blocked"),
        pytest.param("__makeIDB({ blocked: true, lateMs: 60 })", id="blocked-then-late-success"),
    ],
)
def test_a_counter_that_fails_gives_null(factory: str) -> None:
    """Red when: a missing, refused, failed or blocked IndexedDB throws or
    gives a number instead of ``null`` (the fall-back: sharing off, today's
    behaviour), or does not give it AT ONCE: the limit here is 5000 ms and
    the answer must come within 1000 ms, so a page that ignores the
    ``error``/``blocked``/``abort`` event and only gets ``null`` from its time
    limit goes red. ``transaction-fails``: the put succeeds but the
    transaction aborts, so a page that resolves on the put's success, not on
    ``complete``, goes red here."""
    got = _node(
        _COUNTER,
        f"const t0 = Date.now(); const n = await takeTokenNumber({factory}, 5000);\n"
        "return { n, quick: Date.now() - t0 < 1000 };",
    )
    assert got == {"n": None, "quick": True}


def test_an_open_that_never_answers_gives_null_at_its_time_limit() -> None:
    """The bounded counter (revision 5). Red when: the limit is removed
    (Codex's probe of the unbounded step printed ``"sessionFetches":0``), or
    it does not hold to the time given (40 ms here; resolved well within
    1000 ms)."""
    got = _node(
        _COUNTER,
        "const t0 = Date.now(); const n = await takeTokenNumber(__makeIDB({ never: true }), 40);\n"
        "return { n, quick: Date.now() - t0 < 1000 };",
    )
    assert got == {"n": None, "quick": True}


def test_a_late_completion_after_the_limit_is_ignored() -> None:
    """Red when: the counter step's late answer changes the result already
    given, or throws or rejects unhandled after it (the harness fails on an
    unhandled rejection). Partner: the same storage answering in time gives
    a number."""
    got = _node(
        _COUNTER,
        "const n = await takeTokenNumber(__makeIDB({ lateMs: 120 }), 40); await __sleep(250);\n"
        "const inTime = await takeTokenNumber(__makeIDB({ lateMs: 10 }), 1000);\n"
        "return { n, inTime: inTime !== null };",
    )
    assert got == {"n": None, "inTime": True}


def test_the_number_is_given_only_after_the_transaction_completes() -> None:
    """Red when: the page resolves on the ``put`` request's success rather
    than the transaction's ``complete`` event (the write is not durable
    until then). The complete is held 80 ms after the put here."""
    got = _node(
        _COUNTER,
        "const idb = __makeIDB({ completeDelayMs: 80 });\n"
        "const n = await takeTokenNumber(idb, 1000); return { n, completedFirst: "
        "idb.log.completed === 1 };",
    )
    assert got == {"n": {"gen": "gen-1", "seq": 1}, "completedFirst": True}


def test_versionchange_closes_the_connection() -> None:
    """Red when: the page does not call ``close()`` on ``versionchange``
    (another tab's upgrade would stay blocked). The event is fired while the
    transaction is still open (its complete is held 60 ms), so a page that
    only closes after it is done goes red."""
    got = _node(
        _COUNTER,
        "const idb = __makeIDB({ versionchangeAfterOpen: true, completeDelayMs: 60 });\n"
        "await takeTokenNumber(idb, 1000); await __sleep(80);\n"
        "return idb.log.closedOnVersionchange;",
    )
    assert got is True


def test_the_counter_limit_defaults_to_10000_ms() -> None:
    """Red when: the default moves from 10000 ms, or the time given is not
    used. Pinned on the argument the timer is given (rule 8b), both ways:
    omitted gives 10000, an explicit 2222 gives 2222 and no 10000."""
    got = _node(
        _COUNTER,
        "await takeTokenNumber(__makeIDB({})); const omitted = "
        "__log.timers.concat(__log.abortTimeouts);\n"
        "__log.timers.length = 0; __log.abortTimeouts.length = 0;\n"
        "await takeTokenNumber(__makeIDB({}), 2222); const given = "
        "__log.timers.concat(__log.abortTimeouts);\n"
        "return { omitted, given };",
    )
    assert 10000 in got["omitted"]
    assert 2222 in got["given"]
    assert 10000 not in got["given"]


# =============================================================================
# 4. renewSessionToken: one renewal
# =============================================================================

_RENEW = [
    "acceptSharedToken",
    "sharedTokenIdentity",
    "keepRenewedToken",
    "takeTokenNumber",
    "renewSessionToken",
]


def test_a_locked_renewal_posts_one_message_with_exactly_five_fields() -> None:
    """Red when: no post, more than one post, a field missing or added (FM-8:
    no email, nothing else), the state not updated with the token and its
    number, or the lock's name is not ``quorum-session-token`` or its wait
    has no signal."""
    got = _node(
        _RENEW,
        'const locks = __makeLocks(); const tab = __tab("A", "acct-X", __world(), locks);\n'
        "const server = __server(); await __renew(tab, server);\n"
        "return { posts: tab.outbox, state: tab.state, fetches: tab.fetches, server: server.latest,"
        " requests: locks.requests };",
    )
    token = "T1_".ljust(32, "x")
    assert got["fetches"] == 1
    assert got["posts"] == [
        {"kind": "csrf-token", "token": token, "identity": "acct-X", "gen": "gen-1", "seq": 1}
    ]
    assert got["state"]["csrfToken"] == token == got["server"]
    assert got["state"]["tokenGen"] == "gen-1"
    assert got["state"]["tokenSeq"] == 1
    assert not got["state"]["renewing"]
    assert not got["state"]["sharingOff"]
    assert [(r["name"], r["hasSignal"]) for r in got["requests"]] == [
        ("quorum-session-token", True)
    ]


def test_inside_the_lock_the_number_is_taken_before_the_fetch() -> None:
    """Red when: the fetch runs outside the lock, before the number is taken
    (the numbers would then not follow the server's order), or
    ``state.renewing`` is not set while the answer is on its way."""
    got = _node(
        _RENEW,
        'const world = __world(); const locks = __makeLocks(); const tab = __tab("A", "acct-X", '
        "world, locks);\n"
        "let seen = null; const state = tab.state;\n"
        "await renewSessionToken({ locks, indexedDB: tab.idb, channel: tab.channel, state,\n"
        "  lockTimeoutMs: 1000, counterTimeoutMs: 1000,\n"
        '  fetchSession: async () => { seen = { held: locks.held.has("quorum-session-token"),\n'
        "    record: __record(world), renewing: state.renewing === true };\n"
        '    return { csrf_token: __tok(1), account_id: "acct-X" }; } });\n'
        "return { seen, after: state.renewing };",
    )
    assert got["seen"] == {"held": True, "record": {"gen": "gen-1", "seq": 1}, "renewing": True}
    assert not got["after"]


def test_a_second_renewal_posts_the_next_number_in_the_same_generation() -> None:
    """Red when: a tab's second renewal reuses its number, starts a new
    ``gen``, or posts twice."""
    got = _node(
        _RENEW,
        'const tab = __tab("A", "acct-X", __world(), __makeLocks()); const server = __server();\n'
        "await __renew(tab, server); await __renew(tab, server);\n"
        "return tab.outbox.map((m) => [m.gen, m.seq, m.token === __tok(m.seq)]);",
    )
    assert got == [["gen-1", 1, True], ["gen-1", 2, True]]


def test_an_anonymous_renewal_posts_the_anonymous_identity() -> None:
    """Case 3. Red when: an anonymous session posts nothing, or posts an
    identity other than ``"anonymous"``."""
    got = _node(
        _RENEW,
        'const tab = __tab("A", "anonymous", __world(), __makeLocks()); await __renew(tab, '
        "__server());\n"
        "return tab.outbox.map((m) => m.identity);",
    )
    assert got == ["anonymous"]


def test_a_renewal_whose_identity_is_unknown_sets_the_token_and_posts_nothing() -> None:
    """Red when: an answer with neither ``account_id`` nor ``anonymous:
    true`` is shared (its receiver could not check who sent it), or its
    token is not used by this tab. Partner: a known identity posts (above)."""
    got = _node(
        _RENEW,
        'const tab = __tab("A", "", __world(), __makeLocks()); await __renew(tab, __server());\n'
        "return { posts: tab.outbox.length, token: tab.state.csrfToken === __tok(1), fetches: "
        "tab.fetches };",
    )
    assert got == {"posts": 0, "token": True, "fetches": 1}


def test_a_renewal_in_a_tab_whose_sharing_is_off_posts_nothing() -> None:
    """Item 5. Red when: a tab that once renewed without the lock posts on a
    later renewal. Partner: its token is still renewed."""
    got = _node(
        _RENEW,
        'const tab = __tab("A", "acct-X", __world(), __makeLocks()); tab.state.sharingOff = true;\n'
        "await __renew(tab, __server());\n"
        "return { posts: tab.outbox.length, token: tab.state.csrfToken === __tok(1), off: "
        "tab.state.sharingOff };",
    )
    assert got == {"posts": 0, "token": True, "off": True}


def test_a_renewal_with_no_channel_still_renews() -> None:
    """FM-10: no ``BroadcastChannel``. Red when: a missing channel throws or
    stops the token being set."""
    got = _node(
        _RENEW,
        'const tab = __tab("A", "acct-X", __world(), __makeLocks());\n'
        "await __renew(tab, __server(), { channel: null });\n"
        "return { token: tab.state.csrfToken === __tok(1), fetches: tab.fetches, posts: "
        "__log.posts.length };",
    )
    assert got == {"token": True, "fetches": 1, "posts": 0}


def test_the_identity_posted_is_the_one_answered_inside_the_lock() -> None:
    """Codex finding 7: an account change while waiting. The tab's state
    says X before the wait; the answer inside the lock says Y. Red when: the
    identity is taken from before the wait (the message would claim X for
    Y's token)."""
    got = _node(
        _RENEW,
        'const locks = __makeLocks(); const release = locks.hold("quorum-session-token");\n'
        'const tab = __tab("A", "acct-X", __world(), locks); tab.state.sessionAccountId = '
        '"acct-X";\n'
        'const renewal = __renew(tab, __server(), { answerIdentity: "acct-Y" });\n'
        "await __sleep(30); release(); await renewal;\n"
        "return tab.outbox.map((m) => m.identity);",
    )
    assert got == ["acct-Y"]


def test_both_time_limits_default_to_10000_ms() -> None:
    """Red when: either default moves from 10000 ms, or the lock's wait is
    not bounded with ``AbortSignal.timeout(lockTimeoutMs)``. Pinned on the
    arguments, both ways: omitted gives two 10000s; 1111 and 2222 given
    give those and no 10000."""
    got = _node(
        _RENEW,
        'const t1 = __tab("A", "acct-X", __world(), __makeLocks()); const server = __server();\n'
        "await renewSessionToken({ locks: t1.locks, indexedDB: t1.idb, channel: t1.channel, "
        "state: t1.state,\n"
        '  fetchSession: async () => ({ csrf_token: __tok(1), account_id: "acct-X" }) });\n'
        "const omitted = { signal: __log.abortTimeouts.slice(), all: "
        "__log.abortTimeouts.concat(__log.timers) };\n"
        "__log.abortTimeouts.length = 0; __log.timers.length = 0;\n"
        'const t2 = __tab("B", "acct-X", __world(), __makeLocks());\n'
        "await __renew(t2, server, { lockTimeoutMs: 1111, counterTimeoutMs: 2222 });\n"
        "const given = { signal: __log.abortTimeouts.slice(), all: "
        "__log.abortTimeouts.concat(__log.timers) };\n"
        "return { omitted, given, posted: t1.outbox.length };",
    )
    assert got["posted"] == 1
    assert 10000 in got["omitted"]["signal"]
    assert got["omitted"]["all"].count(10000) >= 2
    assert 1111 in got["given"]["signal"]
    assert 2222 in got["given"]["all"]
    assert 10000 not in got["given"]["all"]


# =============================================================================
# 5. Compatibility and bounded recovery: renewing without the lock
# =============================================================================


@pytest.mark.parametrize(
    "locks",
    [
        pytest.param("undefined", id="no-navigator-locks"),
        pytest.param("null", id="null-locks"),
        pytest.param('__makeLocks({ reject: "SecurityError" })', id="request-rejects"),
        pytest.param('__makeLocks({ throwSync: "SecurityError" })', id="request-throws"),
    ],
)
def test_without_the_lock_the_tab_renews_once_and_stops_sharing(locks: str) -> None:
    """Red when: a lock that is missing or fails BEFORE its callback stops
    the boot, renews twice or not at all, or the tab still posts, takes a
    number, or accepts afterwards. Partner: its own token is set."""
    got = _node(
        _RENEW,
        f'const world = __world(); const tab = __tab("B", "acct-X", world, {locks});\n'
        "await __renew(tab, __server());\n"
        'const offer = { kind: "csrf-token", token: __tok(9), identity: "acct-X", gen: "gen-1", '
        "seq: 99 };\n"
        'tab.state.tokenGen = "gen-1";\n'
        "return { fetches: tab.fetches, posts: tab.outbox.length, off: tab.state.sharingOff,\n"
        "  token: tab.state.csrfToken === __tok(1), record: __record(world),\n"
        "  accepts: acceptSharedToken(offer, tab.state) };",
    )
    assert got == {
        "fetches": 1,
        "posts": 0,
        "off": True,
        "token": True,
        "record": None,
        "accepts": False,
    }


def test_without_the_lock_a_failing_fetch_goes_out_as_today() -> None:
    """Red when: the lockless fallback swallows the fetch's error, or
    retries it. Exactly one fetch."""
    got = _node(
        _RENEW,
        'const tab = __tab("B", "acct-X", __world(), undefined);\n'
        'const boom = new Error("fetch failed");\n'
        "let caught = null; try { await __renew(tab, __server(), { fail: boom }); } catch (e) { "
        "caught = e; }\n"
        "return { same: caught === boom, fetches: tab.fetches, posts: tab.outbox.length };",
    )
    assert got == {"same": True, "fetches": 1, "posts": 0}


def test_a_failure_inside_the_lock_is_thrown_once_and_not_retried() -> None:
    """Codex: a catch-all fallback printed ``{"renewalCalls":2,...}``. Red
    when: a fetch that fails INSIDE the acquired callback is treated as a
    lock failure and renewed a second time, the error is not rethrown as it
    is, something is posted, or ``renewing`` is left set."""
    got = _node(
        _RENEW,
        'const tab = __tab("A", "acct-X", __world(), __makeLocks());\n'
        'const boom = new Error("Could not start a session.");\n'
        "let caught = null; try { await __renew(tab, __server(), { fail: boom }); } catch (e) { "
        "caught = e; }\n"
        "return { same: caught === boom, fetches: tab.fetches, posts: tab.outbox.length,\n"
        "  renewing: tab.state.renewing === true };",
    )
    assert got == {"same": True, "fetches": 1, "posts": 0, "renewing": False}


def test_a_lock_wait_that_times_out_renews_without_the_lock_and_ignores_the_late_holder() -> None:
    """E3b's unit twin. Tab H holds the lock with a slow answer; tab B's
    40 ms wait ends. Red when: B waits for H (the time limit is not applied),
    B takes a number, posts, or later accepts H's late message, or B renews
    more than once. Partner: H's late message IS posted and B keeps its own,
    newer token, which is the server's."""
    got = _node(
        _RENEW,
        "const world = __world(); const locks = __makeLocks(); const server = __server();\n"
        'const h = __tab("H", "acct-X", world, locks); const b = __tab("B", "acct-X", world, '
        "locks);\n"
        "const held = __renew(h, server, { delayMs: 200 });\n"
        "await __sleep(20); const t0 = Date.now();\n"
        "await __renew(b, server, { lockTimeoutMs: 40 }); const waited = Date.now() - t0;\n"
        "const bNumber = b.state.tokenSeq; await held;\n"
        "const accepted = h.outbox.map((m) => __deliver(m, b));\n"
        "return { waitedUnder: waited < 190, bFetches: b.fetches, bPosts: b.outbox.length,\n"
        "  hPosts: h.outbox.length, accepted, bToken: b.state.csrfToken, server: server.latest,\n"
        "  bNumber, off: b.state.sharingOff, record: __record(world) };",
    )
    assert got["waitedUnder"] is True
    assert got["bFetches"] == 1
    assert got["bPosts"] == 0
    assert got["hPosts"] == 1
    assert got["accepted"] == [False]
    assert got["bToken"] == got["server"] == "T2_".ljust(32, "x")
    assert got["off"] is True
    assert got["record"] == {"gen": "gen-1", "seq": 1}


def test_after_a_lockless_renewal_a_locked_retry_keeps_sharing_off() -> None:
    """Item 5: for the rest of the page load. Red when: a later renewal that
    does hold the lock turns sharing back on (posts, or accepts). Partner:
    the retry renews the token."""
    got = _node(
        _RENEW,
        'const tab = __tab("B", "acct-X", __world(), __makeLocks()); const server = __server();\n'
        "await __renew(tab, server, { locks: undefined }); await __renew(tab, server);\n"
        'const offer = { kind: "csrf-token", token: __tok(9), identity: "acct-X",\n'
        '  gen: tab.state.tokenGen || "gen-1", seq: 99 };\n'
        "return { fetches: tab.fetches, posts: tab.outbox.length, off: tab.state.sharingOff,\n"
        "  token: tab.state.csrfToken === __tok(2), accepts: acceptSharedToken(offer, "
        "tab.state) };",
    )
    assert got == {"fetches": 2, "posts": 0, "off": True, "token": True, "accepts": False}


# =============================================================================
# 6. The counter's failures, through a whole renewal
# =============================================================================


@pytest.mark.parametrize(
    ("factory", "seed"),
    [
        pytest.param("undefined", None, id="no-indexedDB"),
        pytest.param("{ openThrows: true }", None, id="open-refused"),
        pytest.param("{ openError: true }", None, id="open-error"),
        pytest.param("{ txError: true }", None, id="transaction-fails"),
        pytest.param("{ blocked: true }", None, id="blocked"),
        pytest.param("{ never: true }", None, id="never-answers"),
        pytest.param("{}", '{ gen: "G7", seq: "41" }', id="malformed"),
        pytest.param("{}", '{ gen: "G7", seq: 9007199254740991 }', id="exhausted"),
    ],
)
def test_a_counter_failure_renews_once_and_stops_sharing(factory: str, seed: str | None) -> None:
    """Revision 5. Red when: a counter that is missing, refused, failing,
    blocked, silent (40 ms limit here), malformed or exhausted makes more or
    fewer than ONE ``/v1/session`` fetch, leaves sharing on, posts, or stops
    the token being set."""
    idb = "undefined" if factory == "undefined" else f"__makeIDB({factory}, world)"
    seeding = f"__seed(world, {seed});" if seed else ""
    got = _node(
        _RENEW,
        f'const world = __world(); {seeding} const tab = __tab("A", "acct-X", world, '
        f"__makeLocks());\n"
        f"await __renew(tab, __server(), {{ indexedDB: {idb}, counterTimeoutMs: 40 }});\n"
        "return { fetches: tab.fetches, posts: tab.outbox.length, off: tab.state.sharingOff,\n"
        "  token: tab.state.csrfToken === __tok(1) };",
    )
    assert got == {"fetches": 1, "posts": 0, "off": True, "token": True}


def test_a_counter_that_answers_after_its_limit_changes_nothing() -> None:
    """Red when: the counter step's late completion is used after the
    renewal went ahead without it (a post, or a number set). Partner: the
    renewal itself went ahead with one fetch."""
    got = _node(
        _RENEW,
        'const world = __world(); const tab = __tab("A", "acct-X", world, __makeLocks());\n'
        "await __renew(tab, __server(), { indexedDB: __makeIDB({ lateMs: 120 }, world), "
        "counterTimeoutMs: 40 });\n"
        "const at = { gen: tab.state.tokenGen, seq: tab.state.tokenSeq }; await __sleep(250);\n"
        "return { fetches: tab.fetches, posts: tab.outbox.length, off: tab.state.sharingOff,\n"
        "  unchanged: tab.state.tokenGen === at.gen && tab.state.tokenSeq === at.seq,\n"
        "  token: tab.state.csrfToken === __tok(1) };",
    )
    assert got == {"fetches": 1, "posts": 0, "off": True, "unchanged": True, "token": True}


# =============================================================================
# 7. The order: Codex's counterexamples as regressions
# =============================================================================


def _late_message(prelude: str = "") -> Any:
    return _node(
        _RENEW,
        prelude
        + "const world = __world(); const locks = __makeLocks(); const server = __server();\n"
        'const a = __tab("A", "acct-X", world, locks); const b = __tab("B", "acct-X", world, '
        "locks);\n"
        "await __renew(a, server); await __renew(b, server);\n"
        "const late = a.outbox[0];\n"
        "const toA = b.outbox.map((m) => __deliver(m, a)); const toB = __deliver(late, b);\n"
        "return { a: a.state.csrfToken, b: b.state.csrfToken, server: server.latest, toA, toB,\n"
        "  seqs: [late.seq, b.outbox[0].seq] };",
    )


def test_a_late_message_is_ignored_by_a_tab_with_a_newer_token() -> None:
    """A takes 1 then B takes 2; A's message reaches B only after B's own
    renewal. Red when: the ``seq`` comparison is removed (B would take A's
    older T1 and both tabs would hold a token the server retired). Partner:
    B's message IS taken by A."""
    got = _late_message()
    t2 = "T2_".ljust(32, "x")
    assert got["seqs"] == [1, 2]
    assert got["toA"] == [True]
    assert got["toB"] is False
    assert got["a"] == got["b"] == got["server"] == t2


def test_the_order_does_not_depend_on_any_tab_clock() -> None:
    """Codex's second check: tabs' clocks can disagree
    (``{"atA":101000,"atB":1001,...}``). Here ``Date.now`` runs backwards
    and ``performance.now`` jumps around for the whole run. Red when: the
    order is taken from a clock (the late T1 would then win)."""
    skew = (
        "let __back = 2e12; Date.now = () => (__back -= 100000);\n"
        "let __jump = 0; performance.now = () => ((__jump += 1) % 2 ? 1e9 : 1);\n"
    )
    got = _late_message(skew)
    t2 = "T2_".ljust(32, "x")
    assert got["toB"] is False
    assert got["a"] == got["b"] == got["server"] == t2


def test_the_timeout_variant_a_keeps_its_own_token() -> None:
    """B posted with k, then renewed without the lock; A renewed after it,
    locked, with k+1; B's old message reaches A. Red when: ``seq`` is not
    compared, so A takes B's older token."""
    got = _node(
        _RENEW,
        "const world = __world(); const locks = __makeLocks(); const server = __server();\n"
        'const a = __tab("A", "acct-X", world, locks); const b = __tab("B", "acct-X", world, '
        "locks);\n"
        "await __renew(b, server);\n"
        "await __renew(b, server, { locks: undefined });\n"
        "await __renew(a, server);\n"
        "const old = b.outbox[0]; const took = __deliver(old, a);\n"
        "return { took, a: a.state.csrfToken, server: server.latest, seqs: [old.seq, "
        "a.state.tokenSeq],\n"
        "  bPosts: b.outbox.length };",
    )
    assert got["bPosts"] == 1
    assert got["seqs"] == [1, 2]
    assert got["took"] is False
    assert got["a"] == got["server"] == "T3_".ljust(32, "x")


def test_three_tabs_an_accept_then_a_renewal_never_goes_back() -> None:
    """C renews (1), A renews (2), B renews (3); C accepts B's 3, then renews
    with 4; A's late 2 reaches C. Red when: ``tokenSeq`` can go down, or an
    accepted number is not recorded (C would take A's T2). Partner: C did
    accept B's message."""
    got = _node(
        _RENEW,
        "const world = __world(); const locks = __makeLocks(); const server = __server();\n"
        'const a = __tab("A", "acct-X", world, locks); const b = __tab("B", "acct-X", world, '
        "locks);\n"
        'const c = __tab("C", "acct-X", world, locks);\n'
        "await __renew(c, server); await __renew(a, server); await __renew(b, server);\n"
        "const fromB = __deliver(b.outbox[0], c); const seqAfterAccept = c.state.tokenSeq;\n"
        "await __renew(c, server);\n"
        "const fromA = __deliver(a.outbox[0], c);\n"
        "return { fromB, seqAfterAccept, fromA, c: c.state.csrfToken, cSeq: c.state.tokenSeq,\n"
        "  server: server.latest };",
    )
    assert got["fromB"] is True
    assert got["seqAfterAccept"] == 3
    assert got["fromA"] is False
    assert got["cSeq"] == 4
    assert got["c"] == got["server"] == "T4_".ljust(32, "x")


def test_a_message_from_before_a_storage_reset_is_ignored() -> None:
    """Codex's fourth check: A posts (G1, 41) late; the browser clears the
    site's storage; B creates (gen-1, 1) and renews; A's message reaches B.
    Red when: the ``gen`` check is removed (41 > 1, so B would take A's
    older token: Codex's model printed ``"B":"Told"``). The reverse is
    refused too: A, still on G1, does not take B's new-generation message
    (stale at worst, as today)."""
    got = _node(
        _RENEW,
        'const world = __world(); __seed(world, { gen: "G1", seq: 40 });\n'
        "const locks = __makeLocks(); const server = __server();\n"
        'const a = __tab("A", "acct-X", world, locks); const b = __tab("B", "acct-X", world, '
        "locks);\n"
        "await __renew(a, server);\n"
        "world.dbs.clear();\n"
        "await __renew(b, server);\n"
        "const late = a.outbox[0]; const toB = __deliver(late, b); const toA = "
        "__deliver(b.outbox[0], a);\n"
        "return { late: [late.gen, late.seq], bNumber: [b.state.tokenGen, b.state.tokenSeq], "
        "toB, toA,\n"
        "  b: b.state.csrfToken, server: server.latest };",
    )
    assert got["late"] == ["G1", 41]
    assert got["bNumber"] == ["gen-1", 1]
    assert got["toB"] is False
    assert got["toA"] is False
    assert got["b"] == got["server"] == "T2_".ljust(32, "x")


# =============================================================================
# 8. The page's wiring: initSession, retrySession and the message handler
# =============================================================================

_WIRED = ["initSession", "retrySession", *_RENEW]


def _bootstrap(identity: str, token: str) -> dict[str, Any]:
    body: dict[str, Any] = {"csrf_token": token, "expires_at": "2026-10-25T00:00:00+00:00"}
    if identity == "anonymous":
        body["anonymous"] = True
    elif identity:
        body["account_id"] = identity
    return body


def test_boot_and_retry_each_make_one_session_fetch_and_one_post() -> None:
    """Codex re-check finding 6: ``retrySession`` calls ``initSession``, so
    it renews and posts too. Red when: ``initSession`` does not go through
    ``renewSessionToken`` (no lock, no post), or either path fetches or posts
    more than once. Partner: W87-2's identity is still recorded."""
    t1, t2 = "B1".ljust(32, "q"), "B2".ljust(32, "q")
    got = _node(
        _WIRED,
        "navigator.locks = __makeLocks(); indexedDB = __makeIDB({}, __world());\n"
        "await initSession(); const boot = { fetch: __log.fetch, posts: __log.posts.length };\n"
        "await retrySession();\n"
        "return { boot, fetch: __log.fetch, urls: __log.fetchUrls, posts: __log.posts,\n"
        "  token: state.csrfToken, pageIdentity: state.pageIdentity,\n"
        "  locks: navigator.locks.requests.map((r) => r.name), reloads: __log.reloads };",
        answers=[_bootstrap("acct-X", t1), _bootstrap("acct-X", t2)],
    )
    assert got["boot"] == {"fetch": 1, "posts": 1}
    assert got["fetch"] == 2
    assert got["urls"] == ["/v1/session", "/v1/session"]
    assert [(p["token"], p["identity"], p["seq"]) for p in got["posts"]] == [
        (t1, "acct-X", 1),
        (t2, "acct-X", 2),
    ]
    assert got["token"] == t2
    assert got["pageIdentity"] == "acct-X"
    assert got["locks"] == ["quorum-session-token", "quorum-session-token"]
    assert got["reloads"] == 0


def test_initSession_with_no_browser_api_still_sets_the_token() -> None:
    """FM-10: no ``navigator.locks``, no IndexedDB, no channel. Red when: the
    boot depends on any of them (throws, or no token), or the page shares
    anyway."""
    token = "N1".ljust(32, "q")
    got = _node(
        _WIRED,
        "navigator.locks = undefined; indexedDB = undefined; BroadcastChannel = undefined;\n"
        "await initSession();\n"
        "return { token: state.csrfToken, fetch: __log.fetch, posts: __log.posts.length };",
        answers=[_bootstrap("acct-X", token)],
    )
    assert got == {"token": token, "fetch": 1, "posts": 0}


def _handler_run(message: str, state: str) -> Any:
    source = APP_JS.read_text(encoding="utf-8")
    handler = _message_handler(source)
    body = (
        f"Object.assign(state, {state});\n"
        "const before = JSON.parse(JSON.stringify(state));\n"
        f"const message = {message};\n"
        "const event = Object.assign({}, message, { data: message });\n"
        "await __handler(event); await __sleep(20);\n"
        "const after = JSON.parse(JSON.stringify(state)); const changed = {};\n"
        "for (const k of new Set([...Object.keys(before), ...Object.keys(after)])) {\n"
        "  if (JSON.stringify(before[k]) !== JSON.stringify(after[k])) changed[k] = after[k] "
        "=== undefined ? null : after[k];\n"
        "}\n"
        "return { changed, fetch: __log.fetch, posts: __log.posts.length, reloads: __log.reloads };"
    )
    return _node(_RENEW, body, extra=f"const __handler = ({handler});")


_HANDLER_STATE = (
    '{ csrfToken: "OLD".padEnd(32, "o"), pageIdentity: "acct-X", pageIdentityChanged: false,'
    ' sharingOff: false, renewing: false, tokenGen: "G1", tokenSeq: 4 }'
)


def test_receiving_a_token_changes_only_the_token_and_its_number() -> None:
    """FM-7 and FM-14. Red when: the handler fetches, posts (a loop needs
    only one of these), reloads, or changes anything in the page state but
    ``csrfToken`` and ``tokenSeq``; or does not take a valid message. The
    handler is the function in app.js that calls ``acceptSharedToken``; it
    is given an event whose ``data`` is the message (and, so a handler
    that is passed the message itself also works, the message's own fields)."""
    got = _handler_run(
        '{ kind: "csrf-token", token: "NEW".padEnd(32, "n"), identity: "acct-X", gen: "G1", '
        "seq: 6 }",
        _HANDLER_STATE,
    )
    assert got == {
        "changed": {"csrfToken": "NEW".ljust(32, "n"), "tokenSeq": 6},
        "fetch": 0,
        "posts": 0,
        "reloads": 0,
    }


def test_receiving_a_refused_token_changes_nothing() -> None:
    """Red when: the handler sets the token without asking
    ``acceptSharedToken`` (another person's token is taken), or does anything
    else on a refusal. Partner: the same handler takes a valid message
    (above)."""
    got = _handler_run(
        '{ kind: "csrf-token", token: "NEW".padEnd(32, "n"), identity: "acct-Y", gen: "G1", '
        "seq: 6 }",
        _HANDLER_STATE,
    )
    assert got == {"changed": {}, "fetch": 0, "posts": 0, "reloads": 0}


_CHANNEL = re.compile(r"""new\s+BroadcastChannel\(\s*(["'])quorum-session-token\1\s*\)""")


def _code_lines(text: str) -> list[str]:
    """Lines that are not ``//`` or ``*`` comment lines."""
    return [ln for ln in text.splitlines() if not ln.lstrip().startswith(("//", "*", "/*"))]


def test_the_channel_is_opened_once_and_not_per_renewal() -> None:
    """Item 1 (FM-4). Red when: app.js opens no ``quorum-session-token``
    channel, opens it more than once, or opens it inside ``initSession`` or
    ``renewSessionToken`` (a new channel per renewal, and a booting tab
    could miss a neighbour's message). Comment lines are not counted."""
    source = APP_JS.read_text(encoding="utf-8")
    opened = [ln for ln in _code_lines(source) if _CHANNEL.search(ln)]
    assert len(opened) == 1, opened
    for name in ("initSession", "renewSessionToken"):
        assert not _CHANNEL.search(_function(source, name)), name


@pytest.mark.parametrize("template", ["capped-sign-in.html", "session-capped.html"])
def test_the_capped_pages_never_join_the_channel(template: str) -> None:
    """FM-12. Red when: a capped page (its own token, no app.js) joins the
    channel. Partner: app.js does (the test above), and the template
    exists."""
    path = TEMPLATES / template
    assert path.is_file(), path
    assert "BroadcastChannel" not in path.read_text(encoding="utf-8")


# =============================================================================
# 9. The lane's new read of a session's account stays test-only
# =============================================================================


def test_the_session_account_read_is_test_only() -> None:
    """E6's seam (``/session-account`` on the signed-in lane's loopback
    stub). Red when: the app itself answers ``/session-account`` with
    anything but 404, or a file under ``src/`` names it. Partners: a real
    session route answers without a cookie with its own 401, and the
    launcher compares the request path with the string."""
    import ast

    from fastapi.testclient import TestClient

    from product_app.main import app

    client = TestClient(app)
    assert client.get("/v1/session/idle").status_code == 401
    for method in ("GET", "POST"):
        assert (
            client.request(method, "/session-account", json={"session_id": "x"}).status_code == 404
        )
    hits = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "src").rglob("*")
        if path.is_file() and "session-account" in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert hits == []
    launcher = (ROOT / "e2e" / "servers" / "signed_in_server.py").read_text(encoding="utf-8")
    compared = {
        side.value
        for node in ast.walk(ast.parse(launcher))
        if isinstance(node, ast.Compare)
        for side in [node.left, *node.comparators]
        if isinstance(side, ast.Constant) and isinstance(side.value, str)
    }
    assert "/session-account" in compared
