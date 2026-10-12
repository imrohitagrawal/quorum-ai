# Session handoff — 2026-10-13

The session that ran from 2026-10-11 to 2026-10-13 (transcript `20d36bac`) on the how-we-work plan,
packages A and B. The source of truth is `git log` and the ADRs; this note says where things stand.

## Shipped

| Pull request | Merge commit | What | Decisions |
|---|---|---|---|
| #558 | `b66b107` | Package A: one process skill (`.agents/skills/work-item-delivery/SKILL.md`), loaded by `AGENTS.md`; `make skill-route ITEM=…` / `DIFF=…`; `make prompt-check`; nine old root prompts archived | ADR-0159, ADR-0160, CHG-040 |
| #559 | `9d55a96` | Package B: three status homes named in `docs/README.md`; `docs/product-readiness.md` generated from production; the completion-word check; `PRESENT@<sha>`; `make board-github-check` | ADR-0161, ADR-0162, CHG-041 |

Each was verified by the Deploy job of the run that succeeded and by `/status` `build_sha`: #558 at
`b66b107` (2026-10-11T18:20:13Z), #559 at `9d55a96` (2026-10-12T19:02:22Z). Neither changed a file
under `src/`.

Issues #458 and #459 were checked and closed with the owner's approval (CHG-041 (a)), each with an
evidence comment. Open issues are now #105 and #268, on the board as W14 and W13.

## Next

W55, then W56. The prompt is `CONTINUE-W55-W56-PROMPT.md` in the owner's main checkout, untracked,
so a fresh clone does not have it; the version it replaced is archived in `docs/archive/2026-10/`.
It names the skill and the approvals. Without it, start from the skill and board rows W55 and W56.

## The fresh-reader test (package B's user-journey test)

The same question ("what is live, what is open, is it ready?", saved word for word) was put to a
reader started with no project memory (`claude -p --safe-mode`):

| | Before, on `main` at `c894f78` | After, on this handoff branch |
|---|---|---|
| Matched | 9 of 19 | 15 of 19 |
| Partial | 2 | 3 |
| Wrong | 4 | 0 |
| Missing | 4 | 1 |

The after reader took the build, the switches and the verdict from `docs/product-readiness.md`, and
the open work from the board. It still met two answers in two places:
- `/ready` reports `"status": "ready"` while the verdict says "Not ready". The file does not say that
  `/ready`'s "ready" means only that the server is up;
- the board's "Verified at" line names an older commit than its rows.

## Left as advisory

- Board rows W57 to W67: the 2026-10-11 advisory leftovers, large web pages (W66), and one
  completion-check gap (W67).
- The "Left as advisory" sections of #558 and #559 list the rest. The main ones:
  - the router over-routes real feature commits;
  - a real citation supports every claim in its Markdown block;
  - the readiness file names the build before the merge that commits it, because every merge
    redeploys.

## Traps met this session

- A "merged" or "in production" written in a handoff, an ADR, a tracked root prompt or a status
  document now needs a cited pull request, a commit on `main` or a CHG row in the same block, or
  `make validate` fails. Write status fields one per line: "Merged: no" is read on its own line.
- A new root prompt needs a paragraph that opens with bold **Process:** and names the skill file.
  `make prompt-check` judges the rendered page, so a line inside a code block does not count.
- `make prompt-check`, `make completion-check` and `make readiness` run through `uv run`: the
  system Python has neither the Markdown parser nor a certificate store.
- Hand-written Markdown rules failed twice in both packages; both checks now use the CommonMark
  parser the project already pins (ADR-0029).
- A narrow re-check after round 2 found a regression in a round-2 fix both times. Budget for it.
