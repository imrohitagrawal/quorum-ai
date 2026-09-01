# 65 · Open work — the board

**This is the source of truth for what is open, what it is blocked by, and what
proves each row's state.** Issues on GitHub are the mirror; this file is the
original, because a gate and an offline agent can read it and cannot read `gh`.

Verified at: `33c53793e2af19f0de73510ebe3dc49481219988`

The board holds **22** rows, **5** of them unpinned.

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
- **The five unpinned rows.** Nothing is checked about them.
- **A row that should exist and does not.**

Review remains the primary defence — measured here, 0 of 16 `src/` defects were
caught by any automated check and 10 of 16 by adversarial review
(`docs/metrics/defect-discovery-audit.md`).

## The board

| ID | Item | State | Evidence | Issue | Depends on |
|----|------|-------|----------|-------|------------|
| W1 | Stream the provider call (was "B2") | DONE | `ABSENT src/product_app/providers.py :: "stream": True` | — | — |
| W2 | Peer critique: the answer models critique each other, two rounds | PENDING | `PRESENT src/product_app/debate.py :: model_id=settings.debate_model_id,` | #290 | W1 |
| W3 | Re-set the money constants against a measured bound — **STOP** | PENDING | `PRESENT src/product_app/costs.py :: DAILY_CAP_USD = Decimal("0.20")` | — | W2 |
| W4 | Variable panel size N ∈ {2,3,4} | PENDING | `PRESENT src/product_app/model_slots.py :: if len(model_ids) != EXPECTED_SLOT_COUNT:` | — | — (W10 done) |
| W5 | Quick-answer N=1 mode | UNPINNED | `—` | — | W4 |
| W6 | A panel of one reports strong consensus | DONE | `ABSENT src/product_app/synthesis_consensus.py :: if len(stance) == 1:` | #383 | — |
| W7 | Google sign-in and logout | UNPINNED | `—` | — | — |
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
| W23 | The mutation gate cannot run when a changed function is covered by a schemathesis case | UNPINNED | `—` | — | — |

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

