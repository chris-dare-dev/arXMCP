---
project: source-truth
type: handoff
status: complete
authorship: agent-generated
handoff_kind: continuation
date: 2026-07-13
companion: HANDOFF-2026-07-13-source-truth-session-review.md
roadmap: plans/source-truth/roadmap.yaml
resume_target: any
tags:
- project/source-truth
- type/handoff
- authorship/agent-generated
- handoff/continuation
- project/arxmcp
aliases:
- source-truth — continuation handoff (2026-07-13)
---

# CONTINUATION HANDOFF — source-truth (2026-07-13)

> **Audience:** a fresh session picking up source-truth. The companion review handoff
> ([[HANDOFF-2026-07-13-source-truth-session-review]]) covers *what shipped and why* — THIS doc says
> **exactly where to resume and what's left**. Roadmap: `plans/source-truth/roadmap.yaml`.
>
> **Program goal:** ship the source-truth layer — document/revision registry, span + truncation +
> printed-number persistence, per-revision license provenance, and a content-addressed corpus manifest
> — so downstream (R2 identity, R5 provenance) can pin to sources that are reproducible + fail-closed.

## 1. Current state (as of this handoff)

`main == origin/main == 32f4d69` for source-truth's work (a concurrent session's `8045da6`
memory-consolidation commit sits unpushed on top — **not** this program's; leave it).

| Milestone | Status |
|---|---|
| source-truth-spike-1 (license-URI coverage) | ✅ DONE (prior session) |
| source-truth-spike-2 (printed-number coverage) | ✅ DONE (concurrent session) |
| source-truth-spike-3 (span-anchor stability) | ✅ DONE — anchor UNSTABLE → checksum+text-hash string |
| source-truth-spike-4 (schema-v2 migration dry-run) | ✅ DONE — clean in-place for string columns |
| **source-truth-m1** — revision registry + OAI-PMH license (advisory) | ✅ SHIPPED + LIVE (registry populated on both notebooks) |
| **source-truth-m2** — chunks schema v2 (spans/truncation/printed-numbers) | ✅ SHIPPED + LIVE (19,581 rows hydrated) |
| **source-truth-m3** — `arxmcp://corpus-manifest` resource | ✅ SHIPPED (read-only resource) |
| **source-truth-m5** — get_chunk surfaces the 5 fields | ✅ SHIPPED |
| **source-truth-m4** — fail-closed license cutover | ⬜ ← RESUME HERE (owner-gated) |

Load-bearing live facts:
- The **live corpus is hydrated**: m1's per-notebook `documents.db` registry + m2's 5 chunk columns
  are populated on `bridgeland-stability` (15,106 rows) + `fourier-duality` (4,475 rows).
- **The running MCP server serves OLD code.** m5 (`get_chunk` fields) + m3 (`arxmcp://corpus-manifest`)
  appear on the wire only after a `make up` restart. Both are fully test-verified; live serving needs
  the restart. This is a "restart to see it live" note, not a defect.
- Serving behavior is **unchanged**: license is advisory (m1/m5); the blanket `arxiv-license` token
  still drives today's truncation. m4 is the flip.
- **Un-hydrated notebooks:** `bridgeland-stability-pdfs` (780 rows) + `fourier-duality-pdfs` (2,051)
  are still on the pre-m2 21-col schema with no `documents.db`. m5 surfaces their 5 fields as
  explicit `null`; m3 marks them `registry_present:false`. Full hydration is a fast-follow (§5).

## 2. RESUME HERE — source-truth-m4 (owner-gated fail-closed license cutover)

**Goal:** flip serving so unknown/unrecognized-license content fails closed, and retire the blanket
`arxiv-license` token. `plans/source-truth/roadmap.yaml` id `source-truth-m4` (lane: later, `depends_on:
[source-truth-m2, source-truth-m3]` — both DONE, so the gate passes).

**Facts already decided / available:**
- m4 flips `server/license_policy.py` (`OA_ALLOWLIST` / `is_open_access`, `:44-53`) so missing/unknown
  license truncates to the existing 300-char path on a fresh install (textbook chunks included), and
  backfills out the blanket `arxiv-license` token.
- The inputs it consumes already exist: m1's per-revision `license_status` (`documents.db`), m5's
  advisory `chunk.license_ref`, and **m3's per-notebook operator override flag**
  (`license_unknown_override_<slug>` in `operator_settings` — m3 RECORDS it; m4 GATES on it).
- spike-1's >20%-unknown escalation is REAL and must surface before the flip: **bridgeland-stability
  9.9% unknown, fourier-duality 19.2%** (both live-measured; fourier is close to the 20% line).
- m4's roadmap text also expects wiring `tools/documents_coverage_report.py`'s escalation gate to
  consult the override flag (m3 deferred that to m4 — see the review handoff §cross-cutting).

**⚠ THIS IS THE ONE MILESTONE TO STOP AT A GO/NO-GO.** m4 CHANGES WHAT THE SERVER SERVES. Its roadmap
entry is owner-sign-off-gated. Run Research → present the owner an explicit checkpoint (which
license_status values truncate; the override-flag semantics; the fourier-19.2% call) → do NOT flip
serving autonomously. The other 5 milestones this session ran fully autonomously; m4 is deliberately
different.

## 3. Definition of done for m4

