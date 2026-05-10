# E09_S03 — `cite_neighbors` research brief 1

## 1. In-codebase context

**Schema + source-vocabulary contract** (`ingest/kuzudb_schema.py`). `KUZU_SCHEMA_VERSION = 2`; the docstring names this milestone:

> "downstream cache layers, e.g. `cite_neighbors` in E09_S03 can detect drift on an existing database. … any schema mutation MUST bump a version constant so cached responses derived from the schema don't go stale silently."

And pins the edge-source vocabulary:

> `cites`: FROM papers TO papers; source ("openAlex" | "inspire" | "intra-paper"); confidence (0..1).

`papers` PK = `paper_id STRING`; v2 adds nullable `doi`/`journal_ref`/`inspire_id`. Use `kuzudb_schema.read_schema_version(db_path)` for the cache-key stamp.

**Edge writer** (shared by both ingest passes — `ingest/graph_ingest.py:_merge_cite`):

> `MERGE (a)-[r:cites {source: $source}]->(b) ON CREATE SET r.confidence = $confidence ON MATCH SET r.confidence = $confidence`

Note: `source` is part of the MERGE key, so an OpenAlex edge and an INSPIRE edge for the same `(src, dst)` are distinct relationships. `cite_neighbors` will see all of them and must dedupe on `(paper_id, hop)` only when the caller wants paper-level neighbors. OpenAlex emits `source="openAlex"` (camelCase, `graph_ingest.py:621`); INSPIRE emits `source="inspire"` (lowercase, `inspire_ingest.py:670` region); intra-paper will be `"intra-paper"`. **Do not normalize at write — normalize for display in the result mapper if at all.**

**Existing reader pattern** to mirror — `inspire_ingest._existing_paper_ids` (lines 437-448): open db, connect, `execute`, `while result.has_next(): result.get_next()`, drain. Use the same `try/finally: del db` lifecycle from `apply_schema` (deterministic close — load-bearing on Windows tmp_path teardown).

**chunk_id format** (`ingest/identifiers.py:21,49-54`):

> `chunk_id`: `arxiv:<paper_id>:<16-hex>`. `CHUNK_ID_PATTERN = rf"arxiv:({PAPER_ID_PATTERN}):[0-9a-f]{{16}}"`

There is **no separate `chunk_id_to_paper_id` mapping module**. The format is regex-locked and the existing `get_chunk` handler proves the round-trip via LanceDB lookup. Use the regex (`CHUNK_ID_RE.match(chunk_id).group(1)`) — a string-parse derivation is O(1), avoids touching LanceDB until needed, and matches the same `is_valid_chunk_id` validation the chunk handler uses.

**LanceDB chunks table** (`ingest/schema.py:69-118`): columns `chunk_id`, `paper_id`, `kind` (`"stmt"`, `"proof"`, `"section"`, or env name `"lemma"`/`"corollary"`/…), `theorem_label` (nullable). Read access via `server/corpus.py::open_chunks_table` (version-pinned handle). The "first kind=stmt for each paper_id" lookup follows `server/handlers/paper.py:47-52`: `chunks_table.search().where(f"paper_id IN ({csv}) AND kind = 'stmt'", prefilter=True).limit(N).to_arrow()`. **One batched query over all paper_ids**, group by `paper_id` in Python, pick the lexicographically-first `chunk_id`. Per-paper queries would multiply round trips by 50.

**Server design constraints** that apply:

- `server/corpus.py` cache contract: every cache key must include the `version` int — for `cite_neighbors` add `KUZU_SCHEMA_VERSION` AND the LanceDB `corpus_version`.
- The `server/cache.py` 3-tier cache is for `search_papers`. `cite_neighbors` is graph-local; a per-(chunk_id, depth, direction, max_results) memo at the handler boundary is reasonable but **out of scope for this milestone** (E06_S04 wires the MCP tool).
- `server/handlers/citations.py` exists as a stub with **incompatible direction literals** (`"citers", "cited", "co_cited", "co_citing", "depends_on"`). The brief uses `"cites", "cited_by", "depends_on"`. This is E06_S04's reconciliation problem; the function in `server/graph_queries.py` MUST follow the brief.

**Tests/conftest discipline** (`tests/conftest.py`): autouse fixtures redirect every checkout-relative writeable path into `tmp_path` (store-stats, BM25 stats/index, cache db). The `cite_neighbors` test must build its 5-paper fixture under `tmp_path` via `apply_schema(tmp_path/"kuzu")` + direct `MERGE` calls (mirror `tests/test_graph_ingest.py`). No new autouse fixture is needed — `cite_neighbors` is read-only.

