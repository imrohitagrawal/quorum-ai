# ADR-0022: A credential is removed from the test process, not hidden at the print site

## Status

Accepted — 2026-08-07

## Context

On 2026-08-07 a real `QUORUM_EVAL_JUDGE_API_KEY` was printed in full to a
developer's terminal by the test suite. The mechanism took three independent,
individually reasonable design choices to line up:

1. `config.py:31` sets `env_file=".env"`, so `Settings` reads the working-tree
   `.env`. This is correct and deliberate — it is how local development gets
   its configuration.
2. `tests/unit/test_evaluation_judge.py:131` asserted
   `settings.quorum_eval_judge_api_key == ""` to express "the judge is off by
   default".
3. pytest's assertion rewriting prints **both sides** of a failed `==`.

With a real key in `.env`, (1) put the live value into `Settings`, (2) compared
it to a literal, and (3) printed it. From there it reached the terminal, the
session transcript, and — via `make test-report` — `build/test-results/pytest.xml`.
The CI sibling of that file is an uploaded artifact.

**No existing gate could have caught this, and the reason is structural.** CI has
no `.env`, so in CI the value is `""`, the assertion passes, and the leak path is
never exercised. Every secret-related control in this repository is scoped to
either *what git tracks* (`scripts/security_scan.py`, `.gitignore`) or *what CI
runs*. This channel is neither. The defect could only ever fire on a developer's
machine — precisely where nothing was looking.

The blast radius was measured, not assumed:

| Where | Command | Result |
|---|---|---|
| Merged commits, branch, fixture | `git log -p --all -S<pattern>` | 0 matches |
| All git objects incl. dangling blobs | `git cat-file --batch-all-objects` scan (126 MB) | 0 matches |
| `.env` ever staged? | `git log --all --diff-filter=A -- .env` | never |
| Shell history | pattern scan | 52 occurrences, 24 files — redacted |
| `/tmp` working copies | `grep -rl` | removed |

Nothing was committed; no history rewrite was required. The 52 shell-history
occurrences trace to a `fly secrets set … KEY='sk-or-v1-…'` command shape, which
places a live secret on the command line — a separate defect in how the secret
was *handled*, recorded here so the next author uses a file-reading form instead.

The conftest **already knew about this hazard**. It says, verbatim, that "the
working-tree `.env` sets `OPENROUTER_LIVE_EXECUTION_ENABLED=true` with a real
key", and overrides that variable. It mitigated **spending** and not
**disclosure**, from the same premise.

## Decision

**Blank every credential environment variable in `tests/conftest.py`, before any
`product_app` module is imported.** The secret is not present in the process, so
there is nothing for any print site to leak.

The mechanism is an explicit `os.environ[...] = ""`, which **beats the `.env`
file** in pydantic-settings precedence and therefore covers both sources. It is
the same mechanism, in the same file, for the same reason as the pre-existing
`OPENROUTER_LIVE_EXECUTION_ENABLED` override beside it.

Placement before the imports is load-bearing, not stylistic: `config.py` builds
a module-level `settings = Settings()` at import time, so a fixture — which runs
after collection — would be too late.

Three consequences follow:

- **`sentry_dsn` is marked `repr=False`.** It is a credential (a DSN embeds a
  public key), and a real one activates a **live Sentry client on every pytest
  run** — observed in this session's own output as *"Sentry is attempting to
  send 2 pending events"*. The redaction hook in `main.py` does not cover
  exception or log text. Marking it also makes the credential set **derivable
  from `config.py`** rather than hand-maintained (rule 1a): the guard test reads
  the `repr=False` fields out of `config.py` and requires each to be blanked, so
  adding a sixth credential field fails the gate until it is covered.
- **`QUORUM_EVAL_JUDGE_MODEL_ID` is blanked too**, though it is not a
  credential. It is the other half of the two-value judge gate, and since #269
  priced the judge into `max_cost_usd`, leaving it set makes the local
  configuration differ from CI's in a way that **moves the spend rails** — CI
  would validate them in a shape production never runs.
- **A credential attribute may not appear on an `assert` line at all.**

  The first version of this rule banned only a comparison against a literal,
  and listed `assert not settings.<key>` and `assert len(settings.<key>) == 0`
  as safe alternatives. **An adversarial review refuted that with a canary**,
  and a third form was found leaking during the fix. Measured 2026-08-07 on a
  40-character canary:

  | Form | Result |
  |---|---|
  | `assert settings.<key> == ""` | LEAKS — `assert 'CANARY…' == ''` |
  | `assert not settings.<key>` | LEAKS — `assert not 'CANARY…'` |
  | `assert len(settings.<key>) == 0` | LEAKS — `where 40 = len('CANARY…')` |
  | `assert bool(settings.<key>) is False` | LEAKS — `where True = bool('CANARY…')` |
  | `n = len(settings.<key>)` then `assert n == 0` | safe |
  | `present = bool(settings.<key>)` then `assert not present` | safe |
  | `assert Settings.model_fields[...].default == ""` | safe |

  pytest's rewriting reports **intermediate** values, so any wrapper reached
  inline is printed with its argument. Enumerating wrappers is a losing game —
  the ban is therefore general: **reduce the credential to a non-secret in its
  own statement, then assert on that.**

  The broadened detector immediately found a **second, pre-existing instance**
  of the primitive at `tests/integration/test_query_run_evaluation_endpoint.py:345`
  (`assert not settings.quorum_eval_judge_api_key`) that the narrow version had
  missed. It is fixed here. A repo-wide sweep now reports 0 offenders.

