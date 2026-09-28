"""Re-runnable mutation proof for W7 part 3's first pull request (ADR-0137):
sign out everywhere, sign-in events, and the sign-in start limit.

Each mutation breaks one guard (the cutoff in memory and on disk, the rows
it deletes, the re-check before a charge, the events and their keep rules,
the start limit) and runs the session-safety tests. Same harness as
``w7_deletion_mutations.py``: exact anchors with counted occurrences,
``__pycache__`` cleared, the file restored from a copy and compared with
``cmp``, a red baseline refused. Run it in a ``git archive HEAD`` copy when
anything else reads the working tree:

    uv run python scripts/proofs/w7_session_safety_mutations.py
"""

from __future__ import annotations

import filecmp
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
AU = "src/product_app/auth.py"
ST = "src/product_app/session_store.py"
GS = "src/product_app/google_signin.py"

#: (file, anchor, replacement, expected count, which occurrence)
MUTATIONS: list[tuple[str, str, str, int, int]] = [
    # The cutoff in memory: recorded, never lowered, cached sessions
    # dropped, lapsed cutoffs pruned (and only those).
    (
        AU,
        "            self._valid_after[account_id] = cutoff if current is None"
        " else max(current, cutoff)\n",
        "",
        1,
        0,
    ),
    (
        AU,
        "            self._valid_after[account_id] = cutoff if current is None"
        " else max(current, cutoff)\n",
        "            self._valid_after[account_id] = cutoff\n",
        1,
        0,
    ),
    (
        AU,
        "                if session.account_id == account_id and session.created_at <= cutoff\n"
        "            ]:\n"
        "                self._sessions.pop(session_id, None)",
        "                if session.account_id == account_id and session.created_at <= cutoff\n"
        "            ]:\n"
        "                pass",
        1,
        0,
    ),
    (AU, "                del self._valid_after[lapsed]\n", "                pass\n", 1, 0),
    (AU, "if c + SESSION_TTL <= now]:", "if c <= now]:", 1, 0),
    # The cutoff on disk, read at restore; a failed read refuses.
    (
        AU,
        "        if not read or (cutoff is not None and stored.created_at <= cutoff):",
        "        if not read:",
        1,
        0,
    ),
    (
        AU,
        "        if not read or (cutoff is not None and stored.created_at <= cutoff):",
        "        if cutoff is not None and stored.created_at <= cutoff:",
        1,
        0,
    ),
    (
        AU,
        "            if self.account_was_deleted(session.account_id)"
        " or self._before_cutoff_locked(",
        "            if self.account_was_deleted(session.account_id) or False and (",
        1,
        0,
    ),
    # A request already past its session check is refused before a charge.
    (
        AU,
        "    if session_repository.get(session.session_id) is None:\n        raise",
        "    if False:\n        raise",
        1,
        0,
    ),
    # The store: the cutoff (never lowered) and the rows, in one
    # transaction; no account says so; the second pass.
    (
        ST,
        "\"MAX(COALESCE(sessions_valid_after, ''), ?) WHERE account_id = ?\",",
        '"? WHERE account_id = ?",',
        1,
        0,
    ),
    (
        ST,
        '                        "DELETE FROM sessions WHERE account_id = ? AND created_at <= ?",\n'
        "                        (key, stamp),",
        '                        "SELECT ?, ?",\n                        (key, stamp),',
        1,
        0,
    ),
    (GS, '    if outcome == "no_account":', '    if outcome == "never":', 1, 0),
    (GS, '    if outcome != "ended":', '    if outcome == "never":', 1, 0),
    (
        GS,
        '    if store.end_sessions_before(session.account_id, cutoff) != "ended":',
        "    if False:",
        1,
        0,
    ),
    (GS, "    auth.session_repository.end_sessions_of(session.account_id, cutoff)\n", "", 1, 0),
    # Events: only for an existing account; the keep rules; gone with it.
    (
        ST,
        '"SELECT ?, ?, ? WHERE EXISTS (SELECT 1 FROM accounts WHERE account_id = ?)",',
        '"SELECT ?, ?, ? WHERE ? IS NOT NULL",',
        1,
        0,
    ),
    (
        ST,
        '"DELETE FROM sign_in_events WHERE account_id = ? AND at < ?", (key, cutoff)',
        '"SELECT ?, ?", (key, cutoff)',
        1,
        0,
    ),
    (
        ST,
        '"ORDER BY at DESC, rowid DESC LIMIT ?)",',
        '"ORDER BY at DESC, rowid DESC LIMIT ? + 1000)",',
        1,
        0,
    ),
    (
        ST,
        '"ORDER BY at DESC, rowid DESC LIMIT ?)",',
        '"ORDER BY at ASC, rowid ASC LIMIT ?)",',
        1,
        0,
    ),
    (
        ST,
        '"DELETE FROM sign_in_events WHERE account_id = ?", (key,)',
        '"SELECT ?", (key,)',
        1,
        0,
    ),
    (GS, '    _record_event(account_id, "signed_in")\n', "", 1, 0),
    (GS, '        _record_event(session.account_id, "signed_out")\n', "        pass\n", 1, 0),
    (GS, '    _record_event(session.account_id, "signed_out_everywhere")\n', "", 1, 0),
    # The response is not cached.
    (
        GS,
        "    response = JSONResponse(SignOutResponse(signed_out=True).model_dump())\n"
        '    response.headers["Cache-Control"] = "no-store"\n',
        "    response = JSONResponse(SignOutResponse(signed_out=True).model_dump())\n",
        1,
        0,
    ),
    # The start limit: on, per address, 60 s Retry-After.
    (
        GS,
        "    if not sign_in_start_limiter.allow(",
        "    if False and not sign_in_start_limiter.allow(",
        1,
        0,
    ),
    (GS, 'ip=auth.client_ip_of(request) or "unknown"', 'ip="everyone"', 1, 0),
    (
        GS,
        "str(math.ceil(60 / settings.sign_in_starts_per_address_per_minute))",
        '"1"',
        1,
        0,
    ),
]

TESTS = [
    "tests/integration/test_session_safety.py",
    "tests/integration/test_google_sign_in.py",
    "tests/integration/test_account_deletion.py",
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
