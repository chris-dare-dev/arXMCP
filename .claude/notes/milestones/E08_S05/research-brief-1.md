# E08_S05 — Research Brief 1

## 1. In-codebase context

### Design notes that apply

**`01-mission-and-context.md`** — Sets the model-role framing this milestone crystallizes. Load-bearing quote:
> "Practical consequence: the adversarial critic role in a math pipeline is the *least* valuable LLM role. Lean's kernel error message is a better critic than another Claude. The valuable roles all live *upstream* of verification — and they all depend on having relevant prior work loaded."

This is the intellectual foundation for the verifier-pass removal. The note also maps roles to retrieval granularity (Sketcher → abstracts, Autoformalizer → theorem statements, Tactician → proof chunks + lemma lookup), which informs where Haiku vs Sonnet belongs.

**`07-multi-agent-caching.md`** — Cost analysis and model-selection implications. Load-bearing quote (line 24):
> "Min cacheable prefix: ~1024 tokens for Sonnet/Opus, ~2048 for Haiku. (Verify.)"

This means the Haiku minimum cache prefix is DOUBLE that of Sonnet/Opus — a real cost consideration for retrieval-heavy turns where cached prefixes are short. The note warns these numbers must be verified against current Anthropic docs before design lockdown. Also load-bearing: the 4-agent cost analysis ("Combined effect: a 4-agent pipeline costs roughly 1.3–1.5× a single-agent call, not 4×") — dropping the verifier pass cuts this further, roughly to 1.0–1.2×.

**`README.md` (roadmap)** — H10 entry:
> "| **H10** | Verifier pass circular → DROPPED; Lean kernel is the math critic | E08_S05 |"

E08_S05 is the SOLE closer of H10. The roadmap also notes the milestone tag: `area:runtime`, `kind:design`, `tier:2`.

### `server/router.py` — RouteTag enum

The four values, exactly as defined in source (line 100–103):
```python
class RouteTag(StrEnum):
    LOOKUP = "LOOKUP"
    SYNTHESIS = "SYNTHESIS"
    VERIFICATION = "VERIFICATION"
    AUTOFORMALIZATION = "AUTOFORMALIZATION"
```

The docstring on RouteTag explicitly anticipates this milestone: "The set is CLOSED at four for v1; adding a fifth value requires coordination with E08_S02 (role prefixes) and **E08_S05 (model selection)**, which both assert 'exactly 4'."

The router's `DEFAULT_TAG` is `RouteTag.LOOKUP`, and the router's docstring cites `E08-agent-runtime.md:192` (model policy) for Haiku being the cheapest role.

### `server/orchestrator/__init__.py`

The package docstring explicitly names E08_S05 as the next landing point: "The orchestrator wiring itself (the loop that calls Anthropic with `ROLE_PREFIXES[tag]`, the tool-result handling, the 4-agent fan-out) lands in **E08_S05+**." This confirms the orchestrator package currently has only `id_canon.py`; `model_selector.py` is new work for this milestone.

### `server/prompts.py`

Defines `ROLE_PREFIXES` for all four RouteTags — LOOKUP, SYNTHESIS, VERIFICATION, AUTOFORMALIZATION. The Verification role has a live prefix:
> `"[Role: Verification] Validate the candidate proof step against the retrieved authoritative sources. Cite the chunk that confirms or refutes each step. Do not assume facts not present in retrieval."`

The prefix still exists even though the verifier *agent execution* is dropped. This is not contradictory: the brief says "The Verification RouteTag remains in the router for query classification purposes — queries classified as Verification go to the Autoformalizer role." The role prefix for VERIFICATION still serves BP1 byte-identity (the closed-at-four invariant in `prompts.py` enforces `set(ROLE_PREFIXES.keys()) == set(RouteTag)`). However, VERIFICATION queries are re-dispatched to the Autoformalizer at runtime. The `model_selector` is the dispatch point where VERIFICATION is remapped.

### `server/prompts.py` — No model IDs present

