# Critique — notebook-ops-hardening-m2

**Critic:** adversary
**Generated:** 2026-05-28T00:00:00Z
**Commit range:** a54f8f3a3eb5847ca758d5b6c58c49f1f22ba630..6e18e96e5cb08349c1687c86ac36346849b49365
**Verdict:** SHIP

## Executive summary

- SHIP. This is a tightly-scoped 2-pragma durability bump + a LanceDB on-disk
  format pin (3 `create_table` sites + one shared constant). Every load-bearing
  claim in the synthesis was verified against the diff and the surrounding code:
  the connection-scoping argument, the create-vs-open branch (no migration risk),
  and the regenerable-cache scope boundary all hold.
- Finding counts: 0 CRITICAL, 0 HIGH, 1 MEDIUM, 2 LOW.
- Highest-value observation: `tests/test_notebook_durability.py:237-254` proves the
  pin is *passed to* `db.create_table` but not that lancedb *forwards it to Rust* —
  the exact silent-drop failure mode the synthesis itself names as the top risk goes
  unguarded at runtime. MEDIUM, not HIGH (the source guard + read-back test bound the
  blast radius; this is a latent regression-detection gap, not a present bug).
- Cache byte-stability (Axis 1): CLEAN. The diff touches none of `server/tools.py`,
  `server/prompts.py`, the `tools/list` wire response, or `EXPECTED_TOOL_SCHEMA_SHA256`
  (verified: `git diff --stat` over those four paths is empty).
- Durability correctness: CLEAN. `_open_sync` (server/notebooks_store.py:110-135) is
  the SINGLE sqlite3 connection for `notebooks.db`, lifetime-cached as `self._conn`;
  the per-open pragma set is correct and sufficient. The two OTHER durable-ish trackers
  (`server/ingest_tracker.py`, `server/parse_tracker.py`) persist THROUGH this same
  connection (they import `NotebooksStore`, they do not open their own sqlite3 handle),
  so they inherit the upgrade — no second opener was missed.
- Format-pin safety: CLEAN. `write_chunks` (ingest/store.py:816-833) routes existing
  tables through `open_table` (untouched) and only new tables through the pinned
  `create_table`; `merge_insert` appends in the table's existing format. No read-break
  for existing on-disk datasets.
- No-fork / local-first / version-drift: CLEAN. No fork URLs, submodules, or `uv.lock`
  changes in the diff; lancedb stays at 0.30.2 (matches the synthesis's silent-drop
  analysis); `lancedb>=0.6` upper bound deliberately left open with a documented rationale.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Spy test proves pass-through, not Rust-forwarding of the pin

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_notebook_durability.py:237-254
- **What:** `test_write_chunks_passes_storage_options_to_create_table` wraps the REAL
  `db.create_table` and asserts `captured["storage_options"] == LANCE_STORAGE_OPTIONS`.
  This proves the option reaches the lancedb Python `create_table` entrypoint. It does
  NOT prove lancedb forwards the value to the Rust layer / writes a `"stable"`-format
  dataset. The synthesis (FM-F, lines 195-196) names exactly this class of bug: the bare
  `data_storage_version` kwarg is "accepted in the signature but never forwarded" — a
  silent drop that "looks correct and does nothing." The new `storage_options` key is the
  current working form, but no test would catch a future lancedb release that begins
  silently dropping `new_table_data_storage_version` the same way.
- **Why it matters:** The entire milestone's value is "a uv/pip upgrade can't silently
  migrate the on-disk format." A regression test that asserts only the Python-side
  pass-through cannot detect the precise failure mode (silent drop at the binding) that
  motivated the milestone. `test_pinned_table_is_readable` (:256-267) proves writes don't
  crash but says nothing about WHICH format was written (the unpinned default is also
  `"stable"` today, so a fully-dropped option still produces a readable table that passes
  this test).
- **Proposed fix:** Add one assertion that inspects the actual on-disk format of the
  table written via the pinned path. The synthesis (line 178) deliberately avoided the
  "brittle 16-byte trailer read," which is fair — but a non-brittle alternative exists:
  open the written dataset and read its reported storage/format version through the
  lancedb/lance API if exposed (e.g. `tbl.to_lance().data_storage_version` or the
  equivalent in 0.30.2), and assert it equals the `"stable"` major. If no stable API
  surface exposes it, gate a single trailer-byte assertion behind a `requires_model`-style
  marker so it is opt-in rather than load-bearing on every run. Either way, leave a comment
  that this is the ONLY test that would catch a future silent-drop regression.
