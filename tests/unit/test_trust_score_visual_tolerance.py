"""W41: the screenshot specs load a SAVED font stylesheet, keep their tolerances,
and keep the trust-score card's exact-text check.

The decision (docs/19-change-control-log.md, CHG-031, which replaces CHG-027 (e)'s
700 px and CHG-030's allowance): the trust-score screenshot flake was caused by
Google Fonts sometimes answering the test browser with a different Geist build
(font URLs of the form ``fonts.gstatic.com/l/font?kit=...``) whose weight-600
letters are slightly wider. The owner chose: pin the stylesheet in the two
screenshot specs, keep ``maxDiffPixels: 120``, keep the exact-text check.
ADR-0149 has the measurements.

Four things must hold, and the tests below pin them:

* T1, tolerances. Every ``toHaveScreenshot(`` call in
  ``trust-score-visual.spec.ts`` passes exactly ``{maxDiffPixels: 120}``; every
  call in ``visual-snapshots.spec.ts`` exactly ``{maxDiffPixelRatio: 0.01}``
  plus the ``mask: masks(page)`` it already had; and ``e2e/playwright.config.ts``
  sets no screenshot option globally.
* T2, the pin is CALLED. Each visual spec imports ``pinGoogleFonts`` from
  ``../../fixtures/pinned-fonts`` and, in every test, runs
  ``await pinGoogleFonts(page);`` as a top-level statement before anything
  loads the page (directly, or first thing in a local helper that loads it).
* T3, the saved stylesheet matches what the app asks for. If the template's font
  link changes, the fixture is stale and these tests stay red until it is
  re-captured.
* T4, the exact-text check cannot be deleted, or moved after the screenshot,
  without a test going red.

HOW THE SPECS ARE READ. As code, not text (AGENTS.md rule 8). The specs explain
their tolerance in comments, so a substring search would be satisfied by prose.
``tests.code_text.code_without_comments`` strips ``//`` and ``/* */`` only for
``.js``/``.mjs``/``.cjs``; for a ``.ts`` path it falls back to ``#``-stripping
and leaves every ``//`` comment in place. So each ``.ts`` file's text is copied
to a ``.js`` file first and read through the public helper.
``test_the_reader_drops_a_ts_comment_decoy`` proves that route really strips.

The 120, the 0.01 and the five card lines are literals written here, not read
back from the file under test (rule 7a).

WHAT THESE TESTS CANNOT SEE. They read source, not a running browser: whether the
route in ``pinned-fonts.ts`` really serves the saved file is proven by the e2e
run, not here. ``mask`` is pinned as the call ``masks(page)``, not as what
``stabilize.ts`` returns. A pin nested in any block (an ``if``, a loop, an
arrow function) is not counted, but an early ``return`` before a top-level pin
is not detected. CLI flags in ``e2e.yml`` (``--update-snapshots``,
``--ignore-snapshots``) are not read.

WHAT TURNS EACH TEST RED is stated on the test.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from tests.code_text import code_without_comments

ROOT = Path(__file__).resolve().parents[2]
E2E = ROOT / "e2e"
INVARIANTS = E2E / "tests" / "invariants"
TRUST_SPEC = INVARIANTS / "trust-score-visual.spec.ts"
OTHER_SPEC = INVARIANTS / "visual-snapshots.spec.ts"
VISUAL_SPECS = (TRUST_SPEC, OTHER_SPEC)
PW_CONFIG = E2E / "playwright.config.ts"
FIXTURES = E2E / "fixtures"
PIN_HELPER = FIXTURES / "pinned-fonts.ts"
FONTS_CSS = FIXTURES / "google-fonts.css"
FONTS_META = FIXTURES / "google-fonts.json"
TEMPLATE = ROOT / "src" / "product_app" / "templates" / "workspace.html"

#: ``toHaveScreenshot`` options that cannot loosen a compare. Every OTHER option
#: (``maxDiffPixels``, ``maxDiffPixelRatio``, ``threshold``, ``mask``,
#: ``maskColor``, ``stylePath``, ``_comparator``, any key not known here, a
#: spread, a shorthand, a computed key) is recorded and must match exactly.
NEUTRAL_OPTIONS = frozenset(
    {"fullPage", "animations", "caret", "scale", "timeout", "clip", "omitBackground"}
)

_CALL = re.compile(r"\.toHaveScreenshot\s*\(")
_OPEN = "([{"
_CLOSE = ")]}"
_QUOTES = "\"'`"


def _code_of(text: str) -> str:
    """*text* with its ``//`` and ``/* */`` comments blanked."""
    with tempfile.TemporaryDirectory() as scratch:
        as_js = Path(scratch) / "spec.js"
        as_js.write_text(text, encoding="utf-8")
        return code_without_comments(as_js)


