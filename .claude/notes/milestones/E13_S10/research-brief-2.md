# Research Brief — E13_S10

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-19T23:50:00Z

## In-codebase context

E13_S10 is **not** a feature-implementation milestone. All E13_S01–S09 are shipped
(`phase: complete`, no deferred findings blocking closure). E13_S10's sole deliverable
is a cumulative threat-model coverage table that documents:

1. Which epic first shipped each mitigation
2. Which E13 milestone audited it
3. Which test files exercise it
4. Any gaps found (filed as GitHub issues + linked from the doc)

From `.claude/notes/08-security-observability-ops.md` § Threat model, the 7 threats are:

**Threat 1:** Path traversal via `paper_id` → **Threat 2:** Indirect prompt injection
from chunks → **Threat 3:** LaTeXML on hostile source → **Threat 4:** Resource
exhaustion via tool arguments → **Threat 5:** Origin spoofing on HTTP transport →
**Threat 6:** Supply-chain (model weights) → **Threat 7:** Source ingestion fetches.

Each is fully tested per researcher-1's inventory (E13_S01 covers T1, E13_S02 covers T2,
etc.). The table aggregates them.

**Doc placement correction:** Brief says `docs/security/threat-model-coverage.md`.
CLAUDE.md §1 restricts `docs/` to operator-facing content only. Established precedent
across E13_S01–S07 is `.claude/docs/security-threat-N-audit.md`. **Correct path:**
`.claude/docs/security-threat-model-coverage.md`.

**MCP spec conformance:** The MCP 2025-06-18 spec § "Security and Trust & Safety"
defines four key principles: User Consent, Data Privacy, Tool Safety, and LLM Sampling
Controls. **None of these introduce NEW threats beyond arXMCP's 7-threat model.** The
spec is host-facing (LLM app ↔ MCP server) and focuses on user authorization; arXMCP's
threat model is already impl-facing (LLM output → tool args → filesystem/network). No
spec-mandated rows need adding to the coverage table.

## Prior decisions and lessons

From git log and E13_S01–S09 milestone memory:

1. **Fictional milestones already fixed in implementations:** E07_S12 (path-traversal
   regex) shipped but briefs cite non-existent E07_S05+. E13_S01–S09 all implemented
   correctly despite fictional citations. E13_S10 should cite only real milestones
   (E06_S05, E07_S10, E13_SXX range).

2. **Test file naming pattern:** Each E13_SXX ships `tests/security/test_*.py`. 9 files
   exist: `test_path_traversal.py`, `test_delimiters.py`, `test_latexml_sandbox.py`,
   `test_resource_exhaustion.py`, `test_origin_binding.py`, `test_model_pinning.py`,
   `test_source_ingest.py`, `test_bind_regression.py`, `test_log_redaction.py`. E13_S10
   has **no** new test file; it's purely documentation + issue filing.

3. **Audit doc validation precedent:** E13_S08 implemented `TestAuditDocPresence` class
   in `test_log_redaction.py` to verify `.claude/docs/security-observability-logging.md`
   exists. E13_S10 should follow the same pattern: a pytest assertion that validates
   cited test files **actually exist** before closing the audit.

## Failure-mode analysis — audit-specific risks

Five plausible ways this milestone breaks (and how to defend):

### Failure 1: False-positive coverage claim
**Risk:** The table claims `test_path_traversal.py` covers Threat 1, but the file has
been renamed or deleted between E13_S01 landing and E13_S10 audit.

**Defense:** Implement `TestAuditDocCoverage::test_cited_files_exist()` in E13_S10's
test file. Walk the coverage table's "Test files" column, stat each file, and assert
it exists. This catches file-rename drift automatically. Pattern: `tests/security/test_*.py`
glob + dictionary lookup.

### Failure 2: Test file exists but doesn't exercise the threat
**Risk:** A test file was added but is a stub or exercises a different threat. The
table falsely claims coverage.

