# Category 8 — What remains UNVERIFIED + the single next step

## Still UNVERIFIED (do not treat as fact)

| Claim | Why unverified | How to verify |
|-------|----------------|---------------|
| #21 deploy "should be closed" | No PR closes it; deploy success is only *inferred* from #26/#27 timing | Trigger/observe one real deploy on a main SHA; check `deploy.yml` run status |
| #26 API key was actually fixed | No PR references it; "valid funded key" in #31 is inference | Inspect Fly secret history / a real live run's provider path |
| #31/#32 search behaviour offline | `:online` + citations + fallback only differ against a real provider | A real-provider integration test (paid — do deliberately, once) |
| Provenance of the 25 `.agents/skills` without the factory marker | Not fetch-compared against upstreams | Diff each against its candidate source repo |
| Visual layout of #33 as a "bug" vs design call | The issue itself says "partly a design call" | Human review of the seeded transcript snapshot at 1440px |
| That the #30 fix fully greens the invariant | Fix not yet written, but greenability was hardened: adversarial review confirmed only genuine prose surfaces are flagged (source titles de-scoped to plain text); ordered-list rendering is NOT asserted (a partial fix could pass) | Implement the per-surface renderer fix, re-run the invariant — must go green; confirm lists via the visual snapshot |

## Corrections applied vs the brief (for the record)

- Brief said "close #21" → **corrected** to "OPEN — verify before closing".
- Brief's `/metrics-404` and deploy-gate-scope "unfiled" → **verified true** and
  added as UNFILED-A / UNFILED-B in the ledger.
- Transcript "0 skills downloaded" → **corrected**: 6 vendored + ~83 factory
  (see `05-skills-strategy.md`).

## The single next execution step

**Fix #30 (raw Markdown) by routing every provider-PROSE surface through the
appropriate renderer, then flip the invariant gate to blocking.** Rationale: it
is the highest-blast-radius bug, the cheapest to test offline, already has a
RED-proven gate waiting to turn green, and the fix is the archetype for "collapse
ad-hoc paths into one." Sequence:

1. Route the raw prose surfaces through the appropriate renderer (both reuse
   `formatAnswerText`'s HTML-escaping, so no XSS regression):
   - **block** `formatAnswerText` for prose blocks: `app.js` 2074 (trust caption),
     2424/2437/2442 (verdict/summary/caveat), 1579 (live critique), 3111-3116 /
     3141 (transcript answers/critiques), synthesis rows;
   - **inline** `mdInline` for the positions cell (2906).
   - Leave source titles (3369/3390) as plain text — NOT part of this fix.
2. Re-run `e2e/tests/invariants/rendering-invariants.spec.ts` → the two #30 tests
   must go GREEN (the fixture is designed to green on this fix; verified that only
   greenable prose surfaces are flagged).
3. **Remove `continue-on-error` from the invariants step in `.github/workflows/e2e.yml`**
   — the enforcement handoff.
4. Then #29 (monotonic clamp) and #33 (layout + baseline seed) under the same gate.
