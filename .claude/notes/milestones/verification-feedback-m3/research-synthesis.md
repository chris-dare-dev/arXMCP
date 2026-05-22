# Research Synthesis — verification-feedback-m3

**Inputs:** `research-brief-1.md` (in-codebase touchpoints) + `research-brief-2.md` (external + 6 failure modes).
**Orchestrator merge.** Both briefs returned `status: ok`. Disagreement is explicit and resolved below — not silently averaged.

## 1. Touchpoint map (briefs agree)

Six edit sites for the `lean_verify` tool:

1. **`server/handlers/lean_verify.py`** (new). Async handler
   `handle_lean_verify(snippet, imports, mode)` modeled on
   `server/handlers/citations.py` (the m1 template). Pydantic
   `Annotated[..., Field(...)]` typing on inputs; first-line input
   validation; `envelope()` + `cap_result_list`/`enforce_byte_cap` wrap.
2. **`server/tools.py`** — add `LEAN_VERIFY = ToolMeta(...)`; append to
   `ALL_TOOLS` (8th slot, end of tuple); wire `handler_by_name` in
   `register_all`; **bump `TOOL_SCHEMA_VERSION` 11 → 12** at line ~111.
3. **`server/schemas/lean_verify_result.json`** (new). Frozen result-row
   schema. `"version": 12` (cross-checked by
   `tests/test_snippet_contract.py::TestSchemaVersionPin`). Closed
   `additionalProperties: false`, all fields `required`, list-valued fields
   typed `"type": "array"` (NOT nullable — see §6 normalization).
4. **`server/lean_repl.py::spawn`** — accept `rlimit_as_bytes`; pass
   `preexec_fn` only when `sys.platform != "win32"` (see §4).
5. **`server/config.py`** — new `lean_rlimit_as_bytes: int = 4 * 1024**3`
   field (env var `ARXMCP_LEAN_RLIMIT_AS_BYTES`).
6. **`tests/test_handlers_lean_verify.py`** (new). Tier-1 always-run via
   `_FakeProc` (port the m2 critique-F2 harness from
   `tests/test_lean_repl.py::TestFakeProcRoundTrips`). Tier-2
   `@pytest.mark.requires_lean_repl` for the three AC scenarios + the
   high-allocation memory-cap assertion.

## 2. The m2 LeanRepl.query response → m3 result schema (briefs agree)

`leanprover-community/repl` response keys (verbatim from spike-2 + the
upstream README):

| REPL field | Schema field | Mapping |
|---|---|---|
| `messages[*].severity` (`error`/`warning`/`info`) | `messages[*].severity` | verbatim |
| `messages[*].pos` (`{line, column}`) | `messages[*].position` | rename `pos → position` |
| `messages[*].data` | `messages[*].text` | rename `data → text` |
| `sorries[*]` (`{pos, endPos, goal, proofState}`) | `sorry_goals[*]` | full row with `position` |
| `sorries[*].goal` | `goals_remaining[*]` | goal-string only |
| `sorries[0].goal` (or `null`) | `proof_state` | first sorry's goal, else `null` |
| derived (`any sev=="error"`) | `compilation_success` | `not any(m.severity == "error")` |
| derived | `status` | `"error"` > `"sorry"` > `"ok"` (or `"timeout"` / `"unavailable"`) |

**`sorry_goals` vs `goals_remaining`** — picked brief-2's distinction:
`sorry_goals` carries the full row (with `position`), `goals_remaining`
carries goal strings only. They differ in shape — both useful, neither
redundant. (Brief-1 proposed making them byte-identical in v1; rejected
because brief-2's shape better satisfies the brief AC text and reserves no
future-divergence work.)

## 3. `syntax_only` mode — DISAGREEMENT RESOLVED

**The protocol fact** (both briefs reach independently): the
`leanprover-community/repl` JSON protocol has **no `syntax_only` flag**.
Verified against the upstream README and spike-2.

- Brief-1: recommends `{"cmd": snippet, "allTactics": false}` with an
  inline TODO + fallback to `#check`. Confidence is low; brief-1 itself
  lists this as Open Question 1.
- Brief-2: rejects the `allTactics` hypothesis (not what the flag does
  in upstream — it controls per-tactic output, not skip-kernel) and
  recommends wrapping the snippet as `{"cmd": "#check (<term>)"}` for
  `syntax_only` mode. Lean's `#check` runs the elaborator and reports
  type errors without driving the full kernel/decide-instances pipeline.

