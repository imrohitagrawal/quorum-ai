"""Length discipline for the synthesis pipeline.

The synthesis was previously producing wall-of-caveats output on
high-stakes queries (see Defect 4 in ``docs/SYNTHESIS_AUDIT.md``).
PR-2 introduces a soft cap on each section's character count:

* ``DEFAULT_SECTION_MAX_CHARS = 280`` for the four short sections
  (Consensus, Disagreement, Source support, Uncertainty).
* ``RECOMMENDATION_MAX_CHARS = 420`` for the Recommendation
  section, which must also carry the mandatory decision-support
  caveat.

The cap is a soft cap: the LLM prompt says "be concise" and the
post-processing truncates with an ellipsis if it exceeds. The
recommendation caveat is protected from truncation — if the LLM
output ends with the verbatim decision-support sentence it is left
intact; if the caveat is missing, it is appended after the
truncation.

The module is pure logic (no I/O, no configuration). The audit
acknowledges that the cap is a heuristic; a future revision may
tighten the budget further if observed outputs still run long.
"""

from __future__ import annotations

import re

#: Soft cap for the four short sections.
DEFAULT_SECTION_MAX_CHARS = 280

#: Soft cap for the Recommendation section, which must also carry
#: the mandatory decision-support caveat.
RECOMMENDATION_MAX_CHARS = 420

#: The mandatory decision-support caveat substring. The verbatim
#: sentence in ``HIGH_STAKES_NOTICE_FRAGMENT`` is the long form;
#: we key on a substring to be robust to comma insertions and
#: minor rephrasings.
_CAVEAT_MARKER = "decision support only"

#: Sentence-boundary pattern used by ``truncate_section`` to find
#: the last "natural" stop. We treat ".", "!", "?" followed by a
#: space as a sentence end.
_SENTENCE_BOUNDARY = re.compile(r"[.!?] ")

#: The trailing ellipsis added to truncated sections. Single
#: character so the total length stays within the cap.
_ELLIPSIS = "…"


def truncate_section(text: str, *, max_chars: int) -> str:
    """Truncate ``text`` to at most ``max_chars`` characters.

    The truncation is "soft" — we try to find the last sentence
    boundary within the budget and truncate there. If no
    sentence boundary exists, we hard-truncate and append
    ``"…"``.

    If ``text`` is already within the budget, it is returned
    unchanged.
    """
    if not text:
        return text
    if len(text) <= max_chars:
        return text

    # We need at least one character of ellipsis, so the budget
    # for the body is max_chars - 1.
    budget = max_chars - 1
    if budget <= 0:
        return _ELLIPSIS

    # Look for the last sentence boundary (". ", "! ", "? ") at
    # or before the budget. We require the boundary character
    # PLUS the trailing space to be present in the kept portion
    # so the truncated output ends with a complete sentence
    # before the ellipsis.
    body = text[:budget]
    last_boundary = -1
    for match in _SENTENCE_BOUNDARY.finditer(body):
        # The position of the space after the boundary char.
        last_boundary = match.end()

    if last_boundary > 0:
        return body[:last_boundary].rstrip() + _ELLIPSIS
    return body.rstrip() + _ELLIPSIS


def truncate_recommendation(text: str) -> str:
    """Truncate the Recommendation section while protecting the
    decision-support caveat.

    The verbatim sentence the LLM prompt mandates is
    ``"This summary is decision support only and is not medical,
    legal, financial, safety, or regulated professional advice."``
    (see ``_RECOMMENDATION_PROMPT`` rule 1 in synthesis.py and
    ``HIGH_STAKES_NOTICE_FRAGMENT``).

    The function's contract:
    * If the caveat is present (substring ``"decision support
      only"`` exists in the text), the text is truncated using
      ``truncate_section(max_chars=RECOMMENDATION_MAX_CHARS)``
      *before* the caveat. The caveat is left intact.
    * If the caveat is missing, the text is truncated and the
      full caveat sentence is appended.

    The "truncate before the caveat" rule prevents a long LLM
    output from dropping the mandatory disclaimer. The audit
    flagged that the templated recommendation can run to 258+
    characters on high-stakes queries; the 420-char cap is the
    application-level guarantee.
    """
    if not text:
        # Nothing to do. The orchestrator's templated branch
        # always emits a recommendation that includes the
        # caveat, so the empty case should not occur in
        # practice, but we handle it defensively.
        return _CaveatEnforcer.append_if_missing("")

    caveat_present = _CAVEAT_MARKER in text.lower()

    # Path A: caveat already present. Truncate the body before
    # the caveat so the caveat is preserved.
    if caveat_present:
        return _truncate_with_caveat_present(text)

    # Path B: caveat missing. Truncate the body so body +
    # caveat together stay within the cap, then append.
    caveat_len = len(_CaveatEnforcer.FULL_CAVEAT)
    body_budget = RECOMMENDATION_MAX_CHARS - caveat_len - 1
    if body_budget <= 0:
        return _CaveatEnforcer.FULL_CAVEAT
    if len(text) <= body_budget:
        return _CaveatEnforcer.append_if_missing(text)
    body_truncated = truncate_section(text, max_chars=body_budget)
    return _CaveatEnforcer.append_if_missing(body_truncated)


def _truncate_with_caveat_present(text: str) -> str:
    """Truncate a recommendation that already contains the caveat.

    The caveat is preserved verbatim; the body up to the caveat
    is truncated to fit within the cap. We find the caveat
    position, then truncate the pre-caveat body so that the
    total length (body + ellipsis + caveat) stays under the cap.
    """
    caveat_idx = text.lower().find(_CAVEAT_MARKER)
    pre_caveat = text[:caveat_idx]
    caveat_onward = text[caveat_idx:]

    # If the full text is already within the cap, return as-is.
    if len(text) <= RECOMMENDATION_MAX_CHARS:
        return text

    # Otherwise truncate the pre-caveat body. We budget the body
    # so the total length (body + ellipsis + caveat + 2 spaces)
    # stays within the cap.
    body_budget = RECOMMENDATION_MAX_CHARS - len(caveat_onward) - 4
    if body_budget <= 0:
        # Caveat is too long by itself to fit with a body; the
        # cap can fit only the caveat.
        return caveat_onward.rstrip()

    body_truncated = truncate_section(pre_caveat, max_chars=body_budget)
    body_truncated = body_truncated.rstrip()
    if body_truncated.endswith(_ELLIPSIS):
        return body_truncated + "  " + caveat_onward.lstrip()
    return body_truncated + " " + _ELLIPSIS + "  " + caveat_onward.lstrip()


class _CaveatEnforcer:
    """Internal helper: ensure the decision-support caveat is
    present at the end of a recommendation string.

    The caveat is added with a leading space so the resulting
    sentence reads naturally. If the text already contains the
    caveat substring, it is returned unchanged.
    """

    #: The full caveat sentence. The orchestrator's templated
    #: branch emits this verbatim, and the LLM prompt's rule 1
    #: mandates it.
    FULL_CAVEAT = (
        "This summary is decision support only and is not medical, "
        "legal, financial, safety, or regulated professional advice."
    )

    @classmethod
    def append_if_missing(cls, text: str) -> str:
        if _CAVEAT_MARKER in text.lower():
            return text
        stripped = (text or "").rstrip()
        if not stripped:
            return cls.FULL_CAVEAT
        return stripped + " " + cls.FULL_CAVEAT
