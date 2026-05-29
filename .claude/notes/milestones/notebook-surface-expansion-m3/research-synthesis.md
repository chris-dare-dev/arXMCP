# Research Synthesis — notebook-surface-expansion-m3

**Milestone:** Constitution refreshed (drop the stale "no frontend" claim; describe
the shipped UI) + a UI-security-audit issue FILED at `chris-dare-dev/arXMCP`.
**Mode:** standard (2× Sonnet). Both briefs `ok`. 1 external write (Phase-4 gated).
**Implementation path:** INLINE (4 doc edits + 1 issue-body md + 1 doc-grep test;
no code, no novel arch).

---

## Load-bearing decisions (orchestrator-resolved)

### D1 — The brief named the WRONG two files. Edit FOUR constitution files.

Both researchers independently confirmed (and the orchestrator's grep proves): the
literal stale claim is NOT in `06-mcp-server-design.md` or `CLAUDE.md`. It is the
phrase **"The MCP tool surface is the UI"**, present in exactly two TOP-LEVEL notes:
- `.claude/notes/02-architecture-overview.md:150` — `- Beautiful UI. The MCP tool surface is the UI.` (Non-goals for v1)
- `.claude/notes/09-feature-priorities.md:151` — `- **A web UI.** The MCP tool surface is the UI.` (Things to explicitly NOT build in v1)

So the work is:
- **Edit 02 + 09** to remove the now-FALSE absolute (a browser UI ships).
- **Add a UI-surface DESCRIPTION to 06 + CLAUDE.md** — these never carried the false
  claim; their gap is an OMISSION. This is the literal AC target ("they describe the
  actual UI surface").

`09-feature-priorities.md` is marked SUPERSEDED in CLAUDE.md §11, but it still carries
a false absolute that misleads any agent reading it — edit it anyway (light touch,
keep it honest about the loopback-only operator console, not a general research UI).

### D2 — Doc-grep guard test scans BROADLY (not vacuously against 06/CLAUDE.md)

The AC says "a doc-grep test asserts the stale phrase is gone from both [06+CLAUDE.md]"
— but the phrase was never there, so that literal test passes vacuously (brief-2 FM-1).
The correct, stronger test (both researchers): scan the **top-level** constitution
(`.claude/notes/*.md`, NON-recursive) + `CLAUDE.md` + `README.md` for the exact phrase
`"The MCP tool surface is the UI"` and assert ABSENT; PLUS assert `06-mcp-server-design.md`
now describes the UI (contains `/ui/` and `htmx`).

**Do NOT recurse into `.claude/notes/milestones/`** — frozen critique artifacts (e.g.
`E13_S06/critique-merged.md` "no frontend exists in arXMCP") are immutable historical
records and use different wording; scanning only top-level notes avoids them cleanly.
Precedent: `tests/test_langfuse_doc.py` (`REPO_ROOT = parents[1]`, `read_text`,
parametrized string assertions). New file: `tests/test_constitution_ui_claims.py`.

### D3 — Issue body → committed artifact; `gh` fires ONLY in Phase 4

Write the issue body to
`.claude/notes/milestones/notebook-surface-expansion-m3/ui-security-audit-issue.md`
(agent-internal → `.claude/` per doc-placement rule), committed in the feat commit.
**Phase 2 must NOT run `gh issue create`** (brief-2 FM-2: it's a CRITICAL-banned
Phase-2 pattern; external-write boundary). Phase 4, after per-event user authorization,
runs:
```
gh issue create --repo chris-dare-dev/arXMCP \
  --title "UI security audit: server/routes/ui.py + notebooks.py + templates (CAND-13)" \
  --body-file .claude/notes/milestones/notebook-surface-expansion-m3/ui-security-audit-issue.md \
  --label "area:security"
```
Precedent: `.claude/notes/milestones/E13_S10/_file_issues.py` (`--body-file`; labels
silently dropped if absent). gh auth verified valid (account `chris-dare-dev`); existing
issues #1–#8, next is #9; NO existing UI-audit issue → safe, non-duplicate.

### D4 — 06 gets a `## Browser UI surface` section; CLAUDE.md stays lean

Insert into `06-mcp-server-design.md` a new `## Browser UI surface` section (just before
"What this server does NOT do") enumerating the actual endpoints + posture (see the
checklist). CLAUDE.md gets MINIMAL additions only (no new top-level section, no bloat —
the file is re-read every session): a §2 sentence, a §5 directory-layout pair of rows
(`server/routes/` + `frontend/`), and a §6 capability bullet. Brief-2 FM-6.

### D5 — Accurate UI surface (read from source, not guessed)

The endpoints to document (verified by both researchers against `server/routes/ui.py`
+ `server/routes/notebooks.py`):
- **HTML pages:** `GET /ui/`, `GET /ui/notebooks/{slug}`, `GET /ui/notebooks/{slug}/papers/{paper_id}/preview` (tight CSP + meta-refresh strip), `GET /ui/status-badge` (m4).
- **REST/htmx (`/ui/api/notebooks/*`):** list/create/delete; `PATCH` rename (m2,
  mass-assignment-guarded); papers list/add/remove; upload (PDF+ar5iv); ingest trigger/poll.
- **Posture:** server-rendered Jinja2 + vendored htmx (NO SPA / NO Node build chain —
  hard constraint); explicit autoescape; `CONTENT_SECURITY_POLICY_UI` + tighter preview
  CSP; `SecFetchSiteMiddleware(exempt_prefixes=("/ui",))` + Origin + Host validation;
  loopback-only bind.

---

## Implementation checklist

1. `.claude/notes/02-architecture-overview.md:150` — replace the false bullet with one
   that states a loopback-only Jinja2+htmx operator console at `/ui/` ships (not a
   general research UI; no SPA/build chain).
2. `.claude/notes/09-feature-priorities.md:151` — same correction (keep honest re:
   superseded status).
3. `.claude/notes/06-mcp-server-design.md` — add `## Browser UI surface` (endpoints +
   posture per D5) before "What this server does NOT do".
4. `CLAUDE.md` — §2 one sentence; §5 add `server/routes/` + `frontend/` rows; §6 one
   capability bullet. Minimal.
5. `.claude/notes/milestones/notebook-surface-expansion-m3/ui-security-audit-issue.md`
   — the issue body (title + scope + current-defenses baseline + open questions +
   references). Committed in feat; consumed by Phase-4 `gh issue create --body-file`.
6. `tests/test_constitution_ui_claims.py` — (a) stale phrase absent across top-level
   notes + CLAUDE.md + README (non-recursive); (b) 06 contains `/ui/` and `htmx`.

## What this milestone does NOT touch

No `server/tools.py`, `EXPECTED_TOOL_SCHEMA_SHA256`, `server/prompts.py`,
`EXPECTED_BP1_SHA256`, or any `/mcp` / handler code. No schema migration. Pure docs +
one test + one filed issue.

## Open questions

None blocking. The only judgment call (resolved in D1): edit 02 + 09 in addition to the
two files the brief named — required or the doc-grep guard catches the surviving claim.

## External writes required

| type | target | why | gate |
|---|---|---|---|
| `gh issue create` | `chris-dare-dev/arXMCP` | File the UI-security-audit tracking issue (CAND-13; E13 deferred the UI audit) | Phase-4, per-event authorized; NOT executed in Phase 2 |
