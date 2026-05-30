# Challenge — capability-scout 2026q2-notebook-ux-storage-ops

**Challenger generated:** 2026-05-28
**Synthesis path:** `.claude/notes/capability-scouts/2026q2-notebook-ux-storage-ops/artifacts/synthesis.md`
**Candidates evaluated:** CAND-1 through CAND-18 (18 total)

---

## 1. Executive Summary

One candidate is already-shipped (CAND-7 — HEALTHCHECK present at `docker/Dockerfile.server:133`) and should be killed before Phase 4. Two candidates carry MAJOR unsurfaced costs: CAND-1 (docker-compose effort under-estimated and the `reject_non_loopback` reconciliation is already solved, changing the sizing argument) and CAND-11 (SYSTEM_PROMPT authoring is a broader agent-harness policy decision that scopes creep beyond this infra scout's theme and forces BP1 re-pin with cross-team implications). The dominant cross-cutting concern is MCP tool-surface cost: 3 candidates (CAND-12, CAND-17, and the action-tools subset of CAND-10) each independently force an `EXPECTED_TOOL_SCHEMA_SHA256` re-pin, and the synthesis's own recommendation to batch them is not formalized as a dependency in the DAG. The second dominant concern is value-density: CAND-4 (Litestream) and CAND-8 (SSE) both carry net-new OSS dependencies for marginal benefit on a single-operator workstation, given cheaper alternatives are already in-flight.

---

## 2. BLOCKER Findings

### CAND-7 — Add `HEALTHCHECK` to `Dockerfile.server`

**Severity: BLOCKER**

**Objections:**
- **Axis 1 (architecture-lock compatibility) / Axis 8 (effort honesty):** The synthesis flags a contradiction but does not resolve it. Ground-checking `docker/Dockerfile.server` directly confirms: the HEALTHCHECK is already present at line 133 (`HEALTHCHECK --interval=30s --timeout=5s --start-period=5m --retries=3 CMD curl -fsS http://127.0.0.1:7733/readyz || exit 1`). This candidate describes something that is already shipped. `curl` is also already installed in the runtime stage at `docker/Dockerfile.server:84`.
- **Axis 8 (effort honesty):** Shipping as-is burns a milestone slot on a null change.

**Kill recommendation:** Drop CAND-7. The HEALTHCHECK is shipped. Fold the verification note into CAND-1 (docker-compose) as a prerequisite confirmation: the compose's `service_healthy` chain can reference the in-image HEALTHCHECK without modification.

---

## 3. MAJOR Findings

### CAND-1 — Ship the base `docker-compose.yml`

**Severity: MAJOR**

**Objections:**

- **Axis 8 (effort honesty):** The synthesis sizes this M. The sizing argument is partially invalidated by an already-shipped carve-out: `server/config.py:348` ships `unsafe_network_bind: bool = False` with an explicit escape hatch documented as "for container deployments." The validator at line 513 already permits `ARXMCP_BIND_HOST=0.0.0.0` when `ARXMCP_UNSAFE_NETWORK_BIND=1`. The adversary brief's `ARXMCP_IN_CONTAINER` carve-out sketch is therefore unnecessary — the mechanism exists today. This removes one of the effort-inflating sub-tasks. However, the sizing still hides two legitimately large sub-tasks the synthesis only alludes to: (a) the BGE-M3 model weights (~2.3 GB) need a host-cache volume mount strategy (baking them into the image is a non-starter; volume mounting requires operator pre-warming documentation); (b) the ingest service needs either its own Dockerfile (CAND-7b / adversary L3) or an entrypoint override on the server image. The synthesis defers (b) as an "open question" but shipping a compose stack with a placeholder `arxmcp-ingest` service that has no image is incomplete.
- **Axis 10 (sequencing dependencies):** The synthesis correctly notes CAND-7b (Dockerfile.ingest) as an open question gated on CAND-1. But the reverse is also true: CAND-1's `--profile ingest` service is hollow without CAND-7b. The DAG should record CAND-7b as a hard prerequisite of the full CAND-1 (or CAND-1 should scope out the ingest service entirely for v0 and ship server-only compose first).
- **Axis 5 (local-first):** The named-volume vs bind-mount resolution favors bind-mount (`$PWD/var/arxmcp`) for restic compatibility. This is the right call for local-first. However, the bind-mount approach creates a **uid/gid ownership mismatch**: `docker/Dockerfile.server:92` creates UID 1000 (`arxmcp`) and chowns `/app/var` to it. If the host-side `var/arxmcp/` is root-owned or owner-uid-differs (common on macOS where Docker Desktop runs a VM), the container will either fail to write or silently run as a different effective uid. The synthesis does not surface this friction point. Operators on macOS will hit it on first run.

**Suggested scope adjustment:**
- v0: server-only compose (no ingest service); bind-mount `var/arxmcp/`; document the uid/gid chown pre-step (`chown -R 1000:1000 var/arxmcp`); `ARXMCP_UNSAFE_NETWORK_BIND=1` in the compose env. Size: S.
- v1: add ingest service after CAND-7b (Dockerfile.ingest) lands. Size: S incremental.
- Drop the M sizing for the bundle; S+S is more accurate.

---

### CAND-11 — Author the `SYSTEM_PROMPT` placeholder + set MCP `initialize` `instructions` field

**Severity: MAJOR**

**Objections:**

- **Axis 8 (effort honesty) / value density:** The synthesis correctly identifies that authoring `SYSTEM_PROMPT` forces a BP1 re-pin (`tests/test_prompts.py::EXPECTED_BP1_SHA256`). What it does not surface is that the content decision is an agent-harness policy call — it determines what every agent role sees as the global context for math retrieval. Authoring it wrong (e.g., injecting dynamic notebook state into `SYSTEM_PROMPT`) breaks BP1 cross-session cache sharing. The synthesis sketch says "keep `instructions` static/version-pinned" correctly, but the SYSTEM_PROMPT body itself (not just `instructions`) requires a deliberate content authoring decision that is architecturally upstream of this infra scout's scope. This is not a 1-day task for an infra milestone — it requires coordination with the sketcher/autoformalizer pipeline design.
- **Axis 3 (prompt-cache discipline):** The BP1 re-pin consequence is real: `tests/test_prompts.py:649` pins `EXPECTED_BP1_SHA256`. Changing `SYSTEM_PROMPT` at `server/prompts.py:113` drifts BP1. The synthesis acknowledges this but describes it as "coordinated, one-time" — understating the cache-busting impact for a production agent pipeline. The current placeholder has been stable for multiple epics; changing it mid-scout-cycle is a larger ops event than shipping a compose file.
- **Axis 9 (value density):** The `instructions` field in `initialize` has high value (Claude Code Tool Search uses it). But the synthesis conflates two distinct deliverables: (a) populating `initialize.instructions` with a static server description (cheap, safe, correct), and (b) authoring the full `SYSTEM_PROMPT` constant (expensive, policy decision, BP1-breaking). Only (a) belongs in this scout's deliverable. (b) is its own track.
- **Axis 6 (doc-placement):** The synthesis sketch is sound for (a), but any SYSTEM_PROMPT authoring decisions should be documented in `.claude/docs/model-policy.md`, not in an infra-scout artifact.

**Suggested scope adjustment:**
- v0: populate `initialize.instructions` with a static one-paragraph server description (no dynamic state, no notebook enumeration). This requires zero BP1 change (the `instructions` field is in the `initialize` response, not in `tools/list` or the system prompt). Zero `EXPECTED_BP1_SHA256` re-pin needed. Size: XS.
- Defer: SYSTEM_PROMPT authoring to a dedicated E08_S04 milestone that involves the agent-harness team. Re-pin BP1 once, deliberately, with a vetted content decision.

---

## 4. MINOR Findings

### CAND-4 — Litestream sidecar

**Severity: MINOR**

**Objections:**

- **Axis 9 (value density):** CAND-2 (restic, XS) + CAND-3 (synchronous=FULL, XS) together close the "commit survives power-loss" and "notebooks are backed up" failure modes. Litestream adds sub-second-lag WAL replication to a LOCAL second path — on a single workstation where the second path is the same physical disk (or a USB-attached NAS at best), the incremental durability benefit over CAND-2+CAND-3 is marginal. The failure mode Litestream specifically closes — "committed transaction is in WAL, not yet checkpointed, power loss, WAL also lost" — is closed by CAND-3's `synchronous=FULL` + `fullfsync=ON`, which forces each commit to a durable write before returning. The only remaining gap is point-in-time recovery BETWEEN restic nightly snapshots, which is a meaningful durability improvement only if the operator does multi-hour notebook sessions that they'd be unwilling to replay. For a low-write metadata store that accumulates maybe 10–50 writes per session, this is hard to justify.
- **Axis 10 (sequencing):** The synthesis correctly gates CAND-4 on CAND-1 (requires compose to run as a sidecar). If CAND-1 ships server-only (recommended v0 cut above), CAND-4 is further deferred.
- **Axis 2 (no-fork policy):** Litestream runs as its own Docker image (not vendored code). This passes the no-fork check — it is a runtime container, not an imported library. No objection on this axis.

**Suggested scope adjustment:** Defer to a v2 of the storage-durability cluster, AFTER CAND-2+CAND-3 have been in production for one milestone cycle and any remaining durability gap is empirically motivated. The synthesis's own "challenger: weigh value-density" flag is correct — this candidate is a MINOR scope reduction, not a kill.

---

### CAND-8 — SSE-based ingest progress

**Severity: MINOR**

**Objections:**

- **Axis 9 (value density):** arXMCP already ships htmx polling with the HTTP-286 stop-signal (adversary "done well") and this is confirmed functional. SSE with `sse-starlette` adds net-new dependency, CSP surface changes, and a second event-delivery mechanism to maintain alongside polling. For a SINGLE operator, the UX delta between "2s polling with auto-stop" and "server-push SSE" is cosmetic. The synthesis itself surfaces this tension explicitly and defers to the challenger — the right call is MINOR/scope-reduce, not kill.
- **Axis 4 (MCP tool-surface contract):** The MCP `logging:{}` capability extension (optional second half of CAND-8) carries zero tool-schema cost, but the synthesis sketch bundles it with the UI SSE work. These should be split: the MCP notification path is independent of `sse-starlette` and has no CSP surface.
- **Axis 2 (no-fork policy):** `sse-starlette` is a pip library (BSD-3), not a forked repo. Allowed as a dependency. No objection on this axis.

**Suggested scope adjustment:**
- v0: ship MCP `logging:{}` capability + `notifications/message` from ingest subprocess only (no `sse-starlette`, no UI change, zero CSP risk). This is the agent-facing half of CAND-8 at ~0.5-day effort.
- v1: add `sse-starlette` + UI SSE extension only if polling UX proves insufficient in practice (empirically motivated, not speculative).

---

### CAND-12 — Notebook-management MCP tools (`list_notebooks`, `get_notebook_status`, corpus stats)

**Severity: MINOR**

**Objections:**

- **Axis 4 (MCP tool-surface contract):** Any tool added to `server/tools.py::ALL_TOOLS` forces `EXPECTED_TOOL_SCHEMA_SHA256` re-pin (`tests/test_server_tool_schema.py:94-96`). The synthesis correctly identifies this cost and recommends preferring CAND-10 (resources) for read-only enumeration. The MINOR objection is that the synthesis does not fully kill CAND-12 — it scopes it to "action-only" tools — but the action-tool use case (e.g., `trigger_ingest`) is not actually demonstrated as needed by any existing pipeline agent. The synthesis identifies a hypothetical agent need without evidence that the sketcher/autoformalizer currently calls back to trigger corpus changes.
- **Axis 3 (prompt-cache discipline):** Adding 1–3 read-only tools to `ALL_TOOLS` drifts BP1 (the `EXPECTED_TOOL_SCHEMA_SHA256` hash IS part of what BP1 keys on at `tests/test_server_tool_schema.py` per the module docstring). The synthesis notes batching as the mitigation but does not call out that CAND-12 should be batched with CAND-17 (which also requires a re-pin) into a SINGLE schema bump. Shipping them separately generates two consecutive cache-busting events.
- **Axis 10 (sequencing):** CAND-12 read-only tools are largely redundant with CAND-10 (resources). The synthesis resolves this correctly but Phase 4 should formalize the dependency: CAND-12 only if CAND-10 is judged insufficient for the agent use-case, AND batched with CAND-17.

**Suggested scope adjustment:** Kill the read-only subset (list, status, stats) — CAND-10 covers them at zero BP1 cost. Keep the action subset (trigger_ingest) in the backlog but only instantiate if a concrete agent use-case is demonstrated. If retained, batch with CAND-17 into one schema bump.

---

### CAND-13 — Refresh the stale design constitution

**Severity: MINOR**

**Objections:**

- **Axis 9 (value density) / security gap:** The synthesis correctly flags that the E13 security audit scope said "no frontend exists" and therefore the Jinja2/htmx stack was never audited for XSS, CSP gaps, template injection, or htmx-specific injection patterns. This is NOT a doc-refresh problem — it is an unaudited security surface. The synthesis sketch says "flag in the E13 milestone state that the UI surface was never security-audited" which under-scopes the finding. A doc note that says "someone should look at this" is not the same as looking at it. The correct v1 is: (a) doc refresh (what the synthesis describes), AND (b) file a GitHub issue at `chris-dare-dev/arXMCP` (alongside the existing #1–#6) for a dedicated UI security audit milestone, analogous to E13 for the MCP surface.
- **Axis 6 (doc placement):** The synthesis correctly identifies `.claude/notes/06-mcp-server-design.md`, CLAUDE.md §5, and `docs/install.md` as the targets. Doc placement is correct — no objection.
- **Axis 8 (effort honesty):** Sized XS. Correct for the doc-only portion. The follow-up security audit issue is a separate-track item.

**Suggested scope adjustment:** Ship the doc refresh as scoped (XS). Add one concrete output: a filed GitHub issue at `chris-dare-dev/arXMCP` for "UI security audit (Jinja2/htmx/CSP)" — this converts the "flag" from a doc comment to a tracked work item that will not be forgotten.

---

### CAND-17 — Adopt the Claude Code operability contract

**Severity: MINOR**

**Objections:**

- **Axis 3 (prompt-cache discipline):** The synthesis is correct that adding `_meta["anthropic/maxResultSizeChars"]` to tool definitions in `ALL_TOOLS` drifts `EXPECTED_TOOL_SCHEMA_SHA256` (confirmed by `tests/test_server_tool_schema.py:41-46` — the hash includes `by_alias=True` which serializes `meta` → `_meta` wire form). The synthesis correctly states BP1 is NOT affected (BP1 at `tests/test_prompts.py:649` hashes `{name, description}` per tool, not `_meta`). The MINOR finding is that the synthesis does not formalize that CAND-17's schema bump MUST be batched with any other tool additions (especially CAND-12 if retained) into a single re-pin event.
- **Axis 4 (MCP tool-surface contract):** `tools:{listChanged:true}` at `initialize` is zero-cost (separate request, no hash drift). `_meta` additions are a schema bump. The synthesis correctly separates these. No objection beyond the batching point.
- **Axis 8 (effort honesty):** Sized S. Correct. The main cost is verifying all large-result tools and writing the test update.

**Suggested scope adjustment:** Ship `listChanged` + `alwaysLoad` doc first (XS, zero re-pin). Batch `_meta` additions with any other tool changes to minimize re-pin events. The two sub-tasks should be sequenced: (a) now vs (b) when the next tool change happens.

---

### CAND-15 — Build a per-notebook BM25 index for textbook-kind notebooks

**Severity: MINOR**

**Objections:**

- **Axis 7 (retrieval-quality regression):** The synthesis correctly identifies this as a 3-LOC add. The MINOR concern is the synthesis's own statement: "only valuable alongside enabling hybrid retrieval for notebooks." Adding a BM25 pickle file to the textbook notebook path (`tools/notebook_textbook_ingest.py`) before the notebook retrieval path (`server/retrieval/bm25.py`) actually uses it for textbooks creates dead code. Dead code that is tested will bloat the test suite; dead code that is not tested is a silent maintenance burden. The synthesis flags the sequencing dependency but does not make it a hard gate.
- **Axis 10 (sequencing):** Hybrid notebook retrieval is not on the current roadmap per CLAUDE.md §3 (status snapshot). CAND-15 should be gated on a concrete roadmap entry for hybrid notebook retrieval, not shipped speculatively.

**Suggested scope adjustment:** Defer until hybrid notebook retrieval is explicitly roadmapped. If shipped, add a test asserting the BM25 index file is present after textbook ingest (so the dead-code risk is covered by the test suite).

---

## 5. Clean Candidates

The following candidates survive the 10-axis gauntlet without objection:

- **CAND-2** — Extend restic backup to cover notebook data + `notebooks.db`. XS, zero architecture conflict, closes a real data-loss gap.
- **CAND-3** — Harden `notebooks.db` SQLite durability (`synchronous=FULL` + `fullfsync`). 5-LOC fix; no architecture or cache interaction.
- **CAND-5** — Add `/status` JSON endpoint (IETF `application/health+json`). Pure-ASGI, no tool-surface change, no BP1 interaction.
- **CAND-6** — Operator status surface: `make status` + htmx badge. Correctly gated on CAND-5; XS–S, no architecture conflict.
- **CAND-9** — Per-notebook export/import (tar + `manifest.json`). Pure-ASGI `StreamingResponse`; no tool change; no BP1 interaction; no new OSS dep.
- **CAND-10** — Expose notebooks as MCP resources (`resources/list` + `resources/subscribe`). Zero BP1 cost (separate capability; `tools/list` bytes unchanged). Zero `EXPECTED_TOOL_SCHEMA_SHA256` drift. Correctly preferred over CAND-12.
- **CAND-14** — Notebook UI completion (ingest-status column, freshness indicator, htmx CRUD). Additive SQLite migration pattern; pure-ASGI; no MCP surface change.
- **CAND-16** — LanceDB on-disk format version-pin discipline. 3-LOC + pyproject.toml comment; prevents silent corruption on upgrade; no architecture or cache conflict.
- **CAND-18** — Formalize restic retention policy + `check --read-data-subset` quarterly drill. 20-LOC shell; no architecture conflict; hardens already-shipped mechanism.

---

## 6. Cross-Cutting Concerns

### CC-1: Three candidates independently force `EXPECTED_TOOL_SCHEMA_SHA256` re-pin

CAND-12 (new tools), CAND-17 (`_meta` additions), and any action-tool subset of CAND-10 each require a `tests/test_server_tool_schema.py` re-pin. The synthesis recommends batching but does not formalize this as a scheduling constraint. Phase 4 should assign a single "MCP tool-surface bump" milestone slot that executes CAND-17 + any retained CAND-12 action tools in one commit, running `pytest --update-tool-schema-hash` exactly once. Two consecutive re-pins in the same release cycle generate two session-wide cache-busting events for all connected agents.

### CC-2: CAND-7 is already shipped — the synthesis's "VERIFY" flag was correct; verification was not done

The synthesis flagged CAND-7 as needing verification (`[VERIFY — may already exist]`). Ground-checking `docker/Dockerfile.server:133` confirms the HEALTHCHECK is present. This is a scout synthesis process failure: the verification step should have been executed before the candidate was forwarded to the challenger. Future synthesis runs should resolve [VERIFY] flags inline rather than deferring them.

### CC-3: Six candidates gate on CAND-1 (docker-compose)

CAND-4 (Litestream sidecar), CAND-5 (status endpoint for Gatus), CAND-6 (status badge, indirectly), and the "Gatus" integration path all assume compose is shipped. Phase 4 should mark CAND-1 as the structural unblocker and sequence accordingly. The recommended v0 (server-only, S) unblocks CAND-5/6 immediately; CAND-4 waits for v1 (with ingest service).

### CC-4: CAND-13's security gap is understated across the catalog

Three candidates (CAND-13, CAND-14, CAND-8) all touch the Jinja2/htmx UI surface without noting that this surface has never been security-audited. Any UI-touching candidate should carry the caveat: "this change adds to an un-audited UI surface; the CAND-13 follow-up security audit should review this change's additions." The catalog should not imply the UI surface is safe by omission.

### CC-5: BP1 precision — `_meta` drifts `EXPECTED_TOOL_SCHEMA_SHA256` but NOT `EXPECTED_BP1_SHA256`

The synthesis gets this right for CAND-17 but the distinction needs to be explicit in the Phase 4 scheduling notes. `EXPECTED_BP1_SHA256` at `tests/test_prompts.py:649` hashes `{name, description}` per tool (the `server/tools.py` ALL_TOOLS name+description projection at line 855). `EXPECTED_TOOL_SCHEMA_SHA256` at `tests/test_server_tool_schema.py:94` hashes the full `tools/list` wire response including `_meta`. A `_meta` change is a **tool-schema re-pin only, not a BP1 re-pin**. New tool name/description (CAND-12) is **both** a tool-schema re-pin AND a BP1 re-pin. This distinction determines the urgency of coordination with connected agent pipelines.

---

## 7. Recommended Kill List

1. **CAND-7** — Already shipped (`docker/Dockerfile.server:133`). Kill unconditionally. Fold into CAND-1 as a pre-verified prerequisite note.

2. **CAND-12 read-only subset** (`list_notebooks`, `get_notebook_status`, corpus stats) — Redundant with CAND-10 (MCP resources) at zero BP1 cost. The synthesis's own resolution is correct. Kill the read-only tools; retain the `trigger_ingest` action tool in the backlog only when a concrete agent use-case is demonstrated.

3. **CAND-4** — Recommended strong-defer (not hard kill): correct that it is over-investment for a single workstation given CAND-2+CAND-3 close the primary failure modes. If restic + `synchronous=FULL` prove insufficient after a milestone cycle, revisit. Do not schedule in the same release as CAND-1.
