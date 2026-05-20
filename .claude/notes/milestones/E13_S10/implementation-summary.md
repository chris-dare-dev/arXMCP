# Implementation summary — E13_S10

**Milestone:** E13_S10 — Cumulative threat-model coverage review
**Implementation base SHA:** `dc96387ab11f9d2325ce8fb42499faf794953f36`
**Path:** inline (orchestrator implemented directly in main session)

## One-line summary

Shipped the cumulative threat-model coverage doc at
`.claude/docs/security-threat-model-coverage.md` (7-threat table +
observability addendum + 6 gap-issue placeholders) and a 21-test
pytest staleness gate at
`tests/security/test_threat_model_coverage.py` that pins the audit
chain against future doc/test drift. **No production code changed**
— this is a pure documentation + verification milestone.

## Files changed

| File | Change | Why |
|---|---|---|
| `.claude/docs/security-threat-model-coverage.md` | NEW | Audit deliverable: summary table + per-threat sections + 6-row gap-issue triage table + forward-maintenance contract |
| `tests/security/test_threat_model_coverage.py` | NEW | 21 tests across 5 classes pinning doc structure, cited-file existence, gap-row well-formedness, threat-count parity with `08-security-observability-ops.md`, and per-milestone (E13_S01–S10) mention coverage |

## Acceptance criteria status

| AC | Status | Evidence |
|---|---|---|
| `docs/security/threat-model-coverage.md` committed with all 7 threats covered | ✅ (reframed: `.claude/docs/security-threat-model-coverage.md` per CLAUDE.md §1) | `TestThreatStructure::test_all_seven_threats_have_section_heading` + `test_all_seven_threats_appear_in_summary_table` |
| Every threat has at least one automated test linked in the table | ✅ | `TestCitedTestFilesExist::test_every_cited_file_exists` + `test_at_least_one_test_file_cited` + inverse `test_every_security_test_file_is_cited` |
| Any gap has a filed issue linked in the "Gap issues" column | ⚠️ **Phase-4 gated** — 6 gap candidates documented as `(TODO file issue: ...)` placeholders. `gh issue create` is an external write requiring per-event user authorization at the Phase-4 boundary. On user approval, placeholders become `[#NNN](URL)` markdown links. On user skip, placeholders remain and the doc body notes the decision. |
| Document reviewed by the developer and committed (not just drafted) | ⚠️ **process gate** — the user reviews the coverage doc at the Phase-4 boundary alongside the gap-issue authorization conversation. The user's authorization (or explicit skip) IS the review event; the final chore commit's body records the decision. |

## Brief deviations (all resolved by orchestrator synthesis)

1. **`docs/security/threat-model-coverage.md` → `.claude/docs/security-threat-model-coverage.md`** — CLAUDE.md §1 restricts `docs/` to operator-facing content (today: only `docs/install.md`). Every prior E13 audit doc landed under `.claude/docs/`; this milestone follows the precedent.

2. **"7-row table" preserved + 1 observability-addendum row** — the brief is explicit on "7-row table" for the numbered threats. E13_S08's logging redaction addresses the same threat-model file but a SEPARATE subsection ("Logging") and is not a numbered threat. Synthesis: keep the table at 7 + add an explicit "Observability addendum" row labeled `—` (em-dash, not a threat number) so the audit chain is complete without violating the brief's table-shape contract.

3. **Gap-issue filing deferred to Phase 4** — the brief says "any gap must be filed". The project's external-write boundary policy requires per-event user authorization for `gh issue create`. Synthesis: compile the gap list in Phase 2 as `(TODO file issue: ...)` placeholders; surface to the user at the Phase-4 boundary; file only what the user authorizes.

4. **Fictional milestone IDs corrected** — brief-style citations like "E07_S12 (specified the regex)" were sometimes pointing at non-existent milestones (E07 only has S01–S04). The coverage doc uses real file:line citations of where each mitigation actually shipped, not the brief's fictional epic-ID strings.

## Tests

