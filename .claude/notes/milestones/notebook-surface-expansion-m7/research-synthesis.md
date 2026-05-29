# Research Synthesis — notebook-surface-expansion-m7

**Milestone:** `tools/notebook_restore.py` consumes an m6 export bundle into a
target notebooks base — safely (zip-slip class is the load-bearing security
surface) and round-trip-readable. (Epic e3, piece 2/2 — **completes the roadmap.**)
**Mode:** standard (2× Sonnet). Both `ok`; converge on dual-layer security + DB-only
`--force`. Both open questions resolved (verified live). 0 external writes.
**Implementation path:** INLINE — 2 files (new CLI module + new tests), < 500 LOC.

---

## Load-bearing decisions

### D1 — Dual-layer security on tar extraction (both briefs agree)

The bundle is **untrusted** — m6's producer-side preflight cannot be relied upon
(a hostile/tampered bundle bypasses it). Two independent layers:

**Layer 1 — manual `_safe_member` pre-pass** (the PRIMARY gate). Iterate
`tar.getmembers()` BEFORE any extraction; REJECT THE WHOLE RESTORE (raise + exit
non-zero, extract nothing) on ANY of:
- `tarinfo.isabs()` (absolute path) OR `name` starts with `/`;
- any `..` segment in `pathlib.PurePosixPath(name).parts` OR in
  `os.path.normpath(name)`;
- `tarinfo.issym()` or `tarinfo.islnk()` (sym/hardlink — not present in m6's
  USTAR output but a hostile bundle could carry them);
- `tarinfo.isdev()` or `tarinfo.isfifo()` (device / FIFO);
- normalized name is neither `manifest.json` exactly NOR begins with `<slug>/`
  (post-`PurePosixPath`/`normpath` so trick forms like `./foo/../bar` are caught).

