# Changes

Epic-grain changelog. Per-milestone detail is in
[`.claude/notes/milestones/<EXX_SYY>/`](.claude/notes/milestones/) (each has
a research synthesis, implementation summary, critique-merged, and
state.json). Per-commit detail is in `git log`.

This file groups changes by **epic** rather than version because arXMCP is
not yet versioned beyond `0.1.0`. The next semver bump will land with the
production cutover (E11).

---

## Unreleased

### 2026-05-21 — `proof-verify` handler-wiring (m1 + m2): `paper_id` filter goes live in `search_papers`

The downstream `/proof-verify` per-notebook pipeline can now scope a
`search_papers` call to a specific arXiv paper id, and the response echoes
back which filter was actually honored. The hybrid + rerank pipeline
modules (E07) remain unwired pending a 100-paper curated fixture proving
measurable lift; only the cheap filter-wiring half of the pivot has landed.

- **m1** — `search_papers` now honors `filters={"paper_id": "<id>"}` (or a
  list of ids) end-to-end. The string form is canonicalized to a sorted
  one-element list before predicate construction so a single-id call and
  a list-of-one call share a cache key (F4 from m1 critique). Predicates
  are built with `LanceDB.where(predicate, prefilter=True)` and combined
  with the BGE-M3 ANN search; unsupported filter keys are surfaced in
  `filter_warnings` with per-key strings and capped via
  `MAX_FILTER_KEY_LEN=64` so a malicious key cannot blow the response
  envelope (F2 from m1 critique). The `paper_id` value list is capped at
  `MAX_PAPER_ID_FILTER_ITEMS=100` and SQL-escaped via single-quote
  doubling. Trailing-newline rejection in `is_valid_paper_id` (and the
  parity copy in `ingest/chunker.py` + `tools/validate_eval_fixtures.py`)
  was hardened by replacing the regex `$` anchor with `\Z` (F3 from m1
  critique).
- **m2** — Filtered responses now carry a `filters_applied` object that
  echoes the canonical form of every key actually honored (currently just
  `paper_id`). The field is absent — not null — when no filter was passed,
  preserving byte-stability for the no-filter cache hit. The echo is
  scoped to `SUPPORTED_FILTER_KEYS`; unsupported keys remain in
  `filter_warnings` and never appear in the echo (a regression guard
  pinned by `TestFiltersAppliedHelper.test_unsupported_filter_keys_are_dropped`).
  Schema bumped v8→v9; `TOOL_SCHEMA_VERSION` bumped 8→9; the
  `tools/list` byte-hash and BP1 prompt-cache breakpoint were re-pinned
  in lockstep.
- **Out of scope (deferred):** The wider `degraded` / `degraded_reasons`
  schema-vs-runtime gap surfaced during m2 research is tracked as a
  future milestone; m2 deliberately did not widen scope. The hybrid +
  rerank wiring (m4 / m5) is gated on the 100-paper curated fixture
  proving measurable lift; the 2026-05-20 spike found dense-only already
  returns the right paper at top-1 on the 22-paper math.AG notebook.

### 2026-05-10 — Doc-layout consolidation

- Restricted root-of-repo Markdown to five files only: `README.md`,
  `CLAUDE.md`, `CHANGES.md`, `SECURITY.md`, `OWNERS.md`.
- Moved `TIER-GATES.md` from repo root to `.claude/TIER-GATES.md`.
- Moved `server/prompts.md` to `.claude/notes/prompts-bp-discipline.md`.
- Moved 7 internal-reference docs from `docs/` to `.claude/docs/`:
  `chunker-fixtures.md`, `eval-curation.md`, `model-policy.md`,
  `orchestrator-rules.md`, `proof-chain-workflow.md`,
  `retrieval-quality-report.md`, `snippet-contract.md`. Only
  `docs/install.md` (operator-facing) remains under `docs/`.
- Deleted `ROADMAP.md` (was a self-superseded redirect; the authoritative
  roadmap lives at `.claude/roadmap/README.md`).
