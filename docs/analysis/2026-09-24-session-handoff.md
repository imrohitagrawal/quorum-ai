# Session handoff — 2026-09-24 (W4 PR 3 shipped; BYOK plan recorded as PROPOSED; W5 scoped and parked)

Read `AGENTS.md` first, then this. Figures are NOT restated here: each item
points at the pull request, the commit bodies or the command that holds them.
The session ran unattended from the owner's prompt
`CONTINUE-W4-PR3-AND-BYOK-ULTRACODE-PROMPT.md` (untracked, repo root; written
by the previous session at the owner's request on 2026-09-23), starting
late on 2026-09-23 and finishing on 2026-09-24.

## 0. Preconditions

```bash
cd /Users/rohitagrawal/Projects/quorum-ai
git status --porcelain     # expect only the CONTINUE-*.md prompts (untracked)
git worktree list          # expect quorum-ai (main) and quorum-ai-wt-268 (parked)
curl -s https://quorum.stackclimb.com/status | jq '{build_sha,live_execution,peer_critique_enabled,peer_critique_in_effect}'
```

`live_execution` is false. Nothing this session opened a window, flipped a
flag, moved a money value, closed an issue, or made a paid call.

## 1. Merged and running in production

| item | PR | what it is |
|---|---|---|
| W4, 3 of 3: the copy outside the run path reads the decided words (CHG-011) | #496 | D1 to D7 delivered; board row W4 is complete in three pull requests |
| BYOK plan as PROPOSED: ADR-0121, the failure-mode page, board row W28 | #497 | docs only; nothing built; owner's delivery decision still owed |
| this handoff and the W5 scoping note | this pull request | docs only |

Every claim (byte-identical result and transcript views, 20 of 20 mutations,
lane floor 293 → 298 by measurement, the phone-width density numbers, the
two review rounds) is in PR #496's body and its three commit bodies, with
its command. Deploy verified per AGENTS rule 18 at close-out (the session's
final report has the Deploy job ids: #496 run 35913928780, #497 run 35917924555, each the one `success` among three runs per merge).

## 2. What is next

- **W5 (N=1 quick answer): PARKED.** `docs/analysis/2026-09-24-w5-scoping.md`
  names the three decisions still owed (the guard, the copy, the price
  posture). Ask them in one message; build only after all three.
- **BYOK: PLANNED, NOT NEXT.** ADR-0121 is `PROPOSED — AWAITING OWNER`; the
  owner has set the shape (CHG-011 D8) and not the delivery. Prerequisite
  before any per-run toggle: the confirmation token binds the slot list and
  the shape (CHG-011 D9; it bound neither when this was written; landed
  later the same day, ADR-0123).
- **#268** stays parked on `../quorum-ai-wt-268` (draft PR #491, ADR-0119).
  **#458, #459, #447** stay gated on owner decisions not taken.

## 3. Advisory debt recorded, not fixed

- The debate placeholder and the five synthesis-section tooltips sit inside
  `.panel.panel-section`, which `app.css` hides on every view; they carry
  neutral text and no renderer (PR #496 body).
- Below 600px the landing's capability line (D4) is not rendered: the two
  hero lines do not fit the #222 density bound together (measured in
  `app.css`'s comment; the spec pins the tradeoff).
- The advisory mutation gate reported 81.2% on #496: all 34 survivors are
  mutants of `_render_workspace_html` as a whole, which the gate measures
  because one line was added to it.
- `docs/10` FR-012 is titled "bring-your-own" and describes server keys; the
  traceability matrix cites two test files that do not exist. Recorded in
  the failure-mode page; repaired by the first BYOK pull request, not now.
- The composer's `Choose two to four different models.` helper line
  predates this session and describes the composer state (D3 allows it).

## 4. Traps measured this session

- **`getModelIds()` throws before `/v1/models/defaults` answers**: the
  template's placeholder `<label data-model-slot>` has no `.value`. A direct
  call from the landing hand-off left the CTA dead until reload. Found by
  review, not by any gate; the fix counts `select[data-model-slot]` and
  falls back to the default panel. Anything on the landing must not call
  `getModelIds()`.
- **`test_peer_caption_counts.py` pins the number of `describePeerCritique(`
  call sites and refuses any inline `critique_shape === "peer"` test.** A new
  reader of the shape goes through the helper (null means moderator) and the
  pin moves by one.
- **The phone-width landing has about 78px of slack against the #222
  density bound** (1515px on `main` before this session vs 1593.6px). Two
  more hero lines did not fit at any type size; measure with the spec's own
  setup (`/ready` stubbed live, 390×664) before adding landing copy.
- **`diff-cover` measures nothing for a dict-literal continuation line**: the
  island key added to `main.py` produced "No lines with coverage information
  in this diff" and the gate exits 0 with its empty-denominator notice. The
  pinned literal assertions are the cover.
- **The cited-paths gate resolves any `tests/…py` token on an added line**,
  including a sentence saying the file does NOT exist. Name a missing file
  without its path.
- **A commit body written before its check is a claim, not a result**: one
  "re-checked at 53d0a11" sentence in the BYOK commit was written first and
  verified after (true, by luck). Run the check, then write the sentence.
- **Reviewers sharing the scratchpad re-extracted over each other's copies**
  in round 1; give every reviewer a `$RANDOM-$RANDOM` directory and a port
  above 18200.
- **The provenance of an "owner decision" needs the transcript record type.**
  A prompt file written by a session at the owner's request is the
  session's wording; the owner's words are the `type: user` records. Two
  review rounds were spent on sentences that blurred this.
