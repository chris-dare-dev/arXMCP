# arXMCP — session handoff

**Snapshot date:** 2026-05-10
**Branch:** `claude/gallant-blackburn-b89422`
**Worktree:** `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422`
**Latest commit:** `144b1cc` — `rect(server): close 4 MEDIUM + 1 LOW from E08_S05 critique`
**Test count:** 1177 passed, 4 skipped, 0 failed (full suite via `pytest`)
**Lint status:** `ruff check .` clean
**Total commits on branch:** 78

---

## 1. What this project is

**arXMCP** is a local-first MCP (Model Context Protocol) server that
exposes a research-mathematics arXiv corpus to multi-agent Claude
pipelines. The constitutional design intent (per
`.claude/notes/01-mission-and-context.md`):

> *"Lean's kernel error message is a better critic than another
> Claude. The valuable LLM roles all live upstream of verification —
> and they all depend on having relevant prior work loaded."*

**System shape (200K-paper target, currently at Tier-2 dev scale):**

- **Ingest** (`ingest/`): arXiv source pull → LaTeXML → chunker
  (theorem-statement + proof split for the 512-token BGE-M3 limit)
  → BGE-M3 embedder → LanceDB writer with MVCC version pinning.
- **Server** (`server/`): FastAPI + FastMCP serving 7 tools over
  Streamable HTTP at `/mcp`. Loopback-only bind (Threat 4 from the
  security note). Per-corpus-version pinning, prompt-cache
  discipline, retrieval caps.
- **Eval** (`tests/eval/`): Curated 20-query nDCG@5 retrieval-quality
  fixture; gates Tier-0→Tier-1→Tier-2 transitions.

**Roadmap structure:** 14 epics (E01–E14) split into ~70 milestones
(`E<NN>_S<MM>`). Each milestone has a brief in
`.claude/roadmap/E<NN>-<slug>.md`. Roadmap index lives at
`.claude/roadmap/README.md`. Progress so far: **E01 done (vertical
slice); E02–E08 NEW**, with all milestones up through **E08_S05
shipped** (last shipped was E08_S05 in this session).

---

## 2. The milestone-pipeline skill

All non-trivial milestone work runs through the **`milestone-pipeline`
slash command** (`.claude/skills/milestone-pipeline/SKILL.md`). The
discipline is non-negotiable; future agents continuing this work MUST
use it. The skill enforces a 4-phase workflow:

| Phase | What | Who | Output |
|---|---|---|---|
| 1 — Research | Read briefs, design notes, code | 2× Sonnet (default), 1× Opus (`--deep`), 1× Sonnet (`--single`) — all `general-purpose` agents in parallel | `research-brief-N.md` + `research-synthesis.md` |
| 2 — Implement | Write code, write docs, run tests | Inline (orchestrator) or 1–2× Sonnet sub-agents | Local commits + `implementation-summary.md` |
| 3 — Critique | Find problems, not virtues | Adversary (always, **Opus**) + infra-safety (conditional) | `critique-merged.md` |
| 4 — Rectify | Fix HIGH+CRITICAL always, MEDIUM if cheap, defer LOW | Main session (NOT a sub-agent) | `rect(<scope>): close ...` commit |

**State machine** lives at `<repo-root>/.claude/notes/milestones/<ID>/state.json`
with strict-forward-only transitions through:
`init → research-running → research-complete → implement-running →
implement-complete → critique-running → critique-complete →
rectify-running → complete`.

**Three load-bearing scripts**:
- `.claude/skills/milestone-pipeline/scripts/init-state.sh <ID>` — idempotent
- `.claude/skills/milestone-pipeline/scripts/checkpoint.py <ID> --get|--set` — state machine validator
- `.claude/skills/milestone-pipeline/scripts/status.sh <ID>` — human-readable dump

**Anti-patterns to avoid** (full table in `SKILL.md`):

| Tempting belief | Reality |
|---|---|
| "Skip Phase 1, the milestone is small." | Phase 1 captures `external_writes_required` — Phase 4 reads it. Skipping = surprise external writes at the end. |
| "Dispatch the second researcher in the next turn." | Sequential dispatch defeats parallelism. Both researchers MUST launch in one assistant turn. |
| "The implementer can also write the critique." | Self-critique misses ~70% of real findings. Critics MUST be fresh sub-agents. |
| "≥40% of CRITICAL findings invalidated is fine." | That's a broken critic prompt. Re-tune the axes. |
| "Bundle the rect commit into the last implementer commit with `--amend`." | Phase 4's commit is a separate, named artifact. |
| "I can push since the user already authorized the milestone." | Authorization is per-event. `git push` is a separate user check. |

