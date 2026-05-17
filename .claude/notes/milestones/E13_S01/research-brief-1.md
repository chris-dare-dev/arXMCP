# E13_S01 — Research Brief 1 (In-Codebase Context)

**Scope:** in-codebase reality of the Threat-1 (path-traversal via `paper_id`/`chunk_id`)
audit. The brief as written contains three factual errors against the v1 tool surface
and the FastMCP error-handling contract; this brief is opinionated about which parts of
the brief to keep, drop, or reframe before Phase-2 implementation begins.

---

## 1. The REAL v1 tool surface — brief is wrong on 2 of 7 tools

`server/tools.py::ALL_TOOLS` is the authoritative tuple (`ALL_TOOLS` lines 247-255).
The seven registered tools, in registration order, are:

1. `search_papers`
2. `get_chunk`
3. `find_equation`
4. `get_definitions`
5. `find_lemma_by_name`
6. `get_paper`
7. `cite_neighbors`

The brief's list — `search_papers, get_chunk, get_paper, paper_diff, cite_neighbors,
dependency_graph, find_equation` — is wrong: **`paper_diff` and `dependency_graph`
DO NOT EXIST in the v1 surface**, and the brief silently omits `get_definitions` and
`find_lemma_by_name`. CLAUDE.md §6 lists the seven I enumerated above. Sub-issue closure:
the audit must target the REAL seven, not the brief's seven. Drop `paper_diff` +
`dependency_graph`; add `get_definitions` + `find_lemma_by_name`.

## 2. Per-handler input map — where `paper_id`/`chunk_id` actually enter

I walked every file in `server/handlers/*.py`. Map of inputs:

| Handler | Identifier args | Validation today |
|---|---|---|
| `handle_search_papers` (search.py) | `query`, `level`, `k`, `filters` (paper_id may be inside), `cursor` | **NONE** — `filters` is `dict[str, Any]`; paper_id-shaped values are accepted and silently echoed in `filter_warnings`. No regex check. |
| `handle_get_chunk` (chunk.py) | `chunk_id` | In-body: `if not is_valid_chunk_id(chunk_id): raise ValueError(...)` (line 39-43). |
| `handle_find_equation` (equation.py) | `latex_or_mathml`, `k` | **No paper_id/chunk_id args.** |
| `handle_get_definitions` (definitions.py) | `paper_id`, `term`, `cursor` | In-body: `if not is_valid_paper_id(paper_id): raise ValueError(...)` (line 73-78). |
| `handle_find_lemma_by_name` (lemma.py) | `name`, `paper_id` (optional), `k` | In-body: `if paper_id is not None and not is_valid_paper_id(paper_id): raise ValueError(...)` (line 68-71). |
| `handle_get_paper` (paper.py) | `paper_id`, `version` | In-body: `if not is_valid_paper_id(paper_id): raise ValueError(...)` (line 37-40). |
| `handle_cite_neighbors` (citations.py) | `chunk_id`, `direction`, `depth`, `limit` | **NONE** — stub handler. Echoes `chunk_id` straight into the response envelope (citations.py line 32). |

**Findings:**
- 4 of 7 handlers (`get_chunk`, `get_definitions`, `find_lemma_by_name`, `get_paper`)
  have in-body validators that raise `ValueError`.
- 2 of 7 (`find_equation`, `search_papers`) take no `paper_id`-shaped scalar at all
  (search_papers may take one nested in `filters`, but the brief's three adversarial
  scalars don't go through that path).
- **`cite_neighbors` is the gap.** It accepts a `chunk_id` of any shape and returns
  it untouched. Threat-1's adversarial `../../etc/passwd` flows straight to the
  response. The handler is a v1 stub (per CLAUDE.md §7) so no SQL/path use happens,
  but per CLAUDE.md §6 the matching library `server/graph_queries.py::cite_neighbors`
  IS real and the stub will be wired to the boundary soon. The audit must close this.

## 3. The canonical regex — verbatim

From `ingest/identifiers.py` (the single source of truth — F11 close from E06_S03):

```python
_PAPER_ID_FULL_PATTERN = (
    r"^\d{4}\.\d{4,5}(v\d+)?$"  # new style: 2401.00001 or 2401.00001v3
    r"|"
    r"^[a-z][a-z\-]*/\d{7}(v\d+)?$"  # old style: math.AG/0001234
)

PAPER_ID_PATTERN = (
    r"\d{4}\.\d{4,5}(v\d+)?|[a-z][a-z\-]*/\d{7}(v\d+)?"
)

PAPER_ID_RE = re.compile(_PAPER_ID_FULL_PATTERN)

