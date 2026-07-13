# Phase 1 synthesis — source-truth-m1

**Mode:** standard (explore→brief-1, general→brief-2). Both `complete`, 0 injections. Both
live-verified against source (brief-2 made 3 live OAI-PMH GETs). Same env deviation as prior
milestones (bespoke agents → `general-purpose`; lock-free-unavailable-worktree N/A here — m1
took the lock after clearing a stale one).

## The milestone the roadmap *described* vs what the spikes + research proved

The roadmap's e1/m1 text is **stale on three load-bearing points** (spike-1 + this research
override it — that is what the spike existed to do):
1. License comes from **OAI-PMH `GetRecord`** (`https://oaipmh.arxiv.org/oai`), **not** the
   `tools/_arxiv_api.py` Atom client (Atom = 0/30, schema-level absence).
2. License coverage is **not uniform**: new-style papers carry `<license>`; **old-style papers
   carry none** (arXiv-side gap, 2/2 verified under both `arXiv` and `arXivRaw` prefixes).
3. Counts are **142 (bridgeland) + 52 (fourier) = 194**, ~25 old-style — not the roadmap's
   ~200/~65.

## Affected files (deduped)

| File | Action | Role |
|---|---|---|
| `server/documents_store.py` | CREATE | The per-revision documents registry — mirror `server/paper_metadata_store.py` (async-over-sync SQLite, `PRAGMA user_version`, WAL, `synchronous=NORMAL`, idempotent `open()` + `upsert`). New `DocumentRecord` + `DOCUMENTS_DB_FILENAME="documents.db"` (sibling of `paper_metadata.db`). |
| OAI-PMH license client | CREATE | `GetRecord` client: canonical host, `identifier=oai:arXiv.org:<bare_id>` (strip `vN` via `strip_id_version`), parse `<license>` as **optional** + `<header status="deleted">` (withdrawn) in one fetch, `idDoesNotExist` non-fatal, **`defusedxml`**, mirror `ingest/oai_delta.py::_fetch_page` politeness/503/redirect-pinning. (Impl choice: reuse `oai_delta._fetch_page` (verb-agnostic) vs new `tools/`-side fn — implementer's call.) |
| license decision function | CREATE | Advisory-only URI→`license_status` mapping (see Decision B). **Does NOT touch `server/license_policy.py`** (that's m4). |
| `tools/notebook_documents_backfill.py` | CREATE | Backfill CLI — mirror `tools/notebook_metadata_backfill.py` (`papers.txt` membership, idempotency gate, structural 0-re-embed, loud summary line). Per-paper `GetRecord`, 3s politeness (~11 min for 194). |
| coverage report | CREATE | Per-`license_status` + per-ID-shape counts; loud >20%-unknown-on-bridgeland escalation (Decision C). |
| `tests/test_documents_store.py`, `tests/test_notebook_documents_backfill.py`, OAI-PMH client + decision-fn tests | CREATE | Mirror `test_paper_metadata_store.py` / `test_notebook_metadata_backfill.py` / `test_oai_delta.py`. Assert 0-re-embed (LanceDB row count / `corpus_version` unchanged). |

**Untouched (confirmed):** `server/license_policy.py`, `server/handlers/chunk.py`, `server/tools.py`,
`ingest/store.py`, the embedder, `EXPECTED_TOOL_SCHEMA_SHA256` (`TOOL_SCHEMA_VERSION=17` stays).

## Estimated diff + Phase 2 path

New store + OAI-PMH client + decision fn + backfill CLI + coverage + full test suites ≈ **>800
LOC across ~8 files** — genuinely large (m1 is a 5-task milestone). **Path: DELEGATED**, and I'll
**set `allow_large_diff`** (the 5 tasks form one coherent registry system; splitting via
`/roadmap` would be heavier than building the decomposition that already exists). One
`milestone-implementer`, explicit-pathspec commits (concurrent sessions active). Mid-flight
scope guard is pre-acknowledged.

## Acceptance criteria (deduped, traced to roadmap AC1/AC2/AC3)

1. **[AC1]** `documents_store.py` opens idempotently (paper_metadata_store pattern); 2nd open = no-op.
2. **[AC1]** Every registered revision row carries: work id (versionless) + revision id (`vN`),
   raw-source sha256 (**or the abstention marker — Decision A**), parse-artifact sha256
   (`parsed/<id>/index.html`), `CHUNKER_VERSION` (`ingest/chunker_types.py:45`) + `parser_used`
   + LaTeXML-version-**absent-noted**, `fetched_at`, license URI, active/withdrawn/superseded.
3. **[AC1]** License hydrated via **OAI-PMH GetRecord** across all 3 id shapes; `<license>` optional;
   withdrawn from `<header status="deleted">`; `idDoesNotExist` non-fatal.
4. **[AC2]** Advisory decision fn: missing→`unknown`(→truncate); recognized-open→`eligible`;
   real-but-non-CC (`nonexclusive-distrib`)→**per Decision B**; logged advisory, serving unchanged,
   `license_policy.py` untouched.
5. **[AC1/AC3]** Backfill CLI over 194 papers (`papers.txt` membership), 0 chunks re-embedded
   (asserted in a test), idempotent re-run.
6. **[AC3]** Coverage report: per-`license_status` + per-ID-shape counts; loud escalation when
   bridgeland `unknown` >20% (Decision C defines which bucket counts).

## external_writes_required (verbatim from brief-2)

```yaml
external_writes_required: ["git push origin main"]
```
OAI-PMH GETs are read-only hydration (politeness-contracted), not external writes.

## Open questions → OWNER CHECKPOINT (before Phase 2)

- **Decision A — old-style raw-source checksum gap** (~25/194 papers have no raw source on disk):
  abstention (`raw_source_sha256=null` + `raw_source_status=unavailable`, per the roadmap's own
  "abstention not silence") **[recommended]** vs re-fetch (extra ~25 arXiv egress).
- **Decision B — license_status model:** 3-way (`eligible` / `not-allowlisted-open` /
  `unknown`) **[recommended, both researchers]** vs 2-way (folds `nonexclusive-distrib` into one
  bucket, conflating "no data" with "undecided policy" and corrupting the escalation signal).
- **Decision C — >20% escalation bucket:** threshold on `unknown` alone (genuine data gaps)
  **[recommended]**, reporting the `not-allowlisted-open` count equally prominently — vs threshold
  on `unknown + not-allowlisted-open` combined.
- (Non-owner) superseded-status extraction has no existing signal (arXivRaw `<versions>`, unparsed)
  → m1 records active/withdrawn now; superseded deferred with a noted null, unless cheap.
