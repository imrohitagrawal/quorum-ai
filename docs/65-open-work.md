# 65 · Open work — the board

**This is the source of truth for what is open, what it is blocked by, and what
proves each row's state.** Issues on GitHub are the mirror; this file is the
original, because a gate and an offline agent can read it and cannot read `gh`.

Verified at: `e6d5300e955fb25cf1c523b3c967953f31bc04f2`

The board holds **118** rows, **62** of them unpinned.

`scripts/check_open_work.py --check` reads every row's evidence off disk and
refuses if a claim is false. It runs inside `make validate`, and
`tests/unit/test_open_work_matches_reality.py` holds its bite-proofs.

## How a row proves itself

**Nobody writes the State column. It is generated from the tree.**

Each row's **Evidence** cell states what the tree looks like **while the work is
still open**:

- `ABSENT <path> :: <needle>` — the needle is not in that file.
- `PRESENT <path> :: <needle>` — it is.
- `—` — unpinned.

`scripts/check_open_work.py` reads each needle off disk and derives the state:

| Derived | When |
|---|---|
| `PENDING` | the claim holds as written — the work is still open |
| `DONE` | its opposite holds — the work landed |
| `UNPINNED` | no needle. **An unpinned row can never read `DONE`.** |

Run `make open-work-write` (or `python3 scripts/check_open_work.py`) to
regenerate it; `--check`, inside `make validate`, refuses when the checked-in
column disagrees with the tree. **No hand writes that column**, so a row cannot
be marked done by editing its status — it moves when the tree moves. This is the
same shape as `scripts/generate_adr_index.py`: a derived fact is generated and
verified, not trusted. What it does *not* stop is an author who rewrites the
**claim** as well; see the limits below, which are asserted by a test rather
than only promised here.

Needles are matched against **code text only**: a `#` that starts a line or
follows whitespace ends that line before the search. Without that, appending
`# TODO: we still need to send "stream": True here` to `providers.py` derives
`DONE` for W1 — a comment saying the work is *not* done would have completed the
row. Verified against all 13 live needles: every one still matches after
stripping. The **whitespace guard** is the load-bearing part — a naive cut at
the first `//` would truncate W16's needle line to `URL = "https:`.

### Two designs this replaced, and why

Both were defeated by adversarial review before merge, and both are recorded
because the failure is instructive rather than embarrassing:

1. **Polarity typed by the author.** Replacing every `| PENDING |` with
   `| DONE |` left the gate green, printing "0 PENDING", with **zero bytes
   changed under `src/`**.
2. **State coupled to polarity** — `PENDING` asserts the claim, `DONE` its
   opposite. A *two*-token edit did the same thing, and a second route also
   worked: unpin a row, then mark it `DONE`.

The root cause both share: the state and the claim were **both typed by the same
hand, in the same file**. Coupling two author-controlled fields to each other
raises the number of tokens an author edits; it does not make an independent
check. ADR-0079 has the full account.

### What this cannot see

Stated narrowly, because both earlier drafts overclaimed here and were wrong:

- **An author who rewrites the Evidence cell.** The polarity word is part of
  the claim, and the author writes the claim — so changing `ABSENT` to `PRESENT`
  *and* the state together is accepted, because the derivation reads the flipped
  polarity and derives the flipped state. What derivation closes is a hand
  writing the **State column alone**, which is what carelessness looks like.
  Rewriting a claim is a visible change in the diff, and review is what reads
  it. `test_rewriting_the_evidence_claim_is_accepted_and_that_is_the_known_limit`
  asserts this limit, so nobody can quietly write down a stronger promise.
  Closing it would need the evidence text to be immutable between anchor stamps
  (`git show <anchor>:docs/65-open-work.md`); that guards against a deliberate
  author, which is not the failure this board exists to prevent.
- **Work that lands under a different name** than the needle — if streaming
  ships without that exact literal, W1 stays `PENDING` while being stale.
- **Work that lands by a different route under the same name.** W15 is pinned on
  `_bound_sniff_time` being present-and-undefined; deleting the dangling
  references flips it, but *defining* the function would not.
- **The unpinned rows.** Nothing is checked about them.
- **A row that should exist and does not.**

Review remains the primary defence — measured here, 0 of 16 `src/` defects were
caught by any automated check and 10 of 16 by adversarial review
(`docs/metrics/defect-discovery-audit.md`).

## The board

