#!/usr/bin/env python3
"""Check that every root prompt file is a valid next-session prompt.

A root prompt is any ``.md`` file at the repository root whose name contains
"prompt", in any case. Unless it is exempt, each one must (ADR-0160, ADR-0169):

- carry a visible paragraph of this form:

      **Process:** ... .agents/skills/work-item-delivery/SKILL.md ...

- be named ``CONTINUE-<AREA>-<ROWS>-PROMPT.md``, where AREA is one or more
  upper-case words joined by hyphens and ROWS is one or more board rows
  (``W28`` or ``W28-W70``), see ``NAME_PATTERN``;
- show each of the four sections in ``REQUIRED_SECTIONS`` as a level-2
  heading at the top level of the page, in any order.

Visibility is decided by a CommonMark parser (markdown-it-py, which ADR-0029
chose after hand-rolled block rules failed), not by line rules: two rounds of
hand-written rules each let a code example or a comment through. The check
walks the RENDERED HTML, not the parser's tokens, because raw HTML passes
through the tokens unread: a comment it left open hid a paragraph from a
reader while a token-based check still accepted it. A heading counts only as
an ``<h2>`` with no attribute and no enclosing element, so a heading inside a
code block, a comment, a block quote, a list or a raw ``<div>`` does not.

The check reads the directory itself, so it sees untracked files too. It
exits 1 on any problem, and also when it finds no prompt file at all.
``paste_lines`` gives, for each validly named prompt that passes, the one
line the owner pastes to start the next session; ``make handoff`` prints it.
"""

from __future__ import annotations

import argparse
import re
from html.parser import HTMLParser
from pathlib import Path

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]

#: Files that may lack the line, each with the reason. A name here whose file
#: is gone is itself a problem, so an exemption cannot outlive its file.
EXEMPT: dict[str, str] = {
    "R2-S2-S4-ULTRACODE-PROMPT.md": (
        "a worked example kept because tests/test_ultracode_prompt_enforcement_contract.py "
        "pins its shape; marked 'Example only' at its top"
    ),
}

_SKILL_PATH = ".agents/skills/work-item-delivery/SKILL.md"

#: The only accepted name of a root prompt: CONTINUE-, an upper-case area of
#: one or more hyphen-joined words, one or more board rows, then -PROMPT.md.
NAME_PATTERN = re.compile(r"^CONTINUE-[A-Z0-9]+(?:-[A-Z0-9]+)*-W[0-9]+(?:-W[0-9]+)*-PROMPT\.md$")

#: The level-2 headings every root prompt must show (order is not checked).
REQUIRED_SECTIONS: tuple[str, ...] = (
    "Read first",
    "The items, in order",
    "Approvals",
    "End of session",
)

_NAME_FORM = "CONTINUE-<AREA>-<ROWS>-PROMPT.md"


def find_prompt_files(root: Path) -> list[Path]:
    """Every root ``.md`` file whose name contains "prompt", in any case."""
    return sorted(
        p
        for p in root.iterdir()
        if p.is_file() and p.name.lower().endswith(".md") and "prompt" in p.name.lower()
    )


#: Elements that never hold content (the HTML void elements), so they are never
#: left open. Any other tag written self-closing, such as ``<div hidden />``,
#: stays open in a browser: the slash is ignored, and what follows is inside it.
_VOID = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }
)

#: Block elements a Markdown paragraph may sit inside (block quote, list).
_CONTAINERS = frozenset({"blockquote", "ul", "ol", "li"})
#: Inline elements Markdown makes inside a paragraph; text in them is visible.
_INLINE = frozenset({"strong", "em", "code", "a"})


def _plain(tag: str, attrs: list[tuple[str, str | None]]) -> bool:
    """True when the element carries only attributes Markdown itself writes:
    none, ``start`` on a numbered list, ``href``/``title`` on a link."""
    allowed = {"ol": {"start"}, "a": {"href", "title"}}.get(tag, set())
    return all(name in allowed for name, _ in attrs)


