# Session handoff, 2026-10-19 to 2026-10-27 (transcript `bda9c799`)

Written by the session. The owner's decisions are the CHG rows named here.

## Pull requests #582 to #589

Before this handoff pull request, production `/status` reported `build_sha`
`d92f628ba6aa981a8882d6f058f5c1f7ab3d7df7`, the squash merge of #589, and `/ready` answered 200;
`make readiness` read the same build at 2026-10-26T21:04:01Z (UTC).

| Pull request | What |
|---|---|
| #582 | W87-2: deleting an account needs a Google sign-in within the last 10 minutes |
| #583 | W87-3: an operator command ends signed-in sessions; every process reads the cutoff on each request |
| #584 | pypdf 6.21.1 and certifi 2026.10.19 (CHG-085) |
| #586 | pypdf 6.21.2 (CHG-086) |
| #587 | W88: another site can open the page but cannot load it hidden or ask for a session |
| #588 | W87-2: the restored question stays in view through a font reflow |
| #589 | W105: open tabs of the same person share a renewed anti-forgery token (CHG-089) |

#589 also fixed a CI break: GitHub's `ubuntu-latest` moved from 24.04 to 26.04, where
`git clone --local` failed with "Invalid cross-device link"; the replay-scope test now clones with
`--no-hardlinks`. Every CI job runs on `ubuntu-latest`, so watch the next deploys.

## Recorded in this handoff pull request

- CHG-092 and ADR-0181: the owner's standing rule for a new security warning (update first,
  without asking, within the same major version; ask in four cases).
- CHG-093: board row W45 stays open (not the session's recommendation).
- CHG-094: W113 is rebuilt on a Markdown parser in a fresh session, limit 2,900 changed lines.
- CHG-092 to CHG-094 each carry the clause W113's script renders, and their extracts are in
  `docs/owner-answers/`. Nothing on `main` checks them until W113 merges.
- The board: anchor re-stamped to `d92f628` (it was 61 first-parent commits behind on W113's
  branch, past the limit of 60); new row W114, parked.

## Not finished

- **W114** (the W87-3 follow-up): parked under the stop rule. See its Parked line. CHG-088 is
  reserved for its owner answers; CHG-060 keeps the detail out of the repository until pull
  request A ships.
- **W113** (the owner's quoted decisions match the transcript): branch `w113/owner-quote-check`,
  local only, head `1e44865`, worktree `quorum-ai-w113`, a bundle backup in the owner's evidence
  folder `2026-10-26/w113/`. Two review rounds ran; round 1's 18 findings were fixed or recorded in its fix plan; round 2
  reproduced that the check reads the log as lines of text, so Markdown can hide a row or the true
  answer. The folder's `STATE.md`, `r2/root-cause-and-plan.md` and `r2/codex-plan-review.md`
  ("sound with changes") are the starting point.
- **W80, W75, W76**: not started.

## Traps for the next session

- **Numbering across branches.** CHG-088 is W114's; CHG-090 and CHG-091 are on W113's branch;
  CHG-092 to CHG-094 are here. ADR-0179 is on W113's branch; ADR-0181 is here. When W113 merges
  `main`, both logs end in appended rows: put them back in number order (W113's own check
  refuses rows out of order) and keep both sets of extracts.
- **W113's check refuses a new row numbered below CHG-090.** So add CHG-088 (W114, pull
  request A) before W113 merges, as the prompt's order does, or the check refuses it.
- **The board anchor counts the branch's commits too.** A long branch can push it past 60 again;
  merge `main` and re-gate.
- **Transcripts under `~/.claude/projects/` are read-only.** A test designer's command nearly
  sent the live transcript to `/dev/null` (2026-10-26); the permission check refused it.
- **`owner_answers.py extract --transcript`** takes a file path, not an 8-letter id.

## For the owner

- W113's one-off audit of CHG-012 to CHG-089 is in `2026-10-26/w113/audit-report.txt` in the
  evidence folder: 118 answers quoted exactly, 4 ambiguous, 36 unmatched, 12 rows that cannot be
  checked. No old row was edited. The 40 ambiguous or unmatched answers are for you to look at.
- W114's pull request B needs one answer before it is built (whether its sign-out may evict);
  the next session asks it with an example.

## Not verified

- W105 in a real signed-in browser: two signed-in tabs actually sharing, Firefox and WebKit
  signed in, hidden tabs, a browser-cache restore, and a real Google sign-in.
- Recorded in review reports and not re-measured here: WebKit scrolls sideways at 390 px wide,
  which W105's review saw on `main` before W105; the mutation job's
  "No such file or directory: 'src'" in `test_end_sessions_command`.
