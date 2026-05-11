# arXMCP — Documentation Surface Scan

Scan date: 2026-05-10. Repo root: `/Users/chris.dare/Personal/SourceCode/arXMCP`.
Branch state: `main`, latest commit `fbda415`. Per `.claude/notes/HANDOFF.md`,
E01 is DONE and E02–E08 are SHIPPED through `E08_S05`. The directory listing
of `.claude/notes/milestones/` also shows `E09_S01..S04` directories present —
so E09 work is in flight or just landed (state.json files all read `complete`
for E02..E09).

---

## 1. Top-level docs

### `/Users/chris.dare/Personal/SourceCode/arXMCP/README.md` (56 lines, 2.5 KB)

First 30 lines (quoted):

```
# arXMCP

A local-first, Docker-deployable [Model Context Protocol](https://modelcontextprotocol.io/specification/2025-06-18) server that exposes a research-mathematics arXiv corpus to multi-agent Claude pipelines.

The intended consumer is a multi-agent math-proof workflow (sketcher → autoformalizer → tactician → fixer), each a Claude sub-agent, all sharing one corpus through this server.

## Target arXiv categories

- `math.AG` — algebraic geometry
- `math.NT` — number theory
- `math-ph` — mathematical physics
- `hep-th` — high-energy physics, theory

## Documentation

The design constitution lives in [`.claude/notes/`](.claude/notes/README.md). Every implementation decision should trace back to one of those notes — start there before reading code.

The roadmap is at [`ROADMAP.md`](ROADMAP.md) (15 epics, Tier 0 → Tier 7) with per-epic detail under [`.claude/roadmap/`](.claude/roadmap/).

## Repo layout

| Path | Purpose |
|---|---|
| [`server/`](server/) | Streamable HTTP MCP server (long-running, owns indices + caches) |
| [`ingest/`](ingest/) | Ingestion service (separate process, single-writer) |
| [`shim/`](shim/) | stdio → HTTP proxy registered in `~/.claude.json` |
| [`infra/`](infra/) | Docker Compose, container definitions |
| [`tools/`](tools/) | One-off developer scripts (seed corpus fetch, etc.) |
```

Staleness flags:
- Points at `ROADMAP.md` as authoritative but `ROADMAP.md` itself is marked
  SUPERSEDED 2026-05-08 (see §1.2). The README still claims "15 epics, Tier 0
  → Tier 7" while the live roadmap has 14 epics and `E12` is `SCOPED_OUT`.
- "Quick start" section lists only `make help/bootstrap/test/eval` — does NOT
  mention `make up` (server start), `make ingest`, or the
  `arxmcp-server` / `arxmcp-shim` console-script binaries that are now
  installed and load-bearing.
- No mention of E02–E09 having shipped. No mention of seven canonical MCP
  tools (`search_papers`, `get_chunk`, `get_paper`, `paper_diff`,
  `cite_neighbors`, `dependency_graph`, `find_equation`). No mention of
  `docs/` directory.

### `/Users/chris.dare/Personal/SourceCode/arXMCP/ROADMAP.md` (151 lines, 7.6 KB)

Lines 1–11 explicitly mark it SUPERSEDED 2026-05-08 in favor of
`.claude/roadmap/README.md`. Body uses the older epic numbering
(E05 = Storage, E07 = MCP Server, E08 = Multi-Agent Caching, plus a 15th
"E15 QoL" epic that no longer exists). All "epic detail files" links in
the body still point at `.claude/roadmap/epic-01-vertical-slice.md` etc.,
which no longer exist — the live filenames are `E01-shipped.md`,
`E02-chunker.md`, … `E14-observability-ops.md`. The status column
shows every epic as "not started", which is factually wrong post-E08.

Verdict: SUPERSEDED. Header already says so. Body is dead-link-laden and
contradicts the live roadmap by design.

### `/Users/chris.dare/Personal/SourceCode/arXMCP/TIER-GATES.md` (235 lines, 9.1 KB)

Lines 1–34 establish it as the single authoritative source for tier
promotion conditions. Specifies:

- Tier-0 → Tier-1: `pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.70`
  on ANN-only (owner: E05_S02).
