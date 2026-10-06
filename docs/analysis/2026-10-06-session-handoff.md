# Session handoff — 2026-10-04 to 2026-10-06

The record is `git log` on `main` and the board (`docs/65-open-work.md`). This note lists only what those do not say.

## Shipped this session, each merged and verified in production

| Board row | PR | What |
|---|---|---|
| W37 | #536 | A follow-up sends the previous question and final answer (ADR-0143) |
| W47 | #537 | Anonymous spend counted per network (ADR-0144) |
| W48 | #538 | One-time hints and an optional tour (ADR-0145) |
| W52 | #539 | Search excerpts kept with their source, never served (ADR-0146) |
| W53 | #540 | The untrusted-text fence catches an altered marker (ADR-0147) |
| W29 | #541 | The judge reads cited pages, behind `quorum_source_fetch_enabled` = False (ADR-0148) |

## Decided by the owner on 2026-10-06 (CHG-029)

- **W54:** approved one paid measured run, plus up to two extra. Show the owner the free estimate before any spend. Do the run on the session's machine, not by switching production on.
  - Build first, with fetching still off:
    - the plain-English wording for pages a website asks tools not to read (CHG-029 (b));
    - picking the relevant passages of pages over 4,000 characters (CHG-029 (c)), compared against "first 4,000 characters" in the extra runs.
- **`docs/48`:** the rows for search excerpts, cited page text and the anonymous network key are approved.
- **Follow-ups:** W47's two follow-ups are board rows W55 (ledger retention) and W56 (the Sentry pairing).
- **ADR-0148:** its calls stand. Revisit call (iii) once the paid run shows how often fetches fail.

## Traps met here

- **GitHub Actions outage (2026-10-05/06):** jobs were cancelled with "The job was not acquired by Runner". This is not a code failure. Re-run them with `gh run rerun <id> --failed`, and check githubstatus first.
- **The ✘ in markdown-corpus `dunder-identifier`** is a `test.fail()` known gap. It shows ✘ on green runs too.
- **Floors in `e2e.yml`** are raised to the measured count with the evidence in the comment. W29's raise (453 -> 455) is PR #542, merged.
