"""W105 (ADR-0178, Consequences): only the workspace page joins the token channel.

ADR-0178 says that of the templates only ``workspace.html`` loads ``app.js``,
so the capped, ops and invite pages never join the ``quorum-session-token``
channel. Those pages hold their own token, or none, and must not pass it to
the workspace's tabs or take one from them. The designer's
``test_the_capped_pages_never_join_the_channel`` names two of the other
templates. This file walks the whole directory, so a template added later is
covered without editing a list.

Each template is read as HTML: its ``<script>`` elements are collected, and
only their code is searched, never the page's comments or prose. A script the
page loads from ``/static/`` is read from disk and searched the same way.

RED IF: any template other than ``workspace.html`` loads ``app.js``, or has an
inline script, or loads a ``/static/`` script, whose code opens a
``BroadcastChannel``. Partners: ``workspace.html`` does load ``/static/app.js``,
``app.js`` does open the channel, and the walk sees inline and ``src`` scripts
in the other templates, so "none found" is not true over nothing.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from tests.code_text import code_without_comments

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "src" / "product_app" / "templates"
STATIC = ROOT / "src" / "product_app" / "static"
WORKSPACE = "workspace.html"

# A channel opened in code: ``new BroadcastChannel(`` with any spacing.
_OPENS_CHANNEL = re.compile(r"\bnew\s+BroadcastChannel\s*\(")


class _Scripts(HTMLParser):
    """Collects each ``<script>``: its ``src`` (or None) and its inline text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[tuple[str | None, str]] = []
        self._src: str | None = None
        self._inside = False
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self._inside = True
            self._src = dict(attrs).get("src")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._inside:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._inside:
            self.scripts.append((self._src, "".join(self._text)))
            self._inside = False


def _scripts(template: Path) -> list[tuple[str | None, str]]:
    parser = _Scripts()
    parser.feed(template.read_text(encoding="utf-8"))
    parser.close()
    return parser.scripts


def _js_code(text: str, tmp_path: Path, name: str) -> str:
    """``text`` as JavaScript with its comments blanked out."""
    path = tmp_path / f"{name}.js"
    path.write_text(text, encoding="utf-8")
    return code_without_comments(path)


def _other_templates() -> list[str]:
    return sorted(p.name for p in TEMPLATES.glob("*.html") if p.name != WORKSPACE)


def test_the_walk_sees_the_templates_and_their_scripts() -> None:
    """Partner. Red when: the directory walk finds no other template, or the
    parser sees no inline script or no ``src`` script in them, so the checks
    below would pass over nothing."""
    others = _other_templates()
    assert (TEMPLATES / WORKSPACE).is_file()
    assert others, "no template other than workspace.html was found"
    scripts = [s for name in others for s in _scripts(TEMPLATES / name)]
    assert any(src is None and text.strip() for src, text in scripts), "no inline script seen"
    assert any(src for src, _ in scripts), "no src script seen"


def test_the_workspace_loads_app_js_and_app_js_opens_the_channel(tmp_path: Path) -> None:
    """Partner. Red when: ``workspace.html`` stops loading ``/static/app.js``,
    or ``app.js`` no longer opens a channel in code, so the parser or the
    pattern would miss the very thing the other tests refuse."""
    sources = [src for src, _ in _scripts(TEMPLATES / WORKSPACE) if src]
    assert "/static/app.js" in sources, sources
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert _OPENS_CHANNEL.search(_js_code(app_js, tmp_path, "app"))


@pytest.mark.parametrize("template", _other_templates())
def test_no_other_template_loads_app_js_or_opens_a_channel(template: str, tmp_path: Path) -> None:
    """Red when: this template loads ``app.js``, or an inline script, or a
    ``/static/`` script it loads, opens a ``BroadcastChannel`` in code."""
    for index, (src, text) in enumerate(_scripts(TEMPLATES / template)):
        if src:
            assert Path(src.split("?")[0]).name != "app.js", (template, src)
            if src.startswith("/static/"):
                loaded = STATIC / src.split("?")[0].removeprefix("/static/")
                assert loaded.is_file(), (template, src)
                code = code_without_comments(loaded)
                assert not _OPENS_CHANNEL.search(code), (template, src)
        code = _js_code(text, tmp_path, f"inline{index}")
        assert not _OPENS_CHANNEL.search(code), (template, index)
