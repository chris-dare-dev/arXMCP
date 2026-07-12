# Research synthesis — data-plane-governance-m1 (orchestrator fan-in, 2026-07-11)

Sources: research/brief-1.md (explore), research/brief-2.md (general). Both verified the
same critical correction independently.

## Affected files (deduped)

| File | Action | Notes |
|---|---|---|
| `.claude/docs/adr-data-plane-boundary.md` | CREATE | Repo's first ADR; Nygard/MADR-lite skeleton per brief-2; no YAML frontmatter (no `.claude/docs/` file has one) |
| `CLAUDE.md` | MODIFY (additive only) | New `### 4.8` anchor recommended (renumber-free); file is PRE-DIRTY with an uncommitted paper-metadata-m2 hunk in §7 → hunk-scoped staging mandatory (disjoint regions: amendment in §4, stray hunk in §7) |
| `.claude/notes/milestones/data-plane-governance-m1/*` | bookkeeping | pipeline artifacts |

NOT touched: README.md, `plans/agent-platform/roadmap.yaml` (m2's task), anything under
`server/` (roadmap wont), the six untracked plan dirs, `AGENTS.md`.

## Load-bearing corrections (both briefs, independently verified)

1. **model_selector is NOT tests-only.** `server/observability/spend_constants.py:51`
   imports `MODEL_HAIKU_4_5`; `observability/__init__.py:30` + `server/main.py` make that a
   transitive RUNTIME import at server startup. `tests/test_model_selector.py` pins the
   module path; relocation would break server code — out of scope for a documents-only
   milestone. → Disposition must be keep-in-place-as-library, recording the true consumer set.
2. **"Under tools/" is not process isolation.** `server/routes/notebooks.py:64-74` imports
   `tools.*` at runtime; the wheel packages `tools*`. Option B must be phrased as
   dependency-direction + state rules, not a directory rule.
3. **No "Hard constraints" section exists in CLAUDE.md** (README.md:135 and
   .claude/notes/README.md:20 hold different lists with that name). Anchor options: new
   §4.8 (recommended; zero renumbering) vs new top-level section.
4. **Server-side agent dispatch/memory: verified absent** — zero anthropic imports under
   `server/` (guard test `tests/test_langfuse_doc.py` ~:179-207 enforces); rule wording must
   scope to "the served process and the `server/` package" (not `.claude/` dev tooling) and
   carve out server-internal operational writes (cache sqlite, logs, metrics, ingest-status)
   + classify `/ui/api/.../ingest` (runs in-process) as operator-gated console action.
5. **Stale facts not to copy into binding text:** "7-tool surface" (§6 — actually 8),
   "make ingest is a stub" (§7 — Makefile:188 is the real orchestrator).

## Acceptance criteria (deduped; traced to roadmap AC 1–3)

1. ADR exists at the fixed path, states the three boundary rules normatively, records owner
   approval, committed. [AC1]
2. ADR records ONE loop-placement choice (loser explicitly rejected), the model_selector
   disposition naming `spend_constants.py:51`, and the candidate-layer principle (general
   form only; R7 owns specifics). [AC2]
3. CLAUDE.md states the three rules as binding constraints at the chosen anchor, links the
   ADR; ADR records the anchor. Amendment lands only AFTER approval is recorded. [AC3]
4. Zero `server/` changes; `tests/test_constitution_ui_claims.py` passes (no reintroduction
   of "mcp tool surface is the ui"; keep "/ui/", "operator console", "Browser UI surface");
   no section renumbering; gate results attributed against the pre-m1 dirty-tree baseline
   (29 known Windows failures; in-flight paper-metadata changes are not m1's).
5. Commit hygiene: m1 commits contain ONLY m1 hunks (hunk-scoped staging for CLAUDE.md);
   conventions per repo (GPG, heredoc, trailer naming the actual model — cfb7c27 precedent).

## external_writes_required (verbatim from brief-2 frontmatter)

- "git push origin main"

(One item; CLAUDE.md 4.1 names commit+push as the landing pattern, 4.4 makes each push
per-event authorized; declinable at the 4d boundary with skip recorded in both ledgers.)

## Open questions (owner checkpoint — consolidated)

1. Orchestrator-loop placement: A (separate repo; both briefs + R0 recommend) vs B
   (tools/ carve-out with dependency-direction rules)?
2. CLAUDE.md anchor: §4.8 (recommended) vs new top-level section?
3. Pre-existing paper-metadata-m2 CLAUDE.md/README/docs hunks: commit separately as a
   `docs(repo)` sync first, or leave uncommitted (hunk-scoped staging around them)?
4. ADR approval mode: approve-on-decisions in-session (record Accepted with interactive
   approval note) vs land as Proposed and review the full draft before the CLAUDE.md
   amendment?
5. (Deferrable to m2) Under Option A: loop repo name/path.

## Phase 2 path decision inputs

Estimated diff: ADR ~180–260 lines (new file) + CLAUDE.md ~25–40 added lines = ≤ ~300 LOC,
2 tracked files, no novel architecture → **INLINE**. (Consequence per pipeline §Phase 4:
rectify should be DELEGATED — trigger 3.)
