---
milestone_id: "source-truth-m2"
researcher_role: "explore"
date: "2026-07-13"
injection_attempts: 0
title: "source-truth-m2 codebase map — schema/migration mechanism, truncated-flag drop point, printed-number extraction site, m1-registry join, backfill mutation mechanism"
---

# source-truth-m2 research brief — codebase map

Read-only exploration. No code edited, no git operations. Grounded on `CLAUDE.md` §§4.5/4.7/4.8/4.9
and the three load-bearing spike notes (`source-truth-spike-2/3/4`), which have already resolved
most of m2's design questions (printed-number coverage clears 80%; the span anchor must be
`(revision_checksum + normalized_text_hash)` as a STRING, not `char_offset`, not a struct; the
5-column migration rides the existing `_migrate_chunks_schema_if_needed` mechanism cleanly if
`source_span` stays a string). This brief maps the remaining unresolved piece: how the
5 columns actually get **populated** on ~15,106 EXISTING chunk rows without re-embedding —
which none of the three spikes exercised.

## Affected files / context

### 1. Schema + migration — where the 5 columns slot in

- `ingest/schema.py` `CHUNKS_SCHEMA_V1` (:121-210) — 21 fields today, declaration order ends at
  `parser_used` (:208). The `# ---- textbook-ingest-m2 columns ----` comment block (:169) is the
  precedent pattern to mirror one section further down for source-truth-e2's 5 columns.
- `ingest/store.py::_migrate_chunks_schema_if_needed` (:330-411), `_TEXTBOOK_MIGRATION_DEFAULTS`
  (:319-327), the `merge_insert` writer inside `write_chunks` (:868-873).
- **Name collision warning:** the shipped migration and its tests are literally named for
  "textbook-ingest-m2" — a DIFFERENT, already-completed milestone that happens to share the "m2"
  suffix with source-truth-m2. Don't conflate the two "m2"s when reading code, comments, or test
  names below.
- Spike-4 (dry-run against a copy of the live 15,106-row table) confirmed: the 4 pure-scalar
  columns (`source_revision_id` str, `truncated` bool, `printed_number` str, `license_ref` str)
  ride the existing `dict[str,str]` SQL-expression `add_columns` path completely unmodified — one
  `cast(NULL as string)` / `cast(NULL as boolean)` entry each in `_TEXTBOOK_MIGRATION_DEFAULTS`,
  one nullable field each appended to `CHUNKS_SCHEMA_V1`. `source_span` only needs the OTHER
  `add_columns` call form (`pa.field(...)`, not the SQL-dict form) if declared as a struct — spike-4
  reproduced the exact DataFusion parser failure for a struct SQL-cast. **Spike-3 recommends
  `source_span` be a plain string** (see §4), in which case all 5 columns go through the identical
  single-loop SQL-dict mechanism and no struct-dispatch branch is needed at all.
- The `alter_columns` nullability fixup loop (:395-403) is a correct no-op for all 5 new columns
  (NULL-defaulted → infers `nullable=True` directly, unlike textbook-ingest-m2's non-null
  `'arxiv'`/`'arxiv-license'` literals) — confirmed empirically by spike-4 (0/5 fixups fired).

### 2. The `truncated` flag — already computed, silently dropped

- `ingest/chunker_types.py:169` — `ChunkRecord.truncated: bool = field(default=False)`; its
  docstring (:109-112) states explicitly "NOT persisted to LanceDB — runtime signal only."
  `to_dict()` (:186-207) DOES include it (:206), so it reaches the per-chunk JSON files under
  `var/arxmcp/corpus/chunks/<paper_id>/` — just not the LanceDB row.
- Set at 3 sites in `ingest/chunker.py`, all via `_truncate_to_token_budget` (:539-558, returns
  `(text, bool)`, substring-slices rather than encode/decode round-tripping):
  1. Statement chunks (the theorem-scan site, §3 below): call at :695-697, `ChunkRecord(...,
     truncated=stmt_truncated)` at :716.
  2. Section-prose chunks (`_extract_section_chunks`): call at :808, `truncated=prose_truncated`
     at :827.
  3. Section-less-fallback chunks (`_extract_body_fallback_chunks`): call at :919-921,
     `truncated=truncated` at :933.
  Proof-window chunks (`_window_proof_text`, def :497+, called at :618 and :724-725) never set
  `truncated=` — correctly: windowing splits a long proof into overlapping windows that together
  cover the full text, so no individual window is a lossy truncation.
