# ADR-0168: Parked work carries a reason, an owner and a resume-when; a branch is deleted only when nothing in it is lost

## Status

Accepted — 2026-10-16. The instructions are the owner's: CHG-047 (no branch deleted blindly),
CHG-048 (parked work reviewed first), CHG-049 (the stop rule, and Codex reviewing each plan before
code). The mechanism below is the session's design, reviewed by Codex before any code was written.

## Context

Measured on 2026-10-16 with `git ls-remote origin 'refs/heads/*'` and `gh pr list --state open`:
five branches other than `main` existed. Three belonged to pull requests closed without merging
(#500, #491, #523) and two to open drafts (#525, #567). No rule covered a branch whose pull request
closed without merging: `AGENTS.md` rule 18a and the delivery skill both say to delete the `merged`
branch. One closed branch still held the only copy of a script that measures an open decision
(issue #268, row W13), and four records in `main` cite it.

W28 shows what goes wrong without a record. On 2026-09-29 the owner parked it until two other pieces
of work were finished. Both finished, and nothing noticed, because the condition lived only in a
discussion log.

The owner asked that parked work be reviewed first in the next session, except work knowingly parked
behind other priorities (CHG-048). The owner also agreed to the stop rule the session proposed after
research, and to Codex reviewing each plan before code (CHG-049).

## Decision

1. **The board has a Parked table** (`docs/65-open-work.md`, section `## Parked`): one row per parked
   item, with where it lives (a draft pull request, a branch, an issue), the reason, the owner and a
   resume-when. A resume-when is `after W71, W72` (every named row reads DONE), `on YYYY-MM-DD`, or
   both joined by ` or `. Nothing else parses. The first cell is backticked (`` `W28` ``) so the
   board's row parser, which reads `| W28 |`, never reads or rewrites a Parked row.
2. **`make parked-check`** (`scripts/check_parked_work.py`) lists every remote branch other than `main`
   with no open pull request, and every parked item whose resume-when has come, with counts. It
   exits 1 when:
   - an open draft pull request has no Parked row;
   - a board row marked **STOP**, or waiting on the owner, has no Parked row;
   - a Parked row has an empty cell, a resume-when that does not parse, or names a row that does not
     exist;
   - it measured nothing: no remote branch read, `gh` unavailable, no Parked row, or the pull-request
     list reached its limit of 500 and may be cut short.
   A due item or a branch without a pull request is a list to act on, not a failure.
3. **`make handoff` shows that report** as a section and still writes its file and exits 0 (ADR-0045,
   ADR-0160). `make parked-check` is the part that fails.
4. **Parked work is reviewed first.** Step 0 of the delivery skill runs `make parked-check`. Every item
   it lists is resumed, re-parked with a new reason and resume-when, or closed, before new work is
   chosen. An item parked behind other work waits until its resume-when, as the owner's exception says.
5. **A branch ends one of two ways:** squash-merged into `main` and deleted, or recorded in the Parked table. A branch with
   no open pull request is deleted only when every file it holds is in `main` or archived there, every
   citation points at the new place, and the pull request that moved them has landed on `main` and is deployed.
6. **The stop rule.** After two failed fixes in a row (the fix did not work, or it added a defect):
   revert to the last commit that review cleared, write the root cause and a smaller plan, have Codex
   review it, and restart in a fresh session.
7. **Codex reviews each item's plan before any code**, as well as the code in each review round.

## The three closed branches (2026-10-16)

| Branch | Files not in `main` | What needs them | Where they went |
|---|---|---|---|
| `proposal/268-web-search-context-tokens` (#491) | ADR-0119 (a proposal the owner never took up); `scripts/proofs/search_context_band_sweep.py`; its test; edits to the ADR index, the board and `tests/unit/test_live_posture_check.py` | Issue #268 (open, W13); ADR-0120, ADR-0121, ADR-0125; `src/product_app/costs.py`; `tests/unit/test_bound_search_context_is_decoupled.py`; CHG-015 | The script and its test into `main` under `scripts/proofs/`, docstring corrected for ADR-0125; ADR-0119 to `docs/archive/2026-10/`; every citation repointed. The index, board and posture-test edits only registered ADR-0119 in `docs/adr/` and are not carried |
| `w29/judge-wiring-plan` (#523) | `docs/analysis/2026-09-29-w29-judge-wiring-plan.md` | Nothing in `main` cites it; the work it planned was built in #541 | `docs/archive/2026-10/` |
| `fix/e2e-visual-wait-for-fonts` (#500) | Edits to `e2e/fixtures/stabilize.ts` and `e2e/tests/invariants/trust-score-visual.spec.ts` | Nothing; review rejected the fix because its stated cause was false | Its patch and the reason, as a record in `docs/archive/2026-10/`; nothing is activated |

## Measurements

| What | Command | Result |
|---|---|---|
| The sweep runs on `main` | `PYTHONPATH=src .venv/bin/python scripts/proofs/search_context_band_sweep.py --fallback-prices` (copied into a worktree of `6872e46`) | EXIT=0; at 2500, 2900 and 3200: `0 mixes change band, 0 newly 'block'`; the point estimate moves on 715 of 715 mixes, the bound on 0 |
| Its test runs on `main` | `pytest tests/unit/test_search_context_band_sweep_refuses_an_unpriced_judge.py` | `3 passed` |
| GitHub's default pull-request page | `gh pr list --help` | `-L, --limit int  Maximum number of items to fetch (default 30)` |

## Rejected alternatives

- **Review every parked item at the start of every session.** It costs every session effort when
  nothing has changed, and it grows with the parked list. The check lists only what is due or
  unrecorded, so the review happens when it matters. (The owner's words asked for review first; the
  check is how it happens, see CHG-048.)
- **Delete a closed branch because GitHub keeps `refs/pull/<n>/head`.** GitHub documents no retention
  for those refs, and a pull-request ref is not in `main`, so it fails the owner's rule.
- **Parked rows as ordinary `| W28 |` rows.** Codex showed the board parser would read them as duplicate
  rows and rewrite their cells.
- **`make handoff` exits 1 on an empty input.** ADR-0045 and ADR-0160 rejected that: an offline handoff
  must still write its file.

## Consequences

- A new open draft, or a new row waiting on the owner, fails `make parked-check` until it has a Parked
  row.
- The check needs `gh` and the network; offline it fails, saying what it could not read.
- The resume-when dates are the session's choices unless a CHG row gives them; each Parked row says
  which.
