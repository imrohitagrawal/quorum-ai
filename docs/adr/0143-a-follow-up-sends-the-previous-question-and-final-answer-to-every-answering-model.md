# ADR-0143: A follow-up sends the previous question and final answer to every answering model

## Status

Accepted — 2026-10-04, board row W37. The product owner decided the behaviour:
CHG-026 (g) (*"send the previous question and final answer to all four models; the
next-question box opens empty with 'Following up on: …'"*, from M08 point 5), their
2026-07-23 decision (*"prior question + final synthesis in the prompts"*), and on
2026-10-04 (CHG-027) *"In W37 bring back both 'Follow up on this' and 'Start fresh'"*,
the landing rename and the hint wording. The shape below is the session's design; the
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
   ceiling: answer calls for the question and the answer; debate (the moderator, or
   each critic) for the question only, which is what it has always been sent;
   synthesis for both, once per section call. The judge gets no context and is not
   priced for any.
3. **Quick accepts context** and sends it to its one answer call. This supersedes
   ADR-0126 decision 5a.
4. **The page sends it.** On a result that has a final answer, "Ask your next
   question" shows **Follow up on this** (pressed by default) and **Start fresh**.
   In follow-up mode the note reads *Following up on: "‹previous question›"* and
   says the models will see that question and its final answer; in Start fresh mode
   it says the next question is answered on its own. The box opens empty. A result
   with no final answer (stopped, failed, timed out) shows no mode buttons and the
   on-its-own note. (Measured by the test designer: the page opens the result
   view only when a final synthesis exists, so the reachable case is a synthesis
   whose sections are all empty.)
5. **"Review & run" in follow-up mode attaches the context** to the composer, which
   shows the same *Following up on* line with a **Start fresh** button that drops it.
   The estimate, the safety-warnings probe and the run are built from the same state,
   so all three carry the same context. Every other way to the composer — "New
   question", the brand link, the landing page — clears it.
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
  name; the moderator is not one of the four models.
- **Keep debate and synthesis over-priced** as a safety margin. The typical figure
  is what the daily allowance is charged, so every follow-up would pay for text
  never sent.
- **Trim the previous answer below the server limit.** Not what the owner decided;
  the measured cost below is the input for that decision if they want it.

## Consequences

- Measured after the change with `scripts/proofs/w37_follow_up_cost_sweep.py`
  (built-in price table, production's posture): see the table in the pull request
  that carries this ADR; before the change, the failure-modes document has the same
  table. A typical follow-up (a 38,000-character final answer) costs more than a
  fresh question, so the $0.40 day holds fewer runs when some are follow-ups.
- Personal text is not stored anywhere new: no new store, log field or history
  column; `docs/48` is unchanged.
- A model whose context window is smaller than question + search context + previous
  answer is refused by the provider; that slot falls back to simulation and the run
  is marked degraded. No catalog model's window was measured here.
- Calls taken by the session (the owner may overturn any of them): (i) quick accepts
  context; (ii) debate is sent the previous question only; (iii) the composer line
  and its Start fresh button; (iv) "New question" and the brand link clear the
  context; (v) the full final answer up to the server limit, no smaller trim;
  (vi) one step back only.
