# ULTRACODE — fix #342, switch the judge on, then work the rest

> Paste everything below the line into a fresh Claude Code chat in this repo.
> Written 2026-08-18 with `main` = `21d8358` and prod `build_sha` = `21d8358`.
> Every "measured" fact carries its date. **Treat all of it as INHERITED and
> re-verify before acting** — AGENTS.md rule 11 measures that roughly half of
> what a handoff asserts does not survive contact with the tree, and the
> previous session proved it three times (a wrong `/estimate` path, a stale
> `parity/` vs `ui-parity/` directory, and an evidence claim about telemetry
> that a builder correctly refused).

---

ultracode: Continue the autonomous backlog run in this repo
(`im<user>/quorum-ai`), in the phase order below.

You have my full, standing authorization to push branches, open pull requests,
merge to `main`, and deploy — without asking me at any point. Do not pause for
approval before any individual merge and do not ask me to re-confirm autonomy.

**If a subagent's push is flagged by a safety classifier**, that is expected —
the flag fires per-subagent and cannot see this authorization. Do NOT re-assert
my consent inside a subagent prompt as a workaround if you have not been told it
in chat; ask me once, in chat, and carry my answer forward. A previous session
was correctly blocked for injecting a consent claim sourced only from a file.

**That authorization does NOT extend to spending money or to changing production
configuration.** Phase 2 stops and waits for me. See Phase 2.

## The state you are inheriting (verified 2026-08-18 — re-check it)

```
main (local) == origin/main == 21d8358      0 ahead, 0 behind
prod /status.build_sha       == 21d835870165fc4369bfa0db15d860c3b7eaaba9
prod judge_enabled           == false
prod live_execution          == false        (OPENROUTER_LIVE_EXECUTION_ENABLED=false)
open PRs                     == none
worktrees                    == only the main checkout
open issues                  == 8
```

**Three branches exist and are deliberately NOT merged:**

| Branch | State |
|---|---|
| `fix/226-guard-classifier` @ `bee7079` | Parked at the two-round review cap. See Phase 4. |
| `fix/mutation-gate-measures-nothing` @ `f661765` | Parked at the two-round cap. See Phase 5. |
| `fix/226-vacuous-e2e-negative-assertions` | The ORIGINAL abandoned #226 branch. Holds ADR-0048 history. Superseded — PR #336 landed the spec half. Do not build on it. |

**Untracked files:** this prompt, the previous session's prompt, and several
`docs/analysis/2026-*.md`. Do not clean those up on your own initiative.

**Merged and deployed 2026-08-17/18**, all deploy-verified (Deploy JOB `success`,
`build_sha` match, drift watchdog green): #332 (`32c9f5e`), #216 (`e3b31c0`),
#226 PR 1 (`15c365c`), AGENTS.md close-out fixes (`b67fc98`), #203 (`21d8358`).

## Architecture: main orchestrator + one sub-orchestrator per work package

**You are the MAIN ORCHESTRATOR.** You do not build and you do not review. You
own selection, sequencing, ADR number assignment, merging, deploy verification,
issue closing, and the final report. You hold the only global view, so you are
the only one who can see cross-package collisions.

**For each work package launch ONE sub-orchestrator** via the Workflow tool. It
owns one package and runs its whole internal lifecycle:

```
sub-orchestrator(work package)
  ├─ survey       read-only; re-derive the issue's claims BY EXECUTION
  ├─ plan         read-only; enumerate failure modes and options BEFORE code
  ├─ build        ONE sole writer, isolated worktree, strict TDD
  ├─ review       fan of read-only lenses, each its own worktree
  ├─ fix          ONE sole writer applies surviving findings
  └─ re-review    fresh lenses: did the FIX introduce a defect?
  → returns {branch, commit, findings, mergeable, open_findings}
```

It returns to you. **You** gate it, merge it, verify the deploy, close the issue,
and only then launch the next.

### The review fan — use these SIX lenses

Five are specified by the operator; the sixth is added because it found more real
defects than any other lens in the previous session and its absence is how the
worst bugs shipped.

