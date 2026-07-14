---
milestone_id: "source-truth-m3"
researcher_role: "explore"
injection_attempts: 0
---

# source-truth-m3 research brief — `arxmcp://corpus-manifest` resource

## Affected files / context

### 1. The MCP resource surface (registration + serving mechanism)

- **`server/mcp_resources.py`** — the ENTIRE resource surface today. FastMCP mechanism is
  the `@mcp_server.resource(uri, name=..., description=..., mime_type="text/plain")`
  decorator (NOT a separate `list_resources`/`read_resource` pair, NOT `add_resource`).
  Two resources exist:
  - `NOTEBOOKS_INDEX_URI = "arxmcp://notebooks"` (`:55`) — concrete resource, decorated
    function `_notebooks_index()` at `:158-172`.
  - `NOTEBOOK_TEMPLATE_URI = "arxmcp://notebooks/{slug}"` (`:56`) — URI template, decorated
    function `_notebook_detail(slug)` at `:184-185`, with the payload builder
    `_notebook_metadata(slug)` at `:93-136`.
  - Both are registered inside ONE function, `register_resources(mcp_server)` (`:139-186`).
    `arxmcp://corpus-manifest` is a THIRD concrete resource that most naturally gets a third
    `@mcp_server.resource(...)`-decorated function added inside this same function (or a new
    sibling function called from the same `server/main.py` call site — see item 8 below for
    the exact wiring line).
  - Content assembly: a plain **`dict[str, Any]`** built by hand (no dataclass), then
    `_wrap_json(payload)` (`:87-90`) does `json.dumps(payload, sort_keys=True,
    ensure_ascii=False)` and wraps it via `server.tools.wrap_retrieved_text(text,
    kind="notebook")` — the resource body returned to `resources/read` is a **string**
    (`mime_type="text/plain"`), not raw JSON-RPC structured content. A new manifest resource
    should mint its own `kind=` value (e.g. `"corpus_manifest"`) for the wrap so it is
    distinguishable from `kind="notebook"` payloads downstream.
  - Store wiring pattern: a **module-level `None`-initialized reference**
    (`_notebooks_store`, `:60`) set by `set_notebooks_store()` (`:63-70`, called from the
    FastAPI lifespan) and read via `_require_store()` (`:79-84`, raises `NotebookError` if
    unset — no confusing empty payload). A manifest resource that needs its OWN store
    (documents registry, override flags) should mirror this exact pattern, not thread a
    request-scoped dependency (resource callbacks get no FastAPI DI).
  - Security discipline to replicate: `validate_slug` FIRST for any per-slug path
    (`tools._notebook_common.validate_slug`, path-traversal guard before any store/FS
    access); operator-authored text wrapped in `<retrieved_*>` (Threat 2); **explicit
    allowlist-by-projection** on the returned dict (`:124-136` comment) — internal store
    fields (e.g. absolute `lancedb_path`) must NEVER be spread into the response.

