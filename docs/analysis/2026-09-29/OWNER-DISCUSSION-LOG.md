# The owner's points from 2026-09-28 to 2026-09-30, and their status

A plain restatement under CHG-102: the exact messages are kept in the owner's private
notes, outside this repository. The point numbers (M01 to M25) stay because other
documents cite them. File names cited below map as in this folder's `README.md`:
`INDEX.md` → `README.md`, `inv-results.md` → `owner-bugs-root-causes.md`,
`approach-research/synthesis.md` → `approach-synthesis.md`,
`skills-tools-research/shortlist.md` → `skills-tools-shortlist.md`. The decisions are
recorded as CHG-026. When a later session acts on a row, it updates the Status column
and names the pull request or commit.

## Status of every point raised

| # | Point (short) | Answer / decision | Recorded in | Status |
|---|---|---|---|---|
| M01 | Finish W7 3a PR A, then W7 3b, W29, BYOK draft | Done: #521, #522 merged and deployed; W29 and BYOK plans drafted | git log; handoff 2026-09-29 | W7 DONE; W29 #523 and BYOK #525 are DRAFTS |
| M02 | Which decisions were waiting on the owner | The session's numbered list: the lockout after a signed-in session expires, the flaky screenshot test, the values of ADR-0137 and ADR-0138, W29, and BYOK | CHG-026 c | ANSWERED |
| M03.1, M04, M05.1 | Colleague sign-in vs the 2-a-day limit | Network limit for anonymous use only; never blocks sign-in; signed-in users limited per account | NEXT-SESSION-PROMPT decisions | DONE — ADR-0139 (W34) |
| M03.2 | The flaky trust-score screenshots | Allow just above the largest difference seen (589 px), those screenshots only | CHG-026 k | CHG-027 e (2026-10-04): 700 px, those screenshots only (W41); replaced by CHG-031 (2026-10-06): the cause was found (Google Fonts sometimes serves a different version of a font file), the screenshot specs use a saved copy of Google's font stylesheet, the allowance stays 120 px, with an exact-text check of the card (CHG-030, ADR-0149), in W41's pull request |
| M03.3 | ADR-0137's four values and ADR-0138's two | Approved: events 10 / 30 days, sign-in starts 5 then 1 a minute, idle 120 minutes, warning 5 | CHG-026 c; ADR-0137, ADR-0138, docs/48 updated | DONE (recorded 2026-09-30) |
| M03.4, M04, M05.2 | robots.txt: fetch pages when possible | Respect robots.txt; if disallowed, the judge uses the search excerpt | same | DECIDED; CHG-028 (2026-10-05): keep the search excerpts first (W52, ADR-0146); judge use is W29 |
| M03.5 | BYOK security research first | Parked until W29 and the limits work; key in server memory only, not in any logs or web sessions, or anywhere a user or an attacker can inspect it, and other security threats ruled out | same | RESEARCHED 2026-10-17 (`docs/analysis/2026-10-17-w28-key-storage-research.md`); the owner then chose a key stored encrypted per account, not memory only (CHG-075 to CHG-080, ADR-0180); W28 is built after the rows CHG-061 names |
| M03.6, M04 | Sign out everywhere during a run | Ask first; Yes stops the run and signs out; No keeps only the running session | same | DECIDED, not built |
| M05.3–4, M21 | Google sign-in | Open to any Google account ("Testing" does not restrict basic scopes) | NEXT-SESSION-PROMPT | DECIDED 2026-09-30; record in docs/19 and fix the runbook sentence |
| M04, M21 | #511 retest | Steps 1–3 confirmed; sign-out after a reload still to check | NEXT-SESSION-PROMPT | OWNER: 1-minute check |
| M07.1 | Start fresh wipes the session list | Bug; a blocking test pins the wrong behaviour | inv-results.md | DONE — W33 slice A (ADR-0140, AC-055): only Clear empties the list |
| M07.2 | Old follow-up stays in the box | Bug; box opens empty with "Following up on: …" | inv-results.md | BUILT — W33 slice A (ADR-0140) opens the box empty; W37's pull request (ADR-0143) adds "Following up on: …" and sends the context; DONE once it is merged and running in production |
| M07.3–4, M08.6 | Wrong cap in the error; limits unclear | Bug; message names the limit hit and today's allowance | inv-results.md | DONE — W33 slice C (ADR-0141, AC-054): the card names the limit that fired; estimates show the allowance left in the last 24 hours |
| M07.5, M08, M10, M11 | Why testing missed these; the process | Engineering review + prevention plan | ENGINEERING-REVIEW-2026-09-29.md | PLAN PROPOSED |
| M07.6 | No way home from a result | Bug; logo link + back | inv-results.md | DONE — W33 slice A (ADR-0140, AC-055) |
| M07.7, M08.8 | Starter questions | Six audience groups × four full questions, wider high-stakes list | NEXT-SESSION-PROMPT | DECIDED, not built |
| M07.8, M08.7, M09 | History clickable, full results, continue chat | Store full result; 20 conversations / 30 days; open read-only; "Continue this conversation" | NEXT-SESSION-PROMPT | PARTLY DONE — the History list refreshes without a reload (W33 slice D, ADR-0142); opening a row, full results, the 20 / 30-day keep and Continue are W36 |
| M07.9 | Empty session panel | Bug; proper empty state | inv-results.md | DONE — W33 slice A (ADR-0140, AC-055) |
| M08.5 | Follow-up context to the models | Send previous question + final answer to all four models | NEXT-SESSION-PROMPT | BUILT in W37's pull request (ADR-0143, AC-057); DONE once it is merged and running in production |
| M09, M10 | Simulated runs deduct like live | Yes; the banner already says simulated | NEXT-SESSION-PROMPT | DECIDED, not built |
| M13 | Use Codex through its Claude Code skill | Used for contests | the session's notes | DONE |
| M14 | Autonomous orchestrator mandate; fans of subagents | Charter + separated roles | NEXT-SESSION-PROMPT | PROPOSED; confirm in plan mode |
| M14, M18.6 | Statement-only skills list | First pass: 104 of 107 unregistered skills are prose only | skills-tools-research/skills-firstpass.csv | FIRST PASS; full audit in step 5 |
| M15 | Slim AGENTS.md as a separate fresh task; first or later? | Planned at step 5 | NEXT-SESSION-PROMPT order | ANSWERED — later, after W37 and the anonymous-spend change (CHG-027 f) |
| M15 | Hooks and CI so rules are enforced, not guidance | Enforcement layers table | approach-research/synthesis.md | PROPOSED |
| M16, M17 | Deep research: approach; skills and tools | Done, contested by Codex and a sceptic | approach-research/, skills-tools-research/ | DONE (PROPOSED conclusions) |
| M18, M19 | Left-out items, DORA, Pact, BMAD, Spec Kit, Kiro, TOON | Answered in chat | this log | ANSWERED |
| M19 | Separate prompt for a new product | Written; it concerns another repository, so it is kept in the owner's private notes | the owner's private notes | DONE; runs after Quorum steps 0–2 |
| M19, M20 | A separate GitHub identity for agents | Set up and verified, with fewer rights than the owner's account; its details are kept privately | NEXT-SESSION-PROMPT | OWNER PART DONE; container is step 0 |
| M20 | Tracker shared by Quorum and the new-product starter | Rows in docs/65 (state derived from files) | NEXT-SESSION-PROMPT | PROPOSED |
| M18.5, M22 | Reviewer-must-execute rule; final feature testing on the real system, not mocks; were they followed? | See the section below | this log | ANSWERED; fixes in steps 2 and 5 |
| M23 | #511 retest | PASS (owner, 2026-09-30) | this log | DONE — #511 fully confirmed live |
| M23 | Sign-out after 2 sign-ins shows "This network has reached its session limit" | Cause (read from code, reproduce as a failing test first): sign-in does not count against the per-network cap (`auth.issue_signed_in_session`), but sign-out clears the cookie (google_signin.py:721-736), so the next page load mints a NEW anonymous session, which counts (SESSION_MINT_CAP_PER_IP = 2, auth.py:84). Same item as the 29 Sep decision (never block sign-in); decided, not built | this log | DONE — ADR-0139 (W34): a capped network gets a sign-in-only session |
| M23 | Whether the previous day's bugs were fixed yet | Not yet: nothing merged since 7c74b4f; fixes were planned for step 3 | this log | ANSWERED |
| M23 | After the landing question, the page focuses the question, not the models (bug 10) | Confirmed in code: goToComposer() focuses the question box (app.js:9491) while the note says "Taking you to review your N models". Fix: land on the models step with a one-line "Next: check your models, then See the estimate" | this log | DONE — W33 slice A (ADR-0140): lands on the models with a hint and a step marker |
| M23 | Tutorials for new users? | Recommend contextual help at the moment of need, not a tutorial tour (NN/g, "Onboarding Tutorials vs. Contextual Help", Laubheimer, 2023: tutorials "interrupt users, don't necessarily improve task performance, and are quickly forgotten") | this log | DECIDED — build both contextual help and an optional tour (CHG-027 g, board row W48) |
| M24 | Hint must say: Estimate to see the cost first, or Run to start now | Agreed. Use the real button names: "Your four models are picked for you — change any if you like. Then press **See the estimate** to check the cost first, or **Run now** to start straight away." Also align the landing buttons ("Estimate", "Run the debate") with the composer's ("See the estimate", "Run now") | this log | REPLACED — the owner's own wording (CHG-027 d), built in W37's pull request (ADR-0143); DONE once it is merged and running in production |
| M24 | Is there an index of these files? Will a fresh session find them? | INDEX.md and a check that fails on an unlisted file | INDEX.md | DONE — the folder's files are in the repository since #527 as docs/analysis/2026-09-29/ (README.md is its map; the outside folder's INDEX.md and its check stayed outside) |
| M25 | Can a new agent find what is where across the repo's documents? | No, measured: 268 of 538 docs not reachable within three links of AGENTS.md; several homes per kind of information. Plan: one map (docs/README.md), one home per kind, a check, and a before/after findability test | NEXT-SESSION-PROMPT (Findability) | DONE — #527: docs/README.md, checked by scripts/check_docs_map.py in make validate |

## M22 — what the files said, measured 2026-09-30

- "Execute, don't read" IS a rule: AGENTS.md rule 1. Reviewers DID execute: the W7 review
  reports record pytest runs, mutations and Playwright probes of the changed feature. What
  no rule required was walking the user journeys AROUND the change (follow-up, Start fresh,
  History). So the rule was followed as written. Its scope was the diff, not the product.
- "Test with real providers, not mocks or clean fixtures" was written ONLY in
  `docs/DAY-ONE-PROMPT.md`, which no always-loaded file referred to. The always-loaded
  AGENTS.md said the opposite: render against the golden FIXTURE. And AGENTS.md rule 17f
  said $0, no paid calls. Three instructions conflicted; nobody resolved them, so agents
  followed the loaded, cheaper one.
- A word search of the owner's saved messages found the no-mocks request once, on
  2026-09-29 (M18 point 5). An instruction phrased differently could be missed.
