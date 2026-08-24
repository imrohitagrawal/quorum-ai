"""A mutant may not be silenced in this repository. Issue #365, ADR-0069.

#365 asked for a way to record a mutant as proven-equivalent that could not
become a way to hide a real survivor. The answer ADR-0069 records is that there
is no such recording mechanism here at all: an equivalent mutant is removed from
the code, not excused. This module is the half of that decision that has teeth,
because **mutmut already ships a proof-free silencer and nothing was guarding
it**.

`# pragma: no mutate` (bare, or `block`/`start`/`end`/`function`) makes
`MutationVisitor._should_mutate_node` return False, so the `Mutation` object is
never created. The mutant does not survive, does not time out and is not
skipped — **it never exists**. Nothing lands in `.meta`, so `report()` counts
nothing, prints nothing, and the score's denominator silently shrinks. Measured
2026-08-25 on `synthesis_consensus.py`:

    no pragma : 11 mutants for _stance_majority_flags
    one pragma:  9 mutants          -> 2 silently removed

That is one comment, no proof, no review signal, and a gate that still reports a
clean percentage over a population somebody quietly made smaller. AGENTS.md
rule 14 already forbids the exact analogue — "never lower a threshold, add
`# pragma: no cover`, or delete a test to go green" — and this is the same move
against the mutation gate rather than the coverage one.

`[tool.mutmut]`'s `do_not_mutate` and `do_not_mutate_patterns` do the same thing
at file scope, so they are checked too.

GATE CHARTER
-----------
WHY THIS EXISTS: mutmut ships a one-line, proof-free way to delete a mutant from
the population, and nothing in this repo guarded it. #365 asked for an
equivalent-mutant mechanism that could not be turned into a silencer; building
one while leaving a cheaper silencer installed next to it would have raised the
cost of doing this honestly and not the cost of doing it dishonestly.

WHAT IT CANNOT SEE: intent, and anything outside `src/`. It cannot tell an
author hiding a survivor from one who copied the pragma out of mutmut's README —
it refuses both. A pragma in `tests/` or `scripts/` is invisible, which is
sound only because neither tree is mutated, so neither can silence a mutant.
It also cannot see the OTHER ways a population shrinks: a deselected marker
under `[tool.mutmut]` moves mutants to `no_tests` (already failed by the gate
itself), and `only_mutate` narrowing is deliberately allowed.

FALSE-POSITIVE COST: near zero, and bounded by construction. It fires only on a
real `# pragma:` COMMENT token whose text says `no mutate`, so the pragma named
in a string literal or in this docstring does not trip it — asserted, not
assumed, in `test_the_scanner_detects_a_pragma_that_is_really_there`. The cost
of a genuine hit is a conversation, which is the intended outcome.

WHEN TO REMOVE: when an equivalent mutant can be recorded with an executable,
machine-checked proof that the gate itself verifies — i.e. when the mechanism
ADR-0069 defers has actually been built and the population of equivalent mutants
is large enough to have justified it. At that point the honest path exists and
this blanket refusal should become "silence it only through that mechanism".
Also remove it if mutmut drops pragma support, which would make it dead code.

Turns red if: anyone adds a `# pragma: no mutate` under `src/`, or a
`do_not_mutate`/`do_not_mutate_patterns` key to `[tool.mutmut]`. Proven by
mutation — planting the pragma in a scratch copy of a real module is exactly
what `test_the_scanner_detects_a_pragma_that_is_really_there` does, so the
detector's bite is asserted on every run rather than claimed here.
"""

from __future__ import annotations

import io
import tokenize
import tomllib
from pathlib import Path

import pytest
from tests.repo_root import find_repo_root

#: Reads the repository's own tree, so it must resolve the REAL root rather than
#: mutmut's `./mutants/` copy — inside the copy `src/` carries one generated
#: `x_<name>__mutmut_N` variant per mutant and any census of it is meaningless
#: (#158). Deselected under mutmut for the same reason.
pytestmark = pytest.mark.repo_introspection

