# ultracode — Groups A and B, orchestrated

Paste this whole file as the first message of a fresh session. The word
`ultracode` on the first line is the opt-in that permits multi-agent
orchestration; without it the harness will refuse to fan out.

---

ultracode

You are the **main orchestrator**. You own the working tree, the git history,
and every gate. You do not write product code yourself and you do not delegate
the gates to a subagent — you run them and read their output.

Read `AGENTS.md` in full before anything else. It overrides this file wherever
they disagree. Then read
`docs/analysis/2026-08-10-open-issue-triage-by-execution.md`, which is the
triage this plan comes from.

## How this is structured, and why

Two work packages, run **strictly in sequence** (rule 17: one work package, one
pull request, merged before the next starts).

Each package is driven by **one `Workflow` invocation** that acts as the group
lead. The lead is a script, not an agent, because plan → build → verify →
review is deterministic control flow: encoding it in a script means no model
can skip or reorder a phase. Inside the script, `agent()` calls fan out.

Three rules constrain the fan, and they are not negotiable:

- **Fan out for review, never for building** (rule 9). Every build phase has
  exactly ONE sole tree-writer. Subagents share one working tree; parallel
  writers corrupt each other.
- **Two lenses, not five** (rule 10). Two reviewers ≈ four. The saving goes
  into *verifying* findings, not into more finders.
- **Reviewers are read-only** (rule 12a). Tell every reviewer **IN CAPITALS**
  not to write, edit, `git checkout`, `git stash`, or `sed -i` anything. A
  reviewer that must mutate source gets its own copy via
  `git archive HEAD | tar -x -C <dir>` (rule 12b).

## Merge authority — delegated

The repository owner has explicitly delegated rule 17b's approval to the main
orchestrator for these two packages. **You may push, open the pull request,
merge to `main`, and let the deploy run, on their behalf, without pausing.**

That authority is delegated, not unconditional. It covers Packages A and B as
scoped here and nothing else. **Merging also deploys to production** — no
workflow has a paths filter, so `build_sha` follows `main`'s tip after every
merge, including a docs-only one. So the preconditions below are the safety
mechanism that the human pause used to be, and every one is mechanical:

You may merge a package **only** when all of these are true, each evidenced by
output you have actually read:

1. every required status check from the live branch-protection API is green
   (Phase A6 — re-derive the list, do not trust a table);
2. every review finding is resolved or explicitly written down as a leftover;
3. the RED→GREEN mutation proof exists for every new test;
4. the branch is up to date with `main` and the merged tree was re-gated
   locally, diff-cover included (rule 17d — a clean auto-merge is not a
   correct merge).

If any one of those is not true, **stop and report instead of merging**. The
delegation is authority to proceed when the evidence is in, not permission to
proceed without it.

Escalate to the human — do not decide alone — if: a change turns out to touch
auth, secrets or spend limits beyond what is scoped here; a fix needs a
threshold lowered or a test deleted; the deploy verification fails after a
merge; or you hit either mandatory-stop condition at the end of this file.

Report after each package rather than before: what merged, the merge SHA, what
is verified running in production, and what was left open.

## Inherited facts — treat as ASSUMED until re-checked

Roughly half of what a handoff asserts does not survive contact with the tree
(rule 11). Each fact below names the command that produced it. Re-run the cheap
ones; do not build on any of them unverified.

| Fact | Command that produced it |
|---|---|
| `main` tip and production `build_sha` were equal at triage time | `git rev-parse origin/main` vs `curl -s https://quorum-ai.fly.dev/status` |
| A `#fragment` marker lands in `unverifiable`, same bucket as an off-run URL | executing `citation_marker_census` with positive and negative controls |
| Exactly one evaluation recompute per GET; `eval_json` is written and never read back | counting calls through `TestClient` on a real terminal run |
| Hostile input at the app's own 8000-char answer cap costs ~1.48 s per GET; ~3.10 s just under `_PARSE_LIMIT_CHARS` | `citation_marker_census` over 9 scopes, min of 3 runs, dev Mac |
| No log drain, no per-token columns in `runs`, Fly log ring ~100 lines | grep over `DEPLOY.md` and `run_history_store.py` |

