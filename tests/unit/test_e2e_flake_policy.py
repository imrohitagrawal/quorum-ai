"""RB-4 — the e2e FLAKE POLICY, pinned as executable text assertions.

A retry is not a fix. Playwright's ``retries`` silently converts a real,
intermittent regression into a green check: the gate keeps reporting "pass"
while the contract it guards is only true two times in three. This repo's
policy is therefore:

* **default retries = 0.** Masking is opt-in (``PW_RETRIES``), never ambient,
  and never on in a blocking lane.
* **measure, don't paper over.** ``flake-scan.yml`` runs the timing-sensitive
  specs ``--repeat-each`` N>=10 on a schedule so a rate is a MEASURED number
  with a run id, not an impression.
* **>0/10 failures => QUARANTINE**, with a ledger row and an owner. Never a
  retry, never a widened timeout.
* **no cross-engine screenshots.** A ``toHaveScreenshot`` baseline is seeded in
  one container on one engine; running it on firefox/webkit compares
  like-for-unlike and can only ever produce noise. RB-6's cross-engine job
  must therefore never touch a visual spec (D-18).

These assert on the workflow/config TEXT rather than on prose in a doc, so a
regression in the machinery reds here — the same pattern as
``tests/unit/test_makefile_gate_integrity.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PW_CONFIG = REPO_ROOT / "e2e" / "playwright.config.ts"
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
E2E_WORKFLOW = WORKFLOW_DIR / "e2e.yml"
FLAKE_SCAN_WORKFLOW = WORKFLOW_DIR / "flake-scan.yml"
CSP_SMOKE_WORKFLOW = WORKFLOW_DIR / "csp-smoke.yml"

# Specs that compare pixels against a committed baseline. A baseline is
# environment- AND engine-specific, so these may only ever run on the engine
# that seeded them (chromium, in CI's own container).
VISUAL_SPECS = (
    "visual-snapshots.spec.ts",
    "trust-score-visual.spec.ts",
)

#: The directory both visual specs live in. Passing it as a bare path argument
#: runs them without naming them.
VISUAL_SPEC_DIR = "tests/invariants"


def _read(path: Path) -> str:
    assert path.exists(), f"expected {path.relative_to(REPO_ROOT)} to exist"
    return path.read_text(encoding="utf-8")


def _playwright_invocations(text: str) -> list[str]:
    """Every ``npx playwright test ...`` command in a workflow, as one string each.

    Workflow ``run:`` blocks use YAML folded scalars (``>-``), so a single
    invocation spans many lines and cannot be read one line at a time.

    The slice must END accurately or the check inverts: if one command's text
    bleeds into the next step, a *neighbouring* ``--retries=0`` gets attributed
    to an invocation that does not carry it, and the gate passes on a masked
    lane. So terminate at whichever comes first — the next list item at step
    indentation (any key, not just ``name``/``uses``: a step may lead with
    ``- run:``) or the next invocation itself.
    """
    commands: list[str] = []
    starts = [m.start() for m in re.finditer(r"npx playwright test\b", text)]
    for index, start in enumerate(starts):
        rest = text[start:]
        stops = [len(rest)]
        next_step = re.search(r"\n\s{0,8}-\s+[A-Za-z_-]+:", rest)
        if next_step:
            stops.append(next_step.start())
        if index + 1 < len(starts):
            stops.append(starts[index + 1] - start)
        commands.append(rest[: min(stops)])
    return commands


def _strip_ts_comments(text: str) -> str:
    """Drop ``//`` and ``/* */`` comments so prose about a setting is not read
    as the setting. Crude (it would also cut a comment marker inside a string
    literal), which is fine here: the configs under test contain no such
    string, and erring toward stripping can only remove candidate matches from
    a gate that fails closed on the ones that remain."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def _spec_arguments(command: str) -> list[str]:
    """The positional path arguments of a playwright invocation.

    Everything that is not the command itself and not a ``--flag``: either a
    spec file or a directory to walk. YAML folded scalars put each on its own
    line, but tokenising on whitespace handles both shapes.
    """
    tokens = command.split()
    return [
        token
        for token in tokens[3:]  # skip `npx playwright test`
        if not token.startswith("-") and ("/" in token or token.endswith(".spec.ts"))
    ]


