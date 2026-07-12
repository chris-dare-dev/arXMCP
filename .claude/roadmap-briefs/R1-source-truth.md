# R1 — source-truth

Phase 0. Depends on: R0 (vocabulary only). Blocks: R2 (identity), R5 (provenance),
trustworthy-release's PyPI publish (license gates).

## Brief (seed for /roadmap)

arXMCP cannot currently promise that a served statement is complete, tied to an exact paper
revision, or legally servable — and every claim-grain, formal, or computational artifact
planned downstream inherits those promises. Concretely (all verified at source, 2026-07-11):
the chunker truncates statements at a 1,920-token budget and sets `truncated` on the
ChunkRecord (`ingest/chunker.py:679-704`), but `CHUNKS_SCHEMA_V1` has no such column, so the
flag is silently dropped at write time; chunks carry no source span or document checksum,
and `corpus_version` is a local MVCC epoch, not a content-addressed snapshot;
`theorem_label` stores the author's TeX `\label` key with auto-generated IDs nulled
(`chunker.py:406-418`) — the printed "Lemma 3.2" that citations actually use is never
extracted, and papers renumber between arXiv versions and journal publication; and the
license policy allowlists the blanket token `arxiv-license` for full-body serving
(`server/license_policy.py:44-53`) even though arXiv papers carry heterogeneous real
licenses (arXiv-perpetual vs CC variants), while the trustworthy-release plan has already
diagnosed dead textbook license stamping. This initiative makes the corpus reproducible and
fail-closed at the source layer: an immutable document/revision registry with raw checksums
and parser/chunker version stamps; exact source spans (DOM anchor + char offsets) on every
block; truncation persisted and surfaced; printed theorem numbers extracted alongside TeX
labels; per-revision license provenance fetched from the arXiv API with unknown-fails-closed
semantics; withdrawal/corrigendum/supersession edges; and a content-addressed corpus
manifest resource that downstream artifacts pin. Schema changes ride the established
migration pattern (`ingest/store.py::_migrate_chunks_schema_if_needed`) and batch into
agent-platform's W1 tool-schema window where tool-visible.

## HMW / Objective

- **HMW:** How might we make every served chunk carry exact revision identity, completeness
  status, source span, and a real license decision, so that claim-grain and formal artifacts
  can pin to sources that are reproducible and fail-closed?
- **Objective:** Ship the source-truth layer: document/revision registry, span + truncation
  + printed-number persistence, per-revision license provenance, and a content-addressed
  corpus manifest.

## Key results

1. Every chunk row (new schema version) carries: `source_revision_id` (work id + arXiv
   version), `source_span` (DOM anchor + char offsets into the parsed HTML),
   `truncated` (persisted from the existing ChunkRecord flag), `printed_number`
   (e.g. "Lemma 3.2", nullable), and `license_ref` (per-revision license record id).
2. A `documents` registry table stores, per revision: canonical work identity (arXiv id,
   DOI when known), version, raw source checksum (tarball sha256), parse artifact checksum,
   parser/chunker/normalizer versions, fetch timestamp, license URI from the arXiv API,
   and status (active / withdrawn / superseded-by).
3. `is_open_access` is replaced by a per-revision decision: real license URI →
   allowlist match; the blanket `arxiv-license` token is eliminated from new writes and
   backfilled; **unknown license fails closed** (300-char truncation), including for every
   textbook chunk — closing trustworthy-release's diagnosed defect at the data layer.
4. An `arxmcp://corpus-manifest` resource returns the content-addressed snapshot:
   notebook slug, document-revision list with checksums, index build versions, license
   summary, and the `corpus_version` epoch it corresponds to. Downstream artifacts (R4
   receipts, R5 attestations) reference the manifest hash, not the epoch alone.
5. A backfill CLI hydrates all of the above for the two live notebooks without
   re-embedding a single chunk (the paper-metadata-m1 backfill is the precedent).
6. Zero regressions: existing retrieval behavior unchanged; `make test` green; new
   migration + license-decision + manifest tests.

