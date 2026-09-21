# Session handoff — 2026-09-22 (items 0, 1, #464, #469, #465 shipped; #268 input half proposed)

Read `AGENTS.md` first, then this. Figures are NOT restated here: each item
points at the commit body, the ADR, the pull request or the command that holds
them. The session ran unattended from the owner's prompt
`CONTINUE-BACKLOG-ULTRACODE-PROMPT.md` (untracked, at the repo root).

## 0. Preconditions

```bash
cd /Users/rohitagrawal/Projects/quorum-ai
git status --porcelain     # expect only the three CONTINUE-*.md files (untracked)
git worktree list          # expect quorum-ai (main) and quorum-ai-wt-268 (parked, see §3)
curl -s https://quorum.stackclimb.com/status | jq '{build_sha,live_execution,peer_critique_enabled,peer_critique_in_effect}'
```

`live_execution` is false. Nothing this session opened, extended or
re-affirmed a window, flipped a flag, moved a money value, closed an issue,
or made a paid call. The only network use was `gh`, `git`, `/status`,
`/ready`, and the free OpenRouter catalog the sweep fetches.

## 1. Merged and running in production

Every row: all six required contexts green on the PR head, every Deploy
**run** for the merge SHA enumerated (3 per merge; the extras cancelled by
concurrency) and its Deploy **job** read, `/status.build_sha` equal to the
merge SHA at the time.

| item | PR | merge | issue |
|---|---|---|---|
| item 0: the JS sweep skips uv's in-tree cache | #486 | `6653bb9` | none |
| item 1: what the owner already said about W4, W5, W7 | #487 | `4bdde99` | none (`docs/analysis/2026-09-22-decision-register.md`) |
| #464: a truncated mutation run with no survivor no longer passes | #488 | `9d75286` | open, commented |
| #469: the citation gate checks `.tsx`/`.mdx`/`.pyi` whole | #489 | `88f2341` | open, commented |
| #465: the 35 `_tavily_search` survivors triaged and cleared | #490 | `3452b2e` | open, commented; `/ready` 200 |

ADR-0118 (Accepted, test tooling only) records #464. ADR-0065 carries an
amendment note below its Status. Board rows W25, W26, W27 added, all
derived `DONE`.

## 2. Parked, with the evidence on the branch

**#268's input half, `cost_web_search_context_tokens`** — DRAFT PR #491,
branch `proposal/268-web-search-context-tokens`, worktree
`../quorum-ai-wt-268` left in place. ADR-0119 is `PROPOSED — AWAITING
OWNER`; the constant is still 2000. Measured: 43 of 48 readings above 2000;
every raise tried (2100 upward) moves at least two mixes into `block`, so the
decision-brief rule ("no mix moves into block") fails for every candidate.
The two questions the owner owes are in ADR-0119 §"The decision owed".

## 3. Owner decisions still open (asked in the session's first message)

1. #268 input half: the autonomy rule, and which value if any.
2. #458: couple the peer flag to the window scripts without flipping it.
3. #459: close on option 1 alone.
4. W4: how a user chooses N, and the range. **Blocks the authorised build.**
5. W5: build after W4.
6. #447: Route A or B (recommended neither yet).
Also: confirm `docs/analysis/2026-09-22-decision-register.md`.

Not started, by the prompt's own order: W4, W5, #447, #458, #459 (all
gated on the above); #105 (needs production logs); W7 (needs scoping).

## 4. What the prompt said that did not survive re-derivation

- **#464's "over-broad scope" did not reproduce.** `git diff -U0 | grep -c
  _tavily_search` prints 0 because a `-U0` hunk header names the enclosing
  class; `-W` shows the function edited on `a6770b2`. The prompt called the
  claim "confirmed"; ADR-0118 has the command. Fixes 2 and 3 were not built.
- `Field(ge=1, le=4)` is at **four** sites, as the prompt said; the board
  said three and is corrected.
- The 2026-08-31 W4/W7 "owner quotes" were **drafted by an assistant** and
  sent by the owner two minutes later (transcript `d1d57431`, type
  `assistant`, `2026-08-31T21:06:46Z`). The register says so.

## 5. Traps measured this session

- **Corrections are less reliable than originals, again.** The decision
  register's round-1 fix added two false sentences; round 2 deleted them
  rather than reword. Deleting makes no new claim.
- **`test_doc_records_the_numbers_the_shipped_gate_produced` goes red in any
  worktree where you just ran `make mutation-baseline`**: it reads
  `build/mutation/score.txt`. Delete your own `build/mutation` and
  `mutants/` (untracked, gitignored) before `make quality`.
- **`PYTHONPATH=src` is needed to run `scripts/proofs/*.py` under `uv run`**
  in a fresh worktree; the package is not installed into the venv.
- **A PROPOSED ADR is refused by the posture checker, and
  `test_only_the_three_genuinely_revoked_adrs_in_this_tree_are_refused` pins
  the exact set.** Add the new ADR to that list with its reason; do not
  relabel it Accepted.
- **A one-status log test admits that one status as a constant.** Use a
  status nobody would hard-code (503) or two different ones.
- **A test fake with a usable default hides a dropped argument.** The Tavily
  fake's `timeout: float = 0` let a call with no timeout pass; a sentinel
  default (`"NOT PASSED"`) is what made the mutant red.
- **The main checkout's `make quality` is green again** after item 0. The
  `e2e/tests/review/` scratch specs still make `test_no_orphaned_e2e_specs`
  red there; run gates in a worktree (they are untracked and do not follow).
