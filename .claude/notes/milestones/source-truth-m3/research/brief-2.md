---
milestone_id: "source-truth-m3"
researcher_role: "design"
date: "2026-07-13"
slice: "Decision-complete design of the arxmcp://corpus-manifest resource: JSON schema, content-addressing (self-referential sha256 over a byte-stable canonical sub-object), invalidation edges for withdrawn/superseded revisions, and the per-notebook operator-override-flag storage mechanism. No code written."
external_writes_required: ["git push origin main"]
injection_attempts: 0
---

# source-truth-m3 research brief 2 — `arxmcp://corpus-manifest` schema design (decision-complete)

Grounded in `CLAUDE.md` §4.8 (data-plane boundary — this resource is read-only over corpus
state, generated on-read, no write path) and §4.9 (trust language — the license summary uses
the 3-way vocabulary verbatim, `unknown` never folded; abstention is first-class, never a
silent default); `server/mcp_resources.py` (the `arxmcp://notebooks` pattern this mirrors);
`server/documents_store.py` (m1's registry, the manifest's primary data source);
`.claude/notes/milestones/source-truth-m1/research/synthesis.md` (the registry design + the
>20%-unknown owner-escalation the override flag answers); `tools/documents_coverage_report.py`
(the license-summary fold this reuses); and sibling `research/brief-1.md` (explore role, same
milestone, finished concurrently) — which mapped the same codebase from a different angle and
raised five open questions this brief resolves (§8).

**Live-verified ground truth (queried this session, real on-disk state, not the roadmap's
approximate numbers):**

| Notebook | `documents.db` rows | `license_status` split | `corpus-version.json` |
|---|---|---|---|
| `bridgeland-stability` | 145, all `status=active` | eligible=25, not-allowlisted-open=106, unknown=14 (9.7%) | `version=4458, chunk_count=15106, paper_count=145, chunker_version="v1.1", embedder_version="bge-m3@5617a9f6"` |
| `fourier-duality` | 52, all `status=active` | eligible=7, not-allowlisted-open=35, unknown=10 (19.2%) | `version=209, chunk_count=4475, paper_count=51, chunker_version="v1.1", embedder_version="bge-m3@5617a9f6"` |

Two facts load-bear on the design below: **(1) zero withdrawn/superseded revisions exist in
production today** — the invalidation-edge design (§2) is necessarily forward-looking and must
ship with a synthetic test fixture, not rely on live data. **(2) `fourier-duality`'s registry
count (52) and corpus `paper_count` (51) already legitimately diverge by one** (a
registry-ahead-of-corpus gap noted independently in `source-truth-m2`'s brief-2 grounding —
the 52nd registered paper has no chunks yet). The manifest must report registry-derived and
corpus-derived counts as **separate fields**, never reconciled or asserted-equal — a one-off
drift between two independently-sourced stores is expected, not an error condition.

Also confirmed independently (matches brief-1 and the memory-file lesson from this same
milestone): the roadmap's `links.code: ["server/resources.py", ...]` for source-truth-m3 is
**stale** — `server/resources.py` is the unrelated `Resources` process-lifecycle dataclass
(E06_S01, BGE-M3/LanceDB/reranker singletons). The actual extension point is
`server/mcp_resources.py::register_resources()`, verified by reading both modules' docstrings
directly.

---

## 1. Manifest schema

### 1.1 Resource identity

One **concrete** resource (not a template — no `{slug}`, unlike the per-notebook detail
resource), mirroring `NOTEBOOKS_INDEX_URI`'s shape:

```python
CORPUS_MANIFEST_URI = "arxmcp://corpus-manifest"
```

Registered via a third `@mcp_server.resource(...)`-decorated function inside (or called from)
`register_resources()` in `server/mcp_resources.py`, wired at the same `server/main.py:849`
call site, subject to the identical "after `register_all_tools`, before `mount_mcp`"
snapshot-at-mount constraint the two existing resources already satisfy. `mime_type="text/plain"`
(matches the existing two — the body is a wrapped string, not structured JSON-RPC content).

### 1.2 Top-level JSON shape

```json
{
  "manifest_version": 1,
  "generated_at": "2026-07-13T23:10:00Z",
  "content_hash": "<64-hex sha256>",
  "snapshot": {
    "notebooks": {
      "<slug>": { "...": "see §1.3" }
    }
  }
}
```

**The hash boundary is structural, not convention-based.** `content_hash` is computed over the
canonical JSON of `snapshot` **alone** — not the whole payload. This is the key design choice
that makes re-verification unambiguous: a client extracts `payload["snapshot"]`, canonicalizes
it, hashes it, and compares. There is no "exclude these three keys by name" convention to get
wrong. Three fields sit deliberately **outside** the hash boundary because they are read-time
or wire-format metadata, not corpus content:

- `content_hash` itself (self-referential — must be added *after* hashing).
- `generated_at` — a wall-clock read-time stamp. If included in the hash, `content_hash` would
  change on every single read even when nothing in the registry/corpus changed, defeating
  "content-addressed" (the hash should be stable across repeated reads of unchanged data).
- `manifest_version` — the wire-format schema version. A server code deploy that bumps this
  (a richer JSON shape) should not, by itself, look like a corpus content change.

Everything inside `snapshot` (including the per-notebook `override` block — an operator policy
decision IS part of the asserted servable-state truth) **is** hashed.

### 1.3 Per-notebook block

Keyed by slug inside `snapshot.notebooks`. Enumerated from `NotebooksStore.list_notebooks()`
(the same store already wired at `server/mcp_resources.py`'s module level) — **every**
notebook appears, regardless of `notebook_kind` (arxiv/textbook) or registry-hydration state;
there is no filtering by kind. This mirrors the existing `arxmcp://notebooks` index's
complete-enumeration behavior and avoids a second, divergent "which notebooks count" policy.

```json
{
  "corpus_version": 4458,
  "chunker_version": "v1.1",
  "embedder_version": "bge-m3@5617a9f6",
  "corpus_created_at": "2026-07-13T18:41:28Z",
  "paper_count": 145,
  "chunk_count": 15106,
  "registry_present": true,
  "registry_error": null,
  "license_summary": {
    "eligible": 25,
    "not-allowlisted-open": 106,
    "unknown": 14,
    "total": 145
  },
  "id_shape": {
    "new_style": 130,
    "old_style": 15,
    "versioned": 0
  },
  "revisions_digest": {
    "count_total": 145,
    "count_active": 145,
    "count_withdrawn": 0,
    "count_superseded": 0,
    "rollup_sha256": "<64-hex>",
    "active_rollup_sha256": "<64-hex>"
  },
  "revisions": [ "... see §1.4, one entry per registered (work_id, arxiv_version) ..." ],
  "override": {
    "license_unknown_escalation_override": false,
    "set_by": null,
    "set_at": null,
    "note": null
  }
}
```

**Abstention invariant:** `corpus_version` / `chunker_version` / `embedder_version` /
`corpus_created_at` / `paper_count` / `chunk_count` are populated **together or not at all** —
they all come from one `read_corpus_version(notebook_lancedb_path(slug))` call, which returns
either a fully-populated `CorpusVersionInfo` or `None` (cold-start: the notebook exists but was
never ingested). On `None`, all six fields are `null` — never a partial mix.

**Registry-absent invariant:** when `var/arxmcp/notebooks/<slug>/documents.db` does not exist
on disk (today: `bridgeland-stability-pdfs`, `fourier-duality-pdfs`, `demo-nb`, and any future
un-backfilled or textbook-kind notebook), the block sets `registry_present: false` and
`license_summary` / `id_shape` / `revisions_digest` / `revisions` / `override` are all omitted
entirely (not present as empty/null placeholders — their absence *is* the signal, matching
`tools/documents_coverage_report.py::_load_stats`'s existing `present=False` short-circuit,
which deliberately never calls `DocumentsStore.open()` on a missing file to avoid the
open-creates-the-file side effect on what should be a pure read). `corpus_version` and its
siblings are still reported if the notebook happens to be ingested despite lacking a registry
(the two data sources are independent, per the drift note above).

**Per-notebook failure isolation:** a corrupt/mid-write-crashed `documents.db` (file exists but
`sqlite3.DatabaseError: file is not a database` on first query) must degrade **that one
notebook** to `registry_present: false, registry_error: "<short reason>"` — it must never raise
and fail the entire `resources/read` call. This mirrors the existing precedent in
`_notebook_metadata()` (`server/mcp_resources.py:110-123`), which catches a `NotebookError` from
the symlink-containment check and degrades to `is_ingested=False` rather than propagating. Wrap
each per-notebook block's assembly in its own `try/except (sqlite3.DatabaseError, OSError,
ValueError)`.

**Deliberately omitted from the per-notebook block:** `display_name` (operator-facing naming
already lives on `arxmcp://notebooks`; the manifest is a provenance/hash artifact, not a
directory) and any raw `license_uri` (kept only as the derived `license_status` — see §1.4).
Both omissions are also a security property: they shrink the set of operator/external-authored
freeform strings flowing through this resource to exactly one field, `override.note` (§4).

### 1.4 Per-revision entry

