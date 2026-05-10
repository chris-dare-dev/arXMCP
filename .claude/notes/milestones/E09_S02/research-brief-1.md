# E09_S02 — INSPIRE-HEP enrichment — research brief 1

## 1. In-codebase context

### `ingest/graph_ingest.py` (E09_S01 — the template to mirror)

The E09_S01 OpenAlex ingest is the contract we copy. Load-bearing constants and patterns:

- **Polite-pool politeness** (`graph_ingest.py:25–38`): `User-Agent: arXMCP/0.1 (mailto:<email>)` via `tools.arxiv_fetch.build_user_agent`; `?mailto=` query string; `OPENALEX_POLITE_SLEEP_SECONDS = 0.1`; 429/503 → `tools.arxiv_fetch.parse_retry_after` with `DEFAULT_503_BACKOFF_SECONDS` (30 s) capped at `MAX_503_BACKOFF_SECONDS` (300 s), `MAX_HTTP_RETRIES = 3`, exponential between retries.
- **Response-size cap** (`graph_ingest.py:135–141`): a *separate* per-source cap, not the 200 MB arXiv-tarball cap. F2 from the E09_S01 rect (`95fd3cf`) carved out `OPENALEX_MAX_RESPONSE_BYTES = 5 * 1024 * 1024` *precisely because* "a malformed CDN response allocate[s] 20,000× more memory than the OpenAlex shape ever needs." E09_S02 MUST define its own `INSPIRE_MAX_RESPONSE_BYTES` — a record with 1k references is larger than OpenAlex's ~10 KB. Empirical: the ATLAS Higgs paper (147 refs, expanded) is well under 1 MB; **10 MiB** is a safe-and-tight cap.
- **Idempotent MERGE upserts** (`graph_ingest.py:423–450` and `:467–480`): `MERGE (p:papers {paper_id: $paper_id}) ON CREATE SET … ON MATCH SET …` for nodes; `MATCH … MERGE (a)-[r:cites {source: $source}]->(b)` for edges. **The `source` property is on the MERGE pattern**, so an `inspire` edge is a *distinct* edge from an `openAlex` edge for the same (src,dst) pair — AC#3 "Existing `source="openAlex"` edges are not duplicated or overwritten" is satisfied by construction.
- **`_merge_paper` forward-compat hazard** (`graph_ingest.py:405–422`, the docstring carrying F4): quoting verbatim — *"the `ON MATCH SET` clauses below unconditionally overwrite `title`, `authors`, etc. with the OpenAlex values on every re-MERGE. … if INSPIRE-HEP populated a canonical journal title in `title`, this re-MERGE would clobber it with the OpenAlex preprint title. E09_S02 must introduce a per-field source-rank predicate (or split the `_merge_paper` writers per-source) before adding any cross-source enrichment that writes the same columns."* This is the single most important constraint on the design.
- **Checkpointing** (`graph_ingest.py:375–397`): atomic `os.open` + `os.fsync` + `os.replace`, `.tmp` sibling in the same directory (F7), batch flushed every `CHECKPOINT_BATCH_SIZE = 100`. Failure tracking via `state["fetch_failures"]` (F3) — list of `{arxiv_id, error}`; CLI exits 1 while non-empty.
- **Validation precedes I/O** (`graph_ingest.py:524`): `validate_paper_id(arxiv_id)` before any fetch — Threat 1 mitigation.

### `ingest/kuzudb_schema.py`

- `KUZU_SCHEMA_VERSION = 1` (line 46); F6-mandated bump on any DDL mutation. **E09_S02 bumps to 2.**
- `papers` table columns: `paper_id, title, abstract, authors, year, categories, oa_work_id` (lines 58–67). E09_S02 adds nullable `doi`, `journal_ref`, `inspire_id` (per the brief; all `STRING`).
- `cites` rel table: `source STRING, confidence FLOAT` (lines 70–74) — the docstring already enumerates `"openAlex" | "inspire" | "intra-paper"`.
- `SCHEMA_STATEMENTS` is a `tuple[str, ...]` of idempotent `CREATE … IF NOT EXISTS` statements. To add columns, Kùzu 0.11 supports `ALTER TABLE … ADD …`; appending three `ALTER TABLE papers ADD doi STRING` (each idempotent via try/except on "already exists" — Kùzu does **not** support `ADD COLUMN IF NOT EXISTS`) is the migration shape. **Open question (Q3 below).**

