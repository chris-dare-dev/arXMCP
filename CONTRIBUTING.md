# Contributing to arXMCP

Thanks for your interest. arXMCP is a single-maintainer research project (see
[OWNERS.md](OWNERS.md)) — most work is done by the maintainer with Claude
agents. External contributions are welcome;
this guide explains how the repo works so a change has the best chance of
landing.

## Before you start

- **Open an issue first** for anything non-trivial; a quick discussion avoids
  work that collides with the maintainer's plans.
- **Read [CREDO.md](CREDO.md)** — one page on what this repository holds and
  what it refuses. It overrides every other file here.
- **Read [CLAUDE.md](CLAUDE.md)** — working conventions, hard constraints
  and known gotchas.
- For security issues, **do not** open a public issue — follow
  [SECURITY.md](SECURITY.md).

## How changes are made

A change stays under ~400 authored lines and one concern; larger work is
split, or starts with a one-paragraph design in its issue (CREDO.md §5).

This is a single-workstation project: the maintainer's local test suite is
the authority (there is no blocking CI). `make test` must be green before
anything lands.

## Development setup

```sh
python3 -m venv .venv && source .venv/bin/activate
make bootstrap          # editable install + var/ tree
make test               # ruff + pytest — must pass
```

Python ≥ 3.11. Optional system dependencies (LaTeXML, MinerU, Lean, restic)
are listed in the [archived install guide](https://github.com/chris-dare-dev/arXMCP/blob/433ba41ba8710be74d6f99c627dce7d3b5383fca/docs/install.md)
until it moves to the wiki.

## Coding conventions

These are enforced by tests and review — see [CLAUDE.md](CLAUDE.md):

- **`assert` is banned for invariants** (`python -O` strips them). Use
  `if … raise RuntimeError(…)`.
- **Pure-ASGI middleware only** — `BaseHTTPMiddleware` is banned.
- **No `anthropic` SDK at runtime** — the server is a tool provider.
- **No-fork policy** — use ideas from other projects, never their code.
- **`server/` never references `claude-opus`** — model policy is Haiku/Sonnet.
- **Ruff clean** (`ruff check .`), line length 100.

## Documentation placement

Markdown in the tree is limited to the allow-list in
[CREDO.md](CREDO.md), and the `credo` CI job fails a pull request that adds
or edits any other:

- **Repo root:** only `README.md`, `AGENTS.md`, `CLAUDE.md`, `CREDO.md`,
  `CHANGES.md`, `SECURITY.md`, `OWNERS.md`, `LICENSE`, `CONTRIBUTING.md`,
  `CONTRIBUTORS.md`.
- **Elsewhere:** a navigational `README.md` in a product or test directory,
  `.github/pull_request_template.md` and `src/arxmcp/server/frontend/static/VENDORED.md`.
- **Wiki:** guides, runbooks, API reference, architecture, design notes and
  rules agents follow.
- **Issue or pull request:** plans, research, critiques and handoffs.

## Commit & PR conventions

- **Conventional commits**, subject ≤ 50 chars after the type prefix. Types:
  `feat`, `fix`, `test`, `chore`, `ci`, `docs`. Scopes match subsystems
  (`server`, `ingest`, `shim`, `infra`, `apps`, `tests`, `repo`, …).
- **GPG signing is required** (`commit.gpgsign=true`). Never `--no-gpg-sign`.
- **Pre-commit hooks are honored.** Never `--no-verify`; fix the underlying
  issue and make a new commit.
- **No co-author or attribution trailers.** Do not add `Co-Authored-By:`,
  `Generated-with:` or any equivalent naming an AI agent or tool. This
  replaces an earlier rule that required one; it was removed at the
  maintainer's direction on 2026-08-24. Commits before that date carry the
  trailer and are not the convention.

- If you open a PR, describe what changed and why, link the issue, and
  confirm `make test` is green locally.

## Adding to the MCP tool surface

The `tools/list` response is **byte-stable** for prompt-cache discipline. If
you add or change a tool, re-pin `EXPECTED_TOOL_SCHEMA_SHA256`
(`pytest --update-tool-schema-hash`) and follow the checklist in
[CLAUDE.md](CLAUDE.md). A tool-surface change is at least a MINOR release.
