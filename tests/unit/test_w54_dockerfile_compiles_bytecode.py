"""W54 step 3, round 2: the image ships compiled bytecode for its packages.

The PDF child (ADR-0153) runs under a 2 s CPU limit and imports pypdf on
every PDF. The runtime stage sets ``PYTHONDONTWRITEBYTECODE=1``, so nothing
compiles at run time: whatever ``.pyc`` the image has, the BUILDER stage
wrote. The break-it session measured the pypdf import at 0.17-0.19 s of CPU
without ``.pyc`` and 0.04-0.05 s with it. So the builder stage's
``uv pip install`` must compile bytecode: ``--compile-bytecode`` on that
command, or ``UV_COMPILE_BYTECODE`` set to 1 in that stage before it.

The Dockerfile is PARSED (continuation lines joined, comment lines dropped as
Docker drops them, stages split at ``FROM``, each ``RUN`` split into its
``&&``/``;`` commands and tokenised with ``shlex``), never searched as one
string: a substring would match a comment that merely mentions the flag.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from tests.repo_root import find_repo_root

pytestmark = pytest.mark.repo_introspection

DOCKERFILE = find_repo_root(Path(__file__)) / "Dockerfile"


@dataclass
class Stage:
    name: str
    instructions: list[tuple[str, str]] = field(default_factory=list)


def _instructions(text: str) -> list[tuple[str, str]]:
    """``(KEYWORD, arguments)`` per instruction, continuations joined."""
    out: list[tuple[str, str]] = []
    pending = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue  # Docker drops comment lines, even inside a continuation
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        whole = (pending + line).strip()
        pending = ""
        keyword, _, arguments = whole.partition(" ")
        out.append((keyword.upper(), arguments.strip()))
    return out


def _stages(text: str) -> list[Stage]:
    stages: list[Stage] = []
    for keyword, arguments in _instructions(text):
        if keyword == "FROM":
            words = arguments.split()
            name = words[-1] if len(words) >= 3 and words[-2].upper() == "AS" else words[0]
            stages.append(Stage(name=name))
        elif stages:
            stages[-1].instructions.append((keyword, arguments))
    return stages


def _commands(run_arguments: str) -> list[list[str]]:
    """The shell commands of one ``RUN``, each tokenised."""
    return [shlex.split(part) for part in re.split(r"&&|;", run_arguments) if part.strip()]


def _env_pairs(arguments: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for token in shlex.split(arguments):
        key, sep, value = token.partition("=")
        if sep:
            pairs[key] = value
    return pairs


def _uv_pip_install(stage: Stage) -> tuple[int, list[str]] | None:
    """The index of the RUN holding ``uv pip install`` and that command's
    tokens (after any leading ``NAME=value`` assignments)."""
    for index, (keyword, arguments) in enumerate(stage.instructions):
        if keyword != "RUN":
            continue
        for command in _commands(arguments):
            words = [w for w in command if not re.fullmatch(r"[A-Z_][A-Z0-9_]*=.*", w)]
            if words[:3] == ["uv", "pip", "install"]:
                return index, command
    return None


def _builder() -> tuple[Stage, int, list[str]]:
    for stage in _stages(DOCKERFILE.read_text(encoding="utf-8")):
        found = _uv_pip_install(stage)
        if found is not None:
            return stage, found[0], found[1]
    raise AssertionError("no stage of the Dockerfile runs `uv pip install`")


def test_the_builder_stage_installs_the_app_with_uv_and_the_runtime_copies_that_venv() -> None:
    """The partner: the parser finds what the real test inspects. RED IF:
    no stage runs ``uv pip install`` into ``/opt/venv``, or no later stage
    copies ``/opt/venv`` from that stage (then the builder's bytecode would
    not be what ships)."""
    stage, _index, command = _builder()
    assert "--python" in command and command[command.index("--python") + 1].startswith("/opt/venv")
    stages = _stages(DOCKERFILE.read_text(encoding="utf-8"))
    copies = [
        arguments
        for later in stages[stages.index(stage) + 1 :]
        for keyword, arguments in later.instructions
        if keyword == "COPY"
    ]
    assert any(
        f"--from={stage.name}" in shlex.split(c) and "/opt/venv" in shlex.split(c) for c in copies
    ), copies


def test_the_builder_stage_compiles_bytecode() -> None:
    """RED IF: the builder stage's ``uv pip install`` neither carries
    ``--compile-bytecode`` nor runs with ``UV_COMPILE_BYTECODE`` set to 1 (as
    an ``ENV`` of that stage before it, or an assignment on the command).
    The image then has no ``.pyc`` for pypdf, and every PDF child spends
    about 0.15 s more of its 2 s CPU limit importing it."""
    stage, index, command = _builder()
    flag = "--compile-bytecode" in command
    inline = any(w in ("UV_COMPILE_BYTECODE=1", "UV_COMPILE_BYTECODE=true") for w in command)
    env = any(
        _env_pairs(arguments).get("UV_COMPILE_BYTECODE", "").lower() in ("1", "true")
        for keyword, arguments in stage.instructions[:index]
        if keyword == "ENV"
    )
    assert flag or inline or env, (stage.name, command)
