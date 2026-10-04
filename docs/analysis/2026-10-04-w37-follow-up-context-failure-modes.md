# W37 — follow-up context: failure modes before the code

Written 2026-10-04 before the change (AGENTS.md rule 16e: this changes what a run
costs). Board row W37. Decision: CHG-026 (g), the owner's M08 point 5 (*"If we do not
have context or a track of those questions being sent to models, then how would the
models understand that this is a follow-up question?"*), and, as a session recorded it on
2026-07-23, *"prior question + final synthesis in the prompts"*
(`docs/archive/2026-08/UI-BUG-TRIAGE-2026-07-23-ANALYSIS.md`, "User decisions"; no
transcript of that day is kept, so the words cannot be checked against the owner's). On
2026-10-04 the owner accepted ADR-0140's calls and asked for both follow-up buttons back
(CHG-027). Design: ADR-0143.

## Mechanism today (read on `4ba35ce`)

- The API accepts `context: {prior_question, prior_synthesis}` on estimate, create and
  the safety-warnings probe (`query_runs._check_context`, one implementation). Limits:
  20,000 and 60,117 characters (`FINAL_SYNTHESIS_MAX_CHARS`).
- **The page sends no context on any run** (`app.js` request-body builder comment).
- Where context goes when a client does send it:

| Call | Sent | Priced (`costs._cost_components`) |
|---|---|---|
| Each answer call (2–4 slots, or quick's one) | nothing (`providers.py` per-slot call passes no `context`) | nothing |
| Debate (moderator, or each critic under peer critique) | `prior_question`, system message | `prior_question + prior_synthesis` |
| Synthesis (5 section calls) | `prior_question` in the system message, `prior_synthesis` in the user message | `2 × (prior_question + prior_synthesis)` |
| Judge | nothing | nothing |

- A quick request with context is refused (ADR-0126 5a).
- The confirmation token is bound to the account, the estimated cost, the panel and the
  shape (ADR-0123), not the text; create re-prices the request it receives.

## What a follow-up costs today, if a client sent context (measured, hermetic)

`uv run python scripts/proofs/w37_follow_up_cost_sweep.py` on the unchanged tree
(`4ba35ce`): built-in price table, live catalog disabled, no network, no paid call. Default
four models, the question "How should a small team choose between Postgres and MySQL?",
judge on and peer critique off — production's posture on `/status`, 2026-10-04 (judge
model `openai/gpt-4.1-mini` per the 2026-09-10 telemetry; `/status` does not report it;
live execution off, so production runs are simulated, and simulated runs
deduct from the daily allowance like live ones, CHG-026 h). Real final answers in
production telemetry (`docs/analysis/2026-09-10-telemetry-tokens.jsonl`, synthesis stage,
three runs) total 9,338 / 9,663 / 9,693 completion tokens, about 38,000 characters at four characters a token (the telemetry
keeps no character count).

| Final answer (chars) | Typical | Ceiling | Band | Runs in the $0.40 day at that typical |
|---|---|---|---|---|
| none (fresh question) | 0.1134 | 0.1927 | allow | 3 |
| 8,000 | 0.1224 | 0.2018 | allow | 3 |
| 38,000 (typical) | 0.1562 | 0.2355 | allow | 2 |
| 60,117 (the limit) | 0.1811 | 0.2604 | allow | 2 |

With peer critique on, the 60,117 row reaches `require_confirmation` (ceiling 0.3142).
These figures include the over-pricing in rows 3 and 4 below and exclude the answer
calls (row 1); ADR-0143 re-measures with the same script after the change.

## Failure modes and the design answer

| # | Failure | Harm | Answer |
|---|---|---|---|
| 1 | Context sent to the answer calls but not priced there. | Spend above the estimate; the ceiling stops being a ceiling. | Each answer call's input is priced with the context it is sent, in the typical figure and the ceiling, panel and quick alike. |
| 2 | Context priced but not sent (the page sends none today). | The owner's decision is not honoured; the estimate is wrong the day it starts. | The page sends it; a server test asserts the text reaches every answer call's messages. |
| 3 | Debate is priced for `prior_synthesis` it is never sent. | The typical figure — what the daily allowance is charged — is too high for every follow-up. | Price what is sent: the prior question only. |
| 4 | Synthesis prices the context twice; it is sent once. | Same as 3. | Price it once per section call. |
| 5 | The estimate and create bodies carry different context. | A confirm-band follow-up loops on "the cost changed" (the token is bound to cost). | One builder makes both bodies and the warnings probe body from the same state. |
| 6 | The warnings probe gets no context while create does. | The probe says no acknowledgement is needed and create refuses (issue #155). | The probe body carries the same context. |
| 7 | The prior answer is client-supplied text placed in a system message. | A crafted "previous answer" instructs the model. | Fenced as data and flattened, after our own instructions. `prior_question` is fenced there today but not flattened; flattening it too is ADR-0143 decision 1. |
| 8 | Context placed in the user message. | The web-search request may be built from the user message; 38,000 characters would be searched. (How OpenRouter builds the search query is UNVERIFIED; this design does not depend on it.) | Context goes in the system message; the user message stays the new question. |
| 9 | The page composes a prior answer longer than 60,117 characters (headings added to five full sections). | A 422 on the follow-up; the user cannot ask it. | The page sends the five section texts joined without added headings, cut to the limit; the server limit is unchanged. |
| 10 | Context from the wrong result: the session list re-opens an older result. | The models get a different conversation from the one on screen. | Context is taken from the result on screen when "Review & run" is pressed. |
| 11 | A result with no final answer (failed, stopped, timed out) offers "Follow up on this". | A follow-up with nothing to follow. | The mode buttons show only on a result with a final answer; otherwise the note says the next question is answered on its own. |
| 12 | A quick result's follow-up, or a follow-up asked in quick mode, is refused (ADR-0126 5a). | "Follow up on this" fails in one of the two modes. | Quick accepts context and sends it to its one answer call; the prior answer of a quick result is its answer text. ADR-0143 supersedes 5a. |
| 13 | "New question", the brand link or "Start fresh" leaves context attached. | A fresh question sent as a follow-up and charged for the context. | Only "Review & run" in follow-up mode attaches it; every way to the composer that starts something new clears it; "Back to the question", the cost confirmation's Back and browser Back/Forward keep it (ADR-0143 decision 5); the composer shows the line and a way to drop it. |
| 14 | The composer shows nothing about the context. | The user does not know why the estimate went up. | The composer shows "Following up on: …" with the prior question while context is attached. |
| 15 | The prior question in "Following up on: …" is rendered as HTML. | Injection into the page. | Text only (`textContent`), shortened for display. |
| 16 | "Start fresh" empties the session list (bug 1). | Regression of ADR-0140 decision 1. | It only switches the mode. |
| 17 | Context written to logs, the run-history store or the account history. | Personal text kept where `docs/48` says it is not. | No new store or log field; the telemetry keeps its character counts only. |
| 18 | A follow-up to a high-stakes question needs the acknowledgement again (`high_stakes_required` reads the context). | The user is surprised by the box. | Existing behaviour, kept; the probe gets the context (row 6) so the box shows before the estimate. |
| 19 | A model's context window is smaller than question + search context + prior answer. | The provider refuses; the slot falls back to simulation and the run is marked degraded. | Recorded as a known limit (no catalog model's window was measured here). |
| 20 | Follow-ups use the $0.40 allowance faster (the table above). | Fewer runs a day. | The estimate shows the real figure before anything runs; ADR-0143 records the measured consequence for the owner. |
