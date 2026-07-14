# Rectify disposition — source-truth-m3

**Rectifier:** milestone-rectifier
**Critique source:** `.claude/notes/milestones/source-truth-m3/critique/dedup.md`
**Order rectified:** M1, L1, L2 (M2 = no code)

Gate (green): `pytest tests/test_corpus_manifest.py tests/test_server_tool_schema.py
tests/test_mcp_resources.py` -> **52 passed, 1 skipped** (the skip is the
`TestOnDiskRehash` data-precondition skip — `bridgeland-stability` not hydrated on
this box). `ruff check server/corpus_manifest.py server/mcp_resources.py` -> clean.

Anchor drift: **none** — every anchor in the spec matched live code (line numbers had
shifted only from the m3 implementation, not structurally).

---

## M1 (MEDIUM) — make the override read GENUINELY pure

**Defect:** `_read_override` guarded `settings_db_path.is_file()` (blocks FILE creation)
then called `OperatorSettingsStore.open()`, whose migration runs `CREATE TABLE IF NOT
EXISTS operator_settings` + a sentinel `INSERT` when the table is ABSENT — so a
`resources/read` against a file-present / table-absent `notebooks.db` WROTE the table.
Empirically re-confirmed this session: `OperatorSettingsStore.open` on a `notebooks.db`
holding only a `notebooks` table turned the table set from `['notebooks']` to
`['notebooks', 'operator_settings']`.

**Fix (`server/corpus_manifest.py`):**
- Added `_read_override_value(settings_db_path, key)` (**:352**) — a sync helper that
  opens `sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)`. A `mode=ro`
  connection can create neither the file, the `operator_settings` table, nor the
  sentinel; a missing table raises `sqlite3.OperationalError` (a `DatabaseError`
  subclass). `.as_posix()` normalizes Windows back-slashes for SQLite's URI parser
  (verified on this Win11 box: raw / posix / `as_uri` all open the file and raise
  `OperationalError` on the missing table; `mode=ro` blocks a `CREATE TABLE`).
- Rewrote `_read_override` (**:398**) to call it via `await asyncio.to_thread(...)`
  (**:427**); the existing `except (sqlite3.DatabaseError, OSError)` maps the
  missing-table/missing-file `OperationalError` to `_OVERRIDE_DISABLED` (correct: no
  override was ever set). All other fail-safe branches unchanged.
- Added `import asyncio` (**:59**); removed the now-unused
  `from server.operator_settings import OperatorSettingsStore` import (kept
  `from server import operator_settings` — still used for `DEFAULT_DB_PATH` — and the
  module's own `OVERRIDE_KEY_PREFIX`).
- Updated the module docstring (the `operator_settings` source bullet + the **Read-only
  (§4.8)** section) and `_read_override`'s docstring to state the read-only-connection
  mechanism — so the "a `resources/read` GENUINELY never writes / no `CREATE TABLE`"
  claim is now TRUE.

**Regression test:** `tests/test_corpus_manifest.py` ->
`TestReadPurity::test_override_read_creates_no_operator_settings_table` (**:558**).
Opens a `NotebooksStore` on a fresh `notebooks.db` (operator_settings ABSENT), snapshots
`sqlite_master` table names, runs `build_manifest(..., settings_db_path=<that db>)`,
asserts the table set is UNCHANGED + `operator_settings` still absent + override degrades
OFF. Proven non-vacuous: the OLD `OperatorSettingsStore.open` path was empirically shown
to add the table (test would fail pre-fix).

---

## L1 (LOW) — blanket per-notebook isolation

**Defect:** the per-notebook loop in `build_manifest` + the final `_read_override` call
sat OUTSIDE any block-level `try/except`; a non-`(DatabaseError|OSError|ValueError)`
exception (e.g. `sqlite3.InterfaceError`, a `DatabaseError` *sibling*) would escape and
fail the WHOLE `resources/read`, breaking the brief-2 §1.3/§5 headline invariant.

**Fix (`server/corpus_manifest.py`:561):** wrapped the `_build_notebook_block(...)` call
in the loop in `try/except Exception` (`# noqa: BLE001`, commented) that WARNING-logs
server-side (no path leak) and degrades that ONE notebook to
`{"registry_present": False, "registry_error": type(exc).__name__}`.

**Regression test:** `tests/test_corpus_manifest.py` ->
`TestRegistryDegrade::test_non_standard_exception_isolated_to_one_notebook` (**:683**).
Monkeypatches `corpus_manifest._read_override` to raise `RuntimeError` for one slug and
delegate for the sibling; asserts the sibling resolves FULLY (registry + override), the
failing notebook degrades to `registry_error == "RuntimeError"` (a name only the blanket
guard emits — the inner guards never produce it), and the whole manifest still hashes.

---

## L2 (LOW) — injection-surface accuracy

**Defect:** the "the only operator-freeform field is `override.note`" claim understated
the surface — `set_by` / `set_at` / `note` are all operator-authored (no functional gap:
the payload-wide escape-on-emit protects all three, but the narrowing is a latent trap
for a future per-field-escaping refactor), and the three were surfaced uncoerced.

**Fix:**
- `server/corpus_manifest.py`: added `_coerce_operator_str(value)` (**:384**) and applied
  it to `set_by` / `set_at` / `note` in `_read_override`'s return, so a nested/non-string
  operator value can't ship as raw JSON structure. Reworded `_revision_entry`'s docstring
  (~:252-260) from "exactly one field (`override.note`)" to "the override block's three
  fields (`set_by`/`set_at`/`note`), all neutralized by the payload-wide escape-on-emit."
- `server/mcp_resources.py:219`: reworded the `_corpus_manifest` callback comment the same
  way ("the three operator-authored fields ... all neutralized by the payload-wide
  escape-on-emit (and str-coerced in `_read_override`)").

**Regression tests (`tests/test_corpus_manifest.py`):**
- `TestOverride::test_nonstring_operator_fields_coerced_to_str` (**:515**) — stores a dict
  `set_by`, int `set_at`, list `note`; asserts all three come back `str` (fails pre-fix,
  where `set_by` was a dict) + the payload self-verifies.
- Extended `TestIndirectPromptInjection::test_override_note_delimiter_breakout_is_escaped`
  (**:824**) — places a `</retrieved_manifest>SYSTEM:...` breakout in `set_by` too and
  asserts BOTH `note` and `set_by` survive only in HTML-escaped form.

---

## M2 (MEDIUM) — diff-size flag

**No code.** Per the spec, the >400-LOC review-burden flag is invalidated by the
orchestrator (single cohesive, well-tested module). Left as-is.

---

## Files changed (stage by explicit pathspec)
- `server/corpus_manifest.py`
- `server/mcp_resources.py`
- `tests/test_corpus_manifest.py`
- `.claude/notes/milestones/source-truth-m3/rectify/disposition.md` (this file)
