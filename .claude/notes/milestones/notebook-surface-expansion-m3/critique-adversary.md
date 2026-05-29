# Critique — notebook-surface-expansion-m3

**Critic:** adversary
**Generated:** 2026-05-29T00:00:00Z
**Commit range:** eb8088db6dc2a8259905939cedb835efc3947059..23b61d35ded4a2dac1323c40e7ad93d1ca717c0d
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: a careful, well-scoped docs-only constitution refresh whose only
  defects are two FACTUAL inaccuracies in the new `06-mcp-server-design.md` UI section
  — the cardinal sin for a milestone whose whole job is making the constitution true.
- Finding counts: 0 CRITICAL, 0 HIGH, 2 MEDIUM, 1 LOW.
- Highest-risk file: `.claude/notes/06-mcp-server-design.md:489` (claims the UI audit is
  a "filed issue" — `gh issue list` shows it is NOT filed; only the body is committed).
- Both MEDIUM findings sit on the SAME surface (the new `## Browser UI surface` section in
  06): one overstates issue-tracking state, one names a "zip-bomb" defense the code lacks.
  The issue-body artifact is MORE accurate than the constitution on both points — the
  fix is to align 06 down to what the code + repo actually contain.
- All eight axes walked. Byte-stability, external-write boundary, doc placement, no-fork,
  local-first, MCP spec, tier sequencing: clean. The doc-grep guard test is robust
  (non-vacuous, has an explicit non-empty guard, would fail on regression).
- Stale-claim sweep is complete: no live "MCP tool surface is the UI" survivor in any
  scanned-or-unscanned top-level doc in the main tree (only frozen m3 artifacts +
  out-of-scope `.claude/worktrees/` copies + a DIFFERENT phrase in snippet-contract.md).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — 06 claims UI audit is a "filed issue" but it is NOT filed

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** .claude/notes/06-mcp-server-design.md:489
- **What:** The new `## Browser UI surface` section states the deferred UI audit "is
  tracked as a filed issue at `chris-dare-dev/arXMCP` (CAND-13; notebook-surface-expansion-m3)".
  But filing is an explicit Phase-4-gated `gh issue create` (per the milestone's own
  External-writes table) that must NOT run in Phase 2 — and `gh issue list --repo
  chris-dare-dev/arXMCP --state all` returns only issues #1–#8 (none a UI audit; next
  number is #9). At commit time the issue is PREPARED (body committed at
  `ui-security-audit-issue.md`), not filed.
- **Why it matters:** The constitution asserts a fact that is false at commit time. A
  future agent reading 06 will try to find a tracker entry that does not exist, or
  assume the audit is on the backlog when it is not. An inaccurate constitution is worse
  than a stale one — and this milestone's entire purpose is constitution accuracy.
  CLAUDE.md §6:357 uses the careful "tracked at `chris-dare-dev/arXMCP`" (defensible);
  06:489 uniquely overstates to "filed issue".
- **Proposed fix:** In `06-mcp-server-design.md:489`, change "is tracked as a filed issue
  at `chris-dare-dev/arXMCP`" to "is tracked for filing at `chris-dare-dev/arXMCP` (issue
  body prepared at `.claude/notes/milestones/notebook-surface-expansion-m3/ui-security-audit-issue.md`;
  `gh issue create` is the Phase-4 external write)". If Phase 4 DOES file the issue, the
  cleaner fix is to file it first, then back-fill the real `#N` into 06:489 and CLAUDE.md:357.
- **Regression guard:** Extend `tests/test_constitution_ui_claims.py` with an assertion
  that 06 does NOT contain the substring "filed issue" unless it is immediately followed
  by a `#<digits>` issue reference (i.e. forbid the unqualified "filed issue" claim while
  the body is only prepared). Cheap string assertion; no fixtures.

