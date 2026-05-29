# Implementation Summary — notebook-surface-expansion-m6

**One-liner:** `GET /ui/api/notebooks/{slug}/export` streams a deterministic
USTAR tar (one notebook's on-disk assets + a `manifest.json`) for backup/move,
byte-identical across two exports of the same notebook. (Epic e3, piece 1/2.)

**Commit range:** `<base>..<head>` (filled at finalize).
**Implementation path:** inline — 3 files (route + 1-block middleware exemption +
a new test file), ~400 LOC.

---

## What landed

### `server/routes/notebooks.py`
- New `GET /ui/api/notebooks/{slug}/export` route returning a `Response`
  (`media_type="application/x-tar"`, `Content-Disposition: attachment;
  filename="<slug>.tar"`, `Content-Length` set). `validate_slug` → 422;
  `get_notebook` → 404; `notebook_dir(slug)` containment → 422.
- `_EXPORT_MANIFEST_FORMAT_VERSION = 1`, `_EXPORT_NOTEBOOK_ALLOWLIST = (slug,
  display_name, notebook_kind, created_at, parse_status)` — **OMITS**
  `lancedb_path`, `parsed_html_path` (absolute host paths = m4 D3 info-leak
  class), `parse_error` (internal stderr state; not useful for backup).
- `_build_export_manifest` returns canonical-JSON bytes
  (`sort_keys=True, separators=(",", ":"), ensure_ascii=True`), `papers` sorted
  by `paper_id`.
- `_iter_safe_export_members` preflight (m6 D5): skip + WARN for symlinks,
  non-files, paths whose resolved location escapes `notebook_dir`, member names
  over USTAR's 255-byte limit, and names with control chars (`< 0x20`).
- `_make_deterministic_tarinfo` — manually-constructed `TarInfo` with EVERY
  drift-prone field normalized (`mtime=0, uid=0, gid=0, uname="", gname="",
  mode=0o644, type=REGTYPE`). Uses `tarfile.USTAR_FORMAT` (not the default PAX
  — PAX writes floating-point microsecond mtimes in extended headers that
  drift across exports even with `TarInfo.mtime=0`).
- Bundle layout: `manifest.json` at the root + assets under `<slug>/<rel>`
  members (slug-prefixed, relative paths constructed manually — never from
  `path` directly; eliminates the absolute-path / `..` class on the m7 untar
  side).

### `server/main.py`
- Extended `_is_exempt_path` with a single inline check:
  `path.startswith("/ui/api/notebooks/") AND path.endswith("/export")` → exempt
  from the 256 KB `BodySizeCapMiddleware` response cap (m6 synthesis D1).
  **Narrow-suffix** exemption — every other `/ui/api/notebooks/*` path stays
  capped (defense-in-depth preserved on the small-JSON routes).

### `tests/test_notebook_export.py` (new, 8 tests)
- Happy-path: 200 + content-type + filename + manifest shape + allowlist
  asserts (omits `lancedb_path` / `parsed_html_path` / `parse_error`); empty
  notebook → manifest-only tar.
- **Byte-deterministic**: two exports → byte-identical (the load-bearing AC).
- **No cross-notebook leak**: two notebooks; A's bundle contains only A's
  rows; tar bytes don't contain B's slug or paper_id.
- 422 malformed slug; 404 unknown slug.
- **Preflight**: a symlink under `<slug>/` is NOT in the tar; a WARNING is
  logged.
- **Byte-cap exemption (unit)**: `_is_exempt_path` exempts the export path AND
  rejects every other notebook-API path (the narrow-suffix property).

---

## Acceptance criteria status

- [x] **AC1** — `GET /ui/api/notebooks/{slug}/export` streams a tar with
  `manifest.json` + the notebook's `var/` asset files; 422 malformed; 404
  unknown. (Tests: `TestExportHappyPath`, `TestErrorCases`.)
- [x] **AC2** — new streaming export route + deterministic manifest builder
  (sorted keys, stable member order via `sorted(rglob)` + zeroed `TarInfo`
  fields); `validate_slug` + `notebook_dir` containment; manifest serializes
  ONLY the requested slug's rows. (Synthesis D2/D3/D5.)
- [x] **AC3** — tests pin: byte-deterministic across two exports; no
  cross-notebook leak; 422/404; symlink preflight skip + WARN; byte-cap
  exemption is narrow. **No re-pin of any MCP/BP1/tool-schema hash** — the
  export is `/ui/api/*`, disjoint from the MCP surface.

## Deviations from the brief

1. **BodySizeCap exemption is narrow-suffix, NOT broad-prefix.** The brief
   didn't specify; both researchers flagged the cap; resolved in synthesis D1
   to exempt ONLY `path.startswith("/ui/api/notebooks/") AND .endswith("/export")`
   rather than the whole `/ui/api/notebooks/` subtree — minimum widening, every
   other notebook-API response stays capped as defense-in-depth.
2. **Manifest omits `parse_error`** (in addition to the brief's omission of the
   path fields). Researchers disagreed; chosen exclude — internal stderr,
   possibly carries parser path fragments, not useful for backup/move.
3. **Format: USTAR** (not the default PAX). Required for byte-determinism —
   PAX writes float microsecond mtimes in extended headers that drift across
   exports even with `TarInfo.mtime=0`.

## Test surface

New: `tests/test_notebook_export.py` (8). Changed: `server/main.py`,
`server/routes/notebooks.py`. ruff clean. Adjacent suites
(`test_notebook_api.py`, `test_server_startup.py`) + byte-stability gates
(`test_server_tool_schema.py`, `test_prompts.py`) green — 188 tests total in
the m6 regression sweep.

## Byte-stability / scope

No `server/tools.py`, `ALL_TOOLS`, `EXPECTED_TOOL_SCHEMA_SHA256`,
`server/prompts.py`, or `EXPECTED_BP1_SHA256` change. No `TOOL_SCHEMA_VERSION`
bump. The export is `/ui/api/*`, disjoint from the frozen MCP surface.

## External writes required

**None.** Purely local.
