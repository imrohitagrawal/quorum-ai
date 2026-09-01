# ADR-0086: The moderator grading its own answer is reported, not refused

## Status

Accepted — 2026-09-01

## Context

`settings.debate_model_id` picks one model to audit the panel's answers.
Nothing has ever stopped that model also being **on** the panel — and in the
shipped defaults it is:

| Setting | Value | Where |
|---|---|---|
| `debate_model_id` | `anthropic/claude-haiku-4.5` | `config.py` |
| slot 2 default | `anthropic/claude-haiku-4.5` | `model_slots.py`, `DEFAULT_MODEL_IDS` |

Measured on `origin/main` at `c15edbe`:
`grep -c "debate_model_id" src/product_app/model_slots.py` → **0**. The two
values were equal and neither module knew about the other.

**This is not cosmetic, and the moderator is not blind to it.** The chain, all
in `src/product_app`:

1. `debate._debate_user_prompt` labels every answer with its model —
   `f"- Slot {answer.slot_number} — {label} ({answer.status.value}): {excerpt}"`,
   where
   `label` is `answer.display_name or answer.model_id`.
2. `ROUND_ONE_SYSTEM_PROMPT` and `ROUND_TWO_SYSTEM_PROMPT` both say
   *"Cite the model names"*.
3. So the moderator reads a panel containing its own answer, labelled as its
   own, and is asked to name names while grading it.
4. It replies with a `PanelStance` carrying one position per slot
   (`debate.parse_moderator_output`).
5. `synthesis_consensus._usable_stance` turns that into
   `{slot number: position}` and hands it to `panel_agreement` —
   `"agreed" if len(set(stance.values())) == 1 else "split"` — and to
   `compute_consensus_strength`, which returns `"strong"` when one group
   reaches `_required_cluster(len(stance))` (3 of 4 at the shipped panel size).

One of the four votes deciding the verdict a reader is shown is therefore a
model's grade of its own work, and a self-preferring moderator only has to move
its own slot to turn a 2-2 split into a 3-1 `strong`. Nothing detected, logged
or displayed any of this.

**Deliberate or accidental?** Settled from history, not assumed.
`debate_model_id`'s value dates to the initial commit
(`git log -S'debate_model_id: str = ' -- src/product_app/config.py` → one
commit, `d3bbec2`). Slot 2 became the same id later, in `f25696e`, which moved
it from `anthropic/claude-3-haiku` to `anthropic/claude-haiku-4.5` and added the
comment `# slot 2 — Anthropic (debate)`.

So the collision was **noticed and never decided**. No ADR and no requirement
mentions it — ADR-0032 is the closest, and it addresses a *different* self-
reference (round 2 re-reading its own round-1 critique) while stating that
`_call_debate_model` is the only debate dispatch site and sends one separate
moderator model; it never says that moderator may also be a panellist.

**One place did already know, and an earlier draft of this ADR wrongly said
nothing did.** `tests/resilience/test_fault_injection_lane.py` records it in
prose — *"Slot 2 is `anthropic/claude-haiku-4.5`, which IS
`settings.debate_model_id` ... This test faulted slot 2 when it was written, on
the stated but unchecked belief that the moderator 'uses a different model id'.
It does not."* — and guards it executably in
`_faulted_model_collides_with_no_moderator()`
(`assert config.settings.debate_model_id != _FAULTED_MODEL_ID`).

That makes the case stronger, not weaker. The overlap was found, written down
and gated **for a different consequence**: it invalidated a fault-injection
scenario, because faulting slot 2 also templated the debate. Nobody carried it
across to the question this ADR asks — whether that model should be grading its
own answer in the consensus verdict — and no surface reported it. FR-008 still
describes "a single separate moderator model", which the shipped configuration
does not honour; correcting that requirement is left open, not decided here.

## Decision

**Detect the overlap and report it. Never refuse on it, and do not change which
models are used.**

`model_slots.py` gains a pure function and a thin configured wrapper:

```python
def moderator_overlap_slots(
    model_slots: Sequence[ModelSlot], *, moderator_model_id: str
) -> tuple[int, ...]

def default_moderator_overlap_slots() -> tuple[int, ...]
```

`/status` gains `moderator_slot_overlap`, the list of default panel slot
numbers that are the configured moderator. On the shipped configuration it
reads `[2]`.

Three parts of that are decisions rather than mechanics.

