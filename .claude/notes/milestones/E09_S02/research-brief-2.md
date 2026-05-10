# E09_S02 research brief 2 — INSPIRE-HEP enrichment

## 1. In-codebase context

### `_ResolvedWork` and the checkpoint shape (`ingest/graph_ingest.py`)

`_ResolvedWork` is a frozen dataclass with seven fields: `oa_work_id`, `title`,
`abstract`, `authors`, `year`, `categories`, `referenced_works`. Serialization
goes through `_serialize_resolved` / `_deserialize_resolved`, which round-trip
each field by literal name; `referenced_works` is stored as a list and re-cast
to a tuple on load. The checkpoint skeleton is
`{"resolved": {}, "edges_done": [], "fetch_failures": []}`. **E09_S02 should
NOT extend `_ResolvedWork`** — the OpenAlex resolver only cares about OpenAlex
fields. Introduce a parallel `_ResolvedInspire` dataclass (`inspire_id`,
`dois`, `journal_ref`, `references_arxiv`, `collaborations`) with its own
serializer and checkpoint file. Mixing sources in one dataclass re-creates the
F4 hazard at the dataclass layer.

### `_merge_paper` and the F4 hazard

The docstring is load-bearing (lines 408-422):

> "the `ON MATCH SET` clauses below unconditionally overwrite `title`,
> `authors`, etc. with the OpenAlex values on every re-MERGE … if INSPIRE-HEP
> populated a canonical journal title in `title`, this re-MERGE would clobber
> it with the OpenAlex preprint title. E09_S02 must introduce a per-field
> source-rank predicate (or split the `_merge_paper` writers per-source)
> before adding any cross-source enrichment that writes the same columns."

**Recommendation:** *split, do not unify.* Implement `_merge_paper_inspire`
that writes ONLY the INSPIRE-owned columns (`doi`, `journal_ref`,
`inspire_id`) and never touches `title`/`abstract`/`authors`/`year`/
`categories`. This makes the source-ownership rule structural, not predicate
logic — a future reader can see at a glance "OpenAlex owns prose; INSPIRE
owns identifiers and bibliographic ref." A shared `_merge_paper(source, …)`
with a source-rank table is more elegant but invites an off-by-one ownership
bug; the split form is brittle in a safe direction.

### `_merge_cite` and AC#3 semantics

The Cypher is:

> `MERGE (a)-[r:cites {source: $source}]->(b)`

Source is **part of the relationship's MERGE key.** `(a,b,"openAlex")` and
`(a,b,"inspire")` are distinct edges. This is the *intended* semantics for
AC#3 ("existing `source="openAlex"` edges are not duplicated or
overwritten") — the brief is asking for additive enrichment, and the schema
already permits it. **Confirm:** AC#3 is satisfied automatically by reusing
`_merge_cite(source="inspire", confidence=1.0)`; no special "skip if exists"
logic is needed. There is one downstream concern: `cite_neighbors` (E09_S03)
will need to deduplicate per (a,b) pair when both sources have the edge.
That's E09_S03's problem, not ours.

### Schema version bump

`KUZU_SCHEMA_VERSION = 1` (line 46 of `kuzudb_schema.py`). E09_S02 bumps to
`2`. `papers` gains three nullable columns; Kùzu's DDL for that is
`ALTER TABLE papers ADD doi STRING`, `ADD journal_ref STRING`, `ADD inspire_id
STRING`. Append the ALTERs to `SCHEMA_STATEMENTS` (idempotent: re-runs need
to detect "column already exists" — Kùzu raises on duplicate `ADD`; wrap each
ALTER in a try/except for `kuzu.RuntimeError` matching "already exists",
OR introspect `CALL TABLE_INFO('papers')` first and skip ADDs whose column is
present). The latter is cleaner and matches the "CREATE … IF NOT EXISTS"
spirit of the v1 statements.

### Response-byte cap

`OPENALEX_MAX_RESPONSE_BYTES = 5 * 1024 * 1024` (line 141). For INSPIRE,
live response inspection at `https://inspirehep.net/api/arxiv/1207.7214`
shows ~150 KB minified for the ATLAS Higgs paper (17,334 citations, hundreds
of authors). A paper with thousands of references could plausibly hit ~1-2
MB. **Use `INSPIRE_MAX_RESPONSE_BYTES = 8 * 1024 * 1024`** — slightly more
generous than OpenAlex because the references list is denser, but still
two orders of magnitude under the 200 MB arXiv tarball cap. Apply via the
same `body = resp.read(CAP+1); if len(body) > CAP: raise` pattern.

### `fetch_failures` and `_normalize_source`

The F3 pattern is reusable verbatim: `state["fetch_failures"]` list, `URLError`
records into it, re-runs drain it, CLI exits 1 while non-empty. Use the same
`_serialize_failures` helper. **`_normalize_source`** currently rejects
anything other than `"openalex"`; E09_S02 must extend it to accept
`"inspire"` / `"INSPIRE"` / `"Inspire"` and canonicalize to lowercase
`"inspire"`. The existing regression test
`test_f1_source_rejects_unknown_value` uses `"inspire"` as the *unknown*
case and expects rc=2 — **delete or rewrite that test** when E09_S02 lands,
since `"inspire"` becomes valid. Add new tests pinning all three casings.

