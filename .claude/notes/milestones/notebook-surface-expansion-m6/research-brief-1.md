# Research Brief — notebook-surface-expansion-m6

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-29T19:30:00Z

## In-codebase context

### Route file + slug-validation pattern (verbatim)

`server/routes/notebooks.py` houses all notebook API routes. The invariant
pattern across every handler:

```python
try:
    validate_slug(slug)
except NotebookError as e:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=str(e),
    ) from e
```

Then 404 on unknown slug (e.g. from `list_papers`):

```python
if await store.get_notebook(slug) is None:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"notebook {slug!r} not found",
    )
```

The DI dependency pattern:

```python
async def export_notebook(
    slug: str,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008
) -> StreamingResponse:
```

**No existing `StreamingResponse`, `FileResponse`, or `application/x-tar`
precedent exists in `server/` source** (confirmed by grep — only references
are in middleware comments about `_StreamingResponse` internals). The
implementer must introduce `from fastapi.responses import StreamingResponse` as
a new import.

### `notebook_dir` + `NOTEBOOKS_BASE` (verbatim)

From `tools/_notebook_common.py`:

```python
NOTEBOOKS_BASE: Path = REPO_ROOT / "var" / "arxmcp" / "notebooks"

def notebook_dir(slug: str, *, base: Path | None = None) -> Path:
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

The containment check already enforces that `notebook_dir(slug)` stays under
`NOTEBOOKS_BASE`. The export handler must call `notebook_dir(slug)` to obtain
the root, and NOT walk any path outside it.

### Asset tree under `var/arxmcp/notebooks/<slug>/`

From the upload handler (`server/routes/notebooks.py`) and the milestone
context:

| Subdir | Contents | Milestone that created it |
|---|---|---|
| `ar5iv/` | ar5iv HTML files (`<flat_paper_id>.html`) | m8 |
| `pdfs/` | textbook PDFs (`<flat_paper_id>.pdf`) | textbook-ingest-m4 |
| `lancedb/` | per-notebook LanceDB dataset | notebook-retrieval-m1 |
| `parsed/` | MinerU + LaTeXML rendered output | textbook-ingest-m6 |

**Recommendation: include ALL of `<slug>/` recursively.** The brief says
"PDFs + ar5iv parsed HTML + the per-notebook LanceDB/chunks", which is the
entire notebook subtree. The containment check (calling `notebook_dir(slug)`)
guarantees the walk stays within bounds. An explicit allowlist would need
updates as new subdirs land; ALL-OF is safer for backup completeness and
simpler to implement.

### `NotebooksStore` dict shapes (verbatim)

`get_notebook(slug)` returns (from `notebooks_store.py` lines 318-327):

```python
{
    "slug": row[0], "display_name": row[1],
    "lancedb_path": row[2], "created_at": row[3],
    "notebook_kind": row[4],
    "parse_status": row[5],
    "parse_error": row[6],
    "parsed_html_path": row[7],
}
```

`list_papers(slug)` returns (lines 436):

```python
[{"paper_id": r[0], "added_at": r[1]} for r in rows]
```

### **FLAG — `lancedb_path` and `parsed_html_path` are internal host paths**

`lancedb_path` is an absolute host path (e.g.
`/Users/chris.dare/…/var/arxmcp/notebooks/my-nb/lancedb`). Including it in
the manifest is an **info-leak** — a backup/move bundle consumed on another
host has the wrong path burned in. The m4 D3/F4 discipline deliberately
omitted `lancedb_path` from the MCP resources surface for exactly this reason.
Similarly `parsed_html_path` is a host-absolute path.

**Recommendation: ALLOWLIST the manifest `notebook` dict** to safe fields
only:

```json
{
  "format_version": 1,
  "slug": "...",
  "notebook": {
    "slug": "...",
    "display_name": "...",
    "notebook_kind": "...",
    "created_at": "...",
    "parse_status": "..."
  },
  "papers": [
    {"paper_id": "...", "added_at": "..."}
  ]
}
```

Fields **omitted** from the allowlist: `lancedb_path`, `parsed_html_path`,
`parse_error`. The restore side (m7 of this epic, piece 2) can derive
`lancedb_path` from `notebook_dir(slug) / "lancedb"` in the target base.
`parse_error` is volatile HTML-escaped stderr; not useful in a backup.

### Determinism

Two requirements for byte-stable exports:

(a) **Manifest**: `json.dumps(manifest_dict, sort_keys=True, separators=(",", ":"))` — no spaces, keys sorted at every level, consistent across Python versions.

(b) **Tar member order + mtime zeroing**: iterate files via `sorted(nb_dir.rglob("*"))` (stable lexicographic order) and zero mtime on each `TarInfo` entry before adding (set `tarinfo.mtime = 0`). Without mtime zeroing the tar bytes drift between exports even with identical content.

**No existing deterministic-tar precedent in the codebase.** `tools/_notebook_common.py` imports `tarfile` (used in `fetch_raw_tex_if_missing` for arXiv eprint extraction), but does not produce a tar — it only reads one. `tools/arxiv_fetch.py` has a `_safe_extract` helper for reading tarballs. Neither writes a tar stream.

The recommended generator pattern (no in-memory buffer):

```python
import io, tarfile, json
from fastapi.responses import StreamingResponse

