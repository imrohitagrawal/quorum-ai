# UI Bug Triage — 2026-07-23 — full analysis (single source of truth for the 4-PR fix series)

> Produced by a triage session: 16 user-reported issues from live use of
> https://quorum.stackclimb.com/ui (screenshots + a run export), investigated by three
> parallel code explorers (file:line evidence below) plus a live Chrome walkthrough of prod
> (chip flow, landing view, theme toggle confirmed by direct observation).
> The four PR prompts (`UI-PR1-QUICKFIXES-ULTRACODE-PROMPT.md`, then PR2–PR4 authored one
> per session close) reference this file — do not restate its content in prompts; verify it.

## Verdict legend

- **BUG** — behavior implemented, currently wrong.
- **NEVER BUILT** — the user remembers a discussion, but the feature was never implemented
  (in several cases explicitly deferred in code comments). Not a regression.
- **BY DESIGN (bad UX)** — code does what it was told; the design/copy is the problem.

## The 16 issues

| # | Report | Verdict | Root cause (file:line) | Fixed in |
|---|--------|---------|------------------------|----------|
| 1 | Suggested-question chips skip the "Run Estimate / Run" hand-off; typed questions get it | BUG (gap) | Chip handler `app.js:6516-6527` fills the composer and jumps instantly; typed path `handoffFromLanding` `app.js:6436-6463` shows a hand-off note + 2.8 s dwell (`LANDING_HANDOFF_DWELL_MS` `app.js:6296`). Both DO land on the composer — chips just skip the message. | PR1 |
| 2 | "Run notices … no citation annotations … fallback web search … :online results" confusing | BY DESIGN (bad copy) | Exact string set in `providers.py:335-338` (notice branches 317-345); rendered via `workspace.html:420-422`, `app.js:1801-1855`, `3895-3899`, `4097-4147`. Developer-speak (`:online`, "citation annotations") leaks to users. | PR1 |
| 3 | Synthesis sections (Consensus/Disagreement/Uncertainty/Recommendation/Sources) trimmed; no expander | **DATA truncation, not CSS** | `synthesis_length.py`: `DEFAULT_SECTION_MAX_CHARS = 280` (l.30), `RECOMMENDATION_MAX_CHARS = 420` (l.34); `truncate_section()` (l.52) hard-cuts + "…" (l.88) **before storage** (applied in `synthesis.py`, e.g. l.694-699, 737). No CSS clamp on `.result-synth-body` (`app.css:3212-3217`). An expander alone can never recover the text. | PR2 |
| 4 | Debate rounds / "Summary for Human Reviewer" trimmed (ends "It shoul") | **DATA truncation** | `DEBATE_ROUND_MAX_TOKENS = 700` (`debate.py:52`, used l.428); token-capped output stored verbatim with **no finish-reason check** (`debate.py:369,399`). "Summary for Human Reviewer" is inside the LLM's own critique text — same cut. Also `SYNTHESIS_SECTION_MAX_TOKENS = 800` (`synthesis.py:88`). | PR2 |
| 5 | Literal `*` asterisks/bullets in rendered text | BUG | Block renderer `formatAnswerText` (`app.js:4206-4306`) handles `* ` bullets at line start, but **inline surfaces** (`setInlineProse` `app.js:4335` → `mdInline` 4349-4400) have no list support → `source_support` caption (`app.js:2382`), trust captions, high-stakes caveat render `* ` literally; odd asterisk counts leave a stray `*` ("reliability issue*"). **CI gate gap:** `RAW_MARKDOWN_PATTERNS` (`e2e/fixtures/golden-run.ts:40-56`) has no `* `/`- ` bullet or single-asterisk pattern — bullets escape the blocking invariants gate. | PR3 |
| 6 | No dark-mode toggle on landing | BUG (confirmed live) | `#theme-toggle` lives in `.topbar` (`workspace.html:87`), but `app.css:597-602` hides the topbar on `landing`, `result`, `live-run`, `transcript`. Toggle only reachable on composer + cost-gate. Also: no localStorage persistence, no `prefers-color-scheme`; `<html data-theme="light">` hardcoded (`workspace.html:2`). | PR1 |
| 7 | Debate quotes truncated ("> Star" incomplete blockquote) | **DATA truncation (prompt-side)** | Moderator sees only `answer_text[:200]` (`debate.py:450`, labelled "first 200 chars"); synthesis prompt gets answers `[:600]` (`synthesis.py:496`) and critiques `[:700]` (l.518); movement synopses cut at 140 chars (`debate.py:641-654`). The moderator is told to quote passages — of already-cut text. | PR2 |
| 8/15 | "The panel's leaning/verdict" says "do not act…" while "4 of 4 models aligned"; contradicts Consensus | BY DESIGN (contradictory) | Headline = `final_synthesis.recommendation` verbatim (`renderVerdictBand` `app.js:2492-2559`), which is **citation-coverage-driven** (templated: `synthesis.py:701-737`; live prompt rule `synthesis.py:125`); "N of 4 aligned" is a separate deterministic tally (`debate.py:657-667`, `synthesis_consensus.py`). Coverage is chronically low because `:online` often returns no annotations and Tavily fallback sources deliberately don't count (`synthesis.py:259-260`). "Heuristic fallback: " = `TEMPLATED_FALLBACK_PREFIX` (`synthesis.py:73`, prepended l.572,611,645,687,730) leaking internal jargon when live synthesis is unavailable. | PR3 |
| 9 | Stacked "Failed to fetch" toasts on the right | BUG | `startPolling` (`app.js:5725-5737`) polls every 750 ms and toasts **every** rejection verbatim (6 s life → up to ~8 stacked). Friendly `NETWORK_UNREACHABLE` mapping exists (`app.js:989-1013`) but the poll catch shows `error.message` raw. No dedupe/backoff. (A past toast-storm fix exists for a different bug: `parity-behavior.spec.ts:274-295`.) | PR1 |
| 10 | Old question stays in the composer box | NEVER BUILT | Nothing ever clears `#query-text` (grep: zero `queryTextarea.value = ""` outside Start-fresh). No history routing at all (zero `pushState`/`popstate`). | PR1 |
| 11 | Follow-up question answered without prior context | NEVER BUILT (explicitly deferred) | Code comment `app.js:6529-6531`: "there is no server-side context carry (that remains a documented backend follow-up)". `POST /v1/query-runs` payload = `{query_text, model_slots, safety_acknowledgements, cost_confirmation}` only (`app.js:5524-5532`; `query_runs.py:261-268`); provider messages always `[system, user(query_text)]` (`providers.py:700-728`). | PR4 |
| 12 | No conversation trail when following up | NEVER BUILT (ephemeral by design) | Client keeps only `state.liveQueryText`; nulls result state on each run (`app.js:5537-5545`). Server: in-memory repo + TTL; `run_history_store.py` persists **metrics only, never prose** (PII minimisation). No endpoint returns past runs' text. | PR4 |
| 13 | Run ID looks clickable, "nothing happens" | BUG (invisible feedback) | It IS a copy button (`app.js:2455-2474` → `copyRunIdToClipboard` 3963-3985). Success/failure feedback is **only** `title`/`aria-label` change; `navigator.clipboard` unavailable/blocked (incognito/insecure) fails silently. Receipt's `⧉` button has a visible cue (`app.css:2860`); header button does not. | PR1 |
| 14 | "Please enter a question before running" fires on Start fresh | BUG | `state.submissionAttempted` set true on submit (`app.js:5426,5473`) and **never reset**; Start-fresh path writes `""` + dispatches `input` (`app.js:6561-6562`) → error branch `app.js:4695-4697` paints on arrival. | PR1 |
| 16 | Swap slot 4 deepseek → `nvidia/nemotron-3-nano-30b-a3b` | CHANGE REQUEST | Source of truth `DEFAULT_MODEL_IDS` (`model_slots.py:92`; price comment 55-64); `DEFAULT_VENDORS` (`catalog_fetcher.py:51`); `ONLINE_CAPABLE_VENDORS` (`model_slots.py:382`) — **nvidia absent; `:online` support UNVERIFIED, check first**; `_FALLBACK_CATALOG` entry needed with curated short name + real prices (`catalog_fetcher.py:153-160`); `vendorForModel` (`app.js:1126-1135`) + tint (`tokens.css:48`, `app.css:4602-4604`); copy strings naming Deepseek (`app.js:604,614,2165,3779`); ~114 deepseek refs in tests/fixtures/docs/openapi. Display drift note: prod shows "deepseek-v3.1-terminus" because the live catalog superseded the curated id and `_short_name_for()` (`catalog_fetcher.py:187`) strips the vendor from the raw slug. | PR4 |
| — | (Found during triage) Export loses everything | BUG | The exported markdown contains **5 lines** (question, leaning line, agreement count, run id) — no synthesis, answers, or debate. Combined with #3/#4 there is currently no way to read or keep the full analysis. | PR2 |

