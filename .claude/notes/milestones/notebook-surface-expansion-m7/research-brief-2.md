# Research Brief — notebook-surface-expansion-m7

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-29T20:05:00Z

## In-codebase context

### m6 bundle contract — what the consumer receives

From `implementation-summary.md` (m6):

> Bundle layout: `manifest.json` at the root + assets under `<slug>/<rel>` members
> (slug-prefixed, relative paths constructed manually — never from `path` directly;
> eliminates the absolute-path / `..` class on the m7 untar side).

Format: `tarfile.USTAR_FORMAT`. `_EXPORT_MANIFEST_FORMAT_VERSION = 1`. The manifest
contains `format_version`, `slug`, `display_name`, `notebook_kind`, `created_at`,
`parse_status`, and a `papers` list (each entry: `paper_id`, `added_at`). It OMITS
`lancedb_path`, `parsed_html_path`, `parse_error`.

The m6 producer runs `_iter_safe_export_members` as a preflight that SKIPS symlinks
and paths escaping `notebook_dir`. The m7 consumer MUST NOT trust this: a bundle
could have been created by a hostile source, tampered in transit, or be a hand-crafted
attack tar.

### `validate_slug` and `notebook_dir` — existing security seam

From `tools/_notebook_common.py` (docstring, verbatim):

> The slug regex (`^[a-z][a-z0-9-]{2,30}$`) is the FIRST-LINE defense against path
> traversal — see Threat 1 in `.claude/notes/08-security-observability-ops.md` and
> FM-2 in the synthesis. A path containment check at `(notebooks_base / slug).resolve()`
> is the belt-and-braces secondary check.

`notebook_dir` refuses symlinks at the slug directory level. m7 must call
`validate_slug(manifest["slug"])` before constructing any paths.

### `notebooks_store.py` — idempotent DB insert pattern

`create_notebook` raises `sqlite3.IntegrityError` on duplicate slug — this is the
409-conflict path. For idempotent restore: the implementer should run
`DELETE FROM notebooks WHERE slug = ?` followed by `INSERT`, wrapped in a single
transaction, guarded by a check that `--force` was supplied (or the slug does not
already exist). `delete_notebook` cascades to `notebook_papers` via FK. `add_paper`
raises on duplicate `(slug, paper_id)` — for restore, use bulk INSERT within the
same transaction after the notebooks row is established.

The DB is sync-over-async (`asyncio.to_thread`). `tools/notebook_restore.py` is a
CLI (not a FastAPI route), so it should open a DIRECT `sqlite3` connection with
`PRAGMA foreign_keys = ON; PRAGMA journal_mode = WAL; PRAGMA synchronous = FULL;`
mirroring `notebooks_store.py`'s `_open_sync`.

### `notebook_purge.py` — precedent for destructive CLIs

`notebook_purge.py` uses an interactive typed-slug prompt unless `--force` is passed.
It still emits a WARN under `--force` (the WARN is not silenced). This is the
project precedent for destructive CLI gates.

### Threat 1 (path traversal) in `08-security-observability-ops.md`

> **Threat 1: Path traversal via `paper_id`** — Tool arguments come from LLM output.
> An LLM that has been prompt-injected... could pass `paper_id="../../../etc/passwd"`.
> **Mitigation:** strict regex on every arxiv ID input.

The note does NOT mention tar extraction specifically; it covers path traversal via
LLM-controlled string inputs. Tar extraction is the m7-specific threat surface.
The slug regex + `notebook_dir` containment check (Threat 1 mitigations) ARE the
direct analogs for the tar-member-name containment check.

### `NotebooksStore` schema — fields needed for restore

Schema (from docstring, verbatim):
```sql
CREATE TABLE notebooks (
    slug           TEXT PRIMARY KEY,
    display_name   TEXT NOT NULL DEFAULT '',
    lancedb_path   TEXT NOT NULL,
    created_at     TEXT NOT NULL  -- ISO-8601 UTC
);
CREATE TABLE notebook_papers (
    slug           TEXT NOT NULL,
    paper_id       TEXT NOT NULL,
    added_at       TEXT NOT NULL,
    PRIMARY KEY (slug, paper_id),
    FOREIGN KEY (slug) REFERENCES notebooks(slug) ON DELETE CASCADE
);
```

`lancedb_path` is required (NOT NULL). The manifest omits it — the restore tool must
reconstruct it as `str(notebook_dir(slug, base=notebooks_base) / "lancedb")`, NOT
re-use any path embedded in the bundle (info-leak class, m4 D3).

**No MCP tool surface change.** `tools/notebook_restore.py` is a CLI only; no
`ALL_TOOLS` change; no `EXPECTED_TOOL_SCHEMA_SHA256` re-pin needed.

## Prior decisions and lessons

Recent commits confirm m6 shipped (`c18fc82`). The m7 milestone directory already
has `state.json` at `research-running`.

**Banned patterns:** `assert` is banned — use `if … raise RuntimeError(…)`. The
`tools/notebook_purge.py` uses `NotebookError(RuntimeError)` throughout; m7 should
follow the same pattern.

**No MCP-tool-schema re-pin needed** (CLI only, no `ALL_TOOLS` change).

**`KMP_DUPLICATE_LIB_OK=TRUE` in `tests/conftest.py`** — this milestone adds CLI
tests only; no risk of removing it.

## External sources

### PEP 706 — tarfile extraction filters

From https://peps.python.org/pep-0706/ (verbatim):

