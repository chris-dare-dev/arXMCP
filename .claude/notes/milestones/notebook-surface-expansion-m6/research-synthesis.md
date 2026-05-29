# Research Synthesis — notebook-surface-expansion-m6

**Milestone:** `GET /ui/api/notebooks/{slug}/export` streams a deterministic,
slug-only tar (assets + a manifest) for backup/move. (Epic e3, piece 1/2.)
**Mode:** standard (2× Sonnet). Both `ok`; one decisive divergence resolved (the
BodySizeCap response cap). 0 external writes.
**Implementation path:** INLINE — 3 files (the route + the middleware exemption +
a new test file), ~400 LOC.

---

## Load-bearing decisions

### D1 — BodySizeCapMiddleware caps RESPONSES — the export path MUST be exempted (brief-2 over brief-1)

The briefs disagreed. Confirmed by `server/main.py:90` ("Body-size middleware
**(256 KB cap on tool responses)** — pure ASGI") and the middleware body (line
197: "if body_bytes > self.byte_cap: … abort 413"): the cap is a **response**
cap. Without an exemption, every non-trivial export (a single PDF can be 10 MB+)
would 413.

**Resolution: narrow suffix-based exemption, NOT broad subtree exemption.**
Brief-2 recommended adding `/ui/api/notebooks` to `_BYTE_CAP_EXEMPT_PREFIXES`,
but that exempts every other notebook API response too (`list`, `get`, the htmx
fragments) — wider than needed, removing defense-in-depth on routes that return
small JSON. Instead, extend `_is_exempt_path` (or add a sibling
`_BYTE_CAP_EXEMPT_SUFFIXES` / a single inline check) to exempt **specifically**
paths matching `path.startswith("/ui/api/notebooks/") AND path.endswith("/export")`
— a single export route, smallest possible widening, every other response
remains capped.

### D2 — Deterministic tar recipe: USTAR + manual `TarInfo` + sorted members

Both briefs agree (brief-2 has the full Python-docs-grounded recipe). Use
`tarfile.open(fileobj=BytesIO(), mode="w", format=tarfile.USTAR_FORMAT)`
(NOT the default `PAX_FORMAT` — PAX writes floating-point microsecond mtimes in
extended headers that drift across exports even with `TarInfo.mtime=0`).
Construct EVERY `TarInfo` manually (NEVER `tarfile.gettarinfo`) and normalize:
- `mtime = 0`, `uid = 0`, `gid = 0`, `uname = ""`, `gname = ""`
- `mode = 0o644` for regular files, `type = tarfile.REGTYPE` always
- Members added in `sorted(nb_dir.rglob("*"), key=lambda p: str(p.relative_to(nb_dir)))` order
- Member names are `f"{slug}/{rel}"` (slug-prefixed, relative-path constructed),
  NEVER from `path` directly (eliminates the absolute-path / `..` class on the
  m7 untar side).

### D3 — Manifest allowlist (mirrors m4 D3/F4 lancedb_path-omission discipline)

