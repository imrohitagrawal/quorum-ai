# ADR-0091: The board checker tokenizes Python instead of stripping `#` comments

## Status

Accepted — 2026-09-01

## Context

`scripts/check_open_work.py` derives every pinned row's state by searching a
needle in the evidence file's CODE, deliberately excluding comments — the
module's own docstring records why: appending
`# TODO: we still need to send "stream": True here` to `providers.py` would
otherwise have flipped W1's evidence, letting a comment claiming the work was
NOT done derive `DONE`. The exclusion was implemented as its own
line-by-line, whitespace-guarded `#`-stripper (`code_text()`), independent of
`tests/code_text.py` — a module that already exists to solve the identical
"prose matches the literal, not the code" problem for guard tests (PR #164),
and whose own docstring documents two prior instances of it.

`code_text()` only ever stripped comment TAILS. It never tokenized, so it had
no notion of a Python docstring at all. A needle living only inside a
triple-quoted docstring — prose *explaining* a construct, not the construct
itself — was matched as PRESENT exactly like real code. Reproduced directly
against a real row (#418): deleting W20's guard
(`if len(stance) < 2:` in `synthesis_consensus.py`) correctly flipped the
board to `PENDING`; with the guard still deleted, adding that same text to a
docstring instead flipped the row straight back to `DONE`. Every one of the
board's 17 currently-pinned rows was exposed to this — it is the board's own
truth mechanism, the one every other work package in this run is trusted to
report against.

This is the exact class of bug `tests/code_text.py` exists to prevent, and
`check_open_work.py` had grown a second, weaker implementation of the same
concern instead of using it — which is how the two were able to diverge in
the first place.

## Decision

**`scripts/check_open_work.py` loads `tests/code_text.py` directly, by path,
and routes every `.py` evidence file through its tokenizer
(`code_without_comments`), which blanks both comments and docstrings.**
Every non-`.py` evidence file (today: one Markdown row, W17) keeps using
`check_open_work.py`'s own whitespace-guarded `#`-stripper unchanged — there
is no Python parser to fall back on for Markdown or TOML, and that path's
existing behaviour is already verified against every live non-Python needle.

**Loaded BY PATH (`importlib.util.spec_from_file_location`), not as
`import tests.code_text` or `from tests.code_text import ...`.** Two
constraints ruled out a normal import:

- `tests/` carries no `__init__.py`, and `check_open_work.py` is invoked
  directly (`python3 scripts/check_open_work.py`, no `PYTHONPATH`) both from
  `make validate` and from an operator's shell — a package import would only
  resolve by accident of the caller's working directory / `sys.path`, the
  same reason this script's own tests already load *it* by path rather than
  as `scripts.check_open_work`.
- `make type-check` runs `mypy src tests`. mypy follows static imports from
  the files it is given as roots, so a real `import tests.code_text`
  statement sitting inside a `scripts/` file — a directory never given to
  mypy as a root — would still not be *visited* (mypy never opens
  `check_open_work.py`, since nothing in `src` or `tests` imports it
  statically), but the existing test-loader comment in
  `tests/unit/test_open_work_matches_reality.py` already commits to
  avoiding any static import that could put a `scripts/` file inside a
  strict-mode gate; loading by path keeps that invariant true from both
  directions rather than resting on "mypy happens not to traverse this
  edge today."

**No new dependency footprint.** `tests/code_text.py` imports only `io`,
`tokenize` and `pathlib` — stdlib, nothing pytest-specific, no fixtures, no
`conftest.py` reliance — so pulling it into `check_open_work.py`, which runs
inside `make validate` on every commit, adds nothing heavy.

## Rejected alternatives

- **Reimplement equivalent tokenization directly in `check_open_work.py`,
  with no cross-import.** This is what created the bug: a second parallel
  stripper, of different strength, that could not be prevented from
  drifting from the first. Rejected on the same grounds the module import
  itself states — duplicating the concern is the root cause, not a fix for
  it.
- **Move the shared helper to `src/`** so both `scripts/` and `tests/` reach
  it from a location neither owns. Rejected as unnecessary churn: nothing
  about `code_without_comments` is product code, it has no other consumer
  outside `tests/`, and `tests/code_text.py` is already pure-stdlib and
  therefore just as safe to import from `scripts/` as anything in `src/`
  would be — moving it would only relocate the file, not change any
  property that mattered to the decision.
- **A normal package import (`from tests.code_text import
  code_without_comments`).** Rejected for the two reasons in "Decision"
  above: it depends on invocation directory (no `tests/__init__.py`, no
  guaranteed `PYTHONPATH`), and it reopens the exact hazard this script's
  own test-loading convention was written to close.

## A bug found while adopting the fix, fixed in the same change

`tests/code_text.py`'s docstring detector (`_is_docstring`) decided whether a
`STRING` token was a docstring by looking only at what token preceded it:
`NL`/`NEWLINE`/`INDENT`/`DEDENT` meant "this string is the first thing on its
logical line," which was treated as sufficient. It is not: `tokenize` emits
`NL` for every line break **inside** an open bracket, so a dict/list/tuple
literal written one entry per line —

```python
payload = {
    "model": model_id,
    "stream": True,
}
```

— has `"model"` and `"stream"` each preceded by `NL`, exactly the shape the
heuristic read as "a docstring follows." Adopting `code_without_comments`
for W1's own evidence file (`providers.py`, whose `"stream": True` line sits
inside precisely this kind of multi-line dict) blanked the key and flipped
W1's derived state from `DONE` to `PENDING` — caught by re-deriving the full
17-row table before and after this change (see the PR body), not by reading
the diff.

**Fixed by requiring bracket depth 0.** A real docstring is by definition a
top-level expression statement; it can never appear inside `(`, `[` or `{`.
`_bracket_depths()` now computes each token's nesting depth by scanning `OP`
tokens for open/close brackets, and `_is_docstring` is only consulted when
the candidate string sits at depth 0.
`test_a_multiline_dict_key_is_not_mistaken_for_a_docstring` pins this with
the exact reproduction above, mutation-proven by removing the depth check
and confirming the assertion goes red for the demonstrated reason.

## Consequences

- Every one of the board's 17 pinned needles was re-derived before and after
  this change, by hand, against a clean `origin/main` checkout — see the PR
  body for the full before/after table. **Zero rows changed derived state.**
  The board's existing `DONE`/`PENDING` claims were not resting on a
  comment- or docstring-only occurrence; this closes a real hole in the
  mechanism without it having been exploited (knowingly or not) yet.
- The two strippers (`check_open_work.py`'s own, for non-Python evidence; and
  `tests/code_text.py`'s tokenizer, for Python evidence) now cover disjoint
  file-type scopes rather than overlapping, weaker/stronger implementations
  of the same scope — the shape that let them drift apart is gone, not
  merely patched around.
- `code_without_comments`'s bracket-depth fix benefits every existing and
  future consumer in `tests/`, not only this script — it was a latent
  correctness bug in shared, opt-in infrastructure, not something scoped
  narrowly to `check_open_work.py`.
- **What this still cannot see**, stated narrowly per the board's own
  "what this cannot see" section: a needle whose surrounding construct is
  neither a comment, a docstring, nor inside a bracket, but is still dead or
  unreachable code (e.g. behind `if False:`) reads as real code here, same
  as it always has. Tokenization proves the needle is *syntactically* code;
  it does not prove the code executes or is reachable. That is unchanged
  scope, not a new gap this ADR introduces.
- **Found by review, recorded rather than fixed:** `_is_docstring` still
  cannot tell a real module/class/function docstring from a bare
  string-literal EXPRESSION STATEMENT sitting elsewhere in a function body at
  depth 0 — e.g. `x = 1\n"needle"\nreturn x`. Both are "the first STRING
  token after an NL/NEWLINE/INDENT/DEDENT at bracket depth 0"; nothing here
  additionally checks that the statement is the FIRST one in its
  module/class/def body. Reproduced in isolation; none of the board's 17
  live needles sits in a bare string statement (each is a real assignment,
  call, or dict-literal line), so this does not affect any currently-pinned
  row. Narrowing this further would mean tracking each block's first
  statement, which is closer to a real parse than this tokenizer pass does
  anywhere else — left as a known gap rather than built speculatively for a
  case with no live instance.