**Layer 2 — `tar.extractall(path=dest, filter="data")`** (the BELT-AND-BRACES
layer). PEP 706's `data` filter independently rejects absolute paths, `..`
escapes, sym/hardlinks, and special files. Python 3.12 (live runtime) accepts
`filter=` natively; 3.11 has it backported per PEP 706 (verified: `pyproject.toml`
pins `>=3.11`; `tarfile.data_filter` exists; the project's runtime is 3.12.13).

Reject the **entire** restore on any violation — never partial-extract a
suspicious bundle.

### D2 — `--force` semantics: DB-only overwrite; on-disk clobber is REFUSED

Both briefs converge. `--force` permits the DB re-insert to overwrite an existing
slug row (DELETE + INSERT — cascades `notebook_papers` via FK). `--force` does
**NOT** allow extracting on top of an existing `<base>/<slug>/` directory — if
the dir already exists, refuse with a clear error (instruct the operator to run
`tools/notebook_purge.py <slug>` first). This separation keeps the security
review tractable: file-write safety and DB-write safety are independent.

### D3 — Manifest format-version pinning + slug consistency

- `_RESTORE_SUPPORTED_FORMATS: tuple[int, ...] = (1,)` — reject any
  `manifest["format_version"]` not in the tuple, with a clear error citing the
  observed and supported values.
- `validate_slug(manifest["slug"])` — refuse a bad slug in the manifest BEFORE
  any path construction.
- Cross-check: every `<slug>/...` member name MUST share the manifest's slug
  (the pre-pass's "name starts with `<slug>/`" check enforces this).

### D4 — Restore order (atomicity-of-failure, not transaction-atomicity)

1. Open `tar` (`tarfile.open(bundle_path, mode="r")`).
2. Read + parse `manifest.json` from the tar (before any disk write).
3. Validate `format_version`, `validate_slug(manifest["slug"])`.
4. Resolve `target_dir = notebook_dir(slug, base=notebooks_base)`. **Pre-check:
   refuse if `target_dir` already exists**, regardless of `--force` (D2).
5. Run `_safe_member` pre-pass (D1 Layer 1) over every member; abort on any
   violation. No disk write yet.
6. Connect direct `sqlite3` to `db_path` (PRAGMAs: `foreign_keys=ON`,
   `journal_mode=WAL`, `synchronous=FULL` — mirroring `_open_sync`); start
   a `BEGIN IMMEDIATE` transaction with retry on `sqlite3.OperationalError`
   ("database is locked") — 3 retries, 200 ms backoff (brief-2 OQ2).
7. Check `SELECT 1 FROM notebooks WHERE slug = ?`; if present and not `--force`,
   refuse. If `--force`, `DELETE FROM notebooks WHERE slug = ?` (cascades).
8. `INSERT INTO notebooks` from the manifest, with `lancedb_path =
   str(target_dir / "lancedb")` (DERIVED from the target base — never reuse
   the m6-omitted absolute path).
9. Bulk `INSERT OR IGNORE INTO notebook_papers` for every paper row.
10. Commit the SQL transaction.
11. `tar.extractall(path=notebooks_base, filter="data")` — produces
    `<base>/<slug>/<rel>` (since members are `<slug>/<rel>`). The Layer 2 gate
    fires here independently of the pre-pass.
12. Print a one-line success summary (slug + paper count + asset count).

**Atomicity boundary**: SQL is transactional (rollback on any failure to step
10). Disk is NOT transactional (a partial extraction at step 11 leaves a
half-populated `<slug>/` dir). The error message on step-11 failure tells the
operator to run `tools/notebook_purge.py <slug> --force` + remove the dir
manually. The SQL rows + on-disk assets are designed to be independently
purgeable (per the m6 / `notebook_purge.py` discipline).

### D5 — `restore_bundle()` is a testable Python function; CLI is a thin shell

```python
def restore_bundle(
    bundle_path: Path,
    *,
    notebooks_base: Path,
    db_path: Path,
    force: bool = False,
) -> RestoreReport:
    """Return a structured report; raise NotebookError on any safety violation
    or DB conflict; ValueError on bundle-format issues."""
```

The CLI (`main(argv=None) -> int`) parses args (`--notebooks-base`, `--db`,
`--force`, positional `<bundle.tar>`), calls `restore_bundle`, catches
`NotebookError`/`ValueError` → prints to `stderr` → returns exit code 1.
`run()` exists for direct test invocation (mirroring `notebook_purge.py`).
Tests call `restore_bundle()` directly + a small `main([...])` smoke for the
CLI wiring.

### D6 — Python version guard (brief-2 OQ1 resolved)

`pyproject.toml` pins `>=3.11`. `tarfile.data_filter` + the `filter="data"`
extractall kwarg are **available on 3.11.4+** (PEP 706 was security-backported)
and natively on 3.12+. The project's live runtime is 3.12.13. No version guard
needed; pass `filter="data"` explicitly (avoids the 3.13+ DeprecationWarning
about the absent argument).

---

## Implementation checklist

1. **`tools/notebook_restore.py`** (new) — module-level constants
   (`_RESTORE_SUPPORTED_FORMATS = (1,)`, the safe-member-error classes);
   `_safe_member(tarinfo, slug)` validator; `_open_db_with_retry(db_path)`
   helper; `restore_bundle(...)` the Python function (D4); `run(...)` (sync
   wrapper); `_build_arg_parser()`; `main(argv=None) -> int`; the standard
   `if __name__ == "__main__": sys.exit(main())` pragma.
2. **`tests/test_notebook_restore.py`** (new) — happy-path round-trip via the
   m6 export route + restore into a fresh tmp base/db; the malicious-bundle
   matrix (absolute path, `..` traversal, symlink, hardlink, device/FIFO);
   format-version mismatch; bad-slug manifest; manifest slug ≠ member prefix;
   no-clobber-without-`--force` (DB); `--force` DB-only re-insert; on-disk
   clobber REFUSED even with `--force`; the CLI `main([...])` smoke (exit code
   0 on success, 1 on validation failure).

## Byte-stability / scope

No MCP / `server/tools.py` / `EXPECTED_TOOL_SCHEMA_SHA256` / `EXPECTED_BP1_SHA256`
change. No new server route. CLI only. The m6 export route is consumed via its
existing HTTP surface; no m6 source edit.

## Open questions

None blocking. Both researcher OQs resolved above (D6 for the Python guard, D4
step 6 for the WAL BUSY retry).

## External writes required

**None.** Purely local. (Push at milestone end is per-event authorized.)
