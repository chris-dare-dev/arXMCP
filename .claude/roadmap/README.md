# arXMCP Roadmap (rev 2026-05-20)

This index supersedes `.claude/notes/09-feature-priorities.md` and the old `epic-01-*.md` through `epic-15-*.md` files. The old epic files remain on disk for historical reference but are no longer authoritative. All new milestone work should be tracked against the `E<NN>-<slug>.md` files listed below.

The design constitution remains `.claude/notes/01-mission-and-context.md` through `10-references-and-prior-art.md` — those notes are authoritative for *why*; this roadmap specifies the *how*.

---

## Epics

| ID | Title | Tier | Deps | Status | File |
|---|---|---|---|---|---|
| E01 | Vertical Slice | 0 | — | DONE | [E01-shipped.md](E01-shipped.md) |
| E02 | Chunker | 0 | E01 | SHIPPED | [E02-chunker.md](E02-chunker.md) |
| E03 | Embedder | 0 | E02 | SHIPPED | [E03-embedder.md](E03-embedder.md) |
| E04 | Vector Store | 0 | E02, E03 | SHIPPED | [E04-vector-store.md](E04-vector-store.md) |
| E05 | Eval Harness | 0 | E02, E03, E04 | SHIPPED (harness only; fixture pending) | [E05-eval-harness.md](E05-eval-harness.md) |
| E06 | MCP Server | 1 | E04 | SHIPPED | [E06-mcp-server.md](E06-mcp-server.md) |
| E07 | Hybrid Retrieval | 1 | E04, E06 | SHIPPED | [E07-hybrid-retrieval.md](E07-hybrid-retrieval.md) |
| E08 | Agent Runtime + Caching | 2 | E06, E07 | SHIPPED | [E08-agent-runtime.md](E08-agent-runtime.md) |
| E09 | Citation Graph | 3 | E04, E06, E07, E08 | SHIPPED (closes H7) | [E09-citation-graph.md](E09-citation-graph.md) |
| E10 | Specialized Indices | 4 | E04, E06 | SHIPPED | [E10-specialized-indices.md](E10-specialized-indices.md) |
| E11 | Scale Cutover | 5 | E04, E07, E10 | SHIPPED | [E11-scale-cutover.md](E11-scale-cutover.md) |
| E12 | Full Corpus (folded) | 5 | E11 | SCOPED_OUT | [E12-full-corpus.md](E12-full-corpus.md) |
| E13 | Security Hardening | 5 | E06 | SHIPPED | [E13-security.md](E13-security.md) |
| E14 | Observability & Ops | 5–6 | E06, E08 | SHIPPED (S01–S05) | [E14-observability-ops.md](E14-observability-ops.md) |

> **Ship status sourced from `.claude/notes/milestones/<EXX_SYY>/state.json`.**
> An epic is `SHIPPED` if every milestone under it has `phase: complete`.
> E14 ships with S01–S05 complete; S06 + S09–S12 (Tier-5/6+ follow-ups: deferred-work tracker, Grafana dashboard, ops runbook index, Langfuse docs, API spend metrics) remain unstarted and are tracked here for completeness — they do not gate the v1 ship.
> The per-epic `*.md` files retain `Status: NEW` in their bodies as a
> historical artifact; the table above is the authoritative current
> status. Total tests: 2100 passing, 22 skipped (`requires_model` + offline-only paths), 29 pre-existing Windows-platform failures (`os.getpgid`, POSIX shell, colons-in-filenames, symlinks), 1 xfailed, as of 2026-05-20.

---

## Tier exit gates

These are the authoritative promotion conditions. Each is a machine-checkable command, not a prose aspiration. See `TIER-GATES.md` (created in E05_S03) for the single-source-of-truth document.

| Transition | Gate condition | Defined in |
|---|---|---|
| **Tier-0 → Tier-1** | `pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.70` passes on ANN-only (no BM25, no reranker) | E05_S02, E05_S03 |
| **Tier-1 → Tier-2** | `pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.80` passes with BM25 hybrid + reranker active | E07_S04 |
| **Tier-2 → Tier-3** | E08 caching telemetry healthy: cache hit rate ≥ 30% on a 24-hour production traffic sample | E08 |
| **Tier-5 cutover trigger** | 200K paper backfill complete AND drift watchdog stable (nDCG@5 within 5% of baseline for 7 days) | E11_S05 |

Reranker activation (introduced in E07) is **conditional** on the Tier-1 gate: if nDCG@5 does not reach 0.80 after adding BM25 + reranker, activation is blocked and the retrieval pipeline is debugged before Tier-2 begins.

---

