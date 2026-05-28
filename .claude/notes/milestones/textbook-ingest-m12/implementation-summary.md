# Implementation Summary — textbook-ingest-m12

**Summary:** New `tools/notebook_textbook_ingest.py` driver embeds m7 textbook chunks (BGE-M3 dual-column, via the embedder's low-level `_encode_batch`/`_build_embed_input`) and writes them into the per-notebook LanceDB, so textbook chunks are retrievable via `search_papers`. Closes the e4 OUTCOME end-to-end and the follow-up at chris-dare-dev/arXMCP#8.

**Commit range:** `58c6989..HEAD` (single feat commit + this summary).

## Acceptance criteria status

| AC | Status | Evidence |
|---|---|---|
| New `tools/notebook_textbook_ingest.py`: slug + paper_id → chunk_textbook → embed → write_chunks to the notebook LanceDB | [x] | the driver: `ingest_textbook_paper` / `run` / `main` |
| **MODEL-FREE integration test (e4-demo guard):** textbook chunk written via the driver path is dense-retrievable with `source_kind="textbook"` | [x] | `tests/test_notebook_textbook_ingest.py::TestIngestTextbookPaper::test_textbook_chunk_is_dense_retrievable_with_source_kind_filter` — real tmp LanceDB, synthetic encoder, `.search(qv).where("source_kind='textbook'", prefilter=True)` returns the definition chunk |
| Idempotent re-run (no duplicates) | [x] | `::test_idempotent_rerun_no_duplicates` (merge_insert on chunk_id; count stays 2) |
| m9 prefix↔source_kind invariant satisfied | [x] | chunks pass through `write_chunks` unmodified (textbook: ids + source_kind=textbook); write succeeds |
| Reuse BGE-M3 embedder, no duplicated routing; real path model-gated | [x] | imports `_encode_batch`/`_build_embed_input` (the `embed_equations.py` precedent); routing applied from the single source; `encoder` injectable → tests model-free, real default = `_encode_batch` |
| FM-3: never write the global corpus path | [x] | `::test_write_targets_notebook_path_not_global_corpus` (spy asserts `lancedb_path == notebook path != DEFAULT_LANCEDB_PATH`) |
| FM-1: routing single-source | [x] | `::TestBuildEmbedRecord::test_stmt_and_proof_route_to_distinct_columns` |
| per-notebook corpus_version handled | [x] | `write_chunks` writes `corpus-version.json` (integer MVCC); D2 marker `chunker_version` caveat documented in the driver docstring |
| NO tool-schema / BP1 re-pin | [x] | ingest-only CLI; no `server/` change, no `ALL_TOOLS` touch |

## What changed
- **`tools/notebook_textbook_ingest.py`** (NEW, ~210 LOC): `_build_embed_record(chunks, *, batch_size, encoder=_encode_batch)` (mirrors `_embed_paper_impl`'s build→batch→split, returns EmbedRecord in-memory, injectable encoder for model-free tests); `ingest_textbook_paper(slug, paper_id, ...)` (chunk→embed→write to `notebook_lancedb_path(slug)`); `run(slug, paper_ids, ...)` (exit 0/1/2); `main(argv)` (argparse CLI, `--paper-id` required+repeatable, `--batch-size`, `--dry-run`).
- **`tests/test_notebook_textbook_ingest.py`** (NEW): `TestBuildEmbedRecord` (routing, version stamp, empty, L2-norm), `TestIngestTextbookPaper` (write to notebook lancedb, FM-3 path guard, the e4-demo retrieval guard, idempotency, dry-run), `TestRunExitCodes` (0/1/2). All model-free (synthetic encoder).

## Design decisions (from synthesis)
- **Fork (b):** embed `ChunkRecord`s directly via `_encode_batch`/`_build_embed_input` — the established `ingest/embed_equations.py` precedent — NOT `embed_paper` (which assumes the global chunk store). No edits to `ingest/embedder.py` or `ingest/store.py`.
- **D1: skip BM25** — notebook retrieval is dense-only at v1 (notebook-retrieval-m2 AC2); a notebook BM25 index would be dead code + the collision surface. Documented in the driver docstring.
- **D2: corpus-version marker `chunker_version` inaccuracy** — `write_chunks` stamps the arXiv `"v1.1"` not `"tv0.1"`; observability-only (integer version is correct, BM25 skipped). Accepted + documented in the docstring; no `store.py` change.
- **D3-refinement: `--paper-id` explicit (required, repeatable)** — chosen over auto-enumerating `chunks/` because `_flat_paper_id` (`:`/`/`→`_`) is lossy and not cleanly reversible to the original paper_id `chunk_textbook` needs. Matches the upload contract (paper_id is explicit per upload).

## Failure modes guarded
- FM-1 (routing drift): routing from the single import; unit test pins stmt/proof partition.
- FM-3 (corpus pollution): always `notebook_lancedb_path(slug)`; spy test asserts not `DEFAULT_LANCEDB_PATH`.
- FM-5 (model leak in tests): `encoder` injected; all tests model-free.
- FM-7 (body_tokens None): synthetic chunks set `body_tokens`; `write_chunks` accepts.

## External writes required
| type | target | why | status |
|---|---|---|---|
| git push | origin/main | ship the feat→rect→chore triple | Phase-4 per-event authorized |
| gh issue close | chris-dare-dev/arXMCP#8 | this milestone closes the tracked follow-up | Phase-4 per-event authorized |

## Deviations from the brief
- The brief floated auto-enumerating paper_ids from `nb_dir/chunks/`; refined to explicit `--paper-id` (lossy flat-id reversal — see D3-refinement). Auto-enumerate is a documented future enhancement.
- The full `search_papers` handler/Resources/`filters.notebook` routing is NOT re-tested here — it is already proven for any notebook LanceDB by `tests/test_search_notebook_routing.py` (m2). m12 proves the complementary half: the driver writes a notebook LanceDB whose textbook chunks are dense+source_kind retrievable.
