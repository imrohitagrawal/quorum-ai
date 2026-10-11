"""Regressions for review round 2 of how-we-work package A (ADR-0159, ADR-0160).

Each test names the finding it pins. Inputs and expected values are LITERALS:
a real board row copied from docs/65-open-work.md on 2026-10-11, real source
lines, and literal class names. None is read from ``configs/skill-router.json``
(AGENTS.md rule 7a).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from tests.repo_root import find_repo_root
from tests.subprocess_env import env_without_coverage

_ROOT = find_repo_root(Path(__file__))
_SCRIPTS = _ROOT / "scripts"
_ROUTER_PATH = _SCRIPTS / "skill_router.py"


def _load(name: str, path: Path) -> ModuleType:
    """A fresh copy of a script, loaded by path INSIDE each test, so a missing
    function fails that test alone. Registered in sys.modules before it runs,
    because session_hygiene's dataclasses look their module up there (#467)."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _router() -> ModuleType:
    return _load("skill_router_round_2_under_test", _ROUTER_PATH)


def _check() -> ModuleType:
    return _load("check_root_prompts_round_2_under_test", _SCRIPTS / "check_root_prompts.py")


def _handoff() -> ModuleType:
    return _load("session_handoff_round_2_under_test", _SCRIPTS / "session_handoff.py")


def _one_line_diff(path: str, *changed: str) -> str:
    """A unified diff of ``path`` whose changed lines are ``changed`` (each
    starting with + or -)."""
    body = "".join(f"{line}\n" for line in changed)
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1,1 +1,1 @@\n{body}"


def _classes(path: str, line: str) -> list[str]:
    r = _router().route_work([path], _one_line_diff(path, line))
    return r["classes"]  # type: ignore[no-any-return]


# --------------------------------------------------------------------------
# 1. The process line is found by a CommonMark parser, not by line rules.
# --------------------------------------------------------------------------

_LINE = "**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`."


@pytest.mark.parametrize(
    "text",
    [
        f"# P\n\n- ```markdown\n  {_LINE}\n  ```\n",
        "# P\n\n**Process:** <!-- .agents/skills/work-item-delivery/SKILL.md -->\n",
        f"# P\n\nx <!-- a --> y <!-- b\n{_LINE}\n-->\n",
        f"# P\n\n````markdown\n```\n{_LINE}\n````\n",
        f"# P\n\nIntro paragraph.\n\n    {_LINE}\n",
        f"# P\n\nIntro paragraph.\n\n\t{_LINE}\n",
        f"# P\n\n<!--\n{_LINE}\n-->\n",
        f"# P\n\n## {_LINE}\n",
    ],
    ids=[
        "list-item-fence",
        "path-only-in-a-comment",
        "second-comment-opens-on-the-same-line",
        "four-backtick-fence-with-a-three-backtick-line",
        "indented-4",
        "indented-tab",
        "html-block-comment",
        "heading-not-a-paragraph",
    ],
)
def test_the_process_line_in_code_or_a_comment_is_refused(text: str) -> None:
    # Red when: has_process_line() counts a line inside a fence (also a fence opened in a
    # list item, or one a shorter fence line does not close), an indented code block, an HTML
    # block, reads the skill path from an inline <!-- --> comment as visible text, or counts
    # an inline token that is not a paragraph's (the heading case: drop the paragraph_open test).
    assert _check().has_process_line(text) is False, text


@pytest.mark.parametrize(
    "text",
    [
        f"# P\n\n{_LINE}\n",
        f"# P\n\n1. {_LINE}\n",
        f"# P\n\nUse `<!--` to hide a note.\n\n{_LINE}\n",
        f"# P\n\n<!--\na note\n-->\n{_LINE}\n",
        "# P\n\n**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`\n",
    ],
    ids=[
        "plain",
        "numbered-list-item",
        "after-inline-code-mentioning-a-comment-opener",
        "after-a-closed-multi-line-comment",
        "path-in-backticks",
    ],
)
def test_the_process_line_in_visible_text_is_accepted(text: str) -> None:
    # Red when: has_process_line() refuses a visible line: as a list item, after a paragraph
    # whose inline code holds "<!--", after a closed HTML comment, or with the path in
    # backticks (code_inline content dropped from the visible text).
    assert _check().has_process_line(text) is True, text


