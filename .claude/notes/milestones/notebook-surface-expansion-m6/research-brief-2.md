# Research Brief — notebook-surface-expansion-m6

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-29T19:30:00Z

---

## In-codebase context

### Security and path-containment constraints

From `08-security-observability-ops.md` Threat 1 (load-bearing, verbatim):

> **Threat 1: Path traversal via `paper_id`** — Tool arguments come from LLM output.
> An LLM that has been prompt-injected by something it read in an arXiv abstract could
> pass `paper_id="../../../etc/passwd"`. **Mitigation:** strict regex on every arxiv ID
> input. Reject at the JSON-Schema level so it never reaches handlers.

This threat class extends directly to the export route: the `slug` path parameter is
the vector for notebook-directory traversal. The existing two-layer defense is
**already shipped** and must be reused verbatim:

1. `tools._notebook_common.validate_slug(slug)` — slug regex `^[a-z][a-z0-9-]{2,30}$`
   (rejects `..`, slashes, shell metacharacters, uppercase, leading hyphen).
2. `tools._notebook_common.notebook_dir(slug)` — resolves the path, checks for symlinks
   at the slug name (`is_symlink()` before `.resolve()`), then verifies containment via
   `target.relative_to(nb_base)`.

From `_notebook_common.py` lines 102–123 (load-bearing, verbatim excerpt):
```python
def notebook_dir(slug, *, base=None):
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

**This is the required entrypoint for all path work in the export route.**

### Route placement and middleware inheritance

The export route must live under `/ui/api/notebooks/{slug}/export` in
`server/routes/notebooks.py` (same file as all other notebook API routes). From
`server/main.py` (load-bearing):

```python
app.add_middleware(SecFetchSiteMiddleware, exempt_prefixes=("/ui",))
app.include_router(notebooks_router, prefix="/ui/api")
```

The `/ui` carve-out on `SecFetchSiteMiddleware` means `same-origin` XHRs from
`/ui/` pages are permitted — a browser GET from `http://127.0.0.1:7733/ui/`
to `/ui/api/notebooks/{slug}/export` works. Cross-site is blocked. Origin/Host
loopback validation still applies (no additional wiring needed).

**CRITICAL CONFLICT — BodySizeCapMiddleware applies to `/ui/api/*`:**
From `server/main.py` lines 94–120, the 256 KB response cap (`_BYTE_CAP_EXEMPT_PREFIXES`)
exempts `/healthz`, `/readyz`, `/status`, `/metrics`, `/mcp`, and `/ui/static` — but
NOT `/ui/api/notebooks/{slug}/export`. A notebook tar will EXCEED 256 KB for any
notebook with even one uploaded file (PDFs and ar5iv HTML routinely exceed this).

**The implementer MUST add `/ui/api/notebooks` (or at minimum `/ui/api/notebooks/`
followed by `export` detection) to `_BYTE_CAP_EXEMPT_PREFIXES`, OR use a suffix-based
exemption for the export path specifically.**

Recommended exemption: add `"/ui/api/notebooks"` to `_BYTE_CAP_EXEMPT_PREFIXES` with a
comment explaining the export stream is the motivating case. (The other `/ui/api/notebooks`
routes return small JSON bodies, so widening the exemption to the whole subtree is safe —
parallel to the existing `/ui/static` reasoning in the comments.)

### Manifest data sources

`NotebooksStore.get_notebook(slug)` returns a `dict[str, str] | None` with keys:
`slug, display_name, lancedb_path, created_at, notebook_kind, parse_status,
parse_error, parsed_html_path`.

`NotebooksStore.list_papers(slug)` returns `list[dict[str, str]]` with keys:
`paper_id, added_at` (ordered `added_at DESC`).

**INFO-LEAK RISK:** `lancedb_path` and `parsed_html_path` are absolute host paths
(e.g. `/Users/chris.dare/Personal/SourceCode/arXMCP/var/arxmcp/notebooks/mybook/lancedb`).
Including them in the manifest leaks the operator's filesystem layout to anyone who unpacks
the tar. These fields MUST be OMITTED from the manifest — m7 reconstructs them from
`NOTEBOOKS_BASE / slug / "lancedb"` via `notebook_lancedb_path()` after import.

Allowlisted manifest notebook fields: `slug`, `display_name`, `created_at`,
`notebook_kind`, `parse_status`, `parse_error`. Omit: `lancedb_path`,
`parsed_html_path`.

