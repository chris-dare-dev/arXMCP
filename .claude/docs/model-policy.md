# Model selection policy (v1)

This document is the canonical reference for which Anthropic model
the orchestrator uses for which turn. The corresponding code lives
at `server/orchestrator/model_selector.py::select_model`.

E08_S05 freezes the v1 policy. Future changes (Opus 4.7 integration,
fine-tuned models, dynamic per-query selection) live in v2 and need
their own milestone.

## Selection table

The orchestrator dispatches every Anthropic Messages API call as a
`(RouteTag, TurnType)` pair. The complete 4 × 3 = 12-cell table:

| RouteTag | TurnType | Model ID |
|---|---|---|
| `LOOKUP` | `RETRIEVAL` | `claude-haiku-4-5` |
| `LOOKUP` | `DRAFT` | `claude-haiku-4-5` |
| `LOOKUP` | `LEAN_WRITE` | **FORBIDDEN** (raises `ValueError`) |
| `SYNTHESIS` | `RETRIEVAL` | `claude-haiku-4-5` |
| `SYNTHESIS` | `DRAFT` | `claude-haiku-4-5` |
| `SYNTHESIS` | `LEAN_WRITE` | **FORBIDDEN** (raises `ValueError`) |
| `VERIFICATION` | `RETRIEVAL` | `claude-haiku-4-5` |
| `VERIFICATION` | `DRAFT` | `claude-haiku-4-5` |
| `VERIFICATION` | `LEAN_WRITE` | `claude-sonnet-4-6` |
| `AUTOFORMALIZATION` | `RETRIEVAL` | `claude-haiku-4-5` |
| `AUTOFORMALIZATION` | `DRAFT` | `claude-haiku-4-5` |
| `AUTOFORMALIZATION` | `LEAN_WRITE` | `claude-sonnet-4-6` |

The pattern: **Haiku is the default; Sonnet is the exception**, used
exclusively for the Autoformalizer's terminal `LEAN_WRITE` turn (and
its `VERIFICATION`-routed equivalent). All retrieval and draft work
runs on Haiku.

**Forbidden cells** (F1 fix from the E08_S05 critique): `LEAN_WRITE`
turns for non-Autoformalizer roles (`LOOKUP`, `SYNTHESIS`) are
ILLEGAL. Calling `select_model(LOOKUP, LEAN_WRITE)` raises
`ValueError`. Reasoning: those roles do not produce Lean output, so
a `LEAN_WRITE` dispatch with a non-Autoformalizer route tag signals
a caller bug. The pre-fix table silently returned Haiku for those
cells, masking the bug. Failing loud catches misroutes early.

### Why Sonnet for `LEAN_WRITE`

The Lean-syntax write is the single turn whose output is
mechanically validated by the Lean kernel. A syntactically incorrect
output forces a retry — every retry pays the full retrieval +
context-assembly cost again. Sonnet's higher quality on
Mathlib-style syntax reduces the kernel-rejection rate enough that
the per-call cost increase pays for itself.

The brief's $1/$5 (Haiku) → $3/$15 (Sonnet) MTok rate change is a
3× per-token uplift; if Sonnet produces correct Lean on the first
attempt where Haiku would have needed two attempts, the net cost is
the same OR lower (because the second attempt would have included
the full retrieval prefix again).

### Why Haiku everywhere else

Retrieval turns are **tool-call planners**: the model decides which
tool to invoke with what arguments and writes a short JSON snippet.
Quality is bounded by tool-call discipline, not generation quality.
Haiku is fine.

Draft turns are intermediate prose (analysis, planning, context
assembly). The output is consumed by another agent or accumulated
into the next turn's context — it is NOT shown to a human reader.
Haiku is fine here too.

### Verification routes to Autoformalizer

The `RouteTag.VERIFICATION` value remains in `server/router.py` and
`server/prompts.py` for query classification + BP1 byte-identity.
But at dispatch time, a Verification-tagged query is executed by
the Autoformalizer agent. The model selection table reflects this
explicitly: `(VERIFICATION, X)` returns the same model as
`(AUTOFORMALIZATION, X)` for all `X`. See "Verifier pass: dropped
and why" below.

## Verifier pass: dropped and why

The v1 design originally had a dedicated **Verification agent**
that re-read retrieved chunks to validate proof steps. This pass
is **eliminated** (closes H10 in `.claude/roadmap/README.md`).

