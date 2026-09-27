"""Re-runnable mutation proof for W7's account-deletion pull request (ADR-0136).

Each mutation breaks one part of deleting an account (refusing its sessions,
the restore re-check, each row the transaction removes, the keyed hash, the
typed-email check, CSRF, the cookie, the operator rows, the carry-over links,
the random id per account life, and the spend key that
keeps the 24-hour envelope: its column, its backfill, and every money call
and route that must pass it) and runs the deletion and spend-key tests.

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
CO = "src/product_app/costs.py"
QR = "src/product_app/query_runs.py"

#: (file, anchor, replacement, expected count, which occurrence)
MUTATIONS: list[tuple[str, str, str, int, int]] = [
    # Deleting: refusing the account's sessions, the restore re-check, the
    # mark's lifetime, lifting it after a failed delete.
    (AU, "            self._deleted_accounts[account_id] = now + SESSION_TTL\n", "", 1, 0),
    (
        AU,
        "                self._sessions.pop(session_id, None)\n\n    def account_was_deleted",
        "                pass\n\n    def account_was_deleted",
        1,
        0,
    ),
    (
        AU,
        "            if self.account_was_deleted(session.account_id):\n                return None",
        "            if False:\n                return None",
        1,
        0,
    ),
    (
        AU,
        "            return until is not None and until > datetime.now(UTC)",
        "            return until is not None",
        1,
        0,
    ),
    (AU, "                del self._deleted_accounts[lapsed]\n", "                pass\n", 1, 0),
    (
        AU,
        "            return account_id in self._deleting or self.account_was_deleted(account_id)",
        "            return self.account_was_deleted(account_id)",
        1,
        0,
    ),
    # The spend key at the request: a deleted account refused, a read error
    # refused rather than falling back to the id.
    (
        AU,
        "    if key == session.account_id and session_repository.account_is_going(",
        "    if False and session_repository.account_is_going(",
        1,
        0,
    ),
    (AU, "    if key is None:\n        raise", "    if False:\n        raise", 1, 0),
    # The rows one transaction removes.
    (ST, '"DELETE FROM history WHERE account_id = ?", (key,)', '"SELECT ?", (key,)', 1, 0),
    (ST, '"DELETE FROM sessions WHERE account_id = ?", (key,)', '"SELECT ?", (key,)', 1, 0),
    (ST, '"DELETE FROM accounts WHERE account_id = ?", (key,)', '"SELECT ?", (key,)', 1, 0),
    # A random id per life; the spend key from the subject, under the key.
    (
        ST,
        "                        account_id = uuid4()\n",
        "                        account_id = account_id_for(google_sub, key=_account_key())\n",
        1,
        0,
    ),
    (
        ST,
        "                        subject_key = account_id_for(google_sub, key=_account_key())\n",
        "                        subject_key = account_id\n",
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
    # The migration: backfill with the id, sign-in off without it, a NULL
    # key means the id, a read error is None.
    (
        ST,
        '"UPDATE accounts SET spend_key = account_id WHERE spend_key IS NULL"',
        '"UPDATE accounts SET spend_key = NULL WHERE spend_key IS NULL"',
        1,
        0,
    ),
    (
        ST,
        "self._migrate_accounts() and self._migrate_spend_key()",
        "self._migrate_accounts() and (self._migrate_spend_key() or True)",
        1,
        0,
    ),
    (
        ST,
        '        if row is None or row["spend_key"] is None:\n            return account_id',
        "        if row is None:\n            return account_id",
        1,
        0,
    ),
    (
        ST,
        '                self._warn("read a spend key", exc)\n                return None\n'
        "        if row is None",
        '                self._warn("read a spend key", exc)\n                return account_id\n'
        "        if row is None",
        1,
        0,
    ),
    # History only for an account row, checked in the write's transaction.
    (
        ST,
        '"WHERE EXISTS (SELECT 1 FROM accounts WHERE account_id = ?) "',
        '"WHERE ? IS NOT NULL "',
        1,
        0,
    ),
    # The run keeps the key its charge opened under; every money call uses it.
    (
        QO,
        "    return query_run.account_id if query_run.spend_key is None else query_run.spend_key",
        "    return query_run.account_id",
        1,
        0,
    ),
    (
        QO,
        "spend_key=account_id if spend_key is None else spend_key,",
        "spend_key=account_id,",
        1,
        0,
    ),
    (QO, "account_id=_spend_key(query_run),", "account_id=query_run.account_id,", 3, 0),
    (QO, "account_id=_spend_key(query_run),", "account_id=query_run.account_id,", 3, 1),
    (QO, "account_id=_spend_key(query_run),", "account_id=query_run.account_id,", 3, 2),
    (
        QO,
        "str(query_run.query_run_id), _spend_key(query_run), quick=",
        "str(query_run.query_run_id), query_run.account_id, quick=",
        1,
        0,
    ),
    (
        CO,
        "        meter_key = spend_key if spend_key is not None else account_id\n",
        "        meter_key = account_id\n",
        1,
        0,
    ),
    # The routes pass the key.
    (QR, "        spend_key=spend_key,\n        # WP-G2", "        # WP-G2", 1, 0),
    (
        QR,
        "        spend_key=spend_key,\n        context=payload.context,",
        "        context=payload.context,",
        1,
        0,
    ),
    (
        QR,
        "            spend_key=spend_key,\n        )\n    except ActiveQueryRunExistsError",
        "        )\n    except ActiveQueryRunExistsError",
        1,
        0,
    ),
    # A run-history row written either side of the NULLing loses the account.
    (
        QO,
        "        if session_repository.account_was_deleted(query_run.account_id):\n"
        "            run_history_store.forget_account",
        "        if False:\n            run_history_store.forget_account",
        1,
        0,
    ),
    # The endpoint and the deletion order.
    (
        AD,
        "    if body.confirm_email.strip().casefold() != account.email.strip().casefold():",
        "    if body.confirm_email != account.email:",
        1,
        0,
    ),
    (AD, "    auth.enforce_csrf(request, session)\n", "", 1, 0),
    (AD, "    if account is None:\n", "    if False:\n", 1, 0),
    (AD, " or session.legacy else", " else", 1, 0),
    (AD, "        auth.session_repository.revoke_account(account_id)\n", "", 1, 0),
    (AD, "        auth.session_repository.end_deletion(account_id)\n", "        pass\n", 1, 0),
    (AD, "    auth.session_repository.begin_deletion(account_id)\n", "", 1, 0),
    (AD, "    account_history.forget_account(account_id)\n", "", 1, 0),
    (AD, "    run_history_store.forget_account(str(account_id))\n", "", 1, 0),
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
    # The spend key is kept a day for the account's re-creation (CHG-025).
    (ST, "                    self._carry_spend_key(key)\n", "", 1, 0),
    (
        ST,
        "spend_key = subject_key if carried is None else UUID(carried[0])",
        "spend_key = subject_key",
        1,
        0,
    ),
    (ST, 'row["spend_key"] or key, (now + SPEND_KEY_CARRY)', "key, (now + SPEND_KEY_CARRY)", 1, 0),
    # Carry-over never takes a deleted account's runs, and forgets links from it.
    (
        AH,
        "        if auth.session_repository.account_is_going(anonymous_account_id):\n"
        "            return",
        "        if False:\n            return",
        1,
        0,
    ),
    (AH, "if account_id in (a, target)", "if target == account_id", 1, 0),
    # Review round 2 of the re-plan, fixed in the owner-approved third round.
    (AD, "        store.delete_sessions_of(account_id)\n", "", 1, 0),
    (
        AU,
        "            if left > 0:\n                self._deleting[account_id] = left\n"
        "            else:\n                self._deleting.pop(account_id, None)",
        "            self._deleting.pop(account_id, None)",
        1,
        0,
    ),
    (
        ST,
        "        if row is None:\n            return\n        subject_key",
        "        subject_key",
        1,
        0,
    ),
    (
        AD,
        "        auth.session_repository.revoke_account(account_id)\n        # Once refused",
        "        # Once refused",
        1,
        0,
    ),
    (
        ST,
        "                    self._purge_lapsed_carry()\n                    if row is None:",
        "                    if row is None:",
        1,
        0,
    ),
    (
        ST,
        "                    try:\n                        self._purge_lapsed_carry()\n",
        "                    try:\n                        pass\n",
        1,
        0,
    ),
    (
        ST,
        "                    self._conn.execute(self._SPEND_KEY_CARRY_DDL)\n"
        "                    # Housekeeping",
        "                    # Housekeeping",
        1,
        0,
    ),
    (
        AU,
        "    if key == session.account_id and session_repository.account_is_going(",
        "    if session_repository.account_is_going(",
        1,
        0,
    ),
    # Pinned after the final review: the refusal comes before the second
    # pass, and a returning sign-in purges lapsed pointers too.
    (
        AD,
        "        auth.session_repository.revoke_account(account_id)\n"
        "        # Once refused, no session of the account is written again; a row\n"
        "        # another device wrote back just before the refusal goes now.\n"
        "        store.delete_sessions_of(account_id)\n",
        "        store.delete_sessions_of(account_id)\n"
        "        auth.session_repository.revoke_account(account_id)\n",
        1,
        0,
    ),
    (
        ST,
        "                    self._purge_lapsed_carry()\n                    if row is None:\n",
        "                    if row is None:\n                        self._purge_lapsed_carry()\n",
        1,
        0,
    ),
    # A sign-in finishing during the delete revokes its own session.
    (GS, "    if store.account_for(account_id) is None:\n", "    if False:\n", 1, 0),
]

TESTS = [
    "tests/integration/test_account_deletion.py",
    "tests/integration/test_spend_key.py",
    "tests/integration/test_account_history_flow.py",
    "tests/integration/test_google_sign_in.py",
    "tests/unit/test_account_history_store.py",
    "tests/unit/test_account_delete_message.py",
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
