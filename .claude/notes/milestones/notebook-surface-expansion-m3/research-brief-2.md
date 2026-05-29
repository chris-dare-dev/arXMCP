# Research Brief — notebook-surface-expansion-m3

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-29T17:35:00Z

## In-codebase context

### Stale claims — exact locations

The milestone brief says to drop the "no frontend exists, by design" claim. The
phrase lives in at least **three** design-constitution files, not just the two
named:

1. `.claude/notes/02-architecture-overview.md:150` — verbatim: `"- Beautiful UI. The MCP tool surface is the UI."` (non-goals list)
2. `.claude/notes/09-feature-priorities.md:151` — verbatim: `"- **A web UI.** The MCP tool surface is the UI."`
3. `.claude/notes/06-mcp-server-design.md` — no identical phrase, but the
   "What this server does NOT do" section (lines 428–437) omits any mention of
   the operator HTML surface, leaving the impression it does not exist.

**FLAG: the brief names only `06-mcp-server-design.md` + `CLAUDE.md`. Files
02-architecture-overview.md and 09-feature-priorities.md carry the stale
claim too. The doc-grep test must scan broadly or it passes vacuously.**
Recommend the test grep all `.claude/notes/*.md` + `CLAUDE.md` for the
exact phrase `"The MCP tool surface is the UI"` and assert it is absent.

The E13_S06 critique artifact also contains:
`.claude/notes/milestones/E13_S06/critique-merged.md:5` — `"Frontend-UX: N/A (no frontend exists in arXMCP)"` — this is a frozen historical artifact in a milestone dir; it does NOT need updating (critique artifacts are immutable records).

### What actually shipped

From `server/routes/ui.py` and `server/routes/notebooks.py`, the shipped UI is:

- **HTML pages (Jinja2+htmx):**
  - `GET /ui/` — landing page; notebook list + create form
  - `GET /ui/notebooks/{slug}` — per-notebook detail; paper list; URL-paste; drag-drop upload card; parse-status / freshness (m1); in-page rename/delete (m2)
  - `GET /ui/notebooks/{slug}/papers/{paper_id}/preview` — direct-serve of ar5iv HTML with `CONTENT_SECURITY_POLICY_PREVIEW` + `_META_REFRESH_RE` strip (m10)
- **Mutation REST surface (`/ui/api/notebooks/...`):**
  - `POST /notebooks` — create
  - `DELETE /notebooks/{slug}` — metadata-only delete
  - `PATCH /notebooks/{slug}` — rename `display_name` only (m2 mass-assignment guard)
  - `GET/POST/DELETE /notebooks/{slug}/papers` — paper list, add-from-URL, remove
  - `POST /notebooks/{slug}/papers/upload` — PDF + ar5iv HTML upload (m4)
  - `POST /notebooks/{slug}/ingest` — ingest trigger
  - `GET /ui/status-badge` — operability badge (m4)
- **Templates:** `frontend/templates/` (base.html, index.html, notebook_detail.html)
- **Static:** `frontend/static/` mounted at `/ui/static/`

### Current security posture (baseline for the audit issue body)

From `server/middleware.py` and `server/routes/ui.py`:

- **Loopback bind** — `ARXMCP_BIND_HOST` defaults to `127.0.0.1`; non-loopback
  rejected at config parse by `reject_non_loopback_bind`.
- **Autoescape** — `server/routes/ui.py` constructs `jinja2.Environment` with
  `autoescape=jinja2.select_autoescape(enabled_extensions=("html","htm","xml"),
  default_for_string=True)`. No `| safe` filter in any template. This is
  load-bearing per MEMORY note `jinja2-autoescape-explicit-construction`.
- **CSP on UI pages** — `CONTENT_SECURITY_POLICY_UI` (defined in `middleware.py`,
  lines ~170–177): `default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'`
- **Tighter preview CSP** — `CONTENT_SECURITY_POLICY_PREVIEW` on the ar5iv
  direct-serve route; strips `<meta http-equiv="refresh">` via `_META_REFRESH_RE`.
- **SecFetchSite** — `SecFetchSiteMiddleware` in `server/main.py:581` with
  `exempt_prefixes=("/ui",)` — allows `Sec-Fetch-Site: same-origin` on `/ui/*`
  (htmx XHRs); everything else requires `none` or absent.
- **OriginValidation + HostValidation** — on all routes including `/ui/*`.
- **BodySizeCap** — 1 MB default; 200 MB envelope for `/ui/api/notebooks` (m4).
- **`validate_slug`** — called at every mutation boundary; enforces slug regex +
  symlink rejection.
- **Pydantic bounds** — `display_name: str = Field(max_length=256)`.
- **Control-char strip** — `_CONTROL_CHARS_RE.sub("", body.display_name)` before
  store update.
