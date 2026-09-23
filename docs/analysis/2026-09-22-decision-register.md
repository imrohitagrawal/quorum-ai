# Decision register — W4, W5, W7 (2026-09-22)

**RECONSTRUCTED FROM SESSION TRANSCRIPTS — AWAITING OWNER CONFIRMATION**, for
the sections dated up to 2026-09-22. The section dated 2026-09-23 at the end
is different in kind: the owner gave those decisions in chat, in their own
messages, and CHG-011 records them; see that section for how each was checked.

This file records what the product owner said, or sent, about three board rows,
with where each sentence came from. The two 2026-08-31 lines were drafted by an
assistant and then sent by the owner; see below. It exists because none
of it was in the repository, so every new session labelled these rows
"undecided" and asked again.

The sections up to 2026-09-22 are **not** a decision record: no CHG row and
no ADR was filed from them, and none should be until the owner confirms that
text. (W4's own decisions of 2026-09-22 were then taken in chat and recorded
in CHG-010 and ADR-0120, as its section notes.) The 2026-09-23 section is
recorded in CHG-011.

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

Owner's own message, transcript `5512d375`, `2026-09-21T16:41:52Z`:

> For the W4, W5, and W7 also, I think we had already discussed these three
> options, and I had given you my responses. I'm not sure why it is still
> showing product scope, my call. All of these items have already been
> discussed, and the plan was there to be worked upon.

## W4 — variable panel size, N in {2, 3, 4}

