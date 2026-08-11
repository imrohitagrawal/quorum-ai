# ADR-0032: The copy describes the moderator; the requirement keeps peer critique

## Status

Accepted — 2026-08-11

## Context

The product's public copy claimed a mechanism the system does not have.

`src/product_app/templates/workspace.html`, the landing served at `/ui` (the
first-visit front door — returning visitors on the same device boot into the
composer and never see it), told visitors that Quorum "has them critique each
other twice." The same claim appeared across `README.md`, `docs/faq/index.html`,
`src/product_app/static/app.js`, the OpenAPI `info.description` in
`src/product_app/main.py`, and FR-008 — **15 prose lines across six files** (README 2, FAQ 8,
`workspace.html` 2, `app.js` 2, `main.py` 1; count with
`git diff origin/main -- <file> | grep -c '^-[^-]'`), plus the FR-008 status
line, which is an addition rather than a correction. One
of them (`faq/index.html`, the "how it works" list) describing a fuller
mechanism still: *"the first round asks each model to critique the others; the
second round gives models a chance to revise their positions in light of the
critiques."*

Two of those sites were the worst of the set and were **missed by the first
draft of this change**, because its cluster grep covered only `README.md`,
`docs/` and `templates/`:

- `app.js` set a tooltip on **every model card, on every run** claiming *"each
  model is asked to revise its answer after reading the others — the refined
  version replaces this card."* Doubly false: no model reads the others, and no
  card is ever replaced.
- `main.py`'s OpenAPI `info.description` said *"has them debate"*. It reaches
  readers two ways: the committed `openapi.yaml` in this public repository, and
  the `/openapi.json` and `/docs` routes **wherever `Settings.api_docs_enabled`
  is true** — local, dev and CI.

  **Correction, 2026-08-11.** The first version of this line said "served at
  `/openapi.json` and `/docs` to every API consumer". That overstates the
  reach. Both routes are gated by `api_docs_enabled` — `_openapi_url` in
  `main.py` returns `None` when it is off, which removes the route — and
  **production has them off**:

  ```
  $ curl -s -o /dev/null -w "%{http_code}" https://quorum-ai.fly.dev/openapi.json
  404
  ```

  The claim was written without running that command, inside a change whose
  entire subject is prose asserting more than the code does. It is corrected
  here rather than quietly rewritten, because it is the same defect class this
  ADR exists to close, committed by the same author in the same hour — and
  because rule 4 says a correction must itself be verified before it is
  written. The underlying fix was still right: the description was wrong in the
  repository and in every environment that does serve it.

That miss is the reason the grep published below includes `src/product_app/`
whole rather than just `templates/`, and the reason this ADR says the grep is a
**seed, not a closure**.

What the code does, verified by reading the dispatch sites rather than the
prose:

- The four slot models are called **once each per run**, in parallel, from the
  initial-answer fan-out in `query_runs.py`. No second debate round calls them.
  (Narrow rather than absolute, per rule 4: `providers.py` does have a one-shot
  retry with the bare model id when the `:online` suffix fails, so "called
  exactly once" would be false on that path. It is a retry of the same
  question, not a second opinion.)
- `debate.py` `_call_debate_model` is the **only** debate dispatch site. It
  sends `model_id=settings.debate_model_id` — one separate moderator model,
  `anthropic/claude-haiku-4.5` by default — a transcript of all four answers,
  and asks for a critique. Twice.
- The four answer models never see each other's answers. There is no code path
  on which they could.

So the debate is real, live and billed — but it is a moderator audit, not a
peer debate. The gap was recorded on 2026-08-08 in a session analysis document that was
never committed. **It is deliberately not cited by path here**: it exists only
in the author's working tree, so a path would not resolve for any other reader,
and `tests/unit/test_cited_paths_resolve.py` correctly rejects such a citation.
Its note was that someone should decide deliberately whether to correct the
spec or build to it, and record it. No decision was recorded, and the copy
stayed live. This ADR is that decision, three days late.

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