---

## 3. Project conventions (load-bearing)

- **Conventional commits**, scope = subsystem: `feat(server)`,
  `feat(ingest)`, `feat(shim)`, `feat(infra)`, `feat(tests)`,
  `feat(skill)`, `rect(<scope>)`, `chore(<scope>)`, `docs(<scope>)`.
- **GPG signing is enabled** (`commit.gpgsign=true`). NEVER use
  `--no-gpg-sign`.
- **Co-author trailer is mandatory** on every commit:
  `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`
- **Pre-commit hooks honored**. NEVER `--no-verify`. If a hook
  fails, fix the underlying issue and create a NEW commit (not
  `--amend`).
- **No `git push` without explicit user authorization** — the
  branch lives only in the local worktree.
- **Project check command**: `ruff check . && pytest -q` (no
  Makefile yet; once one lands, prefer `make test`).
- **Design constitution**: `.claude/notes/` (10 numbered files +
  README) is the source of truth for *why*. `.claude/roadmap/` is
  the source of truth for *how*. Cite both by filename in any
  finding/decision that derives from them.
- **HEREDOC for commits to avoid bash-quoting issues** with
  apostrophes etc.:
  ```bash
  git commit -F - <<'COMMIT_EOF'
  Subject line under 50 chars
  ...
  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  COMMIT_EOF
  ```
- **State.json updates are bulk via the `checkpoint.py --set` CLI**
  — strict-forward-only; backward transitions are refused. Set
  `phase` last; it gates the workflow.

---

## 4. Work completed in this session

The session shipped **5 milestones (E08_S02 through E08_S05)**
through the full 4-phase pipeline. E08_S01 had landed in a prior
session; the work picked up from there.

### Cumulative E08 epic status

| Milestone | Effort | Status | Feat commit | Rect commit | Brief crit summary |
|---|---|---|---|---|---|
| **E08_S01** Query router (regex classifier) | M | done before session | `31ba211` | `4ac435d` | 2 HIGH + 6 MEDIUM closed |
| **E08_S02** Role-as-user-turn-prefix + BP1/BP2 | M | done this session | `6504db7` | `559d613` | 2 HIGH + 6 MEDIUM closed |
| **E08_S03** 3-tier MCP-side retrieval cache | L | done this session | `611dece` | `a08a7c0` | **1 CRITICAL** + 5 HIGH + 7 MEDIUM closed |
| **E08_S04** Tool-use ID canonicalization + caps | M | done this session | `12423ad` | `2d0a95e` | 2 HIGH + 5 MEDIUM closed |
| **E08_S05** Model selection policy + verifier-pass removal | S | done this session | `a8ea914` | `144b1cc` | 4 MEDIUM closed |

The E08 epic ("Agent Runtime + Caching") is **complete through S05
of S05** as listed in `.claude/roadmap/E08-agent-runtime.md`. The
roadmap defines exactly five S-stages for E08; **the epic is done**.

### Per-milestone load-bearing artifacts

#### E08_S02 — Role prefixes + BP1/BP2

**Files shipped:**
- `server/prompts.py` — `ROLE_PREFIXES: Mapping[RouteTag, str]`
  wrapped in `MappingProxyType`. Four prefix constants
  (`_LOOKUP_PREFIX`, `_SYNTHESIS_PREFIX`, `_VERIFICATION_PREFIX`,
  `_AUTOFORMALIZATION_PREFIX`), each ≤200 chars (50-token
  heuristic). Placeholder `SYSTEM_PROMPT` (E08_S04 was supposed
  to land the real body — but didn't; **still placeholder** for
  E08_S06+ to address). Beta header constants
  `EXTENDED_CACHE_TTL_HEADER_NAME = "anthropic-beta"`,
  `EXTENDED_CACHE_TTL_HEADER_VALUE = "extended-cache-ttl-2025-04-11"`.
  Closed-at-four import-time check via `if … raise RuntimeError(…)`
  (NOT bare `assert` — survives `python -O`).
- `server/prompts.md` — companion doc; contains the verbatim AC#4
  sentence "BP3 is dropped; heterogeneous roles never share seed
  retrieval bytes" twice for survivability. Carries the ASCII
  message-structure diagram + "Why BP3 was dropped" rationale +
  Security section on `[Role:]` injection.
- `tests/test_prompts.py` — 33 tests. AST literal-only check on
  the prefixes. BP1 byte-identity test uses **live `ALL_TOOLS`**
  (rectification F1 — was a synthetic stub; live surface is the
  right thing). Pinned `EXPECTED_BP1_SHA256 = "f01de11288..."`
  (rectification F13).

