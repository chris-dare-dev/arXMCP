# Critique — E08_S01

**Critic:** adversary
**Generated:** 2026-05-10T03:55:16Z
**Commit range:** 7ee930145323ed1533460fcd39dc209af2fb7913..31ba2114bb9c9f093de3487787735a4ca0c6bd57
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict: SHIP-WITH-FIXES. Implementation is clean, tests are dense, and the four brief ACs pass; but the YAML loader has zero defenses against ReDoS, and a small set of test/contract gaps would let real regressions ship silently. 0 CRITICAL, 2 HIGH, 7 MEDIUM, 3 LOW.
- Highest-risk file: `server/router.py:217-229` — `_load_and_compile` accepts any compilable regex without latency/complexity validation. A future YAML edit with `(a*)*b` blows the 1 ms budget by 4 orders of magnitude on 28 chars of adversarial input (measured: 17.9 s). The 200-char prefix slice does NOT save you here.
- `classify(b"prove this")` silently returns `LOOKUP` instead of `SYNTHESIS` (`server/router.py:135-137` `_canonicalize` does `isinstance(q, str)` check). Bytes-shaped input is not exotic; the orchestrator may pass through wire bytes unconverted at some integration point.
- The "no hardcoded patterns in router.py" guard (`tests/test_router.py:319`) only checks 3 of the 19 patterns; a future change hardcoding `r"\bsketch\b"` or `r"\bverify\b"` is undetected. The AC #6 invariant the test claims to defend is mostly aspirational.
- The brief's stated priority order `AUTOFORMALIZATION > VERIFICATION > LOOKUP > SYNTHESIS` (synthesis D4) is encoded ONLY in YAML insertion order. No assertion in code or tests pins the per-tag *block boundaries*: the `TestPriorityOrder` cases catch a few cross-tag swaps but not, e.g., re-ordering `LOOKUP` patterns above `VERIFICATION` patterns within the YAML.
- The latency test exercises a no-match worst case but uses repeated-`x` filler; it does NOT exercise unicode-heavy queries (NFC normalization cost) nor catastrophic-backtracking-resistance on the *current* patterns. The 1 ms budget is observed in steady-state; a regex-complexity guard would future-proof the contract.
- Cross-axis pattern: every issue flagged is a *future-edit* hazard, not a today-bug. The router as-shipped behaves correctly on the brief's ACs; the gaps are in the editorial-safety net for the YAML, which is the entire premise of "edit-without-touching-Python".
- Cache byte-stability axis (BP1): clean — `RouteTag` values never appear on the wire to the model (`.claude/notes/07-multi-agent-caching.md:74` BP1 = system prompt + tool defs only); orchestrator consumption is downstream of the breakpoint.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — `_load_and_compile` has no ReDoS / regex-complexity guard

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/router.py:217-229
- **What:** `_load_and_compile` accepts any regex that `re.compile` swallows. A future YAML edit adding e.g. `(a*)*b` or `(a+)+\$` would compile fine but exhibit catastrophic backtracking on adversarial input. Measured locally on `python3.12`: pattern `(a*)*b` against `'a'*28` takes 17.9 seconds (budget: 1 ms; ratio: 17,900x). The 200-char prefix slice (`server/router.py:138`) does NOT prevent this — exponential growth fits inside 200 chars at trivial input lengths.
- **Why it matters:** The brief's stated H1 closure ("makes routing behavior deterministic and auditable" — risk note) and the 1 ms latency contract (AC #4) are both violated by a single line of YAML that no test catches. `.claude/notes/08-security-observability-ops.md` has no ReDoS guidance, so the absence is unguarded by a project convention either. The classifier sits on the request hot path; a hung classify() on adversarial user input is a request-thread DoS.
- **Proposed fix:** In `_load_and_compile`, after `re.compile`, run a synthetic worst-case test: time `pattern.search` on `'a' * 200` with a hard deadline (e.g. `signal.SIGALRM` with 5 ms timeout, or thread+join with timeout). Reject any pattern that exceeds 5 ms on this synthetic input. Alternatively (cheaper, less complete): forbid `+` and `*` quantifiers nested inside groups via a static regex over the regex-source string (e.g. reject patterns matching `r"\([^)]*[+*][^)]*\)[+*]"`). Document the rejection rule in the YAML header.
- **Regression guard:** `TestImportTimeValidation::test_redos_pattern_rejected` — write a synthetic YAML with `(a*)*b`, assert `_load_and_compile` raises `RuntimeError` matching `"backtracking"` or `"complexity"`.

