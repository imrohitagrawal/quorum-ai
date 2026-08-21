"""No served surface may caption the tally as models agreeing with each other.

``agreement.aligned`` answers "is this model's opening position represented in
the final answer?" — for a minority opener, literally a 4-gram containment of
its opening against the model-written final synthesis
(``synthesis_consensus._opening_reflected_in_final``). It was captioned
"N of M models aligned", a claim about the models agreeing with EACH OTHER, and
a production run served "0 of 4 models aligned — the rest are preserved as
disagreement below." directly above a Consensus section reading "All four define
the two models oppositely… All agree seat-based is the more predictable revenue
model."

Five surfaces read the tally: the verdict band's headline, the band's ring, the
Agreement card, the Copy summary and the Markdown export. They carry their own
grammar, which is fine; what they must not carry is their own WORDING of what
the number means — #128 was exactly that, and the file a user kept disagreed
with the screen they exported it from.

Structural, over ``app.js`` with whole-line ``//`` comments stripped, following
``tests/unit/test_agreement_clause_honesty.py``.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_JS = REPO_ROOT / "src" / "product_app" / "static" / "app.js"


def _code_only(path: Path) -> str:
    """``path``'s JS with whole-line ``//`` comments dropped.

    The comments explaining this change quote the old caption verbatim, so a
    naive count would find the very strings the test exists to prove are gone.
    """
    return "".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines(keepends=True)
        if not line.lstrip().startswith("//")
    )


def test_no_served_string_captions_the_tally_as_models_agreeing() -> None:
    """The negative, and its three positive partners (rule 7).

    What turns it red: re-word any surface back to "models aligned", or set the
    ring label back to "agree".
    """
    raw = APP_JS.read_text(encoding="utf-8")
    code = _code_only(APP_JS)

    # THE NEGATIVE.
    assert code.count("models aligned") == 0
    assert code.count('"agree"') == 0

    # POSITIVE PARTNER 1 — the comments that explain the change still quote the
    # old caption, which proves ``_code_only`` removed something and that the
    # zeros above are not measuring an empty or unreadable file.
    assert raw.count("models aligned") == 5
    assert raw.count('"agree"') == 1

    # POSITIVE PARTNER 2 — the tally is still RENDERED. Without this, deleting
    # every agreement surface would satisfy the negative above.
    assert code.count("${aligned} of ${total}") == 6
    assert code.count("${ctx.aligned} of ${ctx.total}") == 2

    # POSITIVE PARTNER 3 — the replacement caption is one shared constant, used
    # by every surface rather than re-typed: 1 declaration + 8 uses.
    assert code.count("CARRIED_INTO_FINAL") == 9
    assert code.count('const CARRIED_INTO_FINAL = "carried into the final answer";') == 1

    # The ring's own two-word caption moved with the rest.
    assert code.count('"result-ring-label", "carried"') == 1
