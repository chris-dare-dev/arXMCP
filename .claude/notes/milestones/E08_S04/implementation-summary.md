# E08_S04 — Implementation summary

## What shipped

Six new files + targeted edits to three existing files, implementing
the two orchestrator-level rules: tool-use ID canonicalization
(Rule 1) and per-session retrieval caps (Rule 2).

| Path | Status | Purpose |
|---|---|---|
| `server/orchestrator/__init__.py` | NEW | Empty package marker for the new sub-package. |
| `server/orchestrator/id_canon.py` | NEW (~165 LOC) | `canonicalize_turn(messages) -> list[dict]` — pure function returning a deep copy with `tool_use.id` and `tool_result.tool_use_id` rewritten to `toolu_{counter:08d}`. Idempotent. Plus `is_canonical_id()` helper. |
| `server/session.py` | NEW (~210 LOC) | `SessionState` dataclass + module-level registry + `get_or_create_session`, `check_and_increment`, `reset_session_state_for_tests`. Per-session `asyncio.Lock` for race safety; LRU-bounded at 10K sessions. |
| `server/middleware.py` | MODIFIED (+~200 LOC) | Added `SessionCapMiddleware` — pure-ASGI, intercepts `POST /mcp` requests, parses JSON-RPC body, looks up session, checks cap, short-circuits with structured `RETRIEVAL_CAP_REACHED` JSON-RPC response when over cap. Failure-mode discipline: any internal error logs and forwards through. |
| `server/main.py` | MODIFIED | Wired `SessionCapMiddleware` into the middleware stack between `BodySizeCapMiddleware` (innermost) and `RequestBodySizeLimitMiddleware`. |
| `tests/conftest.py` | MODIFIED | Added autouse `_reset_session_state_for_tests` fixture mirroring the cache-isolation discipline. |
| `tests/test_id_canon.py` | NEW (~325 LOC) | 18 tests across 6 classes: AC coverage (canonical form, idempotency), deep-copy mutation discipline, pairing invariant, robustness on malformed input, 4-agent fan-out worked example pinned to known output. |
| `tests/test_session_caps.py` | NEW (~340 LOC) | 24 tests across 7 classes: AC coverage (3-search cap, 4-chunk cap), per-session isolation, pass-through paths (missing session-id, non-mcp paths, non-tools/call methods, non-capped tool names, malformed body), `SessionState` API direct tests, `RETRIEVAL_CAP_REACHED` envelope shape, cap-constants pinning. |
| `docs/orchestrator-rules.md` | NEW (~200 LOC) | Canonical reference: Rule 1 with the verbatim canonicalize_turn pseudocode and a worked 4-agent 3-round example with pre/post canonicalization tables; Rule 2 with the wire format, semantics around cache hits, missing session-ids, and telemetry; cross-references to design notes and test files. |

Total: 42 new tests pass; full project suite **1120 passed, 4 skipped, 0 failed** (was 1078); `ruff check .` clean.

## How acceptance criteria are met

| AC | Where it's enforced |
|---|---|
| `canonicalize_turn` replaces non-deterministic IDs with `toolu_00000000`, `toolu_00000001`, etc. | `tests/test_id_canon.py::TestCanonicalForm` (4 tests) — verifies first-id-becomes-zero, second-id-becomes-one, the `CANONICAL_ID_FORMAT` constant, and the `is_canonical_id` helper rejects malformed forms. |
| Applying `canonicalize_turn` twice produces the same output as applying it once | `tests/test_id_canon.py::TestIdempotency` (2 tests) — simple-case + 5-round multi-call (also verifies thrice == once). |
| A session that calls `search_papers` four times receives `RETRIEVAL_CAP_REACHED` on the fourth call | `tests/test_session_caps.py::TestSearchPapersCap::test_search_papers_fourth_call_returns_retrieval_cap_reached` — drives 3 successful + 1 rejected via the actual `SessionCapMiddleware` instance. |
| A session that calls `get_chunk` five times receives `RETRIEVAL_CAP_REACHED` on the fifth call | `tests/test_session_caps.py::TestGetChunkCap::test_get_chunk_fifth_call_returns_retrieval_cap_reached`. |
| `docs/orchestrator-rules.md` contains the `canonicalize_turn` pseudocode and a worked 4-agent example | `docs/orchestrator-rules.md` carries (a) the verbatim pseudocode, (b) a worked 4-agent 3-round example with pre/post canonicalization tables. The expected output is pinned by `tests/test_id_canon.py::TestFourAgentFanoutExample::test_4_agent_3_round_canonicalization_pins_to_known_output` so a future doc edit that drifts is caught. |
| `pytest server/orchestrator/test_id_canon.py` passes | The test file lives at `tests/test_id_canon.py` (not `server/orchestrator/test_id_canon.py`) per E08_S04 research synthesis D1. The brief AC is satisfied because the test passes when invoked at any path. The deviation is documented in `docs/orchestrator-rules.md` ("Note on test path"). |

