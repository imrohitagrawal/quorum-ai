---
name: operations-runbook
description: Create operations runbooks and a troubleshooting guide for a software project — how to run it, how to monitor it, and exactly what to do when something breaks. Produces one action-first runbook per component (Markdown, repo-first) with a failure-mode entry per thing that can go wrong, plus monitoring signals, routine operations, and escalation. Use this whenever the user wants a runbook, ops guide, on-call doc, troubleshooting guide, incident playbook, SRE doc, "what to do when X fails", or wants to document how to operate, monitor, and recover their service. Use it even if the user only says "write the runbook for this", "document operations and on-call", or "how do we recover when it goes down". Built for projects that include AI components (model cost, drift, guardrails) as well as ordinary services. Operator-facing — not an end-user how-to (usage-guide), design rationale (architecture-and-decisions), or look-up Q&A (project-faq).
---

# Operations Runbook Builder

Build the **operator-facing** documentation: how to run the system, what to watch, and the exact
steps to recover when it breaks. A runbook is read under pressure, so it is action-first and concrete.
Read `references/house-style.md` first. The default scope is `internal` (operators and on-call), so
naming the real tools and commands is expected.

**Diátaxis mode:** a blend of *how-to* (recovery procedures) and *reference* (signals, thresholds,
contacts). Keep procedures imperative and scannable.

---

## Before you start (inputs, timing, and where this sits)

**What this needs as input.** One or more components that are far enough along to operate — they
build, deploy, and emit some signal (logs, metrics, or traces). For each component: its failure
modes (the failure-mode analysis or FMEA the design work produced), its dependencies, the dashboards
and alerts, and where the live service-level objectives and error budget are tracked — you **link**
those, you do not restate the numbers. Plus the project profile (`assets/project-profile.md`).

**When to run it — per component, as each one becomes operable. Not on an empty repo, not every
commit.** A runbook describes how a thing behaves when it runs, so it can only be truthful once the
thing runs. Write or refresh a component's runbook when that component reaches its Definition of Done
(it deploys and you can watch it), then **walk the recovery steps through once** — an untested
runbook is a guess. Refresh it at each milestone and after every incident, folding the lesson back
in. This is per-component and starts with the first shippable slice; it is not a single pass saved
for the end.
- You **may** draft a recovery procedure from the design before the component is built — but mark the
  unvalidated parts `[designed, not yet built]` and confirm them when it runs. Drafting from the
  design is fine; asserting that a recovery path works before it has been walked through is not.

**Where this sits among the suite (producer/consumer).** This is a *consumer* skill: it reads what
the architecture work produced (the failure modes and the dependency map) and links the
service-level-objective register rather than re-deriving it. Run it after the design docs exist and
the component is operable.
- **Use this, not a sibling:** for how an end user *works* the product, use **usage-guide**; for
  *why* it is built this way, use **architecture-and-decisions**; for quick look-up answers, use
  **project-faq**; for ramping a new *contributor* into the codebase, use **onboarding-companion**.
  This skill is the one for *operating, monitoring, and recovering* a running system.

---

## Workflow

1. **Ground and configure.** Read `house-style.md`; find or create the project profile. Note
   `grade_target_operations_runbook` and `scope_operations_runbook`. List the components/repos that
   need a runbook (one per separately-deployed thing).
2. **For each component, write a runbook** to the structure below, using
   `references/runbook-method.md`. Each failure-mode entry follows
   `assets/runbook-entry.template.md` exactly — copy it per failure mode.
3. **Define the monitoring** using `references/observability-and-slo.md` — what to watch, the
   thresholds, the service-level objectives, and (for AI components) the GenAI-specific signals.
4. **Define incident response** using `references/incident-response.md` — severity levels, the
   timeline template, and the blameless post-incident note.
