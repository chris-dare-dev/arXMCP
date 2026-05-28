# Research Synthesis — notebook-retrieval-m1

**Generated:** 2026-05-28 (post-research-phase)
**Merge mode:** orchestrator (main session), two-brief standard merge + orchestrator decision
**Inputs:** `research-brief-1.md`, `research-brief-2.md`, plus three follow-up
spikes: `spike-accuracy-fork-analysis.md`, `spike-accuracy-by-difficulty-class.md`,
`spike-forkA-futureproofing.md`.

---

## ADDENDUM (2026-05-28) — three accuracy/architecture spikes resolve the open decisions

After the initial synthesis the operator asked two questions, each answered by a
background spike. Both CONFIRM the synthesis's fork-C-for-m1 resolution.

**Spike 1 + 2 — retrieval accuracy (does m1 need the full BM25→ANN→RRF→rerank pipeline?):**
- The live `search_papers` path is **dense-only over `embedding_stmt`**
  (`search.py:481`), explicitly excludes proof chunks (`"excluded_kinds": ["proof"]`,
  `search.py:539`), and `retrieval_mode="dense_only"`. VERIFIED in code.
- The 100-paper spike (`poc.py:172-234`) DID stratify by difficulty. Dense-only scores
  **1.000 top-1 on the adversarial class** (its best); hybrid breaks it to 0.600;
  rerank only partly repairs hybrid's self-inflicted damage. BM25 IDF is non-
  discriminating on a single-topic math corpus; rerank churns (−10pt aggregate,
  122× latency). **m1 SHIPS DENSE-ONLY. Do NOT wire BM25/RRF/rerank — they regress.**
  AC2 is corrected accordingly (see below).
- The genuine depth-discrimination lever the operator correctly intuited is NOT the
  hybrid pipeline — it is the **unused `embedding_proof` column** (the live path
  queries only `embedding_stmt` and drops proof chunks). "Deep treatment" of a topic
  lives in the proof. → filed as a follow-up **dual-column-fusion spike** (contingent
  on verifying the notebooks have proof chunks embedded). Out of scope for m1.

**Spike 3 — Fork A future-proofing:**
- Fork A (`filters.notebook=<slug>`) **IS the correct architectural endpoint** —
  with-the-grain of the planned `filters.source_kind` convention
  (`textbook-ingest-roadmap.md:55`, KR4) and the "one process, many concurrent
  agents" thesis (`02-architecture-overview.md:18-89`). The operator's lean is right
  about the destination.
- BUT build **Fork C now as a deliberately-shaped stepping-stone**, not A directly:
  A is per-request routing on an already-running server, and the server is un-bootable
  today (empty shared corpus). C makes it boot + proves the notebook-open path. C is
  NOT throwaway — slug-validation + path-derivation + open/version-pin/BM25-bind are
  reused verbatim by A; only env-var-as-sole-selector is demoted.
- **Front-load ONE thing into C:** put the notebook-`lancedb_path` derivation in a
  shared helper that A's per-request path will also call (so C→A is additive).
- **Do NOT front-load** the cache-key slug bump / SCHEMA_VERSION change: C's isolation
  is structural (one process = one corpus_version), so the slug component is premature
  until A makes multi-notebook real.

**Net: m1 = Fork C, dense-only, shaped as a stepping-stone to A. Triple-confirmed
(synthesis reasoning + accuracy stratification + fork-future-proofing).**

### AC corrections folded in
- **AC2 (corrected):** "the SAME dense-only retrieval the shared corpus uses
  (single ANN over `embedding_stmt`, proof chunks excluded, `retrieval_mode=
  dense_only`), routed at the notebook's lancedb — NOT a hybrid/rerank pipeline."
- **AC6 (BM25):** reframed to "the notebook's dense ANN uses the notebook's pinned
  corpus_version; BM25 is off the live path so no BM25-version concern for m1."
- **New AC8:** the notebook-`lancedb_path` derivation lives in a shared helper
  (stepping-stone shaping) so Fork A (m2) reuses it without refactor.

---

## TL;DR + the decision the operator must confirm

