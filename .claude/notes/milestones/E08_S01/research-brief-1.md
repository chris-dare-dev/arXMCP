# E08_S01 — Research Brief 1 (Query router: Python regex classifier)

## 1. In-codebase context

### Roles: where the four-agent runtime is documented

The brief calls the four `RouteTag` values **Lookup, Synthesis, Verification, Autoformalization**. The constitution notes use slightly different vocabulary (Sketcher / Autoformalizer / Tactician / Fixer) but the *retrieval intents* line up. Quote, `.claude/notes/01-mission-and-context.md:113-123`:

> "Different agent roles want different retrieval granularities:
>  - **Sketcher** wants paper abstracts and section summaries.
>  - **Autoformalizer** wants theorem statements with their context (definitions, notation).
>  - **Tactician** wants theorem+proof chunks plus exact lemma-name lookup over Mathlib-style symbols.
>  - **Fixer** wants display-equation similarity and version-diff …"

Mapping the **router**'s four `RouteTag`s onto those: Lookup ≈ Tactician/Autoformalizer-context (named-object retrieval), Synthesis ≈ Sketcher (assemble-a-proof-strategy), Verification ≈ pre-Lean check step (E08_S05 routes this to Autoformalizer for kernel checking), Autoformalization ≈ Autoformalizer (Lean syntax). The router's enum is the canonical set going forward — `01-mission` vocabulary is constitutional but not a deliverable name.

`.claude/roadmap/E08-agent-runtime.md:196` makes the Verification→Autoformalizer routing explicit:
> "The Verification RouteTag remains in the router (E08_S01) for query classification purposes — queries classified as Verification go to the Autoformalizer role, which produces Lean syntax for kernel checking."

### Role-prefix / BP1 design (downstream consumer)

`.claude/notes/07-multi-agent-caching.md:74-82` is the load-bearing constraint that `RouteTag` feeds:

> "**Breakpoint 1 (BP1, 1-hour TTL):** end of system prompt + tool definitions block. Byte-identical across every agent role because roles are encoded as a ≤50-token prefix in the first *user* turn (not as per-role system prompts). … **Breakpoint 2 (BP2, 1-hour TTL):** end of the problem statement."

Implication for the router: the router's **only** output is a `RouteTag` enum value. It does not synthesize prefixes, does not touch prompts, does not affect BP1 bytes. E08_S02 owns the four frozen prefix strings keyed by `RouteTag`; the router is a pure switch.

### H1 critique line (verifying the milestone closes the right thing)

`.claude/roadmap/README.md:69`:
> "| **H1** | Sonnet planner unjustified → Python regex router | E08_S01 |"

This milestone is the sole closer of H1.

### Server layout — where `router.py` lives

Files in `server/`: `__init__.py` (empty), `config.py`, `corpus.py`, `health.py`, `main.py`, `middleware.py`, `query_encoder.py`, `resources.py`, `tools.py`, plus subpackages `handlers/`, `retrieval/`, `schemas/`. There is currently **no `orchestrator/` directory** (E08_S04 will create one). Place the new files at `server/router.py` and `server/router_patterns.yaml` — flat with the other module-level files.

The router is **stateless and pure-Python**. Do **not** wire it into `Resources` (`server/resources.py:209-242`). `Resources` is for "expensive, long-lived objects" (BGE-M3 model, LanceDB handle, reranker, semaphores) — the router is a few-hundred-byte module-level constant after import. The orchestrator (lands in E08_S04+) will `from server.router import classify, RouteTag` at the call site.

The single optional integration hook: at `server/resources.py:248` (`Resources.startup`), an `import server.router` statement would force YAML parsing + regex compilation into the eager startup window so the first request does not pay it. Recommend doing this — costs <10 ms and keeps `/readyz` honest.

### `pyproject.toml` — PyYAML status

