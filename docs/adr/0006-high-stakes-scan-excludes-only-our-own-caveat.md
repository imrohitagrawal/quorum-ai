# ADR-0006: The high-stakes scan strips our own caveat by token, never by wildcard

## Status

Accepted — 2026-08-03 (major-issues batch, issue #155)

## Context

`required_warnings_for_query` decides whether a caller must acknowledge a
`high_stakes` warning. It scanned `query_text` only, while both `context`
values reach a provider prompt — so high-stakes wording placed in `context`
skipped the acknowledgement entirely.

The obvious fix (scan `context` too) was shipped once and **reverted**: this
product's own mandated decision-support caveat matches `HIGH_STAKES_PATTERN`
five times (`medical`, `legal`, `financial`, `safety`, `regulated`), and
`synthesis_length` guarantees it is present in every recommendation. Scanning
it wholesale made every legitimate follow-up — a client re-sending our own
output — demand an acknowledgement.

## Decision

Scan `context` **after removing this product's own caveat**, and build the
matcher from **the caveat's own tokens joined by a whitespace/comma class**.
No wildcard anywhere in it.

## Measurements

The first implementation used wildcards
(`[^.!?]*\bdecision support only\b[^.!?]*\badvice\s*\.`) and adversarial review
broke it **4 attempts out of 4**. `[^.!?]*` is greedy and unanchored, so it ran
*backwards* over any hostile text sharing the sentence:

```
"I need a medical diagnosis for my lawsuit but this is decision
 support only and is not professional advice."      -> stripped to " "
```

Every high-stakes word vanished before the scan — a cleaner bypass than the one
being fixed. **Any "delete a span between two landmarks" shape has this flaw,
because the attacker chooses what sits in the span.**

The token-built replacement was then probed with 1,836 keyword-at-every-position
insertions and 3,000 randomised trials by a review agent: **0 bypasses**, and
every matched span, stripped of punctuation, equalled exactly the caveat's own
tokens. *(That figure is the agent's measurement, reproducible from its method,
not asserted by a test in this repo.)*

It also removed a real ReDoS: the old pattern took 4.5 s on 4.4 kB and hung past
20 s on 44 kB; the token-built one is under 1 ms on 100 kB.

## Consequences

- A caveat the model **rewords** (rather than re-punctuates) no longer matches,
  so that follow-up is asked for an acknowledgement it does not strictly need.
  Deliberate direction: an unnecessary ack is friction the client can satisfy;
  a missed one is the control not running.
- The caveat's opening clause is optional, because `synthesis_length`'s
  truncation path drops it — the product mangles its own sentence.
- `/warnings` accepts `context` and shares the create route's validator, so
  discovery and enforcement cannot disagree.

## Rejected alternatives

- **Scan the context wholesale.** Shipped once, reverted: 422s every legitimate
  follow-up.
- **Strip any sentence containing the marker.** Rejected: hands an attacker a
  better bypass — append the phrase to a hostile sentence and the whole
  sentence disappears before the scan.
- **Skip stripping; raise the threshold.** Rejected: the caveat contributes a
  fixed, large share of any short excerpt, so no threshold separates it from
  real content.

## Related

- Issue #155; `src/product_app/safety.py`
- Tests: `tests/unit/test_high_stakes_context_discriminator.py`
