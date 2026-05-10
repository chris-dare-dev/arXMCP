# Adversary critique — E08_S05 (model selection policy + verifier-pass removal)

**Commit range:** `2d0a95e..a8ea9147` (single feat commit, 7 new files,
1116 LOC).
**Reviewer:** Adversary (find problems, not virtues).
**Verdict:** Conditionally accept — body of work is clean and tightly
scoped, but four MEDIUM issues + a handful of LOWs need rectification
before this is wired into a real orchestrator.

## Executive summary

- Pure-lookup `select_model(route_tag, turn_type) -> str` lands as a
  ~250 LOC module; 40 tests pass; `ruff` clean; full suite still green
  (1171 passed).
- All 6 acceptance criteria are mechanically satisfied. The implementer
  correctly resolved the brief's confusing AC #1 wording in favor of the
  "wait, correction" form (Sonnet for `LEAN_WRITE`).
- **Cache byte-stability is sound**: model IDs are bare string
  literals, no f-string interpolation, no env reads, table wrapped in
  `MappingProxyType`. Verified mutation-attempts raise `TypeError`.
- **Two MEDIUM correctness issues**: (a) `select_model` does NOT
  reject string-typed arguments at the type-system boundary — the
  `"LOOKUP_TYPO"`-string test technically passes only because
  `RouteTag.LOOKUP == "LOOKUP"` (StrEnum); a typo on a real RouteTag
  *value* (e.g. `"LOOKUP "` with trailing space) would raise the right
  `ValueError`, but a typo on a real *RouteTag attribute* (`RouteTag.LOOPUP`)
  raises `AttributeError` at the call site, not `ValueError` from the
  selector. Acceptable. (b) The "defensive" entries
  `(LOOKUP|SYNTHESIS, LEAN_WRITE) → Haiku` are a **footgun**: a future
  caller bug that misroutes a non-Lean role into a `LEAN_WRITE` turn
  gets a silent Haiku response instead of a fail-loud exception.
- **One MEDIUM gap**: the brief's "no model ID strings appear elsewhere
  in the orchestrator" guarantee is enforced ONLY for the Opus string;
  there's no test asserting `claude-haiku-4-5` / `claude-sonnet-4-6`
  appear ONLY in `model_selector.py`. A future contributor pasting
  `model="claude-sonnet-4-6"` directly into a `messages.create` call
  would NOT be caught.