Confirmed: `server/prompts.py` contains zero model ID strings. The forbidden-string check (AC #4: `"claude-opus"` absent from `server/`) is currently trivially passing. After this milestone, `model_selector.py` will introduce Haiku and Sonnet IDs but MUST NOT introduce Opus.

### Existing model ID references in `server/`

`grep -rn "claude-opus\|claude-sonnet\|claude-haiku"` over `server/` returns **zero hits** (confirmed by search). The E14 roadmap references `claude-haiku-4-5` in a metrics label context, but that is in `.claude/roadmap/`, not `server/`. The forbidden-string check scope is `server/` only per AC #4.

### Test naming conventions

All tests in `tests/` follow `test_*.py` naming. Existing orchestrator-related tests: `tests/test_id_canon.py` (note: the brief for E08_S04 specified `server/orchestrator/test_id_canon.py` but the implementation placed it at `tests/test_id_canon.py` per the project's `testpaths = ["tests"]` in `pyproject.toml`). The brief for E08_S05 specifies `tests/test_model_selector.py` — consistent with project convention and the implemented precedent.

### `05-storage-and-indexing.md`

No direct model-policy implications. Confirms BGE-M3 is the sole embedder (no Anthropic models in the retrieval path). The `07-multi-agent-caching.md` note confirms the summarizer (formerly Haiku-powered) is **permanently dropped** (E06_S04 update), so there is no live Haiku summarizer to collide with.

---

## 2. Prior decisions and lessons

### TurnType — not defined anywhere yet

No prior milestone has defined `TurnType`. The brief lists three values: `RETRIEVAL`, `DRAFT`, `LEAN_WRITE`. These must be defined in `model_selector.py` itself (as a `StrEnum` mirroring `RouteTag`'s pattern). The brief implies no fourth value beyond these three, but there is a tension: the brief describes "Autoformalizer's non-write turns (retrieval, context assembly)." `RETRIEVAL` covers retrieval; `DRAFT` can cover context assembly (both map to Haiku). No CONTEXT_ASSEMBLY value is implied by the ACs — use exactly the three values the ACs exercise.

### Model ID verification (CRITICAL)

The brief uses `claude-haiku-4-5` and `claude-sonnet-4-6`. As of May 2026, Anthropic's published model IDs (from `docs.anthropic.com/en/docs/about-claude/models/overview`) are:

| Model | Claude API ID (pinned) | Claude API alias |
|---|---|---|
| Claude Haiku 4.5 | `claude-haiku-4-5-20251001` | `claude-haiku-4-5` |
| Claude Sonnet 4.6 | `claude-sonnet-4-6` | `claude-sonnet-4-6` (same) |
| Claude Opus 4.7 | `claude-opus-4-7` | `claude-opus-4-7` (same) |

**Key finding:** `claude-haiku-4-5` is a convenience alias, not a pinned snapshot. The pinned ID is `claude-haiku-4-5-20251001`. `claude-sonnet-4-6` and `claude-opus-4-7` are dateless (no suffix) — they ARE pinned snapshots per the Anthropic note: "Starting with the Claude 4.6 generation, model IDs use a dateless format that is also a pinned snapshot."

**Recommendation:** Use the pinned ID `claude-haiku-4-5-20251001` for the constant, expose the alias `claude-haiku-4-5` as a secondary constant. The AC text says `returns "claude-haiku-4-5"` — this is the alias, which Anthropic resolves. Use the alias for simplicity, document the pinned snapshot in a comment. The project already uses `claude-haiku-4-5` in E14 roadmap references as the label value. Use `claude-haiku-4-5` consistently with the rest of the project.

### Verification → Autoformalizer remapping

The brief AC #3: `select_model(RouteTag.VERIFICATION, TurnType.DRAFT) -> "claude-haiku-4-5"`. AC #1: `select_model(RouteTag.AUTOFORMALIZATION, TurnType.LEAN_WRITE) -> "claude-sonnet-4-6"`. These are consistent with treating VERIFICATION as "routes to Autoformalizer" at dispatch time. The `model_selector` does NOT need to remap internally — it just needs to return the correct model for `(VERIFICATION, DRAFT)` = Haiku. The brief does not define AC for `(VERIFICATION, LEAN_WRITE)`. Decision: treat VERIFICATION like AUTOFORMALIZATION for all turn types (LEAN_WRITE → Sonnet for Verification queries too, since a verification query that proceeds to Lean output IS an Autoformalizer turn). This avoids a gap where `select_model(VERIFICATION, LEAN_WRITE)` raises a KeyError.

### "claude-opus" forbidden string — scope is server/ only

AC #4 says "anywhere in `server/` source files." The constant must be ABSENT from `server/` entirely — not even a comment referencing it, not even a `DEFERRED = "claude-opus-4-7"` constant. The test in `tests/test_model_selector.py` should grep the `server/` directory tree for the substring `"claude-opus"` and assert zero matches.

### E08_S02 import-time closed-at-four invariant

`server/prompts.py` raises `RuntimeError` at import if `ROLE_PREFIXES.keys() != set(RouteTag)`. Adding a new `RouteTag` would require updating `prompts.py`. E08_S05 does NOT add any new RouteTags — it defines a new enum `TurnType` in `model_selector.py` only. No import-time invariant change needed in `prompts.py`.

### Verifier prefix tension resolved

The `_VERIFICATION_PREFIX` in `prompts.py` still exists and is used for BP1 byte-stability. The execution-dispatch decision (route VERIFICATION queries to Autoformalizer behavior) is a runtime decision made at the model_selector / orchestrator level, not at the prompt-prefix level. The two concerns are cleanly separated.

---

## 3. External sources

**Anthropic Models Overview (fetched May 2026):**

- `claude-haiku-4-5`: alias; pinned snapshot is `claude-haiku-4-5-20251001`. Fastest model, 200K context, $1/$5 per MTok input/output.
- `claude-sonnet-4-6`: dateless pinned snapshot. Balanced speed/intelligence, 1M context, $3/$15 per MTok.
- `claude-opus-4-7`: dateless pinned snapshot. Most capable, 1M context, $5/$25 per MTok.

**The 35% tokenizer expansion claim in the brief** for Opus 4.7 vs Sonnet 4.6: the Anthropic docs note Opus 4.7 "uses a new tokenizer" and has a 1M-token context with a note of "~555k words / ~2.5M unicode characters" vs Sonnet 4.6's "~750k words / ~3.4M unicode characters" for the same 1M token context. This confirms the tokenizer produces MORE tokens per word for Opus 4.7, consistent with the brief's "35% tokenizer expansion" claim. Opus is not just more expensive at the same token count — it tokenizes inputs into more tokens than Sonnet/Haiku do.

**Minimum cache prefix for Haiku 4.5 vs Sonnet:** `07-multi-agent-caching.md` states Haiku requires ~2048 tokens minimum cacheable prefix (vs 1024 for Sonnet/Opus). This is load-bearing for the cost rationale in `docs/model-policy.md` — retrieval turns that stay under 2048 tokens get NO cache benefit from Haiku, which narrows the cost advantage. The brief should document this nuance in the token-budget section.

---

## Open questions

1. **Model ID format — alias vs pinned.** `claude-haiku-4-5` is an alias for `claude-haiku-4-5-20251001`. The ACs use the alias form. **Recommendation:** use the alias `claude-haiku-4-5` as the constant value (consistent with E14 roadmap references and the AC text), add a comment citing the pinned form `claude-haiku-4-5-20251001`. Do NOT use the pinned form as the constant — that would break the AC string comparison.

2. **TurnType values.** The ACs exercise exactly three: `RETRIEVAL`, `DRAFT`, `LEAN_WRITE`. No fourth value is needed for AC compliance. However, the brief mentions "context assembly" as a non-write Autoformalizer turn. **Recommendation:** define only the three ACs-exercised values. Context assembly maps to `RETRIEVAL` or `DRAFT` — let the orchestrator (future milestone) decide which TurnType to pass; `model_selector` doesn't care about the semantic difference.

3. **`select_model(VERIFICATION, LEAN_WRITE)` — is this valid?** The brief has no AC for it. A VERIFICATION-tagged query should be redirected to Autoformalizer behavior. If it somehow reaches LEAN_WRITE, it should get Sonnet (same as AUTOFORMALIZATION + LEAN_WRITE). **Recommendation:** implement `VERIFICATION` identically to `AUTOFORMALIZATION` in the lookup table (Haiku for RETRIEVAL/DRAFT, Sonnet for LEAN_WRITE). Raise `ValueError` only for truly unknown `(RouteTag, TurnType)` combinations.

4. **Where does `TurnType` live?** The brief says `model_selector.py`. This is correct — no prior module defines it, and it is a model-selection concern, not a routing concern. Define `TurnType` as a `StrEnum` in `server/orchestrator/model_selector.py`. Export it from there; the orchestrator (future E08_S06+) imports it from that module.

5. **Haiku minimum cache prefix (2048 tokens).** The `07-multi-agent-caching.md` caveat ("Verify against docs") applies. The 2048 figure may have changed. The `docs/model-policy.md` token-budget section should include a dated note and a link to verify.

6. **`docs/model-policy.md` location.** The brief says `docs/model-policy.md`. Verify the `docs/` directory exists at project root. If not, create it (it should exist — E08_S04 created `docs/orchestrator-rules.md`).

---

## External writes the implementation will require

| Type | Target | Notes |
|---|---|---|
| None | — | All deliverables are local source + tests + docs. No git push, no PR, no third-party API call, no new runtime dependency. |

The three model ID strings (`claude-haiku-4-5`, `claude-sonnet-4-6`, and the absence of `claude-opus`) are pure Python string constants. No Anthropic SDK call happens in `model_selector.py` — it is a pure lookup function. The test suite mocks nothing; it calls `select_model` directly with enum values and asserts string returns.
