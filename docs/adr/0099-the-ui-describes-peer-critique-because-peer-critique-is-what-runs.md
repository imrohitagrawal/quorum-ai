# ADR-0099: The UI describes peer critique, because peer critique is what runs

## Status

Accepted - 2026-09-04.

Supersedes **ADR-0032 decisions 3 and 4** (the landing subhead naming a
moderator model, and the chip calling peer critique "planned, not yet built").
ADR-0032 decision 5 - the eyebrow and the h1 - is a product-owner decision and
is UNCHANGED. ADR-0032 decision 2 (FR-008's Behavior line retained verbatim with
an implementation-status line beneath it) stands; only the status line's VALUE
moves, from BUILT, NOT YET ENABLED to BUILT AND ENABLED.

Does not supersede ADR-0063: its removal of the position table was about
per-model attribution being unobservable, and ADR-0096 already recorded that
`self_assessment` observes it. Restoring that table remains a separate package.

**Authorises nothing.** It carries no `**Authorises:**` line and may not be
cited to sanction a live-execution posture.

## Context

The product owner opened the running product on 2026-09-03 and found it
describing a product that no longer exists.

`PEER_CRITIQUE_ENABLED` went true in production at 2026-09-03T07:51:25Z. From
that moment the four answer models critique each other and may revise their own
answers (#290, ADR-0093/0095/0096), and on a fully-eligible run NO moderator
call is made at all. The copy still described the moderator shape.

**Nothing went red, because five test files ASSERTED THE FALSE STATE.** That is
the anti-pattern AGENTS.md forbids in its own words - "Never write a check that
goes red when the bug is FIXED - that locks in the defect" - and it is the
structural finding here, larger than any individual sentence.

Verified by command at 82cb5a6, not by reading:

| Claim | Where | Why false |
|---|---|---|
| "A moderator model audits them over two rounds" | `workspace.html:760` | `debate.py:1430-1434` - no moderator call on a peer run |
| "Peer critique ... is planned, not yet built" | `workspace.html:840` | shipped, enabled, and billed per critic |
| "Per-model debate detail is not captured" | `workspace.html:488` | `slot_critiques` records it; the receipt itemises a `(critique)` row per critic. Visible on EVERY live run |
| "Each answer model critiqued the others, in both rounds" | `app.js` x2 | four reachable false states, below |
| "from the four refined answers" | `app.js` | unconditional; `synthesis.py:804-810` revises only from live critics |
| `Focus: disagreement, weak_support, missing_reasoning` | `app.js` x3 | module constant on both rounds; false for round 2 since ADR-0096 |
| "Panel divided" | `app.js` | bare `else` of `isConsensus`, so it fires on *undetermined* |

### The four false states behind one sentence

1. round 2 can be skipped entirely (`_should_skip_round_two`);
2. `critique_shape` is stamped PER ROUND, and the caption used `.some()`;
3. only ELIGIBLE slots critique, so the count is 0-4;
4. **a critic that returns nothing usable still yields a `SlotCritique`** with
   Quorum's template and `critique_mode` left at `"fallback"`, while the round
   stays shaped `"peer"`. A run where every critic fell back therefore rendered
   "Each answer model critiqued the others" directly above rows the same view
   marks "Written by Quorum, not by a model".

State 4 was missed by the handoff that commissioned this work, which listed
three. It is the one that makes a dispatch count the wrong thing to read.

## Decision

### 1. The landing describes the pipeline that runs

Subhead: "Four frontier AI models answer. They critique each other's answers and
sources, and each can revise its own. A synthesis model writes the one answer -
where they agree, where they don't, and exactly what to trust."

It remains pinned BYTE-EXACT, for ADR-0032's original reason: a rewrite must be
RED BY DEFAULT so an editor has to come back and re-approve the claim.

### 2. The stale roadmap chip becomes a real current limit

"Peer critique ... planned, not yet built" -> "Sources are cited, but aren't
checked against their pages". ADR-0096 decision 1 buys L1 only and says in those
words that no UI copy may imply otherwise; the chip slot is where that belongs.

### 3. Copy that counts must read the count

Both debate captions call `describePeerCritique`, which reads
`slot_critiques[].critique_mode` - critics that ANSWERED, not critics that were
dispatched - and `eligible_critic_count` as the denominator.

**The unknown branch is mandatory.** `eligible_critic_count` defaults to 0 and a
pre-#290 payload carries no `slot_critiques`, so a numeric branch would render
"0 of 4 answer models critiqued" beside however many `(critique)` charges the
receipt lists - a worse falsehood than the one removed.

Same rule for the synthesis attribution: `describeSynthesisInput` restates
`synthesis.py`'s own condition (live critique AND visible `revised_answer`).

### 4. The transcript chip reports the panel reading, not its negation

Three states from `panel_agreement`: agreed / split / **undetermined**.
`data-consensus` stays strictly under `isConsensusResult`, so the green surface
keeps all five AC-019 conjuncts and the new third state can never paint green.

### 5. The constant focus line goes from all three remaining surfaces

Live card, transcript, and the Markdown export. ADR-0096 made round 2 the
convergence step while `FOCUS_AREAS` still stamps "disagreement" on it, so the
line became FALSE rather than merely redundant - which is what retires the
previous "placement decision, not a deletion" reasoning.

### 6. Every gate that pinned a falsehood is INVERTED in this commit

with a positive partner for the other shape, the pattern
`peer-critique-copy.spec.ts` already used.

## Rejected alternatives

**Change `FOCUS_AREAS` itself.** It is stamped on telemetry events and
`SlotCritique.focus_areas`, so editing it moves the API and the telemetry
schema. That is a behaviour change wearing a copy change's clothes; the display
decision belongs in the display.

**Drop the quantifier ("The answer models critiqued each other's answers").**
Smallest diff and true in every state, but it also fails the `/critiqued the
others/i` pin, and it leaves the reader unable to reconcile the caption against
a variable number of `(critique)` charges on the same page. The number is
precisely what they need.

**Reuse `mayClaimDisagreement` for the chip.** It folds in `noLiveAnswers` and
`aligned >= total`, which are about the tally clause, and `renderTranscript`
builds no `ctx` - so reuse means assembling one in a second place or silently
reading `undefined`, the #128/#247 defect.

**Delete the dead hidden panel** (`.panel.panel-section{display:none}`) and its
four false moderator claims. Correct in principle and DELIBERATELY NOT DONE
here: `app.js` resolves those three ids with no null guard, so removing the
markup throws on every completed run, and it would void an XSS assertion that
scans `#model-grid`. Different concern, recorded as debt.

## Consequences

- The moderator shape REMAINS REACHABLE (flag off, no eligible critic, or a
  cancel before the first dispatch), and its copy is untouched. Both branches
  ship; the caption picks per run.
- `describePeerCritique` and `describeSynthesisInput` are the second and third
  UI surfaces to read fields the API already served and nobody consumed. If a
  fourth appears, the pattern is the fix, not another hard-coded sentence.
- FR-008's implementation status moves to BUILT AND ENABLED. `docs/32-ui-state-
  matrix.md` loses its description of the caption as "honest".
- `openapi.yaml`'s own prose still describes the moderator shape. It is 404 in
  production (`api_docs_enabled` is LOCAL-only, verified by curl), so it is a
  correctness fix, not a user-facing one.