### The argument

The verifier reads from the same MCP corpus as the other agents.
If the retrieval system mis-ranked or omitted a relevant chunk,
the verifier is reading the same flawed evidence and cannot detect
the gap. The verifier's "validation" is circular — it can only
confirm that the cited claim is consistent with the retrieved
context, not that the retrieved context is correct.

For mathematical proofs, the **correct critic is the Lean kernel**:

1. **Independent of the retrieval corpus.** The kernel's check is
   over the formal proof object, not over the natural-language
   chunks the LLM consumed. A Lean proof that type-checks is sound
   regardless of whether the surrounding citations are correct.
2. **Formally sound.** The kernel rejects any unsound step by
   construction. The LLM verifier accepts any step it considers
   "consistent with the retrieved context" — a much weaker
   property.

### Operational impact

- **~25% reduction in per-query cost.** The Verification agent's
  retrieval + draft + critique sequence cost roughly 25% of the
  4-agent total in the previous design. Dropping it scales the
  4-agent fan-out from ~1.3–1.5× a single-agent call (per
  `.claude/notes/07-multi-agent-caching.md`) down toward ~1.0–1.2×.
- **Eliminates a category of false confidence.** A Verification
  pass that returns "valid" gives the user (and downstream
  systems) the impression of independent validation that does
  not exist. Removing the pass forces the user to either trust
  the kernel check OR accept that no formal validation has
  occurred.

### What replaces it

For Autoformalization queries: the Lean kernel is the verifier,
and it runs outside the agent pipeline (as part of the user's
Lean development environment, or a CI step that imports the
`.lean` output of the `LEAN_WRITE` turn).

For non-Autoformalization queries (Lookup, Synthesis): there is
no formal verification. The agent's output is grounded in the
cited chunks; the user reads the chunks to validate. This matches
the project's mission framing in `.claude/notes/01-mission-and-context.md`:

> *"Practical consequence: the adversarial critic role in a math
> pipeline is the least valuable LLM role. Lean's kernel error
> message is a better critic than another Claude. The valuable
> roles all live upstream of verification — and they all depend
> on having relevant prior work loaded."*

## Opus 4.7: deferred to v2

