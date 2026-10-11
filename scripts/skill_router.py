#!/usr/bin/env python3
"""Deterministic skill router for Codex Product Factory."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# A placeholder marker only counts when it sits in a *placeholder context*:
# it must own a whole field -- a line, a Markdown table cell, a bullet, or the
# value after a ``Key:`` label. Matching the bare words anywhere in prose made
# finished documents that merely *mention* a marker (or assert the opposite,
# e.g. docs/12 "not a pending activation") route as unfinished templates.
#
# ``_FIELD_START`` = start of line / table cell / field value, plus any
# Markdown decoration (bullet, quote, heading, emphasis, backticks). Written as
# a single flat character class -- a nested quantifier here backtracks
# catastrophically on long ``---``/``***`` rules (measured: the sweep over
# docs/ hung past 120s before this was flattened).
_FIELD_START = r"(?:^|[|·:])[ \t>*_`~#+-]*"
# ``_FIELD_END`` = the marker is the whole field: only trailing punctuation or
# Markdown decoration may follow before the next cell boundary or end of line.
_FIELD_END = r"[ \t]*[.,;!*_`~]*[ \t]*(?=$|[|·])"
# Single-word markers: only a placeholder when they are the entire field value.
_MARKER_WORD = r"(?:TBD|TODO|Pending|Placeholder)"
# Imperative template stubs: inherently template text, so opening a field is
# enough -- the rest of the sentence is the instruction ("Replace with ...").
_MARKER_PHRASE = (
    r"(?:Replace with|Write the idea here|Define after clarification|"
    r"To be written after idea clarification)"
)
PLACEHOLDER_RE = re.compile(
    rf"{_FIELD_START}(?:{_MARKER_WORD}(?![A-Za-z0-9]){_FIELD_END}"
    rf"|{_MARKER_PHRASE}(?![A-Za-z0-9]))",
    re.I | re.M,
)


def read_text(rel: str) -> str:
    path = ROOT / rel
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def meaningful(rel: str) -> bool:
    text = read_text(rel).strip()
    if len(text) < 40:
        return False
    if rel == "PRODUCT_IDEA.md":
        raw = re.search(r"## Raw idea\s+(.*?)(\n## |\Z)", text, re.S)
        if raw:
            text = raw.group(1).strip()
        return len(text) > 40 and not PLACEHOLDER_RE.search(text)
    return PLACEHOLDER_RE.search(text) is None


def load_router() -> dict[str, Any]:
    return json.loads((ROOT / "configs" / "skill-router.json").read_text(encoding="utf-8"))


def detect_risk_triggers() -> list[str]:
    # Only inspect artifacts that already contain meaningful product-specific content.
    # Template placeholders mention many enterprise topics and should not trigger every reviewer.
    if not meaningful("PRODUCT_IDEA.md"):
        return []
    candidate_paths = [
        "PRODUCT_IDEA.md",
        "docs/04-problem-statement.md",
        "docs/10-functional-requirements.md",
        "docs/11-non-functional-requirements.md",
        "docs/20-architecture.md",
        "docs/42-ai-safety-grounding.md",
        "docs/59-backend-engineering-practices.md",
        "docs/96-study-artifact-publishing.md",
        "docs/97-faq-wiki-plan.md",
        "docs/98-technical-article-plan.md",
        "docs/99-linkedin-post-plan.md",
        "docs/100-industry-and-integration-practices.md",
    ]
    texts = [read_text(p) for p in candidate_paths if meaningful(p)]
    combined = "\n".join(texts).lower()
    found: list[str] = []
    if any(
        k in combined
        for k in ["ai", "llm", "rag", "agent", "prompt", "model", "embedding", "hallucination"]
    ):
        found.append("ai_llm_rag_agentic")
    if any(
        k in combined
        for k in [
            "auth",
            "permission",
            "personal data",
            "privacy",
            "secret",
            "token",
            "encryption",
            "compliance",
        ]
    ):
        found.append("security_privacy_data")
    if any(
        k in combined
        for k in ["jira", "confluence", "mcp", "external skill", "skills.sh", "atlassian"]
    ):
        found.append("external_skill_or_mcp")
    if any(
        k in combined
        for k in ["ui", "ux", "screen", "dashboard", "user journey", "onboarding", "accessibility"]
    ):
        found.append("ux_customer_loved")
    if any(
        k in combined
        for k in [
            "slo",
            "observability",
            "grafana",
            "alert",
            "incident",
            "runbook",
            "latency",
            "throughput",
        ]
    ):
        found.append("operations_reliability")
    if any(
        k in combined
        for k in [
            "study",
            "faq",
            "wiki",
            "article",
            "linkedin",
            "confluence page",
            "publish",
            "watermark",
            "gif",
            "video",
            "diagram",
            "knowledge base",
        ]
    ):
        found.append("content_study_publishing")
    if any(
        k in combined
        for k in [
            "fastapi",
            "python api",
            "backend",
            "pydantic",
            "apirouter",
            "sqlalchemy",
            "async",
            "database",
            "api endpoint",
        ]
    ):
        found.append("backend_api_python")
    return found


def route() -> dict[str, Any]:
    config = load_router()
    selected = None
    for phase in config["phases"]:
        if not all(meaningful(rel) for rel in phase.get("evidence", [])):
            selected = dict(phase)
            break
    if selected is None:
        selected = {
            "id": "operate-improve",
            "label": "Operate, learn, and improve",
            "evidence": [],
            "driver": "production-feedback-loop",
            "reviewers": [
                "post-release-operations",
                "support-readiness",
                "product-discovery",
                "fanatic-critic",
            ],
            "blocking_gates": ["production-readiness-review"],
            "triggers": ["all core evidence exists"],
            "prompt": (
                "Review production signals, incidents, support feedback, and product "
                "metrics. Propose the next iteration with evidence."
            ),
        }
    risks = detect_risk_triggers()
    triggered_skills: list[str] = []
    for risk in risks:
        triggered_skills.extend(config.get("risk_triggers", {}).get(risk, []))
    # Preserve order, remove duplicates, and keep driver separate.
    reviewers = []
    for skill in selected.get("reviewers", []) + triggered_skills:
        if skill != selected.get("driver") and skill not in reviewers:
            reviewers.append(skill)
    selected["reviewers"] = reviewers
    selected["risk_triggers_detected"] = risks
    selected["conflict_precedence"] = config.get("conflict_precedence", [])
    selected["external_skill_rule"] = config.get("external_skill_rule", "")
    selected["orbi_profile_rule"] = config.get("orbi_profile_rule", "")
    selected["missing_or_placeholder_evidence"] = [
        rel for rel in selected.get("evidence", []) if not meaningful(rel)
    ]
    return selected


def format_route(r: dict[str, Any]) -> str:
    reviewers = ", ".join(r.get("reviewers", [])) or "None"
    blockers = ", ".join(r.get("blocking_gates", [])) or "None"
    missing = ", ".join(r.get("missing_or_placeholder_evidence", [])) or "None"
    risks = ", ".join(r.get("risk_triggers_detected", [])) or "None"
    return f"""Skill route