def _code_of_file(path: Path) -> str:
    return _code_of(path.read_text(encoding="utf-8"))


def _skip_string(code: str, i: int) -> int:
    """Index just past the string literal that opens at ``code[i]``."""
    quote, j = code[i], i + 1
    while j < len(code):
        if code[j] == "\\":
            j += 2
            continue
        if code[j] == quote:
            return j + 1
        j += 1
    raise AssertionError(f"unterminated string literal at offset {i}")


def _is_string_literal(text: str) -> bool:
    return text[:1] in _QUOTES and _skip_string(text, 0) == len(text)


def _split_top_level(code: str, start: int, closer: str) -> tuple[list[str], int]:
    """Split ``code[start:]`` at depth-0 commas until the matching *closer*.

    Returns the stripped pieces and the index just past *closer*.
    """
    pieces: list[str] = []
    depth, piece_start, i = 0, start, start
    while i < len(code):
        c = code[i]
        if c in _QUOTES:
            i = _skip_string(code, i)
            continue
        if c in _OPEN:
            depth += 1
        elif c in _CLOSE:
            if depth == 0:
                if c != closer:
                    raise AssertionError(f"mismatched {c!r} at offset {i}")
                pieces.append(code[piece_start:i].strip())
                return [p for p in pieces if p], i + 1
            depth -= 1
        elif c == "," and depth == 0:
            pieces.append(code[piece_start:i].strip())
            piece_start = i + 1
        i += 1
    raise AssertionError(f"no matching {closer!r} after offset {start}")


def _matching(code: str, open_index: int) -> int:
    """Index of the bracket that closes the one at ``code[open_index]``."""
    closer = _CLOSE[_OPEN.index(code[open_index])]
    _, end = _split_top_level(code, open_index + 1, closer)
    return end - 1


def _depth_at(code: str, index: int) -> int:
    """Bracket depth of ``code[index]``, ignoring brackets inside strings."""
    depth, i = 0, 0
    while i < index:
        c = code[i]
        if c in _QUOTES:
            i = _skip_string(code, i)
            continue
        if c in _OPEN:
            depth += 1
        elif c in _CLOSE:
            depth -= 1
        i += 1
    return depth


def _top_level_colon(prop: str) -> int:
    """Index of the first depth-0 ``:`` outside strings in *prop*, or -1."""
    depth, i = 0, 0
    while i < len(prop):
        c = prop[i]
        if c in _QUOTES:
            i = _skip_string(prop, i)
            continue
        if c in _OPEN:
            depth += 1
        elif c in _CLOSE:
            depth -= 1
        elif c == ":" and depth == 0:
            return i
        i += 1
    return -1


