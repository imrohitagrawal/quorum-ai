# Session handoff — 2026-10-03 to 2026-10-04

This session built W42 and W33 (the owner's bugs 1, 2, 3, 4, 6, 8a, 9, 10 and W43)
the way W34 was built. What merged is in `git log origin/main`; each pull request
body carries its evidence. This page says only what `git log` does not.

## Merged

- **#531, W42**: the in-memory cost ring is cleared between tests. CI's mutation job
  on #533 then passed its clean-test step for the first time on a session-code change
  and stopped at its own deadline (113 of 437 mutants reached), so it still reports no
  score on a change that size.
- **#532, W33 slice A (ADR-0140)**: the page journey — the session list kept, an empty
  next-question box, a way to a new question from every view, the models hint and step
  marker, no red box on load.
- **#533, W33 slice C (ADR-0141)**: a blocked run names the limit it hit, and estimates
  show the allowance left.
- **#534, W33 slice D (ADR-0142)**: the History panel asks the server each time it opens;
  the first signed-in browser lane (14 tests executed in CI). Its advisory mutation job
  stopped at stats collection: inside mutmut's copy, `test_cited_paths_resolve` cannot
  find the `e2e/servers/` files the branch cites, because `[tool.mutmut] also_copy`
  does not copy them. Any later branch that cites those paths will hit the same.

## How each slice was built

Failure modes and an ADR first; a test-designer agent wrote the acceptance tests red; a
builder agent made them green and edited no test (`git diff --stat` over the test paths,
checked after every builder commit); two review rounds (break-it, Codex, a product
reviewer driving the real server in Chromium, a prose and owner-attribution audit), and
where round 2 found something, one bounded fix with its own red test and a narrow check.
In slices A and D, round 1's fix added a defect that round 2 found (the cost
confirmation describing the edited question; the idle reminder hiding a toast); in
slice C, round 2 found an ADR that did not record a decision the build had made.

## Waiting on the owner

- **Signed-in people can spend less than signed-out ones**: after signing out, the next
  anonymous session starts with a fresh $0.40 (ADR-0141; the product reviewer called it
  "very visible").
- **Calls the session made that the owner may overturn** (ADR-0140): "homepage" means
  the composer; "Follow up on this" and "Start fresh" are hidden until W37 sends
  context; the landing buttons keep their names; the hint's button names and its
  approval clause are the session's wording.
- CHG-026 (m) in `docs/19` still words the hint's button names as the owner's decision.

## Next

- **W37** (follow-up context) brings back the hidden follow-up buttons; until then the
  owner sees no "Follow up on this" (an ADR-0140 call).
- **W36** (open a History row, keep 20 for 30 days, continue the conversation).
- **W45** (two tabs: `GET /v1/session` rotates the CSRF token) and **W46** (the
  signed-in top bar overflows between 601 and 837 px; toasts are not capped), both
  measured during review and older than this session.
- **W44** (mutmut's local "segfault" label) — and do not run mutmut on this Mac until the
  runaway `gcloud` chain is explained: it filled the user's process table twice on
  2026-10-03 during local mutmut runs (link unproven; nothing in the repo calls
  `gcloud`; `~/.zshrc` only adds it to PATH and loads completion).

## Traps this session paid for

- **The scratchpad is wiped by a restart.** Notes kept only there were lost; keep
  anything needed across a restart in a worktree or under `~/Projects`.
- **Test designers write throwaway reference implementations** to prove their tests can
  pass; move them out of the scratchpad before the builder starts, or the separation
  is only nominal.
- **Two worktrees share port 18085** for the main e2e lanes; tell every agent to check
  `lsof` and never kill a process it did not start.
- **Merging main into a branch while a reviewer is copying it** moved the tree under a
  reader (AGENTS.md rule 9a); the reviewer reported which commit it tested.
- **CI's `pytest` job took 15 min 37 s** of its 20-minute limit on #533.
- **Production serves no `/openapi.json`** (API docs are off); check new response fields
  another way.
