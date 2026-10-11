"""Review round 1 of package B (one status): a regression test for each reproduced finding.

ADR-0161 and ADR-0162. Each section names the finding it pins. Every test was
run against the code BEFORE its fix and its failure recorded; the tests of
section 6 pin guards that already worked, so their bite is shown by deleting
the guard instead.

1. The completion check judged hand-made "units": a run of non-blank lines was
   one unit, so one citation on a bullet supported a false claim on the next,
   a wrapped "in / production" was never seen, and a negation was read across a
   sentence end. The check now reads the CommonMark blocks the reader sees.
2. ``(#N)`` anywhere in a main subject counted as a merged pull request, so an
   issue number in a commit scope ("feat(#105):") supported a claim.
3. The grandfathered plain PRESENT rows were trusted by row id, so W28's
   needle could be swapped for a made-up one.
4. The readiness file: the spending ceiling, missing fields, a non-production
   URL, switches that no run reaches, and a hand-typed verdict.
5. The mechanical handoff called production "NOT in sync" after a docs-only
   merge, though every merge deploys (AGENTS.md rule 18a).
6. Guards a falsification lens deleted with every test green.

GATE CHARTER
------------
WHY THIS EXISTS: review round 1 of package B reproduced each of these with a
plant or a deletion that left every existing test green.

WHAT IT CANNOT SEE: wordings other than the ones planted here.

FALSE-POSITIVE COST: none beyond the checks under test.

WHEN TO REMOVE: with the checks under test.
"""

from __future__ import annotations

import copy
import io
import json
import re
import shutil
import urllib.error
from collections.abc import Iterator
from email.message import Message
from pathlib import Path
from typing import Any

import pytest
from tests.repo_root import find_repo_root
from tests.status_clone import (
    CUTOFF,
    git,
    git_out,
    is_ancestor_of_main,
    load_script,
    make_clone,
    planted,
    rel,
    run_python,
)

# No repo_introspection mark: ROOT comes from find_repo_root, so inside mutmut's
# ./mutants/ copy it still names the real repository, which the clone is made from.

ROOT = find_repo_root(Path(__file__))
COMPLETION_SCRIPT = str(ROOT / "scripts" / ("check_completion_claims" + ".py"))
BOARD = rel("docs", "65-open-work.md")
READINESS_FILE = rel("docs", "product-readiness.md")


def _completion() -> Any:
    return load_script(ROOT, "check_completion_claims")


def _newest_narrative_handoff(clone: Path) -> str:
    tracked = git_out(clone, "ls-files", "--", "docs/analysis/").splitlines()
    handoffs = sorted(
        p for p in tracked if p.count("/") == 2 and re.search(r"-session-handoff[^/]*\.md$", p)
    )
    assert handoffs, "no tracked narrative handoff to plant in"
    return handoffs[-1]


def _append_block(text: str, block: str) -> tuple[str, int]:
    """``text`` with ``block`` appended after a blank line, and the block's first line number."""
    head = text.rstrip("\n")
    return head + "\n\n" + block + "\n", len(head.splitlines()) + 2


