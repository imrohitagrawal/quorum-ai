"""Re-runnable mutation proof for the #105 defect-B change (ADR-0110).

The change makes the MEASURED cost carry OpenRouter's flat ``:online``
per-request web-search fee. Two things have to hold, and a test that only
checked the happy path would catch neither:

* the fee's CARDINALITY — once per SEARCHING call, not once per run, not once
  per priced call (AGENTS.md rule 6b: accounting code asserts how many);
* the fee's TRIGGER — the model id actually PUT ON THE WIRE, not
  ``ModelSlot.search``. Those two agree in the clean case and disagree exactly
  when ``:online`` is rejected and the BARE retry serves the answer. Only the
  bare call was billed, so an intent-keyed implementation over-charges that
  slot on a receipt the UI labels ``measured``.

Mutation 03 IS that wrong implementation, written out, so it can never ship
looking green. Mutations 04-07 are the cardinality defeats.

Applies each mutation by hand, runs the tests, restores the file from a `cp`
copy, and verifies with `diff -q` that the tree came back byte-identical.
Never uses `git checkout` (it would discard uncommitted work).

    uv run python scripts/proofs/search_fee_measured_mutations.py

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
    "providers": ROOT / "src" / "product_app" / "providers.py",
    "orchestration": ROOT / "src" / "product_app" / "query_run_orchestration.py",
}
TESTS = [
    "tests/unit/test_search_fee_wire_truth.py",
    "tests/unit/test_actual_cost_source.py",
]

#: (label, file key, exact text to find, replacement). Each anchor MUST be
#: unique in the file — a non-unique anchor silently mutates a namesake
#: elsewhere and reports a false SURVIVED, which is a trap this repo has
#: already paid for. `make format` reflows Python and can invalidate these
#: anchors, so re-run this proof AFTER formatting.
MUTATIONS: list[tuple[str, str, str, str]] = [
    (
        "01 the wire stamp is dropped entirely",
        "providers",
        '            searched=model_id.endswith(":online"),',
        "            searched=False,",
    ),
    (
        "02 every call claims it searched",
        "providers",
        '            searched=model_id.endswith(":online"),',
        "            searched=True,",
    ),
    (
        "03 the fee keys on the INTENT, not the wire outcome",
        "providers",
        "                searched=live_response.searched,",
        "                searched=model_slot.search,",
    ),
    (
        "04 the measured fee term is deleted",
        "orchestration",
        "            if answer.searched:\n                slot_cost += search_request_fee",
        "            if False:\n                slot_cost += search_request_fee",
    ),
    (
        "05 the fee is charged once per RUN, not per searching call",
        "orchestration",
        "            if answer.searched:\n                slot_cost += search_request_fee",
        "            if answer.searched and answer.slot_number == 1:\n"
        "                slot_cost += search_request_fee",
    ),
    (
        "06 the fee is charged on every measurable slot",
        "orchestration",
        "            if answer.searched:\n                slot_cost += search_request_fee",
        "            if True:\n                slot_cost += search_request_fee",
    ),
    # 08-11 are the defeats adversarial review demonstrated against earlier
    # versions of this change. 04 above deletes the term outright; 05-07 are the
    # cardinality defeats. 08-10 are the three defeats adversarial review
    # demonstrated against the
    # FIRST version of this change: each one is a wrong implementation of the
    # feature that kept the whole suite, and this very proof, green. They are
    # replayed here so they can never pass silently again. The tests that kill
    # them are, in order: the fee-DELTA test, the colon-bearing-id test, and
    # the unequal source counts in the cardinality fixture.
    (
        "08 the fee is a hardcoded literal, not the setting",
        "orchestration",
        "        search_request_fee = Decimal(str(settings.cost_web_search_request_fee_usd))",
        '        search_request_fee = Decimal("0.01")',
    ),
    (
        "09 any colon counts as a search suffix",
        "providers",
        '            searched=model_id.endswith(":online"),',
        '            searched=":" in model_id,',
    ),
    (
        "10 the fee scales with the citation count",
        "orchestration",
        "                slot_cost += search_request_fee",
        "                slot_cost += search_request_fee * len(answer.sources)",
    ),
    (
        # ROUND 2. Every fee value the tests used was a whole number of cents,
        # so rounding the fee to cents satisfied all of them AND charged
        # nothing at the real $0.007. Killed by the sub-cent rows in the
        # cardinality test and the sub-cent deltas in the SETTING test.
        "11 the fee is truncated to whole cents (invisible at $0.007)",
        "orchestration",
        "        search_request_fee = Decimal(str(settings.cost_web_search_request_fee_usd))",
        "        search_request_fee = (\n"
        "            Decimal(int(settings.cost_web_search_request_fee_usd * 100)) / 100\n"
        "        )",
    ),
    (
        "07 the fee leaks onto the synthesis calls too",
        "orchestration",
        "                    prompt_tokens=synth_usage.prompt_tokens,\n"
        "                    completion_tokens=synth_usage.completion_tokens,\n"
        "                )",
        "                    prompt_tokens=synth_usage.prompt_tokens,\n"
        "                    completion_tokens=synth_usage.completion_tokens,\n"
        "                )\n"
        "                + search_request_fee",
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
                print(f"  {label:56} ANCHOR NOT UNIQUE (x{count}) — proof invalid")
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
            print(f"  {label:56} {status} restore={restore} | {tail[-1] if tail else ''}")
            if not killed or clean.returncode != 0:
                failures += 1

    print(f"\n{len(MUTATIONS) - failures} killed / {len(MUTATIONS)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
