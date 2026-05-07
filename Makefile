.PHONY: help bootstrap test up ingest

help:
	@echo "arXMCP development targets:"
	@echo ""
	@echo "  make bootstrap   Set up dev env and create var/arxmcp/ tree"
	@echo "  make test        Run ruff + pytest"
	@echo "  make up          Start the MCP server (E01_S08; not yet implemented)"
	@echo "  make ingest      Run the ingestion pipeline (E11; not yet implemented)"
	@echo ""
	@echo "Before fetching from arXiv, export ARXMCP_CONTACT_EMAIL=<your-email>"
	@echo "(used in the User-Agent string per arXiv TOS)."

bootstrap:
	python3 -m pip install -e ".[dev]"
	mkdir -p var/arxmcp/corpus/raw var/arxmcp/corpus/parsed var/arxmcp/corpus/chunks
	mkdir -p var/arxmcp/index/lancedb var/arxmcp/index/kuzu
	mkdir -p var/arxmcp/cache/ar5iv
	mkdir -p var/arxmcp/ops/parser-failures
	@echo ""
	@echo "Bootstrap complete. var/arxmcp/ tree created."
	@if [ -z "$$ARXMCP_CONTACT_EMAIL" ]; then \
		echo "WARNING: export ARXMCP_CONTACT_EMAIL=<your-email> before fetching from arXiv."; \
	fi

test:
	ruff check .
	pytest

up:
	@echo "make up — not yet implemented (lands in E01_S08)"
	@exit 1

ingest:
	@echo "make ingest — not yet implemented (the seed corpus tooling lives in tools/)"
	@echo "  tools/curate_seed.py    pre-filter math.AG candidates from arXiv API"
	@echo "  tools/fetch_seed.py     fetch + LaTeXML parse the 50-paper seed"
	@echo "Production ingestion lands in E11."
	@exit 1
