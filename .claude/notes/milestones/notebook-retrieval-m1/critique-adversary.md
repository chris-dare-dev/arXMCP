# Critique — notebook-retrieval-m1

**Critic:** adversary
**Generated:** 2026-05-28T00:00:00Z
**Commit range:** `da9a800f..56397647`
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: fork-C routing is correct and well-tested at the config layer, but the persisted Tier-1 SQLite cache is SHARED across notebook relaunches and keyed without a notebook slug — a latent cross-notebook wrong-results / data-leakage vector (F1).
- Finding counts: 0 CRITICAL, 1 HIGH, 3 MEDIUM, 1 LOW.
- Highest-risk file:line: `server/config.py:458` (validator rewrites `lancedb_path` but NOT `cache_db_path`, so two notebook servers share `var/arxmcp/cache/retrieval.db` while the cache key carries only `corpus_version`, not the slug).
- Cache byte-stability (axis 1) clean for BP1/tool-schema: no `server/tools.py` / `server/prompts.py` / handler / Field edits; pin tests pass at HEAD. The cache concern is a DIFFERENT cache (Tier-1 retrieval, not the Anthropic prompt cache).
- The synthesis claim "fork C cache isolation is automatic (one server = one corpus_version)" holds WITHIN a process but NOT across relaunches against a shared SQLite file — corpus_version is per-dataset MVCC (bridgeland=369, shimura=49 today, but a fresh small notebook can collide).
- Test surface: the end-to-end "Resources.startup boots against an ARXMCP_NOTEBOOK-derived path" is untested though the `seeded_lancedb` + `mocked_bge_m3` fixtures to do it cheaply already exist in the same file (F2).
- Threat 1 (slug→path) is correctly gated BEFORE filesystem use via `notebook_lancedb_path → notebook_dir → validate_slug` + symlink rejection + containment; ambiguity guard holds even when both env vars are set (verified empirically). Clean.
- Absolute-vs-relative `lancedb_path` (synthesis risk note) is a non-issue: every consumer resolves or passes through cleanly. `data_dir`/`ops_dir` sharing across notebook servers is benign (filesystem-level disk metric + shared cron sentinels).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Tier-1 cache shared across notebooks; key lacks notebook slug

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/config.py:458 (root cause); server/cache_sqlite.py:103-141 (key); server/resources.py:506 (shared path)
- **What:** The notebook validator rewrites `self.lancedb_path` but leaves `cache_db_path` at the shared default `var/arxmcp/cache/retrieval.db` (`server/config.py:134`, unmodified). `Resources.startup` opens the Tier-1 store at that shared path (`server/resources.py:506`) with `corpus_version=corpus_info.version`. The Tier-1 key is `sha256(query + filters + k + corpus_version + level)` (`server/cache_sqlite.py:135-141`) — NO notebook slug. The SQLite file persists across restarts (`cache_sqlite.py` module docstring) and `RetrievalCache.open` does NOT call `purge_other_corpus_versions` (`server/cache.py:268-278`); `_rehydrate_tier1_from_sqlite` loads ALL unexpired rows regardless of corpus_version (`server/cache.py:298-309`).
- **Why it matters:** corpus_version is the per-dataset LanceDB MVCC integer, NOT globally unique — confirmed on disk (bridgeland-stability=369, shimura-varieties=49, both 1-paper). Two notebooks can share a corpus_version (e.g. two freshly ingested small notebooks, or any pair whose ingest used the same number of write ops). Sequence: launch `ARXMCP_NOTEBOOK=A` (version V), query "X" → result row cached under `sha256("X"+{}+k+V+level)` in the shared DB. Within the 1-hour TTL, relaunch `ARXMCP_NOTEBOOK=B` where B also has version V; an agent queries "X" with the same k/level → Tier-1 HIT returns notebook A's chunks for a notebook-B query. This is wrong results + cross-notebook content leakage on a plausible operator workflow (the milestone's whole point is switching notebooks by relaunch). The synthesis's "fork C isolation is automatic" reasoning silently assumes one process never reuses another notebook's persisted cache — which the shared `cache_db_path` violates.
- **Proposed fix:** Cheapest correct fix: in `derive_notebook_lancedb_path`, also redirect the cache to a per-notebook sibling so notebooks never share a Tier-1 file:
  ```python
  # after: self.lancedb_path = derived
  if "cache_db_path" not in self.model_fields_set:
      self.cache_db_path = derived.parent / "cache" / "retrieval.db"
  ```
  (derived is `.../notebooks/<slug>/lancedb`; `.parent` is `.../notebooks/<slug>`.) This keeps each notebook's Tier-1 cache structurally isolated, mirroring how the lancedb itself is isolated — and is exactly the structural-isolation posture the synthesis claimed fork C already had. Alternatively, gate `RetrievalCache.open` to call `purge_other_corpus_versions(corpus_info.version)` at startup AND add the notebook slug to the key — but per-notebook `cache_db_path` is the smaller, more robust change and avoids the slug-in-key refactor the synthesis deliberately deferred to m2.
