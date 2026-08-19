# ADR-0059: The negative-assertion guard resolves a member property through both `Identifier.name` and a static literal, and fails closed when it cannot

## Status

Accepted — 2026-08-19 (issue 226; ADR-0058 was the first half, this is the classifier half)

## Context

`e2e/tools/check-negative-assertions.mjs` is the #131 guard: it fails a changed
Playwright spec whose negative assertion has no positive partner in the same
`test()`. It read a member expression's property as `node.property.name` at every
member-property read in the file — the matcher, the `.not` walk, the
`expect.soft`/`expect.poll` root, `isTestCall`, and
`isDescribeCall`/`isBeforeEachCall`. Count them rather than trusting a number
written here: `git show origin/main:e2e/tools/check-negative-assertions.mjs |
grep -c '\.property\.name'`.

For a **computed** property (`expect(x)["not"]`) the property node is a
`Literal`, not an `Identifier`, so `.name` is `undefined` and every one of those
reads silently produced nothing. One root cause, and the table below tabulates
each face it wore, in **both** failure directions at once.

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
halves lean toward a red gate; there is no reading of the `unresolved` flag
**inside `classify`** that makes the guard quieter.

That scoping is deliberate, because the same sentence is FALSE one level up. An
unresolvable TEST MODIFIER resolves toward SILENCE: `test[k]("t", ...)` with `k`
a binding is not recognised as a test at all, so its whole body goes unwalked
and an unpartnered negative inside it reports zero violations — measured, while
the statically-spelled `test["only"]` sibling correctly reports one. Rejected
alternative 6 records why that is not "fixed" by failing closed there too.

This follows ADR-0047 — "static gate detectors resolve an ambiguous case toward
a RED gate, and bound how far they may guess". ADR-0047 scopes itself to
detectors in `tests/`; this checker lives in `e2e/tools/`, so the posture is
being extended by analogy rather than inherited.

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
defeated by adding ` as string`: `expect("lit" as string).toBeTruthy()` is a
`TSAsExpression`, so it was accepted. The question is now inverted: could an
expression **of this shape** reach live state, answered by walking to the root
and answered **no** for anything unrecognised.

**This is default-deny on the NODE TYPE, not on reachability, and the shapes
that remain open are named rather than implied.** The predicate never asks
whether a particular value is live — that needs the dataflow analysis rejected
below. So a dead literal wrapped in a call or bound to a name is still accepted.
Measured against a genuinely vacuous negative in the same test, each of these
silences it and the guard exits 0: `expect(String("lit")).toBeTruthy()`,
`expect(Boolean(1)).toBeTruthy()`,
`expect(Object.keys({ a: 1 }).length).toBeGreaterThan(0)`, and
`const dead = "x"; expect(dead).toBeTruthy()` — against a control fixture with
no partner at all, which reports 1. This is not a regression: `origin/main`'s
blocklist accepts the same shapes. What the change closes is the
`TSAsExpression` family, not the tautology family.

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

### 6. `isLiveSubject` accepts a `NewExpression` whose ARGUMENT is live

Not planned; forced by measurement. Walking every call expression in the 28
tracked specs through both checkers found exactly **one** assertion whose
classification the change altered:
`e2e/tests/ui-parity/parity-behavior.spec.ts:1412`,
`expect(new Set(bgs).size, ...).toBe(4)`, demoted from partner to non-partner.
The asymmetry had no justification — the plain-call spelling
`Array.from(bgs).length` was already accepted through the `CallExpression` arm,
so only the `new` keyword separated them, exactly as `items.length + 1` reaches
live state through an operand via the `BinaryExpression` arm.

The arm is argument-driven, so `new Date()` — no arguments — stays dead, and
`new Set(["a"])` — a literal argument — stays dead. Both directions are pinned
as `PARTNER_SHAPES` rows. With the arm, the classification of the tracked
corpus is byte-identical to `origin/main`'s.

Deliberately NOT extended to `ArrayExpression` elements, which would cover the
spread spelling `[...new Set(live)]`: no committed spec uses it, so it would be
a widening with no measured demand.

## Regression sweep — TRACKED-ONLY

`--all` lists files with `git ls-files`, so it is blind to the gitignored specs
under `e2e/tests/review/`. Every number here is tracked-only.

Driving `checkSource` over `git ls-files 'e2e/**/*.spec.ts'`:

| Checker | Spec files | Violations |
|---|---|---|
| `origin/main` at `5bbe616` | 28 | 0 (empty set) |
| this change | 28 | 0 (empty set) |

The violation **sets**, not merely the counts, are identical — both empty.

