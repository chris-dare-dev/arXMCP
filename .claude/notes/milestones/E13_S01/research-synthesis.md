# E13_S01 — Research synthesis (orchestrator-merged)

**Sources:** [research-brief-1.md](research-brief-1.md) (in-codebase,
241 LOC) + [research-brief-2.md](research-brief-2.md) (MCP spec +
SDK behavior, 320 LOC). The two researchers converged on every
load-bearing finding; the synthesis is the orchestrator's
opinionated merge of both.

---

## 1. Headline findings

1. **Brief's 7-tool list is wrong.** It names `paper_diff` and
   `dependency_graph` which **do not exist** in our v1 surface
   and silently omits `get_definitions` and `find_lemma_by_name`.
   The authoritative list is `server/tools.py::ALL_TOOLS`:
   `search_papers`, `get_chunk`, `find_equation`,
   `get_definitions`, `find_lemma_by_name`, `get_paper`,
   `cite_neighbors`.
2. **Brief's -32602 AC cannot be met by the mcp Python SDK.**
   Brief 2 §4 reads `mcp/server/lowlevel/server.py:521-532` +
   `mcp/server/fastmcp/tools/base.py:93-117` and confirms: BOTH
   `jsonschema.validate` failures AND Pydantic `ValidationError`
   surface as `CallToolResult(isError=True)`. JSON-RPC -32602 is
   reserved for **unknown-tool** requests. The brief's literal
   AC is not satisfiable without bespoke `McpError` wrapping
   (which would be a bigger surgery than this milestone budgets
   — and the spec leaves the choice ambiguous: "Invalid
   arguments" appears under Protocol Errors AND "Invalid input
   data" appears under `isError:true` Tool Execution Errors).
3. **`E07_S12` is a fictional dependency.** The brief inherits
   it from the E13 epic header; `.claude/roadmap/E07-*.md` only
   reaches `E07_S04`. The audit cannot "verify E07_S12 mandated
   regex at the JSON-Schema level" because that milestone never
   shipped. **The audit must also be an enforcement milestone**
   for the uncovered handlers.
4. **`cite_neighbors` is the coverage gap.** The handler in
   `server/handlers/citations.py` accepts any `chunk_id` and
   echoes it straight into the response envelope without
   validation. Threat-1's `../../etc/passwd` flows through
   unchallenged. The handler is a v1 stub (per CLAUDE.md §7) so
   it doesn't hit the filesystem yet — but `server/graph_queries.py`
   is real and will be wired soon. Fix now.
5. **4 of 7 handlers already validate.** `get_chunk`,
   `get_definitions`, `find_lemma_by_name`, `get_paper` each
   call `is_valid_paper_id` or `is_valid_chunk_id` in-body and
   raise `ValueError` on failure. The audit doc records this as
   pre-existing coverage.
6. **2 of 7 handlers take NO scalar identifier.**
   `search_papers` only accepts `paper_id`-shaped values via the
   `filters` dict (which is `dict[str, Any]` accepted-but-
   ignored). `find_equation` takes `latex_or_mathml` + `k` only,
   no identifier. Both are out of Threat-1 scope at the entry-
   point level. The `search_papers.filters` path is documented
   as a separate known gap (it's wired to nothing today; when
   E07_S04 lands real filter execution, the audit must extend).
7. **Canonical regex lives in `ingest/identifiers.py`.** Both
   the design note and the brief carry a slightly drifted
   old-style pattern (`^[a-z\-]+/\d{7}(v\d+)?$` instead of the
   canonical `^[a-z][a-z\-]*/\d{7}(v\d+)?$` — leading lowercase
   letter required, not bare dash). Use the canonical pattern.
8. **No JSON-Schema migration in this milestone.** Adding
   `Pydantic Field(pattern=PAPER_ID_PATTERN)` to handler
   signatures would re-trigger `EXPECTED_TOOL_SCHEMA_SHA256`
   (CLAUDE.md §9 step 4) and invalidate the BP1 prompt-cache
   for every existing agent prefix. The audit's goal is
   *coverage*, not *layer migration*. Keep in-body validation.
9. **Doc destination per CLAUDE.md §1:** `.claude/docs/security-threat-1-audit.md`.
   `docs/security/` would be a brand-new operator-facing
   subtree with nothing in it; the audit checklist is agent-
   internal.
10. **Tests at `tests/security/`** — new directory; this
    milestone's `test_path_traversal.py` is the first
    occupant.

---

## 2. Decisions

### D1. Real 7-tool surface

Adopt `server/tools.py::ALL_TOOLS` as the source of truth.
Drop `paper_diff` + `dependency_graph` (don't exist).
Add `get_definitions` + `find_lemma_by_name` (already shipped).

### D2. Reframe AC: `isError=True` + handler-not-called

The brief's literal "JSON-RPC -32602 Invalid Params" cannot be
met by the mcp Python SDK today (brief 2 §4 reads the source).
The Threat-1 *security* goal is **"never reaches the handler
body"** — the wire-level error code is presentation, not
security.

Adopted AC (verbatim for the implementation summary):

> Every adversarial input produces `CallToolResult.isError == True`
> with a message identifying the bad identifier, AND the handler
> body never reaches `chunks_table` / `theorem_names_db` / Kùzu /
> the filesystem. The latter is asserted via a spy that
> monkeypatches the handler function and flag-checks for
> invocation.

Migration to bespoke `McpError(ErrorData(code=INVALID_PARAMS))`
is documented in the implementation summary as deferred work for
a future Tier-6+ milestone (out of E13_S01 budget). The brief's
quoted wording (`-32602`) is acknowledged as drift; the audit
doc explains the reframe.

### D3. Plug `cite_neighbors` gap

`server/handlers/citations.py::handle_cite_neighbors` gains a
3-line guard at handler entry:

```python
from ingest.identifiers import is_valid_chunk_id

if not is_valid_chunk_id(chunk_id):
    raise ValueError(
        f"chunk_id does not match the expected format "
        f"arxiv:<paper_id>:<16-hex>; got {chunk_id!r}"
    )
```

Mirrors the existing `get_chunk` pattern verbatim. No new
imports, no schema change, no Pydantic Field modification.

### D4. `search_papers.filters` — documented as known gap

The audit doc lists `search_papers.filters` under "Known gaps"
with the rationale: today the `filters` arg is accepted but
NOT EXECUTED (the v1 handler discards it with a
`filter_warnings` annotation). A `paper_id`-shaped value inside
`filters` never reaches the filesystem. When E07_S04 wires real
filter execution, the matching audit extension MUST land in the
same PR.

No code change in this milestone.

### D5. `find_equation` — out of Threat-1 scope

The handler takes `latex_or_mathml` (a string that goes through
a separate MathML/LaTeX validation path — Threat 3 in note 08)
and `k`. No paper_id, no chunk_id. Audit doc records this
explicitly so a future contributor doesn't add this handler to
the path-traversal test list.

### D6. Canonical regex from `ingest/identifiers.py`

The audit doc + tests reference `ingest/identifiers.py`'s
`_PAPER_ID_FULL_PATTERN` and `CHUNK_ID_RE` as the lock. The
slightly-drifted variants in `.claude/notes/08-security-observability-ops.md`
and the milestone brief are flagged as documented drift; the
note will be updated in a follow-up note-grooming pass (out of
scope here).

### D7. No JSON-Schema Pydantic migration

Adding `Annotated[str, Field(pattern=PAPER_ID_PATTERN)]` to
every handler signature would:

1. Re-publish the `tools/list` JSON-Schema bytes (every
   `paper_id` arg gets `"pattern":"..."` in the rendered schema).
2. Trip `EXPECTED_TOOL_SCHEMA_SHA256` in `tests/test_server_tool_schema.py`,
   requiring a hash re-pin via `pytest --update-tool-schema-hash`.
3. Bump `TOOL_SCHEMA_VERSION` per CLAUDE.md §9 step 4.
4. Invalidate the BP1 prompt-cache for every existing agent
   prefix.

The Threat-1 mitigation is already achievable via in-body
validation. The migration's only marginal benefit is publishing
the regex to clients in the schema — desirable but not
load-bearing for the security goal. Defer.

The audit doc explicitly mentions Pydantic schema migration as
a documented "next step" so future security work can pick it up.

### D8. Doc destination — `.claude/docs/security-threat-1-audit.md`

Per CLAUDE.md §1: `docs/` is operator-facing-only. A threat-
audit per-tool checklist is agent-internal. The file lands
at `.claude/docs/security-threat-1-audit.md` following the
E14_S02 precedent (`.claude/docs/observability-tracing.md`).

### D9. Test surface — `tests/security/test_path_traversal.py`

New directory `tests/security/`. The first test file covers:

**Adversarial inputs (3):**
- `"../../../etc/passwd"` (path-traversal)
- `"; cat /etc/shadow #"` (shell-injection-shaped)
- `"a" * 512` (overlong; ReDoS proxy)

**Tool × identifier matrix:**

| Tool | Identifier arg | Test count |
|---|---|---|
| `get_paper` | `paper_id` | 3 |
| `get_definitions` | `paper_id` | 3 |
| `find_lemma_by_name` | `paper_id` (optional) | 3 |
| `get_chunk` | `chunk_id` | 3 |
| `cite_neighbors` | `chunk_id` | 3 |

Total: **15 test cases** (the brief's "21" assumed
`paper_diff` + `dependency_graph` exist; the real matrix is
15 — researcher 1 confirms).

**Invocation pattern:** call the handler function directly
(`handle_get_paper(paper_id=bad_input)`) and assert the
expected `ValueError` is raised. This is faster than spinning
up FastMCP and proves the in-body validator fires regardless
of upstream SDK behavior. The audit doc separately notes the
SDK behavior (`isError=True` wrap).

A SECOND smoke test (1 case) goes through FastMCP's Tool.run
path to confirm the wire-level behavior is what the audit
doc claims: `CallToolResult.isError = True` + the handler
function was not invoked (via a monkeypatched spy).

### D10. No `max_length` Pydantic caps in this milestone

Brief 2 §6 makes a defensible case for `max_length=30` on
paper_id Fields as belt-and-suspenders against future regex
loosening. The cost is the same byte-stability re-pin as D7.
The regex is anchored and not ReDoS-vulnerable today, so the
marginal security benefit is small.

Defer to a future milestone that ALSO does the JSON-Schema
migration (so the schema-hash re-pin pays off across multiple
goals). Audit doc records the recommendation.

### D11. Audit doc shape

```
# Threat-1 audit — paper_id / chunk_id path-traversal coverage

## Summary table

| Tool | Identifier args | Validation today | Test coverage | Status |
|---|---|---|---|---|
| search_papers | filters (dict) | NONE (filters discarded) | N/A | KNOWN GAP — see §gaps |
| get_chunk | chunk_id | in-body: is_valid_chunk_id | 3 cases | ✅ |
| find_equation | (none) | N/A | N/A | OUT OF SCOPE |
| get_definitions | paper_id | in-body: is_valid_paper_id | 3 cases | ✅ |
| find_lemma_by_name | paper_id (opt) | in-body: is_valid_paper_id | 3 cases | ✅ |
| get_paper | paper_id | in-body: is_valid_paper_id | 3 cases | ✅ |
| cite_neighbors | chunk_id | NEW: is_valid_chunk_id (E13_S01) | 3 cases | ✅ |

## Adversarial inputs tested
- "../../../etc/passwd"
- "; cat /etc/shadow #"
- "a" * 512

## Canonical regex (source of truth)
ingest/identifiers.py::_PAPER_ID_FULL_PATTERN  (verbatim)
ingest/identifiers.py::CHUNK_ID_RE             (verbatim)

## Known gaps
- search_papers.filters — see D4
- Pydantic JSON-Schema migration — deferred (D7)

## Migration plan (deferred)
- Add max_length=30 (paper_id) / 64 (chunk_id) on Fields
- Add pattern=PAPER_ID_PATTERN to handler signatures
- Re-pin EXPECTED_TOOL_SCHEMA_SHA256
- Update BP1 cache discipline in note 07

## Per-handler reference
[7 sub-sections, one per tool, naming the file:line of the
validator call]
```

### D12. CI hook (the AC's "CI runs ... on every PR" claim)

The brief mandates CI on every PR. The project has **no CI
configured today** (CLAUDE.md §4.1: "All work lands on main
directly. No CI / GitHub Actions blocking merges. The local
test suite is the authority — make test must be green before
pushing.").

Resolution: the brief's CI-AC is reframed as a **`make test`
hook** — the new tests run as part of the standard test
suite. The audit doc notes the brief's CI wording is
aspirational against this project's posture.

---

## 3. Forced cross-file changes

| File | Change | Decision |
|---|---|---|
| `server/handlers/citations.py` | NEW: `is_valid_chunk_id` guard at handler entry | D3 |
| `tests/security/__init__.py` (NEW) | empty package marker | D9 |
| `tests/security/test_path_traversal.py` (NEW) | 15 parametrized tests + 1 SDK-smoke | D9, D2 |
| `.claude/docs/security-threat-1-audit.md` (NEW) | per-tool audit table + canonical regex + known gaps + migration plan | D8, D11 |
| `README.md` | add row in operator-runbooks table pointing at `.claude/docs/security-threat-1-audit.md`? **NO** — `.claude/docs/` is agent-internal; not linked from README. Per CLAUDE.md §1. | D8 |

---

## 4. Implementation order

1. `server/handlers/citations.py` — add the `is_valid_chunk_id`
   guard. Smallest change, lowest blast radius.
2. `tests/security/__init__.py` + `tests/security/test_path_traversal.py`.
   Verify the 15 cases pass; the `cite_neighbors` test now
   passes because of step 1.
3. `.claude/docs/security-threat-1-audit.md` — the audit doc.
4. `make test`, `ruff check .`.
5. Implementation summary + feat commit.

---

## 5. Open questions resolved at synthesis time

All open questions from both briefs are resolved by the
decisions above. None require user input.

---

## 6. External writes required

**Zero beyond local commits.** No network calls, no
GitHub-Actions changes, no MCP-spec amendments, no PR
creation. `git push origin main` per user authorization
per-event.

---

## 7. Risk register (carry into Phase 3)

- **Reframed AC (-32602 → `isError=True`).** Adversary may
  flag the AC drift. The rationale is documented in D2 — the
  mcp Python SDK doesn't emit -32602 for tool-arg validation
  today; migrating to that error code is a separate Tier-6+
  milestone. The security GOAL ("never reach handler body") is
  met.
- **`cite_neighbors` gap closure is a real code change.** The
  handler is a v1 stub but the guard lands in production code,
  not in a future-wiring placeholder.
- **`search_papers.filters` still uncovered.** Documented in
  the audit doc as a known gap. Adversary may flag this; the
  defense is: `filters` is `dict[str, Any]` accepted-but-
  ignored today, so no exploitable path exists.
- **No Pydantic JSON-Schema migration.** Adversary may flag
  the absence of schema-published `pattern=` constraints. The
  defense is: in-body validation is the security boundary; the
  schema migration is a documentation/UX enhancement, not a
  security enhancement, and its byte-stability cost is real.
- **Note 08 + brief regex drift.** Documented in the audit
  doc; a future note-grooming pass updates note 08 to match
  `ingest/identifiers.py`.