### `tests/test_graph_ingest.py` — mocking pattern to mirror

Mock target is the module-level fetch function: `monkeypatch.setattr(graph_ingest, "_fetch_openalex_work", _stub)` (line 122). The stub signature `(arxiv_id, contact_email) -> dict | None`. `None` represents the 404 path. The `fixture_corpus` (P1..P5 with one paper-not-in-source case) is the template — E09_S02 needs the analogous shape (some IDs in INSPIRE, one not, intentional cycle, external reference dropped).

### Design notes that apply

- **`05-storage-and-indexing.md` § Kùzu citation graph** (lines 185–237): the *aspirational* schema names the rel table `CITES` with `source ENUM('inspire', 'openalex', 'tex_extracted')` and is seeded *"INSPIRE-HEP for hep-th, math-ph (per-paper API enrichment, continuous)"*. The current Tier-3 minimal schema uses lowercase `cites`/`papers` per `kuzudb_schema.py:20–28` — we follow the implemented schema, not the aspirational one.
- **`08-security-observability-ops.md` § Threat 7: Source ingestion fetches** (lines 88–98): *"Verify TLS certs (default for the HTTP client; do not disable). … Content-length sanity checks (a single paper > 100 MB source is suspicious). Sandbox the parser …"* Threat 7 was originally written about arxiv.org/ar5iv but generalizes to any external citation source — `INSPIRE_MAX_RESPONSE_BYTES` is the AC.
- **`03-ingestion-pipeline.md` § Source 4 (citation enrichment, not corpus): INSPIRE-HEP** (lines 61–70): *"Endpoint: `https://inspirehep.net/api/literature` … Free, generous limits (~15 rps with backoff), structured records with references already resolved to other arXiv IDs and DOIs. Citation graph backbone for the physics half of the corpus."* Note the design-note rate is **15 rps**; the brief says **5 rps**. See §3.

## 2. Prior decisions and lessons

Recent commits: `732dd8e` (E09_S01 feat) and `95fd3cf` (E09_S01 rect closing 3 HIGH + 5 MEDIUM + 1 LOW) define the bar.

What to copy verbatim from `graph_ingest.py`:

1. `build_user_agent(contact_email)` + a `?mailto=` (or other polite-pool query string — but INSPIRE doesn't document one; see §3).
2. The `_fetch_*_record` retry loop (429/503 + `Retry-After`, attempts cap, exponential backoff).
3. The `_normalize_source` argparse `type=` callable pattern (F1).
4. `apply_schema` idempotent-DDL pattern; bump `KUZU_SCHEMA_VERSION` to 2 (F6).
5. Checkpoint atomic-write + `_serialize_failures` + nonzero CLI exit on pending failures (F3, F7).
6. `urllib.request` only (stdlib) — no new runtime deps.
7. Test pattern: `monkeypatch.setattr(inspire_ingest, "_fetch_inspire_record", stub)`.

**F4 closure (the key design decision for this milestone).** Three options; I recommend **option C**:

- **A.** Separate `_merge_paper_inspire` writer that touches *only* `doi`, `journal_ref`, `inspire_id` (and never `title`/`authors`/`abstract`/`year`). Pro: zero risk to OpenAlex columns; cleanest blast radius. Con: throws away INSPIRE's better title/journal data even when OpenAlex's is empty.
- **B.** Shared `_merge_paper` with a `source_rank` arg and per-field precedence table. Pro: encodes priority once. Con: now the OpenAlex writer needs to read `inspire_id` to know whether to overwrite — extra round-trip per paper.
- **C. (recommended)** Asymmetric `ON CREATE`/`ON MATCH` per field: `ON CREATE SET p.title = $title` (so first writer wins) for fields both sources own; `SET p.doi = $doi, p.journal_ref = $journal_ref, p.inspire_id = $inspire_id` on every MERGE (INSPIRE-exclusive columns). Also: change the OpenAlex `_merge_paper`'s `ON MATCH` to *only* update `oa_work_id` and the OpenAlex-exclusive columns, leaving `title/authors/abstract/year` immutable after first write. Pro: source-of-record is "whoever resolved the paper first," matches the brief's "additive enrichment" framing, no priority table. Con: requires touching `graph_ingest._merge_paper` (a 4-line change; covered by existing tests that pin those columns on a fresh DB).

Justification for C: the brief says *"Existing edges from OpenAlex are not overwritten — this is additive enrichment."* Symmetric "first-writer-wins" for node properties is the natural generalization of "additive" semantics to nodes.

**Mirror the per-source response cap (F2).** Use `INSPIRE_MAX_RESPONSE_BYTES = 10 * 1024 * 1024`. The OpenAlex cap is 5 MiB; INSPIRE refs lists are larger.

## 3. External sources — INSPIRE-HEP REST API

Probed live against `https://inspirehep.net/api/` on 2026-05-10.

**Endpoint shapes (both work; pick the path form):**

- `GET https://inspirehep.net/api/arxiv/<arxiv_id>` — direct identifier path. For `1207.7214`, returns one literature record. **Recommended** — clearer than the q= form, no URL escaping needed, mirrors the OpenAlex `/works/<id>` shape.
- `GET https://inspirehep.net/api/literature?q=arxiv:<arxiv_id>` — query form; returns a `{hits: {hits: [...], total}}` envelope. Use only if multiple hits are expected (versions/replacements).

**Rate limit (verbatim from `github.com/inspirehep/rest-api-doc`):** *"every IP address is allowed 15 requests in a 5s window."* That is **3 rps sustained** (not 5, not 15). The brief's "≤5/second" AC is *technically* compliant since 3 < 5, but a naive 5 rps sender will burst-trip the bucket. The design note's "~15 rps with backoff" is wrong (or referred to the 15-in-5s window misread). **Recommendation:** `INSPIRE_POLITE_SLEEP_SECONDS = 0.34` (≈2.94 rps, safely under both the 5 rps AC and the 15-in-5s window). On 429 honor `Retry-After` — confirmed via the GitHub repo doc.

**Headers.** No polite-pool convention is documented. INSPIRE doesn't ask for `mailto=` or a contact email. Recommendation: still send `User-Agent: arXMCP/0.1 (mailto:<email>)` via `build_user_agent` (consistency + courtesy + a real contact if they ever do rate-limit by UA), and `Accept: application/json`. No query-string mailto.

**Response shape (live, verbatim keys for `arxiv/1207.7214`):**

- Top-level: `updated, uuid, links, created, revision_id, id, metadata`.
- `metadata` keys include: `control_number` (the INSPIRE recid — this is `inspire_id`), `arxiv_eprints` (list of `{value, categories}`), `dois` (list of `{value}` — take `dois[0].value` if present), `publication_info` (list — first element has `journal_title, journal_volume, page_start, page_end, year`; concatenate into a `journal_ref` string), `collaborations` (list of `{value}` — e.g. ATLAS, CMS), `references` (the cited-papers list), `citation_count` (forward-cite count, not the list).
- **`references[*]` shape (verbatim, live):**

  ```json
  {
    "record": {"$ref": "https://inspirehep.net/api/literature/1345805"},
    "reference": {
      "misc": ["title or note"],
      "label": "10",
      "authors": [{"full_name": "Pasterski, S."}],
      "arxiv_eprint": "1502.06120"
    },
    "curated_relation": false
  }
  ```

  **Reference identification (Q5 answer):** prefer `reference.arxiv_eprint` (a bare arXiv ID — what we want for the `cites` reverse map); fall back to `reference.dois[0].value` only if we ever build a DOI reverse map; the `record.$ref` URL ends in the INSPIRE recid (parse with `Path(url).name`) as a tertiary fallback. Many references have *neither* `arxiv_eprint` nor `record` (pure journal/book refs) — these are silently dropped, mirroring the OpenAlex "not in corpus" branch.

- **Forward citations (the `citations` field claimed in the brief): IT DOES NOT EXIST as an inline list on the record.** The `metadata.citations` field is absent. To get citers you query `GET /api/literature?q=refersto:recid:<control_number>&fields=arxiv_eprints,control_number&size=N` (paginated; total in `hits.total`). **AC implication:** the brief's "both `references` (papers the target cites) and `citations` (papers that cite the target)" is half-true. Recommendation: implement the forward-citation pass as an *optional* second sub-pass (a separate `_fetch_inspire_citers(recid)` that paginates `refersto:recid:`) and gate it behind a CLI flag (`--include-back-refs` default off). The MUST-have path is `references`. The brief's milestone goal — improving graph completeness for physics papers — is mostly served by `references` alone since the target paper is in the corpus and the references will close many in-corpus pairs by reverse-mapping. Adding forward citers helps coverage when the citer is in the corpus and the target's references list doesn't include the citer (asymmetric metadata), which is rare but real.

- **Required fields query param (response-size discipline):** `?fields=control_number,arxiv_eprints,dois,publication_info,collaborations,references` — drops `authors` (huge) and `abstracts` and trims responses by ~10× on big collaboration papers. Pin this list as `INSPIRE_FIELDS_REQUEST`.

- **API versioning.** No URL-path version exists; no `Accept-Version` is documented. The repo `inspirehep/rest-api-doc` is the de facto schema. **Pin via response shape regression test**, not URL. Commit a snapshot (`tests/fixtures/inspire_atlas_higgs.json`) of one stripped record and a `test_response_shape_pinned` that asserts the keys we depend on are present. Risk-note compliance.

## Open questions

- **Q1: arXiv-ID → INSPIRE-ID mapping.** Resolved. Use `GET /api/arxiv/<arxiv_id>`; `inspire_id = str(metadata.control_number)`. The query form `?q=arxiv:<id>` returns the same record under `hits.hits[0]`. The path form is canonical.
- **Q2: F9 / categories-column-vs-arXiv-categories mismatch.** Critical. The current `categories` column is OpenAlex Topics display names (e.g. `"Algebraic Geometry"`), never the strings `"hep-th"` or `"math-ph"`. The brief's filter `categories LIKE "%hep-th%" OR categories LIKE "%math-ph%"` **matches zero rows on E09_S01-ingested data**. Three options:
  - **(a) preferred:** *don't filter at all in this milestone.* Iterate over **all** `papers` nodes, GET `/api/arxiv/<id>` for each; INSPIRE returns 404 for non-physics papers and we skip — let INSPIRE be the source of truth on "is this a physics paper." Cost: extra 47 wasted GETs against the 50-paper seed (all `math.AG`). At ~3 rps that's ~16 s. Trivially acceptable for seed-corpus scale; correctness > efficiency at this size.
  - **(b)** Use INSPIRE's `metadata.arxiv_eprints[0].categories` from the response itself to confirm physics-relevance *after* fetching, and gate the metadata-write+edge-emit step on `set(categories) & {"hep-th", "math-ph"} != ∅`. This is the "let INSPIRE classify" path.
  - **(c)** Defer to a future arXiv-metadata fetcher that backfills a true `arxiv_categories STRING[]` column — out of scope per E09_S01 rect's F9-deferral note.
  - **Recommendation: (a) + (b) combined** — iterate all papers, INSPIRE 404 is the no-op; on success, only write metadata + edges if `arxiv_eprints[*].categories ∩ {hep-th, math-ph} ≠ ∅`. Defensive against the seed corpus expanding to include non-physics papers that happen to be in INSPIRE.
- **Q3: Kùzu `ALTER TABLE … ADD column` syntax + idempotency.** Kùzu 0.11 supports `ALTER TABLE papers ADD doi STRING` but **does not** support `ADD COLUMN IF NOT EXISTS`. Two options: (i) catch the "already exists" error in `apply_schema` and treat as no-op; (ii) gate the ALTERs on `read_schema_version() < 2`. Recommend **(ii)** — uses the `_schema_meta` machinery F6 introduced for exactly this purpose. Bump `KUZU_SCHEMA_VERSION = 2`. The MERGE in `apply_schema` writes the new version after the ALTERs succeed.
- **Q4: Seed-corpus coverage.** Confirmed via `tools/seed-papers.txt`: 50 IDs, *all* `math.AG` (curated from `export.arxiv.org/api/query?cat=math.AG`). **Zero hep-th or math-ph papers.** The brief's AC#1 ("For all seed corpus papers with `hep-th` or `math-ph`…") is vacuously satisfied today. **The integration test MUST use a synthetic fixture corpus with 1–2 physics IDs** (e.g. `1207.7214` for ATLAS, `1502.06120` for the Pasterski–Strominger–Zhiboedov memory paper, both confirmed live). Production-risk flag for the implementer: this milestone is effectively un-exercised on the live seed corpus and only becomes meaningful when the corpus expands beyond Tier-0.
- **Q5: `references` reference-space.** Resolved. `reference.arxiv_eprint` (bare arXiv ID) is the primary key for in-corpus reverse mapping; `reference.dois[*].value` and `record.$ref` are fallback ID spaces, neither needed for E09_S02 since the corpus is keyed by arXiv ID.
- **Q6: F4 closure shape.** Recommend option **C** above (asymmetric `ON CREATE`/`ON MATCH` per column; INSPIRE-exclusive columns set on every MERGE, shared columns set only on CREATE). Touch `graph_ingest._merge_paper` to drop the `ON MATCH SET` for `title/authors/abstract/year/categories`; add a regression test pinning "OpenAlex re-MERGE after INSPIRE write does not overwrite INSPIRE's `journal_ref`."
- **Q7: Forward-citations (`citations`).** No inline field — needs a paginated `refersto:recid:` search. Recommend deferring forward-citations to a `--include-back-refs` flag (default off); document the gap in the implementation summary as the brief's "approximation."

## External writes the implementation will require

| type | target | why |
| --- | --- | --- |
| API call (test-time, MOCKED) | `https://inspirehep.net/api/arxiv/<id>` and `https://inspirehep.net/api/literature?q=refersto:recid:<n>` | record fetch + optional forward-citation pagination; must be `monkeypatch.setattr`-stubbed in CI, mirroring `_fetch_openalex_work` |
| API call (operator-driven runtime only) | same INSPIRE-HEP endpoints | actual enrichment run by a human operator after E09_S01 lands; NOT triggered by CI |
| local file write | `var/arxmcp/ops/inspire-ingest-checkpoint.json` (or similar) | resumable checkpoint, atomic write |
| local DB write | `var/arxmcp/index/kuzu/` | schema migration (ALTER TABLE × 3, bump `KUZU_SCHEMA_VERSION` row in `_schema_meta`) + `MERGE` upserts on `papers` and `cites` |
| local config write | `pyproject.toml` | none expected — stdlib `urllib` is sufficient; no new runtime dep |
| commit fixture | `tests/fixtures/inspire_atlas_higgs.json` (and one math-ph snapshot) | response-shape regression pin per the risk-note ("Pin the response parsing to a documented API version") |

Nothing in this list crosses the external-write boundary at gate time. No PRs, tickets, infra mutations, or pushes to remote. The orchestrator should treat this milestone as **locally executable** with the standard mock-the-API discipline.
