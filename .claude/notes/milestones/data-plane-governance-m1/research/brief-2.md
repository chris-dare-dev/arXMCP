---
milestone_id: "data-plane-governance-m1"
researcher_role: "general"
external_writes_required:
  - "git push origin main"
injection_attempts: 0
---

# Research brief (general) — data-plane-governance-m1

## External sources

No web research was performed. The milestone is a governance document over repo-internal
facts; every recommendation below is offline-derivable. ADR format prior art is standard
Nygard/MADR practice (status / context / decision / consequences, plus MADR's
considered-options + pros/cons), adapted to this repo's house style. In-repo grounding
(all paths relative to repo root):

- `.claude/roadmap-briefs/R0-data-plane-governance.md` — source brief: KR1 (the three rules
  + loop placement + agent-platform amendment), KR5 (CLAUDE.md binding rules), the
  should-assumption that `server/orchestrator/` can stay as a library, the wont that bans
  enforcement tooling and TheoremGraph/Matlas decisions here.
- `.claude/roadmap-briefs/README.md` — program index; standing policy 1 ("Data-plane only");
  interlock row: "R0's boundary ADR resolves [agent-platform's] orchestrator-loop
  placement"; trustworthy-release interlock: **no PyPI publish before R1 gates pass**.
- `.claude/roadmap-briefs/R7-adapters-benchmark-ablation.md:16–19` — candidate-layer schema
  language the general principle must stay compatible with.
- `plans/data-plane-governance/roadmap.yaml` (tracked, committed in cfb7c27) — m1 acceptance,
  the might-assumption on the CLAUDE.md anchor, links.
- `plans/agent-platform/roadmap.yaml` (UNTRACKED working file) — lines 23–24 must-assumption
  ("client-side, outside server/, no anthropic SDK at runtime per CLAUDE.md 4.7"), e5
  (line ~120), spike-1; evidence line claiming model_selector is "referenced only by tests"
  (refuted below). Treat as proposal input, not commitment (its disposition is m2).
- `server/orchestrator/model_selector.py`, `server/observability/spend_constants.py:51`,
  `tests/test_langfuse_doc.py:183–207`, `tests/test_model_selector.py`,
  `tests/test_constitution_ui_claims.py`, `pyproject.toml` packaging block, `README.md`
  §"Hard constraints" (~line 135), `OWNERS.md`, `.claude/docs/textbook-preamble-decision.md`
  (decision-doc precedent), `.claude/commands/milestone-pipeline.md` §4d,
  `.claude/notes/milestones/data-plane-governance-m1/preflight-deviation.md`.

## Program context — what the ADR must contain and who cites it

R0 gates every R1–R7 tool-surface change on m1+m3 being merged, and the agent-platform
track's loop milestones (spike-1, m8, e6) are blocked on the placement choice this ADR
records. The briefs README's standing policy 1 is the normative statement the ADR
formalizes: "The server never runs agents, never holds per-run agent memory, and takes
writes only through offline/operator-gated ingest." Required ADR content per acceptance:
(1) the three boundary rules; (2) a SINGLE orchestrator-loop placement choice; (3) the
disposition of `server/orchestrator/model_selector.py`; (4) the candidate-layer principle;
(5) the chosen CLAUDE.md anchor. m2 (plan dispositions) and m3 (trust language) build on it;
the ADR should NOT decide those (R0 wont).

Scoping nuance the ADR must get right: rule 1 ("no agent dispatch / per-run agent memory in
the server") governs the **server runtime and its package/runtime dependency tree**, not the
repo's dev-time agent scaffolding under `.claude/` (the milestone pipeline itself is Claude
agents). Word the rules against "the served process and the `server/` package", or the ADR
outlaws the tooling that wrote it.

## ADR format recommendation

