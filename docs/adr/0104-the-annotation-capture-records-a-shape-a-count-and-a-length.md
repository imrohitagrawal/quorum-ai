# ADR-0104: The annotation capture records a shape, a count and a length

## Status

Accepted — 2026-09-07.

Implements the remedy ADR-0103 bought time for. Provides the measurement that
will answer ADR-0084's open dead-path question; does not answer it. Does not
close issue #447 — the judge still cannot read its sources.

## Context

Issue #447: `build_judge_evidence` (`evaluation.py:1674`) hands the judge
`[i] title :: url` and nothing in `src/` resolves one of those urls, so the
judge is asked whether an answer asserts only what its evidence supports, about
evidence it has never seen. Closing that has two routes:

- **Route A** — read the passage content OpenRouter's `:online` annotations
  *may* carry. No new outbound fetches.
- **Route B** — a credential-guarded fetcher resolving cited urls.

Route A is possible only if the annotations carry content. **Nobody knows
whether they do**, and the product could not find out: `_extract_citations`
keeps title and url, `SourceReference` has no field that could hold content, and
0 of the 27 names in `TELEMETRY_FIELD_NAMES` described an annotation. The paid
run of 2026-09-06 was declared partly to settle this and lost it for exactly
that reason.

ADR-0084 records a second open question the same signal answers: we read a
**flat** `annotation["url"]` while OpenRouter documents a **nested**
`url_citation` object — *"if that documentation is right the annotations path
has been dead all along and the inline-markdown fallback is what produces
sources today."*

## Decision

Capture **labels from closed sets, counts, and a length** in the
`provider_call_tokens` stream. Seven fields. The first three were the whole of
the original design; the other four exist because adversarial review
**demonstrated** the first three cannot be read on their own.

| Field | Answers | Without it |
|---|---|---|
| `annotation_shape` | where the url sits (`absent`/`flat`/`nested`/`other`) | — |
| `annotation_count` | how many DISTINCT annotations arrived | a cumulative re-send multiplies the measurement |
| `annotation_content_chars` | how many characters of passage text | — |
| `annotation_sites` | WHERE an annotations key was on the wire | `absent` cannot be attributed |
| `annotation_arrivals` | the raw element count | the de-duplication is invisible |
| `annotation_content_shape` | what TYPE the content value was | `0` means four different things |
| `annotation_usable_count` | how many sources the reader actually yields | "does the reader work?" is inferred, wrongly |

### 1. The measurement reads a RECONSTRUCTION, so it must say so

The first version computed the shape from `parsed` and reported it as the
provider's response. It is not. Every call streams (`providers.py` sets
`"stream": True`; the only other path is a whole body that parses as one
completion), so `parsed` is built by `_reassemble_streamed_completion`, which

- concatenates each frame's annotation list **without de-duplicating**, and
- collects from `choices[0].delta` **only**.

Two defects followed, both reproduced by execution:

- a provider re-sending its array on each delta was reported as
  **count=8, chars=76** against a truth of **2 sources / 19 characters**. The
  multiplier is the content-frame count, which varies with answer length, so
  the inflation is not even constant between calls;
- annotations at `choice`, `message` or frame level produced a payload
  identical to one where nothing arrived — and the harvester printed *"the
  provider returned no annotations at all. Route A is not available on this
  evidence."* **A verdict about an upstream, drawn from our own reader.** That
  is AGENTS.md rule 8c in its purest form.

The fix is a probe inside the fold, recording **where** an annotations key
appeared (`delta`/`message`/`choice`/`frame`) and how many elements arrived,
plus de-duplication for the count. `absent` with `sites=none` is now a statement
about the provider; `absent` with any other site is a statement about our fold,
and the harvester says which.

**The probe is observation only.** It reads keys it never acts on and changes
nothing the fold collects. A test pins that a raising probe cannot alter what
the call returns — see §5.

