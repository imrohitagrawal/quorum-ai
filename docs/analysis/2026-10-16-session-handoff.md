# Session handoff — 2026-10-16

The session of 2026-10-16 (transcript `6a12f59d`) ran `CONTINUE-PARKED-WORK-W28-W70-PROMPT.md`,
archived by this pull request as `docs/archive/2026-10/CONTINUE-PARKED-WORK-W28-W70-PROMPT.md`.
The source of truth is `git log` and the ADRs; this note says where things stand.

## Shipped

| Pull request | Merge commit | What | Decisions it added or rests on |
|---|---|---|---|
| #570 | `ad959d2` | Item 1: owner messages recorded as CHG rows; the Parked table and `make parked-check`; the stop rule and Codex plan review in the skill and `AGENTS.md`; the next-session prompt as a template with a name and section check | added CHG-047 to CHG-052, ADR-0168, ADR-0169 |
| #571 | `467ae9f` | W28: research on the six bring-your-own-key decisions, `docs/analysis/2026-10-16-w28-decision-research.md`; no decision recorded | rests on CHG-051; added none |
| #567 | `3825a12` | W70: the secret scan reads every committable file, joins split keys, knows the key shapes of five services and refuses home-folder paths | added ADR-0167, CHG-045, CHG-053, CHG-054; rests on CHG-049, CHG-050 |

This session checked each of #570, #571 and #567 in production. The Deploy job concluded
`success`, `/status` `build_sha` matched the merge commit, and `/ready` returned 200:
- #570: run 38827514235.
- #571: run 38836258854.
- #567: run 38903234762, after one re-run of the E2E job (see "Advisory left").

Production cannot show W70: the scanner runs in CI and locally. Its proof is 211 tests in the six
`tests/unit/test_security_scan*.py` files and 14 in the home-path rewrite tests, and CI's
`validate-and-test` log for #567, which reads `Security scan passed (1712 files scanned, 0 findings)`.

## W70: what moved out

The stop rule (CHG-049) fired twice in W70.
- **Named secrets.** Three fix rounds in a row on the named-secret rule each added a defect, so the
  rule moved to row W83. Its last version and tests are at `70080f3`. On 2026-10-16,
  `git merge-base --is-ancestor 70080f3` against `refs/pull/567/head` (`e41e385`) exited 0, so the
  commit stays reachable after the branch is deleted.
- **Input the kept rules cannot read** moved to row W84: UTF-16 files, encoded keys, fragments
  joined with backticks, ADR-0167's advisories, and `++file:` in a merge commit's combined diff.
- **The `file:` part of the home-folder rule.** The builds `f4f994a` and `04c5202` each failed
  review. The owner chose to finish in this session with no further detection changes (CHG-054).

Three limits are recorded by the owner's choice (CHG-053, ADR-0167): a PATH entry that is itself a
URL, a web path under `/Users` with no `/` after the name, and Windows backslash paths.

## Left for the owner

- **W28's six decisions.** The research recommends, one line each:
  1. keep the key in server memory only;
  2. one key per session;
  3. signed-in users only;
  4. drop the key at sign-in;
  5. stop at the next stage, with the run bound to the key it started with;
  6. FR-012 optional, two postures, keeping and sharpening AC-026.

  It also recommends OpenRouter's OAuth sign-in (PKCE) with a credit limit and expiry, if a free
  trial run shows OpenRouter enforces them. No decision is recorded. W28's resume-when in the
  Parked table names W71 to W81 only, so W82, W83 and W84 do not hold it back.
- **W74** needs the owner's approval of its spend, and **W78** an owner decision. Both are parked
  until W82 has ranked the security rows.

## Traps learned

- A Codex job started directly through `codex-companion.mjs` does not wake the session when it
  ends. This session sat idle for about 3.4 hours waiting on one. Use the `codex:codex-rescue`
  agent, whose end the harness reports.
- In zsh, `$r:s` is a variable modifier, so `git show $r:scripts/security_scan.py` breaks. Write
  `${r}:scripts/security_scan.py`.
- Root prompts and `docs/adr/0*.md` are in the completion-claims check's scope, and
  `tests/unit/test_cited_paths_resolve.py` reads committed lines.
- Since W70, a home-folder path written out in any committed text fails the scan: a test comment,
  a docstring, a CHG row. Build such paths at run time in tests and describe them in prose
  elsewhere.
- For the home-folder rule, allow-lists of the characters that may come before a path kept missing
  forms. A rule that denies a match at a path boundary held up.
- Each fix round on a hand-written detector found new edge cases. Bound such work with the stop
  rule and board rows, not more rounds.
- `refs/pull/N/head` moves only when the branch is pushed. Check reachability before citing it.
- W28's whole board row must stay as it was at commit `b66b107`:
  `tests/unit/test_one_status_review_round_1.py` compares it. Put W28 news in the Parked table.
- A row turned DONE must lose its Parked line, or `make parked-check` fails.
- Do not share a venv by linking `.venv` into a worktree. Since W70 the scan reads every file git
  could commit; `.gitignore`'s `.venv/` matches only a directory, so the link is read and its
  target is a home-folder path: `.venv:1: home_directory_path`, and 18 tests fail. Set
  `UV_PROJECT_ENVIRONMENT` to the main checkout's `.venv` instead.
- Run long gates in the background under `caffeinate -i sh -c`, logging to the scratchpad, or
  the Mac sleeps and the run stretches.

## Advisory left

- **W60, the signed-in E2E lane.** The push run of `3825a12` (#567) failed once in
  `history-refresh.spec.ts` at 700 px: the page never showed `#account-email`, and the server logged
  no completed sign-in for that test. No `src/`, `e2e/` or workflow file changed in #567. The
  re-run of the failed job (attempt 2 of run 38893581540) passed. The row now lists this run.
- **W83 and W84** hold W70's leftovers (above).
