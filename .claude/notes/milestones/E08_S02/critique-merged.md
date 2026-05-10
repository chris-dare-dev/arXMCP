# E08_S02 — Adversary Critique

## Executive summary

- **Verdict: PARTIAL.** All 24 tests pass and the deliverable surface
  (constants, doc, AST literal-only check) is honest, but two
  load-bearing acceptance criteria are softer than the brief
  demanded: AC #5 ("4-agent fan-out *integration* test confirming
  BP1 byte-identical") is met by a tautological synthetic-stub test
  whose `_build_fanout_request` discards the `tag` parameter for
  the BP1 region — see F1.
- The implementation summary's stated rationale for the synthetic
  stub ("`server.tools` import pulls lancedb / FastMCP — heavy")
  is **factually incorrect**: `import server.tools` runs in 9.6 ms
  on this box and lancedb is NOT imported transitively. The same
  test surface that `tests/test_server_tool_schema.py` already
  exercises in 0.5 s could be reused — see F1.
- The closed-at-four invariant is enforced by a bare `assert`
  statement. Running Python with `-O` strips it, leaving the
  invariant unenforced — see F4.
- The example code in `server/prompts.py`'s module docstring
  documents BP2 placement only and is **silently wrong** about
  BP1: it shows `"system": SYSTEM_PROMPT` as a raw string, which
  cannot carry a `cache_control` marker. E08_S04 will need to
  revisit the integration seam — see F2.
- A new prompt-injection surface introduced by this milestone
  (raw concatenation of attacker-controlled `problem_statement`
  with the role-prefix `[Role: …]` marker) is undocumented and
  has no test coverage. Threat 2 in
  `.claude/notes/08-security-observability-ops.md:18` covers
  retrieval-result injection but not user-input injection. See F3.
- The 200-char heuristic is conservative for English ASCII (we
  measured 32–37 cl100k tokens for the four prefixes via
  tiktoken) but VERIFICATION sits at 196/200 chars — a one-line
  tweak by a future contributor adding an em-dash or extending
  one clause overshoots. The cap also under-counts CJK / emoji
  by 4–8× — see F8.
- Cache byte-stability axis is otherwise clean for the bytes this
  milestone owns; the upstream tools/list hash pin (E06_S06)
  remains the load-bearing dependency.
- Test surface for AC #1 / #2 / #3 / #4 is real and proves what
  the brief asks. AC #5 is the weak link.

## Severity calibration

| Severity | Meaning |
|---|---|
| CRITICAL | Data loss, broken invariant, exploitable security flaw, or shipped behavior that contradicts the brief on the common path. |
| HIGH | Wrong behavior on a common path; AC ostensibly met but test is tautological/circular; integration seam misleading enough that a downstream milestone will have to redo this work. |
| MEDIUM | Subtle correctness gap, missing test for an edge case the brief implies, defense-in-depth that fails open. |
| LOW | Style, doc nit, paper-cut that won't compound. |

## Findings

### F1 — AC #5 BP1 byte-identity test is tautological; synthetic stub bypasses what the brief asked

