# Decision register — W4, W5, W7 (2026-09-22)

**RECONSTRUCTED FROM SESSION TRANSCRIPTS — CONFIRMED BY THE PRODUCT OWNER on
2026-09-24** (*"confirmed"*, transcript `df5e9b18`, `type: user`,
`2026-09-24T06:59:26Z`; the 2026-09-24 section below, D9, records the
exchange), for the sections dated up to 2026-09-22. The section dated 2026-09-23 at the end
is different in kind: the owner gave those decisions in chat, in their own
messages, and CHG-011 records them; see that section for how each was checked.

This file records what the product owner said, or sent, about three board rows,
with where each sentence came from. The two 2026-08-31 lines were drafted by an
assistant and then sent by the owner; see below. It exists because none
of it was in the repository, so every new session labelled these rows
"undecided" and asked again.

The sections up to 2026-09-22 were **not** a decision record when written: no
CHG row and no ADR was filed from them. The owner confirmed their text on
2026-09-24 (D9 below; CHG-012), so they may now be cited as confirmed. (W4's own decisions of 2026-09-22 were then taken in chat and recorded
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
the check; that was the reason for the AWAITING CONFIRMATION label this file
carried until 2026-09-24. The
2026-09-23 section marks, quote by quote, which words are the owner's and
which are the session's.

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
D9 text below follows that file's wording (D6 abridged, D8 annotated); the
owner has not separately confirmed that wording, and the "party paying"
principle sentence in D8 is the session's phrasing. The three direct
quotations, in D1, D5 and D8, are the owner's own `type: user` words, each
checked in that transcript.
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
Abuse limits under a user key, the session's reading of the owner's
numbers: about 100 to 200 sessions per IP per day (not 2: office networks
share an IP); about 10 requests per 1 to 2 minutes. The owner's sentence (`16:21:02Z`): "I would not keep 2 new
sessions per IP because that is too low. … We should look at 100 or 200
requests, that is something, but yes, within 1 or 2 minutes, we can have a
limit of, say, 10 requests." "Sessions per IP per day" for the first number
is the session's reading, not the owner's noun. Likewise the keep/drop rails
list and the three-pull-request sequencing above were the session's
suggestions in that chat, accepted by the owner with "For the rest, I agree
with all your suggestions" (`16:21:02Z`); the owner's own typed points are
the $5 window, live execution and the judge on by default, "everything should
be a user-defined flag", and the limits quoted above. Sequencing: own board item; failure-mode page first; then
three PRs (key intake and scoping; rails by credential source plus the
budget window; user toggles and per-run shape). Nothing of this is built now.

**D9. Future-proofing that binds PR 3 and W5 now.**
- One predicate for shape copy (`_peer_critique_in_effect`); BYOK adds one term there.
- "Live execution" is to mean "a key that may be spent" (app or user); the BYOK ADR generalises it; nothing new reads the app flag directly.
- Every optional stage stays a priced `by_stage` row.
- The confirmation token must bind the slot list and the shape BEFORE any per-run toggle exists; W5 must not add a per-run choice first.

**W5, restated on 2026-09-23:** the session-written prompt (at the owner's
request, above) queues it "only if its decision register entry is complete
enough to build; otherwise write the scoping and stop". The entry above names the mode's SHAPE (what it keeps and
drops) and nothing else; a W5 scoping note naming what is still owed follows
in its own docs-only pull request.

## 2026-09-24 — the backlog decisions: W5, #458, #459, #447, #268, the order, W7, BYOK timing, and this file's confirmation

**DECIDED by the product owner, 2026-09-24, in chat.** Source and how it was
checked: the owner's own messages (`type: user`) in transcript `df5e9b18`,
at `2026-09-24T06:20:42Z`, `06:24:09Z`, `06:55:41Z`, `06:58:37Z` and
`06:59:26Z`, each parsed from the transcript file and its record type
confirmed. The session's replies the owner was answering are `assistant`
records at `06:08:03Z`, `06:11:04Z`, `06:21:09Z`, `06:24:40Z`, `06:56:02Z`,
`06:57:41Z` and `06:58:46Z`; the session's final restatement of the course of
action, after the last decision, is the `assistant` record at `06:59:32Z`. Every
sentence in quotation marks below is the owner's, verbatim, typing errors
included; every sentence outside quotation marks is the session's phrasing
of what the owner answered, or the session's own proposal, and says which.
At `07:01:59Z` the session wrote these decisions into the root prompt
`CONTINUE-BACKLOG-2026-09-24-ULTRACODE-PROMPT.md` (the `Write` tool record;
untracked; announced in an `assistant` record at `07:02:14Z`), and the session that executed that prompt wrote this
section from the transcript, not from the prompt. Recorded the same day in
CHG-012.

**D1. W5, the quick-answer mode (`06:20:42Z`).** Owner: *"W5: Guard: separate
mode: "quick", Copy: "Quick answer — one model, no debate", show info message
that "four models by default, 2 debates and 1 sourced answer" which we have
been using in this product as a feature available, Price posture: judge on,
cost gate kept, so user knows that did the 1 model approach was actually good
for him/her or not. Judge will help user understand whether the answer that
model give is how much accurate."* The session's reading: a separate request
shape (`mode: "quick"`) that never touches the panel validator (2 to 4
stays, `MIN_SLOT_COUNT = 2`); the mode's copy is the owner's sentence; the
mode shows an information line stating the product default; the judge runs
and is a priced `by_stage` row; the per-run cost gate applies. What the mode
keeps and drops is unchanged from the approved plan of 2026-08-25 quoted in
the W5 section above: it keeps the answer, source support, citation
coverage, the safety notices and the receipt, and drops the agreement ring,
the verdict band, the debate transcript and convergence-based trust. It adds
no per-run toggle of any other kind (CHG-011 D9).

