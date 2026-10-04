# Owner discussion log — session e25d3396 (2026-09-28 → 2026-09-30)

> Copied into the repository on 2026-09-30 from the outside evidence folder. File
> names cited below map as in this folder's `README.md`: `INDEX.md` → `README.md`,
> `inv-results.md` → `owner-bugs-root-causes.md`, `approach-research/synthesis.md`
> → `approach-synthesis.md`, `skills-tools-research/shortlist.md` →
> `skills-tools-shortlist.md`. The decisions are recorded as CHG-026.

Every owner message from this session, word for word (extracted mechanically from the session
transcript: `type: user` records, excluding tool results, agent reports and system notices).
The status table comes first; the verbatim messages follow it. When a later session acts on a row,
it updates the Status column and names the PR or commit.

## Status of every point raised

| # | Point (short) | Answer / decision | Recorded in | Status |
|---|---|---|---|---|
| M01 | Finish W7 3a PR A, then W7 3b, W29, BYOK draft | Done: #521, #522 merged and deployed; W29 and BYOK plans drafted | git log; handoff 2026-09-29 | W7 DONE; W29 #523 and BYOK #525 are DRAFTS |
| M03.1 | Colleague sign-in vs the 2-a-day limit | Network limit for anonymous use only; never blocks sign-in; signed-in users limited per account | NEXT-SESSION-PROMPT decisions | DONE — ADR-0139 (W34) |
| M03.2 | The flaky trust-score screenshots | Allow just above the largest difference seen (589 px), those screenshots only | CHG-026 k | CHG-027 e (2026-10-04): 700 px, those screenshots only (W41), not built |
| M03.3 | ADR-0137's four values and ADR-0138's two | *"approve all points in 3."* — events 10 / 30 days, sign-in starts 5 then 1 a minute, idle 120 minutes, warning 5 | CHG-026 c; ADR-0137, ADR-0138, docs/48 updated | DONE (recorded 2026-09-30) |
| M03.4, M04 | robots.txt: fetch pages when possible | Respect robots.txt; if disallowed, the judge uses the search excerpt | same | DECIDED, not built (W29) |
| M03.5 | BYOK security research first | Parked until W29 and the limits work; key in server memory only | same | PARKED |
| M03.6, M04 | Sign out everywhere during a run | Ask first; Yes stops the run and signs out; No keeps only the running session | same | DECIDED, not built |
| M05.3–4, M21 | Google sign-in | Open to any Google account ("Testing" does not restrict basic scopes) | NEXT-SESSION-PROMPT | DECIDED 2026-09-30; record in docs/19 and fix the runbook sentence |
| M04, M21 | #511 retest | Steps 1–3 confirmed; sign-out after a reload still to check | NEXT-SESSION-PROMPT | OWNER: 1-minute check |
| M07.1 | Start fresh wipes the session list | Bug; a blocking test pins the wrong behaviour | inv-results.md | DONE — W33 slice A (ADR-0140, AC-055): only Clear empties the list |
| M07.2 | Old follow-up stays in the box | Bug; box opens empty with "Following up on: …" | inv-results.md | BUILT — W33 slice A (ADR-0140) opens the box empty; W37's pull request (ADR-0143) adds "Following up on: …" and sends the context; DONE once it is merged and running in production |
| M07.3–4 | Wrong cap in the error; limits unclear | Bug; message names the limit hit and today's allowance | inv-results.md | DONE — W33 slice C (ADR-0141, AC-054): the card names the limit that fired; estimates show the allowance left in the last 24 hours |
| M07.5, M08, M10, M11 | Why testing missed these; the process | Engineering review + prevention plan | ENGINEERING-REVIEW-2026-09-29.md | PLAN PROPOSED |
| M07.6 | No way home from a result | Bug; logo link + back | inv-results.md | DONE — W33 slice A (ADR-0140, AC-055) |
| M07.7, M08.8 | Starter questions | Six audience groups × four full questions, wider high-stakes list | NEXT-SESSION-PROMPT | DECIDED, not built |
| M07.8, M08.7, M09 | History clickable, full results, continue chat | Store full result; 20 conversations / 30 days; open read-only; "Continue this conversation" | NEXT-SESSION-PROMPT | PARTLY DONE — the History list refreshes without a reload (W33 slice D, ADR-0142); opening a row, full results, the 20 / 30-day keep and Continue are W36 |
| M07.9 | Empty session panel | Bug; proper empty state | inv-results.md | DONE — W33 slice A (ADR-0140, AC-055) |
| M08.5 | Follow-up context to the models | Send previous question + final answer to all four models | NEXT-SESSION-PROMPT | BUILT in W37's pull request (ADR-0143, AC-057); DONE once it is merged and running in production |
| M09, M10 | Simulated runs deduct like live | Yes; the banner already says simulated | NEXT-SESSION-PROMPT | DECIDED, not built |
| M13 | Use Codex via the Claude skill | Used for contests | memory: use-codex-via-the-claude-skill | DONE |
| M14 | Autonomous orchestrator mandate; fans of subagents | Charter + separated roles | NEXT-SESSION-PROMPT | PROPOSED; confirm in plan mode |
| M14, M18.6 | Statement-only skills list | First pass: 104 of 107 unregistered skills are prose only | skills-tools-research/skills-firstpass.csv | FIRST PASS; full audit in step 5 |
| M15 | Slim AGENTS.md as a separate fresh task; first or later? | Planned at step 5 | NEXT-SESSION-PROMPT order | ANSWERED — later, after W37 and the anonymous-spend change (CHG-027 f) |
| M15 | Hooks and CI so rules are enforced, not guidance | Enforcement layers table | approach-research/synthesis.md | PROPOSED |
| M16, M17 | Deep research: approach; skills and tools | Done, contested by Codex and a sceptic | approach-research/, skills-tools-research/ | DONE (PROPOSED conclusions) |
| M18, M19 | Left-out items, DORA, Pact, BMAD, Spec Kit, Kiro, TOON | Answered in chat | this log | ANSWERED |
| M19 | Separate prompt for a new product | Written | NEW-PRODUCT-STARTER-PROMPT.md | DONE; runs after Quorum steps 0–2 |
| M19, M20 | Agent GitHub identity rohitagrawal4u | Set up and verified: push yes, admin no, `repo` scope only | NEXT-SESSION-PROMPT | OWNER PART DONE; container is step 0 |
| M20 | Tracker shared by Quorum and the starter | Rows in docs/65 (state derived from files) | NEXT-SESSION-PROMPT | PROPOSED |
| M22 | Reviewer-must-execute rule; no-mocks rule; were they followed? | See the section below | this log | ANSWERED; fixes in steps 2 and 5 |
| M23 | #511 retest | PASS (owner, 2026-09-30) | this log | DONE — #511 fully confirmed live |
| M23 | Sign-out after 2 sign-ins shows "This network has reached its session limit" | Cause (read from code, reproduce as a failing test first): sign-in does not count against the per-network cap (`auth.issue_signed_in_session`), but sign-out clears the cookie (google_signin.py:721-736), so the next page load mints a NEW anonymous session, which counts (SESSION_MINT_CAP_PER_IP = 2, auth.py:84). Same item as the 29 Sep decision (never block sign-in); decided, not built | this log | DONE — ADR-0139 (W34): a capped network gets a sign-in-only session |
| M23 | Nothing from yesterday's list is fixed | Correct: nothing merged since 7c74b4f; fixes were planned for step 3 | this log | ANSWERED |
| M23 | After the landing question, the page focuses the question, not the models (bug 10) | Confirmed in code: goToComposer() focuses the question box (app.js:9491) while the note says "Taking you to review your N models". Fix: land on the models step with a one-line "Next: check your models, then See the estimate" | this log | DONE — W33 slice A (ADR-0140): lands on the models with a hint and a step marker |
| M23 | Tutorials for new users? | Recommend contextual help at the moment of need, not a tutorial tour (NN/g, "Onboarding Tutorials vs. Contextual Help", Laubheimer, 2023: tutorials "interrupt users, don't necessarily improve task performance, and are quickly forgotten") | this log | DECIDED — build both contextual help and an optional tour (CHG-027 g, board row W48) |
| M24 | Hint must say: Estimate to see the cost first, or Run to start now | Agreed. Use the real button names: "Your four models are picked for you — change any if you like. Then press **See the estimate** to check the cost first, or **Run now** to start straight away." Also align the landing buttons ("Estimate", "Run the debate") with the composer's ("See the estimate", "Run now") | this log | REPLACED — the owner's own wording (CHG-027 d), built in W37's pull request (ADR-0143); DONE once it is merged and running in production |
| M24 | Is there an index of these files? Will a fresh session find them? | INDEX.md + check_index.py (fails on an unlisted file; proven) + auto-loaded memory pointer `evidence-folder-catalog.md` | INDEX.md; memory | DONE — the folder's files are in the repository since #527 as docs/analysis/2026-09-29/ (README.md is its map; the outside folder's INDEX.md and check_index.py stayed outside) |
| M25 | Can a new agent find what is where across the repo's documents? | No, measured: 268 of 538 docs not reachable within three links of AGENTS.md; several homes per kind of information. Plan: one map (docs/README.md), one home per kind, a check, and a before/after findability test | NEXT-SESSION-PROMPT (Findability) | DONE — #527: docs/README.md, checked by scripts/check_docs_map.py in make validate |