Claude Opus 4.7 is **not used** in the v1 model policy. The string
`"claude-opus"` deliberately does NOT appear anywhere under
`server/` (per E08_S05 AC #4); the deferral is a v1 freeze, not a
permanent ban.

### Why deferred

- **35% tokenizer expansion** relative to Sonnet 4.6. Per Anthropic's
  models overview (verified 2026-05): Opus 4.7's 1M-token context
  carries roughly 555K English words vs Sonnet 4.6's 750K — Opus
  tokenizes the same input into more tokens. The pipeline is
  retrieval-heavy (every retrieval round pays the prompt prefix
  cost), so a 35% input-token uplift is multiplied across every
  agent's every turn.
- **3× per-token rate uplift** vs Sonnet ($5/$25 vs $3/$15 MTok).
  Combined with the tokenizer expansion, Opus is ~4× the per-call
  cost of Sonnet for the same logical work.
- **Marginal quality lift** on Lean-syntax tasks. v1 evals will
  show whether Opus produces materially better Lean than Sonnet
  on the Autoformalizer write step. If yes, the cost may be
  justified for that single turn (only). v2 revisits.

### What "v2" means here

A future milestone (likely E08_S06 or later) revisits the policy
once eval data is available. The trigger to add Opus is a
demonstrated quality gap on the LEAN_WRITE turn that maps to a
measurable downstream cost (kernel-rejection retries) larger than
the Opus per-call uplift.

## Token-budget estimates

Approximate cost per query type, assuming a 4-agent fan-out with
3 turns per agent (1 retrieval, 1 draft, 1 final). Numbers are
order-of-magnitude estimates per Anthropic's published rates as
of 2026-05.

| Query type | Turn breakdown | Approx cost / query |
|---|---|---|
| Lookup-only | 4 agents × 3 Haiku turns × 2K input + 0.5K output | ~$0.054 |
| Synthesis | Same as Lookup; no Sonnet turn | ~$0.054 |
| Autoformalization | 11 Haiku turns + 1 Sonnet `LEAN_WRITE` (~3K input, 1K output) | ~$0.075 |
| Verification (routed to Autoformalization) | Same as Autoformalization | ~$0.075 |

### Worked example (Lookup-only row)

(F8 fix from the E08_S05 critique — show the arithmetic so a
future contributor updating Anthropic's pricing knows which
numbers to flex.)

- 4 agents × 3 turns/agent = **12 Haiku turns** total
- Per turn: 2,000 input tokens + 500 output tokens
- Haiku 4.5 rates: $1 / MTok input, $5 / MTok output
- Per-turn cost = $0.002 (input) + $0.0025 (output) = **$0.0045**
- Per-query cost = 12 × $0.0045 = **$0.054**

For Autoformalization: 11 Haiku turns ($0.0495) + 1 Sonnet
`LEAN_WRITE` (3K input @ $3/MTok = $0.009, 1K output @ $15/MTok =
$0.015 → $0.024) = **$0.0735 ≈ $0.075**.

Cache hit rates significantly reduce these numbers in practice.
Per `.claude/notes/07-multi-agent-caching.md`, BP1 (system + tools)
provides 80–95% input-token cache hits across the 4-agent fan-out
when prompt-cache discipline is honored (E08_S02 + E08_S04).

## Cache-invalidation discipline

(F3 fix from the E08_S05 critique.)

The Anthropic prompt cache is keyed on **model ID + prefix bytes**
(per `.claude/notes/07-multi-agent-caching.md` line 21–30). Any
change to a cell in `_SELECTION_TABLE` (e.g. promoting
`(SYNTHESIS, RETRIEVAL)` from Haiku to Sonnet for a quality
experiment) flips the model ID for that pair, which **invalidates
every cached prefix for that pair across all four agents**.

The change can land in a routine PR without anyone realizing the
cache-warming infrastructure now needs to re-warm from cold. To
prevent silent invalidation:

1. **Bump `POLICY_VERSION`** in
   `server/orchestrator/model_selector.py` whenever any cell in
   `_SELECTION_TABLE` changes value. Use semantic-version-style
   numbering: bump the patch digit for documentation-only changes,
   the minor digit for cell flips that don't change the model
   universe (e.g., promoting one cell from Haiku to Sonnet), and
   the major digit when a new model ID is added (e.g., the future
   Opus-as-LEAN_WRITE-only experiment).
2. **Add a CHANGELOG row to this document** under the table below
   with the date and rationale.
3. **PR description must cite the cache impact**: "This PR flips
   `(X, Y)` from `<old>` to `<new>`. The Anthropic prompt cache
   for that pair will be cold for the cache TTL window after merge."

A pinning test (`tests/test_model_selector.py::TestPolicyVersion`)
asserts `POLICY_VERSION` matches the expected value. Bumping the
constant is a deliberate, reviewable signal in the PR diff.

### CHANGELOG

| `POLICY_VERSION` | Date | Change |
|---|---|---|
| `1.0` | 2026-05-10 | Initial v1 policy: Haiku default, Sonnet for `(AUTOFORMALIZATION\|VERIFICATION, LEAN_WRITE)`, Opus deferred. `(LOOKUP\|SYNTHESIS, LEAN_WRITE)` forbidden (F1 fix). |

### Caveat — Haiku minimum cacheable prefix

Per `.claude/notes/07-multi-agent-caching.md` line 24: *"Min
cacheable prefix: ~1024 tokens for Sonnet/Opus, ~2048 for Haiku.
(Verify.)"* The Haiku minimum is DOUBLE the Sonnet minimum. If a
retrieval turn's full context (system + tools + role prefix +
problem) is under 2048 tokens, Haiku gets NO cache benefit and
the per-call cost is the full input rate. This narrows the cost
advantage of Haiku for the smallest turns. Operators should
verify the 2048 figure against current Anthropic docs before
treating it as load-bearing.

## Cross-references

- `server/orchestrator/model_selector.py` — the implementation
- `server/router.py` — `RouteTag` enum (E08_S01)
- `server/prompts.py` — `ROLE_PREFIXES` (E08_S02), including the
  Verification role prefix retained for BP1 byte-identity
- `.claude/notes/01-mission-and-context.md` — "Lean's kernel error
  message is a better critic than another Claude"
- `.claude/notes/07-multi-agent-caching.md` — cache prefix
  thresholds, 4-agent cost analysis
- `.claude/roadmap/README.md` — H10 (verifier-pass dropped)
- `tests/test_model_selector.py` — AC tests + forbidden-string
  check + table completeness
