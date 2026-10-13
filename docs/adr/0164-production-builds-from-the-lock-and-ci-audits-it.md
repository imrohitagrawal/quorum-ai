# ADR-0164: Production builds from the lock, and CI audits it

## Status

Accepted — 2026-10-13. The work is the owner's choice: CHG-042 (b) put "lock file + library
updates + vulnerability check" second, after W56 (board row W68). The design below (`uv sync
--frozen` in the Dockerfile, `pip-audit` through `uvx`, two steps inside the required
`validate-and-test` job, a check of the built image against the lock, `--locked` on every CI
install) is the session's.

## Context

Findings S3 and S4 of `docs/analysis/2026-10-13-security-review.md`:

- **S4: production did not run what CI tested.** The Dockerfile's builder stage ran
  `uv pip install --python /opt/venv/bin/python --no-cache --compile-bytecode .`. That resolves
  from the version ranges in `pyproject.toml` and ignores `uv.lock`. Every CI lane runs
  `uv sync`, which installs the lock. So the image held whatever was newest within the ranges on
  the day it was built.
- **S3: the lock carried six known vulnerabilities, and nothing looked.** `anyio` 4.14.0
  (PYSEC-2026-4023, -4024, -4025, fixed in 4.14.2) and `urllib3` 2.7.0 (PYSEC-2026-4175, -4176,
  -4177, fixed in 2.8.0). No CI job audited libraries.

This record changes three earlier statements without editing their bodies:

- ADR-0029 decision 10 and the comment in `pyproject.toml` justify pinning `markdown-it-py`
  exactly because "`Dockerfile:10` builds with `uv pip install .`, which resolves from the range
  and ignores `uv.lock`". That is no longer true. The exact pin stays: a range would still let a
  routine `uv lock --upgrade` move the parser, and so the grounding score, with no code change.
  The `pyproject.toml` comment now says so.
- ADR-0154's consequences say `cffi` and `pycparser` are not pinned in the image. They are now
  (board row W59 derives `DONE` from the Dockerfile).
- ADR-0163 says the image installs sentry-sdk 2.72.0 "until board row W68 builds the image from
  the lock". It now installs the locked 2.63.0 (measurement 4 below). The metric hook
  `before_send_metric=_drop_sentry_metric` stays, as defence in depth: a later sentry-sdk update
  that ignores `enable_metrics=False` cannot turn metrics back on. The comment in
  `src/product_app/main.py` says so.

## Decision

1. **The image installs from the lock.** The builder stage runs
   `uv sync --frozen --no-dev --no-install-project --compile-bytecode --no-cache`, with
   `UV_PROJECT_ENVIRONMENT=/opt/venv`, `UV_PYTHON=/usr/local/bin/python3.12` and
   `UV_PYTHON_DOWNLOADS=never` set by `ENV`. `--frozen` reads the lock as it is. No `--extra`, so
   the `dev` and `quality` extras stay out. `--no-install-project`, because the runtime stage
   already runs the app from `/app/src` on `PYTHONPATH`. The venv is built on the builder
   image's `/usr/local/bin/python3.12`, the same path `python:3.12-slim` has, so the venv's
   interpreter link still resolves in the runtime stage. `--compile-bytecode` keeps the W54
   bytecode contract.
2. **`anyio` and `urllib3` move to fixed releases**, and nothing else moves:
   `uv lock --upgrade-package anyio --upgrade-package urllib3`.
3. **`make vuln-audit`** (`scripts/vuln_audit.py`) exports the production set
   (`uv export --frozen --no-dev --no-emit-project --no-hashes`) and audits exactly that list
   with `uvx --python 3.12 --from pip-audit==2.10.1 pip-audit -r <file> --no-deps --disable-pip
   --strict --cache-dir <fresh temporary folder> --format json`. The fresh cache folder means
   every run asks the vulnerability service again; an old cache cannot answer for it. It
   prints `vuln-audit: exported N pinned lines, M apply to the image (Linux, CPython 3.12)`
   first and `vuln-audit: M packages, V known vulnerabilities` last. It exits 1 on any known
   vulnerability and prints each as `<name> <version> <id> fixed in <versions>`. It exits 2,
   refusing, when the export fails or pins nothing for the image, when pip-audit's output is
   not JSON, when pip-audit skipped any package, or when the set of `(name, version)` pairs
   pip-audit audited differs from the pairs the export pins for the image (markers evaluated
   as `make image-lock-check` evaluates them). Each missing pair is printed as
   `vuln-audit: not audited: <name>==<version>`.
4. **`make image-lock-check`** (`scripts/check_image_matches_lock.py --image $(IMAGE)`, `IMAGE`
   defaulting to `quorum-ai:local`, the tag `make docker-build` builds) lists every distribution
   the image's `/opt/venv/bin/python` can see and compares it with the same export, markers
   evaluated for Linux CPython 3.12. The image's listing is read verbatim, with no marker
   evaluation: the version is everything after the first `==`, so a metadata version such as
   `9.9 ; os_name == "nt"` cannot hide an installed package. It exits 1 on a missing, extra or
   different-version package, on one distribution listed twice in any spelling (two versions
   installed side by side: Python imports only one, and a name-to-version map would keep only
   one), or on a listing line that is not `name==version`. No extra is allowed:
   the image's venv holds no `pip`, `setuptools` or `wheel` (measurement 15), and an
   allowance for them would hide a vulnerable one. It exits 2 when either side is empty.
5. **Both run as blocking steps of the required `validate-and-test` job**: `make vuln-audit`
   after `make security-scan`, `make image-lock-check` after `make docker-build`. No
   `continue-on-error`, no `if:`.
6. **Every `uv sync` in `.github/workflows/` carries `--locked`** (12 steps in 8 files). A
   stale `uv.lock` now fails the install step instead of being rewritten on the runner.
   Without it, CI audited, tested and built a re-locked set while production built the
   committed lock (measurement 11).

## Measurements

All on 2026-10-13. "This branch" is `w68/build-from-lock`; local commands ran on macOS (arm64)
with Docker Desktop.

| # | Fact | Value | Command |
|---|---|---|---|
| 1 | What CI's image installed before this change (run 38408508822, the pull-request run of PR #562's head `9685224`; the push run of `1b6adf9` is 38412480320) | `anyio==4.15.1`, `sentry-sdk==2.72.0`, `urllib3==2.8.0`; the same job's `uv sync` installed the locked `anyio==4.14.0`, `sentry-sdk==2.63.0`, `urllib3==2.7.0` | `gh run view 38408508822 --job 115334339883 --log`, grep `+ <name>==` |
| 2 | The audit on `1b6adf9`'s lock | exit 1; 6 known vulnerabilities (the six in S3); `vuln-audit: exported 32 pinned lines, 31 apply to the image (Linux, CPython 3.12)`, `vuln-audit: 31 packages, 6 known vulnerabilities` | `scripts/vuln_audit.py` run in a folder holding only `1b6adf9`'s `pyproject.toml` and `uv.lock` |
| 3 | The audit on this branch | exit 0; `vuln-audit: exported 33 pinned lines, 31 apply to the image (Linux, CPython 3.12)`, `vuln-audit: 31 packages, 0 known vulnerabilities` | `make vuln-audit` |
| 4 | The image built from this branch | `uv sync` used `CPython 3.12.12 interpreter at: /usr/local/bin/python3.12`, installed 31 packages including `anyio==4.14.2`, `sentry-sdk==2.63.0`, `urllib3==2.8.0`, and compiled 934 files; `/opt/venv/bin/python -> /usr/local/bin/python3.12` | `make docker-build`; `docker run --rm --entrypoint sh quorum-ai:local -c 'ls -l /opt/venv/bin/python'` |
| 5 | The image against the lock | exit 0; `image-lock-check: locked 31, installed 31` | `make image-lock-check` |
| 6 | The check bites | the same image against `1b6adf9`'s lock: exit 1, `anyio: uv.lock pins 4.14.0, the image has 4.14.2` and the same for `urllib3`; a tag that does not exist: exit 2, refusing | `scripts/check_image_matches_lock.py` run in that folder, and with `--image quorum-ai:no-such-tag` |
| 7 | The app starts without the project installed | `/health` 200 and `/ready` 200 (`live_readiness.state: offline_by_config`) with no secrets set | `docker run --rm -d -p 18231:8000 quorum-ai:local`, `curl` |
| 8 | Time locally | `make vuln-audit` 2.20 s, 1.99 s and 5.02 s on three runs with a fresh pip-audit cache each time (warm uv cache); `make image-lock-check` 0.98 to 1.01 s; `make docker-build` 16.98 s with cached base layers, its `uv sync` step 8.9 s | `/usr/bin/time -p make <target>` |
| 9 | Time budget in CI | `validate-and-test` took 25 min 5 s (13:52:14 to 14:17:19) against its 35-minute limit; its Docker build step took about 15 s | run 38408508822, `gh run view --json jobs` and the step timestamps in its log. The two new steps' time in CI is UNVERIFIED until the first run of this branch; pip-audit's first download there is not measured |
| 10 | The lock change | `anyio` 4.14.0 became two entries: 4.14.2 for Python below 3.15 and 4.15.1 for 3.15 and above; `urllib3` 2.7.0 became 2.8.0; no other package changed version | `uv lock --upgrade-package anyio --upgrade-package urllib3`, then the `[[package]]` versions diffed before and after |
| 11 | A stale lock got through both gates before `--locked` | Reported by the round 1 break-it review, not re-run here: a lock pinning `anyio` 4.14.0 and `urllib3` 2.7.0 behind a `pyproject.toml` that needed a re-lock exited 0 from `make vuln-audit`, `make docker-build` and `make image-lock-check` in CI's order, because `uv sync --all-extras` re-locked the runner's copy first, while a fresh checkout's `uv sync --frozen` image held the vulnerable versions | the reviewer's reproduction |
| 12 | `uv sync --locked` refuses a stale lock | On a scratch copy with `"six>=1.16"` added to `pyproject.toml` and no re-lock: uv 0.11.18 printed ``The lockfile at `uv.lock` needs to be updated, but `--locked` was provided. To update the lockfile, run `uv lock`.`` and exited 1; uv 0.13.0 printed ``error: The lockfile at `uv.lock` needs to be updated, but `--locked` was provided.`` and exited 1; the lock file was left unchanged (`cmp`) | `uv sync --locked --all-extras`, and `uvx --from uv==0.13.0 uv sync --locked --all-extras` |
| 13 | This branch's lock is not stale for CI's uv | CI installed uv 0.13.0 (run 38412480320's log: `Successfully installed uv version 0.13.0`); `uv lock --check` exits 0 under uv 0.11.18 and under 0.13.0 | `uv lock --check`; `uvx --from uv==0.13.0 uv lock --check` |
| 14 | The audit refuses offline even after an online run | exit 2, `vuln-audit: refusing: pip-audit exited 1 without a JSON report`, run straight after an online run. The round 1 version, using pip-audit's default cache, exited 0 in the same case (reported by the round 1 prose review, not re-run here) | `HTTPS_PROXY=http://127.0.0.1:9 HTTP_PROXY=http://127.0.0.1:9 make vuln-audit` |
| 15 | The image's venv holds no installer tooling | on an image built from this branch (tag `w68fix-check`, removed after): `[]` for `pip`, `setuptools` and `wheel`; `image-lock-check: locked 31, installed 31` with no allowance | `docker run --rm --pull never --entrypoint /opt/venv/bin/python <image> -c ...` listing those names; `make image-lock-check IMAGE=<image>` |