===========
Phase: {r.get("label")}
Driver skill: {r.get("driver")}
Reviewer skills: {reviewers}
Blocking gates: {blockers}
Missing/placeholders: {missing}
Risk triggers: {risks}

Suggested Codex prompt:
{r.get("prompt")}
"""


# --------------------------------------------------------------------------
# Work-item routing (ADR-0159). route() above picks a product phase from the
# documents; it never looks at the work. route_work() reads the change itself:
# its paths, and the lines it adds or removes.
# --------------------------------------------------------------------------

BOARD = "docs/65-open-work.md"
_BACKTICKED = re.compile(r"`([^`]+)`")
_NEEDLE = re.compile(r"^(?:PRESENT|ABSENT)\s+(\S+)\s+::")
_PATH_TOKEN = re.compile(r"^[\w.*-]+(?:/[\w.*-]*)*$")
_FILE_NAME = re.compile(
    r"(?:\.(?:py|m?js|ts|css|html|md|json|ya?ml|toml|txt|sh|lock|png|svg|cfg|ini|example)"
    r"|^Makefile|^Dockerfile)$"
)


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _is_docs(path: str) -> bool:
    return path.startswith("docs/") or ("/" not in path and path.lower().endswith(".md"))


def _changed_lines(diff_text: str) -> list[str]:
    """The added and removed lines of a unified diff. Context lines, hunk
    headers, the ``---``/``+++`` file headers and the lines of Markdown files
    never count: prose about fees is not a fee change."""
    lines: list[str] = []
    in_header = skip_file = False
    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            in_header, skip_file = True, line.lower().endswith(".md")
        elif line.startswith("@@"):
            in_header = False
        elif not in_header and not skip_file and line.startswith(("+", "-")):
            lines.append(line[1:])
    return lines


def _name_has_word(path: str, words: list[str]) -> bool:
    """True when the file name holds one of ``words`` as a whole part, outside
    docs/. So ``test_cost_breakdown.py`` and ``costs.py`` match "cost", but
    ``feedback_store.py`` does not match "fee"."""
    if path.startswith("docs/"):
        return False
    parts = re.split(r"[^a-z0-9]+", path.rsplit("/", 1)[-1].lower())
    return any(part in (word, word + "s") for part in parts for word in words)


def route_work(paths: list[str], diff_text: str = "", *, docs_only: bool = True) -> dict[str, Any]:
    """Classify one work item by its paths and changed lines. ``docs_only``
    allows the docs-only shortcut when every path is a doc; item mode turns it
    off, because a board row's docs path is a citation, not the change."""
    cfg = load_router()["work_item_routing"]
    classes = cfg["classes"]
    matched: list[dict[str, Any]] = []
    unclassified: list[str] = []
    if docs_only and paths and all(_is_docs(p) for p in paths):
        matched = [c for c in classes if c["id"] == "docs-only"]
    else:
        changed = "\n".join(_changed_lines(diff_text))
        covered: set[str] = set()
        for cls in classes:
            if cls["id"] == "docs-only":
                continue
            hits = {
                p
                for p in paths
                if any(fnmatch.fnmatchcase(p, g) for g in cls.get("paths", []))
                or _name_has_word(p, cls.get("name_words", []))
            }
            covered |= hits
            pattern = cls.get("identifiers")
            if hits or (pattern and changed and re.search(pattern, changed)):
                matched.append(cls)
        # A docs path next to code is read by the prose auditor; it is not "unclassified".
        unclassified = [p for p in paths if p not in covered and not _is_docs(p)]
        if not matched and paths and all(_is_docs(p) for p in paths):
            # Item mode: a row's words come first; a row that cites only docs and
            # whose words match no class is docs work.
            matched = [c for c in classes if c["id"] == "docs-only"]
    is_code = any(c["id"] != "docs-only" for c in matched)
    roles = cfg["base_roles"] + (cfg["code_roles"] if is_code else [])
    return {
        "driver": cfg["driver"],
        "classes": [c["id"] for c in matched],
        "roles": _unique(roles + [r for c in matched for r in c["roles"]]),
        "reviewer_skills": _unique([s for c in matched for s in c["reviewer_skills"]]),
        "checks": _unique([k for c in matched for k in c["checks"]]),
        "owner_decisions": _unique([d for c in matched for d in c["owner_decisions"]]),
        "unclassified": unclassified,
    }


