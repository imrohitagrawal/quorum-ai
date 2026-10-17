# ADR-0170: The security measures list names a test for each measure, and a test checks the names

## Status

Accepted — 2026-10-17, board row W82. The owner directed that the security session first look at
the measures in place, the gaps and how to close them (CHG-051). Everything decided below is the
session's proposal, which CHG-051 records as not the owner's decision: the list's shape, the check
on it, ASVS 5.0.0 Level 2 as the checklist, and the rule for ordering the security rows. Codex
reviewed the plan and the order before any code (ADR-0168, decision 7) and the plan was revised
on its findings, then re-checked by Codex.

## Context

`docs/41-security-controls.md` listed 12 controls from June 2026. Each named a test such as
`TEST-FR-001`, which is a requirement label, not a test: it names 17 distinct labels, and 14 of them
appear in no file under `tests/` (`git grep -F <label> 2f13e22 -- tests`). One control, CTRL-001, was false (anonymous visitors run questions by
design, ADR-0144), and CTRL-012 claimed static code analysis that runs nowhere. Nothing compared the
list with the code, so it drifted for four months without a failure.

The 2026-10-13 security review (`docs/analysis/2026-10-13-security-review.md`, section 9) also left
open which ASVS Level 2 items the app fails.

## Decision

1. **`docs/41-security-controls.md` is the one list of the security measures in place.** Each row
   is one measure: what it stops, where it lives, the tests that fail without it (or the e2e spec,
   or "none"), the CI job that runs them, the decision behind it, and a status (`TESTED`,
   `PARTIAL`, `CODE-ONLY`, `MEASURED`, `UNKNOWN`). The 97 rows were written by a read-only agent and
   checked by the session: every named test exists, and the session ran the measured rows itself.
2. **`tests/unit/test_security_controls_cite_real_tests.py` checks the list on every pull request.**
   It reads the tables that markdown-it-py (a pinned dependency, `gfm-like` preset) renders, so a row
   in a comment, a code block or a `<script>` block is not a measure. It pins the set of measure ids
   (SC-01 to SC-97), so removing or renumbering a measure fails until the test is edited too. It
   refuses a malformed or duplicate id, an SC id in a table that is not a measure table, an empty
   ID, Measure, Where, Runs in or Status cell, a struck-out ID or Status cell, an unknown status, a
   `TESTED` or `PARTIAL` row with no test, a named test that does not exist, does not follow
   pytest's default collection names (a `test_*.py` file, a `test_*` function, a `Test*` class) or
   carries an unconditional `@pytest.mark.skip`, and a named e2e spec that does not exist. It was
   written first by a separate test designer and failed on the old file (`id-missing (97)`); each
   of its rules was then broken by hand in a copy and caught by the partner test meant for it.
3. **OWASP ASVS 5.0.0 at Level 2 is the checklist**, recorded item by item in
   `docs/analysis/2026-10-17-asvs-5-level-2-check.md`. The 2026-10-13 review named Level 2 as the
   level that fits this app; the session's reason is that the app handles accounts and money. The
   standard's own description of its levels was not re-read for this decision.
4. **How the security rows are ordered**, in `docs/analysis/2026-10-17-w82-security-baseline.md`
   section 5: what can be used against the running site now comes first, most harmful first; then what waits only
   on an owner value; then what must land before bring-your-own key (W75, W76); then what must land
   before paid live answers are switched back on (W71, W72, W73); then process, documents and low
   risk, with the exceptions that section names. Rows needing the owner's money or decision are
   parked (ADR-0168).

## Measurements

| What | Command | Result |
|---|---|---|
| The list's named tests exist | `ast` lookup of every cited `tests/<file>.py::<name>` in `docs/41-security-controls.md`'s Proof cells, by a script not committed; the committed test now does the same check | `ids 216 ok 216 missing 0` before review; since then the committed test makes the same check on every run |
| The tests the six ASVS agents cited exist and pass | the same lookup over the agents' reports, then `pytest <ids> -q --no-cov` on `2f13e22` | `ids 142 ok 142 missing 0`; `265 passed`, exit 0 |
| ASVS items checked | parse the six agents' tables against the standard's CSV | `wanted 253 parsed 253 missing [] extra [] dups []` |

## Rejected alternatives

- **A floor on the row count (at least 30 rows).** The first plan. Codex showed it passes when an
  essential row is deleted and 30 others remain, and that it was an arbitrary number. A pinned set
  of ids fails on any removed row.
- **Checking only that each named function exists.** Codex showed that a helper such as
  `tests/helpers.py::scoped_events`, or a fixture, would pass. The check now applies pytest's own
  collection rules.
- **Running pytest's collector from the test.** It would prove collection exactly, but it starts a
  second pytest on the 108 test files the list names inside every run of the suite. The naming rules catch the cases
  found, at no cost.
- **Keeping CTRL-001 to CTRL-012 and adding evidence to them.** Their scope was the June 2026 plan,
  one was false and one was product behaviour; the old ids are mapped to the new ones in the file,
  so `docs/45-control-mapping.md` still resolves until row W99 rewrites it.

- **Reading the Markdown line by line.** The first two versions of the test did this. Two review
  rounds each found Markdown it read wrongly in both directions (rows hidden in comments still
  counted, a `<!--` inside a code span hid a citation, a row with no leading pipe was not read). The
  third version reads what the parser the app already pins renders. That change itself added two
  small defects (`<br>` losing its word break, struck-out text read as if not struck); the stop rule
  had then fired, and the owner chose one more fix (CHG-058).

## Consequences

- A pull request that removes a measure, or renames the test that proves it, fails until it also
  edits `docs/41-security-controls.md` and the pinned id list.
- **What the check cannot see:** whether a named test really exercises its measure. Codex's
  example: one unrelated test named by every row passes. Review is the defence. It does not run
  pytest's collector, so a test skipped by `skipif`, by a class or module mark, by a fixture or at
  run time, or hidden by a `conftest.py` hook, still counts. An e2e citation proves only that the
  spec file exists. The Measure, Where and Runs in cells are checked for being filled, not against
  the code, and Decided by is not checked at all. It reads markdown-it-py's rendering, not GitHub's:
  the two may differ (markdown-it-py keeps a cell holding `\\|` whole), and a raw HTML `<table>`
  is not read. A `<br>` with attributes is not read as a break, a strike tag whose attribute
  holds `>` is not recognised, and an empty strike element is reported as struck; the owner chose
  one more fix and no further patches (CHG-058), so these stay stated limits.
- On 2026-10-17 the owner set the front of the order: the small live rows W85, W86, W100, W87, W88
  and W80, then W75 and W76, then W28 (CHG-061, replacing CHG-059's order). For the live gaps not
  yet fixed, the public documents hold back how to reproduce them until each fix ships (CHG-060).
- `Where` cells give line numbers at `2f13e22`; they move as code changes, and nothing checks them.
- Seventeen new board rows, W85 to W101, and changes to W71, W72, W73, W75 and W77. The owner's
  answers of 2026-10-17 (CHG-056) set W87's values, unpark W78 and keep W74 parked until it is
  priced.
