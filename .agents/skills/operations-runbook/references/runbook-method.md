# Runbook method — deriving the runbook and the failure-mode entries

## Ownership principle
**You build it, you run it.** The people who build a component own operating it. The runbook is how
that ownership is shared and survives someone being on holiday — it turns private knowledge into a
procedure anyone on-call can follow.

## Deriving the failure-mode entries
Work through the component and list everything that can go wrong, then write one entry per item:

1. **Walk each dependency.** For every external service, data store, queue, and API the component
   calls: what happens when it is slow, when it errors, when it is down, when it rate-limits? Each is
   usually an **OPS** entry (retry, backoff, failover, resume).
2. **Walk each step.** For every processing step: what happens on a crash mid-step, a partial write, a
   duplicate trigger, a malformed input? Decide the safe recovery and whether the step is idempotent.
3. **Walk correctness.** Where could the system produce a wrong result or break an invariant (a bad
   output, a wrong calculation, a violated rule)? Each is a **CORR** entry — block, fix, regenerate,
   review, add a test. Never "just retry".
4. **For AI components, add the AI-specific modes:** the model is slow or down (OPS, with a fallback
   chain); cost spikes (OPS/budget); output quality drifts or a guardrail trips (CORR); a prompt or
   tool call fails (OPS or CORR depending on cause). See `observability-and-slo.md`.

For each, capture the eight fields in `assets/runbook-entry.template.md`. Keep it action-first.

## Routine operations to document
Besides failures, document the everyday procedures, each as numbered steps with the expected result:
- **Deploy** and **roll back** (the single most important pair — make rollback obvious and fast).
- **Back up** and **restore** (and when you last tested a restore — a backup you have never restored is
  a hope).
- **Scale** up/down; **rotate** keys/secrets (tell operators to do secret steps the secure way, never
  via a doc); **run** any scheduled job manually.

## Writing for pressure
- Put the **symptom first** in every entry — operators match on what they see, then act.
- One action per line; bold the verbs.
- State the **safe** recovery, and name the invariant a recovery must not break.
- Link dashboards and alerts inline so they are one click away.
- Keep the beginner floor: define operational terms (idempotency, backoff, circuit breaker, burn rate)
  on first use — on-call is not always the original author.