1. Public descriptions of the mechanism now say a separate moderator call reads
   all four answers and writes a critique across two rounds. The starting
   cluster came from this grep — published as a **seed, not a closure**, because
   the first draft's narrower version missed `app.js` and `main.py` entirely and
   also misses the FAQ's "reads the four initial answers" phrasing:

   ```bash
   grep -rn -iE "critique (each other|one another|the others)|argue it out|reads the (others|four)|revise (its|their)" \
     README.md docs/ src/product_app/
   ```

   Two hits are **deliberately not changed**: `docs/01-product-brief.md:28`
   ("I want them to critique each other's answers") states a user need that
   remains the goal, and `PRODUCT_IDEA.md` states the original desired outcome.
   Rewriting either would erase the requirement instead of recording it as
   unmet. See #290.

2. **FR-008's Behavior line is retained verbatim** and an `Implementation
   status: PARTIALLY MET` line added beneath it. The requirement is not lowered
   to match the build; the shortfall is made visible instead.

3. The landing subhead now carries the **whole** pipeline — four models answer,
   a moderator audits, a synthesis model writes the answer. Previously it named
   only the four models, which left the two distinctive stages invisible.

4. A landing disclaimer chip states that peer critique between the four models
   is **planned, not yet built**, and #290 tracks it. It sits in the existing
   truthful-chips row rather than a tooltip, because the landing's own blocking
   gate measures at 390x664 and tooltips have no hover on touch. The wording is
   deliberately weaker than the first draft's "in development": review pointed
   out that nothing — no issue, branch or roadmap row — backed the stronger
   claim at the time it was written, which would have been this ADR's own
   defect one step removed. Filing #290 and softening the verb fixed both ends.

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
| **Drop round 2, since one moderator refining itself is not a debate** | Rejected on churn. Peer debate's round 2 occupies the same slot in the pipeline and reuses the same plumbing — the round loop, `_should_skip_round_two`, the `DEBATE_HARD_TIMEOUT_MS` budget, `debate_by_round` attribution, and the `debate_round_2` stage name hard-coded in `costs.py` twice, `debate.py` twice, `query_runs.py` and `app.js` (`openapi.yaml` carries only the `debate_round_2_running` status enum, not the stage name). Deleting it now means restoring it later and changing public copy twice. The saving is ~$0.005/run (measured round-2 cost $0.0043, `docs/validation/live-run-2026-07-14.json`) against a current production spend of $0 (`fly.toml` ships live execution off). |
| **Put the roadmap in a tooltip on the subhead** | Tooltips have no hover on touch, and the landing's blocking gate measures at 390x664. The mechanism would be invisible to phone visitors, which is the opposite of the goal. |
| **Correct the dated design-handoff records too** | `docs/design-handoff/*`, `design_handoff_quorum_ui/*` and `docs/32-ui-state-matrix.md` record a design review that happened. Editing them rewrites history rather than correcting a live claim. They are exempt, deliberately, and this row is the record of that. |

## Consequences

- The landing page now names the moderator and synthesis stages explicitly; the previous wording named only the four models and the mutual critique that does not happen. The shipped subhead is 183 characters against the previous 190. Length was NOT
  the risk: the first draft had the same character count and still wrapped to 5
  lines instead of 4, pushing the CTA from 4px above the fold to 20px below it.
  Candidates were measured at 390x664 and the shipped wording restores
  `ctaBelowFold` to -4, exactly the baseline. Page height grew 1422 -> 1491px
  against a 1593.6 bound (fold x 2.4) because of the fourth disclaimer chip,
  which sits below the CTA. Measured with
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
- The FAQ's default-slot list and its debate/synthesis model names are correct
  again: slot 4 is NVIDIA (not DeepSeek) and the synthesis model is
  `openai/gpt-5-mini` (not `gpt-4o-mini`, which contradicted the app's own
  tooltip). Two further DeepSeek mentions remain and are CORRECT — they
  describe what the OpenRouter gateway routes to, not what this product uses.
- No model call, cost, classification or computed output changed. The served
  landing HTML did change — that is the point of the change — and the OpenAPI
  `info.description` with it, so `openapi.yaml` is regenerated.