### `tests/conftest.py` discipline

Autouse fixtures redirect `STORE_STATS_PATH`, `BM25_STATS_PATH`,
`BM25_INDEX_ROOT`, and `ARXMCP_CACHE_DB_PATH` into `tmp_path`. The INSPIRE
test should follow the `test_graph_ingest.py` pattern:
`monkeypatch.setattr(inspire_ingest, "_fetch_inspire_record", _stub)`,
per-test `db_path` + `checkpoint_path` fixtures, KeyError on unexpected
fixture lookup.

### Load-bearing design-note quotes

- `05-storage-and-indexing.md:211` — `source ENUM('inspire', 'openalex',
  'tex_extracted')`. Lowercase `'inspire'` is the canonical value (current
  graph uses camelCase `"openAlex"` — drift; E09_S02 should write lowercase
  `"inspire"` to match the design constitution, NOT camelCase `"INSPIRE"`).
- `05-storage-and-indexing.md:233` — *"INSPIRE-HEP for hep-th, math-ph
  (per-paper API enrichment, continuous)."* Matches the brief.
- `05-storage-and-indexing.md:236` — *"Don't try to extract `\\cite{}` from
  .tex and resolve them yourself — INSPIRE and OpenAlex have already done
  the disambiguation."* Validates the AC.
- `08-security-observability-ops.md:236` — *"Continuous   INSPIRE-HEP
  per-paper enrichment (15 rps)"*. **Conflicts with the brief's "≤5/sec"
  AC**; resolve in favor of the brief (5 rps is the conservative read of
  the API's "15 requests per 5s window" — 3 rps with bursting headroom is
  honest; 5 rps is the brief's safe ceiling).
- `03-ingestion-pipeline.md:65` — *"Free, generous limits (~15 rps with
  backoff), structured records with references already resolved to other
  arXiv IDs and DOIs."* Confirms references carry arXiv IDs directly; no
  second lookup needed for the in-corpus filter.

## 2. Prior decisions and lessons (the rect commit)

Commit `95fd3cf` closed 9 findings. Every one applies to INSPIRE:

- **F1** — `_normalize_source` must accept `"inspire"` / `"INSPIRE"` /
  `"Inspire"`, canonicalize to `"inspire"`. **Update existing
  regression**: `test_f1_source_rejects_unknown_value` uses `"inspire"` as
  the unknown case; that test must be rewritten with a different unknown
  value (e.g. `"semanticscholar"`).
- **F2** — INSPIRE needs its own response cap, NOT reuse of
  `OPENALEX_MAX_RESPONSE_BYTES`. The two services have different response
  shapes. Pin `INSPIRE_MAX_RESPONSE_BYTES = 8 MiB`.
- **F3** — same `fetch_failures` list, same CLI exit-1 path. Identical
  pattern; copy the structure.
- **F4** — *the big one*. Split-writer approach (above). Do NOT touch
  `_merge_paper`; introduce `_merge_paper_inspire` that only writes the
  three new columns.
- **F5** — reuse `tools.fetch_seed.read_seed_list` for the seed-file path
  (if INSPIRE ingest reads a seed file at all; see open questions). Do
  NOT carry a local copy.
- **F6** — bump `KUZU_SCHEMA_VERSION` from `1` to `2`. The `_schema_meta`
  MERGE is idempotent and re-writes the new value on re-run. Add a
  regression test like `test_stamps_schema_version` that pins v2.
- **F7** — atomic checkpoint write via `save_checkpoint`. If E09_S02
  uses a separate checkpoint file (recommended:
  `var/arxmcp/ops/inspire-ingest-checkpoint.json`), reuse the function
  verbatim — the same-fs invariant is already documented.
- **F8** — INSPIRE has `control_number` (the INSPIRE record ID). The
  arxiv-ID → inspire-ID mapping should detect collisions the same way
  `oa_work_id` collisions are detected; an arXiv ID resolving to two
  INSPIRE records is the "withdrawn / replaced version" case.
- **F10** — every assertion must be non-vacuous. No `or
  nested.parent.exists()`. Watch for `assert x is not None or y is None`
  shaped expressions.

**Instruction to the implementer:** `git show 95fd3cf` before writing a
single line of code. The body is 70 lines and re-reading it costs nothing.

## 3. External sources (INSPIRE-HEP REST API)

Confirmed live against the docs and one real response:

- **Endpoint shape.** Direct lookup is `GET
  https://inspirehep.net/api/arxiv/<arxiv-id>`. Accepts both new-style
  (`1207.7214`) and old-style (`hep-ph/0603175`) IDs. No auth. The
  search form `GET /api/literature?q=arxiv:<id>` also works but returns a
  search-hit envelope rather than a direct record — use the `arxiv/<id>`
  form to avoid an extra unwrap step.
