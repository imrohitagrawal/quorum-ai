"""Harvest the three measurements the live-execution window was declared for.

The window declared in ``configs/live-execution-windows.json`` names three
things only a real, paid run can settle:

1. **What eight critique calls actually cost.** SETTLED on 2026-09-06 by the
   run ADR-0102 records (41,644 input tokens, receipt $0.0806), which unblocked
   W3/ADR-0094. Still reported here so a second run can be compared against it
   at the new cap — the cost moves with the cap even though the settled
   question does not.
2. **Whether ``DEBATE_ROUND_MAX_TOKENS`` still fits**, read off
   ``finish_reason`` on the rows of BOTH debate rounds -- ``debate.py``
   dispatches them through one seam with one ``max_tokens``, so reading round 2
   alone inspects half the calls the constant governs. The 2026-09-06 run put a
   FLOOR under the requirement (four of eight critique calls clipped at 2000,
   three of them in round 2) and no ceiling; the cap is 4000 now.
3. **Whether OpenRouter's ``:online`` annotations carry passage CONTENT**,
   which decides whether the judge can be given its sources (#447) without a
   new outbound fetcher.

This script reads ``telemetry-tokens.jsonl`` and prints all three. It computes
no policy and changes no constant; like
``scripts/telemetry_classification_report.py``, which it is modelled on, it is
decision SUPPORT and not a decision.

Usage::

    python scripts/window_measurement_report.py [directory] [--run <query_run_id>]

``--run`` is REQUIRED whenever the file holds more than one correlated run,
which the production volume normally does. Without it the report prints every
run, chooses no headline, and exits non-zero: guessing which run the money was
spent on is the one thing it must not do.

``directory`` defaults to ``$TELEMETRY_LOG_DIR`` — the same variable
``telemetry_sink.py`` reads to decide where to WRITE. Production sets it to
the mounted ``/data`` volume (``fly.toml``). A DIRECTORY and not a file, so
the harvest command can hand it whatever it copied the volume into.

TWO DELIBERATE DEPARTURES FROM THE PRECEDENT SCRIPT
---------------------------------------------------
**It refuses empty input.** ``telemetry_classification_report.py`` exits 0
over zero rows, printing a clean "insufficient data" line. Every reading here
is a negative check — "no row said ``length``", "no annotation carried
content" — and a negative check over zero rows is trivially true. This repo has
measured what that costs: 13 of 21 CI jobs could reach a terminal status having
measured nothing, four of them blocking. So: exit non-zero and say NO DATA.

**It scopes every reading to ONE NAMED run.** ``/data`` is a persistent volume that
already holds runs taken under DIFFERENT limits — the 2026-09-06 run ran at
``DEBATE_ROUND_MAX_TOKENS = 2000`` and clipped 3 of 4 round-2 replies; the cap
is 4000 today. Pooling those rows would answer measurement 2 wrongly, and
wrongly in the PESSIMISTIC direction: clipping that a superseded cap caused
would be read as clipping the current one causes, and the obvious response
would be to raise a cap that was already big enough. Every number below is
per-``query_run_id``, and the headline is the newest run only.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

#: The file this reads, inside the directory it is given. Named the same way
#: ``telemetry_classification_report.py`` names its own inputs, so the two
#: scripts take the same argument and cannot be handed a path in one shape and
#: a path in the other.
TOKENS_FILE_NAME = "telemetry-tokens.jsonl"

#: What a census reports for a row that predates the field it is counting.
#: Spelled with angle brackets so it can never collide with a real label — every
#: closed-set value in ``providers`` is a bare lowercase word.
FIELD_MISSING = "<field missing>"

#: Refuse when more than this share of usable lines failed to parse. A
#: JUDGEMENT, not a measurement, and stated as one: the harvest pipes
#: ``fly ssh console -C "cat …"`` into a file, which can prepend a connection
#: banner and can tear the tail of a live append-only file, so a handful of bad
#: lines is normal and a majority of them means the copy went wrong. Below the
#: threshold the count is still PRINTED -- silence about dropped lines is the
#: defect, not the dropping.
MAX_UNPARSABLE_SHARE = 0.05

#: The one message this stream carries. Rows with any other message are not
#: token rows and must not be counted as though they were.
TOKEN_EVENT = "provider_call_tokens"

#: Stage names, verbatim from ``telemetry_sink.TELEMETRY_STAGES``. Copied
#: rather than imported so the script runs against a harvested file with no
#: ``src`` on the path — this is invoked as ``python scripts/...``, not
#: ``uv run``, in the harvest procedure. A copy that nothing compares is a copy
#: that drifts, and a drifted stage name here would make every reading for that
#: stage silently return zero — so
#: ``tests/unit/test_window_measurement_report.py`` compares this tuple
#: against ``telemetry_sink.TELEMETRY_STAGES`` in
#: ``test_the_stage_names_match_the_ones_the_product_emits``.
STAGE_DEBATE_ROUND_1 = "debate_round_1"
STAGE_DEBATE_ROUND_2 = "debate_round_2"
STAGE_JUDGE = "judge"
#: The full stage vocabulary. Consulted by no lookup in this script —
#: ``CRITIQUE_STAGES`` and ``STAGE_JUDGE`` carry those — and kept anyway as the
#: SUBJECT of the drift guard: a stage renamed in ``telemetry_sink`` and not
#: here turns that test red, which is the only mechanism comparing this copy to
#: the tree. Recorded plainly rather than left to look like dead code.
STAGE_NAMES = (
    "initial_answers",
    STAGE_DEBATE_ROUND_1,
    STAGE_DEBATE_ROUND_2,
    "synthesis",
    STAGE_JUDGE,
)

#: The two stages a peer-critique run bills its critique calls to. Measurement
#: 1 is "what did eight critique calls cost", and eight is four critics in each
#: of two rounds.
CRITIQUE_STAGES = (STAGE_DEBATE_ROUND_1, STAGE_DEBATE_ROUND_2)


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    """``(parsed rows, lines that could not be used)``.

    A torn last line is the normal state of an append-only file being copied
    off a live volume, so skipping one is right. Skipping it SILENTLY is not:
    an earlier version of this function said the count was "reported by the
    caller" while returning no count at all, and a file of 200 torn lines plus
    one good row produced a full confident verdict set at exit 0. The count is
    now returned, printed, and enforced by :data:`MAX_UNPARSABLE_SHARE`.

    The MISSING-file case is not distinguished from the empty-file case: both
    mean "no measurement", both are refused by :func:`main`, and the refusal
    names the path either way.
    """
    if not path.exists():
        return [], 0
    rows: list[dict[str, Any]] = []
    skipped = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
        else:
            # Valid JSON that is not an object -- a bare number or string. Not
            # a telemetry record, and counting it as usable would let a file of
            # them satisfy the non-empty check.
            skipped += 1
    return rows, skipped


def token_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only the ``provider_call_tokens`` records."""
    return [row for row in rows if row.get("message") == TOKEN_EVENT]


