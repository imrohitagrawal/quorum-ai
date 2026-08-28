"""#382: ``_has_strong_overlap`` counted DEGREE, not a mutual cluster.

``_overlap_partner_counts`` returns, per answer, how many OTHER completed
answers it overlaps with — a per-node DEGREE in the overlap graph.
``_has_strong_overlap`` asked for >=3 nodes with degree >= 2. That is
NECESSARY but NOT SUFFICIENT for three answers to mutually agree, because
4-gram overlap is symmetric but not TRANSITIVE: A~B and B~C does not give
A~C.

## The live reproduction (issue #382, N=4)

The 4-cycle. A overlaps C and D; B overlaps C and D; **A never overlaps B,
and C never overlaps D**::

    degrees [2, 2, 2, 2]   edges (A,C) (A,D) (B,C) (B,D)
    largest set of MUTUALLY overlapping answers = 2

Every answer clears "degree >= 2", so the shipped rule reads the panel
"strong" — a human looking at it sees two disjoint pairs, the 2-vs-2 split
#354 exists to catch. Exhaustive count at N=4 (issue #382, verified
2026-08-26): of 26 degree-based "strong" verdicts, 3 have no mutually
overlapping trio at all.

## Why CONNECTED-COMPONENT is not the fix

A plausible-looking alternative: instead of degree, require the overlap
GRAPH to be connected (or have a component of size >= 3). This does **not**
fix the reproduction above: the 4-cycle *is* one connected component of size
4 (A-C-B-D-A is a cycle through all four nodes). A connected-component check
would still call it "strong". The rule needs an actual CLIQUE — a set of >=3
answers where EVERY pair overlaps — because that is what "these three
answers mutually agree" means. ``test_row_four_cycle_is_connected_but_not_a_
clique`` below pins this distinction directly, so the rejected alternative
cannot be quietly reintroduced.

## The fix

``_has_strong_overlap`` now checks: does there exist a set of >= 3 texts
where every pair overlaps (a triangle in the overlap graph)? Unchanged at
N=3: with only 3 nodes, "all 3 have degree >= 2" already forced every node
to touch both others — i.e. a full triangle — so N=3 behaviour is identical
before and after (pinned by ``test_row_n3_degree_rule_was_already_a_clique_
check``). The change is visible only at N=4, where degree >= 2 no longer
implies mutual overlap. The threshold stays the literal ``3`` — NOT
generalised via ``_required_cluster`` to the panel size. ADR-0075 already
measured why not: at panel_size 2 and 3 that formula returns 2, so an
overlap bar built on it would certify "strong" on a SINGLE EDGE — two
answers sharing opening boilerplate while reaching opposite conclusions.
That decision is unchanged by this fix; ``test_row7_the_overlap_bar_refuses_
a_majority_cluster_that_is_a_single_edge`` in ``test_consensus_is_n_relative.
py`` still pins it.

## Structural change this required

A degree VECTOR alone cannot distinguish a genuine K4 (every pair overlaps)
from the 4-cycle (opposite pairs don't) — both produce ``[2, 2, 2, 2]``.
``_has_strong_overlap`` can no longer be a pure function of
``_overlap_partner_counts``'s output; it needs the full pairwise adjacency.
``_overlap_adjacency`` is the new primitive (an N x N boolean matrix);
``_overlap_partner_counts`` is now DEFINED in terms of it (row sums), so the
two can never drift apart, and every existing consumer of
``_overlap_partner_counts`` (``_opening_majority_flags``, and the row 7-9
controls in ``test_consensus_is_n_relative.py``) is unaffected — verified
below in ``test_partner_counts_is_still_the_adjacency_row_sums``.

INPUT-CLASS TABLE.

  #  population                                              expected
  1  the 4-cycle (issue #382's exact reproduction)            NOT strong  <-- THE FIX
  2  a genuine K4 (every pair overlaps)                       strong      (control)
  3  N=3, all pairwise overlap (a triangle)                   strong      (unchanged)
  4  N=3, single edge only (2 of 3 overlap)                   NOT strong  (unchanged)
  5  the 4-cycle IS one connected component of size 4          — pins why
                                                                  connected-component
                                                                  was rejected
  6  every adjacency matrix at panel sizes 0-5, against an
     independently-written triangle oracle                    identical    <-- THE GUARD
  7  ``_overlap_partner_counts`` == row-sums of
     ``_overlap_adjacency``, for real texts                   identical

WHAT TURNS EACH ROW RED. Measured with a ``cp``-restored copy of
``synthesis_consensus.py``, bytecode caching disabled
(``PYTHONDONTWRITEBYTECODE=1``, ``python -B``), never ``git checkout``:

  A  revert ``_has_strong_overlap`` to the shipped degree-only rule
     (``sum(1 for p in _overlap_partner_counts(texts) if p >= 2) >= 3``)
     -> rows 1 and 6 fail. Row 2, 3, 4 stay GREEN, which is what makes row
     1's failure attributable to the mutuality gap rather than to the
     fixtures (a rule that always said "not strong" would also pass row 1).
  B  clique check changed from "exists a triangle" to "exists an edge"
     (``any(adjacency[i][j] for i,j in combinations(range(n),2))``)
     -> row 4 fails (a single edge would now read "strong"). Row 6 fails
     across most of the space.
  C  clique check changed to require ALL pairs among ALL n texts to overlap
     (a Hamilton-style total-connectivity requirement rather than existence
     of one triangle) -> row 2 stays green (K4 is fully connected) but row 6
     fails: any adjacency matrix with a genuine triangle plus one
     non-overlapping extra node would now read "not strong", which is wrong.
  D  ``_overlap_partner_counts`` reverts to its own independent pairwise
     loop instead of summing ``_overlap_adjacency`` rows -> no test here
     fails (behaviourally identical), but recorded as the reason the row-7
     equivalence test exists: it is the guard against the two drifting
     apart on a FUTURE edit, not against today's code.

  No survivors across A-C.
"""