- **Regression guard:** Test that two `Config(notebook=...)` instances with colliding corpus_version derive DISTINCT `cache_db_path` values; and an integration test that writes a Tier-1 row under notebook A's `cache_db_path`, reopens `RetrievalCache` at notebook B's `cache_db_path`, and asserts the row is NOT visible (miss). Both are synthetic, no model required.

### F2 — No end-to-end test that Resources.startup boots a notebook path

- **Severity:** MEDIUM
- **File:** tests/test_server_startup.py:328-394 (TestNotebookConfig stops at config-string assertions)
- **What:** Every `TestNotebookConfig` test asserts only the derived `lancedb_path` STRING (`:343`, `:351`, `:358`) or a config-load error (`:368`, `:378`, `:388`). None drives `Resources.startup(cfg)` against an `ARXMCP_NOTEBOOK`-derived path. The "server actually boots against the notebook and pins its corpus_version" claim (AC1 routing) is unverified — only the string derivation is.
- **Why it matters:** The validator could derive a correct string while `Resources.startup` chokes on the absolute, `.resolve()`-d notebook path or some interaction (e.g. an absolute path through `open_chunks_table_with_fallback` / BM25Phase). The file ALREADY has `seeded_lancedb` (`:108`) + `mocked_bge_m3` (`:90`) fixtures and the `TestReadinessTransition` pattern (`:197-219`) that runs `Resources.startup` against a `Config(lancedb_path=...)` with no real model — so closing this gap is cheap and the AC1 "operator-deferred end-to-end query" excuse does not apply to the no-model startup-routing assertion.
- **Proposed fix:** Add a test that seeds `notebooks_base / "demo-nb" / "lancedb"` as a real seeded corpus (reuse the `seeded_lancedb` builder logic / corpus-version.json + 2 chunks), sets `ARXMCP_NOTEBOOK=demo-nb`, calls `asyncio.run(Resources.startup(cfg))`, and asserts the resources pin the NOTEBOOK's corpus_version and the opened table is the notebook's (e.g. row count = 2). Synthetic + mocked BGE; no `requires_model` gate.
- **Regression guard:** This test IS the guard — it converts AC1 from a config-string assertion into a boot-and-serve assertion.

### F3 — Config-load `is_dir()` vs Resources.startup open is a TOCTOU

- **Severity:** MEDIUM
- **File:** server/config.py:452 (`if not derived.is_dir()`) vs server/resources.py:306 (`read_corpus_version(config.lancedb_path)`)
- **What:** The validator checks `derived.is_dir()` at config-load and raises AC5's clean error if absent. `Resources.startup` later re-reads the path and raises `CorpusNotIngestedError` if `corpus-version.json` is absent. Two distinct checks, two distinct error types, with a window between them; and `is_dir()` only proves the `lancedb` dir exists — NOT that `corpus-version.json` is present inside it.
- **Why it matters:** A notebook dir that exists but was never fully ingested (lancedb dir present, no `corpus-version.json`) PASSES the AC5 config check and then hits the deeper `CorpusNotIngestedError` at startup — exactly the "500 mid-startup, not a clean config error" outcome AC5 was written to prevent. The TOCTOU race (dir deleted between config-load and startup) is low-probability on a single workstation, but the "dir exists, marker missing" case is a realistic partial-ingest state that defeats AC5's intent. Note `test_missing_notebook_corpus_clear_error` (`tests/test_server_startup.py:364`) only covers the dir-fully-absent case, not the dir-present-marker-absent case.
- **Proposed fix:** Tighten the config check to match what startup actually requires: check `(derived / "corpus-version.json").is_file()` (or call `read_corpus_version(derived) is not None`) instead of `derived.is_dir()`, so the AC5 clean error fires for partial-ingest states too. This also collapses the two divergent checks toward one contract.
- **Regression guard:** Add a test: create `notebooks_base / "demo-nb" / "lancedb"` as an empty dir (no `corpus-version.json`) and assert `Config(notebook="demo-nb")` raises the AC5 ValidationError naming the ingest command — proving partial-ingest is caught at config-load, not at startup.

### F4 — Ambiguity guard rejects ARXMCP_LANCEDB_PATH set to its own default

- **Severity:** MEDIUM
- **File:** server/config.py:431 (`if "lancedb_path" in self.model_fields_set`)
- **What:** The guard keys on `model_fields_set`, so setting `ARXMCP_LANCEDB_PATH=var/arxmcp/index/lancedb` (the exact default value) together with `ARXMCP_NOTEBOOK` is rejected as "ambiguous" even though the explicit value matches the default and carries no real conflict. Verified: the guard fires on the env path (`Config()` with both env vars raises ValidationError).
- **Why it matters:** Operators commonly export a baseline `ARXMCP_LANCEDB_PATH` in a shared shell profile / systemd unit and then add `ARXMCP_NOTEBOOK` per-launch. With this guard they get a hard config-load failure with no obvious cause (the value they set IS the default). It is a usability foot-gun on the milestone's primary operator workflow, not a correctness bug — hence MEDIUM, not HIGH. The error message is clear once read, but the rejection of a no-op explicit value is surprising.
- **Proposed fix:** Only reject when the explicit `lancedb_path` DIFFERS from the field default, i.e. guard on `self.lancedb_path != type(self).model_fields["lancedb_path"].default` in addition to `"lancedb_path" in self.model_fields_set` — or document the strict behavior prominently in `docs/install.md`. If keeping strict, that is a defensible choice; flag it so Phase 4 decides deliberately rather than by omission.
- **Regression guard:** Test `Config(notebook="demo-nb", lancedb_path=Path("var/arxmcp/index/lancedb"))` — assert either it succeeds (if relaxed) or raises with the expected message (if intentionally strict). Pin the chosen semantics.