**D2. #458, the peer-critique flag (`06:20:42Z`).** Owner: *"#458: yes,
couple the flag"*. The owner was answering the session's recommendation at `06:11:04Z`
("yes, couple the flag to the window scripts, and flip it to false now"),
so the session's reading is: couple
`PEER_CRITIQUE_ENABLED` to the live-execution window mechanism, so that
closing a window turns it off together with live execution; flip the
production value to `"false"` in `fly.toml` in the same change; peer
critique turns on again only by the window mechanism.

**D3. #459, the watchdog's latency (`06:20:42Z`).** Owner: *"#459: option 1
only."* Option 1 is the first of the two the session listed at `06:08:03Z`, which
are the issue's own two: correct every stated
latency to the measured band, with the date and the sample size from the
issue; do not tighten the cron; do not move the check.

**D4. #447, the judge and the sources (`06:20:42Z`, `06:24:09Z`).** Owner:
*"#447: JUdge should be able to verify the sources then only will be able to
judge properly. I want you to choose the right option here. confirm me your
answer."* The session had recommended Route A at `06:11:04Z`; asked to choose
again after the owner's sentence, it chose the issue's Route B at
`06:21:09Z`, a credential-guarded fetcher that reads the cited pages so the
judge grades what it has read, with one free capture first to learn whether
OpenRouter's annotations already carry page content. Owner: *"#447: I
agree with your choice"*.

**D5. #268 (`06:24:09Z`).** Owner: *"#268: pick b"*. Option (b) was the
second of the two the session laid out at `06:21:09Z`: keep `cost_web_search_context_tokens = 2000` and
restructure the worst-case bound so that a truer constant cannot move an
affordable mix into `BLOCK`. The constant itself does not move on this
decision; a new value is a later owner decision with its own CHG row.

**D6. The order (`06:24:09Z`).** Owner: *"Order: W5 first (small, unblocked
now), then W7 as its own package."* That sentence is the session's own line
from `06:21:09Z` ("Order: W5 first (small, unblocked now), then W7 as its
own package with …"), typed back by the owner — the same shape this file
labels "assistant-drafted, sent by the owner" for the 2026-08-31 lines, so
it carries that weight and no more. The owner had offered at `06:20:42Z`
that W7 could be clubbed with W4 and W5 (*"you can decide to club this with
W4 and W5 where things can be done in 1 shot."*); the session recommended
against clubbing and the owner chose this order. The full order the
session then proposed at `06:57:41Z` and restated at `06:59:32Z` — #458,
the confirmation-token binding, W5, #459, #447, #268, W7, BYOK — is the
session's sequencing around the owner's two fixed points (W5 before W7;
BYOK last, D8) and was not contested.

**D7. W7, sign-in with history (`06:20:42Z`, `06:55:41Z`).** Owner: *"W7:
the purpose of sig-in is to preserve the history of the searches from a
account. THis can be limited to last 5 searches for example if we face issue
in storage."* Asked whether the session had a better rule, the session
proposed (`06:24:40Z`) a count AND an age limit, storing a summary row per
run rather than the whole run, and — wrongly — deleting on sign-out. Owner
(`06:55:41Z`): *"do you suggest that Count and age together should be
configurable like plug-and-play and not hard coded? what you suggest? what
do you mean by Delete on sign-out? the whole purpose will be forfeited if we
delete the history on every sign-out! but yes on account deletion we should
remove, but how are we planning to give an option to User for account
deletion?"* The session withdrew sign-out deletion and answered
(`06:56:02Z`) with the design below, which it summarised back to the owner
at `06:57:41Z` under "W7 details agreed"; the owner's next messages moved
on to BYOK timing and the register without objection. So the design is the
SESSION's, accepted by the owner in that sense and not restated by the
owner in their own words:
- keep the last 5 runs per account AND drop anything older than 30 days,
  both as environment settings with pinned defaults (`HISTORY_KEEP_COUNT`,
  `HISTORY_KEEP_DAYS`), not a toggle surface, not per-user;
- store the summary row per run (question, date, verdict line, cost, run
  id), not the whole run; the full result is re-openable only while the run
  is still in the run store;
- nothing is deleted on sign-out; history belongs to the account;
- account deletion: a typed-confirmation action on one authenticated
  endpoint that removes the account, its history rows and its session in one
  transaction and signs the browser out; operator run rows keep their counts
  with the account id set to null; the 24-hour spend envelope stays keyed on
  a one-way hash of the Google subject for 24 hours after deletion so
  deletion cannot reset it;
- W7's pull request rewrites "Results are ephemeral" (`main.py`
  `_app_description`, CHG-004) for signed-in users, files the CHG row and
  the threat-model rows, and writes the ADR.
Google sign-in only; no password; no durable provider key (that is BYOK, D8).

**D8. BYOK timing (`06:58:37Z`).** Owner: *"BYOK delivery timing: after all
the current features and bugs are worked upon."* BYOK is last, after every
package above. ADR-0121 stays `PROPOSED — AWAITING OWNER` until then.

**D9. This file (`06:58:37Z`, `06:59:26Z`).** The owner asked *"what is
Confirmation of the reconstructed sections of the 2026-09-22 decision
register.?"*, the session explained (`06:58:46Z`) that the sections dated
up to 2026-09-22 were quoted from transcripts and carried the AWAITING label
until the owner confirmed the quotes were theirs, and the owner answered
*"confirmed"*. The label is removed from those sections by the pull request
that adds this section, and they are cited as confirmed by the product owner
on 2026-09-24 at `06:59:26Z`.
