"""Re-runnable mutation proof for the #447 annotation capture (ADR-0104).

SCOPE: the CAPTURE only (``providers.py``, ``telemetry_sink.py``). The reader
that turns these fields into a verdict ships separately, under ``scripts/``,
and brings its own mutants — the two answer different questions and a reviewer
cannot audit both in one diff. See ADR-0105.

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
SINK = ROOT / "src" / "product_app" / "telemetry_sink.py"

T_ANN = "tests/unit/test_provider_annotation_shape.py"
T_SINK = "tests/unit/test_telemetry_sink.py"
ALL_TESTS = (T_ANN, T_SINK)

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
