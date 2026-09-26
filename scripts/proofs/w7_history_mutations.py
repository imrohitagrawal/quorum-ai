"""Re-runnable mutation proof for W7's history pull request (ADR-0135).

Each mutation breaks one part of signed-in history (a keep rule, the
carry-over, the anonymous-only guard, the no-move rule, the verdict, the
escaping, the signed-in copy, the keyboard reach) and runs the history tests.

Applies each mutation by exact text (the anchor must occur the stated number
of times, or the proof is reported invalid), clears ``__pycache__``, runs the
tests, restores the file from a copy and checks it with ``cmp``. Never uses
``git checkout``. It edits the tree it lives in, so run it in a
``git archive HEAD`` copy when anything else is reading the working tree
(AGENTS.md rule 12b):

    uv run python scripts/proofs/w7_history_mutations.py

Exit 0 only when every mutation is KILLED and every restore is byte-identical.
A red baseline aborts with exit 2: a kill count against it proves nothing.
"""

from __future__ import annotations

import filecmp
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
ST = "src/product_app/session_store.py"
AH = "src/product_app/account_history.py"
GS = "src/product_app/google_signin.py"
QO = "src/product_app/query_run_orchestration.py"
M = "src/product_app/main.py"
C = "src/product_app/config.py"

#: (file, anchor, replacement, expected count, which occurrence)
MUTATIONS: list[tuple[str, str, str, int, int]] = [
    (
        ST,
        '"DELETE FROM history WHERE account_id = ? AND completed_at < ?",',
        '"SELECT ?, ?",',
        1,
        0,
    ),
    (
        ST,
        '"DELETE FROM history WHERE account_id = ? AND query_run_id NOT IN ("',
        '"SELECT ?, ? WHERE 0 AND ? IN ("',
        1,
        0,
    ),
    (
        ST,
        '"SELECT * FROM history WHERE account_id = ? AND completed_at >= ? "',
        '"SELECT * FROM history WHERE account_id = ? AND completed_at >= ? OR 1 "',
        1,
        0,
    ),
    # Both protections at once (either alone keeps a run in its account):
    # the update re-keys the account AND no longer checks it matches.
    (
        ST,
        '"completed_at = excluded.completed_at, verdict = excluded.verdict "\n'
        '                        "WHERE history.account_id = excluded.account_id",',
        '"completed_at = excluded.completed_at, verdict = excluded.verdict, "\n'
        '                        "account_id = excluded.account_id",',
        1,
        0,
    ),
    (ST, '                verdict=row["verdict"],\n', "", 1, 0),
    (
        ST,
        '                self._warn("read history", exc)\n                return None',
        '                self._warn("read history", exc)\n                return []',
        1,
        0,
    ),
    (
        ST,
        "        self._history_ready = self._accounts_ready and self._migrate_history()",
        "        self._history_ready = self._accounts_ready",
        1,
        0,
    ),
    (
        AH,
        "    if store is not None and store.account_for(account_id) is not None:\n"
        "        return account_id\n",
        "",
        1,
        0,
    ),
    (AH, "        if link[1] < now:", "        if False:", 1, 0),
    (AH, "        return link[0]\n", "        return None\n", 1, 0),
    (
        AH,
        "        if store is None or store.account_for(anonymous_account_id) is not None:\n"
        "            return\n",
        "",
        1,
        0,
    ),
    (
        AH,
        "            _write(_entry(query_run, account_id), now)\n    except",
        "            pass\n    except",
        1,
        0,
    ),
    (AH, "        if not query_run.is_terminal:\n            return\n", "", 1, 0),
    (AH, "        question=query_run.query_text,", '        question="",', 1, 0),
    (AH, "        verdict=query_run.history_verdict,", "        verdict=None,", 1, 0),
    (
        AH,
        "    return max(QUERY_RUN_ACTIVE_TTL, "
        "timedelta(seconds=settings.quorum_run_deadline_seconds))",
        "    return QUERY_RUN_ACTIVE_TTL",
        1,
        0,
    ),
    (GS, "        account_history.carry_over(", "        (lambda **kw: None)(", 1, 0),
    (QO, "        account_history.record_finished_run(query_run)\n", "        pass\n", 1, 0),
    (QO, "        query_run.history_verdict = _history_verdict(response)\n", "", 1, 0),
    (
        QO,
        '    return f"{agreement.aligned} of {agreement.total} carried into the final answer"',
        '    return f"{agreement.aligned} of {agreement.total} models aligned"',
        1,
        0,
    ),
    (
        QO,
        "                if query_run.account_id == account_id and query_run.is_terminal\n",
        "                if query_run.account_id == account_id\n",
        1,
        0,
    ),
    (M, "            + escape(entry.question)", "            + entry.question", 1, 0),
    (M, "            + _history_html(account.account_id)\n", "", 1, 0),
    (
        M,
        "        rendered = rendered.replace(_ANONYMOUS_LEDE, escape(_signed_in_lede()), 1)",
        "        pass",
        1,
        0,
    ),
    (
        M,
        "_render_workspace_html(controls, signed_in=shows_account)",
        "_render_workspace_html(controls)",
        1,
        0,
    ),
    (
        M,
        "_render_workspace_html(controls, signed_in=shows_account)",
        "_render_workspace_html(controls, signed_in=True)",
        1,
        0,
    ),
    (M, "    if entries is None:\n", "    if False:\n", 1, 0),
    (
        M,
        '\'<div class="account-history-panel" tabindex="0" role="region" \'',
        '\'<div class="account-history-panel" role="region" \'',
        1,
        0,
    ),
    (
        C,
        "    history_keep_count: int = Field(default=5, ge=1, le=50)",
        "    history_keep_count: int = Field(default=6, ge=1, le=50)",
        1,
        0,
    ),
    (
        C,
        "    history_keep_days: int = Field(default=30, ge=1, le=365)",
        "    history_keep_days: int = Field(default=31, ge=1, le=365)",
        1,
        0,
    ),
]

