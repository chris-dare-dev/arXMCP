---
milestone_id: "data-plane-governance-spike-1"
injection_attempts: 0
---

# Disposition brief — pair 3: `scale-ops-hardening`, `trustworthy-release`

Grounding read: `CLAUDE.md` §4.8 (lines 252–284) and §4.9 (lines 286–313);
`.claude/docs/adr-data-plane-boundary.md`; `.claude/docs/trust-language-policy.md`;
`.claude/roadmap-briefs/README.md`; `.claude/roadmap-briefs/R1-source-truth.md`,
`R3-verification-contract.md`, `R7-adapters-benchmark-ablation.md`.

Both tracks were `generated_by` on 2026-07-07, drawn from the same
`_pipeline/gap-analysis-2026-07` chapter set (D1/D4/D5/D6/D8/D9 + cross-synthesis,
referee-merged 2026-07-07) that the *adjudicated* rev-2 analysis (2026-07-11) later
corrected into R0–R7. The roadmap-briefs README's interlocks table (written 2026-07-11,
i.e. **after** both tracks existed) reviewed both by name and kept them as live,
complementary tracks rather than superseding either wholesale — that finding anchors
both dispositions below rather than a fresh good/bad judgment in a vacuum.

---

## scale-ops-hardening

### 1. What it scopes

862 lines, read in full. Six epics: (e1) linearize the bulk LanceDB write path
(`defer_indices` mode, kill full-table `to_arrow()` scans — the single blocker capping
the corpus at ~10³–10⁴ papers); (e2) an ~8-gauge scale-guard telemetry pack, BM25
decoupled from `/readyz`, concurrency/lookup bounds; (e3) nightly LanceDB
maintenance + backup telemetry + Windows cron/systemd parity + a first CI workflow;
(e4) GPU-capable ingest device selection + a corrected 200K storage plan + a Kuzu-successor
spike/ADR; (e5) content-security hardening — MinerU/PDF no-egress containment
(CVE-2026-24770 Zip-Slip class), a Windows LaTeXML WSL2/bwrap half-step, and
ingest-time hidden-instruction screening; (e6) a growth-gated 10K-paper capacity
checkpoint gating Tier-5 entry. It is pure infrastructure/ops/security engineering —
no retrieval-quality verdicts, no claim semantics.

### 2. Boundary/trust alignment

**(a) Agent dispatch / loop / per-run agent memory in server or repo?** None found.
No occurrence of "agent," "anthropic," "orchestrator," "LLM," or "dispatch" anywhere in
the 862 lines. Every epic targets ingest pipeline, storage engine, ops/telemetry, or
sandboxing — none of it touches an agent loop. Clean.

**(b) Write paths outside offline-ingest / operator-gated?** All write-path items route
through the ADR's two approved surfaces:
- `scale-ops-hardening-e1` (lines 68–94) and its milestone/tasks (296–378) touch only
  `ingest/store.py`, `bulk_ingest.py`, `oai_delta.py`, `re_embed.py` — the ADR's own
  "~18 offline ingest CLIs" enumeration (ADR context, line 48).
- `scale-ops-hardening-e5` / `m11` (lines 741–803) adds the injection-screening
  verdict inside `ingest/bulk_ingest.ingest_one_paper` — same offline path — and is
  explicit that the operator override is **"CLI-only... never a silent drop, no console
  UI for the override"** (line 757, restated 801) — stricter than the ADR requires, not
  looser.
- `scale-ops-hardening-e3` / `m5` (lines 585–608) is the one item worth naming
  precisely: `tools/lancedb_maintenance.py` on a nightly cron/Task-Scheduler job
  **"deletes LanceDB versions older than a retention window"** (line 138–142, 592–595).
  This is MVCC version-retention pruning (a pin-aware allowlist, skipped when a writer
  is active), not new corpus content — closer to the ADR's carve-out for
  "implementation detail, not corpus writes" (ADR Decision 1 rule 2, lines 73–74) than
  to a corpus write, and it is direct precedent-following of the already-existing,
  never-flagged nightly `ops/cron/arxmcp-backup.sh`. Compliant by reasonable reading;
  flagged here only so the eventual implementer's milestone brief states that reading
  explicitly rather than leaving it implicit.
