"""Guard ``scripts/window_measurement_report.py``.

That script harvests the three measurements the live-execution window was
declared for, out of ``telemetry-tokens.jsonl``. It decides nothing and moves
no constant; it prints per-run numbers and the verdict each supports.

WHY THIS FILE IS AS LONG AS IT IS
---------------------------------
The first version of the script printed a confident, clean, WRONG verdict on
inputs that are reachable on the file it will actually be pointed at.
Adversarial review demonstrated all of these, and every one is pinned below:

* ``FITS`` on a run where every round-2 reply landed exactly on the cap and no
  row carried a usable ``finish_reason``;
* ``CLIPPED — 3 of 8 … at cap(s) [2000, 4000]``, the pooling sentence the
  script's own docstring says the design prevents, because rows with no
  ``query_run_id`` were treated as one run. ADR-0102 measured ``/data``: **108
  records, of which 18 carry the correlator** — 83% of the real file;
* a one-row uncorrelated bucket taking the ``>>> NEWEST RUN`` headline from a
  run that clipped 4 of 4;
* ``BUILD TOO OLD`` discarding three calls that returned 5,000 characters each
  because a fourth row was older — failing toward the expensive route;
* ``ROUTE A POSSIBLE`` on a run where every content field was empty;
* a full verdict set at exit 0 over 1 usable line out of 201.

Nine of sixteen mutants also survived the first version of this file. The rule
that catches them: assert the COMPUTED VALUE, never a substring that could match
the script's own prose, and pin the USE of a constant rather than its value.

WHAT TURNS EACH TEST RED
------------------------
Named per test.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "window_measurement_report.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "window_measurement_report_under_test", _SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


report: Any = _load_script()


def _row(**fields: Any) -> dict[str, Any]:
    """One ``provider_call_tokens`` row, shaped like the real formatter's."""
    base: dict[str, Any] = {
        # Varied per call below. A single hardcoded stamp made the timestamp
        # WINDOW — the thing the AMBIGUOUS refusal tells an operator to choose
        # by — indistinguishable from its own last element, and a mutant
        # collapsing it survived all 151 tests.
        "timestamp": "2026-09-07T12:00:00+00:00",
        "level": "INFO",
        "logger": "product_app.telemetry.tokens",
        "message": "provider_call_tokens",
        "model_id": "anthropic/claude-haiku-4.5:online",
        "search_enabled": True,
        "usage_absent": False,
    }
    base.update(fields)
    return base


def _captured(**fields: Any) -> dict[str, Any]:
    """A row from a build that HAS the annotation capture."""
    base = {
        "annotation_shape": "absent",
        "annotation_count": 0,
        "annotation_arrivals": 0,
        "annotation_usable_count": 0,
        "annotation_sites": "none",
        "annotation_content_shape": "absent",
    }
    base.update(fields)
    return _row(**base)


def _write(directory: Path, rows: list[dict[str, Any]], *, raw: str = "") -> Path:
    path = directory / str(report.TOKENS_FILE_NAME)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows) + raw, encoding="utf-8")
    return path


def _run(tmp_path: Path, capsys: Any, *, run: str | None = None) -> tuple[int, str, str]:
    argv = [str(tmp_path)] + ([] if run is None else ["--run", run])
    code = report.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


#: A run at the SUPERSEDED cap of 2000 that clipped 3 of its 4 round-2 replies
#: — the 2026-09-06 run's shape, already on the production volume.
_OLD_CLIPPED_RUN = [
    _row(
        query_run_id="run-old",
        stage="debate_round_2",
        slot_number=slot,
        max_tokens=2000,
        prompt_tokens=3000,
        completion_tokens=2000 if clipped else 900,
        finish_reason="length" if clipped else "stop",
    )
    for slot, clipped in enumerate((True, True, True, False), start=1)
]

#: A run at the CURRENT cap of 4000 where every reply finished cleanly and well
#: short of the ceiling.
_NEW_CLEAN_RUN = [
    _captured(
        query_run_id="run-new",
        stage="debate_round_2",
        slot_number=slot,
        max_tokens=4000,
        prompt_tokens=3200,
        completion_tokens=1500 + slot,
        finish_reason="stop",
    )
    for slot in range(1, 5)
]


# --- the refusals, and their positive partner --------------------------------


