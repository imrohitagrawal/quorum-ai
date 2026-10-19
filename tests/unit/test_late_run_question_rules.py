"""W87-2 (ADR-0175): the page's rules for the late-run question and the
delete deadline, run under Node from the served ``app.js``.

The functions are lifted out of ``app.js`` by brace count, as
``tests/unit/test_account_delete_message.py`` does, so this measures the
served source. The interface (the plan, 2026-10-20, with its "Final save
rule"):

* ``lateRunQuestionEntry({accountId, anonymous, pageIdentityChanged,
  question, nowMs})``: what the save writes, or ``null`` for nothing. A save
  happens only when this page load's identity never changed and the current
  identity is known: an account gives ``{account, question}``, a positive
  ``anonymous: true`` gives ``{anonymous: true, saved_at, question}``.
* ``lateRunQuestionToRestore(saved, {accountId, signedIn, nowMs})``:
  ``{question, notice}``, where ``saved`` is the raw string the tab's
  sessionStorage held (``null`` when none). An anonymous entry is put back
  for whichever session the tab has, within 900 000 ms of ``saved_at``; a
  signed-in entry only for the same account, and for another signed-in
  account it gives the notice instead.
* ``initSession`` records ``state.pageIdentity`` (the account id, or
  ``"anonymous"``) from the FIRST bootstrap of the page load and sets
  ``state.pageIdentityChanged`` when a later one (``retrySession``) names a
  different or an unknown identity; ``signInAgainKeepingQuestion`` is the ONE
  save function both late-run card buttons call.
* ``recentSignInFresh(secondsLeft, loadedAtMs, nowMs)``: the page's own
  deletion deadline, ``loadedAtMs + secondsLeft * 1000``, inclusive.
* ``accountDeleteMessage`` answers ``RECENT_SIGN_IN_REQUIRED`` with the
  CHG-063 (f)(1) sentence.

Each extracted function runs inside a scope where a name the harness does not
provide resolves to a no-op function, and any one-line ALL-CAPS ``const`` the
function names is lifted with it, so a helper or a constant the builder adds
does not break the harness (memory: JS harnesses extract one function).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

APP_JS = Path(__file__).resolve().parents[2] / "src" / "product_app" / "static" / "app.js"
KEY = "quorum.lateRunQuestion"

#: CHG-063 (f)(1), verbatim.
RECENT_SIGN_IN_TEXT = (
    "For your safety, sign in with Google again before deleting your account. "
    "If you are still signed in to Google it takes one click."
)


@pytest.fixture(autouse=True)
def _needs_node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")


def _function(source: str, name: str) -> str:
    """The text of ``function name(...) {...}``, with a leading ``async``."""
    match = re.search(r"(async\s+)?function " + re.escape(name) + r"\(", source)
    assert match is not None, f"app.js defines function {name}"
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
    depth = 0
    while True:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1


def _constants(source: str, functions: list[str], provided: set[str]) -> str:
    """One-line ``const NAME = ...;`` declarations the functions name."""
    names = sorted(
        {n for text in functions for n in re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", text)} - provided
    )
    lines = []
    for name in names:
        found = re.search(r"^\s*const " + re.escape(name) + r" = [^\n]*;\s*$", source, re.M)
        if found:
            lines.append(found.group(0).strip())
    return "\n".join(lines)


#: The scope every extracted function runs in. ``fetch`` answers from
#: ``answers`` in order; sessionStorage is a plain map; ``startGoogleSignIn``
#: only counts. Any other name not on ``globalThis`` (and not the harness's
#: own ``__`` names) is a no-op function.
_PRELUDE = r"""
const __answers = __ANSWERS__;
const __store = {};
const __calls = { start: 0, fetch: 0 };
const __stubs = {
  state: { csrfToken: "", sessionAccountId: "" },
  STATUS_COPY: {},
  ApiError: class ApiError extends Error {
    constructor(o) { super((o && o.message) || ""); Object.assign(this, o || {}); }
  },
  fetch: async function () {
    __calls.fetch += 1;
    const body = __answers.shift();
    return { ok: true, status: 200, json: async () => body };
  },
  el: function () { return { textContent: "", dataset: {}, hidden: false, focus() {} }; },
  window: {
    sessionStorage: {
      setItem(k, v) { __store[k] = String(v); },
      getItem(k) { return Object.prototype.hasOwnProperty.call(__store, k) ? __store[k] : null; },
      removeItem(k) { delete __store[k]; },
    },
    location: { assign() {}, reload() {} },
  },
  queryTextarea: { value: __QUESTION__, dispatchEvent() {} },
  startGoogleSignIn: async function () { __calls.start += 1; },
  signInStartMessage: function (e) { return String(e); },
  LATE_RUN_QUESTION_KEY: "quorum.lateRunQuestion",
};
const __scope = new Proxy(__stubs, {
  has(target, key) {
    if (typeof key !== "string" || key.startsWith("__")) return false;
    return key in target || !(key in globalThis);
  },
  get(target, key) {
    if (key === Symbol.unscopables) return undefined;
    if (key in target) return target[key];
    return function () {};
  },
  set(target, key, value) { target[key] = value; return true; },
});
"""

_PROVIDED = {"STATUS_COPY", "LATE_RUN_QUESTION_KEY"}


def _node(functions: list[str], body: str, *, answers: list[Any] | None = None) -> Any:
    source = APP_JS.read_text(encoding="utf-8")
    texts = [_function(source, name) for name in functions]
    prelude = _PRELUDE.replace("__ANSWERS__", json.dumps(answers or [])).replace(
        "__QUESTION__", json.dumps("the draft question")
    )
    script = (
        prelude
        + "with (__scope) {\n"
        + _constants(source, texts, _PROVIDED)
        + "\n"
        + "\n".join(texts)
        + "\n(async () => {\n"
        + body
        + "\n})().then((out) => console.log(JSON.stringify(out)), (e) => {"
        + " console.log(JSON.stringify({ __error: String(e && e.stack || e) })); });\n}\n"
    )
    out = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=30, check=False
    )
    assert out.returncode == 0, out.stderr
    decoded = json.loads(out.stdout.strip().splitlines()[-1])
    assert not (isinstance(decoded, dict) and "__error" in decoded), decoded
    return decoded


# --- 16a. what the save writes ------------------------------------------------------


def _entry(**given: Any) -> Any:
    args = {"question": "q", "nowMs": 1000, **given}
    return _node(["lateRunQuestionEntry"], f"return lateRunQuestionEntry({json.dumps(args)});")


def test_an_account_identity_saves_an_account_entry() -> None:
    """Red when: a signed-in save loses its account, or gains an anonymous
    marker."""
    got = _entry(accountId="B", anonymous=False, pageIdentityChanged=False)
    assert got == {"account": "B", "question": "q"}


def test_a_positive_anonymous_identity_saves_an_anonymous_entry() -> None:
    """Red when: the anonymous case saves nothing (the owner's answer 3 keeps
    the question), or loses its marker or the time it was saved."""
    got = _entry(accountId="", anonymous=True, pageIdentityChanged=False, nowMs=123456)
    assert got == {"anonymous": True, "saved_at": 123456, "question": "q"}


def test_a_missing_account_is_never_read_as_anonymous() -> None:
    """Codex's defect. Red when: a bootstrap with neither an account nor
    ``anonymous: true`` saves an anonymous entry (or any entry). Partner: the
    positive anonymous case above does save."""
    assert _entry(accountId="", anonymous=False, pageIdentityChanged=False) is None


@pytest.mark.parametrize(
    "identity", [{"accountId": "C", "anonymous": False}, {"accountId": "", "anonymous": True}]
)
def test_after_an_identity_change_nothing_is_saved(identity: dict[str, Any]) -> None:
    """Final save rule. Red when: a page load whose identity changed still
    saves (B's draft would be labelled C's, or anonymous). Partners: the same
    identities save when nothing changed (the two tests above)."""
    assert _entry(pageIdentityChanged=True, **identity) is None


# --- 16. what is put back --------------------------------------------------------------


def _restore(saved: Any, **given: Any) -> Any:
    raw = json.dumps(saved) if isinstance(saved, dict) else saved
    args = {"accountId": "", "signedIn": False, "nowMs": 0, **given}
    return _node(
        ["lateRunQuestionToRestore"],
        f"return lateRunQuestionToRestore({json.dumps(raw)}, {json.dumps(args)});",
    )


ANONYMOUS_ENTRY = {"anonymous": True, "saved_at": 0, "question": "typed anonymously"}
SIGNED_IN_ENTRY = {"account": "A", "question": "typed as A"}


def test_an_anonymous_entry_is_put_back_up_to_900_000_ms_and_not_after() -> None:
    """Red when: the age bound is dropped, moves (literals both sides:
    900 000 ms restored, 900 001 ms not), or a signed-in arrival does not get
    an anonymous question back."""
    at = _restore(ANONYMOUS_ENTRY, accountId="A", signedIn=True, nowMs=900_000)
    late = _restore(ANONYMOUS_ENTRY, accountId="A", signedIn=True, nowMs=900_001)
    assert at == {"question": "typed anonymously", "notice": False}
    assert late == {"question": "", "notice": False}


def test_an_anonymous_entry_is_put_back_for_an_anonymous_session_too() -> None:
    """A cancel at Google leaves the tab anonymous. Red when: the question is
    then lost."""
    got = _restore(ANONYMOUS_ENTRY, accountId="", signedIn=False, nowMs=1000)
    assert got == {"question": "typed anonymously", "notice": False}


def test_an_anonymous_entry_without_a_saved_time_is_not_put_back() -> None:
    """Red when: an entry whose age cannot be known is put back (the 900 s
    bound would not hold). Partner: with a time it is put back (above)."""
    entry = {"anonymous": True, "question": "typed anonymously"}
    assert _restore(entry, accountId="A", signedIn=True, nowMs=1000) == {
        "question": "",
        "notice": False,
    }


def test_a_signed_in_entry_is_put_back_only_for_its_own_account() -> None:
    """Red when: the same account loses its question, or another account gets
    it, or another account is not told (owner answer 5)."""
    same = _restore(SIGNED_IN_ENTRY, accountId="A", signedIn=True, nowMs=10**12)
    other = _restore(SIGNED_IN_ENTRY, accountId="B", signedIn=True, nowMs=1000)
    assert same == {"question": "typed as A", "notice": False}
    assert other == {"question": "", "notice": True}


@pytest.mark.parametrize("saved", [SIGNED_IN_ENTRY, None, "{not json"])
def test_nothing_to_match_puts_nothing_back_and_shows_no_notice(saved: Any) -> None:
    """Red when: a signed-in entry meets a bootstrap with neither field (no
    account to name) and shows the notice or the question, or nothing saved
    (or a broken entry) puts anything back. Partner: the matching account
    gets it back (above)."""
    assert _restore(saved, accountId="", signedIn=False, nowMs=1000) == {
        "question": "",
        "notice": False,
    }


# --- 16b. the identity transition, through the real initSession -------------------------


def _bootstrap(identity: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {"csrf_token": "t", "expires_at": "2026-10-20T00:00:00+00:00"}
    if identity == "anonymous":
        body["anonymous"] = True
    elif identity is not None:
        body["account_id"] = identity
    return body


def _page_load(*identities: str | None) -> Any:
    """``initSession`` once per bootstrap (the first, then each retry), then
    the late-run card's save; what sessionStorage holds and the page state."""
    body = (
        "for (let i = 0; i < __ANSWER_COUNT__; i += 1) { await initSession(); }\n"
        "await signInAgainKeepingQuestion();\n"
        "return { saved: window.sessionStorage.getItem(LATE_RUN_QUESTION_KEY),"
        " pageIdentity: state.pageIdentity === undefined ? null : state.pageIdentity,"
        " changed: state.pageIdentityChanged === true, starts: __calls.start,"
        " fetches: __calls.fetch };"
    ).replace("__ANSWER_COUNT__", str(len(identities)))
    return _node(
        ["initSession", "lateRunQuestionEntry", "signInAgainKeepingQuestion"],
        body,
        answers=[_bootstrap(i) for i in identities],
    )


