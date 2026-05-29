# Research Brief — notebook-surface-expansion-m7

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-29T20:00:00Z

---

## In-codebase context

### Bundle contract (from m6 — authoritative)

From `server/routes/notebooks.py` (lines 1416–1427, 1442–1473, read verbatim):

```python
_EXPORT_MANIFEST_FORMAT_VERSION: int = 1

_EXPORT_NOTEBOOK_ALLOWLIST: tuple[str, ...] = (
    "slug", "display_name", "notebook_kind", "created_at", "parse_status",
)
```

Manifest JSON shape (from `_build_export_manifest`):
```json
{
  "format_version": 1,
  "notebook": {"slug","display_name","notebook_kind","created_at","parse_status"},
  "papers": [{"paper_id","added_at"}],
  "slug": "..."
}
```

Bundle members: `manifest.json` at the root + `<slug>/<rel>` asset members
(USTAR format, not PAX — PAX drifts mtimes even with `mtime=0`). The m6
implementation summary states: "Bundle layout: `manifest.json` at the bundle
root + assets under `<slug>/<rel>` members (slug-prefixed, relative paths
constructed manually — never from `path` directly; eliminates the
absolute-path / `..` class on the m7 untar side)."

**OMITTED from manifest (m6 synthesis D3):** `lancedb_path`, `parsed_html_path`
(absolute host paths = info-leak), `parse_error` (internal stderr). m7 MUST
derive `lancedb_path` from `notebook_dir(slug, base=target_base) / "lancedb"`.

### CLI patterns in `tools/`

All four notebook CLI tools share the same structural pattern (quoted from
`tools/notebook_purge.py` and `tools/notebook_init.py`):

1. **Pure function `run(...)` returns int exit code.** Tests call `run()`
   directly. The `main(argv)` is a thin argparse wrapper.
2. **`_build_arg_parser()` returns `argparse.ArgumentParser`** with
   `formatter_class=argparse.RawDescriptionHelpFormatter`.
3. **`main(argv=None) -> int`** calls `_build_arg_parser().parse_args(argv)`,
   then calls `run(...)`, catches `NotebookError`, prints to stderr, returns 1.
4. **`if __name__ == "__main__": sys.exit(main())`** at the bottom (pragma: no cover).
5. **Exit codes:** 0 = success, 1 = validation/precondition failure, 2 = user abort.
6. **`--force` precedent in `notebook_purge.py`** (line 285):
   `parser.add_argument("--force", action="store_true", help="...")`.
   In purge, `--force` skips interactive confirmation but does NOT silence
   warnings. m7 `--force` should skip the no-clobber guard.
7. **`stderr` for errors/warnings; `stdout` for progress.** All tools follow:
   `print(f"error: {exc}", file=sys.stderr)` in `main()`.
8. **CRITICALLY: None of the existing notebook CLI tools uses `asyncio.run`
   or imports `NotebooksStore`.** `notebook_purge.py`, `notebook_init.py`, and
   `notebook_fetch.py` are all purely synchronous — they manipulate the
   filesystem and `papers.txt` files, never the SQLite DB. m7 is the FIRST
   notebook CLI tool that must write to `notebooks.db`.

The `--db` override pattern does NOT exist in any existing tool. m7 introduces
`--db` and `--notebooks-base` to support targeting a fresh deployment. The
implementation needs `asyncio.run(...)` wrapping the async `NotebooksStore`
methods.

### `tools/_notebook_common` helpers (verbatim)

```python
NOTEBOOKS_BASE: Path = REPO_ROOT / "var" / "arxmcp" / "notebooks"
SLUG_RE: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9-]{2,30}$")

def validate_slug(slug: str) -> None:
    """Reject any slug that doesn't match SLUG_RE. Raises NotebookError."""
    if not isinstance(slug, str):
        raise NotebookError(...)
    if not SLUG_RE.fullmatch(slug):
        raise NotebookError(...)

def notebook_dir(slug: str, *, base: Path | None = None) -> Path:
    """Return the per-notebook dir. base= param for tests and CLI overrides.
    Validates slug AND containment. Refuses symlinks at the slug path."""
    validate_slug(slug)
    nb_base = (base or NOTEBOOKS_BASE).resolve()
    unresolved_target = nb_base / slug
    if unresolved_target.is_symlink():
        raise NotebookError(...)
    target = unresolved_target.resolve()
    try:
        target.relative_to(nb_base)
    except ValueError as exc:
        raise NotebookError(...) from exc
    return target
```

m7 MUST call `notebook_dir(slug, base=target_base)` with explicit `base=`
(not the default global) for the fresh-deployment round-trip test.

### `NotebooksStore` re-insert path

From `server/notebooks_store.py` (lines 330–376):

```python
async def create_notebook(
    self,
    slug: str,
    display_name: str,
    lancedb_path: str,
    created_at: str,
    notebook_kind: str = "arxiv",
    parse_status: str | None = None,
) -> None:
    """Insert a notebook row. Raises sqlite3.IntegrityError on duplicate slug
    — the REST handler catches and translates to HTTP 409 (FM-5)."""
```

