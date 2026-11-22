# CLAUDE.md

Rules for agents working in arXMCP. [`CREDO.md`](CREDO.md) states what the
repository holds and refuses; where this file disagrees with it, the Credo
wins. Guides, runbooks and design notes live in the
[wiki](https://github.com/chris-dare-dev/arXMCP/wiki), not here.

## What arXMCP is

A local-first MCP server that exposes a research-mathematics arXiv corpus to
multi-agent Claude pipelines (sketcher → autoformalizer → tactician → fixer).
The MCP tool surface is the agent interface; a loopback-only Jinja2 + htmx
operator console at `/ui/` manages notebooks. No SPA, no Node build chain.
Retrieval and pre-loading are where the effort goes: the Lean kernel, not an
LLM, is the critic.

Layout: `src/arxmcp/` is the one Python package, holding `server/` (MCP
server, handlers, retrieval, console), `ingest/` (corpus pipeline), `shim/`
(stdio ↔ HTTP bridge), `ops/` (backup, cutover, drift) and `tools/` (developer
and ingest utilities). `src/desktop/` is the Tauri supervisor and PyInstaller
packaging, `deploy/` the container, compose and k8s files, and `tests/` the
suite. `var/` is the gitignored data tree. The import-linter contract in
`pyproject.toml` enforces which box may import which.

## Hard constraints

- **Loopback only.** The server binds `127.0.0.1:7733` and refuses `0.0.0.0`
  at config-parse time unless `ARXMCP_UNSAFE_NETWORK_BIND=1`.
- **MCP 2025-06-18 Streamable HTTP.** No SSE; single-shot JSON responses.
- **Math fidelity over recall.** LaTeXML + MathML; never PyPDF as the primary
  parser.
- **The server never runs agents.** No agent loop, dispatch or per-run agent
  memory server-side. The `anthropic` SDK stays out of `server/` and out of
  the runtime dependencies. The orchestrator loop lives in another repository;
  `src/arxmcp/server/orchestrator/` is an SDK-free policy library.
- **Writes enter only through offline ingest CLIs or operator-confirmed
  `/ui/` actions.** MCP tools are read-only over corpus state; `lean_verify`
  computes and never persists corpus-visible state.
- **Non-commercially-licensed data** enters only a candidate layer and is
  never served as evidence without a recorded per-source license check.

## Trust language

- **No bare "verified".** Trust is a multi-axis record; no axis is inferred
  from another. New trust-bearing fields are namespaced per axis, never a new
  bare `status`. `lean_verify` reports `status: "elaborated_no_errors"` and a
  separate `axiom_audit` axis; formal alignment and checker identity are not
  measured and are absent, not defaulted to passing.
- **Abstention is a success state.** Tools return `unknown` / `ambiguous` /
  `not-in-corpus` / `unsupported-by-provider`, kept distinct from operational
  status (`timeout` / `unavailable` / `disabled` / `invalid-input`) and from a
  degraded-but-answered result.
- **Absence claims are dated censuses** (named set, queries run, date,
  verdict). Internal facts are cited by file, not paraphrased.

## Coding conventions

- **`assert` is banned for invariants** outside `tests/` (`python -O` strips
  it). Use `if … raise RuntimeError(…)`. Ruff `S101` enforces it;
  `tests/test_assert_ban.py` pins the config.
- **Pure-ASGI middleware only.** `BaseHTTPMiddleware` silently stops
  intercepting streamed responses.
- **`server/` never references `claude-opus`.** Model selection in the
  orchestrator policy is Haiku/Sonnet only.
- **No-fork policy.** Take ideas from other arXiv MCP projects, never code.
- Comments explain why the code is the way it is. No issue, PR, milestone or
  date provenance in identifiers or comments (CREDO §4).

## Repository hygiene

- Markdown is limited to the allow-list in CREDO.md; the `credo` workflow
  fails any tracked Markdown outside it.
- `.claude/`, `.cargo/` and `.milestone-pipeline/` are machine-local and
  gitignored. Never force-add them, and never commit plans, briefs,
  critiques, agent memory, run output or anything a command can regenerate.
- A code change never carries an edit to a guide or runbook. If one is now
  wrong, say so in the pull request; the wiki is updated apart.

## Commits and pull requests

- Work on a branch and open a pull request; the owner reads and merges it.
  Push only when asked, and each push needs its own go-ahead. Never
  force-push `main`.
- Conventional commits, subject ≤ 50 chars after the type. Types: `feat`,
  `fix`, `test`, `chore`, `ci`, `docs`. Scopes match subsystems.
- **No co-author or attribution trailers.** No `Co-Authored-By:`,
  `Generated-with:` or equivalent naming Claude, Codex or any other agent or
  tool, whatever older commits in `git log` show.
- Never `--no-verify` or `--no-gpg-sign`. If a hook fails, fix the cause and
  make a new commit.
- Use `git commit -F - <<'EOF' … EOF` so apostrophes survive.

## Tests

- `make test` runs `ruff check .`, the import-linter contract, then `pytest`,
  and must be green before a pull request. Without `make`, run those steps
  with the venv's Python (`uv sync --locked`, then `.venv/bin/lint-imports`
  and `.venv/bin/python -m pytest`).