```json
{
  "work_id": "0705.3794",
  "arxiv_version": "",
  "raw_source_sha256": "8178b7bfe757f2809d68312644cd0c5da1164c1fcebaac4a3d009c7996b2cff7",
  "raw_source_status": "present",
  "parse_artifact_sha256": "b49e27087f71b588c7ff7d49933af968e1d2037d93d64d03fb2d6db346115de6",
  "license_status": "unknown",
  "status": "active",
  "invalidated": false,
  "invalidation_reason": null
}
```

**Explicit allowlist-by-projection** (mirrors the `_notebook_metadata()` m4-rect-F4
discipline): only the fields AC1 (checksums) and AC2 (invalidation) actually need cross the
boundary. `chunker_version` / `parser_used` / `latexml_version` / `fetched_at` / `license_uri`
from the underlying `DocumentRecord` are **not** repeated per-row — `chunker_version` is
already reported once per notebook (§1.3), and the other four are registration-internal
provenance with no AC1/AC2 role. This keeps the payload lean across hundreds of rows and, per
the security note above, keeps `license_uri` (an externally-sourced arXiv OAI-PMH string) out
of the response entirely — only the closed-vocabulary `license_status` derived value ships.

**Ordering is load-bearing for hash determinism.** `revisions` is a JSON *array*; `sort_keys`
only orders object keys, never array elements. The list MUST be sorted by `(work_id,
arxiv_version)` before serialization. `DocumentsStore.all_records()` already returns rows in
this order (`ORDER BY work_id, arxiv_version` — `server/documents_store.py:320`), so this falls
out for free *if* that method is the data source; state the dependency explicitly rather than
relying on incidental DB ordering silently continuing to hold.

**`invalidated` / `invalidation_reason`** are pure derived fields:
`invalidated = (status != "active")`; `invalidation_reason = status if invalidated else null`
(i.e. literally `"withdrawn"` or `"superseded"`, never a separate vocabulary). See §2.

### 1.5 Full per-revision list vs. a rollup-only digest — decision

**Decision: ship the full per-revision list, plus a rollup digest (§1.6) alongside it.** This
is not a coin-flip — it is substantially forced by AC1's own wording:

> "checksums re-verify on a clean re-fetch of 3 sample papers"

A client cannot re-verify a *specific paper's* checksum against a single rolled-up hash — there
is no value to compare against without the manifest exposing the actual per-paper
`parse_artifact_sha256` / `raw_source_sha256` strings. A rollup-only manifest would fail AC1 as
written; it can only ever prove "something changed somewhere," never "paper X's checksum is
exactly Y." The full list is therefore the primary artifact.

The full list is also **practical at today's scale**: 145 + 52 = 197 revisions total across the
two live notebooks, each row ~200-300 bytes of canonical JSON → the whole manifest resolves
comfortably under a few hundred KB. This is well inside a normal `resources/read` response
budget and orders of magnitude below anything requiring pagination.

The rollup digest is added **in addition**, not instead, for two reasons the full list doesn't
serve on its own: (a) a cheap equality/drift check without re-hashing hundreds of rows client
side, and (b) a short, stable string R4/R5 downstream artifacts can embed in a receipt/
attestation instead of inlining the whole per-revision list (per `R1-source-truth.md:54-57`:
"downstream artifacts... reference the manifest hash, not the epoch alone").

**Scale ceiling, flagged not solved:** if the corpus ever grows toward E11's full-corpus
ambition (~200K papers, CLAUDE.md §3), a full per-revision list on every read stops being
practical (tens of MB, most of it unread). That threshold is nowhere near today's 197-revision
reality and is out of scope for this milestone to solve — see §9 risk 2.

### 1.6 Rollup digest algorithm (the "Merkle-ish" digest)

Not a real Merkle tree (nothing here consumes an inclusion proof) — a flat, sorted,
canonical-JSON digest over positional arrays (no dict keys inside each row, so there is no
key-ordering question to get wrong):

