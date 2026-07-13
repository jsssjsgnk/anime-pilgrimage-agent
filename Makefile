.PHONY: bootstrap bootstrap-conda verify-env dev dev-infra compose-up compose-down lint typecheck test \
	verify-phase-1 verify-phase-2 verify-phase-3 verify-phase-4 verify-phase-5 verify-phase-6 verify-all

PYTHON ?= python
UV ?= uv
PNPM ?= pnpm

bootstrap:
	$(UV) sync --extra dev
	$(PNPM) install --frozen-lockfile
	$(PNPM) --filter @pilgrimage/web exec playwright install chromium

bootstrap-conda:
	$(PYTHON) scripts/bootstrap_conda.py

verify-env:
	$(PYTHON) scripts/verify_env.py

dev:
	$(PYTHON) scripts/dev.py

dev-infra:
	docker compose up -d postgres

compose-up:
	docker compose up -d --build

compose-down:
	docker compose down

lint:
	$(UV) run ruff check .
	$(PNPM) lint

typecheck:
	$(UV) run mypy
	$(PNPM) typecheck

test:
	$(UV) run pytest -m "not live and not e2e" --cov=pilgrimage_agent --cov-report=term-missing
	$(PNPM) test

verify-phase-1:
	$(PYTHON) scripts/gate.py 1

verify-phase-2:
	$(PYTHON) scripts/gate.py 2

verify-phase-3:
	$(PYTHON) scripts/gate.py 3

verify-phase-4:
	$(PYTHON) scripts/gate.py 4

verify-phase-5:
	$(PYTHON) scripts/gate.py 5

verify-phase-6:
	$(PYTHON) scripts/gate.py 6

verify-all:
	$(PYTHON) scripts/gate.py all
