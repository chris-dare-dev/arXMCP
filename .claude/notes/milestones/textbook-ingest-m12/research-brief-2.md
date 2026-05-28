# Research Brief — textbook-ingest-m12

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-28T20:10:00Z

---

## In-codebase context

### Design notes that apply

- `07-multi-agent-caching.md`: BP1 discipline — `EXPECTED_TOOL_SCHEMA_SHA256` must not
  change unless MCP tool definitions change. This milestone adds an ingest CLI tool,
  NOT an MCP tool. No re-pin expected. However: `write_chunks` writes
  `corpus-version.json` which the server reads at startup; the notebook corpus_version
  must be an integer that the server's `Resources.notebook_table` + `open_chunks_table`
  can consume correctly.
- `08-security-observability-ops.md` §Threat 1: "Path traversal via paper_id — strict
  regex on every arxiv ID input." Textbook paper_ids (form `textbook:<slug>`) must go
  through `_validate_paper_id` before any filesystem path construction.
- `08-security-observability-ops.md` §Threat 6: "Pin model commit SHAs in configuration
  (`BAAI/bge-m3@<sha>`), not just names. Use safetensors format only." The embedder
  already enforces this via `BGE_M3_COMMIT_SHA` + `validate_model_revision`.

### Key codebase contracts (verbatim)

From `ingest/embedder.py` line 1028 (routing rule):
> `routing.append("embedding_proof" if kind == "proof" else "embedding_stmt")`

From `ingest/store.py` `_build_arrow_table` (m9 prefix invariant, lines 469-479):
> ```
> expected_prefix = f"{chunk.source_kind}:"
> if not chunk.chunk_id.startswith(expected_prefix):
>     raise ValueError(...)
> ```
> "`arxiv:` ⇔ 'arxiv'; `textbook:` ⇔ 'textbook'."

From `ingest/schema.py` `EmbedRecord.__post_init__` (cross-list overlap guard):
> "Each chunk_id must appear in exactly one of the two lists (never both —
> the embedder's routing rule is exclusive)."

From `ingest/textbook_chunker.py` module docstring (line 43):
> "Writes chunk JSONs only — NOT LanceDB. Embedding/LanceDB-write is a downstream step."

From `ingest/embed_equations.py` (precedent for direct `_encode_batch` reuse):
> `from ingest.embedder import EMBED_BATCH_DEFAULT, _encode_batch`
> "Reuses the chunks-embedder batch path. `_encode_batch` is the canonical L2-normalized
> BGE-M3 batched encoder; we import and call it directly rather than reimplementing
> the model lifecycle."

From `ingest/embedder.py` `_build_embed_input` (lines 371-388):
> "Returns the NFC-normalized `preamble + "\n\n" + body_text` view. F3 fallback: when
> the per-paper preamble is missing, `preamble_text` is `""` and the embedder encodes
> `body_text` alone."

From `ingest/embedder.py` (textbook preamble permanent decision):
> Textbook `preamble_text=""` is PERMANENT. MinerU emits math already expanded at
> PDF-render level; there are no author macros to inherit.

### Notebook serving path

`server/resources.py::Resources.notebook_table(slug)` opens
`var/arxmcp/notebooks/<slug>/lancedb` (reads `corpus-version.json` from that dir).
`server/handlers/search.py` calls `r.notebook_table(notebook_slug)` when
`filters['notebook']` is present (m2 fork-A), or uses `ARXMCP_NOTEBOOK` env var
(process-level fork-C). The integration test can use either route to drive
`search_papers` against the notebook LanceDB.

### BM25 question resolved

`search_papers` is dense-only at v1. `notebook_ingest.py` builds BM25 because
`run_bulk_ingest` writes arXiv chunks that DO have a BM25 path. For the textbook
driver, the hybrid BM25 path in `server/retrieval/bm25.py` DOES support textbook
chunks (m9 shipped `_source_kind_from_chunk_id` there). However: the e4 AC only
requires `search_papers` with `filters.source_kind=textbook` to return the chunk —
which is the dense path. **BM25 build is optional but recommended for completeness.**
Flag as a lower-priority add-on; the dense path is sufficient for the AC guard.

---

## Failure Mode Analysis (six required + additional)

### FM-1: Driver duplicates BGE-M3 stmt/proof routing rule and drifts

**Trigger:** Implementer writes `routing = "embedding_proof" if kind == "proof" else
"embedding_stmt"` by COPYING the string from embedder.py into the new driver instead
of importing the shared `_build_embed_input` + calling `_encode_batch` with an
externally-routed list.

**Symptom:** Silent; proof chunks end up in `embedding_stmt` column, stmt chunks in
`embedding_proof`. ANN search over `embedding_stmt` column retrieves proof bodies, not
statement bodies. Misclassification is permanent in the LanceDB row; no error is raised.

