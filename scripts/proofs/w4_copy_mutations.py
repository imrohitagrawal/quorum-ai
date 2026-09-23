"""Re-runnable mutation proof for W4's third pull request (CHG-011, ADR-0120).

Every user-visible sentence this change adds or rewrites has a test that
turns red when the sentence, the count branch or the shape branch is broken.
This script proves that by applying each mutation, running the tests,
restoring the file from a `cp` copy and checking with `cmp` that the tree came
back byte-identical. Never `git checkout` (it would discard uncommitted work).

    uv run python scripts/proofs/w4_copy_mutations.py          # pytest-killed set
    uv run python scripts/proofs/w4_copy_mutations.py --e2e    # plus the browser-only set

The `--e2e` set covers the wiring the unit harness cannot see (the render call,
the attribute write, the handoff message). For each of those the script starts
its own server, confirms with `curl` that the MUTATED bytes are what it serves
(a reused server serving pre-mutation files is a measured false-green), runs
the two specs exactly as CI does, and stops the server.

Exit 0 only when every mutation is KILLED and every restore is byte-identical.
A kill count against a RED baseline proves nothing, so the baseline is run
first and a red one aborts with exit 2.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
FILES = {
    "js": ROOT / "src" / "product_app" / "static" / "app.js",
    "main": ROOT / "src" / "product_app" / "main.py",
    "html": ROOT / "src" / "product_app" / "templates" / "workspace.html",
}
TESTS = [
    "tests/unit/test_w4_copy_outside_run_path.py",
    "tests/unit/test_ui_honesty.py",
]
SPECS = [
    "tests/invariants/panel-size.spec.ts",
    "tests/invariants/landing-cta-reachable.spec.ts",
]

AVAILABILITY = (
    '      "Peer critique, where each model critiques the others, is available and off on '
    'this deployment."'
)
ISLAND_KEY = (
    '        "peer_critique_in_effect": _peer_critique_in_effect(settings),\n    }\n'
    "    live_readiness_json"
)
ISLAND_FLAG_ALONE = (
    '        "peer_critique_in_effect": settings.peer_critique_enabled,\n    }\n'
    "    live_readiness_json"
)
SUBLINE_P = (
    '              <p class="landing-note landing-note-panel">Your panel, your size: four '
    "models by default, three or two when that is all you need.</p>\n"
)
DEBATE_P = (
    '              <p class="landing-note">Two rounds of debate, by the panel itself or by a '
    "moderator model, then one sourced synthesis.</p>\n"
)
PEER_READ = (
    '    const peer = Boolean(seed && typeof seed === "object" && '
    "seed.peer_critique_in_effect === true);"
)
PEER_READ_INVERTED = (
    '    const peer = !(seed && typeof seed === "object" && seed.peer_critique_in_effect === true);'
)
CARD_SHAPE = "    const cardPeerShape = describePeerCritique(cardRounds) !== null;"

#: (label, file key, exact text to find, replacement). Each anchor MUST be
#: unique in its file — a non-unique anchor silently mutates a namesake
#: elsewhere and reports a false SURVIVED; the script refuses a non-unique one.
MUTATIONS: list[tuple[str, str, str, str]] = [
    (
        "01 composerShapeCopy ignores the shape (always moderator)",
        "js",
        "    if (peerInEffect) {\n      if (n === 2) {",
        "    if (false) {\n      if (n === 2) {",
    ),
    (
        "02 composerShapeCopy ignores the count under the moderator shape",
        "js",
        '    const answers = n === 2 ? "both answers" : `all ${word} answers`;',
        '    const answers = "all four answers";',
    ),
    (
        "03 composerShapeCopy loses the two-model peer sentence",
        "js",
        '      if (n === 2) {\n        return "This run: both models critique each other',
        '      if (n === 5) {\n        return "This run: both models critique each other',
    ),
    (
        "04 composerShapeCopy drops the availability sentence",
        "js",
        AVAILABILITY,
        '      ""',
    ),
    (
        "05 modelCardInfoText ignores the shape",
        "js",
        "    if (peerShape) {\n      const others",
        "    if (false) {\n      const others",
    ),
    (
        "06 modelCardInfoText ignores the count",
        "js",
        '    const all = n === 2 ? "both" : `all ${words[n] || String(n)}`;',
        '    const all = "all four";',
    ),
    (
        "07 landingHandoffCopy ignores the count",
        "js",
        '    const word = words[n] || String(n);\n    return kind === "estimate"',
        '    const word = "four";\n    return kind === "estimate"',
    ),
    (
        "08 the readiness island drops the shape key",
        "main",
        ISLAND_KEY,
        "    }\n    live_readiness_json",
    ),
    (
        "09 the readiness island reads the flag alone (the #458 falsehood)",
        "main",
        ISLAND_KEY,
        ISLAND_FLAG_ALONE,
    ),
    (
        "10 the landing drops the panel subline (D2)",
        "html",
        SUBLINE_P,
        "",
    ),
    (
        "11 the landing carries the panel subline twice (D2 says once)",
        "html",
        SUBLINE_P,
        SUBLINE_P + SUBLINE_P,
    ),
    (
        "12 the headline becomes the rejected range (D1)",
        "html",
        '<p class="brand-lede">Four AI models, one sourced answer.</p>',
        '<p class="brand-lede">2 to 4 AI models, 1 sourced answer.</p>',
    ),
    (
        "13 the landing drops the capability line (D4)",
        "html",
        DEBATE_P,
        "",
    ),
    (
        "14 the hidden debate placeholder names four again",
        "html",
        "run a query to see the round-level critique of the panel's answers.",
        "run a query to see the moderator's critique of all four answers.",
    ),
]

#: Browser-only: the wiring between the pure functions and the DOM.
E2E_MUTATIONS: list[tuple[str, str, str, str]] = [
    (
        "E1 renderModelInputs no longer renders the shape line",
        "js",
        "    renderPanelShapeLine(modelIds.length);\n",
        "",
    ),
    (
        "E2 the shape line reads the flag's absence as peer",
        "js",
        PEER_READ,
        PEER_READ_INVERTED,
    ),
    (
        "E3 the model-card tooltip is the four-moderator constant again",
        "js",
        '      modelCardInfo.setAttribute("data-info-text", cardInfoText);',
        '      modelCardInfo.setAttribute("data-info-text", modelCardInfoText(4, false));',
    ),
    (
        "E4 the handoff message reads the default panel, not the composer",
        "js",
        "      const message = landingHandoffCopy(kind, getModelIds().length);",
        "      const message = landingHandoffCopy(kind, 4);",
    ),
    (
        "E5 the model-card tooltip ignores the rounds' shape",
        "js",
        CARD_SHAPE,
        "    const cardPeerShape = false;",
    ),
]


def _clear_pycache() -> None:
    for d in (ROOT / "src").rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def _pytest(label: str) -> bool:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run(
        ["uv", "run", "pytest", "-q", "-p", "no:cacheprovider", "--no-cov", *TESTS],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    tail = proc.stdout.strip().splitlines()[-1:] if proc.stdout.strip() else [proc.stderr[-200:]]
    print(f"    pytest for {label}: exit {proc.returncode} — {tail[0] if tail else ''}")
    return proc.returncode == 0


def _serve_and_confirm(
    expect_served: str, file_key: str, expect_absent: str | None = None
) -> subprocess.Popen[bytes]:
    """Start a server on 18085 and confirm the mutated text is what it serves.

    ``expect_absent`` is for a deletion mutation, whose only signature is the
    text that is GONE: a reused server serving pre-mutation files still has it.
    """
    subprocess.run("lsof -ti tcp:18085 | xargs -r kill -9", shell=True, check=False)
    (ROOT / ".data" / "feedback_events.sqlite3").unlink(missing_ok=True)
    env = dict(
        os.environ,
        UV_CACHE_DIR=".uv-cache",
        PYTHONPATH="src",
        SENTRY_DSN="",
        SESSION_RATE_LIMIT_PER_MINUTE="600",
        SESSION_MINT_CAP_OVERRIDE="600",
    )
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "product_app.main:app", "--host", "127.0.0.1", "--port", "18085"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    url = {"js": "http://127.0.0.1:18085/static/app.js", "html": "http://127.0.0.1:18085/ui"}[
        file_key
    ]
    for _ in range(60):
        try:
            body = urllib.request.urlopen(url, timeout=2).read().decode("utf-8")
            break
        except Exception:  # noqa: BLE001 — not up yet
            time.sleep(1)
    else:
        raise SystemExit("server did not come up on 18085")
    if expect_served not in body:
        raise SystemExit(f"the server is NOT serving the mutated bytes ({expect_served[:40]!r})")
    if expect_absent is not None and expect_absent in body:
        raise SystemExit(f"the server still serves pre-mutation bytes ({expect_absent[:40]!r})")
    return proc


def _playwright(label: str) -> bool:
    env = dict(os.environ, SESSION_RATE_LIMIT_PER_MINUTE="600", SESSION_MINT_CAP_OVERRIDE="600")
    proc = subprocess.run(
        ["npx", "playwright", "test", *SPECS, "--project=chromium", "--workers=1", "--retries=0"],
        cwd=ROOT / "e2e",
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    summary = [line for line in proc.stdout.splitlines() if " passed" in line or " failed" in line]
    print(f"    playwright for {label}: exit {proc.returncode} — {' / '.join(summary[-2:])}")
    return proc.returncode == 0


def main(argv: list[str]) -> int:
    run_e2e = "--e2e" in argv
    print("baseline (must be green, or every kill below is meaningless)")
    _clear_pycache()
    if not _pytest("baseline"):
        print("BASELINE IS RED — aborting", file=sys.stderr)
        return 2
    if run_e2e:
        server = _serve_and_confirm("renderPanelShapeLine(modelIds.length);", "js")
        try:
            ok = _playwright("baseline")
        finally:
            os.killpg(os.getpgid(server.pid), signal.SIGKILL)
        if not ok:
            print("E2E BASELINE IS RED — aborting", file=sys.stderr)
            return 2

    failures: list[str] = []
    plan = [(m, False) for m in MUTATIONS] + ([(m, True) for m in E2E_MUTATIONS] if run_e2e else [])
    with tempfile.TemporaryDirectory() as tmp:
        for (label, key, old, new), via_e2e in plan:
            path = FILES[key]
            backup = pathlib.Path(tmp) / path.name
            shutil.copyfile(path, backup)
            text = path.read_text(encoding="utf-8")
            if text.count(old) != 1:
                print(f"  {label}: ANCHOR NOT UNIQUE ({text.count(old)} hits) — refusing")
                failures.append(label)
                continue
            path.write_text(text.replace(old, new), encoding="utf-8")
            _clear_pycache()
            print(f"  {label}")
            try:
                if via_e2e:
                    # The serve check: a replacement's text must be served; a
                    # deletion's signature is the OLD text being gone.
                    if new.strip():
                        server = _serve_and_confirm(new.strip(), key)
                    else:
                        server = _serve_and_confirm(
                            "function renderPanelShapeLine(", key, old.strip()
                        )
                    try:
                        green = _playwright(label)
                    finally:
                        os.killpg(os.getpgid(server.pid), signal.SIGKILL)
                else:
                    green = _pytest(label)
            finally:
                shutil.copyfile(backup, path)
                _clear_pycache()
            cmp = subprocess.run(["cmp", "-s", str(backup), str(path)], check=False)
            same = cmp.returncode == 0
            if not same:
                print(f"    RESTORE FAILED for {path}")
                failures.append(label + " (restore)")
            print(f"    {'SURVIVED' if green else 'KILLED'}")
            if green:
                failures.append(label)
    print()
    if failures:
        print("SURVIVORS / FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"all {len(plan)} mutations KILLED; every restore byte-identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