def test_the_same_account_at_every_bootstrap_saves_its_entry() -> None:
    """Red when: a retry that brings back the SAME account stops the save, or
    the first identity is not recorded. Partner of the change cases below."""
    got = _page_load("B", "B")
    assert got["fetches"] == 2 and got["starts"] == 1
    assert got["pageIdentity"] == "B"
    assert got["changed"] is False
    assert json.loads(got["saved"]) == {"account": "B", "question": "the draft question"}


def test_a_retry_that_brings_another_account_saves_nothing() -> None:
    """Codex re-check 4 (red on W87-1's code too, which saves it as C's).
    Red when: the change check is removed. Partner: the sign-in still
    started."""
    got = _page_load("B", "C")
    assert got["fetches"] == 2 and got["starts"] == 1
    assert got["changed"] is True
    assert got["saved"] is None


def test_a_retry_that_turns_anonymous_saves_nothing() -> None:
    """Codex re-check 3. Red when: a draft typed while signed in as B is
    saved as anonymous after a retry answers ``anonymous: true``."""
    got = _page_load("B", "anonymous")
    assert got["starts"] == 1
    assert got["changed"] is True
    assert got["saved"] is None


def test_anonymous_at_every_bootstrap_saves_the_anonymous_entry() -> None:
    """Owner answer (3). Red when: an anonymous page load saves nothing, or
    loses the marker or the time. Partner of the case above."""
    got = _page_load("anonymous", "anonymous")
    assert got["pageIdentity"] == "anonymous"
    assert got["changed"] is False
    saved = json.loads(got["saved"])
    assert saved["anonymous"] is True
    assert saved["question"] == "the draft question"
    assert isinstance(saved["saved_at"], int | float) and saved["saved_at"] > 0
    assert "account" not in saved