## 2. Prior decisions and lessons

**Path drift — same flavor, same resolution.** E09_S01 docstring (`ingest/kuzudb_schema.py:6-13`):

> "The milestone brief AC#1 names the path `var/arxmcp/index/kuzudb/`; that wording conflicts with the bootstrap target and both relevant design notes (`05-storage-and-indexing.md` and `08-security-observability-ops.md`), all of which use `kuzu/`. The implementation follows the design constitution and treats the brief's AC#1 path-name as drift to be corrected in a follow-up docs PR."

E09_S03's brief signature default `kuzudb_path: str = "var/arxmcp/index/kuzudb/"` is the same drift. **Recommendation: ship `kuzu_path: str = "var/arxmcp/index/kuzu/"` to match the existing bootstrap and the two prior milestones**, and document the deviation in the docstring exactly as `kuzudb_schema.py` did. Renaming the param from `kuzudb_path` to `kuzu_path` matches the rest of the codebase (every existing caller and CLI uses `--kuzudb` as the *flag* but `kuzu` as the path; the function param should follow the path, not the flag). If renaming the param feels too aggressive, keep `kuzudb_path` as the param NAME but change its default VALUE to the `kuzu/` path.

**F1 (E09_S01) — case-insensitive accept, canonical write.** `graph_ingest._normalize_source` accepts `openAlex`/`openalex`. The Kùzu rows themselves carry the **as-written** source string (`"openAlex"` from OpenAlex, `"inspire"` from INSPIRE). `cite_neighbors` is a downstream **reader** — it must accept either casing in any future filter parameter and normalize internally if it ever filters on `source`. For this milestone, no `source` filter is in the signature, so we just project the raw value.

**F9 (E09_S01/S02) — categories filter unsatisfiable.** Doesn't bite us directly: `cite_neighbors` doesn't filter on `papers.categories`. But the lesson — **trust column shape, not the brief's prose** — applies to the brief's `\ref{}` line: "scan the paper's LaTeXML HTML." Verify on a real parsed file before committing to a regex.

**F4 (E09_S01) — split writers, structural ownership.** `_merge_paper` (OpenAlex) and `_merge_paper_inspire` (INSPIRE) own disjoint columns. `intra_paper_refs.py` follows the same discipline: writes ONLY `cites` rows with `source="intra-paper"`, never touches `papers` columns. Per-paper: read parsed HTML, find `<a class="ltx_ref" href="#KEY">` (LaTeXML 0.8.8 emits `\ref{KEY}` this way), look up `theorem_label == KEY` chunk in the same paper via LanceDB, emit a self-edge via existing `_merge_cite` with `source="intra-paper"`, `confidence=0.5` (conventional for static-analysis edges; document). The brief frames this as a self-edge `papers(p) → papers(p)`; verified live, Kùzu 0.11.3 stores/traverses self-edges.

**F3 pattern.** Both `graph_ingest` and `inspire_ingest` track `fetch_failures` and exit non-zero while pending. `intra_paper_refs.py` operates on local files, so the failure mode is "parsed HTML missing" — emit `WARNING` and continue; do **not** invent a checkpoint.

## 3. External sources

**Kùzu 0.11.3 Cypher — verified live in this session** with a tmp database:

- `MATCH p = (s:papers {paper_id: $id})-[:cites*1..2]->(n:papers) RETURN n.paper_id, length(p) AS hop` — works. `length(p)` returns the integer hop count.
- `MATCH p = (n:papers)-[:cites*1..2]->(s:papers {paper_id: $id}) RETURN n.paper_id, length(p) AS hop` — works (this is `cited_by`; reverse the arrow direction in the pattern).
- `relationships(p)` projection — works; returns a list of dicts with `source` / `confidence` per hop. Use this if per-hop edge metadata matters for the result.
- `r[idx].source` shorthand — **does NOT parse** in Kùzu 0.11.3 (`Parser exception: mismatched input '.'`). Do not write that even though it's idiomatic openCypher.
- `MIN(length(p))` aggregation deduplicates same-paper-by-multiple-paths to the shortest hop. **Recommendation: dedupe in Cypher with `MIN`** rather than in Python — fewer wire-format bytes and ordering is correct.
- `ORDER BY hop ASC, pid ASC LIMIT 50` — works at the Cypher layer. Apply the cap in Cypher to bound result-set size before crossing the kuzu→Python boundary.
- Self-loops are returned by variable-length matches (the intra-paper case). When `direction` is `"cites"` or `"cited_by"`, **filter out self-loops in Python** (`if neighbor_paper_id == source_paper_id: skip`) unless the caller asks for `depends_on`.

