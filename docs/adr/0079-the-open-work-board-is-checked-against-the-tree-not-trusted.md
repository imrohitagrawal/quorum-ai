# ADR-0079: The open-work board is checked against the tree, not trusted

## Status

Accepted — 2026-08-28

## Context

Work in this repository was planned in five places that did not know about each
other: two approved plans under `~/.claude/plans/` (outside the repository
entirely), two untracked `CONTINUE-*.md` files at the root, seven GitHub issues,
a narrative handoff under `docs/analysis/`, and a "factory console" that
`AGENTS.md` mandates maintaining.

Measured 2026-08-28, not asserted:

| Claim | Command | Result |
|---|---|---|
| The factory console is stale | `git rev-list --count --first-parent $(git log --first-parent origin/main --format=%H -1 -- docs/00-factory-console.md)..origin/main` | **64** first-parent commits behind its own last touch |
| …and staler by content | `git rev-list --count --since=2026-07-23 origin/main` | its content is dated 2026-07-23, **241** commits back |
| Four open issues appear in no plan | `gh issue list` against `grep -rn` over `docs/` and the root prompts | #383, #382, #380, #379 exist only in `gh` |
| Three files each claim the authoritative phase | `grep -rn "authoritative" docs/` | the console's `## Current phase`, `docs/session-handoff.md` (disavowed by its own later section), and `docs/analysis/R2-plan-review-findings.md` |

The console still announced work from PR #91 and quoted `pytest 1342 passed`
against a suite that collects **3819** (`uv run pytest --collect-only -q`,
measured 2026-08-28).

**What the existing console gates do and do not do.** Four test files under
`tests/` reference the console (`git grep -l "00-factory-console" origin/main --
tests/` → 4; the handoff prompt inherited here said "six", which is wrong).
Two of them are real truthfulness gates: `test_factory_console_claims.py`
re-measures a claim inside a block labelled *measured* and checks that durable
pointers resolve, and `test_factory_console_quoted_output.py` requires every
`OK: ...` line quoted in a code fence to be producible by some script. Neither
asks the question that matters here — **whether the work the console announces
is the work in flight.** A document can pass both gates while describing a
different month.

The root cause is not carelessness. It is that **no mechanism compared any of
those sentences to the tree**, and this repository has measured, repeatedly,
that prose without a check drifts: `AGENTS.md` said "twelve" about a directory
holding 15 for months, and the ADR index went stale by hand twice while carrying
a note asking future readers not to let it.

## Decision

**One board — `docs/65-open-work.md` — and every row carries a claim about the
tree that a gate reads off disk.**

Each row's evidence cell is one of:

* `ABSENT <path> :: <needle>` — the needle is not in that file today.
* `PRESENT <path> :: <needle>` — it is.
* `—` — unpinned; the gate checks nothing about this row.

**A `PENDING` row's needle is chosen so that it flips when the work lands.**
Completing W1 puts `"stream": True` into `providers.py`, the `ABSENT` claim
becomes false, and `scripts/check_open_work.py --check` refuses until the row is
flipped to `DONE` with its evidence inverted. A `DONE` row's inverted claim is
read off disk too, so a row cannot be marked done over nothing.

This inversion is the whole point. The obvious design — a board that goes red
when work is *abandoned* — stays green through every delivery, which is exactly
how the console reached 64 commits of drift with four gates reading it.

Three further pieces:

* **Two count pins.** The board states its own row count and its own
  unpinned-row count as digits, both compared against the parsed table. Copied
  from `tests/test_doc_gate_consistency.py` Part D, plus its anti-vacuity floor
  and its bite-proof.
* **A freshness anchor.** The board records the commit its rows were verified
  at. It must exist, be an ancestor of `HEAD`, and be no more than
  `MAX_DRIFT_COMMITS` first-parent commits behind it.
* **Wired into `make validate`**, exactly as `adr-index-check` is — this
  repository's own precedent that a derived doc is verified, not trusted.

