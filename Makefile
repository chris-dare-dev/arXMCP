# m2 critique F8 / m3: split the single 219-char .PHONY line into per-section
# groups for readability. Each .PHONY: stanza below pairs with the section
# it describes — adding a new target means appending it to the matching
# group rather than scrolling to find a single mega-line.

# FIRST TIME? — the onboarding-uplift verbs an operator needs on a
# fresh clone before they can ingest + query.
.PHONY: help bootstrap up up-wizard

# CORPUS LIFECYCLE — bulk-ingest + reindex paths (E11).
.PHONY: ingest delta re-embed re-embed-all ingest-recover-preambles

# OPS / MAINTENANCE — daily checks, status, drift, cutover.
.PHONY: test eval status watchdog cutover notebook-cutover
.PHONY: daily-report parser-failures-report sbom refresh-arxiv-ca
.PHONY: wheel-check wheel-check-full desktop-conformance
.PHONY: desktop-package desktop-package-check desktop-package-clean desktop-model-check

# NOTEBOOK CRUD (m2) — first-class Make verbs for the notebook
# lifecycle (proposal §9; backed by tools/notebook_*.py + /ui/api/*).
.PHONY: init add notebook-list

# REPAIR / RECONCILE (m3) — heal the on-disk-vs-registry split + the
# corpus-version.json marker drift bugs.
.PHONY: repair-registry reconcile

# Override with `make test PYTHON=python3.13` if your default python3 is too old.
PYTHON ?= python3
MIN_PY_MINOR := 11
# notebook-ops-hardening-m4: port `make status` curls. Mirrors the server
# default (server/config.py DEFAULT_BIND_PORT); override via the env var.
ARXMCP_BIND_PORT ?= 7733
# onboarding-uplift-m2: per-call args for `make init` / `make add`.
# Override on the command line: `make init NOTEBOOK=demo EMAIL=me@x`.
NOTEBOOK ?=
EMAIL ?=
MINERU_BIN ?=
PAPER ?=
ifeq ($(OS),Windows_NT)
DESKTOP_EXE_SUFFIX := .exe
else
DESKTOP_EXE_SUFFIX :=
endif

