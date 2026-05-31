# Support

arXMCP is a single-maintainer research project. There is no SLA, but issues
and questions are welcome and answered best-effort.

## Where to go

| You want to… | Go to |
|---|---|
| Set it up | [Install guide](install.md) |
| Use a feature | [Usage guide](usage.md) · [MCP tool API](api.md) |
| Recover from a failure | [Operations runbooks](ops/README.md) · [`failure-modes.md`](ops/failure-modes.md) |
| Report a **security** issue | [SECURITY.md](../SECURITY.md) — **do not** open a public issue |
| Report a bug / ask a question | [GitHub issues](https://github.com/chris-dare-dev/arXMCP/issues) |
| Propose a change | [Contributing guide](../CONTRIBUTING.md) |

## First-stop troubleshooting

| Symptom | Likely cause & fix |
|---|---|
| `arxmcp-shim: command not found` | Install didn't put it on `$PATH` — re-run the install from the [install guide](install.md). |
| Shim returns `503` | Server is mid-warmup or has no corpus. Wait for `/readyz` to return 200, or ingest a corpus first. |
| Server FATALs naming `ARXMCP_CONTACT_EMAIL` | That var is for the arXiv **fetch tools**, not the server. `unset ARXMCP_CONTACT_EMAIL` before `make up`. |
| Container exits at startup | Empty `var/arxmcp` — the server warms a corpus eagerly. Populate a corpus or set `ARXMCP_NOTEBOOK=<slug>`. |
| Custom client POSTs to `/mcp` and gets an empty body / 307 | POST to `/mcp/` **with the trailing slash**. The shim does this for you. |
| `make eval` reports `skipped` | The fixture or corpus is missing — see [Evaluation](evaluation.md). |

The [install guide's troubleshooting table](install.md#troubleshooting) has
the full matrix. Operational failures (crashes, drift, restore) are covered
by the [operations runbooks](ops/README.md).

## Filing a good issue

Include: what you ran, what you expected, what happened, the relevant log
lines, and your platform (OS, Python version). For server problems, the
output of `make status` and the last lines of the server log are gold.

## Reporting a vulnerability

Security issues go through [SECURITY.md](../SECURITY.md) — contact the owner
directly and **do not** file a public issue for an unfixed vulnerability.