def test_an_unknown_first_bootstrap_saves_nothing() -> None:
    """Red when: a bootstrap with neither field leads to any save. Partner:
    the sign-in still started."""
    got = _page_load(None)
    assert got["starts"] == 1
    assert got["saved"] is None


# --- 17. the page's own deletion deadline ------------------------------------------------


def test_the_delete_deadline_is_fresh_at_its_boundary_and_stale_1_ms_after() -> None:
    """Red when: the comparison is strict (stale at the boundary), the
    seconds are not turned into milliseconds, or 1 ms past the deadline is
    still fresh."""
    got = _node(
        ["recentSignInFresh"],
        "return [recentSignInFresh(600, 1000, 601000), recentSignInFresh(600, 1000, 601001),"
        " recentSignInFresh(0, 5000, 5001), recentSignInFresh(42, 0, 42000)];",
    )
    assert got == [True, False, False, True]


def test_the_delete_page_answers_a_recent_sign_in_refusal_with_its_own_sentence() -> None:
    """Red when: a 403 ``RECENT_SIGN_IN_REQUIRED`` gets the "Reload the page"
    line (untrue: reloading does not help). Partner: an unknown code still
    gets the reload line."""
    got = _node(
        ["accountDeleteMessage"],
        'return [accountDeleteMessage({ code: "RECENT_SIGN_IN_REQUIRED", status: 403 }),'
        ' accountDeleteMessage({ code: "SOMETHING_ELSE", status: 403 })];',
    )
    assert got == [RECENT_SIGN_IN_TEXT, "Your session changed. Reload the page, then try again."]
