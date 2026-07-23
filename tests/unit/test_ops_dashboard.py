"""OD-2: the ops dashboard page (`/ui/ops`) — RED-first contract.

The page is a self-contained, same-origin operations dashboard: it fetches
`/metrics`, `/status` and `/ready` client-side and renders SLO tiles. The
tests pin the properties the stage spec demands:

* the route serves HTML and references only same-origin assets (strict CSP —
  no external hosts anywhere in the page or its JS/CSS);
* every "current" value is computed client-side from live responses — the
  page source must not contain a hardcoded metric value;
* the route stays out of the OpenAPI schema (like `/metrics`), so the
  byte-faithful ``openapi.yaml`` drift guard is untouched;
* the sparkline is honest: values accumulate only since page open and the
  page says so.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from product_app.main import app

STATIC_DIR = Path(__file__).resolve().parents[2] / "src" / "product_app" / "static"
TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "src" / "product_app" / "templates"


def test_ops_page_serves_html() -> None:
    client = TestClient(app)
    response = client.get("/ui/ops")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Ops" in response.text


# Hosts the page is allowed to reference — keyed by EXACT host, never a
# whole-string substring (AGENTS.md: "Never gate a secret/threat check on
# whole-line substrings; key off the matched token or value"). The first two
# are the workspace's Google Fonts pair (already in the app-wide CSP
# style-src/font-src); the third is the product's OWN production origin quoted
# in the how-to-read ``curl`` example — inline text, not a fetched asset.
_ALLOWED_HOSTS = frozenset(
    {
        "fonts.googleapis.com",
        "fonts.gstatic.com",
        "quorum.stackclimb.com",
        "www.w3.org",  # the SVG XML namespace identifier — not a network ref
    }
)

# Any absolute (``scheme://authority``) or protocol-relative (``//authority``)
# URL. Case in the scheme is ignored so ``HTTPS://`` cannot slip past. The
# whole authority is captured up to the first ``/ ? # " ' <`` or whitespace;
# ``_host_of`` then extracts the REAL host, so a userinfo trick
# (``fonts.googleapis.com@evil.com``) or a subdomain trick
# (``fonts.googleapis.com.evil.com``) exposes ``evil.com`` and fails equality.
_URL_RE = re.compile(r"""(?i)(?:https?:)?//([^/?#"'\s<>]*)""")


def _host_of(authority: str) -> str:
    """Reduce a URL authority to its bare host (drop userinfo and port)."""
    host = authority.rsplit("@", 1)[-1]  # userinfo before the last @ is not the host
    host = host.split(":", 1)[0]  # strip :port
    return host.lower()


def _external_hosts(text: str) -> set[str]:
    """Return every referenced host that is not in the allowlist."""
    hosts = {_host_of(a) for a in _URL_RE.findall(text) if a}
    return {h for h in hosts if h and h not in _ALLOWED_HOSTS}


def test_ops_page_references_only_same_origin_assets() -> None:
    """CSP-clean: every referenced host must be same-origin or explicitly allowed.

    Design-synchrony change: the ops page loads the same Google Fonts
    stylesheet the workspace loads (already allowed by the app-wide CSP
    ``style-src``/``font-src``).  The guard keys off the parsed HOST of each
    URL, so a look-alike host that merely *contains* an allowed string
    (``fonts.googleapis.com.evil.com``, ``…@evil.com``) is caught — proven
    both directions by ``test_same_origin_guard_bites_on_lookalike_hosts``.
    """
    client = TestClient(app)
    html = client.get("/ui/ops").text
    js = (STATIC_DIR / "ops.js").read_text()
    css = (STATIC_DIR / "ops.css").read_text()
    tokens = (STATIC_DIR / "tokens.css").read_text()
    for name, text in (
        ("html", html),
        ("ops.js", js),
        ("ops.css", css),
        ("tokens.css", tokens),
    ):
        assert _external_hosts(text) == set(), f"external host referenced in {name}"


