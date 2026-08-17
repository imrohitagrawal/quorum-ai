# ADR-0050: Duplicate ADR numbers are refused at both discovery points, and a gap is not a defect

## Status

Accepted — 2026-08-17 (issue #332)

## Context

`docs/adr/` numbers its records by filename prefix, `NNNN-slug.md`. Nothing
compared those numbers to each other, so two files could claim one number and
every gate stayed green.

That is not hypothetical. ADR-0049 records it happening: three branches each
created a `docs/adr/0047-*.md`, `make validate` exited 0, and the index carried
two ADR-0047 rows. ADR-0049 §"Nothing checks `docs/adr/` for duplicate numbers"
diagnosed the cause and deliberately deferred the fix to its own issue, because
three branches were racing on the same directory at the time. This ADR is that
fix.

There were two independent places a duplicate could have been caught, and both
were blind — for different reasons:

1. **`tests/unit/test_docs_numbering_no_collisions.py`** enumerates with
   `git ls-files "docs/*.md"`. That glob *does* cross the slash, so all 48
   `docs/adr/*.md` files were already in the gate's input list. They were
   dropped by the pattern: `_NUMBER_PREFIX` is anchored `^docs/(\d+)-`, and
   `docs/adr/0049-….md` has a non-digit segment where the digits must be. The
   gate was reading the ADRs and matching none of them.
2. **`scripts/generate_adr_index.py`** emits one table row per file and never
   compares numbers across records. `--check` byte-diffs the rendered text
   against the file, so an index with two identical numbers is "up to date".

A third fact shapes the decision: the two discovery mechanisms disagree about
*when* they see a new file. The test shells out to `git ls-files`, so an ADR is
invisible to it until `git add`. The generator uses `ADR_DIR.glob("[0-9]*.md")`
— the filesystem — so it sees the file the moment it is written.

Finally, the sequence is **not** contiguous and must not be required to be. On
2026-08-17 the tracked records ran 0001..0047 and then 0049. `0048` is not
missing by accident; it is claimed by the unmerged branch
`origin/fix/226-vacuous-e2e-negative-assertions`. A gate that demanded a
contiguous run would have been red on clean `main` that day and would have
collided with #226 on merge.

## Decision

**Refuse a duplicate ADR number at both discovery points, and treat a gap as
normal.**

1. `tests/unit/test_docs_numbering_no_collisions.py` gains a second pattern,
   `_ADR_NUMBER_PREFIX = ^docs/adr/(\d+)-`, over the same tracked-file list,
   plus an anti-vacuity floor and a positive partner. The shared grouping logic
   is extracted into `_collisions(paths, pattern)`, which takes the path list as
   an argument so the duplicate and gap cases are driven from synthetic input
   without writing into the real tree.
2. `scripts/generate_adr_index.py` refuses to write, and `--check` refuses to
   pass, when two records claim one number. The refusal reuses the existing
   `SystemExit` shape of the empty-directory guard directly above it, and the
   message names the number and every file claiming it.
3. **Only a repeated number is a defect. A gap is not reported**, and no gate
   asserts contiguity.

Both halves are kept deliberately, rather than picking one, because they catch
the fault at different moments — see the table below.

## Measurements (2026-08-17, macOS/darwin 25.5.0, this repository at `7688528`)

| Question | Command | Result |
|---|---|---|
| How many ADRs are tracked? | `git ls-files "docs/adr/*.md" \| wc -l` | `48` |
| Do they reach the existing gate at all? | `git ls-files "docs/*.md" \| grep -c "^docs/adr/"` | `48` — yes, all of them |
| How many does the existing pattern match? | count matches of `^docs/(\d+)-` over those 48 paths | **`0`** |
| Are any numbers duplicated today? | group the 48 by `NNNN` prefix | `{}` — all 48 distinct |
| Is the sequence contiguous? | same grouping, min/max/gaps | min `0001`, max `0049`, gaps `[0048]` |
| Who holds 0048? | `git ls-tree -r --name-only origin/fix/226-vacuous-e2e-negative-assertions docs/adr/` | `0048-a-positive-partner-must-survive-…md` |
| Does the generator write a duplicate? | in a `git archive HEAD` copy, add a second `0047-*.md`, run the generator | `wrote docs/24-adr-index.md (49 records)`, exit `0` |
| …and does the index really carry two? | `grep -c "ADR-0047" docs/24-adr-index.md` | `2` |
| …and does `--check` notice? | `python3 scripts/generate_adr_index.py --check` | `adr-index: up to date (49 records)`, exit `0` |

ADR-0049 reports `adr-index: up to date (48 records)` for the same fault. That
is not a contradiction: it measured the real 48-file tree in which two of the
files were both 0047, whereas the reproduction above added a 49th file to a tree
whose 48 were already distinct. Both are the same blindness at a different
record count.

The discovery asymmetry, measured on the uncommitted `docs/adr/0050-*.md` of
this very change, before it was `git add`ed:

| Discovery mechanism | Used by | Saw the new uncommitted ADR? |
|---|---|---|
| `git ls-files "docs/adr/*.md"` | the pytest gate | **no** — 48 files |
| `ADR_DIR.glob("[0-9]*.md")` | the index generator | **yes** — 49 files |

That difference is the whole argument for keeping both halves. The generator
refuses at the moment the duplicate is *created*, which is when the author can
still fix it cheaply and is the earlier of the two. The pytest gate refuses at
the moment it is *committed*, and it is the one wired into the required CI
context `pytest (Python 3.12)`, so it holds even if someone edits the generator.

## Rejected alternatives

**Require a contiguous sequence.** Rejected on measurement, not taste: the tree
had a live gap at 0048 on the day this was written, held by an unmerged branch.
This gate would have been red on clean `main` and would have fought #226 on
merge. It also encourages the genuinely harmful fix — filling a gap that another
branch already owns, which *creates* the duplicate it was meant to prevent.

**Fix only the pytest gate, and leave the generator alone.** Rejected because
the pytest gate cannot see an uncommitted file (measured above). An author can
write a duplicate ADR, regenerate the index, watch `make validate` pass, and get
no signal at all until the `git add`. The generator is the only one of the two
that can speak at the moment of the mistake.

**Fix only the generator, and leave the test alone.** Rejected because the
generator's refusal is enforced by a script that the same person editing ADRs
can edit. The pytest gate is an independent lens in a required merge context,
and it is what makes the generator's guard itself testable.

**Make the generator auto-renumber the newer record.** Rejected: it would
rewrite a filename that other documents, issues and branches already reference
by number, and it cannot know which of the two claimants is "newer" in any sense
that matters. Refusing and naming both files leaves the choice with the author.

**Assert the ADR count as an exact number.** Rejected under AGENTS.md rule 7a
and rule 1a. An exact `== 48` breaks on the next ADR — including this one — and
teaches contributors to edit the assertion rather than read it. The floor is
`>= 40` against a measured population of 48 that only grows, which a regex
matching nothing (the actual bug, `0`) still trips.

## Consequences

- Two ADRs sharing a number now fail in two places: `make validate` (via
  `adr-index-check`, inside the required context `validate-and-test`) and
  `pytest` (inside the required context `pytest (Python 3.12)`).
- A gap in the sequence stays legal, so an ADR number claimed by an unmerged
  branch does not have to be filled and should not be.
- **Picking a number is still a manual step, and this gate does not make it
  safe.** It compares only what is on `main` and in your worktree. A number
  claimed by an *unmerged branch* — exactly how 0048 is spoken for — is invisible
  to both halves, so two branches can still each pass locally and collide on the
  second merge. What changes is that the collision now fails loudly at that merge
  instead of silently producing a double-numbered index. To check properly before
  choosing, look at the branches too:
  `git ls-tree -r --name-only <branch> docs/adr/`.
- The generator now has two refusal paths sharing one shape. A future third
  (say, a malformed number) should follow it rather than inventing an
  exception type.

## Related

- #332 (this change); ADR-0049 §"Nothing checks `docs/adr/` for duplicate
  numbers", which recorded the gap, verified it, and deferred it here
- ADR-0034 (`docs/adr/0034-docs-numbering-scheme-and-ranges.md`) — the sibling
  numbering scheme for `docs/NN-*.md`, whose collision gate this extends
- `tests/unit/test_docs_numbering_no_collisions.py`,
  `tests/unit/test_adr_index_matches_directory.py`,
  `scripts/generate_adr_index.py`
- AGENTS.md rule 7 (a negative check needs a positive partner), rule 7a (never
  assert a bound against the constant that defines it), rule 1a (prefer a check
  over a corrected sentence)