### F2 — `classify(bytes)` silently returns `DEFAULT_TAG` instead of decoding

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/router.py:135-137
- **What:** `_canonicalize` does `if not isinstance(query, str): return ""`. `classify(b"prove this")` therefore returns `LOOKUP` instead of `SYNTHESIS`. Verified locally: `classify(b"prove this") == RouteTag.LOOKUP`; `classify("prove this") == RouteTag.SYNTHESIS`. The brief is silent on bytes input but the orchestrator (E08_S04+) consumes router output from a wire-borne MCP request; a single bytes-vs-str regression in an upstream caller silently misroutes every query.
- **Why it matters:** "Defensive return DEFAULT_TAG" is correct for `None` / numeric input where a string conversion is meaningless. For `bytes`, however, a silent decode is the standard contract (every Python wire-protocol library does it). Returning `DEFAULT_TAG` here makes a real input shape look like a no-match and disguises the bug from observability — there is no metric or log line that says "saw bytes, fell back".
- **Proposed fix:** In `_canonicalize`, before the `isinstance` check, add `if isinstance(query, (bytes, bytearray)): query = query.decode("utf-8", errors="replace")`. Then proceed as today. Add a log-warn for bytes input so observability sees the upstream bug.
- **Regression guard:** `TestDefensiveInput::test_bytes_input_decodes_utf8` — assert `classify(b"prove this") is RouteTag.SYNTHESIS` and `classify(b"\xff\xfe\xfd") is DEFAULT_TAG` (invalid utf-8 → empty after errors=replace).

### F3 — `test_no_hardcoded_patterns_in_router_module` checks only 3 of 19 patterns

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_router.py:319
- **What:** The guard for AC #6 ("editing YAML does NOT require touching router.py") iterates over a hardcoded tuple `(r"\bprove\b", r"\bdefin", r"\blean\b")`. A future edit that hardcodes any of the *other 16* patterns (e.g. `r"\bsketch\b"`, `r"\bverify\b"`, `r"\bmathlib\b"`, `r"\bproof\b"`, `r"\bcorrect\b"`, `r"\bnotation\b"`) is not caught.
- **Why it matters:** AC #6 is a load-bearing architectural invariant — the YAML is the source of truth. The current test gives a false sense of coverage; it would pass even if 80% of patterns were duplicated into `router.py`.
- **Proposed fix:** Replace the needle-list approach with a structural assertion: parse `server/router.py` AST, assert no `re.compile(...)` call exists at module level, OR assert no `\b...\b` regex literal exists anywhere in the file's string literals. The simpler version: derive needles dynamically from the YAML — load `router_patterns.yaml`, iterate every pattern's `regex` value, assert none of those literal strings appear in `router.py`'s text.
- **Regression guard:** the test as rewritten IS the regression guard.

### F4 — Priority order is encoded only as YAML insertion order; no test pins block boundaries

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_router.py:407-441 (TestPriorityOrder) and server/router_patterns.yaml
- **What:** Synthesis D4 says priority is `AUTOFORMALIZATION > VERIFICATION > LOOKUP > SYNTHESIS`. This is documented in the YAML header (lines 11-22) but encoded ONLY as YAML insertion order. The `TestPriorityOrder` class has 6 cases that catch some cross-tag swaps, but it does NOT catch in-block reorderings (e.g. moving the LOOKUP `\bdefin(e|ition)\b` pattern to position 0 above the AUTOFORMALIZATION block). It also does not assert *block-level invariants* — that all AUTOFORMALIZATION patterns precede all VERIFICATION patterns, etc.
- **Why it matters:** The pattern file is the editable surface. A maintainer following the YAML header rules is fine; a maintainer who appends a new AUTOFORMALIZATION pattern at the bottom of the file silently demotes it below LOOKUP and SYNTHESIS, breaking the priority contract. The test should fail in that case.
- **Proposed fix:** Add `TestPriorityOrder::test_yaml_block_order_invariant`: walk `_COMPILED_PATTERNS` once, extract the per-entry `RouteTag`, assert the sequence of tags maps to the priority `[AUTOFORMALIZATION...] + [VERIFICATION...] + [LOOKUP...] + [SYNTHESIS...]` (i.e. monotonically non-increasing under the priority key).
- **Regression guard:** as above.

