# Python runner: prefer python3, fall back to python.
# Override when needed: make PYTHON=/path/to/python3 <target>
PYTHON ?= $(shell if command -v python3 >/dev/null 2>&1; then command -v python3; elif command -v python >/dev/null 2>&1; then command -v python; fi)
UV_CACHE_DIR ?= $(CURDIR)/.uv-cache
RELOAD ?= 0


# --- R2 Phase-0 gate configuration -------------------------------------
# Perf specs live under both tests/perf and tests/performance. These are
# HARDCODED, never $(wildcard ...): a glob over a deleted or renamed directory
# expands to nothing, the recipe degrades to a bare `pytest -q --no-cov`, and
# pytest falls back to `testpaths = ["tests"]` — so a "blocking" gate passes the
# ordinary suite while measuring nothing. A hardcoded missing path makes pytest
# exit 4 instead. See gate-min-collected below for the emptied-directory case.
PERF_TEST_PATHS ?= tests/perf tests/performance
CONTRACT_TEST_PATHS ?= tests/contract
# Collection floors, MEASURED on the R2 Phase-0 tree that adds tests/perf (no
# earlier commit contains that directory, so there is no revision to cite):
# perf collects 11 (tests/perf 10 + tests/performance 1), contract collects 23.
# Perf is floored at its exact count (hand-authored specs) — tests/unit/
# test_perf_gate_collection_floor.py re-measures it and fails on any drift, so
# the floor cannot quietly sink below the suite. Contract is floored below its
# count because schemathesis parametrises off the live OpenAPI schema, so the
# number legitimately moves with the API surface; the floor only has to catch a
# deleted/emptied suite. That job needs it ABOVE the largest single contract
# module — measured: schemathesis 17, hand-authored OpenAPI 6 — or deleting the
# hand-authored half leaves 17 over a floor of 10 and api-contract stays green.
# 18 clears 17 and leaves 5 of slack for a legitimately shrinking API surface;
# tests/unit/test_contract_gate_collection_floor.py re-measures both modules.
PERF_MIN_TESTS ?= 11
CONTRACT_MIN_TESTS ?= 18
# An aggregate floor cannot protect a *particular* spec. PERF_MIN_TESTS is an
# equality assert against the live collection, so deleting the hermeticity probe
# and lowering the floor to match is a one-line edit that leaves every guard
# green — MEASURED: `gate-min-collected GATE_PATHS="<perf minus hermeticity>"
# GATE_MIN=5` exits 0. The gate would then be free to drop
# `_pin_static_catalog()` and go back to depending on a live call to
# openrouter.ai, which is the exact regression the probe exists to prevent.
# So the specs the perf gate is worthless without are named here with per-file
# floors, MEASURED on this tree: hermeticity 6, latency percentiles 2. Removing
# one is now an explicit, reviewed edit to this line. Enforced (existence, and
# collected count per file) by tests/unit/test_perf_gate_required_specs.py.
PERF_REQUIRED_SPECS ?= tests/perf/test_perf_gate_hermeticity.py:6 tests/perf/test_workflow_latency_percentiles.py:2
# Mutation scope: changed lines vs the merge-base with origin/main, per the
# R2 decision to mutate changed code only (not whole modules).
DIFF_BASE ?= origin/main
MUTMUT_PATHS ?= src/product_app

.PHONY: check-python publishing-check skill-onboarding-check skill-discover handoff check-breaking apply-orbi-profile skill-route start next capture-idea validate validate-strict fr-completeness openapi-export openapi-check quality format format-check lint type-check test test-report gate-min-collected gate-min-executed perf-gate api-contract mutation-baseline diff-cover security-scan ci-evidence run docker-build feedback-audit