def _object_entries(obj: str) -> dict[str, str]:
    """Every property of the object literal *obj*, key -> value text.

    A spread (``...x``, recorded BEFORE any split at ``:``, since its expression
    may hold one), a shorthand (``threshold``), a computed key (``[k]: 9``) or
    any other non-identifier key is recorded under a ``<...>`` key. Quoted keys
    (``"threshold"``) are unquoted, so they compare like plain ones.
    """
    props, _ = _split_top_level(obj, 1, "}")
    entries: dict[str, str] = {}
    for prop in props:
        if prop.startswith("..."):
            entries[f"<spread {prop}>"] = ""
            continue
        colon = _top_level_colon(prop)
        if colon < 0:
            entries[f"<shorthand or method {prop}>"] = ""
            continue
        key, value = prop[:colon].strip(), prop[colon + 1 :].strip()
        if _is_string_literal(key) and key[0] != "`":
            key = key[1:-1]
        if not re.fullmatch(r"[A-Za-z_$][\w$]*", key):
            key = f"<computed or odd key {key}>"
        entries[key] = value
    return entries


def _screenshot_tolerances(code: str) -> list[dict[str, str]]:
    """For each ``toHaveScreenshot(`` CALL in *code*, its non-neutral options.

    A name argument (a string or template literal) is skipped. An object literal
    is read with :func:`_object_entries`. Any other argument (``opts``, a call)
    is recorded as opaque.
    """
    calls: list[dict[str, str]] = []
    for match in _CALL.finditer(code):
        args, _ = _split_top_level(code, match.end(), ")")
        options: dict[str, str] = {}
        for arg in args:
            if _is_string_literal(arg):
                continue
            if arg.startswith("{") and _matching(arg, 0) == len(arg) - 1:
                options.update(_object_entries(arg))
            else:
                options[f"<non-literal argument {arg}>"] = ""
        calls.append({k: v for k, v in options.items() if k not in NEUTRAL_OPTIONS})
    return calls


# --------------------------------------------------------------------------- T1


def test_the_reader_drops_a_ts_comment_decoy() -> None:
    """RED if ``_code_of`` stops stripping ``//`` or ``/* */`` — e.g. it is
    changed to call ``code_without_comments`` on the ``.ts`` path directly,
    which strips only ``#`` comments. Every test below would then be satisfiable
    by a comment."""
    decoy = (
        "await expect(x).toHaveScreenshot('a.png', {\n"
        "  // maxDiffPixels: 700,\n"
        "  /* maxDiffPixelRatio: 0.5, */\n"
        "  maxDiffPixels: 120,\n"
        "});\n"
    )
    code = _code_of(decoy)
    assert "maxDiffPixels: 120" in code, "POSITIVE PARTNER: live code must survive"
    assert "700" not in code, "a // comment reached the reader"
    assert "0.5" not in code, "a /* */ comment reached the reader"


def test_the_option_reader_records_every_loosening_shape() -> None:
    """RED if the option reader lets any shape round-1 reviewers used read as
    plain ``{maxDiffPixels: 120}``: a spread whose expression holds a colon,
    ``mask``/``maskColor``/``_comparator``/``stylePath``/``threshold``, a quoted
    or computed key, a shorthand, or a non-literal options argument — or if it
    stops unquoting a quoted key, or starts recording ``fullPage`` or the name."""
    baseline = {"maxDiffPixels": "120"}
    shapes = [
        "...(process.env.CI ? { maxDiffPixels: 5000 } : {})",
        "mask: [page.locator('body')]",
        "maskColor: '#000'",
        "_comparator: 'ssim-cie94'",
        "stylePath: 'hide.css'",
        "threshold: 0.9",
        '"threshold": 0.9',
        "'maxDiffPixels': 5000",
        "[key]: 900",
        "threshold",
    ]
    for shape in shapes:
        call = f"await expect(s).toHaveScreenshot('a.png', {{ maxDiffPixels: 120, {shape} }});"
        (options,) = _screenshot_tolerances(_code_of(call))
        assert options != baseline, f"{shape!r} read as no extra option ({options})"
    quoted = _object_entries('{ "threshold": 0.9 }')
    assert quoted == {"threshold": "0.9"}, f"quoted key not unquoted: {quoted}"
    variable = "await expect(s).toHaveScreenshot('a.png', LOOSE);"
    (opaque,) = _screenshot_tolerances(_code_of(variable))
    assert opaque != {}, "a non-literal options argument read as no option"
    plain = (
        "await expect(s).toHaveScreenshot(`t-${w}.png`, { fullPage: true, maxDiffPixels: 120 });"
    )
    (neutral,) = _screenshot_tolerances(_code_of(plain))
    assert neutral == baseline, (
        f"POSITIVE PARTNER: a neutral option or the name was recorded: {neutral}"
    )


