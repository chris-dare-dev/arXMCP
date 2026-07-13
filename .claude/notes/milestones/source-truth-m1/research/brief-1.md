---
milestone_id: "source-truth-m1"
researcher_role: "explore"
injection_attempts: 0
date: "2026-07-12"
title: "source-truth-m1 codebase map — registry store pattern, field sources, license-allowlist gap"
---

# source-truth-m1 research brief — codebase map

Read-only exploration. No code edited, no git operations. Grounded on `CLAUDE.md` §§4.5/4.7/4.8/4.9
and `.claude/notes/milestones/source-truth-spike-1/spike-note.md` (the load-bearing spike: arXiv's
Atom client returns 0/30 licenses; OAI-PMH carries `<license>`).

## Affected files / context

### 1. The store pattern to extend

`server/paper_metadata_store.py` (320 lines) is the exact pattern the documents registry should
follow — it is itself called out in roadmap.yaml as a "might"-tier assumption ("the per-notebook
SQLite store pattern extends to the documents registry without a new storage engine").

| Element | Location | Reuse for the registry |
|---|---|---|
| Schema-version constant | `SCHEMA_VERSION: int = 1` at `server/paper_metadata_store.py:61` | Add a sibling constant, e.g. `DOCUMENTS_SCHEMA_VERSION`, in a new `server/documents_store.py` |
| Per-notebook filename constant | `PAPER_METADATA_DB_FILENAME = "paper_metadata.db"` at `:67` | New constant, e.g. `DOCUMENTS_DB_FILENAME = "documents.db"` — sibling file next to `paper_metadata.db` under `var/arxmcp/notebooks/<slug>/` |
| Frozen record dataclass | `PaperMetadataRecord` at `:70-90` | New `DocumentRecord` (work id, version, raw sha256, parse-artifact checksum, chunker/parser version stamps, fetch timestamp, license URI, status) |
| Async-over-sync store class | `PaperMetadataStore` at `:93-277`, `asyncio.Lock` + `asyncio.to_thread`, single `sqlite3.Connection` | Identical shape for the new store class |
| `open()` classmethod, idempotent | `:112-171` — `PRAGMA user_version`, `WAL` mode, `synchronous=NORMAL` (NOT `FULL` — this is regenerable data, same durability tier reasoning applies: raw checksums/license data are re-derivable by re-running the backfill) | Reuse verbatim: `mkdir(parents=True, exist_ok=True)`, `isolation_level=None` (autocommit) + explicit `BEGIN`/`COMMIT`/`ROLLBACK` around the v0→v1 `CREATE TABLE IF NOT EXISTS` |
| Idempotent batch writer | `upsert_records()` at `:189-228` — `INSERT OR REPLACE` keyed by primary key, one transaction | Reuse pattern; registry PK should be `(work_id, version)` or a synthesized `revision_id`, not `paper_id` alone (see identity distinction below) |
| Read path | `get()` / `hydrated_paper_ids()` / `row_count()` at `:239-277` | `hydrated_paper_ids()`'s "title != '' AND authors != '[]'" idempotency gate (`:251-266`) is the direct precedent for a registry-side "already-registered" gate the backfill CLI needs |
| Migration crash-safety precedent | `server/notebooks_store.py:260-292` (v4→v5, notebook-paper-discovery-m1) — two-column ADDITIVE migration wrapped in explicit `BEGIN`/`COMMIT` so a crash between ALTERs can't strand `user_version` ahead of the tables | Cite as the multi-statement-migration precedent if the registry ever needs >1 additive column across a version bump (m1 itself is a fresh v0→v1 create, so this doesn't fire yet, but a future m1-follow-on column would use it) |

**Instantiation site (read path, already shipped):** `server/resources.py:1362-1404`
(`_open_paper_metadata_store`) shows the production per-notebook derivation:
`pmd_path = Path(config.lancedb_path).parent / PAPER_METADATA_DB_FILENAME` — i.e. the metadata DB
is a sibling of the notebook's `lancedb/` dir. "Open-only-if-exists" is load-bearing (`:1374-1377`):
`PaperMetadataStore.open` *creates* the file, but only the backfill CLI should populate it — the
server never scatters empty DBs next to un-hydrated notebooks. **The new documents-registry store
should mirror this exact non-critical-enrichment contract** if it's ever read server-side (m1 itself
only needs a writer/CLI path — no MCP tool reads the registry in this milestone).