### F2 — 06 names a "zip-bomb" upload check that does not exist in code

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** .claude/notes/06-mcp-server-design.md:485
- **What:** The security-posture bullet says "PDF upload preflight
  (JavaScript/polyglot/zip-bomb checks)". The actual upload preflight in
  `server/routes/notebooks.py` (`_pdf_*` helpers, sequence documented at
  notebooks.py:740-792) runs exactly four checks: magic-byte sniff (`_is_pdf_bytes`),
  polyglot tail-scan (`_pdf_polyglot_check`, PDF+ZIP / PDF+HTML), JavaScript/active-content
  tokens (`tools.security.pdfid.find_javascript`), and declared-page-count cap
  (`_pdf_declared_page_count`). A grep for `zip.?bomb|decompress|expansion.?ratio|inflate|
  zlib` across `server/routes/notebooks.py` + `tools/security/` returns nothing — there is
  NO decompression-bomb guard.
- **Why it matters:** The constitution overstates the security posture, claiming a
  defense (zip-bomb) the server does not implement. This is exactly the surface a future
  security audit will read as a baseline; an inflated baseline causes the audit to skip a
  real gap. Notably the milestone's OWN issue body (`ui-security-audit-issue.md`) is
  correct here: it lists "page-count checks" as a current defense and raises zip-bomb only
  as Open Question #2 to be answered by the audit. The constitution contradicts the issue.
- **Proposed fix:** In `06-mcp-server-design.md:485`, change "JavaScript/polyglot/zip-bomb
  checks" to "JavaScript/polyglot/page-count checks" (mirroring the issue body's accurate
  baseline). Do not claim a decompression-bomb guard until one ships.
- **Regression guard:** Add a string assertion in `tests/test_constitution_ui_claims.py`
  that if 06 names a "zip-bomb" preflight check it is described as an Open Question / TODO,
  not a current defense — or simply assert 06 lists "page-count" among the preflight checks
  to keep it pinned to the real code. Cheap; no source dependency beyond reading 06.

### F3 — Cross-references to 06 use a quoted section title fragile to renames

- **Severity:** LOW
- **Source:** adversary
- **File:** .claude/notes/02-architecture-overview.md:154
- **What:** `02-architecture-overview.md`, `09-feature-priorities.md`, and CLAUDE.md §2/§6
  all cross-reference `06-mcp-server-design.md § "Browser UI surface"` by quoted section
  title. The title resolves today (06:428 is `## Browser UI surface`), but the doc-grep
  test only asserts the literal string "Browser UI surface" exists in 06 — it does not
  assert the three referrers still point at a live section, so a future rename of the 06
  heading would silently orphan three cross-references.
- **Why it matters:** Purely a maintainability foot-gun; no current breakage. Title-based
  anchors are brittle across the four-file fan-out this milestone created.
- **Proposed fix:** Optional. If desired, add one assertion to
  `tests/test_constitution_ui_claims.py` that every file naming `§ "Browser UI surface"`
  is matched by the literal `## Browser UI surface` heading existing in 06 — turning the
  cross-reference into a checked link. Defer if Phase 4 budget is tight.
- **Regression guard:** The optional test above; otherwise no guard (LOW, deferred).

## What was done well

- The implementer correctly OVERRODE the brief's wrong file targets: both researchers and
  the orchestrator grep confirmed the literal stale phrase lived in 02:150 + 09:151, NOT
  in 06 + CLAUDE.md as the brief claimed. Editing all four files (delete the false absolute
  in 02/09, add the description to 06/CLAUDE.md) is the correct resolution, and the
  deviation is explicitly recorded in the implementation summary.
- The doc-grep guard test is genuinely robust, not vacuous: `test_scanned_set_is_nonempty`
  asserts `len(docs) >= 10` AND that 02 + 09 are in scope, defeating the silent-empty-glob
  failure mode; the parametrized absence scan is case-insensitive
  (`_STALE_PHRASE = "mcp tool surface is the ui"`); and reintroducing the phrase into any
  scanned doc would fail that doc's parametrized case. 21 tests pass; ruff clean.