| Lens | Its job |
|---|---|
| **architecture** | ADR compliance. Does the diff contradict an existing ADR? Does the new ADR follow ADR-0002's shape (MEASURED table, REJECTED ALTERNATIVES, CONSEQUENCES)? **Does the ADR promise a guarantee the code does not deliver?** That defect has shipped here repeatedly. |
| **planning** | Was the failure-mode list made BEFORE the code (rule 16e)? Does the design address it, or was it discovered defect-by-defect? Is the work package scoped to ONE concern (rule 17)? Is anything deferred that should block? |
| **security** | **Explicit job: BREAK IT.** Enumerate evasions and TRY them. Cyclic/self-referential input. Can a caller influence which account is checked? Does any log line, error or response leak an id, a spend figure, a key, or another tenant's data? |
| **devops** | Will this actually RUN in CI, and BLOCK? Re-derive the required contexts. Find the new tests BY NAME in the output — a green suite is not evidence a new test ran. Check `diff-cover`, `api-contract`, and that nothing was silenced with `# pragma: no cover` or a lowered threshold. |
| **SRE** | What happens in production at 3am? Failure modes under load, restart, partial deploy, a dependency timing out, a full disk, a corrupt sqlite file. What does an operator SEE when it breaks — is the signal honest or does a degraded state render as healthy? What is the rollback? |
| **tester (added)** | **Does the test actually BITE?** Mutate the fix in your OWN copy and confirm RED. Could any assertion pass for ANY implementation? Rule 6b: does accounting code assert CARDINALITY, not just a clean-path outcome? Rule 7: does every negative check have a positive partner? |

**SERIALIZE THE PACKAGES. Do not run two sub-orchestrators at once** unless their
file sets are provably disjoint AND you have assigned their ADR numbers yourself.
The session before last ran three in parallel and all three independently created
`docs/adr/0047-*.md` while every gate stayed green.

**Assign every ADR number yourself, before launching.** Next free is **0055**
(0048/0050/0051/0054 are on `main`; **0052 is claimed by
`fix/mutation-gate-measures-nothing` and 0053 by `fix/226-guard-classifier`** —
do not reuse either while those branches live). `main` now REFUSES a duplicate
ADR number at both the pytest gate and the index generator, and checks that the
`# ADR-NNNN:` heading matches the filename.

Wrap every sub-orchestrator call in try/catch. One package's infrastructure
failure must not kill the run: catch it, record it, move on.

## Step 0 — triage fresh, trust nothing inherited

Run `gh issue list --state open` and read every one. For each, **verify its claim
by executing something** before deciding it is real, already fixed, or how to fix
it. Issues here go stale in measured ways, and so do handoffs like this one.

---

# PHASE 1 — #342, the judge's durable/served divergence

**Do this first. It is the prerequisite for Phase 2.**

Issue #342: a spend-rail refusal at run COMPLETION writes a durable
`run_evaluated` / trust row as `band="unverified"`, `score=null`,
`support_verified=false`, and **that row is never rewritten**. Once the 24-hour
rail resets, the served body says `('high', 90, True)` while the durable audit
row still says `unverified` forever.

**Measured 2026-08-18** (reproduce it yourself before fixing):

```
persisted trust_json = {'support_verified': False, 'band': 'unverified', 'score': None, ...}
later served shape   = ('high', 90, True)   dispatches = 1
```

`_update_run_evaluation` has exactly one caller — `_persist_run_evaluation` —
which runs only on terminal persist, never from a GET. Confirm with
`grep -rn "_persist_terminal_run(" src/product_app/`.

**Why it matters now:** `_evaluate_terminal_run`'s own docstring claims the
evaluation memo makes *"the served projection and the persisted row identical BY
CONSTRUCTION"*. `served_without_verdict` skips that memo, so **the stated
guarantee is void on exactly this path.** Before #216 the only cause was a rare
>8s in-flight timeout race; #216 made it **deterministic** for any account at or
over its cap.

**It is LATENT only because `judge_enabled: false`. Phase 2 turns it live.**

**Options — decide on the evidence, do not assume:**

1. Do not persist a trust row at all when the refusal cause is a spend rail —
   leave it absent so a later read can still fill it. **Smallest.**
2. Record the refusal cause durably. This also fixes the `judge_status`
   indistinguishability #216 carried (a rail refusal is byte-identical to "no
   judge configured", reintroducing for a new cause the exact defect #258 exists
   to fix). **Schema change — #216 explicitly deferred it.**