## Scale commitment

The system is designed for 200K papers from day one. The implementation proceeds in tiers:

| Tier | Paper count | Description |
|---|---|---|
| 0 | 50 | math.AG seed corpus; dev + eval baseline |
| 1 | ~500 | Add hybrid BM25; tune retrieval; server hardening |
| 2 | ~5K | Add caching, multi-agent orchestration, telemetry |
| 3 | ~50K | Citation graph, equation index, multi-category |
| 4 | ~200K | Ingestion at scale, GPU embedding, incremental updates |
| 5 | 200K+ | Production cutover; drift watchdog stable |

The Tier-0 → Tier-5 progression is **data backfill + activation**, not re-architecture. The schemas (E04), APIs (E06), and metrics (E05) are defined for 200K from the start.

---

## Critique-remediation matrix

This table records every HIGH and MEDIUM finding from the Phase 3 design critique and maps each to the milestone(s) that close it. It is the definitive audit trail for design changes.

| Issue ID | Description | Closed by milestone(s) |
|---|---|---|
| **H1** | Sonnet planner unjustified → Python regex router | E08_S01 |
| **H2** | BP3 seed cache not stable → DROPPED, BP1+BP2 only | E08_S02, E08_S03 |
| **H3** | Theorem+proof overflows BGE-M3 → dual 512-tok columns | E02_S01, E03_S01, E04_S01 |
| **H4** | Tantivy LaTeX analyzer vapor → Python regex pre-tokenizer + standard BM25 | E02_S03, E04_S04 |
| **H5** | Equation similarity dense-only insufficient → TED + dense fusion | E10_S03 |
| **H6** | `resource_link` not universally followed → inline snippets, agent calls `get_chunk` | E06_S04 |
| **H7** | Cross-paper proof chains unaddressed → `cite_neighbors(depth=2)` + bulk `get_chunk` | E09_S03, E09_S04 |
| **H8** | Voyage cross-model footgun → DROPPED Voyage; BGE-M3 same model for index + query | E03_S01 |
| **H9** | 200 vs 200K scale assumption → Tier-0 dev → Tier-5 prod explicit cutover trigger | E11_S05 |
| **H10** | Verifier pass circular → DROPPED; Lean kernel is the math critic | E08_S05 |
| **MEDIUM** | Symlink atomic swap → LanceDB MVCC via `dataset.checkout(version=N)` | E04_S02 |
| **MEDIUM** | Singleflight + GIL on embedder | E03_S03 |
| **MEDIUM** | `corpus_version` cache invalidation | E04_S03, E08_S03 |
| **MEDIUM** | Tool-use ID canonicalization in orchestrator | E08_S04 |
| **MEDIUM** | 7+ tools tool-block bloat | E06_S03 |
| **MEDIUM** | Snippet + summary duplication | E06_S04 |
| **MEDIUM** | Theorem-name dedup naive | E10_S02 |
| **MEDIUM** | Re-embed cost on version bumps | E11_S03 |
| **MEDIUM** | Contextual retrieval vs preamble overlap | E02_S02 |
| **MEDIUM** | Drift detection / retrieval quality metrics | E05_S02, E11_S04 |
| **MEDIUM** | arXiv 429 backoff; ingestion latency budget | E11_S02 |
| **MEDIUM** | LaTeXML version drift → equation index breaks | E10_S04 |
| **MEDIUM** | Anthropic Citations API doesn't validate MCP results | E06_S04 |
| **MEDIUM** | Sub-agent role-specific system prompts → no cross-role caching | E08_S02 |

---

## Component decisions (decisive)

These decisions are final. Re-opening them requires a formal ADR.

| Component | Decision | Rationale |
|---|---|---|
| **Chunker strategy** | Theorem-aware structural chunking; theorem+proof split into dual 512-tok chunks | Closes H3; enables dual-column ANN; avoids LLM at ingest time |
| **Preamble context** | Deterministic preamble extraction (newcommand, etc.) prepended to embedding input | Closes MEDIUM:contextual-retrieval; preserves BP1 byte-identical caching |
| **Embedding model** | BGE-M3 self-hosted, MIT license, pinned commit SHA | Closes H8; no cross-model footgun; supply-chain safe (Threat 6) |
| **Embedding columns** | Two columns: `embedding_stmt` (≤512 tok) + `embedding_proof` (≤512 tok); `embedding_eq` reserved | Closes H3 structurally |
| **Vector store** | LanceDB; native MVCC via `dataset.checkout(version=N)` | Closes MEDIUM:symlink-swap |
| **BM25** | Python regex pre-tokenizer → `body_tokens` field → standard BM25 (`rank_bm25`) | Closes H4; no fictional Tantivy LaTeX analyzer |
| **Equation index** | Tree-edit distance (Zhang-Shasha / `zss`) over canonical MathML + dense cosine on `embedding_eq` | Closes H5; Sonnet B / E10 |
| **Citation graph** | Kùzu embedded graph; OpenAlex + INSPIRE-HEP; `cite_neighbors(depth=2)` in 2 rounds | Closes H7 |
| **Eval gate** | nDCG@5 ≥ 0.70 ANN-only (Tier-0); ≥ 0.80 hybrid+reranker (Tier-1) | Replaces vibes-check; closes E01_S10 |

