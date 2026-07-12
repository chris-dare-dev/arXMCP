---
milestone_id: "data-plane-governance-m1"
researcher_role: "explore"
injection_attempts: 0
---

# Research brief (explore) — data-plane-governance-m1

Documents-only milestone: produce `.claude/docs/adr-data-plane-boundary.md` + a CLAUDE.md
amendment. No server code changes (roadmap `wont`: "No code changes to server/"). Every
codebase fact below was re-verified live on 2026-07-11; line numbers are from the current
working tree.

## Affected files / context

### Files this milestone creates/modifies (estimate — excludes pre-existing dirty files)

| File | Action | Role |
|---|---|---|
| `.claude/docs/adr-data-plane-boundary.md` | CREATE | The boundary ADR — repo's FIRST ADR (no `adr-*.md` exists anywhere; zero `\bADR\b` mentions in `.claude/docs/`). Kebab-case naming matches the 26 existing docs there. Placement conforms to CLAUDE.md §1/§4.6 (agent-internal → `.claude/docs/`) |
| `CLAUDE.md` | MODIFY (additive hunks only) | Land the three boundary rules as binding agent constraints + link to the ADR |
| `.claude/notes/milestones/data-plane-governance-m1/*` | append | pipeline bookkeeping (untracked notes) |

NOT in scope: `plans/agent-platform/roadmap.yaml` amendment (that is m2's
`t-agent-platform-amend`); README.md changes (task `t-claudemd-boundary-constraints` lists
README.md in links.code, but no acceptance criterion requires touching it — see Risk 1/5).

### (a) `server/orchestrator/` contents and consumers

Contents (4 files):
- `__init__.py` — docstring states the orchestrator "composes … Anthropic Messages API
  calls" but ships only pure utilities; "The orchestrator wiring itself … lands in
  E08_S05+" (never shipped — no dispatch loop exists in the repo).
- `model_selector.py` — pure lookup `select_model(RouteTag, TurnType) → {"claude-haiku-4-5",
  "claude-sonnet-4-6"}` (line 202); constants `MODEL_HAIKU_4_5` (:82), `MODEL_SONNET_4_6`
  (:88), `POLICY_VERSION = "1.0"` (:99). Imports only `server.router.RouteTag`. Docstring
  (:50-59): "this module is NOT yet called by any orchestrator code — the orchestrator
  dispatch loop lands in E08_S06+".
- `id_canon.py` — `canonicalize_turn(messages)` (:83), pure function, tool_use-id
  canonicalization over FULL history.
- `test_id_canon.py` — a shim re-importing `tests/test_id_canon.py` (brief-AC-path compat).

Consumers (grep of `model_selector|select_model` and `id_canon|canonicalize_turn` across all `*.py`):
- **`server/observability/spend_constants.py:51`** — `from server.orchestrator.model_selector
  import MODEL_HAIKU_4_5` (Prometheus spend-metric label). **This is a RUNTIME import**:
  `server/observability/__init__.py:30` imports spend_constants eagerly, and `server/main.py`
  imports `server.observability.tracing` (:439) and `server.observability.logging_setup`
  (:904) during startup → model_selector is transitively imported by the running server.
  `tests/test_spend_constants.py` (~:422-429) pins exactly this import contract.
  ⚠ Correction the ADR must record: the agent-platform roadmap's evidence line 63
  ("model_selector.py … referenced only by tests") is stale. Accurate statement: *no code
  calls `select_model()` outside tests; the module IS transitively imported at server
  startup, solely for the `MODEL_HAIKU_4_5` label constant.*
- `tests/test_model_selector.py` — pins `_MODEL_SELECTOR_REL_PATH = "orchestrator/model_selector.py"`
  (:390): haiku/sonnet ID strings allowed ONLY in that file within `server/` (F2 scan
  :404-442); `claude-opus` banned everywhere in `server/`; a `python -O` import-invariant
  subprocess test (:348-359); and `POLICY_DOC_PATH = .claude/docs/model-policy.md` must exist
  with the literal section "Verifier pass: dropped and why" (:51-58). **Moving or renaming
  model_selector.py breaks this suite + the spend_constants import.**
