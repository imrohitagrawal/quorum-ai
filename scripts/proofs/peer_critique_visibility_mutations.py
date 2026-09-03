"""Re-runnable mutation proof for the peer-critique visibility change (ADR-0097).

Exists because a commit body once claimed "16 killed / 16" without listing the
mutations, and a reviewer could not re-derive the number — they guessed a
different formulation of one mutation and got a different failure count. A
mutation count nobody else can re-run is an unfalsifiable number.

Applies each mutation by hand, runs the tests, restores the file from a `cp`
copy, and verifies with `diff -q` that the tree came back byte-identical.
Never uses `git checkout` (it would discard uncommitted work).

    uv run python scripts/proofs/peer_critique_visibility_mutations.py

Exit 0 only when every mutation is KILLED and every restore is byte-identical.
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
    "post": ROOT / "scripts" / "live_posture_check.py",
    "main": ROOT / "src" / "product_app" / "main.py",
    "deb": ROOT / "src" / "product_app" / "debate.py",
}
TESTS = [
    "tests/unit/test_posture_reports_peer_critique.py",
    "tests/integration/test_peer_critique_is_observable.py",
    "tests/unit/test_live_posture_check.py",
]

#: (label, file key, exact text to find, replacement). Each anchor MUST be
#: unique in the file — a non-unique anchor silently mutates a namesake
#: elsewhere and reports a false SURVIVED, which is how an earlier run of this
#: same proof reported 3 phantom survivors.
MUTATIONS: list[tuple[str, str, str, str]] = [
    (
        "01 main() stops probing",
        "post",
        "    peer_states = {url: fetch_peer_critique_enabled(url) for url in status_urls}\n",
        "    peer_states = {}\n",
    ),
    (
        "02 main() passes None onward",
        "post",
        "        peer_states=peer_states,\n",
        "        peer_states=None,\n",
    ),
    (
        "03 /status drops the key",
        "main",
        '        "peer_critique_enabled": settings.peer_critique_enabled,\n',
        "",
    ),
    (
        "04 /status hardcodes True",
        "main",
        '        "peer_critique_enabled": settings.peer_critique_enabled,\n',
        '        "peer_critique_enabled": True,\n',
    ),
    (
        "05 /status reads the judge",
        "main",
        '        "peer_critique_enabled": settings.peer_critique_enabled,\n',
        '        "peer_critique_enabled": judge_configured(),\n',
    ),
    (
        "06 fetcher accepts truthy",
        "post",
        '    value = payload.get("peer_critique_enabled")\n'
        "    if isinstance(value, bool):\n        return value\n",
        '    value = payload.get("peer_critique_enabled")\n'
        "    if value is not None:\n        return bool(value)\n",
    ),
    (
        "07 unreadable reported as false",
        "post",
        '        return f"peer_critique_enabled was unreadable on all {probed} /status host(s)."\n',
        '        return "peer_critique_enabled=false."\n',
    ),
    (
        "08 unprobed reported as false",
        "post",
        '        return "peer_critique_enabled was not probed."\n',
        '        return "peer_critique_enabled=false."\n',
    ),
    (
        "09 flag sense flipped in the gate",
        "deb",
        "        if not settings.peer_critique_enabled:\n            return None\n",
        "        if settings.peer_critique_enabled:\n            return None\n",
    ),
    (
        "10 wrapper drops the note (original bug)",
        "post",
        '    return replace(result, detail=f"{detail}{separator}{note}")',
        "    return result",
    ),
    (
        "11 flag-off caveat removed",
        "post",
        '    elif state == "true" and not live:',
        '    elif state == "true" and not True:',
    ),
    (
        "12 dispatch promised unconditionally",
        "post",
        '            " On a run that has eligible critics the debate leg would dispatch "',
        '            " The debate leg therefore dispatches "',
    ),
    (
        "13 wrapper stops forwarding peer_states",
        "post",
        "        {} if peer_states is None else peer_states,",
        "        {},",
    ),
    (
        "14 live verdict always True",
        "post",
        "    readable = {url: s for url, s in readiness_states.items() if s is not None}\n"
        "    if any(",
        "    readable = {url: s for url, s in readiness_states.items() if s is not None}\n"
        "    if True or any(",
    ),
    (
        "15 unread becomes off",
        "post",
        "    if not readable:\n        return None\n",
        "    if not readable:\n        return False\n",
    ),
    (
        "16 unknown-vocabulary guard dropped",
        "post",
        "    if any(s not in KNOWN_READINESS_STATES for s in readable.values()):",
        "    if False:",
    ),
    (
        "17 partial-view guard dropped",
        "post",
        "    if len(readable) != len(readiness_states):",
        "    if False:",
    ),
    (
        "18 stops failing closed",
        "post",
        "    if any(s != FLAG_OFF_STATE and s in KNOWN_READINESS_STATES"
        " for s in readable.values()):",
        "    if any(s != FLAG_OFF_STATE and s not in KNOWN_READINESS_STATES"
        " for s in readable.values()):",
    ),
    (
        "19 run-on join restored",
        "post",
        '    separator = " " if detail.endswith((".", "!", "?")) else ". "',
        '    separator = " "',
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
                print(f"  {label:44} ANCHOR NOT UNIQUE (x{count}) — proof invalid")
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
            print(f"  {label:44} {status} restore={restore} | {tail[-1] if tail else ''}")
            if not killed or clean.returncode != 0:
                failures += 1

    print(f"\n{len(MUTATIONS) - failures} killed / {len(MUTATIONS)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