The two researchers split on the selection mechanism (fork 1), and BOTH
independently flagged that **the server cannot start today** — the shared
corpus `var/arxmcp/index/lancedb` has no `corpus-version.json`, so
`Resources.startup` raises `CorpusNotIngestedError`. This makes **AC4
("no-notebook query = shared-corpus byte-identical") literally
unsatisfiable** and turns fork 1 into a genuine product decision, not a
code-only one.

**Orchestrator resolution: fork (C) `ARXMCP_NOTEBOOK=<slug>` env var for
m1; fork (A) `filters.notebook=<slug>` deferred to m2.** Reasoning below.
This is surfaced to the operator before implementation because it commits
to a "one server instance = one notebook" operator model and reframes AC4.

---

## Fork 1 — selection mechanism (the central decision)

Both briefs verified the same load-bearing fact (verbatim, `server/handlers/search.py:303-313`):

```python
filters: Annotated[
    dict[str, Any] | None,
    Field(description=("Optional filters. Honors 'paper_id' ...")),
] = None,
```

`filters` is a free-form `dict[str, Any] | None` → adding a `notebook` key
is INVISIBLE to the FastMCP-derived `inputSchema` → **no
`EXPECTED_TOOL_SCHEMA_SHA256` re-pin for EITHER fork** (provided the Field
description string is left unchanged — R1's caveat). So BP1 is NOT the
deciding factor.

| | R1 → fork (C) env var | R2 → fork (A) filters.notebook |
|---|---|---|
| Server startability | **Makes the server startable** (points `lancedb_path` at a populated notebook lancedb) | Presupposes a running server — which requires a startable corpus, i.e. fork (C) or a populated shared corpus first |
| Surface | `Config` +1 field, `Resources.startup` conditional path. ~2 files. | Per-notebook `NotebookResources` cache + `asyncio.Lock` + cache-key slug component + **`cache_sqlite.SCHEMA_VERSION` bump** + handler routing. ~4 files. |
| Cache isolation | Automatic — one server = one corpus_version = one cache | Requires injecting `notebook_slug` into the Tier-1 key (the guaranteed-collision fix) |
| Multi-notebook | One notebook per server instance (relaunch to switch) | Any notebook per call from one server |
| Matches textbook-ingest roadmap's planned `filters.source_kind` convention | No | **Yes** (R2's strongest point) |

**Decision: fork (C) for m1.** The dispositive fact is R1's: **fork (A)
logically requires fork (C) (or a populated shared corpus) to exist first**,
because the server can't boot against the empty shared corpus and fork (A)
is per-request routing on an already-running server. You cannot route
per-call to notebooks if the process won't start. Fork (C) is the minimal
change that (1) makes the server boot, (2) serves a notebook end-to-end,
(3) needs no cache-key refactor / SCHEMA_VERSION bump, (4) is a clean single
milestone. Fork (A) — multi-notebook per-call routing + the cache-key slug
isolation R2 correctly insists on — becomes **m2**, layered on top, where
the env-var notebook becomes the default and `filters.notebook` the
per-call override. The two compose; they are not mutually exclusive.

R2's textbook-roadmap-convention argument is valid and is exactly why
fork (A) is the RIGHT m2 — but m1's job is to make ONE notebook queryable
at all, and fork (C) does that with the least risk.

## AC4 reframe (both briefs flagged it as unsatisfiable)

Original AC4: "no notebook selection → shared-corpus byte-identical, no
regression." The shared corpus is empty; the server can't start against it.

**Reframed AC4:** "With `ARXMCP_NOTEBOOK` UNSET, the server's startup
behavior is byte-identical to today — i.e., it attempts the shared corpus
and raises `CorpusNotIngestedError` exactly as it does now. No new code path
alters the default (shared-corpus) behavior." This preserves the
no-regression intent without requiring the impossible (a non-empty shared
corpus). The env-var-absent path is untouched.

## Confirmed facts (both briefs agree, verbatim citations)

- **Shared corpus empty:** `var/arxmcp/index/lancedb/corpus-version.json`
  NOT FOUND → `read_corpus_version` → None → `CorpusNotIngestedError`
  (`server/resources.py:282+`). Server un-startable on default config.
- **Notebook lancedbs are startable:** bridgeland-stability
  `corpus_version=369`, shimura-varieties `corpus_version=49`; both have
  `corpus-version.json` + `chunks.lance`.