check-python:
	@if [ -z "$(PYTHON)" ]; then 		echo "ERROR: Python 3 is required. Install python3, or set PYTHON=/path/to/python3."; 		exit 127; 	fi
	@$(PYTHON) -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 'ERROR: Python 3.10+ required. Found ' + '.'.join(map(str, sys.version_info[:3])) + '. Set PYTHON=/path/to/python3 or upgrade Python.')"

start: next

next: check-python
	$(PYTHON) scripts/factory_next.py

capture-idea: check-python
	@if [ -n "$(IDEA)" ]; then 		$(PYTHON) scripts/capture_idea.py "$(IDEA)"; 	else 		$(PYTHON) scripts/capture_idea.py; 	fi

validate: check-python fr-completeness
	$(PYTHON) scripts/validate_all.py

validate-strict: check-python fr-completeness
	FACTORY_STRICT=1 $(PYTHON) scripts/validate_all.py

# R2 EN-2/FS-3: fail if an FR-0NN in docs/10 has no row in BOTH docs/17 and
# docs/18. Stdlib-only, like the other factory validators, so it runs without
# a uv environment. Part of the `validate` chain and build-failing in CI.
fr-completeness: check-python
	$(PYTHON) scripts/validate_fr_completeness.py

# Regenerate openapi.yaml from app.openapi() (a fresh FastAPI app instance).
openapi-export:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run python scripts/export_openapi.py

# Drift-guard: fail if the checked-in openapi.yaml != app.openapi(). Runs
# under uv so FastAPI/PyYAML are importable (unlike the stdlib-only
# ``make validate`` gates). Enforced in the validate-and-test CI job.
openapi-check:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run python scripts/validate_openapi_contract.py

quality: format-check lint type-check test

format:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run ruff check . --fix
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run ruff format .

format-check:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run ruff format . --check

lint:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run ruff check .

type-check:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run mypy src tests

test:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run pytest

test-report:
	mkdir -p build/test-results build/coverage
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run pytest --junitxml=build/test-results/pytest.xml --cov=src --cov-report=xml:build/coverage/coverage.xml --cov-report=term-missing

# Fail-closed collection guard shared by the gate targets. Refuses an empty
# path list (pytest would fall back to testpaths and run the ordinary suite), a
# path that does not collect, and a suite that has shrunk below its measured
# floor. Called as: $(MAKE) gate-min-collected GATE_NAME=.. GATE_PATHS=.. GATE_MIN=..
gate-min-collected:
	@if [ -z "$(strip $(GATE_PATHS))" ]; then \
		echo "$(GATE_NAME): no test paths configured — the gate would run the whole suite instead."; \
		exit 1; fi
	@mkdir -p build/gates
	@if ! SENTRY_DSN= UV_CACHE_DIR=$(UV_CACHE_DIR) OPENROUTER_LIVE_EXECUTION_ENABLED=false QUORUM_RUNTIME_ENVIRONMENT=ci \
		uv run pytest $(GATE_PATHS) -q --no-cov --collect-only > build/gates/$(GATE_NAME).collect 2>&1; then \
		tail -5 build/gates/$(GATE_NAME).collect; \
		echo "$(GATE_NAME): collection failed for '$(GATE_PATHS)' — the gate has no tests to run."; \
		exit 1; fi
	@n=$$(grep -c '::' build/gates/$(GATE_NAME).collect || true); \
	if [ "$$n" -lt "$(GATE_MIN)" ]; then \
		echo "$(GATE_NAME): collected $$n tests from '$(GATE_PATHS)', below the floor of $(GATE_MIN)."; \
		echo "  The gate would pass while measuring nothing. Restore the tests, or"; \
		echo "  lower the floor deliberately with a recorded measurement."; \
		exit 1; fi; \
	echo "$(GATE_NAME): $$n tests collected from '$(GATE_PATHS)' (floor $(GATE_MIN))."