- **Regression guard:** the added format-version assertion is itself the guard; it must
  fail if `storage_options` is removed from the `create_table` call AND lancedb's default
  ever diverges from `"stable"`.

### F2 — Two of three create_table sites have source-guard coverage only, no runtime spy

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/test_notebook_durability.py:269-292
- **What:** Only `ingest/store.py::write_chunks` gets a runtime spy proving the option
  reaches `create_table` at execution time. `ingest/index_equations.py:70-75` and
  `ingest/index_definitions.py:337-342` are covered only by the parametrized SOURCE-TEXT
  guard `test_all_create_table_sites_pin_storage_options` (greps for the literal
  `storage_options=LANCE_STORAGE_OPTIONS`). A refactor that renames the constant import
  alias, or wraps the call, could pass the source grep while changing runtime behavior.
- **Why it matters:** Low blast radius — both index tables are regenerable indices
  (definitions / equations), not user state, and existing real-LanceDB tests for those
  paths exist (`tests/test_definitions_index.py`, `tests/test_embed_equations.py`). The
  gap is detection precision, not a present bug.
- **Proposed fix:** Optional. Either extend the existing spy pattern to call
  `open_or_create_equations_table` / `open_or_create_definitions_table` under the same
  `spy_connect` monkeypatch, or accept the source guard as adequate given these are
  regenerable indices. Cheapest acceptable resolution is to DEFER and note the rationale.
- **Regression guard:** if fixed, the spy assertion on each index create path.

### F3 — fullfsync=ON is a silent no-op on Linux; no comment notes the prod platform

