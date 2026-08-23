# Python runner: prefer python3, fall back to python.
# Override when needed: make PYTHON=/path/to/python3 <target>
PYTHON ?= $(shell if command -v python3 >/dev/null 2>&1; then command -v python3; elif command -v python >/dev/null 2>&1; then command -v python; fi)
UV_CACHE_DIR ?= $(CURDIR)/.uv-cache
RELOAD ?= 0


# --- R2 Phase-0 gate configuration -------------------------------------
# Perf specs live under tests/perf (tests/performance/ was a duplicate
# top-level directory covering the same concern; merged into tests/perf/ by
# housekeeping PR 5 -- its one spec, test_query_run_performance_evidence.py,
# moved over with no behaviour change). This is HARDCODED, never
# $(wildcard ...): a glob over a deleted or renamed directory expands to
# nothing, the recipe degrades to a bare `pytest -q --no-cov`, and pytest
# falls back to `testpaths = ["tests"]` — so a "blocking" gate passes the
# ordinary suite while measuring nothing. A hardcoded missing path makes pytest
# exit 4 instead. See gate-min-collected below for the emptied-directory case.
PERF_TEST_PATHS ?= tests/perf
CONTRACT_TEST_PATHS ?= tests/contract
# Collection floors, MEASURED on the R2 Phase-0 tree that adds tests/perf (no
# earlier commit contains that directory, so there is no revision to cite):
# perf collects 12 (all under tests/perf as of housekeeping PR 5; previously
# 11 in tests/perf + 1 in tests/performance/), contract collects 23.
# (S4/FR-017 added tests/perf/test_eval_batch_baseline.py, +1.)
# Perf is floored at its exact count (hand-authored specs) — tests/unit/
# test_perf_gate_collection_floor.py re-measures it and fails on any drift, so
# the floor cannot quietly sink below the suite. Contract is floored below its
# count because schemathesis parametrises off the live OpenAPI schema, so the
# number legitimately moves with the API surface; the floor only has to catch a
# deleted/emptied suite. That job needs it ABOVE the largest single contract
# module — measured: schemathesis 17, hand-authored OpenAPI 6 — or deleting the
# hand-authored half leaves 17 over a floor of 10 and api-contract stays green.
# R2-S3 added tests/contract/test_evaluation_signal_schema_additive.py (3 stable
# hand-authored cases), so tests/contract now collects 32. 22 clears the largest
# single module (schemathesis 17) and leaves 10 of slack for a legitimately
# shrinking API surface — it is deliberately NOT pinned to the exact 32, per
# the collection-floor test's documented rationale (schemathesis moves with the
# schema); tests/unit/test_contract_gate_collection_floor.py re-measures both.
PERF_MIN_TESTS ?= 12
CONTRACT_MIN_TESTS ?= 22
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
# NOTE: there is deliberately no MUTMUT_PATHS variable. One existed, said
# `src/product_app`, and was read by nothing but a banner — while the scope
# code diffs `-- src` (which also holds src/httpx2). A decorative variable that
# disagrees with the real pathspec is a lie waiting to be believed; the banner
# now states the pathspec the code actually uses.

.PHONY: check-python publishing-check skill-onboarding-check skill-discover handoff check-breaking apply-orbi-profile skill-route start next capture-idea validate validate-strict fr-completeness openapi-export openapi-check adr-index-check quality format format-check lint type-check test evals test-report gate-min-collected gate-min-executed perf-gate api-contract mutation-baseline diff-cover security-scan close-guard ci-evidence run docker-build feedback-audit

check-python:
	@if [ -z "$(PYTHON)" ]; then 		echo "ERROR: Python 3 is required. Install python3, or set PYTHON=/path/to/python3."; 		exit 127; 	fi
	@$(PYTHON) -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 'ERROR: Python 3.10+ required. Found ' + '.'.join(map(str, sys.version_info[:3])) + '. Set PYTHON=/path/to/python3 or upgrade Python.')"

start: next

next: check-python
	$(PYTHON) scripts/factory_next.py

capture-idea: check-python
	@if [ -n "$(IDEA)" ]; then 		$(PYTHON) scripts/capture_idea.py "$(IDEA)"; 	else 		$(PYTHON) scripts/capture_idea.py; 	fi

validate: check-python fr-completeness adr-index-check
	$(PYTHON) scripts/validate_all.py

# The ADR index is a DERIVED fact. It went stale by hand twice; it is now
# generated and verified rather than trusted. See ADR-0004..0007's arrival.
adr-index-check:
	$(PYTHON) scripts/generate_adr_index.py --check

validate-strict: check-python fr-completeness
	FACTORY_STRICT=1 $(PYTHON) scripts/validate_all.py

# R2 EN-2/FS-3: fail if an FR-0NN in docs/10 has no row in BOTH docs/17 and
# docs/18. Stdlib-only, like the other factory validators, so it runs without
# a uv environment. Part of the `validate` chain and build-failing in CI.
fr-completeness: check-python
	@# --min-requirements: every check in this gate is "no requirement lacks a
	@# row", which passes trivially over zero requirements. Measured: truncating
	@# the requirements doc to 2 sections dropped the parsed count from 29 to 14
	@# and the gate still printed OK. The floor is the positive partner.
	$(PYTHON) scripts/validate_fr_completeness.py --min-requirements 25

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