### F5 — `test_no_hardcoded_patterns_in_router_module` uses CWD-relative path

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_router.py:313-315
- **What:** `Path("server/router.py").resolve()` resolves against the CWD. Verified locally: from `/tmp` this resolves to `/private/tmp/server/router.py` and `is_file()` is False — but the test reads `text = router_src.read_text(encoding="utf-8")` *without* checking existence first, so an `FileNotFoundError` would surface. If pytest is invoked from a different CWD (some CI configurations do `cd tests/`), the test errors instead of asserting.
- **Why it matters:** AC #6's protection silently breaks across CWDs; the test becomes flaky-by-environment.
- **Proposed fix:** Replace with `Path(__file__).resolve().parent.parent / "server" / "router.py"` (CWD-independent), or even better: `import server.router; router_src = Path(server.router.__file__)`.
- **Regression guard:** running `pytest tests/test_router.py::TestPatternFileSourceOfTruth -v` from `/tmp` should pass after the fix.

### F6 — Latency budget test does not exercise unicode-heavy queries

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_router.py:259-294
- **What:** `TestLatencyBudget` uses `"x " * 100` as the worst-case query — pure ASCII, trivial NFC. NFC normalization (`server/router.py:139`) on a 200-char query of decomposed Unicode (e + combining accents) is materially more expensive than ASCII. AC #4 says "any 200-character prefix" — the test does not measure the truly worst case.
- **Why it matters:** The brief's AC literally promises <1 ms for ANY input, including Unicode. A future regex pattern using lookaround on Unicode-heavy text could push the budget. The test gives a false confidence by measuring only the easy case.
- **Proposed fix:** Add `test_classify_under_1ms_on_decomposed_unicode`: build a 200-char query of 100 occurrences of `"é "` in DECOMPOSED form (`"é " * 67` truncated to 200 chars), assert mean over 1000 iterations < 1 ms.
- **Regression guard:** as above.

### F7 — `_load_and_compile` accepts non-string `rationale` field silently

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/router.py:197-216
- **What:** Validation enforces `regex` must be a string (`server/router.py:218-222`) but does NOT validate the type of `rationale`. A YAML entry like `rationale: 42` or `rationale: null` passes import. The brief says rationale is "annotated with the rationale for each pattern" and the implementation summary calls it "part of the audit trail" — accepting null breaks the audit-trail premise.
- **Why it matters:** Silent acceptance of malformed `rationale` defeats the editorial-review premise (a pattern with no rationale should not pass review). Catching it at import shifts the cost from human reviewer to validator.
- **Proposed fix:** Add `if not isinstance(entry["rationale"], str) or not entry["rationale"].strip():` after the regex-type check; raise `RuntimeError` matching `"rationale must be a non-empty string"`.
- **Regression guard:** `TestImportTimeValidation::test_empty_rationale_raises` and `test_non_string_rationale_raises`.

### F8 — `_load_and_compile` permits extra keys in YAML entries

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/router.py:203-209
- **What:** The validation uses `_REQUIRED_KEYS - set(entry.keys())` to detect missing keys, but does NOT reject extra keys. A YAML entry like `{tag: LOOKUP, regex: 'foo', rationale: 'x', priority: 99}` passes validation, and the `priority` field is silently ignored. This is the exact failure mode the brief's "no LLM, no implicit semantics" stance exists to prevent.
- **Why it matters:** A future maintainer adding what they think is a meaningful field ("priority", "weight", "disabled") gets no signal that the field is ignored. Editorial confusion is the failure mode.
- **Proposed fix:** Replace the `missing` check with a strict equality: `extra = set(entry.keys()) - _REQUIRED_KEYS; if extra or missing: raise RuntimeError(f"router_patterns.yaml[{idx}] keys must be exactly {sorted(_REQUIRED_KEYS)}, got missing={sorted(missing)}, extra={sorted(extra)}")`.
- **Regression guard:** `TestImportTimeValidation::test_extra_keys_rejected`.

