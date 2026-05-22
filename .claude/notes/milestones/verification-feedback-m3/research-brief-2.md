# Research Brief — verification-feedback-m3

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-22T22:55:00Z
**Focus:** EXTERNAL sources + FAILURE-MODE analysis (researcher-2)

---

## In-codebase context

Cross-checked against the design constitution + m2 artifacts. Load-bearing
constraints:

- `.claude/docs/lean-sandbox-design.md` row "Memory cap" (D4) — verbatim:
  > **m3+:** the 30 s per-query timeout is the primary safeguard in m2/m3;
  > the memory cap mirrors E13_S03, which itself defers Docker-level
  > enforcement of the LaTeXML cap. A follow-up milestone adds `RLIMIT_AS`
  > on POSIX.
  m3 is now that follow-up.
- `.claude/notes/spikes/verification-feedback-spike-2.md` "Findings the m2
  implementation MUST honour" #3 — verbatim:
  > **Protocol.** Commands: a JSON object then a blank line. Responses: a
  > JSON object terminated by a blank line.
- Same spike, finding #1 (Windows): `asyncio.create_subprocess_exec` does
  not PATH-search; absolute `lake.exe` required. **The arXMCP target
  workstation is Windows** (the user's CLAUDE.md §1 path and spike-2
  "Environment note" — primary env macOS, secondary checkout Windows; this
  worktree is `C:\Users\cedar\...` so the implementer is on Windows).
- `.claude/notes/08-security-observability-ops.md` Threat 3 (LaTeXML on
  hostile source) — the explicit mitigation template for an
  externally-influenced subprocess: hard timeout, dedicated UID, write
  whitelist, no network, sandbox profile. The m3 brief asks for `RLIMIT_AS`;
  Threat-3 demands the same template applied to Lean.
- `.claude/notes/07-multi-agent-caching.md` Property 1: `tools/list` is
  byte-stable; an 8th tool changes the hash. The brief AC names
  `EXPECTED_TOOL_SCHEMA_SHA256` re-pin — that is the BP1-cache flush event
  the implementer **must** perform via `pytest --update-tool-schema-hash`
  AFTER `ALL_TOOLS` is updated AND `TOOL_SCHEMA_VERSION` bumped to v12.
- `server/tools.py:111` — `TOOL_SCHEMA_VERSION = 11`. v12 is m3's bump.
- `server/lean_repl.py:131-144` — current spawn passes no `preexec_fn`. The
  m3 work must thread one in conditionally (POSIX only, see §1.3).
- `server/resources.py` step 6e (lines ~656-685) — Lean spawn already moved
  AFTER the `Resources` constructor (m2 F1 rect). m3 must not regress this
  ordering.
- `tests/test_lean_repl.py` already ships `@_lean_skip` (env-var-gated, both
  `ARXMCP_LAKE_PATH` + `ARXMCP_LEAN_REPL_DIR` required) and a `_FakeProc`
  harness for always-run round-trip tests. The high-allocation test the
  brief asks for is `requires_lean_repl`-gated by design.

**Conflict watch — none.** The brief's "no `snippet` field" line is
**consistent with** `.claude/docs/snippet-contract.md`: the 150-char snippet
contract applies to "the `search_papers` tool's result-row" only.
`lean_verify` is not a retrieval tool and never emits paper-derived text, so
the `<retrieved_chunk>` wrap (Threat 2) also does not apply to its output.

---

## Prior decisions and lessons

- Git log shows m2 shipped at c9df7f1; m2 rect 3a1a0ad closed F1 (resource
  leak) and F2-F5; F4 (RLIMIT_AS) was carried forward into the m3 brief by
  design (`critique-merged.md` §Rectification status, F4).
- M1 (cite_neighbors wiring) bumped `TOOL_SCHEMA_VERSION` 9→11; m3's bump
  to **v12** is the next deliberate version.
- The `search_papers_result.json` schema file (`server/schemas/`) is the
  template for the frozen result-row schema the m3 brief requires; place
  `server/schemas/lean_verify_result.json` next to it, set `version: 12`
  to track `TOOL_SCHEMA_VERSION`, and pin via `tests/test_snippet_contract.py`
  cross-check pattern.
- The `cite_neighbors` handler in `server/handlers/citations.py` is the
  current template for: Pydantic `Annotated[Literal[...], Field(...)]`
  argument typing → FastMCP derives the inputSchema; `envelope()` +
  `cap_result_list()` for byte-cap; deferred no-cache pattern (lean_verify
  is also NOT cacheable — different snippets = different results, BP1 not
  affected).

