.PHONY: bootstrap check test lint format typecheck infra-up infra-down migrate migration-check api worker projector diagnosis-worker web

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
	uv run ruff check src tests migrations
	uv run ruff format --check src tests migrations

format:
	uv run ruff check --fix src tests migrations
	uv run ruff format src tests migrations
	pnpm --filter @chakravyuh/web format

typecheck:
	uv run mypy

infra-up:
	docker compose up -d --wait
	uv run alembic upgrade head

infra-down:
	docker compose down

migrate:
	uv run alembic upgrade head

migration-check:
	uv run alembic check

api:
	uv run uvicorn chakravyuh.api.main:create_app --factory --reload

worker:
	uv run chakravyuh-worker

projector:
	uv run chakravyuh-projector

diagnosis-worker:
	uv run chakravyuh-diagnosis-worker

web:
	pnpm web:dev
