# E09_S02 Research Synthesis

**Milestone:** INSPIRE-HEP per-paper enrichment (hep-th / math-ph).
**Inputs merged:** [research-brief-1.md](research-brief-1.md),
[research-brief-2.md](research-brief-2.md).
**Date:** 2026-05-10.

The two briefs converged on most facts (rate limit, response shape,
F-finding inheritance, the F9 categories-column blocker, the empty-seed
problem) and disagreed cleanly on **F4 closure shape**. Both options
are presented below with the pick + reasoning.

---

## 1. Vendor facts both researchers verified live

These are the operational constants the implementer must use.

| fact | value | sources (both confirm) |
|---|---|---|
| API base | `https://inspirehep.net/api` | R1 §3, R2 §3 |
| Direct lookup endpoint | `GET /api/arxiv/<arxiv-id>` (preferred over `?q=arxiv:<id>`) | R1 §3, R2 §3 |
| Real rate limit | **15 requests / 5-second window = 3 rps sustained** (the design note's "15 rps" and brief's "5 rps" are both wrong / loose) | R1 §3 (verbatim quote), R2 §3 |
| Polite-pool sleep | `0.2 s` (R2) → `0.34 s` (R1, more conservative). Either satisfies AC#6's "≤ 5/sec" — pick **`0.25 s`** for headroom | R1 §3 (0.34), R2 §3 (0.2) |
| 429 floor | `5.0 s` per the docs (failed requests still count toward the quota) | R2 §3 |
| Headers | `User-Agent: arXMCP/0.1 (mailto:<email>)` (reuse `tools.arxiv_fetch.build_user_agent`) + `Accept: application/json`. NO mailto query param — INSPIRE does not document one | R1 §3, R2 §3 |
| Auth | none required | R1 §3, R2 §3 |
| Response cap | between **8 MiB (R2)** and **10 MiB (R1)**. Pick **8 MiB** — R2's empirical 150 KB ATLAS Higgs and R1's 1 MB worst-case both fit comfortably | R1 §3, R2 §3 |
| Schema versioning | no URL-version; pin via snapshot-fixture regression tests | R1 §3 (commit `tests/fixtures/inspire_<id>.json`), R2 §3 |
| `?fields=` filter | `?fields=control_number,arxiv_eprints,dois,publication_info,collaborations,references` cuts response ~10× by dropping `authors` + `abstracts` | R1 §3 |

**INSPIRE record top-level shape (verified live for `1207.7214`):**

- `metadata.control_number` (int) → goes into `inspire_id` (cast to string).
- `metadata.dois[0].value` → goes into `doi`.
- `metadata.publication_info[0].{journal_title, journal_volume, year, page_start, page_end}` → concatenate into `journal_ref` STRING.
- `metadata.collaborations[*].value` (e.g. `"ATLAS"`, `"CMS"`) → not in the schema; defer.
- `metadata.references[i].reference.arxiv_eprint` (when present) → bare arXiv ID directly usable as `paper_id` for the in-corpus reverse-map filter. **No second lookup needed.**
- `metadata.citations` field **does not exist as an inline list.** The brief's "both `references` and `citations`" framing is half-true; forward-citations require a paginated `?q=refersto:recid:<n>` search. **Decision (both agree):** defer to an opt-in `--include-back-refs` flag, default off. The brief's milestone goal (improve graph completeness) is mostly served by `references` alone.

---

## 2. Two CRITICAL discrepancies between the brief and reality

Both briefs flagged these. They are blocking-quality issues that must be
resolved before code is written.

### 2.1 F9 — `categories` column does not contain arXiv categories

The current `papers.categories` STRING column carries OpenAlex Topics
display names (e.g. `"Algebraic Geometry"`), NOT arXiv categories like
`"hep-th"`. R1 and R2 independently confirmed: the brief's
`categories LIKE '%hep-th%' OR categories LIKE '%math-ph%'` filter
matches **zero rows** on any seed corpus that's been ingested via the
existing `graph_ingest.py`. F9 was deferred from E09_S01 explicitly.

**Resolution (both agree):**

- **Do NOT filter on `categories` in production code.** Iterate over
  ALL `papers` nodes; let INSPIRE's `arxiv/<id>` endpoint return 404
  for non-physics papers (the natural skip path).
- **AND** post-fetch, gate the metadata-write + edge-emit step on
  `set(metadata.arxiv_eprints[*].categories) ∩ {"hep-th", "math-ph"} ≠ ∅`.
  This is the "let INSPIRE classify" path — defensive against
  non-physics papers that happen to be in INSPIRE for some other
  reason.