def test_same_origin_guard_bites_on_lookalike_hosts() -> None:
    """Both directions: the allowlist keys on exact host, not a substring.

    Every one of these evasions kept a valid ``https://`` off the stripped
    string under the old ``str.replace`` guard; the host-keyed guard catches
    them all.
    """
    # Legitimate references produce no external host.
    assert _external_hosts('href="https://fonts.googleapis.com/css2?x"') == set()
    assert _external_hosts('src="https://fonts.gstatic.com/font.woff2"') == set()
    assert _external_hosts("curl -s https://quorum.stackclimb.com/metrics") == set()
    assert _external_hosts('xmlns="http://www.w3.org/2000/svg"') == set()
    # Every look-alike / trick host is flagged with its REAL host.
    for evil in (
        '<link href="https://fonts.googleapis.com.evil.com/x.css">',
        '<script src="https://fonts.gstatic.com.attacker.net/x.js"></script>',
        '<a href="https://fonts.googleapis.com@evil.com/">',
        '<script src="//evil.com/x.js"></script>',  # protocol-relative
        '<script src="HTTPS://evil.com/x.js"></script>',  # mixed case
        '<img src="https://evil.cdn.example/x.png">',
    ):
        assert _external_hosts(evil), f"guard missed external host in: {evil}"


def test_ops_page_fetches_the_three_live_surfaces() -> None:
    js = (STATIC_DIR / "ops.js").read_text()
    for surface in ("/metrics", "/status", "/ready"):
        assert f'"{surface}"' in js, f"ops.js must fetch {surface}"


def test_ops_page_not_in_openapi_schema() -> None:
    assert "/ui/ops" not in app.openapi()["paths"]


def test_ops_js_has_no_hardcoded_current_values() -> None:
    """No literal percentage/latency value may be baked into the page.

    SLO *targets* are allowed (they are declared, and rendered as
    ``SLO: target``); a hardcoded *current* value would fabricate a
    measurement.  The guard: the JS must never assign a numeric literal
    into a tile's current-value slot — currents flow only through the
    ``render*``/``fmt*`` helpers fed by fetched data.
    """
    js = (STATIC_DIR / "ops.js").read_text()
    assert re.search(r'currentEl\.textContent\s*=\s*["\']\d', js) is None
    assert "data-current" in js  # tiles get their current values injected


def test_ops_page_labels_sparkline_as_since_page_open() -> None:
    html = (TEMPLATES_DIR / "ops.html").read_text()
    assert "since page open" in html.lower()


def test_ops_page_uses_textcontent_never_innerhtml() -> None:
    """Fetched metric text must never be injected via innerHTML."""
    js = (STATIC_DIR / "ops.js").read_text()
    assert "innerHTML" not in js


# --- Design-token synchrony (shared tokens.css) ----------------------------


def test_design_tokens_extracted_to_shared_stylesheet() -> None:
    """The workspace token block lives in tokens.css, shared by both pages.

    Pure-move guard: the primitive palette must exist in ``tokens.css`` and
    must NOT be re-declared in ``app.css`` or ``ops.css`` — one source of
    truth, no drift (the ``--c-muted`` WCAG correction must never fork).
    """
    tokens = (STATIC_DIR / "tokens.css").read_text()
    app_css = (STATIC_DIR / "app.css").read_text()
    ops_css = (STATIC_DIR / "ops.css").read_text()
    for primitive in ("--c-paper:", "--c-ink:", "--c-green:", "--font-sans:"):
        assert primitive in tokens, f"{primitive} missing from tokens.css"
        assert primitive not in app_css, f"{primitive} re-declared in app.css"
        assert primitive not in ops_css, f"{primitive} re-declared in ops.css"
    # Dark-theme token block moves too (both pages inherit it).
    assert 'html[data-theme="dark"]' in tokens


def test_both_templates_link_shared_tokens_before_page_styles() -> None:
    for template, page_css in (("workspace.html", "app.css"), ("ops.html", "ops.css")):
        html = (TEMPLATES_DIR / template).read_text()
        assert "/static/tokens.css" in html, f"{template} must link tokens.css"
        assert html.index("/static/tokens.css") < html.index(f"/static/{page_css}"), (
            f"{template}: tokens.css must load before {page_css}"
        )


def test_ops_css_is_built_on_the_shared_tokens() -> None:
    """ops.css consumes semantic tokens instead of its own palette."""
    ops_css = (STATIC_DIR / "ops.css").read_text()
    for token in ("var(--surface)", "var(--line", "var(--font-sans)", "var(--font-mono)"):
        assert token in ops_css, f"ops.css must use {token}"
    # The old standalone palette block is gone.
    assert ":root" not in ops_css


