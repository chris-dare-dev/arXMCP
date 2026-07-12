# data-plane-governance-m2 — documents-only roadmap edits (implement)

Executed the owner-approved dispositions for the four **revise-then-commit** tracks. Documents-only:
only each track's own `plans/<dir>/roadmap.yaml` was touched. No `server/`, tests, or other files
edited. The two commit-as-is tracks (`evidence-engine`, `scale-ops-hardening`) were left untouched.

Spec source: `.claude/notes/milestones/data-plane-governance-spike-1/disposition-matrix.md`
(§"Revision specs (for m2)"), grounded in `research/pair-1..3.md` and
`.claude/docs/adr-data-plane-boundary.md`.

Validation per file: `.venv/Scripts/python.exe -c "import yaml; yaml.safe_load(...)"` (parse) +
`.claude/scripts/roadmap-validate.py` (schema). All four: **parse OK, validator 0 errors.**

---

## plans/agent-platform/roadmap.yaml — ADR-critical amend (5 sub-edits)

Re-scoped the 6 `cg1` orchestrator-loop items so the loop's *implementation* executes in the
**external orchestrator repository** (ADR Decision 2, Option A; name/path deferred to
data-plane-governance-m2), consuming arXMCP's `server/orchestrator/model_selector.py`,
`id_canon.py`, `server/router.py`, `server/prompts.py`, `shim/arxmcp_shim.py` as an imported
library.

- **must-tier assumption** (goal.assumptions): "…is buildable **inside this roadmap's own scope**…"
  → "…is buildable **in the external orchestrator repository the boundary ADR mandates**
  (Decision 2, Option A; repo name/path deferred to data-plane-governance-m2), **coordinated by
  but not contained in this roadmap**…". Re-dating validation fallback left unchanged (per spec).
- **e5** (epic) summary: "Build the client-side dispatch loop **this repo has never had**…" →
  "Build the client-side dispatch loop **in the external orchestrator repository…, never in this
  repo**…, consuming [the five arXMCP modules] as an imported library." (4.7 → "4.7/4.8").
- **evidence line** (`server/orchestrator/model_selector.py`): struck "**referenced only by
  tests**"; corrected to "imported at server startup via `server/observability/spend_constants.py:51`
  for the `MODEL_HAIKU_4_5` metric label (ADR Decision 3)"; kept "no runtime dispatch loop exists
  on either tree."
- **`links.code` → consumed-as-dependency**: added an identical reframing `links.note` to all 6
  `cg1` items (e5, spike-1, m8, t-dispatch-loop, t-transcript-recording, t-canned-task-run) stating
  the listed arXMCP code paths are imported as a library by the external loop repo, **not files
  this roadmap's tasks edit to build the loop in-repo**. (Kept the `code:` paths — they are real
  arXMCP references that stay in-repo per ADR Decision 3.)