### F9 — Multi-line `rationale` values via YAML `|` block scalar carry trailing newline

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/router_patterns.yaml:50-52 (and 16 other entries)
- **What:** Every rationale uses YAML `|` (literal block scalar). YAML preserves the trailing newline on `|` (chomping indicator absent). Consumers reading `rationale` get strings ending in `"\n"`. Today there are no consumers; the moment a downstream observability tool starts logging rationales (entirely the point of the audit trail), the trailing newlines pollute logs.
- **Why it matters:** Latent foot-gun. The audit-trail premise (rationales surfaced for review) requires clean strings.
- **Proposed fix:** Change `|` to `|-` (chomping indicator: strip trailing newline) in all 19 entries, OR strip in `_load_and_compile` after read. The loader-side fix is more defensive: `entry["rationale"].strip()`.
- **Regression guard:** `test_rationale_no_trailing_whitespace` over `_COMPILED_PATTERNS` (would require exposing rationale on the compiled tuple — currently dropped).

### F10 — Compiled pattern tuple drops `rationale` — audit trail unrecoverable at runtime

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/router.py:230, 246-248
- **What:** `_load_and_compile` returns `tuple[tuple[re.Pattern, RouteTag], ...]` — `rationale` is validated at import then discarded. The implementation summary says rationale is "part of the audit trail" but no runtime API exposes it. A downstream observability hook ("tag X was chosen because pattern Y matched, whose rationale is Z") cannot be implemented without re-parsing the YAML.
- **Why it matters:** The audit trail premise (per E08-agent-runtime narrative + brief "annotated with the rationale") is not actually reachable from the runtime. This is a design gap, not a correctness bug; flagging at MEDIUM because the YAML *is* version-controlled and human-readable, so the audit is recoverable, just not programmatic.
- **Proposed fix:** Change the compiled tuple to `tuple[tuple[re.Pattern, RouteTag, str], ...]`; expose a (private) `_classify_with_rationale(query) -> tuple[RouteTag, str | None]` for observability. Public `classify` API unchanged.
- **Regression guard:** `test_classify_with_rationale_returns_pattern_rationale_on_match`.

### F11 — `re.IGNORECASE` is redundant given all-lowercase YAML patterns

- **Severity:** LOW
- **Source:** adversary
- **File:** server/router.py:224
- **What:** Every YAML pattern is lowercase (`\bmathlib\b`, `\blean\b`, etc.) and `_canonicalize` preserves case. The `re.IGNORECASE` flag adds matching cost (small) without behavioral change today. Comment at `server/router.py:130-133` calls this "defense-in-depth" against an editor mistake — fair, but worth a note in the YAML header that all-lowercase is the convention.
- **Why it matters:** Documentation/style only; no bug.
- **Proposed fix:** Add a one-line note to the YAML schema header: "patterns SHOULD be lowercase; `re.IGNORECASE` is set as a safety net." OR remove `re.IGNORECASE` and add a validator that rejects mixed-case patterns.
- **Regression guard:** n/a (LOW).

### F12 — `RouteTag` is `StrEnum`; downstream consumers expecting `IntEnum` would break

- **Severity:** LOW
- **Source:** adversary
- **File:** server/router.py:87-100
- **What:** `RouteTag` values are uppercase strings ("LOOKUP" etc.). Downstream code (E08_S02 role prefixes, E08_S05 model selection) needs to know whether to expect `tag.value` (str) or `int(tag)` (would fail). Synthesis D6 explicitly chose `StrEnum` and downstream is expected to do `tag.name.lower()`. Documenting in the docstring would prevent the trap.
- **Why it matters:** Cross-milestone contract is documented in the synthesis but not in the public API surface (the `RouteTag` docstring).
- **Proposed fix:** Add to `RouteTag` docstring: "Downstream consumers should access `tag.value` (str, uppercase) or `tag.name.lower()` for the role-prefix key. Do NOT cast to int."
- **Regression guard:** n/a (LOW; documentation).

### F13 — `pyyaml>=6.0` declared as runtime dep but already transitively present

