# Credo

What this repository holds and what it refuses. Where another file here
disagrees, this one wins.

**MUST**: a change that breaks it does not merge. **SHOULD**: depart from it
only with the reason stated in the pull request.

## 1. The tree holds what a person wrote and would read

- You MUST NOT commit anything a command can regenerate: build output,
  rendered or captured data, run state, logs, measurements, screenshots,
  per-declaration or per-file listings.
- You MUST NOT commit the record of how a change was made: plans, research
  briefs, critiques, reviews, handoffs, transcripts, agent memory. That record
  is the issue, the pull request and the wiki.
- Prose in the tree is limited to the files listed under "In this repository".
  Guides, runbooks, references, design notes and rules for agents go in the
  wiki.
- Agent instruction files hold rules, not history. They SHOULD stay under 200
  lines and point here instead of repeating this file.

## 2. A change costs what it touches

- A change that touches neither the product nor a check that judges it MUST
  NOT start a product build.
- You MUST NOT open a pull request that only adds or edits prose: prose that
  changes on its own belongs in the wiki. One that only deletes prose is
  allowed.

## 3. Every check earns its place

- A check MUST state, where it is defined, the one invariant it guards.
- A check that is kept MUST run in CI on every change it can judge. One that
  runs only on a workstation is not a check.
- You MUST NOT add a check whose input is another check's output: evidence,
  receipts, attestations that a run happened.
- Scripts that support the build MUST NOT grow fixtures, golden files or a
  test suite of their own. A script that needs those is a product and lives in
  its own repository.
- An exceptions list (baseline, allowlist, nolint) only shrinks.

## 4. Names and comments say what the thing is

- Identifiers, file names and comments MUST NOT carry issue, pull-request,
  milestone or decision-record numbers, dates, or the names of agents and
  tools. Provenance goes in the commit message.
- A comment explains why the code is the way it is. It does not narrate what
  was tried, what it replaced, or which review asked for it.
- Names SHOULD stay under 60 characters. A longer one means the statement
  wants splitting or an intermediate definition wants a name.

## 5. Changes are small enough to read

- A change SHOULD stay under 400 authored lines and one concern. Larger work
  is split, or starts with a one-paragraph design in its issue.
- A person reads every line before merge. "I do not understand this yet"
  blocks the merge.

## 6. Health is a trend, not a volume

- Progress is not measured in commits, pull requests or lines added.
- The measures are: product share of lines, share of changes that touch the
  product, median change size, size of the exceptions lists, open issues.
  They are computed on demand and never committed.

## In this repository

| | |
|---|---|
| Product | `server/`, `ingest/`, `apps/`, `shim/`, `infra/`, `docker/`, `ops/`, `tools/`, `pyproject.toml`, `uv.lock`, `Makefile` |
| Tests | `tests/`, for product code only |
| Prose allowed in the tree | the root files `README.md`, `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `CREDO.md`, `CHANGES.md`, `SECURITY.md`, `OWNERS.md`, `CONTRIBUTORS.md`, `LICENSE`; a `README.md` in a product or test directory; `.github/pull_request_template.md`; `server/frontend/static/VENDORED.md`. Nothing else, and nothing under `docs/`, `.claude/` or `plans/` |
| Wiki | install, usage and API guides, architecture, operator runbooks, design notes and decision records, rules agents follow, roadmap, spike write-ups |
| Issue or pull request | plans, research, critiques, handoffs |
| Never committed | pipeline output (state, briefs, critiques, summaries), agent memory, chaos-run evidence, measurement dumps |

Rules for this codebase:

- A test asserts behaviour a caller of the product can observe. You MUST NOT
  test the wording of documentation, agent instructions or stylesheets.
- A test file SHOULD be no longer than the module it tests. When it is, the
  cases are redundant or the module wants splitting.
- `make test` runs in CI on every change to product or test code.
- The `credo` workflow fails any change that adds or edits Markdown outside
  the allow-list above. Its exceptions list, `LEGACY` in
  `.github/credo_prose.py`, only shrinks.
- Milestone identifiers do not appear in `server/`, `ingest/`, `apps/` or
  `tests/`: not in names, not in comments, not in docstrings.

## Not yet met

The repository does not meet these yet. A line is deleted when it becomes
true. Until then the older rule in `CLAUDE.md` applies to what that line
names and to nothing else.

- Markdown under `docs/`, `.claude/` (agent definitions, commands, skills and
  references included) and `plans/` is still in the tree (§1). It may be
  deleted, never edited; `LEGACY` names what is left.
- `CLAUDE.md` is over 200 lines and carries dated history (§1).
- CI runs one test file, not `make test` (§3).
- `tests/` includes tests of documentation wording and stylesheets.
- Milestone identifiers remain in product and test code (§4).