- `STMT_MAX_TOKENS = 1920` at :92; `PROOF_MAX_TOKENS = 1856` at :89.
- **Drop point confirmed**: `ingest/store.py::_build_arrow_table` (:414-564) builds the per-chunk
  row dict at :528-563 — 17 keys, no `"truncated"` entry anywhere. `ChunkRecord.truncated` is read
  nowhere in this function. This is the literal silent-drop the roadmap brief names.

### 3. Printed-number extraction site — nothing extracts it yet; here is where to add it

- `_THEOREM_CLASS_RE = re.compile(r"\bltx_theorem_(\w+)\b")` (:99), matched against
  `_get_classes(child)` in the theorem-scan loop at :638-643 (inside `_extract_chunks_from_container`,
  entered :566). This class-match does **not** gate on `child.name` — so spike-2 recommendation
  (b), "match `ltx_theorem` on any element, not just `<div>`," is **already satisfied** at this
  step; no code change needed here. The real F5 gap spike-2 flagged (a theorem nested inside a
  `<li>`, e.g. `1804.00132`) lives one level up: the recursion decision at :647
  (`if child.name in {"section", "div", "article"}:`) plus the exclusion set at :651-655
  (`{"p","table","figure","ul","ol","dl","h1"…"h6","math","span","a"}` — explicitly excluded from
  the defensive-recurse fallback) means `<ul>`/`<ol>`/`<dl>` are never recursed into at all, so a
  theorem nested inside a list item is never visited. Confirmed real (not just spike-2's own
  caveat) but **orthogonal to printed_number and out of m2's 5-column scope** — a chunk that's
  never emitted has no printed_number either way regardless of extractor quality. Flagging so the
  implementer doesn't scope-creep into fixing list traversal under this milestone.
- `env_name = thm_match.group(1)` (:663) is the CSS class suffix (e.g. `"lemma"`, or a custom
  `"ttt"`/`"Mukai"`). `_env_kind(env_name)` (:474-484, using `_THEOREM_ENV_KINDS` :179-226) maps it
  to the stored `kind` column, defaulting unknown envs to `"stmt"` — its own docstring records this
  fixed a real bulk-ingest crash. Spike-2 F4 flagged env_name/CSS-class-suffix as unreliable
  specifically for **kind** classification (custom `\newtheorem` names render as literal, undescriptive
  class suffixes) — but `_env_kind`/`kind` is a separate, already-shipped column NOT in m2's
  5-column list. printed_number extraction does not require touching `_env_kind`: every matched
  `ltx_theorem_*` div gets some `kind` regardless, and printed_number should be extracted
  independently of it.
- `theorem_label = _extract_theorem_label(child)` (:665, fn :418-430) and `theorem_name =
  _extract_theorem_name(child)` (:666, fn :433-471) are the two existing analogues — this is where
  printed_number extraction slots in. `_extract_theorem_name`'s `heading_candidates` loop (:456-461)
  already finds `<span class="ltx_tag ltx_tag_theorem">` direct children and reads their
  `_element_text()` (:464, the math-fidelity-preserving extractor at :328-362); today that text is
  searched ONLY for a parenthetical name (`_PAREN_NAME_RE = re.compile(r"\(([^)]+)\)")` at :103,
  applied :465-469). **printed_number extraction is a new, additive sibling function** that should
  reuse the same `heading_candidates` text and apply a NEW trailing-number regex — spike-2's
  validated pattern `[A-Za-z]?\.?\d+(\.\d+)*` anchored at the end of the tag text, hand-confirmed
  correct in spike-2 §3e including the single-letter appendix-prefix case and a case where the
  LaTeXML **id** (`A2.ThmThm1`) disagreed with the **rendered** printed prefix (`"B.1"`) — proving
  the rendered tag text, never the id or class, is the only reliable source. Wire the result into
  `ChunkRecord` at the same construction sites as `theorem_label`/`theorem_name` (:707-718 for the
  stmt chunk; proof chunks at :728-738 inherit `theorem_name`/`theorem_label` from the paired
  statement and should presumably inherit `printed_number` the same way).
- `_extract_theorem_label`'s auto-ID-nulling (:418-430) is the "TeX `\label` stored, auto-IDs
  nulled" behavior the roadmap brief points at — printed_number is a *different* signal (the
  rendered "Lemma 3.2" text) that exists independently of whether a `\label{}` was given.

### 4. The span + revision link — m1's documents registry

