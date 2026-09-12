"""Re-runnable mutation proof for the #105 step-1 billing verdict (ADR-0112).

`providers.py` already computed the distinction issue #105 turns on — `None`
means "refused before inference, provably not billed", `_DISPATCH_UNMEASURED`
means "dispatched, may already have been charged" — and the initial-answer path
flattened both into a single `None` one frame above the slot record. This change
carries the verdict through to `InitialModelAnswer.billing_class`.

It changes NO money. Nothing prices anything from the field. What has to hold is
that the verdict is the RIGHT one in both directions, because a field that
always says "possibly billed" is exactly as uninformative as the flattening it
replaced — safe, and useless for the decision ADR-0012 deferred.

Mutation 04 is the one that matters most: a 200 carrying the provider's own
`usage` with an invisible completion is the single failure mode where money
provably moved and the slot still produced nothing. Reporting it `not_billed`
would be worse than the flattening, because it asserts a falsehood rather than
declining to answer.

Applies each mutation by hand, runs the tests, restores the file from a `cp`
copy, and verifies with `diff -q` that the tree came back byte-identical.
Never uses `git checkout` (it would discard uncommitted work).

    uv run python scripts/proofs/failed_slot_billing_verdict_mutations.py

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
    "tests/unit/test_failed_slot_billing_verdict.py",
    "tests/unit/test_provider_stubs.py",
    "tests/unit/test_provider_billing_classification.py",
    "tests/integration/test_invisible_completion_billing_honesty.py",
    # Drives the REAL deadline path with live execution off and an empty key,
    # which is the only place the call site's verdict decision is observable.
    "tests/integration/test_run_deadline.py",
]

#: (label, file key, exact text to find, replacement). Each anchor MUST be
#: unique in the file — a non-unique anchor silently mutates a namesake
#: elsewhere and reports a false SURVIVED. `make format` reflows Python, so
#: re-run this proof AFTER formatting.
MUTATIONS: list[tuple[str, str, str, str]] = [
    (
        "01 the verdict is flattened back to None at the boundary",
        "providers",
        "        if isinstance(result, _DispatchedUnmeasured):\n"
        "            return _DISPATCH_UNMEASURED",
        "        if isinstance(result, _DispatchedUnmeasured):\n            return None",
    ),
    (
        "02 every failed slot claims it was possibly billed",
        "providers",
        '        live_billing_class: Literal["not_billed", "possibly_billed"] = BILLING_NOT_BILLED',
        '        live_billing_class: Literal["not_billed", "possibly_billed"] = '
        "BILLING_POSSIBLY_BILLED",
    ),
    (
        "03 a dispatched failure is recorded as provably unbilled",
        "providers",
        "                live_billing_class = BILLING_POSSIBLY_BILLED\n"
        "                # Narrowed by EXCLUSION",
        "                live_billing_class = BILLING_NOT_BILLED\n"
        "                # Narrowed by EXCLUSION",
    ),
    (
        "04 an invisible completion that WAS billed reports not-billed",
        "providers",
        "            return _DISPATCH_UNMEASURED\n        return result",
        "            return None\n        return result",
    ),
    (
        "05 the verdict never reaches the slot record",
        "providers",
        "            provider_notice=NOTICE_PROVIDER_UNAVAILABLE,\n"
        "            billing_class=billing_class,",
        "            provider_notice=NOTICE_PROVIDER_UNAVAILABLE,",
    ),
    (
        "06 the live-failure path drops the captured verdict",
        "providers",
        "                started_at=started_at,\n"
        "                billing_class=live_billing_class,\n"
        "            )\n\n        # No live response, or live response returned no usable text.",
        "                started_at=started_at,\n"
        "            )\n\n        # No live response, or live response returned no usable text.",
    ),
    # NOT PINNED, and said here rather than left to be discovered: the
    # CANCELLED call site's verdict has no mutation, because it has no
    # observable surface. A cancelled slot is not recorded in
    # ``initial_answers`` at all — measured: after the real cancel path runs,
    # no slot carries ``error_code == "CANCELLED"`` there — so nothing can
    # read its verdict. It is set for correctness and symmetry with the
    # deadline path, and it is unpinned. Recorded as debt rather than forced
    # into a test that would assert a state the product does not produce.
    #
    # 09-11 are the defects adversarial review found in the first version.
    # 08/09 are the field-drift footgun the failure constructors' own docstrings
    # warn about: an earlier draft set the verdict only in `_failed_answer`, so a
    # deadline-cut slot whose POST may be in flight recorded the value meaning
    # "not applicable". 11 is the duck-typing trap that narrowing by isinstance
    # walked straight into.
    (
        "09 the deadline verdict stops consulting whether a POST was possible",
        "orchestration",
        "                billing_class=(\n"
        "                    BILLING_POSSIBLY_BILLED\n"
        "                    if provider_execution_service._live_execution_enabled(\n"
        "                        openrouter_key=openrouter_key\n"
        "                    )\n"
        "                    else BILLING_NOT_BILLED\n"
        "                ),",
        "                billing_class=BILLING_POSSIBLY_BILLED,",
    ),
    (
        "10 the dispatched test is inverted so nothing is ever possibly billed",
        "providers",
        "            if live_outcome is not None:\n"
        "                live_billing_class = BILLING_POSSIBLY_BILLED",
        "            if live_outcome is None:\n"
        "                live_billing_class = BILLING_POSSIBLY_BILLED",
    ),
    (
        "11 the success path is narrowed by isinstance (breaks duck-typed doubles)",
        "providers",
        "                if not isinstance(live_outcome, _DispatchedUnmeasured):",
        "                if isinstance(live_outcome, LiveProviderResult):",
    ),
    (
        "07 a completed answer is stamped with a verdict too",
        "providers",
        '    billing_class: Literal["not_billed", "possibly_billed"] | None = None',
        '    billing_class: Literal["not_billed", "possibly_billed"] | None = "possibly_billed"',
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
                print(f"  {label:60} ANCHOR NOT UNIQUE (x{count}) — proof invalid")
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
            print(f"  {label:60} {status} restore={restore} | {tail[-1] if tail else ''}")
            if not killed or clean.returncode != 0:
                failures += 1

    print(f"\n{len(MUTATIONS) - failures} killed / {len(MUTATIONS)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