- **Severity:** LOW
- **Source:** adversary
- **File:** pyproject.toml:96
- **What:** Synthesis correctly notes pyyaml is already transitive via transformers/lancedb; pinning `>=6.0` in `[project] dependencies` is correct discipline (no hidden deps). However, the comment block does not name the *current* transitive minimum, so a downstream `pip install` resolution that pins `pyyaml<6.0` (e.g. an old transformers version) would silently downgrade and the `safe_load` call still works (safe_load is in pyyaml 3.x+). The CVE-2017-18342 footnote is correct but slightly misleading: that CVE is about `yaml.load` without Loader, not a pyyaml-version issue per se.
- **Why it matters:** Style/comment-clarity only.
- **Proposed fix:** None functional. Optionally tighten comment to: "pyyaml is required for `yaml.safe_load`; any version >= 5.1 supports the safe_load default-Loader. Pinned >= 6.0 to align with project convention."
- **Regression guard:** n/a (LOW).

## What was done well

- Module docstring is exemplary — names H1, cites the roadmap line, names the four roles with cross-references to `07-multi-agent-caching.md:66-67`, and explicitly states the misrouting-is-quality-not-correctness contract.
- Eager module-level compilation (`_COMPILED_PATTERNS`, `server/router.py:246-248`) is the correct pattern for the 1 ms budget. Mirrors the `ingest/chunker.py` precedent cited in synthesis D2.
- Defensive input handling — `None`, non-`str`, empty, whitespace-only all return `DEFAULT_TAG` rather than raising. Tested in `TestDefensiveInput`. Aligned with the brief's misrouting-is-quality stance.
- YAML header (`server/router_patterns.yaml:1-42`) documents the priority rule, the schema, AND the canonicalization pre-processing. A maintainer can edit safely without reading any Python.
- Import-time validation surface is comprehensive within its scope: 8 distinct failure modes (`TestImportTimeValidation`) all raise `RuntimeError` with a typed message that names the offending file path. Server startup will fail loudly, not silently misroute.
- `_canonicalize` does NOT lowercase, deferring to `re.IGNORECASE`. This preserves the original repr for debugging — a thoughtful choice documented inline.
- Slice-before-normalize is correct (synthesis D3): O(1) prefix slice keeps the unicode normalization step bounded regardless of input size. Brief says "first 200 characters", correctly interpreted as pre-normalization.
- `pyyaml` declared explicitly in `pyproject.toml` with a CVE footnote and a "no implicit deps" rationale — matches project discipline.
- `RouteTag` chosen as `StrEnum` (Python 3.11+) — JSON-serializable without a custom encoder, clean repr, downstream-friendly.
- Test coverage is dense (63 tests across 11 classes), brief AC #1/#2/#3 are present verbatim, and the ambiguous-cases class adds a 4th case beyond the brief's "≥3" requirement.

## Recommended rectification order

1. **F2** (HIGH, bytes input) — single-line fix in `_canonicalize`; ships an actual common-path bug-fix.
2. **F1** (HIGH, ReDoS guard) — design-level work but small (10-30 LOC for the synthetic-input timer + reject); guards the entire YAML-edit attack surface.
3. **F3** (MEDIUM, hardcoded-pattern guard) — replace 3-needle list with YAML-derived needles; ~10 LOC change, restores AC #6 protection.
4. **F4** (MEDIUM, priority-block invariant) — one new test asserting block-order monotonicity; 10 LOC.
5. **F5** (MEDIUM, CWD-relative path) — change one `Path("...")` to `Path(__file__)...`; 1 line.
6. **F8** (MEDIUM, extra-key rejection) — extend the missing-key check to also reject extras; 5 LOC.
7. **F7** (MEDIUM, rationale-type validation) — extend validator; 5 LOC + 2 tests.
8. **F6** (MEDIUM, unicode-heavy latency test) — one new test, no production change.
9. **F9** (MEDIUM, trailing newline in rationales) — strip in loader; 1 line.
10. **F10** (MEDIUM, audit-trail recoverability) — only if rectifier accepts the design expansion; otherwise defer.
11. **F11**, **F12**, **F13** (LOW) — defer or fold into a single docstring/comment commit.

## Rectification status (filled by Phase 4)