---

# Package A — "the served evaluation is honest and cheap" (#285 + #284)

Both issues live in `_evaluation_projection` / `citation_marker_census`, both
were found reviewing #283, and both are exercised by the same tests. Clubbed
under rule 17g (shared narrow surface), not merely because both are small.

**Ordering is load-bearing: fix #285 BEFORE #284.** Serving a stored row while
the fragment bug is live would freeze the wrong number into the persisted row.
State this constraint in the builder's prompt.

Launch one `Workflow` whose `meta.name` is `group-a-served-evaluation`, with
these phases.

### Phase A0 — Recon (read-only fan, 3 agents, parallel)

1. **Call-graph agent.** Every caller, test and fixture touching
   `_normalize_url`, `_sanitize_source_url`, `citation_marker_census`,
   `_evaluation_projection`, `_evaluate_terminal_run`, and the
   `eval_json`/`trust_json` persistence path. Return file:line, not prose.
2. **Failure-mode agent.** Rule 16e: before writing code that touches a trust
   surface, enumerate how it fails — *first*, on one page, from research and
   from existing ADRs. Re-read ADR-0029 and ADR-0013 rather than reasoning
   around them. Cover at minimum: cache/stored-row staleness across a schema
   bump, URL shapes beyond fragments (query strings, trailing punctuation,
   percent-encoding, case), and what a wrong `schema_version` comparison does.
3. **Gate agent.** Re-derive the required merge contexts from the API — do NOT
   trust the table in `AGENTS.md`, which has been wrong twice:
   `gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'`
   Return each context and the local command that produces it.

### Phase A1 — Design panel (3 independent designs, then 1 judge)

Three agents, each given a different starting bias, each producing a complete
design for **both** issues:

- one that strips the fragment in `_normalize_url`;
- one that stops stripping it from source rows (and must confront the two
  documented security reasons in `_sanitize_source_url`'s docstring — the SPA
  route hash and `javascript:` smuggling);
- one that compares both sides in an explicit canonical shape without changing
  either existing function's contract.

Then one judge agent scores them and synthesises a single design, grafting the
best ideas from the runners-up. The judge must output:

- the chosen approach and why, **with the rejected alternatives and what each
  would cost** — this is the raw material for the ADR, which rule 16d requires
  **in the same PR** that makes the decision;
- for #284, the exact staleness rule (serve the stored row only when the run is
  terminal AND `schema_version` equals the current one; recompute otherwise);
- the RED test for each issue, named, with the one line saying what turns it
  red.

### Phase A2 — Build (ONE sole tree-writer, no fan)

A single agent, working in a dedicated `git worktree` (rule 17a), never the
main checkout. TDD, strictly:

1. Write the failing tests first and **capture the verbatim failure output**
   (rule 6a). "It failed" is not evidence; the message is.
2. Fix #285. Its test needs a **positive partner** proving a genuinely off-run
   URL still does not resolve (rule 7) — a fragment-resolves test alone would
   pass over an implementation that resolves everything.
3. Fix #284. Its test must assert **cardinality** — how many times the
   evaluation is computed across N reads — not merely that a read returns the
   right shape (rule 6b). A test that asserts only the served value passes
   against an implementation that still recomputes every time.
4. Write the ADR, regenerate the index with
   `python3 scripts/generate_adr_index.py`. Never hand-edit the index.

Traps to state in the builder's prompt:

- **Never `git checkout <file>`** to undo a mutation — it discards uncommitted
  work. `cp` aside and restore from the copy, verify with `diff -q` (rule 6).
- `make format` reformats test assertions and breaks `sed`-style anchors; grep
  for the real text before any programmatic edit (rule 16).
- Do not grow `goldenCompletedResp()` — it feeds a blocking visual lane that
  cannot be re-baselined on a Mac (rule 13d). Add a dedicated builder if a new
  shape is needed.

### Phase A3 — Bite-proof verification (fan of 3, read-only, own copies)

