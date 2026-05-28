# Research Brief — notebook-ops-hardening-m2

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-28T00:00:00Z
**Focus:** LanceDB format-pin half (CAND-16) + external-sources-first

---

## In-codebase context

### Installed versions (live-verified)

- **lancedb:** `0.30.2` (from `uv.lock`, confirmed via `uv run python -c "import lancedb; print(lancedb.__version__)"`)
- **lance (pylance):** NOT installed as a standalone package. `lancedb 0.30.2` bundles lance in `lancedb._lancedb` (a Rust extension). `import lance` fails with `ModuleNotFoundError`.
- **pyproject.toml pin:** `"lancedb>=0.6"` — open-ended lower bound only, no upper cap.
- **uv.lock resolved version:** `lancedb==0.30.2` (ARM64 macOS wheel `lancedb-0.30.2-cp39-abi3-macosx_11_0_arm64.whl`, sha256 `3dd8cb9e2e25efb32c088b24b3fbc57f3f24a636f4b8ad4b287b1eb52f6b5075`)

### Design note load-bearing quotes

From `.claude/notes/05-storage-and-indexing.md` §Versioning via LanceDB MVCC:

> "LanceDB exposes native versioning: every write operation on a dataset creates a new integer version (starting from 1). Readers pin a specific version by calling `dataset.checkout(version=N)`, which returns a read-only snapshot."

> "Manual symlink swaps (`current -> v0007`) are **explicitly prohibited** under the new design. Use LanceDB's native MVCC mechanism instead."

The format pin milestone does NOT touch the MVCC version-integer contract; it is additive.

### The `data_storage_version` parameter — CRITICAL FINDING

**`data_storage_version` IS the correct parameter name in the public API docs for lancedb 0.30.2**, but live inspection reveals it is **deprecated and silently dropped** in `LanceDBConnection.create_table`:

```python
# LanceDBConnection.create_table (lancedb/db.py, lancedb 0.30.2)
# Accepts data_storage_version in signature but does NOT forward it to LanceTable.create.
# The parameter is silently accepted and ignored.
tbl = LanceTable.create(
    self, name, data, schema,
    mode=mode, ...,
    storage_options=storage_options,   # ← data_storage_version is NOT here
    storage_options_provider=storage_options_provider,
)
```

The `LanceTable.create` classmethod (which IS the write path) also marks the parameter deprecated with:

```
data_storage_version: optional, str, default "stable"
    Deprecated.  Set `storage_options` when connecting to the database and set
    `new_table_data_storage_version` in the options.
```

When `data_storage_version` is passed to `LanceTable.create`, it emits a `DeprecationWarning` and translates it to `storage_options["new_table_data_storage_version"] = data_storage_version`. But since `LanceDBConnection.create_table` never passes it down, the translation never fires for the standard call path.

**THE CORRECT PARAMETER for lancedb 0.30.2 is `storage_options={"new_table_data_storage_version": "stable"}`** passed to `db.create_table(...)`. This bypasses the deprecated path entirely and goes directly to the Rust layer.

Live-verified:
```python
tbl = db.create_table("chunks", schema=CHUNKS_SCHEMA_V1,
                       storage_options={"new_table_data_storage_version": "stable"})
# Rust receives storage_options={'new_table_data_storage_version': 'stable'} — confirmed
```

### Accepted values for `new_table_data_storage_version`

Live testing confirms these are accepted without error: `"stable"`, `"legacy"`, `"2.0"`, `"2.1"`, `"stable_starting_v2_2"`. Invalid strings are also silently accepted (no validation at Python layer — the Rust layer applies them). The correct value to pin is **`"stable"`** — this is the documented default and maps to whatever the current "production-stable" format is for the installed release.

**Default when omitted:** When `storage_options` is `None` (current code), the Rust extension receives `None` and applies its own default. Live measurement shows all tables produced identical on-disk format regardless of whether `"stable"`, `"legacy"`, `"2.0"`, or `None` was passed — all produce Lance format major version 3, minor version 0 (verified by reading the 16-byte file trailer: `...03 00 4c 41 4e 43`). This means the default is already `"stable"` in 0.30.2, and the value `"stable"` is an alias that can shift meaning in future releases (see Failure Mode E below).

### Write sites (edit locations)

All sites that call `db.create_table(...)` and must gain the `storage_options` argument:

**Site 1 — `ingest/store.py` line 825:**
```python
tbl = db.create_table(CHUNKS_TABLE_NAME, schema=CHUNKS_SCHEMA_V1)
```
This is the global arXiv corpus LanceDB AND the per-notebook LanceDB (both call `write_chunks` → this line). This is the primary write site.

**Site 2 — `ingest/index_equations.py` lines 66–69:**
```python
return db.create_table(
    EQUATIONS_TABLE_NAME,
    schema=EQUATIONS_SCHEMA_V1,
)
```

**Site 3 — `ingest/index_definitions.py` lines 333–336:**
```python
return db.create_table(
    DEFINITIONS_TABLE_NAME,
    schema=DEFINITIONS_SCHEMA_V1,
)
```

**`tools/_notebook_common.py`:** Contains no `create_table` calls — it is a path-helper module only. No write edits needed here.

**`ingest/re_embed.py`:** Contains no `create_table` calls — all connections via `lancedb.connect` + `open_table`. However, the staging LanceDB used by `run_re_embed` is written via `write_chunks` (Site 1), so Site 1 covers this path.

**`server/routes/notebooks.py`:** Records lancedb_path string in SQLite only, no LanceDB table creation.

### MCP server surface / BP1 impact

This milestone touches `ingest/store.py`, `ingest/index_equations.py`, `ingest/index_definitions.py` only. It does NOT touch:
- `server/tools.py::ALL_TOOLS` — no tool added/removed/modified
- `EXPECTED_TOOL_SCHEMA_SHA256` in `tests/test_server_tool_schema.py` — no re-pin needed
- `server/prompts.py` (BP1/BP2 breakpoints) — untouched
- Any MCP protocol surface

The local-first contract (`127.0.0.1` only, no external network) is untouched. This milestone is purely ingest-path storage hardening.

---

## Prior decisions and lessons

From git log: recent commits are all textbook-ingest and notebook-ops milestones. No prior work on `data_storage_version` pinning. The `lancedb>=0.6` lower bound was set in E04_S01 and has not been revisited.

From `.claude/notes/05-storage-and-indexing.md`: the LanceDB MVCC contract (integer version pinning via `corpus-version.json`) is load-bearing for cache key discipline. Format-pin changes must not break MVCC semantics — verified: `merge_insert` + `tbl.version` work correctly when `storage_options` is set.

**MEMORY note relevant:** The `list_tables()` comment in `store.py` line 808 documents a lancedb 0.30 API change (`table_names` deprecated). The format-pin change is similarly API-version-sensitive — cite this pattern in code comments.

---

## External sources

No external docs were successfully fetched (404 on LanceDB GitHub release tags and CHANGES.md). Live code inspection of the installed `lancedb==0.30.2` package was used instead and is more authoritative than release notes.

**From `lancedb/table.py` (lancedb 0.30.2) docstring — verbatim:**

```
data_storage_version: optional, str, default "stable"
    Deprecated.  Set `storage_options` when connecting to the database and set
    `new_table_data_storage_version` in the options.
```

This sentence establishes: (a) the documented default is `"stable"`, (b) the parameter is deprecated, (c) the canonical approach is `storage_options["new_table_data_storage_version"]`.

**From `lancedb/db.py` (lancedb 0.30.2) docstring — verbatim:**

```
data_storage_version: optional, str, default "stable"
    Deprecated.  Set `storage_options` when connecting to the database and set
    `new_table_data_storage_version` in the options.
```

---

## Recommendation

**Pin using `storage_options={"new_table_data_storage_version": "stable"}` on all three `db.create_table(...)` calls (Sites 1–3 above). Do NOT use the deprecated `data_storage_version` positional argument.**

Reasoning: `data_storage_version` is silently dropped by `LanceDBConnection.create_table` in 0.30.2 (the kwarg is accepted but never forwarded to `LanceTable.create`). Only `storage_options={"new_table_data_storage_version": "stable"}` reaches the Rust extension. Using the correct key also avoids the `DeprecationWarning` and future removal.

The value `"stable"` is correct because: (a) it is the documented default, (b) it is the value the Rust layer applies today, (c) making it explicit means any future release that changes the default will produce a divergence that is caught at connection time (or surfaced in release notes) rather than silently shifting the format under existing data.

**pyproject.toml:** Add a pin-rationale comment adjacent to `"lancedb>=0.6"` explaining the storage format discipline. Do NOT tighten the version upper bound for this milestone alone — a future milestone can add `<0.31` if a format regression is observed.

