# E08_S01 — Query router: Python regex classifier — Research Brief 2

## 1. In-codebase context

### YAML dependency status — adding PyYAML is a NEW dep

`/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/pyproject.toml:30-92` lists every runtime dep with a per-line rationale. **`PyYAML` is not pinned**, and a `grep -rn "yaml\|PyYAML\|safe_load"` across `server/`, `ingest/`, and `pyproject.toml` returns **zero hits**. The project has been disciplined about dependency minimalism — every added dep carries a paragraph explaining why. Adding PyYAML is one new transitive (libyaml C-extension; PyYAML wheels bundle a pure-Python fallback so portability is fine), but the precedent matters.

**Recommendation — DO NOT add PyYAML.** The brief calls the YAML file "annotated… includes rationale comments". Comments are strictly more expressive in TOML (Python 3.11 ships `tomllib` in stdlib — already a hard requirement at `pyproject.toml:34`) or in a Python module that lists patterns as data. **Pick `server/router_patterns.toml`** loaded via `tomllib.loads(...)`, zero new deps, perfect comment fidelity, identical reviewability. If the implementer insists on YAML for cosmetic familiarity, the brief's intent is satisfied by the `data-not-code` separation, and TOML satisfies that intent without a dep. The roadmap brief does not bind the format on disk; it binds the behavior ("editable without touching Python source").

### Where `RouteTag` lives

`server/__init__.py` is empty (1 line). The brief mandates `server/router.py` as the home. **Do not re-export from `server/__init__.py`** — every existing public symbol is imported via the dotted path (`from server.config import Config`, `from server.middleware import _validate_host_header`). Mirror that. Downstream `server/prompts.py` (E08_S02) and `server/orchestrator/model_selector.py` (E08_S05) will both `from server.router import RouteTag`. The enum is the cross-milestone seam.

### The four roles are canonical, not extensible in v1

`/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/.claude/notes/07-multi-agent-caching.md:66-67` states it directly:

> "Heterogeneous agent roles (Lookup, Synthesis, Verification, Autoformalization) issue heterogeneous tool calls"

The roadmap brief at `.claude/roadmap/E08-agent-runtime.md:62` repeats it ("byte-identical across all four roles"), and `E08_S02` deliverable line 80 says "**exactly 4** role-prefix constants". The router YAML/TOML schema must support arbitrary tags as DATA, but the `RouteTag` enum is closed at four. Out-of-scope explicitly forbids "Multi-label routing" (line 46).

### Anchor pattern: `re.search`, not `re.match`

The brief uses `\b…\b` patterns with no `^`/`$` anchors. That mandates `re.search` (or `pattern.search` on a compiled pattern). Document this on the function — first-match-wins semantics depend on the search returning a truthy `Match` object on any partial hit.

### `re.IGNORECASE`: redundant but defensive

The brief says "operate on the lowercased, whitespace-normalized first 200 characters". Pre-lowercasing makes `re.IGNORECASE` redundant. **Recommendation**: still set `re.IGNORECASE` at compile time as defense-in-depth — if the YAML/TOML ever contains a pattern like `\bLean\b` (the brief itself uses `r"\blean\b"`), an editor mistake doesn't silently miscount tags. Add a comment in `router.py` documenting that the flag is belt-and-suspenders given upstream lowercasing.

### Unicode handling — `\b` is Unicode-by-default in Python 3

AC #1 is `classify("What is the definition of an étale morphism?")` → `RouteTag.LOOKUP`. The active patterns there are `\bdefin(e|ition)\b` and `\bwhat is\b`; neither touches the `é`. Python 3's `re` module uses Unicode word boundaries for `\w` and therefore `\b` **by default** — this is the documented `re.UNICODE` flag, which is implicit on `str` patterns (Python docs: *"Matches Unicode word characters; this includes most characters that can be part of a word in any language"*). `re.ASCII` would have to be explicitly opted into. So `\b` works on `étale` correctly. Pin the test: add an explicit assertion that `classify("What is the étale fundamental group?")` matches Lookup, so a future ASCII-flag regression is loud.

### H1 — quoted

`/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/.claude/roadmap/README.md:68`:

> "**H1** | Sonnet planner unjustified → Python regex router | E08_S01"

E08_S01 is the **sole** closure of H1. The risk note in the brief is the binding rationale: zero LLM calls on the routing path, deterministic, auditable.

