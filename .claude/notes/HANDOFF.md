# arXMCP — Session Handoff (post-E09 + doc consolidation)

**Snapshot date:** 2026-05-10
**Branch:** `main`
**Worktree:** `/Users/chris.dare/Personal/SourceCode/arXMCP` (no
detached worktree this session; all work directly on `main`)
**Latest commit:** `49dbd29` — `docs(repo): enforce strict root-MD
layout; agent docs under .claude/`
**Remote:** `https://github.com/chris-dare-dev/arXMCP.git` —
`origin/main` in sync.
**Test count:** 1311 passing, 4 skipped (`requires_model`), 0 failed
**Lint status:** `ruff check .` clean
**Tree state:** clean (`git status` reports nothing).

The prior handoff (pre-E09 session, ending at `144b1cc`) was archived
to [`.claude/notes/handoffs/HANDOFF-pre-E09.md`](handoffs/HANDOFF-pre-E09.md)
for historical reference.

---

## 1. What this project is (one-paragraph orientation)

**arXMCP** is a local-first MCP (Model Context Protocol) server that
exposes a research-mathematics arXiv corpus to multi-agent Claude
pipelines (`math.AG`, `math.NT`, `math-ph`, `hep-th`). The intended
consumer is a Claude **sketcher → autoformalizer → tactician → fixer**
pipeline; every sub-agent calls into one shared MCP endpoint at
`127.0.0.1:7733` (Streamable HTTP, MCP 2025-06-18 spec). The
constitutional framing — *"Lean's kernel is a better critic than
another LLM"* — drives every architectural choice: invest aggressively
in retrieval + pre-loading; don't spend tokens on LLM-as-critic for
math content.

Full design notes: [`.claude/notes/`](.) — start with
[`01-mission-and-context.md`](01-mission-and-context.md) and
[`.claude/notes/README.md`](README.md) for reading order.

Project-scope orientation for new agents:
[`/CLAUDE.md`](../../CLAUDE.md).

---

## 2. What was accomplished in this session (2026-05-10)

This session shipped **E09 in full** (4 milestones, the final epic in
Tiers 0-2 of the roadmap) and then did a **repo-wide doc-layout
consolidation**.

### 2.1 E09 — Citation Graph epic (SHIPPED in this session; closes H7)

Four milestones, all via the [`/milestone-pipeline`](../skills/milestone-pipeline/SKILL.md)
4-phase Research → Implement → Critique → Rectify discipline. Every
milestone produced the canonical three-commit triple:
`feat(...)` + `rect(...)` + `chore(notes): finalize`.

| Milestone | Feat | Rect | Findings closed | Closes |
|---|---|---|---|---|
| **E09_S01** Kùzu schema + OpenAlex bulk ingest | `732dd8e` | `95fd3cf` | 3 HIGH + 5 MED + 1 LOW | |
| **E09_S02** INSPIRE-HEP enrichment + schema v2 | `2c12ef4` | `4cd2c7f` | 2 HIGH + 6 MED | F4 from S01 (multi-source-write split-writer pattern) |
| **E09_S03** `cite_neighbors` async library + intra-paper `\ref{}` ingest | `d10157d` | `2ca0042` | 2 HIGH + 4 MED + 2 LOW | |
| **E09_S04** 2-round proof-chain workflow + 500ms perf gate | `b29fcf2` | `25cbe3a` | 1 HIGH + 4 MED + 3 LOW | **H7 fully closed** |

**H7 closure framing** ("cross-paper proof chains unaddressed"): the
[`server/graph_queries.py::cite_neighbors`](../../server/graph_queries.py)
async library + the documented 2-round agent pattern in
[`.claude/docs/proof-chain-workflow.md`](../docs/proof-chain-workflow.md)
together close H7. `tests/test_proof_chain.py` (10 tests including a
500 ms perf gate on a synthetic 50-paper graph) is the verification.

**Cumulative E09 test delta:** 1177 → 1312 passed (+135 new tests in
this session pre-doc-consolidation). Adversary critic
**well-calibrated** across all 4 milestones — 0% HIGH-invalidation
rate at every Phase-4 re-verify.

### 2.2 Repo-wide doc consolidation (2026-05-10, commits `7094d0c` + `49dbd29`)