- `server/documents_store.py` — `DocumentRecord` (:104-129), `DocumentsStore` (:131-334), one
  SQLite file **per notebook** at `var/arxmcp/notebooks/<slug>/documents.db` (:79-83), PRIMARY KEY
  `(work_id, arxiv_version)` (:37, :198). Carries `parse_artifact_sha256` (:121 — sha256 of
  `parsed/<work_id>/index.html`), `license_uri` (:126) + 3-way `license_status` (:127 — values
  `eligible` / `not-allowlisted-open` / `unknown`, from `tools/oai_license.py`), `raw_source_sha256`
  + `raw_source_status` abstention pair (:119-120), `status` (active/withdrawn/superseded, :128).
- **Join mechanics — the part that needs care.** `ChunkRecord.paper_id` (and the LanceDB
  `paper_id` column) is always version-stripped (`chunker_types.py` docstring :62-64), which is
  byte-identical in form to the registry's `work_id` — so `chunk.paper_id == work_id` directly,
  no transform needed. But `arxiv_version` is **not derivable from the chunk row at all**: it comes
  only from whatever explicit `vN` suffix was on the matching `papers.txt` line
  (`tools/notebook_documents_backfill.py::_Membership`, :179-185; extracted at :358-375, literally
  `version = line.strip()[len(work_id):]`). Since most `papers.txt` lines are bare ids,
  `arxiv_version` is `""` for the common case (confirmed by source-truth-m1 brief-1.md: "arXiv
  version... Not persisted anywhere today... The registry is the first place... that needs to
  retain vN"). **Consequence: the m2 backfill cannot resolve `source_revision_id` from the chunk
  alone — it must walk the same `papers.txt` membership parse `notebook_documents_backfill.py`
  used** (or query the registry by `work_id` and take the row(s) found).
- `parse_artifact_sha256` is the natural candidate for spike-3's recommended `source_span`
  "revision_checksum" component — computed from the exact same file
  (`var/arxmcp/corpus/parsed/<paper_id>/index.html`) that `ingest/chunker.py::_chunk_paper_impl`
  already reads into `html_bytes` at :1017. See Risks §2 for a consistency caveat if this ever
  gets recomputed independently instead of read from the registry.
- `license_ref`'s exact value contract is **underspecified** in every source document read (roadmap
  brief, m2 milestone brief, both m1 research briefs) beyond "per-revision license record id" — m1's
  registry has no separate "license record" entity distinct from the per-revision `DocumentRecord`
  row itself. See Risks §3.
- `server/license_policy.py` (`OA_ALLOWLIST` :44-53, `is_open_access()` :56-66) is the existing,
  unrelated, **token**-based (not URI-based) serving-time check `get_chunk`
  (`server/handlers/chunk.py:94-98`) already calls against the pre-existing `license` column. Per
  the roadmap brief and m1 brief-2's "License-decision semantics" section, this stays untouched by
  source-truth-m2 — m2 only persists `license_ref` as a pointer; the fail-closed cutover that
  consumes it is m4, explicitly out of m2's scope.

### 5. The backfill precedent — and where it does NOT transfer

- `tools/notebook_metadata_backfill.py` + `tools/notebook_documents_backfill.py` share a
  structural pattern worth copying: `papers.txt` (not the empty `notebook_papers` junction table)
  is membership truth; test seams (`base`/`sleep`/`fetch` kwargs on `run()`); idempotency via
  "already have a good value, skip" gates; a machine-parseable one-line summary
  (`registered=N skipped=M missing=K malformed=J unique=U total=T`,
  `notebook_documents_backfill.py:407-414`) that keeps a zero-row run loud — the natural template
  for m2's AC3 abstention report.
- **But neither precedent mutates the LanceDB `chunks` table.** `notebook_metadata_backfill.py`
  writes to `paper_metadata.db`; `notebook_documents_backfill.py` writes to `documents.db` — both
  brand-new, separate per-notebook SQLite files. m2 is structurally different: the 5 new columns
  are declared ON the `chunks` LanceDB table itself, so the backfill must mutate ~15,106 EXISTING
  LanceDB rows in place.