- **Do NOT rename `categories` → `topics` in this milestone.** That
  schema rename touches every reader and is a separate concern.
  F9 stays deferred per the E09_S01 rect; document the trade-off
  in the CLI `--help` and the implementation summary.
- The integration test uses a **synthetic fixture corpus** with at
  least one paper whose mocked INSPIRE response includes
  `arxiv_eprints[0].categories = ["hep-th"]`. Pre-populate the
  Kùzu DB by calling `graph_ingest.ingest()` first with stubbed
  OpenAlex responses, then run INSPIRE enrichment.

### 2.2 Seed corpus has zero hep-th / math-ph papers

`tools/seed-papers.txt` was curated for math.AG (E01_S03). All 50
seed IDs are `2604.*` / `2605.*`. R1 confirmed via direct read.

**Resolution (both agree):**

- AC#1 is *vacuously satisfied* on the live seed corpus today (zero
  candidate papers means the loop is a no-op).
- The integration test MUST use a synthetic fixture; R1 suggests
  using `1207.7214` (ATLAS Higgs, well-known live) as a fixture ID,
  R2 suggests pre-populating the DB.
- Production-risk flag: this milestone is effectively un-exercised
  on the live seed corpus and only becomes meaningful when the
  corpus expands beyond Tier-0. The implementation summary should
  call this out so a future operator doesn't think it's dead code.

---

## 3. F4 closure — the central design choice

The E09_S01 rect commit closed F4 with a docstring note flagging the
multi-source-write hazard and explicitly named E09_S02 as the place to
fix it. Both researchers proposed solutions; they disagree on shape.

### Option A — R2's "split writers" (recommended by R2)

A new `_merge_paper_inspire(conn, paper_id, ri)` writer that touches
ONLY `doi`, `journal_ref`, `inspire_id`, and never `title` /
`authors` / `abstract` / `year` / `categories`. The OpenAlex
`_merge_paper` is unchanged.

- **Pro:** structural, explicit ownership ("OpenAlex owns prose;
  INSPIRE owns identifiers + bibliographic ref"). Easy to read
  "what does each source own?" by grep. No risk of breaking E09_S01
  tests.
- **Pro:** future enrichers (e.g. an arXiv-metadata fetcher for the
  true `arxiv_categories STRING[]` column F9 wants) get their own
  writer with no merge logic.
- **Con:** throws away INSPIRE's potentially-better title / journal
  data even when OpenAlex's value is empty. INSPIRE often has the
  *canonical* publication title; OpenAlex has the *preprint* title.
  In practice this rarely matters since the title is informational.

### Option B — R1's "asymmetric ON CREATE / ON MATCH" (recommended by R1)

Change the existing `_merge_paper` to use `ON CREATE SET` for the
shared fields (`title` / `authors` / `abstract` / `year` /
`categories`) and unconditional `SET` only for source-exclusive
fields. Then the new `_merge_paper_inspire` does the same (sets
INSPIRE-exclusive fields unconditionally; touches shared fields only
on CREATE).

- **Pro:** symmetric "first-writer-wins" for prose. Matches the
  brief's "additive enrichment" framing exactly.
- **Pro:** unified protocol; one mental model.
- **Con:** requires touching `_merge_paper` (a 4-line change), which
  changes E09_S01's behavior on re-run. The existing
  `test_metadata_populated_from_openalex` test would still pass
  (it runs against a fresh DB), but a future test asserting "an
  OpenAlex re-MERGE updates `title` to a newer value" would now
  fail. No such test exists today, but the implementation summary
  for E09_S01 said `_merge_paper` "uses ON MATCH SET to overwrite
  all fields" — that documented behavior would need to change.

### Pick: **Option A (split writers)** + a docstring rationale

Reasoning: the criterion is "what's least surprising for a future
maintainer reading this code?" Two writers with explicit ownership
beats one writer with subtle precedence rules. The brief's "additive
enrichment" framing applies primarily to **edges** (which both sources
add cleanly via the `MERGE (a)-[r:cites {source: $source}]->(b)` key);
node properties are a different problem with cleaner solutions when
ownership is fixed by source.

The R1 option C is also defensible and could be revisited in a future
milestone if a third source needs to write the same fields. For now,
two columns × two writers is the simplest correct thing.

**Implementation note:** The OpenAlex `_merge_paper` is left unchanged
(no E09_S01 behavior shift). The new `_merge_paper_inspire` is
strictly additive — it can only set NULL → some-value or some-value →
some-value (no reads required). The docstring explicitly names the
ownership boundary.

