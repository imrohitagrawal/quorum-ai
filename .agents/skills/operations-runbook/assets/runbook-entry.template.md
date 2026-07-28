# Runbook entry template (copy one per failure mode)

A runbook is read under pressure. Keep each entry short and action-first. Each entry maps one-to-one
to a row of the failure-mode analysis for the component.

**Filling this in.** The square-bracket slots below — `[component]`, `[one line]`, `[links]`, and the
rest — are **author-fill slots**: replace each by hand with the real value for this component. They
are deliberately *not* the suite's `{{key}}` placeholders (which a tool resolves from
`project-profile.md`); a runbook's component, owner, and links differ for every entry and are not
profile values, so you write them in directly. The one fixed-format slot is the **`Last reviewed:`
date** — keep it as an ISO `YYYY-MM-DD` literal, because the verifier's freshness check reads that
exact shape.

---

## Component (top of the file, once)

- **Name:** [component]
- **Owner:** [owner + contact]
- **What it does:** [one line]
- **Steps / responsibilities covered:** [e.g. ingest / process / store, or the service's endpoints]
- **Where it runs:** [local command + deployed location]
- **Dependencies:** [the services/data stores/external APIs it relies on]
- **Tracking / ADRs:** [ticket prefix] · [related ADR numbers]
- **Dashboards / alerts:** [links]
- **Last reviewed: YYYY-MM-DD** — the date this runbook was last walked through end to end (an untested runbook is a guess). Keep the `Last reviewed: YYYY-MM-DD` shape so the freshness check reads it.

---

## Entry (repeat per failure mode)

### [Failure mode name] — class: OPS | CORR

- **Symptom.** What an operator actually observes (the visible effect, not the root cause).
- **Signal / alert.** Which signal or alert fires, and at what threshold.
- **Blast radius.** What is affected. State clearly what **fails** versus what **degrades gracefully**,
  and what is never dropped.
- **First response.** The immediate containment step. (Examples: confirm the alert is real; check the
  health of the shared dependency; check whether a fallback fired.)
- **Resume / recovery.** The safe path back, chosen by class:
  - *Crash or partial run (OPS):* re-trigger using the idempotency key `[key, e.g. id + timestamp]`;
    the run resumes from saved state and does not duplicate work. Confirm exactly one terminal state.
  - *Availability failure (OPS):* confirm backoff / circuit-breaker behaviour; clear the condition; let
    the queued work drain.
  - *Correctness failure (CORR):* do **not** retry blindly — it will reproduce. Block the artifact at
    the gate, fix, regenerate, and review. A retry never fixes a CORR failure.
- **Escalation.** When to escalate and to whom; a human is the final gate for any risky or irreversible
  step.
- **Post-incident note.** A short blameless note: what happened, the timeline, the fix. Feed anything
  new back into the failure-mode analysis and the SLO tuning — this is the feedback loop that keeps the
  runbook current.

---

## Worked example entry (replace with your component's real modes)

### External model/service timeout or outage — class: OPS

- **Symptom.** Processing stalls; throughput drops to near zero across in-flight work.
- **Signal / alert.** Provider latency/error signal breaches; a "fallback fired" alert; the fast
  burn-rate tier may page.
- **Blast radius.** The steps that call the provider stall; storage and intake are unaffected; the
  trigger is never dropped (it resumes).
- **First response.** Confirm the provider's status; check which option in the fallback chain is
  active; confirm backoff is engaged.
- **Resume / recovery.** Let the fallback chain and backoff carry the load; queued work resumes via the
  idempotency key once a provider responds. Verify no duplicate work occurred.
- **Escalation.** If every option in the chain is failing, or a weaker fallback is suspected of
  lowering quality, escalate to the owner before releasing the output.
- **Post-incident note.** Record the duration, which providers failed, and whether quality held on the
  fallback path; tune the fallback order or the stuck-pipeline timeout if needed.