**Key invariants:**
- BP1 (system + tools) byte-identical across the 4-agent fan-out.
- The `system` field in the integration-seam example uses the
  **list-of-content-blocks form** with `cache_control` on the
  LAST block — bare-string `system` silently drops `cache_control`
  per Anthropic Messages API.
- BP3 is **dropped** (not just deferred). The 4-breakpoint
  per-request budget retains 2 unused slots.
- Closed-at-four `RouteTag` × `ROLE_PREFIXES` invariant: adding a
  fifth value to either trips the import-time check.

#### E08_S03 — 3-tier retrieval cache

**Files shipped:**
- `server/cache.py` — `RetrievalCache` class. Tier 1 = SQLite-backed
  exact-query memo (1h TTL, 10K LRU cap, mirror enforces TTL on
  read per F2). Tier 2 = FAISS `IndexFlatIP` over recent query
  embeddings (15min TTL, ≥0.97 cosine, **searches top-K not
  top-1** per F9). Tier 3 = LRU rerank-set memo (1h TTL).
  Module-level singleton; `get_cache()`, `set_cache()`,
  `reset_cache_for_tests()`. Brief-spec aliases `lookup`/`store`
  added per F13 (over `lookup_search`/`store_search`).
- `server/cache_sqlite.py` — `Tier1Store` (stdlib `sqlite3` +
  `asyncio.to_thread`, no `aiosqlite`). WAL mode, schema-version
  migration, lazy TTL eviction. **Length-prefix encoding** in
  `derive_tier1_key` (rect F1, CRITICAL — `|`-separator was
  collision-prone). The new `canonical_key_components(...)`
  helper is shared with Tier-2 fingerprint (rect F12).
- `server/metrics.py` — Prometheus counters/gauges:
  `arxmcp_cache_lookups_total{tier}`, `_hits_total{tier}`,
  `_evictions_total{tier}`, `_bytes{tier}`,
  `arxmcp_cache_payload_skips_total{reason}` (rect F11),
  `arxmcp_retrieval_cap_rejections_total{tool}` (E08_S04 rect F9).
  `refresh_cache_metrics()` scrape-time hook called from
  `server/health.py`.
- `server/routes/__init__.py` + `server/routes/debug.py` — new
  sub-package. `GET /debug/cache-stats` returns per-tier stats JSON.
- `tests/test_cache.py` — 40 tests (was 28 in initial impl;
  rectification added 12 regression guards).

**Critical integration:** `server/handlers/search.py` was modified
even though the brief didn't list it as a deliverable. Cache
lookup before encode (Tier 1) + after encode (Tier 2) + store on
miss path. **`level` argument added to Tier-1 cache key** during
implementation — the brief omitted it but caching across distinct
`level` values is a correctness bug (verified empirically). The
fix is in `derive_tier1_key(..., level=None)` and propagated through
`lookup_search`/`store_search`.

**KMP_DUPLICATE_LIB_OK workaround:** `tests/conftest.py` sets
`KMP_DUPLICATE_LIB_OK=TRUE` via `os.environ.setdefault` BEFORE
the pytest import. This is the documented Intel-MKL workaround for
the `faiss-cpu` × PyTorch OpenMP-loader collision on macOS that
produces SIGSEGV in pytest. Cleared by `pytest_sessionfinish` if
WE set it (rect F10). **Test-only — production Linux containers
don't need it.**

**`pyproject.toml`:** added `faiss-cpu>=1.7` runtime dep (the only
external write authorized for the milestone).

**`tests/conftest.py`** also gained `_patched_cache_db_path` autouse
fixture (rect F4) — redirects `Config.cache_db_path` into
`tmp_path/cache/retrieval.db` so tests don't pollute the worktree.

#### E08_S04 — Tool-use ID canonicalization + retrieval caps

**Files shipped:**
- `server/orchestrator/__init__.py` — new package marker.
- `server/orchestrator/id_canon.py` — `canonicalize_turn(messages)
  -> list[dict]` returns a deep copy with `tool_use.id` and
  `tool_result.tool_use_id` rewritten to `toolu_{counter:08d}`.
  **MUST be called over the FULL accumulated history each time**
  (rect F1 — counter is per-call, reset on every invocation;
  passing only-new-turn produces ID collisions across transitions).
  Idempotent. Strict `isinstance(messages, list)` check (rect F10).
  Block with both `id` AND `tool_use_id` maps each independently
  (rect F4).