- **Severity:** HIGH
- **File:** `tests/test_prompts.py:422-453, 481-496`
- **What:** The brief says: *"A 4-agent fan-out **integration test**
  confirms BP1 is byte-identical across all roles (hash equality
  check)."* The implemented test calls `_build_fanout_request(tag,
  problem)` which sets `"system": SYSTEM_PROMPT` and a fixed
  two-element `"tools"` list **regardless of `tag`**. Then
  `_bp1_hash` extracts only `{"system", "tools"}`. By
  construction the four hashes must be equal — the test would
  still pass if `ROLE_PREFIXES` were empty, if `RouteTag` had 17
  values, or if every role had the same prefix. It does not
  exercise the production tool-registration surface that BP1
  actually depends on.
- **Why:** AC #5 is the central acceptance check for the entire
  milestone. The implementation summary explicitly notes the
  deviation from synthesis D8 ("Synthetic stub tools list in BP1
  test") and justifies it: *"importing `server.tools` triggers
  FastMCP load + lancedb imports that are heavy"*. This claim is
  **demonstrably false**: `import server.tools` runs in 9.6 ms on
  this box and `lancedb` does NOT appear in `sys.modules` after
  the import. `tests/test_server_tool_schema.py` already imports
  the live tool surface and runs in 0.5 s. The current synthetic
  test does not actually verify that the production system+tools
  surface is byte-identical across the orchestrator's real
  fan-out — it only verifies that two stub strings hash to the
  same value four times.
- **Fix:** Either (a) replace `_build_fanout_request`'s synthetic
  stub list with the real `server.tools.list_tools()` output
  (mirror the `_build_app_and_list_tools` fixture from
  `tests/test_server_tool_schema.py:128-143`) and assert the
  resulting BP1 hash equals the value E06_S06 already pins
  (`EXPECTED_TOOL_SCHEMA_SHA256`), or (b) at minimum, vary the
  `tools` list construction by `tag` (e.g. via a dependency that
  *could* leak per-role state) and prove that the function does
  not in fact branch on `tag`. Option (a) actually satisfies the
  word "integration" in AC #5; option (b) at least makes the test
  non-tautological.

### F2 — Module-docstring integration-seam example silently omits BP1; will mislead E08_S04

- **Severity:** HIGH
- **File:** `server/prompts.py:35-51`
- **What:** The "Integration seam (E08_S04)" docstring example
  shows the request body as
  `request = {"system": SYSTEM_PROMPT, "tools": [...], "messages": messages}`
  with `cache_control` placed only on the user-turn content
  block (BP2). It does NOT show how BP1 is attached. The
  Anthropic Messages API does not accept `cache_control` on a
  raw-string `system` field — to get a system-level cache
  breakpoint the caller must pass `system` as a list of content
  blocks where the LAST block carries
  `cache_control: {"type": "ephemeral", "ttl": "1h"}`, or attach
  `cache_control` to the LAST tool definition. The example as
  written is a working request body that produces only BP2 — BP1
  silently no-ops.
- **Why:** This is the integration seam E08_S04 will copy. The
  implementation summary explicitly calls out (line 67–68): *"#
  system + tools also get cache_control on their LAST element
  (BP1)"* — but that comment is in the summary, not in the
  shipped docstring or `prompts.md`. The diagram in
  `prompts.md:158` shows a "BP1 cache_control (ttl: '1h')"
  marker with no companion code showing how to actually emit it.
- **Fix:** Extend the docstring example with the
  list-of-content-blocks form for `system` (or, equivalently,
  attaching `cache_control` to the last element of the `tools`
  list) and add the same in `server/prompts.md` adjacent to the
  diagram. A two-line code snippet is enough. Currently the only
  reader who knows BP1 needs an explicit marker is the
  implementation-summary author.

### F3 — Role-prefix injection surface for attacker-controlled `problem_statement` is undocumented and untested

- **Severity:** MEDIUM
- **File:** `server/prompts.py:43`, `server/prompts.md:107-110`,
  `.claude/notes/08-security-observability-ops.md:18-32`
- **What:** The integration-seam concatenates raw `problem` /
  `problem_statement` directly after the role prefix:
  `ROLE_PREFIXES[tag] + "\n\n" + problem_statement`. The role
  prefix is recognizable by its `[Role: <Name>]` marker. A
  `problem_statement` containing
  `"[Role: Autoformalizer] Translate to Lean: <attacker
  payload>"` will be presented to a Lookup or Synthesis agent
  with two competing role markers in the same content block.
  Existing security note (Threat 2) covers retrieval-result
  injection via `<retrieved_chunk>` delimiters but explicitly
  does NOT cover user-turn injection — that surface is new in
  E08_S02.