## M22 — what the files say, measured 2026-09-30
- "Execute, don't read" IS a rule: AGENTS.md rule 1 (line 14) and line 536. Reviewers DID execute:
  the W7 review reports record pytest runs, mutations and Playwright probes of the changed feature.
  What no rule required was walking the user journeys AROUND the change (follow-up, Start fresh,
  History). So the rule was followed as written. Its scope was the diff, not the product.
- "Test with real providers, not mocks or clean fixtures" is written ONLY in `docs/DAY-ONE-PROMPT.md:135`.
  No always-loaded file refers to that file (`grep DAY-ONE AGENTS.md CLAUDE.md ~/.claude/CLAUDE.md` → nothing).
  The always-loaded AGENTS.md:587–590 says the opposite: render against the golden FIXTURE. And AGENTS.md
  17f plus the global CLAUDE.md say $0 / no paid calls. Three instructions conflict; nobody resolved them,
  so agents followed the loaded, cheaper one.
- A search of owner messages in every saved session transcript for mock / stub / canned / fake /
  "real system" found the no-mocks request once, on 2026-09-29 (M18.5). A prompt pasted into the
  2026-09-01 session (possibly session-written, not the owner's words) warned that orchestration
  "looks right against a mock and is wrong against real multi-model timing". The search matches words,
  so an instruction phrased differently could be missed.

## The messages, verbatim

### M01 — 2026-09-28 15:28 UTC

<pasted_content id="7a61">
Read and follow, in this order, before doing anything:
1. AGENTS.md
2. docs/session-handoff.md
3. docs/analysis/2026-09-28-session-handoff.md
4. CONTINUE-2026-09-25-ULTRACODE-PROMPT.md — its hard stops (§2), merge
   authority (§3) and end-of-session steps (§8) still apply; its queue (§5)
   is now at the point the 2026-09-28 handoff describes.

Then:
A. Run `df -h /System/Volumes/Data` first. If less than ~5 GB is free, stop
   and tell me.
B. Finish W7 part 3 pull request A on origin/w7/session-safety at 14dde83
   (worktree quorum-ai-wt-w7c): run its mutation proof in a git-archive copy,
   all gates and both e2e lanes, then ONE final review of the simplifying
   round I approved on 2026-09-28 at 12:14:14Z. Merge only if that review
   finds no reproduced blocker; otherwise park it and ask me. After merging,
   verify the deploy and clean up.
C. Then continue the queue: W7 part 3 pull request B (idle expiry), then
   W29, then the BYOK draft, per the handoff and §5.

ultracode.
</pasted_content id="7a61">

### M02 — 2026-09-29 09:30 UTC

What are the decisions pending on me? Can you please explain with an example and also give your recommendation? Please keep it concise and short.

### M03 — 2026-09-29 09:48 UTC

agree with 1 but my concern it that in this case will the new colleague once signs in then his account history will be checked if he has used 2 session this day and when Hiring manager signs back then he gets his 2nd session back to run questions?
2. agree with your recommendation on 2.
3. approve all points in 3.
4. we should try to fetch the pages if possible. by robots.txt I underdtand that you can making a check where robot check or parsing of pages is not allowed on websites/pages. Please correct me if wrong. Rest I agree with all points on W29.
5. BYOK parked until W29 and item 1 are done. agree with all other points just ensure that you Do thorough research and analysis of how other websites are securing this BYOK feature. We should ensure that we are not storing it in any logs, any web sessions, or anywhere the user or an attacker can web-inspect and see the keys, and that any other security threats are not there.
6. Please help me understand, with an example, what all points are carried over from earlier sessions. What is needed from me, and what is your recommendation? For the sign-out everywhere, if a run is already going on, we should first show the alert or the message to the user that a run is already in progress. If she approves and says yes, stop it, then we should go ahead and do it. Let us not assume anything on users' behalf.

### M04 — 2026-09-29 09:56 UTC

But now, since we already have a sign-in and sign-out feature and we are asking a user to sign in, in that case, this 2-per-limit should be applicable per account, right? When a user is not signed in and he is trying to access the application, in that case, the 2-a-day limit should be applicable. What do you suggest, or should we remove this per-network limit and just put it on the account level? Is that possible? 
On reports.ts, if that says "do not read or fetch," in that case, the model should also not be allowed, right? If a model has done that and the model is citing that page, then the judge should also go ahead and fetch it. 
Sign out everywhere during a run: on "No" only that session is not signed out where the run is going on.
Share the steps to test #511 and Google "Audience" settings so we close it.

### M05 — 2026-09-29 10:16 UTC

1. Agree with suggestion on both parts.
2. Agree on robots.txt
3. Publishing status is Testing. Screenshot attached [Image #2]
4. I signed in with a different account which was not there in the testing, and it was still able to sign in. Screenshots attached. [Image #3] [Image #4]

### M06 — 2026-09-29 10:20 UTC

some bugs noticed:

### M07 — 2026-09-29 10:31 UTC

1. When a user is signed in and he asks a question, then again does a follow-up question, and on the next screen, if he switches from the follow-up question to a fresh chat, the previous chat history is removed. Even on coming back to the follow-up question tab, the questions are not shown. This is a big bug, I think, and why was it not properly tested from your side? [Image #5]
2. In case I have a second follow-up question, the first follow-up question is still there on that screen, which is incorrect. It should be removed, and I should be given a fresh or a blank space to type a question, right? Otherwise, I'll have to first delete it and then type my new question. I have also identified multiple times earlier. I'm not sure why it is not getting fixed and properly tested as part of your testing.
3. How is this error making sense? I had identified and highlighted this issue to you earlier as well, but again, this issue is coming up. This means that you have not fixed it, or it has been bugged again. There is no proper testing, and this is happening here. A code change later is actually evading or unfixing the previously made fixes. The session history becomes zero again. Everything is lost. "This run's worst-case cost (up to $0.136) is over the $0.5 hard cap and no override exists in this release. Nothing ran and nothing was charged." [Image #6] 
4. The fresh session, again, when I start, I am able to run the queries, so it is a properly bugged-up scenario that is working. It is unclear which limit is applicable when and where. The error messages are not clear.
5. While creating these features of history, sign-in, sign-out, and sessions, have you tested these features? Have you done the proper testing, review, and then incorporated and made it happen, merged it or not? What was the flow that you followed? I see a complete discrepancy in the engineering practices that we have laid out.
6. From a runs page, there is no option to go to the homepage. Even the Quorum logo on the page is not clickable. How would a user go to a homepage from this page, which I am attaching the screenshot of to you? [Image #7]
7. The default questions which are shown on the page for the user to select do not make sense. You should show the questions which are relatable to the user and to a wider audience. At present, the default 45 questions which are shown are, first of all, incomplete, and then mostly they don't make complete sense to the larger audience. You should try to divide this. Say something like "general public," "engineering public," "medical public," or something like that. What are the top topics that people are searching for and accessing in the AI models? Those should be the questions that should be shown here. You should do thorough research for that and then come up with those options.
8. The history is shown when the user signs out and then signs in. In that case, it was showing me five question histories, but those histories are not clickable. The user will not be able to view the history sessions. What is the purpose of showing this history? But this does not mean that the history should not be shown in the current session and the questions are wiped off for the scenarios that I have listed to you above. [Image #8]
9. There is nothing shown at the bottom after the text or the banner for this session. This is confusing. What would the user take away? What would he or she understand? He or she may feel that the information shown on the web page is incomplete. We should properly end that in case there are no sessions or questions asked. What is your thought and review on this?
Before you start working, give me the analysis and the way of action.

### M08 — 2026-09-29 12:12 UTC

1. The browser test suite cannot sign in at all: You should have called it out and let me know. Also, you should have tested the dummy account. You could have created a dummy account and tried to test the sign-in features.
2. Why the no-end-to-end lane can sign in, and it was merged anyway? Why was it not called out?
3. Why did the reviewer not look at the product as I use it? Isn't a user behavior needed to be tested? Isn't this a user behavior? Isn't this a functional requirement? Isn't this the functional user story that we are building upon? Then why had we not looked at it? Why was it not tested thoroughly? This clearly shows a testing gap. What do you have to say about it?
4. I did not get. What do you mean by "two blocking tests require two of the behaviors you call bugs"? Are you trying to say that these are not bugs and the features that we are trying to provide?
5. I remember correctly that the follow-up was designed to send the previous old question to the models again so that they can infer the context of what was asked by the user and they can again give the response. If we do not have context or a track of those questions being sent to models, then how would the models understand that this is a follow-up question? Is your recommendation here? 
6. I do not understand what you mean by practice runs and the daily limit. At the end of the day, the message that was shown to the user was incorrect, and it did not convey the exact error or the exact cap that has been hit.
7. On the history click, why are you suggesting just one hour's question answers? If a user logs in again, how would he be able to track the questions he or she would have asked earlier? If it's a bring your own key, the user has already spent the money. Why would the user like to again spend the money or pay more as well when a question has already been asked and the user has the answer? Why shouldn't we show those questions and answers to the users and the complete debate? Does it cost us anything, and what are the consequences of this cost?
8. I agree with you on the starter questions.

### M09 — 2026-09-29 12:17 UTC

In addition to what you have mentioned for points 1 to 3, I also would like to understand: how would you ensure that we do not face these kinds of issues again in the future? How do we ensure that proper testing and everything is there and is taken into account? Is there a flaw in the prompt that was given to you or the workflow that was initiated, or was there any other flaw that could have been corrected? If yes, then give me that, and also give me the source based on which you are saying it. So I can also verify from my end. 
In addition to clicking the history row opening it read-only, I would also like to add a feature where a user can ask trailing questions or would like to continue that chat. That visibility should be provided to the user. What do you suggest? 
He has sent context to all four models, no dollars should be pretended to be deducted because that helps the user understand what the live behavior is and how the application behaves when it is actually live. What do you say, what is your suggestion on point 7?

### M10 — 2026-09-29 12:25 UTC

How to ensure that, going forward, whenever we are building a feature, it is end-to-end tested and it also does the application's integration testing? Is there anything else that we should add in the rules or the prompt, or make it a practice that we do not miss these things going forward? Shouldn't these have been part of your planning itself? We have to ensure that we do functional, non-functional, and user-level security testing for all the features that we are building. Is there any other angle of testing that we are missing here? If yes, please let me know. We should add that as well. What are we covering in the PR review if the testing angle is not there? And if the testing angle is there, then what kind of PR review is being done? Clearly mentioned that we should be doing the fan of subagents PR review. What I mean is that we have already shown at the top itself, right, that this is a simulated run and no live run is being done. The user would already get that understanding, and then we can continue with the normal behavior. That is what I meant. Do you feel that it can be made better for the user experience? If yes, then what is the suggestion? Rest, I agree with all your suggestions.

### M11 — 2026-09-29 12:30 UTC

By functional, I don't just mean the UI-level testing. It means UI, app, backend API, and all sorts of testing, right? User behavior testing and all those tests . We should think from all the perspectives of testing from a software engineering perspective. As far as I remember, we have been using test-driven development, which should encourage and take care of these things. Why are we missing it? Is there any engineering gap that is still happening in this application, which could be fixed and should be fixed? Already have so many skills which are enclosed and included in this repo and have also been directed in the agents.md, cloud.md, or the other .md files as to which skills should be used for what, but still these things are happening. Do you suggest downloading any other skills from GitHub, from skills.sh, or from any public repo which has been used by a good number of users, has positive ratings, and is good, claimed online with users' data and everything? What do you mean by "they reviewed the code, not the product"? At the end of the day, the product is made from the code, right? This is the product that we had already decided we are building, and the code is done to build that product. Then why was it not peer reviewed? Based on all these discussions and all the recommendations that you have given so far, can you please give me a thorough plan that you would be executing to ensure that we do not face these issues in the future or any related issues like this?
I would like you to thoroughly analyze, from all angles and from an engineering perspective, the way we have built this product. Give me a thorough, researched analysis. You should be the expert. Get it reviewed thoroughly and question it, contest it from an angle where Codex would be testing it or other models would be testing it: how they would debunk your assumptions or your analysis. Do not assume anything. If there is anything that I have missed, please add that and give me your plan of action.
At the end, also give me a concise, short summary of:
- what we have identified
- how we are going to ensure that it is not going to cause issues in the future
- what gaps we are covering in the engineering practices that we would be following now
- how we can use this product as a roadmap for building new products
- what learnings
We already have a day one engineering prompt or something like that, but still, we are falling prey to being stuck in creating a good product after so much resilience and 67 months of work.

### M12 — 2026-09-29 12:32 UTC

[Request interrupted by user for tool use]

### M13 — 2026-09-29 12:32 UTC

Codex is available, and you can call the Codex in the Claude skill.

### M14 — 2026-09-29 14:34 UTC

We are working on multi-agent harness orchestration, where the main agent is the one who takes care of things on my behalf. You have to ensure that the sub-agents are doing it properly. I should not always be there for a session before you do a release. You have to take on the shoes of an owner and then work on it.
What is the purpose of using workflows or UltraCode? I am asking you to act as the self-autonomous orchestrator and take decisions on my behalf. You spawn a subagent for doing a task, and you monitor that subagent. Once that subagent finishes that task by properly doing:
- planning by a fan of subagents
- proper development by a fan of subagents
- proper testing by a fan of subagents
- proper review by a fan of subagents
Once everything is green, it should go ahead, right?
What is the difference between test-driven development and acceptance-driven development? If you are talking about that, what maturity are we showing in development? How would you ensure that, being autonomously working on my behalf, you are still able to catch these defects? What changes would you like to make? How would you say that we need to slim the agents.md? What changes do you suggest?
You have to think thoroughly and holistically from all the angles when we are dealing with or developing a feature. You have to think from all the angles, all the sub-agents, all the corner cases, all the minutest negative test cases, boundary valuations, and all those things you have to do. You have to thoroughly think about the feature before you plan and develop it. I do not want the dependency on me. I want the agent harness to be self-capable enough to take these decisions to see that everything is working fine. You have to ensure that you do thorough planning, like you do in the plan mode, based on the user's requirement. You do thorough planning for how the features should be developed, what the features should be, corner cases, and everything is covered, and test development is covered.

You also need to identify the 100+ skills that are just statements that don't do anything. They are written in-house and actually do not supervise anything. They are just in statements, not functions, personality checks, or working checks. They do not execute and check. You have to identify and isolate those skills and give me a list if you want to delete them as well.

All this needs a thorough review and analysis. Do you suggest continuing in the current context, or do you want to start from a fresh context? Also, do you want to continue in the plan mode, or do you want to start the fresh context in the plan mode?

### M15 — 2026-09-29 14:43 UTC

When agents date agents, they can share blind spots. I understand. That is why you are expected to spawn a Codex agent and an agent from a different model as well, right? That flexibility you already have. Yes, I agree with the four safeguards that you have mentioned. I am still not clear on the response that you have given for Ultra Code and Workflows. What are you trying to convey? I am already aware that it happens the way that you have said, but then, when testing and everything is there, why was it not able to work properly and still leave gaps from a user's perspective? How do we ensure that, going forward, we do not face these issues again? So, in short, we should use spec-driven development, test-driven development, and acceptance test-driven development as well, right? I think acceptance test-driven development is a part of test-driven development only. Correct me if I am wrong. Along with that, what all things do we need to add? You have mentioned exploratory and usability, and non-functional testing is missing. Though I have been constantly repeating about these aspects, again, those have not been defined. We have used a lot of places where security is pivotal, and I am doubtful about how those features would be developed? I think in the past also, you have said that we are mature at verifying code but immature at validating the product. This is not the first time that we are happening, and despite our earlier failures, we have not learned and implemented corrective measures in place, it seems. What is the exact development approach that we should take based on all the discussions and learnings that we have had so far, and what do you propose to account for in the future? We should take up the slimming of agents.md as a separate task from a fresh context. What do you suggest? Should we take it up first and then the other remaining tasks? Also, how do we ensure that we utilize the hooks, the pre-hooks, and the post-hooks properly in the CI so that we don't end up in these kinds of discussions and say that these were just the guidance, not the enforcements? Suggest using the existing handoff that you have written, or would you like to start by answering these questions, come to a conclusion, and then write the handoff at the end? What do you suggest as an expert?

### M16 — 2026-09-29 14:48 UTC

We are saying that spec-driven development is something that should be taken into account as the priority, and it is the best development approach (which includes test-driven development and acceptance test-driven development as well). Is there any other development approach that should be taken into account? Please do thorough research and then suggest the things. i want you do do a thorough analysis and deep-reserach and then suggest the development approach, the enforcement table, the order. Let me know if your new answer contradicts the earlier one, is a subset of the earlier one, or is equal to what you have identified.

### M17 — 2026-09-29 14:55 UTC

I think there should also be dedicated deep research to identify the most useful and helpful skills, resources, or AI resources or AI agents which are available online from different sources like GitHub, skills.search, or any other platform. These can be helpful in accomplishing or completing these tasks and help you, as an agent, to actively do things in the proper direction and shape.

### M18 — 2026-09-29 15:58 UTC

1. For the points that you have mentioned as left out as overkill for a one-order product, how would these points be? Or rather than saying that, I would say: if we do not include these points, will it not show my flaws in the engineering capabilities used to build this product? Why is the DORA matrix, for example, not useful here? What do you mean by pact contract testing? What are the three usability reviewers on every change? What do you mean by Cucumber step files? Are you referring to the BMAD approach of building AI applications? What and why are we not installing Spec Kit and Kiro? Are these freely downloadable and freely available, or do we need to pay for these things?
2. How would this analysis be useful while developing or creating a brand new product, or while working on an existing product, or a repository, a project, or an application that we have?
3. Have you also evaluated: TOON (Token-Oriented Object Notation)? Whether we are using it presently or not, and whether it is useful or not with the present capabilities or the things that we are using to build applications ?
4. Not able to understand what you mean by "give the agents their own GitHub identity." What do we need to do here? I have only one system on which I'm working. How do you suggest running them under a separate computer or container? How can we enforce it? 
5. Have you covered that the final end-to-end testing, when we say that the feature is ready, is based on the actual testing being done and not on a mocked system (like a mocked backend, a mocked frontend, or mocked APIs)? Are these checks also configured and covered? If they are knowingly left behind, then what is the reasoning for that? If I am missing anything, then please correct me.
6. For the skills and tools, have you analyzed which tools and skills are internally written and which skills are just statements? They do not check anything. Even a simple text like this thing can satisfy that skill without actually checking whether that is a behavior or not and whether that is something that the result produces or not.

### M19 — 2026-09-29 16:29 UTC

Are we using the BMAD approach in the planning phase? Not then why? Please help me understand. Can the TOONs be used for situations or features where we have a message history where the previous reply is passed to the AI models for the new questions? Why was TOON not part of the earlier discovery done by the agent? Can you include in the prompt what all things are to be done for a new project? Should I run all those things from a fresh context or in the continued context? Would you like to give a separate prompt for the new product setup and all the learnings that we have got? What all files and what all are to be done with skills mapping and everything? We also have a day 1 prompt, a day 1 engineering prompt, and learnings agents.md. What all is to be done? Included in that repo, do you want to do that from a fresh context just for the new product, and keep the existing Codem as a separate prompt? All the things that we are discussing for Codem would be a second prompt. What do you suggest? For the second repo, you can use my github account: rohitagrawal4u . Let me know what you suggest. In all the discussions that we have had, give me a final summary at the end for the new project and for the existing project: whatever we have been discussing and what your approach is. What do you suggest I do?

### M20 — 2026-09-30 04:42 UTC

Give me the steps to perform:
1. You are saying, "Invite Rohit Agrawal for you to the Quora repo."
2. You said that BMAD is not needed, but the segregation of responsibility is something that we have missed here, right? The testing was not done properly or had missing scopes. Plus, you also identified the Vercel skill, which was used as a user flow and not what is done by the developer. What is your analysis on that?
3.For this point now, what do you suggest? What is the way forward for the new repo? Would you keep a tracker that Codem also tracks, so that once everything is fine, we do the new sessions, things, and analysis that you have done?

### M21 — 2026-09-30 04:59 UTC

I think we have already discussed these items of Google Signin and #511 retest, isn't it ? Reiterating: Google sign-in open to anyone. What exactly do you again need in 511? Please confirm along with the steps.

### M22 — 2026-09-30 05:02 UTC

In separation of duties, you have mentioned that you have read the code, not the running product. This is a hard-coded rule that was instructed and given in agents.md and the relevant MD files: there should be an agent in the PR review that will specifically execute the code and verify the data, not just read the code. That was a prerequisite that was defined, but then why was it not followed? Please correct me if wrong.
It was also instructed that, in final feature testing, we should exactly do the testing with the exact system products. Do not fake or use stubs or use canned products. Then why was it being used? Do we ensure that the instructions are followed diligently and not just passed by the way? I hope you have been keeping track of all the discussions, taking notes, and making it available at some point in some MD files so that we can work upon it. This is again not getting lost, like your previous reviews found that the files were getting lost in the bugs and all those things, chats and all.

### M23 — 2026-09-30 05:06 UTC

One more bug that I have identified is that when the user is on the How It Works main page, he asks a question and is brought to the next page. Again, the focus area is the questions, but the user is unaware of what action he has to take: choose the models and all. The focus area or the display should be that the models should be visible, and the user should be asked to or guided to choose the models. Do you suggest tutorials to be done when there is a new user who is accessing the website so that he is aware of what all features are there? What is your recommendation? 
Pass. I did 2 logins and then at logout got the "This network has reached its session limit" message. Means that the previous 9 bugs, or the bugs that were identified yesterday, are still not fixed, right?

### M24 — 2026-09-30 05:10 UTC

In the fix, when you say "Change any" or "Press See the estimate," there, we should also make it more clear: "In case you want to see the estimate, then click on Estimate, or if you want to directly run, then click on Run." What do you suggest? Rest, I agree. I also see that you are storing some of the discussions and analyses in different MD files, right? Do we have an index which keeps track? When you are run in a fresh context, will you be able to go to the exact file whenever a need arises, or will these discussions get lost in multiple MD files? Will the agents.md or you, as a worker, know the catalog of where to fetch what information?

### M25 — 2026-09-30 05:12 UTC

Over these MD files, like owner decisions.md, or other log files, I'm just wanting to understand: is the folder hierarchy, the decision hierarchy, the documents hierarchy, the way you are acting on these documents? Whenever a new agent works, will that be able to get what all different files there are, what the use cases are, what values they derive, where to access what information, and all those things? Many times, we have the information, but accessibility becomes an issue where the new model is not able to understand what to access where. I'm trying to resolve these pivotal and basic issues in the repositories.