def test_every_trust_score_screenshot_allows_exactly_120_pixels() -> None:
    """RED while the spec says ``maxDiffPixels: 700`` (the branch before the
    builder reverts it), for 119 or 121, when 120 appears only in a comment,
    when any other tolerance option (a ratio, a threshold, a mask, a spread, a
    computed or quoted key) is added beside it, and when the ``toHaveScreenshot``
    call is deleted."""
    calls = _screenshot_tolerances(_code_of_file(TRUST_SPEC))
    assert calls, (
        f"POSITIVE PARTNER: no toHaveScreenshot( call found in the code of {TRUST_SPEC.name}; "
        "the tolerance check below would pass over nothing"
    )
    for index, tolerance in enumerate(calls):
        assert tolerance == {"maxDiffPixels": "120"}, (
            f"{TRUST_SPEC.name} toHaveScreenshot call #{index + 1} has tolerance {tolerance}; "
            "CHG-031 keeps exactly {'maxDiffPixels': '120'} and nothing else"
        )


def test_the_other_visual_spec_keeps_its_own_tolerance() -> None:
    """RED if any ``toHaveScreenshot`` call in ``visual-snapshots.spec.ts``
    gains ``maxDiffPixels``, changes its ``maxDiffPixelRatio`` from 0.01, gains
    a ``threshold``, a spread or any other non-neutral option, changes its
    ``mask`` from ``masks(page)``, or if the spec loses every
    ``toHaveScreenshot`` call."""
    calls = _screenshot_tolerances(_code_of_file(OTHER_SPEC))
    assert calls, (
        f"POSITIVE PARTNER: no toHaveScreenshot( call found in the code of {OTHER_SPEC.name}; "
        "the unchanged-tolerance check below would pass over nothing"
    )
    expected = {"mask": "masks(page)", "maxDiffPixelRatio": "0.01"}
    for index, tolerance in enumerate(calls):
        assert tolerance == expected, (
            f"{OTHER_SPEC.name} toHaveScreenshot call #{index + 1} has tolerance {tolerance}; "
            f"W41 changes no tolerance here, so it must stay {expected}"
        )


_GLOBAL_SNAPSHOT_WORD = re.compile(
    r"\b(toHaveScreenshot|toMatchSnapshot|ignoreSnapshots|updateSnapshots)\b"
)
_EXPECT_BLOCK = re.compile(r"\bexpect\s*:\s*\{")


def test_the_playwright_config_sets_no_screenshot_option() -> None:
    """RED if ``e2e/playwright.config.ts``'s code names ``toHaveScreenshot``,
    ``toMatchSnapshot``, ``ignoreSnapshots`` or ``updateSnapshots`` anywhere
    (top-level or per-project, quoted or not), or if any ``expect: {`` block in
    it holds a spread, shorthand or computed key — each of these can loosen every
    screenshot compare without touching the specs."""
    code = _code_of_file(PW_CONFIG)
    blocks = [m.end() - 1 for m in _EXPECT_BLOCK.finditer(code)]
    assert "defineConfig(" in code and blocks, (
        f"POSITIVE PARTNER: {PW_CONFIG.name} has no defineConfig( with an expect block; "
        "the checks below may be reading the wrong file"
    )
    assert _GLOBAL_SNAPSHOT_WORD.search("expect: { 'toHaveScreenshot': { threshold: 1 } }"), (
        "POSITIVE PARTNER: the word pattern no longer finds a quoted key"
    )
    found = sorted({m.group(1) for m in _GLOBAL_SNAPSHOT_WORD.finditer(code)})
    assert not found, (
        f"{PW_CONFIG.name} sets {found}; screenshot tolerance belongs on each call in the "
        "visual specs, where the tests above can see it"
    )
    for start in blocks:
        keys = _object_entries(code[start : _matching(code, start) + 1])
        odd = sorted(k for k in keys if k.startswith("<"))
        assert not odd, f"{PW_CONFIG.name} expect block has {odd}, which this test cannot read"


