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
| …and staler by content | `git rev-list --count --since=2026-07-23 origin/main` | its content is dated 2026-07-23, and roughly **240** commits (about **190** first-parent) had landed since. Both figures grow with every commit, so they are given as magnitudes rather than pinned — the count above, against the console's own last touch, is the stable one |
| Four open issues appear in no plan | `gh issue list` against `grep -rn` over `docs/` and the root prompts | #383, #382, #380, #379 exist only in `gh` |
| The phase is claimed in more than one place | `git grep -n "authoritative" origin/main -- docs/` | **one** file uses the word to claim it — `docs/analysis/R2-plan-review-findings.md`. `docs/session-handoff.md` names R2 as authoritative *over* its own line, and `docs/00-factory-console.md` asserts a `## Current phase` without using the word at all. Three files carry a phase; one claims authority; a reader cannot tell which to believe |

The console still announced work from PR #91 and quoted `pytest 1342 passed`
against a suite that had grown past **3,800** (`uv run pytest --collect-only -q`
— deliberately not pinned to a digit here: it moves with every test added, and a
figure that changes under its own repository is the kind this ADR exists to stop
being written down).

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

**Nobody writes the State column. It is derived from the tree.**

The board carries the evidence expression only. `scripts/check_open_work.py`
reads each needle off disk and generates the state — `PENDING` while the claim
holds as written, `DONE` when its opposite holds, `UNPINNED` when there is no
needle — and `--check` refuses when the checked-in column disagrees. A row
cannot be marked done by editing its status; it moves when the tree moves. This
is `scripts/generate_adr_index.py`'s shape, cited in the first draft of this ADR
and not actually followed until the third.

Needles match **code text only**: a `#` starting a line or following whitespace
ends that line before the search. The whitespace guard is the load-bearing part
— a naive cut at the first `//` truncates W16's needle line to `URL = "https:`.
Only `#` is listed because every file the board pins is Python, TOML or
Markdown. Verified against all 13 live needles — every one still matches after
stripping.

Three further pieces:Three further pieces:

* **Two count pins.** The board states its own row count and its own
  unpinned-row count as digits, both compared against the parsed table. Copied
  from `tests/test_doc_gate_consistency.py` Part D, plus its bite-proof.
* **Two anti-vacuity floors, not one.** The table must parse at least one row,
  *and* at least 8 evidence claims must actually be read off disk. The second
  does not follow from the first, and review proved it: a board of entirely
  unpinned rows parses fine and measures nothing.
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

### Three designs, two of them defeated before merge

This is the part worth reading. Each design was green on every gate when review
broke it.

**Draft 1 — polarity typed by the author.** Each row said `ABSENT` or `PRESENT`
and the gate checked it. A four-lens review demonstrated the hole in one
command: replacing every `| PENDING |` with `| DONE |` left the gate exiting 0
and printing `0 PENDING`, with **zero bytes changed under `src/`** and all 22
bite-proofs passing. The board, this ADR and the gate's docstring each said in
plain words that this could not happen.

**Draft 2 — state coupled to polarity.** `PENDING` asserted the claim as
written, `DONE` its opposite, so flipping only the state word went red. A second
review round broke it three ways, all reproduced independently before being
acted on:

| Route | Result |
|---|---|
| flip the state word **and** the polarity word together | gate exits 0, `17 rows (0 PENDING)`, 32 tests pass, no source change |
| unpin a row (evidence `—`), mark it `DONE`, bump the count | gate exits 0 — and it worked on a **STOP** row |
| append `# TODO: we still need to send "stream": True here` to `providers.py` | flips W1's evidence: a comment saying the work was *not* done changed the row |

The root cause both drafts share: **the state and the claim were typed by the
same hand, in the same file.** Coupling two author-controlled fields to each
other raises the number of tokens an author edits; it does not create an
independent check. Draft 2 moved the cost from one token to two and claimed
total protection.

**Draft 3 — derive the state.** Above. Routes 2 and 3 are closed outright: an
unpinned row can only render `UNPINNED`, and needles ignore comments.

**Route 1 is NOT closed, and that is a decision, not an oversight.** The polarity
word is part of the claim and the author writes the claim, so rewriting the
polarity and the state together still passes — the derivation reads the flipped
polarity and derives the flipped state. Closing it needs the evidence text to be
immutable between anchor stamps (comparing each row against
`git show <anchor>:docs/65-open-work.md`). That guards against a **deliberate**
author. The failure this board exists to prevent is a status document rotting
through **carelessness**, and derivation closes that completely; rewriting a
claim and a status together is a visible change to the claim in the diff, which
is what review reads. Adding a third mechanism for a threat outside the model
would be the disproportion this repository has been burned by before.

That residual is pinned by
`test_rewriting_the_evidence_claim_is_accepted_and_that_is_the_known_limit`,
which asserts the limit and goes red if anyone closes it — so the stronger
promise cannot be quietly written down a third time.

Four further findings from the same rounds, each reproduced by command:

| What was claimed | What was measured |
|---|---|
| the evidence family is covered by tests | every bite-proof called the checking functions directly; `check_all`'s wiring to both the evidence and the freshness family could be deleted whole with every test green |
| `make validate` runs the checker | the test asserted a **whole-file** substring, so the recipe could be gutted to `@true` with the name left in a comment. The recipe-body version was then defeated by a leading `-`, make's ignore-errors prefix |
| the gate refuses an empty input | the only floor was on the **table**; a board of entirely unpinned rows exited 0 having read **zero** needles |
| the archive-copy skip works | `has_git_history` used `git rev-parse --git-dir`, which walks **up** through parents, so an unpacked copy under a repository answered yes and the freshness family ran against the wrong history — the exact phantom failure it was added to prevent. It now compares `--show-toplevel` against the root |

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
  without that exact literal, W1 stays satisfiable while being stale. The needle
  is a named contract, not a proof of absence.
* **Work that lands by a different route under the same name.** W15 is pinned on
  `_bound_sniff_time` being present-and-undefined; deleting the dangling
  references flips it, but *defining* the function would not.
* **Four rows carry no needle at all** (W5, W7, W13, W14 — their shapes are not
  yet chosen, #105 closes on production evidence rather than a diff, and W7 lost
  its needle to the review finding above). The gate checks nothing about them.
  The *number* of such rows is pinned, so a fifth cannot be added quietly, but
  that is a cap on the blindness, not a cure.
* **A row that should exist and does not.** A missing item is invisible to every
  check here.

Adversarial review remains the primary defence. Measured in this repository:
**0 of 16** `src/` defects were caught by any automated check and **10 of 16**
by adversarial review (`docs/metrics/defect-discovery-audit.md`). This gate
prevents a regression in the board; it does not find work nobody wrote down.

**The console loses 88 lines of stale hand-written status and gains 9**
(`git diff --numstat origin/main...HEAD -- docs/00-factory-console.md` → `9 88`),
because the demotion line had to go into `scripts/factory_next.py`'s template
and regenerating the file is what applies it. That content announced PR #91 and a
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
