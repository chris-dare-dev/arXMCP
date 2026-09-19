# CLAUDE.md — Context for Claude agents working in arXMCP

This file is loaded at session start by every Claude agent in this repo. It
captures the project's mission, current state, working conventions, and the
landmines learned across E01–E09. **If you're a new agent picking up this
codebase, read this top-to-bottom before touching code.**

---

## 1. Repo doc layout (READ FIRST)

This repo enforces a strict doc-placement rule:

| Location | What's allowed |
|---|---|
| **Repo root** | Only `README.md`, `CLAUDE.md`, `CHANGES.md`, `SECURITY.md`, `OWNERS.md`, `LICENSE`, `CONTRIBUTING.md`, `CONTRIBUTORS.md`. Nothing else. (The last three are the standard community-health files, added 2026-05-31.) |
| **Subdirs other than `.claude/`** | Only `README.md` and `CLAUDE.md` (if useful for that subdir). No other Markdown. |
| **`docs/`** | ONLY user-facing documentation referenced by the root `README.md` — the README's "chapters": `install.md`, `usage.md`, `api.md`, `architecture.md`, `evaluation.md`, `support.md`, `releasing.md`, plus the `docs/ops/` and `docs/observability/` runbook trees, the `docs/adr/` decision records, and `docs/security/` (all linked from `docs/README.md`). |
| **`.claude/`** | All other Markdown agents create — design notes, roadmap, milestones, agent-internal references, scans, gate specs. Free real estate; organize as `.claude/notes/`, `.claude/docs/`, `.claude/roadmap/`, etc. |

**Concrete consequences:**

- The root `README.md` is restricted to **what the project does, how to
  use it, its layout, hard constraints**. NOT a place to link the
  roadmap, list epics, or describe outstanding work.
- Anything roadmap-flavored or work-tracking goes under `.claude/`.
- Agent-internal documents (model policy, orchestrator rules, snippet
  contracts, proof-chain workflow, tier gates) live under
  `.claude/docs/` — they used to be in `docs/` but moved during the
  2026-05-10 doc consolidation.

When you create a new Markdown file, default to `.claude/` unless the
content is BOTH operator-facing AND linked from the root README.

---

## 2. What this project is

**arXMCP** is a local-first MCP (Model Context Protocol) server that exposes
a research-mathematics arXiv corpus to multi-agent Claude pipelines. The
intended consumer is a Claude **sketcher → autoformalizer → tactician →
fixer** pipeline attacking research-level mathematics — every sub-agent
shares one substrate of grounded context through this server. The MCP
surface is **8 tools** (see §6); `tools/list` is byte-frozen for BP1
prompt-cache discipline. Alongside the MCP tool surface (the primary agent
interface), a **loopback-only Jinja2+htmx operator console** at `/ui/`
ships with the server for notebook management (create / list / ingest /
rename / delete / upload); it is deliberately minimal and runs with no
build chain at runtime. Per [ADR-0001](docs/adr/0001-build-time-node-vite-allowed.md)
(Stage-2 D1), Node/Vite are permitted as **build-time-only** tooling. As
of Stage 2 the richer **`/app` SPA** (Vite + React + TS in `frontend-app/`,
committed byte-reproducible `dist/` served by FastAPI — see `server/spa.py`)
has **shipped** under a CSP **stricter** than `/ui/` (`script-src 'self'`,
no unsafe-inline); `/ui/` stays as the zero-JS fallback console and every
runtime invariant (single Python process, loopback-only, no runtime
network fetches, lockfile-reproducible assets) is preserved. See
[`.claude/notes/06-mcp-server-design.md`](.claude/notes/06-mcp-server-design.md)
§ "Browser UI surface".

**The primary workstation is Windows 11** (tier-1; the macOS machine is
secondary — Stage-1 finding 212). Commands in this file are given in
Windows-first form; POSIX equivalents in parentheses where they differ.

The full design rationale lives in
[`.claude/notes/01-mission-and-context.md`](.claude/notes/01-mission-and-context.md).
The "Lean kernel is the better critic" framing in that note is load-bearing
across every architectural decision: the valuable LLM roles live **upstream**
of verification, so we invest aggressively in retrieval and pre-loading rather
than in adversarial LLM critique of math content.

Target arXiv categories: `math.AG`, `math.NT`, `math-ph`, `hep-th`.

---

## 3. Status snapshot (2026-07-04)

> **Trust discipline:** two Stage-1 findings traced real planning errors
> to agents trusting a stale version of this section over code. When this
> table disagrees with `server/tools.py`, handler docstrings, or
> `.claude/notes/milestones/*/state.json`, **the code wins** — and fix
> this file in the same change.