### 2. Where each registry field comes from

| Field | Source | Notes / gaps found |
|---|---|---|
| **Raw-source sha256** | `var/arxmcp/corpus/raw/<id>/` — confirmed populated for **new-style ids only** (e.g. `var/arxmcp/corpus/raw/0712.1083/*.tex,*.bbl,*.eps`). | **Gap, not just a detail:** a directory listing of `var/arxmcp/corpus/raw/` (this session, local `var/`) shows **zero** letter-prefixed (old-style) subdirs — no `alg-geom/`, `hep-th/`, `math/`, `math-ph/` anywhere under `raw/`, while all four exist under `parsed/`. Traced to cause: `ingest/bulk_ingest.py`'s fallback ladder is ar5iv-first (`ingest/ar5iv_fetch.py` docstring: "Run our local LaTeXML only on ar5iv cache misses" — the local `.tex` fetch, `tools/arxiv_fetch.py::fetch_eprint`, is only invoked as LaTeXML's input on an ar5iv miss). Old-style (pre-2007) papers apparently all hit the ar5iv-cache-hit path in this corpus and so never had their raw source persisted locally. Spot-checked: `var/arxmcp/corpus/raw/math/0212237/`, `.../alg-geom/`, `.../hep-th/` — all absent, vs. `var/arxmcp/corpus/parsed/math/0212237/index.html` — present. ~15/142 bridgeland-stability papers are old-style (spike-1 recount). No existing whole-directory-hash utility exists; closest precedent is `ingest/preamble.py:414-416` (`source_hash = hashlib.sha256(source_bytes).hexdigest()`), but that hashes only the single resolved *main* `.tex` file (via `find_main_tex`), not the full raw source tree — a different scope than "raw-source sha256" as the roadmap brief frames it ("raw-tarball sha256"). The original fetched tarball bytes are never persisted either: `tools/arxiv_fetch.py::fetch_eprint` (`:308-371`) reads the gzip body into memory, hands it to `_extract_eprint_response` (`:374+`), and only the **extracted member files** land on disk — the tarball itself is discarded. |
| **Parse-artifact checksum** | `var/arxmcp/corpus/parsed/<id>/index.html` — confirmed present for both new-style and old-style ids (`var/arxmcp/corpus/parsed/math/0212237/index.html` exists). Single file, straightforward to hash with the same `hashlib.sha256(...).hexdigest()` idiom used at `ingest/preamble.py:416`, `ingest/chunker.py:1187`, `ingest/textbook_chunker.py:154`. | No existing precedent hashes this specific file today — new code, but trivial given the single-file target. |
| **Parser/chunker version stamps** | `CHUNKER_VERSION = "v1.1"` at `ingest/chunker_types.py:45` (single source of truth; flows into every `ChunkRecord.chunker_version`, `:163`). Siblings: `TEXTBOOK_CHUNKER_VERSION = "tv0.1"` (`ingest/textbook_chunker.py:89`), `TEXTBOOK_MD_CHUNKER_VERSION = "tmd0.1"` (`ingest/textbook_markdown_chunker.py:53`), `TOKENIZER_VERSION = "v1.0"` (`ingest/tokenizer.py:76`), `EMBEDDER_VERSION = f"bge-m3@{BGE_M3_COMMIT_SHA[:8]}"` (`ingest/embedder.py:136`). Per-chunk parser provenance enum `{"ar5iv","latexml","mineru+latexml"}` already exists as `ChunkRecord.parser_used` (`ingest/chunker_types.py:142-147, :184`) but per that docstring is only "promoted to a persisted chunks-table column in m2" — i.e. not yet a queryable column anywhere, m1 would be its first consumer if used. | **LaTeXML version itself is NOT tracked anywhere.** Grepped the full `ingest/` tree and `tools/arxiv_fetch.py` for a `LATEXML_VERSION`/`--version` capture: none exists. `tools/arxiv_fetch.py` invokes the local `latexmlc` binary as a bare subprocess (`:108-116, :259, :554-567` — path-resolution logic for Windows Strawberry Perl, `--timeout=300`, exit-code handling) with no `--version` capture. ar5iv's server-side LaTeXML version is entirely opaque (remote CDN response, `ingest/ar5iv_fetch.py`, no version header read). So the registry can record **which parser path ran** (`parser_used`) but not **which LaTeXML build** rendered it, unless m1 adds a fresh `latexmlc --version` capture — that would be new work, not reuse. |
| **arXiv version (`vN`)** | Resolved at fetch time — the Atom `id_list` response and (per spike-1) the OAI-PMH response both carry the concrete `vN` a bare id resolves to (spike-1's Step 1 table: e.g. `0708.2247` → `0708.2247v1`). | **Not persisted anywhere today.** `tools/_arxiv_api.py::strip_id_version` (`:276-282`) and `notebook_metadata_backfill.py` (`:299-303`) strip the version *away* before storing — `PaperMetadataRecord.paper_id` and every chunks-table `paper_id` are version-stripped. The registry is the first place in this codebase that needs to retain `vN` as a first-class field rather than discard it. |
| **Work-identity vs. revision-identity** | `ingest/identifiers.py` is the single source of truth for id shape. `ARXIV_PAPER_ID_RE` (`:86-92`) matches new-style `YYMM.NNNNN(vN)?` and old-style `subject/NNNNNNN(vN)?` — the version suffix is *matchable* but every consumer (`strip_id_version`, `is_valid_arxiv_paper_id` call sites) treats the versionless form as the canonical `paper_id`, i.e. **work identity**. There is no existing concept of a **revision identity** (work id + version) persisted in any store — chunks, `paper_metadata.db`, and `papers.txt` are all keyed by work id only. The registry is new territory here, not an extension of an existing revision-keyed table. |
| **Fetch timestamp** | Direct analog: `PaperMetadataRecord.fetched_at` (`server/paper_metadata_store.py:89`), populated via `datetime.now(UTC).isoformat()` in the backfill driver (`tools/notebook_metadata_backfill.py:261`). Reuse verbatim. |
| **Active/withdrawn/superseded status** | **"Withdrawn" has a ready-made, already-tested signal:** OAI-PMH's `<header status="deleted">` — parsed today at `ingest/oai_delta.py:476` (`deleted = header.get("status") == "deleted"`) and explicitly logged as "withdrawn" at `:622` (`_feed_record_to_pipeline`). This is production code with dedicated tests (`tests/test_oai_delta.py::TestParseListRecords::test_deleted_record_flagged`, `:141-148`). **"Superseded" has no existing signal** — `arXivRaw`'s `<versions>` block (mentioned only in a comment at `ingest/oai_delta.py:117`, never parsed) is the likely source (a paper with version N+1 present supersedes N), but nothing in the repo currently extracts or interprets it. |

### 3. The license decision surface

`server/license_policy.py` (67 lines) — read in full.

- `LICENSE_TRUNCATION_CHARS: int = 300` (`:33`).
- `OA_ALLOWLIST: frozenset[str] = {"arxiv-license", "CC-BY", "CC-BY-SA", "CC0", "public-domain", "GFDL"}` (`:44-53`) — **exact-string, case-sensitive** membership.
- `is_open_access(license_token)` (`:56-66`) — fail-closed: `None`/`""` → `False`; anything not in the allowlist → `False`.

**Critical finding, directly answering the task's question:** `"arxiv-license"` in the allowlist is
an **internal placeholder token**, not the real arXiv license URI. It is written as a hard-coded
*default* at chunk-creation time, independent of any actual per-paper license lookup:
`ChunkRecord.license: str = field(default="arxiv-license")` (`ingest/chunker_types.py:176`); the
LanceDB schema casts the same literal for legacy-row backfill and new-row defaults
(`ingest/schema.py:21-22,185`; `ingest/store.py:321,337,553,849`). Every arXiv chunk in the corpus
today carries this literal string regardless of what license the paper actually has — it is exactly
the "blanket token" both `.claude/roadmap-briefs/R1-source-truth.md:18,51` and
`plans/source-truth/roadmap.yaml:18,55,73,122` name as the thing source-truth-e4 eventually retires.

**The real license URI spike-1 found is NOT in `OA_ALLOWLIST` as a raw string.**
`http://arxiv.org/licenses/nonexclusive-distrib/1.0/` (spike-1's dominant-case OAI-PMH result) does
not exact-string-match `"arxiv-license"` or any other allowlist entry. Consequence for m1's
decision function: if it evaluates the raw fetched URI directly against `OA_ALLOWLIST`-shaped logic
with no translation step, **the dominant case (near-100% of the arXiv corpus, per spike-1's
schema-level-absence finding for the *old* Atom source and the one confirmed OAI-PMH hit) would
decision as non-open-access/truncate** — almost certainly not the intended advisory output, since
`"arxiv-license"` was deliberately allowlisted because arXiv's standard non-exclusive license
"explicitly permit[s] non-commercial research use" (rationale recorded at
`.claude/notes/milestones/textbook-ingest-m11/research-brief-2.md:174`). **m1's decision function
therefore needs its own URI→classification mapping** (e.g. recognize the
`arxiv.org/licenses/nonexclusive-distrib/*` URI family as the OA-equivalent of the existing
`"arxiv-license"` token) — this is genuinely new logic, not a call-through to
`is_open_access()`. Per the milestone's own scope, `server/license_policy.py` itself is **not**
modified in m1 (that's source-truth-e4/m4, owner-gated); the new decision function lives
separately and only *logs* what it would decide.

### 4. The backfill precedent

`tools/notebook_metadata_backfill.py` (368 lines) is the direct precedent for the registry backfill
CLI:

- **Membership source of truth is `papers.txt`, not any DB table** — explicit in the module
  docstring (`:3-6`: "the central `notebook_papers` junction table is EMPTY for every notebook") and
  guarded by a dedicated test, `tests/test_notebook_metadata_backfill.py::TestMembershipSource::
  test_driver_never_reads_the_empty_junction_table` (`:467-477`). The registry backfill must read
  the same `papers.txt` (via `tools/_notebook_common.py::read_paper_ids_from_papers_txt`, `:228`).
- **Idempotency gate:** `hydrated_paper_ids()` (already-hydrated rows skipped, zero network egress
  on re-run) — direct analog for a registry-side "already registered" set.
- **0-re-embed guarantee is structural, not incidental, for m1:** the registry backfill never
  touches the LanceDB `chunks` table or the embedder at all (m1's scope is a brand-new SQLite store
  + a license fetch; chunks-schema v2 is source-truth-m2). So "0 chunks re-embedded" is automatically
  satisfied by staying out of `ingest/store.py`/`ingest/embedder.py` entirely — worth stating
  explicitly as an acceptance-test assertion (e.g. LanceDB row count / `corpus_version` unchanged
  before vs. after a backfill run) rather than assuming it.
- **Politeness contract constants to reuse:** `DEFAULT_BATCH_SIZE = 50` (`:96`),
  `MAX_ATTEMPTS_PER_REQUEST = 3` (`:102`), `RATE_LIMIT_BACKOFF_SECONDS = 60.0` (`:106`), all built on
  `tools.arxiv_fetch.POLITENESS_SLEEP_SECONDS` / `parse_retry_after` / `DEFAULT_503_BACKOFF_SECONDS`.
  **These constants are batched-`id_list`-shaped (Atom).** OAI-PMH's `GetRecord` verb (spike-1's
  probe shape) has no batch/id-list equivalent — it is one request per paper id. A registry-scale
  backfill (142 + 52 = 194 papers across both notebooks) means ~194 individual OAI-PMH requests at
  ≥3s spacing ⇒ **≥10 minutes of pure politeness-sleep time minimum**, a materially different cost
  profile than the Atom backfill's batched-50-per-request shape. Surfaced as a risk below.
- **Coverage-report shape:** no dedicated "coverage report" exists yet anywhere in the repo — the
  closest precedent is the backfill's own loud summary line (`tools/notebook_metadata_backfill.py:
  321-328`: `hydrated=N skipped=M missing=K malformed=J unique=U total=T`, machine-parseable,
  "keeps a zero-row run LOUD"). The per-license coverage report (AC3) is new output shape, but
  should mirror this line's discipline: a single parseable summary plus per-license counts, and an
  explicit loud signal (non-zero exit and/or stderr block, mirroring `run()`'s `missing`/`malformed`
  stderr dump at `:329-341`) when bridgeland-stability's unknown-rate exceeds 20%.

### 5. The notebooks

| Notebook | `papers.txt` count (bare-ID lines, `#`/blank skipped — recounted this session) | `paper_metadata.db` present? |
|---|---|---|
| `bridgeland-stability` | **142** (matches spike-1's recount exactly: 127 new-style + 15 old-style) | Yes — `var/arxmcp/notebooks/bridgeland-stability/paper_metadata.db` + `-shm`/`-wal` (WAL mode active, consistent with `PaperMetadataStore.open`'s `PRAGMA journal_mode=WAL`) |
| `fourier-duality` | **52** | **No** — only `papers.txt` and `queries.json` present; no `paper_metadata.db` (or `-wal`/`-shm`) at all |

`plans/source-truth/roadmap.yaml`'s own task-level acceptance for `source-truth-t-registry-backfill`
(`:228`) still says *"the bridgeland-stability (~200 papers) and fourier-duality (~65 papers)
notebooks"* — both estimates are stale, mirroring the same drift spike-1 already flagged for
bridgeland-stability's "~200" figure (its brief text). fourier-duality's true count (52) is also
off from the roadmap's "~65". Also worth noting: `bridgeland-stability-pdfs` is a **separate**
notebook (PDF/MinerU ingest path, `var/arxmcp/notebooks/bridgeland-stability-pdfs/parsed/...`,
distinct LaTeXML.css/MinerU-JSON artifacts) — not one of the two notebooks m1's acceptance criteria
name ("both live notebooks" = `bridgeland-stability` + `fourier-duality`).

### 6. Test surfaces

- `tests/test_paper_metadata_store.py` (276 lines): `TestStoreSchema` (double-init no-op, migration
  rerunnable without data loss, migration never drops tables), `TestUpsertAndRead`,
  `TestHandlerFieldMapping`, `TestColdReopen` (serves metadata after a cold reopen with **no**
  chunks-table dependency — the store's self-containment acceptance). Direct template for the
  registry store's test file.
- `tests/test_notebook_metadata_backfill.py` (477 lines): `TestHappyPath`, `TestPoliteness` (6
  tests covering 3s spacing / email-at-entry / 503 / 429 / retry exhaustion), `TestIdempotency`,
  `TestFailureModes` (5 tests), `TestMembershipSource`. Direct template for the registry backfill
  CLI's test file.
- `tests/test_arxiv_api.py` (246 lines) and `tests/test_arxiv_api_metadata.py` (236 lines) test the
  existing Atom-only surface (`build_query_url`/`parse_atom_feed`/`fetch_candidates`/
  `build_id_list_url`/`parse_atom_metadata`) — **no OAI-PMH tests exist in either file.**
- `tests/test_oai_delta.py` — mature, tests `TestParseListRecords`, `TestStateFile`,
  `TestResolveResume`, `TestHarvestSet`, `TestRunDelta` against `ingest/oai_delta.py`'s
  `ListRecords`-shaped harvester (see risk below — this is a *different* shape than what a
  per-known-id license backfill needs, but it's the only existing OAI-PMH test precedent in the
  repo).
- **`get_chunk` / `tools/list` schema-hash pin is untouched by m1, confirmed:** `server/tools.py:168`
  pins `TOOL_SCHEMA_VERSION: int = 17`, with an explicit changelog at `:150-167` recording exactly
  what each of the last two bumps changed (v16 = textbook-ingest-m11's `truncated_for_license` +
  `chunk.license` fields; v17 = paper-metadata-m2's `get_paper` description). m1 adds no new MCP
  tool, and touches none of `server/tools.py`, `server/handlers/chunk.py`, or `ALL_TOOLS` — so
  `EXPECTED_TOOL_SCHEMA_SHA256` in `tests/test_server_tool_schema.py` (pinned at `:94`, guarded by
  `test_live_tools_match_pinned_hash` at `:341`) stays exactly as-is. This matches
  `plans/source-truth/roadmap.yaml`'s own sequencing — `get_chunk` field surfacing is explicitly
  deferred to `source-truth-m5` ("rides W1"), not m1.

### 7. Scope check

Confirmed against `plans/source-truth/roadmap.yaml`'s milestone/epic breakdown: m1 = `source-truth-e1`
only — documents registry (schema + idempotent writer), raw/parse checksums + version stamps at
registration, license URI hydration, the advisory-only per-revision decision function, the backfill
CLI, and the per-license coverage report. Explicitly **not** m1:

- Chunks-schema v2 (`source_revision_id`, `source_span`, `truncated`, `printed_number`,
  `license_ref` columns on the LanceDB `chunks` table) — `source-truth-e2`/`m2`, depends on m1.
- `get_chunk` response surfacing any of the above fields — `source-truth-m5`, depends on m2, "rides
  W1" tool-schema window.
- The owner-gated fail-closed cutover (flipping `server/license_policy.py`'s actual serving
  behavior, retiring the blanket `arxiv-license` token from new writes) — `source-truth-e4`/`m4`,
  depends on m2 **and** m3.
- The `arxmcp://corpus-manifest` resource — `source-truth-e3`/`m3`, depends on m1 but is a sibling
  deliverable, not part of m1 itself.

## Acceptance criteria the implementer must meet

Traced to the 3 roadmap ACs (`plans/source-truth/roadmap.yaml:164-167`, reproduced in this
milestone's own brief) — AC-refs below are `[R#]`.

1. **[R1]** The documents-registry store initializes idempotently, following
   `server/paper_metadata_store.py`'s exact pattern (async-over-sync SQLite, `PRAGMA user_version`,
   WAL + `synchronous=NORMAL`, explicit `BEGIN`/`COMMIT` around the v0→v1 create): a second `open()`
   on an existing file is a no-op and the schema-version row is unchanged.
2. **[R1]** At registration, every already-fetched revision gets a raw-source checksum, a
   parse-artifact checksum, and parser/chunker version stamps persisted, and a re-run is a no-op.
   **Must explicitly define behavior when `var/arxmcp/corpus/raw/<id>/` does not exist** (confirmed
   true for every old-style id sampled this session) — silently writing a null/placeholder without
   a documented convention would violate "every ingested revision has a documents row with all
   those fields."
3. **[R1]** Each row captures work identity (versionless `paper_id`) *and* revision identity
   (resolved `vN`) as distinct fields, plus `fetched_at` and an active/withdrawn/superseded status.
   Withdrawn can reuse the OAI-PMH `<header status="deleted">` signal already parsed at
   `ingest/oai_delta.py:476`; superseded has no existing extraction and needs new logic (see risk).
4. **[R1, R3]** License hydration runs over registered revisions across all three id shapes
   (new-style, old-style, versioned) via **OAI-PMH, not `tools/_arxiv_api.py`'s Atom client**
   (spike-1: Atom is a confirmed schema-level 0/30; the roadmap epic/task text's "via the existing
   tools/_arxiv_api.py Atom client" wording is stale relative to the spike and must not be followed
   literally), honoring the arXiv politeness contract, and stores either the fetched license URI or
   `license_status=unknown`.
5. **[R2]** The per-revision decision function returns a full-body-eligible decision for a
   recognized open license and `license_status=unknown` (→ truncate) for missing/unrecognized,
   logged advisory-only, with **zero modifications to `server/license_policy.py`,
   `server/handlers/chunk.py`, or actual serving behavior**. Must include a URI→classification
   mapping for the dominant-case arXiv default license
   (`http://arxiv.org/licenses/nonexclusive-distrib/1.0/`, spike-1) — feeding that raw URI through
   `OA_ALLOWLIST`-shaped exact-string matching as-is would misclassify ~100% of the corpus as
   unknown, since the allowlist only contains the internal `"arxiv-license"` placeholder token, not
   the URI.
6. **[R1, R3]** The backfill CLI, run against both live notebooks (142 bridgeland-stability + 52
   fourier-duality bare ids, re-verified this session — not the roadmap's stale ~200/~65 estimates),
   registers every ingested revision, writes zero LanceDB/embedding changes (m1 never touches
   `ingest/store.py` or the embedder — assert this in a test, don't just assume it), and a re-run is
   a no-op.
7. **[R3]** The coverage report emits per-license counts for both notebooks from the hydrated
   registry, and loudly surfaces (mirroring the existing backfill summary-line discipline at
   `tools/notebook_metadata_backfill.py:321-341`) when bridgeland-stability's unknown-license rate
   exceeds 20%, before any serving cutover.

## Risks and open questions

1. **Roadmap planning text names the wrong client.** `plans/source-truth/roadmap.yaml`'s
   `source-truth-e1` summary (`:86`) and `source-truth-t-license-hydration` acceptance (`:204`) both
   say license URIs come "via the existing tools/_arxiv_api.py Atom client" / "via the Atom client."
   Spike-1 falsified this for the corpus's actual id shapes (0/30, schema-level absence). The
   implementer must source from OAI-PMH per the spike's corrected recommendation, not the roadmap
   document's literal wording — this brief is the record of that override.

2. **A mature OAI-PMH client already exists but doesn't fit the backfill's access pattern, and its
   license coverage on the *current* endpoint+prefix is unverified.** `ingest/oai_delta.py`
   (E11_S02, production, tested via `tests/test_oai_delta.py`) already talks OAI-PMH against
   `https://oaipmh.arxiv.org/oai` (the current HTTPS endpoint — arXiv migrated off
   `export.arxiv.org/oai2` in March 2025 per its own comment, `:82-84`) with
   `metadataPrefix=arXivRaw` (`:119`, richer than the plain `arXiv` prefix spike-1 tested). Three
   gaps versus what m1 needs: (a) it's a `ListRecords`-by-date/set harvester for *discovering new*
   papers, not a per-known-id lookup — `GetRecord` (spike-1's probe verb, matching a fixed
   `papers.txt` list) is used nowhere in the repo and would need to be newly written; (b) its
   `_parse_listrecords` (`:419-501`) does not currently extract `<license>` or `<versions>` even
   though the module's own comment claims `arXivRaw` carries both (`:116-118`) — that claim is a
   code comment, not something spike-1 (or any test) independently verified, since spike-1's live
   OAI-PMH check used the legacy endpoint + the plain `arXiv` prefix, not
   `oaipmh.arxiv.org` + `arXivRaw`; (c) it parses with plain `xml.etree.ElementTree` (`:65, :429`),
   not `defusedxml`, inconsistent with `tools/_arxiv_api.py`'s stated XXE-safety rationale for using
   `defusedxml` on untrusted external responses. A cheap live `GetRecord` (or one-page `ListRecords`)
   check against the current endpoint+prefix, confirming `<license>` still resolves the way spike-1's
   legacy-endpoint probe did, is worth doing before committing to a design — this session's mandate
   was local-filesystem-only, so that check is undone.

3. **The dominant-case license URI is not in `OA_ALLOWLIST`.**
   `http://arxiv.org/licenses/nonexclusive-distrib/1.0/` (spike-1's finding) does not exact-string-match
   any of `server/license_policy.py:44-53`'s six allowlist entries — only the internal placeholder
   token `"arxiv-license"` is allowlisted, and that token is written blindly by the chunker/store
   defaults (`ingest/chunker_types.py:176` and callers) with no relationship to a real per-paper
   license lookup today. m1's decision function needs its own URI-recognition logic to avoid the
   dominant case reading as "unknown" — see AC5 above. This is squarely m1's to solve (advisory
   only) even though `server/license_policy.py` itself isn't touched until source-truth-e4.

4. **Raw-source checksums cannot be computed for old-style-id papers from what's on disk today.**
   `var/arxmcp/corpus/raw/` (checked this session) contains zero old-style (letter-prefixed)
   subdirectories anywhere, while `var/arxmcp/corpus/parsed/` has all four
   (`alg-geom/`, `hep-th/`, `math/`, `math-ph/`). Traced to `ingest/bulk_ingest.py`'s ar5iv-first
   fallback ladder never invoking the raw `.tex` fetch on an ar5iv cache hit. ~15/142
   bridgeland-stability papers are old-style (spike-1's recount). The implementer must pick and
   document one of: re-fetch raw sources for these ids at registration time (extra network egress
   and politeness budget on top of the license-hydration requests), or define an explicit
   null-with-reason convention for `raw_source_sha256` (consistent with this roadmap's own
   "abstention, not silence" principle used elsewhere for `source_span`) — silently leaving the
   field empty with no status marker would violate AC1's "every ingested revision has a documents
   row with all those fields."

5. **OAI-PMH's per-id `GetRecord` shape has no batching, unlike the Atom `id_list` precedent the
   existing backfill CLI is built around.** `tools/notebook_metadata_backfill.py`'s politeness
   constants (`DEFAULT_BATCH_SIZE=50`, etc.) assume ~50-papers-per-request batching; OAI-PMH
   `GetRecord` is one request per paper. Registering + license-hydrating 194 papers (142 + 52,
   both counts re-verified this session, correcting the roadmap's stale ~200/~65 estimates) at
   the ≥3s politeness floor is a ≥10-minute minimum wall-clock backfill even before accounting for
   retries/backoff — a materially different operational profile than the paper-metadata-m1
   precedent, worth sizing explicitly rather than assuming batch-style throughput.
