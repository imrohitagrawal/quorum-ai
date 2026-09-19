"""Live-state reporting in `scripts/session_handoff.py` (issue #134).

`docs/session-handoff.md` used to describe its OWN structure (skill route,
git status, blocking gates) but never the numbers a handoff document has
historically carried by hand -- prod build_sha, pytest count, open issue
count, unmerged branches. Those went stale the moment they were typed,
because nothing re-derived them (#134's own example: a handoff said "expect
main `2bba0d1`"; the merge that recorded it moved the tip to `c1d20f8`, wrong
on arrival).

This file tests the pure formatting/parsing functions that turn raw
git/gh/HTTP output into the "Live state" section, so a handoff never has to
quote a number by hand again -- it points at `make handoff` instead.

What turns each test red: reverting `session_handoff.py` to a version
without the corresponding function (or with its comparison/parsing logic
deleted) raises `AttributeError` or produces the wrong string.
"""

from __future__ import annotations

import contextlib
import http.server
import importlib.util
import json
import socket
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "session_handoff_live", REPO_ROOT / "scripts" / "session_handoff.py"
)
assert _spec is not None and _spec.loader is not None
session_handoff = importlib.util.module_from_spec(_spec)
sys.modules["session_handoff_live"] = session_handoff
_spec.loader.exec_module(session_handoff)


# ---------------------------------------------------------------------------
# _build_sha_drift_line: compares production's /status.build_sha against the
# last commit that touched src/, without a network call -- pure comparison.
# ---------------------------------------------------------------------------


def test_build_sha_drift_line_reports_in_sync_on_matching_sha() -> None:
    line = session_handoff._build_sha_drift_line(
        last_src_commit="abc1234567890",
        prod_build_sha="abc1234567890",
    )
    assert "in sync" in line.lower()
    assert "abc1234" in line


def test_build_sha_drift_line_reports_drift_on_mismatched_sha() -> None:
    line = session_handoff._build_sha_drift_line(
        last_src_commit="abc1234567890",
        prod_build_sha="def9999999999",
    )
    assert "does not match" in line.lower()
    assert "abc1234" in line
    assert "def9999" in line


def test_build_sha_drift_line_flags_unreachable_production() -> None:
    line = session_handoff._build_sha_drift_line(
        last_src_commit="abc1234567890",
        prod_build_sha=None,
    )
    assert "unavailable" in line.lower()
    assert "abc1234" in line


def test_build_sha_drift_line_flags_unreadable_local_commit() -> None:
    line = session_handoff._build_sha_drift_line(
        last_src_commit=None,
        prod_build_sha="def9999999999",
    )
    assert "unavailable" in line.lower()
    assert "def9999" in line


def test_build_sha_drift_line_handles_both_missing() -> None:
    line = session_handoff._build_sha_drift_line(last_src_commit=None, prod_build_sha=None)
    assert "unavailable" in line.lower()


# ---------------------------------------------------------------------------
# _parse_pytest_collected_count: turns pytest --collect-only -q output into a
# short reportable count, without ever executing a test.
# ---------------------------------------------------------------------------


def test_parse_pytest_collected_count_basic_summary_line() -> None:
    # Deliberately not a real repo path (would trip
    # tests/unit/test_cited_paths_resolve.py's citation-existence check) --
    # this is sample pytest collection output, not a claim about the tree.
    raw = (
        "test_example_module.py::test_a\ntest_example_module.py::test_b\n"
        "\n2913 tests collected in 2.78s\n"
    )
    assert session_handoff._parse_pytest_collected_count(raw) == "2913"


def test_parse_pytest_collected_count_reports_errors_too() -> None:
    raw = "test_example_module.py::test_a\n\n10 tests collected, 2 errors in 1.02s\n"
    result = session_handoff._parse_pytest_collected_count(raw)
    assert "10" in result
    assert "2 error" in result


def test_parse_pytest_collected_count_unparseable_output_is_unavailable() -> None:
    result = session_handoff._parse_pytest_collected_count("ImportError: no module named foo\n")
    assert "unavailable" in result.lower()


def test_parse_pytest_collected_count_empty_output_is_unavailable() -> None:
    assert "unavailable" in session_handoff._parse_pytest_collected_count("").lower()


# ---------------------------------------------------------------------------
# _e2e_lane_counts: counts spec files per e2e lane directory from the tree,
# so this number can never drift the way AGENTS.md's own "twelve" -> "17"
# miscount did (rule: "Keep the number a digit").
# ---------------------------------------------------------------------------


