.DEFAULT_GOAL := help

ARGS ?=

.PHONY: help install dev dev-down test test-int test-all lint format run run-lite \
        docker-build docker-run docker-run-lite clean clean-docker

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies and Playwright Chromium
	uv sync && uv run playwright install chromium

dev: ## Start postgres + redis, wait for health checks
	docker compose up -d
	@echo "Waiting for postgres..."
	@until docker compose exec -T postgres pg_isready -U postgres -d jobhunter > /dev/null 2>&1; do sleep 1; done
	@echo "Waiting for redis..."
	@until docker compose exec -T redis redis-cli ping > /dev/null 2>&1; do sleep 1; done
	@echo "Infrastructure ready (postgres:5432, redis:6379)"

dev-down: ## Stop infrastructure services
	docker compose down

test: ## Run unit tests
	uv run pytest -m unit

test-int: ## Start infra and run integration tests
	$(MAKE) dev
	uv run pytest -m integration

test-all: ## Run all tests
	uv run pytest

lint: ## Run linter and type checker
	uv run ruff check . && uv run mypy .

format: ## Auto-format code
	uv run ruff format . && uv run ruff check --fix .

run: ## Run CLI (pass args via ARGS="...")
	uv run job-hunter run $(ARGS)

run-lite: ## Run CLI in lite mode (SQLite, no Docker)
	JH_DB_BACKEND=sqlite JH_CACHE_BACKEND=db uv run job-hunter run --lite $(ARGS)

docker-build: ## Build Docker image
	docker build -t job-hunter-agent:latest .

docker-run: ## Run in Docker with full infra (pass args via ARGS="...")
	docker compose --profile full run --rm app run /app/data/resume.pdf $(ARGS)

docker-run-lite: ## Run in Docker lite mode (no infra needed, pass args via ARGS="...")
	docker run --rm \
		--env-file .env \
		-e JH_DB_BACKEND=sqlite \
		-e JH_CACHE_BACKEND=db \
		-v ./output:/app/output \
		-v ./data:/app/data:ro \
		job-hunter-agent:latest run /app/data/resume.pdf --lite $(ARGS)

clean: ## Remove Python caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null; true

clean-docker: ## Remove Docker containers, volumes, and image
	docker compose --profile full down -v
	docker rmi job-hunter-agent:latest 2>/dev/null; true