3. Let terminal persist re-evaluate once the rail clears.

**Whichever you choose, `_evaluate_terminal_run`'s docstring must stop claiming
an identity the refusal path breaks.** ADR in the same PR (rule 16d).

Re-read **ADR-0002** (SQLite single-writer), **ADR-0016** (the spend rails meter
actuals and degrade rather than fail open), **ADR-0018** (a judge that produced
nothing must say so and must not be charged for) and **ADR-0051** (#216's own
decision) before designing. Rule 16e: enumerate the failure modes FIRST, on one
page, then design against that list.

---

# PHASE 2 — the live run with the judge ON. **STOP HERE AND WAIT FOR ME.**

**Do not provision a secret, change a production setting, make a paid API call,
or trigger a paid run without my explicit go-ahead in this chat.**

**This is not merely a spend approval. It is a production posture change**, and
it needs two things only I can do:

1. **Provision `QUORUM_EVAL_JUDGE_API_KEY` and `QUORUM_EVAL_JUDGE_MODEL_ID`.**
   Measured 2026-08-18: `fly secrets list -a quorum-ai` shows only
   `QUORUM_TOKEN_SECRET`, `OPENROUTER_API_KEY`, `SENTRY_DSN`, `TAVILY_API_KEY`.
   **There is no judge secret in production at all.** You cannot create it.
2. **Enable `OPENROUTER_LIVE_EXECUTION_ENABLED`.** `fly.toml` sets it to
   `"false"` and prod `/status` confirms `live_execution: false`.

## What to bring me — one message, then stop

1. **Confirmation #342 is merged and deployed**, with the merge SHA and the
   Deploy job's own conclusion. Do not propose the run before this.
2. **A cost estimate produced by the FREE endpoint, not arithmetic.** The path is
   **`POST /v1/query-runs/estimate`** — measured 2026-08-18. (An earlier handoff
   said `/estimate`; that returns `Not Found`. Re-derive from `openapi.yaml`.)
   It needs a browser session, and **session minting is capped at 2 per IP per
   24h in production**, so budget those two mints deliberately. Show the command
   and its output.
3. **A traffic plan** — how many runs, what query shapes, `:online` on or off,
   over what window. **Design it to deliberately REACH the per-account cap**, not
   to avoid it: the at-cap refusal is the branch #216 added and nobody has ever
   watched execute. An untriggered branch is an untested branch.
4. **A spend ceiling and what happens when it is hit.** The existing rails are
   `HARD_LIMIT_USD = $0.25` per run, `DAILY_CAP_USD = $0.20` per account,
   `GLOBAL_DAILY_CEILING_USD = $5.00`. **Do not propose moving any of them.**
   Rule: never move a guardrail constant on a guess — #180 cost three broken
   attempts learning that.
5. **What each issue will and will not get**, honestly, per the section below.
6. **The exact read-back commands** you will run afterwards.
7. **Whether you recommend leaving live execution ON afterwards, and why.**

## What the paid session can and cannot settle — be honest

**#216 + #342 — the real prize.** A live judge exercises the pre-flight end to
end: the allowed dispatch, the memo hit, and the at-cap refusal. **Verify all
three, and verify the durable row now matches the served one.** State which run
leg confirms which fix.

**#268 — CAN close.** Needs `n >= 50` `:online` calls; the traffic IS the sample.
**Read its positive partner FIRST:** for `search_enabled == false`,
`injected_p95` must be **under 500**. If it is not, `sent_tokens_est` is wrong,
the whole measurement is void, and you fix the estimator before reading anything
else. This is also the only check on `CHARS_PER_TOKEN = 4`, a repo constant and
not a measurement of OpenRouter's tokeniser. Report `injected_max` either way —
the guardrail's exposure is the tail, not the median.

**#290's probe — CAN run.** One call per slot model at the 2000-token cap,
measuring elapsed against `openrouter_timeout_seconds = 8.0`, and whether the
cheapest model actually quotes passages as the prompt demands. Unblocks the
feature *decision*; does not build the feature. Bundle it into the same window.