**1. Report, never refuse.** The shipped default IS the overlapping
configuration, so a guard that raised — at import, at startup or per run —
would fail every production run on the next deploy. A guard whose first act is
to break the thing it guards does not get deployed; it gets reverted. The
posture mirrors `ModelDefaultsResponse.stale_model_ids`, the module's existing
report-only diagnostic: *"the UI can show a small warning when this is
non-empty, but the four returned slots are unchanged."* (That field reports
catalog DRIFT — ids the upstream catalog no longer lists — not a config
conflict. The shape and the posture are the precedent; the subject is not.)

**2. `/status`, and slot numbers only.** `/status` is the operator's single
page and `static/ops.js` already fetches it. Adding a key is safe: the
public-contract test is a superset check —
`tests/security/test_operations_info_leak.py::test_status_stays_public_and_unauthenticated`
asserts `set(response.json()) >= {...}` — and no exact-equality check on the key
set exists anywhere.

`/status` **is** in `openapi.yaml` (`operationId: status_snapshot_status_get`),
and an earlier draft of this ADR said it was not. The true and narrower fact is
the one that matters: its 200 schema is `{type: object, additionalProperties:
true}`, so adding a KEY regenerates nothing — whereas editing
`status_snapshot`'s **docstring** would, because `openapi.yaml`'s `description`
is a byte-identical copy of it (8317 characters on both sides, measured) and
`make openapi-check` sits inside the required `validate-and-test` context. That
is why this change adds an inline comment and leaves the docstring alone.

The field carries slot **numbers**, never model ids, and a test asserts the id
is absent from the whole payload — but **not** because the id is a secret:
`GET /ui` with no cookie already publishes all four slot ids, so `[2]` beside
that page names the moderator's model to an anonymous caller either way. The
reasons are narrower: this field can never become a new place an id leaks from,
and numbers stay meaningful for a caller-supplied panel whose ids are not on
`/ui`. (`/status` does report values — `global_daily_spend_usd`,
`uptime_seconds`, `build_sha`. The discipline it actually keeps is its own
docstring's: never query text, account ids, session tokens, or filesystem
paths.)

**3. Normalisation, biased toward detecting.** Three things are not a
difference of model, and each is a real way the check could have been silently
switched off:

| Not a difference | Why it is reachable |
|---|---|
| case | `DEBATE_MODEL_ID` is free-text environment configuration |
| surrounding whitespace | same — a deployment tool leaves a trailing newline |
| a trailing `:variant` suffix | `:free` / `:preview` / `:batch` are the same weights on another tier. The reachable shape is a catalog- or caller-supplied id that already carries a colon — `_MODEL_ID_RE` permits it and the live catalog serves such ids (70 `:batch` ids of 425, measured 2026-09-01). |

An earlier draft justified that last row with `providers.py`'s `:online`
suffix. That was the wrong reason: `:online` is appended at dispatch
(`online_model_id = f"{bare_model_id}:online"`, and only when the slot's
`search` flag is set) and is never stored on a `ModelSlot`, so it never reaches
the comparison. `providers.py` is still correct that the debate is dispatched
without it — *"does NOT attempt the `:online` suffix — the debate and synthesis
stages…"* — it is simply not how a stored id comes to carry a colon.

The suffix is stripped from the model segment only, after the first slash, so
two vendors can never collapse into one. The bias is stated because it is a
choice: for a detector a false negative defeats the whole purpose, while a
false positive costs an operator one look.

**What this normalisation cannot see**, measured against the live public
catalog on 2026-09-01 (425 ids, free unauthenticated GET):

- **Floating aliases.** 12 ids of the form `~vendor/model-latest` exist,
  including `~anthropic/claude-haiku-latest`. A moderator set to one of those
  against a slot pinned to `anthropic/claude-haiku-4.5` reports `[]`. Whether
  that alias currently routes to the pinned id is **UNVERIFIED** — settling it
  needs a paid call.
- **`openrouter/auto`**, a per-request router that could resolve to any panel
  model. It passes `_MODEL_ID_RE` and is catalog-known.
- **Canonical slugs.** Slot 2's own `canonical_slug` is
  `anthropic/claude-4.5-haiku-20251001`, a different string.

None is reachable in the shipped configuration, and closing them needs an alias
graph the catalog does not expose. Recorded as known limits, not fixed.

Also stated rather than measured away: exactly ONE trailing `:segment` is
dropped, so `a/b:online:free` would not match `a/b`. Unreachable — **0 of the
425** live ids carry two colons, and **0 of the 13** shipped fallback ids carry
even one.

## Rejected alternatives