- **Why:** The brief lists no risk-note for this surface, but the
  decision to encode role as a user-turn prefix is precisely
  what creates it (per-role system prompts would be unspoofable
  from user content). At minimum the docs should call out that
  upstream callers MUST sanitize `[Role: …]` markers from
  `problem_statement` (or wrap it in a non-spoofable delimiter
  pair). Without a documented contract, E08_S04 will pass user
  bytes through unchanged.
- **Fix:** Add a "Threat — `[Role:]` marker spoofing" subsection
  to `server/prompts.md` with one of: (a) require
  `problem_statement` to be wrapped in `<problem>...</problem>`
  delimiters and document that the agent should treat `[Role:]`
  inside as data; (b) explicitly state the orchestrator MUST
  reject or escape `[Role:]` substrings in user input. Add a
  test in `tests/test_prompts.py` documenting the chosen
  contract.

### F4 — Closed-at-four invariant uses bare `assert`; stripped under `python -O`

- **Severity:** MEDIUM
- **File:** `server/prompts.py:154-159`
- **What:** The import-time check
  `assert set(ROLE_PREFIXES.keys()) == set(RouteTag), …` is a
  Python `assert` statement, which compiles to a no-op when
  Python is run with `-O` (PYTHONOPTIMIZE=1). I verified this
  locally: `python -O -c "import server.prompts"` succeeds even
  though the assert would fail if the dict were short. Production
  containers commonly set `PYTHONOPTIMIZE=1` to strip docstrings
  and asserts; in such environments the closed-at-four invariant
  is unenforced.
- **Why:** The docstring at lines 149-153 explicitly markets this
  as the load-bearing defense: *"A future fifth value … without
  updating this module breaks the import loudly"*. Under `-O` it
  doesn't break loudly — it returns `KeyError` at first
  agent-fan-out call. The defense advertised in the comment is
  not the defense actually provided.
- **Fix:** Replace the `assert` with an explicit
  `if … : raise RuntimeError(…)` block. Keep the message text;
  remove the keyword `assert`. Add a regression test that runs
  `python -O -c "import server.prompts"` (or
  `subprocess.run([sys.executable, "-O", "-c", "import server.prompts"])`)
  and verifies it raises when a synthetic mismatch is forced.

### F5 — `MappingProxyType` is defense-in-depth in name only; no test pins the contract

- **Severity:** LOW
- **File:** `server/prompts.py:137-142`,
  `tests/test_prompts.py:344-358`
- **What:** `ROLE_PREFIXES` is wrapped in `MappingProxyType` and
  the test suite asserts `__setitem__` / `__delitem__` raise
  `TypeError`. Both are true. But anyone can trivially escape
  the proxy via `dict(ROLE_PREFIXES)` (verified locally) and
  then mutate the copy. The implementation summary calls this
  "defense alongside the AST literal-only check"; the actual
  defense — a future contributor accidentally mutating
  `ROLE_PREFIXES` in another module — works only if the
  contributor *also* doesn't realize `dict(...)` exists.
- **Why:** The risk is small (the AST check is the real
  protection); the cost of the framing is that the
  implementation summary overstates the immutability guarantee.
- **Fix:** Either remove the `MappingProxyType` wrap (the AST
  check is sufficient) and document that fact, or add a comment
  acknowledging that `MappingProxyType` only blocks accidental
  in-place mutation, not `dict(ROLE_PREFIXES).pop(...)` style
  escapes.

### F6 — Verbatim AC #4 sentence test is brittle to common markdown edits

- **Severity:** LOW
- **File:** `tests/test_prompts.py:80-83, 376-385`
- **What:** The test does a substring check for the exact bytes
  `"BP3 is dropped; heterogeneous roles never share seed
  retrieval bytes"`. A future doc edit that adds emphasis
  (`**BP3 is dropped**; heterogeneous roles…`), or wraps the
  sentence onto two lines (markdown will still render fine but
  inserts a `\n` mid-sentence), or replaces the ASCII
  semicolon with a Unicode one (autocorrect — happens via
  some editors), or adds a leading bullet character will fail
  the test even though the doc still complies with the spirit
  of the AC.