- **`server/mcp_instructions.py`** — unrelated static content (the MCP `initialize`
  handshake hint string). Not touched by a new resource; cited only because the milestone
  brief asked to check it. Its own byte-pin (`EXPECTED_INSTRUCTIONS_SHA256`,
  `tests/test_mcp_instructions.py:27-29`) is a **third example** of this repo's
  "pin a SHA-256 of canonical bytes with an UPDATE-ANCHOR sentinel + rewrite helper" pattern
  (alongside `EXPECTED_TOOL_SCHEMA_SHA256`) — a useful precedent for how the manifest's own
  content-hash mechanics COULD be implemented, but note the important disanalogy in
  Open Question 2 below (that pin is static; a corpus manifest's hash is necessarily dynamic).

- **Exact wiring site** — `server/main.py` inside `create_app()`:
  ```
  843  register_all_tools(mcp_server)      # tools MUST come first (snapshot-at-mount)
  849  register_resources(mcp_server)      # from server.mcp_resources — MUST be before mount
  850  mount_mcp(app, mcp_server)          # streamable_http_app() snapshots registered state here
  ```
  A new resource must land inside/alongside `register_resources()`, i.e. between lines 843
  and 850 — same "after tools, before mount" snapshot constraint (comment at `:840-848`
  explains why). If the manifest resource needs a NEW store (documents registry aggregation,
  override flags), wire its module-level setter the same way `set_notebooks_store` is wired
  at `server/main.py:505-507` (inside the lifespan, right after the store opens).

### 2. Resources-list pin — confirmed NONE exists

- `tests/test_mcp_resources.py::TestByteStability` (`:94-121`) is the ONLY byte-stability
  guard touching resources, and it pins the opposite direction: it proves that registering
  resources does **NOT** change `EXPECTED_TOOL_SCHEMA_SHA256`
  (`tests/test_server_tool_schema.py:94-96`, currently `"5189d7a6...` / pinned at
  `TOOL_SCHEMA_VERSION=18`). Three tests do this: `test_tools_list_hash_unchanged_with_resources`,
  `test_resources_do_not_change_tools_vs_baseline`, `test_resources_add_no_tools` (asserts
  exactly 8 tools, unchanged, both with and without `register_resources`).
- A repo-wide grep for any `RESOURCE.*SHA256` / `EXPECTED_RESOURCE*` / resource-count pin
  found **zero matches** beyond the tool-schema files above. There is no
  `resources/list` byte-pin, no resource-count assertion outside
  `test_resources_add_no_tools` (which counts *tools*, not resources).
- **Implication for AC2**: "EXPECTED_TOOL_SCHEMA_SHA256 stays UNCHANGED" is mechanically easy
  to satisfy — `resources/list` is a distinct JSON-RPC method
  (`mcp.list_resources()`/`mcp.list_resource_templates()`, exercised at
  `tests/test_mcp_resources.py:124-138`) that never enters `tools/list` serialization. The
  new milestone's test obligation is to ADD a fourth `TestByteStability`-style assertion
  (extend the existing class or add a sibling test module) proving the SAME invariant holds
  for the manifest resource specifically — there is no existing test that will auto-catch a
  manifest-resource regression; it must be net-new.

### 3. m1's registry — `server/documents_store.py`

- `DocumentsStore` (`:131-334`), one SQLite file per notebook at
  `var/arxmcp/notebooks/<slug>/documents.db` (`DOCUMENTS_DB_FILENAME`, `:83`).
- `DocumentRecord` (`:104-129`) fields the manifest needs: `work_id`, `arxiv_version`
  (PK is `(work_id, arxiv_version)`, `:198` in the CREATE TABLE — first revision-identity
  store in the repo), `raw_source_sha256` + `raw_source_status` (`'present'`/`'unavailable'`
  abstention marker for old-style papers), `parse_artifact_sha256`, `chunker_version`,
  `parser_used` + `latexml_version` (both NULL in m1 — no per-paper signal exists yet),
  `fetched_at`, `license_uri`, `license_status` (3-way: `eligible` /
  `not-allowlisted-open` / `unknown`), `status` (`active` / `withdrawn` / `superseded` —
  `superseded` is a reserved value m1 never writes; `withdrawn` comes from OAI-PMH
  `<header status="deleted">`).
- **Enumerate ALL revisions**: `await store.all_records()` (`:313-323`) — ordered by PK,
  no pagination, this is the read path `tools/documents_coverage_report.py` already uses
  and the manifest should reuse identically.
- Opening the store: `DocumentsStore.open(db_path)` (`:150-209`), idempotent, `PRAGMA
  user_version` + WAL + `synchronous=NORMAL` (regenerable data, lighter durability tier
  than `notebooks.db`'s `FULL`+`fullfsync`).
- **Live on-disk state verified**: only 2 of 5 notebooks under `var/arxmcp/notebooks/` have
  a `documents.db` today — `bridgeland-stability` (confirmed, `corpus-version.json`:
  `chunk_count=15106, paper_count=145, version=4458, chunker_version="v1.1",
  embedder_version="bge-m3@5617a9f6"`) and `fourier-duality`. `bridgeland-stability-pdfs`,
  `fourier-duality-pdfs`, and `demo-nb` have NO `documents.db` (matches
  `tools/documents_coverage_report.py:66-69`'s `DEFAULT_NOTEBOOKS` hardcoding to exactly
  those two). The manifest MUST define a degrade path for un-hydrated notebooks.

### 4. The `corpus_version` epoch

- **`server/corpus.py`** — `CorpusVersionInfo` dataclass (`:329-362`): `version` (int, the
  LanceDB MVCC integer AND the cache-namespace key — `chunker_version`/`embedder_version`
  are informational only, must never enter cache keys), `chunker_version`,
  `embedder_version`, `created_at`, `paper_count`, `chunk_count`.
- **`read_corpus_version(lancedb_path)`** (`:479-538`) reads `corpus-version.json`
  (`CORPUS_VERSION_MARKER_NAME = "corpus-version.json"`, `ingest/store.py:133`) sitting next
  to the LanceDB dataset dir. Returns `None` if absent (cold-start signal — must be handled
  gracefully, not raised), raises `ValueError` if present-but-malformed.
- **Per-notebook, not global**: each notebook has its OWN `lancedb/corpus-version.json` at
  `notebook_lancedb_path(slug)` = `notebook_dir(slug) / "lancedb"`
  (`tools/_notebook_common.py:126-141`). Live-verified:
  `var/arxmcp/notebooks/bridgeland-stability/lancedb/corpus-version.json` exists and parses
  cleanly. So the manifest's `corpus_version` epoch is a **per-notebook field**, not a
  single server-wide value — mirrors how `Resources.notebook_table()` (`server/resources.py`
  — NOTE: this is the `Resources` *process-lifecycle dataclass* module, see Open Question 1
  — `:1172-1241`) lazily opens per-notebook LanceDB handles today.

### 5. Index build versions

- `chunker_version` — `CHUNKER_VERSION = "v1.1"` (`ingest/chunker_types.py:45`), a flat
  string constant, already a `DocumentRecord` field AND a `CorpusVersionInfo` field
  (written once per corpus build, once per revision — the two should agree but are
  independently sourced today).
- `embedder_version` — `EMBEDDER_VERSION = f"bge-m3@{BGE_M3_COMMIT_SHA[:8]}"`
  (`ingest/embedder.py:136`), already a `CorpusVersionInfo` field.
- **BM25 index "version"** — there is NO separate BM25 version string. The BM25 artifact is
  directory-versioned by the SAME `corpus_version` int: `var/arxmcp/index/bm25/v<N>/{bm25.pkl,
  chunk_ids.json}` (`_bm25_version_dir`, `ingest/bm25_indexer.py:108-130`; the docstring
  at `:1-71` confirms one-index-per-corpus-version, built via `build_bm25_index`, and is
  currently a MANUAL post-ingest step, not auto-wired to `write_chunks`). For the manifest,
  "BM25 index build version" == the notebook's `corpus_version` int — no independent field
  exists to surface.
- **LanceDB library version** — `pyproject.toml:71` pins only a floor, `lancedb>=0.6`; the
  installed version (`0.30.2`, per a live-verified comment in `server/resources.py:273-274`)
  is NOT persisted anywhere per-notebook or per-corpus-build. If the manifest wants to
  surface "the LanceDB format/library version this notebook was built with," that signal
  does not exist today and would need a NEW capture point (e.g. `importlib.metadata.version
  ("lancedb")` stamped into `corpus-version.json` at write time) — out of scope for a
  read-only resource milestone; the manifest can only read what's already captured
  (`chunker_version`, `embedder_version`, `version`).

### 6. Per-notebook operator override flags — confirmed NEW, nothing exists today

- Repo-wide grep for `notebook_override` / `license_override` / `operator_override` /
  `per_notebook_override` / `fail_closed_override` returned **zero matches**. Nothing in
  `server/config.py` (env-var config is process-wide `ARXMCP_*`, wrong shape for a
  multi-notebook server — a single process can serve N notebooks via
  `Resources.notebook_table()`, so a `ARXMCP_*` env var cannot scope to one slug at a time).
- **Context**: `plans/source-truth/roadmap.yaml:44` and
  `.claude/roadmap-briefs/R1-source-truth.md:78-79` both describe this as the escape hatch
  for spike-1's >20%-unknown-license escalation on `bridgeland-stability` — "a per-notebook
  operator override flag (recorded in the manifest) as the documented escape hatch." m1's
  own implementation synthesis (`.claude/notes/milestones/source-truth-m1/implement/synthesis.md`)
  confirms m1 shipped ONLY the registry + advisory decision fn + coverage report — no
  override-flag storage. **This IS new plumbing for m3, not a wiring task.**
- **Nearest existing precedent**: `server/operator_settings.py` — a flat SQLite key-value
  store (`operator_settings` table in the CENTRAL `notebooks.db`, sibling of
  `NotebooksStore`'s own tables but migration-independent via an in-table
  `__schema_version__` sentinel, `:74-100`). Today's only key is `contact_email` (+
  `mineru_bin`); both module docstring (`:8-9`) and design explicitly anticipate "Future
  keys: wizard dismissal-state, last-ingest timestamp, etc." The cheapest-consistent
  extension is a **namespaced key convention** (e.g. `license_override:<slug>`) reusing this
  store as-is (zero schema migration) rather than adding a new column to `notebooks` table
  (`SCHEMA_VERSION` bump, `server/notebooks_store.py:83`) or a new per-notebook file. This is
  a genuine design decision for Phase 2, not something this research brief should resolve.

### 7. The 3-sample-paper re-verify path (AC1)

- Raw source root: `CORPUS_RAW_DIR = REPO_ROOT/var/arxmcp/corpus/raw`
  (`tools/_notebook_common.py:41`); parsed root: `CORPUS_PARSED_DIR =
  REPO_ROOT/var/arxmcp/corpus/parsed` (`:34`). Both confirmed live-populated
  (`var/arxmcp/corpus/raw/0705.3794/`, `var/arxmcp/corpus/parsed/0705.3794/` etc. exist on
  disk).
- The EXACT hashing functions already used to produce the checksums the manifest would
  report — reuse these, do not reinvent:
  - `_hash_raw_source_tree(raw_dir)` (`tools/notebook_documents_backfill.py:124-147`) —
    deterministic sha256 over every file's POSIX-relative-path + byte-length + bytes in
    sorted order, of `CORPUS_RAW_DIR/<work_id>/`. Returns `None` for the old-style
    abstention case (dir absent/empty).
  - `_parse_artifact_sha256(work_id, parsed_root)` (`:165-171`) — sha256 of the single file
    `CORPUS_PARSED_DIR/<work_id>/index.html`.
  - Both are called from `_build_record()` (`:188-220`) at registration time and the
    resulting digests are what's already stored in `DocumentRecord.raw_source_sha256` /
    `.parse_artifact_sha256`.
- **AC1 test shape**: pick 3 real on-disk work ids from a hydrated notebook (e.g. 3 of the
  145 `bridgeland-stability` papers), call `_hash_raw_source_tree` /
  `_parse_artifact_sha256` fresh against the SAME on-disk paths, and assert the result
  equals what the manifest resource reports for those revisions. "Re-fetch" most plausibly
  means "re-hash the existing on-disk artifact tree" (no network egress implied by AC1's
  own wording, and re-fetching from arXiv would violate the politeness/idempotency
  discipline every other tool in this family observes) — but see Open Question 4.

### 8. Tests — the template

- **`tests/test_mcp_resources.py`** (321 lines, read in full) is the exact template:
  `res_env` fixture (private-loop `NotebooksStore` wired via `set_notebooks_store`,
  `:42-58`), `_mcp_with_resources()` helper (`:87-91`, `register_all` then
  `register_resources`), `_read_text()` helper unwrapping the `<retrieved_*>` envelope
  (`:80-84`). Four test classes to mirror: `TestByteStability` (hash-invariance — the AC2
  proof), `TestResourceListing` (URI appears in `list_resources()`/
  `list_resource_templates()`), `TestIndexRead`/`TestDetailRead` (shape assertions +
  `assert "lancedb_path" not in meta` style allowlist checks), `TestIndirectPromptInjection`
  (delimiter-breakout + escape-on-emit checks for ANY operator-authored string field the
  manifest surfaces, e.g. `license_uri` or a notebook `display_name` if re-included),
  `TestStoreNotReady` (resource read before lifespan wiring raises cleanly).

## Acceptance criteria the implementer must meet

1. Register `arxmcp://corpus-manifest` via `@mcp_server.resource(...)` inside/alongside
   `register_resources()` in `server/mcp_resources.py`, wired at `server/main.py:849` (after
   `register_all_tools`, before `mount_mcp`) — same snapshot-at-mount constraint as the
   existing two resources.
2. Add a `TestByteStability`-equivalent test proving `EXPECTED_TOOL_SCHEMA_SHA256`
   (`tests/test_server_tool_schema.py:94-96`, currently pinned at
   `TOOL_SCHEMA_VERSION=18`) is byte-identical with and without the new resource registered
   — this does not exist yet for a THIRD resource and must be added net-new (AC2's binding
   half).
3. For each notebook (`NotebooksStore.list_notebooks()`), assemble: its `DocumentsStore
   .all_records()` (checksums + status per revision), its `read_corpus_version(lancedb_path)`
   (the `corpus_version` epoch + `chunker_version`/`embedder_version`), and a license summary
   mirroring `tools/documents_coverage_report.py`'s `_analyze()`/`CoverageStats` shape
   (per-`license_status` + per-id-shape counts) — reuse, don't reimplement, the aggregation
   logic already shipped there.
4. Checksums must be re-verifiable: a live test recomputes `_hash_raw_source_tree` /
   `_parse_artifact_sha256` (`tools/notebook_documents_backfill.py:124-171`) against 3 real
   on-disk sample papers and asserts equality with the manifest's reported values (AC1,
   roadmap `plans/source-truth/roadmap.yaml:280`).