# Fail-closed EXECUTED-count guard, run after a gate's pytest invocation.
# gate-min-collected alone is gameable: a skipped test still collects, so one
# `pytestmark = pytest.mark.skip(...)` satisfied the floor and exited 0 with
# zero assertions run. This re-derives the count from the run's own JUnit XML
# and refuses any skip/xfail in a gate suite — a gate measures or it fails.
# Called as: $(MAKE) gate-min-executed GATE_NAME=.. GATE_MIN=..
gate-min-executed:
	@counts=$$(UV_CACHE_DIR=$(UV_CACHE_DIR) uv run python -c "import sys, xml.etree.ElementTree as ET; r = ET.parse(sys.argv[1]).getroot(); s = r if r.tag == 'testsuite' else r[0]; a = s.attrib; g = lambda k: int(a.get(k, 0)); print(g('tests') - g('skipped') - g('failures') - g('errors'), g('skipped'))" build/gates/$(GATE_NAME).xml); \
	set -- $$counts; \
	if [ "$$2" -ne 0 ]; then \
		echo "$(GATE_NAME): $$2 test(s) were skipped — a blocking gate must not be silenced."; \
		echo "  Remove the skip, or delete the test deliberately and re-measure the floor."; \
		exit 1; fi; \
	if [ "$$1" -lt "$(GATE_MIN)" ]; then \
		echo "$(GATE_NAME): only $$1 test(s) executed, below the floor of $(GATE_MIN)."; \
		exit 1; fi; \
	echo "$(GATE_NAME): $$1 tests executed (floor $(GATE_MIN)), 0 skipped."

# The one perf spec that is opt-in by design. tests/perf/
# test_perf_baseline_is_honest.py::test_documented_headroom_still_reproduces
# RE-MEASURES the laptop-specific latency envelope, so its own docstring says it
# is "deliberately NOT part of the blocking perf-gate job" — but it lives on
# PERF_TEST_PATHS, so it *was* part of it, and its skipif made the whole job
# exit 2 on a clean tree (MEASURED: `10 passed, 1 skipped` -> gate-min-executed
# "a blocking gate must not be silenced"). Deselecting it is the fix that
# matches the documented intent; weakening the anti-skip guard would re-open
# GAME-3 (a wholly skipped gate suite passing). It is deselected from the RUN
# only, not from gate-min-collected: the collection floor stays at its measured
# 11 and tests/unit/test_perf_gate_collection_floor.py keeps re-measuring it.
# Fail-closed on rename: pytest ignores a --deselect that matches nothing, the
# skip comes back, and the gate goes red rather than quietly measuring less.
PERF_GATE_DESELECT ?= --deselect tests/perf/test_perf_baseline_is_honest.py::test_documented_headroom_still_reproduces
# ...so the EXECUTED floor is the collection floor minus that one deselection.
PERF_MIN_EXECUTED ?= $(shell expr $(PERF_MIN_TESTS) - 1)

# R2 P0-E: hermetic ($0, stubbed-provider) p50/p95 latency + concurrency gate.
# --no-cov because a partial run would trip the global --cov-fail-under=88.
# SENTRY_DSN= for the same reason mutation-baseline pins it: never let a
# repo-level DSN turn a gate documented as making no outbound calls into one.
# `make perf-gate` is itself executed end-to-end by tests/unit/
# test_perf_gate_runs_clean.py — every other perf guard inspects this target
# instead of running it, and all of them stayed green while it exited 2.
perf-gate:
	@$(MAKE) --no-print-directory gate-min-collected GATE_NAME=perf-gate GATE_PATHS="$(PERF_TEST_PATHS)" GATE_MIN=$(PERF_MIN_TESTS)
	SENTRY_DSN= UV_CACHE_DIR=$(UV_CACHE_DIR) OPENROUTER_LIVE_EXECUTION_ENABLED=false QUORUM_RUNTIME_ENVIRONMENT=ci QUORUM_RUN_PERF_BUDGET=1 uv run pytest $(PERF_TEST_PATHS) $(PERF_GATE_DESELECT) -q --no-cov --junitxml=build/gates/perf-gate.xml
	@$(MAKE) --no-print-directory gate-min-executed GATE_NAME=perf-gate GATE_MIN=$(PERF_MIN_EXECUTED)