Each gets its **own** extracted copy (rule 12b) and reports a demonstrated
result, not an opinion:

1. **Mutation agent.** Revert each fix in its own copy; prove the matching test
   goes RED. Confirm the run actually executed — a mutation that breaks
   collection proves nothing.
2. **Vacuity agent.** For every new assertion, ask: *could this fail for ANY
   implementation?* Specifically attack the #284 cardinality test and the #285
   negative partner.
3. **Performance agent.** Re-measure the 9-scope cost after the fix, same
   method as the triage (min of 3, at the 8000-char cap and just under
   `_PARSE_LIMIT_CHARS`). Report the before/after table. If the per-GET cost is
   not bounded, that is a finding, not a footnote.

### Phase A4 — Adversarial review (2 lenses + 1 prose auditor)

Read-only, IN CAPITALS. Reviewers **refute by default** and report only
findings backed by a demonstrated failure (rule 12a).

1. **Correctness lens** — break the URL comparison. Query strings, trailing
   punctuation, percent-encoding, case, a fragment containing a second `#`,
   an empty fragment, a marker that is a bare fragment.
2. **Security lens** — the fragment strip exists for two documented reasons.
   Prove the fix does not reopen either. This is required: the change touches
   validation logic.
3. **Prose auditor** (rule 11a, verbatim in the prompt): *"for every number,
   superlative, and causal claim in the diff's comments, commit body and PR
   description, name the command that produces it — or mark it UNVERIFIED."*
   Six false claims shipped in one session when nobody was asked to do this,
   and every one of them was in prose, not code.

### Phase A5 — Verify findings, then one fixer

Fan an adversarial verifier per finding — prompted to **refute**, defaulting to
refuted when uncertain. Only findings that survive go to a **single** writer
who applies them. **Check the fix, not just the finding** (rule 11). Expect
your own fix to introduce a defect; budget a round for it (rule 12). Cap at
**two rounds**, then stop and escalate with the leftovers written down.

### Phase A6 — Gates (main orchestrator, not a subagent, serial)

```bash
uv sync --all-extras        # NOT --extra dev: schemathesis lives in `quality`
make quality && make validate
make api-contract
make openapi-check
make security-scan
git add -A && git commit    # COMMIT BEFORE diff-cover — rule 15a
make diff-cover DIFF_BASE=origin/main
```

Run `pytest` and `diff-cover` **serially** — the pytest-invoking targets rewrite
the shared coverage data `diff-cover` reads (rule 15). `make diff-cover`
measures `origin/main...HEAD` **plus the working tree**, so an uncommitted edit
makes it blame untouched code.

Then e2e, exactly as CI does or ~95 phantom failures appear (rule 13):

```bash
lsof -ti tcp:18085 | xargs -r kill -9
cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 SESSION_MINT_CAP_OVERRIDE=600 \
  npx playwright test <spec> --project=chromium --workers=1 --retries=0
```

Two local-only red herrings — neither is your diff:

- `ls e2e/tests/review/` — if it exists, `test_no_orphaned_e2e_specs` goes red
  locally and green in CI (rule 13a).
- The visual lane fails 8/8 on a Mac on clean `main`; darwin baselines are
  stale and CI compares linux ones. **Never `--update-snapshots`** to go green
  (rule 13e).

**Never lower a threshold, add `# pragma: no cover`, or delete a test to go
green.** If a line is genuinely untestable, say so with evidence.

### Phase A7 — Merge and close-out

Confirm the four merge preconditions above are met, then proceed on the owner's
behalf. In this order, no skipping and no reordering (rule 18a):

1. merge with an explicit message —
   `gh pr merge --squash --subject "..." --body "..."`. A bare `--squash`
   concatenates every intermediate commit body onto `main`.
   **Do not write "not fixed: #N" in a body** — GitHub closes on the keyword
   and ignores the negation.
