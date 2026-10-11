# ADR-0162: A false "done" must fail a check

## Status

Accepted — 2026-10-11, package B of `docs/analysis/2026-10-11-how-we-work-review.md`, which the
product owner approved (CHG-040 (b)). The scope and the cut-off are the session's design.

## Context

On 2026-10-11, 14 false completion claims were planted, one at a time, in a copy of `main` (the
appendix of the review document). Three were rejected by a real support check: the board refused
two hand-typed DONEs, and the findings ledger refused a DONE with no proof. Two were rejected only
by chance, by a snapshot or a freshness check. Nine got through, including these three:
- in a handoff, "W55 and W56 merged … in production";
- an ADR marked "Accepted, owner approved" with no CHG row;
- a board row pinned to a made-up `PRESENT` needle.

The findings ledger already shows what works: a DONE must cite its proof, and a test checks it.

## Decision

1. **A completion word needs a cited proof.** A test reads the scoped files and finds the words
   "merged", "in production", "complete", "completed", "verified", "approved", "accepted", "passed",
   "released", "GA", "production-ready" and "release-ready". Each must cite, in the same paragraph
   or table row, one of these:
   - a pull request whose squash commit, with `(#N)` in its subject, is on `main`;
   - a commit on `main`;
   - a CHG row that exists in `docs/19`.

   A negation just before the word ("not merged", "UNVERIFIED") does not count, and neither does a
   word quoted in backticks or double quotes, which mentions the word rather than claims it. The
   scoped files
   are the narrative handoffs, the mechanical handoff, tracked root prompts, `docs/17`, `docs/18`,
   `docs/12`, the ADRs, and the readiness documents (`docs/73`, `docs/74`, `docs/95` and the
   generated readiness file).
2. **Only lines written after the cut-off commit `b66b107`** (the merge of package A, #558) are
   checked: `git blame` says which commit last wrote each line, and an uncommitted line always
   counts. Files last changed before the cut-off are skipped without a blame. At the cut-off, 155
   of 157 ADRs say "Accepted" and all 24 narrative handoffs say "merged" or "in production", so
   checking old lines would fail hundreds of true records. Checking whole files would do the same
   to any old file a later change touches, such as a banner added to `docs/18`. The test reports
   how many scoped files and lines it checked and how many the cut-off exempts. Because blame
   reads history, not a diff, the check is not empty on `main`.
3. **`docs/00-factory-console.md` must equal what `make next` writes.** It is generated, so a typed
   edit ("Released, GA") is a false claim the generator would never write.
4. **A new `PRESENT` row must name a commit where its needle was in the file:**
   `PRESENT@<sha> <path> :: <needle>`. The check reads the file at that commit, and the commit must
   be on `main`. The 10 rows that used `PRESENT` on 2026-10-11 (W3, W10, W15, W16, W17, W18, W22,
   W28, W37, W47) keep working by name. `scripts/check_open_work.py` changes only in this.
5. **The board and GitHub must agree.** `scripts/check_board_github.py` lists every DONE row whose
   issue is open, and every open issue that no row cites. `make board-github-check` exits 1 on any
   mismatch. `make handoff` shows the result. Without `gh` or the network, it reports "unavailable"
   and does not fail (ADR-0045).

## Rejected alternatives

- **Check every file, from the start.** Hundreds of old, true records would fail, and the check
  would be switched off.
- **Check only the lines a branch changes against `main`.** A gate scoped to a diff is empty on
  `main` by construction. Blame-based scope is not.
- **Check whole files changed after the cut-off.** Adding one banner line to an old file would make
  every old line in it fail.
- **Make the board-versus-GitHub check part of `make validate`.** It needs the network; `make
  validate` must run offline.
- **Close claim I3 (a row's polarity flipped).** The board already documents it as its known limit,
  and closing it needs the same commit proof for ABSENT rows. The test asserts that I3 still
  gets through.

## Consequences

- Of the 14 planted claims, the in-scope ones are now rejected by a support check, and a test
  plants each of them in a temporary copy.
- A session writing "merged" must cite the pull request. That is the habit this repository already
  asks for in prose.
- Words outside the list ("done", "shipped", "live") still pass. The list can grow when a planted
  claim shows the need.