```python
def _revision_key(r: DocumentRecord) -> list:
    return [r.work_id, r.arxiv_version, r.parse_artifact_sha256,
            r.raw_source_sha256, r.license_status, r.status]

def rollup_sha256(records: list[DocumentRecord]) -> str:
    rows = sorted(records, key=lambda r: (r.work_id, r.arxiv_version))
    canonical = json.dumps(
        [_revision_key(r) for r in rows],
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

`revisions_digest.rollup_sha256` = `rollup_sha256(all_records)`.
`revisions_digest.active_rollup_sha256` = `rollup_sha256([r for r in all_records if r.status ==
DOCUMENT_STATUS_ACTIVE])`.

Both `license_status` and `status` (not just the two checksums) feed the key — a license
re-decision (e.g. `unknown` → `eligible` after a re-hydration) or a status flip
(`active` → `withdrawn`) is exactly the kind of provenance change downstream consumers pinning
to this hash need to see, not just raw byte changes.

**Free regression-test invariant:** when a notebook has zero invalidated revisions (true for
*both* live notebooks today — see the grounding table), `rollup_sha256` and
`active_rollup_sha256` must be byte-identical, since the active-filtered list and the full list
are then the same set. That equality is directly assertable against live data without any
synthetic fixture; the *inequality* case (a withdrawn row present) requires one, since no
production row exercises it yet (§ grounding note 1).

### 1.7 Content-hash definition (formal)

```python
def compute_manifest_hash(snapshot: dict) -> str:
    canonical = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

