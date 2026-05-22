# Critique — verification-feedback-m3

**Critic:** adversary
**Generated:** 2026-05-22T23:21:40Z
**Commit range:** f52ce5cf4559f0a10dc68402baa5b621e438181a..52951ad2775ccf4b2da855ce2ad4027766fe5278
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES: the `lean_verify` tool is wired correctly across handler, schema, registration, BP1 hash, and the RLIMIT_AS plumbing, but the brief's "high-allocation snippet is bounded" AC is not actually verified by the integration test and three schema-conformance gaps mean a future Lean REPL change could silently produce schema-violating responses.
- Finding counts: 0 CRITICAL, 2 HIGH, 4 MEDIUM, 2 LOW.
- Highest-risk site: `tests/test_handlers_lean_verify.py:702-726` — the integration assertion meant to prove RLIMIT_AS works submits `List.range 1000` (a trivial 1k-element allocation) and asserts only `status in {ok, error, sorry}` — would pass even if `preexec_fn` were never attached.
- Cache discipline is intact: `TOOL_SCHEMA_VERSION` 11→12, `EXPECTED_TOOL_SCHEMA_SHA256` re-pinned, `EXPECTED_BP1_SHA256` re-pinned, `LEAN_VERIFY` appended at the end of `ALL_TOOLS` (not mid-tuple). Description is a literal constant (no f-strings).
- Threat-3 input bound for subprocess (`MAX_SNIPPET_LEN=16 KiB`, `MAX_IMPORT_LINE_LEN=256`, `MAX_IMPORTS=64`) is a sane defensive add (D2) and consistent with the project's threat-model note.
- Security axes (origin pinning, loopback bind, redaction, snippet contract) are untouched — the tool returns no paper-derived text so the `<retrieved_chunk>` wrapping does not apply (correctly skipped per schema description and module docstring).
- Tier-sequencing clean: m3 depends only on m2 (already shipped) — no consumption of pending epics. No new external service, no AWS, no submodule, no `BaseHTTPMiddleware`, no `0.0.0.0`, no `latest` image tag, no `assert`-for-invariant, no `import anthropic`, no `claude-opus` string — banned-pattern checklist clean.
- The disabled and timeout sentinel envelopes preserve the same key set as the success envelope (good for agent ergonomics and cache stability of the tool-result shape).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — RLIMIT_AS integration test asserts nothing about the cap

- **Severity:** HIGH
- **Source:** adversary
- **File:** tests/test_handlers_lean_verify.py:702
- **What:** `TestRealLeanRepl::test_real_rlimit_as_bounds_high_allocation` submits the snippet `def m3_alloc := List.range 1000` and asserts `result["status"] in {"ok", "error", "sorry"}`. `List.range 1000` allocates ~1k cons cells (kilobytes), well below the configured 4 GiB cap and below any plausible Lean baseline RSS — it does not exercise RLIMIT_AS at all. The assertion passes trivially even if `preexec_fn` is never attached, even if `_resource is None`, even if RLIMIT_AS is broken upstream.
- **Why it matters:** The brief AC reads literally "`@requires_lean_repl` test asserts high-allocation snippet is bounded." The closest test currently asserts nothing about boundedness — it would green-light a regression that fully removes the cap. This is the regression guard that closes the m2 critique F4 carry-forward; without a meaningful assertion, F4 effectively re-opens on the next refactor.
- **Proposed fix:** Either (a) set a deliberately small per-test cap (e.g. spawn the REPL with `rlimit_as_bytes=512 * 1024 * 1024` — 512 MiB, below Lean's typical mmap'd olean footprint) and assert the subprocess fails with a kernel/allocation error rather than OOM-killing the parent, OR (b) submit a snippet that demonstrably allocates above the cap (e.g. `def x := (List.range 100000000).map (· + 1)` while running at the 512 MiB cap) and assert `status == "error"` or `lean_status == "timeout"`. Both forms force the test to fail when the preexec_fn is removed.
- **Regression guard:** The test rewritten per above IS the regression guard. Pair it with a unit-level assertion that `_FakeProcess` captures the actual `cap` value reaching `setrlimit` (currently only `callable(preexec_fn)` is asserted — the cap integer is not).

