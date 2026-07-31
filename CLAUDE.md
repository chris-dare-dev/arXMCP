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
| **`docs/`** | ONLY user-facing documentation referenced by the root `README.md` — the README's "chapters": `install.md`, `usage.md`, `api.md`, `architecture.md`, `evaluation.md`, `support.md`, `releasing.md`, plus the `docs/ops/` and `docs/observability/` runbook trees. |
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
shares one substrate of grounded context through this server. Alongside the
MCP tool surface (the primary agent interface), a **loopback-only Jinja2+htmx
operator console** at `/ui/` ships with the server for notebook management
(create / list / ingest / rename / delete / upload); it is deliberately
minimal and build-chain-free (no SPA, no Node/npm). See
[`.claude/notes/06-mcp-server-design.md`](.claude/notes/06-mcp-server-design.md)
§ "Browser UI surface".

The full design rationale lives in
[`.claude/notes/01-mission-and-context.md`](.claude/notes/01-mission-and-context.md).
The "Lean kernel is the better critic" framing in that note is load-bearing
across every architectural decision: the valuable LLM roles live **upstream**
of verification, so we invest aggressively in retrieval and pre-loading rather
than in adversarial LLM critique of math content.

Target arXiv categories: `math.AG`, `math.NT`, `math-ph`, `hep-th`.

---

## 3. Status snapshot (2026-05-20)

| Epic | Status | What landed |
|---|---|---|
| E01 — Vertical slice | ✅ SHIPPED | 50-paper math.AG seed corpus fetched + parsed |
| E02 — Chunker | ✅ SHIPPED | Theorem-aware structural chunker, preamble extractor, regex tokenizer |
| E03 — Embedder | ✅ SHIPPED | BGE-M3 dual-column encoder (`embedding_stmt` + `embedding_proof`), singleflight |
| E04 — Vector store | ✅ SHIPPED | LanceDB `chunks` table with MVCC, BM25 index, corpus_version marker |
| E05 — Eval harness | ✅ SHIPPED | nDCG@5 / Recall@10 test, 20-query fixture (curation pending) |
| E06 — MCP server | ✅ SHIPPED | FastAPI + Streamable HTTP, 7-tool surface (**8 today** — `lean_verify` landed later; §6 is current state, this column is what the epic itself landed), stdio shim, snippet contract |
| E07 — Hybrid retrieval | ✅ SHIPPED | BM25 → ANN+RRF → BGE-reranker pipeline modules |
| E08 — Agent runtime | ✅ SHIPPED | Regex router, role prefixes, 3-tier retrieval cache, tool-use ID canonicalization, model policy |
| E09 — Citation graph | ✅ SHIPPED | Kùzu schema, OpenAlex ingest, INSPIRE-HEP enrichment, `cite_neighbors`, proof-chain workflow (closes H7) |
| E10 — Specialized indices | ✅ SHIPPED | Definitions index + `get_definitions`, FTS5 theorem-name index + `find_lemma_by_name`, TED equation index + dense fusion, LaTeXML drift detector |
| E11 — Scale cutover | ✅ SHIPPED | Bulk ingest orchestrator (`make ingest`), OAI-PMH delta loop, partial re-embed driver, drift watchdog, atomic cutover + restic backup |
| E12 — Full corpus | 🚫 SCOPED OUT | Folded into E11 |
| E13 — Security audit | ✅ SHIPPED | 10 milestones (Threats 1–7 + logging redaction + bind regression + cumulative coverage doc); 6 follow-up issues filed at `chris-dare-dev/arXMCP#1`–`#6` |
| E14 — Observability/ops | ✅ SHIPPED (S01–S05) | `/metrics` endpoint, OTel tracing, Phoenix integration, daily ops cadence + parser-failures roll-up, restic backup + restore drill. S06 + S09–S12 (Tier-5/6+ follow-ups) remain unstarted |

**Test count (Windows 11, 2026-07-14):** 4066 passing, 92 skipped, 1 xfailed,
**0 failing**; `pytest` exit 0, `ruff check .` clean. Verified against a
**pristine `git worktree` checkout of the pushed commit** (`6535810`),
isolated from this box's dirty tree — the `.claude/`-only commits pushed since
(origin tip `f8a2eaf`) don't touch the test/lint path. A **data-populated**
box reports 4068 passing / 91 skipped instead: two data-precondition tests
skip without the gitignored `var/` corpus tree and pass once it's hydrated —
both configurations are **0 failing**.

