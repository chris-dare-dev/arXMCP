# Implementation Summary — notebook-surface-expansion-m3

**One-liner:** Refreshed the design constitution to drop the stale "the MCP tool
surface is the UI" claim and describe the shipped Jinja2+htmx operator console;
prepared (NOT filed) the UI-security-audit tracking issue for `chris-dare-dev/arXMCP`.
(Epic e4 — UI completion; closes the constitution-drift the capability-scout flagged.)

**Commit range:** `<base>..<head>` (filled at finalize).
**Implementation path:** inline — 4 doc edits + 1 issue-body artifact + 1 doc-grep test.

---

## What landed

### Constitution edits
- **`.claude/notes/02-architecture-overview.md`** — the "Non-goals for v1" bullet
  "Beautiful UI. The MCP tool surface is the UI." reworded: a loopback-only
  Jinja2+htmx operator console DOES ship (notebook management; no SPA/build chain),
  the MCP tool surface remains the primary agent interface.
- **`.claude/notes/09-feature-priorities.md`** — the "Things to NOT build" bullet
  "A web UI. The MCP tool surface is the UI." reworded the same way (note kept its
  SUPERSEDED marker; the false absolute removed so it no longer misleads).
- **`.claude/notes/06-mcp-server-design.md`** — NEW `## Browser UI surface` section
  (before "What this server does NOT do") enumerating the HTML pages
  (`server/routes/ui.py`), the `/ui/api/*` REST surface (`server/routes/notebooks.py`),
  and the security posture (loopback bind, explicit autoescape, CSP, SecFetchSite
  `/ui` carve-out + Origin/Host validation, validate_slug, Pydantic bounds, upload
  preflight) — plus a note that this surface has NOT been security-audited (E13
  scope-out; tracked as the filed issue).
- **`CLAUDE.md`** — minimal: §2 one sentence (the console exists alongside the MCP
  surface); §5 directory layout (`server/routes/` + a top-level `frontend/` block,
  `/status` noted on health.py); §6 one capability bullet (browser console URL +
  "not yet security-audited"). No new top-level section; no bloat.

### Issue artifact (committed; FILED in Phase 4, not Phase 2)
- **`.claude/notes/milestones/notebook-surface-expansion-m3/ui-security-audit-issue.md`**
  — the verbatim issue BODY (summary, audit scope, current-defenses baseline, 5 open
  questions, references). Phase-4 fires:
  `gh issue create --repo chris-dare-dev/arXMCP --title "UI security audit:
  server/routes/ui.py + notebooks.py + templates (CAND-13)" --body-file <that file>
  --label "area:security"`.

### Test
- **`tests/test_constitution_ui_claims.py`** (new, 24 tests w/ parametrization;
  3 added in m3-rect for adversary F1/F2/F3 — no "filed issue" overstatement in 06,
  no "zip-bomb" defense claim + real page-count check named, and the
  `## Browser UI surface` cross-references resolve) —
  (1) the stale phrase `"the MCP tool surface is the UI"` is ABSENT (case-insensitive)
  across the TOP-LEVEL `.claude/notes/*.md` (NON-recursive — excludes frozen milestone
  critique artifacts) + `CLAUDE.md` + `README.md`; a guard asserts the scanned set is
  non-empty + includes 02 & 09 (no vacuous pass); (2) `06-mcp-server-design.md`
  contains the "Browser UI surface" section + `/ui/` + `htmx`; (3) `CLAUDE.md` mentions
  the operator console + `/ui/`.

---

## Acceptance criteria status

- [x] **AC1** — `06-mcp-server-design.md` + `CLAUDE.md` describe the actual UI surface;
  a doc-grep test asserts the stale claim is gone. **DEVIATION (recorded below):** the
  literal stale phrase was NOT in those two files — it lived in
  `02-architecture-overview.md` + `09-feature-priorities.md`, which were also edited;
  the doc-grep test scans the whole top-level constitution, not just the two named.
- [x] **AC2** — a UI-security-audit issue is PREPARED for filing at
  `chris-dare-dev/arXMCP` (body committed); the `gh issue create` is the Phase-4
  per-event-authorized external write. The audit itself is NOT executed this cycle.

## Deviations from the brief

1. **The brief named the wrong two files for the stale claim.** Both researchers +
   the orchestrator's grep confirmed `06-mcp-server-design.md` and `CLAUDE.md` never
   contained "the MCP tool surface is the UI" (they had an OMISSION). The literal
   claim was in `02-architecture-overview.md:150` + `09-feature-priorities.md:151`.
   m3 edits all four files: deletes the false absolute from 02+09, adds the UI
   description to 06+CLAUDE.md. The doc-grep test scans broadly so the surviving claim
   couldn't slip through (brief-2 FM-1/FM-5).
2. **The doc-grep test scans the whole top-level constitution**, not "06 + CLAUDE.md"
   literally — the literal reading would pass vacuously.

## Test surface

New: `tests/test_constitution_ui_claims.py` (21). Changed: 4 constitution docs. No
source/code change. ruff clean; existing doc guards (`test_tier_gates_doc.py`,
`test_langfuse_doc.py`) still green.

## Byte-stability / scope

No `server/tools.py`, `EXPECTED_TOOL_SCHEMA_SHA256`, `server/prompts.py`,
`EXPECTED_BP1_SHA256`, or any `/mcp` / handler change. Docs + one test + one prepared
issue body only.

## External writes required

| type | target | why | gate |
|---|---|---|---|
| `gh issue create` | `chris-dare-dev/arXMCP` | file the UI-security-audit tracking issue (CAND-13) | Phase-4, per-event authorized; NOT executed in Phase 2 |
