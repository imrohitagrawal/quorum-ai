# Session handoff — 2026-09-19 (#448, #458 code half, #447 piece 1, #467, #459)

Read `AGENTS.md` first, then this. Figures are NOT restated here: each item
points at the commit body or command that holds them (the last session's lesson).

## 0. Preconditions

```bash
cd /Users/rohitagrawal/Projects/quorum-ai
git status --porcelain            # expect only CONTINUE-105-BACKLOG-ULTRACODE-PROMPT.md (untracked, now stale; see §4)
git worktree list                 # expect only quorum-ai (main)
curl -s https://quorum.stackclimb.com/status | jq '{build_sha,live_execution,peer_critique_enabled}'
make handoff                      # the Production line now works (#467); it runs under uv
```

`live_execution` is false. Nothing this session opened, extended or
re-affirmed a window, or flipped a flag.

## 1. Merged and running in production

Each row: Deploy JOB read on every run for the merge SHA, and `/status.build_sha`
matched after it. Details, red output and mutation lists are in the commit bodies.

| issue | PR | merge | issue state |
|---|---|---|---|
| #448 audit call refuses a redirect | #475 | `ee3c96a` | closed (owner-approved) |
| #458 code half: landing subhead follows `peer_critique_enabled` | #476 | `7048d28` | open (flag half remains) |
| #447 piece 1: nested `url_citation` read; judge title can no longer forge an evidence line | #477 | `2521fa8` | open (pieces 2-3 remain) |
| #467 handoff `/status` probe works | #478 | `088a514` | closed (owner-approved) |
| #459 watchdog interval measured and stated in ONE place (option 1) | #479 | `cfe26d4` | open (option 2 remains; closing needs the owner's yes) |

Advisory leftovers for each are listed in its PR body. Read them there.

## 2. Next, in order (owner agreed 2026-09-19)

1. **#268: price debate output from measurement.** Do the repo sweep FIRST
   (every sentence stating `cost_debate_output_tokens` / 400, and the
   point-estimate dollar figures), then re-run the 715-mix band sweep under
   production posture, then propose a value for the owner's sign-off. The
   measurement source is `docs/analysis/2026-09-10-telemetry-tokens.jsonl`
   (stages `debate_round_1/2`). Do NOT retry the refuted fold of
   `prior_critique_input_cost` into `debate_prompt_tokens`; its recorded
   "9 of 495" is itself stale (715 mixes now, ladder moved).
   Why it matters: the per-call band prices debate at the 4000 cap and is
   safe; the daily cap and the per-account cumulative rail
   (`costs.py` `_cumulative_spend_for`) sum the point estimate, so they
   under-count debate spend.
2. **#458 flag half: couple the displayed shape to live execution.** The
   landing and `/status` should describe peer critique as effective only when
   `peer_critique_enabled` AND live execution are both on. With live off,
   every slot is simulated, so `debate.py` `_eligible_critics` is empty and
   `_build_peer_round` falls back to the moderator path, while the landing
   says "they critique each other". Code only; no flag is flipped.
3. **W23: make schemathesis cases selectable by the mutation gate.** The
   board's stated cause is FALSE: pytest selects an id with a space fine
   (a plain parametrized `[GET /status]` id collects). What fails is selecting
   a `SchemathesisFunction` item by its id (`... ::test_api_conforms_to_openapi_contract[GET /status]`
   collects nothing; the bare function name collects all 13). Deselecting the
   module is NOT acceptable: `tests/unit/test_mutation_test_set_integrity.py`
   forbids exempting tests that can kill a `src/` mutant. Correct the board
   row's cause in the same PR. Then #464.
4. **Watchdog auto-off (#459 option 2), before any live window.** Production
   refuses live execution once the declared window lapses, so detection
   latency stops mattering. Touches live-execution behaviour: owner approval
   and an ADR first.

## 3. Owner decisions still open

- #268's value (after the sweep).
- #459 option 2 (auto-off) design, and whether #459 closes on option 1 alone.
- `configs/live-execution-windows.json` still says the watchdog runs "every
  30 minutes"; left untouched because it is the window declaration file.

## 4. Traps measured this session

- **A figure copied into many files is many chances to be wrong.** #459 wrote a
  sample-bound interval into 8 files; the full history disagreed. Keep a
  measured number in ONE place with its window and command.
- **Sweep the numbers, not only the phrasings you expect.** A narrow regex
  missed 6 stale sentences; grepping the figures found all of them at once.
- **The mutation gate can die without measuring** on any diff reaching a
  schemathesis-covered handler (PR #476's run). Read its log before citing it.
- **`/ui` answers 429 from this machine** (per-IP daily mint cap), so the
  served landing page cannot be read from here; `/status` can.
- The root `CONTINUE-105-BACKLOG-ULTRACODE-PROMPT.md` is stale: its items 1-6
  are done. Use §2 above instead.
