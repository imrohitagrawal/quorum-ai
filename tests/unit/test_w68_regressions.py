"""W68 round 1 review: regressions for the holes the reviewers reproduced.

1. A stale ``uv.lock`` passed both new gates. CI's install steps ran ``uv
   sync`` without ``--locked``, which rewrites a stale lock on the runner, so
   CI audited and built a set the committed lock did not pin, while
   production (``uv sync --frozen``) built the committed lock.
2. ``scripts/vuln_audit.py`` passed when pip-audit skipped a package, or
   audited fewer packages than the image holds.
3. ``scripts/check_image_matches_lock.py`` collapsed two installed versions
   of one distribution into one, and allowed pip, setuptools and wheel as
   unreported extras.
4. Nothing stopped the Makefile recipes from being made unable to fail.
5. Argument pins the first tests left loose, and a marker test that could
   only bite on a non-Linux host.

Subprocesses go through each script's injected ``run`` argument: no test
here needs ``uv``, pip-audit, Docker or the network.

WHAT TURNS THIS FILE RED: drop ``--locked`` from a workflow ``uv sync``;
let ``vuln_audit.main`` pass with a skipped or missing package; let
``check_image_matches_lock.main`` pass with a duplicate distribution; add
``|| true`` or a leading ``-`` to a gate recipe; or evaluate markers with the
host's environment.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shlex
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import packaging.markers
import pytest
import yaml
from tests.code_text import code_without_comments
from tests.repo_root import find_repo_root

ROOT = find_repo_root(Path(__file__))
WORKFLOWS = ROOT / ".github" / "workflows"
MAKEFILE = ROOT / "Makefile"


def _load(script: str) -> ModuleType:
    path = ROOT / "scripts" / script
    spec = importlib.util.spec_from_file_location(f"w68_regressions_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class _Done:
    returncode: int
    stdout: str
    stderr: str = ""


class _FakeRun:
    """``uv`` gets ``first``; ``uvx`` or ``docker`` gets ``second``."""

    def __init__(self, first: _Done, second: _Done | None = None) -> None:
        self.first = first
        self.second = second
        self.calls: list[list[str]] = []

    def __call__(self, command: Sequence[object], **_kwargs: object) -> _Done:
        argv = [str(a) for a in command]
        self.calls.append(argv)
        if Path(argv[0]).name == "uv":
            return self.first
        assert Path(argv[0]).name in ("uvx", "docker"), argv
        assert self.second is not None, argv
        return self.second

    def tool(self, name: str) -> list[list[str]]:
        return [c for c in self.calls if Path(c[0]).name == name]


# ---------------------------------------------------------------------------
# 1. Every workflow install refuses a stale lock
# ---------------------------------------------------------------------------


def _uv_sync_commands() -> list[tuple[str, str, str, list[str]]]:
    """``(workflow file, job, step name, argv)`` for every ``uv sync`` command
    in a step's ``run``, one per shell line, comment lines skipped."""
    found = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in (workflow.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                script = str(step.get("run", "")).replace("\\\n", " ")
                for line in script.splitlines():
                    if "uv" not in line or "sync" not in line or line.strip().startswith("#"):
                        continue
                    words = shlex.split(line, comments=True)
                    pairs = list(zip(words, words[1:], strict=False))
                    if ("uv", "sync") in pairs:
                        found.append((path.name, job_name, str(step.get("name", "")), words))
    return found


def test_every_workflow_uv_sync_refuses_a_stale_lock() -> None:
    """Red when: any ``uv sync`` in any workflow step lacks ``--locked`` (or
    ``--frozen``). Without it uv rewrites a stale lock on the runner, so CI
    tests, audits and builds a set the committed lock does not pin, while the
    deploy builds the committed lock (round 1 break-it repro: a lock pinning
    anyio 4.14.0 and urllib3 2.7.0 passed both gates)."""
    commands = _uv_sync_commands()
    loose = [(f, j, s, w) for f, j, s, w in commands if not {"--locked", "--frozen"} & set(w)]
    assert loose == [], loose


def test_partner_the_validate_and_test_install_step_is_one_of_the_uv_sync_commands() -> None:
    """Partner: the scan above finds the commands it judges. Red when: the
    parser finds no ``uv sync`` at all, or misses ``validate-and-test``'s
    ``Install dependencies`` step (the job holding both W68 gates), or that
    step lacks ``--locked``."""
    commands = _uv_sync_commands()
    assert len(commands) >= 1, commands
    install = [
        w
        for f, j, s, w in commands
        if (f, j, s) == ("ci.yml", "validate-and-test", "Install dependencies")
    ]
    assert len(install) == 1, commands
    assert "--locked" in install[0], install


# ---------------------------------------------------------------------------
# 2. vuln_audit refuses a skipped or missing package
# ---------------------------------------------------------------------------

_EXPORT = """\
# This file was autogenerated by uv via the following command:
#    uv export --frozen --no-dev --no-emit-project --no-hashes
anyio==4.14.2 ; python_full_version < '3.15'
anyio==4.15.1 ; python_full_version >= '3.15'
colorama==0.4.6 ; sys_platform == 'win32'
linux-only==1.0 ; sys_platform == 'linux'
"""


def _report(deps: list[dict[str, Any]]) -> _Done:
    return _Done(0, json.dumps({"dependencies": deps, "fixes": []}))


def _clean(name: str, version: str) -> dict[str, Any]:
    return {"name": name, "version": version, "vulns": []}


def _skip(name: str) -> dict[str, Any]:
    return {"name": name, "skip_reason": "Dependency not found on PyPI and could not be audited"}


def _audit(export: str, deps: list[dict[str, Any]]) -> tuple[int, _FakeRun]:
    fake = _FakeRun(_Done(0, export), _report(deps))
    code = _load("vuln_audit.py").main([], run=fake)
    return code, fake


def test_vuln_audit_full_coverage_passes(capsys: pytest.CaptureFixture[str]) -> None:
    """Partner for the refusals below. Red when: an audit that covered
    exactly the two lines that apply to the Linux CPython 3.12 image (not the
    win32 or Python 3.15 lines) does not exit 0, or the first line does not
    report 4 exported lines and 2 that apply."""
    code, _ = _audit(_EXPORT, [_clean("anyio", "4.14.2"), _clean("linux-only", "1.0")])
    out = capsys.readouterr().out
    assert code == 0, out
    first = "vuln-audit: exported 4 pinned lines, 2 apply to the image (Linux, CPython 3.12)"
    assert out.splitlines()[0] == first, out


def test_vuln_audit_refuses_when_every_package_is_skipped(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Red when: a report where pip-audit skipped every package does not
    exit 2 with "refusing"."""
    code, _ = _audit(_EXPORT, [_skip("anyio"), _skip("linux-only")])
    captured = capsys.readouterr()
    assert code == 2, captured.out
    assert "refusing" in captured.err, captured.err


def test_vuln_audit_refuses_one_skipped_and_one_clean(capsys: pytest.CaptureFixture[str]) -> None:
    """Red when: one clean package and one skipped package pass. This is the
    reproduced hole: the first version exited 0 here, because it only refused
    when NOTHING was audited."""
    code, _ = _audit(_EXPORT, [_clean("anyio", "4.14.2"), _skip("linux-only")])
    captured = capsys.readouterr()
    assert code == 2, captured.out
    assert "vuln-audit: skipped linux-only" in captured.out, captured.out


def test_vuln_audit_refuses_a_skipped_entry_even_when_the_set_is_covered(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Red when: a skipped entry is ignored as long as every expected package
    was audited (so the skip check is not dead code behind the set check)."""
    deps = [_clean("anyio", "4.14.2"), _clean("linux-only", "1.0"), _skip("something-else")]
    code, _ = _audit(_EXPORT, deps)
    captured = capsys.readouterr()
    assert code == 2, captured.out


def test_vuln_audit_refuses_when_a_package_the_image_holds_was_not_audited(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Red when: pip-audit leaving out a line that applies to the Linux image
    (here ``sys_platform == 'linux'``, which a Mac run of pip-audit drops by
    its own marker evaluation) passes, or the missing package is not named."""
    code, _ = _audit(_EXPORT, [_clean("anyio", "4.14.2")])
    captured = capsys.readouterr()
    assert code == 2, captured.out
    assert "vuln-audit: not audited: linux-only==1.0" in captured.out.splitlines(), captured.out


def test_vuln_audit_argv_is_strict_python_312_and_uses_a_fresh_cache(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Red when: pip-audit is not run with ``--python 3.12`` right after
    ``--python``, without ``--strict``, or without ``--cache-dir`` pointing
    inside the same fresh temporary folder as the requirements file (a warm
    shared cache let an offline run exit 0 in round 1)."""
    _, fake = _audit(_EXPORT, [_clean("anyio", "4.14.2"), _clean("linux-only", "1.0")])
    capsys.readouterr()
    [argv] = fake.tool("uvx")
    assert argv[argv.index("--python") + 1] == "3.12", argv
    assert "--strict" in argv, argv
    cache = Path(argv[argv.index("--cache-dir") + 1])
    requirements = Path(argv[argv.index("-r") + 1])
    assert cache.parent == requirements.parent, argv
    assert not cache.parent.exists(), "the temporary folder should be gone after the run"


# ---------------------------------------------------------------------------
# 3. check_image_matches_lock refuses a duplicate distribution
# ---------------------------------------------------------------------------

_LOCKED = "anyio==4.14.2\nurllib3==2.8.0\n"


@pytest.mark.parametrize(
    "listing",
    [
        "anyio==4.14.2\nurllib3==2.7.0\nurllib3==2.8.0\n",
        "anyio==4.14.2\nurllib3==2.8.0\nurllib3==2.7.0\n",
    ],
    ids=["vulnerable-first", "locked-first"],
)
def test_image_check_refuses_a_distribution_installed_twice(
    listing: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Red when: an image listing urllib3 twice (2.7.0 and 2.8.0) passes, in
    either order, or the printed difference does not name urllib3 with both
    versions. In the ``vulnerable-first`` order a dict keeps the locked 2.8.0,
    so only a duplicate check can see it; Python may import the other one."""
    fake = _FakeRun(_Done(0, _LOCKED), _Done(0, listing))
    code = _load("check_image_matches_lock.py").main(["--image", "t"], run=fake)
    out = capsys.readouterr().out
    assert code == 1, out
    rows = [ln for ln in out.splitlines() if "more than once" in ln]
    assert len(rows) == 1 and "urllib3" in rows[0], out
    assert "2.7.0" in rows[0] and "2.8.0" in rows[0], out


def test_image_check_pins_pull_never(capsys: pytest.CaptureFixture[str]) -> None:
    """Red when: ``docker run`` lacks ``--pull never`` (as a pair), so a
    missing local tag could be pulled from a registry and checked instead."""
    fake = _FakeRun(_Done(0, _LOCKED), _Done(0, _LOCKED))
    _load("check_image_matches_lock.py").main(["--image", "t"], run=fake)
    capsys.readouterr()
    [argv] = fake.tool("docker")
    assert argv[argv.index("--pull") + 1] == "never", argv


# ---------------------------------------------------------------------------
# 5. Markers are evaluated for the image even on a Linux host
# ---------------------------------------------------------------------------


def test_parse_pins_ignores_the_host_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Red when: ``parse_pins(text)`` with no ``env`` evaluates markers with
    the host's environment. The host is faked as macOS on arm64, so this
    bites on a Linux CI runner too, where the host and image agree."""
    darwin = {
        "implementation_name": "cpython",
        "implementation_version": "3.12.13",
        "os_name": "posix",
        "platform_machine": "arm64",
        "platform_release": "25.6.0",
        "platform_system": "Darwin",
        "platform_version": "Darwin Kernel Version 25.6.0",
        "python_full_version": "3.12.13",
        "platform_python_implementation": "CPython",
        "python_version": "3.12",
        "sys_platform": "darwin",
    }
    monkeypatch.setattr(packaging.markers, "default_environment", lambda: dict(darwin))
    text = "linux-only==1.0 ; sys_platform == 'linux'\nmac-only==1.0 ; sys_platform == 'darwin'\n"
    assert _load("check_image_matches_lock.py").parse_pins(text) == {"linux-only": "1.0"}


# ---------------------------------------------------------------------------
# 4. The gate recipes can fail
# ---------------------------------------------------------------------------

_SWALLOW = re.compile(r"\|\|\s*(?:true|:|exit\s+0)(?=\s|;|\)|$)|;\s*true(?=\s|;|\)|$)")


def _recipe_lines(target: str) -> list[str]:
    lines = code_without_comments(MAKEFILE).splitlines()
    starts = [i for i, line in enumerate(lines) if re.match(rf"^{re.escape(target)}\s*:", line)]
    assert len(starts) == 1, (target, starts)
    recipe = []
    for line in lines[starts[0] + 1 :]:
        if not line.startswith("\t"):
            break
        if line.strip():
            recipe.append(line[1:])
    return recipe


@pytest.mark.parametrize(
    ("target", "command"),
    [
        ("vuln-audit", "scripts/vuln_audit.py"),
        ("image-lock-check", "scripts/check_image_matches_lock.py"),
        ("docker-build", "docker build"),
    ],
)
def test_gate_recipes_cannot_swallow_a_failure(target: str, command: str) -> None:
    """Red when: a line of the ``vuln-audit``, ``image-lock-check`` or
    ``docker-build`` recipe starts with ``-`` (make ignores its exit status,
    including as ``@-`` or ``-@``) or ends a command with ``|| true``,
    ``|| :``, ``; true`` or ``|| exit 0``. Each would let the CI step pass on
    a finding while every other test stays green. Partner: the recipe exists
    and runs ``command``."""
    recipe = _recipe_lines(target)
    assert any(command in line for line in recipe), recipe
    for line in recipe:
        prefix = re.match(r"[@+\-\s]*", line)
        assert prefix is not None and "-" not in prefix.group(0), line
        assert not _SWALLOW.search(line), line


@pytest.mark.parametrize(
    "line",
    [
        "uv run python x.py || true",
        "uv run python x.py ||true",
        "uv run python x.py || :",
        "uv run python x.py; true",
        "uv run python x.py || exit 0",
    ],
)
def test_partner_the_swallow_pattern_matches_each_shape(line: str) -> None:
    """Partner: the pattern above recognises every shape it is meant to
    refuse. Red when: one of these lines does not match."""
    assert _SWALLOW.search(line), line


def test_partner_the_swallow_pattern_leaves_a_plain_command_alone() -> None:
    """Partner: ``|| exit 1`` and ``truecolor`` are not swallowing a failure.
    Red when: the pattern matches them (it would fail the real recipes)."""
    assert not _SWALLOW.search("cmd || exit 1")
    assert not _SWALLOW.search("cmd --theme=truecolor; true_thing")
