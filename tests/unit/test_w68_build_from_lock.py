"""W68: production is built from ``uv.lock``, and CI checks the lock for known
vulnerabilities and the image against the lock.

Findings S3 and S4 of ``docs/analysis/2026-10-13-security-review.md``:

* S4: ``Dockerfile`` ran ``uv pip install ... .``, which resolves from the
  version ranges in ``pyproject.toml`` and ignores ``uv.lock``. CI's
  docker-build log for run 38408508822 installs sentry-sdk 2.72.0, anyio
  4.15.1 and urllib3 2.8.0 while ``uv.lock`` pins 2.63.0, 4.14.0 and 2.7.0, so
  production ran versions CI never tested.
* S3: the locked anyio 4.14.0 and urllib3 2.7.0 carry six known
  vulnerabilities (fixed in 4.14.2 and 2.8.0), and no CI job audits libraries.

This file pins the repository files: the Dockerfile, ``uv.lock``, the CI
workflow and the Makefile. Each is PARSED (Dockerfile instructions with
continuations joined and comments dropped; TOML; YAML; Makefile recipes with
comments blanked), never searched as one string, so a comment that mentions a
flag cannot satisfy a test.

The two scripts' behaviour is pinned in ``test_w68_vuln_audit.py`` and
``test_w68_image_matches_lock.py``.

WHAT TURNS THIS FILE RED: put ``uv pip install`` back in the Dockerfile, drop
``--frozen`` from its ``uv sync``, lower anyio or urllib3 in ``uv.lock`` below
the fixed versions, or remove the ``make vuln-audit`` / ``make
image-lock-check`` steps from the ``validate-and-test`` job.
"""

from __future__ import annotations

import re
import shlex
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml
from packaging.version import Version
from tests.code_text import code_without_comments
from tests.repo_root import find_repo_root

pytestmark = pytest.mark.repo_introspection

ROOT = find_repo_root(Path(__file__))
DOCKERFILE = ROOT / "Dockerfile"
LOCK = ROOT / "uv.lock"
CI = ROOT / ".github" / "workflows" / "ci.yml"
MAKEFILE = ROOT / "Makefile"

_ASSIGNMENT = re.compile(r"[A-Z_][A-Z0-9_]*=.*")


# ---------------------------------------------------------------------------
# Dockerfile parsing (same rules as test_w54_dockerfile_compiles_bytecode.py)
# ---------------------------------------------------------------------------


def _instructions(text: str) -> list[tuple[str, str]]:
    """``(KEYWORD, arguments)`` per instruction, continuations joined, comment
    lines dropped as Docker drops them (even inside a continuation)."""
    out: list[tuple[str, str]] = []
    pending = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        whole = (pending + line).strip()
        pending = ""
        keyword, _, arguments = whole.partition(" ")
        out.append((keyword.upper(), arguments.strip()))
    return out


def _stages(text: str) -> list[list[tuple[str, str]]]:
    """Instructions grouped per ``FROM`` stage (the ``FROM`` itself first)."""
    stages: list[list[tuple[str, str]]] = []
    for keyword, arguments in _instructions(text):
        if keyword == "FROM":
            stages.append([])
        if stages:
            stages[-1].append((keyword, arguments))
    return stages


def _commands(run_arguments: str) -> list[list[str]]:
    """The shell commands of one ``RUN``, each tokenised with ``shlex``."""
    return [shlex.split(part) for part in re.split(r"&&|;|\|\|", run_arguments) if part.strip()]


def _words(command: list[str]) -> list[str]:
    """Command words without ``NAME=value`` assignments and without leading
    ``RUN`` flags such as ``--mount=type=cache,...``."""
    words = [w for w in command if not _ASSIGNMENT.fullmatch(w)]
    while words and words[0].startswith("--"):
        words = words[1:]
    return words


def _all_run_commands() -> list[list[str]]:
    text = DOCKERFILE.read_text(encoding="utf-8")
    return [
        command
        for keyword, arguments in _instructions(text)
        if keyword == "RUN"
        for command in _commands(arguments)
    ]


