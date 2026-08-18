# ADR-0059: The negative-assertion guard resolves a member property through both `Identifier.name` and a static literal, and fails closed when it cannot

## Status

Accepted — 2026-08-19 (issue 226; ADR-0058 was the first half, this is the classifier half)

## Context

`e2e/tools/check-negative-assertions.mjs` is the #131 guard: it fails a changed
Playwright spec whose negative assertion has no positive partner in the same
`test()`. It read a member expression's property as `node.property.name` at five
separate places — the matcher, the `.not` walk, the `expect.soft`/`expect.poll`
root, `isTestCall`, and `isDescribeCall`/`isBeforeEachCall`.

For a **computed** property (`expect(x)["not"]`) the property node is a
`Literal`, not an `Identifier`, so `.name` is `undefined` and every one of those
reads silently produced nothing. One root cause, six measured faces, in **both**
failure directions at once.

Each row below was reproduced by driving the exported `checkSource` against
`origin/main` at `5bbe616` from a throwaway copy of the checker, over the
fixture in the first column. "main" is the number of violations it reported.

| Fixture (with the partner or negative shown) | main | Correct | Direction |
|---|---|---|---|
| `expect(x)["not"].toBeVisible()` + a real unpartnered negative | 0 | 2 | evasion — the fake `.not` posed as the partner |
| `expect(b)["toBeHidden"]()`, alone | 0 | 1 | evasion — invisible; needs no partner to hide behind |
| `expect.soft(b)["toBeHidden"]()`, alone | 0 | 1 | evasion |
| `expect["soft"](b).toBeVisible()` + a real negative | 1 | 0 | FALSE POSITIVE |
| `expect(b)["toBeVisible"]()` + a real negative | 1 | 0 | FALSE POSITIVE |
| `test["only"]("t", …)` with an unpartnered negative inside | 0 | 1 | evasion — the WHOLE test body went unwalked |
| `test["describe"](…)` with a `beforeEach` liveness partner | 1 | 0 | FALSE POSITIVE — the partner never reached the test |
| ``expect(x)[`not`].toBeVisible()`` + a real negative | 0 | 2 | evasion, and statically resolvable |
| `const k = "not"; expect(x)[k].toContainText("gone")` | 0 | 1 | UNDECIDABLE |

The command that produces the "main" column, and the "Correct" column after the
fix, is the test file itself:

```
.venv/bin/pytest tests/unit/test_negative_assertion_guard.py \
  -k "computed or template or unresolvable"
```

It reported `7 failed` before the change and passes after.

The parked branch that first found two of these carried **no test for any of
them**; `grep` for `computed` in its test file returned nothing, and its suite
was green while the defect stood.

## Decision

### 1. One `propertyName()` helper, used at every member-property read

Three spellings are static text and are resolved: a dot property, a string
`Literal`, and a `TemplateLiteral` with zero interpolations. Everything else
returns an `UNRESOLVED` sentinel.

### 2. An unresolvable property FAILS CLOSED

An assertion whose chain carries a property the parser cannot read is classified
**negative**: it demands a positive partner, and it never supplies one. Both
halves lean toward a red gate; there is no reading of the flag that makes the
guard quieter. This follows ADR-0047 — "static gate detectors resolve an
ambiguous case toward a RED gate, and bound how far they may guess" — for
exactly the class of detector ADR-0047 is about.

The report labels such a matcher `<computed>` rather than printing a name that
would only be half the story.

**The measured cost of failing closed** is that it bites only when the
surrounding test has no positive partner at all. An undecidable matcher sitting
beside a genuine `expect(x).toBeVisible()` reports zero violations
(`test_an_unresolvable_computed_property_fails_closed`, second assertion). The
existing `// no-positive-partner: <reason>` annotation is the escape hatch, and
it is the right one: it puts a human-readable reason in front of a reviewer
instead of granting a silent exemption.

### 3. The blank-character rule is Playwright's own, re-read on every test run

Adopted from the parked #226 branch. The predicate that decided whether an
argument proves the subject carries content accepted **any** template literal
(`` `` `` included) and **any** regex literal (`/(?:)/` included). It now uses
Playwright's own normalizer, copied rather than re-derived, because AGENTS.md
rule 8c says a mitigation gated on an upstream is worth exactly as much as your
measurement of that upstream.

Read here, 2026-08-19, from the `playwright-core` package installed under
`e2e/node_modules/` — its own manifest reports version `1.61.1`, the same
version pinned at `e2e/package-lock.json:1078` — in that package's
`lib/coreBundle.js`. (The installed tree is not tracked in git, so it is named
here as an install location rather than cited as a repo path.)

```
518  function normalizeWhiteSpace(text2) {
521    result2 = text2.replace(/[\u200b\u00ad]/g, "").trim().replace(/\s+/g, " ");
```

Exactly two characters are stripped, and then JavaScript `\s` is trimmed and
collapsed. `test_the_blank_character_rule_is_playwrights_own_normalizer` re-reads
that expression on every run, floors on having found at least one strip class,
and compares it against the guard's **exported** `PLAYWRIGHT_STRIPS` — read by
importing it, not by regexing the `.mjs`, whose header comment quotes the class
in prose.

