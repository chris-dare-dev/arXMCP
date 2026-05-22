# Research Synthesis — proof-verify-handler-wiring-m10

**Phase:** 1 (Research) → 2 (Implement)
**Briefs merged:** `research-brief-1.md`, `research-brief-2.md`
**Generated:** 2026-05-22

---

## Milestone in one paragraph

Ship a per-paper "Preview" affordance in the m8 browse table that opens
the stored ar5iv HTML in a sandboxed view at
`GET /ui/notebooks/{slug}/papers/{paper_id}/preview`. The route serves
the stored HTML with a TIGHT per-response Content-Security-Policy that
neutralises scripts, base-uri hijack, form-action exfiltration, and
clickjacking of the preview page itself. The CSP is the load-bearing
security boundary; the `<iframe sandbox>` is defense-in-depth where
the parent page wraps the response.

---

## Cross-brief agreements (high confidence — both researchers concur)

### A1. The roadmap's HTML source path is WRONG

The brief at `plans/proof-verify-handler-wiring-roadmap.md:356` says
`var/arxmcp/corpus/parsed/<paper_id>/index.html`. Both briefs
demonstrate this is incomplete:

R-1 (`research-brief-1.md:13-33`) enumerates two distinct write sites:
- **Path A** — `ingest/ar5iv_fetch.py:53,284` writes
  `var/arxmcp/corpus/parsed/<paper_id>/index.html` (note: `paper_id`
  used directly as subdir, so old-style IDs produce nested subdirs).
- **Path B** — `server/routes/notebooks.py:605-620` writes
  `var/arxmcp/notebooks/<slug>/ar5iv/<flat_paper_id>.html` where
  `flat_paper_id = paper_id.replace("/", "_")`.

R-2 (`research-brief-2.md:11-22`) confirms Path B is the m8-upload
contract and is the primary location for notebook-scoped previews.