`pyproject.toml:33-96` lists every runtime dep (beautifulsoup4, transformers, torch, safetensors, numpy, lancedb, pyarrow, rank-bm25, mcp, fastapi, uvicorn[standard], pydantic-settings, prometheus-client). **`PyYAML` is NOT pinned.** It must be added. PyYAML is already transitively present in the local dev env (6.0.3) via transformers/lancedb, but the project must declare it directly — implicit deps are exactly what `extra="forbid"` style discipline rejects. Add `"pyyaml>=6.0"` to `[project]` dependencies with a one-line comment ("E08_S01 router-pattern YAML loader; safe_load only").

### Test template

The simplest existing pure-Python test is in this codebase pattern: `tests/test_preamble.py:1-50` — uses pytest classes per AC, module-level docstring with a coverage map, `from __future__ import annotations`, fixtures path via `Path(__file__).parent / "fixtures"`. Mirror this style. **Do not** import any heavy module (torch / lancedb / transformers); the router has zero such deps. The test must run in <1s including the timeit budget check.

## 2. Prior decisions and lessons

### YAML loading: `yaml.safe_load`, period

CVE-2017-18342: `yaml.load(stream)` without an explicit `Loader=` arg deserializes arbitrary Python objects, achieving RCE on a malicious YAML file. The router YAML is in-tree and version-controlled, so attacker pressure is low — but using `safe_load` costs nothing and closes a known vector. **Recommended:**

```python
with PATTERNS_PATH.open("r", encoding="utf-8") as fh:
    raw = yaml.safe_load(fh)
```

### Regex compilation: at module import, into a frozen tuple

The 1ms latency budget is comfortable for a few dozen `re.search()` calls on a ≤200-char string but **only if patterns are pre-compiled**. Recommended module-level shape:

```python
_COMPILED: tuple[tuple[re.Pattern[str], RouteTag], ...] = _load_and_compile()
```

`_load_and_compile()` reads the YAML once, compiles each `pattern` string with `re.compile(..., re.IGNORECASE)`, and returns an immutable tuple in YAML-declared order. Tuple (not list) prevents accidental mutation. `re.IGNORECASE` makes the patterns themselves authorable in lower case while still matching mixed-case inputs — this lets us drop the `.lower()` step on the query itself (see normalization below).

### Normalization: slice first, then normalize, then match

The brief says "lowercased, whitespace-normalized first 200 characters." Slice before normalize: `query[:200]` is O(1), normalization on 200 chars is <1µs, normalization on a megabyte query before slicing is not. **Recommended canonical normalization:**

```python
def _canonicalize(q: str) -> str:
    if not isinstance(q, str):
        return ""
    head = q[:200]                       # cheap slice first
    head = unicodedata.normalize("NFC", head)  # match query_encoder._canonicalize
    head = " ".join(head.split())        # collapses any \s+ run incl. tabs/newlines
    return head                          # do NOT lowercase — re.IGNORECASE handles it
```

NFC normalization mirrors `server/query_encoder.py::_canonicalize` (see `tests/test_query_encoder.py:324-337`), keeping `étale` / `\'etale` discipline aligned with the rest of the server. Whitespace collapse via `" ".join(s.split())` is idiomatic and handles all Unicode whitespace.

### Priority ordering and tiebreak

YAML list order **is** the tiebreak. The classifier walks `_COMPILED` top-to-bottom and returns on the **first** `re.search` hit. Recommended priority (most specific first):

1. **Autoformalization** — `\blean\b`, `\bmathlib\b`, `\bformalize\b`, `\btranslate\b.*\blean\b`. Most specific because "Lean" is a strong, rare token.
2. **Verification** — `\bverify\b`, `\bcheck\b`, `\bvalidate\b`, `\bis\b.*\bcorrect\b`. Verification is more specific than synthesis.
3. **Synthesis** — `\bprove\b`, `\bshow that\b`, `\bderive\b`, `\bsketch\b`. Action verbs requesting new derivation.
4. **Lookup** — `\bdefin(e|ition)\b`, `\bwhat is\b`, `\blemma \d`, `\btheorem \d`, `\bnotation\b`. Last because also serves as the **default**.

### Ambiguity resolution rule

The brief mandates ≥3 ambiguous test cases. Document this rule in a YAML comment block at the top of `router_patterns.yaml`: **"When two intents collide, the higher-priority pattern wins. Lean tokens beat everything; verification beats synthesis; synthesis beats lookup."** Three required cases:

| Query | Expected | Why |
|---|---|---|
| `"What is the proof of the Yoneda lemma?"` | `SYNTHESIS` | "proof" / "prove" intent dominates "what is" lookup intent — the user wants a derivation, not a named-object lookup. Implement by placing a `\bprove|\bproof\b` pattern in Synthesis above the `\bwhat is\b` Lookup pattern. |
| `"Verify that this Lean proof of Cauchy-Schwarz typechecks"` | `AUTOFORMALIZATION` | `\blean\b` is highest priority. The agent needs Lean syntax handling; the orchestrator (E08_S05) routes Verification through Autoformalizer anyway. |
| `"Sketch a proof and check the key step"` | `VERIFICATION` | "check" wins over "sketch" because we want the more conservative, more specific intent. (Reasonable people may disagree; the test documents the rule.) |

### The 200-char slice — before normalization

Already covered above. Slice first.

### Default tag on no-match: `LOOKUP`

The brief lists four tags but is silent on miss behavior. Two options: (a) raise; (b) default to `LOOKUP`. Recommend **`LOOKUP`** — it routes the query to the lowest-cost agent role (Haiku for retrieval per `E08-agent-runtime.md:192`), and `01-mission-and-context.md:115-118` describes Sketcher/Tactician retrieval as the most general-purpose path. A miss is "I don't know what this is" which most resembles "look something up." Raising would force every caller into a try/except for what is by design a quality (not correctness) issue per the brief: *"Misrouting is a quality issue, not a correctness issue."*

### Defensive input validation

- `None`, non-`str`: return `RouteTag.LOOKUP` (do not raise — see above; consistent with quality-not-correctness).
- Empty / whitespace-only: returns `LOOKUP` naturally (no patterns match empty string).
- Strings >> 200 chars: handled by the `[:200]` slice. No length cap needed.
- No upstream guarantee about Unicode form, so NFC normalize.

### Test framework: pytest + `timeit` for AC #4

Use `timeit.timeit("classify(q)", globals={...}, number=10_000)` and assert `mean_per_call_ms < 1.0`. Run on a 200-char worst-case payload (a query that matches no pattern, forcing every regex to be tested). Mark with no special pytest marker — this runs in default CI. Reference: AC #4 in the brief.

## 3. External sources

- **PyYAML safe_load** — official docs: `https://pyyaml.org/wiki/PyYAMLDocumentation`. CVE-2017-18342: `yaml.load` without `Loader=` arg permits arbitrary code execution; `yaml.safe_load` restricts to a subset that maps cleanly to Python primitives. PyYAML 6.0+ raises a deprecation warning for `yaml.load(stream)` without a `Loader`; pin `>=6.0`.
- **`re.compile` performance** — Python docs `https://docs.python.org/3/library/re.html#re.compile`: compiled `Pattern` objects skip the cache lookup the module-level `re.search()` would do. The internal cache is bounded to ~512 entries, so sufficient for our scale, but explicit compile makes the cost a startup concern not a per-call concern. CPython benchmarks: compiled `Pattern.search` on a 200-char string with 20 patterns is ~5–20 µs total — well inside the 1ms budget.
- **Roadmap H1** — `.claude/roadmap/README.md:69` and `.claude/roadmap/E08-agent-runtime.md:48-49`: this milestone is the sole closer of H1 (replacing a Sonnet planner with a regex router).

## Open questions

None require pre-implementation resolution. Three calls are documented above and the implementer should adopt them rather than re-debate:

1. Default tag on no-match → `RouteTag.LOOKUP`.
2. Verification ↔ Synthesis tiebreak → Verification wins (most specific).
3. "What is the proof of …" → `SYNTHESIS` (verb intent dominates).

## External writes the implementation will require

**Zero.** This milestone is pure local implementation: three new files (`server/router.py`, `server/router_patterns.yaml`, `tests/test_router.py`), one dependency line added to `pyproject.toml`. No git pushes, no PR creation, no ticket mutations, no third-party API calls. Acceptance is `pytest tests/test_router.py` passing locally.
