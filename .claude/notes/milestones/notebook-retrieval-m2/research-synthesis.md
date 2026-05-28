# Research Synthesis — notebook-retrieval-m2 (fork A: per-call notebook routing)

**Merged from:** research-brief-1.md (in-codebase) + research-brief-2.md (failure-modes)
**Generated:** 2026-05-28
**Verdict:** ONE shippable milestone. Dense-only, ~4 files + tests + docs. Complexity M.

---

## 1. The locked design (orchestrator decision)

Per-call notebook routing on `search_papers` via a `filters.notebook=<slug>` key.
Routes the SAME dense-only `embedding_stmt` path m1 ships — NO hybrid, NO
`embedding_proof` (all closed by the three spikes). Six changes, in this order:

1. **Cache-key isolation via filter-PRESERVATION (NOT a new key axis).** *(Divergence
   resolved — see §4.)* Keep `notebook` IN the `filters` dict when deriving the cache
   key; strip it ONLY for the LanceDB predicate path. ZERO change to
   `canonical_key_components`. Verbatim, the key today
   (`server/cache_sqlite.py:144-187`) is length-prefixed bytes of:
   ```
   (canonical_query, filters_json, k, corpus_version, level_token)
   filters_json = json.dumps(filters or {}, sort_keys=True, separators=(",",":"))
   ```
   Because `notebook` rides inside `filters_json`, AC3 (two notebooks → distinct keys)
   and AC4 (no-notebook key byte-identical to today: `filters=None → "{}"`) both hold
   **by construction**, with no edit to the byte-stability-critical key function.