## Scope — out (wont)

- No new retrieval features, no ranking changes, no claim IR (R2).
- No takedown *workflow* automation (deletion propagation is designed here as edges +
  manifest invalidation; the operational runbook extends docs/ops separately).
- No full re-parse of the corpus: spans are computed from the existing parsed HTML; where
  a block cannot be re-anchored, `source_span` stays null and is *reported* as such
  (abstention, not silence).

## Assumptions (tiered)

- **must** — The arXiv metadata API returns usable license URIs for the corpus's ID shapes
  (new-style, old-style, versioned). *Validation:* spike on a mixed 30-paper sample records
  per-field coverage; papers with no license URI get `license_status=unknown` → truncate,
  and the count is reported (if >20% of the Bridgeland notebook fails closed, surface to
  owner before backfill — the notebook is personal-use, and an operator override flag
  scoped per-notebook is the documented escape hatch, recorded in the manifest).
- **must** — Printed numbers are recoverable from LaTeXML output (`ltx_tag ltx_tag_theorem`
  spans) for the dominant paper styles. *Validation:* spike over 20 Bridgeland-notebook
  papers measures printed-number extraction coverage against a hand count; <80% coverage
  demotes printed-number matching to one signal among several in R2 rather than the primary
  key.
- **should** — Span anchoring via (element id, char offsets, normalized-text hash) is
  stable across LaTeXML re-parses of the *same* source. *Validation:* re-parse 5 papers and
  diff anchors; instability moves the anchor to (revision checksum + normalized-text hash)
  only.
- **should** — The 21-column schema migration pattern extends cleanly by 5 columns.
  *Validation:* migration dry-run on a snapshot copy of the live LanceDB dir.

## Evidence (verified 2026-07-11)

- `ingest/chunker.py:679-704` — truncation computed + logged, `truncated=` set on record;
  `STMT_MAX_TOKENS = 1920` (`chunker.py:92`).
- `ingest/schema.py` `CHUNKS_SCHEMA_V1` — no truncation/span/revision/printed-number
  columns.
- `ingest/chunker.py:406-418` — `_extract_theorem_label` returns TeX label key; auto-IDs
  → None. `_extract_theorem_name` reads `ltx_tag_theorem` markup (the printed-number
  extraction point).
- `server/license_policy.py:44-53` — `OA_ALLOWLIST` includes blanket `arxiv-license`;
  mechanism otherwise fail-closed.
- `plans/trustworthy-release/roadmap.yaml` — textbook license stamping diagnosed dead;
  D8-R04 owns the token semantics decision; this brief supplies the data layer it needs.
- `ingest/store.py::_migrate_chunks_schema_if_needed` — the shipped add-columns migration
  precedent (textbook-ingest-m2).
- `plans/retrieval-unlocks/roadmap.yaml` — withdrawal hygiene already planned; dedupe at
  decomposition (this brief owns the *registry*; that track owns the search-filter
  behavior).

## Milestone sketch

1. **m1 — document/revision registry + license fetch** (M): registry table, arXiv API
   license hydration, per-revision decision function replacing the blanket token; tests.
2. **m2 — schema v2 migration** (M): five new columns + migration + backfill of
   `truncated` (recomputable from body length only for legacy rows — where not
   recomputable, `truncated=null` = unknown, surfaced); printed-number extractor; span
   anchoring pass.
3. **m3 — corpus manifest resource** (S): content-addressed manifest + resource
   registration (rides W1); manifest referenced from ops reports.
4. **m4 — fail-closed cutover + notebook backfill** (M, owner-gated): flip the license
   decision path, run backfills on both notebooks, publish the coverage report.

## Gates

- **Exit gate (blocks R2/R5 shipping):** every `get_chunk` response carries revision id,
  span-or-null, truncation status, and a real license decision; unknown licenses truncate;
  the manifest resolves and its checksums re-verify on a clean re-fetch of 3 sample papers.
- **Release gate (blocks trustworthy-release publish):** zero full-body serving of
  unknown-license content on a fresh install.