## User decisions (recorded 2026-07-23)

1. **Truncation (#3/#4/#7):** full text + expanders — remove/raise server caps, finish-reason
   handling so nothing ends mid-sentence silently, UI expand/collapse previews.
2. **Follow-ups (#11/#12):** minimal context-carry — prior question + final synthesis in the
   prompts; compact client-side session trail (browser-session only, preserving the
   ephemeral privacy stance).
3. **Verdict (#8/#15):** restructure the band — agreement-led headline, coverage caution as a
   clearly separate second line, "automated summary" badge replacing the
   "Heuristic fallback:" prefix (backend gains `synthesis_mode` field; prefix stops leaking).
4. **Shipping:** four staged PRs by theme, each a fresh-session ULTRACODE prompt, TDD'd,
   adversarially reviewed (≤2 cycles), deploy-verified in order.

## The 4-PR series

- **PR1 — quick UI bugs + copy** (`UI-PR1-QUICKFIXES-ULTRACODE-PROMPT.md`): issues 1, 2, 6,
  9, 10, 13, 14. Frontend-heavy + one backend copy string.
- **PR2 — data completeness**: issues 3, 4, 7 + export. Raise/remove `synthesis_length.py`
  caps (280→~4000 / 420→~2000 as safety bounds with explicit "(shortened)" markers),
  `DEBATE_ROUND_MAX_TOKENS` 700→2000 + finish-reason marking, excerpt slices `[:200]`/
  `[:600]`/`[:700]` raised to real text, full-content export, frontend expanders
  (synthesis sections, transcript rounds, trust captions — replace the 4-line clamp
  `app.css:2577-2585`). Re-verify estimate-gate cost stays under the $0.25 hard cap.
- **PR3 — verdict band + markdown gate**: issues 5, 8, 15. Band restructure +
  `synthesis_mode` field; inline-surface list handling + stray-asterisk fix; widen
  `RAW_MARKDOWN_PATTERNS` with `* `/`- ` bullets + stranded `*` and extend the golden
  fixture — prove the gate RED on the current defect, then GREEN. Visual baselines reseed.
- **PR4 — follow-up context + model swap**: issues 11, 12, 16. Optional `context` object on
  `QueryRunCreateRequest`; prompt assembly incl. prior turn in providers/debate/synthesis;
  estimate counts context tokens; session trail UI; update the `app.js:6529` comment.
  Nemotron swap with the `:online` verification gate above; if `:online` unsupported, slot 4
  relies on the Tavily fallback and the UI says so honestly.

PR2–PR4 prompts are authored at the close of each preceding session (not up front) so each
incorporates learnings and a fresh `git log`/prod state — this file carries the scope.

## Cross-cutting cautions for all four sessions

- Deploy verification = deploy JOB ran (`gh run list --branch main`, filter
  `startsWith(SHA)`; `--commit` silently returns `[]`) AND
  `curl -s https://quorum.stackclimb.com/status | jq -r .build_sha` == merged SHA.
- A push to `main` cancels in-flight CI — follow-ups via branch+PR only.
- Manual browser spot-checks are browser-dependent (CSP differs per browser) — verify prod
  cross-browser via the e2e/csp-smoke machinery, not one look.
- $0/hermetic by default; at the very end of the series, ONE deliberate cheap live run
  (~$0.02, user-approved) to confirm full-pipeline data completeness + follow-up context.
- Copy/notice strings are pinned by tests — change producer + every pinned test in-diff and
  prove both directions.
