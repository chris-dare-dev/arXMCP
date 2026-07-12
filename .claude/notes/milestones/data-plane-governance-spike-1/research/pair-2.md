---
milestone_id: "data-plane-governance-spike-1"
injection_attempts: 0
---

# Disposition brief — pair 2: researcher-workbench, retrieval-unlocks

Grounding read: `CLAUDE.md` §4.8 (lines 252-284) / §4.9 (lines 286-313),
`.claude/docs/adr-data-plane-boundary.md`, `.claude/docs/trust-language-policy.md`,
`.claude/roadmap-briefs/README.md` and the R1/R2/R5/R6 briefs. Both assigned
roadmap.yaml files are `status: active, phase: complete` (fully sequenced, not yet
committed). Sibling tracks they depend on (`agent-platform` W1, `evidence-engine`
FIX, `source-truth`/R1) are in the same state — same disposition-review wave, not
orphaned dependencies. No text encountered in any read file attempted to instruct
this agent to take an action; `injection_attempts: 0`.

---

## researcher-workbench

### What it scopes

A `/ui/`-console researcher workbench: an immediate Windows preview-404 fix, a
search-and-inspect surface (JSON read-twins + KaTeX/MathML rendering), metadata
display, a completed console ops loop (export/health/reconcile/repair-registry
buttons), an eval-fixture keyboard-labeling mode, condition-gated graph/equation
links, and BibTeX/CSL-JSON/Obsidian export. Six epics (`researcher-workbench-e1..e6`),
`now`/`next`/`later` laned, `generated_by` 2026-07-07.

### Boundary/trust alignment