**Resolution.** The preview route searches **notebook-scoped first,
corpus-global second** (R-1's recommendation; R-2 does not contradict).
Returning to corpus-global as fallback costs essentially nothing (one
extra `Path.is_file()` stat) and means seed-corpus papers that haven't
been re-uploaded through m8 are still previewable. Both paths are
constructed under `notebook_dir(slug)` / `REPO_ROOT / "var" / "arxmcp"
/ "corpus" / "parsed"` — both go through path-containment guards.

### A2. Delete `tests/test_m9_scope_invariants.py` as step zero

R-1 §"m9 scope-invariant test" and R-2 FM-8 both call out the same
guard: the m9 test greps `frontend/` for `iframe|preview` and fails on
ANY match. m10 deliberately adds both tokens. Delete the test file in
the first commit; the guard served its m9-boundary purpose and is
obsolete once m10 ships.

### A3. CSP3 directives — three real gaps in the roadmap CSP

The roadmap CSP (line 359) is:
```
default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'none'
```

Both briefs cite CSP3 §6.8.3 (R-2 §"CSP Level 3"): `default-src` is
the fallback for **fetch directives only**. Three non-fetch directives
do NOT inherit and need explicit values:

| Directive | Type | Without it | With `'none'` |
|---|---|---|---|
| `base-uri` | document | `<base href="https://attacker/">` redirects all relative URLs | Blocked (R-2 FM-2) |
| `form-action` | navigation | `<form action="https://attacker/exfil">` POSTs on submit | Blocked (R-2 FM-3) |
| `frame-ancestors` | navigation | Any origin can iframe the preview page (clickjacking) | Blocked (R-2 FM-4) |

**Final agreed CSP** (verbatim, byte-stable constant):
```
default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'
```

### A4. The CSP-override mechanism uses middleware idempotency

`SecurityHeadersMiddleware` (`server/middleware.py:685-741`) emits the
broad m8 `/ui/*` CSP only when `b"content-security-policy" not in
existing` (R-1 §"CSP override", R-2 §"Existing CSP"). The preview
handler sets its own `Content-Security-Policy` response header BEFORE
the middleware fires; the middleware then skips injection. This is the
correct override path — no middleware change needed.

### A5. Triple-defense path validation

Both briefs converge on the same chain (R-1 §"is_valid_paper_id +
path-traversal defense", R-2 FM-6):

1. `validate_slug(slug)` — m6 guard.
2. `is_valid_paper_id(paper_id)` — `\Z`-anchored regex (m1-rect-F3
   hardening); MUST fire before any `Path(...)` construction or
   `.replace("/", "_")` substitution.
3. `notebook_dir(slug)` — m6 symlink-rejection path-containment.
4. (Belt-and-braces) `str(html_path.resolve()).startswith(str(
   ar5iv_dir.resolve()))` — explicit prefix check before opening.

The `{paper_id:path}` URL parameter is required because old-style IDs
contain `/`; the chain above is what makes it safe.

### A6. MathJax / math-rendering trade-off — accepted

R-2 FM-9 documents the trade-off precisely: ar5iv HTML uses MathJax 3
which requires `script-src 'self' 'unsafe-eval'`. With `script-src
'none'`, MathJax cannot run and math renders as raw LaTeX markup. R-1
does not address this directly but agrees with the tight CSP.

**Resolution.** Accept raw-LaTeX display for v2 m10. Document in the
implementation summary as a known limitation and a future-enhancement
candidate (server-side KaTeX pre-render during ingest — out of m10
scope). This aligns with the brief's design intent ("static math
content; no JS execution needed").

### A7. Route placement — `server/routes/ui.py`, NOT `notebooks.py`

R-1 §"Route placement" — `notebooks_router` is mounted at `/ui/api`,
`ui_router` at `/ui`. The preview URL is `/ui/notebooks/...` (no
`/api`), so the route belongs in `server/routes/ui.py` next to
`ui_notebook_detail`. R-2 §"Open question 2" reaches the same
conclusion. No `server/main.py` mounting change.

---

## Substantive disagreement (resolved)

### D1. Route shape — wrapper page + raw route vs direct-serve

**R-1's position (Option A — two routes).** Wrapper page at
`/preview` serves a minimal HTML containing `<iframe
sandbox="allow-same-origin" src=".../preview/raw">`. The `/preview/raw`
route serves the raw HTML with the tight CSP. R-1's reasoning: gives
two independently testable boundaries (wrapper CSP + raw CSP), provides
the `sandbox` attribute layer in addition to CSP.

**R-2's position (direct-serve).** The `/preview` route returns the
stored HTML directly with the tight CSP on the response. No nested
iframe inside our markup. R-2 reaches this after exploring both options:
"The sandboxing is enforced by the parent's `<iframe sandbox>` element
wrapping THIS page in the browse table... This is architecturally
cleaner."

**Decision — adopt R-2's direct-serve approach.** Reasoning:

1. **Security parity.** The tight CSP already includes `script-src
   'none'`, `frame-ancestors 'none'`, `base-uri 'none'`, `form-action
   'none'`. The `<iframe sandbox="allow-same-origin">` attribute in
   R-1's Option A adds redundant script-disabling on top of `script-src
   'none'`. With the same-origin sandbox, the iframe origin matches
   `'self'` for `img-src`/`style-src` — but we get the same behavior
   serving directly: the page IS at our origin.

2. **Surface area.** Option A doubles the route count, doubles the
   CSP-constant count, and requires a wrapper template. R-2's
   direct-serve is one route, one CSP constant, no template.

3. **Browse-table integration is simpler.** The "Preview" link in the
   browse table becomes a plain `<a href="..." target="_blank">` that
   opens in a new tab. No per-row stat-cost question, no inline-iframe
   nesting question. The user closes the tab when done.

4. **R-1's "Option C provides no iframe sandbox boundary" argument
   does not bind here.** R-1's worry was scripts running in the
   tab. But `script-src 'none'` blocks `<script>` elements, blocks
   `eval()`, and by the `script-src-attr` fallback chain (R-2
   §"`script-src 'none'` and inline event handlers") blocks inline
   `onclick="..."` handlers too. There is no script execution path.

5. **v2 Later-lane scope.** The roadmap classifies this as the
   Later-lane finale (M, "S (~half day)"). Adding a wrapper page
   contradicts the scope tier.

**Final shape:** ONE route at `/ui/notebooks/{slug}/papers/{paper_id:path}/preview`
that serves the stored HTML with the tight CSP on the response.
Browse-table "Preview" link opens in new tab via `target="_blank"
rel="noopener"`.

---

## Implementation plan (Phase 2 — INLINE path)

Estimated size: < 200 LOC + ~6 tests. Single file boundary (server +
template + tests). **INLINE.** No worktree delegation.

### Step 0 — Delete obsolete m9 guard
- `git rm tests/test_m9_scope_invariants.py`.

### Step 1 — Add CSP constant in middleware
- `server/middleware.py`: add module-level
  `CONTENT_SECURITY_POLICY_PREVIEW: bytes = (
    b"default-src 'none'; img-src 'self' data:; "
    b"style-src 'self' 'unsafe-inline'; script-src 'none'; "
    b"base-uri 'none'; form-action 'none'; "
    b"frame-ancestors 'none'"
  )`
  alongside `CONTENT_SECURITY_POLICY_UI`. Byte-stable constant per
  cache-discipline conventions.

### Step 2 — Add preview route in `server/routes/ui.py`
- Route: `GET /notebooks/{slug}/papers/{paper_id:path}/preview`.
- Handler:
  1. `validate_slug(slug)` (raises 422 on bad slug).
  2. `is_valid_paper_id(paper_id)` (raises 422 on bad ID).
  3. Search order: `notebook_dir(slug) / "ar5iv" / f"{flat_paper_id}.html"`
     first; corpus-global `REPO_ROOT / "var/arxmcp/corpus/parsed" /
     paper_id / "index.html"` second.
  4. Path-containment check via `Path.resolve()` + `startswith`.
  5. 404 with generic message if neither path exists (don't leak
     filesystem paths).
  6. Read bytes; return `Response(content=bytes, media_type="text/html",
     headers={"Content-Security-Policy": CONTENT_SECURITY_POLICY_PREVIEW.decode()})`.

### Step 3 — Augment `ui_notebook_detail` to compute `has_preview` per paper
- Per-row filesystem stat for both Path A and Path B (one `Path.is_file()`
  call each, very cheap on loopback). Pass `has_preview: bool` into
  template context per paper.

### Step 4 — Browse-table template change
- `frontend/templates/notebook_detail.html:114-131`: add a new `<td>`
  (or inline in the action `<td>`) with:
  - When `has_preview`: `<a href="/ui/notebooks/{{ notebook.slug }}/papers/{{ p.paper_id }}/preview" target="_blank" rel="noopener">Preview</a>`
  - When not: `<span title="no preview available" class="hint">Preview</span>` (per AC #2)

### Step 5 — Tests under `tests/` (NEW file `test_preview_route.py`)
Concrete tests required:
1. `test_preview_returns_html_with_tight_csp` — happy path. Assert
   exact CSP header bytes match `CONTENT_SECURITY_POLICY_PREVIEW`.
2. `test_preview_script_in_paper_is_not_executed` — CSP-by-inspection:
   write a fake ar5iv HTML containing `<script>alert(1)</script>` to
   the notebook dir, GET `/preview`, assert response includes the
   script tag (it's served as-is) AND CSP header forbids script
   execution.
3. `test_preview_external_img_blocked_by_csp_header` — assert `img-src
   'self' data:` is present (browser-side enforcement; we assert the
   header contract).
4. `test_preview_404_when_html_absent` — generic 404 body, no
   filesystem path in response.
5. `test_preview_rejects_path_traversal` — `/preview` with `paper_id`
   containing `..` returns 422 from `is_valid_paper_id`.
6. `test_preview_link_only_when_html_exists` — render
   `ui_notebook_detail`; assert "Preview" anchor present when
   `has_preview=True`, absent (or wrapped in `<span>`) when not.
7. `test_notebook_first_search_order` — both paths exist on disk;
   assert notebook-scoped content wins (different sentinel bytes).
8. `test_corpus_fallback_used_when_notebook_missing` — only Path A
   exists; assert it's served.

### Step 6 — Run `make test`; verify ruff clean + green.

### Step 7 — Commit triple per CLAUDE.md §4.3
- `feat(server): paper preview route with tight CSP (proof-verify-handler-wiring-m10)`
- (rect commit if critique surfaces findings)
- `chore(notes): finalize proof-verify-handler-wiring-m10 state -> complete`

---

## Orchestrator synthesis notes

- **Divergence on route shape (D1) resolved in favor of R-2 (direct-serve).**
  The reasoning is recorded above; both researchers acknowledged the
  trade-off, R-2 explicitly pivoted to direct-serve during their
  analysis, and R-1's Option A advantages (two independently-testable
  CSPs) do not justify the doubled surface area at this scope tier.
- **No other unresolved disagreements.** All other findings overlap
  cleanly between the briefs.
- **The roadmap brief's HTML-path inaccuracy is a documentation bug**,
  not a blocker. The implementation searches both locations; we are
  not changing the brief.

---

## Open questions for the implementer

All implementer-time decisions, none architectural:

1. **`Content-Length` header**: emit explicitly? Default Response
   handling does this; no special handling needed.
2. **Cache-Control on preview**: default `no-store` for loopback dev?
   Recommendation: omit; let the browser decide. The CSP is what
   matters here.
3. **Title element / favicon**: served HTML is the ar5iv content
   verbatim; ar5iv already includes a `<title>` and a viewport meta.
   No wrapping needed.

---

## External writes the implementation will require

**None.** Purely local milestone:
- No `git push` (final user gate per CLAUDE.md §4.4).
- No `gh issue create`, no PR, no infra apply.
- No third-party API call, no MCP tool schema change (no
  `EXPECTED_TOOL_SCHEMA_SHA256` re-pinning needed).
- All file edits under `server/`, `frontend/templates/`, `tests/`.

Single pre-push authorization remains the only external-write gate;
the rectifier phase does not introduce external writes either.
