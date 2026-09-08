# CONTINUE — file the judge-source issue, ship the harvester, then measure a live run

**Written 2026-09-07T16:55Z by the session that shipped ADR-0101 and ADR-0102.**
Executable procedure. Read `AGENTS.md` FIRST — it overrides everything here.

**THIS IS THE CURRENT PROMPT.** It supersedes
`CONTINUE-JUDGE-SOURCES-AND-WINDOW-ULTRACODE-PROMPT.md`, whose Item 1 is
REFUTED-then-RESOLVED (ADR-0101, ADR-0102) and whose Items 2 and 3 are the work
below. That file is moved to `docs/archive/2026-09/` in the same commit that
adds this one; if you find it still at the repo root ALSO claiming to be the
current prompt, the archiving did not happen — compare
`git log --diff-filter=A -1 --format=%ci` on each and trust the newer.

---

## RULE ZERO: THIS DOCUMENT IS A CLAIM, NOT A FACT

This repo has MEASURED that roughly half of what a handoff asserts does not
survive contact with the tree. The session that wrote this file had **a
correctness defect and a user-visible falsehood** found in work it had already
reported green, and it wrote **two false claims into an ADR about false
claims** before review caught them.

**Re-verify every numbered claim before acting on it.** Each names the command
that settles it. If a premise turns out false, AGENTS.md rule 3 applies — STOP
and say so; do not repair it silently.

---

## FIRST MOVE — run these before anything else

```bash
cd /Users/rohitagrawal/Projects/quorum-ai
git fetch -q origin && git rev-list --left-right --count main...origin/main   # expect 0 0
curl -s https://quorum-ai.fly.dev/status | python3 -m json.tool
uv run python scripts/live_posture_check.py > /tmp/p.log 2>&1; echo "EXIT=$?"; cat /tmp/p.log
gh issue list --state open --limit 50
ls docs/adr/ | tail -3            # 0102 is TAKEN; next free is 0103
ls e2e/tests/review/ 2>/dev/null  # non-empty => make quality is RED locally, not your diff
```

Expected: `main` 0/0 at `0b6b0b4` or later; `build_sha` == main's tip;
`live_execution`, `judge_enabled`, `peer_critique_enabled` all `true`.

**IF THE WATCHDOG EXITS 1, RESOLVE IT BEFORE ANYTHING ELSE.** It means
production is in a money-spending posture nobody is attending. Read the
`decision=` it printed and branch on it:
- `live_reaffirmation_lapsed` — declared, but nobody confirmed in 24h. ASK the
  owner, then post the re-affirmation in the form under "WHAT NEEDS THE HUMAN".
  Re-run the watchdog and require EXIT=0 before continuing.
- `live_past_declared_window` — the declaration expired. This needs a NEW
  window, which is the owner's decision. ASK; do not declare one.
- `live_undeclared` — nobody declared it at all. STOP and escalate: production
  is spending with no cover.
The watchdog also auto-files an issue (it filed #445 on 2026-09-07). Close it
with evidence once the condition is genuinely resolved.

---

## THE HARD DEADLINE — read this before planning anything

The declared live-execution window **expires `2026-09-08T07:51:25Z`**. It was
~14.9h away when this was written. Compute the real number before you plan:

```bash
python3 -c "
from datetime import datetime,timezone
exp=datetime.fromisoformat('2026-09-08T07:51:25+00:00')
print(f'{(exp-datetime.now(timezone.utc)).total_seconds()/3600:.1f}h left')"
```

**If the window has expired, the live run needs a NEW declaration, which is a
human decision — ASK, do not declare one yourself.**

**Items 2 and 3 cost no money, but Item 3 IS ON THE DEADLINE'S CRITICAL PATH.**
The run cannot happen until 3 is built, reviewed (this repo budgets TWO
adversarial rounds plus one for your own fix), gated under rule 14, merged AND
deployed — because a run against a build without the annotation capture cannot
produce measurement 3. Budget backwards from the expiry, and if it does not
fit, ASK for a longer window before starting rather than after.

---

## WHAT NEEDS THE HUMAN, EVERY TIME

1. **Re-affirm the window every 24h.** Comment on issue **#290**, token
   STARTING the line, quoting the window's own `opened_at` (NOT today's date):
   ```
   REAFFIRM live-execution 2026-09-03T07:51:25+00:00
   ```
   `gh` here is `imrohitagrawal`, type `User` (workflow `Bot` tokens are
   refused — confirm with `gh api user --jq .type`). The owner has authorised
   posting on their behalf **when ASKED**. Ask; there is no standing licence.
   Last posted 2026-09-07T16:53:52Z. (The scheduled watchdog run FAILED at
   15:09:35Z that day and went green only after that comment.)