2. Verify the deploy three ways (rule 18): the deploy **job** ran (not
   `skipped`/`cancelled` — read the job, not the run's rollup), `/status.build_sha`
   equals the merged SHA, and the fixed behaviour actually fires. A merge
   produces two runs and one is cancelled by concurrency dedupe — resolve the
   **newest run by `createdAt`**.
3. `git branch -f main origin/main` (the local ref does not follow).
4. Delete the merged branch, local and remote; remove the worktree.

Probe production only where it is free: `/ready`, `/status`, `/metrics`,
`/ui/ops`, `/estimate`. A full run is not free.

Report back to yourself in one block: what merged, what is verified running,
what was left open.

---

# Package B — "measure production before deciding" (#105 + #268 + #203)

Start only after A is merged and verified running.

**Read this before planning: Package B does not close its three issues.** It
ships the telemetry that makes them decidable. Any agent that proposes closing
#105, #268 or #203 in this PR has misread the task — all three are blocked on
data that does not exist yet, and a classification changed on a guess is the
exact failure mode #180 cost three broken attempts to learn.

Verified blockers: no log drain (`DEPLOY.md` lists it as future work), no
per-token columns in `run_history_store`'s `runs` table, Fly's log ring holds
~100 lines.

Launch one `Workflow` named `group-b-production-telemetry`. Same phase shape as
A, with these differences.

### The design phase matters more than the build phase

Fan the design panel wider here and the build stays one writer. The three
things to instrument:

- **#105** — HTTP status on the 5xx branch, plus whether the error body carries
  `error.metadata.provider_name`. Log the **shape**, not the content.
- **#268** — per-call input-token counts, durably, so the assumed constants
  (`cost_system_prompt_tokens` 350, `cost_web_search_context_tokens` 2000) can
  be compared against reality.
- **#203** — the response shape of a 403 on this deployment's actual egress
  path. This one may need operator input on what intermediaries exist; if so,
  say so and stop rather than guessing.

### Three constraints specific to this package

1. **Go and look at the upstream before gating on it** (rule 8c). A previous
   fix bounded a body read by requiring `Content-Length`; correct on loopback,
   green on every gate, and worthless in production because OpenRouter sits
   behind Cloudflare and answers errors with `Transfer-Encoding: chunked` and
   no `Content-Length`. One free `curl` — a bad key gives
   `401 {"error":{"message":"User not found.","code":401}}` with no
   `error.metadata` — found it in seconds.
2. **A security lens is mandatory**, not optional. Telemetry that logs request
   or error bodies is the single easiest way to leak a key into a log. The
   reviewer's explicit job is to find the leak. Cross-check
   `scripts/security_scan.py`, and note CI's `--cov=src` does not see helper
   scripts, so a behavioural change there still needs its own test.
3. **The `HTTPError` doubles in this repo have an EMPTY body and do not say
   so** (rule 8a). Both `_http_error` helpers pass `fp=None`, so `.read()`
   returns `b''` — any test asserting "the error body does not contain X"
   against them passes **vacuously, against every implementation, including one
   that never reads the body**. This bites #105 and #203 identically. Give every
   such test a REAL body and a positive partner proving the present case is
   detected.

### Close-out for B

Same gates, same four merge preconditions, same rule-18 deploy verification.
Then, explicitly:

- Post a comment on #105, #268 and #203 saying what is now instrumented and
  **what reading will settle each one** — do not close any of them.
- Record the decision as an ADR (rule 16d): what is logged, what is
  deliberately not, and the removal condition.

---

## Scale, and when to stop

Roughly 12–15 agents per package. That is the session default and it is enough:
the fan buys diverse lenses, not volume. If a phase wants more than that, the
phase is probably two phases.

**Mandatory stops** — in each case, stop and report rather than working around:

- A premise you were handed turns out to be false (rule 3). Say so; never
  repair it silently and carry on.
- Two fixes in a row add defects — change the approach, do not iterate again.
- A higher-ranked item surfaces mid-work (rule 20). Park the branch, re-run
  selection, record it.
- An item is bigger than it looked (rule 19). Say so and stop; do not file a
  new issue and continue.

**Hermetic and $0 throughout** (rule 17f). No paid API calls for routine
checks, no secret rotation, no paid runs. Never fabricate a number, a label or
a baseline — flag the gap instead.