---

## 4. Source-string casing: "inspire" (lowercase)

R2 noticed `05-storage-and-indexing.md:211` says
`source ENUM('inspire', 'openalex', 'tex_extracted')` — all lowercase.
The current implementation writes `"openAlex"` (camelCase). The brief
itself uses `"openAlex"` for OpenAlex.

**Resolution:** new code writes lowercase `"inspire"` (matches the
design note). The OpenAlex camelCase remains a documented drift; a
future cleanup can normalize. AC#3 ("existing source=openAlex edges
are not duplicated or overwritten") is satisfied by the
`MERGE (a)-[r:cites {source: $source}]->(b)` structure regardless of
casing — the source is part of the edge's MERGE key, so distinct
casings produce distinct edges.

This is a minor inconsistency. Document in the implementation
summary; do NOT migrate existing OpenAlex edges.

---

## 5. Schema migration to v2 — Kùzu `ALTER TABLE` plan

Bump `KUZU_SCHEMA_VERSION` from `1` to `2`. Add three nullable
columns to `papers`: `doi STRING`, `journal_ref STRING`,
`inspire_id STRING`.

**Idempotency.** Kùzu 0.11 supports `ALTER TABLE … ADD column` but
does NOT support `ADD COLUMN IF NOT EXISTS`. Two paths to idempotency:

- **(R1)** Catch the "already exists" `kuzu.RuntimeError` and treat
  as no-op.
- **(R2)** Introspect via `CALL TABLE_INFO('papers')` first; skip
  ADDs whose column is already present.

**Pick: R2's introspection approach.** Cleaner — explicit
"check then act" loop matches the spirit of the v1
`CREATE … IF NOT EXISTS` statements; no try/except on a
foreign-library exception class that may rename.

**Migration sequence in `apply_schema`:**

1. Apply existing v1 statements (CREATE NODE / REL TABLE IF NOT
   EXISTS, MERGE `_schema_meta`).
2. New: introspect `papers` columns; for each of `doi`,
   `journal_ref`, `inspire_id` not already present, run
   `ALTER TABLE papers ADD <col> STRING`.
3. Re-MERGE `_schema_meta` with `value=KUZU_SCHEMA_VERSION` (= 2).

**Migration is forward-only.** Downgrade is not supported (Kùzu
doesn't have `DROP COLUMN` reliable across versions; we accept
v1 → v2 is one-way).

**Regression test:** `test_apply_schema_adds_v2_columns` —
calls `apply_schema(db_path)` on a fresh DB; asserts all three
new columns exist via `CALL TABLE_INFO('papers')`. A second test
`test_apply_schema_v1_to_v2_migration` simulates a v1-only DB
(create the v1 schema by hand without the ALTERs, stamp version=1)
and verifies the migration brings it to v2.

---

## 6. Implementation skeleton

Both researchers agree on the structural shape. Consolidated:

**File layout:**

