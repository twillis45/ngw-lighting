.PHONY: run run-https run-prod ui ui-https test format lint clean install help analyze-ref analyze-ref-raw

PYTHON  ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || { command -v python3 || command -v python; })
UVICORN ?= $(shell [ -x .venv/bin/uvicorn ] && echo .venv/bin/uvicorn || echo uvicorn)
HOST    ?= 0.0.0.0
PORT    ?= 8000
PYARGS  ?=

help: ## Show this help
	@grep -E '^[a-z][a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies into active env
	pip install -r requirements.txt

run: ## Start dev server (auto-reload)
	$(UVICORN) main:app --host $(HOST) --port $(PORT) --reload

run-https: ## Start dev server with HTTPS (required for camera on LAN/mobile)
	$(UVICORN) main:app --host $(HOST) --port $(PORT) --reload \
		--ssl-keyfile certs/local-key.pem \
		--ssl-certfile certs/local.pem

ui: ## Start Vite dev server (use with make run)
	npm run dev --prefix ui

ui-https: ## Start Vite dev server with HTTPS proxy (use with make run-https)
	BACKEND_HTTPS=1 npm run dev --prefix ui

run-prod: ## Start production server (no reload)
	$(UVICORN) main:app --host $(HOST) --port $(PORT) --workers 2

test: ## Run full test suite
	$(PYTHON) -m pytest -v --tb=short $(PYARGS)

test-fast: ## Run tests without verbose output
	$(PYTHON) -m pytest -q $(PYARGS)

format: ## Format code with ruff
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check --fix .

lint: ## Lint without fixing
	$(PYTHON) -m ruff check .

analyze-ref: ## 3-layer ref analysis: make analyze-ref IMAGE=path/to/file
	@TF_CPP_MIN_LOG_LEVEL=3 $(PYTHON) scripts/analyze_ref.py $(IMAGE) --pretty 2>/dev/null

analyze-ref-raw: ## Same as analyze-ref but includes upstream data
	@TF_CPP_MIN_LOG_LEVEL=3 $(PYTHON) scripts/analyze_ref.py $(IMAGE) --raw --pretty 2>/dev/null

clean: ## Remove caches and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null; true
	find . -name '*.pyc' -delete 2>/dev/null; true
	rm -rf ui/node_modules/.vite 2>/dev/null; true