| Epic | Status | What landed |
|---|---|---|
| E01 — Vertical slice | ✅ SHIPPED | 50-paper math.AG seed corpus fetched + parsed |
| E02 — Chunker | ✅ SHIPPED | Theorem-aware structural chunker, preamble extractor, regex tokenizer |
| E03 — Embedder | ✅ SHIPPED | BGE-M3 dual-column encoder (`embedding_stmt` + `embedding_proof`), singleflight |
| E04 — Vector store | ✅ SHIPPED | LanceDB `chunks` table with MVCC, BM25 index, corpus_version marker |
| E05 — Eval harness | ✅ SHIPPED | nDCG@5 / Recall@10 harness; the curated 20-query fixture is still empty (owner-led curation pending) |
| E06 — MCP server | ✅ SHIPPED | FastAPI + Streamable HTTP, stdio shim, snippet contract (tool count has since grown to 8 — see §6) |
| E07 — Hybrid retrieval | ⚠️ MODULES ONLY | BM25/ANN/RRF/reranker **modules** exist under `server/retrieval/` but are NOT wired into any live query path. `search_papers` ships **dense-only** (`retrieval_mode: "dense_only"` hardcoded in the payload). The wiring epic was CLOSED 2026-05-21 with verdict **NO** (zero P@10 lift, −10 pp top-1, 122× latency — `plans/proof-verify-handler-wiring-roadmap.md`). Do not schedule hybrid wiring without a new measured verdict at materially larger corpus scale. |
| E08 — Agent runtime | ✅ SHIPPED | Regex router, role prefixes, 3-tier retrieval cache, tool-use ID canonicalization, model policy |
| E09 — Citation graph | ✅ SHIPPED | Kùzu schema v2, OpenAlex ingest, INSPIRE-HEP enrichment, intra-paper refs, `cite_neighbors` **wired live** (verification-feedback-m1; tools v10/v11), proof-chain workflow |
| E10 — Specialized indices | ✅ SHIPPED | Definitions index + `get_definitions`, FTS5 theorem-name index + `find_lemma_by_name`, TED equation index + dense fusion in `find_equation`, LaTeXML drift detector |
| E11 — Scale cutover | ✅ SHIPPED | Bulk ingest orchestrator (`make ingest`), OAI-PMH delta loop, partial re-embed driver, drift watchdog, atomic cutover + restic backup |
| E12 — Full corpus | 🚫 SCOPED OUT | Folded into E11 |
| E13 — Security audit | ✅ SHIPPED | 10 milestones over the MCP tool surface (Threats 1–7 + logging redaction + bind regression + coverage doc); follow-up issues `chris-dare-dev/arXMCP#1`–`#6`. The `/ui/` console audit is **still open** (#9, untouched since 2026-05-29; scope-amendment draft at `docs/security/issue-9-scope-amendment-draft.md`) |
| E14 — Observability/ops | ✅ SHIPPED (S01–S05) | `/metrics` endpoint, OTel tracing, Phoenix integration, daily ops cadence + parser-failures roll-up, restic backup + restore drill. S06 + S09–S12 (Tier-5/6+ follow-ups) remain unstarted |

**Post-epic milestone era (2026-05-20 → now).** After E14 the repo moved to
`plans/<slug>-roadmap.md` roadmaps driven through `/milestone-pipeline`.
Landed families (see `plans/` + milestone state.json for ground truth):
notebook surface expansion + ops hardening + paper discovery (the notebook
model, `/ui/` console, per-notebook LanceDBs, export manifests), textbook
ingest (MinerU + markdown-native chunker, `--chunker markdown`),
verification feedback (**`lean_verify` — the 8th MCP tool**, env-gated via
`ARXMCP_ENABLE_LEAN` with `lean_status="disabled"` degradation),
proof-verify handler wiring (search filters now real: `paper_id`,
`source_kind`, notebook routing), corpus integrity/observability, UI
polish, k3s deploy manifests, Windows parse-path fixes.

**Test baseline (Windows, the tier-1 host, 2026-07-04):** `ruff check .`
clean; pytest green with documented platform skips only — see
[`.claude/notes/windows-test-triage.md`](.claude/notes/windows-test-triage.md)
for every skip class and `tests/test_windows_skip_markers.py` for the
audit that keeps skip reasons documented. (The previously advertised "29
known Windows failures" are triaged: real Windows bugs fixed in code,
environment-limited fixtures skipped with reasons.)

For per-milestone ground truth, see
[`.claude/notes/milestones/<ID>/state.json`](.claude/notes/milestones/).
Files with `phase: complete` are shipped. The authoritative roadmap index is
[`.claude/roadmap/README.md`](.claude/roadmap/README.md).

---

## 4. Working conventions — READ BEFORE COMMITTING

### 4.1 This is a single-user, single-workstation project

- **All work lands on `main` directly.** No feature branches, no pull
  requests, no code review handoff. Commit + push.
- **No CI / GitHub Actions blocking merges.** The local test suite is the
  authority — `make test` must be green before pushing.
- **Worktrees are fine** (e.g. for parallel milestone-pipeline researchers)
  but the final commits land on `main`.

### 4.2 Use the `/milestone-pipeline` command for non-trivial work

Any roadmap milestone (`E<NN>_S<MM>`) or comparable-effort ad-hoc task MUST
run through the [`/milestone-pipeline`](.claude/commands/milestone-pipeline.md)
slash command. The four phases are non-negotiable: **Research → Implement →
Critique → Rectify**. Skipping a phase is the named anti-pattern documented in
the command body.

The command uses the bespoke sub-agents defined in `.claude/agents/`. The
registry-synced base set (see `.claude/.registry-manifest.json`) is
`milestone-researcher`, `milestone-implementer`, `milestone-adversary-critic`,
and `milestone-oss-scout`; the repo-local agents `milestone-adversary` and
`milestone-infra-safety` remain as arXMCP-specific critics (note: the synced
orchestrator discovers overlay critics via the `milestone-*-critic.md` naming
convention). The slash command is the orchestrator (main thread); sub-agents
cannot spawn sub-agents.

The state machine lives at
`.claude/notes/milestones/<ID>/state.json` and is strict-forward-only
through `init → research-running → research-complete → implement-running →
implement-complete → critique-running → critique-complete → rectify-running
→ complete`.

Trivial edits (one-liners, formatting fixes) can skip the command — but if a
change touches more than ~3 files or adds new tests, run the pipeline.

### 4.3 Commit conventions

- **Conventional commits.** Subject ≤50 chars after the type prefix.
  Types in this repo: `feat`, `rect`, `chore`, `docs`. Scopes match
  subsystems: `server`, `ingest`, `shim`, `infra`, `tests`, `skill`, `notes`,
  `repo`.
- **Three-commit-per-milestone pattern.** Every milestone produces:
  1. `feat(<scope>): <topic> (E<NN>_S<MM>)` — the implementation commit
  2. `rect(<scope>): close <N> <severity> from E<NN>_S<MM> critique` —
     adversary findings closed via the rectifier protocol
  3. `chore(notes): finalize E<NN>_S<MM> state -> complete` — state.json
     bookkeeping
- **GPG signing is enabled** (`commit.gpgsign=true`). **Never**
  `--no-gpg-sign`.
- **Co-author trailer is mandatory** on every commit:
  ```
  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  ```
- **Pre-commit hooks are honored.** **Never** `--no-verify`. If a hook
  fails, fix the underlying issue and create a NEW commit (don't `--amend`
  the failing one).
- **HEREDOC for commit messages** to survive apostrophes / special chars:
  ```bash
  git commit -F - <<'COMMIT_EOF'
  feat(scope): subject line

  Body text with 'apostrophes', "quotes", and $vars all survive.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  COMMIT_EOF
  ```

### 4.4 Push when the user asks; not before

- **Push is per-event authorization.** A user "yes, push" once does NOT
  authorize future pushes. Re-ask each time.
- **Never `git push --force` to `main`.** The system rules forbid it
  without explicit user request and there is no scenario in this project
  that requires it.

### 4.5 Test + lint discipline

- **Before any commit:** run `ruff check .` then the full `pytest` suite
  (that is what `make test` does; `make` is absent on the Windows
  workstation, so run the two commands directly). Tests must pass, ruff
  must be clean.
- **Use the repo venv's Python, not the system one:**
  ```
  .venv/Scripts/python.exe -m pytest [args]       (Windows, tier-1)
  uv run python -m pytest [args]                  (macOS/Linux)
  ```
  The system `pytest`/`python` may resolve to the wrong interpreter;
  the project requires Python ≥ 3.11.
- **Use `--tb=no -p no:warnings`** when you only care about the
  pass/fail count and want a clean terminal:
  ```bash
  uv run python -m pytest --tb=no -p no:warnings 2>&1 | grep "passed"
  ```
- **8 test markers exist** (registered in `pyproject.toml`
  `[tool.pytest.ini_options].markers`; the count and names here are
  pinned to that registry by `tests/test_claude_md_doclint.py`):
  - **`requires_model`** — tests that download / load a real ML
    model (BGE-M3, BGE-reranker-v2-m3, etc.). Skipped by default;
    opt-in via `pytest -m requires_model` AND per-model env vars
    (`ARXMCP_RUN_REAL_BGE_RERANKER=1`, etc.).
  - **`eval`** — end-to-end retrieval-quality eval against the
    curated 20-query fixture (E05_S02 / E07_S04). Tier-0 → Tier-1
    gate; skipped via cold-start matrix when fixture or corpus is
    missing.
  - **`requires_latexmlc`** — tests that invoke the real `latexmlc`
    binary (E10_S04 drift detector). Skipped by default; opt-in
    via `pytest -m requires_latexmlc`. Install: `brew install
    latexml` / `apt install latexml`.
  - **`requires_full_corpus`** — tests against a fully-ingested
    200K-paper corpus (E11_S01 sanity). Skipped by default; opt-in
    via `pytest -m requires_full_corpus` AND
    `ARXMCP_RUN_FULL_CORPUS_TESTS=1`.
  - **`requires_lean_repl`** — tests that invoke the real Lean 4
    REPL subprocess (verification-feedback-m2+). Skipped by
    default; opt-in via BOTH `ARXMCP_LAKE_PATH` and
    `ARXMCP_LEAN_REPL_DIR` env vars.
  - **`requires_pdflatex`** — tests that invoke the real
    `pdflatex` + `pdftoppm` binaries (parser-fidelity-eval-m1 CDM
    gate). Skipped by default; opt-in via `pytest -m
    requires_pdflatex` AND `ARXMCP_RUN_REAL_PDFLATEX=1`. Install:
    `brew install --cask mactex-no-gui && brew install poppler` /
    `apt install texlive-base poppler-utils`. Subprocess sandbox
    profile at `.claude/docs/security-cdm-sandbox.md` (Threat-3 peer).
  - **`requires_mineru`** — tests that invoke the real `mineru`
    binary (textbook-ingest-m5 PDF parser subprocess driver).
    Skipped by default; opt-in via `pytest -m requires_mineru` AND
    `ARXMCP_RUN_REAL_MINERU=1` AND `ARXMCP_MINERU_BIN` set to the
    binary's absolute path. Sandbox profile at
    `.claude/docs/security-pdf-sandbox.md`; the RLIMIT_AS 4 GB cap
    is Linux-only — the wall timeout is the only memory backstop
    elsewhere.
  - **`requires_restic`** — tests that invoke the real `restic`
    binary (notebook-ops-hardening-m1 backup→wipe→restore
    round-trip). Skipped by default; opt-in via `pytest -m
    requires_restic` AND `ARXMCP_RUN_RESTIC_TESTS=1`. Requires
    restic ≥ 0.16 (`brew install restic` / `apt install restic`).

### 4.6 Doc placement (re-stated; this is load-bearing)

- **Never put a Markdown file in `server/`, `ingest/`, `tests/`, `tools/`,
  `shim/`, `docker/`, or `infra/`** unless it's a navigational
  `README.md` / `CLAUDE.md` for that subdir.
- **All new agent-internal documents go under `.claude/`** — typically
  `.claude/docs/` (per-feature references), `.claude/notes/` (design
  constitution), or `.claude/notes/milestones/<ID>/` (per-milestone
  research / critique / implementation summary).
- **Don't bring back `ROADMAP.md` at the root** — the authoritative
  roadmap is `.claude/roadmap/README.md`.

### 4.7 Coding conventions

- **Constitution amendment (ADR-0001, Stage-2 D1):** Node/Vite are
  allowed as **build-time-only** tooling (SPA at `/app`). Runtime
  invariants are unamended and non-negotiable: single Python process,
  loopback-only bind, no runtime network fetches, vendored/pinned or
  lockfile-reproducible assets, stricter CSP at `/app` than `/ui/`.
  See [`docs/adr/`](docs/adr/README.md) for the full decision record
  (D1–D9 + third-repo extraction triggers).
- **`assert` is BANNED for invariants** — Python `-O` strips them. Use
  `if … raise RuntimeError(…)` instead.
- **Pure-ASGI middleware required.** `BaseHTTPMiddleware` is project-banned
  (E06_S01 F1 — it silently no-ops response interception for SSE paths).
- **No `anthropic` SDK at runtime.** The server is a tool provider; the
  LLM lives in the calling agent.
- **No-fork policy.** Nothing lifted from existing `arxiv-mcp` repos. Use
  ideas, not code.
- **`server/` source NEVER references `claude-opus`.** Model selection in
  the orchestrator is Haiku/Sonnet only.

---

## 5. Directory layout — what lives where

```
arXMCP/
├── README.md                user-facing landing page (project / how-to-use / layout)
├── CLAUDE.md                this file
├── CHANGES.md               changelog (epic-grain)
├── SECURITY.md              security reporting + threat-model pointer
├── OWNERS.md                ownership / contact
├── Makefile                 make help / bootstrap / test / eval / up / ingest
├── pyproject.toml           Python ≥3.11; per-line dep comments are agent-grade material
├── uv.lock                  uv lockfile
├── docker/
│   └── Dockerfile.server    multi-stage; non-root user; tini; HEALTHCHECK on /readyz
├── infra/
│   └── README.md            placeholder for docker-compose (E14)
├── docs/                    operator-facing ONLY (chapters indexed by docs/README.md)
│   ├── README.md            chapter index — every entry below is linked from here
│   ├── install.md           operator setup + Claude Code MCP registration
│   ├── usage.md             notebooks, ingestion, search, operator console
│   ├── api.md               MCP tool surface reference (args / returns / envelopes)
│   ├── architecture.md      retrieval + caching + citation-graph overview
│   ├── evaluation.md        retrieval-quality + parser-fidelity (CDM) gates
│   ├── support.md           troubleshooting + how to report a problem
│   ├── releasing.md         maintainer release workflow
│   ├── ops/                 runbook tree (bulk ingest, backup/restore, drift, cutover, …)
│   ├── observability/       /metrics, OTel, Phoenix, Grafana, Langfuse guides
│   ├── adr/                 Stage-2 decision records 0001–0010 (D1–D9 + extraction triggers)
│   └── security/            issue #9 scope-amendment draft (local; not posted)
├── server/                  long-running MCP server (FastAPI + Streamable HTTP)
│   ├── main.py              FastAPI app factory + lifespan
│   ├── config.py            ARXMCP_* env vars; rejects 0.0.0.0 at parse time
│   ├── tools.py             8-tool registration + envelope helpers (TOOL_SCHEMA_VERSION)
│   ├── handlers/            one file per MCP tool
│   ├── proving/             Stage-2 WS-D proving lane (orchestrator, skeptic, faithfulness gate, KAT)
│   ├── schemas/             pydantic request/response models (WS-A response typing)
│   ├── retrieval/           BM25, ANN, RRF, BGE-reranker modules (dense-only ANN is the live path; see §3 E07)
│   ├── orchestrator/        id_canon + model_selector (E08)
│   ├── observability/       Stage-2 WS-A event ring + SSE bus (requests/logs/sessions/ingest)
│   ├── spa.py               static mount serving frontend-app/dist at /app (Stage-2 D1; CSP stricter than /ui/)
│   ├── graph_queries.py     cite_neighbors library (E09_S03; the MCP handler wires to it)
│   ├── graph_types.py       CitationNeighbor dataclass
│   ├── cache.py             3-tier retrieval cache
│   ├── cache_sqlite.py      Tier-1 persistence
│   ├── middleware.py        OriginValidation, SecurityHeaders, BodySizeCap, SessionCap, Capability
│   ├── session.py           per-Mcp-Session-Id retrieval caps
│   ├── router.py            regex-based query router (4 RouteTags)
│   ├── router_patterns.yaml 18 named patterns
│   ├── prompts.py           role-prefix constants (BP1+BP2 cache breakpoints)
│   ├── corpus.py            LanceDB MVCC chunks-table reader
│   ├── health.py            /healthz + /readyz + /status (health+json; m4)
│   ├── metrics.py           Prometheus counters
│   └── routes/              HTTP route modules (operator console + JSON APIs)
│       ├── ui.py            /ui/ HTML pages: landing, /ui/notebooks/{slug} (paginated), preview, status-badge
│       ├── notebooks.py     /ui/api/* REST + htmx (create/list/rename/delete/ingest/upload)
│       ├── api_v1.py        /api/v1 JSON-only router (paginated; aliases /ui/api, HX-Request stripped)
│       ├── bridge.py        GET /bridge/contracts handshake endpoint (contract-registry advertisement)
│       ├── capabilities.py  capability-profile config surface (call-time denial; NEVER tools/list filtering — D5)
│       ├── observability.py R1–R8 observability read-APIs + the multiplexed SSE stream
│       └── debug.py         opt-in debug routes
├── frontend/                Jinja2+htmx operator-console assets for /ui/ (server-rendered; no build chain)
│   ├── templates/           Jinja2 templates (base, index, notebook_detail); autoescape ON
│   └── static/              vendored htmx.min.js + minimal CSS (mounted at /ui/static/)
├── frontend-app/            Stage-2 WS-B /app SPA (Vite + React + TS); committed dist/ served by server/spa.py
│   ├── src/                 React sources (Technical-Editorial design tokens; anime.js motion wrappers)
│   ├── dist/                committed byte-reproducible build served at /app (build-time Node/Vite; ADR-0001)
│   └── e2e/                 Playwright + axe + visual harness (incl. the AC-B.20 mandated E2E)
├── contracts/               Stage-2 WS-C bridge contracts — envelope v1 + named type schemas + CONTRACTS.md changelog
├── ops/                     ops CLIs + cron/systemd units (cutover, restic restore drill, drift check)
├── plans/                   post-epic roadmaps (plans/<slug>-roadmap.md; driven via /milestone-pipeline)
├── ingest/                  corpus pipeline (chunker → embedder → indices → graph)
│   ├── chunker.py           theorem-aware structural chunker
│   ├── preamble.py          per-paper \newcommand / \def extractor
│   ├── embedder.py          BGE-M3 dual-column embedder
│   ├── tokenizer.py         math-aware regex pre-tokenizer (for BM25)
│   ├── schema.py            LanceDB chunks-table schema (single source of truth)
│   ├── store.py             LanceDB writer with idempotent merge_insert
│   ├── identifiers.py       paper_id + chunk_id regexes + paper_id_from_chunk_id helper
│   ├── bm25_indexer.py      per-corpus-version BM25 pickle index
│   ├── kuzudb_schema.py     Kùzu schema v2 (papers + cites + _schema_meta)
│   ├── graph_ingest.py      E09_S01 — OpenAlex bulk citation ingest
│   ├── inspire_ingest.py    E09_S02 — INSPIRE-HEP enrichment (hep-th/math-ph)
│   └── intra_paper_refs.py  E09_S03 — intra-paper \ref{} chain (self-edges)
├── shim/
│   └── arxmcp_shim.py       stdio↔HTTP bridge for Claude Code; loopback-only egress
├── tools/                   dev utilities
│   ├── arxiv_fetch.py       politeness contract: User-Agent, 503 backoff, 3s sleep
│   ├── fetch_one_paper.py   single-paper smoke test of arXiv /e-print/ + LaTeXML
│   ├── fetch_seed.py        50-paper seed fetch (idempotent; ≥45/50 to pass)
│   ├── curate_seed.py       math.AG candidate pre-filter
│   ├── exploration/         Stage-2 WS-E open-problem discovery engine (pytest-importable; propose→confirm)
│   ├── validate_eval_fixtures.py  eval-fixture structural validator
│   └── seed-papers.txt      50 hand-curated math.AG arXiv IDs
├── tests/                   pytest suite (2100+ tests; exact counts drift — trust the run)
│   ├── conftest.py          autouse fixtures (path redirects, KMP_DUPLICATE_LIB_OK)
│   ├── _graph_helpers.py    shared synthetic Kùzu/LanceDB fixture builders (E09_S04)
│   ├── eval/                retrieval-quality gate (nDCG@5, Recall@10)
│   ├── retrieval/           per-phase BM25/ANN/rerank tests
│   └── fixtures/            chunker + preamble golden fixtures
├── var/                     gitignored data tree (created by `make bootstrap`)
│   └── arxmcp/              corpus/, index/, cache/, ops/
└── .claude/                 ALL agent-internal docs live here
    ├── TIER-GATES.md        machine-checkable tier-promotion gates
    ├── docs/                per-feature internal references (moved from docs/ 2026-05-10)
    │   ├── chunker-fixtures.md
    │   ├── eval-curation.md
    │   ├── model-policy.md
    │   ├── orchestrator-rules.md
    │   ├── proof-chain-workflow.md
    │   ├── retrieval-quality-report.md
    │   └── snippet-contract.md
    ├── notes/               design constitution (10 numbered notes + HANDOFF + milestones/)
    │   ├── README.md         reading-order index
    │   ├── 01..10-*.md       numbered design notes
    │   ├── prompts-bp-discipline.md   E08_S02 prompt-cache breakpoint doc
    │   ├── HANDOFF.md        in-session handoff snapshot
    │   ├── scans/            repo-wide research scans (history)
    │   └── milestones/       per-milestone state.json + research/critique artifacts
    ├── roadmap/             14 per-epic plans (E01–E14) + authoritative index
    │   ├── README.md         authoritative epic index (NOT the root)
    │   └── E<NN>-*.md        per-epic specs
    ├── agents/              bespoke sub-agent definitions
    │   ├── milestone-{researcher,implementer,adversary-critic,oss-scout}.md   (synced)
    │   ├── roadmap-{refiner,decomposer,sequencer,materializer}.md             (synced)
    │   ├── milestone-adversary.md + milestone-infra-safety.md   (repo-local critics)
    │   └── capability-scout-*.md + frontend-uplift-*.md          (repo-local pipelines)
    ├── commands/
    │   ├── milestone-pipeline.md  the 4-phase execution slash command (synced)
    │   ├── roadmap.md             the 4-phase planning slash command (synced)
    │   └── capability-scout.md + frontend-uplift.md              (repo-local)
    ├── references/          flat reference files
    │   ├── milestone-pipeline-*.md + roadmap-*.md|yaml           (synced)
    │   ├── milestone-pipeline-agent-conventions.md               (repo-local, shared)
    │   ├── roadmap-arxmcp-integration.md                         (repo-local)
    │   └── capability-scout/ + frontend-uplift/                  (repo-local pipelines)
    ├── scripts/             flat scripts
    │   ├── milestone-pipeline-*.{py,sh} + roadmap-*.py               (synced)
    │   └── capability-scout/ + frontend-uplift/                  (repo-local pipelines)
    ├── agent-memory/        per-agent project-scope memory (auto-injected by harness)
    │   └── milestone-*/      MEMORY.md per bespoke sub-agent
    └── .registry-manifest.json  hashes of registry-synced files (never edit synced copies)
```

---

## 6. Capabilities you can rely on

These all work TODAY (verified against code 2026-07-04; when in doubt,
the handler docstrings in `server/handlers/` are the source of truth):

- **Run the server:** `python -m server.main` (or `make up` where `make`
  exists) starts the MCP server on `127.0.0.1:7733` with Streamable HTTP
  at `/mcp`. On a box with no ingested corpus it **refuses to start by
  design** (`CorpusNotIngestedError`); use `ARXMCP_BOOTSTRAP_MODE=1` for
  first-run/empty-corpus operation.
- **Browser operator console** at `http://127.0.0.1:7733/ui/` — notebook
  management (list / create / ingest / rename / delete / upload + ar5iv
  preview + an operability badge); loopback-only, server-rendered
  Jinja2+htmx, no build chain. NOT yet security-audited (E13 scoped it
  out; tracked at `chris-dare-dev/arXMCP#9`; scope-amendment draft at
  `docs/security/issue-9-scope-amendment-draft.md`). See
  `06-mcp-server-design.md` § "Browser UI surface".
- **Stage-2 HTTP surfaces (all loopback-only, all shipped):**
  - **`/app`** — the richer Vite+React SPA (`frontend-app/`, committed
    `dist/` served by `server/spa.py`) under a CSP **stricter** than
    `/ui/` (`script-src 'self'`).
  - **`/api/v1`** — JSON-only router aliasing `/ui/api` (`HX-Request`
    stripped at the ASGI scope, paginated stable-ordered lists, offline
    `openapi.json`; `/openapi.json`/`/docs`/`/redoc` stay 404 at runtime).
  - **`GET /bridge/contracts`** — the cross-repo handshake endpoint
    advertising the `contracts/` registry (absent/scan/registry/malformed
    degradation); consumed by the website's `/proof-verify` preflight.
  - **Capability profiles** — `CapabilityMiddleware` does **call-time
    denial** with structured envelopes; it **never** filters `tools/list`
    (D5). Profiles live in `operator_settings`, are runtime-mutable, and
    are configured via `server/routes/capabilities.py`.
  - **Observability read-APIs** — the R1–R8 requests / logs-tail /
    sessions / ingest-events surfaces + one multiplexed SSE stream with
    drop-oldest queue caps and polling twins (`server/observability/`,
    `server/routes/observability.py`).
- **`tools/list`** returns **8 frozen tool meta records** (byte-stable for
  BP1 cache discipline; `TOOL_SCHEMA_VERSION = 18`): `search_papers`,
  `get_chunk`, `find_equation`, `get_definitions`, `find_lemma_by_name`,
  `get_paper`, `cite_neighbors`, `lean_verify`.
- **All 8 handlers are wired.** In particular:
  - **`cite_neighbors`** is wired to the live Kùzu graph via
    `server/graph_queries.py` (verification-feedback-m1, tools v10/v11) with
    `graph_status` degradation semantics: `present` / `absent` /
    `unavailable`. **Data caveat:** on the Windows workstation the Kùzu
    graph has not been ingested — calls here return `graph_status="absent"`
    with empty neighbors until `python -m ingest.graph_ingest` (etc.) runs.
  - **`lean_verify`** is env-gated: `ARXMCP_ENABLE_LEAN=1` plus
    `ARXMCP_LAKE_PATH` / `ARXMCP_LEAN_REPL_DIR`; disabled it returns the
    structured `lean_status="disabled"` envelope (the call-time-denial
    pattern — never `tools/list` filtering).
  - **`search_papers`** is dense-only ANN over `embedding_stmt`
    (`retrieval_mode: "dense_only"`) with **real** `filters` support:
    `paper_id` (str or list), `source_kind`, and per-notebook routing.
- **3-tier retrieval cache** with Prometheus metrics at `/metrics`.
- **Per-session retrieval caps** via `Mcp-Session-Id` header.
- **Citation graph ingest CLIs** — `python -m ingest.graph_ingest`
  (OpenAlex), `python -m ingest.inspire_ingest` (INSPIRE-HEP),
  `python -m ingest.intra_paper_refs` (intra-paper `\ref{}`).
- **Bulk ingest** — `make ingest ARGS=...` / `python -m ingest.bulk_ingest`
  is the real E11 orchestrator (per-paper ar5iv → LaTeXML → chunk → embed →
  staging LanceDB), plus the OAI-PMH delta loop and re-embed drivers.
- **Textbook ingest** — MinerU PDF path + markdown-native chunker
  (`--chunker markdown`), per-notebook isolation.
- **Seed-corpus fetch** — `python tools/fetch_seed.py` walks
  `tools/seed-papers.txt` against arXiv's `/e-print/` + LaTeXML.

---

## 7. Known deferrals / degraded modes

Things that LOOK shipped but are deferred, degraded, or data-dependent —
verified against code 2026-07-04 (each bullet cites its source of truth):

- **`get_chunk`'s `include_referenced` + `include_equations`** are accepted
  but ignored (`include_*_applied: false` in the response; reserved for
  E07_S03 reranker output + equation atoms — `server/handlers/chunk.py`).
- **`find_equation` LaTeX input** takes the dense-only fallback
  (`retrieval_mode="dense_only_stmt_fallback"`): there is no query-time
  LaTeX→MathML parse path. MathML input gets the real TED+dense fusion
  (`ted_fused`), degrading to `dense_only_fallback` when the equations
  table is missing/unindexed (`server/handlers/equation.py`).
- **`get_paper` is WIRED to the per-notebook metadata store**
  (paper-metadata-m1 store + m2-equivalent wiring, reconciled at the
  Stage-2/3 integration). When a paper's per-notebook
  `var/arxmcp/notebooks/<slug>/paper_metadata.db`
  (`server/paper_metadata_store.py`, hydrated by
  `tools/notebook_metadata_backfill.py` from the arXiv Atom API) holds a
  row, `get_paper` returns the real `title`/`authors`/`abstract`/`year`/
  `categories` (+`primary_category`/`published`) with
  `metadata_status="notebook_metadata_store"`; the handler resolves WHICH
  notebook by enumerating on-disk notebooks and reading the first store
  with a matching row. When no store/row exists (e.g. the metadata has
  not been backfilled, or no notebook is ingested on this workstation) it
  falls back to the historical synthesized-from-chunks envelope with
  `metadata_status="synthesized_from_chunks"` and NULL identity fields
  (`server/handlers/paper.py`). Note: the `get_paper` ToolMeta
  *description* in `server/tools.py` still reads "…null until a real
  papers metadata table lands" — that string is frozen for BP1
  prompt-cache byte-stability and is deliberately NOT edited here; the
  handler behavior above is the ground truth (§3 trust-discipline: the
  code wins).
- **`cite_neighbors` on this workstation** returns `graph_status="absent"`
  until the Kùzu graph is ingested here (handler is wired; the data isn't
  present — see §6).
- **`embedding_eq` on the `chunks` table** is reserved and always NULL
  (`ingest/schema.py`); the separate `equations` table's `embedding_eq` is
  populated by `python -m ingest.embed_equations`.
- **Retrieval-quality eval gate** has the harness shipped (`make eval`)
  but the curated 20-query fixture (`tests/eval/fixtures/queries.json`)
  is still empty — hand-labeling is owner-led per
  [`.claude/docs/eval-curation.md`](.claude/docs/eval-curation.md).
- **Hybrid retrieval** is modules-without-wiring behind a closed NO
  verdict — see §3 E07. Not a deferral to schedule; an evidence gate.
- **`SYSTEM_PROMPT`** in `server/prompts.py` is still a byte-stable
  placeholder (see §8 gotcha 6).
- **Windows platform limits** (tier-1 host): `RLIMIT_AS` memory caps are
  POSIX-only (WARN + wall-timeout backstop here), the LaTeXML
  sandbox layers (`sandbox-exec`/`bwrap`) take the documented degraded
  path, and `ops/*.sh` cron scripts target macOS/Linux. See
  [`.claude/notes/windows-test-triage.md`](.claude/notes/windows-test-triage.md).

---

## 8. Gotchas — landmines learned across E01-E09

1. **macOS pytest segfault with `faiss-cpu` + PyTorch.** The
   `KMP_DUPLICATE_LIB_OK=TRUE` workaround in `tests/conftest.py` is
   required for the full `pytest` run to not SIGSEGV. Cleared at session
   end if `conftest.py` set it. Production Linux containers don't need it.

2. **Kùzu was archived 2025-10-10.** We pin `kuzu==0.11.3` exactly (the
   last stable, MIT). Future fork migration (`Kineviz/bighorn` or
   `Vela-Engineering/kuzu`) is tracked but out of scope.

3. **OpenAlex Concept IDs in epic prose are wrong/deprecated.** The brief
   for E09_S01 specified `C66938386` / `C15736585` (Structural engineering
   + 404 respectively). Live-verified correct IDs are `C68363185` and
   `C169654258`, but Concepts are deprecated in favor of Topics anyway.
   The seed-corpus path uses arXiv-URL-as-identifier resolution; the
   `--category` flag in `ingest/graph_ingest.py` raises
   `NotImplementedError`.

4. **`var/arxmcp/index/kuzu/` vs `var/arxmcp/index/kuzudb/`.** Three epic
   briefs (E09_S01, E09_S03, E09_S04) use `kuzudb/`; the design notes +
   Makefile bootstrap use `kuzu/`. We ship `kuzu/`. The brief wording is
   documented drift.

5. **Tool-use ID canonicalization MUST run over the FULL accumulated
   history each turn.** Pass only the new-turn slice and you get
   collisions across transitions. Contract pinned by tests; see
   [`.claude/docs/orchestrator-rules.md`](.claude/docs/orchestrator-rules.md).

6. **`SYSTEM_PROMPT` in `server/prompts.py` is still a placeholder.**
   The role prefixes are real; the global system prompt isn't yet
   authored. When it lands, `EXPECTED_BP1_SHA256` in
   `tests/test_prompts.py` must be re-pinned.

7. **HEREDOC commits.** Bash mangles `$(cat <<'EOF' … EOF)` form when
   the commit body contains apostrophes (`don't`, `won't`). Use
   `git commit -F - <<'COMMIT_EOF' … COMMIT_EOF` (stdin form).

8. **Wrong-interpreter pytest.** A bare `pytest` may resolve to another
   Python; the project requires 3.11+. On Windows (tier-1) use
   `.venv/Scripts/python.exe -m pytest`; on macOS/Linux use
   `uv run python -m pytest`.

9. **`resource.setrlimit(RLIMIT_AS, ...)` is non-functional on macOS.**
   Verified live test on Darwin 25.4.0 / Apple M4 Max
   (textbook-ingest-m5 research-brief-2): the Darwin kernel keeps the
   hard limit at `RLIM_INFINITY` and refuses lowering at the process
   level — `setrlimit(RLIMIT_AS, (4GB, 4GB))` raises `ValueError:
   current limit exceeds maximum limit`. Any subprocess sandbox that
   uses `preexec_fn=_set_rlimits` on Darwin will crash the child with
   a Python traceback in stderr BEFORE exec. The m5 driver
   (`ingest/textbook_parser.py`) gates the preexec_fn on
   `sys.platform == "linux"` and emits a WARN log on other platforms;
   the 30-min wall timeout is the only memory backstop on macOS.
   `server/lean_repl.py` has the same broken-on-Darwin guard
   (`sys.platform != "win32"`) — separate follow-up issue at
   `chris-dare-dev/arXMCP`.

10. **MinerU 3.x grandchild FastAPI server survives `os.killpg`.**
    MinerU 3.x CLI spawns an internal `LocalAPIServer`
    (FastAPI/uvicorn) with its own `start_new_session=True` (confirmed
    at `mineru/cli/api_client.py:153`), creating a grandchild in a
    different process group. `os.killpg` on the outer CLI's pgid does
    NOT reap the grandchild. The gap is accepted (loopback-only, no
    external network); see
    [`.claude/docs/security-pdf-sandbox.md`](.claude/docs/security-pdf-sandbox.md)
    §"explicitly does NOT do".

11. **Doc-layout consolidation (2026-05-10).** TIER-GATES, all of `docs/*`
    except `install.md`, and `server/prompts.md` moved into `.claude/`.
   The README is now project-scope-only. Tests that hard-pin doc paths
   were updated in lockstep. Don't reintroduce Markdown into `server/`,
   `ingest/`, etc.

---

## 9. Common tasks for new agents

### Run a milestone end-to-end

```bash
/milestone-pipeline E10_S01
```

The slash command (`.claude/commands/milestone-pipeline.md`) resolves the
brief via `.claude/scripts/milestone-pipeline-resolve-brief.py` (canonical:
`plans/<slug>/roadmap.yaml`; legacy prose fallback: `plans/*.md` and
`.claude/roadmap/*.md`), dispatches Phase-1 researcher agents in parallel,
drives Phase-2 implementation inline or via the `milestone-implementer`
agent, Phase-3 critique via parallel critic agents
(`milestone-adversary-critic` always, plus overlays and the opt-in
`milestone-oss-scout`), and Phase-4 rectification in the main session.
Emits a `feat(...)` + `rect(...)` + `chore(...)` commit triple.

### Check status of an in-flight milestone

```bash
bash .claude/scripts/milestone-pipeline-status.sh E10_S01
```

### Verify the full project is green

```
# Windows (tier-1 workstation; make is absent — run the two steps directly):
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m pytest --tb=no

# macOS/Linux:
make test                                                    # ruff + pytest
```

### Start the MCP server (local dev)

```
python -m server.main          # or `make up` where make exists
```

On a box whose corpus is not yet ingested, startup refuses by design
(`CorpusNotIngestedError`) — set `ARXMCP_BOOTSTRAP_MODE=1` for
first-run operation.

The server REJECTS `ARXMCP_CONTACT_EMAIL` (it's an ingest-tool var, not
a server config knob — `tools/notebook_fetch.py`,
`tools/recover_preambles.py`, `ingest/inspire_ingest.py` consume it for
the arXiv polite-pool User-Agent). Unset it for `make up` and only
export it in shells where you're running an ingest CLI.

Health: `curl http://127.0.0.1:7733/healthz` (always 200),
`curl http://127.0.0.1:7733/readyz` (200 once BGE-M3 + LanceDB warm).

### Add a new tool to the MCP surface

1. Write the handler in `server/handlers/<tool>.py`.
2. Add a `ToolMeta` to `ALL_TOOLS` in `server/tools.py`.
3. Wire the handler in `register_all(...)`.
4. **Re-pin `EXPECTED_TOOL_SCHEMA_SHA256`** in
   `tests/test_server_tool_schema.py` — the `tools/list` response must
   stay byte-stable for BP1 prompt-cache discipline. Use
   `pytest --update-tool-schema-hash` to regenerate.
5. Add tests under `tests/test_handlers_<tool>.py`.
6. Update [`.claude/docs/snippet-contract.md`](.claude/docs/snippet-contract.md)
   if the new tool returns a result row with snippet semantics.

---

## 10. Where to look first when something breaks

| Symptom | First file to read |
|---|---|
| Tests segfault on macOS | `tests/conftest.py` (KMP_DUPLICATE_LIB_OK) |
| MCP server refuses to bind | `server/config.py::reject_non_loopback` |
| `tools/list` hash drift | `tests/test_server_tool_schema.py` + `server/tools.py::ALL_TOOLS` |
| Prompt cache miss between agent roles | `server/prompts.py` (BP1/BP2) + `server/orchestrator/id_canon.py` |
| Retrieval results stale | `server/cache.py` corpus-version key |
| Citation graph query empty | `graph_status` in the `cite_neighbors` envelope: `absent` = Kùzu graph not ingested on this machine (`python -m ingest.graph_ingest`); `unavailable` = open/query failure. Handler `server/handlers/citations.py` is wired to `server/graph_queries.py` |
| `make eval` skipped | `tests/eval/fixtures/queries.json` still has zero curated queries (owner-led — see §7) |
| Windows-only test skip/failure | [`.claude/notes/windows-test-triage.md`](.claude/notes/windows-test-triage.md) + `tests/_platform_helpers.py` |

---

## 11. Quick links to the design constitution

The `.claude/notes/` files are the **why** (architectural rationale);
`.claude/roadmap/` files are the **how** (epic-level plans);
`.claude/docs/` files are per-feature internal references. When a design
question arises, quote the note by filename — don't paraphrase.

- [`.claude/notes/README.md`](.claude/notes/README.md) — reading order
- [`.claude/notes/01-mission-and-context.md`](.claude/notes/01-mission-and-context.md) — Why arXMCP exists
- [`.claude/notes/02-architecture-overview.md`](.claude/notes/02-architecture-overview.md) — System shape
- [`.claude/notes/03-ingestion-pipeline.md`](.claude/notes/03-ingestion-pipeline.md) — arXiv → LaTeXML → chunker → embedder → LanceDB
- [`.claude/notes/04-parsing-and-chunking.md`](.claude/notes/04-parsing-and-chunking.md) — Chunk discipline
- [`.claude/notes/05-storage-and-indexing.md`](.claude/notes/05-storage-and-indexing.md) — LanceDB + Kùzu schemas
- [`.claude/notes/06-mcp-server-design.md`](.claude/notes/06-mcp-server-design.md) — Server design
- [`.claude/notes/07-multi-agent-caching.md`](.claude/notes/07-multi-agent-caching.md) — **THE cache discipline note**
- [`.claude/notes/08-security-observability-ops.md`](.claude/notes/08-security-observability-ops.md) — Threat model + ops
- [`.claude/notes/10-references-and-prior-art.md`](.claude/notes/10-references-and-prior-art.md) — Bibliography
- [`.claude/notes/prompts-bp-discipline.md`](.claude/notes/prompts-bp-discipline.md) — BP1/BP2 breakpoint placement (E08_S02)
- [`.claude/roadmap/README.md`](.claude/roadmap/README.md) — Authoritative epic index
- [`.claude/commands/milestone-pipeline.md`](.claude/commands/milestone-pipeline.md) — 4-phase pipeline slash command (orchestrator)
- [`.claude/references/milestone-pipeline-agent-conventions.md`](.claude/references/milestone-pipeline-agent-conventions.md) — shared sub-agent conventions (repo-local; prompts live in `.claude/agents/*.md`)
- [`.claude/references/milestone-pipeline-state-schema.md`](.claude/references/milestone-pipeline-state-schema.md) — state.json schema + transitions
- [`.claude/TIER-GATES.md`](.claude/TIER-GATES.md) — Tier-promotion machine-checkable gates
- [`.claude/docs/orchestrator-rules.md`](.claude/docs/orchestrator-rules.md) — Tool-use ID canonicalization + per-session caps
- [`.claude/docs/model-policy.md`](.claude/docs/model-policy.md) — `(RouteTag, TurnType) → model` table
- [`.claude/docs/proof-chain-workflow.md`](.claude/docs/proof-chain-workflow.md) — 2-round proof-chain pattern
- [`.claude/docs/snippet-contract.md`](.claude/docs/snippet-contract.md) — 150-char snippet contract
- [`.claude/docs/chunker-fixtures.md`](.claude/docs/chunker-fixtures.md) — Chunker fixture regeneration runbook
- [`.claude/docs/eval-curation.md`](.claude/docs/eval-curation.md) — Eval-fixture hand-labeling runbook
- [`.claude/docs/retrieval-quality-report.md`](.claude/docs/retrieval-quality-report.md) — nDCG@5 report (PRELIMINARY)

Note: `.claude/notes/09-feature-priorities.md` is **SUPERSEDED** by
[`.claude/roadmap/README.md`](.claude/roadmap/README.md).

---

## 12. The user

- The primary user is `chris.dare@nalej.com`. See [`OWNERS.md`](OWNERS.md).
- They invoke milestones with `/milestone-pipeline E<NN>_S<MM>`.
- They expect **autonomous execution** (auto-mode) and **minimal
  interruption** — make reasonable assumptions and proceed.
- They expect **rigorous adherence to the 4-phase pipeline.** Skipping
  phases or short-circuiting the rectifier protocol is unwelcome.
- They appreciate **concise end-of-milestone summaries** with key changes,
  test count delta, and adversary-critic invalidation rate.

---

**End of CLAUDE.md.** Re-read this file at the start of every new session
in this repo.
