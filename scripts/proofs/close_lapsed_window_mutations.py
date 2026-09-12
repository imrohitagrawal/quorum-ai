"""Re-runnable mutation proof for the #460 lapsed-window fix.

`make close-window` existed to revert a live-execution posture in one command,
and refused to do anything in the single most likely real case: a window that
had already lapsed while `OPENROUTER_LIVE_EXECUTION_ENABLED` still read
`"true"`. That is the 2026-09-11 shape — the window expired at 07:51:25Z and
production kept serving a spend-capable posture for 21.6-25.5h past its own
expiry.

The fix LOOSENS a refusal, so both directions have to be proven (AGENTS.md):
the false refusal is gone, AND every genuine refusal still fires. The genuine
ones are two, and they are different:

* the flag already reads off -> nothing to revert;
* a STANDING window is declared -> it has no expires_at and its sanction is a
  policy decision this script never makes.

Mutations 01-03 attack the standing boundary, 04-07 the revert itself, and 08-11
are the four defects adversarial review found in the first version of this fix:
an unrecognised `mode` read as "no window" (which silently ended a standing
sanction), every absence reported as a lapse that happened, the deploy
instruction dropped from the success path, and the two refusals collapsed into
one generic message. Mutation 11 SURVIVED twice before it killed -- first
because nothing read the standing message at all, then because asserting one
shared substring still matched the mutated text.

Applies each mutation by hand, runs the tests, restores the file from a `cp`
copy, and verifies with `diff -q` that the tree came back byte-identical.
Never uses `git checkout` (it would discard uncommitted work).

    uv run python scripts/proofs/close_lapsed_window_mutations.py

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
FILES = {"closer": ROOT / "scripts" / "close_live_window.py"}
TESTS = ["tests/unit/test_close_live_window.py", "tests/unit/test_live_posture_check.py"]

#: The single formatted line ``ruff format`` produces for
#: ``has_standing_window``'s return. Kept as a constant because BOTH the
#: "always standing" and "never standing" mutations replace it, and a
#: hand-copied duplicate is exactly how an anchor silently goes stale.
_STANDING_RETURN_SRC = (
    '    return any(isinstance(entry, dict) and entry.get("mode") == MODE_STANDING '
    "for entry in windows)"
)

#: (label, file key, exact text to find, replacement). Each anchor MUST be
#: unique in the file — a non-unique anchor silently mutates a namesake
#: elsewhere and reports a false SURVIVED. `make format` reflows Python, so
#: re-run this proof AFTER formatting.
MUTATIONS: list[tuple[str, str, str, str]] = [
    (
        "01 the standing guard is dropped from the revert condition",
        "closer",
        "    if not closed and not has_standing_window(payload):",
        "    if not closed:",
    ),
    (
        "02 every payload looks standing (the revert never fires)",
        "closer",
        _STANDING_RETURN_SRC,
        "    return True",
    ),
    (
        "03 no payload looks standing (a standing sanction is silently ended)",
        "closer",
        _STANDING_RETURN_SRC,
        "    return False",
    ),
    (
        "04 the reverted flag is computed but never written",
        "closer",
        '            stranded_path.write_text(reverted_text, encoding="utf-8")',
        "            pass",
    ),
    (
        "05 the lapsed revert reports failure instead of success",
        "closer",
        '                f"and a `fly secrets set {FLAG}` would override it."\n'
        "            )\n"
        "            return 0",
        '                f"and a `fly secrets set {FLAG}` would override it."\n'
        "            )\n"
        "            return 1",
    ),
    (
        "06 the lapsed branch also rewrites the declaration file",
        "closer",
        '            stranded_path.write_text(reverted_text, encoding="utf-8")\n'
        "            # Say what was ACTUALLY found.",
        '            stranded_path.write_text(reverted_text, encoding="utf-8")\n'
        '            windows_path.write_text("{}", encoding="utf-8")\n'
        "            # Say what was ACTUALLY found.",
    ),
    # 08-11 are the defects ADVERSARIAL REVIEW found in the FIRST version of
    # this fix. 08 is the dangerous one: two independent reviewers showed that a
    # wrongly-cased "Standing" was invisible to has_standing_window, fell into
    # the lapsed-revert branch, and SILENTLY ENDED A STANDING SANCTION. 11 is a
    # mutation a reviewer ran that SURVIVED the original suite, because nothing
    # read the standing refusal's message.
    (
        "08 an unrecognised mode is treated as 'no window' (ends a sanction)",
        "closer",
        "    return [\n"
        '        str(entry.get("mode"))\n'
        "        for entry in windows\n"
        '        if isinstance(entry, dict) and entry.get("mode") '
        "not in (MODE_TIME_BOXED, MODE_STANDING)\n"
        "    ]",
        "    return []",
    ),
    (
        "09 every absence is reported as a lapse that happened",
        "closer",
        "    if lapsed:",
        "    if True:",
    ),
    (
        "10 the revert stops telling the operator to deploy and verify",
        "closer",
        '                "Commit it, DEPLOY, then verify /status.live_execution yourself: "',
        '                "" ',
    ),
    (
        "11 the two refusals collapse back into ONE generic message",
        "closer",
        "            f\"Checked {windows_path}: a 'standing' window is declared, which has \"\n"
        '            "no expires_at to close and whose sanction is a POLICY decision this "\n'
        '            "script never makes. If the live posture should end, retire the "\n'
        '            "standing declaration deliberately.",',
        '            f"Checked {windows_path}: nothing is currently open.",',
    ),
    (
        "07 an already-off flag is treated as a successful revert",
        "closer",
        "        if flag_was_on:",
        "        if True:",
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
                print(f"  {label:62} ANCHOR NOT UNIQUE (x{count}) — proof invalid")
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
            print(f"  {label:62} {status} restore={restore} | {tail[-1] if tail else ''}")
            if not killed or clean.returncode != 0:
                failures += 1

    print(f"\n{len(MUTATIONS) - failures} killed / {len(MUTATIONS)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