- Tier-1 → Tier-2: same test, `--ndcg-min=0.80`, hybrid + reranker
  (owner: E07_S04).
- Tier-2 → Tier-3: cache hit rate ≥ 30 % over 24 h (owner: E08).
- Tier-5 cutover: 200K backfill + drift watchdog within 5 % (E11_S05).

Status: STILL RELEVANT — the gates remain machine-checkable
preconditions for forward tier promotions (Tier-2→Tier-3 needs E08
production traffic; Tier-5 needs E11). Tier-0→Tier-1 and Tier-1→Tier-2
gates exist as code in `tests/eval/`; per `docs/retrieval-quality-report.md`
the actual Tier-1 run is PENDING because `queries.json` is still an empty
stub. Do NOT archive.

The user's "TIER-CONSOLIDATION.md" name does not exist in this repo —
only `TIER-GATES.md`.

---

## 2. `.claude/notes/` — Design constitution

Contents of `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/notes/`:

| File | One-line | Authoritative? |
|---|---|---|
| `README.md` | Index + reading order + hard constraints. | YES — still load-bearing index. |
| `01-mission-and-context.md` | Why arXMCP exists: research-math agent pipeline, math vs code asymmetry, NotebookLM equivalent for Claude. | YES. |
| `02-architecture-overview.md` | Two headline corrections (Streamable HTTP transport; macro expansion before embedding); top-level system diagram. | YES. |
| `03-ingestion-pipeline.md` | Academic Torrents + OAI-PMH + `/e-print/` + INSPIRE/OpenAlex; no S3. | YES — still spec; landing in E11. |
| `04-parsing-and-chunking.md` | LaTeXML primary, ar5iv cache, Nougat fallback; theorem+proof pairing chunker. | PARTIAL — chunker shipped per E02, but LaTeXML container deferred to E11. |
| `05-storage-and-indexing.md` | LanceDB schema (dual `embedding_stmt`/`embedding_proof`), MVCC, BM25, Kùzu. | YES — schema shipped per E04. |
| `06-mcp-server-design.md` | Streamable HTTP, stdio shim, tool surface, byte-stable cache discipline. | YES — server shipped per E06. |
| `07-multi-agent-caching.md` | Anthropic prompt cache, BP1/BP2 breakpoints, 3-tier retrieval cache, singleflight. | YES — caching landed per E08. |
| `08-security-observability-ops.md` | 7-threat threat model, observability stack, daily ops cadence. | YES — referenced by E13/E14. |
| `09-feature-priorities.md` | Tier-0 → Tier-7 feature ROI ranking. | **SUPERSEDED** (own header L1–11; superseded 2026-05-06 by `.claude/roadmap/README.md`). Specific obsoletions: BM25-over-LaTeX-analyzer, Voyage embedders, symlink swaps, 9-tool surface. |
| `10-references-and-prior-art.md` | PaperQA2, LeanDojo, DeepSeek-Prover, OpenAlex, INSPIRE, protocol specs. | YES — reference doc. |
| `HANDOFF.md` | In-session handoff snapshot, dated 2026-05-10, snapshots state through E08_S05. | PARTIAL — captures up to E08_S05; does NOT yet reflect E09_S01–S04 completion shown in milestones/. Useful as session continuity doc, but stale by a few days. |

Quoted mission statement (`01-mission-and-context.md` L1–22):

```
# 01 — Mission and Research Context

## The problem we are solving

A solo developer wants to run multi-agent Claude Code pipelines that attack
research-level mathematics problems. The agent roles parallel a code-review pipeline
they already use:

| Code pipeline role | Math pipeline role | What it does |
|---|---|---|
| Researcher (Opus) | Sketcher | Reads relevant prior work; produces a natural-language proof outline |
| Implementer (Sonnet) | Autoformalizer + Tactician | Translates the sketch to Lean 4 with `sorry` placeholders, then fills each subgoal |
| Adversarial critic (Sonnet) | Lean kernel | Verifies the proof; in math the LLM critic is structurally weak — Lean is the real critic |
| Fixer (Sonnet) | Fixer | Reads Lean's error message, retries with retrieval over similar lemmas |

Every Claude agent in this pipeline needs deep background context — definitions,
prior lemmas, related theorems, conventions in subfields like algebraic geometry or
hep-th. Without that context the agents produce nonsense at every stage. **arXMCP is
the substrate that gives every agent in the pipeline grounded access to a
research-math arXiv corpus.**
```