The user requested a **strict root-MD layout**:
- Root contains ONLY 5 files: `README.md`, `CLAUDE.md`, `CHANGES.md`,
  `SECURITY.md`, `OWNERS.md`.
- Non-`.claude/` subdirs contain only `README.md` / `CLAUDE.md`.
- `docs/` contains only operator-facing docs the root README links to
  (today: only `install.md`).
- All other Markdown agents create lives under `.claude/`.

To meet that:

- **New top-level files created:**
  - [`README.md`](../../README.md) — rewritten to project scope only
    (what / how to use / layout / hard constraints). No roadmap, no
    epics, no work-tracking content.
  - [`CLAUDE.md`](../../CLAUDE.md) — full agent context. Mission,
    ship status, working conventions (main-only, milestone-pipeline
    discipline, conventional commits, GPG signing, HEREDOC commits,
    never `--no-verify`, `uv run pytest`), directory layout,
    capabilities, known stubs, gotchas, quick-task recipes. **READ
    THIS FIRST.**
  - [`CHANGES.md`](../../CHANGES.md) — epic-grain changelog covering
    E01-E09 + the doc consolidation.
  - [`SECURITY.md`](../../SECURITY.md) — reporting policy +
    security-invariants table referencing
    [`08-security-observability-ops.md`](08-security-observability-ops.md).
  - [`OWNERS.md`](../../OWNERS.md) — single owner
    (`chris.dare@nalej.com`); single-user / single-workstation
    working model.

- **Files moved (via `git mv`, history preserved):**
  - `TIER-GATES.md` → [`.claude/TIER-GATES.md`](../TIER-GATES.md)
  - `server/prompts.md` → [`.claude/notes/prompts-bp-discipline.md`](prompts-bp-discipline.md)
  - 7 files from `docs/` → [`.claude/docs/`](../docs/):
    `chunker-fixtures.md`, `eval-curation.md`, `model-policy.md`,
    `orchestrator-rules.md`, `proof-chain-workflow.md`,
    `retrieval-quality-report.md`, `snippet-contract.md`

- **Files deleted:**
  - `ROADMAP.md` — was a self-superseded redirect; authoritative
    roadmap remains [`.claude/roadmap/README.md`](../roadmap/README.md).

- **Test path constants updated in lockstep:**
  - `tests/test_model_selector.py` `POLICY_DOC_PATH`
  - `tests/test_prompts.py` `PROMPTS_DOC_PATH`
  - `tests/test_proof_chain.py` `DOC_PATH`
  - `tests/test_snippet_contract.py` `DOC_PATH`
  - `tests/test_tier_gates_doc.py` `TIER_GATES_PATH` + dropped the
    `TestReadmeLinksTierGates` AC (README-link-to-TIER-GATES is
    incompatible with the new root scope).
  - `Makefile` and `tools/validate_eval_fixtures.py` updated.
  - Relative-link prefixes in the 7 moved docs corrected via sed
    (`../server` → `../../server`, etc.).

- **Test count delta:** 1312 → **1311 passed** (the one lost test was
  the dropped `TestReadmeLinksTierGates`; the move was intentional).

### 2.3 Session commits, in order

Total: **17 commits pushed to `origin/main` this session.** Listed
newest first:

```
49dbd29  docs(repo): enforce strict root-MD layout; agent docs under .claude/
7094d0c  docs(repo): rewrite README + add CLAUDE.md + consolidate ROADMAP
8e19ed6  chore(notes): commit carried-over E01_S01-S03 milestone artifacts
b79bab8  chore(notes): finalize E09_S04 state -> complete (H7 closed)
25cbe3a  rect(docs,tests): close 1 HIGH + 4 MEDIUM + 3 LOW from E09_S04 critique
b29fcf2  feat(docs,tests): 2-round proof-chain workflow + H7 closure (E09_S04)
7d89e0e  chore(notes): finalize E09_S03 state -> complete
2ca0042  rect(server,ingest): close 2 HIGH + 4 MEDIUM + 2 LOW from E09_S03 critique
d10157d  feat(server,ingest): cite_neighbors graph query + intra-paper refs (E09_S03)
e5ecbee  chore(notes): finalize E09_S02 state -> complete
4cd2c7f  rect(ingest): close 2 HIGH + 6 MEDIUM from E09_S02 critique
2c12ef4  feat(ingest): inspire-hep enrichment + schema v2 (E09_S02)
5c4bc9c  chore(notes): finalize E09_S01 state -> complete
95fd3cf  rect(ingest): close 3 HIGH + 5 MEDIUM + 1 LOW from E09_S01 critique
732dd8e  feat(ingest): kuzu schema + openalex bulk ingest (E09_S01)
fbda415  chore(repo): accumulated milestone artifacts + HANDOFF + uv.lock   (pre-session; baseline)
```