2. **Any paid production run.** The 17b override covers push/PR/merge/deploy;
   it does NOT cover money. The owner gave consent for ONE run on 2026-09-07;
   confirm it still stands before spending.
3. **Closing the window** on 2026-09-08: `make close-window` makes BOTH edits
   atomically. The obvious one-edit revert is REFUSED — #407 was a window that
   outlived its expiry by ~8.6h because that two-part edit was skipped. (The
   ~8.6h is INHERITED from `CONTINUE-OPEN-WORK-ULTRACODE-PROMPT.md`, not
   re-measured; the checkable part is that `make close-window` runs
   `scripts/close_live_window.py` and makes BOTH edits.)

---

## STATE AT HANDOFF — what shipped, verified

Two PRs merged, deployed, and verified three ways (deploy JOB `success`, not
the rollup; `build_sha` match; watchdog EXIT=0):

- **PR #443 → `84358ed`, ADR-0101.** The "seven of eight `finish_reason:
  length`" figure was NEVER a critique measurement: it came from `a2_probe.py`
  on 2026-08-26, four ANSWER models on a prompt written to fill the cap, eight
  days before peer critique existed (`5aed777`). ADR-0093's own *Measured*
  table (`0093:43,45`) is where the word "critique" came from — it labels that
  probe a "2000-token critique" twice. Not a transcription slip; inherited
  framing.
- **PR #444 → `0b6b0b4`, ADR-0102.** The first real critique run (2026-09-06,
  $0.0806) clipped **3 of 4** round-2 replies at 2000. Shipped:
  `DEBATE_ROUND_MAX_TOKENS` 2000→**4000**, the threshold ladder
  0.15/0.20/0.25→**0.30/0.40/0.50**, and `quorum_run_deadline_seconds`
  360→**720** (a PUBLISHED REQUIREMENT — NFR-001, NFR-004, AC-021, the
  traceability matrix and the operator dashboard all moved with it).

**`DEBATE_HARD_TIMEOUT_MS` is deliberately STILL 180_000.** That is the round-1
gate, and whether it now fires is the single most important thing the live run
must settle.

---

## THE ORDER — do not reorder without saying why

**There is deliberately no ITEM 1.** The numbering is inherited from the
superseded prompt, where Item 1 was the clipped-critique defect — refuted by
ADR-0101 and then resolved by ADR-0102. Items 2 and 3 keep their old numbers so
that the issue trail and the earlier prompt still line up. The steps below are
lettered to avoid colliding with them.

A. **Item 2 — file the judge-source issue.** Free. It is tracked NOWHERE, which
   is why it has slipped three sessions running, including the one that wrote
   this file.
B. **Item 3 — the $0 harvest harness, PLUS the annotation capture.** Free to
   run, but ON the deadline's critical path — see above.
C. **Merge and deploy 2 and 3.** Verify `build_sha` before going further.
D. **One live run** (~$0.10). NEEDS THE OWNER'S GO and a sanctioned window.
E. **Harvest and report.**

**THE WINDOW'S THREE MEASUREMENTS** — referred to throughout, and declared in
`configs/live-execution-windows.json` (the `reason` field of the current
window; the same file `make close-window` edits):
1. what eight critique calls actually cost — W3/ADR-0094 is blocked on it;
2. whether `DEBATE_ROUND_MAX_TOKENS` still fits, read off `finish_reason`;
3. whether OpenRouter's `:online` annotations carry passage CONTENT, which
   decides whether judge source-checking is possible without new fetches.
Measurements 1 and 2 were settled by the 2026-09-06 run. **3 was lost**, and
Item 3a below is what stops it being lost twice.

**Step 3 before step 4 is load-bearing, and this repo has already paid for
getting it wrong once.** On 2026-09-06 a paid run settled two of the window's
three measurements and **lost the third**, because nothing in the product
captures it. Do not repeat that.

---

## ITEM 2 — THE JUDGE CANNOT READ ITS SOURCES (file it)

**Verify first:**
```bash
sed -n '1725,1735p' src/product_app/evaluation.py     # the evidence block
grep -n "JUDGE_MAX_SOURCE_LINES\|JUDGE_MAX_SOURCE_TITLE_LEN" src/product_app/evaluation.py
grep -rn "class SourceReference" -A 6 src/product_app/providers.py
```

`build_judge_evidence` (`evaluation.py:1674` — PUBLIC, no leading underscore;
grepping `_build_judge_evidence` finds nothing) formats each source as
`f"[{i}] {title} :: {url}"` —
titles and URLs, no page content — and **nothing in `src/` resolves a cited
URL**. The outbound HTTP call sites are `providers` (OpenRouter),
`catalog_fetcher`, `readiness` and `feedback_audit`; `credentialed_url` is the
guarded opener `providers` binds, not an independent caller. So the judge is
asked whether an answer asserts only what its evidence supports, about evidence
it has never seen. **ADR-0099** (commit `0e91052`) shipped the UI copy that now says sources
*"aren't checked against their pages"* — NOT ADR-0098, which this prompt first
credited. ADR-0098 records the gap at `0098:230-232` but is about the
`is_fallback` presentation. The gap itself is untouched.

**File an issue containing at least:**

- The gap above, with the three commands that prove it.
- **Two routes, and the one unmeasured signal that decides between them.**
  Route A: use the `:online` annotation content, if it exists — no new fetches.
  Route B: a credential-guarded fetcher resolving cited URLs;
  `src/product_app/credentialed_url.py` already exists and already refuses
  redirects, so Route B's groundwork is partly built.
- **A second unknown the same measurement settles for free.** ADR-0084 records,
  and did not fix, that `_extract_citations` reads a **flat**
  `annotation["url"]` (`providers.py:3462`) while OpenRouter documents a
  **nested** `url_citation` object — *"if that documentation is right the
  annotations path has been dead all along and the inline-markdown fallback is
  what produces sources today."*
- **The coupling that must not be missed.** Judge input is bounded today at
  **32 source lines x 300 chars** (`JUDGE_MAX_SOURCE_LINES`,
  `JUDGE_MAX_SOURCE_TITLE_LEN`, `JUDGE_MAX_SOURCE_URL_LEN`,
  `evaluation.py:1655-1657`), and **#268 records that nothing bounds a call's
  INPUT**. Passage content is orders of magnitude larger than a title, so
  source access must ship **with** an input bound or it widens exactly the
  exposure #268 is open about.

Link it to #290 and #268. **Do not close either.**

Filing an issue is outward-facing, so ASK before you post it — AGENTS.md rule
17b covers push/PR/merge/deploy and says nothing about issues, and this
document's "WHAT NEEDS THE HUMAN" list does not cover it either. Show the body
first. Then:
```bash
gh issue create --title "<title>" --body-file <file>   # add --label if the repo has a fitting one
```

---

## ITEM 3 — THE HARVESTER, AND THE CAPTURE THAT MAKES IT WORTH RUNNING

### 3a. The annotation capture — THE BLOCKING PART

**Verify the gap:**
```bash
python3 - <<'PY'
import re, pathlib
s = pathlib.Path("src/product_app/telemetry_sink.py").read_text()
blk = s[s.index("TELEMETRY_FIELD_NAMES"):s.index("#: Every value the ``stage`` field may hold")]
f = re.findall(r'^\s{8}"([a-z_]+)",', blk, re.M)
print(len(f), "fields; annotation-related:", [x for x in f if "annot" in x or "citat" in x])
PY
```
Expected: **27 fields, none annotation-related.** Combined with
`SourceReference` keeping only title/url/provider/is_fallback,
`_extract_citations` DISCARDS any content field at parse time. So window
measurement 3 — *do `:online` annotations carry passage CONTENT?* — is
**unobservable end to end**, and a paid run loses it again.

**Ship a BOUNDED capture** — a label and a count, never content, exactly as
every other field in that stream is bounded:
- `annotation_shape`: a CLOSED set, like `_finish_reason_label` produces —
  never the upstream's raw string. Decide and WRITE DOWN the rule before you
  code it; the suggested one, which matches what `_extract_citations` already
  looks for:
  - `absent` — `message.annotations` (or `message.citations`) missing or empty;
  - `flat` — the first annotation dict has a top-level `url` or `source` key
    (what `providers.py:3462` reads today);
  - `nested` — it has a `url_citation` key whose value is a dict (what
    OpenRouter documents, and what ADR-0084 suspects is really sent);
  - `other` — neither. **Include this fourth value.** Without it an unexpected
    shape is silently filed as one of the three and the answer looks clean.
- `annotation_count`: how many annotations arrived.
- `annotation_content_chars`: total length of the `content` field where one
  exists — check `url_citation.content` first, then a top-level `content`.
  **A LENGTH, NOT THE TEXT.** Absent if no content key is present anywhere;
  `0` means "the key was there and empty", which is a DIFFERENT answer from
  absent and is exactly the distinction Route A turns on.

**Where to compute it.** `_extract_citations` discards everything but
title/url, so reading a `SourceReference` is too late. Compute the trio in
`providers.py` where the parsed payload is still whole — next to
`_extract_usage` / `_finish_reason_label` in `_post_openrouter` — and thread it
into `_log_call_token_shape` the way `finish_reason` already is.

That trio answers Route A vs Route B *and* ADR-0084's dead-path question from
one run, at zero marginal cost. Add the names to `TELEMETRY_FIELD_NAMES`, or
`tests/unit/test_telemetry_sink.py:322` fails — it checks that list in BOTH
directions. (The first version of this prompt said an omitted field is "dropped
silently"; the test is what stops that, which is the point of having it. What
IS dropped silently is a field whose name collides with a `JsonFormatter`
reserved key — see the field list's own docstring.)

### 3b. The harvester

A new script under `scripts/` — `<window-measurement-report>.py` is the
suggested name; it is written deliberately WITHOUT a resolvable path here,
because `tests/unit/test_cited_paths_resolve.py` refuses a docs line citing a
repo path that does not exist, and this one does not exist until you create it
—
modelled on `scripts/telemetry_classification_report.py`, which is the repo's
precedent for this shape. Copy its STRUCTURE (argument handling, the
`TOKENS_FILE_NAME` constant, the `$TELEMETRY_LOG_DIR` default) but NOT its
empty-input posture — measured, it exits 0 over zero rows, which is the very
thing the last bullet forbids. It must:

- read `telemetry-tokens.jsonl` from a DIRECTORY given as the first argument,
  defaulting to `$TELEMETRY_LOG_DIR` (production writes `/data`, per
  `fly.toml`) — the same interface as the precedent script, which is why the
  harvest command below passes a directory and not a file;
- **SCOPE EVERY READING TO ONE `query_run_id`, and say which.** `/data` is a
  persistent volume that ALREADY holds the 2026-09-06 run described above —
  the one that clipped 3 of 4 at cap 2000. A report that pools all rows would
  mix a cap-2000 run with a cap-4000 run and answer measurement 2 wrongly, in
  the pessimistic direction. Group by `query_run_id`, report per run, and make
  the newest run's verdict the headline;
- report **measurement 1** (what the 8 critique calls cost, in TOKENS — do not
  invent a dollar figure that would compete with the receipt's own `by_stage`);
- report **measurement 2** (`finish_reason` on `debate_round_2` rows, plus the
  completion-token distribution against `max_tokens`);
- report **judge** token counts (`stage == "judge"`);
- report **measurement 3** from the new fields;
- **REFUSE ON EMPTY INPUT.** Every reading here is a negative check, and a
  negative check over zero rows is trivially true. The measured scale of this
  in THIS repo: **13 of 21 CI jobs could reach a terminal status having
  measured nothing, four of them blocking** (AGENTS.md). Exit non-zero and say NO DATA rather than
  printing a clean number over nothing.

A working prototype existed in this session's scratchpad and was proven to
refuse empty input (EXIT=1); the scratchpad has been cleared, so rebuild it.
**Validate against SIMULATED runs, which cost nothing** — but note a fully
simulated run makes no provider calls and therefore writes NO token rows, so
drive `_log_call_token_shape` through a stubbed provider rather than expecting
a sim run to populate the file.

### 3c. Gate it

`finish_reason`, `stage` and `slot_number` are already in the stream. The new
fields need the same both-directions test. Prove the capture bites by mutation:
`cp` the file aside, break it, watch red, restore from the copy, `diff -q`.
**Never `git checkout <file>`** — it discards uncommitted work.

---

## ITEM 4 — THE LIVE RUN

**Preconditions, all four:**
1. Items 2 and 3 merged AND deployed — verify `build_sha` matches the merge SHA,
   or the run's telemetry will not carry the new fields.
2. Watchdog EXIT=0 and the window not expired.
3. The owner's go for the money, re-confirmed.
4. **A free session mint slot.** Production caps NEW sessions at **2 per IP per
   24h** (`auth.py:83`, `SESSION_MINT_CAP_PER_IP = 2`). There is **no
   allowlist**, and `SESSION_MINT_CAP_OVERRIDE` is LOCAL-only —
   `validate_production_environment()` REFUSES TO START if it is set anywhere
   else. On 2026-09-07 this IP was capped; the `/ui` page said a slot frees in
   ~2 hours. An ALREADY-OPEN session still works.

   **DO NOT PROBE `GET /v1/session` TO CHECK.** It IS the mint endpoint: with
   no cookie it MINTS, so a probe that succeeds has SPENT one of the two slots
   to learn there was one, and a probe that fails tells you only what opening
   the UI would have. Check by opening the UI in the browser you will run in.

**Run it through the browser so a human can watch**, and use a query you
compose rather than a UI preset. The one prepared for this run, chosen because
it is genuinely contestable and will produce long, citation-heavy round-2
replies — which is exactly what clipped at 2000 and must fit in 4000:

> What are the main trade-offs between PostgreSQL and SQLite for a small
> production web application, and when does that choice actually start to matter?

**What the run must answer:**

| Question | What proves it |
|---|---|
| Does round 1 still fit inside `DEBATE_HARD_TIMEOUT_MS` (180s)? | 4 `debate_round_2` rows AND a synthesis present. If the gate fires, `missing_steps` carries `debate_round_2` AND `synthesis` (`debate.py:1088`) |
| Is 4000 actually ENOUGH? | `finish_reason` on round-2 rows is `stop`, not `length`. The earlier run put a FLOOR under the requirement (>= 2000) and no ceiling |
| Do `:online` annotations carry content? | the new `annotation_*` fields |

**Harvest, free:**
```bash
mkdir -p /tmp/harvest
fly ssh console -a quorum-ai -C "cat /data/telemetry-tokens.jsonl" \
  > /tmp/harvest/telemetry-tokens.jsonl