REPO_ROOT = find_repo_root(Path(__file__))
SOURCE_ROOT = REPO_ROOT / "src"

#: mutmut matches on the text after `# pragma:` containing `no mutate`
#: (`mutmut/mutation/pragma_handling.py`), which covers the bare form and the
#: `block` / `start` / `end` / `function` variants in one string.
PRAGMA_MARKER = "no mutate"

#: `[tool.mutmut]` keys that remove code from the mutated population wholesale
#: (`mutmut/configuration.py`). `only_mutate` is deliberately NOT here: it
#: NARROWS scope to `src/product_app/*.py` and is load-bearing (`pyproject.toml`
#: explains why), whereas these two SUBTRACT from whatever that scope selected.
SILENCING_CONFIG_KEYS = ("do_not_mutate", "do_not_mutate_patterns")


def _pragma_comments(source: str) -> list[tuple[int, str]]:
    """(line number, comment text) for every `# pragma: no mutate` COMMENT.

    Tokenised, never matched against raw line text: a raw-text scan would fire
    on the string literals in this module's own docstring and on any code that
    merely mentions the pragma, and rule 8 asks for structure over substrings.
    """
    found = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            text = token.string
            if "pragma:" in text and PRAGMA_MARKER in text.partition("pragma:")[2]:
                found.append((token.start[0], text.strip()))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # An unparseable file is a different failure and another gate's job;
        # failing here would blame this gate for someone else's syntax error.
        return []
    return found


def _mutmut_table() -> dict[str, object]:
    """`[tool.mutmut]`, PARSED — never sliced out of the file's raw text.

    `pyproject.toml` names `[tool.mutmut]` in a comment above the real table,
    so a text slice on that literal returns the comment. `tomllib` cannot make
    that mistake.
    """
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return dict(tomllib.load(handle)["tool"]["mutmut"])


def _source_files() -> list[Path]:
    return sorted(SOURCE_ROOT.rglob("*.py"))


def test_the_scan_actually_reads_a_real_population_of_files() -> None:
    """Anti-vacuity floor: "no pragma found" is trivially true over no files.

    Every assertion in this module is a negative one, and AGENTS.md rule 7 is
    explicit that a negative check needs a positive partner. If `src/` moves,
    is renamed, or `rglob` stops matching, this gate would report a clean sweep
    having read nothing at all.

    Turns red if: `SOURCE_ROOT` stops pointing at real Python source, or
    `find_repo_root` resolves to a tree without `src/`.
    """
    files = _source_files()
    assert len(files) >= 20, (
        f"the pragma scan found only {len(files)} Python files under "
        f"{SOURCE_ROOT} — it is not reading the source tree, so every "
        "'no pragma found' assertion below is vacuous"
    )
    assert any(path.read_text(encoding="utf-8").strip() for path in files), (
        "every file the scan found is empty; there is nothing to tokenise"
    )


def test_the_scanner_detects_a_pragma_that_is_really_there() -> None:
    """The POSITIVE PARTNER, and the detector's own bite proof.

    Without this, `_pragma_comments` returning `[]` unconditionally — a broken
    tokeniser, a typo in `PRAGMA_MARKER`, an `if False` — would make the gate
    below report a permanently clean tree. So the detector is shown finding a
    planted pragma in a real module's source, in memory, on every run. Nothing
    is written to disk and no tracked file is touched.

    It also pins the two ways a naive scanner gets this wrong: it must NOT fire
    on the pragma spelled inside a string literal (a raw-text `in` check does),
    and it must NOT fire on an unrelated pragma such as `# pragma: no cover`.

    Turns red if: `_pragma_comments` stops matching, or is loosened to raw-text
    matching — the string-literal case then produces a false positive.
    """
    real_module = SOURCE_ROOT / "product_app" / "synthesis_consensus.py"
    source = real_module.read_text(encoding="utf-8")
    assert not _pragma_comments(source), "the fixture module already carries a pragma"

    anchor = "    largest = max(sizes.values())"
    assert anchor in source, (
        "the anchor line this proof plants its pragma on has moved; re-point it "
        "rather than deleting the proof"
    )
    planted = source.replace(anchor, f"{anchor}  # pragma: no mutate", 1)
    hits = _pragma_comments(planted)
    assert len(hits) == 1, f"the scanner missed a planted pragma: {hits}"
    assert PRAGMA_MARKER in hits[0][1]

    # A raw-text scan fires on both of these. A tokenised one fires on neither.
    assert not _pragma_comments('X = "# pragma: no mutate"\n'), (
        "the scanner fired on a pragma inside a STRING literal; it is matching "
        "raw text rather than comment tokens"
    )
    assert not _pragma_comments("X = 1  # pragma: no cover\n"), (
        "the scanner fired on `# pragma: no cover`, which is a different tool "
        "and a different decision"
    )


