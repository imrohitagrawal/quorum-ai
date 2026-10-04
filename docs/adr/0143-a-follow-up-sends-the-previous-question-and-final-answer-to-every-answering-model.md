# ADR-0143: A follow-up sends the previous question and final answer to every answering model

## Status

Accepted — 2026-10-04, board row W37. The product owner decided the behaviour in
their message of 2026-10-04 (CHG-027), build item 1: *"W37: follow-up context — the
previous question and final answer go to all four models; the next-question box opens
empty with "Following up on: …"; bring back both follow-up buttons; plus the landing
rename and the hint wording."* and *"In W37 bring back both "Follow up on this" and
"Start fresh"."* It was first decided as CHG-026 (g), from M08 point 5 and M09 (the owner's reply to
the session's question "send context to all four models?"), with M10's *"Rest, I
agree with all your suggestions"*, and before that on 2026-07-23, as a
session recorded it: *"prior question + final synthesis in the prompts"*. The shape below is the session's design; the
points that are the session's own calls are listed under Consequences so the owner can
overturn them. Failure modes, listed before the code:
`docs/analysis/2026-10-04-w37-follow-up-context-failure-modes.md`.

## Context

The API has accepted `context: {prior_question, prior_synthesis}` since WP-G2, but the
page has never sent it, so no follow-up has ever reached a model as one. When a client
does send it, the four answer calls receive none of it and are not priced for it;
debate is priced for both texts and sent only the question; synthesis is priced for
both texts twice and sent each once. A quick request with context is refused
(ADR-0126 5a). The failure-modes document has the table and the measured cost.

## Decision

1. **Every answer call gets the context**: the 2–4 panel slots and the quick answer's
   one model. The previous question and the previous final answer go in the system
   message, after our own instructions, each fenced as data and flattened the way
   synthesis already treats `prior_synthesis`. The user message stays the new
   question alone, so the web search is not handed the old answer. The previous
   question is fenced in the one shared system-message builder that debate and
   synthesis also use, so flattening it there flattens it in their prompts too.
   That is intended: today a previous question can still start its own line inside
   the fence.
2. **Each call is priced for what it is sent**, in the typical figure and the
   ceiling: answer calls for the question and the answer (the fixed words around them
   sit inside the flat 350 tokens already priced for that system message); debate
   (the moderator, or each critic) for the question only, which is what it has always
   been sent, plus the fixed words around it; synthesis for both texts and their fixed
   words, once per section call. For debate and synthesis the fixed words are measured
   from the functions that write them, so price and prompt cannot drift apart; for an
   answer call a test guards that they stay inside the flat 350. The judge gets no context and
   is not priced for any.
3. **Quick accepts context** and sends it to its one answer call. This supersedes
   ADR-0126 decision 5a.
4. **The page sends it.** On a result that has a final answer, "Ask your next
   question" shows **Follow up on this** (pressed by default) and **Start fresh**.
   In follow-up mode the note reads *Following up on: "‹previous question›"* and
   says the models will see that question and its final answer; in Start fresh mode
   it says the next question is answered on its own. The box opens empty. A result
   with no final answer (stopped, failed, timed out) shows no mode buttons and the
   on-its-own note. (A finished panel run on the real backend always has the five
   sections, so the empty-answer case is tested with a mocked payload; a failed,
   stopped or timed-out run re-opened from the session list reaches the result view
   with no synthesis and also offers no follow-up.)
5. **"Review & run" in follow-up mode attaches the context** to the composer, which
   shows the same *Following up on* line with a **Start fresh** button that drops it.
   The estimate, the safety-warnings probe and the run are built from the same state,
   so all three carry the same context. Every way to the composer that starts something
   new clears it: "New question", the brand link, the landing page, and the "Start a
   new run", "Start your own query" and "Stop it & start new" actions on a failure or
   busy card. The ways that go back to the question being worked on keep it: "Back to
   the question", the cost confirmation's Back, and browser Back and Forward. A run that finishes onto its result
   leaves no context attached. Clearing the context also drops an estimate still
   loading for it, and the composer's Start fresh is unavailable while the run that
   carries the context is being created.
6. **What is sent.** The previous question is the question of the result on screen.
   The previous final answer is, for a panel result, the five synthesis sections in
   the order the page shows them (consensus, disagreement, uncertainty,
   recommendation, source support), joined by blank lines, cut to the server's
   60,117-character limit; for a quick result, its answer text. Only one step back:
   a follow-up to a follow-up carries the latest question and answer, not the chain.
7. **"Start fresh" only switches the mode.** It does not empty the session list
   (ADR-0140 decision 1 stands).
8. **The landing button "Run the debate →" is renamed "Choose models →"**, and the
   composer hint's last part becomes the owner's wording: *"Press **See the
   estimate** to check the cost first, or **Run now** to start straight away. If a
   run costs more than usual, it asks you first."*

## Rejected alternatives

- **The server looks up the previous run by id** instead of trusting client text.
  Stronger against a forged "previous answer", but runs live in memory with a
  time limit, and a run made before signing in answers 404 after it. The text is the
  user's own, priced, fenced and capped. Revisit with W36's stored history.
- **Context in the user message.** The web search may be built from it (how
  OpenRouter builds the search query is unverified); the system message avoids the
  question.