def test_playwright_default_retries_is_zero() -> None:
    """The config must default to ZERO retries — CI included.

    ``retries: process.env.CI ? 2 : 0`` is the anti-pattern: it turns on
    masking exactly where it does the most damage (the blocking lane) and
    nowhere a developer would notice it locally.
    """
    text = _read(PW_CONFIG)
    # EVERY `retries:` in the file, wherever it appears. A per-project override
    # (`projects: [{ name: "chromium", retries: process.env.CI ? 2 : 0 }]`)
    # silently beats the top-level default — Playwright resolves retries as
    # takeFirst(CLI, project, config) — so checking only the first, or only
    # line-leading, occurrence would bless exactly the regression this test
    # exists to stop. The value runs to the end of the line or to the `,`/`}`
    # that closes it, so an inline object literal is matched too.
    #
    # Comments are stripped first. This file now carries several comments that
    # discuss `retries:` and quote the banned expression to explain why it is
    # banned; matching those would red the gate over its own documentation.
    expressions = re.findall(r"\bretries:\s*([^,}\n]+)", _strip_ts_comments(text))
    assert expressions, "playwright.config.ts must declare an explicit `retries:`"
    for expression in expressions:
        assert "process.env.CI" not in expression, (
            "retries must not be conditioned on CI — that masks flakes precisely "
            f"in the blocking lane. Found: retries: {expression}"
        )
        assert "PW_RETRIES" in expression, (
            "every retries setting must be opt-in via the PW_RETRIES env var. "
            f"Found: retries: {expression}"
        )
        assert re.search(r"\?\?\s*0", expression), (
            f"the PW_RETRIES default must be 0. Found: retries: {expression}"
        )


def test_every_playwright_invocation_in_e2e_yml_passes_retries_zero() -> None:
    """Belt and braces: the blocking lane pins ``--retries=0`` at the call site.

    The config default could be changed by a later edit; the workflow flag is
    the gate's own declaration that it will not accept a masked pass.
    """
    commands = _playwright_invocations(_read(E2E_WORKFLOW))
    assert commands, "e2e.yml must invoke playwright at least once"
    for command in commands:
        assert "--retries=0" in command, (
            "every playwright invocation in the BLOCKING e2e lane must pass "
            f"--retries=0. Offending invocation:\n{command.strip()[:400]}"
        )


def test_csp_smoke_workflow_pins_retries_zero() -> None:
    """RB-6: the advisory cross-engine CSP smoke lives in its OWN workflow, which
    escapes the e2e.yml-only ``--retries=0`` pin above — so pin it here too.

    A retry would silently convert an intermittent cross-engine CSP break into a
    green check, exactly the masking RB-4 forbids. Advisory (non-gating) does not
    exempt it: an advisory signal that is quietly wrong is worse than none.
    """
    text = _read(CSP_SMOKE_WORKFLOW)
    commands = _playwright_invocations(text)
    assert commands, "csp-smoke.yml must invoke playwright at least once"
    for command in commands:
        assert "--retries=0" in command, (
            "every playwright invocation in the advisory CSP-smoke lane must pass "
            "--retries=0 (no masking, even advisory). Offending invocation:\n"
            f"{command.strip()[:400]}"
        )
    # Advisory means NOT masked: the job must not hide failures behind
    # continue-on-error (that is how a broken cross-engine signal goes unnoticed).
    # It is advisory by not being a required status check, not by swallowing reds.
    # Match the YAML KEY (`continue-on-error:`), not the bare word — the workflow
    # comment explains *why it is banned* and must not trip its own gate.
    assert not re.search(r"^\s*continue-on-error\s*:", text, re.MULTILINE), (
        "csp-smoke.yml must fail honestly; it is advisory by not being a required "
        "check, not by continue-on-error masking (RB-4 policy)."
    )


def test_a_flake_scan_workflow_exists_with_repeat_each_at_least_ten() -> None:
    """The measurement half: a scheduled N>=10 repeat run over timing-sensitive specs.

    Without this the quarantine policy has no input — "flaky" stays an
    impression. ``--repeat-each`` is Playwright's built-in vehicle; a bash loop
    would lose the per-repeat reporting.
    """
    text = _read(FLAKE_SCAN_WORKFLOW)
    repeats = [int(n) for n in re.findall(r"--repeat-each=(\d+)", text)]
    assert repeats, "flake-scan.yml must run playwright with --repeat-each=N"
    assert min(repeats) >= 10, f"the flake scan must repeat each spec at least 10x; found {repeats}"
    assert "schedule:" in text and "cron:" in text, (
        "flake-scan.yml must be scheduled so the rate is sampled over time"
    )
    assert "workflow_dispatch:" in text, (
        "flake-scan.yml must be dispatchable on demand — a quarantine decision "
        "cannot wait for the next cron tick"
    )
    for command in _playwright_invocations(text):
        assert "--retries=0" in command, (
            "the flake scan measures the UNMASKED rate; --retries=0 is "
            f"mandatory. Offending invocation:\n{command.strip()[:400]}"
        )


