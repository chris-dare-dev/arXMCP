.PHONY: help bootstrap test eval up ingest delta re-embed watchdog cutover daily-report parser-failures-report

# Override with `make test PYTHON=python3.13` if your default python3 is too old.
PYTHON ?= python3
MIN_PY_MINOR := 11

help:
	@echo "arXMCP development targets:"
	@echo ""
	@echo "  make bootstrap   Set up dev env and create var/arxmcp/ tree"
	@echo "  make test        Run ruff + pytest"
	@echo "  make eval        Run the Tier-0 retrieval-quality gate (see .claude/TIER-GATES.md)"
	@echo "  make up          Start the arxmcp-server on 127.0.0.1:7733 (E06_S01)"
	@echo "  make ingest      Run the bulk ingest orchestrator (E11_S01; see docs/ops/bulk-ingest-runbook.md)"
	@echo "  make delta       Run the OAI-PMH nightly delta loop (E11_S02; see docs/ops/delta-loop.md)"
	@echo "  make re-embed    Run the partial re-embed driver (E11_S03; see docs/ops/re-embed-runbook.md)"
	@echo "  make watchdog    Run the drift watchdog against staging (E11_S04; see docs/ops/drift-watchdog.md)"
	@echo "  make cutover     Activate the staging corpus as the new active (E11_S05; see docs/ops/cutover-runbook.md)"
	@echo "  make daily-report           Scrape /metrics and write the daily ops report (E14_S04; see docs/ops/daily-ops-cadence.md)"
	@echo "  make parser-failures-report Roll up parser-failures/*.{log,jsonl} into the weekly review (E14_S04; see docs/ops/parser-failure-review.md)"
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
	# E14_S03: Phoenix's SQLite trace store under PHOENIX_WORKING_DIR.
	# The host path bind-mounts to /mnt/data inside the container per
	# infra/observability/phoenix-compose.yml.
	mkdir -p var/arxmcp/observability/phoenix
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

# The Tier-0 → Tier-1 exit gate. See .claude/TIER-GATES.md for the full
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
# port-mapping. Honors ARXMCP_BIND_HOST and ARXMCP_BIND_PORT (and
# all other ARXMCP_* env vars per server/config.py).
#
# The server eager-loads BGE-M3 at startup (~5-30s) before /readyz
# flips to 200. Use the docker image (docker/Dockerfile.server) for
# production; this target is for local dev.
#
# Closes IS3 from the E06_S01 critique: invokes ``python -m
# server.main`` (rather than the bare ``uvicorn server.main:app``
# CLI form) so the env-var bind overrides actually apply. The
# ``__main__`` block in server/main.py reads Config and passes
# bind_host / bind_port into uvicorn.run(). The CLI form would
# silently ignore ARXMCP_BIND_PORT.
up:
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), \
		f'arXMCP requires Python >= 3.$(MIN_PY_MINOR); got {sys.version_info[:2]}. \
Try: make up PYTHON=python3.$(MIN_PY_MINOR)'"
	$(PYTHON) -m server.main

ingest:
	@# E11_S01 — bulk ingest orchestrator. The Python module owns the
	@# per-paper loop (ar5iv → LaTeXML → chunk → embed → staging
	@# LanceDB). The operator runs `make ingest ARGS="--paper-ids-file=
	@# tools/seed-papers.txt --limit=5"` for a smoke test before the
	@# full multi-day run. The active corpus-version.json is NOT
	@# advanced — that's E11_S05's atomic cutover.
	@#
	@# NOTE on ARGS: paths inside ARGS must not contain spaces — Make's
	@# shell expansion splits at whitespace before argparse sees the
	@# tokens. Use an absolute, space-free path for --paper-ids-file.
	@#
	@# See docs/ops/bulk-ingest-runbook.md for the operator workflow.
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), \
		f'arXMCP requires Python >= 3.$(MIN_PY_MINOR); got {sys.version_info[:2]}. \
Try: make ingest PYTHON=python3.$(MIN_PY_MINOR)'"
	$(PYTHON) -m ingest.bulk_ingest $(ARGS)

delta:
	@# E11_S02 — OAI-PMH nightly delta loop. The Python module
	@# harvests yesterday's new/updated papers from arXiv's
	@# https://oaipmh.arxiv.org/oai and feeds them through the same
	@# per-paper pipeline as `make ingest` (writes to the staging
	@# LanceDB). Canonical production invocation is via systemd
	@# (ops/systemd/arxmcp-delta.{service,timer}) or cron
	@# (ops/cron/arxmcp-delta.sh). This Makefile target is for
	@# operator smoke tests + manual one-shot runs.
	@#
	@# See docs/ops/delta-loop.md for the operator workflow.
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), \
		f'arXMCP requires Python >= 3.$(MIN_PY_MINOR); got {sys.version_info[:2]}. \
Try: make delta PYTHON=python3.$(MIN_PY_MINOR)'"
	$(PYTHON) -m ingest.oai_delta $(ARGS)

