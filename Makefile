.PHONY: install dev migrate test test-int lint run run-lite clean

install:
	uv sync && uv run playwright install chromium

dev:
	docker compose up -d && uv run alembic upgrade head

migrate:
	uv run alembic upgrade head

test:
	uv run pytest -m unit

test-int:
	docker compose up -d && uv run pytest -m integration

lint:
	uv run ruff check . && uv run mypy .

run:
	uv run python -m job_hunter_cli.main

run-lite:
	JH_DB_BACKEND=sqlite uv run python -m job_hunter_cli.main --lite

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null; true
