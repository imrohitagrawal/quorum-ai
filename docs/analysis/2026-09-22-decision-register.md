# Decision register — W4, W5, W7 (2026-09-22)

**RECONSTRUCTED FROM SESSION TRANSCRIPTS — AWAITING OWNER CONFIRMATION.**

This file records what the product owner said, or sent, about three board rows,
with where each sentence came from. **Only the 2026-08-26 quote is the owner's
own typing.** The two 2026-08-31 lines were drafted by an assistant and then
sent by the owner; see below. It exists because none
of it was in the repository, so every new session labelled these rows
"undecided" and asked again.

It is **not** a decision record. No CHG row and no ADR has been filed for any
row below, and none should be until the owner confirms this text. Nothing here
is "Accepted".

## How each quote was checked

Every quote below was found by searching a session transcript under
`~/.claude/projects/-Users-rohitagrawal-Projects-quorum-ai/` and parsing the
matching record to confirm its `type` is `user`. The 2026-08-31 lines contain
hard line breaks in the transcript, so a one-line `grep -F` finds only
fragments of them; they are shown here with the breaks joined. Timestamps are
the transcript's own, in UTC. The transcripts
are outside this repository, so a reader without that machine cannot re-run
the check; that is the reason for the AWAITING CONFIRMATION label.

The two 2026-08-31 lines come from one long prompt. **An assistant drafted
it**: transcript `d1d57431`, a record of type `assistant` at
`2026-08-31T21:06:46Z`, opens "Here's the self-autonomous prompt, ready to
paste" and contains both lines. The owner sent that prompt as a `user` message
in transcript `01c85b90` at `2026-08-31T21:09:03Z`. So they are words the owner
chose to send, not words the owner wrote, and they carry less weight than the
2026-08-26 quote.

## The owner's most recent statement on all three

Owner's own typing, transcript `5512d375`, `2026-09-21T16:41:52Z`:

> For the W4, W5, and W7 also, I think we had already discussed these three
> options, and I had given you my responses. I'm not sure why it is still
> showing product scope, my call. All of these items have already been
> discussed, and the plan was there to be worked upon.

This register exists because of that message.

## W4 — variable panel size, N in {2, 3, 4}

| What | Source |
|---|---|
| The plan containing W4 was approved. | Plan-approval event, transcript `fcaa7c25`, `2026-08-25T20:43:24Z`. Plan of record: `~/.claude/plans/i-think-you-did-quiet-stearns.md`, "Settled decisions" §5 and work item 3. |
| *"The two, three, or four-model flexibility was provided to the user. We cannot force the user to always select four panels, and it depends on the user and how you want to use it. It was given as flexibility, not on a panel being cheaper …"* (the sentence goes on; the message is a discussion of #290, not an instruction about W4) | Owner's own typing, transcript `2c1b09e2`, `2026-08-26T06:18:53Z`. |
| *"Real feature work, larger scope — if it doesn't fit cleanly in one package, say so and stop rather than half-ship it."* Item 7 of the priority list in a prompt for an unattended overnight run. | Assistant-drafted, sent by the owner: transcript `01c85b90`, `2026-08-31T21:09:03Z`. |

Repository-side scope:
`docs/archive/2026-08/CONTINUE-DEMO-READINESS-ULTRACODE-PROMPT.md`, package D.

**Still owed by the owner:** how a user chooses N (a visible control, a URL
parameter, or not exposed), and the range to pin (`2..4` or `3..4`). FR-004 and
AC-007 still say four model slots. Asked at 2026-09-21T20:16Z; unanswered when this
file was written.

## W5 — quick-answer mode, N = 1

The shape is in the same approved plan, "Settled decisions" §5:

> So N=1 ships as a **distinct "Quick answer" mode**: keeps the answer, **source
> support and citation coverage**, safety notices and the cost receipt; drops the
> agreement ring, verdict band, debate transcript and convergence-based trust.

The `2026-08-31T21:09:03Z` prompt (assistant-drafted, sent by the owner) lists
W5 among work not to attempt unattended, with the reason given as
*"blocked on W4"*.

**Still owed by the owner:** a yes or no on building it straight after W4
lands. Asked at 2026-09-21T20:16Z; unanswered when this file was written.

## W7 — Google sign-in and logout

| What | Source |
|---|---|
| *"Google sign-in — unpinned, no reliable "done" shape chosen yet, needs scoping with me first"* | Assistant-drafted, sent by the owner: transcript `01c85b90`, `2026-08-31T21:09:03Z`. |
| Durable accounts and history were moved to a later enhancement. Of the nine rows in that log (CHG-001 to CHG-009), CHG-003 is the only one about user accounts. `grep -c -i "account\|sign-in\|google"` matches six rows, but the other five are the words "accounting" (CHG-005) and "per-account daily envelope" (CHG-006 to CHG-009), which concern spend; "sign-in" and "google" match nothing. | `docs/19-change-control-log.md`, row `CHG-003`, dated 2026-06-17. |

**Still owed by the owner:** a scoping conversation. No build is authorised.
