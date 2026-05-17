# Milestone-pipeline — shared agent conventions

This file is shared context for every agent in the milestone-pipeline:

- `milestone-researcher` (Phase 1)
- `milestone-implementer` (Phase 2)
- `milestone-adversary` (Phase 3 — always fires)
- `milestone-infra-safety` (Phase 3 — conditional)
- `milestone-oss-scout` (Phase 3 — opt-in)

Each agent's own `.md` file embeds its agent-specific protocol (research steps,
implementation rules, critique axes, severity calibration, finding output format).
**The conventions below are NOT duplicated in those files** — when an agent file
references "see agent-conventions.md §<n>", read this file for the detail.

This file is the single source of truth for: sub-agent isolation, memory protocol,
return-contract shape, banned-pattern checklist, commit conventions, test discipline,
doc placement, and the anti-pattern guards common to every phase.

---

## 1. Sub-agent isolation (platform constraint)

**You CANNOT spawn sub-agents.** This is a platform-level constraint on Claude Code —
not just a convention. Sub-agents do not have access to the `Agent` tool. Attempting
nested delegation will fail.

If your task requires nested delegation, **return early** with:

```json
{
  "path": "<your-output-path>",
  "status": "blocked",
  "summary": "Line 1: nested delegation required for <task>\nLine 2: missing capability: <name>\nLine 3: orchestrator should dispatch <next agent> with <inputs>"
}
```

The main thread will route the follow-on work.

---

## 2. Memory protocol (agentic learning loop)

Each agent has `memory: project` in its YAML frontmatter. This enables persistent
project-scope memory at:

```
.claude/agent-memory/<your-agent-name>/MEMORY.md
```

### Read at start — automatic

The Claude Code harness automatically injects the **first 200 lines (or 25 KB,
whichever comes first)** of `MEMORY.md` into your system prompt at invocation. You
do **NOT** need to `Read` it manually — its content is already in your context.

If you do want to confirm the file exists or inspect content beyond the auto-injection
window, you may `Read` it explicitly, but this is rarely necessary.

### Append after success

At the end of a successful run, if you learned a **genuinely new pattern** that
would help future runs of THIS agent on THIS codebase, append a dated entry to
`MEMORY.md`. Create the file if it does not yet exist.

```bash
# Pseudo — adapt to your tool surface:
mkdir -p .claude/agent-memory/<your-agent-name>
cat >> .claude/agent-memory/<your-agent-name>/MEMORY.md <<'EOF'

## 2026-05-17 — E13_S01 — chunk-id-canonical-guard
The canonical guard for chunk_id validation in this codebase is
`is_valid_chunk_id` in `ingest/identifiers.py`. Prefer suggesting it over
hand-rolled regex in any security/path-traversal finding.
EOF
```

**Format:**
```markdown
## <ISO-8601 date> — <milestone ID> — <short pattern name>
<1–3 lines. Terse. Actionable.>
```

### Discipline — avoid log spam

Append ONLY when:

- The pattern is **genuinely new** (not already covered in this MEMORY.md or in the
  design constitution `.claude/notes/`)
- It is **action-changing** (would have changed how you handled THIS milestone if you
  had known it at the start)
- It is **stable** (not a one-off observation specific to this milestone)

Spammy entries silently degrade the agent's effectiveness over time — the auto-inject
window fills up with low-value bullets and the high-value patterns scroll off.

### Pruning

If MEMORY.md grows past ~150 lines, the agent (or the orchestrator) should consolidate:
merge duplicate patterns, drop stale entries, keep the file lean. Pruning is a separate
task — not part of a normal milestone run.

---

## 3. Return contract — universal shape

Every milestone-pipeline agent returns **exactly one JSON object** with these three
fields and nothing else:

```json
{
  "path": "<absolute path to the agent's output artifact>",
  "status": "ok|partial|blocked",
  "summary": "Line 1: …\nLine 2: …\nLine 3: …"
}
```

**Status values:**

- `"ok"` — primary deliverable produced, no caveats
- `"partial"` — produced but ≥1 sub-task incomplete (explain in summary)
- `"blocked"` — could not produce useful output (explain reason in summary)

**Summary discipline:**

- Exactly 3 lines, separated by literal `\n` in the JSON value
- Each line ≤ 80 characters
- Line 1 = headline (what you did / verdict / recommendation)
- Line 2 = top risk / top finding / key constraint
- Line 3 = counts (findings, criteria, open questions, …)

**Output channel discipline:**

- Do **NOT** echo the artifact file's content in your response
- Do **NOT** include any text outside the JSON object
- Do **NOT** wrap the JSON in markdown code fences
- The orchestrator parses your response with a strict JSON reader

Full artifacts live on disk. The orchestrator reads them on demand. This keeps the
orchestrator's context window flat across multiple sub-agent dispatches per phase.

---

## 4. Banned patterns (project-wide — flagged in critique)

These patterns are banned project-wide per `CLAUDE.md §8`. The adversary critic
checks all of them. Every agent should know them — the researcher flags them in
recommendations, the implementer avoids them, the critics flag any instance.