# OD-4: run the eval suites and print an honest per-suite summary table.
# Counts come from the real pytest run; the two pinned pilot measurements
# are cited with their pinning docs, never restated as fresh numbers.
evals:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run python scripts/evals_summary.py

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
	@if [ ! -f "build/gates/$(GATE_NAME).xml" ]; then \
		echo "$(GATE_NAME): build/gates/$(GATE_NAME).xml is missing — the gate suite never produced its JUnit XML."; \
		echo "  A gate measures or it fails; a missing report must never pass silently."; \
		exit 1; fi
	@counts=$$(UV_CACHE_DIR=$(UV_CACHE_DIR) uv run python -c "import sys, xml.etree.ElementTree as ET; r = ET.parse(sys.argv[1]).getroot(); ss = [r] if r.tag == 'testsuite' else r.findall('testsuite'); t=sum(int(s.attrib.get('tests',0)) for s in ss); f=sum(int(s.attrib.get('failures',0)) for s in ss); e=sum(int(s.attrib.get('errors',0)) for s in ss); sk=sum(int(s.attrib.get('skipped',0)) for s in ss); print(t-f-e, sk)" build/gates/$(GATE_NAME).xml); \
	set -- $$counts; \
	if [ $$# -ne 2 ]; then \
		echo "$(GATE_NAME): could not derive executed/skipped counts from build/gates/$(GATE_NAME).xml — refusing to pass a gate it cannot measure."; \
		exit 1; fi; \
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
	SENTRY_DSN= UV_CACHE_DIR=$(UV_CACHE_DIR) OPENROUTER_LIVE_EXECUTION_ENABLED=false QUORUM_RUNTIME_ENVIRONMENT=ci QUORUM_RUN_PERF_BUDGET=1 uv run pytest $(PERF_TEST_PATHS) $(PERF_GATE_DESELECT) -q -s --no-cov --junitxml=build/gates/perf-gate.xml
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
# ADVISORY IN CI, HONEST LOCALLY. There is no leading `-` on the recipe, so a
# below-threshold score really does fail `make` — the exit status tells the
# truth here and in the job's own status. What makes it advisory is
# `continue-on-error` on the CI job alone, so it reports without blocking a
# merge. That split is deliberate: the old arrangement had BOTH switches on,
# which meant a crashed run looked identical to a clean one. Measured evidence
# for the advisory decision: docs/metrics/mutation-gate-study.md. The recipe
# FAILS CLOSED throughout: an unresolvable $(DIFF_BASE) is a hard error rather
# than silently an empty scope, `mutmut run` is not piped so its exit status
# survives, stale `mutants/` metadata is removed first, and `report` exits
# non-zero both below threshold AND when zero mutants were scored, and its
# status reaches make because it is redirected, not piped into `tee` (tee's 0
# would win). Every one of those is covered by
# tests/unit/test_mutation_gate_integrity.py, and the blocking behaviour itself
# — the shipped recipe, a below-threshold report, make exits non-zero — is
# executed in tests/unit/test_mutation_gate_blocking.py.
#
# The promotion condition recorded in docs/metrics/mutation-baseline.md §5 was
# "not until the timeout storm is fixed or RING-FENCED". It is ring-fenced two
# ways, both measured: timeouts are excluded from the score's denominator, and
# a scope in which EVERYTHING timed out is no longer conflated with a run that
# never happened (see `report`). Measured worst case that made the second
# ring-fence necessary: 66/66 mutants of `_persist_terminal_run` timed out
# under mutmut while the same tests pass in 1.34s standalone.
# Threshold derivation and the raw baseline: docs/metrics/mutation-baseline.md.
# Re-measured 2026-07-19: the RB-3 leak fix widened the changed-function scope
# from 425 to 504 mutants and the score fell to a measured 87.2-88.7% across
# five runs, so the old 90 floor is retired. 80 = lowest observed (87.2) minus
# the same 6.4-point harness-noise headroom the previous derivation used.
MUTATION_MIN_SCORE ?= 80
MUTMUT_MAX_CHILDREN ?= 8
# Issue #182: the CI job's `timeout-minutes: 30` is a JOB-level GitHub
# Actions setting. When IT fires mid-run, the whole job (including the
# report() step below) dies with no score printed at all -- reproduced on
# PR #181 (30m16s, killed mid-mutant, zero score line). `run_with_deadline.py`
# gives `mutmut run` its OWN, shorter, internally-enforced deadline, so this
# recipe always reaches `report()` -- which scores whatever
# `mutants/**/*.py.meta` state exists, partial or complete, since mutmut
# writes those incrementally per mutant (verified against the installed
# mutmut/mutation/data.py: `register_result` calls `self.save()` after every
# completed mutant). 1440s (24m) leaves ~6 minutes of the 30-minute job
# budget for checkout/setup/report -- a judgment call with margin, not a
# freshly measured number (a real 24-minute mutation run was not executed
# to re-derive it, to avoid burning CI minutes on this batch); the CI job's
# own setup steps (checkout, fetch base ref, setup-uv, python install, uv
# sync) are comfortably under a minute in the existing measured baseline
# above, so the margin here is intentionally generous.
MUTATION_RUN_DEADLINE_SECONDS ?= 1440

# #337. scripts/run_with_deadline.py drops this file when it kills the run for
# exceeding the deadline above, and deletes any stale one when it does not.
# report() reads it and refuses to print a percentage for a truncated run.
# ONE definition, passed to both readers below as RUN_WITH_DEADLINE_MARKER, so
# the writer's path and the reader's path cannot drift apart.
#
# `override :=`, NOT `?=`: `?=` yields to the environment, and adversarial
# review demonstrated `MUTATION_TRUNCATION_MARKER=/dev/null make
# mutation-baseline` making a completed, below-threshold run report UNMEASURED
# and exit 0. There is no legitimate reason to point this anywhere else.
override MUTATION_TRUNCATION_MARKER := build/mutation/truncated

define MUTMUT_SCOPE_PY
import ast, collections, glob, io, json, os, re, subprocess, sys, tokenize

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


def unmutatable(node):
    """True when mutmut will not generate mutants for this function.

    Mirrors mutmut/mutation/file_mutation.py:230-235 - decorated functions are
    skipped because the trampoline copy re-runs decorators, EXCEPT a lone bare
    @staticmethod/@classmethod, which it handles. Measured on this tree: 34 of
    the 40 decorated functions under src/product_app are unmutatable.
    """
    decorators = getattr(node, "decorator_list", [])
    if not decorators:
        return False
    if len(decorators) == 1:
        only = decorators[0]
        if isinstance(only, ast.Name) and only.id in ("staticmethod", "classmethod"):
            return False
    return True


def _joined_str_has_a_real_string_literal(node, source):
    """True when a `JoinedStr` contains a PLAIN (non-f) string token.

    stdlib `ast` merges Python's implicit adjacent-literal concatenation
    (``f"a {x}" "b"``) into ONE `JoinedStr`, with the plain literal's text
    folded into an ordinary `Constant` sub-part indistinguishable from real
    f-string text. libcst does NOT merge them: it keeps the plain segment as
    its own `cst.SimpleString`, which `operator_string` DOES mutate.
    Measured directly (`providers._local_simulation_text`, #146): 3 real
    mutants, all from the plain segment stdlib `ast` had hidden.

    Tokenizing the node's own source segment tells the two apart: Python
    3.12+'s tokenizer emits FSTRING_START/MIDDLE/END for an f-string's own
    text, so a `tokenize.STRING` token appearing in that segment can only be
    a separate, plain literal glued on by implicit concatenation.
    """
    segment = ast.get_source_segment(source, node)
    if segment is None:
        return True  # can't prove it safe -- caller fails closed on this
    try:
        tokens = tokenize.generate_tokens(io.StringIO(segment).readline)
        return any(tok.type == tokenize.STRING for tok in tokens)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return True


def _safe_comprehension(generators, source):
    """True when every `for ... in ...` clause of a comprehension is safe.

    No mutmut operator targets a comprehension's `for`/`if` clauses
    structurally (there is no `cst.CompFor` entry in `mutation_operators`),
    so only the ITER and IFS sub-expressions can carry real content.
    """
    for gen in generators:
        if not _safe_expr(gen.iter, source):
            return False
        if any(not _safe_expr(cond, source) for cond in gen.ifs):
            return False
    return True


# mutmut's `operator_name` (mutators.py's `name_mappings`) rewrites a bare
# `Name` node with this exact identifier, REGARDLESS of whether it sits in a
# call with arguments, without arguments, or isn't called at all. `_safe_expr`
# must never call a `Call`'s callee (or any bare `Name`) safe when it is one
# of these (#146 false-exclusion bug: a zero-arg `deepcopy()` was wrongly
# excluded because the args-only fast path never looked at the callee name).
_MUTMUT_RENAMED_NAMES = frozenset({"deepcopy"})

# mutmut's `operator_symmetric_string_methods_swap` /
# `operator_unsymmetrical_string_methods_swap` rewrite a method `Call` to its
# opposite purely by matching the ATTRIBUTE NAME on `node.func` -- neither
# checks argument count first, so a zero-arg `x.lower()` is still a real
# mutant (`x.upper()`).
_MUTMUT_SWAPPABLE_METHOD_NAMES = frozenset(
    {
        "lower",
        "upper",
        "lstrip",
        "rstrip",
        "find",
        "rfind",
        "ljust",
        "rjust",
        "index",
        "rindex",
        "removeprefix",
        "removesuffix",
        "partition",
        "rpartition",
        "split",
        "rsplit",
    }
)


def _safe_expr(node, source):
    """True when mutmut has NO operator that can touch this expression.

    Mirrors mutmut/mutation/mutators.py's `mutation_operators` table exactly
    for the shapes this repo's dead functions actually use (#146): a bare
    name/attribute chain, `None`/`...`, a call with NO positional or keyword
    args (operator_arg_removal needs >=1 to remove or None-replace,
    operator_dict_arguments needs a keyword arg to `dict(...)`), an IfExp
    over such sub-expressions (no operator targets ast.IfExp itself), an
    f-string built only from safe placeholders and NO implicitly-concatenated
    plain string (operator_string type-checks `isinstance(node,
    cst.SimpleString)` and yields nothing for a `cst.FormattedString`, but
    DOES mutate a plain literal glued on next to it), and a comprehension
    over safe sub-expressions (no operator targets a comprehension's
    `for`/`if` clauses). A bare `Name`/callee is safe UNLESS it is a name
    `operator_name` rewrites, and a method `Call` is safe UNLESS its
    attribute name is one `operator_symmetric_string_methods_swap` /
    `operator_unsymmetrical_string_methods_swap` swap regardless of args
    (#146 false-exclusion bug).

    FAILS CLOSED: any expression shape not explicitly listed here returns
    False, so this can under-detect (leaving a truly-dead function scoped,
    today's status quo) but can never wrongly call a mutable expression safe.
    """
    if node is None:
        return True
    if isinstance(node, ast.Name):
        return node.id not in _MUTMUT_RENAMED_NAMES
    if isinstance(node, ast.Attribute):
        return _safe_expr(node.value, source)
    if isinstance(node, ast.Constant):
        return node.value is None or node.value is Ellipsis
    if isinstance(node, ast.Call):
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in _MUTMUT_SWAPPABLE_METHOD_NAMES
        ):
            return False
        if node.args or node.keywords:
            return False
        return _safe_expr(node.func, source)
    if isinstance(node, ast.IfExp):
        return (
            _safe_expr(node.test, source)
            and _safe_expr(node.body, source)
            and _safe_expr(node.orelse, source)
        )
    if isinstance(node, ast.Tuple | ast.List):
        return all(_safe_expr(elt, source) for elt in node.elts)
    if isinstance(node, ast.JoinedStr):
        if _joined_str_has_a_real_string_literal(node, source):
            return False
        for part in node.values:
            if isinstance(part, ast.Constant):
                continue  # literal text: operator_string ignores FormattedString entirely
            if isinstance(part, ast.FormattedValue):
                if part.format_spec is not None or not _safe_expr(part.value, source):
                    return False
                continue
            return False
        return True
    if isinstance(node, ast.DictComp):
        return (
            _safe_expr(node.key, source)
            and _safe_expr(node.value, source)
            and _safe_comprehension(node.generators, source)
        )
    if isinstance(node, ast.ListComp | ast.SetComp | ast.GeneratorExp):
        return _safe_expr(node.elt, source) and _safe_comprehension(node.generators, source)
    return False


