---
milestone_id: "verification-contract-m1"
phase: "implement"
implementer_status: "complete"
commit_sha: "6c681b9bf88469dcb147844fa40ee6ccf5624839"
branch: "worktree-agent-a71336b2f18ab67b8"
external_writes_required:
  - "git push origin main"
---

# Implement synthesis — verification-contract-m1

## Built

- **AC1** — `status="ok"` renamed to `status="elaborated_no_errors"` at all 6 live code
  sites in `server/handlers/lean_verify.py`: the cmd-branch assignment
  (`_normalize_response`, ~line 731) and its two downstream comparisons deriving
  `compilation_success` (~lines 740/743), the `_default_audit_for` gate (~line 787), the
  tactic_step-branch assignment (`_normalize_tactic_step`, ~line 833), and the axiom-audit
  round-trip gate in `handle_lean_verify` (~line 1457). No response field reads bare
  `"verified"` anywhere (grep-verified regression guard, unchanged).
- **AC2** — confirmed the four trust fields (`status`, `compilation_success`,
  `axiom_audit`, `continuation_status`) stay independently derived; none is inferred from
  another. Recorded the "why `status` is a rename, not a Certificate-wrap" reasoning
  visibly in two places per the research synthesis's explicit instruction: a new code
  comment at the status-computation block (`server/handlers/lean_verify.py:717-726`) and a
  dedicated paragraph in the ADR's Context section.
- **AC3** — both frozen-schema hashes re-pinned in the documented order (handler + `tools.py`
  + both `server/schemas/*.json` edited first, then the hash/BP1 pins computed against the
  final bytes): `TOOL_SCHEMA_VERSION` 22 -> 23 with an extended bump-history comment
  (`server/tools.py:226`); `LEAN_VERIFY.description`'s two `"ok"` mentions renamed
  (`server/tools.py:437,446`); `EXPECTED_TOOL_SCHEMA_SHA256` +
  `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` regenerated via
  `pytest tests/test_server_tool_schema.py --update-tool-schema-hash` (got the expected
  "commit and rerun" failure, then confirmed green on re-run); `EXPECTED_BP1_SHA256`
  hand-edited in `tests/test_prompts.py` from the value printed by the failing assertion,
  with a new `# v23:` history comment. Both `server/schemas/lean_verify_result.json` and
  `server/schemas/search_papers_result.json` bumped `version`/`$id` 22->23 in lockstep
  (search_papers_result.json content otherwise untouched, matching its own ~8x-precedented
  bump-though-unchanged pattern); `tests/test_search_filter.py`'s `$id`-suffix assertion
  for search_papers_result.json passes. `tests/test_handlers_lean_verify.py:224`'s hardcoded
  `TOOL_SCHEMA_VERSION == 22` updated to `== 23` with an extended docstring history list.
  All ~21 literal `"ok"`/`!= "ok"` assertion sites in `tests/test_handlers_lean_verify.py`
  renamed programmatically (verified via diff review — 19 `==` sites + 2 `!=` sites); the
  two `!=` sites had their comparison TARGET flipped, not their polarity. Two adjacent prose
  comments describing the current (not historical) assertion behavior were updated for
  consistency; three genuinely historical-narrative comments (describing pre-m5 or pre-rename
  behavior, or directly quoting CLAUDE.md's still-unmodified founding-case prose) were left
  as-is per the research brief's own "optional, safe to leave" guidance.
- **AC4** — new ADR at `.claude/docs/adr-verification-contract-five-operations.md` (~200
  lines), following the `adr-data-plane-boundary.md` house format. Defines, for each of
  `parse_source` / `elaborate_signature` / `check_declaration` / `audit_axioms` /
  `strict_replay_proof`: inputs, isolation dependency (explicit `verification-contract-e2`
  citation for all five), and target-binding behavior. Implements none of them (no code
  changes accompany the file). Resolves both open questions the research synthesis left to
  the implementer: (a) checker identity is assigned to the `arxmcp://lean-env` manifest
  resource (m5), not a sixth operation; (b) `strict_replay_proof`'s mechanism CLASS (full
  `Environment.replay`, never trust-the-loaded-environment) is committed now, while the
  concrete TOOL (SafeVerify vs a bespoke fallback) is explicitly deferred to
  `verification-contract-spike-2`. Names `check_declaration`/`strict_replay_proof` as two
  different, deliberately non-overlapping soundness guarantees (AXLE-shape vs
  SafeVerify-shape) rather than the same check at two speeds — the research brief's single
  highest-priority finding. Records the `Lean.trustCompiler`-naming and
  SafeVerify-branch-gap documentation-staleness hazards without any code change. Ships
  `Status: Proposed` with an explicit "Pending" Owner approval record, per the research
  synthesis's Decision 2 (no interactive owner round-trip has run for this document).
- **Drive-by fix (not an AC, flagged as a nice-to-have by both research briefs):** the
  handler's module docstring (`server/handlers/lean_verify.py:9`) claimed schema "version
  12"; corrected to "version 23" while the file was already open for the rename.