- `server/session.py` — `SessionState` dataclass + module-level
  registry. Per-session `asyncio.Lock`. **LRU eviction at 10K
  sessions.** Constants `MAX_SEARCH_PAPERS_CALLS = 3`,
  `MAX_GET_CHUNK_CALLS = 4`. `get_or_create_session`,
  `check_and_increment`, `reset_session_state_for_tests`.
- `server/middleware.py` — added `SessionCapMiddleware` (pure-ASGI;
  intercepts `POST /mcp` JSON-RPC body for `tools/call` with
  `search_papers` or `get_chunk`; short-circuits with structured
  `RETRIEVAL_CAP_REACHED` JSON-RPC response when over cap). **Strict
  `^[0-9a-f]{32}$` UUID4-hex format check** on `mcp-session-id`
  (rect F2 — narrows the trivial-cap-bypass attack surface;
  spoofed non-hex IDs skip cap accounting and forward to FastMCP
  which rejects with HTTP 404).
- `server/main.py` — wired `SessionCapMiddleware` between
  `BodySizeCapMiddleware` (innermost) and
  `RequestBodySizeLimitMiddleware`.
- `tests/conftest.py` — added `_reset_session_state_for_tests`
  autouse fixture.
- `tests/test_id_canon.py` — 22 tests (incl. 4 rectification
  guards).
- `tests/test_session_caps.py` — 31 tests (incl. 7 rectification
  guards). Existing test session-ids refactored via
  `_hex_session_id(seed)` helper to use the UUID4-hex format the
  F2 fix requires.
- `server/orchestrator/test_id_canon.py` — re-export stub at the
  brief's literal AC path (rect F3). Imports from
  `tests/test_id_canon.py` so `pytest server/orchestrator/test_id_canon.py`
  passes literally.
- `docs/orchestrator-rules.md` — canonical reference. Verbatim
  `canonicalize_turn` pseudocode + worked 4-agent 3-round example
  pinned by `tests/test_id_canon.py::TestFourAgentFanoutExample`.
  Wire format for `RETRIEVAL_CAP_REACHED`. "Why `result.isError=true`
  rather than a JSON-RPC error envelope" subsection (rect F8).
  "MUST pass FULL accumulated history each time" warning (rect F1).

**Critical contract for E08_S06+:** the orchestrator MUST call
`canonicalize_turn` over the FULL accumulated history each
transition. The contract is documented in the docstring with
`✅ RIGHT` / `❌ WRONG` examples; both behaviors are pinned by tests.

#### E08_S05 — Model selection policy

**Files shipped:**
- `server/orchestrator/model_selector.py` — `select_model(route_tag,
  turn_type) -> str` over a 12-cell `MappingProxyType`-wrapped
  table. `TurnType` enum (3 values: `RETRIEVAL`, `DRAFT`,
  `LEAN_WRITE`). Constants `MODEL_HAIKU_4_5 = "claude-haiku-4-5"`,
  `MODEL_SONNET_4_6 = "claude-sonnet-4-6"`, `POLICY_VERSION = "1.0"`
  (rect F3 — bumping signals cache-invalidation intent in PR diff).
  **`(LOOKUP, LEAN_WRITE)` and `(SYNTHESIS, LEAN_WRITE)` are
  FORBIDDEN** (rect F1) — `select_model` raises `ValueError` rather
  than silently returning Haiku. Closed-at-(4×3) + whitelist-only
  import-time invariants via `if … raise RuntimeError(…)`.
- `docs/model-policy.md` — verbatim "Verifier pass: dropped and
  why" section title (AC #5). Selection table + worked-example
  arithmetic ($0.054/query for Lookup, $0.075/query for
  Autoformalization). Cache-invalidation discipline section (rect
  F3) + CHANGELOG table.