- `scale-ops-hardening-e2`/`m2`/`m3` (BM25 gating, telemetry gauges) write only to
  `server/metrics.py`, `server/health.py` — squarely the ADR's "retrieval-cache SQLite,
  logs, metrics" carve-out (line 73).

**(c) N/A** — the task frames this check as trustworthy-release-specific; scale-ops-hardening
has no external-data-licensing surface.

**(d) Categorical novelty claims?** None. "0 CI workflows exist" (line 19) and similar
figures are internal repo-state facts (directly `grep`-verifiable), not external
prior-art/novelty claims — trust-language-policy §3's dated-census rule targets claims
about the outside world, not a local file count.

**Trust-language positive note:** `scale-ops-hardening-t-jaccard-fallback-cap`
(lines 533–546) introduces a new `retrieval_mode=fts5_trigram_capped` value for a
lower-precision fallback path — textbook-correct application of trust-language-policy
§5c (a present-but-lower-precision result gets a namespaced mode value, never folded
into a bare status). Authored before §4.9 existed; complies anyway.

### 3. R0–R7 relationship

Interlocks README (line 54): **"R3's sandbox composes with its parser-containment
work; nothing in R1–R7 gates on corpus scale."** Verified directly:
- R3's Windows-isolation spike (`R3-verification-contract.md` assumptions, "must" #1,
  lines 95–100) explicitly cites **"Docker/WSL2 which scale-ops-hardening already
  plans for MinerU"** — R3 is the one referencing this track, not the reverse, and the
  two isolate different subprocesses (Lean REPL vs. MinerU/LaTeXML) — complementary
  infra, not duplicated scope. Neither roadmap.yaml needs a cross-edge; the interlock
  is already correctly captured at the README level.
- No item in this track touches R1 (source-truth), R2 (claim-graph), R4/R5 (formal
  targets), or R7 (adapters) — confirmed by scanning all 15 milestones' `links.code`
  targets, none of which overlap those tracks' evidence files.