# --------------------------------------------------------------------------
# 2a. The global spend ceiling and the daily cap are money.
# --------------------------------------------------------------------------

_QUERY_RUNS = "src/product_app/query_runs.py"


@pytest.mark.parametrize(
    "line",
    [
        "-    query_run = query_run_repository.mark_global_ceiling_reached(query_run.query_run_id)",
        '+    OVER_DAILY_CAP = "over_daily_cap"',
        "+  const atGlobalCeiling = true;",
        "+class GlobalCeilingReached(Exception):",
    ],
    ids=["global_ceiling", "DAILY_CAP", "camel-atGlobalCeiling", "camel-GlobalCeiling"],
)
def test_the_global_ceiling_and_the_daily_cap_are_money(line: str) -> None:
    # Red when: the money identifiers lose global_ceiling (first case), daily_cap (second)
    # or the CamelCase GlobalCeiling (last two).
    classes = _classes(_QUERY_RUNS, line)
    assert "money" in classes, (line, classes)


def test_a_time_ceiling_is_still_not_money() -> None:
    # Red when: the ceiling identifier is widened back to bare "ceiling", so a comment about
    # a time ceiling routes money.
    classes = _classes(_QUERY_RUNS, "+  # the time ceiling is 35 minutes")
    assert "money" not in classes, classes
    # Positive partner: the same file's path still routes its own class.
    assert "ai-output-judge" in classes, classes


# --------------------------------------------------------------------------
# 2b. Item mode never takes the docs-only shortcut.
# --------------------------------------------------------------------------

# Copied verbatim from docs/65-open-work.md on 2026-10-11.
_W39 = "| W39 | The engineering harness: agents run in a container with only the agent account's token; a signed-in real-backend journey lane with an execution-backed gate; release integrity; a slimmer AGENTS.md with tracked hooks; the skills audit (`docs/analysis/2026-09-29/NEXT-SESSION-PROMPT.md`, order steps 0–7; PROPOSED, confirm in plan mode) | UNPINNED | `—` | — | — |"  # noqa: E501


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_ROUTER_PATH), *args],
        env=env_without_coverage(),
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _classes_line(stdout: str) -> list[str]:
    lines = [x for x in stdout.splitlines() if x.startswith("Classes: ")]
    assert len(lines) == 1, stdout
    return [c.strip() for c in lines[0].removeprefix("Classes: ").split(",")]


def test_an_item_citing_only_a_docs_path_still_routes_by_its_words(tmp_path: Path) -> None:
    # Red when: item mode takes the docs-only shortcut because the row's only cited path is a
    # Markdown file, discarding the row's words ("signed-in" routes sign-in-session).
    board = tmp_path / "board.md"
    board.write_text(f"{_W39}\n", encoding="utf-8")
    proc = _cli("--item", "W39", "--board", str(board))
    assert proc.returncode == 0, (proc.returncode, proc.stdout[-500:], proc.stderr[-500:])
    classes = _classes_line(proc.stdout)
    assert "sign-in-session" in classes, classes
    assert "docs-only" not in classes, classes
    # Partner: the docs path was read from the row (so the shortcut had a docs path to take).
    assert "docs/analysis/2026-09-29/NEXT-SESSION-PROMPT.md" in proc.stdout, proc.stdout


# --------------------------------------------------------------------------
# 2c. AI settings route to ai-output-judge.
# --------------------------------------------------------------------------

_CONFIG = "src/product_app/config.py"
_TEST_PATH = "tests/unit/test_visible_text.py"


def test_a_source_fetch_setting_routes_ai_output_judge_and_settings() -> None:
    # Red when: the ai-output-judge identifiers lose source_fetch, so a config.py page-reading
    # switch routes as "settings" only.
    classes = _classes(_CONFIG, "+    quorum_source_fetch_enabled: bool = True")
    assert "ai-output-judge" in classes, classes
    assert "settings" in classes, classes


def test_the_fly_toml_source_fetch_switch_routes_ai_output_judge() -> None:
    # Red when: the ai-output-judge identifiers stop matching the UPPER env spelling
    # QUORUM_SOURCE_FETCH_ENABLED (case-sensitive pattern).
    classes = _classes("fly.toml", '+  QUORUM_SOURCE_FETCH_ENABLED = "true"')
    assert "ai-output-judge" in classes, classes