| What | Source |
|---|---|
| The plan containing W4 was approved. | Plan-approval event, transcript `fcaa7c25`, `2026-08-25T20:43:24Z`. Plan of record: `~/.claude/plans/i-think-you-did-quiet-stearns.md`, "Settled decisions" §5 and work item 3. |
| *"The two, three, or four-model flexibility was provided to the user. We cannot force the user to always select four panels, and it depends on the user and how you want to use it. It was given as flexibility, not on a panel being cheaper …"* (the sentence goes on; the message is a discussion of #290, not an instruction about W4) | Owner's own message, transcript `2c1b09e2`, `2026-08-26T06:18:53Z`. |
| *"Real feature work, larger scope — if it doesn't fit cleanly in one package, say so and stop rather than half-ship it."* Item 7 of the priority list in a prompt for an unattended overnight run. | Assistant-drafted, sent by the owner: transcript `01c85b90`, `2026-08-31T21:09:03Z`. |

Repository-side scope:
`docs/archive/2026-08/CONTINUE-DEMO-READINESS-ULTRACODE-PROMPT.md`, package D.

**Decided by the owner in chat, later on 2026-09-22 (after this file was
first written), recorded in CHG-010 and ADR-0120:** (1) a visible remove/add
control per slot; (2) range `2..4`, four by default; (3) at N=2 with both
agreeing, a green "Both models agree (2 of 2)" band — the owner overruled the
session's "never a green band at N=2" — with the served trust capped at
`moderate`. Source: owner's own message, transcript `b56df1d3`,
`2026-09-22T15:02:03Z`; the owner's own words on the band were: *"a green unanimous band because the USER selected only 2 models ...
trust stays at the 'moderate' level"*.

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
| Durable accounts and history were moved to a later enhancement. | `docs/19-change-control-log.md`, row `CHG-003`, dated 2026-06-17. |

**Still owed by the owner:** a scoping conversation. No build is authorised.

## 2026-09-23 — W4's third pull request (the copy), and BYOK as a plan

**DECIDED (D1 to D7) and PLANNED (D8, D9) by the product owner, 2026-09-23.**
Source and how it was checked: the owner's own messages (`type: user`) in
transcript `23fee4a3`, between `2026-09-23T15:15:46Z` ("We cannot change the
main heading …") and `16:21:02Z` (the abuse-limit numbers); at `16:23:25Z`
the owner asked the session for a self-running prompt, and the SESSION wrote
those decisions into the root prompt `CONTINUE-W4-PR3-AND-BYOK-ULTRACODE-PROMPT.md`
§4 at `16:25:17Z` (an `assistant` record; the file is untracked). The D1 to
D9 text below is that file's wording, which the owner has not separately
confirmed; the two direct quotations in D1 and D5 are the owner's own words.
Recorded the same day in CHG-011; ADR-0120 carries the amendment.

**D1. Headline.** The landing headline stays exactly
`Four AI models, one sourced answer.` Owner: "We cannot change the main
heading to '2 to 4 AI models, 1 sourced answer.' That is completely wrong,
and I would not approve that."

**D2. Subline.** One muted line under the headline, once, small:
`Your panel, your size: four models by default, three or two when that is all you need.`
No price claim in it, ever.

**D3. The copy rule.** Copy that describes the product describes the DEFAULT
(four). Copy that describes this composer state or this run reads the actual
count (two, three or four) and the actual shape.

**D4. Landing debate line, a capability, both shapes named:**
`Two rounds of debate, by the panel itself or by a moderator model, then one sourced synthesis.`

**D5. Composer shape line**, chosen by the deployment's posture through the
existing predicate `_peer_critique_in_effect` (main.py; ADR-0116) and
count-aware ("four" / "three" / "both"):
- Moderator shape (production today):
  `This run: a moderator model critiques all four answers, in two rounds, then one sourced synthesis.`
  `Peer critique, where each model critiques the others, is available and off on this deployment.`
- Peer shape (flag on AND live execution on):
  `This run: each of the four models critiques the others, in two rounds, then one sourced synthesis.`
Owner: the second sentence is "stated as a fact about this deployment".
Static copy must NEVER claim the models critique each other while the
moderator shape runs; `tests/unit/test_ui_honesty.py` refuses it and stays.

**D6. Where the count and shape change.** The debate panel's pre-run
placeholder, the result-view tooltips and the landing-to-composer transition
message become count-aware; the placeholder is also shape-aware per D5.
Landing eyebrow and `main.py`'s landing copy stay at four (D3).

**D7. Flags.** Flags stay environment settings. Money flags (live execution,
the judge) stay governed by the committed, watchdog-enforced window. No
admin toggle surface is built. Under the APP-OWNED key there is NO per-run
peer/moderator choice; it is an operator setting, shown honestly (D5).

**D8. Bring-your-own-key (BYOK) — PLANNED, NOT NEXT. Principle:** "the party
paying chooses the flags; the party at risk sets the rails." Under a user
key: live execution on by default; judge and peer critique are user toggles,
on by default, each a priced `by_stage` row in the estimate; the judge runs
on the user's OpenRouter key (same `call_with_prompt` seam, verified);
per-run peer/moderator choice allowed. Rails under a user key: DROP the
global daily ceiling, the per-account envelope and the live window; ADD a
user budget window, $5 default, the existing cost gate asking before a run
crosses it; KEEP the per-run hard cap and one run at a time per session.
Abuse limits under a user key, owner's numbers: about 100 to 200 sessions
per IP per day (not 2: office networks share an IP); about 10 requests per
1 to 2 minutes. The owner's sentence (`16:21:02Z`): "I would not keep 2 new
sessions per IP because that is too low. … We should look at 100 or 200
requests, that is something, but yes, within 1 or 2 minutes, we can have a
limit of, say, 10 requests." "Sessions per IP per day" for the first number
is the session's reading, not the owner's noun. Sequencing: own board item; failure-mode page first; then
three PRs (key intake and scoping; rails by credential source plus the
budget window; user toggles and per-run shape). Nothing of this is built now.

**D9. Future-proofing that binds PR 3 and W5 now.**
- One predicate for shape copy (`_peer_critique_in_effect`); BYOK adds one term there.
- "Live execution" is to mean "a key that may be spent" (app or user); the BYOK ADR generalises it; nothing new reads the app flag directly.
- Every optional stage stays a priced `by_stage` row.
- The confirmation token must bind the slot list and the shape BEFORE any per-run toggle exists; W5 must not add a per-run choice first.

**W5, restated on 2026-09-23:** the owner's queue says build it "only if its
decision register entry is complete enough to build; otherwise write the
scoping and stop". The entry above names the mode's SHAPE (what it keeps and
drops) and nothing else; a W5 scoping note naming what is still owed follows
in its own docs-only pull request.