re-embed:
	@# E11_S03 — partial re-embed driver. Reads the active LanceDB,
	@# re-chunks every paper with the current chunker_version, diffs
	@# the new chunk-id set against the old, copies unchanged
	@# embeddings from the old LanceDB version, and re-runs the
	@# embedder only for new/changed chunks. Writes to the staging
	@# LanceDB; active corpus-version.json is NEVER advanced (that
	@# is E11_S05's atomic cutover).
	@#
	@# NOTE on ARGS: paths inside ARGS must not contain spaces —
	@# Make's shell expansion splits at whitespace before argparse
	@# sees the tokens. Use an absolute, space-free path for
	@# --paper-ids-file.
	@#
	@# Operator workflow: see docs/ops/re-embed-runbook.md for the
	@# scenario-by-scenario GPU-hours table and the
	@# embedding-space-mixing warning.
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), \
		f'arXMCP requires Python >= 3.$(MIN_PY_MINOR); got {sys.version_info[:2]}. \
Try: make re-embed PYTHON=python3.$(MIN_PY_MINOR)'"
	$(PYTHON) -m ingest.re_embed $(ARGS)

watchdog:
	@# E11_S04 — drift watchdog. Runs the E05 retrieval-quality
	@# eval against the STAGING LanceDB and compares the nDCG@5
	@# mean against the most-recent prior eval report. Writes a
	@# quarantine sentinel at var/arxmcp/ops/eval-quarantine.flag
	@# if the regression exceeds the configured threshold. The
	@# active corpus-version.json is NEVER touched — staging IS
	@# quarantine; the sentinel is what E11_S05's cutover script
	@# reads to refuse promotion.
	@#
	@# NOTE on ARGS: paths inside ARGS must not contain spaces —
	@# Make's shell expansion splits at whitespace before argparse
	@# sees the tokens. Use an absolute, space-free path for
	@# --fixture-path / --report-dir.
	@#
	@# Operator workflow: see docs/ops/drift-watchdog.md for the
	@# threshold-tuning table, the cutover dependency, and the
	@# quarantine-clearance procedure.
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), \
		f'arXMCP requires Python >= 3.$(MIN_PY_MINOR); got {sys.version_info[:2]}. \
Try: make watchdog PYTHON=python3.$(MIN_PY_MINOR)'"
	$(PYTHON) -m ops.watchdog_eval $(ARGS)

cutover:
	@# E11_S05 — 200K cutover activation. Checks the 4 activation
	@# criteria (seed eval, staging watchdog, ingest complete,
	@# restore drill passed) and performs an atomic directory
	@# swap (lancedb/ -> lancedb-prev/, lancedb-staging/ ->
	@# lancedb/). Rollback (`make cutover ARGS="--rollback"`) is
	@# the inverse swap; total wall-clock < 30s.
	@#
	@# NOTE on ARGS: paths inside ARGS must not contain spaces —
	@# Make's shell expansion splits at whitespace before argparse
	@# sees the tokens.
	@#
	@# Operator workflow: see docs/ops/cutover-runbook.md.
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), \
		f'arXMCP requires Python >= 3.$(MIN_PY_MINOR); got {sys.version_info[:2]}. \
Try: make cutover PYTHON=python3.$(MIN_PY_MINOR)'"
	$(PYTHON) -m ops.cutover $(ARGS)

daily-report:
	@# E14_S04 — daily ops metrics report. Scrapes /metrics from
	@# the running server (default http://127.0.0.1:7733/metrics)
	@# and writes markdown to var/arxmcp/ops/daily-reports/<date>.md.
	@# Use `make daily-report ARGS="--dry-run --fixture
	@# tests/fixtures/metrics_sample.txt"` to render against the
	@# saved fixture without touching the network or disk.
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), \
		f'arXMCP requires Python >= 3.$(MIN_PY_MINOR); got {sys.version_info[:2]}. \
Try: make daily-report PYTHON=python3.$(MIN_PY_MINOR)'"
	$(PYTHON) -m tools.daily_metrics_report $(ARGS)

parser-failures-report:
	@# E14_S04 — weekly parser-failures review. Aggregates
	@# var/arxmcp/ops/parser-failures/*.{log,jsonl} into an
	@# ISO-week markdown report at
	@# var/arxmcp/ops/reports/parser-failures-<YYYY>-W<NN>.md.
	@# Use `make parser-failures-report ARGS="--dry-run --week
	@# 2026-W19"` to inspect a specific historical week.
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), \
		f'arXMCP requires Python >= 3.$(MIN_PY_MINOR); got {sys.version_info[:2]}. \
Try: make parser-failures-report PYTHON=python3.$(MIN_PY_MINOR)'"
	$(PYTHON) -m tools.parser_failures_report $(ARGS)