@pytest.fixture(scope="module")
def clone(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    yield make_clone(ROOT, tmp_path_factory.mktemp("review-round-1") / "repo")


# ---------------------------------------------------------------------------
# 1, 2 and the git-fetch hint: every completion-check case, planted together and
# checked ONCE. Each case is its own block group, after a blank line, so no case
# can lend another a citation.
# ---------------------------------------------------------------------------

#: name -> the block planted. Literal inputs, from the round-1 reproductions.
BLOCKS: dict[str, str] = {
    # b1 (a): a bullet's citation must not support the next bullet.
    "list": "- W54 merged (#556)\n- W55 merged and in production",
    # b1 (b), the reviewer's exact input. The heading is its own unit and holds no
    # listed word ("done" is not on the list). The two lines under it are ONE
    # paragraph, which cites #556, so under the rule ("a citation supports only the
    # claims in its own unit") that paragraph passes. What the rule changes is shown
    # by "heading-claim" below: a heading's own claim words are judged alone.
    "heading-reviewer": (
        "## Done this session\nW55 and W56 merged and in production.\n"
        "See #556 for the earlier slice."
    ),
    "heading-claim": "## W55 merged and in production\nSee #556 for the earlier slice.",
    # b1 (c): a table written without leading pipes; each row is its own unit.
    "pipeless-table": "Row | State\n--- | ---\nW54 | merged #556\nW55 | merged and in production",
    "wrapped": "W55 is in\nproduction now.",
    "sentence-stop": "Rollback needed: no. In production since this morning.",
    "question-no": "Blocked? No, merged.",
    "status-fields": "Pushed: yes. Merged: no. In production: no.",
    "status-not-yet": "Merged: not yet. In production: not yet.",
    "status-yes": "In production: yes, W55 and W56.",
    "verified-label": "## Verified myself",
    "verified-heading": "## Verified the deploy",
    "release-ready": "W55 is release-ready.",
    "ga-upper": "Release 1 is GA.",
    "ga-lower": "The ga flag is a lower-case word.",
    # 2: #105 is in main subjects only as a commit scope ("feat(#105): ..."); #473 is
    # a squash suffix.
    "scope-105": "W14 merged and in production (#105).",
    "squash-473": "The web-search fee was merged in (#473).",
    "uncited": "W55 and W56 merged in #9558, in production.",
    # A line opening with inline triple-backtick code is a paragraph, not a fence:
    # its words are claims, and the paragraph after it is still read. LAST, because
    # a check that reads it as a fence skips every block after it.
    "inline-triple": "```W55``` merged and in production.\n\nW56 merged and in production.",
}

#: name -> {line offset in its block: the words reported there}. A line not named
#: here must have NO problem.
REPORTED: dict[str, dict[int, set[str]]] = {
    "list": {1: {"merged", "in production"}},
    "heading-reviewer": {},
    "heading-claim": {0: {"merged", "in production"}},
    "pipeless-table": {3: {"merged", "in production"}},
    "wrapped": {0: {"in production"}},
    "sentence-stop": {0: {"in production"}},
    "question-no": {0: {"merged"}},
    "inline-triple": {0: {"merged", "in production"}, 2: {"merged", "in production"}},
    "status-fields": {},
    "status-not-yet": {},
    "status-yes": {0: {"in production"}},
    "verified-label": {},
    "verified-heading": {0: {"verified"}},
    "release-ready": {0: {"release-ready"}},
    "ga-upper": {0: {"ga"}},
    "ga-lower": {},
    "scope-105": {0: {"merged", "in production"}},
    "squash-473": {},
    "uncited": {0: {"merged", "in production"}},
}


@pytest.fixture(scope="module")
def batch(clone: Path) -> dict[str, Any]:
    off_main = git_out(clone, "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "off main")[:7]
    blocks = dict(BLOCKS)
    blocks["off-main-sha"] = f"Deployed {off_main}, in production."
    path = _newest_narrative_handoff(clone)
    text = (clone / path).read_text(encoding="utf-8")
    starts: dict[str, int] = {}
    for name, block in blocks.items():
        text, starts[name] = _append_block(text, block)
    with planted(clone, {path: text}):
        problems, counts = _completion().check(clone)
    return {
        "problems": list(problems),
        "counts": dict(counts),
        "path": path,
        "starts": starts,
        "blocks": blocks,
        "off_main": off_main,
    }


def _at(batch: dict[str, Any], name: str, offset: int) -> list[str]:
    prefix = f"{batch['path']}:{batch['starts'][name] + offset}:"
    return [p for p in batch["problems"] if p.startswith(prefix)]


def _words(problems: list[str]) -> set[str]:
    return {m.group(1).lower() for p in problems if (m := re.search(r"'([^']+)'", p))}


@pytest.mark.parametrize("name", list(BLOCKS))
def test_each_planted_block_is_judged_unit_by_unit(batch: dict[str, Any], name: str) -> None:
    # Red when: a unit borrows another unit's citation (a bullet, a heading, a pipe-less table
    # row), a wrapped or sentence-separated claim is missed, a status field "Merged: no" or a
    # "Verified myself" label is refused, "```W55```" opens a fence, "(#105)" in a commit scope
    # counts as a merged pull request, or "release-ready"/"GA" stop being words.
    expected = REPORTED[name]
    lines = len(BLOCKS[name].splitlines())
    for offset in range(lines):
        found = _at(batch, name, offset)
        want = expected.get(offset, set())
        assert _words(found) == want, (
            f"{name}, line {offset} {BLOCKS[name].splitlines()[offset]!r}: "
            f"reported {sorted(_words(found))}, wanted {sorted(want)}\n{found}"
        )


def test_the_preconditions_of_the_batch_hold(clone: Path, batch: dict[str, Any]) -> None:
    # Red when: a plant's premise moves (#556 or #473 stops being a squash on main, #105 becomes
    # one, or the batch planted nothing the check counted), which would make a case vacuous.
    subjects = git_out(clone, "log", "refs/remotes/origin/main", "--format=%s").splitlines()
    assert any(re.search(r"\(#556\)\s*$", s) for s in subjects)
    assert any(re.search(r"\(#473\)\s*$", s) for s in subjects)
    assert any("(#105)" in s for s in subjects), "#105 must appear in a subject, as a scope"
    assert not any(re.search(r"\(#105\)\s*$", s) for s in subjects)
    assert batch["counts"]["claims"] > 0, batch["counts"]


def test_a_commit_not_on_the_local_main_says_to_fetch(clone: Path, batch: dict[str, Any]) -> None:
    # Red when: an unsupported claim citing a commit that is not on the local main does not say
    # so and suggest `git fetch` (production deploys a merge before this clone has fetched it).
    assert not is_ancestor_of_main(clone, batch["off_main"])
    found = _at(batch, "off-main-sha", 0)
    assert _words(found) == {"in production"}, found
    assert all("git fetch" in p and batch["off_main"] in p for p in found), found
    # PARTNER: a claim that cites no commit at all gets no fetch advice.
    uncited = _at(batch, "uncited", 0)
    assert uncited and not any("git fetch" in p for p in uncited), uncited


def test_the_makefile_runs_the_completion_check_with_uv() -> None:
    # Red when: `make completion-check` runs the check with the system Python, which lacks the
    # CommonMark parser the check now needs.
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = re.search(r"^completion-check:.*\n((?:\t.*\n)+)", makefile, re.MULTILINE)
    assert recipe, "no completion-check target"
    assert "uv run python scripts/check_completion_claims.py" in recipe.group(1), recipe.group(1)


# ---------------------------------------------------------------------------
# 3. A grandfathered PRESENT row keeps its needle, not just its id.
# ---------------------------------------------------------------------------

W28_OLD = "credential_source = ProviderCredentialSource.APP_OWNED`"
W28_NEW = "credential_source = ProviderCredentialSource.CALLER_CHOOSES`"


@pytest.fixture(scope="module")
def board_clone(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    repo = make_clone(ROOT, tmp_path_factory.mktemp("review-round-1-board") / "repo")
    # The board checker in the WORKING TREE is the one measured, with the helper it loads.
    for path in (rel("scripts", "check_open_work.py"), rel("tests", "code_text.py")):
        shutil.copyfile(ROOT / path, repo / path)
    yield repo


def _w28_row(text: str) -> str:
    rows = [line for line in text.splitlines() if line.startswith("| W28 |")]
    assert len(rows) == 1, rows
    return rows[0]


def test_a_grandfathered_row_with_a_swapped_needle_is_refused(board_clone: Path) -> None:
    # Red when: a grandfathered id may keep a plain PRESENT needle that differs from the one it
    # had at the cut-off (b66b107), so W28's needle can be swapped and typed DONE.
    script = rel("scripts", "check_open_work.py")
    done = run_python(board_clone, script, "--check")
    assert done.returncode == 0, f"the real board must pass first:\n{done.stdout}{done.stderr}"
    text = (board_clone / BOARD).read_text(encoding="utf-8")
    row = _w28_row(text)
    assert "| PENDING |" in row and W28_OLD in row, row
    at_cutoff = git_out(board_clone, "show", f"{CUTOFF}:{BOARD}")
    assert _w28_row(at_cutoff) == row, "W28 must be as it was at the cut-off"
    swapped = row.replace(W28_OLD, W28_NEW).replace("| PENDING |", "| DONE |")
    needle = W28_NEW.rstrip("`")
    target = board_clone / rel("src", "product_app", "query_run_orchestration.py")
    assert needle not in target.read_text(encoding="utf-8"), "the swapped needle must be absent"
    with planted(board_clone, {BOARD: text.replace(row, swapped)}):
        bad = run_python(board_clone, script, "--check")
    output = bad.stdout + bad.stderr
    assert bad.returncode == 1, f"exit {bad.returncode}\n{output}"
    assert "W28" in output and "PRESENT@" in output, output


# ---------------------------------------------------------------------------
# 4. The readiness file.
# ---------------------------------------------------------------------------

GENERATED_AT = "2026-10-11T18:37:09Z"

#: Production on 2026-10-11 (the designer's fixture in test_product_readiness.py), literal.
STATUS_2026_10_11: dict[str, Any] = {
    "app": "Quorum-AI",
    "version": "0.2.0",
    "build_sha": "b66b107f3f36eeaeb943ce93776b4fd4ef72095a",
    "environment": "production",
    "live_execution": False,
    "feedback_db": "connected",
    "feedback_writes": "unverified",
    "feedback_lost_billed_writes": 0,
    "feedback_events_total": 956,
    "latest_audit": None,
    "global_daily_spend_usd": "0",
    "global_daily_ceiling_usd": "5.00",
    "global_daily_simulated_spend_usd": "0",
    "last_live_charge_at": "2026-09-10T06:36:55.020418+00:00",
    "judge_enabled": True,
    "peer_critique_enabled": False,
    "source_fetch_enabled": True,
    "source_pages_in_effect": True,
    "sign_in_enabled": True,
    "session_limit_allow_list": {"active_entries": 0, "expired_entries": 0, "exempted_requests": 0},
    "invite_links": {"enabled": False, "revoked_links": 0, "requests_with_invite": 0},
    "peer_critique_in_effect": False,
    "model_catalog_loaded": True,
    "moderator_slot_overlap": [2],
    "error_tracking": "active",
    "uptime_seconds": 1068.3,
}
READY_2026_10_11: dict[str, Any] = {
    "status": "ready",
    "environment": "production",
    "live_readiness": {
        "state": "offline_by_config",
        "reasons": ["OPENROUTER_LIVE_EXECUTION_ENABLED is not set to 'true'."],
        "catalog_drift_ids": [],
        "global_spend_ceiling_reached": False,
    },
}
IDLE_HEADING = "Built and switched on, but idle while live execution is off: no run reaches them"
IDLE_KEYS = ("judge_enabled", "source_fetch_enabled", "source_pages_in_effect")


def _readiness() -> Any:
    return load_script(ROOT, "product_readiness")


def _live_and_ready() -> tuple[dict[str, Any], dict[str, Any]]:
    status = copy.deepcopy(STATUS_2026_10_11)
    status["live_execution"] = True
    ready = copy.deepcopy(READY_2026_10_11)
    ready["live_readiness"]["state"] = "live"
    ready["live_readiness"]["reasons"] = []
    return status, ready


def test_the_spending_ceiling_reached_is_not_ready() -> None:
    # Red when: /ready at the global spending ceiling (Codex's input: live on, "ready", no
    # reasons, global_spend_ceiling_reached true) gives the verdict "Ready".
    status, ready = _live_and_ready()
    said, _reasons = _readiness().verdict(status, ready)
    assert said == "Ready", "the partner: the same input below the ceiling is Ready"
    ready["live_readiness"]["global_spend_ceiling_reached"] = True
    said, reasons = _readiness().verdict(status, ready)
    assert said == "Not ready", reasons
    assert any("ceiling" in reason.lower() for reason in reasons), reasons


@pytest.mark.parametrize(
    "drop", ["live_readiness", "reasons", "global_spend_ceiling_reached", "reasons-a-string"]
)
def test_a_missing_live_readiness_field_is_not_ready(drop: str) -> None:
    # Red when: /ready without the live_readiness fields the verdict reads is taken as healthy.
    status, ready = _live_and_ready()
    if drop == "live_readiness":
        del ready["live_readiness"]
    elif drop == "reasons-a-string":
        ready["live_readiness"]["reasons"] = "a string, not a list"
    else:
        del ready["live_readiness"][drop]
    said, reasons = _readiness().verdict(status, ready)
    assert said == "Not ready", reasons
    named = "live_readiness" if drop == "live_readiness" else drop.split("-")[0]
    assert any(named in reason for reason in reasons), reasons


def test_another_server_is_named_as_itself_and_not_as_production() -> None:
    # Red when: a file rendered from --base-url (a local server) calls itself production.
    module = _readiness()
    status, ready = _live_and_ready()
    local = "http://localhost:18085"
    text = str(module.render(status, ready, GENERATED_AT, base_url=local))
    verdict_lines = [line for line in text.splitlines() if line.startswith("Verdict:")]
    assert len(verdict_lines) == 1, text
    assert local in verdict_lines[0] and "not production" in verdict_lines[0], verdict_lines
    prose = re.sub(r"```json\n.*?\n```", "", text, flags=re.DOTALL)
    assert "in production" not in prose and "production's" not in prose, prose
    assert "production build" not in prose, prose
    # PARTNER: the default URL is production and is called so.
    default = str(module.render(status, ready, GENERATED_AT))
    assert "production build" in default and "In effect in production" in default, default


def _section(text: str, heading_start: str) -> str:
    match = re.search(rf"^## {re.escape(heading_start)}.*?(?=^## |\Z)", text, re.M | re.S)
    assert match, f"no section starting {heading_start!r}:\n{text}"
    return match.group(0)


def test_switches_no_run_reaches_are_listed_as_idle_not_in_effect() -> None:
    # Red when: with live execution off, the judge, page fetching or page reading is listed as
    # "In effect", though no run reaches them.
    text = str(_readiness().render(STATUS_2026_10_11, READY_2026_10_11, GENERATED_AT))
    in_effect = _section(text, "In effect")
    idle = _section(text, IDLE_HEADING)
    for key in IDLE_KEYS:
        assert f"`{key}`" in idle, idle
        assert f"`{key}`" not in in_effect, in_effect
    assert "`sign_in_enabled`" in in_effect, in_effect
    # PARTNER: with live execution on, the same switches are in effect and nothing is idle.
    status, ready = _live_and_ready()
    live = str(_readiness().render(status, ready, GENERATED_AT))
    assert IDLE_HEADING not in live, live
    assert all(f"`{key}`" in _section(live, "In effect") for key in IDLE_KEYS), live


_EMBEDDED = re.compile(r"^```json\n(.*?)\n```$", re.MULTILINE | re.DOTALL)


def _rerendered(text: str) -> str:
    blocks = _EMBEDDED.findall(text)
    assert len(blocks) == 1, f"{len(blocks)} embedded JSON blocks, not 1"
    data = json.loads(blocks[0])
    assert set(data) == {"base_url", "generated_at", "status", "ready"}, sorted(data)
    return str(
        _readiness().render(
            data["status"], data["ready"], data["generated_at"], base_url=data["base_url"]
        )
    )


def test_the_committed_readiness_file_is_exactly_what_its_embedded_responses_render() -> None:
    # Red when: docs/product-readiness.md differs from render() over the /status and /ready it
    # embeds, so a hand-typed "Verdict: Ready" passes; or it embeds no responses.
    text = (ROOT / READINESS_FILE).read_text(encoding="utf-8")
    assert _rerendered(text) == text
    # PARTNER: the same file with its verdict typed by hand is caught.
    verdict = re.search(r"^Verdict: (Not ready|Ready|unknown)", text, re.MULTILINE)
    assert verdict, text
    other = "Verdict: Not ready" if verdict.group(1) == "Ready" else "Verdict: Ready"
    typed = text.replace(verdict.group(0), other, 1)
    assert typed != text and _rerendered(typed) != typed


# ---------------------------------------------------------------------------
# 5. The mechanical handoff's build line.
# ---------------------------------------------------------------------------

SRC = "a" * 40
BUILD = "b" * 40
OTHER = "c" * 40


def _handoff() -> Any:
    return load_script(ROOT, "session_handoff")


def test_production_at_the_main_tip_is_in_sync_after_a_docs_only_merge() -> None:
    # Red when: production at origin/main's tip is called "NOT in sync" because the tip is a
    # docs-only merge, not the last src/ commit (every merge deploys, AGENTS.md rule 18a).
    line = _handoff()._build_sha_drift_line(
        last_src_commit=SRC, prod_build_sha=BUILD, main_tip=BUILD
    )
    assert "in sync" in line.lower() and "not match" not in line.lower(), line


def test_production_containing_the_last_src_commit_is_in_sync() -> None:
    # Red when: a build that contains the last src/ commit is called "NOT in sync".
    line = _handoff()._build_sha_drift_line(
        last_src_commit=SRC, prod_build_sha=BUILD, main_tip=OTHER, src_commit_in_build=True
    )
    assert "in sync" in line.lower() and "not match" not in line.lower(), line
    # PARTNER: neither at the tip nor containing the last src/ commit is still the warning.
    stale = _handoff()._build_sha_drift_line(
        last_src_commit=SRC, prod_build_sha=BUILD, main_tip=OTHER, src_commit_in_build=False
    )
    assert "does not match" in stale.lower() and "overdue" in stale.lower(), stale


def test_the_ancestor_helper_reads_git(tmp_path: Path) -> None:
    # Red when: the handoff's "does this build contain that commit" question is not answered by
    # git's ancestry (an older commit is in a newer one; a newer one is not in an older one).
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet", "-b", "main")
    shas = []
    for n in range(2):
        (repo / "f.txt").write_text(f"{n}\n", encoding="utf-8")
        git(repo, "add", "f.txt")
        git(repo, "commit", "--quiet", "-m", f"commit {n}")
        shas.append(git_out(repo, "rev-parse", "HEAD"))
    module = _handoff()
    assert module._is_ancestor(shas[0], shas[1], root=repo) is True
    assert module._is_ancestor(shas[1], shas[0], root=repo) is False
    assert module._is_ancestor(shas[0], "0" * 40, root=repo) is False


# ---------------------------------------------------------------------------
# 6. Guards that survived deletion with every test green.
# ---------------------------------------------------------------------------


def test_no_scoped_file_is_an_error_on_a_repo_that_has_the_cutoff(tmp_path: Path) -> None:
    # Red when: the completion check passes, or fails for another reason, on a repository that
    # has the cut-off commit but tracks no scoped file (it read nothing).
    repo = make_clone(ROOT, tmp_path / "repo")
    assert git(repo, "cat-file", "-e", f"{CUTOFF}^{{commit}}").returncode == 0
    git(repo, "rm", "-r", "-q", "--cached", "--", "docs")
    prompts = [p for p in git_out(repo, "ls-files").splitlines() if "/" not in p and "PROMPT" in p]
    if prompts:
        git(repo, "rm", "-q", "--cached", "--", *prompts)
    done = run_python(ROOT, COMPLETION_SCRIPT, "--root", str(repo))
    output = done.stdout + done.stderr
    assert done.returncode == 1, output
    assert "no scoped file is tracked here" in output, output
    assert "files_scoped=0" in output, output


def test_a_missing_cutoff_commit_is_an_error(tmp_path: Path) -> None:
    # Red when: the completion check passes a repository without the cut-off commit (a shallow
    # clone), where no line can be dated.
    repo = tmp_path / "shallow"
    (repo / "docs").mkdir(parents=True)
    git(repo, "init", "--quiet", "-b", "main")
    (repo / "docs" / "session-handoff.md").write_text("W55 merged.\n", encoding="utf-8")
    git(repo, "add", "docs")
    git(repo, "commit", "--quiet", "-m", "one scoped file")
    done = run_python(ROOT, COMPLETION_SCRIPT, "--root", str(repo))
    output = done.stdout + done.stderr
    assert done.returncode == 1, output
    assert "is not in this repository" in output and "files_scoped=1" in output, output


def test_no_fail_reports_a_mismatch_and_exits_0(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Red when: `--no-fail` (what `make handoff` uses) still exits 1 on a mismatch, or stops
    # reporting it; or the check without it stops exiting 1.
    module = load_script(ROOT, "check_board_github")
    monkeypatch.setattr(module, "open_issues", lambda: ({99999}, ""))
    assert module.main(["--no-fail"]) == 0
    assert "MISMATCH issue #99999" in capsys.readouterr().out
    assert module.main([]) == 1


class _Body(io.BytesIO):
    """A response body that records the size each read asked for."""

    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.asked: list[int | None] = []

    def read(self, size: int | None = -1, /) -> bytes:
        self.asked.append(size)
        return super().read(size)


class _Response:
    def __init__(self, body: _Body) -> None:
        self.body = body

    def __enter__(self) -> _Body:
        return self.body

    def __exit__(self, *exc: object) -> None:
        return None


def test_a_read_is_bounded_to_64_kib(monkeypatch: pytest.MonkeyPatch) -> None:
    # Red when: a /status or /ready body is read without the 65536-byte bound.
    module = _readiness()
    body = _Body(b'{"status": "ready"}')
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **k: _Response(body))
    found, error = module.fetch("http://127.0.0.1:9/ready")
    assert found == {"status": "ready"} and error == "", (found, error)
    assert body.asked == [65536], body.asked


def test_an_http_error_body_is_read_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    # Red when: /ready's 503 answer (a JSON body) is dropped instead of read, or read unbounded.
    module = _readiness()
    body = _Body(b'{"status": "not_ready"}')

    def raise_503(*_args: object, **_kwargs: object) -> None:
        raise urllib.error.HTTPError("http://127.0.0.1:9/ready", 503, "busy", Message(), body)

    monkeypatch.setattr(module.urllib.request, "urlopen", raise_503)
    found, error = module.fetch("http://127.0.0.1:9/ready")
    assert found == {"status": "not_ready"} and error == "", (found, error)
    assert body.asked == [65536], body.asked


NEEDLE = "def the_needle_under_test("


def _present_repo(tmp_path: Path) -> dict[str, str]:
    repo = tmp_path
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "--quiet", "-b", "main")
    (repo / "filler.txt").write_text("nothing to see\n", encoding="utf-8")
    git(repo, "add", "filler.txt")
    shas = {}
    for name, text in (("in_comment", f"# {NEEDLE}): pass\n"), ("in_code", f"{NEEDLE}): pass\n")):
        (repo / "target.py").write_text(text, encoding="utf-8")
        git(repo, "add", "target.py")
        git(repo, "commit", "--quiet", "-m", name)
        shas[name] = git_out(repo, "rev-parse", "HEAD")
    return shas


def _present_board(sha: str, evidence: str) -> str:
    fillers = "".join(
        f"| W{100 + i} | filler | PENDING | `ABSENT filler.txt :: a-needle-that-is-absent-{i}` "
        "| — | — |\n"
        for i in range(8)
    )
    return (
        "# fixture board\n\n"
        f"Verified at: `{sha}`\n\n"
        "The board holds **9** rows, **0** of them unpinned.\n\n"
        "| ID | Item | State | Evidence | Issue | Depends on |\n"
        "|----|------|-------|----------|-------|------------|\n"
        f"{fillers}| W60 | the row under test | PENDING | `{evidence}` | — | — |\n"
    )


def test_a_present_at_needle_is_read_as_code_at_its_commit(tmp_path: Path) -> None:
    # Red when: the at-commit read stops stripping comments, so a needle that was only in a
    # comment at that commit counts as present.
    shas = _present_repo(tmp_path)
    checker = load_script(ROOT, "check_open_work")
    board = tmp_path / rel("docs", "65-open-work.md")
    board.parent.mkdir(parents=True, exist_ok=True)

    def failures(at: str) -> list[str]:
        evidence = f"PRESENT@{shas[at]} target.py :: {NEEDLE}"
        board.write_text(_present_board(shas["in_code"], evidence), encoding="utf-8")
        found, _report = checker.check_all(tmp_path, 10**9)
        return [f for f in found if "W60" in f]

    assert failures("in_code") == [], "the partner: a needle in code at its commit is accepted"
    assert NEEDLE in git_out(tmp_path, "show", f"{shas['in_comment']}:target.py")
    assert len(failures("in_comment")) == 1
