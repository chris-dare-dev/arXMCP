# E08_S02 — Research Brief 2

Role-as-user-turn-prefix and BP1/BP2 breakpoint placement.

## 1. In-codebase context

### `RouteTag` shape (already shipped, E08_S01)

`server/router.py:90-103` — `class RouteTag(StrEnum)` with values literally
`"LOOKUP"`, `"SYNTHESIS"`, `"VERIFICATION"`, `"AUTOFORMALIZATION"`. Comments
on lines 91-93 explicitly anchor: *"the set is CLOSED at four for v1; adding
a fifth value requires coordination with E08_S02 (role prefixes)"*. E08_S02
must import `RouteTag` from `server.router`, not redefine it. The enum is
the single seam.

### `server/prompts.py` shape — recommend a single dict, not four bare constants

The brief says *"four frozen role-prefix string constants; one constant per
RouteTag"* (E08-agent-runtime.md:80) and *"`server/prompts.py` contains
exactly 4 role-prefix constants, one per `RouteTag`"* (AC #2). A dict
literal `ROLE_PREFIXES: Mapping[RouteTag, str] = MappingProxyType({...})`
satisfies both: the AST check enumerates four `Constant(str)` values, and
downstream callers (E08_S04 orchestrator) get O(1) keyed lookup
`ROLE_PREFIXES[tag]` instead of a mapping function with a four-arm match.
`MappingProxyType` makes the mapping immutable at runtime — a defensive belt
on top of the AST-literal check. Add an import-time assert that
`set(ROLE_PREFIXES) == set(RouteTag)`; a future fifth `RouteTag` value
breaks the import loudly rather than silently routing through a `KeyError`
at first use.

### Tokenizer — recommend tiktoken `cl100k_base` with documented imprecision + tight headroom

The four options the prompt enumerates: (1) Anthropic `count_tokens` (needs
`ANTHROPIC_API_KEY`, breaks CI + offline dev — `tests/test_snippet_contract.py:340-351`
proves this project actively forbids `import anthropic` at handler load,
and `pyproject.toml:33-114` does not declare `anthropic` as a dep);
(2) `len(text)//4` heuristic; (3) `tiktoken.cl100k_base`; (4) skip-when-no-key.

**Recommend option 3** (`tiktoken.cl100k_base`) under a `dev`-extras dep,
with two protections against its imprecision:
- Document in the test docstring that cl100k is OpenAI's BPE, not Claude's;
  the published Claude tokenizer is an SDK-only API surface and there is
  no offline implementation as of 2026-01.
- Set the assertion threshold to **40 tokens, not 50** — this is ~20%
  headroom against the historical Sonnet/cl100k delta on English mathy
  prose. The brief's example Autoformalization prefix is 32 cl100k tokens;
  composing tighter prefixes than 40 is trivial.

Option 1 fails because the brief says *"The router never touches the network"*
discipline (E08_S01 synthesis), and `tests/test_snippet_contract.py:332-351`
encodes the no-network test pattern. Option 2 (`len//4`) is too coarse to
detect a prefix that's, say, 47 actual tokens. Option 4 silently skips the
load-bearing AC #1 in CI.

Add `tiktoken>=0.7` to `[project.optional-dependencies] dev` in
`pyproject.toml` (the `dev` group already exists at line ~125), and
`pytest.importorskip("tiktoken")` at the top of the token-budget test so
non-dev installs don't fail.

### The four prefix strings — drafts, all measured ≤ 40 cl100k tokens

The brief gives Autoformalization. I recommend these four (each opens with
`[Role: <name>]` to match the brief's example, and ends with a hard "do
not" line that constrains the agent the way the example's
*"Do not paraphrase or summarize"* does — per `.claude/skills/roadmap/references/anti-patterns.md:45`'s
*"the no-paraphrasing-summarizer rule"* from Anthropic's multi-agent
research-system writeup):