Why `anyio` forks (row 10): `anyio` 4.15.1 needs `typing_extensions>=4.16.0` below Python 3.15
(its PyPI metadata), and the lock keeps `typing-extensions` 4.15.0 because only `anyio` and
`urllib3` were allowed to move. So uv kept 4.14.2, which has the fixes, for the Python
production runs (3.12), and 4.15.1 only where `typing-extensions` is not needed. Both versions
are at or above the fixed 4.14.2.

## Rejected alternatives

- **`uv export --frozen ... | uv pip install -r -`.** It also installs the locked versions, but
  through a second command, and a requirements file between the two whose flags must stay in
  step with the export. `uv sync --frozen` reads the lock directly. Rejected for the extra moving
  part.
- **`uv sync --locked` instead of `--frozen`.** `--locked` refuses when the lock is out of date
  with `pyproject.toml`; `--frozen` does not look. uv does not accept both (`uv sync --locked
  --frozen` exits 2: "the argument '--locked' cannot be used with '--frozen'"). In the image,
  `--frozen` is what is wanted: install what the lock says, and nothing resolved at build time.
  The out-of-date-lock case is closed in CI instead, by `--locked` on every install (decision
  6): a stale lock fails the required `validate-and-test` job at its install step.
- **osv-scanner instead of pip-audit.** It reads `uv.lock` directly and covers more
  ecosystems, but it is a Go binary that would need its own install step and its own pinning in
  CI. pip-audit runs through `uvx`, which CI already has, pinned with one `==`, and can query
  OSV too (`--vulnerability-service osv`; its default is `pypi`). The two were not compared on
  this repository.
