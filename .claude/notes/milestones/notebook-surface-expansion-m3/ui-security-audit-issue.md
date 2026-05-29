## Summary

The E13 (Security Hardening) audit deliberately scoped itself to the **7-tool MCP
surface** (`server/handlers/`). The loopback-only **Jinja2 + htmx operator console**
(`server/routes/ui.py` + `server/routes/notebooks.py` + `frontend/templates/`) was
never given a dedicated security audit — at the time, the constitution still framed
arXMCP as having no UI ("the MCP tool surface is the UI"). That console has since
grown a **state-mutating** REST surface (create / delete / rename / paper add-remove /
file upload / ingest trigger). This issue tracks the deferred UI security audit
(CAND-13 / CAND-14 from the 2026q2 notebook-ux-storage-ops capability scout;
notebook-surface-expansion-m3 refreshed the constitution and files this).

**This is a tracking issue, not the audit itself.** The audit is a future effort.

## Audit scope

- `server/routes/ui.py` — HTML page routes (`/ui/`, `/ui/notebooks/{slug}`,
  `/ui/notebooks/{slug}/papers/{paper_id}/preview`), the ar5iv direct-serve path,
  the m10 `<meta http-equiv="refresh">` strip, and `CONTENT_SECURITY_POLICY_PREVIEW`.
- `server/routes/notebooks.py` — the state-MUTATING `/ui/api/notebooks/*` surface:
  create (`POST`), delete (`DELETE`), rename (`PATCH`, m2), paper add/remove
  (`POST`/`DELETE`), PDF + ar5iv upload (`POST .../papers/upload`), ingest trigger
  (`POST .../ingest`), plus the operability badge (`GET /ui/status-badge`).
- `frontend/templates/` — `base.html`, `index.html`, `notebook_detail.html`
  (Jinja2 autoescape; the htmx JSON-shim in `base.html`).
- `server/middleware.py` — `SecFetchSiteMiddleware` `/ui` carve-out,
  `OriginValidationMiddleware`, `HostValidationMiddleware`, `BodySizeCap`, and the
  `CONTENT_SECURITY_POLICY_UI` / `CONTENT_SECURITY_POLICY_PREVIEW` constants.

## Current defenses (audit baseline — already in place)

- **Loopback-only bind** (`127.0.0.1`); non-loopback rejected at config parse.
- **Jinja2 autoescape**, explicitly constructed (`select_autoescape(...,
  default_for_string=True)`); zero `| safe` filters in any template; hand-built
  htmx fragments use `html.escape` per value.
- **CSP**: `CONTENT_SECURITY_POLICY_UI` on `/ui/*`; tighter
  `CONTENT_SECURITY_POLICY_PREVIEW` on the ar5iv preview; `frame-ancestors 'none'`.
- **CSRF posture (no token, by design)**: `SecFetchSiteMiddleware(exempt_prefixes=
  ("/ui",))` admits only `Sec-Fetch-Site: same-origin|none` on `/ui/*`, plus
  Origin + Host loopback validation.
- **Input validation**: `validate_slug` (path-traversal regex + symlink rejection)
  at every mutation boundary; Pydantic `Field(max_length=...)` bounds; `display_name`
  control-char strip + mass-assignment guard (`PATCH` accepts only `display_name`).
- **Upload preflight**: PDF JavaScript / polyglot / page-count checks; HTML
  byte-sniff; per-kind size caps.

## Open questions the audit must answer

1. **CSRF without explicit tokens.** Is `SecFetchSiteMiddleware` + loopback bind
   sufficient against a malicious local process / DNS-rebinding, or does a
   double-submit token add meaningful defense on the mutating endpoints?
2. **Upload polyglot / zip-bomb completeness.** Can a `%PDF-…<html>` polyglot pass
   both the PDF and HTML sniffers? Is the decompression-bomb guard aligned with the
   per-kind body-size envelope?
3. **Path-traversal completeness on the preview route.** Are `validate_slug` +
   `is_valid_arxiv_paper_id` + the resolved-path containment check jointly
   sufficient to prevent escaping a notebook's `var/arxmcp/notebooks/<slug>/` dir
   (incl. symlink-inside-notebook attacks)?
4. **CSP `unsafe-inline` scope.** `CONTENT_SECURITY_POLICY_UI` allows
   `script-src 'self' 'unsafe-inline'` (htmx + the inline JSON-shim). Would moving
   the shim to a static file + per-script hashes/nonce meaningfully reduce risk?
5. **Stored-XSS on operator-authored fields.** Confirm no render path emits
   `display_name` (or any operator string) via `| safe` / `Markup(...)`; confirm the
   two-renderer pair (Jinja `<p>` vs the PATCH fragment) cannot diverge into an
   unescaped path.

## References

- `.claude/notes/08-security-observability-ops.md` — threat-model framing.
- `.claude/notes/06-mcp-server-design.md` § "Browser UI surface" — the surface + posture.
- `.claude/notes/milestones/E13_S10/` — the MCP-surface audit coverage doc + gap issues.
- CAND-13 / CAND-14 — `.claude/notes/capability-scouts/2026q2-notebook-ux-storage-ops/`.