---

## External sources

### MCP 2025-06-18 spec — tools (verbatim MUST/SHOULD clauses)

From https://modelcontextprotocol.io/specification/2025-06-18/server/tools:

- Servers that support tools **MUST** declare the `tools` capability
  (already done).
- `tools/list` response per-tool has `name`, optional `title`,
  `description`, `inputSchema` (JSON Schema), optional `outputSchema`,
  optional `annotations`.
- Tool result: `content` array (text / image / audio / resource_link /
  embedded resource) AND optional `structuredContent` JSON object.
- **"For backwards compatibility, a tool that returns structured content
  SHOULD also return the serialized JSON in a TextContent block."**
  FastMCP's `add_tool` does this automatically when the wrapped handler
  returns a `dict`.
- **"Servers MUST provide structured results that conform to this schema"
  (when an outputSchema is provided).** Implication: if m3 declares
  `outputSchema` on the tool meta, every code path must conform — easier
  to leave it off and keep the JSON-schema file as an internal contract
  pinned by tests (matches `search_papers_result.json`).
- Security: "Servers MUST: Validate all tool inputs, …, Rate limit tool
  invocations, Sanitize tool outputs." — Pydantic on the handler
  signature + `enforce_byte_cap` cover this.
- Tool execution error: report via `isError: true` in result (NOT a
  JSON-RPC error). A failed-elaboration is NOT an `isError` — it is a
  successful tool call returning `compilation_success: false` per the
  brief. `isError: true` is for "Lean REPL crashed" / "timeout" /
  "Lean disabled".

### leanprover-community/repl protocol — exact response fields

From https://github.com/leanprover-community/repl (verbatim shape, also
cross-checked against spike-2 §Results):

- **Input (Command mode):** `{"cmd": "<lean source>", "env": <int|null>}`.
  `env` is the environment ID returned by a previous response (chaining
  imports / context).
- **Response:** any subset of:
  - `env`: int (new env id)
  - `messages`: list of `{severity, pos: {line, column}, endPos: {line,
    column}, data: str}` — `severity ∈ {"error","warning","info"}` (the
    spike validated "error"; the repl source includes "warning" + "info").
  - `sorries`: list of `{pos, endPos, goal: str, proofState: int}`.
  - `tactics`: list (only when `allTactics: true`).
  - `proofState`: int (Tactic mode).
- **No `compilation_success` field exists in the protocol.** The handler
  must derive it: `compilation_success = not any(m.severity == "error"
  for m in messages)`.
- **No `goals_remaining` field.** Derive: `goals_remaining =
  [s.goal for s in sorries]` (plus any unresolved goal from the Tactic
  reply, if used). The brief's schema has `goals_remaining` AND
  `sorry_goals` as separate keys; recommend `sorry_goals` carries the
  full sorry rows (with position) and `goals_remaining` carries the goal
  strings only.
- **No "syntax_only" command exists in the REPL.** §Failure mode 1 below
  covers how m3 must distinguish modes.

### Python `resource.setrlimit(RLIMIT_AS, ...)` — POSIX semantics

From https://docs.python.org/3/library/resource.html:

- **"Availability: Unix, not WASI."** The `resource` module **does not
  exist on Windows.** `import resource` raises `ModuleNotFoundError` on
  Windows. The m3 implementer must guard the import behind a `sys.platform
  != "win32"` check or `try/except ImportError`.
- `setrlimit(RLIMIT_AS, (soft, hard))`: caps **virtual address space**
  (heap + stack + mmap), broader than `RLIMIT_DATA` (heap only). Both
  soft and hard must be passed.
- Soft limit can be lowered any time; hard limit can be lowered to ≥ soft
  but only super-user can raise. Passing `RLIM_INFINITY` keeps unlimited.
- Errors: `ValueError` if soft > hard or new hard exceeds existing hard
  for non-root; `OSError` (alias `resource.error`) on syscall failure.
- Audit event: `resource.setrlimit` is emitted (informational).

### `asyncio.create_subprocess_exec` — `preexec_fn` platform note

From https://docs.python.org/3/library/asyncio-subprocess.html (cross-ref
to `loop.subprocess_exec`):