**Re-pinning existing datasets:** existing on-disk Lance files are written at format 3.0 (verified). New writes with `"stable"` produce the same format 3.0. No incompatibility for `merge_insert` into existing tables — LanceDB's merge path appends new data files; it does not rewrite existing files. Read-back of pre-pin rows continues unchanged.

---

## Failure mode analysis

**FM-A — Reader/writer version skew after `uv upgrade lancedb`.**
- Trigger: `uv upgrade` bumps lancedb from 0.30.2 to e.g. 0.32.x which ships a new default format.
- Symptom: new writer creates files in format 4.0; old reader (if a second process is pinned to 0.30.2) cannot decode them.
- Mitigation: explicit pin makes format version visible in `pyproject.toml`; any `uv upgrade` that changes the default is caught because the pin survives the upgrade. The MVCC integer (`corpus-version.json`) is format-independent; the concern is the Lance file format bytes, not the dataset version integer.

**FM-B — Pinning to a value the installed version rejects → write crash.**
- Trigger: using a string like `"2.5"` that maps to a format not yet implemented, or a future release removes `"legacy"` support.
- Symptom: `db.create_table(...)` raises an exception (from the Rust layer).
- Mitigation: pin to `"stable"` which is explicitly documented as the default and cannot be removed without a major API break. Tested above — accepted in 0.30.2.

**FM-C — Existing on-disk datasets written without the pin; new writes break reads of old data.**
- Trigger: corpus was written without `storage_options` (current state); implementer adds pin; next write via `merge_insert` lands files in format "stable".
- Symptom: reader opens existing table, runs merge_insert with "stable" storage_options — could the new files be unreadable by the connection that opened the old ones?
- Mitigation: tested live — `merge_insert` into an existing table created WITHOUT `storage_options` works correctly when `storage_options` is added to the `create_table` call path. The storage_options on `create_table` only affect NEW tables; `merge_insert` appends data files to the existing table's format (the format is set at table-creation time, stored in the dataset manifest). **For existing datasets, `storage_options` on `create_table` is irrelevant — those tables already exist and the `open_table` path is taken instead.** The pin ONLY affects future `create_table` calls (new deployments / notebooks). No data corruption risk.

**FM-D — Per-notebook LanceDB vs global corpus LanceDB format divergence.**
- Trigger: `write_chunks` is called with `lancedb_path=per_notebook_path` for textbook ingest. If Site 1 gains the pin, both global and per-notebook tables get `"stable"`.
- Symptom: none — both go through the same `db.create_table` codepath with the same `storage_options`.
- Mitigation: Site 1 is the single write-path for both corpus types. Uniform.

**FM-E — `"stable"` alias meaning shifts across releases (defeating the pin).**
- Trigger: lancedb 0.32 redefines `"stable"` to mean "format 4.0" which is not backward-compatible with 0.30.2 readers.
- Symptom: new install of 0.32 writes tables that a process still on 0.30.2 cannot open.
- Mitigation: This is partially mitigated by tightening `"lancedb>=0.6"` to `"lancedb>=0.6,<0.31"` in a future milestone. For this milestone, explicitly documenting the pin purpose in `pyproject.toml` is the correct action — a reader encountering an old corpus with an incompatible format will get a lancedb error message, not silent corruption. The MVCC contract still holds (version integers are independent of format).

**FM-F (bonus) — `data_storage_version` kwarg silently accepted by the public API but not applied.**
- Trigger: an implementer reads the deprecated docstring default `"stable"` and passes `data_storage_version="stable"` to `db.create_table(...)`.
- Symptom: no error, no warning (the DeprecationWarning path in `LanceTable.create` is never reached because `LanceDBConnection.create_table` drops the kwarg), table is created with the library default (which happens to be `"stable"` anyway in 0.30.2, so no observable difference today, but may diverge in future).
- Mitigation: use `storage_options={"new_table_data_storage_version": "stable"}` as recommended above. Add a code comment citing this gotcha so future maintainers don't revert to the deprecated form.

---

## Open questions

No open questions — implementation can proceed on the above recommendation.

The implementer does NOT need to tighten the lancedb upper bound in `pyproject.toml` for this milestone; a pin-rationale comment is sufficient. Upper-bound tightening is a separate, explicitly scoped decision (FM-E mitigation) that can land independently.

---

## External writes the implementation will require

None — this milestone is purely local.

All changes are in `ingest/store.py`, `ingest/index_equations.py`, `ingest/index_definitions.py`, and `pyproject.toml` comments. No git push, no ticket, no infra mutation, no third-party API call.
