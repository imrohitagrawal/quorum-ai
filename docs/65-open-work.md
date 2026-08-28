# 65 · Open work — the board

**This is the source of truth for what is open, what it is blocked by, and what
proves each row's state.** Issues on GitHub are the mirror; this file is the
original, because a gate and an offline agent can read it and cannot read `gh`.

Verified at: `e115d92ac0703ca3ce6faa6174a13de0edfae1bd`

The board holds **18** rows, **4** of them unpinned.

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
| W1 | Stream the provider call (was "B2") | PENDING | `ABSENT src/product_app/providers.py :: "stream": True` | — | — |
| W2 | Peer critique: the answer models critique each other, two rounds | PENDING | `PRESENT src/product_app/debate.py :: model_id=settings.debate_model_id,` | #290 | W1 |
| W3 | Re-set the money constants against a measured bound — **STOP** | PENDING | `PRESENT src/product_app/costs.py :: DAILY_CAP_USD = Decimal("0.20")` | — | W2 |
| W4 | Variable panel size N ∈ {2,3,4} | PENDING | `PRESENT src/product_app/model_slots.py :: if len(model_ids) != EXPECTED_SLOT_COUNT:` | — | W10 |
| W5 | Quick-answer N=1 mode | UNPINNED | `—` | — | W4 |
| W6 | A panel of one reports strong consensus | PENDING | `PRESENT src/product_app/synthesis_consensus.py :: if len(sizes) == 1 or max(sizes.values()) >= _required_cluster(len(stance)):` | #383 | — |
| W7 | Google sign-in and logout | UNPINNED | `—` | — | — |
| W9 | Guard the moderator model overlapping a panel slot | PENDING | `ABSENT src/product_app/model_slots.py :: debate_model_id` | — | — |
| W10 | Consensus certifies a mutual cluster it never checked | PENDING | `PRESENT src/product_app/synthesis_consensus.py :: return sum(1 for partners in counts if partners >= 2) >= 3` | #382 | — |
| W11 | Completeness divides by answers recorded, not slots requested | PENDING | `PRESENT src/product_app/evaluation.py :: slot_count = len(initial_answers)` | #380 | — |
| W12 | `last_live_charge_at` reports a pre-#376 row as a live charge | PENDING | `PRESENT src/product_app/feedback_store.py :: WHERE recorder = 'cost' AND event_type = '{COST_ACCEPTED_EVENT}'` | #379 | — |
| W13 | Nothing bounds a call's INPUT — **STOP** | UNPINNED | `—` | #268 | — |
| W14 | Close the 5xx possibly-billed premise with data | UNPINNED | `—` | #105 | production logs |
| W15 | `_bound_sniff_time` is referenced and does not exist | PENDING | `PRESENT src/product_app/providers.py :: _bound_sniff_time` | — | — |
| W16 | The catalog fetcher hardcodes the models URL | DONE | `PRESENT src/product_app/catalog_fetcher.py :: OPENROUTER_CATALOG_URL = "https://openrouter.ai/api/v1/models"` | — | — |
| W17 | FR-004 names a model we do not ship | PENDING | `PRESENT docs/10-functional-requirements.md :: deepseek/deepseek-chat-v3.1` | — | — |
| W18 | The paid call sends the API key to a configured base with no scheme guard | PENDING | `PRESENT src/product_app/providers.py :: url=f"{settings.openrouter_api_base_url}/chat/completions"` | — | — |
| W19 | A provider-timeout bound fails locally and passes in CI | PENDING | `PRESENT tests/unit/test_provider_call_time_budget.py :: assert wall < 4.0,` | — | — |

**STOP** marks a row that cannot be finished without a human decision — a money,
cost or safety guardrail value that only real measurement could justify. Do not
move one of those numbers as a side effect of any other package.

## What each row is

**W1 — stream the provider call.** `providers.py` posts a non-streaming request
and reads the whole body. `_read_body_within_budget` is the template for
deadline discipline, not the implementation. `_extract_message_content`,
`_extract_usage`, `_finish_reason_indicates_truncation` and
`_extract_citations` are reused unchanged once deltas are reassembled — streamed
frames carry `choices[0].delta.content`, not `choices[0].message.content`. Keep
the `product_app.providers.urlopen` seam: it appears on **43 lines across 14
test files** (`grep -rn "product_app.providers.urlopen" tests/`; an inherited
figure of "34 patch sites across 15 test files" matches no reading of the tree
and is not repeated here). Keep `openrouter_call_budget_seconds`: keep-alives
defeat a per-`recv` timeout once streaming lands, so the total budget becomes
the only wall-clock brake on a paid call. **W15 rides inside this package** —
the same file. Whether to reach for an SDK instead is an open design question;
the "two failed hand-rolled attempts" bar that an inherited document attributed
to ADR-0029 is **not in ADR-0029**, which is about the citation grounding score
and never mentions an SDK.

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
(`debate.py` twice, `providers.py` once) and they move together. **Blocked on
W10**: #382 ends *"whoever lifts those caps must fix this primitive first"*, and
W4 is the row that lifts them. The CSS is cheaper than feared:
`.model-slot-grid` is `grid-template-columns: 1fr 1fr` with an existing
single-column media query, not a 2×2 `grid-template-areas`, so N=2 and N=3
already reflow (verified 2026-08-28).

