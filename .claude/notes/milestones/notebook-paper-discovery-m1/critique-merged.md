# Critique — notebook-paper-discovery-m1

**Critic:** adversary
**Generated:** 2026-05-31T00:00:00Z
**Commit range:** 867edb726addb8b51ceac87a83c24a707af9d366..82e3ba5939e5f8919dbbedadef1533ee3f365922
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: one MEDIUM doc-vs-code inconsistency on the description control-char claim; no CRITICAL or HIGH findings.
- 0 CRITICAL, 0 HIGH, 1 MEDIUM, 1 LOW — clean implementation on all security-critical axes.
- Highest-risk citation: `server/routes/notebooks.py:370` — `description` reaches the store raw on the create path, contradicting the design note's "control chars stripped before storage" claim.
- Migration atomicity (FM-3) is correctly handled: `BEGIN`/`COMMIT` wraps both ALTERs and `PRAGMA user_version = 5`; PRAGMA user_version is transactional and rolls back on ROLLBACK (verified by live SQLite test).
- All 8 axes walked; no cache, math-fidelity, MCP spec, local-first, tier-sequencing, or fork-policy violations found.
- FM-4 (SELECT column list) and FM-5 (INSERT branch parity) are correctly implemented in both INSERT branches and both SELECT queries.
- XSS surface is clean: no `| safe` filter anywhere in the new template code; `_topic_fragment` html-escapes both values; Jinja2 autoescape applies to the initial render.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Cross-critic agreement

_None — no file:line region was flagged by ≥ 2 critics._

<!-- end:cross-critic-agreement -->

## Findings

### F1 — description not stripped on create path; design note claims it is

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/routes/notebooks.py:370
- **What:** `create_notebook` passes `description=body.description` directly to the store without calling `_CONTROL_CHARS_RE.sub("", ...)`. The PATCH handler at line 598 does perform stripping (`cleaned_desc = _CONTROL_CHARS_RE.sub("", body.description)`), but the POST create path does not. As a result, a `description` containing C0 control characters (NUL, newlines, tabs, DEL) supplied at notebook-creation time is stored verbatim.
- **Why it matters:** The design note at `.claude/notes/notebook-discovery-model.md:27` explicitly states "control chars stripped before storage" for the `description` field. This is the authoritative m2-m4 contract document; m2's arXiv Atom query builder will read `description` as an `abs:`/`ti:` keyword string and may be written assuming it is clean text. The inconsistency is the same pre-existing gap as `display_name` on the create path (line 364), but for `display_name` no analogous cross-milestone contract document makes the "stripped before storage" claim.
- **Proposed fix:** Add a one-liner before the `store.create_notebook(...)` call at lines 361-371:
  ```python
  cleaned_desc = _CONTROL_CHARS_RE.sub("", body.description)
  ```
  Then pass `description=cleaned_desc` at line 370. Mirror the same fix for `display_name=body.display_name` at line 364 if desired for consistency, but the doc contract makes it load-bearing only for `description`.
- **Regression guard:** Add a test in `tests/test_notebook_api.py::TestNotebookTopicMetadata` — `test_create_strips_control_chars_from_description` — that POSTs a description containing `"\x01tab\nline\x7f"` and asserts the persisted value is `"tabline"`.

### F2 — design note cross-references `plans/` which is outside the CLAUDE.md §1 allowed layout

- **Severity:** LOW
- **Source:** adversary
- **File:** .claude/notes/notebook-discovery-model.md:109
- **What:** The cross-references section at line 109 reads `Roadmap: plans/notebook-paper-discovery-roadmap.md`. The `plans/` directory at the repo root is outside the doc-placement table in CLAUDE.md §1 (only `README.md`, `CLAUDE.md`, `CHANGES.md`, `SECURITY.md`, `OWNERS.md` allowed at root; all other Markdown under `.claude/`). The `plans/` directory itself is pre-existing and was not introduced by this milestone.
- **Why it matters:** The CLAUDE.md §1 doc-placement rule is described as "strict and load-bearing." A design note that is the authoritative contract for m2-m4 should not reference a path outside the canonical layout, as it normalizes the deviation and future implementers may create additional files there.
- **Proposed fix:** Update the cross-reference at line 109 to the canonical location, or confirm that `plans/` is intentional by adding it to the allowed-layout table in CLAUDE.md. No code change needed; the roadmap file itself can stay where it is since it is pre-existing.

