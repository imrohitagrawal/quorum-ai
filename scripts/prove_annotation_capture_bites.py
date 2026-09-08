"""Re-runnable mutation proof for the #447 annotation capture (ADR-0104).

SCOPE: the capture (``providers.py``, ``telemetry_sink.py``) AND the reader
(``scripts/window_measurement_report.py``). The capture's mutants shipped with
ADR-0104; the reader's arrive here with ADR-0105.

WHY THIS IS COMMITTED RATHER THAN RUN BY HAND
---------------------------------------------
The first version of this work reported "15 of 15 hand-written mutants killed"
from a script that was then deleted. Nobody could re-run it, and the claim was
worth exactly nothing as adequacy evidence: independent reviewers writing their
own mutants found **17 survivors** across the same two test files, including a
passage leak that the leak test itself was blind to and a deleted event filter
that turned the empty-input refusal into a clean report.

So the mutants live here. Every one below reintroduces a defect that a reviewer
DEMONSTRATED, and each names the test that must catch it.

WHAT IT DOES
------------
For each mutant: copy the file aside with ``cp``, apply a unique-anchored
edit, run the named tests, restore from the copy, and confirm with ``diff -q``.
Never ``git checkout`` — that discards uncommitted work (AGENTS.md rule 6).

A baseline run comes FIRST and the script refuses to score anything if the
baseline is red, because a 100% kill rate over a broken harness is the classic
false signal.

Usage::

    python scripts/prove_annotation_capture_bites.py

Exit 0 when every mutant is killed; exit 1 on any survivor or invalid anchor.
Not wired into CI: it mutates ``src/``, so it must never run against a shared
working tree that something else is reading (AGENTS.md rule 9a). Run it
deliberately, on a tree you own.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = ROOT / "src" / "product_app" / "providers.py"
REPORT = ROOT / "scripts" / "window_measurement_report.py"
SINK = ROOT / "src" / "product_app" / "telemetry_sink.py"

T_ANN = "tests/unit/test_provider_annotation_shape.py"
T_RPT = "tests/unit/test_window_measurement_report.py"
T_SINK = "tests/unit/test_telemetry_sink.py"
ALL_TESTS = (T_ANN, T_RPT, T_SINK)

#: ``(name, file, old, new, tests)``. ``old`` must appear EXACTLY ONCE or the
#: mutant is reported INVALID rather than silently mutating the wrong function
#: -- a hand-rolled proof that string-matches non-unique source will mutate
#: something else and report a false survivor.
MUTANTS: tuple[tuple[str, Path, str, str, tuple[str, ...]], ...] = (
    (
        "the annotation argument is dropped from the log call",
        PROVIDERS,
        "                annotations=_annotation_shape(parsed),\n",
        "",
        (T_ANN,),
    ),
    (
        "the shape is computed OUTSIDE the contextlib.suppress (money safety)",
        PROVIDERS,
        "        with contextlib.suppress(Exception):\n            _log_call_token_shape(",
        "        _hoisted = _annotation_shape(parsed)\n"
        "        with contextlib.suppress(Exception):\n            _log_call_token_shape(",
        (T_ANN,),
    ),
    (
        "content_chars defaults to 0 instead of ABSENT",
        PROVIDERS,
        "    content_chars = total_chars if seen_content else None",
        "    content_chars = total_chars",
        (T_ANN,),
    ),
    (
        "a non-string content no longer counts as PRESENT",
        PROVIDERS,
        '    if isinstance(nested, dict) and "content" in nested:\n        seen = True',
        '    if isinstance(nested, dict) and isinstance(nested.get("content"), str):\n'
        "        seen = True",
        (T_ANN,),
    ),
    (
        # Found by the CI mutation gate, not by this set: the list-of-parts
        # fixture had ONE dict-with-text part, so `+=` and `=` agreed.
        "the content-parts sum keeps only the LAST part instead of adding",
        PROVIDERS,
        "                if isinstance(text, str):\n                    total += len(text)",
        "                if isinstance(text, str):\n                    total = len(text)",
        (T_ANN,),
    ),
    (
        "a list of content parts counts zero characters",
        PROVIDERS,
        "    if isinstance(value, list):\n        total = 0",
        "    if isinstance(value, list) and False:\n        total = 0",
        (T_ANN,),
    ),
    (
        "the content SHAPE collapses every non-string to 'other'",
        PROVIDERS,
        "    if isinstance(value, list):\n        return ANNOTATION_CONTENT_LIST",
        "    if isinstance(value, list):\n        return ANNOTATION_CONTENT_OTHER",
        (T_ANN,),
    ),
    (
        "annotations are no longer de-duplicated (the cumulative-resend bug)",
        PROVIDERS,
        "        if key in seen_keys:\n            continue",
        "        if False:\n            continue",
        (T_ANN,),
    ),
    (
        "arrivals reports the distinct count instead of the raw one",
        PROVIDERS,
        "    arrivals = len(annotations)",
        "    arrivals = 0",
        (T_ANN,),
    ),
    (
        "the tie-break is reversed (nested wins over flat)",
        PROVIDERS,
        '    if first.get("url") or first.get("source"):\n        label = ANNOTATION_SHAPE_FLAT\n'
        '    elif isinstance(first.get("url_citation"), dict):\n        label = '
        "ANNOTATION_SHAPE_NESTED",
        '    if isinstance(first.get("url_citation"), dict):\n        label = '
        "ANNOTATION_SHAPE_NESTED\n"
        '    elif first.get("url") or first.get("source"):\n        label = ANNOTATION_SHAPE_FLAT',
        (T_ANN,),
    ),
    (
        "the 'source' key is no longer read as flat",
        PROVIDERS,
        '    if first.get("url") or first.get("source"):',
        '    if first.get("url"):',
        (T_ANN,),
    ),
    (
        "the upstream's own 'type' string becomes the label (unbounded write)",
        PROVIDERS,
        "        label = ANNOTATION_SHAPE_OTHER\n    return AnnotationShape(label, count, arrivals",
        '        label = str(first.get("type") or ANNOTATION_SHAPE_OTHER)\n'
        "    return AnnotationShape(label, count, arrivals",
        (T_ANN,),
    ),
    (
        "'annotations or citations' precedence is reversed",
        PROVIDERS,
        '    annotations = message.get("annotations") or message.get("citations") or []\n'
        "    if not isinstance(annotations, list) or not annotations:\n"
        "        return _NO_ANNOTATIONS",
        '    annotations = message.get("citations") or message.get("annotations") or []\n'
        "    if not isinstance(annotations, list) or not annotations:\n"
        "        return _NO_ANNOTATIONS",
        (T_ANN,),
    ),
    (
        "the fold stops recording sites it does not collect from",
        PROVIDERS,
        "            if _has_annotation_content(choice):\n"
        "                annotation_sites.add(ANNOTATION_SITE_CHOICE)",
        "            if False:\n                annotation_sites.add(ANNOTATION_SITE_CHOICE)",
        (T_ANN,),
    ),
    (
        "the usable count is INFERRED from the label instead of measured",
        PROVIDERS,
        "                annotation_usable_count=_annotation_usable_count(parsed),",
        "                annotation_usable_count=_annotation_shape(parsed).count,",
        (T_ANN,),
    ),
    (
        "the usable count includes the inline-markdown fallback",
        PROVIDERS,
        '    return len(_extract_citations(deduped, content=""))',
        "    return len(_extract_citations(payload))",
        (T_ANN,),
    ),
    (
        "the passage text itself is written to the durable stream",
        PROVIDERS,
        '        "annotation_count": annotations.count,',
        '        "annotation_count": annotations.count,\n'
        '        "annotation_shape_debug": ["SENTINEL-PASSAGE-" + "z" * 103],',
        (T_ANN,),
    ),
    (
        "the annotation names are dropped from TELEMETRY_FIELD_NAMES",
        SINK,
        '        "annotation_shape",\n        "annotation_count",\n',
        "",
        (T_ANN, T_SINK),
    ),
    # --- round 3. Found by attacking the printed ANSWER rather than the code,
    # --- and by a reviewer mutating the round-2 fix.
    # --- round 4. Two of these are mutants a reviewer wrote that the round-3
    # --- set could not see, and both were in judgement VALUES rather than
    # --- control flow -- the class this harness is structurally weakest at.
    (
        "the whole-body probe selects choices[0] instead of the index-0 choice",
        PROVIDERS,
        "    first = _index_zero_choice(choices)\n    if first is None:",
        "    first = choices[0] if isinstance(choices[0], dict) else None\n    if first is None:",
        (T_ANN,),
    ),
    # --- round 2. Every mutant below reintroduces a defect that survived the
    # --- first 34, found by reviewers writing mutants the author had not.
    (
        "a site is recorded for key PRESENCE rather than key CONTENT",
        PROVIDERS,
        "    return any(bool(container.get(key)) for key in _ANNOTATION_KEYS)",
        "    return bool(_ANNOTATION_KEYS & container.keys())",
        (T_ANN,),
    ),
    (
        "the whole-body path checks only choices[0].message, as it first did",
        PROVIDERS,
        "    sites: set[str] = set()\n    if _has_annotation_content(whole):\n"
        "        sites.add(ANNOTATION_SITE_FRAME)",
        "    sites: set[str] = set()\n    if False:\n        sites.add(ANNOTATION_SITE_FRAME)",
        (T_ANN,),
    ),
    (
        "the whole-body path stops recording the choice site",
        PROVIDERS,
        "    if _has_annotation_content(first):\n        sites.add(ANNOTATION_SITE_CHOICE)",
        "    if False:\n        sites.add(ANNOTATION_SITE_CHOICE)",
        (T_ANN,),
    ),
    (
        "the whole-body probe is gutted entirely",
        PROVIDERS,
        "                                annotation_sites=_whole_body_annotation_sites(whole),",
        "                                annotation_sites=frozenset(),",
        (T_ANN,),
    ),
    (
        "the usable count is taken over the RAW block, not the distinct one",
        PROVIDERS,
        '    deduped = {"choices": [{"message": {"content": "", "annotations": distinct}}]}',
        '    deduped = {"choices": [{"message": {"content": "", "annotations": block}}]}',
        (T_ANN,),
    ),
    (
        "a content label loses its rank entry (would delete the whole record)",
        PROVIDERS,
        "    ANNOTATION_CONTENT_LIST,\n    ANNOTATION_CONTENT_STRING,\n)",
        "    ANNOTATION_CONTENT_STRING,\n)",
        (T_ANN,),
    ),
    (
        "the content rank order is permuted (mapping/null swapped)",
        PROVIDERS,
        "    ANNOTATION_CONTENT_MAPPING,\n    ANNOTATION_CONTENT_NULL,",
        "    ANNOTATION_CONTENT_NULL,\n    ANNOTATION_CONTENT_MAPPING,",
        (T_ANN,),
    ),
    (
        "a fifth site label is added without widening the vocabulary",
        PROVIDERS,
        "        ANNOTATION_SITE_FRAME,\n    }\n)",
        "    }\n)",
        (T_ANN,),
    ),
    (
        "the harvester exits 0 on empty input",
        REPORT,
        '            "the build under test emits the token stream.",\n'
        "            file=sys.stderr,\n        )\n        return 1",
        '            "the build under test emits the token stream.",\n'
        "            file=sys.stderr,\n        )\n        return 0",
        (T_RPT,),
    ),
    (
        "the harvester stops filtering on the token event name",
        REPORT,
        '    return [row for row in rows if row.get("message") == TOKEN_EVENT]',
        "    return list(rows)",
        (T_RPT,),
    ),
    (
        "unparsable lines are skipped without being counted",
        REPORT,
        "        except json.JSONDecodeError:\n            skipped += 1",
        "        except json.JSONDecodeError:\n            skipped += 0",
        (T_RPT,),
    ),
    (
        "uncorrelated rows are pooled into a run again",
        REPORT,
        "        if not isinstance(run_id, str) or not run_id:\n"
        "            uncorrelated.append(row)\n            continue",
        '        if not isinstance(run_id, str) or not run_id:\n            run_id = ""',
        (T_RPT,),
    ),
    (
        "runs are ordered by first appearance instead of last",
        REPORT,
        "        last_seen[run_id] = position",
        "        last_seen.setdefault(run_id, position)",
        (T_RPT,),
    ),
    (
        "a run with no usable finish_reason reports FITS",
        REPORT,
        '    if uninformative:\n        return (\n            f"NOT MEASURED',
        '    if False:\n        return (\n            f"NOT MEASURED',
        (T_RPT,),
    ),
    (
        "a reply exactly at the cap reports FITS",
        REPORT,
        "    if caps and longest is not None and longest == min(caps):",
        "    if caps and longest is not None and longest == -1:",
        (T_RPT,),
    ),
    (
        "two caps in one group no longer refuse",
        REPORT,
        '    if len(caps) > 1:\n        return (\n            f"NOT COMPARABLE',
        '    if False:\n        return (\n            f"NOT COMPARABLE',
        (T_RPT,),
    ),
    (
        "completion_max reports the minimum",
        REPORT,
        '        "completion_max": max(completions) if completions else None,',
        '        "completion_max": min(completions) if completions else None,',
        (T_RPT,),
    ),
    (
        "one field-less row vetoes the whole measurement again",
        REPORT,
        "    if captured == 0:",
        "    if captured < searching:",
        (T_RPT,),
    ),
    (
        "absent annotations are blamed on the provider regardless of site",
        REPORT,
        '        if not result["missed_site_calls"]:\n            lines.append(\n'
        '                f"NO ANNOTATIONS ON THE WIRE',
        '        if True:\n            lines.append(\n                f"NO ANNOTATIONS ON THE WIRE',
        (T_RPT,),
    ),
    (
        "zero characters of content reports ROUTE A POSSIBLE",
        REPORT,
        '    elif not result["content_chars_total"]:',
        "    elif False:",
        (T_RPT,),
    ),
    (
        "the M3 census counts calls that never asked for search",
        REPORT,
        '    shapes = Counter(str(row.get("annotation_shape", FIELD_MISSING))'
        " for row in searching)",
        '    shapes = Counter(str(row.get("annotation_shape", FIELD_MISSING)) for row in rows)',
        (T_RPT,),
    ),
    (
        "the critique cost counts round 2 only",
        REPORT,
        "CRITIQUE_STAGES = (STAGE_DEBATE_ROUND_1, STAGE_DEBATE_ROUND_2)",
        "CRITIQUE_STAGES = (STAGE_DEBATE_ROUND_2,)",
        (T_RPT,),
    ),
    (
        "the debate-fit reading looks at round 2 only, as it first did",
        REPORT,
        '    stage_rows = [row for row in rows if row.get("stage") in CRITIQUE_STAGES]\n'
        "    reasons = Counter(",
        '    stage_rows = [row for row in rows if row.get("stage") == STAGE_DEBATE_ROUND_2]\n'
        "    reasons = Counter(",
        (T_RPT,),
    ),
    (
        "the per-round split is dropped, hiding WHICH round clipped",
        REPORT,
        "    per_round = {}\n    for stage in CRITIQUE_STAGES:",
        "    per_round = {}\n    for stage in ():",
        (T_RPT,),
    ),
    (
        "the report guesses a headline when two runs are present",
        REPORT,
        "    if wanted_run is None and len(ordered) > 1:",
        "    if False:",
        (T_RPT,),
    ),
    (
        "--run is ignored and the default is used instead",
        REPORT,
        "    selected = wanted_run if wanted_run is not None else ordered[0]",
        "    selected = ordered[0]",
        (T_RPT,),
    ),
    (
        "an unknown --run silently falls back to a default",
        REPORT,
        "    if wanted_run is not None and wanted_run not in grouped:",
        "    if False:",
        (T_RPT,),
    ),
    (
        "the missed-site reading is gated on the run's annotation total again",
        REPORT,
        '    if result["missed_site_calls"]:',
        '    if result["missed_site_calls"] and not result["annotations_total"]:',
        (T_RPT,),
    ),
    (
        "the passage floor is removed, so a snippet reads as a passage",
        REPORT,
        '    elif (result["content_chars_max"] or 0) < MIN_PASSAGE_CHARS:',
        "    elif False:",
        (T_RPT,),
    ),
    (
        "measurement 1 loses its completeness verdict",
        REPORT,
        "    if calls < EXPECTED_CRITIQUE_CALLS:",
        "    if False:",
        (T_RPT,),
    ),
    (
        "an empty debate claims the round never ran",
        REPORT,
        '            "NO DEBATE ROWS — no debate_round_1 or debate_round_2 token rows are "',
        '            "NO ROUND-2 ROWS — the run produced no debate_round_2 call at all. "',
        (T_RPT,),
    ),
    (
        "the passage floor is set uselessly LOW rather than removed",
        REPORT,
        "MIN_PASSAGE_CHARS = 200",
        "MIN_PASSAGE_CHARS = 2",
        (T_RPT,),
    ),
    (
        "the timestamp window collapses to its last stamp",
        REPORT,
        'window = f"{stamps[0]} .. {stamps[-1]}" if stamps else "(no timestamps)"',
        'window = f"{stamps[-1]} .. {stamps[-1]}" if stamps else "(no timestamps)"',
        (T_RPT,),
    ),
    (
        "a call that delta DID read is counted as entirely missed",
        REPORT,
        '        if "delta" not in str(row.get("annotation_sites", FIELD_MISSING)).split(",")',
        '        if True or "delta" in str(row.get("annotation_sites", FIELD_MISSING))',
        (T_RPT,),
    ),
    (
        "the partial-sample line is dropped",
        REPORT,
        '    if result["partly_missed_calls"]:',
        "    if False:",
        (T_RPT,),
    ),
    (
        "the mixed-cap refusal moves back above the positive evidence",
        REPORT,
        '    if len(caps) > 1:\n        return (\n            f"NOT COMPARABLE — no reply clipped',
        "    if len(caps) > 1 or True:\n        return (\n"
        '            f"NOT COMPARABLE — no reply clipped',
        (T_RPT,),
    ),
    (
        "an over-cap reply borrows the exactly-at-the-cap reason",
        REPORT,
        "    if caps and longest is not None and longest > min(caps):",
        "    if False:",
        (T_RPT,),
    ),
    (
        "the clipped verdict stops naming which round clipped",
        REPORT,
        "f\"'length' at cap(s) {caps} ({where}). The cap did NOT fit.{partial}\"",
        "f\"'length' at cap(s) {caps}. The cap did NOT fit.{partial}\"",
        (T_RPT,),
    ),
    (
        "the short-critique verdict invents a cause again",
        REPORT,
        '            f"FEWER THAN A FULL PEER ROUND — {calls} of the {EXPECTED_CRITIQUE_CALLS} "',
        "            f\"PARTIAL — a floor, not the run's cost — {calls} of the "
        '{EXPECTED_CRITIQUE_CALLS} "',
        (T_RPT,),
    ),
    (
        "--run=<id> is read as a directory instead of refused",
        REPORT,
        '    unknown = [a for a in args if a.startswith("-")]',
        "    unknown = []",
        (T_RPT,),
    ),
    (
        "a second --run is silently ignored",
        REPORT,
        '    if args.count("--run") > 1:',
        "    if False:",
        (T_RPT,),
    ),
    (
        "a second directory is silently ignored",
        REPORT,
        "    if len(args) > 1:",
        "    if False:",
        (T_RPT,),
    ),
    (
        "the judge's prompt tokens are hardcoded to zero",
        REPORT,
        '    stage_rows = [row for row in rows if row.get("stage") == STAGE_JUDGE]\n'
        "    return {\n"
        '        "calls": len(stage_rows),\n'
        '        "prompt_tokens": sum(_ints(stage_rows, "prompt_tokens")),',
        '    stage_rows = [row for row in rows if row.get("stage") == STAGE_JUDGE]\n'
        "    return {\n"
        '        "calls": len(stage_rows),\n'
        '        "prompt_tokens": 0,',
        (T_RPT,),
    ),
    (
        "usage_absent is no longer counted per stage",
        REPORT,
        '            "usage_absent": sum('
        '1 for row in stage_rows if row.get("usage_absent") is True),',
        '            "usage_absent": 0,',
        (T_RPT,),
    ),
    (
        "bools are allowed into the token distributions",
        REPORT,
        "        if isinstance(value, int) and not isinstance(value, bool):",
        "        if isinstance(value, int):",
        (T_RPT,),
    ),
    (
        "the unparsable ceiling is loosened 0.05 -> 0.99",
        REPORT,
        "MAX_UNPARSABLE_SHARE = 0.05",
        "MAX_UNPARSABLE_SHARE = 0.99",
        (T_RPT,),
    ),
    (
        "the uninformative refusal is moved ABOVE the positive evidence",
        REPORT,
        '    if result["clipped"]:\n        where = ',
        '    if uninformative:\n        return "NOT MEASURED — moved"\n'
        '    if result["clipped"]:\n        where = ',
        (T_RPT,),
    ),
    (
        "the refusal is widened so a real CLIPPED reading is discarded",
        REPORT,
        '    if result["clipped"]:\n        where = ',
        '    if uninformative:\n        return "NOT MEASURED — widened"\n'
        '    if result["clipped"]:\n        where = ',
        (T_RPT,),
    ),
    (
        "the rotation scope line is dropped",
        REPORT,
        '    print(f"Reads {TOKENS_FILE_NAME} only — rotated backups (.1-.4) are NOT included.")',
        "    pass",
        (T_RPT,),
    ),
)


def _run_tests(tests: tuple[str, ...]) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *tests, "-q", "--no-cov", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    output = (proc.stdout + proc.stderr).strip().splitlines()
    return proc.returncode, output[-1] if output else "(no output)"


def main() -> int:
    print("=== BASELINE (unmutated) ===")
    code, summary = _run_tests(ALL_TESTS)
    print(f"  EXIT={code}  {summary}")
    if code != 0:
        print("\nBASELINE IS RED. Every kill below would be meaningless. Stopping.")
        return 1

    killed: list[str] = []
    survived: list[tuple[str, str]] = []
    invalid: list[tuple[str, str]] = []

    for name, path, old, new, tests in MUTANTS:
        backup = path.with_suffix(path.suffix + ".mutbak")
        shutil.copy2(path, backup)
        try:
            source = path.read_text()
            occurrences = source.count(old)
            if occurrences != 1:
                invalid.append((name, f"anchor matched {occurrences} times, not 1"))
                continue
            path.write_text(source.replace(old, new))
            if path.read_text() == backup.read_text():
                invalid.append((name, "the mutation changed no bytes"))
                continue
            code, summary = _run_tests(tests)
        finally:
            # Restore from the COPY, never ``git checkout`` -- that would
            # discard uncommitted work (AGENTS.md rule 6). Verified with
            # ``diff -q``: a proof that leaves the tree mutated poisons every
            # measurement taken after it.
            shutil.copy2(backup, path)
            restored = subprocess.run(["diff", "-q", str(path), str(backup)], capture_output=True)
            backup.unlink()
            restore_failed = restored.returncode != 0
        if restore_failed:
            print(f"\nRESTORE FAILED for {path}. STOP and inspect the tree.")
            return 1
        if code != 0:
            killed.append(name)
        else:
            survived.append((name, summary))

    total = len(MUTANTS)
    print(f"\n=== KILLED {len(killed)}/{total} ===")
    for name in killed:
        print(f"  KILLED    {name}")
    if survived:
        print(f"\n=== SURVIVED {len(survived)} — these tests do NOT bite ===")
        for name, summary in survived:
            print(f"  SURVIVED  {name}\n              {summary}")
    if invalid:
        print(f"\n=== INVALID {len(invalid)} — the anchor is wrong, not the tests ===")
        for name, why in invalid:
            print(f"  INVALID   {name}: {why}")
    return 0 if not survived and not invalid else 1


if __name__ == "__main__":
    raise SystemExit(main())