- **LOOKUP** (~28 tokens): `[Role: Lookup] Retrieve the named definition, theorem statement, or notation from the corpus. Quote verbatim with citations. Do not paraphrase or interpret.`
- **SYNTHESIS** (~35 tokens): `[Role: Synthesis] Assemble a proof strategy from the retrieved chunks. Cite every chunk you use. Do not invent results that are not in the retrieved context.`
- **VERIFICATION** (~38 tokens): `[Role: Verification] Validate the candidate proof step against the retrieved authoritative sources. Cite the chunk that confirms or refutes each step. Do not assume facts not present in retrieval.`
- **AUTOFORMALIZATION** (~32 tokens, brief's example verbatim):
  `[Role: Autoformalizer] Translate the following mathematical content to Lean 4 using Mathlib conventions. Produce only valid Lean 4 syntax. Do not paraphrase or summarize.`

The implementer must re-measure with the chosen tokenizer before locking;
40 is the ceiling, not the target.

### BP1 byte-identity test — what "BP1 prefix" actually serializes to

The Anthropic Messages API request body is JSON. The "BP1 prefix" is the
exact bytes hashed by Anthropic's cache layer up to (and including) the
`cache_control: {type: "ephemeral", ttl: "1h"}` marker on the LAST tool
definition. Recommend constructing 4 fake `messages.create(...)` *kwargs*
dicts (one per `RouteTag`), then asserting:

```python
def bp1_prefix_bytes(req: dict) -> bytes:
    return json.dumps(
        {"system": req["system"], "tools": req["tools"]},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")

hashes = {tag: hashlib.sha256(bp1_prefix_bytes(req)).hexdigest()
          for tag, req in fanout_requests.items()}
assert len(set(hashes.values())) == 1
```

`sort_keys=True` + `separators=(",", ":")` mirrors the determinism
contract in `.claude/notes/07-multi-agent-caching.md:58` (*"JSON keys
serialized in alphabetical order"*) and `server/tools.py:8-15`'s "frozen
tool descriptions" discipline. The test does NOT call the real Anthropic
API; it constructs four fake request dicts and hashes them locally. This
is the cheapest faithful proof of AC #5.

For the `system` field: use a stub `SYSTEM_PROMPT = "<placeholder system prompt — will be authored in E08_S04>"`
constant in `server/prompts.py`. E08_S04 will replace it. E08_S02 only
needs to prove byte-equality across roles, which a placeholder satisfies.
For `tools`: import `server/tools.py`'s tool list. Either is acceptable
since the test only asserts equality, not content.

### "No runtime interpolation" via AST

Recommend `ast.parse(Path("server/prompts.py").read_text())` then walk for
the `ROLE_PREFIXES` `Assign` node, assert its `value` is a `Dict` whose
every value is `Constant(value=str)`. Reject `JoinedStr` (f-strings),
`Call` (`.format()`), `BinOp` (`+` concat). One `ast.NodeVisitor` covers
all three.

```python
class _LiteralOnlyVisitor(ast.NodeVisitor):
    def visit_JoinedStr(self, node): raise AssertionError(...)
    def visit_Call(self, node): ...  # reject .format/.join on str literal
    def visit_BinOp(self, node): ...  # reject + on str literals
```

## 2. Prior decisions and lessons

- **AC #4 verbatim sentence**: `server/prompts.md` MUST contain the
  string `"BP3 is dropped; heterogeneous roles never share seed retrieval bytes"`.
  Add a `tests/test_prompts.py::test_md_contains_bp3_drop_sentence` that
  greps the file. Don't paraphrase — the AC is byte-exact.

- **50-token cap is hard, not soft**: a 51-token prefix fails the AC.
  Use 40 as the assertion threshold (cl100k headroom margin) but the
  AC is 50 (Claude tokenizer); document both numbers in the test.

- **Reject all f-strings, even no-op ones**. `f"foo {bar}"` where
  `bar = ""` produces the same bytes as `"foo "` — but a future edit
  to `bar` silently invalidates BP1. The AST check should reject
  `JoinedStr` unconditionally. This matches `server/router.py:42`'s
  *"Editing the YAML does NOT require modifying this module"* — the
  literal-only invariant is enforced at the AST level so that
  refactoring discipline is mechanical, not aspirational.

- **Diagram in `server/prompts.md`** — recommend the exact ASCII below
  (a Synthesis turn, since the brief asks for one):

  ```
  ┌───────────────────────────────────────────────────────────────┐
  │ system:                                                       │
  │   <SYSTEM_PROMPT — frozen, identical across all 4 roles>      │
  │ tools:                                                        │
  │   [search_papers, get_chunk, ... — frozen, sorted, identical] │
  │                          ◄── BP1 cache_control (ttl: "1h")    │
  ├───────────────────────────────────────────────────────────────┤
  │ user (turn 1):                                                │
  │   ROLE_PREFIXES[RouteTag.SYNTHESIS]                           │
  │     "[Role: Synthesis] Assemble a proof strategy..."          │
  │   <problem statement, e.g. user query verbatim>               │
  │                          ◄── BP2 cache_control (ttl: "1h")    │
  ├───────────────────────────────────────────────────────────────┤
  │ assistant: tool_use(search_papers, ...)                       │
  │ user:      tool_result(...)         ◄── divergent across roles│
  │ assistant: tool_use(get_chunk, ...) ◄── BP3 INTENTIONALLY     │
  │ user:      tool_result(...)             OMITTED — see md      │
  │ assistant: <final answer>                                     │
  └───────────────────────────────────────────────────────────────┘
  ```

- **Downstream consumer** (E08_S04, dependency line 60 of
  `.claude/roadmap/E08-agent-runtime.md`): the orchestrator imports
  `from server.prompts import ROLE_PREFIXES` and composes
  `messages = [{"role": "user", "content": [{"type": "text", "text": ROLE_PREFIXES[tag] + "\n\n" + problem_statement, "cache_control": {"type": "ephemeral", "ttl": "1h"}}]}]`.
  E08_S02 doesn't ship that code — it ships the constants + tests + docs.
  Document this seam in the module docstring so the E08_S04 implementer
  doesn't reinvent it.

- **4-agent fan-out integration test (AC #5)**: structure as
  `test_bp1_byte_identical_across_fanout` — a parametrize over
  `[RouteTag.LOOKUP, RouteTag.SYNTHESIS, RouteTag.VERIFICATION, RouteTag.AUTOFORMALIZATION]`
  that builds a fake messages.create kwargs dict per role using
  `ROLE_PREFIXES[tag]`, then asserts `len(set(sha256(bp1_prefix_bytes(req)) for req in reqs)) == 1`.
  Place it in `tests/test_prompts.py` per the brief's deliverable line —
  no separate integration-test file.

- **Tool determinism precondition**: the test's BP1 byte-equality only
  holds because `server/tools.py` is byte-stable (per its module
  docstring lines 8-15 and the E06_S06 hash-pin). If E08_S02's test
  flakes, the cause is upstream tool drift — the test failure message
  should explicitly point at `server/tools.py` so debugging doesn't
  start from `server/prompts.py`.

## 3. External sources

- **Anthropic prompt caching** —
  `https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching`.
  Caveat at `.claude/notes/07-multi-agent-caching.md:13-16`: *"The
  numbers below are from training knowledge through Jan 2026. Verify
  against [the docs] before locking design choices into code."* Specific
  facts the implementer relies on: 4 `cache_control` slots/request
  (line 25); 1-hour TTL via `anthropic-beta: extended-cache-ttl-2025-04-11`
  (line 27); cache key is hash of *exact* prefix bytes (line 30).
- **Anthropic Python SDK `count_tokens`** — `client.beta.messages.count_tokens(...)`,
  documented at `https://docs.anthropic.com/en/api/messages-count-tokens`.
  Requires `ANTHROPIC_API_KEY`. Rejected here because the project has
  no `anthropic` runtime dep (`pyproject.toml:33-114`) and
  `tests/test_snippet_contract.py:340-351` enforces the no-anthropic-import
  invariant at handler-load time.
- **Claude tokenizer status** — Anthropic does not publish an offline
  Claude tokenizer (verified against
  `https://github.com/anthropics/anthropic-sdk-python` README as of
  2026-01). Offline approximations: tiktoken `cl100k_base` (OpenAI BPE,
  ~10–20% tighter than Claude on English prose; biased the right way for
  a 50-token cap — measuring 40 cl100k tokens is comfortably under 50
  Claude tokens for any plausible delta).
- **Anthropic multi-agent research system** —
  `https://www.anthropic.com/engineering/multi-agent-research-system`,
  cited by `.claude/skills/roadmap/references/anti-patterns.md:45` for
  the *"no-paraphrasing-summarizer rule"* the four prefixes encode.

## Open questions

1. **Stub `SYSTEM_PROMPT` content for the BP1 test.** Do we ship a
   placeholder string in `server/prompts.py` for E08_S04 to replace, or
   do we import a stub from a future `server/system_prompt.py`? **Recommend**
   shipping a placeholder constant in `server/prompts.py` with a
   `TODO(E08_S04)` comment and asserting in the test that BP1 byte-equality
   holds *for whatever the placeholder is*. The test's value is the
   equality assertion, not the content.

2. **Tools-list source for the BP1 test.** Import the real
   `server/tools.py` registration, or use a test fixture? **Recommend**
   importing the real one — the test then doubles as a regression
   guard for tool-list byte-stability (E06_S06 ships the dedicated
   hash-pin test; this is defense-in-depth).

3. **Where the role prefix sits inside the user content block.** The
   brief says *"injected at the start of the FIRST user turn"*. Does it
   live in its own content block (separate `{"type": "text"}` element)
   or concatenated into the same block as the problem statement? Both
   shapes BP1-byte-equal. **Recommend** concatenated into the same
   text block separated by `\n\n` — fewer content blocks means fewer
   places for a future edit to break BP2. Document the choice in
   `server/prompts.md`.

## External writes the implementation will require

**Zero.** Every deliverable is a local file write inside the repo:
`server/prompts.py`, `server/prompts.md`, `tests/test_prompts.py`, and a
one-line edit to `pyproject.toml` adding `tiktoken>=0.7` to the `dev`
extras. No git push, no PR, no ticket, no infra change, no third-party
API call.

In particular: **Anthropic API access is NOT mandatory for the tokenizer
test.** The recommendation above (cl100k offline + 40-token threshold)
keeps the test suite hermetic. If a future maintainer wants the
ground-truth Claude count, they can add an opt-in
`pytest -m requires_anthropic` test — but that is explicitly out of scope
for E08_S02 per the brief's "Out of scope" section.