The real-Chromium agreement figures the parked branch quoted for this rule are
INHERITED, not re-measured here.

### 4. `isLiveSubject`, default-deny

Also adopted from the parked branch. The predicate deciding whether an
`expect()` subject can reach live application state was a **blocklist** —
reject `Literal`, `TemplateLiteral`, `ArrayExpression`, `ObjectExpression`,
accept everything else — and the exact case its own comment claimed to close was
defeated by four characters: `expect("lit" as string).toBeTruthy()` is a
`TSAsExpression`, so it was accepted. The question is now inverted: can this
expression reach live state at all, answered by walking to the root and answered
**no** for anything unrecognised.

The accept set came from a census of `expect()` subjects across the committed
specs taken on the parked branch. That census is INHERITED and was not re-run
here; what *is* re-measured is that the guard still reports zero violations over
the tracked corpus (below) and that every `subject-live-*` row in
`PARTNER_SHAPES` is still accepted.

### 5. Scope: the test/describe recognisers are in, two other widenings are out

`isTestCall`, `isDescribeCall` and `isBeforeEachCall` are the same one-line
property read, and `test["only"]` is the largest evasion of the family (it hides
every assertion in a test at once) while `test["describe"]` is a false positive.
Leaving them out while claiming to close the computed-access family would be a
false claim in the commit body, so they are in.

The parked branch's `toHaveClass` plain-direction acceptance and its
`toHaveAttribute` first-argument tightening are **not** taken: both are
independent changes to the partner definition, not the computed-access concern
(rule 17), and neither is needed — see the sweep below.

## Regression sweep — TRACKED-ONLY

`--all` lists files with `git ls-files`, so it is blind to the gitignored specs
under `e2e/tests/review/`. Every number here is tracked-only.

Driving `checkSource` over `git ls-files 'e2e/**/*.spec.ts'`:

| Checker | Spec files | Violations |
|---|---|---|
| `origin/main` at `5bbe616` | 28 | 0 (empty set) |
| this change | 28 | 0 (empty set) |

The violation **sets**, not merely the counts, are identical — both empty. No
committed spec changes classification, so this pull request touches no
`.spec.ts` file at all, and the `// no-positive-partner:` waiver in
`e2e/tests/ui-parity/parity-behavior.spec.ts` is left exactly as it is.

## Rejected alternatives

1. **Fail OPEN on an unresolvable property** — skip the assertion, as before.
   Rejected: that *is* the defect, and ADR-0047 already settled the direction
   for this class of detector.

2. **Resolve a property from a `const` binding by dataflow analysis.** Rejected:
   undecidable in general (reassignment, imports, computed keys), and the
   fail-closed posture plus the existing waiver already give the author a cheap,
   reviewable escape.

3. **Enumerate the known computed spellings** (`["not"]`, `["toBeHidden"]`, …).
   Rejected: that is an allowlist, the anti-pattern this issue exists to remove,
   and an enumeration is what left the hole in the first place.

4. **Close the "an un-awaited locator assertion passes vacuously" hole.**
   Rejected because there is no hole. Measured on the parked branch against the
   real Playwright runner 1.61.1: two un-awaited assertions plus one awaited
   control gave `3 failed`. The shape passes only in a bare node script, not
   under the runner. Recorded here so the next session does not re-open it.
   **This measurement is INHERITED from that branch and was not reproduced
   here.**

5. **Take the parked branch's `toHaveClass`/`toHaveAttribute` changes and its
   spec edit.** Rejected on scope (rule 17) and on measurement: the guard
   already reports zero violations over the tracked corpus without them, so the
   waiver that edit removes is not load-bearing either way.

## Consequences

- An author writing a genuinely dynamic matcher in a test with no positive
  partner gets a conservative false positive and must write a waiver with a
  reason a reviewer reads. That is the deliberate direction.
- The blank-character rule is now a COPY of an upstream expression. A test
  re-reads `playwright-core` on every run and fails on drift; since ADR-0058
  that check FAILS rather than skips in the required `pytest (Python 3.12)`
  lane, because that lane runs `npm ci` in `e2e/` and sets
  `QUORUM_REQUIRE_E2E_NODE_TOOLING=1`.
- An unresolvable **test modifier** (`test[k](...)`) is still not recognised as
  a test, so its body is still unwalked. Only the statically readable spellings
  are resolved. Not closed here, and not measured in any committed spec.
- STILL OPEN, not fixed here: the guard step in `.github/workflows/e2e.yml` is
  gated `if: github.event_name == 'pull_request'`, so it never runs on
  push-to-main. Separate concern, separate pull request.
- STILL OPEN: `--all` is blind to gitignored specs, so every count this ADR
  quotes is tracked-only.
- `toHaveAttribute` is still accepted as a partner with no argument inspection
  at all. Recorded as a known limit in the checker's header, not fixed.
