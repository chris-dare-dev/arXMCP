# E08_S01 — Implementation summary

**One-line:** Fast Python regex query classifier returning a `RouteTag` enum (Lookup / Synthesis / Verification / Autoformalization). Patterns live in `server/router_patterns.yaml`; routing is sub-millisecond. Closes H1.

## Files

### NEW: `server/router.py` (~290 LOC)

- `RouteTag` enum (`enum.StrEnum`, Python 3.11+) with the four canonical values: `LOOKUP`, `SYNTHESIS`, `VERIFICATION`, `AUTOFORMALIZATION`. The set is closed at four for v1 — adding a fifth requires coordination with E08_S02 / E08_S05.
- `DEFAULT_TAG = RouteTag.LOOKUP` — default on no-match. Cheapest agent role; brief explicit that misrouting is a quality issue, not correctness.
- `MAX_QUERY_PREFIX_CHARS = 200` — pinned constant for the brief's "first 200 characters" rule.
- `_canonicalize(query)` — slice → NFC normalize → whitespace-collapse via `" ".join(s.split())`. NFC mirrors `server/query_encoder._canonicalize`. Does NOT lowercase (`re.IGNORECASE` flag on the compiled patterns handles case).
- `_load_and_compile(patterns_path)` — reads YAML via `yaml.safe_load` (CVE-2017-18342 closure), validates each entry has `{tag, regex, rationale}`, refuses unknown tags, refuses bad regexes, refuses zero-pattern files. Failures are `RuntimeError` at import.
- `_COMPILED_PATTERNS` — module-level immutable tuple of `(re.Pattern, RouteTag)` — compiled ONCE at import. Per-call `re.search` over this tuple, first-match wins.
- `classify(query) -> RouteTag` — public API. Defensive: `None`, non-`str`, empty, whitespace-only all return `DEFAULT_TAG` rather than raising.

### NEW: `server/router_patterns.yaml`

19 patterns across the four tags, top-down priority:

1. **AUTOFORMALIZATION** (highest): `\blean\b`, `\bmathlib\b`, `\bformalize\b`, `\btranslate\b.*\blean\b`
2. **VERIFICATION**: `\bverify\b`, `\bcheck\b`, `\bvalid(ate)?\b`, `\bcorrect\b`
3. **LOOKUP**: `\bwhat\s+is\b`, `\bdefin(e|ition)\b`, `\b(lemma|theorem|corollary|proposition)\s+\d`, `\bnotation\b`, `\bstate(ment)?\s+of\b`
4. **SYNTHESIS**: `\bprove\b`, `\bproof\b`, `\bshow\s+that\b`, `\bderive\b`, `\bsketch\b`

Each entry carries a `rationale` string for the audit trail. The YAML header documents the priority rule (AUTOFORMALIZATION → VERIFICATION → LOOKUP → SYNTHESIS) so a future editor doesn't accidentally re-sort.

### NEW: `tests/test_router.py` (~480 LOC, 63 tests)

10 test classes:
- **TestBriefAcceptanceCriteria** (3 tests) — brief AC #1, #2, #3 verbatim.
- **TestCanonicalLookup / Synthesis / Verification / Autoformalization** (6+5+5+5 = 21 parametrized) — ≥5 canonical examples per tag.
- **TestAmbiguousCases** (4 tests) — ≥3 ambiguous cases with documented expected behavior.
- **TestDefensiveInput** (6 tests) — None, non-string, empty, whitespace-only, no-match all return `DEFAULT_TAG`.
- **TestUnicode** (3 tests) — `étale`, `Poincaré`, NFC normalization equivalence.
- **TestLatencyBudget** (2 tests) — `timeit` mean over N=1000 on worst-case query (no-match) AND first-match query, both <1 ms.
- **TestPatternFileSourceOfTruth** (3 tests) — no hardcoded patterns in `router.py`; `PATTERNS_PATH` resolves; `MAX_QUERY_PREFIX_CHARS == 200`.
- **TestImportTimeValidation** (8 tests) — missing file, malformed YAML, top-level not list, missing required keys, unknown tag, bad regex, empty pattern list, non-dict entry — each raises a typed `RuntimeError`.
- **TestPriorityOrder** (6 tests) — pin AUTOFORMALIZATION > VERIFICATION > LOOKUP > SYNTHESIS with explicit cases.
- **TestPrefixSlice** (2 tests) — signal past char 200 ignored; signal at char 0 still matches.
- **TestCanonicalization** (5 tests) — strip, whitespace-collapse, 200-char truncation, no lowercasing, non-string returns empty.

### MODIFIED: `pyproject.toml`

Added `pyyaml>=6.0` to `[project] dependencies` with a one-line rationale comment (the CVE-2017-18342 note + transitive-presence acknowledgement).

## Acceptance criteria

| Brief AC | Status | Evidence |
|---|---|---|
| `classify("What is the definition of an étale morphism?")` → `LOOKUP` | met | `TestBriefAcceptanceCriteria::test_ac1_what_is_definition_is_lookup` |
| `classify("Prove that the Hodge conjecture...")` → `SYNTHESIS` | met | `test_ac2_prove_is_synthesis` |
| `classify("Formalize Yoneda lemma in Lean 4")` → `AUTOFORMALIZATION` | met | `test_ac3_formalize_lean_is_autoformalization` |
| `classify(...)` returns within 1ms (timeit) | met | `TestLatencyBudget` (2 tests; mean over 1000 iterations) |
| `pytest tests/test_router.py` passes | met | 63 passed |
| Adding YAML pattern doesn't require modifying `router.py` | met | `TestPatternFileSourceOfTruth::test_no_hardcoded_patterns_in_router_module` |

## What this milestone closes

- **H1** (per `.claude/roadmap/README.md:68`): "Sonnet planner unjustified → Python regex router". This module is the SOLE closer. Zero LLM calls on the routing path; deterministic; auditable via the YAML rationale strings.

## External writes the orchestrator must authorize

None. Pure-internal:
- `server/router.py` (new)
- `server/router_patterns.yaml` (new)
- `pyproject.toml` (modify — add `pyyaml>=6.0`)
- `tests/test_router.py` (new)

No git push, PR creation, ticket mutation, or third-party API call. The router never touches the network.

## Project check command

`ruff check .` — clean.
`pytest -q` — **988 passed, 4 skipped** (was 925 pre-milestone — +63 from this milestone, no regressions).