python3 scripts/window_measurement_report.py /tmp/harvest --run <query_run_id>
```
`--run` IS REQUIRED. `/data` holds more than one correlated run, and the report
refuses to choose: with several runs and none named it prints them all, picks no
headline, and EXITS 1. That refusal exists because picking by recency was
measured printing the exact opposite of the paid run's result in both money
directions — one concurrent query on the live `/ui` lands in the same file. Take
the id from the run you just watched, or from the timestamp window the report
prints for each run.

The filename matters: the script takes a DIRECTORY and reads
`<dir>/telemetry-tokens.jsonl` inside it, exactly as
`telemetry_classification_report.py` does. Redirecting to `tokens.jsonl` and
passing `.` would silently read a file that is not there — and a harvester that
refuses empty input (as ITEM 3b requires) would then correctly report NO DATA
about a run that really happened.

**IF THE ROUND-1 GATE FIRES**, the owner's stated preference (2026-09-07) is to
raise `DEBATE_HARD_TIMEOUT_MS` 180s → 360s. That now FITS, because the run
deadline moved to 720s — at the old 360s deadline a 6-minute gate would have
equalled the entire run budget. Treat it as its own package with its own ADR,
and re-measure rather than assume it is enough.

---

## FACTS THIS SESSION PAID FOR — do not re-derive

- **Measure at production's REAL posture: judge ON *and* peer critique ON.**
  `fly.toml:84` sets `PEER_CRITIQUE_ENABLED = "true"`. A sweep at the config
  default (peer OFF) reproduces ADR-0081's published `0.1043`/`0.1134` exactly
  and is WRONG — that is how this session shipped a false sentence into `src/`.
  ADR-0081's table is peer-OFF and now carries a supersession note.
- **Name the query with every bound figure.** The bound moves with query
  length; ADR-0102's table is at `"Compare transparent model answers"`
  (33 chars), default slots `search=True`. A figure without its query is not
  reproducible, and review caught a table and a sweep taken under different
  conditions.
- **Dispatch is SEQUENTIAL** (`_build_peer_round`'s own docstring, `debate.py`).
  A peer round is bounded by FOUR call budgets, not one. `config.py`'s
  five-legs-one-call-each arithmetic no longer describes the worst case.
- **A cut stream is `possibly_billed`**, with the usage discarded, and it
  demotes the receipt from `measured` to `estimated`. The honest phrasing for a
  timeout is "may pay and return nothing" — NOT "fail-safe".
- **The point estimate is cap-independent** (0.0548 at cap 2000 and 4000). Only
  the BOUND moves with the cap. If a fixture bounds the point estimate, a cap
  change is no reason to loosen it.
- **`0.1043` is stale in the tree** and is PROSE in every occurrence, asserted
  nowhere. Re-derive the count rather than trusting one —
  `grep -rl "0\\.1043" --exclude-dir=.git . | wc -l` returned 27 before THIS
  file existed and returns one more once it is committed, so a count printed in
  a document that is itself counted is self-defeating. Precedent (PR #378, and ADR-0102) is to correct the canonical
  statement only. Two of the 27 are dated HISTORY (`CHANGELOG.md`,
  `docs/18-…`) and must NOT be "fixed".
- **The mutation gate can abort with no score.** Two distinct aborts, and the
  first version of this prompt stated a THIRD cause that is false — worth
  keeping as a warning:
  - `BadTestExecutionCommandsException`: a schemathesis-parametrised test id
    collects zero tests inside `./mutants/`, pytest exits 4 (usage error), and
    mutmut raises before scoring a single mutant. Recorded at
    `docs/65-open-work.md:331` and `docs/analysis/2026-09-01-overnight-run.md:81`.
    It is SCOPE-DEPENDENT: PR #413 scored 38 survivors the same night, because
    its scope was `providers.py`, which no schemathesis case covers.
  - "failed to collect stats": the suite cannot run inside `./mutants/` at all.
    `docs/metrics/mutation-gate-study.md:28-35` documents one of these. The
    Makefile names its two causes: a check resolving the repo root from
    `__file__`/`parents[n]`, or a root file missing from
    `[tool.mutmut].also_copy`.
  - **NOT the coverage floor.** This prompt first blamed `--cov-fail-under=88`.
    That is refuted by `pyproject.toml:245,253`, which passes `--no-cov` to
    mutmut's pytest for exactly that reason, in its own words: *"the global
    --cov-fail-under=88 would fail every per-mutant partial run, scoring every
    mutant 'killed' and making the number meaningless."* Do not go change a
    setting that is already handled.

---

## TRAPS THAT COST THIS SESSION DIRECTLY

- **Never read a gate's exit status through a pipe OR after another command.**
  `make X 2>&1 | tail` reports *tail's* status; `make X; echo "EXIT=$?"` after
  another command reports *that* command's. Write it as:
  ```bash
  make <target> > /tmp/gate.log 2>&1; echo "EXIT=$?"; tail -30 /tmp/gate.log
  ```
- **`ruff format --check` passing says NOTHING about `ruff check`.** A 101-char
  comment line passes the first and fails the second (E501). Hit this session.
- **A blanket find-and-replace corrupts HISTORY.** Rewriting
  `Decimal("0.20")` → `0.40` broke a `git log -S 'DAILY_CAP_USD =
  Decimal("0.20")'` command inside a docstring, whose whole purpose was to find
  the commit that set the OLD value.