Critique pass clean (C/H closed); serving flip is owner-approved + reversible; `make test` green
(esp. `tests/test_server_tool_schema.py` if the tool surface moves, and the license-policy tests);
the escalation/override wiring tested; roadmap progress journal appended
(`plans/source-truth/progress/agent.jsonl`); memory updated ([[arxmcp-source-truth-license-reality]]).

## 4. Remaining epics / milestones

- **source-truth-m4** (the only remaining R1 milestone) — see §2. Owner-gated serving flip.
- R1 (source-truth) is otherwise COMPLETE. The broader program continues in **R2–R7** (claim graph,
  Lean verification contract, verified computation, formal-target registry, proof bundles, adapters)
  — briefs at `.claude/roadmap-briefs/R2..R7-*.md`, **none yet run through `/roadmap`** (no
  `plans/<slug>/` for them). R3 (sound Lean verification contract) is the trust foundation for R4/R5
  and touches the one component with a confirmed live soundness gap (`lean_verify`).

## 5. Cross-cutting follow-ups (landmines you'll trip on)

1. **The 2 `-pdfs` (MinerU) notebooks are un-hydrated** and will stay `registry_present:false` /
   null source-truth fields until m1's registry + m2's backfill are run on them. They are MinerU/PDF,
   not LaTeXML — no `ltx_theorem` markup, so printed-number extraction won't apply; and they'd need
   their own m1 OAI-PMH registration. A genuine fast-follow, out of R1's shipped scope.
2. **New-paper ingest does NOT consult the registry** (m2 brief-2 Risk 5): a paper ingested after m2
   gets `truncated`/`printed_number` (chunker-native) but NULL `source_span`/`source_revision_id`/
   `license_ref` until a re-backfill. Tracked m2-gap.
3. **Concurrent sessions land commits on `main` throughout** — this repo runs multiple sessions on the
   same working tree. Always `git fetch` + re-verify ancestry before any push; commit with EXPLICIT
   pathspecs (`git commit -F - -- <paths>`), never `git add -A`. This session interleaved with
   concurrent kuzu-close, Windows-test, ingest-robustness, auto-id (`880fcfd`), and memory-consolidation
   (`8045da6`, currently unpushed) commits — none of them this program's to re-litigate.
4. **GPG passphrase cache expires on long sessions.** After the ~30-min m1 backfill + spikes, signing
   failed ("gpg failed to sign" — a Qt pinentry timed out); the user re-unlocked. On a long session,
   bump `~/.gnupg/gpg-agent.conf` `default-cache-ttl`/`max-cache-ttl` or expect one re-unlock.
5. **The working tree is habitually dirty** (Obsidian frontmatter stamper on `docs/*` + `plans/*.md`,
   agent-memory/scratch dirs). Don't reflexively clean it; diff-inspect anything you didn't write.

## 6. Environment / resume notes (how to reconnect)

- **Windows box.** Use `.venv/Scripts/python.exe` for python/pytest — NOT the macOS
  `/Users/chris.dare/.../uv run` in CLAUDE.md §4.5 (that's the canonical macOS doc; this is Windows).
- **Working dir:** the milestone-pipeline scripts run from the repo root `C:/Users/cedar/Documents/
  Personal Projects/Source Code/arXMCP` (the SESSION cwd is its parent, which is not a git repo — cd in).
- **Pipeline state:** `.claude/notes/milestones/<id>/state.json`; the shared lock is
  `.claude/notes/milestones/.lock` (a stale lock from a dead pid is cleared via
  `init-state.sh <held-id> --release-lock`, never `rm`). All source-truth milestones are `phase: complete`.
- **Test baseline:** the Windows-platform pytest failures were driven to 0 on 2026-07-12 (concurrent
  session). Gate by failure-set attribution vs a throwaway-worktree baseline, not by expecting a clean run.
- **Polite-pool email** for any arXiv/OAI-PMH fetch is persisted in `operator_settings`
  (`cedare96@gmail.com`), resolved by `resolve_contact_email` — no env var needed.

## 7. Key values you'll need (copy-paste reference)

    slug:                source-truth
    roadmap:             plans/source-truth/roadmap.yaml
    session commit head: 32f4d69   (origin/main; 8045da6 = concurrent, unpushed, not ours)
    m1 code:             server/documents_store.py, tools/oai_license.py, tools/notebook_documents_backfill.py
    m2 code:             ingest/schema.py, ingest/store.py, ingest/chunker.py, tools/notebook_chunks_backfill.py
    m5 code:             server/handlers/chunk.py, server/tools.py (TOOL_SCHEMA_VERSION=18)
    m3 code:             server/corpus_manifest.py, server/mcp_resources.py (arxmcp://corpus-manifest)
    m4 target:           server/license_policy.py:44-53 (OA_ALLOWLIST / is_open_access)
    override flag key:   license_unknown_override_<slug>  (server/operator_settings.py, notebooks.db)
    live unknown rates:  bridgeland-stability 9.9% ; fourier-duality 19.2%  (spike-1 escalation input)
    python/pytest:       .venv/Scripts/python.exe -m pytest
    schema-hash pin:     EXPECTED_TOOL_SCHEMA_SHA256 = 5189d7a6…  (tests/test_server_tool_schema.py)

*Full review of what shipped: [[HANDOFF-2026-07-13-source-truth-session-review]].*