- **Why:** The brief's AC says "explicitly states" — a literal
  byte-equal substring match is one valid reading; a more
  robust reading is "the sentence appears in normalized form".
  The current implementation is the strict reading and is
  acknowledged to be brittle (the doc deliberately repeats the
  sentence twice for survivability — a workaround for the
  fragility).
- **Fix:** Either accept the fragility (current state) and add a
  comment to `prompts.md` saying "do not edit either occurrence
  of the BP3-dropped sentence — see test
  `test_prompts_md_contains_ac4_sentence_verbatim`", or relax
  the test to normalize whitespace before substring matching
  (`"".join(text.split())`).

### F7 — `EXTENDED_CACHE_TTL_HEADER_VALUE` carries an unverified TTL string with no source-of-truth pin

- **Severity:** MEDIUM
- **File:** `server/prompts.py:71-72`,
  `.claude/notes/07-multi-agent-caching.md:27`
- **What:** The constant value `extended-cache-ttl-2025-04-11`
  is taken from `.claude/notes/07-multi-agent-caching.md:27`
  which itself says "(verify exact name)". The notes file has a
  caveat: *"Behavior is stable; specific TTL/pricing numbers may
  have shifted"* (line 12-16). The constant is shipped as
  load-bearing for the orchestrator's beta header but no
  verification was performed against Anthropic docs.
- **Why:** If the header name is wrong, BP1 falls back to 5-min
  TTL silently — the request still succeeds, the cache write
  expires three times faster, and the only signal is a
  degradation in cache-hit metrics that won't exist until
  E08_S04 ships. The brief is silent on this, but the
  research-brief-1 process should have produced a
  WebFetch-confirmed value.
- **Fix:** Add a TODO(E08_S04) comment in `server/prompts.py`
  near the constant: "Verify against Anthropic docs before the
  orchestrator's first live call." Or, better, add a CI
  smoke-test (skipped by default; run manually) that issues a
  prepared request with the header and asserts the response
  carries `cache_creation_input_tokens` for the 1h tier rather
  than 5m.

### F8 — 200-char token-cap heuristic under-counts non-ASCII; VERIFICATION sits at 196/200

- **Severity:** MEDIUM
- **File:** `tests/test_prompts.py:65, 90-101`,
  `server/prompts.py:96-101, 119-124`
- **What:** The 4 chars/token figure is Anthropic's published
  *English ASCII* average. CJK characters tokenize to ~1
  token/char in BPE tokenizers; a 200-char Chinese prefix would
  be ~200 tokens, 4× over cap. Emoji characters (multi-byte
  UTF-8) commonly tokenize to 2-4 tokens each. The test
  comment acknowledges *"our prefixes are pure English
  imperative"* but the cap does not enforce that constraint —
  a future contributor adding `[Role: 验证]` is silently allowed.
  Separately, the VERIFICATION prefix is 196/200 chars;
  appending one em-dash or any 4–5-character clause overshoots
  silently.
- **Why:** The brief mandates "≤ 50 tokens (Claude Sonnet 4.6
  tokenizer)". The 200-char heuristic is conservative for one
  textual regime and unconservative for another. With tiktoken
  cl100k as a proxy I measured 32–37 tokens for the current
  prefixes — comfortably under 50. But the test does not
  encode that headroom; it only encodes the 200-char ceiling.
- **Fix:** Either (a) add an ASCII-only assertion
  (`assert prefix.isascii()`) to the existing test, narrowing
  the heuristic's domain to where it's valid; or (b) add
  `tiktoken` as a dev-only dep and assert
  `len(enc.encode(prefix)) <= 45` (5-token headroom under the
  50 cap, since cl100k is a proxy); or (c) trim VERIFICATION
  to ~150 chars to recreate the headroom that the other three
  prefixes have.

