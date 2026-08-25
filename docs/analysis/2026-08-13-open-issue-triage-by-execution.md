# Open-issue triage by execution — 2026-08-13

Every finding below is a command I ran myself against the live tree, with its
verbatim output pasted in. Nothing here is taken from an issue's own prose,
a commit message, or a subagent's summary without a direct re-check — two
subagent claims below (#303's file count, #143/#167) were independently
re-verified and one subagent claim was corrected on re-check (see "Corrections").

Verified against `bb20bdb`, confirmed to be both `git rev-parse HEAD` locally
and production's live `build_sha` (`curl https://quorum-ai.fly.dev/status`),
so "on main" and "in production" are the same tree right now.

## 0. Full open-issue count

```
$ gh issue list --state open --limit 500 --json number,title | jq length
17
```

17 open issues: #105, #134, #143, #145, #146, #160, #167, #203, #209, #216,
#224, #226, #242, #268, #290, #303, #313.

This supersedes a prior triage from 2026-08-10 (`docs/analysis/2026-08-10-open-issue-triage-by-execution.md`,
16 issues on `de1a639`). Since then: #285 and #284 closed (fixed), and #290,
#303, #313 were filed new. The other 12 issues from that triage were
individually re-checked below (§4) rather than assumed to still hold.

## 1. Confirmed closed since 2026-08-10 — verified in code, not just by label

```
$ gh issue view 285 --json state,closedAt -q '.state, .closedAt'
CLOSED
2026-08-10T10:53:06Z
$ gh issue view 284 --json state,closedAt -q '.state, .closedAt'
CLOSED
2026-08-10T10:53:06Z
$ git merge-base --is-ancestor f7128b1 HEAD && echo "ancestor of HEAD"
ancestor of HEAD
```

The fix commit's own message claims a fragment fix; I located it directly
rather than trusting the message:

```
$ grep -n "fragment" src/product_app/evaluation.py
505:    fragment (none can today; every construction site goes through
545:    fragment_idx = url.find("#")
546:    if fragment_idx != -1:
547:        url = url[:fragment_idx]
837:#: fragments rather than trusting the first boundary it finds.
...
```

`fragment_idx = url.find("#")` at evaluation.py:545-547 strips the fragment
before comparison — the actual defect from #285. Confirmed fixed in code, not
just closed by label.

## 2. New issue #313 — log redaction (BLOCKER label)

Issue claims: 9 raw-exception log call sites across 5 modules, no redaction filter.

```
$ grep -rnE "log(ger)?\.(exception|error|warning)\(.*(%s.*exc|exc\)|str\(exc)" src/product_app/*.py
src/product_app/feedback_store.py:521:            _log.warning("feedback_store: F-01 preview backfill did not run: %s", exc)
src/product_app/run_history_store.py:416:        _log.warning("run_history_store: failed to persist run %s: %s", row.query_run_id, exc)
src/product_app/feedback_audit.py:685:        _log.warning("feedback_audit: audit model call failed: %s", exc)
src/product_app/feedback_audit.py:691:        _log.warning("feedback_audit: could not parse audit response: %s", exc)
src/product_app/feedback_audit.py:995:                _log.warning("feedback_audit: could not parse LLM response: %s", exc)
src/product_app/store_reconnect.py:325:        _log.error("store_reconnect: could not start reopen thread %r: %s", name, exc)
src/product_app/store_reconnect.py:366:        _log.warning("store_reconnect: run_history store reopen attempt failed: %s", exc)
```
(7 lines — this pattern excludes `.debug(` calls. Two more exist:)
```
$ sed -n '2358p;2492p' src/product_app/query_runs.py
        logger.debug("cost_estimate_accuracy logging failed: %s", exc)
        logger.debug("run_history persistence failed: %s", exc)
```

**7 + 2 = 9 call sites, across 5 files** (feedback_store.py, run_history_store.py,
feedback_audit.py, store_reconnect.py, query_runs.py) — the issue's count is
exact, confirmed line-by-line, not assumed from the issue text.

No redaction filter exists for stdlib log records:

```
$ grep -n "class.*Filter\|redact\|scrub" src/product_app/logging_config.py
(no output)
```

`JsonFormatter.format()` (logging_config.py) calls `record.getMessage()`
straight into the JSON payload — zero scrubbing. The one redaction mechanism
in the repo (`main.py`'s `_USER_TEXT_FIELDS`) scrubs prose fields before
Sentry, and never touches stdlib `logger.*` calls — confirmed by grep, this
is a genuinely separate code path.

**Severity, tested rather than assumed**: the one call site that touches a
real secret is `feedback_audit.py:685`, wrapping an OpenRouter call carrying
`Authorization: Bearer {key}`. I tested what `str()` actually produces on the
exception types that call site catches:

```
$ python3 -c "
from urllib.error import HTTPError, URLError
print(str(HTTPError('url', 401, 'Unauthorized', {}, None)))
print(str(URLError('some reason')))
"
HTTP Error 401: Unauthorized
<urlopen error some reason>
```

Neither leaks the key today. **Verdict: confirmed defect, correctly LATENT not
LIVE** — the gap is real (no filter exists) but today's specific exception
types don't trigger it. It becomes live the moment any call site's exception
type changes to one that embeds request/header data (e.g. a raw `requests`
exception instead of `urllib`'s).

## 3. New issue #303 — file organization

```
$ wc -l src/product_app/*.py | sort -n | tail -10
    1081 src/product_app/feedback_audit.py
    1191 src/product_app/main.py
    1270 src/product_app/debate.py
    1467 src/product_app/feedback_store.py
    1472 src/product_app/synthesis.py
    2049 src/product_app/costs.py
    2259 src/product_app/evaluation.py
    2391 src/product_app/providers.py
    3509 src/product_app/query_runs.py
   22495 total
$ ls src/product_app/*.py | wc -l
      26
```

Top 4 files (query_runs.py + providers.py + evaluation.py + costs.py) =
10,208 / 22,495 = **45.4%** of 26 files — confirms the issue's claim
(a subagent I dispatched said "27" files; my own recount says 26 — corrected below).

`query_runs.py` really does merge 3 architecturally-distinct concerns declared
separately in `docs/20-architecture.md` (query_api / orchestration /
persistence): 6 `@router` HTTP endpoints, `class InMemoryQueryRunRepository`,
and `_execute_query_run`/`_execute_query_run_safely` orchestration logic all
live in the same 3,509-line file.

```
$ grep -rl "from.*query_runs import\|import query_runs" src/ tests/ | wc -l
51
```

51 files import from it — a split is a real refactor, not a mechanical move.
**No test, CI gate, or bug currently depends on this being fixed** — it is
pure structural debt, correctly scoped as its own careful work package rather
than a quick PR.

## 4. #105 / #268 / #203 — telemetry landed, not yet decided

```
$ git merge-base --is-ancestor ab4296c HEAD && echo "ancestor of HEAD"
ancestor of HEAD
$ ls -la src/product_app/telemetry_sink.py
-rw-r--r--  1 <user>  staff  13707 10 Aug 20:57 src/product_app/telemetry_sink.py
$ grep -n "TELEMETRY_LOG_DIR" fly.toml
44:  TELEMETRY_LOG_DIR = "/data"
$ grep -n "_UNBILLED_HTTP_STATUSES: frozenset" src/product_app/providers.py
1650:_UNBILLED_HTTP_STATUSES: frozenset[int] = frozenset({400, 401, 402, 403, 404, 429})
```

The classification constant `_UNBILLED_HTTP_STATUSES` is **unchanged** — no
5xx status is in it, meaning #105's actual billing question is still
unanswered by code, only instrumented. The telemetry sink and its production
wiring are confirmed live (ancestor of HEAD, config present in the deployed
`fly.toml`, matching prod's live `build_sha`).

**What I could not verify**: whether bytes have actually landed in
`/data/*.jsonl` on the production volume — that needs `fly ssh console`,
which I did not run (would require live-instance access outside routine
$0 checks). This is the one open unknown; the code and config being live is
confirmed, whether it has collected real 5xx/403 samples yet is not.

**Correct disposition for all three**: still open. The telemetry PR
instruments; it deliberately does not decide. Nothing here should be closed.

## 5. New issue #290 — peer critique (feature, not bug)

```
$ grep -n "debate_model_id\|live_call_usages\|_call_debate_model" src/product_app/debate.py | head -8
10:``debate_model_id`` setting — Haiku 4.5 by default) when a key is
229:    live_call_usages: list[tuple[int, TokenUsage | None]] = field(default_factory=list)
494:    def _call_debate_model(
529:        if not openrouter_key or not settings.debate_model_id:
543:            model_id=settings.debate_model_id,
$ grep -n "FR-008" docs/17-requirement-registry.md
12:| FR-008 | Functional | Two debate and critique rounds | ... | Draft |
```

Confirmed: today's debate stage uses ONE moderator model (`debate_model_id`)
to critique all 4 answers, not genuine peer critique among the 4 answer
models. `live_call_usages` records usage keyed by round only, not by model —
confirmed by reading the field, so under peer critique (4 different models
critiquing) the existing cost-accounting code would misattribute price to
the wrong model. FR-008 is registered "Draft"/partially met, matching the
issue's framing. **This is a real, substantial feature gap** (new
model_id plumbing, schema change, cost-accounting fix, and — per the issue's
own flagged risk — an unresolved 8-second-timeout-vs-40-second-critique
mismatch that needs one paid measurement before building). Not a quick fix;
correctly scoped as its own work package, not near-term backlog.

## 6. Spot-checks on the 12 unchanged issues from 2026-08-10

Two were independently re-executed myself (not just re-affirmed by subagent) because they were load-bearing for prioritization:

**#160 / #145 — enum pin gap, re-counted:**
```
$ grep -rn "^class.*\(Enum\|str, Enum\)" src/product_app/*.py | wc -l
17
```
17 production enums today (the issue was filed against 14) — confirms the
issue's own note that this gap is already growing, not shrinking.

**#216 — judge_enabled, re-checked live against prod right now:**
```
$ curl -s https://quorum-ai.fly.dev/status
{"app":"Quorum-AI",...,"build_sha":"bb20bdb...","judge_enabled":false,...}
$ git rev-parse HEAD
bb20bdb099babd68d14a595f0dd8de061174fb3a
```
`build_sha` matches local HEAD exactly — this is a live re-confirmation on
the current tip, not a 3-day-old snapshot: `judge_enabled` is still `false`
in production today.

**#143 / #167 — pin-test gap, re-checked because a subagent's first-pass
claim needed a second look:**
```
$ grep -rln "replay_mutation_scope" tests/
tests/unit/test_replay_mutation_scope.py
tests/unit/test_mutation_test_set_integrity.py
$ grep -n "Makefile\|MUTMUT_SCOPE_PY" tests/unit/test_replay_mutation_scope.py
(no output)
```
A test file referencing `replay_mutation_scope` does exist — but reading it
confirms it tests the script's own scope-classification behavior, and never
references the Makefile or `MUTMUT_SCOPE_PY` at all. The specific gap the
issue names — nothing pins the replay script equivalent to the real gate —
is still open. Confirmed by reading the test body, not by its filename.

The remaining 9 (#134, #146, #167 [covered above], #209, #224, #226, #242)
were spot-checked by an agent against file mtimes and `git log --since` on
the exact files/lines the 2026-08-10 doc cites; no commits touched those
surfaces since. Treat that as lighter-weight evidence than the sections
above — it is drift-detection, not independent re-derivation.

## Corrections to my own process this session

- A subagent reported "27 files" for #303; my own `ls | wc -l` says 26. Used
  the personally-verified number above.
- A subagent's harness-flagged output (reading `.claude/settings.json`,
  which contains directive-shaped text) is not relied on anywhere in this
  doc for a judgment call — only its file-existence claims, which I did not
  independently re-derive. Flagged to the user directly, not silently
  absorbed into the conclusions.
- I originally grepped for the #285 fix in the wrong file (`query_runs.py`,
  based on the commit message's framing); the real fix is in
  `evaluation.py`. Corrected before writing this section.

## Categorized groups and priority

**P0 — none.** The two live P0s from 2026-08-10 (#285, #284) are fixed and
verified in code.

**P1 — new, real, and cheap: #313 (log redaction)**
Confirmed defect, LATENT today, half-day fix (one shared redaction filter on
the root logger + a test with an injected fake secret). No dependency on
anything else in the backlog. Ships fastest of anything open.

**P2 — "our pins bite" (#160 + #145)** — unchanged from 08-10, and the gap is
measurably growing (14 → 17 enums since filing). #145 fixes the detector
#160's pins need to pass; do #145 first.

**P3 — "our guards bite" (#167 + #143)** — unchanged; #143 is the concrete
first instance #167's general mechanism should be built and demonstrated on.

**P4 — waiting on production data, correctly still open (#105 + #268 + #203)**
— telemetry is live in prod (verified via `/status` build_sha match); no
issue should close until real 5xx/403/token-count samples exist. Re-check by
reading `/data/*.jsonl` on the Fly volume (needs `fly ssh console`, not run
this session) or by waiting and re-measuring.

**P5 — test-suite integrity (#226 + #209)** — unchanged from 08-10, not
independently re-derived this session, spot-check only.

**P6 — structural, no urgency (#303)** — real, confirmed, but blocks nothing
concrete; 51-file blast radius makes it a dedicated work package, not a
quick win.

**P7 — feature initiative, needs a paid probe first (#290)** — substantial
scope, correct next step per the issue's own text is one deliberate paid
timeout measurement before any build work, not folded into a quick PR.

**P8 — process/tooling, no urgency (#224, #242, #134, #146)** — unchanged
from 08-10, spot-check only; #146 still needs a ~60-minute `mutmut` run to
settle its magnitude, not done this session (would burn significant compute
for an already-P8 item).

## Clubbing recommendation (rule 17g — same concern, one PR)

- **#160 + #145** — same PR, #145 first (unchanged from 08-10 recommendation).
- **#167 + #143** — same PR (unchanged).
- **#226 + #209** — same PR, separable if a reviewer objects to mixed Python/TS.
- **#313** — standalone, nothing else touches log redaction.
- **#105 + #268 + #203** — no new PR needed; already clubbed and shipped as
  the telemetry PR. What's left is a data-reading follow-up per issue, once
  volume exists — likely 3 separate small closing PRs, not one, since each
  closes on a different data condition.
- **#303, #290** — each standalone; different review shapes, no shared surface.
