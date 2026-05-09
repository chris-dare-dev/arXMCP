.PHONY: help bootstrap test eval up ingest

# Override with `make test PYTHON=python3.13` if your default python3 is too old.
PYTHON ?= python3
MIN_PY_MINOR := 11

help:
	@echo "arXMCP development targets:"
	@echo ""
	@echo "  make bootstrap   Set up dev env and create var/arxmcp/ tree"
	@echo "  make test        Run ruff + pytest"
	@echo "  make eval        Run the Tier-0 retrieval-quality gate (see TIER-GATES.md)"
	@echo "  make up          Start the arxmcp-server on 127.0.0.1:7733 (E06_S01)"
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

# The Tier-0 → Tier-1 exit gate. See TIER-GATES.md for the full
# behavior matrix (pass / fail / SKIP) and the operator's prerequisite
# checklist. SKIP is NOT a pass for promotion — verify the test
# reports `1 passed`, not `1 skipped`, before declaring Tier-0 done.
eval:
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), \
		f'arXMCP requires Python >= 3.$(MIN_PY_MINOR); got {sys.version_info[:2]}. \
Try: make eval PYTHON=python3.$(MIN_PY_MINOR)'"
	$(PYTHON) -m pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.70

# Start the long-running arxmcp-server (E06_S01). Binds to 127.0.0.1
# only (Threat 4); container deployments expose the port via host
# port-mapping. Override the bind via ARXMCP_BIND_PORT and the LanceDB
# path via ARXMCP_LANCEDB_PATH; full env-var list in server/config.py.
#
# The server eager-loads BGE-M3 at startup (~5-30s) before /readyz
# flips to 200. Use the docker image (docker/Dockerfile.server) for
# production; this target is for local dev.
up:
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), \
		f'arXMCP requires Python >= 3.$(MIN_PY_MINOR); got {sys.version_info[:2]}. \
Try: make up PYTHON=python3.$(MIN_PY_MINOR)'"
	$(PYTHON) -m uvicorn server.main:app --host 127.0.0.1 --port 7733 --lifespan on

ingest:
	@echo "make ingest — not yet implemented (the seed corpus tooling lives in tools/)"
	@echo "  tools/curate_seed.py    pre-filter math.AG candidates from arXiv API"
	@echo "  tools/fetch_seed.py     fetch + LaTeXML parse the 50-paper seed"
	@echo "Production ingestion lands in E11."
	@exit 1