- **A separate audit job.** A new job would run in parallel, but it blocks a merge only if
  branch protection names it as required, and that list is the owner's setting. A step inside
  `validate-and-test`, already required and part of the "CI" workflow that `deploy.yml`'s gate
  waits for (`scripts/deploy_gate.py`, `REQUIRED_WORKFLOWS`), blocks without a settings
  change. The cost is the job's time. Locally the two steps take seconds (measurement 8);
  their time in CI is UNVERIFIED (measurement 9). On run 38408508822 the job finished about
  10 minutes inside its limit.
- **Audit the installed CI venv (`pip-audit` with no `-r`).** That venv holds the `dev` and
  `quality` extras, which production does not ship, so a finding there could block a merge
  over a library the product never runs, and the count would not describe production.

## Consequences

- The image holds what the lock pins, and CI fails if a later Dockerfile edit drifts from it
  (`make image-lock-check`).
- A merge fails while any locked runtime library has a known vulnerability. Someone has to
  update the library (`uv lock --upgrade-package <name>`) before anything else can merge, even
  a change that has nothing to do with it. That is the intended pressure. A vulnerability
  without a fixed release will block too; there is no allow-list yet, and adding one is a
  decision for whoever meets that case.
- The audit needs the network: `uvx` downloads pip-audit, and pip-audit asks PyPI's
  vulnerability service (its default, `--vulnerability-service pypi`) about each package. When
  the service cannot be reached, the step refuses (exit 2) rather than passing, even right
  after an online run, because each run starts with an empty pip-audit cache (measurement 14).
