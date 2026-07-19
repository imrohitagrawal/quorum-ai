"""Proves the mutation gate's *promotion path* actually blocks.

`test_mutation_gate_integrity.py` covers the scoring logic going green while
measuring nothing. This module covers the one thing nothing else executes: the
Makefile comment promises that deleting the leading `-` from the
`mutation-baseline` recipe on $(MUTATION_ADVISORY_UNTIL) turns the gate
blocking, "the report step already exits non-zero below threshold". That is a
claim about *shell exit-status plumbing*, and it is only true if the report
step's status is the one make sees.

The fail-open shape found in review was:

    ... | $(PYTHON) - report ... | tee build/mutation/score.txt

`tee` is the last command of the pipeline, so make sees tee's 0 no matter what
the report exits with. Delete the `-` on 2026-08-02 and you get a gate that is
green at any mutation score, forever, silently. The status-preserving shape is
`> build/mutation/score.txt; status=$?; cat ...; exit $status`.

So this asserts by *execution*: the real recipe is lifted out of the Makefile,
promoted (leading `-` removed) exactly as the comment instructs, pointed at a
stub report that fails, and make must exit non-zero. `_run_promoted_recipe`
takes the Makefile text as an argument so the same harness can be pointed at a
mutated recipe to show it red.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"

TARGET = "mutation-baseline:"

# The stub stands in for $(PYTHON): `scope` yields one in-scope function so the
# recipe takes its work branch, `report` fails the way a below-threshold run does.
# The recipe invokes it as `$(PYTHON) - <mode> ...`, where `-` means "script on
# stdin"; the stub is a real file, so it drops that leading argument itself.
STUB_PY = """\
import sys

sys.stdin.read()
args = [arg for arg in sys.argv[1:] if arg != "-"]
if args[0] == "scope":
    print("product_app.stub.x_f__mutmut_*")
else:
    print("mutation score = 10.0% (threshold 90%)")
    print("BELOW THRESHOLD")
    raise SystemExit(1)
"""


def recipe_lines(makefile_text: str) -> list[str]:
    lines = makefile_text.splitlines()
    start = lines.index(TARGET) + 1
    end = start
    while end < len(lines) and lines[end].startswith("\t"):
        end += 1
    body = lines[start:end]
    assert body, "mutation-baseline recipe body not found in the Makefile"
    return body


def _run_promoted_recipe(makefile_text: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Run the recipe with the leading `-` deleted, against a failing report."""
    body = recipe_lines(makefile_text)
    assert any(line.startswith("\t-") for line in body), (
        "no `-`-prefixed line in the recipe — it is either already blocking or "
        f"has been restructured; this harness no longer models it:\n{body}"
    )
    promoted = [re.sub(r"^\t-", "\t", line) for line in body]

    (tmp_path / "stub.py").write_text(STUB_PY, encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub_python = bin_dir / "stub-python"
    stub_python.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{tmp_path}/stub.py" "$@"\n', encoding="utf-8"
    )
    stub_python.chmod(0o755)
    # `uv run mutmut run ...` must succeed so control reaches the report step.
    uv = bin_dir / "uv"
    uv.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    uv.chmod(0o755)

    makefile = tmp_path / "Makefile"
    makefile.write_text(
        "DIFF_BASE ?= origin/main\n"
        "MUTATION_MIN_SCORE ?= 90\n"
        "MUTATION_ADVISORY_UNTIL ?= 2026-08-02\n"
        "MUTMUT_PATHS ?= src/product_app\n"
        "MUTMUT_MAX_CHILDREN ?= 8\n"
        "UV_CACHE_DIR ?= .uv-cache\n"
        "export MUTMUT_SCOPE_PY\n"
        f"{TARGET}\n" + "\n".join(promoted) + "\n",
        encoding="utf-8",
    )
    return subprocess.run(
        ["make", "--no-print-directory", "mutation-baseline", f"PYTHON={stub_python}"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "MUTMUT_SCOPE_PY": "unused-by-the-stub"},
    )


def test_promoting_the_recipe_makes_a_below_threshold_run_fail(tmp_path: Path) -> None:
    result = _run_promoted_recipe(MAKEFILE.read_text(encoding="utf-8"), tmp_path)
    assert "BELOW THRESHOLD" in result.stdout, (
        "the report step never ran; the harness is not exercising the gate:\n"
        f"{result.stdout}{result.stderr}"
    )
    assert result.returncode != 0, (
        "the recipe exits 0 with the `-` deleted and a below-threshold report — "
        "promoting the gate on MUTATION_ADVISORY_UNTIL would enforce nothing:\n"
        f"{result.stdout}{result.stderr}"
    )


def test_report_step_status_is_not_swallowed_by_a_pipe() -> None:
    """Static twin of the above: the report must not end a pipeline it doesn't own."""
    body = "\n".join(recipe_lines(MAKEFILE.read_text(encoding="utf-8")))
    report = re.search(r"- report .*?(?=;)", body, re.DOTALL)
    assert report, f"no `report` invocation in the recipe:\n{body}"
    assert "|" not in report.group(0), (
        "the report's exit status is discarded by a downstream pipe stage "
        f"(tee/cat): {report.group(0)}"
    )


def test_recipe_is_still_advisory_until_the_locked_date() -> None:
    """The `-` is the advisory switch; it may only go with a re-measured decision."""
    body = recipe_lines(MAKEFILE.read_text(encoding="utf-8"))
    assert any(line.startswith("\t-") for line in body), (
        "the mutation gate has been promoted to blocking — that is a locked "
        "decision (MUTATION_ADVISORY_UNTIL) and needs a recorded re-measurement"
    )