def _as_path(token: str) -> str | None:
    """The repo path a backticked board token names, or None if it is not one."""
    needle = _NEEDLE.match(token)
    if needle:
        return needle.group(1)
    token = re.sub(r":\d+$", "", token.strip())  # `path:42` cites a line
    # `/status` is a URL path and `src/` a directory; neither names a file.
    if token.startswith("/") or token.endswith("/") or not _PATH_TOKEN.match(token):
        return None
    if "/" in token:
        # `origin/main` and a model id like `vendor/model` are not repo paths.
        return token if (ROOT / token.split("/", 1)[0]).exists() else None
    if not _FILE_NAME.search(token):
        return None
    # The board often names a module bare (`providers.py`); find it in src/.
    if not (ROOT / token).exists() and (ROOT / "src" / "product_app" / token).exists():
        return f"src/product_app/{token}"
    return token


def paths_for_item(item_id: str, board_text: str | None = None) -> tuple[list[str], str]:
    """The paths cited in the board row whose first cell is exactly ``item_id``."""
    text = read_text(BOARD) if board_text is None else board_text
    for line in text.splitlines():
        cells = line.split("|")
        if len(cells) > 2 and line.lstrip().startswith("|") and cells[1].strip() == item_id:
            found = [_as_path(t) for t in _BACKTICKED.findall(line)]
            return _unique([p for p in found if p]), line
    raise LookupError(f"no row with id {item_id!r} in {BOARD}")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    ).stdout