def test_e2e_lane_counts_counts_spec_files_per_directory(tmp_path: Path) -> None:
    e2e_tests = tmp_path / "e2e" / "tests"
    (e2e_tests / "invariants").mkdir(parents=True)
    (e2e_tests / "ops").mkdir(parents=True)
    (e2e_tests / "degraded").mkdir(parents=True)
    for i in range(3):
        (e2e_tests / "invariants" / f"spec{i}.spec.ts").write_text("x", encoding="utf-8")
    (e2e_tests / "ops" / "one.spec.ts").write_text("x", encoding="utf-8")
    # Non-spec files (helpers, fixtures) must not be counted.
    (e2e_tests / "invariants" / "helper.ts").write_text("x", encoding="utf-8")

    counts = session_handoff._e2e_lane_counts(e2e_tests)

    assert counts["invariants"] == 3
    assert counts["ops"] == 1
    assert counts["degraded"] == 0


def test_e2e_lane_counts_missing_directory_reports_zero(tmp_path: Path) -> None:
    e2e_tests = tmp_path / "e2e" / "tests"
    e2e_tests.mkdir(parents=True)

    counts = session_handoff._e2e_lane_counts(e2e_tests)

    assert counts["invariants"] == 0


# ---------------------------------------------------------------------------
# _parse_unmerged_branches: cleans `git branch -r --no-merged origin/main`
# output down to a reportable list, excluding the base ref itself and the
# `HEAD -> ...` pointer line git prints alongside real branches.
# ---------------------------------------------------------------------------


def test_parse_unmerged_branches_strips_origin_prefix() -> None:
    raw = "  origin/fix/p1-313-log-redaction\n  origin/fix/p8-224\n"
    result = session_handoff._parse_unmerged_branches(raw)
    assert result == ["fix/p1-313-log-redaction", "fix/p8-224"]


def test_parse_unmerged_branches_excludes_head_pointer_line() -> None:
    raw = "  origin/HEAD -> origin/main\n  origin/fix/p8-224\n"
    result = session_handoff._parse_unmerged_branches(raw)
    assert result == ["fix/p8-224"]


def test_parse_unmerged_branches_empty_output_is_empty_list() -> None:
    assert session_handoff._parse_unmerged_branches("") == []


def test_parse_unmerged_branches_unavailable_marker_passes_through() -> None:
    result = session_handoff._parse_unmerged_branches("unavailable: git error")
    assert result == []


# ---------------------------------------------------------------------------
# run(): on a failing subprocess (e.g. pytest --collect-only hitting a
# collection error, which exits non-zero), the caller still needs the real
# output pytest already printed -- not a generic "returned non-zero exit
# status" message that throws away the collected-count summary line.
# ---------------------------------------------------------------------------


def test_run_on_called_process_error_surfaces_the_real_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    real_pytest_output = (
        "ERRORS\ntest_broken.py - ImportError: cannot import name 'x'\n"
        "5 tests collected, 1 error in 0.42s\n"
    )

    def _fake_check_output(*_args: object, **_kwargs: object) -> str:
        raise subprocess.CalledProcessError(
            returncode=2, cmd=["uv", "run", "pytest"], output=real_pytest_output
        )

    monkeypatch.setattr(subprocess, "check_output", _fake_check_output)
    result = session_handoff.run(["uv", "run", "pytest"])

    assert "5 tests collected, 1 error in 0.42s" in result


def test_run_on_called_process_error_falls_back_to_str_when_output_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    def _fake_check_output(*_args: object, **_kwargs: object) -> str:
        raise subprocess.CalledProcessError(returncode=2, cmd=["git", "status"], output="")

    monkeypatch.setattr(subprocess, "check_output", _fake_check_output)
    result = session_handoff.run(["git", "status"])

    assert "unavailable" in result.lower()
    assert "returned non-zero exit status" in result


# ---------------------------------------------------------------------------
# _gather_live_state's `last_src_commit` (#134 residual gap): it must report
# the last commit touching `src/` reachable from `origin/main`, never from
# whatever the CURRENT CHECKOUT's HEAD happens to be. AGENTS.md rule 17a
# mandates every session work from a dedicated branch/worktree, so a local
# HEAD that lags `origin/main` (not yet fast-forwarded) is the normal case,
# not an edge case -- and `git log -1 --format=%H -- src/` run against a
# stale local HEAD silently returns a stale/wrong commit.
#
# What turns this red: reverting the `last_src_commit = run([...])` line in
# `_gather_live_state()` back to `["git", "log", "-1", "--format=%H", "--",
# "src/"]` (no ref, i.e. implicit HEAD) makes it report commit A (local
# HEAD's last src/-touching commit) instead of commit B (origin/main's).
# ---------------------------------------------------------------------------


def _run_git(args: list[str], cwd: Path) -> str:
    import subprocess

    return subprocess.check_output(
        ["git", *args], cwd=cwd, stderr=subprocess.STDOUT, text=True
    ).strip()