(The pre-session baseline was `fbda415`; the 12 E09 commits + 1
carry-over + 2 doc-consolidation commits = 17 total to a new agent
reading the log.)

### 2.4 Critical findings surfaced during E09 (lessons for future epics)

These were verified live by research agents and shaped the
implementations:

1. **Kùzu was archived 2025-10-10.** The upstream graph DB project is
   frozen. `pyproject.toml` pins `kuzu==0.11.3` (the last stable
   release, MIT). Do NOT bump this without checking for a fork
   migration path (Kineviz `bighorn` or `Vela-Engineering/kuzu`).

2. **OpenAlex Concept IDs in the E09_S01 brief were wrong.** The
   brief named `C66938386` (claimed to be "algebraic geometry") and
   `C15736585` (claimed to be "number theory"). Live verification
   showed `C66938386` resolves to "Structural engineering" and
   `C15736585` returns 404. The correct IDs are `C68363185` and
   `C169654258`, but OpenAlex Concepts are deprecated in favor of
   Topics. The shipped implementation uses arXiv-URL-as-identifier
   resolution (the canonical Topics-based bulk-discovery path raises
   `NotImplementedError` and points at this gap).

3. **Brief vs. design-constitution path drift (`kuzudb/` vs
   `kuzu/`).** Three E09 briefs (S01, S03, S04) name
   `var/arxmcp/index/kuzudb/`; the Makefile bootstrap, design notes,
   and shipped code use `var/arxmcp/index/kuzu/`. The latter wins
   (three repo signals beat one brief signal). Documented in the
   relevant module docstrings.

4. **`relationships(p)` projection works in Kùzu 0.11.3** even though
   list-comprehensions over recursive-rel bindings (`[r IN rels | r.source]`)
   fail with a binder exception. The `cite_neighbors` implementation
   uses the projection function to extract per-hop edge metadata in
   a single query. If a future Kùzu version (or fork migration)
   breaks this, the documented two-query fallback (depth=1 +
   depth=2-only-via-2-hops) is the migration path.

5. **`search_papers` filters argument is accepted but ignored at v1.**
   Deferred to E07_S04. The `chunk_id=None` fallback in the proof-
   chain workflow says the agent could call
   `search_papers(filters={"paper_id": ...})` for a paper-scoped
   search, but v1 surfaces a `filter_warnings` entry instead of
   honoring the filter. **Agents should currently SKIP `chunk_id=None`
   neighbors rather than spending a third round on a search that
   v1 cannot satisfy.** The doc states this accurately.

---

## 3. Final repository state

### 3.1 Top-level layout

```
arXMCP/
├── README.md          PROJECT SCOPE ONLY (what / how to use / layout)
├── CLAUDE.md          AGENT CONTEXT (start here for new sessions)
├── CHANGES.md         epic-grain changelog
├── SECURITY.md        reporting policy + security invariants
├── OWNERS.md          single owner; main-only workflow
├── Makefile           make help / bootstrap / test / eval / up / ingest
├── pyproject.toml     Python ≥3.11; per-line dep comments
├── uv.lock
├── docs/
│   └── install.md     operator-facing only (linked from root README)
├── server/, ingest/, tests/, tools/, shim/, docker/, infra/
│   └── (each contains only README.md as a navigational nav)
├── var/               gitignored (created by `make bootstrap`)
└── .claude/
    ├── TIER-GATES.md          machine-checkable tier promotion gates
    ├── docs/                  7 per-feature internal references
    │   ├── chunker-fixtures.md
    │   ├── eval-curation.md
    │   ├── model-policy.md
    │   ├── orchestrator-rules.md
    │   ├── proof-chain-workflow.md
    │   ├── retrieval-quality-report.md
    │   └── snippet-contract.md
    ├── notes/                 design constitution + handoffs
    │   ├── README.md           reading-order index
    │   ├── 01..10-*.md         numbered design notes
    │   ├── prompts-bp-discipline.md   (moved from server/prompts.md)
    │   ├── HANDOFF.md          this file
    │   ├── handoffs/HANDOFF-pre-E09.md   (the prior session's handoff)
    │   ├── scans/              repo-wide research scans (history)
    │   └── milestones/         per-milestone state.json + artifacts
    ├── roadmap/                14 per-epic plans + index
    │   ├── README.md            authoritative epic index
    │   └── E<NN>-*.md           per-epic specs
    └── skills/
        └── milestone-pipeline/  the 4-phase milestone discipline
```

