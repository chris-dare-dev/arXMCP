# Research Brief — proof-verify-handler-wiring-m1

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-21T05:30:00Z

---

## In-codebase context

### What the handler currently does (search.py lines 217-265)

The ANN call at `server/handlers/search.py:221-225`:
```python
arrow = (
    r.chunks_table.search(query_vec, vector_column_name="embedding_stmt")
    .limit(k * 5 if level != "theorem" else k)
    .to_arrow()
)
```
No `.where()` is chained. Then lines 243-248 emit a `filter_warnings` entry
when `filters` is truthy:
```python
if filters:
    filter_warnings.append(
        "filters arg is accepted but not yet processed (deferred to E07_S04)"
    )
```
The cache at line 168 already passes `filters=filters` to `lookup_search` and
at line 279 to `store_search`. The `derive_tier1_key` function in
`server/cache_sqlite.py:103-141` includes filters in the hash via
`canonical_key_components`, which uses `json.dumps(filters or {}, sort_keys=True)`.
**The cache key already accounts for filters correctly** — a query with
`filters={"paper_id":["a"]}` already produces a different Tier-1 key than the
same query with `filters=None`.

**Tier-2 also already handles filters** via `_filter_fingerprint` in
`server/cache.py:127-163`, which feeds through the same `canonical_key_components`
helper. There is no cache-key work to do in m1 beyond confirming no regression.

### Existing LanceDB `.where()` pattern in the codebase

Two production patterns establish the predicate API:

`ingest/intra_paper_refs.py:218-223` (the canonical IN-list pattern):
```python
labels_csv = ",".join(f"'{_escape_sql(label)}'" for label in sorted(candidate_labels))
paper_id_escaped = _escape_sql(paper_id)
where = (
    f"paper_id = '{paper_id_escaped}' "
    f"AND theorem_label IN ({labels_csv})"
)
```
where `_escape_sql` (line 253-255) is: `return value.replace("'", "''")`

`server/graph_queries.py:261-263` (the exact pattern m1 needs, on `paper_id IN`):
```python
ids_csv = ",".join(f"'{_escape_sql(pid)}'" for pid in sorted(paper_ids))
where = f"paper_id IN ({ids_csv}) AND kind IN ({kinds_csv})"
```
with its own `_escape_sql` at line 292-295: `return value.replace("'", "''")`

The spike-1 note at `.claude/notes/spikes/lancedb-ann-where-composition/note.md`
verifies: **`paper_id IN ('id1', 'id2', ...)`** is the correct predicate syntax
and it composes correctly with ANN `.search()`. The spike was validated against
39-paper notebook scale with a 5-paper filter.

### `is_valid_paper_id` and the security perimeter (Threat 1)

`ingest/identifiers.py:57-64` provides `is_valid_paper_id` with regex:
```python
_PAPER_ID_FULL_PATTERN = (
    r"^\d{4}\.\d{4,5}(v\d+)?$"
    r"|"
    r"^[a-z][a-z\-]*/\d{7}(v\d+)?$"
)
```
This regex allows only digits, dots, slashes, hyphens, and the literal `v` prefix.
**It structurally cannot match a single-quote character.** However, the defense
layer must still call `is_valid_paper_id` on every element of the list before
constructing any predicate string, per Threat 1 in `08-security-observability-ops.md`:
*"Reject at the JSON-Schema level so it never reaches handlers."* For a list value
this means explicit per-element validation in the handler body.

### `MAX_FILTER_ITEMS = 100` at search.py:97 is a DICT-ITEM cap, not a LIST-LENGTH cap

The existing guard at `server/handlers/search.py:133-137`:
```python
if filters is not None and len(filters) > MAX_FILTER_ITEMS:
    raise ValueError(...)
```
checks `len(filters)` — the number of keys in the dict. A `filters={"paper_id": [10_000_ids]}`
with one key passes this check with `len(filters) == 1`. **There is no existing
cap on the length of the paper_id list value.** m1 must introduce one.

### Cache behavior on server upgrade (existing entries)

The cache key already includes `filters` (implemented). Existing cached entries
from before m1 have `filters=None` or `filters={}` in their key. After m1 ships,
a call with `filters={"paper_id":["x"]}` hashes differently and gets a cache miss
(correct behavior — the result set is scoped). Entries cached WITHOUT filters
remain valid and unaffected. **There is no cache invalidation on upgrade.**
The `corpus_version` component ensures stale corpus entries are already separated;
filter-keyed entries simply never existed before m1.