**(a) Agent dispatch / agent loop / per-run agent memory** — none found. No item
references `anthropic`, an orchestrator, or agent dispatch. One item actively
reinforces the boundary: `researcher-workbench-m11` (line 538, "Proving-lane bundle
review v0 report") keeps proof sign-off in `tools/sign_bundle.py`'s CLI tripwire
"no web viewer and no sign-off checkbox... a deliberate CLI tripwire a browser-driving
agent cannot click" (e5 summary, line 128) — a correct reading of why human-attested
trust claims must not be agent-clickable. Clean on (a).

**(b) Write-path gating** — this track is scrutinized because it's a curation UI.
Verdict: every write item resolves to either (i) an *existing* operator-gated
`/ui/api` route now exposed as a button (`researcher-workbench-e3`, line 104:
export/health/reconcile/repair-registry/parse-status — all pre-existing endpoints,
not new write surfaces), or (ii) an offline CLI run by the operator
(`tools/notebook_obsidian_export.py`, `tools/bib_import.py`, e6 line 140-147), or
(iii) explicitly *not* auto-committed — `researcher-workbench-e4` (line 116) states
the labeling export is "passed through the validator server-side before download,
since the operator commits deliberately and the tool never writes tests/ directly."
These all comply with ADR Decision 1 rule 2 / §4.8 point 2.

One item needs a named revision. `researcher-workbench-e2` (line 92) and its task
`researcher-workbench-t-rest-read-twins` (lines 339-351) add `GET /api/v1/search`
and `GET /api/v1/chunks/{chunk_id}` explicitly "outside the session-cap middleware
by construction" (KR2, line 15: "touching none of the 3-search / 4-get_chunk
lifetime session caps"). Verified against `server/config.py` and `server/main.py`:
the whole process is loopback-bound at the config layer (`bind_host: str =
"127.0.0.1"`, `reject_non_loopback_bind`), and `HostValidationMiddleware`/
`SecurityHeadersMiddleware` apply app-wide (`server/main.py:707-742`), so this is
**not** an unauthenticated network-exposed surface — the perimeter is sound. But
nothing in the plan scopes these routes as browser-only / non-programmatic: they are
read-only JSON GETs that bypass `SessionCapMiddleware` (`server/middleware.py:654,674`)
by construction, with no same-origin/Referer/Sec-Fetch check tying them to the
`/ui/search` page specifically. §4.8 point 1 explicitly preserves "per-session budget
counters" as legitimate, non-agent-memory governance. Since the ADR's future
orchestrator loop is expected to live in a *separate repo* but very plausibly on this
*same single-operator workstation*, an unscoped `/api/v1` read-twin is a plausible
door for that loop to read the corpus at volume while bypassing the exact budget
governance the MCP surface enforces for agent callers — without being an "MCP tool"
the boundary rules even contemplate policing. This is fixable, not fatal: add explicit
scope language (and ideally a lightweight guard, e.g. Sec-Fetch-Mode/Referer check
tied to `/ui/search`) stating these routes are the human-workbench's internal API,
not a documented contract for programmatic/agent consumption.

**(c) bare-status / trust-enum surface** — N/A to this track (no MCP tool surface
touched; this track is UI/export only). No finding.

**(d) categorical novelty claims** — none found. The `wont` list items ("No live
Zotero local-API client," etc., lines 54-58) are internal scope decisions, not
external-absence claims, so they don't trigger the evidence-ledger dated-census
requirement.

### R0-R7 relationship

- **R5 (formal-target-registry), Phase 2** — R5's brief states outright: "Curation
  rides researcher-workbench's labeling UI" (R5 brief line 5) and KR6: "every entry's
  faithfulness review is human, recorded through the workbench labeling instrument"
  (R5 brief line 81-82). The roadmap-briefs README's interlock table (line 55) says
  the same for R2: "R2 assumption review and R5 target curation route through its
  labeling UI." **Gap**: `researcher-workbench-e4`/`m8` (lines 113-123, 498-512)
  scopes the labeling workbench *only* for evidence-engine's 0-3 relevance-grade
  query labeling — there is zero mention of "R2", "R5", "assumption," "faithfulness,"
  or "formal_target" anywhere in this roadmap.yaml. R2's assumption review
  (accept/reject a machine-extracted `effective_hypotheses` candidate) and R5's
  faithfulness review (human sign-off + reviewer/date on a Lean-target-to-statement
  match) are structurally different labeling primitives than a 0-3 relevance grade.
  Explainable by dates — this roadmap predates the 2026-07-11 R-briefs — but it means
  e4/m8 will either need a v2 extension or a bolted-on parallel surface later unless
  the gap is acknowledged now.
- **R1 (source-truth)** — no conflict; researcher-workbench's should-tier assumption
  (line 39-40) already checks live `graph_status` before scheduling graph-link work
  and correctly treats the citation-graph ingest as an external precondition it does
  not own.
- Otherwise complementary, not duplicative, of R0-R7: this track is UI/operator
  tooling: nothing here re-specifies retrieval, claim, or trust semantics owned by
  R1-R7.

### Recommended disposition: **revise-then-commit**

Rationale: the plan is well-evidenced (every epic cites `file:line`), fixes a live
Windows-blocking bug today (404 on every document preview), sequences its own
security-audit gate (issue #9) *before* new routes ship and requires every
subsequent route to pass the same checklist (KR8, line 21) — a genuinely
boundary-respecting design, not just a boundary-adjacent one. It does not conflict
with §4.8's core rules and introduces no agent dispatch. Two specific, narrow
revisions before commit: **(1)** scope `researcher-workbench-e2`'s `/api/v1`
read-twins explicitly as non-agent-facing / human-workbench-internal (with a
same-origin-style guard if practical), so the session-cap governance §4.8 point 1
preserves for agent callers isn't quietly bypassable by a co-located orchestrator;
**(2)** add a should-tier assumption to `researcher-workbench-e4` acknowledging R2's
assumption-review and R5's faithfulness-review labeling needs as declared downstream
consumers (per roadmap-briefs/README.md's interlock and R5's own brief), and either
build minimal extensibility into the v1 data model or explicitly scope e4 as
"eval-fixture-only v1" with a named v2 follow-up. Neither revision touches the
Windows-fix / math-rendering / ops-loop core, so they can land as roadmap-doc edits
at decomposition without re-opening the already-good epic structure.

---

## retrieval-unlocks

### What it scopes

Unlocks retrieval capability the ingest pipeline already built but serving hides:
proof-chunk statement↔proof linkage (`get_chunk(include_referenced=True)`), an
opt-in proof-kind search column, LaTeX-form equation queries routed onto the
existing TED+dense fusion (instead of always falling back to dense-only),
`kind=definition` filtering, withdrawal-aware corpus hygiene, S2-hydrated citation
contexts, and a Stacks Project textbook adapter — with every reranker/embedder/
prefix quality upgrade explicitly gated behind evidence-engine's fixture numbers.
Six epics (`retrieval-unlocks-e1..e6`), `generated_by` 2026-07-07.

### Boundary/trust alignment

**(a) Agent dispatch / agent memory** — none found; this is pure server-side
retrieval-serving work (search_papers/get_chunk/find_equation/cite_neighbors
handlers). Clean.

**(b) Write-path gating** — `retrieval-unlocks-e5` (Stacks Project ingest, line
108-117) is "a new per-chapter ingest driver... through the existing LaTeXML-to-
theorem-aware-chunker lane" — offline-ingest-CLI-shaped, consistent with existing
`ingest/` patterns. `retrieval-unlocks-m7`/spike-1 (lines 370-396, citation-context
backfill) hydrates Kuzu via "the existing introspect-and-ALTER precedent" — also
ingest-pipeline-shaped, not an MCP-surface write. No MCP tool gains a write
capability anywhere in this track; `search_papers`/`get_chunk`/`find_equation`/
`cite_neighbors` all stay read-only, consistent with ADR Decision 1 rule 2 / §4.8
point 2. No finding.

**(c) bare-status / trust-enum surface** — this is the track's live issue, and it's
real. `retrieval-unlocks`'s roadmap.yaml (generated 2026-07-07) **predates**
trust-language-policy's acceptance (data-plane-governance-m3, 2026-07-12) and
contains zero references to CLAUDE.md §4.9, `trust-language-policy.md`, or
`evidence-ledger-standard.md` anywhere in its `evidence:` section (lines 49-58) —
despite touching exactly the "proofs/equations/definitions" trust-bearing surfaces
the policy targets. In shape, the concrete field choices already lean the right
way — KR2/KR3 (lines 14-15) reuse the existing `retrieval_mode`/`excluded_kinds`
fields "honestly" rather than inventing a new bare status, and `retrieval-unlocks-m6`
(withdrawal hygiene, line 359-368) uses namespaced fields (`withdrawn`,
`arxiv_version_latest`, a "newer-version-exists" staleness signal) rather than one
collapsed enum — so this is a citation gap more than a design gap. But one concrete
acceptance-criteria hole will reproduce a documented defect pattern:
`retrieval-unlocks-m1` (`get_chunk` stmt↔proof linkage, lines 131-146) has three
acceptance criteria (lines 142-144) covering "proof found via theorem_label,"
"proof found via adjacency fallback," and "reverse proof→statement lookup" — but
**no criterion for "no proof exists anywhere in the paper for this
theorem_label."** `trust-language-policy.md` §5d (lines 132-138) already found and
named this exact defect shape in `get_definitions` ("an unknown paper and a real
paper with zero definitions collapse to the identical
`{definitions: [], total: 0, index_status: "ok"}`"); `get_chunk(include_referenced=
True)` returning a silently empty proof list for "no proof exists" vs. "lookup
failed" is the same collapse, one handler over.
**(d) categorical novelty claims** — none of substance. "the flagship math-native
differentiator" (brief, line 8) is positioning language about this product's own
design, not an external "no system does X" claim, so it doesn't trigger the
evidence-ledger dated-census requirement (§4.9 rule 3) — flagged only for
completeness, no revision needed.

### R0-R7 relationship

The task brief's prior (R2 claim-graph / R6 proof-structure overlap) does **not**
hold up on close reading, and it's worth stating why rather than confirming it by
default: R2's claim-edge/proof-DAG work operates on **citation** (`\ref{}`)
resolution and semantic block/claim IR (R2 KR5, R2 brief line 68); `retrieval-
unlocks-e1`'s statement↔proof linkage is a different, pre-existing relation — pairing
a chunk with *its own* proof via `(paper_id, theorem_label, kind='proof')`, already
latent in the chunker's schema, not a `\ref{}` edge at all. R6's own evidence section
(line 116) confirms the relationship is composition, not duplication: the example
lane "is largely serving paid-for structure (matches retrieval-unlocks' 'unlock'
pattern)." No revision needed here — this is a correct complement, not an overlap to
resolve.

The overlap that **does** hold up is with **R1 (source-truth)**, and it is already
named in R1's own brief but not yet acted on in retrieval-unlocks' file.
`R1-source-truth.md` (evidence section, lines 107-109) states explicitly:
"`plans/retrieval-unlocks/roadmap.yaml` — withdrawal hygiene already planned; dedupe
at decomposition (this brief owns the *registry*; that track owns the search-filter
behavior)." R1's KR2 (R1 brief lines 46-49) scopes a `documents` registry table
storing, per revision, "version... status (active / withdrawn / superseded-by)...
fetch timestamp" — nearly identical fields to what `retrieval-unlocks-m6` (line 360)
independently scopes persisting: "versions[]/arxiv_version_latest/withdrawn/
fetched_at/source_route from already-harvested arXivRaw data." `retrieval-unlocks-m6`
has **no `depends_on`** referencing `source-truth`/R1's registry milestone (confirmed:
`plans/source-truth/roadmap.yaml` exists as a sibling untracked track, also
`status: active, phase: complete`, in this same disposition wave). Left as-is, both
tracks would independently persist overlapping withdrawal/version fields from the
same arXivRaw source — exactly the duplicate-persistence-path risk R1's own text
flags as needing resolution "at decomposition," which hasn't happened yet in this
file.

### Recommended disposition: **revise-then-commit**

Rationale: the retrieval-unlocking core (proof-chunk search, LaTeX-routed TED
equations, definition filter) is sound, serves genuine already-paid-for capability,
and already embeds the right discipline — every quality-sensitive change (rerank,
embedder, prefixes, the proof-search default-flip) is explicitly held behind
evidence-engine's fixture numbers (KR8, line 20; `retrieval-unlocks-m3`, lines
261-269), which is exactly the "trust and truth before capability" standing policy
the roadmap-briefs program requires. It does not conflict with §4.8 (no agent
dispatch, no new MCP writes) and its R2/R6 relationship is genuinely complementary,
not duplicative. Two specific, narrow revisions before commit: **(1)** give
`retrieval-unlocks-m6` an explicit `depends_on` on `source-truth`/R1's
document/revision-registry milestone, and narrow its own summary to *consume* R1's
persisted version/withdrawal fields (once R1 lands) rather than independently
re-deriving them from arXivRaw — resolving the dedupe R1's own evidence section
already called for but that hasn't been executed yet; if R1 is vetoed elsewhere in
this disposition wave, m6 should say explicitly that it then owns minimal fallback
persistence itself. **(2)** Add a citation to CLAUDE.md §4.9 / `trust-language-
policy.md` in the `evidence:` section (the policy postdates this roadmap's authoring
date), and add one acceptance criterion to `retrieval-unlocks-m1` covering "no proof
exists anywhere in the paper for this `theorem_label`" as an explicit not-found/
abstention-shaped result, distinct from a lookup error — pre-empting the exact
`not-in-corpus`-vs-empty collapse the policy already caught once in `get_definitions`.