- **The blanking has one explicit escape hatch, `QUORUM_TEST_LIVE_CREDENTIALS=1`.**
  Blanking unconditionally silently broke `tests/integration/test_tavily_live.py`,
  a documented, opt-in, operator-run paid verification that reads
  `TAVILY_API_KEY` and skips when it is absent — it began skipping *always*.
  That is the "prove both directions" failure: the false positive was gone and
  a genuine capability went with it. The hatch defaults OFF, must be typed on
  the command line, and is named after the existing
  `OPENROUTER_LIVE_EXECUTION_ENABLED` idiom. The two runtime guards skip when
  it is set (credentials are present on purpose); the static guards still run.

Separately, **`scripts/security_scan.py` drops the `tests/` exemption for
`raw_openrouter_key_pattern` only.** A real key committed under `tests/` passed
that blocking gate — wider than the incident and independent of it. The
exemption stays for `env_secret_assignment`, which exists because fixtures
legitimately assign fake secrets.

## Rejected alternatives

**1. A `pytest_runtest_makereport` scrubber that redacts secrets from failure
output.** This was the first design and it was built far enough to measure. It
works against an **exported** environment variable and **still leaks a
`.env`-only secret**, because to redact a value it must first know the value —
i.e. it would have to parse `.env` and hold the secret in order to hide it. It
also only covers the report hook: it does not cover `--capture=no` output,
a `print()` in a fixture, log records, or the junit XML writer. Redaction is a
filter on one channel; removal closes all of them. Rejected as a *primary*
control; it remains available as defence in depth and is not implemented here.

**2. Stop loading `.env` during tests (unset `env_file`).** Rejected: it changes
`Settings` behaviour under test away from the production shape, which is the
opposite of what the spend-rail work needs, and it would silently break the
non-credential local overrides the suite relies on.

**3. Ban `.env` from developer machines / require a secret manager.** Rejected as
disproportionate and unenforceable. It also would not have helped: the same
print happens with an exported variable.

**4. Rely on `.gitignore` plus the existing secret scanner.** This is what
existed. It is what failed. Both are scoped to what git tracks, and the secret
never went near git.

## Consequences

- A test can no longer observe a real credential, so the incident's mechanism is
  gone rather than filtered. Any test that genuinely needs a live key must set
  it explicitly and locally, which is visible in the diff.
- The credential set is now **derived from `config.py`**, so it cannot drift.
  The cost is a text-matching gate over `config.py`'s `Field(... repr=False)`
  shape; if that shape is refactored, the gate must be updated with it — it
  fails loudly rather than silently, and it carries a positive partner asserting
  it still finds at least one field.
- Local runs no longer initialise Sentry, no longer differ from CI on the judge
  gate, and therefore validate the spend rails in the shape production uses.
- **This class of defect — a control that can only fail on a developer's machine
  — remains largely unguarded.** This ADR closes the credential instance of it.
  The general case (local `.env` state changing test outcomes) is not addressed
  and is worth a follow-up, because the same asymmetry that hid this leak hides
  anything else `.env` perturbs.

## Known limits, measured not assumed

- **A pytest plugin loaded with `-p` that imports `product_app` beats the
  blanking.** Demonstrated: a plugin doing `from product_app.config import
  settings` printed `judge_key_len=39` for an exported canary, because `-p`
  plugins are imported during pre-parse, before any conftest. It is not
  reachable by accident — no installed plugin imports `product_app`, and
  `addopts` contains no `-p` — so it needs a deliberate `-p <module>`. Note the
  guard **did catch it**, failing with lengths only. Recorded rather than fixed:
  no mechanism available here runs earlier than plugin import.
- **`scripts/security_scan.py` is line-based and cannot see a key split across
  adjacent string literals**, which Python joins at compile time. Pre-existing,
  not introduced here, and it applies to the whole tree rather than to `tests/`.
  This file's own `_REAL_KEY` fixture depends on that property, and says so.
- **The `.env` file itself is not scanned**, by design: it is gitignored and
  holds real credentials legitimately. The guarantee is that its contents do not
  reach a *test process*, not that they do not exist.