Design note `07-multi-agent-caching.md`: *"Cache layer crash / OOM → Fall through
to recompute; log; alert. Caching is performance, not correctness."*

### `paper_id` column is `pa.utf8()` in the schema

`ingest/schema.py:85`: `pa.field("paper_id", pa.utf8(), nullable=False)`. PyArrow
does not validate content during writes; the column accepts any UTF-8 string.
There is no pyarrow-side injection defense. The predicate builder is the sole
escape layer.

### Tool schema is NOT changing

The `filters: dict[str, Any] | None` parameter already exists in the handler
signature with its `Field(description=...)`. m1 adds validation LOGIC in the
handler body, not a new Pydantic constraint. **EXPECTED_TOOL_SCHEMA_SHA256 does
NOT need to be re-pinned** (per the `MAX_FILTER_ITEMS` precedent in the same
handler — that too was added as handler-body validation without schema changes).

### The 3-call session cap is orthogonal

`server/session.py:54`: `MAX_SEARCH_PAPERS_CALLS: int = 3`. The cap fires in
`SessionCapMiddleware` before the handler body runs, keyed on tool name. Filter
presence does not affect cap accounting.

---

## Failure-mode analysis (PRIMARY)

**FM-1: Predicate injection via malformed paper_id**

- **Trigger:** `filters={"paper_id": ["foo'; DROP TABLE chunks; --"]}` passed
  as tool argument.
- **Symptom without mitigation:** The predicate `paper_id IN ('foo'; DROP TABLE chunks; --')`
  is passed to LanceDB. LanceDB's SQL parser may execute the injected fragment
  or raise a parse error. In either case, attacker influences the predicate.
- **Mitigation (defense-in-depth):** (1) `is_valid_paper_id` regex structurally
  excludes `'`, `;`, `-`, and all non-arXiv characters. (2) Even if the regex
  were bypassed, `_escape_sql` (doubling single-quotes) would neutralize the
  single-quote injection vector. The codebase has both layers in `intra_paper_refs.py`
  and `graph_queries.py`; m1 must use both in the same order: validate first,
  escape always.
- **Risk level after mitigation:** LOW (regex makes this structurally impossible
  for well-formed paper IDs; escape is defense-in-depth).

**FM-2: Empty paper_id list treated as "no filter"**

- **Trigger:** `filters={"paper_id": []}` passed by the caller.
- **Symptom without mitigation:** The handler might treat the empty list as
  `filters=None` and return corpus-wide results — silently ignoring the caller's
  scoping intent. Alternatively, `paper_id IN ()` is invalid SQL and LanceDB
  raises a parse error.
- **Canonical handling:** `filters={"paper_id": []}` MUST raise a `ValueError`
  with a message distinguishing it from `filters=None` (no filter requested) and
  `filters={"paper_id": null}` (JSON null maps to Python None, same as key absent).
  The spec AC confirms: "a clear error is surfaced via the result envelope (not a 500)."
  Do NOT silently coerce to `filters=None`.

**FM-3: String instead of list for paper_id**

- **Trigger:** `filters={"paper_id": "2604.26204"}` (string, not list).
- **Symptom without mitigation:** `for pid in filters["paper_id"]` iterates
  over characters of the string rather than the string itself. The predicate
  becomes `paper_id IN ('2', '6', '0', '4', ...)` — wrong but not a security
  issue.
- **Mitigation:** Mirror `server/retrieval/bm25.py:683-687` (`_apply_supported_filters`):
  coerce `isinstance(paper_id_filter, str)` to `[paper_id_filter]`. This is the
  established project convention for this argument.

**FM-4: Oversized paper_id list (resource exhaustion)**

- **Trigger:** `filters={"paper_id": [<10_000_ids>]}` — passes the existing
  `MAX_FILTER_ITEMS=100` guard (that checks dict key count, not list length).
- **Symptom without mitigation:** A 10K-element `IN` clause constructs a ~120 KB
  predicate string on each call. LanceDB must parse it; the predicate is passed
  over IPC; it may be held in memory for the duration of the ANN call.
