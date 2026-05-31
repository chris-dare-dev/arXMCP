# Research Synthesis — onboarding-uplift-m4

**Merged from:** research-brief-1.md (seam map + envelope-crashes-in-stub
critical) + research-brief-2.md (m9 IngestTaskTracker conflict + MCP spec
+ 12 FMs).
**Generated:** 2026-05-31.
**Verdict:** INLINE — **scope is materially smaller than the brief
estimated**. ~5 files, ~350 LOC main + tests. Both briefs surface the
same two cardinal findings; both recommend reusing the existing m9
`IngestTaskTracker` rather than building a parallel job registry.

---

## 1. THE BIG SCOPE CORRECTION

**The brief said:** "TWO new endpoints: `POST /ui/api/notebooks/<slug>/ingest`,
`GET /ui/api/notebooks/<slug>/ingest-status`."

**Reality (both R1 and R2 confirm):** these endpoints **ALREADY EXIST**
from `notebook-surface-expansion-m9`:

- `POST /ui/api/notebooks/<slug>/ingest` — at `server/routes/notebooks.py:1634`,
  returns 202 + HTML fragment. Backed by
  `app.state.ingest_tracker.start_ingest(slug, store)` (R1 §4, R2
  §"Existing ingest infrastructure").
- `GET /ui/api/notebooks/<slug>/ingest/latest` — at
  `server/routes/notebooks.py:1713`, returns the structured status
  shape (`status, started_at, finished_at, last_error, ...`).
- `app.state.ingest_tracker = IngestTaskTracker()` already wired in
  lifespan at `server/main.py:522`.
- `IngestTaskTracker` (`server/ingest_tracker.py`) already provides:
  - `_tasks: dict[str, asyncio.Task]` (GC-safe strong refs).
  - `_global_cap: asyncio.Semaphore(1)` (resource exhaustion guard).
  - `is_running(slug)` + 409-on-duplicate via DB fallback
    (`store.has_running_ingest(slug)`).
  - `shutdown()` that cancels in-flight tasks (FM-1 SIGTERM
    mitigation).
  - Subprocess architecture: `asyncio.create_subprocess_exec
    tools/notebook_ingest.py <slug>`.

**m4's actual work is therefore much smaller:** add the bootstrap-mode
substrate (Config field + Resources.startup branch + stub-check + late-
binding) and the Make wrapper. The ingest endpoints already work.

---

## 2. The locked design

**File deltas (5 files, ~350 LOC):**

1. **`server/config.py`** — add `bootstrap_mode: bool = False` field
   following the existing `enable_lean: bool = False` pattern (R1 §1
   verbatim). No `Field(...)` wrapper; pydantic-settings auto-derives
   `ARXMCP_BOOTSTRAP_MODE` from the field name + the `env_prefix="ARXMCP_"`
   in `SettingsConfigDict`. ~15 LOC including docstring.

