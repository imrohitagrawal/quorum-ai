> **Archived 2026-10-11** (CHG-040 (c)). The process now lives in `.agents/skills/work-item-delivery/SKILL.md`; this file is history and is not to be run. Home-directory paths were replaced with `~`.

# ULTRACODE — the 2026-09-24 backlog: eight packages in a fixed order

ultracode. Workflows and subagents for READ-ONLY fan-out only (understanding,
review, verification). Never for building: subagents share one working tree.

I am away. Do NOT wait for me. Work the queue in §5 in order. Every decision
you need is in §4, in my own words where quoted; do not re-ask any of them.
Stop only at a §2 hard stop, and then write it in the report.

---

## 0. Read first, in this order, then run the checks

1. `AGENTS.md` — it overrides everything here on every technical rule, with
   ONE exception: §2 and §3 of this file are the explicit human approval that
   AGENTS rule 17b requires (push, open a PR, merge, deploy). Granted for this
   session, bounded by §2.
2. `docs/00-factory-console.md`, `docs/session-handoff.md`.
3. `docs/analysis/2026-09-24-session-handoff.md` — what shipped on
   2026-09-23/24 (#496, #497, #498) and the eight traps measured.
4. `docs/analysis/2026-09-24-w5-scoping.md`, `docs/adr/0121-*.md`,
   `docs/analysis/2026-09-23-byok-failure-modes.md`, CHG-011 in
   `docs/19-change-control-log.md`, and the 2026-09-23 section of
   `docs/analysis/2026-09-22-decision-register.md`.
5. The issues: #458, #459, #447, #268 (draft PR #491 on the parked worktree
   `../quorum-ai-wt-268`, ADR-0119 lives on that branch only).

```bash
cd ~/Projects/quorum-ai
git status --porcelain     # expect only CONTINUE-*.md prompts (untracked)
git worktree list          # expect quorum-ai (main) + quorum-ai-wt-268 (parked)
git log --oneline -1       # expect 42cd965 or later
curl -s https://quorum.stackclimb.com/status | jq '{build_sha,live_execution,peer_critique_enabled,peer_critique_in_effect}'
ls -lt ~/.claude/projects/-~-Projects-quorum-ai/*.jsonl | head -3
```

`live_execution` must be false. A transcript written in the last few minutes
means another session may be live: read its tail before taking work. Do NOT
run `make handoff` here; it belongs at §8 only. The other root `CONTINUE-*`
prompts are superseded by this file. Run the commands, not the numbers: if a
figure here disagrees with a command, the command wins and you say so.

---

## 1. What this session is for

Eight work packages, §5, in that order, one pull request each, each merged
and verified in production before the next starts. The FIRST package also
files the decision record for everything in §4. If a package is bigger than
it looks, say so, park it (§5 parking protocol) and continue with the next.

---

## 2. HARD STOPS — stop, write it in the report, do not ask twice

- Any paid API call or live run. `/status`, `/ready`, `/metrics`, `/ui/ops`,
  `/estimate` and the free OpenRouter catalog are fine. One free `curl` to
  the live OpenRouter API for a header or error shape (AGENTS rule 8c) is
  fine; a completion is not.
- Opening, extending or re-affirming a live-execution window; editing
  `configs/live-execution-windows.json`; any `fly secrets` command.
  **Exception, decided in §4:** package 1 flips `PEER_CRITIQUE_ENABLED` to
  `"false"` in `fly.toml` and couples it to the window scripts. That is the
  only flag change authorised, and it is authorised.