- **This is a real mechanism gap neither spike-4 nor any shipped code has exercised.** Spike-4
  validated only "add 5 NULL-defaulted columns via schema-level `add_columns`" (metadata-only,
  <1s, zero new data files) — it did NOT test writing real, per-row COMPUTED values into existing
  rows. The obvious `ingest/store.py::write_chunks` path
  (`merge_insert("chunk_id").when_matched_update_all()`, :868-873) is the wrong tool for this:
  `when_matched_update_all()` replaces the ENTIRE matched row with the incoming Arrow table's row,
  and `_build_arrow_table` (:414-564) raises `ValueError` (:451-455) if any chunk_id is missing an
  embedding — using it forces either fabricating/copying all 15,106 embedding vectors into every
  backfill call (safe if done correctly — byte-identical copy, the same technique
  `ingest/re_embed.py`'s "copy path" already uses for a different problem — but easy to get wrong)
  or bypassing `write_chunks` entirely.
- **Live-verified better mechanism:** the installed `lancedb==0.30.2`'s
  `Table.update(where: str, values: dict)` (confirmed this session via direct
  `inspect.signature`/docstring introspection on `lancedb.table.Table.update`) updates ONLY the
  named columns for rows matching a SQL `where` clause, leaving every other column — including
  `embedding_stmt`/`embedding_proof` — completely untouched. Example from the live docstring:
  `table.update(where="x = 2", values={"vector": [10.0, 10]})`. Grepped `ingest/` for `.update(`
  against LanceDB tables: **zero hits** — this would be new code, but it is the mechanism that
  actually satisfies AC2's "0 chunks re-embedded" at the LanceDB-API level. Caveat: `values` applies
  the same dict to every row matched by one `where` clause, so per-chunk-unique values
  (printed_number, source_span, truncated) need either ~15,106 individual per-chunk `.update()`
  calls (each its own MVCC version) or a read-modify-write batch via `merge_insert` instead — see
  Risks §1.
- `ingest/re_embed.py` (:1-34) solves a *different* problem (chunker/embedder version bumps) by
  staging a whole new table under `lancedb-staging/` and cutting over; cited only because its
  "copy vectors without recomputing" pattern is the closest existing precedent if the implementer
  chooses the read-modify-write `merge_insert` path over `Table.update`.
- `tools/oai_license.py`'s module docstring (:10-19) records a directly-relevant lesson: importing
  `ingest.oai_delta` pulls in `ingest.bulk_ingest` → the BGE-M3 embedder transitively, so m1's
  documents backfill deliberately avoided that import chain to keep "0 chunks re-embedded"
  **structural**, not just behavioral. The same discipline should apply to m2's backfill: connect to
  LanceDB directly (`lancedb.connect(...).open_table(CHUNKS_TABLE_NAME)`) rather than routing
  through `ingest.store.write_chunks`, so the embedder is never imported at all.

### 6. Confirmed: m2 does not touch the tool surface

- `server/handlers/chunk.py::handle_get_chunk` (:33-157) builds its `chunk` dict explicitly
  field-by-field (:99-113: `body_text`, `chunk_id`, `chunker_version`, `embedder_version`, `kind`,
  `license`, `paper_id`, `preamble_ref`, `section_path`, `theorem_label`, `theorem_name`). None of
  the 5 new columns are referenced anywhere in this file — adding LanceDB columns is invisible to
  this handler by construction (it projects named fields from the Arrow row; unprojected columns
  are simply ignored). m2 requires zero changes here; tool-visible surfacing is m5, per the roadmap.
- `tests/test_server_tool_schema.py`'s `EXPECTED_TOOL_SCHEMA_SHA256` (:94-96) hashes the
  wire-equivalent JSON of the MCP `tools/list` response (tool names/descriptions/argument schemas
  from `server/tools.py::ALL_TOOLS`) — entirely independent of the internal LanceDB row schema.
  Confirmed no coupling exists today. m2 stays outside this gate as long as the implementer doesn't
  also (out of scope) touch `chunk.py`'s handler signature or `ALL_TOOLS`.

### 7. Test surfaces / templates

- `tests/test_store.py:820-1290` ("textbook-ingest-m2 — round-trip + migration tests") is the
  direct template: `test_migration_adds_seven_columns_with_arxiv_defaults` (:1048),
  `test_post_migration_nullability_matches_canonical` (:1099),
  `test_merge_insert_update_on_migrated_table` (:1136), `test_migration_is_idempotent` (:1212 — the
  literal AC1 "second run is a no-op" shape), `test_migration_unhandled_column_raises` (:1232),
  `test_migration_extensible_with_new_default` (:1259). Same name-collision caveat as §1: these
  tests belong to the already-shipped, differently-scoped "textbook-ingest-m2."
- `tests/test_chunker.py` — `_extract_theorem_label`/`_extract_theorem_name` tests at :491-556
  (`test_auto_id_returns_none`, `test_custom_label_returned`, `test_parenthetical_name_extracted`,
  `test_span_tag_extracted` :539, `test_nested_parenthetical`) are the template for new
  printed_number extractor unit tests. `test_long_stmt_truncated_flag_set` (:1180) /
  `test_normal_stmt_not_truncated` (:1213) already cover `ChunkRecord.truncated` at the chunker
  level — m2 needs a NEW store-level test (in `test_store.py`) asserting `truncated` survives the
  LanceDB round-trip, since no such test exists today (the drop happens in `_build_arrow_table`,
  which `test_chunker.py` never exercises).
- `tests/test_chunker_ids.py` — chunk_id stability tests; relevant because `_compute_chunk_id`
  (`chunker.py:1180-1204`, called :1097) hashes only `preamble_text + NFC(body_text)` — confirmed
  NOT touched by any of the 5 new fields. Keep it that way (AC7 below).

## Acceptance criteria the implementer must meet (≤7)

1. **[roadmap AC1]** `CHUNKS_SCHEMA_V1` (`ingest/schema.py:121-210`) gains exactly 5 new nullable
   fields — `source_revision_id`, `source_span`, `truncated`, `printed_number`, `license_ref` —
   appended after `parser_used` (:208), and `_TEXTBOOK_MIGRATION_DEFAULTS`
   (`ingest/store.py:319-327`) gains a matching `cast(NULL as ...)` entry for each. Per spike-3's
   recommendation that `source_span` be a plain string (not a struct), all 5 can ride the existing
   single-loop SQL-dict `add_columns` mechanism (`_migrate_chunks_schema_if_needed`, :330-411)
   unmodified; a struct `source_span` instead requires the schema-based `add_columns(pa.field(...))`
   branch spike-4 proved necessary.
2. **[roadmap AC1]** A second migration call against an already-migrated table is a no-op:
   `missing = target_names - existing_names` is empty, zero `add_columns` calls fire — matching the
   existing `test_migration_is_idempotent` (`tests/test_store.py:1212`) pattern applied to the new
   columns.
3. **[roadmap AC1 + AC2]** Every pre-existing column on all 15,106 live rows is byte-identical
   after migration + backfill — `embedding_stmt`/`embedding_proof` in particular must remain
   untouched, verified the way spike-4's `verify_integrity.py` did (bit-identical `np.array_equal`
   on sampled vectors) or stronger (all rows, not a sample).