---

## Milestone index by ID

Full list of milestones across all authored epics. Sonnet B milestones are listed by ID for cross-reference; their bodies are in their respective epic files (pending).

**E01 (DONE)**
- E01_S01 — Repo skeleton (DONE)
- E01_S02 — Single-paper hand-fetch (DONE)
- E01_S03 — 50-paper seed corpus (DONE)
- E01_S04 — Naive section chunker (SUPERSEDED_BY E02_S01)
- E01_S05 — Stub macro normalizer (SUPERSEDED_BY E02_S02)
- E01_S06 — LanceDB v0 write (SUPERSEDED_BY E04_S01)
- E01_S07 — Seed embed (SUPERSEDED_BY E03_S01 + E03_S02)
- E01_S08 — Server skeleton (SUPERSEDED_BY E06_S01)
- E01_S09 — stdio shim (SUPERSEDED_BY E06_S02)
- E01_S10 — Happy-path demo (SUPERSEDED_BY E05_S03)

**E02 (NEW — Chunker)**
- E02_S01 — Theorem-aware structural chunker (L)
- E02_S02 — Preamble extractor (M)
- E02_S03 — `body_tokens` regex pre-tokenizer (M)
- E02_S04 — Chunker version stamping + content-addressable chunk_id (S)
- E02_S05 — Chunker fixture suite (M)

**E03 (NEW — Embedder)**
- E03_S01 — BGE-M3 dual-column encoder (M)
- E03_S02 — Idempotent re-embed (S)
- E03_S03 — Singleflight wrapper for query encoding (M)

**E04 (NEW — Vector Store)**
- E04_S01 — LanceDB chunks table v1 schema (M)
- E04_S02 — MVCC via `dataset.checkout(version=N)` (M)
- E04_S03 — `corpus_version` marker file (S)
- E04_S04 — BM25 index over `body_tokens` (M)

**E05 (NEW — Eval Harness)**
- E05_S01 — 20 hand-labeled query triples (M)
- E05_S02 — nDCG@5 + Recall@10 test (M)
- E05_S03 — Tier-0 exit gate documentation (S)

**E06 (NEW — MCP Server)**
- E06_S01 — FastAPI server skeleton with Streamable HTTP transport (L)
- E06_S02 — Stdio shim binary (S)
- E06_S03 — Implement all 7 tools (rationalized from 9) (L)
- E06_S04 — Snippet contract: no summary field, no Citations API (M)
- E06_S05 — Security hardening: Origin validation and localhost binding (S)
- E06_S06 — Tool schema byte-stability test (S)

**E07 (NEW — Hybrid Retrieval)**
- E07_S01 — Phase 1: BM25 over `body_tokens` (M)
- E07_S02 — Phase 2: dual-ANN with Reciprocal Rank Fusion (M)
- E07_S03 — Phase 3: BGE-reranker with env-flag gate (M)
- E07_S04 — End-to-end eval: promote nDCG@5 to ≥0.80 (M)

**E08 (NEW — Agent Runtime + Caching)**
- E08_S01 — Query router: Python regex classifier (M)
- E08_S02 — Role-as-user-turn-prefix and BP1/BP2 breakpoint placement (M)
- E08_S03 — MCP-side 3-tier retrieval cache (L)
- E08_S04 — Tool-use ID canonicalization and hard retrieval caps (M)
- E08_S05 — Model selection policy and verifier pass removal (S)

**E09 (NEW — Citation Graph)**
- E09_S01 — Kùzu schema + OpenAlex bulk ingest (L)
- E09_S02 — INSPIRE-HEP enrichment (M)
- E09_S03 — `cite_neighbors()` graph traversal (M)
- E09_S04 — Cross-paper proof chain workflow (M)

**E10 (NEW — Specialized Indices)**
- E10_S01 — Definitions index and `get_definitions` tool (M)
- E10_S02 — Theorem-name index and `find_lemma_by_name` tool (M)
- E10_S03 — Equation index: tree-edit distance fused with dense cosine (L)
- E10_S04 — LaTeXML version drift detector (S)