- **Severity:** LOW
- **Source:** adversary
- **File:** server/notebooks_store.py:131
- **What:** `PRAGMA fullfsync=ON` is a macOS-only mechanism (the comment at :123 correctly
  says "macOS only"). On Linux — the documented production-container target (CLAUDE.md §8
  gotcha #1: "Production Linux containers don't need [the macOS workaround]") — the pragma
  is accepted and reads back, but `F_FULLFSYNC` does not exist; SQLite falls back to plain
  `fsync`. The durability story on the actual deployment platform rests entirely on
  `synchronous=FULL` + `fsync`, which is correct and sufficient on Linux, but the comment
  frames `fullfsync` as the durability mechanism without stating that it contributes
  nothing in prod.
- **Why it matters:** Purely a documentation-precision issue. The behavior is correct on
  both platforms; a future reader debugging a Linux durability question could be misled
  into thinking `fullfsync` is doing work it isn't. No test asserts `fullfsync==1` on a
  platform where it would read back differently, so there is no test fragility here either.
- **Proposed fix:** Append one clause to the :123 comment, e.g. "On Linux F_FULLFSYNC does
  not exist; SQLite falls back to fsync, which with synchronous=FULL is already durable —
  the pragma is a no-op there and harms nothing." No code change.
- **Regression guard:** none required (doc-only).

## What was done well

- Correct diagnosis and avoidance of the silent-drop trap: the code comment at
  ingest/schema.py:97-108 and the test guard at tests/test_notebook_durability.py:289-292
  both actively prevent a maintainer from "fixing" the working `storage_options` form back
  to the silently-dropped bare `data_storage_version=` kwarg. This is the highest-value
  landmine in the change and it is well-defended.
- Connection-scoping is handled exactly right. The test reads `fullfsync` from
  `store._conn` (not a fresh connection), and `test_fullfsync_does_not_persist_to_fresh_connection`
  (:124-142) locks in WHY — preventing a future maintainer from "simplifying" it into the
  broken separate-connection pattern that works only for the database-scoped `user_version`.
- The create-vs-open branch was verified, not assumed: existing tables route through
  `open_table` (ingest/store.py:817) and are untouched; only new tables hit the pinned
  `create_table` (:829-833). No migration / read-break risk for on-disk datasets.
- Scope boundary is principled and test-locked: `cache_sqlite.py` and
  `theorem_names_store.py` stay NORMAL because they are regenerable from the corpus, and
  `TestDurabilityScope` (:145-165) pins that decision so a future "make everything FULL"
  sweep is caught. The regenerability claim checks out (theorem store rebuilds via
  `python -m ingest.index_theorem_names`).
- Zero MCP-surface / BP1 / tool-schema-hash impact, correctly identified up front and
  verified in the diff. No cache byte-stability risk.
- WAL mode and FK enforcement are preserved across the pragma change, and
  `test_journal_mode_stays_wal` (:118-122) guards the WAL invariant that the FK cascade
  depends on.
- The deviations from the literal AC (storage_options form instead of bare kwarg;
  `_notebook_common.py` correctly NOT edited because it has no `create_table`) are
  recorded honestly in both the synthesis and the implementation summary, with live
  verification cited — not hand-waved.
- pyproject.toml rationale comment is precise and resists scope creep: it explicitly says
  the upper bound is NOT tightened yet and names the exact condition (`<0.31` only if a
  real format regression is observed) under which it should be.
- The 11 new tests are real assertions, not vacuous — verified by running
  `tests/test_notebook_durability.py tests/test_store.py` (all pass), and the spy test
  wraps the REAL `create_table` rather than a mock, so it genuinely exercises the call path.
- Shared constant `LANCE_STORAGE_OPTIONS` placed in `ingest/schema.py` (the single source
  of truth for schema) and imported by all 3 sites — no copy-paste drift across the
  three `create_table` calls.

## Recommended rectification order

1. F1 (MEDIUM) — add an on-disk-format assertion so the milestone's core guarantee
   (no silent format drift) actually has a regression test. Highest leverage; small.
2. F3 (LOW) — one-clause comment addition for the Linux fullfsync no-op. Trivial.
3. F2 (LOW) — optional spy extension to the two index create sites, or DEFER with the
   regenerable-index rationale.

## Rectification status (filled by Phase 4)

- **F1 (MEDIUM) — FIXED.** Added
  `TestLanceFormatPin::test_storage_options_key_reaches_engine_not_silently_dropped`
  (tests/test_notebook_durability.py). It does NOT use the brittle 16-byte trailer
  read, and does NOT need pylance (`to_lance()` is unavailable — pylance isn't
  installed, confirmed). Instead it uses a discriminator the synthesis missed: a
  GARBAGE `new_table_data_storage_version` is validated only in the Rust/Lance layer,
  so passing it via `storage_options` RAISES `RuntimeError: Unknown Lance storage
  version` (proving the key is forwarded to the engine), while the same garbage via the
  bare `data_storage_version` kwarg does NOT raise (locking the silent-drop trap). If a
  future lancedb release begins silently dropping the `storage_options` key the same
  way, the raise disappears and this test fails — exactly the future-regression the
  pass-through spy could not catch. Live-verified both branches before adding.
- **F3 (LOW) — FIXED.** Appended a clause to the `_open_sync` comment
  (server/notebooks_store.py) noting that on Linux (the prod-container target)
  `F_FULLFSYNC` does not exist, SQLite falls back to plain `fsync`, and durability in
  prod rests on `synchronous=FULL` + `fsync` — so `fullfsync` is a harmless no-op
  there. Doc-only, no code change.
- **F2 (LOW) — DEFERRED.** The two index `create_table` sites
  (`index_equations.py`, `index_definitions.py`) keep source-guard coverage only (the
  parametrized `test_all_create_table_sites_pin_storage_options`). Rationale (matches
  the adversary's "cheapest acceptable resolution"): both are REGENERABLE indices
  (definitions/equations), not user state; real-LanceDB tests already exercise those
  write paths (`tests/test_definitions_index.py`, `tests/test_embed_equations.py`); and
  the shared `LANCE_STORAGE_OPTIONS` constant means all 3 sites pass the identical
  object, so the `write_chunks` runtime spy + the new F1 engine-reaches test already
  prove the mechanism end-to-end for the constant they all share. A future milestone
  may extend the spy to the index paths if those tables ever hold non-regenerable data.

**Net:** 2 of 3 findings fixed (the 1 MEDIUM + 1 LOW); 1 LOW deferred with rationale.
Durability test count 11 -> 12. ruff clean.
