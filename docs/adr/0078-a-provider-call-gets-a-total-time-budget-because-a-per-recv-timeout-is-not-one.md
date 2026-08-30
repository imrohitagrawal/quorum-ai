# ADR-0078: A provider call gets a total time budget, because a per-`recv` timeout is not one

## Status

Accepted — 2026-08-26

## Context

The approved plan scheduled this as *"the two timeout constants — move together,
only after B2"*, and flagged it as a stop-and-ask: `quorum_run_deadline_seconds`
180 → 300 plus a new ~45s per-call budget are **guardrail values**, and the
~122s critical path behind them contained an *estimated* ~37s synthesis leg for
a model that had never been probed, from a sample of 2 reps.

That was the right call. Ten additional paid calls were authorised
(**$0 wasted — 10 of 10 succeeded**) and the measurement changed three things.

### 1. The synthesis leg, measured for the first time

`openai/gpt-5-mini`, non-streamed, `max_tokens=3000` — the cap synthesis
actually uses, and 1.5× anything the earlier spike probed. n=6:

| wall (s) | ttfb (s) | max inter-chunk gap (s) | chunks | finish | completion tokens |
|---|---|---|---|---|---|
| 25.072 | 1.050 | 0.572 | 64 | stop | 2427 |
| 28.260 | 0.950 | 0.601 | 73 | stop | 2894 |
| 29.027 | 1.153 | 0.643 | 74 | stop | 2653 |
| 30.778 | 1.748 | 0.631 | 78 | stop | 2819 |
| 30.947 | 0.909 | 0.624 | 79 | **length** | 3000 |
| 40.170 | 0.848 | 0.621 | 98 | stop | 2753 |

The plan's ~37s estimate was good — median 30.8s, max 40.2s.

### 2. The finding that matters more: the per-`recv` bite is a property of the MODEL

**0 of 6 exceeded the 8.0s `openrouter_timeout_seconds`. 6 of 6 exceeded it on
wall clock.** This model dribbles its answer across ~78 chunks, every gap an
order of magnitude under the cap, so a 40-second call is indistinguishable from
a healthy one to every bound the code had.

The earlier spike measured the four default *answer* models at inter-chunk gaps
of 5.7–25.1s — they buffer. Both behaviours are real, on the same endpoint,
through the same client. **"The 8s timeout is the binding constraint" is true of
some models and false of others**, and the plan generalised from four to the
whole pipeline.

*(A correction while re-deriving: the plan and
`docs/analysis/2026-08-26-session-handoff.md` both say "8 of 8 exceed it on wall
clock". Against their own table it is **7 of 8** — 6.385s does not. The
per-`recv` figure, 6 of 8, is correct, and that is the one that decides
anything.)*

### 3. So the real defect is that no bound existed at all

`urlopen(request, timeout=…)` sets a **socket** timeout, applied per-`recv`,
never cumulative. `_post_messages` then called `response.read()`. Nothing
bounded a call's total wall clock except `quorum_run_deadline_seconds` — a
whole-**run** safety net shared by every stage, which cannot distinguish one
slow call from five healthy ones.

Reproduced on loopback, a body dribbled 512 bytes per second through an 8.0s
socket timeout that never fired:

```
TODAY's unbounded read(): wall=12.042s for 6040 bytes,
per-recv timeout was 8.0s and NEVER fired
```

`config.py` justified the 180s deadline with *"the pipeline's own per-call HTTP
timeouts keep a healthy run far below this"*. That sentence was false, and had
been since it was written; nothing had checked it.

### 4. Streaming, measured on a paired sample

Not built here, but it is what the next package rests on, so it was measured
while the budget was open — same model, same endpoint:

| `openai/gpt-4o-mini` @3000 | max inter-chunk gap |
|---|---|
| non-streamed (2026-08-26 spike) | **22.440 / 25.055 s** |
| streamed (this probe) | **0.478 / 0.208 s** |

Across all four streamed calls the worst gap was **0.478s**, against 1,736–4,908
frames per call. Keep-alive comment frames are confirmed present (1, 16, 16 and
21 per call) — **with no fixed cadence**, so any figure quoting one is
unsupported. OpenRouter's streaming DOCUMENTATION says `usage` arrives in the
final chunk with **no opt-in** required, which was the open question that could
have made streaming break the cost ledger.

**Corrected 2026-08-30 by ADR-0084:** this paragraph said the documentation
"confirms" it and that it "does not" break the ledger. That is one notch
stronger than the evidence supports — the source is a vendor page, not a probe
row, and the probe script was not retained. Read it as **ASSUMED**. The
streaming package designs for the assumption being false (absent usage is
reported absent, never fabricated, so a receipt degrades to `estimated` rather
than reporting a wrong number) and instruments the answer instead of arguing
it.

## Decision

**Four levels, named, with one new enforcement mechanism.**