### F9 — `prompts.md` cross-reference points at lines that may drift

- **Severity:** LOW
- **File:** `server/prompts.md:185-189`
- **What:** Cross-reference to `.claude/notes/07-multi-agent-caching.md:74-82`
  is a line-range citation. If anyone edits the upstream notes
  file (and they will — note line 12 explicitly invites
  verification revisits), the citation rots silently. Same for
  `.claude/roadmap/README.md:69`.
- **Why:** Line-anchored citations to non-versioned files are
  fragile. The notes file is the constitutional source per the
  cross-ref's own admission, so it WILL be edited.
- **Fix:** Replace `:74-82` with a section anchor like
  `#property-3-breakpoint-placement-is-deliberate` (markdown
  rendering on GitHub generates these), or quote the relevant
  prose directly into `prompts.md` and remove the line numbers.

### F10 — `_REQUIRED_KEYS` analog absent from `prompts.py`; mismatch between import-time and AST validation paths

- **Severity:** LOW
- **File:** `server/prompts.py:154-159`,
  `tests/test_prompts.py:223-283`
- **What:** The AST literal-only test walks `ROLE_PREFIXES.keys`
  / `.values` looking for unwrapped `MappingProxyType(<Dict>)`.
  If a future contributor refactors to a different shape (e.g.
  stores prefixes in a dataclass, or uses dict comprehension),
  the AST visitor's `assert isinstance(inner_dict, ast.Dict)`
  fails with "ROLE_PREFIXES value must be a Dict literal". The
  failure mode is correct but the error message implies a
  contract that isn't documented in `prompts.py` itself. A
  reader of the source has no comment saying "do not refactor
  this dict literal away — the AST test depends on its
  structure".
- **Why:** The dependency is one-way (test → source) and not
  obvious from the source. Adds a future-paper-cut risk.
- **Fix:** Add a comment above the `ROLE_PREFIXES = MappingProxyType({...})`
  block: "# DO NOT refactor: tests/test_prompts.py AST-walks this
  exact dict-literal-inside-MappingProxyType-call shape."

### F11 — Implementation summary table cites char counts that don't match shipped prefixes

- **Severity:** LOW
- **File:** `.claude/notes/milestones/E08_S02/implementation-summary.md:21`,
  `.claude/notes/milestones/E08_S02/research-synthesis.md:42-61`
- **What:** Implementation summary line 21 says
  *"All four prefixes measure 136–177 chars"*. Actual measured
  values (verified locally): LOOKUP=156, SYNTHESIS=157,
  VERIFICATION=196, AUTOFORMALIZATION=170. The 196-char
  VERIFICATION value is the load-bearing data point that
  motivates F8 — it's been silently miscited as "177" (which
  matches the synthesis-doc's older estimate, not the shipped
  string). The reader is told there's more headroom than there
  is.
- **Why:** Misleads the critic / future maintainer about how
  close the prefixes are to the cap.
- **Fix:** Update the summary's range to "156–196 chars" and
  call attention to VERIFICATION specifically being ~98% of the
  cap. (Pure-internal note; no source change required.)

### F12 — `AC #5` test does NOT include the role prefix in the bytes hashed; the "sanity check" `test_role_prefix_lives_in_user_turn_not_bp1` is the only thing that *would* catch a regression and it tests one role only

- **Severity:** MEDIUM
- **File:** `tests/test_prompts.py:513-529`
- **What:** `test_role_prefix_lives_in_user_turn_not_bp1` searches
  for the substring `"[Role: Autoformalizer]"` in the BP1 region
  for `RouteTag.AUTOFORMALIZATION` only. It is the only test
  that would catch a refactor where someone moves the role
  prefix into the system prompt for, say, LOOKUP. If a future
  edit moves only the LOOKUP prefix into the system prompt
  (silly, but possible), this test passes.
