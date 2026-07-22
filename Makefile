SHELL := /bin/bash
ROOT  := $(shell pwd)

# Absolute paths so MetricFlow works from any directory (no more relative-path traps).
export WAREHOUSE_DB    ?= $(ROOT)/data/warehouse.duckdb
export DBT_PROFILES_DIR := $(ROOT)/dbt/retail_dwh

DBT  := uv run dbt
PROJ := --project-dir dbt/retail_dwh --profiles-dir dbt/retail_dwh

.PHONY: help setup data stream build parse build-prod parse-prod warehouse run \
        agent test cov eval format lint typecheck check hooks docker-up \
        docker-down clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Install the environment (uv sync)
	uv sync

data: ## Generate synthetic source data + load the Bronze layer
	uv run python scripts/generate_raw_data.py
	uv run python -m scripts.load_bronze

stream: ## Stream live order events into ORDER_EVENTS (T=duckdb|snowflake, SECS=20)
	uv run python -m scripts.stream_orders --target $(or $(T),duckdb) \
		--rate $(or $(RATE),5) --duration $(or $(SECS),20)

build: ## Run dbt models (Silver + Gold) and data tests
	$(DBT) build $(PROJ)

parse: ## Generate the MetricFlow semantic manifest (local DuckDB target)
	$(DBT) parse $(PROJ)

# ⚠️ The semantic manifest is TARGET-SPECIFIC: it hard-codes the warehouse
# catalog. After running anything with DBT_TARGET=prod, re-run `make parse`
# before using the local agent/tests, or MetricFlow will look for the Snowflake
# catalog against DuckDB ("Catalog RETAIL_DWH does not exist").
build-prod: ## Build Silver+Gold on Snowflake (DBT_TARGET=prod)
	DBT_TARGET=prod $(DBT) build $(PROJ)

parse-prod: ## Generate the semantic manifest for the Snowflake target
	DBT_TARGET=prod $(DBT) parse $(PROJ)

warehouse: data build parse ## Full pipeline: data -> dbt -> semantic manifest

run: ## Launch the Streamlit dashboard
	uv run streamlit run streamlit_app.py

agent: ## Ask the agent, e.g. make agent Q="revenue by category in May 2026"
	uv run python -m governed_analytics_agent.cli "$(Q)"

api: ## Serve the governed agent as a REST API (http://localhost:8080/docs)
	uv run python -m governed_analytics_agent.api

test: ## Run the pytest suite
	uv run pytest

cov: ## Run tests with a coverage report (terminal, shows missing lines)
	uv run pytest --cov=governed_analytics_agent --cov-report=term-missing

eval: ## Measure agent routing accuracy (needs ANTHROPIC_API_KEY + warehouse)
	uv run python -m eval.run_eval

format: ## Auto-format + autofix lint issues (ruff)
	uv run ruff check --fix .
	uv run ruff format .

lint: ## Lint + format check, read-only (what CI runs)
	uv run ruff check .
	uv run ruff format --check .

typecheck: ## Static type-check with mypy
	uv run mypy

check: lint typecheck test ## All quality gates: lint + types + tests

hooks: ## Install the pre-commit git hooks
	uv run pre-commit install

docker-up: ## Build + run everything in Docker (Colima)
	docker compose up --build

docker-down: ## Stop the container (keeps the warehouse volume)
	docker compose down

clean: ## Remove generated artifacts (warehouse, raw data, dbt target)
	rm -rf data/raw data/*.duckdb data/*.duckdb.wal \
		dbt/retail_dwh/target dbt/retail_dwh/logs