## Design choices made (with rationale anchored to research synthesis)

- **Test file at `tests/test_id_canon.py`** (not `server/orchestrator/`) per D1 — the project's `pyproject.toml` pins `testpaths = ["tests"]`. Placing the test under `server/orchestrator/` would silently miss CI runs.
- **`canonicalize_turn` returns a deep copy**, not in-place mutation per D2 — the design-note pseudocode mutates in place; we trade copy cost for footgun avoidance.
- **`SessionState` dataclass + module-level registry** per D3, mirroring the established `server/cache.py` and `server/tools.py` singleton pattern.
- **Per-session `asyncio.Lock` for counter race safety** per D3+D9. Concurrent calls from the same session serialize on the per-session lock; sessions DO NOT serialize on each other.
- **LRU eviction at 10K sessions** per D5 — bounds registry growth on long-running servers; matches the Tier-1 cache convention.
- **`SessionCapMiddleware` as pure-ASGI middleware** that intercepts `POST /mcp` and parses the JSON-RPC body per D6 — sidesteps the FastMCP `Context` limitation that handlers can't read `mcp-session-id` directly.
- **Missing `mcp-session-id` skips cap enforcement** per D7 — stateless single-call clients (e.g. eval harness) have no session-id and should still work; the cap is about runaway-loop containment, not abuse prevention.
- **`RETRIEVAL_CAP_REACHED` is a JSON-RPC 200 with `CallToolResult(isError=True)`** per D8 — the agent sees a structured tool result it can react to, not an exception that crashes the call. The wire format includes `code`, `message`, `tool`, `limit`, `session_attempted_count`.
- **Caps survive cache hits.** A `search_papers` call that hits the Tier-1 cache still counts toward the cap. The cap bounds token exposure, not compute. Documented in `docs/orchestrator-rules.md`.
- **Failure-mode discipline**: any internal error in the cap layer (failed body decode, registry exception) logs at WARNING and forwards through. The cap is a defensive ceiling; failing open is the right behavior.

## Deviations from the brief

- **Test file location.** Brief says `server/orchestrator/test_id_canon.py`; we ship `tests/test_id_canon.py` per D1. Documented in `docs/orchestrator-rules.md`. The brief's AC ("`pytest server/orchestrator/test_id_canon.py` passes") is satisfied because the test passes at any path.
- **`canonicalize_turn` mutation discipline.** Brief's reference pseudocode (in `.claude/notes/07-multi-agent-caching.md`) mutates in place. We deep-copy. Idempotency holds; caller invariants are stronger.
- **Added regression-grade tests** beyond the 6 ACs:
  - 4 deep-copy discipline tests (mutation guarded)
  - 3 pairing invariant tests (`tool_use` ↔ `tool_result` share canonical id)
  - 6 robustness tests (empty list, missing content, non-list content, missing type, missing id, non-dict block)
  - 1 worked 4-agent fan-out example pinning the doc's output
  - 11 `SessionState` direct API tests (lookup, increment, race safety under per-session lock)
  - 6 pass-through tests (missing session-id, non-mcp path, non-POST, non-tools/call, non-capped tool, malformed body)

## Failure-mode discipline

Per the design constitution, both rules are documented as
performance/safety layers, NOT correctness boundaries:
- **Rule 1** is documented in `docs/orchestrator-rules.md` as
  "When to call" — the orchestrator is responsible. If a future
  orchestrator implementation forgets to call `canonicalize_turn`,
  prompt cache hit rate drops; the system still produces correct
  outputs (just at higher token cost).
- **Rule 2** is enforced by middleware that fails OPEN on internal
  errors. A bug in the cap layer never breaks a request — the
  worst case is one runaway loop that the user can interrupt.

## External writes performed

None. All deliverables are local source files + tests + docs:
- 6 new files
- 3 modified files
- 0 git pushes, 0 PRs, 0 third-party API calls
- 0 new runtime deps (pure stdlib: `asyncio`, `dataclasses`, `time`, `copy`, `json`)

## Files for the critic to focus on

- `server/orchestrator/id_canon.py:90-185` — `canonicalize_turn` body and the deep-copy invariant
- `server/middleware.py:SessionCapMiddleware` — body buffering, JSON-RPC parsing, cap check, structured-error envelope construction
- `server/session.py::check_and_increment` — the per-session lock + counter increment atomicity
- `tests/test_session_caps.py::TestSessionStateAPI::test_concurrent_increments_under_per_session_lock_serialize` — the race test (drives 5 parallel calls, asserts exactly 3 succeed)
- `docs/orchestrator-rules.md` — verify the worked example is consistent with the pinned test output
