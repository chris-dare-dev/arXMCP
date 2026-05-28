# Installing arxmcp for Claude Code

The arxmcp package ships two artifacts:

- **`arxmcp-server`** — the long-running MCP server (E06_S01) that
  owns the BGE-M3 embedder, the LanceDB index, and (when E07 lands)
  the BM25 + reranker pipeline. Run as a single instance per
  workstation.
- **`arxmcp-shim`** — a tiny stdio↔HTTP bridge (E06_S02). Claude
  Code spawns one shim process per sub-agent (per the
  `~/.claude.json` registration); each shim forwards JSON-RPC
  frames to the same shared `arxmcp-server`.

This split is load-bearing: the long-running server holds the warm
BGE-M3 weights, the LanceDB connection, and the per-process query
cache, so every sub-agent benefits from the shared retrieval cache
across separate Claude context windows.

## 1. Install

```sh
pipx install arxmcp        # preferred — isolates the install
# or:
pip install arxmcp         # if you want it in your active venv
```

### Optional ingest system deps

The runtime server (`arxmcp-server`) has no system dependencies
beyond Python ≥3.11. The optional **bulk ingest pipeline** (E11_S01,
`make ingest`) and the **LaTeXML drift detector** (E10_S04,
`ops/cron/latexml-drift-check.sh`) need two system binaries:

- **`aria2c`** — BitTorrent client used to download the Academic
  Torrents arXiv source dump. `brew install aria2` (macOS) or
  `apt install aria2` (Debian/Ubuntu). Only needed if you're
  running `make ingest` against a fresh corpus; the 50-paper
  seed fetch does not use it.
- **`latexmlc`** — LaTeXML's CLI driver. `brew install latexml`
  (macOS) or `apt install latexml` (Debian/Ubuntu). Used as the
  fallback for papers whose ar5iv cache misses, AND by the daily
  drift-detector cron. Not needed for the MCP server itself.

### Optional textbook-ingest dep — MinerU

The textbook-ingest pipeline (`textbook-ingest-e2`) parses
operator-supplied PDFs via **MinerU 3.x** running in a sandboxed
subprocess. MinerU pulls a large PyTorch + ONNX + transformers tree —
install it into a **separate venv** rather than the project venv:

```sh
# macOS / Apple Silicon (MLX backend)
uv venv ~/venvs/mineru
uv pip install --python ~/venvs/mineru/bin/python 'mineru[pipeline,mlx]'

# Linux (CPU pipeline only)
uv venv ~/venvs/mineru
uv pip install --python ~/venvs/mineru/bin/python 'mineru[pipeline]'

# Pre-download the ONNX model weights (one-time, ~5-7 GB)
~/venvs/mineru/bin/mineru-models-download -s huggingface -m pipeline
```

Two environment variables control the m5 sandbox driver
(`ingest/textbook_parser.py`):

- **`ARXMCP_MINERU_BIN`** — absolute path to the `mineru` CLI binary.
  Required for textbook-ingest. Example:
  `export ARXMCP_MINERU_BIN=~/venvs/mineru/bin/mineru`. Without it
  the driver falls back to `shutil.which("mineru")` and raises
  `RuntimeError` if not found.
- **`ARXMCP_MINERU_TIMEOUT_S`** — wall-clock cap on a single MinerU
  invocation in seconds. Default 1800 (30 min). Valid range
  [60, 3600]. Parsed at module load — out-of-range values raise
  `RuntimeError` at server startup rather than silently clamping.

### Textbook ingest end-to-end (m6 + later)

After uploading a PDF to a `notebook_kind="textbook"` notebook, the
m6 background pipeline runs MinerU + LaTeXML to produce HTML5+MathML.
The upload returns immediately (201 with the HTML row fragment); the
parse runs in the background. Poll the parse status via:

```
GET /ui/api/notebooks/<slug>/parse-status
```

The endpoint returns JSON with the following fields:

```json
{
  "slug": "<notebook-slug>",
  "notebook_kind": "textbook",
  "parse_status": "pending|running|complete|failed|skipped",
  "parse_error": "<HTML-escaped tail; empty unless failed>",
  "parsed_html_path": "<absolute path to index.html; empty unless complete>"
}
```

States:
- **`skipped`** — arxiv-kind notebook; no parse pipeline applies.
- **`pending`** — textbook notebook created but no PDF uploaded yet.
- **`running`** — MinerU + LaTeXML pipeline is in flight (typically 5–30 min).
- **`complete`** — `parsed_html_path` points at the rendered `index.html`.
- **`failed`** — `parse_error` carries an HTML-escaped tail of the failure.

