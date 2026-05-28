# Research Brief — notebook-retrieval-m2

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-28T06:10:00Z

## In-codebase context

### Confirmed: filters is free-form dict — X-1/X-2 UNCHANGED

`server/handlers/search.py:344-355` (verbatim):

```python
filters: Annotated[
    dict[str, Any] | None,
    Field(
        description=(
            "Optional filters. Honors 'paper_id' as a str or "
            "list[str] (up to 100 items, each validated against "
            "the arXiv paper_id format) and 'source_kind' "
            "('arxiv' or 'textbook'); these compose (AND). Other "
            "keys are ignored and surface in 'filter_warnings'."
        ),
    ),
] = None,
```

`filters` is `dict[str, Any] | None`. Adding a `notebook` key to the dict adds NO new
parameter to the JSON Schema `inputSchema` — the schema advertises `filters` as a single
`object | null`. X-1 (`EXPECTED_TOOL_SCHEMA_SHA256`) and X-2 (`EXPECTED_BP1_SHA256`) are
genuinely unchanged. Confirmed.

### Tier-1 key construction — the slug-injection seam

`server/cache_sqlite.py:144-187` (`canonical_key_components`): the key is length-prefixed
bytes of `(canonical_query, filters_json, k, corpus_version, level_token)`. Critically,
`filters_json = json.dumps(filters or {}, sort_keys=True, separators=(",", ":"))`. If the
caller passes `filters={"notebook": "bridgeland-stability", ...}`, the slug is already
baked into the `filters_json` component — **the slug IS in the key without any code
change**, as long as `notebook` is left in the filters dict when computing the cache key.

This is the load-bearing insight: the implementer MUST NOT strip `notebook` from `filters`
before the cache key derivation. The `_canonicalize_filters` function (`search.py:301-332`)
currently normalizes `paper_id` only; if a future version strips unknown keys before cache
lookup, the slug falls out of the key and AC3 regresses.

**AC7 reconciliation path:** m1's F1 fix routed `cache_db_path` to a per-notebook sibling
(`var/arxmcp/notebooks/<slug>/cache/retrieval.db`) for fork-C structural isolation. Fork A
serves many notebooks from one process — a single shared `cache_db_path` at
`var/arxmcp/cache/retrieval.db` is correct, with slug-in-key providing logical isolation.
The m1 per-notebook `cache_db_path` derivation activates only when `ARXMCP_NOTEBOOK` is
set; when it is not set (fork-A mode), `cache_db_path` defaults to the shared path.
These two mechanisms coexist without conflict as long as fork-C and fork-A are mutually
exclusive at the `cache_db_path` level — which they are today.

### `validate_slug` is the established guard

`tools/_notebook_common.py:58-76` (`validate_slug`): rejects anything not matching
`^[a-z][a-z0-9-]{2,30}$` with a `NotebookError`. `notebook_dir` (lines 79-123) adds a
symlink-rejection check and containment verification. `notebook_lancedb_path` (lines
126-147) wraps `notebook_dir`. This is already called at every existing notebook code
path. The m2 handler must call it at the `filters["notebook"]` extraction point.

### SUPPORTED_FILTER_KEYS two-copy sync pattern

`server/handlers/search.py:249`:
```python
SUPPORTED_FILTER_KEYS: frozenset[str] = frozenset({"paper_id", "source_kind"})
```
`server/retrieval/bm25.py:117` has a parallel `SUPPORTED_FILTER_KEYS`. Both must be
updated in lockstep if `"notebook"` is ever added to the supported set. However, `notebook`
is a routing key, not a retrieval filter — it should NOT appear in `SUPPORTED_FILTER_KEYS`
(it belongs to the routing layer, not the filter-application layer) and should NOT appear
in `filters_applied`. Stripping it before passing `filters` to LanceDB predicates is
correct; including it in the cache key is also correct (via `filters_json`). This dual
treatment (strip from predicate / keep in cache key) is the critical distinction.

---

## Failure-mode analysis (primary deliverable)

### FM-1: Cache-key byte-instability (AC4 regression) — slug=None injection

**Trigger:** Naive implementation strips `notebook` from `filters` for LanceDB predicate
building but also strips it from the dict passed to `derive_tier1_key`. The no-notebook
path then passes `filters=None` → `filters_json = "{}"` — identical to today. This
preserves AC4. The collision risk is the opposite case: the implementer forgets to strip
`notebook` from the dict going to LanceDB predicates and passes `{"notebook": "bridgeland-stability"}` as a literal `filters` WHERE clause.

**Byte-exact solution:** Extract slug = `filters.pop("notebook", None)` (or equivalent
shallow-copy strip) ONLY from the predicate-building path, NOT from the cache-key path.
Pass the ORIGINAL `filters` (including `notebook`) to `derive_tier1_key`. Pass `filters`
minus `notebook` to `_build_paper_id_predicate` and the LanceDB `.where()` builder.
`_canonicalize_filters` must NOT strip `notebook` — it must leave it intact so the
cache-key hash differs between notebook-A and notebook-B queries.

