# NFR-posture method — scalability, SLOs, security, and observability, told honestly

The non-functional posture is where a walkthrough most easily slips from teaching into wishful
thinking. It is tempting to write down round, confident targets for a system that is half-built. This
method keeps the section true: it tells the reader what the system *promises*, how each promise is
*measured* and *enforced*, and — plainly — which promises are real today and which are designed.

A **non-functional requirement (NFR)** is a quality the system must have rather than a feature it must
do: how available it is, how fast, how much load it takes, how much it costs to run, how isolated one
user's data is. A **service-level objective (SLO)** is a target for one such quality (for example,
"99% of jobs succeed over 28 days"); the thing it measures is the **service-level indicator (SLI)**.

## 1. Not every target is an error budget — pick the control mode

This is the idea the section turns on, and the one most often gotten wrong. Each quality is *enforced*
in the way that fits it. State the **control mode** next to every target, because the mode tells the
reader what happens when the target is missed:

- **Error budget** — for availability, latency, and throughput. The budget is `1 − SLO` over a rolling
  window (a 99% target leaves a 1% budget). It *may be spent*: brief, bounded failure is normal, and
  burn-rate alerting pages when it is being spent too fast. When the budget for a service is exhausted,
  reliability work for that service takes priority over new features until it is back inside budget.
  **Derive the burn-rate alert tiers from the budget definition, do not pick round numbers.** A
  multi-window scheme (a fast-burn page, a slow-burn ticket) has thresholds that are arithmetic from the
  budget — "spend 2% of the window's budget in 1 hour" is a burn rate of `(0.02 × window-hours) ÷ 1`, a
  figure you can show your working for — so the alert is verifiable rather than invented. Show the
  arithmetic next to the tier; a fabricated threshold is the same honesty failure as a fabricated SLO.
- **Spend ceiling** — for cost. A ceiling with alerts (say at 80% and 100%) and a fall-back ladder
  (cache, down-route, shed non-urgent work, alert). It is a **guardrail, not a spendable budget**: you
  do not get to "use up" overspend the way you tolerate a little downtime.
- **Regression gate / threshold** — for correctness and quality (a grounding pass rate, a mutation
  score, a stability floor). Dropping below the threshold **blocks the release path or quarantines the
  failing part**. It is emphatically **not** a spendable budget. Treating correctness as an error
  budget — "we are allowed N wrong outputs this month" — is a **category error**: a wrong result is not
  a tolerable amount of downtime, it is a defect to fix. Say this explicitly; it is a common and
  expensive confusion.
- **Adopted** — for a quality another document already owns (often detection: mean-time-to-detect,
  burn-rate tiers). Do not redefine it; name the owning record and adopt its numbers, so the value
  lives in one place.

A reader who learns *which mode* governs a quality understands the system's real posture far better
than one who only sees a number.

## 2. Name each SLI's measurement signal

For every indicator, state **the signal that computes it and the window** — which metric, span, or
log, over how long. "Job success measured as completed ÷ accepted jobs over 28 days" is checkable and
will match the dashboard; "high availability" is a wish. Naming the signal is also what keeps the
written definition and the monitoring in step: they are the same sentence.

## 3. Provisional now, ratified later — and labelled the whole time

Setting a target before you can measure the system is a *design decision*, not a measured fact — and
that is fine, because a target gives the monitoring something to check against from day one. The rule
is honesty about which is which:

- **Commit the target now, and label it provisional.** Every unvalidated figure reads "provisional"
  (or "proposed, not yet locked") until a baseline confirms it.
- **Validate against a baseline in the phase that owns the telemetry.** When real measurement exists,
  compare the baseline to the provisional target and **ratify** (keep), **adjust** (re-set, with the
  reason recorded), or **tighten** it.
- Until then, do not present a provisional number as a measured one. The label is the difference
  between teaching and bluffing.

## 4. Built vs designed — do not put a live SLO on a part that does not exist

A measurable SLO belongs only on a component that exists to measure. For a part that is designed but
not built, **register the target, mark it `[designed, not yet built]`, and link the live status** —
do not imply the guarantee is being met by a thing that is not running yet. An unmeasurable target on
an unbuilt component is a zombie: it can never pass or fail, so it teaches nothing and rots quietly.

## 5. Single source — each value has exactly one owner

The posture section *references* its numbers; it does not own them. State an **ownership matrix**:
each value (an availability target, a mutation threshold, a capacity envelope, a security target)
names the one record or config file that owns it, and everywhere else links to that owner. This is the
same single-source rule the decision treatments follow — never copy a tunable value into the
walkthrough; name its key and point to its home — applied to the non-functional numbers. A value
written in two places will disagree in two places.

## 6. Scalability — name the seam now, build it at its trigger

Scalability is part of the posture, and it has its own discipline so the section does not turn into
speculative capacity planning:

- **Decide the posture now; defer the costly build (temporal decomposition).** Name each way the
  system will need to scale as a *seam* — a place designed to be extended — and record the cheap,
  hard-to-reverse foundations that are worth laying early. The expensive build for a seam waits until
  its trigger is approached, so the walkthrough is not full of machinery that does not exist.
- **Every scaling trigger needs four things:** a metric, the source that reads it, a threshold stated
  against an SLO, and the owner who responds. A trigger with no monitor and no owner is not a plan.
  Write the trigger down as a concrete condition that *forces* the build — so "scale it later" cannot
  quietly become "never," which is how a deferred seam accretes special cases until it is the mess the
  seam existed to avoid.
- **Validate each documented limit with a scheduled test.** A capacity number written once and never
  re-checked rots. Where the project can, drive the system to each stated limit on a schedule (a
  nightly load or soak test) and re-derive the figure, so the numbers cannot quietly go stale —
  exactly the docs-in-lockstep idea, applied to capacity.
- **Mark the binding constraint.** Many systems are not bound first by their own compute but by an
  external dependency (a provider's rate limit, a cost ceiling, a downstream quota). Say what binds
  first, because that is what the scaling design actually has to manage.

## 7. Security NFRs — and the one that is a hard gate

Security qualities (authentication latency, authorization-check latency, the overhead of an isolation
mechanism, cross-boundary isolation) sit in the posture too, usually owned by the security/authz
decision record and referenced here. Most are error-budget-style latency targets. **Isolation is the
exception: it is a hard regression gate, not a spendable budget.** "Reads that crossed a tenant or
user boundary" has a target of exactly zero, and any non-zero result blocks the release path — the
same control mode as a correctness gate, for the same reason. Do not average it, and do not budget it.

## What to write in the section

A short table or list of the qualities the system promises, and for each: the indicator and the signal
that measures it; the target with its control mode; whether it is provisional or ratified; whether the
component is built or designed; and the owner the value links to. Then a paragraph or two on the one or
two that matter most — usually the binding constraint and the isolation gate. Honest, linked, and
labelled beats round and confident.
