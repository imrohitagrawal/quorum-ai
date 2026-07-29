# Evidence ledger

Dated records of what we checked, when, from which primary source, and **how
strongly it is actually evidenced**. Separate from the standard on purpose:
`docs/DAY-ONE-PROMPT.md` says what to do; this says why we believe it and how much
weight it will bear.

## Why this exists

Two failures, both paid for on this project:

- **Practices adopted from claims nobody checked.** "Code review finds most
  defects", "review 200–400 lines at a time", "80% coverage" — all widely repeated,
  all traceable to sources far weaker than their reputation. We were about to
  encode two of them.
- **Findings that lived only in a chat window.** On 2026-07-30 a session produced
  roughly a dozen measured findings that existed nowhere but the conversation and
  would have been lost at session end. This ledger is where they land instead.

## How to use it

**Records are superseded, never edited.** This is the ADR convention (Nygard,
*Documenting Architecture Decisions*, 2011): when a finding changes, write a new
dated record and mark the old one superseded, with a link. You then get the thing
that matters — *what was believed on a date, and what replaced it* — instead of a
document that silently becomes untrue.

**Every claim carries two things a citation alone does not give you:**

| Column | Why |
|---|---|
| **Grade** | How strongly it is evidenced. A peer-reviewed randomized experiment and a vendor case study are not the same input to a decision |
| **What would change this** | The trigger to go look again. A date tells you research is old; a trigger tells you when it matters |

**Grades used:**

| Grade | Meaning |
|---|---|
| `WELL-EVIDENCED` | Peer-reviewed, primary source read, method and sample stated |
| `INDUSTRY-PUBLISHED` | Named organisation reporting its own practice; no independent audit path |
| `VENDOR` | Published by a party selling the thing measured |
| `ASSERTION` | Stated by a credible source with no published methodology |
| `LOCAL` | Measured on this repository. n is usually small. Does not generalise |
| `NOT-FOUND` | Searched for, does not appear to exist. **This is a finding, not a gap** |
| `REFUTED` | We believed it; checking killed it. Kept deliberately — see below |

**`REFUTED` rows are kept, not deleted.** A record of what we got wrong is the
most useful part of this ledger, because the same wrong belief tends to come back.

## Index

| Date | Record | Scope | Status |
|---|---|---|---|
| 2026-07-30 | [engineering-practice](2026-07-30-engineering-practice.md) | Code review effectiveness, quality gates, documentation decay, session handoff, LLM review precision, review cost | Current |

## Adding a record

1. New file, `YYYY-MM-DD-<topic>.md`.
2. Every claim gets: statement, grade, primary source (author, title, year, venue,
   URL), how it was verified, and what would change it.
3. **If you could not open the primary source, say so on the row.** A citation you
   have not read is `ASSERTION`, not `WELL-EVIDENCED`, however respectable the name.
4. Add a row here. If it supersedes an earlier record, mark that one superseded and
   link both ways.
