"""ADR-0093 decisions 3 and 4: a critic's spend gets its own receipt row.

WHY
---
``writer_cost = debate_total + synthesis_cost`` folds every debate call into
one row whose ``model_id`` is the literal string ``"synthesis"`` and whose label
was fixed to ``"Debate + synthesis"``. Under peer critique the four SLOT models
earn that spend, so a slot's money would render under a row named after the
writer -- the identical defect ADR-0064 fixed for the Layer-B judge, whose own
comment says folding it in "would label spend on a THIRD model as synthesis
spend".

It fixes a NUMBER, not a label. Before this, ``_actual_cost`` priced every
debate call at ``settings.debate_model_id``, so under peer critique four
different models were charged at one model's rate while the receipt still said
``measured``.

Decision 4 renames the writer row ``Synthesis``, because under a fully-eligible
peer run that row holds NO debate spend at all -- the name does not merely
drift, it becomes false.

WHAT TURNS EACH TEST RED: named per test.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from product_app.costs import CostBreakdown, build_measured_breakdown

_SLOTS = [
    ("prov/model-1", "Model 1", Decimal("0.010")),
    ("prov/model-2", "Model 2", Decimal("0.020")),
    ("prov/model-3", "Model 3", Decimal("0.030")),
    ("prov/model-4", "Model 4", Decimal("0.040")),
]


def _measured(**kwargs: object) -> CostBreakdown:
    base: dict[str, object] = {
        "per_model_initial": _SLOTS,
        "debate_by_round": {1: Decimal("0.004"), 2: Decimal("0.004")},
        "synthesis_cost": Decimal("0.050"),
    }
    base.update(kwargs)
    return build_measured_breakdown(**base)  # type: ignore[arg-type]


def test_the_writer_row_is_named_synthesis() -> None:
    """RED WHEN: the row goes back to ``"Debate + synthesis"``.

    Decision 4. Under a fully-eligible peer run no moderator call is made, so
    that row holds no debate spend; keeping the old name repeats the #16
    relabel's defect mirrored -- a name that hides what the row contains.
    """
    breakdown = _measured()
    writer = [line for line in breakdown.by_model if line.kind == "synthesis"]
    assert len(writer) == 1
    assert writer[0].display_name == "Synthesis"
    assert writer[0].model_id == "synthesis"


def test_a_critique_row_is_emitted_per_critic_and_they_come_last() -> None:
    """RED WHEN: critique rows are pooled, dropped, or emitted before the judge.

    Position is defence in depth, not decoration: ``app.js`` used to map
    ``by_model`` rows onto slot cards BY POSITION, so slot rows stay at indices
    0-3 and the writer row at index 4. ``tests/integration/test_cost_gate_js.py``
    pins that index-4 label and is shared with the JavaScript consumer, which is
    why critique rows go after everything, not before.
    """
    breakdown = _measured(
        judge=("judge/model", Decimal("0.005")),
        critique_by_model=[
            ("prov/model-1", "Model 1 (critique)", Decimal("0.001")),
            ("prov/model-2", "Model 2 (critique)", Decimal("0.002")),
        ],
    )
    kinds = [line.kind for line in breakdown.by_model]
    assert kinds == ["model"] * 4 + ["synthesis", "judge", "critique", "critique"], kinds
    assert breakdown.by_model[4].display_name == "Synthesis"


def test_the_composite_key_stays_unique_when_a_critic_is_also_the_judge() -> None:
    """RED WHEN: a critique row reuses ``model_id="synthesis"`` or pools critics.

    ``app.js`` pairs an estimate row to its actual row on the composite key
    ``"{kind} {model_id}"``. It resolves with ``.find()`` -- FIRST MATCH WINS --
    and de-duplicates the backfill with a ``Set`` of those keys, so two rows
    sharing a pair render one figure twice and lose the other, silently
    under-summing the itemized column. The overlap is not hypothetical: the
    moderator defaults to a model that is also slot 2, and nothing forbids the
    judge reusing a slot id either.
    """
    breakdown = _measured(
        judge=("prov/model-2", Decimal("0.005")),
        critique_by_model=[
            ("prov/model-2", "Model 2 (critique)", Decimal("0.001")),
            ("prov/model-1", "Model 1 (critique)", Decimal("0.002")),
        ],
    )
    keys = [f"{line.kind} {line.model_id}" for line in breakdown.by_model]
    assert len(keys) == len(set(keys)), f"duplicate composite key in {keys}"


def test_a_critique_row_never_carries_a_bare_short_name() -> None:
    """RED WHEN: ``display_name`` drops the critique marker.

    ``app.js`` uses ``display_name`` as the ENTIRE visible label, so a bare
    short name prints the same string twice on one receipt with two different
    figures -- a money surface that cannot be read. This is why
    "``app.js:6519`` needs no change" is true and insufficient.
    """
    breakdown = _measured(
        critique_by_model=[("prov/model-1", "Model 1 (critique)", Decimal("0.001"))]
    )
    labels = [line.display_name for line in breakdown.by_model]
    assert len(labels) == len(set(labels)), f"two rows share a visible label: {labels}"


def test_both_partitions_still_sum_to_the_total_with_critique_rows() -> None:
    """RED WHEN: critique rows are appended after reconciliation.

    The UI's reconciliation invariant: every line is >= 0 and the lines sum to
    the quantized total EXACTLY, on both partitions. Appending an unreconciled
    line afterwards makes the partition over-sum by exactly that line.
    """
    # Consistent inputs, as the pricing loop produces them: every critique
    # dollar is ALSO a debate-round dollar, because it is the same dollar seen
    # from the other partition. Handing this function a critique total larger
    # than its debate total is not a case the caller can reach, and it raises
    # rather than silently reconciling -- see ``test_an_impossible_split_is_refused``.
    breakdown = _measured(
        debate_by_round={1: Decimal("0.023"), 2: Decimal("0.027")},
        judge=("judge/model", Decimal("0.005")),
        critique_by_model=[
            ("prov/model-1", "Model 1 (critique)", Decimal("0.011")),
            ("prov/model-2", "Model 2 (critique)", Decimal("0.012")),
            ("prov/model-3", "Model 3 (critique)", Decimal("0.013")),
            ("prov/model-4", "Model 4 (critique)", Decimal("0.014")),
        ],
    )
    assert sum(line.usd for line in breakdown.by_model) == breakdown.total
    assert sum(line.usd for line in breakdown.by_stage) == breakdown.total
    assert all(line.usd >= 0 for line in breakdown.by_model)


def test_critique_spend_still_lands_on_the_debate_stage_lines() -> None:
    """RED WHEN: critique money is moved out of ``by_stage``'s debate rounds.

    The two partitions describe the SAME total from two angles. ``by_model``
    splits critique out per critic; ``by_stage`` keeps it under
    ``debate_round_1``/``debate_round_2``, because that is when it was spent.
    Moving it would break the ``by_stage`` <-> ``by_model`` correspondence,
    which is the reason ADR-0093 rejected folding critique into the slot rows.
    """
    breakdown = _measured(
        debate_by_round={1: Decimal("0.021"), 2: Decimal("0.022")},
        critique_by_model=[
            ("prov/model-1", "Model 1 (critique)", Decimal("0.021")),
            ("prov/model-2", "Model 2 (critique)", Decimal("0.022")),
        ],
    )
    stages = {line.stage: line.usd for line in breakdown.by_stage}
    assert stages["debate_round_1"] > 0
    assert stages["debate_round_2"] > 0


def test_no_critique_rows_means_the_receipt_is_exactly_what_shipped() -> None:
    """RED WHEN: an empty critique list still emits a row, or moves the others.

    The POSITIVE PARTNER for every test above (rule 7): the default deployment
    makes no critique call, so its receipt must be byte-identical to what
    shipped apart from decision 4's rename. A gate that only ever sees the peer
    receipt would not notice the moderator receipt breaking.
    """
    breakdown = _measured(judge=("judge/model", Decimal("0.005")))
    assert [line.kind for line in breakdown.by_model] == [
        "model",
        "model",
        "model",
        "model",
        "synthesis",
        "judge",
    ]
    assert len(breakdown.by_model) == 6


@pytest.mark.parametrize("critique_cost", [Decimal("0"), Decimal("0.5")])
def test_the_writer_row_holds_no_critique_spend(critique_cost: Decimal) -> None:
    """RED WHEN: critique money is summed into the writer row as well as its own.

    Double-counting is the failure the reconciliation above cannot see on its
    own -- the partition would still sum to a total that is itself too large.
    The writer row must equal the MODERATOR debate spend plus synthesis, with
    the critics' share removed.
    """
    breakdown = _measured(
        debate_by_round={1: critique_cost, 2: Decimal("0")},
        synthesis_cost=Decimal("0.050"),
        critique_by_model=(
            [("prov/model-1", "Model 1 (critique)", critique_cost)] if critique_cost else []
        ),
    )
    writer = next(line for line in breakdown.by_model if line.kind == "synthesis")
    critique_total = sum(
        (line.usd for line in breakdown.by_model if line.kind == "critique"), Decimal("0")
    )
    initial_total = sum(
        (line.usd for line in breakdown.by_model if line.kind == "model"), Decimal("0")
    )
    assert writer.usd + critique_total + initial_total == breakdown.total


def test_an_impossible_split_is_refused_rather_than_reconciled() -> None:
    """RED WHEN: an over-large critique total is silently absorbed.

    Critique spend is a SUBSET of debate spend -- the same dollars, seen from
    the other partition -- so a critique total exceeding the debate total is
    incoherent input the pricing loop cannot produce. It must fail loudly: an
    implementation that clamps it would report a receipt whose writer row was
    quietly invented, and "measured" would stop meaning measured.

    This also pins the ``max(Decimal("0"), ...)`` guard as a floor on the
    WRITER row and not as a licence to reconcile nonsense.
    """
    with pytest.raises(ValueError):
        _measured(
            debate_by_round={1: Decimal("0.001"), 2: Decimal("0")},
            critique_by_model=[("prov/model-1", "Model 1 (critique)", Decimal("0.900"))],
        )
