# Incident response — severity, timeline, and the blameless post-incident note

When something breaks badly, a shared procedure beats improvisation. Keep this light but real.

## Severity levels (agree these once, use them every time)
Severity sets the response — who is paged, how fast, and how much communication. A common scale:

- **SEV1 — critical.** The system is down or unusable for most users, or data is at risk. All hands,
  immediate response, frequent updates until resolved.
- **SEV2 — major.** A major feature is broken or badly degraded for many users; no full outage.
  Urgent response during working hours / on-call.
- **SEV3 — minor.** A limited or non-critical problem; a workaround exists. Handled in normal work.
- **SEV4 — low.** Cosmetic or very limited; logged and scheduled.

State, per level: who responds, how quickly, who is informed, and how often updates go out.

## The incident timeline (capture as you go)
During an incident, one person keeps a running timeline — it makes the post-incident note honest and
quick to write:

```
Detected:      [time] — how it was noticed (alert/report)
Acknowledged:  [time] — who picked it up
Severity:      SEV[n] — and why
Mitigated:     [time] — what stopped the bleeding (the user-facing fix)
Resolved:      [time] — full service restored
Root cause:    [what actually caused it]
Follow-ups:    [the fixes and tests to prevent recurrence, with owners]
```

## The blameless post-incident note (postmortem)
After a significant incident, write a short note — **blameless**: it examines the system and the
process, never blames a person. People act reasonably given what they knew at the time; the goal is a
system that fails less, not someone to fault. Keep it short:

- **What happened** — plainly, with the timeline.
- **Impact** — who and what was affected, and for how long.
- **Why** — the contributing causes (usually several, not one).
- **What we are changing** — concrete fixes and **new tests/alerts** so it cannot recur, each with an
  owner and a due date.
- **What went well** — what helped detection or recovery (worth keeping).

Feed every new failure mode and every tuning lesson back into the runbook, the failure-mode analysis,
and the SLOs. That feedback loop is what keeps operations from going stale.

## A note on AI components
For an incident caused by an AI output, attach the reproducibility data from
`observability-and-slo.md` (exact input, parameters, model and version, temperature/seed). Without it,
the incident cannot be reliably reproduced or fixed, and the new test cannot be trusted.
