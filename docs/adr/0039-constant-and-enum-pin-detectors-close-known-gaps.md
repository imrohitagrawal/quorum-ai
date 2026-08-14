# ADR-0039: The constant-pin and enum-pin detectors close their stated gaps, with a deliberately conservative reachability rule

## Status

Accepted — 2026-08-14 (#145, #160)

## Context

`tests/unit/test_risk_constant_pins.py` guards module-level constants in
risk-tier code with a triage registry (bucket A: literal pin, bucket B: pin
the behaviour, bucket C: no pin, with a reason). Its own docstring named
three measured gaps, tracked as #145:

1. No reachability check — an assert inside `if False:`, a
   `@pytest.mark.skip`ped test, or an uncalled nested function still counted
   as a pin.
2. `pytest.approx(...)` and container literals (`Tuple`/`List`/`Set`/`Dict`)
   were rejected outright, so a float or a collection constant could not be
   promoted to bucket A even where that is the correct pin shape.
3. Discovery covered module-level names only. Class-level ALL-CAPS attributes
   (e.g. `config.Settings.RUN_DEADLINE_MAX_SECONDS`) were invisible.

Separately, #160 measured that most production `StrEnum` classes have no
exhaustive membership pin: adding a member can go unnoticed by every gate
except a schema-shape check that a routine regeneration would clear.

## Decision

**Close all three #145 gaps in the existing detector, and add a separate,
purpose-built exhaustive-membership pin file for #160** rather than
generalizing the constant-pin detector to also understand enums.

### #145 gap 1 — reachability

`_reachable_asserts` walks a collected test's statement list and stops at:
dead code after an unconditional `return`/`raise`/`continue`/`break`; the
untaken branch of a literal `if True:`/`if False:`; and **any** nested
`def`/`async def`, called or not.

**The nested-function rule is deliberately conservative**: the detector never
descends into a nested function's body, even if that function is invoked
elsewhere in the same test. The alternative — proving the nested function is
actually called — requires call-graph analysis inside a single function body,
which is real complexity for a case that does not occur anywhere in this
repo's ~30 real pins today (every one is written directly in its test's
body). If a legitimate pattern ever needs an assert inside a called nested
helper, the fix is to inline the assert into the collected test, not to teach
the detector call-graph analysis.

A test is "collected" if it is a module-level or class-method `test_*`
function without a `@pytest.mark.skip`/`skipif` decorator. Decorator
detection matches the AST shape (`Attribute(attr="skip", value=Attribute
(attr="mark"))`), not a substring of `ast.dump` — an early draft used
`"mark.skip" in ast.dump(deco)`, which never matches a real
`pytest.mark.skip(...)` decorator, because `ast.dump` renders `attr='mark'`
and `attr='skip'` as separate, non-adjacent fields. Caught by running the
detector's own self-test before committing (rule 6).

### #145 gap 2 — approx and containers

`_is_literal` now accepts `pytest.approx(...)` and the bare `approx(...)`
import form (both used in this repo), and `Tuple`/`List`/`Set`/`Dict`
literals whose elements are themselves literal. An empty container is
rejected, mirroring the existing zero-arg-call guard for `Decimal`/
`frozenset`/etc: `all([])` is vacuously `True`, so `assert X == ()` must not
read as a pin of `X` to "some tuple."

That closed the direct-literal shape, but not the shape the issue calls out
by name: "the natural way to write 13 pins" is
`@pytest.mark.parametrize('expected', [0.001])` /
`assert CONST == expected`, where the literal lives in the decorator and
`expected` is an `ast.Name` at the assert site — nothing `_is_literal` can
see on its own, since the value it would need to inspect is not in the
comparison at all. A first version of this ADR and the surrounding
docstrings claimed gap 2 was "fully closed" without this case; it was not —
`_pins_in_file` resolved a parametrize-bound argument the same as any other
`ast.Name`, i.e. symbolic, never a pin. `_parametrize_literal_params` closes
it: for each collected test, it reads its `@pytest.mark.parametrize`
decorators (single- and multi-argname forms) and binds a parameter name to
"literal" only when **every** case in that parametrize list supplies a
literal for it — one symbolic case (e.g. a value computed from another
module constant) means the assert does not prove the constant against a
literal on every run, so the name stays unpinned
(`test_a_parametrized_non_literal_does_not_pin_the_constant`).

### #145 gap 3 — class-level constants

