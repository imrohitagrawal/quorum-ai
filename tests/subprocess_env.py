"""One place that denies a child process pytest-cov's subprocess hooks.

`pyproject.toml`'s `addopts` is `--cov=src` — a **relative** path — and there
is no `[tool.coverage]` section pinning a source. pytest-cov hands that string
to every child process it can reach, through a `.pth` file that runs at
interpreter start-up. Measured on this tree, from inside a test run::

    VAL COV_CORE_CONFIG=':'
    VAL COV_CORE_DATAFILE='/Users/.../quorum-ai/.coverage'
    VAL COV_CORE_SOURCE='src'

`COV_CORE_SOURCE` is `'src'`, unqualified. A child launched with `cwd=` some
directory OUTSIDE the repository resolves it against **its own** working
directory, and `coverage`'s `find_possibly_unexecuted_files()` then walks that
directory and records every importable `.py` file under it at 0%. The child
writes its data beside the absolute `COV_CORE_DATAFILE`, and the parent
combines it. The parent's statement TOTAL grows by a tree nobody changed.

Measured on this repository, both directions, 2026-08-25 (issue #368)::

    $ .venv/bin/python -m pytest \
        tests/unit/test_stance_majority_flags_has_no_equivalent_mutants.py \
        --cov=src --cov-report=term -q
    TOTAL   5847  3963  32%      # a test that clones nothing

    $ .venv/bin/python -m pytest \
        tests/unit/test_replay_scope_matches_makefile_scope.py \
        --cov=src --cov-report=term -q
    TOTAL  10426  8551  18%      # the same flags, on a test that clones the repo

4,579 of those statements are the clone's, under
`/private/var/.../pytest-of-.../mutscope-clone0/repo/src/`. Divide a healthy
run's covered lines by the inflated denominator and 95.28% becomes 53%, which
is below `--cov-fail-under=88` — a **required** status check going red for a
reason unrelated to the diff.

The mitigation is to strip the hook's variables from the child's environment.
It already existed, correctly, at two call sites and was absent at a third.
Duplicated mitigations drift; this module exists so there is exactly one, and
so `tests/unit/test_subprocess_env_hygiene.py` has a single name to recognise
as safe.

WHAT DOES NOT NEED THIS. Only a **Python interpreter** child loads the `.pth`
hook, so a `git`, `make` or `/bin/sh` child cannot leak — verified in
`tests/unit/test_subprocess_env_hygiene.py`, which does not flag them. And a
child whose `cwd` is the repository root measures the repository's own `src/`,
which changes no total. The hazard is specifically an interpreter pointed at a
tree outside the repository.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

#: The two prefixes pytest-cov uses to hand a child its coverage configuration.
#:
#: `COV_CORE_*` is the load-bearing one — those three variables are what the
#: `pytest-cov.pth` hook reads, and they are the three actually present in a
#: run of this suite (measured above). `COVERAGE` covers `COVERAGE_FILE` and
#: `COVERAGE_PROCESS_START`, which coverage.py itself honours when a child
#: enables measurement by another route; neither appears in this suite today,
#: and both are stripped anyway because a mitigation that only covers the
#: spelling in front of it is the reason this module had to be written.
COVERAGE_ENV_PREFIXES: tuple[str, ...] = ("COV_CORE", "COVERAGE")


def env_without_coverage(
    base: Mapping[str, str] | None = None, /, **overrides: str
) -> dict[str, str]:
    """`base` (default `os.environ`) with every coverage variable removed.

    Keyword arguments are applied AFTER the strip, so a caller can add its own
    variables in one expression::

        subprocess.run(
            [sys.executable, "-c", "..."],
            cwd=copy,
            env=env_without_coverage(PYTHONPATH=str(copy)),
        )

    An override is applied after the strip and is therefore never filtered —
    passing `COVERAGE_FILE=` explicitly is a deliberate act and this function
    does not second-guess it. `tests/unit/test_subprocess_env_hygiene.py`
    relies on exactly that: it launches a nested coverage run with
    `env_without_coverage(COVERAGE_FILE=...)` so the nested run writes its data
    somewhere harmless instead of over the outer run's.
    """
    source = os.environ if base is None else base
    stripped = {
        key: value for key, value in source.items() if not key.startswith(COVERAGE_ENV_PREFIXES)
    }
    stripped.update(overrides)
    return stripped