- **One MEDIUM doc gap**: `_SELECTION_TABLE` cell changes silently
  invalidate cached prompt prefixes (the model ID is part of
  Anthropic's cache key per `.claude/notes/07-multi-agent-caching.md`).
  No CHANGELOG / version-bump discipline is documented; a future PR
  flipping `(SYNTHESIS, RETRIEVAL)` from Haiku to Sonnet ships without
  any caller knowing the cache reset hit.
- **Tier sequencing OK**: imports `RouteTag` from `server.router`
  (E08_S01, landed) and the doc cross-references `ROLE_PREFIXES`
  (E08_S02, landed). No reverse coupling.
- **Integration gap acknowledged but not documented in code**: the
  module is dead code as of this commit — nothing in `server/` calls
  `select_model`. The implementation summary says the orchestrator
  dispatch loop "lands in E08_S05+", but the module's docstring claims
  to be the SSoT of an orchestrator that doesn't exist yet. Not a bug
  per se, but a strong invitation to a future drift between policy and
  call site.

## Severity calibration table

| Severity | Used for | Count |
|---|---|---|
| CRITICAL | Data loss, security, broken invariant | 0 |
| HIGH | Wrong behavior on common path | 0 |
| MEDIUM | Subtle correctness, missing test, footgun | 4 |
| LOW | Style, minor doc, defensive nit | 6 |

---

## MEDIUM findings

### F1 — Defensive `(LOOKUP|SYNTHESIS, LEAN_WRITE) → Haiku` entries are a silent-failure footgun

**Severity:** MEDIUM
**File:** `server/orchestrator/model_selector.py:137-145`,
`tests/test_model_selector.py:231-238`

**What:** The selection table contains entries
`(LOOKUP, LEAN_WRITE) → Haiku` and `(SYNTHESIS, LEAN_WRITE) → Haiku`.
The implementer's own comment on line 233 of the test admits these are
defensive-only: *"LOOKUP doesn't produce Lean — its LEAN_WRITE turn
(if it ever happens, defensive-only) gets Haiku."* The implementation
summary is even more candid (`implementation-summary.md:44`):
*"shouldn't ever produce a `LEAN_WRITE` turn in practice... This is
defensive completeness rather than a real use case."*

**Why:** This is a textbook silent-failure pattern. The "totality
invariant" is correctly enforced at import time, but it's enforced by
filling nonsense cells with a plausible-looking value rather than by
rejecting the cells outright. A real-world scenario:

1. A future contributor wires up the orchestrator and writes a bug
   that dispatches a `LOOKUP`-classified query down the
   Autoformalizer's `LEAN_WRITE` code path (perhaps a bad conditional).
2. `select_model(RouteTag.LOOKUP, TurnType.LEAN_WRITE)` returns
   `"claude-haiku-4-5"` — no exception, no log, no telemetry.
3. The orchestrator generates Haiku-quality "Lean" output for a
   query that wasn't even an autoformalization request. The Lean
   kernel rejects garbage, the user sees a confusing error, and
   the misroute survives because nothing fired.

The brief's intent ("Sonnet ONLY for the Autoformalizer role's
Lean-syntax write step") is actively contradicted by these cells:
LEAN_WRITE for non-Autoformalizer roles is now silently accepted as a
legal combination.

**Fix:** Mark these cells as forbidden (sentinel value) and have
`select_model` raise `ValueError` for them. Concretely:

```python
_FORBIDDEN = object()  # sentinel

_SELECTION_TABLE = MappingProxyType({
    (RouteTag.LOOKUP, TurnType.LEAN_WRITE): _FORBIDDEN,
    (RouteTag.SYNTHESIS, TurnType.LEAN_WRITE): _FORBIDDEN,
    # ...
})

def select_model(route_tag, turn_type):
    result = _SELECTION_TABLE[(route_tag, turn_type)]
    if result is _FORBIDDEN:
        raise ValueError(
            f"({route_tag!r}, {turn_type!r}) is not a legal "
            f"combination — only Autoformalization/Verification "
            f"produce LEAN_WRITE turns."
        )
    return result
```

Add a test that asserts both forbidden cells raise `ValueError`. The
existing totality invariant still holds (every key is present).

---

### F2 — Forbidden-string test is asymmetric: Opus is banned outside `model_selector.py`, Haiku/Sonnet are not

**Severity:** MEDIUM
**File:** `tests/test_model_selector.py:111-131`

**What:** `TestForbiddenStrings::test_no_claude_opus_in_server_python_files`
walks `server/**/*.py` and asserts `"claude-opus"` is absent. Good.
But the brief promises a stronger invariant
(milestone brief, lines about deliverables): *"This function is the
single source of truth for model selection — no model ID strings appear
elsewhere in the orchestrator."* That property is **not tested**.

**Why:** A future contributor writing
```python
response = client.messages.create(model="claude-sonnet-4-6", ...)
```
in any orchestrator file would slip through CI. The entire point of
`select_model` as the SSoT is that grepping `claude-` should return
exactly one file's worth of hits (`model_selector.py`). Without a
test, this property will rot the moment someone writes a quick test
fixture or a "temporary" hardcoded call.

The implementation summary explicitly highlights this risk
(`implementation-summary.md:33`): *"`select_model` is the SINGLE
SOURCE OF TRUTH for model selection in the orchestrator; no model ID
strings appear elsewhere in `server/`"* — but the test surface
doesn't enforce it.

**Fix:** Add a `test_no_haiku_or_sonnet_outside_model_selector` test
that walks `server/**/*.py`, allows `claude-haiku-4-5` and
`claude-sonnet-4-6` ONLY in `server/orchestrator/model_selector.py`,
and rejects them everywhere else. The test should be parametrized
over both model strings so error messages are self-locating.

---

### F3 — `_SELECTION_TABLE` cell changes silently invalidate cached prompt prefixes; no version-bump discipline documented

**Severity:** MEDIUM
**File:** `docs/model-policy.md` (entire),
`server/orchestrator/model_selector.py:122-156`

**What:** Per `.claude/notes/07-multi-agent-caching.md:21-30`,
Anthropic's prompt cache is keyed on **model ID + prefix bytes**.
Changing any cell of `_SELECTION_TABLE` (e.g. promoting
`(LOOKUP, RETRIEVAL)` from Haiku to Sonnet for a quality experiment)
flips the model ID, which invalidates every cached prefix for that
`(RouteTag, TurnType)` pair across all 4 agents. The change can land
in a routine PR without anyone realizing the cache-warming
infrastructure now needs to re-warm from cold.

The doc has no section on "what changes here trigger a cache
invalidation" or "what the version-bump discipline is when this table
is touched." The closest acknowledgment is the mention that v2 will
revisit Opus — but a v1 cell flip (Haiku → Sonnet for, say, the
Verification draft turn) doesn't even need a v2 bump under the
current doc.

**Why:** The orchestrator-rules doc (`docs/orchestrator-rules.md`,
which I assume covers the BP1 byte-identity discipline from E08_S04)
is presumably strict about prefix bytes. Model ID is part of those
bytes. A v1 cell flip is functionally equivalent to a BP1 violation
but is invisible from the prompts.py / tools.py side.

**Fix:** Add a section to `docs/model-policy.md` titled
"Cache-invalidation discipline" (or fold into "Selection table") that
states:

1. Any change to `_SELECTION_TABLE` cells invalidates the prompt
   cache for that `(RouteTag, TurnType)` pair.
2. PRs that touch `_SELECTION_TABLE` MUST be flagged in the PR
   description with `cache-invalidation: true` (and a CI grep can
   enforce this).
3. Major-version cell flips require a CHANGELOG entry under
   `docs/model-policy.md` itself, with the date and rationale.

Optionally add a `_POLICY_VERSION = "1.0"` constant at the top of
`model_selector.py` whose value is asserted by a test, and require it
to bump on any cell change.

---

### F4 — Module is dead code; no integration test wires `select_model` into a real Anthropic call

**Severity:** MEDIUM
**File:** `server/orchestrator/model_selector.py` (entire),
`server/orchestrator/__init__.py`

**What:** I grepped for callers of `select_model` and `MODEL_HAIKU_4_5`
across `server/` — zero hits outside the module itself and the test
file. The orchestrator's `__init__.py` says (verbatim): *"The
orchestrator wiring itself ... lands in E08_S05+. The utilities here
are pure functions that the orchestrator imports."* The implementation
summary repeats: orchestrator dispatch loop is future work.

The brief, however, says (deliverables section): *"The orchestrator
selects the model via `server/orchestrator/model_selector.py::select_model(route_tag, turn_type) -> str`, which maps `(RouteTag, TurnType)` pairs to model IDs."* This implies a working orchestrator that actually calls `select_model`.

**Why:** Two related problems:

1. As shipped, the entire policy is unenforced. Nothing in the runtime
   path actually consumes `select_model`. Until E08_S06+ wires the
   dispatch loop, the policy is documentation, not code.
2. The next milestone implementer will write the dispatch loop with
   no integration test that asserts `select_model` is the only
   place model IDs come from. The risk in F2 multiplies.

This is borderline between MEDIUM and "expected per tier sequencing."
I rate MEDIUM because the brief's wording is misleading: an
acceptance-critic reading "the orchestrator selects the model via..."
would expect a runtime path. There isn't one.

**Fix:** Either (a) add an "integration" test stub that imports
the future orchestrator entry point and verifies it would call
`select_model` (impossible until the orchestrator lands — punt to
E08_S06), or (b) add a one-line note in
`server/orchestrator/model_selector.py`'s module docstring that says
*"As of E08_S05 this module is not yet called by any orchestrator
code. The dispatch loop in E08_S06+ will be the first consumer; an
integration test landing with that milestone must assert this is
the only model-ID source."* Option (b) costs 3 lines and prevents
the next implementer from being surprised.

---

## LOW findings

### F5 — `select_model` does not validate argument types; passing arbitrary objects falls through to dict lookup

**Severity:** LOW
**File:** `server/orchestrator/model_selector.py:164-199`

**What:** `select_model(None, None)` raises `ValueError` (good — via
the `KeyError` rewrap), but `select_model(123, 456)` also does. There's
no `isinstance` check that asserts the inputs are `RouteTag` and
`TurnType` enum members. This means a contributor passing a random
string or int gets the same error as someone passing a typo'd enum
attribute.

**Why:** Type-narrowing in error messages is a quality-of-life issue,
not a correctness one. The current `ValueError` message includes the
`!r` form of the bad input, which is enough to debug. Mypy would catch
the mistake at static-analysis time. LOW.

**Fix:** Optional. Add at the top of `select_model`:
```python
if not isinstance(route_tag, RouteTag):
    raise TypeError(f"route_tag must be a RouteTag, got {type(route_tag).__name__}")
if not isinstance(turn_type, TurnType):
    raise TypeError(f"turn_type must be a TurnType, got {type(turn_type).__name__}")
```
Or rely on mypy + don't fix.

---

### F6 — `test_select_model_unknown_pair_raises_value_error` relies on StrEnum equality semantics; brittle to a future enum-class change

**Severity:** LOW
**File:** `tests/test_model_selector.py:207-215`

**What:** The test passes `"LOOKUP_TYPO"` (a string) where a `RouteTag`
is expected. This works only because `RouteTag` is a `StrEnum` AND the
string `"LOOKUP_TYPO"` doesn't equal any RouteTag value. If a future
refactor changes `RouteTag` from `StrEnum` to `Enum`, the dict lookup
behavior changes (a string would never collide with a non-string enum
key) and the test still passes — but for the wrong reason.

**Why:** Test fragility, not a runtime bug. If the StrEnum invariant
changes, the entire `_SELECTION_TABLE` becomes unindexable by string
anyway, so the broader test suite would fail loudly. LOW.

**Fix:** Use a sentinel object that's not even a candidate for the
dict:
```python
class _NotARouteTag: pass
with pytest.raises(ValueError, match="No model selected"):
    select_model(_NotARouteTag(), TurnType.RETRIEVAL)
```

---

### F7 — `docs/model-policy.md` cites Haiku 2048-token cache caveat as load-bearing without verification

**Severity:** LOW
**File:** `docs/model-policy.md:182-192`

**What:** The doc reproduces the
`.claude/notes/07-multi-agent-caching.md:24` caveat: *"Min cacheable
prefix: ~1024 tokens for Sonnet/Opus, ~2048 for Haiku. (Verify.)"* and
warns operators to "verify the 2048 figure against current Anthropic
docs." The source note explicitly tags it `(Verify.)`.

**Why:** Honest of the implementer to flag the unverified claim. But
this is a doc that says *"Claude Haiku 4.5 is the default for
retrieval turns (cost-justified)"* and then admits the cost-comparison
is based on an unverified cache threshold. If 2048 is wrong (say
Anthropic changed it to 1024 across all models), the cost analysis
shifts. LOW because the implementer correctly hedged.

**Fix:** Verify the 2048 figure against current Anthropic public docs
(or replace with a citation to a specific docs URL with retrieval
date) before this doc gets cited as authoritative anywhere.

---

### F8 — Token-budget table arithmetic is plausibly correct but not shown

**Severity:** LOW
**File:** `docs/model-policy.md:170-176`

**What:** The doc gives `~$0.054` for Lookup-only and `~$0.075` for
Autoformalization. Sketch from the prompt:
4 agents × 3 turns × (2K input × $1/MTok + 0.5K output × $5/MTok)
= 4 × 3 × ($0.002 + $0.0025) = $0.054. Checks out.

The Autoformalization figure: 11 Haiku turns at $0.0045 each = $0.0495,
plus 1 Sonnet turn (3K input × $3 + 1K output × $15 = $0.009 + $0.015 =
$0.024) = $0.0735 ≈ $0.075. Checks out.

**Why:** The math is right, but the doc doesn't show it. A reader
auditing the cost model has to derive both lines. LOW.

**Fix:** Add a footnote or a "Worked example" subsection showing the
arithmetic for one row, so future contributors updating the table
(e.g. when Anthropic changes pricing) know which numbers to flex.

---

### F9 — `_SELECTION_TABLE` not in `__all__` (correct) but the underscore convention is the only signal

**Severity:** LOW
**File:** `server/orchestrator/model_selector.py:242-247`

**What:** `__all__` exports `MODEL_HAIKU_4_5`, `MODEL_SONNET_4_6`,
`TurnType`, `select_model`. `_SELECTION_TABLE` is correctly omitted.
But Python's `from server.orchestrator.model_selector import *` still
respects `__all__`, while explicit imports
(`from ... import _SELECTION_TABLE`) bypass it. The test file's
`TestSelectionTableTotality::test_select_model_unknown_pair_raises_value_error`
is intentionally a black-box test (uses `select_model`, not the table
directly). Good. The other tests don't import `_SELECTION_TABLE`.
Clean.

**Why:** Documenting that I checked — no fix needed.

**Fix:** None.

---

### F10 — `model_selector.py` import pulls in YAML loader via `server.router`

**Severity:** LOW
**File:** `server/orchestrator/model_selector.py:57`

**What:** `from server.router import RouteTag` triggers `server.router`
import, which loads `router_patterns.yaml` at module-import time
(per `server/router.py:75`). My `python -X importtime` measurement:
`server.orchestrator.model_selector` total import 18 ms, of which 17
ms is `server.router` (loading PyYAML + parsing the patterns file).

**Why:** Not slow enough to matter for normal use. But it does mean
that any test file importing `model_selector` pays for YAML parsing
even if it never uses the router. The `model_selector` module
doesn't need any router behavior; it only needs the `RouteTag` enum.

**Fix:** Optional — extract `RouteTag` into a `server/route_tag.py`
shim that doesn't load the YAML. Probably not worth the churn unless
test-suite startup time becomes an issue. LOW.

---

## What was done well

- **Single source of truth, properly enforced.** The `_SELECTION_TABLE`
  is wrapped in `MappingProxyType` (verified mutation raises
  `TypeError`); model ID constants are bare string literals with no
  interpolation; no env reads, no datetime injection. Cache
  byte-stability is sound.
- **Closed-at-N invariant uses `if … raise RuntimeError`** rather than
  `assert`, mirroring the F4 fix discipline from E08_S02. Survives
  `python -O`. There's even a regression test (`TestClosedAtNInvariantSurvivesDashO`)
  that spawns `python -O` to confirm it.
- **Whitelist-only model-ID check at import** (lines 231-239): a
  future typo introducing `"claude-haiku-4-7"` (a model that doesn't
  exist) would fail import. Defense in depth above and beyond the
  closed-at-N totality check.
- **Forbidden-string test correctly skips `__pycache__`** and walks
  every `.py` file under `server/`. The test's failure message is
  self-locating (path + line number + line content).
- **Test file documents its AC coverage in a header comment** with a
  table mapping ACs to test classes. Easier to audit than burying the
  mapping in implementation notes.
- **Implementation summary candidly flags risks**: the implementer
  explicitly acknowledges that `(LOOKUP|SYNTHESIS, LEAN_WRITE)` is
  defensive-only and not a real use case (line 44). Honest, even if
  the mitigation is wrong (see F1).
- **Verifier-pass-removal rationale is well-argued** in
  `docs/model-policy.md:73-129`. The "circular validation" framing is
  precise and the Lean-kernel-as-correct-critic argument is anchored
  to `.claude/notes/01-mission-and-context.md`. The doc doesn't
  pretend the absence of an LLM verifier is a free win — it explicitly
  notes that non-Autoformalization queries get NO formal verification
  and the user must read the cited chunks.
- **No model ID strings hardcoded outside `model_selector.py`** as of
  this commit (verified by grep). The Opus ban is the only one
  enforced by test (see F2), but the project as a whole is currently
  in compliance.
- **Tier sequencing clean**: imports `RouteTag` from E08_S01 (landed),
  cross-references `ROLE_PREFIXES` from E08_S02 (landed), no reverse
  coupling. The `Verification` route prefix in `prompts.py` is
  preserved for BP1 byte-identity (correctly noted in the doc).
- **No-fork policy honored**: zero matches for `arxiv-mcp` or
  `model-router` in `server/` or `docs/`. The implementation is
  greenfield.

---

## Recommended rectification order

1. **F1** (footgun: `(LOOKUP|SYNTHESIS, LEAN_WRITE)` silent-Haiku) —
   blocks any safe wire-up in E08_S06. Add the `_FORBIDDEN` sentinel
   and a `ValueError`-raising path for the two nonsense cells. Update
   the totality invariant comment to distinguish "covered" from
   "legal."
2. **F2** (asymmetric forbidden-string test: only Opus is banned
   outside the module) — add the symmetric Haiku/Sonnet test before
   the next milestone wires `select_model` into a real call site,
   otherwise the SSoT property will rot on first integration.
3. **F4** (dead code disclaimer) — 3-line docstring update; cheap.
4. **F3** (cache-invalidation discipline doc) — add a section to
   `docs/model-policy.md` and optionally a `_POLICY_VERSION` constant.
5. **F5–F10** — LOW-priority polish; defer if time-bound. F7 (verify
   the 2048 figure) is worth doing whenever someone has 5 minutes
   with the Anthropic docs open.

---

## Rectification status

(empty — to be filled by the rectifier)