Top-level shape (sorted keys at every level — `json.dumps(sort_keys=True,
separators=(",", ":"), ensure_ascii=True)`):
```json
{
  "format_version": 1,
  "notebook": {"slug","display_name","notebook_kind","created_at","parse_status"},
  "papers": [{"paper_id","added_at"}, …],
  "slug": "..."
}
```
**OMIT from the `notebook` dict:** `lancedb_path` + `parsed_html_path` (absolute
host paths — m4 D3 info-leak class) AND `parse_error` (HTML-escaped stderr;
notebook-internal state, possibly leaks parser paths in a stack-trace fragment;
not useful for backup/move). brief-1 excludes `parse_error`; brief-2 included it
— **brief-1 wins** (smaller leak surface; m7 restore doesn't need it). `papers`
is sorted by `paper_id` (independent of `list_papers`'s `added_at DESC` order)
for cross-export byte-stability.

### D4 — Bundle layout: `manifest.json` at root, assets under `<slug>/...`

Single top-level `manifest.json` (so m7 can peek the manifest pre-extraction to
detect the slug + `format_version`) + everything else under `<slug>/<rel>`
members. Both briefs agree. m7 untars `<slug>/...` into the target
`var/arxmcp/notebooks/<slug>/`.

### D5 — Member preflight: skip-not-abort

Before adding each on-disk member, run the safety preflight (mirrors m4-rect F2's
discipline of "return the safe answer, log the security signal"):
```python
if path.is_symlink():               # don't embed symlinks
    logger.warning(…); continue
if not path.is_file():               # skip dirs / devices / FIFOs
    continue
if not path.resolve().is_relative_to(nb_dir.resolve()):  # containment beyond notebook_dir's check
    logger.warning(…); continue
if len(member_name) > 255 or any(0 < ord(c) < 0x20 for c in member_name):
    logger.warning(…); continue
```
Skip + log a WARNING; don't abort the export (a partial bundle is better than
500-ing — m4-rect F2 discipline). The result is byte-deterministic across
exports because the same on-disk set produces the same skipped/included split.

### D6 — Return as `Response` (NOT `StreamingResponse`)

Both briefs converge here. The tar is bounded (single notebook, loopback-only)
and `tarfile` is synchronous. Build into a `BytesIO`, then
`Response(content=buf.getvalue(), media_type="application/x-tar", headers={
"Content-Disposition": f'attachment; filename="{slug}.tar"',
"Content-Length": str(len(content))})`. Honest `Content-Length` lets the browser
show download progress.

### D7 — Tests (`tests/test_notebook_export.py`, new)

Mirror the m2 `tests/test_notebook_rename_delete.py` private-loop+REST-seed
pattern:
- happy-path: a seeded notebook with ≥1 on-disk asset → 200, `Content-Type:
  application/x-tar`, `Content-Disposition` filename, tar opens, manifest member
  present, manifest shape matches D3 (incl. omits asserts: `lancedb_path` /
  `parsed_html_path` / `parse_error` absent), asset member present at
  `<slug>/<rel>`.
- **byte-deterministic**: two exports of the SAME notebook+assets → identical
  bytes (the load-bearing determinism guard; if it fails, a TarInfo field
  drifted).
- **no cross-notebook leak**: seed two notebooks; export of A's manifest contains
  ONLY A's notebook+papers rows (no B's).
- 422 malformed slug.
- 404 unknown slug.
- preflight skip: place a symlink under `<slug>/` → it is NOT in the tar (and a
  WARNING is logged).
- **BodySizeCap exemption**: place enough asset bytes that the tar exceeds the
  256 KB cap → 200 (not 413). Confirms the exemption is wired.

---

## Implementation checklist

1. **`server/main.py`** — extend `_is_exempt_path` (or add a one-line suffix check
   inline) for `path.startswith("/ui/api/notebooks/") AND path.endswith("/export")`
   with a comment citing m6 D1.
2. **`server/routes/notebooks.py`** — add `GET /ui/api/notebooks/{slug}/export`:
   `validate_slug` → 422; `get_notebook` → 404; `notebook_dir(slug)` (containment);
   `list_papers(slug)`; build manifest (allowlist D3, sort_keys); build USTAR tar
   into BytesIO (D2, D4) with preflight (D5); return `Response` (D6).
3. **`tests/test_notebook_export.py`** (new) — the 7 tests in D7.

## Byte-stability / scope

No MCP / `server/tools.py` / `EXPECTED_TOOL_SCHEMA_SHA256` / `EXPECTED_BP1_SHA256`
change. No notebooks.db schema change. The export is read-only.

## Open questions

None blocking. (Both researchers had non-blocking design choices that the synthesis
resolved: BodySizeCap exemption shape — narrow suffix; manifest `parse_error`
inclusion — exclude.)

## External writes required

**None.** Purely local. (Push at milestone end is per-event authorized.)