snapshot = {"notebooks": {...}}          # built WITHOUT a content_hash key anywhere inside
digest = compute_manifest_hash(snapshot)
payload = {
    "manifest_version": 1,
    "generated_at": _utc_iso(),
    "content_hash": digest,
    "snapshot": snapshot,
}
```

This `sort_keys=True, separators=(",", ":"), ensure_ascii=True` convention is not invented for
this milestone — it is the **exact** canonicalization `tests/test_server_tool_schema.py`'s
`_serialize_tools()` already uses to compute `EXPECTED_TOOL_SCHEMA_SHA256`
(`tests/test_server_tool_schema.py:177-179`). Reusing it verbatim means the manifest's
content-hash inherits an already-adjudicated, already-cross-platform-tested canonicalization
rather than establishing a second, potentially-divergent one.

**This is a separate serialization pass from the outer wire envelope.** `_wrap_json()`
(`server/mcp_resources.py:87-90`) serializes the *whole returned payload* with
`ensure_ascii=False` for transmission — that pass is unrelated to, and need not match, the
canonicalization used to compute `content_hash` over `snapshot` alone. Do not conflate the two;
`content_hash` is fixed the moment `snapshot` is fixed, regardless of how the outer envelope is
later encoded for the wire.

---

## 2. Invalidation semantics (AC2)

**"Invalidated" means exactly this, for a read-only manifest resource, and nothing more:**

1. Every `revisions` entry whose registry `status` is `withdrawn` or `superseded` (read
   verbatim from `DocumentRecord.status` — never re-derived or inferred) carries
   `invalidated: true` and `invalidation_reason` set to that same status string.
2. That entry is **excluded** from `active_rollup_sha256` (§1.6) but **retained** in the full
   `revisions` list, `rollup_sha256`, and `count_total`. Nothing is ever deleted, hidden, or
   omitted from the audit-complete view — "edges only" means the manifest adds a machine-
   readable flag to an existing row; it does not trigger any corpus mutation, does not call any
   delete/purge path, and does not touch `chunks.lance` or the Kùzu graph.
3. `count_withdrawn` / `count_superseded` are reported as separate counters (not folded into one
   "invalidated" bucket) so an operator can distinguish an arXiv-side withdrawal (has a real
   extraction signal today — `<header status="deleted">`) from a supersession (no extraction
   signal exists anywhere in this repo yet; `DOCUMENT_STATUS_SUPERSEDED` is a reserved value
   `source-truth-m1` never writes — `server/documents_store.py:85-94`). Expect
   `count_superseded == 0` in every live read until a future milestone adds the extraction
   path; the field exists now for forward compatibility, not because current data exercises it.

**Scope decision, resolving sibling brief-1's Open Question 3 explicitly:** "edges" here means
a JSON field on the existing per-revision entry (interpretation (a) in brief-1's framing) —
**not** a new KùzuDB `REL TABLE` for withdrawal/supersession relationships (interpretation
(b)). Confirmed by checking `ingest/kuzudb_schema.py`: exactly one rel table exists (`cites`);
nothing for withdrawal/supersession exists or is planned by any milestone this brief could find
evidence of. A graph-relationship model is a materially larger, differently-scoped, and
differently-owned piece of work than an S-sized, resources-surface-only milestone that depends
on nothing but `source-truth-m1` (no graph-schema dependency in `plans/source-truth/
roadmap.yaml`'s `source-truth-m3` entry). If a future milestone wants withdrawal/supersession
as first-class graph edges, it is free to consume this manifest's `invalidated`/
`invalidation_reason` fields as its own data source — this design does not foreclose that, it
just doesn't build it.

**No live data exercises this path today.** Both notebooks show `status={"active": N}` only
(grounding table, §0). The implementer needs a synthetic fixture — direct
`DocumentsStore.upsert_records([...])` with a `status=DOCUMENT_STATUS_WITHDRAWN` row in a test —
to exercise AC2's invalidation behavior; a live-corpus-only test suite would pass by vacuous
truth (0 invalidated rows) without ever proving the `invalidated`/`active_rollup_sha256`
exclusion logic actually works.

---

## 3. Content-addressing + re-verify recipe (AC1)

**Resolving sibling brief-1's Open Question 4:** AC1's "clean re-fetch of 3 sample papers"
does **not** mean a live network round-trip to arXiv. Every fetch-capable tool in this family
(`tools/notebook_documents_backfill.py`, `tools/oai_license.py`) treats *avoiding* re-fetch as
a tested invariant (idempotent re-runs, zero requests on an already-registered id) — a test
that deliberately re-hits arXiv on every `make test` run would violate that norm and introduce
network flakiness into the default suite. "Re-fetch" is used loosely for "recompute
independently of the stored value, from the on-disk artifact that is the actual source of
truth" — i.e. do not trust the SQLite row; recompute from `parsed/<id>/index.html` (and
`raw/<id>/` when present) and assert equality.

**Concrete recipe, reusing the exact functions that produced the stored values (do not
reinvent):**

```python
# tools/notebook_documents_backfill.py:124-171 — the ONLY correct source for these two hashes.
_hash_raw_source_tree(CORPUS_RAW_DIR / work_id)        # -> str | None
_parse_artifact_sha256(work_id, CORPUS_PARSED_DIR)     # -> str | None
```

1. Pick 3 `(work_id, arxiv_version)` entries from a hydrated notebook's manifest `revisions`
   list (any hydrated notebook qualifies; a mixed sample — one `raw_source_status="present"`
   and one `"unavailable"` — exercises the abstention path too, but is not required).
2. For each, call `_parse_artifact_sha256(work_id, CORPUS_PARSED_DIR)` fresh and assert it
   equals the manifest's `parse_artifact_sha256` for that entry — always possible,
   `parse_artifact_sha256` is required non-null for every registered row.
3. When `raw_source_status == "present"`, additionally call
   `_hash_raw_source_tree(CORPUS_RAW_DIR / work_id)` fresh and assert equality with
   `raw_source_sha256`. Skip this half when `raw_source_status == "unavailable"` (the
   old-style abstention case — `raw_source_sha256` is `null` by design, nothing to re-verify).
4. Re-reading the manifest a second time with no underlying change must reproduce the identical
   `content_hash` and identical per-notebook `rollup_sha256` / `active_rollup_sha256` —
   stability across reads is itself part of what "content-addressed" promises and should be a
   named test, not just implied by the hash function being pure.

---

## 4. Operator override flag

**Storage — decided.** Reuse `server/operator_settings.py`'s existing flat SQLite key-value
store (`operator_settings` table, `var/arxmcp/cache/notebooks.db` — already durable, already
has a tested async class API for server callers and a sync API for CLI tools, already
explicitly anticipates "future keys" in its own docstring). **Zero schema migration required** —
this is exactly why it is the right home, versus a new `notebooks` table column (would force a
`NotebooksStore.SCHEMA_VERSION` bump, currently at 5) or a new per-notebook file (a second
storage mechanism to maintain for one boolean).

**Key format:** `f"license_unknown_override_{slug}"` (e.g.
`license_unknown_override_bridgeland-stability`). Single-underscore delimiter is unambiguous
because `SLUG_RE` (`^[a-z][a-z0-9-]{2,30}$`) never permits underscores inside a slug — no
reverse-parsing of the key is ever needed since the manifest always constructs it from an
already-known, already-validated slug.

**Value shape:** a JSON string (the store's `value` column is `TEXT`):

```json
{"enabled": true, "set_by": "chris.dare@nalej.com", "set_at": "2026-07-20T10:00:00Z",
 "note": "accepted bridgeland-stability's unknown rate pending re-hydration"}