**W5 — N=1.** Unreachable while `_validate_model_id_list` rejects any count but
four. Unpinned: no honest needle exists before the shape is chosen.

**W6 — #383.** Reachable today on a degraded four-slot run where three slots
failed. **Not blocked by W4.**

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

**W10 — #382.** `_has_strong_overlap` asks for three answers each with two
partners. Necessary but not sufficient: that admits a shape with no mutually
overlapping trio. Latent at N=4 today, live the moment W4 lifts the bound —
which is why W4 waits on this.

**W11 — #380.** The denominator is answers recorded, so a slot that produced
nothing is absent from both sides and a run that requested four and recorded
three scores 1.0. The product's own copy states the opposite contract.

**W12 — #379.** Unlike the 24h totals it never self-heals.

**W13 — #268. STOP.** Unpinned: the fix's shape is not yet chosen. Marked STOP
because the issue's own subject is a cost guardrail — it identifies
`cost_debate_output_tokens = 400` as a point estimate five times below the
enforced 2000-token cap, and measures **9 of the 495** shipped-catalog four-slot
mixes flipping `CONFIRM` → `BLOCK` on the over-charge alone. `BLOCK` is a hard
refusal, so this is a guardrail move, not a bug fix.

**W14 — #105.** No code. It closes on production evidence, not a diff.

**W15 — a dangling reference.** Two docstrings in `providers.py` point at
`_bound_sniff_time`, which has no definition anywhere. Doc-only.

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

**W19 — a timing bound that is machine-dependent.**
`test_the_budget_covers_the_header_phase_not_only_the_body` asserts
`wall < 4.0` against a loopback server that dribbles headers. Measured
2026-08-28 on this machine: **5 of 5 runs failed at 4.13–4.18s**, and it fails
identically on a clean `git archive` of `origin/main`, so it is **not** caused
by any current branch. CI passes it. A bound that close to its own input is a
coin toss on a slower machine, and the next session will lose time deciding
whether it broke something. Either widen it with a re-derived margin or make it
CI-only — but measure first, because the bound is load-bearing: its partner
lower bound is what proves the dribble really happened.

**W17 — FR-004.** `docs/10-functional-requirements.md` and
`docs/12-acceptance-criteria.md` both name `deepseek/deepseek-chat-v3.1` as slot
4's default; `model_slots.py` ships `nvidia/nemotron-3-nano-30b-a3b` and its own
comment says "replaces deepseek". No gate catches it.

## What is deliberately NOT on this board

The archived demo-readiness prompt
(`docs/archive/2026-08/CONTINUE-DEMO-READINESS-ULTRACODE-PROMPT.md`) ends
*"Stop after F. Items 6–10 need product judgement the human owns."* Item 6 is
W5. Items 7–10 are described only in a plan outside this repository and are not
work a session may select; they are not rows here, and their absence is a
decision rather than an oversight.

## Order and what may run in parallel

**Clear the independent, issue-backed rows first, then W1 (+W15).**

The earlier order read `W1 → W2 → W3`. That lane is the largest item, then one
that cannot be validated without spend, then a row now formally deferred
(ADR-0081) — so nothing ships for a long time. Meanwhile W12 (#379), W11 (#380),
W6 (#383) and W10 (#382) have no dependencies at all and close four open issues
at $0.

**Club W6 and W10 into ONE package** (rule 17g): both live in
`synthesis_consensus.py` and both are the consensus verdict disagreeing with
itself. One reviewer, one deploy. W10 also unblocks W4.

**Size W17 before selecting it — the string is everywhere, the defect is not.**
`git grep -l "deepseek/deepseek-chat-v3.1" | wc -l` returns **113 files**
(measured 2026-08-28), which reads alarming and mostly is not:

| Where | Files | Is it a defect? |
|---|---|---|
| `tests/` | 91 | **No** — fixture and catalog data. `deepseek/deepseek-chat-v3.1` is a real OpenRouter model; it is simply not a default slot. |
| live `docs/*.md` | 16 | **Check each** — this is the real work |
| `docs/archive/`, `docs/validation/` | 6 | **No** — records of runs that really happened; changing them would falsify history |
| `src/` | 1 | **No** — `_FALLBACK_CATALOG` legitimately lists it as an available model |

The defect is narrow: **FR-004 and its acceptance criterion name it as a
DEFAULT SLOT**, which `model_slots.py` contradicts. The work is reading the 16
live docs and correcting only the ones making that claim — not a global replace,
which would break fixtures and rewrite history.

**Do not attempt W2 or W3 while `OPENROUTER_LIVE_EXECUTION_ENABLED` is false.**
W2's shape depends on W1's measured streaming behaviour, and W3 is deferred.

Cleanly disjoint: **W1 + W6**. W1 + W4 is nearly parallel — the single overlap
is `Field(ge=1, le=4)` in `providers.py` — but W4 now waits on W10. **W4 and W7
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

When you re-verify the rows, stamp the current commit on the `Verified at:`
line. Do not stamp it without re-reading — the drift limit is deliberately loose
precisely so that re-stamping stays a real act.

Adding or removing a row means editing the count sentence above in the same
change; the gate compares both numbers against the table.