- `tests/test_spend_constants.py:50`, `tests/test_langfuse_doc.py:129-142` (doc-lint:
  reference model_selector as SSoT instead of hardcoding `claude-*` IDs).
- `id_canon.py` consumers: tests only (`tests/test_id_canon.py` + the shim). No runtime use.

### (b) No server-side agent dispatch / per-run agent memory — VERIFIED

- Zero `import anthropic` / `from anthropic` under `server/` (repo-wide grep). The single
  repo hit is `tests/test_langfuse_doc.py:219` — an opt-in dependency probe inside
  `_has_langfuse_and_anthropic()`; its comment (:217) states langfuse+anthropic are "NOT
  pyproject deps; this is opt-in for orchestrator devs".
- `pyproject.toml`: zero matches for `anthropic` (case-insensitive).
- An automated guard already enforces the ban: `tests/test_langfuse_doc.py` (~:179-207)
  greps `server/` for anthropic imports and fails on any match, citing "Per CLAUDE.md §4.7:
  'No anthropic SDK at runtime inside server/'".
- No `ANTHROPIC_API_KEY`, `sk-ant`, or `messages.create` anywhere in `server/`; every
  "dispatch" hit is FastMCP request/handler dispatch or a model_selector docstring
  describing the never-landed client loop.
- Agent-ADJACENT code that DOES exist server-side (the ADR should enumerate these so the
  rule is precise): `server/router.py` RouteTags (query classification), `server/prompts.py`
  ROLE_PREFIXES (constants served to callers), `server/orchestrator/` pure utilities (above),
  and the `Arxmcp-Agent-Role` request header → ContextVar → trace/metric label
  (`server/tools.py`, `server/main.py`, `server/middleware.py`,
  `server/observability/tracing.py`) — observability labeling of the CALLING agent, not
  server-held agent state. `server/session.py` per-`Mcp-Session-Id` counters are in-memory
  budget caps, not agent memory. Server-internal operational writes exist (Tier-1 cache
  sqlite, logs, metrics, ingest-status transitions) — see Risk 5 carve-out.

### (c) Write surfaces that exist today