---

## 3. `.claude/roadmap/` — Per-epic plans

Contents of `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/roadmap/`:

| File | Epic status (header) | One-line |
|---|---|---|
| `README.md` | (index, rev 2026-05) | Authoritative roadmap index; supersedes `.claude/notes/09-feature-priorities.md`. |
| `E01-shipped.md` | `PRESERVED — DONE` | 50-paper vertical slice; commits `8633cc6` → `01c6579`. |
| `E02-chunker.md` | `NEW` | Theorem-aware structural chunker, preamble extractor, regex pre-tokenizer, fixtures. |
| `E03-embedder.md` | `NEW` | BGE-M3 dual-column encoder + singleflight + idempotent re-embed. |
| `E04-vector-store.md` | `NEW` | LanceDB chunks schema, MVCC, corpus_version marker, BM25 index. |
| `E05-eval-harness.md` | `NEW` | 20-query fixture + nDCG@5 / Recall@10 test + Tier-0 gate doc. |
| `E06-mcp-server.md` | `NEW` | FastAPI Streamable HTTP server, stdio shim, 7-tool surface, snippet contract, Origin pinning, schema stability. |
| `E07-hybrid-retrieval.md` | `NEW` | 3-phase BM25 → ANN+RRF → BGE-reranker pipeline + Tier-1 gate. |
| `E08-agent-runtime.md` | `NEW` | Python regex router, role-as-user-prefix, 3-tier retrieval cache, tool-use ID canonicalization, model selection. |
| `E09-citation-graph.md` | `NEW` | Kùzu graph, OpenAlex + INSPIRE-HEP ingest, `cite_neighbors`, proof-chain workflow. |
| `E10-specialized-indices.md` | `NEW` | Definitions index, theorem-name index, equation index (TED + dense), LaTeXML drift detector. |
| `E11-scale-cutover.md` | `NEW` | Academic Torrents seed, OAI-PMH delta, re-embed budget, drift watchdog, backup runbook. |
| `E12-full-corpus.md` | `SCOPED OUT — folded into E11` | Empty placeholder for numbering consistency. |
| `E13-security.md` | `NEW` | Threat-model audit across 7 tools (path-traversal, prompt-injection, etc.). |
| `E14-observability-ops.md` | `NEW` | `/metrics`, OTel tracing, Phoenix, runbooks, backup/restore, deferred Tier-6 tracker. |

Cross-check vs `.claude/notes/milestones/`:

State.json `phase: complete` confirmed for: `E02_S01..S05`, `E03_S01..S03`,
`E04_S01..S04`, `E05_S01..S03`, `E06_S01..S06`, `E07_S01..S04`,
`E08_S01..S05`, `E09_S01..S04`. `E01_S01-S03` reads `rectify-running`
(pre-state-machine artifact). E10..E14 milestones have NO state.json yet
— they are unshipped.

Note: the roadmap README's per-epic Status column still says "NEW" for
E02..E11/E13/E14 — i.e. the README has not been updated as epics
shipped. Authoritative ground truth for "shipped" is the
`.claude/notes/milestones/*/state.json` files, not the README column.

---

## 4. `docs/` — Public-facing documentation

Contents of `/Users/chris.dare/Personal/SourceCode/arXMCP/docs/`:

| File | Audience | Content |
|---|---|---|
| `chunker-fixtures.md` | Contributors editing the chunker | E02_S05 fixture suite: 10 hand-crafted HTML fixtures, schema, scenario coverage table. |
| `eval-curation.md` | Eval curator (human) | E05_S01 manual runbook for hand-labeling 20 `(query, chunk_id, relevance)` triples; cannot be LLM-automated. |
| `install.md` | New operators | Step-by-step `pipx install arxmcp` → register `arxmcp-shim` in `~/.claude.json` → `make up` → verify via tools/list. Includes troubleshooting matrix and out-of-scope (TLS, auth). |
| `model-policy.md` | Orchestrator implementers | Canonical 4×3 `(RouteTag, TurnType) → model_id` table; Haiku default, Sonnet for `LEAN_WRITE`, forbidden cells raise `ValueError`. Frozen at E08_S05. |
| `orchestrator-rules.md` | Orchestrator implementers | E08_S04 rules: (1) tool-use ID canonicalization (`toolu_{counter:08d}`); (2) per-session caps. |
| `proof-chain-workflow.md` | Sub-agent prompt authors | E09_S04 2-round pattern: round 1 `cite_neighbors(depth=2)`, round 2 bulk parallel `get_chunk`; closes H7. |
| `retrieval-quality-report.md` | Eval reviewers + go/no-go gatekeepers | E07_S04 nDCG@5 + latency report. **Status: PRELIMINARY** — fixture is empty stub, Tier-1 gate run pending hand-labeling. |
| `snippet-contract.md` | MCP tool implementers | E06_S04 frozen `search_papers` result-row spec: 150-char snippet, no `summary` field, no Citations API integration. |

### `server/prompts.md` (separate; not in `docs/`)

Companion to `server/prompts.py`. E08_S02. Pins four role-prefix
templates (≤50 tokens, injected as user-turn prefix not system prompt),
BP1/BP2 cache breakpoint placement, "Why BP3 was dropped" (closes H2).

Staleness: `retrieval-quality-report.md` is INCOMPLETE — the harness
exists but the curated fixture does not yet, so the report is a stub
that records the harness machinery and waits for a real run. Everything
else in `docs/` is FRESH and authoritative.

---

## 5. `pyproject.toml` + Makefile — propagation candidates

### pyproject.toml (140 lines)

- Project name = `arxmcp`, version `0.1.0`, requires Python ≥ 3.11,
  license MIT. Description: *"Local-first MCP server exposing a
  research-mathematics arXiv corpus to multi-agent Claude pipelines"*.
- Console scripts: `arxmcp-shim = shim.arxmcp_shim:main` (per E06_S02).
  Note: `arxmcp-server` binary referenced in `docs/install.md` is NOT
  declared in `[project.scripts]` — operators currently must run
  `python -m server.main`. The Makefile `make up` target uses this form.
  **Possible doc-vs-code mismatch.**
- Dependencies block contains extensive per-line comments tying each
  dependency to a milestone (e.g., `lancedb`: E04_S01; `kuzu==0.11.3`:
  E09_S01 pinned exactly because upstream archived 2025-10-10;
  `mcp>=1.27,<2`: E06_S01 + spec 2025-06-18; `faiss-cpu`: E08_S03
  Tier-2 semantic-query cache). These comments are excellent
  README-grade material.
- pytest markers: `requires_model` (default-skipped; opt-in via
  `pytest -m requires_model` + per-model env-var like
  `ARXMCP_RUN_REAL_BGE_RERANKER=1`), `eval` (Tier-1→Tier-2 gate).

### Makefile (86 lines)

- Targets: `help`, `bootstrap`, `test`, `eval`, `up`, `ingest`.
- `make help` block (L7–19) is the ground-truth quick-start doc; the
  README's Quick Start is a strict subset.
- `make up` runs `python -m server.main` (NOT `uvicorn` directly — env
  vars only apply via the `__main__` block; called out in critique
  IS3).
- `make ingest` is currently a stub that prints "not yet implemented"
  and exits 1 — production ingestion lands in E11.
- `make eval` comment block (L49–52): "SKIP is NOT a pass for
  promotion — verify the test reports `1 passed`, not `1 skipped`."

---

## 6. Staleness inventory