### F2 — Frozen `lean_verify_result.json` schema is not enforced against real handler output

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/schemas/lean_verify_result.json:42
- **What:** The new schema declares `messages[*].severity: {enum: ["error", "warning", "info"]}`, `messages[*].text: {type: "string"}`, and `sorry_goals[*].goal: {type: "string"}`. `_normalize_response` in `server/handlers/lean_verify.py:107-123` passes the REPL's fields through verbatim with only `m.get(..., default)` — no enum-clamping, no type-coercion. If `leanprover-community/repl` ever emits `severity="trace"` (Lean does have a trace category internally) or returns a non-string `data` / `goal` (structured proof state objects are an active upstream RFC), the handler will produce a payload that violates the frozen schema. No test loads the schema and validates a sample response against it (Draft7Validator is imported and used in `tests/test_snippet_contract.py` for `search_papers_result.json` but no analogous test exists for `lean_verify_result.json`).
- **Why it matters:** The schema is purely documentary today. The whole point of a frozen result-row schema is to detect drift between the upstream REPL protocol and the handler's mapping — without a conformance test the schema is a comment, not a contract. The m3 brief calls this out: "frozen result-row schema file added."
- **Proposed fix:** Add a `TestLeanVerifyResultSchema` class in `tests/test_handlers_lean_verify.py` that loads `server/schemas/lean_verify_result.json`, constructs `Draft7Validator(schema)`, and validates the handler's output for: the clean compile, the type-error path, the sorry path, the syntax_only path, the disabled envelope, the timeout envelope, and the generic-error envelope. Additionally, in `_normalize_response`, clamp `severity` to `{"error", "warning", "info"}` (default unknown → "error" since unknown is the safer default — "warning" or "info" would silently downgrade), and coerce `m.get("data")` / `s.get("goal")` to `str(...)` so a non-string upstream payload becomes a string rather than a schema-violating slot.
- **Regression guard:** The `TestLeanVerifyResultSchema` Draft7Validator-based test IS the guard. It fires whenever the handler emits a schema-violating envelope.

### F3 — Timeout detection relies on substring match on the exception message

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/handlers/lean_verify.py:302
- **What:** The handler discriminates the timeout path with `if "timeout" in str(exc).lower()`. The upstream `LeanReplError` message in `server/lean_repl.py:275` is currently `f"Lean REPL query exceeded the {timeout}s timeout."` — works today. But the same error class is also raised at `lean_repl.py:265-268` ("Lean REPL process has exited") and `lean_repl.py:299-302` ("Lean REPL closed stdout before returning a response") and `lean_repl.py:327-329` ("returned a non-JSON response"). Future contributors who reword "exceeded the {timeout}s" to "deadline reached" or "wait_for cancelled" will silently break the kill+respawn path — the handler will fall through to the generic-error envelope and leave the wedged REPL serving stale stdout to every subsequent call. That is the exact m2-critique-F4 / m3-promised contract failure mode.
- **Why it matters:** Sentinel-via-string-match is a known foot-gun pattern; the lean-sandbox-design.md "Per-query timeout" row promises kill+respawn-on-timeout as the m3 deliverable, and a substring-coupled discriminator is brittle.
- **Proposed fix:** Add a `LeanReplTimeoutError(LeanReplError)` subclass in `server/lean_repl.py` and raise it from the `TimeoutError → LeanReplError` chain at line 273-276. In `server/handlers/lean_verify.py`, catch `LeanReplTimeoutError` as a distinct `except` arm BEFORE the broader `except LeanReplError`. ~10 LOC; preserves backward compatibility (a `LeanReplTimeoutError` IS a `LeanReplError`).
- **Regression guard:** A new test that raises a non-timeout `LeanReplError` with the word "timeout" elsewhere in the message (e.g. `LeanReplError("non-JSON response after the 30s timeout window")`) and asserts the handler returns the generic-error envelope, not the timeout-respawn envelope. Today this test would FAIL — the substring would match and the handler would erroneously kill+respawn.