| Pattern | Severity if introduced | Why banned |
|---|---|---|
| `assert` for invariants | HIGH | Python `-O` strips them; use `if … raise RuntimeError(…)` |
| `BaseHTTPMiddleware` | CRITICAL | Project-banned (E06_S01 F1); silently no-ops SSE response interception |
| `import anthropic` in `server/`, `ingest/`, `shim/` | HIGH | Server is a tool provider; LLM lives in the caller |
| `"claude-opus"` string in `server/` source | HIGH | Model selection lives in the orchestrator, never in server source |
| `git push`, `gh issue create`, `gh pr create` from agent code | CRITICAL | External-write boundary violation; Phase 4 main-thread only |
| `helm install`, `kubectl apply`, `terraform apply` | CRITICAL | Same external-write boundary |
| New `.md` outside `.claude/` | LOW–MEDIUM | Doc placement rule (see §6) — except navigational `README.md` / `CLAUDE.md` for a subdir |
| Forked code from existing `arxiv-mcp` repos | CRITICAL | No-fork policy; ideas are fine, code is not |
| Path using `var/arxmcp/index/kuzudb/` instead of `kuzu/` | MEDIUM | Documented drift; canonical is `kuzu/` |
| `kuzu==` version differs from CLAUDE.md §8 row 2 without same-commit CLAUDE.md update | HIGH | Pin lives in `CLAUDE.md §8`; bump them together or flag |
| `--no-verify`, `--no-gpg-sign` on `git commit` | HIGH | Pre-commit hooks and GPG signing are required |
| Listening on `0.0.0.0` instead of `127.0.0.1` in server code | HIGH | Rejected by `config.py::reject_non_loopback`; security regression |
| `latest` Docker image tags | HIGH | Prevents reproducible builds; pin to version or digest |
| Removing `KMP_DUPLICATE_LIB_OK=TRUE` from `tests/conftest.py` | HIGH | macOS pytest segfault guard with faiss-cpu + PyTorch |
| `make ingest` stub replaced with active ingest command | HIGH | Stub is intentional pending E11; do not unfold |

---

## 5. Commit conventions (for agents that commit)

Only the **implementer** commits during normal operation. Other agents are read-only.
If any non-implementer agent needs to commit, route the request back to the main
thread via `status: "blocked"`.

### Conventional commits format

```
<type>(<scope>): <subject in imperative mood, ≤ 50 chars after type prefix>

<Body: explain the WHY, not just the what. Two to five sentences.>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

**Types in this repo:** `feat`, `rect`, `chore`, `docs`
**Scopes match subsystems:** `server`, `ingest`, `shim`, `infra`, `tests`, `notes`, `repo`

### Hard rules

- **GPG signing is enforced** (`commit.gpgsign=true`). Never `--no-gpg-sign`.
- **Pre-commit hooks are honored.** Never `--no-verify`. Hook failure is a real failure
  — investigate and fix, then create a **NEW** commit (never `--amend` a hook-failed
  commit, which modifies the PREVIOUS commit and hides the rectification record).
- **Co-author trailer is mandatory** on every commit:
  `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`

### HEREDOC form for multi-line commit messages

Bash mangles `$(cat <<'EOF' … EOF)` when the body contains apostrophes (`don't`,
`won't`). Use the stdin form instead:

```bash
git commit -F - <<'COMMIT_EOF'
feat(server): add paper-id boundary validation (E13_S01)

Closes Threat 1 (path traversal via paper_id) from
.claude/notes/08-security-observability-ops.md. The handler chain
now validates paper_id against the canonical regex in
ingest/identifiers.py before any LanceDB query is executed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
COMMIT_EOF
```

---

## 6. Doc placement rule (CLAUDE.md §1)

Strict and load-bearing:

| Location | Allowed |
|---|---|
| Repo root | Only `README.md`, `CLAUDE.md`, `CHANGES.md`, `SECURITY.md`, `OWNERS.md` |
| Subdirs other than `.claude/` | Only `README.md` and `CLAUDE.md` (if useful for that subdir) |
| `docs/` | ONLY user-facing documentation referenced by the root README |
| `.claude/` | All other agent-internal Markdown — notes, roadmap, milestones, etc. |

When in doubt, default to `.claude/`. New milestone artifacts go to
`.claude/notes/milestones/<ID>/`. Per-feature internal references go to
`.claude/docs/`.

---

## 7. Test discipline

The project check command is `make test` (which runs `ruff check . && pytest`).

### Test runner — `uv run` is mandatory

```bash
/Users/chris.dare/Library/Python/3.9/bin/uv run python -m pytest [args]
```

The system `pytest` may pick up Python 3.9; this project requires 3.11+. Using
`uv run` resolves to the project's Python 3.12 environment.

For pass/fail-count-only checks, suppress noise:

```bash
/Users/chris.dare/Library/Python/3.9/bin/uv run python -m pytest --tb=no -p no:warnings 2>&1 | grep "passed"
```

### Test markers in this project

