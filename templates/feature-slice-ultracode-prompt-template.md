# Feature-Slice Ultracode Prompt — Template

> Extracted from `R2-S2-S4-ULTRACODE-PROMPT.md`, a real execution of this
> pattern in this repo (Quorum-AI Release 2: Trust & Evaluation, slices
> S2→S3→S4, shipped 2026-07-21/22). That file is the fully-worked,
> project-specific example; this template is the reusable shape, with
> quorum-ai's branch names, commit SHAs, file paths, and feature IDs stripped
> out and replaced with `<placeholders>`. Fill in every placeholder before
> using this — an unfilled template pasted as-is will fail immediately (the
> agent has nothing concrete to act on), which is the correct failure mode.

**How to run:** paste the filled-in version of this whole file as the task,
plus your orchestrator's multi-agent trigger keyword if it has one.

---

## Precondition — prerequisite gates must exist and be RED-proven

**Do not start this feature until its prerequisite gates exist and have been
proven failing on a real defect, then passing.** This is a literal
precondition, not a note: it is satisfied by *running* the gates in this
checkout, never by reading a plan document and believing it. A plan is
influence; only a gate that fails the build is enforcement.

Run `<list the prerequisite gate commands here>` first. If any command is
missing or fails, stop and finish the prerequisite work before touching this
feature.

Then confirm each gate is **RED-proven** — someone has shown it failing on a
real defect (pre-fix file content or an injected mutant) and passing after.
A gate that was never proven RED is assumed broken and does not count. Record
in the final report which gates you ran, their output, and any you could not
run (with the reason) — never assert "prerequisites complete" from a document.

---

## Mission

`<one paragraph: what this feature does, why it matters, and the measurable
exit criteria that define "done" for the whole feature, not just one slice>`

Ship each slice as a reviewed, green, documented increment. At the end,
produce a single report for human review (see **Final report** below).

---

## Prime directives (NON-NEGOTIABLE — apply to every slice, every file)

These generalise; keep them verbatim, only adjust wording for your domain.

1. **Evidence-first, execute don't preach.** Find the data, decide from the
   data. No guardrail value, weight, or threshold is set from a guessed
   number — calibrate against measured data and record the calibration.
2. **TDD always — RED then GREEN.** Every behavioural change ships with a
   test that **fails without it**, proven failing first (capture the RED
   output), then made green. Applies to helper scripts too, not just
   production code.
3. **Verify by performing.** Drive the real flow, run the real path — never
   assert correctness from a single clean unit test or one sample.
4. **Adversarial subagent review per non-trivial change.** At minimum a
   correctness pass; for any security/trust/safety-relevant surface, a
   reviewer whose explicit job is to break it / find an evasion / find bias.
   Do this proactively; fix findings test-first before declaring a slice done.
5. **Honesty over fabrication.** Never show a made-up number. Absent/unknown
   ⇒ an explicit "unavailable" marker, never a placeholder value. Figures
   copied verbatim from the canonical source, never recomputed or "upgraded."
6. **Data minimisation.** `<state your project's data-sensitivity boundary —
   what must never be persisted/emitted beyond what's strictly needed>`.
7. **Hermetic, $0 CI.** Every-PR CI makes zero paid external calls — prove it
   with a spy test. Paid/gated work is key-gated and lives only in an opt-in
   job.
8. **Existing security/access boundaries are preserved**, not just inherited.
   `<name your project's specific boundary, e.g. auth, tenancy>` — every new
   endpoint or surface stays behind it, proven with an explicit test, not
   assumed.
9. **Follow existing conventions.** `<point at your project's doc formats,
   naming schemes, ID schemes>`.
10. **Green gates are necessary, not sufficient.** All required gates passing
    AND a clean adversarial review, before a slice is "done."
11. **Every threshold ships advisory/OFF until calibrated against real data.**
    Shipping a guessed threshold as enforcing is the guardrail-from-a-guess
    failure; do not. Flip to enforcing only once measured, with the measured
    numbers written down.
12. **The review loop is bounded: max `<N>` rounds, then human override.** Fix
    findings test-first each round. If the final round still yields a
    significant finding, stop and escalate to the operator with the residual
    list — the operator may accept, defer, or authorise more rounds, and the
    override is recorded. The loop always terminates.
13. **Docs before code for any user/safety-facing surface.** `<name the docs
    that must be updated before, not after, the code lands>`.

---

## Locked decisions (from planning — honour all)

`<Fill in the decisions already made during planning that implementers must
not re-open: scope boundaries, technology choices, integration patterns,
what's explicitly deferred out of this run>`

## Deferred — DO NOT build in this run

`<List anything a slice might be tempted to build that's explicitly out of
scope, and where to record the deferral instead (a debt register, a
follow-up issue)>`

---

## Ground-truth codebase map

`<List the real files/symbols each slice will touch, with a brief note on
what each owns, so an agent designs against reality instead of guessing.
Read to confirm before planning — this map decays the moment code moves.>`

---

## Slice `<N>` — `<name>` (`<requirement ID(s)>`)

For each slice:
- What gets built, in terms of real symbols/files.
- **RED-first tests**: name the specific test cases that must exist and fail
  before the implementation, and what they prove (not just "add tests").
- **Docs**: which docs get updated, in what order relative to the code.
- **Rollback**: what happens if this slice's feature flag/gate is off —
  confirm it's a no-op, not a partial state.

(Repeat this section per slice. Order slices so later ones can depend on
earlier ones; note the dependency explicitly.)

---

## Cross-cutting gates & Definition of Done

A slice is done only when ALL hold; the feature is done when all slices are
done. "All gates green" is not a checkable statement — name the exact
commands, and each must be run with its output captured in the slice report:

- **Prerequisite still holds** — re-run it; do not carry a stale claim.
- **TDD proven**: each behavioural change has a captured RED then GREEN;
  timing-sensitive tests run enough times to establish a real flake rate.
- **Full suite green**, linter/type-checker clean, and every named gate
  command exits 0.
- **Hermetic proof**: a spy test shows zero paid/external calls on the
  every-PR path.
- **Neutrality proof** (if applicable): a gated feature OFF produces an
  identical result to before it existed, with zero calls to its own seam.
- **Adversarial review clean**: findings fixed test-first, not waved away.
- **Docs complete** in the established formats.
- **Security/access boundary intact — proven, not asserted**: the explicit
  test from directive 8 is green.
- **No deferred scope crept in.**

## Suggested orchestration

Run slices in dependency order. Within each slice, pipeline:
`implement (RED→GREEN)` → `adversarial verify (2-3 independent skeptics:
correctness; evasion/bias; honesty)` → `fix findings test-first` → `docs`.
Gate progression to the next slice on a green Definition-of-Done for the
current one. Interleave doc-writing per slice — don't batch to the end.

## Final report for human review

1. Per-slice: files changed, new requirement IDs, the RED→GREEN evidence
   (paste the key failing-then-passing outputs), and adversarial-review
   findings + how each was fixed.
2. Full-suite / linter / type-checker / gate results.
3. Confirmation of the hermetic ($0) proof and any neutrality proof.
4. Anything deferred, with a pointer to where it's tracked.
5. The exact commands to run any opt-in/gated path locally, so the operator
   can reproduce it.

**Do not** activate any paid path, rotate any secret, or deploy without
explicit operator approval. Hand back a branch ready for human review.