```python
async def add_paper(
    self,
    slug: str,
    paper_id: str,
    added_at: str,
) -> None:
    """Insert a junction row. Raises sqlite3.IntegrityError on duplicate
    (slug, paper_id) — handler catches → HTTP 409. Also raises if the
    parent notebook doesn't exist (FK violation)."""
```

**Decision for m7 idempotency:**

- **Notebook INSERT:** check existence first via `get_notebook(slug)`. If slug
  exists AND `--force` is NOT set: refuse with a clear error (exit code 1). If
  `--force`: `delete_notebook(slug)` first (cascades papers via FK), then
  `create_notebook(...)`. Do NOT catch `IntegrityError` — the
  delete-then-insert idiom is cleaner and avoids the race in
  `INSERT OR REPLACE` (which also resets the rowid and triggers cascade delete).
- **Papers INSERT:** use `INSERT OR IGNORE` directly — the m7 brief explicitly
  says "idempotent — if `(slug, paper_id)` exists, skip; restore should be
  re-runnable." `add_paper` raises `IntegrityError` on duplicate; the restore
  function needs to catch it and continue (or bypass via a raw execute with
  `INSERT OR IGNORE`). Recommend a new `_add_paper_or_ignore` private helper
  in the restore module using `asyncio.to_thread` + direct SQL, OR override via
  a try/except around `add_paper`. The try/except is simpler and avoids a
  new method on `NotebooksStore`.

Note: `NotebooksStore` is async. The restore CLI must use
`asyncio.run(restore_bundle_async(...))` from the sync `run()` function.

### Python `tarfile` extraction filter

`pyproject.toml` pins `requires-python = ">=3.11"`. The project Python is
3.12.13 (verified: `/Users/chris.dare/Library/Python/3.9/bin/uv run python`).

From `tools/arxiv_fetch.py` (lines 330–346) — the existing `_safe_extract`
in the codebase:
```python
def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    dest_resolved = dest.resolve()
    for member in tar.getmembers():
        member_path = (dest / member.name).resolve()
        try:
            member_path.relative_to(dest_resolved)
        except ValueError as e:
            raise RuntimeError(
                f"refusing to extract path outside dest: {member.name}"
            ) from e
    tar.extractall(dest, filter="data")
```

This is the CANONICAL pattern already in the codebase: explicit member-by-member
rejection THEN `filter="data"` as a belt-and-braces layer. m7 MUST follow this
pattern verbatim. The `filter="data"` parameter is confirmed working in Python
3.12 (verified live). In Python 3.11 the parameter was backported in security
releases (3.11.4+), but pyproject pins `>=3.11` — safe since the project's
runtime Python is 3.12.

**Additional m7 member validation** beyond `_safe_extract`'s containment check:
- Reject members with `..` in any path component (covers `name = "foo/../etc/passwd"`)
- Reject absolute paths (name starting with `/`)
- Reject symlink members (`member.type == tarfile.SYMTYPE`)
- Reject hardlink members (`member.type == tarfile.LNKTYPE`)

The `filter="data"` layer also rejects these, but the explicit check before
`extractall` is a defense-in-depth guard and enables precise error logging.

### Test fixture pattern (from m6)

The m6 test `tests/test_notebook_export.py` (lines 39–64) shows the canonical
fixture pattern:
```python
@pytest.fixture
def exp_client(tmp_path, monkeypatch):
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    db_path = tmp_path / "notebooks.db"
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        app = FastAPI()
        app.state.notebooks_store = store
        app.include_router(notebooks_router, prefix="/ui/api")
        with TestClient(app) as c:
            yield c, base
        loop.run_until_complete(store.close())
    finally:
        loop.close()
```

The m7 test for the round-trip SHOULD NOT use the TestClient fixture exclusively
— the restore step invokes the standalone CLI function `restore_bundle(...)`,
NOT an HTTP endpoint. The test flow should be:
(a) seed notebook + papers + on-disk asset via `NotebooksStore.open` + direct
    file placement in `tmp_path/source-base/<slug>/`;
(b) build the tar in-memory (via the m6 `_build_export_manifest` +
    `_iter_safe_export_members` logic, OR via TestClient GET of the export route);
(c) write bytes to `tmp_path/<slug>.tar`;
(d) call `restore_bundle(tar_path, notebooks_base=target_base, db_path=target_db)`
    directly as a Python function;
(e) open a fresh `NotebooksStore(target_db)`, call `get_notebook(slug)` +
    `list_papers(slug)`, assert rows match; assert asset file exists.

The CLI wrapper is: `main(argv)` calls `run(tar_path, ...)` which calls
`asyncio.run(restore_bundle_async(...))`. The function `restore_bundle` is
testable without subprocess.

---

## Prior decisions and lessons