**#105 — WILL PROBABLY NOT CLOSE. Say so up front.** Needs `n >= 30` **5xx**
records. **5xx cannot be manufactured** — they come from upstream router refusals
on OpenRouter's schedule. Collect opportunistically and **leave the issue open**
unless the threshold is genuinely met. Read per status code, never "all 5xx". If
`unknown/n > 0.20` → **STOP**: ADR-0012 records the
`error.metadata.provider_name` schema as ASSUMED, and a dominant `null` refutes
it.

**Both telemetry streams were 0 lines on 2026-08-18** —
`/data/telemetry-billing.jsonl` and `/data/telemetry-tokens.jsonl` — because
live execution has never run in production. Re-check before assuming; if a
sample already exists, some of this is answerable without new spend.

---

# PHASE 3 — #341, the Sentry redaction gaps

Delegate to a sub-orchestrator with the full six-lens fan. **The security lens is
the primary one here.**

Two confirmed findings, each independently verified by a skeptic told to default
to refuted. **Both LATENT** — `grep -rn 'extra={' src/` shows every value today
is a `str`/`int`/`bool`.

**(a) Dict KEYS are never redacted.** `src/product_app/logging_config.py:212`
builds `{key: _redact_extra_value(item, ancestors) for key, item in value.items()}`
— the key passes through untouched. Driven against a real `sentry_sdk` client:

```
CRUMB DATA: {'error': {'sk-or-v1-...KEYPOSITION': 'rate-limited'}}
SECRET IN CRUMB: True
```