def test_the_flake_scan_persists_its_junit_report_to_a_file() -> None:
    """A scan whose report goes to stdout measures nothing anyone can read.

    Passing ``--reporter=junit`` on the command line REPLACES the reporter list
    from ``playwright.config.ts`` outright, and the bare junit reporter then
    writes its XML to **stdout** — ``results.xml`` is never created. Verified
    empirically against Playwright 1.61.1.

    That failure mode is silent in the worst way: the summary step would report
    every leg as ``UNMEASURED`` and the upload step would fail on
    ``if-no-files-found: error``, so the nightly job would produce a red badge
    and zero data while looking like it had run. ``PLAYWRIGHT_JUNIT_OUTPUT_NAME``
    is what actually routes the report to a file.
    """
    text = _read(FLAKE_SCAN_WORKFLOW)
    for command in _playwright_invocations(text):
        if "--reporter=junit" not in command:
            continue
        assert "PLAYWRIGHT_JUNIT_OUTPUT_NAME" in text, (
            "--reporter=junit overrides the config reporter and writes to STDOUT; "
            "set PLAYWRIGHT_JUNIT_OUTPUT_NAME so the report lands in a file the "
            "summary and upload steps can actually read"
        )
    # And whatever the report is called, the steps that consume it must agree.
    output_name = re.search(r"PLAYWRIGHT_JUNIT_OUTPUT_NAME:\s*(\S+)", text)
    assert output_name, "the flake scan must name its junit output file"
    report = output_name.group(1).strip("\"'")
    assert f"path: e2e/{report}" in text, (
        f"the upload step must upload the report the run step produces ({report})"
    )
    assert f'Path("{report}")' in text, (
        f"the summary step must parse the report the run step produces ({report})"
    )


@pytest.mark.parametrize("visual_spec", VISUAL_SPECS)
def test_no_workflow_runs_a_visual_spec_on_a_non_chromium_engine(
    visual_spec: str,
) -> None:
    """D-18: no ``toHaveScreenshot`` spec may run on a non-chromium engine.

    The committed ``*-linux.png`` baselines were seeded by chromium in CI's own
    container. Firefox and WebKit rasterise text differently by design, so a
    cross-engine compare is guaranteed noise — a permanently red or a
    permanently-ignored gate, and both are worse than no gate at all.

    Two deliberate choices make this pin actually hold when RB-6 lands:

    * **Every workflow file is scanned**, not just ``e2e.yml``. RB-6's
      ``csp-cross-engine`` job may well arrive in a file of its own, and a
      guard that only reads one file would wave it straight through.
    * **It fails CLOSED.** The engine is only treated as chromium when the flag
      says so *literally*. A templated ``--project=${{ matrix.engine }}`` is
      unresolvable from static text, so it counts as non-chromium — which is
      the right default, because that expression is exactly how a cross-engine
      matrix job is written.
    """
    for workflow in sorted(WORKFLOW_DIR.glob("*.yml")):
        for command in _playwright_invocations(_read(workflow)):
            projects = set(re.findall(r"--project=(\S+)", command))
            # No --project at all means every configured project runs, and the
            # config declares firefox, webkit and mobile alongside chromium.
            chromium_only = bool(projects) and projects <= {"chromium"}
            if chromium_only:
                continue
            arguments = _spec_arguments(command)
            # No path argument at all is the widest invocation there is: it
            # walks the whole `testDir`, visual specs included. Treating an
            # empty argument list as "nothing to check" would let the single
            # most dangerous command shape through untested.
            assert arguments, (
                f"{workflow.name} runs playwright with no path argument on "
                f"projects={projects or '<all>'}, which walks the entire test "
                f"directory — including {visual_spec}, whose baselines are "
                f"chromium-only:\n{command.strip()[:400]}"
            )
            for argument in arguments:
                # Naming the spec is only the obvious way to run it. A DIRECTORY
                # argument (`tests/invariants/`, the form seed-visual-baselines.yml
                # uses) sweeps the visual specs up without ever mentioning them.
                #
                # Matched per ARGUMENT, not as a substring of the whole command:
                # a sibling spec in the same directory — RB-6's
                # `tests/invariants/csp-smoke.spec.ts`, which is *meant* to run
                # cross-engine — shares the prefix but is not a visual spec, and
                # a prefix match would block exactly the job this repo wants.
                sweeps_directory = not argument.endswith(".spec.ts") and (
                    f"{VISUAL_SPEC_DIR}/".startswith(argument.rstrip("/") + "/")
                    or argument.rstrip("/") == VISUAL_SPEC_DIR
                )
                names_the_spec = argument.endswith(visual_spec)
                assert not (sweeps_directory or names_the_spec), (
                    f"{visual_spec} compares pixels against a chromium-seeded "
                    f"baseline and must never run on another engine, but "
                    f"{workflow.name} reaches it via the argument `{argument}` "
                    f"with projects={projects or '<all>'}:\n{command.strip()[:400]}"
                )