**E11 (NEW — Scale Cutover)**
- E11_S01 — Academic Torrents seed download and bulk ingest (L)
- E11_S02 — OAI-PMH delta loop (L)
- E11_S03 — Re-embed cost budget and partial re-embed strategy (M)
- E11_S04 — Drift watchdog: per-corpus-version nDCG@5 regression alert (M)
- E11_S05 — Backup/restore runbook and 200K cutover activation (M)

**E12 (SCOPED_OUT — Full Corpus, folded into E11)**
- E12_S01 — SCOPED OUT: content folded into E11_S01–E11_S05

**E13 (NEW — Security Hardening)**
- E13_S01 — Threat-1 audit: paper_id path-traversal coverage across the 7 tools
- E13_S02 — Threat-2 audit: prompt-injection delimiter coverage across the 7 tools
- E13_S03 — Threat-3: LaTeXML sandbox hostile-input validation
- E13_S04 — Threat-4 audit: resource-exhaustion limits across the 7 tools
- E13_S05 — Threat-5 audit: Origin spoofing, DNS-rebinding, and localhost-binding hardening
- E13_S06 — Threat-6: model commit SHA pinning, safetensors-only, and SBOM generation
- E13_S07 — Threat-7 audit: source ingestion TLS pinning and content-length enforcement
- E13_S08 — Tool-result and request-input redaction in structured logs
- E13_S09 — Localhost-only binding regression test
- E13_S10 — Cumulative threat-model coverage review

**E14 (NEW — Observability & Ops)**
- E14_S01 — `/metrics` endpoint: full Prometheus surface
- E14_S02 — OpenTelemetry tracing: one span per JSON-RPC tool call
- E14_S03 — Phoenix integration for retrieval-quality views
- E14_S04 — Daily ops runbook and cron cadence
- E14_S05 — Failure-mode handlers, restic backup, and restore drill
- E14_S06 — DEFERRED WORK TRACKER (Tier 6+): parked items and un-park triggers
- E14_S09 — Cache hit-ratio and latency Grafana dashboard
- E14_S10 — Ops runbook index
- E14_S11 — Langfuse orchestrator-side tracing documentation
- E14_S12 — API spend metrics for hosted-model fallbacks

---

## Live tracks (`plans/<slug>/roadmap.yaml`)

**This section was missing until 2026-08-04.** `CLAUDE.md` §3 names this file as
"the authoritative roadmap index", and `CLAUDE.md` §9 documents that
`/milestone-pipeline` resolves briefs from `plans/<slug>/roadmap.yaml` — but no
index of those live tracks existed anywhere in the repo, so twelve active tracks
were reachable only by knowing to run `ls plans/`. That is a real onboarding hole
for a fresh agent or a fresh clone, and it is why this table exists.

Each row is a `roadmap/1` document consumed directly by
`/milestone-pipeline <milestone-id>`. **This table is hand-maintained and goes
stale** — regenerate it from the source of truth rather than trusting it:

```bash
python - <<'PY'
import yaml, io, glob
for f in sorted(glob.glob('plans/*/roadmap.yaml')):
    d = yaml.safe_load(io.open(f, encoding='utf-8'))
    ms = [i for i in (d.get('items') or []) if i.get('kind') == 'milestone']
    done = [i for i in ms if i.get('status') == 'done']
    print(f"{d['slug']:24s} {d.get('status'):8s} {d.get('phase'):10s} {len(done)}/{len(ms)}")
PY
```

`phase` tracks the *planning* pipeline (`init → refined → decomposed → sequenced
→ complete`); `phase: complete` means the roadmap is fully authored, **not** that
the work shipped. Read the milestone column for delivery.