# R2 P0-F: schemathesis contract fuzzing against the app's own /openapi.json,
# driven in-process (ASGI) so it is hermetic and $0.
api-contract:
	@$(MAKE) --no-print-directory gate-min-collected GATE_NAME=api-contract GATE_PATHS="$(CONTRACT_TEST_PATHS)" GATE_MIN=$(CONTRACT_MIN_TESTS)
	SENTRY_DSN= UV_CACHE_DIR=$(UV_CACHE_DIR) OPENROUTER_LIVE_EXECUTION_ENABLED=false QUORUM_RUNTIME_ENVIRONMENT=ci uv run pytest $(CONTRACT_TEST_PATHS) -q --no-cov --junitxml=build/gates/api-contract.xml
	@$(MAKE) --no-print-directory gate-min-executed GATE_NAME=api-contract GATE_MIN=$(CONTRACT_MIN_TESTS)

# R2 P0-D (ledger RB-7): mutation score on CHANGED FUNCTIONS.
#
# Whole-module mutation is both gameable and slow — measured: 1009 mutants for
# query_runs.py alone. So the scope is derived from the diff: every Python
# function under src/ whose body overlaps a line changed vs $(DIFF_BASE) (plus
# uncommitted working-tree changes) is turned into a mutmut mutant-name glob.
#
# ADVISORY (non-blocking) until $(MUTATION_ADVISORY_UNTIL) per the locked
# 2-week decision — the leading `-` is what makes it advisory. Delete the `-`
# to make it blocking. The recipe below FAILS CLOSED so that promotion is safe:
# an unresolvable $(DIFF_BASE) is a hard error rather than silently an empty
# scope, `mutmut run` is not piped so its exit status survives,
# stale `mutants/` metadata is removed first, and `report` exits non-zero both
# below threshold AND when zero mutants were scored, and its status reaches
# make because it is redirected, not piped into `tee` (tee's 0 would win). Every
# one of those is covered by tests/unit/test_mutation_gate_integrity.py, and the
# promotion itself — `-` deleted, below-threshold report, make exits non-zero —
# is executed in tests/unit/test_mutation_gate_blocking.py.
# Threshold derivation and the raw baseline: docs/metrics/mutation-baseline.md.
# Re-measured 2026-07-19: the RB-3 leak fix widened the changed-function scope
# from 425 to 504 mutants and the score fell to a measured 87.2-88.7% across
# five runs, so the old 90 floor is retired. 80 = lowest observed (87.2) minus
# the same 6.4-point harness-noise headroom the previous derivation used.
MUTATION_MIN_SCORE ?= 80
MUTATION_ADVISORY_UNTIL ?= 2026-08-02
MUTMUT_MAX_CHILDREN ?= 8

define MUTMUT_SCOPE_PY
import ast, collections, glob, json, os, re, subprocess, sys

mode, base, threshold = sys.argv[1], sys.argv[2], float(sys.argv[3])


def changed_lines():
    """New-side line numbers per file, from the merge-base diff + the worktree."""
    ranges = {}
    for args in (["diff", "-U0", base + "...HEAD", "--", "src"], ["diff", "-U0", "HEAD", "--", "src"]):
        proc = subprocess.run(["git"] + args, capture_output=True, text=True)
        if proc.returncode != 0:
            # Fail closed: an unresolvable base ref (fork PR, renamed default
            # branch, unfetched ref) otherwise yields an empty scope and the
            # recipe reports "nothing to mutate" and passes.
            print("git %s failed (rc=%d) for base '%s': %s" % (
                " ".join(args), proc.returncode, base, proc.stderr.strip()))
            raise SystemExit(1)
        out = proc.stdout
        path = None
        for line in out.splitlines():
            if line.startswith("+++ b/"):
                path = line[6:]
            elif line.startswith("@@") and path and path.endswith(".py") and os.path.exists(path):
                m = re.search(r"\+(\d+)(?:,(\d+))?", line)
                start, count = int(m.group(1)), int(m.group(2) or 1)
                ranges.setdefault(path, set()).update(range(start, start + count))
    return ranges


