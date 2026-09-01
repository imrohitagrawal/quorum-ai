# ADR-0092: The board anchor is checked against a `main` this checkout can see, not against `HEAD`

## Status

Accepted — 2026-09-01

## Context

`docs/65-open-work.md` carries a `Verified at: <40-hex sha>` anchor, and
`scripts/check_open_work.py::check_freshness` required that commit to exist, to
be an ancestor of **`HEAD`**, and to be within `MAX_DRIFT_COMMITS` (60)
first-parent commits of it.

On a feature branch, a commit made ON that branch **is** an ancestor of `HEAD`.
So a session that stamped its own branch commit passed every gate on the pull
request. This repository squash-merges (rule 17c), which discards that commit;
on `main` the anchor is then neither present nor an ancestor, and the gate
refuses **after** the merge instead of before it. Measured on PR #399: anchor
`2350e59`, squash `59f402a`, and on that SHA `gh run list` reported
`1 CI: failure`, `1 Tests: failure`, `3 Deploy to Fly.io: failure` and
`6 Deploy to Fly.io: skipped`. Nothing reached production, and `main` was
broken until a follow-up re-stamped it.

Two earlier designs were built against this and both were withdrawn. Each
shipped a 100 %-green suite with every mutation killed, and each pinned the
wrong contract. The full measurements are in
`docs/analysis/2026-09-01-402-freshness-gate-design.md`; the two that decide
this ADR are:

- **Design A** accepted a non-ancestor anchor whose committer was
  `GitHub <noreply@github.com>`, on the reasoning that GitHub performs every
  squash merge here. GitHub stamps that same identity on the one-click "Update
  branch" merge it makes **on a feature branch** — `172803b` in this repository
  is a confirmed instance, and Design A accepted it.
- **Design B** decided skip-versus-refuse from `remote.origin.fetch`. Git's
  behaviour and that config disagree in at least four measured ways on git
  2.54.0, and the design skipped in a `git clone --bare` + `git worktree add`
  layout while a complete `refs/heads/main` sat in the same object store. It
  was a regression against Design A on the shape it most needed to catch.

## Decision

**Add a second, independent family: the anchor must be an ancestor of at least
one `main` ref this checkout can actually resolve.** `check_freshness` keeps
its `HEAD` ancestry and drift checks unchanged, so the pair is strictly
stronger than what was there before.

`known_main_refs()` asks which refs **exist**, never which refspecs are
configured, and builds its candidates from configured remote **names** rather
than by matching a suffix:

1. `refs/remotes/origin/main`;
2. `refs/remotes/<other configured remote>/main`, sorted;
3. the local `refs/heads/main`.

Then:

| What resolves | Answer |
|---|---|
| at least one candidate contains the anchor | pass; the report line names the ref |
| candidates exist, none contains the anchor | REFUSE — the #402 defect |
| no candidate, but a remote is configured | REFUSE, naming a remedy measured to work |
| no candidate and no remote | skip, and say so on the report line |

**"At least one", not "`origin/main`"**, is what admits a contributor whose
`origin` is a fork that is behind while `upstream` is canonical — with no
heuristic, because `upstream/main` simply answers.

### The one place this departs from the design note it was built from

That note said to **skip** whenever no `main` ref resolves. Measured afterwards
on git 2.54.0: a `--single-branch --branch <feature>` clone holds only
`refs/heads/feature` and `refs/remotes/origin/feature` — no `main` ref of any
kind. Skipping there would fail open in the shape where a branch-only anchor is
most likely to be typed. So the skip population is split by **why** the answer
is unavailable: no remote at all means nothing could ever answer (skip); a
remote with no `main` ref means a `main` is one command away (refuse).

Design A also refused in that shape and was faulted for it — but the fault was
the remedy it printed, not the refusal. Measured, git 2.54.0:

| Command | `refs/remotes/origin/main` afterwards |
|---|---|
| `git fetch origin main` | **still ABSENT** (writes FETCH_HEAD only) |
| `git fetch origin main:refs/remotes/origin/main` | CREATED |
| `git remote set-branches --add origin main && git fetch origin` | CREATED |

The refusal message names the two that work. A test drives the remedy and then
asserts the same branch-only anchor is still caught, so the message cannot rot
into Design A's dead end.

## Rejected alternatives

- **Ancestry against `merge-base(HEAD, origin/main)`.** Measured: strictly
  weaker than comparing against `origin/main` directly, since the merge-base is
  itself an ancestor of the ref tip, so it can only refuse more often. It does
  not escape the stale-remote refusal either.
- **A committer-identity escape hatch.** Refuted above by `172803b`.
- **Deciding from `remote.origin.fetch`.** Four measured disagreements with
  git's real behaviour, plus a live regression: `git remote set-branches --add
  origin main` — the exact remedy an affected user runs — puts `main` on the
  **second** config line, which a first-line-only parse misses.
- **Matching candidate refs by the suffix `/main`.** A branch called
  `release/main` would then be treated as trunk.

## Consequences

- A branch-only anchor now fails the pull request instead of `main`.
- **Accepted limitation, stated rather than hidden:** a `main` ref that has not
  been fetched refuses an anchor that really is on `main`. This is not
  derivable offline — against a stale ref, a genuine `main` commit and a branch
  commit are both simply descendants of the ref tip. `git fetch` is the first
  remedy and it does **not** always clear it: when `origin` is a fork that is
  itself behind, fetching it advances nothing.
- The skip is ignorance, not permission. Its test gives the same repository a
  `main` and shows the same anchor refused at once.
- `make validate` runs in one CI job (`ci.yml:77`, `validate-and-test`) whose
  checkout is `fetch-depth: 0`, so `origin/main` is present there and the gate
  measures rather than skips. The report line prints which ref answered, so the
  CI log itself is the evidence.
