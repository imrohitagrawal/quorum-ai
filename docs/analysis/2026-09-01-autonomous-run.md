# 2026-09-01 autonomous run (ultracode, unattended)

## Summary

- **Shipped and verified running in production (both, independently re-checked
  by me, not taken on the sub-orchestrator's word):**
  - PR #419 — W21+W22 transport hardening. Merge SHA `1c90615f0ca5fefadbd1ed322aaaeeebd71cef00`.
  - PR #420 — #418 board-needle tokenization fix. Merge SHA `0d5be18f2a831abf2e0fe67a082d8cf35103889a`.
  - `curl https://quorum.stackclimb.com/status` at end of run:
    `build_sha == 0d5be18f2a831abf2e0fe67a082d8cf35103889a` (== the newer
    merge SHA, == `origin/main`'s tip), `live_execution: false` throughout.
  - Board: 22 rows, **3 PENDING / 14 DONE** (was 5 PENDING / 12 DONE at
    session start). `check_open_work.py --check` exits 0.
- **Stopped and why:** nothing stopped early — both planned packages closed
  cleanly within the two-review-round cap, no repeated-defect pattern.
- **Left for human decision:**
  - `docs/adr/0090-a-credential-does-not-follow-a-redirect-and-tavily-gets-the-same-scheme-check.md`
    and `docs/adr/0091-the-board-checker-tokenizes-python-instead-of-stripping-hash-comments.md`
    both recorded ADVISORY_DEBT
    that was correctly left out of scope rather than fixed in-package — see
    each package's entry below for what and why.
  - Local `main` is still ahead of `origin/main` by the 3 docs-only commits
    this run and the prior overnight session produced (the deliberately
    unpushed `#402` design record plus this run's two log commits). Per
    AGENTS.md rule 17b, pushing/merging needs explicit human approval — this
    run committed locally only, as instructed, and did not push.
  - #402 and #290 remain open and were out of scope for this run by design.

## Starting state (verified)

```
git fetch origin && git status -sb        -> ## main...origin/main [ahead 1]
git worktree list                          -> only /Users/rohitagrawal/Projects/quorum-ai (ec84ebb, main)
python3 scripts/check_open_work.py --check -> 22 rows (5 PENDING, 12 DONE), 17 needles, 5 unpinned; EXIT=0
gh issue list --state open                 -> #418 #402 #290 #268 #105
curl -s https://quorum.stackclimb.com/status | jq '{build_sha, live_execution}'
  -> {"build_sha":"875839602aec3e0adba7aa0358fb679240fd8091","live_execution":false}
```

Both protected files confirmed present, unmodified:
`docs/analysis/2026-09-01-overnight-run.md`,
`docs/analysis/2026-09-01-402-freshness-gate-design.md`.

## Clubbing decision: W21 + W22

Clubbed into ONE package ("transport-harden the credential-bearing calls in
providers.py"), per AGENTS.md rule 17g. Reasoning verified from code, not
assumed:

- Both rows pin lines inside `src/product_app/providers.py` (W21:
  `urlopen(request, timeout=settings.openrouter_timeout_seconds)` in
  `_post_messages`; W22:
  `url=f"{settings.tavily_api_base_url.rstrip('/')}/search"` in
  `_tavily_search`).
- W21's board row names W18 as its dependency. W22 has no dependency but is
  the same defect class (a configured, operator-settable base URL that
  receives a bearer credential with no transport guard) as W18, which W21
  extends with a redirect guard.
- `src/product_app/credentialed_url.py`'s own module docstring (written for
  W18) explicitly names the Tavily gap: *"this covers the calls built from
  `OPENROUTER_API_BASE_URL`. It is NOT every credentialed request in the
  process — `providers._tavily_search` sends `Authorization: Bearer <the
  operator's Tavily key>` to `f"{settings.tavily_api_base_url}/search"` with
  no scheme guard at all... That is a different credential and a different
  setting, so it is board row W21's neighbour W22."* The author of the W18 fix
  already reasoned about both rows together and deliberately scoped W18
  narrower — but flagged W22 as the sibling gap, which is exactly the
  same-narrow-area signal rule 17g asks for.
- Rule 17 (one CONCERN per PR) still binds: this is not "club because small,"
  it is "club because it is one concern" — hardening outbound
  credential-bearing transport in one file against two related bypass
  vectors (scheme, redirect).

## Package log

### Package 1 — W21 + W22 (transport-harden credential-bearing calls in providers.py)

**Status: DONE — merged and verified running in production.**

- PR #419, squash-merged to `main`. Merge SHA `1c90615f0ca5fefadbd1ed322aaaeeebd71cef00`.
- close-guard: `PR=419 EXPECT_CLOSE=""` exit 0 (no GitHub issue to close for either row).
- Fix: `src/product_app/credentialed_url.py` extended with `CREDENTIAL_OPENER`
  (redirect-refusing opener, same shape as `readiness.py`'s `_KEY_PROBE_OPENER`)
  and `tavily_search_url()` (scheme guard reusing `is_credential_safe`).
  `providers.py`'s `_post_messages` and `_tavily_search` now dial through
  `CREDENTIAL_OPENER.open`, rebound under the name `urlopen` so all 16
  pre-existing tests that monkeypatch `providers_module.urlopen` kept working.
  New test file `tests/unit/test_credential_transport_guard.py` (16 tests,
  incl. 2 real two-socket redirect proofs). Mutation-proven: reverting to the
  bare `urlopen` + old f-string turned exactly the 4 fix-exercising tests RED,
  capturing a real leaked `Authorization: Bearer` header verbatim; restored
  via `cp` copy, `diff -q` clean (never `git checkout`).
- ADR: `docs/adr/0090-a-credential-does-not-follow-a-redirect-and-tavily-gets-the-same-scheme-check.md`,
  index regenerated.
- Review: 1 round (capped per rule 12, no blockers). Security reviewer found
  no CRITICAL_BLOCKER/REQUIRED_CONTRACT; ADVISORY_DEBT noted —
  `feedback_audit._call_audit_model` still uses bare `urlopen` with the same
  redirect exposure, correctly left out of scope and recorded as a follow-up
  in the ADR. Reuse reviewer found no blockers; corrected a "17 test files"
  off-by-one claim in the ADR (verified via grep) to the accurate 16.
- **What I (main orchestrator) personally re-ran and verified, independent of
  the sub-orchestrator's report:**
  - `gh pr view 419 --json state,mergedAt,mergeCommit` → `MERGED`, SHA
    `1c90615f0ca5fefadbd1ed322aaaeeebd71cef00` — matches the claimed merge SHA.
  - `gh run view 33503516318 --json jobs` → `Deploy to Fly.io` job
    conclusion `success` (also `Gate — require CI + Tests + E2E green for the
    SHA` → `success`).
  - `curl -s https://quorum.stackclimb.com/status` →
    `build_sha == 1c90615f0ca5fefadbd1ed322aaaeeebd71cef00` (exact match),
    `live_execution: false`.
  - `python3 scripts/check_open_work.py --check` → EXIT=0, board now
    **3 PENDING, 14 DONE** (was 5 PENDING / 12 DONE at session start — exactly
    +2 DONE, consistent with W21 and W22 both flipping).
  - `git worktree list` → only the main checkout remains;
    `git branch -a` → only `main` remains (branch deleted local + remote).
  - `ls -la` on both protected analysis files → sizes unchanged (21405 and
    37964 bytes) from the session-start check.
  - Also independently verified CI was genuinely green before authorizing the
    merge: `gh pr checks 419` showed all 6 required contexts
    (`validate-and-test`, `pytest (Python 3.12)`, `Changed-lines coverage >=
    95%`, `Schemathesis API contract`, `FR traceability completeness`, `e2e
    axe + parity (chromium)`) passing, cross-checked against
    `gh api repos/:owner/:repo/branches/main/protection --jq
    '.required_status_checks.contexts[]'` — the only failing check
    ("Mutation score on changed functions") is advisory and not in that list.
- No STOP condition. One process hiccup (not a defect in the work): the
  sub-orchestrator twice ended its turn to wait on a local `make diff-cover`
  run as if it were a long external wait; corrected via SendMessage to run it
  synchronously, after which it proceeded normally.

### Package 2 — #418 (board's Python needle checker fooled by a docstring)

**Status: DONE — merged and verified running in production.**

- PR #420 "fix(board): a docstring can no longer satisfy a Python needle
  (#418)", squash-merged. Merge SHA `0d5be18f2a831abf2e0fe67a082d8cf35103889a`.
- close-guard: `EXPECT_CLOSE="418"`, closed exactly `[418]`, exit 0.
- Fix: `.py` evidence files in `scripts/check_open_work.py` now route through
  `tests/code_text.py`'s `code_without_comments` tokenizer (loaded by path,
  mirroring the existing convention already used to load
  `check_open_work.py` itself — stdlib-only, no test-only dependency pulled
  into `make validate`). Non-Python evidence (W17, Markdown) unchanged.
- **Hazard #1 (row flips) — the important check.** All 17 Python-pinned
  needles were enumerated before and after the fix. **Zero net flips
  shipped** — every row read the same DONE/PENDING both before and after,
  independently confirmed by a reviewer who re-derived the same table from
  isolated `git archive` copies of both trees (not just re-reading the
  sub-orchestrator's table).
  - One flip DID occur transiently during development, and is the most
    interesting finding of this package: adopting `tests/code_text.py`
    exposed a **real pre-existing bug in that module** — its docstring
    detector misclassified a line-leading string inside a multi-line dict
    literal (e.g. `"stream": True,`) as a docstring, because `tokenize` emits
    `NL` inside brackets too. This flipped **W1 from DONE to PENDING**
    mid-fix. It was caught only because the brief required re-deriving all 17
    needles rather than trusting the diff, and was fixed in the same PR by
    requiring bracket depth 0 (new `_bracket_depths()` helper, with its own
    bite-proof test) before something counts as a docstring. Net effect on
    the shipped board: none (W1 reads DONE before and after the complete
    fix) — but the near-miss is exactly the class of silent-lie failure this
    package exists to close, and it would not have been caught without the
    explicit before/after enumeration this brief demanded.
- ADR: `docs/adr/0091-the-board-checker-tokenizes-python-instead-of-stripping-hash-comments.md`
  — confirmed present, records the layering decision (load-by-path from
  `scripts/`, not a `src/`-shared module or a reimplementation), rejected
  alternatives, the bracket-depth bug and fix, and one residual ADVISORY_DEBT
  (a bare string-literal expression statement outside any real docstring
  context is still misclassified — does not touch any of the 17 live
  needles, correctly left unfixed and merely recorded).
- Review: 1 round (capped per rule 12, no blockers surfaced). Both reviewers
  worked from isolated `git archive` copies per the read-only instruction.
- **What I (main orchestrator) personally re-ran and verified, independent of
  the sub-orchestrator's report:**
  - `gh pr view 420 --json state,mergedAt,mergeCommit` → `MERGED`, SHA
    `0d5be18f2a831abf2e0fe67a082d8cf35103889a` — matches.
  - `gh issue view 418 --json state,closedAt` → `CLOSED` at the same instant
    as the merge (`2026-09-01T12:36:36/37Z`) — confirms close-guard's claim,
    not just close-guard's own exit code.
  - `gh run view 33509727505 --json jobs` → `Deploy to Fly.io` conclusion
    `success` (also the pre-deploy gate job `success`).
  - `curl -s https://quorum.stackclimb.com/status` →
    `build_sha == 0d5be18f2a831abf2e0fe67a082d8cf35103889a` (exact match),
    `live_execution: false`.
  - `git log --oneline main..origin/main` / `origin/main..main` from the main
    checkout → confirmed both merge commits (`1c90615`, `0d5be18`) are on
    `origin/main`, and local `main` is ahead only by the 3 docs-only commits
    (no divergence, no missed rebase).
  - `python3 scripts/check_open_work.py --check` → EXIT=0, board
    **3 PENDING / 14 DONE** — unchanged from the end of Package 1, consistent
    with the claimed zero net flips (this fix touches no W-row's needle
    itself).
  - `grep -n "_bracket_depths" tests/code_text.py` → confirms the claimed
    bracket-depth fix genuinely landed in the file, not just described in
    the ADR/PR prose.
  - `git worktree list` / `git branch -a` → only the main checkout and
    `main` branch remain.
  - `ls -la` on both protected analysis files → sizes unchanged (21405 and
    37964 bytes).
- No STOP condition. Same process hiccup as package 1 (not a defect in the
  work itself): the sub-orchestrator twice ended its turn to wait on a local
  `make quality`/gate run as if it were a long external wait; corrected via
  SendMessage to run gates synchronously, after which it proceeded normally
  through review, PR, merge and deploy verification without further
  intervention.

(entries appended below as each package closes)

---

# Session 2 (continuation, same date) — #402 and #290

Appended by a second unattended orchestrator run on 2026-09-01, continuing this
file because the date matches. Session 1's entries above are unchanged.

## Session 2 summary

- **Shipped and verified running in production:** PR #421 — `#402`, the board
  anchor is checked against a `main`, not against `HEAD`. Merge SHA
  `bc1f1a1965b15af8fbcf2eff26772899eab0d2c8`. `#402` CLOSED.
- **Starting state re-verified before any work** (not assumed): `origin/main` =
  `0d5be18f…`, prod `build_sha` identical, `live_execution: false`, board
  `22 rows (3 PENDING, 14 DONE)` EXIT=0, local `main` ahead 5 (docs-only, prior
  run), all three protected analysis docs present, open issues #402 #290 #268
  #105. The six required merge contexts were re-derived from
  `gh api …/branches/main/protection` (AGENTS.md rule 14) rather than trusted
  from the table.

## Package 3 — #402 board-anchor freshness gate (attempt #3)

**Outcome: SHIPPED.** The two prior attempts (recorded in
`docs/analysis/2026-09-01-402-freshness-gate-design.md`) were each stopped under
rule 12. This one closed inside the two-round cap.

### What was built

A second, independent gate family `check_anchor_is_on_main`, leaving
`check_freshness` untouched — so the pair is strictly stronger than before, not
a replacement whose regressions could be invisible. The anchor must be an
ancestor of at least one `main` the checkout can actually resolve:
`refs/remotes/origin/main`, then any other remote's `main`, then local
`refs/heads/main` as a fallback rather than a peer.

It asks which refs **exist**, never which refspecs are **configured**. That is
the §9 shape, and it makes §12's four refspec-parsing disagreements structurally
unreachable.

### The one deliberate deviation from §9, flagged not repaired silently (rule 3)

§9 says *skip* whenever no `main` resolves. The sub-orchestrator measured that a
`--single-branch --branch <feature>` clone has **no `main` ref of any kind**, so
§9-as-written would skip requirement 3's exact shape — failing open precisely
where a branch-only anchor is most likely to be typed. It split the skip
population by *why* the answer is missing:

- no remote at all and no local `main` → **skip, out loud**;
- a remote present but no `main` ref → **refuse**, with a remedy it measured.

This is fail-closed where §9 was fail-open. Design A's fault in this area was
never the refusal — it was that its printed remedy did not work.

### Independent verification — what I (main orchestrator) ran myself

Everything below is my own command output, not the sub-orchestrator's report.

- `gh pr view 421` → `MERGED`, mergeCommit `bc1f1a19…`; `gh issue view 402` →
  `CLOSED` / `COMPLETED` at `2026-09-01T16:50:14Z`, one second after the merge.
- `git rev-parse origin/main` → `bc1f1a1965b15af8fbcf2eff26772899eab0d2c8`.
- Seven runs for that SHA, enumerated **both** ways (`--commit` and
  `--branch main` with a SHA match — rule 18a's trap) and agreeing exactly:
  `CI: success`, `Tests: success`, `E2E (axe + parity): success`,
  `CSP smoke: success`, and three `Deploy to Fly.io` — two `cancelled` by
  concurrency, newest (`33535412368`, by `createdAt`) `success`.
- **The Deploy JOB, not the rollup**:
  `gh api …/runs/33535412368/jobs` → `Gate — require CI + Tests + E2E green
  for the SHA: success` and `Deploy to Fly.io: success`.
- `curl /status` → `build_sha == bc1f1a1965b15af8fbcf2eff26772899eab0d2c8`
  (exact match to the merge SHA), `live_execution: false`. `/ready` → 200.

### The bite-proof I ran myself (this is the part that matters)

The sub-orchestrator's mutation table is its evidence. This is mine: a clone of
the repo, `origin/main` set to the merged SHA, HEAD on a feature branch, a real
branch commit `c5f13b3`, and the board's `Verified at:` stamped to it — PR
#399's exact mistake.

| Script under test | Result |
|---|---|
| **OLD** (`0d5be18`, pre-fix) | `EXIT=0` — accepts it. **The bug, reproduced.** |
| **NEW** (`bc1f1a1`, merged) | `EXIT=1` — `anchor commit c5f13b3005e1 is not on any 'main' this checkout can see` |

Same repository, same board, same anchor, one file different. Reverting the fix
turns it green, so it is a test that can fail.

Positive and negative partners in the shapes that decide it, all mine:

| Shape | Report line | Exit |
|---|---|---|
| full clone, valid anchor | `anchor on refs/remotes/origin/main` | 0 |
| no remote, local `main` present | `anchor on refs/heads/main` | 0 |
| no remote **and** no `main` anywhere | `squash-survival SKIPPED (no remote and no 'main' ref here)` | 0 |
| remote present, no `main` ref | `squash-survival REFUSED (no 'main' ref)` | 1 |
| true `--single-branch` clone, after remedy, **branch-only** anchor | `anchor on no known 'main'` | 1 |
| true `--single-branch` clone, after remedy, **valid** anchor | `anchor on refs/remotes/origin/main` | 0 |

The last two are the §5 discipline both prior designs lacked: a skip/refuse path
whose positive partner varies *the dimension the check is about* — "is this
anchor branch-only?" — inside the same shape.

The gate never reports a bare pass: it names which ref it measured against, or
says out loud that it skipped. A negative check that states what it counted
(the standing complaint in AGENTS.md's gate section).

### The remedy it prints — verified, because Design A's did not work

Built a **true** `--single-branch --branch feat` clone (refspec
`+refs/heads/feat:refs/remotes/origin/feat`, `origin/main` and local `main` both
ABSENT) and ran the message's own claims:

- `git fetch origin main` → exit 0, `refs/remotes/origin/main` still **ABSENT**.
  The message's claim is correct.
- `git remote set-branches --add origin main && git fetch origin` → ref
  **PRESENT**, and `remote.origin.fetch` becomes **two lines** with `main` on
  the second — the exact §12 trap that killed Design B. The shipped design has
  no refspec parsing to be fooled by it:
  `grep -n "remote\..*\.fetch\|fnmatch" ` → **0 hits** (three `splitlines`
  hits exist but are board-text parsing, not git config).

One nuance I chased and resolved: in an artificial hybrid (wildcard refspec,
ref merely deleted) `git fetch origin main` **does** restore the ref, so the
message's "does NOT create it **here**" is shape-dependent. That hybrid is not a
clone shape git produces, and the message's second remedy works in both, so
nobody is stranded. Recorded as accurate-in-practice, not as a defect.

### Review

Two rounds, both producing reproduced findings — two `CRITICAL_BLOCKER` false
acceptances, both fixed: (a) `git remote`'s exit code was ignored, so one
invalid refspec made a checkout that *held* `origin/main` read as "no remote",
and accept a branch-only anchor — reachable from the gate's own printed remedy;
(b) `git checkout main && git merge --ff-only feature` laundered the branch
commit onto local `main` and the gate passed it. Also one `REQUIRED_CONTRACT`
(two vacuous mutants), four `ADVISORY_DEBT` fixed, one accepted and recorded,
one equivalent mutant documented in code.

Two mutants survived the first mutation round and were fixed: both were in
operator **text** (the remedy commands, and the "stamp what you were cut FROM"
advice), not control flow — Design A's exact defect class, caught this time.

### Housekeeping verified after the fact

Local `main` still carries its **5** unpushed docs-only commits (`fc5bff4` at
tip), now `ahead 5, behind 1` — expected, since the merge landed on
`origin/main`. `git branch -f main origin/main` and `git merge --ff-only` were
**not** run, per this run's brief. All three protected analysis docs present and
unchanged in length. 6 stashes unchanged. Only untracked file is the run prompt.
Worktree removed, branch deleted local and remote — `git worktree list` shows
one entry, `git branch --list` shows only `main`, `git ls-remote --heads origin`
shows no `402` branch. One reviewer did create and delete a stray `feat.txt` in
the shared checkout; the working tree is clean, so nothing survived.

### UNVERIFIED, carried forward honestly

- That a `pull_request` build checks out `refs/remotes/pull/N/merge` detached
  (run `33507457668`) is **[sub-orchestrator's reviewer only]**; neither it nor
  I opened that log. It bounds two residual local-only false acceptances.
  Settles with `gh run view 33507457668 --log | grep 'git checkout'`.
- PR #399's original failure tally is inherited from the postmortem, not re-run.

## Package 4 — #290 peer critique (bounded to design; `#290` stays OPEN)

**Outcome: SHIPPED as a design record.** PR #422, merge SHA
`d860b2a95e371e81add7f517a01c253d2894ac15`. `#290` deliberately left OPEN —
`close-guard` run with `EXPECT_CLOSE=""` and it reported *"closes exactly the
expected set: nothing"*.

### Three stale premises in the brief, found and reported rather than repaired silently (rule 3)

The brief I wrote for this package was wrong on three counts. All three were
caught by the sub-orchestrator and confirmed by me:

1. **The paid probe I forbade had already been run — with the owner's
   authorisation.** Issue #290's own comment records it: 2026-08-26, budget of
   10 calls, **8 used, $0.034170**, worst per-`recv` gap **25.055 s** on
   `openai/gpt-4o-mini` against `openrouter_timeout_seconds = 8.0`. Verified by
   me with `gh issue view 290 --comments`. Its verdict was acted on by board row
   W1, which made the provider call streamed (ADR-0084): I read
   `providers.py:1264` at `origin/main` and it is `"stream": True`,
   **unconditional, exactly one occurrence in the file**. So the STOP condition
   my brief was built around was already settled months ago.
2. **The billing change was already merged** — ADR-0037. I read
   `debate.py:933-936`: `result.usage.model_copy(update={"model_id":
   settings.debate_model_id})`. The field exists and is stamped.
3. **ADR-0092 was already taken, and that collision was MY error.** I assigned
   `0092` centrally to avoid exactly this — but I ran `ls docs/adr/` in the main
   checkout, whose local `main` (`fc5bff4`) *predates* the #402 merge. I read a
   stale tree and handed out a number PR #421 had already used. The
   sub-orchestrator caught it, filed **0093**, and said so in the ADR, the
   commit and the PR. Both `0092` and `0093` are on `origin/main`; no collision
   shipped. `docs/24-adr-index.md:98-99` lists both.

### One premise of mine the code refuted outright

My brief told it to design for "two slot models that are the same `model_id`".
`model_slots.py:378-386` **rejects that outright** — *"Model IDs must be unique
across all four slots."* I read it myself. The genuine duplicate is
moderator-versus-slot, and it ships by default. Designing against my framing
would have been building for an unreachable state.

### What shipped

- `docs/adr/0093-…` — `DebateOutput` keeps one element per round with peer
  detail nested behind a `critique_shape` discriminator; the usage tuple does
  **not** widen; critique spend gets its own `kind="critique"` row (flagged as
  needing the product owner).
- `docs/analysis/2026-09-01-290-peer-critique-failure-modes.md` — the rule 16e
  enumeration.
- **The only `src/` change is a comment.** I ran
  `git diff bc1f1a1 d860b2a -- src/` → `providers.py | 7 insertions, 2
  deletions`, and read the hunk: a `#:` docstring on `TokenUsage.model_id` that
  falsely claimed `synthesis.py` stamps the field. It does not —
  `grep -c "TokenUsage(" synthesis.py` → **0**; it never builds one. No
  behaviour change.

### The rejected alternative, verified not restated

The issue claims one row per `(round, model)` breaks `app.js`, which keys a Map
by round number. I read `app.js:1829` myself before writing the brief:
`const byRound = new Map(debate.map((r) => [r.round_number, r]));` — **true**.
The ADR adds that it *understates*: five consumers read `debate_outputs` and
only that one fails silently; `app.js:4816` would tell a user a 2-round run had
"8 rounds".

### Review

Two rounds. **Two CRITICAL_BLOCKERs, both real, both fixed by changing the
design** — not by patching it: (a) the first draft's "derived digest" falsified
`SYNTHESIS_DEBATE_EXCERPT_MAX_CHARS` and would silently drop ~3 of 4 **paid**
critics; (b) `_debate_signals_convergence` (`synthesis_consensus.py:641` —
exact line confirmed by me) reads `critique_text` and returns `"strong"`, so
pooling four critics lets any one flip the panel and bypass #185's guard. Root
cause named honestly: the consumer census enumerated *renderers* and stopped.
The ADR now separates renderers (read the digest) from deciders (read the
critics). Five REQUIRED_CONTRACT findings folded in; ~14 of its own prose
citations were wrong and were re-grepped and corrected.

### Independent verification — my own commands

- `gh pr view 422` → `MERGED`, mergeCommit `d860b2a9…`;
  `gh issue view 290` → **`OPEN`**.
- 8 runs for the SHA: CI / Tests / E2E / CSP all `success`, three
  `Deploy to Fly.io` — two `cancelled` by concurrency, newest
  `33542756121` — and the **JOB**, not the rollup:
  `gh api …/runs/33542756121/jobs` → `Gate — require CI + Tests + E2E green:
  success`, `Deploy to Fly.io: success`. Plus `Deploy drift watchdog: success`.
- `curl /status` → `build_sha == d860b2a95e371e81add7f517a01c253d2894ac15`
  (exact), `live_execution: false`, `judge_enabled: true`. `/ready` 200.
- **The #402 gate shipped last package, re-run at THIS deployed SHA in a
  post-merge `main` shape**: `EXIT=0`,
  `anchor on refs/remotes/origin/main`. It measured and passed — the new gate
  did not turn `main` red, which was the whole risk of shipping it.
- Six code citations sampled and confirmed at `origin/main`:
  `providers.py:1264`, `debate.py:935`, `model_slots.py:378-386`,
  `synthesis.py:203`, `synthesis.py` TokenUsage count = 0,
  `synthesis_consensus.py:641`.
- No spend: `config.py` → `openrouter_live_execution_enabled: bool = False`,
  and production reports `live_execution: false`.

### Housekeeping

Local `main` at `98fc678`, **ahead 6 / behind 2** — the 5 prior-run docs commits
plus my Package 3 log entry, all intact and unpushed.
`git branch -f main origin/main` and `git merge --ff-only` were **not** run.
All three protected analysis docs present. 6 stashes unchanged. One worktree,
one branch, no leftover remote branches. My own scratch clones deleted by name.

### UNVERIFIED, carried forward

- **Whether the streamed transport carries a real production run.** The board's
  own words for W1: *"latent-correct, not observed"*
  (`docs/65-open-work.md:651-655`). This is the human-gated step that remains —
  and it is **not** a latency probe; that one is done and paid for. It needs an
  owner-authorised live-execution window.
- That a `kind="critique"` row renders end to end (`app.js:6519`'s ternary was
  read, not executed). Settling it is build work.
- The ×1.25–×1.41 cost projection is arithmetic, not measured (ADR-0081's own
  label). W3 stays STOP.

## Package 5 — the #268 measurement window (owner-approved, attended)

**Outcome: SHIPPED and CLOSED.** Three PRs, all merged, deployed and verified.
`#268` stays open; this collected data, it did not move the constant.

| PR | Merge SHA | What |
|---|---|---|
| #423 | `470156f` | publish the #402 postmortem ADR-0092 already cited |
| #424 | `ae9865f` | open the declared window, flag → `true` |
| #425 | `014b010` | `make close-window`, flag → `false`, result recorded |

### The recommendation I had to retract before spending

I first told the owner W1 streaming was unmeasured and worth ~$0.16 to settle,
reading `docs/65-open-work.md:651` — *"latent-correct, not observed"*. **That
prose was two days stale.** Commit `64a3b14` (2026-08-31) had already closed a
window that measured it: `usage_absent: false` and `stream_terminator: "done"`
on **24 of 24** calls, and the W1 row itself already read `DONE`. I should have
read the commit log before recommending a spend. Second number I corrected for
the owner in this session; the first was the $5.00/day public exposure that my
"$0.16" had understated by 30×.

**What was genuinely unmeasured** was `#268`'s input-token distribution: n=8,
and `docs/analysis/2026-08-26-b3-timeout-probe.md` says of it *"a start, not a
bound: every row shares one query, one prompt size and one day."* The window
was re-aimed at that.

### De-risking that cost nothing

Everything was rehearsed against a LOCAL instance with live execution off, so
the first money spent was on a flow already proven end to end:

- The API contract, learned rather than assumed: `GET /v1/session` mints the
  cookie and a `csrf_token`; `POST …/estimate` and `POST /v1/query-runs` need
  `x-csrf-token` **and** a `safety_acknowledgements` entry. Three separate
  refusals (`AUTH_REQUIRED`, `CSRF_INVALID`, missing acknowledgement) were
  found and fixed for free.
- `SESSION_MINT_CAP_PER_IP = 2` — only two cookie-less `/ui` boots per IP per
  24h in production. The rehearsal deliberately did not spend one.
- Production telemetry proved readable BEFORE opening the window
  (`flyctl ssh console -C "wc -l /data/telemetry-tokens.jsonl"` → 54). A window
  that produced unreadable data would have been pure loss.
- Baseline captured for a clean pre/post split: 54 records, 20 `:online` calls
  carrying `injected_tokens_est`.

### One prediction of mine that executing refuted

From `costs.py:26` and `:878` I concluded the daily meter charges the POINT
estimate, so three runs at `$0.0677` = `$0.2032` could not fit under
`DAILY_CAP_USD = $0.20`, and planned for two. Rather than route around the cap
by minting a second account — which the mint budget allowed and which would
have been my decision to make, not the owner's — **I submitted the third run
and let the guardrail adjudicate. It was ADMITTED.** So the meter reconciles to
ACTUAL spend after a run completes, and my reading of it was wrong. Verify by
executing, including against your own reasoning.

### What the window measured

| Question shape | Actual | Elapsed | Slots live | Receipt |
|---|---|---|---|---|
| broad comparative | `$0.0672` | 101.4s | 4/4 | `measured` |
| ambiguous low-signal | `$0.0518` | 73.8s | 4/4 | `measured` |
| narrow factual | `$0.0459` | 63.3s | 4/4 | `measured` |

**Total actual spend `$0.1649`**, against a `$0.1917` estimate budget. Every run
`cost_source: measured`, zero `failed_steps`, zero simulated slots — so no call
fell back and no timeout demoted a receipt to `estimated`. That is a second,
incidental confirmation of the streamed transport under real search-heavy load.

### For #268 — the actual finding

12 new `:online` calls (3 runs × 4 slots, exactly as expected):

```
-63  2353  2370  2449  2477  2500  2520  2570  2595  2668  2719  2890
```

**11 of 12 exceed `cost_web_search_context_tokens = 2000`**, by up to 44%
(max 2890). Under-estimating input is the FAIL-OPEN direction, because the cost
guardrail keys off the estimate. Combined with the baseline that is **n=32
across four question shapes, 27 over** — where before it was one shape.

The constant is **NOT** moved. ADR-0081 freezes that class pending a measured
bound; W3 stays STOP.

### A defect in my own analysis, found and corrected mid-flight

My first extraction used `grep -o '"injected_tokens_est": *[0-9][0-9]*'`, which
**silently drops negative values** — and many records carry them (a provider
reporting FEWER input tokens than were sent). The first distribution I produced
was therefore a filtered subset presented as the whole. Re-derived by parsing
JSON instead of pattern-matching it, which is AGENTS.md rule 8 (assert
structure, not substrings) applying to analysis, not just to tests. One
`:online` call is genuinely negative: `-63` on `google/gemini-2.5-flash:online`.

### Safety verification, all mine

- Window OPEN only from the `ae9865f` deploy (20:53Z) to the `014b010` deploy
  (~21:47Z) — **~54 minutes**, inside a declared 19:57Z–22:57Z window, closed
  early rather than left to expire.
- `make close-window` performed the atomic revert; the flag alone cannot be
  flipped back while a window covers `now` (#407).
- Deploy JOB (not the rollup) `success` on all three merges;
  `33557939325`, `33562260104` read individually.
- Production final: `build_sha 014b010…`, **`live_execution: false`**,
  `judge_enabled: true`.
- `gh issue list --label live-posture --state open` → **empty**. The watchdog
  raised no alert, so the posture never outlived its declaration.
- Both windows in `origin/main`'s declaration file parse as `closed`.

## Package 6 — the stale documents that caused the wasted recommendation

**Outcome: SHIPPED.** PR #426, merge SHA `c5de16f`, deployed and verified.

Three stale claims in two files, each verified false against the tree before
being touched:

| Claim | Where | Refuted by |
|---|---|---|
| W1 is *"latent-correct, not observed"* | `docs/65-open-work.md:651` | `64a3b14` measured 24 of 24 calls on 2026-08-31; the W1 row already read `DONE` |
| an owner window is *"the step between W1 and W2"* | same paragraph | that step has now run twice |
| the #268 sample is *"n=8 on one question shape"* | `2026-08-26-b3-timeout-probe.md:137` | second window ran three varied shapes; now n=32 across four |

The first of those is the one that cost something: it is what I read when I
recommended spending money to measure something already measured.

**What replaced them.** The board now names both windows and what each
measured, and states that **W2 is PENDING because it is UNBUILT, not blocked** —
its dependency on W1 is discharged — while **W3 stays STOP for an unrelated
reason**, ADR-0081's owner decision rather than any measurement. The probe doc
got a SUPERSEDING section rather than an edit, so the original reasoning stays
readable beside what replaced it.

**The old wording is quoted, not deleted.** `docs/65-open-work.md:661` keeps
*"latent-correct, not observed"* inside a sentence explaining that it stood for
two days and caused a spend recommendation. A `grep` for the phrase therefore
still matches once, deliberately — checked, so a future reader does not read
the quote as a surviving claim.

**Verified by me:** `make quality` exit 0 (`4016 passed, 67 skipped`),
`make validate` exit 0, `check_open_work.py --check` exit 0
(`22 rows (3 PENDING, 14 DONE) … anchor on refs/remotes/origin/main`, anchor at
drift 13 of 60 so no re-stamp), all 11 CI checks green, Deploy JOB (not rollup)
`success` on run `33595537213`, prod `build_sha c5de16f…` with
`live_execution: false`.

## Package 7 — the owner's decision on ADR-0093, recorded

**Outcome: SHIPPED.** PR #427, merge `b218526`, deployed and verified.
`#290` still **OPEN**; nothing built, build not scheduled.

The owner signed off decision 3 on 2026-09-02 and added two more. The ADR now
records **why**, not just that.

- **3 (approved as written).** One `kind="critique"` row per critic. The owner's
  framing — a debate that used to be one moderator becomes four models actually
  debating, so the spend sits with the models that earn it — admits **two**
  spellings, and the choice was not cosmetic: folding critique into each model's
  existing row satisfies the framing but makes a critique's cost unrecoverable
  from its answer's. The board freezes **W3** until *"#290 is built and its cost
  is measured"*, so that spelling would leave the feature W3 waits on unable to
  unblock it. One-way door, too.
- **4 (new).** Rename the writer row to `Synthesis`. §Consequences already held
  the sharper fact — under a fully-eligible peer run that row holds **no debate
  spend at all** — and had deferred the rename to this review.
- **5 (new).** `query_run_id` + `stage`/`round` on the telemetry record, in the
  **same** work package. Peer critique takes the file from one debate call per
  run to eight, from four models that also appear as answerers.

### Two errors of mine, caught before they reached the ADR

- I first wrote that per-model **per-round** data was already available from
  telemetry. It is not: `query_run_id`, `stage`, `round`, `slot_number`,
  `finish_reason` and elapsed are all absent from `TELEMETRY_FIELD_NAMES`
  (grep, zero hits each). I had even *seen* `query_run_id` print as `None` for
  every row earlier in this session and not registered it. Correcting it is what
  produced decision 5, so the error was worth more than the claim would have
  been.
- I nearly cited the wrong "seven of eight". The `finish_reason: "length"`
  figure is from the **#290 probe comment**; `b3-timeout-probe.md:87` carries an
  unrelated seven-of-eight for **wall-clock timeout exceedance**. Two different
  measurements sharing a ratio — the ADR now says so explicitly so nobody merges
  them later.
- Also mis-cited the rename's origin as §"Rejected alternatives"; it is
  §Consequences. Found by grepping for my own claim before shipping it, which is
  the only reason it did not ship wrong.

**Verified by me:** `make quality` exit 0 (`4016 passed, 67 skipped`),
`make validate` exit 0, `check_open_work.py` exit 0, `make diff-cover` measured
nothing and said so, all 11 CI checks green, close-guard *"closes exactly the
expected set: nothing"*, Deploy JOB (not rollup) `success` on run `33603928027`,
prod `build_sha b218526…` `live_execution: false`, all four decision headings
present at the deployed SHA, `gh issue view 290` → **OPEN**.
