# ADR-0047: Static gate detectors resolve an ambiguous case toward a RED gate, and bound how far they may guess

## Status

Accepted — 2026-08-15 (#326, #325)

## Context

Two static-analysis detectors that live in `tests/` had a false negative each,
found by an adversarial review round on 2026-08-14. Both were advisory-severity
— neither was hiding a live doc or pin defect on the current tree (measured
below) — but both are the same shape: the detector met an input it could not
classify cleanly and quietly resolved it in the direction that produced FEWER
findings.

**#326 — `_window()` in `tests/test_doc_gate_consistency.py`.**
`_window` takes the text after a gate identifier and cuts it at the first
clause break, so `` changed-lines coverage (`diff-cover` >=95%), advisory
mutation baseline `` never attributes "advisory" to `diff-cover`. Since #141 it
first skips a run of closing markdown punctuation, and since #224/#317 a run of
balanced parenthetical asides, landing at a position `i`. A comma sitting
*exactly* at `i` is exempt — that is the idiomatic `` (`gate`, blocking) ``
shape and cutting there loses the status word. `";"` and `". "` had no such
exemption, and `str.find(boundary, i)` is inclusive of `i`, so the same sentence
spelt with a semicolon lost its claim. Measured on `origin/main` at `dd154ee`:

```
the `example-gate` job (a b), blocking  ->  ['blocking']
the `example-gate` job (a b); blocking  ->  []
the `example-gate` job (a b). blocking  ->  []
```

The real repro used the registered identifier `` `mutation-baseline` ``. It is
written as `example-gate` here on purpose: `docs/adr/` is inside this very
gate's own doc corpus, and the first draft of this ADR — quoting the real
identifier — took `test_doc_status_claims_match_the_workflows` RED on three of
its own lines, including the two the fix had just taught it to see. That is the
gate working, and it is the cheapest available proof that it is not vacuous.

**#326, second round — the first fix was too wide.** It exempted a `";"` or
`". "` whenever one sat at `i`, and `i` is also `0` on a line with no closing
punctuation and `1` when only the identifier's own closing backtick was stepped
over. In neither of those was an aside skipped, and in both a `";"` or `"."`
there is ordinary sentence punctuation. Exempting it pulled the NEXT clause into
the window. Measured on that first fix, against `origin/main` at `dd154ee` in
the same process:

```
                                                     main   first fix
the `example-gate`; blocking since June              []     ['blocking']
the `example-gate`. blocking since June              []     ['blocking']
run make example-gate. It is blocking.               []     ['blocking']
Two advisory jobs: example-gate; the other gate
  is blocking.                                       []     ['blocking']
```

Every negative partner the first fix shipped put the word "job" between the
identifier and the boundary, which puts `i` on a space and so never exercises
the exemption at all — all six of them stayed green under both the wide rule
and the narrow one. The exemption is now gated on an aside actually having been
skipped, and four spacer-free negative partners cover the shapes above.

**#325 — `_parametrize_literal_params` in `tests/unit/test_risk_constant_pins.py`.**
It binds a parametrize argument name to "literal" when every case supplies a
literal, so `assert CONST == expected` counts as a literal pin. It never read
`indirect=`. Under `indirect`, pytest hands each value to a fixture of the same
name and passes the FIXTURE'S return value to the test — the fixture may
transform, clamp or discard it — so the decorator's literal proves nothing about
what the assert compares against. `grep -n indirect tests/unit/test_risk_constant_pins.py`
returned nothing on `origin/main`; a synthetic probe against the real
`_pins_in_file` confirmed all five `indirect` shapes counted as pins:

```
indirect=True                       -> pinned (wrong)
indirect=['expected']               -> pinned (wrong)
indirect=False                      -> pinned (right)
indirect=['label'] (assert expected)-> pinned (right)
indirect=_FLAG (unresolvable)       -> pinned (wrong)
```

**#325, second round — `indirect` has two arrival paths, and the first fix read
one.** pytest's signature is
`parametrize(argnames, argvalues, indirect=False, ids=None, scope=None)`, so
`@pytest.mark.parametrize("expected", [0.001], True)` is a real indirect
parametrize with no `indirect=` text in it at all. Measured on pytest 8.4.2
with a fixture that multiplies its `request.param` by 1000, the test received
`1.0`, not `0.001` — the literal never reaches the assert. The first fix
iterated `deco.keywords` only, while its caller already read `deco.args[0]` and
`deco.args[1]` positionally and never looked at `deco.args[2]`, so every
positional spelling still counted as a literal pin:

```
parametrize('expected', [0.001], True)          -> pinned (wrong)
parametrize('expected', [0.001], ['expected'])  -> pinned (wrong)
parametrize('expected', [0.001], True, None)    -> pinned (wrong)
parametrize('expected', [0.001], _ROUTE)        -> pinned (wrong)
parametrize('expected', [0.001], False)         -> pinned (right)
```

## Decision

**When a detector in `tests/` cannot classify an input, it resolves toward the
answer that makes the gate go RED, not the one that makes it stay quiet.** A
detector that under-reports is invisible; a detector that over-reports announces
itself the first time it runs. The two fixes point in opposite syntactic
directions and are the same decision:

- **#326 widens the window** when unsure whether a boundary character is a
  clause break — more text scanned means more status claims found means more
  chances for `test_doc_status_claims_match_the_workflows` to fire.
- **#325 narrows the pin set** when unsure whether a parametrize value reaches
  the assert intact — fewer pins means more chance for
  `test_every_bucket_a_constant_really_has_a_literal_pin` to fire.

**#326: the exemption is POSITIONAL, and it requires a skipped aside.**
`_boundary_search_start(chunk, i, boundary)` steps over a boundary sitting at
exactly index `i` and nothing else — a `";"` or `". "` anywhere later in the
chunk is still a clause break and still cuts. The step is `len(boundary)`, so
the two-character `". "` is stepped over in full rather than leaving its
trailing space to re-match. **Which boundaries get that exemption differs:**

| Boundary | Exempt at `i` when… | Why |
|---|---|---|
| `","` | always | #141's rule. `` (`gate`, blocking) `` needs it after a bare punctuation run, and that shape has carried the exposure since #141 without misfiring. |
| `";"`, `". "` | only if a parenthetical aside was skipped | Without an aside, `i` is 0 or 1 and the boundary is ordinary sentence punctuation — a real clause break whose status word belongs to the next clause. |

Widening `";"`/`". "` to match the comma's unconditional rule is what the first
round of this fix did, and it is measurably wrong (Context, above).

**#325: an unresolvable `indirect` fails closed, on BOTH arrival paths.**
`_indirect_params` resolves the two static value shapes — a bool (all the
names, or none) and a list/tuple of names — and returns `None` for anything
else: a bare name, a call, or a `**kwargs` splat (`keyword.arg is None`) that
could be hiding `indirect=True`. The caller treats `None` as "assume every name
is indirect" and counts no pin from that decorator. `indirect` is read from
`deco.args[2]` first — its positional slot in pytest's signature — and only
then from `deco.keywords`. The two cannot both be present (Python raises
`TypeError`), so there is no precedence question; an `*args` splat in the
positional slot is an `ast.Starred`, unresolvable, and so fails closed like
everything else.

### Rejected alternative (#326): treat `";"` and `". "` as never a boundary

Deleting them from the boundary tuple would fix the reported shape in one line.
It also deletes the protection they exist to provide: every sentence that puts
a status word in a clause after a semicolon or a full stop would start
attributing it to whatever gate the earlier clause named.

Measured by applying exactly that alternative — `for boundary in (",",):` —
and running the file:

```
$ uv run pytest tests/test_doc_gate_consistency.py -q -p no:cacheprovider --no-cov -o addopts=""
9 failed, 47 passed in 0.81s
```

The nine are `test_a_real_semicolon_clause_break_outside_any_aside_still_cuts`,
`test_a_real_sentence_break_outside_any_aside_still_cuts`,
`test_a_bare_semicolon_clause_break_with_no_aside_still_cuts`,
`test_a_bare_sentence_break_with_no_aside_still_cuts`,
`test_a_semicolon_after_an_aside_that_quotes_an_identifier_still_cuts`,
`test_a_semicolon_straight_after_the_identifier_backtick_still_cuts`,
`test_a_full_stop_straight_after_the_identifier_backtick_still_cuts`,
`test_a_semicolon_straight_after_a_bare_identifier_still_cuts` and
`test_a_full_stop_straight_after_a_bare_identifier_still_cuts`.

### Rejected alternative (#326): exempt a `";"`/`". "` at `i` unconditionally

This is what the first round of this fix shipped, and it is the alternative
this ADR's Context section measures as wrong. Applied here as
`exempt_at_i = boundary == "," or True`:

```
4 failed, 52 passed in 0.88s
```

The four are the spacer-free negative partners
`test_a_semicolon_straight_after_the_identifier_backtick_still_cuts`,
`test_a_full_stop_straight_after_the_identifier_backtick_still_cuts`,
`test_a_semicolon_straight_after_a_bare_identifier_still_cuts` and
`test_a_full_stop_straight_after_a_bare_identifier_still_cuts`. Reverting the
other way — to `origin/main`'s comma-only rule, `exempt_at_i = boundary == ","`
— takes `3 failed, 53 passed`, the three aside-shaped positives #326 exists to
fix. The two mutations go red on disjoint sets, which is what shows the rule
sits between them rather than at either extreme.

### Rejected alternative (#325): disqualify any decorator carrying `indirect=`

Simpler to write and safe in the "counts no false pin" direction, but it throws
away real pins: `indirect=['label']` routes only `label` through a fixture, so
an `expected` literal in the same decorator is still passed directly and still
pins the constant. `indirect=False` is pytest's default spelt out and must
behave exactly like omitting the keyword. Verified by mutating
`_indirect_params`'s inner `_resolve` to `return set(names)` unconditionally:

```
4 failed, 36 passed, 1 warning in 1.29s
```

The four are the positive partners
`test_an_indirect_list_naming_another_param_still_pins_this_one`,
`test_an_explicit_indirect_false_still_pins_the_constant`,
`test_a_positional_indirect_false_still_pins_the_constant` and
`test_a_positional_indirect_list_naming_another_param_still_pins_this_one`.

For the opposite direction — dropping the `indirect` read altogether, which is
`origin/main`'s behaviour — `indirect = set()` in the caller takes
`7 failed, 33 passed`: the four keyword-path negatives and the three
positional-path ones. Deleting only the positional read
(`if len(deco.args) > 2:` made unreachable) takes `3 failed, 37 passed`, which
is the whole value of this second round.

## Measurements (2026-08-15, this machine, CPython 3.14.5)

Neither fix changes any real result on the tree as it stands today. Both were
measured by importing the `origin/main` copy (`git archive origin/main`) and the
fixed copy into one process and running BOTH over the SAME corpus — the branch
tree, so the two columns are like-for-like:

| Detector | Population | Before | After | Changed |
|---|---:|---:|---:|---:|
| `_claims` (#326) | 30,729 doc lines × 6 gates | 39 claims | 39 claims | **0** |
| `_pins_in_file` (#325) | 241 test files | 233 constants | 233 constants | **0** |

The population is the BRANCH's corpus, which is larger than `origin/main`'s
30,456 doc lines because this ADR and its index row are themselves inside the
corpus this gate scans. Running each detector over its own tree instead gives
the same 39 → 39.

Both totals are non-zero, so the "changed: 0" row is a real comparison and not a
comparison of two empty sets. The 233 is the union of pinned constant names, not
a sum; the per-file sum is 340, also unchanged. The value of both fixes is
forward protection: today the tree has **172** `parametrize` decorators, of which
**0** carry `indirect` as a keyword and **0** carry a third positional argument,
so both spellings are equally latent and equally unprotected before this change.

## Consequences

- A doc sentence may now put its status word after a semicolon or a full stop
  **that immediately follows a parenthetical aside** and still be checked. A
  semicolon or full stop anywhere else — including one sitting straight after
  the identifier with no aside in between — still cuts exactly as it did on
  `origin/main`.
- **The `". "` exemption is the widest guess in this change.** A status word in
  the sentence *after an aside* — `` the `example-gate` job (see #1). The other
  gate is blocking. `` — is now inside the window and can be attributed to the
  wrong gate. That is the accepted cost of failing loud: the failure mode is a
  RED gate on a correct doc line, which a human sees and fixes in one edit,
  rather than a green gate over a wrong one. The exposure is bounded to the
  after-an-aside case; the first round of this fix extended it to every full
  stop after an identifier, which is ordinary English and far too wide.
  Measured today, zero of 30,729 real doc lines change classification.
- **A parameter routed through a fixture by `indirect` can no longer satisfy
  bucket A**, in either the keyword or the positional spelling. This is a claim
  about the PARAMETER, not the decorator: `indirect=False` and an `indirect`
  list naming only *other* parameters are unaffected and still pin — that is
  what `test_an_explicit_indirect_false_still_pins_the_constant` and
  `test_an_indirect_list_naming_another_param_still_pins_this_one` assert. A
  test author who legitimately needs a bucket A constant routed through a
  fixture must pin it a second way, or move it to bucket B.
- The conservative `None` path means a `**kwargs` splat on any `parametrize`
  decorator now silently contributes no pins. If a real test ever needs that
  spelling, the gate will say so by failing on the constant it stopped pinning
  — it will not pass while pinning nothing.

## Related

- ADR-0039: the constant-pin and enum-pin detectors and their triage buckets —
  #325 extends its `_parametrize_literal_params`.
- ADR-0038: guard tests prove they bite by mutating the ARTIFACT, not the test.
  Both fixes here were bite-proved that way (mutate the detector, watch the
  new tests go red, restore from a `cp` copy, `diff -q`).
