"""The mutation gate must actually be able to fail once it is promoted.

`mutation-baseline` is ADVISORY today: the leading `-` on the recipe (and
`continue-on-error: true` on the CI job) swallow a below-threshold score on
purpose. The hazard is what happens on promotion day — if the scoring step's
exit status is thrown away *inside* the recipe (e.g. piped into `tee`, whose
own 0 becomes the pipeline status under make's `/bin/sh`, which has no
`pipefail`), then removing the `-` yields a permanently-green "blocking" gate.

So this exercises the promotion path directly: the shipped recipe text, with
the advisory `-` stripped and the two expensive steps stubbed, must exit
non-zero when the report step exits non-zero.
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


def _stubbed_makefile(tmp_path: Path, *, promote: bool) -> Path:
    """The shipped recipe with the costly steps stubbed, optionally promoted to
    blocking (i.e. with the advisory `-` deleted, as the comment instructs)."""
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
    if promote:
        # Promotion: drop the leading `-` that makes the gate advisory.
        body, dropped = re.subn(r"^\t-", "\t", body, flags=re.MULTILINE)
        assert dropped == 1, "expected exactly one advisory `-` in the recipe"

    makefile = tmp_path / "Makefile"
    makefile.write_text("mutation-baseline:\n" + body + "\n", encoding="utf-8")
    return makefile


def test_promoted_mutation_gate_fails_on_a_below_threshold_score(tmp_path: Path) -> None:
    _stubbed_makefile(tmp_path, promote=True)
    env = {**os.environ, "MUTMUT_SCOPE_PY": "# stubbed"}
    result = subprocess.run(
        ["make", "mutation-baseline"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "BELOW THRESHOLD" in result.stdout, result.stdout + result.stderr
    assert result.returncode != 0, (
        "mutation-baseline scored BELOW THRESHOLD yet the recipe exited 0 — "
        "the report step's exit status is being discarded (a pipe into `tee` "
        "under /bin/sh has no pipefail), so deleting the advisory `-` would "
        f"produce a permanently-green blocking gate:\n{result.stdout}{result.stderr}"
    )


def test_advisory_mutation_gate_still_reports_and_survives(tmp_path: Path) -> None:
    """Until promotion the same failure must stay non-fatal, and the score file
    must still be written for the CI artifact upload."""
    body = _recipe("mutation-baseline", MAKEFILE.read_text(encoding="utf-8"))
    assert re.search(r"^\t-", body, flags=re.MULTILINE), (
        "mutation-baseline lost its advisory `-`; if that was deliberate, drop "
        "`continue-on-error: true` from the CI job too and delete this test"
    )

    _stubbed_makefile(tmp_path, promote=False)
    env = {**os.environ, "MUTMUT_SCOPE_PY": "# stubbed"}
    result = subprocess.run(
        ["make", "mutation-baseline"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    score = tmp_path / "build" / "mutation" / "score.txt"
    assert score.exists(), "build/mutation/score.txt was not written"
    assert "BELOW THRESHOLD" in score.read_text(encoding="utf-8")