## 2. Prior decisions and lessons

### Schema for `router_patterns.toml`

**Recommendation — flat list-of-tables, top-down priority:**

```toml
# server/router_patterns.toml
# Patterns are evaluated TOP-TO-BOTTOM; first match wins.
# When in doubt, place narrower patterns first.

[[pattern]]
tag = "AUTOFORMALIZATION"
regex = '\blean\b'
rationale = "Lean is the formal-verification target language."

[[pattern]]
tag = "LOOKUP"
regex = '\bwhat is\b'
rationale = "Definitional lookup. Place above SYNTHESIS so 'what is the proof of X' routes to Lookup."
```

The flat list makes priority a single linear axis (the file order), which is exactly the brief's "ordered by priority". The grouped-by-tag form (`{tag: [{pattern, rationale}]}`) reintroduces a priority-among-groups ambiguity. Flat list also makes the test harness trivial — iterate in file order.

### Pattern compilation — module-level constant, import-time

```python
# server/router.py
_PATTERN_FILE = Path(__file__).parent / "router_patterns.toml"
_COMPILED_PATTERNS: list[tuple[re.Pattern[str], RouteTag]] = _load_patterns(_PATTERN_FILE)
```

Compile **once** at import; every `classify` call iterates the pre-compiled list. Mirrors the precedent at `ingest/chunker.py:97-106` (`_THEOREM_CLASS_RE = re.compile(...)`, `_AUTO_ID_RE = re.compile(...)` — module-level compiled constants).

### Ambiguous case resolution — recommended priority order

The brief mandates ≥3 ambiguous tests. **Concrete priority order** (top wins):

1. **AUTOFORMALIZATION** — `\blean\b`, `\bmathlib\b`, `\bformalize\b`, `\btranslate.*lean\b`. Highest priority because the Lean target is a hard mode-switch; even "Prove X in Lean" must route Autoformalization to satisfy AC #3 (`"Formalize Yoneda lemma in Lean 4"` → AUTOFORMALIZATION beats `\bformalize\b`-vs-the-implicit-prove signal).
2. **VERIFICATION** — `\bverify\b`, `\bcheck\b`, `\bvalid\b`, `\bcorrect\b`. Verification overrides Lookup because "Verify the definition of X" is a validation request, not a name-lookup request.
3. **LOOKUP** — `\bwhat is\b`, `\bdefin(e|ition)\b`, `\b(lemma|theorem) \d`, `\bnotation\b`. Lookup beats Synthesis because most "what is the proof of Y" queries are people asking *for* Y's proof to be retrieved, not assembled.
4. **SYNTHESIS** — `\bprove\b`, `\bsketch\b`, `\bshow that\b`, `\bderive\b`. Default-active for assembly-style requests.

Concrete ambiguous-case tests, with documented expected behavior:
- `"What is the proof of the Yoneda lemma?"` → **LOOKUP** (Lookup precedes Synthesis; user wants the cached proof, not assembly)
- `"Verify that this is the correct definition of étale"` → **VERIFICATION** (Verification precedes Lookup; user has a candidate to validate)
- `"Formalize the proof of the Hodge conjecture"` → **AUTOFORMALIZATION** (Autoformalization is top; Lean target is the hard signal)

These priority decisions must be reflected in the TOML's top-down ordering AND repeated in tests/test_router.py docstring so the order isn't accidentally re-sorted alphabetically by a future editor.

### Default tag on no-match

Brief lists four tags, no `UNKNOWN`. **Recommendation — default to `RouteTag.SYNTHESIS`**. Rationale: per `.claude/roadmap/E08-agent-runtime.md:208`, the orchestrator already collapses Verification → Autoformalizer downstream, and per E08_S05 line 207 `SYNTHESIS` is mapped to Haiku for retrieval — the cheapest broadly-capable tier. Synthesis is also the role with the most generic role-prefix ("assemble across multiple chunks"), so it's the safest fallback when intent is unclear. Document the default in both `router.py` and the TOML header.

### The 1ms budget — `timeit` test pattern

```python
def test_classify_latency_under_1ms():
    q = "Prove that " + "x" * 188  # exactly 200 chars after lowercase+strip
    elapsed_ms = timeit.timeit(lambda: classify(q), number=1000) / 1000 * 1000
    assert elapsed_ms < 1.0, f"classify mean = {elapsed_ms:.3f}ms (budget 1ms)"
```

