# Why closing one issue kept opening another, and what changes (2026-08-01)

## The complaint, verified against real data

Mid-session (during #128's close-out), the user flagged: "every time
there's an issue closed and the issue is opened, and the count remains 39."
Before changing anything, the claim was checked against real GitHub data
rather than assumed correct or dismissed.

```bash
gh issue list --state all --limit 250 --json number,title,createdAt,closedAt,state
```

85 issues fetched, 46 closed. Reconstructing the running open-issue count
from every `createdAt`/`closedAt` event, in order, over the prior three
weeks:

| Date | Open count | What happened |
|---|---|---|
| 2026-07-14 | 0 → 4 | first issues filed |
| 2026-07-17 | → 0 | a clean sweep — everything filed that week got closed |
| 2026-07-22 to 27 | 0 → 9 | steady filing, light closing |
| 2026-07-28 | 9 → 34 | a large single day: 22 opened, 8 closed (net +14) — the UI-triage and gate-liveness audits found far more than they fixed that day |
| 2026-07-29 to 30 | 34 → 47 | continued net growth — mutation-gate infrastructure work opened 10 new issues (#136-#168) while closing only 3 |
| 2026-07-31 | 47 → 44 | net -3 — #171/#151/#106/#177/#176 closed, #185/#188/#189/#193 opened, but closes edged out opens |
| 2026-08-01 (today, before this session) | 44 → 39 | net -5 — the #158/#156/#163 cluster, the #100+#178 session, and the #62 session together closed 8 issues while opening only 1 (#199) |

**The backlog size has never been flat.** It went from 0 to 48 and back to
39 over three weeks, driven mostly by *review/audit sessions that discover
far more than they fix* (2026-07-28 to 30), balanced by *sessions that
close without opening* (2026-07-31, and most of today before this session).

**The narrower claim — my own pattern — is accurate.** The two most recent
single-issue sessions before this one were:

- #112 session: closed #112, opened #203. Net 0.
- #128 session (this one, before the correction below): closed #128, opened
  #206. Net 0.

Both handoffs (`HANDOFF-POST-112-ULTRACODE-PROMPT.md`,
`HANDOFF-POST-128-ULTRACODE-PROMPT.md`) explicitly named this as "the
issue's own follow-up, filed as its own issue, deliberately NOT built here"
— treating it as the responsible thing to do, modeled directly on the
#180-vs-#185 and #112-vs-#203 clubbability calibration already in this
repo's standing practice. It was responsible reasoning applied to the wrong
question. The clubbability check answers "should this be the SAME PR as the
current work?" (no, per rule 17). It does not answer "should this be
attempted in the SAME SESSION, as its OWN PR?" — and nothing in the prior
practice ever asked that second question. Every review-discovered follow-up
defaulted to deferred, regardless of whether it was actually ready to build.

## Root cause

Adversarial review is working as designed — both #203 and #206 are real,
verified findings, not noise. The gap is what happens AFTER a review round
surfaces something: the practice treated "discovered during review" as
sufficient reason to file-and-stop, without asking whether the finding was
actually blocked on anything. Some findings genuinely are blocked (#203
needs new data collection — capturing real proxy/WAF response shapes — that
doesn't exist yet). Others are not blocked at all; they're just small
(#206: a type annotation, a regenerated OpenAPI file, one test, ~30 net
lines, no external dependency, no unresolved design question). Filing both
the same way collapsed a real distinction that should have controlled
whether the session kept going.

## The fix: a readiness test, applied per finding

A session that opens an issue on itself (discovered during its own review,
investigation, or build) must attempt to **dissolve it in the same
session** — build it, review it, merge it, deploy it, as its OWN PR
(one-concern-per-PR still binds; being in the same session never bundles
two concerns into one diff) — unless the finding fails at least one of
these tests:

1. **No concrete fix design exists yet.** It needs a measurement or
   research step before anyone could say what the correct fix even is
   (#203's proxy/WAF response-shape capture; #180's boilerplate-exclusion
   measurement).
2. **It needs a product or UX decision the session cannot make
   unilaterally.** Two named options, no way to pick one from the code
   alone (#115, #126 in the current backlog).
3. **It is large or high-risk relative to a single clean PR.** A rough
   line-count estimate in the hundreds, or touching multiple files/subsystems
   with open design questions of its own (#123's ~430-line estimate).
4. **It is a genuinely different subsystem or mechanism**, not a deeper
   layer of the same one — the #180-vs-#185 calibration (same function,
   different mechanisms, correctly NOT clubbed) extends here too: different
   mechanism, not just "found nearby," is grounds to defer.

If a finding passes all four — small, ready, no decision pending, same
area — building it now beats filing it. Filing it produces exactly the
net-zero pattern the user measured. Deferring only when a real blocker
exists (not merely "discovered mid-session") is what turns adversarial
review from a backlog-generator into a backlog-reducer.

## Demonstrated this session

#206 was tested against the four conditions: it had a concrete fix already
(Literal type + regenerated OpenAPI schema — no research needed), no
product decision pending, small (~30 net lines across 4 files, confirmed by
`git diff --stat` before starting), and the same subsystem/layer as the
work just finished (the exact field #128 had just touched). It failed none
of the four blocking conditions, so it was built as PR #207 in this same
session — its own worktree, its own review round, its own four-step
close-out — rather than filed as a third open issue.

Result: this session closed #128 AND #206, opened zero new issues. Open
count went from 39 to 38. The first single-session NET REDUCTION in this
handoff chain's recorded history (every prior single-issue session either
held flat via a 1-for-1 follow-up, or wasn't tracked closely enough to
compare).

**#203 was re-examined against the same four conditions and correctly
stays deferred** — it still needs the same measurement step it needed when
filed. The new rule does not mean "build every follow-up regardless of
readiness"; it means "stop defaulting to deferred without checking
readiness first."

## What does NOT change

- **AGENTS.md rule 17 (one concern per PR)** is untouched. Dissolving a
  follow-up in-session means a SECOND PR, not a bigger first PR.
- **AGENTS.md rule 19 ("close more than you open")** is reinforced, not
  relaxed — this practice is a mechanism for satisfying it more often, not
  an excuse to keep building indefinitely. A session should still stop and
  say so if a "small" follow-up turns out bigger once started (test 3
  above), rather than forcing it through.
- **The clubbability check (§3a in the standing handoff)** still answers a
  different question (same PR or not) and still applies whenever two
  issues — pre-existing OR discovered mid-session — turn out to be the same
  concern. This practice is layered on top of it, not a replacement.
- **Genuinely blocked follow-ups still get filed and deferred.** #203
  proves the rule has teeth in both directions.