- **Send the previous answer to debate too.** More spend for calls the owner did not
  name: the moderator call is not one of the four answer calls (in production it runs
  slot 2's model), and under peer critique each critic gets the question only.
- **Keep debate and synthesis over-priced** as a safety margin. The typical figure
  is what the daily allowance is charged, so every follow-up would pay for text
  never sent.
- **Trim the previous answer below the server limit.** Not what the owner decided;
  the measured cost below is the input for that decision if they want it.

## Consequences

- Measured with `uv run python scripts/proofs/w37_follow_up_cost_sweep.py` (built-in
  price table, live catalog disabled, no call made; default four models; judge on
  and peer critique off as production's `/status` reported on 2026-10-04; judge model
  `openai/gpt-4.1-mini` per the 2026-09-10 telemetry, since `/status` does not report it).
  "Before" is the unchanged tree `4ba35ce` as if a client had sent the context; the
  page sent none, so no follow-up from the page was ever priced this way. The last column is how many runs at that
  typical figure fit in the $0.40 day.

  | Final answer (chars) | Before: typical / ceiling | After: typical / ceiling | Runs a day after |
  |---|---|---|---|
  | none (fresh question) | 0.1134 / 0.1927 | 0.1134 / 0.1927 | 3 |
  | 8,000 | 0.1224 / 0.2018 | 0.1191 / 0.1984 | 3 |
  | 38,000 (typical) | 0.1562 / 0.2355 | 0.1397 / 0.2190 | 2 |
  | 60,117 (the limit) | 0.1811 / 0.2604 | 0.1549 / 0.2342 | 2 |

  Every row is `allow`. With peer critique on, the 60,117 row moves from
  `require_confirmation` (0.3142) to `allow` (0.2731), and the 38,000 row is
  0.1595 / 0.2579. At every length in the table a follow-up is cheaper than the old
  pricing quoted, because debate and synthesis are no longer priced for text they are
  not sent; that saving is larger than the new price of the four answer calls. For a
  previous answer shorter than about 250 characters it is the other way round, by
  $0.0001 (50 characters: 0.1135 before, 0.1136 after, typical), because the fixed
  wording is now priced. It still costs more than a fresh
  question: at a typical final answer, two runs fit in the day instead of three.
- The fixed text this change adds to each answer call's system message (a follow-up
  sentence, the untrusted-data rule, labels and fences) brings the default answer
  system prompt to 1,175 characters, 293.75 tokens, inside the flat 350 tokens
  already priced for it (measured by the builder; recorded in
  `providers._follow_up_system_suffix`).
- This supersedes ADR-0126 decision 5a and ADR-0140 decision 3 (and decision 8's
  last hint sentence); each now says so in its Status, its decisions left as written.
- Personal text is not stored anywhere new: no new store, log field or history
  column; `docs/48` is unchanged.
- A model whose context window is smaller than question + search context + previous
  answer is refused by the provider; that slot falls back to simulation and the run
  is marked degraded. No catalog model's window was measured here.
- Calls taken by the session (the owner may overturn any of them): (i) quick accepts
  context; (ii) debate is sent the previous question only; (iii) the composer line
  and its Start fresh button; (iv) "New question" and the brand link clear the
  context; (v) the full final answer up to the server limit, no smaller trim;
  (vi) one step back only; (vii) both texts go in the system message and the user
  message stays the new question; (viii) debate and synthesis are re-priced to exactly
  what they are sent, wording included, which lowers their charge for a previous
  answer longer than about 250 characters and raises it slightly below that; (ix) the previous
  question is now flattened for debate and synthesis too; (x) the server trusts the
  client's text rather than looking up the previous run; (xi) a result with no final
  answer offers no follow-up; (xii) the previous answer is the five sections in
  display order joined by blank lines, taken from the result on screen; (xiii) "all
  four models" is read as the answer calls, so under peer critique the critics get the
  question only; (xiv) which ways to the composer keep or clear the context
  (decision 5); (xv) an answer call's fixed follow-up wording is not priced on its
  own, it fits the flat 350-token system allowance (1,175 characters, measured),
  while debate and synthesis are priced for theirs; (xvi) the composer footer also
  uses the hint sentence of CHG-027 (d), replacing "anything needing confirmation
  still pauses for your approval" — the owner named only the hint; (xvii) the cost
  confirmation repeats "Following up on: …"; (xviii) with one model the note says
  "the model"; (xix) a result re-opened from the session list opens with an empty
  box; (xx) a context with no previous answer says nothing about a final answer,
  and one with no previous question says nothing about a question; (xxi) a finished
  run leaves no context attached, so browser Back to the composer shows none.
- The price assumes four characters a token, an average rather than a bound
  (ADR-0095). A follow-up now sends up to 80,117 characters of client text to each
  of up to four answer calls at the slot's own price, so text that tokenizes worse
  than average (code, some non-English scripts) can cost more than the ceiling says.
  How much worse is unmeasured: no tokenizer is installed here.
- Known limits found by review and left for later (browser review of 2026-10-04):
  on a phone, the "Following up on" line is below the first screen after "Review &
  run"; a follow-up to a high-stakes question asks for the acknowledgement again
  without saying the previous question is why; the run's pop-up messages can cover
  the line for a few seconds (board row W46); the mode buttons wrap to two lines at
  390 px. "Go to run" on a "one run at a time" card does not open the other run's
  result once this tab has finished or re-opened a run (board row W49); it would otherwise pair this tab's last question with that
  run's answer.