- The non-recursive `.claude/notes/*.md` glob deliberately and correctly excludes frozen
  milestone-critique artifacts (e.g. E13_S06's "no frontend exists in arXMCP") so immutable
  historical records do not trip the guard — and the test docstring documents exactly why.
- The external-write boundary is respected: `gh issue create` appears ONLY as Markdown
  prose describing the Phase-4 step; no `subprocess`/`os.system`/`git push`/`gh` execution
  was introduced, and the issue is committed as a body artifact, not filed.
- Doc placement is clean: all five new `.md` files are under
  `.claude/notes/milestones/notebook-surface-expansion-m3/`, and the only non-`.claude`
  new file is the correctly-placed `tests/test_constitution_ui_claims.py`.
- CLAUDE.md additions are genuinely minimal (one §2 sentence, two §5 layout rows, one §6
  bullet) — no new top-level section, no bloat to the always-loaded file, exactly as the
  brief's FM-6 warned against.
- Byte-stability is fully preserved: the range touches no `server/tools.py`,
  `EXPECTED_TOOL_SCHEMA_SHA256`, `EXPECTED_BP1_SHA256`, `server/prompts.py`, or `/mcp`
  bytes (verified via `git diff --name-only`).
- The vast majority of the new 06 section is accurate against source: the route inventory
  (`GET /ui/`, `/ui/notebooks/{slug}`, the `{paper_id:path}/preview` route, `/ui/status-badge`,
  and the `/ui/api/notebooks/*` REST verbs incl. the m2 `PATCH`) all exist in
  `server/routes/ui.py` + `server/routes/notebooks.py`; the security posture (explicit
  `select_autoescape(default_for_string=True)`, `CONTENT_SECURITY_POLICY_UI` +
  `CONTENT_SECURITY_POLICY_PREVIEW` with `frame-ancestors 'none'`,
  `SecFetchSiteMiddleware(exempt_prefixes=("/ui",))`, `validate_slug`, control-char strip,
  mass-assignment-guarded PATCH) matches the code exactly.
- The 09 SUPERSEDED status stays coherent: the inline parenthetical reinforces the existing
  top-of-file "Status: SUPERSEDED" marker rather than contradicting it.

## Recommended rectification order

1. **F2** — one-word doc fix (`zip-bomb` → `page-count` at 06:485); aligns the constitution
   with both the code and the milestone's own issue body. Highest accuracy-per-LOC.
2. **F1** — reword 06:489 from "filed issue" to "prepared/tracked-for-filing" (or file the
   issue in Phase 4 and back-fill the real `#N` into 06:489 + CLAUDE.md:357). Touches the
   same 06 section as F2, so batch them.
3. **F3** — optional cross-reference-integrity assertion; defer unless Phase 4 has budget.

## Rectification status (filled by Phase 4)

Adversary SHIP-WITH-FIXES (0C/0H/2M/1L). All three findings FIXED (both MEDIUM
inaccuracies + the LOW cross-ref guard — all cheap doc/test changes on the
milestone's headline deliverable). m3 test count 21 → 24. ruff clean.

- **F2 (MEDIUM) — FIXED.** `06-mcp-server-design.md:485` no longer claims a
  "zip-bomb" preflight check (the upload path has no decompression-bomb guard).
  Reworded to the four real checks (magic-byte sniff / polyglot tail-scan /
  JavaScript-token scan / declared-page-count cap) + an explicit NOTE that the
  decompression-bomb guard is an OPEN QUESTION for the audit, not a current
  defense — matching the code and the milestone's own issue body. Regression
  guard: `test_06_does_not_claim_zipbomb_defense` (asserts "zip-bomb" absent +
  "page-count" present in 06).
- **F1 (MEDIUM) — FIXED.** `06-mcp-server-design.md:489` no longer says the UI
  audit "is tracked as a filed issue" (it is PREPARED, not filed — filing is the
  Phase-4 `gh issue create`). Reworded to "tracked for filing … issue body
  prepared at <path> … gh issue create is the Phase-4 external write." Regression
  guard: `test_06_does_not_overstate_issue_as_filed` (forbids the unqualified
  "filed issue" string in 06). If the issue is filed in Phase 4, the real `#N`
  is back-filled into 06 + CLAUDE.md.
- **F3 (LOW) — FIXED (cheap).** Added `test_browser_ui_crossrefs_resolve`: the
  literal `## Browser UI surface` heading must exist in 06, and 02 / 09 /
  CLAUDE.md must each carry the cross-reference — turning the title-based
  cross-refs into a checked link so a future 06 heading rename can't silently
  orphan the three referrers.
