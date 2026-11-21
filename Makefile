# Shortcuts. Run e.g. `make up`. (Indented lines must start with a TAB.)
.PHONY: up down migrate seed test lint

up:        ## start Postgres
	docker compose up -d

down:      ## stop Postgres (data is kept)
	docker compose down

migrate:   ## create or update all tables
	uv run alembic upgrade head

seed:      ## load the NRW universities
	uv run python -m admissions.seed

test:      ## run all tests
	uv run pytest

lint:      ## check code style
	uv run ruff check .