def test_no_source_file_silences_a_mutant_with_a_pragma() -> None:
    """The gate itself. ADR-0069.

    Turns red if: a `# pragma: no mutate` comment is added anywhere under
    `src/`. Its partner above proves the scanner can see one.
    """
    offenders = {
        path.relative_to(REPO_ROOT).as_posix(): _pragma_comments(path.read_text(encoding="utf-8"))
        for path in _source_files()
    }
    offenders = {path: hits for path, hits in offenders.items() if hits}

    assert offenders == {}, (
        "a `# pragma: no mutate` under src/ deletes mutants from the "
        "population before they are ever counted — the mutation gate then "
        "reports a clean score over a set someone quietly made smaller, with "
        "no proof and no review signal.\n"
        f"  {offenders}\n"
        "If the mutant is a real test gap, write the test. If it is EQUIVALENT "
        "— it cannot change behaviour for any input — change the code so the "
        "mutant is not generated, the way ADR-0069 removed the two in "
        "`_stance_majority_flags`. Silencing it is neither."
    )


def test_the_mutmut_config_does_not_subtract_from_the_mutated_population() -> None:
    """The same silencing, one level up, in `[tool.mutmut]`.

    `do_not_mutate` / `do_not_mutate_patterns` remove whole files or patterns
    from what mutmut mutates. `only_mutate` is deliberately allowed: it narrows
    the scope to `src/product_app/*.py` and `pyproject.toml` records why.

    Turns red if: either key is added to `[tool.mutmut]`. The partner is
    `test_the_config_check_is_reading_the_real_mutmut_table` below.
    """
    table = _mutmut_table()

    present = [key for key in SILENCING_CONFIG_KEYS if key in table]
    assert present == [], (
        f"[tool.mutmut] sets {present}, which subtracts from the population "
        "the mutation gate scores. That is the file-scope form of "
        "`# pragma: no mutate` and ADR-0069 rejects it for the same reason."
    )


def test_the_config_check_is_reading_the_real_mutmut_table() -> None:
    """POSITIVE PARTNER for the check above — "key absent" is trivially true
    over an empty table, which is what a renamed or unparsed table produces.

    This caught a real defect in the first version of this module, which is why
    it is here rather than being assumed: the check sliced the file on the
    literal `[tool.mutmut]`, and `pyproject.toml` mentions that string in a
    COMMENT several lines above the real table. The slice returned the comment
    prose, `do_not_mutate` was trivially "absent" from it, and the gate above
    passed while reading nothing. Parsing the TOML removes the whole class —
    structure over substrings, AGENTS.md rule 8.

    Turns red if: `[tool.mutmut]` is renamed or removed, or the loaded table
    stops carrying the keys known to be in it.
    """
    table = _mutmut_table()
    assert "only_mutate" in table, (
        "the loaded [tool.mutmut] table does not contain `only_mutate`, which "
        "is known to be in it — the check above is not reading the real table"
    )
    assert "source_paths" in table, "the loaded table is missing `source_paths`"