5. A `status="withdrawn"` or `"superseded"` `DocumentRecord` must cause its manifest entry to
   carry an explicit invalidation marker (field name/shape is an implementation decision —
   see Open Question 3) while leaving unaffected revisions/notebooks untouched — "edges only,
   no takedown" (roadmap `:281`) means no data is deleted, only flagged/referenced.
6. Per-notebook operator override flags need NEW storage (none exists — Section 6 above);
   whatever mechanism is chosen, its current value must be surfaced per-notebook in the
   manifest response, and the response must follow the existing allowlist-by-projection +
   `<retrieved_*>`-wrap + escape-on-emit discipline (`server/mcp_resources.py:87-90,
   124-136`; `tests/test_mcp_resources.py::TestIndirectPromptInjection`) for any
   operator/license-uri string field.

## Risks and open questions

1. **The roadmap's own code links for m3 are misleading.** Both
   `plans/source-truth/roadmap.yaml:283` and the milestone's `state.json` list
   `server/resources.py` as a target file — but that module is the `Resources`
   process-lifecycle dataclass (BGE-M3/LanceDB/cache singletons, `app.state.resources`),
   **not** the MCP resources surface. The actual target is `server/mcp_resources.py`. The
   second linked file, `server/paper_metadata_store.py`, is a pattern precedent (per-notebook
   SQLite store shape) that `server/documents_store.py` already mirrors — it is very unlikely
   this milestone needs to edit that file directly. Flag this explicitly to the implementer
   so Phase 2 doesn't start by modifying the wrong module.