- **PDF preflight** — `_pdf_find_javascript` + zip-bomb guard on upload.
- **Mass-assignment guard** — `PATCH` accepts ONLY `display_name`; slug / kind /
  parse_status are NOT patchable.

### What the E13 audit scoped out

E13_S01–S10 audited only the **7-tool MCP surface** (`server/handlers/`). The
`server/routes/ui.py` and `server/routes/notebooks.py` surfaces were explicitly
not in scope because the E13 brief's audit scope read: *"The audit scope is
deliberately limited to the 7 tools that constitute the v1 surface."* This is
confirmed by the E13_S06 critique line 5. CAND-13 (capability scout, 2026q2
notebook-ux-storage-ops) proposed a tracking issue; this milestone executes that.

### gh issue create mechanics — how E13 issues #1–#6 were filed

From `.claude/notes/milestones/E13_S10/_file_issues.py`:
- Repo: `chris-dare-dev/arXMCP`
- Command form: `gh issue create --repo chris-dare-dev/arXMCP --title "<title>" --body-file <path>`
- Labels via `--label "<label>"` (one flag per label; gh silently skips
  labels that don't exist on the repo; the script retried without labels
  on `"not found"` stderr)
- The body was written to a `tempfile.NamedTemporaryFile` (suffix `.md`) then
  passed via `--body-file`; stdout of `gh issue create` is the resulting URL

**`gh auth status` is currently valid:** `gh auth status` confirms
`github.com` logged in as `chris-dare-dev`, active account, token scopes
include `repo`. No auth blocker.

**Existing issues #1–#8 at `chris-dare-dev/arXMCP`:** verified via
`gh issue list`. The next issue number will be #9. There is NO existing
UI-security-audit issue. Idempotency: safe to file; no duplicate.

**Recommended convention for this milestone:**
Write the issue body to `.claude/notes/milestones/notebook-surface-expansion-m3/ui-security-audit-issue.md`.
This file is committed in the `feat(notes)` commit (Phase 2). Phase 4 then
runs:
```
gh issue create \
  --repo chris-dare-dev/arXMCP \
  --title "UI security audit: server/routes/ui.py + notebooks.py + templates (CAND-13)" \
  --body-file .claude/notes/milestones/notebook-surface-expansion-m3/ui-security-audit-issue.md \
  --label "area:security"
```
This is a clean, reviewable, idempotent step. The `--label area:security` may
be silently dropped if the label doesn't exist (mirrors E13 pattern); that is
acceptable.

## Prior decisions and lessons

From git log:
- `eb8088d` — m2 complete (rename + delete wired)
- `d073c0a` — `feat(server): in-page notebook rename + delete (notebook-surface-expansion-m2)`
- `096be65` — m1 complete
- `18a4733` — E14 observability ops shipped (S01–S05)

From MEMORY (auto-injected): `jinja2-autoescape-explicit-construction` and
`parse_status-is-notebook-not-paper-scoped` are load-bearing; neither is
touched by this milestone.

**Doc-placement rule (CLAUDE.md §1, agent-conventions.md §6):** All new Markdown
goes under `.claude/`. The issue-body file must live at
`.claude/notes/milestones/notebook-surface-expansion-m3/ui-security-audit-issue.md` —
NOT in `docs/`, `server/`, or any other location.

**CLAUDE.md §4.6** (doc placement): "All new agent-internal documents go under
`.claude/`." This explicitly covers issue-body files.

**Tool-schema re-pinning:** This milestone adds NO MCP tools. `EXPECTED_TOOL_SCHEMA_SHA256` is UNCHANGED.

**BP1 re-pinning:** No `server/prompts.py` change. `EXPECTED_BP1_SHA256` is UNCHANGED.

## External sources

The MCP spec and Anthropic caching docs are not relevant to this milestone (no
server-surface change, no tool-schema change, no caching change). No external
source fetch required.

The CAND-13 scout brief (`.claude/notes/capability-scouts/2026q2-notebook-ux-storage-ops/artifacts/synthesis.md:221`) is the authoritative in-repo description of the doc-refresh scope and the audit issue rationale.

## Recommendation

**Write the issue body file under `.claude/notes/milestones/notebook-surface-expansion-m3/ui-security-audit-issue.md`
and commit it in the feat commit (Phase 2). Phase 4 fires `gh issue create --body-file <path>` after
per-event user authorization.**

The issue body draft (for the implementer to use verbatim or lightly edit):

---
**Title:** `UI security audit: server/routes/ui.py + notebooks.py + templates (CAND-13)`

**Body:**

