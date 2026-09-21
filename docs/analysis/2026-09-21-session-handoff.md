# Session handoff — 2026-09-21 (#268 both halves, #458 flag half, W23)

Read `AGENTS.md` first, then this. Figures are NOT restated here: each item
points at the commit body, the ADR or the command that holds them.

## 0. Preconditions

```bash
cd /Users/rohitagrawal/Projects/quorum-ai
git status --porcelain     # expect only the two CONTINUE-*.md files (untracked)
git worktree list          # expect only quorum-ai (main)
curl -s https://quorum.stackclimb.com/status | jq '{build_sha,live_execution,peer_critique_enabled,peer_critique_in_effect}'
make handoff
```

`live_execution` is false. Nothing this session opened, extended or
re-affirmed a window, or flipped a flag. No paid call was made.

## 1. Merged and running in production

Every row: the Deploy JOB read on every run for the merge SHA (each merge
produced 2–3 runs, the extras cancelled by concurrency), and
`/status.build_sha` equal to the merge SHA at the time.

| item | PR | merge | issue state |
|---|---|---|---|
| #268 judge half: the displayed estimate prices a typical judge call | #481 | `b1209b5` | open |
| #268 debate half: the debate stage priced from measurement, 400 → 2200 | #482 | `18396df` | open (the web-search half remains) |
| #458 flag half: the copy follows whether peer critique is IN EFFECT | #483 | `aa072b9` | open (the flag flip and the coupling remain) |
| W23: a lazily expanded case is selectable by its node id | #484 | `597e02b` | — (#464 remains) |

Owner decisions taken in session: the debate value 2200 (2026-09-20) and the
merges of #481 and #482 (2026-09-21). CHG-008 and CHG-009 record them.
ADR-0114, ADR-0115, ADR-0116, ADR-0117 carry the measurements.

`/status` gained `peer_critique_in_effect`. Production now reports
`peer_critique_enabled: true` with `peer_critique_in_effect: false`, which is
the state #458 existed to make visible.

## 2. Next, in order

1. **#464 — the mutation gate's verdict inverts under truncation.** W23 made
   the gate able to RUN; #464 is that a truncated run still exits 0, so it can
   still report a pass having measured a fraction of its scope. The issue's own
   cheapest-first list stands. Read `docs/adr/0117-*` first: it records what
   W23 did and did not change, and the measured numbers for a gate that scores
   nothing versus one that scores honestly.
2. **#268's remaining half** — `cost_web_search_context_tokens`. ADR-0027 calls
   it "the half of #268 that remains open". Measurements exist in the issue's
   comments (n=32 across four question shapes, 27 over the shipped 2000); the
   value has never moved. Same shape of work as ADR-0115: sweep first, propose,
   owner signs off.
3. **#459 option 2** (production refuses live execution once the declared
   window lapses). Needs the owner's approval and an ADR before building.
4. **#458's own remaining half** — flipping `PEER_CRITIQUE_ENABLED` and
   coupling it to the live window. Both are product-owner decisions;
   `scripts/close_live_window.py` still does not touch the peer flag.

## 3. Owner decisions still open

- Whether #268 closes on its debate half alone, or waits for the search-context
  half.
- #459 option 2's design, and whether #459 closes on option 1 alone.
- The `PEER_CRITIQUE_ENABLED` flip and the flag coupling (#458).
- `configs/live-execution-windows.json` still says the watchdog runs "every
  30 minutes"; untouched, because it is the window declaration file.

## 4. Traps measured this session

- **A design that matches a measured TOTAL better may be cancelling two
  errors.** Decoupling the synthesis critique-input term scored $0.1240 against
  $0.1235 measured, versus $0.1285 for the simpler design — but only because
  leaving that term low cancelled a different under-pricing. ADR-0115's
  rejected alternative has the per-term numbers. Compare each term, not the
  total.
- **A module global in a pytest plugin is a false-pass machine.** `mutmut`
  calls `pytest.main` in-process and then forks; state set by the parent leaks
  into every child, whose runs then die and are dropped from the denominator.
  Measured: 100.0% and exit 0 where the honest answer was 68.4% and exit 2.
  ADR-0117 has all three runs.
- **A single-mutant proof cannot see a multi-mutant defect.** The RED/GREEN run
  that proved W23's fix used a diff with one mutant — the one shape where the
  parent's test-id set equals the child's. The defect above lived exactly
  outside it.
- **A test whose probe lives in `tmp_path` may never exercise the thing under
  test.** Two such tests passed against any implementation this session: one
  outside `tests/` (so the conftest plugin never ran), one asserting a
  collected-summary line while a real run behaved differently. Assert on what
  executes.
- **`repo_introspection` on a FUNCTION is invisible to the guard that forbids
  silent exemptions** — it reads module-level markers only. A per-function
  marker exempted a whole module from the mutation oracle without appearing in
  the pinned list.
- **The open-work board's anchor goes stale at 60 commits** and its header
  states the unpinned-row count; both are checked by
  `scripts/check_open_work.py --check`, which `make validate` runs.
- **An ADR amendment note placed ABOVE the `## Status` value makes the posture
  checker read that ADR as not live** (`test_only_the_three_genuinely_revoked_adrs…`
  goes red). Put it below.
- **`make quality` is RED on this machine for two reasons that are not your
  diff**, both the same shape as rule 13a:
  - `test_no_orphaned_e2e_specs` — 7 failures from `e2e/tests/review/`, which
    is gitignored local scratch that the test enumerates with `rglob`. Run
    `ls e2e/tests/review/` before blaming a diff.
  - `test_code_text_strips_js_comments` — the sweep excludes `node_modules`,
    `.venv`, `build`, `playwright-report` and `test-results`, but NOT
    `.uv-cache`, which the repo's own Makefile puts inside the checkout
    (`UV_CACHE_DIR`). MEASURED 2026-09-21: 12 minified offenders, ALL under
    `.uv-cache` — so any session that runs a make target and then pytest sees
    this red. CI never does, because its cache lives outside the tree. The fix
    is one more entry in that exclusion list, with a comment; it is NOT done
    here because it is a different concern from this handoff (rule 17).
- `/ui` still answers 429 from this machine, so the served landing page cannot
  be read from here; `/status` can, and now carries both peer fields.
- Both root `CONTINUE-*.md` prompts are stale for items 1–3. Use §2 above.