- A library update is now an explicit commit to `uv.lock`, reviewed like any change. Before,
  an image rebuild picked up new releases silently.

## What it cannot see

- **Operating-system packages in the base images** (`python:3.12-slim`, and the uv builder
  image) are not audited. Neither is the Python interpreter itself.
- **The base image's own Python packages, outside `/opt/venv`**, are neither audited nor
  compared. Reported by the round 2 break-it review, not re-run here: `python:3.12-slim` ships
  pip 25.0.1 at `/usr/local/lib/python3.12/site-packages`, it is on `PATH` in the container,
  and the venv has `include-system-site-packages = false`, so the app cannot import it. Re-run
  by this change on 2026-10-14: pip-audit 2.10.1 over a requirements file holding only
  `pip==25.0.1`, with `--no-deps`, reports 6 distinct PYSEC ids (12 entries), fixed in releases
  from 25.3 to 26.2. This change does not remove it.
- **`uv sync --frozen` in a workflow** passes the workflow test by design, except in
  `validate-and-test`'s install step, which must use `--locked`. The workflow test refuses
  a `uv sync` with neither `--locked` nor `--frozen`, a `uv sync` step with `||`, and any `uv
  lock` but `uv lock --check`, and no workflow uses `--frozen` today.
- **`UV_PYTHON_DOWNLOADS=never` and `UV_PYTHON` in the Dockerfile are not pinned by a test.**
  They are defence in depth: `make image-lock-check` lists what `/opt/venv/bin/python` sees,
  whichever interpreter built the venv, and refuses (exit 2) when that interpreter does not
  start.
- **A vulnerability published after a merge** is caught only on the next CI run. Production
  keeps running the old image until then; no scheduled audit exists.
- **An out-of-date lock is no longer a gap in CI.** Before decision 6, a `pyproject.toml`
  change without a re-lock gave an image built from the old lock (`--frozen` does not look),
  while CI's `uv sync --all-extras` re-locked on the runner and tested, audited and built the
  new set; the round 1 review reproduced a vulnerable lock passing both gates this way
  (measurement 11). Every CI install now runs `uv sync --locked`, which exits 1 on a stale
  lock (measurement 12), so such a change fails each CI job that installs (`fr-completeness`
  installs nothing) at its install step, before either W68 gate runs. A deploy of a commit CI did not run on is outside this check.
- **Lines whose marker does not hold for the image** (Linux, CPython 3.12) are not audited:
  today `colorama` (Windows only) and the `anyio` 4.15.1 entry (Python 3.15 and above). Neither
  is installed in the image. The first output line shows how many lines apply; if pip-audit
  leaves out a line that applies to the image (it evaluates markers for the machine it runs
  on), the audit refuses and names it.
- **The audit's own trust**: pip-audit 2.10.1 is pinned by version, not by hash. Only
  pip-audit itself is pinned: `uvx` resolves its dependencies when it runs, with no lock or
  constraints file from this repository, so they can change between runs without a commit.
  Its advisory data is whatever PyPI's service returns that day.
