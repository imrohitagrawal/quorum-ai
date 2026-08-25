# Product Repository Instructions

This repository was generated from Codex Product Factory Enterprise Edition.

## Operating rules — read these first

Placed first deliberately: instruction-following degrades as instruction count
rises, and earlier instructions are measurably better followed than later ones
(IFScale, arXiv:2507.11538). These are the non-negotiables. The reasoning behind
each one lives in `docs/evidence/` and `docs/103-incident-learnings.md`; this list
is the rule only.

**Truth**
1. **Verify by executing, never by reading.** State the command and what it
   printed, or say UNVERIFIED out loud. **This includes claims about WHERE
   something is, not only about what it does** — "this file says X" is a claim,
   and `grep` is the command that settles it.
   Measured 2026-08-04, on a list of **three** stale items in this very file,
   written by an agent that had just spent a session applying this rule:
   one was real, one named a file that did not contain the text at all (the
   location was recalled, not grepped), and one was already correct and would
   have been "fixed" into being wrong. **Two of three evaporated on contact with
   a command.** Assume your own list is the same until you have run it.
1a. **Prefer a check over a corrected sentence.** The same session found
   `AGENTS.md` claiming a directory held "twelve" specs when it held 15 — three
   were added over months and nothing ever failed, because nothing compared the
   sentence to the tree. A corrected number lasts until the next change; a gate
   lasts. Where a number is derivable from the repo OFFLINE, pin it:
   `tests/test_doc_gate_consistency.py` Part D is the worked example, and the
   place to add the next one. Numbers that need the network (the rule-14
   contexts table) cannot be pinned this way and stay a human step.
2. **A green advisory job is not evidence it ran; a RED one is not evidence it
   measured.** Open the log and find the number.
3. **If a premise you were handed turns out to be false, STOP and say so.** Never
   repair it silently and carry on.
4. **When you CORRECT a false claim, verify the REPLACEMENT before writing it.**
   Three review rounds here caught rewrites that were themselves false — one told
   an operator a money-losing fault was benign. Prefer narrow hedged wording
   ("no workflow sets it") over absolutes ("set nowhere else").
5. **Plain English. No jargon, no invented shorthand.**

**Tests**
6. **Every test ships with one line saying what turns it red.** Prove it by
   mutation: `cp` the file aside, mutate, restore from the copy, verify with
   `diff -q`. **Never `git checkout <file>`** — it discards uncommitted work.
   Confirm the run actually executed; a mutation that breaks collection proves
   nothing.
6a. **Capture the verbatim failure output** when the test first fails. "It failed"
   is not evidence; the message is.
6b. **Accounting code (cost, quota, rate limits, usage) asserts CARDINALITY** — how
   many records, rows, or calls — never just a clean-path outcome. F-01 survived
   every existing test because they asserted *that* a run was billed, never *how
   many times*. Ask of every assertion: could this fail for ANY implementation?
7. **A negative check needs a positive partner.** "No X found" is trivially true
   over nothing.
7a. **Never parametrize a test over the constant it tests**; never assert a bound
   against the constant that defines it.
8. **Assert structure, not substrings** — a substring matches the prose that
   explains the thing. Use `tests/code_text.py` when you must read a file.
8a. **The repo's `HTTPError` doubles have an EMPTY body, and they do not say so.**
   Both PRE-EXISTING `_http_error` helpers — `tests/unit/test_provider_billing_classification.py:119`
   (`hdrs=None`) and `tests/unit/test_readiness_key_auth.py:85` (`hdrs=Message()`,
   used by 5 call sites) — pass `fp=None`, and that does NOT raise on `.read()`.
   Measured on CPython 3.12.13: `.read()` returns `b''` because CPython
   substitutes an empty `BytesIO`; `.headers` is `None` for the first and an
   EMPTY `email.message.Message` for the second (`== {}` is False — do not
   assert that). So any test asserting "the error body does not contain X"
   against either double passes **vacuously, against every implementation,
   including one that never reads the body at all**. This bites #105 and #203
   identically, since both fixes turn on reading a real response body. Give
   every such test a REAL body and a positive partner proving the present case
   is detected.
8b. **A bound enforced downstream of the operation is not a bound**, and a
   BYTE bound is not a TIME bound. Both measured on one 40-line function,
   2026-08-05:
   - A test asserting `body_bytes <= LIMIT` survived deleting the read's size
     argument entirely, because a slice taken *after* an unbounded read still
     reported a bounded number. Assert on the ARGUMENT, not the result — and
     never against the constant that defines the bound (rule 7a): pinning
     `<= LIMIT` also let `LIMIT` itself be raised 8192 → 40000 undetected.
     Pin the exact boundary with literals on both sides.
   - `exc.read()` on an `HTTPError` is a SOCKET read. A 503 with no
     `Content-Length` and the socket held open blocked for the full
     `openrouter_timeout_seconds` — **0.008-0.013s (5 reps) → 8.009s on the
     error path** — then raised `TimeoutError`, paying the whole timeout to
     learn nothing. No unit test can see this; it took a reviewer driving a
     real loopback server that withholds a body. Bound the TIME — lower the
     socket timeout before the read. **Do NOT "fix" this by gating on
     `Content-Length`**: that was tried, and rule 8c below is what it cost.