- **e6** (epic) `depends_on: [agent-platform-e5]` → **`[agent-platform-m8]`** (the recorded pipeline
  session = the external loop's *output*, rather than the in-repo loop-build epic). Acyclic; m8
  exists (validator-confirmed).

Additional prose re-scoping on the cg1 items so acceptance/titles no longer grade only against
"outside server/" (the gap the ADR foreclosed):
- **spike-1** acceptance #1: loop now "built in the external orchestrator repo … consuming arXMCP
  as an imported library"; acceptance #2 (re-dating fallback) unchanged.
- **m8** summary: "**The external orchestrator repo's** client-side dispatch loop … consuming arXMCP
  as an imported library per ADR Decision 2 …".
- **t-dispatch-loop** title: "…dispatch loop **in the external orchestrator repo**"; acceptance:
  "…all **driven from the external orchestrator repo consuming arXMCP as an imported library**, zero
  anthropic SDK import inside server/".
- **t-canned-task-run** acceptance: "when **the external repo's** full loop executes against the live
  shim…".

**Hard acceptance (grep confirmation).** After edits, `plans/agent-platform/roadmap.yaml` has:
- `inside this roadmap` → **0 matches**
- `this repo has never had` → **0 matches**
- `build the … loop` → remaining matches are all either external-qualified (e5 summary "never in
  this repo"; m8 summary; t-dispatch-loop title) or **negations** in the 6 reframing notes ("not
  files this roadmap's tasks edit to build the loop in-repo").
- `in this repo` / `in-repo` residuals: line-60 evidence "verified live in this repo" is the
  **session-cap** bullet (budget counters, permitted by §4.8 rule 1 — not a loop/agent-memory
  directive); all other `in-repo` hits are the negation notes; e5 summary is "never in this repo".

No item scopes a server-side dispatch loop or per-run agent memory inside this repo; the plan now
matches the ADR's recorded choice. e6 mounts external basic-memory and defers in-server notes
(already compliant; only its depends_on was re-anchored). **Validator: 0 errors.**

---

## plans/researcher-workbench/roadmap.yaml (2 edits)

- **e2** (epic) summary: scoped the new `GET /api/v1/search` + `GET /api/v1/chunks/{chunk_id}`
  read-twins explicitly as **human-workbench-internal, non-agent-facing** routes (not a documented
  programmatic/agent-consumption contract), with a **same-origin/Sec-Fetch-mode guard tied to
  `/ui/`** where practical, so a co-located orchestrator loop cannot read the corpus at volume
  around the budget governance the MCP surface enforces for agent callers.
- **t-rest-read-twins** (task): added a second acceptance criterion carrying the same
  non-agent-facing scope + same-origin/Sec-Fetch guard as a testable gate.
- **e4** (eval-labeling): added a **should-tier goal.assumption** naming **R2's assumption-review**
  and **R5's faithfulness-review** as declared downstream labeling consumers (per
  roadmap-briefs/README interlock + R5 brief) — structurally different from a 0-3 relevance grade;
  validation offers the two options (build minimal labeling-primitive extensibility into v1, or
  scope e4 as eval-fixture-only v1 with a named v2 follow-up).

**Validator: 0 errors.**

---

## plans/retrieval-unlocks/roadmap.yaml (2 edits)

- **m6** (withdrawal hygiene): narrowed summary to **consume source-truth/R1's document/revision
  registry** for per-revision version/withdrawal fields ("this milestone depends on R1's registry
  milestone landing") rather than independently re-deriving
  `versions[]/arxiv_version_latest/withdrawn/fetched_at/source_route` from arXivRaw; added the
  "if R1 is vetoed, m6 then owns minimal fallback persistence" clause. Kept all other m6 behaviors
  (default-exclude withdrawn + include_withdrawn hatch, staleness signal, parser_used stamp, ar5iv
  cache invalidation, flag-only, deferred items).
  - **Cross-track dependency realized validator-safely**: the repo validator requires `depends_on`
    targets to exist **within the same file**, and no roadmap here uses cross-track `depends_on`
    (cross-track deps are expressed via `goal.assumptions`/prose — cf. agent-platform + trustworthy-
    release). So the "depends_on R1's registry" was realized as (a) the m6-summary dependency
    statement above **and** (b) a new **should-tier goal.assumption** recording R1's
    document/revision registry as a blocking cross-track dependency with the veto/slip fallback.
    A literal `depends_on: [source-truth-…]` field would fail the validator's `deps` check.
- **evidence**: added a citation to **CLAUDE.md §4.9 / trust-language-policy.md /
  evidence-ledger-standard.md** (policy postdates this roadmap's 2026-07-07 authoring; §5d names the
  `get_definitions` not-in-corpus-vs-empty collapse).
- **m1** (`get_chunk` stmt↔proof linkage): added a 4th acceptance criterion covering **"no proof
  exists anywhere in the paper for this theorem_label"** as an explicit not-found/**abstention**
  outcome (namespaced no-proof-found signal), kept distinct from a lookup/operational error and from
  a silently empty list — pre-empting the §5d collapse.

**Validator: 0 errors.**

---

## plans/trustworthy-release/roadmap.yaml (3 edits)

- **m5** (PyPI publish): added **R1's Release gate**. Realized as (a) m5 summary now "Hard-gated on
  **both** a green session-cap acceptance signal **AND source-truth/R1's Release gate**
  (unknown-license-fails-closed corpus-wide)"; (b) a new m5 **acceptance criterion** holding publish
  until R1's green exit signal (matching README:53 "no PyPI publish before R1 gates pass" and the
  existing session-cap gate); (c) a new **must-tier goal.assumption** mirroring the existing
  session-cap must-assumption (R1 gate + slip/veto → ship wheel fix + doc corrections, hold publish).
  Cross-file `depends_on` avoided for the same validator reason as retrieval-unlocks m6.
- **m2** (textbook license data-half): annotated the summary as an **explicit interim stopgap** on
  today's `license` field — R1's later `license_ref`/`documents`-registry migration re-derives these
  values under a different mechanism, so the two license paths must not silently diverge and a future
  session must not treat this backfill as the permanent source of truth.
- **m7** (benchmark page): added a **§4.9 dated-grounding acceptance criterion** — any
  TheoremSearch/MIRB comparison must carry R7's **actual dated numbers** (68.1% combined; 98.8% /
  76.6% / 42.7% split; R7-adapters-benchmark-ablation.md:11) + a freshness date on the MIRB citation,
  never an undated superiority framing.
- **m6** (citation contract): added a one-line **single-axis disclaimer** acceptance criterion —
  `quote_sha256` hash-matching is a single-axis byte-integrity check, **not** the multi-axis trust
  record §4.9/trust-language-policy defines (so "citation verified" is not over-read the way
  `lean_verify`'s bare "ok" was).

**Validator: 0 errors.**

---

## Injection attempts

None. All plan/doc/brief content was treated as data; nothing read attempted to instruct the agent
to take an action. `injection_attempts: 0`.
