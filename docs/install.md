# Installing arXMCP for Claude Code

arXMCP ships two artifacts:

- **`arxmcp-server`** — the long-running MCP server that owns the BGE-M3
  embedder and the LanceDB index. Run as a single instance per workstation.
- **`arxmcp-shim`** — a tiny stdio↔HTTP bridge. Claude
  Code spawns one shim process per sub-agent (per the
  `~/.claude.json` registration); each shim forwards JSON-RPC
  frames to the same shared `arxmcp-server`.

This split is load-bearing: the long-running server holds the warm
BGE-M3 weights, the LanceDB connection, and the per-process query
cache, so every sub-agent benefits from the shared retrieval cache
across separate Claude context windows.

## 1. Install

arXMCP is **not yet published to PyPI** — install from source. This puts both
`arxmcp-server` and `arxmcp-shim` on your `$PATH`:

```sh
git clone https://github.com/chris-dare-dev/arXMCP.git && cd arXMCP
python3 -m venv .venv && source .venv/bin/activate
make bootstrap             # editable install (pip install -e ".[dev]") + var/ tree
```

(When a release is published to PyPI, `pipx install arxmcp` will become the
preferred path — see [releasing.md](releasing.md).)

### Running on Windows (no `make`)

The commands above (and the rest of this guide) assume a POSIX shell with GNU
`make`. The arXMCP **server and the `/ui/` operator console run on native
Windows**, but the `Makefile` is bash-only and `make` is usually absent, so use
the make-free invocations below from **PowerShell**. (For the full ingest /
ops workflow, prefer **WSL2** or **Docker** — see the caveats.)

```powershell
# 1. Clone, create + activate the venv, editable-install.
git clone https://github.com/chris-dare-dev/arXMCP.git
Set-Location arXMCP
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"          # replaces `make bootstrap`'s install step

# 2. Create the var/ data tree `make bootstrap` would have made.
New-Item -ItemType Directory -Force -Path `
  var\arxmcp\corpus\raw, var\arxmcp\corpus\parsed, var\arxmcp\corpus\chunks, `
  var\arxmcp\index\lancedb, var\arxmcp\index\kuzu, var\arxmcp\cache\ar5iv, `
  var\arxmcp\ops\parser-failures, var\arxmcp\observability\phoenix | Out-Null

# 3a. Run the server (replaces `make up`). Fresh clone with NO corpus yet?
#     Use bootstrap/wizard mode so it boots without one (replaces `make up-wizard`):
$env:ARXMCP_BOOTSTRAP_MODE = "1"; python -m server.main

# 3b. Or serve an ingested notebook (replaces `ARXMCP_NOTEBOOK=demo make up`).
#     PowerShell has no inline `VAR=x cmd` prefix — set the env var, then run:
$env:ARXMCP_NOTEBOOK = "demo"; python -m server.main
```

The server binds `127.0.0.1:7733`; the operator console is at
<http://127.0.0.1:7733/ui/>. Then continue with **§2 Register** below — on
Windows `~/.claude.json` is `%USERPROFILE%\.claude.json`, and the
`arxmcp-shim` console script installs to `.venv\Scripts\arxmcp-shim.exe`
(activate the venv, or use that absolute path, so Claude Code can spawn it).

Run tests / lint without `make` (the suite is the authority — there is no CI):

```powershell
python -m ruff check .
python -m pytest -q
```

> **Windows caveats (read before relying on it):**
> - **No `make`.** Every `make <target>` in this repo is bash-only. Install GNU
>   Make + run under Git Bash, or use WSL2, if you want the `make` verbs.
> - **POSIX-only security features degrade.** The textbook-PDF sandbox's memory
>   cap (`RLIMIT_AS`) and process-group kill (`os.killpg`) are no-ops on Windows,
>   and the symlink-confinement checks + Lean REPL spawn carry Windows guards.
>   Treat **untrusted textbook-PDF ingest as less hardened on Windows** — prefer
>   Linux or the Docker image for that path.
> - **~60 tests fail on Windows for platform reasons** (symlinks, `killpg`,
>   colons-in-filenames, POSIX-shell + path-containment tests). They pass on
>   macOS / Linux; the failures are not regressions. Filter with
>   `python -m pytest -q -k "not symlink"` etc., or run the suite under WSL2.
> - **System ingest deps** (`aria2c`, `latexmlc`, MinerU) document `brew` /
>   `apt` install lines below; on Windows use `scoop` / `choco` or WSL2.

### Optional ingest system deps

The runtime server (`arxmcp-server`) has no system dependencies
beyond Python ≥3.11. The optional **bulk ingest pipeline**
(`make ingest`) and the **LaTeXML drift detector**
(`ops/cron/latexml-drift-check.sh`) need two system binaries:

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

The textbook-ingest pipeline parses operator-supplied PDFs via
**MinerU 3.x** running in a sandboxed subprocess. MinerU pulls a large
PyTorch + ONNX + transformers tree — install it into a **separate venv**
rather than the project venv:

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

Two environment variables control the sandbox driver
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

Once MinerU is installed, the end-to-end textbook parse workflow
(upload → background parse → `parse-status` polling) is covered in the
[usage guide](usage.md#textbook-pdf-ingest).

> **Platform note (macOS):** the sandbox's 4 GB virtual-memory cap
> (`RLIMIT_AS`) is **not enforceable on macOS** — the Darwin kernel refuses
> to lower it, so the 30-min wall timeout is the only memory backstop there
> (Linux gets the full cap). Full rationale:
> [`.claude/docs/security-pdf-sandbox.md`](../.claude/docs/security-pdf-sandbox.md).

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

> **MCP endpoint path.** The registration above is correct as-is — the shim
> appends `/mcp/` (with the trailing slash) to the `--server` base URL.
> Custom HTTP clients should POST to `http://127.0.0.1:7733/mcp/` directly:
> FastAPI 307-redirects bare `/mcp` → `/mcp/`, and clients commonly drop the
> POST body on that redirect. See *Troubleshooting* for the symptom.

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