help:
	@echo "arXMCP development targets:"
	@echo ""
	@echo "  FIRST TIME? (onboarding-uplift-m2):"
	@echo "  make bootstrap                 Set up dev env and create var/arxmcp/ tree"
	@echo "  make init NOTEBOOK=<slug> [EMAIL=<addr>]"
	@echo "                                 Scaffold a notebook on disk + register it in"
	@echo "                                 notebooks.db; optionally persist your arXiv"
	@echo "                                 polite-pool email to operator_settings"
	@echo "                                 (CLI fetch tools read it without env var)."
	@echo "  make add NOTEBOOK=<slug> PAPER=<arxiv-id>"
	@echo "                                 Tag a paper into a notebook. POSTs to the"
	@echo "                                 running server if /healthz is up; else"
	@echo "                                 appends to var/arxmcp/notebooks/<slug>/papers.txt."
	@echo "  make notebook-list             List registered notebooks (live REST if server up,"
	@echo "                                 else direct SQLite read)."
	@echo "  make ingest                    Bulk-ingest the seed corpus into the shared LanceDB"
	@echo "                                 (E11_S01; see docs/ops/bulk-ingest-runbook.md)."
	@echo "  make up                        Start the arxmcp-server on 127.0.0.1:7733."
	@echo "  make up-wizard                 Start with ARXMCP_BOOTSTRAP_MODE=1 (fresh-clone"
	@echo "                                 wizard mode). MCP tools return no_notebook_selected"
	@echo "                                 envelope until first ingest completes; server then"
	@echo "                                 promotes itself in-process (no restart needed)."
	@echo ""
	@echo "  REPAIR / RECONCILE (onboarding-uplift-m3) — corrective maintenance, NOT first-time:"
	@echo "  make repair-registry           Re-register on-disk notebooks missing from"
	@echo "                                 notebooks.db. Server-up curls"
	@echo "                                 POST /ui/api/admin/repair-registry;"
	@echo "                                 server-down opens NotebooksStore directly."
	@echo "  make reconcile NOTEBOOK=<slug> Heal corpus-version.json marker drift for one"
	@echo "                                 notebook. Pass NOTEBOOK= for per-notebook;"
	@echo "                                 omit for the SHARED global corpus."
	@echo ""
	@echo "  EVERYTHING ELSE:"
	@echo "  make test        Run ruff + pytest"
	@echo "  make eval        Run the Tier-0 retrieval-quality gate (see .claude/TIER-GATES.md)"
	@echo "  make status      Print a one-line running/ready summary from /status"
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
	@echo "  make wheel-check            Build the wheel, install it into a throwaway venv, assert ops/ + server/frontend/ + console scripts (issue #206; ~10s)"
	@echo "  make wheel-check-full       Same, but an isolated venv with the REAL deps + an ARXMCP_BOOTSTRAP_MODE=1 boot polled at /healthz. Pre-publish gate (~4 min warm)"
	@echo "  make desktop-conformance    Build the locked fixture sidecar, then run its Rust/Python contract and lifecycle gate with zero skips"
	@echo "  make desktop-package        Build the PyInstaller onedir desktop bundle from the committed spec into var/desktop-package/dist/ (macOS/Linux only; first run provisions the pinned build venv and NEEDS NETWORK; fails on any build-machine path in the artifact)"
	@echo "  make desktop-package-check  Packaging gate: two consecutive cold-cache builds + determinism/hygiene proofs (AC1-AC5) with zero skips (macOS/Linux only; ~150s of builds after the one-time network provisioning)"
	@echo "  make desktop-model-check    Real-model gate: build the bundle, then load the REAL BGE-M3 + reranker weights from the EXTERNAL HuggingFace cache and check the production encode/rerank output against the committed golden fixture (both pinned revisions must already be cached)"
	@echo "  make desktop-package-clean  Reclaim var/desktop-package/ (~1 GB persistent build venv plus ~0.75 GB per bundle)"
	@echo ""
	@echo "Override the python interpreter with: make test PYTHON=python3.13"
	@echo ""
	@echo "Before running the arXiv CLI fetch tools (tools/notebook_fetch.py,"
	@echo "tools/recover_preambles.py, ingest/inspire_ingest.py — NOT"
	@echo "'make up'; the server REJECTS the var), export"
	@echo "ARXMCP_CONTACT_EMAIL=<your-email> for the User-Agent (arXiv TOS)."

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
		echo "NOTE: export ARXMCP_CONTACT_EMAIL=<your-email> before running"; \
		echo "the arXiv CLI fetch tools (tools/notebook_fetch.py,"; \
		echo "tools/recover_preambles.py, ingest/inspire_ingest.py)."; \
		echo "The server itself REJECTS the var — keep it unset for 'make up'."; \
	fi

test:
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), \
		f'arXMCP requires Python >= 3.$(MIN_PY_MINOR); got {sys.version_info[:2]}. \
Try: make test PYTHON=python3.$(MIN_PY_MINOR)'"
	$(PYTHON) -m ruff check .
	$(PYTHON) -m pytest