4. **[roadmap AC2]** The backfill CLI hydrates `truncated`, `printed_number`, `source_span`,
   `source_revision_id`, and `license_ref` on both live notebooks' existing chunks without calling
   the BGE-M3 embedder — structurally, not just behaviorally: it must not import
   `ingest.store.write_chunks` or anything that transitively imports `ingest.embedder` (mirrors
   `tools/oai_license.py:10-19`'s documented reason for not reusing `ingest.oai_delta`). `truncated`
   and `printed_number` are recomputable directly from the existing parsed HTML the chunker already
   reads (`var/arxmcp/corpus/parsed/<paper_id>/index.html`); `source_revision_id`/`license_ref` are
   resolved via `server/documents_store.py::DocumentsStore` keyed by `(work_id, arxiv_version)`,
   where `arxiv_version` must be recovered from the same `papers.txt` membership parse
   `tools/notebook_documents_backfill.py::_Membership` (:179-185) uses — never assumed to be `""`
   or derived from the chunk row alone.
5. **[roadmap AC2]** The backfill's write mechanism updates only the 5 new columns per matching
   chunk row (e.g. `lancedb.table.Table.update(where=f"chunk_id = '<id>'", values={...})`,
   confirmed available in the installed `lancedb==0.30.2`) rather than a
   `merge_insert(...).when_matched_update_all()` full-row replace, so no embedding vector is read,
   copied, or rewritten as a side effect of a column-only backfill.
6. **[roadmap AC3]** A block whose `(source_revision_id, normalized_body-grain_text_hash)` cannot
   be resolved against the current parsed HTML (spike-3's recommended anchor — NOT `char_offset`,
   measured at only 11% stable across a re-ingest) gets `source_span = null`, and the backfill's
   summary output counts these un-anchorable blocks explicitly and separately from successes —
   mirroring the `registered=N skipped=M missing=K` machine-parseable summary already shipped in
   `tools/notebook_documents_backfill.py:407-414` — never a silent null.
7. **[roadmap AC1 + AC2, guardrail]** `ingest/chunker.py::_compute_chunk_id` (:1180-1204) — which
   hashes only `preamble_text + NFC(body_text)` — is NOT modified to depend on any of the 5 new
   fields; every existing chunk_id in the corpus must remain byte-stable through m2 (a rotated
   chunk_id is a new row to `merge_insert`, not an update to an existing one, which would silently
   break the "0 chunks re-embedded" guarantee at the identity level even if no embedder is called).

## Risks and open questions (≤5)

1. **The per-row backfill write mechanism is unspiked.** Spike-4 proved the schema-migration step
   (add 5 NULL columns, metadata-only, <1s) is safe, but no spike exercised writing 15,106 distinct
   computed values into existing rows. `Table.update(where=..., values={...})` (confirmed
   available, column-scoped, live-introspected this session; zero existing uses in `ingest/`) is
   this brief's recommended mechanism, but it applies one static `values` dict per call — meaning
   either ~15,106 individual per-chunk calls (each its own MVCC version; spike-4's `add_columns`
   timings, ~0.1-0.3s/call, suggest tens of minutes total for this — untested at this granularity)
   or a read-modify-write via `merge_insert` (copying embeddings byte-identical,
   `ingest/re_embed.py`'s pattern) that trades many small MVCC bumps for one large one. Neither has
   been measured; benchmark on a small slice before committing to one at 15K-row scale.
2. **`source_span`'s revision-checksum component can be computed two different ways that could
   silently diverge.** `server/documents_store.py`'s `parse_artifact_sha256` (computed once by
   `notebook_documents_backfill.py::_parse_artifact_sha256`, :165-171) and a hypothetical
   independent `sha256(html_bytes)` inside `ingest/chunker.py::_chunk_paper_impl` (which already
   holds `html_bytes` in memory at :1017) are the SAME computation over the SAME file, done by two
   different code paths at two different times. If the registry is backfilled once and the parsed
   HTML is later re-fetched/re-parsed (a legitimate ar5iv-cache-refresh event), the two checksums
   could disagree with no built-in detection. Recommend the m2 backfill read `parse_artifact_sha256`
   FROM the registry (single source of truth) rather than recomputing it independently.
3. **`license_ref`'s exact value contract is undefined in every available source document.**
   Nothing read (roadmap brief, m2 milestone brief, m1 briefs 1/2, `documents_store.py`) specifies
   whether `license_ref` is a distinct id namespace or literally the same string as
   `source_revision_id` — m1's registry has only one row type per revision carrying both
   provenance and license fields, so there is no separate "license record" to point at. This brief
   recommends `license_ref == source_revision_id` (same `(work_id, arxiv_version)` pointer) as the
   simplest reading that matches what exists on disk today, but flags it as a decision the
   implementer must make explicitly and document, not a finding.
4. **`printed_number`'s F2 blind spot (old-style, pre-`\newtheorem` papers with zero `ltx_theorem`
   divs) has no cheap per-paper detector wired in yet.** Spike-2 confirmed this is real,
   non-hypothetical, total-loss (`alg-geom/9606006`: 25 real theorems, 0 recoverable) and
   recommended (not as a hard AC, but worth the budget) a per-paper sanity check — "zero
   `ltx_theorem` divs but the rendered text contains Theorem/Lemma/Proposition more than N times" —
   to flag such papers in the backfill's abstention report distinctly from ordinary per-block
   `source_span` misses. Not required by the 3 roadmap ACs; recommend folding it into the same
   abstention report AC6 already requires, since the detection logic is nearly free given spike-2's
   own methodology.
5. **The registry join assumes one `(work_id, arxiv_version)` row per work_id per notebook —
   untested at scale for collisions.** `notebook_documents_backfill.py` dedupes by
   `(work_id, arxiv_version)` from `papers.txt` lines, so a notebook could in principle carry two
   different versions of the same work as distinct registry rows (e.g. `0708.2247` bare AND
   `0708.2247v2` both listed). No source read here confirms whether this actually occurs in either
   live notebook, nor how the m2 backfill should pick which registry row a given chunk (which
   carries no version) should join against if it does. Worth a quick census (distinct work_ids vs.
   distinct `(work_id, version)` pairs across both `papers.txt` files) before assuming the join is
   always 1:1.
