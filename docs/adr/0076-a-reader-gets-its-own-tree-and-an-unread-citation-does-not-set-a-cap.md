# ADR-0076: A reader gets its own tree, an unread citation does not set a cap, and a gate's exit status is never read through a pipe

## Status

Accepted — 2026-08-26

## Context

Three method rules in `AGENTS.md` were each contradicted by measurement during
the session that shipped ADR-0075 (PR #384). None of them is a code change; all
three cost real work while they were wrong, and none is catchable by a gate —
they are about how a session drives the tree and how it reads evidence.

### 1. Rule 9 protected the reviewers from writing, and nothing protected the tree

Rule 9 says *"tell every reviewer IN CAPITALS not to write."* It says nothing
about the **orchestrator** writing while readers run. Two false signals in one
session, both from that gap:

- A read-only planner was mid-measurement when the orchestrator committed. Its
  baseline was taken across two different trees, so the comparison it reported
  was between states that never coexisted.
- A `make diff-cover` was backgrounded, then `synthesis_consensus.py` grew by 15
  lines while it ran. `tests/unit/test_not_invoked_is_not_evidence.py` went RED:

  ```
  assert 'invoked=invoked' in 'def _opening_reflected_in_final(...)'
  ```

  That assertion is not about `_opening_reflected_in_final` at all. Verified on
  this branch:

  ```
  $ grep -n "getsource\|invoked=invoked" tests/unit/test_not_invoked_is_not_evidence.py
  279:    source = inspect.getsource(synthesis_consensus.classify_model_alignment)
  280:    assert "invoked=invoked" in source, "the classifier must pass invoked= explicitly"
  ```

  `inspect.getsource` resolves a function's body by **line number against the
  file on disk**, not against the module object already imported. Shift the file
  under a running interpreter and it reads a different function's text. The
  failure names a file the diff never touched, which reads exactly like a
  regression and is not one.

Rule 12b already gives a **mutating** reviewer its own
`git archive HEAD | tar -x -C <dir>` copy. The measured failure shows the
hazard is not mutation — it is *any* concurrent write to a tree something is
reading.

### 2. Rule 10's finder cap rested on a citation this repo had already downgraded

Rule 10 read *"Two lenses, not five. Two reviewers ≈ four; one is worse (Porter
et al., IEEE TSE 1997)."* That traces to exactly one row of the repo's own
evidence record:

```
$ grep -n "^| 1.1 " docs/evidence/2026-07-30-engineering-practice.md
23:| 1.1 | **Two reviewers ≈ four reviewers. One is worse.** ... | `ASSERTION` — **downgraded from `WELL-EVIDENCED` on 2026-07-30, see note below** | Porter, Siy, **Toman** & Votta ... 1997 ...
```

The same file's correction note says why, in its own words: *"An author list
that wrong is proof the primary source was not read"* — the paper is paywalled,
and neither the quote nor its figures were confirmed against it. It also records
that no modern replication exists, and that the study measured **human**
inspection teams **in meetings** on 1997 C++.

Rule 11 forbids building on an assumed claim without checking, and rule 8c
forbids gating behaviour on an upstream you have not measured. Setting an
LLM-agent fan size from a 1997 human-meeting result is the same move against a
different population.

What the same document grades `WELL-EVIDENCED` points the opposite way:

```
$ grep -n "^| 2.1 " docs/evidence/2026-07-30-engineering-practice.md
70:| 2.1 | **Best measured LLM review: precision 16.65%, recall 23.18%, F1 19.38% ...** | `WELL-EVIDENCED` for the measurement, but **preprint** | SWRBench, arXiv:2509.01494v2 ...
```

Read as two separate numbers rather than one verdict:

| Number | What it constrains | Direction |
|---|---|---|
| recall **23.18%** | one lens misses ~77% of real findings | more finders, not fewer |
| precision **16.65%** | ~83% of what a finder reports is noise | verification is the bottleneck |

Session evidence from 2026-08-26, **inherited from that session's record and
not re-measured here**, n=1: four agents reviewing one diff produced four
**disjoint** finding sets. That is consistent with low recall per lens; it is
not a replication of anything.

### 3. A gate's exit status read through a pipe is the pipe's exit status

Measured on this box, 2026-08-26:

```
$ ( sh -c 'exit 1' | tail -1 ); echo "EXIT_THROUGH_PIPE=$?"
EXIT_THROUGH_PIPE=0
$ sh -c 'exit 1' > /dev/null 2>&1; echo "EXIT_DIRECT=$?"
EXIT_DIRECT=1
```

