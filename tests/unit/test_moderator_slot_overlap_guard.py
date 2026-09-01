"""W9: the moderator model may be a panel member grading its own answer.

WHAT GOES WRONG WITHOUT THE GUARD

``settings.debate_model_id`` (``anthropic/claude-haiku-4.5``) is also slot 2's
shipped default. The moderator prompt names every answer's model
(``debate._debate_user_prompt`` builds
``f"- Slot {answer.slot_number} — {label} ({answer.status.value}): {excerpt}"``)
and the system prompt says "Cite the model names", so the moderator
reads a panel that includes its own answer, labelled as its own. It then returns
a ``PanelStance`` with one position per slot, and
``synthesis_consensus._usable_stance`` feeds that straight into
``panel_agreement`` ("agreed"/"split") and ``compute_consensus_strength``
("strong"/"divided"). One of the four votes deciding the verdict the reader sees
is the moderator's grade of its own answer, and nothing anywhere says so.

WHAT THE GUARD DOES

It DETECTS and REPORTS; it never refuses. The shipped default configuration IS
the overlapping one, so a refusal would brick production on the next deploy.
See ADR-0086.

WHAT TURNS EACH TEST RED

Every test below drives ``model_slots.moderator_overlap_slots`` over
CONSTRUCTED slot lists — never over ``DEFAULT_MODEL_IDS`` and
``settings.debate_model_id``, which would assert today's configuration rather
than the guard (AGENTS rule 7a). Deleting the guard (returning ``()``) turns
the positive tests red; the named weakenings in each docstring turn exactly one
test red each.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from product_app.config import settings
from product_app.main import app
from product_app.model_slots import ModelSlot, moderator_overlap_slots


def _slots(*model_ids: str) -> list[ModelSlot]:
    """Slot records numbered 1..N over the given ids."""
    return [
        ModelSlot(slot_number=index, model_id=model_id, search=True)
        for index, model_id in enumerate(model_ids, start=1)
    ]


# ---------------------------------------------------------------------------
# The pure guard.
# ---------------------------------------------------------------------------


def test_the_slot_whose_model_is_the_moderator_is_reported() -> None:
    """RED when the guard is deleted (an empty tuple is returned always)."""
    overlap = moderator_overlap_slots(
        _slots("vendor-a/one", "vendor-b/two", "vendor-c/three", "vendor-d/four"),
        moderator_model_id="vendor-b/two",
    )
    assert overlap == (2,)


def test_a_panel_that_excludes_the_moderator_is_not_reported() -> None:
    """The POSITIVE PARTNER for every "it flags X" assertion here (AGENTS
    rule 7): a guard that flagged everything would pass those and fail this.

    RED when the guard reports a slot it did not match — e.g. returning every
    slot number, or matching on the vendor prefix rather than the whole id.
    """
    overlap = moderator_overlap_slots(
        _slots("vendor-a/one", "vendor-b/two", "vendor-c/three", "vendor-d/four"),
        moderator_model_id="vendor-b/not-on-the-panel",
    )
    assert overlap == ()


def test_every_slot_is_examined_not_only_the_first() -> None:
    """RED when the guard compares only slot 1 (or only the first match).

    The moderator sits at slot 2 in the shipped configuration, so a guard
    written against slot 1 would look correct on a constructed example and be
    blind to production.
    """
    last = moderator_overlap_slots(
        _slots("vendor-a/one", "vendor-b/two", "vendor-c/three", "vendor-d/four"),
        moderator_model_id="vendor-d/four",
    )
    assert last == (4,)

    twice = moderator_overlap_slots(
        _slots("vendor-a/one", "vendor-b/two", "vendor-a/one", "vendor-d/four"),
        moderator_model_id="vendor-a/one",
    )
    assert twice == (1, 3)


def test_the_reported_numbers_are_the_slots_own_not_their_position() -> None:
    """RED when the guard derives slot numbers from ``enumerate`` instead of
    reading ``ModelSlot.slot_number``.

    ``validate_model_slots`` numbers 1..N today, but the guard is handed
    ``ModelSlot`` records precisely so a caller-supplied or filtered list
    cannot make it report a number that belongs to a different slot.
    """
    slots = [
        ModelSlot(slot_number=3, model_id="vendor-a/one", search=True),
        ModelSlot(slot_number=4, model_id="vendor-b/two", search=True),
    ]
    # ``enumerate(..., start=1)`` over this list would call the second entry
    # slot 2. It is slot 4. (``ModelSlot`` bounds slot_number to
    # 1..EXPECTED_SLOT_COUNT, so the divergence is shown inside that bound
    # rather than by inventing a number the model rejects.)
    assert moderator_overlap_slots(slots, moderator_model_id="vendor-b/two") == (4,)


def test_case_and_surrounding_space_are_not_a_difference_of_model() -> None:
    """RED when the comparison is case-sensitive, or does not strip.

    ``DEBATE_MODEL_ID`` is a free-text environment setting
    (``config.py``), so an operator typing the id with different case, or a
    deployment tool leaving a trailing newline on the value, must not silently
    turn the guard off.
    """
    overlap = moderator_overlap_slots(
        _slots("vendor-a/one", "Vendor-B/Two", "vendor-c/three", "vendor-d/four"),
        moderator_model_id="  vendor-b/TWO\n",
    )
    assert overlap == (2,)


def test_a_routing_suffix_does_not_hide_the_same_model() -> None:
    """RED when the guard compares whole ids without dropping the
    ``:variant`` routing suffix.

    A slot stored with a ``:online`` / ``:free`` / ``:preview`` / ``:batch``
    variant is the same weights as the bare moderator id and grades itself just
    as hard. The reachable shape is a catalog- or caller-supplied id that
    already carries a colon; ``providers.py``'s ``:online`` is appended at
    dispatch and never stored, so it is NOT how such an id arises. See
    ``_normalised_model_id``.
    """
    online = moderator_overlap_slots(
        _slots("vendor-a/one", "vendor-b/two:online", "vendor-c/three", "vendor-d/four"),
        moderator_model_id="vendor-b/two",
    )
    assert online == (2,)

    free = moderator_overlap_slots(
        _slots("vendor-a/one", "vendor-b/two", "vendor-c/three", "vendor-d/four"),
        moderator_model_id="vendor-b/two:free",
    )
    assert free == (2,)


def test_a_suffix_is_dropped_from_the_model_not_from_the_vendor() -> None:
    """RED when the guard splits on the FIRST colon of the whole id rather
    than inside the model segment.

    The partner to the suffix test above: over-stripping is how a detector
    starts reporting overlaps that are not there. ``_MODEL_ID_RE`` in this
    module permits a colon in the VENDOR segment
    (``[A-Za-z0-9._:-]`` before the slash), so two ids that differ only there
    are a shape this repo's own validator accepts — and a first-colon split
    reduces both of them to ``"vendor"`` and calls them the same model.

    MEASURED: a first-colon split leaves the trailing-suffix test above green,
    so without this partner the anchoring is untested.
    """
    same_vendor_different_model = moderator_overlap_slots(
        _slots("vendor-a/one", "vendor-b/two", "vendor-c/three", "vendor-d/four"),
        moderator_model_id="vendor-b/different-model:online",
    )
    assert same_vendor_different_model == ()

    colon_in_the_vendor = moderator_overlap_slots(
        _slots("vendor:x/one", "vendor-b/two"),
        moderator_model_id="vendor:y/one",
    )
    assert colon_in_the_vendor == ()


def test_a_slot_that_merely_contains_the_moderator_id_is_a_different_model() -> None:
    """RED when the comparison is loosened from ``==`` to ``in``, to a reversed
    ``in``, or to ``startswith``.

    MEASURED: all three of those mutants survived the first draft of this file,
    because every other negative case used ids that are not substrings of one
    another. ``openai/gpt-4`` and ``openai/gpt-4o`` are the real shape — a
    prefix match would report a model that is not on the panel and send an
    operator to investigate a configuration that is correct.
    """
    longer_slot = moderator_overlap_slots(
        _slots("vendor-a/one", "vendor-b/two-extended"),
        moderator_model_id="vendor-b/two",
    )
    assert longer_slot == ()

    longer_moderator = moderator_overlap_slots(
        _slots("vendor-a/one", "vendor-b/two"),
        moderator_model_id="vendor-b/two-extended",
    )
    assert longer_moderator == ()


def test_a_blank_moderator_id_reports_nothing() -> None:
    """RED when the "no moderator, nothing to report" early return is deleted.

    ``debate._call_debate_model`` returns before dispatching when
    ``settings.debate_model_id`` is falsy, so a blank setting means no
    moderator call and therefore no self-grading to report.

    The blank SLOT id is what makes this bite, and it is the only shape that
    can: without the early return, two ids that both normalise to ``""``
    compare EQUAL, so a deployment with no moderator at all would be reported
    as one grading its own answer. MEASURED — with only the non-blank slot
    ids below, deleting the early return leaves this test green, because
    ``"" != "vendor-a/one"`` regardless. ``_validate_model_id_list`` rejects a
    blank id on the request path; this function is public, pure and total over
    whatever it is handed, so it answers for the shape rather than assuming it
    away.
    """
    assert moderator_overlap_slots(_slots("vendor-a/one"), moderator_model_id="") == ()
    assert moderator_overlap_slots(_slots("vendor-a/one"), moderator_model_id="   ") == ()
    assert moderator_overlap_slots(_slots("", "vendor-a/one"), moderator_model_id="") == ()
    assert moderator_overlap_slots(_slots("   ", "vendor-a/one"), moderator_model_id=" ") == ()


def test_the_guard_reads_whatever_panel_size_it_is_given() -> None:
    """RED when the guard hardcodes ``EXPECTED_SLOT_COUNT`` (4) by asserting
    on it, or by looping over ``range(4)``.

    NOT by slicing, and an earlier draft of this line wrongly claimed so:
    ``model_slots[:EXPECTED_SLOT_COUNT]`` SURVIVES this test (measured — 14
    passed), because ``ModelSlot`` bounds ``slot_number`` to
    ``EXPECTED_SLOT_COUNT`` so a longer list cannot be built to catch it. That
    mutant becomes observable only when W4 lifts the bound.

    W4 (variable panel size N in {2,3,4}) is an open board row; a guard that
    only works at N=4 would have to be rewritten by it. N stops at 4 here
    because ``ModelSlot`` bounds ``slot_number`` to ``EXPECTED_SLOT_COUNT``,
    so a larger panel is not constructible today — which is W4's job, not
    this guard's.
    """
    two = moderator_overlap_slots(
        _slots("vendor-a/one", "vendor-b/two"),
        moderator_model_id="vendor-b/two",
    )
    assert two == (2,)

    three = moderator_overlap_slots(
        _slots("vendor-a/one", "vendor-b/two", "vendor-c/three"),
        moderator_model_id="vendor-c/three",
    )
    assert three == (3,)


def test_an_empty_panel_reports_nothing() -> None:
    """The anti-vacuity partner for the empty-tuple assertions above: an empty
    result must be reachable for a reason other than "there was no input".

    RED when the guard raises on an empty list instead of returning ``()``.
    """
    assert moderator_overlap_slots([], moderator_model_id="vendor-b/two") == ()


# ---------------------------------------------------------------------------
# The operator surface.
# ---------------------------------------------------------------------------


@pytest.fixture
def restore_debate_model_id() -> Iterator[None]:
    """Restore the process-wide moderator setting after a test moves it."""
    original = settings.debate_model_id
    try:
        yield
    finally:
        settings.debate_model_id = original


def test_status_reports_the_overlapping_slot_numbers(restore_debate_model_id: None) -> None:
    """RED when ``/status`` does not carry the field, or carries a constant.

    The moderator is pointed at whatever slot 2 currently resolves to, so the
    expected answer is the single number 2 — not "some slots" and not "all of
    them". A guard hardwired to report every slot would give ``[1, 2, 3, 4]``
    here and fail.
    """
    client = TestClient(app)
    slots = client.get("/status")  # warm the process; the call below reads defaults
    assert slots.status_code == 200

    from product_app.model_slots import default_model_slots

    panel = default_model_slots()
    settings.debate_model_id = panel[1].model_id

    body = client.get("/status").json()
    assert body["moderator_slot_overlap"] == [panel[1].slot_number]


def test_status_reports_no_overlap_for_a_moderator_off_the_panel(
    restore_debate_model_id: None,
) -> None:
    """The POSITIVE PARTNER for the field: it must be able to say "none".

    RED when the field is hardcoded non-empty, and RED together with the test
    above when the field is hardcoded to any single value.
    """
    settings.debate_model_id = "no-such-vendor/no-such-model"
    body = TestClient(app).get("/status").json()
    assert body["moderator_slot_overlap"] == []


def test_status_survives_a_failing_overlap_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED when the best-effort ``try`` around the read is removed: the
    endpoint 500s instead of answering.

    ``default_moderator_overlap_slots`` consults the model catalog through
    ``default_model_slots``, which is a network-backed service with a fallback
    — it can raise. ``/status`` is the page an operator opens when something is
    already wrong, and it must not be the next thing that breaks. The same
    posture the three spend reads above it take.
    """
    from product_app import main as main_module

    def _boom() -> tuple[int, ...]:
        raise RuntimeError("catalog unavailable")

    monkeypatch.setattr(main_module, "default_moderator_overlap_slots", _boom)
    response = TestClient(app).get("/status")
    assert response.status_code == 200
    assert response.json()["moderator_slot_overlap"] == []


def test_status_names_slot_numbers_and_never_a_model_id(
    restore_debate_model_id: None,
) -> None:
    """``/status`` is unauthenticated and reports STATE, never values —
    ``judge_enabled`` is a bool for exactly this reason.

    RED when the field is widened to carry the model id (or the whole slot
    record) onto the public surface.
    """
    from product_app.model_slots import default_model_slots

    panel = default_model_slots()
    settings.debate_model_id = panel[1].model_id

    body = TestClient(app).get("/status").json()
    reported = body["moderator_slot_overlap"]
    assert isinstance(reported, list)
    # NOT just `all(...)` and a `not in`: both are trivially true over an empty
    # list, and MEASURED, this test passed ALONE against a field hardcoded to
    # `[]`. It was rescued only by its sibling above living in the same file.
    assert reported == [panel[1].slot_number]
    assert all(isinstance(number, int) and not isinstance(number, bool) for number in reported)
    assert panel[1].model_id not in repr(body)