| Doc | State | Notes |
|---|---|---|
| `README.md` | STALE | Refers to superseded `ROADMAP.md`; "15 epics" wrong; no E02–E09 mention; no `make up` / `arxmcp-shim`. |
| `ROADMAP.md` | SUPERSEDED (self-declared) | Dead links to renamed epic files; old numbering; status column all "not started". |
| `TIER-GATES.md` | FRESH (still authoritative) | Tier-0/1 gates land in current code; Tier-2/5 gates still forward-looking. |
| `.claude/notes/README.md` | FRESH | Reading order still valid. |
| `.claude/notes/01-..05` | FRESH | Design intent unchanged. |
| `.claude/notes/06-..08` | FRESH | Implementations now exist (E06/E08/E13) — design intent unchanged. |
| `.claude/notes/09-feature-priorities.md` | SUPERSEDED (self-declared) | Header L1–11 lists obsolete prescriptions. |
| `.claude/notes/10-..` | FRESH | Reference doc. |
| `.claude/notes/HANDOFF.md` | PARTIAL | Snapshot dated 2026-05-10 captures through E08_S05 but E09 milestones are now `complete`. |
| `.claude/roadmap/README.md` | PARTIAL | Authoritative index; but Status column still "NEW" for shipped E02..E09 epics. |
| `.claude/roadmap/E01-shipped.md` | FRESH (records done state) | — |
| `.claude/roadmap/E02..E09` | FRESH design intent + SHIPPED per state.json | Header still says "NEW". |
| `.claude/roadmap/E10..E14` | FRESH | Unshipped; design intent still applies. |
| `docs/install.md` | FRESH (minor mismatch) | References `arxmcp-server` binary not declared in pyproject. |
| `docs/chunker-fixtures.md` | FRESH | E02_S05 shipped doc. |
| `docs/eval-curation.md` | FRESH | E05_S01 runbook; still load-bearing. |
| `docs/model-policy.md` | FRESH | E08_S05 frozen. |
| `docs/orchestrator-rules.md` | FRESH | E08_S04 frozen. |
| `docs/proof-chain-workflow.md` | FRESH | E09_S04 shipped. |
| `docs/retrieval-quality-report.md` | INCOMPLETE | Awaiting populated fixture; harness landed. |
| `docs/snippet-contract.md` | FRESH | E06_S04 frozen. |
| `server/prompts.md` | FRESH | E08_S02 companion to code. |
| `pyproject.toml` | FRESH | Per-line dep comments are propagation gold. |
| `Makefile` | FRESH | `make help` is canonical quick-start. |

---

## 7. Consolidation recommendations

1. **`ROADMAP.md`**: archive-with-note. Already self-declared SUPERSEDED.
   Two options:
   - Delete + add a 5-line redirect file pointing at
     `.claude/roadmap/README.md`.
   - Move to `.claude/notes/archive/ROADMAP-v1.md` and replace the
     root file with a thin redirect.
   The README's link target at line 18 currently goes to `ROADMAP.md`;
   redirect that to `.claude/roadmap/README.md` in the README rewrite
   regardless.

2. **`TIER-GATES.md`**: keep as-is at repo root. Cited by README
   (line 44), Makefile (L12, L49–52), pyproject (eval marker
   description), and multiple epic specs. Tier-0/1 gates have shipped
   harness but the actual Tier-1 run is still PENDING (per
   `docs/retrieval-quality-report.md`). Tier-2/3/5 gates remain
   forward-looking. The doc is not "done" just because E01–E09 shipped.

3. **`.claude/notes/09-feature-priorities.md`**: keep as historical
   reference (already SUPERSEDED-headed). Multiple milestone bodies
   cite it for Tier-0 design rationale.

4. **`.claude/notes/HANDOFF.md`**: refresh on each major chapter
   close. Either roll forward to a 2026-05-10 post-E09 snapshot or
   move to `.claude/notes/handoffs/HANDOFF-2026-05-10.md` and start
   fresh.

5. **`.claude/roadmap/README.md` Status column**: flip E02..E09 from
   `NEW` to `SHIPPED` based on state.json ground truth. This is a
   small, mechanical edit but high signal for readers.

6. **`README.md`**: full rewrite. Add: shipped epics summary, link
   to `docs/install.md`, link to canonical 7-tool surface, link to
   `docs/` index, drop the "15 epics" claim, fix the ROADMAP link.

7. **Missing `arxmcp-server` console-script**: either add it to
   `[project.scripts]` or fix `docs/install.md` to say `python -m
   server.main` everywhere.

---

## 8. Link targets (from repo root)

Design constitution (`.claude/notes/`):
- `.claude/notes/README.md`
- `.claude/notes/01-mission-and-context.md`
- `.claude/notes/02-architecture-overview.md`
- `.claude/notes/03-ingestion-pipeline.md`
- `.claude/notes/04-parsing-and-chunking.md`
- `.claude/notes/05-storage-and-indexing.md`
- `.claude/notes/06-mcp-server-design.md`
- `.claude/notes/07-multi-agent-caching.md`
- `.claude/notes/08-security-observability-ops.md`
- `.claude/notes/09-feature-priorities.md` (superseded; cite as historical)
- `.claude/notes/10-references-and-prior-art.md`
- `.claude/notes/HANDOFF.md`