### F4 — Respawn-failure path swallows all exceptions silently

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/handlers/lean_verify.py:320
- **What:** When `LeanRepl.spawn_from_config(resources.config)` fails inside the timeout path, the `except Exception:` arm logs via `logger.exception(...)` and sets `resources.lean_repl = None`. This is a bare-catch of every exception type — `KeyboardInterrupt` excluded by Python's hierarchy, but `SystemExit`, `MemoryError`, `asyncio.CancelledError`, and any platform-specific subprocess error are all swallowed. `CancelledError` in particular MUST propagate (asyncio task cancellation is broken if any task swallows it). The docstring on `LeanRepl.spawn_from_config` documents that it raises `LeanUnavailableError` on toolchain absence — catching only that subclass would be more precise.
- **Why it matters:** Mutating `resources.lean_repl = None` on a `CancelledError` corrupts global state: a cancelled task running at the wrong instant leaves the server permanently in the disabled path until restart. The disabled-path return ALSO obscures real toolchain failures from observability — the operator gets a `lean_status="timeout"` response, not a `lean_status="disabled"` one, even though the next call WILL fall through to disabled.
- **Proposed fix:** Narrow `except Exception:` to `except (LeanUnavailableError, OSError):` (the documented + plausible failure surface). For `asyncio.CancelledError` specifically, re-raise — never swallow. Same fix at line 314 (the close path swallow). 8 LOC.
- **Regression guard:** A test that injects `asyncio.CancelledError` from a monkeypatched `LeanRepl.spawn_from_config` and asserts the cancellation propagates rather than being absorbed.

### F5 — `_normalize_position` accepts negative integers, violating schema `minimum: 0`

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/handlers/lean_verify.py:83-90
- **What:** `_normalize_position` returns `{"line": int(line), "column": int(column)}` whenever `line`/`column` are integers, with NO lower bound. The schema at `server/schemas/lean_verify_result.json:35-36` declares both fields as `type: integer, minimum: 0`. Lean shouldn't emit negatives, but a future REPL build that 1-indexes vs 0-indexes badly, or any wrapper that subtracts an offset, could trivially emit `-1`. With no Draft7Validator test (F2) the violation would ship.
- **Why it matters:** Two latent integrity layers (schema declared, handler ignored) means a real schema-conformance test is the only thing that would catch the drift; with F2 fixed, F5 becomes a trivially testable invariant.
- **Proposed fix:** In `_normalize_position`, clamp via `max(0, int(line))` and `max(0, int(column))`. 2 LOC.
- **Regression guard:** Unit test `test_normalize_position_clamps_negatives`: `_normalize_position({"line": -1, "column": -2}) == {"line": 0, "column": 0}`.

### F6 — `_disabled_envelope` and `_timeout_envelope` are not covered by the integration shape contract

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/handlers/lean_verify.py:162-195
- **What:** Both sentinel envelopes return a dict with 8 keys (status, lean_status, mode, messages, sorry_goals, goals_remaining, proof_state, compilation_success) — which is then wrapped by `envelope(...)` adding `corpus_version`. The schema requires those 9 fields PLUS `corpus_version` — the schema currently `required` list is the 9 fields *without* `corpus_version` (line 94-104 of the schema). Cross-check: the schema's `properties` block includes `corpus_version` (line 12-15) and `additionalProperties: false` (line 4). So a real envelope WITH corpus_version validates fine — but a hand-written `_disabled_envelope` missing any one of the 9 required fields would not be caught by any test today (see F2 — no Draft7Validator runs against the disabled / timeout outputs in the test file's existing assertions; the tests assert specific subsets, not full-schema conformance).
- **Why it matters:** The disabled and timeout paths are the agent's most fragile contract surface (they fire on operator misconfiguration and runtime failure, exactly when the agent most needs a parseable response). A drift in field shape there is exactly what the schema is meant to prevent.
- **Proposed fix:** Once F2 is in (Draft7Validator test), explicitly assert disabled / timeout / generic-error envelopes pass full-schema validation. Add the missing assertion as part of F2's fix rather than as a separate change.
- **Regression guard:** Subsumed by F2's `TestLeanVerifyResultSchema` if the test cases include the disabled, timeout, and generic-error envelopes (recommended above).