> The `'data'` filter enforces: Refuse to extract links (hard or soft) that link to
> absolute paths; refuse to extract links (hard or soft) which end up linking to a
> path outside of the destination; refuse to extract device files (including pipes);
> ignore user and group info (set `uid`, `gid`, `uname`, `gname` to `None`).

> For additional safety, PEP 706 recommends users "do additional checks" including:
> extracting to new empty directories; using external resource limits; checking
> filenames against allowlists; verifying expected file extensions; limiting extracted
> file counts and sizes; detecting case-insensitive filesystem shadowing.

### Python 3.12 `tarfile` docs — `data_filter`

From https://docs.python.org/3/library/tarfile.html#tarfile.data_filter (verbatim):

> "Even with `filter='data'`, *tarfile* is not suited for extracting untrusted files
> without prior inspection. Among other issues, the pre-defined filters do not prevent
> denial-of-service attacks."

Exception table (verbatim from docs):
| Violation | Exception |
|---|---|
| Absolute path | `tarfile.AbsolutePathError` |
| Path outside destination | `tarfile.OutsideDestinationError` |
| Absolute symlink | `tarfile.AbsoluteLinkError` |
| Symlink outside destination | `tarfile.LinkOutsideDestinationError` |
| Device/pipe/special file | `tarfile.SpecialFileError` |

Recommended invocation:
```python
with tarfile.open(bundle_path) as tar:
    tar.extractall(path=dest, filter="data")
```

The `filter="data"` parameter was added in Python 3.12 (PEP 706). The project
requires Python ≥ 3.11 (`pyproject.toml`). **Flag:** at Python 3.11 the `filter`
kwarg exists but raises `DeprecationWarning` if omitted (backport), while 3.12+
accepts it cleanly. The project's `uv run` environment targets 3.12 — verify
`python_requires` in `pyproject.toml` is `>=3.12` or add a version guard.

## Recommendation

**Implement `tools/notebook_restore.py` with two security layers and conservative
`--force` semantics.**

**Layer 1 — pre-extraction validation (`_safe_member` pass):** Before calling
`tar.extractall`, iterate `tar.getmembers()` and reject the ENTIRE restore (raise +
exit non-zero, extract nothing) if ANY member violates:
- `tarinfo.isabs()` — absolute path;
- `..` in `tarinfo.name` before or after `pathlib.PurePosixPath(tarinfo.name).parts`;
- `tarinfo.issym()` or `tarinfo.islnk()` — symlink or hardlink;
- `tarinfo.isdev()` or `tarinfo.isfifo()` — device or FIFO;
- member name does not start with `<slug>/` AND does not equal `manifest.json` exactly
  (after PurePosixPath normalization);
- `os.path.normpath(tarinfo.name)` does not start with `<slug>/` (post-normalization
  double-check).

**Layer 2 — `filter="data"` on extractall:** After the pre-pass, call
`tar.extractall(path=dest, filter="data")`. This is belt-and-braces; the pre-pass is
the primary gate.

**`--force` semantics:** `--force` permits the DB re-insert to overwrite an existing
slug (DELETE existing notebooks row + cascade to notebook_papers, then INSERT).
`--force` does NOT allow extracting on top of an existing `<slug>/` directory — if
`notebook_dir(slug, base=notebooks_base)` already exists on disk, refuse with a clear
error even under `--force`. Require the operator to run `tools/notebook_purge.py
<slug>` first. This separation keeps each operation's security surface tractable.

**DB re-insert:** Use a direct `sqlite3` connection (not `NotebooksStore` async) with
`PRAGMA foreign_keys = ON; PRAGMA journal_mode = WAL; PRAGMA synchronous = FULL;`. Run
the delete+insert+papers bulk-insert in a single `BEGIN EXCLUSIVE` transaction. If the
transaction raises, the on-disk assets (already extracted) are orphaned — the error
message must tell the operator to run `tools/notebook_purge.py <slug> --force` to clean
up.

**`_RESTORE_SUPPORTED_FORMATS = (1,)`:** read `manifest["format_version"]`; reject if
not in `_RESTORE_SUPPORTED_FORMATS`.

**Test structure:** (a) happy-path round-trip using m6's export route + restore into
`tmp_path`; (b) malicious-tar-member test — construct a tar with an `../escape` member,
assert restore exits non-zero and no files written outside tmp; (c) no-clobber-without-
force (existing slug dir → reject); (d) `--force` on DB-only clobber (dir absent, slug
in DB → succeeds with `--force`).

**Determinism:** the round-trip test should assert functional equivalence: notebook
exists in DB, papers list matches manifest's papers list, a known asset file's bytes
match. Do NOT assert bit-identical DB rows (timestamps may differ on re-import).

## Open questions

1. **Python version guard for `filter="data"`:** does the project's `pyproject.toml`
   pin `python_requires >= "3.12"` or only `>= "3.11"`? If 3.11, add
   `if sys.version_info < (3, 12): raise RuntimeError("Python 3.12+ required for
   tarfile data filter")` at the top of the script. Check `pyproject.toml` before
   implementing.

2. **WAL checkpoint before restore DB write:** `notebooks.db` runs in WAL mode. A
   CLI tool that opens a DIRECT `sqlite3` connection while the server is also open
   (both writing) risks a SQLITE_BUSY. The `notebook_purge.py` precedent opens
   direct `sqlite3` without a checkpoint. For restore, a `BEGIN EXCLUSIVE` with
   retry loop (3 retries, 200ms sleep) is sufficient — no separate checkpoint
   script needed. Confirm this is adequate for the implementation.

## External writes the implementation will require

None — this milestone is purely local.
