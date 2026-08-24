# Database migrations

Migrations are the only supported way to change Chakravyuh's authoritative PostgreSQL
schema. Apply them before starting a new application release:

    uv run alembic upgrade head

Rollback is supported for local development. Production rollbacks must use a reviewed
forward repair migration whenever an older application cannot safely read newer data.