| Track | Title | Status | Phase | Milestones done |
|---|---|---|---|---|
| [agent-platform](../../plans/agent-platform/roadmap.yaml) | Agent Platform & Protocol — truthful MCP surface, sane budgets | active | complete | 2/8 |
| [data-plane-governance](../../plans/data-plane-governance/roadmap.yaml) | Data-plane governance — boundary ADR, plan dispositions | active | complete | 3/3 |
| [discovery-substrate](../../plans/discovery-substrate/roadmap.yaml) | Discovery substrate — mine the corpus's negatives | active | complete | 0/8 |
| [evidence-engine](../../plans/evidence-engine/roadmap.yaml) | Evidence Engine — end the never-measured era | active | complete | 0/6 |
| [paper-metadata](../../plans/paper-metadata/roadmap.yaml) | get_paper real metadata | active | complete | 2/2 |
| [researcher-workbench](../../plans/researcher-workbench/roadmap.yaml) | Researcher workbench — search, curate, label, export | active | complete | 0/14 |
| [retrieval-unlocks](../../plans/retrieval-unlocks/roadmap.yaml) | arXMCP retrieval unlocks — proofs, equations, definitions | active | complete | 3/13 |
| [scale-ops-hardening](../../plans/scale-ops-hardening/roadmap.yaml) | arXMCP scale, ops & content-security hardening | active | complete | 0/15 |
| [source-truth](../../plans/source-truth/roadmap.yaml) | Source truth — revision registry, spans, license provenance | active | complete | 4/5 |
| [trustworthy-release](../../plans/trustworthy-release/roadmap.yaml) | arXMCP — trustworthy release & adoption | active | complete | 0/13 |
| [**ui-uplift**](../../plans/ui-uplift/roadmap.yaml) | Operator console UI uplift — give `/ui/` an authored visual thesis | active | sequenced | 5/23 |
| [verification-contract](../../plans/verification-contract/roadmap.yaml) | Lean verification contract — honest five-operation trust surface | active | complete | 0/7 |

**`ui-uplift` provenance note:** unlike its siblings it was NOT produced by the
`/roadmap` 4-phase pipeline. It is a transcription of a `/frontend-uplift`
discovery run (`2026q3-ui-uplift`), whose ranked report, adversarial challenge and
five scout briefs live at
[`.claude/notes/frontend-uplifts/2026q3-ui-uplift/`](../notes/frontend-uplifts/2026q3-ui-uplift/).
Its own `generations[0].note` says so; read that before trusting its `phase` field.

---

## Archived standalone tracks (all complete)

Eleven prose track briefs lived under `plans/*.md` until 2026-07-29. `plans/` is
reserved for live `roadmap/1` tracks (`plans/<slug>/roadmap.yaml`), and `CLAUDE.md`
§ 1 permits no other Markdown outside `.claude/` — so they moved here, joining the
standalone briefs already in this directory (`notebook-cutover.md`,
`embedder-truncation.md`, `notebook-preamble-recovery.md`, `notebook-retrieval.md`).

They stay inside `milestone-pipeline-resolve-brief.py`'s legacy-prose glob
(`.claude/roadmap/*.md`), so `/milestone-pipeline <id>` still resolves every
milestone in them — verified after the move.

Every one of these tracks is **complete**; each file carries a header recording
its milestone list and the evidence.

| Track | Milestones complete |
|---|---|
| [corpus-integrity-completion](corpus-integrity-completion-roadmap.md) | 5 |
| [corpus-integrity-observability](corpus-integrity-observability-roadmap.md) | 5 |
| [lean-repl-observability](lean-repl-observability.md) | 1 — see note below |
| [license-serving-removal](license-serving-removal.md) | 1 |
| [notebook-ops-hardening](notebook-ops-hardening-roadmap.md) | 4 |
| [notebook-paper-discovery](notebook-paper-discovery-roadmap.md) | 4 |
| [notebook-surface-expansion](notebook-surface-expansion-roadmap.md) | 7 |
| [proof-verify-handler-wiring](proof-verify-handler-wiring-roadmap.md) | 9 + m5 |
| [textbook-ingest](textbook-ingest-roadmap.md) | 12 |
| [ui-attractive-polish](ui-attractive-polish-roadmap.md) | 5 |
| [verification-feedback](verification-feedback-roadmap.md) | 4 |

Two carry an asterisk:

- **`proof-verify-handler-wiring-m5`** has no `state.json` — it ran as a measurement
  outside the state machine. Its own heading records **COMPLETE 2026-05-21, Verdict
  NO**: hybrid+rerank produced zero P@10 lift, a −10pp top-1 regression, and 122×
  latency. That verdict is the ≥ 0.10-absolute-lift bar `evidence-engine` must clear
  to re-open hybrid.
- **`lean-repl-observability-m1`** reads `rectify-running` in `state.json` even though
  its close-out triple landed (`8844bd4` feat → `101bd4f` rect → `54232e0` finalize).
  The finalize commit committed the state file without flipping the phase. Left
  uncorrected on purpose: it is a concurrent session's artifact. Anything reading
  `state.json` (e.g. `milestone-pipeline-status.sh`) will report it in-flight until
  that session closes it.

Historical artifacts under `.claude/notes/milestones/` still cite the old
`plans/*.md` paths. That is deliberate — they are dated records of where the file
was when they were written, and rewriting them would falsify the record. Only live
documents were repointed.