**W2 — peer critique (#290).** Today there is exactly one debate caller and it
always dispatches `settings.debate_model_id`; `debate.py` says so in a comment
next to the usage stamp #290 already added. Blocked on W1 because the #290 spike
measured **7 of 8** probe calls exceeding the 8s timeout on wall clock —
`nvidia/nemotron`'s first rep at 6.385s does not — and 6 of 8 on the per-`recv`
gap. (The approved plan and two session handoffs say "8 of 8"; ADR-0078 and
`docs/analysis/2026-08-26-b3-timeout-probe.md` both correct it against the
probe's own table. The corrected figure is the one used here.) Streaming
collapsed the gap to 0.478 / 0.208 s on a paired sample. Building critique first
ships a feature that pays for discarded tokens and demotes every receipt to
`estimated`.

**W3 — the money constants. STOP, and DEFERRED by decision (ADR-0081).**
The product owner decided 2026-08-28: **the three constants do not move until
#290 is built and its cost is measured.** `SOFT_THRESHOLD_USD = 0.15`,
`HARD_LIMIT_USD = 0.25`, `DAILY_CAP_USD = 0.20` stay as they are. The earlier
approved shape (`SOFT ≈ 0.20 / DAILY_CAP ≈ 0.60 / HARD ≈ 0.75`) prices a feature
that does not exist, on a projection that is not measured.

Measured headroom today, judge-ON: a default question's bound is **0.1134**
against a `0.15` line — about **3.7 cents**. That margin is the number to watch;
W13 (#268) is a change that would eat into it. `SOFT_THRESHOLD_USD <
DAILY_CAP_USD < HARD_LIMIT_USD` is mandatory or the confirmation band is dead
code. When W2 lands, re-measure and bring a number back with its measurement.

**W4 — variable panel size.** `Field(ge=1, le=4)` appears at three sites
(`debate.py` twice, `providers.py` once) and they move together. **No longer
blocked**: #382 ended *"whoever lifts those caps must fix this primitive
first,"* and W10 fixed it (ADR-0083). The CSS is cheaper than feared:
`.model-slot-grid` is `grid-template-columns: 1fr 1fr` with an existing
single-column media query, not a 2×2 `grid-template-areas`, so N=2 and N=3
already reflow (verified 2026-08-28).

**W5 — N=1.** Unreachable while `_validate_model_id_list` rejects any count but
four. Unpinned: no honest needle exists before the shape is chosen.

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
makes the first open of an existing read-only database raise. Unpinned: its
first needle was the bare word `google`, which review satisfied by adding a
*comment* to `auth.py` saying the work was still to do. A needle that a comment
can satisfy is not evidence.

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

**W23 — the mutation gate aborts instead of measuring.** Found by W9, whose
changed functions are the first to be covered by a schemathesis case.
`mutmut` picks the tests that cover a changed function and re-invokes pytest
with their node ids. Schemathesis parametrises by `"{METHOD} {PATH}"`, so one
of those ids is
`test_api_conforms_to_openapi_contract[GET /status]` — and **pytest cannot
select a node id containing a space**, even though `--collect-only` lists it.
Measured on the real tree, not only inside `./mutants/`:

```
uv run pytest 'tests/contract/test_api_contract_schemathesis.py::\
  test_api_conforms_to_openapi_contract[GET /status]' --no-cov -q --collect-only
  -> no tests collected in 0.20s
```

pytest exits 4 (usage error), `mutmut` raises
`BadTestExecutionCommandsException`, and the gate dies **before scoring a
single mutant** — exactly the "a RED gate is not evidence it measured" shape of
rule 2, and the gate's own failure text says so. PR #414 is where it first
fired; PR #413 the same night scored normally (38 survivors) because its scope
was `providers.py`, which no schemathesis case covers.

So the gate is blind for **any** future diff touching a function reachable from
a documented endpoint — the `/status`, `/ready`, `/ui` and `/v1/*` handlers and
everything under them. Not fixed in #414: it is gate machinery and a separate
concern from the guard that found it (rule 17), and W9's changed functions were
mutation-proven by hand instead — 16 mutants, 16 killed, 0 survivors.

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

**W13 — #268. STOP.** Unpinned: the fix's shape is not yet chosen. Marked STOP
because the issue's own subject is a cost guardrail — it identifies
`cost_debate_output_tokens = 400` as a point estimate five times below the
enforced 2000-token cap, and measures **9 of the 495** shipped-catalog four-slot
mixes flipping `CONFIRM` → `BLOCK` on the over-charge alone. `BLOCK` is a hard
refusal, so this is a guardrail move, not a bug fix.

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

**Do not attempt W2 or W3 while `OPENROUTER_LIVE_EXECUTION_ENABLED` is false.**
W2's shape depends on W1's measured streaming behaviour, and W3 is deferred.
W1 is built and, once this lands, merged — but it is **latent-correct, not
observed**: with
live execution off nothing exercises the streaming path in production. The
owner-authorised measurement window is what turns W1 from "tested" into
"measured", and it is the step between W1 and W2 — not an optional follow-up.

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
repository SQUASH-merges, so every commit you make on a branch is discarded and
the anchor check (`is not an ancestor of HEAD`) fails the moment the branch
lands. Measured 2026-08-30: W1 stamped its own branch commit `2350e59`, the
squash produced `59f402a`, and `main` went RED across `Tests`, `CI` and every
`Deploy` run for that SHA — the deploy gate correctly reporting a *stranded
merge* rather than deploying. Nothing reached production, but `main` was broken
until a follow-up re-stamped it.

So either stamp the commit your branch was cut FROM, or re-stamp after the
merge. "Stamp the current commit" is the natural reading and it is the wrong
one here.

**Being on `main` is necessary, not sufficient**: the anchor must ALSO be within
`MAX_DRIFT_COMMITS` (60) first-parent commits of HEAD, which at the time of
writing reaches back about 17 days. An anchor that is on `main` but older than
that fails with a different message. Both messages in
`scripts/check_open_work.py` now say which commit to pick, because a failing
author reads the error, not this paragraph — that omission is what let W1 stamp
a branch commit while the gate's own text said "stamp the current commit".

Adding or removing a row means editing the count sentence above in the same
change; the gate compares both numbers against the table.