- **Why:** Belt-and-suspenders against the central failure mode
  of the milestone (role bleeding into BP1) is exercised for
  one of four roles. A `pytest.mark.parametrize` over
  `RouteTag` would cost one line.
- **Fix:** Parametrize over `list(RouteTag)`:
  `@pytest.mark.parametrize("tag", list(RouteTag))` and assert
  `f"[Role: {tag.name.title()}…"` (or the literal prefix
  marker for each tag) is absent from the BP1 bytes.

### F13 — Cache byte-stability axis: AC #5 does not pin the SHA256, so a silent BP1-prefix change doesn't fail any test

- **Severity:** MEDIUM
- **File:** `tests/test_prompts.py:498-511`,
  `.claude/notes/milestones/E08_S02/research-synthesis.md:70`
- **What:** Synthesis open question 2 explicitly notes the
  decision to NOT pin `EXPECTED_BP1_SHA256`: *"The hash depends
  on the placeholder `SYSTEM_PROMPT`; pinning now means E08_S04
  must update the constant when the real system prompt lands."*
  The structural assertion (4 hashes equal each other) cannot
  detect a change that affects all four roles uniformly — e.g.
  a contributor reformatting `SYSTEM_PROMPT` whitespace, adding
  a new tool, or reordering tool fields. The
  `tests/test_server_tool_schema.py` hash pin catches the
  tools-side drift but no test pins the
  `(SYSTEM_PROMPT, tools)` joint surface that BP1 actually
  is. So a uniform BP1 change ships silently.
- **Why:** The brief's AC #5 is "BP1 byte-identical across
  roles" — the structural test does prove that. But the
  *intent* of byte-identity is to prevent silent regressions
  from invalidating cache; uniform-but-changed BP1 invalidates
  the cache identically across all four roles, which the test
  does not catch. The placeholder rationale is fair but
  forfeits a regression detector.
- **Fix:** Add an `EXPECTED_BP1_SHA256` pin (or a SHA256 of the
  *placeholder*) gated by a `--update-bp1-hash` flag mirroring
  the E06_S06 pattern. Document that E08_S04 will need to bump
  the constant when the real system prompt lands.

## What was done well

- **AST literal-only visitor is well-targeted.** The visitor
  correctly rejects `JoinedStr` (f-strings, including
  no-placeholder ones — verified), `Call` (covers `.format`
  and `.join`), `BinOp` (covers `+`-concatenation and `%`),
  `Name` (variable references), `Attribute`, and `IfExp`. The
  failure messages are actionable.
- **Implicit string concatenation correctly handled.** Python
  parses `("foo" "bar")` to a single `Constant` (not BinOp),
  so the four parenthesized prefixes pass cleanly without
  needing to whitelist concatenation. This is the right shape.
- **Canonical-JSON helper mirrors the E06_S06 discipline.**
  `_canonical_json` reuses `sort_keys=True, separators=(",",":"),
  ensure_ascii=True` — the same three flags used in the
  tools/list hash pin. Reduces cognitive load.
- **The `prompts.md` doc explicitly states the AC #4 sentence
  twice.** Pragmatic survivability against doc edits — even
  though F6 still calls out the brittleness of byte-exact
  matching, having two occurrences is meaningfully better than
  one.
- **`SYSTEM_PROMPT` placeholder carries an explicit
  `TODO(E08_S04)` marker.** Future-author finds the right line
  without grepping. (Marker is at `server/prompts.py:83-84`.)
- **No fork: nothing was lifted from existing arxiv-mcp repos.**
  Grep for `arxiv-mcp` / `blazickjp` / `MCP-arxiv` returns no
  hits in the new files.
- **Tier sequencing clean.** `from server.router import RouteTag`
  matches the E08_S01 surface; `RouteTag` is a `StrEnum` with
  the expected four values.
