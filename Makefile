.PHONY: bootstrap check test lint format typecheck infra-up infra-down api web

bootstrap:
	uv sync --all-groups
	pnpm install --frozen-lockfile

check: lint typecheck test
	pnpm web:check
	pnpm web:test
	pnpm web:build

test:
	uv run pytest

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

format:
	uv run ruff check --fix src tests
	uv run ruff format src tests
	pnpm --filter @chakravyuh/web format

typecheck:
	uv run mypy

infra-up:
	docker compose up -d --wait

infra-down:
	docker compose down

api:
	uv run uvicorn chakravyuh.api.main:create_app --factory --reload

web:
	pnpm web:dev