### 3.2 Epic status (sourced from
[`.claude/notes/milestones/<ID>/state.json phase=complete`](milestones))

| Epic | Status | Notes |
|---|---|---|
| E01 Vertical Slice | ✅ DONE | 50-paper math.AG seed corpus |
| E02 Chunker | ✅ SHIPPED | |
| E03 Embedder | ✅ SHIPPED | BGE-M3 dual-column |
| E04 Vector Store | ✅ SHIPPED | LanceDB MVCC + BM25 |
| E05 Eval Harness | ✅ SHIPPED (harness only) | 20-query fixture still empty stub; hand-curation pending |
| E06 MCP Server | ✅ SHIPPED | 7 tools registered (`cite_neighbors` is a v1 stub) |
| E07 Hybrid Retrieval | ✅ SHIPPED | BM25 + ANN+RRF + BGE-reranker modules |
| E08 Agent Runtime + Caching | ✅ SHIPPED | Router, 3-tier cache, ID canon, model policy |
| E09 Citation Graph | ✅ SHIPPED | Closes H7 fully |
| E10 Specialized Indices | ⏳ PENDING | Equation TED, FTS5 theorem-name, full eq similarity |
| E11 Scale Cutover | ⏳ PENDING | Production ingest driver; `make ingest` still a stub |
| E12 Full Corpus | 🚫 SCOPED OUT | Folded into E11 |
| E13 Security Hardening | ⏳ PENDING | Audit across 7 tools beyond E06_S05 |
| E14 Observability/Ops | ⏳ PENDING | docker-compose, OTel, alerting runbooks |

---

## 4. What remains to be done

### 4.1 Immediate / Tier-3-blocking work

**E10 — Specialized Indices** (4 milestones, all NEW):

- **E10_S01** — Definitions index + dedicated `get_definitions` improvements
- **E10_S02** — FTS5 theorem-name index → swap the in-memory substring
  scan in `server/handlers/lemma.py` (`find_lemma_by_name`) for a real
  index
- **E10_S03** — Equation index: Zhang-Shasha tree-edit distance over
  canonical MathML fused with dense cosine on `embedding_eq` (currently
  reserved NULL column). Closes **H5**.
- **E10_S04** — LaTeXML version drift detector

Brief: [`.claude/roadmap/E10-specialized-indices.md`](../roadmap/E10-specialized-indices.md).

**E11 — Scale Cutover** (5 milestones, all NEW) is the production cutover:

- **E11_S01** — Academic Torrents seed download + bulk ingest
- **E11_S02** — OAI-PMH delta loop (incremental updates)
- **E11_S03** — Re-embed cost budget + partial re-embed strategy
- **E11_S04** — Drift watchdog (per-corpus-version nDCG@5 regression alert)
- **E11_S05** — Backup/restore runbook + 200K cutover activation
  (closes **H9** — Tier-5 cutover trigger)

This is where `make ingest` finally stops being a stub.
Brief: [`.claude/roadmap/E11-scale-cutover.md`](../roadmap/E11-scale-cutover.md).

### 4.2 Secondary work (Tier-3+)

**E13 — Security Hardening** (10 sub-issues): per-threat audits across
the 7 tools (path traversal, prompt injection, LaTeXML sandbox,
resource exhaustion, Origin spoofing, supply chain, source-ingestion
TLS). Brief: [`.claude/roadmap/E13-security.md`](../roadmap/E13-security.md).

**E14 — Observability & Ops** (10+ sub-issues): `/metrics` full
Prometheus surface, OTel tracing, Phoenix retrieval-quality views, daily
ops runbook + cron, failure-mode handlers + restic backup, dashboards,
Langfuse orchestrator-side tracing, API spend metrics. Brief:
[`.claude/roadmap/E14-observability-ops.md`](../roadmap/E14-observability-ops.md).