# desktop-distribution-m3 (+m5): the authoritative desktop boundary gate. The
# broad Python suite keeps Rust optional, but this target must fail rather than
# skip executable identity, loopback ownership, authentication, and lifecycle
# tests. m5 adds the supervisor build plus the real-child lifecycle suite: the
# marker expression opts the requires_desktop_stack tests IN while still
# running the file's fast tests, so the gate runs test_desktop_child.py with
# zero skips. DESKTOP_SUPERVISOR_BIN is deliberately NOT ARXMCP_-prefixed —
# tests in that file import server.main, whose unknown-ARXMCP_* scan would
# FATAL on a harness-only variable. BOTH env vars arm conftest's zero-skip
# guard (m6 critique H2/H5): keying it on DESKTOP_SUPERVISOR_BIN alone left
# the contract line — which runs AC3's stress and AC5's loopback proof —
# able to skip both while this target still exited 0. m9 adds the support-floor
# line with BOTH vars set: its artifact check reads minos off the two binaries
# built above, so it must run where they exist and must not be skippable.
desktop-conformance:
	cargo fmt --all --manifest-path apps/desktop/Cargo.toml -- --check
	cargo test --locked --manifest-path apps/desktop/Cargo.toml --workspace
	cargo clippy --locked --manifest-path apps/desktop/Cargo.toml --workspace --all-targets --all-features -- -D warnings
	cargo build --locked --manifest-path apps/desktop/Cargo.toml --bin fixture-sidecar
	cargo build --locked --manifest-path apps/desktop/Cargo.toml --bin supervisor
	ARXMCP_FIXTURE_SIDECAR="$(CURDIR)/apps/desktop/target/debug/fixture-sidecar$(DESKTOP_EXE_SUFFIX)" $(PYTHON) -m pytest tests/test_desktop_contract.py -m "requires_desktop_stack or not requires_desktop_stack"
	DESKTOP_SUPERVISOR_BIN="$(CURDIR)/apps/desktop/target/debug/supervisor$(DESKTOP_EXE_SUFFIX)" $(PYTHON) -m pytest tests/test_desktop_child.py -m "requires_desktop_stack or not requires_desktop_stack"
	ARXMCP_FIXTURE_SIDECAR="$(CURDIR)/apps/desktop/target/debug/fixture-sidecar$(DESKTOP_EXE_SUFFIX)" DESKTOP_SUPERVISOR_BIN="$(CURDIR)/apps/desktop/target/debug/supervisor$(DESKTOP_EXE_SUFFIX)" $(PYTHON) -m pytest tests/test_desktop_support_floor.py -m "requires_desktop_stack or not requires_desktop_stack"
	# m10 self-authored arm: the ONLY line here that runs with
	# ARXMCP_DESKTOP_LAUNCH_PLAN deliberately ABSENT. Needs BOTH binaries —
	# the supervisor under test and the fixture staged in m7's onedir shape —
	# and both vars also arm conftest's zero-skip guard, so the unset-plan
	# evidence cannot go missing behind a green run.
	ARXMCP_FIXTURE_SIDECAR="$(CURDIR)/apps/desktop/target/debug/fixture-sidecar$(DESKTOP_EXE_SUFFIX)" DESKTOP_SUPERVISOR_BIN="$(CURDIR)/apps/desktop/target/debug/supervisor$(DESKTOP_EXE_SUFFIX)" $(PYTHON) -m pytest tests/test_desktop_self_authored_launch.py -m "requires_desktop_stack or not requires_desktop_stack"

# desktop-distribution-m7 — build the PyInstaller onedir sidecar bundle. The
# driver provisions a uv-locked build venv (PyInstaller hash-pinned in
# apps/desktop/pyinstaller/requirements-build.txt, deliberately OUTSIDE
# pyproject.toml/uv.lock), sanitizes direct_url.json BEFORE freezing, and
# fails on any build-machine path string in the artifact — including .pyc
# bytes inside the executables' embedded PYZ archives. Work/dist paths live
# under gitignored var/desktop-package/, never PyInstaller's repo-root
# build/ default.
desktop-package:
	$(PYTHON) apps/desktop/pyinstaller/desktop_package.py build

# The m7 packaging gate. DESKTOP_PACKAGE_GATE arms conftest's zero-skip guard
# (same mechanism as desktop-conformance) and the tautology -m expression
# opts the requires_desktop_package tests IN while running the file's fast
# tests too, so this session cannot exit 0 with the two-build determinism
# evidence silently skipped. Budget ~150s of builds (plus one-time venv
# provisioning); deliberately NOT part of `make test` (m6 findings.json:240
# precedent against unmarked expensive desktop tests in the default gate).
desktop-package-check:
	DESKTOP_PACKAGE_GATE=1 $(PYTHON) -m pytest tests/test_desktop_package.py -m "requires_desktop_package or not requires_desktop_package"

# The m8 real-model gate. Separate target because it is a different concern
# and a different cost class: it loads ~4.6 GB of REAL weights from the
# operator's EXTERNAL HuggingFace cache (HF_HUB_OFFLINE, so an uncached pin
# fails rather than downloading) and boots the frozen child. Depends on
# desktop-package because the bundle assertions are made against a real
# artifact; the tests RAISE rather than skip when it is missing.
desktop-model-check: desktop-package
	DESKTOP_BUNDLED_MODEL_GATE=1 $(PYTHON) -m pytest tests/test_desktop_bundled_model.py -m "requires_bundled_model or not requires_bundled_model"