**LaTeXML `\ref{}`.** No useable parsed file in this checkout — `var/arxmcp/corpus/parsed/2605.03890/index.html` is 17 lines, body empty. LaTeXML 0.8.8 emits `\ref{key}` as `<a class="ltx_ref" href="#key" title="...">…</a>`; the user's label key is in `href`. Chunker already extracts `theorem_label` from the element `id` (`ingest/chunker._extract_theorem_label`). Use BeautifulSoup (already a dep) over `index.html`, scan `<a class="ltx_ref" href="#KEY">`, look up `theorem_label == KEY` chunk in the same paper via LanceDB. A regex over raw `.tex` would also work, but chunker operates on parsed HTML and stored `body_text` is plain-text (no `\ref{}` tokens preserved) — HTML traversal is the right tier.

## Open questions

1. **`chunk_id → paper_id` mapping.** Recommend regex-parse via `ingest.identifiers.CHUNK_ID_RE` (group 1 = paper_id). It's O(1), no IO. The brief's "simple lookup" framing implies anything cheap; the regex is cheaper than touching LanceDB and is already the validation surface.
2. **`kuzudb_path` default.** Ship `var/arxmcp/index/kuzu/` to match E09_S01/S02; document the brief drift in the function docstring exactly as `kuzudb_schema.py:6-13` does. Keeping the parameter name `kuzu_path` is cleaner than `kuzudb_path` but either is acceptable.
3. **First kind=stmt lookup.** Single batched LanceDB query — see § 1.
4. **`depends_on` cross-paper fallback.** The brief: "When `direction="depends_on"` and a result chunk is in a different paper, it falls back to `direction="cites"` for cross-paper hops." Recommendation: the Cypher path is `MATCH p = (s:papers{paper_id:$id})-[r:cites*1..$depth]->(n:papers)` — same query, no source filter (so it walks both intra-paper and OpenAlex/INSPIRE edges), and the result mapper labels each hop by the actual `r.source` from `relationships(p)`. The "fallback" the brief describes is **automatic** if you do not filter on `source` for `depends_on` — you only need the filter when the caller asks for `cites`/`cited_by` exclusively. **Document this**: `depends_on` is "any edge type, intra-paper-rooted"; `cites`/`cited_by` are "non-intra-paper edges only" (`WHERE r.source <> 'intra-paper'`).
5. **`cited_by` Cypher direction.** Verified live (above). Reverse the arrow: `(n:papers)-[:cites*1..N]->(s:papers {paper_id: $id})`.
6. **Source-string normalization.** Return the **raw** value from the rel table. Downstream display can lowercase if it wants, but losing the distinction between `"openAlex"` and `"inspire"` in the typed result removes auditability. The dataclass docstring should explicitly call out the casing.
7. **`max_results` truncation.** **`LIMIT 50` in Cypher** — see § 3 above. Order by `(hop ASC, paper_id ASC)` so the truncation is deterministic and a re-run returns the same 50 papers.
8. **Result ordering.** `hop ASC, paper_id ASC` (lexicographic on the arXiv ID is stable and reproducible).
9. **`chunk_id=None` case.** **Make the dataclass field `chunk_id: str | None`** even though the brief writes `chunk_id: str`. AC#7 ("Papers in the graph but not in the chunked corpus return `chunk_id=None`") is non-negotiable; non-Optional `str` plus `None` value is a type lie. The brief's signature is informal Python; downstream agents (Sonnet B's E06_S04) will introspect via `pydantic` schema generation and a non-Optional `str` would render `None` as the string `"None"` or fail validation.

## External writes the implementation will require

| type | target | why |
| --- | --- | --- |
| (none) | n/a | Pure-local milestone: code under `server/` and `ingest/`, plus a unit test under `tests/`. No HTTP, no MCP-tool registration (E06_S04), no PR/issue creation per the auto-mode rules. The intra-paper ref pass reads existing parsed HTML on disk and writes Kùzu rows via the already-present `_merge_cite`. No external surface is touched. |