- `ingest/inspire_ingest.py` — module mirroring `graph_ingest.py`
  shape:
  - `_ResolvedInspire` dataclass (`inspire_id`, `doi`,
    `journal_ref`, `references_arxiv: tuple[str, ...]`, optionally
    `categories: tuple[str, ...]` for the post-fetch physics gate).
  - `_fetch_inspire_record(arxiv_id, contact_email) -> dict | None`
    — module-level for monkeypatch. Returns None on 404.
  - `_merge_paper_inspire(conn, paper_id, ri)` — only writes the
    INSPIRE-exclusive columns (does NOT touch title / authors /
    abstract / year / categories).
  - `enrich(seed_or_db_paper_ids, db_path, checkpoint_path,
    contact_email, *, fetch_fn=None, sleep_seconds=...,
    batch_size=..., include_back_refs=False) -> dict[str, Any]` —
    the two-pass main loop (resolution + edge-emit), mirroring
    `graph_ingest.ingest()`.
  - CLI: `main(argv)` with `--seed-file`, `--checkpoint`, `--kuzudb`,
    `--include-back-refs`. The default behavior iterates ALL
    `papers` nodes in the existing graph (not a seed file); the
    `--seed-file` option lets the operator constrain to a subset for
    testing. **Open question:** should the default be "all papers"
    or "seed file"? Both researchers lean "all papers" (matches the
    brief's "iterates over all `papers` nodes"). I pick **all
    papers** with `--seed-file` as an opt-in narrowing.
- `ingest/kuzudb_schema.py` — bump `KUZU_SCHEMA_VERSION = 2`; add
  the introspect-and-ALTER block; add an `_apply_v2_alters()`
  helper.
- `tests/test_inspire_ingest.py` — synthetic fixture with at least
  one hep-th paper, one math-ph paper, one paper with
  `arxiv_eprint` references in-corpus, one paper not in INSPIRE
  (404), one paper with collisions on INSPIRE record_id.
- `tests/fixtures/inspire_atlas_higgs.json` — minimal real-shape
  fixture for the schema-pin regression test.

**Reuse, do not reinvent (from `graph_ingest.py`):**

- `tools.arxiv_fetch.build_user_agent` (User-Agent format).
- `tools.arxiv_fetch.parse_retry_after` (Retry-After parsing).
- `tools.arxiv_fetch.DEFAULT_503_BACKOFF_SECONDS` /
  `MAX_503_BACKOFF_SECONDS` (exponential backoff bounds).
- `graph_ingest.save_checkpoint` and `graph_ingest.load_checkpoint`
  patterns (atomic write; `fetch_failures` tracking).
- `graph_ingest._serialize_failures` helper.
- `graph_ingest._merge_cite` — INSPIRE edges go through the SAME
  `_merge_cite(conn, src, dst, source="inspire", confidence=1.0)`
  call; AC#3 falls out of the existing edge MERGE-key composition.
- `graph_ingest._normalize_source` — extend to accept `"inspire"`
  / `"INSPIRE"` / `"Inspire"` and canonicalize to lowercase
  `"inspire"`.
- `tools.fetch_seed.read_seed_list` (for `--seed-file`).

**Update an existing test (per R2):**
`tests/test_graph_ingest.py::TestRectificationGuards::test_f1_source_rejects_unknown_value`
currently uses `"inspire"` as the unknown-value case. With E09_S02,
`"inspire"` becomes valid, so that test must be **rewritten** to use
`"semanticscholar"` or another genuinely-unknown source name. Do
NOT delete the regression — the F1 finding is still closed; just the
"unknown" sentinel changes.

**Constants to define in the new module:**

- `INSPIRE_API_BASE = "https://inspirehep.net/api"`
- `INSPIRE_POLITE_SLEEP_SECONDS = 0.25` (3.3 rps; under the brief's
  ≤5 AC and the docs' 15-in-5s real limit)
- `INSPIRE_429_FLOOR_SECONDS = 5.0` (per docs)
- `INSPIRE_MAX_RESPONSE_BYTES = 8 * 1024 * 1024` (8 MiB)
- `INSPIRE_TIMEOUT_SECONDS = 30.0`
- `MAX_HTTP_RETRIES = 3`
- `INSPIRE_FIELDS_REQUEST = "control_number,arxiv_eprints,dois,publication_info,collaborations,references"`

---

## 7. F-finding inheritance from E09_S01 (R2's checklist, kept verbatim)

Every closed finding from `95fd3cf` applies to INSPIRE. The
implementer must NOT re-introduce any of these. Listing for
explicitness:

- **F1** (CLI casing) — `_normalize_source` accepts `"inspire"` /
  `"INSPIRE"` / `"Inspire"`. Add regression tests; rewrite
  `test_f1_source_rejects_unknown_value` to use a genuinely-unknown
  value.
- **F2** (response cap) — `INSPIRE_MAX_RESPONSE_BYTES = 8 MiB`,
  not the OpenAlex cap.
- **F3** (fetch failure tracking) — same pattern; `URLError` writes
  to `state["fetch_failures"]`; CLI exits 1 while non-empty.
- **F4** (multi-source-write) — closed by Option A above
  (split writers).
- **F5** (seed-list parser) — reuse `tools.fetch_seed.read_seed_list`
  if `--seed-file` is wired.
- **F6** (schema version) — bump to 2; new test pins the new
  version stamp.
- **F7** (atomic fs) — reuse `graph_ingest.save_checkpoint`.
- **F8** (collision detection) — INSPIRE has `control_number`; if
  two papers resolve to the same `control_number` (the
  withdrawn/replaced case), log a warning. Same shape as the
  `oa_work_id` collision test.
- **F10** (non-vacuous test assertions) — every new assertion must
  fail when the production behavior is wrong.

R2's instruction to the implementer is sound: `git show 95fd3cf`
before writing a single line of code.

---

## 8. Open questions (consolidated)

Items resolved in this synthesis:

1. ✅ **arXiv-ID → INSPIRE-ID mapping**: `GET /api/arxiv/<arxiv_id>`
   direct path; `inspire_id = str(metadata.control_number)`.
2. ✅ **F9 categories filter**: don't filter; iterate all papers;
   INSPIRE 404 = skip; post-fetch gate on
   `arxiv_eprints[*].categories ∩ {hep-th, math-ph} ≠ ∅`.
3. ✅ **Schema migration**: introspect via `CALL TABLE_INFO('papers')`;
   ALTER TABLE for missing columns only.
4. ✅ **Seed corpus has zero physics papers**: integration test uses
   synthetic fixture; production no-op until corpus expands; flag
   in implementation summary.
5. ✅ **References reverse mapping**: `references[*].reference.arxiv_eprint`
   directly; no second lookup.
6. ✅ **F4 closure**: split writers; new
   `_merge_paper_inspire(conn, paper_id, ri)`; OpenAlex
   `_merge_paper` unchanged.
7. ✅ **Forward citations**: defer behind `--include-back-refs` flag,
   default off.
8. ✅ **Source-string casing**: lowercase `"inspire"` for new edges.
9. ✅ **Polite-pool sleep**: `0.25 s` (3.3 rps).

Items the implementer should resolve during Phase 2:

1. **Default iteration scope**: `--seed-file` opt-in, all-papers
   default. Confirm by reading the brief's "iterates over all
   `papers` nodes" wording.
2. **Schema-meta shape**: stay with single-int `version` row, not
   migration-history list (R2's recommendation; R1 silent).
3. **Live `?fields=` query string**: pin
   `INSPIRE_FIELDS_REQUEST` (R1 recommendation; bandwidth + parse
   surface reduction).
4. **Snapshot fixture**: commit one stripped real INSPIRE response
   to `tests/fixtures/inspire_<id>.json` for the schema-pin test.
   Strip authors / titles to keep the file small (< 50 KB).

---

## 9. External writes the implementation will require

Combined and deduped from both briefs.

**Local-only (no user gate at the milestone boundary):**

| type | target | why |
|---|---|---|
| code edits | `ingest/inspire_ingest.py`, `ingest/kuzudb_schema.py`, `tests/test_inspire_ingest.py`, `tests/test_graph_ingest.py` (rewrite F1 unknown-value test), `tests/fixtures/inspire_<id>.json` | new module + schema bump + tests |
| filesystem write | `var/arxmcp/index/kuzu/` (operator local) | schema v2 ALTERs + new INSPIRE rows / edges; gitignored |
| filesystem write | `var/arxmcp/ops/inspire-ingest-checkpoint.json` (operator local) | checkpoint state; gitignored |

**Network calls (operator-only, NEVER in CI; tests MUST mock):**

| type | target | why |
|---|---|---|
| HTTP GET | `https://inspirehep.net/api/arxiv/<id>?fields=...` | per-paper INSPIRE record fetch |
| HTTP GET (opt-in `--include-back-refs`) | `https://inspirehep.net/api/literature?q=refersto:recid:<n>&fields=...&size=200` | optional forward-citation pagination |

**No new runtime dependencies.** Stdlib `urllib` is sufficient.

**Phase 4 boundary:** no `git push`, no GitHub mutations, no
external API calls in CI. The `external_writes_required` list at
the milestone boundary is empty (all local-file edits land inside
the milestone's commits; operator-time HTTP GETs are out of scope).

---

## 10. Severity-tagged risk register for Phase 3

The adversary critic should focus here:

- **CRITICAL**: live INSPIRE calls leak into CI (test regression);
  `_merge_paper_inspire` accidentally writes to a shared column
  (regressing F4 closure).
- **HIGH**: `INSPIRE_MAX_RESPONSE_BYTES` left at the OpenAlex value
  (or worse, the arXiv 200 MB cap); `_normalize_source` accepts
  `"inspire"` but doesn't reject non-source values cleanly; schema
  v2 migration not idempotent; AC#3 violated by accidentally
  re-MERGEing with a different source value.
- **MEDIUM**: `categories ∩ {hep-th, math-ph}` post-fetch gate
  missing or buggy; pulling 30+ unused fields per response
  (`?fields=` not pinned); collision-detection on `control_number`
  missing.
- **LOW**: snapshot fixture not committed; CLI `--help` doesn't
  warn that "for the seed corpus this is currently a no-op";
  source-casing inconsistency between OpenAlex (camelCase) and
  INSPIRE (lowercase) not documented.

---

**End of synthesis.** Phase 2 reads this in full + both briefs
(R1 for the live INSPIRE schema details + the `?fields=` filter,
R2 for the structured F-finding inheritance checklist).
