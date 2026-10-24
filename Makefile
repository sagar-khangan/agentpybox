
.DEFAULT_GOAL := help

UV := uv
PYTHON := $(UV) run python

HOST := 127.0.0.1
PORT := 8000
API := agenthaven.api:app

.PHONY: help setup install dev run health \
        test lint format check \
        demo sandbox-check sandbox-demo \
        sandbox-tests execution-tests \
        file-tests api-tests history-tests ttl-tests \
        full-demo status tree \
        clean clean-cache clean-runtime reset-env

help: ## Show all commands
	@echo ""
	@echo "AgentHaven Development Commands"
	@echo "==============================="
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-22s %s\n", $$1, $$2}'
	@echo ""

setup: ## Install Python 3.13 and dependencies
	$(UV) python install 3.13
	$(UV) sync

install: ## Sync project dependencies
	$(UV) sync

dev: ## Start development API with hot reload
	$(PYTHON) -m uvicorn $(API) \
		--host $(HOST) --port $(PORT) --reload

run: ## Start API without reload
	$(PYTHON) -m uvicorn $(API) \
		--host $(HOST) --port $(PORT)

health: ## Check API health
	curl --fail --silent --show-error \
		http://$(HOST):$(PORT)/health
	@echo ""

test: ## Run all automated tests
	$(UV) run pytest -v

lint: ## Run Ruff linting
	$(UV) run ruff check src tests examples

format: ## Format Python files
	$(UV) run ruff format src tests examples

check: lint test ## Run lint and tests

demo: ## Run basic lifecycle demo
	$(PYTHON) examples/lifecycle_demo.py

sandbox-check: ## Verify Bubblewrap isolation
	@command -v bwrap >/dev/null
	bwrap --unshare-all --die-with-parent \
		--ro-bind /usr /usr \
		--ro-bind-try /bin /bin \
		--ro-bind-try /lib /lib \
		--ro-bind-try /lib64 /lib64 \
		--proc /proc --dev /dev --tmpfs /tmp \
		-- /usr/bin/python3 -I -c \
		'print("Sandbox isolation ready")'

sandbox-demo: ## Run sandbox execution demonstration
	$(PYTHON) examples/execution_demo.py

sandbox-tests: ## Run all sandbox tests
	$(UV) run pytest -v tests/

execution-tests: ## Run Bubblewrap execution tests
	$(UV) run pytest -v tests/test_sandbox_execution.py

file-tests: ## Run file API tests
	$(UV) run pytest -v tests/test_files.py

api-tests: ## Run all API tests
	$(UV) run pytest -v tests/

history-tests: ## Run execution history tests
	$(UV) run pytest -v tests/test_execution_history.py

ttl-tests: ## Run sandbox TTL tests
	$(UV) run pytest -v tests/test_ttl.py

full-demo: ## Run complete sandbox lifecycle demo
	$(PYTHON) examples/full_demo.py

tree: ## Show Python dependencies
	$(UV) tree

status: ## Show Git and disk usage
	git status --short
	df -h .
	@du -sh .venv .runtime 2>/dev/null || true

clean: ## Remove Python development caches
	@find src tests examples -type d \
		\( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) \
		-prune -exec rm -rf -- {} +
	@rm -rf .pytest_cache .ruff_cache
	@echo "Development caches removed."

clean-cache: ## Prune uv dependency cache
	$(UV) cache prune

clean-runtime: ## Delete sandbox runtime data
	@echo "WARNING: Deletes sandbox sessions and history."
	@echo "Stop the AgentHaven API before proceeding."
	@read -r -p "Type RESET to confirm: " answer; \
		if [ "$$answer" = "RESET" ]; then \
			rm -rf -- .runtime; \
			echo "Runtime deleted."; \
		else \
			echo "Cancelled."; \
		fi

reset-env: ## Recreate virtual environment
	@read -r -p "Type RESET to recreate .venv: " answer; \
		if [ "$$answer" = "RESET" ]; then \
			rm -rf -- .venv; \
			$(UV) sync; \
		else \
			echo "Cancelled."; \
		fi

agent-demo: ## Run OpenRouter agent with AgentHaven
	$(PYTHON) examples/openrouter_agent.py

metrics: ## Show last 24 hours of execution metrics
	@curl -fsS "http://127.0.0.1:8000/observability/summary?hours=24" \
		| $(PYTHON) -m json.tool

metrics-recent: ## Show recent sandbox executions
	@curl -fsS "http://127.0.0.1:8000/observability/executions?limit=20" \
		| $(PYTHON) -m json.tool

observability-tests: ## Run observability tests
	$(UV) run pytest -v tests/test_observability.py