- Merging any change to a shipped money value (defaults, caps, bands,
  ceilings, rate limits, mint caps). Build it, gate it, DRAFT PR, stop.
  Package 6 (#268) restructures the BOUND and leaves the constant at 2000;
  if the restructure cannot avoid moving a value, DRAFT PR and stop.
- Any merge whose `EXPECT_CLOSE` is non-empty (closing an issue). Write
  `Refs #N`, never Fixes/Closes/Resolves, in PR title, PR body and merge body.
- Lowering a threshold, `# pragma: no cover`, deleting or exempting a test.
- Force-push, history rewrite, `git clean`, `git stash`, touching secrets,
  `git add -A` at the repo root (stage named paths only).
- Recording a decision I have not made. §4 is what I decided; anything
  beyond it is `PROPOSED — AWAITING OWNER` in every artefact.
- Writing "half" in price copy, or a range in the landing headline.
- Two fix rounds in a row that add a defect: stop, root-cause, re-plan, report.
- W7 only: storing a provider key, a password, or any Google token beyond
  the sign-in exchange; storing more than the summary row per run (§4 W7).

---

## 3. Standing authority to merge, when ALL hold and the output of each is shown

1. Required contexts re-derived (`gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'`, six on 2026-09-24) and each SUCCESS on the PR head SHA.
2. `make quality` and `make validate` exit 0 in the worktree, read as two steps (never through a pipe).
3. `make diff-cover DIFF_BASE=origin/main` green on a COMMITTED tree, run last after a fresh `make quality`.
4. `make api-contract`, `make openapi-check`, `make security-scan` exit 0; the e2e lanes per §7 if UI, specs or fixtures changed; `node e2e/tools/check-negative-assertions.mjs <spec>` on every changed spec.
5. Review complete: correctness, break-it and prose lenses (rule 11a verbatim in every prompt), every finding reproduced BY YOU and triaged, zero open CRITICAL_BLOCKER or REQUIRED_CONTRACT. Two rounds max. Give every reviewer its OWN `git archive HEAD` copy in a `$RANDOM-$RANDOM` directory and a port above 18200 (they overwrote each other on 2026-09-24).
6. Every behavioural change has a test proven by mutation (cp aside, mutate, clear `__pycache__`, run, restore from the copy, `cmp`), recorded in the commit body. UI changes: the byte-identical proof of the result and transcript views on `goldenCompletedResp()` (rule 13e) or, where a view changes by design, the full-document diff with every hunk explained.
7. `make close-guard` with an explicit empty `EXPECT_CLOSE`.
8. Finish the PR body BEFORE the final push (`ci.yml` fires on `edited`).
9. After merge: every Deploy RUN for the merge SHA enumerated, each Deploy JOB read, exactly one `success`; `/status.build_sha` equals the merge SHA; `/ready` 200.
10. Then `git merge --ff-only origin/main` in the main checkout, delete the branch local and remote, remove the worktree.

---

## 4. The decisions — taken by the product owner on 2026-09-24, in chat

Source: transcript `df5e9b18-4276-47ee-a183-997cf95518ae`, the owner's own
`type: user` messages at the UTC times given. Where a sentence is quoted it
is the owner's; where it is not, it is the session's phrasing of what the
owner answered, and the register section package 1 writes must say so.

**D1. W5, the N=1 quick-answer mode (06:20:42Z).** Owner: *"Guard: separate
mode: "quick", Copy: "Quick answer — one model, no debate", show info message
that "four models by default, 2 debates and 1 sourced answer" which we have
been using in this product as a feature available, Price posture: judge on,
cost gate kept, so user knows that did the 1 model approach was actually good
for him/her or not. Judge will help user understand whether the answer that
model give is how much accurate."* So: a separate request shape
(`mode: "quick"`), the panel validator untouched (2 to 4 stays); the mode's
copy is that sentence; the mode shows the product-default info line; the
judge runs and is a priced `by_stage` row; the cost gate applies. The mode
keeps the answer, source support, citation coverage, safety notices and the
receipt; drops the agreement ring, verdict band, debate transcript and
convergence-based trust (approved plan of 2026-08-25, quoted in the
register's W5 section). No per-run toggle of any other kind (CHG-011 D9).

**D2. #458 (06:20:42Z).** Owner: *"yes, couple the flag"*. Couple
`PEER_CRITIQUE_ENABLED` to the live-execution window scripts so closing a
window turns it off with live execution; flip the production value to
`"false"` in `fly.toml` in the same change (it is currently `"true"` with
live execution off, which promises up to eight critic calls the moment a
window opens). Peer critique turns on again only by the window mechanism.

**D3. #459 (06:20:42Z).** Owner: *"option 1 only."* Correct every stated
watchdog latency to the measured 2 to 6 hours, with the date and sample size
from the issue; do not tighten the cron; do not move the check.

**D4. #447 (06:20:42Z and 06:24:09Z).** Owner: *"JUdge should be able to
verify the sources then only will be able to judge properly."* and *"I agree
with your choice"* to the session's Route B: a credential-guarded fetcher
that reads the cited pages so the judge grades what it has read. Sequencing
inside it: one free capture first to see whether OpenRouter's annotations
already carry page content; if they do, they are a cheaper input to the same
fetcher, never a substitute. The fetcher reuses `credentialed_url.py`'s
guards (no redirects, scheme guard) and bounds time per fetch (AGENTS 8b).

**D5. #268 (06:24:09Z).** Owner: *"#268: pick b"*: keep
`cost_web_search_context_tokens = 2000` and restructure the worst-case bound
so that a truer constant cannot move an affordable mix into `BLOCK`. The
constant itself does not move in this session; ADR-0119 (branch
`proposal/268-web-search-context-tokens`, draft PR #491) records the two
questions and their measurements; that branch's input-half work is folded
into this package or superseded by it — say which, and close #491 only by
merging or by an explicit owner decision (neither is in §4; if the branch is
superseded, leave #491 open and say so in the report).

**D6. Order (06:24:09Z).** Owner: *"Order: W5 first (small, unblocked now),
then W7 as its own package."* Not clubbed. The full order is §5.

**D7. W7, sign-in with history (06:20:42Z, 06:58:37Z and the exchange that
followed).** Owner: *"the purpose of sig-in is to preserve the history of the
searches from a account. THis can be limited to last 5 searches for example
if we face issue in storage."* The owner then accepted the session's rule:
- keep the last 5 runs per account AND drop anything older than 30 days, both
  as environment settings with pinned defaults (`HISTORY_KEEP_COUNT`,
  `HISTORY_KEEP_DAYS`), not a toggle surface, not per-user;
- store the summary row per run (question, date, verdict line, cost, run
  id), not the whole run; the full result is re-openable only while the run
  is still in the run store;
- nothing is deleted on sign-out (owner: *"the whole purpose will be
  forfeited if we delete the history on every sign-out!"*); history belongs
  to the account;
- account deletion: a typed-confirmation action on one authenticated
  endpoint that removes the account, its history rows and its session in one
  transaction and signs the browser out; operator run rows keep their counts
  with the account id set to null; the 24-hour spend envelope stays keyed on
  a one-way hash of the Google subject for 24 hours after deletion so
  deletion cannot reset it;
- W7's pull request rewrites "Results are ephemeral" (`main.py`
  `_app_description`, CHG-004) for signed-in users, files the CHG row and
  the threat-model rows (T-006 and a new history row), and writes the ADR.
Google sign-in only; no password; no durable provider key (BYOK is D8).

**D8. BYOK (06:58:37Z).** Owner: *"BYOK delivery timing: after all the
current features and bugs are worked upon."* BYOK is LAST, after every
package in §5. ADR-0121 stays `PROPOSED — AWAITING OWNER` until then; its
prerequisite (the confirmation token binding the slot list and the shape) is
package 2.

**D9. The decision register (06:59:26Z).** Owner: *"confirmed"* — the
reconstructed sections of `docs/analysis/2026-09-22-decision-register.md`
(dated up to 2026-09-22) are confirmed as written. Package 1 removes the
AWAITING label from those sections and says who confirmed, when.

---

## 5. The queue

**Parking protocol.** An item that needs a decision not in §4, or that is
bigger than one package: push the branch, open a DRAFT PR carrying the
evidence, leave the worktree, record it in §8's Pending, cut the next
worktree fresh off `origin/main`. Do not idle.

**Every package:** dedicated worktree off fresh `origin/main`
(`uv sync --all-extras`; `cd e2e && npm ci` if you will run e2e); TDD with
the verbatim red output; mutation proof per behavioural change; a decision
gets its ADR or CHG row in the same PR (rule 16d); rule 11a prose audit;
one line in the PR body saying why the package outranks the rest of the
queue (rule 20 — here, "it is next in the owner's order of 2026-09-24").

### Package 1 — #458: couple the peer flag to the window, and file the decision record

One concern: "peer critique cannot outlive a window". Build: the window
scripts (`scripts/close_live_window.py` and whatever opens or re-affirms a
window) set `PEER_CRITIQUE_ENABLED` with the live flag; `fly.toml` reads
`PEER_CRITIQUE_ENABLED = "false"`; a test proves closing a window flips both
and that no other writer of the flag exists; `scripts/live_posture_check.py`
treats a true peer flag with live execution off as a drift to report. The
landing subhead and the composer shape line already follow
`_peer_critique_in_effect`, so no copy changes; prove it with the existing
tests. **In the same PR, the decision record:** a CHG-012 row "Decided by the
product owner 2026-09-24" with D1 to D9 (quotes verbatim, the rest marked as
the session's phrasing); a 2026-09-24 section in the decision register with
the same, citing transcript `df5e9b18` and the times in §4; the AWAITING
label removed from the reconstructed sections per D9. Refs #458.

### Package 2 — the confirmation token binds the slot list and the shape

`costs.py::_format_token` binds `account_id | query_run_id |
estimated_cost_usd | expires_at | nonce`. Add the ordered model ids and the
critique shape the estimate was priced for; verification refuses a token
minted for another panel or shape; a test mints for a moderator panel of
two and proves it cannot confirm a peer panel of four (and the reverse);
rule 6b: assert HOW MANY tokens, not that one exists. ADR in the same PR
(it closes the D9 debt recorded in ADR-0120's handoff §3 and ADR-0121).
Watch `openapi.yaml` and the schemathesis lane. Refs CHG-011 D9.

### Package 3 — W5, the quick-answer mode

Build to D1 the way #494 was built: TDD, mutation proofs, e2e as CI, two
review rounds, byte-identical result and transcript views for the existing
modes. A new request shape, not a widened panel; `MIN_SLOT_COUNT` stays 2.
Estimate: one upstream answer, no debate, no synthesis rows, the judge row
present; the fail-safe bound shares the arithmetic. Result page: the answer,
source support, citation coverage, safety notices, the receipt, the judge's
verdict; the ring, band, transcript link and convergence trust absent (assert
absence WITH a positive partner). Copy per D1. Board row W5 gets a needle
(`ABSENT` of the new mode's validator message while open). ADR and CHG row
in the same PR. Refs W5.

### Package 4 — #459: the watchdog's measured latency

Docs and comments only, per D3: every place that states 30 minutes for the
live-posture watchdog reads the measured 2 to 6 hours with the date and
sample size from #459; a test pins that the cron comment and the ADR
paragraph agree (rule 1a: a check, not a corrected sentence). Refs #459.

### Package 5 — #447: the judge reads the sources (Route B)

First the free capture (D4) — read-only, no completion: does an `:online`
annotation carry page content? Record the answer with the command. Then the
fetcher: reuses `credentialed_url.py`, refuses redirects, bounds bytes AND
time per fetch, never sends any key to a cited host, caps the number of
pages per run, and hands the judge the fetched text with per-source
provenance; the judge prompt says what was fetched and what was not. Every
fetch is a priced or explicitly-free line on the receipt (rule: every
optional stage is a `by_stage` row). Failure-mode page first (rule 16e), ADR
and CHG row in the same PR. Two review rounds with a break-it lens on the
fetcher (SSRF, redirects, size, time). If the design cannot fit one package,
ship the fetcher behind a default-off setting with its tests, park the
judge wiring as a DRAFT PR, and say so. Refs #447.

### Package 6 — #268 (b): restructure the bound, constant unchanged

Per D5. Merge `main` into the parked branch first or start fresh and say
which. Redesign the worst-case bound so a truer web-search context constant
cannot move an affordable mix into `BLOCK` (candidates: bound the context
term separately from the output term; or price the bound from the point
estimate plus a measured margin). Prove with a sweep over the shipped
catalog's four-slot mixes that at 2000, 2500, 2900 and 3200 no mix changes
band under the new bound while the point estimate is unchanged to the cent
at 2000. Do not move the constant; the value is a later owner decision with
its own CHG row. ADR in the same PR. Refs #268.

### Package 7 — W7: Google sign-in with history

Per D7. Failure-mode page first (rule 16e: token handling, session fixation,
history leakage across accounts, deletion and the spend envelope, storage
growth). Then, if it fits, one PR; otherwise two in this order: (a) sign-in
and sign-out with the account row and the threat-model rows; (b) history
(summary rows, the two retention settings with pinned defaults, the
signed-in history view, account deletion with the hashed 24-hour spend key).
Copy: "Results are ephemeral" rewritten for signed-in users only. Board row
W7 gets a needle. ADR and CHG row in the same PR. Refs W7.

### Package 8 — BYOK

Only after packages 1 to 7 are merged and in production (D8). Start from
ADR-0121 and the failure-mode page; the first PR is key intake and scoping
with `credential_source` resolved per run. ADR-0121's Status changes to
Accepted only by an owner message; if you reach this package, build the
first PR as a DRAFT and stop.

---

## 6. Practices that are not optional

- One concern per PR, dedicated worktree off fresh `origin/main`, merged and
  deployed before the next starts.
- TDD with a bite-proof: capture the VERBATIM red output; prove every
  behavioural change by mutation; record each mutation in the commit body.
  Never `git checkout <file>`.
- Fan out for review, never for building. Tell every reviewer IN CAPITALS
  not to write, edit, `git checkout`, `git stash` or `sed -i` anything; own
  `git archive HEAD` copy, own directory, own port.
- Never move the tree under a running reader or gate.
- Audit prose (rule 11a) in every review prompt, verbatim. On 2026-09-24
  the prose lens found nine false sentences across two PRs; the code lenses
  found one.
- Attribution: "the owner decided X" only with a `type: user` record and its
  time; everything else is the session's phrasing. Say which, every time.
- Keep `docs/00-factory-console.md` untouched by hand; keep the board true
  (polarity describes the OPEN state; never flip ABSENT to PRESENT).

---

## 7. Commands that bite

- Fresh worktree: `uv sync --all-extras`, then `cd e2e && npm ci` if you
  will run e2e. A bare `uv run` builds a venv with no pytest.
- e2e exactly as CI, or ~95 phantom failures:
  ```bash
  lsof -ti tcp:18085 | xargs -r kill -9
  rm -f .data/feedback_events.sqlite3
  cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 SESSION_MINT_CAP_OVERRIDE=600 \
    npx playwright test <specs> --project=chromium --workers=1 --retries=0
  ```
  First blocking lane: the 18 specs listed in `.github/workflows/e2e.yml`
  (floor 298 on 2026-09-24; move it only by a re-measured count); second
  lane: axe-all-views, parity-behavior, docs-under-csp,
  real-integration-smoke, degraded-banner, ops-dashboard, ops-navigation.
  The visual lane fails on this Mac by design; never `--update-snapshots`.
- `e2e/tests/review/` is gitignored scratch; delete your own before
  `make quality`.
- Never read a gate's exit status through a pipe:
  `make <target> > /tmp/gate.log 2>&1; echo "EXIT=$?"; tail -30 /tmp/gate.log`.
- `timeout` does not exist on this box; use the tool's own timeout.
- Commit before trusting `make diff-cover`; a dict-literal continuation line
  measures nothing and the gate exits 0 with a notice — the pinned literal
  test is the cover.
- The cited-paths gate resolves any `tests/…py` token on an added line, even
  in a sentence saying the file does not exist; name a missing file without
  its path.
- `getModelIds()` throws before `/v1/models/defaults` answers; nothing on the
  landing may call it. `test_peer_caption_counts.py` pins the
  `describePeerCritique(` call-site count.
- The advisory CI mutation gate: read `score.txt` from the run artifact,
  post the number on the PR, never treat it as required.
- A merge produces 3 to 6 Deploy runs; exactly one has a Deploy JOB of
  `success`; read the jobs, never the count.
- `/ui` answers 429 from this machine; `/status`, `/ready`, `/estimate` do not.

---

## 8. Reporting — at the end, and at any hard stop

Post one closing block, in this order, plain English, no jargon:

`Done` (what merged, SHA, and that it is running in production, each with
the command that proved it) / `Verified myself` (what YOU ran, with output;
subagent reports separately) / `Cleanup` (what was deleted, with the
command output; worktrees and branches gone; nothing unpushed) / `Pending`
(anything parked, with its draft PR and the decision owed, in my words) /
`Next action`.

Before the block: `make next`, `make skill-route`, `make handoff`, and a
narrative `docs/analysis/<YYYY-MM-DD>-session-handoff.md` (a second session
the same day appends `-2`), merged as its own docs-only PR, deploy verified.
If nothing is outstanding, end with "nothing pending — safe to close this
session" in those words.