2. **"Content-addressed" is underspecified.** `.claude/roadmap-briefs/R1-source-truth.md:54-57`
   says downstream artifacts (R4/R5) "reference the manifest hash, not the epoch alone" —
   implying the manifest response needs a self-referential content-hash field. Unlike
   `EXPECTED_TOOL_SCHEMA_SHA256` / `EXPECTED_INSTRUCTIONS_SHA256` (static pinned test
   constants for content that changes only on a deliberate code edit), a corpus manifest's
   hash is **dynamic** — it changes every time a paper is added/backfilled/re-ingested. No
   existing precedent in this repo computes a hash-of-live-mutable-state for external
   reference (as opposed to hash-of-frozen-source-bytes). The canonicalization rule (which
   fields feed the hash, `sort_keys`+`separators` convention reuse) is undefined and should
   be nailed down at decomposition/implementation, not assumed.
3. **"Edges only, no takedown" (AC2) is ambiguous between two very different scopes.** It
   could mean (a) a lightweight JSON pointer/reference field inside the manifest response
   itself (e.g. an invalidated revision's entry carries a `superseded_by` string), or (b) an
   actual new KùzuDB `REL TABLE` for withdrawal/supersession relationships. Checked
   `ingest/kuzudb_schema.py`: only ONE rel table exists today, `cites` (`:85`) — nothing for
   withdrawal/supersession, despite the parent roadmap brief's broader vision naming
   "withdrawal/corrigendum/supersession edges" as a top-level initiative goal (roadmap.yaml
   line 26). Given m3 is Size=S, depends ONLY on `source-truth-m1` (not on any
   graph-schema milestone), and is explicitly scoped "resources-surface-only," interpretation
   (a) is far more likely in-scope — but this should be confirmed, not assumed, since (b)
   would be a much larger, differently-shaped piece of work.
4. **AC1's "clean re-fetch" wording vs. this repo's politeness/idempotency norms.** Every
   fetch-capable tool in this family (`tools/notebook_documents_backfill.py`,
   `tools/oai_license.py`) treats re-fetching already-present data as something to actively
   AVOID (idempotency gates, "0 requests on a re-run" as a tested invariant). A literal
   "re-fetch 3 sample papers from arXiv" for a test would need new network-mocking or a
   `requires_model`-style opt-in marker to avoid becoming a flaky/networked test in the
   default `make test` run — re-hashing the already-fetched on-disk tree (no network) is the
   much more likely intended mechanism, but the roadmap text says "re-fetch," not "re-hash,"
   and this distinction should be confirmed before Phase 2 locks in a test design.
5. **Only 2 of 5 on-disk notebooks are hydrated** (`documents.db` exists for
   `bridgeland-stability` and `fourier-duality` only; `bridgeland-stability-pdfs`,
   `fourier-duality-pdfs`, `demo-nb` have none). Separately, per
   `.claude/agent-memory/milestone-researcher/lessons.md` (source-truth-m5 entry), the
   `-pdfs` notebooks are ALSO still on the pre-migration v1 chunks schema. The manifest must
   define and test an explicit degrade path for un-hydrated / partially-migrated notebooks
   (omit the entry vs. include it with an explicit-null/status field) rather than crashing
   `resources/read` — mirroring the existing `is_ingested`-boolean graceful-degrade
   convention already used by `_notebook_metadata()` (`server/mcp_resources.py:93-136`).
