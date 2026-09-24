# ADR-0125: The bound prices web-search context from its own figure, not the setting

## Status

Accepted — 2026-09-25. Code and tests. **Moves no value**: at the shipped
setting (`cost_web_search_context_tokens = 2000`) every estimate, bound and
band is byte-identical to `main` (measured below). The owner decided the
direction on 2026-09-24 (their words: *"#268: pick b"*; CHG-012 D5: keep the
constant at 2000 and restructure the worst-case bound so a truer constant
cannot move an affordable mix into `BLOCK`). The design here is the
session's. One consequence is left to the decision that later raises the
setting; it is written below as PROPOSED — AWAITING OWNER.

## Context

Issue #268: the web-search context OpenRouter's `:online` suffix injects is
priced at 2000 tokens per searching slot, and 48 telemetry readings put it
higher (median 2438, max 3160; ADR-0119, which lives only on the unmerged
branch of draft PR #491). Both the point estimate and the fail-safe bound
read that one setting, and the bands key off the bound, so a truer setting
raises every searching mix's bound and tips mixes near a band edge.

## Decision

1. A new constant in `costs.py`, `BOUND_WEB_SEARCH_CONTEXT_TOKENS = 2000`.
   `_cost_components` takes `search_context_override`; `_estimate_bound_usd`
   passes the constant, and the point estimate passes nothing and keeps
   reading the setting. Raising the setting later moves the displayed
   estimate and not the bound, so not the per-call band (allow, confirm or
   block), which is what D5 is about. The two per-account spend rails, the
   cumulative guard and the 24-hour cap, add the TYPICAL estimate to spend
   already recorded (the `max_cost_usd` docstring in `costs.py` says why), so
   after a raise they reach their limit sooner, as they should: they track
   what runs are expected to cost.
2. The constant is a LITERAL pin in the risk registry
   (`tests/unit/test_risk_constant_pins.py`). Moving it is a money-value
   change: the owner's decision, with its own CHG row.
3. The hand-built worst case in `tests/unit/test_estimate_token_model.py`
   reconstructs the bound from the constant, the figure the bound prices.

## Measurements

On the `wp/268-bound-decoupled` worktree at `81eee7a` plus this change. No
paid call. The static table is `_FALLBACK_CATALOG` (13 models, 715
four-model mixes, every slot searching). The live-price run fetched the free
public catalog (455 models priced on 2026-09-25) and used ADR-0119's judge,
`openai/gpt-4.1-mini`, with a dummy key; production's judge model is a
secret, so that choice is ADR-0119's, not a reading of production.

**What a raise does, old structure against this one** (static table, so no
judge: the static table cannot price the judge production runs; mixes that
change per-call band, and of those, newly `BLOCK`):

| peer critique | query | value | old: change / new `BLOCK` | this: change |
|---|---|---|---|---|
| off | 59 chars | 2500 | 48 / 29 | 0 |
| off | 59 chars | 2900, 3200 | 63 / 44 | 0 |
| off | 1,000 chars | 2500 to 3200 | 28 / 28 | 0 |
| off | 4,000 or 16,000 chars | 2500 to 3200 | 0 / 0 | 0 |
| on | 59 to 16,000 chars | 2500 to 3200 | 1 to 6 / 0 | 0 |

At 4,000 characters and more, the mixes a raise would tip are `BLOCK`
already; a sweep over long queries alone reads 0 with peer critique off. The
judge changes the count: on the old structure at the 59-character query,
peer critique off, review measured 63 / 44 with no judge, 38 / 38 with
`openai/gpt-4o-mini` as judge, 28 / 28 with `openai/gpt-5-mini` and 0 / 0
with `openai/gpt-4.1`. Production's posture is judge on and peer critique
off; the live-price table below is the closer reading of it.
This ADR's first draft made exactly that mistake and claimed the old
structure moved no band with peer critique off; ADR-0119's short query
showed otherwise.

**Live prices, 59-character query** (ADR-0119's sweep script, run against a
`git archive` copy of `main` and against this branch):

| peer critique | old: change / new `BLOCK` at 2500, 2900, 3200 | this |
|---|---|---|
| off (production) | 0 / 0 at each | 0 at each |
| on | 9 / 4, 11 / 5, 13 / 5 | 0 at each |

**Unchanged at 2000**: every 2-, 3- and 4-model mix, search on and off, peer
critique on and off, queries of 40, 4,000 and 20,000 characters, `main`
against this branch: 12,948 estimates, 0 differ in point, bound or band.

**Tests**:

| what | result |
|---|---|
| RED on `main` (`test_bound_search_context_is_decoupled.py` in a `git archive` copy) | 4 failed; at 2500, 76 mixes change band with peer critique off and 6 with it on; the constant does not exist |
| GREEN, full suite | recorded in the pull request |
| mutations (copy aside, mutate, clear `__pycache__`, run the three test files, baseline `59 passed`, restore, `cmp`) | 4 of 4 killed: the bound reads the setting again; the point ignores the setting; the constant 2000 to 2001; 2000 to 1999 |

## PROPOSED — AWAITING OWNER: the point may pass the bound after a raise

`costs.py` states that the point never exceeds the bound in four places
(the `max_cost_usd` docstring, the comment above the call to
`_estimate_bound_usd`, the clamp comment in `_estimate_breakdown`, and the
`_cost_components` docstring), and four test files assert it at the shipped
setting. It holds at 2000. With the setting raised and the bound fixed, it
breaks on long queries (static table, peer critique off; peer critique on
reads 0 at every length measured; 2500 reads 0 everywhere):

| query | 2900 | 3200 |
|---|---|---|
| 8,000 or 9,000 chars | 0 mixes | 0 mixes |
| 10,000 chars | 0 mixes | 55 mixes |
| 10,300 chars | 11 mixes | 55 mixes |
| 10,500 to 20,000 chars | 55 mixes | 55 mixes |

Every such mix is already `BLOCK` (the lowest bound among them is 0.5637
against the 0.50 hard limit), so no money moves on it; what breaks is the
displayed "typical" figure sitting above the "up to" figure on a refused
estimate. The session's proposal, not decided: settle it in the CHG row
that raises the setting, by clamping the displayed point to the bound or by
accepting it on refused mixes. Nothing here is changed until then.

## Rejected alternatives

- **Price the bound from the point plus a measured margin** (the second
  candidate in the package brief). The bound would follow the setting,
  which is the coupling D5 removes.
- **Folding ADR-0119's branch in.** It records measurements and questions,
  not a restructure. This change starts fresh from `main`; ADR-0119 and
  draft PR #491 are left as they are, and #491 stays open.

## Consequences

- Today nothing observable changes.
- A later raise of the setting moves the displayed estimate on every
  searching mix and no per-call band, in either posture, on either price
  table measured above. The per-account spend rails still see the higher
  typical estimate.
- #268 stays open: the value itself is the owner's later decision.
