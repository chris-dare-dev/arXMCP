# Rectify summary — source-truth-m3

**Rect commit:** `e183413` (GPG-signed; `Reviewed-by:` both critics; `Co-Authored-By: Claude Opus 4.8`).
3 files (2 production + 1 test). **Critique:** C0 H0 M2 L2. **Invalidation rate:** 1/4 = 25%. **Gate:** OK.

## Fixed (3)

| id | sev | fix |
|----|-----|-----|
| M1 | MED | **The manifest `resources/read` is now genuinely pure.** `_read_override` reads via a read-only `sqlite3.connect(f"file:{path}?mode=ro", uri=True)` connection (new `_read_override_value` + `asyncio.to_thread`) — a `mode=ro` connection refuses to write, so it can no longer create the `operator_settings` table (`OperatorSettingsStore.open` ran `CREATE TABLE IF NOT EXISTS` + a sentinel INSERT on a table-absent `notebooks.db`). Docstrings corrected to state the read-only mechanism; unused `OperatorSettingsStore` import removed. Regression test snapshots `sqlite_master` before/after a manifest read on a fresh `notebooks.db` and asserts the table set is unchanged (non-vacuous — the old path created the table). |
| L1 | LOW | Blanket per-notebook `except Exception` around `_build_notebook_block` in `build_manifest`'s loop → degrades one notebook to `registry_present:false, registry_error=type(exc).__name__` rather than failing the whole `resources/read` on a non-`(DatabaseError\|OSError\|ValueError)` exception. Test: monkeypatch `_read_override` to raise `RuntimeError`; the sibling notebook still resolves + the manifest still hashes. (Cross-critic: adversary + arxmcp.) |
| L2 | LOW | `set_by`/`set_at`/`note` coerced to `str` (non-None); the "the only operator-freeform field" claim reworded to "three operator-authored fields, all neutralized by the payload-wide escape-on-emit" (`corpus_manifest.py` + `mcp_resources.py`); the delimiter-breakout injection test extended to `set_by`. |

## Invalidated (1)
- **M2** (MEDIUM, +561-LOC code diff auto-flag): a single cohesive, single-concern provenance module (~40% docstrings), fully covered by 24 tests + 697 test LOC, no cross-cutting edits. Splitting adds churn without reducing risk — conscious acceptance.

## Regression tests
`tests/test_corpus_manifest.py` — the sqlite_master-unchanged read-purity test (M1), the blanket-isolation RuntimeError test (L1), the extended `set_by` delimiter-breakout test (L2). Gate: corpus_manifest + `tools/list` schema-hash pin + resources green (52 pass / 1 data-precondition skip); ruff clean.

## No go-live
m3 is a read-only, on-read-generated resource — no corpus mutation, no backfill. The manifest
resolves against whatever registry state exists on day one (`registry_present:false` for the 3
un-hydrated notebooks). No owner-gated go-live.

## External write
- `git push origin main` — the m3 feat + rect + notes. Owner-authorized per-event.