# --- Metrics-explained sections (OD follow-up: human-facing /metrics) ------


def test_ops_page_has_the_four_explainer_sections() -> None:
    html = (TEMPLATES_DIR / "ops.html").read_text()
    for section_id in (
        "explainer-about",
        "explainer-catalog",
        "explainer-howto",
        "explainer-slo",
    ):
        assert f'id="{section_id}"' in html, f"missing section {section_id}"


def test_explainer_about_states_purpose_and_exposure() -> None:
    html = (TEMPLATES_DIR / "ops.html").read_text().lower()
    assert "prometheus" in html
    # The deliberate public-unauthenticated exposure must be stated on-page.
    assert "public" in html and "unauthenticated" in html


def test_explainer_catalog_counts_are_computed_not_hardcoded() -> None:
    """The family count is a live value: a DOM slot fed by fetched data.

    Hardcoding today's count (20) would fabricate a measurement the moment
    a family is added or removed.
    """
    html = (TEMPLATES_DIR / "ops.html").read_text()
    js = (STATIC_DIR / "ops.js").read_text()
    assert 'data-current="family-count"' in html
    assert '"family-count"' in js  # fed via setCurrent(...) from parsed data
    assert "# HELP" in js or '"# TYPE"' in js  # parsed from the exposition
    # No literal family count baked into the page near the slot.
    assert re.search(r'family-count"[^>]*>\s*\d', html) is None


def test_explainer_catalog_has_the_three_group_containers() -> None:
    html = (TEMPLATES_DIR / "ops.html").read_text()
    for group in ("http", "process", "python"):
        assert f'data-group="{group}"' in html, f"missing catalog group {group}"


def test_explainer_howto_shows_shell_read_path_and_p95_caveat() -> None:
    html = (TEMPLATES_DIR / "ops.html").read_text()
    assert "curl" in html
    assert "bucket" in html.lower()  # bucket-derived p95 caveat centralised


def test_explainer_slo_names_source_of_truth_doc() -> None:
    """The SLO section must point at the declared-targets source of truth."""
    html = (TEMPLATES_DIR / "ops.html").read_text()
    assert "docs/80-observability.md" in html


# --- Per-tile relevance copy (why-it-matters / when-red follow-up) ----------
#
# Every SLO tile must be self-explanatory to someone who has never seen
# Prometheus: a "why this matters" line on all six tiles, and a "when it's
# red" first-action hint where a red state exists. Keyed off stable data-*
# hooks (data-why / data-red), never brittle prose.

_ALL_TILE_KEYS = ("rate", "p95", "err", "ready", "uptime", "version")
_RED_HINT_KEYS = ("rate", "p95", "err", "ready")


def test_every_tile_carries_why_it_matters_copy() -> None:
    html = (TEMPLATES_DIR / "ops.html").read_text()
    for key in _ALL_TILE_KEYS:
        assert f'data-why="{key}"' in html, f"tile {key} missing data-why copy"


def test_red_hint_present_exactly_where_a_red_state_exists() -> None:
    """Uptime and version have no red state — an invented hint would lie."""
    html = (TEMPLATES_DIR / "ops.html").read_text()
    for key in _RED_HINT_KEYS:
        assert f'data-red="{key}"' in html, f"tile {key} missing data-red hint"
    for key in ("uptime", "version"):
        assert f'data-red="{key}"' not in html, f"tile {key} must not fake a red state"


def test_relevance_copy_is_static_explanation_not_a_value_sink() -> None:
    """The copy explains; the values keep flowing through data-current only.

    ops.js must never write into a relevance slot, and no relevance paragraph
    may embed a live-value slot — explanation and measurement stay separate,
    so a hardcoded number can never masquerade as a current value.
    """
    js = (STATIC_DIR / "ops.js").read_text()
    assert "data-why" not in js and "data-red" not in js
    html = (TEMPLATES_DIR / "ops.html").read_text()
    # Match the WHOLE element (group 0), not just the body: a data-current
    # attribute on the relevance <p> tag itself must fail too — ops.js's
    # querySelector takes the first document-order match, so such a
    # regression would silently reroute a live value into the copy.
    paras = [
        m.group(0)
        for m in re.finditer(r'<p[^>]*data-(?:why|red)="[^"]+"[^>]*>(.*?)</p>', html, re.S)
    ]
    assert len(paras) == len(_ALL_TILE_KEYS) + len(_RED_HINT_KEYS)
    for element in paras:
        assert element.count("data-") == 1  # exactly the data-why/data-red hook
        assert "data-current" not in element