### Run via Docker Compose (server-only v0)

`infra/docker-compose.yml` builds `docker/Dockerfile.server` and runs the MCP
server as a non-root container (UID 1000), published on **loopback only**
(`127.0.0.1:7733`). The ingest service + a Litestream sidecar are a deliberate
v1 increment (see *Out of scope*); the stdio shim still runs on the host, not
in Docker.

> **Corpus prerequisite (required).** The server warms its corpus EAGERLY at
> startup, so it needs a populated corpus BEFORE `docker compose up` — either an
> ingested shared corpus at `var/arxmcp/index/lancedb` (seed-fetch + ingest;
> see *Optional ingest system deps* above and the line about running the ingest
> pipeline in *Troubleshooting*) OR a notebook corpus served via
> `ARXMCP_NOTEBOOK=<slug>` (set it in the compose `environment:` block). With an
> EMPTY `var/arxmcp` (just after `make bootstrap`), `open_chunks_table` raises
> `FileNotFoundError` and the container **EXITS at startup** (it does NOT serve a
> 503) — `docker compose up --wait` then reports the service unhealthy and exits
> non-zero. Populate the corpus first.

```sh
# 1. Create the gitignored var/arxmcp/ tree the container bind-mounts.
#    (Then populate a corpus — see the Corpus prerequisite note above; an
#    empty var/arxmcp makes the container exit at startup.)
make bootstrap

# 2. One-time ownership pre-step — LINUX ONLY:
#    On native Linux Docker, bind-mount ownership is literal, so the in-image
#    UID 1000 must own (or be able to write) var/arxmcp:
chown -R 1000:1000 var/arxmcp        # native Linux Docker ONLY
#    On macOS Docker Desktop this is NOT needed — its VirtioFS file-sharing
#    maps the bind mount to any container UID transparently (validated:
#    .claude/notes/spikes/notebook-ops-hardening-spike-1.md). Skip the chown.

# 3. Bring the server up and block until it is healthy.
docker compose -f infra/docker-compose.yml up --wait

# 4. Verify readiness (200 once BGE-M3 + LanceDB are warm; the first run
#    downloads BGE-M3 ~2.3 GB, so the healthcheck has a 5-minute grace).
curl -fsS http://127.0.0.1:7733/readyz
```

Notes:

- **Loopback only.** The host port is pinned to `127.0.0.1`; inside the
  container the server binds `0.0.0.0` (required for Docker's bridge network),
  which is why the compose env sets `ARXMCP_UNSAFE_NETWORK_BIND=1`. The LAN can
  never reach the server. A WARN log about the non-loopback bind is expected.
- **Restart policy.** The default is `restart: "no"` — you bring the server up
  explicitly. For an always-on server (auto-restart on reboot), change the
  `server` service to `restart: "unless-stopped"` (note it reloads BGE-M3
  ~2.3 GB into RAM on every boot).
- **`ARXMCP_CONTACT_EMAIL`** is NOT needed by the server and is intentionally
  absent from the compose env; the v1 ingest service will require it.
- **Resource limits.** `mem_limit: 8g` / `cpus: 4.0` are conservative starting
  points (BGE-M3 + the reranker + LanceDB); tune in `infra/docker-compose.yml`.
- **Bind-mount scope.** The compose mounts the ENTIRE repo-root `var/arxmcp`
  read-write (matching the image `WORKDIR /app` + `VOLUME /app/var/arxmcp`).
  That includes notebook metadata (`cache/notebooks.db`), uploaded PDFs, every
  per-notebook corpus, and the restic-relevant ops tree — not just the shared
  index the server-only v0 reads. This is acceptable under the loopback-only
  single-workstation threat model (you own the host + data), but it is broader
  than "server only"; a future v1 ingest increment may narrow the mount to the
  subset each service needs.

### Serving a notebook corpus

By default the server reads the shared corpus at
`var/arxmcp/index/lancedb`. To serve a notebook you ingested with
`tools/notebook_ingest.py`, set `ARXMCP_NOTEBOOK` to its slug:

```sh
ARXMCP_NOTEBOOK=bridgeland-stability make up
```

The server then serves that notebook's corpus
(`var/arxmcp/notebooks/bridgeland-stability/lancedb`). This is the
**process-level default** (fork C): the whole server is bound to that one
notebook. Setting both `ARXMCP_NOTEBOOK` and `ARXMCP_LANCEDB_PATH` is rejected
(pick one). If the notebook has not been ingested, the server refuses to
start with a message naming the ingest command.

#### Per-call notebook selection (`filters.notebook`)

A single running server can also serve **many** notebooks across calls without
a relaunch: pass `filters={"notebook": "<slug>"}` on a `search_papers` call and
that one query is routed to the named notebook's corpus.

```jsonc
// search_papers arguments
{ "query": "Bridgeland's original definition", "filters": { "notebook": "bridgeland-stability" } }
```

Notes:

- **`notebook` is a routing key, not a result filter.** It selects which corpus
  to search; it composes with `filters.paper_id` / `filters.source_kind` (those
  still filter *within* the routed notebook) and does not appear in
  `filters_applied` or `filter_warnings`.
- **Per-call wins over the process default.** If the server was launched with
  `ARXMCP_NOTEBOOK=A` and a call passes `filters.notebook=B`, that call serves
  B (an explicit per-call selection is more specific than a launch default).
- **The result envelope's `corpus_version` reflects the routed notebook's**
  version, not the launch-default corpus's.
- A call with **no** `filters.notebook` is unchanged — it serves the launch
  substrate (the `ARXMCP_NOTEBOOK` notebook, or the shared corpus).
- An invalid slug (path traversal, bad characters) or an un-ingested notebook
  returns a clean tool error, not a 500.

Because the server must still boot against *some* corpus, launch it with either
`ARXMCP_NOTEBOOK=<a-notebook>` or an ingested shared corpus; per-call
`filters.notebook` then reaches any *other* ingested notebook from that same
process.

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

Should print a JSON line containing `"tools": [...]` — the eight canonical
tools (see [the API reference](api.md)). If you see
`FATAL: cannot reach arxmcp-server`, the server is not running on
the configured port; double-check `make up` is alive.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `arxmcp-shim: command not found` | the editable install didn't run, or the venv isn't activated | activate the venv and re-run `make bootstrap` (§1) |
| Shim exits with `FATAL: arxmcp-server returned 503` | Server is mid-warmup or LanceDB corpus is missing | wait for `/readyz` 200, or run the ingest pipeline first |
| Shim hangs on first request | `json_response=True` not set on server, so it returns SSE the shim can't parse | the v1 server sets it by default; this should not happen on a fresh install |
| `Mcp-Session-Id` errors | spec violation upstream | report; shim captures session-id from response headers per MCP 2025-06-18 |
| Custom HTTP client POSTs to `http://127.0.0.1:7733/mcp` and gets an empty body or 307 | FastAPI/Starlette 307-redirects bare `/mcp` to `/mcp/`; most HTTP clients drop the POST body on the redirect | POST to `http://127.0.0.1:7733/mcp/` (with the trailing slash). The `arxmcp-shim` does this transparently; only direct curl / custom clients are affected. |
| Server FATALs at boot with `unknown ARXMCP_* environment variables` mentioning `ARXMCP_CONTACT_EMAIL` | `ARXMCP_CONTACT_EMAIL` is an ingest-tool var, not a server config knob; the server's strict-typo check rejects it | `unset ARXMCP_CONTACT_EMAIL` before `make up`. Only export it in shells where you're running an arXiv CLI fetch tool (`tools/fetch_seed.py`, `tools/notebook_fetch.py`, `tools/recover_preambles.py`, `ingest/inspire_ingest.py`, `ingest/graph_ingest.py`). |

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