2. **`server/resources.py`** — `Resources.startup` gains a bootstrap
   branch immediately after the `corpus_info = read_corpus_version(...)`
   read at `server/resources.py:439-447`. Synthesis §3 D7 (FM-7
   resolution) — bootstrap mode is a HINT, not an override:
   - If `corpus_info is None` AND `config.bootstrap_mode is True`:
     skip `CorpusNotIngestedError`. Set `chunks_table = None`,
     `corpus_info = None`, `bm25_phase = None`, `cache = None`. Set new
     `bootstrap_mode_active: bool = True` field. Log INFO
     `Resources.startup: bootstrap mode active; MCP tools return
     stub-mode envelope until ingest completes`.
   - If `corpus_info is None` AND `config.bootstrap_mode is False`:
     unchanged — raise `CorpusNotIngestedError`.
   - If `corpus_info is NOT None` AND `config.bootstrap_mode is True`:
     **log INFO and IGNORE the flag** ("bootstrap_mode requested but
     corpus already ingested; booting normally"). FM-7 mitigation.
   - If `corpus_info is NOT None` AND `config.bootstrap_mode is
     False`: unchanged — normal boot. Default state. AC3 holds.
   ~80 LOC including the new fields, comments, and the late-bind
   coroutine (D2 below).

3. **`server/tools.py` — stub-check at the orchestrator level** (NOT
   per-handler). Both briefs concur this is the right pattern (R1 §3,
   R2 FM-9). Add a `_check_bootstrap_envelope(resources)` helper in
   `server/tools.py` that returns a structured envelope when
   `resources.bootstrap_mode_active is True`, else `None`. Wire it into
   the top-level dispatch — every handler gets it via the orchestrator
   without per-handler edits. **Critical (R1 §3):** the envelope MUST
   NOT call `envelope()` (which crashes on `corpus_info.version` when
   `corpus_info is None`); construct the dict literally with
   `"corpus_version": -1` per R1's §3 recommendation. The MCP 2025-06-18
   spec (R2 §"MCP 2025-06-18 spec") explicitly supports the structured
   envelope with `isError: true` for "business logic errors" — quoted
   verbatim: *"Tool Execution Errors: Reported in tool results with
   `isError: true`: ... **Business logic errors**"*. ~60 LOC.

4. **`Resources.late_bind` async method** (NEW, in
   `server/resources.py`) — called after the first successful ingest.
   Re-reads `corpus-version.json` from `config.lancedb_path`, opens
   `chunks_table` at the new version, rebuilds `BM25Phase`, opens
   `RetrievalCache`. Flips `bootstrap_mode_active = False` LAST. Per
   synthesis §3 D2 (rect note below) the original `asyncio.Event` was
   removed since no consumer awaited it. The `IngestTaskTracker`'s
   `done_callback` fires `late_bind` via
   `asyncio.create_task(resources.late_bind())` when the ingest
   subprocess exits 0. ~60 LOC.

5. **`Makefile`** — new `up-wizard` target wrapping `make up` with
   `ARXMCP_BOOTSTRAP_MODE=1` set inline (R1 §8). Add to
   `.PHONY` FIRST-TIME stanza. Update `make help`. ~20 LOC.

**Tests (new file, ~120 LOC):**

- **`tests/test_bootstrap_mode.py`** — covers AC1, AC2, AC3, AC8, AC10
  + the FM-7 hint-vs-override semantic:
  - `test_bootstrap_mode_skips_corpus_not_ingested_error` (AC1) —
    `Config(bootstrap_mode=True)` + empty `lancedb_path` → no raise.
  - `test_cold_start_without_bootstrap_still_fatals` (AC3) —
    `Config(bootstrap_mode=False)` + empty `lancedb_path` →
    `CorpusNotIngestedError`. Cardinal D1: no silent flip.
  - `test_bootstrap_mode_with_existing_corpus_ignores_flag` (FM-7) —
    `Config(bootstrap_mode=True)` + populated `lancedb_path` →
    `bootstrap_mode_active is False` (silent ignore), real chunks_table
    opened.
  - `test_mcp_handler_returns_stub_envelope_in_bootstrap_mode` (AC8) —
    stub-mode response has `{"error": "no_notebook_selected", ...}`
    + `isError: true` + `corpus_version: -1`; does NOT crash on
    `corpus_info.version`.
  - `test_late_bind_flips_event` (AC6) — manually invoke `late_bind`
    + assert `bootstrap_mode_active is False`.
  - `test_make_up_wizard_target_exists_and_sets_env_var` (AC2) — Make
    dry-run grep.
  - `test_bp1_bp2_hashes_unchanged` (AC10) — runs the existing
    `tests/test_server_tool_schema.py` + `tests/test_prompts.py` paths
    to verify no MCP surface drift.

---

## 3. Divergences resolved (orchestrator synthesis note)

### D1 — `/readyz` returns 200 or 503 in bootstrap mode?

Both briefs concur — return **200 with `"status": "bootstrap"` in the
JSON body**. R1 §"Open questions (a)" + R2 §"Recommendation". A 503
would cause the shim (`shim/arxmcp_shim.py`) to give up before the
operator can ingest, defeating the milestone goal. The structured body
lets the shim distinguish bootstrap from normal-ready without a 503
liveness failure.

### D2 — Late-binding flip: `asyncio.Event` vs `asyncio.Lock` + bool

Both briefs concur — **`asyncio.Event`, one-way set**. R2 FM-2 +
R1 §"Open questions (b)". Reasoning:
1. The event loop is single-threaded; cooperative multitasking is the
   serialization.
2. `Event.set()` is a one-time atomic operation; no lock contention
   on the hot path.
3. Handlers check `not event.is_set()` cheaply (single attribute read).
4. The alternative (`Lock` + flag) requires acquiring the lock on
   every handler invocation — measurable overhead on the MCP query
   path.

**Implementation deferral (onboarding-uplift-m4 F6 rect):** the
`_corpus_ready_event` field was added but found to have no consumer —
the orchestrator stub-check reads the `bootstrap_mode_active` bool flag
directly; no handler awaits the event. The event was removed in the
Phase-4 rectification commit. If a future surface (e.g. a
`/ui/api/bootstrap-status` poll endpoint) wants event semantics,
re-add it then alongside its first consumer.

### D3 — D5 (BGE-M3 download progress) — full bytes tracking vs sentinel?

R1 §6 + §"Recommendation" identifies an **architectural barrier**: the
existing `IngestTaskTracker` runs ingest as a **subprocess**. The BGE-M3
download happens INSIDE the subprocess; a `huggingface_hub.utils.tqdm`
monkeypatch in the SERVER process cannot intercept SUBPROCESS callbacks
without an IPC channel (pipe or shared file). R2 §"huggingface_hub
download progress" verifies the technical pin (`transformers>=4.40`)
but does not address the cross-process boundary.

**RESOLVED → simplified D5 for m4. Full byte tracking is OUT OF SCOPE.**

Reasoning:
1. The full tqdm shim requires either (a) modifying
   `tools/notebook_ingest.py` to write progress to a pipe/file the
   server reads, OR (b) loading BGE-M3 in the server process before
   spawn. Both are 2-3-day projects on their own, expanding m4 well
   beyond its scope.
2. The decisions doc D5 says "real bytes-progress" but the proposal
   §9 m4 ESTIMATE was "2-3 days" — adopting cross-process IPC for
   tqdm puts m4 over budget.
3. **The simpler approach satisfies operator UX**: detect whether
   `~/.cache/huggingface/hub/models--BAAI--bge-m3/` exists BEFORE
   spawning the subprocess. If absent, set
   `phase = "downloading_model"` in the existing `notebook_ingest_runs`
   row with `bytes_total = -1` (unknown sentinel). If present, skip
   the `downloading_model` phase entirely. ~10 LOC delta.
4. Full byte progress is **deferred to m5** (the wizard milestone)
   where it can be addressed alongside the wizard's progress-bar UI
   needs — the wizard might prefer a different progress model anyway.

**Implementation:** in the `start_ingest` path (or a new pre-spawn
hook), check the HF cache; pass a `phase_hint=downloading_model` arg
to the subprocess if absent. The subprocess prints
`phase: downloading_model` to stdout when it loads the model; the
existing `IngestTaskTracker` already parses subprocess output.

**Further deferral (onboarding-uplift-m4 F9 rect):** even the 10-LOC
`phase=downloading_model` pre-spawn HF cache check was deferred from
the m4 implementation. The implementer noted that it requires editing
`tools/notebook_ingest.py` in ways that expand the touch-surface beyond
the m4 brief, and the operator UX hit is minimal — the ingest-status
endpoint already shows accurate per-paper progress phases once the
subprocess starts. The phase-sentinel work is explicitly deferred to m5
where it fits naturally alongside the wizard's progress-bar UI.

### D4 — `ARXMCP_NOTEBOOK + ARXMCP_BOOTSTRAP_MODE` conflict

R1 §"Open questions (d)" flags this: `Config.derive_notebook_lancedb_path`
at `server/config.py:510-515` checks for `corpus-version.json`
REGARDLESS of `bootstrap_mode`, fatalling at config-parse time before
`Resources.startup` runs. Setting both env vars together breaks the boot.

**RESOLVED → document as unsupported for m4; defer the per-notebook
bootstrap path to m5+.**

Reasoning:
1. The per-notebook bootstrap UX (ingest a notebook + boot scoped to it
   in one shell session) is a wizard-flavored UX better solved alongside
   the wizard.
2. The fix (add `bootstrap_mode` check to `derive_notebook_lancedb_path`)
   needs `self.bootstrap_mode` access at validator time which is doable
   but adds complexity not justified by m4 scope.
3. m4 ships the shared-corpus bootstrap path (operator opens UI,
   creates a notebook, ingests, queries via shared corpus). The
   advanced `ARXMCP_NOTEBOOK=<slug>` + bootstrap mode combination
   stays unsupported with a clear error message at config-parse time.

**Implementation:** no code change. Add a docstring note + a test
asserting the combination errors out with the existing validator's
error message (informational regression guard).

### D5 — Stub-check: per-handler vs orchestrator-level?

Both briefs concur — **orchestrator-level** (R1 §3, R2 FM-9). Per-handler
checks miss future additions (a new handler without the check would
5xx in bootstrap mode). The orchestrator-level dispatch is the
centralized entry point that catches every tool call.

**Implementation:** the stub-check goes into the `tools/call` dispatch
in `server/tools.py`. Wire it into the handler-orchestrator's pre-call
hook. Returns the stub envelope when `resources.bootstrap_mode_active
is True`; otherwise proceeds to per-handler dispatch.

---

## 4. Failure modes → required handling (R2's 12-mode enumeration, condensed)

- **FM-1 (SIGTERM during mid-flight ingest):** SOLVED by existing
  `IngestTaskTracker.shutdown()`. The orchestrator's `try/finally`
  + `asyncio.CancelledError` catch are already in place.
- **FM-2 (late-binding race):** SOLVED by `asyncio.Event` (D2).
  Handlers check `not event.is_set()` atomically; `event.set()` is
  the one-time flip.
- **FM-3 (half-failed first ingest):** SOLVED by existing m3 pattern
  — `corpus-version.json` is written LAST atomically. No marker = stub
  reader stays active. LanceDB MVCC means partial rows from a cancelled
  write are unreachable.
- **FM-4 (BGE-M3 download interrupted):** mitigated by HF Hub's
  partial-blob resume. Out of scope for m4 (D3 simplified).
- **FM-5 (concurrent POST /ingest same slug):** SOLVED by existing
  `IngestTaskTracker.is_running(slug)` 409.
- **FM-6 (concurrent POST /ingest different slugs):** the existing
  `_global_cap = asyncio.Semaphore(1)` blocks the second. For m4
  bootstrap-mode operator, this is acceptable.
- **FM-7 (bootstrap_mode + existing corpus):** SOLVED by §3 (D7
  resolution above) — silent INFO + ignore the flag.
- **FM-8 (server restart with `ARXMCP_BOOTSTRAP_MODE=1` after ingest):**
  resolved by FM-7. Benign.
- **FM-9 (handler bypasses stub-check):** SOLVED by orchestrator-level
  check (D5).
- **FM-10 (aggressive polling races with progress write):** NOT A RISK
  — single-threaded asyncio, plain attribute assignment is atomic
  within the loop. No lock needed.
- **FM-11 (last_error PII):** apply the existing m9
  `prepare_stderr_tail()` pipeline + path-redaction precedent. The
  ingest-status response inherits this.
- **FM-12 (HF_HUB_OFFLINE=1):** D3 simplification sidesteps this —
  no tqdm monkeypatch, no offline-mode crash risk.

---

## 5. Acceptance criteria — restated with implementation handles

- **AC1** `ARXMCP_BOOTSTRAP_MODE=1 make up` boots cleanly with no
  marker. Test:
  `test_bootstrap_mode_skips_corpus_not_ingested_error`.
- **AC2** `make up-wizard` exists + sets the env var. Test:
  `test_make_up_wizard_target_exists_and_sets_env_var`.
- **AC3** Default behavior UNCHANGED — cold-start + no marker still
  fatals. Test: `test_cold_start_without_bootstrap_still_fatals`.
- **AC4** Existing m9 `POST /ui/api/notebooks/<slug>/ingest` endpoint
  works in bootstrap mode (no new endpoint needed). Verified by the
  existing m9 tests + the new bootstrap-mode test that ingests + late-
  binds.
- **AC5** Existing m9 `GET /ui/api/notebooks/<slug>/ingest/latest`
  endpoint returns the structured shape. Already passing in m9 tests.
- **AC6** Late-binding flips after first ingest. Test:
  `test_late_bind_flips_event`.
- **AC7** **DEFERRED to m5** (full BGE-M3 byte tracking). m4 ships the
  cached-vs-not-cached detection + the `downloading_model` phase
  sentinel. The detail will be added to the implementation summary.
- **AC8** Stub envelope returned by MCP handlers in bootstrap mode +
  no crash on `corpus_info.version`. Test:
  `test_mcp_handler_returns_stub_envelope_in_bootstrap_mode`.
- **AC9** `make test` green + `ruff check .` clean.
- **AC10** BP1/BP2 hashes UNCHANGED. Test:
  `test_bp1_bp2_hashes_unchanged`.
- **AC11** Regression tests added (the 7 above).

---

## 6. Implementation order

1. **`server/config.py`** — `bootstrap_mode: bool = False` field. ~15 LOC.
2. **`server/resources.py`** — bootstrap branch in `startup` + new
   `bootstrap_mode_active` field + `late_bind` coroutine. ~140 LOC.
3. **`server/tools.py`** — `_check_bootstrap_envelope` helper +
   wire into the orchestrator dispatch path. ~60 LOC.
4. **`server/main.py` / `server/routes/notebooks.py`** — wire
   `done_callback` to fire `resources.late_bind()` when ingest exits 0.
   May only need a small edit to an existing callback. ~30 LOC.
5. **`Makefile`** — `up-wizard` target + help. ~20 LOC.
6. **`tests/test_bootstrap_mode.py`** — 7 tests covering ACs. ~200 LOC.

---

## 7. Open questions

**None blocking.** All resolved in §3 D1-D5 + §1 scope correction.
The deferred AC7 (full BGE-M3 bytes) is a documented synthesis decision,
not an unresolved question.

## 8. External writes required

**None.** Purely local. Both briefs concur.