class _Paragraph:
    def __init__(self) -> None:
        self.opening = "await-strong"  # then "in-strong", then "opened" or "no"
        self.label = ""
        self.text = ""


class _ProcessParagraphs(HTMLParser):
    """Walks rendered HTML and sets ``found`` when a paragraph that Markdown
    made opens with ``<strong>Process:</strong>`` and its text names the skill.

    Raw HTML passes through to the page, so only what Markdown makes counts. A
    paragraph is a ``<p>``, or an ``<li>`` (a tight list item has no ``<p>``),
    with no attribute, whose every enclosing element is a plain block quote or
    list. Its text is the data directly in it or in plain ``strong``, ``em``,
    ``code`` or ``a``; a nested list item's text is its own. Comments are
    never data. Markdown writes ``<br />``, ``<hr />`` and ``<img ... />``,
    void elements, which are opened and closed at once; a raw ``<br>``
    without the slash stays open and refuses what follows it, the strict side.
    A self-closing tag that is not void (``<div hidden />``) stays open, as in
    a browser."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found = False
        # Each open element: (tag, plain, the paragraph it starts or None).
        self._open: list[tuple[str, bool, _Paragraph | None]] = []

    def _innermost(self) -> tuple[int, _Paragraph | None]:
        """The innermost open paragraph and its index in ``_open``."""
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i][2] is not None:
                return i, self._open[i][2]
        return -1, None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        _, para = self._innermost()
        if para and para.opening == "await-strong":
            para.opening = "in-strong" if tag == "strong" else "no"
        elif para and para.opening == "in-strong":
            para.opening = "no"
        starts = (
            tag in ("p", "li")
            and not attrs
            and all(t in _CONTAINERS and plain for t, plain, _ in self._open)
        )
        self._open.append((tag, _plain(tag, attrs), _Paragraph() if starts else None))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        _, para = self._innermost()
        if para and para.opening == "in-strong":
            ends = tag == "strong" and para.label == "Process:"
            para.opening = "opened" if ends else "no"
        self._close_to(tag)

    def handle_data(self, data: str) -> None:
        i, para = self._innermost()
        if para is None:
            return
        if not all(t in _INLINE and plain for t, plain, _ in self._open[i + 1 :]):
            return  # inside an element Markdown does not make in a paragraph
        if para.opening == "await-strong" and data.strip():
            para.opening = "no"
        elif para.opening == "in-strong":
            para.label += data
        para.text += data

    def _close_to(self, tag: str) -> None:
        """Close ``tag`` and every element opened inside it; an end tag with
        no open element is ignored, as in a browser."""
        if all(t != tag for t, _, _ in self._open):
            return
        while self._open:
            closed, _, para = self._open.pop()
            if para and para.opening == "opened" and _SKILL_PATH in para.text:
                self.found = True
            if closed == tag:
                return


def has_process_line(text: str) -> bool:
    """True when the RENDERED page shows a paragraph (at any depth: list item,
    block quote) that opens with bold ``Process:`` and whose visible text names
    the skill. The Markdown is rendered by a CommonMark parser and the HTML is
    walked, so code blocks, headings, HTML comments (also one an HTML block or
    inline HTML leaves open) and paragraphs that raw HTML wraps or marks never
    count; a path in backticks or in link text does."""
    walker = _ProcessParagraphs()
    # An unclosed "<!--" hides everything after it in a browser. Python's
    # HTMLParser ends one at close() as a comment on 3.12.13 but as text on
    # 3.9.6 (both measured), so close it explicitly: after an open comment,
    # "-->" ends it; with none open, it is three characters of text at the
    # end, which cannot name the skill.
    walker.feed(MarkdownIt("commonmark").render(text) + "-->")
    walker.close()
    return walker.found


class _TopLevelHeadings(HTMLParser):
    """Walks rendered HTML and collects the text of every level-2 heading a
    reader sees at the top level of the page: an ``<h2>`` with no attribute
    and no enclosing element. Its text is the data directly in it or in plain
    ``strong``, ``em``, ``code`` or ``a``; any other element inside it spoils
    the heading. Comments are never data."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headings: list[str] = []
        self._open: list[tuple[str, bool]] = []
        self._text: str | None = None  # the open top-level heading's text
        self._spoiled = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._text is not None and not (tag in _INLINE and _plain(tag, attrs)):
            self._spoiled = True
        if tag in _VOID:
            return
        if tag == "h2" and not attrs and not self._open:
            self._text, self._spoiled = "", False
        self._open.append((tag, _plain(tag, attrs)))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # A self-closing tag that is not void stays open, as in a browser.
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if all(t != tag for t, _ in self._open):
            return
        while self._open:
            closed, _ = self._open.pop()
            if not self._open and self._text is not None:
                if not self._spoiled:
                    self.headings.append(self._text.strip())
                self._text = None
            if closed == tag:
                return

    def handle_data(self, data: str) -> None:
        if self._text is not None:
            self._text += data


