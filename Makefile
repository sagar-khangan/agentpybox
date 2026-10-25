
.DEFAULT_GOAL := help

UV := uv
AGENTHAVEN := $(UV) run agenthaven

INPUT_DIR := input
OUTPUT_DIR := output
PROFILE := python-basic
TTL := 300
HOURS := 24

.PHONY: help install test lint format check doctor \
        demo demo-basic demo-sdk demo-multi \
        demo-data demo-pandas env-data env-list \
        env-inspect env-find env-delete \
        run-script run-code metrics history \
        sandboxes create-sandbox cleanup clean

help:
	@echo ""
	@echo "AgentHaven Commands"
	@echo "===================================="
	@echo "Development"
	@echo "  make install           Install dependencies"
	@echo "  make check             Lint + automated tests"
	@echo "  make format            Format Python code"
	@echo "  make doctor            Check Bubblewrap environment"
	@echo ""
	@echo "Examples"
	@echo "  make demo-basic        Run standard-library Python"
	@echo "  make demo-sdk          Run existing SDK example"
	@echo "  make demo-multi        Run multiple sandbox sessions"
	@echo "  make demo-data         Analyze CSV with stdlib"
	@echo "  make env-data          Register pandas environment"
	@echo "  make demo-pandas       Analyze CSV with pandas"
	@echo ""
	@echo "Environment Registry"
	@echo "  make env-list          List registered environments"
	@echo "  make env-inspect ENV=python-pandas"
	@echo "  make env-find PACKAGE=pandas"
	@echo "  make env-delete ENV=python-pandas"
	@echo ""
	@echo "Sandbox Operations"
	@echo "  make run-script FILE=input/script.py"
	@echo '  make run-code CODE="print(42)"'
	@echo "  make create-sandbox PROFILE=python-basic"
	@echo "  make sandboxes"
	@echo "  make history SID=<sandbox-id>"
	@echo "  make metrics HOURS=24"
	@echo "  make cleanup"
	@echo "  make clean"
	@echo ""

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

demo: demo-sdk

demo-basic:
	$(AGENTHAVEN) run \
		--env python-basic \
		--code "print(sum(range(100)))"

demo-sdk:
	$(UV) run python examples/sdk_demo.py

demo-multi:
	$(UV) run python examples/multi_sandbox_demo.py

demo-data:
	@mkdir -p $(OUTPUT_DIR)
	$(AGENTHAVEN) run \
		--env python-data \
		--file $(INPUT_DIR)/analyze.py \
		--upload $(INPUT_DIR)/sales.csv \
		--download report.txt \
		--output-dir $(OUTPUT_DIR)

env-data:
	$(AGENTHAVEN) env create python-pandas \
		--requirements $(INPUT_DIR)/requirements-data.txt

demo-pandas:
	@mkdir -p $(OUTPUT_DIR)
	$(AGENTHAVEN) run \
		--env python-pandas \
		--file $(INPUT_DIR)/pandas_analysis.py \
		--upload $(INPUT_DIR)/sales.csv \
		--upload $(INPUT_DIR)/customers.csv \
		--download report.csv \
		--download summary.json \
		--output-dir $(OUTPUT_DIR)

env-list:
	$(AGENTHAVEN) env list

env-inspect:
	@test -n "$(ENV)" || (echo "Usage: make env-inspect ENV=python-pandas" && exit 1)
	$(AGENTHAVEN) env inspect $(ENV)

env-find:
	@test -n "$(PACKAGE)" || (echo "Usage: make env-find PACKAGE=pandas" && exit 1)
	$(AGENTHAVEN) env find --package $(PACKAGE)

env-delete:
	@test -n "$(ENV)" || (echo "Usage: make env-delete ENV=python-pandas" && exit 1)
	$(AGENTHAVEN) env delete $(ENV)

run-script:
	@test -n "$(FILE)" || (echo "Usage: make run-script FILE=input/script.py" && exit 1)
	$(AGENTHAVEN) run --env $(PROFILE) --file $(FILE)

run-code:
	@test -n "$(CODE)" || (echo 'Usage: make run-code CODE="print(42)"' && exit 1)
	$(AGENTHAVEN) run --env $(PROFILE) --code '$(CODE)'

sandboxes:
	$(AGENTHAVEN) list

create-sandbox:
	$(AGENTHAVEN) create --env $(PROFILE) --ttl $(TTL)

history:
	@test -n "$(SID)" || (echo "Usage: make history SID=<sandbox-id>" && exit 1)
	$(AGENTHAVEN) history $(SID)

metrics:
	$(AGENTHAVEN) metrics --hours $(HOURS)

cleanup:
	$(AGENTHAVEN) cleanup

clean:
	rm -rf .pytest_cache .ruff_cache
	@find src tests examples -type d -name __pycache__ -prune -exec rm -rf -- {} +
	@echo "Development caches removed."