from __future__ import annotations

import itertools

import pytest

from product_app import synthesis_consensus as sc

# ------------------------------------------------------------------ fixtures
#
# Four texts engineered so the overlap graph is EXACTLY the 4-cycle from the
# issue: A~C, A~D, B~C, B~D; A and B never overlap; C and D never overlap.
# Built from two disjoint 4-gram vocabularies (the ``a*``/``b*`` tokens) so
# the graph shape is exact and verifiable rather than approximate — measured
# below in ``test_row1``, not merely asserted:
#
#   A = "a1..a7"            (4-grams entirely from the A vocabulary)
#   B = "b1..b7"             (4-grams entirely from the B vocabulary, disjoint
#                              from A's, so A~B == 0 as required)
#   C = "a1 a2 a3 a4 b1 b2 b3 b4"   (shares A's FIRST 4-gram and B's FIRST
#                                     4-gram)
#   D = "a4 a5 a6 a7 b4 b5 b6 b7"   (shares A's LAST 4-gram and B's LAST
#                                     4-gram — different grams from C's, so
#                                     C~D == 0 as required)
#
# Measured (see the module docstring's "structural change" section):
# A~C=0.125, A~D=0.125, B~C=0.125, B~D=0.125, A~B=0, C~D=0 — the 4-cycle,
# with every present edge comfortably above ``_OVERLAP_JACCARD_THRESHOLD``
# (0.1).
_A = "a1 a2 a3 a4 a5 a6 a7"
_B = "b1 b2 b3 b4 b5 b6 b7"
_C = "a1 a2 a3 a4 b1 b2 b3 b4"
_D = "a4 a5 a6 a7 b4 b5 b6 b7"

FOUR_CYCLE = [_A, _B, _C, _D]

#: A genuine K4: a shared 9-token core plus a distinct one-token suffix per
#: text. The 6 non-boundary 4-grams of the core are identical across all
#: four, giving every pair Jaccard 0.75 — a real, fully mutual cluster.
_CORE = "c1 c2 c3 c4 c5 c6 c7 c8 c9"
K4_ALIGNED = [f"{_CORE} v1", f"{_CORE} v2", f"{_CORE} v3", f"{_CORE} v4"]

TRIANGLE = K4_ALIGNED[:3]

#: Two answers sharing boilerplate, reaching opposite conclusions, plus one
#: unrelated text — a single edge among 3, from test_consensus_is_n_relative.py.
SINGLE_EDGE_TRIO = [
    "Based on the available evidence, I would recommend we approve the merger outright.",
    "Based on the available evidence, I would recommend we reject the merger outright.",
    "Vitamin D supplementation shows no mortality benefit in the meta-analysis.",
]


def _adjacency_has_triangle_literal(adjacency: list[list[bool]]) -> bool:
    """Independent oracle: does ANY 3 indices have all 3 pairwise edges?

    Written as an explicit triple-nested loop rather than
    ``itertools.combinations`` (which the implementation uses), per the
    repo's "don't share code with the thing under test" convention
    (AGENTS.md rule 7a) — a shared bug in both would otherwise be invisible.
    """
    n = len(adjacency)
    for i in range(n):
        for j in range(i + 1, n):
            if not adjacency[i][j]:
                continue
            for k in range(j + 1, n):
                if adjacency[i][k] and adjacency[j][k]:
                    return True
    return False


