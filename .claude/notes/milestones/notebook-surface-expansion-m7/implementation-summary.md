# Implementation Summary — notebook-surface-expansion-m7

**One-liner:** `tools/notebook_restore.py` consumes an m6 export bundle and
reproduces the notebook on a target deployment — safely (zip-slip class is
explicitly closed by a dual-layer guard) and round-trip-readable from a fresh
base+db. (Epic e3, piece 2/2 — **completes the roadmap.**)

**Commit range:** `<base>..<head>` (filled at finalize).
**Implementation path:** inline — 2 files (new CLI module + new tests), ~440 LOC.

---

## What landed

### `tools/notebook_restore.py` (new)
- `restore_bundle(bundle_path, *, notebooks_base, db_path, force=False) -> RestoreReport`
  — the testable Python entry; raises `NotebookError` on any safety/contract
  failure. The CLI is a thin shell (`main(argv=None) -> int` → `run(...)` →
  `restore_bundle(...)`).
- **Layer 1 — manual `_safe_member` pre-pass** (the primary gate, m7 D1).
  Iterates every `tar.getmembers()` BEFORE any extraction and rejects the WHOLE
  restore on ANY of: absolute path (POSIX or Windows-style); `..` segment
  pre- OR post-`os.path.normpath`; symlink / hardlink (`SYMTYPE` / `LNKTYPE`);
  device / FIFO (`CHRTYPE` / `BLKTYPE` / `FIFOTYPE`); normalized name not equal
  to `manifest.json` AND not beginning with `<slug>/`. No partial extraction.
- **Layer 2 — `tar.extractall(path=…, filter="data")`** (PEP 706 belt-and-braces).
  Independently rejects absolute paths, `..` escapes, links, and special files.
- Manifest contract (m7 D3): `_RESTORE_SUPPORTED_FORMATS = (1,)`; reject
  mismatched `format_version`; `validate_slug(manifest["slug"])`; cross-check
  `manifest.notebook.slug == manifest.slug`.
- DB layer (`_open_db_with_retry`, `_restore_db_rows`): direct `sqlite3` with the
  same PRAGMAs as `NotebooksStore._open_sync` + a small WAL-BUSY retry (3
  attempts, 200 ms backoff); `BEGIN IMMEDIATE` transaction; `DELETE` on
  `--force` (cascades to `notebook_papers` via FK), `INSERT` the notebook row;
  bulk `INSERT OR IGNORE INTO notebook_papers` (idempotent re-runs).
- `lancedb_path` is DERIVED from the target base (`str(target_dir / "lancedb")`)
  — m6 OMITS the absolute source path from the manifest, so an old host-path
  can never leak into the restored row (closes the m4 D3 / m6 D3 leak class on
  the consumer side).
- `--force` semantics (m7 D2): DB-only overwrite. **On-disk clobber is REFUSED
  unconditionally** — if `<notebooks_base>/<slug>/` already exists the restore
  refuses with `"run tools/notebook_purge.py <slug> first"`. Even under
  `--force`. Separation keeps file-write and DB-write security surfaces
  independently auditable.

### `tests/test_notebook_restore.py` (new, 19 tests — 3 added in m7-rect for F2/F3/F6; F4/F5 strengthened existing helpers/asserts)
- **End-to-end round-trip** — seed source via the m6 fixture (TestClient), GET
  the export route, write the tar, `restore_bundle()` into a SEPARATE fresh
  base+db, assert: DB rows match (slug, display_name, notebook_kind,
  `lancedb_path` is DERIVED from target base — never source), papers list
  matches, asset bytes reproduce byte-for-byte.
- **Malicious-bundle matrix** (6 tests): absolute path, `..` traversal,
  `SYMTYPE`, `LNKTYPE`, `CHRTYPE` device, member name not under slug → each
  rejected with `NotebookError`; **the target slug dir is NEVER created** (the
  pre-pass aborts before extraction).
- **Manifest contract** (4 tests): format_version mismatch, missing
  manifest.json, bad slug in manifest, top-level `slug` ≠ `notebook.slug`.
- **`--force` semantics** (3 tests): existing DB row without `--force`
  rejected; with `--force` overwrites (DELETE + INSERT cascades); existing
  on-disk slug dir REJECTED even with `--force` (the unconditional guard);
  the pre-existing on-disk file is NOT overwritten.
- **CLI wrapper** (2 tests): `main([...])` returns 0 on success + prints to
  stdout; returns 1 on failure + prints `error:` to stderr.

---

## Acceptance criteria status

- [x] **AC1 (round-trip)** — m6 export → restore into a FRESH base+db
  reproduces the notebook + papers + on-disk asset (`TestRoundTrip`).
- [x] **AC2 (safe extraction)** — Python 3.12 `tarfile.data` filter (PEP 706) +
  explicit pre-pass rejecting absolute / `..` / sym/hardlink / device/FIFO
  members; `validate_slug` on the manifest slug; `--force` is DB-only (on-disk
  clobber refused unconditionally); idempotent DB re-insert via
  `INSERT OR IGNORE` on `notebook_papers`.
- [x] **AC3 (tests)** — round-trip + 6 malicious-bundle + 4 manifest-contract +
  3 force-semantics + 2 CLI tests.

## Deviations from the brief

None material. Two synthesis-resolved decisions worth recording:
1. **`--force` is DB-only.** The brief said "refuse to clobber an existing slug
   without `--force`" without distinguishing DB row vs on-disk dir; the synthesis
   D2 split them so the security review is tractable (file-write and DB-write
   are independent failure modes). The operator must `notebook_purge.py <slug>`
   before restoring over an existing dir.
2. **`papers` are inserted via `INSERT OR IGNORE`** (idempotent re-runs) rather
   than catching `IntegrityError` per-row (researcher-1's alternative). Simpler
   + atomic in the single `BEGIN IMMEDIATE` transaction.

## Test surface

New: `tests/test_notebook_restore.py` (16). Changed: `tools/notebook_restore.py`
(new). ruff clean. Adjacent suites (`test_notebook_export.py`,
`test_notebook_api.py`) + byte-stability gates (`test_server_tool_schema.py`,
`test_prompts.py`) all green — **187 tests in the m7 regression sweep**.

**Pre-existing failure (NOT m7):** `test_tools_all.py::test_cite_neighbors_wired`
fails on a stale `var/arxmcp/index/kuzu` directory; m7 diff touches no
graph/citations code.

## Byte-stability / scope

CLI only. No `server/`, no `tools.py`, no `ALL_TOOLS`, no
`EXPECTED_TOOL_SCHEMA_SHA256`, no `EXPECTED_BP1_SHA256`, no `TOOL_SCHEMA_VERSION`
bump. No new HTTP route.

## External writes required

**None.** Purely local.