- **Rate limit.** "*every IP address is allowed 15 requests in a 5s
  window*." That's 3 rps sustained, 15 rps burst. The brief's ≤5/sec AC
  is conservative; honor it. Inter-request sleep = `0.2 s`. On 429,
  the docs say *"requests that are blocked due to exceeding the rate
  limit count towards the quota, so you'll need to wait at least 5s when
  receiving a 429 response before trying again."* Set the 429 floor to
  5.0 s.
- **Polite pool.** No documented mailto convention. Send a User-Agent
  matching `arXMCP/0.1 (mailto:<email>)` — the existing
  `tools.arxiv_fetch.build_user_agent` template works as-is. Operators
  expect to find arXMCP traffic identifiable in their logs even if
  INSPIRE doesn't formally recognize the contact.
- **Response shape (top-level).** `{$schema, metadata, …}`. The
  citation-relevant fields live under `metadata`: `control_number` (int,
  the INSPIRE record ID), `references` (list), `arxiv_eprints` (list of
  `{value, categories}`), `dois` (list of `{value, …}`),
  `publication_info` (list of `{journal_title, journal_volume,
  journal_volume, year, page_start, page_end, …}`), `collaborations`
  (list of `{value, record}`), `citation_count` (int),
  `citation_count_without_self_citations` (int), `titles`, `authors`.
- **References sub-object.** Each `references[i]` has `curated_relation`,
  `legacy_curated`, `raw_refs` (unparsed), `record` (linkable to the
  cited INSPIRE record — `{$ref: ".../literature/<id>"}` form), and
  `reference` (parsed bibliographic data). The schema *does not*
  guarantee `reference.arxiv_eprint` is present on every reference —
  some references are book/conference-only. **Handle absent
  `reference.arxiv_eprint` by skipping the edge silently** (analogous
  to OpenAlex's `referenced_works` cross-corpus drop). When present,
  it's an arXiv ID string directly usable as `paper_id` in the existing
  graph — no second lookup pass is needed.
- **Pagination.** Single-record GETs do not paginate. Reference list is
  embedded in the record. The ATLAS Higgs paper (1207.7214) returns
  ~150 KB *with* the references inline; even a 1000-reference paper
  fits comfortably under the 8 MiB cap.
- **Schema versioning.** Each response carries `$schema` pointing to a
  doc URL. There's no per-version pin parameter; the brief's risk note
  ("field names can change") is best mitigated by snapshot-fixture
  tests, not API versioning.
- **`?fields=` filter.** `GET /api/arxiv/<id>?fields=control_number,
  references,arxiv_eprints,dois,publication_info` cuts the response by
  ~30-50% on author-heavy papers. Recommended for bandwidth and to
  reduce the parse surface that can drift on field renames.

## Open questions

- **The hep-th/math-ph filter problem (F9).** `papers.categories` currently
  carries OpenAlex Topics display names (`"Algebraic Geometry"`), not
  arXiv categories (`"hep-th"`). The brief's `categories LIKE '%hep-th%'`
  filter matches **zero rows** on any real seed corpus. `tools/seed-papers.txt`
  is all math.AG (IDs `2604.*`/`2605.*`). **Recommendation:** the integration
  test uses synthetic fixtures that pre-populate a paper with
  `categories="hep-th, math-ph"` (the column accepts arbitrary text); for
  the production run path, defer the real category-driven discovery to
  E09_S03+ and document the limitation in the CLI `--help`. **Do NOT**
  rename `categories` → `topics` in this milestone — that is a separate
  schema-rev touching every reader. F9 is deferred for a reason.
- **F4 design choice.** Recommended: split writers (`_merge_paper` stays
  OpenAlex-only; new `_merge_paper_inspire` writes only the three new
  columns). Source ownership is structural.
- **Reverse-mapping for INSPIRE references.** `references[i].reference.
  arxiv_eprint` is the arXiv ID directly. Filter against
  `MATCH (p:papers {paper_id: $id}) RETURN p` per reference. No
  INSPIRE-ID → arXiv-ID round trip is needed.
- **`_schema_meta` history.** Current shape stores a single
  `key="version"` row. Adding `applied_migrations = [1,2]` (a list)
  vs. just stamping the latest version. **Recommendation: keep the
  single-version-int form.** History is an audit nicety, not a
  correctness requirement; downstream cache invalidation in E09_S03
  keys on a single int. Add a JSON-string column later if needed.
- **`build_user_agent` reuse.** The template `arXMCP/0.1 (mailto:<email>)`
  is service-agnostic. INSPIRE will accept it. Reuse verbatim; do not
  fork.

## External writes the implementation will require

| type | target | why |
|---|---|---|
| API call | `GET https://inspirehep.net/api/arxiv/<id>` (live) | Required for end-to-end manual smoke test. CI must mock. |
| filesystem write | `var/arxmcp/ops/inspire-ingest-checkpoint.json` | Per-paper resolver checkpoint (atomic). |
| filesystem write | `var/arxmcp/index/kuzu/` (existing DB) | Schema v2 ALTERs + new INSPIRE rows/edges. |
