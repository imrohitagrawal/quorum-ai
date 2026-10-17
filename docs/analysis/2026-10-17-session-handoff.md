# Session handoff — 2026-10-17

The session of 2026-10-17 (transcript `21387da6`) ran `CONTINUE-SECURITY-W82-W71-W81-PROMPT.md`,
archived by this pull request as `docs/archive/2026-10/CONTINUE-SECURITY-W82-W71-W81-PROMPT.md`.
The source of truth is `git log` and the ADRs; this note says where things stand.

## Shipped

| Pull request | Merge commit | What | Decisions it added or rests on |
|---|---|---|---|
| #573 | `1571295` | W82: the security baseline. `docs/41-security-controls.md` lists 97 measures with their proofs; a test checks them; OWASP ASVS 5.0.0 Level 1 and 2, all 253 items; rows W85 to W101 and their order | added ADR-0170, CHG-056 to CHG-061; rests on CHG-051, CHG-055 |

This session checked #573 in production: the Deploy job of run 39020545269 concluded `success`
(two earlier runs for the same commit were cancelled), `/status` `build_sha` read
`1571295eccaa7551c57a498779799438ba5f829e`, and `/ready` returned 200. W82 changed documents and a
test only, so nothing new is visible in the running app.

## What the owner decided this session

- CHG-056: W74's attack suite is priced before any spend; W78 is to be built; W87 ends a signed-in
  session after 12 hours and an anonymous one after 24, and account deletion needs a Google sign-in
  within 10 minutes.
- CHG-057: the session switched on private vulnerability reporting in the 10 public repositories,
  secret scanning and push protection in `stackclimb-website`; validity checks could not be
  switched on through the API.
- CHG-058: the stop rule fired on the docs/41 check; the owner chose one more fix.
- CHG-059 and CHG-061: the order after W82 is W85, W86, W100, W87, W88, W80, W75, W76, then W28 in
  a fresh session, then the other security rows. W28's decision 3 is decided: signed-in only.
- CHG-062: the W28 work gets one source of truth, the earlier W28 documents are marked superseded
  or archived, the leftover W28 worktree is removed, and the next prompts miss nothing.
- CHG-060: the public documents hold back how to reproduce the live gaps W85, W87, W88 and W100
  until each fix ships. W82 was published as one fresh commit so earlier drafts stay unpublished;
  the full evidence is in `~/Projects/quorum-ai-evidence/2026-10-17/w82/`, outside the repository. Keep it
  until those four rows ship.

## Left for the owner

- **Start two sessions:** the security fixes (`CONTINUE-SECURITY-W85-W76-PROMPT.md`) and the W28
  research (`CONTINUE-BYOK-RESEARCH-W28-PROMPT.md`), both committed by this pull request. They use
  separate CHG and ADR numbers (the security session's next: CHG-063 and ADR-0171; the W28 session's:
  CHG-075 and ADR-0180).
- **GitHub, by hand:** validity checks, if a repository's Advanced Security page offers them; on the
  account's Code security page, automatically enabling private vulnerability reporting for new
  public repositories; adding a second email address to the GitHub account.
- **Accounts the session cannot read:** a credit limit on the app's and the judge's OpenRouter keys;
  whether `FLY_API_TOKEN` is limited to this app (`fly tokens list`); how long Fly keeps volume
  snapshots; 2-step login on Fly, Google Cloud, OpenRouter and Sentry; who Sentry alerts.
- **W28's decisions 1, 2, 4, 5 and 6, its four tensions, and whether four older owner statements
  still hold**: the W28 research session asks them, with examples.

## W28: what this session gathered

At the owner's request, the W28 prompt was rebuilt to miss nothing. Three read-only agents wrote
input reports, kept outside the repository in `~/Projects/quorum-ai-evidence/2026-10-17/w28-inputs/`:
every W28 trace in the repository, every trace on GitHub and in git history, and the checklist the
research must cover. A fourth file holds the 21 key-safety tests of 2026-10-13, taken from that
session's transcript. The session checked the four owner quotes that exist only in transcripts,
word for word. The local worktree and branch `w28/byok-pr1-plan`, clean and identical to GitHub,
were removed; the branch on GitHub stays until the W28 session archives its plan (CHG-047).

## How the work is organised

The owner asked whether one orchestrator with sub-orchestrators would beat separate chats. The
repository tried a sub-orchestrator per item in August (`docs/archive/2026-10/AUTONOMOUS-WORK-LOOP-ULTRACODE-PROMPT.md`);
`docs/analysis/2026-10-11-how-we-work-review.md` folded it into today's process (ADR-0159). Anthropic's
and Cognition's published experience points the same way: parallel readers, one writer at a time.
So: one chat per stream, a main orchestrator per chat, single-role helpers that write long output
to files and return short reports.

## Found late, for the next sessions

- Dependabot alerts, which the owner switched on (the session only read them, CHG-057), list 3 open
  medium alerts, all in test-only dependencies: `Werkzeug` and `pytest` in `uv.lock`, and
  `brace-expansion` in `e2e/package-lock.json`. The audit of the runtime packages `uv.lock` pins
  (`make vuln-audit`) found 0 in 31. Row W92 covers the dependency audit.
- The completeness critic's questions not yet on a row, at a high level: what an agent session can
  reach with the owner's signed-in `fly` and `gh` (W81 is only about `.env`); no item-by-item check
  of OWASP's lists for language-model applications and APIs; whether the vendors that answer
  questions keep them; reading GitHub's alert lists, not only its switches; the vendored JavaScript
  is outside every vulnerability check; old events already in Sentry.

## Traps learned

- **Escaped pipes.** A Markdown table cell can hold `\|`; split cells on unescaped pipes only. A
  generator here cut 12 ASVS cells short before review caught it.
- **Hand-written Markdown parsing.** Two review rounds each found the docs/41 check misreading
  Markdown both ways. Reading the tables `markdown-it-py` renders (a pinned dependency) closed
  that class; it still differs from GitHub in small ways, which ADR-0170 lists.
- **zsh does not split `$VAR` into words.** `git checkout br -- $FILES` handed git one long name;
  pipe the list through `xargs` instead.
- **A table-editing helper that renames a row's key** must record the key before the edit.
- **A public repository.** Pushing a branch publishes every commit on it. To publish a redacted
  version, build one fresh commit from `origin/main` and check its tree equals the reviewed one
  (`git diff <reviewed-branch>` prints nothing).
- **Corrections were less reliable than the first draft again.** Round 2 found two of round 1's own
  corrections false (SC-08, SC-86). Check each replacement sentence with a command before writing
  it.
- **Disk.** Free space fell to about 2.6 GB, mostly outside this work (uv's shared cache is about
  4.9 GB). `make docker-build` was left to CI.