| Alternative | Why not |
|---|---|
| **Point `debate_model_id` at a model not on the panel** | The obvious fix, and it is a **money change**. `costs.py` prices both debate rounds on `settings.debate_model_id` and `model_slots.py` pins a per-slot price table and a `$0.00150 / 1K` combined input cost read from the live catalog on a stated date; `costs.py` reasons about this id "by 25% — the unsafe direction for a spend cap". Moving it moves real spend and real cap arithmetic, and the measurement that would justify a new value cannot be taken with `OPENROUTER_LIVE_EXECUTION_ENABLED=false`. It is a product-owner decision with a price attached, not a defect fix. Recorded as the open follow-on below. |
| **Point `debate_model_id` at `openai/gpt-4o-mini`** | The specific move ADR-0028 costed (line 43: `debate_model_id anthropic/claude-haiku-4.5 -> openai/gpt-4o-mini`, `-$0.0227/run at the cap`). It is **slot 1's** id, so it would have RELOCATED the overlap from slot 2 to slot 1, not removed it — and nothing in that ADR noticed. Whoever reopens the money question must pick a model that is on no slot. |
| **Refuse the run when the moderator is on the panel** | Breaks the shipped default on the next deploy. See decision 1. |
| **Exclude the moderator's own slot from the stance it grades** | The most directly corrective option, and out of proportion tonight. Today *every* live run overlaps, so this would change `panel_agreement` and `compute_consensus_strength` from a 4-slot to a 3-slot reading on every run — `_required_cluster(3)` is 2, not 3 — and `_usable_stance` requires the stance to cover every scored slot, so the exclusion has to be threaded through that subset test too. A verdict-changing rewrite of the consensus math is not something to ship unattended behind a diagnostic. |
| **Surface it on `/v1/models/defaults` beside `stale_model_ids`** | The closest shape precedent, but that route is in `openapi.yaml` (byte-faithful drift guard, plus the Schemathesis contract gate) and is session-gated, so it reaches the browser rather than the operator. `/status` reaches the operator, is what `/ui/ops` polls, and costs no schema change. |
| **A `logger.warning` and nothing else** | Not queryable. A field an alert rule can threshold is strictly better than a line in a log, and `/status` already carries `feedback_lost_billed_writes` on exactly that argument. |

## Consequences

- `/status` on production will report `moderator_slot_overlap: [2]` from the
  next deploy. **That is the true reading of the shipped configuration, not a
  regression** — the condition predates this change by every commit since
  `f25696e`; only the reporting is new.
- The field is reported and **never enforced**. No rail reads it, no run
  changes behaviour, and no cost constant moved. Verified: this change edits
  `model_slots.py`, `main.py`, one new test file, this ADR, the regenerated
  `docs/24-adr-index.md` and the board — six files, and it touches neither
  `costs.py` nor `config.py` nor `DEFAULT_MODEL_IDS`.
- It also reads `[2]` on a deployment that grades nothing:
  `debate._call_debate_model` returns before dispatch when live execution is off
  or the key is missing, and this field does not consult either. Read it beside
  `live_execution` in the same payload.
- **`/status` now calls `default_model_slots()`**, which assigns
  `OpenRouterModelCatalogService._last_drift_diagnostic` as a side effect. Two
  routes read that process-global in a non-atomic read-after-write pair (the
  `/ui` drift banner and `/v1/models/defaults.stale_model_ids`), and `/status`
  is unauthenticated and polled on a timer by `ops.js`, so the write rate rises.
  No wrong value was demonstrated reaching a caller — both writers compute from
  the same 6 h cache, so the interleaved write is normally identical — and the
  catalog calls per `/status` went 1 → 2, both cache hits (0.0013s → 0.0017s,
  no new network round trip). Recorded as a mechanism, not a proven harm.
- `moderator_overlap_slots` assumes no panel size. W4 (variable N) can call it
  unchanged.
- **Open, and deliberately not closed here:**
  1. Whether the moderator *should* be a panel member at all. Settling it needs
     a paid A/B — the same instrument ADR-0032 names for its own unmeasured
     question — and a re-read of the price table. Product-owner decision.
  2. `/ui/ops` renders no tile for the field yet; it is machine-readable on
     `/status` only.
  3. A **caller-supplied** slot list is not checked. `moderator_overlap_slots`
     is pure and takes any list, so the per-run check is one call away, but the
     natural home for it is `ModelSlotSelectionEvent`'s payload and reshaping
     that event's contract is its own concern (AGENTS rule 17).
