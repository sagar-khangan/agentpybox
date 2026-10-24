
.DEFAULT_GOAL := help

UV := uv
AGENTHAVEN := $(UV) run agenthaven

INPUT_DIR := input
OUTPUT_DIR := output
PROFILE := python-data
TTL := 300
HOURS := 24

.PHONY: help install test lint format check doctor demo \
        analyze run-script run-code metrics history \
        sandboxes create-sandbox cleanup clean

# ==========================================
# Help
# ==========================================

help:
	@echo ""
	@echo "AgentHaven Commands"
	@echo "=============================="
	@echo "make install          Install dependencies"
	@echo "make test             Run tests"
	@echo "make lint             Check code quality"
	@echo "make format           Format Python files"
	@echo "make check            Run lint + tests"
	@echo "make doctor           Check sandbox environment"
	@echo "make demo             Run SDK demonstration"
	@echo "make analyze          Run CSV analysis end-to-end"
	@echo "make run-script       Execute a custom Python script"
	@echo "make run-code         Execute inline Python code"
	@echo "make metrics          Show execution metrics"
	@echo "make history          Show sandbox history (requires SID)"
	@echo "make sandboxes        List sandboxes"
	@echo "make create-sandbox   Create persistent sandbox"
	@echo "make cleanup          Clean expired sandboxes"
	@echo "make clean            Remove development caches"
	@echo ""

# ==========================================
# Development
# ==========================================

install:
	$(UV) sync --extra dev

test:
	$(UV) run --extra dev pytest -q

lint:
	$(UV) run --extra dev ruff check src tests examples

format:
	$(UV) run --extra dev ruff format src tests examples

check: lint test

doctor:
	$(AGENTHAVEN) doctor

demo:
	$(UV) run python examples/sdk_demo.py

# ==========================================
# One-Time Sandbox Execution
# ==========================================

analyze:
	@mkdir -p $(OUTPUT_DIR)
	$(AGENTHAVEN) run \
		--profile $(PROFILE) \
		--file $(INPUT_DIR)/analyze.py \
		--upload $(INPUT_DIR)/sales.csv \
		--download report.txt \
		--output-dir $(OUTPUT_DIR)

run-script:
	@test -n "$(FILE)" || (echo "Usage: make run-script FILE=input/script.py" && exit 1)
	@mkdir -p $(OUTPUT_DIR)
	$(AGENTHAVEN) run \
		--profile $(PROFILE) \
		--file $(FILE) \
		--output-dir $(OUTPUT_DIR)

run-code:
	@test -n "$(CODE)" || (echo 'Usage: make run-code CODE="print(42)"' && exit 1)
	$(AGENTHAVEN) run \
		--profile $(PROFILE) \
		--code '$(CODE)'

# ==========================================
# Observability
# ==========================================

metrics:
	$(AGENTHAVEN) metrics --hours $(HOURS)

history:
	@test -n "$(SID)" || (echo "Usage: make history SID=<sandbox-id>" && exit 1)
	$(AGENTHAVEN) history $(SID)

# ==========================================
# Sandbox Management
# ==========================================

sandboxes:
	$(AGENTHAVEN) list

create-sandbox:
	$(AGENTHAVEN) create \
		--profile $(PROFILE) \
		--ttl $(TTL)

cleanup:
	$(AGENTHAVEN) cleanup

# ==========================================
# Maintenance
# ==========================================

clean:
	rm -rf .pytest_cache .ruff_cache
	@find src tests examples -type d -name __pycache__ -prune -exec rm -rf -- {} +
	@echo "Development caches removed."
