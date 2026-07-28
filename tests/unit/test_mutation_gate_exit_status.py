"""The mutation gate must actually be able to fail, and still leave an artifact.

`mutation-baseline` BLOCKS since #130. Until then the leading `-` on the recipe
(and `continue-on-error: true` on the CI job) swallowed a below-threshold score
on purpose, and this module existed to prove the promotion *would* work. It now
proves the shipped recipe *does* work: if the scoring step's exit status is
thrown away inside the recipe (e.g. piped into `tee`, whose own 0 becomes the
pipeline status under make's `/bin/sh`, which has no `pipefail`), the gate is
permanently green while calling itself blocking.

The second property matters just as much and is easy to lose when a gate is
made to fail: the recipe must still WRITE `build/mutation/score.txt` on the
failing path, or CI's artifact upload has nothing to upload and the author of a
red gate cannot see which mutants survived.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"

# Stands in for $(PYTHON): emits one in-scope function for `scope`, and fails
# the way report() does for a below-threshold score.
STUB_PYTHON = """#!/bin/sh
cat >/dev/null
[ "$1" = "-" ] && shift    # the recipe feeds the program on stdin: `python - <mode>`
case "$1" in
  scope) echo "product_app.demo.x_demo__mutmut_*" ;;
  report) echo "mutation score = 40.0% (threshold 90%)"; echo "BELOW THRESHOLD"; exit 1 ;;
esac
"""


def _recipe(name: str, text: str) -> str:
    """The recipe body of `name`, verbatim (tab-indented lines after the rule)."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}:"))
    body = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        body.append(line)
    return "\n".join(body)


def _stubbed_makefile(tmp_path: Path, *, demote: bool = False) -> Path:
    """The shipped recipe with the costly steps stubbed.

    ``demote`` puts the advisory ``-`` back, which is only used to prove the
    harness can go green — otherwise a harness that fails unconditionally would
    look like a working gate.
    """
    body = _recipe("mutation-baseline", MAKEFILE.read_text(encoding="utf-8"))
    assert "report" in body, "mutation-baseline no longer runs the report step"

    stub = tmp_path / "stub-python"
    stub.write_text(STUB_PYTHON, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    # Expand the handful of variables the recipe reads; mutmut itself is the one
    # step we cannot afford to run, so it becomes a no-op.
    body = body.replace("$(PYTHON)", str(stub))
    body = body.replace("uv run mutmut run", "true mutmut-stubbed")
    body = re.sub(r"\$\([A-Z_]+\)", "stub", body)
    assert "mutmut-stubbed" in body, "the mutmut invocation moved; it must stay stubbed"
    if demote:
        # Put the advisory `-` back on the work branch, as it was before #130.
        body, added = re.subn(r"^\t@if ", "\t-@if ", body, count=1, flags=re.MULTILINE)
        assert added == 1, "could not re-add the advisory `-`; the recipe has been restructured"

    makefile = tmp_path / "Makefile"
    makefile.write_text("mutation-baseline:\n" + body + "\n", encoding="utf-8")
    return makefile


def _make(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", "mutation-baseline"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**os.environ, "MUTMUT_SCOPE_PY": "# stubbed"},
    )


def test_the_shipped_gate_fails_on_a_below_threshold_score(tmp_path: Path) -> None:
    """Turns red if: the advisory `-` returns, or the report's status is piped away."""
    _stubbed_makefile(tmp_path)
    result = _make(tmp_path)
    assert "BELOW THRESHOLD" in result.stdout, result.stdout + result.stderr
    assert result.returncode != 0, (
        "mutation-baseline scored BELOW THRESHOLD yet the recipe exited 0 — "
        "the report step's exit status is being discarded (a pipe into `tee` "
        "under /bin/sh has no pipefail), so the gate calls itself blocking "
        f"while being permanently green:\n{result.stdout}{result.stderr}"
    )


def test_the_score_file_survives_a_failing_gate(tmp_path: Path) -> None:
    """A red gate must still leave the artifact that explains WHY it is red.

    The recipe redirects the report into `build/mutation/score.txt` and only
    then exits with its status. Reordering that — exiting before the redirect
    completes, or writing only on success — leaves CI's `Upload mutation
    report` step with nothing and the author with no survivor list.

    Turns red if: the recipe is changed to exit on the report's status before
    writing score.txt.
    """
    _stubbed_makefile(tmp_path)
    result = _make(tmp_path)
    assert result.returncode != 0, "expected the below-threshold stub to fail the gate"
    score = tmp_path / "build" / "mutation" / "score.txt"
    assert score.exists(), "build/mutation/score.txt was not written on the failing path"
    assert "BELOW THRESHOLD" in score.read_text(encoding="utf-8")


def test_the_harness_can_go_green(tmp_path: Path) -> None:
    """Positive partner: a harness that always fails proves nothing above.

    Putting the pre-#130 advisory `-` back must make the identical run pass, so
    the two assertions above are measuring the recipe rather than a broken stub
    or a missing `make`.

    Turns red if: the stub, PATH, or variable expansion breaks so the recipe
    fails for a reason unrelated to the gate.
    """
    _stubbed_makefile(tmp_path, demote=True)
    result = _make(tmp_path)
    assert result.returncode == 0, (
        "the advisory form ALSO fails, so the blocking assertions above are "
        f"not measuring the `-`:\n{result.stdout}{result.stderr}"
    )