### 2. `annotation_content_chars` is ABSENT, never defaulted to `0`

Absent means the upstream sends no content field at all. `0` means the field is
there. Rejected: a `0` default, which would collapse the two and answer "Route
B" — build the fetcher — to a question it never asked.

But `0` alone was found to be ambiguous four ways: an empty string, a JSON
`null`, a mapping, **and a list of content parts holding 360 real characters**.
So `annotation_content_shape` reports the value's type, and `content_chars`
counts the string parts inside a list. A list-of-parts reported as a bare `0`
would have sent the project to build a fetcher it does not need.

### 3. `flat` is STRUCTURAL, and the reader is measured instead

The first version's table said `flat` meant *"our reader WORKS; ADR-0084
refuted"*. Refuted by counterexample: the label tests key presence, while
`_extract_citations` also runs `_sanitize_source_url` and iterates every
mapping. **A `flat` label with zero extracted citations is committed as a test** —
including `{"source": "web", "url_citation": {...}}`, a plausible real shape.

`annotation_usable_count` now MEASURES it, by calling the product's own reader
with `content=""` so the inline-markdown fallback is excluded. That is ADR-0084's
question as a number, and it cannot drift from the reader it is measuring.

### 4. A LENGTH, never the passage

Passage content is unbounded upstream text, and nobody here has weighed a real
`:online` response. Writing it to the sink would
be the exact unbounded-input exposure #268 is open about, persisted to disk, and
would break the sink's rule: shapes and enumerations, never content (ADR-0031).

**Note what enforces this and what does not.** `TELEMETRY_FIELD_NAMES` is
referenced nowhere in `src/` except its own definition — it is documentation
enforced by a test, not a write-time allowlist, and an undeclared field reaches
the file. The leak test is the primary defence, and its first version was blind
to the leak shape its own docstring claimed to cover: it filtered the record to
scalars before searching, so a `list` carrying the passage passed green. It now
serialises the whole record with `default=repr`.

### 5. Instrumentation must never move money

`_annotation_shape(parsed)` is evaluated as an argument expression **inside**
`contextlib.suppress(Exception)`. The property was real but UNPINNED: the
existing telemetry-failure test patches `_log_call_token_shape` only, so
hoisting the call to a local above the `with` left 58 tests green while making
the exception escape `_post_messages` entirely. There is now a test that
patches `_annotation_shape` to raise and asserts the call still returns its
usage.

The helper is nonetheless **total over every JSON-shaped input**, as
`_finish_reason_label` is. It must not NEED the suppression: instrumentation
that can raise is instrumentation that can be silently dropped from the very run
it was built for.

### 6. The reader ships separately

The reader that turns these fields into a verdict is NOT in this change; it
lands with ADR-0105, under `scripts/`. Two reasons, and the second is the load-bearing one:

- A reviewer cannot audit a telemetry capture and a decision-support report in
  one diff; they answer different questions and fail in different directions.
- **The asymmetry of cost.** The capture writes to a durable volume. If the
  READER is wrong, the fix is free — edit the script and re-read the same file.
  If the CAPTURE is wrong, the measurement is gone and it costs another paid
  run. Only this half has to be right before the money is spent, and that is
  why it goes first and alone.

Its decisions and its own review history are recorded in ADR-0105.

## Consequences

- One paid run answers three things instead of two, plus ADR-0084's dead-path
  question, at zero marginal cost.
- `TELEMETRY_FIELD_NAMES` grows 27 → 34. The declared→formatter direction of
  the both-directions test covers all seven; the emitted→declared direction and
  the field-count floor cover six, because the driver's payload has no
  annotations so `annotation_content_chars` is legitimately absent. The seventh
  is covered by `test_the_wire_carries_every_annotation_field`.
- That floor read `>= 11` while the truth on clean `HEAD` was **12**:
  `finish_reason` was added after 11 was measured and nothing compared the two.
  Re-pinned at the branch's measured **18**.