# The build venv is intentionally REUSED across runs, so var/desktop-package/
# is persistent (~1 GB venv + ~0.75 GB per bundle), not transient. This is the
# documented way to reclaim it; the next build re-provisions from the network.
desktop-package-clean:
	rm -rf var/desktop-package

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

# onboarding-uplift-m4: wizard-mode entry point for fresh-clone operators.
# Sets ARXMCP_BOOTSTRAP_MODE=1 so the server boots without a corpus;
# MCP tools return the structured no_notebook_selected envelope until the
# first ingest completes and Resources.late_bind() promotes the process.
# Does NOT require a pre-existing corpus-version.json.
up-wizard:
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), \
		f'arXMCP requires Python >= 3.$(MIN_PY_MINOR); got {sys.version_info[:2]}. \
Try: make up-wizard PYTHON=python3.$(MIN_PY_MINOR)'"
	ARXMCP_BOOTSTRAP_MODE=1 $(PYTHON) -m server.main

status:
	@# notebook-ops-hardening-m4: one-action "is it running + ready?".
	@# curl the /status health+json endpoint and print a human line. A 503
	@# (fail/warming), a non-2xx, or an unreachable server all curl-fail and
	@# print the DOWN line. m4 rect IS1: an if/else (NOT `... || echo`) so a
	@# crash in status_line.py propagates its OWN non-zero exit + traceback
	@# rather than being silently misreported as "DOWN" (a healthy server +
	@# broken parser must not look like a down server).
	@if out=$$(curl -sf --max-time 5 "http://127.0.0.1:$(ARXMCP_BIND_PORT)/status" 2>/dev/null); then \
		printf '%s' "$$out" | $(PYTHON) tools/status_line.py; \
	else \
		echo "DOWN: arxmcp-server at 127.0.0.1:$(ARXMCP_BIND_PORT)/status is down or warming up"; \
	fi

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

wheel-check:
	@# issue #206 / trustworthy-release-m4 — the packaging-boundary gate.
	@# Builds the wheel, installs it into a THROWAWAY venv, and asserts
	@# that what an operator receives matches what the docs promise.
	@#
	@# This exists because packaging bugs are invisible from a source
	@# checkout: the repo root is on sys.path and every data file is right
	@# there on disk, so the suite passes and `make up` works while the
	@# wheel ships none of it. Five holes were open simultaneously until
	@# 2026-07-31 — the whole ops/ layer, frontend/, router_patterns.yaml,
	@# server/schemas/*.json and tools/seed-papers.txt — plus an
	@# arxmcp-server console script that docs/install.md promised and
	@# pyproject.toml never declared.
	@#
	@# Needs `uv` (or `python -m build`) on PATH. No network.
	$(PYTHON) tools/wheel_install_check.py --mode contents

wheel-check-full:
	@# The pre-publish gate (docs/releasing.md). Same as `wheel-check`,
	@# but the venv is fully isolated and resolves the REAL dependency set
	@# (~2 GB: torch, transformers, faiss), then boots the installed
	@# server with ARXMCP_BOOTSTRAP_MODE=1 and polls /healthz.
	@#
	@# Slow (~4 min on a warm uv cache, ~15 min cold) and network-bound.
	@# Run it before any PyPI upload — it is the only check that proves an
	@# operator with nothing pre-installed ends up with a server that
	@# starts.
	$(PYTHON) tools/wheel_install_check.py --mode full

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


# ============================================================================
# onboarding-uplift-m2: thin Make wrappers for the notebook lifecycle
# ============================================================================
#
# Each target is a thin shell over an existing `tools/notebook_*.py` module
# or a `/ui/api/notebooks/*` REST endpoint. See proposal at
# .claude/notes/uplift/startup-ux/streamlined-flow-proposal.md §9 + decisions
# at .claude/notes/uplift/startup-ux/decisions.md (D2: corpus-level ingest,
# D4: operator settings in SQLite). The synthesis at
# .claude/notes/milestones/onboarding-uplift-m2/research-synthesis.md is
# the locked design.
#
# Pattern: `make <verb> NOTEBOOK=<slug> [EMAIL=<addr>] [PAPER=<id>]`.