### 4.3 Smaller debts the next agent should know about

These are NOT roadmap items; they're per-milestone deferrals the
critique loops surfaced and the user accepted as "fix when convenient":

| Where | Issue | Severity |
|---|---|---|
| `server/handlers/citations.py` | v1 stub returning `{neighbors: [], infrastructure_status: "deferred"}`. The real library at `server/graph_queries.py::cite_neighbors` is shipped + tested. Wiring requires formalizing the path-validation boundary contract (F2 from E09_S03 critique). Likely a future E06_S0X milestone. | MEDIUM |
| `server/prompts.py::SYSTEM_PROMPT` | Still a placeholder ("<placeholder system prompt — E08_S04 will author the v1 body...>"). When the real prompt lands, `EXPECTED_BP1_SHA256` in `tests/test_prompts.py` must be re-pinned. | LOW |
| `server/prompts.py::EXTENDED_CACHE_TTL_HEADER_VALUE` | Carries a `TODO(E08_S04)` to verify against current Anthropic docs. | LOW |
| `ingest/intra_paper_refs.py::_list_paper_ids_from_lancedb` | Uses unbounded `limit(1_000_000)` — a Tier-4 corpus could silently truncate. (F7 from E09_S03 critique, deferred.) | MEDIUM-when-Tier-4 |
| `tests/eval/fixtures/queries.json` | Empty stub. Tier-0 → Tier-1 promotion gate (per [`.claude/TIER-GATES.md`](../TIER-GATES.md)) requires this fixture to be hand-curated per [`.claude/docs/eval-curation.md`](../docs/eval-curation.md). | HIGH (gates Tier-1) |
| `[project.scripts] arxmcp-server` | `docs/install.md` mentions an `arxmcp-server` console script that doesn't exist in `pyproject.toml`. Operators must use `python -m server.main` (which is what `make up` does). Either declare the script or fix the doc. | LOW |
| OpenAlex API-key transition | A January 2026 announcement floated requiring API keys post-Feb 13 2026; current docs still document the polite-pool/mailto pattern. There's a `TODO` in `ingest/graph_ingest.py` for an API-key path. | LOW (until OpenAlex actually flips the switch) |
| `_normalize_source` casing inconsistency | OpenAlex edges in the Kùzu graph are written with `source="openAlex"` (camelCase from the brief); INSPIRE-HEP uses `source="inspire"` (lowercase, matching the design constitution at `05-storage-and-indexing.md:211`). A future cleanup PR could normalize the OpenAlex casing. | LOW |

---

## 5. How to resume — step-by-step for the next session

### 5.1 Verify clean state

```bash
cd /Users/chris.dare/Personal/SourceCode/arXMCP
git status                          # should show clean tree on `main`
git log --oneline -5                # newest commit: 49dbd29 (doc consolidation)
git fetch && git status -uno        # confirm in sync with origin/main
```

### 5.2 Activate the Python environment

The project uses `uv`:

```bash
# uv lockfile is committed; .venv is created by `uv sync`
/Users/chris.dare/Library/Python/3.9/bin/uv sync --extra dev
```

**Critical:** the system `python3` is 3.9; the project requires 3.11+.
Always invoke pytest via `uv run`:

```bash
/Users/chris.dare/Library/Python/3.9/bin/uv run python -m pytest --tb=no -p no:warnings | grep passed
# expected: 1311 passed, 4 skipped
```

### 5.3 Read in order

The next agent should read these BEFORE touching code:

1. [`/CLAUDE.md`](../../CLAUDE.md) — project-level context + doc-layout rule + working conventions
2. This handoff (you are here)
3. [`.claude/notes/01-mission-and-context.md`](01-mission-and-context.md) — the "Lean kernel is the better critic" framing
4. [`.claude/roadmap/README.md`](../roadmap/README.md) — authoritative epic index, ship status
5. [`.claude/notes/07-multi-agent-caching.md`](07-multi-agent-caching.md) — load-bearing for ANY change touching tool schemas, prompts, or cache discipline
6. Pick the next milestone's brief from `.claude/roadmap/E<NN>-*.md`

### 5.4 Pick the next milestone

**Most likely next ask: `E10_S01`** (definitions index — Tier-3-flavored
work; closes the dynamic-substring-scan limitation of
`find_lemma_by_name`). Alternative: `E13_S01` if the user prioritizes
security hardening before specialized indices.

