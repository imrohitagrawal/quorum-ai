"""Re-runnable mutation proof for W7's account-deletion pull request (ADR-0136).

Each mutation breaks one part of deleting an account (refusing its sessions,
the restore re-check, each row the transaction removes, the keyed-hash
account id, the typed-email check, CSRF, the cookie, the operator rows, the
carry-over links, and what keeps the time before a deletion out once the
same Google account signs in again) and runs the deletion tests.

Applies each mutation by exact text (the anchor must occur the stated number
of times, or the proof is reported invalid), clears ``__pycache__``, runs the
tests, restores the file from a copy and checks it with ``cmp``. Never uses
``git checkout``. It edits the tree it lives in, so run it in a
``git archive HEAD`` copy when anything else is reading the working tree
(AGENTS.md rule 12b):

    uv run python scripts/proofs/w7_deletion_mutations.py

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
AD = "src/product_app/account_deletion.py"
AU = "src/product_app/auth.py"
RH = "src/product_app/run_history_store.py"
GS = "src/product_app/google_signin.py"
QO = "src/product_app/query_run_orchestration.py"
M = "src/product_app/main.py"
C = "src/product_app/config.py"

#: (file, anchor, replacement, expected count, which occurrence)
MUTATIONS: list[tuple[str, str, str, int, int]] = [
    (
        AU,
        "            self._deleted_accounts[account_id] = (now + SESSION_TTL, now)\n",
        "",
        1,
        0,
    ),
    (
        AU,
        "                self._sessions.pop(session_id, None)\n\n    def account_was_deleted",
        "                pass\n\n    def account_was_deleted",
        1,
        0,
    ),
    (
        AU,
        "            if self.account_was_deleted("
        "session.account_id, created_before=session.created_at):\n",
        "            if False:\n",
        1,
        0,
    ),
    (
        AU,
        "            if mark is None or mark[0] <= datetime.now(UTC):",
        "            if mark is None:",
        1,
        0,
    ),
    (ST, '"DELETE FROM history WHERE account_id = ?", (key,)', '"SELECT ?", (key,)', 1, 0),
    (ST, '"DELETE FROM sessions WHERE account_id = ?", (key,)', '"SELECT ?", (key,)', 1, 0),
    (ST, '"DELETE FROM accounts WHERE account_id = ?", (key,)', '"SELECT ?", (key,)', 1, 0),
    (
        ST,
        "account_id = account_id_for(google_sub, key=_account_key())",
        "account_id = UUID(bytes=secrets.token_bytes(16), version=4)",
        1,
        0,
    ),
    (
        ST,
        'digest = hmac.new(key, b"w7-account:"',
        'digest = hmac.new(b"fixed", b"w7-account:"',
        1,
        0,
    ),
    (
        AD,
        "    if body.confirm_email.strip().casefold() != account.email.strip().casefold():",
        "    if body.confirm_email != account.email:",
        1,
        0,
    ),
    (AD, "    auth.enforce_csrf(request, session)\n", "", 1, 0),
    (AD, "    if account is None:\n", "    if False:\n", 1, 0),
    (AD, "    auth.session_repository.revoke_account(account_id)\n", "", 1, 0),
    (AD, "    run_history_store.forget_account(str(account_id))\n", "", 1, 0),
    (AD, "    account_history.forget_account(account_id)\n", "", 1, 0),
    (AD, "    auth.clear_session_cookie(response)\n", "", 1, 0),
    (
        AD,
        "    if store is None or not store.delete_account(account_id):",
        "    if store is None or (store.delete_account(account_id) and False):",
        1,
        0,
    ),
    (
        RH,
        '"UPDATE runs SET account_id = NULL WHERE account_id = ?"',
        '"UPDATE runs SET account_id = account_id WHERE account_id = ?"',
        1,
        0,
    ),
    (
        QO,
        "            account_id=None if query_run.account_deleted else str(query_run.account_id),",
        "            account_id=str(query_run.account_id),",
        1,
        0,
    ),
    # Review round 1 (2026-09-27): the id comes back on signing in again.
    (
        AU,
        "            return created_before is None or created_before < mark[1]",
        "            return True",
        1,
        0,
    ),
    (AU, "                del self._deleted_accounts[lapsed]\n", "                pass\n", 1, 0),
    (QO, "                query_run.account_deleted = True\n", "                pass\n", 1, 0),
    (
        QO,
        " or query_run.account_id != account_id or query_run.account_deleted:",
        " or query_run.account_id != account_id:",
        1,
        0,
    ),
    (
        QO,
        "                    and not query_run.is_terminal\n"
        "                    and not query_run.account_deleted\n",
        "                    and not query_run.is_terminal\n",
        1,
        0,
    ),
    (
        QO,
        "                query_run.account_id == account_id and not query_run.is_terminal\n"
        "                for query_run in self._query_runs.values()",
        "                query_run.account_id == account_id and not query_run.is_terminal\n"
        "                and not query_run.account_deleted\n"
        "                for query_run in self._query_runs.values()",
        1,
        0,
    ),
    (
        AH,
        "        if not query_run.is_terminal or query_run.account_deleted:",
        "        if not query_run.is_terminal:",
        1,
        0,
    ),
    (
        ST,
        '"WHERE EXISTS (SELECT 1 FROM accounts WHERE account_id = ?) "',
        '"WHERE ? IS NOT NULL "',
        1,
        0,
    ),
    (GS, "    if store.account_for(account_id) is None:\n", "    if False:\n", 1, 0),
    (AD, "    query_run_repository.detach_account(account_id)\n", "", 1, 0),
    (AD, " or session.legacy else", " else", 1, 0),
    (
        AD,
        '"Sign in again to try once more."',
        '"Please try again."',
        1,
        0,
    ),
]

TESTS = [
    "tests/integration/test_account_deletion.py",
    "tests/integration/test_account_history_flow.py",
    "tests/integration/test_google_sign_in.py",
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
