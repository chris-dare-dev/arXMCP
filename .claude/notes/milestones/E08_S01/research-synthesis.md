# E08_S01 — Research synthesis

## Both researchers agree on these load-bearing facts

1. **The four roles are canonical and closed at four** for v1. `.claude/notes/07-multi-agent-caching.md:66-67` quotes verbatim: *"Heterogeneous agent roles (Lookup, Synthesis, Verification, Autoformalization) issue heterogeneous tool calls"*. E08_S02's deliverable line says "exactly 4 role-prefix constants". `RouteTag` enum is closed at four; YAML schema can carry arbitrary tags but the enum is the cross-milestone seam.

2. **`PyYAML` is NOT a declared runtime dep** but IS transitively present (via transformers/lancedb). Adding it explicitly is a one-line change.

3. **H1 closure**: this milestone is the SOLE closer. `.claude/roadmap/README.md:68`: *"H1 | Sonnet planner unjustified → Python regex router | E08_S01"*. Risk-note rationale: zero LLM calls on the routing path; deterministic; auditable.

4. **Pattern compilation at module import**: module-level `_COMPILED_PATTERNS: tuple[tuple[re.Pattern, RouteTag], ...]`. The 1ms latency budget demands pre-compilation. Mirrors `ingest/chunker.py:97-106` precedent.

5. **`re.search`, NOT `re.match`**: brief patterns use `\b…\b` with no `^`/`$` anchors.

6. **Python's `\b` is Unicode-aware on `str` patterns by default** — AC #1 (`étale`) works without `re.UNICODE`. `re.IGNORECASE` flag still set as defense-in-depth (an editor mistake adding a mixed-case pattern doesn't silently never-match).

7. **Slice before normalize**: `query[:200]` is O(1); normalization on 200 chars is <1µs; normalization on a megabyte query is wasteful.

8. **Stateless and pure-Python**: NOT wired into `Resources` (per Brief 1). The orchestrator (E08_S04+) imports `from server.router import classify, RouteTag` at the call site.

## Decisions for the implementer

| ID | Decision | Rationale |
|---|---|---|
| D1 | **Use PyYAML for the pattern file** (`server/router_patterns.yaml`); add `pyyaml>=6.0` to `pyproject.toml` runtime deps with a one-line rationale. Use `yaml.safe_load`, never `yaml.load`. | Honors the brief literal (deliverable name `router_patterns.yaml`). PyYAML is already transitively present; explicit declaration matches the project's "no implicit deps" discipline. CVE-2017-18342 closes via `safe_load`. |
| D2 | **Module-level eager compilation**: `_COMPILED_PATTERNS: tuple[tuple[re.Pattern[str], RouteTag], ...] = _load_and_compile()`. Tuple (not list) — immutable. | 1ms latency budget; mirrors the `ingest/chunker.py` precedent. |
| D3 | **Canonicalization**: slice first → NFC → whitespace-collapse. Do NOT lowercase (use `re.IGNORECASE` flag). | NFC mirrors `server/query_encoder._canonicalize`. Whitespace-collapse via `" ".join(s.split())` handles all Unicode whitespace. |
| D4 | **Priority order (top-down, first-match wins)**: AUTOFORMALIZATION → VERIFICATION → LOOKUP → SYNTHESIS. | Lean is the strongest mode-switch signal (highest); Verification is more specific than Lookup; Lookup beats Synthesis because most "what is X" queries want retrieval, not assembly; Synthesis is reserved for explicit derivation verbs. |
| D5 | **Default tag on no-match: `LOOKUP`.** | Routes the query to the lowest-cost agent role (Haiku for retrieval). `01-mission-and-context.md:115-118` describes Sketcher/Tactician retrieval as the most general-purpose path. Brief is silent; this is the safest cheap default. Quality-not-correctness per brief: misrouting is acceptable. |
| D6 | **`RouteTag` is `enum.StrEnum`** (Python 3.11+). Values: `"LOOKUP"`, `"SYNTHESIS"`, `"VERIFICATION"`, `"AUTOFORMALIZATION"`. | Modern stdlib choice; clean repr; JSON-serializable; downstream `model_selector.py` can do `tag.name.lower()`. |
| D7 | **Three ambiguous test cases**: (1) `"What is the proof of the Yoneda lemma?"` → LOOKUP (Lookup precedes Synthesis); (2) `"Verify that this is the correct definition of étale"` → VERIFICATION; (3) `"Formalize the proof of the Hodge conjecture"` → AUTOFORMALIZATION (Lean target wins). | Mandated by the brief. Resolution is deterministic per D4. Document the priority rule prominently in the YAML header. |
| D8 | **Defensive input validation**: `None`, non-`str`, empty string → return `LOOKUP` (do NOT raise). Per the brief: misrouting is a quality issue, not a correctness one. | Forces every caller to wrap classify in try/except for what is a defensible quality call. |
| D9 | **Import-time YAML load**: file-missing OR malformed YAML raises at module import. Wrap in `RuntimeError("router_patterns.yaml failed to load: ...")` so the operator sees the file path. | Server startup must fail loudly. Mirrors `server/config.py`'s pydantic-at-startup discipline. |
| D10 | **Validation on load** (per Brief 2): every entry has keys `{tag, regex, rationale}`; `tag` must match a `RouteTag` value (typo → fail-fast); `regex` must `re.compile` cleanly. | Catches YAML editor mistakes at import, not at first never-matching query. |
| D11 | **`timeit` budget test**: mean over `number=1000` iterations of a 200-char query that matches no pattern (worst case — every regex tested). Assert `mean_per_call_ms < 1.0`. | Per Brief 1 — single-call measurement is JIT/cache-noise dominated at sub-ms scale. |

## Open questions

1. **Optional eager-import hook in `Resources.startup`**: a bare `import server.router` in startup forces YAML parsing + regex compilation off the first-request path. Cost <10ms. Recommend; non-blocking. Not strictly part of E08_S01's deliverables (E08_S04+ orchestrator integration), but cheap.

## External writes the implementation will require

None. Pure-internal:
- `server/router.py` (new)
- `server/router_patterns.yaml` (new)
- `pyproject.toml` (modify — add `pyyaml>=6.0` runtime dep)
- `tests/test_router.py` (new)

No git push, PR creation, ticket mutation, infra change, or third-party API call. The router never touches the network.