**Picked: brief-2's `#check` wrapping.** Reasoning: brief-2's analysis is
grounded in the upstream protocol (the `allTactics` flag's actual
semantics is "emit per-tactic message rows," not "skip kernel"), and
`#check` is a documented Lean elaboration entry point. The tool
description must state this verbatim — "`syntax_only` does NOT skip Lean's
elaborator; it skips post-elaboration kernel verification by wrapping the
snippet in `#check`" — so the caller's expectations match the mechanism.

**Open: what if the snippet is a `theorem` / `def`, not a term?** A
`theorem` cannot be `#check`-wrapped directly. Implementer recommendation:
when `mode == "syntax_only"`, send the snippet AS-IS but with the snippet
preceded by `set_option maxHeartbeats 5000 in` to short-circuit
kernel-heavy work; `#check` wrapping applies when the input is a bare
expression. The implementer should ship one consistent strategy and
document it in the handler's docstring.

## 4. RLIMIT_AS placement — POSIX-only, Windows safe-no-op (briefs agree)

`server/lean_repl.py::spawn` already calls `asyncio.create_subprocess_exec`
at line 132. Add a `preexec_fn` parameter that calls
`resource.setrlimit(resource.RLIMIT_AS, (cap, cap))`.

**Windows discipline (load-bearing — this checkout is Windows).** Two
guards, both required:

```python
# 1. Import guard — `resource` does not exist on Windows.
try:
    import resource as _resource
except ImportError:
    _resource = None

# 2. Spawn-time guard — preexec_fn on Windows raises ValueError.
spawn_kwargs: dict[str, Any] = {}
if sys.platform != "win32" and _resource is not None and rlimit_as_bytes:
    def _set_rlimit():
        _resource.setrlimit(
            _resource.RLIMIT_AS, (rlimit_as_bytes, rlimit_as_bytes)
        )
    spawn_kwargs["preexec_fn"] = _set_rlimit

proc = await asyncio.create_subprocess_exec(..., **spawn_kwargs)
```

On Windows, log WARN at spawn: "Lean REPL spawned WITHOUT RLIMIT_AS
(Windows); the 30 s timeout is the only memory backstop." This matches
the existing `.claude/docs/lean-sandbox-design.md` Memory-cap row's
POSIX/Windows split and is **documented**, not silent. The
`Config.lean_rlimit_as_bytes` default is `4 * 1024**3` (4 GiB) per both
briefs.

## 5. Failure modes — implementer must close each before ship

(Brief-2's six failure modes plus brief-1's lean_repl=None graceful path.)

| ID | Trigger | Mitigation (implementer) |
|---|---|---|
| FM-1 | `syntax_only` silently equals `full` (no REPL flag exists) | `#check`-wrap snippet when `mode == "syntax_only"` (§3) |
| FM-2 | 30 s timeout raises `LeanReplError` but DOES NOT kill + respawn → next call reads stale stdout, corrupts session | Handler catches timeout, calls `await self._repl.close()` + `LeanRepl.spawn_from_config(...)`, returns `status: "timeout"` + `compilation_success: false`. Add regression test using `_FakeProc(stdout_hang=True)`. **Required by `.claude/docs/lean-sandbox-design.md` row "Per-query timeout"** (m3-promised). |
| FM-3 | `preexec_fn` on Windows raises `ValueError` | `sys.platform != "win32"` guard + ImportError guard on `resource` (§4) |
| FM-4 | Schema fields missing (REPL omits empty `messages`/`sorries`) → `KeyError` or `null` against `type: "array"` | All list fields default to `[]` (NOT `null`); strict `_normalize()` step on every response; schema uses `type: "array"` (not nullable) so absences are positive errors during dev |
| FM-5 | Hash drift not re-pinned → `make test` fails OR (worse) ships and flushes every sub-agent's BP1 cache | Order: bump `TOOL_SCHEMA_VERSION` 11 → 12 FIRST, write handler + schema + ToolMeta, run `pytest tests/test_server_tool_schema.py --update-tool-schema-hash` LAST. The F2 anti-decorative-version guard at `test_server_tool_schema.py:367-382` enforces version-bump-before-update-flag. |
| FM-6 | RLIMIT_AS set too low (e.g. 1 GiB) → Lean kernel + oleans mmap exceeds cap, subprocess OOM-exits, every query reports "subprocess crashed" | Default 4 GiB; env-overridable via `ARXMCP_LEAN_RLIMIT_AS_BYTES`; `requires_lean_repl` smoke test asserts a trivial snippet succeeds at the configured cap before the high-allocation test runs |
| FM-7 | `enable_lean=False` + agent calls `lean_verify` (the tool is registered for BP1 stability but the REPL is None) | Handler reads `get_resources().lean_repl`; when `None`, return graceful envelope `{status: "unavailable", lean_status: "disabled", ...}` with empty lists. Mirrors `citations.py::graph_status` precedent from m1. NEVER 5xx on the disabled path. |