Invoke the milestone-pipeline skill:

```bash
/milestone-pipeline E10_S01
```

The skill is documented at
[`.claude/skills/milestone-pipeline/SKILL.md`](../skills/milestone-pipeline/SKILL.md).
The 4-phase discipline (Research → Implement → Critique → Rectify) is
**non-negotiable**. Skipping a phase or short-circuiting the rectifier
protocol is the named anti-pattern in the skill's own SKILL.md.

State persists at `.claude/notes/milestones/<ID>/state.json` —
strict-forward-only through nine phases.

### 5.5 Per-milestone commit pattern

Every milestone produces three commits, in order:

1. `feat(<scope>): <topic> (E<NN>_S<MM>)`
2. `rect(<scope>): close <N> <severity> from E<NN>_S<MM> critique`
3. `chore(notes): finalize E<NN>_S<MM> state -> complete`

GPG signing is enabled (`commit.gpgsign=true`). Never `--no-gpg-sign`.
Pre-commit hooks are honored. Never `--no-verify`. Mandatory co-author
trailer:

```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

Use HEREDOC for commit messages to survive apostrophes:

```bash
git commit -F - <<'COMMIT_EOF'
feat(scope): subject line

Body.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
COMMIT_EOF
```

### 5.6 Push when authorized

`git push` is per-event authorization. Re-ask each time. The current
remote is `origin` → `https://github.com/chris-dare-dev/arXMCP.git`.
Push target is `main` (NOT `dev` — this repo doesn't have a `dev`
branch; the user-level CLAUDE.md's dev-branch rule applies to the
platform repo at a different path, not this project).

---

## 6. Project conventions (load-bearing)

Restated from [`CLAUDE.md`](../../CLAUDE.md). All of these are
enforced by the test suite or by pre-commit hooks.

### 6.1 Doc-layout rule (new in this session)

| Location | What's allowed |
|---|---|
| **Repo root** | Only `README.md`, `CLAUDE.md`, `CHANGES.md`, `SECURITY.md`, `OWNERS.md`. |
| **Subdirs other than `.claude/`** | Only `README.md` and `CLAUDE.md`. |
| **`docs/`** | ONLY user-facing docs the root README links to (today: just `install.md`). |
| **`.claude/`** | Everything else agents create — design notes, roadmap, milestones, agent-internal references, scans, gate specs. |

**Never put a Markdown file in `server/`, `ingest/`, `tests/`,
`tools/`, `shim/`, `docker/`, or `infra/`** beyond `README.md` /
`CLAUDE.md`.

### 6.2 Coding conventions

- **`assert` is BANNED for invariants** (Python `-O` strips them). Use
  `if … raise RuntimeError(…)`.
- **Pure-ASGI middleware required.** `BaseHTTPMiddleware` is
  project-banned (E06_S01 F1).
- **No `anthropic` SDK at runtime.** Server is a tool provider; the
  LLM lives in the calling agent. Pinned by
  `tests/test_snippet_contract.py:340-351`.
- **No-fork policy.** Nothing lifted from existing `arxiv-mcp` repos.
- **`server/` source NEVER references `claude-opus`.** Model selection
  is Haiku/Sonnet only. Pinned by
  `tests/test_model_selector.py::TestForbiddenStrings`.

### 6.3 Test discipline

- `make test` = `ruff check .` + `pytest`. All 1311 tests must pass +
  ruff clean before any commit.
- Use `/Users/chris.dare/Library/Python/3.9/bin/uv run python -m pytest`
  (NOT the system pytest, which is 3.9 and incompatible).
- Two test markers: `requires_model` (skipped by default; opt-in via
  per-model env vars) and `eval` (Tier-0/1 gate; skipped via cold-start
  matrix when fixture / corpus is missing).

---

## 7. Known landmines (THE list every agent should re-read)

1. **macOS pytest segfault with `faiss-cpu` + PyTorch.** The
   `KMP_DUPLICATE_LIB_OK=TRUE` workaround in `tests/conftest.py` is
   required to avoid SIGSEGV. Cleared at session end if `conftest.py`
   set it. Linux containers don't need it.

2. **Kùzu archived 2025-10-10.** Pin is `kuzu==0.11.3` exactly. Don't
   bump without re-evaluating the upstream-fork landscape.