- **Do not edit the tree while a gate or a read-only reviewer is running.**
  Done once this session; the `diff-cover` result had to be discarded.
- **Memory pressure kills long jobs.** Several `make quality` runs were killed
  after stacking background watcher loops. Run gates one at a time; chunk the
  suite (`tests/*.py`, `tests/unit`, then the rest) if they keep dying.
- **`git worktree remove` leaves the directory** if it is not empty (a stray
  `.DS_Store` is enough). Check and `rm -rf` the named path after.
- **Run e2e exactly as CI does**, or ~95 phantom failures appear:
  ```bash
  lsof -ti tcp:18085 | xargs -r kill -9
  mv .data/feedback_events.sqlite3 /tmp/fb-bak.sqlite3 2>/dev/null || true  # DESTRUCTIVE as rm
  cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 SESSION_MINT_CAP_OVERRIDE=600 \
    npx playwright test <spec> --project=chromium --workers=1 --retries=0
  ```

---

## THE REVIEW LESSON, measured 2026-09-06/07

Two adversarial rounds on the ladder change found, in work already locally
green with every gate passing:

- **a live correctness defect** — `_estimate_reasons`, a SECOND reasons
  producer on `POST /v1/query-runs/estimate`, publishing the OLD limits, so one
  response body carried two contradictory sets of numbers. `grep` for it in
  `tests/` returned nothing AT THE TIME — the fix shipped with its regression
  test, so the same grep hits today. That is the fix working, not this section
  being stale;
