# Command Reference and Execution Map

This file explains what each factory command does, where to run it, and when to use it.

## Two command locations

| Location | Meaning | Typical use |
|---|---|---|
| Factory root, `codex-product-factory/` | The reusable factory template itself. | Validate the skeleton, smoke-test bootstrapping, package upgrades. |
| Generated product repo, for example `my-product/` | The real product created from the factory. | Capture idea, route skills, build product, hand off sessions, validate evidence. |

Most day-to-day commands should be run from the **generated product repo**, not the factory root.

## Per-product command sequence

```bash
make capture-idea IDEA="Your rough product idea"
make next
make skill-route
codex
```

Before switching terminal/session:

```bash
make next
make skill-route
make handoff
make validate
```

Before release readiness:

```bash
make check-breaking
make publishing-check
FACTORY_STRICT=1 make validate-strict
```

## Core commands

| Command | Run from | Purpose | When to run | Expected result |
|---|---|---|---|---|
| `make next` | Generated product repo | Updates `docs/00-factory-console.md` and prints the next best action. | After adding idea, after each major phase, or whenever stuck. | Shows current phase, missing evidence, driver skill, reviewers, blockers, and suggested Codex prompt. |
| `make skill-route` | Generated product repo | Runs the deterministic skill router without changing the console. | When you want to know which skill should drive next. | Prints driver skill, reviewer skills, blocking gates, risk triggers, and prompt. |
| `make handoff` | Generated product repo | Writes `docs/session-handoff.md` using route + git status. | Before closing a Codex session, switching terminal, or handing work to another agent. | Captures phase, driver, reviewers, blockers, changed files, next action, and next-session prompt. |
| `make skill-discover` | Generated product repo | Prints curated external skill sources to consider before building a new local skill. | When a new capability is needed, such as design, session management, PM discovery, database, cloud, testing, media, or content. | Shows candidate skill ecosystems and default adoption mode. It does not install anything. |
| `make skill-onboarding-check` | Generated product repo | Validates the future-skill onboarding backbone. | After adding/editing external skill registry, onboarding policy, or skill research docs. | Confirms required skill governance files and local skills exist. |
| `make check-breaking` | Generated product repo | Performs a lightweight check for schema/config/API contract governance. | Before committing contract/schema/OpenAPI/config changes. | Passes if no contract changes are detected or required governance files exist. Flags likely breaking-change process gaps. |
| `make validate` | Generated product repo or factory root | Runs all normal validation gates. | After each major phase and before PR. | Proves structure and required artifacts exist. In template mode it can pass with placeholders. |
| `FACTORY_STRICT=1 make validate-strict` | Generated product repo | Runs strict evidence validation. | Before release readiness or final demo. | Should fail until placeholders are replaced with real product evidence. Passing means the product has stronger release evidence. |

## Supporting engineering commands

| Command | Run from | Purpose |
|---|---|---|
| `make quality` | Generated product repo | Runs format-check, lint, type-check, and tests. |
| `make format` | Generated product repo | Runs `ruff check . --fix` and then `ruff format .`. |
| `make test` | Generated product repo | Runs the test suite. |
| `make run` | Generated product repo | Starts the local FastAPI app. |
| `make publishing-check` | Generated product repo or factory root | Validates study/FAQ/article/LinkedIn/media publishing backbone. |
| `make bootstrap-smoke` | Factory root | Creates a temporary product and validates it. Useful when changing the factory itself. |

## What these commands are not

- They do not replace Codex. They guide Codex and validate its work.
- They do not publish to Confluence or Git remotes by themselves.
- They do not install external skills by themselves.
- They do not guarantee business correctness. They enforce the process and evidence bar.

## Golden rule

When unsure, run:

```bash
make next
make skill-route
```

Then give the suggested prompt to Codex. The skeleton should guide you instead of making you remember the lifecycle.


## Python command compatibility

The skeleton Makefiles auto-detect Python in this order:

```text
python3 -> python
```

Use `make` targets for day-to-day work so this detection is applied automatically. If your system has a custom Python path, override it explicitly:

```bash
make PYTHON=/path/to/python3 next
make PYTHON=/path/to/python3 validate
```

For direct script execution, use `python3` on macOS/Linux systems where `python` is not installed, or use `python` only when it points to Python 3. The factory requires Python 3.10 or newer.