def test_err_red_hint_names_request_id_and_runbook() -> None:
    """The 5xx first action is the real one: logs by request_id, then runbook."""
    html = (TEMPLATES_DIR / "ops.html").read_text()
    match = re.search(r'<p[^>]*data-red="err"[^>]*>(.*?)</p>', html, re.S)
    assert match is not None
    assert "request_id" in match.group(1)
    assert "docs/80-observability.md" in match.group(1)


def test_ready_red_hint_states_simulation_fallback() -> None:
    """Any non-live state must be explained honestly: runs fall back to simulation."""
    html = (TEMPLATES_DIR / "ops.html").read_text()
    match = re.search(r'<p[^>]*data-red="ready"[^>]*>(.*?)</p>', html, re.S)
    assert match is not None
    assert "simulat" in match.group(1).lower()


# --- Jump-bar TOC, "Used by" honesty, glossary, favicon ---------------------
#
# Four additive pieces (one PR): a sticky section TOC with scroll-spy, a
# truthful "Used by" marker per catalog family, a plain-language glossary
# with jargon links from page-authored copy, and a same-origin favicon on
# both product templates.

_TOC_EXPECTED_TARGETS = (
    "live-tiles",
    "explainer-about",
    "explainer-catalog",
    "explainer-howto",
    "explainer-slo",
    "explainer-glossary",
)


def test_ops_page_has_jump_bar_toc_targeting_real_anchors() -> None:
    """Every TOC href must resolve to a real element id on the page."""
    html = (TEMPLATES_DIR / "ops.html").read_text()
    nav = re.search(r'<nav[^>]*class="[^"]*ops-toc[^"]*"[^>]*>(.*?)</nav>', html, re.S)
    assert nav is not None, "missing .ops-toc nav"
    hrefs = re.findall(r'href="#([^"]+)"', nav.group(1))
    assert tuple(hrefs) == _TOC_EXPECTED_TARGETS
    for target in hrefs:
        assert f'id="{target}"' in html, f"TOC target #{target} does not exist"


def test_toc_is_ordered_after_the_skip_link() -> None:
    """Keyboard order: skip-link stays the first focusable thing on the page."""
    html = (TEMPLATES_DIR / "ops.html").read_text()
    assert html.index('class="skip-link"') < html.index("ops-toc")


def test_toc_scroll_spy_uses_intersection_observer_not_scroll_handler() -> None:
    js = (STATIC_DIR / "ops.js").read_text()
    assert "IntersectionObserver" in js
    assert "aria-current" in js
    # No scroll-handler jank: the spy must not hang off a per-frame scroll
    # listener. The ban keys on the exact event name ("scroll",) so the
    # once-per-gesture "scrollend" listener — which cannot jank — stays
    # allowed.
    assert 'addEventListener("scroll",' not in js
    assert "addEventListener('scroll'," not in js


def test_toc_targets_never_hide_under_the_sticky_bar() -> None:
    """scroll-padding-top on the root shields ALL scroll-into-view ops
    (anchor jumps AND keyboard-focus scrolling of id-less elements) from
    the sticky bar; reduced motion honoured. scroll-margin-top on targets
    is forbidden — it would ADD to the padding (double offset)."""
    css = (STATIC_DIR / "ops.css").read_text()
    assert "scroll-padding-top" in css
    assert "scroll-margin-top" not in css
    assert "prefers-reduced-motion" in css


def test_glossary_panel_has_the_eight_entries() -> None:
    html = (TEMPLATES_DIR / "ops.html").read_text()
    assert 'id="explainer-glossary"' in html
    for term_id in (
        "term-gc",
        "term-histogram",
        "term-percentile",
        "term-cardinality",
        "term-rss",
        "term-fd",
        "term-scrape",
        "term-counter-gauge",
    ):
        assert f'id="{term_id}"' in html, f"missing glossary entry {term_id}"