### F7 — Schema `description` claims a byte-stability test that does not exist for this file

- **Severity:** LOW
- **Source:** adversary
- **File:** server/schemas/lean_verify_result.json:5
- **What:** The schema's top-level `description` reads "The byte-stability test in E06_S06 hashes this file's bytes and pins the SHA-256". E06_S06's hash (`EXPECTED_TOOL_SCHEMA_SHA256` in `tests/test_server_tool_schema.py`) covers the canonical `tools/list` response JSON — NOT this result-row schema file. A hash test for `search_papers_result.json`'s bytes also does not exist (only the `version` field is cross-checked). The description is inherited verbatim from `search_papers_result.json` and is misleading.
- **Why it matters:** Documentation drift. The implementer (or a reader) might assume edits to `lean_verify_result.json` are caught by a hash test when in fact only the `version` field is pinned.
- **Proposed fix:** Either (a) reword the description to match reality ("The `version` field is cross-checked against `server.tools.TOOL_SCHEMA_VERSION` by `tests/test_handlers_lean_verify.py::test_schema_version_matches_tool_schema_version`. There is no byte-hash pin on the file itself today."), OR (b) add a hash pin test that hashes the file bytes the same way `EXPECTED_TOOL_SCHEMA_SHA256` does for `tools/list`. Option (a) is the LOW-cost fix; option (b) is a follow-up if the project wants the same byte-stability contract on result-row schemas as on the tool-list envelope.
- **Regression guard:** Description correctness is verified by reading the file; no automated guard required for the doc-only fix.

### F8 — `MAX_IMPORTS` validation is enforced only by Pydantic, not by the defense-in-depth loop

- **Severity:** LOW
- **Source:** adversary
- **File:** server/handlers/lean_verify.py:278-287
- **What:** The Pydantic `Field(max_length=MAX_IMPORTS)` on `imports` caps the list length to 64 when invoked through FastMCP. The "defense-in-depth" loop at lines 282-287 only checks per-line length and string type — NOT the list length. A direct call to `handle_lean_verify(snippet="...", imports=["x"] * 100000)` (the same "non-FastMCP caller" path the docstring explicitly motivates the loop for) would skip the list-length cap. The handler would happily build a 100k-import preamble and ship it to the REPL.
- **Why it matters:** The docstring at line 281 explicitly justifies the loop with "this catches a non-FastMCP caller path" — but the loop is incomplete relative to that justification.
- **Proposed fix:** Add `if len(imports_list) > MAX_IMPORTS: raise ValueError(...)` immediately before the per-line loop. 3 LOC.
- **Regression guard:** Unit test `test_oversize_imports_list_rejected` analogous to `test_oversize_import_line_rejected` — pass `imports=["x"] * (MAX_IMPORTS + 1)` and assert `ValueError`.

## What was done well