8c. **A mitigation gated on an upstream's behaviour is worth exactly as much as
   your MEASUREMENT of that upstream — and you probably have none.** Measured
   2026-08-05, on a fix that had already survived two review lenses and 20
   mutations: it bounded a body read by refusing to read unless the response
   declared `Content-Length`. Correct against a loopback server, green on every
   gate. **The real OpenRouter API is behind Cloudflare and answers errors with
   `Transfer-Encoding: chunked` and NO `Content-Length`**, so it would have
   collected nothing at all in production while looking perfectly healthy. One
   `curl` to the live API — free, a 401 costs no tokens — found it in seconds.
   Before you gate on an upstream header, status or body shape, GO AND LOOK.
   Useful facts already paid for: OpenRouter errors are chunked, JSON, ~50
   bytes, `Server: cloudflare`; a bad key gives `401 {"error":{"message":"User
   not found.","code":401}}` with NO `error.metadata`; and it exposes
   `X-Provider-Name` in `Access-Control-Expose-Headers`.

**Review**
9. **Fan out for review, never for building.** Subagents share one working tree.
   Tell every reviewer **IN CAPITALS** not to write, edit, `git checkout`,
   `git stash` or `sed -i` anything.
10. **Two lenses, not five.** Two reviewers ≈ four; one is worse (Porter et al.,
    *IEEE TSE* 1997). Spend the difference on verification, not more finders.
11. **Verify every reviewer claim before acting.** **Check the fix, not just the
    finding.** The often-quoted "roughly a fifth do not survive" has **no source
    document in this repo** — treat it as assumed, not measured.
    What *is* measured, on 2026-07-30, is the decay rate of claims **inherited
    from handoff documents** — a different and worse population. Two components,
    each checkable on its own; deliberately NOT summed into one headline figure,
    because the first attempt at that produced an aggregate nobody could re-derive:
    - **2 of 3** headline findings refuted outright (extraction ledger §4.1, §4.2);
      a third (§2) was narrowed rather than refuted.
    - **8 of 18** "would be lost outright" candidates already done, already filed,
      or largely wrong (§4).
    Roughly half of what a handoff asserts does not survive contact with the tree.
12. **Cap review at TWO rounds**, then STOP and escalate with open findings
    listed. If two fixes in a row add defects, change the approach.
    **Expect your own fix to introduce a defect — budget a round for it.**
11a. **Tell every reviewer to audit the diff's PROSE, not only its code.**
    Verbatim, in the prompt: *"for every number, superlative, and causal claim
    in the diff's comments, commit body and PR description, name the command
    that produces it — or mark it UNVERIFIED."*
    Measured 2026-08-03: six false claims shipped inside one session — a
    containment figure quoted as a Jaccard, an agent's "1,836 attempts" cited
    as a repo fact, "the guaranteed floor" (false on a truncation path), "that
    clamp responded to CONTAINER width" (it was `5vw`). Every one was in prose,
    none in code, and the reviewers who were not asked to look at prose did not
    look. Research into mechanical alternatives concluded no tool anywhere
    flags an unverified claim in prose; this line is the highest-yield
    mitigation available and it costs nothing.
12a. **Reviewers refute by default** and report only findings backed by a
    demonstrated failure. Reviews are **read-only**; a separate single writer
    applies fixes.
12b. **A reviewer that must mutate source gets its OWN copy**
    (`git archive HEAD | tar -x -C <dir>`). A shared-worktree mutation once gave
    another reviewer 4 phantom failures, and once left uncommitted edits a later
    agent inherited.

**Commands that bite if you get them wrong**
13. **Run e2e exactly as CI does**, or ~95 phantom failures appear. Since
    #100, `SESSION_RATE_LIMIT_PER_MINUTE` alone is not enough — the DURABLE
    per-IP daily mint cap (2/24h in production) needs its own LOCAL-only
    override too, or the 3rd cookie-less `/ui` boot in the run gets a 429
    and every invariant spec after it fails to even render:
    ```bash
    lsof -ti tcp:18085 | xargs -r kill -9
    cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 SESSION_MINT_CAP_OVERRIDE=600 \
      npx playwright test <spec> --project=chromium --workers=1 --retries=0
    ```
13a. **`e2e/tests/review/` makes `make quality` RED on your machine and green in
    CI.** That directory is gitignored (`.gitignore:59`) and holds local review
    scratch specs. `tests/unit/test_no_orphaned_e2e_specs.py:95` enumerates with
    `rglob` — the FILESYSTEM — so it finds them and fails with
    *"is committed under e2e/tests/ but no workflow invokes it"*, which
    `git check-ignore` flatly contradicts. Measured 2026-08-04: **7 failed, 28
    passed** locally; `28 passed` on a clean `git archive HEAD` copy. Before
    blaming your diff for a red `test_no_orphaned_e2e_specs`, run
    `ls e2e/tests/review/`. The mirror-image bug is in
    `e2e/tools/check-negative-assertions.mjs:380`, whose `--all` mode uses
    `git ls-files` and is therefore BLIND to those same 7 files.