**Defense:** Cannot be mechanically enforced (would require parsing test AST to verify
function logic). This is a **code-review gate** — Phase 4 implementer must visually
verify each test file tests the claimed threat. Brief AC#2 says "every threat has ≥1
test"; this is a reading check, not an automation.

### Failure 3: Gap issues are filed but not linked from the doc
**Risk:** GitHub issues #123, #124 are filed for byte-cap enforcement gaps, but the
coverage doc's "Gap issues" column is blank or lists the wrong issue numbers.

**Defense:** Implement `TestAuditDocCoverage::test_gap_issues_linked()` that parses
the coverage doc's "Gap issues" column, extracts issue URLs, and verifies each URL
returns HTTP 200 (issues exist). Uses `gh issue view` CLI to verify.

### Failure 4: A new threat is added to 08-security-observability-ops.md after E13_S10
**Risk:** Future work adds Threat 8 (e.g., "Rust dependency supply chain"), but the
E13_S10 coverage doc is never updated. The audit doc becomes stale + misleading.

**Defense:** Document this as a **forward maintenance contract:** The brief AC#3 is
"Any gap must be filed as a GitHub issue and linked before this milestone closes."
Add an AC#5: "Future threats added to 08-security-observability-ops.md require a
corresponding row in the coverage table before the next epic closes." This is a
**process gate**, not a pytest gate. Implementer documents it in the table's footer
or in CLAUDE.md.

### Failure 5: The doc is committed but never reviewed by the user
**Risk:** Brief AC#4 says "Document reviewed by the developer and committed (not just
drafted)." But "reviewed by the developer" has no machinable contract. The doc lands
on main untested.

**Defense:** Make the review explicit in the commit message. Brief says "reviewed by
the developer" — Phase 4 implementer must have the user confirm the coverage table
before pushing. This is a **process gate** (manual authorization at Phase-4
boundary), not an automation gate.

## Gap-triage process recommendations

### Should gaps be filed individually or as a tracking epic?

**Recommend:** File **individually** as GitHub issues. Reason: Each gap has a
different scope (byte-cap enforcement on 5 tools, BGE-M3 SHA bump, etc.) and may have
different assignees/timelines. A single tracking epic would be artificial. Individual
issues allow Kanban-style prioritization.

### Should gap-issue filing be automatic (Phase 2) or gated by user authorization (Phase 4)?

**Recommend:** **Gated by Phase 4 authorization.** The brief says "any gap that
surfaces must be filed"; this is a directive, not a requirement to file blindly. The
implementer should:

1. (Phase 2) Audit all 7 threats + write the coverage table
2. (Phase 3) Adversary critiques the table; identifies any overlooked gaps
3. (Phase 4) Implementer files issues **after user reviews + authorizes**

This prevents automated issue spam (e.g., filing 50 issues if a brief misunderstands
the codebase state).

### Document placeholder pattern

Until the user authorizes issue filing, the coverage doc can use placeholder
references:

```markdown
| Threat 4 | E06_S07/E06_S08/E07_S10 | E13_S04 | test_resource_exhaustion.py | (TODO: #NNN byte-cap coverage gap on 5 tools) |
```

Once issues are filed, replace `(TODO: #NNN ...)` with actual markdown links:
`[#123 - byte-cap enforcement on get_paper](https://github.com/...)`

## Document-validation enforcement

### Yes: Implement pytest gate for file existence

Add to `tests/security/test_coverage.py` or extend `test_log_redaction.py`:

```python
class TestAuditDocCoverage:
    """Validates the E13_S10 threat-model coverage table.
    
    Reads .claude/docs/security-threat-model-coverage.md,
    extracts cited test files, and asserts each exists.
    """
    
    def test_cited_test_files_exist(self):
        """Parse coverage table; verify all test_*.py files exist."""
        # Parse markdown table from .claude/docs/security-threat-model-coverage.md
        # Extract test file names from "Test files" column
        # Assert each file path exists in tests/security/
```

