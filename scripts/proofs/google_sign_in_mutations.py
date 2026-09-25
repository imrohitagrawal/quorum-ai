"""Re-runnable mutation proof for W7's first pull request (ADR-0130).

Each mutation breaks one sign-in check (the state compare, a claim check, the
session rotation, the time bound, the redaction, ...) and runs the test named
for it. Mutations 01-36 are the first build's; 37-45 are review round 1's
fixes (the access-log formatter, no-store on a signed-in page, sign-out with
sign-in off, pending-state purging, claim types, the redirect host), 46-47
the access-log fix's fallback branches.

Applies each mutation by exact text (every anchor must be unique, or the
proof is reported invalid), clears ``__pycache__``, runs the named test,
restores the file from a copy and checks it with ``cmp``. Never uses
``git checkout``. It edits the tree it lives in, so run it in a
``git archive HEAD`` copy when anything else is reading the working tree
(AGENTS.md rule 12b):

    uv run python scripts/proofs/google_sign_in_mutations.py

Exit 0 only when every mutation is KILLED and every restore is byte-identical.
A red baseline aborts with exit 2: a kill count against it proves nothing.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
FILES = {
    "signin": ROOT / "src" / "product_app" / "google_signin.py",
    "auth": ROOT / "src" / "product_app" / "auth.py",
    "store": ROOT / "src" / "product_app" / "session_store.py",
    "logging": ROOT / "src" / "product_app" / "logging_config.py",
    "main": ROOT / "src" / "product_app" / "main.py",
}
BASELINE_TESTS = [
    "tests/integration/test_google_sign_in.py",
    "tests/unit/test_google_signin_units.py",
    "tests/integration/test_browser_ui_advanced_contract.py",
]

#: (label, file key, [(exact text, replacement), ...], the test that must go red).
_T = "tests/integration/test_google_sign_in.py"
_U = "tests/unit/test_google_signin_units.py"

MUTATIONS: list[tuple[str, str, list[tuple[str, str]], str]] = [
    (
        "01 state compare removed",
        "signin",
        [
            (
                (
                    "if not secrets.compare_digest(presented_state.encode(),"
                    " pending.state.encode()):"
                ),
                "if False:",
            ),
        ],
        _T + "::" + "test_a_callback_without_this_sessions_fresh_state_is_refused",
    ),
    (
        "02 state not deleted on use",
        "signin",
        [
            (
                (
                    "            pending = self._entries.pop(session_id, Non"
                    "e)\n"
                    "            # Every other"
                ),
                ("            pending = self._entries.get(session_id)\n            # Every other"),
            ),
        ],
        _T + "::" + "test_a_callback_without_this_sessions_fresh_state_is_refused",
    ),
    (
        "03 expiry not checked",
        "signin",
        [
            (
                ("if pending is None or now - pending.started_at > SIGN_IN_STATE_TTL:"),
                "if pending is None:",
            ),
        ],
        _T + "::" + "test_a_callback_without_this_sessions_fresh_state_is_refused",
    ),
    (
        "04 iss check removed",
        "signin",
        [
            (
                ("    if not isinstance(issuer, str) or issuer not in GOOGLE_ISSUERS:"),
                "    if not isinstance(issuer, str):",
            ),
        ],
        "tests/integration/test_google_sign_in.py",
    ),
    (
        "05 aud check removed",
        "signin",
        [
            ('if not client_id or claims.get("aud") != client_id:', "if not client_id:"),
        ],
        "tests/integration/test_google_sign_in.py",
    ),
    (
        "06 azp check removed",
        "signin",
        [
            ('if "azp" in claims and claims.get("azp") != client_id:', "if False:"),
        ],
        "tests/integration/test_google_sign_in.py",
    ),
    (
        "07 exp check removed",
        "signin",
        [
            ("if expires is None or expires <= now:", "if False:"),
        ],
        "tests/integration/test_google_sign_in.py",
    ),
    (
        "08 exp boundary < instead of <=",
        "signin",
        [
            ("if expires is None or expires <= now:", "if expires is None or expires < now:"),
        ],
        _T + "::" + "test_a_token_expiring_at_this_very_second_is_expired",
    ),
    (
        "09 iat check removed",
        "signin",
        [
            (
                ("if issued is None or issued > now + ID_TOKEN_CLOCK_SKEW_S or issued > expires:"),
                "if issued is None:",
            ),
        ],
        "tests/integration/test_google_sign_in.py",
    ),
    (
        "10 email_verified check removed",
        "signin",
        [
            ('if claims.get("email_verified") is not True:', "if False:"),
        ],
        "tests/integration/test_google_sign_in.py",
    ),
    (
        "11 email_verified truthy",
        "signin",
        [
            (
                'if claims.get("email_verified") is not True:',
                'if not claims.get("email_verified"):',
            ),
        ],
        "tests/integration/test_google_sign_in.py",
    ),
    (
        "12 sub check removed",
        "signin",
        [
            (
                "if not isinstance(subject, str) or not subject.strip():",
                "if not isinstance(subject, str):",
            ),
        ],
        "tests/integration/test_google_sign_in.py",
    ),
    (
        "13 email check removed",
        "signin",
        [
            ("if not isinstance(email, str) or not email.strip():", "if False:"),
        ],
        "tests/integration/test_google_sign_in.py",
    ),
    (
        "14 old session not revoked",
        "auth",
        [
            (
                (
                    "    session_repository.revoke(previous_session_id)\n"
                    "    session = session_repository.create(account_id=acco"
                    "unt_id)"
                ),
                ("    session = session_repository.create(account_id=account_id)"),
            ),
        ],
        _T + "::" + "test_the_session_id_from_before_sign_in_stops_working",
    ),
    (
        "15 rotation reuses old id (rebind)",
        "auth",
        [
            (
                (
                    "    session_repository.revoke(previous_session_id)\n"
                    "    session = session_repository.create(account_id=acco"
                    "unt_id)"
                ),
                (
                    "    session = session_repository.get(previous_session_i"
                    "d)\n"
                    "    session.account_id = account_id"
                ),
            ),
        ],
        _T + "::" + "test_the_session_id_from_before_sign_in_stops_working",
    ),
    (
        "16 token response logged",
        "signin",
        [
            (
                ('    id_token = payload.get("id_token") if isinstance(payload, dict) else None'),
                (
                    '    _log.info("token response %s", payload)\n'
                    '    id_token = payload.get("id_token") if isinstance(pa'
                    "yload, dict) else None"
                ),
            ),
        ],
        _T + "::" + "test_no_google_token_reaches_the_database_or_the_logs",
    ),
    (
        "17 id token stored as email",
        "signin",
        [
            (
                ("google_sub=identity.google_sub, email=identity.email, now="),
                (
                    "google_sub=identity.google_sub, email=identity.email + "
                    "'|'+str(len(pending.code_verifier))+pending.code_verifi"
                    "er, now="
                ),
            ),
        ],
        _T + "::" + "test_no_google_token_reaches_the_database_or_the_logs",
    ),
    (
        "18 no total time bound",
        "signin",
        [
            ("    worker.join(total_seconds)\n", "    worker.join()\n"),
        ],
        _T + "::" + "test_a_token_endpoint_that_dribbles_cannot_hold_the_callback",
    ),
    (
        "19 sign-in consumes a mint",
        "auth",
        [
            (
                (
                    "    session_repository.revoke(previous_session_id)\n"
                    "    session = session_repository.create(account_id=acco"
                    "unt_id)"
                ),
                (
                    "    session_repository.revoke(previous_session_id)\n"
                    "    return issue_session(account_id=account_id, client_"
                    "ip='testclient')"
                ),
            ),
        ],
        _T + "::" + "test_sign_in_neither_spends_nor_is_refused_by_the_per_ip_mint_cap",
    ),
    (
        "20 partial config counts as on",
        "signin",
        [
            (
                ("    if not all(values) or not _redirect_uri_is_usable(values[2]):"),
                "    if not _redirect_uri_is_usable(values[2]):",
            ),
        ],
        _T + "::" + "test_sign_in_is_off_when_any_one_setting_is_missing",
    ),
    (
        "21 redirect path unchecked",
        "signin",
        [
            (
                (
                    "    return parts.path == CALLBACK_PATH and not parts.qu"
                    "ery and not parts.fragment"
                ),
                "    return not parts.query and not parts.fragment",
            ),
        ],
        _T + "::" + "test_a_malformed_redirect_uri_keeps_sign_in_off",
    ),
    (
        "22 CSRF not enforced on start/sign-out",
        "signin",
        [
            (
                (
                    "    session = auth.require_session(request)\n"
                    "    auth.enforce_csrf(request, session)\n"
                ),
                "    session = auth.require_session(request)\n",
            ),
        ],
        "tests/integration/test_google_sign_in.py",
    ),
    (
        "23 accounts DDL unguarded in _SCHEMA",
        "store",
        [
            (
                (
                    "            self._conn.executescript(self._SCHEMA)\n"
                    "        self._accounts_ready"
                ),
                (
                    "            self._conn.executescript(self._SCHEMA + ';'"
                    " + self._MIGRATIONS_DDL + ';' + self._ACCOUNTS_DDL + ';"
                    "')\n"
                    "        self._accounts_ready"
                ),
            ),
        ],
        _T + "::" + "test_an_old_read_only_database_still_opens_and_only_sign_in_is_unavailable",
    ),
    (
        "24 migration skipped",
        "store",
        [
            (
                ("                if applied is not None:\n                    return True\n"),
                "                return True\n",
            ),
        ],
        _T + "::" + "test_the_migration_adds_the_accounts_table_to_an_old_database",
    ),
    (
        "25 account keyed by email",
        "store",
        [
            (
                ('"SELECT account_id FROM accounts WHERE google_sub = ?", (google_sub,)'),
                ('"SELECT account_id FROM accounts WHERE email = ?", (email,)'),
            ),
        ],
        _T + "::" + "test_two_google_accounts_get_two_rows_and_a_return_visit_reuses_its_row",
    ),
    (
        "26 log redaction pattern removed",
        "logging",
        [
            (('    re.compile(r"(?<=/v1/auth/google/callback\\?)[^\\s\\"\\\\]+"),\n'), ""),
        ],
        _T + "::" + "test_the_callback_query_is_redacted_from_access_log_lines",
    ),
    (
        "27 sentry scrub removed",
        "main",
        [
            ('        request["query_string"] = "[REDACTED]"\n', "        pass\n"),
        ],
        _T + "::" + "test_sentry_events_lose_the_callback_query",
    ),
    (
        "28 email not escaped",
        "main",
        [
            ("            + escape(account.email)\n", "            + account.email\n"),
        ],
        _T + "::" + "test_the_signed_in_email_is_escaped",
    ),
    (
        "29 PKCE challenge is the plain verifier",
        "signin",
        [
            (
                (
                    '    digest = hashlib.sha256(code_verifier.encode("ascii'
                    '")).digest()\n'
                    "    return base64.urlsafe_b64encode(digest)"
                ),
                (
                    '    digest = code_verifier.encode("ascii")\n'
                    "    return base64.urlsafe_b64encode(digest)"
                ),
            ),
        ],
        _T + "::" + "test_a_full_sign_in_exchanges_the_code_with_pkce_and_signs_the_browser_in",
    ),
    (
        "30 size bound removed",
        "signin",
        [
            ("    if len(raw) > TOKEN_RESPONSE_MAX_BYTES:\n", "    if False:\n"),
        ],
        _T + "::" + "test_an_oversized_token_response_is_refused",
    ),
    (
        "31 sign-out does not revoke",
        "signin",
        [
            (
                (
                    "    auth.session_repository.revoke(session.session_id)\n"
                    "    response = JSONResponse"
                ),
                "    response = JSONResponse",
            ),
        ],
        _T + "::" + "test_sign_out_revokes_the_session_server_side_and_deletes_nothing_else",
    ),
    (
        "32 pending not keyed by session",
        "signin",
        [
            (
                "        pending = PendingSignIn(\n",
                ("        session_id = 'shared'\n        pending = PendingSignIn(\n"),
            ),
            (
                (
                    "            pending = self._entries.pop(session_id, Non"
                    "e)\n"
                    "            # Every other"
                ),
                (
                    "            pending = self._entries.pop('shared', None)"
                    "\n"
                    "            # Every other"
                ),
            ),
        ],
        _T + "::" + "test_a_callback_without_this_sessions_fresh_state_is_refused",
    ),
    (
        "33 pending eviction removed",
        "signin",
        [
            (
                ("            while len(self._entries) >= MAX_PENDING_SIGN_INS:\n"),
                "            while False:\n",
            ),
        ],
        _U + "::" + "test_the_pending_table_drops_its_oldest_entry_when_full",
    ),
    (
        "34 token endpoint guard removed",
        "signin",
        [
            (
                ("    if not is_credential_safe(endpoint):\n        # The request body"),
                ("    if False:\n        # The request body"),
            ),
        ],
        _T + "::" + "test_a_token_endpoint_that_is_not_https_or_loopback_is_never_dialled",
    ),
    (
        "35 sign-in button id changed",
        "main",
        [
            ('<button id="sign-in-google"', '<button id="sign-in-with-google"'),
        ],
        "tests/integration/test_browser_ui_advanced_contract.py::test_workspace_html_contains_all_dom_hooks_used_by_javascript",
    ),
    (
        "36 migration failure not caught",
        "store",
        [
            (
                (
                    "        except sqlite3.Error as exc:\n"
                    "            _log.warning(\n"
                    '                "session_store: the accounts table'
                ),
                (
                    "        except ValueError as exc:\n"
                    "            _log.warning(\n"
                    '                "session_store: the accounts table'
                ),
            ),
        ],
        _T + "::" + "test_an_old_read_only_database_still_opens_and_only_sign_in_is_unavailable",
    ),
    (
        "37 the redaction factory drops record.args again",
        "logging",
        [
            (
                "            if redacted != rendered and not _redact_args_in_place(record):\n",
                "            if redacted != rendered:\n",
            ),
        ],
        _T + "::" + "test_the_callback_access_line_formats_through_uvicorns_access_formatter",
    ),
    (
        "38 a signed-in page is cacheable",
        "main",
        [
            (
                (
                    '        response.headers["Cache-Control"] = "no-store"\n'
                    "    attach_session_cookie"
                ),
                ("        pass\n    attach_session_cookie"),
            ),
        ],
        _T + "::" + "test_a_page_showing_a_signed_in_email_is_not_cached",
    ),
    (
        "39 sign-out gated on the settings again",
        "signin",
        [
            (
                ("    session = _require_cookie_session(request)\n    pending_sign_ins.discard("),
                (
                    "    _require_enabled()\n"
                    "    session = _require_cookie_session(request)\n"
                    "    pending_sign_ins.discard("
                ),
            ),
        ],
        _T + "::" + "test_a_browser_signed_in_before_sign_in_was_switched_off_can_still_sign_out",
    ),
    (
        "40 Sign out hidden once sign-in is off",
        "main",
        [
            (
                "    if account is not None:\n",
                "    if account is not None and sign_in_enabled():\n",
            ),
        ],
        _T + "::" + "test_a_browser_signed_in_before_sign_in_was_switched_off_can_still_sign_out",
    ),
    (
        "41 take() stops purging expired entries",
        "signin",
        [
            (
                (
                    "            # leaves memory (review round 1).\n"
                    "            self._purge_locked(now)\n"
                ),
                "            # leaves memory (review round 1).\n",
            ),
        ],
        _T + "::" + "test_a_take_purges_other_sessions_expired_entries",
    ),
    (
        "42 sign-out keeps the pending sign-in",
        "signin",
        [
            ("    pending_sign_ins.discard(session.session_id)\n", ""),
        ],
        _T + "::" + "test_sign_out_drops_the_sessions_pending_sign_in",
    ),
    (
        "43 iss type not checked",
        "signin",
        [
            (
                ("    if not isinstance(issuer, str) or issuer not in GOOGLE_ISSUERS:"),
                "    if issuer not in GOOGLE_ISSUERS:",
            ),
        ],
        _T + "::" + "test_a_claim_of_an_unexpected_type_fails_the_sign_in_and_never_500s",
    ),
    (
        "44 /start accepts any host",
        "signin",
        [
            (
                ("    if not on_sign_in_host(request):\n        raise"),
                ("    if False:\n        raise"),
            ),
        ],
        _T + "::" + "test_sign_in_is_offered_only_on_the_redirect_uris_host",
    ),
    (
        "45 the page offers sign-in on any host",
        "main",
        [
            (
                "    if not sign_in_enabled() or not on_sign_in_host:\n",
                "    if not sign_in_enabled():\n",
            ),
        ],
        _T + "::" + "test_sign_in_is_offered_only_on_the_redirect_uris_host",
    ),
    (
        "46 args kept even when a secret survives in the template",
        "logging",
        [("    if _redact_secrets(rendered) != rendered:\n        return False\n", "")],
        _T + "::" + "test_args_are_left_alone_when_redacting_them_is_not_enough",
    ),
    (
        "47 a failing re-format raises out of the helper",
        "logging",
        [
            (
                "    try:\n        rendered = str(record.msg) % redacted_args\n"
                "    except Exception:  # noqa: BLE001 - never let a bad %-format crash logging\n"
                "        return False\n",
                "    rendered = str(record.msg) % redacted_args\n",
            )
        ],
        _T + "::" + "test_args_are_left_alone_when_redacting_them_is_not_enough",
    ),
]


def _purge() -> None:
    """Drop stale bytecode so a mutated module is re-read, not re-used."""
    for pyc in ROOT.rglob("__pycache__"):
        shutil.rmtree(pyc, ignore_errors=True)


def _pytest(targets: list[str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    cmd = ["uv", "run", "pytest", *targets, "-x", "-q", "--no-cov", "-p", "no:cacheprovider"]
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env)


def _last_line(run: subprocess.CompletedProcess[str]) -> str:
    lines = [ln for ln in run.stdout.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else "(no output)"


def main() -> int:
    _purge()
    base = _pytest(BASELINE_TESTS)
    print(f"BASELINE: {_last_line(base)}")
    if base.returncode != 0:
        print("BASELINE IS RED — a kill count against a red baseline proves nothing.")
        return 2
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        backups = {k: pathlib.Path(tmp) / f"{k}.bak" for k in FILES}
        for key, path in FILES.items():
            shutil.copy2(path, backups[key])
        for label, key, edits, target in MUTATIONS:
            text = backups[key].read_text()
            counts = [text.count(old) for old, _ in edits]
            if counts != [1] * len(edits):
                print(f"  {label:58} ANCHOR NOT UNIQUE {counts} — proof invalid")
                failures += 1
                continue
            for old, new in edits:
                text = text.replace(old, new)
            FILES[key].write_text(text)
            _purge()
            run = _pytest([target])
            shutil.copy2(backups[key], FILES[key])
            _purge()
            same = subprocess.run(["cmp", "-s", str(FILES[key]), str(backups[key])]).returncode
            # pytest exits 1 when a test failed; 2-5 mean it never ran the test
            # (collection or usage error), which proves nothing either way.
            status = {0: "SURVIVED", 1: "KILLED  "}.get(
                run.returncode, f"INVALID rc={run.returncode}"
            )
            restore = "ok" if same == 0 else "DIRTY"
            print(f"  {label:58} {status} restore={restore} | {_last_line(run)}")
            if run.returncode != 1 or same != 0:
                failures += 1
    print(f"\n{len(MUTATIONS) - failures} killed / {len(MUTATIONS)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