**Mitigation (FM-1 close):** Use fork **(b)** — embed ChunkRecords directly by
importing `_encode_batch` (the precedent set by `ingest/embed_equations.py:31`) and
`_build_embed_input` from `ingest.embedder`. Apply the routing rule from the IMPORT,
not a copy. Single point of truth: if the production routing rule ever changes,
both paths change together.

**EmbedRecord validation as a partial backstop:** `EmbedRecord.__post_init__` only
validates that no chunk_id appears in BOTH lists — it does NOT detect a chunk that
ends up in the wrong list. This check will NOT catch FM-1. The correct column
check requires per-kind cross-validation at the driver level.

### FM-2: EmbedRecord NPZ-alignment violation

**Trigger:** The driver builds `EmbedRecord` with chunk_id appearing in BOTH
`chunk_ids_stmt` AND `chunk_ids_proof`, or a chunk with a kind that maps to `proof`
accidentally inserted into `chunk_ids_stmt`.

**Symptom:** `EmbedRecord.__post_init__` raises:
> `"chunk_ids in BOTH stmt and proof lists (routing rule violated): [...]"`
at `EmbedRecord` construction time (ingest/schema.py lines 384-389).

**Mitigation:** Accumulate stmt and proof lists in strictly separate loops. Assert no
overlap at the driver level BEFORE constructing `EmbedRecord`. The `__post_init__`
check is the backstop; the driver should not rely on it as the primary guard.

**Does the textbook embed path satisfy the alignment check?** YES, provided the driver
applies the routing rule (`kind == "proof"` → proof list, all else → stmt list) exactly
once, which fork (b) with `_encode_batch` + `_build_embed_input` achieves. `chunk_textbook`
returns `list[ChunkRecord]` with well-formed `kind` fields (validated by
`_ALLOWED_KINDS` in store.py at write time).

### FM-3: Writing to WRONG LanceDB path (global corpus pollution)

**Trigger:** Driver calls `write_chunks(chunks, embed_record)` without `lancedb_path`
argument, or passes `lancedb_path=DEFAULT_LANCEDB_PATH` (from `ingest/store.py:113`).

**Symptom:** Textbook chunks with `source_kind="textbook"` and `textbook:` chunk_id
prefix land in `var/arxmcp/index/lancedb/` — the shared arXiv corpus table. The m9
prefix invariant does NOT block this (it only checks prefix vs source_kind agreement,
not whether the path is correct). The global corpus is now polluted with textbook rows.
`search_papers` without a notebook filter returns textbook chunks mixed with arXiv chunks.

**Mitigation:** The driver MUST always pass
`lancedb_path = nb_dir / "lancedb"` explicitly — never use the default. Tests must
use `tmp_path / "lancedb"` and verify the correct path received the write. The test
should also assert the global `DEFAULT_LANCEDB_PATH` received NO write (a separate
assertion that the global corpus is untouched).

### FM-4: m9 prefix-source_kind invariant tripped by accident

**Trigger:** Driver calls `chunk_textbook(slug, paper_id)` but uses the returned chunks
with a modified `paper_id` field (e.g. resolving the textbook paper_id to a flat form),
or calls `write_chunks` with chunks whose `chunk_id` has been mangled (e.g. by calling
`_compute_chunk_id` from `ingest/chunker.py` which hardcodes `arxiv:` prefix).

**Symptom:** `_build_arrow_table` raises:
> `"chunk X has source_kind='textbook' but its chunk_id does not start with the
> matching prefix 'textbook:'"`
at write time (ingest/store.py lines 470-479).

**Mitigation (invariant satisfied by m7):** `chunk_textbook` already emits chunks with
`chunk_id = textbook:<slug>:<hex>` and `source_kind="textbook"`. The driver must pass
the returned `list[ChunkRecord]` to `write_chunks` WITHOUT modifying `chunk_id` or
`source_kind`. Do NOT call `_compute_chunk_id` from `ingest/chunker.py` for textbook
chunks (it hardcodes `arxiv:` — from m7 research).

**Worse failure:** The invariant could be accidentally SATISFIED while `source_kind` is
wrong (e.g. a chunk with `chunk_id="textbook:..."` but `source_kind="arxiv"` from a
stale ChunkRecord default). `write_chunks` would catch this via the prefix check. The
textbook chunker's `ChunkRecord` defaults (`source_kind="textbook"`) prevent this at
construction time.

### FM-5: Model dependency leaking into the integration test

**Trigger:** Integration test calls the driver without monkeypatching `_encode_batch`,
causing a `_get_model()` call that attempts to download BGE-M3 (~2.3 GB).

