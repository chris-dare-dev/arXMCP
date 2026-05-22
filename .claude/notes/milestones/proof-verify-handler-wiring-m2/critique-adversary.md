# Critique — proof-verify-handler-wiring-m2

**Critic:** adversary
**Generated:** 2026-05-21T00:00:00Z
**Commit range:** `a1aa11bb83f4198bff2e17dae60be9c353cc197b..ba574e9447916d290b6f472baeae37de2be1d199`
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- The m2 surgery is small, structurally correct, and the wire-level
  byte-stability claim (sort-keys at serialize time keeps both
  `structuredContent[0].text` and the FastMCP-emitted `structuredContent`
  field byte-stable across miss vs. Tier-1 / Tier-2 hit) holds — verified
  by simulation. No CRITICAL data-loss, security, or spec-compliance
  issues found.
- Findings: 0 CRITICAL, 2 HIGH, 3 MEDIUM, 2 LOW. The two HIGH items are
  both about the test surface (cache-hit paths are not exercised; cached
  payload is mutated rather than re-stamped post-hit), not about
  shippable correctness on the common path.
- Highest-risk file:line: `server/handlers/search.py:518-536` — the miss
  path stores the m2-stamped `filters_applied` IN the cached payload,
  contradicting the helper's own docstring at lines 218-221 ("never
  stored in cached payload"). Today this is benign because the cache key
  pins the filter shape, but the contradiction is a foot-gun the moment
  any future change (e.g. cache-key omitting filters; semantic-equivalent
  cross-filter Tier-2 expansion) breaks the implicit invariant.
- `CHANGES.md:45-47` claims "BP1 prompt-cache breakpoint were re-pinned
  in lockstep" but `tests/test_prompts.py:619-621` was NOT touched; the
  implementation-summary explicitly says BP1 was unchanged. The
  changelog and the impl-summary disagree — either the impl-summary is
  right (and the changelog wording is wrong) or the changelog is right
  (and the implementation forgot to bump). Verified: impl-summary is
  correct, changelog is wrong.
- Two test-name drift items in the impl-summary (claims
  `test_tier1_cache_hit_restamps_filters_applied` and
  `test_unsupported_filter_keys_are_dropped` exist; neither does). The
  former is a substantive gap (cache-hit path uncovered); the latter is
  documentation drift (the test exists under the name
  `test_unsupported_keys_excluded_from_echo`).
- Research synthesis "Disagreement #2" claim that `TOOL_SCHEMA_VERSION`
  flows into the BP1 hash via `_meta` is false **as the BP1 hash is
  pinned today** — `tests/test_prompts.py:464` deliberately serializes
  only `{name, description}` from `ALL_TOOLS`, dropping `_meta`. The
  implementer correctly noted this divergence in the impl-summary;
  flagged as MEDIUM because production-mode prompt-cache discipline
  (what Anthropic actually hashes for `cache_control`) may still see
  `_meta` if the orchestrator passes the full `tools/list` response into
  `tools=[...]`.