| Constant | From | To | Why |
|---|---|---|---|
| `openrouter_timeout_seconds` | 8.0 | **8.0, unchanged** | worst streamed gap 0.478s → ~17× margin; it is a stall detector and stays one |
| `openrouter_call_budget_seconds` | *(absent)* | **60.0** | 1.5× the longest call measured (40.170s) |
| `quorum_run_deadline_seconds` | 180.0 | **360.0** | measured critical path ~124.7s, and 5 x the call budget is 300 |
| `tavily_timeout_seconds` | 8.0 | **8.0, unchanged** | never measured; nothing here justifies moving it |

**The budget is enforced as a deadline across the whole body read**, in
`_read_body_within_budget`. A `TimeoutError` from it lands in `_post_messages`'
existing catch-all and is classified `_DISPATCH_UNMEASURED` — correct, because
tokens were generated and the call may well have been billed.

Three details, two inherited from the error path's `_read_within_budget` and one
new:

* the budget is a **deadline re-applied before every chunk**, not one lowered
  timeout — that sibling's docstring measures the single-timeout version taking
  **16.051s** against a 2s cap;
* `read1` returns after **one** `recv` instead of looping until it has the
  requested count, which is what stops a dribble overrunning inside a single
  call;
* the socket hop on a success response is **`response.fp.raw._sock`** — one
  level shallower than the `HTTPError` path's `exc.fp.fp.raw._sock`. Measured,
  not assumed: on CPython 3.12 the shallower path resolves to a `socket` while
  the deeper one raises `AttributeError`.

The per-chunk timeout is `min(per_recv, remaining)`, so the stall detector keeps
working *inside* the budget rather than being replaced by it.

**A validator refuses a budget at or below the per-`recv` timeout**, and refuses
NaN and infinity before any comparison — NaN compares False to every bound, so a
pure range check accepts it, and a NaN deadline makes `remaining <= 0` False
forever.

### The critical path, and an honest note about the deadline

Five sequential legs — 4 parallel initial answers, debate round 1, debate round
2, 5 parallel synthesis sections, judge:

```
26.5 + 26.5 + 26.5 + 40.2 + ~5  =  ~124.7s
```

The first three are measured (2 reps × 4 models, `max_tokens=2000`); the
synthesis leg is measured here for the first time; **the judge leg is still
ASSUMED at ~5s and has never been probed.**

**180 was not demonstrated to be too small.** 124.7 < 180. This is a margin
decision, not a fix: 2.9× where 180 bought 1.45×, on legs that are each a
max-of-N draw with small N. Two further limits, stated rather than buried:
**n=6 gives a maximum, never a p95**, and the parallel legs are the slowest of
4 and of 5 draws respectively, which is worse than the slowest of 6 reps of one
model.

**360 rather than 300, and a reviewer had to point out why.** The first draft
of this ADR said 300 and claimed it "keeps the deadline above
`5 × openrouter_call_budget_seconds`". 5 × 60 = **300**, which is not above
300 — it is exactly equal, zero margin — and each leg can overshoot its budget
by up to one already-started `recv` on top, so the true five-leg worst case is
nearer 340. At 300 the run-level net would have fired on a run that every
per-call bound considered healthy, which is the opposite of what a safety net
is for. 360 clears `5 × budget` by 60s.

**This number is NFR-001, NFR-004 and acceptance criterion AC-021.** It is not
an internal knob: it is published in `docs/11-non-functional-requirements.md`,
`docs/12-acceptance-criteria.md`, `docs/18-requirement-traceability-matrix.md`,
`docs/54-ac-to-test-map.md` and on the operator dashboard
(`templates/ops.html`, "hard timeout 360 s (NFR-001)"). All of them moved with
it. Changing the code alone would have left the product's stated hard timeout
false in the one place an operator reads it, and no gate would have noticed —
a reviewer found it, not CI.

### What the adversarial review changed

Four lenses over the committed diff, then two independent refuters per finding.
26 raised, 4 refuted, 12 dropped unverified below the cap (all `ADVISORY_DEBT`,
listed in the pull request rather than discarded), 10 survived. The three that
changed the shipped code:

**A `CRITICAL_BLOCKER`, and it was a silent one on the paid path.**
`_read_body_within_budget` treated `read1() == b""` as end-of-body.
`response.read()` — the call it replaced — runs `_safe_read` and raises
`IncompleteRead` when a `Content-Length` response ends early; `read1` returns
`b""` at EOF regardless. Re-measured at the keyboard against a loopback server
declaring 4220 bytes and sending 124, then closing gracefully:

```
HONEST Content-Length (control)   OLD read(): RETURNED 124, length=0    NEW: RETURNED 124, length=0
LYING Content-Length (truncated)  OLD read(): RAISED IncompleteRead     NEW: RETURNED 124, length=4096
```

The delivered prefix was valid JSON, so a truncated response would have been
served as a complete answer, priced, and reported `is_truncated=False`. **No
test in the change used `Content-Length` framing at all** — every server in the
new test file sets `Transfer-Encoding: chunked` — so the suite was structurally
blind to it. The guard now consults `HTTPResponse.length` and raises; five tests
cover it, including the honest-framing partner.