def _is_connected_literal(adjacency: list[list[bool]]) -> bool:
    """Independent connected-component check, used only to demonstrate the
    4-cycle is connected (row 5) — never used as an oracle for the fix."""
    n = len(adjacency)
    if n == 0:
        return True
    seen = {0}
    frontier = [0]
    while frontier:
        node = frontier.pop()
        for other in range(n):
            if adjacency[node][other] and other not in seen:
                seen.add(other)
                frontier.append(other)
    return len(seen) == n


# --------------------------------------------------------- the fix itself


def test_row1_the_four_cycle_is_not_strong() -> None:
    """THE FIX. Reproduces #382 exactly: every text has 2 partners, but no
    trio mutually overlaps."""
    assert sc._overlap_partner_counts(FOUR_CYCLE) == [2, 2, 2, 2]
    assert sc._has_strong_overlap(FOUR_CYCLE) is False


def test_row2_a_genuine_k4_is_strong_control() -> None:
    """CONTROL for row 1: the fix does not simply switch the bar off. A real
    unanimous panel (every pair overlaps) must still read strong."""
    assert sc._overlap_partner_counts(K4_ALIGNED) == [3, 3, 3, 3]
    assert sc._has_strong_overlap(K4_ALIGNED) is True


def test_row3_n3_triangle_is_strong_unchanged() -> None:
    assert sc._overlap_partner_counts(TRIANGLE) == [2, 2, 2]
    assert sc._has_strong_overlap(TRIANGLE) is True


def test_row4_n3_single_edge_is_not_strong_unchanged() -> None:
    assert sc._has_strong_overlap(SINGLE_EDGE_TRIO) is False


def test_row5_the_four_cycle_is_connected_but_not_a_clique() -> None:
    """Pins WHY connected-component is the wrong fix. The 4-cycle is a
    single connected component of size 4 (a real alternative fix would need
    to reject it too), yet it contains no triangle. A reviewer proposing
    connected-component instead of clique should see this test fail."""
    adjacency = sc._overlap_adjacency(FOUR_CYCLE)
    assert _is_connected_literal(adjacency) is True
    assert _adjacency_has_triangle_literal(adjacency) is False
    assert sc._has_strong_overlap(FOUR_CYCLE) is False


# ------------------------------------------------- the exhaustive guard


def _all_adjacency_matrices(n: int) -> list[list[list[bool]]]:
    """Every symmetric boolean n x n matrix with a zero diagonal — i.e.
    every possible undirected graph on n labelled nodes."""
    if n == 0:
        return [[]]
    pairs = list(itertools.combinations(range(n), 2))
    matrices = []
    for bits in itertools.product([False, True], repeat=len(pairs)):
        matrix = [[False] * n for _ in range(n)]
        for (i, j), present in zip(pairs, bits, strict=True):
            matrix[i][j] = matrix[j][i] = present
        matrices.append(matrix)
    return matrices


def test_row6_exhaustive_over_every_graph_at_panel_sizes_0_to_5(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE GUARD. Pins the whole decision surface — every possible overlap
    graph, not one shape — against an independently-written oracle.

    A graph on n nodes has ``2 ** C(n, 2)`` possible edge sets: 1 at n=0/1,
    2 at n=2, 8 at n=3, 64 at n=4, 1024 at n=5. All are cheap to enumerate.
    """
    texts_by_size = {n: ["placeholder"] * n for n in range(6)}
    mismatches = []
    for n in range(6):
        for adjacency in _all_adjacency_matrices(n):
            monkeypatch.setattr(sc, "_overlap_adjacency", lambda _t, a=adjacency: a)
            actual = sc._has_strong_overlap(texts_by_size[n])
            expected = n >= 3 and _adjacency_has_triangle_literal(adjacency)
            if actual is not expected:
                mismatches.append((n, adjacency, actual, expected))

    assert mismatches == []

    # Positive partner: prove the oracle (and therefore the fixed function)
    # actually produces BOTH answers somewhere in the space, at sizes where
    # both are reachable — otherwise a function returning False always would
    # pass the loop above vacuously.
    for n in (3, 4, 5):
        verdicts = {
            _adjacency_has_triangle_literal(adjacency) for adjacency in _all_adjacency_matrices(n)
        }
        assert verdicts == {True, False}


def test_partner_counts_is_still_the_adjacency_row_sums() -> None:
    """Regression for every EXISTING consumer of ``_overlap_partner_counts``
    (``_opening_majority_flags``, and rows 7-9 in
    ``test_consensus_is_n_relative.py``): the row-sum relationship must
    hold for real text, not only in the monkeypatched exhaustive test."""
    for texts in (FOUR_CYCLE, K4_ALIGNED, TRIANGLE, SINGLE_EDGE_TRIO):
        adjacency = sc._overlap_adjacency(texts)
        assert sc._overlap_partner_counts(texts) == [sum(row) for row in adjacency]
