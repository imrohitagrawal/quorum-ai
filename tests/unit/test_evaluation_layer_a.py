"""Layer-A deterministic evaluation: markers, refusal, signals, composite.

Every test here is hermetic and performs zero I/O.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from decimal import Decimal
from pathlib import Path

import pytest

from product_app.debate import AgreementSummary
from product_app.evaluation import (
    LAYER_A_WEIGHTS,
    citation_marker_census,
    citation_marker_grounding,
    detect_refusal,
    evaluate_layer_a,
    extract_citation_markers,
    presentation_confidence,
)
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
    SourceReference,
)
from product_app.synthesis import (
    FinalSynthesis,
    SynthesisQualityChecks,
    SynthesisStatus,
)

_LOADER_PATH = Path(__file__).resolve().parent.parent / "evals" / "corpus" / "loader.py"
_spec = importlib.util.spec_from_file_location("s2_corpus_loader", _LOADER_PATH)
assert _spec is not None and _spec.loader is not None
_corpus = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("s2_corpus_loader", _corpus)
_spec.loader.exec_module(_corpus)

REAL_URL = "https://pages.nist.gov/800-63-3/sp800-63b.html"
OTHER_URL = "https://www.rfc-editor.org/rfc/rfc6238"
THIRD_URL = "https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html"


def _source(url: str = REAL_URL, *, is_fallback: bool = False) -> SourceReference:
    return SourceReference(
        title="A source",
        url=url,
        provider=ProviderPath.OPENROUTER_SEARCH,
        is_fallback=is_fallback,
    )


def _answer(
    *,
    slot: int = 1,
    text: str = "An answer with a claim [1].",
    sources: list[SourceReference] | None = None,
    status: InitialAnswerStatus = InitialAnswerStatus.COMPLETED,
    path: ProviderPath = ProviderPath.OPENROUTER_SEARCH,
) -> InitialModelAnswer:
    resolved = [_source()] if sources is None else sources
    return InitialModelAnswer(
        slot_number=slot,
        model_id=f"vendor/model-{slot}",
        display_name=f"Model {slot}",
        answer_text=text,
        sources=resolved,
        provider_attempt_order=[path],
        provider_path=path,
        fallback_used=any(s.is_fallback for s in resolved),
        status=status,
        latency_ms=100,
        citation_coverage=CitationCoverage(
            material_claim_count=2,
            cited_claim_count=2 if resolved else 0,
            coverage_ratio=Decimal("1.00") if resolved else Decimal("0"),
            target_met=bool(resolved),
        ),
    )


def _synthesis(
    *,
    false_consensus_preserved: bool = False,
    decision_support: bool = True,
    high_stakes_required: bool = False,
    high_stakes_notice: str | None = None,
    uncertainty: str = "The panel could not establish the long-run effect.",
    consensus: str = "The panel agrees on the mechanism.",
) -> FinalSynthesis:
    return FinalSynthesis(
        status=SynthesisStatus.COMPLETED,
        consensus=consensus,
        disagreement="No material disagreement.",
        source_support="Both sources carried the load.",
        uncertainty=uncertainty,
        recommendation="Treat this as decision support, not a decision.",
        high_stakes_notice=high_stakes_notice,
        citation_coverage=CitationCoverage(
            material_claim_count=8,
            cited_claim_count=4,
            coverage_ratio=Decimal("0.50"),
            target_met=False,
        ),
        quality_checks=SynthesisQualityChecks(
            citation_coverage_target_met=False,
            false_consensus_preserved=false_consensus_preserved,
            decision_support_framing_present=decision_support,
            high_stakes_warning_required=high_stakes_required,
        ),
    )


def _grounding(texts: list[str], sources: list[SourceReference]) -> float | None:
    """Run ``citation_marker_grounding`` with one scope per text.

    The engine scopes ordinals per answer; these unit cases each describe a
    single block of prose against a single bibliography, which is exactly
    one scope per text.
    """
    return citation_marker_grounding(scopes=[(text, sources) for text in texts])


# --------------------------------------------------------------------------
# Marker grammar
# --------------------------------------------------------------------------


def test_numeric_bracket_markers_are_extracted_individually() -> None:
    assert extract_citation_markers("A claim [1] and another [2, 3].") == ["1", "2", "3"]


def test_markdown_link_markers_are_extracted_as_urls() -> None:
    text = f"See [NIST SP 800-63B]({REAL_URL}) for the wording."
    assert extract_citation_markers(text) == [REAL_URL]


def test_link_text_is_never_mistaken_for_a_numeric_marker() -> None:
    """Markdown links are consumed before numeric scanning."""
    text = f"[RFC 6238]({OTHER_URL}) and a separate ordinal [2]."
    assert extract_citation_markers(text) == [OTHER_URL, "2"]


@pytest.mark.parametrize(
    "text",
    [
        "A bare URL https://example.org/paper is deliberately not a marker.",
        "Author-year style (Smith, 2020) is deliberately not a marker.",
        "A footnote caret ^1 is deliberately not a marker.",
        "The bracketed phrase [citation needed] is deliberately not a marker.",
        "An empty bracket [] is not a marker.",
    ],
)
def test_deliberately_unmatched_forms(text: str) -> None:
    assert extract_citation_markers(text) == []


# --------------------------------------------------------------------------
# citation_marker_grounding — the None vs 0.0 distinction
# --------------------------------------------------------------------------


def test_grounding_is_one_when_every_marker_resolves() -> None:
    grounding = _grounding(
        texts=[f"A claim [1] and [Source]({REAL_URL})."],
        sources=[_source(REAL_URL)],
    )
    assert grounding == pytest.approx(1.0)


def test_grounding_is_near_zero_when_markers_resolve_to_nothing() -> None:
    """The ORDINAL is what makes this 0.0, not the off-run link.

    ``[7]`` points at bibliography slot 7 of a one-entry bibliography, which
    Layer A can check with no I/O: it is resolvable-as-false. The off-run URL
    is excluded as unknown (see
    ``test_an_off_run_url_marker_is_unknown_not_unresolved``), so the
    denominator here is 1, not 2.
    """
    grounding = _grounding(
        texts=["Confident prose [7] with [a study](https://not-a-real.example/paper) behind it."],
        sources=[_source(REAL_URL)],
    )
    assert grounding == pytest.approx(0.0)


# --------------------------------------------------------------------------
# DEBT-011 part C — an off-run URL is UNKNOWN, not unresolved
# --------------------------------------------------------------------------


def test_an_off_run_url_marker_is_unknown_not_unresolved() -> None:
    """Layer A performs no I/O, so it cannot call an off-run URL fabricated.

    One resolving ordinal plus one off-run URL. If the URL were counted as
    unresolved the answer would be 0.5; it is excluded from BOTH numerator
    and denominator instead, so the answer is 1.0 over a denominator of 1.

    The engine cannot fetch. It therefore cannot distinguish an INVENTED URL
    from a real page a model knew but did not retrieve on this run, and
    scoring it zero would assert the former — an assumption dressed as a
    measurement. This is the same "None is unknown, not zero" doctrine that
    governs the ``None`` return, applied one level down.
    """
    grounding = _grounding(
        texts=["A claim [1] and [a page](https://not-a-real.example/paper)."],
        sources=[_source(REAL_URL)],
    )
    assert grounding == pytest.approx(1.0)


def test_a_run_whose_only_markers_are_off_run_urls_is_unknown_not_zero() -> None:
    """The RECORDED COST of the rule above, pinned so it cannot rot (DEBT-012).

    A run that cites nothing but invented URLs used to score 0.0 —
    ``unfaithful``/``high``. It now scores ``None``, which the classifiers
    read as *unknown*: ``partial``/``medium``. That is a real loss of
    detection and it is deliberate, because Layer A cannot tell an invented
    URL from an un-retrieved real one without a fetch. Recorded as DEBT-012;
    closing it needs URL liveness/support verification (a fetch or the
    Layer-B judge), not a threshold change.

    If a future change makes this ``0.0`` again, this test goes RED and
    DEBT-012 must be revisited rather than the rule quietly re-flipped.

    R2-S3: the ENGINE label is unchanged and still wrong; what closes the S3
    exposure is the presentation guard asserted below. Here the labels are
    already a warning (``partial``/``medium``), so the guard must NOT suppress
    them — it can only ever under-claim.
    """
    evaluation = evaluate_layer_a(
        initial_answers=[
            _answer(
                slot=slot,
                text="A confident claim [a study](https://not-a-real.example/paper).",
                sources=[_source(REAL_URL)],
            )
            for slot in (1, 2, 3, 4)
        ],
        final_synthesis=_synthesis(),
        agreement=AgreementSummary(aligned=4, total=4),
    )
    assert evaluation.signals.citation_marker_grounding is None
    assert evaluation.faithfulness_label == "partial"
    assert evaluation.hallucination_risk == "medium"
    assert evaluation.signals.unverifiable_marker_count == 4
    assert (
        presentation_confidence(
            evaluation.signals,
            faithfulness_label=evaluation.faithfulness_label,
            hallucination_risk=evaluation.hallucination_risk,
        )
        == "reportable"
    )


def test_a_link_whose_url_the_scan_rejects_cannot_launder_its_TEXT_into_an_ordinal() -> None:
    """Measured regression (adversarial review round 2), HIGH.

    Bounding the URL run to ``[^\\s)\\[\\]]{1,2000}`` for cost made TWO
    shapes stop matching: a URL containing a literal bracket (an unencoded
    query key, an IPv6 literal host) and a URL longer than 2000 characters.
    The comment on ``_MARKDOWN_LINK_RE`` claimed the failure direction was
    "a marker that goes UNCOUNTED rather than one that falsely resolves".
    Measured, it was the opposite whenever the link TEXT is numeric — the
    canonical ``[1](url)`` shape: the link did not match, so the removal
    pass left ``[1]`` standing and the ordinal scan read it as ordinal 1,
    which resolves against the run's first real source.

    Consequence, measured end to end: a wholly INVENTED URL citation scored
    grounding 1.0 → ``faithful``/``low`` (the maximum trust labels) instead
    of being EXCLUDED as unknown per part C / DEBT-012 — i.e. a silent
    bypass of the behaviour
    ``test_a_run_whose_only_markers_are_off_run_urls_is_unknown_not_zero``
    exists to pin, triggered by one unencoded bracket.
    """
    bracketed = "Rotation is deprecated [1](https://invented.example/r?filter[status]=open)."
    over_long = "Rotation is deprecated [1](https://invented.example/" + "b" * 2100 + ")."

    # Whatever the scan does with these URLs, the link TEXT is never an ordinal.
    assert "1" not in extract_citation_markers(bracketed)
    assert "1" not in extract_citation_markers(over_long)

    # ...so an off-run URL citation stays UNKNOWN rather than resolving.
    for text in (bracketed, over_long):
        assert _grounding(texts=[text], sources=[_source(REAL_URL)]) is None, text


def test_a_bracket_in_a_url_query_is_still_read_as_a_citation_marker() -> None:
    """The other half: the bracketed URL must still RESOLVE when it is real.

    Excluding brackets from the URL run silently dropped this marker
    entirely. Both halves matter — dropping it loses a real resolution,
    and dropping it while leaving the link text behind invents a false one.
    """
    on_run = "https://a.test/r?filter[status]=open"
    text = f"A claim [1]({on_run})."
    assert extract_citation_markers(text) == [on_run]
    assert _grounding(texts=[text], sources=[_source(on_run)]) == pytest.approx(1.0)


def test_an_out_of_range_ordinal_stays_in_the_denominator() -> None:
    """The asymmetry between an off-run URL and an out-of-range ordinal.

    An ordinal names a POSITION in a bibliography Layer A holds in memory.
    ``[9]`` against a one-entry bibliography points at a slot that
    demonstrably does not exist on this run — resolvable-as-FALSE with no
    I/O whatsoever. It is not "unknown", and excluding it would gut the
    fabrication signal.
    """
    grounding = _grounding(texts=["A claim [9]."], sources=[_source(REAL_URL)])
    assert grounding == pytest.approx(0.0)


def test_no_markers_at_all_is_unknown_not_zero() -> None:
    """A run that never claimed a citation has not fabricated one.

    This is the distinction the composite depends on: ``None`` means the
    signal is unknown and is EXCLUDED from the weighted composite, while
    ``0.0`` means markers were made and resolved to nothing, which is a
    real, punishable defect.
    """
    assert (
        _grounding(
            texts=["Plain prose with no citation markers whatsoever."],
            sources=[_source(REAL_URL)],
        )
        is None
    )


def test_fallback_sources_do_not_ground_a_marker() -> None:
    """A LOCAL-SIMULATION stub resolves nothing.

    The discriminator is the reserved ``example.test`` host the app's own
    stubs are minted under (``providers.LOCAL_SIMULATION_URL_PREFIX``), NOT
    the ``is_fallback`` flag — since issues #31/#32 that flag is also set on
    REAL pages returned by the Tavily web search (see
    ``test_a_real_web_search_source_grounds_even_though_it_is_flagged_fallback``).
    """
    assert _grounding(
        texts=["A claim [1]."],
        sources=[_source("https://example.test/local-demo/1", is_fallback=True)],
    ) == pytest.approx(0.0)


def _tavily_source(url: str) -> SourceReference:
    """A REAL page supplied by the Tavily supplement (providers.py:866).

    ``FALLBACK_SEARCH`` / ``is_fallback=True``, and a genuine URL — the exact
    shape a live run gets when the ``:online`` model returns no citations.
    """
    return SourceReference(
        title="A real page",
        url=url,
        provider=ProviderPath.FALLBACK_SEARCH,
        is_fallback=True,
    )


def _stub_source(slot: int = 1) -> SourceReference:
    """The fabricated stub, exactly as ``providers._fallback_sources`` mints it."""
    return SourceReference(
        title=f"Fallback search evidence for slot {slot}",
        url=f"https://example.test/local-demo/fallback/{slot}",
        provider=ProviderPath.FALLBACK_SEARCH,
        is_fallback=True,
    )


def test_an_ordinal_is_POSITIONAL_against_the_list_the_user_is_shown() -> None:
    """MEASURED defect (adversarial review round 3), HIGH.

    The ceiling used to be a COUNT of distinct non-fallback URLs while an
    ordinal is a POSITION in the source list the UI renders
    (``app.js::renderSourceList`` walks ``sources`` in order, stub rows
    included). The two disagree the moment a scope holds a stub or a
    duplicate row, and they disagreed in the UNSAFE direction: with
    ``[stub, real-a, real-b]`` the count ceiling was 2, so ``[1]`` — which
    points at the FABRICATED stub — resolved, while ``[3]`` — which points
    at a genuine source — did not.
    """
    sources = [_stub_source(), _source(REAL_URL), _source(OTHER_URL)]

    # [1] is the stub row: a fabricated placeholder grounds nothing.
    assert _grounding(texts=["Claim [1]."], sources=sources) == pytest.approx(0.0)
    # [2] and [3] point at genuine rows and must resolve.
    assert _grounding(texts=["Claim [2]."], sources=sources) == pytest.approx(1.0)
    assert _grounding(texts=["Claim [3]."], sources=sources) == pytest.approx(1.0)
    # [4] is past the end of the rendered list: resolvable-as-false.
    assert _grounding(texts=["Claim [4]."], sources=sources) == pytest.approx(0.0)


def test_a_duplicate_source_row_does_not_shift_the_ordinals_below_it() -> None:
    """The same positional rule, for the duplicate case.

    A scope listing one page twice renders three rows, so ``[3]`` names the
    third rendered row. Under the old distinct-URL count the ceiling was 2
    and the genuine third row scored as a fabrication.
    """
    sources = [_source(REAL_URL), _source(REAL_URL), _source(OTHER_URL)]
    assert _grounding(texts=["Claim [3]."], sources=sources) == pytest.approx(1.0)
    assert _grounding(texts=["Claim [4]."], sources=sources) == pytest.approx(0.0)


def test_a_real_web_search_source_grounds_even_though_it_is_flagged_fallback() -> None:
    """MEASURED defect (adversarial review round 3), HIGH — the live path.

    Since #31/#32 a slot whose ``:online`` call returned no citations gets a
    REAL Tavily web search attached, and every such source carries
    ``is_fallback=True`` while being a genuine page. Keying "grounds
    nothing" off that flag meant a fully live 4-model run whose every marker
    was correct against its own rendered bibliography scored grounding 0.0
    and was served ``unfaithful``/``high``.
    """
    tavily = [
        _tavily_source("https://pages.nist.gov/800-63-3/sp800-63b.html"),
        _tavily_source("https://owasp.org/www-project-asvs/"),
    ]
    text = (
        "Password length minimums should be at least 8 characters [1]. "
        "Composition rules are discouraged [2]. See "
        "[the primary text](https://pages.nist.gov/800-63-3/sp800-63b.html)."
    )
    evaluation = evaluate_layer_a(
        initial_answers=[
            _answer(slot=slot, text=text, sources=list(tavily)) for slot in (1, 2, 3, 4)
        ],
        final_synthesis=None,
        agreement=AgreementSummary(aligned=4, total=4),
    )
    assert evaluation.signals.citation_marker_grounding == pytest.approx(1.0)
    assert evaluation.faithfulness_label == "faithful"
    assert evaluation.hallucination_risk == "low"


def test_the_marker_census_separates_resolved_unresolved_and_unverifiable() -> None:
    """The census is the single source of truth for marker classification.

    The DEBT-012 laundering shape — one resolving ordinal beside 20 off-run
    URL markers, per slot, over four slots — is classified as 4 resolved,
    0 resolvable-as-false, 80 unverifiable. ``citation_marker_grounding`` is
    derived from ``resolved / resolvable`` and so is 1.0, VALUE unchanged.
    """
    fabricated = " ".join(
        f"[claim{i}](https://fabricated-{i}.example.org/paper)" for i in range(20)
    )
    scopes = [
        (f"Therapy reduces mortality by 42% [1]. {fabricated}", [_source(REAL_URL)])
        for _slot in range(4)
    ]
    census = citation_marker_census(scopes=scopes)
    assert census.resolved == 4
    assert census.unresolved == 0
    assert census.unverifiable == 80
    assert census.resolvable == 4
    # Value semantics of grounding are the census ratio, unchanged.
    assert citation_marker_grounding(scopes=scopes) == pytest.approx(4 / 4)


def test_unverifiable_marker_ratio_is_None_when_the_prose_has_no_markers_at_all() -> None:
    """``unverifiable_marker_ratio`` is ``None`` iff the run carried no markers.

    A run that never cited anything has no unverifiable markers to report a
    ratio OVER, which is distinct from a run whose markers were all resolvable
    (ratio 0.0).
    """
    evaluation = evaluate_layer_a(
        initial_answers=[
            _answer(
                slot=slot,
                text="Plain prose, no citation markers.",
                sources=[_source(REAL_URL)],
            )
            for slot in (1, 2, 3, 4)
        ],
        final_synthesis=None,
        agreement=AgreementSummary(aligned=4, total=4),
    )
    assert evaluation.signals.unverifiable_marker_count == 0
    assert evaluation.signals.unverifiable_marker_ratio is None


def test_one_off_run_url_beside_one_resolving_ordinal_is_already_indeterminate() -> None:
    """DOSE 1: the case a dominance cut misses; why D-1.4 is zero-tolerance.

    One fabricated off-run URL beside one resolving ordinal yields grounding
    1.0 → ``faithful``/``low`` (measured today), and its unverifiable RATIO is
    exactly 0.5 — BELOW a strict-majority cut. A dominance rule would pass this
    while failing the 20-link case. Zero-tolerance at the confident end catches
    both.
    """
    evaluation = evaluate_layer_a(
        initial_answers=[
            _answer(
                slot=slot,
                text="Effective [1]. [claim](https://fabricated.example.org/paper)",
                sources=[_source(REAL_URL)],
            )
            for slot in (1, 2, 3, 4)
        ],
        final_synthesis=None,
        agreement=AgreementSummary(aligned=4, total=4),
    )
    assert evaluation.signals.citation_marker_grounding == pytest.approx(1.0)
    assert evaluation.faithfulness_label == "faithful"
    assert evaluation.hallucination_risk == "low"
    # 4 unverifiable of 8 markers total → ratio exactly 0.5.
    assert evaluation.signals.unverifiable_marker_count == 4
    assert evaluation.signals.unverifiable_marker_ratio == pytest.approx(0.5)
    assert (
        presentation_confidence(
            evaluation.signals,
            faithfulness_label=evaluation.faithfulness_label,
            hallucination_risk=evaluation.hallucination_risk,
        )
        == "indeterminate"
    )


def test_the_corpus_confident_cases_keep_their_reportable_presentation() -> None:
    """The MEASURED under-claim cost, gated so it cannot rot (DEBT-012).

    On the frozen corpus the guard degrades 0 of the 2 confident cases: both
    the ``faithful-consensus`` (census 17 resolved / 3 resolvable-as-false /
    0 unverifiable) and ``preserved-polar-disagreement`` (11 / 2 / 0) cases
    carry ``unverifiable_marker_count == 0``, so their presentation stays
    ``reportable``. If a corpus edit introduces an off-run URL marker into a
    confident case this goes RED rather than silently under-claiming.
    """
    for case_id in ("faithful-consensus", "preserved-polar-disagreement"):
        case = _corpus.load_case(case_id)
        evaluation = evaluate_layer_a(
            initial_answers=case.initial_answers,
            final_synthesis=case.final_synthesis,
            agreement=case.agreement,
        )
        assert evaluation.signals.unverifiable_marker_count == 0, case_id
        assert (
            presentation_confidence(
                evaluation.signals,
                faithfulness_label=evaluation.faithfulness_label,
                hallucination_risk=evaluation.hallucination_risk,
            )
            == "reportable"
        ), case_id


def test_a_simulated_stub_cited_BY_URL_does_not_ground_either() -> None:
    """The URL arm of the same rule, which no test used to reach.

    ``test_fallback_sources_do_not_ground_a_marker`` exercises the ORDINAL
    path only, so the run-wide URL set's placeholder filter had NO oracle:
    deleting it left the whole suite green while a fabricated
    ``example.test`` stub cited by URL scored 1.0 → ``faithful``/``low``
    (measured, adversarial review round 3).

    A stub URL is not "unknown" the way an off-run URL is — the run holds
    the row and Layer A can see it is a placeholder — but it is excluded
    from the run-wide URL set, so the marker is treated as off-run and the
    scope reports ``None`` (unknown) rather than resolving.
    """
    stub = _stub_source()
    assert (
        _grounding(
            texts=[f"The answer is X, per [{stub.title}]({stub.url})."],
            sources=[stub],
        )
        is None
    )
    # ...while a REAL page cited by URL resolves, fallback flag or not.
    tavily = _tavily_source("https://owasp.org/www-project-asvs/")
    assert _grounding(
        texts=[f"The answer is X, per [ASVS]({tavily.url})."],
        sources=[tavily],
    ) == pytest.approx(1.0)


def test_a_nested_bracket_or_a_newline_in_link_TEXT_cannot_launder_an_ordinal() -> None:
    """MEASURED defect (adversarial review round 3), HIGH.

    Round 2 fixed the case where the link's URL failed to parse by removing
    the link SHAPE independently — and called that "TRUE BY CONSTRUCTION".
    It was not: both the extraction and the removal pattern bounded the link
    TEXT with ``[^\\]\\n]``, so a text containing a nested ``]`` or a newline
    matched NEITHER. The shape survived the removal pass and the ordinal
    scan read the surviving ``[1]`` as ordinal 1, which resolves against the
    scope's own real bibliography: a wholly fabricated URL citation scored
    grounding 1.0 → ``faithful``/``low`` instead of being EXCLUDED as
    unknown (DEBT-012).
    """
    fake = "https://invented.example/totally-fake"
    for text in (
        f"The rate is 41% [[1]]({fake}).",
        f"The rate is 41% [see [1]]({fake}).",
        f"The rate is 41% [1\n]({fake}).",
    ):
        assert "1" not in extract_citation_markers(text), text
        assert _grounding(texts=[text], sources=[_source(REAL_URL)]) is None, text


def test_a_nested_bracket_link_to_a_REAL_page_still_resolves_as_a_URL() -> None:
    """The other half: widening the shape must not drop a genuine marker.

    ``[[1]](url)`` is ordinary provider output (a bracketed ordinal rendered
    as the link text). Its URL must still be extracted and resolved, or the
    fix would trade a false resolution for a lost one.
    """
    text = f"The rate is 41% [[1]]({REAL_URL})."
    assert extract_citation_markers(text) == [REAL_URL]
    assert _grounding(texts=[text], sources=[_source(REAL_URL)]) == pytest.approx(1.0)


def test_a_four_digit_bracket_is_not_read_as_an_ordinal_marker() -> None:
    """The three-digit bound on ``_ORDINAL_MARKER_RE``, which had no oracle.

    A four-digit bracket in provider prose is a year or a line number far
    more often than a citation. Widening the bound to ``\\d{1,4}`` left the
    eval/layer-A/decoupling/properties suites fully green (measured,
    adversarial review round 3) while a bracketed year became an ordinal
    that can never resolve and dragged grounding down — the FALSE-ACCUSATION
    direction: three years plus one real ordinal scored 0.25 →
    ``unfaithful``/``high``.
    """
    text = "The rule took effect [2024] and is documented [1]."
    assert extract_citation_markers(text) == ["1"]
    assert _grounding(texts=[text], sources=[_source(REAL_URL)]) == pytest.approx(1.0)
    # ...and the three-digit form is still a marker.
    assert extract_citation_markers("A claim [999].") == ["999"]


def test_one_resolving_ordinal_launders_many_off_run_urls_to_maximum_trust() -> None:
    """The OTHER HALF of the DEBT-012 cost, measured and pinned (round 3).

    DEBT-012 recorded only the URL-ONLY case ("scores unknown rather than
    fabrication"), which reads conservative. Measured, the MIXED case is the
    opposite direction: because an off-run URL leaves the DENOMINATOR
    entirely, fabricated URL citations cannot dilute grounding at all, so
    ONE resolving ordinal carries the run to the MAXIMUM trust labels no
    matter how many invented URLs sit beside it. Under the pre-part-C
    counting the same run measured 0.0476 → ``unfaithful``/``high``.

    This asserts TODAY'S behaviour so the cost cannot silently rot. Closing
    it needs a URL oracle (a fetch or the Layer-B judge), not a threshold
    edit — capping grounding once excluded markers dominate would need a
    calibrated cut, which FS-6 defers to the S4 golden set.

    R2-S3: the ENGINE label is unchanged and still wrong; what closes the S3
    exposure is the presentation guard asserted below — the laundering shape
    now carries a measurable ``unverifiable_marker_count`` and its confident
    labels are downgraded to ``indeterminate`` for presentation.
    """
    fabricated = " ".join(
        f"[claim{i}](https://fabricated-{i}.example.org/paper)" for i in range(20)
    )
    evaluation = evaluate_layer_a(
        initial_answers=[
            _answer(
                slot=slot,
                text=f"Therapy reduces mortality by 42% [1]. {fabricated}",
                sources=[_source(REAL_URL)],
            )
            for slot in (1, 2, 3, 4)
        ],
        final_synthesis=None,
        agreement=AgreementSummary(aligned=4, total=4),
    )
    assert evaluation.signals.citation_marker_grounding == pytest.approx(1.0)
    assert evaluation.faithfulness_label == "faithful"
    assert evaluation.hallucination_risk == "low"
    assert evaluation.signals.unverifiable_marker_count == 80
    assert evaluation.signals.unverifiable_marker_ratio == pytest.approx(80 / 84)
    assert (
        presentation_confidence(
            evaluation.signals,
            faithfulness_label=evaluation.faithfulness_label,
            hallucination_risk=evaluation.hallucination_risk,
        )
        == "indeterminate"
    )


def test_run_wholly_refused_needs_EVERY_substantive_slot_not_almost_every() -> None:
    """The unanimity in ``run_wholly_refused`` had no oracle at all.

    Relaxing ``refusals == len(completed)`` to ``>= len(completed) - 1`` left
    all 1092 tests green (measured, adversarial review round 3) while
    flipping the persisted, served signal to True on a run where one slot
    genuinely answered. The two existing assertions on the computed value
    are both ``is False`` on runs with ZERO refusals, which the mutant also
    satisfies; nothing distinguished 3-of-4 from 4-of-4.
    """
    decline = "I cannot help with that request."
    three_of_four = evaluate_layer_a(
        initial_answers=[
            _answer(slot=1, text=decline),
            _answer(slot=2, text=decline),
            _answer(slot=3, text=decline),
            _answer(slot=4, text="The mechanism is well documented [1]."),
        ],
        final_synthesis=None,
        agreement=AgreementSummary(aligned=1, total=4),
    )
    assert three_of_four.signals.refusal_detected is True
    assert three_of_four.signals.run_wholly_refused is False

    four_of_four = evaluate_layer_a(
        initial_answers=[_answer(slot=slot, text=decline) for slot in (1, 2, 3, 4)],
        final_synthesis=None,
        agreement=AgreementSummary(aligned=1, total=4),
    )
    assert four_of_four.signals.run_wholly_refused is True


def test_the_ordinal_ceiling_is_the_LENGTH_of_the_scopes_rendered_list() -> None:
    """Replaces ``test_ordinal_ceiling_is_the_count_of_DISTINCT_real_sources``.

    That test asserted the ceiling was the count of DISTINCT non-fallback
    URLs, on a stated premise that is no longer true of the code: it said
    "``evaluate_layer_a`` concatenates every slot's sources with no dedup,
    so four models citing the SAME three pages hand this function a
    12-element list". Since DEBT-011 part B the scopes are PER ANSWER
    (``scopes = [(a.answer_text, a.sources) for a in initial_answers]``), so
    a 12-row scope can only be one answer that really lists 12 rows — and
    the UI renders all 12, in order.

    Measured (adversarial review round 3), the distinct-URL count was
    unsafe, not conservative: against ``[stub, real-a, real-b]`` it resolved
    the ordinal pointing at the FABRICATED stub and refused the one pointing
    at a genuine source
    (``test_an_ordinal_is_POSITIONAL_against_the_list_the_user_is_shown``).
    The property this test was protecting — that one slot's ordinals cannot
    borrow another slot's bibliography — is per-SCOPE, not per-URL, and is
    covered by ``test_an_ordinal_is_not_grounded_by_another_slots_sources``
    and ``test_fabricated_ordinals_do_not_resolve_against_a_pooled_run_bibliography``.

    The COST of the change, recorded honestly: a scope that lists one page
    12 times now resolves ordinals 1-12. Each of those ordinals does name a
    row the user is shown, so it is not a fabrication — but a duplicate-rich
    bibliography is a wider ceiling than a distinct-URL count would give.
    """
    duplicated = [_source(REAL_URL), _source(OTHER_URL), _source(THIRD_URL)] * 4
    assert len(duplicated) == 12
    grounding = _grounding(
        texts=["Claim [1]. Claim [5]. Claim [9]. Claim [12]. Claim [13]."],
        sources=duplicated,
    )
    assert grounding == pytest.approx(0.8)


def test_an_ordinal_is_not_grounded_by_another_slots_sources() -> None:
    """Slot 1's numbering indexes slot 1's OWN bibliography.

    This test used to fabricate ``[9]`` against a run with two distinct
    sources — so it passed on the run-level ceiling and asserted nothing
    about the property in its name. ``[2]`` is the case that actually tests
    it: slot 1 has exactly ONE source, so ``[2]`` is unresolvable in slot 1's
    prose no matter what slot 2 found.
    """
    slot_one = _answer(slot=1, text="Slot one claims [2].", sources=[_source(REAL_URL)])
    slot_two = _answer(slot=2, text="Slot two is plain prose.", sources=[_source(OTHER_URL)])
    evaluation = evaluate_layer_a(
        initial_answers=[slot_one, slot_two],
        final_synthesis=None,
        agreement=AgreementSummary(aligned=2, total=2),
    )
    assert evaluation.signals.citation_marker_grounding == pytest.approx(0.0)


def test_fabricated_ordinals_do_not_resolve_against_a_pooled_run_bibliography() -> None:
    """The production source layout, not the corpus one.

    In a live run each model searches independently and returns DIFFERENT
    pages, so the run-level distinct-URL count is roughly four times any one
    slot's bibliography. Here four slots hold three sources each and the run
    holds eight distinct URLs; every slot then cites ordinals 4-8. Under a
    run-level ceiling of 8 all of them "resolve" and the run scores
    ``faithful`` / ``low``. Against each answer's own bibliography (ceiling
    3) none of them resolve.
    """
    urls = [f"https://example.org/page-{n}" for n in range(1, 9)]
    per_slot = [(1, 2, 3), (1, 2, 4), (3, 5, 6), (6, 7, 8)]
    answers = [
        _answer(
            slot=slot,
            text="A confident claim [4][5][6][7][8].",
            sources=[_source(urls[n - 1]) for n in picks],
        )
        for slot, picks in enumerate(per_slot, start=1)
    ]
    distinct = {url for picks in per_slot for url in (urls[n - 1] for n in picks)}
    assert len(distinct) == 8

    evaluation = evaluate_layer_a(
        initial_answers=answers,
        final_synthesis=None,
        agreement=AgreementSummary(aligned=4, total=4),
    )
    assert evaluation.signals.citation_marker_grounding == pytest.approx(0.0)
    assert evaluation.faithfulness_label == "unfaithful"
    assert evaluation.hallucination_risk == "high"


def test_a_url_marker_still_resolves_against_any_real_source_on_the_run() -> None:
    """URLs are self-identifying; ordinals are positional.

    An ordinal only means something relative to one bibliography, so it is
    scoped to its own answer. A URL NAMES the page, so a slot that links a
    page another slot retrieved is pointing at a document the run really
    holds — that is grounded, and scoping URLs per-answer would punish it.
    """
    slot_one = _answer(slot=1, text=f"Slot one links [a page]({OTHER_URL}).", sources=[])
    slot_two = _answer(slot=2, text="Slot two is plain prose.", sources=[_source(OTHER_URL)])
    evaluation = evaluate_layer_a(
        initial_answers=[slot_one, slot_two],
        final_synthesis=None,
        agreement=AgreementSummary(aligned=2, total=2),
    )
    assert evaluation.signals.citation_marker_grounding == pytest.approx(1.0)


def test_a_synthesis_ordinal_never_resolves() -> None:
    """DEBT-011 part B. The synthesis has no bibliography AT ALL.

    This test previously asserted the OPPOSITE — that a synthesis ``[2]``
    resolves against the pooled run bibliography — on the argument that the
    pooled list was "the only defensible ceiling". The argument was wrong in
    a measurable way: the pooled list is the WIDEST ceiling on the run, no
    numbered source list for the synthesis is ever shown to a user, and an
    in-range ordinal against a bibliography nobody can see is not evidence
    of anything (R-4, measured: an invented ``[10] [11] [12]`` scored
    grounding 1.0 and was served ``faithful``/``low``).

    The honest ceiling is 0. Two slots with one distinct source each; the
    synthesis ``[2]`` resolves against nothing, and so would ``[1]``.
    """
    slot_one = _answer(slot=1, text="Slot one is plain prose.", sources=[_source(REAL_URL)])
    slot_two = _answer(slot=2, text="Slot two is plain prose.", sources=[_source(OTHER_URL)])
    for ordinal in ("[1]", "[2]"):
        evaluation = evaluate_layer_a(
            initial_answers=[slot_one, slot_two],
            final_synthesis=_synthesis(consensus=f"The panel agrees {ordinal}."),
            agreement=AgreementSummary(aligned=2, total=2),
        )
        assert evaluation.signals.citation_marker_grounding == pytest.approx(0.0), ordinal


def test_a_synthesis_url_marker_still_resolves_against_the_run() -> None:
    """Part B narrows ORDINALS only. A URL is self-identifying.

    The synthesis is passed an empty source list, but the run-wide URL set is
    built from the ANSWER scopes, so a synthesis linking a page the run
    actually retrieved is still grounded. Without this test, "pass the
    synthesis an empty list" could silently be implemented as "the synthesis
    grounds nothing".
    """
    slot_one = _answer(slot=1, text="Slot one is plain prose.", sources=[_source(REAL_URL)])
    evaluation = evaluate_layer_a(
        initial_answers=[slot_one],
        final_synthesis=_synthesis(consensus=f"The panel agrees, see [the page]({REAL_URL})."),
        agreement=AgreementSummary(aligned=1, total=1),
    )
    assert evaluation.signals.citation_marker_grounding == pytest.approx(1.0)


def test_grounding_is_none_when_there_are_no_texts() -> None:
    assert _grounding(texts=[], sources=[_source()]) is None


def test_a_run_with_no_markers_is_not_punished_like_one_that_fabricated_them() -> None:
    """The end-to-end form of the same distinction, at composite level."""
    silent = evaluate_layer_a(
        initial_answers=[_answer(text="Plain prose with no markers at all.")],
        final_synthesis=_synthesis(),
        agreement=AgreementSummary(aligned=1, total=1),
    )
    fabricating = evaluate_layer_a(
        initial_answers=[_answer(text="Prose with a fabricated marker [9].")],
        final_synthesis=_synthesis(),
        agreement=AgreementSummary(aligned=1, total=1),
    )
    assert silent.signals.citation_marker_grounding is None
    assert fabricating.signals.citation_marker_grounding == pytest.approx(0.0)

    from product_app.evaluation import build_trust_score

    silent_composite = build_trust_score(silent).diagnostics.layer_a_composite_unverified
    fabricating_composite = build_trust_score(fabricating).diagnostics.layer_a_composite_unverified
    assert silent_composite > fabricating_composite
    # The silent run is not credited for grounding either — it is simply
    # excluded, so its composite is the renormalised sum of what IS known.
    assert all(
        contribution.signal != "citation_marker_grounding"
        for contribution in build_trust_score(silent).diagnostics.contributions
    )


# --------------------------------------------------------------------------
# marker extraction: cost, not just correctness
# --------------------------------------------------------------------------

#: An UNTERMINATED markdown link opener, repeated. Each opener's URL run has
#: no closing ``)``, so a URL pattern that can scan past the next ``[``
#: rescans the rest of the document once per opener — O(n^2).
_UNTERMINATED_OPENER = "[x](http://" + "a" * 50

#: The same shape with a BRACKET inside the URL run. Round 1 bounded the run
#: by EXCLUDING ``[``/``]``, which made a failing opener stop at the next
#: ``[`` — and was unsound (see
#: ``test_a_link_whose_url_the_scan_rejects_cannot_launder_its_TEXT_into_an_ordinal``).
#: Brackets are allowed in the run again, so the cost gate must cover the
#: payload that exclusion used to be the defence against: here the run can
#: only be stopped by the possessive bound itself.
_BRACKETED_UNTERMINATED_OPENER = "[x](http://a.test/?f[" + "a" * 50

#: Round 3 replaced the two link REGEXES with a bracket-balanced scan
#: (``_scan_links``), because no fixed regex can consume a nested link text
#: at arbitrary depth. A balanced scan has a different cost profile from a
#: regex — a Python loop over bracket positions plus a stack — so the gate
#: carries the payloads that stress THAT: an unbounded run of openers with
#: no closer (stack growth, no shape ever completes) and an unbounded run of
#: closers with no opener (pop on an empty stack).
_NESTED_OPENER = "[[[[1"
_UNMATCHED_CLOSER = "]]]]"


@pytest.mark.env_oracle
@pytest.mark.parametrize(
    "opener",
    [
        _UNTERMINATED_OPENER,
        _BRACKETED_UNTERMINATED_OPENER,
        _NESTED_OPENER,
        _UNMATCHED_CLOSER,
    ],
    ids=["plain", "bracketed", "nested-openers", "unmatched-closers"],
)
@pytest.mark.parametrize("openers", [2000, 4000, 8000])
def test_marker_extraction_stays_linear_in_unterminated_link_openers(
    openers: int,
    opener: str,
) -> None:
    """Measured (adversarial review round 1): this was quadratic.

    ``[x](http://aaa…`` repeated, with no closing paren, cost 0.7 / 2.8 /
    12.4 / 51.5 s at 61 / 122 / 244 / 488 KB — an exact 4x per doubling.
    ``citation_marker_grounding`` is recomputed on EVERY read of a run (the
    result projection re-evaluates rather than reading the stored eval), and
    no length cap exists on ``answer_text`` anywhere on the path, so the
    input is provider-controlled and unbounded.

    The budget is deliberately loose (a ~10x margin over the round-2
    re-measured post-fix cost of 14 / 27 / 53 ms at 122 / 244 / 488 KB, an
    exact 2x per doubling) so this is a COMPLEXITY gate, not a machine-speed
    gate: quadratic re-entry blows it by two orders of magnitude on the
    largest size while a linear scan cannot approach it.

    Round 3 measured the balanced-scan replacement on the same sizes: 2 ms
    (plain and bracketed openers), 50 ms (nested openers), 62 ms (unmatched
    closers) and 1 ms (plain prose) at 488 KB. Every payload is scaled to
    the SAME byte size, so a short opener does not silently make its case
    100x smaller than the one the budget was set from.
    """
    payload = opener * max(1, (len(_UNTERMINATED_OPENER) * openers) // len(opener))
    started = time.perf_counter()
    extract_citation_markers(payload)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.5, f"{len(payload)} chars took {elapsed:.3f}s — is the URL scan quadratic?"


def test_bounding_the_url_scan_did_not_stop_ordinary_links_matching() -> None:
    """The bound is on the URL RUN, and real links are unaffected."""
    assert extract_citation_markers(f"see [NIST SP 800-63B]({REAL_URL}) and more") == [REAL_URL]
    assert extract_citation_markers("[x]( https://a.test/b?q=1&r=2#frag ) ") == [
        "https://a.test/b?q=1&r=2#frag"
    ]
    # A URL longer than the bound is not a citation marker; it is also not a
    # crash, and it must not swallow the ordinals that follow it.
    over_long = "[x](http://a.test/" + "b" * 2100 + ") then [3]"
    assert extract_citation_markers(over_long) == ["3"]


# --------------------------------------------------------------------------
# detect_refusal
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "I'm sorry, but I can't help with that request.",
        "I can't provide that. What you've described is a procedure for bypassing.",
        "I am unable to assist with this request.",
        "Sorry - I cannot help with that.",
        "I will not write instructions for getting past an authentication control.",
        "I'm not able to answer this one.",
    ],
)
def test_detect_refusal_fires_on_real_refusal_shapes(text: str) -> None:
    assert detect_refusal(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "The guidance says a verifier should not require periodic change.",
        "I would not present this as a settled first-line intervention.",
        "I am describing published guidance, not your regulator's reading of it.",
        "The provider cannot guarantee availability, but the control still applies.",
        "I can help with the defensive side of the same problem.",
    ],
)
def test_detect_refusal_does_not_fire_on_substantive_answers(text: str) -> None:
    assert detect_refusal(text) is False


_HEDGING_ANSWER = (
    "Periodic password rotation is not recommended by current guidance, and the "
    "verifier requirements in SP 800-63B say so explicitly. Rotation on a fixed "
    "schedule pushes users toward predictable transformations of an existing "
    "secret, which is why the guidance moved to screening against known-breached "
    "passwords instead. The effect size reported across the published field "
    "studies varies with the population and the enforcement regime, so "
    "I cannot provide an exact confidence interval for it."
)


def test_a_mid_answer_hedge_is_not_a_refusal() -> None:
    """The evasion this anchoring exists to close.

    "I cannot provide an exact confidence interval" is a hedge INSIDE a
    substantive answer, not a decline. Counting it as a refusal short-circuits
    the fabrication check and lets an unfaithful run be relabelled ``partial``
    at ``low`` risk.
    """
    assert detect_refusal(_HEDGING_ANSWER) is False


@pytest.mark.parametrize(
    "tail",
    [
        " I am unable to give a single number for that.",
        " I cannot provide a precise figure here.",
        " I'm not able to quantify the residual risk.",
    ],
)
def test_a_decline_phrase_late_in_a_substantive_answer_is_not_a_refusal(tail: str) -> None:
    # Non-vacuous by construction: each tail, standing alone, IS a decline the
    # detector fires on. Without this line the case could pass because the
    # phrase matches nothing in ``_REFUSAL_PHRASES`` at all (which is exactly
    # how " I can not provide ..." — two words — used to sit here proving
    # nothing).
    assert detect_refusal(tail.strip()) is True
    assert detect_refusal(_HEDGING_ANSWER + tail) is False


#: A SHORT substantive answer whose only decline phrase sits in its closing
#: sentence. Its length is deliberately below the corpus's shortest
#: substantive answer, so no character-window rule could separate it from a
#: refusal; only the first-sentence anchor can.
#: ``tests/evals/test_trust_calibration.py`` re-derives that corpus minimum
#: and asserts this fixture stays shorter than it.
SHORT_HEDGING_ANSWER = (
    "Current guidance drops password rotation and screens secrets against "
    "known-breached lists instead. Reported effect sizes vary by population and "
    "enforcement regime, so I cannot provide an exact figure."
)


def test_a_late_hedge_in_a_short_answer_is_not_a_refusal() -> None:
    """No character budget can do this; first-sentence anchoring can.

    Re-measured: ``SHORT_HEDGING_ANSWER`` is exactly 200 characters and its
    decline phrase starts at index 167 — i.e. INSIDE a 200-character lead
    window, not past it. That is precisely what the fixture demonstrates: a
    lead window of 200 would call this answer a refusal (a FALSE POSITIVE),
    and no smaller window survives either, because shrinking it re-breaks
    the mirror case in
    ``test_a_decline_in_a_long_first_sentence_is_still_a_refusal``, where a
    genuine decline sits past character 200 and would be MISSED. What makes
    this one not a refusal is structural, not positional: the answer's FIRST
    sentence answers the question.

    (An earlier version of this docstring claimed the phrase "starts past
    character 200 only by accident of length". That was false; the assertion
    below now pins the two measured numbers so the rationale cannot drift
    from the fixture again.)
    """
    assert len(SHORT_HEDGING_ANSWER) == 200
    assert SHORT_HEDGING_ANSWER.index("I cannot provide") == 167
    assert detect_refusal(SHORT_HEDGING_ANSWER) is False


def test_a_decline_in_a_long_first_sentence_is_still_a_refusal() -> None:
    """The mirror failure of a lead window: a refusal that apologises at length.

    The decline phrase here starts well past 200 characters, but it is still
    in the answer's first sentence, so it is still a decline.
    """
    text = (
        "I'm sorry, but having read the request carefully and considered the "
        "framing, the stated justification, the account-recovery control it "
        "targets, and the realistic use of step-by-step instructions of this "
        "kind once they are written down, I cannot help with that."
    )
    assert text.index("I cannot help") > 200
    assert detect_refusal(text) is True


# --------------------------------------------------------------------------
# DEBT-011 part D — the two measured reasons R-2 was missed
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "I can not help with that request.",
        "I can not provide that.",
        "I can not assist with this.",
    ],
)
def test_the_two_word_spelling_of_cannot_is_the_same_decline(text: str) -> None:
    """A SPELLING normalisation, not a new phrase.

    ``_REFUSAL_PHRASES`` deliberately lists one spelling of each phrase. The
    two-word negation "can not" is the same decline as "cannot", and it is
    one of the two measured reasons the R-2 apology-first refusal was missed
    (``tests/evals/test_refusal_fabrication_residual.py``). Normalising it
    alongside the typographic apostrophe keeps the phrase list a list of
    PHRASES rather than a list of spellings.
    """
    assert detect_refusal(text) is True
    assert detect_refusal(text.replace("can not", "cannot")) is True


def test_a_leading_pure_apology_sentence_is_skipped_before_anchoring() -> None:
    """The other measured reason R-2 was missed: the decline is in sentence 2.

    An apology is not an answer. The discriminator this detector rests on is
    structural — "the answer's FIRST sentence answers the question"
    (``test_a_late_hedge_in_a_short_answer_is_not_a_refusal``) — and a pure
    apology answers nothing, so it is skipped and the NEXT sentence is the
    anchor.
    """
    assert (
        detect_refusal("I am sorry you are going through this. I can not help with that request.")
        is True
    )
    assert detect_refusal("I'm sorry. I cannot help with that.") is True


def test_only_a_leading_APOLOGY_is_skipped_not_the_first_sentence_generally() -> None:
    """The bound on part D: this is not "look at the first two sentences".

    ``SHORT_HEDGING_ANSWER``'s decline sits in sentence 2 OF 2 and is an
    ordinary closing hedge. Widening the anchor to two sentences would turn
    that fixture — and this one, its minimal form — into a false positive.
    Only a leading sentence that ANSWERS NOTHING is skipped.
    """
    assert (
        detect_refusal(
            "Current guidance drops password rotation and screens against breached "
            "lists. Reported effect sizes vary, so I cannot provide an exact figure."
        )
        is False
    )
    assert detect_refusal(SHORT_HEDGING_ANSWER) is False


def test_an_apologetic_sentence_that_itself_declines_is_not_skipped() -> None:
    """Skipping must not skip the decline itself.

    "I'm sorry, but I can't help with that request." contains an apology AND
    the decline in ONE sentence. If the skip rule keyed on the apology token
    alone it would step over the decline and return False — the exact
    opposite of the fix.
    """
    assert detect_refusal("I'm sorry, but I can't help with that request.") is True


def test_a_leading_apology_before_a_substantive_answer_is_not_a_refusal() -> None:
    """The skip finds the next sentence; it does not assume it declines."""
    assert (
        detect_refusal(
            "I'm sorry for the confusion. The guidance says a verifier should not "
            "require periodic change."
        )
        is False
    )


def test_an_apology_that_is_the_whole_answer_is_not_a_refusal() -> None:
    """Nothing follows the skipped sentence, so nothing anchors."""
    assert detect_refusal("I am sorry you are going through this.") is False


def test_only_ONE_leading_apology_sentence_is_skipped() -> None:
    """The DEPTH bound on part D, which nothing pinned (review round 2, LOW).

    ``detect_refusal``'s docstring commits to a bounded skip — "Only a
    sentence that answers nothing is skipped, and only one of them" — and
    the sibling half of that sentence ("deliberately NOT widened to the
    first two sentences") IS pinned, by
    ``test_only_a_leading_APOLOGY_is_skipped_not_the_first_sentence_generally``.
    The ONE-ness was not: turning the single ``if`` into a ``while`` that
    skips every leading pure-apology sentence left the ENTIRE suite green,
    so a later refactor could widen the skip arbitrarily in silence.

    The cost of the bound, stated honestly rather than hidden: the third
    sentence here IS a decline and this returns False — a false NEGATIVE.
    That is the safe direction under part A (``refusal_detected`` only caps
    a verdict downward or resolves an unknown risk band), whereas an
    unbounded skip walks past arbitrarily much prose to find a decline
    phrase, which is the false-POSITIVE direction. The bound is structural,
    not a tunable constant, so it is a test and not a calibration (FS-6).
    """
    assert (
        detect_refusal("I am sorry. I am truly sorry about this. I cannot help with that request.")
        is False
    )


#: The apology/sympathy vocabulary, written out as a LITERAL fixture list and
#: compared to :data:`_APOLOGY_TOKENS` for exact equality below.
#:
#: Measured defect (adversarial review round 2): the vocabulary shipped as an
#: inline alternation ``(?:sorry|apolog\w*)`` and the ``apolog\w*`` half had
#: no fixture ANYWHERE — deleting it left the whole suite green, while
#: deleting ``sorry`` reddened 10 tests. That is the identical defect class
#: the module already records as measured for ``_REFUSAL_PHRASES`` (eight of
#: eighteen phrases unfixtured), and the remedy invented there — a literal
#: fixture list compared to the tuple — simply was not applied here.
#: Parametrizing over the tuple would NOT catch it, because the
#: parametrization shrinks with the tuple.
EVERY_APOLOGY_TOKEN: tuple[str, ...] = ("sorry", r"apolog\w*")

#: One leading sentence per token, each a PURE apology (no decline in it), so
#: the skip is what makes the following decline reachable.
_APOLOGY_OPENINGS: tuple[str, ...] = (
    "I am sorry you are going through this.",
    "I apologize for the confusion.",
    "I apologise for the confusion.",
    "My apologies for the confusion.",
    "Apologies for the delay.",
)


def test_the_declared_apology_tokens_are_exactly_the_ones_the_fixtures_exercise() -> None:
    """Adding an apology token without a fixture turns this red."""
    from product_app.evaluation import _APOLOGY_TOKENS

    assert tuple(_APOLOGY_TOKENS) == EVERY_APOLOGY_TOKEN


@pytest.mark.parametrize("opening", _APOLOGY_OPENINGS)
def test_every_apology_spelling_is_skipped_so_the_next_sentence_anchors(opening: str) -> None:
    """Each spelling, in the position the skip actually fires in."""
    assert detect_refusal(f"{opening} I cannot help with that request.") is True


@pytest.mark.parametrize("opening", _APOLOGY_OPENINGS)
def test_every_apology_spelling_is_inert_before_a_substantive_answer(opening: str) -> None:
    """...and the skip finds the next sentence, it does not assume it declines."""
    assert (
        detect_refusal(
            f"{opening} The guidance says a verifier should not require periodic change."
        )
        is False
    )


@pytest.mark.parametrize(
    "separator",
    ["\n\n", "\n\n\n", " \n\n  ", "\n \n", "  ", "\t", "\n"],
    ids=[
        "markdown-paragraph-break",
        "two-blank-lines",
        "space-then-blank-line",
        "newline-space-newline",
        "double-space",
        "tab",
        "single-newline",
    ],
)
def test_the_apology_skip_survives_any_whitespace_between_the_two_sentences(
    separator: str,
) -> None:
    """The apology skip must not depend on the SHAPE of the gap.

    Measured defect (adversarial review round 1): the boundary regex
    consumes the terminal ``.`` plus exactly ONE whitespace character, so
    a markdown paragraph break left a LEADING ``\\n`` on the remainder;
    the boundary regex then matched its ``\\n`` alternative at index 0 and
    the anchor came back EMPTY, so no phrase could match. Every separator
    below is the same refusal — the prose form the R-2 acceptance fixture
    happens to use (single space) and the markdown-paragraph form the same
    model emits when it puts the decline in its own paragraph.
    """
    text = f"I am sorry you are going through this.{separator}I can not help with that request."
    assert detect_refusal(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "\nI can not help with that request.",
        "\n\nI cannot help with that request.",
        "   \n  I can't help with that request.",
    ],
    ids=["leading-newline", "leading-blank-line", "leading-mixed-whitespace"],
)
def test_leading_whitespace_before_the_first_sentence_does_not_hide_a_refusal(
    text: str,
) -> None:
    """An answer that merely BEGINS with a newline must still anchor.

    Same root cause as the apology-skip defect: the boundary regex matches
    its ``\\n`` alternative at index 0 and yields an empty anchor. Provider
    output routinely starts with a blank line.
    """
    assert detect_refusal(text) is True


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (". x", "x"),
        ("! I can't help with that.", "i can't help with that"),
        ("? really", "really"),
        ("... The answer is yes.", "the answer is yes"),
    ],
    ids=["period", "bang", "question", "ellipsis"],
)
def test_a_sentence_boundary_at_index_zero_never_yields_an_empty_anchor(
    text: str, expected: str
) -> None:
    """MEASURED defect (adversarial review round 3).

    ``_first_sentence``'s docstring claimed an empty sentence was
    impossible for non-blank text "because leading whitespace is stripped
    first, so a boundary can only be found at an index greater than zero".
    Measured, ``_SENTENCE_BOUNDARY_RE`` matches at index 0 whenever the text
    OPENS with terminal punctuation followed by whitespace, and the function
    returned ``""``. An ellipsis opener returned ``".."`` — non-empty and
    equally word-free. Either way no decline phrase can match the anchor.

    The rule is therefore "the first sentence that carries a WORD", which is
    what the surrounding argument (an anchor is the sentence that answers
    the question) always meant.
    """
    from product_app.evaluation import _first_sentence

    assert _first_sentence(text.lower()) == expected


@pytest.mark.parametrize(
    "text",
    [
        "I'm sorry. ! I can't help with that.",
        "I am sorry. ... I cannot help with that request.",
        ". I am sorry. I can not help with that request.",
    ],
    ids=["bang-opener", "ellipsis-opener", "leading-period"],
)
def test_a_punctuation_only_fragment_does_not_swallow_the_refusal_anchor(
    text: str,
) -> None:
    """The consumer of the defect above: the Part-D apology skip.

    The skip re-anchors on ``_first_sentence(_after_first_sentence(...))``.
    When the sentence after the apology opened with stray punctuation the
    anchor came back empty (or as ``".."``) and the refusal was missed —
    measured, ``detect_refusal("I'm sorry. ! I can't help with that.")`` was
    ``False`` while the same text without the ``!`` was ``True``.
    """
    assert detect_refusal(text) is True


# --------------------------------------------------------------------------
# _REFUSAL_PHRASES coverage
# --------------------------------------------------------------------------

#: Written out LITERALLY, not imported, and deliberately not parametrized
#: over ``_REFUSAL_PHRASES`` itself: a test that parametrizes over the tuple
#: it is meant to cover shrinks with the tuple and cannot notice a deleted
#: phrase. Measured (adversarial review round 1): eight of the eighteen
#: phrases were exercised by NO fixture anywhere, and deleting all eight
#: left the whole refusal suite green.
EVERY_REFUSAL_PHRASE: tuple[str, ...] = (
    "i can't help",
    "i cannot help",
    "cannot help with that",
    "i can't provide",
    "i cannot provide",
    "i can't assist",
    "i cannot assist",
    "i can't write",
    "i cannot write",
    "i can't do that",
    "i am unable to",
    "i'm unable to",
    "unable to assist with",
    "i won't",
    "i will not write",
    "i will not provide",
    "i am not able to",
    "i'm not able to",
)


def test_the_declared_phrase_list_is_exactly_the_one_the_fixtures_exercise() -> None:
    """The phrase list and its fixture list are the same list.

    Adding a phrase to :data:`_REFUSAL_PHRASES` without a fixture, or
    deleting a phrase no fixture would miss, turns this red. That is what
    makes the module comment's coverage claim true rather than asserted.
    """
    from product_app.evaluation import _REFUSAL_PHRASES

    assert tuple(_REFUSAL_PHRASES) == EVERY_REFUSAL_PHRASE


@pytest.mark.parametrize("phrase", EVERY_REFUSAL_PHRASE)
def test_every_declared_phrase_fires_in_a_first_sentence(phrase: str) -> None:
    """Each phrase, in the position the detector actually anchors on."""
    assert detect_refusal(f"{phrase} with this request.") is True


@pytest.mark.parametrize("phrase", EVERY_REFUSAL_PHRASE)
def test_every_declared_phrase_is_inert_outside_the_anchor(phrase: str) -> None:
    """...and each is a PHRASE, not a substring match over the whole answer.

    Several are ordinary mid-answer hedges; none of them may fire from the
    tail of a substantive answer.
    """
    assert detect_refusal(f"{_HEDGING_ANSWER} {phrase} more than that.") is False


def test_a_refusal_that_links_a_crisis_resource_is_not_a_fabricating_run() -> None:
    """Safe-completion refusals link a policy or crisis page. That is not
    fabrication, and must not be served as the WORST trust labels.

    Reproduced regression: a clause rejecting any answer carrying citation
    markers made every one of these slots a non-refusal, which left a run of
    four declines scored ``unfaithful`` / ``high``.
    """
    text = (
        "I cannot help with that request. If you are in crisis, please contact "
        "[988 Suicide & Crisis Lifeline](https://988lifeline.org)."
    )
    assert detect_refusal(text) is True
    evaluation = evaluate_layer_a(
        initial_answers=[_answer(slot=slot, text=text, sources=[]) for slot in (1, 2, 3, 4)],
        final_synthesis=_synthesis(),
        agreement=AgreementSummary(aligned=4, total=4),
    )
    assert evaluation.signals.refusal_detected is True
    assert evaluation.faithfulness_label == "partial"
    assert evaluation.hallucination_risk == "low"


def test_a_refusal_that_links_an_on_run_source_is_not_the_maximum_trust_label() -> None:
    """The mirror case: the linked page IS a run source.

    Every marker resolves, so a fabrication-first classifier would hand this
    run ``faithful`` / ``low`` — the MAXIMUM trust labels — for a panel that
    answered nothing. A wholly refused run asserts nothing either way.
    """
    text = f"I cannot help with that request. Our policy is at [the policy]({REAL_URL})."
    evaluation = evaluate_layer_a(
        initial_answers=[
            _answer(slot=slot, text=text, sources=[_source(REAL_URL)]) for slot in (1, 2, 3, 4)
        ],
        final_synthesis=_synthesis(),
        agreement=AgreementSummary(aligned=4, total=4),
    )
    assert evaluation.faithfulness_label == "partial"
    assert evaluation.hallucination_risk == "low"


def test_one_slot_that_declines_then_fabricates_still_costs_the_run() -> None:
    """The refusal precedence is WHOLLY-refused, not per-answer exclusion.

    If a refused answer's markers were simply dropped from the grounding
    signal, a single slot could open with a decline and then fabricate freely
    while the run scored ``faithful``. Here three slots are clean and one
    declines-then-fabricates; the run must still be penalised.
    """
    evaluation = evaluate_layer_a(
        initial_answers=[
            _answer(slot=1, text="I cannot help with that. But see [7], [8] and [9]."),
            _answer(slot=2, text="A substantive answer [1]."),
            _answer(slot=3, text="Another substantive answer [1]."),
            _answer(slot=4, text="A third substantive answer [1]."),
        ],
        final_synthesis=_synthesis(),
        agreement=AgreementSummary(aligned=3, total=4),
    )
    assert evaluation.signals.run_wholly_refused is False
    # 3 resolved of 6 markers = 0.5 is NOT below the fabrication cut, but the
    # fabricated ordinals must at least be counted rather than vanish.
    assert evaluation.signals.citation_marker_grounding == pytest.approx(0.5)


def test_a_run_that_fabricates_citations_is_not_excused_by_refusing_slots() -> None:
    """Ordering: fabrication outranks refusal.

    Two slots decline and two fabricate markers. ``refusal_detected`` is True
    (2/4 meets the majority threshold), but the run still put fabricated
    citations in front of a user, so it must not be served as ``partial`` /
    ``low`` risk.
    """
    evaluation = evaluate_layer_a(
        initial_answers=[
            _answer(slot=1, text="I can't help with that."),
            _answer(slot=2, text="I cannot assist with this request."),
            _answer(slot=3, text="A confident claim [9]."),
            _answer(slot=4, text="Another confident claim [8]."),
        ],
        final_synthesis=_synthesis(),
        agreement=AgreementSummary(aligned=2, total=4),
    )
    assert evaluation.signals.refusal_detected is True
    assert evaluation.signals.citation_marker_grounding == pytest.approx(0.0)
    assert evaluation.faithfulness_label == "unfaithful"
    assert evaluation.hallucination_risk == "high"


def test_run_level_refusal_needs_a_majority_of_slots() -> None:
    """Advisory threshold (FS-6): one declining slot out of four is not a
    refused run, three out of four is."""
    one_refusal = evaluate_layer_a(
        initial_answers=[
            _answer(slot=1, text="I can't help with that."),
            _answer(slot=2, text="A substantive answer [1]."),
            _answer(slot=3, text="Another substantive answer [1]."),
            _answer(slot=4, text="A third substantive answer [1]."),
        ],
        final_synthesis=_synthesis(),
        agreement=AgreementSummary(aligned=3, total=4),
    )
    assert one_refusal.signals.refusal_detected is False

    most_refuse = evaluate_layer_a(
        initial_answers=[
            _answer(slot=1, text="I can't help with that."),
            _answer(slot=2, text="I am unable to assist with this request."),
            _answer(slot=3, text="I cannot provide that."),
            _answer(slot=4, text="A substantive answer [1]."),
        ],
        final_synthesis=_synthesis(),
        agreement=AgreementSummary(aligned=1, total=4),
    )
    assert most_refuse.signals.refusal_detected is True
    assert most_refuse.faithfulness_label == "partial"


# --------------------------------------------------------------------------
# Signals and composite
# --------------------------------------------------------------------------


def test_live_ratio_and_completeness_are_measured_from_the_slots() -> None:
    evaluation = evaluate_layer_a(
        initial_answers=[
            _answer(slot=1),
            _answer(slot=2),
            _answer(slot=3, path=ProviderPath.LOCAL_SIMULATION),
            _answer(
                slot=4,
                status=InitialAnswerStatus.FAILED,
                text="",
                sources=[],
                path=ProviderPath.LOCAL_SIMULATION,
            ),
        ],
        final_synthesis=_synthesis(),
        agreement=AgreementSummary(aligned=2, total=4),
    )
    assert evaluation.signals.live_ratio == pytest.approx(0.5)
    assert evaluation.signals.completeness == pytest.approx(0.75)


def test_high_stakes_warning_presence_is_reported_separately_from_the_requirement() -> None:
    missing = evaluate_layer_a(
        initial_answers=[_answer()],
        final_synthesis=_synthesis(high_stakes_required=True, high_stakes_notice=None),
        agreement=AgreementSummary(aligned=1, total=1),
    )
    assert missing.signals.high_stakes_warning_required is True
    assert missing.signals.high_stakes_warning_present is False

    present = evaluate_layer_a(
        initial_answers=[_answer()],
        final_synthesis=_synthesis(
            high_stakes_required=True, high_stakes_notice="This is health-related."
        ),
        agreement=AgreementSummary(aligned=1, total=1),
    )
    assert present.signals.high_stakes_warning_present is True


def test_suppressed_disagreement_is_flagged_and_costs_the_composite() -> None:
    """Polar disagreement in the answers that the synthesis did NOT preserve."""
    answers = [
        _answer(slot=1, text="I would recommend the change [1]."),
        _answer(slot=2, text="I would avoid the change [1]."),
    ]
    suppressed = evaluate_layer_a(
        initial_answers=answers,
        final_synthesis=_synthesis(false_consensus_preserved=False),
        agreement=AgreementSummary(aligned=2, total=2),
    )
    preserved = evaluate_layer_a(
        initial_answers=answers,
        final_synthesis=_synthesis(false_consensus_preserved=True),
        agreement=AgreementSummary(aligned=2, total=2),
    )
    assert suppressed.signals.polar_disagreement_detected is True
    assert suppressed.signals.disagreement_suppressed is True
    assert preserved.signals.disagreement_suppressed is False

    from product_app.evaluation import build_trust_score

    assert (
        build_trust_score(preserved).diagnostics.layer_a_composite_unverified
        > build_trust_score(suppressed).diagnostics.layer_a_composite_unverified
    )


def test_a_missing_synthesis_is_evaluated_without_crashing() -> None:
    evaluation = evaluate_layer_a(
        initial_answers=[_answer()],
        final_synthesis=None,
        agreement=AgreementSummary(aligned=0, total=1),
    )
    assert evaluation.signals.decision_support_framing_present is False
    assert evaluation.signals.uncertainty_surfaced is False
    assert evaluation.faithfulness_label in {"faithful", "unfaithful", "partial"}


def test_an_empty_run_is_evaluated_without_dividing_by_zero() -> None:
    evaluation = evaluate_layer_a(
        initial_answers=[],
        final_synthesis=None,
        agreement=AgreementSummary(aligned=0, total=0),
    )
    assert evaluation.signals.live_ratio == pytest.approx(0.0)
    assert evaluation.signals.completeness == pytest.approx(0.0)
    assert evaluation.signals.citation_marker_grounding is None


def test_contributions_sum_to_the_composite_and_the_weights_are_named() -> None:
    from product_app.evaluation import build_trust_score

    trust = build_trust_score(
        evaluate_layer_a(
            initial_answers=[_answer()],
            final_synthesis=_synthesis(),
            agreement=AgreementSummary(aligned=1, total=1),
        )
    )
    total = sum(c.contribution for c in trust.diagnostics.contributions)
    assert total == pytest.approx(trust.diagnostics.layer_a_composite_unverified, abs=1e-6)
    assert {c.signal for c in trust.diagnostics.contributions} <= set(LAYER_A_WEIGHTS)


def test_declared_weights_sum_to_one() -> None:
    assert sum(LAYER_A_WEIGHTS.values()) == pytest.approx(1.0)


def test_agreement_is_recorded_but_deliberately_excluded_from_the_composite() -> None:
    """Measured on the S2 corpus: agreement is not monotone in trust.

    ``simulated-low-live-ratio`` scores 3/4 agreement while the genuinely
    divided ``preserved-polar-disagreement`` scores 0/4, so weighting it
    would reward the simulated run. It is carried as a signal only.
    """
    assert "agreement_ratio" not in LAYER_A_WEIGHTS
    evaluation = evaluate_layer_a(
        initial_answers=[_answer()],
        final_synthesis=_synthesis(),
        agreement=AgreementSummary(aligned=1, total=1),
    )
    assert evaluation.signals.agreement_ratio == pytest.approx(1.0)


# --------------------------------------------------------------------------
# Boundary and normalisation behaviour
#
# The assertions below were added after a mutmut run over
# ``src/product_app/evaluation.py`` left the corresponding mutants alive:
# every constant, comparison and normalisation step below had no oracle.
# --------------------------------------------------------------------------


def test_url_markers_are_matched_modulo_trailing_punctuation_and_case() -> None:
    """``_normalize_url`` folds exactly these differences and no others."""
    for spelling in (
        "https://PAGES.nist.gov/800-63-3/sp800-63b.html",
        "https://pages.nist.gov/800-63-3/sp800-63b.html/",
        "https://pages.nist.gov/800-63-3/sp800-63b.html",
    ):
        assert _grounding(
            texts=[f"See [the guideline]({spelling})."],
            sources=[_source(REAL_URL)],
        ) == pytest.approx(1.0)

    # A different document is still a different document. Since DEBT-011
    # part C an unmatched URL is EXCLUDED rather than counted as unresolved,
    # so the discriminating observation is ``None`` (nothing resolvable in
    # the prose) versus 1.0 above — not 0.0 versus 1.0. Either way a
    # normalisation that folded the query string would resolve it and this
    # would read 1.0.
    assert (
        _grounding(
            texts=[f"See [another page]({REAL_URL}?query=1)."],
            sources=[_source(REAL_URL)],
        )
        is None
    )


def test_an_ordinal_beyond_the_real_source_count_does_not_resolve() -> None:
    sources = [_source(REAL_URL), _source(OTHER_URL)]
    assert _grounding(texts=["A claim [2]."], sources=sources) == pytest.approx(1.0)
    assert _grounding(texts=["A claim [3]."], sources=sources) == pytest.approx(0.0)
    assert _grounding(texts=["A claim [0]."], sources=sources) == pytest.approx(0.0)


def test_markers_are_counted_across_every_text_not_just_the_first() -> None:
    assert _grounding(
        texts=["Resolves [1].", "Does not resolve [4]."],
        sources=[_source(REAL_URL)],
    ) == pytest.approx(0.5)


def test_ordinal_group_separators_are_both_supported() -> None:
    assert extract_citation_markers("A claim [1; 2].") == ["1", "2"]
    assert extract_citation_markers("A claim [ 1 , 2 ].") == ["1", "2"]


def test_a_refusal_written_with_a_typographic_apostrophe_is_still_a_refusal() -> None:
    """Providers emit U+2019, not ASCII ', far more often than not."""
    assert detect_refusal("I’m sorry, but I can’t help with that.") is True


def test_a_failed_slot_with_text_is_not_counted_as_a_substantive_answer() -> None:
    evaluation = evaluate_layer_a(
        initial_answers=[
            _answer(slot=1, text="A substantive answer [1]."),
            _answer(
                slot=2,
                text="A partial fragment that was still marked failed [1].",
                status=InitialAnswerStatus.FAILED,
            ),
        ],
        final_synthesis=_synthesis(),
        agreement=AgreementSummary(aligned=1, total=2),
    )
    assert evaluation.signals.completeness == pytest.approx(0.5)


def test_the_uncertainty_floor_is_the_documented_twenty_characters() -> None:
    short = evaluate_layer_a(
        initial_answers=[_answer()],
        final_synthesis=_synthesis(uncertainty="x" * 19),
        agreement=AgreementSummary(aligned=1, total=1),
    )
    exact = evaluate_layer_a(
        initial_answers=[_answer()],
        final_synthesis=_synthesis(uncertainty="x" * 20),
        agreement=AgreementSummary(aligned=1, total=1),
    )
    assert short.signals.uncertainty_surfaced is False
    assert exact.signals.uncertainty_surfaced is True


@pytest.mark.parametrize(
    ("grounding", "label", "risk"),
    [
        (0.0, "unfaithful", "high"),
        (0.49, "unfaithful", "high"),
        (0.5, "faithful", "medium"),
        (0.79, "faithful", "medium"),
        (0.8, "faithful", "low"),
        (1.0, "faithful", "low"),
    ],
)
def test_classifier_thresholds_are_the_declared_constants(
    grounding: float, label: str, risk: str
) -> None:
    from product_app.evaluation import (
        GROUNDING_FABRICATION_THRESHOLD,
        GROUNDING_GOOD_THRESHOLD,
        LayerASignals,
        classify_faithfulness,
        classify_hallucination_risk,
    )

    assert GROUNDING_FABRICATION_THRESHOLD == 0.5
    assert GROUNDING_GOOD_THRESHOLD == 0.8
    signals = LayerASignals(
        citation_coverage_ratio=1.0,
        citation_marker_grounding=grounding,
        agreement_ratio=1.0,
        live_ratio=1.0,
        completeness=1.0,
        false_consensus_preserved=False,
        polar_disagreement_detected=False,
        disagreement_suppressed=False,
        decision_support_framing_present=True,
        high_stakes_warning_required=False,
        high_stakes_warning_present=False,
        uncertainty_surfaced=True,
        refusal_detected=False,
        run_wholly_refused=False,
    )
    assert classify_faithfulness(signals) == label
    assert classify_hallucination_risk(signals) == risk


@pytest.mark.parametrize(
    ("live_ratio", "completeness", "expected"),
    [(1.0, 1.0, "faithful"), (0.75, 1.0, "partial"), (1.0, 0.75, "partial")],
)
def test_a_degraded_run_is_partial_even_when_its_markers_resolve(
    live_ratio: float, completeness: float, expected: str
) -> None:
    from product_app.evaluation import LayerASignals, classify_faithfulness

    signals = LayerASignals(
        citation_coverage_ratio=1.0,
        citation_marker_grounding=1.0,
        agreement_ratio=1.0,
        live_ratio=live_ratio,
        completeness=completeness,
        false_consensus_preserved=False,
        polar_disagreement_detected=False,
        disagreement_suppressed=False,
        decision_support_framing_present=True,
        high_stakes_warning_required=False,
        high_stakes_warning_present=False,
        uncertainty_surfaced=True,
        refusal_detected=False,
        run_wholly_refused=False,
    )
    assert classify_faithfulness(signals) == expected


def _signals_for(composite: float) -> object:
    """Signals whose composite is exactly ``composite`` (0-100).

    With the three boolean components at 1.0 the composite is
    ``100 * (0.80 * x + 0.20)`` where ``x`` is the shared ratio value.
    """
    from product_app.evaluation import LayerASignals

    x = (composite / 100.0 - 0.20) / 0.80
    return LayerASignals(
        citation_coverage_ratio=x,
        citation_marker_grounding=x,
        agreement_ratio=0.0,
        live_ratio=x,
        completeness=x,
        false_consensus_preserved=False,
        polar_disagreement_detected=False,
        disagreement_suppressed=False,
        decision_support_framing_present=True,
        high_stakes_warning_required=False,
        high_stakes_warning_present=False,
        uncertainty_surfaced=True,
        refusal_detected=False,
        run_wholly_refused=False,
    )


@pytest.mark.parametrize(
    ("composite", "band"),
    [
        # 20.0 is the floor reachable with the three boolean components
        # present; a run with none of them is covered by the corpus cases.
        (20.0, "low"),
        (49.0, "low"),
        (50.0, "moderate"),
        (74.0, "moderate"),
        (75.0, "high"),
        (100.0, "high"),
    ],
)
def test_band_cuts_are_the_declared_constants_once_support_is_verified(
    composite: float, band: str
) -> None:
    """The verified path exists and is exercised, even though no hermetic run
    can reach it (``support_verified`` requires a real judge)."""
    from product_app.evaluation import (
        BAND_LOW_CEILING,
        BAND_MODERATE_CEILING,
        RunEvaluation,
        build_trust_score,
        compute_composite,
    )

    assert (BAND_LOW_CEILING, BAND_MODERATE_CEILING) == (50.0, 75.0)
    signals = _signals_for(composite)
    measured, _ = compute_composite(signals)  # type: ignore[arg-type]
    assert measured == pytest.approx(composite)

    evaluation = RunEvaluation(
        signals=signals,  # type: ignore[arg-type]
        faithfulness_label="faithful",
        hallucination_risk="low",
    )
    trust = build_trust_score(evaluation, support_verified=True)
    assert trust.band == band
    assert trust.score == int(round(composite))
    assert trust.served_confidence() == int(round(composite))


def test_an_unknown_grounding_renormalises_rather_than_scoring_zero() -> None:
    """The excluded-weight arithmetic, asserted numerically."""
    from product_app.evaluation import LayerASignals, compute_composite

    known = LayerASignals(
        citation_coverage_ratio=1.0,
        citation_marker_grounding=1.0,
        agreement_ratio=0.0,
        live_ratio=1.0,
        completeness=1.0,
        false_consensus_preserved=False,
        polar_disagreement_detected=False,
        disagreement_suppressed=False,
        decision_support_framing_present=True,
        high_stakes_warning_required=False,
        high_stakes_warning_present=False,
        uncertainty_surfaced=True,
        refusal_detected=False,
        run_wholly_refused=False,
    )
    unknown = known.model_copy(update={"citation_marker_grounding": None})
    composite_known, contributions_known = compute_composite(known)
    composite_unknown, contributions_unknown = compute_composite(unknown)
    assert composite_known == pytest.approx(100.0)
    assert composite_unknown == pytest.approx(100.0)
    assert len(contributions_known) == len(contributions_unknown) + 1
    # Renormalisation, not a free pass: with one weight removed the
    # remaining weights each grow by 1/0.70.
    live = next(c for c in contributions_unknown if c.signal == "live_ratio")
    assert live.contribution == pytest.approx(100.0 * 0.20 / 0.70)


def test_synthesis_prose_markers_are_counted_not_just_answer_markers() -> None:
    """A citation invented in the synthesis is exactly as ungrounded as one
    invented in an answer."""
    evaluation = evaluate_layer_a(
        initial_answers=[_answer(text="Plain prose with no markers.")],
        final_synthesis=_synthesis(consensus="The panel agrees [9]."),
        agreement=AgreementSummary(aligned=1, total=1),
    )
    assert evaluation.signals.citation_marker_grounding == pytest.approx(0.0)


def test_an_exact_half_of_the_slots_declining_counts_as_a_refused_run() -> None:
    """``REFUSAL_MAJORITY_THRESHOLD`` is inclusive: 2 of 4 is a refused run."""
    from product_app.evaluation import REFUSAL_MAJORITY_THRESHOLD

    assert REFUSAL_MAJORITY_THRESHOLD == 0.5
    evaluation = evaluate_layer_a(
        initial_answers=[
            _answer(slot=1, text="I can't help with that."),
            _answer(slot=2, text="I cannot provide that."),
            _answer(slot=3, text="A substantive answer [1]."),
            _answer(slot=4, text="Another substantive answer [1]."),
        ],
        final_synthesis=_synthesis(),
        agreement=AgreementSummary(aligned=2, total=4),
    )
    assert evaluation.signals.refusal_detected is True


def test_coverage_without_a_synthesis_counts_answers_with_a_real_source() -> None:
    """The no-synthesis fallback reproduces the production aggregate."""
    with_real = evaluate_layer_a(
        initial_answers=[_answer(slot=1), _answer(slot=2)],
        final_synthesis=None,
        agreement=AgreementSummary(aligned=0, total=2),
    )
    # 2 answers x material_claim_count 2 = 4 material claims, 2 answers with a
    # non-fallback source = 2 cited claims -> 0.50.
    assert with_real.signals.citation_coverage_ratio == pytest.approx(0.5)

    only_fallback = evaluate_layer_a(
        initial_answers=[
            _answer(slot=1, sources=[_source("https://example.test/1", is_fallback=True)]),
            _answer(slot=2, sources=[_source("https://example.test/2", is_fallback=True)]),
        ],
        final_synthesis=None,
        agreement=AgreementSummary(aligned=0, total=2),
    )
    assert only_fallback.signals.citation_coverage_ratio == pytest.approx(0.0)


def test_no_synthesis_coverage_excludes_real_web_search_sources_like_production() -> None:
    """Coverage is PRIMARY-ONLY and must reproduce the production aggregate.

    A REAL Tavily page (real host, ``is_fallback=True`` since #31/#32) is
    deliberately NOT counted toward citation coverage — the metric measures the
    model's OWN ``:online`` citations, and fallback/web-search sources are
    excluded (SYNTHESIS_AUDIT.md; synthesis.py; providers.py). This is the
    OPPOSITE of grounding / judge-evidence, which ARE host-keyed. The
    no-synthesis branch must therefore stay ``is_fallback``-keyed, not
    placeholder-keyed. Pins the distinction the ``example.test``-only fixtures
    above could not (they are excluded under either rule)."""
    real_web = evaluate_layer_a(
        initial_answers=[
            _answer(slot=1, sources=[_source(OTHER_URL, is_fallback=True)]),
            _answer(slot=2, sources=[_source(THIRD_URL, is_fallback=True)]),
        ],
        final_synthesis=None,
        agreement=AgreementSummary(aligned=0, total=2),
    )
    assert real_web.signals.citation_coverage_ratio == pytest.approx(0.0)


def test_an_empty_run_reports_zero_agreement_not_perfect_agreement() -> None:
    evaluation = evaluate_layer_a(
        initial_answers=[],
        final_synthesis=None,
        agreement=AgreementSummary(aligned=0, total=0),
    )
    assert evaluation.signals.agreement_ratio == pytest.approx(0.0)


def test_a_url_marker_followed_by_sentence_punctuation_still_resolves() -> None:
    assert _grounding(
        texts=[f"See [the guideline]({REAL_URL}.)"],
        sources=[_source(REAL_URL)],
    ) == pytest.approx(1.0)


def test_missing_uncertainty_or_decision_support_framing_lowers_the_composite() -> None:
    from product_app.evaluation import build_trust_score

    full = evaluate_layer_a(
        initial_answers=[_answer()],
        final_synthesis=_synthesis(),
        agreement=AgreementSummary(aligned=1, total=1),
    )
    no_uncertainty = evaluate_layer_a(
        initial_answers=[_answer()],
        final_synthesis=_synthesis(uncertainty=""),
        agreement=AgreementSummary(aligned=1, total=1),
    )
    no_framing = evaluate_layer_a(
        initial_answers=[_answer()],
        final_synthesis=_synthesis(decision_support=False),
        agreement=AgreementSummary(aligned=1, total=1),
    )
    baseline = build_trust_score(full).diagnostics.layer_a_composite_unverified
    assert build_trust_score(no_uncertainty).diagnostics.layer_a_composite_unverified < baseline
    assert build_trust_score(no_framing).diagnostics.layer_a_composite_unverified < baseline
