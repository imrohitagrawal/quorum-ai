

=================================================

The navigation-and-history lens reproduces all three problems in a real signed-in browser, on a copy of main at 7c74b4f. None of them is a regression. The dead end on the result page dates from 2026-07-11. The two History problems shipped with the History feature on 2026-09-27. No test has ever driven a signed-in page in a browser.

Probe command, run from `.../scratchpad/inv-nav`: `ROOT=$PWD PORT=18431 PYTHONDONTWRITEBYTECODE=1 .../.venv/bin/python probe/nav_history.py` (a second probe, `probe/reopen.py`, uses the same command).

## Item 6: no way back to the home page from a result

**(a) Reproduced.** The probe signs in, asks a question, approves the estimate and reaches the result view. Verbatim output:
```
2. result view: topbar display = none
   nav: {"brand_tag": "SPAN", "brand_in_link": false, "brand_cursor": "auto", "history_visible": false, "signout_visible": false}
3. after clicking result brand, view: result
7. browser Back from result view -> url: about:blank
```
- The only visible controls in the header are Copy, Export and the theme toggle.
- The only way off the page is "Review & run →" at the bottom, and it pre-fills the old question.
- History, Sign out and "How it works" all live in the top bar, so they are hidden too.
- Screenshot: `probe/result-top.png`.

**(b) Root cause.**
- `app.css:830-834` hides the top bar on the landing, result, live-run and transcript views.
- The result view's own brand is a plain `<span class="result-brand">` with no link and no click handler (`workspace.html:528-531`). A grep of `app.js` for `result-brand` finds nothing.
- `app.js` has no `pushState` or `popstate` (grep finds nothing), so the browser Back button leaves the app instead of returning to the question box.
- The only exit is the `result-next-run` handler (`app.js:9666-9685`), which calls `goToComposer()`.