- **Mitigation:** Introduce `MAX_PAPER_ID_FILTER_ITEMS = 100` (matching the
  roadmap's stated budget of ~100 paper IDs per call per `plans/proof-verify-handler-wiring-roadmap.md:39`).
  Validate `len(paper_id_list) > MAX_PAPER_ID_FILTER_ITEMS` and raise `ValueError`
  in the handler body — NOT as a Pydantic constraint (to preserve schema
  byte-stability per BP1 discipline).
- **Threat model reference:** `08-security-observability-ops.md` Threat 4:
  *"An LLM in a retry loop can pass k=10000 and torch the rerank budget."*

**FM-5: All paper_ids invalid (malformed list)**

- **Trigger:** `filters={"paper_id": ["not-an-arxiv-id", "also-bad"]}` — no
  element passes `is_valid_paper_id`.
- **Symptom without mitigation:** Handler raises ValueError on ALL elements;
  or (if per-element rejection is silent) produces an empty predicate and an
  empty result set.
- **Canonical handling:** Raise `ValueError` with the count of rejected IDs when
  NO valid IDs remain. If SOME ids are invalid, raise ValueError — do not silently
  drop malformed IDs and proceed with a partial filter (that would be semantically
  surprising and hides LLM errors).
- **Note:** `is_valid_paper_id` in `ingest/identifiers.py` is the canonical
  validator; do NOT redefine the regex inline.

**FM-6: Cache key collision across filter sets**

- **Trigger:** Two queries with same `(query, k, level)` but different
  `filters` values calling `lookup_search`.
- **Status:** Already handled correctly. `derive_tier1_key` in `cache_sqlite.py:103`
  includes `filters` via `canonical_key_components:171`:
  `json.dumps(filters or {}, sort_keys=True, separators=(",", ":"))`. The Tier-2
  fingerprint uses the same helper via `_filter_fingerprint`. m1 requires no
  cache changes — **but this should be explicitly tested** with two same-query
  calls, one filtered and one unfiltered, asserting they produce distinct keys.

**FM-7: paper_ids not in corpus (non-existent filter)**

- **Trigger:** `filters={"paper_id": ["aaaa.bbbb"]}` where `aaaa.bbbb` passes
  `is_valid_paper_id` but does not exist in the chunks table.
- **Symptom:** LanceDB `.where("paper_id IN ('aaaa.bbbb')")` filters to zero
  matching rows; the ANN search returns an empty Arrow table. `_arrow_to_rows`
  produces an empty list. The handler returns `{"results": [], ...}` — correct
  behavior.
- **Risk:** The handler MUST NOT raise; empty result is the correct semantic.
  Verify `_arrow_to_rows` handles zero-row input (it does — the zip is over
  empty columns). No additional code change needed but a test assertion is needed.

**FM-8: `prefilter` vs post-filter behavior on ANN**

- **Trigger:** The spike uses the default (no `prefilter` kwarg). The existing
  ingest uses `prefilter=True`. For ANN search, the behavior differs:
  `prefilter=True` filters the candidate set BEFORE ANN (correct semantics);
  default (False or unspecified) may filter AFTER ANN retrieves candidates.
- **Risk:** Without `prefilter=True`, a `k=10` call with a 5-paper filter might
  retrieve 10 candidates from the corpus-wide ANN and then discard 8 of them
  because they're not in the filter set, returning only 2 results even though
  the filtered sub-corpus has plenty of matching chunks.
- **Mitigation:** Use `prefilter=True` in the `.where()` call, consistent with
  `ingest/index_theorem_names.py:132` and `ingest/intra_paper_refs.py:226`.
  The spike-1 note does not mention `prefilter` — the implementer must verify
  whether the spike used it implicitly and whether LanceDB defaults are stable.

**FM-9: `filter_warnings` removal creates regression for unhandled filter keys**

- **Trigger:** A caller passes `filters={"paper_id": ["x"], "year": 2024}`.
  m1 handles `paper_id` but not `year`. If the handler removes the filter_warnings
  message unconditionally, the caller has no visibility that `year` was silently
  ignored.
- **Canonical handling:** Remove the "deferred to E07_S04" warning ONLY for
  `paper_id` when it is honored. Keep (or add) a warning for any other key in the
  filter dict. The roadmap AC says remove the warning "when the filter IS honored"
  — not "when any filter is present."

---

## Prior decisions and lessons

**Git log (recent):**
`0555ea2 chore(notes): mark E13_S04b external writes as completed`
`874db28 feat(server,tests,docs): extend 256 KB byte cap to all tools (E13_S04b)`

The E13_S04b byte-cap work confirms the pattern: handler-body validation
preferred over Pydantic constraints when schema hash must not change.

**Memory — E13_S04 (from MEMORY.md):**
"Adding a Pydantic Field constraint would re-pin EXPECTED_TOOL_SCHEMA_SHA256 +
bump TOOL_SCHEMA_VERSION (BP1 cache cost). Use handler-body `raise ValueError`
instead."

**Spike-1 verdict (`.claude/notes/spikes/lancedb-ann-where-composition/note.md`):**
"YES — LanceDB's ANN search composes correctly with `.where('paper_id IN (...)')`."
Latency: 1.5ms filtered vs 50ms unfiltered (30× speedup — filter narrows ANN
search space).

**BM25Phase string-coercion convention (server/retrieval/bm25.py:683-687):**
Single `str` coerced to `frozenset({paper_id_filter})`. m1 must mirror this.

**`_escape_sql` is multiply-defined** across `ingest/intra_paper_refs.py:253`,
`server/graph_queries.py:292`, and implied in `server/handlers/paper.py`. The
implementer should define it locally in `server/handlers/search.py` rather than
importing from graph_queries.py (cross-module import from a handler to a
graph-query library is a smell). Alternatively, promote to `ingest/identifiers.py`
as a shared utility — but that is out of scope for m1.

---

## External sources

**LanceDB predicate syntax (verified via spike-1 note):** The SQL-ish predicate
language uses single-quoted string literals: `paper_id IN ('a', 'b')`. The
separator between `.search()` and `.limit()` is `.where(predicate_string)`.
The API accepts an optional `prefilter` boolean kwarg.

**No parameterized queries:** `ingest/index_definitions.py:404-405` documents:
*"LanceDB does not accept bound parameters for predicates today."* This means
string concatenation with manual escaping is the ONLY option — making the
`_escape_sql` single-quote doubling mandatory.

**PyArrow paper_id column:** `pa.utf8()` at `ingest/schema.py:85`. Arrow provides
no content-level validation; all safety is at the predicate construction layer.

**MCP spec (2025-06-18):** No relevant changes for this milestone — the tool
signature, result shape, and content block format are unchanged.

**Prompt caching docs:** Not relevant — no tool schema changes.

---

## Recommendation

Implement m1 as follows:

1. In `handle_search_papers`, after the existing `MAX_FILTER_ITEMS` guard,
   extract and validate the `paper_id` list: coerce `str` to `[str]`, reject
   empty list with `ValueError`, reject any element failing `is_valid_paper_id`
   with `ValueError`, cap list length at `MAX_PAPER_ID_FILTER_ITEMS = 100`.

2. Build the predicate: `ids_csv = ",".join(f"'{pid.replace(chr(39), chr(39)+chr(39))}'" for pid in sorted(valid_ids))` then `predicate = f"paper_id IN ({ids_csv})"`.

3. Chain `.where(predicate, prefilter=True)` between `.search(...)` and `.limit(...)`
   in the ANN call.

4. Remove the "deferred to E07_S04" filter_warning ONLY for paper_id; keep
   warnings for any other unhandled key.

5. Do NOT change any Pydantic schema decorators or tool metadata. Do NOT
   re-pin `EXPECTED_TOOL_SCHEMA_SHA256`.

This approach exactly mirrors the `server/graph_queries.py:261-263` pattern
(already in the server module) and the `ingest/intra_paper_refs.py:218-226`
pattern. No new dependencies. No cache changes needed (filters already in key).

---

## Open questions

1. **`prefilter=True` or default?** The spike-1 note does not record whether
   `prefilter=True` was used. The implementer must check the LanceDB Python API
   for whether the default for `.where()` on a vector search applies pre- or
   post-filter semantics. Based on existing ingest patterns, `prefilter=True`
   is the safe choice (guarantees results are within the filter set, avoids
   ANN returning k corpus-wide candidates and then discarding most).

2. **`MAX_PAPER_ID_FILTER_ITEMS` value:** 100 is consistent with the roadmap
   prose (`~100 ids per call comfortably`). No evidence for a tighter or looser
   cap. Implementer should use 100.

---

## External writes the implementation will require

None — this milestone is purely local. All changes are in `server/handlers/search.py`
and `tests/`. No git push, no PR, no infra mutation, no third-party API calls.