**The budget did not cover the header phase.** `urlopen` returns only once the
status line and header block are read, and that phase is bounded per-`recv`
exactly like the body was. Starting the clock after `urlopen` left it unbounded,
so `config.py`'s "TOTAL wall-clock budget for one provider call" was false as
written. The clock now starts before `urlopen`.

**`5 × 60 = 300` is not above 300.** See the deadline note above.

Two more survivors were closed with tests rather than code: dropping
`and not chunks` from the fallback guard let the reader switch from `read1` to
`read` *mid-body*, stitching a differently-framed read onto a partial one; and
`openrouter_timeout_seconds` — the other half of `min(per_recv, remaining)` —
had no validator, so 0 (which makes a socket **non-blocking**, not fast), NaN
and infinity were all accepted.

## Rejected alternatives

### A 40s or 45s per-call budget — REJECTED on the measurement

40 was the figure recalled in discussion and **is below an observed value**
(40.170s); it would have cut that call dead. 45 is the plan's figure and sits
12% above the maximum of a 6-sample draw, which is not a margin. 60 is 1.5×.

### Shipping the constant without enforcing it — REJECTED

A total budget that nothing applies is worse than none: it reads as a bound in
`config.py` and in `.env.example` while every call remains unbounded. If the
enforcement were deferred to the streaming package, the constant would have to
be deferred with it.

### Deferring the whole package until streaming exists — REJECTED

The plan's own sequencing said "only after B2", on the reasoning that the
per-call value only becomes a stall detector once streaming lands. The
measurement inverts it: **the unbounded-call defect is live today**, on a model
in the default panel, and keep-alives will make the per-`recv` timeout *less*
able to bound a call, not more. The budget is needed before streaming, not
after.

### Raising `tavily_timeout_seconds` — REJECTED as unmeasured

Named in the deadline validator's own warning and therefore tempting to move
"for consistency". Nothing here measured the search leg, so moving it would be
setting a guardrail from nothing — the exact failure this package was stopped
to avoid.

### Keeping the literal `== 180.0` pin in the deadline integration test — REJECTED

`test_a_normal_run_under_the_default_deadline_completes_fully` opened with
`assert settings.quorum_run_deadline_seconds == 180.0`. That guard has a real
job — proving the run is measured against the shipped default rather than a
value an earlier test monkeypatched — but a literal does that job *and* rots the
moment the default moves. It now compares against the **declared** default via
`model_fields`, which keeps the anti-leak check and cannot go stale (rules 1a
and 7a).

## Consequences

- A single provider call can no longer run unbounded. The budget clock starts
  **before** `urlopen`, so connect, request, headers and body share one
  allowance; the worst case is 60s plus at most one already-started `recv`.
  The first version started the clock *after* `urlopen` returned, which left
  the status-line and header phase bounded per-`recv` only — a reviewer
  measured that phase alone reaching several times the budget, and the
  docstring's "total wall-clock budget for one provider call" was false as
  written until the clock moved.
- **A slow-but-healthy call that previously completed at, say, 70s will now be
  cut and classified possibly-billed.** No measured call came close — the
  longest was 40.170s — but this is a real behaviour change on the paid path and
  it is the cost of the bound.
- `quorum_run_deadline_seconds` (360) stays above
  `5 × openrouter_call_budget_seconds` (300) by 60s, pinned by a test, so the
  run-level net cannot fire on a run every per-call bound considered healthy.
- **`DEBATE_HARD_TIMEOUT_MS` (180s) is now effectively unreachable** and is
  deliberately left alone. It gates debate round two on elapsed time since
  round one; with each call bounded at 60s, two rounds cannot reach 180s. It is
  a separate mechanism with its own tests, and retiring it is a different
  concern from bounding a call. Recorded here so the next reader does not
  mistake it for an oversight.
- **None of this can fire in production today.** `live_execution` is `false`, so
  no live body reaches this code. Like ADR-0075's stance branch and ADR-0077's
  `is_truncated`, it is latent-correct: covered by tests and seven killed
  mutants, and by nothing observable.
- The judge leg remains unprobed, and n=6 remains a maximum rather than a p95.
  Both are recorded above rather than smoothed over.

### Two process notes worth keeping

**A mutation run with a bad flag proves nothing.** The first pass of these seven
mutants reported all seven killed. It had passed `--timeout 120` to pytest, and
`pytest-timeout` is **not installed** here — so pytest errored on every mutant
and every "kill" was the flag, not the test. The rerun added an explicit
unmutated **baseline** (green, 18 passed) before any mutant, and used a
subprocess timeout where a hang counts as a failure. It found **three real
survivors**. This is the same family as rule 13b's note that `pytest-randomly`
is absent while `pyproject.toml` configures it.

**An equivalent mutant can be equivalent only for the input you chose.** The
non-bytes guard's mutant survived against an opaque `object()`, because control
fell through to `bytes(chunk)`, which raises anyway. `bytes(5)` does not raise —
it returns five zero bytes, and the loop asks for more forever. The test is now
parametrised over both, and the guard is what stops the loop rather than a
coincidence downstream of it.