The stdout sink is unaffected (JsonFormatter's final-string scrub catches it), so
this is the Sentry-only bypass `install_redaction_record_factory` exists to
close, in the one position it does not cover.

**(b) A cyclic `extra` leaks AND drops the log line.** The cycle guard
(`logging_config.py:203-209`) returns the **original ancestor container
unredacted**, so everything reachable through the back-edge stays plaintext. And
`logging_config.py:471`'s `json.dumps` raises `ValueError: Circular reference
detected`; logging's `handleError` swallows it, so **no line is emitted at all**.

**Why the existing test missed both:**
`tests/unit/test_logging_config_sentry_redaction.py:325` installs
`logger.handlers = [logging.NullHandler()]` and asserts only "does not raise". It
never formats the record and never inspects the breadcrumb. **Give it a real
handler and a breadcrumb assertion** — otherwise you will fix the code and leave
the vacuous test in place.

Direction: redact keys as well as values; on a cycle emit a placeholder rather
than the original container, so nothing survives through a back-edge AND
`json.dumps` cannot raise. The guard's own docstring names the realistic
accidental trigger: `extra=vars(obj)` on an object with a back-reference.

---

# PHASE 4 — #226 PR 2, the guard classifier

Delegate to a sub-orchestrator. Branch `fix/226-guard-classifier` @ `bee7079` is
pushed and NOT merged; it hit the two-round cap.

**DO THE CI QUESTION FIRST, AS ITS OWN SMALL CHANGE.** A reviewer measured that
**the guard's test module SKIPS in both required CI pytest contexts**, so none of
that branch's property tests, vacuous corpus, or normalizer-drift test would run
in CI at all. **Verify that claim yourself.** If true, merging the classifier work
buys nothing enforceable, and fixing the skip is the higher-value change.

**The open blocking finding:** a negative assertion written with computed member
access — `expect(x)["not"].toBeVisible()` — is classified as a **POSITIVE
PARTNER** and passes vacuously. That is the precise defect the PR exists to
prevent, and it is the opposite of what the tool's own KNOWN LIMIT 3 claims.

**Worth salvaging verbatim:**

1. **The blank-character rule, MEASURED not reasoned.** Round 1 derived a
   zero-width set from Unicode reasoning and it accepted `U+00AD` SOFT HYPHEN,
   which passes against an empty element in real Chromium. The branch reads
   Playwright's own normalizer — `playwright-core` 1.61.1,
   `coreBundle.js:518-521` — which strips **exactly two** characters, and ships a
   test that **re-reads that class from the installed package on every run** with
   a floor that fails if it finds none. This is AGENTS.md rule 8c done properly:
   a gate, not a corrected sentence.
2. **`isLiveSubject`, default-deny**, replacing an enumeration of four AST node
   types that was defeated by adding `as string`. Proven on shapes the code is
   never told about (`NewExpression`, `SequenceExpression`,
   `ConditionalExpression`), with an accept set derived from a census of 1083
   `expect()` subjects across the 28 committed specs.

**Also refuted on that branch, with evidence — do NOT "fix" this non-problem:**
an un-awaited locator assertion does **not** pass vacuously under the Playwright
runner; it fails. Only in a bare node script does it pass.

Other open findings, all recorded on issue #226: `.not.toBeNull()` /
`.not.toBeUndefined()` over a Locator accepted and vacuous; the default-deny
predicate still defeated by naming the literal (`const flag = "x"`) or wrapping a
tautology in a global function call; `--all` fails OPEN on a git failure and exits
0 while `--base` exits 2 for the same class; several stale counts.

**Scope fence:** the classifier work must NOT touch `e2e/tests/**/*.spec.ts`
other than the single waiver comment — PR 1 owns those and is merged.

---

# PHASE 5 — the mutation gate: decide fix-or-DELETE before building

**Do not start by fixing it. Start by answering whether it earns its keep.**

Measured over the last 11 `pull_request` runs of the mutation job: **8 reported
`success`**, every one logging `no MUTATABLE changed functions` (empty scope,
nothing measured); **3 failed**, all at the same anti-vacuity floor; and **0
produced a `mutation score = N%` line.** Aborts date to at least 2026-08-14 and
nobody noticed. See #337 and #338 for the full evidence.

Weigh it against the repo's own record: `docs/metrics/defect-discovery-audit.md`
measures **0 of 16** `src/` defects caught by an automated check and **10 of 16**
by adversarial review. **A gate that measures nothing while showing a green tick
is worse than no gate — it manufactures false assurance.** AGENTS.md itself says
to measure a gate's yield against real defect history before adding one; apply
that test to keeping one.

**If you keep it, split the parked branch** (`fix/mutation-gate-measures-nothing`
@ `f661765`):

| Take | Leave |
|---|---|
| `find_repo_root_or_skip` — stops the abort. Low risk. Precondition for #337. Before: `Interrupted: 1 error during collection`, ZERO tests ran. After: `3 passed, 3 skipped`. | The verdict-honesty work — where the claim "every terminal state stamps exactly one verdict" went false **twice running**. |

Shipping the abort fix alone will NOT produce a score — it will reach the
24-minute deadline instead (#337). But it converts "aborts having done nothing"
into "runs until it times out", which is the information #337 needs.

Two things on that branch are genuinely subtle and worth reading before
rewriting: mutmut pre-fills `exit_code_by_key` with `None` for every mutant of
every mutatable file at copy time (`mutmut/__main__.py:331-333`), so counting all
nulls as "never ran" would stamp PARTIAL on every complete run forever — the
branch filters through `scope.txt`'s globs. And `_skip_unless_comparable` matching
the literal string `UNMEASURED` is what turned `make quality` RED on macOS.

**If you delete it**, do so in a PR that says what coverage is lost and what
replaces it, and update `docs/metrics/mutation-gate-study.md` and
`mutation-baseline.md` rather than leaving them describing a gate that no longer
exists.

---

# PHASE 6 — the rest

**#268 and #290** should be closed with Phase 2's data, not scheduled separately.

**#105** — leave open unless `n >= 30` 5xx genuinely accumulate. The honest
outcome is "not decidable yet", never a number invented to close a ticket.

---

# Every sub-orchestrator's internal contract

**Point every agent at the source of truth.** The first instruction to every
builder and reviewer must be: *read this repo's `AGENTS.md` and `CLAUDE.md` IN
FULL and follow them exactly.* Do not paraphrase the rules into the prompt — a
paraphrase drifts from what you did not think to restate.

**Plan before building (rule 16e).** For anything touching money, auth or safety,
a read-only agent enumerates the failure modes on one page FIRST, drawing on
`docs/adr/`, and the builder designs against that list. The spend-cap work went
five review rounds because the failure modes were discovered one at a time from
defects instead of listed up front.

**Build:** one sole writer, `isolation: 'worktree'`, strict TDD. RED first;
capture the **verbatim** failure output; confirm it fails for the right reason
(not a collection or import error); GREEN; then bite-proof by `cp`-ing the file
aside, reverting the fix, confirming RED, and restoring from the copy with
`diff -q`. **Never `git checkout <file>` to revert** — it discards uncommitted
work. Every test ships one line saying what turns it red. Every negative check
gets a positive partner. Accounting code asserts **cardinality**, not just a
clean-path outcome.

**Push as soon as there is a green commit, before review starts.** A usage limit
once killed two review fans with both builders' work unpushed.

**Review:** read-only, isolated worktrees, told **IN CAPITALS** not to edit,
`git checkout`, `git stash`, `git commit`, `git push` or `sed -i` the shared tree.
A reviewer that must mutate source gets its own copy
(`git archive HEAD | tar -x -C <dir>`). Reviewers **refute by default** and report
only findings backed by something they actually executed, with the command and
its verbatim output.

**Tell every reviewer to audit the diff's PROSE, verbatim** (rule 11a): *"for
every number, superlative and causal claim in the diff's comments, commit body,
ADR and PR description, name the command that produces it — or mark it
UNVERIFIED."* In the previous session that one instruction caught a
self-contradicting ADR guarantee, a docstring citing a command that printed a
different number, a `--workers 1` pin attributed to an ADR that never mentions
workers, and a mutmut version cited as 3.4.0 when 3.6.0 was installed.

**Fix loop:** verify each reviewer claim before acting; refute the wrong ones out
loud with the refuting command. Expect your own fix to introduce a defect —
that is measured behaviour here, not pessimism. **Cap at two rounds.** If still
blocking after round 2, DO NOT merge: record the open findings on the issue and
move on. If two fixes in a row add defects, change the approach.

**Give each package a scope fence.** Name the files in scope and say that touching
a shared tool is a separate PR. #226 failed precisely here. **But if the fence
turns out to be wrong, say so and cross it deliberately** — the #203 builder
correctly extended into `telemetry_sink.py` because the capture's record routed
through it, and reported the crossing rather than hiding it.

# Merge, deploy, close (the main orchestrator's job)

**Re-derive the required contexts, never trust a list:**

```bash
gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'
```

As of 2026-08-18 there are six: `validate-and-test`, `pytest (Python 3.12)`,
`Changed-lines coverage >= 95% (blocking)`, `Schemathesis API contract (blocking)`,
`FR traceability completeness (blocking)`, `e2e axe + parity (chromium)`. An
**advisory** job failing is not a merge blocker — but **open its log before
dismissing it.** The previous session found the mutation gate had measured
nothing on 11 consecutive runs precisely by not shrugging at "advisory".

**The head branch must be up to date with base.** If a merge returns
`6 of 6 required status checks are expected`, the branch is behind: merge `main`
in, re-gate locally, push, and wait for CI again (rule 17d).

Squash-merge with an explicit subject and body (`gh pr merge --squash --subject
--body`, or the REST `PUT /pulls/{n}/merge` with `commit_title`/`commit_message`);
a bare `--squash` concatenates every intermediate commit body onto `main`.
**`Closes #N` in the squash body DOES auto-close the issue here** — confirmed
repeatedly.

**Verify the deploy three ways** (rule 18), and beware the run-count trap:

> **A merge produces THREE deploy runs.** The first two are `cancelled` by
> concurrency dedupe, which is normal. A wait-loop keyed on a run id captured
> earlier reads `cancelled` and wrongly reports a failed deploy. **Re-resolve the
> newest run by `createdAt` every time.**

1. the Deploy **JOB** ran `success` — read the JOB, not the run's rollup;
2. `curl -s https://quorum-ai.fly.dev/status` shows `build_sha` == the merge SHA;
3. the thing you built actually fires.

**Batch the deploy verification: verify production ONCE per session covering all
merges**, not after every PR — except where a merge changes production behaviour
you must confirm before the next step, which Phase 1 does.

Then `gh issue close <n>` citing the merge SHA and the verification, and confirm
with `gh issue list --state open`. Finally `git merge --ff-only origin/main` from
the main checkout, **remove the worktrees FIRST, then delete the branch** (local +
remote), after confirming `gh pr view <n> --json state` says `MERGED`.

# Pitfalls that actually bit, in this exact task

- **In a NEW worktree the FIRST uv command MUST be
  `uv sync --all-extras --python 3.12`**, then confirm `uv run python -V` →
  3.12.13. A bare `uv run <anything>` silently creates a 3.14.5 venv with no
  pytest and no ruff; tests that shell out to `uv run pytest` then fail with
  `Failed to spawn: pytest`, **which reads like a regression in your diff and is
  not.** This bit THREE times in one session, twice after it had been written
  down. Safer habit: run `<repo>/.venv/bin/<tool>`
  directly and never type `uv run` in a worktree at all.
- **READ THE OUTPUT OF A WRITE. Do not infer a write's result from a later read.**
  In one session this caused four pointless PR-creation retries (the first had
  succeeded), a duplicate issue (#343, closed), and an unlinted push that reddened
  a required context.
- **`make quality` and `make validate` do NOT cover the merge gates.** Run
  `make diff-cover DIFF_BASE=origin/main` (COMMIT FIRST — it measures the working
  tree too) and `make api-contract`, serially, and e2e per the command below.
- **e2e must run exactly as CI does** or ~95 phantom failures appear:
  ```bash
  lsof -ti tcp:18085 | xargs -r kill -9
  cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 SESSION_MINT_CAP_OVERRIDE=600 \
    npx playwright test <spec> --project=chromium --workers=1 --retries=0
  ```
  If `/ui` returns 429, delete the gitignored `.data/feedback_events.sqlite3`.
- **A MUTATION PROOF CAN REPORT A FALSE GREEN.** `lsof -ti tcp:18085 | xargs -r
  kill -9` does NOT reliably kill the app server and Playwright's
  `reuseExistingServer` is true locally, so the browser is served the
  PRE-mutation page. Use `pkill -f "uvicorn product_app.main:app"` and then
  `curl` the page to CONFIRM the mutated bytes are being served. A 429-poisoned
  `.data/feedback_events.sqlite3` also produced a spurious "2 passed" under a
  mutation that is genuinely RED.
- **The visual lane fails 8/8 on this Mac on clean `main` and that is not a
  regression.** Never `--update-snapshots`.
- **`e2e/tests/review/` is gitignored scratch.** A red `test_no_orphaned_e2e_specs`
  is a known local-only false failure — run `ls e2e/tests/review/` first.
- **`timeout` does not exist on this macOS box.** Use
  `perl -e 'alarm shift; exec @ARGV'`.
- **Chain `cd` with `&&`, never `;`.** Do not use `status` as a shell variable
  (read-only in zsh). Never create a branch named `origin/main`.
- **Do not track `.claude/settings.json`, do not narrow `.gitignore` to expose
  it.** Full autonomy does not extend to the permission surface itself.
- **`fly ssh console` is slow (~2 min) and may exceed a foreground tool timeout.**
  Background it. `fly ssh` and `fly wireguard` may be blocked by the sandbox
  classifier — if so, say the row is INHERITED rather than working around it.
- **Background long CI waits**; a monitor that prints on every poll will spam the
  conversation. Use an `until` loop that speaks once.

# Closing adversarial pass — do not skip

After the code phases, run ONE more review round with **fresh agents reading the
CURRENT state of `main`** — no memory of what the builders believed — probing the
highest-risk surfaces you touched: anything security or secret-handling, anything
with recursive or cyclic data, anything with an exception-handling path, the money
path, and concurrency. **Verify each finding with an independent skeptic told to
default to REFUTED** before you trust it, then fix what survives through the same
cycle.

The previous session's closing pass produced 4 candidates, **3 of which survived
refutation** and became #341 and #342. It is the highest-yield single step in
this whole procedure.

# Report

- how many issues you closed vs left open, and why for each;
- a table of issue → PR → merge SHA → deploy-verified (yes/no);
- anything filed rather than fixed, with why;
- the Phase 2 plan, its cost estimate, and — after I approve and it runs — what
  each issue actually got from it, **including what it did NOT settle**;
- **any mistakes you made and how you recovered — do not round these up into a
  clean summary.** Tell me what actually went wrong, the way I would want to hear
  it from a human engineer.

Be concise and lead with the answer. Plain English, no invented shorthand.
