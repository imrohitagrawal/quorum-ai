"""Re-runnable mutation proof for the mechanism-copy change (ADR-0099).

Exists because the FIRST version of this change shipped a mutation proof that
mutated a FUNCTION while nothing asserted the render path called it. Adversarial
review then defeated the whole suite by leaving ``describePeerCritique`` in
place as dead code and reverting both call sites: every user-visible sentence
went back to the falsehood and the tests stayed green. Mutations 01 and 02 below
ARE that defeat, replayed, so it can never pass silently again.

Mutation 05 is the second demonstrated defeat: moving the caption out of the
``mkEl(...)`` literal put it beyond ``test_ui_honesty``'s
``_extract_mkel_literals``, so ``BANNED_EXCHANGE_CLAIMS`` stopped covering the
sentence the product actually serves.

Applies each mutation by hand, runs the tests, restores the file from a `cp`
copy, and verifies with `diff -q` that the tree came back byte-identical.
Never uses `git checkout` (it would discard uncommitted work).

    uv run python scripts/proofs/mechanism_copy_mutations.py

Exit 0 only when every mutation is KILLED and every restore is byte-identical.
A kill count against a RED baseline proves nothing, so the baseline is printed
and a red one aborts with exit 2.
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
    "js": ROOT / "src" / "product_app" / "static" / "app.js",
    "main": ROOT / "src" / "product_app" / "main.py",
}
TESTS = [
    "tests/unit/test_peer_caption_counts.py",
    "tests/unit/test_ui_honesty.py",
]

#: (label, file key, exact text to find, replacement). Each anchor MUST be
#: unique in the file — a non-unique anchor silently mutates a namesake
#: elsewhere and reports a false SURVIVED. `make format` reflows JavaScript and
#: can invalidate these anchors, so re-run this proof AFTER formatting.
MUTATIONS: list[tuple[str, str, str, str]] = [
    (
        "01 result caption bypasses the helper",
        "js",
        """    const peerSentence = describePeerCritique(
      rounds,
      "The card shows the round's combined critique; the per-model detail is " +
        "recorded and itemised on the receipt.",
    );""",
        """    const peerSentence = rounds.some((r) => r && r.critique_shape === "peer")
      ? "Each answer model critiqued the others, in both rounds."
      : null;""",
    ),
    (
        "02 transcript caption bypasses the helper",
        "js",
        """    const transcriptPeerSentence = describePeerCritique(
      debate,
      "Below is the round-level critique; the per-model detail is recorded and " +
        "itemised on the receipt.",
    );""",
        """    const transcriptPeerSentence = debate.some((r) => r && r.critique_shape === "peer")
      ? "Each answer model critiqued the others, in both rounds."
      : null;""",
    ),
    (
        "03 counts dispatches, not answers",
        "js",
        '        live: critiques.filter((c) => c && c.critique_mode === "live").length,',
        "        live: critiques.length,",
    ),
    (
        "04 unknown branch renders a zero",
        "js",
        "    if (!perRound.every((r) => r.known)) {\n"
        "      return withDetail(`The answer models critiqued the others${scopeOf(peer)}.`);\n"
        "    }",
        "    if (false) {\n"
        "      return withDetail(`The answer models critiqued the others${scopeOf(peer)}.`);\n"
        "    }",
    ),
    (
        "05 banned exchange claim in the helper",
        "js",
        "      return withDetail(`The answer models critiqued the others${scopeOf(answered)}.`);",
        "      return withDetail(`Each model replied to the others' rebuttals in turn.`);",
    ),
    (
        "06 claim scoped to all rounds, not the answered ones",
        "js",
        "      return withDetail(`Each answer model critiqued the others${scopeOf(answered)}.`);",
        "      return withDetail(`Each answer model critiqued the others${scopeOf(peer)}.`);",
    ),
    (
        "07 synthesis attribution hard-coded again",
        "js",
        "        describeSynthesisInput(res || {}),",
        '        "from the four refined answers",',
    ),
    (
        "08 synthesis credits invisible revisions",
        "js",
        '        if (c && c.critique_mode === "live" && hasVisibleText(c.revised_answer)) {',
        '        if (c && c.critique_mode === "live" && String(c.revised_answer || "").trim()) {',
    ),
    (
        "09 transcript chip asserts disagreement again",
        "js",
        '      let chipText = "Not determined";\n'
        '      if (isConsensus) chipText = "Consensus reached";\n'
        '      else if (panelReading === "split") chipText = "Panel divided";',
        '      let chipText = "Panel divided";\n'
        '      if (isConsensus) chipText = "Consensus reached";',
    ),
    (
        "10 API description stops branching on the flag",
        "main",
        "    if active_settings.peer_critique_enabled:\n"
        "        mechanism = (\n"
        "            \"has them critique each other's answers and sources "
        'so each can revise its own, and "\n'
        "        )\n"
        "    else:\n"
        '        mechanism = "has a separate moderator model critique their answers, and "\n',
        "    mechanism = (\n"
        "        \"has them critique each other's answers and sources "
        'so each can revise its own, and "\n'
        "    )\n",
    ),
]


def _purge() -> None:
    """Drop stale bytecode so a mutated module is re-read, not re-used."""
    for pyc in ROOT.rglob("__pycache__"):
        shutil.rmtree(pyc, ignore_errors=True)


def main() -> int:
    env = dict(os.environ, QUORUM_TOKEN_SECRET="x", PYTHONDONTWRITEBYTECODE="1")
    cmd = ["uv", "run", "pytest", *TESTS, "-q", "--no-cov"]

    _purge()
    base = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env)
    base_line = [ln for ln in base.stdout.strip().splitlines() if ln.strip()]
    print(f"BASELINE: {base_line[-1] if base_line else '(no output)'}")
    if base.returncode != 0:
        print("BASELINE IS RED — a kill count against a red baseline proves nothing.")
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
                print(f"  {label:46} ANCHOR NOT UNIQUE (x{count}) — proof invalid")
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
            print(f"  {label:46} {status} restore={restore} | {tail[-1] if tail else ''}")
            if not killed or clean.returncode != 0:
                failures += 1

    print(f"\n{len(MUTATIONS) - failures} killed / {len(MUTATIONS)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