```
## Summary

The E13 (Security Hardening) audit covered only the 7-tool MCP surface
(`server/handlers/`). The Jinja2+htmx notebook UI was explicitly out of scope
because E13's audit scope stated "no frontend exists" — a stale claim as of the
proof-verify and textbook-ingest streams. This issue tracks the deferred UI audit.

## Audit scope

- `server/routes/ui.py` — HTML page routes (`/ui/`, `/ui/notebooks/{slug}`,
  `/ui/notebooks/{slug}/papers/{paper_id}/preview`), m10 meta-refresh strip,
  preview CSP (`CONTENT_SECURITY_POLICY_PREVIEW`)
- `server/routes/notebooks.py` — state-MUTATING REST surface: create (`POST`),
  delete (`DELETE`), rename (`PATCH /ui/api/notebooks/{slug}`), paper-add/remove
  (`POST`/`DELETE`), PDF+ar5iv upload (`POST .../papers/upload`), ingest-trigger
  (`POST .../ingest`), plus operability badge (`GET /ui/status-badge`)
- `frontend/templates/` — base.html, index.html, notebook_detail.html
- `server/middleware.py` — `SecFetchSiteMiddleware` `/ui` carve-out,
  `OriginValidationMiddleware`, `HostValidationMiddleware`, `BodySizeCap`,
  `CONTENT_SECURITY_POLICY_UI` + `CONTENT_SECURITY_POLICY_PREVIEW` constants

## Current defenses (baseline)

- Loopback bind (`127.0.0.1`); `reject_non_loopback_bind` at config-parse
- Jinja2 `autoescape=select_autoescape(...)` — explicit; no `| safe` in templates
- `SecFetchSiteMiddleware(exempt_prefixes=("/ui",))` — allows `same-origin` on `/ui/*`
- `OriginValidationMiddleware` + `HostValidationMiddleware` on all routes
- `CONTENT_SECURITY_POLICY_UI` + tighter `CONTENT_SECURITY_POLICY_PREVIEW`
- `_META_REFRESH_RE` strip on ar5iv HTML before serving
- `validate_slug` at every mutation boundary
- `display_name: Field(max_length=256)` + `_CONTROL_CHARS_RE.sub(...)` strip
- PDF preflight (`_pdf_find_javascript` + zip-bomb guard)
- Mass-assignment guard: `PATCH` accepts ONLY `display_name`

## Open questions the audit must answer

1. **CSRF on mutation endpoints without explicit tokens.** The current defense
   is `SecFetchSiteMiddleware` (blocks cross-site fetches from other origins) +
   loopback-only bind. An explicit CSRF token was NOT added (it was judged
   redundant for a loopback-only service). The audit should verify whether the
   `same-origin` carve-out combined with the bind constraint is sufficient, or
   whether an explicit double-submit token adds meaningful defense.

2. **Upload polyglot and zip-bomb completeness.** The PDF preflight checks
   `%PDF-` magic bytes and `_pdf_find_javascript`. The ar5iv HTML upload path
   checks `_is_html_bytes`. The audit should verify: can a polyglot file
   (e.g., `%PDF-... <html>`) bypass both checks? Is the zip-bomb guard size
   limit aligned with the 200 MB middleware envelope?

3. **Path-traversal completeness on the preview route.** The preview route is
   `GET /ui/notebooks/{slug}/papers/{paper_id}/preview` — the ar5iv HTML is
   served directly from `var/arxmcp/notebooks/{slug}/...`. The audit must verify
   that `validate_slug` + `is_valid_arxiv_paper_id` together are sufficient to
   prevent path traversal to files outside the notebook's directory.

4. **CSP `unsafe-inline` scope.** `CONTENT_SECURITY_POLICY_UI` allows
   `script-src 'self' 'unsafe-inline'` for htmx + inline shim. The audit
   should assess whether moving the inline shim to a static file + per-script
   hashes would reduce risk meaningfully for a loopback-only UI.

5. **`display_name` stored-XSS vector.** The Jinja2 autoescape + `html.escape`
   in the PATCH fragment path are the guards. Confirm no path renders
   `display_name` with `| safe` or `Markup(...)` direct injection.

## References

- `.claude/notes/08-security-observability-ops.md` — threat model framing
- `.claude/notes/milestones/E13_S10/` — coverage doc + G1–G6 gap issues
- CAND-13 (`.claude/notes/capability-scouts/2026q2-notebook-ux-storage-ops/artifacts/synthesis.md:221`)
- `server/middleware.py` — middleware constants + `SecFetchSiteMiddleware`

## Labels

`area:security`
```
---

## Failure-mode analysis

**FM-1: Doc-grep test too narrow — passes vacuously.**
Trigger: the test only asserts the phrase is gone from `06-mcp-server-design.md`
and `CLAUDE.md`, but the brief targets `"no frontend exists, by design"`.
The ACTUAL stale phrases are `"Beautiful UI. The MCP tool surface is the UI."`
(02-architecture-overview.md:150) and `"A web UI. The MCP tool surface is the UI."`
(09-feature-priorities.md:151). If the test asserts absence of a phrase that
never existed in those files, it passes vacuously.
Mitigation: the doc-grep test must use the actual exact phrase from each file,
OR scan broadly for `"The MCP tool surface is the UI"` across all `.claude/notes/*.md`
and `CLAUDE.md`. **Recommend the broad scan; it future-proofs the test.**

**FM-2: Implementation phase accidentally runs `gh issue create`.**
Trigger: the implementer reads "FILE a UI-security-audit tracking issue" and
runs the `gh` command during Phase 2.
Mitigation: the brief says "(do NOT execute)" and "external write — Phase-4,
per-event authorized." The issue-body file must be written to disk in Phase 2,
but the `gh issue create` invocation is BANNED from Phase 2 per `agent-conventions.md §4`
(`gh issue create` from agent code is CRITICAL banned pattern) and §8 (external-write
boundary). The research brief MUST make this explicit.

**FM-3: Duplicate issue already exists — idempotency check.**
Trigger: a UI-security-audit issue exists before Phase 4 runs (e.g. filed out-of-band).
Mitigation: verified via `gh issue list --repo chris-dare-dev/arXMCP --state all
--limit 15` — no existing UI-security-audit issue as of 2026-05-29. The issue
text is distinct enough from #1–#8 (all Threat 1–7 follow-ups) that a duplicate
is unlikely. The implementer should note the check recommendation in the
issue-body file as a pre-flight comment.

**FM-4: `gh` auth fails at Phase 4.**
Trigger: `gh auth status` shows expired or missing token at Phase 4 execution.
Mitigation: `gh auth status` confirmed valid NOW (Logged in to github.com account
`chris-dare-dev`, `repo` scope). However, tokens can expire. If Phase 4 fails,
the remediation is `gh auth login`. The issue-body file is already on disk, so
the `--body-file` invocation can be retried without re-running the pipeline.

**FM-5: Stale claim in 02-architecture-overview.md or 09-feature-priorities.md
is not updated — contradiction survives.**
Trigger: the implementer updates only `06-mcp-server-design.md` and `CLAUDE.md`.
Files 02-architecture-overview.md:150 and 09-feature-priorities.md:151 still
say `"The MCP tool surface is the UI."` A future agent reading those files will
conclude no UI exists, defeating the milestone.
Mitigation: the implementer must update all three `.claude/notes/` files that
carry the stale claim. The doc-grep test (if broad) will catch the regression if
the files are not updated. **FLAG: the brief names only two files — the
implementer must be told to also update 02 and 09.**

**FM-6: CLAUDE.md edit bloats the always-loaded context or violates doc-placement rule.**
Trigger: the implementer adds a new long section describing the UI to `CLAUDE.md`.
Mitigation: `CLAUDE.md §5` already has a directory layout table. The correct
edit is to add `server/routes/` and `frontend/` rows to the existing layout
table (or add a one-sentence note to the "What this project is" section). It
must NOT add a new top-level section. The doc-placement rule (`CLAUDE.md §1`)
governs what CAN be in CLAUDE.md; this is allowed since CLAUDE.md is the
project-level instruction file.

**FM-7: Issue body leaks sensitive information.**
Trigger: the issue body includes file paths that expose internal ops details,
private corpus statistics, or PII.
Mitigation: the draft body above contains only public-facing route paths, class
names, and feature descriptions — all of which are in the repository source.
No private data, no API keys, no corpus statistics. Low risk.

**FM-8 (CAND): The `09-feature-priorities.md` "Things to explicitly NOT build"
list is superseded by the roadmap but the stale entry could be interpreted as
authoritative.**
`CLAUDE.md §11` says: `"Note: .claude/notes/09-feature-priorities.md is
SUPERSEDED by .claude/roadmap/README.md."` The implementer should add a
deprecation note on the "A web UI" entry in 09 rather than removing it (so the
historical record is clear), or just acknowledge it is superseded.

## Open questions

No open questions — implementation can proceed on the above recommendation.
The only risk that requires a judgment call is **FM-5** (stale phrases in files
not named in the brief): the implementer must update `02-architecture-overview.md`
and `09-feature-priorities.md` in addition to the two named files.

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| `gh issue create` | `chris-dare-dev/arXMCP` (GitHub) | File the UI-security-audit tracking issue (CAND-13). ONE issue, per-event authorized in Phase 4. NOT to be executed in Phase 2. |

The issue-body file artifact
(`.claude/notes/milestones/notebook-surface-expansion-m3/ui-security-audit-issue.md`)
is committed to the repo in Phase 2's `feat` commit. The `gh issue create
--body-file <path>` invocation is the Phase 4 external-write step.
