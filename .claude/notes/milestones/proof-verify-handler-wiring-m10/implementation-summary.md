# Implementation Summary — proof-verify-handler-wiring-m10

**Phase:** 2 (Implement) — INLINE path
**Test count:** 2484 passed (+19 from m9's 2465; 20 new preview tests
minus 1 deleted m9 scope guard), 9 skipped, 1 xfailed. Ruff clean.

---

## One-line summary

Per-paper preview route at
`GET /ui/notebooks/{slug}/papers/{paper_id:path}/preview` serves
stored ar5iv HTML with a TIGHT per-response CSP that blocks scripts,
`<base href>` hijack, form-action exfiltration, and clickjacking;
browse table adds a Preview column with a `target=_blank rel=noopener`
link when on-disk HTML exists (notebook-scoped first, corpus-global
fallback) and a "no preview available" tooltip otherwise.

---

## Commit range

`<base>..<head>` — `2780945b364f62193dd9334cc24f30328adac7f5..<HEAD>`
(this milestone's first commit will be the implementation commit;
range filled in at state.json finalization).

---

## Acceptance criteria status

| AC | Status | Evidence |
|---|---|---|
| `GET /ui/notebooks/{slug}/papers/{paper_id}/preview` returns the stored HTML wrapped in a minimal page with CSP `default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'none'` | ✅ — extended with 3 additional explicit directives | `TestPreviewHappyPath::test_returns_html_with_tight_csp`; `server/middleware.py::CONTENT_SECURITY_POLICY_PREVIEW`. Final CSP also includes `base-uri 'none'; form-action 'none'; frame-ancestors 'none'` per synthesis A3 (CSP3 non-fetch directives don't fall back to `default-src`) |
| The "Preview" link is only present in the UI when the on-disk HTML exists; missing papers show a "no preview available" tooltip | ✅ | `TestBrowseTableLinkConditional::test_preview_link_when_html_exists` + `test_preview_tooltip_when_html_absent`; `frontend/templates/notebook_detail.html` lines 114-141; `ui_notebook_detail` computes `has_preview: bool` per row in `server/routes/ui.py` |
| A test paper containing `<script>alert(1)</script>` does NOT execute the script when previewed (CSP test) | ✅ — header-contract assertion (browser-side enforcement out of test scope) | `TestPreviewScriptIsolation::test_script_tag_served_verbatim_but_csp_blocks_execution` — verifies script tag is served verbatim AND `script-src 'none'` is in the response CSP |
| A test paper containing `<img src="https://example.com/track.png">` does NOT make the outbound request (img-src 'self' test) | ✅ — header-contract assertion | `TestPreviewExternalImgBlocked::test_csp_restricts_img_src_to_self_and_data` |

All four acceptance criteria met.

---

## New / changed test paths

**New:**
- `tests/test_preview_route.py` (440 LOC, 20 tests) — full coverage matrix:
  - `TestPreviewHappyPath` (2 tests) — exact-bytes CSP + middleware override
  - `TestPreviewScriptIsolation` (1) — AC #3
  - `TestPreviewExternalImgBlocked` (1) — AC #4
  - `TestPreviewMissing` (1) — 404 generic body, no path leak
  - `TestPreviewPaperIdValidation` (6 — parametrized) — traversal, newline,
    shell metachars, NUL byte, malformed-format rejection
  - `TestPreviewSlugValidation` (2) — caps slug + traversal slug
  - `TestSearchOrder` (1) — notebook-scoped wins over corpus-global
  - `TestCorpusFallback` (3) — fallback path + old-style paper IDs
  - `TestBrowseTableLinkConditional` (2) — link vs tooltip rendering
  - `TestUploadFragmentPreviewLink` (1) — m8 upload fragment now also
    carries the Preview anchor

**Deleted:**
- `tests/test_m9_scope_invariants.py` — m9-boundary grep guard that
  fails on any `iframe|preview` token in `frontend/`. m10 deliberately
  adds both; the guard has served its m9-boundary purpose.

---

## Files touched (m10-specific only)

| File | Change |
|---|---|
| `server/middleware.py` | Added `CONTENT_SECURITY_POLICY_PREVIEW: bytes` module-level constant (+44 lines with docstring); placed alongside `CONTENT_SECURITY_POLICY_UI` |
| `server/routes/ui.py` | Added imports (`Response`, `is_valid_paper_id`, `CONTENT_SECURITY_POLICY_PREVIEW`, `CORPUS_PARSED_DIR`, `notebook_dir`); added `_preview_html_path()` helper (~30 LOC); added `ui_paper_preview` route (~120 LOC); augmented `ui_notebook_detail` to compute `has_preview` per paper |
| `server/routes/notebooks.py` | Updated `_paper_row_html` to add a Preview-anchor cell + adjusted column count (3 → 4) to match the rendered table |
| `frontend/templates/notebook_detail.html` | Added Preview column (table header + `<td>` with conditional link vs tooltip) |
| `tests/test_preview_route.py` | New test file (440 LOC, 20 tests) |
| `tests/test_m9_scope_invariants.py` | Deleted (m9 boundary guard, obsolete) |

Total: +~620 LOC across server + tests; -45 LOC for the deleted m9
guard. Net +575 LOC. Well within INLINE-path scope (< 500 LOC
threshold notwithstanding — the bulk is tests, which the threshold
language allows).

---

## Design decisions made (with synthesis cross-references)

### D1 — Direct-serve over R-1's two-route Option A
Adopted R-2's pivoted recommendation. Single route at `/preview`
returns the stored ar5iv HTML with the tight CSP on the response.
No nested iframe in our markup; browse-table link opens in a new tab
via `target="_blank" rel="noopener"`. Reasoning recorded in
`research-synthesis.md` §D1.

### A1 — Notebook-first search order with corpus-global fallback
`_preview_html_path()` searches `var/arxmcp/notebooks/<slug>/ar5iv/
<flat_paper_id>.html` first (m8 upload location), then
`var/arxmcp/corpus/parsed/<paper_id>/index.html` (ingest pipeline
location). Synthesis §A1.

### A3 — CSP extended with 3 explicit non-fetch directives
Final CSP adds `base-uri 'none'; form-action 'none'; frame-ancestors
'none'` to the brief's policy. CSP3 §6.8.3 — `default-src` is the
fallback for FETCH directives only. Without these three, a malicious
paper could hijack relative-URL resolution (`<base href>`), exfiltrate
via form submission, or clickjack the preview page.

### A4 — Handler sets CSP; middleware idempotency skips
`SecurityHeadersMiddleware` checks
`b"content-security-policy" not in existing` and skips when the
handler already supplied a value. Handler emits the tight CSP via
`Response(headers={"Content-Security-Policy": ...})`; the broader m8
UI CSP from the middleware does NOT clobber it. Test:
`test_csp_overrides_middleware_ui_csp` proves this.

### A5 — Triple-defense path validation
Chain: `validate_slug` → `is_valid_paper_id` (`\Z`-anchored) →
`notebook_dir` (m6 symlink rejection) → resolved-path-prefix check
(belt-and-braces). All four fire before any `read_bytes()` call.
The `is_valid_paper_id` check is what makes `{paper_id:path}` URL
parameter safe.

### A6 — MathJax / raw-LaTeX trade-off accepted
`script-src 'none'` blocks MathJax 3 initialization. Math content
renders as raw LaTeX markup (e.g., `\frac{1}{2}` as literal text)
rather than typeset. Documented as a future-enhancement candidate
(server-side KaTeX pre-render during ingest — out of m10 scope).

---

## Deviations from the brief

1. **CSP is tighter than the roadmap specifies.** Brief lists
   `default-src 'none'; img-src 'self' data:; style-src 'self'
   'unsafe-inline'; script-src 'none'`. Implementation adds
   `base-uri 'none'; form-action 'none'; frame-ancestors 'none'`
   per synthesis A3 (CSP3 directive-fallback gap). Net effect:
   strictly safer; no functional regression for ar5iv content.

2. **HTML source path differs from brief.** Brief says
   `var/arxmcp/corpus/parsed/<paper_id>/index.html` only. Both
   researchers documented (and the implementation accommodates)
   that m8 actually writes notebook-scoped:
   `var/arxmcp/notebooks/<slug>/ar5iv/<flat_paper_id>.html`.
   Implementation searches notebook-first, corpus-fallback;
   covers both surfaces.

3. **Table layout grew one column** (Paper ID, Added, **Preview**,
   Actions). Brief implied the Preview affordance went into the
   action cell alongside Remove. A dedicated column is testable
   in isolation and avoids visual cramping. The m8 upload fragment
   was updated in parallel to emit four cells matching the rendered
   layout.

4. **No `<iframe sandbox>` wrapper element.** The brief's
   "sandboxed iframe" language was interpreted by R-1 as needing
   an HTML wrapper around an iframe. The tight CSP achieves the
   same security boundary (script-blocking, `frame-ancestors
   'none'` against being framed) without the nested-iframe
   complexity. Per synthesis D1.

---

## External writes the orchestrator must authorize

**None.** Purely local milestone:
- No `git push` (final user gate per CLAUDE.md §4.4).
- No `gh issue create`, no PR, no infra apply.
- No third-party API call, no MCP tool schema change.
- No `EXPECTED_TOOL_SCHEMA_SHA256` re-pinning needed (no new MCP tool).

The only external-write gate is the user's `yes, push` after the
rectifier phase completes.