- The deferred `degraded` / `degraded_reasons` schema gap (Disagreement
  #3 in synthesis) is real: emitting either field on the miss path
  causes `jsonschema.validate` to fail under the existing
  `additionalProperties: false` top-level. Verified empirically. Not a
  m2 regression — pre-existing — but its persistence after m2 is a
  latent foot-gun the rectifier should be aware of when triaging.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Tier-1 / Tier-2 cache-hit re-stamp path has zero test coverage

- **Severity:** HIGH
- **Source:** adversary
- **File:** `tests/test_search_filter.py:223` (cache mocked to `None`),
  `server/handlers/search.py:387-392` + `:420-432` (re-stamp call sites
  that are unreachable from the existing fixture).
- **What:** The `_inject_filters_applied` helper is wired into ALL THREE
  paths (Tier-1 hit lines 387-396, Tier-2 hit lines 421-436, miss lines
  515-523), but the `fake_resources` fixture at `tests/test_search_filter.py:223`
  monkeypatches `server.handlers.search.get_cache` to return `None`. Every
  new m2 integration test (`TestFiltersAppliedHandlerIntegration`,
  `TestSchemaConformanceForFiltersApplied`) reuses this fixture, so the
  cache-hit re-stamp slots are **never executed in tests**. The
  implementation-summary at `.claude/notes/milestones/proof-verify-handler-wiring-m2/implementation-summary.md:43-47`
  claims a test `TestFiltersAppliedHandlerIntegration::test_tier1_cache_hit_restamps_filters_applied`
  exists; grep confirms no test by that name in the repo.
- **Why it matters:** Two of the three insertion points the helper claims
  to defend (per the helper's own docstring at `server/handlers/search.py:218-221`)
  are untested. A future refactor of `_restamp_degraded`, an accidental
  removal of the post-restamp `_inject_filters_applied` call, or a
  dict-mutation regression on the cache-hit path would slip through `make
  test` undetected. AC #6 in the impl-summary ("All three cache-paths
  (miss, Tier-1 hit, Tier-2 hit) re-stamp the echo") is asserted but
  unverified. The m1 critique explicitly closed F4 (filter-canonicalization)
  by adding cache-stability tests; m2 reverts to the pre-m1 posture
  for the new field.
- **Proposed fix:** Add a `with_cache_resources` fixture (or extend
  `fake_resources` with a `with_cache=True` parameter via
  `pytest.fixture(params=[True, False])`) that wires a real `MultiTierCache`
  pointing at an in-memory Tier-1 mirror. Then add at minimum:
  ```python
  def test_filters_applied_present_on_tier1_cache_hit(self, fake_resources_with_cache):
      # First call: miss + store
      r1 = _run(handle_search_papers(query="x",
          filters={"paper_id": ["2604.26204"]}, k=3))
      # Second call: same args -> Tier-1 hit
      r2 = _run(handle_search_papers(query="x",
          filters={"paper_id": ["2604.26204"]}, k=3))
      assert r1.structuredContent["filters_applied"] == r2.structuredContent["filters_applied"]
      assert r2.structuredContent["filters_applied"] == {"paper_id": ["2604.26204"]}
  ```
  Plus a Tier-2 analogue (different query but same paper_id filter,
  forcing semantic-equivalent dispatch on the embedded path).
- **Regression guard:** The two tests above; both must FAIL if either
  `_inject_filters_applied(structured, canonical_filters)` call on lines
  392 / 432 of `search.py` is removed or replaced with a no-op.

### F2 — Miss path STORES `filters_applied` in cached payload, contradicting its own docstring

- **Severity:** HIGH
- **Source:** adversary
- **File:** `server/handlers/search.py:518-536`
- **What:** The miss path computes
  ```python
  payload = _inject_filters_applied(payload, canonical_filters)  # line 522
  structured = envelope(payload)                                   # line 523
  ...
  await cache.store_search(... payload=structured, ...)            # line 529-536
  ```
  so the value cached under the `(query, filters, k, level)` key
  ALREADY contains `filters_applied` baked in. The docstring on
  `_inject_filters_applied` at `server/handlers/search.py:218-221`
  describes the helper as "Called on all three cache paths ... so cached
  payloads — which do NOT carry caller-specific metadata — get the field
  stamped post-hit, paralleling the `_restamp_degraded` pattern." This
  is false: the cached payload DOES carry the field. The cache-hit re-stamp
  then OVERWRITES the same `filters_applied` value (idempotent because
  cache key pins filter shape).
- **Why it matters:** Today the behavior is correct because the cache
  key includes `canonical_filters`, so the cached `filters_applied`
  always matches the request's filter exactly. But:
  1. The docstring is a load-bearing claim about the architecture; a
     reader following its guidance to e.g. add a new caller-specific
     field will assume the same "never stored" invariant holds and may
     introduce a real bug.
  2. The pattern is structurally inconsistent with `_restamp_degraded`
     (which DOES strip `degraded` from the cached payload before
     re-stamping, at `search.py:567-568`). `_restamp_degraded` was added
     in E14_S05 specifically because the cache key does NOT include
     server-degraded state. The m2 author followed the form
     (post-cache-hit re-stamp call) without following the substance
     (strip-then-re-add).
  3. If any future milestone drops `canonical_filters` from the cache
     key, or adds Tier-2 cross-filter semantic-equivalent expansion (a
     plausible E07-area optimization: same query, different filter set,
     same underlying ANN result), the cached `filters_applied` will
     silently lie about the request's actual scoping.
- **Proposed fix:** Choose ONE of:
  - **Option A (preferred — matches docstring):** Add
    `payload.pop("filters_applied", None)` to `_restamp_degraded` so
    the cached value is stripped on the hit path before
    `_inject_filters_applied` re-adds it. Then move the
    `_inject_filters_applied(payload, canonical_filters)` call on the
    miss path to AFTER `cache.store_search(...)` so it is never stored.
    Resulting code at miss:
    ```python
    structured = envelope(payload)
    if cache is not None:
        await cache.store_search(... payload=structured, ...)
    # Stamp post-cache so caller-specific metadata is never persisted:
    structured = _inject_filters_applied(structured, canonical_filters)
    structured = _cap(structured)
    ```
    Note: this changes the byte-form of the stored payload too — the
    cached payload no longer has `filters_applied`, matching what the
    Tier-1 hit path strips.
  - **Option B (minimal):** Rewrite the helper docstring to acknowledge
    that the miss-path stamping IS persisted to cache, and the hit-path
    stamping is an idempotent re-application gated by the
    filter-cache-key alignment. Add an `assert` (caveat: project bans
    `assert` for invariants — use `if … raise RuntimeError`) on the hit
    paths verifying that any pre-existing cached `filters_applied`
    equals the to-be-stamped value, raising loudly if drift is ever
    observed.
- **Regression guard:** After Option A, a test like:
  ```python
  def test_cached_payload_does_not_contain_filters_applied(self, fake_resources_with_cache):
      _run(handle_search_papers(query="x", filters={"paper_id": ["x"]}, k=3))
      # Reach into Tier-1 mirror; assert filters_applied NOT in stored value
  ```
  Plus the existing `test_filters_applied_present_on_tier1_cache_hit`
  (from F1) which verifies the hit still surfaces the field.

### F3 — CHANGES.md claims BP1 hash was re-pinned; implementation summary says the opposite

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `CHANGES.md:45-47` vs
  `.claude/notes/milestones/proof-verify-handler-wiring-m2/implementation-summary.md:84-88`
- **What:** `CHANGES.md` says
  > "Schema bumped v8→v9; `TOOL_SCHEMA_VERSION` bumped 8→9; the
  > `tools/list` byte-hash and BP1 prompt-cache breakpoint were re-pinned
  > in lockstep."

  The implementation-summary explicitly says
  > "The BP1 hash (`tests/test_prompts.py::EXPECTED_BP1_SHA256`) was
  > **not** re-pinned — it remained stable across the m2 bump because the
  > BP1-cached tool metadata doesn't include the `version` integer from the
  > JSON schema (only the descriptor side carries it via `_meta`, which
  > is already covered by `EXPECTED_TOOL_SCHEMA_SHA256`)."

  Confirmed: `tests/test_prompts.py:619-621` still pins
  `"f77e6f80dbb9dd0a3d200791b7f7ab2f86de52ee7020c5e783fb8497be22bf77"`
  and is not in the diff (`git diff tests/test_prompts.py` shows no
  changes in the m2 commit). The CHANGES.md wording is inaccurate.
- **Why it matters:** CHANGES.md is the public-facing changelog. A
  future reader auditing why the BP1 hash moved (or did not) will be
  misled by the lockstep claim. More importantly, the lockstep wording
  is the SAFE wording — it implies the author thought the hash should
  have moved but verified it did not. If a follow-on milestone bumps
  `TOOL_SCHEMA_VERSION` again and the BP1 hash DOES move (e.g. because
  `_live_tools_payload` is widened to include `_meta` per the synthesis
  D2 claim), the author will need to know which past changelog entries
  were factually accurate.
- **Proposed fix:** Edit `CHANGES.md:45-47` to match reality:
  ```
  Schema bumped v8→v9; `TOOL_SCHEMA_VERSION` bumped 8→9; the
  `tools/list` byte-hash (`EXPECTED_TOOL_SCHEMA_SHA256` +
  `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`) was re-pinned in lockstep.
  The BP1 hash (`EXPECTED_BP1_SHA256` in `tests/test_prompts.py`) was
  NOT re-pinned: the canonical BP1 surface measured by
  `_live_tools_payload` is `{name, description}` per tool only and
  does not include `_meta.tool_schema_version`, so the version bump
  does not drift this hash. See research-synthesis Disagreement #2
  for the audit trail.
  ```
- **Regression guard:** Cosmetic only — no test change. The
  contradiction between docs is the regression.

### F4 — Implementation summary cites a test name that does not exist in the suite

- **Severity:** MEDIUM
- **Source:** adversary
- **File:**
  `.claude/notes/milestones/proof-verify-handler-wiring-m2/implementation-summary.md:43-47`
  cites `TestFiltersAppliedHandlerIntegration::test_tier1_cache_hit_restamps_filters_applied`;
  `implementation-summary.md:34-35` cites
  `TestFiltersAppliedHelper::test_unsupported_filter_keys_are_dropped`.
  Neither exists. The closest actual tests are:
  - `tests/test_search_filter.py:563` ::
    `TestFiltersAppliedHelper::test_unsupported_keys_excluded_from_echo`
  - No Tier-1 / Tier-2 hit test exists (see F1).
- **What:** The impl-summary is the artifact Phase-4 rectification reads
  to verify acceptance criteria were met. Citing two non-existent tests
  by name is a false-positive on AC verification. The
  `test_unsupported_filter_keys_are_dropped` mention is documentation
  drift (the test exists under a different name); the
  `test_tier1_cache_hit_restamps_filters_applied` mention is a
  test-surface gap masquerading as coverage (see F1).
- **Why it matters:** Phase-4's verify gate strips findings whose cited
  `file:line` no longer matches; an impl-summary that cites non-existent
  tests undermines the parallel acceptance-verification path. The
  per-milestone state.json + impl-summary are auditable artifacts.
- **Proposed fix:** Edit `implementation-summary.md`:
  - Line 35: rename to `test_unsupported_keys_excluded_from_echo`.
  - Lines 43-47: remove the `test_tier1_cache_hit_restamps_filters_applied`
    citation. Replace with an explicit note that **the cache-hit
    re-stamp path is wired but not yet tested** — and either add the
    coverage per F1 or accept the gap explicitly in the deferral list.
- **Regression guard:** Per F1.

### F5 — `_canonicalize_filters` does not dedupe `paper_id`, but synthesis claims "deduped"

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `server/handlers/search.py:259-260` and
  `.claude/notes/milestones/proof-verify-handler-wiring-m2/research-synthesis.md:11`
  ("echoes the **canonical** form of the honored filter") and
  `implementation-summary.md:23-27` ("same canonical (sorted, deduped)
  shape produced by `_canonicalize_filters`").
- **What:** `_canonicalize_filters` only sorts:
  ```python
  elif isinstance(pid, list):
      out["paper_id"] = sorted(pid)
  ```
  No `list(dict.fromkeys(...))` or `set(...)` dedup. A caller passing
  `filters={"paper_id": ["a","a","b"]}` gets:
  - cache key built from `["a","a","b"]` (sorted: same)
  - `_build_paper_id_predicate` builds
    `paper_id IN ('a','a','b')` (LanceDB tolerates duplicates)
  - `filters_applied` echoes `{"paper_id": ["a","a","b"]}` — duplicates
    preserved
  The schema accepts this (`type: object`, no inner constraint), so no
  validation failure. Two callers passing `["a","a","b"]` vs `["a","b"]`
  get DISTINCT cache keys despite semantic equivalence — a cache-stability
  miss the F4 work in m1 was designed to prevent.
- **Why it matters:**
  1. Synthesis claim is inaccurate — the `filters_applied` echo is NOT
     the deduped canonical form, only the sorted form.
  2. Cache-key collisions between semantically-equivalent dup-vs-no-dup
     inputs reduce cache effectiveness. m1's F4 explicitly closed
     str-vs-list and sort-vs-unsort drift; m2 inherits the dup gap.
  3. Downstream agents using `filters_applied` to verify scoping ("did
     I actually constrain to paper X?") will see noisy output if a
     buggy upstream passes duplicates.
- **Proposed fix:** Either:
  - **Tighten canonicalization (recommended):**
    `server/handlers/search.py:260`: change to
    `out["paper_id"] = sorted(set(pid))` (or
    `sorted(dict.fromkeys(pid))` to preserve type semantics; both work
    for str values). Add a test:
    `test_canonicalize_filters_dedupes_paper_id`.
  - **Fix the docs:** strike "deduped" from the synthesis and impl-summary
    if the dup behavior is intentional. Less preferred — the m1 cache-key
    F4 work points at "deduped" being the right invariant.
- **Regression guard:**
  ```python
  def test_canonicalize_filters_dedupes_paper_id() -> None:
      from server.handlers.search import _canonicalize_filters
      assert _canonicalize_filters({"paper_id": ["a","a","b"]}) == {"paper_id": ["a","b"]}
  ```
  Plus a Tier-1 cache-key collision test asserting `derive_tier1_key(...,
  filters={"paper_id":["a","a","b"]}, ...) == derive_tier1_key(...,
  filters={"paper_id":["a","b"]}, ...)`.

### F6 — Synthesis "Disagreement #2" claim about BP1 hash is wrong; impl-summary correctly notes the divergence but doesn't fully resolve the production-mode risk

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_prompts.py:443-464` (the
  `_live_tools_payload` definition) vs.
  `.claude/notes/milestones/proof-verify-handler-wiring-m2/research-synthesis.md:62-68`
  (claims `TOOL_SCHEMA_VERSION` flows into BP1 via `_meta`).
- **What:** The synthesis stated unambiguously:
  > "BUT `TOOL_SCHEMA_VERSION` is in per-tool `_meta` ⊂ `ALL_TOOLS` ⊂
  > `tools/list` ⊂ BP1. Bumping the schema version 8→9 (required by
  > `TestSchemaVersionPin` for the schema-file `"version": 9`) drifts
  > `EXPECTED_BP1_SHA256`."

  But `tests/test_prompts.py:464` reads:
  ```python
  return [{"name": t.name, "description": t.description} for t in ALL_TOOLS]
  ```
  No `_meta`, no `tool_schema_version`. The BP1 hash measured by the
  test is independent of `TOOL_SCHEMA_VERSION`. Empirically: m2's bump
  to v9 left the BP1 hash unchanged and the test green.

  However: `server/tools.py:736-743` (`register_all`) attaches
  `meta={"tool_schema_version": TOOL_SCHEMA_VERSION}` to every
  FastMCP-registered tool. The PRODUCTION `tools/list` JSON-RPC response
  will include `_meta` for every tool. If the orchestrator (E08 / E14
  path) ever populates its Anthropic Messages API `tools=[...]` kwarg
  by deserializing the live `tools/list` response (rather than
  re-projecting `{name, description}` from `ALL_TOOLS`), the actual
  prompt-cache key Anthropic computes WILL include `_meta`, and
  bumping `TOOL_SCHEMA_VERSION` WILL invalidate the production BP1
  cache across all roles.
- **Why it matters:** The test pin is a regression guard for the
  ORCHESTRATOR'S CHOSEN PROJECTION of `tools/list`. If a future
  orchestrator code path drifts to passing the full `tools/list`
  response, the BP1 test will silently still pass while real production
  cache-hit rates degrade. The m2 implementer was right to NOT re-pin
  BP1 (the test, as written, doesn't see the version), but neither the
  synthesis nor the impl-summary establishes a written contract that
  the orchestrator's `tools=[...]` projection MUST strip `_meta`.
- **Proposed fix:** Either (cheap):
  1. Add a comment in `server/tools.py:736-743` stating the contract:
     "`_meta.tool_schema_version` is informational; the orchestrator
     MUST strip `_meta` before populating Anthropic Messages
     `tools=[...]` to keep BP1 cache-stable across schema version
     bumps. See `tests/test_prompts.py:443` `_live_tools_payload` for
     the canonical projection."
  2. Add a regression test in `tests/test_prompts.py` that verifies
     `register_all` produces `_meta` per tool (proving the
     `_live_tools_payload` projection is a deliberate strip, not a
     accidental omission). This will catch a future change that
     accidentally drops `_meta` from registration OR adds it to
     `_live_tools_payload`.
- **Regression guard:** the projection-contract test in (2).

### F7 — `filters_applied` schema declares `type: "object"` with no inner constraints; future SUPPORTED_FILTER_KEYS additions can quietly drift

- **Severity:** LOW
- **Source:** adversary
- **File:** `server/schemas/search_papers_result.json:26-29`
- **What:** The new schema entry is
  ```json
  "filters_applied": {
    "description": "...",
    "type": "object"
  }
  ```
  No `properties`, no `additionalProperties: false`, no required-keys
  enforcement, no per-value `items` constraint. A future careless
  edit that emits `filters_applied: {"paper_id": "single_string"}`
  (rather than the canonical-list form) would validate against the
  schema, silently breaking the documented `list[str]` contract.
- **Why it matters:** The schema is the load-bearing wire contract.
  The current loose definition makes it easy for an inner-shape drift
  to escape `jsonschema.validate`. Today the helper enforces the
  contract by construction, but the schema is the durable artifact.
- **Proposed fix:** Tighten the schema:
  ```json
  "filters_applied": {
    "description": "...",
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "paper_id": {
        "type": "array",
        "items": {"type": "string"},
        "minItems": 1
      }
    }
  }
  ```
  Note: adding the property requires bumping
  `TOOL_SCHEMA_VERSION` → 10 and re-pinning the tool-schema SHA. If
  that scope expansion is undesired, defer to a follow-up.
- **Regression guard:** A test that asserts
  `filters_applied: {"paper_id": "not-a-list"}` is REJECTED by
  `jsonschema.validate`.

### F8 — Deferred-from-m2 `degraded` / `degraded_reasons` schema gap is real and reachable

- **Severity:** LOW (pre-existing; m2 deferred per Synthesis D3)
- **Source:** adversary
- **File:** `server/schemas/search_papers_result.json:80` (the
  `required` list and top-level `additionalProperties: false`) +
  `server/handlers/search.py:515-517` (degraded emission) +
  `server/handlers/search.py:569-571` (re-stamp emission).
- **What:** Verified empirically: any `search_papers` response that
  triggers the degraded path (e.g. `r.degraded is not None` at line
  377-379, or `embed_fallback_active=True` at line 411) emits
  `degraded` and `degraded_reasons` fields. These are NOT declared in
  the v9 schema (or v8 before it); `additionalProperties: false` at
  the top level causes `jsonschema.validate` to REJECT the payload.
  ```
  Additional properties are not allowed ('degraded', 'degraded_reasons'
  were unexpected)
  ```
  Today this is hidden because no test fixture toggles
  `fake.degraded = SomeReason(...)`, and the only consumer that calls
  `jsonschema.validate` (`tests/test_snippet_contract.py::TestSchemaConformance`
  + the new `TestSchemaConformanceForFiltersApplied`) uses
  non-degraded fixtures.
- **Why it matters:** Synthesis D3 deferred this to a separate chore.
  m2 is consistent with that call. But the gap PERSISTS and the m2
  schema bump was the cheap window to close it. The implementation
  summary at lines 103-108 acknowledges the deferral. Flagging here
  so the next rectifier or the operator triaging an operational
  degraded-mode 500-from-schema-violation knows the connection.
- **Proposed fix:** Out of scope for m2 per synthesis D3. Track as a
  follow-up chore: `chore(server): close pre-existing
  degraded/degraded_reasons schema gap`. Either widen
  `server/schemas/search_papers_result.json` `properties` to include
  both fields, or remove them from the handler and surface degradation
  via a separate `_meta` block.
- **Regression guard:** Once closed, add a test
  `test_degraded_response_validates_against_schema` that constructs a
  payload with `degraded=True, degraded_reasons=["x"]` and asserts
  `jsonschema.validate` passes. m2 should NOT add this — that's the
  scope of the follow-up.

## What was done well

- The synthesis's resolved disagreements (esp. D4 "absent not null")
  were honored to the letter — the helper at
  `server/handlers/search.py:230-231` does conditional-set-if-truthy,
  preserving the no-filter byte shape. Verified by
  `TestFiltersAppliedHandlerIntegration::test_filters_applied_absent_when_no_filter`.
- The helper placement (`_inject_filters_applied` called BEFORE
  `envelope(payload)` on the miss path, line 522-523) is the correct
  call ordering — `_sort_dict` inside `envelope()` will sort
  `filters_applied` into its alphabetical position with the rest of
  the payload keys. Wire-form byte-stability confirmed by simulation.
- Schema metadata bump is complete and internally consistent: `$id`
  v8→v9 at line 3, `version: 9` at line 6, description appended at
  line 5 — three drift points moved together; the `TestSchemaVersionPin`
  test would have caught any of the three being missed.
- The `_unsupported_keys_excluded_from_echo` test
  (`tests/test_search_filter.py:563-573`) is the right regression
  guard for synthesis D1 (SUPPORTED_FILTER_KEYS subset only) — a
  future careless edit that widens the echo to include warned-about
  keys will fail this test.
- The end-to-end `test_filtered_response_validates_against_schema`
  test (line 698) is exactly the kind of contract test the F1 mode
  of the synthesis required ("schema validation failure on filtered
  call"). It loads the live schema from disk, builds a real handler
  response, and runs `jsonschema.validate` — closing the loop the
  m1 critique would have flagged if missing.
- The hash re-pin discipline is correct: schema-version moves with
  the BP1-projected `EXPECTED_TOOL_SCHEMA_SHA256` and the paired
  `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` version-anchor (the F2-style
  guard that refuses to ship a new hash without also bumping the
  version). Both anchors move together at
  `tests/test_server_tool_schema.py:95` and `:109`.
- CHANGES.md correctly groups m1+m2 under one `## Unreleased` entry
  rather than two separate entries — matches the project's epic-grain
  changelog discipline (the file's own preamble at CHANGES.md:7-10).
- The deferred-degraded-schema-gap (synthesis D3) was correctly NOT
  merged into m2 — the impl-summary at lines 103-108 explicitly
  preserves the deferral, matching the synthesis resolution.

## Recommended rectification order

1. **F2** (HIGH) — pick Option A (strip-then-re-add to match docstring +
   `_restamp_degraded` pattern) OR Option B (fix the docstring). Option A
   is the cleaner architectural fix; Option B is the minimal-change fix.
   Either is shippable but choose explicitly. Doing this BEFORE F1
   ensures the test added in F1 covers the correct invariant.
2. **F1** (HIGH) — add Tier-1 and Tier-2 cache-hit tests for the
   `filters_applied` re-stamp. After F2 is resolved, the test asserts
   the post-F2 invariant (either "field stripped from cache and
   re-stamped" per Option A, or "field present in cache and idempotently
   overwritten" per Option B).
3. **F3** (MEDIUM) — one-line CHANGES.md edit to remove the false
   "BP1 ... re-pinned" claim. Trivial; do under same rect commit as F1+F2.
4. **F4** (MEDIUM) — update impl-summary to fix the two test-name drift
   items. Trivial.
5. **F5** (MEDIUM) — add dedup to `_canonicalize_filters` (one-line
   change to `sorted(set(pid))`) plus the dedup regression test. Modest
   surface increase but closes a real cache-key collision class.
6. **F6** (MEDIUM) — add either the comment-as-contract OR the
   `register_all` `_meta` regression test. Cheap; tightens the BP1
   contract.
7. **F7** (LOW) — defer unless touching the schema for F8.
8. **F8** (LOW, pre-existing) — explicitly defer; not m2 scope.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