TESTS = [
    "tests/unit/test_account_history_store.py",
    "tests/integration/test_account_history_flow.py",
    "tests/integration/test_google_sign_in.py",
    "tests/integration/test_workspace_html_copy.py",
]


def _clear_caches() -> None:
    for cache in ROOT.rglob("__pycache__"):
        if ".venv" not in cache.parts and "node_modules" not in cache.parts:
            shutil.rmtree(cache, ignore_errors=True)


def _run_tests() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "pytest", *TESTS, "-q", "-p", "no:cacheprovider", "--no-cov", "-x"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def main() -> int:
    _clear_caches()
    baseline = _run_tests()
    if baseline.returncode != 0:
        print("BASELINE RED: a kill count against it proves nothing")
        print(baseline.stdout[-2000:])
        return 2
    survivors = 0
    with tempfile.TemporaryDirectory() as scratch:
        for number, (name, anchor, replacement, count, which) in enumerate(MUTATIONS, 1):
            path = ROOT / name
            text = path.read_text()
            if text.count(anchor) != count:
                print(f"{number:02d} INVALID: anchor found {text.count(anchor)} times in {name}")
                return 2
            backup = pathlib.Path(scratch) / f"{number:02d}_{path.name}"
            shutil.copy(path, backup)
            index = -1
            for _ in range(which + 1):
                index = text.index(anchor, index + 1)
            path.write_text(text[:index] + replacement + text[index + len(anchor) :])
            _clear_caches()
            result = _run_tests()
            shutil.copy(backup, path)
            if not filecmp.cmp(backup, path, shallow=False):
                print(f"{number:02d} RESTORE FAILED for {name}")
                return 2
            first = next((ln for ln in result.stdout.splitlines() if ln.startswith("E ")), "")
            status = "KILLED" if result.returncode else "SURVIVED"
            survivors += result.returncode == 0
            print(f"{number:02d} {status} {name.rsplit('/', 1)[-1]}: {anchor[:60]!r} {first[:120]}")
    _clear_caches()
    print(f"{len(MUTATIONS) - survivors} of {len(MUTATIONS)} killed")
    return 0 if survivors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