**Symptom:** Test imports succeed; at runtime, `from transformers import AutoModel`
triggers a HuggingFace download. CI/offline environments fail. Test may be slow (~5 min)
or hang on network timeout.

**Mitigation:** The model-free seam already exists:
1. `_encode_batch` in `ingest/embedder.py` is the only model-touching function.
2. The test monkeypatches `ingest.embedder._encode_batch` to return a pre-built
   `(np.ndarray, 0)` tuple — exactly the shape `_encode_batch` returns.
3. Alternatively, the driver exposes a `_build_embed_record(chunks, batch_size,
   _encoder=_encode_batch)` helper with injectable `_encoder`; tests inject a lambda.
4. The real-model path is gated by `@pytest.mark.requires_model`.

**Confirm the seam:** `_encode_batch` is already imported by `ingest/embed_equations.py`
at module level. Monkeypatching `ingest.embedder._encode_batch` in the test fixture
prevents ANY BGE-M3 load. The test in `tests/test_embed_equations.py` uses the same
pattern — follow it.

### FM-6: Per-notebook corpus_version / MVCC collision on second ingest run

**Trigger:** Driver runs twice for the same notebook. Second call calls `write_chunks`
again, which calls `write_corpus_version_marker`, producing a HIGHER LanceDB version
integer in `corpus-version.json`. The server has cached the OLD version's LanceDB
handle (from `Resources.notebook_table`). The cached handle now points to a stale
version.

**Symptom:** Server continues serving stale rows from the old version. BM25 index
(if built) is at the old corpus_version; the new rows are invisible to BM25.

**Mitigation (idempotency via merge_insert):** `write_chunks` uses
`merge_insert(on="chunk_id")` — same chunks produce the same chunk_ids (content-
addressable). On re-run, every row is an update (not an insert), so the LanceDB
dataset version still increments, but `corpus-version.json` is atomically rewritten.
The `Resources.notebook_table` registry uses an LRU dict with a lock — the handle is
evicted on the next call after the marker changes (because `_read_corpus_version_info`
re-reads the marker file). The driver must call `write_corpus_version_marker` AFTER
`write_chunks` — `write_chunks` already does this internally. Mirror
`notebook_ingest.py::_read_corpus_version` pattern for the BM25 step.

**CRITICAL — BM25 sentinel collision:** `notebook_ingest.py` wrote a `.notebook_slug`
sentinel at `BM25_INDEX_ROOT/v<N>/`. If m12 builds BM25, it must either use the SAME
sentinel guard (to avoid cross-notebook version collisions) OR use a notebook-scoped
BM25 path. The global BM25 collision risk documented in `notebook_ingest.py:132-151`
is a load-bearing cross-milestone constraint. If m12 opts to skip BM25, this risk
is deferred.

### FM-7: `body_tokens` field is None on textbook ChunkRecords

**Trigger:** `chunk_textbook` produces a `ChunkRecord` with `body_tokens=None`
(e.g. `tokenize_body` returns None for empty body_text, or the tokenizer is bypassed).

**Symptom:** `_build_arrow_table` raises:
> `"chunk X has body_tokens=None; E02_S03 is required and must have populated this field"`
at write time (ingest/store.py lines 431-436).

**Mitigation:** `ingest/textbook_chunker.py` calls `tokenize_body` from
`ingest/tokenizer.py` (import at line 71). Verify that every emitted `ChunkRecord` has
a non-None `body_tokens`. A test fixture with an empty body_text chunk should verify
the sentinel value (e.g. `""` or `"tok"`) is used as in `_make_chunk` in test_store.py.

---

## Prior decisions and lessons

- **m7 MEMORY:** `_compute_chunk_id` in `ingest/chunker.py` HARDCODES `arxiv:` prefix.
  Textbook chunker CANNOT call it — must use `_compute_textbook_chunk_id`. m12 driver
  must NOT call the arXiv version for textbook chunks.
- **m9 MEMORY:** `bm25._apply_supported_filters` infers source_kind from chunk_id prefix.
  `textbook:` prefix → "textbook". m12 textbook chunks are BM25-compatible as-is.
- **m9 MEMORY:** `SUPPORTED_FILTER_KEYS = frozenset({"paper_id"})` exists in BOTH
  `server/retrieval/bm25.py:117` AND `server/handlers/search.py:208` — both were updated
  in m9 to add `source_kind`. No further update needed for m12.
- **embed_equations.py precedent:** The file at `ingest/embed_equations.py:31` already
  does `from ingest.embedder import EMBED_BATCH_DEFAULT, _encode_batch` — directly
  calling the low-level batch encoder without going through `embed_paper`. This is the
  SAME pattern m12 should use. It is an established intra-codebase precedent.