def test_every_jargon_link_targets_an_existing_glossary_entry() -> None:
    """Term links live in page-authored copy and resolve to real entries."""
    html = (TEMPLATES_DIR / "ops.html").read_text()
    term_links = re.findall(r'class="term"[^>]*href="#(term-[^"]+)"', html)
    term_links += re.findall(r'href="#(term-[^"]+)"[^>]*class="term"', html)
    assert term_links, "no jargon links found in page-authored copy"
    for target in term_links:
        assert f'id="{target}"' in html, f"term link #{target} has no glossary entry"


def test_glossary_terms_are_not_injected_into_machine_help_text() -> None:
    """The raw `# HELP` text renders verbatim — ops.js must not linkify it.

    The catalog help cell is machine text; the glossary sits beside it. The
    guard: ops.js never creates anchor elements (all its DOM writes are
    td/tr/polyline/textContent), so parsed provider text can never become a
    link — belt to the existing innerHTML-ban braces.
    """
    js = (STATIC_DIR / "ops.js").read_text()
    assert 'createElement("a")' not in js
    assert "innerHTML" not in js  # restated locally so this test bites alone


_CONSUMED_FAMILIES = ("http_requests_total", "http_request_duration_seconds")


def test_used_by_badges_key_off_the_families_the_page_parses() -> None:
    """Badge truth is keyed off family NAME, defaulting to informational.

    The two families whose samples the tiles actually read (`ops.js
    parseMetrics` reads `http_requests_total{` and
    `http_request_duration_seconds_bucket{`) get a "feeds" marker; every
    other — including unknown/new — family reads "informational".
    """
    js = (STATIC_DIR / "ops.js").read_text()
    for family in _CONSUMED_FAMILIES:
        assert f'"{family}"' in js, f"badge map must key {family}"
    assert "informational" in js  # the default for non-consumed families
    # The map keys must be the same names parseMetrics actually reads.
    assert 'indexOf("http_requests_total{")' in js
    assert 'indexOf("http_request_duration_seconds_bucket{")' in js


def test_catalog_tables_gain_a_used_by_column() -> None:
    html = (TEMPLATES_DIR / "ops.html").read_text()
    assert html.count("Used by") >= 4  # one header cell per group table


def test_catalog_intro_states_slo_source_group_honestly() -> None:
    """One sentence: SLOs come from http_* only; the rest is informational."""
    html = (TEMPLATES_DIR / "ops.html").read_text()
    catalog = re.search(r'id="explainer-catalog".*?<section class="catalog-group"', html, re.S)
    assert catalog is not None
    assert "http_" in catalog.group(0)
    assert "informational" in catalog.group(0).lower()


def test_favicon_linked_in_both_templates_and_served_same_origin() -> None:
    for template in ("ops.html", "workspace.html"):
        html = (TEMPLATES_DIR / template).read_text()
        assert 'rel="icon"' in html, f"{template} missing favicon link"
        assert "/static/favicon.svg" in html, f"{template} favicon not same-origin"
    client = TestClient(app)
    response = client.get("/static/favicon.svg")
    assert response.status_code == 200
    assert "image/svg+xml" in response.headers["content-type"]
    # Same-origin guard applies to the icon too: no external host inside it.
    assert _external_hosts(response.text) == set()
    # The asset must be WELL-FORMED XML, or browsers show a broken icon.
    # (Live-look finding: a ``--token-name`` inside an XML comment is
    # illegal XML — a 200 + right content-type still failed to decode.)
    import xml.etree.ElementTree as ET

    root = ET.fromstring(response.text)
    assert root.tag.endswith("svg")
    # Safari ignores SVG favicons — a PNG fallback must exist and be linked
    # BEFORE the SVG (browsers that support SVG still prefer it; Safari
    # takes the PNG instead of showing a blank globe).
    png = client.get("/static/favicon-32.png")
    assert png.status_code == 200
    assert "image/png" in png.headers["content-type"]
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"
    for template in ("ops.html", "workspace.html"):
        html = (TEMPLATES_DIR / template).read_text()
        assert "/static/favicon-32.png" in html, f"{template} missing PNG fallback"
        assert html.index("favicon-32.png") < html.index("favicon.svg"), (
            f"{template}: PNG fallback must be linked before the SVG icon"
        )