def no_mutable_content(func, source):
    """True when NOTHING mutmut can mutate lives anywhere in `func`.

    Recurses into a nested `def` inside `func` too (skipping it only if it is
    itself `unmutatable()`), because mutmut attributes every mutation inside a
    nested function to the SAME enclosing top-level name
    (OuterFunctionProvider) - see `walk()`. A changed line whose enclosing
    function is entirely inert this way still names a glob mutmut generates
    zero mutants for, the same abort/silent-gap #136 already covers for
    decorated functions.

    FAILS CLOSED like `_safe_expr`: an unrecognised statement shape (If, For,
    Assign, ...) makes the whole function ineligible for exclusion.
    """
    body = list(func.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        # A leading docstring never counts against a function: mutmut's own
        # operator_string explicitly excuses triple-quoted strings ("we
        # assume triple-quoted stuff are docs").
        body = body[1:]
    if not body:
        return True

    def safe_stmts(stmts):
        for stmt in stmts:
            if isinstance(stmt, ast.Pass):
                continue
            if isinstance(stmt, ast.Return | ast.Expr):
                if not _safe_expr(stmt.value, source):
                    return False
                continue
            if isinstance(stmt, ast.With | ast.AsyncWith):
                for item in stmt.items:
                    if not _safe_expr(item.context_expr, source):
                        return False
                    if item.optional_vars is not None and not isinstance(item.optional_vars, ast.Name):
                        return False
                if not safe_stmts(stmt.body):
                    return False
                continue
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                if unmutatable(stmt):
                    continue
                if not no_mutable_content(stmt, source):
                    return False
                continue
            # If/For/While/Try/Assign/Raise/... are not provably inert.
            return False
        return True

    return safe_stmts(body)


def scope():
    """Changed functions -> mutmut mutant-name globs (xǁClassǁmethod / x_function)."""
    globs = []
    skipped = []
    for path, lines in sorted(changed_lines().items()):
        module = path.removeprefix("src/").removesuffix(".py").replace("/", ".")
        with open(path) as handle:
            source = handle.read()
        tree = ast.parse(source)

        def walk(node, cls=None, frozen=False):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    # A DECORATED class is skipped by mutmut together with its
                    # WHOLE SUBTREE (file_mutation.py:236-237 returns True from
                    # _skip_node_and_children, and on_visit stops descending).
                    # So every method inside it is unmutatable, decorated or not
                    # - e.g. every @dataclass. Missing this left #136 reachable
                    # from _Session.is_expired and three others.
                    walk(child, child.name, frozen or bool(child.decorator_list))
                elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    span = range(child.lineno, (child.end_lineno or child.lineno) + 1)
                    if lines & set(span):
                        if frozen or unmutatable(child):
                            # mutmut cannot build a trampoline for this function,
                            # so naming it yields a glob that matches nothing. With
                            # a scope made ONLY of these, `mutmut run` dies with
                            # "Filtered for specific mutants, but nothing matches"
                            # and the recipe blames also_copy - the wrong cause.
                            # Measured over history: 7% of changes abort this way,
                            # 38% carry one silently. Excluded and REPORTED (#136).
                            skipped.append("%s.%s [decorated]" % (module, child.name))
                        elif no_mutable_content(child, source):
                            # #146: genuinely nothing for any mutmut operator to
                            # touch anywhere in this function (own body or a
                            # nested def inside it) - same dead-glob abort as
                            # the decorated case, different cause.
                            skipped.append("%s.%s [no mutable content]" % (module, child.name))
                        else:
                            name = "xǁ%sǁ%s" % (cls, child.name) if cls else "x_%s" % child.name
                            globs.append("%s.%s__mutmut_*" % (module, name))
                            # #337. mutmut reads this same list TWICE, and the
                            # two readers want DIFFERENT spellings of the name:
                            #   * collect_source_file_mutation_data() matches it
                            #     against concrete mutant keys, which do carry
                            #     the suffix ("<mod>.<name>__mutmut_7") - that
                            #     is what the glob above is for; and
                            #   * tests_for_mutant_names() matches it against
                            #     the MANGLED names recorded during stats
                            #     collection, which carry NO suffix at all
                            #     ("<mod>.<name>", mangled_name_from_mutant_name
                            #     partitions it off before recording).
                            # A suffixed glob matches zero mangled names, so
                            # tests_for_mutant_names() returned the EMPTY set -
                            # and mutmut's _pytest_args_regular_run() reads an
                            # empty test set as "no selection given" and runs
                            # the WHOLE suite in its clean-test phase, before a
                            # single mutant is scored. Measured on the three
                            # costs functions of PR #359: 0 mangled names
                            # matched and the clean phase ran all 2929 tests;
                            # the real association set is 258.
                            # `*<mod>.<name>` matches that mangled name and
                            # matches NO mutant key (every one has text after
                            # the name), so it narrows the clean phase without
                            # widening what gets mutated.
                            globs.append("*%s.%s" % (module, name))
                    # Do NOT recurse into a FunctionDef's body looking for
                    # further FunctionDefs: mutmut attributes EVERY mutation
                    # inside a nested `def` - at any depth - to this SAME
                    # enclosing name (OuterFunctionProvider), never to the
                    # nested def's own name. A nested def's lines are already
                    # inside `span` above, so the overlap check already
                    # caught it; minting a second, separate glob for the
                    # nested name produces one mutmut matches nothing (#146).

        walk(tree)
    # Only write anything when the scope is non-empty. `print("".join([]))`
    # emits a bare newline, which is 1 byte, which makes the recipe's
    # `[ -s build/mutation/scope.txt ]` TRUE — so the "nothing to mutate"
    # branch was unreachable and `mutmut run` was invoked with ZERO globs
    # (i.e. mutate everything) on every change that touched no src/ Python.
    # The advisory `-` hid that for as long as it existed; the first blocking
    # run surfaced it immediately.
    if skipped:
        # stderr, never stdout: stdout is redirected into scope.txt and a note
        # there would be read by `mutmut run` as a mutant name.
        sys.stderr.write(
            "mutation scope: %d changed function(s) cannot be mutated by mutmut "
            "(excluded so the run does not abort; reason per function below):\n%s\n"
            % (len(skipped), "\n".join("  " + n for n in sorted(set(skipped))))
        )
    if globs:
        print("\n".join(sorted(set(globs))))


def report():
    """Score the run. Timeouts are reported but excluded: measured, they are a
    harness artifact of mutmut's fork-based runner on this app, not evidence
    that a test caught the mutant."""
    # #142: mirrors mutmut's own status_by_exit_code map (mutmut/__main__.py)
    # instead of a sign test on the raw exit code. `"killed" if code > 0 else
    # "timeout"` treated ANY positive code not in a three-entry dict as a kill
    # — silently scoring pytest's NO_TESTS_COLLECTED (5, the same meaning as
    # mutmut's own 33), pytest's USAGE_ERROR (4), mutmut's other timeout codes
    # (24/36/152/255), and mutmut's `skipped` (34) as proof a test caught the
    # mutant. It also relabelled a segfault/OOM (-11/-9) as the same ordinary
    # fork-runner timeout this file already excuses.
    EXIT_STATUS = {
        0: "survived", 1: "killed", 3: "killed",
        5: "no_tests", 33: "no_tests",
        34: "skipped",
        24: "timeout", 36: "timeout", 152: "timeout", 255: "timeout", -24: "timeout",
        37: "type_check",
        4: "error",
        -9: "crash", -11: "crash",
        # Found by adversarial review of this fix: mutmut's own map has
        # `2: "check was interrupted by user"` (a local Ctrl-C mid-run) — the
        # first version of this dict omitted it, so it fell to the
        # "suspicious" default and read as a generic broken-run message
        # instead of naming what actually happened.
        2: "interrupted",
    }
    # #337: was the run cut short by its own wall-clock deadline?
    # scripts/run_with_deadline.py exits 0 when it kills the run, deliberately,
    # so that this function still gets to score whatever landed on disk. The
    # cost of that choice is invisible until the run reaches the mutant phase
    # at all: mutmut writes one .meta entry per FINISHED mutant and leaves the
    # rest at `None`, and the `code is None: continue` below skips exactly
    # those. Demonstrated on a synthetic .meta with 3 killed and 289 unfilled:
    # this function printed "mutation score = 100.0%" and exited 0.
    #
    # The wrapper drops a marker file when it kills the run and removes it when
    # it does not. Detection is by CONTENT, not by existence: the marker path
    # comes from the environment, and `os.path.exists` alone would let
    # `RUN_WITH_DEADLINE_MARKER=/dev/null` (or any pre-existing file) declare
    # every completed run truncated and skip the threshold check. Found by
    # adversarial review, demonstrated with /dev/null.
    TRUNCATION_SENTINEL = "run_with_deadline killed this run at "
    marker = os.environ.get("RUN_WITH_DEADLINE_MARKER", "")
    try:
        with open(marker) as handle:
            truncated = handle.read(len(TRUNCATION_SENTINEL)) == TRUNCATION_SENTINEL
    except OSError:
        # Unset, absent, or a directory: all mean "no wrapper said it killed
        # this run", which is the only thing this flag is allowed to assert.
        truncated = False
    counts = collections.Counter()
    survivors = []
    for meta in glob.glob("mutants/src/**/*.py.meta", recursive=True):
        with open(meta) as handle:
            data = json.load(handle)
        for key, code in data["exit_code_by_key"].items():
            if code is None:
                continue
            # Any code this map does not recognize fails closed as
            # "suspicious" rather than defaulting to a kill — an unenumerated
            # exit code is exactly the gap a sign test cannot see.
            bucket = EXIT_STATUS.get(code, "suspicious")
            counts[bucket] += 1
            if bucket == "survived":
                survivors.append(key)
    checked = counts["killed"] + counts["survived"]
    print("mutants scored: %d killed, %d survived, %d timeout (excluded), %d no-tests" % (
        counts["killed"], counts["survived"], counts["timeout"], counts["no_tests"]))
    if truncated:
        # Printed here, before every diagnosis below, so that whichever branch
        # fires carries the context. Found by adversarial review: mutmut sorts
        # its mutants by estimated cost ascending and a no-tests mutant costs
        # zero, so "all of the few mutants we reached were no-tests" is the
        # LIKELY shape of a real truncation - and that branch used to tell the
        # author to add a test without ever mentioning the budget.
        print("TRUNCATED: this run was cut short by its own wall-clock "
              "deadline. Every count below is a PREFIX of the scope, not the "
              "whole of it; the mutants the deadline never reached are "
              "unmeasured, not killed.")
    if (counts["skipped"] or counts["crash"] or counts["error"] or counts["suspicious"]
            or counts["type_check"] or counts["interrupted"]):
        # Found by adversarial review of the fix above: type_check (37, a
        # mutant caught by mypy rather than a test) was already excluded from
        # the score before this file, correctly — but was never named
        # anywhere in the printed summary, unlike every other excluded
        # bucket. A reader could not tell 10 type-checked mutants from 0.
        print("  (%d skipped, %d crash, %d error, %d type-checked, %d interrupted, "
              "%d suspicious/unrecognized exit code)" % (
            counts["skipped"], counts["crash"], counts["error"], counts["type_check"],
            counts["interrupted"], counts["suspicious"]))
    if counts["no_tests"]:
        # Checked BEFORE the `not checked` branch below, because a scope where
        # EVERY mutant is no_tests also has `killed + survived == 0` and would
        # otherwise be reported as "the run did not happen" — false, and the
        # same wrong-diagnosis bug this recipe already fixed for timeouts.
        # Measured: adding one untested function produced 6 no-tests, 0 killed,
        # 0 survived, and the old ordering blamed an absent mutants/ tree.
        #
        # exit 33 = mutmut found NO test covering this mutant. Those mutants are
        # not in `checked`, so they do not lower the score — they leave it. That
        # is the quietest way to fake a pass: silence a function's tests and its
        # mutants stop being counted rather than start failing. Measured on a
        # scratch tree, identical source, one added deselection marker: 63.6%
        # BELOW THRESHOLD became 100.0% pass, with 9 mutants moved to no_tests.
        # Changed code with no covering test is precisely what this gate exists
        # to catch, so it fails here instead of scoring around it.
        print("%d mutant(s) had NO covering test (no-tests). A changed function "
              "with no test cannot be measured, and these are excluded from the "
              "score — so this is a gap, not a pass. Add a test, or if the tests "
              "exist but are deselected under [tool.mutmut], that deselection is "
              "hiding this function." % counts["no_tests"])
        raise SystemExit(1)
    if counts["interrupted"]:
        # exit 2 = mutmut's own "check was interrupted by user" (a local
        # Ctrl-C mid-run). Named distinctly rather than folded into the
        # generic error/suspicious message below, so a developer who
        # interrupted their own local run sees why, instead of hunting for a
        # broken-run cause that never existed.
        print("%d mutant(s) were interrupted by the user (Ctrl-C) mid-run — "
              "not a kill, and not evidence of anything about the code under "
              "test. Re-run the gate to completion." % counts["interrupted"])
        raise SystemExit(1)
    if counts["error"] or counts["suspicious"]:
        # #142: a pytest USAGE_ERROR (4) or any exit code this map does not
        # recognize means the mutant was never genuinely tested — the same
        # "not a kill" gap as no_tests, so it fails closed the same way rather
        # than falling through to `killed` the way the old sign test did.
        print("%d mutant(s) exited with a broken-run or unrecognized code (a "
              "pytest usage error, or a code this gate does not know) — that "
              "is not a kill, and this gate refuses to guess. See the exit "
              "codes above." % (counts["error"] + counts["suspicious"]))
        raise SystemExit(1)
    if not checked:
        # Two very different states used to share one message, and the message
        # was only true of the first. Now the gate blocks, telling an author to
        # go hunting for a crashed run that did not crash costs real time.
        if counts["timeout"] or counts["crash"]:
            # Every mutant timed out or crashed. Measured (baseline §5): 66/66
            # mutants of _persist_terminal_run time out under mutmut's
            # fork-based runner while the same tests pass in 1.34s standalone.
            # Timeouts are already excluded from the score by a recorded
            # decision — counting them as survivors would fail the gate for a
            # tooling defect — and an all-timeout (or all-crash) scope is the
            # limit case of that same decision, so it is NOT failed here. It
            # is also NOT a pass: nothing was measured, and this line says so
            # in the log and in score.txt so it can never be read as a clean
            # score. #142: a segfault/OOM (crash) is named separately from an
            # ordinary fork-runner timeout — they are different failures and
            # the old sign test conflated them under one "timeout" label.
            parts = []
            if counts["timeout"]:
                parts.append("%d timed out" % counts["timeout"])
            if counts["crash"]:
                parts.append("%d crashed (segfault/OOM)" % counts["crash"])
            print("UNMEASURED: every mutant %s — a harness/environment "
                  "artifact, not a test failure. No mutation evidence for "
                  "this change." % " and ".join(parts))
            return
        if truncated:
            # #337's actual CI symptom, named correctly - and placed AFTER the
            # timeout/crash branch above, because a scope slow enough to time
            # every mutant out is a scope slow enough to hit the wall clock,
            # and "every mutant timed out" is the more specific true statement
            # when both hold. Adversarial review demonstrated this branch
            # printing "before a single mutant was scored" over a run in which
            # 66 mutants had timed out on the line above.
            #
            # The message this replaces was "the run did not happen (empty or
            # absent mutants/)" - false, and it sent three sessions reading
            # also_copy. It deliberately does NOT claim mutants/ is intact:
            # this function never looks at mutants/ beyond globbing for .meta
            # files, so that would be a second unverified claim in place of the
            # first (also an adversarial-review finding).
            print("UNMEASURED: the run was cut short by its own wall-clock "
                  "deadline before any mutant produced a kill-or-survive "
                  "verdict. This is the gate running out of budget, not a "
                  "statement about the diff. Widen "
                  "MUTATION_RUN_DEADLINE_SECONDS or narrow the scope.")
            raise SystemExit(1)
        # Fail closed: absent/crashed run == no measurement, not a perfect score.
        print("no mutants were scored — the run did not happen (empty or absent mutants/)")
        raise SystemExit(1)
    for key in sorted(survivors):
        print("  SURVIVED %s" % key)
    if truncated:
        # A partial run is NOT a score. The mutants the deadline never reached
        # are unmeasured, not killed, and dividing over only the ones that
        # finished reports a percentage of an arbitrary prefix of the scope.
        print("UNMEASURED: the run was cut short by its own wall-clock "
              "deadline after scoring %d of the scope's mutants. A partial "
              "run is not a score - no percentage is reported, because the "
              "mutants the deadline never reached are unmeasured, not "
              "killed." % checked)
        if counts["survived"]:
            # ... but a SURVIVOR is not a percentage. It is a mutant that ran
            # and that no test caught, and truncating the run afterwards does
            # not un-demonstrate it. Adversarial review found the first version
            # of this branch returning 0 over 7 survivors that had made the
            # same gate exit 1 the moment before the marker appeared - turning
            # a visibly RED job GREEN, which is the exact class of defect this
            # whole record exists to remove.
            #
            # This is deliberately STRICTER than the complete-run rule, which
            # tolerates survivors up to the threshold: over a prefix there is
            # no honest denominator to compare a threshold against, so the only
            # sound rule is that a demonstrated survivor fails.
            print("%d mutant(s) SURVIVED before the cut-off. A survivor is a "
                  "test gap that was DEMONSTRATED - it needs no denominator "
                  "and the rest of the run cannot take it back - so this "
                  "fails even though no score was produced." % counts["survived"])
            raise SystemExit(1)
        return
    score = 100.0 * counts["killed"] / checked
    print("mutation score (killed / (killed+survived)) = %.1f%% (threshold %.0f%%)" % (score, threshold))
    if score < threshold:
        print("BELOW THRESHOLD")
        raise SystemExit(1)


{"scope": scope, "report": report}[mode]()
endef
export MUTMUT_SCOPE_PY

mutation-baseline:
	@echo "mutation-baseline: ADVISORY in CI (reported, does not block a merge) — changed functions under src/ vs $(DIFF_BASE), threshold $(MUTATION_MIN_SCORE)%"
	@mkdir -p build/mutation
	@printf '%s' "$$MUTMUT_SCOPE_PY" | $(PYTHON) - scope $(DIFF_BASE) $(MUTATION_MIN_SCORE) > build/mutation/scope.txt
	@echo "changed functions in scope:"; sed 's/^/  /' build/mutation/scope.txt
	@# #337: the scope expansion below is deliberately UNQUOTED, because each
	@# line has to become its own argument -- and now that the scope also emits
	@# leading-asterisk oracle patterns, that expansion is subject to PATHNAME
	@# expansion as well. A repo-root file whose name happened to end in a
	@# mutant name would silently replace the pattern with that filename. The
	@# "set -f" below turns globbing off for this recipe; word-splitting is IFS
	@# and is unaffected, and nothing else on this branch relies on a glob.
	@if [ -s build/mutation/scope.txt ]; then \
		set -f; \
		rm -rf mutants; \
		SENTRY_DSN= OPENROUTER_LIVE_EXECUTION_ENABLED=false QUORUM_RUNTIME_ENVIRONMENT=ci QUORUM_TOKEN_SECRET=mutation-baseline UV_CACHE_DIR=$(UV_CACHE_DIR) \
			RUN_WITH_DEADLINE_MARKER=$(MUTATION_TRUNCATION_MARKER) \
			$(PYTHON) scripts/run_with_deadline.py $(MUTATION_RUN_DEADLINE_SECONDS) \
			uv run mutmut run --max-children $(MUTMUT_MAX_CHILDREN) $$(tr '\n' ' ' < build/mutation/scope.txt) > build/mutation/run.log 2>&1 \
			|| { tail -40 build/mutation/run.log; \
			echo "mutation-baseline: mutmut run failed — see build/mutation/run.log"; \
			echo "  THIS EXIT CODE IS ABOUT THE GATE, NOT ABOUT YOUR DIFF. No mutation"; \
			echo "  score was produced. A red job here is not evidence that anything"; \
			echo "  was measured — read the log and find the number before blaming the change."; \
			echo "  'failed to collect stats' == the suite could not run inside ./mutants/."; \
			echo "  Two causes, in the order they actually occur:"; \
			echo "    1. a check that resolves the repo root from __file__/parents[n]. Inside"; \
			echo "       ./mutants/ that points at the COPY, whose src/ carries one generated"; \
			echo "       x_<name>__mutmut_N variant per mutant — so any census of the source"; \
			echo "       counts mutmut's own output and blows its bound (#158). Resolve with"; \
			echo "       tests/repo_root.find_repo_root, or mark the module repo_introspection."; \
			echo "    2. a repo-root file missing from [tool.mutmut].also_copy"; \
			echo "       (guarded by tests/unit/test_mutation_copy_completeness.py)."; \
			exit 1; }; \
		tail -40 build/mutation/run.log; \
		printf '%s' "$$MUTMUT_SCOPE_PY" | RUN_WITH_DEADLINE_MARKER=$(MUTATION_TRUNCATION_MARKER) $(PYTHON) - report $(DIFF_BASE) $(MUTATION_MIN_SCORE) > build/mutation/score.txt; \
		status=$$?; cat build/mutation/score.txt; \
		if [ $$status -eq 0 ] && ! grep -qE 'mutation score .* = [0-9.]+%|UNMEASURED' build/mutation/score.txt; then \
			echo "mutation-baseline: the scope was NON-EMPTY and the run exited 0, but"; \
			echo "  build/mutation/score.txt contains no score and no UNMEASURED verdict."; \
			echo "  A gate measures or it fails — refusing to pass having produced no number."; \
			exit 1; fi; \
		exit $$status; \
	else \
		echo "no MUTATABLE changed functions under src/ vs $(DIFF_BASE) — nothing to mutate (any exclusions are named above)"; \
		echo "mutation-baseline: NO SCORE WAS PRODUCED. This job is green because there"; \
		echo "  was nothing in scope, not because anything was measured. Do not cite this"; \
		echo "  run as evidence the gate works — that was #130's exact mistake."; \
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
		--markdown-report build/coverage/diff-cover.md \
		--format json:build/coverage/diff-cover.json
	@# FAIL-CLOSED FLOOR. `--fail-under` computes its percentage over the lines
	@# diff-cover could map to the report; when it maps NONE the denominator is
	@# empty, the percentage reads 100, and this BLOCKING gate exits 0. Measured
	@# 2026-07-29: two uncovered new lines in fence() plus a report with no
	@# packages gave "No lines with coverage information in this diff" and rc=0.
	@# Same shape as #130 and #158 — a status with no measurement behind it.
	@$(PYTHON) scripts/check_diff_cover_measured.py --base $(DIFF_BASE)

security-scan: check-python
	$(PYTHON) scripts/security_scan.py

# Layer 2 of the close-keyword guard (ADR-0066). Vets the EXACT text you are
# about to hand to `gh pr merge`, and asks GitHub what it thinks the pull
# request closes. This is the ONLY layer that can stop the PR #360 class, where
# the damaging sentence lived in the merge body and was therefore invisible both
# to the pull-request lane and to GitHub's own `closingIssuesReferences`.
#
# DISCIPLINE, NOT ENFORCEMENT. Nothing can make this run before a merge; CI
# never sees the merge text. It is a loaded gun pointed at your own foot and
# this target is the safety catch you have to remember to use.
#
#   make close-guard PR=361 \
#     SUBJECT="fix: the thing" \
#     BODY="$$(cat /tmp/merge-body.md)"
close-guard: check-python
	@MERGE_SUBJECT="$(SUBJECT)" MERGE_BODY="$(BODY)" $(PYTHON) \
		scripts/check_close_keywords.py --env MERGE_SUBJECT MERGE_BODY \
		--require-nonempty --premerge-pr $(PR)

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