### F5 — Docstring/error names `tools/notebook_ingest.py` — verify the script exists

- **Severity:** LOW
- **File:** server/config.py:456 (`uv run python tools/notebook_ingest.py {self.notebook}`)
- **What:** The AC5 remediation message and the `notebook_lancedb_path` docstring (`tools/_notebook_common.py:130`) both name `tools/notebook_ingest.py` as the ingest command. The `test_missing_notebook_corpus_clear_error` test asserts the message matches `notebook_ingest.py demo-nb` (`tests/test_server_startup.py:368`), so the STRING is pinned — but nothing verifies the script actually exists on disk.
- **Why it matters:** If the operator-facing remediation command does not exist (or is named differently), the clean AC5 error sends the operator to a dead path. This is the recurring "doc/comment says X, code does Y" drift class. LOW because it is a message-accuracy issue, not a runtime bug, and the path is operator-facing rather than executed.
- **Proposed fix:** Confirm `tools/notebook_ingest.py` exists (and accepts a slug arg); if the actual ingest entrypoint differs, correct the message + docstring. If the script is itself a future-milestone deliverable, soften the message to name the real current path.
- **Regression guard:** A test asserting `Path("tools/notebook_ingest.py").is_file()` (or that the named entrypoint is importable), co-located with the AC5 message test so the message and the script cannot drift.

## What was done well

- Threat 1 is correctly gated: the slug flows through `notebook_lancedb_path → notebook_dir → validate_slug` (regex) + un-resolved-symlink rejection + post-resolve containment BEFORE any filesystem use, and `TestNotebookConfig::test_notebook_slug_traversal_rejected` + the helper symlink test cover traversal/slash/uppercase/short/symlink cases.
- The shared-seam discipline (AC8) is real, not cosmetic: `notebook_lancedb_path` is a single function both fork C and the future fork A call, with the slug-safety contract inherited once rather than reimplemented — `TestNotebookLancedbPathHelper` proves the C/A paths share one safety contract.
- BP1 + tool-schema byte-stability is preserved by construction: zero edits to `server/tools.py`, `server/prompts.py`, handler signatures, or Field descriptions; the pin tests (`test_server_tool_schema.py`, `test_prompts.py`) pass at HEAD — the notebook key rides the free-form `filters` dict exactly as the synthesis predicted.
- The no-op-when-unset posture (AC4) is genuinely byte-identical: `if self.notebook is None: return self` short-circuits before any new code path, and `test_notebook_unset_keeps_shared_corpus` pins the default `lancedb_path` unchanged.
- The dense-only retrieval path is genuinely untouched — `search_papers` still does a single ANN over `embedding_stmt` with `excluded_kinds=["proof"]` and `retrieval_mode="dense_only"` (`server/handlers/search.py:480-543`); the AC2 correction (don't wire BM25/RRF/rerank) was honored.
- The ambiguity guard holds across construction paths including the env-var path (empirically verified: both env vars set → ValidationError), closing the "operator points at two substrates" foot-gun.
- Validator ordering is safe: `derive_notebook_lancedb_path` is the FIRST `model_validator(mode="after")`, so the rewrite lands before any other validator (and before `Resources.startup`) reads `lancedb_path`.
- Local-first / Docker / no-fork / tier-sequencing all clean: no cloud dependency, no forked code, reuses only shipped infra (`notebook_dir`, `Resources.startup`); ruff clean; no banned patterns in runtime code (the `assert`s in the diff are all pytest assertions in test code).
- Good lazy-import hygiene: the `tools._notebook_common` import is deferred inside the validator so the common notebook-unset case pays no server→tools import cost at module load.

## Recommended rectification order

1. **F1 (HIGH)** — per-notebook `cache_db_path` derivation. Highest blast radius (silent wrong results / cross-notebook leakage on the relaunch workflow) and the cheapest correct fix (≈4 LOC in the existing validator + 2 synthetic tests). Do this first.
2. **F3 (MEDIUM)** — tighten the AC5 config check from `is_dir()` to `corpus-version.json is_file()`; small and removes a TOCTOU + a partial-ingest gap in the same edit.
3. **F2 (MEDIUM)** — add the Resources.startup-against-notebook boot test; reuses existing fixtures, converts AC1 from string-assertion to boot-and-serve.
4. **F4 (MEDIUM)** — decide ambiguity-guard semantics (relax to value-differs, or document strict) and pin it.
5. **F5 (LOW)** — verify `tools/notebook_ingest.py` exists; correct the message/docstring if not.

## Rectification status
