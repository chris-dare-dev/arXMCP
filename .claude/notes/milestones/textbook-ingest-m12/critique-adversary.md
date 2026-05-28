# Critique — textbook-ingest-m12

**Critic:** adversary
**Generated:** 2026-05-28T20:09:56Z
**Commit range:** 58c698939dead77654c14172c307ce67f54782e8..0f40d747320c6f8f1a5fa4546ca53328e0383e98
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the load-bearing details (embed-source fidelity, FM-3 corpus-isolation, the e4 dense+source_kind retrieval guard) are all correct and genuinely tested; the open items are robustness/scope-honesty, not correctness.
- Finding counts: 0 CRITICAL, 0 HIGH, 3 MEDIUM, 2 LOW.
- Highest-risk gap: `tools/notebook_textbook_ingest.py:229` — `main()`/`run()` have no slug-validation pre-check and no `try/except NotebookError`, diverging from the sibling `tools/notebook_ingest.py:204-208` contract; a bad slug/paper_id raises an uncaught traceback instead of a clean exit code.
- `_build_embed_record` (`tools/notebook_textbook_ingest.py:84-160`) is a line-faithful mirror of `_embed_paper_impl` (`ingest/embedder.py:1017-1081`): same build→batch→split, same row-aligned split, same `np.zeros((0, EMBEDDING_DIM))` empty case, routing applied from the imported single source (FM-1). Verified clean.
- FM-3 verified: the driver ALWAYS passes `lancedb_path=notebook_lancedb_path(slug)` (`:194-196`); the global default `DEFAULT_LANCEDB_PATH` (`ingest/store.py:802`) is unreachable on every code path; the spy test asserts `!= DEFAULT_LANCEDB_PATH` (`tests/...:177`). Genuine.
- The e4-demo guard exercises the REAL mechanism: `tbl.search(qv, vector_column_name="embedding_stmt").where("source_kind = 'textbook'", prefilter=True)` (`tests/...:192-197`) is byte-identical to the server's `search_papers` dense path (`server/handlers/search.py:628-650`); the asserted chunk is the stmt-routed `definition` (correct column). Genuine, not a table scan.
- Scope honesty caveat: "closes e4 end-to-end" is true by composition but no single test runs a TEXTBOOK chunk through the full `search_papers` handler + `filters.notebook` routing (m2's routing tests use `source_kind="arxiv"` — `tests/test_search_notebook_routing.py:542,553`). The seam is mechanically trivial; flagged MEDIUM for honesty, not HIGH.
- Cache byte-stability / no-fork / banned-patterns / tier-sequencing: all axis-verified clean (no `server/tools.py`/`ALL_TOOLS`/schema touch; `_encode_batch` import is the established `embed_equations.py` intra-repo reuse; ruff clean).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — main()/run() lack slug-validation + NotebookError guard

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tools/notebook_textbook_ingest.py:229
- **What:** `run()` (`:204-226`) never calls `validate_slug(slug)` up front, and `main()` (`:229-257`) does not wrap `run()` in `try/except NotebookError`. Slug/paper_id validation happens only inside `chunk_textbook` (`ingest/textbook_chunker.py:296-302`), which RAISES `ValueError`/`NotebookError` (not the per-paper `[]` path) for an invalid or unsafe slug/paper_id.
- **Why it matters:** The sibling CLI `tools/notebook_ingest.py` validates the slug at `run()` top (`:70`) and converts `NotebookError` to a clean exit-code-1 in `main()` (`:204-208`). m12 does neither, so `uv run python tools/notebook_textbook_ingest.py BadSlug --paper-id x` prints a raw Python traceback and exits via an uncaught exception instead of the documented 0/1/2 exit-code contract. This is NOT a security hole — the slug is still rejected (path traversal is blocked by `notebook_dir`); it is a robustness/contract divergence. Per-paper validation also fires once per `--paper-id` iteration rather than once up front, so a bad slug only surfaces after the first chunk attempt.
- **Proposed fix:** Add `validate_slug(slug)` at the top of `run()` (import from `tools._notebook_common`), and wrap the `run(...)` call in `main()` with `try: return run(...) except NotebookError as exc: print(f"error: {exc}", file=sys.stderr); return 1` — mirroring `notebook_ingest.py:204-208`. Also catch `InvalidPaperIDError`/`ValueError` from the paper_id validator.
- **Regression guard:** Add `TestRunExitCodes::test_invalid_slug_clean_exit` asserting `main(["Bad-Slug", "--paper-id", "textbook:x"])` returns 1 (not raises), and `test_invalid_slug_validated_before_chunking` asserting `chunk_textbook` is NOT reached for a malformed slug.

### F2 — "closes e4 end-to-end" unproven through the search_papers handler

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_notebook_textbook_ingest.py:179
- **What:** The e4-demo guard queries the LanceDB table directly (`tbl.search(...).where(..., prefilter=True)`, `:192-197`) — faithfully replicating the server's dense path — but does NOT route a textbook chunk through the actual `search_papers` handler with `filters.notebook=<slug>` + `filters.source_kind="textbook"`. The summary defers that to `tests/test_search_notebook_routing.py` (m2), but m2's routing tests assert against `source_kind="arxiv"` rows only (`tests/test_search_notebook_routing.py:542,553`; fixture default `:296`).
- **Why it matters:** Each half is proven (m12: textbook chunk dense+source_kind retrievable at the LanceDB layer; m2: `filters.notebook` routes to the notebook table for arxiv rows), but the COMPOSITION — a driver-written textbook chunk returned by the full handler under notebook routing — is inferred, not exercised. The inference is sound (`textbook` is whitelisted at `server/handlers/search.py:209-211`; routing is orthogonal to source_kind; the `.where(predicate, prefilter=True)` chain is identical at `search.py:628-650`), so the risk is low — but the milestone's headline claim ("closes the e4 OUTCOME end-to-end") slightly overstates what one test demonstrates.
- **Proposed fix:** Either (a) add one handler-level test that calls the real `search_papers` handler against a notebook table containing a m12-driver-written textbook chunk with `filters={"notebook": slug, "source_kind": "textbook"}` and asserts the chunk returns, OR (b) downgrade the summary/docstring wording from "closes e4 end-to-end" to "closes the LanceDB-write half of e4; the handler+notebook-routing half is proven for any notebook table by m2." (b) is the cheap honest fix.
- **Regression guard:** The (a) handler test above; it would fail if a future schema/routing change broke textbook retrievability through the handler — the gap (a) leaves open today.

### F3 — no test pins vector↔chunk_id alignment across the split

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tools/notebook_textbook_ingest.py:136
- **What:** The split loop (`:136-153`) keeps `all_array[i]` aligned with `chunk_ids_in_order[i]` and `routing[i]` — correct, and identical to the proven `_embed_paper_impl` (`ingest/embedder.py:1062-1068`). But `test_stmt_and_proof_route_to_distinct_columns` (`tests/...:76-88`) only asserts the ID-LISTS are partitioned correctly (`chunk_ids_stmt == [stmt.chunk_id]`); it does NOT assert that `embedding_stmt[0]` is actually the encoding of the stmt chunk's input text. Both fixture chunks share `source_kind="textbook"`, so the e4 retrieval test cannot catch a vector/id transpose either.
- **Why it matters:** A future refactor of the split (e.g. building `rows_stmt` from a separately-sorted source, or a zip mismatch) could embed chunk A's vector under chunk B's id — silent corruption that `EmbedRecord.__post_init__` provably does NOT catch (it validates dup/overlap/L2-norm only — `ingest/schema.py:309-414`; a transposed-but-still-normalized vector passes all four checks). The code is correct as written; this is a missing latent-foot-gun guard, not a live bug.
- **Proposed fix:** In `_build_embed_record`'s unit test, inject a deterministic encoder that returns an identity-derived marker per input (e.g. encode text `i` to a vector whose argmax index is `i`), then assert `int(np.argmax(rec.embedding_stmt[0]))` maps back to the stmt chunk's original position — so a vector/id transpose fails the test. Cheap (≤15 LOC, no new fixture file).
- **Regression guard:** The argmax-marker assertion above; it fails iff the split desynchronizes vectors from ids.

### F4 — synthesis-resolved auto-enumerate (D3) silently dropped for required --paper-id

- **Severity:** LOW
- **Source:** adversary
- **File:** tools/notebook_textbook_ingest.py:238
- **What:** `--paper-id` is `required=True` (`:238`). The research synthesis resolved D3 the other way: "`--paper-id` repeatable; **if omitted, ENUMERATE all paper_ids from `nb_dir/chunks/*`**" (research-synthesis.md:27,38), explicitly to handle multi-volume textbooks without manual listing.
- **Why it matters:** This is a deviation from an orchestrator-resolved design decision. The implementer's rationale is technically sound — `_flat_paper_id` (`ingest/textbook_chunker.py:106`) does `":"→"_"` and `"/"→"_"`, which is genuinely not uniquely reversible, so enumerating `chunks/` subdirs cannot reconstruct the original paper_id `chunk_textbook` needs. Requiring explicit `--paper-id` also matches the per-upload contract. So the deviation is defensible and documented (implementation-summary.md:44), but it IS a usability regression vs the plan (operator must hand-list every volume) and was decided unilaterally at implement time.
- **Proposed fix:** No code change required; accept the deviation. Optionally, support enumeration via the notebook's `papers.txt` (which stores the ORIGINAL, un-flattened paper_ids — `read_paper_ids_from_papers_txt`, `tools/_notebook_common.py:150`) rather than the lossy `chunks/` dir, restoring the convenience without the reversal problem.
- **Regression guard:** N/A (accepted deviation). If enumeration is added later, a test asserting `--paper-id` omitted reads from `papers.txt`.

### F5 — no real-model smoke test despite AC/synthesis implying one

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/test_notebook_textbook_ingest.py:1
- **What:** The synthesis (research-synthesis.md:30,45) and AC table (implementation-summary.md:15) describe a `@pytest.mark.requires_model` real-embed path ("real path model-gated"). No `requires_model`-marked test ships in `tests/test_notebook_textbook_ingest.py` (the only `_encode_batch` reference is a docstring at `:31`).
- **Why it matters:** The model-free seam is fully and correctly exercised (FM-5 is genuinely closed — verified that every test injects a synthetic encoder or monkeypatches `_build_embed_record`, and `run()`'s default `encoder=_encode_batch` is never reached with real chunks), so this is not a correctness gap. But the absence means the driver's real-encoder default (`:88,168`) has zero CI coverage even in the opt-in tier — a real BGE-M3 call from this driver is never validated end-to-end. Such tests are skipped-by-default anyway, so blast radius is minimal.
- **Proposed fix:** Add one `@pytest.mark.requires_model` test that calls `_build_embed_record([chunk])` with the DEFAULT encoder (no injection) and asserts the returned `embedding_stmt` is `(1, EMBEDDING_DIM)` and L2-normalized — gated so it stays skipped without the model env var.
- **Regression guard:** The `requires_model` test above; catches a future signature drift between the driver and the real `_encode_batch`.

## What was done well

- `_build_embed_record` (`tools/notebook_textbook_ingest.py:84-160`) is a faithful line-by-line mirror of `_embed_paper_impl` (`ingest/embedder.py:1017-1081`): identical build→batch→`np.concatenate`→routing-split→`np.zeros((0, EMBEDDING_DIM))` flow, with the proof/stmt rule applied from the imported single source (never a copied string) — FM-1 honored exactly as the synthesis required.
- FM-3 (corpus pollution, highest blast radius) is airtight: `lancedb_path=notebook_lancedb_path(slug)` is the only call (`:194-196`); there is no fallback, default-arg, or error path that reaches the global `DEFAULT_LANCEDB_PATH`; the spy test asserts both `== nb_lancedb` AND `!= DEFAULT_LANCEDB_PATH` (`tests/...:176-177`).
- The e4-demo guard is genuine, not trivial: it writes via the REAL `write_chunks` to a REAL tmp LanceDB and queries via the exact `.search(qv, vector_column_name="embedding_stmt").where("source_kind = 'textbook'", prefilter=True)` chain the server uses (`server/handlers/search.py:628-650`), asserting the correctly stmt-routed `definition` chunk returns.
- The model-free guarantee (FM-5) holds across every test, including the tricky `run()` path (`test_all_papers_chunked_exit_0`) which monkeypatches `_build_embed_record` to inject a synthetic encoder without recursion — and `run()` takes no encoder arg, so this is the right seam.
- Path-traversal defense is preserved by construction: `chunk_textbook` runs `validate_slug` + symlink refusal + containment (`ingest/textbook_chunker.py:296-302`) and `_validate_paper_id` (which DOES accept `textbook:<slug>` — `ingest/chunker.py:118-121`), and `notebook_lancedb_path` chains through `notebook_dir`→`validate_slug` (`tools/_notebook_common.py:102-147`).
- The empty-column case is handled correctly (`np.zeros((0, EMBEDDING_DIM))` rather than crashing on `np.stack([])` — `:144-153`), matching the embedder, and a dedicated test pins it (`test_empty_chunks_returns_empty_record`).
- The D2 corpus-version-marker caveat is HONESTLY documented in the driver docstring (`:41-46`) and is genuinely harmless: all server readers consume the integer `corpus_version` (correct), and the inaccurate string `chunker_version="v1.1"` surfaces only in a startup `logger.info` line (`server/resources.py:337-345`), never a functional gate — and BM25 (the only version-gated reader) is skipped by design.
- Cache byte-stability is untouched: no `server/tools.py`, `ALL_TOOLS`, `prompts.py`, or `EXPECTED_TOOL_SCHEMA_SHA256` change — correctly NO re-pin, exactly as the brief specified for an ingest-only CLI.
- No-fork honored: the `_encode_batch`/`_build_embed_input` import is the established intra-repo `ingest/embed_equations.py` precedent, not lifted code; ruff clean; no banned patterns (`assert`/`anthropic`/`BaseHTTPMiddleware`/`0.0.0.0`) in the new files.
- Idempotency is genuinely tested (re-run, assert `n1 == n2 == 2` via `merge_insert(chunk_id)` — `tests/...:204-211`) and the chunks pass through `write_chunks` UNMODIFIED so the m9 `textbook:` prefix ↔ `source_kind="textbook"` invariant holds (FM-4).

## Recommended rectification order

1. **F1** (slug-validation + NotebookError guard in `run()`/`main()`) — highest leverage: restores the documented CLI exit-code contract and matches the sibling driver; small, self-contained (~10 LOC + 2 tests).
2. **F2** (e4 handler-composition honesty) — pick the cheap (b) wording fix unless (a) handler test is wanted; resolves the only scope-overclaim.
3. **F3** (vector↔id alignment guard) — cheap argmax-marker test; closes the silent-corruption foot-gun the `EmbedRecord` validation provably cannot catch.
4. **F5** (requires_model smoke test) — defer-eligible; add if cheap.
5. **F4** (auto-enumerate deviation) — accept as-is; optional `papers.txt` enumeration is a future enhancement, not a Phase-4 fix.

## Rectification status

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