From git log (`c18fc82` most recent): m6 is complete. Key decisions from m6:
- USTAR (not PAX) is load-bearing for byte-determinism.
- `filter="data"` is already in use in `arxiv_fetch._safe_extract`.
- The `_safe_extract` pattern (explicit member loop + `extractall(filter="data")`)
  is the established precedent.

From MEMORY.md (injected):
- `notebook-surface-expansion-m6 — no-streaming-precedent-use-bytesio-tar`:
  build tar in-memory, return `Response` (not `StreamingResponse`).
- `notebook-surface-expansion-m6 — manifest-allowlist-omit-host-paths`:
  omit `lancedb_path` + `parsed_html_path`; allowlist confirmed.

From CLAUDE.md §4.7 (banned patterns):
- `assert` is BANNED — use `if ... raise NotebookError(...)`.
- No `BaseHTTPMiddleware`, no `anthropic` SDK at runtime.

From CLAUDE.md §8 (gotcha #1): `KMP_DUPLICATE_LIB_OK=TRUE` in `conftest.py` is
load-bearing; m7 does NOT touch `conftest.py` so this is not a risk.

**No conflict between the milestone brief and the codebase.** The m6 bundle
contract is exactly what the brief describes. The manifest shape and member
layout are confirmed above.

---

## External sources

### Python 3.12 tarfile filter API (PEP 706)

The `filter="data"` parameter was introduced by PEP 706 and backported to
3.9.17+, 3.10.12+, 3.11.4+. In Python 3.12 it is the default in security
patches. The "data" filter rejects: absolute paths, paths with `..`, symlinks,
hardlinks, device/FIFO members, setuid/setgid bits. It does NOT prevent
extraction — it sanitizes the `TarInfo` before extraction (strips ownership,
sets safe modes, rejects illegal names).

In Python 3.12.x the default is still `"fully_trusted"` (emits
`DeprecationWarning` if `filter=` is omitted). In Python 3.14 the default
becomes `"data"`. **m7 MUST pass `filter="data"` explicitly** — the project
runs 3.12 and will warn without it.

The existing `_safe_extract` in `arxiv_fetch.py` already uses
`tar.extractall(dest, filter="data")`. m7 inherits this pattern.

No MCP spec or Anthropic caching docs are relevant — m7 is a CLI tool, not an
MCP tool modification. No `server/tools.py` changes; no `EXPECTED_TOOL_SCHEMA_SHA256`
re-pin needed.

---

## Recommendation

**Implement `restore_bundle` as a standalone async function in
`tools/notebook_restore.py`, wrapped by a thin sync `run()` + `main()` CLI.**

Structure:
```python
async def restore_bundle_async(
    tar_path: Path,
    *,
    notebooks_base: Path,
    db_path: Path,
    force: bool = False,
) -> None:
    # 1. Open the tar, read manifest.json — validate format_version == 1
    # 2. validate_slug(manifest["slug"])
    # 3. _validate_tar_members(tar) — explicit loop: reject absolute, .., symlinks, hardlinks
    # 4. Check slug existence in NotebooksStore — refuse without --force
    # 5. Compute target_nb_dir = notebook_dir(slug, base=notebooks_base)
    # 6. Extract ONLY <slug>/* members into notebooks_base via tar.extractall(filter="data")
    # 7. --force: delete_notebook first (cascades papers)
    # 8. create_notebook(..., lancedb_path=str(notebook_lancedb_path(slug, base=notebooks_base)))
    # 9. For each paper in manifest: try add_paper / except IntegrityError: skip
```

```python
def run(tar_path: Path, *, notebooks_base: Path, db_path: Path, force: bool = False) -> int:
    try:
        asyncio.run(restore_bundle_async(tar_path, notebooks_base=notebooks_base,
                                          db_path=db_path, force=force))
        return 0
    except NotebookError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
```

Reasoning: This mirrors every other notebook CLI tool (pure `run()` returns int,
`main()` is thin argparse shell). The async function is directly importable for
tests — no subprocess needed. The `asyncio.run()` in `run()` is safe because
these CLIs are never called from within a running event loop.

**For papers idempotency:** use try/except `sqlite3.IntegrityError` around
`add_paper()` calls (simpler than adding a new method to `NotebooksStore`).

**For the malicious-tar test:** create a `tarfile.TarFile` in-memory with
pathological members (absolute path, `../escape`, symlink type) and assert
`restore_bundle` raises `NotebookError` before any file is written.

---

## Open questions

No open questions — implementation can proceed on the above recommendation.

The `add_paper_or_ignore` question is resolved: use try/except `IntegrityError`
around the existing `add_paper()` method. This avoids adding new methods to
`NotebooksStore` for a single-consumer use case.

---

## External writes the implementation will require

None — this milestone is purely local. `tools/notebook_restore.py` is a new
file, `tests/test_notebook_restore.py` is a new test file. No MCP surface
changes, no `EXPECTED_TOOL_SCHEMA_SHA256` re-pin, no infra changes, no git push
authorized here.