def paths_for_diff(base: str, repo: Path | None = None) -> tuple[list[str], str]:
    """Paths changed since the merge base of ``base`` and HEAD: committed,
    uncommitted and untracked (not ignored) files. Also the diff text."""
    repo = repo or ROOT
    merge_base = _git(repo, "merge-base", base, "HEAD").strip()
    changed = _git(repo, "diff", "--name-only", "--no-renames", "-z", merge_base).split("\0")
    untracked = _git(repo, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    paths = _unique([p for p in changed + untracked if p])
    added = "".join(_as_added(repo, p) for p in untracked if p)
    return paths, _git(repo, "diff", "--no-renames", merge_base) + added


def _as_added(repo: Path, rel: str) -> str:
    """An untracked file as a diff that adds every line, so its content is read
    like a tracked change. A Markdown, binary or over-256-KiB file gives ""."""
    path = repo / rel
    if rel.lower().endswith(".md") or not path.is_file() or path.stat().st_size > 256 * 1024:
        return ""
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return ""
    if "\0" in text:
        return ""
    body = "".join(f"+{line}\n" for line in text.splitlines())
    return f"diff --git a/{rel} b/{rel}\n--- /dev/null\n+++ b/{rel}\n@@ -0,0 +1 @@\n{body}"


def format_work_route(source: str, paths: list[str], r: dict[str, Any]) -> str:
    def line(items: list[str]) -> str:
        return ", ".join(items) or "None"

    classes = line(r["classes"]) if r["classes"] else "none matched; only the base roles apply"
    decisions = "".join(f"\n  - {d}" for d in r["owner_decisions"]) or " None"
    return f"""Work item route
===============
{source}
Paths: {line(paths)}
Driver: {r["driver"]}
Classes: {classes}
Roles: {line(r["roles"])}
Checks: {line(r["checks"])}
Reviewer skills: {line(r["reviewer_skills"])}
Owner decisions:{decisions}
Unclassified paths: {line(r["unclassified"])}
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--item", help="route the docs/65-open-work.md row with this id")
    group.add_argument("--diff", metavar="BASE", help="route the change since BASE")
    # Tests only: read this file instead of docs/65-open-work.md.
    parser.add_argument("--board", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.item:
        board = args.board.read_text(encoding="utf-8") if args.board else None
        try:
            paths, row = paths_for_item(args.item, board_text=board)
        except LookupError as exc:
            print(f"skill_router: {exc}. Check the id.", file=sys.stderr)
            return 1
        # The row's prose is read as added lines, so "spend key" routes money.
        rows_as_added = "".join(f"+{x}\n" for x in row.splitlines())
        result = route_work(paths, rows_as_added, docs_only=False)
        if not result["classes"]:
            print(
                f"NOT ROUTED: neither the paths nor the words of row {args.item} match any "
                f"class (paths: {', '.join(paths) or 'none'}). Route the change with "
                "`make skill-route DIFF=origin/main` once it exists, or add a backticked "
                f"path to the row in {BOARD}.",
                file=sys.stderr,
            )
            return 1
        print(format_work_route(f"Item: {args.item}", paths, result))
        return 0
    if args.diff:
        try:
            paths, diff_text = paths_for_diff(args.diff)
        except subprocess.CalledProcessError as exc:
            print(f"skill_router: git failed: {exc.stderr.strip()}", file=sys.stderr)
            return 1
        if not paths:
            print(f"skill_router: no changed paths since {args.diff}.", file=sys.stderr)
            return 1
        print(format_work_route(f"Diff: {args.diff}", paths, route_work(paths, diff_text)))
        return 0
    print(format_route(route()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