> **Staleness correction (2026-07-14):** the line here previously asserted
> **0 failing as of 2026-07-12**, but `main` was in fact RED from 2026-07-12
> until 2026-07-14. Two overlapping regressions the hand-maintained snapshot
> missed: **(a)** three `source-truth-m5` tool-schema-version echo failures,
> since fixed by `license-serving-removal-m1`; and **(b)** two
> `test_textbook_chunker.py` golden-fixture tests
> (`TestGoldenFixture` + `TestTheoremRemarkProofPairingAudit`) that drifted
> when `source-truth-m2` (`2572f2f`) added the `printed_number`
> chunks-schema-v2 column to `ChunkRecord.to_dict()` but left the committed
> textbook fixtures un-regenerated — fixed in `cd90ce6` by regenerating them
> per [`.claude/docs/textbook-chunker-fixtures.md`](.claude/docs/textbook-chunker-fixtures.md).
> Treat this block as a **hand-maintained snapshot, not a live gate**: it
> goes stale whenever a milestone changes output without updating it here, so
> re-run `make test` before trusting it.

The Windows-platform failures this box used to show (≈56, up from the stale
29-failure snapshot as the suite grew) were driven to zero during the
**2026-07-12 win32-portability push**: **30 FIXED**, **18 GUARDED**, and
**8 RESOLVED** (the kuzu re-open tests — see below). FIXED = test-only portability bugs (path-separator assertions normalized via `.as_posix()` / `replace("\\","/")`, missing `encoding="utf-8"` on `.tex`/`.py`/JSON reads, a `newline=""` staging write so the byte-`source_hash` is stable, a `repr()` fix for a Windows path embedded in a `python -c` string, a deterministic fake clock for a coarse-`time.monotonic()` budget test, colon-free eval-report fixture filenames) **plus one real bug in `server/routes/ui.py`** (the preview path-containment check used a hard-coded `/` separator and 404'd every valid path on Windows — replaced with `Path.is_relative_to`). GUARDED = `sys.platform == "win32"`-scoped `skipif` where the OS capability is genuinely absent: symlink creation (9), POSIX bash-script subprocess (5), `os.replace`-under-concurrency (1), control-char filename (1); plus 2 data-precondition skips (local curated notebooks mid-curation — a data state, NOT a portability issue). Every win32 skip still RUNS on macOS/Linux, preserving the §4.1 POSIX authority. RESOLVED = the 8 kuzu 0.11.3 mandatory-lock DB re-open tests, unguarded on 2026-07-12 by moving the production ingest lifecycle off `del db` to explicit `conn.close(); db.close()` (connection before database, nested so `db.close()` always runs) in milestone `adhoc-20260712-955c958`; they now run and pass on Windows. Residual `del db` sites remain at `server/graph_queries.py::cite_neighbors`, `ingest/intra_paper_refs.py::ingest`, and `ops/restore_drill_check.py` (tracked fast-follow — the identical Windows lock bug on those paths).

For per-milestone ground truth, see
[`.claude/notes/milestones/<EXX_SYY>/state.json`](.claude/notes/milestones/).
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
`milestone-oss-scout`, `milestone-rectifier`, and `milestone-frontend-ux`. The
repo-local overlay critics are `milestone-arxmcp-critic` (the 8 arXMCP axes —
renamed from `milestone-adversary`, which the orchestrator could no longer see)
and `milestone-infra-safety-critic`. Both are discovered via the
`milestone-*-critic.md` naming convention, so their filenames MUST keep that
suffix. Overlay critics run **alongside** the always-on
`milestone-adversary-critic`, never instead of it. The slash command is the
orchestrator (main thread); sub-agents cannot spawn sub-agents.

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
- **Co-author trailer naming the actual authoring model is mandatory** on
  every commit:
  ```
  Co-Authored-By: <authoring Claude model> <noreply@anthropic.com>
  ```
- **Pre-commit hooks are honored.** **Never** `--no-verify`. If a hook
  fails, fix the underlying issue and create a NEW commit (don't `--amend`
  the failing one).
- **HEREDOC for commit messages** to survive apostrophes / special chars:
  ```bash
  git commit -F - <<'COMMIT_EOF'
  feat(scope): subject line

  Body text with 'apostrophes', "quotes", and $vars all survive.

  Co-Authored-By: <authoring Claude model> <noreply@anthropic.com>
  COMMIT_EOF
  ```

### 4.4 Push when the user asks; not before

- **Push is per-event authorization.** A user "yes, push" once does NOT
  authorize future pushes. Re-ask each time.
- **Never `git push --force` to `main`.** The system rules forbid it
  without explicit user request and there is no scenario in this project
  that requires it.

### 4.5 Test + lint discipline

- **Before any commit:** `make test` (runs `ruff check .` then `pytest`).
  1311+ tests must pass, ruff must be clean.
- **Pytest in this project uses `uv`:**
  ```bash
  /Users/chris.dare/Library/Python/3.9/bin/uv run python -m pytest [args]
  ```
  The system `pytest` may pick up the wrong Python (3.9 vs the project's
  3.12). Use `uv run` to be safe.
- **Use `--tb=no -p no:warnings`** when you only care about the
  pass/fail count and want a clean terminal:
  ```bash
  uv run python -m pytest --tb=no -p no:warnings 2>&1 | grep "passed"
  ```
- **Six test markers exist** (registered in `pyproject.toml`
  `[tool.pytest.ini_options].markers`):
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

### 4.8 Data-plane boundary — hard constraints (binding)

arXMCP is a read-only proof-discovery data plane. Constitution:
[`adr-data-plane-boundary.md`](.claude/docs/adr-data-plane-boundary.md)
(data-plane-governance-m1, Accepted 2026-07-12). Scope: the served process,
the `server/` package, and the shipped distribution. These bind every agent
session in this repo:

1. **The server never runs agents.** No agent dispatch, no agent loop, no
   per-run agent memory (run state, transcripts, model conversation state)
   server-side. The `anthropic` SDK stays out of `server/` imports and out of
   `pyproject.toml` runtime deps (§4.7's SDK ban is one mechanism of this
   rule; guard test for the import half: `tests/test_langfuse_doc.py` — the
   pyproject half is convention-only, enforcement tooling deferred per the
   ADR). Observability labeling of a *calling* agent's role and per-session
   budget counters are not agent memory.
2. **Writes enter only via offline ingest CLIs or operator-gated `/ui/`
   console actions.** The MCP tool surface stays read-only over corpus state
   (`lean_verify` computes; it never persists corpus-visible state).
   Server-internal operational writes (retrieval-cache SQLite, logs, metrics,
   ingest-status transitions) are implementation detail, not corpus writes.
   Any future agent-suggested write path terminates in an operator-confirm
   step.
3. **The orchestrator dispatch loop lives in a separate repository** — never
   under this repo. No `server/` module imports the loop; the loop holds no
   state the server reads. `server/orchestrator/` stays in place as an
   SDK-free policy/canonicalization library (its real consumer set — including
   the `spend_constants.py` runtime import — is recorded in the ADR).

Non-commercially-licensed external data enters only a candidate layer — never
redistributed, never promoted to served evidence without a recorded
per-source license check (ADR Decision 4; adapter mechanics are the
R7 track's).

### 4.9 Trust language and evidence ledger (binding)

Trust is multi-axis; abstention is a success; novelty claims are dated censuses.
Constitution: [`trust-language-policy.md`](.claude/docs/trust-language-policy.md) and
[`evidence-ledger-standard.md`](.claude/docs/evidence-ledger-standard.md)
(data-plane-governance-m3, Accepted 2026-07-12). Scope: rule 1 binds the MCP tool surface;
rule 3 binds every arXMCP planning/analysis document. These bind every agent session:

1. **No bare "verified".** No tool response carries a single "verified"-style status that
   collapses distinct trust questions into one token. Trust is a multi-axis record (an ordinal
   level + attached evidence per axis); **no axis is inferred from another** — fidelity is
   never inferred from elaboration. New trust-bearing fields are namespaced and axis-specific,
   never a new bare `status`.
   **The founding case is now closed** (issues #205 / #281 / #332): `lean_verify`'s
   `status:"ok"` ⇔ no-errors ∧ no-sorry — which a bare `axiom h : False` passed — is joined by
   an independent `axiom_audit` axis populated from `#print axioms` over the declarations the
   snippet introduces (`server/handlers/lean_verify.py`, "Axiom-hygiene axis"). Read that
   closure as the worked example of this rule, not as the rule retiring: `status` and
   `compilation_success` were deliberately left reporting exactly what they measure
   (elaboration, kernel acceptance), because forcing them to "error" on an axiom finding would
   be the same conflation pointing the other way. Two axes the policy names are still
   **unmeasured and therefore absent** from that tool's record rather than defaulted to
   passing — formal alignment (does the declaration state the theorem you meant) and checker
   identity (which checker, in which named environment). The wire-level half of the fix — the
   `LEAN_VERIFY.description` edit and the `TOOL_SCHEMA_VERSION` bump — is staged in
   [`w1-schema-deltas.md`](.claude/docs/w1-schema-deltas.md) for the next batched re-pin, so
   until that lands the tool DESCRIPTION does not yet mention `axiom_audit` (§7's "don't trust
   a tool description over §6 and this section" applies).
2. **Abstention is a first-class, tested success state.** Every tool must be able to return the
   epistemic outcomes `unknown` / `ambiguous` / `not-in-corpus` / `unsupported-by-provider`,
   kept **distinct** from operational status (`timeout` / `unavailable` / `disabled` /
   `invalid-input`) and from a partial result (answered, one axis low — e.g. `get_paper`'s
   `metadata_status="synthesized_from_chunks"`). A degraded-but-answered result is not
   abstention; "no answer" and "weaker answer" never share a token.
3. **Novelty claims are dated, scoped censuses.** No categorical "no system does X" in any
   arXMCP document; every external absence claim carries a census (named set + queries run +
   date + verdict) per the evidence-ledger standard. Internal codebase facts are cited at
   `file:line` instead; positive prior-art gets only a freshness date.

Enforcement is by-reference discipline (no CI linter or schema validator this track); the
consuming tracks (R3 Lean surface, R5 registry) implement and gate on the policy.

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
├── docs/                    operator-facing ONLY
│   └── install.md           operator setup + Claude Code MCP registration
├── server/                  long-running MCP server (FastAPI + Streamable HTTP)
│   ├── main.py              FastAPI app factory + lifespan
│   ├── config.py            ARXMCP_* env vars; rejects 0.0.0.0 at parse time
│   ├── tools.py             7-tool registration + envelope helpers
│   ├── handlers/            one file per MCP tool
│   ├── retrieval/           BM25, ANN, RRF, BGE-reranker phases
│   ├── orchestrator/        id_canon + model_selector (E08)
│   ├── graph_queries.py     cite_neighbors library (E09_S03; not yet wired to MCP tool)
│   ├── graph_types.py       CitationNeighbor dataclass
│   ├── cache.py             3-tier retrieval cache
│   ├── cache_sqlite.py      Tier-1 persistence
│   ├── middleware.py        OriginValidation, SecurityHeaders, BodySizeCap, SessionCap
│   ├── session.py           per-Mcp-Session-Id retrieval caps
│   ├── router.py            regex-based query router (4 RouteTags)
│   ├── router_patterns.yaml 18 named patterns
│   ├── prompts.py           role-prefix constants (BP1+BP2 cache breakpoints)
│   ├── corpus.py            LanceDB MVCC chunks-table reader
│   ├── health.py            /healthz + /readyz + /status (health+json; m4)
│   ├── metrics.py           Prometheus counters
│   └── routes/              loopback-only browser operator console (Jinja2+htmx)
│       ├── ui.py            HTML pages: /ui/, /ui/notebooks/{slug}, preview, /ui/status-badge
│       └── notebooks.py     /ui/api/* REST + htmx (create/list/rename/delete/ingest/upload)
├── frontend/                operator-console assets (NO SPA / NO Node build chain)
│   ├── templates/           Jinja2 templates (base, index, notebook_detail); autoescape ON
│   └── static/              vendored htmx.min.js + minimal CSS (mounted at /ui/static/)
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
│   ├── validate_eval_fixtures.py  eval-fixture structural validator
│   └── seed-papers.txt      50 hand-curated math.AG arXiv IDs
├── tests/                   1311 pytest tests + 4 skipped (requires_model)
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
    │   ├── milestone-{rectifier,frontend-ux}.md                               (synced)
    │   ├── roadmap-{refiner,decomposer,sequencer,materializer}.md             (synced)
    │   ├── milestone-{arxmcp,infra-safety}-critic.md      (repo-local overlay critics)
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
    │   ├── milestone-pipeline-*.{py,sh} + roadmap-*.py + sync-repos.py  (synced)
    │   └── capability-scout/ + frontend-uplift/                  (repo-local pipelines)
    ├── agent-memory/        per-agent project-scope memory (auto-injected by harness)
    │   └── milestone-*/      MEMORY.md per bespoke sub-agent
    └── .registry-manifest.json  hashes of claude-registry-synced files (never edit synced copies)
```

---

## 6. Capabilities you can rely on

These all work TODAY (no stubs):

- **Run the server:** `make up` (or `python -m server.main`) starts the MCP
  server on `127.0.0.1:7733` with Streamable HTTP at `/mcp`.
- **Browser operator console** at `http://127.0.0.1:7733/ui/` — notebook
  management (list / create / ingest / rename / delete / upload + ar5iv
  preview + an operability badge); loopback-only, server-rendered Jinja2+htmx,
  NO SPA / Node build chain. NOT yet security-audited (E13 scoped it out;
  tracked at `chris-dare-dev/arXMCP#9`). See `06-mcp-server-design.md`
  § "Browser UI surface".
- **`tools/list`** returns 8 frozen tool meta records (byte-stable for BP1
  cache discipline).
- **All 8 MCP tools are wired handlers** (re-verified at `9227be0`,
  2026-07-24) — `search_papers`, `get_chunk`, `find_equation`,
  `get_definitions`, `find_lemma_by_name`, `get_paper`, `cite_neighbors`,
  `lean_verify`. **No handler is a stub.** Individual *arguments* are
  still deferred — see §7.
- **`cite_neighbors`** is live at the MCP boundary
  (verification-feedback-m1, `server/handlers/citations.py`) over the
  `server/graph_queries.py` library. Kùzu + LanceDB paths come from
  `Config`, never from agent-supplied JSON — this closes the E09_S03 F2
  path-validation contract. `graph_status` reports `present` / `absent` /
  `unavailable` and returns an empty `neighbors` list rather than a 5xx
  when the graph is missing or unqueryable. Results are deliberately NOT
  cached, so a graph re-ingest can never serve a stale neighbor list. The
  library stays directly callable for proof-chain workflows (see
  [`.claude/docs/proof-chain-workflow.md`](.claude/docs/proof-chain-workflow.md)).
- **`get_chunk(include_referenced=True)`** returns the statement ↔ proof
  counterpart via `server/proof_linkage.py` (retrieval-unlocks-m1), joined
  on `(paper_id, theorem_label, kind)` with a uniqueness-gated
  section-scope fallback. `linkage.outcome` carries one of four epistemic
  results — `resolved` / `not-in-corpus` / `ambiguous` /
  `unsupported-by-provider` — never a silently empty list (§4.9).
- **`search_papers(filters=…)`** honors `paper_id` (str or list, ≤100
  items, each format-validated) and `source_kind` (`arxiv` / `textbook`)
  as ANDed LanceDB `.where(…, prefilter=True)` predicates, plus two
  *routing* keys: `notebook` (selects the per-notebook corpus) and
  `include_kinds: ["proof"]` (retrieval-unlocks-m2 — routes the ANN onto
  the `embedding_proof` column, reported as
  `retrieval_mode="dense_only_proof_column"`). Routing keys ride the cache
  key but never appear in `filters_applied` or `filter_warnings`.
- **3-tier retrieval cache** with Prometheus metrics at `/metrics`.
- **Per-session retrieval caps** via `Mcp-Session-Id` header.
- **Citation graph ingest** — `python -m ingest.graph_ingest` (OpenAlex),
  `python -m ingest.inspire_ingest` (INSPIRE-HEP),
  `python -m ingest.intra_paper_refs` (intra-paper `\ref{}`).
- **Seed-corpus fetch** — `python tools/fetch_seed.py` walks
  `tools/seed-papers.txt` against arXiv's `/e-print/` + LaTeXML.

---

## 7. Known stubs / deferrals

Things that LOOK shipped but aren't fully wired — don't be surprised.

> **Re-verified against source at `9227be0` on 2026-07-24.** This section
> had drifted badly. Three claims were dropped as simply false —
> `cite_neighbors` (wired in verification-feedback-m1),
> `find_lemma_by_name` (FTS5 shipped in E10_S02), and `make ingest`
> (runs the real `ingest.bulk_ingest` since E11_S01). Three more were
> narrowed to the part that is still true. The tool *handlers* are all
> wired; what remains deferred is a handful of *arguments* and *input
> modes*. Current capability claims live in §6.

- **`get_chunk`'s `include_equations`** is accepted and ignored — equation
  atoms are not wired into the chunk surface. It is the sole remaining
  member of the `_record_unused_args` name tuple
  (`server/handlers/chunk.py:221`), so passing it echoes it back in
  `unused_args`. Its sibling `include_referenced` is **live** (§6).
- **`search_papers`'s `cursor`** is accepted and ignored; `next_cursor` is
  always `null` (pagination deferred to E07_S04). Unrecognized `filters`
  keys (`categories`, `year_min`, …) are likewise ignored and surface in
  `filter_warnings` — but four keys ARE honored end-to-end (§6).
- **`find_equation` on LaTeX input** is, by default, a dense-only fallback
  over `embedding_stmt` (`retrieval_mode="dense_only_stmt_fallback"`).
  retrieval-unlocks-m4 added an opt-in route (`Config.eq_latex_route`,
  **default OFF**): when enabled, a LaTeX query is converted to Presentation
  MathML at request time via `latex2mathml` and routed onto the SAME TED lane
  as MathML input (`retrieval_mode="ted_fused"`/`"ted_fused_eq"`, plus a
  `query_conversion` provenance field); an unconvertible query falls back to
  `dense_only_stmt_fallback`. The conversion is a pure-Python `latex2mathml`
  call — there is still **no** query-time LaTeXML subprocess pool in the
  request path. MathML input has always taken the TED path (`ted_fused`)
  directly.
- **Index-absent degradation is by design, not breakage.** With no
  theorem-names SQLite DB, `find_lemma_by_name` falls back to the legacy
  in-memory scan (`retrieval_mode="in_memory_scan_fallback"`); with no
  `equations` table (or all-NULL `mathml_tree_json`), `find_equation`
  degrades to `dense_only_fallback`; with no Kùzu DB, `cite_neighbors`
  returns `graph_status="absent"`. Read `retrieval_mode` / `graph_status`
  before concluding a query "returned nothing" — a degraded answer and an
  empty corpus are different facts (§4.9).
- **`get_paper`** serves real `authors`/`title`/`abstract`/`year`/`categories`
  (`metadata_status="hydrated"`; title/abstract/authors wrapped in
  `<retrieved_chunk>` delimiters) when the per-notebook metadata store
  (`server/paper_metadata_store.py` → `var/arxmcp/notebooks/<slug>/paper_metadata.db`,
  hydrated via `tools/notebook_metadata_backfill.py`) has a usable row —
  wired in paper-metadata-m2. Papers without a row, and the shared corpus
  (no metadata sibling next to its lancedb dir), still return NULLs with
  `metadata_status="synthesized_from_chunks"`.
- **`embedding_eq` column** on `chunks` is reserved and always NULL — the
  embedder never populates it (`ingest/schema.py:165`). The separate
  `equations` table has its own `embedding_eq`, also NULL at v1, but
  `server/retrieval/equations.py` already carries the populated-path
  branch for whenever a future milestone fills it.
- **Retrieval-quality eval gate** has the harness shipped (`make eval`)
  but the curated 20-query fixture is still being hand-labeled per
  [`.claude/docs/eval-curation.md`](.claude/docs/eval-curation.md) —
  `tests/eval/fixtures/queries.json` still carries an empty `queries` list.
- **The wire schema deliberately lags behavior on two arguments.**
  `get_chunk.include_referenced` still advertises "Reserved for E07_S03;
  ignored at v1", and the `search_papers.filters` description does not
  mention `include_kinds` — both false, both intentional: `tools/list`
  must stay byte-stable for BP1 prompt-cache discipline, so the corrected
  strings are staged for one bundled `TOOL_SCHEMA_VERSION` re-pin in
  agent-platform's W1 window
  ([`.claude/docs/w1-schema-deltas.md`](.claude/docs/w1-schema-deltas.md)).
  **Do not trust a tool DESCRIPTION string over §6 and this section** —
  that mismatch is what made this section stale in the first place.

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

8. **`uv run pytest` vs system `pytest`.** The system `pytest` is
   Python 3.9; the project requires 3.11+. Use
   `/Users/chris.dare/Library/Python/3.9/bin/uv run python -m pytest`.

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

```bash
make test                                                    # ruff + pytest
/Users/chris.dare/Library/Python/3.9/bin/uv run python -m pytest --tb=no
```

### Start the MCP server (local dev)

```bash
make up
```

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
| Citation graph query empty | `server/handlers/citations.py` — read `graph_status` first (`absent` = graph never ingested, `unavailable` = path exists but unqueryable, `present` = real empty result); then `server/graph_queries.py` |
| `make eval` skipped | `tests/eval/fixtures/queries.json` is still an empty stub |

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