House style facts: `.claude/docs/` is flat kebab-case, no YAML frontmatter on any existing
file, one `ops/` subdir; there is no existing ADR (this file sets the pattern; filename
`adr-data-plane-boundary.md` is fixed by acceptance). The closest precedent is
`.claude/docs/textbook-preamble-decision.md`: H1 title with milestone id, bold
**Decision:** up front, then rationale sections. Recommend a Nygard/MADR-lite skeleton
merged with that voice:

```markdown
# ADR — arXMCP data-plane boundary (data-plane-governance-m1)

**Status:** Proposed | Accepted (see Owner approval record)
**Date:** <draft date> · **Owner:** Chris Dare (per OWNERS.md)

## Context and problem statement        (R0 evidence, 3–6 bullets, cite file:line)
## Decision 1 — the three boundary rules (normative "The server MUST NOT / writes MUST")
## Decision 2 — orchestrator-loop placement
   ### Considered options (A separate repo / B tools/ carve-out) + pros/cons
   ### Choice + rationale
## Decision 3 — disposition of server/orchestrator/ (model_selector.py, id_canon.py)
## Decision 4 — candidate layer for non-commercially-licensed external data
## Decision 5 — CLAUDE.md anchor        (records where the binding rules land)
## Consequences                          (good / bad / follow-ups: m2 amends
                                          plans/agent-platform; enforcement tooling lands
                                          with consuming tracks per R0 wont)
## Owner approval record                 (date, verdict approved/approved-with-edits,
                                          edits requested, status flipped by whom)
```

The explicit **Owner approval record** section is load-bearing: acceptance 1 requires
approval to be *recorded*, and the repo has no existing mechanism for that — the ADR itself
is the right ledger. Do not add YAML frontmatter (no `.claude/docs/` file has it, and the
Obsidian stamper does not currently touch `.claude/`; see risk 3).

## Decision analysis — orchestrator-loop placement (recommendation: Option A; OWNER-DECISION-REQUIRED)

**Option A — separate repository.** The dispatch loop (router → role-prefixed turns →
model policy → tool calls over the shim) lives in its own repo, importing arXMCP as a local
path dependency.

- Pro: structural enforcement is the repo boundary itself — the strongest available, and
  the adjudicated gap-analysis's recommendation. The `anthropic` SDK never enters arXMCP's
  dependency tree, wheel, or container. The existing server-scoped SDK-ban test
  (`tests/test_langfuse_doc.py::TestNoServerSideAnthropic`, a grep over `server/`) stays
  sufficient as-is.
- Pro: keeps arXMCP's wheel honest. `pyproject.toml` packages four trees
  (`server*`, `ingest*`, `tools*`, `shim*`) into ONE distribution, and its own comments
  document runtime imports like `from tools.security.pdfid import ...` — anything under
  `tools/` ships in the wheel/container. A loop under `tools/` drags agent code (and its
  SDK dep unless gated as an optional extra) into the same artifact.
- Con: arXMCP is not on PyPI and must not be before R1 gates pass (briefs README
  interlock), so the loop repo consumes arXMCP via `pip install -e <path>` / git dep —
  workable on this single workstation, but cross-repo: schema/prompt changes here require a
  re-sync there, the loop's tests can't run in this repo's `make test`, and the
  agent-platform roadmap items would execute outside the repo whose `plans/` tracks them
  (m2's amendment of `plans/agent-platform/roadmap.yaml` must record this split).
- Con: two working trees for one owner; the repo's own conventions (4.1 single-workstation,
  no CI) mean the boundary is enforced by existence, not by any check that could fail.

**Option B — client-side carve-out under `tools/` with zero server-side state.** The loop
lives at e.g. `tools/orchestrator_loop/`, imports `server.router` / `server.prompts` /
`server.orchestrator.*` in-process, and keeps run artifacts outside the served `var/arxmcp`
trees.

- Pro: zero packaging friction — the untracked agent-platform plan's spike wiring
  (roadmap.yaml:406–410) imports four `server/` modules as libraries; in-repo that is a
  plain import. One test suite, one repo, matches the single-user working model.