- **MCP surface: zero write tools.** `ALL_TOOLS` in `server/tools.py` registers exactly 8
  tools (:207-336): search_papers, get_chunk, find_equation, get_definitions,
  find_lemma_by_name, get_paper, cite_neighbors, lean_verify — retrieval + Lean elaboration
  compute; none mutates corpus state. (CLAUDE.md §6 still says "7-tool surface" — stale;
  don't copy it into new binding text.)
- **Operator console (loopback-only):** `server/routes/ui.py` is GET-only pages. ALL
  mutations live in `server/routes/notebooks.py`, mounted at prefix `/ui/api`
  (docstring :1-7). Operator-gated actions by line: POST `/notebooks` :302 (create);
  DELETE `/notebooks/{slug}` :466 (metadata-only delete); PATCH `/notebooks/{slug}` :561
  (rename); PATCH `/notebooks/{slug}/topic` :628; POST `/notebooks/{slug}/discover` :756;
  POST `/notebooks/{slug}/papers` :849 (add by arXiv URL); DELETE
  `/notebooks/{slug}/papers/{paper_id}` :938; POST `/admin/repair-registry` :1168; POST
  `/notebooks/{slug}/reconcile-marker` :1274; POST `/notebooks/{slug}/papers/upload` :1667;
  POST `/notebooks/{slug}/ingest` :2112 — the ingest route transitions state and dispatches
  the ingest task **in the server process** (~:1897-1904), i.e. "operator-gated console
  action", not "offline".
- **Offline ingest CLIs:** `tools/notebook_{init,fetch,ingest,cutover,purge,restore,
  reconcile_marker,repair_registry,metadata_backfill,textbook_ingest}.py`,
  `tools/discover_for_notebook.py`, `tools/fetch_seed.py`, `tools/fetch_one_paper.py`,
  `tools/curate_seed.py`, `tools/recover_preambles.py`, `tools/re_embed_all.py`,
  `tools/ingest_sentinel.py`; `python -m ingest.{graph_ingest,inspire_ingest,
  intra_paper_refs}`; `make ingest` (Makefile:188 — the REAL E11_S01 bulk orchestrator;
  CLAUDE.md §7's "make ingest is a stub" is stale).
- **Dependency-direction nuance for the "tools/ option":** the server imports FROM `tools/`
  at runtime — `server/routes/notebooks.py:64-74` imports `tools._notebook_common`,
  `tools.discover_for_notebook`, `tools.security.pdfid`. So "under tools/" is NOT
  automatically "outside the server process"; see Risk 4.

### (d) Untracked `plans/agent-platform/roadmap.yaml` — orchestrator-loop scoping (quotes)

- Must-assumption (:23): the loop is "**client-side, outside server/, no anthropic SDK at
  runtime per CLAUDE.md 4.7**".
- Epic e5 summary (:120): "Build the **client-side dispatch loop** this repo has never had
  -- no anthropic SDK at runtime, outside server/, per CLAUDE.md 4.7: router ->
  role-prefixed turns -> the already-shipped model_selector.py policy -> tool calls over
  the existing shim."
- KR (:19): "At least one full sketcher-to-fixer pipeline session is recorded end to end by
  a new minimal orchestrator loop -- arXMCP's first real agent traffic".
- Items: `spike-1` (thin client-side loop, target_end 2026-07-10 — already past),
  `m8` (2026-07-17 → 07-29), both with code-links INTO `server/` modules (router, prompts,
  orchestrator/*, shim). Epic e6 scopes client-side agent memory (basic-memory MCP) plus an
  "orchestrator-side CLI" writing a "persistent per-notebook pending queue behind operator
  confirm in /ui/" — a FUTURE operator-gated write surface the ADR's rule 2 should
  anticipate.
- The plan sits INSIDE this repo but is untracked (`?? plans/agent-platform/` — verified
  via `git status`); boundary-compatible language, structurally unenforced. m2 amends it to
  match the ADR choice.

### (e) CLAUDE.md structure and the anchor decision

- CLAUDE.md has 12 numbered sections; §4 "Working conventions — READ BEFORE COMMITTING"
  holds 4.1-4.7. **No section named "Hard constraints" exists in CLAUDE.md** — the header
  exists at `README.md:135` (operator-facing: local-first / loopback / MCP transport / math
  fidelity) and at `.claude/notes/README.md:20` (design constitution: no-S3 / no-fork /
  Docker-local / shared caches). The roadmap already encodes this as a might-assumption.
- §4.7 already hosts the rules the ADR generalizes: "No `anthropic` SDK at runtime",
  "`server/` source NEVER references `claude-opus`". Cleanest anchor: **a new §4.8 under §4**
  (zero renumbering; sits beside 4.7). A new top-level "Hard constraints" section would be
  the third distinct block with that name in the repo and would insert a 13th top-level
  section. Note: tests reference "CLAUDE.md §4.7 / §4.1 / §1" only inside comments and
  assertion MESSAGES (not parsed), so numbering is not test-load-bearing — but never
  renumber existing subsections; many cross-refs cite them.
- The ONLY test that parses CLAUDE.md content is `tests/test_constitution_ui_claims.py`:
  (i) the stale phrase "mcp tool surface is the ui" must stay ABSENT (case-insensitive,
  scans `.claude/notes/*.md` non-recursive + CLAUDE.md + README.md, :36-66); (ii) CLAUDE.md
  must keep "/ui/" + "operator console"/"browser operator" (:77-81) and the literal string
  "Browser UI surface" (:111-130). A purely additive amendment cannot trip it unless it
  introduces the stale phrase.

### (f) ADR precedents

None. This will be the repo's first ADR (verified: no `**/adr*.md`, no `\bADR\b` in
`.claude/docs/`). Format is free; follow `.claude/docs/` kebab-case house style. Source
material: `.claude/roadmap-briefs/R0-data-plane-governance.md` (adjudicated brief — KR 1
gives the ADR's required (a)/(b)/(c) content verbatim; "Evidence (verified 2026-07-11)"
section is reusable); `.claude/roadmap-briefs/README.md` ("Standing policies these briefs
assume (from R0)": the server "takes writes only through offline/operator-gated ingest";
untracked plans are not project state "until the owner promotes them (R0 decision)").
Cross-reference candidates: `.claude/docs/orchestrator-rules.md`,
`.claude/docs/orchestrator-recommended-system-prompt.md`, `.claude/docs/model-policy.md`,
`docs/observability/langfuse-orchestrator.md` (caller-side orchestrator docs).

### (g) Tests that pin doc paths (trip-check for this milestone's files)

- `tests/test_constitution_ui_claims.py` — parses CLAUDE.md/README.md (see (e)). Only
  guard affected by the CLAUDE.md amendment; additive edits are safe.
- `tests/security/test_threat_model_coverage.py` — pins
  `.claude/docs/security-threat-model-coverage.md` existence + content; does NOT enumerate
  the `.claude/docs/` directory → adding `adr-data-plane-boundary.md` trips nothing.
- `tests/test_model_selector.py` — pins `.claude/docs/model-policy.md` + its "Verifier
  pass: dropped and why" section + model_selector's path (relevant only if the ADR's
  disposition tried to move files — m1 is documents-only).
- ~12 security tests pin `.claude/docs/security-*.md` paths; `tests/test_proof_chain.py`
  pins `proof-chain-workflow.md`; `tests/test_snippet_contract.py`, `tests/test_chunker.py`,
  `tests/test_textbook_chunker.py`, `tests/test_watchdog_eval.py` pin other `.claude/docs/`
  files — all untouched by m1.
- Conclusion: no doc-layout test enumerates directories; new-file + additive-amendment is
  test-safe. Run `make test` anyway (guard tests above are cheap).

### (h) Trust-language evidence anchor — VERIFIED

`server/handlers/lean_verify.py:290-298` (exact logic): `has_error = any(m["severity"] ==
"error" for m in messages)`; `has_sorry = bool(sorry_goals)`; then `status = "error"` |
`"sorry"` | `"ok"`. So `status: "ok"` ⇔ no error-severity messages AND no sorry goals —
the bare-status gap the roadmap cites, at exactly the cited lines. Adjacent nuance worth
quoting in the ADR: :300-307 forces `compilation_success = None` when `mode ==
"syntax_only"` even if status is "ok" ("Surface this as null so the agent does not
interpret a syntax-only pass as a full kernel acceptance") — the codebase already gestures
at multi-axis trust.

### Working-tree state caveat (per milestone instruction)

`git status --porcelain` (verified): ~40 pre-existing modified files NOT from this
milestone — including **CLAUDE.md and README.md themselves** — documented in
`.claude/notes/milestones/data-plane-governance-m1/preflight-deviation.md` (paper-metadata-m2
doc updates from a prior session). Six untracked plan dirs: `?? plans/{agent-platform,
evidence-engine,researcher-workbench,retrieval-unlocks,scale-ops-hardening,
trustworthy-release}/` (matches the R0 evidence exactly); `plans/data-plane-governance/roadmap.yaml`
and `plans/source-truth/roadmap.yaml` ARE tracked (R-track scaffolds, outside disposition
scope). None of the pre-existing modifications are counted in this brief's affected-files
estimate.

## Acceptance criteria the implementer must meet

1. `.claude/docs/adr-data-plane-boundary.md` exists, states all three boundary rules (no
   agent dispatch or per-run agent memory in the server; writes only via offline ingest or
   operator-gated console actions; orchestrator loop in a separate repo OR re-scoped as a
   client-side tool under `tools/` with zero server-side state), records owner approval,
   and is committed. (roadmap AC 1)
2. The ADR records a SINGLE orchestrator-loop placement choice and notes that m2's
   `t-agent-platform-amend` will align `plans/agent-platform/roadmap.yaml` to it. (AC 2)
3. The ADR names the disposition of `server/orchestrator/model_selector.py` using the
   verified consumer graph from §(a) — including the transitive runtime import via
   `spend_constants.py:51` / `observability/__init__.py:30` and the test pins that make
   relocation breaking — not the stale "referenced only by tests" claim. (AC 2)
4. The ADR states the candidate-layer principle: non-commercially-licensed external data
   stays in a candidate layer and is never redistributed (general principle only; R7 owns
   TheoremGraph/Matlas specifics per the roadmap `wont`). (AC 2)
5. CLAUDE.md states the three boundary rules as binding agent constraints, linking to the
   ADR, and the ADR records the chosen anchor (new hard-constraints section vs extended §4;
   see (e) for why §4.8 is the low-risk choice). (AC 3)
6. Zero code changes under `server/` (roadmap `wont`), and `make test` stays green — in
   particular `tests/test_constitution_ui_claims.py`, `tests/test_langfuse_doc.py`,
   `tests/test_model_selector.py`.
7. The milestone's feat commit contains ONLY m1 hunks: the pre-existing CLAUDE.md/README.md
   working-tree modifications stay uncommitted and byte-identical (hunk-level staging), per
   preflight-deviation.md mitigation 2.

## Risks and open questions

1. **CLAUDE.md is already dirty.** m1 must edit a file carrying uncommitted
   paper-metadata-m2 hunks; naive `git add CLAUDE.md` smuggles another session's work into
   the m1 commit. Mitigation: `git add -p`-style hunk staging (or `git diff` before/after
   comparison) + verify the staged diff shows only the amendment. Same hazard applies if
   README.md is touched (recommend: don't touch it).
2. **Anchor choice.** Recommend extending §4 with a new 4.8 (renumber-free, adjacent to the
   4.7 rules the ADR generalizes) over a new top-level "Hard constraints" section (would be
   the repo's third distinct "Hard constraints" block — README.md:135 and
   .claude/notes/README.md:20 already use that name for DIFFERENT lists). Owner may prefer
   the README-mirroring name; the ADR just has to record whichever is chosen.
3. **model_selector disposition must not promise relocation.** Moving it out of `server/`
   breaks `tests/test_model_selector.py` (import + F2 allow-list `orchestrator/model_selector.py`)
   and the `spend_constants` runtime import — i.e., server code changes this track forbids.
   The roadmap's should-assumption ("remain a library consumed by the external client")
   matches the verified import graph; keep-in-place-as-library is the only disposition that
   is documents-only. If the owner chooses otherwise, the ADR must defer execution to a
   future code milestone, not this one.
4. **"Under tools/" is not process isolation.** The server imports `tools/` modules at
   runtime (`server/routes/notebooks.py:64-74`), so the ADR's "zero server-side state"
   option must be phrased as dependency-direction + state rules (server never imports the
   orchestrator module; the loop holds no state the server reads under `var/`; anthropic
   stays out of `pyproject.toml` per the test_langfuse_doc.py:215-223 opt-in precedent),
   not as a directory rule alone.
5. **Write-rule precision + stale-fact hazard.** Rule 2 needs a carve-out for
   server-internal operational writes (Tier-1 cache sqlite, logs, metrics, ingest-status
   transitions) and should classify the `/ui/api/.../ingest` route as an operator-gated
   console action that runs ingest in-process. And the amendment must not copy CLAUDE.md's
   stale counts into new binding text ("7-tool surface" §6 — actually 8 incl. lean_verify;
   "make ingest is a stub" §7 — Makefile:188 is the real E11 orchestrator).
