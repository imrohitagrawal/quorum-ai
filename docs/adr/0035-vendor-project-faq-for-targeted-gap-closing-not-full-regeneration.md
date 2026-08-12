# ADR-0035: Vendor `project-faq` for targeted gap-closing, not full-page regeneration

## Status

Accepted

## Context

`docs/faq/index.html` is a hand-authored, real (not stub) FAQ page. It has a confirmed,
narrow staleness gap: its "Where can I read the architectural decisions?" answer named
only ADR-0001 and ADR-0002 by name, while the repository has grown to 34 ADRs. Separately,
a suite of first-party documentation-authoring skills
(`https://github.com/imrohitagrawal/project-doc-skills`, same author, MIT+Attribution,
already the source of 4 skills vendored in this repo — see `configs/external-skill-registry.json`)
includes `project-faq`, built for exactly this kind of page.

Rather than assume the skill's output would be better, a trial was run: `project-faq` was
vendored, and a full rewrite was generated to a second, uncommitted file (a sibling of
`index.html` inside `docs/faq/`, deleted once the trial concluded) sourced from the same
ground truth as the original (README, architecture/domain docs, all 34 ADRs, direct code
citations). Both pages were then run through the skill's own `verify.py` for an objective
comparison.

## Measurements

| | Original | Full rewrite (trial) |
|---|---|---|
| Tabs | 6 | 5 (no "Working with the tools" tab — not authored in the trial) |
| Questions | 29 | 22 |
| Glossary terms | 24 | 11 |
| Reading grade (target ≤8) | ~9.0 (warn) | ~11.8 (FAIL) |
| ADR-list answer | 2 of 34 ADRs named | All 34, grouped by theme |

The full rewrite was **not** a strict improvement: it dropped a tab and used denser prose
than the original despite the skill's own grade-8 target. It did close the confirmed ADR
gap convincingly. Separately, the verifier's `has_copyright = "©" in raw` check
(`.agents/skills/project-faq/scripts/verify.py:469`) is a **false positive on the original page** — it checks for
the literal Unicode `©` character and misses the `&copy;` HTML entity the original page
already uses (confirmed by reading `docs/faq/index.html:1240` directly). The original
was never actually missing a copyright notice; the verifier's check was wrong. That bug is
upstream (`project-doc-skills`), not fixed here.

One unrelated defect was found by manual inspection while doing this work: the original
footer read "All rights reserved," which contradicts this repository's actual MIT +
Attribution `LICENSE`. Fixed as part of this same change (not a `project-faq` finding).

## Decision

**Hand-merge, not full-regenerate.** Keep the original `docs/faq/index.html` as the base
(it has broader real coverage). Graft in only what the trial demonstrably improved: the
34-ADR grouped answer (replacing the 2-ADR list) and an explicit disclosure that ADR-0001
is still `Status: Draft` despite being effectively superseded piece-by-piece by many later
ADRs. Also fix the unrelated "All rights reserved" defect found during this work. Update
only the Architecture tab's "Last reviewed" stamp (2026-08-12) — the other 5 tabs were not
touched and keep their real 2026-07-23 date, so the freshness stamps stay honest per tab.

Vendor `project-faq` into `.agents/skills/project-faq` (registry entry: `trust_tier
first-party-operator-authored`, `status: registered`) for future **targeted** use —
closing a specific confirmed gap, verified by comparison — not as a wholesale
page-replacement tool until a future pass demonstrably matches the original's coverage and
reading-grade target.

## Consequences

- The FAQ's most-cited stale fact (2-of-34 ADRs) is fixed, with the ADR-0001 staleness now
  disclosed rather than hidden.
- `project-faq` is available in-tree for the next real gap, without having established it
  can safely replace the whole page yet.
- The stray trial-rewrite file was deleted rather than left in the tree — nothing else
  references it.
- The verifier's `&copy;`-entity blind spot is now on record here; fixing it is a
  `project-doc-skills` change, out of this repository's scope.

## Rejected alternatives

- **Ship the full rewrite as-is**: rejected — it measurably regressed coverage
  (missing tab, fewer questions/glossary terms) and reading grade versus the page it would
  replace.
- **Do nothing, leave the 2-of-34 ADR gap**: rejected — it's a confirmed, real staleness
  defect with a cheap, verified fix available.
- **Trust the verifier's copyright-footer FAIL and add a redundant footer**: rejected
  after reading the actual page — the original already had one; the check itself was
  wrong.
