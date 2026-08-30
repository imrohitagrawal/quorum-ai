# 65 · Open work — the board

**This is the source of truth for what is open, what it is blocked by, and what
proves each row's state.** Issues on GitHub are the mirror; this file is the
original, because a gate and an offline agent can read it and cannot read `gh`.

Verified at: `59f402a7c951b90e2af376558f71ff4701b831a1`

The board holds **19** rows, **4** of them unpinned.

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
- **The four unpinned rows.** Nothing is checked about them.
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
| W9 | Guard the moderator model overlapping a panel slot | PENDING | `ABSENT src/product_app/model_slots.py :: debate_model_id` | — | — |
| W10 | Consensus certifies a mutual cluster it never checked | DONE | `PRESENT src/product_app/synthesis_consensus.py :: return sum(1 for partners in counts if partners >= 2) >= 3` | #382 | — |
| W11 | Completeness divides by answers recorded, not slots requested | PENDING | `PRESENT src/product_app/evaluation.py :: slot_count = len(initial_answers)` | #380 | — |
| W12 | `last_live_charge_at` reports a pre-#376 row as a live charge | DONE | `ABSENT src/product_app/feedback_store.py :: _live_charge_cutover_id` | #379 | — |
| W13 | Nothing bounds a call's INPUT — **STOP** | UNPINNED | `—` | #268 | — |
| W14 | Close the 5xx possibly-billed premise with data | UNPINNED | `—` | #105 | production logs |
| W15 | `_bound_sniff_time` is referenced and does not exist | DONE | `PRESENT src/product_app/providers.py :: _bound_sniff_time` | — | — |
| W16 | The catalog fetcher hardcodes the models URL | DONE | `PRESENT src/product_app/catalog_fetcher.py :: OPENROUTER_CATALOG_URL = "https://openrouter.ai/api/v1/models"` | — | — |
| W17 | FR-004 names a model we do not ship | PENDING | `PRESENT docs/10-functional-requirements.md :: deepseek/deepseek-chat-v3.1` | — | — |
| W18 | The paid call sends the API key to a configured base with no scheme guard | PENDING | `PRESENT src/product_app/providers.py :: url=f"{settings.openrouter_api_base_url}/chat/completions"` | — | — |
| W19 | A provider-timeout bound fails locally and passes in CI | PENDING | `PRESENT tests/unit/test_provider_call_time_budget.py :: assert wall < 4.0,` | — | — |
| W20 | `panel_agreement()` reports "agreed" for a genuine N=1 panel | PENDING | `PRESENT src/product_app/synthesis_consensus.py :: return "agreed" if len(set(stance.values())) == 1 else "split"` | #394 | — |

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

**W9 — moderator/slot overlap.** `debate_model_id` defaults to
`anthropic/claude-haiku-4.5`, which is also slot 2's default. Nothing forbids
the moderator being a panel member grading its own answer. `model_slots.py`
mentions `debate_model_id` nowhere, which is the absence the needle pins.

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

**W11 — #380.** The denominator is answers recorded, so a slot that produced
nothing is absent from both sides and a run that requested four and recorded
three scores 1.0. The product's own copy states the opposite contract.

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

**W18 — the paid call's base URL is unguarded.** Found by review while shipping
W16. `readiness.probe_key_auth` refuses to dial when the configured base is
cleartext, because it sends a bearer token — but `providers.py` sends the *same*
credential to `f"{settings.openrouter_api_base_url}/chat/completions"` with no
such check. One of the two credential-bearing calls is guarded and the other is
not. Pre-existing, not introduced by W16, and deliberately not fixed there:
W16's concern is the catalog, and the paid path deserves its own reviewer.

**W19 — a timing bound that flips with machine load.**
`test_the_budget_covers_the_header_phase_not_only_the_body` asserts
`wall < 4.0` against a loopback server that dribbles headers. Measured both ways
on the same box on 2026-08-28:

| Condition | Result |
|---|---|
| under concurrent load (full suites + review agents running) | **5 of 5 failed**, 4.13–4.18s |
| idle | **6 of 6 passed**, 3.92–3.96s — and an independent reviewer got 11 of 11 |

It also failed on a clean `git archive` of `origin/main` while loaded, so no
branch causes it. CI passes it. **A red result here is therefore NOT
automatically W19** — re-run it isolated on an idle machine before dismissing
it, because the margin is about 2% and a real regression would look the same.

**Re-measured 2026-08-30, and the "idle passes" half no longer holds on this
box.** Hit while shipping W1, where it mattered: W1 rewrites this exact code
path, so the table above would have licensed dismissing a real regression. What
settled it was a PAIRED, interleaved comparison against a clean
`git archive origin/main`, 6 reps each, alternating, at load average ~5:

| | wall (s) |
|---|---|
| clean `origin/main` | 4.095 4.116 4.117 4.145 4.026 4.091 — mean **4.098** |
| the W1 branch | 4.070 4.089 4.025 4.085 4.086 4.083 — mean **4.073** |

**All 6 clean-`main` reps exceed the 4.0 bound**, and the branch is if anything
FASTER (lower in 5 of 6 paired reps). An earlier draft of this paragraph said
"9 of 9 idle failures"; the table beside it shows 6 reps per arm at load
average ~5, which is not idle and is not nine, so the sentence is now the one
the data supports. (An independent reviewer separately reproduced 9 of 9 on a
clean `dc25c95` clone at load 2.78, 4.052-4.132 s — consistent, but that run is
not the table above and is not quoted as if it were.) So the bound now fails on
a quiet machine too — this box has drifted past the 2% margin — and it is still
not any diff's fault. Whoever fixes this row should re-derive the margin from a fresh
distribution rather than nudging `4.0` upward: the number in the assertion has
never been anything but the machine it was written on.
Either widen the bound with a re-derived margin or make it CI-only — but measure
first: its partner lower bound is what proves the dribble really happened.

**W17 — FR-004.** `docs/10-functional-requirements.md` and
`docs/12-acceptance-criteria.md` both name `deepseek/deepseek-chat-v3.1` as slot
4's default; `model_slots.py` ships `nvidia/nemotron-3-nano-30b-a3b` and its own
comment says "replaces deepseek". No gate catches it.

**W20 — #394.** `panel_agreement()` shares the exact structural pattern
`compute_consensus_strength` had at N=1 before ADR-0083: `len(set(stance.values()))
== 1` is trivially true whenever the stance dict has one entry, so a genuine
one-answer panel still reads `"agreed"`. Found by review while shipping W6/W10,
deliberately not fixed there — a different function, a different concern
(rule 17). **Confirmed zero live impact**: `isConsensusResult` (`app.js`)
requires `panelAgreement === "agreed"` AND `false_consensus_preserved ===
false`; the second is now correctly `True` at N=1 (blocking the green banner)
regardless of what this function reports.

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
squash produced `59f402a`, and `main` went RED across `Tests`, `CI` and all
three `Deploy` runs — the deploy gate correctly reporting a *stranded merge*
rather than deploying. Nothing reached production, but `main` was broken until
a follow-up re-stamped it.

So either stamp the commit your branch was cut FROM, or re-stamp after the
merge. "Stamp the current commit" is the natural reading of the sentence above
and it is the wrong one on a squash-merge repository.

Adding or removing a row means editing the count sentence above in the same
change; the gate compares both numbers against the table.