A stronger claim was made here in an earlier revision and it was false: "no
committed spec changes classification". Re-walking all 5790 call expressions in
those 28 specs through both checkers found one that did — the `new Set(...)`
subject at `parity-behavior.spec.ts:1412` — which produced no violation only
because that test carries two other partners. Decision 6 closes it, and with
that arm the re-walk reports **0 classification changes**. A violation-set
comparison is weaker than a classification comparison; do not report one as the
other.

This pull request therefore touches no `.spec.ts` file at all, and the
`// no-positive-partner:` waiver in
`e2e/tests/ui-parity/parity-behavior.spec.ts` is left exactly as it is.

The sweep is no longer a one-off author measurement. It now runs on a required
gate as
`tests/unit/test_negative_assertion_guard.py::test_no_tracked_spec_is_reported_by_the_classifier`,
with a floor on the file count and a partner test proving the sweep machinery
reports a vacuous spec when there is one. It bites: `isLiveSubject` with its
`MemberExpression` arm returning `false` turns it red across a large share of
the tracked corpus. No spec-file count is quoted — an earlier draft of this
paragraph said "17 specs" and the real figure is 15, and a corpus count goes
stale silently (rule 1a). The test reads the counts at runtime.
Its limit is worth stating — a classification change surfaces there
only once it removes a test's LAST partner, which is exactly why the `new Set`
demotion above had to be caught by hand.

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
   spec edit.** Rejected on scope (rule 17): both are independent widenings of
   the partner definition.

   An earlier revision justified this partly on the claim that "the waiver that
   edit removes is not load-bearing either way". That is FALSE and was measured
   after the fact. Driving `checkSource` over
   `e2e/tests/ui-parity/parity-behavior.spec.ts` with the
   `// no-positive-partner:` line at 536 deleted reports
   `not.toHaveClass @536`; with it present, zero. The waiver IS load-bearing,
   because its real partner is a plain-direction `toHaveClass`, which
   `classify` still does not accept — precisely the widening this ADR declines
   to make. So the spec edit is correctly not taken here, and the waiver's own
   comment ("fix deferred to the #226 classifier PR") is still accurate about a
   future pull request, not this one. The scope decision stands; only the
   reason given for it was wrong.

6. **Fail closed on an unresolvable TEST MODIFIER too**, so `test[k](...)`
   demands partners the way an unresolvable matcher does. Rejected: the
   recogniser cannot tell `test[k](...)` from `foo[k](...)` without resolving
   the object, so failing closed there would start walking arbitrary
   two-argument calls as if they were tests. The measured cost of leaving it is
   zero on the tracked corpus, and it is disclosed in Consequences. This is a
   deliberate, narrow deviation from Decision 2's posture, not an oversight.

7. **Teach `isLiveSubject` to resolve values rather than shapes**, closing
   `expect(String("lit"))`. Rejected as the same dataflow analysis as rejected
   alternative 2, arriving by a different door. Named in Decision 4 and in the
   checker's KNOWN LIMIT 6 so it reads as a known open shape rather than a
   closure claim.

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
- `toBeTruthy()` over a Locator or Page is still accepted as a partner and
  proves nothing — those objects are truthy whether or not they match anything.
  INHERITED from the parked branch's runner measurement, not re-measured here.
  This is the limit the checker's header cross-references.
- `isLiveSubject` is default-deny on the node TYPE, not on reachability. See
  Decision 4 for the measured list of dead-value shapes it still accepts, and
  KNOWN LIMIT 6 in the checker header for the same list beside the code.
- The guard sees only the literal identifier `expect`, and only assertions
  lexically inside a `test()` body. An aliased `const e = expect` and a negative
  moved into a helper function the test calls both report zero violations,
  measured. `it.only(...)` / `it.skip(...)` bodies are likewise unwalked,
  because the modifier recogniser requires the object to be `test` and accepts
  `it` only bare — also measured, against an `it(...)` control that reports one.
  None is fixed here; all are recorded in the checker's KNOWN LIMITS.
- A LOCAL-VERIFICATION trap, pre-existing and not fixed: the script's
  `import.meta.url === \`file://${process.argv[1]}\`` entry guard compares an
  unresolved path, so invoking it through a symlinked path (on macOS, anything
  under `/tmp`) runs `main()` not at all and exits 0 having checked nothing —
  which reads exactly like a clean run. CI is unaffected; it invokes the script
  by its real path from `e2e/`.

## Related

- ADR-0047 — static gate detectors resolve an ambiguous case toward a RED gate.
  The governing posture for Decision 2, extended by analogy (see there).
- ADR-0048 — what a positive partner must be. Decisions 3, 4 and 6 change that
  definition's enforcement side; the tracked-corpus sweep is the evidence its
  partnered sites still classify as partnered.
- ADR-0058 — the first half of issue 226: making this guard's own test module
  run in a required lane. Without it, none of the tests here would execute on a
  merge gate.
- ADR-0050 — why the gap at ADR-0053 (this decision's first draft number) is
  not a defect.
