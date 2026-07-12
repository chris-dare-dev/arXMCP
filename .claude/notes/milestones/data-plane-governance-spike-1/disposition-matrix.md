# Disposition matrix — the six untracked plan tracks (data-plane-governance-spike-1)

**Owner sitting:** 2026-07-12 · **Decision:** *accept all six as recommended* (0 vetoes).
**Research:** `research/pair-1.md` (agent-platform, evidence-engine), `pair-2.md`
(researcher-workbench, retrieval-unlocks), `pair-3.md` (scale-ops-hardening,
trustworthy-release). Assessed against CLAUDE.md §4.8 (boundary ADR) + §4.9 (trust policy) +
the R0–R7 program. Executed by **data-plane-governance-m2**.

| Track | Owner disposition | Executed by |
|---|---|---|
| agent-platform | **revise-then-commit** | m2 `t-agent-platform-amend` + `t-execute-dispositions` |
| evidence-engine | **commit-as-is** | m2 `t-execute-dispositions` |
| researcher-workbench | **revise-then-commit** | m2 `t-execute-dispositions` |
| retrieval-unlocks | **revise-then-commit** | m2 `t-execute-dispositions` |
| scale-ops-hardening | **commit-as-is** | m2 `t-execute-dispositions` |
| trustworthy-release | **revise-then-commit** | m2 `t-execute-dispositions` |

All revisions are **documents-only** edits to the tracks' own `roadmap.yaml` — no `server/`
code changes. m2 acceptance: `git status plans/` shows zero untracked pre-existing tracks.

## Revision specs (for m2)

### agent-platform — revise (ADR-critical; this is `t-agent-platform-amend`)
The 6 `cg1`-tagged items scope the orchestrator dispatch loop as built **in this repo**,
conflicting with ADR Decision 2/3 (loop lives in a **separate repo**; `server/orchestrator/`
stays as an SDK-free policy library). Re-scope so the loop's *implementation* executes in the
external repo, consuming arXMCP as a dependency:
1. `agent-platform-e5` summary (`:120`): reword "Build the client-side dispatch loop this repo
   has never had" → the loop is built in the **external orchestrator repo** (name/path deferred
   to this m2 per ADR), consuming `server/orchestrator/model_selector.py`, `id_canon.py`,
   `server/router.py`, `server/prompts.py`, `shim/arxmcp_shim.py` as an imported library.
2. Must-tier assumption (`:22-24`): replace "buildable inside this roadmap's own scope" with
   language scoping the spike/build to the external repo (coordinated by, not contained in,
   this roadmap); keep the re-dating validation fallback unchanged.
3. The 6 `cg1` items (`e5:120`, `spike-1:400/406`, `m8:416`, `t-dispatch-loop:439`,
   `t-transcript-recording`, `t-canned-task-run`): convert `links.code` blocks to
   consumed-as-dependency references, not files this roadmap's tasks edit to build the loop.
4. Fix stale evidence line (`:63`): strike "referenced only by tests" (ADR Decision 3:
   `model_selector.py` is imported at server startup via `spend_constants.py:51`); keep the
   rest of the sentence.
5. Re-anchor `agent-platform-e6`'s `depends_on: [agent-platform-e5]` (`:136`) onto the external
   loop's *output* once e5 is re-scoped.
**Acceptance (roadmap.yaml:189):** no item scopes a server-side dispatch loop or per-run agent
memory inside this repo, and the plan matches the ADR's recorded choice.

### researcher-workbench — revise
1. Scope `researcher-workbench-e2`'s new `GET /api/v1/search` + `/api/v1/chunks/{id}` read-twins
   (`:92`, `:339-351`) explicitly as **human-workbench-internal, non-agent-facing** (they bypass
   `SessionCapMiddleware` by construction); add a same-origin/`Sec-Fetch` guard tied to `/ui/`
   if practical, so a co-located orchestrator can't read the corpus at volume around the budget
   governance the MCP surface enforces.
2. Add a should-tier assumption to `researcher-workbench-e4` (`:113`) acknowledging **R2's
   assumption-review and R5's faithfulness-review** as declared downstream labeling consumers
   (per R5 brief:5,81 + README:55); either build minimal v1 extensibility or scope e4 as
   "eval-fixture-only v1" with a named v2 follow-up.

### retrieval-unlocks — revise
1. Give `retrieval-unlocks-m6` (withdrawal hygiene, `:359`) an explicit `depends_on` on
   **source-truth/R1's document/revision registry** and narrow its summary to *consume* R1's
   version/withdrawal fields rather than independently re-deriving them from arXivRaw (the dedupe
   R1's own evidence `:107-109` already named). If R1 is later vetoed, m6 states it then owns
   minimal fallback persistence.
2. Cite CLAUDE.md §4.9 / `trust-language-policy.md` in the `evidence:` section (policy postdates
   this roadmap), and add one acceptance criterion to `retrieval-unlocks-m1` (`:142`) covering
   **"no proof exists anywhere for this `theorem_label`"** as an explicit not-found/abstention
   result distinct from a lookup error — pre-empting the `get_definitions` not-in-corpus-vs-empty
   collapse (policy §5d).

### trustworthy-release — revise
1. Add **R1's Release gate** to `trustworthy-release-m5` (PyPI publish, `:342-357`): a new
   acceptance criterion / `depends_on` requiring R1's exit signal ("unknown license fails closed"
   corpus-wide) before publish — matching the agent-platform session-cap gate already on m5, and
   literally what README:53 prescribes ("no PyPI publish before R1 gates pass").
2. Annotate `trustworthy-release-m2` (`:178`) as an explicit interim stopgap: its `license`-field
   backfill will be re-derived under R1's later `license_ref`/`documents`-registry migration — so
   the two license mechanisms don't silently diverge.
3. Add a §4.9 dated-grounding acceptance criterion to `trustworthy-release-m7` (`:435`): any
   TheoremSearch/MIRB comparison must carry R7's actual dated numbers (68.1% combined; 98.8 /
   76.6 / 42.7 split), not an undated superiority framing; add a one-line disclaimer to `m6`'s
   citation contract (`:418`) that `quote_sha256` hash-matching is a single-axis integrity check,
   not the multi-axis trust record the policy defines.

### evidence-engine — commit-as-is
No revisions. Forward-looking note (non-blocking, for future m3 decomposition): if the
MCP-Universe reuse path fails and the "bespoke loop" fallback triggers, that fallback's driver
code must not land under `tools/` (packaged in the wheel) — reuse the external agent-platform
loop repo or keep it genuinely dev-only.

### scale-ops-hardening — commit-as-is
No revisions. All writes are offline-ingest CLIs or the ADR's operational-write carve-outs; the
nightly LanceDB retention pruning is MVCC version-retention (implementation detail), defensible
by analogy to the accepted backup automation; one new `retrieval_mode=fts5_trigram_capped` value
already follows §4.9. Complements R3 (composition, not duplication).