- `requires_model` — skipped by default; opt-in via per-model env var
  (e.g. `ARXMCP_RUN_REAL_BGE_RERANKER=1`)
- `eval` — Tier-0 → Tier-1 gate; skipped via cold-start matrix when fixture or
  corpus is missing

### Tool-schema re-pinning (load-bearing)

If a milestone adds, removes, or modifies any MCP tool definition in
`server/tools.py::ALL_TOOLS`, `EXPECTED_TOOL_SCHEMA_SHA256` in
`tests/test_server_tool_schema.py` MUST be re-pinned, otherwise the byte-stability
test fails and BP1 prompt-cache invalidates:

```bash
/Users/chris.dare/Library/Python/3.9/bin/uv run python -m pytest --update-tool-schema-hash
```

Run this **AFTER** wiring the new tool in `ALL_TOOLS` and the handler, not before.
Running early produces the wrong hash.

---

## 8. External-write boundary

Sub-agents are permitted to:

- Read any file in `$REPO_ROOT`
- Edit files under `$REPO_ROOT` (implementer only — critics are read-only)
- Make local `git commit` calls (implementer only)
- Run `make test`, `pytest`, `ruff`, `git log`, `git diff`, `git status`

Sub-agents are **NEVER** permitted to:

- `git push` (any remote, any branch)
- `gh issue create`, `gh pr create`, `gh pr review`, any `gh` mutation
- `helm install`, `kubectl apply`, `terraform apply`, any infra mutation
- Any API call to an external service
- Edit files outside `$REPO_ROOT`

These are **Phase 4 main-thread** operations, gated on per-event user authorization.

If your work logically requires an external write to complete, record it under the
"External writes required" section of your output artifact and **stop**. The
orchestrator will surface the requirement to the user in Phase 4 with explicit
per-write authorization gates.

---

## 9. Anti-pattern guards common to every phase

When you catch yourself doing the left column, stop and read the right column.

| Tempting belief | Reality |
|---|---|
| "I'll spawn a sub-agent for the nested step." | Platform-blocked. Return `status: "blocked"` and let the main thread route. |
| "I'll echo my full artifact in the response so the orchestrator has it in context." | Token waste; orchestrator reads from disk. Return only `{path, status, summary}`. |
| "Memory append after every run keeps things fresh." | Log spam. Append only when the pattern is new, action-changing, AND stable. |
| "I'll skip the memory check — this is a fresh milestone." | Past runs have learned things. The harness auto-injects MEMORY.md; rely on it. |
| "My summary can be 4 lines, the orchestrator can handle it." | Exactly 3 lines, ≤ 80 chars each. Strict shape. |
| "I'll write narrative prose between sections of my artifact." | Artifacts are structured data; prose between headings breaks downstream parsing. |
| "If pre-commit hook fails, `--no-verify` is fine for an agent run." | Never. Hook failure = real failure. Investigate and create a NEW commit. |
| "I'll cite the file but skip the line number — it's obvious." | A finding without `file:line` is not a finding. Cite or drop it. |
| "I'll inflate this finding to CRITICAL to make sure it gets fixed." | One inflation breaks the calibration table. Use the right severity. |
| "Pre-populating the `## Rectification status` section saves Phase 4 a step." | Phase 4 fills it. Pre-populating breaks replay semantics. |

---

## 10. macOS segfault guard

`tests/conftest.py` sets `KMP_DUPLICATE_LIB_OK=TRUE` at import. This is required
for the full `pytest` run not to SIGSEGV on macOS with `faiss-cpu` + PyTorch
co-loaded. Production Linux containers do not need it.

**Do not remove this line.** The adversary critic flags removal as HIGH.

---

## 11. Reference files (read on demand)

Embedded protocol in each agent file is usually sufficient. Read these only if you
need detail beyond what is in your agent file or this conventions file:

| File | When to read |
|---|---|
| `.claude/milestone-pipeline/references/phase-research.md` | Researcher — full Phase 1 detail |
| `.claude/milestone-pipeline/references/phase-implement.md` | Implementer — full Phase 2 detail |
| `.claude/milestone-pipeline/references/phase-critique.md` | Critics — full Phase 3 detail |
| `.claude/milestone-pipeline/references/phase-rectify.md` | (Main thread only — sub-agents do not run Phase 4) |
| `.claude/milestone-pipeline/references/critique-format.md` | Critics — machine-parsed format spec (`dedupe-findings.py` reads it) |
| `.claude/milestone-pipeline/references/state-schema.md` | Any agent reading/writing `state.json` |
| `.claude/notes/07-multi-agent-caching.md` | Cache discipline — read for any cache/prompt/tool-schema change |
| `.claude/notes/08-security-observability-ops.md` | Threat model — read for any security-adjacent work |
| `.claude/roadmap/README.md` | Authoritative epic index — read for tier-sequencing checks |

---

**End of agent-conventions.md.** Agent-specific protocol — research steps,
implementation rules, critique axes, severity calibration per critic, output
artifact format — lives in each agent's own `.md` file under `.claude/agents/`.
