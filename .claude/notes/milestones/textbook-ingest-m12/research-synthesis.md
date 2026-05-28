# Research Synthesis — textbook-ingest-m12

**Orchestrator merge of research-brief-1 + research-brief-2.** Strong agreement on the core (fork (b)); three divergences resolved below.

## What m12 is

A new `tools/notebook_textbook_ingest.py` CLI driver that embeds m7 textbook chunks and writes them into a notebook's LanceDB, making textbook chunks retrievable via `search_papers`. Closes the e4 OUTCOME end-to-end and the follow-up tracked at **chris-dare-dev/arXMCP#8**. Ingest-only — NO `server/` changes, NO MCP tool-schema/BP1 re-pin.

## The embed-source fork: RESOLVED → fork (b), via the embed_equations precedent

Both briefs independently chose **fork (b)**: embed `chunk_textbook`'s `ChunkRecord`s DIRECTLY (no global-store NPZ round-trip, no `embed_paper` refactor). The decisive evidence: **`ingest/embed_equations.py:31` ALREADY does `from ingest.embedder import EMBED_BATCH_DEFAULT, _encode_batch`** and calls the low-level batched encoder directly rather than going through `embed_paper`. So importing the embedder's lower-level primitives is an ESTABLISHED intra-codebase pattern — not a layering violation. Fork (a) (teaching `embed_paper`/`_load_chunks` a notebook-scoped source) would refactor a core module for no benefit; rejected.

**Entrypoints to reuse (verbatim, do NOT duplicate):**
- `_build_embed_input(preamble_text, body_text) -> str` (`ingest/embedder.py:371`) — NFC-normalize + concat. Textbook `preamble_text=""` is PERMANENT (m8 OQ-1; MinerU expands math at render time, no author macros).
- `_encode_batch(texts, chunk_ids=None) -> (np.ndarray float32 (N,1024) L2-normed, truncated_count)` (`ingest/embedder.py:396`) — the ONLY model-touching entrypoint; the canonical L2-normalized BGE-M3 encoder.
- Routing rule (`ingest/embedder.py:1028`): `"embedding_proof" if kind == "proof" else "embedding_stmt"`. **IMPORT/apply the rule from the single source — never copy the string (FM-1).** Mirror the split-after-batch pattern in `_embed_paper_impl` (lines ~1020-1081).
- `EmbedRecord` (`ingest/schema.py`): `{chunk_ids_stmt, embedding_stmt, chunk_ids_proof, embedding_proof, embedder_version}`; `__post_init__` validates L2 norms (atol 1e-3), no dup, no cross-list overlap. `embedder_version = EMBEDDER_VERSION`.
- `write_chunks(chunks, embeddings, lancedb_path=...)` (`ingest/store.py`) — MVCC upsert (`merge_insert("chunk_id")`, idempotent) + writes `corpus-version.json`. **Returns the post-index version int.**
- `tools/_notebook_common.py`: `notebook_dir(slug)` (validate_slug + symlink rejection, Threat 1) + `notebook_lancedb_path(slug)` → `var/arxmcp/notebooks/<slug>/lancedb`.

## Driver shape

```
uv run python tools/notebook_textbook_ingest.py <slug> [--paper-id ID ...] [--batch-size N] [--dry-run]
```
- `slug` required (validate via `notebook_dir`/`validate_slug`).
- `--paper-id` repeatable; **if omitted, ENUMERATE all paper_ids from `nb_dir/chunks/*` subdirs** (no `papers.txt` dependency for the textbook path — resolves brief-2 OQ-1; handles multi-volume textbooks).
- **One-pass** (resolves brief-2 OQ-2): the driver CALLS `chunk_textbook(slug, paper_id)` directly (chunk → embed → write), NOT reading pre-written JSONs. If HTML is missing, `chunk_textbook` logs a failure row + returns `[]`; the driver surfaces a non-zero exit (mirror `notebook_ingest.py::run()`).
- Per paper: `chunks = chunk_textbook(slug, paper_id)` → `embed_record = _build_embed_record(chunks, batch_size, _encoder=_encode_batch)` → `write_chunks(chunks, embed_record, lancedb_path=notebook_lancedb_path(slug))`.
- `_build_embed_record(chunks, batch_size, *, _encoder=_encode_batch)` — the model-free seam: tests inject a synthetic `_encoder`; the real path is `@pytest.mark.requires_model`.

## Resolved divergences (orchestrator decisions)

**D1 — BM25: SKIP it.** brief-1 says skip (notebook retrieval is dense-only at v1 — notebook-retrieval-m2 AC2 locks `retrieval_mode="dense_only"` over `embedding_stmt`); brief-2 says build it (to pre-empt the cross-notebook BM25 version-collision bug). **DECISION: SKIP.** Reasoning: (a) the e4 AC only needs the DENSE path (`search_papers` + `filters.source_kind=textbook`), which both briefs confirm is sufficient; (b) notebook retrieval is dense-only by design (m2 AC2), so a notebook BM25 index would be DEAD CODE — never consulted; (c) brief-2's collision concern is *introduced by building BM25* — skipping it sidesteps the risk entirely rather than managing it; (d) YAGNI — when hybrid notebook retrieval lands, the BM25 build (with the `.notebook_slug` sentinel) belongs in that milestone. Document the skip with a cite to notebook-retrieval-m2 AC2.