| ID | Item | State | Evidence | Issue | Depends on |
|----|------|-------|----------|-------|------------|
| W1 | Stream the provider call (was "B2") | DONE | `ABSENT src/product_app/providers.py :: "stream": True` | — | — |
| W2 | Peer critique: the answer models critique each other, two rounds (built; ships default-off) | DONE | `ABSENT src/product_app/debate.py :: def _build_peer_round(` | #290 | W1 |
| W3 | Re-set the money constants against a measured bound — ladder moved 2026-09-07 (ADR-0102); token constants remain (W13/#268) | DONE | `PRESENT src/product_app/costs.py :: DAILY_CAP_USD = Decimal("0.20")` | — | W2 |
| W4 | Variable panel size N ∈ {2,3,4} — shipped in three PRs: the backend (#493), the workspace control with the validator widening (#494), and the copy outside the run path (third PR) (ADR-0120, CHG-010, CHG-011) | DONE | `ABSENT src/product_app/model_slots.py :: Between 2 and 4 model slots are required.` | — | — (W10 done) |
| W5 | Quick-answer mode (`mode: "quick"`, one model, judge on) — complete in four PRs: backend (#506), served verdict (#507), workspace UI (#508) and the verification-only judge prompt with per-claim evidence (fourth PR) (ADR-0126, ADR-0127, ADR-0128, ADR-0129; CHG-016, CHG-017, CHG-018, CHG-019) | DONE | `ABSENT src/product_app/evaluation.py :: JUDGE_QUICK_PROMPT_ID` | — | W4 |
| W6 | A panel of one reports strong consensus | DONE | `ABSENT src/product_app/synthesis_consensus.py :: if len(stance) == 1:` | #383 | — |
| W7 | Google sign-in and logout: sign-in and sign-out (ADR-0130, CHG-020); history and retention (ADR-0135, CHG-023); account deletion and the hashed spend key (ADR-0136); then session safety (CHG-021 b to e, in two pull requests): sign out everywhere, sign-in events and a rate-limited sign-in start (#521, ADR-0137); idle expiry with a keep-active reminder (ADR-0138) | DONE | `ABSENT src/product_app/config.py :: signed_in_idle_minutes` | — | the session-safety pull request |
| W9 | Guard the moderator model overlapping a panel slot | DONE | `ABSENT src/product_app/model_slots.py :: debate_model_id` | — | — |
| W10 | Consensus certifies a mutual cluster it never checked | DONE | `PRESENT src/product_app/synthesis_consensus.py :: return sum(1 for partners in counts if partners >= 2) >= 3` | #382 | — |
| W11 | Completeness divides by answers recorded, not slots requested | DONE | `ABSENT src/product_app/query_run_orchestration.py :: requested_slot_count = len(query_run.model_slots)` | #380 | — |
| W12 | `last_live_charge_at` reports a pre-#376 row as a live charge | DONE | `ABSENT src/product_app/feedback_store.py :: _live_charge_cutover_id` | #379 | — |
| W13 | Nothing bounds a call's INPUT — **STOP** | UNPINNED | `—` | #268 | — |
| W14 | Close the 5xx possibly-billed premise with data | UNPINNED | `—` | #105 | production logs |
| W15 | `_bound_sniff_time` is referenced and does not exist | DONE | `PRESENT src/product_app/providers.py :: _bound_sniff_time` | — | — |
| W16 | The catalog fetcher hardcodes the models URL | DONE | `PRESENT src/product_app/catalog_fetcher.py :: OPENROUTER_CATALOG_URL = "https://openrouter.ai/api/v1/models"` | — | — |
| W17 | FR-004 names a model we do not ship | DONE | `PRESENT docs/10-functional-requirements.md :: deepseek/deepseek-chat-v3.1` | — | — |
| W18 | The paid call sends the API key to a configured base with no scheme guard | DONE | `PRESENT src/product_app/providers.py :: url=f"{settings.openrouter_api_base_url}/chat/completions"` | — | — |
| W19 | A provider-timeout bound fails locally and passes in CI | DONE | `ABSENT tests/unit/test_provider_call_time_budget.py :: budget_handed_to_body_read` | — | — |
| W20 | `panel_agreement()` reports "agreed" for a genuine N=1 panel | DONE | `ABSENT src/product_app/synthesis_consensus.py :: if len(stance) < 2:` | #394 | — |
| W21 | A redirect carries the API key off the guarded base | DONE | `ABSENT src/product_app/providers.py :: urlopen = CREDENTIAL_OPENER.open` | — | W18 |
| W22 | The Tavily search call sends its key to a configured base with no scheme guard | DONE | `PRESENT src/product_app/providers.py :: url=f"{settings.tavily_api_base_url.rstrip('/')}/search"` | — | — |
| W23 | The mutation gate cannot run when a changed function is covered by a schemathesis case | DONE | `ABSENT tests/conftest.py :: from tests.lazy_nodeid_selection import rewrite_lazy_case_args` | — | ADR-0117 |
|  W24 | The `:online` web-search fee is measured at $0.007 and was priced at `0.0`, so every searching run's receipt and its daily-cap booking were $0.028 light — ACTIVATED 2026-09-15 by product-owner decision (CHG-007, ADR-0113). This was defect A of issue 105, which stays open for W14 | DONE | `ABSENT src/product_app/config.py :: Field(default=0.007, ge=0, allow_inf_nan=False)` | — | —  |
| W25 | A truncated mutation run with no survivor passes, so the gate gets greener as it measures less | DONE | `ABSENT Makefile :: print("INCONCLUSIVE: no survivor` | #464 | ADR-0118 |
| W26 | The citation gate reports `.tsx`, `.mdx` and `.pyi` citations under a truncated path nobody wrote | DONE | `ABSENT tests/unit/test_cited_paths_resolve.py :: def test_a_longer_extension_is_not_truncated_to_a_listed_shorter_one` | #469 | — |
| W27 | 35 mutants of `_tavily_search` survive: the request's shape, its socket timeout and both of its log events are unasserted | DONE | `ABSENT src/product_app/providers.py :: _CONTENT_TYPE_HEADER: Final = "Content-Type"` | #465 | W25 |
| W28 | BYOK: two postures, the party paying chooses — PLANNED by the owner 2026-09-23 (CHG-011 D8), delivery not decided (ADR-0121 PROPOSED; failure modes in `docs/analysis/2026-09-23-byok-failure-modes.md`) | PENDING | `PRESENT src/product_app/query_run_orchestration.py :: credential_source = ProviderCredentialSource.APP_OWNED` | — | owner decision; the token binding (CHG-011 D9) landed 2026-09-24 (ADR-0123) |
| W29 | The judge reads the cited pages (#447, Route B): the fetcher is built behind a default-off setting (ADR-0124); the judge wiring — page text in the judge's evidence, the input reserve, the receipt row, the posture-keyed copy — is built with fetching still off (ADR-0148); switching it on is W54 | DONE | `ABSENT src/product_app/evaluation.py :: source_pages` | #447 | W54 |
| W30 | The per-network session limits count every visitor as the app's ingress address (CHG-022): take the visitor's address from what Fly's proxy forwards, measured first; the cap value stays 2 | DONE | `ABSENT src/product_app/auth.py :: def client_ip_of(` | — | — |
| W31 | An allow-list of named, dated addresses or ranges (at most /24 IPv4, /48 IPv6) exempt from the per-network session limits only, never the spend limits (CHG-022) | DONE | `ABSENT src/product_app/config.py :: session_cap_exempt_networks` | — | W30 |
| W32 | An invite link that lifts the session limit for whoever opens it, from any network, until an end date (CHG-022; planned now, not deferred) | DONE | `ABSENT src/product_app/config.py :: invite_link_signing_key` | — | W30 |
| W33 | The owner's bugs 1–10 of 2026-09-29 (root causes: `docs/analysis/2026-09-29/owner-bugs-root-causes.md`; CHG-026 h, m): Start fresh wipes the session list; the old follow-up stays in the box; the block card names the hard cap instead of the daily cap; limits unclear; no way home from a result; empty session panel; History stale (opening a row is W36); the composer lands on the question, not the models. Failing tests first, thin slices (built in three slices: A #532 ADR-0140, C #533 ADR-0141, D ADR-0142) | DONE | `ABSENT src/product_app/main.py :: "/v1/account/history",` | — | — |
| W34 | The daily session cap counts anonymous use only and must never stop anyone signing in; today, sign-out after two sign-ins on one network locks it out with "This network has reached its session limit" (CHG-026 a; ADR-0138 records the mechanism; built: ADR-0139, AC-053) | DONE | `ABSENT src/product_app/auth.py :: sign_in_only` | — | — |
| W35 | "Sign out everywhere" during a run asks first: "Yes" stops the run and signs out everywhere; "No" signs out everywhere except the running session (CHG-026 b) | UNPINNED | `—` | — | W34 |
| W36 | History keeps the full result (answers, debate, synthesis) for signed-in accounts, 20 conversations for 30 days, delete one / delete all; a row opens read-only with "Continue this conversation" (CHG-026 i; supersedes the 5-question keep of CHG-023 when built) | UNPINNED | `—` | — | W33 |
| W37 | Follow-up context: the previous question and final answer go to all four models; the next-question box opens empty with "Following up on: …" (CHG-026 g); both follow-up buttons back, the landing rename and the hint wording (CHG-027 b–d; ADR-0143) | DONE | `PRESENT src/product_app/query_runs.py :: A quick answer takes no follow-up context.` | — | W33 |
| W38 | Starter questions: six audience groups, four complete questions each, with a wider high-stakes keyword list (CHG-026 j) | UNPINNED | `—` | — | — |
| W39 | The engineering harness: agents run in a container with only the agent account's token; a signed-in real-backend journey lane with an execution-backed gate; release integrity; a slimmer AGENTS.md with tracked hooks; the skills audit (`docs/analysis/2026-09-29/NEXT-SESSION-PROMPT.md`, order steps 0–7; PROPOSED, confirm in plan mode) | UNPINNED | `—` | — | — |
| W40 | The agent account's GitHub token expires 2026-12-29 (`NEXT-SESSION-PROMPT.md`, "Agent account DONE by the owner"); rotate it before then | UNPINNED | `—` | — | W39 |
| W41 | The trust-score screenshot flake: Google Fonts sometimes serves a different version of the Geist font file (CHG-031, ADR-0149); the screenshot specs use a saved copy of Google's font stylesheet, the allowance stays 120 px, and the card's text is checked exactly (CHG-030). This replaces the 700 px of CHG-027 e | DONE | `ABSENT e2e/tests/invariants/trust-score-visual.spec.ts :: pinGoogleFonts(page)` | — | — |
| W42 | The mutation gate's clean-test step inside `./mutants/` failed on PR #528 ("Failed to run clean test"): `tests/integration/test_spend_key.py::test_a_run_is_charged_under_the_spend_key` read `0.2104 == 0.1052` because `tests/conftest.py::_reset_state` never cleared the in-memory cost ring, and mutmut runs its clean tests in set order (the local half of PR #528's report moved to W44) | DONE | `ABSENT tests/conftest.py :: costs.cost_event_recorder.clear()` | — | — |
| W43 | The empty question box is already red with "Question is required." on one plain load of `/ui` right after signing in, before anything is typed (four browser runs on 2026-09-30, W34's product review) (built in W33 slice A, ADR-0140 decision 9) | DONE | `ABSENT src/product_app/static/app.js :: const isInvalid = isEmpty && !!state.submissionAttempted;` | — | W33 |
| W44 | Locally (macOS), `make mutation-baseline` on PR #528's head recorded 201 mutants as "segfault" in `test_context_carry.py::test_non_string_context_value_is_rejected_not_crashed`, a test that passes when run directly with a mutant on; mutmut 3.6 files exit -9 (SIGKILL, e.g. its own hard CPU limit) under the same label, so the cause is unmeasured. A fork reproduction outside mutmut, run by this session's investigator on 2026-10-03, did not crash (its scripts were not kept). Do not run mutmut locally until a runaway `gcloud` process chain is explained: it filled the user's process table twice on 2026-10-03, both times while a local mutmut run was in progress; the link is not proven and nothing in this repository calls `gcloud` | UNPINNED | `—` | — | W42 |
| W45 | Every `GET /v1/session` rotates the session's CSRF token, so with two tabs of one browser the tab that loaded first gets 403 `CSRF_INVALID` on its next run or on sign-out (measured on 2026-10-03 by two agents independently: two calls gave different tokens and sign-out with the first was refused; a second `/ui` tab made the first tab's run fail). Same class as #511 ("a page GET must not rotate a token"). Note, 2026-10-25: since W105 (ADR-0178) open tabs of the same person share the renewed token | UNPINNED | `—` | — | — |
| W46 | Between 601 and 837 px wide the signed-in top bar is wider than the screen (`scrollWidth` 838), so History and Sign out sit partly or fully off-screen at 601–700 px; measured identically on `290d8c5` by W33 slice D's break-it reviewer (2026-10-03). Nothing limits how many toasts stack, so with the idle reminder showing, about 7 toasts within 4.5 s reach the top bar at 720 px tall | UNPINNED | `—` | — | — |
| W47 | Anonymous spend counted per network: all anonymous sessions on one network share one $0.40 a day; signed-in accounts keep their own $0.40 (CHG-027 a). Failure modes and an ADR first (ADR-0144). Before it, the next anonymous session after a sign-out started with a fresh $0.40 (ADR-0141) | DONE | `PRESENT src/product_app/auth.py :: def spend_key_for(session: SessionContext) -> UUID:` | — | W37 |
| W48 | Help for new users: contextual hints on by default (the cost estimate, the trust score, History; each once per device, with "Got it"), and an optional 1-minute tour opened only from "Take the tour" on the landing page and in "How it works", never automatically, skippable at every step, keyboard and screen-reader accessible, sharing its text with the hints (CHG-027 g). Journeys and acceptance tests first (ADR-0145) | DONE | `ABSENT src/product_app/templates/workspace.html :: Take the tour` | — | W47 |
| W49 | "Go to run" on a "one run at a time" card does not open the other run's result once this tab has finished or re-opened a run: `goToActiveRun` does not reset `state.terminalHandled`, so the poll that sees the run finish returns early and the page stays on the live-run view (measured by W37's test designer, 2026-10-04, with mocked responses). Once fixed, also reset `state.liveQueryText` there, or a follow-up would pair this tab's last question with that run's answer (ADR-0143) | UNPINNED | `—` | — | — |
| W50 | The cost confirmation's Run button stays greyed out (`disabled`) and Ctrl+Enter does nothing after this path: Run now on a question, "New question", re-open that question from "This session", "Review & run", "See the estimate"; the way out is "Back to edit" then "Run now". Reproduced on `369ed5e` and on `main` (`4ba35ce`) by W37's round-2 product reviewer, 2026-10-04; the cause is unmeasured | UNPINNED | `—` | — | — |
| W51 | "How it works" (the top bar's `enterLanding`) does not drop an estimate still loading, so an estimate requested on the composer opens the cost gate over the landing when it arrives (reproduced on `40249a6` by W48's break-it reviewer, 2026-10-05). W48 closes its tour when that happens; the stray cost gate itself is this row | UNPINNED | `—` | — | — |
| W52 | Keep the short excerpt each search result carries (OpenRouter annotation text, Tavily `content`) with its source for the run, so W29's judge can read it for a cited page that robots.txt says not to fetch (CHG-028). Not shown on the page; bounded; never put in any prompt here (W29's judge must fence it as untrusted); a `docs/48` row pending the owner's approval. Failure modes and an ADR first (ADR-0146) | DONE | `ABSENT src/product_app/providers.py :: excerpt: str` | — | — |
| W53 | The untrusted-text fence (`neutralize_delimiters` in `untrusted_text.py`) catches its end marker only when it is exact: a marker with a combining mark (U+034F) or variation selector inside it, a look-alike letter or a space passes it unchanged (reproduced on `88887ee` by W52's round-2 reviewers, 2026-10-05). Already true for the answers, questions and debate text it fences today; whether a model obeys an altered marker is untested. Make the fence catch an altered marker before W29 puts a search excerpt in the judge's prompt; widening W52's character removal cannot close it | DONE | `ABSENT src/product_app/untrusted_text.py :: unicodedata.normalize("NFKC"` | — | ADR-0147 |
| W54 | Switch the judge's page reading on (W29's second step, CHG-026 (e), CHG-029): the owner approved one paid measured run and up to two extra (CHG-029); make it on the session's machine with the real keys after showing the owner the free estimate; measure the judge with pages (cost, the typical judge input `cost_judge_input_tokens`, time held in the run slot, verdict quality, and at least one non-English page for tokens per character); build first, with fetching still off: the plain-English trust-note wording for pages a website asks tools not to read (CHG-029 (b), which needs a served count of sources checked by preview only) and the passage picking for pages over 4,000 characters (CHG-029 (c)), compared against the first 4,000 characters in the extra runs; capture the golden output for `PR-EVAL-JUDGE-v2`, then set `QUORUM_SOURCE_FETCH_ENABLED` in `fly.toml`. Step 1 (the wording and the passage picking, fetching still off) is ADR-0150; the paid runs were made on 2026-10-07 (CHG-032); step 2 (previews for unreadable pages, the page reserve at one token per character, the typical judge input 8,400) is ADR-0152; step 3 (PDFs read by pypdf in a sandboxed child) is ADR-0153; step 3b (encrypted PDFs that open without a password, and PDFs served as binary downloads, CHG-036 (a), CHG-037) is ADR-0154; the typical judge input becomes 15,000 (CHG-036 (b)) in its own pull request, ADR-0155; the landing line about sources follows whether pages are read (CHG-039), ADR-0158; the paid runs on the final code (CHG-038) are the golden capture, and page reading is switched on in `fly.toml` (ADR-0156) | DONE | `ABSENT fly.toml :: QUORUM_SOURCE_FETCH_ENABLED = "true"` | — | — |
| W55 | The cost-ledger rows that carry an anonymous network's spend key (W47, ADR-0144) are never deleted (nothing in `src/` deletes cost-ledger rows), so the hash outlives the 24-hour window it is used for; decide and build a retention period (CHG-029 (d)). Decided: 48 hours (CHG-033 (c)); widened by the owner on 2026-10-13 (CHG-044) to every cost-ledger row, signed-in and anonymous alike, and to the visitor's address in session rows (ADR-0165) | DONE | `ABSENT src/product_app/feedback_store.py :: def wipe_expired_identifiers(` | — | — |
| W56 | A run degraded to simulation at the global ceiling sends the anonymous network's spend key to Sentry as `account_id` in the same event as the visitor's address (`client_ip`), so Sentry can pair the two (ADR-0144 decision 5); stop sending them together (CHG-029 (d)). Widened by the owner on 2026-10-13 (CHG-042 (a)) to "nothing private reaches Sentry": the visitor's address and anti-forgery token in request headers reach it, shown by a local probe with production's Sentry scrubbing, sampling every request (finding S1; production samples about 1 request in 10), and a key inside an error message would (finding S2: a probe, with no code path known to put a key there today; both in `docs/analysis/2026-10-13-security-review.md`) | DONE | `PRESENT@7ac9a79 src/product_app/costs.py :: scope.set_extra("client_ip", client_ip)` | — | — |
| W57 | The PDF reader's exit wait (`source_fetcher._wait_for_exit_unreaped`) uses `select.select`, so with more than 1,024 open files a readable PDF would come back `unusable`, by reading of the code (advisory from the 2026-10-11 handoff) | UNPINNED | `—` | — | — |
| W58 | The 200-character floor for a fetched page counts control characters that are deleted later, for web pages and PDFs (advisory from the 2026-10-11 handoff) | UNPINNED | `—` | — | — |
| W59 | `cffi` and `pycparser` are not pinned in the production image, because `uv pip install .` ignores `uv.lock` (advisory from the 2026-10-11 handoff) | DONE | `PRESENT@1b6adf9 Dockerfile :: uv pip install --python /opt/venv/bin/python --no-cache --compile-bytecode .` | — | — |
| W60 | The signed-in E2E lane failed on two runs (the push of `dbf314e`, PR #556) on specs no change in that session touched (history-refresh, shared-allowance); both re-runs passed (advisory from the 2026-10-11 handoff); again on the push of `3825a12` (PR #567, run 38893581540), `history-refresh.spec.ts` at 700 px, where sign-in never completed, and attempt 2 passed | UNPINNED | `—` | — | — |
| W61 | The advisory mutation-score job runs out of time before scoring on most pull requests (advisory from the 2026-10-11 handoff) | UNPINNED | `—` | — | — |
| W62 | The full suite keeps growing; running it in parallel, or once per change instead of up to four times, is the lasting answer to the CI time limits (2026-10-11 handoff; plan package D1). The cuts found on 2026-10-29, in order, each to be measured before and after over several runs (CHG-103): the changed-lines coverage job reuses the coverage `validate-and-test` already produces, about 26 runner-minutes per pull-request event; a cluster of about one hundred tests that each take close to 5 seconds in CI (counted on one run; to be re-measured), probably a test-server teardown wait whose cause is to be proven on Linux before it is fixed; the slow jobs start after the unit tests; and, locally, one full-suite run per change | UNPINNED | `—` | — | — |
| W63 | The deploy gate's no-limit check would wrongly flag a job whose `if:` is false on push (advisory from the 2026-10-11 handoff) | UNPINNED | `—` | — | — |
| W64 | With the 15,000-token judge input, questions of 5,580 to 6,247 characters fit two runs a day, not three (advisory from the 2026-10-11 handoff) | UNPINNED | `—` | — | — |
| W65 | With the model catalog unreachable, every page load fetched it again (763 fetches in about 6 minutes in a browser review), so a failed fetch appears not to be cached (advisory from the 2026-10-11 handoff) | UNPINNED | `—` | — | — |
| W66 | A cited page over 256 KiB whose server states its size is refused and never read (Wikipedia's Photosynthesis article, 970,143 bytes, stated its size on 6 of 6 requests); decide whether to read the first 256 KiB (plan package D3) | UNPINNED | `—` | — | — |
| W67 | The completion-word check (ADR-0162) lets a "no" answer with no colon cancel the claim that opens the next line: "Rollback needed? no" followed by "In production: yes" passes uncited (found by the narrow re-check of package B, 2026-10-11) | UNPINNED | `—` | — | — |
| W68 | Build production from `uv.lock` (`Dockerfile:16` installs from `pyproject.toml` ranges instead), update `anyio` to 4.14.2 and `urllib3` to 2.8.0 (six known vulnerabilities, `pip-audit`), and add a blocking vulnerability check to CI; fixes the cause of W59 (finding S3 and S4 in `docs/analysis/2026-10-13-security-review.md`) | DONE | `PRESENT@1b6adf9 Dockerfile :: uv pip install --python /opt/venv/bin/python --no-cache --compile-bytecode .` | — | W59 |
| W69 | Pin every GitHub Action from outside this repository to a full commit (1 of 50 is today); by agents' reports, to reproduce first: add the `zizmor` workflow check, pin the `flyctl` version, and refuse a manual deploy from refs other than `main` on refs that carry W69, the deployment-environment boundary being an owner action (ADR-0166) (finding S6 in `docs/analysis/2026-10-13-security-review.md`); built with ADR-0166 | DONE | `PRESENT@b604c69 .github/workflows/ci.yml :: astral-sh/setup-uv@v5` | — | — |
| W70 | `scripts/security_scan.py` misses a key in a `.js` file (reproduced) and has no rule for a home-directory path (28 files under `docs/` already hold one) and, by an agent's report, in `.ts`, `.sh` and `.example` files, split keys and other secret names (finding S5 in `docs/analysis/2026-10-13-security-review.md`); built with ADR-0167 and CHG-045. Named secrets moved to W83 and input the kept rules cannot read to W84 (2026-10-16) | DONE | `PRESENT@c56dd8e scripts/security_scan.py :: TEXT_SUFFIXES = {` | — | — |
| W71 | The cost estimate assumes 4 characters per token for every language (`CHARS_PER_TOKEN`); an agent's arithmetic, not re-run, says Chinese or Japanese text is underpriced by it and can pass the per-run and daily limits; fix before live answers are switched back on (finding S7 in `docs/analysis/2026-10-13-security-review.md`). W82 adds: also count the web-search provider's calls (Tavily), which no limit counts today (`costs.py` names Tavily only in a comment); an agent's report, to reproduce first (section 4 of `docs/analysis/2026-10-17-w82-security-baseline.md`) | UNPINNED | `—` | — | — |
| W72 | By reading the code (not run end to end): with no provider citations, links the model writes are fetched as sources, so a poisoned page could make the server send the question to an attacker's address; fetch only links the search provider cited (finding S8 in `docs/analysis/2026-10-13-security-review.md`). W82 adds: limit the page fetcher to ports 80 and 443 and prefer https (ASVS V1.3.6 and V12.3.1 (a), section 4 of `docs/analysis/2026-10-17-w82-security-baseline.md`) | UNPINNED | `—` | — | — |
| W73 | Small AI-input gaps: a Cyrillic look-alike letter passes the text cleaning and the citation host denylist is exact-match only; by agents' reports, to reproduce first: variation selectors also pass, and models with fees we do not price are accepted (findings S9 and section 2 in `docs/analysis/2026-10-13-security-review.md`). W82 adds: record as a threat that panel models asked with `:online` receive web results OpenRouter adds and the app never sees, so the fence cannot cover them, and have W74 measure it (section 4 of `docs/analysis/2026-10-17-w82-security-baseline.md`) | UNPINNED | `—` | — | — |
| W74 | Only three hand-written injection attacks have run against a real model (the judge, 2026-08-07, `tests/evals/golden/measured/judge_behaviour_2026-08-07.json`), and AIR-003 in `docs/44-model-risk-register.md` reads "Not measured"; run a broad attack suite (`garak` or `promptfoo`) against the models in use today. It makes paid calls, so it needs the owner's approval of its spend (section 7 in `docs/analysis/2026-10-13-security-review.md`). The owner chose to price the suite first, from public prices, and then be asked for one exact amount; no paid call before that (CHG-056 (a)) | UNPINNED | `—` | — | owner approval |
| W75 | The page's security policy allows inline scripts (`script-src 'unsafe-inline'` in `main.py`); move to a nonce so an injected script cannot run; required before W28 (finding S11 in `docs/analysis/2026-10-13-security-review.md`). W82 adds: also `object-src 'none'`, the security headers on unhandled-error responses (a 500 carries none of them, measured), and filling the page template in one pass so a catalog label naming a placeholder cannot break the page's data (ASVS V1.3.7, V3.4.1, V3.4.3; section 4 of `docs/analysis/2026-10-17-w82-security-baseline.md`) | UNPINNED | `—` | — | — |
| W76 | Key-safety gaps to close before W28: Sentry breadcrumbs keep a key, the key pattern misses glued, encoded and prefix-less keys, the 422 handler echoes validator messages, and `model_dump_json` prints the app key (section 2 in `docs/analysis/2026-10-13-security-review.md`; agents' reports, to reproduce first) | UNPINNED | `—` | — | W56 |
| W77 | Add a security reviewer to every review round except docs-only (per-item routing, `make skill-route ITEM=`, names security skills only for sign-in and AI-output changes), replace the generic security skills under `.agents/skills/` with one written for this app, and correct `docs/41-security-controls.md` and `docs/45-control-mapping.md` (sections 1 and 2 in `docs/analysis/2026-10-13-security-review.md`). W82 rewrote `docs/41-security-controls.md` (ADR-0170), and the `docs/45-control-mapping.md` part moves to W99, so W77 keeps the security reviewer and the replacement of the generic skills | UNPINNED | `—` | — | — |
| W78 | The board's I3 limit: flipping a row's needle word and typing DONE passes (`tests/test_planted_false_claims.py` row I3 expects 0); re-check the row's first committed needle when it turns DONE, unless an owner CHG row approves the rewrite; also refuse a NEW row that is born DONE (both in section 6 and finding S12 of `docs/analysis/2026-10-13-security-review.md`). The owner chose to build the re-check (CHG-056 (b)) | UNPINNED | `—` | — | — |
| W79 | No disclosure route or key-replacement steps: add `SECURITY.md` and `security.txt`, and a key-rotation section to `docs/84-incident-response.md` (it says "rotat" 0 times) (finding S12 in `docs/analysis/2026-10-13-security-review.md`). The two repository settings W69 added here (ADR-0166) were done by the owner on 2026-10-15 (CHG-046): `FLY_API_TOKEN` lives only in the `production` environment, which allows only `main`, and actions must be pinned to a full commit | UNPINNED | `—` | — | — |
| W80 | Two sign-in gaps found by reading: `/feedback/audit` accepts any anonymous session, and the sign-in callback discards the pending sign-in before checking `state`, so a cross-site link can cancel a sign-in (finding S10 in `docs/analysis/2026-10-13-security-review.md`) | UNPINNED | `—` | — | — |
| W81 | Nothing stops an agent session reading `.env`: no Claude settings file has a `deny` rule; add deny rules and a hook (finding S12 in `docs/analysis/2026-10-13-security-review.md`) | UNPINNED | `—` | — | — |
| W82 | The security baseline, ranked first among the security rows (W71 to W81) by the owner's direction that the security session first analyses the measures in place, the gaps, and how to close them (CHG-051). The rest is as the session proposed, not the owner's decision: list every security measure in place with the command that proves it runs, replacing `docs/41-security-controls.md`; check OWASP ASVS 5.0 Level 2 item by item; turn each gap, and the gaps in section 9 of `docs/analysis/2026-10-13-security-review.md`, into a board row ranked with W71 to W81, and have Codex review that ranking before any code. Built 2026-10-17: `docs/41-security-controls.md` (97 measures, each with its proof or "none"), `docs/analysis/2026-10-17-asvs-5-level-2-check.md` (253 items) and `docs/analysis/2026-10-17-w82-security-baseline.md` (rows W85 to W101 and their order, which Codex reviewed; the gaps left without a row are marked advisory in the ASVS file); ADR-0170 | DONE | `ABSENT docs/41-security-controls.md :: The one list of the security measures in place` | — | — |
| W83 | Named secret assignments, moved from W70 on 2026-10-16 by the stop rule (CHG-049): a name ending in `_API_KEY`, `_TOKEN`, `_SECRET`, `_DSN` or `_PASSWORD` given a real-looking value is not checked. The removed rule `named_secret_assignment` read the assignment syntax of every kind of file on one line, and three fix rounds in a row each added misses or false positives in a syntax other than the one being fixed (root cause in ADR-0167). Carries round 3's open findings (a secret in a Makefile comment, a continued recipe line starting with spaces, a value starting with `+` after an earlier quoted word; `%DB_HOST%:%DB_PORT%`, help text in code, a Python annotation read as YAML, a spaced empty value before the next name, `process.env.DB_PASSWORD+""`; a `"NAME=value"` string over 512 characters in code, `\n` after a value, base64url with `_` after a YAML `:`), and Python item assignment, the Dockerfile `ENV` form, Python string prefixes, values in parentheses, template literals, `"NAME=" "value"`, `dict[str, str]` and `vault:` references; and one item the split added itself, backslash-continued lines. The removed rule's last version, with round 3's four fixes (D1 percent-encoded values, D2 names inside strings, D3 make comments, D4 fragments crossing the 512-character window) and the base64-padding fix, and their tests, is at commit `70080f3` (`tests/unit/test_security_scan_w70_round3.py` there). `refs/pull/567/head` (`e41e385`) contains it (`git merge-base --is-ancestor`, exit 0 on 2026-10-16), and GitHub keeps that ref after the branch `w70/secret-scan` is deleted. The deleted tests are listed by `git show --stat 3d42751` and its diff. The plan chooses a reader per syntax, a maintained tool with a baseline, or a narrower rule with its limits written down, and Codex reviews it before any code. Scheduled work, not a known limit (CHG-050) | UNPINNED | `—` | — | — |
| W84 | Input the kept secret-scan rules cannot read, moved from W70 on 2026-10-16: a UTF-16 file, or any text with a NUL byte in its first 8192 bytes, is skipped as binary; an encoded OpenRouter key or known shape (a JSON `\u002d` or `%2D` for `-`, or base64) is not decoded; quoted fragments joined with backticks are not joined. Not built in W70: each is a new decoder in front of every rule, and when W70 was split it had one review round left under the two-round cap in `.agents/skills/work-item-delivery/SKILL.md`. Also scheduled here, from ADR-0167's advisories: a `scheme:` inside another URL's path directly before a root is named; a Ruby-style `#{host}:` before a root is named; and the listing in `tests/unit/test_security_scan_w70.py::test_the_real_tree_is_read_exactly_as_git_would_commit_it` follows symbolic links while the scan reads them as link text. Also, from the last W70 re-check (CHG-054: a new finding goes to a board row): a merge commit's combined diff starts an added line with `++`, so `++file://` or `++git+file://` before a root is not named. Scheduled work, not a known limit (CHG-050); see ADR-0167 | UNPINNED | `—` | — | — |
| W85 | A request body of any size was read, and parsed when it was JSON, before the session was checked: bad JSON with no cookie got 422, not 401, and a 200 MB body with no cookie was read in full (measured in a local copy; whether Fly's proxy limits the size is UNVERIFIED). Refuse a body over a size limit before it is read, and refuse unknown fields and over-long lists in the request models (ASVS V2.4.1, V15.2.2, V2.2.1, V15.3.3, V5.2.1; section 4 of `docs/analysis/2026-10-17-w82-security-baseline.md`). Fixed by W85: a body over 1 MB gets 413 before it is read (CHG-063 (a)); built with ADR-0171 | DONE | `ABSENT src/product_app/main.py :: app.add_middleware(RequestBodyLimitMiddleware)` | — | — |
| W86 | Signed-in history older than 30 days is deleted only when that same account saves a question (`session_store.py`, the age and count deletes inside `record_history`), so an account that stops using the site keeps old questions on disk, against the approved keep rule (`docs/48-data-retention.md`, CHG-023); reads already leave them out. Delete them for every account, and turn on `secure_delete` in the session store, which never sets it (ASVS V14.2.4; section 4 of `docs/analysis/2026-10-17-w82-security-baseline.md`) | DONE | `ABSENT src/product_app/auth.py :: store.sweep_history(` | — | — |
| W87 | A session ended only after idle time, so a stolen cookie that kept being used never expired (fixed by W87-1) and kept the power to delete the account (fixed by W87-2). End a signed-in session 12 hours after it started and an anonymous one 24 hours after; require a Google sign-in within the last 10 minutes before deleting an account (both CHG-056 (c) and (d)); give an operator a command to end one account's or every session; record why sign-in is single-factor (ASVS V7.3.2, V7.6.1, V7.4.5, V6.3.3; section 4 of `docs/analysis/2026-10-17-w82-security-baseline.md`). Done: maximum age (W87-1, ADR-0174); a recent sign-in before deletion and the single-factor record (W87-2, ADR-0175); the operator command, which ends one account's or every signed-in session while every process reads the durable cutoff on each request (W87-3, ADR-0176) | DONE | `ABSENT src/product_app/session_store.py :: SIGNED_IN_CUTOFF_LOCK_TIMEOUT_S = ` | — | — |
| W88 | Another site could make a visitor's browser load `/ui` or `/v1/session` with no cookie (a cross-site image or fetch sends no `SameSite=Lax` cookie), and each load opened a session counted against the network's 2 a day; a top-level link to `/v1/session` does send the cookie, so it resumed the visitor's session and replaced an open tab's anti-forgery token (read by the session; measured in Chromium by W88's failure-modes list on 2026-10-18, which found that a frame of `/ui` opened a session too, `docs/analysis/2026-10-18-w88-cross-site-session-loads-failure-modes.md`). (ASVS V3.5.3; section 4 of `docs/analysis/2026-10-17-w82-security-baseline.md`.) Fixed by W88, which reads `Sec-Fetch-Site`, `Sec-Fetch-Mode` and `Sec-Fetch-Dest`: this site's own requests and a typed address are allowed; from another site, `same-site` included, `/ui` is served only as a page (a navigation that loads a document, such as a link), and `/v1/session` is refused in every form; a prefetch of either is refused (review round 1); all before any counter; with no `Sec-Fetch-Site` the `Origin` header decides (CHG-063 (b), CHG-067); built with ADR-0177 | DONE | `ABSENT src/product_app/main.py :: fetch_site.cross_site_refusal(request, page=False)` | — | — |
| W89 | A crash inside a run is caught and the run marked failed with the error's class name, with no log line and no Sentry event (`query_run_orchestration.py`, `_execute_query_run_safely`); refusals (401, 403, anti-forgery, 429, 422) are counted only as `4xx` in `/metrics`; uvicorn's own logs are plain text. Log the crash and send it to Sentry, count refusals apart, and give uvicorn the app's JSON format. Adds no identifier to any record: an address or a network on sign-in events would change their approved keep rule (`docs/48-data-retention.md`), which is the owner's decision (ASVS V16.3.1 to V16.3.4, V16.2.x; section 4 of `docs/analysis/2026-10-17-w82-security-baseline.md`) | UNPINNED | `—` | — | — |
| W90 | The browser keeps private data after a session: no `Cache-Control: no-store` on `/v1/session` (which returns the anti-forgery token) or on a run's answers, no `Clear-Site-Data` at sign-out or deletion, the email, history and last answer stay on screen after idle expiry or a failed sign-out, and "Sign out" sits only in the top bar, hidden on the result views. Fix each (ASVS V14.2.2, V14.3.1, V14.3.2, V7.4.4; agents' reports, to reproduce first; section 4 of `docs/analysis/2026-10-17-w82-security-baseline.md`) | UNPINNED | `—` | — | — |
| W91 | Nothing would notice the app's OpenRouter key being used outside the app: the key check reads only the status code and makes no call while live answers are off, and nothing compares the app's records with OpenRouter's usage. Read the key's usage from OpenRouter's free key endpoint and alert when it grows faster than the app's own records. The credit limit on the key is the owner's account setting (section 3 of `docs/analysis/2026-10-17-w82-security-baseline.md`; agents' report) | UNPINNED | `—` | — | — |
| W92 | The supply chain is checked only when CI runs (on a push, a pull request or a manual start), never on a schedule: the vulnerability audit runs only in `ci.yml`, base images are pinned by tag, the image's system packages and its `pip` are not audited, Fly builds its own image so the one CI checked is not the one deployed, and no static analysis (ruff's security rules, CodeQL or Semgrep) runs. Add a daily audit, digest pins, an audit of the image, deploying the checked image, and ruff's security rules (ASVS V15.1.x, V15.2.1, V1.2.4; section 4 of `docs/analysis/2026-10-17-w82-security-baseline.md`) | UNPINNED | `—` | — | — |
| W93 | Every page load fetches the fonts from Google, which sends each visitor's address to Google; no decision records it (ADR-0149 pins the stylesheet for the screenshot tests only). Serve the fonts from this site; the screenshot baselines move (ASVS V14.2.3; section 4 of `docs/analysis/2026-10-17-w82-security-baseline.md`) | UNPINNED | `—` | — | — |
| W94 | Limits at scale, by agents' reports: sign-in-only sessions have no site-wide cap, an IPv6 /48 holds 65,536 counted networks, 8 networks can hold all 16 run slots, any machine in Fly's private range `fdaa::/16` can choose its own visitor address, an allow-listed network has no per-minute limit, history reads have no limit, and old per-account limiter entries are never swept. Every value is the owner's; the session proposes measured values before asking (section 4 of `docs/analysis/2026-10-17-w82-security-baseline.md`) | UNPINNED | `—` | — | owner decision |
| W95 | Keys: no list of every key with its use and owner; `QUORUM_TOKEN_SECRET` is only required to be non-empty (`config.py`), and one secret keys three things; `DEPLOY.md` says it keys only the cost confirmations, though rotating it also restarts every network's daily allowance (ADR-0144), and the doc check reads only `auth.py`. Add the list, refuse a secret under 32 bytes, separate the keys, correct `DEPLOY.md` and widen its check. Build with W79, which keeps the replacement steps (ASVS V11.1.1, V11.1.2, V11.2.3, V13.3.2; section 4 of `docs/analysis/2026-10-17-w82-security-baseline.md`) | UNPINNED | `—` | — | — |
| W96 | The model-catalog fetch runs at every start (`main.py`, `prewarm`) through a bare `urlopen`, which follows redirects, and accepts a plain `http` address (`catalog_fetcher.py`). It sends no key, but its prices feed the cost estimate. Refuse redirects and plain http, as the key-carrying calls do (ASVS V15.3.2, V12.3.1 (b); read by the session; section 4 of `docs/analysis/2026-10-17-w82-security-baseline.md`) | UNPINNED | `—` | — | — |
| W97 | Google sign-in token checks: no `nonce` is sent or checked, a future `nbf` is accepted, and the ID token's signature is not checked (ADR-0130 decision 4 relies on the token arriving over verified TLS from the server's own call, which OpenID Connect allows; ASVS 6.8.2 does not). Add the nonce and the `nbf` check, and either check the signature against Google's keys or record the exception to ASVS in ADR-0130 (ASVS V6.8.2, V9.1.1, V9.1.2, V9.2.1, V10.5.1; section 4 of `docs/analysis/2026-10-17-w82-security-baseline.md`) | UNPINNED | `—` | — | — |
| W98 | Measures in place that no test would miss, listed in `docs/41-security-controls.md` under "Measures no test would miss" and in the ASVS file's W98 items: give each a test that fails without it (section 4 of `docs/analysis/2026-10-17-w82-security-baseline.md`) | UNPINNED | `—` | — | — |
| W99 | The security documents do not match the code: `docs/40-threat-model.md` says anonymous visitors cannot run questions and lists bring-your-own key as built; `docs/45-control-mapping.md` reads "Not available" throughout; no table lists the routes and who may call them, the stored data and its keep time, the outbound connections, the logs, the sign-in pathways, or the request rules and limits; ADR-0130 to ADR-0139 lack amendment lines, except ADR-0134 and ADR-0136; `docs/18-requirement-traceability-matrix.md` names test files that never existed; `.github/CODEOWNERS` is a placeholder; and several comments state old numbers. Rewrite them; takes `docs/45` over from W77 (section 4 of `docs/analysis/2026-10-17-w82-security-baseline.md`) | UNPINNED | `—` | — | — |
| W100 | The page could tell the server a visitor acknowledged a high-stakes warning they never saw: the box was checked only if the half-second background check had already answered and found the warning, a failed check left the gate open, the cost gate's confirm button had no high-stakes check, and `proceedWithRun` sent every warning the final check returned as acknowledged (`static/app.js`; read by the session, by Codex and by a reviewer; reproduced by W100 on a local simulated server). Send an acknowledgement only for a box the visitor ticked, and hold the run for the box when the final check finds a warning (section 4 of `docs/analysis/2026-10-17-w82-security-baseline.md`). Fixed by W100: the high-stakes acknowledgement is sent only when the box is ticked after the final check, the sensitive-data one stays automatic, and an unticked run is held on the composer (CHG-063 (g), CHG-065); built with ADR-0173 | DONE | `ABSENT src/product_app/static/app.js :: function safetyAcknowledgementsFor(` | — | — |
| W101 | Invite links, off in production (`/status` `invite_links.enabled: false`): the `quorum_invite` cookie has no `__Host-` prefix, the signing key need only be 32 characters, not 32 random bytes, the host is not part of what is signed, and revoking a link leaves the sessions it opened working. Fix each before invite links are switched on (ASVS V3.3.1, V3.3.3, V9.1.3, V9.2.3; agents' reports; section 4 of `docs/analysis/2026-10-17-w82-security-baseline.md`) | UNPINNED | `—` | — | — |
| W102 | Many requests of just under W85's 1 MB limit, sent at once, still cost the server far more memory than their size, and production is one machine with 512 MB (measured locally on 2026-10-18; details held back until the fix ships, the session applying CHG-060's rule). Options, each needing the owner: a lower body limit than CHG-063 (a)'s 1 MB, a cap on how many bodies are read at once, or checking the session before parsing the body (ADR-0171, A5) | UNPINNED | `—` | — | — |
| W103 | A run can end after its session (W87-1's recorded limit, ADR-0174): the run deadline is checked at three points, and a stage started before it runs to its own timeout, so a run admitted with 720 s left can finish after the session ends (by reading: up to about 9 minutes past a 720 s deadline). Make the run stop at its deadline between stages and calls, or bind it to the session's end (NFR-004) | UNPINNED | `—` | — | — |
| W104 | Three small follow-ups from W87-1's user-journey test (2026-10-19): after the 12-hour end the History panel says another tab, window or device ended the session; pressing "Sign in again" on the late-run card after the session has ended shows only the toast "Sign-in could not start. Please try again."; the top bar still reads "Session active" after the end. Each needs the owner's words before it changes | UNPINNED | `—` | — | — |
| W105 | Open tabs share a renewed anti-forgery token (CHG-071): when a tab renews the session's token it passes the new token to the site's other open tabs in the same browser (same origin only, BroadcastChannel), so a second tab, or one opened from another site's link, no longer leaves the first tab refused until it reloads. The sharing is page-only; the drawn-account guard adds one data island to `/ui`; its own pull request after W88 (ADR-0178, CHG-089) | DONE | `ABSENT src/product_app/static/app.js :: new BroadcastChannel("quorum-session-token")` | — | — |
| W106 | Page loads never count (CHG-067): `/ui` serves the page without opening a session, and only the page's own same-origin script opens one, so no load of the page from another site can spend one of a network's daily sessions. Weigh ADR-0139's sign-in from the capped page and the test that a first visit starts a session | UNPINNED | `—` | — | — |
| W107 | The PDF reader's child-process write catches only `BrokenPipeError` (`source_fetcher.py`, the non-blocking stdin write): on a heavily loaded Mac the write raised `BlockingIOError` though `select` said writable, failing 58 to 59 `tests/unit/test_w54_*` locally, identically on a clean `main` copy (measured 2026-10-18; CI's Linux runner passes). Catch it and keep selecting, with a test that forces a short write | UNPINNED | `—` | — | — |
| W110 | The circle that can deploy, which every design for keeping users' keys relies on staying small (ADR-0180, Consequences; CHG-082): the two app-scoped Fly deploy tokens expire in 2046 (`fly tokens list -a quorum-ai`, 2026-10-17); the `production` environment's only rule is the `main` branch policy, with no required reviewer, and the repository has 2 collaborators, one admin and one write (`gh api`, 2026-10-18); 2-step login is on for the owner's GitHub account (`docs/41-security-controls.md`) and unchecked for Fly and for the write collaborator; organisation-scoped Fly tokens are not listed (U12 in `docs/analysis/2026-10-17-w28-key-storage-research.md`). Mostly the owner's own settings: shorter-lived Fly tokens, 2-step login, a required reviewer on `production`, and whether the write collaborator still needs it. W79 keeps the disclosure route and the key-replacement steps; this row is who can deploy. Numbered W110 to leave W103 to W109 to the parallel security session | UNPINNED | `—` | — | — |
| W111 | The ordinary sign-in path checks the session only before the Google exchange: a deletion that completes during that exchange lets the sign-in create a new account row for the same Google identity, and a sign-out everywhere during it leaves a working session (by reading and by the W87-2 break-it matrix, 2026-10-20; ADR-0175 Known limits). Re-check after the exchange and hold the account write under the repository lock, as W87-2 does for a recovered session | UNPINNED | `—` | — | — |
| W112 | Doc claims no check reads: a number in an ADR or docs/41 that restates a constant (SC-103's 600 seconds), a CHG-NNN (x) letter that does not exist, docs/41's bare file.py:NNN citations (test_cited_paths_resolve reads only paths that start with a folder), and e2e.yml's measured-run comments; each survived a planted change in W87-2's falsification rounds (2026-10-20). Pin what can be derived offline, as tests/test_doc_gate_consistency.py Part D does | UNPINNED | `—` | — | — |
| W113 | A check that each CHG row's quoted answer matches the answer the owner gave, with the quoted clauses rendered from a saved extract of each answer. Built on the local branch `w113/owner-quote-check` and never merged; paused for redesign under CHG-102, because public rows are now restatements and no longer quote answers (Parked) | UNPINNED | `—` | — | W117 |
| W114 | A follow-up to W87-3 found in its review (CHG-083 (a), ADR-0176): while the session database could not be checked (not ready, busy past the wait, or failing a read), a signed-in visitor's cookie was swapped for a new anonymous session, which spent one of the network's 2 daily sessions and left them signed out after the store recovered; sign-in failed at Google instead of before it; the operator saw nothing; and a sign-out whose row delete failed could be undone by a Google sign-in that crossed the 12 hours. Pull request A (CHG-088, ADR-0176's amendment of 2026-10-25) keeps the cookie and creates nothing (a 503 page that reloads itself, the 401 `SESSION_UNCHECKED`, an open tab that retries in place), refuses sign-in before Google, adds a rate-limited log line and `/status` `session_store`, the command's busy and no-match sentences and the 6 s bound, and keeps a revoked session out of the 12-hour recovery. Open for pull request B: a sign-out while the session cannot be checked is refused and keeps the cookie (the owner's "Clear the cookie anyway", CHG-088 (i), accepted as temporary in (l)); the owner answered B's question on 2026-10-27 (15:20 UTC, transcript `16de928d`): "Refuse when not held" (CHG-096); asked again on 2026-10-28 with each option's outcome for the example, the owner chose "Cap 1,000, oldest out (Recommended)" (CHG-098, which replaces CHG-096): the cookie is always cleared, and the server notes the session id, at most 1,000 for 24 hours, oldest out. B builds from a table of every way a session ends, including a sign-out that races a sign-in's rotation (CHG-088 (m)). | PENDING | `ABSENT src/product_app/auth.py :: def sign_out_unchecked(` | — | — |
| W115 | The three required CI jobs that run the whole pytest suite (`validate-and-test`, `pytest (Python 3.12)`, `Changed-lines coverage >= 95% (blocking)`) ran up to 33.3 minutes against their 35-minute limit (the session measured every run of the three workflows created from 2026-10-20 to 2026-10-27; no job was cut off by the limit). A later push run on 2026-10-28, run 40673869190 (`13ef1f7`), took 33.8 minutes in `validate-and-test`, still under 35. The owner chose (CHG-095) to raise the job limits, the deploy gate's wait and the drift watchdog's grace together now, then to look for the cause of the roughly 7-minute swing between runs of the same suite (the session plans that as reading CI logs first and reporting to the owner before any change). The plan (45, 45 and 45 minutes, e2e staying at 35; gate 3000 s; grace 3300 s; ADR-0182, superseding ADR-0157 in part; tests red first) and its measurement script are in the owner's evidence folder outside the repository, `2026-10-28/ci-limits/`. Investigation (c) follows this item: read-only on CI logs, reported to the owner before any change. | DONE | `ABSENT .github/workflows/test.yml :: timeout-minutes: 45` | — | — |
| W116 | The advisory CI job "Mutation score on changed functions" has printed no score on any pull request that changed Python code since #578 (2026-10-18; #563, 2026-10-13, printed `mutation score (killed / (killed+survived)) = 100.0%`): each time its first run of the tests stopped at a failing test, and that run stops at the first failure. The discovery probe #596 (run 40753467337, closed unmerged; CHG-100) ran the whole suite inside the mutation tool's copy and listed 26 failing tests in five causes (ADR-0183): (A) 5 call src code after `monkeypatch.chdir` to a folder with no `src`, and the tool finds the code by the relative path `src`; (B) 17 start a Python child in such a folder; (C) 1 recognises `create` by its frame's function name, which the tool renames; (D) 2 count the structure of the MUTATED source, read through a module's `__file__`; (E) 1 reads `e2e/servers`, which `[tool.mutmut].also_copy` left out. A sixth, in the later clean-test step, is #564's `tests/unit/test_run_history_store.py::test_configure_for_tests_isolation`. The fix: a test leaves the tree's folder only through `tests/mutmut_cwd.py`'s `mutmut_can_run_in`; the lock double recognises `create` by a wrapper; structural reads of src use `find_repo_root`; `also_copy` gains `e2e/servers`; the run deadline goes from 1440 s to 2400 s inside a 50-minute job; guards in `tests/unit/test_w116_tests_run_inside_the_mutation_copy.py`. The needle is the frame-name read the fix deletes, so the row derives DONE at merge, but W116 counts as done only when the confirmation probe run after merge prints a score (CHG-099, CHG-100), which the handoff carries as an open step. If that probe fails in the clean-test step: one fix pull request and one more probe; if in the first test run: work stops for a product-owner decision (CHG-101). The job stays advisory; making it blocking is a separate owner decision. The owner raised it and placed it after W115 (CHG-097) | DONE | `PRESENT@7f8cf00 tests/integration/test_late_run_refusal.py :: f_code.co_name` | — | — |
| W117 | Public-content guard and rules (CHG-102, CHG-103): adopting the shared public-content guard built outside this repository (CHG-104): its CI step, advisory first, and a scan of the merge subject and body in the `close-guard` target, once it is released; the secret scan ahead of the unit tests in CI; and rewriting the rules that require the owner's exact words and session ids in public files (`AGENTS.md`, `.agents/skills/work-item-delivery/SKILL.md`, the prompt template, the owner-words row of `docs/README.md`) | UNPINNED | `—` | — | — |
| W118 | Enterprise hygiene (CHG-103), with W79: a real `CODEOWNERS` in place of the placeholder; a Dependabot configuration, and dependencies kept current; CodeQL default setup, advisory; a static security scan with a baseline, its findings triaged and each reproduced before it is called a defect; gitleaks; commits made with the GitHub no-reply address; required conversation resolution on pull requests | UNPINNED | `—` | — | — |
| W119 | Process sized to risk (CHG-103): review tiers by risk, keeping at every tier the completeness critic, a Codex review of any document that carries a decision, and a final prose check of the pull request body; the tier and the roles stated in the pull request body, advisory; a weekly report; no net growth of `AGENTS.md`; and the handoff design reworked | UNPINNED | `—` | — | — |
| W120 | Two mutants of `product_app.pdf_text.is_garbled` survive, `x_is_garbled__mutmut_9` and `x_is_garbled__mutmut_12`: found by the confirmation probe #598 (closed unmerged), run 40853766761, which printed a score of 86.7% (13 killed, 2 survived; threshold 80%). Strengthen the boundary tests until both are killed (CHG-103) | UNPINNED | `—` | — | — |
| W121 | Flaky tests (CHG-103): `tests/unit/test_history_sweep.py::test_a_raising_purge_does_not_skip_the_sweep` races the cleanup daemon, seen as `['purge', 'purge'] == ['purge']` on #597's coverage job; the signed-in e2e `store-unchecked.spec.ts` test "J1p at 390" timed out once on #597. Reproduce each, then fix | UNPINNED | `—` | — | — |

**STOP** marks a row that cannot be finished without a human decision — a money,
cost or safety guardrail value that only real measurement could justify. Do not
move one of those numbers as a side effect of any other package.

## What each row is

**W1 — stream the provider call. DONE** (ADR-0084), clubbed with W15.
`_post_messages` now sends `"stream": True` and folds SSE frames into the
payload an equivalent non-streamed call would have returned, so
`_extract_message_content`, `_extract_usage`,
`_finish_reason_indicates_truncation` and `_extract_citations` are reused
BYTE-UNCHANGED and the two shapes cannot drift apart.
`_read_body_within_budget` became the generator `_iter_body_within_budget`, so
exactly one loop still touches the socket and every transport guard is shared
rather than reimplemented. What is MEASURED behind that choice is the frame
count — the B3 probe records a 2,594-token answer arriving in **4,194 frames**;
it kept no byte column, so any wire-byte figure is a model at roughly 300
bytes/frame, about 1.2 MB against roughly 10 KB non-streamed. An earlier draft
of this paragraph quoted "1,262,550 bytes over 4,196 frames, ~119x" as measured:
the frame count contradicted the source by two and the ratio compared wire bytes
to body bytes while claiming *resident* bytes. Corrected here rather than
deleted, because the direction is what the decision rests on and it holds.

The check streaming had to ADD: chunked framing carries no length, so the
`IncompleteRead` guard is inert on the normal path and a stream that stops
part-way raises nothing. A terminator is now required — `[DONE]`, a non-null
`finish_reason`, or a top-level `error` — and its absence is
`_DISPATCH_UNMEASURED` plus `upstream_provider_stream_incomplete`. Accepting
three terminators rather than `[DONE]` alone is deliberate: `[DONE]` is
measured nowhere against this upstream, and requiring it could have classified
every healthy call unmeasured.

The seam survived as promised: `product_app.providers.urlopen` now appears on
**44 lines across 15 test files**, against **43 across 14** on `origin/main`
(both re-measured 2026-08-30). Read that +1 honestly — the per-file counts are
identical across the 14 shared files, and the 15th file is
`tests/provider_wire.py`, whose single occurrence is a *sentence about* the
seam in its module docstring, not a patch site. So the count grew by a
docstring; what it evidences is that no existing patch site had to move. The
bodies changed, not the seam;
`tests/provider_wire.py` renders a non-streamed payload as the stream that
carries it, so 12 hand-rolled builders became one.

Two things this did NOT do, both stated in ADR-0084 rather than left to be
found: `stream_options: {"include_usage": true}` is not sent (the "usage
arrives with no opt-in" claim is ASSUMED, not measured, and both documents
asserting it are corrected here), and `_extract_citations`' FLAT annotation
read is carried across faithfully but not fixed — settling that shape needs a
live `:online` call, which is spend.

**W2 — peer critique (#290, closure decided 2026-09-15). BUILT, shipping DEFAULT-OFF in
`config.py`, switched ON in production by `fly.toml` from 2026-09-03 until
2026-09-24, when it was coupled to the live window and turned off (#458, ADR-0122).** ADR-0093's
shape is implemented in full (decisions 1, 1a, 1b, 2, 3, 4, 5) behind
`settings.peer_critique_enabled`, which defaults to `false`. ADR-0095 records
why the flag exists and it is not caution: `_estimate_bound_usd` calls itself a
TRUE CEILING and prices exactly two debate calls, while a peer run makes two
PER ELIGIBLE CRITIC. The bound now reads the same flag, so the ceiling holds in
both postures — measured on four identical slots, `debate_round_1` goes
`$0.0052` -> `$0.0208`, a ratio of exactly 4.0000: one call per slot.

**#290 — peer critique has run in production; closure decided by the product
owner 2026-09-15 and effected by the merge of the change that carries this
paragraph.** W2's row
reads DONE because the mechanism is in the tree, and the run this paragraph
used to wait for has happened, four times: the 2026-09-03 live window ran with
`PEER_CRITIQUE_ENABLED=true`, and `docs/analysis/2026-09-10-telemetry-tokens.jsonl`
carries four runs with peer-shaped debate rounds — `1cb95597` (2026-09-06),
`2e2d3c2e` (2026-09-08) and `5a9c2d63` (2026-09-10) dispatched `debate_round_1`
AND `debate_round_2` to all four slot models, and `fcca9510` (2026-09-10)
dispatched round 1 to all four while its round 2 ran entirely on templated
fallback critiques and made no provider call, so it left no round-2 telemetry
rows — the run completed, `cost_source` measured (ADR-0110;
`docs/analysis/2026-09-10-window-measurements.md`). The moderator shape would
show only `settings.debate_model_id`. Re-derive:
`python3 -c` over that file, grouping `stage` by `query_run_id` and counting
distinct `model_id`. The two 2026-09-10 runs' cost is reconciled against the
provider bill in CHG-006. Production ran `PEER_CRITIQUE_ENABLED = "true"` (`fly.toml`, `/status`) with
live execution off from 2026-09-12 until 2026-09-24, when ADR-0122 coupled the
flag to the window and turned it off. What
#290 asked for is built, shipped and exercised; the per-model measurement W3
wants is now derivable from that telemetry and is W3's work, not #290's. The
needle was REPLACED for this row — the old one pinned
`model_id=settings.debate_model_id,`, a literal the moderator call sites still
carry, so it would have read PENDING for a reason that is no longer the reason.

The history below is why it was blocked, kept because W3 still leans on it.
Before this change there was exactly one debate caller and it
always dispatched `settings.debate_model_id`. Blocked on W1 because the #290 spike
measured **7 of 8** probe calls exceeding the 8s timeout on wall clock —
`nvidia/nemotron`'s first rep at 6.385s does not — and 6 of 8 on the per-`recv`
gap. (The approved plan and two session handoffs say "8 of 8"; ADR-0078 and
`docs/analysis/2026-08-26-b3-timeout-probe.md` both correct it against the
probe's own table. The corrected figure is the one used here.) Streaming
collapsed the gap to 0.478 / 0.208 s on a paired sample. Building critique first
would have shipped a feature that pays for discarded tokens and demotes every
receipt to `estimated`. **That blocker is now discharged** — see the W1 note
below: two live windows measured the streamed path, most recently three runs
that all came back `measured` with no failed steps.

**W3 — the money constants. MOVED on 2026-09-07 (ADR-0102); ADR-0081's
deferral is discharged.** ADR-0081 (2026-08-28) held the ladder at
0.15 / 0.20 / 0.25 until #290 was built and its cost measured. Both have
happened: W2 shipped on 2026-09-03 (`5aed777`), and ADR-0102 (Accepted
2026-09-06; `0b6b0b4`, 2026-09-07) measured the first real critique run,
raised `DEBATE_ROUND_MAX_TOKENS` 2000 → 4000 together with
`cost_debate_output_tokens_cap`, and moved the ladder to
`SOFT_THRESHOLD_USD = 0.30`, `DAILY_CAP_USD = 0.40`, `HARD_LIMIT_USD = 0.50`,
with `GLOBAL_DAILY_CEILING_USD` held at 5.00. The row's needle names the OLD
`DAILY_CAP_USD = Decimal("0.20")` line, so the row derives DONE for exactly
that reason. Re-derive:
`grep -n -E '^(SOFT_THRESHOLD_USD|HARD_LIMIT_USD|DAILY_CAP_USD|GLOBAL_DAILY_CEILING_USD) ' src/product_app/costs.py`.
Until 2026-09-16 this block still quoted the 0.15 ladder as current and told a
reader to hold it; it had been stale since `0b6b0b4`.

Measured headroom (2026-09-16; live catalog, 441 models; production posture on that date,
peer critique ON and the judge `openai/gpt-4.1-mini` ON; peer critique was turned off on 2026-09-24,
ADR-0122): with the `:online`
search fee at the `$0.007` it ships at since the 2026-09-15 activation
(CHG-007, ADR-0113), the default mix on ADR-0102's own query bounds at
**0.2110** against the **0.30** line — **ALLOW, about 8.9 cents** of headroom.
Before that activation, with the fee at `0.0`, the same shape bounded at
**0.1830** (point estimate 0.0755, about 11.7 cents), and ADR-0102 measured
0.1827 for it. That margin is the number to watch; W13 (#268) is a change
that would eat into it. `SOFT_THRESHOLD_USD < DAILY_CAP_USD < HARD_LIMIT_USD`
is mandatory or the confirmation band is dead code. Re-derive with
`cost_estimation_service._estimate_bound_usd` and `_threshold_for` on the
four default slots (the sweep script's `_band` helper is the same call), with
the posture set in the environment and printed beside the number.

**ADR-0094's pre-computed targets were overtaken, not landed.** Its hermetic
sweep over all **715** four-slot mixes (C(13,4); the often-quoted "495" is
stale, from a twelve-model catalog) proposed `cost_debate_output_tokens`
400 → 1700, `SYNTHESIS_SECTION_MAX_TOKENS` 3000 → 6000 and a ladder of
0.18 / 0.27 / 0.28. ADR-0102 then moved the ladder further and by a different
mechanism (the measured cap), and the two token constants have NOT moved:
`cost_debate_output_tokens` IS LANDED from measurement — 400 -> 2200,
#268 / ADR-0115 / CHG-009, product owner 2026-09-20 (value) and 2026-09-21
(merge) — measured against the peer-shaped
telemetry at cap 4000, with the 715-mix sweep re-run (0 band flips, 0 bound
changes). `synthesis.py` still ships `SYNTHESIS_SECTION_MAX_TOKENS = 3000`,
which is NOT landed and is deliberately a separate concern: it is a call-site
cap, not a pricing typical, and no measurement here bears on it. So this
paragraph's "land both token constants in ONE pull request" was followed only
for the one the telemetry measures; say so rather than silently ignore it.
Nothing in this paragraph authorises a live window or a paid run.

`finish_reason` is now IN PLACE (ADR-0093 decision 5, shipped with W2): the
durable token stream carries `query_run_id`, `stage` and a bounded
`finish_reason` on every provider call, plus `slot_number` on the calls that
belong to an answer slot — the initial answers and, under the flag, each critic.
A call belonging to no slot (the moderator, synthesis, the judge) OMITS that
field rather than nulling it. So the post-#290 sweep can group by run and round
instead of inferring from `model_id`. The RUN has now happened — four
peer-shaped runs between 2026-09-06 and 2026-09-10 (see W2 above) — so the
per-model numbers the design exposes are derivable from that telemetry. W3 has
not yet re-derived them, and that is W3's work; #290's closure was decided
2026-09-15.

**W4, W5 and W7: what the owner has already said** is recorded, with sources, in
`docs/analysis/2026-09-22-decision-register.md` (reconstructed from session
transcripts and confirmed by the owner on 2026-09-24, CHG-012 D9; its
2026-09-24 section holds that day's decisions on W5, W7, #458, #459, #447,
#268 and BYOK). Read it before calling any of the three "undecided".

**W4 — variable panel size.** Decided by the owner on 2026-09-22 (CHG-010,
ADR-0120): a visible remove/add control, range 2..4, and at N=2 a green
"Both models agree (2 of 2)" band with trust capped at moderate. The backend
half is in: `MIN_SLOT_COUNT`/`MAX_SLOT_COUNT`, the four `Field(ge=1, le=4)`
sites now read `le=MAX_SLOT_COUNT`, the estimate prices N upstream answers,
and the trust cap exists. The validator still accepts only four until the
workspace control ships with it. **No longer
blocked**: #382 ended *"whoever lifts those caps must fix this primitive
first,"* and W10 fixed it (ADR-0083). The CSS is cheaper than feared:
`.model-slot-grid` is `grid-template-columns: 1fr 1fr` with an existing
single-column media query, not a 2×2 `grid-template-areas`, so N=2 and N=3
already reflow (verified 2026-08-28).

**W5 — the quick-answer mode.** Every decision is taken (CHG-012 D1 and the
owner's answers of 2026-09-24 evening, recorded in
`docs/analysis/2026-09-24-w5-parked.md`). Four pull requests: (1) the backend
request shape, estimate, bound, token shape, run path and receipt (ADR-0126,
CHG-016; merged, #506); (2) what a quick result serves (ADR-0127, CHG-017; merged, #507): the safety-notice carrier, the
quick trust shape and the run store's `mode` column; (3) the workspace
control and result view (ADR-0128, CHG-018; merged, #508);
(4) the judge prompt, verification only, with the judge's per-claim
evidence (ADR-0129, CHG-019). **W5 is complete with the fourth pull
request:** its needle, `JUDGE_QUICK_PROMPT_ID`, is the name that pull request
adds to `evaluation.py`, so the row derives DONE from the tree. It was pinned
on the composer sentence until review of the third pull request pointed out
that the row then read DONE while W5 still had work open. Two things stay
open and are not W5 rows: the quick judge prompt's quality on real answers is
unmeasured (no live window has run it), and the owner has not confirmed that
the per-claim evidence is what they meant by "artifacts to support why".

**W6 — #383. DONE** (ADR-0083). The stance branch of `compute_consensus_strength`
called a panel of exactly ONE scored answer "strong" — `len(sizes) == 1` is
trivially true at N=1, and independently so is the majority clause, since
`_required_cluster(1) == 1`. Both called a lone answer "unanimous", with
nothing to corroborate it. Fixed with a guard returning `"weak"` at
`len(stance) == 1`, matching what the overlap branch (no live moderator) was
already returning for the identical N=1 shape — the module no longer
disagrees with itself. This also flips `false_consensus_preserved` to `True`
at N=1, which is what actually suppresses the green "unanimous panel" banner
(AC-019) — traced end to end, not just asserted on the literal. The row's
original Evidence needle (the pre-existing majority-bar line) never changed
by this fix and was re-pinned to the new guard; the old needle would have
left this row `PENDING` forever, fixed or not.

**W7 — Google sign-in.** In `auth.py` and `session_store.py`. The demo plan named
`readiness.py`; that module is the OpenRouter live-execution key probe and holds
no session or account code (verified 2026-08-28) — the plan was wrong. A `users`
or `identities` table goes in a guarded `schema_migrations` block, **never** in
`session_store._SCHEMA`, whose own docstring records that adding a table there
makes the first open of an existing read-only database raise. Its first
needle was the bare word `google`, which review satisfied by adding a
*comment* to `auth.py` saying the work was still to do. A needle that a comment
can satisfy is not evidence.

The first of W7's two pull requests (ADR-0130, CHG-020) built sign-in and
sign-out: an `accounts` table in a guarded `schema_migrations` block of the
sessions database, the OpenID Connect flow in `google_signin.py`, and the
session rotation in `auth.py`. It is off in production until the operator
creates the Google OAuth client and sets the three `GOOGLE_OAUTH_*` secrets.
The row was first pinned on `history_keep_count` (the history setting),
then moved to `signed_in_idle_minutes`, the setting only the last of W7's
pull requests adds (idle expiry, ADR-0138), so the row read PENDING until
all of W7 had landed. It reads DONE from that pull request on.

**W8 — DECIDED 2026-08-28, and removed from the table.**
`min_machines_running` stays `0`: the app keeps scaling to zero. It was never a
code change, it was a question, and the answer is recorded in **ADR-0082**. A
board that carries settled questions stops being a list of open work. Reopen it
when there is a scheduled demo with an audience — and price the always-on option
first, because nobody has.

**W9 — moderator/slot overlap. DONE** (ADR-0086). `debate_model_id` defaults
to `anthropic/claude-haiku-4.5`, which is also slot 2's default, so the
moderator is a panel member grading its own answer — and not blindly:
`debate._debate_user_prompt` labels every answer with its model and both
moderator system prompts say "Cite the model names". Its reply is a
`PanelStance` with one position per slot, which `synthesis_consensus.
_usable_stance` feeds to `panel_agreement` ("agreed"/"split") and
`compute_consensus_strength` ("strong"/"divided"), so one of the four votes
behind the verdict a reader sees was cast on its author's own work. At the
shipped panel size `_required_cluster(4)` is 3 (measured), so moving one slot
turns a 2-2 `divided` into a 3-1 `strong`.

Fixed by DETECTING and REPORTING, never refusing: `model_slots.py` gains
`moderator_overlap_slots` (pure, any panel size, normalising case, whitespace
and a trailing `:online`/`:free` routing suffix) plus
`default_moderator_overlap_slots`, and `/status` gains
`moderator_slot_overlap` — slot NUMBERS only, so the field can never become a
new place a model id leaks from (the ids themselves are already public on
`/ui`, so this is not a secrecy claim). On the shipped configuration it reads
`[2]`, including on a deployment with live execution off, which grades nothing.

**Refusal was rejected, and so was changing the default.** The shipped default
IS the overlapping configuration, so a guard that raised would fail every run
on the next deploy; and pointing `debate_model_id` elsewhere moves real spend
(`costs.py` prices both debate rounds on it, and `model_slots.py` pins a
measured per-slot price table) with no measurement available while live
execution is off. That is a product-owner decision, left open in ADR-0086
along with excluding the moderator's own slot from the stance it grades —
which would change every live run's verdict from a 4-slot to a 3-slot reading
and is a rewrite of the consensus math, not a diagnostic.

**W23 — the mutation gate aborts instead of measuring. DONE** (ADR-0117).
Found by W9, whose changed functions are the first to be covered by a
schemathesis case. `mutmut` picks the tests that cover a changed function and
re-invokes pytest with their node ids, one of which is
`test_api_conforms_to_openapi_contract[GET /status]`.

**THIS ROW'S STATED CAUSE WAS FALSE and is corrected here.** It said *"pytest
cannot select a node id containing a space"*. It can: measured under this
repo's own config, a plain parametrized id carrying the same `GET /status`
text selects fine (`tests/test_lazy_nodeid_selection.py` selects one, and
would go red if that stopped being true). What actually fails is selecting a
case produced by a LAZILY EXPANDED collector. pytest matches a requested name
against the module's DIRECT children; schemathesis returns one child named
`test_api_conforms_to_openapi_contract` and produces its 13 per-operation
items only when that child is expanded, so the bracketed id matches nothing:

```
uv run pytest 'tests/contract/test_api_contract_schemathesis.py::\
  test_api_conforms_to_openapi_contract[GET /status]' --no-cov -q --collect-only
  -> ERROR: not found: ...[GET /status]
     (no match in any of [<Module test_api_contract_schemathesis.py>])
```

pytest exits 4 (usage error), `mutmut` raises
`BadTestExecutionCommandsException`, and the gate dies **before scoring a
single mutant** — exactly the "a RED gate is not evidence it measured" shape of
rule 2, and the gate's own failure text says so. PR #414 is where it first
fired; PR #413 the same night scored normally (38 survivors) because its scope
was `providers.py`, which no schemathesis case covers.

So the gate was blind for **any** diff touching a function reachable from a
documented endpoint — the `/status`, `/ready`, `/ui` and `/v1/*` handlers and
everything under them. It fired on #414, on PR #476 and again on PR #483.
Not fixed in #414: it is gate machinery and a separate concern from the guard
that found it (rule 17), and W9's changed functions were mutation-proven by
hand instead — 16 mutants, 16 killed, 0 survivors.

`tests/lazy_nodeid_selection.py` now rewrites such an argument to its parent
function before collection and keeps exactly the requested items afterwards,
so one case runs rather than the function's thirteen; an id matching nothing
is a `UsageError` naming it, never a silent full-function run. MEASURED on the
real gate, same diff both ways: without it, exit 2 and
`BadTestExecutionCommandsException` with no score; with it, exit 0 and
`mutants scored: 1 killed, 0 survived`.

**A gate that can run is not yet a gate that can fail honestly:** #464 recorded
that a truncated run still exited 0. That is row W25 (ADR-0118). #464's other
claim, an over-broad scope, did not reproduce; ADR-0118 has the command.

**W10 — #382. DONE** (ADR-0083). `_has_strong_overlap` asked for three answers
each with two partners — a DEGREE check. Necessary but not sufficient: overlap
is symmetric but not transitive, so a 4-cycle (A~C, A~D, B~C, B~D, A never~B,
C never~D) gives every text degree 2 with no mutually overlapping trio at
all — the exact 2-vs-2 split #354 exists to catch. Fixed by adding
`_overlap_adjacency` (the full pairwise matrix) and rewriting
`_has_strong_overlap` to require a genuine clique of 3 (a real triangle), not
degree alone; `_overlap_partner_counts` is now derived from the adjacency
matrix (row sums) so the two can never drift apart again. A connected-component
check was considered and rejected: the 4-cycle IS one connected component of
size 4, so it would not have fixed the reproduction — pinned directly in
`test_consensus_requires_mutual_cluster.py`. N=3 behaviour is unchanged (with
only 3 nodes, degree ≥2 already forced a full triangle). **This unblocks W4**
— #382 ends *"whoever lifts those caps must fix this primitive first,"* and
that primitive is now fixed.

**W11 — #380. DONE.** The denominator was answers recorded, so a slot that
produced nothing was absent from both sides and a run that requested four and
recorded three scored 1.0 — the product's own copy states the opposite
contract. `evaluate_layer_a`/`evaluate_run` now take an optional
`requested_slot_count` (default `None`, meaning "fall back to
`len(initial_answers)`" for callers with no run to ask); the one production
call site in `query_run_orchestration.py` passes
`len(query_run.model_slots)`.

**W12 — #379. DONE** (merged `991669b`, deployed and verified: `/status`
`last_live_charge_at` went from `"2026-08-25T17:00:10..."` to `null` on a
`live_execution: false` deployment). `last_live_charge_at` read the
`cost_guardrail_accepted` column alone; every row written before #376 carries
that type whether or not the run could spend, and unlike the 24h totals the
field is deliberately unwindowed, so it never self-healed. Now bounded by two
signals, taking whichever excludes less: a one-shot migration freezing
`MAX(id)` at the fixed code's first boot, and a query-time boundary at the
first-ever simulated charge. **Known limitation, recorded in the method's own
docstring:** this narrows the gap rather than closing it — signal 2 can only
tighten using a simulated row predating signal 1's freeze, so a ledger with no
simulated charge before first boot collapses to signal 1. Unreachable here
(`fly.toml` has never enabled live execution) and not worth a posture column
for a field no spend rail reads.

**This row's Evidence needle had to be REPLACED, and that is the lesson.** It
was pinned on `WHERE recorder = 'cost' AND event_type = '{COST_ACCEPTED_EVENT}'`
— a line the fix KEPT, appending `AND id > ...` on the next line instead of
rewriting it. So the needle never flipped, `make validate` stayed green, and
the board went on reporting `PENDING` for work that was merged, closed and in
production. That is exactly the "work that lands under a different name than
the needle" case listed under *What this cannot see* — observed for real, not
hypothetically. The needle is now `_live_charge_cutover_id`, which exists in
genuine code (the constructor assignment and the two SQL binds), not only in a
comment or docstring — the W7 trap. **When you pin a row, pick a needle the
fix must DELETE or must ADD, never a line the fix will merely edit around.**

**W13 — #268. The debate half is DONE** (ADR-0115, CHG-009, owner-approved
2026-09-21): `cost_debate_output_tokens` 400 -> 2200, measured. Two figures
this row used to carry were stale and are not repeated: the cap is 4000, not
2000, and the "9 of 495 mixes flipping CONFIRM -> BLOCK" came from a
twelve-model catalog and a different over-charge — the measured sweep for THIS
change is 715 mixes, **0** band flips and **0** bound changes, because the
bands key off the fail-safe bound, which this constant does not feed.
**#268 stays open**: its other named half, `cost_web_search_context_tokens`,
keeps its value, 2000.
The web-search half, the owner's 2026-09-24 "pick b" (CHG-012 D5), is built
(ADR-0125): the bound prices that term from its own constant, 2000, so a
later, truer setting moves the displayed estimate and no per-call band. The value is
still the owner's decision, with its own CHG row.

**W14 — #105.** No code. It closes on production evidence, not a diff.

**W15 — a dangling reference. DONE**, inside W1 (rule 17g, same file). Two
docstrings in `providers.py` pointed at `_bound_sniff_time`, which had no
definition anywhere. They now name `_read_within_budget`, which is what
actually bounds that read — verified by reading its call site
(`_read_within_budget(exc, _ERROR_BODY_SNIFF_LIMIT_BYTES,
_ERROR_BODY_SNIFF_TIMEOUT_SECONDS)`), not by recalling it, because rule 4 asks
for the REPLACEMENT to be verified and not merely the error.

**W16 — the catalog URL. DONE** (ADR-0080). `catalog_fetcher.py` hardcoded the
models endpoint while `providers.py` and `readiness.py` both built theirs from
`settings.openrouter_api_base_url`, so an operator pointing the app at a proxy
redirected every paid call and the key probe while the catalog went on talking
to the real upstream. `catalog_url()` now derives it at call time. The row's
Evidence cell still states the OPEN form — that is what `DONE` means: the
opposite of that claim now holds.

**W18 — the paid call's base URL is unguarded. DONE** (ADR-0085). Found by
review while shipping W16. `readiness.probe_key_auth` refuses to dial when the
configured base is cleartext, because it sends a bearer token — but
`providers.py` sent the *same* credential to
`f"{settings.openrouter_api_base_url}/chat/completions"` with no such check.

The package found a **second** unguarded site the original grep could not see:
`feedback_audit._call_audit_model` reads `os.environ["OPENROUTER_API_BASE_URL"]`
directly rather than the settings attribute everyone had been grepping for, and
sends the same key to the same endpoint. It also crashed outright with
`ValueError: unknown url type: '/chat/completions'` when the variable was unset,
which its own docstring said could not happen.

Both now build the endpoint through `credentialed_url.chat_completions_url`,
which returns the URL for `https` anywhere or `http` to loopback, and `None`
otherwise — the shape both call sites already document as "nothing was
dispatched, nothing can have been billed".

**W21 — a redirect carries the key off the guarded base. DONE, ADR-0090.**
Opened by W18's own review, and the reason W18's guard was not the whole
answer: `urllib.request.urlopen` follows redirects and copies every header
except `Content-Length` and `Content-Type` onto the redirected request.
Measured on loopback 2026-09-01 — a `POST` carrying `Authorization: Bearer
sk-or-SECRET` to a server answering `302` arrived at the redirect target with
that header intact. So an `https` base that redirects to `http://` still put
the key in clear, and W18's guard checked the configured base rather than the
final URL.

Sharper than a footnote, because W18's own loopback carve-out is the enabling
condition for the worst form of it: a base of `http://localhost:PORT` — the
deployment the carve-out exists to support — handed the key's final
destination to whatever held that port, since one `302` from it delivered the
bearer token to an arbitrary remote host in clear.

**The mechanism already existed in this repository.** `readiness.py` ships
`class _NoRedirect(HTTPRedirectHandler)` and
`_KEY_PROBE_OPENER = build_opener(_NoRedirect)`, with a docstring already
recording the same measurement. This was not novel work; it applies the other
half of readiness's credential policy to the two paid calls. Clubbed with W22
into one PR rather than folded into W18 itself, because both are the same
concern — hardening the credential-bearing calls' TRANSPORT, as opposed to
W18's scheme check on the CONFIGURED base — and because every existing test
doubles `providers.urlopen` directly, so both fixes land by rebinding that
same module attribute to `credentialed_url.CREDENTIAL_OPENER.open` rather
than by widening one call site at a time.

The needle used to be **PRESENT**-polarity, on the line that called the
redirect-following default opener, and a paragraph here explained why an
`ABSENT` needle naming an identifier was rejected: `scripts/check_open_work.py`
strips `#` comments but not docstrings, so a docstring merely CLAIMING the
fix would flip the row without landing it. The fix that shipped keeps that
call-site line's text unchanged on purpose (`providers.urlopen` still gets
called at both sites, under that name, so every existing test double keeps
working) and instead makes `urlopen` itself no longer the bare stdlib
function — so the PRESENT-polarity needle on the call site can no longer
distinguish fixed from broken, and the evidence cell now pins the line the
fix actually ADDS instead: `urlopen = CREDENTIAL_OPENER.open`. That is not
the identifier-in-a-sentence shape the rejected design worried about — it is
a real assignment statement, not prose a docstring would plausibly restate
without the code behind it — and it is backed by a real-socket bite-proof
(`tests/unit/test_credential_transport_guard.py`) that a doc-only claim
cannot pass.

**W22 — the Tavily key has no scheme guard either. DONE, ADR-0090.** Found by
W18's review, which asked what else carries a credential to an
operator-settable base. `providers._tavily_search` sent `Authorization:
Bearer <the operator's Tavily key>` to
`f"{settings.tavily_api_base_url.rstrip('/')}/search"`, and
`tavily_api_base_url` is a plain settings field like the OpenRouter one.
Demonstrated dialling `file:///etc/passwd/search` and
`http://attacker.example.com/search` with the key attached. Not folded into
W18 itself because it is a different credential and a different setting
(rule 17) — but clubbed with W21 into one PR, both being the same narrower
concern of hardening `providers.py`'s two credential-bearing outbound calls.
The fix is `credentialed_url.tavily_search_url`, a second builder next to
`chat_completions_url` rather than a reuse of it (the endpoint is `/search`,
not `/chat/completions`), sharing the same `is_credential_safe` scheme check
and the same `CREDENTIAL_OPENER` redirect guard W21 added.

**W19 — a timing bound that flips with machine load. DONE, ADR-0089.**
`test_the_budget_covers_the_header_phase_not_only_the_body` asserted
`wall < 4.0` against a loopback server that dribbles 72 header bytes at 0.05s.
It failed locally and passed in CI: 5 of 5 under load on 2026-08-28, a paired
interleaved comparison on 2026-08-30 where all six clean `origin/main` reps
exceeded 4.0, and **10 of 10 re-measured 2026-09-01** on a pristine
`origin/main` worktree at load average 5.6-6.0 (4.021-4.159 s). The record also
had passing halves, kept here rather than dropped: 6 of 6 idle at 3.92-3.96 s
and 11 of 11 for an independent reviewer on 2026-08-28, and 9 of 9 on a clean
`dc25c95` clone at load 2.78. Both halves are the same phenomenon — the bound
sat inside the noise.

The plan recorded here was to re-derive the margin from a fresh distribution.
**That plan was wrong, and what killed it is a comparison of the two arms
rather than more reps of one.** Moving `call_started` to after `urlopen` — the
exact defect the test names — and recording the budget handed to
`_iter_body_within_budget`, paired and interleaved, 8 pairs at load ~4.9:

| | wall (s) | budget handed to the body read (s) |
|---|---|---|
| clean `origin/main` | 4.008-4.106, mean 4.056 | **-2.508 .. -2.606** |
| clock after `urlopen` | 4.049-4.157, mean 4.091 | **+1.4999905 .. +1.4999957** |

**Four independent sessions could not agree on even the SIGN of the wall
difference** — this one found the defect slower in 6 of 8 pairs; a reviewer
found it reliably FASTER (3.868-3.928 s against clean 4.053-4.138, i.e. the
bound was GREEN on the defect and RED on the fix); two others found the arms
straddling 4.0. The wall is set by the SERVER — ~3.55 s of headers before the
client can act — and a client-side budget cannot shorten a phase already over.
The ARGUMENT separated the arms completely in every session that measured two
arms (three of the four; reviewer A's run had only the clean arm).

The fix asserts on that argument (rule 8b): the clock must have charged at
least 3.0 s to connect + request + headers, with an anti-vacuity floor that the
body read was reached exactly once and a positive partner that the charge is a
real elapsed slice of this call. Twelve source-side mutants were tried against
it — including a `max(0.0, remaining)` clamp, a different clock, a stale
timestamp and a module-level alias to dodge the spy — and every one goes red.
**It cannot flake on the quantity it measures:** the charge is floored by 71
`time.sleep(0.05)` calls that never return early, so ~3.55 s is structural;
across 28 clean reps of this session's own, spanning load 3.6-20.9, the charge
ranged 3.762-4.106 s, low 3.7617 s -- and the lowest values came at AMBIENT
load, not under the `yes` generators. That is 25% headroom over the 3.0
literal. Reviewers, reported as theirs: 34 of 34 green up to load 96, 10 of 10
at load 77, and a round-two low of 3.7146 s over 29 reps.

The needle had to be re-pinned. `PRESENT ... :: assert wall < 4.0,` also
matches `test_a_slow_dribble_is_cut_at_the_budget` (its `wall` measures 1.502 s
against a 4.0 s bound, a 2.66x margin), which is healthy and deliberately
untouched — so the row would have stayed PENDING after a correct fix. What the
change stops catching, and where that is and is not still covered, is in
ADR-0089.

**W17 — FR-004. DONE, ADR-0088.** `docs/10-functional-requirements.md` and
`docs/12-acceptance-criteria.md` both named `deepseek/deepseek-chat-v3.1` as slot
4's default. deepseek actually left `DEFAULT_MODEL_IDS` on **2026-07-25** in
commit f25696e (as `nvidia/nemotron-3-super-120b-a12b`); 3bf13a6 narrowed it two
days later to the shipped `nvidia/nemotron-3-nano-30b-a3b`. Ten live documents
carried the stale claim. No gate caught it for five weeks.

The sizing warning below held, and the census below it was **incomplete in one
direction** — worth recording, because the lesson generalises. It enumerated the
population with the exact string `deepseek/deepseek-chat-v3.1`, and two live
present-tense claims did not contain it: `docs/design-handoff/AC-CROSSWALK.md:48`
wrote the ids **without vendor prefixes** (`deepseek-chat-v3.1`), and
`docs/architecture/40-decisions.md:53` named no id at all (*"four vendor families
(OpenAI, Anthropic, Google, DeepSeek)"*). Both were found by adversarial review,
not by the grep. **A needle chosen for precision under-counts the population it
is meant to size.**

Of the files that needed reading, **ten** were corrected (the documents
asserting, in the present tense, what the product defaults to), **three** got an
additive `Superseded 2026-07-25` note rather than a rewrite because they record
something that was true on 2026-06-16 — `docs/04-problem-statement.md` (decision
D-010), `docs/13-open-questions.md` (OQ-005) and
`docs/design-handoff/README.md` (an approved mock that really does show
DeepSeek) — and **four** were left untouched: `PRODUCT_IDEA.md`,
`docs/design-handoff/Quorum Final Review.dc.html`,
`scripts/seed_feedback_audit_data.py` (demo data that already mixes in
`anthropic/claude-3-haiku`, so it asserts nothing about defaults) and this board.

Per rule 1a the row closes with a **gate**, not ten corrected sentences: Part G
of `tests/test_doc_gate_consistency.py` pins each covered document against
`product_app.model_slots.DEFAULT_MODEL_IDS` in **two** ways — slot ORDER inside
*default-claim blocks*, and set MEMBERSHIP over the whole file.

**Two review rounds, five reproduced holes, and the second round is the one
worth reading.** Round 1 broke the original whole-file extractor three ways:
`README.md` could not be covered at all (line 42 names slot 2's model a second
time for `debate_model_id`), a backticked MIME type turned a covered doc red
blaming the model slots, and emptying `_DEFAULT_SLOT_SPEC_DOCS` left the gate
green over zero documents. Round 2 then broke the FIX: block scoping had
**silently traded away** detection the whole-file version had — a stale id
appended outside the claim block of `docs/10-functional-requirements.md` passed
— and the new corpus floor's `set()` dedup fell to respelling one entry
`./README.md`, which read README twice and dropped `AC-CROSSWALK.md` from
coverage while staying green. Both are closed and pinned, which is why the gate
keeps both halves rather than replacing one with the other. **Rule 12's "expect
your own fix to introduce a defect" was correct here twice over.**

ADR-0088 has the rejected alternatives, the seven bite-proofs, and the stated
blind spots — an unbackticked id, a fenced block with no cue, setext headings,
ordered lists, a cue only in a table header, an interrupted bullet run, and a
single id under a cue. `docs/architecture/40-decisions.md` was corrected but is
**not** gated: it names a vendor family, not an id, which is also why the census
could not see it.

After the fix `git grep -l "deepseek/deepseek-chat-v3.1" | wc -l` returns
**107** (92 `tests/`, 6 `docs/archive/` + `docs/validation/`, 6 live docs, 1
`src/` `_FALLBACK_CATALOG` — which lives in `catalog_fetcher.py`, not
`model_slots.py` — 1 `PRODUCT_IDEA.md`, 1 `scripts/`). The live-docs figure fell
13 -> 6; the six are the three annotated records, the `.dc.html` mock, this
board, and ADR-0088 itself. The `tests/` figure rose 91 -> 92 because the new
gate names the retired id in its own bite-proof.

**W20 — #394. DONE, ADR-0087.** `panel_agreement()` shared the exact
structural pattern `compute_consensus_strength` had at N=1 before ADR-0083:
`len(set(stance.values())) == 1` is trivially true whenever the stance dict has
one entry, so a genuine one-answer panel read `"agreed"`. Found by review while
shipping W6/W10, deliberately not fixed there — a different function, a
different concern (rule 17). Reachable today with no unreleased feature: a run
that loses three of four slots leaves one scored slot, measured on `ee27c19` at
`_usable_stance` → `{1: 'nrr'}`, `panel_agreement` → `"agreed"`.

The **banner** was already blocked and that was re-verified by execution, not
inherited: `isConsensusResult` (`app.js`) requires `panelAgreement === "agreed"`
AND `false_consensus_preserved === false`, and the second is correctly `True` at
N=1 (`compute_consensus_strength` → `"weak"`, ADR-0083). But the row's older
"zero live impact" wording was too broad — `agreement.panel_agreement` is a
served API field, so the false claim reached every client that reads the JSON.
`panel_agreement` now returns `"undetermined"` when the stance covers fewer than
two models; N=2, 3 and 4 are byte-identical in both directions and pinned as
such.

The needle was **re-pinned** in the same change. The open form pinned
`return "agreed" if len(set(stance.values())) == 1 else "split"`, a line the fix
KEEPS — the guard is added above it — so the row would have read `PENDING`
forever with the defect closed (trap 12, measured on W12/#379). It now pins
`ABSENT … :: if len(stance) < 2:`, verified absent on `origin/main` and present
after.

**W33–W43 — the 2026-09-28..30 owner session, added 2026-09-30** (W42 and W43 found by W34's reviews; W44 split from W42 on 2026-10-03; W45 and W46 found by W33's reviews; W47 and W48 added from the owner's decisions of 2026-10-04, CHG-027; W49 found by W37's test designer; W50 by W37's product reviewer; W51 by W48's break-it reviewer; W52 from CHG-028; W53 by W52's round-2 reviewers; W54 split from W29 on 2026-10-06; W55 and W56 from CHG-029). Added
unpinned: each is built in its own pull request, and that pull request pins
the row (W34 first, pinned by ADR-0139's pull request) with the needle its change adds or deletes (memory of this repo:
"pin a needle the fix must add or delete", not a line the fix edits around).
The owner's words are in `docs/analysis/2026-09-29/OWNER-DISCUSSION-LOG.md`,
the decisions in CHG-026, the bug root causes in
`docs/analysis/2026-09-29/owner-bugs-root-causes.md`, and the plan and its
order in `docs/analysis/2026-09-29/NEXT-SESSION-PROMPT.md`. W34 is first: the
sign-out lockout is the bug the owner hit again on 2026-09-30 (M23), and
W35 depends on it.

**W68–W81 — the security review of 2026-10-13, added 2026-10-13**, with W56 widened by the owner's decision CHG-042 (a). Each row names its finding in `docs/analysis/2026-10-13-security-review.md`, which keeps what the session ran apart from what agents reported; a row resting on an agent's report is reproduced before it is built. Added unpinned, like W33–W56: each pull request pins its row with a needle its change adds or deletes. The order is CHG-042 (b): W56, W68, W55, W69, W70; the review recommends W71–W73 before live answers are switched back on and W75–W76 before W28.

**W85–W101 — the security baseline of 2026-10-17 (W82), added 2026-10-17.** Each row names its ASVS 5.0.0 items or its source in section 4 of `docs/analysis/2026-10-17-w82-security-baseline.md`, which says for each whether the session measured it, read it, or took it from an agent's report; a row resting on an agent's report is reproduced before it is built. They join the queue of W71 to W81 (CHG-055). Their order, and the order of W71 to W81, is section 5 of that file: the session's proposal, which Codex reviewed, not an owner decision. The owner's answers of 2026-10-17 are CHG-056: W87's three values, W78 to be built, and W74 to be priced before any spend. Added unpinned; each pull request pins its row.

## Parked

Work that started and stopped, or that waits on the owner, and when it resumes (ADR-0168). The first
cell is in backticks so the board's row reader never takes these for board rows.
`make parked-check` lists every item here whose resume-when has come, and every remote branch with no
open pull request. It fails when an open draft pull request, or a board row marked **STOP** or waiting
on the owner, has no line here. A resume-when is `after W71, W72` (every named row reads DONE),
`on YYYY-MM-DD`, or both joined by `or`. A resume point a session chose, not the owner, says so in
the Reason cell.

| Item | Where | Reason | Owner | Resume when |
|---|---|---|---|---|
| `W13` | issue #268; `scripts/proofs/search_context_band_sweep.py` | **STOP**: raising `cost_web_search_context_tokens` is a money decision only the owner can make (CHG-015); since ADR-0125 the sweep shows it moves the estimate and no band. Resume date: the session's, to ask the owner again | product owner | on 2026-11-16 |
| `W28` | `docs/archive/2026-10/2026-09-29-byok-pr1-plan.md` (the one file of draft #525, which was closed and its branch `w28/byok-pr1-plan` deleted after #576 was deployed, CHG-047); `docs/analysis/2026-10-17-w28-key-storage-research.md` | The six numbered W28 decisions are made: decision 3 (CHG-059) and decisions 1, 2, 4, 5 and 6, with the four tensions and four earlier statements (CHG-075 to CHG-080, 2026-10-17), recorded as ADR-0180; the abuse-limit numbers, audit retention, privacy wording, which law applies and page copy are not decided (ADR-0180, "Not decided"). The one W28 analysis is `docs/analysis/2026-10-17-w28-key-storage-research.md`. The owner put W28 after the small live rows W85, W86, W100, W87, W88 and W80 and after W75 and W76, in a fresh session (CHG-061), started from `docs/archive/2026-10/CONTINUE-BYOK-BUILD-W28-PROMPT.md`. Before the build the owner runs the free OpenRouter sign-in trial in section 16 of that analysis. From W82, for the build to keep in mind: on Fly the master key (a Fly secret) and the database sit on the same machine, so whoever can deploy or SSH reads both (section 3 of `docs/analysis/2026-10-17-w82-security-baseline.md`); ADR-0180 bounds that damage rather than preventing it | product owner | after W85, W86, W100, W87, W88, W80, W75, W76 |
| `W74` | the board row | The owner chose to price the attack suite first (CHG-056 (a)): the session counts the attacks and prices them from OpenRouter's public price list, then asks the owner for one exact amount; no paid call before that. Resume point: the session's, after the AI-input row W73 in the order of `docs/analysis/2026-10-17-w82-security-baseline.md` | product owner | after W73 |
| `W94` | the board row | Every limit in the row is the owner's to set, and the session has no measured basis to propose values yet. Resume point: the session's, once the live rows W85, W86, W100, W87, W88, W80, W90 and W89 are done, to propose measured values and ask | product owner | after W85, W86, W100, W87, W88, W80, W90, W89 |
| `W113` | the local branch `w113/owner-quote-check` (never pushed; no pull request) | Paused for redesign under CHG-102: it checks quoted answers, and public rows no longer quote them. Resume point: CHG-103's order, after the public-content rules of W117 | product owner | after W117 |
| `W114` | pull request A merged as #591 (`e6d5300`); pull request B's first branch, `w87-3/unchecked-cookie`, is local only, and its reviewed plan is in the owner's private notes | Pull request A shipped the core as #591 (CHG-088 (l)). Pull request B, the sign-out while a session cannot be checked, is built from its table-first plan with CHG-098 (replacing CHG-096) and the race in CHG-088 (m), after W117, W118, W62, W121, W120 and W119 (CHG-103) | product owner | after W117, W118, W62, W121, W120, W119 |

## What is deliberately NOT on this board

The archived demo-readiness prompt
(`docs/archive/2026-08/CONTINUE-DEMO-READINESS-ULTRACODE-PROMPT.md`) ends
*"Stop after F. Items 6–10 need product judgement the human owns."* Item 6 is
W5. Items 7–10 are described only in a plan outside this repository and are not
work a session may select; they are not rows here, and their absence is a
decision rather than an oversight.

## Order and what may run in parallel

**W1 (+W15) is DONE.** The order below is what the board said before the
product owner directed W1 next on 2026-08-30, and it is kept because its
reasoning still governs what comes after.

**Clear the independent, issue-backed rows first, then W1 (+W15).**

The earlier order read `W1 → W2 → W3`. That lane is the largest item, then one
that cannot be validated without spend, then a row now formally deferred
(ADR-0081) — so nothing ships for a long time. W12 (#379) took that advice and
is now **DONE**; **W11 (#380) is the remaining issue-backed row with no
dependencies** and closes an open issue at $0, so it is the obvious next pick.
(W13/#268 also has no dependency, but it is **STOP** — it moves a cost
guardrail.) W20 (#394) is likewise unblocked and cheap, though its own row
records zero live impact today.

**W6 and W10 shipped as ONE clubbed package** (rule 17g, ADR-0083): both lived
in `synthesis_consensus.py` and both were the consensus verdict disagreeing
with itself. One reviewer, one deploy. W10 unblocked W4, which no longer waits
on anything from this cluster.

**Size W17 before selecting it — the string is everywhere, the defect is not.**
`git grep -l "deepseek/deepseek-chat-v3.1" | wc -l` returns **113** files
(measured 2026-08-28), which reads alarming and mostly is not. The breakdown
sums to 113 exactly, and a first draft of this table did not — it said "16 live
docs" and double-counted `docs/validation/`:

| Where | Files | Is it a defect? |
|---|---|---|
| `tests/` | 91 | **No** — fixture and catalog data. It is a real OpenRouter model, just not a default slot. |
| live `docs/` (excluding `archive/` and `validation/`) | 13 | **Check each** — this is the real work. Two are under `docs/design-handoff/`, one of them `.dc.html`. |
| `docs/archive/` + `docs/validation/` | 6 | **No** — records of runs that really happened; editing them would falsify history |
| `src/` | 1 | **No** — `_FALLBACK_CATALOG` legitimately lists it |
| `PRODUCT_IDEA.md` | 1 | **Check** |
| `scripts/` | 1 | **Check** |

Reproduce the live-docs row with:
`git grep -l "deepseek/deepseek-chat-v3.1" -- 'docs/*' | grep -v '^docs/archive/\|^docs/validation/' | wc -l`

The defect is narrow: **FR-004 and its acceptance criterion name it as a DEFAULT
SLOT**, which `model_slots.py` contradicts. The work is reading those 15
check-each files and correcting only the ones making that claim — not a global
replace, which would break fixtures and rewrite history.

**W1 is MEASURED, and W2's dependency on it is discharged.** The
owner-authorised window that turns W1 from "tested" into "measured" has been
run twice, so this is no longer the step between W1 and W2:

- 2026-08-31 (`64a3b14`): `usage_absent: false` and `stream_terminator: "done"`
  on **24 of 24** live production calls, across six distinct models.
- 2026-09-01 (`014b010`): three runs on three varied question shapes, every one
  `live_count` 4/4 with `cost_source: "measured"` and zero `failed_steps` — so
  no call fell back and no timeout demoted a receipt to `estimated`.

This paragraph read *"latent-correct, not observed"* for two days after the
first of those windows closed, and a session then recommended spending money to
re-measure it. Nothing compared the sentence to the commit log. That is the
failure mode rule 1a exists for.

**W3's deferral is discharged** — ADR-0102 moved the ladder on 2026-09-07 (see
the W3 paragraph; its remainder is the two token constants). **W2 is BUILT
and has run in production** (four peer-shaped runs, see the W2 paragraph above);
the sentence this change replaces said it was unbuilt; that was overtaken on
2026-09-03 (`5aed777`, `_build_peer_round`) and stood until this change merged.
ADR-0093's decision 3 (a `kind="critique"` receipt row) shipped: the row is
built in `src/product_app/costs.py` (grep `kind="critique"`).

W4 no longer waits on anything (W10 is done), and no longer overlaps W1
either: W1 has landed and left `Field(ge=1, le=4)` in `providers.py`
untouched. **W4 and W7
both hold `main.py`, `app.js` and `workspace.html`: sequence them.** W16 collided
with W4 only through `tests/unit/test_risk_constant_pins.py`; it shipped first,
so that collision is gone.

Before any parallel dispatch, assign centrally: **ADR numbers, `openapi.yaml`
ownership, the money constants, and the `Field(ge=1, le=4)` bound.** Two
orchestrators here once both created ADR-0072, each green because neither could
see the other. A worktree isolates files; it does not isolate shared namespaces.

## Updating this board

**In the same pull request that changes an item's state.** The gate forces it:
when the tree moves, the derived column moves with it, and `--check` refuses
until the file is regenerated.

**Do not edit the State column.** Run `make open-work-write`. There is no way to
mark a row done by hand, which is the entire point — two earlier designs let a
one- and then a two-token edit declare the whole board finished.

When you re-verify the rows, stamp a commit on the `Verified at:` line. Do not
stamp it without re-reading — the drift limit is deliberately loose precisely so
that re-stamping stays a real act.

**Stamp a commit that is already on `main`, never one from your branch.** This
repository SQUASH-merges, so every commit you make on a branch is discarded the
moment the branch lands. Measured 2026-08-30: W1 stamped its own branch commit
`2350e59`, the squash produced `59f402a`, and `main` went RED across `Tests`,
`CI` and every `Deploy` run for that SHA — the deploy gate correctly reporting a
*stranded merge* rather than deploying. Nothing reached production, but `main`
was broken until a follow-up re-stamped it.

So either stamp the commit your branch was cut FROM, or re-stamp after the
merge. "Stamp the current commit" is the natural reading and it is the wrong
one here.

**The gate now catches that on the pull request instead of on `main`** (#402,
ADR-0092). Until then it only asked whether the anchor was an ancestor of
`HEAD` — and on a feature branch a commit made ON that branch is one, so it
passed the PR and refused only after the squash discarded it. It now ALSO
requires the anchor to be an ancestor of at least one `main` ref this checkout
can resolve: `origin/main`, then any other configured remote's `main`, then the
local `refs/heads/main`. The report line names the ref that answered, so a
skip is never silent.

Two consequences worth knowing before you see the error. A `main` ref that has
not been fetched refuses an anchor that really is on `main` — that fact is not
derivable offline, so `git fetch` is the first thing to try, though it does not
always clear it (when `origin` is a fork that is itself behind, fetching it
advances nothing). And a clone with no `main` ref at all but a remote
configured is refused rather than skipped; measured on git 2.54.0,
`git fetch origin main` does NOT create `refs/remotes/origin/main` there, while
`git remote set-branches --add origin main && git fetch origin` does.

**Being on `main` is necessary, not sufficient**: the anchor must ALSO be within
`MAX_DRIFT_COMMITS` (60) first-parent commits of HEAD, which at the time of
writing reaches back about 17 days. An anchor that is on `main` but older than
that fails with a different message. Both messages in
`scripts/check_open_work.py` now say which commit to pick, because a failing
author reads the error, not this paragraph — that omission is what let W1 stamp
a branch commit while the gate's own text said "stamp the current commit".

Adding or removing a row means editing the count sentence above in the same
change; the gate compares both numbers against the table.