#: The key the uncorrelated rows are collected under. Never a run id — see
#: :func:`group_by_run`.
UNCORRELATED = ""


def group_by_run(
    rows: list[dict[str, Any]],
) -> tuple[list[str], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """``(correlated run ids oldest-first, rows per run, uncorrelated rows)``.

    **The uncorrelated rows are returned SEPARATELY and are never a run.** An
    earlier version put them in the same dict under ``""`` and gave them the
    full verdict machinery, which reproduced word for word the pooling failure
    this script exists to prevent: two runs at two different caps landed in one
    bucket and printed ``CLIPPED — 3 of 8 … at cap(s) [2000, 4000]``.

    That is not a corner case on the file this will be pointed at. ADR-0102
    measured ``/data``: **108 records, of which 18 carry the correlator** — so
    83% of the real file has no ``query_run_id``. And they can take the
    headline: ``evaluation.py`` passes ``telemetry_labels=None`` for the JUDGE
    call when the run id is absent, and the judge is a run's LAST stage, so its
    uncorrelated row is the last row in the file.

    Correlated runs are ordered by FILE POSITION of each run's LAST row, not by
    the ``timestamp`` field. The stream is append-only, so position is a fact
    about the file; ``timestamp`` is a field this script would have to trust a
    record to have set. Position also survives a row that lost its timestamp,
    and orders two INTERLEAVED runs by which finished last.

    Ordering decides only the PRINT order. It never decides which run is
    reported on — that is ``--run``'s job, because a second user's query on a
    live ``/ui`` lands in the same file and picking by recency once printed the
    exact opposite of the paid run's result in both money directions.
    """
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    uncorrelated: list[dict[str, Any]] = []
    last_seen: dict[str, int] = {}
    for position, row in enumerate(rows):
        run_id = row.get("query_run_id")
        if not isinstance(run_id, str) or not run_id:
            uncorrelated.append(row)
            continue
        grouped[run_id].append(row)
        last_seen[run_id] = position
    ordered = sorted(grouped, key=lambda key: last_seen[key])
    return ordered, dict(grouped), uncorrelated


def _ints(rows: list[dict[str, Any]], field: str) -> list[int]:
    """Every integer value of ``field``, skipping rows that do not carry one.

    ``bool`` is excluded explicitly: it is an ``int`` subclass, and a
    ``True`` sliding into a token distribution would be a 1 nobody could see.
    """
    values = []
    for row in rows:
        value = row.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            values.append(value)
    return values


def measurement_1_critique_cost(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """What the critique calls cost, in TOKENS.

    Deliberately NOT in dollars. The run's own receipt computes the money from
    provider prices, and a second dollar figure derived here would compete with
    it — two numbers for one fact is how they come to disagree. Tokens are what
    this stream measures; the receipt is what prices them.
    """
    per_stage: dict[str, dict[str, int]] = {}
    for stage in CRITIQUE_STAGES:
        stage_rows = [row for row in rows if row.get("stage") == stage]
        if not stage_rows:
            continue
        per_stage[stage] = {
            "calls": len(stage_rows),
            "prompt_tokens": sum(_ints(stage_rows, "prompt_tokens")),
            "completion_tokens": sum(_ints(stage_rows, "completion_tokens")),
            "usage_absent": sum(1 for row in stage_rows if row.get("usage_absent") is True),
        }
    return {
        "per_stage": per_stage,
        "calls": sum(entry["calls"] for entry in per_stage.values()),
        "prompt_tokens": sum(entry["prompt_tokens"] for entry in per_stage.values()),
        "completion_tokens": sum(entry["completion_tokens"] for entry in per_stage.values()),
    }


#: What a complete peer-critique run bills to the two debate stages: four
#: critics in each of two rounds. Used ONLY to say whether the cost total is
#: complete -- never to reject a run, because a run with fewer eligible critics
#: is a legitimate shape (``debate.py`` falls back to the moderator when no
#: critic is eligible), and it is the SILENCE about incompleteness that misleads.
EXPECTED_CRITIQUE_CALLS = 8


def _verdict_1(result: dict[str, Any]) -> str:
    """Whether the critique cost total is complete, or only part of one.

    Measurement 1 had no verdict at all, so a partial total read exactly like a
    complete one. Two demonstrated ways that misleads: a run whose calls were
    dispatched and failed before telemetry reported 4 of 8 calls, which against
    ADR-0102's 41,644 input tokens reads as the new cap HALVING critique cost;
    and a run straddling a log rotation reported its tail with nothing saying so.
    """
    calls = result["calls"]
    if calls == 0:
        return "NO CRITIQUE ROWS — nothing to total."
    if calls < EXPECTED_CRITIQUE_CALLS:
        return (
            f"FEWER THAN A FULL PEER ROUND — {calls} of the {EXPECTED_CRITIQUE_CALLS} "
            f"calls a full peer round bills. This report cannot tell WHY, and the two "
            f"cases have opposite meanings: a moderator-shape run (peer critique off, "
            f"or no eligible critic) bills exactly this many and the totals ARE its "
            f"cost; a run that lost calls to failure or a log rotation has totals that "
            f"are only a floor. Moderator rows carry no slot_number — check that "
            f"before reading the totals as complete."
        )
    if calls > EXPECTED_CRITIQUE_CALLS:
        return (
            f"MORE THAN EXPECTED — {calls} calls against the {EXPECTED_CRITIQUE_CALLS} "
            f"a full peer round bills. These rows may span more than one run."
        )
    return f"COMPLETE — all {EXPECTED_CRITIQUE_CALLS} critique calls are present."


def measurement_2_debate_fit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Did the debate replies fit inside the cap they were given?

    **BOTH ROUNDS, and that is a correctness fix, not thoroughness.**
    ``debate.py`` dispatches round 1 and round 2 through ONE seam with ONE
    ``max_tokens=DEBATE_ROUND_MAX_TOKENS``. Reading only ``debate_round_2``
    inspects four of the eight calls that constant governs — and ADR-0102's own
    table records the previous run's ROUND 1 slot 4 stopping at 2000/length. A
    round-2-only reading would have printed FITS while half the calls the cap
    governs were still being truncated at full price, and there was no verdict
    it could print for that outcome.

    The per-round split is kept in the output because the rounds are not
    equally expensive to clip: ADR-0096 made round 2 carry a critique, a
    self-assessment, sources AND a revised answer, and ``synthesis`` reads
    those revised answers.

    The cap is read off the ROWS and never off ``debate.DEBATE_ROUND_MAX_TOKENS``:
    a harvested file may predate the constant's current value, and asserting a
    historic run against today's constant is how a superseded cap gets read as
    the current one.
    """
    stage_rows = [row for row in rows if row.get("stage") in CRITIQUE_STAGES]
    reasons = Counter(str(row.get("finish_reason", FIELD_MISSING)) for row in stage_rows)
    completions = _ints(stage_rows, "completion_tokens")
    caps = sorted(set(_ints(stage_rows, "max_tokens")))
    per_round = {}
    for stage in CRITIQUE_STAGES:
        subset = [row for row in stage_rows if row.get("stage") == stage]
        if subset:
            per_round[stage] = {
                "calls": len(subset),
                "clipped": sum(1 for r in subset if r.get("finish_reason") == "length"),
                "completion_max": max(_ints(subset, "completion_tokens"), default=None),
            }
    return {
        "calls": len(stage_rows),
        "finish_reasons": dict(reasons),
        "clipped": reasons.get("length", 0),
        "caps_seen": caps,
        "completion_max": max(completions) if completions else None,
        "completion_tokens": sorted(completions, reverse=True),
        "per_round": per_round,
    }


def measurement_3_annotations(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Do the ``:online`` annotations carry passage CONTENT? (#447)

    **Every reading here is scoped to the rows that ASKED for search.** The
    product appends ``:online`` only on the per-slot answer path, so debate,
    synthesis and judge rows carry ``search_enabled: false`` -- unless an
    operator's configured model id itself ends in ``:online``, which
    ``search_enabled`` would then report honestly. Pooling those rows floods
    the census with ``absent`` and makes a run look like the provider sends
    nothing. On a real run they are most of the rows.

    The three readings, and the LAST one is the answer to #447:

    * how many calls asked for search at all — the POSITIVE PARTNER. "No
      annotation carried content" is trivially true of a run that never
      switched search on;
    * the ``annotation_shape`` and ``annotation_sites`` census. ``sites`` is
      what makes ``absent`` attributable: ``absent`` with ``sites=none`` is a
      statement about the provider, and ``absent`` with any other site means
      the annotations were somewhere our fold does not read. ``usable`` is
      ADR-0084's question measured rather than inferred;
    * whether ``annotation_content_chars`` was ever present AND non-zero.
    """
    searching = [row for row in rows if row.get("search_enabled") is True]
    # PER CALL, not per run. An earlier version gated the "our reader missed
    # them" reading on ``annotations_total == 0`` for the WHOLE run, so a single
    # annotation reaching ``delta`` anywhere disabled it -- including for calls
    # whose content sat at a site the fold does not read. Minimal reproduction:
    # ONE call whose delta carried a content-free citation while the terminal
    # message carried a 1,500-character passage printed ROUTE B, with the sites
    # census contradicting it one line above.
    # A call is MISSED only when the fold's own site collected nothing from it.
    # ``annotation_sites`` is a SET joined with commas, accumulated across every
    # frame of ONE call, so a call whose annotations reached ``delta`` AND a
    # terminal ``message`` records "delta,message" -- and the delta half WAS
    # collected. An earlier predicate asked "is ANY site outside delta?", which
    # counted such a call as fully missed and printed "nothing they carried is
    # in any reading below" directly above two readings derived from those very
    # calls. Self-contradictory, and it pushed the reader toward Route B.
    missed = [
        row
        for row in searching
        if "delta" not in str(row.get("annotation_sites", FIELD_MISSING)).split(",")
        and any(
            site not in {"none", FIELD_MISSING, ""}
            for site in str(row.get("annotation_sites", FIELD_MISSING)).split(",")
        )
    ]
    # Calls we DID read that also had annotations somewhere we do not. Not
    # missed -- but a reader deciding Route A should know the sample is partial.
    partly_missed = [
        row
        for row in searching
        if "delta" in str(row.get("annotation_sites", "")).split(",")
        and any(
            site not in {"delta", "none", FIELD_MISSING, ""}
            for site in str(row.get("annotation_sites", "")).split(",")
        )
    ]
    shapes = Counter(str(row.get("annotation_shape", FIELD_MISSING)) for row in searching)
    sites = Counter(str(row.get("annotation_sites", FIELD_MISSING)) for row in searching)
    with_field = [row for row in searching if "annotation_content_chars" in row]
    chars = _ints(with_field, "annotation_content_chars")
    content_shapes = Counter(
        str(row.get("annotation_content_shape", FIELD_MISSING)) for row in with_field
    )
    return {
        "calls": len(rows),
        "searching_calls": len(searching),
        "captured_calls": sum(1 for row in searching if "annotation_shape" in row),
        "shapes": dict(shapes),
        "sites": dict(sites),
        "content_shapes": dict(content_shapes),
        "field_absent_calls": len(searching) - len(with_field),
        "content_present_calls": len(with_field),
        "content_zero_calls": sum(1 for value in chars if value == 0),
        "content_chars_total": sum(chars),
        "content_chars_max": max(chars) if chars else None,
        "annotations_total": sum(_ints(searching, "annotation_count")),
        "arrivals_total": sum(_ints(searching, "annotation_arrivals")),
        "usable_total": sum(_ints(searching, "annotation_usable_count")),
        "missed_site_calls": len(missed),
        "missed_sites": sorted(
            {
                site
                for row in missed
                for site in str(row.get("annotation_sites", "")).split(",")
                if site not in {"delta", "none", FIELD_MISSING, ""}
            }
        ),
        "partly_missed_calls": len(partly_missed),
        "partly_missed_sites": sorted(
            {
                site
                for row in partly_missed
                for site in str(row.get("annotation_sites", "")).split(",")
                if site not in {"delta", "none", FIELD_MISSING, ""}
            }
        ),
    }


def judge_tokens(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """What the judge leg cost, in tokens."""
    stage_rows = [row for row in rows if row.get("stage") == STAGE_JUDGE]
    return {
        "calls": len(stage_rows),
        "prompt_tokens": sum(_ints(stage_rows, "prompt_tokens")),
        "completion_tokens": sum(_ints(stage_rows, "completion_tokens")),
        "finish_reasons": dict(
            Counter(str(row.get("finish_reason", FIELD_MISSING)) for row in stage_rows)
        ),
    }


#: ``finish_reason`` values that carry NO information about whether the cap
#: fitted. ``absent`` is ``providers.FINISH_REASON_ABSENT``, returned when the
#: envelope said nothing -- a real production value: a stream that ends
#: ``[DONE]`` without ever sending a reason passes the incompleteness guard and
#: is served and priced as a normal answer. ``<missing>`` is this script's own
#: marker for a row predating the field (it entered the stream on 2026-08-30,
#: and ``/data`` is a persistent volume holding older runs).
_UNINFORMATIVE_FINISH_REASONS = frozenset({"absent", FIELD_MISSING})


def _verdict_2(result: dict[str, Any]) -> str:
    """The debate-fit verdict, or a refusal.

    ORDER MATTERS AND WAS GOT WRONG ONCE. Positive evidence is read FIRST:
    a row that said ``length``, or a reply that landed exactly on the cap, is
    a demonstrated fact about the cap whatever the other rows failed to say.
    An earlier version put the "some rows are uninformative" refusal above the
    ceiling check, so one row with no usable ``finish_reason`` destroyed an
    at-the-cap reading — the same "any missing row vetoes everything" defect
    ``_verdict_3`` had already been fixed for, reintroduced ten lines away.

    Only when NOTHING could have answered does it refuse.
    """
    calls = result["calls"]
    if calls == 0:
        return (
            "NO DEBATE ROWS — no debate_round_1 or debate_round_2 token rows are "
            "present. Either the rounds did not run, or every call failed before "
            "telemetry (the token row is written on the success path only). This "
            "run cannot say which."
        )
    caps = result["caps_seen"]
    longest = result["completion_max"]
    uninformative = sum(
        count
        for reason, count in result["finish_reasons"].items()
        if reason in _UNINFORMATIVE_FINISH_REASONS
    )
    partial = (
        ""
        if uninformative == 0
        else f" ({uninformative} of {calls} row(s) carried no usable finish_reason)"
    )

    # POSITIVE EVIDENCE FIRST — including across mixed caps: a reply that said
    # 'length' clipped at whatever cap it was given, and refusing to say so
    # because a NEIGHBOUR had a different cap discards a demonstrated fact. An
    # earlier version put the mixed-cap refusal above this, which was the one
    # refusal round 3 did not move below the evidence.
    if result["clipped"]:
        where = ", ".join(
            f"{stage} {entry['clipped']}/{entry['calls']}"
            for stage, entry in result["per_round"].items()
            if entry["clipped"]
        )
        # WHICH round matters and the pooled sentence hid it: ADR-0096 made
        # round 2 carry the revised answer synthesis reads, so a round-2 clip
        # cuts the source-backed answer while a round-1 clip cuts a critique.
        # Two opposite run shapes previously produced a byte-identical verdict.
        return (
            f"CLIPPED — {result['clipped']} of {calls} debate replies stopped on "
            f"'length' at cap(s) {caps} ({where}). The cap did NOT fit.{partial}"
        )
    if caps and longest is not None and longest > min(caps):
        return (
            f"OVER THE CAP — the longest reply is {longest} tokens against cap "
            f"{min(caps)}. That should not be possible and is not the "
            f"exactly-at-the-cap signal; do not read it as either fitting or clipped "
            f"until the rows are explained.{partial}"
        )
    if caps and longest is not None and longest == min(caps):
        return (
            f"AT THE CEILING — 0 of {calls} replies said 'length', but the longest "
            f"reply is {longest} tokens against cap {min(caps)}. ADR-0102: a clipped "
            f"reply reports exactly the cap. Treat this as clipped, not as "
            f"fitting.{partial}"
        )

    if len(caps) > 1:
        return (
            f"NOT COMPARABLE — no reply clipped, but these rows span "
            f"{len(caps)} different caps {caps}. 'Nothing clipped' cannot be read as "
            f"'the cap fits' when the rows were not all given the same cap."
        )
    # Only now can a missing reason change the answer.
    if uninformative:
        return (
            f"NOT MEASURED — {uninformative} of {calls} debate row(s) carry no usable "
            f"finish_reason ({result['finish_reasons']}), none reported 'length', and "
            f"no reply reached the cap. This run cannot say whether the cap fitted."
        )
    if not caps:
        return (
            f"NO CAP RECORDED — {calls} row(s) carry no max_tokens, so there is "
            f"nothing to compare the longest reply ({longest}) against."
        )
    return (
        f"FITS — 0 of {calls} debate replies stopped on 'length'. "
        f"Longest reply {longest} completion tokens against cap(s) {caps}."
    )


#: Below this, a "content key was present" reading is not evidence that passage
#: TEXT arrives. A JUDGEMENT, stated as one: a 1-character content field and a
#: 1,400-character passage produced the same verdict word, and the decision
#: Route A turns on is whether there is enough text to check an answer against.
MIN_PASSAGE_CHARS = 200


def _verdict_3(result: dict[str, Any]) -> list[str]:
    """The Route A / Route B reading, as one or more lines.

    A LIST, not a string, because a run can be two things at once: some calls
    can carry readable content while others put their annotations at a site the
    fold never reads. Collapsing that into one verdict is what produced
    ``ROUTE B`` on a run with 2,600 characters of passage text on the wire.
    """
    lines: list[str] = []
    searching = result["searching_calls"]
    if searching == 0:
        return [
            f"NO SEARCHING CALLS — none of the {result['calls']} row(s) set ':online', "
            "so this run says NOTHING about whether annotations carry content."
        ]
    captured = result["captured_calls"]
    if captured == 0:
        return [
            f"BUILD TOO OLD — none of the {searching} searching call(s) carry an "
            "annotation_shape field. This run predates the capture; it cannot answer "
            "measurement 3."
        ]
    if captured != searching:
        lines.append(
            f"CAVEAT — {searching - captured} of {searching} searching row(s) predate "
            f"the capture and are excluded from the readings below."
        )

    # PER CALL, and reported BEFORE the content verdict: these calls' content
    # was never observable, so no content reading covers them.
    if result["missed_site_calls"]:
        lines.append(
            f"OUR READER MISSED {result['missed_site_calls']} CALL(S) ENTIRELY — their "
            f"annotations were only at {result['missed_sites']}, and the fold collects "
            f"from choices[0].delta only. Those calls contribute NOTHING to the "
            f"readings below. This is a defect in our reassembler, not an answer "
            f"about the provider."
        )
    if result["partly_missed_calls"]:
        lines.append(
            f"PARTIAL SAMPLE — {result['partly_missed_calls']} call(s) had annotations "
            f"at {result['partly_missed_sites']} AS WELL AS at delta. What reached "
            f"delta is measured below; what did not is invisible, so the readings are "
            f"a floor for those calls."
        )

    if result["annotations_total"] == 0:
        if not result["missed_site_calls"]:
            lines.append(
                f"NO ANNOTATIONS ON THE WIRE — search was on, and no annotations key "
                f"appeared at any site we look at (sites={result['sites']}). On this "
                f"evidence the provider sent none. NOTE: frames after the [DONE] "
                f"sentinel are drained without being read, so this cannot speak for "
                f"annotations sent there."
            )
        return lines

    usable = result["usable_total"]
    if usable:
        lines.append(
            f"ADR-0084 — the annotations path yielded {usable} source(s) from "
            f"{result['annotations_total']} distinct annotation(s). The path is ALIVE."
        )
    else:
        lines.append(
            f"ADR-0084 — the annotations path yielded 0 sources from "
            f"{result['annotations_total']} distinct annotation(s). The path produced "
            f"NOTHING, so Route A needs TWO fixes: read the content, and repair "
            f"_extract_citations so there is something to attach it to."
        )

    if result["content_present_calls"] == 0:
        lines.append(
            "ROUTE B — annotations arrived but NO searching call carried a content "
            "key. The judge cannot be given passage text without a fetcher (#447)."
        )
    elif not result["content_chars_total"]:
        lines.append(
            f"ROUTE A UNPROVEN — a content key was present on "
            f"{result['content_present_calls']} call(s) and yielded ZERO characters on "
            f"all of them (shapes={result['content_shapes']}). The field exists, so "
            f"Route A is not refuted — but nothing here shows passage text arrives."
        )
    elif (result["content_chars_max"] or 0) < MIN_PASSAGE_CHARS:
        lines.append(
            f"ROUTE A THIN — content arrived but the largest single call held only "
            f"{result['content_chars_max']} characters, under the "
            f"{MIN_PASSAGE_CHARS}-character floor. A snippet is not a passage; this "
            f"does not show the judge could check an answer against it."
        )
    else:
        lines.append(
            f"ROUTE A POSSIBLE — {result['content_present_calls']} call(s) carried a "
            f"content key, {result['content_chars_total']} characters in total "
            f"(largest single call {result['content_chars_max']}, "
            f"shapes={result['content_shapes']})."
        )
    return lines


def format_run(run_id: str, rows: list[dict[str, Any]], *, headline: bool) -> str:
    m1 = measurement_1_critique_cost(rows)
    m2 = measurement_2_debate_fit(rows)
    m3 = measurement_3_annotations(rows)
    judge = judge_tokens(rows)
    stamps = sorted(str(row.get("timestamp", "")) for row in rows if row.get("timestamp"))
    window = f"{stamps[0]} .. {stamps[-1]}" if stamps else "(no timestamps)"
    lines = [
        f"{'>>> SELECTED RUN' if headline else '    run'}  {run_id}",
        f"      rows={len(rows)}  {window}",
        f"      stages={sorted({str(r.get('stage')) for r in rows})}",
        "",
        f"      M1 critique cost — {m1['calls']} call(s) across "
        f"{sorted(m1['per_stage'])}: {m1['prompt_tokens']} prompt + "
        f"{m1['completion_tokens']} completion tokens",
    ]
    for stage in CRITIQUE_STAGES:
        entry = m1["per_stage"].get(stage)
        if entry is not None:
            lines.append(
                f"         {stage}: {entry['calls']} call(s), "
                f"{entry['prompt_tokens']} prompt + {entry['completion_tokens']} completion, "
                f"usage_absent on {entry['usage_absent']}"
            )
    lines.append(f"         -> {_verdict_1(m1)}")
    lines += [
        "",
        f"      M2 debate fit (BOTH rounds — one cap governs both) — "
        f"finish_reasons={m2['finish_reasons']}",
    ]
    for stage, entry in m2["per_round"].items():
        lines.append(
            f"         {stage}: {entry['calls']} call(s), {entry['clipped']} clipped, "
            f"longest {entry['completion_max']}"
        )
    lines += [
        f"         completion tokens (desc): {m2['completion_tokens'][:8]}",
        f"         -> {_verdict_2(m2)}",
        "",
        f"      M3 annotations — searching_calls={m3['searching_calls']}/{m3['calls']}, "
        f"captured={m3['captured_calls']}",
        f"         shapes={m3['shapes']}  sites={m3['sites']}",
        f"         annotations={m3['annotations_total']} distinct "
        f"({m3['arrivals_total']} arrivals)  usable={m3['usable_total']}",
        f"         content key: present on {m3['content_present_calls']}, "
        f"absent on {m3['field_absent_calls']}, zero-length on "
        f"{m3['content_zero_calls']}, shapes={m3['content_shapes']}",
    ]
    lines += [f"         -> {line}" for line in _verdict_3(m3)]
    lines += [
        "",
        f"      judge — {judge['calls']} call(s), {judge['prompt_tokens']} prompt + "
        f"{judge['completion_tokens']} completion tokens, "
        f"finish_reasons={judge['finish_reasons']}",
    ]
    return "\n".join(lines)


def format_uncorrelated(rows: list[dict[str, Any]]) -> str:
    """A CENSUS for the rows carrying no ``query_run_id``. Never a verdict."""
    caps = sorted(set(_ints(rows, "max_tokens")))
    stages = sorted({str(row.get("stage")) for row in rows})
    return (
        f"    {len(rows)} row(s) carry NO query_run_id and belong to no run here.\n"
        f"      stages={stages}  caps={caps}\n"
        f"      -> NOT A RUN. No verdict is printed for these: they may span several "
        f"runs at several caps, and pooling them is the exact error this report "
        f"exists to avoid."
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    wanted_run: str | None = None
    if args.count("--run") > 1:
        # A report whose contract is "there is no honest way to guess which run"
        # must not silently honour the first of two.
        print("NO DATA: --run was given more than once.", file=sys.stderr)
        return 2
    if "--run" in args:
        index = args.index("--run")
        if index + 1 >= len(args):
            print("NO DATA: --run needs a query_run_id.", file=sys.stderr)
            return 2
        wanted_run = args[index + 1]
        del args[index : index + 2]
    # ``--run=<id>`` is a standard GNU form. Unhandled, it was read as a
    # DIRECTORY and the reader was told to re-copy the volume of a paid run.
    unknown = [a for a in args if a.startswith("-")]
    if unknown:
        hint = " Use '--run <id>', with a space." if any("--run=" in a for a in unknown) else ""
        print(f"NO DATA: unrecognised argument(s) {unknown}.{hint}", file=sys.stderr)
        return 2
    if len(args) > 1:
        print(
            f"NO DATA: more than one directory given ({args}). Reading the first "
            "silently is how the wrong harvest gets reported.",
            file=sys.stderr,
        )
        return 2
    directory = args[0] if args else os.environ.get("TELEMETRY_LOG_DIR", "")
    if not directory:
        print(
            "NO DATA: no directory given and TELEMETRY_LOG_DIR is unset. Pass the "
            "directory holding " + TOKENS_FILE_NAME + ", e.g. the copied /data path.",
            file=sys.stderr,
        )
        return 2

    root = Path(directory)
    path = root / TOKENS_FILE_NAME
    all_rows, skipped = read_jsonl(path)
    rows = token_rows(all_rows)
    if not rows:
        print(
            f"NO DATA: {path} holds no '{TOKEN_EVENT}' rows ({len(all_rows)} other "
            f"record(s), {skipped} unparsable line(s)). Nothing here is measured; no "
            "verdict is printed. Check that the harvest copied the right file and that "
            "the build under test emits the token stream.",
            file=sys.stderr,
        )
        return 1

    considered = len(all_rows) + skipped
    if considered and skipped / considered > MAX_UNPARSABLE_SHARE:
        print(
            f"NO DATA: {skipped} of {considered} line(s) in {path} could not be parsed "
            f"({skipped / considered:.0%}, over the {MAX_UNPARSABLE_SHARE:.0%} ceiling). "
            "A verdict from the remainder would be confident about a file that did not "
            "copy cleanly. Re-run the harvest.",
            file=sys.stderr,
        )
        return 1

    ordered, grouped, uncorrelated = group_by_run(rows)
    print(f"Window measurement report — {path}")
    print(
        f"{len(rows)} token row(s), {len(ordered)} correlated run(s), "
        f"{len(uncorrelated)} uncorrelated row(s), {skipped} unparsable line(s)."
    )
    print(f"Reads {TOKENS_FILE_NAME} only — rotated backups (.1-.4) are NOT included.")
    print()

    if wanted_run is not None and wanted_run not in grouped:
        print(
            f"NO DATA: no run '{wanted_run}' in {path}. Runs present: {ordered or '(none)'}.",
            file=sys.stderr,
        )
        return 1

    if not ordered:
        print("NO CORRELATED RUNS — every row lacks a query_run_id.")
        print(format_uncorrelated(uncorrelated))
        print()
        return 1

    # THE REFUSAL TO GUESS. With more than one run in the file and no --run,
    # there is no honest way to say which one the money was spent on: a second
    # user's query on a live /ui lands here too, and a headline pointing at it
    # printed the exact opposite of the paid run's result in both directions --
    # keep a cap that does not fit, AND build a fetcher the data says is
    # unnecessary. Every run is still printed; only the headline is withheld.
    if wanted_run is None and len(ordered) > 1:
        for run_id in ordered:
            print(format_run(run_id, grouped[run_id], headline=False))
            print()
        if uncorrelated:
            print(format_uncorrelated(uncorrelated))
            print()
        print(
            f"AMBIGUOUS: {len(ordered)} correlated runs are present and none was "
            f"named. This report will not guess which one you paid for. Re-run with "
            f"--run <query_run_id>, choosing by the timestamp window printed above.",
            file=sys.stderr,
        )
        return 1

    selected = wanted_run if wanted_run is not None else ordered[0]
    for run_id in ordered:
        print(format_run(run_id, grouped[run_id], headline=run_id == selected))
        print()
    if uncorrelated:
        print(format_uncorrelated(uncorrelated))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