When `filters=None` (no notebook), the Tier-1 key is `sha256(q || "{}" || k || cv || lvl)`
— identical to today. When `filters={"notebook": "bridgeland-stability"}`, the key is
`sha256(q || '{"notebook":"bridgeland-stability"}' || k || cv || lvl)` — distinct. AC4
holds.

### FM-2: Tier-2 filter_fingerprint collision across notebooks

**Trigger:** `server/cache.py:127-163` (`_filter_fingerprint`) derives its fingerprint
from `canonical_key_components` with `query=""`, `k=0`, `corpus_version=0` — only
`filters` and `level` contribute. Since `notebook` is part of `filters`, the fingerprint
IS notebook-scoped **if** `notebook` remains in the `filters` dict at fingerprint-derivation
time. If a future refactor strips `notebook` from `filters` before `_tier2_put`, Tier-2
entries for notebook-A and notebook-B with the same query embedding would share a
fingerprint → cross-serve risk.

**Mitigation:** Never strip `notebook` from the `filters` passed to `store_search` /
`lookup_search`. The Tier-2 fingerprint receives it automatically.

### FM-3: Tier-3 rerank-set collision

**Trigger:** m2 brief says dense-only — no reranker is called. `lookup_rerank` /
`store_rerank` are never invoked on the m2 path. Tier-3 is NOT a collision risk for m2.
Document this explicitly in the implementation summary.

### FM-4: Threat-1 path traversal via filters JSON (AC5)

**Trigger:** An LLM passes `filters={"notebook": "../../etc/passwd"}` or
`filters={"notebook": "bridgeland-stability\x00"}`. `validate_slug` rejects both
(`../../etc/passwd` fails `^[a-z][a-z0-9-]{2,30}$`; null bytes fail similarly).
`notebook_dir` adds a symlink check. But `validate_slug` is only protective if it is
CALLED at the boundary — before `notebook_lancedb_path` constructs the path.

**Symptom if omitted:** `notebook_lancedb_path("../etc")` would raise `NotebookError`
from `notebook_dir`'s containment check, but the stack trace would include unsanitized
user input in the error message (potential log injection). Validate at the explicit
handler boundary first, before calling the path helper.

**Mitigation:** `validate_slug(slug)` must be the first call after extracting slug from
`filters`. Raise a clean `ValueError` (not `NotebookError`) from the handler so it
surfaces as a typed tool error (`isError=true`), not an unhandled exception → 500.

### FM-5: Silent fall-through to shared empty corpus (AC5 gap)

**Trigger:** (a) Valid slug format but no ingested data — `var/arxmcp/notebooks/<slug>/lancedb/`
exists but has no `corpus-version.json`. (b) Typo in filters key: `{"notbook": "bridgeland-stability"}`
is silently ignored; `notebook` extraction returns `None`; routing falls to shared corpus (empty);
returns 0 results with no warning.

**Symptom:** agent receives an empty result set and no error. The agent may conclude the
corpus is empty and halt its search without retrying.

**Mitigation (a):** Check `(notebook_lancedb_path / "corpus-version.json").is_file()` after
path validation — same contract as `server/config.py::derive_notebook_lancedb_path`'s F3
fix. Raise `ValueError` on un-ingested slug before opening any LanceDB handle.
**Mitigation (b):** The `filter_warnings` envelope field already surfaces unrecognized keys
(`SUPPORTED_FILTER_KEYS`). `"notebook"` is a routing key not in `SUPPORTED_FILTER_KEYS`;
if the implementer adds `"notebook"` to the warning set, typo'd keys surface. Alternatively,
document that `"notebook"` is silently ignored when absent — acceptable if AC4 must hold.

### FM-6: Per-notebook table-registry unbounded fd exhaustion

**Trigger:** A lazy slug→table memoization dict in `Resources` (or a module-level dict)
with no eviction bound. An adversary or buggy caller cycles through 10K synthetic slugs
(`aaa`, `aab`, ...), each a valid slug format but pointing to seeded lancedb paths. Each
call opens a new LanceDB handle; the dict grows without bound → fd exhaustion → ENOMEM
or EMFILE on LanceDB open.

**Mitigation:** Bound the slug→table registry at a small constant (e.g. 16 slots) with LRU
eviction. `collections.OrderedDict` with `move_to_end` on hit and `popitem(last=False)` on
overflow is the same pattern used by Tier-1 and Tier-3 LRU. Closing an evicted handle
requires `table.dataset.to_arrow()` doesn't hold a reference — LanceDB table handles are
reference-counted; closing the dict reference is sufficient. Add a `MAX_NOTEBOOK_TABLE_SLOTS`
constant; flag in `Resources` docstring.

