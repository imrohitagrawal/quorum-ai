# Python runner: prefer python3, fall back to python.
# Override when needed: make PYTHON=/path/to/python3 <target>
PYTHON ?= $(shell if command -v python3 >/dev/null 2>&1; then command -v python3; elif command -v python >/dev/null 2>&1; then command -v python; fi)
UV_CACHE_DIR ?= $(CURDIR)/.uv-cache
RELOAD ?= 0

.PHONY: check-python publishing-check skill-onboarding-check skill-discover handoff check-breaking apply-orbi-profile skill-route start next capture-idea validate validate-strict quality format format-check lint type-check test test-report security-scan ci-evidence run docker-build

check-python:
	@if [ -z "$(PYTHON)" ]; then 		echo "ERROR: Python 3 is required. Install python3, or set PYTHON=/path/to/python3."; 		exit 127; 	fi
	@$(PYTHON) -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 'ERROR: Python 3.10+ required. Found ' + '.'.join(map(str, sys.version_info[:3])) + '. Set PYTHON=/path/to/python3 or upgrade Python.')"

start: next

next: check-python
	$(PYTHON) scripts/factory_next.py

capture-idea: check-python
	@if [ -n "$(IDEA)" ]; then 		$(PYTHON) scripts/capture_idea.py "$(IDEA)"; 	else 		$(PYTHON) scripts/capture_idea.py; 	fi

validate: check-python
	$(PYTHON) scripts/validate_all.py

validate-strict: check-python
	FACTORY_STRICT=1 $(PYTHON) scripts/validate_all.py

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

security-scan: check-python
	$(PYTHON) scripts/security_scan.py

ci-evidence: test-report security-scan

run:
	UV_CACHE_DIR=$(UV_CACHE_DIR) PYTHONPATH=src uv run uvicorn product_app.main:app --host 0.0.0.0 --port 8000 $(if $(filter 1 true yes on,$(RELOAD)),--reload,)

docker-build:
	docker build -t quorum-ai:local .

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
