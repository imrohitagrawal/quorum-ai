"""JavaScript URLs in markdown links must not become anchors.

Provider text reaches ``el.innerHTML`` through ``setProse`` /
``setInlineProse``. A markdown link ``[text](url)`` becomes an ``<a href>``, so
a destination like ``javascript:`` would execute on click. The defence is a URL
scheme allow-list: only ``http``, ``https``, ``mailto`` and genuinely
schemeless (relative) URLs become anchors; everything else renders as inert
text.

WHAT CHANGED IN ADR-0014, AND WHY THIS FILE WAS REWRITTEN
---------------------------------------------------------
The hand-rolled ``mdInline`` is gone. It built the anchor itself, so this file
pinned the exact expressions it used:

    assert "safeMarkdownHref(decodeBasicEntities(url))" in text
    assert "return `${text} (${url})`" in text

Both describe code that no longer exists — vendored ``markdown-it`` owns link
parsing now, decodes entity references in a destination itself, and emits the
literal source text when a destination is rejected. Those two assertions are
replaced below by assertions on the NEW wiring. **The allow-list itself did not
change**: ``safeMarkdownHref`` and ``safeHttpUrl`` are the same functions, still
shared with the source chips, and every other assertion in this file is
unchanged and still passes.

ONE GUARANTEE CHANGED MECHANISM AND WAS RE-MEASURED
----------------------------------------------------
The old code stripped every C0 control character from a destination BEFORE
testing its scheme, because a browser strips tab/CR/LF before resolving one —
without that, ``java\\tscript:`` smuggles a scheme past a naive check.
``markdown-it`` defends differently: it PERCENT-ENCODES them. Whether that is
equivalent is a claim about the browser, not about the parser, so it was
settled by asking a real browser rather than by reasoning. Measured 2026-08-05
in Chromium, on the live page:

    href="java%09script:alert(1)"  -> a.protocol "http:"
    href="%6aavascript:alert(1)"   -> a.protocol "http:"
    href="/%5Cevil.example/x"      -> a.protocol "http:"

``%`` is not a legal scheme character, so each resolves as a same-origin path.
That measurement is now a permanent gate — ``markdown-corpus.spec.ts``,
"obfuscated link schemes resolve to http, never javascript" — and it is a
stronger proof than anything in this file, because it reads the browser's own
resolution rather than the source.

This file remains the cheap source-level companion: the e2e lane cannot run in
the unit lane, and a source check cannot see runtime behaviour. Neither
replaces the other.
"""

from __future__ import annotations

import pathlib

from fastapi.testclient import TestClient

from product_app.main import _render_workspace_html, app

APP_JS = pathlib.Path(__file__).resolve().parents[2] / "src/product_app/static/app.js"