Mean over N=1000. **Do NOT measure single calls** — JIT/cache warmup variance dominates at sub-ms scale. Brief says "measured via `timeit`" — this is the canonical form. Run inside `tests/test_router.py`; mark with no special pytest marker (test must run in default CI).

### YAML/TOML missing OR malformed — fail at import

`router.py` calls `_load_patterns(_PATTERN_FILE)` at module import. If the file is missing, `tomllib.loads` raises `FileNotFoundError`; if malformed, `tomllib.TOMLDecodeError`. **Let both propagate** — server startup must fail loudly. This mirrors `server/config.py`'s pydantic-settings-at-startup discipline (`pyproject.toml:79-81`). Add a wrapper that catches and re-raises with a contextual `RuntimeError("router_patterns.toml failed to load: …")` so the operator sees the file path in the traceback.

Validation on load:
- Every entry must have keys `{tag, regex, rationale}` — fail-fast on missing keys.
- `tag` must be a member of `RouteTag` (`.value` lookup) — fail on unknown tag, so a typo doesn't silently never-match.
- `regex` must `re.compile(…, re.IGNORECASE)` cleanly — fail on bad regex.

### Test fixture pattern

Mirror `tests/test_security.py` (`/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/tests/test_security.py:1-60`) — top-of-file docstring with **coverage map** (AC → test class), `from __future__ import annotations`, `pytest` fixtures only when needed (this milestone needs none — pure-function tests). No conftest hooks required; the existing `tests/conftest.py:124-199` autouse fixtures don't touch the router.

### `RouteTag` enum — `enum.StrEnum` (Python 3.11+)

`pyproject.toml:32` requires Python ≥ 3.11. `enum.StrEnum` is in 3.11+ stdlib and gives nicer reprs (`RouteTag.LOOKUP` prints as `"LOOKUP"` when stringified, no `__str__` boilerplate), JSON-serialization works without a custom encoder, and downstream `model_selector.py` can do `tag.name.lower()` cleanly. Plain `enum.Enum` works but `StrEnum` is the modern choice. Enum values: `"LOOKUP"`, `"SYNTHESIS"`, `"VERIFICATION"`, `"AUTOFORMALIZATION"` (uppercase strings = stable wire format if ever logged).

## 3. External sources

- **Python `re` module** (https://docs.python.org/3/library/re.html): `\b` is Unicode-aware on `str` patterns by default; `re.IGNORECASE` for case-insensitive matching; `re.compile` for module-level pre-compilation.
- **Python `tomllib`** (https://docs.python.org/3/library/tomllib.html) — stdlib in 3.11+; read-only TOML parser. No external dep; replaces the implicit PyYAML ask in the brief.
- **Python `enum.StrEnum`** (https://docs.python.org/3/library/enum.html#enum.StrEnum) — 3.11+; auto-string enum.
- **`.claude/roadmap/README.md:68`** — H1 closure binding: "Sonnet planner unjustified → Python regex router | E08_S01".
- **`.claude/notes/07-multi-agent-caching.md:66-67`** — definitive enumeration of the four roles.
- **`.claude/roadmap/E08-agent-runtime.md:33-44`** — deliverables and acceptance criteria, verbatim.

## Open questions

1. **TOML vs YAML for the pattern file.** Brief says YAML. This brief recommends TOML to avoid a new dep. The implementer must resolve before coding — pick one and stay consistent. (TOML is correct; the brief's choice is cosmetic.)
2. **Default tag on no-match — SYNTHESIS or a new UNKNOWN?** This brief recommends `SYNTHESIS`. If the implementer wants `UNKNOWN`, E08_S02 / E08_S05 must learn a fifth case, which contradicts those milestones' "exactly 4" assertions. Stick with `SYNTHESIS`.
3. **Whitespace normalization.** Brief says "whitespace-normalized" — does that mean `re.sub(r"\s+", " ", q.strip())` or just `q.strip().lower()`? Recommend the former (collapse runs of whitespace including tabs/newlines to a single space) so multi-line queries from `paste-multi-line` shells classify the same as single-line.

## External writes the implementation will require

**Zero.** No git push, no PR creation (the milestone-pipeline does that at the rectify gate, not at implement). No infra mutation. No third-party API call (the entire point of H1 closure is eliminating the LLM planner call). The router never touches the network.