`_class_constants` walks each risk module's class bodies for ALL-CAPS
attributes, explicitly excluding `Enum`/`StrEnum`/`IntEnum`/`IntFlag`/`Flag`
subclasses. This found **17** class constants (not the sixteen the issue
named — that count was itself never checked against the fixed detector), all
now triaged:

- Six (`_InMemoryIpRateLimiter`/`_InMemoryAccountRateLimiter`'s `CAPACITY`,
  `REFILL_PER_MINUTE`, `STALE_BUCKET_SECONDS`) are bucket A. Four were
  already pinned by `test_session_rate_limit_override.py` — invisible as a
  *triage* entry before `_qualify` learned to resolve a class import
  (`_InMemoryIpRateLimiter.CAPACITY`) to its module
  (`query_runs._InMemoryIpRateLimiter.CAPACITY`). `STALE_BUCKET_SECONDS` had
  no pin anywhere; `test_the_rate_limiter_eviction_windows_are_pinned` adds
  one.
- Five are bucket B: the two `config.Settings` bounds
  (`RUN_DEADLINE_MAX_SECONDS`, `SESSION_RATE_LIMIT_MAX`,
  `SESSION_MINT_CAP_OVERRIDE_MAX`) are pinned behaviourally by existing
  bound-plus-one-rejected tests; `feedback_store.FeedbackStore
  ._F01_MIGRATION`/`_F01_PREVIEW_SELECT` are pinned by
  `test_f01_preview_billing_backfill.py`'s idempotency proof, which matters
  more than the literal marker string (any string works as long as it gates
  re-application).
- Six are bucket C: the three `MAX_EVENTS` ring-buffer caps (memory, not
  correctness) and three `FeedbackStore` SQL DDL/index strings (churn; fail
  loudly at open if malformed, and the covering index's own docstring already
  measures its loss as latency, never correctness).

### #160 — enum exhaustiveness gets its own file, not a generalized detector

`tests/unit/test_enum_membership_pins.py` follows the same
discover-then-force-triage shape (`_production_enum_classes` walks
`ast.ClassDef` nodes for `StrEnum` bases), but does **not** attempt to detect
arbitrary "does some test assert exhaustive membership" shapes across
`tests/`. Real exhaustive pins in this repo already use at least three
different shapes — `set(Enum) == A | B` (`ProviderPath`), whole-dict equality
(`BillableStage`/`StageBillingState`), and (rejected as NOT exhaustive by
the issue's own follow-up) single-member `==` comparisons
(`WarningType`, initially miscounted as pinned by a regex that matched a
dict literal). Building a general detector for "any of these shapes,
anywhere in tests/" repeats the exact mistake #160's own comment thread
already made once. Instead, `ENUM_MEMBER_PINS` is a hand-typed registry of
the literal member-value set for all 17 enums, checked in one place, with
the triage-forcing test (`test_every_production_enum_is_registered`) as the
only generalized part.

## Rejected alternatives

- **Generalize `_class_constants` to also enumerate enum members**, folding
  #160 into the same file: rejected. Enum membership and "a wrong scalar
  value is silently harmful" are different questions with different pin
  shapes (a set-equality vs. a single literal comparison); conflating them
  would force one triage vocabulary (A/B/C) onto a problem that only ever
  needs "pinned or not."
- **Detect existing exhaustive-set pins automatically** (an AST search for
  `assert set(X) == ...` anywhere in `tests/`) rather than a hand-typed
  registry: rejected. #160's own history shows a regex-based version of this
  already produced one false positive (`WarningType`); a hand-typed registry
  with an independent literal is the same reasoning bucket A already uses,
  and is the one shape proven not to drift silently.
- **Track call graphs to allow asserts inside a called nested function**
  (gap 1): rejected as complexity with no present payoff — see above.

## Consequences

- A new module-level or class-level ALL-CAPS constant in a risk-tier module
  must be triaged (`test_every_risk_constant_is_triaged`) or the suite fails.
- A new production `StrEnum` in one of the eleven listed modules must get a
  membership pin (`test_every_production_enum_is_registered`) or the suite
  fails; a member added to an already-pinned enum fails
  `test_every_registered_enum_membership_matches_its_pin` directly.
- An assert inside dead code, a skipped test, or an uncalled nested function
  can no longer satisfy a bucket A pin.
- `pytest.approx` and container literals are now legitimate bucket A pin
  shapes, unblocking constants that were previously forced into bucket B
  purely because the detector could not see a correct bucket A pin.