## What was done well

- Migration atomicity (FM-3): the v4→v5 block correctly wraps both ALTERs and the `PRAGMA user_version = 5` bump in an explicit `BEGIN`/`COMMIT` with a `try/except ROLLBACK`. This is a strict improvement over the existing v1→v4 blocks and eliminates the duplicate-column crash-loop failure mode. The idempotency test confirms re-opening a v5 DB does not re-run the block.
- FM-4 (SELECT parity): both `list_notebooks` and `get_notebook` SELECT queries were updated in lockstep — `discovery_category, description` added to both column lists AND both returned dicts at indices 8 and 9, matching the SELECT column order.
- FM-5 (INSERT branch parity): both INSERT branches in `create_notebook` (the `parse_status is None` branch and the explicit `parse_status` branch) include the two new columns with matching placeholder counts (7-tuple and 8-tuple respectively). No silent-drop risk.
- Validation coverage: `_validate_discovery_category` is wired into BOTH the `create_notebook` handler (line 331) and the `update_notebook_topic` handler (line 591). Empty string is accepted (FM-1). The function uses `if … raise NotebookError(...)`, not `assert` (CLAUDE.md §4.7 compliance).
- XSS posture is sound: `_topic_fragment` explicitly `html.escape`s both `discovery_category` and `description` (lines 525-526). No `| safe` filter was introduced anywhere in the new template code (confirmed by full template grep). Jinja2 autoescape covers the initial page render including the `{{ notebook.description }}` textarea value.
- Mass-assignment defense: `NotebookTopicUpdate` carries only `discovery_category` and `description`. The rename endpoint (`PATCH /notebooks/{slug}`) accepts only `NotebookRename` with only `display_name`. No scope creep between the two update surfaces.
- `validate_slug` is called first in `update_notebook_topic` (line 564) before any category validation or store access, matching the security posture of `rename_notebook`.
- SQL is fully parameterized throughout: all INSERT and UPDATE statements use `?` placeholders with tuple arguments. No string interpolation into SQL anywhere in the diff.
- Control-char stripping on the PATCH path: `_CONTROL_CHARS_RE.sub("", body.description)` is applied before `store.update_topic(...)` at line 598, mirroring the rename handler's pattern at line 520.
- The design note (`.claude/notes/notebook-discovery-model.md`) is placed under `.claude/notes/` per CLAUDE.md §1, is clearly scoped as authoritative for m2-m4, and correctly locks the propose→confirm model, channel-dedup boundary, and backup-scope claim.

## Recommended rectification order

1. **F1 (MEDIUM):** Strip control chars from `description` in the `create_notebook` handler before passing to the store — one-line fix at `server/routes/notebooks.py:370` + one test. The design note makes an explicit contract claim that m2's query builder will rely on; fixing this keeps the contract honest before m2 is built.
2. **F2 (LOW):** Update the cross-reference in the design note (or canonicalize the `plans/` directory in CLAUDE.md). Defer if the plans directory convention is intentional and known.

## deferred_findings

- F2 (LOW) — `plans/` cross-reference in design note — may defer if `plans/` layout is intentional and accepted by the project.

## Rectification status (filled by Phase 4)

- F1 (MEDIUM) — fixed in `server/routes/notebooks.py` (create handler now strips
  C0 control chars + DEL from `description` via `_CONTROL_CHARS_RE` before
  `store.create_notebook`, mirroring the PATCH /topic path; the create response
  returns the cleaned value). Regression guard:
  `tests/test_notebook_api.py::TestNotebookTopicMetadata::test_create_strips_control_chars_from_description`.
- F2 (LOW) — deferred. The cross-reference `plans/notebook-paper-discovery-roadmap.md`
  is accurate: `plans/<slug>-roadmap.md` is the `roadmap` skill's documented
  canonical output path (`.claude/skills/roadmap/SKILL.md`). Moving the roadmap
  would break the skill contract; the `plans/` directory is pre-existing and not
  introduced by this milestone. No change.

Re-verify gate: F1 re-verified against `server/routes/notebooks.py` (the cited
raw `description=body.description` pass-through still matched the finding pre-fix).
No findings invalidated. Adversary invalidation rate: 0%.