def missing_sections(text: str) -> list[str]:
    """The sections of ``REQUIRED_SECTIONS`` the RENDERED page does not show
    as a top-level level-2 heading whose text, stripped, equals the section.
    In ``REQUIRED_SECTIONS`` order; an empty list means none is missing."""
    walker = _TopLevelHeadings()
    # As in has_process_line: an unclosed "<!--" hides the rest of the page.
    walker.feed(MarkdownIt("commonmark").render(text) + "-->")
    walker.close()
    shown = set(walker.headings)
    return [section for section in REQUIRED_SECTIONS if section not in shown]


def problems(root: Path, exempt: dict[str, str]) -> list[str]:
    """One message per problem. An empty list means the root passes."""
    if not root.is_dir():
        return [f"{root} is not a directory"]
    found: list[str] = []
    files = find_prompt_files(root)
    if not files:
        found.append(f"no root prompt file found in {root}; the check measured nothing")
    for name in sorted(exempt):
        if not (root / name).is_file():
            found.append(f"{name} is exempt but does not exist; remove it from EXEMPT")
    for path in files:
        if path.name not in exempt:
            found += file_problems(path)
    return found


def file_problems(path: Path) -> list[str]:
    """The problems of one root prompt file: its name, its Process line and
    its four sections. An empty list means the file passes."""
    found: list[str] = []
    if not NAME_PATTERN.fullmatch(path.name):
        found.append(
            f"{path.name} is not named {_NAME_FORM} "
            "(for example CONTINUE-PARKED-WORK-W28-W70-PROMPT.md)"
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    if not has_process_line(text):
        found.append(
            f"{path.name} has no '**Process:** ... "
            ".agents/skills/work-item-delivery/SKILL.md' line outside a code block"
        )
    for section in missing_sections(text):
        found.append(f"{path.name} has no visible top-level '## {section}' heading")
    return found


def paste_lines(root: Path) -> list[str]:
    """The line the owner pastes to start the next session, one per root
    prompt whose name matches ``NAME_PATTERN`` and that passes the check,
    sorted by name. A prompt that fails is in ``failing_named_prompts``."""
    return [
        f"Read {path.name} in the repo root and follow it exactly."
        for path in find_prompt_files(root)
        if NAME_PATTERN.fullmatch(path.name) and not file_problems(path)
    ]


def failing_named_prompts(root: Path) -> list[str]:
    """The names of root prompts named for the next session that fail the
    check, sorted. No paste line is offered for these."""
    return [
        path.name
        for path in find_prompt_files(root)
        if NAME_PATTERN.fullmatch(path.name) and file_problems(path)
    ]


def counts(root: Path, exempt: dict[str, str]) -> str:
    """The "checked N, exempt M" line: prompt files read, and prompt files skipped."""
    files = find_prompt_files(root) if root.is_dir() else []
    skipped = sum(1 for p in files if p.name in exempt)
    return f"checked {len(files) - skipped}, exempt {skipped}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="directory to check")
    root = parser.parse_args(argv).root
    found = problems(root, EXEMPT)
    print(f"Root prompt check: {counts(root, EXEMPT)}")
    for message in found:
        print(f"  - {message}")
    print("FAILED" if found else "PASSED")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
