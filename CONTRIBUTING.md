# Contributing to arXMCP

Thanks for your interest. arXMCP is a single-maintainer research project (see
[OWNERS.md](OWNERS.md)) — most work is done by the maintainer with Claude
agents through a structured pipeline. External contributions are welcome;
this guide explains how the repo works so a change has the best chance of
landing.

## Before you start

- **Open an issue first** for anything non-trivial. The maintainer steers a
  roadmap ([`.claude/roadmap/README.md`](.claude/roadmap/README.md)); a quick
  discussion avoids work that collides with it.
- **Read [CLAUDE.md](CLAUDE.md)** — it is the working constitution
  (conventions, gotchas, directory layout). It overrides convention when the
  two differ.
- For security issues, **do not** open a public issue — follow
  [SECURITY.md](SECURITY.md).

## How changes are made

Non-trivial changes (more than ~3 files or new tests) run through the
four-phase **milestone pipeline**: **Research → Implement → Critique →
Rectify**. The pipeline and its bespoke agents live under
[`.claude/`](.claude/commands/milestone-pipeline.md). Trivial edits
(one-liners, typo/formatting fixes) can skip it.

This is a single-workstation project: the maintainer's local test suite is
the authority (there is no blocking CI). `make test` must be green before
anything lands.

## Development setup

```sh
python3 -m venv .venv && source .venv/bin/activate
make bootstrap          # editable install + var/ tree
make test               # ruff + pytest — must pass
```

Python ≥ 3.11. See the [install guide](docs/install.md) for optional system
dependencies (LaTeXML, MinerU, etc.).

## Coding conventions

These are enforced by tests and review — see [CLAUDE.md §4.7](CLAUDE.md):

- **`assert` is banned for invariants** (`python -O` strips them). Use
  `if … raise RuntimeError(…)`.
- **Pure-ASGI middleware only** — `BaseHTTPMiddleware` is banned.
- **No `anthropic` SDK at runtime** — the server is a tool provider.
- **No-fork policy** — use ideas from other projects, never their code.
- **`server/` never references `claude-opus`** — model policy is Haiku/Sonnet.
- **Ruff clean** (`ruff check .`), line length 100.

## Documentation placement

The repo enforces a strict doc-placement rule (see [CLAUDE.md §1](CLAUDE.md)):

- **Repo root:** only `README.md`, `CLAUDE.md`, `CHANGES.md`, `SECURITY.md`,
  `OWNERS.md`, `LICENSE`, `CONTRIBUTING.md`, `CONTRIBUTORS.md`.
- **`docs/`:** user/operator-facing documentation linked from the README.
- **`.claude/`:** all agent-internal docs (design notes, roadmap,
  milestones, engineering references).
- **Other subdirs:** only a navigational `README.md` / `CLAUDE.md`.

## Commit & PR conventions

- **Conventional commits**, subject ≤ 50 chars after the type prefix. Types:
  `feat`, `rect`, `chore`, `docs`. Scopes match subsystems (`server`,
  `ingest`, `shim`, `infra`, `tests`, `notes`, `repo`, …).
- **GPG signing is required** (`commit.gpgsign=true`). Never `--no-gpg-sign`.
- **Pre-commit hooks are honored.** Never `--no-verify`; fix the underlying
  issue and make a new commit.
- **Co-author trailer** on every agent-assisted commit:

  ```
  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  ```

- If you open a PR, describe what changed and why, link the issue, and
  confirm `make test` is green locally.

## Adding to the MCP tool surface

The `tools/list` response is **byte-stable** for prompt-cache discipline. If
you add or change a tool, re-pin `EXPECTED_TOOL_SCHEMA_SHA256`
(`pytest --update-tool-schema-hash`) and follow the full checklist in
[CLAUDE.md §9](CLAUDE.md). A tool-surface change is at least a MINOR release.

## Recognition

Contributors are listed in [CONTRIBUTORS.md](CONTRIBUTORS.md). Open a PR
adding yourself (or ask, and the maintainer will).