- Tests assert behaviour a caller of the product can observe. Never test the
  wording of documentation or agent instructions.
- `requires_*` markers are opt-in: the hook in `tests/conftest.py` skips them
  unless `-m` names them. A new opt-in marker goes in both `pyproject.toml`
  and `_OPT_IN_MARKERS`; registering it in one place only makes it run
  everywhere. `eval` is opt-out.
- The desktop gates (`make desktop-conformance`, `desktop-package-check`,
  `desktop-bundle-check`, `desktop-model-check`) set an env var that turns
  any skip into a failure; most are macOS-only in practice.

## Packaging boundary

A source checkout hides packaging bugs: the repo root is on `sys.path` and
every data file is on disk.

- A package in `[tool.setuptools.packages.find].include` ships only its `.py`
  files. Every other file needs a `[tool.setuptools.package-data]` glob;
  `tests/test_wheel_packaging.py` fails on any unmatched data file.
- A tree added to that include list needs a matching `COPY` in
  `deploy/Dockerfile.server`.
- Run `make wheel-check` after touching `pyproject.toml`, and
  `make wheel-check-full` before a release.

## Adding an MCP tool

1. Write the handler in `src/arxmcp/server/handlers/<tool>.py`.
2. Add a `ToolMeta` to `ALL_TOOLS` in `src/arxmcp/server/tools.py` and wire it in
   `register_all(...)`.
3. `tools/list` must stay byte-stable for prompt caching: re-pin
   `EXPECTED_TOOL_SCHEMA_SHA256` with `pytest --update-tool-schema-hash`.
4. Add `tests/test_handlers_<tool>.py`. Snippet-bearing results keep the
   150-character snippet contract in `src/arxmcp/server/handlers/search.py`.

## Known deferrals

- `get_chunk(include_equations=...)` is accepted and ignored (echoed in
  `unused_args`). `search_papers`' `cursor` is ignored; `next_cursor` is
  always `null`. Unknown `filters` keys surface in `filter_warnings`.
- `find_equation` on LaTeX input is dense-only unless `eq_latex_route` is on.
- `embedding_eq` is reserved and always NULL.
- `tests/eval/fixtures/queries.json` has no curated queries yet, so
  `make eval` skips.
- Tool description strings can lag behaviour, because `tools/list` is
  re-pinned in batches. Trust the handler code over the description.
- A missing index degrades rather than fails: read `retrieval_mode` or
  `graph_status` before concluding a query found nothing.

## Gotchas

- **macOS pytest segfault** (faiss + PyTorch OpenMP): `tests/conftest.py`
  sets `KMP_DUPLICATE_LIB_OK=TRUE` for the session.
- **Kùzu is archived upstream**; `kuzu==0.11.3` is pinned exactly. Close
  connections before databases (`conn.close(); db.close()`).
- **The server rejects `ARXMCP_CONTACT_EMAIL`.** It is an ingest-tool
  variable; export it only in shells that run ingest CLIs.
- **`RLIMIT_AS` does not work on macOS** (the kernel refuses to lower it);
  sandboxes gate `preexec_fn` on Linux and rely on wall timeouts elsewhere.
- **MinerU's internal API server survives `os.killpg`**: it starts its own
  session. Accepted because it is loopback-only.
- **Tool-use ID canonicalization runs over the full history each turn**, not
  the new slice, or IDs collide across turns.
- **The macOS floor is 14.0** (faiss ships only a `macosx_14_0_arm64` wheel).
  It is declared in `tauri.conf.json`, the Makefile's `DESKTOP_MACOS_FLOOR`
  and `desktop_package.MACOS_DEPLOYMENT_TARGET`; keep the three equal.
- **Windows:** a running `arxmcp-shim.exe` locks the venv, so `uv sync`
  fails after a `[project.scripts]` change. Stop the shim, then sync once.

## Platform ownership

The Windows machine builds and qualifies the Windows distribution; the Mac
builds and qualifies the macOS distribution. Neither takes over the other's
platform work or treats results from the wrong host as release evidence.

## Where to look when something breaks

| Symptom | First file |
|---|---|
| Tests segfault on macOS | `tests/conftest.py` |
| Server refuses to bind | `src/arxmcp/settings/config.py` (`reject_non_loopback`) |
| `tools/list` hash drift | `tests/test_server_tool_schema.py`, `src/arxmcp/server/tools.py` |
| Prompt cache misses between roles | `src/arxmcp/server/prompts.py`, `src/arxmcp/server/orchestrator/id_canon.py` |
| Stale retrieval results | `src/arxmcp/server/corpus_freshness.py`, then `src/arxmcp/server/cache.py` |
| Empty citation neighbours | `src/arxmcp/server/handlers/citations.py` (`graph_status` first) |