CHUNK_ID_PATTERN = rf"arxiv:({PAPER_ID_PATTERN}):[0-9a-f]{{16}}"
CHUNK_ID_RE = re.compile(rf"^{CHUNK_ID_PATTERN}$")
```

The brief's quoted old-style pattern `^[a-z\-]+/\d{7}(v\d+)?$` differs from canonical
`^[a-z][a-z\-]*/\d{7}(v\d+)?$` (canonical insists on a leading lowercase letter, not
`[a-z\-]+` which would allow `-/0001234`). Use the canonical pattern — `ingest/identifiers.py`
is the lock.

## 4. Threat 1 verbatim from `.claude/notes/08-security-observability-ops.md`

Lines 9-16:

> ### Threat 1: Path traversal via `paper_id`
>
> Tool arguments come from LLM output. An LLM that has been prompt-injected by
> something it read in an arXiv abstract could pass `paper_id="../../../etc/passwd"`.
>
> **Mitigation:** strict regex on every arxiv ID input:
> `^\d{4}\.\d{4,5}(v\d+)?$` for new-style IDs, `^[a-z\-]+/\d{7}(v\d+)?$` for
> old-style. Reject at the JSON-Schema level so it never reaches handlers.

Note the design note ALSO carries the wrong old-style pattern — both the note and the
brief drift from the canonical `ingest/identifiers.py`. The note explicitly says
"Reject at the JSON-Schema level so it never reaches handlers" — but we do NOT do this
today. We reject in the handler body. The audit should call this out and either
re-affirm the in-body strategy or migrate to schema-level (Pydantic `Field(pattern=...)`).

## 5. The -32602 claim — does NOT match FastMCP today

The brief: "Every case must produce a JSON-RPC -32602 Invalid Params error without
the handler body executing." This is wrong as a literal acceptance criterion.

I read `.venv/lib/python3.12/site-packages/mcp/server/lowlevel/server.py` and
`mcp/server/fastmcp/tools/base.py`. The actual error flow today:

1. **JSON-Schema validation** (`lowlevel/server.py` line 530):
   `jsonschema.validate(instance=arguments, schema=tool.inputSchema)`. On failure,
   `_make_error_result(f"Input validation error: {e.message}")` returns a
   `CallToolResult(isError=True)`. NOT a JSON-RPC -32602.

2. **Pydantic validation in FastMCP** (`fastmcp/utilities/func_metadata.py` line 88):
   `arg_model.model_validate(arguments_pre_parsed)` — Pydantic `ValidationError`
   propagates up to `Tool.run` (`fastmcp/tools/base.py` line 100-117), which catches
   `Exception` and **wraps it in `ToolError(f"Error executing tool {self.name}: {e}")`**.
   Then `lowlevel/server.py` line 583-584's `except Exception` calls
   `_make_error_result(str(e))` — again `isError=True`, not -32602.

3. **In-body handler raises** (our four `ValueError` raises): same path as 2 — wrapped
   in `ToolError`, returned as `CallToolResult(isError=True)`.

**Implication for the audit.** Either:
- (a) Reframe AC: "every case returns `isError=True` with the message containing the
  identifier-format error" — matches today's behavior, easy to test.
- (b) Add an explicit FastMCP middleware/wrapper that converts identifier-format
  failures into JSON-RPC -32602 — bigger surgery, requires raising the appropriate
  `McpError(ErrorData(code=INVALID_PARAMS, ...))` instead of `ValueError`/`ToolError`.

I recommend (a). The Threat-1 mitigation goal is **"never reaches the handler body"**;
the wire-level error code is presentation, not security. The 21 tests can assert
`isError=True` plus a regex-format error message. Tier-5 budget doesn't pay for (b).

## 6. E07_S12 does not exist — the brief's dependency is fictional

`grep "E07_S" .claude/roadmap/E07-hybrid-retrieval.md` returns only E07_S01–E07_S04.
There is no E07_S12, E07_S13, etc. The brief inherits this from the E13 epic header
which also lists fictional dependencies (E07_S08–S13, E11_S05). The audit cannot
"verify E07_S12 mandated regex at the JSON-Schema level" because that milestone never
shipped. The only regex enforcement today is the in-body `is_valid_*` calls.

This means E13_S01 is *also* a coverage milestone, not just an audit milestone: it
must add the regex enforcement for the 3 uncovered entry points (`cite_neighbors`,
`search_papers` filters path, and the optional argument paths in any handler that
slipped). The brief's framing of "audit-only, no net-new implementation" is wrong.

## 7. Existing security tests + directory shape

- **No `tests/security/` directory exists today.** `find` confirms. We'll create it.
- `tests/test_identifiers.py` already covers `is_valid_paper_id`/`is_valid_chunk_id`
  unit semantics. The new file is end-to-end: it dispatches through `mcp_server.add_tool`
  / `Tool.run` to confirm the validation actually fires at the boundary.
- **Doc placement is a CLAUDE.md §1 issue.** The brief calls for
  `docs/security/threat-1-audit.md`. Per CLAUDE.md §1, `docs/` is
  "ONLY user-facing documentation referenced by the root README.md. Today: just
  `docs/install.md`." A threat-audit per-tool checklist is **agent-internal** and
  should land at `.claude/docs/security-threat-1-audit.md` (or
  `.claude/notes/security/threat-1-audit.md`). Do NOT create `docs/security/`.

## 8. Prior decisions / lessons

- **E06_S05** ("origin validation + security headers + 1MB body cap") closed
  the HTTP-layer threats but did NOT touch identifier validation. F1-F13 from its
  critique were all wire-level (Origin, body cap, headers).
- **E06_S03 critique F3 + F11** are the only prior identifier-validation work:
  F11 collapsed three regex definitions to `ingest/identifiers.py`; F3 added the
  in-body `is_valid_paper_id` calls in the four handlers above. These are the only
  Threat-1 mitigations shipped to date.
- **`cite_neighbors` is a known stub** (CLAUDE.md §7) — the citations.py handler
  is intentionally minimal. The audit should add validation NOW so the future
  E09-wiring doesn't have to remember.
- No recent commit since E06_S03 has touched identifier validation. `git log` shows
  the most recent paper_id-related work was E14_S05 disk-full sentinel — unrelated.

## 9. Test-count target — 21 is wrong for the real surface

The brief: "7 tools × 3 adversarial inputs = 21 test cases."

Real arithmetic:
- 4 tools take `paper_id` directly (`get_paper`, `get_definitions`, `find_lemma_by_name`,
  `find_equation`'s `latex_or_mathml` is not a paper_id — skip).
- Actually 3 take `paper_id`: `get_paper`, `get_definitions`, `find_lemma_by_name`.
- 2 take `chunk_id`: `get_chunk`, `cite_neighbors`.
- 1 (`search_papers`) takes `paper_id` only via nested `filters` dict.
- 1 (`find_equation`) takes NO identifier (skip from Threat-1 entirely).

So the matrix is closer to **(3 paper_id tools + 2 chunk_id tools + 1 filters path) ×
3 adversarial inputs = 18 cases**, plus we should ALSO test `chunk_id` adversarial
inputs use a different regex (`CHUNK_ID_RE`) than `paper_id` — those test cases must
use chunk_id-shaped attack strings (e.g., `arxiv:../../../etc/passwd:aaaaaaaaaaaaaaaa`)
in addition to the bare paper-id-shaped strings. Realistic target: **15-21 tests**,
depending on how `search_papers.filters` is tested. Don't pin "21" as load-bearing.

## 10. Open questions

1. **REAL 7-tool list confirmed?** Yes — `ALL_TOOLS` is the source of truth. Drop
   `paper_diff` and `dependency_graph`; add `get_definitions` and `find_lemma_by_name`.
2. **Where is the regex enforced today?** In-body `raise ValueError` in 4 of 7
   handlers (`get_chunk`, `get_definitions`, `find_lemma_by_name`, `get_paper`). NOT
   at JSON-Schema level. `cite_neighbors`, `find_equation`, `search_papers.filters`
   are uncovered. NO Pydantic `Field(pattern=...)` is used anywhere on identifier args.
3. **What does FastMCP return on Pydantic validation failure?**
   `CallToolResult(isError=True, content=[TextContent(text="Error executing tool ...")])`
   — **NOT** -32602. Same for in-body raises. The brief's -32602 AC needs reframing.
4. **`tests/security/` directory?** Does not exist. Create it. **`docs/security/`?**
   Should NOT exist per CLAUDE.md §1; route to `.claude/docs/security-threat-1-audit.md`.
5. **21-test target — does it cover every entry point?** No — see §9. The real
   matrix is paper_id-shaped attacks on 3 handlers + chunk_id-shaped attacks on 2
   handlers + filters-path on 1 handler. `find_equation` is out of Threat-1 scope.

## 11. External writes required

**Zero.** All work is local: new test file, new doc under `.claude/docs/`, and
identifier-validation patches to `citations.py` (and optionally `search.py` for the
filters path). One commit triple per CLAUDE.md §4.3.

## 12. Opinionated recommendations to the synthesist

1. **Drop -32602 from acceptance criteria.** Replace with: `CallToolResult.isError=True`,
   message contains "does not match" or "id format", and the handler body never reaches
   the LanceDB / Kùzu call (verifiable via a fixture that monkeypatches the resource
   read and asserts it was not called).
2. **Add `is_valid_chunk_id` to `handle_cite_neighbors`.** One-line fix — mirror the
   `get_chunk` pattern. Even though the handler is a stub, future graph wiring will
   pass through this code.
3. **Route the per-tool checklist to `.claude/docs/security-threat-1-audit.md`** — do
   NOT touch the user-facing `docs/` tree (CLAUDE.md §1).
4. **Don't try to migrate to JSON-Schema regex at the Pydantic level in this milestone.**
   `Annotated[str, Field(pattern=PAPER_ID_PATTERN)]` would work but changing handler
   signatures will re-trigger the `EXPECTED_TOOL_SCHEMA_SHA256` byte-stability pin
   (CLAUDE.md §9 step 4). That's a bigger blast radius than this milestone budgets.
   Stay with in-body validation; the audit's goal is *coverage*, not *layer migration*.
5. **Use the canonical `_PAPER_ID_FULL_PATTERN` from `ingest/identifiers.py`** — both
   the design note and the milestone brief carry a slightly drifted old-style regex.
   Quote the canonical one in the audit doc, not the drifted one.

---

**Word count:** ~1490.