- **`docs/api.md:131`** — the one stale `` `ok` `` token renamed to `` `elaborated_no_errors` ``
  (minimal fix only, per the research synthesis's Decision 3 — the rest of that line's
  drift, e.g. missing `incomplete`/`invalid-input`/`axiom_audit`, is independently
  pre-existing and out of this milestone's scope).

## Branching note

Per CLAUDE.md §4.1 this repo is main-only, but `main` is checked out in the primary
worktree, so `git checkout main` inside this worktree would fail with "already checked
out." Per the milestone brief's explicit instruction, the commit landed on the assigned
worktree branch `worktree-agent-a71336b2f18ab67b8` at commit `6c681b9bf88469dcb147844fa40ee6ccf5624839`
(GPG-signed, verified good signature). The orchestrator integrates to `main` from the main
session.

## Files touched

- `server/handlers/lean_verify.py` — the 6 live-code rename sites, the new status-block
  comment recording the Certificate-wrapping decision, the docstring version fix, and two
  prose-comment touch-ups (all-code-behavior descriptions, not historical narrative).
- `server/tools.py` — `TOOL_SCHEMA_VERSION` 22->23 + extended bump-history comment;
  `LEAN_VERIFY.description`'s two `"ok"` mentions renamed.
- `server/schemas/lean_verify_result.json` — enum, 2 field descriptions, top-level
  description append, `version`/`$id` 22->23.
- `server/schemas/search_papers_result.json` — `version`/`$id` 22->23 + 1 narrative
  sentence; content otherwise unchanged.
- `tests/test_server_tool_schema.py` — `EXPECTED_TOOL_SCHEMA_SHA256` +
  `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` regenerated via the update-hash flag (mechanical).
- `tests/test_prompts.py` — `EXPECTED_BP1_SHA256` hand-edited + history comment.
- `tests/test_handlers_lean_verify.py` — hardcoded version-integer edit, ~21
  literal-string renames, docstring history addition, 2 prose-comment consistency edits.
- `docs/api.md` — 1-line token rename.
- `.claude/docs/adr-verification-contract-five-operations.md` — new file, the
  five-operation design ADR (no code).

## Deferred

- All five operations' actual implementation (`parse_source`, `elaborate_signature`,
  `check_declaration`, `audit_axioms`, `strict_replay_proof`) — explicitly out of scope
  per AC4 ("without implementing any operation"); lands in `verification-contract-e3`.
- The Windows isolation boundary (`verification-contract-e2`), the SafeVerify-vs-fallback
  toolchain confirmation (`verification-contract-spike-2`), and named environments
  (`verification-contract-e5`) — all future epics/spikes this ADR explicitly does not
  decide.
- The historical-narrative `"ok"` mentions in `server/handlers/lean_verify.py` comments
  (lines ~363-365, quoting CLAUDE.md's still-unmodified founding-case prose, and one
  pre-m5-behavior comment) — left untouched per the research brief's own "optional, safe to
  leave" guidance; changing them would misquote CLAUDE.md §4.9, which was not itself in this
  milestone's scope to edit.
- `CLAUDE.md:413`'s own `status:"ok"` founding-case prose — flagged as optional by
  brief-1 (item 9), not required by any AC; left untouched to keep this milestone's diff
  scoped to its own 10-item checklist.
- Two independently-stale, out-of-scope docs citing the old `290-298` line range
  (`adr-data-plane-boundary.md:30`, `R3-verification-contract.md:10-11,17`) — per the
  repo's established append-don't-edit convention on Accepted docs, and per the research
  synthesis's explicit do-not-touch list.

## external_writes_required

- `["git push origin main"]` — carried verbatim from research; nothing new introduced.

## Test deltas

- `tests/test_server_tool_schema.py` — 2 constants regenerated (mechanical).
- `tests/test_prompts.py` — 1 hash constant hand-edited + history comment.
- `tests/test_handlers_lean_verify.py` — 1 hardcoded version integer + ~21 literal-string
  assertions + docstring/comment updates. No new test cases added or removed; this
  milestone is a rename, not new coverage.

## Check gate results

- `ruff check .` — PASS (clean, "All checks passed!").
- `pytest tests/test_handlers_lean_verify.py tests/test_server_tool_schema.py
  tests/test_prompts.py tests/test_search_filter.py tests/test_snippet_contract.py
  tests/test_server_metrics.py tests/test_tools_all.py` — PASS (targeted fast loop, all
  green, expected `requires_lean_repl` skips only).
- `pytest` (full suite) — PASS. Two full runs performed (one to confirm, one to capture the
  final summary cleanly): exit code 0 both times; 4482 passed / 106 skipped / 1 xfailed / 0
  failed / 0 errors (verified by grepping the raw dot-progress output for `F`/`E` markers —
  none found outside my own `EXIT_CODE=0` trailer text, whose two literal `E` characters were
  independently confirmed as a false match). This box's pytest (`-q --tb=short -p
  no:warnings`, redirected to a file) does not print a final `"N passed in Xs"` summary line
  under this Bash-tool/Git-Bash pipe — a pre-existing environment quirk unrelated to this
  milestone's diff, worked around by counting dot/skip/xfail/failure markers directly rather
  than parsing a summary line. Test counts are higher than the CLAUDE.md-documented
  2026-08-01 snapshot (4447/103/1) because this box has concurrent agent sessions landing
  commits on `main` continuously (CLAUDE.md's own documented concurrency note).
- `git status`: clean after the commit.
