SHELL := /bin/bash
ROOT  := $(shell pwd)

# Absolute paths so MetricFlow works from any directory (no more relative-path traps).
export WAREHOUSE_DB    ?= $(ROOT)/data/warehouse.duckdb
export DBT_PROFILES_DIR := $(ROOT)/dbt/retail_dwh

DBT  := uv run dbt
PROJ := --project-dir dbt/retail_dwh --profiles-dir dbt/retail_dwh

.PHONY: help setup data build parse warehouse run agent test eval \
        format lint typecheck check hooks docker-up docker-down clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Install the environment (uv sync)
	uv sync

data: ## Generate synthetic source data + load the Bronze layer
	uv run python scripts/generate_raw_data.py
	uv run python scripts/load_bronze.py

build: ## Run dbt models (Silver + Gold) and data tests
	$(DBT) build $(PROJ)

parse: ## Generate the MetricFlow semantic manifest
	$(DBT) parse $(PROJ)

warehouse: data build parse ## Full pipeline: data -> dbt -> semantic manifest

run: ## Launch the Streamlit dashboard
	uv run streamlit run streamlit_app.py

agent: ## Ask the agent, e.g. make agent Q="revenue by category in May 2026"
	uv run python -m governed_analytics_agent.cli "$(Q)"

test: ## Run the pytest suite
	uv run pytest

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
