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

import json
import os
import re
import subprocess
import sys
from pathlib import Path

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


def _run(script: Path, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
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