**D2 — corpus-version marker hardcodes arXiv `CHUNKER_VERSION`.** `write_chunks` (store.py:904) writes `chunker_version="v1.1"` into the notebook `corpus-version.json` even for textbook chunks (whose real version is `TEXTBOOK_CHUNKER_VERSION="tv0.1"`). **DECISION: accept as a cosmetic/observability inaccuracy with an explicit code comment; do NOT modify `store.py` (out of scope, would need its own test surface).** The FUNCTIONAL part (the integer `corpus_version` for MVCC pinning) is correct; the `chunker_version` string field is observability metadata only, and with BM25 skipped (D1) the version-gating reader isn't exercised. *If* `write_corpus_version_marker` is cleanly importable, the driver MAY rewrite the marker with `TEXTBOOK_CHUNKER_VERSION` after `write_chunks` as a tidy driver-level correction — implementer's call, lean minimal/commented.

**D3 — CLI shape.** Adopt brief-1's flexible shape (`slug` + optional `--paper-id`, enumerate `chunks/` when omitted) — a superset of brief-2's slug-only enumerate-all default.

## Failure modes the implementation MUST guard (brief-2)

- **FM-1 (routing drift):** apply the proof/stmt routing rule from the IMPORTED single source, never a copied string. `EmbedRecord.__post_init__` does NOT catch a wrong-column placement (only dup/overlap) — so the integration test must assert the textbook chunk retrieves via the DENSE `embedding_stmt` path (the real backstop).
- **FM-3 (corpus pollution — high impact):** the driver MUST ALWAYS pass `lancedb_path=notebook_lancedb_path(slug)` — NEVER the default `DEFAULT_LANCEDB_PATH`. A test must assert the textbook chunks landed in the notebook LanceDB AND that the global corpus path received NO write.
- **FM-4 (m9 prefix invariant):** pass `chunk_textbook`'s `ChunkRecord`s to `write_chunks` UNMODIFIED (`textbook:` chunk_id + `source_kind="textbook"` already agree). Do NOT call `ingest/chunker.py::_compute_chunk_id` (hardcodes `arxiv:`).
- **FM-5 (model leak in tests):** monkeypatch/inject `_encode_batch` (the only model-touching fn) — the write+retrieve integration test must run model-free (mirror `tests/test_embed_equations.py`). Real-embed path `@pytest.mark.requires_model`.
- **FM-7 (body_tokens None):** `write_chunks` raises if `body_tokens is None`. Confirm `chunk_textbook` populates it (it calls `tokenize_body`); a test with a minimal body should verify.

## Implementation path
INLINE — ~150-250 LOC, ~2-3 files (`tools/notebook_textbook_ingest.py` new + `tests/test_notebook_textbook_ingest.py` new + maybe a doc note), no novel architecture (mirrors `tools/notebook_ingest.py` + the `embed_equations.py` encode precedent), no `server/`/`ingest/` core edits.

## Acceptance criteria → plan
- `tools/notebook_textbook_ingest.py`: slug [+paper-ids] → chunk_textbook → embed (fork b) → `write_chunks(lancedb_path=notebook)`. ✔
- **MODEL-FREE integration test (the payoff/e4-demo guard):** synthetic embeddings → write to a tmp notebook LanceDB → `search_papers` against that notebook (`filters.notebook=<slug>` or `ARXMCP_NOTEBOOK`) with `filters.source_kind="textbook"` → assert the textbook chunk returns (dense path). ✔
- idempotent re-run (merge_insert). ✔
- FM-3 guard: global corpus untouched. ✔
- reuse BGE-M3 embedder (no duplicated routing); real path `requires_model`-gated. ✔
- per-notebook corpus_version handled (D2). ✔
- NO tool-schema/BP1 re-pin. ✔ (ingest-only)

## Orchestrator synthesis note
Core (fork b via `_encode_batch`/`_build_embed_input`, the `embed_equations.py` precedent) was unanimous. Resolved: D1 (skip BM25 — dense-only design + sidesteps the collision risk), D2 (accept the cosmetic chunker_version marker inaccuracy, commented), D3 (flexible CLI). The two highest-impact correctness guards are FM-1 (routing single-source) and FM-3 (never write the global corpus path).

## Open questions
None blocking. D1-D3 resolve the only design choices; brief-2 OQ-1/OQ-2 resolved (enumerate chunks/ dir; one-pass).

## External writes the implementation will require
| type | target | why |
|---|---|---|
| `git push` | `origin main` | ship the feat→rect→chore triple |
| `gh issue close` | `chris-dare-dev/arXMCP#8` | this milestone closes the tracked follow-up |

Both are Phase-4 main-thread, per-event-authorized. The driver itself is purely local.
