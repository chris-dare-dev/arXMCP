# Usage guide

Task-oriented walkthroughs for everyday work with arXMCP. Assumes you have
already [installed](install.md) the package and can run `make up`.

- [Notebooks: the unit of corpus](#notebooks-the-unit-of-corpus)
- [Create and populate a notebook](#create-and-populate-a-notebook)
- [Ingest a notebook](#ingest-a-notebook)
- [Serve a notebook to agents](#serve-a-notebook-to-agents)
- [Serving many notebooks](#serving-many-notebooks)
- [The operator console](#the-operator-console)
- [Textbook (PDF) ingest](#textbook-pdf-ingest)
- [Querying from an agent](#querying-from-an-agent)
- [Proof-chain workflow](#proof-chain-workflow)
- [Lean verification](#lean-verification)

## Notebooks: the unit of corpus

A **notebook** is a named, independently-ingested slice of corpus — a set of
arXiv papers (or uploaded textbooks) you want an agent pipeline to work
against. Each notebook owns its own LanceDB index under
`var/arxmcp/notebooks/<slug>/`. A server instance serves one notebook as its
process default and can route individual calls to others.

The arXiv polite-pool User-Agent requires a contact email. Persist it once
at notebook init (stored in `operator_settings`) so the CLI fetch tools find
it without an env var:

```sh
make init NOTEBOOK=bridgeland-stability EMAIL=you@example.com
```

> `ARXMCP_CONTACT_EMAIL` is consumed only by the arXiv **fetch tools**
> (`tools/fetch_seed.py`, `tools/notebook_fetch.py`,
> `tools/recover_preambles.py`, `ingest/inspire_ingest.py`,
> `ingest/graph_ingest.py`). The **server rejects it** — keep it unset for
> `make up`. `make init EMAIL=...` avoids the env var entirely.

## Create and populate a notebook

```sh
make init NOTEBOOK=bridgeland-stability          # scaffold + register
make add  NOTEBOOK=bridgeland-stability PAPER=1309.4265
make add  NOTEBOOK=bridgeland-stability PAPER=1607.01262
make notebook-list                               # list registered notebooks
```

`make add` POSTs to the running server if `/healthz` is up; otherwise it
appends to `var/arxmcp/notebooks/<slug>/papers.txt`. It never silently
falls back on a REST error (that would create orphan rows).

## Ingest a notebook

Ingestion fetches each paper's source (ar5iv → LaTeXML fallback), chunks it
theorem-aware, embeds it with BGE-M3, and writes the LanceDB index. For the
shared seed corpus:

```sh
make ingest ARGS="--paper-ids-file=tools/seed-papers.txt --limit=5"   # smoke test
```

For per-notebook ingest and the full multi-day corpus run, follow the
[bulk-ingest runbook](ops/bulk-ingest-runbook.md). After a chunker or
embedder bump, re-embed with `make re-embed-all` (see the
[re-embed runbook](ops/re-embed-runbook.md)).

## Serve a notebook to agents

```sh
ARXMCP_NOTEBOOK=bridgeland-stability make up
```

The server serves that notebook's corpus. Setting both `ARXMCP_NOTEBOOK` and
`ARXMCP_LANCEDB_PATH` is rejected — pick one. If the notebook isn't ingested,
the server refuses to start and names the ingest command.

Fresh clone with no corpus yet? Use **wizard mode** — the server boots
empty, MCP tools return a `no_notebook_selected` envelope, and the process
promotes itself in-process once the first ingest completes (no restart):

```sh
make up-wizard
```

## Serving many notebooks

A single running server can serve **many** notebooks across calls. Pass a
routing key on the call:

```jsonc
// search_papers arguments
{ "query": "Bridgeland's original definition",
  "filters": { "notebook": "bridgeland-stability" } }
```

- `notebook` is a **routing key, not a result filter** — it selects the
  corpus and composes with `filters.paper_id` / `filters.source_kind`.
- A per-call `filters.notebook` wins over the launch-default `ARXMCP_NOTEBOOK`.
- `corpus_version` in the envelope reflects the routed notebook.

The server must still boot against *some* corpus; per-call routing then
reaches any other ingested notebook. See the
[notebook-modes runbook](ops/notebook-modes.md) for per-daemon vs per-call
topology trade-offs.

## The operator console

A loopback-only, server-rendered Jinja2 + htmx console ships with the server
(no SPA, no Node build chain):

```
http://127.0.0.1:7733/ui/
```

From it you can list / create / rename / delete notebooks, add papers by
URL, drag-drop ar5iv HTML or textbook PDF uploads, trigger an ingest and
watch live status, and preview papers. It is **not yet security-audited**
(tracked at `chris-dare-dev/arXMCP#9`) — keep it loopback-only.

## Textbook (PDF) ingest

Create a `textbook`-kind notebook, upload a PDF, and a background pipeline
runs MinerU + LaTeXML to produce HTML5 + MathML. The upload returns
immediately; poll progress:

```
GET /ui/api/notebooks/<slug>/parse-status
```

`parse_status` moves `pending → running → complete | failed` (`skipped` for
arXiv notebooks). MinerU installs into a **separate venv** — see the
[install guide](install.md#optional-textbook-ingest-dep--mineru). Parses are
serialized (`asyncio.Semaphore(1)`) to avoid GPU/MLX memory pressure.

### Headless (CLI) PDF ingest

The browser upload is not required — a PDF already staged under
`var/arxmcp/notebooks/<slug>/pdfs/<flat>.pdf` can be parsed and ingested from
the shell (this is also the path for an arXiv paper that has no usable ar5iv
HTML, e.g. a PDF-only overview). First persist the mineru binary once
(`make init NOTEBOOK=<slug> MINERU_BIN=<abs path>`, see the
[install guide](install.md#optional-textbook-ingest-dep--mineru)), then:

```sh
# Stage 1 — MinerU + LaTeXML render → parsed/<flat>/index.html (idempotent;
# skips when index.html exists unless --force).
uv run python tools/notebook_pdf_parse.py <slug> --paper-id <id>

# Stage 2 — chunk + embed + write the per-notebook LanceDB.
uv run python tools/notebook_textbook_ingest.py <slug> --paper-id <id>
```

The chunks land in the notebook's own LanceDB with `source_kind="textbook"`;
query them with `ARXMCP_NOTEBOOK=<slug>` (or `filters.notebook=<slug>`).

## Querying from an agent

Once registered in `~/.claude.json`, Claude Code sub-agents call the tools
directly. A typical lookup:

1. `search_papers` with a natural-language query → ranked chunk rows.
2. `get_chunk` on the most relevant `chunk_id`(s) → full bodies.
3. `get_definitions` / `find_lemma_by_name` to resolve notation and named
   results.

See the [MCP tool API](api.md) for every argument and return field.

## Proof-chain workflow

To pull a theorem's supporting context in two MCP rounds: call
`cite_neighbors` to find the dependency/citation neighborhood, then issue a
bulk parallel `get_chunk` over the returned `chunk_id`s. The full pattern,
including depth and direction guidance, is in
[`.claude/docs/proof-chain-workflow.md`](../.claude/docs/proof-chain-workflow.md).

## Lean verification

If a managed Lean 4 kernel is available, set `ARXMCP_ENABLE_LEAN=1` and call
`lean_verify` to check an autoformalizer's candidate snippet. Use
`mode='syntax_only'` for a cheap pre-verify and `mode='full'` for kernel
verification. When Lean is not enabled the tool returns
`lean_status='disabled'` — it never fails the request. See the
[API reference](api.md#lean_verify).