## 6. Implementation contract (synthesis-frozen)

The handler is a thin mapping over `LeanRepl.query` plus the seven
mitigations above. Pseudo-shape:

```python
async def handle_lean_verify(
    snippet: Annotated[str, Field(min_length=1, max_length=8192)],
    imports: Annotated[list[str], Field(max_length=32)] = (),
    mode: Literal["full", "syntax_only"] = "full",
) -> dict:
    # FM-7: graceful disabled path
    resources = get_resources()
    if resources.lean_repl is None:
        return envelope(_lean_unavailable_envelope())

    # FM-1: syntax_only mode wraps the snippet
    cmd = _build_command(snippet, imports, mode)
    try:
        resp = await resources.lean_repl.query({"cmd": cmd})
    except LeanReplError as exc:
        if "timeout" in str(exc):
            # FM-2: close + respawn before next call
            await resources.lean_repl.close()
            resources.lean_repl = await LeanRepl.spawn_from_config(
                resources.config
            )
            return envelope(_timeout_envelope())
        # any other LeanReplError -> error envelope
        return envelope(_repl_error_envelope(exc))

    # FM-4: strict normalize (no KeyError, no nulls on list-typed fields)
    payload = _normalize(resp)
    return envelope(enforce_byte_cap(payload, list_key="messages"))
```

## 7. Cache discipline (synthesis-frozen)

- `LEAN_VERIFY.description` is a frozen module-level constant string. No
  f-strings, no env-var interpolation, no dynamic content. The
  `test_changing_tool_description_changes_hash` regression test is the
  guard.
- `TOOL_SCHEMA_VERSION = 12` is bumped BEFORE `--update-tool-schema-hash`
  runs (the F2 gate rejects bare hash drift otherwise).
- Append `LEAN_VERIFY` to `ALL_TOOLS` at the END of the tuple. Inserting
  it mid-tuple would drift `tools/list` order and the description hash
  needlessly.
- Add a `v12: lean_verify (verification-feedback-m3) - kernel-backed Lean
  4 verification` line at the top of the `v<N>:` comment block at
  `server/tools.py:111`.

## 8. Open questions (post-synthesis)

1. **`#check`-wrapping vs `set_option maxHeartbeats`** for snippets that
   are `theorem`/`def` declarations (not bare terms). §3 covers this:
   implementer picks ONE strategy and documents it in the handler
   docstring + tool description; if `#check` is wrong for declarations,
   fall back to `set_option maxHeartbeats 5000 in <snippet>`. A 1-LOC
   change either way; ship behind a strategy comment.
2. **RLIMIT_AS calibration on the real Lean toolchain.** The 4 GiB default
   is informed by the lean-sandbox-design.md "POSIX follow-up" wording,
   not by measured RSS. The `requires_lean_repl` smoke test (FM-6
   mitigation) acts as a calibration run on first execution.

## 9. External writes the implementation will require

**None.** Both briefs concur. Purely local — handler + schema + tool
registration + a config field + a `LeanRepl.spawn` kwarg + tests + a
re-pinned hash. No `git push`, no `gh`, no infra mutation, no third-party
API. `external_writes_required = []`.

## Orchestrator synthesis note

Two divergences between briefs were resolved here, not averaged:

- **`syntax_only` mechanism** — picked brief-2's `#check` wrapping over
  brief-1's `{"allTactics": false}` (which brief-1 itself listed as
  uncertain).
- **`sorry_goals` vs `goals_remaining` shape** — picked brief-2's distinct
  shapes (full row vs goal-string list) over brief-1's byte-identical v1.

Brief-2's failure-mode analysis (6 modes) is fully adopted into §5; brief-1's
graceful-unavailable pattern (FM-7) is added on top. The implementer's
contract is §6's pseudo-shape — every mitigation in §5 must close before
ship.