The parse pipeline is **serialized via `asyncio.Semaphore(1)`** —
at most one MinerU/LaTeXML run happens at a time across all
notebooks to avoid GPU/MLX memory pressure on Apple Silicon.

After a server restart, any rows stuck in `parse_status='running'`
are reset to `failed` at lifespan startup (`mark_orphaned_parses_failed`
sweep). Operators can retry the upload to schedule a fresh parse.

**Platform note (macOS):** the 4 GB virtual-memory cap
(`RLIMIT_AS`) that the sandbox profile prescribes is **not enforceable
on macOS** (the Darwin kernel keeps the hard limit at `RLIM_INFINITY`
and refuses lowering — verified live test on Darwin 25.4.0 / Apple
M4 Max). On macOS the 30-min wall timeout is the only memory backstop.
Linux deployments get the full RLIMIT_AS cap as designed. See
[`.claude/docs/security-pdf-sandbox.md`](../.claude/docs/security-pdf-sandbox.md)
for the full sandbox profile rationale.

After install, both binaries are on `$PATH`:

```sh
arxmcp-server --help       # FastAPI runner; defaults to 127.0.0.1:7733
arxmcp-shim --help         # stdio shim; --server overrides the address
```

## 2. Register with Claude Code

Open `~/.claude.json` and merge this block into the top-level object
(if `mcpServers` already exists, add the `"arxmcp"` key alongside
your existing entries):

```json
{
  "mcpServers": {
    "arxmcp": {
      "command": "arxmcp-shim",
      "args": ["--server", "http://127.0.0.1:7733"]
    }
  }
}
```

The block above is **verbatim** the snippet from
[`.claude/notes/06-mcp-server-design.md`](../.claude/notes/06-mcp-server-design.md)
(the project's design constitution). Do NOT modify it — the shim
binary name, the `--server` URL, and the port number are all the
v1 defaults the project guarantees.

If you want to bind the server to a non-default port, set
`ARXMCP_BIND_PORT=...` in the server's environment AND update both
the `--server` URL above AND the `-p 127.0.0.1:PORT:PORT` mapping
when running the Docker image.

## 3. Run the server

```sh
make up
# or, equivalently:
python -m server.main
```

The server eager-loads the BGE-M3 model on startup (~5–30 s on
warm Hugging Face cache, longer on a first-run download). Wait for
the log line:

```
Resources.startup: warm
```

…before invoking Claude Code. The shim's startup probe (`GET
/readyz`) prints a readable error to stderr if the server is not
ready, so a misordered start surfaces clearly rather than hanging.

## 4. Verify the shim end-to-end

```sh
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | arxmcp-shim
```

Should print a JSON line containing `"tools": [...]` (empty until
E06_S03 lands the seven canonical tools). If you see
`FATAL: cannot reach arxmcp-server`, the server is not running on
the configured port; double-check `make up` is alive.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `arxmcp-shim: command not found` | pipx/pip didn't install | re-run `pipx install arxmcp` |
| Shim exits with `FATAL: arxmcp-server returned 503` | Server is mid-warmup or LanceDB corpus is missing | wait for `/readyz` 200, or run the ingest pipeline first |
| Shim hangs on first request | `json_response=True` not set on server, so it returns SSE the shim can't parse | the v1 server sets it by default; this should not happen on a fresh install |
| `Mcp-Session-Id` errors | spec violation upstream | report; shim captures session-id from response headers per MCP 2025-06-18 |

## Why a separate shim process per sub-agent

Claude Code's MCP harness spawns one stdio process per registered
server PER sub-agent. The shim is intentionally tiny (≤60 lines of
executable code) so spawn overhead stays in the millisecond range.
Each shim is stateless across invocations (no persistent disk, no
auth material); the only per-process state is the `Mcp-Session-Id`
the MCP spec requires the client to echo for the duration of a
connection. All shims hit the same long-running server and share
its retrieval cache via the BP1 byte-stable cache key contract.

## Out of scope

- **TLS** — the v1 server is loopback-only; no certs.
- **Authentication** — design choice per
  [`.claude/notes/06-mcp-server-design.md`](../.claude/notes/06-mcp-server-design.md).
- **Remote shim → server bridges** — operators who want to run the
  shim on one host and the server on another need a localhost-tunnel
  (SSH `-L`, etc.); that's not a v1 deliverable.