def scope():
    """Changed functions -> mutmut mutant-name globs (xǁClassǁmethod / x_function)."""
    globs = []
    for path, lines in sorted(changed_lines().items()):
        module = path.removeprefix("src/").removesuffix(".py").replace("/", ".")
        with open(path) as handle:
            tree = ast.parse(handle.read())

        def walk(node, cls=None):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    walk(child, child.name)
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    span = range(child.lineno, (child.end_lineno or child.lineno) + 1)
                    if lines & set(span):
                        name = "xǁ%sǁ%s" % (cls, child.name) if cls else "x_%s" % child.name
                        globs.append("%s.%s__mutmut_*" % (module, name))
                    walk(child, cls)

        walk(tree)
    print("\n".join(sorted(set(globs))))


def report():
    """Score the run. Timeouts are reported but excluded: measured, they are a
    harness artifact of mutmut's fork-based runner on this app, not evidence
    that a test caught the mutant."""
    counts = collections.Counter()
    survivors = []
    for meta in glob.glob("mutants/src/**/*.py.meta", recursive=True):
        with open(meta) as handle:
            data = json.load(handle)
        for key, code in data["exit_code_by_key"].items():
            if code is None:
                continue
            bucket = {0: "survived", 33: "no_tests", 37: "type_check"}.get(code, "killed" if code > 0 else "timeout")
            counts[bucket] += 1
            if bucket == "survived":
                survivors.append(key)
    checked = counts["killed"] + counts["survived"]
    print("mutants scored: %d killed, %d survived, %d timeout (excluded), %d no-tests" % (
        counts["killed"], counts["survived"], counts["timeout"], counts["no_tests"]))
    if not checked:
        # Fail closed: absent/crashed run == no measurement, not a perfect score.
        print("no mutants were scored — the run did not happen (empty or absent mutants/)")
        raise SystemExit(1)
    score = 100.0 * counts["killed"] / checked
    for key in sorted(survivors):
        print("  SURVIVED %s" % key)
    print("mutation score (killed / (killed+survived)) = %.1f%% (threshold %.0f%%)" % (score, threshold))
    if score < threshold:
        print("BELOW THRESHOLD")
        raise SystemExit(1)


{"scope": scope, "report": report}[mode]()
endef
export MUTMUT_SCOPE_PY

mutation-baseline:
	@echo "mutation-baseline: ADVISORY until $(MUTATION_ADVISORY_UNTIL) — changed functions in $(MUTMUT_PATHS) vs $(DIFF_BASE), threshold $(MUTATION_MIN_SCORE)%"
	@mkdir -p build/mutation
	@printf '%s' "$$MUTMUT_SCOPE_PY" | $(PYTHON) - scope $(DIFF_BASE) $(MUTATION_MIN_SCORE) > build/mutation/scope.txt
	@echo "changed functions in scope:"; sed 's/^/  /' build/mutation/scope.txt
	-@if [ -s build/mutation/scope.txt ]; then \
		rm -rf mutants; \
		SENTRY_DSN= OPENROUTER_LIVE_EXECUTION_ENABLED=false QUORUM_RUNTIME_ENVIRONMENT=ci QUORUM_TOKEN_SECRET=mutation-baseline UV_CACHE_DIR=$(UV_CACHE_DIR) \
			uv run mutmut run --max-children $(MUTMUT_MAX_CHILDREN) $$(tr '\n' ' ' < build/mutation/scope.txt) > build/mutation/run.log 2>&1 \
			|| { tail -40 build/mutation/run.log; echo "mutation-baseline: mutmut run failed — see build/mutation/run.log"; echo "  'failed to collect stats' == the suite cannot run inside ./mutants/, usually a repo-root file missing from [tool.mutmut].also_copy (guarded by tests/unit/test_mutation_copy_completeness.py)"; exit 1; }; \
		tail -40 build/mutation/run.log; \
		printf '%s' "$$MUTMUT_SCOPE_PY" | $(PYTHON) - report $(DIFF_BASE) $(MUTATION_MIN_SCORE) > build/mutation/score.txt; \
		status=$$?; cat build/mutation/score.txt; exit $$status; \
	else \
		echo "no changed Python functions under src/ vs $(DIFF_BASE) — nothing to mutate"; \
	fi