Roadmap (`.claude/roadmap/`):
- `.claude/roadmap/README.md`
- `.claude/roadmap/E01-shipped.md`
- `.claude/roadmap/E02-chunker.md`
- `.claude/roadmap/E03-embedder.md`
- `.claude/roadmap/E04-vector-store.md`
- `.claude/roadmap/E05-eval-harness.md`
- `.claude/roadmap/E06-mcp-server.md`
- `.claude/roadmap/E07-hybrid-retrieval.md`
- `.claude/roadmap/E08-agent-runtime.md`
- `.claude/roadmap/E09-citation-graph.md`
- `.claude/roadmap/E10-specialized-indices.md`
- `.claude/roadmap/E11-scale-cutover.md`
- `.claude/roadmap/E12-full-corpus.md`
- `.claude/roadmap/E13-security.md`
- `.claude/roadmap/E14-observability-ops.md`

User/contributor docs (`docs/`):
- `docs/install.md`
- `docs/eval-curation.md`
- `docs/chunker-fixtures.md`
- `docs/snippet-contract.md`
- `docs/orchestrator-rules.md`
- `docs/model-policy.md`
- `docs/proof-chain-workflow.md`
- `docs/retrieval-quality-report.md`

Other:
- `server/prompts.md`
- `TIER-GATES.md`
- `Makefile`
- `pyproject.toml`

---

## 9. Audience layering

**NEW USERS / OPERATORS** (what is this; how do I run it):
- `README.md` (root)
- `docs/install.md`
- `Makefile` (`make help`)
- `.claude/notes/01-mission-and-context.md` (high-level "why")

**AGENTS / IMPLEMENTERS** (design constitution + per-component decisions):
- `.claude/notes/README.md` + `01..10`
- `.claude/roadmap/README.md` + `E01..E14`
- `docs/orchestrator-rules.md`
- `docs/model-policy.md`
- `server/prompts.md`
- `.claude/notes/HANDOFF.md`

**CONTRIBUTORS** (test, gate, ship):
- `TIER-GATES.md`
- `docs/eval-curation.md`
- `docs/chunker-fixtures.md`
- `docs/snippet-contract.md`
- `docs/retrieval-quality-report.md`

**REFERENCE** (internal but agent-required):
- `docs/proof-chain-workflow.md`
- `.claude/notes/10-references-and-prior-art.md`
- `.claude/notes/milestones/<ID>/state.json` (per-milestone ground truth)

---

## 10. Recommended new README TOC

```
# arXMCP

## What it is              (1-paragraph elevator pitch from 01-mission-and-context.md)
## Status                  (E01–E09 shipped; Tier-0 harness landed, Tier-1 fixture pending)
## Quick start             (pipx install → register shim → make up → tools/list)
## Documentation map       (the three layers below)

### For operators
- docs/install.md
- Makefile `make help`
- TIER-GATES.md (what "Tier-0 done" means in this repo)

### For agents and implementers
- .claude/notes/README.md (reading order)
- .claude/roadmap/README.md (epic index + critique-remediation matrix)
- docs/orchestrator-rules.md
- docs/model-policy.md
- server/prompts.md
- docs/snippet-contract.md
- docs/proof-chain-workflow.md

### For contributors
- TIER-GATES.md
- docs/eval-curation.md
- docs/chunker-fixtures.md
- docs/retrieval-quality-report.md (PRELIMINARY)

## Repo layout              (server/, ingest/, shim/, infra/, tools/, tests/, docs/, .claude/)
## Hard constraints         (the 4 invariants from .claude/notes/README.md)
## Tier gates               (one-line + link to TIER-GATES.md)
## License                  (MIT)
```

Drop from current README: the "15 epics, Tier 0 → Tier 7" claim and the
direct link to `ROADMAP.md`. Both should be replaced by a one-line
"see `.claude/roadmap/README.md`" pointer.