- **three rendered UI strings** still naming the old cap, including a
  screen-reader announcement that compared the POINT estimate against the cap
  and could say *"Estimated $0.1984 is above the $0.25 hard cap"*;
- **two test ceilings loosened without cause**, proven by reverting them and
  watching the suite still pass;
- **five prose claims that did not reproduce**, including two "no combination
  exists" assertions refuted by counterexample sweeps. (The counts quoted in
  ADR-0102's history — 51 and 55 — are INHERITED here, not re-derived; if you
  need them, re-run the sweep rather than citing this line.)

**So: fan out review, and tell every reviewer IN CAPITALS not to write, edit,
`git checkout`, `git stash` or `sed -i` anything, and to make its own
`git archive HEAD | tar -x -C <dir>` copy if it must mutate.** Also tell it, in
these words: *"for every number, superlative and causal claim in the diff's
comments, commit body and PR description, name the command that produces it —
or mark it UNVERIFIED."* AGENTS.md rule 11a calls that instruction the
highest-yield mitigation available, on the grounds that no tool anywhere flags
an unverified claim in prose — and it costs nothing.

**And expect your own fix to introduce a defect.** This session's round-2 fix
introduced a `ReferenceError` (caught by `node --check`) and a vacuous
assertion (caught by mypy). Budget a round for it.

