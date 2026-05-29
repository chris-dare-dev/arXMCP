.PHONY: help bootstrap test eval up status ingest delta re-embed re-embed-all ingest-recover-preambles watchdog cutover notebook-cutover daily-report parser-failures-report sbom refresh-arxiv-ca

# Override with `make test PYTHON=python3.13` if your default python3 is too old.
PYTHON ?= python3
MIN_PY_MINOR := 11
# notebook-ops-hardening-m4: port `make status` curls. Mirrors the server
# default (server/config.py DEFAULT_BIND_PORT); override via the env var.
ARXMCP_BIND_PORT ?= 7733

help:
	@echo "arXMCP development targets:"
	@echo ""
	@echo "  make bootstrap   Set up dev env and create var/arxmcp/ tree"
	@echo "  make test        Run ruff + pytest"
	@echo "  make eval        Run the Tier-0 retrieval-quality gate (see .claude/TIER-GATES.md)"
	@echo "  make up          Start the arxmcp-server on 127.0.0.1:7733 (E06_S01)"
	@echo "  make status      Print a one-line running/ready summary from /status"
	@echo "  make ingest      Run the bulk ingest orchestrator (E11_S01; see docs/ops/bulk-ingest-runbook.md)"
	@echo "  make delta       Run the OAI-PMH nightly delta loop (E11_S02; see docs/ops/delta-loop.md)"
	@echo "  make re-embed    Run the partial re-embed driver (E11_S03; see docs/ops/re-embed-runbook.md)"
	@echo "  make re-embed-all Re-embed every LanceDB dataset (shared + notebook-scoped; embedder-truncation-m1)"
	@echo "  make ingest-recover-preambles  Back-fill raw .tex + preamble.json for ar5iv-only papers (notebook-preamble-recovery-m1)"
	@echo "                                 NOTE: triggers chunk_id rotation; follow with make re-embed-all"
	@echo "  make watchdog    Run the drift watchdog against staging (E11_S04; see docs/ops/drift-watchdog.md)"
	@echo "  make cutover     Activate the staging corpus as the new active (E11_S05; see docs/ops/cutover-runbook.md)"
	@echo "  make notebook-cutover       Promote notebook lancedb-staging -> lancedb (notebook-cutover-m1)"
	@echo "                              DEFAULT: ALL promotable notebooks; scope with ARGS='--notebook=<slug>'."
	@echo "                              Rollback: ARGS='--rollback --notebook=<slug>' (single-level). MEASURE first;"
	@echo "                              RESTART the server after (it holds an open handle on the old inode)."
	@echo "  make daily-report           Scrape /metrics and write the daily ops report (E14_S04; see docs/ops/daily-ops-cadence.md)"
	@echo "  make parser-failures-report Roll up parser-failures/*.{log,jsonl} into the weekly review (E14_S04; see docs/ops/parser-failure-review.md)"
	@echo "  make sbom        Generate CycloneDX SBOMs + grype scan (E13_S06; see .claude/docs/security-threat-6-audit.md)"
	@echo "  make refresh-arxiv-ca       Re-download infra/ca/arxiv-ca-bundle.pem and verify against live arxiv hosts (E13_S07c)"
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

status:
	@# notebook-ops-hardening-m4: one-action "is it running + ready?".
	@# curl the /status health+json endpoint and print a human line. A
	@# 503 (fail), a non-2xx, or an unreachable server all fall through to
	@# the DOWN line (curl -sf exits non-zero -> the || branch). The
	@# captured-then-piped form avoids double output on the down path.
	@out=$$(curl -sf --max-time 5 "http://127.0.0.1:$(ARXMCP_BIND_PORT)/status" 2>/dev/null) \
		&& printf '%s' "$$out" | $(PYTHON) tools/status_line.py \
		|| echo "DOWN: arxmcp-server not reachable at 127.0.0.1:$(ARXMCP_BIND_PORT)/status"

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