# R2 P0-G: changed-lines coverage vs $(DIFF_BASE) must be >= $(DIFF_COVER_MIN)%.
# Legacy uncovered lines are untouched; only new/changed code is held to the
# bar (the global floor stays 88% via --cov-fail-under in pyproject.toml).
# Requires a full-depth checkout (fetch-depth: 0) AND the base ref fetched, or
# diff-cover exits 1 with "Could not find the branch to compare to" — measured,
# it fails loud rather than silently scoring zero changed lines.
# Measured on feat/r2-s1-run-history-persistence: 165 changed lines, 4 missing,
# 97% — see docs/metrics/diff-cover.md.
DIFF_COVER_MIN ?= 95
diff-cover:
	mkdir -p build/coverage
	@git rev-parse --verify --quiet $(DIFF_BASE) >/dev/null || { \
		echo "diff-cover: base ref '$(DIFF_BASE)' is missing."; \
		echo "  CI needs actions/checkout with fetch-depth: 0 plus an explicit"; \
		echo "  'git fetch origin <base>'. Locally: git fetch origin main."; \
		exit 1; }
	SENTRY_DSN= UV_CACHE_DIR=$(UV_CACHE_DIR) uv run pytest --cov=src --cov-report=xml:build/coverage/coverage.xml
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run diff-cover build/coverage/coverage.xml \
		--compare-branch=$(DIFF_BASE) \
		--fail-under=$(DIFF_COVER_MIN) \
		--markdown-report build/coverage/diff-cover.md

security-scan: check-python
	$(PYTHON) scripts/security_scan.py

ci-evidence: test-report security-scan

run:
	UV_CACHE_DIR=$(UV_CACHE_DIR) PYTHONPATH=src uv run uvicorn product_app.main:app --host 0.0.0.0 --port 8000 $(if $(filter 1 true yes on,$(RELOAD)),--reload,)

docker-build:
	docker build -t quorum-ai:local .

feedback-audit:
	@if [ -z "$$OPENROUTER_API_KEY" ]; then 		echo "OPENROUTER_API_KEY is required for the audit LLM call."; 		echo "Without it, the audit runs in local-only mode (statistics only)."; 		echo "Set OPENROUTER_LIVE_EXECUTION_ENABLED=true and OPENROUTER_API_KEY to enable findings."; 	fi
	mkdir -p feedback
	UV_CACHE_DIR=$(UV_CACHE_DIR) PYTHONPATH=src uv run python -m product_app.feedback_audit --output-dir feedback/

skill-route: check-python
	$(PYTHON) scripts/skill_router.py

apply-orbi-profile: check-python
	$(PYTHON) scripts/apply_profile.py orbi

publishing-check: check-python
	$(PYTHON) scripts/validate_publishing_backbone.py

handoff: check-python
	$(PYTHON) scripts/session_handoff.py

skill-discover: check-python
	$(PYTHON) scripts/discover_external_skills.py

skill-onboarding-check: check-python
	$(PYTHON) scripts/validate_skill_onboarding.py

check-breaking: check-python
	$(PYTHON) scripts/check_breaking.py