---

## CLOSE-OUT, in this order, every time

1. Local gates green (rule 14) and every review finding resolved.
2. `make close-guard` BEFORE the merge — CI never sees the merge text, and four
   issues have been closed by accident this way:
   ```bash
   PR=<n> EXPECT_CLOSE="<issues to close, or empty>" \
     MERGE_SUBJECT="..." MERGE_BODY="$(cat body.md)" make close-guard
   ```
3. Verify the deploy. A bare `gh run list --commit <SHA>` is dominated by the
   other workflows, so FILTER, then read the newest by `createdAt` and open its
   Deploy **JOB** — not the run's rollup:
   ```bash
   gh run list --commit <SHA> --workflow "Deploy to Fly.io" \
     --json databaseId,conclusion,createdAt
   ```
   A merge yields ~3 DEPLOY runs and 2 are `cancelled` by concurrency dedupe.
   Then check `/status.build_sha` == the merge SHA, and that the thing you
   built actually fires.
4. `git merge --ff-only origin/main` from the main checkout (`git branch -f`
   FAILS when `main` is checked out), remove the worktree FIRST, then delete
   the branch local and remote.
5. Delete your own residue by name — scratch files, `/tmp` logs, worktrees.
   **Never `git clean -fdx`.** Keep reusable caches (`.venv`, `node_modules`).
