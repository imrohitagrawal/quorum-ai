# Continue: the work board, then B2 → #290

Written 2026-08-28, at the close of the session that shipped ADR-0076/0077/0078.
This is an **executable procedure** — a future session runs it — and it lives at
root by the convention in `AGENTS.md` ("Where files live"), not in `docs/archive/`.

**W0 SHIPPED 2026-08-28.** The board it asked for is `docs/65-open-work.md`,
and that board — not the "board's initial contents" table further down this
file — is the source of truth for what is open. This document is now the
*procedure*; the board is the *state*. Where the two disagree, the board wins,
because a gate checks it (`scripts/check_open_work.py --check`, inside
`make validate`) and nothing checks this file. The rationale is ADR-0079.

**It supersedes both `CONTINUE-TRANSPORT-AND-RULES-ULTRACODE-PROMPT.md` and
`CONTINUE-DEMO-READINESS-ULTRACODE-PROMPT.md`**, which W0 moved to
`docs/archive/2026-08/`. Do not follow either. In particular the transport prompt's line 7 — *"There is a stale sibling at
root … IGNORE IT"* — **is wrong on the merits**, and acting on it is how
authentication went missing for a whole session.

---

## The prompt to paste into a fresh session

> Read `CONTINUE-OPEN-WORK-ULTRACODE-PROMPT.md` at the repo root and execute it,
> in the order it gives. Work autonomously: select, plan, build, review, merge,
> verify and close out each package without waiting for me, except at the STOP
> conditions the document names.
>
> **Treat every claim in this document as INHERITED.** Roughly half of what a
> handoff asserts does not survive contact with the tree. Re-derive by command
> before acting. Line numbers rot — grep for symbols.
>
> Use the `work-package-protocol` skill. One work package at a time, merged
> before the next starts. Fan out for review, never for building.
>
> You may push, open pull requests, merge and deploy.
>
> **SPEND NOTHING.** `OPENROUTER_LIVE_EXECUTION_ENABLED` stays `false` everywhere
> including production. Do not move any money constant outside the package that
> owns them. If a question can only be settled by spending, mark it UNVERIFIED,
> name the exact probe, and ask.
>
> You may use `Workflow` for the phases this document names. **Ceiling: 14 agents
> per workflow, one workflow at a time.** Do not turn ultracode on.

---

## State, re-derived 2026-08-28 (verify it again anyway)

```
main == origin/main == production build_sha == e115d92ac0703ca3ce6faa6174a13de0edfae1bd
live_execution: false        judge_enabled: true
worktrees: 1 (main only)     open PRs: 0      tree clean but for the root prompt files
next free ADR: 0079          next free docs/ number in the 60–69 range: 65
```

Open issues: **383, 382, 380, 379, 290, 268, 105**.