**(c) Since when.**
- The hidden top bar came from `17ed2b5` (PR #13, 2026-07-11). The span brand came from `cea5886` (PR #7, 2026-07-11).
- The same root cause was reported before, as a missing dark-mode toggle. `docs/archive/2026-08/UI-BUG-TRIAGE-2026-07-23-ANALYSIS.md:26`, bug #6, says the top bar is hidden on landing/result/live-run/transcript. That fix only added a theme toggle to each view and left navigation out.
- No issue or commit mentions logo, home page or "clickable" for this. The `gh issue list` searches returned `[]`.

**(d) Tests today.**
- `e2e/tests/invariants/theme-toggle.spec.ts` treats the hidden top bar as intended and only checks for a theme control.
- `parity-behavior.spec.ts:719` asserts the top bar is hidden (on landing).
- No spec asserts that a view has a way back to the question box.

**(e) Smallest fix and test.**
- Fix: make the result, live-run and transcript brand a real control that returns to an empty question box. Possibly also add a "New question" button to the result header.
- Test: an invariant spec that walks each view where the top bar is hidden and asserts that clicking the visible brand control sets `#main-content[data-active-view="composer"]`.

## Item 8a: "No questions yet" right after asking

**(a) Reproduced.** Verbatim output, same page with no reload:
```
1. load view: composer | history: "...No questions yet..."
4. composer after run, no reload: history: "...No questions yet..." items: []
   history rows in DB now: 1
5. after reload: ... items: [{"tag":"LI","anchors":0,"q":"Should a small team use Postgres or SQLite..."}]
```
Any reload shows the question. Signing out and back in only "fixes" it because both reload the page.

**(b) Root cause.**
- The History panel is built on the server once, when the page loads (`main.py:873-914`, called from `main.py:835`).
- In the browser, `app.js:10002-10014` only closes the panel on Escape or an outside click. Nothing refreshes it after a run.
- ADR-0135 chose this on purpose: decision 4 ("There is no separate endpoint", `0135-signed-in-history.md:61`) and a rejected alternative ("A JSON history endpoint: nothing needs it yet", `:76`).

**(c) Since when.** `5e28de9` (PR #518, 2026-09-27), the first History release. It was not reported before.

**(d) Why tests missed it.**
- `tests/integration/test_account_history_flow.py` (20 tests) uses a test client (FastAPI `TestClient`, no browser) and calls `GET /ui` fresh after each run. It never checks a page that was already open.
- There is no signed-in browser test at all. `e2e.yml` and `playwright.config.ts` contain no `GOOGLE` settings (0 matches), so sign-in is off on the end-to-end test server.
- The Google stub is used only by 3 integration test files. No Python test drives a browser (grep for `sync_playwright` in `tests` finds nothing).

**(e) Smallest fix and test.**
- Fix: when a signed-in run finishes, refresh the panel from the server. That means a small read endpoint, which reverses ADR-0135's rejected alternative and needs an ADR amendment.
  - My memory notes say the decorated-function cap is full, so the endpoint would use `add_api_route`. I did not re-check that in this session.
- Test: a signed-in real-browser test. It needs new setup first: either the end-to-end server started with the Google stub, or an in-process test like the harness. The test asks a question, returns to the question box, opens History without reloading, and expects the question in `#account-history-list` and no `#account-history-empty`.

## Item 8b: history rows cannot be clicked

**(a) Reproduced.** Verbatim output after clicking a row:
```
6. click history row: view composer | composer value before/after: '' '' | history open: True
```
Nothing happens. The rows are an `<li>` with spans (`main.py:885-896`), no link or button, and no handler exists.

**(b) What a row holds, and so what a click could honestly do.**
- A row holds: `query_run_id`, question, status, mode, model count, verdict, estimated cost and completion time (`session_store.py:114-129`, schema `:360-369`). It holds no answer, which CHG-023 and ADR-0135 decided.
- The owner's stated purpose (CHG-012 D7, `docs/19-change-control-log.md:16`): "the purpose of sig-in is to preserve the history of the searches from a account".
- The run id is not in the page today. Probe output: `in /ui html: False`.
- The full result can still be read for a while. `GET /v1/query-runs/{id}` is limited to the owning account (`query_runs.py:1049-1066`), and runs are kept in memory for 1 hour after they finish (`QUERY_RUN_TERMINAL_TTL`, `query_run_orchestration.py:137`). Probe `probe/reopen.py` output:
  ```
  GET run same session: 200
  sign-out: 200
  GET run signed out (new anon session): 401
  sign-in again: 303
  GET run after sign-in again: 200 | has synthesis: True
  ```
- So an honest click could: reopen the full result while the server still holds it (up to 1 hour, same server process, lost on restart). Otherwise it puts the question back in the question box with a line saying the answer was not kept and a new run gets a new estimate.
- UNVERIFIED: whether production runs more than one server machine, which would make reopening fail on some requests. The check is to read `fly.toml` and `fly status`.
- Keeping answers longer than that is outside CHG-023 and needs the owner's decision.

**(c) Since when.** PR #518 (2026-09-27). ADR-0135 never discusses clicking a row.

**(d) Tests.** `tests/unit/test_history_markup.py:48` (`test_the_history_markup_is_exact`) pins the exact span-only markup, so it has to change together with any fix. No test checks that a row does anything.

**(e) Test.** A signed-in real-browser test: click a history row and expect the result view with that run. Then expire the run (or use one older than 1 hour) and expect the question box pre-filled with the question and the "not kept" line.

## Related, belongs to other lenses
- On the result view, "Start fresh" calls `clearSessionTrail()` (`app.js:9661-9664`). That clears the in-page "This session" trail, which fits the owner's item 1.
- The page has two separate histories: the top bar "History" (server-built, stale) and the in-page "This session" trail (live, cleared by Start fresh). The trail is the only one visible on the result view.

Probe files and screenshots are in `/private/tmp/claude-501/-Users-rohitagrawal-Projects-quorum-ai/e25d3396-0a5c-412b-aabf-e12be1095139/scratchpad/inv-nav/probe/`: `nav_history.py`, `reopen.py`, `result-top.png`, `composer-history-stale.png`, `history-after-reload.png`. Nothing was written under `/Users/rohitagrawal/Projects`.


=================================================

All three reports reproduce in a real browser, both signed in and anonymous. None of them is caused by the sign-in work. Report 1 is the trail doing what it was designed to do, and one blocking test requires that behaviour. Report 2 is a field that no code ever clears. Report 9 is an empty state that was never designed.

Tree is build 7c74b4f. All code references are `src/product_app/static/app.js` unless another file is named.

**How the probes were run** (probe files and screenshots are in `/private/tmp/claude-501/-Users-rohitagrawal-Projects-quorum-ai/e25d3396-0a5c-412b-aabf-e12be1095139/scratchpad/inv-trail/probe/`):

```
cd …/scratchpad/inv-trail && ROOT=$PWD PORT=18411 PYTHONDONTWRITEBYTECODE=1 /Users/rohitagrawal/Projects/quorum-ai/.venv/bin/python probe/p1_trail.py      # signed in
SIGNED=0 … PORT=18412 … probe/p1_trail.py                                                                                                          # anonymous
```

Output of `p1_trail.py`, trimmed. The anonymous run gave identical results apart from the email.

```
[1 result of Q1]              trail: ['What are the key metrics…']                     nextInput: ''
[2 composer after follow-up]  composer: 'How do I compute net revenue retention?'
[3 result of follow-up 1]     trail: ['How do I compute net revenue retention?', 'What are the key metrics…']  nextInput: 'How do I compute net revenue retention?'
[4 after clicking Start fresh (nothing run)]     trail: []  listHidden: True
[5 after clicking back to Follow up on this]     trail: []
[6 result after another run]  trail: ['Second follow-up question?']   nextInput: 'Second follow-up question?'
[7 after page reload]         trail: []
sessionStorage keys: []  localStorage keys: ['quorum.workspaceSeen']
```

## Report 1: "Start fresh" wipes the session history

- **(a) Reproduced.** Steps 3 to 5 above. Clicking "Start fresh" deletes the whole trail immediately, before anything is run. Clicking "Follow up on this" again does not bring it back.
- **(b) Root cause.** The "Start fresh" button does two things. It sets the mode, and it also calls `clearSessionTrail()` at `app.js:9661-9664`, which runs `state.sessionTrail = []` at `:6324-6327`.
  - The trail lives only in memory (`:395-402`, `:6300`). Nothing is kept anywhere else, so nothing can restore it.
  - The trail is also lost on every full page load. That includes a reload (step 7), sign-in (`:9888` goes to Google), sign-out (`:9901` reloads `/ui`), the "Refresh session" error action (`:476-477`) and `retrySession` (`:8939`).
- **(c) Since when.** Introduced deliberately by 431071d, "PR8: conversation trail UI", 2026-07-25. It was re-confirmed as intended by 0d23c0e, fixing issue #126, 2026-08-02. The comments at `:8553-8556` and `workspace.html:955` state it: "cleared by 'Start fresh'".
  - No ADR records this choice (`grep -rli "start fresh" docs/adr` found nothing).
  - It was not "fixed" earlier and broken again. It has worked this way since it shipped.
- **(d) Tests.** A blocking test locks the behaviour in: `e2e/tests/invariants/session-trail.spec.ts:132`, "'Start fresh' clears the session trail". It runs in the blocking lane (`e2e.yml:192`). `:141` asserts that after "Start fresh" plus a new run the trail holds exactly one entry.
  - No test switches the mode back and checks that entries are still there.
  - All the trail tests are anonymous and use mocked network routes. Because the result is the same signed in, sign-in is not a factor.
- **(e) Smallest fix.** Remove `clearSessionTrail()` from the "Start fresh" handler (`:9663`). The explicit "Clear" button stays the only way to wipe the trail. Change the two tests at `:132` and `:141` to assert the opposite, and update the comments at `:8553`, `:10207` and `workspace.html:955`.
  - New real-browser test: run 2 questions, click "Start fresh", then "Follow up on this". Assert 2 entries are still there. Then run a third question and assert 3 entries.
  - That test fails today; probe step 5 shows 0 entries.
- **Optional second fix:** keep the trail across reload and sign-in. Store `state.sessionTrail` in `sessionStorage` and clear it on sign-out.
  - Clicking a stored entry refetches the run. My probes show that works in some cases and not others:
    - Signed in, after a reload: HTTP 200.
    - Signed in, after sign-out and sign-in again: 200.
    - A run made while anonymous, after signing in: 404 `QUERY_RUN_NOT_FOUND` "not found for this account" (`probe/p3_owner.py`, `probe/p4_resign.py`).
  - So restoring entries would need a graceful "no longer available" state.

## Report 2: the first follow-up question stays in the box

- **(a) Reproduced.** Step 3: after follow-up 1 finishes, `#result-next-input` still holds "How do I compute net revenue retention?". Step 6 shows the same.
- **(b) Root cause.** When a run finishes, the handler clears only the main question box (`queryTextarea.value = ""` at `:8717-8720`).
  - Nothing ever clears the result view's "Ask your next question" box (`#result-next-input`).
  - The only code that sets it to "" is `setNextMode(false)`, the "Start fresh" click (`:9657`).
  - The mode toggle is not reset after a run either, because `nextFollowUp` is kept in a closure (`:9646`).
- **(c) Since when.** The box and its handler arrived in 17ed2b5 (#13), 2026-07-11.
  - The owner reported the same kind of problem on 2026-07-23 as "Old question stays in the composer box". It is row 10 of `docs/archive/2026-08/UI-BUG-TRIAGE-2026-07-23-ANALYSIS.md`.
  - The PR1 fix, where `PR1/#10` first appears in b112f81 on 2026-07-24, cleared only the main question box (`#query-text`) and missed this box. So this is a known report that was only partly fixed, not a regression.
  - I found no GitHub issue for this box.
- **(d) Tests.** Every multi-run test types the second question straight into the main composer box and never uses the next-question box: `session-trail.spec.ts:148`, `:204`, `:261` and `:342`, all `getByRole("textbox").first().fill(...)`. The parity tests (`parity-behavior.spec.ts:552`, `:1490`) cover only one hop. No test checks what the box holds after a second result.
- **(e) Smallest fix.** Next to `:8718`, also set `el("result-next-input").value = ""` and reset the mode to "Follow up".
  - New real-browser test: type follow-up 1 into `#result-next-input`, click "Review & run", then run it. Assert `#result-next-input` has value "".
  - Positive partner: before the run, the box held the typed text.
  - The test fails today (probe step 3).

## Report 9: empty "THIS SESSION" panel

- **(a) Reproduced** with `PORT=18413 … probe/p2_empty.py`:

```
1440 fresh composer:    panelText 'THIS SESSION'          clearHidden True   entries 0
1440 after Start fresh: panelText 'THIS SESSION\nClear'   clearHidden False  entries 0
390  fresh composer:    panelText 'THIS SESSION'          panelPos 'fixed'
```

  - On a phone the empty panel is a fixed bar pinned to the bottom of the screen with nothing in it (`probe/p2_empty_trail_390.png`).
  - After clearing, a dead "Clear" button is left over an empty list.
- **(b) Root cause.** The empty branch of `renderSessionTrail` (`:6351-6355`) hides only the list. It shows no empty-state text and never hides `#session-trail-clear`. The markup is `workspace.html:957-963`.
- **(c) Since when.** Since 431071d (PR8), 2026-07-25. I found no issue or handoff that reports it.
- **(d) Tests.** No test checks what the panel shows when it is empty, or that "Clear" is hidden again after clearing.
- **(e) Smallest fix.** In the empty branch, set `clearBtn.hidden = true` and show one line of empty-state text, for example "Questions you ask in this tab appear here." Alternatively hide the whole panel until there is a first entry.
  - New real-browser test at 390px and 1440px: the fresh composer panel shows the empty-state line. After one run and then "Clear", the button is hidden.
  - Positive partner: with 1 entry, the empty-state line is gone.

## Related findings from the same code (not asked)

- **"Follow up on this" carries no context to the models.** `:98-100` says the browser sends no context on any run; the server accepts a `context` field (`query_runs.py:244`). `:9638-9640` and the page copy confirm that "Follow up" only pre-fills the box.
  - The owner's "chat history" expectation is therefore not met by design. It was agreed on 2026-07-23 (triage "User decisions" item 2) and never built in the browser.
- **The signed-in "History" list and the "THIS SESSION" trail are two unconnected lists.**
  - History is drawn on the server once, when the page loads (`main.py:835`, `:873-918`), as plain list items with no links. Nothing in `app.js` references it (`grep -n "account-history-list" app.js` found nothing).
  - So History only changes on reload, and its entries are not clickable. That is owner report 8, which belongs to another lens.
  - A signed-in run could be linked: `GET /v1/query-runs/{id}` returned 200 after sign-out and sign-in again (`probe/p4_resign.py`). How long a run stays readable in production is UNVERIFIED.
- **Prior reports.** I searched 26 local session transcripts, the docs and the GitHub issues for earlier reports of items 2 and 9. The only earlier reports found are triage row 10 and issue #126, which was the trail being capped at one entry.

Residue in the throwaway copy: the harness left `harness-18411..18415.sqlite3` files in the scratchpad copy's root. Nothing under `/Users/rohitagrawal/Projects` was written.


=================================================

**Starter questions: findings**

**(a) Reproduced.** There are 7 different starter questions, not 45. They are the same on the live site (build 7c74b4f).

Each one is a short fragment with no context. Clicking it puts exactly the button text in the box. Probe `probe/chips.py`, run with the harness, signed in:
```
click 0 -> textarea: 'Usage-based vs seat pricing?'
click 1 -> textarea: 'Aurora vs AlloyDB vs self-managed?'
click 2 -> textarea: 'Is my startup thesis defensible?'
click 3 -> textarea: 'Rewrite our retention policy?'
```
Free GET of production `/ui` with no cookie, reading the `data-landing-chip` values: the composer four above, plus the landing four: "Should we adopt passkeys by 2027?", "Usage-based vs seat pricing?", "Is my startup thesis sound?", "How do I read this lab result?".

Why they read as "incomplete":
- 4 of 7 point at something the user never gave: "my startup thesis" (twice), "our retention policy", "this lab result". There is no upload.
- Two of those invite the user to paste private material, right under the page's own "Don't paste sensitive or private data" notice (`workspace.html:364`).
- "Aurora vs AlloyDB vs self-managed?" is jargon for specialists.
- "Rewrite our retention policy?" asks for a rewrite, not a question with an answer. That is the kind of task Quorum's debate does not add value to.
- "defensible" and "sound" are two copies of one question.

**(b) Root cause.**
- The questions are hard-coded text in `src/product_app/templates/workspace.html:355-358` (composer) and `:842-861` (landing).
- One click handler, `src/product_app/static/app.js:9601-9637`, copies `dataset.landingChip` (the button text itself) into the box.
- There is no list in code, no audience grouping and no rotation.
- The text came verbatim from the design mock-up, `docs/design-handoff/Quorum Final Review.dc.html`.

Second defect found while checking this: the landing's medical example does not trigger the medical/legal/financial warning. `HIGH_STAKES_PATTERN` (`src/product_app/safety.py:35-42`) is a short keyword list. Probe `probe/hs.py`, which calls `required_warnings_for_query`:
```
no-high-stakes | How do I read this lab result?
no-high-stakes | What are the pros and cons of taking a statin for borderline high cholesterol with no heart disease?
no-high-stakes | Should I pay off my student loans early or invest the extra money?   ("loans" misses \bloan\b)
no-high-stakes | Roth IRA or traditional IRA: which is better early in a career?
HIGH_STAKES    | When should a cough that has lasted three weeks be checked by a doctor?
HIGH_STAKES    | Can I write a simple will myself online, or do I need a lawyer?
```
So adding a medical group without widening that list would show health and money questions with no warning.

**(c) Since when.**
- `git log -G 'data-landing-chip='` on `workspace.html` shows only `cea5886` (#7, landing chips) and `17ed2b5` (#13, composer chips), both dated 2026-07-11. The text has never changed since.
- The keyword list is unchanged since the first commit, `d3bbec2`, on 2026-06-20.

Earlier reports:
- The chip *wording* was never reported before. I searched `docs/analysis`, `docs/65-open-work.md` and `docs/archive`, `gh issue list --state all` for "example questions", "chip" and "starter", and the commit messages.
- The only earlier chip report is about *behaviour*: `docs/archive/2026-08/UI-BUG-TRIAGE-2026-07-23-ANALYSIS.md:21`, where chips skipped the hand-off note. That was fixed in `b112f81`.
- No issue exists about how many high-stakes questions the keyword list catches. #155, closed, was about the context-field bypass.

**(d) Existing tests and why they missed it.**
- `e2e/tests/ui-parity/parity-behavior.spec.ts:162-165` checks that there are 4 chips and that the first one fills in "Usage-based vs seat pricing?".
- `:828` and `:1470-1478` check click mechanics only.
- None of them checks that a chip is a complete, answerable question, or that a health chip shows the high-stakes gate.
- The spec itself needed a complete question for its own run test (`:1372`), because the chip text alone is not one.
- Whether a question "makes sense" can't be checked by a machine. It needs product-owner review of the list.

**(e) Smallest fix and the tests that would catch it.**
1. Move the questions into one list (a small JSON or template include), grouped by audience. Show 4–6 per group behind audience tabs. The button shows a short label; the click fills a complete, self-contained question.
2. Include health and money groups only together with a wider `HIGH_STAKES_PATTERN`: plurals, plus terms like lab, symptom, medication, dose, statin, cholesterol, blood, IRA, invest, mortgage, will. Widening it is a safety-policy change, so it needs an ADR.
3. Tests:
   - A pytest that parses every chip. It fails if the filled text is 8 words or fewer, does not end in "?", or contains "this/my/our" pointing at material the user never gave. It also fails if any health, money or law chip does not get `HIGH_STAKES` from `required_warnings_for_query`. Add a positive partner test that the gentle groups still load a non-empty list. **Red if:** a chip is shortened back to a fragment, or a medical chip's keyword is removed from the pattern.
   - A Chromium e2e test that clicks one chip per group and checks the box holds the full question. For the health chip, it checks that `#high-stakes-gate` is visible. **Red if:** the click handler copies the label instead of the full question.

**Research: what people use AI chat for**

- **OpenAI / NBER Working Paper 34255, "How People Use ChatGPT", 2025** ([paper page](https://www.nber.org/papers/w34255), [PDF](https://www.nber.org/system/files/working_papers/w34255/w34255.pdf)). I pulled the PDF text locally and quote from it; `probe/openai.txt` lines are given. The sample is about 1.1M conversations, May 2024 to June 2025.
  - Practical Guidance, Seeking Information and Writing are "about 77% of all ChatGPT conversations".
  - Practical Guidance is "roughly 29%". Writing fell from 36% to 24%. Seeking Information rose from 14% to 24%. Technical Help is "around 5%" (l.528-531).
  - Tutoring or Teaching is 10.2% of all messages. How-to advice is 8.5%. Computer programming is 4.2% (l.560-563).
  - Relationships and Personal Reflection is 1.9% (l.565).
  - 49% of messages are Asking, 40% Doing, 11% Expressing (l.609). The paper defines Asking as "seeking information or advice that will help the user ... make better decisions".
  - Non-work use rose from 53% of messages (June 2024) to 73% (June 2025) (l.127-128).
  - The health share appears only inside a figure image: UNVERIFIED.
- **Microsoft AI, "It's About Time: The Copilot Usage Report 2025"** ([summary](https://microsoft.ai/news/its-about-time-the-copilot-usage-report-2025/), [arXiv](https://arxiv.org/html/2512.11879v1)). 37.5M conversations, Jan–Sep 2025.
  - Top topics: Technology, Work and Career, Health and Fitness, Language Learning and Translation, Society/Culture/History.
  - On mobile, Health and Fitness is the top topic at every hour of the day.
  - Top intents: Searching, Advice, Creating, Learning, Technical Support.
  - I read this through the fetch tool's summary, not the full text.
- **Pew Research Center.**
  - [2025 short read](https://www.pewresearch.org/short-reads/2025/06/25/34-of-us-adults-have-used-chatgpt-about-double-the-share-in-2023/), 5,123 US adults, Feb–Mar 2025: 34% have used ChatGPT, 26% for learning, 22% for entertainment, 28% of employed adults for work.
  - [2026 report](https://www.pewresearch.org/internet/2026/06/17/americans-and-ai-2026-chatbots-smart-devices-and-views-on-impact/), 5,119 adults, Feb 2026: 49% use AI chatbots. About 42% use them to search for information, 38% of employed adults for work tasks, 20% for medical advice, 20% for diet and fitness information. The base for the 20% figures (all adults, or chatbot users) is UNVERIFIED; the fetch tool gave conflicting answers.
- **Anthropic Economic Index** ([Feb 2025](https://www.anthropic.com/news/the-anthropic-economic-index)): Computer & Mathematical 37.2%, Arts & Media 10.3%, Education & Library 9.3%, Business & Financial 5.9%; 57% of tasks help a person, 43% are done for them. [June 2026 report](https://www.anthropic.com/research/economic-index-june-2026-report): personal use is "just under 50%" on weekends against about 35% on weekdays. Both read through the fetch tool's summary.
- OpenAI's own blog post returned 403 and was not read.

**What this means for Quorum.** Per `docs/01-product-brief.md`, Quorum is best at questions where models may disagree, sources can be checked, and the user is weighing trade-offs. That matches the "Asking / Practical Guidance / Seeking Information" use. It is poor at rewriting tasks and at questions about documents the user hasn't supplied. Health and money are among the most common real uses, but they must carry the high-stakes notice.

**Proposed groups: complete questions, for the owner to review**
- **Everyday life:**
  - Is a heat pump worth it compared with a gas furnace in a cold-winter climate?
  - Should I buy an electric car or a hybrid if I can't charge at home?
  - What is the most effective way for a busy adult to learn a new language: apps, classes, or a tutor?
  - Is it better to repair or replace a ten-year-old laptop?
- **Health (with the high-stakes notice):**
  - What does the evidence say about intermittent fasting compared with ordinary calorie cutting for weight loss?
  - How much sleep do adults really need, and does catching up at the weekend work?
  - When should a cough that has lasted three weeks be checked by a doctor?
  - What are the pros and cons of taking a statin for borderline high cholesterol with no heart disease?
- **Money and law (with the high-stakes notice):**
  - Should I pay off my student loans early or invest the extra money?
  - Is renting or buying a home the better choice if I might move within five years?
  - Roth IRA or traditional IRA: which is better early in a career?
  - Can I write a simple will myself online, or do I need a lawyer?
- **Work and business:**
  - Usage-based or per-seat pricing: which suits a small B2B software product, and why?
  - What do the four-day work week trials show about productivity?
  - Contractors or full-time employees for a 10-person startup: what are the trade-offs?
  - Should a small online shop sell on Amazon, its own website, or both?
- **Technology and engineering:**
  - Should a small team choose PostgreSQL or MongoDB for a new web app?
  - Should a company replace passwords with passkeys by 2027?
  - Monolith or microservices for a team of five engineers building a new product?
  - Is a password manager safer than the passwords saved in my browser?
- **Learning and science:**
  - What does the evidence say about social media harming teenagers' mental health?
  - How close is practical nuclear fusion power, and what are the main obstacles?
  - Is nuclear power safer than wind and solar per unit of energy produced?
  - Why did the Western Roman Empire fall, and where do historians disagree?

Files are in `/private/tmp/claude-501/-Users-rohitagrawal-Projects-quorum-ai/e25d3396-0a5c-412b-aabf-e12be1095139/scratchpad/inv-starters/probe/`:
- `chips.py`
- `hs.py`
- `openai.txt` (the paper's extracted text)
- `pdftext.swift` (the extractor)
- `composer-chips.png`

Nothing was written under `/Users/rohitagrawal/Projects`.


=================================================

**Process audit of the W7 sign-in work (owner's question 5)**

The W7 pull requests were well tested one server feature at a time. Nothing ever drove a signed-in user through a whole journey in a real browser: no e2e lane can sign in at all. Two existing e2e tests pin two of the owner's reported behaviours as correct. Most of the reported bugs predate W7 and were never "fixed then undone". W7 put a history feature on top of them without testing how it combines with the older result page.

## 1. What each W7 pull request tested
Source: `gh pr view <n> --json body,files`.

| PR | Unit and integration | Mutation proof | e2e | Browser drive | Review |
|---|---|---|---|---|---|
| #510 sign-in (ADR-0130) | `tests/integration/test_google_sign_in.py`, unit tests | 47 of 47 killed | none cited | uvicorn log check only | round 1 had 4 lenses (incl. break-it, secrets); round 2 checked the real server |
| #518 history (ADR-0135) | 33 new test functions | 33 of 33 | lane 1: 308 passed; lane 2: 108 passed | History panel layout at 1440 and 390, light and dark, axe | round 1: privacy, correctness, UI and copy, prose; round 2: privacy, correctness, prose |
| #519 deletion (ADR-0136) | `test_account_deletion.py`, `test_spend_key.py` | 58 of 58 | 308 and 108 | delete steps driven by reviewers | 3 design rounds plus 1 bounded round |
| #521 session safety (ADR-0137) | `test_session_safety*.py` | 27 of 27, plus 14 of 14 | 308, 108 and 51 | none cited | 2 rounds plus 1 bounded round |
| #522 idle expiry (ADR-0138) | `test_idle_reminder*.py` | 30 of 31 | 308, 108 and 51 | reminder driven through the harness stub | 2 rounds |

Every mutation proof targets server functions. Every review lens was privacy, correctness, break-it, UI copy or prose. None was a user-journey lens (ask, follow up, Start fresh, History, spend limit).

## 2. The e2e server cannot sign in, so every "e2e passed" line tested the anonymous page
- `e2e/playwright.config.ts:31-32`: the test server is started with no Google sign-in settings.
- `src/product_app/google_signin.py:89`: `GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"` is fixed in code. Only in-process tests can point it at the loopback stub (`tests/google_token_stub.py`).
- `grep -rniE 'sign.?in|account-email|signed.?in' e2e/tests` finds no signed-in spec.
- The PRs said so themselves. #519: "No automated browser test drives the three delete steps (no e2e suite here can sign in)". #522: "No e2e lane can sign in." Both were recorded as advisory. No issue was filed: `gh issue list --search "sign in e2e"` returned nothing relevant.

## 3. Which of the owner's flows have any automated test

| Flow | Reproduced? | Root cause | Introduced | Test today |
|---|---|---|---|---|
| **1.** Start fresh wipes the question list | Code path read; I did not re-probe it (the trail investigation's `inv-trail/probe/p1_trail.py` is written but I did not see its output) | `app.js:9661-9664` calls `clearSessionTrail()` the moment the Start fresh tab is clicked, before anything runs. The list lives only in page memory (`app.js:6315-6325`); my probe step D shows 0 entries after a reload | 431071d (PR8, 2026-07-25); kept by 0d23c0e (#126) | `e2e/tests/invariants/session-trail.spec.ts:132` asserts that Start fresh clears the trail. **It pins the bug.** |
| **2.** The last follow-up stays in the box | **Yes.** Probe step B, after follow-up 1 ran: `'nextInput': 'F1 first follow-up?'`. Step C: `'composer': 'F1 first follow-up?'` | `app.js:9657` is the only line that empties the box, and only on Start fresh. `app.js:9674` pre-fills the last question when the box is empty | 17ed2b5 (#13, 2026-07-11) | `parity-behavior.spec.ts:552-567` requires the pre-fill (`toHaveValue(QUESTION)`). **It pins the behaviour.** |
| **8a.** History does not update during the session | **Yes.** Steps A and B: `'historyEmpty': True` after 2 runs. Step D, after reload: `'historyItems': 2` | `main.py:873` builds the panel only when the page loads. PR #518 chose "no separate history endpoint" | 5e28de9 (#518) | none |
| **8b.** History cannot be opened; **6.** no way home from the result page | **Yes** (`probe/resultnav.py`). Composer view: `history: True, howItWorks: True`. Result view: `history: False, howItWorks: False, email: False, brandIsLink: False, visibleBrandLinks: 0` | The History panel and "How it works" sit in `.topbar`, which `app.css:830-833` hides on the result, live-run and transcript views. The logo is a plain `<div>` (`workspace.html:84`). History rows are plain text with no link (`main.py:884-898`) | hidden bar: 17ed2b5 (2026-07-11); logo: cea5886 (2026-07-11) | `e2e/tests/navigation/navigation.spec.ts` tests only API endpoints |
| **3.** "$0.136 is over the $0.5 hard cap" | Code path read. Which limit fired in the owner's case is left to the cost investigation (UNVERIFIED here) | `app.js:7982-7985` prints the same "worst-case over the hard cap" sentence for every block. The server blocks for three other reasons too: total spend for the account or session (`costs.py:818-830`), a spend-ledger fault (`costs.py:893`), and the daily cap (`costs.py:977`) | sentence: cea5886 (2026-07-11); total-spend limit: 49f72d7 (2026-06-20). #519 changed which key a signed-in user's spend is counted against (`costs.py:804`) | `parity-behavior.spec.ts:193-201` shows a block with a $0.300 total, under the $0.50 cap, which is the same false-sentence case. It checks only the buttons, never the sentence |

## 4. Were these reported before, and did a fix come back undone?
- **Reported before:** yes, in `docs/archive/2026-08/UI-BUG-TRIAGE-2026-07-23-ANALYSIS.md`:
  - #10, "Old question stays in the composer box";
  - #11 and #12, follow-up context and the conversation trail.
- **Why #10 came back:** its fix plan (`UI-PR1-QUICKFIXES-ULTRACODE-PROMPT.md:74`) said the follow-up pre-fill spec should be kept green. So the result page's next-question box was never cleared.
- **Regression?** No. `git log -S` shows each behaviour in its original commit and never reversed. These were never fixed, and two tests lock them in.
- **Earlier issue #126:** the same pattern was already seen once. The session trail could hold only one entry "and its blocking gate enforces that".
- **GitHub issues:** searches for "follow up", "start fresh", "hard cap", "history", "logo", "homepage" and "example questions" found no issue for any of the five flows, only #126.
- **Chat reports:** the local transcripts only go back to 2026-08-30. No earlier report of these flows appears in that range. Whether the owner reported them in chat before 2026-08-30 is UNVERIFIED.
- **Owner's stated purpose:** on 2026-09-24 at 06:20:42 the owner wrote "the purpose of sig-in is to preserve the history of the searches from a account". PR #518 shipped history that cannot be opened, goes stale during the session, and is hidden on the result page. #518's own words say the session made the "no separate history endpoint" call, not the owner.

## 5. The process gap
1. **Tests were checked per feature, never per journey.** All the green e2e results (308, 108, 51) came from a server nobody can sign in to. The W7 sign-in, history and account screens were never tested together in a browser, and nothing blocked merging because of that.
2. **Known holes were recorded, not blocked on.** "No e2e lane can sign in" was written into two PR bodies as advisory. No issue was filed and no gate was added.
3. **Tests pin the defects.** `session-trail.spec.ts:132` and `parity-behavior.spec.ts:567` go red if the owner's bugs are fixed. The block-band test shows the false sentence and never reads it.
4. **No review lens looked at the product as a user.** Reviews checked privacy, races, money and prose, not "can a signed-in user find, open and keep their questions".

## Smallest fixes and the tests that would catch them
- **Let the e2e server sign in:** allow the Google token address to be set from the environment only when running locally, and start the stub from the e2e server command.
- **Add one signed-in journey spec** that checks:
  - after ask, follow up, and clicking Start fresh then Follow up, the list still has 2 entries;
  - the second follow-up box is empty;
  - History lists both questions without a reload;
  - the result page has a visible way home and a visible History control.
- **Rewrite the two pinning tests** so they assert the corrected behaviour.
- **Block message:** choose the sentence by which limit fired, and assert the text using an estimate under $0.50.

## Files
All in `/private/tmp/claude-501/-Users-rohitagrawal-Projects-quorum-ai/e25d3396-0a5c-412b-aabf-e12be1095139/scratchpad/inv-process/`:
- `probe/flows.py`
- `probe/resultnav.py`
- `probe/result_view_signed_in.png`
- `harness-18451.sqlite3` (the test database the harness created; delete it by name when done)

Nothing was written under `/Users/rohitagrawal/Projects`, and there were no production calls.


=================================================

## Cost-block and limits: findings

**Short answer.** Reproduced. Every block the owner can hit with the default models is the $0.40 daily account cap, not the $0.50 per-run cap. The page labels every block "Over the hard cap" all the same. It has done this since the first UI in PR #7 (2026-07-11). This was never fixed and then broken again. It was always wrong, and no test reads the text on the block card.

### (a) Reproduced
Probes `probe/cap.py`, `probe/resign.py` and `probe/rails.py` are in `/private/tmp/claude-501/-Users-rohitagrawal-Projects-quorum-ai/e25d3396-0a5c-412b-aabf-e12be1095139/scratchpad/inv-cost/probe/`. They run against the real routes on port 18421, with live execution off and a signed-in account.

Three simulated runs, then the fourth estimate:
```
A#1..A#3 estimate: allow est 0.1053 max 0.1593 ; create 202 ; completed
A#4 estimate: block est 0.1053 max 0.1593 reasons ['This run would take the account past its USD 0.40 daily cap.', 'Account has spent 0.3159 USD in the last 24 hours; ...']
```
The real UI (See the estimate) then shows, verbatim:
```
"cost-review-band-label": "Over the hard cap — this run won't start",
"cost-gate-reason": "This run is above the MVP cost limit. Choose lower-cost models, shorten the query, or reduce the workflow before trying again. This run would take the account past its USD 0.40 daily cap. Account has spent 0.3159 USD ...",
"cost-gate-block-note": "This run's worst-case cost (up to $0.159) is over the $0.5 hard cap and no override exists in this release. Nothing ran and nothing was charged."
```
Screenshot: `probe/block-signed-in.png`. The shape matches the owner's report exactly ($0.136 "over" $0.5).

The per-run hard cap cannot be reached with the default panel:
```
fresh account | len 19900 | allow est 0.1564 max 0.1829
after 3 sim runs | len 4000..19900 | block ... 'past its USD 0.40 daily cap'
```
Even at the longest allowed question, the worst case is $0.18, below both $0.30 and $0.50. So with default models the only block a user can see is the daily cap. Non-default panels are UNVERIFIED.

### (b) Root cause
- **(i) Wrong label.** The server has four different reasons for a block, and all of them come back as the same `threshold_action: "block"` with only prose `reasons`:
  - per-run cap: `costs.py:2354`
  - running total for the account: `costs.py:819`, whose own reason text "Worst-case cost is above the USD 0.50 hard limit for this account" is also false. That is from reading the code; I did not reproduce it.
  - spend ledger broken: `costs.py:894`
  - daily cap: `costs.py:978-1000`

  The page assumes that "block" always means the per-run cap:
  - `app.js:7966` hard-codes the headline.
  - `app.js:7983-7985` hard-codes the note "over the $0.50 hard cap", and does not check that the worst case is actually above $0.50.
  - `app.js:8878` (the fixed block message) says "above the MVP cost limit… choose lower-cost models".
  - The block banner at run start (`app.js:9102-9116`, title at `app.js:459`) ignores the server's reasons and shows "Hard cap $0.50 · no override".
  - The server's run-start message at `query_runs.py:719` says "exceeds the hard ceiling" for every reason.
- **(ii) Simulated runs count.** Yes, and this is intended. ADR-0074 ("Dropping simulated charges from the per-account cap too… rejected") and the docstring at `feedback_store.py:1216-1223` both say so. A simulated run is booked at its full estimate and never corrected down. `_reconcile_run_billing` returns early unless `cost_source == "measured"` (`query_run_orchestration.py:1709-1710`). Measured: the ledger reads 0.3159 = 3 × 0.1053. So the $0.40 cap allows about 3 simulated runs a day at today's estimate of about $0.105. Nothing in the UI tells the user this. The composer footer (`workspace.html:332`) names only "$0.50/run hard cap" and "one run at a time". No surface shows the $0.40 daily allowance or what is left of it.
- **(iii) Why a fresh session can run again.** Anonymous spend is counted per session. Signed-in spend is counted per account (`auth.py:837-866`, `costs.py:804`). Measured:
  ```
  B(anon, new context) estimate: allow ... create 202 ; completed
  A sign-out: 200 ; A after sign-out (anon) estimate: allow ... completed
  A re-signed-in, same Google account: block ... spent 0.3159
  C new browser, same Google account: block ... spent 0.3159
  ```
  So signing out, or opening a new browser without signing in, starts a fresh $0.40. Signed-in users are held to a stricter limit than anonymous visitors. `costs.py:175-186` calls accounts "free, self-issued" and leaves the per-visitor mint cap and the $5 site ceiling as the real bounds. In production an anonymous visitor is limited to 2 new sessions a day per network, unless the network is allow-listed or has an invite link.

### (iv) Every limit that can stop or change a run
| Limit | Where enforced | What the user sees |
|---|---|---|
| Per-run worst case > $0.50 | `costs.py:2354` | "Worst-case cost could exceed the USD 0.50 hard limit…" plus the hard-cap card (correct only here) |
| Worst case $0.30–$0.50 needs approval | `costs.py:2363`, `query_runs.py:738` | "Estimated query cost requires explicit confirmation." |
| Running total for the account > $0.50 (in-memory, simulated runs included) | `costs.py:813-832` | "Worst-case cost is above the USD 0.50 hard limit…" (wrong wording), shown as a hard-cap card |
| Spend ledger unwritable (off by default) | `costs.py:888-907` | Storage-fault text, shown as a hard-cap card. This was recorded in `docs/archive/2026-08/COST-OPS-BACKLOG-ULTRACODE-PROMPT.md:80` and never fixed |
| $0.40 per day per account, rolling 24h, simulated runs included | `costs.py:978-1000`; checked again at run start (`OVER_DAILY_CAP`, `query_run_orchestration.py:1033`) | Daily-cap reasons under a hard-cap headline and note |
| $5 per day for the whole site (live runs only) | `costs.py:1003-1015` | Not a block: the run switches to simulated answers with a banner (`app.js:778`, `app.js:2791`) |
| 2 new sessions per network per day | `auth.py:84`, `main.py:1692-1712` | `SESSION_MINT_CAP_EXCEEDED` "This IP address has opened its allowance of new sessions…" |
| Invite link daily sessions | `main.py:1676-1688` | `INVITE_DAILY_LIMIT` |
| 10 session requests per minute per network | `query_runs.py:430`, `main.py:1658-1667` | "Too many session requests from this IP. Retry later." |
| 30 requests per minute per account | `query_runs.py:530`, `:582` | "Too many requests for this account. Limit is 30 requests per minute." |
| Sign-in starts (burst 5, then 1 a minute) | `config.py:813-814`, `google_signin.py:642-654` | "Too many sign-in attempts from this network…" |
| One run at a time per account | `query_runs.py:842` | "One query can run at a time for this account." |
| 16 runs at once across the site | `query_run_orchestration.py:990`, `query_runs.py:772` | "Quorum is at capacity for concurrent query runs…" |

### (v) History
- The block-card strings date from `cea5886`, 2026-07-11, PR #7 (`git log -S "no override exists in"` and `-S "Over the hard cap — this run won"`).
- The daily cap is older. It started as `b83f7db` on 2026-06-22 at $0.10 and moved to $0.40 in `0b6b0b4` on 2026-09-07 (ADR-0102).
- The daily-cap reason text dates from `b2da723`, 2026-08-06, PR #263.

So the page has shown a daily-cap block as a hard-cap block from the first UI onward. It became something users actually hit as each run's estimate grew (ADR-0102 raised the debate cap) and because simulated runs count at full price.

I did not find an earlier report from the owner of this exact problem:
- `gh issue list --state all` with 10 searches found nothing.
- A scan of the owner's own typed messages in 25 earlier transcripts for "hard cap", "daily cap", "charged", "won't start" and similar words found nothing.
- The same wrong-label problem was written down by a session in `docs/archive/2026-08/COST-OPS-BACKLOG-ULTRACODE-PROMPT.md:80`: "the UI renders 'Over the hard cap', which blames the user's cost rather than a storage fault". It was not fixed.

The owner's line "session history becomes zero" belongs to another lens. I did not investigate it.

### (d) Why tests missed it
- The server tests check that the cap fires and what the reasons say, for example `tests/integration/test_query_run_cost_guardrails.py::test_daily_cap_admits_the_number_of_runs_its_dollar_value_pays_for`. None of them looks at the UI.
- Every UI test that shows a block uses a mocked estimate and never a real daily-cap block. Those are `e2e/tests/ui-parity/parity-behavior.spec.ts:195`, `e2e/tests/accessibility/axe-all-views.spec.ts:253` and `e2e/fixtures/golden-run.ts:298`.
- That mocked estimate has total 0.300, worst case 0.36 and the reason "Estimated spend exceeds the $0.25 hard cap." The server cannot produce that combination. Rendered, it would say "$0.36 is over the $0.5 hard cap", yet the tests assert only visibility and buttons, never the text.
- `grep "no override exists|Over the hard cap"` over `tests/` and `e2e/tests/` finds nothing.
- `real-integration-smoke.spec.ts:47-49` treats a block as a reason to throw, so it never looks at one.

### (e) Smallest fix and the tests that would catch it
1. **Server.** Add a machine-readable field `block_reason` to `CostEstimate`, set to `per_run_cap`, `account_running_total`, `daily_cap` or `ledger_unavailable`, at the four block points in `costs.py`. Correct the running-total reason text at `costs.py:825`. Put the reason into the run-start error at `query_runs.py:716-721`.
2. **Page.** Choose the headline, note and buttons from `block_reason`, never from prose. For `daily_cap` the page should say something like: "Daily limit reached. This account has used $0.32 of its $0.40 for the last 24 hours, and practice (simulated) runs count too. It frees up as earlier runs pass 24 hours. Nothing ran and nothing was charged." Show the "over the $0.50 hard cap" note only when the reason is `per_run_cap` and the worst case really is above $0.50. Do the same for the run-start banner at `app.js:9102`. Separately, and this needs the owner's decision: show the remaining daily allowance next to the composer footer, and decide whether signing out should give a fresh anonymous $0.40.
3. **Tests.**
   - A Python unit test: every block return carries a `block_reason`, and `per_run_cap` is set exactly when the worst case is above $0.50. Turns red if any block point drops the field.
   - A real-browser e2e with no mocked estimate, driven like `probe/cap.py`: sign in, run simulated runs until blocked, click See the estimate. Assert that the headline has no "hard cap", that the note names the daily cap and the amount spent, and that no displayed "up to $X" is called "over" a cap larger than X. Turns red on today's `app.js:7966` and `7983`.
   - A positive partner test: a mocked `per_run_cap` block with a worst case of $0.60 still shows the hard-cap headline.
   - Replace the impossible 0.300 block fixture in the three spec files.

Nothing was written under `/Users/rohitagrawal/Projects`. `git status` shows the same 6 untracked files as at the start. The probe server on port 18421 is stopped. Probe files stay in the scratchpad `probe/` folder.


=================================================

**Critic's report: I re-ran or re-checked the claims the fixes depend on. The five reports mostly hold up. One proposed fix is incomplete, and a few questions got no answer.**

## What I re-checked myself

1. **Report 1: "Start fresh" wipes the trail.** CONFIRMED, by re-running `inv-trail/probe/p1_trail.py` on port 18471 (signed in).
   - Probe output:
     ```
     [3 result of follow-up 1] trail: ['How do I compute net revenue retention?', 'What are the key metrics...']  nextInput: 'How do I compute net revenue retention?'
     [4 after clicking Start fresh (nothing run)] trail: []  followPressed: 'false'
     [5 after clicking back to Follow up on this] trail: []
     [7 after page reload] trail: []
     ```
   - Code: `app.js:9661-9664`, where the Start fresh click calls `clearSessionTrail()`. That function is at `:6324-6327`.
   - `git log -S "clearSessionTrail();"` shows 431071d (2026-07-25) and then 0d23c0e (#126). This matches the reports.
   - The test that pins it is confirmed. `session-trail.spec.ts:132` asserts the list is hidden after Start fresh, and `e2e.yml:192` runs that spec in the blocking lane.
   - The `:141` test reaches the question box through `goBackToComposer`, which clicks Start fresh (`:40-44`). So it also depends on the trail being cleared.
2. **Report 2: the old follow-up stays in the box.** CONFIRMED by the same probe (step 3). The run-finish code clears only `#query-text` (`app.js:8717-8720`). `#result-next-input` is emptied only by `setNextMode(false)` (`:9657`).
   - Correction to "reported before": triage row 10 (`UI-BUG-TRIAGE-2026-07-23-ANALYSIS.md:30`) was about `#query-text`, not this box.
   - The PR1 plan (`UI-PR1-QUICKFIXES-ULTRACODE-PROMPT.md`, section C) chose to keep the follow-up pre-fill so an existing spec stayed green. The owner's complaint was fixed for one box and left on purpose in the other. It is not a regression.
3. **Report 3: the block text is wrong.** CONFIRMED by re-running `inv-cost/probe/cap.py` on port 18472.
   - Three simulated runs estimated at $0.1053 each. The 4th gets `block ... 'past its USD 0.40 daily cap' ... spent 0.3159`.
   - The page then says "Over the hard cap — this run won't start" and "worst-case cost (up to $0.159) is over the $0.5 hard cap".
   - The daily cap compares `already_spent + estimated`, both point estimates, not the worst case (`costs.py:977`). So the note's use of the worst-case figure is doubly wrong.
   - `app.js:7966` and `:7983-7985` are hard-coded with no check on which limit fired.
   - An anonymous session in a new browser context, and the same account after signing out, could both still run. That reproduces owner item 4.
   - **Not reproduced by me:** "signs back in, still blocked". My re-sign-in step got `429 RATE_LIMITED "Too many session requests from this IP"` (the 10-per-minute limit per network). That is one more limit a user can hit, with another unclear message.
   - Minor copy fault: the note prints "$0.5", not "$0.50". `gateUsd` → `formatUsd(..., {suffix:false})` (`app.js:7831`).
4. **Reports 6 and 8: no way home, History is stale and can't be clicked.** CONFIRMED by reading the code.
   - `app.css:830-833` hides `.topbar` on the landing, result, live-run and transcript views.
   - The result view's brand is a plain `<span class="result-brand">` (`workspace.html:528-531`).
   - History rows are `<li><span>` with no link (`main.py:884-898`). The only use of `account-history` in `app.js` is the panel toggle at `:10002`.
   - The navigation and process lenses name different logo elements (`:528` vs `:84`). Both are right: `:84` is the top-bar logo and `:528` is the result-header one.
5. **Report 5 (process): "No e2e test can sign in".** CONFIRMED.
   - `playwright.config.ts` starts uvicorn with no Google settings.
   - `GOOGLE_TOKEN_ENDPOINT` is a module constant (`google_signin.py:89`) with no environment override. Its only other appearance is the `__all__` list at `:894`.
   - Starter-questions side claim also confirmed: `HIGH_STAKES_PATTERN` (`safety.py:35-42`) returns False for "How do I read this lab result?" and "Should I pay off my student loans early?", and True for the lawyer question.

## Wrong or incomplete in the reports

- **Report 2's proposed fix is too small.** Clearing `#result-next-input` still leaves the old question in the main box. In Follow-up mode (the default), "Review & run" with an empty box fills `#query-text` from `state.liveQueryText` (`app.js:9674-9679`). `parity-behavior.spec.ts:567` requires that (`toHaveValue(QUESTION)`).
  - To give the owner a blank box, "Follow up" must stop pre-filling, or open empty with the previous question shown as context. That is a product decision, and it changes a second test that currently pins the behaviour.
- **"Follow up on this" sends no context to the models.** The trail lens noted this (`app.js:98-100`). It means "follow up" and "fresh" behave the same for the models. The owner's picture of a "chat history" cannot be met by UI fixes alone. That needs a decision before building.
- **"Sign-in is not a factor" in report 1 is only mostly true.** Signed in, the trail is also wiped by the idle-expiry reload (`app.js:9995`, which goes to `/ui` after `signed_in_idle_minutes=120`, `config.py:824`). The sign-out and delete-account reloads (`:9901`, `:10064`) wipe it too. W7 added these paths. None is the owner's direct case.

## Questions none of them answered

1. **Owner item 3's "session history becomes zero".** Nobody tied it to a cause. Nothing on the block card clears the trail (the only clear calls are `:9663` and `:10206`). The most likely cause is that the owner pressed Start fresh before the block. UNVERIFIED; a replay of the owner's exact steps would settle it.
2. **Which limit fired for the owner in production, and at $0.136.** The harness gives a worst case of $0.159 with default models, so the owner's panel or mode was different. Reading production logs for that estimate's `correlation_id` would settle it. That was not allowed here. UNVERIFIED.
3. **Whether production shows the same $0.40 daily cap.** `/status` (build `7c74b4f3…`) exposes no cap values. UNVERIFIED without the Fly settings.
4. **Signed-in users get less than anonymous ones.** Signing out gives a fresh $0.40, so an account is held to a stricter limit than a visitor. None of the reports asked whether that is intended. It needs an owner decision.
5. **Owner item 7's "45 questions".** The starter lens found 7 distinct chips. Nobody checked whether "45" meant "4–5" or another surface. The research numbers came through fetch-tool summaries, and some are marked UNVERIFIED in that report.
6. **Owner item 8: how long a History row can be reopened in production.** Runs stay readable in memory for 1 hour (`QUERY_RUN_TERMINAL_TTL`) on a single process. Whether production runs more than one machine is UNVERIFIED (`fly status`).
7. **No report proposed a gate so a pinned defect cannot hide again.** Two blocking specs lock in behaviour the owner calls bugs. Nothing flags a test that asserts a user-reported defect as intended.

## Cleanup

I deleted my residue by name: `inv-trail/harness-18471.sqlite3`, `harness-18472.sqlite3`, `probe/critic_p1.log`, `probe/critic_cap.log`. Ports 18471 and 18472 are free: `lsof` returned nothing. The main checkout's `git status` shows only the same 6 untracked files as at the start. Nothing was written under `/Users/rohitagrawal/Projects`, and production got only the one free `/status` GET.