ingest-recover-preambles:
	@# notebook-preamble-recovery-m1 — back-fill raw .tex + preamble.json
	@# for papers that were ar5iv-ingested before this milestone shipped.
	@# Walks var/arxmcp/corpus/parsed/ (137 papers live as of 2026-05-28;
	@# 0 in corpus/raw/). For each missing preamble.json: politeness_sleep,
	@# fetch_eprint with 503 backoff, extract_preamble.
	@#
	@# Requires ARXMCP_CONTACT_EMAIL (User-Agent for /e-print/).
	@#
	@# OPERATOR WARNING: after this completes, the next `make re-embed-all`
	@# will detect that body+preamble of every back-filled paper now
	@# differs (preamble bytes flow into the chunk_id hash), so re_embed
	@# produces re_embedded ≫ copied for the affected notebooks —
	@# expect 2-4 hours additional CPU. This is INTENDED (AC5).
	@#
	@# NOTE on ARGS: paths inside ARGS must not contain spaces. Use
	@# `ARGS="--notebook=<slug>"` to scope to one notebook's papers.txt;
	@# `ARGS="--limit=N"` for smoke-testing.
	@#
	@# Concurrency: run ONE back-fill at a time (no per-paper lock; the
	@# arXiv politeness contract is collective across all your machines).
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), \
		f'arXMCP requires Python >= 3.$(MIN_PY_MINOR); got {sys.version_info[:2]}. \
Try: make ingest-recover-preambles PYTHON=python3.$(MIN_PY_MINOR)'"
	$(PYTHON) -m tools.recover_preambles $(ARGS)

re-embed-all:
	@# embedder-truncation-m1 — notebook-aware re-embed driver.
	@# Discovers every LanceDB dataset under var/arxmcp/notebooks/
	@# (plus the shared corpus if non-empty) and invokes the single-
	@# path re_embed driver against each. Required after CHUNKER_VERSION
	@# bumps or token-budget changes that mandate corpus-wide rebuilds.
	@#
	@# Operator workflow: run this once per chunker-bump; expect a
	@# multi-hour run for >10K chunks at the post-bump 2048-token
	@# budget. ARGS forwards to the driver (e.g. ARGS="--dry-run").
	@#
	@# NOTE on ARGS: paths inside ARGS must not contain spaces —
	@# Make's shell expansion splits at whitespace before argparse
	@# sees the tokens. --dry-run has no path arg today; this warning
	@# guards future path-bearing flags added to the driver.
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), \
		f'arXMCP requires Python >= 3.$(MIN_PY_MINOR); got {sys.version_info[:2]}. \
Try: make re-embed-all PYTHON=python3.$(MIN_PY_MINOR)'"
	$(PYTHON) -m tools.re_embed_all $(ARGS)

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

notebook-cutover:
	@# notebook-cutover-m1 — per-notebook staging->active cutover.
	@# Promotes each notebook's re-embedded var/arxmcp/notebooks/<slug>/
	@# lancedb-staging to the live lancedb/ via an atomic two-rename swap
	@# (lancedb/ -> lancedb-prev-<ts>/, lancedb-staging/ -> lancedb/),
	@# building the staging BM25 index first and keeping N=2 backups.
	@#
	@# MEASURE-THEN-PROMOTE: run your pre/post comparison BEFORE this —
	@# cutover destroys the side-by-side (old active vs new staging).
	@# Defaults to ALL promotable notebooks; restrict with
	@# ARGS="--notebook=<slug>". Rollback: ARGS="--rollback
	@# --notebook=<slug>". Downgrade override: add --force.
	@#
	@# RESTART the server after a cutover — it holds an open LanceDB
	@# handle on the old inode and serves stale data until restarted.
	@#
	@# NOTE on ARGS: paths inside ARGS must not contain spaces — Make's
	@# shell expansion splits at whitespace before argparse sees them.
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), \
		f'arXMCP requires Python >= 3.$(MIN_PY_MINOR); got {sys.version_info[:2]}. \
Try: make notebook-cutover PYTHON=python3.$(MIN_PY_MINOR)'"
	$(PYTHON) -m tools.notebook_cutover $(ARGS)

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

sbom:
	@# E13_S06 — Threat-6 SBOM generation + grype scan. This target
	@# replaces the brief's ``.github/workflows/sbom.yml`` deliverable
	@# because the project explicitly has no CI gate
	@# (CLAUDE.md §4.1). Operators run ``make sbom`` before ``git
	@# push`` to verify no critical CVEs exist in the pinned Python
	@# deps OR the built server image.
	@#
	@# Required tools (script prints install hints if missing):
	@#   - cyclonedx-py    (always)
	@#   - grype           (unless ``--no-scan`` is passed via ARGS)
	@#   - syft + docker   (unless ``--skip-image`` is passed)
	@#
	@# Outputs land under .claude/docs/security/sbom/ by default; the
	@# directory is gitignored to keep raw SBOM JSON out of the repo
	@# (multi-MB; reconsider at release-tag time per the audit doc).
	@#
	@# Examples:
	@#   make sbom                          # full run (Python + image)
	@#   make sbom ARGS="--skip-image"      # Python-only (no docker)
	@#   make sbom ARGS="--no-scan"         # generate SBOMs, no grype
	@#
	@# Exit codes propagate from tools/sbom.sh:
	@#   0 OK / 1 missing tool / 2 grype found critical / 3 generator failed
	@#
	@# ARGS forwarding: tools/sbom.sh accepts only fixed flags
	@# (--skip-image, --no-scan, -h/--help) — none take an argument,
	@# so ARGS is space-safe today. For the output directory, use
	@# the SBOM_DIR env var (read by the script directly): e.g.
	@# ``SBOM_DIR=/tmp/sbom make sbom`` works without touching ARGS.
	@# A future flag that takes a path-bearing argument would need
	@# the same "no spaces in ARGS" warning as ingest/re-embed/cutover.
	bash tools/sbom.sh $(ARGS)