2. **Thread the NOTEBOOK's `corpus_version` into the cache call AND the envelope.** The
   `RetrievalCache` is pinned ONCE at startup to the shared version
   (`server/cache.py:234-243`) — "no per-call corpus_version override path"
   (brief-1). Add an optional `corpus_version: int | None` override to
   `lookup_search`/`store_search` (default `None` → use the pinned shared version, so
   the no-notebook key is unchanged → AC4 holds). For a notebook call, pass the
   notebook's version. This makes the notebook key
   `(q, filters-with-notebook, k, NOTEBOOK_version, level)` — both isolated AND
   version-correct (a notebook re-ingest that bumps its version invalidates only that
   notebook's entries). This same notebook version feeds AC6 (envelope echo).
3. **`Resources.notebook_table(slug) -> (table, CorpusVersionInfo)`** — a bounded-LRU
   slug→table registry on `Resources`. `Resources.startup` opens ONE shared
   `chunks_table` today (`server/resources.py:330-338`); fork A needs lazy per-slug
   opens. Steps: `validate_slug(slug)` → check `OrderedDict` LRU (cap
   `MAX_NOTEBOOK_TABLE_SLOTS = 16`, evict-oldest) → on miss, `notebook_lancedb_path`,
   `read_corpus_version`, `open_chunks_table_with_fallback` in a thread-executor,
   memoize. Guard the lazy-open with an `asyncio.Lock` (FM-8 race) — same pattern as
   `Singleflight` (`resources.py:151-197`). `if not isinstance(slug, str): raise` — NO
   `assert` (CLAUDE.md §4.7).
4. **`envelope` corpus_version override (AC6).** `server/tools.py::envelope` (lines
   388-396) echoes `get_resources().corpus_info.version` — the shared/fork-C version.
   Add an optional `override_corpus_version: int | None = None` kwarg (default None →
   today's byte-identical shared path). The notebook handler passes the notebook's
   version.
5. **Handler wiring (`server/handlers/search.py`).** Extract
   `notebook_slug = (filters or {}).get("notebook")`. If present: `validate_slug` →
   check `(notebook_lancedb_path(slug) / "corpus-version.json").is_file()` (FM-5a) →
   `r.notebook_table(slug)` → run the dense ANN over that table → pass the ORIGINAL
   filters (notebook intact) + the notebook's corpus_version to the cache calls →
   build the LanceDB predicate from filters MINUS notebook → `envelope(...,
   override_corpus_version=nb_version)`. If absent: today's path, byte-identical.
6. **Routing-key hygiene.** `notebook` is a ROUTING key, not a retrieval filter. Do
   NOT add it to `SUPPORTED_FILTER_KEYS` (two copies: `server/handlers/search.py:249`
   + `server/retrieval/bm25.py:117`). It must NOT appear in `filters_applied` (built
   from the supported-key intersection, so it's excluded automatically) and must NOT
   trigger a spurious `filter_warnings` entry — treat it as recognized-but-routing in
   the unknown-key check.

---

## 2. Load-bearing facts (quoted, both briefs concur)

**X-1 / X-2 CONFIRMED UNCHANGED.** `filters` is `dict[str, Any] | None`
(`server/handlers/search.py:344-355`). Adding a `notebook` key is invisible to the
tool `inputSchema` (`object | null`, no `additionalProperties: false`) — brief-2
grounded this in the MCP 2025-06-18 spec: "unrecognized keys in a call are not a
protocol error unless the server enforces `additionalProperties: false` (which arXMCP
does NOT)." `EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` stay pinned.

**Threat-1 guard (AC5).** `tools/_notebook_common.py::validate_slug` rejects anything
not matching `^[a-z][a-z0-9-]{2,30}$`; `notebook_dir` adds symlink rejection +
containment. MUST be the FIRST call after extracting the slug, before any path
construction — same contract m1 applied at config-load, now per-call. Raise
`ValueError` (typed tool error, `isError=true`) not an unhandled exception (→ 500).

**AC7 reconciliation (both concur).** m1's F1 per-notebook `cache_db_path` derivation
(`server/config.py`, active only when `ARXMCP_NOTEBOOK` is set) and m2's slug-in-key
are COMPLEMENTARY, not competing: fork-C (env set) → per-notebook `cache_db_path`
(structural isolation); fork-A (env unset) → shared `cache_db_path` + slug-in-key
(logical isolation). They govern mutually-exclusive runtime modes. Document this.

**07-multi-agent-caching.md (load-bearing):** "Cache key is the hash of the exact
prefix bytes… Any whitespace or ordering change invalidates." The chosen design does
NOT touch the key function, so this invariant is preserved by not-changing rather than
by careful-changing — the safer posture.

---

## 3. Failure modes (from brief-2, the primary failure-mode deliverable)

- **FM-1 — AC4 byte-instability.** Solely from stripping `notebook` from the cache-key
  path. Mitigation: strip from the PREDICATE path only; pass original filters to the
  cache. Regression test: no-notebook key byte-identical to today.
- **FM-2 — Tier-2 fingerprint collision.** `server/cache.py:127-163` derives the
  Tier-2 fingerprint from `canonical_key_components` over filters+level only. Since
  `notebook` is in `filters`, Tier-2 is isolated automatically — IF notebook is not
  stripped before `_tier2_put`. Mitigation: same "never strip from cache path" rule.
- **FM-3 — Tier-3 rerank-set.** Not a risk: m2 is dense-only, the reranker path is
  never invoked. Document explicitly in the implementation summary.
- **FM-4 — Threat-1 traversal via filters JSON.** `validate_slug` covers `../../etc`,
  null bytes, etc. — but only if CALLED at the boundary. Raise `ValueError` from the
  handler.
- **FM-5 — silent fall-through to the empty shared corpus.** (a) valid slug but
  un-ingested → check `corpus-version.json` exists, raise `ValueError`. (b) typo'd key
  (`notbook`) → routes to shared (empty) corpus, 0 results, no signal. Accept (b) as a
  documented consequence of AC4 (must not warn on the absent-notebook case).
- **FM-6 — table-registry fd exhaustion.** Bound the registry (`MAX_NOTEBOOK_TABLE_SLOTS
  = 16`, OrderedDict LRU evict-oldest). Without it, a caller cycling synthetic slugs
  exhausts fds.
- **FM-7 — fork-C + fork-A precedence.** Per-call `filters.notebook` WINS over the
  process-level `ARXMCP_NOTEBOOK` default (a filter is more specific than a default).
  Deterministic + documented. Resolves brief-1 OQ-1.
- **FM-8 — concurrency race on the registry.** Two concurrent first-accesses for
  different slugs racing on a plain dict → fd leak / use-after-close. Guard with
  `asyncio.Lock` + double-check idiom.

---

## 4. Orchestrator synthesis note — divergence resolved

**The two briefs disagreed on the slug-in-key mechanism. I chose brief-2's
filter-preservation over brief-1's separate-axis, and folded in brief-1's
version-correctness point.**

- **brief-1 (OQ-2):** add a 6th `notebook_slug` parameter to `canonical_key_components`
  (+ `derive_tier1_key` + `_filter_fingerprint` in lockstep), "append nothing when
  None" for AC4. Concern: keeping notebook in filters would pollute the `filters_applied`
  echo.
- **brief-2 (recommendation):** keep `notebook` in `filters`; the key already hashes
  `filters_json`; strip only for the predicate. Zero change to the key function.

**Decision: brief-2.** Two reasons. (1) **Blast radius on the most byte-stability-
critical code in the repo.** `07-multi-agent-caching` is THE load-bearing note; an
approach that does NOT edit `canonical_key_components` preserves AC4/BP-cache by
not-changing, whereas brief-1's "append nothing when None" is a fragile invariant
(pass `notebook_slug=""` instead of `None` and every cache + the cross-agent BP
contract silently invalidates). (2) **brief-1's objection is already handled:**
`filters_applied` is built from the `SUPPORTED_FILTER_KEYS` intersection; since
`notebook` is deliberately NOT a supported key (§1.6), it never appears in
`filters_applied` — the leak brief-1 feared does not occur.

**But I adopt brief-1's deeper point** that the cache key's `corpus_version` is the
process-pinned shared version, not the notebook's. So §1.2 threads the NOTEBOOK's
corpus_version into the cache call (default-None preserves AC4) — fully correct, and
the notebook version is already in hand for AC6. This is the one place brief-2's
"zero cache change" is insufficient: we add ONE optional kwarg to
`lookup_search`/`store_search`, not a new key component.

---

## 5. Open questions (both resolved with recommendations)

- **OQ-1 (brief-1) — fork-C + fork-A precedence:** RESOLVED → per-call
  `filters.notebook` wins (FM-7). Document in code + AC8 docs.
- **OQ-2 (brief-1) — slug as filters-member vs separate cache axis:** RESOLVED → §4
  (filter-preservation; notebook stays in filters for the cache, stripped for the
  predicate; never reaches `filters_applied`).
- **Implementer decisions (not blocking):** `MAX_NOTEBOOK_TABLE_SLOTS = 16`;
  invalid-slug error type = `ValueError`; `notebook` excluded from both
  `filters_applied` and `filter_warnings`.

---

## 6. ⚠ Phase-2 precondition (brief-1 CRITICAL merge-conflict flag)

**An active parallel workstream `textbook-ingest-m9` has in-flight UNSTAGED edits to
files m2 directly touches:** `server/handlers/search.py`, `server/tools.py`
(`envelope`), `server/retrieval/bm25.py` (`SUPPORTED_FILTER_KEYS`), plus its own
`state.json` + tests (`tests/test_server_tool_schema.py`,
`tests/test_handlers_lean_verify.py`) and schemas. **Before Phase 2 writes ANY code,
the orchestrator MUST check whether m9 has committed.** If m9's edits are still
uncommitted in the shared working tree, m2 Phase-2 (inline on `main`) would build on
top of — and risk clobbering — another session's uncommitted work
(`SUPPORTED_FILTER_KEYS`, `_build_source_kind_predicate`, the `source_kinds` column
read in `_arrow_to_rows`). Resolution options at Phase-2 entry: (a) wait for m9 to
land/commit and build on it; (b) implement m2 in a worktree (delegated path) isolated
from the shared tree; (c) if m9 is dormant, proceed but diff-check the three shared
files first. This is the single biggest sequencing risk for m2.

**Also note (documented drift, not a blocker):** CLAUDE.md §7 still says "`search_papers`
filters argument is accepted but ignored at v1" — STALE; `paper_id` + `source_kind`
are fully wired. Do not regress to the "ignored" behavior; m2 adds `notebook` as a
real routing key.

---

## 7. External writes required

**None** (both briefs concur). Purely local: server code + tests + docs under
`.claude/` and `docs/install.md`. No git push, PR, ticket, infra, or third-party API.