- **Module docstring's "Closes H2" cross-reference is precise.**
  Cites `.claude/roadmap/README.md:69` (which I verified maps
  to the H2 row) and the corresponding `.claude/notes/07-…:320-326`
  for the cache-hit-rate claim.
- **Test class organization mirrors AC structure.** Each AC has
  its own test class with a docstring naming the AC. A reader
  can map test failures to brief sections in seconds.
- **No new runtime deps.** `from types import MappingProxyType`
  is stdlib; `import ast`, `import hashlib`, `import json` in
  the test file are stdlib. Project's no-new-deps discipline
  preserved.

## Recommended rectification order

1. **F1** (HIGH) — replace synthetic stub with real `server.tools`
   surface, OR at minimum vary `tools` by `tag` to prove
   non-tautology. Restores AC #5's actual assurance.
2. **F2** (HIGH) — fix the docstring example to show BP1
   placement (system as content-block list OR cache_control on
   last tool). Without this, E08_S04 ships with no BP1 marker.
3. **F4** (MEDIUM) — convert the `assert` to
   `if … raise RuntimeError`. One-line edit, eliminates `-O`
   strip risk.
4. **F3** (MEDIUM) — document the `[Role:]` injection surface in
   `prompts.md` and either require sanitization in the
   integration seam or wrap `problem_statement` in a delimiter.
5. **F8** (MEDIUM) — narrow the 200-char cap to ASCII-only OR
   add `tiktoken`-based assertion with 5-token headroom. Trim
   VERIFICATION if cap stays char-based.
6. **F12** (MEDIUM) — parametrize the BP1-leak sanity check
   over all four `RouteTag` values.
7. **F13** (MEDIUM) — add an `EXPECTED_BP1_SHA256` pin with the
   placeholder hash and a documented update path for E08_S04.
8. **F7** (MEDIUM) — TODO comment + verification guidance for
   the beta-header constant.
9. **F11** (LOW) — fix implementation-summary char-count range.
10. **F5, F6, F9, F10** (LOW) — pick up as paper-cuts.

## Rectification status

Re-verified all CRITICAL+HIGH and MEDIUM findings against the cited
file:line ranges before any fix. F1's claim that
`import server.tools` runs in ~25 ms with NO `lancedb` import was
independently verified (`python -c "import time; t=time.perf_counter();
import server.tools; …"` → 25.2 ms; `lancedb` not in `sys.modules`).

Fixed in the rectification commit:

- **F1** (HIGH) — fixed. `tests/test_prompts.py:_build_fanout_request`
  now uses `server.tools.ALL_TOOLS` (live frozen `ToolMeta` registry)
  instead of the synthetic 2-element stub. The BP1 hash test now
  exercises the production tool surface that BP1 actually depends
  on, and the hash drift is correlated with E06_S06's
  `EXPECTED_TOOL_SCHEMA_SHA256`.
- **F2** (HIGH) — fixed. `server/prompts.py` module docstring's
  integration-seam example now wraps `system` as a list of content
  blocks with `cache_control` on the LAST block (the form that
  actually emits BP1 per the Anthropic Messages API). Same fix
  applied to `server/prompts.md`'s "BP1 — System + tool definitions"
  section adjacent to the diagram. The pre-fix example would have
  silently no-op'd BP1 for E08_S04.
- **F3** (MEDIUM) — fixed (docs). Added a dedicated
  "Security — `[Role:]` injection from user-controlled input"
  section to `server/prompts.md` documenting the threat and the
  three contracts the orchestrator MAY enforce (reject / escape /
  delimiter-wrap). Cross-referenced from `server/prompts.py`'s
  module docstring. Enforcement is left to E08_S04 because this
  module is pure constants.