`make quality 2>&1 | tail -30` therefore reports **tail's** status. Measured on
this repo's own target, with one file deliberately misformatted and then
restored from a `cp` copy:

```
$ ( make format-check 2>&1 | tail -3 ); echo "EXIT_THROUGH_PIPE=$?"
Would reformat: src/product_app/untrusted_text.py
1 file would be reformatted, 351 files already formatted
make: *** [format-check] Error 1
EXIT_THROUGH_PIPE=0

$ make format-check > /tmp/fc.log 2>&1; echo "EXIT_DIRECT=$?"
EXIT_DIRECT=2
```

The gate printed its own failure and the shell still reported success. The
prior session records this biting four times in one sitting — that count is
inherited; the behaviour above is measured here. Piping to `tail` is what keeps
a long gate log readable, which is exactly why the habit is hard to drop.

Two adjacent traps have the same shape — a cheerful last line that did not set
the exit code. Both measured here, with `line-length = 100` from
`pyproject.toml:75`:

```
$ awk '{print NR": "length($0)}' m.py
2: 204
$ uv run ruff format --line-length 100 m.py --check; echo "EXIT=$?"
1 file already formatted
EXIT=0
$ uv run ruff check --isolated --line-length 100 --select E501 m.py; echo "EXIT=$?"
E501 Line too long (204 > 100)
EXIT=1
```

`ruff format` does not reflow prose inside a docstring, so `format-check` is
green on a line `lint` rejects. And `make quality` is
`format-check lint type-check test` (`Makefile:107`), so mypy runs after ruff:
`All checks passed!` is routinely not the line that set the status.

## Decision

Three edits to `AGENTS.md`, and nothing else. No code, no gate.

**1. New rule 9a — never move the tree under a running reader.** Extends rule
12b from mutators to readers: a read-only agent that runs the suite gets its own
`git archive` copy. Either the gate runs or you edit, never both. And a
full-suite failure in a file the diff never touched is a **phantom until re-run
on a stable tree** — investigate the tree before the diff.

**2. Rule 10 re-graded**, not deleted. The half that survives — *spend the
marginal effort on verifying findings, not on generating more* — is kept and is
now supported by the precision number rather than by the 1997 paper. The finder
**cap** is marked UNMEASURED for agents.

**3. New rule 13f — never read a gate's exit status through a pipe**, with the
two-step form that works, plus the `ruff format` / `ruff check` and
`ruff` / `mypy` neighbours.

## Rejected alternatives

### Making rule 9a mechanical instead of prose — REJECTED as unavailable here

A hook that refuses a write while a background gate holds a lock would enforce
what prose only influences, and this repo's own position (global CLAUDE.md,
"enforcement is mechanical, never prose") prefers that. It is not available:
the writer and the reader are the *same* agent process driving the same shell,
so there is no second party to lock against, and a lock file the agent both
takes and ignores is theatre. Rule 16d's own note applies — *"this rule is
influence, not enforcement… if you notice it being skipped, that is the signal
to make it mechanical."* Recorded as the trigger, not shipped as a gate.

### Deleting rule 10 outright — REJECTED

The downgrade is of the *citation*, not of the practice. Precision 16.65% is
`WELL-EVIDENCED` and says directly that verification is where the marginal
effort pays. Deleting the rule would throw away the supported half along with
the unsupported half.

### Raising the cap to a new number — REJECTED as the same error

Replacing "two" with "four" would set an agent fan size from the same absent
measurement, in the other direction. The honest statement is that the ceiling is
unknown; the floor is two, from recall 23%.

### Fixing rule 13f with `set -o pipefail` — REJECTED as too narrow

`pipefail` is not portable across every shell an agent may be handed, it changes
the status of pipelines that are *supposed* to end early (`| head`), and it does
nothing for the two neighbouring traps, which are not pipes at all — they are
two different tools in one make target. Writing the log to a file and echoing
`$?` needs no shell option and makes the full log available afterwards, which
piping to `tail` destroys.

## Consequences

- Read-only reviewers now get their own tree copy by default, not only when they
  intend to mutate. That costs one `git archive` per reviewer — measured in
  milliseconds — against two false signals in one session.
- Review fan size stops being justified by a citation nobody read. Sessions may
  run more than two finders where recall matters, and are told plainly that the
  cap is unmeasured, rather than believing a number.
- Gate logs get written to a file and tailed afterwards, rather than piped. The
  log survives, which is what rule 2 ("open the log and find the number")
  already wanted.
- **These are influence, not enforcement.** Nothing in this ADR goes red on its
  own. Rule 9a in particular is unenforceable by construction, for the reason in
  the rejected alternative above, and should be made mechanical the moment a
  session notices it being skipped.
