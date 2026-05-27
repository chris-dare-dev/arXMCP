# Research Synthesis — textbook-ingest-m1

**Orchestrator-merged.** Single-mode dispatch (1× Sonnet); the brief at
[research-brief-1.md](research-brief-1.md) is the primary input. This
synthesis records the orchestrator's design decisions where the brief
gave options.

---

## Scope (verbatim from roadmap)

Extend `ingest/identifiers.py::is_valid_paper_id` to accept the
`textbook:<slug>:<sha>` shape alongside the existing arXiv shapes.
Both inputs round-trip via `paper_id_from_chunk_id`. ≥5 Threat-1
regression tests against slash/colon/null-byte/whitespace/`\Z`-bypass
injection. NO chunks-schema or LanceDB-writer changes (m2's job).

**Acceptance criteria** (from the roadmap, verbatim):

1. Given a valid `textbook:<slug>:<sha>` chunk-id, When
   `is_valid_paper_id` is called, Then it returns True and
   `paper_id_from_chunk_id` returns `textbook:<slug>`.
2. Given an injection-shaped input from the 5+ Threat-1 fixtures,
   When the regex matches, Then it does NOT match (negative).
3. Given an existing arXiv chunk-id, When `is_valid_paper_id` is
   called, Then behavior is byte-identical to today (snapshot test).
4. `ruff check .` clean and `make test` green; 2129+ tests passing on
   macOS / Linux.
5. No changes to chunks schema or LanceDB writer in this milestone.

---

## Load-bearing constraints (from the brief)

### Existing three-copy byte-equality lock

`tests/test_identifiers.py:23-32` enforces:

```python
assert _PAPER_ID_RE.pattern == PAPER_ID_RE.pattern              # chunker
assert VAL_RE.pattern == PAPER_ID_RE.pattern                    # eval-fixture
```

Three independent copies of `_PAPER_ID_RE` exist at:

- `ingest/identifiers.py::_PAPER_ID_FULL_PATTERN` (canonical, the
  single-source-of-truth)
- `ingest/chunker.py:106-110::_PAPER_ID_RE` (chunker)
- `tools/validate_eval_fixtures.py:106-110::_PAPER_ID_RE` (validator)

**Any change to the canonical must be propagated atomically.**

### Pre-existing landmine: `CHUNK_ID_RE` uses `$`, not `\Z`

```python
CHUNK_ID_RE = re.compile(rf"^{CHUNK_ID_PATTERN}$")  # ← bug class F3 left this one
```

The F3 closure on `proof-verify-handler-wiring-m1` fixed
`_PAPER_ID_FULL_PATTERN` but missed `CHUNK_ID_RE`. So today,
`is_valid_chunk_id("arxiv:2401.00001:abcdef0123456789\n")` returns
True. **m1 fixes this in the same touch** — same bug class, ≤ 1 LOC,
identical regression test pattern.

### Threat 1 statement (`08-security-observability-ops.md`)

> "Tool arguments come from LLM output. An LLM that has been
> prompt-injected by something it read in an arXiv abstract could
> pass `paper_id='../../../etc/passwd'`. **Mitigation:** strict regex
> on every arxiv ID input."

m1 widens the regex acceptance — adding a new prefix without
adding strict regression coverage is exactly the failure mode this
mitigation is designed to catch.

### Notebook-slug regex (already path-hardened)

`tools/_notebook_common.py:36`:

```python
SLUG_RE: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9-]{2,30}$")
```

Description: "Lowercase ASCII + digits + hyphens, 3-31 chars, must
start with a letter. Rejects `..`, slashes, shell metacharacters,
uppercase, leading hyphen."

This is the inner pattern we reuse for `<slug>` in textbook paper_ids.

---

## Orchestrator design decisions

### D1 — Single composed regex, three alternatives

Per the brief recommendation #3: extend `_PAPER_ID_FULL_PATTERN` with a
third alternative for `textbook:<slug>`. Same form for `PAPER_ID_PATTERN`
(the no-anchor inner version). No new public symbol.

```python
_PAPER_ID_FULL_PATTERN = (
    r"^\d{4}\.\d{4,5}(v\d+)?\Z"
    r"|"
    r"^[a-z][a-z\-]*/\d{7}(v\d+)?\Z"
    r"|"
    r"^textbook:[a-z][a-z0-9-]{2,30}\Z"
)

PAPER_ID_PATTERN = (
    r"\d{4}\.\d{4,5}(v\d+)?"
    r"|[a-z][a-z\-]*/\d{7}(v\d+)?"
    r"|textbook:[a-z][a-z0-9-]{2,30}"
)
```

**`<slug>` inner:** `[a-z][a-z0-9-]{2,30}` — reuses `SLUG_RE` exactly.
**`<sha>` length:** 16 hex chars (matches arXiv chunk sha).

### D2 — `CHUNK_ID_PATTERN` restructured so `group(1)` = full paper_id

Today: `rf"arxiv:({PAPER_ID_PATTERN}):[0-9a-f]{{16}}"` — `group(1)`
captures only the inner. For textbook chunk-ids, we want
`paper_id_from_chunk_id` to return `"textbook:<slug>"` (the prefix is
part of the paper_id, because the prefix IS the `source_kind`
discriminator).

New shape:

```python
CHUNK_ID_PATTERN = (
    r"(arxiv:(?:\d{4}\.\d{4,5}(?:v\d+)?|[a-z][a-z\-]*/\d{7}(?:v\d+)?)"
    r"|textbook:[a-z][a-z0-9-]{2,30})"
    r":[0-9a-f]{16}"
)
CHUNK_ID_RE = re.compile(rf"^{CHUNK_ID_PATTERN}\Z")  # \Z not $
```

`group(1)` now captures the full `<prefix>:<inner>` for both shapes.
Inner subgroups become non-capturing `(?:…)` so `group(1)` stays
unambiguous.

### D3 — Three-copy synchronization: update all three copies

Researcher's recommendation #7, Option A. The byte-equality lock test
requires `chunker._PAPER_ID_RE.pattern == PAPER_ID_RE.pattern`. Since
we're widening the canonical pattern with a third alternative, we must
add the same alternative to `ingest/chunker.py::_PAPER_ID_RE` and
`tools/validate_eval_fixtures.py::_PAPER_ID_RE` — even though neither
will ever encounter a textbook paper_id in m1 (no textbook chunks
exist yet).

Rationale for Option A over Option B (narrow the byte-equality test):
the test contract IS the invariant. Narrowing it would weaken the
single-source-of-truth discipline that F11 (E06_S03) explicitly
established. The widening is forward-compatible and the chunker only
processes inputs that flow through its own pipeline (which has no
textbook source).

### D4 — Fix `CHUNK_ID_RE` end-anchor `$` → `\Z` in the same commit

Same bug class as F3 closure. Inline regression test:
`is_valid_chunk_id("arxiv:2401.00001:abcdef0123456789\n")` must return
False after m1.

### D5 — Acceptance criterion #3 (arXiv byte-stability) is the snapshot test

Existing tests in `tests/test_identifiers.py` exercise arXiv shapes
extensively. Augment with a NEW `test_arxiv_chunk_id_behavior_byte_stable`
that pins the pre/post m1 acceptance/rejection of a representative
arXiv chunk_id sample so the alternation widening doesn't quietly
change arXiv behavior.

---

## Threat-1 regression fixtures (final list)

**Negative** — `is_valid_paper_id` returns False:

| # | Input | Failure mode |
|---|---|---|
| N1 | `textbook:../etc/passwd` | path-traversal via slash + dotdot |
| N2 | `textbook:foo:bar` | extra colon in paper_id form |
| N3 | `textbook:foo\x00bar` | null byte injection |
| N4 | `textbook:foo bar` | whitespace in slug |
| N5 | `textbook:foo\n` | trailing newline (`\Z` bypass — F3 landmine) |
| N6 | `textbook:` | empty slug |
| N7 | `textbook:FOO` | uppercase slug (policy: reject) |
| N8 | `textbook:fo` | slug too short (min 3) |
| N9 | `textbook:` + `a-z * 31` | slug too long (max 31) |
| N10 | `arxiv:textbook:foo` | wrong prefix nesting (chunk-id form via paper_id check) |
| N11 | `textbook:foo:abcdef0123456789` | chunk-id form passed to `is_valid_paper_id` |

**Negative for `is_valid_chunk_id`:**

| # | Input | Failure mode |
|---|---|---|
| C1 | `textbook:foo:abcdef0123456789\n` | trailing newline (`\Z` fix on CHUNK_ID_RE) |
| C2 | `arxiv:2401.00001:abcdef0123456789\n` | EXISTING-ARXIV trailing newline (the F3-class bug we close) |
| C3 | `textbook:../etc/passwd:abcdef0123456789` | path traversal in chunk-id form |
| C4 | `textbook:foo:ABCDEF0123456789` | uppercase hex (policy: reject) |
| C5 | `textbook:foo:abcdef0123456` | sha too short (15 hex chars) |

**Positive** — must return True:

- `is_valid_paper_id("textbook:foo-bar")` (3-char slug minimum)
- `is_valid_paper_id("textbook:shimura-varieties")` (real notebook slug)
- `is_valid_chunk_id("textbook:shimura-varieties:abcdef0123456789")`
- `paper_id_from_chunk_id("textbook:shimura-varieties:abcdef0123456789")` → `"textbook:shimura-varieties"`
- ALL existing arXiv positive tests continue to pass (byte-stability AC).

Total negative: 16. Total positive: 4 + all existing arXiv tests pass.
Brief required ≥5; we ship 16 negative + 4 new positive + the existing
arXiv tests as the snapshot.

---

## Files touched in m1

1. `ingest/identifiers.py` — extend `_PAPER_ID_FULL_PATTERN`,
   `PAPER_ID_PATTERN`, `CHUNK_ID_PATTERN`, `CHUNK_ID_RE`.
   Doc-comment delta documenting the textbook addition and the
   `$ → \Z` fix.
2. `ingest/chunker.py:106-110` — update `_PAPER_ID_RE` to match.
3. `tools/validate_eval_fixtures.py:106-110` — update `_PAPER_ID_RE`
   to match.
4. `tests/test_identifiers.py` — new test class
   `TestTextbookIdentifiers` with 16 negative + 4 positive + the F3
   regression for `CHUNK_ID_RE`.

**No** changes to: chunks schema, LanceDB writer, server handlers,
MCP tool definitions, BP1 prompt prefix.

---

## Failure modes (from brief, prioritized)

| # | Trigger | Symptom | Mitigation |
|---|---|---|---|
| 1 | Three-copy sync breaks | `test_chunker_pattern_equals_canonical` fails | Update all three atomically in m1's single commit |
| 2 | `paper_id_from_chunk_id` returns wrong group | Round-trip test fails | D2 restructure with non-capturing inner subgroups |
| 3 | `server/graph_queries.py` empty result on textbook chunk-id | Silent empty — not a v1 test failure | Known gap; document in implementation-summary |
| 4 | `CHUNK_ID_RE` `\Z` fix forgotten | Trailing newline passes | D4 + C1/C2 regression tests |
| 5 | Alternation order shadowing | `hep-th/9876543` returns False | Add textbook alternative LAST in alternation; rely on existing arXiv tests |
| 6 | `ruff` lint failure on multi-line regex string | CI fail | Use parenthesized concatenation; run `ruff check .` before commit |

---

## Open questions

**None.** All design decisions resolved above.

---

## External writes the implementation will require

**None.** This milestone is purely local — no `git push`, no PR, no
issue, no infra mutation, no external API call. Commit + state-finalize
only.

---

## Orchestrator synthesis note

Single-mode dispatch. No peer disagreement to resolve. Three orchestrator
decisions beyond what the brief said:

1. **D2 (CHUNK_ID_PATTERN restructure)** — chose the "full-prefix capture
   group" form over the "OR'd full-pattern" form, with explicit
   non-capturing inner groups. Cleaner downstream semantics for
   `paper_id_from_chunk_id`.
2. **D3 (three-copy sync — Option A)** — chose to update all three
   copies rather than narrow the byte-equality test. Preserves the F11
   single-source-of-truth invariant.
3. **D4 (CHUNK_ID_RE `\Z` fix)** — folded into m1. Same bug class as
   F3; ≤ 1 LOC; declining to fix it would mean revisiting the same
   landmine in m2.

Brief verdict: ship as drawn with the three decisions above.