- `preexec_fn` is a **POSIX-only** parameter inherited via `**kwds` from
  `subprocess.Popen`. **On Windows the subprocess module raises
  `ValueError` when `preexec_fn` is set.** This is the same constraint the
  `subprocess.Popen` docs spell out explicitly.
- `preexec_fn` runs in the child between `fork()` and `execve()` — single-
  threaded child, so calling `resource.setrlimit` there is safe (no
  threading footguns documented by CPython, though `subprocess` warns
  generally about preexec_fn + threads in the parent).
- Windows uses `creationflags` for analogous control (e.g.
  `CREATE_BREAKAWAY_FROM_JOB`); the Job-Object route (`SetInformationJobObject
  + JOB_OBJECT_LIMIT_PROCESS_MEMORY`) is the **only** way to cap memory
  on Windows and is **not** within m3's scope (matches lean-sandbox-design
  "documented, not implemented" for Windows).

---

## Failure-mode analysis (≥5 enumerated)

### FM-1 — `syntax_only` mode silently equals `full`

**Trigger.** The leanprover-community/repl JSON protocol has **no
"syntax-only" command** (the WebFetch + spike-2 protocol summary confirm
this — only `cmd`, `path`, `tactic`, pickling are accepted). An implementer
who reads "short-circuits after elaboration" and writes
`mode == "syntax_only": await self._repl.query({"cmd": snippet})` ships a
tool whose two modes return identical results. AC3 ("returns after
elaboration without full kernel verification") becomes untestable.

**Symptom.** AC test green by accident (the snippet under test triggers
elaboration errors, which fire identically in both modes); production
latency profile of `syntax_only` equals `full` for any non-trivial proof;
no actual cheap path for the autoformalizer.

**Mitigation.** Pick ONE of two strategies and document it:
1. **Wrap the snippet in `#check`/`#guard_msgs` only** — Lean's elaborator
   reports type errors during `#check` without running the full kernel
   pipeline (decide-instances, etc.). The mode flag substitutes
   `cmd: "#check (proof_term)"` for `syntax_only`.
2. **Use `noncomputable section` + `set_option maxHeartbeats 1`** to
   trip the kernel before it does meaningful work — but this changes the
   semantics of error messages and is fragile. **Reject this.**

**Recommendation:** strategy 1. Document the limitation explicitly in the
tool description: "syntax_only does NOT skip Lean's elaborator; it skips
post-elaboration kernel verification by wrapping the snippet in `#check`."
This sets correct caller expectations and matches what the REPL can
actually do.

### FM-2 — Non-terminating snippet hangs the 30 s timeout AND wedges the single REPL

**Trigger.** Agent submits `def f : Nat := f` or `theorem t : True := by
repeat skip`. The query times out at 30 s (`server/lean_repl.py:51`); on
timeout `LeanReplError` is raised but **the REPL subprocess is not
killed**. The next `query()` acquires the I/O lock, finds
`returncode is None`, sends a new command, and reads stale stdout
(the prior elaboration is still mid-flight and will eventually emit its
response, which the new caller misinterprets).

**Symptom.** Subtle response interleaving; the second call gets the first
call's stale output; every subsequent call sees N-1's response. End-state
is silent corruption of `lean_verify` results for a session.

**Mitigation.** The m3 handler MUST close-and-respawn the REPL on timeout.
The `lean-sandbox-design.md` row "Per-query timeout" already names this:
> m3 will additionally kill+respawn the process on timeout.

Implement: catch `LeanReplError("timeout")` in the handler, call
`await self._repl.close()` then `LeanRepl.spawn_from_config(...)` and set
the result `compilation_success: false` + `status: "timeout"` + a
`messages` row with `severity: "error"`, `text: "Lean REPL killed after
30s"`. Add a regression test using the `_FakeProc(stdout_hang=True)`
pattern to assert respawn happens before the next call succeeds.

### FM-3 — `preexec_fn` + `RLIMIT_AS` crashes on Windows

**Trigger.** Implementer adds `preexec_fn=_apply_rlimit_as` to
`server/lean_repl.py::spawn` unconditionally. On the **Windows
workstation** (this checkout) `asyncio.create_subprocess_exec` calls
`subprocess.Popen` which raises `ValueError("preexec_fn is not supported on
Windows platforms")`. Every `ARXMCP_ENABLE_LEAN=true` startup fails with a
cryptic error.

**Symptom.** The user (Windows secondary checkout) cannot run
`lean_verify` at all; the always-off `enable_lean=False` path remains
green so `make test` passes; the failure surfaces only on operator opt-in
and looks like a Lean toolchain problem.

**Mitigation.** Guard the `preexec_fn` argument with
`sys.platform != "win32"`. Pseudocode:
```python
spawn_kwargs: dict[str, Any] = {}
if sys.platform != "win32" and resource is not None:
    spawn_kwargs["preexec_fn"] = _apply_rlimit_as
proc = await asyncio.create_subprocess_exec(..., **spawn_kwargs)
```
AND guard `import resource` itself with `try: import resource except
ImportError: resource = None` (Windows has no `resource` module). Log a
WARN at startup: "Lean REPL spawned WITHOUT RLIMIT_AS (Windows); the 30 s
timeout is the only memory backstop." This matches the lean-sandbox-design
table's "POSIX/Windows split" intent.

### FM-4 — Result schema fields silently missing when REPL omits them

**Trigger.** The brief mandates the result schema returns
`{status, messages, position, text, proof_state, goals_remaining,
sorry_goals, compilation_success}`. The REPL response **omits** keys when
empty: a clean compile returns `{"env": 0}` with NO `messages`, NO
`sorries`. Implementer writes `messages=resp["messages"]` and gets
`KeyError`. Patches with `resp.get("messages")` and the schema row gets
`null`, which JSON-Schema-rejects against the spec
`messages: [...]` (array).

**Symptom.** Either 500-level Pydantic validation failure on the happy
path, or the schema-pin test in `tests/test_snippet_contract.py` fires
with "messages: null does not match array".

**Mitigation.** All list-valued schema fields default to `[]` (empty list)
not `null`. The handler MUST run every REPL response through a
normalization step:
```python
def _normalize(resp: dict) -> dict:
    msgs = resp.get("messages") or []
    sorries = resp.get("sorries") or []
    has_error = any(m.get("severity") == "error" for m in msgs)
    return {
        "status": "ok" if not has_error else "error",
        "compilation_success": not has_error,
        "messages": [
            {"severity": m["severity"],
             "position": m.get("pos") or {"line": 0, "column": 0},
             "text": m.get("data", "")}
            for m in msgs
        ],
        "sorry_goals": [
            {"goal": s["goal"], "position": s.get("pos")}
            for s in sorries
        ],
        "goals_remaining": [s["goal"] for s in sorries],
        "proof_state": resp.get("proofState"),
    }
```
Schema requires every key (`required: [...]`) and uses `type: "array"`
not `["array","null"]` to make absences a positive error during
development. Document the derived nature of `compilation_success` and
`goals_remaining` (they come from messages+sorries, not the REPL).

### FM-5 — Tool-schema hash drift not re-pinned → BP1 cache flush across ALL agent roles

**Trigger.** Adding `LEAN_VERIFY = ToolMeta(...)` to `ALL_TOOLS` in
`server/tools.py` changes the `tools/list` JSON bytes, which changes
SHA-256. `tests/test_server_tool_schema.py::EXPECTED_TOOL_SCHEMA_SHA256`
is now stale. The contributor forgets to run
`pytest --update-tool-schema-hash` AFTER wiring (running BEFORE produces
the wrong hash — `agent-conventions.md §7`).

**Symptom.** `make test` fails with hash mismatch; OR the contributor
re-pins early, then changes the description, leaves a stale hash, ships,
and **every production sub-agent's BP1 cache is invalidated** because
the live `tools/list` no longer matches what the orchestrator hashed at
prior session start. Per `07-multi-agent-caching.md`: "A casual edit to a
tool description blows every sub-agent's cache."

**Mitigation.** The implementer MUST bump `TOOL_SCHEMA_VERSION` 11 → 12
in `server/tools.py:111`, write the description as a frozen `ToolMeta`
constant (matches the existing pattern), wire the handler in
`register_all()`, then `pytest tests/test_server_tool_schema.py
--update-tool-schema-hash` is the LAST step. Cross-check:
`server/schemas/lean_verify_result.json["version"] == 12` (per the
`search_papers_result.json` cross-check pattern in
`tests/test_snippet_contract.py::TestSchemaVersionPin`).

### FM-6 — `RLIMIT_AS` set too low, kernel/elan bootstrap fails before first query

**Trigger.** Implementer picks a generous-sounding cap (e.g. 1 GiB =
`1 << 30`). Lean's kernel + mathlib-free repl easily mmap > 1 GiB of
oleans during the FIRST `query`. The kernel emits an out-of-memory abort
to stderr (already DEVNULL'd per m2) and the subprocess exits with
non-zero returncode mid-elaboration. The handler reports "Lean REPL
closed stdout before returning a response (subprocess likely crashed)"
on every call.

**Symptom.** All `lean_verify` calls fail with a confusing "subprocess
crashed" error on operator-enable; the always-run test
`TestFakeProcRoundTrips::test_query_eof_before_response_raises` already
covers the error path so the always-run suite stays green; only the
`requires_lean_repl`-gated integration test surfaces the issue (and
only if it submits a snippet, not just `spawn`).

**Mitigation.** Pick the cap empirically. Spike-2 documented "well under
a minute" build + sub-second round-trips; the steady-state RSS of
`lake exe repl` on the spike box was not measured. Set the default
generously (recommend **4 GiB** = `4 * 1024**3`) and expose it as
`ARXMCP_LEAN_RLIMIT_AS_BYTES` so the operator can lower it for a known-
small corpus. Add a `requires_lean_repl` test that:
1. Spawns at the configured cap.
2. Submits the smallest valid snippet (`theorem t : True := trivial`)
   and asserts the response arrives — i.e. the cap is high enough for
   baseline operation.
3. Submits a high-allocation snippet (e.g. `def f := List.range 10000000`)
   and asserts the REPL is **bounded** (the subprocess exits or surfaces
   an error) rather than OOM-killing the parent (which is what the brief
   AC actually requires: "REPL is bounded rather than OOM-killing the
   parent").

---

## Recommendation

Ship m3 in this exact order, one logical commit:

1. Add `server/schemas/lean_verify_result.json` (version 12) with all eight
   required keys, every list-valued field `"type": "array"` (not nullable),
   `messages` items typed `{severity ∈ enum, position: {line, column},
   text: str}`.
2. Add `server/handlers/lean_verify.py`:
   - Pydantic-annotated handler signature: `snippet: str`, optional
     `imports: list[str] = []`, `mode: Literal["full","syntax_only"] =
     "full"`.
   - For `mode="syntax_only"`, wrap snippet as `#check (<term>)` BEFORE
     submission (FM-1).
   - On `LeanReplError` from a timeout, close + respawn `lean_repl` from
     `get_resources()`, return `status: "timeout"` (FM-2).
   - Normalize REPL response with a strict `_normalize()` (FM-4); use
     `envelope()` and `enforce_byte_cap(structuredContent,
     body_text_path=("messages",))` for the byte cap.
3. Modify `server/lean_repl.py::spawn` to accept an optional
   `rlimit_as_bytes: int | None` and pass `preexec_fn` only when
   `sys.platform != "win32"` AND the `resource` module imports (FM-3).
   Default `rlimit_as_bytes` from `Config.lean_rlimit_as_bytes` (new
   field, default `4 * 1024**3`).
4. Add `LEAN_VERIFY` `ToolMeta` constant + append to `ALL_TOOLS` in
   registration order (8th slot). Bump `TOOL_SCHEMA_VERSION` 11 → 12.
5. Wire handler in `register_all`. Run `pytest
   tests/test_server_tool_schema.py --update-tool-schema-hash` LAST (FM-5).
6. Tests: `tests/test_handlers_lean_verify.py` always-run via `_FakeProc`
   harness (mirror `tests/test_lean_repl.py` pattern), plus one
   `@pytest.mark.requires_lean_repl` integration test for the
   high-allocation memory-cap assertion (FM-6).

---

## Open questions

1. **`syntax_only` semantics — `#check` wrapping vs alternative.** The brief
   says "short-circuits after elaboration" but the REPL has no such mode
   (FM-1). Recommendation above is `#check`. The peer brief may pick
   `set_option maxHeartbeats`; orchestrator should surface the
   disagreement to the implementer. **Picked recommendation:** `#check`.
2. **`RLIMIT_AS` default value.** No empirical RSS measurement exists.
   Recommendation: 4 GiB default, env-overridable. The integration test in
   step 6 above doubles as a calibration measurement at first run.

---

## External writes the implementation will require

None — this milestone is purely local. The implementation commit lands on
`main` via the standard milestone-pipeline path (Phase 4 main thread); no
`gh`/`git push`/infra mutation is required by m3 itself. Per CLAUDE.md
§4.4, push is per-event user authorization at the end of Phase 4 and is
the orchestrator's responsibility, not the implementer's.
