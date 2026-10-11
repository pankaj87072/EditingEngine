# ─────────────────────────────────────────────────────────────────────────────
# AutoVideoGen — Makefile
# Common developer commands. Run `make help` to see all targets.
# ─────────────────────────────────────────────────────────────────────────────

.DEFAULT_GOAL := help
.PHONY: help install dev test test-cov lint format type-check \
        run worker celery-inspect clean docker-up docker-down \
        docker-logs docker-shell create-env

PYTHON      = python
PIP         = pip
PYTEST      = pytest
APP_MODULE  = main:app
WORKER_MODULE = workers.celery_app

# ── Help ──────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "  AutoVideoGen — Available Make targets"
	@echo "  ─────────────────────────────────────"
	@echo "  make install        Install all Python dependencies"
	@echo "  make dev            Install deps + create .env from .env.example"
	@echo "  make run            Start FastAPI dev server (port 8000)"
	@echo "  make worker         Start Celery worker (requires Redis)"
	@echo "  make test           Run all tests"
	@echo "  make test-cov       Run tests with coverage report"
	@echo "  make lint           Run flake8 linter"
	@echo "  make format         Run black + isort formatter"
	@echo "  make type-check     Run mypy type checker"
	@echo "  make clean          Remove __pycache__, .pyc, temp files"
	@echo "  make docker-up      Start full stack via Docker Compose"
	@echo "  make docker-down    Stop Docker Compose stack"
	@echo "  make docker-logs    Tail logs from all containers"
	@echo ""

# ── Setup ─────────────────────────────────────────────────────────────────────

install:
	$(PIP) install -r requirements.txt

dev: install create-env
	@echo "✔ Dev environment ready. Edit .env then run: make run"

create-env:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✔ Created .env from .env.example — please fill in your values."; \
	else \
		echo "  .env already exists — skipping."; \
	fi

# ── Running ───────────────────────────────────────────────────────────────────

run:
	uvicorn $(APP_MODULE) --host 0.0.0.0 --port 8000 --reload \
		--log-level debug

run-prod:
	uvicorn $(APP_MODULE) --host 0.0.0.0 --port 8000 --workers 4

worker:
	celery -A $(WORKER_MODULE) worker \
		--loglevel=info \
		--queues=video \
		--concurrency=2 \
		--hostname=video-worker@%h

celery-inspect:
	celery -A $(WORKER_MODULE) inspect active

# ── Testing ───────────────────────────────────────────────────────────────────

test:
	$(PYTEST) tests/ -v

test-cov:
	$(PYTEST) tests/ -v \
		--cov=. \
		--cov-omit="tests/*,*/__init__.py" \
		--cov-report=term-missing \
		--cov-report=html:coverage_html
	@echo "✔ Coverage report → coverage_html/index.html"

test-fast:
	$(PYTEST) tests/ -x -q  # Stop on first failure

# ── Code Quality ──────────────────────────────────────────────────────────────

lint:
	flake8 . \
		--max-line-length=100 \
		--exclude=.env,.git,__pycache__,data/,coverage_html/ \
		--extend-ignore=E501,W503

format:
	black . --line-length 100 --exclude "data/|coverage_html/"
	isort . --profile black

type-check:
	mypy . \
		--ignore-missing-imports \
		--exclude "tests/|data/" \
		--no-strict-optional

check: lint type-check test  ## Run all quality checks + tests

# ── Docker ────────────────────────────────────────────────────────────────────

docker-up:
	docker compose up --build -d
	@echo "✔ Stack started. API → http://localhost:8000/docs"

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

docker-shell:
	docker compose exec api /bin/bash

docker-clean:
	docker compose down -v --remove-orphans
	docker image prune -f

# ── Cleanup ───────────────────────────────────────────────────────────────────

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc"      -delete 2>/dev/null || true
	find . -type f -name "*.pyo"      -delete 2>/dev/null || true
	find . -type f -name ".DS_Store"  -delete 2>/dev/null || true
	rm -rf .mypy_cache .pytest_cache coverage_html .coverage
	@echo "✔ Cleaned up build artifacts"

clean-data:
	@echo "⚠  This will delete all uploaded clips and generated videos!"
	@read -p "Are you sure? [y/N] " confirm && \
		[ "$$confirm" = "y" ] && \
		rm -rf data/uploads/* data/outputs/* && \
		echo "✔ Data directories cleared." || echo "Aborted."