- Updated test path constants in `tests/test_proof_chain.py`,
  `tests/test_snippet_contract.py`, `tests/test_model_selector.py`,
  `tests/test_prompts.py`, and `tests/test_tier_gates_doc.py` for the
  new locations. Dropped the `TestReadmeLinksTierGates` AC since
  TIER-GATES is no longer user-facing.
- Updated `Makefile` and `tools/validate_eval_fixtures.py` references.
- README rewritten to project scope only (what / how / layout); CLAUDE.md
  expanded with the new doc-placement rule and updated paths.
- New: `CHANGES.md`, `SECURITY.md`, `OWNERS.md`.

---

## E09 — Citation Graph (2026-05-10, SHIPPED — closes H7)

The agent runtime can now traverse the citation graph in 2 MCP rounds.

- **E09_S01** — Kùzu schema v1 + OpenAlex bulk citation ingest.
  Embedded graph at `var/arxmcp/index/kuzu/`; `kuzu==0.11.3` pinned
  exactly (upstream archived 2025-10-10). Two-pass resolution +
  citation; idempotent MERGE upserts; polite-pool User-Agent +
  `?mailto=`; atomic-write checkpoint; fetch-failure tracking;
  `oa_work_id` collision detection.
- **E09_S02** — INSPIRE-HEP per-paper enrichment (hep-th / math-ph).
  Schema bumped to v2 (`doi` / `journal_ref` / `inspire_id` columns).
  Split-writer pattern closes F4 from E09_S01 (OpenAlex owns prose;
  INSPIRE owns identifiers + bibliographic refs).
  COALESCE-in-ON-MATCH so a re-MERGE with NULL doesn't clobber
  previously stamped data.
- **E09_S03** — `server/graph_queries.py::cite_neighbors(chunk_id,
  depth, direction)` async library + `CitationNeighbor` dataclass.
  Variable-length Cypher with `relationships(p)` projection;
  Python-side dedup + filter + ordering; LanceDB batched chunk-id
  lookup with `kind="stmt"` priority fallback. Intra-paper `\ref{}`
  ingest pass (`ingest/intra_paper_refs.py`) populates
  `source="intra-paper"` self-edges.
- **E09_S04** — Documents and tests the 2-round agent pattern
  (`cite_neighbors` + bulk parallel `get_chunk`). Synthetic 50-paper
  graph perf gate: ≤500 ms for `depth=2`. Closes **H7**.

---

## E08 — Agent Runtime + Caching (SHIPPED)

- **E08_S01** — Python regex query router → 4 RouteTags
  (`LOOKUP`, `SYNTHESIS`, `VERIFICATION`, `AUTOFORMALIZATION`). Closes H1
  (no Sonnet planner).
- **E08_S02** — Role-as-user-turn-prefix; BP1+BP2 prompt-cache
  breakpoint placement; BP3 dropped (closes H2). Role prefixes ≤50
  tokens; closed-at-four-roles invariant.
- **E08_S03** — 3-tier MCP-side retrieval cache: SQLite exact memo +
  FAISS semantic-query memo + LRU rerank-set memo. Prometheus
  metrics; corpus-version keyed; fall-through-on-failure discipline.
- **E08_S04** — Tool-use ID canonicalization (`toolu_{counter:08d}`)
  + per-`Mcp-Session-Id` retrieval caps (3 search + 4 chunk).
- **E08_S05** — Model-selection policy: Haiku/Sonnet only, Opus
  forbidden in `server/` source. Verifier pass dropped (closes H10).

---

## E07 — Hybrid Retrieval (SHIPPED)

- **E07_S01** — Phase-1 BM25 over `body_tokens`.
- **E07_S02** — Phase-2 dual-ANN (`embedding_stmt` + `embedding_proof`) + RRF.
- **E07_S03** — Phase-3 BGE-reranker-v2-m3 cross-encoder, env-gated.
- **E07_S04** — End-to-end hybrid eval target nDCG@5 ≥ 0.80 (gate run
  pending fixture curation).

