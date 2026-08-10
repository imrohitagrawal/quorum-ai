# ADR-0032: The copy describes the moderator; the requirement keeps peer critique

## Status

Accepted — 2026-08-11

## Context

The product's public copy claimed a mechanism the system does not have.

`src/product_app/templates/workspace.html`, the landing page served at the
deployment's root, told every visitor that Quorum "has them critique each other
twice." `README.md`, `docs/faq/index.html` and FR-008 said the same thing in
five further places, one of them (`faq/index.html`, the "how it works" list)
describing a fuller mechanism still: *"the first round asks each model to
critique the others; the second round gives models a chance to revise their
positions in light of the critiques."*

What the code does, verified by reading the dispatch sites rather than the
prose:

- The four slot models are called **once each, in parallel**, from the
  initial-answer fan-out in `query_runs.py`. Nothing calls them again.
- `debate.py` `_call_debate_model` is the **only** debate dispatch site. It
  sends `model_id=settings.debate_model_id` — one separate moderator model,
  `anthropic/claude-haiku-4.5` by default — a transcript of all four answers,
  and asks for a critique. Twice.
- The four answer models never see each other's answers. There is no code path
  on which they could.

So the debate is real, live and billed — but it is a moderator audit, not a
peer debate. The gap was recorded in an analysis on 2026-08-08 with the note
that someone should "decide deliberately whether to correct the spec or build
to it, and record it." No decision was recorded, and the copy stayed live.

Two further facts shaped the decision:

- **Round 2 is the moderator re-reading its own round-1 critique.**
  `_debate_user_prompt` gives round 2 the same four answers, unchanged, plus its
  own prior output, with the directive "Do NOT repeat it" and a system prompt
  saying "refining the round 1 critique". There is no second party and no new
  evidence.
- **The FAQ also named a vendor the product stopped using.** Slot 4 is
  `nvidia/nemotron-3-nano-30b-a3b`; the FAQ still said DeepSeek.

## Decision

**Correct the copy to describe the moderator. Keep FR-008's requirement
unchanged and record it as partially met.**

Specifically:

1. Every public description of the mechanism now says a separate moderator
   model reads all four answers and writes a critique across two rounds. The
   cluster was derived by grep, not by hand, so the next reader can re-derive it:

   ```bash
   grep -rn -iE "critique (each other|one another|the others)|argue it out|reads the others" \
     README.md docs/ src/product_app/templates/
   ```

2. **FR-008's Behavior line is retained verbatim** and an `Implementation
   status: PARTIALLY MET` line added beneath it. The requirement is not lowered
   to match the build; the shortfall is made visible instead.

3. The landing subhead now carries the **whole** pipeline — four models answer,
   a moderator audits, a synthesis model writes the answer. Previously it named
   only the four models, which left the two distinctive stages invisible.

4. A landing disclaimer chip states that peer critique between the four models
   is in development. It sits in the existing truthful-chips row rather than a
   tooltip, because the landing's own blocking gate measures at 390x664 and
   tooltips have no hover on touch.

5. The eyebrow ("Four AI models · two debate rounds · one sourced answer") and
   the h1 ("Ask once. Let four minds argue it out.") are **unchanged** — a
   product decision by the owner. Both remain true of the pipeline's shape: two
   debate rounds do run, and four models do produce the answers under audit.

6. Round 2 is left exactly as it is. See "Consequences".

## Rejected alternatives

| Alternative | Why not |
|---|---|
| **Rewrite FR-008 to describe the moderator** | Lowers a requirement to match the build, and the follow-on work would have to revert it. The requirement is the target; the status line is the honest record of distance from it. |
| **Build peer critique now instead of correcting the copy** | The copy is false today and the fix is minutes; peer debate is a substantial change with an unsettled risk (eight critique calls against a per-call 8s non-streaming timeout). Correcting the claim is not held hostage to the feature. |
| **Drop round 2, since one moderator refining itself is not a debate** | Rejected on churn. Peer debate's round 2 occupies the same slot in the pipeline and reuses the same plumbing — the round loop, `_should_skip_round_two`, the `DEBATE_HARD_TIMEOUT_MS` budget, `debate_by_round` attribution, and the `debate_round_2` stage name hard-coded in `costs.py` twice, `query_runs.py`, `app.js` and `openapi.yaml`. Deleting it now means restoring it later and changing public copy twice. The saving is ~$0.005/run against a current production spend of $0. |
| **Put the roadmap in a tooltip on the subhead** | Tooltips have no hover on touch, and the landing's blocking gate measures at 390x664. The mechanism would be invisible to phone visitors, which is the opposite of the goal. |
| **Correct the dated design-handoff records too** | `docs/design-handoff/*`, `design_handoff_quorum_ui/*` and `docs/32-ui-state-matrix.md` record a design review that happened. Editing them rewrites history rather than correcting a live claim. They are exempt, deliberately, and this row is the record of that. |

## Consequences

- The landing page now describes three stages instead of one. The subhead is
  ~185 characters against the previous ~189, so the landing-density gate is not
  at risk; measured before and after with
  `e2e/tests/invariants/landing-cta-reachable.spec.ts`, which prints
  `landing @390x664` including `ctaBelowFold` — a figure with only 4px of slack.
- **A known limitation is now on the record with an expiry.** Round 2 is the
  moderator arguing with its own output. Round 1 is asked for the *strongest*
  disagreements and round 2 for *residual* ones it has not already said; with no
  new evidence, complying means weaker material, and `synthesis.py` concatenates
  both rounds into the synthesis prompt at equal weight. Whether that dilutes
  the synthesis is **reasoned from the prompts and the call path, not
  measured** — settling it would need a paid A/B run, and the peer-debate work
  removes the cause. Resolved when peer critique ships.
- The FAQ's vendor list is correct again (NVIDIA, not DeepSeek).
- No behaviour changed. No model call, cost, classification or served value is
  touched by this change.
