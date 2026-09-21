# Decision register — W4, W5, W7 (2026-09-22)

**RECONSTRUCTED FROM SESSION TRANSCRIPTS — AWAITING OWNER CONFIRMATION.**

This file records what the product owner said about three board rows, in the
owner's own words, with where each sentence came from. It exists because none
of it was in the repository, so every new session labelled these rows
"undecided" and asked again.

It is **not** a decision record. No CHG row and no ADR has been filed for any
row below, and none should be until the owner confirms this text. Nothing here
is "Accepted".

## How each quote was checked

Every quote below was found by `grep -F` in a session transcript under
`~/.claude/projects/-Users-rohitagrawal-Projects-quorum-ai/`, in a record whose
`type` is `user`. Timestamps are the transcript's own, in UTC. The transcripts
are outside this repository, so a reader without that machine cannot re-run
the check; that is the reason for the AWAITING CONFIRMATION label.

The two 2026-08-31 quotes come from one long prompt the owner sent as a single
message. The owner sent it; whether the owner typed each sentence or approved
a draft is UNVERIFIED.

## W4 — variable panel size, N in {2, 3, 4}

| What | Source |
|---|---|
| The plan containing W4 was approved. | Plan-approval event, transcript `fcaa7c25`, `2026-08-25T20:43:24Z`. Plan of record: `~/.claude/plans/i-think-you-did-quiet-stearns.md`, "Settled decisions" §5 and work item 3. |
| *"The two, three, or four-model flexibility was provided to the user. We cannot force the user to always select four panels, and it depends on the user and how you want to use it. It was given as flexibility, not on a panel being cheaper"* | Owner message, transcript `2c1b09e2`, `2026-08-26T06:18:53Z`. |
| *"Real feature work, larger scope — if it doesn't fit cleanly in one package, say so and stop rather than half-ship it."* Listed among the items the owner allowed to be built unattended. | Owner message, transcript `01c85b90`, `2026-08-31T21:09:03Z`. |

Repository-side scope:
`docs/archive/2026-08/CONTINUE-DEMO-READINESS-ULTRACODE-PROMPT.md`, package D.

**Still owed by the owner:** how a user chooses N (a visible control, a URL
parameter, or not exposed), and the range to pin (`2..4` or `3..4`). FR-004 and
AC-007 still say four model slots. Asked on 2026-09-22; unanswered when this
file was written.

## W5 — quick-answer mode, N = 1

The shape is in the same approved plan, "Settled decisions" §5:

> So N=1 ships as a **distinct "Quick answer" mode**: keeps the answer, **source
> support and citation coverage**, safety notices and the cost receipt; drops the
> agreement ring, verdict band, debate transcript and convergence-based trust.

In the `2026-08-31T21:09:03Z` message the owner listed W5 among work not to
attempt unattended, with the reason given as *"blocked on W4"*.

**Still owed by the owner:** a yes or no on building it straight after W4
lands. Asked on 2026-09-22; unanswered when this file was written.

## W7 — Google sign-in and logout

| What | Source |
|---|---|
| *"Google sign-in — unpinned, no reliable "done" shape chosen yet, needs scoping with me first"* | Owner message, transcript `01c85b90`, `2026-08-31T21:09:03Z`. |
| Durable accounts and history were moved to a later enhancement. Of the nine rows in that log (CHG-001 to CHG-009), CHG-003 is the only one that mentions accounts or sign-in. | `docs/19-change-control-log.md`, row `CHG-003`, dated 2026-06-17; `grep -n -i "account\|sign-in\|google" docs/19-change-control-log.md`. |

**Still owed by the owner:** a scoping conversation. No build is authorised.