init:
	@# AC1 — scaffold the notebook dir + register in notebooks.db + persist
	@# EMAIL to operator_settings (if given). Fully offline-capable; no
	@# server needed. notebook_init.py handles all three side effects
	@# idempotently (m2 synthesis §3 D2).
	@# m2 critique IS1: quote NOTEBOOK + EMAIL so an inadvertent space
	@# (e.g. ``make init NOTEBOOK="my slug"``) raises a clean argparse
	@# error from Python instead of word-splitting into extra positional
	@# arguments. The slug regex enforces no-whitespace at the Python
	@# layer; this is belt-and-braces.
	@[ -n "$(NOTEBOOK)" ] || { echo "ERROR: NOTEBOOK= required. Usage: make init NOTEBOOK=<slug> [EMAIL=<addr>] [MINERU_BIN=<path>]" >&2; exit 1; }
	@# ingest-robustness-m1 AC3: also persist MINERU_BIN when given. make's
	@# its conditional-flag idiom emits each flag only when its var is set, so
	@# EMAIL and MINERU_BIN stay independent and correctly quoted.
	@$(PYTHON) -m tools.notebook_init "$(NOTEBOOK)" $(if $(strip $(EMAIL)),--email "$(EMAIL)") $(if $(strip $(MINERU_BIN)),--mineru-bin "$(MINERU_BIN)")

add:
	@# AC3 — tag a paper into a notebook. If server is up
	@# (/healthz 200), POST to /ui/api/notebooks/<slug>/papers with the
	@# constructed arXiv URL. If server is down (curl exit 7), append the
	@# bare paper_id to var/arxmcp/notebooks/<slug>/papers.txt with
	@# idempotency (grep -qxF || echo). REST 404 / 5xx is a CLEAN error
	@# — never auto-fallback (would create orphan papers.txt rows;
	@# m2 synthesis §3 D5 / FM-5).
	@[ -n "$(NOTEBOOK)" ] || { echo "ERROR: NOTEBOOK= required. Usage: make add NOTEBOOK=<slug> PAPER=<id>" >&2; exit 1; }
	@[ -n "$(PAPER)" ] || { echo "ERROR: PAPER= required. Usage: make add NOTEBOOK=<slug> PAPER=<id>" >&2; exit 1; }
	@# m2 critique IS1 (LOW): quote every shell-word interpolation of
	@# Make + shell variables. NOTEBOOK validation at the Python layer
	@# (slug regex) already rejects whitespace, but the Make recipe
	@# must not depend on that — a future contributor reading the
	@# recipe in isolation expects shell-safe quoting.
	@if curl -sf --max-time 2 "http://127.0.0.1:$(ARXMCP_BIND_PORT)/healthz" >/dev/null 2>&1; then \
		echo "server up — POST /ui/api/notebooks/$(NOTEBOOK)/papers"; \
		curl -sf --fail-with-body --max-time 30 \
			-X POST -H "Content-Type: application/json" \
			-d '{"arxiv_url":"https://arxiv.org/abs/$(PAPER)"}' \
			"http://127.0.0.1:$(ARXMCP_BIND_PORT)/ui/api/notebooks/$(NOTEBOOK)/papers" \
			|| { echo "ERROR: REST call failed — see above" >&2; exit 1; }; \
		echo; \
	else \
		[ -d "var/arxmcp/notebooks/$(NOTEBOOK)" ] || { echo "ERROR: notebook '$(NOTEBOOK)' not initialized — run 'make init NOTEBOOK=$(NOTEBOOK)' first" >&2; exit 1; }; \
		papers_txt="var/arxmcp/notebooks/$(NOTEBOOK)/papers.txt"; \
		if grep -qxF "$(PAPER)" "$$papers_txt" 2>/dev/null; then \
			echo "server down — $(PAPER) already in $$papers_txt (no-op)"; \
		else \
			echo "$(PAPER)" >> "$$papers_txt"; \
			echo "server down — appended $(PAPER) to $$papers_txt"; \
		fi; \
	fi

