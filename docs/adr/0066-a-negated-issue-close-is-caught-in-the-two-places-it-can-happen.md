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

That has happened five times here. Every row was re-verified from the GitHub API
on 2026-08-24 with `gh api repos/:owner/:repo/issues/<n>/timeline`, reading the
`closed` event's `commit_id`:

| Issue | Text that did it | Surface | Evidence |
|---|---|---|---|
| #175 | `Filed, not fixed: #175 (whitespace ...` | commit `e6c84ea` (PR #174) | close event `commit_id: e6c84ea` |
| #185 | `not fixed: #185, #171, #178, #180, #182` | commit `0ace31e` | close event `commit_id: 0ace31e` |
| #268 | `This does **not** close #268.` | PR #282 body | `closingIssuesReferences: [268]`, close event `commit_id: null` |
| #105 | `does not close #105, #268 or #203` | PR #289 body | caught by a manual grep before merge; the body was reworded and no close event exists |
| #337 | `**This does NOT close #337.**` | `gh pr merge --body` (PR #360) | close event `commit_id: 4ea57ba` |

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
  contain **no other reference to that issue anywhere in the message**, and in
  none of the three did the commit close the issue.
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
therefore strand production permanently over a cosmetic error, with no path to
green. This is why layer 3 below reports and does not block, and it is a
structural fact, not a preference.

## Decision

Three layers. They are not equivalent, and the record is explicit about which is
enforcement and which is discipline.

| # | Surface | Runs | Kind | Blocking |
|---|---|---|---|---|
| 1 | PR title + body | `validate-and-test`, `pull_request` only | **Enforcement** | **Yes** |
| 2 | the exact `gh pr merge --subject`/`--body`, plus GitHub's parse of the PR | `make close-guard`, by hand before merging | **Discipline** | No — and it cannot be |
| 3 | the tip commit message on `main` | `validate-and-test`, `push` only | Backstop | No — see above |

**Layer 1 is legitimately blocking** because the author can edit the title or
body and go green. It lives as a step inside the existing `validate-and-test`
job rather than as a new job, so it inherits that job's required-context status
with **no branch-protection change**, and it runs before `uv sync` so the answer
arrives in seconds.

**Layer 2 is the only layer that can stop the PR #360 class before the damage**,
and nothing can force it to run. CI never sees the merge text. Calling it a gate
would be a lie; it is a safety catch that has to be remembered.

**Layer 3 cannot block** for the reason given above. It writes into the job
summary so that damage is visible the moment it lands, instead of being
discovered weeks later by an issue that is mysteriously closed.

### What is matched, and what is deliberately not

Only a close reference whose own clause **negates** it. Concretely: a negation
word within three words before the keyword, stopping at a clause boundary
(`.!?;:` a newline, **or a comma**), with markdown emphasis (`*`, `_`, `` ` ``)
ignored because GitHub ignores it too — the live PR #282 body is
`This does **not** close #268`.

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
| Real cases flagged (the five above, incl. the two PR bodies) | 5 of 5 |
| Clean-corpus items wrongly flagged | 0 of 10 |
| Mutations applied to the checker and its wiring | 11, **all RED**, 0 survivors |

The fifth case is a pull-request body and so does not appear in the commit scan;
the two PR-body texts are pinned as literals in
`tests/unit/test_close_keyword_guard.py`.

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
4. **Make layer 3 blocking.** Strands production permanently; the message cannot
   be edited. Pinned by a test.
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
* `make close-guard PR=<n> SUBJECT=... BODY=...` exists but is only as good as
  the habit of running it. If the #360 class recurs despite this record, that is
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
* **The opposite error** — a pull request that *should* close an issue and
  silently does not. `scripts/check_issue_closure.py` (issue #139) is the check
  for that direction; this one does not duplicate it.
* **Anything on a branch that never reaches `main`.** The history scan reads
  `origin/main` only.
