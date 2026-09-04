"""Re-runnable mutation proof for ADR-0098 (the retrieved-source discriminator).

A mutation count nobody else can re-run is an unfalsifiable number, so every
mutation is listed here as an exact (anchor, replacement) pair rather than
described in a commit body.

Applies each mutation by hand, runs the tests, restores the file from a `cp`
copy, and verifies with `diff -q` that the tree came back byte-identical.
Never uses `git checkout` (it would discard uncommitted work).

    uv run python scripts/proofs/retrieved_source_classification_mutations.py

Exit 0 only when every mutation is KILLED and every restore is byte-identical.
A RED baseline exits 2 without reporting a kill count: a kill count measured
against a red baseline proves nothing.

NOTE ON ANCHORS: each anchor MUST occur exactly once in its file. A non-unique
anchor silently mutates a namesake elsewhere and reports a false SURVIVED —
which is how an earlier proof in this repo reported 3 phantom survivors. The
runner refuses rather than guessing.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
FILES = {
    "prov": ROOT / "src" / "product_app" / "providers.py",
    "synth": ROOT / "src" / "product_app" / "synthesis.py",
    "app": ROOT / "src" / "product_app" / "static" / "app.js",
}
TESTS = [
    "tests/unit/test_retrieved_source_is_not_a_stub.py",
    "tests/unit/test_source_support_prose_counts_retrieved.py",
    "tests/unit/test_judge_disclosure_is_honest.py",
    "tests/unit/test_tavily_search.py",
    "tests/unit/test_not_invoked_is_not_evidence.py",
    "tests/unit/test_enum_membership_pins.py",
    "tests/unit/test_synthesis.py",
]

MUTATIONS: list[tuple[str, str, str, str]] = [
    # --- the discriminator itself -------------------------------------------
    (
        "01 retrieved page relabelled as the placeholder",
        "prov",
        "                provider=ProviderPath.WEB_SEARCH,",
        "                provider=ProviderPath.FALLBACK_SEARCH,",
    ),
    (
        "02 retrieved page stops being flagged non-own",
        "prov",
        "                # ...but it is still not the MODEL's own citation, so this flag\n"
        "                # stays True and ``citation_coverage`` is deliberately unmoved.\n"
        "                is_fallback=True,",
        "                is_fallback=False,",
    ),
    (
        "03 WEB_SEARCH silently reads as 'a model was invoked'",
        "prov",
        "        ProviderPath.WEB_SEARCH,\n    }\n)",
        "    }\n)",
    ),
    # --- the coverage decision that must NOT move ---------------------------
    (
        "04 coverage starts counting retrieved pages",
        "prov",
        "        primary_source_count = sum(1 for source in sources if not source.is_fallback)",
        "        primary_source_count = len(sources)",
    ),
    # --- the prose ----------------------------------------------------------
    (
        "05 prose claims zero while sources are on screen",
        "synth",
        "            if retrieved:",
        "            if False:",
    ),
    (
        "06 prose credits web search for Quorum placeholders",
        "synth",
        "        and any(source.provider is ProviderPath.WEB_SEARCH for source in answer.sources)",
        "        and answer.sources",
    ),
    # --- the UI -------------------------------------------------------------
    (
        "07 stub badge keys on is_fallback again",
        "app",
        "    return fallback && !REAL_SOURCE_PROVIDERS.has(s.provider);",
        "    return fallback;",
    ),
    (
        "08 fail-safe dropped: unknown provider laundered as real",
        "app",
        "    if (STUB_SOURCE_PROVIDERS.has(s.provider)) return true;",
        "    if (false) return true;",
    ),
    (
        "10 chip row stops calling the shared predicate",
        "app",
        "          const isStub = isStubSource(s);",
        "          const isStub = STUB_SOURCE_PROVIDERS.has(s.provider) || s.isFallback === true;",
    ),
    (
        "11 export stops calling the shared predicate",
        "app",
        "        if (isStubSource(s)) {",
        "        if (s && (STUB_SOURCE_PROVIDERS.has(s.provider) || s.isFallback === true)) {",
    ),
    (
        "12 transcript list stops calling the shared predicate",
        "app",
        "        if (isStubSource(source)) {",
        "        if (STUB_SOURCE_PROVIDERS.has(source.provider)) {",
    ),
    (
        "13 predicate reads only one wire casing",
        "app",
        "    const fallback = s.isFallback === true || s.is_fallback === true;",
        "    const fallback = s.isFallback === true;",
    ),
    (
        "14 retrieved page left bare (no origin tag)",
        "app",
        '  const RETRIEVED_SOURCE_TAG_TEXT = "web search";',
        '  const RETRIEVED_SOURCE_TAG_TEXT = "";',
    ),
    (
        "15 export drops the origin qualifier",
        "app",
        '        const origin = isRetrievedSource(s) ? " — via web search" : "";',
        '        const origin = "";',
    ),
    (
        "17 transcript badges a real page 'fallback'",
        "app",
        "        if (isRetrievedSource(source)) {",
        "        if (false) {",
    ),
    (
        "18 the live section loses its retrieved-sources note",
        "synth",
        "            user_prompt=_with_retrieved_note(user_prompt, initial_answers),",
        "            user_prompt=user_prompt,",
    ),
    (
        "19 the note is claimed on a run that had no web search",
        "synth",
        "    if not retrieved:\n        return user_prompt",
        "    if False:\n        return user_prompt",
    ),
    # --- the judge disclosure ----------------------------------------------
    (
        "20 live note reports the total instead of the real count",
        "synth",
        'f"{user_prompt}\\n\\n{retrieved} of the answers cited no source of their own; "',
        'f"{user_prompt}\\n\\n{len(initial_answers)} of the answers cited no source '
        'of their own; "',
    ),
    (
        "21 counter drops the answer_count guard",
        "synth",
        "        if answer.citation_coverage.answer_count\n"
        "        and any(source.provider is ProviderPath.WEB_SEARCH for source in answer.sources)",
        "        if any(source.provider is ProviderPath.WEB_SEARCH for source in answer.sources)",
    ),
    (
        "09 the false 'support was checked' claim returns",
        "app",
        "    \"An independent judge model checked this answer's citations against its "
        "source list — an automated review, not a human fact-check. The cited "
        'pages themselves were not retrieved.";',
        '    "Citation support was checked by an independent judge model — an '
        'automated review, not a human fact-check.";',
    ),
]


def _purge() -> None:
    subprocess.run(
        "find src tests scripts -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null",
        shell=True,
        cwd=ROOT,
        check=False,
    )


def main() -> int:
    env = dict(os.environ, QUORUM_TOKEN_SECRET="x", PYTHONDONTWRITEBYTECODE="1")
    cmd = ["uv", "run", "pytest", *TESTS, "-q", "--no-cov", "-p", "no:randomly"]

    _purge()
    base = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env)
    base_line = [ln for ln in base.stdout.strip().splitlines() if ln.strip()]
    print(f"BASELINE: {base_line[-1] if base_line else '(no output)'}")
    if base.returncode != 0:
        print("BASELINE IS RED — a kill count against a red baseline proves nothing.")
        print(base.stdout[-3000:])
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        backups = {k: pathlib.Path(tmp) / f"{k}.bak" for k in FILES}
        for k, f in FILES.items():
            shutil.copy2(f, backups[k])

        failures = 0
        for label, key, old, new in MUTATIONS:
            text = backups[key].read_text()
            count = text.count(old)
            if count != 1:
                print(f"  {label:52} ANCHOR NOT UNIQUE (x{count}) — proof invalid")
                failures += 1
                continue
            FILES[key].write_text(text.replace(old, new))
            _purge()
            run = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env)
            shutil.copy2(backups[key], FILES[key])
            _purge()
            clean = subprocess.run(
                ["diff", "-q", str(FILES[key]), str(backups[key])], capture_output=True
            )
            killed = run.returncode != 0
            tail = [ln for ln in run.stdout.strip().splitlines() if ln.strip()]
            status = "KILLED  " if killed else "SURVIVED"
            restore = "ok" if clean.returncode == 0 else "DIRTY"
            print(f"  {label:52} {status} restore={restore} | {tail[-1] if tail else ''}")
            if not killed or clean.returncode != 0:
                failures += 1

    # FLOOR FIRST (rule 7). Printing "3 killed / 3" and only then refusing
    # leaves a number in the log that reads like a result; a reviewer caught
    # exactly that ordering. Refuse before any score is emitted.
    if len(MUTATIONS) < 15:
        print(f"FLOOR FAILED: only {len(MUTATIONS)} mutations declared; expected >= 15.")
        print("No score is reported: a partial mutation set is not a measurement.")
        return 2

    text_pins = sum(1 for _, key, _, _ in MUTATIONS if key == "app")
    print(f"\n{len(MUTATIONS) - failures} killed / {len(MUTATIONS)}")
    print(
        f"HOW MUCH THIS PROVES: {text_pins} of {len(MUTATIONS)} are app.js edits killed "
        "by Python string assertions, not by executing JavaScript. Rendering behaviour "
        "is proved by the blocking e2e lane (source-expander.spec.ts), not here. A "
        "reviewer defeated an earlier version of these same pins with textually "
        "different but behaviourally identical code, so read this number as "
        "'the pins are wired', never as 'the UI is correct'."
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
