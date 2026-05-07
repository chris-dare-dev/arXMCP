.PHONY: help bootstrap test up ingest

# Override with `make test PYTHON=python3.13` if your default python3 is too old.
PYTHON ?= python3
MIN_PY_MINOR := 11

help:
	@echo "arXMCP development targets:"
	@echo ""
	@echo "  make bootstrap   Set up dev env and create var/arxmcp/ tree"
	@echo "  make test        Run ruff + pytest"
	@echo "  make up          Start the MCP server (E01_S08; not yet implemented)"
	@echo "  make ingest      Run the ingestion pipeline (E11; not yet implemented)"
	@echo ""
	@echo "Override the python interpreter with: make test PYTHON=python3.13"
	@echo ""
	@echo "Before fetching from arXiv, export ARXMCP_CONTACT_EMAIL=<your-email>"
	@echo "(used in the User-Agent string per arXiv TOS)."

bootstrap:
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), \
		f'arXMCP requires Python >= 3.$(MIN_PY_MINOR); got {sys.version_info[:2]}'"
	@if [ -z "$$VIRTUAL_ENV" ]; then \
		echo "ERROR: activate a venv first ($(PYTHON) -m venv .venv && source .venv/bin/activate)" >&2; \
		exit 1; \
	fi
	$(PYTHON) -m pip install --require-virtualenv -e ".[dev]"
	mkdir -p var/arxmcp/corpus/raw var/arxmcp/corpus/parsed var/arxmcp/corpus/chunks
	mkdir -p var/arxmcp/index/lancedb var/arxmcp/index/kuzu
	mkdir -p var/arxmcp/cache/ar5iv
	mkdir -p var/arxmcp/ops/parser-failures
	# NOTE: E02_S02 LaTeXML container will need write access to corpus/parsed/;
	# see .claude/notes/08-security-observability-ops.md § Threat 3 for the
	# rootless-container UID isolation that lands there.
	@echo ""
	@echo "Bootstrap complete. var/arxmcp/ tree created."
	@if [ -z "$$ARXMCP_CONTACT_EMAIL" ]; then \
		echo "WARNING: export ARXMCP_CONTACT_EMAIL=<your-email> before fetching from arXiv."; \
	fi

test:
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), \
		f'arXMCP requires Python >= 3.$(MIN_PY_MINOR); got {sys.version_info[:2]}. \
Try: make test PYTHON=python3.$(MIN_PY_MINOR)'"
	$(PYTHON) -m ruff check .
	$(PYTHON) -m pytest

up:
	@echo "make up — not yet implemented (lands in E01_S08)"
	@exit 1

ingest:
	@echo "make ingest — not yet implemented (the seed corpus tooling lives in tools/)"
	@echo "  tools/curate_seed.py    pre-filter math.AG candidates from arXiv API"
	@echo "  tools/fetch_seed.py     fetch + LaTeXML parse the 50-paper seed"
	@echo "Production ingestion lands in E11."
	@exit 1