# --------------------------------------------------------------------------- T2

_PIN_IMPORT = re.compile(
    r"""import\s*\{([^}]*)\}\s*from\s*["']\.\./\.\./fixtures/pinned-fonts["']"""
)
_FIXTURE_IMPORT = re.compile(r"""from\s*["']\.\./\.\./fixtures/([\w.-]+)["']""")
_FUNCTION_DEF = re.compile(
    r"(?:\bfunction\s+([A-Za-z_$][\w$]*)\s*\("
    r"|\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\()"
)
_TEST_CALL = re.compile(r"(?<![\w$.])test\s*\(")
#: The pin as a whole statement: at the start of the body or after ``{ ; }``.
_PIN_STATEMENT = re.compile(r"(?:^|(?<=[{;}]))\s*await\s+pinGoogleFonts\s*\(\s*page\s*\)\s*;")
_GOTO = re.compile(r"\.goto\s*\(")


def _call_of(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w$.]){re.escape(name)}\s*\(")


def _function_bodies(code: str) -> dict[str, str]:
    """``{name: body}`` for every named function / block-bodied arrow in *code*.

    A definition this reader cannot parse is skipped; the positive partner in
    ``test_every_visual_test_pins_the_fonts_before_the_page_loads`` goes red
    if that ever hides the function that loads the page.
    """
    bodies: dict[str, str] = {}
    for match in _FUNCTION_DEF.finditer(code):
        name = match.group(1) or match.group(2)
        try:
            _, after_params = _split_top_level(code, match.end(), ")")
            brace = re.match(r"\s*(?::\s*[^{=;]*)?(?:=>\s*)?\{", code[after_params:])
            if not brace:
                continue  # an expression-bodied arrow or a plain call
            open_index = after_params + brace.end() - 1
            bodies[name] = code[open_index + 1 : _matching(code, open_index)]
        except AssertionError:
            continue
    return bodies


def _loading_functions(bodies: dict[str, str]) -> set[str]:
    """Names in *bodies* that navigate: directly (``.goto(``) or through another."""
    loading: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, body in bodies.items():
            if name in loading:
                continue
            if _GOTO.search(body) or any(_call_of(n).search(body) for n in loading):
                loading.add(name)
                changed = True
    return loading


def _test_bodies(code: str) -> list[str]:
    """The block body of the callback passed to each ``test(`` call."""
    bodies: list[str] = []
    for match in _TEST_CALL.finditer(code):
        args, _ = _split_top_level(code, match.end(), ")")
        callback = args[-1]
        arrow = re.match(r"async\s*\([^)]*\)\s*=>\s*\{", callback, re.S)
        assert arrow, f"test( callback is not an `async (...) => {{` block: {callback[:80]!r}"
        bodies.append(callback[arrow.end() : _matching(callback, arrow.end() - 1)])
    return bodies


def _first_page_event(body: str, local: dict[str, str], loaders: set[str]) -> str:
    """``"pin"``, ``"load"`` or ``"none"``: what happens first, in source order.

    The pin counts only as an ``await pinGoogleFonts(page);`` statement at depth
    0 of *body*. A call to a function in *local* that loads the page is resolved
    by recursing into that function's body.
    """
    events: list[tuple[int, str, str]] = []
    for pin in _PIN_STATEMENT.finditer(body):
        if _depth_at(body, pin.end() - 1) == 0:
            events.append((pin.start(), "pin", ""))
            break
    goto = _GOTO.search(body)
    if goto:
        events.append((goto.start(), "load", ""))
    for name in loaders:
        call = _call_of(name).search(body)
        if call:
            events.append((call.start(), "call", name))
    if not events:
        return "none"
    _, kind, name = min(events)
    if kind == "call" and name in local:
        inner = _first_page_event(local[name], local, loaders)
        return "load" if inner == "none" else inner
    return "pin" if kind == "pin" else "load"


def _pin_order_per_test(spec: Path) -> list[str]:
    code = _code_of_file(spec)
    local = _function_bodies(code)
    every: dict[str, str] = {}
    for module in sorted(set(_FIXTURE_IMPORT.findall(code))):
        fixture = FIXTURES / (module if module.endswith(".ts") else f"{module}.ts")
        if fixture.exists():
            every.update(_function_bodies(_code_of_file(fixture)))
    every.update(local)
    loaders = _loading_functions(every)
    return [_first_page_event(body, local, loaders) for body in _test_bodies(code)]


def test_the_pin_reader_tells_a_call_from_a_decoy() -> None:
    """RED if the pin reader counts a pin that does not run first (after
    ``boot(`` or ``page.goto(``, nested in an ``if`` block or an arrow function,
    in a comment), or stops counting a real top-level pin, directly or as the
    first statement of a local helper that loads the page."""

    def first(body: str, local: dict[str, str] | None = None) -> str:
        helpers = local or {}
        return _first_page_event(_code_of(body), helpers, {"boot", *helpers})

    assert first("await pinGoogleFonts(page);\n  await boot(page);") == "pin", "POSITIVE PARTNER"
    helper = {"drive": _code_of("\n await pinGoogleFonts(page);\n await boot(page);\n")}
    assert first("\n await drive(page);", helper) == "pin", "POSITIVE PARTNER: pin in a helper"
    assert first("await boot(page);\n await pinGoogleFonts(page);") == "load"
    assert first("if (x) { await pinGoogleFonts(page); }\n await boot(page);") == "load"
    arrow = "const f = async () => { await pinGoogleFonts(page); };\n await boot(page);"
    assert first(arrow) == "load"
    assert first("// await pinGoogleFonts(page);\n await boot(page);") == "load"
    assert first("await page.goto('/ui');\n await pinGoogleFonts(page);") == "load"


def test_each_visual_spec_imports_the_pin_from_the_fixture() -> None:
    """RED if either visual spec stops importing ``pinGoogleFonts`` from
    ``../../fixtures/pinned-fonts`` in its code (only a comment mentions it, it
    is renamed with ``as``, or comes from another module), or defines its own
    local ``pinGoogleFonts`` that would shadow the real one."""
    for spec in VISUAL_SPECS:
        code = _code_of_file(spec)
        imports = _PIN_IMPORT.search(code)
        names = [n.strip() for n in imports.group(1).split(",")] if imports else []
        assert "pinGoogleFonts" in names, (
            f"{spec.name} does not import pinGoogleFonts from ../../fixtures/pinned-fonts "
            f"in its code (imported names: {names})"
        )
        assert not re.search(r"\b(?:function|const|let|var)\s+pinGoogleFonts\b", code), (
            f"{spec.name} defines its own pinGoogleFonts, shadowing the fixture's"
        )


def test_every_visual_test_pins_the_fonts_before_the_page_loads() -> None:
    """RED if any test in either visual spec reaches ``boot(``, ``page.goto(``
    or a fixture that loads the page (``driveToResult(``) before a top-level
    ``await pinGoogleFonts(page);``: the call deleted, moved after the load,
    left only as an import, only in a comment, or nested in a block. Also RED
    if a spec has no test, or a test that loads no page."""
    for spec in VISUAL_SPECS:
        order = _pin_order_per_test(spec)
        assert order, f"POSITIVE PARTNER: no test( callback found in {spec.name}"
        assert "none" not in order, (
            f"POSITIVE PARTNER: a test in {spec.name} loads no page that this reader can see "
            f"({order}); the pin check would pass over nothing"
        )
        assert order == ["pin"] * len(order), (
            f"{spec.name}: per test, what happens first is {order}; every test must run "
            "`await pinGoogleFonts(page);` before the page loads (CHG-031)"
        )


def test_the_pin_helper_routes_to_the_saved_stylesheet() -> None:
    """RED if ``e2e/fixtures/pinned-fonts.ts`` is missing, stops exporting
    ``pinGoogleFonts``, calls no ``.route(``, or names ``google-fonts.css`` only
    in a comment."""
    assert PIN_HELPER.exists(), f"{PIN_HELPER.relative_to(ROOT)} does not exist"
    code = _code_of_file(PIN_HELPER)
    assert re.search(
        r"export\s+(?:async\s+function\s+pinGoogleFonts\s*\(|const\s+pinGoogleFonts\s*=)", code
    ), "pinned-fonts.ts does not export pinGoogleFonts"
    assert re.search(r"\.route\s*\(", code), "pinned-fonts.ts routes no request"
    assert "google-fonts.css" in code, "pinned-fonts.ts does not serve google-fonts.css"


# --------------------------------------------------------------------------- T3


class _StylesheetLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        href = values.get("href") or ""
        is_sheet = tag == "link" and values.get("rel") == "stylesheet"
        if is_sheet and href.startswith("https://fonts.googleapis.com/"):
            self.hrefs.append(href)


def _template_font_url() -> str:
    """The template's Google Fonts stylesheet URL, with ``&amp;`` unescaped."""
    links = _StylesheetLinks()
    links.feed(TEMPLATE.read_text(encoding="utf-8"))
    assert len(links.hrefs) == 1, (
        f"POSITIVE PARTNER: expected one Google Fonts stylesheet link in {TEMPLATE.name}, "
        f"found {links.hrefs}"
    )
    return html.unescape(links.hrefs[0])


def _fonts_meta() -> dict[str, object]:
    assert FONTS_META.exists(), f"{FONTS_META.relative_to(ROOT)} does not exist"
    meta = json.loads(FONTS_META.read_text(encoding="utf-8"))
    assert isinstance(meta, dict), meta
    return meta


def _fonts_css() -> bytes:
    assert FONTS_CSS.exists(), f"{FONTS_CSS.relative_to(ROOT)} does not exist"
    return FONTS_CSS.read_bytes()


def test_the_saved_stylesheet_is_for_the_url_the_template_requests() -> None:
    """RED if ``google-fonts.json``'s ``url`` differs from the template's font
    stylesheet href (``&amp;`` unescaped) by even one character, e.g. the
    template gains a weight and the fixture is not re-captured, or if the json
    is missing."""
    assert _fonts_meta().get("url") == _template_font_url(), (
        f"{FONTS_META.name} url != the stylesheet href in {TEMPLATE.name}; re-capture "
        f"{FONTS_CSS.name} for the new link"
    )


def test_the_saved_stylesheet_matches_its_recorded_hash_and_size() -> None:
    """RED if ``google-fonts.css`` changes by one byte (appended, removed,
    edited) without ``google-fonts.json``'s ``sha1`` and ``bytes`` following, or
    if ``sha1`` is not a full 40-character hex SHA-1."""
    meta, body = _fonts_meta(), _fonts_css()
    assert re.fullmatch(r"[0-9a-f]{40}", str(meta.get("sha1"))), meta.get("sha1")
    actual = hashlib.sha1(body, usedforsecurity=False).hexdigest()
    assert actual == meta["sha1"], f"{FONTS_CSS.name} SHA-1 is {actual}, json says {meta['sha1']}"
    assert len(body) == meta.get("bytes"), (
        f"{FONTS_CSS.name} is {len(body)} bytes, json says {meta.get('bytes')}"
    )


def test_the_saved_stylesheet_is_the_normal_answer() -> None:
    """RED if ``google-fonts.css`` holds a ``fonts.gstatic.com/l/`` URL (the
    other Geist build that caused the flake, ADR-0149), any ``url(`` outside
    ``https://fonts.gstatic.com/s/``, or no ``/s/`` URL at all."""
    css = _fonts_css().decode("utf-8")
    targets = re.findall(r"url\(\s*['\"]?([^'\")\s]+)", css)
    normal = [t for t in targets if t.startswith("https://fonts.gstatic.com/s/")]
    assert normal, f"POSITIVE PARTNER: no https://fonts.gstatic.com/s/ URL in {FONTS_CSS.name}"
    assert "fonts.gstatic.com/l/" not in css, (
        f"{FONTS_CSS.name} holds a fonts.gstatic.com/l/ URL, the font build that caused the flake"
    )
    assert normal == targets, (
        f"{FONTS_CSS.name} has url( targets outside fonts.gstatic.com/s/: "
        f"{sorted(set(targets) - set(normal))}"
    )


def test_the_saved_stylesheet_declares_every_family_the_template_requests() -> None:
    """RED if a family the template's link requests (Newsreader, Geist, Geist
    Mono) has no ``font-family`` declaration in ``google-fonts.css``: its
    ``@font-face`` blocks deleted, or a family added to the template and not
    re-captured."""
    query = parse_qs(urlsplit(_template_font_url()).query)
    families = {value.split(":", 1)[0] for value in query.get("family", [])}
    assert "Geist" in families, f"POSITIVE PARTNER: family parse found {families}"
    declared = set(
        re.findall(
            r"font-family\s*:\s*['\"]?([^'\";}]+?)['\"]?\s*[;}]", _fonts_css().decode("utf-8")
        )
    )
    missing = sorted(families - declared)
    assert not missing, f"{FONTS_CSS.name} declares no font-family {missing} (has {declared})"


# --------------------------------------------------------------------------- T4

#: The card's lines, as the exact-text check in the spec pins them. Literals, so
#: deleting or weakening the spec's array cannot pass by reading itself.
CARD_LINES = [
    "Not verified — these are automated structural checks, not a fact-check.",
    "Structural checks passed — citations were not verified against their sources.",
    "Some citation markers did not point at a source on this run.",
    "Not every answer that came back carried a primary source.",
    "This question needed a safety caveat and the synthesis did not include one.",
]


def test_the_exact_text_check_runs_before_the_screenshot() -> None:
    """RED if the ``toEqual([`` of the card's five lines is deleted from
    ``trust-score-visual.spec.ts``'s code (or left only in a comment), loses or
    changes a line, is moved after ``toHaveScreenshot(``, or stops being applied
    to ``expect.poll(cardLines)`` where ``cardLines`` reads
    ``surface.innerText()``."""
    code = _code_of_file(TRUST_SPEC)
    screenshot = _CALL.search(code)
    assert screenshot, "POSITIVE PARTNER: no toHaveScreenshot( call in the spec's code"
    checks: list[tuple[int, list[str]]] = []
    for match in re.finditer(r"\.toEqual\s*\(\s*\[", code):
        items, _ = _split_top_level(code, match.end(), "]")
        if all(_is_string_literal(i) and i[0] == '"' for i in items):
            checks.append((match.start(), [json.loads(i) for i in items]))
    card_checks = [at for at, lines in checks if lines == CARD_LINES]
    assert card_checks, f"no toEqual([...]) of the five card lines in the code; found {checks}"
    at = card_checks[0]
    assert at < screenshot.start(), "the exact-text check comes after toHaveScreenshot("
    receiver = re.sub(r"\s+", "", code[code.rfind("expect", 0, at) : at])
    assert receiver == "expect.poll(cardLines)", f"the check is applied to {receiver!r}"
    assert re.search(r"const\s+cardLines\s*=[^;]*surface\.innerText\(\)", code), (
        "cardLines no longer reads surface.innerText()"
    )