This defends against Failure Mode 1 (file-rename drift). It's a lightweight check
that runs every CI pass.

### Optional: Parse and validate issue URLs

Add optional (non-blocking) validation:

```python
def test_gap_issues_linked_and_valid(self):
    """Extract GitHub issue URLs from 'Gap issues' column.
    
    For each URL, invoke `gh issue view <issue>` and verify
    the issue exists (HTTP 200). Non-critical; skip if gh CLI
    unavailable or repo is offline.
    """
    # Extract URLs like https://github.com/...issues/123
    # Run: gh issue view 123 --json state
    # Assert state == "OPEN" (gap not yet closed)
```

This defends against Failure Mode 3 (broken links). It's optional because it depends
on network access + `gh` CLI availability.

### Yes: Document staleness lint for `make test`

Recommend adding a lint target to `Makefile`:

```makefile
lint-audit-docs:
	@echo "Checking threat-model coverage doc staleness..."
	@pytest tests/security/test_coverage.py::TestAuditDocCoverage --tb=short
```

Run this as part of `make test` so the audit doc is verified on every commit.

## Open questions

1. **File gap issues during E13_S10 implementation, or defer to user authorization?**
   
   **Recommendation:** Defer to Phase 4. The implementer compiles the gap list during
   Phase 2, the adversary critiques it during Phase 3, and the user authorizes filing
   in Phase 4 before pushing. This follows the project's authorization model (Phase 4
   gates external writes like `gh issue create`).

2. **Should pytest gates for doc validity be strict (fail CI) or advisory (warn)?**
   
   **Recommendation:** Strict. The audit doc is the authoritative security posture;
   false claims are worse than missing features. If a test file is renamed, the build
   should fail rather than silently leaving the coverage doc stale.

3. **How detailed should the table's "Test files" column be?**
   
   **Recommendation:** List file paths only (e.g., `tests/security/test_path_traversal.py`).
   The table is a high-level index; readers can click the link to view test details.
   Avoid listing individual test class/function names — that's implementation churn.

4. **Should the coverage table include recommended follow-up work (Tier-6 hardening)?**
   
   **Recommendation:** No. Keep the table strictly to the 7 documented threats. Future
   hardening (e.g., "add mTLS for E14") belongs in individual GitHub issues, not the
   coverage doc. The doc is the audit checkpoint, not a roadmap.

5. **Should the coverage doc be versioned alongside release tags?**
   
   **Recommendation:** Document the v1 snapshot (as of this commit). A git-annotated
   tag for each release (e.g., `v1.0.0-security-audit`) should include the coverage
   table as a reference. Future audits (E14+) will produce updated tables.

## External writes the implementation will require

| Type | Target | Why | Gated by |
|---|---|---|---|
| Document write + commit | `.claude/docs/security-threat-model-coverage.md` | Audit output: 7-row table + gap issue links | Phase 2 (write) + Phase 4 (review + commit) |
| `gh issue create` × N | GitHub arXMCP issues | File gaps found (byte-cap on 5 tools, BGE-M3 .bin-only, etc.). | Phase 4 user authorization (per project conventions) |
| pytest test creation (optional) | `tests/security/test_coverage.py` | Validation gate for doc staleness + issue URL validity. Non-blocking if omitted; recommended for CI robustness. | Phase 2 (optional; add if time permits) |

**Notes on external writes:**

- **No push until Phase 4 user says yes.** The implementer compiles gaps, user reviews,
  user authorizes filing. Then all issues are filed + linked + committed in a single
  batch.
- **File issues before final commit.** If issues are filed in Phase 4, they must be
  linked in the coverage doc _before_ the final `git commit`. Use issue-create output
  (issue number) to populate links.
- **Markdown link format:** `[#123 - byte-cap on get_paper](https://github.com/arXMCP/issues/123)`
  (not `gh issue view` output; use the web URL).
