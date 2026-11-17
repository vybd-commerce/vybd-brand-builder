SHELL := /bin/bash
ENV_FILE := $(if $(wildcard .env),--env-file .env,)
UV := uv run $(ENV_FILE)
PORT ?= 8000

.PHONY: help sync db db-down migrate dev server worker test test-live lint fmt e2e-fake

help:
	@echo "make sync      install workspace deps (uv)"
	@echo "make db        start postgres+pgvector (docker compose)"
	@echo "make migrate   run brain + app alembic migrations"
	@echo "make dev       db + migrate + server + worker"
	@echo "make server    run the API server only"
	@echo "make worker    run one runner worker"
	@echo "make test      pytest (fake providers; db tests skip if postgres is down)"
	@echo "make test-live pytest -m live (real providers; needs LLM_API_KEY)"
	@echo "make lint      ruff + import-linter"
	@echo "make e2e-fake  scripted clear-founder run (server + worker + CLI, fake providers)"

sync:
	uv sync

db:
	docker compose up -d --wait db

db-down:
	docker compose down

migrate:
	$(UV) alembic -c packages/brain/alembic.ini upgrade head
	$(UV) alembic -c packages/server/alembic.ini upgrade head

dev: db migrate
	@trap 'kill 0' EXIT; \
	$(UV) uvicorn server.main:app --reload --port $(PORT) & \
	$(UV) python -m runner.worker & \
	wait

server:
	$(UV) uvicorn server.main:app --reload --port $(PORT)

worker:
	$(UV) python -m runner.worker

test:
	$(UV) pytest

test-live:
	$(UV) pytest -m live

lint:
	uv run ruff check .
	uv run lint-imports

fmt:
	uv run ruff check --fix .
	uv run ruff format .

e2e-fake: migrate
	$(UV) python scripts/e2e_fake.py
