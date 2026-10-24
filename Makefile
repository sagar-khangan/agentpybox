
.DEFAULT_GOAL := help

UV := uv
PYTHON := $(UV) run python
HOST := 127.0.0.1
PORT := 8000
API := agenthaven.api:app

.PHONY: help setup install dev run health test lint format check \
        demo tree clean clean-cache clean-runtime reset-env status

help: ## Show available commands
	@echo ""
	@echo "AgentHaven - Development Commands"
	@echo "---------------------------------"
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-18s %s\n", $$1, $$2}'
	@echo ""

setup: ## Install Python 3.13 and project dependencies
	$(UV) python install 3.13
	$(UV) sync

install: ## Synchronize project dependencies
	$(UV) sync

dev: ## Start FastAPI with automatic reload
	$(PYTHON) -m uvicorn $(API) --host $(HOST) --port $(PORT) --reload

run: ## Start FastAPI without reload
	$(PYTHON) -m uvicorn $(API) --host $(HOST) --port $(PORT)

health: ## Check API health (server must be running)
	curl --fail --silent --show-error http://$(HOST):$(PORT)/health
	@echo ""

test: ## Run automated tests
	$(UV) run pytest -v

lint: ## Check code quality
	$(UV) run ruff check src tests

format: ## Format Python source files
	$(UV) run ruff format src tests

check: lint test ## Run linting and tests

demo: ## Run create-inspect-terminate lifecycle demo
	$(PYTHON) examples/lifecycle_demo.py

tree: ## Show project dependencies
	$(UV) tree

status: ## Show Git and disk usage
	@git status --short
	@df -h .
	@du -sh .venv .runtime 2>/dev/null || true

clean: ## Remove Python test and lint caches
	@find src tests -type d \
		\( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) \
		-prune -exec rm -rf -- {} +
	@rm -rf .pytest_cache .ruff_cache
	@echo "Temporary Python caches removed."

clean-cache: ## Prune unused uv package cache entries
	$(UV) cache prune

clean-runtime: ## Delete local sandbox metadata/workspaces (destructive)
	@echo "WARNING: This deletes AgentHaven local runtime data."
	@read -r -p "Type RESET to continue: " answer; \
		if [ "$$answer" = "RESET" ]; then \
			rm -rf -- .runtime; \
			echo "Runtime removed."; \
		else \
			echo "Cancelled."; \
		fi

reset-env: ## Recreate Python project environment
	@echo "This will delete the project virtual environment."
	@read -r -p "Type RESET to continue: " answer; \
		if [ "$$answer" = "RESET" ]; then \
			rm -rf -- .venv; \
			$(UV) sync; \
		else \
			echo "Cancelled."; \
		fi

bbwrap:
	sudo apt update
	sudo apt install -y bubblewrap
	bwrap --version


sandbox-check: ## Verify Bubblewrap isolation
	@command -v bwrap >/dev/null || { echo "Install bubblewrap"; exit 1; }
	@command -v prlimit >/dev/null || { echo "Install prlimit"; exit 1; }
	bwrap --unshare-all --die-with-parent \
		--ro-bind /usr /usr \
		--ro-bind-try /bin /bin \
		--ro-bind-try /lib /lib \
		--ro-bind-try /lib64 /lib64 \
		--proc /proc --dev /dev --tmpfs /tmp \
		-- /usr/bin/python3 -I -c \
		'print("Sandbox isolation ready")'

sandbox-demo: ## Run the full execution lifecycle demo
	$(PYTHON) examples/execution_demo.py

sandbox-tests: ## Run sandbox-related automated tests
	$(UV) run pytest -v tests/