### The drift threshold, derived rather than chosen

`MAX_DRIFT_COMMITS = 60`.

```
git log --first-parent main --since="90 days ago" --format=%H | wc -l   →   308
```

308 first-parent commits in 90 days is ~3.4 a day, so 60 is about 18 days. The
only *measured* rot point in this repository is the factory console at 64
commits stale, so the gate fires just below the point staleness has actually
been observed at.

It is deliberately loose. The per-row polarity checks are the real freshness
signal and they run on every commit; the anchor only guards the prose and the
unpinned rows. A tight threshold would turn re-stamping into a ritual performed
without re-reading, which manufactures false confidence and is worse than no
gate at all.

## Rejected alternatives

**`docs/00-factory-console.md`.** `scripts/factory_next.py` ends in an
unconditional `write_text` of a fixed template, so `make next` deletes every
hand-written word in that file. `git stash show --stat stash@{0}` is the
evidence: *2 insertions, 88 deletions* — someone ran `make next`, it wiped the
status, and they stashed the damage. `AGENTS.md` tells a session to run
`make next` **and** to maintain that file by hand; those two instructions cannot
both be followed. The console is left as the static lifecycle template it
actually is, with a line saying so.

**A root `STATUS.md`.** Ungated hand-written status is the practice that has
already failed here — the console is the worked example, 64 commits stale with
four gates on it. Adding a fourth file claiming authority, with no check, would
have made the problem worse in exactly the shape it already has.

**GitHub issues as the source of truth.** They are the right *mirror* and
already hold #383/#382/#380/#379, but they are not offline-derivable: no CI
gate and no offline agent can read them, and this repository's test suite is
hermetic by design. Source of truth in the repo, issues as the mirror.

**A needle-free board with a human review checkbox.** That is the console again.

## Consequences

**What this buys.** A status document that cannot silently disagree with the
code. Finishing work now *forces* the board to be updated, in the same pull
request, because the gate goes red otherwise.

**What it costs.** A needle is a substring of a real source line, so an
unrelated refactor that reformats that line turns the gate red. That is the
intended trade — it makes a human look at the board — but it is a real
false-positive cost, and a looser needle would check nothing.

**What it cannot see, stated plainly:**

* **Work that lands under a different name than the needle.** If streaming ships
  without that exact literal, W1 stays green while being stale. The needle is a
  named contract, not a proof of absence.
* **Three rows carry no needle at all** (W5, W13, W14 — their shapes are not yet
  chosen, and #105 closes on production evidence rather than a diff). The gate
  checks nothing about them. The *number* of such rows is pinned, so a fourth
  cannot be added quietly, but that is a cap on the blindness, not a cure.
* **A row that should exist and does not.** A missing item is invisible to every
  check here.

Adversarial review remains the primary defence. Measured in this repository:
**0 of 16** `src/` defects were caught by any automated check and **10 of 16**
by adversarial review (`docs/metrics/defect-discovery-audit.md`). This gate
prevents a regression in the board; it does not find work nobody wrote down.

**The console loses 97 lines of stale hand-written status**, because the
demotion line had to go into `scripts/factory_next.py`'s template and
regenerating the file is what applies it. That content announced PR #91 and a
1342-test suite; it was 241 commits out of date and factually wrong about the
present. It is tracked, so it is recoverable in full:

```
git show e115d92:docs/00-factory-console.md
```

**Two documents were demoted in the same change**, so the board does not simply
become the fourth claimant: the console's `## Current phase` and the PHASE
STATUS block in `docs/analysis/R2-plan-review-findings.md` now say what they are
and point at the board. `docs/session-handoff.md` links it above the fold. Both
edits went into the *generators* (`scripts/factory_next.py`,
`scripts/session_handoff.py`), not the generated files, because a hand edit to
either is deleted by the next `make next` or `make handoff`.