- **New test file:** `tests/security/test_threat_model_coverage.py` (21 tests, all passing)
- **Test classes:**
  - `TestCoverageDocExists` (3 tests) — doc presence, non-empty body, threat-model-source link
  - `TestCitedTestFilesExist` (3 tests) — at least one file cited, every cited file exists, inverse — every `tests/security/test_*.py` is cited
  - `TestThreatStructure` (3 tests) — `## Threat N` sections for all 7 numbered threats, summary-table rows for all 7, threat-count parity with `08-security-observability-ops.md`
  - `TestGapRowsWellFormed` (1 test) — every Gap-cell is `(none)` / em-dash / `(TODO file issue: ...)` / GitHub issue URL
  - `TestForwardMaintenanceContractDocumented` (1 test) — doc must mention the "new threat → paired doc update" rule
  - Parametrized smoke: 10 tests asserting each E13 milestone ID appears in the doc

- **Forward-maintenance bite:** `TestThreatStructure::test_threat_model_source_threat_count_matches` reads `08-security-observability-ops.md` and counts `### Threat N:` headings. If a future commit adds a Threat 8 to the threat-model file, this test fires loudly until the coverage doc and `EXPECTED_THREAT_NUMBERS` are both updated in the same change.

## Project-check status

- `ruff check .` → clean
- `pytest tests/security/test_threat_model_coverage.py` → 21 passed
- Full `pytest` → 2099 passed (was 2079 before this milestone → +20). 30 pre-existing Windows-platform failures unchanged.

## External writes required

| Type | Target | Why | Blocking |
|---|---|---|---|
| `gh issue create` × 6 | github.com/chris-dare-dev/arXMCP | File gap-issue rows G1–G6 (byte-cap coverage, redirect-host pinning, LaTeXML sandbox, BGE-M3 SHA bump, `ARXMCP_PIN_ARXIV_CA` wiring, sanitizer default-on) | NO — milestone can ship clean with `(TODO file issue)` placeholders if the user skips |

The Phase-4 boundary will surface each gap row to the user with a one-line description and ask for per-row authorization. On approval, the issue is filed and the placeholder in the coverage doc is replaced with the resulting `[#NNN — title](URL)` markdown link. The user can also skip individual rows — the placeholder remains and the doc body notes the decision.

## Anything notable for the critic

1. **The doc itself is the deliverable** — no production code paths change. The adversary should focus on (a) whether the doc accurately reflects the v1 security posture (no fabricated coverage claims), (b) whether the gap list is complete (any missing coverage hole the audit missed), and (c) whether the pytest gate would actually catch the failure modes listed in the synthesis.

2. **`TestCitedTestFilesExist::test_every_security_test_file_is_cited` is the inverse contract** — it asserts every real `tests/security/test_*.py` file is mentioned in the doc. This catches "added a test file but forgot to update the coverage doc" drift. The only allow-list entry is `test_threat_model_coverage.py` itself (the doc's own gate — meta-recursive citation would be noise).

3. **Forward-maintenance enforcement is dual** — `EXPECTED_THREAT_NUMBERS` is a tuple constant in the test file. A future Threat 8 in `08-security-observability-ops.md` triggers `test_threat_model_source_threat_count_matches` to fail with a clear message demanding both the coverage doc AND the test constant be updated in the same change. This pins the "paired update" contract.

4. **Gap-row format is intentionally loose** — the regex accepts `(none)`, em-dash `—`, `(TODO file issue: ...)`, or any `github.com/.../issues/N` URL. This is forgiving on purpose so a future developer who wants to use a different placeholder phrasing (e.g., `(TBD)` for very-low-priority gaps) doesn't have to update the test in lockstep. The contract is "well-formed enough that a reader can tell what state the gap is in", not "matches one of three exact strings".

5. **No-fork policy compliance** — nothing copied from OSS audit-doc templates. The doc structure mirrors the E13_S01–S07 audit-doc shape (which itself was new code per milestone).

6. **No `EXPECTED_TOOL_SCHEMA_SHA256` re-pin** — documentation is internal infrastructure; tool surface unchanged.

7. **Brief AC ambiguity on "developer review"** — surfaced in the synthesis as a process-gate (vs. automation-gate) decision. The Phase-4 user-authorization conversation IS the review; the chore commit's body should explicitly record the user's decision (e.g., "User reviewed the coverage doc and authorized filing 4/6 gap issues; G3 + G5 deferred per user request"). This is the closest machinable contract we can produce for "reviewed by the developer".