def test_a_retention_setting_is_not_ai_output_judge() -> None:
    # Red when: the ai-output-judge identifiers match too widely (e.g. any "_days" or "keep"),
    # so a history setting routes the judge reviewers.
    classes = _classes(_CONFIG, "+    history_keep_days: int = 30")
    assert "ai-output-judge" not in classes, classes
    # Positive partner: the line does route, to its own class.
    assert "privacy-retention" in classes, classes


@pytest.mark.parametrize(
    "line",
    [
        "+    judge_enabled = True",
        '+JUDGE_ENABLED = "1"',
        "+    source_fetch_limit = 3",
        "+SOURCE_FETCH_LIMIT = 3",
        "+    source_pages = []",
        "+MAX_SOURCE_PAGES = 4",
        "+    peer_critique_rounds = 1",
        "+PEER_CRITIQUE_ROUNDS = 1",
        "+    live_execution = False",
        '+LIVE_EXECUTION = "false"',
        "+    openrouter_timeout_seconds = 8",
        '+OPENROUTER_API_KEY = ""',
        '+    tavily_api_key = ""',
        '+TAVILY_API_KEY = ""',
        '+    prompt_id = "v2"',
        '+PROMPT_ID = "v2"',
    ],
    ids=[
        "judge",
        "JUDGE",
        "source_fetch",
        "SOURCE_FETCH",
        "source_pages",
        "SOURCE_PAGES",
        "peer_critique",
        "PEER_CRITIQUE",
        "live_execution",
        "LIVE_EXECUTION",
        "openrouter",
        "OPENROUTER",
        "tavily",
        "TAVILY",
        "prompt_id",
        "PROMPT_ID",
    ],
)
def test_each_ai_identifier_routes_ai_output_judge_on_its_own(line: str) -> None:
    # Red when: the ai-output-judge identifiers lose the one word on this line (judge,
    # source_fetch, source_pages, peer_critique, live_execution, openrouter, tavily, prompt_id).
    classes = _classes(_TEST_PATH, line)
    assert "ai-output-judge" in classes, (line, classes)


# --------------------------------------------------------------------------
# 2d. A tracked change that is not UTF-8 does not crash DIFF mode.
# --------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "kept.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "src")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def test_a_tracked_change_that_is_not_utf8_is_read_not_crashed_on(tmp_path: Path) -> None:
    # Red when: paths_for_diff() decodes git's output strictly, so a Latin-1 byte in a tracked
    # change raises UnicodeDecodeError (a traceback from `make skill-route DIFF=...`).
    router = _router()
    repo = _repo(tmp_path)
    (repo / "src" / "kept.py").write_bytes(b"max_cost_usd = 1  # caf\xe9\n")
    paths, text = router.paths_for_diff("HEAD", repo=repo)
    # Joined at run time: the file exists only in the temporary repo, and a literal
    # "src/<name>.py" here would read as a citation to the cited-paths gate.
    assert "src/" + "kept.py" in paths, paths
    r = router.route_work(paths, text)
    assert "money" in r["classes"], (r["classes"], text[-300:])


# --------------------------------------------------------------------------
# 3. Test gaps from round 2.
# --------------------------------------------------------------------------