---

## Prior decisions and lessons

### Path-containment discipline (m6 rect F3 — notebook_dir)

From git log and `_notebook_common.py` docstring: "Closes F3 (HIGH) from the m6
critique: if `nb_base/<slug>` IS a symlink (regardless of where it points), refuse
to operate on it." This is a SHIPPED defense that the export route must mirror for
EACH file under the notebook directory during the tar-building preflight.

### BodySizeCapMiddleware is pure-ASGI, buffers before forwarding

From `server/main.py` lines 145–153: the cap BUFFERS the first response body chunk
before forwarding downstream. If the export returns a BytesIO-backed response with
`Content-Length` set, the middleware will try to buffer it against the 256 KB cap.
A 10 MB tar will trigger a 413. **The export path must be exempted.**

### assert-is-banned pattern

CLAUDE.md §4.7: "`assert` is BANNED for invariants — Python `-O` strips them. Use
`if … raise RuntimeError(…)` instead." The export handler's preflight checks must
use `if … raise NotebookError(…)` or `HTTPException` at the route boundary.

### Doc placement

No new Markdown outside `.claude/` — test file docstrings are fine; do not create
`server/routes/export_spec.md` or similar.

---

## External sources

### Python `tarfile` — determinism recipe

From Python 3.12 tarfile docs (https://docs.python.org/3/library/tarfile.html):

- **Format constants**: `USTAR_FORMAT` (POSIX.1-1988, max filename 256 chars, max
  linkname 100 chars, max file size 8 GiB). `PAX_FORMAT` is the current default —
  it stores timestamps in microseconds via extended headers, creating byte drift
  between exports even when `mtime=0` is set on TarInfo because PAX headers include
  a `mtime` extended header in floating-point format. `GNU_FORMAT` stores `mtime` as
  a 32-bit integer but adds `GNUTYPE_LONGNAME` extension headers for long filenames.

- **RECOMMENDATION: use `tarfile.USTAR_FORMAT`** for byte-deterministic output.
  USTAR stores `mtime` as a fixed-width 12-character octal integer in the 512-byte
  header block — no floating-point, no extended headers. Slug-relative paths for a
  notebook are well under 256 chars. Files under the notebook dir are regular files
  or directories — no long-name extension headers needed.

- **TarInfo attributes that produce byte drift if not normalized** (complete list):
  - `mtime` — filesystem timestamp; varies between exports. Set `mtime=0`.
  - `uid`, `gid` — OS user/group IDs; vary across machines. Set both to `0`.
  - `uname`, `gname` — user/group name strings (100-char field in USTAR). Set both to `""`.
  - `mode` — file permission bits; varies across platforms. Normalize to `0o644` for files.
  - Member ORDER — `tarfile.add()` with recursion is NOT guaranteed sorted in all versions
    (docs: "Recursion adds entries in sorted order" only since Python 3.7). Use explicit
    sorted enumeration with `pathlib.Path.rglob("*")` sorted by `str(p)` (or `p.name`).
  - `type` (`REGTYPE` vs `SYMTYPE`, etc.) — symlinks must be detected and REFUSED
    (not added as `SYMTYPE` members), not silently followed.

- **Deterministic recipe** (construct each TarInfo manually, never use `gettarinfo`):
  ```python
  import io, tarfile
  buf = io.BytesIO()
  with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tar:
      # manifest.json first (top-level, not slug-prefixed)
      manifest_bytes = json.dumps(manifest, sort_keys=True, ensure_ascii=True,
                                  indent=None, separators=(",", ":")).encode()
      ti = tarfile.TarInfo(name="manifest.json")
      ti.size = len(manifest_bytes)
      ti.mtime = 0; ti.uid = 0; ti.gid = 0; ti.uname = ""; ti.gname = ""
      ti.mode = 0o644; ti.type = tarfile.REGTYPE
      tar.addfile(ti, io.BytesIO(manifest_bytes))
      # asset files — sorted by slug-relative name
      for path in sorted(nb_dir.rglob("*"), key=lambda p: str(p.relative_to(nb_dir))):
          if not path.is_file():  # skip dirs, symlinks, FIFOs
              continue
          rel = path.relative_to(nb_dir)
          member_name = f"{slug}/{rel}"  # e.g. "mybook/ar5iv/2401.01234.html"
          data = path.read_bytes()
          ti = tarfile.TarInfo(name=member_name)
          ti.size = len(data); ti.mtime = 0; ti.uid = 0; ti.gid = 0
          ti.uname = ""; ti.gname = ""; ti.mode = 0o644; ti.type = tarfile.REGTYPE
          tar.addfile(ti, io.BytesIO(data))
  buf.seek(0)
  content = buf.read()
  ```

### Security — dangerous tar member types

Six classes the preflight MUST refuse or drop before writing:

1. **`..` or absolute paths in member names** — m6 uses slug-relative names (`<slug>/...`)
   constructed from `path.relative_to(nb_dir)`. Never call `tar.add(path)` directly;
   always construct the name manually. This eliminates the path-traversal class.

2. **Symlinks** (`SYMTYPE`) — `path.is_file()` returns False for symlinks pointing to
   directories, but True for symlinks pointing to files. Use `path.is_symlink()` FIRST:
   if True, skip (do not embed as `SYMTYPE`). Additionally, verify resolved path stays
   under `nb_dir` (mirror of m6 F3 discipline from `notebook_dir`):
   ```python
   if path.is_symlink() or not path.resolve().is_relative_to(nb_dir.resolve()):
       continue  # skip
   ```
   This catches symlinks that escape the notebook dir.

3. **Hardlinks** (`LNKTYPE`) — `tarfile.add()` can detect hardlinks and emit
   `LNKTYPE`. By constructing TarInfo manually with `type=REGTYPE` and always reading
   the file data via `path.read_bytes()`, hardlinks are treated as independent copies —
   LNKTYPE is never emitted.

4. **Device files and FIFOs** (`CHRTYPE`, `BLKTYPE`, `FIFOTYPE`) — `path.is_file()`
   returns False for all of these. The `if not path.is_file(): continue` guard covers them.

5. **Info-leak in manifest: absolute host paths** — `lancedb_path` and `parsed_html_path`
   from `get_notebook()` are absolute. OMIT these fields from the manifest dict. m7
   derives them from the unpacked bundle's `<slug>/` directory structure.

6. **Member name max length + control characters** — USTAR limits member names to 255
   characters. Slug (`^[a-z][a-z0-9-]{2,30}$`) + `/` + relative path under notebook dir.
   Notebook paths are operator-controlled file/directory names. Guard: if
   `len(member_name) > 255` or any non-printable byte in `member_name`, SKIP that member
   and emit a WARNING log (do not abort the export; a partial tar is better than a 500).

### Streaming semantics

`fastapi.responses.StreamingResponse` takes a generator yielding `bytes`. The correct
approach for m6 (bounded, single-operator, single-notebook, loopback-only):

**RECOMMEND: write the full tar into a `BytesIO`, then return as a single-chunk
`Response` (not `StreamingResponse`) with `Content-Length` set explicitly.**

Rationale: `tarfile` is synchronous. Streaming it incrementally requires thread executor
overhead. For a single notebook (bounded by on-disk assets — PDFs cap at 200 MB per the
upload handler, but a TYPICAL notebook has ≤10 papers × ≤5 MB each = ≤50 MB), BytesIO
is correct. `Content-Length` set from `len(content)` means the client knows the total
size up front and the browser download dialog shows progress.

**BodySizeCapMiddleware MUST be exempted for this path** (see CRITICAL CONFLICT above).
Without the exemption, the cap middleware will buffer the full BytesIO response in memory
anyway (to check the cap), then emit a 413. The net effect is double memory use and a
broken download — worse than the exemption.

---

## Recommendation

Implement the export route as a `GET /ui/api/notebooks/{slug}/export` handler appended to
`server/routes/notebooks.py`, using the following recipe:

1. `validate_slug(slug)` → 422 on failure.
2. `get_notebook(slug)` → 404 if None.
3. `nb_dir = notebook_dir(slug)` — uses the two-layer path-safety contract already
   shipped; raises `NotebookError` (translate to 422) on symlink or containment failure.
4. Build the manifest dict with ALLOWLISTED fields only (omit `lancedb_path`,
   `parsed_html_path`); serialize with `json.dumps(sort_keys=True)`.
5. Build the tar into a `BytesIO` using `tarfile.USTAR_FORMAT`, manually-constructed
   `TarInfo` objects with `mtime=0, uid=0, gid=0, uname="", gname="", mode=0o644,
   type=REGTYPE`, and members in sorted order. Preflight each file: skip symlinks,
   skip paths that don't resolve under `nb_dir`, skip names >255 chars or with
   control chars, log WARNINGs on skipped files.
6. Add the `manifest.json` member FIRST (top-level, no slug prefix).
7. Add asset files as `<slug>/<relative-path>` members in `sorted(...rglob("*"))` order.
8. Return `Response(content=buf.read(), media_type="application/x-tar",
   headers={"Content-Disposition": f"attachment; filename={slug}.tar",
             "Content-Length": str(len(content))})`.
9. Add `"/ui/api/notebooks"` to `_BYTE_CAP_EXEMPT_PREFIXES` in `server/main.py` with an
   explanatory comment.

**USTAR** is the format choice — no PAX extended timestamp headers, no GNU long-name
headers for the expected slug-length paths. Byte-stable across Python versions and
platforms.

---

## Open questions

1. **manifest `format_version` field**: The brief does not specify it, but m7 will need
   a version to detect format incompatibility. Recommend adding `"format_version": 1` as
   the first key in the manifest. This is an additive m6 decision that m7 MUST rely on —
   the implementer should resolve this in the implementation comment and make it explicit.
   There is a clear answer (add it); this is not a blocker.

2. **`_BYTE_CAP_EXEMPT_PREFIXES` change scope**: Adding `"/ui/api/notebooks"` exempts ALL
   notebook API routes from the 256 KB response cap. The other notebook API routes return
   small JSON (list of notebooks, list of papers). This is safe and is the recommended
   approach. If a security reviewer objects, the alternative is a more specific path check
   (`path.endswith("/export")`), but the existing code uses prefix matching (not suffix),
   so this would require a pattern change in `_is_exempt_path`. Recommend the simpler
   prefix addition.

---

## External writes the implementation will require

None — this milestone is purely local. No git push, no PR, no ticket, no infra mutation,
no third-party API call.

---

## Failure-mode analysis

| # | Trigger | Symptom | Mitigation |
|---|---|---|---|
| FM-a | `mtime`/`uid`/`gid`/member-order not normalized | Two exports of the same notebook produce different tar bytes — byte-stability test fails | USTAR format + explicit TarInfo construction with `mtime=0, uid=0, gid=0` + sorted member order |
| FM-b | Manifest naïvely dumps full `get_notebook()` row | `lancedb_path` and `parsed_html_path` (absolute host paths) appear in `manifest.json` — info-leak | ALLOWLIST manifest fields: `slug, display_name, created_at, notebook_kind, parse_status, parse_error`; OMIT path fields |
| FM-c | Member name constructed from `path` directly (e.g. `tar.add(path)`) | Absolute paths in tar members (zip-slip class on m7 untar side) | ALWAYS construct name as `f"{slug}/{path.relative_to(nb_dir)}"` |
| FM-d | Symlink under `<slug>/` is embedded as `SYMTYPE` member | m7 or third-party untar extracts the symlink, potentially pointing outside sandbox | `if path.is_symlink(): continue` BEFORE `is_file()` check; also verify `path.resolve().is_relative_to(nb_dir.resolve())` |
| FM-e | Large notebook (200 MB PDF × 10 papers = 2 GB BytesIO) | Process OOM or very slow response | ACCEPTED for v1: single-operator loopback-only; document 200 MB per-file upload cap as the effective bound. Add a WARN log if total tar size >100 MB. |
| FM-f | Ingest mid-flight while export runs | Partial LanceDB files included in tar | ACCEPTED partial snapshot for v1; document. The tar represents a point-in-time snapshot. Do not block on ingest completion. |
| FM-g | `_BYTE_CAP_EXEMPT_PREFIXES` not updated | `BodySizeCapMiddleware` buffers the tar and emits 413 for any export >256 KB | Add `"/ui/api/notebooks"` to `_BYTE_CAP_EXEMPT_PREFIXES` in `server/main.py`. |
| FM-h | Cross-notebook manifest leak (all slugs serialized instead of one) | Manifest includes rows from other notebooks | `get_notebook(slug)` + `list_papers(slug)` are already scoped to one slug; do NOT call `list_notebooks()` in the export handler |