- Nothing decides on these fields. No constant moves, no classification moves,
  no answer text changes.
- **The `nested` shape is designed against documentation nobody here has
  observed.** No fixture in this repo holds a real OpenRouter `:online`
  annotation, and no free probe reaches an annotated completion. That is the
  point of shipping the measurement, and it is why `other` and `sites` exist —
  so a shape we did not anticipate is reported as unanticipated rather than
  filed under a guess.
- **A third route exists and is not considered here.** `_tavily_search` is an
  already-built credentialed egress whose `_parse_tavily_results` discards down
  to title+url, exactly as `_extract_citations` does. Whether Tavily's results
  carry passage text is unmeasured. Flagged for whoever closes #447.
- If measurement 3 comes back `nested` with `usable_count == 0`, the annotations
  path has never produced a source and `_extract_citations` needs a fix of its
  own — a defect this capture would have found, not caused.

## What review round 2 found, in the fix itself

AGENTS.md rule 12: *"Expect your own fix to introduce a defect — budget a round
for it."* It did, twice, and both failed toward the same wrong conclusion.

- **The site probe fired on key PRESENCE.** A provider sending
  `"annotations": []` or `"annotations": null` — the field present and empty —
  recorded a site, so the payload was `absent` WITH a site, and the harvest
  printed *"a defect in our reassembler, not an answer about the provider."*
  That sends a reader to debug the fold on the one question the paid run is
  bought to answer. A site now means "something was there".
- **`_whole_body_annotation_sites` checked one of the four sites.** On the
  not-a-stream path, a body carrying top-level `citations` or choice-level
  annotations reported `sites=none`, and the harvest printed *"On this evidence
  the provider sent none"* — the exact rule-8c sentence §1 claims to delete,
  reintroduced on the one path the fix did not cover. And nothing named the
  helper: gutting it left the proof at 34/34.
- **`annotation_usable_count` was not de-duplicated** while `annotation_count`
  was, so a cumulative re-send printed *"yielded 8 source(s) from 2
  annotation(s)"* — the multiplication `annotation_count` exists to kill,
  surviving one field over.

Three further gaps, each now gated: `ANNOTATION_SITES` had no closure test
while `ANNOTATION_SHAPES` did; a content label missing from
`_ANNOTATION_CONTENT_RANK` would raise inside the paid path's suppression and
silently delete the ENTIRE `provider_call_tokens` record, not just the
annotation fields; and `MAX_UNPARSABLE_SHARE` could be loosened 0.05 → 0.99
invisibly.

Dead code removed: `_StreamedCompletion.annotation_arrivals` and
`_whole_body_annotation_arrivals` were computed on every call and read by
nothing — the logged value comes from `AnnotationShape.arrivals`.

**The money path itself survived.** 20,425 adversarial inputs through the fold:
zero raises, and the folded payload, terminator, frame count and body error are
byte-identical to before the probe. No passage text, url or title reaches disk.

## Costs, measured rather than asserted

`provider_call_tokens` records grow **523 → 732 bytes**, so the active 4 MiB
token file holds **8019 → 5729 rows (−28.6%)**. That is **#268's** evidence,
not #105's: the billing stream is a separate file (1 MiB × 4) behind its own
allowlist on a logger with `propagate=False`, so it is unaffected. The harvester
reads only the active file, so a run straddling a rotation is reported from its
tail — 28.6% sooner now.

`_annotation_shape` costs 0.030 ms on a realistic payload and 125 ms on an
adversarial 20,000-annotation one; linear, not quadratic, against an 8 s call
budget. It transiently holds ~2× the annotation block's size in de-duplication
keys.

## What rounds 3 and 4 found in the CAPTURE

Both rounds' blockers were in the reader, not here — recorded in ADR-0105. Two
findings landed on this half:

- **`_whole_body_annotation_sites` selected `choices[0]` positionally** while
  the streaming probe selects by `index == 0`, and its docstring claimed the
  sites were "checked exactly as the streaming probe checks it". Not reachable
  while nothing sends `n`, but a measurement that selects differently from the
  reader it describes is measuring something else. It uses the shared
  `_index_zero_choice` now.
- **`_annotation_usable_count`'s guards were uncovered** while its docstring
  claimed totality — a raise there would silently delete the ENTIRE token
  record, `prompt_tokens` and all, not just the annotation fields.

Round 4 also found that **two of seven mutants it wrote survived**, both in
judgement VALUES rather than control flow. Three classes this harness
structurally cannot catch, stated so nobody reads a kill rate as adequacy:

1. **A constant set to a wrong-but-plausible value.** Only control flow is
   mutated here.
2. **Omission** — absent code cannot be mutated, so no kill rate measures a
   reading that was never written.
3. **Prose and interfaces no test types.** The docstrings and this ADR are
   outside the harness entirely.

## Numbers corrected in this record## Numbers corrected in this record

Three figures in the round-2 commit body were wrong, and are corrected here
rather than left in the history unchallenged:

- The un-derivable "N of five hand-built payloads" ratio. Round 2 said it stood
  in six places and removed it from five; round 3 "corrected" the count to five
  and declared it closed. **Both were wrong, in opposite directions** — the
  population was six, and the sixth survived two rounds because each round
  checked the NUMBER instead of the tree. It is gone now, and the check is a
  grep for the ratio's own wording rather than a sentence in this file: a count
  printed in a document that is itself counted cannot be trusted.
- "this commit's parent already stood at 30" — the parent stood at **34**; 30
  was the grandparent.
- "all three failed toward the same wrong conclusion" — true of two; the
  un-deduplicated count changed a number, not a verdict.

Two figures quoted from reviewers are **inherited, not re-derived here**: the
523 → 732 byte record growth and the 20,425-input fold fuzz. Neither has a
committed command. The per-call cost figures are for the annotation work as a
whole (`_annotation_shape` plus `_annotation_usable_count`), not for
`_annotation_shape` alone as an earlier draft implied.

## How this was verified

- **26 of 26 mutants killed** over a green baseline of `99 passed`, by
  `scripts/prove_annotation_capture_bites.py` — **committed**, so the claim is
  re-runnable. The first version reported "15 of 15" from a script that was then
  deleted, and reviewers writing their own mutants found survivors across the
  same two test files. A 100% kill rate on self-chosen mutants is not adequacy
  evidence; every mutant here reintroduces a defect a reviewer demonstrated, and
  the mutants added in rounds 2, 3 and 4 are each the ones the earlier sets
  could not see. Round 4 wrote seven of its own and two survived, so **do not
  read a kill rate as adequacy** — see the blind spots above.
- **The proof caught four defects in tests that looked right.** The
  interleaved-ordering test used a row order under which first-appearance and
  last-appearance give the same answer; the content-rank test used shapes whose
  answer is the same under the documented order and its permutation. Both
  passed while pinning nothing. And the ``--run`` test named the one run that a
  "just use the default" mutant also picks, so a mutant ignoring the flag
  entirely survived it. And the argv tests asserted only exit code 2, so each
  specific refusal was being satisfied by a DIFFERENT guard and mutants deleting
  them individually survived.
- **A helper can be correct and untested at once.**
  `_whole_body_annotation_sites` was exercised only by direct call, so deleting
  its CALL SITE left the whole proof green. Pin the use, not the constant —
  one layer up from where that rule usually bites.
- Each of the four capture defects was reproduced by execution before the fix
  and re-run after: 2-sources-as-8, `absent` at four sites, 360 characters as
  `0`, and `flat` with zero extracted citations.
- Field counts (27 → 34) and the floor baselines (12 on clean `HEAD`, 18 on the
  branch) were measured on separate `git archive HEAD` copies, not derived by
  arithmetic.