---

## E06 — MCP Server (SHIPPED)

- **E06_S01** — FastAPI + Streamable HTTP at `/mcp`; loopback bind;
  pure-ASGI middleware; `BodySizeCapMiddleware`; eager BGE-M3 startup.
- **E06_S02** — `arxmcp-shim` stdio↔HTTP bridge for Claude Code;
  byte-pass-through; loopback-only egress.
- **E06_S03** — 7 MCP tools registered (`search_papers`, `get_chunk`,
  `find_equation`, `get_definitions`, `find_lemma_by_name`,
  `get_paper`, `cite_neighbors`).
- **E06_S04** — 150-char snippet contract for `search_papers` rows;
  no summary field; no Citations API dependency.
- **E06_S05** — Origin validation, host validation, security headers,
  body-size caps.
- **E06_S06** — `tools/list` byte-stability test (closes BP1
  prompt-cache invariant at the wire).

---

## E05 — Eval Harness (SHIPPED; fixture curation pending)

- **E05_S01** — 20 hand-labeled `(query, chunk_id, relevance)` triples
  (fixture stub committed; curation per
  [`.claude/docs/eval-curation.md`](.claude/docs/eval-curation.md)).
- **E05_S02** — nDCG@5 + Recall@10 pytest harness with `--ndcg-min` flag.
- **E05_S03** — Tier-0 / Tier-1 gate documentation (now
  [`.claude/TIER-GATES.md`](.claude/TIER-GATES.md)).

---

## E04 — Vector Store (SHIPPED)

- **E04_S01** — LanceDB `chunks` v1 schema (dual `embedding_stmt` +
  `embedding_proof`; `embedding_eq` reserved); HNSW + scalar indices;
  idempotent `merge_insert(on="chunk_id")`.
- **E04_S02** — MVCC via `dataset.checkout(version=N)`. Closes the
  symlink-atomic-swap MEDIUM finding.
- **E04_S03** — `corpus_version` marker file + reader cache key.
- **E04_S04** — BM25 index over `body_tokens` (closes H4 — no fictional
  Tantivy LaTeX analyzer).

---

## E03 — Embedder (SHIPPED)

- **E03_S01** — BGE-M3 dual-column encoder; pinned commit SHA;
  `trust_remote_code=False`; safetensors-only (Threat 6 closure).
- **E03_S02** — Idempotent re-embed.
- **E03_S03** — Singleflight wrapper for query encoding (closes the
  GIL-on-embedder MEDIUM finding).

---

## E02 — Chunker (SHIPPED)

- **E02_S01** — Theorem-aware structural chunker; dual 512-token
  statement + proof chunks (closes H3).
- **E02_S02** — Per-paper preamble macro extractor.
- **E02_S03** — `body_tokens` regex pre-tokenizer.
- **E02_S04** — Chunker version stamping + content-addressable
  `chunk_id` (`arxiv:<paper_id>:<sha256[:16]>`).
- **E02_S05** — Chunker fixture suite + regeneration runbook
  ([`.claude/docs/chunker-fixtures.md`](.claude/docs/chunker-fixtures.md)).

---

## E01 — Vertical Slice (DONE)

- Repo skeleton + 50-paper math.AG seed corpus
  (`tools/seed-papers.txt`) + single-paper hand-fetch
  (`tools/fetch_one_paper.py`) + seed-corpus walk
  (`tools/fetch_seed.py`). Per-milestone subspecs (S04–S10) were
  superseded by E02–E06 milestones and are recorded as
  `SUPERSEDED_BY` in
  [`.claude/roadmap/README.md`](.claude/roadmap/README.md).

---

## Pending epics

E10 (specialized indices: equation TED, FTS5 theorem-name index),
E11 (scale cutover: production ingest driver, 200K backfill),
E13 (security audit), E14 (observability/ops). E12 scoped-out
(folded into E11). See [`.claude/roadmap/README.md`](.claude/roadmap/README.md)
for current status.