### FM-7: fork-C + fork-A conflict — precedence ambiguity

**Trigger:** Server started with `ARXMCP_NOTEBOOK=bridgeland-stability`; agent then calls
`search_papers(filters={"notebook": "shimura-varieties"})`. m1 wired `ARXMCP_NOTEBOOK` to
override `config.lancedb_path` at startup, so the static Resources corpus is already
pointed at bridgeland-stability. The fork-A routing opens a SECOND, per-call table for
shimura-varieties. These two mechanisms can coexist silently OR conflict, depending on
implementation.

**Correct precedence rule:** Per-call `filters.notebook` wins. When the per-call slug is
present, the handler opens the per-call notebook table regardless of the process-level
`ARXMCP_NOTEBOOK` default. This is the only deterministic contract: a filter supplied
by the agent is more specific than a server-level default. Document in AC4 (the "both
present" case mentioned in the milestone brief).

**Symptom if unresolved:** fork-C and fork-A serve different notebooks for the SAME call
(bridgeland corpus from Resources vs shimura per-call) with no log distinction. Debugging
requires tracing which code path fired.

### FM-8: Concurrency race on slug→table registry

**Trigger:** Two concurrent requests for different slugs both find the registry empty and
both attempt to open a LanceDB table. If the registry is a plain `dict` without an
`asyncio.Lock`, both succeeds but one silently overwrites the other's entry → neither gets
evicted (fd leak), or one gets immediately closed and the first request raises on a
subsequent access.

**Mitigation:** Guard the registry with an `asyncio.Lock` (or `asyncio.Event`-based
singleflight). Wrap the lazy-open path: check under lock, if miss create under lock,
re-check before inserting (double-check idiom). The same pattern as
`server/resources.py::Singleflight.run` (lines 151-197).

---

## External sources

**MCP spec (2025-06-18) — tool inputSchema.** The spec defines `inputSchema` as a
JSON Schema object on the tool definition. The spec example shows a flat `properties`
dict; there is NO spec-level constraint on `additionalProperties` for tool argument
objects — the schema is entirely server-defined. Adding a `notebook` key to the
agent-supplied `filters` dict is transparent to the protocol: the server's `inputSchema`
for `filters` is `object | null` (no `additionalProperties: false`), so any additional
key is spec-valid. The X-1 no-re-pin claim is grounded in spec.

Quote from spec (`tools` section): `"inputSchema": { "type": "object", "properties": {...} }`
— the `properties` enumeration is the schema's contract; unrecognized keys in a call
are not a protocol error unless the server enforces `additionalProperties: false` (which
arXMCP does NOT, since `filters` is `dict[str, Any]`). Confirmed.

**Prompt-caching docs** — not consulted for this milestone. The X-2 UNCHANGED status
follows from the tool schema not changing (BP1 is pinned at the end of system prompt +
tool definitions block; no change to either).

---

## Recommendation

**Implement slug-in-key via filter-preservation (not filter-stripping):** extract the
slug from `filters` for path routing, but pass the ORIGINAL filters dict (with
`"notebook"` intact) to `derive_tier1_key` and all three cache tiers. Strip `"notebook"`
only from the LanceDB predicate-building path. This is the minimal, zero-API-change
design: no new cache parameters, no new cache method signatures, no new Tier-1 `slug`
column, no SCHEMA_VERSION bump. The existing `canonical_key_components` already length-
prefixes `filters_json` (the F1 fix from E08_S03), so the notebook key is collision-free
by construction.

Sequence: (1) extract and validate slug with `validate_slug`; (2) look up or open the
per-notebook LanceDB table from a bounded LRU registry; (3) read the notebook's
`corpus_version` from that table's `corpus-version.json`; (4) pass ORIGINAL filters to
`lookup_search`/`store_search`; (5) strip `notebook` from filters before predicate-building;
(6) set envelope `corpus_version` to the notebook's version.

---

## Open questions

No open questions — implementation can proceed on the above recommendation, with these
deferred-decision notes for the implementer:

- **LRU registry slot count:** 8–16 slots is adequate for a single-user server. Pick 16
  and document. No open question; just pick it.
- **Error type for invalid slug:** `ValueError` (surfaces as MCP tool execution error)
  is correct per the existing `_build_paper_id_predicate` precedent. Use `ValueError`.
- **`filter_warnings` for `notebook` key:** do NOT add `"notebook"` to
  `SUPPORTED_FILTER_KEYS` (it is a routing key, not a filter). It should not appear in
  `filters_applied`. Silently omit it from `filter_warnings` as well (it is an
  intentional routing key, not an unrecognized/ignored key). If added to warnings,
  every notebook-scoped call emits a spurious warning that the agent may misread as
  an error.

---

## External writes the implementation will require

None — this milestone is purely local. All changes are local server code, tests, and
design-note updates. No git push, PR, ticket, infra mutation, or third-party API call.