def test_last_src_commit_reports_origin_main_not_a_stale_local_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(["init", "-q", "-b", "main"], cwd=repo)
    _run_git(["config", "user.email", "test@example.com"], cwd=repo)
    _run_git(["config", "user.name", "Test"], cwd=repo)

    src_dir = repo / "src"
    src_dir.mkdir()
    # Built via Path/join rather than a literal source-tree path string, so
    # this fixture file (which does not exist under the real repo's source
    # tree) can't be mistaken by the cited-paths gate for a citation of a
    # real repo path.
    tracked_rel = str(Path("src") / "example_module.py")

    # Commit A: the first (and, on a stale local checkout, the ONLY visible)
    # commit touching src/.
    (src_dir / "example_module.py").write_text("v1\n", encoding="utf-8")
    _run_git(["add", tracked_rel], cwd=repo)
    _run_git(["commit", "-q", "-m", "A: add tracked file under src"], cwd=repo)
    commit_a = _run_git(["rev-parse", "HEAD"], cwd=repo)

    # Commit B: a later commit touching src/, which origin/main has moved to.
    (src_dir / "example_module.py").write_text("v2\n", encoding="utf-8")
    _run_git(["add", tracked_rel], cwd=repo)
    _run_git(["commit", "-q", "-m", "B: update tracked file under src"], cwd=repo)
    commit_b = _run_git(["rev-parse", "HEAD"], cwd=repo)

    assert commit_a != commit_b

    # `refs/remotes/origin/main` points at the true tip, commit B ...
    _run_git(["update-ref", "refs/remotes/origin/main", commit_b], cwd=repo)
    # ... but the local checkout's HEAD is still parked at commit A, exactly
    # the "worktree not yet fast-forwarded to origin/main" scenario rule 17a
    # produces every session.
    _run_git(["reset", "--hard", commit_a], cwd=repo)
    assert _run_git(["rev-parse", "HEAD"], cwd=repo) == commit_a

    monkeypatch.setattr(session_handoff, "ROOT", repo)
    # Avoid network/`gh`/pytest-collection side effects from the rest of
    # `_gather_live_state()` -- this test is scoped to `last_src_commit`.
    monkeypatch.setattr(session_handoff, "_fetch_prod_build_sha", lambda: None)

    state = session_handoff._gather_live_state()

    assert state["last_src_commit"] == commit_b, (
        "last_src_commit must come from origin/main, not the local checkout's "
        f"stale HEAD (commit A = {commit_a})"
    )


# ---------------------------------------------------------------------------
# #467: _fetch_prod_build_sha, driven for real. It had never once returned a
# SHA: loading deploy_drift_check without registering it in sys.modules made
# its @dataclass raise AttributeError, and a blanket except reported that as
# "could not reach". The test above stubs this function out, so nothing
# exercised it. These drive a real HTTP server on loopback.
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _status_server(body: bytes) -> Iterator[str]:
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — the stdlib's name
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            return None

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/status"
    finally:
        server.shutdown()
        server.server_close()


def test_the_prod_probe_reads_a_real_build_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED WHEN: ``_fetch_prod_build_sha`` cannot load its fetcher — which is
    what happened on every generation before #467 (the module was never put in
    ``sys.modules``, so its dataclass raised).
    """
    # Load fresh, so a copy cached by another test cannot mask the defect.
    monkeypatch.delitem(sys.modules, "deploy_drift_check", raising=False)
    sha = "0123456789abcdef0123456789abcdef01234567"
    with _status_server(json.dumps({"build_sha": sha}).encode()) as url:
        assert session_handoff._fetch_prod_build_sha(url) == sha


def test_the_prod_probe_reports_an_unreachable_host_as_none() -> None:
    """The partner: a closed port is a genuine network failure and reads None,
    not an exception."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert session_handoff._fetch_prod_build_sha(f"http://127.0.0.1:{port}/status") is None


def test_a_broken_fetcher_fails_loudly_instead_of_reading_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED WHEN: loading the fetcher goes back inside the blanket ``except``.

    That is how #467 hid for 11 generations: a load error read as "could not
    reach". Also pins that a failed load leaves no half-built module cached.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "deploy_drift_check.py").write_text(
        'raise RuntimeError("the fetcher itself is broken")\n', encoding="utf-8"
    )
    monkeypatch.setattr(session_handoff, "ROOT", tmp_path)
    monkeypatch.delitem(sys.modules, "deploy_drift_check", raising=False)
    with pytest.raises(RuntimeError, match="the fetcher itself is broken"):
        session_handoff._fetch_prod_build_sha("http://127.0.0.1:9/status")
    assert "deploy_drift_check" not in sys.modules