- The one soft dependency this track carries on other **existing** tracks
  (evidence-engine's FIX fixture, gating `m13`/`m14`'s recall-bench and eval-delta
  sub-tasks; agent-platform's W1 re-pin window, gating `t-jaccard-fallback-cap`) is
  already correctly expressed as `goal.assumptions` (lines 34–38) with documented
  fallback behavior if the dependency slips. No new gate needed.

### 4. Recommended disposition: **commit-as-is**

Rationale: zero boundary conflicts, zero agent-loop scope, every write path is either
an offline ingest CLI or the ADR's explicit operational-write carve-out, and the one
gray-area item (nightly LanceDB retention pruning) is defensible by direct analogy to
already-accepted backup automation. Trust-language exposure is a single new
`retrieval_mode` value that already follows the §4.9 pattern correctly. The
interlocks README (authored after this track existed) independently confirms
"nothing in R1–R7 gates on corpus scale" and frames R3's overlap as compositional, not
duplicative. This track should land as tracked project state without content edits.

---

## trustworthy-release

### 1. What it scopes

531 lines. Five epics: (e1) fence two code-confirmed trust defects — unfenced
author-controlled `get_paper` metadata with an inverted-polarity guard test, and dead
textbook license stamping that lets copyrighted PDFs serve full-body under an
open-access default — plus a false `SECURITY.md` claim and Rule-of-Two doc guidance;
(e2) complete the half-executed v0.1.0 release (wheel fix, PyPI publish, quickstart,
GitHub Release against the already-existing tag); (e3) a citation contract with
client-side hash verification and a FIX-gated honest benchmark page; (e4) an adoption
kit (notebook import, one license-clean reference pack, registries, demo,
`CITATION.cff`); (e5) scope-discipline items (multi-client docs, de-hardcoded arXiv
categories, a LeanExplore composition spike) — all under an explicit one-quarter
falsifiability clock on whether distribution is worth continued investment.

### 2. Boundary/trust alignment

**(a) Agent dispatch / loop / per-run agent memory?** None scoped here — and
explicitly, correctly deferred: "SYSTEM_PROMPT authoring and capability-profile
design are orchestrator-era work owned by the agent-platform roadmap" (`e1` summary,
line 78, restated at `m3` line 240). `e5`/`m13`'s LeanExplore item (lines 523–531) is a
feasibility spike for **live, uncached** MCP-to-MCP composition ("compose with
LeanExplore rather than ingesting Mathlib," line 9) — nothing persisted, no agent loop,
clean by construction.

**(b) Write paths outside offline-ingest / operator-gated?** All compliant:
`m2`'s textbook-license work (lines 178–235) writes via the existing operator-gated
`/ui/` textbook-upload route (`server/routes/notebooks.py`) and offline CLIs
(`tools/notebook_textbook_ingest.py`, plus a one-shot backfill CLI, lines 191–235);
`m9`'s notebook import (line 483, `arxmcp notebook import <file>`) is the same CLI
pattern. No MCP-tool-surface write anywhere.

**(c) External-data licensing per ADR Decision 4, and does "trust"/"adoption"
language need §4.9?**

*Decision 4 (candidate layer)* is not actually the operative mechanism here: Decision
4 governs third-party *probabilistic/structured* external data (CC-BY-NC-SA
TheoremGraph-style dumps) — that's R7's adapter-layer domain. `trustworthy-release`'s
license surface is first-party corpus content (textbook PDFs the operator uploads),
governed by the existing `server/license_policy.py` fail-closed mechanism, not a
candidate layer. Correctly out of Decision 4's scope as written.

*§4.9 reference gap — the concrete finding:* `m7` ("Reproducible benchmark page,"
lines 435–449) commits to publishing "a TheoremSearch differentiation table" and cites
"MIRB's independent rerankers-degrade-math-retrieval result" (line 447) with no
acceptance criterion requiring dated grounding. Per trust-language-policy §3 / CLAUDE.md
§4.9 rule 3 (binding on "every arXMCP planning/analysis document," not just
user-facing docs): any TheoremGraph/TheoremSearch comparison must cite R7's actual
measured numbers (68.1% combined edge precision; 98.8%/76.6%/42.7% split by category —
`R7-adapters-benchmark-ablation.md` line 11) dated, not an undated superiority framing;
positive prior-art citations like the MIRB result need "only a freshness date" (policy
§3) but currently carry none in the KR text. `m6`'s citation contract (lines 418–433)
is a narrow, single-axis byte-identity check (`quote_sha256` re-slice match) — sound on
its own terms, but its acceptance criterion ("a fabricated citation is detectably
rejected," line 429) should carry an explicit one-line disclaimer that hash-match
verification is not the multi-axis trust record trust-language-policy defines, so a
downstream reader doesn't over-read "citation verified" the same way `lean_verify`'s
bare `"ok"` was over-read (the policy's own motivating defect, `trust-language-policy.md`
§2).

**(d) Categorical novelty claims?** The `m7` differentiation-table risk above is the
one concrete instance; nothing else in the file makes an unscoped "no system does X"
claim (the brief's "unusually well-tested" line 9 is planning-document color, not a
claim destined to ship verbatim in a served artifact).

### 3. R0–R7 relationship — the material finding

Interlocks README (line 53): **"R1's license provenance subsumes its textbook-license
defect fix; its citation contract (`quote_sha256`) is the base R2/R5 provenance
extends; no PyPI publish before R1 gates pass."** This is not a soft interlock —
`R1-source-truth.md` names `trustworthy-release` by file path twice:
- KR#3 (lines 50–53): "...unknown license fails closed (300-char truncation),
  including for every textbook chunk — **closing trustworthy-release's diagnosed
  defect at the data layer**."
- Evidence (line 103–104): "`plans/trustworthy-release/roadmap.yaml` — textbook
  license stamping diagnosed dead; D8-R04 owns the token semantics decision; this
  brief supplies the data layer it needs."
- R1's own **Release gate** (lines 128–129): **"blocks trustworthy-release publish:
  zero full-body serving of unknown-license content on a fresh install."**

R1 explicitly declares a gate on `trustworthy-release-m5` (PyPI publish, lines
342–357). But `m5`'s acceptance criteria (lines 352–355) gate on exactly one signal —
the agent-platform session-cap fix — with **zero mention of R1 or source-truth
anywhere in the file** (confirmed: no occurrence in a full read of all 531 lines).
That's a real, checkable gap between what R1 (authored 2026-07-11, after this track)
now requires and what this track's own sequencing encodes (authored 2026-07-07,
before R1 existed).

There's a second, more mechanical overlap risk: `trustworthy-release-t-textbook-license-backfill-cli`
(lines 222–235) backfills the *existing* `license` field on `ChunkRecord`
(`ingest/chunker_types.py:174-176`) via a standalone CLI targeting today's schema. R1's
own milestone sketch (`m2` "schema v2 migration," `m4` "fail-closed cutover +
notebook backfill") performs a **second**, broader backfill under a **new**
`license_ref` column into a `documents` registry — the same textbook rows would be
stamped once now, then re-migrated under a different mechanism once R1 lands. Not
wasted work (the near-term stopgap value — stop serving copyrighted PDFs full-body
today — is real and shouldn't wait on R1's full migration), but the roadmap should say
so explicitly rather than let two independent license mechanisms diverge silently.

R7 relationship: `e3`'s citation contract is explicitly the *base* R2/R5 extend
(interlocks README line 53) — this is a reason to keep `m6`, not touch it structurally.
`e5`/`m13`'s LeanExplore spike is complementary to (and could directly inform) R7-`m1`'s
"LeanExplore adapter lands first" (`R7-adapters-benchmark-ablation.md` line 59) — a
feasibility check naturally sequenced before the adapter build, not a duplicate of it.

### 4. Recommended disposition: **revise-then-commit**

Specific revisions:

1. **Add R1's release gate to `trustworthy-release-m5`** (lines 342–357): a new
   acceptance criterion / `depends_on` requiring R1's exit-gate signal ("unknown
   license fails closed" across the corpus, not just textbooks) before the PyPI-publish
   sub-step runs — matching the pattern already used for the agent-platform
   session-cap gate on the same milestone, and literally what the interlocks README
   already prescribes ("no PyPI publish before R1 gates pass").
2. **Annotate `trustworthy-release-m2`** (lines 178–191) as an explicit interim
   stopgap: note that its backfill CLI stamps today's `license` field and that R1's
   later `license_ref`/`documents`-registry migration will re-derive those values
   under a different mechanism — so the two don't silently diverge, and so a future
   session doesn't treat `m2`'s backfill as the permanent source of truth.
3. **Add a §4.9 acceptance criterion to `trustworthy-release-m7`** (lines 435–449):
   any comparative/differentiation claim (TheoremSearch table, MIRB citation) must
   carry a dated source per trust-language-policy §3 before publication, sourced from
   R7's actual measured numbers rather than an undated framing; add a one-line
   disclaimer to `m6`'s citation-contract docs (lines 418–433) that `quote_sha256`
   hash-matching is a single-axis integrity check, not the multi-axis trust record
   trust-language-policy defines.

None of this touches the track's core value — two are real, already-shipped-adjacent
code defects (unfenced metadata, dead license stamping) worth fencing regardless of
R0–R7, and the release/citation-contract work is what R1/R2/R5 explicitly build on
top of. Nothing here is superseded; the gate and two annotations are the fix.