def test_make_skill_route_refuses_item_and_diff_together() -> None:
    # Red when: the Makefile's skill-route target accepts ITEM and DIFF together (runs one of
    # them) instead of stopping with "not both".
    proc = subprocess.run(
        ["make", "skill-route", "ITEM=W35", "DIFF=HEAD"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2, (proc.returncode, proc.stdout[-500:], proc.stderr[-500:])
    assert "not both" in proc.stdout + proc.stderr, (proc.stdout, proc.stderr)
    # Partner: the refusal came before any routing.
    assert "Work item route" not in proc.stdout, proc.stdout


_GOOD = f"# P\n\n{_LINE}\n"
_NO_LINE = "# P\n\nItems: W55.\n"
_EXEMPT = {"EX-PROMPT.md": "an example"}


def _root(tmp_path: Path, prompt_text: str) -> Path:
    root = tmp_path / "root"
    root.mkdir(parents=True)
    (root / "CONTINUE-X-PROMPT.md").write_text(prompt_text, encoding="utf-8")
    (root / "EX-PROMPT.md").write_text(_NO_LINE, encoding="utf-8")
    return root


def test_main_prints_checked_and_exempt_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Red when: main() stops printing "checked N, exempt M", or counts an exempt file as
    # checked (checked 2) or a checked file as exempt.
    check = _check()
    monkeypatch.setattr(check, "EXEMPT", dict(_EXEMPT))
    capsys.readouterr()
    assert check.main(["--root", str(_root(tmp_path, _GOOD))]) == 0
    first = capsys.readouterr().out.splitlines()[0]
    assert first == "Root prompt check: checked 1, exempt 1", first


def test_a_failed_handoff_section_shows_the_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: the FAILED handoff section drops the "checked N, exempt M" counts.
    check = _check()
    monkeypatch.setattr(check, "EXEMPT", dict(_EXEMPT))
    handoff = _handoff()
    monkeypatch.setattr(handoff, "_load_script", lambda name: check)
    section = handoff._prompt_check_section(_root(tmp_path, _NO_LINE))
    status = section.splitlines()[1]
    assert status.startswith("FAILED"), section
    assert "checked 1, exempt 1" in status, section
    assert "CONTINUE-X-PROMPT.md" in section, section


def _untracked_route(tmp_path: Path, name: str, data: bytes) -> list[str]:
    """Write ``data`` as an untracked file under src/ and route the diff."""
    router = _router()
    repo = _repo(tmp_path)
    # Joined at run time: the file exists only in the temporary repo (cited-paths gate).
    rel = "src/" + name
    (repo / rel).write_bytes(data)
    paths, text = router.paths_for_diff("HEAD", repo=repo)
    assert rel in paths, paths
    return router.route_work(paths, text)["classes"]  # type: ignore[no-any-return]


def test_an_untracked_markdown_file_is_not_read_for_money(tmp_path: Path) -> None:
    # Red when: an untracked .md file's lines reach the identifier match, which takes BOTH
    # _as_added()'s ".md" skip and _changed_lines()'s Markdown skip being removed (either one
    # alone still holds; measured by mutation).
    assert "money" not in _untracked_route(tmp_path / "md", "notes.md", b"fee = 1\n")
    # Positive partner: the same words in a small text file ARE read.
    assert "money" in _untracked_route(tmp_path / "txt", "notes.txt", b"fee = 1\n")


def test_an_untracked_file_with_a_nul_byte_is_skipped(tmp_path: Path) -> None:
    # Red when: _as_added() stops skipping a file that contains a NUL byte (binary content).
    assert "money" not in _untracked_route(tmp_path / "nul", "meter.py", b"fee = 1\n\x00\n")
    # Positive partner: without the NUL byte the file is read.
    assert "money" in _untracked_route(tmp_path / "ok", "meter.py", b"fee = 1\n\n")


def test_an_untracked_file_over_256_kib_is_skipped(tmp_path: Path) -> None:
    # Red when: the untracked-file size bound moves off 256 KiB (262,144 bytes) either way.
    head = b"fee = 1\n"

    def sized(total: int) -> bytes:
        return head + b"#" * (total - len(head) - 1) + b"\n"

    assert len(sized(262144)) == 262144 and len(sized(262145)) == 262145
    assert "money" in _untracked_route(tmp_path / "at", "meter.py", sized(262144))
    assert "money" not in _untracked_route(tmp_path / "over", "meter.py", sized(262145))


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("+    session = store.load(sid)", "sign-in-session"),
        ("+    cookie = jar.get(name)", "sign-in-session"),
        ("+    invite = load(code)", "sign-in-session"),
        ("+    account = lookup(subject)", "sign-in-session"),
        ("+    google = connect()", "sign-in-session"),
        ("+    history = []", "privacy-retention"),
        ("+    delete(row)", "privacy-retention"),
        ("+    personal = True", "privacy-retention"),
        ("+    ip_address = peer", "privacy-retention"),
        ("+    totalBill = 0", "money"),
        ("+    wasBilled = True", "money"),
        ("+    runBilling()", "money"),
    ],
    ids=[
        "session",
        "cookie",
        "invite",
        "account",
        "google",
        "history",
        "delete",
        "personal",
        "ip_address",
        "Bill",
        "Billed",
        "Billing",
    ],
)
def test_each_added_identifier_routes_on_its_own(line: str, expected: str) -> None:
    # Red when: the identifiers of the expected class lose the one word on this line.
    classes = _classes(_TEST_PATH, line)
    assert expected in classes, (line, classes)
