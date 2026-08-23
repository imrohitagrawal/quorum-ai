# ADR-0066: A negated issue close is caught in the two places it can happen

## Status

Accepted — 2026-08-24.

## Context

### The defect, five times

GitHub closes an issue when a close keyword (`close`/`closes`/`closed`,
`fix`/`fixes`/`fixed`, `resolve`/`resolves`/`resolved`) sits immediately before
`#<number>` in a commit message, a pull-request title or a pull-request body.
**Its parser has no concept of negation.** The sentence "This does NOT close
#337" contains "close #337", so the issue closes — saying the exact opposite of
what the author wrote.

**Six such texts have named five issues here, and four of those issues actually
closed.** (`tests/unit/test_close_keyword_guard.py` pins all three numbers.) Every row was re-verified from the GitHub API on 2026-08-24 with
`gh api repos/:owner/:repo/issues/<n>/timeline`, reading the `closed` event:

| Issue | Text that did it | Surface | Closed? | Evidence |
|---|---|---|---|---|
| #175 | `Filed, not fixed: #175 (whitespace ...` | commit `e6c84ea` (PR #174) | yes | close event `commit_id: e6c84ea` |
| #185 | `not fixed: #185, #171, #178, #180, #182` | commit `0ace31e` | yes | close event `commit_id: 0ace31e` |
| #268 | `This does **not** close #268.` | PR #282 body | yes | `closingIssuesReferences: [268]`, close event `commit_id: null` |
| #268 | `This does NOT close #268: the ...` | commit `8ca6a98` (the same PR's merge) | — | the same issue, on the other surface |
| #337 | `**This does NOT close #337.**` | `gh pr merge --body` (PR #360) | yes | close event `commit_id: 4ea57ba` |
| #105 | `does not close #105, #268 or #203` | PR #289 body | **NO** | caught by a manual grep before merge; `gh issue view 105` still reports `state=OPEN, closedAt=null` |

**Say "four issues closed", not "five".** The first draft of this record said
five in four different files while its own evidence column said #105 never
closed; a reviewer caught it, and `CLOSED_BY_A_NEGATED_SENTENCE` in
`tests/unit/test_close_keyword_guard.py` now pins the set so the sentence and
the corpus cannot drift apart again.

The #185 case was **not** in the brief for this work. It was found by running the
classifier over all of history, which is the argument for building the
measurement before the mitigation.

Note what GitHub does *not* do, which matters for how narrowly the guard must
match: in the #185 case only `#185` closed. `#171`, `#178`, `#180` and `#182`
follow commas rather than the keyword, and each was verified closed by something
else (`commit_id: null`, or a different commit). The same held for `#176`/`#177`
in the #174 case. **Only the number directly after the keyword closes.**

### Two surfaces, and neither check covers the other