- **F4** (MEDIUM) — fixed. Replaced the bare `assert
  set(ROLE_PREFIXES.keys()) == set(RouteTag), …` with `if
  set(ROLE_PREFIXES.keys()) != set(RouteTag): raise RuntimeError(…)`.
  Regression guard: `test_closed_at_four_check_survives_dash_O`
  spawns `python -O -c "import server.prompts"` and asserts it
  succeeds, AND greps the source to confirm the `assert` form has
  not reappeared.
- **F7** (MEDIUM) — fixed. Added `TODO(E08_S04)` block-comment
  above `EXTENDED_CACHE_TTL_HEADER_VALUE` flagging the
  "verify exact name" caveat from `.claude/notes/07-multi-agent-caching.md:27`
  and noting the silent-5-min-fallback failure mode.
- **F8** (MEDIUM) — fixed. Added
  `TestPrefixTokenCap::test_prefix_is_ascii_only` parametrized over
  every `RouteTag`, asserting `prefix.isascii()`. Narrows the
  heuristic's domain to where the 4 chars/token rate is valid; a
  future contributor adding non-ASCII (CJK, emoji) is caught here
  rather than silently shipping over-cap. VERIFICATION trim
  declined; the test now documents 98% of cap explicitly.
- **F12** (MEDIUM) — fixed. `test_role_prefix_lives_in_user_turn_not_bp1`
  is now `@pytest.mark.parametrize("tag", list(RouteTag))`-decorated,
  exercising the BP1-leak sanity check for every role rather than
  just AUTOFORMALIZATION.
- **F13** (MEDIUM) — fixed. Added `test_bp1_hash_pinned` with
  `EXPECTED_BP1_SHA256 = "f01de11288…"` (computed from the
  placeholder `SYSTEM_PROMPT` + live `ALL_TOOLS`). Documented the
  update procedure in the test docstring (mirror E06_S06's pattern;
  edit the literal when E08_S04 lands the real system prompt).
  Catches the previously-missed failure mode of "BP1 changes
  uniformly across all 4 roles" — invalidates cache silently in
  the structural-only test.
- **F11** (LOW) — fixed inline. Implementation summary char-count
  range corrected from "136–177" to per-prefix breakdown with
  VERIFICATION at 196/200 (98% of cap) called out explicitly.

Deferred (per rectifier protocol — fix as paper-cuts in a future pass):

- **F5** (LOW) — `MappingProxyType` defense-in-depth framing. The
  AST literal-only check is the real protection; the mapping-proxy
  is belt-and-suspenders. Cost > value to either remove the wrap
  or add a comment about `dict(...)` escape.
- **F6** (LOW) — verbatim-substring match brittleness. The doc
  deliberately includes the sentence twice for survivability; the
  fragility is acknowledged.
- **F9** (LOW) — line-anchored cross-references. Section anchors
  would be cleaner but the cited files are project-internal and
  reviewed at the same time `prompts.md` is.
- **F10** (LOW) — "do not refactor this dict literal" warning
  comment. The AST visitor's failure message is already actionable.

Test additions (regression guards):

- `test_prefix_is_ascii_only[<tag>]` × 4 — F8 guard.
- `test_role_prefix_lives_in_user_turn_not_bp1[<tag>]` × 4 — F12
  guard (replaces the single-tag test).
- `test_bp1_hash_pinned` — F13 guard.
- `test_closed_at_four_check_survives_dash_O` — F4 guard.

Final test count: 33 passed (was 24). Full suite: 1038 passed,
4 skipped. `ruff check .` clean.

Inner-loop attempt counts: F1 → 1 attempt; F2 → 1; F3 → 1; F4 → 1;
F7 → 1; F8 → 1; F12 → 1; F13 → 2 (first attempt used a placeholder
hash that the second attempt replaced with the actual computed
value). All under the 3-attempt cap.

Outer-loop iterations: 1 (single full-suite run after batched
fixes). Under the 3-iteration cap.

Invalidation rate: 0/2 HIGH (0%) and 0/6 MEDIUM (0%). Below the
40% threshold that would signal a broken critic prompt.