def test_javascript_url_not_rendered_as_anchor() -> None:
    """A direct check that the URL allow-list is still WIRED UP.

    RED IF: the parser's own ``validateLink`` is left in place (it permits some
    ``data:`` URLs and has no opinion on protocol-relative ``//host``), or the
    ``link_open`` renderer stops re-vetting and attribute-escaping the href.
    """
    # Touch the import so the renderer module is loaded for side-effects.
    assert _render_workspace_html is not None
    text = APP_JS.read_text(encoding="utf-8")

    # The allow-list helper itself — unchanged by ADR-0014.
    assert "function safeMarkdownHref" in text, "safeMarkdownHref helper missing"

    # ...which the parser's link validation now delegates to, INSTEAD of
    # markdown-it's own `validateLink`. This assertion replaces the old
    # `safeMarkdownHref(decodeBasicEntities(url))`: same helper, new caller.
    assert "md.validateLink = (url) => safeMarkdownHref(url) != null;" in text, (
        "markdown-it's own validateLink is still in charge; it permits some "
        "data: URLs and has no opinion on protocol-relative //host"
    )
    # ...and the renderer re-vets the href it is about to emit, rather than
    # trusting that validateLink and the emitter agree about it.
    assert "md.renderer.rules.link_open" in text, "the link_open renderer rule is missing"
    assert 'const href = safeMarkdownHref(tokens[idx].attrGet("href") || "");' in text, (
        "link_open must re-vet the href through the allow-list before emitting it"
    )

    # ...which reuses the URL()-based http(s) allow-list (not a raw-string regex,
    # so control-char scheme smuggling like `java\\tscript:` cannot pass)...
    assert "const http = safeHttpUrl(url);" in text, "safeHttpUrl allow-list not reused"
    # ...strips the full C0-control + DEL set the browser strips before scheme
    # resolution (closes the leading-\\x01 / interior-TAB bypass)...
    assert "/[\\u0000-\\u001F\\u007F]/g" in text, "control-char normalisation missing"
    # ...and attribute-escapes the vetted href so a quote can't break out.
    assert 'href="${escapeHtml(href)}"' in text, "href is not attribute-escaped"

    # A rejected destination must produce NO anchor. markdown-it emits the
    # literal source text in that case, so there is no repo-side fallback
    # expression left to assert; what matters is that the emitter refuses to
    # build an anchor whose href it could not vet.
    assert "if (href == null) return " in text, (
        "link_open must refuse to emit an href it could not vet"
    )
    # Reverse tabnabbing: a target=_blank anchor without this pair is a real
    # vulnerability, and the old renderer set both.
    assert 'rel="noopener noreferrer"' in text, "target=_blank anchors lost their rel pair"


def test_raw_html_is_disabled_in_the_parser() -> None:
    """The other half of the same posture, and the newer half.

    The old renderer escaped every character and re-emitted an allow-list, so
    raw HTML in provider text could not survive by construction. The vendored
    parser escapes it by CONFIGURATION instead, which means one flag now stands
    between a hostile answer and script execution.

    RED IF: ``html`` is flipped to ``true``, or dropped so the parser's own
    default is used. The behavioural proof — a live ``<script>`` driven through
    a provider answer, DOM read in a browser — is in
    ``e2e/tests/invariants/markdown-corpus.spec.ts``; this is the cheap
    companion that runs in the unit lane.
    """
    text = APP_JS.read_text(encoding="utf-8")
    assert "html: false" in text, "the parser is no longer configured with html: false"
    assert "html: true" not in text, "a markdown-it instance is configured with html: true"


def test_workspace_html_loads_with_security_headers() -> None:
    """Sanity check: the workspace page loads and ships the security
    headers configured by the C3 middleware.
    """
    client = TestClient(app)
    response = client.get("/ui")
    assert response.status_code == 200
    assert "nosniff" in response.headers.get("x-content-type-options", "")
    assert "DENY" in response.headers.get("x-frame-options", "")


def test_the_vendored_parser_is_served_before_the_app_script() -> None:
    """Load ORDER is a correctness requirement, not a style choice.

    ``app.js`` reads ``window.markdownit`` when it first renders provider text.
    Both tags are ``defer``, which preserves document order — but only if the
    order is right. Were the parser tag moved after ``app.js``, the renderer
    would fall back to escaped plain text: degraded and still safe, but silently
    wrong, and no other test would notice.

    RED IF: the tags are reordered, or the parser tag is dropped.
    """
    client = TestClient(app)
    body = client.get("/ui").text
    parser = body.find("/static/vendor/markdown-it.min.js")
    app_js = body.find("/static/app.js")
    assert parser != -1, "the vendored parser is not referenced by the workspace page"
    assert app_js != -1, "app.js is not referenced by the workspace page"
    assert parser < app_js, (
        "the vendored parser must load BEFORE app.js; both are `defer`, which "
        "preserves document order"
    )
    # Same-origin, so the strict CSP (`script-src 'self'`) needs no change.
    assert "cdn.jsdelivr.net/npm/markdown-it" not in body, (
        "the workspace page points at a CDN copy of the parser, which the CSP blocks"
    )
