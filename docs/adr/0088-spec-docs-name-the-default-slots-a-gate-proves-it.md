# ADR-0088: Spec docs name the shipped default slots, and a gate proves it

## Status

Accepted — 2026-09-01 (board row W17)

## Context

`src/product_app/model_slots.py` has shipped `nvidia/nemotron-3-nano-30b-a3b`
in default slot 4 since commit `3bf13a6` (WP-G1/F-11, 2026-07-27). Eight live
specification documents still named `deepseek/deepseek-chat-v3.1` there,
including the two that other artefacts trace to:

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
| `src/` | 1 | No — `_FALLBACK_CATALOG`, retained deliberately by `3bf13a6` |
| `PRODUCT_IDEA.md` | 1 | No — intake record |
| `scripts/` | 1 | No — synthetic demo seed data |

A global replace would have rewritten 100 files that were already correct.

## Decision

**1. Correct only documents that assert, in the present tense, what the shipped
product defaults to.** Eight files: `docs/01-product-brief.md`,
`docs/08-prioritization.md`, `docs/10-functional-requirements.md`,
`docs/118-qa-test-charter-jira.md`, `docs/12-acceptance-criteria.md`,
`docs/20-architecture.md`, `docs/35-confluence-operational-guide.md`,
`docs/51-test-data-strategy.md`.

**2. Annotate, never rewrite, a dated record.** Three files state deepseek as
something that was true at a point in time, and that statement is still true:

- `docs/04-problem-statement.md` — the product owner's 2026-06-16 clarifying
  answer, logged as decision D-010.
- `docs/13-open-questions.md` — the same answer recorded against OQ-005.
- `docs/design-handoff/README.md` — describes an approved visual mock that
  genuinely shows DeepSeek V3.1.

Each gets an additive "Superseded 2026-07-27" note pointing at
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
`tests/test_doc_gate_consistency.py` extracts every backticked
`vendor/model` token from each of the eight spec docs and asserts the ordered
tuple equals `product_app.model_slots.DEFAULT_MODEL_IDS`.

## Rejected alternatives

**Global find-and-replace across all 113 files.** Rejected: 100 of them are
correct. Fixtures name deepseek because it is a real catalog model; archives
name it because those runs really used it. This is the failure mode the change
exists to avoid, at a hundred times the blast radius.

**Correct the eight sentences and ship no gate.** Rejected by rule 1a. The
sentences had already drifted once with a fully green suite; nothing about
correcting them stops the ninth drift.

**Anchor the gate on the word "default" near a model id.** Rejected after
measurement: `docs/12-acceptance-criteria.md:51` — one of the two documents at
the centre of the defect — states the slot set without using the word
"default" at all (*"then four slots are populated with …"*). A cue-word anchor
would have skipped it and passed. The gate reads the whole file instead.

**Assert only that `deepseek/deepseek-chat-v3.1` is absent.** Rejected under
rule 7: a negative check is trivially true over a document that names no models,
and it would say nothing if slot 3 drifted. The gate asserts an ordered
four-element equality and refuses an empty input.

**Match model ids as bare substrings.** Rejected under rule 8. Backticks are the
markup that makes a token an identifier rather than prose, so the extractor
requires them — and a positive/negative partner test pins that an unbackticked
mention is *not* matched.

## Consequences

- Changing `DEFAULT_MODEL_IDS` now turns eight documents red until they are
  updated. That coupling is the point; the failure message names the file, both
  lists, and the command that prints the real one.
- The extractor must exclude backticked repo paths (`docs/22-api-contract.md`,
  `src/product_app`), which those docs use heavily. Two independent filters do
  it — a first-segment prefix set and a file-suffix rule — because
  `docs/08-prioritization.md` cites `docs/07-open-questions.md`, a path that no
  longer exists, so an "is it a real file?" test would have mis-classified it.
- Adding a fifth slot, or a spec doc that legitimately names a non-default
  model, will make this gate red. The fix is to update
  `_DEFAULT_SLOT_SPEC_DOCS` with a stated reason — not to loosen the
  comparison.
- The three annotated records still contain the string
  `deepseek/deepseek-chat-v3.1`. That is deliberate and is why they are outside
  `_DEFAULT_SLOT_SPEC_DOCS`.

## Verification

Bite-proved in three directions, all with `PYTHONDONTWRITEBYTECODE=1`, every
mutation restored from a `cp` copy and confirmed with `diff -q`:

1. Against the uncorrected docs — RED: *"docs/01-product-brief.md names default
   model slots [… deepseek/deepseek-chat-v3.1]; the product ships […
   nvidia/nemotron-3-nano-30b-a3b]"*.
2. Slot 4 of `DEFAULT_MODEL_IDS` mutated to `mistralai/mistral-small` — RED,
   naming both lists.
3. The four ids deleted from `docs/20-architecture.md` — RED with *"names no
   OpenRouter model ids at all"*, i.e. it refuses an empty input rather than
   passing over nothing.
