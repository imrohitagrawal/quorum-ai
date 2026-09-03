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
        "                and any(source.provider is ProviderPath.WEB_SEARCH"
        " for source in answer.sources)",
        "                and answer.sources",
    ),
    # --- the UI -------------------------------------------------------------
    (
        "07 stub badge keys on is_fallback again",
        "app",
        "    return s.isFallback === true && !REAL_SOURCE_PROVIDERS.has(s.provider);",
        "    return s.isFallback === true;",
    ),
    (
        "08 fail-safe dropped: unknown provider laundered as real",
        "app",
        "    if (STUB_SOURCE_PROVIDERS.has(s.provider)) return true;\n"
        "    return s.isFallback === true && !REAL_SOURCE_PROVIDERS.has(s.provider);",
        "    if (STUB_SOURCE_PROVIDERS.has(s.provider)) return true;\n    return false;",
    ),
    # --- the judge disclosure ----------------------------------------------
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

    print(f"\n{len(MUTATIONS) - failures} killed / {len(MUTATIONS)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
