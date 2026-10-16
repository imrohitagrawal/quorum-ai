"""Regressions for review round 1 of how-we-work package A (ADR-0159, ADR-0160).

Each test names the finding it pins. Expected values are LITERALS: real board
rows copied from docs/65-open-work.md on 2026-10-11, real config.py field
names, and literal class, role, skill and check names. None is read from
``configs/skill-router.json`` (AGENTS.md rule 7a), except where the config is
ENUMERATED to check that each reviewer skill it names exists.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
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
_SKILLS = _ROOT / ".agents" / "skills"


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
    return _load("skill_router_round_1_under_test", _ROUTER_PATH)


def _check() -> ModuleType:
    return _load("check_root_prompts_round_1_under_test", _SCRIPTS / "check_root_prompts.py")


def _handoff() -> ModuleType:
    return _load("session_handoff_round_1_under_test", _SCRIPTS / "session_handoff.py")


def _hygiene() -> ModuleType:
    return _load("session_hygiene_round_1_under_test", _SCRIPTS / "session_hygiene.py")


def _one_line_diff(path: str, *changed: str) -> str:
    """A unified diff of ``path`` whose changed lines are ``changed`` (each
    starting with + or -)."""
    body = "".join(f"{line}\n" for line in changed)
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1,1 +1,1 @@\n{body}"


# --------------------------------------------------------------------------
# Finding 1: item mode routed real rows to nothing, quietly.
# --------------------------------------------------------------------------

# Copied verbatim from docs/65-open-work.md on 2026-10-11.
_W35 = '| W35 | "Sign out everywhere" during a run asks first: "Yes" stops the run and signs out everywhere; "No" signs out everywhere except the running session (CHG-026 b) | UNPINNED | `—` | — | W34 |'  # noqa: E501
_W36 = '| W36 | History keeps the full result (answers, debate, synthesis) for signed-in accounts, 20 conversations for 30 days, delete one / delete all; a row opens read-only with "Continue this conversation" (CHG-026 i; supersedes the 5-question keep of CHG-023 when built) | UNPINNED | `—` | — | W33 |'  # noqa: E501
_W14 = "| W14 | Close the 5xx possibly-billed premise with data | UNPINNED | `—` | #105 | production logs |"  # noqa: E501
# A constructed row whose words name no class.
_W90 = "| W90 | Tidy the wording of a heading | UNPINNED | `—` | — | — |"


def _route_row(item_id: str, row: str) -> dict:  # type: ignore[type-arg]
    """Route one board row the way the CLI does: its paths, and its text read
    as added lines."""
    router = _router()
    paths, found = router.paths_for_item(item_id, board_text=row + "\n")
    rows_as_added = "".join(f"+{x}\n" for x in found.splitlines())
    return router.route_work(paths, rows_as_added)  # type: ignore[no-any-return]


@pytest.mark.parametrize(
    ("item_id", "row", "expected"),
    [
        ("W35", _W35, "sign-in-session"),
        ("W36", _W36, "privacy-retention"),
        ("W14", _W14, "money"),
    ],
    ids=["W35-sign-out", "W36-history", "W14-billed"],
)
def test_real_rows_with_no_path_route_by_their_words(item_id: str, row: str, expected: str) -> None:
    # Red when: the sign-in identifiers lose sign out/signed-in/session (W35), the retention
    # identifiers lose history/delete (W36), or the money identifiers lose billed (W14).
    r = _route_row(item_id, row)
    assert expected in r["classes"], (item_id, r["classes"])


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_ROUTER_PATH), *args],
        env=env_without_coverage(),
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_item_that_routes_no_class_exits_1_and_says_not_routed(tmp_path: Path) -> None:
    # Red when: `--item` on a known row that matches no class exits 0 (an empty checklist
    # that reads as "only the base roles apply"), or exits 1 without "NOT ROUTED" and the id.
    board = tmp_path / "board.md"
    board.write_text(f"{_W90}\n{_W35}\n", encoding="utf-8")
    proc = _cli("--item", "W90", "--board", str(board))
    assert proc.returncode == 1, (proc.returncode, proc.stdout[-500:], proc.stderr[-500:])
    assert "NOT ROUTED" in proc.stderr, proc.stderr
    assert "W90" in proc.stderr, proc.stderr
    assert "DIFF=" in proc.stderr, proc.stderr

    # Positive partner: a row in the same board that matches a class exits 0 and names it.
    ok = _cli("--item", "W35", "--board", str(board))
    assert ok.returncode == 0, (ok.returncode, ok.stdout[-500:], ok.stderr[-500:])
    assert "sign-in-session" in ok.stdout, ok.stdout
    assert "NOT ROUTED" not in ok.stderr, ok.stderr


# --------------------------------------------------------------------------
# Finding 2: an untracked file's CONTENT was not read in diff mode.
# --------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _clean_repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "configs").mkdir()
    shutil.copy2(_ROUTER_PATH, repo / "scripts" / "skill_router.py")
    shutil.copy2(_ROOT / "configs" / "skill-router.json", repo / "configs" / "skill-router.json")
    (repo / "src").mkdir()
    (repo / "src" / "kept.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "scripts", "configs", "src")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def test_an_untracked_file_routes_by_its_content(tmp_path: Path) -> None:
    # Red when: paths_for_diff() leaves an untracked file's lines out of the diff text, so a
    # new file whose path names no class but which holds a spend cap is not routed money.
    router = _router()
    repo = _clean_repo(tmp_path)
    # Joined at run time: the file exists only in the temporary repo (cited-paths gate).
    meter = "src/" + "new_meter.py"
    (repo / meter).write_text("DAILY_SPEND_CAP_USD = 5.0\n", encoding="utf-8")
    # A note and a binary file next to it are skipped, not crashed on.
    (repo / "NOTES.md").write_text("The fee is high.\n", encoding="utf-8")
    (repo / "src" / "blob.bin").write_bytes(b"\xff\xfe\x00fee\x00")

    paths, text = router.paths_for_diff("HEAD", repo=repo)
    assert meter in paths, paths
    r = router.route_work(paths, text)
    assert "money" in r["classes"], (r["classes"], text[-500:])

    # Partner: the path alone (no content) routes no money, so the content is what did it.
    bare = router.route_work([meter])
    assert "money" not in bare["classes"], bare["classes"]


# --------------------------------------------------------------------------
# Finding 3: sign-in and retention settings routed as settings only.
# --------------------------------------------------------------------------

_CONFIG = "src/product_app/config.py"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("+    signed_in_idle_minutes: int = Field(default=120, ge=15, le=120)", "sign-in-session"),
        ("+    history_keep_days: int = Field(default=30, ge=1, le=365)", "privacy-retention"),
        (
            "+    sign_in_events_keep_days: int = Field(default=30, ge=1, le=365)",
            "privacy-retention",
        ),
        ("+    sign_in_events_keep_days: int = Field(default=30, ge=1, le=365)", "sign-in-session"),
    ],
    ids=[
        "idle-minutes",
        "history-keep-days",
        "events-keep-days-retention",
        "events-keep-days-sign-in",
    ],
)
def test_sign_in_and_retention_settings_route_beyond_settings(line: str, expected: str) -> None:
    # Red when: a changed config.py line for a sign-in or a keep-days setting routes only
    # "settings" (the sign-in or retention identifiers miss signed_in / sign_in / keep_days).
    r = _router().route_work([_CONFIG], _one_line_diff(_CONFIG, line))
    assert "settings" in r["classes"], r["classes"]
    assert expected in r["classes"], (line, r["classes"])


# --------------------------------------------------------------------------
# Finding 4: money over-routed on "feed" and "ceiling".
# --------------------------------------------------------------------------

_TEST_PATH = "tests/unit/test_visible_text.py"


@pytest.mark.parametrize(
    "line",
    ["+    parser.feed(text)", "+  # the time ceiling is 35 minutes"],
    ids=["feed", "ceiling"],
)
def test_feed_and_ceiling_are_not_money(line: str) -> None:
    # Red when: "fee" matches inside "feed" (fee + d), or "ceiling" alone counts as money.
    r = _router().route_work([_TEST_PATH], _one_line_diff(_TEST_PATH, line))
    assert "money" not in r["classes"], (line, r["classes"])


def test_a_fee_setting_is_still_money() -> None:
    # Red when: narrowing "fee" also stops the real fee setting from routing money.
    line = "+    cost_web_search_request_fee_usd = 0.007"
    r = _router().route_work([_TEST_PATH], _one_line_diff(_TEST_PATH, line))
    assert "money" in r["classes"], r["classes"]
    line = "+    fees = request_fee_usd * 2"
    r = _router().route_work([_TEST_PATH], _one_line_diff(_TEST_PATH, line))
    assert "money" in r["classes"], r["classes"]


# --------------------------------------------------------------------------
# Finding 5: the process line was accepted inside a code block or a comment.
# --------------------------------------------------------------------------

_LINE = "**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`."


@pytest.mark.parametrize(
    "text",
    [
        f"# P\n\nIntro paragraph.\n\n    {_LINE}\n",
        f"# P\n\nIntro paragraph.\n\n\t{_LINE}\n",
        f"# P\n\n```markdown\n```not-a-close\n{_LINE}\n",
        f"# P\n\n<!--\n{_LINE}\n-->\n",
    ],
    ids=["indented-4", "indented-tab", "fake-close-fence", "html-comment"],
)
def test_the_process_line_in_a_code_block_or_comment_is_refused(text: str) -> None:
    # Red when: has_process_line() accepts the line indented 4+ spaces or by a tab (an
    # indented code block), treats "```not-a-close" as closing the fence, or reads a line
    # inside <!-- --> as visible.
    assert _check().has_process_line(text) is False, text


@pytest.mark.parametrize(
    "text",
    [
        f"# P\n\n{_LINE}\n",
        f"# P\n\n   {_LINE}\n",
        f"# P\n\n```markdown\nx\n```\n\n<!-- a note -->\n{_LINE}\n",
    ],
    ids=["plain", "indented-3", "after-closed-fence-and-comment"],
)
def test_the_process_line_in_visible_text_is_accepted(text: str) -> None:
    # Red when: the fixes for the cases above also refuse a visible line (at column 0, at 3
    # spaces, or after a properly closed fence and a one-line comment).
    assert _check().has_process_line(text) is True, text


# --------------------------------------------------------------------------
# Finding 6: route gaps the failure-modes doc promised (R2, R4).
# --------------------------------------------------------------------------


def test_a_docs_only_route_has_no_money_skills_checks_or_decisions() -> None:
    # Red when: a docs-only route gains a money reviewer skill or check, or any owner decision.
    r = _router().route_work(["docs/65-open-work.md"])
    for skill in ("cost-finops", "idempotency-concurrency"):
        assert skill not in r["reviewer_skills"], (skill, r["reviewer_skills"])
    for check in ("cardinality-assertions", "diff-cover"):
        assert check not in r["checks"], (check, r["checks"])
    assert r["owner_decisions"] == [], r["owner_decisions"]
    # Positive partner: the route is not empty; it carries the prose auditor.
    assert "prose-auditor" in r["roles"], r["roles"]


def test_a_code_path_gets_the_test_designer_and_the_break_it_reviewer() -> None:
    # Red when: a src/ path stops adding the code roles (the partner to the docs-only absence).
    r = _router().route_work(["src/product_app/costs.py"])
    assert "test-designer" in r["roles"], r["roles"]
    assert "break-it-reviewer" in r["roles"], r["roles"]
    docs = _router().route_work(["docs/65-open-work.md"])
    assert "test-designer" not in docs["roles"], docs["roles"]


def test_every_reviewer_skill_of_every_class_has_a_skill_file() -> None:
    # Red when: any class under work_item_routing.classes names a reviewer skill with no
    # .agents/skills/<name>/SKILL.md (a class no probe path reaches is checked too).
    config = json.loads((_ROOT / "configs" / "skill-router.json").read_text(encoding="utf-8"))
    names = {s for c in config["work_item_routing"]["classes"] for s in c["reviewer_skills"]}
    assert len(names) > 10, f"only {len(names)} names checked"
    missing = sorted(n for n in names if not (_SKILLS / n / "SKILL.md").is_file())
    assert missing == [], f"reviewer skills with no SKILL.md: {missing}"


def test_a_tests_path_no_class_names_is_listed_as_unclassified() -> None:
    # Red when: a tests/ path that matches no class is dropped from "unclassified" (so the
    # route reads as if every path were covered).
    path = "tests/unit/test_root_prompt_check.py"
    r = _router().route_work([path])
    assert path in r["unclassified"], r["unclassified"]
    # Partner: a covered path is not listed.
    assert _router().route_work(["src/product_app/costs.py"])["unclassified"] == []


# --------------------------------------------------------------------------
# Findings 7, 8, 9: the handoff's degrade guards, reasons and counts.
# --------------------------------------------------------------------------

# The four sections every root prompt must carry (item 1, ADR-0169), in good and bad
# fixtures alike, so the bad one lacks ONLY the Process line.
_SECTIONS = (
    "\n## Read first\n\nx\n\n## The items, in order\n\nx\n\n"
    "## Approvals\n\nx\n\n## End of session\n\nx\n"
)
_GOOD = f"# P\n\n{_LINE}\n" + _SECTIONS
_NO_LINE = "# P\n\nItems: W55.\n" + _SECTIONS


def _prompt_root(tmp_path: Path, prompt_text: str) -> Path:
    root = tmp_path / "root"
    root.mkdir(parents=True)
    (root / "CONTINUE-X-W1-PROMPT.md").write_text(prompt_text, encoding="utf-8")
    # The real exemptions are written so they do not fail as "exempt file missing".
    for name in _check().EXEMPT:
        (root / name).write_text(_NO_LINE, encoding="utf-8")
    return root


def _raising_loader(fail: str):  # type: ignore[no-untyped-def]
    def load(name: str) -> object:
        if name == fail:
            raise RuntimeError(f"cannot load {name}")
        return _load(f"{name}_round_1_loader", _SCRIPTS / f"{name}.py")

    return load


def test_prompt_check_section_degrades_when_the_loader_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: _prompt_check_section() lets an exception from loading check_root_prompts
    # escape (aborting the whole handoff, against ADR-0045) instead of saying "unavailable".
    handoff = _handoff()
    monkeypatch.setattr(handoff, "_load_script", _raising_loader("check_root_prompts"))
    section = handoff._prompt_check_section(_prompt_root(tmp_path, _GOOD))
    assert "## Root prompt check" in section, section
    assert "unavailable" in section, section


def test_prompt_check_section_shows_the_counts(tmp_path: Path) -> None:
    # Red when: the passing section drops the "checked N, exempt M" line, so a check that
    # measured nothing reads the same as one that measured every file.
    section = _handoff()._prompt_check_section(_prompt_root(tmp_path, _GOOD))
    assert "PASSED" in section, section
    assert "checked 1" in section, section


def test_leftovers_section_shows_each_findings_reason() -> None:
    # Red when: _leftovers_section() prints a finding's label without its "why", so a REPORT
    # that means "could not measure" reads as an ordinary leftover.
    hygiene = _hygiene()
    category = hygiene.Category(5, "docker", "Docker images and containers", hygiene.REPORT, list)
    finding = hygiene.Finding("docker", hygiene.REPORT, "could not measure: is the daemon up?")
    section = _handoff()._leftovers_section([(category, [finding])])
    assert "`docker`" in section, section
    assert "could not measure: is the daemon up?" in section, section


_LIVE_STATE_STUB: dict[str, object] = {
    "main_tip": "a" * 40,
    "last_src_commit": "b" * 40,
    "prod_build_sha": None,
    "build_sha_drift_line": "unavailable: stub",
    "pytest_count": "unavailable: stub",
    "e2e_lane_counts": {"invariants": 0, "ops": 0, "degraded": 0},
    "open_issue_count": "unavailable",
    "unmerged_branches": [],
}

_ROUTE_STUB: dict[str, object] = {
    "label": "Operate, learn, and improve",
    "driver": "production-feedback-loop",
    "reviewers": [],
    "blocking_gates": [],
    "missing_or_placeholder_evidence": [],
    "prompt": "stub prompt",
}


def _stubbed_handoff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    handoff = _handoff()
    (tmp_path / "docs").mkdir()
    monkeypatch.setattr(handoff, "ROOT", tmp_path)
    monkeypatch.setattr(
        handoff, "_prompt_check_section", lambda *a, **k: "## Root prompt check\nPASSED\n"
    )
    monkeypatch.setattr(handoff, "_gather_live_state", lambda *a, **k: dict(_LIVE_STATE_STUB))
    monkeypatch.setattr(handoff, "load_route", lambda *a, **k: dict(_ROUTE_STUB))
    monkeypatch.setattr(handoff, "run", lambda *a, **k: "")
    # The parked-work section (item 1) reads git and gh; stubbed so no test reaches the
    # network. raising=False: the stub is harmless where main() has no such helper.
    monkeypatch.setattr(
        handoff,
        "_parked_section",
        lambda *a, **k: "## Parked work and branches\nstub\n",
        raising=False,
    )
    return handoff


def test_main_writes_the_handoff_when_leftovers_are_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: main() aborts or drops the Leftovers section when _collect_leftovers()
    # returns None, instead of writing "unavailable" there.
    handoff = _stubbed_handoff(tmp_path, monkeypatch)
    monkeypatch.setattr(handoff, "_collect_leftovers", lambda *a, **k: None)
    assert handoff.main() == 0
    text = (tmp_path / "docs" / "session-handoff.md").read_text(encoding="utf-8")
    assert "## Leftovers" in text, text[:2000]
    assert "unavailable" in text.split("## Leftovers", 1)[1][:300], text[:2000]
    # Positive partner: the rest of the file is still there.
    assert "Operate, learn, and improve" in text


def test_main_writes_the_handoff_when_loading_session_hygiene_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: _collect_leftovers() stops catching an exception from loading or running
    # session_hygiene, so main() aborts and no handoff file is written.
    handoff = _stubbed_handoff(tmp_path, monkeypatch)
    monkeypatch.setattr(handoff, "_load_script", _raising_loader("session_hygiene"))
    assert handoff.main() == 0
    text = (tmp_path / "docs" / "session-handoff.md").read_text(encoding="utf-8")
    assert "## Leftovers" in text, text[:2000]
    assert "unavailable" in text.split("## Leftovers", 1)[1][:300], text[:2000]


# --------------------------------------------------------------------------
# Finding 10: the tracked-prompt test checked nothing on this tree.
# --------------------------------------------------------------------------


def test_the_real_exempt_prompt_fails_without_its_exemption(tmp_path: Path) -> None:
    # Red when: problems() stops refusing a real prompt that lacks the line (the tracked-prompt
    # test copies only non-exempt files, of which this tree has none, so it alone cannot fail).
    name = "R2-S2-S4-ULTRACODE-PROMPT.md"
    root = tmp_path / "root"
    root.mkdir()
    shutil.copy2(_ROOT / name, root / name)
    found = _check().problems(root, {})
    # Since item 1 the file's name (not CONTINUE-<AREA>-<ROWS>-PROMPT.md) and its missing
    # sections are refused too; exactly one message is about the Process line, and every
    # message names the file.
    process = [m for m in found if "**Process:**" in m]
    assert len(process) == 1, found
    assert all(name in m for m in found), found