- **BM25 is global + version-keyed** (`ingest/bm25_indexer.py:108-114`,
  `BM25_INDEX_ROOT/v<N>`). `v369` and `v49` already exist — a notebook
  `BM25Phase.startup(notebook_lancedb_path, notebook_version)` loads them
  without rebuild (AC6 satisfied by construction for fork C).
- **Cache key lacks a slug** (`server/cache_sqlite.py` `derive_tier1_key`:
  `query, filters, k, corpus_version, level`). Under fork (C) this is
  harmless (each server = one corpus_version); under fork (A) it is a
  guaranteed-collision bug requiring the slug component (deferred to m2).
- **Delimiter wrapping is notebook-agnostic** (`server/handlers/search.py`
  `_snippet` wraps every result in `<retrieved_chunk>` regardless of
  source) → Threat-2 covered for notebook results with no extra work.
- **Embedder is a process-wide singleton** (`server/query_encoder.py`) —
  do NOT open a second BGE-M3; only the LanceDB handle + BM25Phase +
  ANNPhase are notebook-specific.

## Implementation plan (fork C — if operator green-lights)

INLINE. ~2-3 files + tests.

1. **`server/config.py`**: add `notebook: str | None = None` sourced from
   `ARXMCP_NOTEBOOK` env. When set, validate via `tools._notebook_common.validate_slug`
   (Threat 1) and derive the effective `lancedb_path` =
   `var/arxmcp/notebooks/<slug>/lancedb` BEFORE `Resources.startup` reads it.
   (R1 open-q 2: the substitution must happen before `read_corpus_version`.)
2. **`server/resources.py`** (or config): the `lancedb_path` derivation is
   the only change; `Resources.startup` is otherwise unchanged — it opens
   whatever `config.lancedb_path` resolves to, gets the notebook's
   corpus_version, and binds BM25Phase at that version.
3. **AC5 (missing/empty notebook):** if `ARXMCP_NOTEBOOK` points at a
   non-existent notebook or one without `corpus-version.json`, raise a
   clear typed config error at startup (not a 500 mid-query) with a
   remediation message.
4. **Tests:** synthetic notebook fixture (a tmp lancedb with
   corpus-version.json + a tiny chunks table) — AC1 routing (query opens
   the notebook path, not the shared), AC4 (env unset → unchanged
   startup), AC5 (bad slug / missing notebook → clean error), slug
   path-traversal rejection. Use the existing `requires_model` marker
   conventions: the model-dependent end-to-end query is a `requires_model`
   test; the path-routing + config tests are synthetic / no-model.
5. **Docs (AC7):** `.claude/notes/06-mcp-server-design.md` — document the
   `ARXMCP_NOTEBOOK` notebook-scoping mode; `docs/install.md` operator note
   (`ARXMCP_NOTEBOOK=bridgeland-stability make up`).

## Open questions (consolidated)

1. **AC4 / startup mode** — resolved by the reframe above (env-unset path
   unchanged). No further blocker.
2. **AC1 test strategy** — synthetic fixture preferred (no `requires_model`
   gate) for the routing assertion; a `requires_model` end-to-end test can
   assert `0705.3794` surfaces. Implementer picks; synthetic is the CI gate.
3. **BM25 auto-build** — for fork (C), `BM25Phase.startup` finds the
   existing `v369`/`v49` artifact; no rebuild. Confirm with `ls var/arxmcp/index/bm25/`.

## External writes the implementation will require

None — local server code + tests. No git push / PR / infra / API.

## Orchestrator synthesis note

The fork-1 split was the key output. Resolved to (C) on the dispositive
startability argument (R1), NOT by averaging — fork (A) is a strict
superset that presupposes (C)'s precondition (a bootable server). R2's
cache-contamination finding and textbook-roadmap-convention argument are
adopted as the SCOPE of m2 (per-call notebook routing + cache-key slug
isolation). Both briefs independently surfaced the empty-shared-corpus /
AC4 conflict — that, plus the one-notebook-per-server operator-model
commitment fork (C) implies, is why the pipeline pauses for an operator
go/no-go before implementation.

**This is m1 = single shippable milestone (no /roadmap decomposition
needed for fork C).** Fork (A) is a clean future m2.