notebook-list:
	@# AC4 — list registered notebooks. Live REST when server up
	@# (curl /ui/api/notebooks → one-line jq via python -c), else the
	@# offline helper opens notebooks.db directly via
	@# tools/notebook_list_offline.py (which uses NotebooksStore so
	@# any pending migrations auto-run on open).
	@if curl -sf --max-time 2 "http://127.0.0.1:$(ARXMCP_BIND_PORT)/healthz" >/dev/null 2>&1; then \
		curl -sf --max-time 5 "http://127.0.0.1:$(ARXMCP_BIND_PORT)/ui/api/notebooks" \
			| $(PYTHON) -c 'import json,sys; rows=json.load(sys.stdin); print(f"{len(rows)} notebook(s) — via /ui/api/notebooks:"); [print(f"  {r[\"slug\"]} ({r.get(\"display_name\") or r[\"slug\"]})") for r in rows]'; \
	else \
		$(PYTHON) -m tools.notebook_list_offline; \
	fi

# ============================================================================
# onboarding-uplift-m3: heal registry-vs-disk + corpus-version.json drift
# ============================================================================
#
# Two heal commands. Server-up = curl the REST endpoint; server-down =
# direct Python via tools/notebook_repair_registry.py +
# tools/notebook_reconcile_marker.py (which themselves route writes
# through NotebooksStore.create_notebook — m2 critique F1 lesson:
# never direct SQLite INSERT to the notebooks table).
#
# See proposal §9 + decisions.md + .claude/notes/milestones/onboarding-uplift-m3/.

repair-registry:
	@# AC4 — walk var/arxmcp/notebooks/ and register on-disk dirs that
	@# have a valid corpus-version.json marker but aren't in
	@# notebooks.db. Live REST when server up; direct NotebooksStore
	@# walk when down. Idempotent at both paths (INSERT OR IGNORE
	@# semantic on the server side; existing-slugs filter on the CLI).
	@if curl -sf --max-time 2 "http://127.0.0.1:$(ARXMCP_BIND_PORT)/healthz" >/dev/null 2>&1; then \
		echo "server up — POST /ui/api/admin/repair-registry"; \
		curl -sf --fail-with-body --max-time 30 \
			-X POST -H "Content-Type: application/json" \
			"http://127.0.0.1:$(ARXMCP_BIND_PORT)/ui/api/admin/repair-registry" \
			|| { echo "ERROR: REST call failed — see above" >&2; exit 1; }; \
		echo; \
	else \
		echo "server down — running tools.notebook_repair_registry"; \
		$(PYTHON) -m tools.notebook_repair_registry; \
	fi

reconcile:
	@# AC4 — recount the LanceDB at the marker's pinned version and
	@# atomically rewrite corpus-version.json (m3 synthesis §3 D4
	@# byte-identical idempotency: re-runs against unchanged state are
	@# byte-identical, not just same-data). Pass NOTEBOOK=<slug> for
	@# per-notebook; omit for the SHARED global corpus reconcile.
	@if [ -z "$(NOTEBOOK)" ]; then \
		echo "no NOTEBOOK= passed — reconciling SHARED global corpus"; \
		SCOPE_SLUG=""; SCOPE_LABEL="shared"; \
	else \
		SCOPE_SLUG="$(NOTEBOOK)"; SCOPE_LABEL="$(NOTEBOOK)"; \
	fi; \
	if curl -sf --max-time 2 "http://127.0.0.1:$(ARXMCP_BIND_PORT)/healthz" >/dev/null 2>&1; then \
		if [ -z "$$SCOPE_SLUG" ]; then \
			echo "server-up + no NOTEBOOK= → falling back to CLI (REST path is per-notebook only)"; \
			$(PYTHON) -m tools.notebook_reconcile_marker --shared; \
		else \
			echo "server up — POST /ui/api/notebooks/$$SCOPE_SLUG/reconcile-marker"; \
			curl -sf --fail-with-body --max-time 30 \
				-X POST -H "Content-Type: application/json" \
				"http://127.0.0.1:$(ARXMCP_BIND_PORT)/ui/api/notebooks/$$SCOPE_SLUG/reconcile-marker" \
				|| { echo "ERROR: REST call failed — see above" >&2; exit 1; }; \
			echo; \
		fi; \
	else \
		echo "server down — running tools.notebook_reconcile_marker"; \
		if [ -z "$$SCOPE_SLUG" ]; then \
			$(PYTHON) -m tools.notebook_reconcile_marker --shared; \
		else \
			$(PYTHON) -m tools.notebook_reconcile_marker "$$SCOPE_SLUG"; \
		fi; \
	fi