5. **Stamp freshness and verify.** Put a **last-reviewed date** on each runbook in ISO `YYYY-MM-DD`
   form — for a runbook this is the date you last *walked it through* end to end (an untested runbook
   is a guess). The verifier's staleness check reads this stamp, so keep the exact `Last reviewed:
   YYYY-MM-DD` shape. Then:
   ```bash
   python3 scripts/verify.py docs/runbook.md --format md --skill operations-runbook --profile docs/project-profile.md
   ```
6. **Publish (repo-first — a separate, later step).** Write the verified Markdown to the repository
   first. That is always the default and the source of truth; a published target is only a mirror,
   and you never author in the target. Publishing is a separate step that runs after this loop,
   performed by the **publish-mirror** skill: it renders each page to every destination configured
   in `docs/publish-targets.yaml` (a wiki, a portal), following `references/render-contract.md`.
   The conversion — collapsible blocks, callouts, the table-of-contents line, diagrams exported to
   images, status badges, the licence footer — is defined once in the render contract; this skill
   does not restate it. Publish per page or per batch as each clears the loop.

---

## Runbook structure (one file per component: `docs/runbook.md`)

1. **Component.** Name; owner; what it does in one line; the steps/responsibilities it covers; where it
   runs; its dependencies; tracking/ADR links; dashboard and alert links.
2. **How to run it.** Local (the one-command start, prerequisites, environment) and deployed (where it
   lives, how to deploy and roll back). Tell operators to handle secrets the normal way — never paste a
   secret into a doc or an insecure place.
3. **Health and monitoring.** What "healthy" looks like; the key signals and thresholds; the
   dashboards and alerts. (See `references/observability-and-slo.md`.)
4. **Failure-mode entries.** One entry per failure mode, each: name + class **OPS** (operational) or
   **CORR** (correctness); symptom (what an operator sees); signal/alert and threshold; blast radius
   (what fails vs degrades); first response (containment); resume/recovery (the safe path back);
   escalation (when and to whom); post-incident note. Use the template asset.
5. **Routine operations.** Deploy, roll back, back up and restore, scale, rotate keys, run a scheduled
   job — each as numbered steps with the expected result.
6. **Service-level objectives and error budget.** The SLOs and where the live budget is tracked (link
   it; do not restate a number that lives elsewhere).
7. **Escalation and contacts.** Who owns what, the on-call path, and the rule that a human is the final
   gate for any risky or irreversible step.

## Two failure classes (handle them differently)
- **OPS (operational).** The system is fine, a dependency or resource failed (timeout, rate limit,
  outage, crash mid-run). Recover with retry/backoff, failover, or resume-from-checkpoint. A retry is
  safe **only** if the step is idempotent (doing it twice equals doing it once).
- **CORR (correctness).** The system produced the wrong result or broke an invariant. **Never retry
  blindly** — it will reproduce. Block at the gate, fix, regenerate, review, and add a test so it
  cannot recur.

## Quality bar (self-check before presenting)
- An operator who has never seen the system could run it and recover a failure from the runbook alone.
- Every entry says what an operator *sees* first, then the exact steps — action-first, not theory.
- OPS vs CORR is correct on every entry; CORR entries never say "just retry".
- Recovery is safe: idempotency/resume are stated where a retry is involved.
- Monitoring lists concrete signals and thresholds; AI components include cost and quality signals.
- Each runbook carries a **last-reviewed** date in `YYYY-MM-DD` (the day it was last walked through); the verifier reads that stamp and passes.


**Licensing and credits (required).** Every page carries the licence footer; the document set ships a `LICENSE` and an **About & credits** page, and the warranty disclaimer appears in the LICENSE — all per `references/licensing-and-credits.md`, using the public or internal variant per the profile's scope. The verifier fails a public page that lacks the footer.

## References and assets
- `references/licensing-and-credits.md` — the licensing + credits standard; applies to every document this skill produces.
- `references/house-style.md` — the shared writing standard (read first).
- `references/runbook-method.md` — how to derive the runbook and the failure-mode entries.
- `references/observability-and-slo.md` — what to monitor, thresholds, SLOs, GenAI signals.
- `references/incident-response.md` — severity levels, timeline, blameless post-incident note.
- `references/render-contract.md` — how a repo page is rendered to each publish target; the publish step (Workflow step 6) points here. The conversion lives here, never in this skill.
- `assets/runbook-entry.template.md` — the per-failure-mode entry template (copy per mode).
- `assets/project-profile.md` — copy into the repo and fill once per project.
- `assets/publish-targets.yaml` — the publish-destinations manifest; copy into the repo, fill the coordinates, and publish-mirror reads it.
- `scripts/verify.py` — run before presenting.

---

_Skill version: 1.1.0 — see `CHANGELOG.md`._