- BP1 cache discipline executed by the book: `TOOL_SCHEMA_VERSION` bumped 11→12 BEFORE the `--update-tool-schema-hash` regeneration (F2 anti-decorative-version guard satisfied), `EXPECTED_TOOL_SCHEMA_SHA256` re-pinned, paired `EXPECTED_BP1_SHA256` re-pinned in `tests/test_prompts.py` in the same commit (the m1 paired-update pattern).
- `LEAN_VERIFY` appended at the END of `ALL_TOOLS` (not inserted mid-tuple) — preserves every prior tool's slot ordering and minimizes the hash delta surface to genuinely new tool bytes.
- `LEAN_VERIFY.description` is a fully-literal multi-line constant string with no f-string interpolation; `test_lean_verify_in_all_tools` asserts the absence of `{` as a frozen-description guard.
- Graceful disabled path (`status="unavailable"`, `lean_status="disabled"`, no 5xx) mirrors the m1 `citations.py::graph_status="absent"` precedent exactly — same agent ergonomics, same key set, no surprise envelope shape.
- POSIX/Windows split for RLIMIT_AS is correctly defended at TWO sites: the `try: import resource` ImportError guard at module top AND the `sys.platform != "win32"` runtime guard before attaching `preexec_fn`. Both guards are required (Windows has the import-fail path AND the create_subprocess_exec ValueError path).
- The new `Config.lean_rlimit_as_bytes` field has a sane default (4 GiB) backed by reasoning in the field docstring (Lean kernel + oleans easily mmap hundreds of MB) — generous enough for steady-state, bounded enough that `List.range 10_000_000` is caught.
- The `_build_command` declaration-vs-term split (`#check (term)` vs `set_option maxHeartbeats 5000 in <decl>`) is documented in both the handler docstring AND the tool description visible to the agent — the synthesis Open Question 1 is resolved cleanly.
- Threat-3 "bound subprocess input" cap (D2 — `MAX_SNIPPET_LEN=16 KiB`, `MAX_IMPORT_LINE_LEN=256`, `MAX_IMPORTS=64`) is an unrequested-but-justified defensive add; the per-line check at lines 282-287 IS the "defense-in-depth" the docstring promises (though F8 notes the list-length omission).
- Test coverage is dense: 22 always-run handler tests + 3 spawn-guard tests across the POSIX/Windows split, plus the 4 `@requires_lean_repl` integration tests. The structure (Tier 1a registration / 1b _build_command / 1c _normalize_response / 1d handler / Tier 2 spawn guard / Tier 3 real REPL) is the most legible test-suite layout in the milestone notes so far.
- The `test_no_rlimit_means_no_preexec_fn` test (rlimit=0/None) is an important negative-case guard — without it, the `if rlimit_as_bytes and ... and ...` chain could be silently broken by removing one term and the POSIX-cap test would still pass.

## Recommended rectification order

1. **F1** (test asserts nothing about the cap) — highest leverage: the RLIMIT_AS-bounds AC is the m2 critique F4 carry-forward, and the test today would pass even with the cap fully removed. Rewriting to a real bounded-allocation assertion takes ~20 LOC and one test.
2. **F2** (no Draft7Validator on lean_verify_result.json) — second-highest leverage: a JSON Schema validation test for the handler's output is the contract guard that the whole "frozen result-row schema" mechanism depends on. Pairs with F5 and F6 below.
3. **F3** (substring-match on timeout) — small change (~10 LOC), localized to `lean_repl.py` + `lean_verify.py`. Adds a `LeanReplTimeoutError` subclass; future reword-resistant.
4. **F4** (bare-catch swallows CancelledError) — narrow the `except Exception:` to specific subclasses. ~8 LOC; pairs naturally with F3 since both touch the timeout-path error handling.
5. **F5** (negative-position clamp) — 2 LOC. Becomes meaningful only once F2's Draft7Validator test is in place.
6. **F6** (sentinel envelope full-schema coverage) — subsumed into F2's fix if the test cases include the disabled / timeout / generic-error envelopes (mark complete when F2 lands).
7. **F8** (MAX_IMPORTS list-length defense-in-depth) — 3 LOC. Pairs with F2 (any envelope-shape test makes the input-validation surface easier to round-trip).
8. **F7** (schema description claims a byte-stability test that does not exist) — doc-only fix. Reword or add a real byte-hash test; LOW priority.

## Rectification status (filled by Phase 4)

