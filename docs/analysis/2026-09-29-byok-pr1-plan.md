# BYOK, first pull request (key intake and scoping) — the plan and the decisions it needs

**PROPOSED — AWAITING OWNER.** Board row W28, ADR-0121 (which stays
PROPOSED), failure modes in `docs/analysis/2026-09-23-byok-failure-modes.md`
rows 1 to 3. Nothing here is built. ADR-0121 records that the owner has not
decided delivery, and the owner's timing (2026-09-24): *"BYOK delivery
timing: after all the current features and bugs are worked upon."* The
owner's 2026-09-28 queue asks for "the BYOK draft"; this page is that draft,
as a plan, because a code draft would have to make the decisions below
first.

Figures are from a read-only map of `a7b2853` on 2026-09-29 (no network, no
paid call, fake keys only; probes not committed, so inherited).

## What the tree does today (measured by the map)

- The run reads the app key once, at start, and hard-codes the source:
  `openrouter_key = settings.openrouter_api_key or ""` and
  `credential_source = ProviderCredentialSource.APP_OWNED`
  (`grep -n "credential_source = ProviderCredentialSource" src/product_app/query_run_orchestration.py`).
  Every stage gets that copy; none re-reads it. Clearing the key after the
  first call still sent all 11 calls with it; turning the live flag off
  mid-run stopped the later stages (the flag is re-read, the key is not).
- Only answer slots record which key paid; debate, synthesis and judge
  calls record none.
- The misconfiguration check reads the app key, not the run's, so a run with
  a user key and no app key would be failed as misconfigured.
- No encryption exists in the app or its dependencies (`grep -ril
  "fernet\|cryptography\|encrypt" src pyproject.toml uv.lock`: one hit, the
  vendored Swagger UI script under `static/vendor`).
- New routes cannot be decorated functions (55 of a cap of 55).

## Decisions only the owner can make

1. **Where a user key lives.** Memory only (on the browser session; lost on
   restart or idle stop, so a returning user re-enters it), or stored at
   rest (needs encryption the tree does not have).
2. **Per session or per account.** Per account means every device of a
   signed-in user shares the key, and it survives sign-out; the failure page
   says "account", the map's measurements favour the session.
3. **Anonymous sessions:** may they hold a key at all?
4. **Sign-in:** does a key entered before sign-in carry over, or is it
   dropped (the safe default against a planted session)?
5. **Removal mid-run (EDGE-013):** the next stage stops (fail closed; calls
   already sent cannot be recalled), or the run finishes on the key it
   started with and says so on the receipt.
6. **FR-012 and AC-025/AC-026:** FR-012 is titled "Required
   bring-your-own OpenRouter key" in `docs/10` and "Optional" in `docs/17`;
   its traceability row cites test files that do not exist. What it should
   say is a requirement change.

## The smallest first pull request, once those are answered

The session's proposal: a setting off by default (routes answer 404 when
off); three routes (submit, status with the last four characters, remove),
cookie session and CSRF only, the key in the body only; one resolver that
returns today's key and source exactly while the setting is off; the
misconfiguration check reading the resolved key; which key paid recorded
truthfully; the EDGE-013 choice above, with its ADR amendment. Tests, each
with a positive partner: the key absent from every page, API response, log
line, Sentry event, model prompt, the database and the session's printout;
another session or account cannot read or spend it; each way a session ends
drops it; removal mid-run gives an exact call count; the setting off gives
today's calls. Rails, validating a key at intake, the judge's key and the
copy are later pull requests (ADR-0121).

## Two things that can go first without any BYOK decision

- The traceability rows that cite non-existent test files are false today
  (`ls` on each path named in `docs/18`); a docs-only repair does not need
  BYOK.
- The log and Sentry redaction misses some key shapes (a key glued to a
  preceding character, percent-encoded, or without its prefix; exception
  messages are not scrubbed), measured by the map with a fake
  `sk-or-v1-` key. The same patterns also guard the app's own
  key.