def test_it_refuses_a_file_with_no_token_rows(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: the script exits 0 over zero rows, as the precedent script does.

    "0 of 0 replies clipped, the cap FITS" reads exactly like a passing
    measurement.
    """
    _write(tmp_path, [])
    code, _out, err = _run(tmp_path, capsys)
    assert code == 1
    assert "NO DATA" in err


def test_it_refuses_a_file_of_rows_that_are_not_token_rows(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: the ``TOKEN_EVENT`` filter is deleted.

    PINS THE USE, NOT THE CONSTANT. An earlier version asserted only that the
    string ``provider_call_tokens`` appeared in ``providers.py``; replacing
    ``token_rows`` with ``list(rows)`` left all 16 tests green and turned the
    empty-input refusal into a full confident report over a file of cost rows.

    The billing stream shares the durable directory, so a harvest that grabbed
    the wrong file lands here rather than at zero rows.
    """
    _write(
        tmp_path,
        [
            {"message": "upstream_provider_http_error", "status_code": 503},
            {"message": "provider_call_cost", "query_run_id": "r", "stage": "judge"},
        ],
    )
    code, _out, err = _run(tmp_path, capsys)
    assert code == 1
    assert "NO DATA" in err
    # The message must say what it DID find, or the operator cannot tell an
    # empty file from a wrong one.
    assert "2 other record(s)" in err


def test_it_refuses_a_file_that_is_missing_entirely(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: a missing file is treated as a measured zero.

    The harvest redirects ``fly ssh console`` output into a directory. Redirect
    it to the wrong NAME and the file the script wants is absent — the exact
    mistake that would otherwise produce a clean report about a paid run that
    really happened.
    """
    assert report.main([str(tmp_path / "nowhere")]) == 1
    assert "NO DATA" in capsys.readouterr().err


def test_it_refuses_when_given_no_directory_and_no_env(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """RED WHEN: a bare invocation silently reads the current directory."""
    monkeypatch.delenv("TELEMETRY_LOG_DIR", raising=False)
    assert report.main([]) == 2
    assert "NO DATA" in capsys.readouterr().err


def test_it_refuses_a_file_that_mostly_did_not_parse(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: unparsable lines are skipped silently.

    Measured on the first version: 200 torn lines plus one good row produced a
    full verdict set at exit 0. ``fly ssh console -C "cat …"`` can prepend a
    banner and can tear the tail of a live append-only file, so this is on the
    harvest path, not a corner case.
    """
    _write(
        tmp_path,
        [_row(query_run_id="r", stage="debate_round_2", max_tokens=4000, finish_reason="stop")],
        raw="{not json\n" * 200,
    )
    code, _out, err = _run(tmp_path, capsys)
    assert code == 1
    assert "200 of 201" in err


def test_a_few_unparsable_lines_are_reported_but_not_fatal(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: the skipped count stops being printed, or the ceiling is absolute.

    The POSITIVE PARTNER for the refusal above (AGENTS.md rule 7): a script that
    refused on ANY bad line would pass that test while being useless on a real
    harvest. One torn line in 41 is under the ceiling — it must run, and it must
    SAY SO. Silence about dropped lines is the defect, not the dropping.
    """
    _write(tmp_path, _NEW_CLEAN_RUN * 10, raw="{torn\n")
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "1 unparsable line(s)" in out


def test_valid_json_that_is_not_an_object_counts_as_unusable(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: non-dict JSON lines are silently dropped instead of counted.

    ``[1,2,3]`` and ``"text"`` parse cleanly and are not telemetry records.
    Counting them as usable would let a file of them satisfy the non-empty
    check; dropping them uncounted would hide a corrupt copy.

    40 good rows so the 2 bad ones sit UNDER the unparsable ceiling — the point
    here is that they are counted, not that they are fatal. Written down because
    the first draft used 4 good rows, which put them at 33% and refused: a
    passing assertion for the wrong reason.
    """
    _write(tmp_path, _NEW_CLEAN_RUN * 10, raw='[1,2,3]\n"a string"\n')
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "2 unparsable line(s)" in out


def test_it_reports_and_exits_zero_when_rows_exist(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: the refusals above are over-broad and reject real data too.

    The POSITIVE PARTNER for all five refusals: a script returning 1
    unconditionally would pass every one of them.
    """
    _write(tmp_path, _NEW_CLEAN_RUN)
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "run-new" in out


def test_the_env_var_is_used_when_no_argument_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """RED WHEN: ``$TELEMETRY_LOG_DIR`` stops being the default.

    It is the variable ``telemetry_sink`` reads to decide where to WRITE.
    """
    _write(tmp_path, _NEW_CLEAN_RUN)
    monkeypatch.setenv("TELEMETRY_LOG_DIR", str(tmp_path))
    assert report.main([]) == 0
    assert "run-new" in capsys.readouterr().out


# --- the pooling trap --------------------------------------------------------


def test_an_old_clipped_run_does_not_make_the_new_run_read_as_clipped(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: the report pools rows instead of grouping by ``query_run_id``.

    Both arms asserted: the OLD run must still show its clipping (it is real,
    and hiding it would be its own defect) while the NEW run — the headline —
    must read as fitting, at its own cap.
    """
    _write(tmp_path, _OLD_CLIPPED_RUN + _NEW_CLEAN_RUN)
    code, out, _err = _run(tmp_path, capsys, run="run-new")
    assert code == 0

    old_block = out[out.index("run-old") : out.index("run-new")]
    new_block = out[out.index("run-new") :]
    assert "CLIPPED — 3 of 4" in old_block
    assert "FITS — 0 of 4" in new_block
    assert "CLIPPED" not in new_block
    assert "[2000]" in old_block and "[4000]" in new_block


def test_uncorrelated_rows_are_a_census_and_never_a_run(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: rows with no ``query_run_id`` are given a run's verdict machinery.

    THE test this script exists for, and the one the first version failed. Two
    runs at two caps with no correlator landed in one bucket and printed
    ``CLIPPED — 3 of 8 … at cap(s) [2000, 4000]`` — word for word the sentence
    the design is supposed to prevent.

    This is not hypothetical: ADR-0102 measured ``/data`` at 108 records with 18
    correlated, so 83% of the real file arrives here.
    """
    orphans = [
        _row(
            stage="debate_round_2",
            slot_number=slot,
            max_tokens=cap,
            completion_tokens=cap,
            finish_reason="length" if cap == 2000 else "stop",
        )
        for cap in (2000, 4000)
        for slot in range(1, 5)
    ]
    _write(tmp_path, orphans)
    code, out, _err = _run(tmp_path, capsys)

    assert code == 1, "a file with no correlated run cannot support a verdict"
    assert "NO CORRELATED RUNS" in out
    assert "8 row(s) carry NO query_run_id" in out
    assert "NOT A RUN" in out
    # The pooled verdict must not appear anywhere.
    assert "CLIPPED" not in out
    assert "FITS" not in out


def test_a_trailing_uncorrelated_row_cannot_steal_the_headline(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: the uncorrelated bucket is eligible for ``>>> NEWEST RUN``.

    ``evaluation.py`` passes ``telemetry_labels=None`` for the JUDGE call when
    the run id is absent, and the judge is a run's LAST stage — so its
    uncorrelated row is the last row in the file. Measured on the first version:
    a run that clipped 4 of 4 was demoted to a plain ``run`` while a one-row
    bucket saying nothing took the headline.
    """
    clipped = [
        _captured(
            query_run_id="run-live",
            stage="debate_round_2",
            slot_number=slot,
            max_tokens=4000,
            completion_tokens=4000,
            finish_reason="length",
        )
        for slot in range(1, 5)
    ]
    orphan = _row(stage="judge", prompt_tokens=100, completion_tokens=10, finish_reason="stop")
    _write(tmp_path, clipped + [orphan])
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert ">>> SELECTED RUN  run-live" in out
    assert "1 row(s) carry NO query_run_id" in out


def test_a_non_string_run_id_is_uncorrelated_not_a_run_of_its_own(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: a non-string ``query_run_id`` is accepted as a run key.

    ``group_by_run`` keys on ``isinstance(run_id, str)``. Dropping that check
    would let ``None``/``0``/``""`` become run ids, and two rows carrying
    different non-strings would each become a "run" with a one-row verdict.
    """
    _write(
        tmp_path,
        _NEW_CLEAN_RUN
        + [
            _row(query_run_id=None, stage="judge", prompt_tokens=1),
            _row(query_run_id="", stage="judge", prompt_tokens=1),
            _row(query_run_id=17, stage="judge", prompt_tokens=1),
        ],
    )
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "1 correlated run(s)" in out
    assert "3 row(s) carry NO query_run_id" in out


def test_the_newest_run_is_the_one_whose_last_row_is_last(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: run order is by id, by first appearance, or arbitrary.

    Two INTERLEAVED runs — the shape two concurrent runs on the shared volume
    produce — ordered so that FIRST-appearance and LAST-appearance disagree:

        run-old, run-new, run-new, run-old

    First appearance says ``old, new`` and would headline ``run-new``. Last
    appearance says ``new, old`` and headlines ``run-old``. Alphabetical order
    also gives ``run-new``. Only the documented rule gives ``run-old``.

    The first draft of this test used ``new, old, new, old``, where both
    orderings give the same answer — a ``setdefault`` mutant survived it. The
    committed mutation proof is what found that; the test looked right.
    """
    interleaved = [_OLD_CLIPPED_RUN[0], _NEW_CLEAN_RUN[0], _NEW_CLEAN_RUN[1], _OLD_CLIPPED_RUN[1]]
    _write(tmp_path, interleaved)
    # Ordering is still observable with two runs: the AMBIGUOUS refusal prints
    # every run in order, oldest first, so the LAST block is the newest.
    code, out, err = _run(tmp_path, capsys)
    assert code == 1 and "AMBIGUOUS" in err
    assert out.index("run-new") < out.index("run-old"), "run-old's last row is last"


# --- measurement 2 -----------------------------------------------------------


def test_rows_with_no_usable_finish_reason_are_refused_not_read_as_fitting(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: ``_verdict_2`` reports FITS over rows that measured nothing.

    ``providers.FINISH_REASON_ABSENT == "absent"`` is a real production value: a
    stream that ends ``[DONE]`` without ever sending a reason passes the
    incompleteness guard and is served and priced as a normal answer. "0 of N
    stopped on 'length'" is trivially true when no row could have said it.

    The replies are well SHORT of the cap on purpose. At the cap they would hit
    ``AT THE CEILING``, which is positive evidence and outranks this refusal —
    see ``test_an_at_the_ceiling_reading_survives_an_uninformative_neighbour``.
    An earlier fixture sat exactly at 4000 and so tested the wrong branch.
    """
    _write(
        tmp_path,
        [
            _captured(
                query_run_id="r",
                stage="debate_round_2",
                slot_number=slot,
                max_tokens=4000,
                completion_tokens=120,
                finish_reason="absent",
            )
            for slot in range(1, 5)
        ],
    )
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "NOT MEASURED — 4 of 4 debate row(s)" in out
    assert "FITS" not in out


def test_a_row_that_predates_the_finish_reason_field_is_also_refused(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: only the literal ``"absent"`` is treated as uninformative.

    ``finish_reason`` entered the stream on 2026-08-30 and ``/data`` is a
    persistent volume holding older runs, so a row with the key entirely missing
    is reachable on the real file.
    """
    _write(
        tmp_path,
        [
            _row(query_run_id="r", stage="debate_round_2", max_tokens=4000, completion_tokens=10)
            for _ in range(2)
        ],
    )
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "NOT MEASURED" in out


def test_a_reply_that_lands_exactly_on_the_cap_is_not_reported_as_fitting(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: the completion length is never compared against the cap.

    ADR-0102 states the rule: **a clipped reply reports exactly the cap.** A run
    where every reply says ``stop`` but the longest equals the ceiling is not
    evidence the ceiling is enough. Literals on both sides: cap 4000, longest
    4000.
    """
    _write(
        tmp_path,
        [
            _captured(
                query_run_id="r",
                stage="debate_round_2",
                slot_number=slot,
                max_tokens=4000,
                completion_tokens=4000,
                finish_reason="stop",
            )
            for slot in range(1, 5)
        ],
    )
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "AT THE CEILING" in out
    assert "FITS" not in out


def test_two_caps_inside_one_run_refuse_rather_than_average(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: rows spanning two caps produce a single verdict.

    Two caps under one ``query_run_id`` means the grouping is wrong or a deploy
    landed mid-run. Either way no one verdict applies, and the previous version
    printed ``cap(s) [2000, 4000]`` with a confident answer beside it.
    """
    _write(
        tmp_path,
        [
            _captured(
                query_run_id="r",
                stage="debate_round_2",
                slot_number=slot,
                max_tokens=cap,
                completion_tokens=10,
                finish_reason="stop",
            )
            for cap in (2000, 4000)
            for slot in (1, 2)
        ],
    )
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "NOT COMPARABLE" in out


def test_a_genuinely_comfortable_run_reports_fits(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: the guards above are over-broad and nothing can ever report FITS.

    The POSITIVE PARTNER for the four refusals above. Literals: cap 4000,
    longest reply 1504, every reason ``stop``.
    """
    _write(tmp_path, _NEW_CLEAN_RUN)
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "FITS — 0 of 4" in out
    assert "Longest reply 1504 completion tokens against cap(s) [4000]" in out


def test_the_longest_reply_is_the_maximum_not_the_minimum(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: ``completion_max`` reports the minimum, or is hardcoded.

    It is the one number a reader uses to judge headroom, and after the
    ceiling check it is the only surviving clipping signal. Literals: replies
    of 100 and 3900 against cap 4000 — the max is what makes this AT THE
    CEILING-adjacent, the min would read as comfortable.
    """
    _write(
        tmp_path,
        [
            _captured(
                query_run_id="r",
                stage="debate_round_2",
                slot_number=slot,
                max_tokens=4000,
                completion_tokens=tokens,
                finish_reason="stop",
            )
            for slot, tokens in ((1, 100), (2, 3900))
        ],
    )
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "Longest reply 3900" in out
    assert "Longest reply 100" not in out


# --- measurement 3 -----------------------------------------------------------


def test_absent_annotations_are_blamed_on_our_reader_when_the_key_was_on_the_wire(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: ``annotation_sites`` stops being read, or ``absent`` is attributed
    to the provider unconditionally.

    The fold collects from ``choices[0].delta`` only. Printing "the provider
    returned no annotations at all" off an empty payload is a claim about
    OpenRouter drawn from our own reader (AGENTS.md rule 8c). Both arms asserted,
    because the whole value is the DISTINCTION.
    """
    _write(
        tmp_path,
        [
            _captured(
                query_run_id="r", stage="initial_answers", slot_number=1, annotation_sites="choice"
            )
        ],
    )
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "OUR READER MISSED 1 CALL(S) ENTIRELY" in out
    assert "annotations were only at ['choice']" in out
    assert "NO ANNOTATIONS ON THE WIRE" not in out


def test_absent_annotations_with_no_site_anywhere_is_a_statement_about_the_provider(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: every ``absent`` is blamed on our reader.

    The POSITIVE PARTNER for the test above. ``sites=none`` means no
    annotations key appeared at ANY site the probe looks at, which is the one
    case where "the provider sent none" is supportable — and this verdict arm
    had no test at all in the first version.
    """
    _write(
        tmp_path,
        [
            _captured(
                query_run_id="r", stage="initial_answers", slot_number=1, annotation_sites="none"
            )
        ],
    )
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "NO ANNOTATIONS ON THE WIRE" in out
    assert "OUR READER MISSED" not in out


def test_no_content_key_reports_route_b(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: an absent content key stops implying Route B.

    ABSENT means the upstream sends no content field, so only a fetcher can
    close #447.
    """
    _write(
        tmp_path,
        [
            _captured(
                query_run_id="r",
                stage="initial_answers",
                annotation_shape="flat",
                annotation_count=2,
                annotation_arrivals=2,
                annotation_usable_count=2,
                annotation_sites="delta",
            )
        ],
    )
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "ROUTE B" in out


def test_a_content_key_that_yields_no_characters_is_unproven_not_possible(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: ``ROUTE A POSSIBLE`` fires on zero characters of content.

    Measured on the first version: four calls whose content field was present
    and empty produced ``ROUTE A POSSIBLE``. A reader scanning the ``->`` lines
    does not then build the fetcher. Zero characters is not evidence Route A
    works — but the field existing is not evidence it fails either, which is why
    this is a third verdict and not Route B.
    """
    _write(
        tmp_path,
        [
            _captured(
                query_run_id="r",
                stage="initial_answers",
                slot_number=slot,
                annotation_shape="flat",
                annotation_count=1,
                annotation_arrivals=1,
                annotation_usable_count=1,
                annotation_sites="delta",
                annotation_content_shape="string",
                annotation_content_chars=0,
            )
            for slot in range(1, 5)
        ],
    )
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "ROUTE A UNPROVEN" in out
    assert "ROUTE A POSSIBLE" not in out


def test_real_content_reports_route_a_with_the_character_count(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: the character total is dropped or hardcoded.

    Literals on both sides: two calls carrying 1200 and 800 characters, so the
    total is 2000 and the largest single call is 1200. No single constant
    satisfies both.
    """
    _write(
        tmp_path,
        [
            _captured(
                query_run_id="r",
                stage="initial_answers",
                slot_number=slot,
                annotation_shape="nested",
                annotation_count=3,
                annotation_arrivals=3,
                annotation_usable_count=0,
                annotation_sites="delta",
                annotation_content_shape="string",
                annotation_content_chars=chars,
            )
            for slot, chars in ((1, 1200), (2, 800))
        ],
    )
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "ROUTE A POSSIBLE" in out
    assert "2000 characters in total" in out
    assert "largest single call 1200" in out
    # ADR-0084's answer, measured rather than inferred from the label.
    assert "yielded 0 sources from 6 distinct annotation(s)" in out
    assert "Route A needs TWO fixes" in out


def test_the_annotations_path_being_alive_is_reported_from_the_usable_count(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: ``annotation_usable_count`` is dropped from the reading.

    The POSITIVE PARTNER for the assertion above: the same shape label with a
    non-zero usable count must report the opposite conclusion, or the sentence
    is a constant rather than a reading.
    """
    _write(
        tmp_path,
        [
            _captured(
                query_run_id="r",
                stage="initial_answers",
                annotation_shape="nested",
                annotation_count=3,
                annotation_arrivals=3,
                annotation_usable_count=3,
                annotation_sites="delta",
                annotation_content_shape="string",
                annotation_content_chars=500,
            )
        ],
    )
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "yielded 3 source(s) from 3 distinct annotation(s). The path is ALIVE" in out


def test_a_run_with_search_off_is_refused_as_evidence(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: a run that never asked for search is read as "no content found".

    THE POSITIVE PARTNER for measurement 3 (AGENTS.md rule 7). "No annotation
    carried content" is trivially true of a run that never switched ``:online``
    on, and reporting that as Route B would close #447's cheap route on evidence
    about nothing.
    """
    _write(
        tmp_path,
        [
            _captured(
                query_run_id="r",
                stage="initial_answers",
                search_enabled=False,
                model_id="anthropic/claude-haiku-4.5",
            )
        ],
    )
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "NO SEARCHING CALLS" in out
    assert "ROUTE" not in out


def test_non_searching_rows_are_excluded_from_the_census_not_counted_as_absent(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: the shape census is computed over all rows instead of searching ones.

    Debate, synthesis and judge legs never set ``:online``. Counting them floods
    the census with ``absent`` and makes a run look like the provider sends
    nothing — on a real run they are most of the rows. Literals: 1 searching
    call and 3 that never asked, so ``searching_calls=1/4`` and the shape census
    holds exactly one entry.
    """
    _write(
        tmp_path,
        [
            _captured(
                query_run_id="r",
                stage="initial_answers",
                annotation_shape="nested",
                annotation_count=1,
                annotation_arrivals=1,
                annotation_usable_count=1,
                annotation_sites="delta",
                annotation_content_shape="string",
                annotation_content_chars=19,
            )
        ]
        + [
            _captured(query_run_id="r", stage=stage, search_enabled=False, model_id="m")
            for stage in ("debate_round_1", "synthesis", "judge")
        ],
    )
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "searching_calls=1/4" in out
    assert "shapes={'nested': 1}" in out
    assert "'absent': 3" not in out


def test_one_old_row_does_not_veto_a_measurement_the_others_made(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: ``BUILD TOO OLD`` fires on ANY field-less row.

    Measured on the first version: one row without the capture vetoed three
    calls that had returned 5,000 characters each — and it failed toward Route
    B, the expensive route, while the line directly above the verdict read
    ``content key: present on 3``.
    """
    _write(
        tmp_path,
        [
            _captured(
                query_run_id="r",
                stage="initial_answers",
                slot_number=slot,
                annotation_shape="nested",
                annotation_count=3,
                annotation_arrivals=3,
                annotation_usable_count=0,
                annotation_sites="delta",
                annotation_content_shape="string",
                annotation_content_chars=5000,
            )
            for slot in range(1, 4)
        ]
        + [_row(query_run_id="r", stage="initial_answers", slot_number=4)],
    )
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "ROUTE A POSSIBLE" in out
    assert "1 of 4 searching row(s) predate the capture" in out
    assert "BUILD TOO OLD" not in out


def test_a_run_entirely_from_an_older_build_cannot_answer_measurement_3(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: rows with no ``annotation_shape`` are read as ``absent``.

    The POSITIVE PARTNER for the test above. The 2026-09-06 run is on the volume
    and predates the capture entirely; reading its missing field as "no
    annotations arrived" would manufacture an answer from a build that could not
    produce one.
    """
    _write(
        tmp_path,
        [
            _row(
                query_run_id="r",
                stage="initial_answers",
                prompt_tokens=2000,
                completion_tokens=900,
                finish_reason="stop",
            )
        ],
    )
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "BUILD TOO OLD" in out
    assert "ROUTE" not in out


def test_the_arrivals_total_is_reported_beside_the_distinct_count(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: ``annotation_arrivals`` is dropped from the reading.

    Literals: 2 distinct annotations, 8 arrivals — the cumulative-resend
    signature. A report showing only one of the two cannot tell a provider that
    sent 8 sources from one that re-sent 2 four times.
    """
    _write(
        tmp_path,
        [
            _captured(
                query_run_id="r",
                stage="initial_answers",
                annotation_shape="nested",
                annotation_count=2,
                annotation_arrivals=8,
                annotation_usable_count=0,
                annotation_sites="delta",
                annotation_content_shape="string",
                annotation_content_chars=19,
            )
        ],
    )
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "annotations=2 distinct (8 arrivals)" in out


# --- measurement 1 and the judge ---------------------------------------------


def test_the_critique_cost_is_summed_over_both_rounds_in_tokens(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: only one debate round is counted, or a dollar figure is invented.

    Literals: four round-1 calls at 100 prompt tokens and four round-2 at 200,
    so 1200 prompt tokens across 8 calls — a number no single-round
    implementation produces.

    No dollar figure: the run's own receipt prices these tokens, and a second
    money number computed here would compete with it.
    """
    rows = [
        _captured(
            query_run_id="run-cost",
            stage=stage,
            slot_number=slot,
            max_tokens=4000,
            prompt_tokens=prompt,
            completion_tokens=completion,
            finish_reason="stop",
        )
        for stage, prompt, completion in (
            ("debate_round_1", 100, 50),
            ("debate_round_2", 200, 150),
        )
        for slot in range(1, 5)
    ]
    _write(tmp_path, rows)
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "M1 critique cost — 8 call(s)" in out
    assert "1200 prompt + 800 completion tokens" in out
    assert "$" not in out, "the report must not invent a dollar figure beside the receipt's"


def test_calls_with_no_usage_are_counted_per_stage(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: the ``usage_absent`` tally is hardcoded or dropped.

    A cost total that silently omits calls the provider never priced reads as a
    complete measurement. Literals: 3 of 4 round-2 calls reported no usage.
    """
    _write(
        tmp_path,
        [
            _captured(
                query_run_id="r",
                stage="debate_round_2",
                slot_number=slot,
                max_tokens=4000,
                prompt_tokens=100,
                completion_tokens=10,
                finish_reason="stop",
                usage_absent=slot != 4,
            )
            for slot in range(1, 5)
        ],
    )
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "usage_absent on 3" in out


def test_the_judge_leg_is_reported_separately(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: judge rows are folded into the critique total, or its reasons dropped.

    The judge is a different receipt line and a different decision. Literals:
    one judge call at 5000 prompt tokens, which must appear on the judge line
    and NOT in the critique total.
    """
    _write(
        tmp_path,
        [
            _captured(
                query_run_id="r",
                stage="debate_round_2",
                slot_number=1,
                max_tokens=4000,
                prompt_tokens=200,
                completion_tokens=150,
                finish_reason="stop",
            ),
            _captured(
                query_run_id="r",
                stage="judge",
                prompt_tokens=5000,
                completion_tokens=300,
                finish_reason="length",
            ),
        ],
    )
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "judge — 1 call(s), 5000 prompt + 300 completion tokens" in out
    assert "finish_reasons={'length': 1}" in out
    assert "M1 critique cost — 1 call(s)" in out
    assert "200 prompt + 150 completion tokens" in out


def test_a_bool_never_slides_into_a_token_distribution(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: ``_ints`` stops excluding ``bool``.

    ``bool`` is an ``int`` subclass, so a ``True`` in a token field would be
    counted as 1 — a number nobody could see in a sum. Literals: one real 100
    beside a ``True``, so the honest total is 100 and the mutant's is 101.
    """
    assert report._ints([{"prompt_tokens": 100}, {"prompt_tokens": True}], "prompt_tokens") == [100]


# --- the copied constants ----------------------------------------------------


def test_the_stage_names_match_the_ones_the_product_emits() -> None:
    """RED WHEN: a stage is renamed in ``telemetry_sink`` and not in the script.

    The script copies the stage names rather than importing them, so it runs
    against a harvested file with no ``src`` on the path. A drifted stage name
    would make every reading for that stage silently return zero.
    """
    from product_app import telemetry_sink

    assert set(report.STAGE_NAMES) == telemetry_sink.TELEMETRY_STAGES


def test_the_critique_stages_are_the_two_debate_rounds() -> None:
    """RED WHEN: a stage is added to or removed from the critique cost reading.

    ``STAGE_NAMES`` alone does not pin this: it is the full stage vocabulary,
    and the cost reading uses a subset. Eight critique calls means four critics
    in each of two rounds, so both rounds must be in and nothing else.
    """
    assert report.CRITIQUE_STAGES == ("debate_round_1", "debate_round_2")
    assert set(report.CRITIQUE_STAGES) < set(report.STAGE_NAMES)


def test_the_token_event_name_matches_the_one_the_product_logs() -> None:
    """RED WHEN: the emitted event name changes and the reader does not.

    Read through ``code_without_comments`` (AGENTS.md rule 8) so the prose ABOUT
    the event name — this module's docstrings name it repeatedly — cannot stand
    in for the call that emits it.

    This pins the VALUE; ``test_it_refuses_a_file_of_rows_that_are_not_token_rows``
    pins the USE. Both are needed: an earlier version had only this one, and
    deleting the filter entirely left every test green.
    """
    from tests.code_text import code_without_comments

    source = code_without_comments(
        Path(__file__).resolve().parents[2] / "src" / "product_app" / "providers.py"
    )
    assert f'_TOKEN_LOGGER.info("{report.TOKEN_EVENT}"' in source


# --- round-2: the gaps the first mutant set could not see --------------------


def test_one_uninformative_row_among_many_still_refuses_FITS(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: the refusal needs EVERY row to be uninformative.

    The first version refused only when all rows were uninformative, so seven
    ``absent`` rows beside one ``stop`` printed ``FITS — 0 of 8 … stopped on
    'length'`` with the caveat in a trailing parenthetical. Same defect, higher
    threshold: "0 of 8 stopped on 'length'" requires all 8 to have been able to
    say it.

    Literals: 7 uninformative, 1 informative, none clipped.
    """
    rows = [
        _captured(
            query_run_id="r",
            stage="debate_round_2",
            slot_number=slot,
            max_tokens=4000,
            completion_tokens=100,
            finish_reason="absent" if slot < 8 else "stop",
        )
        for slot in range(1, 9)
    ]
    _write(tmp_path, rows)
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "NOT MEASURED — 7 of 8 debate row(s)" in out
    assert "FITS" not in out


def test_a_clipped_row_still_reports_CLIPPED_despite_uninformative_neighbours(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: the refusal is widened to any uninformative row at all.

    The POSITIVE PARTNER for the test above, and the reason the guard reads
    ``uninformative and not clipped`` rather than ``uninformative``. A row that
    DID say 'length' is positive evidence: the cap demonstrably did not fit,
    whatever the other rows failed to say. Refusing here would discard a real
    measurement.
    """
    rows = [
        _captured(
            query_run_id="r",
            stage="debate_round_2",
            slot_number=slot,
            max_tokens=4000,
            completion_tokens=4000 if slot == 1 else 100,
            finish_reason="length" if slot == 1 else "absent",
        )
        for slot in range(1, 5)
    ]
    _write(tmp_path, rows)
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "CLIPPED — 1 of 4" in out
    assert "NOT MEASURED" not in out


def test_the_unparsable_ceiling_sits_between_these_two_measured_files(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: ``MAX_UNPARSABLE_SHARE`` is loosened.

    The two existing fixtures bracket only 2.4% and 99.5%, so the constant
    could be raised 0.05 -> 0.99 with the whole suite green — a 20x loosening,
    invisible.

    Literals on BOTH sides of the boundary, and deliberately NOT asserted
    against the constant itself (AGENTS.md rule 7a): pinning ``<= SHARE`` would
    survive the constant being moved. 19 good rows + 1 torn line is 5.0%
    exactly and must PASS; 18 good + 2 torn is 10.0% and must REFUSE. Only a
    ceiling in (0.05, 0.10] satisfies both.
    """
    good = _NEW_CLEAN_RUN[:1] * 19
    _write(tmp_path, good, raw="{torn\n")
    code, _out, _err = _run(tmp_path, capsys)
    assert code == 0, "1 unparsable line in 20 is 5.0% and must be tolerated"

    _write(tmp_path, good[:18], raw="{torn\n{torn\n")
    code, _out, err = _run(tmp_path, capsys)
    assert code == 1, "2 unparsable lines in 20 is 10.0% and must refuse"
    assert "2 of 20" in err


def test_the_report_prints_the_rotation_scope_once_above_the_runs(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: the rotation caveat is dropped.

    The script reads only the ACTIVE ``telemetry-tokens.jsonl``; the sink
    rotates at 4 MiB with 4 backups, so a run straddling a rotation is reported
    from its tail. A reader who does not know that reads a partial run as a
    whole one.

    Asserted as EXACTLY ONE occurrence, above the first run block: ADR-0104
    said this printed "on every run", which was false, and a test asserting
    mere presence would have let that stay false.
    """
    _write(tmp_path, _NEW_CLEAN_RUN + _OLD_CLIPPED_RUN)
    code, out, _err = _run(tmp_path, capsys, run="run-new")
    assert code == 0
    assert out.count("rotated backups (.1-.4) are NOT included") == 1
    assert out.index("rotated backups") < out.index("run-new")


def test_an_at_the_ceiling_reading_survives_an_uninformative_neighbour(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: the uninformative refusal is placed above the ceiling check.

    Round 2 added the refusal ABOVE the positive-evidence branches, so one row
    with no usable ``finish_reason`` destroyed an at-the-cap reading the round
    before it had produced. That is the "any missing row vetoes everything"
    defect ``_verdict_3`` had already been fixed for, reintroduced ten lines
    away — and it fails toward paying for a second harvest.

    Literals: 7 rows say ``stop``, 1 says ``absent``, and the longest reply is
    4000 against cap 4000. ADR-0102: a clipped reply reports exactly the cap.
    """
    rows = [
        _captured(
            query_run_id="r",
            stage="debate_round_2",
            slot_number=slot,
            max_tokens=4000,
            completion_tokens=4000,
            finish_reason="absent" if slot == 8 else "stop",
        )
        for slot in range(1, 9)
    ]
    _write(tmp_path, rows)
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "AT THE CEILING" in out
    assert "NOT MEASURED" not in out
    # The uninformative row is still DISCLOSED, not silently dropped.
    assert "(1 of 8 row(s) carried no usable finish_reason)" in out


def test_measurement_2_reads_round_1_because_one_cap_governs_both(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: the debate-fit reading filters to ``debate_round_2`` only.

    ``debate.py`` dispatches BOTH rounds through one seam with one
    ``max_tokens=DEBATE_ROUND_MAX_TOKENS``. Reading only round 2 inspects four
    of the eight calls that constant governs, and ADR-0102's table records the
    previous run's ROUND 1 slot 4 stopping at 2000/length.

    Ground truth here: all four ROUND-1 replies clipped, round 2 is short. A
    round-2-only reading prints FITS — the cap stays while half the calls it
    governs are truncated at full price. The per-round split must also show
    WHICH round clipped, or a reader cannot act on it.
    """
    rows = [
        _captured(
            query_run_id="r",
            stage="debate_round_1",
            slot_number=slot,
            max_tokens=4000,
            completion_tokens=4000,
            finish_reason="length",
        )
        for slot in range(1, 5)
    ] + [
        _captured(
            query_run_id="r",
            stage="debate_round_2",
            slot_number=slot,
            max_tokens=4000,
            completion_tokens=300,
            finish_reason="stop",
        )
        for slot in range(1, 5)
    ]
    _write(tmp_path, rows)
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "CLIPPED — 4 of 8 debate replies" in out
    assert "FITS" not in out
    assert "debate_round_1: 4 call(s), 4 clipped" in out
    assert "debate_round_2: 4 call(s), 0 clipped" in out


def test_two_runs_and_no_named_run_refuses_to_pick_a_headline(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: the report guesses which run the money was spent on.

    Measured end to end: with a paid measurement run and one ordinary query
    from a second user overlapping it, the headline landed on the ordinary
    query and printed the EXACT OPPOSITE of the paid run in both money
    directions — ``FITS`` beside the paid run's ``CLIPPED 4 of 4``, and ``NO
    ANNOTATIONS`` beside its ``ROUTE A POSSIBLE, 5600 characters``. A reader
    acting on it keeps a cap that does not fit AND builds a fetcher the data
    says is unnecessary. One concurrent query on a live ``/ui`` is enough.

    Every run is still PRINTED — the refusal withholds the headline, not the
    data — and the exit code is non-zero so a script cannot ignore it.
    """
    _write(tmp_path, _OLD_CLIPPED_RUN + _NEW_CLEAN_RUN)
    code, out, err = _run(tmp_path, capsys)
    assert code == 1
    assert "AMBIGUOUS" in err
    assert "--run <query_run_id>" in err
    assert ">>> SELECTED RUN" not in out
    # Both runs and their timestamp windows are still there to choose between.
    assert "run-old" in out and "run-new" in out


def test_naming_a_run_selects_it_as_the_headline(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: ``--run`` is ignored, or selects by position instead of id.

    The POSITIVE PARTNER for the refusal above: a report that always refused
    would satisfy that test and be useless.

    BOTH runs are selected in turn, and that is the point. The first draft
    named only ``run-old``, which is also what a "just use the default" mutant
    picks — so a mutant ignoring ``--run`` entirely survived it. The committed
    proof caught that; the test looked right. No single default satisfies both
    arms below.
    """
    _write(tmp_path, _OLD_CLIPPED_RUN + _NEW_CLEAN_RUN)
    code, out, _err = _run(tmp_path, capsys, run="run-old")
    assert code == 0
    assert ">>> SELECTED RUN  run-old" in out
    assert ">>> SELECTED RUN  run-new" not in out

    code, out, _err = _run(tmp_path, capsys, run="run-new")
    assert code == 0
    assert ">>> SELECTED RUN  run-new" in out
    assert ">>> SELECTED RUN  run-old" not in out


def test_naming_a_run_that_is_not_there_refuses(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: an unknown ``--run`` falls back to a default instead of refusing.

    A typo in a UUID must not silently report a different run than the one
    asked for — that is the headline defect with an extra step.
    """
    _write(tmp_path, _NEW_CLEAN_RUN)
    code, _out, err = _run(tmp_path, capsys, run="run-typo")
    assert code == 1
    assert "no run 'run-typo'" in err


def test_a_call_whose_annotations_were_at_an_unread_site_is_named_per_call(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: the missed-site reading is gated on the whole run's totals.

    An earlier version gated it on ``annotations_total == 0`` for the RUN, so
    ONE annotation reaching ``delta`` anywhere disabled it — including for the
    calls whose content sat where the fold never looks. Measured minimal case:
    one call, delta carrying a content-free citation, the terminal message
    carrying a 1,500-character passage, verdict ``ROUTE B``, with the sites
    census contradicting it one line above.

    Both arms: the run HAS annotations (so the old gate would be off) AND a
    call whose site we do not read. The second call's sites are ``message``
    ALONE — a call that also reached ``delta`` is a different finding, pinned by
    ``test_a_call_read_at_delta_is_not_reported_as_entirely_missed``.
    """
    rows = [
        _captured(
            query_run_id="r",
            stage="initial_answers",
            slot_number=1,
            annotation_shape="flat",
            annotation_count=1,
            annotation_arrivals=1,
            annotation_usable_count=1,
            annotation_sites="delta",
        ),
        _captured(
            query_run_id="r",
            stage="initial_answers",
            slot_number=2,
            annotation_shape="absent",
            annotation_sites="message",
        ),
    ]
    _write(tmp_path, rows)
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "OUR READER MISSED 1 CALL(S) ENTIRELY" in out
    assert "annotations were only at ['message']" in out
    assert "contribute NOTHING to the readings below" in out


def test_a_snippet_is_not_reported_as_a_passage(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: any non-zero content length reports ROUTE A POSSIBLE.

    The only threshold was ``if not content_chars_total``, so a 1-character
    content field and a 1,400-character passage produced the same verdict word.
    Route A turns on whether there is enough text for the judge to check an
    answer against.

    Literals on both sides of the floor: 4 calls at 1 character each is 4 in
    total and 1 at most, well under 200; the partner below clears it.
    """
    thin = [
        _captured(
            query_run_id="r",
            stage="initial_answers",
            slot_number=slot,
            annotation_shape="flat",
            annotation_count=1,
            annotation_arrivals=1,
            annotation_usable_count=1,
            annotation_sites="delta",
            annotation_content_shape="string",
            annotation_content_chars=1,
        )
        for slot in range(1, 5)
    ]
    _write(tmp_path, thin)
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "ROUTE A THIN" in out
    assert "ROUTE A POSSIBLE" not in out


def test_a_partial_critique_total_says_so(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: measurement 1 prints a partial total with no verdict.

    It had none, so 4 of 8 calls read exactly like 8 of 8 — and against
    ADR-0102's 41,644 input tokens that reads as the new cap HALVING critique
    cost. Calls dispatched and failed leave no token row; a run straddling a
    log rotation loses its head.
    """
    rows = [
        _captured(
            query_run_id="r",
            stage="debate_round_1",
            slot_number=slot,
            max_tokens=4000,
            prompt_tokens=5000,
            completion_tokens=100,
            finish_reason="stop",
        )
        for slot in range(1, 5)
    ]
    _write(tmp_path, rows)
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "FEWER THAN A FULL PEER ROUND — 4 of the 8 calls" in out
    assert "cannot tell WHY" in out


def test_a_complete_critique_total_says_so(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: the completeness check reports PARTIAL for a full run.

    The POSITIVE PARTNER: a verdict that always said PARTIAL would pass the
    test above and tell a reader nothing.
    """
    rows = [
        _captured(
            query_run_id="r",
            stage=stage,
            slot_number=slot,
            max_tokens=4000,
            prompt_tokens=100,
            completion_tokens=50,
            finish_reason="stop",
        )
        for stage in ("debate_round_1", "debate_round_2")
        for slot in range(1, 5)
    ]
    _write(tmp_path, rows)
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "COMPLETE — all 8 critique calls are present" in out


def test_billed_calls_that_left_no_row_are_not_read_as_a_round_that_never_ran(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: the empty-debate case claims the round did not happen.

    ``_log_call_token_shape`` runs on the success path only, so four dispatched
    calls that failed leave zero rows. Saying "the run produced no
    debate_round_2 call at all" is a positive claim about the run drawn from
    the absence of a row — the script's own headline principle, one level down.
    The honest reading is "this run cannot say which".
    """
    _write(tmp_path, [_captured(query_run_id="r", stage="judge", prompt_tokens=100)])
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "NO DEBATE ROWS" in out
    assert "This run cannot say which" in out
    assert "did not run" not in out.replace("Either the rounds did not run", "")


# --- round 4 -----------------------------------------------------------------


def test_a_call_read_at_delta_is_not_reported_as_entirely_missed(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: the missed-site predicate counts a call that delta DID read.

    ``annotation_sites`` is a set joined with commas, accumulated over every
    frame of ONE call, so a call whose annotations reached ``delta`` AND a
    terminal ``message`` records ``"delta,message"``. An earlier predicate asked
    "is ANY site outside delta?" and counted such a call as fully missed — then
    printed "those calls contribute NOTHING to the readings below" directly
    above two readings derived from those very calls.

    Measured: four searching calls, all ``delta,message``, 12 usable annotations
    and 20,000 content characters, verdict ``OUR READER MISSED 4 CALL(S)``. Only
    four searching calls existed. A reader believing it discounts ROUTE A and
    builds the fetcher — the expensive direction.
    """
    rows = [
        _captured(
            query_run_id="r",
            stage="initial_answers",
            slot_number=slot,
            annotation_shape="nested",
            annotation_count=3,
            annotation_arrivals=3,
            annotation_usable_count=3,
            annotation_sites="delta,message",
            annotation_content_shape="string",
            annotation_content_chars=5000,
        )
        for slot in range(1, 5)
    ]
    _write(tmp_path, rows)
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "MISSED 4 CALL(S) ENTIRELY" not in out
    assert "PARTIAL SAMPLE — 4 call(s)" in out
    assert "readings are a floor for those calls" in out
    # And the readings it qualifies are still printed.
    assert "ROUTE A POSSIBLE" in out


def test_a_call_read_nowhere_is_still_reported_as_entirely_missed(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: the fix above is over-broad and nothing is ever fully missed.

    The POSITIVE PARTNER. A call whose annotations were ONLY at a site the fold
    does not read contributes nothing, and saying so is the whole point of the
    sites census.
    """
    _write(
        tmp_path,
        [
            _captured(
                query_run_id="r",
                stage="initial_answers",
                annotation_shape="absent",
                annotation_sites="message",
            )
        ],
    )
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "MISSED 1 CALL(S) ENTIRELY" in out
    assert "PARTIAL SAMPLE" not in out


def test_the_passage_floor_sits_between_these_two_measured_calls(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: ``MIN_PASSAGE_CHARS`` is loosened.

    Swept, the constant was green anywhere in [2, 1200]: the thin fixture used
    1 character and the positive partner's largest call was 1,200, so a floor
    set uselessly LOW was invisible. The proof's only floor mutant REMOVES the
    branch, which cannot see that.

    Literals on both sides of the boundary and NOT asserted against the constant
    (AGENTS.md rule 7a): 199 characters must read THIN, 201 must not. Only a
    floor in (199, 201] satisfies both.
    """

    def drive(chars: int) -> str:
        _write(
            tmp_path,
            [
                _captured(
                    query_run_id="r",
                    stage="initial_answers",
                    annotation_shape="flat",
                    annotation_count=1,
                    annotation_arrivals=1,
                    annotation_usable_count=1,
                    annotation_sites="delta",
                    annotation_content_shape="string",
                    annotation_content_chars=chars,
                )
            ],
        )
        code, out, _err = _run(tmp_path, capsys)
        assert code == 0
        return out

    assert "ROUTE A THIN" in drive(199)
    assert "ROUTE A POSSIBLE" in drive(201)


def test_each_run_prints_the_timestamp_window_the_refusal_names(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: the timestamp window collapses to one stamp, or disappears.

    The AMBIGUOUS refusal tells the operator to choose "by the timestamp window
    printed above". Nothing asserted it: every fixture row carried one hardcoded
    stamp, so first and last were identical and a mutant collapsing the window
    survived all 151 tests. Fifth consecutive round to find a test that looked
    right.

    Distinct FIRST and LAST stamps, so the two ends are distinguishable.
    """
    rows = [
        _captured(
            query_run_id="r",
            stage="debate_round_2",
            slot_number=slot,
            max_tokens=4000,
            completion_tokens=100,
            finish_reason="stop",
            timestamp=f"2026-09-07T12:0{slot}:00+00:00",
        )
        for slot in range(1, 5)
    ]
    _write(tmp_path, rows)
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "2026-09-07T12:01:00+00:00 .. 2026-09-07T12:04:00+00:00" in out


def test_a_short_critique_round_does_not_invent_a_cause(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: fewer than 8 critique calls is reported as lost calls.

    ``debate.py`` makes ONE moderator call per round when peer critique is off
    or no slot is eligible — a legitimate shape whose totals ARE the run's cost.
    An earlier sentence said the totals were "a floor, not the run's cost" and
    named two causes, neither of which applies there. The report cannot tell the
    shapes apart, so it must not claim to.
    """
    rows = [
        _captured(
            query_run_id="r",
            stage=stage,
            max_tokens=4000,
            prompt_tokens=19000,
            completion_tokens=1500,
            finish_reason="stop",
        )
        for stage in ("debate_round_1", "debate_round_2")
    ]
    _write(tmp_path, rows)
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "FEWER THAN A FULL PEER ROUND — 2 of the 8" in out
    assert "cannot tell WHY" in out
    assert "a floor, not the run's cost" not in out


def test_a_clipped_reading_survives_rows_at_two_different_caps(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: the mixed-cap refusal is placed above the positive evidence.

    Round 3's stated principle is "positive evidence first". It moved the
    uninformative refusal below CLIPPED and left the caps refusal above it — the
    one refusal it did not move. A reply that said ``length`` clipped at
    whatever cap IT was given; a neighbour's different cap does not unmake that.

    The partner is below: with nothing clipped, mixed caps genuinely cannot
    support "the cap fits".
    """
    rows = [
        _captured(
            query_run_id="r",
            stage=stage,
            slot_number=slot,
            max_tokens=cap,
            completion_tokens=cap,
            finish_reason="length",
        )
        for stage, cap in (("debate_round_1", 2000), ("debate_round_2", 4000))
        for slot in range(1, 5)
    ]
    _write(tmp_path, rows)
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "CLIPPED — 8 of 8" in out
    assert "NOT COMPARABLE" not in out


def test_mixed_caps_with_nothing_clipped_still_refuses(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: the mixed-cap refusal is deleted rather than reordered.

    The POSITIVE PARTNER for the test above. "Nothing clipped" cannot be read as
    "the cap fits" when the rows were not all given the same cap.
    """
    rows = [
        _captured(
            query_run_id="r",
            stage="debate_round_2",
            slot_number=slot,
            max_tokens=cap,
            completion_tokens=50,
            finish_reason="stop",
        )
        for cap in (2000, 4000)
        for slot in (1, 2)
    ]
    _write(tmp_path, rows)
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "NOT COMPARABLE" in out


def test_the_clipped_verdict_names_which_round_clipped(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: the pooled verdict line hides which round clipped.

    ADR-0096 made round 2 carry the revised answer ``synthesis`` reads, so a
    round-2 clip cuts the source-backed answer while a round-1 clip cuts a
    critique. Two opposite run shapes previously produced a BYTE-IDENTICAL
    verdict line — the sentence a reader quotes.

    Both arms, because one alone would pass against a hardcoded string.
    """

    def drive(clipping_stage: str) -> str:
        rows = [
            _captured(
                query_run_id="r",
                stage=stage,
                slot_number=slot,
                max_tokens=4000,
                completion_tokens=4000 if stage == clipping_stage else 300,
                finish_reason="length" if stage == clipping_stage else "stop",
            )
            for stage in ("debate_round_1", "debate_round_2")
            for slot in range(1, 5)
        ]
        _write(tmp_path, rows)
        code, out, _err = _run(tmp_path, capsys)
        assert code == 0
        return out

    assert "(debate_round_1 4/4)" in drive("debate_round_1")
    assert "(debate_round_2 4/4)" in drive("debate_round_2")


def test_a_reply_longer_than_the_cap_is_not_called_at_the_ceiling(
    tmp_path: Path, capsys: Any
) -> None:
    """RED WHEN: ``>=`` lets an over-cap reply borrow the at-the-cap reason.

    The justification quoted is "a clipped reply reports EXACTLY the cap". With
    ``>=``, a 9000-token reply against a 4000 cap printed that sentence — the
    number in it refuting the reason in it, and the implied action (raise the
    cap) costs money. Reachability is unverified; the sentence was wrong either
    way.
    """
    _write(
        tmp_path,
        [
            _captured(
                query_run_id="r",
                stage="debate_round_2",
                slot_number=1,
                max_tokens=4000,
                completion_tokens=9000,
                finish_reason="stop",
            )
        ],
    )
    code, out, _err = _run(tmp_path, capsys)
    assert code == 0
    assert "OVER THE CAP" in out
    assert "AT THE CEILING" not in out


@pytest.mark.parametrize(
    ("argv_extra", "expected"),
    [
        (["--run=paid"], "unrecognised argument"),
        (["--run", "a", "--run", "b"], "given more than once"),
        (["--unknown"], "unrecognised argument"),
    ],
)
def test_argv_shapes_that_would_be_silently_misread_are_refused(
    tmp_path: Path, capsys: Any, argv_extra: list[str], expected: str
) -> None:
    """RED WHEN: an unparsed flag is read as a directory, or a second --run wins.

    ``--run=<id>`` is standard GNU form. Unhandled, it was taken as a DIRECTORY
    and the operator — who had named the run correctly — was told to re-copy the
    volume of a paid run. ``--run A --run B`` silently honoured A, in a report
    whose stated contract is that it will not guess which run.
    """
    _write(tmp_path, _NEW_CLEAN_RUN)
    code = report.main([str(tmp_path), *argv_extra])
    assert code == 2
    # The exact refusal, not just exit 2: measured, both of these were being
    # caught by the "more than one directory" guard instead of their own, so
    # mutants deleting each specific guard survived a code-only assertion.
    assert expected in capsys.readouterr().err


def test_a_second_directory_is_refused_rather_than_ignored(tmp_path: Path, capsys: Any) -> None:
    """RED WHEN: extra positionals are dropped.

    Reading the first of two silently is how the wrong harvest gets reported.
    """
    _write(tmp_path, _NEW_CLEAN_RUN)
    code = report.main([str(tmp_path), str(tmp_path / "other")])
    assert code == 2
    assert "more than one directory" in capsys.readouterr().err
