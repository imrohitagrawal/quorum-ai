# ADR-0088: Docs name the shipped default slots, and a gate proves it

## Status

Accepted — 2026-09-01 (board row W17)

## Context

`src/product_app/model_slots.py` stopped shipping `deepseek/deepseek-chat-v3.1`
in default slot 4 on **2026-07-25**, in commit `f25696e` (as
`nvidia/nemotron-3-super-120b-a12b`); `3bf13a6` narrowed it two days later to
the shipped `nvidia/nemotron-3-nano-30b-a3b`. Ten live documents still named
deepseek there, including the two that other artefacts trace to:

- `docs/10-functional-requirements.md` (FR-004)
- `docs/12-acceptance-criteria.md` (AC-007)

Nothing failed for five weeks. The suite was fully green throughout, because no
check compared the sentence to the constant — the same shape as the "twelve
specs" drift that Part D of `tests/test_doc_gate_consistency.py` was written
for.

`git grep -l "deepseek/deepseek-chat-v3.1" | wc -l` returns **113** files, and
that number is the trap. Measured on this branch's base:

| Where | Files | Stale? |
|---|---|---|
| `tests/` | 91 | No — fixture and catalog data. deepseek is a real, selectable OpenRouter model. |
| live `docs/` (excl. `archive/`, `validation/`) | 13 | Mixed — the actual work |
| `docs/archive/` + `docs/validation/` | 6 | No — records of runs that happened |
| `src/` | 1 | No — the `_FALLBACK_CATALOG` row in `src/product_app/catalog_fetcher.py` (defined line 127, deepseek row line 244), retained deliberately by `3bf13a6`. `model_slots.py` only imports it. |
| `PRODUCT_IDEA.md` | 1 | No — intake record |
| `scripts/` | 1 | No — synthetic demo seed data |

A global replace would have rewritten 100 files that were already correct.

Two further stale claims did **not** contain that exact string and so were
invisible to the census. Both were found by adversarial review, and both are
present-tense assertions about the shipped product:

- `docs/design-handoff/AC-CROSSWALK.md:48` — the AC-007 traceability row, which
  wrote the ids **without vendor prefixes** (`deepseek-chat-v3.1`).
- `docs/architecture/40-decisions.md:53` — *"The default four slots cover four
  vendor families (OpenAI, Anthropic, Google, DeepSeek)"*, which names no id at
  all.

## Decision

**1. Correct only documents that assert, in the present tense, what the shipped
product defaults to.** Ten files: `README.md`, `docs/01-product-brief.md`,
`docs/08-prioritization.md`, `docs/10-functional-requirements.md`,
`docs/118-qa-test-charter-jira.md`, `docs/12-acceptance-criteria.md`,
`docs/20-architecture.md`, `docs/35-confluence-operational-guide.md`,
`docs/51-test-data-strategy.md`, `docs/design-handoff/AC-CROSSWALK.md`, plus
`docs/architecture/40-decisions.md`. (`README.md` was already correct and is
covered by the gate; the other ten were edited.)

**2. Annotate, never rewrite, a dated record.** Three files state deepseek as
something that was true at a point in time, and that statement is still true:

- `docs/04-problem-statement.md` — the product owner's 2026-06-16 clarifying
  answer, logged as decision D-010.
- `docs/13-open-questions.md` — the same answer recorded against OQ-005.
- `docs/design-handoff/README.md` — describes an approved visual mock that
  genuinely shows DeepSeek V3.1.

Each gets an additive "Superseded 2026-07-25" note pointing at
`DEFAULT_MODEL_IDS`. The record stays intact; the reader is not misled.

**3. Leave four files untouched entirely.** `PRODUCT_IDEA.md` (the factory's
first source of truth, an intake record), `docs/design-handoff/Quorum Final
Review.dc.html` (the rendered mock itself — the README note above covers the
drift), `scripts/seed_feedback_audit_data.py` (demo data that already mixes in
`anthropic/claude-3-haiku` and `google/gemini-2.5-flash-lite`, so it asserts
nothing about defaults), and `docs/65-open-work.md` (the board row describing
this defect).

**4. Add a gate, because AGENTS.md rule 1a says a corrected number lasts until
the next change and a gate lasts.** Part G of
`tests/test_doc_gate_consistency.py` reads each covered document's
**default-claim blocks** — a line carrying a "default" cue, or sitting under a
heading that does, plus any list items directly beneath it that are nothing but
one backticked id — and asserts the ordered tuple equals
`product_app.model_slots.DEFAULT_MODEL_IDS`.

## Rejected alternatives

**Global find-and-replace across all 113 files.** Rejected: 100 of them are
correct. Fixtures name deepseek because it is a real catalog model; archives
name it because those runs really used it. This is the failure mode the change
exists to avoid, at a hundred times the blast radius.

**Correct the sentences and ship no gate.** Rejected by rule 1a. The sentences
had already drifted once with a fully green suite; nothing about correcting them
stops the next drift.

**Extract every backticked `vendor/model` token in the whole file.** This was
the FIRST implementation, and adversarial review broke it twice:

- `README.md` — the repo's front door, and the highest-traffic statement of the
  defaults — could not be covered at all, because line 42 names
  `anthropic/claude-haiku-4.5` a second time when describing
  `settings.debate_model_id`. Whole-file extraction read five ids and failed on
  a correct document, which is why README was originally left out of the gate.
- A backticked MIME type (`application/json`, `text/event-stream`) added to any
  covered document turned the gate red with a message blaming the model slots.
  Eight documents were one ordinary sentence away from a misleading failure.

Block scoping fixes both, and a block counts only if it names at least two ids —
a default-slot claim names a SET, which is what keeps `README.md:42`'s single-id
aside out of the comparison.

**Anchoring on the word "default" in the same LINE as the ids.** Rejected after
measurement: `docs/12-acceptance-criteria.md:51` — one of the two documents at
the centre of the defect — states the slot set without using the word anywhere
in that sentence (*"then four slots are populated with …"*). A **line**-scoped
cue would have skipped it and passed. Its heading two lines above **is**
`## AC-007 Default models populated`, so the gate propagates a heading's cue
down to the lines it introduces; that heading rule is what covers AC-007, and
`test_a_default_claim_is_read_from_a_block_not_the_whole_file` pins it.

**Asserting only that `deepseek/deepseek-chat-v3.1` is absent.** Rejected under
rule 7: a negative check is trivially true over a document that names no models,
and it would say nothing if slot 3 drifted. The gate asserts an ordered
four-element equality and refuses an empty input at BOTH levels — per document,
and across the corpus.

**Matching model ids as bare substrings.** Rejected under rule 8. Backticks are
the markup that makes a token an identifier rather than prose, so the extractor
requires them — and a negative partner pins that an unbackticked mention is
*not* matched.

## Consequences

- Changing `DEFAULT_MODEL_IDS` now turns ten documents red until they are
  updated. That coupling is the point; the failure message names the file, the
  line, both lists, and the command that prints the real one.
- **Known blind spots, stated rather than implied.** Both were reproduced by
  review and are inherent to a markup-anchored check:
  - an id written **without backticks** ("the fourth slot is
    deepseek/deepseek-chat-v3.1") is invisible, and
    `test_the_model_id_extractor_ignores_paths_and_mime_types` asserts that on
    purpose;
  - an id inside a **fenced code block** carrying no "default" cue line is
    invisible.
  Both would be NEW contradicting prose rather than the existing sentence going
  stale, which is the drift this gate exists to stop. Closing them needs a
  meaning-level check, not a tighter regex.
- **`docs/faq/index.html` and `docs/readme-verification-appendix.md` state the
  defaults in `<code>` tags, not backticks**, so this extractor cannot read
  them. Both are correct today. Covering them needs an HTML-aware reader and is
  follow-on debt.
- The extractor must exclude backticked repo paths (`docs/22-api-contract.md`,
  `src/product_app`) and MIME types, which these documents use heavily.
  `_FILE_SUFFIX_RE` is defence-in-depth only: review measured that removing it
  turns nothing red today, because every token it would reject is already
  rejected by `_NON_MODEL_PREFIXES`. It is documented as such rather than
  claimed load-bearing.
- Adding a fifth slot, or a document that legitimately names a non-default model
  inside a "default" sentence, will make this gate red. The fix is to update
  `_DEFAULT_SLOT_SPEC_DOCS` (and `_MIN_SPEC_DOCS`) with a stated reason — not to
  loosen the comparison.
- The three annotated records still contain the string
  `deepseek/deepseek-chat-v3.1`. That is deliberate and is why they are outside
  `_DEFAULT_SLOT_SPEC_DOCS`.

## Verification

Five mutations, all with `PYTHONDONTWRITEBYTECODE=1`, each restored from a `cp`
copy and confirmed with `diff -q`. The first three are the drift the gate exists
for; the last two are holes adversarial review opened in the first
implementation and which the shipped one closes.

1. **Against the uncorrected docs** — RED: *"docs/01-product-brief.md names
   default model slots [… deepseek/deepseek-chat-v3.1]; the product ships […
   nvidia/nemotron-3-nano-30b-a3b]"*.
2. **Slot 4 of `DEFAULT_MODEL_IDS` mutated** to `mistralai/mistral-small` —
   RED, naming both lists.
3. **The four ids deleted from `docs/20-architecture.md`** — RED, i.e. it
   refuses an empty input rather than passing over nothing.
4. **`README.md` and `docs/design-handoff/AC-CROSSWALK.md` reverted to
   deepseek** — RED. Both were GREEN against the first implementation: README
   was not covered, and the crosswalk's unprefixed ids were unreadable.
5. **`_DEFAULT_SLOT_SPEC_DOCS` emptied** — RED via
   `test_the_default_slot_corpus_is_not_empty`. Against the first
   implementation this was **GREEN**: the gate measured zero documents and
   reported success, which is exactly the empty-input failure AGENTS.md forbids.

And one regression proof in the opposite direction: appending *"served as
`application/json` over `text/event-stream`"* to `docs/20-architecture.md`
leaves the gate GREEN. The first implementation went red on that, blaming the
model slots.
