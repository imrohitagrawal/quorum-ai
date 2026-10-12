# ADR-0162: A false "done" must fail a check

## Status

Accepted — 2026-10-11, under the plan the product owner approved (CHG-040 (b)).
This is package B of `docs/analysis/2026-10-11-how-we-work-review.md`. The scope and the cut-off
are the session's design.

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
   counts. Files last changed before the cut-off are skipped without a blame. At the cut-off, 154
   of 157 ADRs are marked "Accepted" in their Status section, and 23 of 24 narrative handoffs use
   "merged" or "in production", so
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

- Of the 14 planted claims, the in-scope ones, as planted by the test, are rejected by a support
  check, and a test plants each of them in a temporary copy. A claim written next to an unrelated
  real citation in the same block still passes (I7a typed into ADR-0121's status paragraph, which
  cites CHG-011, is one): the check proves a proof exists, not that it is the right one.
- A session writing "merged" must cite the pull request. That is the habit this repository already
  asks for in prose.
- Words outside the list ("done", "shipped", "live") still pass. The list can grow when a planted
  claim shows the need.
- A citation supports every claim in its block, even a citation of unrelated work. The check proves
  that a proof exists, not that it is the right proof; the reviewers still read it.
- Text inside a fenced code block is quoted output, not a claim. `make handoff` prints generated
  lists in fences, so this is needed; a claim typed inside a fence passes.

## Amendment after review round 1 (2026-10-12)

The review planted claims that the first build let through. Each is now pinned by
`tests/unit/test_one_status_review_round_1.py`:
- **A unit is a CommonMark block.** "The same paragraph or table row" was read as a run of
  non-blank lines, so one bullet's citation supported the next bullet, and a heading or a table
  without leading pipes shared one unit with its neighbours. The check now parses the file with
  the pinned CommonMark parser (ADR-0029) and reads each paragraph, list item, heading and table
  row as its own unit. It runs under `uv run` for that parser.
- **The claim text is the visible text**, line breaks read as spaces, so a phrase wrapped across
  two lines is seen. Inline code, code blocks and raw HTML are mentions, like quoted text.
- **A negation counts only in the same clause.** The look-back crosses spaces and a few filler words ("not yet", "has not been"), never punctuation, so a "no" that
  ends one sentence does not cancel a word in the next. A heading that is exactly a
  closing-status label ("Verified myself") is a label.
- **A status field is read on its own source line** (amended after review round 2, and again
  after the re-check of 8c7838d, because a status block is often written one field per line and
  the joined text read "Merged: no" / "In production: no" as "Merged: no In production: no").
  "Merged: no" is a negation when the field value, which runs to the end of the word's source
  line or to the next ".", ";" or "|", is exactly "no" or "not yet", with optional closing
  punctuation, emphasis markers and one parenthesized remark ("Merged: no (blocked on CI)").
  "Merged: no doubt." and "Merged: no -- see below" are claims. A value wrapped onto the next
  source line is read per line, so "Merged: no" followed by a line "conflicts with main." is a
  negation. A field value negates nothing on the next line: "Merged: no" followed by
  "In production: yes" claims "in production". A plain wrapped negation ("has not" / "been
  merged") still negates.
- **A pull request counts only as a squash suffix:** `(#N)` at the end of a subject on `main`. A
  commit scope such as `feat(#105):` names an issue.
- **A grandfathered PRESENT row keeps its needle, not just its id.** The path and needle are
  read from the board at `b66b107`; a row whose path or needle differs must name a commit with
  `PRESENT@<sha>`. In a repository without that commit, the rows are kept by id, as before.
- A claim is checked when the line holding its first character was written after the cut-off. An
  old line moved without a change is re-dated by blame and so is checked. That limit is kept:
  quote, cite or reword the moved line.