refresh-arxiv-ca:
	@# E13_S07c — refresh the pinned CA bundle for arxiv.org /
	@# ar5iv.labs.arxiv.org / export.arxiv.org TLS verification
	@# (Threat 7 mitigation #2). Re-downloads the canonical Let's
	@# Encrypt ISRG Root X1 PEM and verifies the resulting bundle
	@# accepts the live arxiv.org cert chain BEFORE writing to
	@# infra/ca/arxiv-ca-bundle.pem.
	@#
	@# Cadence: ISRG Root X1 is valid until 2035-06-04. Roots
	@# rotate rarely; intermediates rotate every 60-90 days but the
	@# pin survives intermediate rotations. Re-run if:
	@#   - ssl.SSLCertVerificationError on every arxiv fetch (root
	@#     has rotated), OR
	@#   - the bundle was deleted / corrupted / never committed in
	@#     a fresh clone.
	@#
	@# Required tools: curl, openssl. The target REFUSES to overwrite
	@# the bundle if the new PEM does not verify the live arxiv.org
	@# cert chain — do NOT use --no-verify or similar; review the
	@# failure and refresh manually if needed.
	@#
	@# See .claude/docs/security-threat-7-audit.md § "Refresh the
	@# pinned CA bundle" for the rationale + manual fallback.
	@command -v curl >/dev/null 2>&1 || { echo "ERROR: curl not found" >&2; exit 1; }
	@command -v openssl >/dev/null 2>&1 || { echo "ERROR: openssl not found" >&2; exit 1; }
	@mkdir -p infra/ca
	@tmp=$$(mktemp); \
		echo "Fetching ISRG Root X1 from letsencrypt.org..."; \
		curl -fsSL https://letsencrypt.org/certs/isrgrootx1.pem -o $$tmp || { rm -f $$tmp; echo "ERROR: download failed" >&2; exit 1; }; \
		echo "Verifying live arxiv.org cert chain against new bundle..."; \
		openssl s_client -connect arxiv.org:443 -servername arxiv.org -CAfile $$tmp -verify_return_error </dev/null >/dev/null 2>&1 || { rm -f $$tmp; echo "ERROR: live arxiv.org cert does NOT verify against the new bundle. NOT writing infra/ca/arxiv-ca-bundle.pem." >&2; exit 1; }; \
		echo "Verifying live export.arxiv.org cert chain..."; \
		openssl s_client -connect export.arxiv.org:443 -servername export.arxiv.org -CAfile $$tmp -verify_return_error </dev/null >/dev/null 2>&1 || { rm -f $$tmp; echo "ERROR: live export.arxiv.org cert does NOT verify against the new bundle. NOT writing infra/ca/arxiv-ca-bundle.pem." >&2; exit 1; }; \
		echo "Verifying live ar5iv.labs.arxiv.org cert chain..."; \
		openssl s_client -connect ar5iv.labs.arxiv.org:443 -servername ar5iv.labs.arxiv.org -CAfile $$tmp -verify_return_error </dev/null >/dev/null 2>&1 || { rm -f $$tmp; echo "ERROR: live ar5iv.labs.arxiv.org cert does NOT verify against the new bundle. NOT writing infra/ca/arxiv-ca-bundle.pem." >&2; exit 1; }; \
		mv $$tmp infra/ca/arxiv-ca-bundle.pem || { rm -f $$tmp; echo "ERROR: mv failed; bundle NOT updated (temp file removed)." >&2; exit 1; }; \
		echo "OK: bundle refreshed at infra/ca/arxiv-ca-bundle.pem (all three hosts verified)."; \
		echo "Review the diff and commit: git diff infra/ca/arxiv-ca-bundle.pem"
