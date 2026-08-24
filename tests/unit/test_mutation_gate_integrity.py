"""Guards on the mutation gate's own scoring logic (`MUTMUT_SCOPE_PY`).

`test_makefile_gate_integrity.py` covers gates that go green while running the
*wrong* tests. This module covers the mutation gate going green while running
*nothing at all* — the three fail-open paths found in review:

1. `changed_lines()` read only git's stdout, so a bad/absent base ref (fork PR,
   renamed default branch, transient fetch failure) produced an empty scope and
   the recipe reported "nothing to mutate" and succeeded.
2. `report()` scored `100.0` when zero mutants had metadata, so an absent or
   crashed run looked perfect.
3. The recipe piped `mutmut run` into `tail`, discarding its exit status, and
   never cleaned the gitignored `mutants/` tree, so a crashed run was scored
   against stale metadata from an earlier one.

The scoring code is extracted from the Makefile's `define` block and executed,
so a regression in the real recipe fails here rather than in a prose assertion.
"""

from __future__ import annotations

import ast
import fnmatch
import importlib.util
import json
import os
import re
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, cast

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"

SCOPE_BLOCK = re.compile(r"^define MUTMUT_SCOPE_PY\n(.*?)^endef$", re.DOTALL | re.MULTILINE)


@pytest.fixture(scope="module")
def scope_script(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The Makefile's MUTMUT_SCOPE_PY block, on disk and runnable."""
    match = SCOPE_BLOCK.search(MAKEFILE.read_text(encoding="utf-8"))
    assert match, "MUTMUT_SCOPE_PY define block not found in the Makefile"
    script = tmp_path_factory.mktemp("mutscope") / "mutscope.py"
    script.write_text(match.group(1), encoding="utf-8")
    return script


def _run(
    script: Path, cwd: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the extracted scope script, hermetically w.r.t. the truncation marker.

    ``RUN_WITH_DEADLINE_MARKER`` is CLEARED unless a test sets it, deliberately.
    `make mutation-baseline` exports that variable to everything it runs, and
    this module is collected inside mutmut's own ``./mutants/`` copy under that
    very gate — so an inherited value would leak into every report-mode run
    here. It did: the positive partner of the truncation test below created
    ``build/mutation/truncated`` under its own tmp_path, and the inherited
    RELATIVE path then resolved to that same file, so the run that was supposed
    to be complete read as truncated and the whole gate aborted with
    "failed to collect stats". Found by running the real recipe, not by reading.
    """
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**os.environ, "RUN_WITH_DEADLINE_MARKER": "", **(env or {})},
    )


def _write_meta(cwd: Path, name: str, exit_codes: dict[str, int | None]) -> None:
    meta = cwd / "mutants" / "src" / "product_app" / f"{name}.py.meta"
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(json.dumps({"exit_code_by_key": exit_codes}), encoding="utf-8")


def test_report_fails_when_no_mutants_were_scored(scope_script: Path, tmp_path: Path) -> None:
    """No `mutants/` tree at all means the run did not happen — not a 100%."""
    result = _run(scope_script, tmp_path, "report", "origin/main", "90")
    assert result.returncode != 0, (
        "an absent mutation run scored as a pass; promoting the gate to "
        f"blocking would ship a gate that cannot fail:\n{result.stdout}"
    )
    assert "no mutants were scored" in result.stdout + result.stderr


def test_report_fails_when_every_mutant_is_unrun(scope_script: Path, tmp_path: Path) -> None:
    """Metadata exists but every exit code is null — a crashed/aborted run."""
    _write_meta(tmp_path, "query_runs", {"xǁRunsǁsave__mutmut_1": None})
    result = _run(scope_script, tmp_path, "report", "origin/main", "90")
    assert result.returncode != 0, result.stdout
    assert "no mutants were scored" in result.stdout + result.stderr


def test_an_all_timeout_scope_is_reported_as_unmeasured_not_as_a_crash(
    scope_script: Path, tmp_path: Path
) -> None:
    """Every mutant timed out: real, measured, and NOT "the run did not happen".

    Baseline §5 measured 66/66 mutants of `_persist_terminal_run` timing out
    under mutmut's fork-based runner while the same tests pass in 1.34s
    standalone. Timeouts are excluded from the score by a recorded decision, so
    an all-timeout scope leaves `killed + survived == 0` and lands in the same
    branch as an absent `mutants/` tree. While BOTH advisory switches were on,
    that branch's message never mattered because the failure was swallowed
    whole. `make` now exits honestly, so the message is read by whoever runs the
    gate locally — and a wrong one sends them hunting a crash that never
    happened.

    Turns red if: the `counts["timeout"]` branch is deleted from `report()` —
    the message reverts to "the run did not happen" and the exit becomes 1. Also
    red if the branch keeps its message but re-raises `SystemExit(1)`, which the
    exit-status assertion below is here to catch: asserting only on printed text
    left that mutation green (adversarial review finding).
    """
    _write_meta(tmp_path, "query_runs", {f"x_persist__mutmut_{i}": -24 for i in range(1, 67)})
    result = _run(scope_script, tmp_path, "report", "origin/main", "90")
    output = result.stdout + result.stderr

    assert result.returncode == 0, (
        "an all-timeout scope exited non-zero, so a change to thread-spawning "
        "code is blocked by a tooling artifact rather than by its own tests:\n"
        f"{output}"
    )
    assert "UNMEASURED" in output, (
        "an all-timeout scope must say so in words; it is neither a clean "
        f"score nor a crashed run:\n{output}"
    )
    assert "66" in output, f"the timeout count must be reported, not hidden:\n{output}"
    assert "no mutants were scored" not in output, (
        "an all-timeout run reported itself as a run that never happened — "
        f"that message is false and sends the author after a phantom crash:\n{output}"
    )
    # Positive partner for the two negatives above: prove the crash branch this
    # one is being distinguished FROM still fires, so the assertions are not
    # passing over a report() that prints nothing at all.
    empty = tmp_path / "no-mutants-here"
    empty.mkdir()
    crashed = _run(scope_script, empty, "report", "origin/main", "90")
    assert "no mutants were scored" in crashed.stdout + crashed.stderr


def test_an_all_timeout_scope_never_reports_a_score(scope_script: Path, tmp_path: Path) -> None:
    """The loosening must not become a silent pass that looks measured.

    Turns red if: the bucket map stops excluding timeouts — changing the
    `else "timeout"` fallback to `else "survived"` makes this scope score 0.0%
    and print BELOW THRESHOLD (verified). Zero evidence must never render as a
    number a reader can mistake for a result, in either direction.
    """
    _write_meta(tmp_path, "query_runs", {"a__mutmut_1": -24, "b__mutmut_2": -9})
    result = _run(scope_script, tmp_path, "report", "origin/main", "90")
    output = result.stdout + result.stderr

    assert result.returncode == 0, f"the all-timeout path must not block:\n{output}"
    assert "mutation score" not in output, f"an unmeasured run printed a mutation score:\n{output}"
    assert "BELOW THRESHOLD" not in output, (
        f"an unmeasured run was scored against the threshold:\n{output}"
    )
    # ...and the partner proving the score line exists at all when there IS
    # evidence, so the two negatives above cannot pass over a broken report().
    _write_meta(tmp_path, "other", {"c__mutmut_1": 1, "d__mutmut_2": 0})
    measured = _run(scope_script, tmp_path, "report", "origin/main", "40")
    assert "mutation score" in measured.stdout, measured.stdout + measured.stderr


def test_a_partly_timed_out_scope_is_still_scored_on_what_ran(
    scope_script: Path, tmp_path: Path
) -> None:
    """The timeout branch must trigger ONLY when nothing at all was measured.

    Turns red if: the branch is widened from `killed + survived == 0` to any
    run containing a timeout — which would let one timing-out mutant suppress
    the gate for the whole change.
    """
    _write_meta(
        tmp_path,
        "query_runs",
        {"a__mutmut_1": -24, "b__mutmut_2": 1, "c__mutmut_3": 0},
    )
    result = _run(scope_script, tmp_path, "report", "origin/main", "90")
    output = result.stdout + result.stderr

    assert "UNMEASURED" not in output, (
        f"a scope with real kills and survivors was written off as unmeasured:\n{output}"
    )
    assert "50.0%" in output, f"expected 1 killed / 1 survived = 50%:\n{output}"
    assert result.returncode != 0, f"50% is below the 90 threshold and must still block:\n{output}"


def test_a_function_with_no_covering_test_fails_the_run(scope_script: Path, tmp_path: Path) -> None:
    """`no_tests` must be loud. It is the quietest way to fake a perfect score.

    mutmut records exit code 33 when a mutant has NO covering test, and the
    score's denominator is `killed + survived` — so an uncovered function does
    not score 0%, it scores nothing at all and vanishes. Confirmed on a scratch
    tree, identical source, one added deselection marker:

        before:  7 killed, 4 survived, 0 no-tests →  63.6%  BELOW THRESHOLD
        after:   2 killed, 0 survived, 9 no-tests → 100.0%  pass

    That is the whole evasion: silence a function's tests and its mutants leave
    the measurement rather than failing it. Changed code with no test is
    exactly what this gate exists to catch, so it fails here.

    Turns red if: the `no_tests` check is removed from `report()` — the run
    then exits 0 at a flattering 100%.
    """
    _write_meta(
        tmp_path,
        "evaluation",
        {"a__mutmut_1": 1, "b__mutmut_2": 33, "c__mutmut_3": 33},
    )
    result = _run(scope_script, tmp_path, "report", "origin/main", "80")
    output = result.stdout + result.stderr

    assert result.returncode != 0, (
        "a changed function with no covering test scored 100% and passed — "
        f"the gate measured one mutant and ignored two:\n{output}"
    )
    assert "no-tests" in output.lower() or "no covering test" in output.lower(), (
        f"the failure must name the cause, or nobody can act on it:\n{output}"
    )


def test_an_entirely_untested_function_names_the_real_cause(
    scope_script: Path, tmp_path: Path
) -> None:
    """The shape a REAL run produced, which the mixed case above did not cover.

    Adding one untested function to `src/` gave `0 killed, 0 survived, 0
    timeout, 6 no-tests`. Because `checked == killed + survived`, that is also
    `checked == 0`, so ordering decides the message: the `not checked` branch
    blamed an absent or crashed `mutants/` tree — the same false diagnosis this
    recipe already fixed for timeouts. The author would go hunting a phantom
    crash instead of writing the missing test.

    Found by RUNNING the gate, not by reading it: the mixed case above passes
    under either ordering.

    Turns red if: the `no_tests` check is moved back below `if not checked`.
    """
    _write_meta(tmp_path, "untrusted_text", {f"x_w__mutmut_{i}": 33 for i in range(1, 7)})
    result = _run(scope_script, tmp_path, "report", "origin/main", "80")
    output = result.stdout + result.stderr

    assert result.returncode != 0, f"an entirely untested function passed:\n{output}"
    assert "no covering test" in output.lower(), (
        f"the message must name the missing tests, not a crash:\n{output}"
    )


# #142: the old bucket map was a sign test —
# `{0: "survived", 33: "no_tests", 37: "type_check"}.get(code, "killed" if
# code > 0 else "timeout")` — so ANY positive exit code not in that three-entry
# dict scored as `killed`, and any negative one scored as `timeout`. Checked
# against mutmut's own `status_by_exit_code` map (mutmut/__main__.py), five
# real codes fell through: pytest's NO_TESTS_COLLECTED (5, mutmut's OWN second
# no-tests code alongside 33), pytest's USAGE_ERROR (4), mutmut's other timeout
# codes (24/36/152/255 — this file already covers -24), mutmut's `skipped` (34,
# e.g. `# pragma: no mutate`), and segfault/OOM (-11/-9), which the sign test's
# negative branch silently relabelled as an ordinary fork-runner timeout.


def test_pytest_no_tests_collected_exit_5_is_treated_as_no_tests_not_killed(
    scope_script: Path, tmp_path: Path
) -> None:
    """Exit 5 is pytest's NO_TESTS_COLLECTED — the same meaning as mutmut's own
    exit 33, which report() already treats as `no_tests`. #140's no_tests guard
    only recognized 33, so exit 5 kept the "silence a function's tests" evasion
    open through a second, wider door.

    Turns red if: exit 5 is folded back into the `killed` bucket.
    """
    _write_meta(tmp_path, "evaluation", {"a__mutmut_1": 1, "b__mutmut_2": 5, "c__mutmut_3": 5})
    result = _run(scope_script, tmp_path, "report", "origin/main", "80")
    output = result.stdout + result.stderr

    assert result.returncode != 0, (
        "a mutant with NO_TESTS_COLLECTED (exit 5) was counted as killed "
        f"instead of failing the run:\n{output}"
    )
    assert "no-tests" in output.lower() or "no covering test" in output.lower(), (
        f"the failure must name the cause:\n{output}"
    )


def test_pytest_usage_error_exit_4_is_not_scored_as_killed(
    scope_script: Path, tmp_path: Path
) -> None:
    """Exit 4 is pytest's USAGE_ERROR — a broken invocation, not a kill.

    Turns red if: exit 4 falls through to the `killed` bucket.
    """
    _write_meta(tmp_path, "evaluation", {"a__mutmut_1": 1, "b__mutmut_2": 0, "c__mutmut_3": 4})
    result = _run(scope_script, tmp_path, "report", "origin/main", "80")
    output = result.stdout + result.stderr

    assert "1 killed" in output, (
        "exactly one real kill (exit 1) exists; a usage error (exit 4) must "
        f"not inflate the killed count:\n{output}"
    )
    assert result.returncode != 0, (
        f"a usage error was silently absorbed instead of flagging the run as broken:\n{output}"
    )


def test_mutmut_timeout_codes_beyond_the_pinned_one_are_excluded_not_killed(
    scope_script: Path, tmp_path: Path
) -> None:
    """mutmut's own map marks 24/36/152/255 as timeout (SIGXCPU family), not
    just the -24 the rest of this file already covers.

    Turns red if: 36, 152, or 255 fall through to `killed`.
    """
    _write_meta(
        tmp_path,
        "evaluation",
        {
            "a__mutmut_1": 1,
            "b__mutmut_2": 0,
            "c__mutmut_3": 36,
            "d__mutmut_4": 152,
            "e__mutmut_5": 255,
        },
    )
    result = _run(scope_script, tmp_path, "report", "origin/main", "80")
    output = result.stdout + result.stderr

    assert "1 killed" in output, (
        f"exactly one real kill exists; timeout codes 36/152/255 must not inflate it:\n{output}"
    )
    assert "3 timeout" in output, f"all three timeout codes must be counted as timeout:\n{output}"


def test_mutmut_skipped_exit_34_is_not_scored_as_killed(scope_script: Path, tmp_path: Path) -> None:
    """Exit 34 means mutmut skipped the mutant (e.g. `# pragma: no mutate`) —
    deliberate, unlike an uncovered function, so it must not inflate `killed`
    and must not fail the run the way `no_tests` does.

    Turns red if: exit 34 falls through to `killed`.
    """
    _write_meta(tmp_path, "evaluation", {"a__mutmut_1": 1, "c__mutmut_3": 34})
    result = _run(scope_script, tmp_path, "report", "origin/main", "80")
    output = result.stdout + result.stderr

    assert "1 killed" in output, f"a skipped mutant (exit 34) must not count as killed:\n{output}"
    assert result.returncode == 0, (
        f"a deliberate skip must not fail the run the way an uncovered function does:\n{output}"
    )


def test_an_unrecognized_exit_code_is_not_scored_as_killed(
    scope_script: Path, tmp_path: Path
) -> None:
    """The whole point of #142: mirror mutmut's own exit-code map instead of a
    sign test, so a code NOBODY has enumerated yet still fails closed instead
    of defaulting to `killed` just because it happens to be positive.

    Turns red if: the bucket lookup's default falls back to `"killed"` (the
    old sign test's behavior) instead of failing the run.
    """
    _write_meta(tmp_path, "evaluation", {"a__mutmut_1": 1, "c__mutmut_3": 99})
    result = _run(scope_script, tmp_path, "report", "origin/main", "80")
    output = result.stdout + result.stderr

    assert "1 killed" in output, f"an unrecognized exit code must not count as killed:\n{output}"
    assert result.returncode != 0, (
        f"an unrecognized exit code was silently treated as a pass:\n{output}"
    )


def test_type_check_mutants_are_named_in_the_summary_not_silently_dropped(
    scope_script: Path, tmp_path: Path
) -> None:
    """Found by adversarial review of the fix above: exit 37 (`type_check`, a
    mutant caught by mypy rather than a test) was already excluded from the
    score before this file — correctly — but was never counted in the printed
    summary anywhere, unlike every other excluded bucket. A reader could not
    tell 10 type-checked mutants from 0 by looking at the report.

    Turns red if: type_check mutants stop being named in the summary line.
    """
    _write_meta(
        tmp_path,
        "evaluation",
        {"a__mutmut_1": 1, "b__mutmut_2": 37, "c__mutmut_3": 37},
    )
    result = _run(scope_script, tmp_path, "report", "origin/main", "80")
    output = result.stdout + result.stderr

    assert "1 killed" in output, f"type_check mutants must not inflate killed:\n{output}"
    assert "2 type" in output.lower(), (
        f"type_check mutants must be named in the summary, not silently dropped:\n{output}"
    )


def test_an_interrupted_run_exit_2_is_named_not_lumped_into_suspicious(
    scope_script: Path, tmp_path: Path
) -> None:
    """Found by adversarial review of the fix above: mutmut's own map has
    `2: "check was interrupted by user"` (a local Ctrl-C mid-run), which the
    first version of this fix omitted — it fell to the `suspicious` default
    and failed with a generic "broken-run or unrecognized code" message,
    contradicting this fix's own claim to mirror mutmut's real map.

    Turns red if: exit 2 is not named as an interruption, or falls back to
    `killed`/`suspicious` with no distinguishing message.
    """
    _write_meta(tmp_path, "evaluation", {"a__mutmut_1": 1, "b__mutmut_2": 2})
    result = _run(scope_script, tmp_path, "report", "origin/main", "80")
    output = result.stdout + result.stderr

    assert "1 killed" in output, f"an interrupted mutant must not count as killed:\n{output}"
    assert result.returncode != 0, f"an interrupted run must not pass silently:\n{output}"
    assert "interrupt" in output.lower(), (
        "an interrupted run must name itself, not read as a generic "
        f"broken-run/unrecognized code:\n{output}"
    )


def test_segfault_is_reported_as_a_crash_not_folded_into_ordinary_timeout(
    scope_script: Path, tmp_path: Path
) -> None:
    """-11/-9 (segfault/OOM) is a real crash, not the fork-runner timeout
    artifact baseline §5 documents. The old sign test's negative-code branch
    silently relabelled both as the same "timeout" the harness already excuses.

    Turns red if: a segfault is printed under the plain "timeout" label instead
    of being named as a crash.
    """
    _write_meta(tmp_path, "evaluation", {"a__mutmut_1": -9, "b__mutmut_2": -11})
    result = _run(scope_script, tmp_path, "report", "origin/main", "80")
    output = result.stdout + result.stderr

    assert result.returncode == 0, f"an all-crash scope must not block the run:\n{output}"
    assert "crash" in output.lower(), (
        "a segfault must be named as a crash, not silently folded into the "
        f"ordinary timeout label:\n{output}"
    )
    assert "the run did not happen" not in output, (
        "an untested function was reported as a crashed run — false, and it "
        f"sends the author after a mutants/ tree that is fine:\n{output}"
    )


def test_a_clean_run_with_zero_no_tests_still_passes(scope_script: Path, tmp_path: Path) -> None:
    """Positive partner: the new check must not fail an honest run.

    Without this, `test_a_function_with_no_covering_test_fails_the_run` is
    equally satisfied by a report() that fails unconditionally.

    Turns red if: the `no_tests` check is widened to fail runs that have none.
    """
    _write_meta(tmp_path, "evaluation", {"a__mutmut_1": 1, "b__mutmut_2": 1, "c__mutmut_3": 0})
    result = _run(scope_script, tmp_path, "report", "origin/main", "60")
    output = result.stdout + result.stderr

    assert result.returncode == 0, f"an honest 66.7% run was failed:\n{output}"
    assert "0 no-tests" in output, f"expected the no-tests count to be reported:\n{output}"


def test_report_still_scores_a_real_run(scope_script: Path, tmp_path: Path) -> None:
    """The fail-closed guard must not swallow a genuine measurement."""
    _write_meta(
        tmp_path,
        "query_runs",
        {"a__mutmut_1": 1, "b__mutmut_2": 1, "c__mutmut_3": 0},
    )
    result = _run(scope_script, tmp_path, "report", "origin/main", "60")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 killed, 1 survived" in result.stdout
    assert "66.7%" in result.stdout

    below = _run(scope_script, tmp_path, "report", "origin/main", "90")
    assert below.returncode != 0
    assert "BELOW THRESHOLD" in below.stdout


def test_an_empty_scope_writes_zero_bytes(scope_script: Path, tmp_path: Path) -> None:
    """`[ -s scope.txt ]` is a SIZE test, so a bare newline defeats it.

    Found by the first blocking run (#130). `print("\\n".join([]))` emits one
    newline; `-s` is true for any non-zero size; so the recipe's "no changed
    Python functions — nothing to mutate" branch was unreachable and
    `mutmut run` was invoked with ZERO globs — mutate everything — on every
    change that touched no Python under src/. The advisory `-` swallowed the
    resulting failure, so it went unseen for as long as the gate was advisory.

    Turns red if: the `if globs:` guard is removed from `scope()`.
    """
    # Driven against a throwaway repo, NEVER against REPO_ROOT: `changed_lines()`
    # unions the merge-base diff with `git diff -U0 HEAD -- src`, i.e. the
    # WORKING TREE. Pointed at the real repo this test would go red for any
    # developer with an uncommitted edit under src/ — a false failure caused by
    # unrelated work in progress. It would also fail inside mutmut's ./mutants/
    # copy, which has no `.git` at all. A purpose-built repo has neither problem.
    repo = tmp_path / "repo"
    (repo / "src" / "pkg").mkdir(parents=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)

    git("init", "-q", "-b", "main")
    module = repo / "src" / "pkg" / "thing.py"
    module.write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "base")

    # NEGATIVE: nothing changed at all -> the scope must be zero BYTES, not a
    # bare newline, or `[ -s scope.txt ]` sends the recipe down its work branch.
    empty = _run(scope_script, repo, "scope", "HEAD", "80")
    assert empty.returncode == 0, empty.stdout + empty.stderr
    assert empty.stdout == "", (
        "an empty scope wrote bytes, so the recipe will take its work branch "
        f"and run mutmut unscoped: {empty.stdout!r}"
    )

    # POSITIVE partner: change a line INSIDE the function and the same script
    # must emit a glob. Without this, the assertion above is equally satisfied
    # by a scope() that has stopped producing output at all.
    module.write_text("def f(x):\n    return x + 2\n", encoding="utf-8")
    populated = _run(scope_script, repo, "scope", "HEAD", "80")
    assert populated.returncode == 0, populated.stdout + populated.stderr
    assert "pkg.thing.x_f__mutmut_*" in populated.stdout, (
        "a working-tree change inside a function produced no scope — "
        f"scope() is emitting nothing at all:\n{populated.stdout}{populated.stderr}"
    )


def _repo_with(tmp_path: Path, before: str, after: str) -> Path:
    """A throwaway git repo whose worktree changes `before` -> `after`."""
    repo = tmp_path / "repo"
    (repo / "src" / "pkg").mkdir(parents=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)

    module = repo / "src" / "pkg" / "thing.py"
    module.write_text(before, encoding="utf-8")
    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-qm", "base")
    module.write_text(after, encoding="utf-8")
    return repo


DECORATED_BEFORE = """\
class C:
    @property
    def value(self):
        return 1
"""
DECORATED_AFTER = """\
class C:
    @property
    def value(self):
        return 2
"""


def test_a_decorated_only_change_is_excluded_and_reported(
    scope_script: Path, tmp_path: Path
) -> None:
    """The #136 abort: mutmut builds no mutants for a decorated function.

    Before this fix the scope named the glob, `mutmut run` matched nothing and
    died with "Filtered for specific mutants, but nothing matches" — surfaced to
    the author as the recipe's "missing from also_copy" message, which is the
    wrong cause. Measured over history: 7% of changes with a non-empty scope
    abort this way.

    The function is now excluded (so the run does not abort) and REPORTED on
    stderr (so the gap is visible rather than silent).

    Turns red if: `unmutatable()` stops returning True for a decorated
    function — the glob returns and the abort comes back.
    """
    repo = _repo_with(tmp_path, DECORATED_BEFORE, DECORATED_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "", (
        f"a decorated function was scoped; mutmut will match nothing: {result.stdout!r}"
    )
    assert "cannot be mutated" in result.stderr, (
        f"the exclusion was silent — the whole point is that it is visible:\n{result.stderr}"
    )
    assert "pkg.thing.value" in result.stderr, (
        f"the report must name the function, or it is not actionable:\n{result.stderr}"
    )


def test_the_note_never_contaminates_the_scope_file(scope_script: Path, tmp_path: Path) -> None:
    """The note goes to stderr. On stdout it would become a mutant name.

    `scope` mode's stdout is redirected into build/mutation/scope.txt and passed
    verbatim to `mutmut run`. A human-readable line there is read as a mutant
    glob.

    Turns red if: the note is written with print() instead of sys.stderr.
    """
    repo = _repo_with(tmp_path, DECORATED_BEFORE, DECORATED_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")
    assert "cannot be mutated" not in result.stdout, (
        f"the exclusion note leaked into scope.txt: {result.stdout!r}"
    )


PLAIN_BEFORE = """\
class C:
    @property
    def value(self):
        return 1

    @staticmethod
    def helper(x):
        return x + 1


def free(x):
    return x + 1
"""
PLAIN_AFTER = PLAIN_BEFORE.replace("return x + 1", "return x + 2")


def test_only_the_unmutatable_functions_are_dropped(scope_script: Path, tmp_path: Path) -> None:
    """Positive partner: the exclusion must not swallow mutatable functions.

    A bare @staticmethod IS mutated by mutmut
    (mutmut/mutation/file_mutation.py:230-235), so it must stay in scope — and
    an undecorated function obviously must. Without this, the two assertions
    above are equally satisfied by a scope() that drops everything.

    Turns red if: `unmutatable()` is widened to any decorated function, or to
    all functions.
    """
    repo = _repo_with(tmp_path, PLAIN_BEFORE, PLAIN_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")

    assert "xǁCǁhelper__mutmut_*" in result.stdout, (
        f"a bare @staticmethod was dropped, but mutmut does mutate it:\n{result.stdout}"
    )
    assert "x_free__mutmut_*" in result.stdout, (
        f"an undecorated function was dropped:\n{result.stdout}"
    )


DATACLASS_BEFORE = """\
from dataclasses import dataclass


@dataclass
class Session:
    token: str

    def is_expired(self):
        return 1
"""
DATACLASS_AFTER = DATACLASS_BEFORE.replace("return 1", "return 2")


def test_a_decorated_class_hides_every_method_it_contains(
    scope_script: Path, tmp_path: Path
) -> None:
    """A DECORATED CLASS is skipped by mutmut together with its whole subtree.

    `file_mutation.py:236-237` returns True from `_skip_node_and_children` for a
    decorated ClassDef, and `on_visit` then stops descending — so every method
    inside is unmutatable, decorated or not. Every `@dataclass` is this shape.

    Missing this left #136 reachable from four real functions on main
    (`auth._Session.is_expired`, two `RunEvaluationResult` properties,
    `feedback_audit.Finding.to_markdown`) — a PR touching only session expiry
    would still have aborted with the misleading also_copy message. Found by
    adversarial review; the first fix only handled decorated FUNCTIONS.

    Turns red if: `walk()` stops propagating the enclosing class's decorators
    to its methods.
    """
    repo = _repo_with(tmp_path, DATACLASS_BEFORE, DATACLASS_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "", (
        "an undecorated method of a @dataclass was scoped; mutmut skips the "
        f"whole class subtree, so the glob matches nothing: {result.stdout!r}"
    )
    assert "pkg.thing.is_expired" in result.stderr, (
        f"the exclusion must name the method:\n{result.stderr}"
    )


UNDECORATED_CLASS_BEFORE = """\
class Session:
    def is_expired(self):
        return 1
"""
UNDECORATED_CLASS_AFTER = UNDECORATED_CLASS_BEFORE.replace("return 1", "return 2")


def test_an_undecorated_class_keeps_its_methods(scope_script: Path, tmp_path: Path) -> None:
    """Positive partner: the class rule must key off the DECORATOR, not the class.

    Without this, the assertion above is equally satisfied by a `walk()` that
    drops every method of every class.

    Turns red if: methods are dropped for any class rather than a decorated one.
    """
    repo = _repo_with(tmp_path, UNDECORATED_CLASS_BEFORE, UNDECORATED_CLASS_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")
    assert "xǁSessionǁis_expired__mutmut_*" in result.stdout, (
        f"a plain class method was dropped:\n{result.stdout}{result.stderr}"
    )


EDGE_BEFORE = """\
import builtins


class C:
    @staticmethod()
    def called_form(x):
        return 1

    @builtins.staticmethod
    def attribute_form(x):
        return 1

    @property
    @staticmethod
    def two_decorators(self):
        return 1

    @staticmethod
    async def async_static(x):
        return 1
"""
EDGE_AFTER = EDGE_BEFORE.replace("return 1", "return 2")


def test_the_decorator_edge_cases_match_mutmut(scope_script: Path, tmp_path: Path) -> None:
    """Only a LONE, BARE `staticmethod`/`classmethod` Name is mutatable.

    mutmut checks `isinstance(decorator, cst.Name)` on the single decorator, so
    the call form `@staticmethod()` is an ast.Call, the dotted form
    `@builtins.staticmethod` is an ast.Attribute, and two decorators fail the
    `len == 1` test. All three are unmutatable.

    This pins the cases the implementation gets RIGHT. Without it, "simplifying"
    to `any(isinstance(d, ast.Name) and d.id in (...) for d in decorators)`
    passes every other test in this module while re-opening the #136 abort for
    the four `@field_validator(...) + @classmethod` pairs in config.py.

    Turns red if: the check is loosened to `any(...)` over the decorator list,
    or stops requiring a bare `ast.Name`.
    """
    repo = _repo_with(tmp_path, EDGE_BEFORE, EDGE_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")

    for unmutatable_name in ("called_form", "attribute_form", "two_decorators"):
        assert unmutatable_name in result.stderr, (
            f"{unmutatable_name} should be excluded — mutmut will not mutate it:\n{result.stderr}"
        )
        assert unmutatable_name not in result.stdout, (
            f"{unmutatable_name} was scoped but mutmut generates nothing for it"
        )
    # Positive partner: a lone bare @staticmethod IS mutated, even when async.
    assert "async_static" in result.stdout, (
        f"a lone bare @staticmethod was dropped, but mutmut mutates it:\n{result.stdout}"
    )


NESTED_FUNC_BEFORE = """\
def outer(x):
    def inner(y):
        return y + 1
    return inner(x)
"""
NESTED_FUNC_AFTER = NESTED_FUNC_BEFORE.replace("return y + 1", "return y + 2")


def test_a_nested_function_change_is_attributed_to_the_outer_function(
    scope_script: Path, tmp_path: Path
) -> None:
    """#146: mutmut names every mutant of `inner` `x_outer__mutmut_*`, never
    `x_inner__mutmut_*` — measured directly (mutmut 3.x,
    `mutmut/mutation/file_mutation.py::OuterFunctionProvider`): it links every
    node to the nearest ENCLOSING TOP-LEVEL function or method, and a def
    nested inside another def is not itself a top-level unit. Naming the
    inner function produces a glob that matches nothing, so a PR touching
    only `inner` used to abort with "nothing matches" or, worse, silently
    measure nothing while reporting a clean scope.

    Turns red if: `walk()` goes back to minting a separate glob for a
    FunctionDef nested inside another FunctionDef.
    """
    repo = _repo_with(tmp_path, NESTED_FUNC_BEFORE, NESTED_FUNC_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "x_outer__mutmut_*" in result.stdout, (
        f"the outer function was not scoped:\n{result.stdout}{result.stderr}"
    )
    assert "x_inner" not in result.stdout, (
        f"the nested function got its own (dead) glob: {result.stdout!r}"
    )


DOUBLY_NESTED_BEFORE = """\
def a(x):
    def b(y):
        def c(z):
            return z + 1
        return c(y) + 1
    return b(x) + 1
"""
DOUBLY_NESTED_AFTER = DOUBLY_NESTED_BEFORE.replace("return z + 1", "return z + 2")


def test_a_doubly_nested_function_change_is_attributed_to_the_outermost_function(
    scope_script: Path, tmp_path: Path
) -> None:
    """Measured directly: mutmut attributes `c`'s mutants to `a`, not `b` — the
    OUTERMOST top-level def, regardless of nesting depth.

    Turns red if: nesting depth > 1 attributes to the immediate parent (`b`)
    instead of the outermost top-level function (`a`).
    """
    repo = _repo_with(tmp_path, DOUBLY_NESTED_BEFORE, DOUBLY_NESTED_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "x_a__mutmut_*" in result.stdout, (
        f"the outermost function was not scoped:\n{result.stdout}{result.stderr}"
    )
    assert "x_b" not in result.stdout and "x_c" not in result.stdout, (
        f"an intermediate or innermost nested function got its own (dead) glob: {result.stdout!r}"
    )


NESTED_IN_METHOD_BEFORE = """\
class C:
    def method(self, x):
        def inner(y):
            return y + 1
        return inner(x) + 1
"""
NESTED_IN_METHOD_AFTER = NESTED_IN_METHOD_BEFORE.replace("return y + 1", "return y + 2")


def test_a_function_nested_inside_a_method_is_attributed_to_the_method(
    scope_script: Path, tmp_path: Path
) -> None:
    """Measured directly: nested inside a method, mutmut attributes to the
    method's mangled name (`xǁCǁmethod__mutmut_*`), never the inner def's name.

    Turns red if: a function nested inside a method mints its own glob instead
    of the enclosing method's.
    """
    repo = _repo_with(tmp_path, NESTED_IN_METHOD_BEFORE, NESTED_IN_METHOD_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "xǁCǁmethod__mutmut_*" in result.stdout, (
        f"the enclosing method was not scoped:\n{result.stdout}{result.stderr}"
    )
    assert "inner" not in result.stdout, (
        f"the nested function got its own (dead) glob: {result.stdout!r}"
    )


NO_MUTABLE_RETURN_NAME_BEFORE = """\
_store = None


def get_store(x):
    return _store
"""
NO_MUTABLE_RETURN_NAME_AFTER = NO_MUTABLE_RETURN_NAME_BEFORE.replace(
    "return _store", "return _store  # c"
)


def test_a_bare_return_of_a_name_has_no_mutable_content(scope_script: Path, tmp_path: Path) -> None:
    """#146: `return _store` has no number, string, call-with-args, operator or
    assignment for any mutmut operator to touch — measured directly (mutmut
    3.x): 0 mutants generated. Naming it produces a glob matching nothing.

    Turns red if: `no_mutable_content()` stops recognising a bare-name return.
    """
    repo = _repo_with(tmp_path, NO_MUTABLE_RETURN_NAME_BEFORE, NO_MUTABLE_RETURN_NAME_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "", (
        f"a no-mutable-content function was scoped; mutmut generates nothing: {result.stdout!r}"
    )
    assert "no mutable content" in result.stderr, (
        f"the exclusion must say why, distinctly from the decorated case:\n{result.stderr}"
    )
    assert "pkg.thing.get_store" in result.stderr, (
        f"the report must name the function:\n{result.stderr}"
    )


ELLIPSIS_STUB_BEFORE = """\
def clear_it(self):
    ...
"""
ELLIPSIS_STUB_AFTER = ELLIPSIS_STUB_BEFORE.replace("    ...", "    ...  # c")


def test_an_ellipsis_stub_body_has_no_mutable_content(scope_script: Path, tmp_path: Path) -> None:
    """A bare `...` stub body: measured directly, 0 mutants.

    Turns red if: `no_mutable_content()` stops recognising an Ellipsis body.
    """
    repo = _repo_with(tmp_path, ELLIPSIS_STUB_BEFORE, ELLIPSIS_STUB_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")
    assert result.stdout == "", (
        f"an ellipsis-only function was scoped; mutmut generates nothing for it: {result.stdout!r}"
    )
    assert "pkg.thing.clear_it" in result.stderr


IFEXP_BEFORE = """\
class T:
    def served_confidence(self):
        return self.score if self.support_verified else None
"""
IFEXP_AFTER = IFEXP_BEFORE.replace(
    "return self.score if self.support_verified else None",
    "return self.score if self.support_verified else None  # c",
)


def test_a_bare_ifexp_over_names_has_no_mutable_content(scope_script: Path, tmp_path: Path) -> None:
    """#146's literal example: `return a if b else None`, all three of a/b/None
    bare names — no mutmut operator targets `ast.IfExp` itself. Measured
    directly: 0 mutants.

    Turns red if: `no_mutable_content()` stops recognising a bare IfExp.
    """
    repo = _repo_with(tmp_path, IFEXP_BEFORE, IFEXP_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")
    assert result.stdout == "", (
        f"a bare-IfExp function was scoped; mutmut generates nothing for it: {result.stdout!r}"
    )
    assert "pkg.thing.served_confidence" in result.stderr


ZERO_ARG_CALL_BEFORE = """\
class Svc:
    def default_slots(self, catalog):
        return catalog.default_slots()
"""
ZERO_ARG_CALL_AFTER = ZERO_ARG_CALL_BEFORE.replace(
    "return catalog.default_slots()", "return catalog.default_slots()  # c"
)


def test_a_zero_arg_call_chain_has_no_mutable_content(scope_script: Path, tmp_path: Path) -> None:
    """`return x.y()` with no positional or keyword args: `operator_arg_removal`
    needs at least one arg to remove or None-replace, so this is 0 mutants
    (measured directly on `model_slots.default_model_slots`'s real shape).

    Turns red if: `no_mutable_content()` stops recognising a zero-arg call.
    """
    repo = _repo_with(tmp_path, ZERO_ARG_CALL_BEFORE, ZERO_ARG_CALL_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")
    assert result.stdout == "", (
        f"a zero-arg-call function was scoped; mutmut generates nothing for it: {result.stdout!r}"
    )
    assert "pkg.thing.default_slots" in result.stderr


WITH_CLEAR_BEFORE = """\
class Recorder:
    def clear(self):
        with self._lock:
            self._events.clear()
"""
WITH_CLEAR_AFTER = WITH_CLEAR_BEFORE.replace("self._events.clear()", "self._events.clear()  # c")


def test_a_with_block_wrapping_a_zero_arg_call_has_no_mutable_content(
    scope_script: Path, tmp_path: Path
) -> None:
    """#146's literal example: every `InMemory*Recorder.clear` — `with
    self._lock: self._events.clear()`. `with` itself has no mutmut operator;
    the call inside has no args. Measured directly: 0 mutants.

    Turns red if: `no_mutable_content()` stops recognising a `with` wrapper.
    """
    repo = _repo_with(tmp_path, WITH_CLEAR_BEFORE, WITH_CLEAR_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")
    assert result.stdout == "", (
        f"a with-block zero-arg-call fn was scoped; mutmut generates nothing: {result.stdout!r}"
    )
    assert "pkg.thing.clear" in result.stderr


# --- Positive partners: real mutable content must NOT be excluded. ---

CALL_WITH_ARG_BEFORE = """\
def build(x):
    return dict(a=x)
"""
CALL_WITH_ARG_AFTER = CALL_WITH_ARG_BEFORE.replace("dict(a=x)", "dict(a=x, b=1)")


def test_a_call_with_an_argument_is_not_excluded(scope_script: Path, tmp_path: Path) -> None:
    """Positive partner for the zero-arg-call and with-block tests above: a
    call carrying an argument IS mutable (`operator_arg_removal` /
    `operator_dict_arguments`), so it must stay in scope.

    Without this, the two tests above are equally satisfied by a
    `no_mutable_content()` that excludes every function containing any Call.

    Turns red if: `no_mutable_content()` is widened to treat any Call as inert
    regardless of its arguments.
    """
    repo = _repo_with(tmp_path, CALL_WITH_ARG_BEFORE, CALL_WITH_ARG_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")
    assert "x_build__mutmut_*" in result.stdout, (
        f"a function calling with arguments was wrongly excluded:\n{result.stdout}{result.stderr}"
    )


DEEPCOPY_BARE_CALL_BEFORE = """\
from copy import deepcopy


def snapshot():
    return deepcopy()
"""
DEEPCOPY_BARE_CALL_AFTER = DEEPCOPY_BARE_CALL_BEFORE.replace(
    "return deepcopy()", "return deepcopy()  # c"
)


def test_a_bare_call_to_deepcopy_is_not_excluded(scope_script: Path, tmp_path: Path) -> None:
    """Positive partner for the zero-arg-call tests above: `deepcopy()` has
    zero positional/keyword args, but mutmut's real `operator_name` table
    (`mutmut/mutation/mutators.py`'s `name_mappings`) rewrites the bare
    identifier `deepcopy` -> `copy` wherever it appears as a `Name` node --
    independent of whether it is called with arguments. So this IS a real
    mutant (#146 false-exclusion regression: `_safe_expr`'s zero-arg-call
    fast path treated `_safe_expr(node.func, source)` as sufficient, which
    is true for `operator_arg_removal`/`operator_dict_arguments` but blind
    to `operator_name`).

    Turns red if: `no_mutable_content()`/`_safe_expr()` treats every
    zero-arg call as inert regardless of the callee's name.
    """
    repo = _repo_with(tmp_path, DEEPCOPY_BARE_CALL_BEFORE, DEEPCOPY_BARE_CALL_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")
    assert "pkg.thing.x_snapshot__mutmut_*" in result.stdout, (
        f"a bare no-arg deepcopy() call was wrongly excluded:\n{result.stdout}{result.stderr}"
    )


IFEXP_WITH_LITERAL_BEFORE = """\
def maybe(cond):
    return 1 if cond else 2
"""
IFEXP_WITH_LITERAL_AFTER = IFEXP_WITH_LITERAL_BEFORE.replace(
    "return 1 if cond else 2", "return 3 if cond else 2"
)


def test_an_ifexp_with_a_number_literal_branch_is_not_excluded(
    scope_script: Path, tmp_path: Path
) -> None:
    """Positive partner for the bare-IfExp test: `1`/`2` ARE mutable numbers
    (`operator_number`), so an IfExp whose branches carry literals must stay
    in scope even though the IfExp node itself is never targeted.

    Turns red if: `no_mutable_content()` is widened to treat any IfExp as
    inert regardless of its branches.
    """
    repo = _repo_with(tmp_path, IFEXP_WITH_LITERAL_BEFORE, IFEXP_WITH_LITERAL_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")
    assert "x_maybe__mutmut_*" in result.stdout, (
        f"a function with number-literal IfExp branches was wrongly excluded:\n"
        f"{result.stdout}{result.stderr}"
    )


NESTED_WITH_REAL_CONTENT_BEFORE = """\
def outer(x):
    def inner(y):
        return y + 1
    return inner(x)
"""
# Change the OUTER's own trivial wrapping line, not inner -- still must scope
# to x_outer because inner's own body has a real mutable `+ 1`.
NESTED_WITH_REAL_CONTENT_AFTER = (
    "def outer(x):\n    def inner(y):\n        return y + 1\n    return inner(x)  # c\n"
)


def test_a_changed_outer_whose_nested_function_has_real_content_is_not_excluded(
    scope_script: Path, tmp_path: Path
) -> None:
    """Positive partner: `no_mutable_content()` must inspect a nested def's
    OWN body too, since mutmut attributes its mutations to the same outer
    glob. `inner`'s `y + 1` is mutable, so `outer` must stay in scope even
    though `outer`'s own directly-owned statements are trivial wrappers.

    Turns red if: `no_mutable_content()` only inspects the outer function's
    own body and ignores nested defs, wrongly excluding a function whose real
    mutable content lives one level down.
    """
    repo = _repo_with(tmp_path, NESTED_WITH_REAL_CONTENT_BEFORE, NESTED_WITH_REAL_CONTENT_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")
    assert "x_outer__mutmut_*" in result.stdout, (
        f"a function whose nested def has real mutable content was wrongly "
        f"excluded:\n{result.stdout}{result.stderr}"
    )


FSTRING_BEFORE = """\
def notice(round_number):
    return (
        f"Debate round {round_number} used a local heuristic because the "
        f"live moderator call failed or was not configured."
    )
"""
FSTRING_AFTER = FSTRING_BEFORE.replace("Debate round", "Debate round ")


def test_a_pure_fstring_return_has_no_mutable_content(scope_script: Path, tmp_path: Path) -> None:
    """#146's real dead glob: `debate._debate_fallback_notice` and
    `synthesis._synthesis_fallback_notice`/`_section_prompt` all return an
    f-string. Measured directly against mutmut's own `create_mutations()`
    (mutmut 3.x, `mutmut/mutation/mutators.py::operator_string`): it
    type-checks `isinstance(node, cst.SimpleString)` and yields nothing for
    a `cst.FormattedString` (an f-string), so a pure f-string built only from
    safe placeholders (bare names here) is 0 real mutants.

    Turns red if: `_safe_expr()` stops recognising `ast.JoinedStr`.
    """
    repo = _repo_with(tmp_path, FSTRING_BEFORE, FSTRING_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")
    assert result.stdout == "", (
        f"a pure-fstring-return function was scoped; mutmut generates nothing: {result.stdout!r}"
    )
    assert "pkg.thing.notice" in result.stderr


FSTRING_WITH_LITERAL_PLACEHOLDER_BEFORE = """\
def notice(round_number):
    return f"round {1}"
"""
FSTRING_WITH_LITERAL_PLACEHOLDER_AFTER = FSTRING_WITH_LITERAL_PLACEHOLDER_BEFORE.replace(
    'f"round {1}"', 'f"round {1} "'
)


def test_an_fstring_with_a_number_placeholder_is_not_excluded(
    scope_script: Path, tmp_path: Path
) -> None:
    """Positive partner: mutmut's visitor still recurses into an f-string's
    embedded `{...}` expressions as ordinary CST nodes, so a number literal
    INSIDE the placeholder (`{1}`) IS mutable (`operator_number`) even though
    the f-string's own literal text is not.

    Turns red if: `_safe_expr()` is widened to treat any JoinedStr as inert
    regardless of its embedded placeholder expressions.
    """
    repo = _repo_with(
        tmp_path, FSTRING_WITH_LITERAL_PLACEHOLDER_BEFORE, FSTRING_WITH_LITERAL_PLACEHOLDER_AFTER
    )
    result = _run(scope_script, repo, "scope", "HEAD", "80")
    assert "x_notice__mutmut_*" in result.stdout, (
        f"an f-string with a mutable number placeholder was wrongly excluded:\n"
        f"{result.stdout}{result.stderr}"
    )


DICTCOMP_BEFORE = """\
class Svc:
    def price_index(self):
        return {
            entry.model_id: (entry.input_price, entry.output_price)
            for entry in self._entries()
        }
"""
DICTCOMP_AFTER = DICTCOMP_BEFORE.replace("entry.model_id", "entry.model_id ")


def test_a_dict_comprehension_over_safe_subexprs_has_no_mutable_content(
    scope_script: Path, tmp_path: Path
) -> None:
    """#146's real dead glob: `model_slots.OpenRouterModelCatalogService.price_index`
    — a dict comprehension whose key/value/generator are all bare
    attribute/zero-arg-call chains. Measured directly: no mutmut operator
    targets `cst.DictComp`/`cst.CompFor` at all, so with only safe
    sub-expressions this is 0 real mutants.

    Turns red if: `_safe_expr()` stops recognising a comprehension with safe
    key/value/generator sub-expressions.
    """
    repo = _repo_with(tmp_path, DICTCOMP_BEFORE, DICTCOMP_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")
    assert result.stdout == "", (
        f"a safe-subexpr dict comprehension was scoped; mutmut generates nothing: {result.stdout!r}"
    )
    assert "pkg.thing.price_index" in result.stderr


DICTCOMP_WITH_NUMBER_BEFORE = """\
class Svc:
    def price_index(self):
        return {entry.model_id: 1 for entry in self._entries()}
"""
DICTCOMP_WITH_NUMBER_AFTER = DICTCOMP_WITH_NUMBER_BEFORE.replace(
    "entry.model_id: 1", "entry.model_id: 2"
)


def test_a_dict_comprehension_with_a_number_literal_value_is_not_excluded(
    scope_script: Path, tmp_path: Path
) -> None:
    """Positive partner: a number literal anywhere inside the comprehension
    (here the dict value) IS mutable (`operator_number`), so the whole
    function must stay in scope.

    Turns red if: `_safe_expr()` is widened to treat any comprehension as
    inert regardless of its key/value/generator sub-expressions.
    """
    repo = _repo_with(tmp_path, DICTCOMP_WITH_NUMBER_BEFORE, DICTCOMP_WITH_NUMBER_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")
    assert "xǁSvcǁprice_index__mutmut_*" in result.stdout, (
        f"a dict comprehension with a mutable number literal was wrongly excluded:\n"
        f"{result.stdout}{result.stderr}"
    )


IMPLICIT_CONCAT_BEFORE = """\
class Svc:
    def notice(self, x):
        return (
            f"Cross-check summary for {x}: compare the cited evidence, "
            "preserve disagreement, and verify important claims before acting."
        )
"""
IMPLICIT_CONCAT_AFTER = IMPLICIT_CONCAT_BEFORE.replace(
    "preserve disagreement", "Preserve disagreement"
)


def test_an_fstring_implicitly_concatenated_with_a_plain_string_is_not_excluded(
    scope_script: Path, tmp_path: Path
) -> None:
    """#146 residual, found by cross-checking this fix against mutmut's own
    `create_mutations()` on the real tree: `providers._local_simulation_text`
    is an f-string immediately followed by a plain string literal (Python's
    implicit adjacent-literal concatenation).

    Stdlib `ast` MERGES both into a single `JoinedStr`, with the plain
    literal's text becoming an ordinary `Constant` sub-part indistinguishable
    from true f-string text — but libcst does NOT merge them: it keeps the
    plain segment as its own `cst.SimpleString`, which `operator_string`
    DOES mutate. Measured directly against `create_mutations()`: this shape
    has 3 real mutants (the plain segment's string mutations), all from a
    `_safe_expr()` that trusted the merged `ast.JoinedStr` structure.

    Turns red if: `_safe_expr()` treats every `Constant(str)` inside a
    `JoinedStr` as inert without checking for a literal `STRING` token (a
    plain, non-f segment) in the node's own source text.
    """
    repo = _repo_with(tmp_path, IMPLICIT_CONCAT_BEFORE, IMPLICIT_CONCAT_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")
    assert "xǁSvcǁnotice__mutmut_*" in result.stdout, (
        "an f-string implicitly concatenated with a mutable plain string was "
        f"wrongly excluded:\n{result.stdout}{result.stderr}"
    )


def test_scope_fails_loudly_on_a_bad_base_ref(scope_script: Path) -> None:
    """A base ref git cannot resolve must be a hard error, not an empty scope."""
    result = _run(scope_script, REPO_ROOT, "scope", "origin/does-not-exist-xyz", "90")
    assert result.returncode != 0, (
        "an unresolvable base ref produced an empty scope; the recipe would "
        f"print 'nothing to mutate' and pass:\n{result.stdout}"
    )
    assert "origin/does-not-exist-xyz" in result.stdout + result.stderr


@pytest.fixture(scope="module")
def mutation_recipe() -> str:
    result = subprocess.run(
        ["make", "--no-print-directory", "-n", "mutation-baseline"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.replace("\\\n", " ")


def test_recipe_does_not_pipe_mutmut_into_tail(mutation_recipe: str) -> None:
    """A pipe reports the exit status of `tail`, so a mutmut crash looks clean.

    `||` is fine — that is the explicit failure branch — but a single `|`
    between `mutmut run` and the next command separator is the fail-open shape.
    """
    run = re.search(r"mutmut run.*?(?=;)", mutation_recipe, re.DOTALL)
    assert run, f"no `mutmut run` invocation in the recipe:\n{mutation_recipe}"
    assert not re.search(r"(?<!\|)\|(?!\|)", run.group(0)), (
        f"mutmut's exit status is discarded by the pipe: {run.group(0)}"
    )
    assert "|| {" in run.group(0), f"mutmut run has no failure branch: {run.group(0)}"


def test_recipe_clears_stale_mutant_metadata(mutation_recipe: str) -> None:
    """`mutants/` is gitignored, so a stale tree survives across runs."""
    assert "rm -rf mutants" in mutation_recipe, (
        "the recipe does not clear mutants/; a crashed run would be scored "
        f"against a previous run's metadata:\n{mutation_recipe}"
    )


def test_the_abort_message_names_the_copied_tree_cause(mutation_recipe: str) -> None:
    """The failure text sent the last reader to the wrong file (#158).

    When `mutmut run` dies at `failed to collect stats` the recipe prints the
    diagnosis. It used to assert one cause — "usually a repo-root file missing
    from `[tool.mutmut].also_copy`" — and on #158 that was simply wrong: nothing
    was missing. The real cause was a guard resolving the repository root from
    `__file__`, which inside `./mutants/` reads the copy and counts the mutation
    runner's own generated variants. The message cost real diagnosis time by
    being confidently specific about the wrong thing.

    Both causes must be named, and the message must say plainly that the job
    measured nothing — otherwise a red gate reads as a verdict on the diff.

    Turns red if: the copied-tree cause or the "no score was produced" warning
    is dropped from the recipe's failure branch.
    """
    assert "also_copy" in mutation_recipe, (
        "the also_copy cause was dropped; it is still the second-most-likely "
        "reason the suite cannot run inside ./mutants/"
    )
    assert "__file__" in mutation_recipe, (
        "the failure message does not name the copied-tree cause. #158 aborted "
        "on a guard resolving the repo root from __file__ while the message "
        "pointed at also_copy, where nothing was wrong."
    )
    assert "NOT ABOUT YOUR DIFF" in mutation_recipe, (
        "the failure message no longer says the exit code is about the gate "
        "rather than the change — which is what made a red gate read as a "
        "verdict on the diff in #158"
    )


def _load_scope_module(scope_script: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Import the extracted `MUTMUT_SCOPE_PY` block as a real module.

    The block reads `mode, base, threshold` off `sys.argv` at MODULE level
    (it is normally invoked as `python - scope <base> <threshold>`, never
    imported), so `sys.argv` needs three harmless placeholder args or the
    import itself raises before any test code runs.

    Typed `Any` deliberately: dynamically loaded module, no mypy stub.
    """
    monkeypatch.setattr(sys, "argv", ["mutscope.py", "scope", "HEAD", "80"])
    spec = importlib.util.spec_from_file_location("mutscope_under_test", scope_script)
    assert spec and spec.loader
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_tokenize_failure_fails_closed_instead_of_crashing(
    scope_script: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_joined_str_has_a_real_string_literal()` catches a real tokenize
    failure on the node's own source segment and fails closed (returns
    True — "can't prove it safe").

    Before this test existed, the except clause named a exception class that
    does not exist on this Python (`tokenize.TokenizeError` — the real name
    is `tokenize.TokenError`). Because Python evaluates an `except (...)`
    tuple only when an exception actually needs matching, this was silent
    for every JoinedStr that tokenizes cleanly, and only broke — with an
    `AttributeError` masking the real tokenize error — the one time a segment
    genuinely failed to tokenize (a single unterminated string literal
    genuinely raises `tokenize.TokenError`, confirmed directly against
    CPython 3.14's `tokenize` module).

    Turns red if: `tokenize.TokenError` reverts to the nonexistent
    `tokenize.TokenizeError` name (an `AttributeError` propagates instead of
    the function returning `True`).
    """
    module = _load_scope_module(scope_script, monkeypatch)
    monkeypatch.setattr(module.ast, "get_source_segment", lambda *_a, **_k: '"')

    expr_stmt = ast.parse('f"x"').body[0]
    assert isinstance(expr_stmt, ast.Expr)
    node = expr_stmt.value
    assert isinstance(node, ast.JoinedStr)

    assert module._joined_str_has_a_real_string_literal(node, 'f"x"') is True


# ---------------------------------------------------------------------------
# #337: the scope has to name the ORACLE tests, not only the mutants.
#
# `mutmut run` reads its mutant-name arguments TWICE, and the two readers match
# them against differently-spelled names:
#
#   * ``collect_source_file_mutation_data()`` globs them against concrete
#     mutant keys, which carry the ``__mutmut_<n>`` suffix; and
#   * ``tests_for_mutant_names()`` globs them against the MANGLED function
#     names recorded during stats collection, which do NOT.
#
# The scope emitted only the suffixed spelling, so the second lookup returned
# the empty set -- and mutmut reads an empty test set as "no selection given"
# and runs the WHOLE suite in its clean-test phase, before it scores a single
# mutant. Measured 2026-08-22 against the real stats file for the three
# ``costs`` functions of PR #359: 0 mangled names matched, so the clean phase
# ran all 2929 tests; the genuine association set is 258.
# ---------------------------------------------------------------------------

ORACLE_BEFORE = """\
class C:
    def value(self):
        return 1

    def value_extra(self):
        return 10


def other():
    return 100
"""
ORACLE_AFTER = ORACLE_BEFORE.replace("return 1\n", "return 2\n", 1)

CHANGED_MANGLED_NAME = "pkg.thing.xǁCǁvalue"


def _scope_patterns(scope_script: Path, tmp_path: Path) -> list[str]:
    """The mutant-name arguments the shipped scope() hands to `mutmut run`.

    Exactly one function changes (`C.value`); `C.value_extra` and `other` are
    present and untouched, so an over-selecting pattern has something to catch.
    """
    repo = _repo_with(tmp_path, ORACLE_BEFORE, ORACLE_AFTER)
    result = _run(scope_script, repo, "scope", "HEAD", "80")
    assert result.returncode == 0, result.stdout + result.stderr
    patterns = result.stdout.split()
    assert patterns, (
        "scope() emitted nothing for a changed method, so neither assertion "
        f"below is measuring anything:\n{result.stdout}{result.stderr}"
    )
    return patterns


SYNTHETIC_ASSOCIATIONS = {
    CHANGED_MANGLED_NAME: {"pkg_tests/test_value.py::test_one"},
    "pkg.thing.xǁCǁvalue_extra": {"pkg_tests/test_extra.py::test_two"},
    "pkg.thing.x_other": {"pkg_tests/test_other.py::test_three"},
}


def test_the_scope_names_the_tests_that_will_be_the_oracles(
    scope_script: Path, tmp_path: Path
) -> None:
    """Driven through mutmut's OWN lookup, not through a local model of it.

    Asserts equality, not merely non-emptiness: the companion pattern must find
    the changed function's tests and must not drag in a neighbour's.

    The three `pkg.thing.*` keys are ADDED to mutmut's association map and
    removed again, rather than the map being swapped out wholesale. This module
    runs inside mutmut's own `./mutants/` copy during stats collection, where
    that map is the live recorder of trampoline hits — replacing it, even for
    one test, drops whatever the collector writes during that window.

    Turns red if: scope() stops emitting the unsuffixed `*<module>.<name>`
    companion pattern. Verified by deleting that `globs.append` line —
    `assert set() == {'pkg_tests/test_value.py::test_one'}`.
    """
    import mutmut
    from mutmut.__main__ import tests_for_mutant_names

    patterns = _scope_patterns(scope_script, tmp_path)
    associations = mutmut.tests_by_mangled_function_name
    assert not set(SYNTHETIC_ASSOCIATIONS) & set(associations), (
        "a synthetic key collides with a real recorded one; the assertion "
        "below would be measuring mutmut's own stats, not this scope"
    )
    associations.update(SYNTHETIC_ASSOCIATIONS)
    try:
        found = tests_for_mutant_names(patterns)
    finally:
        for key in SYNTHETIC_ASSOCIATIONS:
            associations.pop(key, None)

    assert set(found) == {"pkg_tests/test_value.py::test_one"}


def test_the_scope_still_selects_exactly_the_changed_functions_mutants(
    scope_script: Path, tmp_path: Path
) -> None:
    """Positive partner: the mutant selection must be unchanged and precise.

    The lookup mirrored here is `collect_source_file_mutation_data()`'s filter
    (`mutmut/__main__.py`: `fnmatch.fnmatch(key, mutant_name)`). It is the half
    of the contract the companion pattern must not disturb: a pattern that
    matched the mangled name by trailing-globbing the function name instead
    (`<name>*`) would also select `value_extra`'s mutants and silently mutate a
    function the diff never touched.

    Turns red if: the `__mutmut_*` glob is dropped (nothing is selected), or
    the companion pattern is spelled `<name>*` instead of `*<name>`
    (`value_extra__mutmut_1` joins the selection).
    """
    patterns = _scope_patterns(scope_script, tmp_path)
    keys = [
        "pkg.thing.xǁCǁvalue__mutmut_1",
        "pkg.thing.xǁCǁvalue__mutmut_2",
        "pkg.thing.xǁCǁvalue_extra__mutmut_1",
        "pkg.thing.x_other__mutmut_1",
    ]

    selected = [k for k in keys if any(fnmatch.fnmatch(k, p) for p in patterns)]

    assert selected == ["pkg.thing.xǁCǁvalue__mutmut_1", "pkg.thing.xǁCǁvalue__mutmut_2"]


def test_an_empty_oracle_set_makes_mutmut_run_the_whole_suite() -> None:
    """Why the test above matters, pinned against mutmut rather than in prose.

    The cost of an unmatched pattern is not "mutmut runs no tests" — it is
    "mutmut runs every test". `_pytest_args_regular_run` treats a falsy test
    set as "no selection given" and falls back to the configured test
    selection, which here is empty, i.e. pytest's own `testpaths`.

    Turns red if: a mutmut upgrade makes an empty test set mean something else,
    at which point the companion pattern above is solving a different problem
    and this whole section needs re-deriving.
    """
    from mutmut.__main__ import PytestRunner

    # A duck-typed stand-in: the method reads exactly one attribute, and
    # constructing a real PytestRunner would require mutmut's Config to be
    # loaded from a pyproject in the current working directory.
    stub = cast(
        "PytestRunner", types.SimpleNamespace(_pytest_add_cli_args_test_selection=["tests"])
    )

    args_for_none = PytestRunner._pytest_args_regular_run(stub, set())
    args_for_one = PytestRunner._pytest_args_regular_run(
        stub, {"pkg_tests/test_value.py::test_one"}
    )

    assert "pkg_tests/test_value.py::test_one" in args_for_one
    assert "tests" not in args_for_one, (
        "a non-empty test set must NARROW the run; mutmut is still adding the "
        f"whole-suite selection: {args_for_one}"
    )
    assert "tests" in args_for_none, (
        "an empty test set no longer falls back to the whole suite — the "
        f"defect this section exists for has changed shape: {args_for_none}"
    )


# ---------------------------------------------------------------------------
# #337: a run the deadline cut short is not a score.
#
# `scripts/run_with_deadline.py` exits 0 when it kills the run, deliberately, so
# that report() still gets to score what landed on disk. mutmut fills in one
# .meta entry per FINISHED mutant and leaves the rest `None`, and report() skips
# `None`. Demonstrated on a synthetic .meta of 3 killed and 289 unfilled — the
# shape a mid-run kill leaves — report() printed "mutation score = 100.0%" and
# exited 0. The wrapper now drops a marker file when it kills the run, and
# report() reads the same path.
# ---------------------------------------------------------------------------

TRUNCATION_MARKER = "build/mutation/truncated"


#: The literal `scripts/run_with_deadline.py` writes, read from the script so a
#: rename on either side turns these tests red rather than quietly unwiring them.
def _sentinel() -> str:
    source = (REPO_ROOT / "scripts" / "run_with_deadline.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "TRUNCATION_SENTINEL" for t in node.targets
        ):
            assert isinstance(node.value, ast.Constant)
            assert isinstance(node.value.value, str)
            return node.value.value
    raise AssertionError("TRUNCATION_SENTINEL is gone from scripts/run_with_deadline.py")


def _mark_truncated(cwd: Path) -> dict[str, str]:
    """Write the marker the deadline wrapper writes, and point report() at it."""
    marker = cwd / TRUNCATION_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"{_sentinel()}1440s\n", encoding="utf-8")
    return {"RUN_WITH_DEADLINE_MARKER": TRUNCATION_MARKER}


def test_a_truncated_run_reports_no_percentage_however_good_the_prefix_looks(
    scope_script: Path, tmp_path: Path
) -> None:
    """The whole defect, asserted on CARDINALITY rather than on a clean path.

    Three mutants finished and all three were killed; the rest of the scope was
    never reached. Reporting 100% off that prefix is the quietest false pass
    this gate has: the run looks perfect precisely because it stopped early.

    Turns red if: the `if truncated:` branch before the score arithmetic is
    removed from `report()`. Verified — the run then prints
    `mutation score (killed / (killed+survived)) = 100.0% (threshold 90%)`.
    """
    metas = {
        "x_a__mutmut_1": 1,
        "x_a__mutmut_2": 1,
        "x_a__mutmut_3": 1,
        "x_a__mutmut_4": None,
        "x_a__mutmut_5": None,
    }
    _write_meta(tmp_path, "costs", metas)

    truncated = _run(
        scope_script, tmp_path, "report", "origin/main", "90", env=_mark_truncated(tmp_path)
    )
    output = truncated.stdout + truncated.stderr

    assert "mutation score" not in output, (
        "a run the deadline cut short still printed a percentage; the mutants "
        f"it never reached are unmeasured, not killed:\n{output}"
    )
    assert "UNMEASURED" in output, f"a truncated run must say so in words:\n{output}"
    assert "3 of the scope's mutants" in output, (
        f"the truncated verdict must report HOW MANY it managed to score:\n{output}"
    )
    assert truncated.returncode == 0, (
        "a truncated run that found NO survivor is a budget event, not a "
        f"verdict on the diff; it must not fail the gate:\n{output}"
    )

    # POSITIVE PARTNER: the same metadata, no marker. Without this, the
    # assertions above are equally satisfied by a report() that has stopped
    # scoring anything at all.
    complete = _run(scope_script, tmp_path, "report", "origin/main", "90")
    assert "mutation score (killed / (killed+survived)) = 100.0%" in complete.stdout, (
        "the identical metadata scores nothing when the run was NOT truncated — "
        f"the marker is not what is being measured:\n{complete.stdout}"
    )


def test_a_truncated_run_still_reports_the_survivors_it_did_find(
    scope_script: Path, tmp_path: Path
) -> None:
    """A survivor found before the deadline is a real finding, not noise.

    Suppressing the whole report on truncation would throw away the one part of
    a partial run that IS evidence. Only the percentage is withheld.

    Turns red if: the truncated branch is moved above the `SURVIVED` loop, or
    the loop is dropped from it.
    """
    _write_meta(tmp_path, "costs", {"x_a__mutmut_1": 1, "x_a__mutmut_2": 0, "x_a__mutmut_3": None})

    result = _run(
        scope_script, tmp_path, "report", "origin/main", "90", env=_mark_truncated(tmp_path)
    )
    output = result.stdout + result.stderr

    assert "SURVIVED x_a__mutmut_2" in output, (
        f"a survivor found before the deadline was swallowed by the cut-off:\n{output}"
    )
    assert "mutation score" not in output, output
    assert result.returncode != 0, (
        "a truncated run that DEMONSTRATED a survivor passed. Adversarial "
        "review found exactly this: the identical metadata exits 1 without the "
        f"marker, so the marker turned a red gate green:\n{output}"
    )


def test_a_truncated_run_that_scored_nothing_names_the_deadline(
    scope_script: Path, tmp_path: Path
) -> None:
    """#337's actual CI symptom, and the message it used to print.

    `mutants/` was present and fully generated; the deadline simply fired inside
    mutmut's clean-test phase, before the mutant phase began. The shipped
    message for that state was "the run did not happen (empty or absent
    mutants/)", which is false and sent three sessions reading `also_copy`.

    Turns red if: the `if truncated:` branch inside `if not checked:` is
    removed — the wrong "empty or absent mutants/" message comes back.
    """
    _write_meta(tmp_path, "costs", {"x_a__mutmut_1": None, "x_a__mutmut_2": None})

    result = _run(
        scope_script, tmp_path, "report", "origin/main", "90", env=_mark_truncated(tmp_path)
    )
    output = result.stdout + result.stderr

    assert result.returncode != 0, f"a run that scored nothing at all must not pass:\n{output}"
    assert "deadline" in output, (
        f"the message must name the deadline, which is the actual cause:\n{output}"
    )
    assert "empty or absent" not in output, (
        "the truncated run is still being blamed on a missing mutants/ tree — "
        f"the wrong cause, and the one that cost the most time:\n{output}"
    )

    # POSITIVE PARTNER: with no marker the "absent mutants/" diagnosis is the
    # right one and must survive.
    untruncated = _run(scope_script, tmp_path, "report", "origin/main", "90")
    assert "empty or absent" in untruncated.stdout + untruncated.stderr


def test_an_unset_marker_variable_is_not_read_as_a_truncated_run(
    scope_script: Path, tmp_path: Path
) -> None:
    """The harness Makefile that runs the recipe verbatim leaves the marker
    variable EMPTY, and `os.path.exists("")` is False — but so is
    `os.path.exists` of any path under a directory that happens to exist. Pin
    the empty-string case explicitly rather than relying on that.

    Turns red if: `truncated` drops its `bool(marker)` guard and an empty
    variable starts resolving to some existing path.
    """
    _write_meta(tmp_path, "costs", {"x_a__mutmut_1": 1, "x_a__mutmut_2": 0})

    result = _run(
        scope_script,
        tmp_path,
        "report",
        "origin/main",
        "90",
        env={"RUN_WITH_DEADLINE_MARKER": ""},
    )

    assert "mutation score (killed / (killed+survived)) = 50.0%" in result.stdout, result.stdout


def test_a_truncated_run_that_found_a_survivor_cannot_be_greener_than_the_same_run_untruncated(
    scope_script: Path, tmp_path: Path
) -> None:
    """The finding that nearly shipped: truncation must never RELAX the gate.

    Three killed and seven survived is 30%, below any threshold this repo uses,
    and the untruncated gate exits 1 on it. The first version of the truncated
    branch returned before the threshold check, so dropping one marker file
    into the workspace turned that exit 1 into an exit 0 — a visibly red job
    made green by the very mechanism added to make the gate more honest.

    Turns red if: the `counts["survived"]` check is removed from the truncated
    branch. Verified — the truncated run then exits 0 while the untruncated one
    exits 1, and the two assertions below disagree.
    """
    metas: dict[str, int | None] = {f"x_a__mutmut_{i}": 1 for i in range(1, 4)}
    metas.update({f"x_b__mutmut_{i}": 0 for i in range(1, 8)})
    metas.update({f"x_c__mutmut_{i}": None for i in range(1, 290)})
    _write_meta(tmp_path, "costs", metas)

    untruncated = _run(scope_script, tmp_path, "report", "origin/main", "80")
    truncated = _run(
        scope_script, tmp_path, "report", "origin/main", "80", env=_mark_truncated(tmp_path)
    )

    assert untruncated.returncode != 0, (
        "the control run passed at 30%; this test is not measuring a "
        f"relaxation because there is nothing to relax:\n{untruncated.stdout}"
    )
    assert "BELOW THRESHOLD" in untruncated.stdout, untruncated.stdout
    assert truncated.returncode != 0, (
        "adding the truncation marker turned a failing gate into a passing "
        f"one:\n{truncated.stdout}"
    )
    assert "7 mutant(s) SURVIVED before the cut-off" in truncated.stdout, truncated.stdout


def test_only_the_deadline_wrappers_own_marker_counts_as_truncation(
    scope_script: Path, tmp_path: Path
) -> None:
    """Detection is by CONTENT, so a pointed-at file cannot mute the gate.

    `RUN_WITH_DEADLINE_MARKER` comes from the environment. With an
    existence-only test, `MUTATION_TRUNCATION_MARKER=/dev/null make
    mutation-baseline` made a completed, below-threshold run report UNMEASURED
    and exit 0 — demonstrated by adversarial review. /dev/null cannot even be
    unlinked, so the wrapper's clear-on-entry could not undo it.

    Turns red if: the sentinel comparison in `report()` is replaced by
    `os.path.exists(marker)`. Verified — the first two cases then report
    UNMEASURED instead of a score.
    """
    _write_meta(tmp_path, "costs", {"x_a__mutmut_1": 1, "x_a__mutmut_2": 0})
    decoy = tmp_path / "decoy"
    decoy.write_text("an ordinary file that is not a truncation marker\n", encoding="utf-8")

    for label, value in (("a file with the wrong content", "decoy"), ("an empty setting", "")):
        result = _run(
            scope_script,
            tmp_path,
            "report",
            "origin/main",
            "90",
            env={"RUN_WITH_DEADLINE_MARKER": value},
        )
        assert "mutation score (killed / (killed+survived)) = 50.0%" in result.stdout, (
            f"{label} muted the score line:\n{result.stdout}"
        )

    # POSITIVE PARTNER: the wrapper's real sentinel IS recognised, so the two
    # negatives above are about the content and not about a dead code path.
    real = _run(
        scope_script, tmp_path, "report", "origin/main", "90", env=_mark_truncated(tmp_path)
    )
    assert "UNMEASURED" in real.stdout, real.stdout


def test_every_truncated_diagnosis_says_the_run_was_truncated(
    scope_script: Path, tmp_path: Path
) -> None:
    """mutmut runs its cheapest mutants first, and a no-tests mutant costs zero.

    So "the few mutants we reached were all no-tests" is a LIKELY shape for a
    real truncation, and that branch used to tell the author to add a test
    without ever mentioning that the budget had run out. The notice is printed
    once, above every diagnosis, so whichever one fires carries the context.

    Turns red if: the `if truncated:` notice after the counts line is removed —
    the no-tests diagnosis then names only a missing test.
    """
    _write_meta(tmp_path, "costs", {"x_a__mutmut_1": 33, "x_a__mutmut_2": 33})

    result = _run(
        scope_script, tmp_path, "report", "origin/main", "90", env=_mark_truncated(tmp_path)
    )
    output = result.stdout + result.stderr

    assert "TRUNCATED" in output, (
        f"a truncated run diagnosed as a pure no-tests gap, silently:\n{output}"
    )
    assert "NO covering test" in output, (
        f"the no-tests diagnosis was lost; it is still the right one:\n{output}"
    )
    assert result.returncode != 0, output


def test_an_all_timeout_truncated_run_keeps_the_all_timeout_diagnosis(
    scope_script: Path, tmp_path: Path
) -> None:
    """Both are true; "every mutant timed out" is the more specific one.

    A scope slow enough to time every mutant out is a scope slow enough to hit
    the wall clock, so this co-occurrence is realistic — `mutation-baseline.md`
    §5 measured a 24-33% timeout rate on this app. The first version of the fix
    put the truncated branch first and printed "before a single mutant was
    scored" over a run in which 66 mutants had timed out on the line above.

    Turns red if: the truncated branch is moved back above the timeout branch.
    """
    _write_meta(tmp_path, "costs", {f"x_a__mutmut_{i}": -24 for i in range(1, 67)})

    result = _run(
        scope_script, tmp_path, "report", "origin/main", "90", env=_mark_truncated(tmp_path)
    )
    output = result.stdout + result.stderr

    assert "every mutant 66 timed out" in output, (
        f"the truncation notice swallowed the true, more specific cause:\n{output}"
    )
    assert "before any mutant produced a kill-or-survive verdict" not in output, (
        f"66 mutants produced a verdict; the message says none did:\n{output}"
    )
    assert "TRUNCATED" in output, f"the truncation is still worth saying:\n{output}"
    assert result.returncode == 0, output


# --------------------------------------------------------------------------
# #337 — a truncated run states its DENOMINATOR, and #365 — the survivor
# verdict stops making a claim the gate cannot support.
# --------------------------------------------------------------------------


def _write_scope(cwd: Path, *globs: str) -> None:
    """The scope file the recipe writes before `mutmut run`, as `scope()` emits it.

    `scope()` emits TWO patterns per changed function: the suffixed
    `<mod>.<name>__mutmut_*`, which matches concrete mutant keys, and the
    companion `*<mod>.<name>` that ADR-0065 added to narrow mutmut's clean-test
    phase and which matches no mutant key at all. Both are written here so the
    denominator is exercised against the real file shape, not a tidied one.
    """
    scope = cwd / "build" / "mutation" / "scope.txt"
    scope.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for pattern in globs:
        lines.append(f"{pattern}__mutmut_*")
        lines.append(f"*{pattern}")
    scope.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_a_truncated_run_says_how_much_of_the_scope_it_reached(
    scope_script: Path, tmp_path: Path
) -> None:
    """#337. "252 of the scope's mutants" never said out of how many.

    That is the one number a reader acts on: 252 of 337 means the diff is
    mostly measured, 252 of 4000 means it is barely measured, and the gate
    printed the same sentence for both. The scope's total is on disk — the
    globs in `build/mutation/scope.txt` are exactly what was handed to
    `mutmut run` — so the denominator is derivable and was simply not derived.

    Ten mutants in scope, four of them reached (2 killed, 1 survived, 1
    timeout), six never started. The assertion pins all three numbers as
    literals so a percentage computed over the wrong base cannot pass.

    Turns red if: `in_scope`/`in_scope_reached` stop being counted, the
    `if in_scope:` branch is dropped, or the denominator is computed over ALL
    meta keys instead of the scope's — the last would report 4 of 12, since
    the out-of-scope module below contributes two more.
    """
    _write_scope(tmp_path, "product_app.costs.x_a")
    metas: dict[str, int | None] = {
        "product_app.costs.x_a__mutmut_1": 1,
        "product_app.costs.x_a__mutmut_2": 1,
        "product_app.costs.x_a__mutmut_3": 0,
        "product_app.costs.x_a__mutmut_4": -24,
    }
    metas.update({f"product_app.costs.x_a__mutmut_{i}": None for i in range(5, 11)})
    _write_meta(tmp_path, "costs", metas)
    # A module the diff never touched. Its mutants are NOT in scope and must not
    # move the denominator — without this the test cannot tell a scope-filtered
    # count from a count of every key on disk.
    _write_meta(
        tmp_path,
        "query_runs",
        {
            "product_app.query_runs.x_z__mutmut_1": None,
            "product_app.query_runs.x_z__mutmut_2": None,
        },
    )

    result = _run(
        scope_script, tmp_path, "report", "origin/main", "90", env=_mark_truncated(tmp_path)
    )
    output = result.stdout + result.stderr

    assert "reached 4 of the scope's 10 mutants (40% of the scope)" in output, (
        f"the truncated run did not state its denominator:\n{output}"
    )
    assert "scored 3 of those" in output, (
        f"killed + survived is 3; the scored count is wrong:\n{output}"
    )
    assert "mutation score" not in output, f"a prefix must not print a percentage:\n{output}"
    assert result.returncode != 0, f"the survivor must still fail the gate:\n{output}"

    # POSITIVE PARTNER. Without a scope file there is no denominator to state,
    # and the pre-#337 sentence must come back rather than a "0 of 0" or a
    # crash. Also proves the assertions above are measuring the scope file and
    # not simply the presence of a truncation marker.
    (tmp_path / "build" / "mutation" / "scope.txt").unlink()
    fallback = _run(
        scope_script, tmp_path, "report", "origin/main", "90", env=_mark_truncated(tmp_path)
    )
    fallback_output = fallback.stdout + fallback.stderr
    assert "after scoring 3 of the scope's mutants" in fallback_output, (
        "with no scope file the gate must fall back to its pre-#337 wording, "
        f"not invent a denominator:\n{fallback_output}"
    )
    assert "of the scope)" not in fallback_output, (
        f"a percentage was reported with no scope to compute it over:\n{fallback_output}"
    )


def test_an_unreadable_scope_file_cannot_stop_the_gate_reporting(
    scope_script: Path, tmp_path: Path
) -> None:
    """The denominator is a REPORTING improvement and must never become a new
    way for the gate to die.

    A directory where `scope.txt` should be is the cheapest way to make the
    read raise something other than "missing file" — `open()` on it raises
    `IsADirectoryError`, a subclass of `OSError`. This is the same failure mode
    ADR-0065 records for the truncation marker, where an unhandled write turned
    a kill into an orphaned worker group.

    Turns red if: the `try/except OSError` around the scope read is removed —
    the script then dies with a traceback and prints no counts at all.
    """
    scope = tmp_path / "build" / "mutation" / "scope.txt"
    scope.mkdir(parents=True)
    _write_meta(tmp_path, "costs", {"x_a__mutmut_1": 1, "x_a__mutmut_2": 0})

    result = _run(scope_script, tmp_path, "report", "origin/main", "90")
    output = result.stdout + result.stderr

    assert "mutants scored: 1 killed, 1 survived" in output, (
        f"an unreadable scope file stopped the gate reporting at all:\n{output}"
    )
    assert "Traceback" not in output, f"the scope read was not fail-soft:\n{output}"
    assert "mutation score (killed / (killed+survived)) = 50.0%" in output, (
        f"the complete-run path must still score normally:\n{output}"
    )


def test_the_survivor_verdict_does_not_claim_every_survivor_is_a_test_gap(
    scope_script: Path, tmp_path: Path
) -> None:
    """#365. The message used to assert something it cannot know.

    It read "a survivor is a test gap that was DEMONSTRATED". That is universal
    and it is false for an EQUIVALENT mutant, which no test can kill — two
    existed in `_stance_majority_flags` and left the job with no path to green.
    The gate reads a `.meta` file of exit codes and never sees source, so it
    cannot tell a missing test from an equivalent mutant; it now names both and
    still fails, because both need a human.

    **This test pins PROSE and cannot see whether the prose is true.** It is a
    substring assertion of the kind AGENTS.md rule 8 warns about, kept because
    the change here IS the wording — the exit status is deliberately unchanged,
    so there is no structural difference to assert on. Its whole value is
    stopping the universal claim coming back by accident.

    Turns red if: the verdict goes back to asserting every survivor is a
    demonstrated test gap.
    """
    _write_meta(tmp_path, "costs", {"x_a__mutmut_1": 1, "x_a__mutmut_2": 0})

    result = _run(
        scope_script, tmp_path, "report", "origin/main", "90", env=_mark_truncated(tmp_path)
    )
    output = result.stdout + result.stderr

    # The behaviour that must NOT change: a survivor still fails the gate.
    assert result.returncode != 0, f"softening the wording must not soften the verdict:\n{output}"
    assert "1 mutant(s) SURVIVED before the cut-off" in output, output

    assert "test gap that was DEMONSTRATED" not in output, (
        "the gate is again asserting that every survivor is a demonstrated "
        f"test gap, which is false for an equivalent mutant:\n{output}"
    )
    # POSITIVE PARTNER for that negative: the replacement text must actually be
    # present. Without this the assertion above passes over any rewording at
    # all, including one that deletes the guidance entirely.
    assert "EQUIVALENT" in output and "no test can kill it" in output, (
        f"the verdict no longer names the equivalent-mutant case:\n{output}"
    )


def test_the_two_numbers_in_the_truncation_line_come_from_one_population(
    scope_script: Path, tmp_path: Path
) -> None:
    """Found by adversarial review of the #337 denominator, before it shipped.

    The first version mixed populations: the "reached N of M" half was
    scope-filtered and the "scored K" half was `checked`, which counts every
    scored key on disk. Over a `mutants/` tree holding a scored key that matches
    no scope glob, that printed the self-contradiction ``reached 0 of the
    scope's 10 mutants (0% of the scope) and scored 2 of those`` — a number a
    reader would act wrongly on, which is the exact defect this denominator was
    added to remove.

    Ten mutants in scope, NONE of them reached. A different module contributes
    one killed and one survived. The scoped line must therefore say 0 and 0.

    Turns red if: the `scored` half goes back to `checked` — it then reads
    ``scored 2 of those`` after ``reached 0``.
    """
    _write_scope(tmp_path, "product_app.costs.x_a")
    _write_meta(
        tmp_path,
        "costs",
        {f"product_app.costs.x_a__mutmut_{i}": None for i in range(1, 11)},
    )
    _write_meta(
        tmp_path,
        "query_runs",
        {
            "product_app.query_runs.x_z__mutmut_1": 1,
            "product_app.query_runs.x_z__mutmut_2": 0,
        },
    )

    result = _run(
        scope_script, tmp_path, "report", "origin/main", "90", env=_mark_truncated(tmp_path)
    )
    output = result.stdout + result.stderr

    assert "reached 0 of the scope's 10 mutants (0% of the scope)" in output, output
    assert "scored 0 of those" in output, (
        "the 'scored' half is counting mutants from outside the scope, so the "
        f"sentence contradicts itself:\n{output}"
    )
    # POSITIVE PARTNER: the out-of-scope survivor is still a survivor and must
    # still fail the gate. Without this, "scored 0" would also be satisfied by a
    # report() that had stopped counting survivors at all.
    assert result.returncode != 0, (
        f"a survivor stopped failing the gate once it fell outside the scope:\n{output}"
    )
    assert "SURVIVED product_app.query_runs.x_z__mutmut_2" in output, output