Shipped and **not to be rebuilt**: Track A (ADR-0075, #384), the rules PR
(ADR-0076, #385), B1 (ADR-0077, #386), B3 (ADR-0078, #388), durable sessions
(#377), the live/simulated cost split (#378).

---

## Why this document exists

Work here was planned in five places that did not know about each other: two
approved plans under `~/.claude/plans/` (outside the repo entirely), two
untracked `CONTINUE-*.md` at root, seven GitHub issues, a narrative handoff under
`docs/analysis/`, and a "factory console" that `AGENTS.md` mandates maintaining.

Measured, not asserted:

- **`docs/00-factory-console.md` is 64 commits behind its last touch and 242
  behind its content date (2026-07-23).** It still announces work from PR #91 and
  quotes `pytest 1342 passed`; the suite is 3730+. It has been touched by 11
  commits ever. **Six gates watch it and none checks whether it is current.**
- **#383, #382, #380 and #379 appear in no plan document at all.** They exist
  only in `gh`.
- **Three documents each claim to be the authoritative phase**: the console's
  `## Current phase`, `docs/session-handoff.md:34` (disavowed by its own line
  117), and `docs/analysis/R2-plan-review-findings.md:35`, which calls itself
  *"durable — authoritative"* and is a month old in abandoned R2 vocabulary.
- **A second live doc/code contradiction, unrelated and unnoticed:** FR-004
  (`docs/10-functional-requirements.md:53`) and an acceptance criterion
  (`docs/12-acceptance-criteria.md:51`) both name `deepseek/deepseek-chat-v3.1`
  as a default slot; the code ships `nvidia/nemotron-3-nano-30b-a3b`
  (`model_slots.py:67`, comment: *"replaces deepseek"*). No gate catches it.

---

## Orchestration — when to use a workflow, and how big

**Ceiling: 14 agents per workflow. One workflow at a time. Never for building**
(rule 9: subagents share one working tree).

Derived from the previous session's measurements, not picked: a 32-agent review
cost ~2.9M tokens, and **every finding that changed code sorted in the top five**
by severity — the `CRITICAL_BLOCKER` was first. The other 21 findings consumed
~60% of the budget and changed nothing.

| Phase | Shape | Agents |
|---|---|---|
| Failure-mode enumeration — money/auth/transport only, per rule 16e | 4 lenses + 1 synthesiser | **5** |
| Review of a small or docs-only diff | **solo** — fan-out costs more than it returns | **0** |
| Review of a normal code diff | 4 finders + top-3 findings × 2 refuters | **10** |
| Review of a money / auth / transport diff | 4 finders + top-5 findings × 2 refuters | **14** |

Six rules that make the fan worth its cost. Each was paid for:

1. **Severity-sort findings BEFORE applying the cap**, and `log()` what was
   dropped. Silent truncation reads as "covered everything". A previous run
   capped in *finder order* and left 6 of 11 unverified.
2. **A finding dies only if BOTH refuters refute it.** One refuter is a coin toss.
3. **Give every agent a uniquely-named scratch dir.** Two agents collided in
   `/tmp`; one detected the contamination and had to redo its run.
4. **Tell every agent IN CAPITALS:** read-only; no `git checkout` / `git stash` /
   `sed -i`; its own `git archive HEAD | tar -x -C <dir>` copy for anything it
   must execute or mutate; **no pytest in the shared tree**;
   `PYTHONDONTWRITEBYTECODE=1` and `python -B`, purging `__pycache__` between
   mutants.
5. **Tell every reviewer to audit the diff's PROSE**, not only its code (rule
   11a). Every false claim shipped here has been in prose, and reviewers not
   asked to look at prose do not look.
6. **`pytest-timeout` is NOT installed.** Passing `--timeout` makes pytest error
   out, so every mutant looks "killed" while nothing is tested — a whole
   mutation pass was invalidated this way. Use a subprocess timeout where a hang
   counts as a failure, and **always run an unmutated baseline first**: if it is
   not green, every kill below it is meaningless.

---

## W0 — the work board. Do this first, one small PR.

### Why not the obvious homes

- **Not `docs/00-factory-console.md`.** `scripts/factory_next.py:100` is an
  unconditional `write_text` of a fixed template, so **`make next` deletes every
  hand-written word**. `git stash show --stat stash@{0}` is the proof: *"2
  insertions, 88 deletions"* — someone ran `make next`, it wiped the status, and
  they stashed the damage. `AGENTS.md` tells a session to run `make next` **and**
  to maintain that file by hand; those two instructions cannot both be followed.
  Leave the console as the static factory-lifecycle template it actually is.
- **Not a root `STATUS.md`.** Ungated hand-written status is precisely the
  practice already skipped ~189 times here.
- **Not GitHub as the source of truth.** Issues are the right **mirror** — they
  already hold #383/#382/#380/#379 — but they are not offline-derivable, so no CI
  gate and no offline agent can read them. Source of truth in the repo; issues
  as the mirror.

### Build

**`docs/65-open-work.md`** — 65 is the first free number in ADR-0034's **60–69
"Implementation planning"** range (60–64 taken; verify before writing). Every row
carries its own falsifiable evidence:

```
| ID | Item | State | Evidence (grep-able) | Issue | Depends on |
|----|------|-------|----------------------|-------|------------|
| W1 | Stream the provider call | PENDING | src/product_app/providers.py::"stream": True | — | — |
| W2 | Peer critique, two rounds | PENDING | src/product_app/debate.py::_call_debate_model(model_id= | #290 | W1 |
```

**`tests/unit/test_open_work_matches_reality.py`** — three assertions, each with
a bite-proof and a positive partner:

1. **The inverted assertion — the move that makes the board self-maintaining.**
   A `PENDING` row asserts its evidence symbol is **absent**, so the gate goes
   **RED the moment the work lands**, forcing the row to be flipped to `DONE`.
   *Completing* work triggers the gate, not merely abandoning it. A `DONE` row
   asserts the symbol is **present**, so a row cannot be marked done over nothing.
2. **A count pin.** Copy `_check_countable_claim` from
   `tests/test_doc_gate_consistency.py` **Part D** (~line 1248) and steal all
   three of its rules: state the count as a **digit, not a word** (the original
   bug was literally `twelve` vs 15); an **anti-vacuity floor**
   (`assert rows, "refuses to pass over an empty input"`); and a **bite-proof**
   fed `real + 1` that asserts it raises.
3. **A freshness gate — the piece genuinely missing repo-wide.**
   `scripts/session_handoff.py:174` already computes `age_days` and **nothing
   ever reads it back**: `docs/session-handoff.md` currently records `2026-08-27`
   and prints `(today)`, and `make handoff` appears in **no** CI workflow. Parse
   the board's recorded SHA, assert it is an ancestor of `HEAD`, and fail when
   `git rev-list --count <sha>..HEAD` on first-parent `main` exceeds a threshold.

**Wire it into `make validate`** as a prerequisite at `Makefile:76`, exactly as
`adr-index-check` already is — the repo's own precedent for *a derived doc is
verified, not trusted*.

### Then close the loop

- **Demote the three phase claimants** with one line each pointing at the board.
  A board that does not demote them just becomes the fourth claimant.
- **Link it from the generated snapshot**: extend
  `scripts/session_handoff.py`'s `_narrative_pointer_line` (`:174`) with a second,
  symmetric pointer, so the board is reachable from `AGENTS.md`'s mandatory
  reading list.
- **Settle the three root prompt files. This is decided — do it in W0's PR, not
  a separate one.** All three are currently untracked, which is the exact
  failure that caused this document to exist.

  | File | Action |
  |---|---|
  | `CONTINUE-OPEN-WORK-ULTRACODE-PROMPT.md` (this one) | **`git add`** — keep at root, now tracked. It is a live executable procedure. |
  | `CONTINUE-TRANSPORT-AND-RULES-ULTRACODE-PROMPT.md` | **`git add`, then `git mv`** to `docs/archive/2026-08/` |
  | `CONTINUE-DEMO-READINESS-ULTRACODE-PROMPT.md` | **`git add`, then `git mv`** to `docs/archive/2026-08/` |

  `git add` **before** `git mv` in both cases: moving an untracked file commits
  nothing and looks successful. 32 `CONTINUE-*` files are already archived
  there, and `docs/archive/` is excluded from the doc gates, so archiving stops
  a document being held to live claims — desirable here, but a behavioural
  change rather than just a move.

  Archive **only after** their content is on the board. Both still hold live
  items: the transport prompt's B2 and its two small carries, and the
  demo-readiness prompt's packages D, E and F.

---

## The board's initial contents

Verified by command at `e115d92`. **Re-verify before trusting.**

| # | Item | State | Blocked by | Files |
|---|---|---|---|---|
| **W1** | **B2 — stream the provider call** | PENDING | — | `providers.py` + ~15 test files |
| **W2** | **#290 peer critique, two rounds** | PENDING | **W1** | `debate.py`, `query_run_orchestration.py`, `costs.py` |
| W3 | Money constants re-set | PENDING | **W2** | `costs.py` |
| W4 | Variable panel size N ∈ {2,3,4} | PENDING | — | `model_slots.py`, `costs.py`, `main.py`, `workspace.html`, `app.js` |
| W5 | Quick-answer N=1 mode | PENDING | **W4** | `synthesis_consensus.py`, UI |
| W6 | #383 — N=1 reports strong consensus | PENDING | — *(not W4)* | `synthesis_consensus.py` |
| W7 | Google sign-in + logout | PENDING | — *(unblocked by #377)* | `auth.py`, `session_store.py`, `main.py`, `openapi.yaml` |
| W8 | `min_machines_running` / demo-live | PENDING | — | `fly.toml` + an ADR |
| W9 | Slot/referee overlap guard | PENDING | — | `model_slots.py` |
| W10 | #382 — clique test for overlap | PENDING | — | `synthesis_consensus.py` |
| W11 | #380 — completeness denominator | PENDING | — | `evaluation.py` |
| W12 | #379 — `last_live_charge_at` | PENDING | — | `feedback_store.py` |
| W13 | #268 — bound call INPUT | PENDING | — | `costs.py`, `providers.py` |
| W14 | #105 — close 5xx with data | PENDING | prod logs | *no code* |
| W15 | `_bound_sniff_time` dangling refs | PENDING | — | `providers.py` — ride inside W1 |
| W16 | `catalog_fetcher.py:47` base URL | PENDING | — | `catalog_fetcher.py` |
| W17 | FR-004 names a model we don't ship | PENDING | — | `docs/10`, `docs/12` |

**Order: `W0 → W16 → W1 (+W15) → W2 → W3`**, with W6, W8, W9 and W17 as cheap
independent fillers when a lane is blocked.

### Hard dependencies, with their evidence

- **W2 ← W1.** The #290 spike measured **8 of 8** probe calls exceeding the 8s
  timeout on wall clock and **6 of 8** on the per-`recv` gap. Streaming collapses
  the gap to **0.478 / 0.208 s** on a paired sample (same model, same endpoint).
  Building critique first ships a feature that pays for discarded tokens and
  demotes every receipt to `estimated`.
- **W3 ← W2.** The approved constant shape prices a #290 that cannot yet be
  built, and rests on an unverified ~57% rise; measured is +25–41%. The projected
  judge-ON bound is **0.1419–0.1599** against `SOFT_THRESHOLD_USD = 0.15`, so
  #290's real shape decides whether every default run demands a confirmation
  click. Ordering `SOFT < DAILY_CAP < HARD` is mandatory (`costs.py:124`) or the
  confirmation band is dead code.
- **W5 ← W4.** N=1 is unreachable while `model_slots.py:188` rejects ≠ 4.
- **W6 is NOT blocked by W4** — it is reachable today on a degraded 4-slot run
  where three slots failed.

### What can run in parallel

**Cleanly disjoint: W1 + W6 + W8.** W1 + W4 is ~95% parallel — the single overlap
is `providers.py:320` (`Field(ge=1, le=4)`). **W4 and W7 both hold `main.py`,
`app.js` and `workspace.html`: sequence them, do not parallelise.** W16 collides
with W4 only via `tests/unit/test_risk_constant_pins.py:360`, so ship W16 first
and the collision disappears.

Before any parallel dispatch, assign centrally: **ADR numbers, `openapi.yaml`
ownership, the money constants, and `providers.py:320`.** Two orchestrators here
once both created ADR-0072, and each was green because neither could see the
other. A worktree isolates files; it does not isolate shared namespaces.

---

## W1 — what streaming actually changes

**Reuse, do not rewrite.** `_read_body_within_budget` (`providers.py:1880`) is the
**template** for deadline discipline, not the implementation: copy its
`deadline = monotonic() + budget`, `read1` returning after one `recv`, and
`settimeout(min(per_recv, remaining))` before each chunk.
`_extract_message_content`, `_extract_usage`,
`_finish_reason_indicates_truncation` and `_extract_citations` are **reused
unchanged** once deltas are reassembled — streamed frames carry
`choices[0].delta.content`, not `choices[0].message.content`.

**Do not re-litigate the error classification.** ADR-0077 already makes an
in-band error land correctly: an SSE body fails `json.loads` and hits the
catch-all, which returns `_DISPATCH_UNMEASURED`. A test asserting "an error
stream is possibly billed" **passes on `main` today, before any code exists** —
that is the vacuity rule 6b forbids. The only genuinely RED assertion is the
*clean*-stream one. Build the parser only.

**Keep** the `product_app.providers.urlopen` seam — 34 patch sites across 15 test
files depend on it. **Keep** `openrouter_call_budget_seconds = 60.0`: keep-alives
defeat the per-`recv` timeout once streaming lands, so the total budget becomes
the only wall-clock brake on a paid call.

Known frame shapes to design against: partial frames split across `read1`
boundaries; keep-alive comment lines (`: OPENROUTER PROCESSING` — counts of 1,
16, 16 and 21 per call measured, **cadence unsettled, do not assume one**); the
`data: [DONE]` sentinel; in-band error frames (`object: "chat.completion.chunk"`
with a top-level `error` and `finish_reason: "error"`); and usage in the final
chunk **with no opt-in required**. Preserve F-06 finding C — extract usage
**before** the `is_visible(content)` guard.

**ADR-0029's bar for adopting an SDK instead is two measured failed hand-rolled
attempts. There are currently zero. Record the attempts honestly** rather than
reaching for the SDK early or pretending the bar was met.

---

## STOP and ask

- Any **guardrail or money constant** whose value is not measured (W3, W8).
- **A published requirement.** Before moving any number,
  `grep -rn "<value>" docs/ src/product_app/templates/`.
  `quorum_run_deadline_seconds` looked like a knob and turned out to be
  **NFR-001, NFR-004 and AC-021**, published in six places including the operator
  dashboard — and **no gate covers that prose**.
- Anything needing **spend**.
- A **briefed premise turns out false** and the package's shape depends on it.
  Say so loudly; never repair it silently and carry on.
- **Two fixes in a row introduce defects** — change the approach.
- **The item is bigger than it looked.** Say so and stop; do not file and continue.

**Three open questions nobody has answered.** Do not guess them:

1. The demo plan names `readiness.py` in the sign-in item, but that module is the
   OpenRouter live-execution key probe and contains no session or account code.
   It most likely meant `auth.py` — confirm before scoping W7.
2. Whether `app.css`'s `.model-slot-grid` hard-codes a 2×2 template. It gates
   W4's UI effort and is still marked UNVERIFIED.
3. A `users` / `identities` table must go in a guarded `schema_migrations` block
   (the `feedback_store.py:369` idiom), **never** in `session_store._SCHEMA` —
   whose docstring records that adding a table there makes the first open of an
   existing read-only database raise.

---

## Gates, per package

Each exit status read **directly, never through a pipe** (rule 13f — a pipeline
returns the last command's status, measured: `make format-check | tail -3`
printed `Error 1` and exited **0**):

```bash
uv sync --all-extras --python 3.12          # a fresh worktree needs this first
make quality  > /tmp/q.log 2>&1; echo "EXIT=$?"
make validate > /tmp/v.log 2>&1; echo "EXIT=$?"
make diff-cover DIFF_BASE=origin/main       # COMMIT first — rule 15a
make api-contract && make openapi-check && make security-scan
# e2e per rule 13 if UI, specs or fixtures move:
#   lsof -ti tcp:18085 | xargs kill -9
#   cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 SESSION_MINT_CAP_OVERRIDE=600 \
#     npx playwright test <spec> --project=chromium --workers=1 --retries=0
```

Re-derive the required checks from branch protection, never from a list:
`gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'`.

**Mutation-prove every new test** against a green unmutated baseline, restoring
from a `cp` copy and confirming with `diff -q` — **never `git checkout`**, which
discards uncommitted work.

---

## Traps, all measured

1. **`make next` destroys the console** — 88 deletions, preserved in `stash@{0}`.
2. **A mutation run with a bad flag proves nothing.** `pytest-timeout` is absent;
   `--timeout` makes pytest error and every mutant look killed. Baseline first.
3. **An equivalent mutant is equivalent only for the input you chose.**
   `bytes(object())` raises, masking a missing guard; `bytes(5)` returns five
   zero bytes and the loop never ends. Vary the mechanism, not just the type.
4. **Replacing a stdlib call drops its guarantees silently.** `read()` raises
   `IncompleteRead` on a short `Content-Length`; `read1` returns `b""`. That
   shipped a truncated body as a complete, priced answer — and every test in the
   file held framing constant (`chunked`), so the suite was structurally blind.
5. **`TaskStop` kills the shell, not the `uv run` child.** A "stopped" suite kept
   running and corrupted the next one. Check `pgrep -f pytest` before re-running.
6. **A merge fires 3–5 deploy runs; most are cancelled by concurrency.**
   Enumerate every run for the SHA and read each Deploy **JOB**, never the
   rollup. `gh run list --commit <SHA>` can return `[]` before runs are created,
   so a "0 pending" wait-loop is **vacuously satisfied** — assert a run exists.
7. **`make close-guard` before every merge**, with the text in the ENVIRONMENT. A
   close keyword next to `#N` closes it, and GitHub cannot read negation.
8. **Never edit the tree while a gate or a read-only agent is running** (rule
   9a). `inspect.getsource` resolves by line number against the file on disk, so
   a concurrent edit produces a RED test in a file your diff never touched.
9. **GitHub Actions can wedge.** Check
   `curl -s https://www.githubstatus.com/api/v2/components.json` before blaming
   the diff; a `major_outage` leaves runs queued and un-rerunnable, and merging
   the next PR is what unsticks the deploy.

---

## Definition of done

Merged **and** verified running in production: the Deploy **job** reports
`success` (not the run rollup), `/status.build_sha` equals the merged SHA, and
the thing you built actually fires. **Where the third is impossible, say so
plainly** — with live execution off, most provider-path work is latent-correct,
covered by tests and mutants and by nothing observable. That is an honest report,
not a gap to paper over.

Then: local `main` fast-forward, delete the branch local **and** remote, remove
the dedicated worktree — worktree **first**, then the branch.

**Update `docs/65-open-work.md` in the same PR that changes an item's state.**
Once W0 ships, the gate will force it: a `PENDING` row whose symbol has appeared
goes red.