- `tests/test_model_selector.py` — 46 tests (incl. 6 rectification
  guards). `TestForbiddenStrings` walks `server/**/*.py` asserting
  `"claude-opus"` is absent (AC #4). `TestRectificationGuards`
  also checks Haiku/Sonnet IDs appear ONLY in `model_selector.py`
  (rect F2 — extends the SSoT property to the two used IDs).

**Verifier-pass DROPPED.** `RouteTag.VERIFICATION` remains in the
router and `ROLE_PREFIXES` for query classification + BP1
byte-identity, but at dispatch time Verification queries route to
the Autoformalizer execution path. The model selector encodes this:
`select_model(VERIFICATION, X) == select_model(AUTOFORMALIZATION, X)`
for all `X`.

**`server/orchestrator/model_selector.py` is dead code as of this
commit** — nothing in `server/` calls `select_model` yet. The
orchestrator dispatch loop lands in **E08_S06+ (which doesn't exist
in the roadmap yet)**. The module's docstring has an "Integration
status" paragraph (rect F4) flagging this.

---

## 5. Architecture decisions cumulative across the session

These constraints are now load-bearing for ANY future milestone work.

### Cache byte-stability invariants

- **BP1** (system + tools) byte-identical across the 4-agent
  fan-out. Pinned by `tests/test_prompts.py::TestBP1ByteIdentityAcrossFanout`.
- **BP2** at the end of the role-prefix + problem-statement user
  turn.
- **BP3 dropped permanently** — heterogeneous roles never share
  seed retrieval bytes.
- **Tool-use ID canonicalization is mandatory** before composing
  one agent's tool history into another agent's context. Failure
  to canonicalize drops the cross-agent cache hit rate from ~95%
  to ~25%.
- **Cache key includes corpus_version** (Tier 1) and `level`
  (search_papers `level` arg). A corpus bump unreachable-izes
  prior entries by hash construction.
- **POLICY_VERSION** in `server/orchestrator/model_selector.py`
  must bump whenever `_SELECTION_TABLE` changes — Anthropic prompt
  cache key is `model + prefix bytes`.

### Session-id semantics

- Server-issued via `uuid4().hex` (32 lowercase hex chars). Per
  `server/middleware.py:_VALID_SESSION_ID_RE`.
- Cap middleware skips spoofed non-hex IDs (forwards them to
  FastMCP which rejects with HTTP 404).
- `mcp-session-id` is in `scope["headers"]` but does NOT flow
  into FastMCP `Context` — handlers cannot read it. The cap
  middleware reads it from headers + parses the JSON-RPC body
  to identify the tool name.

### Forbidden strings in `server/`

- `"claude-opus"` — AC #4 of E08_S05. Walked by
  `tests/test_model_selector.py::TestForbiddenStrings::test_no_claude_opus_in_server_python_files`.
- `"claude-haiku-4-5"` and `"claude-sonnet-4-6"` allowed ONLY in
  `server/orchestrator/model_selector.py` — rect F2 of E08_S05.
  Walked by
  `tests/test_model_selector.py::TestRectificationGuards::test_f2_haiku_and_sonnet_appear_only_in_model_selector`.
- This means **the orchestrator dispatch loop (E08_S06+) MUST call
  `select_model(...)` rather than hardcoding model IDs**.

### Failure-mode discipline

Every cache layer + cap layer wraps internal operations in
`try/except Exception` that logs and falls through. Per
`.claude/notes/07-multi-agent-caching.md`: *"Cache layer crash /
OOM → Fall through to recompute; log; alert. Caching is
performance, not correctness."* The retrieval cap is a defensive
ceiling (per the brief), not a security boundary. NEVER let an
internal cache/cap error propagate to the request handler.

### Hard rules from the design constitution

- **Loopback-only bind**. `server/config.py:reject_non_loopback`
  rejects `0.0.0.0` and any non-loopback host at config-parse time.
- **Pure-ASGI middleware required**. `BaseHTTPMiddleware` is
  project-banned (E06_S01 F1: silently no-ops response interception
  for SSE paths). Every middleware in `server/middleware.py` uses
  the `__call__(self, scope, receive, send)` shape.
- **`assert` is BANNED for invariants** — Python `-O` strips them.
  Use `if … raise RuntimeError(…)` instead. Pinned by F4 from the
  E08_S02 critique; mirrored in E08_S05's `model_selector.py`
  closed-at-N check.
- **No-fork policy**. Nothing lifted from existing arxiv-MCP
  repos. Verified by greps for `arxiv-mcp` / `blazickjp` /
  `MCP-arxiv` returning zero hits.

---

## 6. State of the codebase

### `server/` directory layout (as of this snapshot)

```
server/
├── __init__.py
├── _mcp_mount.py            # FastMCP Streamable HTTP mount
├── cache.py                 # E08_S03 — RetrievalCache
├── cache_sqlite.py          # E08_S03 — Tier1Store
├── config.py                # pydantic-settings; loopback-only bind
├── corpus.py                # CorpusVersionInfo + open_chunks_table
├── handlers/                # MCP tool implementations (E06_S03+)
│   ├── chunk.py
│   ├── citations.py
│   ├── definitions.py
│   ├── equation.py
│   ├── lemma.py
│   ├── paper.py
│   └── search.py            # ↑ modified by E08_S03 cache integration
├── health.py                # /healthz, /readyz, refresh_metrics
├── main.py                  # FastAPI app + lifespan + middleware stack
├── metrics.py               # E08_S03 + E08_S04 — cache + cap counters
├── middleware.py            # E06_S05 + E08_S04 — pure-ASGI middlewares
├── orchestrator/            # E08_S04+
│   ├── __init__.py
│   ├── id_canon.py          # canonicalize_turn
│   ├── model_selector.py    # E08_S05 — select_model (DEAD CODE today)
│   └── test_id_canon.py     # re-export stub for AC literal path
├── prompts.py               # E08_S02 — ROLE_PREFIXES
├── prompts.md               # E08_S02 — companion doc
├── query_encoder.py         # BGE-M3 + singleflight
├── resources.py             # Process lifecycle singleton
├── retrieval/               # E07 — BM25, ANN, RRF, Rerank phases
│   ├── ann.py
│   ├── bm25.py
│   ├── rerank.py            # ↑ modified by E08_S03 Tier-3 wiring
│   └── rrf.py
├── router.py                # E08_S01 — RouteTag + regex classifier
├── router_patterns.yaml
├── routes/                  # E08_S03 — non-tool HTTP routes
│   ├── __init__.py
│   └── debug.py             # GET /debug/cache-stats
├── schemas/                 # E04 — pyarrow / pydantic schemas
├── session.py               # E08_S04 — SessionState
└── tools.py                 # MCP tool registration + envelope
```

### Existing dependencies (`pyproject.toml`)

Runtime: `beautifulsoup4`, `transformers>=4.40`, `torch>=2.0`,
`safetensors>=0.4`, `numpy>=1.24`, `lancedb>=0.6`, `pyarrow>=14.0`,
`rank-bm25>=0.2`, `mcp>=1.27,<2`, `fastapi>=0.115`,
`uvicorn[standard]>=0.30`, `pydantic-settings>=2.4`,
`prometheus-client>=0.20`, `pyyaml>=6.0`, **`faiss-cpu>=1.7`** (added
in E08_S03).

Dev: `ruff>=0.5`, `pytest>=8.0`.

### Pytest configuration (`pyproject.toml`)

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
markers = [
    "requires_model: tests that download / load a real ML model ...",
    "eval: end-to-end retrieval-quality eval ...",
]
```

The `testpaths = ["tests"]` constraint is load-bearing — files at
`server/orchestrator/test_*.py` won't run via plain `pytest`. The
re-export stub at `server/orchestrator/test_id_canon.py` is a
workaround for the E08_S04 AC; explicit `pytest <path>` invocation
also works.

### Test inventory (~46 test files)

Notable test files tied to recent milestone work:
- `tests/test_prompts.py` — 33 tests (E08_S02)
- `tests/test_cache.py` — 40 tests (E08_S03)
- `tests/test_id_canon.py` — 22 tests (E08_S04)
- `tests/test_session_caps.py` — 31 tests (E08_S04)
- `tests/test_model_selector.py` — 46 tests (E08_S05)

Total project: **1177 passed, 4 skipped** (the 4 skips are
`requires_model` tests gated by env vars).

### Uncommitted state

`git status` shows ~10 modified `state.json` files under
`.claude/notes/milestones/E0[6-8]_*` — these are state-machine
updates to OLDER milestones from prior sessions, NOT this session's
work. They are SAFE to ignore unless an explicit user direction
arrives. The session's own milestones (E08_S02 through E08_S05)
have all `state.json` files committed.

---

## 7. What remains (next sessions)

### Immediate next milestone candidates

**E08 epic is structurally complete** — the roadmap defines exactly
S01–S05 for E08 and all five are shipped. No E08_S06 exists in the
roadmap. However, the implementation is **not yet wired into a
working orchestrator**:

- `server/orchestrator/model_selector.py` is **dead code** —
  nothing calls `select_model`.
- `server/orchestrator/id_canon.py::canonicalize_turn` is also
  unwired.
- `SessionCapMiddleware` is the ONLY E08 piece that's runtime-active.

The natural next step is **either**:

1. **Start E09 epic** (Citation Graph) — 4 milestones (S01–S04).
   First milestone: `E09_S01 — Kùzu schema migrations and OpenAlex
   bulk ingest`. Listed as **Tier 3** in the roadmap; **Dependencies:
   E04, E06, E07, E08** — all shipped. This is the natural next epic
   per the roadmap's tier sequence.

2. **Author an "E08_S06 orchestrator dispatch loop" milestone**
   (NOT in the roadmap currently). Would be NEW work scoped by the
   user. The integration test that asserts `select_model` is the
   only model-ID source must land WITH this milestone (per the
   E08_S05 rect F4 docstring note).

3. **Pick up Tier-0 work that hasn't shipped yet** — the roadmap
   notes E02–E08 are NEW status in the index, but the per-epic
   detail files have many milestones marked `done`. Cross-check
   `.claude/notes/milestones/<EXX_SYY>/state.json` for `phase ==
   "complete"` to identify done vs new work. (Most of E02–E08
   appears complete; E09–E14 has no milestones started.)

The user has been working linearly through E08; **E09_S01 is the
most likely next ask** unless they pivot.

### Deferred LOW findings (across all session milestones)

These were explicitly deferred per the rectifier protocol; they're
not bugs but worth knowing about. None are urgent.

| Finding | Where | Description |
|---|---|---|
| E08_S02 F5 | `server/prompts.py` | `MappingProxyType` is defense-in-depth in name only (`dict(ROLE_PREFIXES)` bypasses it). |
| E08_S02 F6 | `tests/test_prompts.py` | AC #4 verbatim-substring match is brittle to markdown edits. |
| E08_S02 F9 | `server/prompts.md` | Cross-references use line-numbered citations that may drift. |
| E08_S02 F10 | `server/prompts.py` | No "DO NOT refactor this dict literal" warning comment. |
| E08_S03 F17 | `server/cache.py` | `_value.get()` reads the prometheus_client private API. |
| E08_S03 F20 | (no test) | No load-test validating the brief's "40-60% Tier-3 hit rate" claim. |
| E08_S04 F11 | `server/middleware.py` | `SessionCapMiddleware` buffers the body for any POST `/mcp`, not just `tools/call`. Optimization opportunity. |
| E08_S04 F12 | `server/middleware.py` | `RETRIEVAL_CAP_REACHED` exposes `session_attempted_count` (only requesting client's own state). |
| E08_S04 F13 | `docs/orchestrator-rules.md` | Worked example doesn't exercise nested-content `tool_result.content` shape. |
| E08_S05 F5 | `server/orchestrator/model_selector.py` | `select_model` doesn't `isinstance`-check args (mypy catches at static-analysis time). |
| E08_S05 F6 | `tests/test_model_selector.py` | Brittle StrEnum-equality test. |
| E08_S05 F7 | `docs/model-policy.md` | Haiku 2048-token cache caveat is unverified (the `(Verify.)` from `.claude/notes/07-multi-agent-caching.md`). |
| E08_S05 F10 | `server/orchestrator/model_selector.py` | Module import pulls in YAML loader via `server.router` (~17ms). |

### Outstanding TODOs in shipped code

- `server/prompts.py` — `SYSTEM_PROMPT` is still a placeholder
  (`"<placeholder system prompt — E08_S04 will author the v1
  body...>"`). E08_S04 did NOT actually land a real system prompt
  body; this is now an open task for whichever milestone lands the
  orchestrator dispatch loop. When the real prompt lands, the
  pinned `EXPECTED_BP1_SHA256` in `tests/test_prompts.py` must be
  bumped (the test docstring describes the procedure).
- `server/prompts.py` — `EXTENDED_CACHE_TTL_HEADER_VALUE` carries
  a `TODO(E08_S04)` to verify the header value against current
  Anthropic docs. E08_S04 didn't address this either.

### Known gotchas / things-that-always-break

1. **macOS pytest segfault with faiss-cpu + PyTorch.** The
   `KMP_DUPLICATE_LIB_OK=TRUE` workaround in `tests/conftest.py`
   is required for the full `pytest` run to not SIGSEGV. The env
   var is cleared at session end if `conftest.py` set it.
   Production Linux containers don't need it.

2. **`pytest server/orchestrator/test_id_canon.py` works only
   because of the re-export stub.** If a future contributor moves
   tests around they MUST keep the stub working — the brief's AC
   path is load-bearing.

3. **Anthropic library is BANNED at runtime.**
   `tests/test_snippet_contract.py:340-351` actively asserts
   `import anthropic` is NOT present at handler load. Don't add
   `anthropic` as a dep without coordinating with the test.

4. **Body-buffering DoS via `SessionCapMiddleware`** is bounded by
   `RequestBodySizeLimitMiddleware` mounted upstream. Mount order
   is asserted by
   `tests/test_session_caps.py::TestRectificationGuards::test_f7_middleware_order_session_cap_inside_request_body_size_limit`.
   Don't reorder middlewares without checking that test.

5. **The `claude/gallant-blackburn-b89422` branch is local only.**
   No `git push` has happened. The user has not authorized one;
   it's per-event authorization.

6. **HEREDOC commits.** When the commit body has apostrophes
   (`"don't"`, `"won't"`, etc.), bash mangles `$(cat <<'EOF' …
   EOF)` form. Use the alternative form
   `git commit -F - <<'COMMIT_EOF' … COMMIT_EOF` (read from stdin)
   — that survives apostrophes in the body.

---

## 8. The 10 design notes (constitutional)

Future agents picking up this work MUST read these before making
non-trivial decisions. They live in `.claude/notes/`:

| File | What it covers |
|---|---|
| `01-mission-and-context.md` | Why arXMCP exists; "Lean kernel is the better critic" framing |
| `02-architecture-overview.md` | High-level system shape |
| `03-ingestion-pipeline.md` | arXiv → LaTeXML → chunker → embedder → LanceDB flow |
| `04-parsing-and-chunking.md` | Chunk discipline; theorem/proof split; 512-token BGE-M3 limit |
| `05-storage-and-indexing.md` | LanceDB schema; MVCC; per-corpus-version pinning |
| `06-mcp-server-design.md` | MCP 2025-06-18 spec; Streamable HTTP; loopback-only; 256 KB byte cap |
| `07-multi-agent-caching.md` | THE cache discipline note. BP1/BP2/BP3, tool-use ID canonicalization, the "single most underrated optimization" framing |
| `08-security-observability-ops.md` | Threat model; Threat 4 (loopback); Threat 5 (DNS rebinding); Threat 6 (no pickle weights) |
| `09-feature-priorities.md` | Superseded by `.claude/roadmap/README.md` (kept on disk for history) |
| `10-references-and-prior-art.md` | Bibliography for design decisions |

The `.claude/roadmap/README.md` is the *how*; the `.claude/notes/`
files are the *why*. **Quote them, don't paraphrase.**

---

## 9. How to resume

1. **`cd` into the worktree**: `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422`
2. **Activate the venv**: `source .venv/bin/activate`
3. **Verify clean state**: `ruff check . && pytest -q | tail -3`
   should report `1177 passed, 4 skipped`.
4. **Pick the next milestone** (likely E09_S01 unless the user
   redirects). Read its brief at
   `.claude/roadmap/E09-citation-graph.md`.
5. **Invoke the milestone-pipeline skill**: `/milestone-pipeline E09_S01`
   (or whichever milestone). The skill is mandatory — DO NOT
   bypass it for non-trivial work.
6. **Phase 1** dispatches researchers in a SINGLE assistant turn.
7. **Phase 2** writes code; verify `ruff check .` + full pytest
   green BEFORE committing.
8. **Phase 3** dispatches the Opus adversary critic in a SINGLE
   assistant turn (infra-safety conditional, oss-scout opt-in).
9. **Phase 4** in the main session; fix CRITICAL+HIGH always,
   MEDIUM if cheap, defer LOW. Commit as `rect(<scope>): close
   <count> <severity> ...`.
10. **State machine** at every step:
    `.claude/skills/milestone-pipeline/scripts/checkpoint.py <ID> --set phase=<next>`.

---

## 10. The user

- **`chris.dare@nalej.com`** is the primary user.
- They invoke milestones with `/milestone-pipeline E<NN>_S<MM>`.
- They expect autonomous execution (auto-mode framing) and
  minimal interruption — make reasonable assumptions and proceed.
- They expect rigorous adherence to the 4-phase pipeline. Skipping
  phases or short-circuiting the rectifier protocol is unwelcome.
- They appreciate concise summaries at end of each milestone with
  the key changes, test count delta, and invalidation rate.

---

## 11. Cumulative test/lint/commit deltas across the session

| Metric | Start of session | End of session | Delta |
|---|---|---|---|
| Full pytest suite | ~1000 (estimated baseline before E08_S02) | 1177 passed, 4 skipped | +177 tests |
| `ruff check .` | clean | clean | (always green) |
| Commits on branch | ~70 | 78 | +8 commits (4 feat + 4 rect, one per session-shipped milestone) |
| Files added to `server/` | (existed) | +6 (cache.py, cache_sqlite.py, metrics.py, prompts.py, session.py, orchestrator/) | |
| Files added to `tests/` | (existed) | +5 (test_cache.py, test_id_canon.py, test_model_selector.py, test_prompts.py, test_session_caps.py) | |
| Files added to `docs/` | (didn't exist) | 2 (orchestrator-rules.md, model-policy.md) | +2 |

The session shipped a coherent slice of the agent-runtime epic:
prompt-cache discipline (E08_S02), retrieval cache (E08_S03),
runtime safety nets (E08_S04), and the model-selection policy
freeze (E08_S05). Combined, this is the foundation a future
orchestrator dispatch loop will build on.

---

**End of handoff.**
