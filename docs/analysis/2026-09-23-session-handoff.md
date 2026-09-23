# Session handoff — 2026-09-23 (W4 PR 2 shipped: the workspace removes and adds a slot)

Read `AGENTS.md` first, then this. Figures are NOT restated here: each item
points at the pull request, the commit bodies or the command that holds them.
The session ran from the owner's prompt "build PR 2 of the W4 plan" on top of
`CONTINUE-BACKLOG-ULTRACODE-PROMPT.md` (untracked, repo root).

## 0. Preconditions

```bash
cd /Users/rohitagrawal/Projects/quorum-ai
git status --porcelain     # expect only the three CONTINUE-*.md files (untracked)
git worktree list          # expect quorum-ai (main) and quorum-ai-wt-268 (parked)
curl -s https://quorum.stackclimb.com/status | jq '{build_sha,live_execution,peer_critique_enabled,peer_critique_in_effect}'
```

`live_execution` is false. Nothing this session opened a window, flipped a
flag, moved a money value, closed an issue, or made a paid call.

## 1. Merged and running in production

| item | PR | what it is |
|---|---|---|
| W4, 2 of 3: the workspace removes and adds a slot; copy reads the panel size | #494 | ADR-0120 decisions 2 and 5 delivered; board row W4 derives DONE on its needle |

Every claim (estimator identical to the cent main vs branch, byte-identical
result/transcript views, lane counts, 16+4 mutants) is in PR #494's body with
its command. Deploy verified per AGENTS rule 18 at close-out (see the session's
final report; the `/estimate` probe with 2 and 4 default slots is there too).

## 2. What is next for W4

**PR 3 — copy that names "four" outside the run path.** On `main` after #494:
`app.js` 6082, 6184–6188, 8911–8912; `workspace.html` 87 and 768 (landing),
941 (tooltip attribute), 949 (debate panel pre-run placeholder); `main.py`
306 / 337 (landing subhead). Text only; the citation and rendering gates cover
it. `landing-cta-reachable.spec.ts` pins the landing copy — check it before
editing.

W5 (N=1 quick-answer mode) stays after W4. #268's input half is still parked
on `../quorum-ai-wt-268` (draft PR #491, ADR-0119 PROPOSED).

## 3. Advisory debt recorded in #494, not fixed

- `model_slots: []` answers with Pydantic's generic envelope (`min_length=1`);
  one and five get the typed one (ADR-0120 decision 6).
- The confirmation token does not bind the slot list; equal-cost 2- and
  4-slot mixes share a token (only seen in the ALLOW band).
- `_extract_weak_support` / `_build_uncertainty` count RECORDED answers and
  phrase the all-clear with the REQUESTED size.
- An estimate response in flight during a remove/add paints `by_model` rows
  by position (same race as a swap).

## 4. Traps measured this session

- **Unit harnesses run ONE app.js function under node.** `computeDemoModeBannerCopy`,
  `describeSynthesisInput` and `initModelSlotSelection` are sliced by brace
  count; a new module-level helper called inside them is a `ReferenceError`
  there (6 tests), and `el(...)` inside `initModelSlotSelection` is undefined
  under its shim (2 tests). Keep those functions self-contained.
- **The negative-assertion classifier counts only `toBeGreaterThan(0)` or
  `toBeGreaterThanOrEqual(<positive literal>)` as a numeric partner.**
  `toBeGreaterThan(20)` is not one. Run
  `node e2e/tools/check-negative-assertions.mjs <spec>` before `make quality`.
- **Board polarity describes the OPEN state.** `ABSENT path :: needle` derives
  DONE once the needle exists; flipping it to `PRESENT` when closing the row
  makes `make validate` say "the tree says PENDING".
- **`make diff-cover` aborts on any test failure before measuring.** A red
  diff-cover after a red quality is the same failure, not a coverage number.
- **The full-document dump differs on hidden views and the session trail's
  clock.** For rule 13e, compare the result/transcript view `outerHTML`
  (byte-identical) and show every full-document hunk sits in a `hidden` view.
- **The invariants lane counted 293 locally**, not 283+9; the 2026-09-09
  local/CI one-test gap was not re-measured. The floor is set to the local
  count; read CI's own number on the PR.