- **git log:** As of `58c6989` (notebook-cutover-m1), `tools/_notebook_common.py`
  provides `notebook_dir(slug)` + `validate_slug`. m12 must use these for path
  resolution (same as m7's textbook_chunker).
- **No `assert` ban:** `assert` for invariants is banned project-wide (CLAUDE.md §4.7).
  Use `if ... raise RuntimeError(...)` or `if ... raise ValueError(...)`.

---

## External sources

The BGE-M3 dual-column contract is entirely internal to `ingest/embedder.py` lines
396-481 (`_encode_batch`) and the routing rule at line 1028. No external doc is more
authoritative than the source. The `_encode_batch` function signature:
```python
def _encode_batch(texts: list[str], chunk_ids: list[str] | None = None) -> tuple[object, int]:
```
Returns `(embeddings: np.ndarray(float32, shape=(N, EMBEDDING_DIM)), truncated_count: int)`.
The vectors are L2-normalized. This is the ONLY encode entry point the driver should call.

MCP spec: not relevant — this milestone is a CLI ingest driver with no MCP tool changes.
No tool schema re-pin expected.

---

## Recommendation

**Use fork (b): embed `chunk_textbook`'s `ChunkRecords` directly.**

Specifically, the driver should:

1. Call `chunk_textbook(slug, paper_id)` → `list[ChunkRecord]`.
2. Build embed inputs via `_build_embed_input("", chunk.body_text)` for each chunk
   (preamble is permanently `""` per m8 OQ-1 decision).
3. Apply the routing rule (kind == "proof" → proof column, all else → stmt) to
   split chunk_ids into `chunk_ids_stmt` / `chunk_ids_proof` lists.
4. Call `_encode_batch(stmt_texts, chunk_ids=chunk_ids_stmt)` and
   `_encode_batch(proof_texts, chunk_ids=chunk_ids_proof)` separately,
   OR batch all texts and split after using the routing index (the same pattern as
   `_embed_paper_impl` lines 1020-1081 — follow it exactly).
5. Construct `EmbedRecord(...)` with `embedder_version=EMBEDDER_VERSION`.
6. Call `write_chunks(chunks, embed_record, lancedb_path=nb_dir / "lancedb")`.

Fork (b) is lower-risk than (a) because:
- No global chunk-store NPZ round-trip; textbook chunks live in the notebook scope.
- `embed_equations.py` has already established `_encode_batch` as the correct
  low-level entry point for non-paper-level embedding.
- The routing rule stays single-sourced in `ingest/embedder.py`; driver imports it,
  not copies it.
- The test path (monkeypatching `_encode_batch`) is proven by `test_embed_equations.py`.

**DO NOT skip BM25.** While dense-only suffices for the e4 AC, add a BM25 step
mirroring `notebook_ingest.py::run()` lines 127-157 (including the `.notebook_slug`
sentinel). This prevents the BM25 collision bug from appearing when a textbook
notebook and an arXiv notebook happen to reach the same `corpus_version` integer.

**Driver shape:** `tools/notebook_textbook_ingest.py` with a `run(slug)` function
and a CLI argparser mirroring `tools/notebook_ingest.py`. Accept a `slug` only (not
`(slug, paper_id)` pairs) — all textbook paper_ids are derived from the slug's
`chunks/` directory, same as how `notebook_ingest.py` reads `papers.txt`. The driver
discovers all `chunk_textbook` output paths via `nb_dir / "chunks" / *`.

---

## Open questions

1. **Single paper_id vs multi-paper textbooks.** The milestone brief says "given a
   textbook notebook slug (+ paper_id(s))". If a notebook has MULTIPLE textbook
   paper_ids (e.g. Volume 1 and Volume 2 of Milne), the driver must embed all of them.
   The safest design: enumerate all subdirectories under `nb_dir / "chunks"/` and
   embed each. Mirroring how `notebook_ingest.py` reads `papers.txt` is an alternative
   but requires the operator to pre-populate `papers.txt` with textbook paper_ids.
   RECOMMENDATION: enumerate `nb_dir / "chunks"/` directly (no `papers.txt` dependency
   for the textbook path).

2. **What if `chunk_textbook` has NOT been run yet?** The driver should call
   `chunk_textbook(slug, paper_id)` directly (one-pass shape), NOT read pre-written
   chunk JSONs. This simplifies the driver and matches the milestone brief's
   "CENTRAL DESIGN FORK" framing that one-pass is preferred. If the HTML is missing,
   `chunk_textbook` will log a failure row and return `[]`; the driver should surface
   this as a non-zero exit code (mirrors `notebook_ingest.py::run()`'s failure path).

No further open questions — the above two are resolvable at implementation time
without external input.

---

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| `git push` | `main` | Ship the milestone commit triple to remote |
| `gh issue close` | `chris-dare-dev/arXMCP#8` | Milestone closes this follow-up issue |
