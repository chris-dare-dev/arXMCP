# Implement synthesis — data-plane-governance-m1

## Built

- AC1 (ADR exists, three rules, owner approval recorded, committed):
  `.claude/docs/adr-data-plane-boundary.md` (172 lines, commit 90a1049) — Decision 1
  states the three boundary rules normatively, scoped to "the served process and the
  `server/` package" with the operational-writes carve-out and the `/ui/api/.../ingest`
  classification; Owner approval record section carries the Accepted verdict from the
  interactive pipeline checkpoint (2026-07-12) with all decisions enumerated.
- AC2 (single loop-placement choice; model_selector disposition; candidate-layer
  principle): ADR Decision 2 chooses the separate repository and explicitly rejects the
  tools/ carve-out on the verified grounds (server imports tools.* at runtime,
  notebooks.py:64-74; wheel packages tools*); Decision 3 keeps server/orchestrator/ in
  place as an SDK-free library and records the true consumer set incl.
  spend_constants.py:51 (retiring the stale "tests-only" claim); Decision 4 states the
  candidate-layer principle, mechanism deferred to R7.
- AC3 (CLAUDE.md binding rules at the recorded anchor, post-approval): CLAUDE.md new
  §4.8 "Data-plane boundary — hard constraints (binding)" (32 added lines, additive
  only, zero renumbering), linking the ADR; ADR Decision 5 records the §4.8 anchor.
  Ordering satisfied: approval was granted at the checkpoint BEFORE the amendment was
  drafted/committed; ADR and amendment land in one reviewed diff per the owner's chosen
  approval mode.

## Branching note

Committed directly on `main` per CLAUDE.md 4.1 ("All work lands on main directly").

## Files touched

- `.claude/docs/adr-data-plane-boundary.md` — the ADR (new; repo's first).
- `CLAUDE.md` — §4.8 added via hunk-scoped staging (`staging-m1.patch` applied with
  `git apply --cached`); the pre-existing paper-metadata-m2 §7 hunk remains uncommitted
  and byte-identical in the working tree (owner decision: leave uncommitted).

## Deferred

- `plans/agent-platform/roadmap.yaml` amendment → m2 (`t-agent-platform-amend`).
- Loop repo name/path → m2.
- Trust-language / abstention / evidence-ledger policies → m3 (will land as §4.9 or
  extend §4.8).
- Any enforcement tooling (grep tests, dependency linters) → consuming tracks (R0 wont).

## external_writes_required

- "git push origin main"

## Test deltas

- None (documents-only milestone; no production code changed, so the rect-commit
  test-file rule applies only if rectification changes production code).

## Check gate results

- `ruff check .`: PASS (clean).
- `pytest tests/test_constitution_ui_claims.py` (the ONLY test that parses CLAUDE.md):
  PASS 28/28.
- Full `pytest`: 68 failures, **0 attributable to m1** — attribution record:
  - Mechanistic: m1's diff is 2 markdown files; grep over all 31 failing test files
    finds references to `CLAUDE.md`/`.claude/docs` only in docstrings, comments, and
    assertion-message strings (test_delimiters.py:10,541-569; test_snippet_contract.py:37;
    test_textbook_chunker.py:200,224; test_model_selector.py's POLICY_DOC_PATH pins
    `.claude/docs/model-policy.md`, untouched). No failing test reads m1's files.
  - Empirical: `tests/test_model_selector.py::TestRectificationGuards` (2 failures)
    reproduced at baseline cfb7c27 in a clean worktree BEFORE m1's commit — root cause
    is a Windows path bug in the test itself (`str(rel) == "orchestrator/model_selector.py"`
    at tests/test_model_selector.py:424 compares backslashed WindowsPath to a
    forward-slash literal, so the allow-list never matches on Windows).
  - Class attribution of the remainder: (a) Windows platform class (symlink/POSIX/path
    tests — CLAUDE.md §3 documents 29 pre-existing Windows failures; the live count has
    drifted with new tests since that 2026-05-20 snapshot); (b) in-flight UNCOMMITTED
    paper-metadata-m2 work changing pinned behavior — e.g.
    `test_delimiters::TestV1Gaps::test_get_paper_does_not_yet_wrap` asserts v1
    non-wrapping while the uncommitted m2 code wraps get_paper metadata (the CLAUDE.md
    §7 working-tree hunk documents exactly this), and the two schema-version pin tests
    match the m2 TOOL_SCHEMA_VERSION bump; (c) live-var/-dependent notebook validations
    (a separate ingest session is actively running against the bridgeland notebook).
  - Full log: `gate-lf.log` in this directory. The pytest teardown crash that eats the
    final count line is the known faiss/torch shutdown issue (CLAUDE.md gotcha 1 class).
- `git status` (m1-scoped): clean — both m1 files committed in 90a1049; the remaining
  working-tree dirt is the pre-existing state catalogued in `preflight-deviation.md`,
  deliberately left untouched per the owner's checkpoint decision.

## Owner follow-ups surfaced (not m1's to fix)

1. tests/test_model_selector.py:424 Windows path bug (`str(rel)` vs posix literal) —
   one-line fix (`rel.as_posix()`), fixes 2 of the platform failures.
2. The uncommitted paper-metadata-m2 work (server behavior + doc updates + state.json)
   needs its own session to finish/commit — several suite failures clear when it lands.
3. A husk directory `../arxmcp-m1-baseline` (partially-deleted attribution worktree,
   file-locked by a stale process) needs manual deletion; git's worktree registry
   already pruned it.