```

**Default: absent key = disabled.** `enabled=false, set_by=null, set_at=null, note=null` when
the key has never been set — default-off per the task's own instruction, and consistent with
every other fail-closed default in this track.

**Fail-safe malformed-value handling:** if the stored value is present but fails
`json.loads` or is missing the `enabled` boolean, the manifest generator MUST treat it exactly
as absent (log a WARNING naming the slug, never raise, never crash the read) — a corrupt
override record must degrade to the *safe* state (no override), matching this track's existing
"a defect never silently grants a permissive outcome" posture (the license-decision function
`decide_license_status` uses the identical any-parse-doubt-falls-to-`unknown` shape).

**Read path:** the manifest generator opens a short-lived `OperatorSettingsStore` connection
per `resources/read` call (`await OperatorSettingsStore.open()` → `.get(key)` → `.close()`),
mirroring `tools/documents_coverage_report.py::_load_stats`'s open-read-close-per-call pattern
rather than adding new lifespan-level module wiring — `resources/read` is not a hot path (unlike
`search_papers`), so a fresh SQLite connection per read is acceptable and keeps the manifest
generator free of new server-startup plumbing.

**Set path — decided at the storage-mechanism level, left open at the UX level (§9 risk 1).**
An operator can set the flag today with zero new code via the already-public, already-tested
`server.operator_settings.set_setting(key, json.dumps({...}))` (sync) or
`OperatorSettingsStore.set(key, ...)` (async) — this alone satisfies "the manifest RECORDS it"
for m3. Whether m3 additionally ships a thin CLI convenience wrapper (mirroring
`tools/notebook_init.py`'s flag-setting precedent) or defers that operator-facing UX to m4 (the
milestone that actually gates serving on it) is flagged, not decided, in §9.

**Explicitly not m3's job:** the flag's *effect* on serving or on
`tools/documents_coverage_report.py`'s exit-code escalation gate. m3 only records and surfaces
the current value; consuming it to change behavior is m4's owner-gated cutover work (per the
milestone brief: "the manifest RECORDS it, doesn't gate serving").

---

## 5. Boundary and AC checks

**Read-only, verified by enumeration.** The manifest generator's only calls are: `NotebooksStore
.list_notebooks()` (already open, server-lifespan-wired), `DocumentsStore.open()` /
`.all_records()` / `.close()` per notebook (guarded by a file-existence check first — see §1.3
registry-absent invariant — so a `resources/read` never *creates* an empty `documents.db` as a
side effect), `read_corpus_version(...)` (a pure file read, raises only on
present-but-malformed, returns `None` on absent), and `OperatorSettingsStore.open()` / `.get()`
/ `.close()` per notebook. **No write call appears anywhere in this path** — no `upsert_records`,
no `set_setting`/`.set()`, no LanceDB write, no Kùzu write.

**Not a single atomic transaction, by design — an accepted, pre-existing pattern.** The
per-notebook block composes three independently-read data sources (LanceDB marker file, a
SQLite registry, a SQLite settings store) at request time with no cross-store transaction. A
registry backfill running concurrently with a manifest read could in principle observe a torn
view (e.g. `corpus_version` bumped between two of the three reads). This mirrors the existing
lack of cross-store transactions elsewhere in the codebase (`NotebooksStore` and
`DocumentsStore` are already independent files with no shared transaction) and is not a new gap
this milestone introduces.

**`EXPECTED_TOOL_SCHEMA_SHA256` stays unchanged — mechanically, not by discipline.**
`resources/list` / `resources/read` are a separate JSON-RPC method from `tools/list`
(`mcp.list_resources()` vs `mcp.list_tools()`); a resource registered via `@mcp_server.resource
(...)` never enters `tools/list`'s serialization. `TOOL_SCHEMA_VERSION` (currently `18`)
requires **zero** change for this milestone. This is already proven generically by
`tests/test_mcp_resources.py::TestByteStability` for the two existing resources
(`test_tools_list_hash_unchanged_with_resources`, `test_resources_do_not_change_tools_vs_
baseline`, `test_resources_add_no_tools` — asserts exactly 8 tools). No existing test will
auto-catch a *manifest*-resource regression specifically, though — extend that class (or add a
sibling assertion) with the manifest resource registered, so the invariant is pinned for three
resources, not silently assumed to generalize from two.

**§4.9 3-way vocabulary.** `license_summary` uses `eligible` / `not-allowlisted-open` /
`unknown` verbatim (imported from `tools.oai_license`'s constants, never re-typed as string
literals) with an explicit `total`. `unknown` is never added into `not-allowlisted-open` or
vice versa anywhere in the manifest — the same discipline `documents_coverage_report.py`
already enforces for its owner-escalation gate.

**`wrap_retrieved_text`'s silent-fallback landmine — must be fixed, not just called correctly.**
`server/tools.py:574-577` dispatches `kind` through a **closed** dict: `{"equation": ...,
"notebook": ...}.get(kind, _WRAP_TAG_CHUNK)`. Any `kind` value not already in that dict —
including a naive `kind="manifest"` — silently falls back to `<retrieved_chunk>` wrapping
instead of raising or producing a distinct tag. The implementer MUST add
`_WRAP_TAG_MANIFEST = "retrieved_manifest"` **and** a `"manifest": _WRAP_TAG_MANIFEST` dict
entry in `server/tools.py` *before* the manifest resource calls
`wrap_retrieved_text(text, kind="manifest")` — otherwise the manifest payload silently mislabels
itself as chunk content, which is both semantically wrong and a bad precedent (an agent's
system-prompt guidance may treat `<retrieved_chunk>` differently from a provenance/manifest
payload). This is the one place in this design where "call the existing helper" is not enough
without a small, one-line addition to that helper's dispatch table.

**Minimized injection surface, verified against the schema in §1.** The only operator-authored
freeform string anywhere in the manifest is `override.note` (§4) — every other field is a
closed-vocabulary enum (`license_status`, `status`, `raw_source_status`), an integer, a
hex-string checksum, or an ISO-8601 timestamp. `license_uri` and `display_name` are both
deliberately excluded (§1.3/§1.4). `override.note` alone needs the
`TestIndirectPromptInjection`-style delimiter-breakout test the existing notebook-resource test
suite already exercises for `display_name` (`tests/test_mcp_resources.py`) — the manifest's
attack surface is one field, not the whole payload.

---

## 6. No go-live / no backfill

The manifest has **no independent persisted storage** — no `manifest.json` on disk, no cron, no
build step, no `tools/notebook_manifest_backfill.py`. Every `resources/read` regenerates the
snapshot from the three already-live sources (`NotebooksStore`, per-notebook `DocumentsStore`,
per-notebook `corpus-version.json`, per-notebook `OperatorSettingsStore` entry) at request time.
Unlike `source-truth-m1`/`m2`, there is nothing to backfill and therefore **no owner-gated
go-live checkpoint for m3** — the resource either resolves correctly against whatever registry
state currently exists, or (for an un-hydrated notebook) reports `registry_present: false`, on
day one. `source-truth-m4`'s owner-gated cutover is a separate, later concern that consumes this
resource's output; it does not gate this milestone's shipping.

---

## 7. Recommended file layout (non-binding — implementer's call on exact module boundaries)

- **New module, `server/corpus_manifest.py`** — pure, FastMCP-independent logic:
  `async def build_manifest(notebooks_store, *, base=None) -> dict` (returns the full payload
  dict, hash already computed), plus separately-unit-testable `compute_manifest_hash(snapshot)`
  and `rollup_sha256(records)` functions. Mirrors the existing separation where
  `_notebook_metadata()` is a plain async function that `mcp_resources.py` only wraps with
  `@mcp_server.resource`.
- **`server/mcp_resources.py`** gains a third resource registration whose callback calls
  `corpus_manifest.build_manifest(_require_store())` and wraps the result with
  `wrap_retrieved_text(text, kind="manifest")`.
- No new lifespan wiring is required beyond what already exists — the manifest generator reuses
  the already-wired `_notebooks_store` module reference and opens its own short-lived
  `DocumentsStore` / `OperatorSettingsStore` connections per read (§4, §5).

This keeps `mcp_resources.py` as thin FastMCP registration glue (its documented role) and keeps
the manifest's hashing/aggregation logic independently testable without spinning up FastMCP,
matching this repo's existing file-per-concern convention (`documents_store.py` vs
`notebook_documents_backfill.py` vs `documents_coverage_report.py` are already three separate
files for three separate concerns over the same registry).

---

## 8. Resolution of sibling brief-1's open questions

| Brief-1 OQ | Resolution in this brief |
|---|---|
| OQ1 — roadmap's `server/resources.py` link is misleading | Confirmed independently (§0); `server/mcp_resources.py` is the real target. Not a design fork, just a documentation correction — no residual risk. |
| OQ2 — "content-addressed" is underspecified (dynamic hash, no existing precedent) | Resolved: §1.2/§1.7 — nested `snapshot` sub-object as the hash boundary, `generated_at`/`manifest_version`/`content_hash` excluded, canonicalization reuses `test_server_tool_schema.py`'s exact convention. |
| OQ3 — "edges only" ambiguous between a JSON field vs. a new Kùzu rel table | Resolved: §2 — a JSON field (interpretation (a)); no graph-schema change, confirmed no rel-table precedent or dependency exists for this milestone. |
| OQ4 — "clean re-fetch" vs. this repo's anti-re-fetch idempotency norms | Resolved: §3 — means on-disk re-hash via the exact existing functions, not a network round-trip. |
| OQ5 — degrade path for un-hydrated/partially-migrated notebooks | Resolved: §1.3 registry-absent invariant + per-notebook failure isolation. |

---

## Acceptance criteria the implementer must meet

1. **[AC1]** `resources/read` on `arxmcp://corpus-manifest` resolves to `{manifest_version,
   generated_at, content_hash, snapshot:{notebooks:{...}}}`; `content_hash` equals
   `sha256(canonical_json(snapshot))` using `sort_keys=True, separators=(",", ":"),
   ensure_ascii=True` (§1.7) — verified by an implementer test that recomputes the hash
   independently from the returned `snapshot` and asserts equality with the returned
   `content_hash`.
2. **[AC1]** For 3 sample papers drawn from a hydrated notebook's `revisions`, an independent
   on-disk recompute of `_parse_artifact_sha256` (always) and `_hash_raw_source_tree` (when
   `raw_source_status="present"`) via the exact functions in
   `tools/notebook_documents_backfill.py:124-171` matches the manifest's reported values — no
   network egress in the test (§3).
3. **[AC1]** Reading the manifest twice with no underlying change yields an identical
   `content_hash` and identical per-notebook `rollup_sha256`/`active_rollup_sha256` (stability).
4. **[AC2]** Every `revisions` entry carries `invalidated`/`invalidation_reason` derived from
   `status != "active"`; `active_rollup_sha256` excludes invalidated revisions while the full
   `revisions` list and `rollup_sha256` retain them (§2) — proven with a synthetic
   `DocumentsStore.upsert_records` fixture containing a `status="withdrawn"` row, since no live
   row exercises this today.
5. **[Boundary]** A `TestByteStability`-equivalent assertion (extending
   `tests/test_mcp_resources.py` or a sibling module) proves `EXPECTED_TOOL_SCHEMA_SHA256` and
   the 8-tool count are unchanged with the manifest resource registered — net-new, since the
   existing three tests only cover the two pre-existing resources.
6. **[§4.9]** `license_summary` reports the full 3-way vocabulary
   (`eligible`/`not-allowlisted-open`/`unknown`) with a `total`, imported from
   `tools.oai_license`'s constants (never re-typed as literals); `unknown` is never folded with
   `not-allowlisted-open` anywhere in the manifest or its aggregation code.
7. **[Operator override]** `override.license_unknown_escalation_override` defaults to `false`
   for an absent key AND for a malformed stored value (invalid JSON or missing `enabled`) — the
   manifest read path never calls `set_setting`/`OperatorSettingsStore.set` under any input.

---

## Risks and open questions

1. **Override-flag SET UX is a genuine open call, not resolved here.** §4 decides the storage
   mechanism (`operator_settings`, namespaced key, JSON value) and the read path fully, but
   leaves open whether m3 ships a thin CLI wrapper (`tools/notebook_set_license_override.py`,
   mirroring `notebook_init.py`'s flag precedent) now, or defers all operator-facing UX
   (CLI flag vs. a future `/ui` toggle) to m4, which is where the flag starts mattering for
   actual serving/escalation behavior. Either is defensible; the owner's call is really "how
   much UX polish belongs in an S-sized resources-only milestone."
2. **Full-per-revision-list scale ceiling is flagged, not solved.** §1.5's decision is correct
   at today's 197-revision reality and is *forced* by AC1's literal wording, but if the corpus
   ever grows toward CLAUDE.md §3's E11 full-corpus ambition (~200K papers), unconditionally
   returning every revision on every read stops being practical. No threshold or fallback shape
   (rollup-primary + truncated sample?) is decided here — revisit only once corpus scale
   actually approaches it; premature design here would be speculative.
3. **Textbook / non-arXiv notebooks have no parallel provenance registry at all.** `documents.db`
   is OAI-PMH-hydrated and arXiv-specific; a `notebook_kind="textbook"` notebook (or the MinerU
   `-pdfs`-suffixed notebooks) will permanently show `registry_present: false` under this
   design, which is a correct abstention today but has no forward path once/if a
   textbook-specific provenance source exists — out of scope for whoever designs that.
4. **The per-notebook failure-isolation behavior (§1.3, §5) needs its own explicit test**, not
   just implied correctness — a corrupt `documents.db` degrading one notebook rather than
   failing the whole `resources/read` is a much better failure mode for downstream agents and
   should be asserted directly (e.g. a fixture with a truncated/non-SQLite file at the
   `documents.db` path), since nothing in the existing test suite exercises this shape.
5. **Whether `tools/documents_coverage_report.py`'s exit-code escalation gate should start
   consulting the override flag is explicitly deferred to m4**, per the milestone brief's own
   "records, doesn't gate" framing (§4) — but `source-truth-m4`'s roadmap text ("record the
   per-notebook operator override flag in the manifest alongside a published coverage report")
   reads as if that wiring is expected there. Flagging so m4's own research phase does not
   discover this as a surprise gap: the coverage-report/override integration is unbuilt by m3
   and is m4's to design, not silently assumed already-done because the manifest exists.