13b. **`pytest-randomly` is NOT installed**, though `pyproject.toml:192` sets
    `-p no:randomly`. Verified: `uv run python -c "import pytest_randomly"` →
    `ModuleNotFoundError`. So that flag disables a plugin that is not there, and
    **test order is deterministic-alphabetical, locally and in CI**. Do not
    reach for `--randomly-seed` to shake out ordering bugs; it does not exist
    here. Shuffle at the module level (pass test files in a different order)
    instead.
13c. **`timeout` does not exist on this macOS box** (`command not found`). Use
    your tool's own timeout, or `perl -e 'alarm shift; exec @ARGV'`.
13d. **Growing `goldenCompletedResp()` changes a BLOCKING visual lane you cannot
    re-baseline locally.** It feeds `visual-snapshots.spec.ts` /
    `trust-score-visual.spec.ts`, whose Linux baselines are seeded only by
    `.github/workflows/seed-visual-baselines.yml`; only the `-darwin` ones exist
    on your machine. To give a rendering gate a new shape, add a DEDICATED
    builder (see `goldenRespWithBlockStructure`, added for #120) rather than
    mutating the shared one.

13e. **The visual lane fails 8/8 on your Mac, on CLEAN `main`, and that is not a
    regression.** Playwright compares `*-chromium-darwin.png` locally; CI
    compares `*-chromium-linux.png`. They were NOT seeded together — darwin was
    added in `f25696e` (2026-07-25), linux first in `2533fd3` (2026-07-17) and
    last re-seeded by `94fc256` (2026-07-28) — and the page has grown since, so
    the darwin images are stale:
    measured 2026-08-04 on clean `main`, `result-verdict` expects 1440x**3137**
    and the page renders 1440x**3385** — 248px taller, 3% of pixels. `e2e.yml`
    already says a local pixel comparison "couldn't be trusted locally"; this is
    what that looks like. **Never `--update-snapshots` to make it green** — the
    darwin images are dev-only and CI ignores them, so you would commit noise
    and still not have tested what CI tests. To show a rendering change is SAFE
    for the Linux baselines, dump the relevant `outerHTML` on
    `goldenCompletedResp()` before and after and prove it byte-identical.

14. **`make quality` and `make validate` do NOT cover the merge gates.** Six
    contexts are required by branch protection. Passing both targets locally
    proves almost nothing about whether the pull request can merge. Each
    required context, and the local command that produces it (verified
    2026-07-30):

    | Required status check | Produced locally by |
    |---|---|
    | `validate-and-test` | one CI job running **eight** targets: `make validate`, `openapi-check`, `format-check`, `lint`, `type-check`, `test-report`, `security-scan`, `docker-build`. The first six are covered by `make quality && make validate` below; **`docker-build` is covered by nothing local** |
    | `pytest (Python 3.12)` | `make quality` |
    | `Changed-lines coverage >= 95% (blocking)` | `make diff-cover DIFF_BASE=origin/main` |
    | `Schemathesis API contract (blocking)` | `make api-contract` |
    | `FR traceability completeness (blocking)` | `make fr-completeness` (inside `make validate`) |
    | `e2e axe + parity (chromium)` | **the e2e suite — see rule 13** |

    ```bash
    uv sync --all-extras   # NOT --extra dev: schemathesis lives in `quality`
    make quality && make validate
    make diff-cover DIFF_BASE=origin/main
    make api-contract
    make openapi-check
    make security-scan
    # and e2e per rule 13 if you touched UI, specs or fixtures
    ```

    **This list has been wrong twice.** Until 2026-07-30 it omitted
    `make api-contract`; the fix that added it still missed
    `e2e axe + parity (chromium)`, which is a required check whose words appear
    nowhere else in this file. **A count goes stale silently, so do not trust
    the table — re-derive it:**
    ```bash
    gh api repos/:owner/:repo/branches/main/protection \
      --jq '.required_status_checks.contexts[]'
    ```
    **Never lower a threshold, add `# pragma: no cover`, or delete a test to go
    green.** If a line is genuinely untestable, say so with evidence.
15. **Run `pytest` and `make diff-cover` serially.** Until 2026-08-02 they
    also raced on the fixed, shared `build/gates/guard-good-xml.xml` written
    by `tests/unit/test_makefile_gate_integrity.py` (#113, #104 item 2) —
    that race is now closed (the guard names are suffixed per-`os.getpid()`,
    so two concurrent processes never touch the same file). Still run them
    serially anyway: per rule 15a below, `make api-contract` and the other
    pytest-invoking targets rewrite the SAME shared coverage data
    (`.coverage` / `build/coverage/coverage.xml`) that `diff-cover` reads,
    which is a separate reason and is not fixed by the guard-xml change.
15a. **`make diff-cover` measures `origin/main...HEAD` PLUS the working tree, so
    COMMIT before you trust it.** When a later uncommitted edit deletes code an
    earlier commit on the same branch added, the two do not cancel: diff-cover
    attributes *pre-existing, untouched* lines to your diff. Measured
    2026-07-30 — it reported `synthesis_length.py (37.5%): Missing lines
    179-183` for five lines inside `_truncate_with_caveat_present`, a function
    the branch never edited, and that is a BLOCKING gate going red while naming
    the wrong code. Committing the tree took the same diff to `20 lines, 100%`.
    Re-run `make quality` immediately before it, too: `make api-contract` and
    the other pytest-invoking targets rewrite the coverage data underneath it.
16. **`make format` reformats test assertions** and breaks `sed`-style anchors.
    Grep for the real text before any programmatic edit.
16a. **Process-global test state.** The cost event ring, the run-capacity
    semaphore and the model catalog are process globals — a test that mutates one
    changes the cap for everything after it. Use
    `tests/helpers.isolated_run_semaphore` (`tests/helpers.py:19`).
16b. **A probe script that does `sys.path.insert(0, ROOT/"src")` can silently
    measure a STALE copy of the tree** sitting next to it, making a working fix
    look broken. Repoint `ROOT` and sanity-check that the file you think you are
    importing is the one on disk.
16c. **Before deleting a file, run `git ls-files <path>`.** Tracked files are
    recoverable with `git show <sha>:<path>`. An untracked file has no history —
    but if it was ever `git add`ed it survives as a **dangling blob**, and
    `git fsck --lost-found` plus `git cat-file -p <blob>` recovers it byte-exact.
    Recorded 2026-07-30: three untracked handoff documents were deleted, declared
    unrecoverable on the strength of `git log --all` alone, and then recovered in
    full from dangling blobs. **Check the object store before declaring loss.**

**Decisions**
16d. **A decision gets an ADR in the same PR that makes it.** A decision is:
    a default value, a failure posture (open vs closed), a policy, a rejected
    alternative that cost real work, or anything a future reader would ask
    "why is it like this?" about. Use `docs/adr/`, follow ADR-0002's shape
    (measured table, rejected alternatives, consequences), and regenerate the
    index with `python3 scripts/generate_adr_index.py` — `make validate` fails
    if you don't. **Do not hand-edit the index.**
    Measured 2026-08-03: a nine-issue batch made ~6 architecture decisions and
    recorded **zero**, while `docs/adr/`, the index, AND
    `.agents/skills/architecture-and-decisions/` all already existed. Every
    mechanism was discoverable and optional, and the task list did not name
    them. Worse, ADR-0002 pinned the exact constraint (`SQLite single-writer`)
    that the batch's money work then reasoned on top of without re-reading.
    **This rule is influence, not enforcement.** The index gate is mechanical;
    "did you write the ADR at all" is not, and cannot be. If you notice this
    rule being skipped, that is the signal to make it mechanical, not to
    restate it louder.

16e. **Before writing code that touches money, auth or safety, list the known
    failure modes first.** One page, from research and from existing ADRs, then
    design against that list. Front-loaded and cheap.
    Measured 2026-08-03: the spend-cap work went five review rounds, each fix
    correct in isolation and each revealing the next, because the failure modes
    were discovered one at a time from defects instead of enumerated up front.
    Thirty minutes on "how do spend meters fail" would have surfaced
    read-modify-write races, lost writes, reconciliation and idempotency — the
    exact four. Worse, ADR-0002 already recorded the governing constraint and
    was not re-read. **The homework mostly already exists in `docs/adr/`; the
    failure is not reading it.**

**Shipping**
17. **One CONCERN per pull request**, merged before the next starts — a reviewer
    cannot audit a billing fix and a docs restructure in the same diff. Merge
    `main` into your branch **before** starting. Check you are on your branch
    before committing.
17a. **Branch in a dedicated `git worktree`**, never the main checkout, so other
    uncommitted work is never at risk.
17b. **Push, open a pull request, merge and deploy only with explicit human
    approval.** Commit locally freely.
17c. **Squash-merge with an explicit message**
    (`gh pr merge --squash --subject --body`). A bare `--squash` concatenates
    EVERY commit body onto `main`, so superseded figures from intermediate
    commits land there. (Violated on PR #172, merged 2026-07-29 — both bodies
    landed.)
    **Vet that text before you run the command:**
    ```bash
    PR=<n> EXPECT_CLOSE="<issues this merge closes, comma-separated, or empty>" \
      MERGE_SUBJECT="..." MERGE_BODY="$(cat body.md)" make close-guard
    ```
    (the text goes in the ENVIRONMENT — a merge body full of backticks and
    quotes must never be re-parsed by a shell). The guard refuses unless what
    WILL close — the merge text plus GitHub's parse of the pull request —
    equals `EXPECT_CLOSE` in both directions; before 2026-08-25 it announced
    an unintended close and passed (#374). When it refuses: if the named
    issue SHOULD close, add it to `EXPECT_CLOSE`; if not, move the keyword
    away from the number and run again. A close keyword next to `#N`
    closes that issue, and GitHub cannot read negation:
    `**This does NOT close #337.**` in PR #360's merge body closed #337.
    **Four** issues have been closed this way; a fifth was caught by hand just
    before merging. CI checks the pull request's title and body mechanically;
    it never sees the MERGE text, so this command is the only thing that does.
    ADR-0066 has the measurements and the blind spots.
17d. **The head branch must be up to date with base.** A second stacked pull
    request merges `main` in first, then **re-gates the merged tree locally**
    (diff-cover included). A clean auto-merge is not a correct merge.
17e. **After merging, `git branch -f main origin/main`** — the merge lands on the
    remote and the local ref does not follow.
    **That command FAILS when `main` is the branch you have checked out**, which
    in this repo's own workflow is the usual case: `fatal: cannot force update
    the branch 'main' used by worktree at '/Users/.../quorum-ai'` (measured
    2026-08-17, closing out PR #334). Use `git merge --ff-only origin/main`
    from the main checkout instead — same result, and it refuses rather than
    rewrites if the histories have diverged. `git branch -f` is still the right
    form when you are on some other branch.
    Related, same close-out: `git branch -D <merged>` also fails while any
    worktree still has that branch checked out (`error: cannot delete branch
    ... used by worktree at ...`). Remove the worktrees FIRST, then delete the
    branch — which is the order step (4) of rule 18a already implies but does
    not state.
17f. **Hermetic / $0.** No paid API calls for routine checks. Never fabricate a
    number — flag the gap instead.
17g. **Before selecting a work package, check whether several open issues are
    the SAME concern under different issue numbers** — same function/file/
    narrow area, one a direct follow-on of another, or a batch of trivial
    same-surface copy/doc fixes. Club those into ONE PR to cut redundant
    review-and-deploy churn on the same code. **Do not club issues just
    because each is individually small** if they are actually unrelated
    concerns — rule 17 (one CONCERN per PR) still binds; this changes work-
    package *selection*, not the one-concern-per-PR rule itself. State which
    issues are in the cluster and why each belongs, same as rule 20 requires
    for a single issue.
18. **Done means merged AND running in production.** Verify three ways: the
    deploy **job** ran (not `skipped`/`cancelled` — check the job, not the run's
    rollup), `/status.build_sha` equals the merged SHA, and the thing you built
    actually fires. Probe production only where it costs nothing — `/ready`,
    `/status`, `/metrics`, `/ui/ops` and `/estimate` are all free; a full run
    is not.
18a. **Close out in this order, every time — do not skip or reorder:**
    (1) local gates green (rule 14) and every review finding resolved;
    (2) merge (rule 17c); (3) verify the deploy per rule 18, on the newest
    run for the merge SHA if a concurrency-cancelled run appears first;
    (4) `git branch -f main origin/main` (rule 17e), delete the merged
    branch (local + remote), remove the dedicated worktree. Merging without
    step 3 and leaving a stale branch/worktree without step 4 are both
    measured failure modes, not edge cases.
    A docs-only merge still redeploys (no workflow has a paths filter), so
    `build_sha` tracks `main`'s tip after **every** merge, not only code ones.
    Traps:
    - **`gh run list --commit <SHA>` returned `[]` on 2026-07-22** and the
      workaround was `--branch main` plus a SHA-prefix match. **Re-measured
      2026-07-30 on `gh 2.96.0`: it returns runs normally** (10, and 5/10/8/10
      across four `main` SHAs). The workaround is still safe but no longer
      required. Recorded with its date and tool version because the original
      was written as a timeless absolute, so nobody re-checked it for a week.
    - **A merge produces two runs; one is `cancelled` by concurrency dedupe.** A
      wait-loop keyed on "any completed run for this SHA" fires on the cancelled
      one and reports done while production is still on the old build. Resolve
      the **newest run by `createdAt`**, then read its Deploy **job**.
19. **Close more than you open.** If an item is bigger than it looked, say so and
    stop — do not file and continue.
20. **A pull request opens with one line saying why this item outranks the top of
    the backlog.** If that line cannot be written honestly, the ranking is wrong.
    Discovering a higher-ranked item mid-work is a **mandatory stop**: park the
    branch, re-run selection, record it.

**Before adding a gate**, measure its yield against real defect history and state
what it cannot see. Measured here: **0 of 16** `src/` defects were caught by an
automated check; **10 of 16** by adversarial review
(`docs/metrics/defect-discovery-audit.md`).


## Simplified start

The user may start in either way:

1. Fill `PRODUCT_IDEA.md`; or
2. Tell the idea directly in the Codex prompt.

If the idea is supplied in the prompt, first write it into `PRODUCT_IDEA.md`. Then run the `idea-intake-clarifier` skill. Ask the smallest useful set of clarifying questions before generating requirements, architecture, Jira issues, Confluence pages, tests, or implementation code.

Maintain `docs/00-factory-console.md` after every meaningful step. It must show current phase, next best action, suggested prompt, questions, assumptions, suggestions, and validation status.

## Mandatory lifecycle

Run `.agents/skills/factory-orchestrator/SKILL.md` before implementation.

Do not code until these exist and validate:

- `docs/01-product-brief.md`
- `docs/03-source-of-truth.md`
- `docs/10-functional-requirements.md`
- `docs/11-non-functional-requirements.md`
- `docs/12-acceptance-criteria.md`
- `docs/17-requirement-registry.md`
- `docs/18-requirement-traceability-matrix.md`
- `docs/20-architecture.md`
- `docs/21-domain-model.md`
- `docs/40-threat-model.md`
- `docs/42-ai-safety-grounding.md`
- `docs/50-test-strategy.md`
- `docs/60-implementation-plan.md`
- `docs/70-ci-cd-plan.md`
- `docs/80-observability.md`

## Jira workflow

Use only statuses defined in `configs/jira-statuses.json`:

Backlog → To Do → Ready For Dev → In Development → Code Review → CI Validation → QA Ready → In QA → QA Verified → Closed.

`Cancelled` and `Duplicate` are terminal. `Closed` can be reopened only with explicit human approval and reason.

## Validation

Run:

```bash
make validate
make quality
```

Stop on failed validation gates.


## Review before "done"

Green gates are necessary but not sufficient — they catch known failures, not
new bugs a change introduces. Before declaring any non-trivial change complete:

- **Adversarially review the diff with independent subagents.** At minimum a
  correctness pass; and for anything touching security, secret handling, auth,
  or detection/validation logic, a reviewer whose explicit job is to *break*
  the change and find an evasion. Do this proactively — do not wait to be
  asked, and do not rely on a single self-assessment.
- **A behavioural change ships with a test that would fail without it.** This
  applies to helper scripts too (e.g. `scripts/security_scan.py`), not only
  `src/` — CI coverage (`--cov=src`) does not see them.
- **When you loosen or suppress a check, prove both directions:** the false
  positive is gone AND every genuine case the check must still catch is still
  caught. Never gate a secret/threat check on whole-line substrings; key off
  the matched token or value.
- **Verify by executing, never by reading.** A statement about what a tool,
  gate, or test does is UNVERIFIED until you have run it and read its output.
  This is not a style preference — it is the failure mode that has cost this
  project the most, and it applies to human and AI contributors equally.
  Measured examples, all from one work package
  (`docs/metrics/mutation-gate-study.md` §8): a CI gate reported green for
  **~7 days** while aborting before it measured anything (abort confirmed by log
  on 22 and 28 July), and the issue to promote it cited that abort as a passing
  run; two freshly-written tests asserted only on printed text and stayed green
  under the mutation they existed to catch; a guard asserting
  `"sys.platform" in source` survived the constant being flipped to the wrong
  value. In each case the reading was confident and the run disagreed.
  **This paragraph said "months" until 2026-07-30.** §8 of the very study it
  cites lists that word in its own table of refuted claims, corrected to ~7 days
  — so the rulebook's flagship example of verifying by execution was itself an
  unverified number, carried for a week inside the section warning against
  exactly that. The lesson is not that the gate was broken; it is that a
  citation is not a check.
  - Before promoting an advisory gate, **open its job log** and confirm it
    produced its number.
  - **A RED gate is not evidence it measured either.** A non-zero exit can mean
    the gate fell over before measuring anything — which is what #158 was, and
    the failure message named the wrong cause. Read the log and find the number
    before attributing a red gate to the diff in front of you.
  - Before excluding tests from a gate, **measure** what that removes.
  - Before claiming a check bites, **mutate the code and watch it go red** —
    `cp` the file aside and restore from the copy, never `git checkout`.
- **Every gate must report what it counted, and refuse to pass on an empty
  input.** Nearly every gate here is a negative check ("no line uncovered", "no
  secret matched", "no requirement lacks a row"), and all of those are trivially
  true over nothing. Measured 2026-07-29: **13 of 21 CI jobs could reach a
  terminal status having measured nothing, four of them blocking** — including
  `diff-cover`, reproduced exiting **0** on a diff with genuinely uncovered new
  lines because its coverage report mapped none of them. Floors now exist
  (`docs/analysis/03-enforcement-machinery.md`); when you add a gate, add its
  floor in the same commit and prove it red against an empty input.
- **Do not add a new gate before checking how the last N real defects were
  found.** Measured over every fix commit touching `src/`: **0 of 16 were caught
  by an automated check**; 10 of 16 came from adversarial review. The
  per-commit table, the method and its limits: `docs/metrics/defect-discovery-audit.md`. Gates here
  prevent regressions; they do not detect new defects. The multi-lens review fan
  is what does, and the slice built without one leaked 10 escaped defects against
  0 for the two built with one.


## UI verification (the built workspace)

This is **influence, not enforcement** — the binding gate is CI (see below), not
this file. But when you touch the workspace UI (`src/product_app/static/app.js`,
`app.css`, `templates/workspace.html`):

- **Drive the real UI, don't just read the code or run a green test.** A passing
  unit test on clean sim data has repeatedly hidden real-LLM-output bugs
  (raw Markdown, a non-monotonic timer, cramped layout). Render against the
  **golden messy fixture** (`e2e/fixtures/golden-run.ts`) — real-shaped provider
  output with headings, bold/italic (both `*` and `_`), inline code, links,
  ordered lists, blockquotes, long multi-paragraph answers, an empty-citation
  slot — and look at it as a user would (screenshot at 1440px).
- **The below-the-line gate is `e2e/tests/invariants/`** — driven in CI by
  `.github/workflows/e2e.yml`. That directory holds **18** specs, not the
  three described below: `answer-completeness`, `export-and-expanders`,
  `landing-cta-reachable`, `markdown-corpus`, `provider-notice-coverage`,
  `readiness-banner`, `readiness-no-flash`, `real-integration-smoke`,
  `rendering-invariants`, `result-debate`, `session-trail`, `source-expander`,
  `source-support-denominator`, `theme-toggle`, `trust-score-invariants`,
  `trust-score-visual`, `verdict-band`, `visual-snapshots`. All 18 are named in
  a `playwright test` command in `e2e.yml` — 15 in the first blocking lane,
  `real-integration-smoke` in the second, and `trust-score-visual` +
  `visual-snapshots` in the visual-baseline lane. Three are detailed below
  because they have contracts worth stating; the other fifteen bind just as
  hard. Enumerate the directory rather than trusting this list.
  **This count said "twelve" until 2026-08-04**, and the error is instructive:
  the FIRST blocking lane runs exactly 12 invariant specs, so a number that was
  right about the LANE got written down about the DIRECTORY, and three more
  specs were added later without anyone noticing. Nothing failed, because
  nothing checked. It is checked now —
  `tests/test_doc_gate_consistency.py::test_agents_md_states_the_real_invariant_spec_count`
  compares this sentence against `ls -1 e2e/tests/invariants/*.spec.ts | wc -l`
  and goes red the moment a spec is added or removed without editing it. **Keep
  the number a digit**: the gate cannot read "twelve".
  **Two holes in the guard that is supposed to keep that true**
  (`tests/test_e2e_workflow_covers_all_invariant_specs.py`) — both pre-existing,
  neither fixed here:
  - It asserts `spec in workflow` against the **raw text** of `e2e.yml`, so a
    spec named only in that file's header comment block passes while running in
    no step. It forces the *name* to appear, not the spec to *execute* — an
    instance of the substring-vs-structure trap in rule 8, inside a gate.
  - Its `GATED_SPEC_DIRS` covers only `e2e/tests/invariants/` and
    `e2e/tests/ops/`. `e2e/tests/degraded/` is **not** swept, though
    `e2e.yml:213` runs a blocking spec from it.

  The specs are:
  - `rendering-invariants.spec.ts` — walks `#main-content` and asserts NO raw
    Markdown survives in any text node (`**`, `##`, `` `code` ``, `](url)`,
    `_ _`/`__ __`, line-start `>`), a **monotonic** elapsed timer, no horizontal
    overflow, and inline code stays verbatim. **Blocking.**
  - `visual-snapshots.spec.ts` — human-reviewed `toHaveScreenshot` baselines for
    the result + transcript views (Linux baselines seeded in CI; see
    `.github/workflows/seed-visual-baselines.yml`).
  - `e2e/tests/degraded/degraded-banner.spec.ts` — **note the path: it is in
    `tests/degraded/`, not `tests/invariants/`**, though `e2e.yml` runs it in the
    same blocking lane. This file said `invariants/` until 2026-07-30, so a
    reader looking for it there found nothing. The result view must surface a
    degraded banner
    whenever the panel came up SHORT, so an incomplete run is never shown as a
    complete one. Note this line **described a contract the code did not have**
    until WP-H: the banner was keyed on `local_count > 0` — "were any answers
    simulated?" — which is blind to a slot that produced *no* answer (cancelled,
    or the run deadline expired). Such a slot is counted in neither `live_count`
    nor `local_count`, so a run with three live answers and one missing showed no
    banner at all while the headline read "3 of 4 models aligned". The condition
    is now `localCount > 0 || failedCount > 0` (`app.js:2297`, where
    `failedCount` is the slots that produced nothing) — equivalent to
    `live_count < slot_count` **whenever `live + local <= slot_count`**, which is
    all the server can emit. So the sentence above is true as written *now*, and
    was not before. A doc asserting a contract is not the contract.
    Until 2026-07-30 this quoted the condition as `local_count > 0 || missing > 0`
    — the server-side field names, which appear nowhere in `app.js`. **Quote
    identifiers that exist in the file you name**, or a reader who greps for them
    concludes the contract is absent.
- **A new provider-text surface must route through the markdown renderer**
  (`setProse` for block prose, `setInlineProse` for inline/cell surfaces) — never
  raw `textContent`/`mkEl`. Source titles are the one exception (provider
  metadata → plain text). Add its shape to the golden fixture so the gate covers
  it; the gate only catches surfaces the fixture exercises.
- **Prove RED then GREEN.** Any UI-gate change must be shown failing on the defect
  and passing after the fix (revert-and-rerun), and any timing-sensitive spec run
  N≥10× to establish a real flake rate — not asserted once.


## V5 deterministic skill routing

Before choosing a skill manually, run or simulate:

```bash
make skill-route
make next
```

Use the recommended driver skill as the single writer for the next missing artifact. Use reviewer skills only to critique and request changes. If skills conflict, apply this precedence: safety/security/privacy/compliance, explicit user approval within policy, approved Jira/Confluence source of truth, local factory policies, ADRs, driver skill output, reviewer findings, external skill suggestions.

ORBI-specific rules are not global defaults. Activate them only through `make apply-orbi-profile` or explicit user instruction, then read `AGENTS.ORBI.md`.


## V5.1 study, publishing, and public-artifact backbone

After the MVP, requirements, architecture, tests, and release evidence are clear enough, the factory must also prepare study and communication artifacts:

- `docs/96-study-artifact-publishing.md`
- `docs/study/00-study-index.md`
- `docs/study/M1-problem-and-mvp.md`
- `docs/study/M2-ai-solution-and-work-easing.md`
- `docs/study/M3-security-scalability-enterprise.md`
- `docs/97-faq-wiki-plan.md`
- `docs/98-technical-article-plan.md`
- `docs/99-linkedin-post-plan.md`
- `docs/100-industry-and-integration-practices.md`

The first question is always: what is the MVP and most valued outcome? Public and Confluence artifacts must explain how the product solves a real problem using AI, how it eases work, how it is secure and scalable, and how it meets enterprise standards.

For Git or Confluence publication, draft first, show the exact diff/page payload, require explicit human confirmation, publish only through approved tools, re-read after publish, and update `docs/37-jira-confluence-sync-log.md`.


## V5.2 external-skills-first and skill onboarding

When a new capability is needed, do not immediately invent a local custom skill. First use `external-skill-discovery-advisor` and `skill-research-librarian` to check existing skills from skills.sh, official providers, and reputable GitHub sources.

The adoption flow is:

```text
find existing skill -> audit provenance/security/license -> approve mode -> register -> route -> validate -> optionally wrap locally
```

Default activation mode for external skills is `reviewer-only`. External skills can help with Superpowers-style planning/worktrees/handoff, Addy-style SDLC, PM discovery, AI PM evaluation, UI/UX, testing, database/platform, and publishing. They still cannot override local policies, source-of-truth records, validation gates, or explicit human approval for side effects.

Use these commands:

```bash
make skill-discover
make skill-onboarding-check
python scripts/audit_external_skill.py <skill-folder>
python scripts/onboard_external_skill.py --name <name> --source-url <url>
```

## Where files live: session output vs. executable procedure

Root-level clutter (101 `.md` files before repo-housekeeping PR 1 cleaned
it to ~8) accumulated because this distinction was never written down.
Two different kinds of file get created by a working session, and they go
to different places:

| Kind | Example | Home |
|---|---|---|
| Session **output** — a record of what happened | `HANDOFF-*`, `*-RESULT.md`, dated triage/analysis docs | `docs/archive/` (or `docs/analysis/` if it stays actively referenced) |
| Executable **procedure** — text a future session runs | `*-ULTRACODE-PROMPT.md` | root, or `.agents/skills/` once generalised |

**The rule is "session output never accumulates at root," not "session
artifacts never at root."** The blunt version would forbid
`REPO-HOUSEKEEPING-ULTRACODE-PROMPT.md` itself — an executable procedure
correctly kept at root — and a rule that forbids the thing you're holding
gets ignored rather than followed. If you're not sure which kind a file
is, ask: would a future session **run** this, or does it only **read**
this to see what a past session did? Running → procedure → root/skills.
Reading-only → output → `docs/archive/`. **A handoff doc that is half
state-record and half next-steps-to-execute is genuinely both** — several
existing `docs/archive/2026-08/*-ULTRACODE-PROMPT.md` files are exactly
this shape, correctly archived despite the naming heuristic above pointing
at "procedure." When a file is a real hybrid, judge by what it mostly is
today, not by its filename suffix alone.

For `docs/NN-*.md` numbering specifically (a separate but related form of
this same problem — 14 numbers collided before nothing checked a new
doc's number against the tree), see ADR-0034
(`docs/adr/0034-docs-numbering-scheme-and-ranges.md`) for the range table
and `tests/unit/test_docs_numbering_no_collisions.py` for the gate.

## Session continuity

Before ending or handing off a session:

```bash
make next
make skill-route
make handoff
```

A new session must read `AGENTS.md`, `docs/00-factory-console.md`, and `docs/session-handoff.md` before editing. Use git worktrees for parallel sessions and keep one owner per artifact family.

`docs/session-handoff.md` is a mechanical snapshot only (branch, `git
status`, skill-route) — `make handoff` regenerates it from live state and it
cannot hold narrative content. Write the actual "what happened, what's next,
the traps" narrative to `docs/analysis/<YYYY-MM-DD>-session-handoff.md`;
`scripts/session_handoff.py` finds the newest one by filename and links it
at the top of the regenerated mechanical file, so the next session always has
a live pointer to the real context instead of a stale one — and flags the
link's age in days if it isn't from today, so a stale fallback (e.g. the
latest got archived before a replacement existed) is visible rather than
silently presented as current.

**If a narrative handoff for today already exists** (a second session the
same date), update it in place, or add it as
`docs/analysis/<YYYY-MM-DD>-session-handoff-2.md` (the pointer sorts a
numeric suffix correctly within a date) — never silently overwrite the
first session's file at the same path. **Archive the current narrative
handoff only after its replacement exists**, not before — archiving first
leaves the pointer falling back to an older, staler doc in the gap.

## User-guided start

If `PRODUCT_IDEA.md` is empty, placeholder-only, or the user gives the idea in chat, ask for the problem in plain language first. Then suggest the next best action. The user should not have to guess which skill or file to use.