Rect commit closes F1–F8 (every finding); zero deferred. **Zero findings
invalidated** on the Phase-4 re-verify gate — every cited `file:line` still
matched the diff (0% invalidation rate, well under the 40% heuristic).

- F1 (HIGH) — **fixed.** `tests/test_handlers_lean_verify.py`:
  `test_real_rlimit_as_bounds_high_allocation` rewritten as
  `test_real_rlimit_as_bounds_subprocess`. Spawns a fresh REPL at a
  deliberately tight 32 MiB cap (below Lean's baseline RSS) and asserts the
  trivial query either raises `LeanReplError` (subprocess crashed under the
  cap) or returns `status in {error, timeout, unavailable}` — `status == "ok"`
  is the failure signal. **Companion unit assertion** in
  `TestSpawnRlimitGuard::test_posix_attaches_preexec_fn`: `inspect.getclosurevars`
  reads the closure's `cap` and asserts the integer cap actually reaches the
  setrlimit closure.
- F2 (HIGH) — **fixed.** New `TestLeanVerifyResultSchema` class (7 tests)
  validates every handler envelope (clean / type-error / sorry / syntax_only /
  disabled / timeout / generic-error) against the frozen schema via
  `jsonschema.Draft7Validator`. Handler-side: `_normalize_response` now
  clamps `severity` to the schema enum (default "error" for unknown — the
  safer side; silent downgrade to "info" would mask diagnostics) AND coerces
  `messages[*].text` + `sorry_goals[*].goal` to `str(...)` so a future REPL
  emitting structured proof-state objects becomes a string rather than a
  schema-violating slot.
- F3 (MEDIUM) — **fixed.** New `LeanReplTimeoutError(LeanReplError)`
  subclass in `server/lean_repl.py`; raised from the `TimeoutError` chain
  in `LeanRepl.query`. Handler catches `LeanReplTimeoutError` as a distinct
  `except` arm BEFORE `except LeanReplError`. Substring-match on the
  message is gone. Guard: `TestTimeoutDiscriminatorIsTypeNotSubstring` —
  raises a non-timeout `LeanReplError` whose message contains the word
  "timeout"; asserts the handler routes through the generic-error envelope
  and does NOT close the REPL.
- F4 (MEDIUM) — **fixed.** `server/handlers/lean_verify.py` timeout path:
  `except Exception:` narrowed to `except (OSError, LeanReplError)` on the
  close arm and `except (LeanUnavailableError, OSError)` on the respawn
  arm. `asyncio.CancelledError` now propagates. Guard:
  `TestRespawnFailureNarrowExcept::test_cancelled_error_during_respawn_propagates`.
- F5 (MEDIUM) — **fixed.** `_normalize_position` clamps negative
  integers to `0` (`max(0, int(line))` / `max(0, int(column))`). Guard:
  `TestPositionClampsNegatives` (helper-level + via `_normalize_response`).
- F6 (MEDIUM) — **subsumed by F2.** The new `TestLeanVerifyResultSchema`
  suite includes `test_disabled_envelope_conforms`,
  `test_timeout_envelope_conforms`, and `test_generic_error_envelope_conforms`
  — every sentinel envelope now Draft7Validator-conforms.
- F7 (LOW) — **fixed.** `server/schemas/lean_verify_result.json`'s top-level
  `description` reworded to match reality: cross-checked by
  `TestToolRegistration::test_schema_version_matches_tool_schema_version` +
  the new `TestLeanVerifyResultSchema` Draft7Validator suite; no byte-hash
  pin on the file bytes today (E06_S06's hash covers the canonical
  `tools/list` JSON, not this result-row schema). Option (a) from the
  proposed fix — the LOW-cost reword.
- F8 (LOW) — **fixed.** `handle_lean_verify` enforces
  `len(imports_list) > MAX_IMPORTS → ValueError(...)` BEFORE the per-line
  loop. Guard:
  `TestImportsListLengthDefenseInDepth::test_oversize_imports_list_rejected`.
