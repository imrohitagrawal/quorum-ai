# Session handoff — 2026-08-27 (transport track B, and the review-practice rules)

Three work packages, all merged and running in production on `8b2ffda`.
Written for the session that picks up **B2 (streaming)**, which is the only
thing from the transport plan still unbuilt.

## What shipped

| PR | What | ADR | Merge |
|---|---|---|---|
| #385 | Review-practice rules: 9a (never move the tree under a running reader), 10 re-graded, 13f (never read a gate's exit through a pipe) | 0076 | `cb4b6fd` |
| #386 | The response body decides the outcome, and a dispatched call that answered nothing leaves evidence | 0077 | `4d7320f` |
| #388 | A provider call gets a total time budget, because a per-`recv` timeout is not one | 0078 | `8b2ffda` |

`live_execution` is `false` throughout. No money constant moved. 10 authorised
paid calls spent, 10 succeeded, nothing wasted.

## Read these before touching the transport code

**The plan's premise for B1 was half wrong, and the correction is in ADR-0077.**
"Classify in-band SSE errors" was already satisfied by accident: an SSE body
fails `json.loads` and lands in the existing catch-all, so the obvious
bite-proof passes on `main` before the code exists. The only genuinely RED
assertion is the *clean*-stream one, and satisfying it means writing the parser.
**B2 must not re-litigate this** — build the parser, and the classification is
already there.

**The measurement that justifies B2** is in
`docs/analysis/2026-08-26-b3-timeout-probe.md`. The headline is a PAIRED sample,
same model, same endpoint:

| `openai/gpt-4o-mini` | max inter-chunk gap |
|---|---|
| non-streamed | 22.440 / 25.055 s |
| streamed | 0.478 / 0.208 s |

Two facts B2 depends on, both settled at $0 from OpenRouter's own docs:
`usage` arrives in a stream's **final chunk with no opt-in**, and keep-alive
comment frames (`: OPENROUTER PROCESSING`) exist. **Their cadence is NOT
settled** — counts of 1, 16, 16 and 21 per call with no regular spacing. Any
figure quoting a fixed interval is unsupported.

**Keep-alives will defeat the per-`recv` timeout.** Once streaming lands, the
8s stall detector can no longer bound a call, which is exactly why
`openrouter_call_budget_seconds` had to land first. Do not remove it.

## The three defects a reviewer found in my own code

Recorded because each is a pattern, not a one-off.

1. **A truncated `Content-Length` body was served as a complete, priced
   answer.** My bounded read treated `read1() == b""` as end-of-body;
   `response.read()` raises `IncompleteRead` there. Every test I wrote used
   `Transfer-Encoding: chunked`, so the suite was **structurally blind** to the
   other framing. When you replace a stdlib call, enumerate what it did for you
   that you are no longer doing.
2. **The budget did not cover the header phase.** `urlopen` returns only after
   the status line and headers are read. Starting the clock afterwards left that
   phase unbounded while the docstring called it a "TOTAL wall-clock budget".
3. **`5 × 60 = 300` is not above 300.** I claimed a margin that was equality.

## Numbers that were wrong in inherited documents

- The plan and the 2026-08-26 handoff say "8 of 8 exceed on wall clock". It is
  **7 of 8** — 6.385s does not. The per-`recv` figure (6 of 8) is correct and is
  the one that decides anything.
- The per-`recv` timeout's bite is a property of the **MODEL**, not of
  OpenRouter. `openai/gpt-5-mini` dribbles (max gap 0.643s over ~78 chunks); the
  four default answer models buffer (5.7-25.1s). A conclusion drawn from four
  models did not hold for the fifth.

## Traps that cost real time this session

1. **`pytest-timeout` is NOT installed.** Passing `--timeout` makes pytest error
   out, so a mutation run reports every mutant "killed" while testing nothing.
   My first pass reported 7 of 7 killed and was worthless; the rerun with a
   baseline found **three real survivors**. Always run an unmutated baseline
   first and use a subprocess timeout.
2. **An equivalent mutant can be equivalent only for the input you chose.** The
   non-bytes guard survived against `object()` (because `bytes(object())` raises
   anyway) and died against `5` (`bytes(5)` returns five zero bytes and the loop
   never ends).
3. **`TaskStop` kills the shell, not the `uv run` child.** A "stopped" suite
   kept running and corrupted the next one — two suites on one tree. Check
   `pgrep -f pytest` before re-running.
4. **GitHub Actions had a `major_outage`** (verified via
   `githubstatus.com/api/v2/components.json`, not guessed). Runs wedge in
   `queued` and cannot be cancelled or re-run. The resolution was to merge the
   next PR, whose fresh SHA got a working deploy carrying both changes.
5. **`quorum_run_deadline_seconds` is a published requirement**, not a knob:
   NFR-001, NFR-004, AC-021, the traceability matrix, the AC-to-test map and the
   operator dashboard. **No gate covers that prose.** Changing the code alone
   would have left the product's stated timeout false where an operator reads it.

## What is left

- **B2 — stream the provider call.** The only unbuilt item of the transport
  plan. ADR-0029's bar for adopting an SDK instead is two measured failed
  attempts at hand-rolled SSE; there are still zero. Record the attempts.
- **`DEBATE_HARD_TIMEOUT_MS` (180s) is now effectively unreachable** — with each
  call bounded at 60s, two debate rounds cannot reach 180s. Left alone
  deliberately; retiring it is its own concern.
- **The judge leg has never been probed** and is still assumed at ~5s in the
  critical path.
- **n=6 is a maximum, not a p95.** Every timeout value here rests on maxima.
- Open issues unchanged: 383, 382, 380, 379, 290, 268, 105. Issue 105 is now
  *collectable* — the durable billing file finally admits the transport and
  body-unreadable events — but is not settled; it needs production data.
- **12 advisory findings from the B3 review were dropped below the cap**, listed
  in PR #388's description rather than discarded. Notably: a budget expiry and a
  per-`recv` stall write byte-identical durable records, so the new bound cannot
  yet be tuned from production evidence.