def _export_generator(nb_dir: Path, manifest_bytes: bytes):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w|") as tf:
        # 1. manifest.json first (stable, named member)
        info = tarfile.TarInfo(name="manifest.json")
        info.size = len(manifest_bytes)
        info.mtime = 0
        buf.seek(0); buf.truncate()
        tf.addfile(info, io.BytesIO(manifest_bytes))
        yield buf.getvalue(); buf.seek(0); buf.truncate()
        # 2. asset files in sorted order
        for fpath in sorted(nb_dir.rglob("*")):
            if not fpath.is_file():
                continue
            ...
```

Note: `mode="w|"` (streaming, no seeking) is correct for StreamingResponse
use; `mode="w"` requires seekable. However, a simpler fully-in-memory approach
(`mode="w"` into a `BytesIO`, yield at end) avoids chunking complexity and is
acceptable for notebook sizes (PDFs + LanceDB files, tens of MB at most for
a single notebook). **Recommendation: use in-memory BytesIO for simplicity**
(`tarfile.open(fileobj=buf, mode="w")`), seek to 0, then
`StreamingResponse(iter([buf.getvalue()]), ...)`. This guarantees sorted member
order and mtime=0 without needing incremental yields.

## Prior decisions and lessons

From git log (last 10 commits):
- `55832d7` — notebook-surface-expansion-m5 finalized (MCP initialize.instructions)
- `85077ca` — static MCP initialize.instructions (m5)
- `96cca0d`, `a2da7a3` — m4 complete (notebooks as MCP resources, 3M+1L critique)

**Key m4 precedent:** D3 and F4 in m4 established the allowlist-by-projection
discipline: `lancedb_path` was explicitly kept out of the MCP resource surface
to avoid info-leak. This brief extends that same discipline to the export
manifest.

**m8 file-naming pattern** (from `upload_paper`): on-disk filenames derive
from `flat_paper_id = paper_id.replace("/", "_").replace(":", "_")`, not from
`file.filename`. The export tar must include files using their actual on-disk
names (not reversed to `paper_id`).

**`NOTEBOOKS_BASE` monkeypatch pattern** (from `test_notebook_api.py`):

```python
@pytest.fixture
def notebooks_base(tmp_path, monkeypatch):
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base, raising=False)
    return base
```

The `raising=False` is needed because `notebooks_module` doesn't always
re-export `NOTEBOOKS_BASE` directly. The export handler inherits the same
requirement.

No adjacent milestone state.json files contain relevant prior art for
tar/streaming. The restic backup work (notebook-ops-hardening-m1) uses shell
scripts, not Python tarfile.

## External sources

This milestone does not touch the MCP tool surface, tool schema, or prompt
cache layer. Per `07-multi-agent-caching.md` §"Property 1: Tool definitions
are byte-stable": **no `EXPECTED_TOOL_SCHEMA_SHA256` re-pinning required** —
the new route is a plain FastAPI GET, not an MCP tool registration.

The `StreamingResponse` API is standard Starlette/FastAPI. No external docs
needed; the pattern is `from fastapi.responses import StreamingResponse` with
`media_type` and `headers` kwargs.

Python `tarfile` stdlib: `tarfile.TarInfo` accepts `mtime=0` to zero the
timestamp. `tarfile.open(fileobj=buf, mode="w")` writes an uncompressed tar
to a BytesIO. No external deps required.

## Recommendation

**Implement the export handler as a single synchronous tar-build into a
`BytesIO`, then return it as a `StreamingResponse`.** Specifically:

1. `validate_slug` → 422 on fail (exact pattern from `delete_notebook`).
2. `await store.get_notebook(slug)` → 404 if None.
3. `nb_dir = notebook_dir(slug)` → containment check already baked in.
4. `await store.list_papers(slug)` → paper rows for manifest.
5. Build manifest dict with ALLOWLISTED `notebook` fields (slug, display_name,
   notebook_kind, created_at, parse_status — NO lancedb_path, parsed_html_path,
   parse_error). Serialize with `json.dumps(..., sort_keys=True, separators=(",", ":"))`.
6. Build tar in-memory: `buf = BytesIO(); tf = tarfile.open(fileobj=buf, mode="w")`.
   Add `manifest.json` first (TarInfo with mtime=0). Then add asset files in
   `sorted(nb_dir.rglob("*"))` order, each with `tarinfo.mtime = 0`.
7. Return `StreamingResponse(iter([buf.getvalue()]), media_type="application/x-tar",
   headers={"Content-Disposition": f'attachment; filename="{slug}.tar"})`.

Write tests in a NEW `tests/test_notebook_export.py` (the export is
substantial enough to warrant its own file; the m2 `test_notebook_rename_delete.py`
precedent shows new feature-specific test files are preferred). Mirror the
`client` fixture from `test_notebook_api.py` exactly — same
`asyncio.new_event_loop()` + `monkeypatch` pattern.

## Open questions

**No open questions — implementation can proceed on the above recommendation.**

The one design choice that needed resolution (lancedb_path / parsed_html_path
in the manifest) is resolved: OMIT both, ALLOWLIST the safe fields. This
mirrors the m4 D3/F4 discipline already established.

## External writes the implementation will require

None — this milestone is purely local.
- New route in `server/routes/notebooks.py`
- New test file `tests/test_notebook_export.py`
- No MCP tool changes → no tool-schema re-pinning
- No git push, no infra mutation, no ticket