def _env_pairs(arguments: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for token in shlex.split(arguments):
        key, sep, value = token.partition("=")
        if sep:
            pairs[key] = value
    return pairs


def _uv_sync_commands() -> list[tuple[list[tuple[str, str]], int, list[str]]]:
    """Every ``uv sync`` command: (its stage, the RUN's index in it, tokens)."""
    found = []
    for stage in _stages(DOCKERFILE.read_text(encoding="utf-8")):
        for index, (keyword, arguments) in enumerate(stage):
            if keyword != "RUN":
                continue
            for command in _commands(arguments):
                if _words(command)[:2] == ["uv", "sync"]:
                    found.append((stage, index, command))
    return found


def _is_pip_install(command: list[str]) -> bool:
    """``uv pip install``, ``pip install``, ``python -m pip install`` and
    ``/opt/venv/bin/pip install`` all have a ``pip``/``pip3`` word directly
    followed by ``install``."""
    words = _words(command)
    return any(
        Path(a).name in ("pip", "pip3") and b == "install"
        for a, b in zip(words, words[1:], strict=False)
    )


def test_no_dockerfile_command_installs_with_pip() -> None:
    """Red when: any RUN command in any stage is a pip install (``uv pip
    install`` included). Those resolve from ``pyproject.toml`` ranges and
    ignore ``uv.lock`` (finding S4). Partner inside: the parser does see the
    Dockerfile's RUN commands (``useradd`` in the runtime stage), so "no pip
    install" is not true over an empty list."""
    commands = _all_run_commands()
    assert any(_words(c)[:1] == ["useradd"] for c in commands), commands
    offending = [c for c in commands if _is_pip_install(c)]
    assert offending == [], offending


def test_the_dockerfile_installs_with_uv_sync_from_the_lock_without_dev_or_extras() -> None:
    """Red when: no RUN runs ``uv sync``, or a ``uv sync`` lacks ``--frozen``
    (install exactly what uv.lock pins), ``--no-dev`` (no dev group in
    production) or ``--no-install-project`` (the app ships as source on
    PYTHONPATH), or carries ``--all-extras``/``--extra`` (the optional dev and
    quality extras would ship, and differ from the ``uv export`` the image is
    checked against)."""
    syncs = _uv_sync_commands()
    assert syncs, "no RUN command in the Dockerfile runs `uv sync`"
    for _stage, _index, command in syncs:
        for flag in ("--frozen", "--no-dev", "--no-install-project"):
            assert flag in command, (flag, command)
        assert "--all-extras" not in command, command
        assert not any(w == "--extra" or w.startswith("--extra=") for w in command), command


def test_the_uv_sync_installs_into_the_venv_the_runtime_stage_copies() -> None:
    """Red when: the ``uv sync`` does not target ``/opt/venv`` through
    ``UV_PROJECT_ENVIRONMENT`` (an ``ENV`` earlier in its stage, or an
    assignment on the command), or no later stage copies ``/opt/venv`` from
    that stage. Then what was synced from the lock is not what ships."""
    syncs = _uv_sync_commands()
    assert syncs, "no RUN command in the Dockerfile runs `uv sync`"
    stage, index, command = syncs[0]
    inline = "UV_PROJECT_ENVIRONMENT=/opt/venv" in command
    env = any(
        _env_pairs(arguments).get("UV_PROJECT_ENVIRONMENT") == "/opt/venv"
        for keyword, arguments in stage[:index]
        if keyword == "ENV"
    )
    assert inline or env, command

    from_words = stage[0][1].split()
    assert len(from_words) >= 3 and from_words[-2].upper() == "AS", stage[0]
    name = from_words[-1]
    stages = _stages(DOCKERFILE.read_text(encoding="utf-8"))
    later = stages[stages.index(stage) + 1 :]
    copies = [shlex.split(a) for st in later for k, a in st if k == "COPY"]
    assert any(f"--from={name}" in c and "/opt/venv" in c for c in copies), copies


# ---------------------------------------------------------------------------
# uv.lock
# ---------------------------------------------------------------------------


def _locked_versions(name: str) -> list[Version]:
    data = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    return [Version(p["version"]) for p in data["package"] if p["name"] == name]


def test_uv_lock_pins_anyio_at_or_above_the_fixed_release() -> None:
    """Red when: uv.lock pins anyio below 4.14.2 (4.14.0 carries
    PYSEC-2026-4023, -4024 and -4025). Partner inside: anyio IS in the lock,
    so the bound is not checked over nothing."""
    versions = _locked_versions("anyio")
    assert versions, "anyio is not in uv.lock"
    assert all(v.release >= (4, 14, 2) for v in versions), versions


def test_uv_lock_pins_urllib3_at_or_above_the_fixed_release() -> None:
    """Red when: uv.lock pins urllib3 below 2.8.0 (2.7.0 carries
    PYSEC-2026-4175, -4176 and -4177). Partner inside: urllib3 IS in the
    lock."""
    versions = _locked_versions("urllib3")
    assert versions, "urllib3 is not in uv.lock"
    assert all(v.release >= (2, 8, 0) for v in versions), versions


# ---------------------------------------------------------------------------
# CI workflow
# ---------------------------------------------------------------------------


def _job() -> dict[str, Any]:
    workflow = yaml.safe_load(CI.read_text(encoding="utf-8"))
    job: dict[str, Any] = workflow["jobs"]["validate-and-test"]
    return job


def _step_index(steps: list[dict[str, Any]], run: str) -> int:
    matches = [i for i, s in enumerate(steps) if str(s.get("run", "")).strip() == run]
    assert len(matches) == 1, (run, matches, [s.get("run") for s in steps])
    return matches[0]


def _assert_blocking(job: dict[str, Any], step: dict[str, Any]) -> None:
    assert not job.get("continue-on-error", False), job.get("continue-on-error")
    assert not step.get("continue-on-error", False), step
    assert "if" not in step, step


def test_ci_partner_validate_and_test_runs_security_scan_and_docker_build() -> None:
    """Partner, passes now. Red when: the ``validate-and-test`` job loses its
    ``make security-scan`` or ``make docker-build`` step, which the two tests
    below order against (without them those tests would fail for the wrong
    reason)."""
    steps = _job()["steps"]
    assert _step_index(steps, "make security-scan") >= 0
    assert _step_index(steps, "make docker-build") >= 0


def test_ci_runs_a_blocking_vulnerability_audit_after_the_security_scan() -> None:
    """Red when: ``validate-and-test`` has no step whose run is ``make
    vuln-audit``, the step comes before ``make security-scan``, or it is made
    non-blocking (``continue-on-error`` on it or the job, or an ``if:`` that
    can skip it). W68 asks for a BLOCKING check."""
    job = _job()
    steps = job["steps"]
    audit = _step_index(steps, "make vuln-audit")
    assert audit > _step_index(steps, "make security-scan")
    _assert_blocking(job, steps[audit])


def test_ci_checks_the_built_image_against_the_lock_after_building_it() -> None:
    """Red when: ``validate-and-test`` has no step whose run is ``make
    image-lock-check``, the step runs before ``make docker-build`` (there is
    no image to inspect yet), or it is made non-blocking."""
    job = _job()
    steps = job["steps"]
    check = _step_index(steps, "make image-lock-check")
    assert check > _step_index(steps, "make docker-build")
    _assert_blocking(job, steps[check])


# ---------------------------------------------------------------------------
# Makefile
# ---------------------------------------------------------------------------


def _makefile_code() -> str:
    return code_without_comments(MAKEFILE)


def _recipe_words(target: str) -> list[str]:
    """Whitespace-split words of ``target``'s recipe (tab-indented lines after
    the ``target:`` line), with comments blanked."""
    lines = _makefile_code().splitlines()
    starts = [i for i, line in enumerate(lines) if re.match(rf"^{re.escape(target)}\s*:", line)]
    assert len(starts) == 1, (target, starts)
    words: list[str] = []
    for line in lines[starts[0] + 1 :]:
        if not line.startswith("\t"):
            break
        words.extend(line.split())
    return words


def _image_default() -> str | None:
    for line in _makefile_code().splitlines():
        m = re.match(r"^IMAGE\s*\?=\s*(\S+)\s*$", line)
        if m:
            return m.group(1)
    return None


def test_makefile_partner_docker_build_tags_an_image() -> None:
    """Partner, passes now. Red when: the recipe parser cannot find the
    ``docker-build`` recipe or its ``docker build -t <tag>`` words, so the
    Makefile tests below would be checking nothing."""
    words = _recipe_words("docker-build")
    assert "docker" in words and "build" in words and "-t" in words, words


def test_makefile_vuln_audit_target_runs_the_script() -> None:
    """Red when: there is no ``vuln-audit`` target, or its recipe does not run
    ``scripts/vuln_audit.py``."""
    words = _recipe_words("vuln-audit")
    assert any(w.endswith("scripts/vuln_audit.py") for w in words), words


def test_makefile_image_lock_check_targets_the_image_docker_build_tags() -> None:
    """Red when: there is no ``image-lock-check`` target, its recipe does not
    run ``scripts/check_image_matches_lock.py --image $(IMAGE)``, ``IMAGE``
    does not default (``?=``) to ``quorum-ai:local``, or ``docker-build``
    tags a different image than the one checked."""
    words = _recipe_words("image-lock-check")
    assert any(w.endswith("scripts/check_image_matches_lock.py") for w in words), words
    assert "--image" in words and words[words.index("--image") + 1] == "$(IMAGE)", words
    assert _image_default() == "quorum-ai:local"
    build = _recipe_words("docker-build")
    assert build[build.index("-t") + 1] in ("quorum-ai:local", "$(IMAGE)"), build