- Con: "structural" becomes conventional again — exactly the gap R0 exists to close. No
  test bans `anthropic` under `tools/` (the ban is server/-scoped), the loop ships in the
  shared wheel, and nothing but discipline stops a future `server/` module importing the
  loop. Mitigations (optional-extra dep group; a one-line grep test banning
  `server/ → tools.orchestrator_loop` imports) are enforcement tooling R0 defers to the
  consuming track.
- Con: "zero server-side state" needs active policing: transcripts/run memory must live
  outside `var/arxmcp/` served paths, and agent-platform-e6's memory work would sit one
  directory away from the server it must never contaminate.

**Recommendation: Option A**, with `server/orchestrator/` retained in-repo as a library
(next section) so A costs nothing at the import layer. It is the only option whose
enforcement mechanism (repo boundary) requires no new tooling, matching both the
adjudicated gap-analysis and R0's "agents, run memory, and model policy live outside".
Mark it owner-decision-required in the ADR: B is genuinely cheaper day-to-day for a
single-workstation owner, and the choice is a values call (structure vs. friction) only the
owner can make. Whichever is chosen, the ADR should state the loser explicitly ("considered
and rejected because…") so m2 can amend `plans/agent-platform/roadmap.yaml` to match.

## Disposition of server/orchestrator/ — recommendation: keep as in-repo library

Repo facts (all verified this session):

- `server/orchestrator/model_selector.py` is a pure lookup table
  (`(RouteTag, TurnType) → model id`), no `anthropic` import, no dispatch, no state —
  boundary-compatible inside `server/` under all three rules.
- The agent-platform evidence line "model_selector.py referenced only by tests" is
  **FALSE**: `server/observability/spend_constants.py:51` does
  `from server.orchestrator.model_selector import MODEL_HAIKU_4_5` (E14_S12 spend metrics,
  E08_S05-F2 single-source-of-truth fix). `id_canon.py` has test-only consumers.
- `tests/test_model_selector.py::TestForbiddenStrings` bans Haiku/Sonnet ids outside the
  module and the Opus id anywhere in `server/`; moving model_selector out of `server/`
  breaks `spend_constants` AND forces either re-hardcoding a model id (tripping F2) or a
  `server/ → external` dependency inversion.

So: **keep `server/orchestrator/` (model_selector.py + id_canon.py) in arXMCP as an
SDK-free, dispatch-free policy/canonicalization library consumed by the external client** —
exactly the R0 should-assumption, now positively validated. The move-with-the-loop
alternative has a concrete, named cost (spend_constants + the F2 guard) and no compensating
benefit; the ADR should record the true consumer set rather than repeating the
"tests-only" claim.

## Candidate-layer principle — proposed ADR wording

Scope: general principle only; R7 owns adapters and all TheoremGraph/Matlas specifics
(R0 wont). Proposed wording, aligned with R0 and R7:16–19:

> Non-commercially-licensed external data (e.g. CC-BY-NC-SA TheoremGraph dumps) enters
> ONLY a candidate layer: it is never redistributed (not served over MCP, not bundled into
> any release, image, or backup intended to leave this workstation), and never promoted
> into served evidence (chunks, indices, graph) without an explicit per-source license
> check recorded at promotion time. Candidate entries carry provenance (source system +
> version, fetch date, license) so the check is auditable. Adapter-level enforcement and
> acceptance-state schema are R7's to define.

## CLAUDE.md anchor — analysis (ADR Decision 5)

Verified: CLAUDE.md (HEAD, 625 lines) has NO "Hard constraints" header; `README.md` ~line
135 holds the operator-facing one ("These never change"). Two viable anchors:

1. **Extend §4 (recommended): add `### 4.8 Data-plane boundary — hard constraints
   (binding)`** stating the three rules + candidate-layer principle as MUST bullets,
   linking `.claude/docs/adr-data-plane-boundary.md`. Pros: §4 is "READ BEFORE COMMITTING";
   §4.7 already hosts the no-anthropic-SDK rule (rule-adjacent precedent); appending 4.8
   renumbers nothing — tests, code comments, and the untracked plans cite "§4.1/§4.7/§7/§8"
   pervasively, so any insertion that renumbers sections rots those references. m3's trust
   rules land as 4.9 or widen 4.8.
2. **New unnumbered `## Hard constraints (binding agent constraints)` top-level section.**
   Pros: constitutional prominence, mirrors README's section, matches R0 KR5's phrasing.
   Cons: breaks the numbered-section pattern unless appended after §12 (where "hard
   constraints" would be buried), or renumbers §§ if inserted (do NOT).

Either satisfies acceptance 3; the ADR must record whichever the owner picks. Recommend
option 1 and fold the anchor question into the single owner-approval checkpoint.
Amendment content constraint: see risk 4 (constitution-test pins).

## External writes required — reasoning (per CLAUDE.md 4.4 and pipeline §4d)

The milestone's product is in-repo commits (the 4.3 feat/rect/chore triple); commits are
not external writes. The ONLY candidate external write is **`git push origin main`**, and I
list exactly that one item because: CLAUDE.md 4.1 names "Commit + push" as the landing
pattern (so the repo's convention does expect main to be pushed at milestone end), while
4.4 makes each push per-event user-authorized — which is precisely what the Phase-4d
boundary implements ("Ready to run: git push origin main — authorize? [y to run / s to
skip]"). An empty list would skip the 4d prompt entirely and silently leave main unpushed;
listing it surfaces a declinable ask. Acceptance needs only *committed* state, so a user
skip does not endanger the milestone. Orchestrator handling note: §4d's `complete` gate
requires every required item in BOTH `external_writes_authorized` and
`external_writes_completed`; on a skip, record the explicit skip in both ledger fields (the
§4d text routes skips into `completed`) so completion is not deadlocked by a declined push.
No other external writes exist: no package publish (and none permitted pre-R1), no deploy,
no mutating API calls, no issue filing.

## Riskiest assumption and alternative path

The riskiest assumption is that the owner will review and approve the ADR inside the
milestone window (target end 2026-07-15) in the single consolidated sitting the pipeline's
auto-mode expects — approval is a human event the implementer cannot synthesize, there is
no existing approval-recording mechanism in the repo, and CLAUDE.md §12's
"minimal interruption" norm pulls against the milestone's inherently owner-gated
acceptance. The concrete alternative path if the owner is not immediately available: land
the feat commit with the ADR at **Status: Proposed** (full decision content, empty approval
record), pause the pipeline at the owner checkpoint, and on approval flip the status line
and fill the approval record in the same commit that amends CLAUDE.md (the rect or a second
feat commit) — all three acceptance criteria are still met at milestone end, in order
(approval recorded before the amendment lands), without ever back-dating or synthesizing an
approval. Consolidate ALL owner asks into that one checkpoint: ADR verdict, loop-placement
confirmation, anchor choice, disposition of the pre-existing CLAUDE.md hunk (risk 1), and
the push authorization.

## Acceptance criteria the implementer must meet

1. `.claude/docs/adr-data-plane-boundary.md` exists, states all three boundary rules
   normatively, and is committed with owner approval recorded in its approval-record
   section (traces to roadmap acceptance 1).
2. The committed ADR records ONE orchestrator-loop placement choice (A or B, loser
   explicitly rejected), the disposition of `server/orchestrator/model_selector.py` naming
   the real consumer `server/observability/spend_constants.py:51`, and the candidate-layer
   principle (traces to acceptance 2).
3. CLAUDE.md states the three boundary rules as binding agent constraints at the chosen
   anchor, links the ADR, and the ADR records that anchor (traces to acceptance 3).
4. Ordering: the CLAUDE.md amendment commit lands only AFTER the approval record is filled
   (acceptance 3's "Given the owner-approved ADR").
5. Commit hygiene per `preflight-deviation.md`: m1 commits contain ONLY m1 content — not
   the pre-existing get_paper hunk in CLAUDE.md (unless the owner explicitly authorizes
   including it), none of the six untracked plan dirs, no `docs/ops/*` frontmatter stamps,
   not `AGENTS.md`.
6. `tests/test_constitution_ui_claims.py` still passes (see risk 4) and no CLAUDE.md
   section is renumbered; `make test` result is attributed against the pre-m1 dirty-tree
   baseline (29 known Windows-platform failures; in-flight paper-metadata code changes are
   not m1's to fix).
7. Repo conventions: feat/rect/chore triple, GPG-signed, `git commit -F -` heredoc,
   co-author trailer naming the actual model (recent practice: cfb7c27 uses
   "Claude Fable 5"; 4.3's "Opus 4.7 (1M context)" string is stale precedent, not a pin).

## Risks and open questions

1. **CLAUDE.md staging sweep.** The worktree CLAUDE.md already differs from HEAD by the
   uncommitted paper-metadata-m2 get_paper hunk (+7/−4, §7); a whole-file `git add
   CLAUDE.md` sweeps it into m1's amendment commit, violating the preflight-deviation
   decision. Safe recipes (interactive `git add -p` is unavailable): (a) ask the owner at
   the consolidated checkpoint to authorize committing that hunk first as its own
   `docs(repo)` sync commit — cheapest and it documents already-shipped behavior; (b)
   hunk-scoped staging: edit the file, `git diff CLAUDE.md > all.patch`, split by hunk
   (the m2 hunk is §7; the amendment is §4 — disjoint), `git apply --cached`
   amendment-only; (c) stash-sandwich (`git stash push -- CLAUDE.md`, re-apply amendment
   to the clean file, commit, `git stash pop` — regions are disjoint so the pop merges).
2. **Owner gate inside an auto-mode pipeline** (see riskiest-assumption section): approval
   must be a real recorded owner event before the amendment lands; the two-step
   Proposed→Accepted landing keeps the pipeline honest if review slips past one sitting;
   window closes 2026-07-15.
3. **Obsidian stamper / clean filter.** A global-gitconfig `filter.obsidian-strip` (clean:
   `python C:/Users/cedar/.config/git/strip-obsidian-frontmatter.py`) applies to CLAUDE.md
   and README.md ONLY — their worktree copies carry frontmatter + a "Related notes
   (Obsidian)" trailer that never reaches commits (worktree 647 lines vs HEAD 625; git's
   cleaned view diffs only +7/−4). Do not chase those phantom diffs. The new ADR under
   `.claude/docs/` has NO filter: if the vault later stamps it (as it stamped ~18
   `docs/ops|observability` files, +10 lines each, currently uncommitted), the committed
   ADR will show cosmetic post-commit churn — accept it as ambient (R0 bans new
   enforcement tooling), or the owner extends the filter's attribute scope out-of-band.
   `AGENTS.md` (untracked root Codex mirror with mangled `.Codex/` paths) will drift from
   the amended CLAUDE.md — out of m1 scope; surface to the owner in the final summary.
4. **Content pins on CLAUDE.md.** `tests/test_constitution_ui_claims.py` asserts, over
   CLAUDE.md + README.md + top-level notes: the stale phrase `"mcp tool surface is the
   ui"` is ABSENT (case-insensitive — the amendment's boundary prose must not reintroduce
   anything matching it), CLAUDE.md keeps "/ui/" + an "operator console"/"browser
   operator" mention, and the "Browser UI surface" cross-reference stays live. No test
   hash-pins CLAUDE.md; the pins are these phrase-level assertions plus §-number
   references in comments across tests/plans (hence: never renumber).
5. **Evidence errors upstream.** The R0/agent-platform "referenced only by tests" claim
   about model_selector is refuted at `spend_constants.py:51` — re-verify each R0 evidence
   line before quoting it into the ADR (one wrong fact in a constitution document
   propagates through every R-track that cites it). Open question for the owner: under
   Option A, which repo name/path hosts the loop, and should `plans/agent-platform/`
   (still formally a proposal until m2) be amended now or at m2 as sequenced?