| ID | Severity | Status | Notes |
|---|---|---|---|
| F1 | HIGH | **fixed (with adjustment)** | Initially implemented as a thread-based timing probe (50 ms deadline on `'a'*200`); rejected at first run because `re` does NOT release the GIL during catastrophic backtracking — the daemon worker keeps burning CPU after the probe times out, leaking runaway threads across pytest's run and hanging the suite. **Replaced with a static-analysis check** via `_REDOS_NESTED_QUANTIFIER_RE = re.compile(r"\([^()]*[+*?][^()]*\)[+*?]")`, which catches the canonical nested-quantifier shapes `(a*)*`, `(a+)+`, `(.*)+`, `(a?)*`, etc. Less complete than a true regex parser (misses overlapping-alternation ReDoS like `(a\|a)*`) but safe and deterministic. New `TestReDoSGuard` class with 2 tests covers the four canonical shapes. |
| F2 | HIGH | **fixed** | `_canonicalize` now decodes `bytes` / `bytearray` via `utf-8` with `errors="replace"` BEFORE the `isinstance(query, str)` check. Invalid UTF-8 still degrades gracefully via the no-match path. New `TestBytesInput` class (5 tests) covers bytes routing to SYNTHESIS/LOOKUP/VERIFICATION + invalid-UTF-8 + UTF-8 with Unicode. |
| F3 | MEDIUM | **fixed** | `test_no_yaml_pattern_string_appears_in_router_source` now derives the needle list from the YAML at test time — every pattern in the YAML is checked against the router source. A future YAML edit adding a pattern that someone hardcoded in `router.py` is automatically caught. Renamed for clarity. |
| F4 | MEDIUM | **fixed** | New `_TAG_PRIORITY_RANK` dict in `router.py` (`AUTOFORMALIZATION=4 > VERIFICATION=3 > LOOKUP=2 > SYNTHESIS=1`). `_load_and_compile` walks the compiled list and asserts the tag-rank sequence is monotonically non-increasing — appending a high-priority tag at the bottom of the YAML now raises `RuntimeError` at import. New `TestBlockOrderInvariant` class with 3 tests. |
| F5 | MEDIUM | **fixed** | `test_no_yaml_pattern_string_appears_in_router_source` (was `test_no_hardcoded_patterns_in_router_module`) now uses `Path(server.router.__file__).resolve()` — CWD-independent. |
| F6 | MEDIUM | **fixed** | New `TestUnicodeLatency::test_classify_under_1ms_on_decomposed_unicode` builds a 200-char query of `"é "` (decomposed: e + U+0301 + space) and asserts mean latency over 1000 iterations stays <1 ms. NFC normalization cost is exercised on the worst case. |
| F7 | MEDIUM | **fixed** | `_load_and_compile` now validates `rationale` is a non-empty string. Empty / null / int / whitespace-only all raise `RuntimeError("non-empty string")`. New `TestRationaleValidation` class with 4 tests. |
| F8 | MEDIUM | **fixed** | `_load_and_compile` rejects EXTRA keys (not just missing). Error message is now "keys must be exactly {required}; got missing=[...], extra=[...]". Existing `test_missing_required_keys_raises` updated to match the new message. New `TestExtraKeyRejection::test_extra_key_raises` covers the `priority: 99` case from the critique. |
| F9 | MEDIUM | **deferred** | The YAML uses `\|` block scalars (with default chomping); rationale strings carry trailing newlines. Not currently exposed at runtime (F10 deferred); when the audit-trail-via-API observability lands, strip in the loader OR change `\|` to `\|-` in the YAML. Documented for the F10 follow-up. |
| F10 | MEDIUM | **deferred** | Audit-trail observability — exposing `rationale` at runtime via a `_classify_with_rationale` API — is a design expansion beyond the brief deliverables. Deferred to E08_S04+ when the orchestrator actually consumes the audit trail. The YAML rationale is still version-controlled and human-readable. |
| F11 | LOW | **deferred** | Documentation/style; `re.IGNORECASE` is documented as defense-in-depth in the source. |
| F12 | LOW | **deferred** | Documentation/style; the `RouteTag` `StrEnum` choice is documented in the class docstring. |
| F13 | LOW | **deferred** | Documentation/style; the `pyyaml>=6.0` rationale comment is correct. |

Suite at rectification: **1005 passed, 4 skipped, ruff clean** (was 988 pre-rect — +17 from new test classes).

Reverify pass: F1 was implemented twice — first as a timing probe (rejected because `re`'s GIL behavior leaks runaway threads on rejection — verified by hung pytest run), then as a static check. The static check covers the canonical nested-quantifier shape; sophisticated ReDoS via overlapping alternation is documented as out of scope. F2 was reproduced by `classify(b"prove this") == RouteTag.LOOKUP` before the fix, then `RouteTag.SYNTHESIS` after.