* For PR #282, GitHub's own parse — `gh pr view 282 --json
  closingIssuesReferences` — reported `[268]` **before** the merge. The
  authoritative signal existed and nobody looked at it.
* For PR #360, the same query reports `[]`. A clean bill of health. The damaging
  sentence lived in the `gh pr merge --body` text, which is **not part of the
  pull request at all**, and it still closed #337.

So GitHub's authoritative API is necessary and **not sufficient**. Any guard that
only inspects the pull request is blind to the exact case that most recently bit.

### The premise this record refutes

The work was commissioned on the belief that `fix(#337):` — the
conventional-commit *scope* slot in PR #360's merge subject — was the vector, and
that the bracket form is therefore a never-legitimate shape worth flagging.
**Measured, it is neither.**

* `fix(#N)` appears in **10** commit subjects on `main`
  (`git log origin/main --format='%s' | grep -E '^fix\(#[0-9]+\)'`).
* Three of them — `68d8b69` `fix(#148)`, `5bbe616` and `15c365c` `fix(#226)` —
  carry **no other close-shaped reference** to that issue; `15c365c` does mention
  it once more, as `#226 stays OPEN for PR 2.`, which closes nothing. In none of
  the three did the commit close the issue.
* The decisive one: issue #148 was closed on **2026-08-02** with
  `commit_id: null`; its `fix(#148)` commit landed **2026-08-19**, seventeen days
  *later*. The bracket form cannot have closed it.

The real vector in PR #360 was the other line in the same merge body:
`**This does NOT close #337.**`

Had the guard been built to the original brief it would have produced **ten**
false positives against real history and **missed the sentence that did the
damage**. The bracket form is deliberately not flagged.

### A commit-message check on `main` can never block

`.github/workflows/ci.yml` triggers on `push: branches: [main]` and produces the
`validate-and-test` job, which is one of the six required status checks;
`.github/workflows/deploy.yml` gates deployment on the "CI" workflow concluding
successfully for that SHA. A commit message is **immutable** — no edit can turn a
failing message check green. A blocking check on the merged message would
therefore strand the deploy over a cosmetic error, with no way to fix that SHA —
until some later commit supersedes it (`scripts/deploy_gate.py` only treats a
SHA as stranded while it is `main`'s tip) or an operator reaches for
`deploy.yml`'s `workflow_dispatch` escape hatch. Neither is a remedy anyone
should need for a typo. This is why layer 3 below reports and does not block,
and it is a structural fact, not a preference.

## Decision

Three layers. They are not equivalent, and the record is explicit about which is
enforcement and which is discipline.

| # | Surface | Runs | Kind | Blocking |
|---|---|---|---|---|
| 1 | PR title + body | `validate-and-test`, `pull_request` only (incl. `edited`) | **Enforcement** | **Yes** |
| 2 | the exact `gh pr merge --subject`/`--body`, plus GitHub's parse of the PR | `make close-guard`, by hand before merging | **Discipline** | No — and it cannot be |
| 3 | the tip commit message on `main` | `validate-and-test`, `push` only | Backstop | No — see above |

**Layer 1 is legitimately blocking** because the author can edit the title or
body and go green. It lives as a step inside the existing `validate-and-test`
job rather than as a new job, so it inherits that job's required-context status
with **no branch-protection change**, and it runs before `uv sync` so the answer
arrives in seconds.

`ci.yml`'s `pull_request` trigger now names its activity types explicitly,
**including `edited`**, which is not a default — GitHub runs a workflow on
`opened`, `synchronize` and `reopened` only. Without it, a body edited after the
last push is never inspected while GitHub still parses it at merge time.
Measured over the last 60 merged pull requests: 12 had title or body edits (33
edits in total) and **7 landed their last edit after the last commit push** —
including **PR #289 itself**, edited 25 minutes after its final push and merged
15 minutes later with no CI run in between. The cost is roughly half an extra
CI run per pull request, on a public repository where Actions minutes are free.

**Layer 2 is the only layer that can stop the PR #360 class before the damage**,
and nothing can force it to run. CI never sees the merge text. Calling it a gate
would be a lie; it is a safety catch that has to be remembered.

Its `make` recipe passes the subject and body **through the environment and
never through a make variable**. The first version expanded them into `/bin/sh`,
which a reviewer used to execute a command from a crafted body — and which could
not parse PR #360's *real* merge body at all, the single text the layer exists
for, because that body contains 30 backticks and 6 double quotes. A layer that
cannot read its own motivating case is worse than absent, since it reports an
error that looks like a tooling problem rather than a finding.

**Layer 3 cannot block** for the reason given above. It writes into the job
summary so that damage is visible the moment it lands, instead of being
discovered weeks later by an issue that is mysteriously closed.

### What is matched, and what is deliberately not

Only a close reference whose own clause **negates** it. Concretely: a negation
word within three words before the keyword, stopping at a clause boundary
(`.`, `!`, `?`, `;`, `:` **or a comma** — see below for newlines), with markdown
emphasis (`*`, `_`, `` ` ``) ignored because GitHub ignores it too — the live
PR #282 body is `This does **not** close #268`.

**References inside markdown code are skipped entirely**, because GitHub skips
them. Measured rather than assumed, on 2026-08-24: PR #361's own body was edited
to carry `` `Closes #148` `` inside an inline span and inside a fenced block, and
`gh pr view 361 --json closingIssuesReferences` returned `[]`; the positive
control, the identical text as plain prose, returned `[148]`. Without this the
guard blocks any pull request that documents it — this very ADR quotes the
corpus and carries 13 references that GitHub would never act on.

A **single newline is not a boundary; a blank line is.** git wraps a commit body
at about 72 characters, so `does NOT\nclose #337` is the ordinary shape of the
sentence this exists to catch — treating every newline as a boundary disarmed
the guard on it entirely. Treating no newline as a boundary is equally wrong: it
let the walk reach out of `Closes #258.` into the subject line above and find
the `nothing` in *"a judge that produced nothing"*, producing two false
positives on real commits (`b904ce6`, `9cfda0e`). A blank line separates a
commit subject from its body and one paragraph from the next; a line wrap
separates nothing.

A bare `Fixes #123` is the correct and common way to close an issue and is left
alone. The comma boundary is what keeps `With no regressions, closes #123` clean
while `Filed, not fixed: #175` still trips.

## Measurements

All hermetic, `$0`, no provider call.

```
$ python3 scripts/check_close_keywords.py --scan-history origin/main
4ea57ba6  #337  **This does NOT close #337.** ...
8ca6a984  #268  This does NOT close #268: the `cost_system_prompt_tokens` /
0ace31ee  #185  not fixed: #185, #171, #178, #180, #182 (unrelated, ...
e6c84eae  #175  Filed, not fixed: #175 (whitespace completion served as ...

examined 344 commit message(s) on origin/main; 4 flagged
```

| Measure | Value |
|---|---|
| Commit messages examined on `main` | 344 |
| Closing references found (the positive partner) | 68, across 56 commits |
| Legitimate closes left alone | 64 |
| Negated closes flagged | 4 commits — every one a real defect |
| False positives over all of history | **0** |
| Real texts flagged | 6 of 6 |
| Clean-corpus items wrongly flagged | 0 of 13 |
| Mutations applied to the checker and its wiring | 40, **all RED**, 0 survivors |

And on the **other** surface layer 1 actually gates, which the first draft did
not measure at all:

| Measure | Value |
|---|---|
| Pull requests examined (title + body) | 242 |
| Closing references found | 67, across 59 PRs |
| Flagged | **1** — PR #282, the true positive |
| False positives | **0** |

The two pull-request-body texts (#282's and #289's) do not appear in the commit
scan and are pinned as literals in `tests/unit/test_close_keyword_guard.py`.

**Method, so the figure is reproducible rather than asserted:** each mutation
edits one named line (a constant, a regex, a boundary character, a workflow
`if:`, a Makefile recipe), then `uv run pytest
tests/unit/test_close_keyword_guard.py` runs and the file is restored from a
`cp` taken beforehand, with `diff -q` confirming the restore. `__pycache__` is
cleared between runs — without that, a restored file keeps its original mtime
and Python silently reuses the mutant's bytecode, which produced a wrong table
the first time this was measured.

**Seventeen of those 40 survived on first attempt**, across two review rounds,
and they are recorded because the fixes are the interesting part:

* Ten mutations of the negation and boundary logic survived because every real
  text happens to use plain `not`: the negation set could be reduced to one
  word, the emphasis set to one character, and `:`/`;`/`!`/`?` could each be
  deleted from the clause boundary. The corpus now carries a synthetic entry per
  member, and a test refuses any member no text exercises.
* `_LOOKBACK_WORDS` could be set to 1, 4, 5 or 1000 undetected. Both bounds are
  now pinned with literals on either side.
* Widening the keyword set to the gerund `closing` — which GitHub does not
  honour — went undetected because the suite asserted only that such text was
  not *flagged*, never that it was not a *reference*.
* Flipping the pull-request step's `if:` from `==` to `!=` survived a substring
  assertion. Not cosmetic: it would run the blocking step on every push to
  `main` with the variables unset, exit 2, and redden a required context.
* The blocking lane could be silently downgraded by adding `continue-on-error:
  true` or appending `--advisory`, and the Makefile's `$(BODY)` denylist was
  walked past with the identical `${BODY}` spelling, restoring both the
  injection and the silent text loss. The recipe test is now an allowlist.

## Rejected alternatives

1. **Flag every close keyword adjacent to `#N`.** Measured: 68 firings over this
   history, 64 of them correct closes. A gate that is wrong 94% of the time is
   routed around within a week, and it also trains people to ignore a red
   signal — worse than no gate.
2. **Flag the `fix(#N)` bracket form.** Ten false positives, zero true positives.
   See the refutation above.
3. **Rely on `gh pr view --json closingIssuesReferences` alone.** Authoritative
   for the pull request and blind to the merge text. It returned `[]` for PR
   #360 while that merge closed #337. Kept in layer 2 as a *supplement*, where it
   covers forms the regex does not (`GH-123`, `owner/repo#123`, issue URLs).
4. **Make layer 3 blocking.** The message cannot be edited, so that SHA can
   never go green. Precisely: `scripts/deploy_gate.py` treats a failed SHA as a
   stranding only while it is still `main`'s tip, so the block lasts until the
   next commit lands rather than forever, and `deploy.yml` keeps
   `workflow_dispatch` as an explicit ungated escape hatch. It is still an
   outage of the deploy path caused by a typo, with no in-place remedy. Pinned
   by a test.
5. **A local `commit-msg` git hook.** The damaging text is composed by
   `gh pr merge`, not by a local `git commit`, so the hook never sees it. Also
   local-only, absent in CI, and skippable at will.
6. **Add a new required status context.** Needs a branch-protection change (admin
   action, human approval) and would make seven required contexts. Folding the
   step into `validate-and-test` obtains identical blocking behaviour for free.

## Consequences

* A pull request whose title or body negates a close **cannot merge** until the
  wording changes. The fix is to move the keyword away from the number: "does not
  close issue 337", or "#337 stays open". Both read the same and neither closes
  anything.
* One new step on every PR run, before dependency install, costing seconds.
* `PR=<n> MERGE_SUBJECT=... MERGE_BODY=... make close-guard` exists but is only
  as good as the habit of running it. The text travels in the environment: an
  earlier form passed it as make variables, which expanded a crafted body into
  `/bin/sh` and could not parse PR #360's real merge body at all. If the #360 class recurs despite this record, that is
  the evidence that layer 2 needs to become mechanical — most plausibly by having
  the merge go through a script rather than a remembered command.

### What this cannot see

Stated plainly, because a guard whose blind spots are unwritten gets trusted past
its evidence:

* **A merge performed in the GitHub web UI.** Layer 2 never runs; layer 3 reports
  only after the issue has already closed.
* **An issue closed by a comment, or by editing the issue directly.** Neither
  surface is inspected.
* **Reference forms other than `#N`** — `GH-123`, `owner/repo#123`, a full issue
  URL. Layer 2's `gh` query sees these for the pull request; the layer 1 and
  layer 3 regex does not.
* **A negation further than three words before the keyword**, or separated from
  it by a comma or a sentence end. That boundary is what buys the zero false
  positives, and it is a deliberate trade.
* **Negation expressed without a negation word.** An adversarial reviewer found
  these unflagged, every one of which GitHub would act on: *"This fails to close
  #337"*, *"This declines to close #337"*, *"This only partially fixes #337"*,
  *"This hardly closes #337"*, *"This does not, in any way, close #337"* (the
  commas stop the walk), *"Deliberately not: closes #337"*. **Zero instances of
  any of them exist** in 344 commit messages or 242 pull requests, so they were
  left out rather than widening the matcher on speculation and paying in false
  positives. If one ever lands, add it to the corpus — do not guess ahead of it.
* **`without`, `unfixed`, `unresolved`** were in the negation set and were
  removed: no natural sentence puts them directly before `close #N`, so nothing
  could exercise them, and a test now refuses a negation word that no corpus
  text reaches.
* **The opposite error** — a pull request that *should* close an issue and
  silently does not. `scripts/check_issue_closure.py` (issue #139) is the check
  for that direction; this one does not duplicate it.
* **Anything on a branch that never reaches `main`.** The history scan reads
  `origin/main` only.

### Open, and deliberately not closed here

Found by review, reproduced, and left for a separate change rather than fixed
past the two-round cap:

* **Markdown block structure is not a boundary, only a blank line is.** So
  `- no regressions` on one line and `- closes #123` on the next is flagged, as
  is a `## Nothing regressed` heading above a `Closes #123`. **Zero occurrences
  in 344 commit messages and 242 pull requests**, so this is forward-looking
  risk rather than a live defect — but it is on the BLOCKING lane and this
  repository writes bullet-heavy pull-request bodies. The fix is to treat a
  newline into or out of a line beginning with a markdown block marker as a
  boundary; it needs its own review round.
* **Whether GitHub Actions sets `PR_BODY` at all for a pull request with a null
  body is UNVERIFIED.** If it omits the variable rather than setting it empty,
  the per-variable floor exits 2 on every body-less pull request. The check is
  one throwaway pull request with an empty body. Every pull request in this
  repository's history has a body, so it has not been reachable here.
* **`ci.yml` has no `concurrency` group**, so `edited` adds runs rather than
  superseding in-flight ones — measured at 33 edits over 60 pull requests.
  Cost, not correctness, and adding one touches every job in the workflow.
* **A zero-width space defeats the walk** (`does not\u200bclose #123` is a
  reference GitHub honours and the guard does not flag). This is a guard against
  accident, not against a deliberate actor.
* **Negation more than three words back, or across a comma**, remains
  undetectable by construction — see the list above.