3. **OpenAlex Concept IDs in epic prose are wrong/deprecated.** See §
   2.4 above. The shipped code uses arXiv-URL-as-identifier resolution
   for the seed-corpus path; the category-bulk path raises
   `NotImplementedError`.

4. **`var/arxmcp/index/kuzu/` vs `kuzudb/`.** Three epic briefs (S01,
   S03, S04) used `kuzudb/`; we shipped `kuzu/` (matches Makefile
   bootstrap + design notes). The brief wording is documented drift.

5. **Tool-use ID canonicalization MUST run over the FULL accumulated
   history each turn.** Passing only the new-turn slice produces
   collisions across transitions. Documented in
   [`.claude/docs/orchestrator-rules.md`](../docs/orchestrator-rules.md).

6. **HEREDOC commits.** Bash mangles `$(cat <<'EOF' … EOF)` form when
   the body has apostrophes. Use `git commit -F - <<'COMMIT_EOF' …
   COMMIT_EOF` (stdin form) — survives apostrophes.

7. **Doc-layout consolidation (this session).** Don't reintroduce
   `Markdown` files into `server/`, `ingest/`, `tests/`, etc. Don't
   bring `ROADMAP.md` back at the root.

8. **`uv run pytest` vs system `pytest`.** The system `pytest` is
   3.9; project is 3.11+. Always `uv run`.

9. **`server/handlers/citations.py` is a v1 STUB.** Don't trust
   `cite_neighbors` over MCP to return real results; call
   `server.graph_queries.cite_neighbors` directly (the library) until
   the handler is wired in a future milestone.

---

## 8. The user

- **Primary owner:** `chris.dare@nalej.com` (see [`OWNERS.md`](../../OWNERS.md))
- **Working model:** auto-mode preferred — make reasonable assumptions
  and proceed. Minimal interruption.
- **Expects rigorous adherence to the 4-phase milestone-pipeline.**
- **Appreciates concise end-of-milestone summaries:** key changes, test
  count delta, adversary-critic invalidation rate.
- **All work lands on `main` directly.** No feature branches, no PRs,
  no code review handoff in this repo. (Note: the user-level
  `CLAUDE.md` mentions a `dev` branch convention — that applies to the
  separate `platform/` repo, not arXMCP.)
- **Push is per-event authorization.** Re-ask each time.

---

## 9. Quick links (for fast onboarding)

| What | Where |
|---|---|
| **Start-here for agents** | [`/CLAUDE.md`](../../CLAUDE.md) |
| **Mission & framing** | [`.claude/notes/01-mission-and-context.md`](01-mission-and-context.md) |
| **Authoritative epic index** | [`.claude/roadmap/README.md`](../roadmap/README.md) |
| **Tier-promotion gates** | [`.claude/TIER-GATES.md`](../TIER-GATES.md) |
| **Cache discipline (BP1/BP2)** | [`.claude/notes/07-multi-agent-caching.md`](07-multi-agent-caching.md) |
| **Threat model** | [`.claude/notes/08-security-observability-ops.md`](08-security-observability-ops.md) |
| **Orchestrator rules** | [`.claude/docs/orchestrator-rules.md`](../docs/orchestrator-rules.md) |
| **Model policy** | [`.claude/docs/model-policy.md`](../docs/model-policy.md) |
| **Proof-chain workflow** | [`.claude/docs/proof-chain-workflow.md`](../docs/proof-chain-workflow.md) |
| **Milestone-pipeline skill** | [`.claude/skills/milestone-pipeline/SKILL.md`](../skills/milestone-pipeline/SKILL.md) |
| **Per-milestone state** | [`.claude/notes/milestones/<ID>/state.json`](milestones) |
| **Operator install** | [`docs/install.md`](../../docs/install.md) |
| **Changelog** | [`/CHANGES.md`](../../CHANGES.md) |
| **Security policy** | [`/SECURITY.md`](../../SECURITY.md) |
| **Ownership** | [`/OWNERS.md`](../../OWNERS.md) |
| **Prior session handoff** | [`handoffs/HANDOFF-pre-E09.md`](handoffs/HANDOFF-pre-E09.md) |

---

**End of handoff.** Replace this file (overwrite, archive the existing
file to `handoffs/HANDOFF-<date>.md` first) when the next major chapter
closes.
