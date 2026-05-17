---
description: Run one roadmap milestone end-to-end through Research → Implement → Critique → Rectify
argument-hint: <ID> [--brief "..."] [--deep|--single] [--repo-root /path]
---

# milestone-pipeline orchestrator

You are the orchestrator for a single roadmap milestone in the arXMCP project. This
command drives four sequential phases — Research, Implement, Critique, Rectify —
dispatching bespoke sub-agents per phase and persisting state in a strict-forward-only
state machine. You are the main thread. Sub-agents cannot spawn sub-agents.

## Parse the invocation arguments

The full invocation is the value of `$ARGUMENTS` — a single string containing every
token the user typed after `/milestone-pipeline`.

```
/milestone-pipeline <ID> [--brief "text"] [--deep|--single] [--repo-root /path]
```

- `<ID>` — milestone identifier in `EXX_SYY` format (e.g. `E13_S01`) or any
  string for ad-hoc runs. Required unless `--brief` is the first arg.
- `--brief "text"` — inline milestone brief, overrides roadmap file lookup.
- `--deep` — Research mode: 1× Opus (single researcher, deeper coverage).
  Mutually exclusive with `--single`.
- `--single` — Research mode: 1× Sonnet (small milestones; skip parallel pair).
  Mutually exclusive with `--deep`.
- `--repo-root /path` — override repo-root detection. Otherwise detected via
  the `REPO_ROOT` env var (if set), then `git rev-parse --show-toplevel`.

### Explicit argument parser

Parse `$ARGUMENTS` once at the top — do not let the LLM "infer" flag presence later
on. Use this routine (adapt the syntax to your shell of choice):

```bash
# Initialize defaults
MILESTONE_ID=""
INLINE_BRIEF=""
RESEARCH_MODE="standard"
REPO_ROOT_OVERRIDE=""

# Tokenize ARGUMENTS. The user may quote --brief's value.
set -- $ARGUMENTS
while [ $# -gt 0 ]; do
  case "$1" in
    --brief)         INLINE_BRIEF="$2"; shift 2 ;;
    --brief=*)       INLINE_BRIEF="${1#--brief=}"; shift ;;
    --deep)          RESEARCH_MODE="deep"; shift ;;
    --single)        RESEARCH_MODE="single"; shift ;;
    --repo-root)     REPO_ROOT_OVERRIDE="$2"; shift 2 ;;
    --repo-root=*)   REPO_ROOT_OVERRIDE="${1#--repo-root=}"; shift ;;
    --*)             echo "unknown flag: $1" >&2; exit 64 ;;
    *)               [ -z "$MILESTONE_ID" ] && MILESTONE_ID="$1" || echo "extra positional: $1" >&2
                     shift ;;
  esac
done

# Validate flag combinations
if [ "$RESEARCH_MODE" = "deep" ] && [ "$INLINE_BRIEF" = "" ] && [ -z "$MILESTONE_ID" ]; then
  echo "must provide <ID> or --brief" >&2; exit 64
fi

# Resolve REPO_ROOT (precedence: --repo-root > $REPO_ROOT env > git toplevel)
if [ -n "$REPO_ROOT_OVERRIDE" ]; then
  REPO_ROOT="$REPO_ROOT_OVERRIDE"
elif [ -n "${REPO_ROOT:-}" ]; then
  : # use existing env var
else
  REPO_ROOT="$(git rev-parse --show-toplevel)"
fi

SCRIPTS="$REPO_ROOT/.claude/milestone-pipeline/scripts"
```

If the parser surfaces an error (unknown flag, missing ID), surface it to the user
verbatim and stop — do not silently default.

---

## Pre-flight: state init and resume detection

Before entering any phase, run:

```bash
$SCRIPTS/init-state.sh $MILESTONE_ID [--repo-root $REPO_ROOT] [--brief "..."]
```

If init-state.sh prints `already initialized — resume from phase '<phase>'`, read
that phase and **jump directly to it** — do not re-run earlier phases.

Read current phase:
```bash
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID --get phase --repo-root $REPO_ROOT
```

Phase → jump target:
- `init` → Phase 1 (Research)
- `research-running` → Phase 1 (resume mid-research)
- `research-complete` → Phase 2 (Implement)
- `implement-running` → Phase 2 (resume mid-implement)
- `implement-complete` → Phase 3 (Critique)
- `critique-running` → Phase 3 (resume mid-critique)
- `critique-complete` → Phase 4 (Rectify)
- `rectify-running` → Phase 4 (resume mid-rectify)
- `complete` → Report summary and stop (milestone already complete)

State persists across session restarts and compactions. The pipeline is fully
resumable — re-invoking `/milestone-pipeline E13_S01` on an in-flight milestone
is safe and correct.

---

## Phase 1: Research

### Precondition
`state.phase` is `init` or `research-running`.

### Brief resolution
If `--brief "text"` was passed, use that text as `MILESTONE_BRIEF`.

Otherwise, extract the brief from the roadmap:
```bash
# Find the roadmap file for this milestone
ROADMAP_FILE=$(grep -rl "### $MILESTONE_ID " $REPO_ROOT/.claude/roadmap/ 2>/dev/null | head -1)
# If not found, also search plans/
[ -z "$ROADMAP_FILE" ] && ROADMAP_FILE=$(grep -rl "### $MILESTONE_ID " $REPO_ROOT/plans/ 2>/dev/null | head -1)
```

If not found in either location and no `--brief` was given, check `state.milestone_brief`
from the already-initialized state.json. If still empty, surface the gap to the user
and stop — a thin brief produces a thin pipeline.

### Checkpoint to research-running
```bash
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID research-running --repo-root $REPO_ROOT
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID --set "research_mode=\"$RESEARCH_MODE\"" --repo-root $REPO_ROOT
```

### Output paths
```
BRIEF_PATH_1 = $REPO_ROOT/.claude/notes/milestones/$MILESTONE_ID/research-brief-1.md
BRIEF_PATH_2 = $REPO_ROOT/.claude/notes/milestones/$MILESTONE_ID/research-brief-2.md  # standard mode only
SYNTHESIS_PATH = $REPO_ROOT/.claude/notes/milestones/$MILESTONE_ID/research-synthesis.md
```

### Dispatch researchers — ALL IN ONE ASSISTANT TURN

**Critical:** both Agent calls below MUST appear in the same assistant response.
Sequential dispatch (one per turn) defeats parallelism and is the named anti-pattern.

**Standard mode (default — 2× Sonnet in parallel):**

Dispatch BOTH of the following Agent calls simultaneously in your response:

> Agent 1 — Use the **milestone-researcher** agent with this prompt:
>
> You are researcher-1 of 2 running in parallel for milestone `$MILESTONE_ID` in
> the arXMCP project (a research-mathematics MCP server targeting algebraic geometry
> and number theory papers). Your peer is running concurrently — do NOT coordinate.
>
> Milestone brief:
> ```
> $MILESTONE_BRIEF
> ```
>
> Repo root: `$REPO_ROOT`
> Write your brief to: `$BRIEF_PATH_1`
>
> Cover in this order:
>
> 1. **In-codebase context.** Read `.claude/notes/` (design constitution; enumerate
>    files at runtime with `ls .claude/notes/*.md` — count drifts as new notes are added),
>    relevant files under `.claude/roadmap/`, and any existing source the milestone
>    touches. Quote load-bearing constraints verbatim; do not paraphrase. Identify
>    which design notes apply and cite them by filename.
>
> 2. **Prior decisions and lessons.** Recent git log (last 20 commits), any
>    milestone state.json files for adjacent milestones in `.claude/notes/milestones/`,
>    design notes that explicitly call out "things that always break." If a constraint
>    here conflicts with the milestone brief, FLAG IT — do not silently resolve.
>
> 3. **External sources.** Vendor docs (version-pinned where applicable), the MCP
>    spec at `https://modelcontextprotocol.io/specification/2025-06-18` for any
>    server-surface change, arXiv when the milestone touches math-content parsing,
>    and active GitHub OSS only when directly relevant. No marketing pages, no blog
>    summaries when the primary source is accessible.
>
> End your brief with two REQUIRED sections:
>
> - **Open questions** — anything the implementer must resolve before writing code.
>   If none, say so explicitly ("No open questions").
> - **External writes the implementation will require** — every push, PR creation,
>   ticket, infra mutation, third-party API call. List zero or more rows, each
>   `{type, target, why}`. An empty list means the milestone is purely local.
>
> Constraints:
> - Be opinionated. "Use foo or bar" without a recommendation is noise.
> - Quote — don't paraphrase — anything load-bearing from the codebase.
> - Cap at ~1500 words.
> - This is research, not a design doc. Don't propose architecture beyond what's
>   needed to scope the implementation.
>
> Return ONLY: `{ "path": "$BRIEF_PATH_1", "status": "ok|partial|blocked",
> "summary": "exactly 3 lines, ≤ 80 chars each" }`. Do NOT echo the file's content.
> Do NOT include any text outside the JSON object.

> Agent 2 — Use the **milestone-researcher** agent with this prompt:
>
> You are researcher-2 of 2 running in parallel for milestone `$MILESTONE_ID` in
> the arXMCP project. Your peer is running concurrently — do NOT coordinate.
>
> Milestone brief:
> ```
> $MILESTONE_BRIEF
> ```
>
> Repo root: `$REPO_ROOT`
> Write your brief to: `$BRIEF_PATH_2`
>
> Focus your coverage differently from researcher-1:
>
> 1. **External sources first.** Pull vendor docs (version-pinned), the MCP spec
>    (https://modelcontextprotocol.io/specification/2025-06-18) for the milestone's
>    surface area, arXiv if math-content parsing is in scope, and recently-updated
>    OSS in the same domain. Document API signatures, spec MUST clauses, and version
>    constraints explicitly.
>
> 2. **Failure-mode analysis.** What are the plausible ways this implementation
>    breaks? Enumerate at least five. For each: trigger condition, observable
>    symptom, and mitigation strategy. Ground these in the project's threat model at
>    `.claude/notes/08-security-observability-ops.md`.
>
> 3. **In-codebase cross-check.** After the external pass, read `.claude/notes/`
>    and confirm no design constraint contradicts your external findings. Flag
>    contradictions explicitly.
>
> End with the same two required sections as researcher-1 (Open questions +
> External writes), independently derived. Disagreement between the two briefs is
> USEFUL — the orchestrator will surface and resolve it at merge time.
>
> Same constraints: opinionated, quote load-bearing material, cap ~1500 words.
>
> Return ONLY: `{ "path": "$BRIEF_PATH_2", "status": "ok|partial|blocked",
> "summary": "exactly 3 lines, ≤ 80 chars each" }`.

**Deep mode (`--deep` flag — 1× Opus, single pass):**

Dispatch ONE Agent call using the **milestone-researcher** agent:

> You are the sole researcher for milestone `$MILESTONE_ID` in deep mode
> (single Opus pass, no peer). Apply the same coverage as the standard pair but
> go deeper:
>
> - Read every file in `.claude/notes/` that could plausibly apply, not just the
>   obvious ones.
> - Pull the MCP spec for the surface this milestone touches and quote every MUST
>   clause relevant to the implementation.
> - If the milestone is a parser / chunker / cache change, read the full
>   multi-agent caching note (`07-multi-agent-caching.md`) and reflect its
>   byte-stability rules in your brief.
> - Enumerate at least seven failure modes with trigger + symptom + mitigation.
>
> Brief to: `$BRIEF_PATH_1`. Same Open-questions / External-writes sections required.
> Cap ~3000 words.
>
> Return ONLY: `{ "path": "$BRIEF_PATH_1", "status": "ok|partial|blocked",
> "summary": "exactly 3 lines, ≤ 80 chars each" }`.

**Single mode (`--single` flag — 1× Sonnet):**

Dispatch ONE Agent call using the **milestone-researcher** agent. The prompt is
adapted from researcher-1 — there is no peer, so the "researcher-1 of 2" framing is
removed:

> You are the SOLE researcher for milestone `$MILESTONE_ID` in the arXMCP project
> (a research-mathematics MCP server targeting algebraic geometry and number theory
> papers). Single-mode dispatch — no peer researcher running concurrently.
>
> Milestone brief:
> ```
> $MILESTONE_BRIEF
> ```
>
> Repo root: `$REPO_ROOT`
> Write your brief to: `$BRIEF_PATH_1`
>
> Single-mode is used for small / well-scoped milestones. Cover the same three
> sections as the standard pair but in one combined pass:
>
> 1. **In-codebase context** — design constitution, roadmap, source files the
>    milestone touches. Quote load-bearing constraints verbatim.
> 2. **Prior decisions and lessons** — recent git log, adjacent milestone state.json.
>    Flag any conflict between the brief and the codebase in bold.
> 3. **External sources** — vendor docs (version-pinned), MCP spec for any
>    server-surface change, failure-mode enumeration.
>
> End with two REQUIRED sections: **Open questions** and **External writes the
> implementation will require** (zero or more `{type, target, why}` rows).
>
> Constraints: opinionated, quote load-bearing material verbatim, cap ~1500 words.
>
> Return ONLY: `{ "path": "$BRIEF_PATH_1", "status": "ok|partial|blocked",
> "summary": "exactly 3 lines, ≤ 80 chars each" }`. Do NOT echo file content.

### Post-dispatch: merge to synthesis (orchestrator, main session — NOT a sub-agent)

After ALL researchers return:

1. Read `$BRIEF_PATH_1` (and `$BRIEF_PATH_2` in standard mode) from disk.
2. Write `$SYNTHESIS_PATH` with these merge rules:
   - Quote — don't paraphrase — anything load-bearing.
   - Where briefs disagree, surface BOTH positions and pick one with explicit
     reasoning. Do not silently average.
   - Combine "External writes" lists into a deduped union.
   - Preserve all "Open questions" (dedup by meaning, not literal string).
   - Add an "Orchestrator synthesis note" section naming any divergence resolved.

Do NOT dispatch a "summarizer" sub-agent for this step. Merge in main session.

3. Persist state:
```bash
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID \
  --set 'research_briefs=[{"agent_id":"researcher-1","brief_path":"'$BRIEF_PATH_1'","summary":"..."},...]' \
  --repo-root $REPO_ROOT
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID \
  --set 'research_synthesis="'$SYNTHESIS_PATH'"' --repo-root $REPO_ROOT
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID \
  --set 'external_writes_required=[...]' --repo-root $REPO_ROOT
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID research-complete --repo-root $REPO_ROOT
```

---

## Phase 2: Implement

### Precondition
`state.phase` is `research-complete` or `implement-running`.

### Read synthesis first
Read `$SYNTHESIS_PATH` in full before any implementation decision.

### Record base commit and transition
```bash
BASE_SHA=$(git -C $REPO_ROOT rev-parse HEAD)
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID \
  --set "implementation_base=\"$BASE_SHA\"" --repo-root $REPO_ROOT
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID implement-running --repo-root $REPO_ROOT
```

### Choose implementation path

Use this decision tree (evaluate top-to-bottom; first match wins):

```
size estimate from synthesis < 500 LOC AND < 5 files touched
  AND no novel architecture
  AND no specialist match
  → INLINE: orchestrator (main session) implements directly.

matches a specialist agent's domain (none currently registered for arXMCP)
  → SPECIALIST: dispatch ONE specialist agent directly in main repo.
    (This path is currently unused — arXMCP has no specialist agents.)

otherwise
  → DELEGATED: dispatch 1–2 milestone-implementer agents in worktrees.
```

Record the choice:
```bash
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID \
  --set 'implementation_path="inline"' --repo-root $REPO_ROOT  # or "delegated"/"specialist"
```

### Inline path (orchestrator implements directly)

Read the synthesis, edit files, write tests, run the check command, commit.
One commit per logical unit. Conventional commits, GPG signed, never `--no-verify`.
Co-author trailer: `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.

Hard rules:
- Every acceptance criterion in the brief either has a verifiable artifact or stays
  unchecked with a written reason in `implementation-summary.md`.
- New code → new tests. Bug fix → regression test that fails on the old code.
- Stop at the external-write boundary: no `git push`, no `gh issue create`,
  no infra apply. Phase 4 gates external writes.

### Delegated path (1–2 milestone-implementer agents in worktrees)

If work can be parallelized along a clean module boundary, dispatch 2 implementers.
Both MUST be dispatched in ONE assistant turn.

For each implementer, use the **milestone-implementer** agent with isolation `worktree`:

> You are implementing milestone `$MILESTONE_ID` [part N of M] in the arXMCP project
> in an isolated git worktree. The orchestrator will critique your work next.
>
> Research synthesis (read in full): `$SYNTHESIS_PATH`
> Your implementation summary output path:
>   `$REPO_ROOT/.claude/notes/milestones/$MILESTONE_ID/implementation-summary.md`
>   [or implementation-summary-partN.md for multi-part]
>
> Assigned work scope: [describe module boundary partition here]
>
> Hard rules (non-negotiable):
> 1. Acceptance criteria are the contract. Every brief checkbox needs a verifiable
>    artifact or an explicit "unmet: reason" note in your summary.
> 2. Tests are not optional. New code paths get tests in `tests/`. Bug fixes get
>    regression tests.
> 3. Project check command must be green at exit. Detect order: `make test` if the
>    target exists in Makefile; otherwise `ruff check . && /Users/chris.dare/Library/Python/3.9/bin/uv run python -m pytest -q`.
>    Do not commit if it fails.
> 4. Conventional commits, GPG signed. Subject ≤ 50 chars after type prefix.
>    Co-author trailer: `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
>    Never `--no-verify`.
> 5. Stop at the external-write boundary. Local commits only.
>
> Your implementation-summary.md must include:
> - One-line summary of what landed
> - Commit range `<base>..<head>`
> - Acceptance criteria status (each checkbox)
> - New / changed test paths
> - External writes the orchestrator must authorize (zero or more `{type,target,why,blocking}` rows)
> - Any deviation from the brief's design and reason
>
> Return ONLY: `{ "path": "<summary path>", "status": "ok|partial|blocked",
> "summary": "exactly 3 lines, ≤ 80 chars each" }`.

After implementers return, orchestrator merges branches (if 2-part), re-runs the
check command, and records the final commit range.

### Project check command — detect order (re-detect each Phase 2 entry, don't cache)

```bash
if grep -qE '^(test|check):' $REPO_ROOT/Makefile 2>/dev/null; then
    make -C $REPO_ROOT test
else
    cd $REPO_ROOT && ruff check . && \
      /Users/chris.dare/Library/Python/3.9/bin/uv run python -m pytest -q \
        --tb=no -p no:warnings
fi
```

Do NOT advance state while the check command fails. Debug, fix, retry.

### Write implementation-summary.md

At `$REPO_ROOT/.claude/notes/milestones/$MILESTONE_ID/implementation-summary.md`:
- One-line summary
- Commit range `<base>..<head>`
- Acceptance criteria status (each brief checkbox)
- New / changed test paths
- External writes required (zero or more)
- Deviations from the brief

### Persist and advance
```bash
HEAD_SHA=$(git -C $REPO_ROOT rev-parse HEAD)
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID \
  --set "implementation_commit_range=\"$BASE_SHA..$HEAD_SHA\"" --repo-root $REPO_ROOT
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID \
  --set 'implementation_commits=["'$HEAD_SHA'"]' --repo-root $REPO_ROOT
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID \
  --set 'implementation_branch="main"' --repo-root $REPO_ROOT
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID implement-complete --repo-root $REPO_ROOT
```

---

## Phase 3: Critique

### Precondition
`state.phase` is `implement-complete` or `critique-running`.

### Gather diff scope
```bash
COMMIT_RANGE=$(python3 $SCRIPTS/checkpoint.py $MILESTONE_ID \
  --get implementation_commit_range --repo-root $REPO_ROOT)
CHANGED_FILES=$(git -C $REPO_ROOT diff --name-only $COMMIT_RANGE)
```

### Decide which critics fire

- **milestone-adversary** — ALWAYS fires. No exceptions.
- **milestone-infra-safety** — fires if any changed path matches:
  `^(infra/|\.github/workflows/|Dockerfile|docker-compose(\.[^/]+)?\.ya?ml|Makefile)`
- **milestone-oss-scout** — fires ONLY on explicit user request, OR if the
  research synthesis flagged the milestone as "active research area / unfamiliar OSS."
- **Frontend-UX critic** — NEVER fires on arXMCP (no frontend exists, by design).

### Checkpoint to critique-running
```bash
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID critique-running --repo-root $REPO_ROOT
```

### Output paths
```
CRITIQUE_ADVERSARY  = $REPO_ROOT/.claude/notes/milestones/$MILESTONE_ID/critique-adversary.md
CRITIQUE_INFRA      = $REPO_ROOT/.claude/notes/milestones/$MILESTONE_ID/critique-infra-safety.md
CRITIQUE_OSS        = $REPO_ROOT/.claude/notes/milestones/$MILESTONE_ID/critique-oss-scout.md
CRITIQUE_MERGED     = $REPO_ROOT/.claude/notes/milestones/$MILESTONE_ID/critique-merged.md
```

### Dispatch ALL critics in ONE assistant turn

All Agent calls below MUST appear in the same assistant response. Sequential dispatch
serializes the critics and is the named anti-pattern.

**Adversary critic (always — use milestone-adversary agent):**

> You are the adversary critic for milestone `$MILESTONE_ID` in the arXMCP project.
> Your job is to find problems, not to congratulate. Your report is the ONLY input
> to rectification, so missed issues ship.
>
> Inputs:
> - Commit range: `$COMMIT_RANGE`
> - Repo root: `$REPO_ROOT`
> - Milestone brief (verbatim): `$MILESTONE_BRIEF`
> - Implementation summary: `$REPO_ROOT/.claude/notes/milestones/$MILESTONE_ID/implementation-summary.md`
> - Output path: `$CRITIQUE_ADVERSARY`
>
> Walk EVERY axis below. For each, either flag a finding or note the axis as clean.
> Empty axes signal the critic is not earning its keep.
>
> 1. **Cache byte-stability** — non-alphabetical key serialization in tool definitions
>    or results, timestamps in tool responses, schema mutations without a hash bump.
>    Cite `07-multi-agent-caching.md`.
> 2. **Math fidelity** — any code path touching LaTeX, MathML, or paper bytes that
>    could mangle math (PyPDF as primary parser, regex-strip markup, lossy transforms,
>    dropped `<math>` tags). Cite `01-mission-and-context.md`, `04-parsing-and-chunking.md`.
> 3. **Security threat-model coverage** — `paper_id` regex validation,
>    indirect-prompt-injection wrapping (`<retrieved_chunk>` delimiters), LaTeXML
>    sandboxing, resource caps, origin pinning, session-id entropy.
>    Cite `08-security-observability-ops.md`.
> 4. **MCP 2025-06-18 spec compliance** — Streamable HTTP correctness, no
>    protocol-level streaming for tool results, pagination only on listings.
>    Cite `06-mcp-server-design.md`.
> 5. **Local-first + Docker constraint** — any AWS S3 / requester-pays /
>    multi-host-only dependency. Single-workstation deployment is the contract.
> 6. **Tier sequencing** — milestone consumes infrastructure that an uncompleted
>    prior tier was supposed to provide. Cross-check against `.claude/roadmap/`.
> 7. **No-fork policy** — git submodule, vendored copy, or direct file lift from
>    existing arxiv-MCP repos.
> 8. **Test surface** — acceptance-criteria coverage for the milestone, regression
>    test for any bug fixed.
>
> Beyond the axes: dead code, error handling that masks real failures, race conditions,
> partial implementations, missed edge cases on explicitly-accepted inputs, configuration
> left in a broken default.
>
> Output format: `# Critique — $MILESTONE_ID` header; **Critic:** adversary;
> **Generated:** ISO-8601 UTC; **Commit range:** `$COMMIT_RANGE`; **Verdict:** SHIP |
> SHIP-WITH-FIXES | DO-NOT-SHIP. Then: Executive summary (≤ 8 bullets, verdict first),
> Severity calibration table, Findings grouped by severity with `### F<n> — title`
> headings, "What was done well" (5–10 bullets, REQUIRED), Recommended rectification
> order, and an empty `## Rectification status` footer.
>
> Finding severity hard limits: CRITICAL = data loss / security / broken invariant.
> HIGH = wrong behavior on common path. MEDIUM = subtle correctness / missing test.
> LOW = style. A finding without a `file:line` citation is not a finding.
> Do NOT inflate severity — a CRITICAL inflation breaks the calibration table.
>
> Return ONLY: `{ "path": "$CRITIQUE_ADVERSARY", "status": "ok|partial|blocked",
> "summary": "exactly 3 lines, ≤ 80 chars each" }`.

**Infra-safety critic (conditional — fire only if CHANGED_FILES matches the infra regex):**

Use the **milestone-infra-safety** agent with this prompt:

> You are the infra-safety critic for milestone `$MILESTONE_ID`. Scope is narrow:
> only paths matching `^(infra/|\.github/workflows/|Dockerfile|docker-compose(\.[^/]+)?\.ya?ml|Makefile)`.
>
> Commit range: `$COMMIT_RANGE`. Repo root: `$REPO_ROOT`.
> Output path: `$CRITIQUE_INFRA`.
>
> Walk these axes for the matched paths only:
> 1. **Container hygiene** — base image pin, non-root user, read-only FS where
>    possible, no secrets in env, HEALTHCHECK present.
> 2. **docker-compose correctness** — port bind to `127.0.0.1` only (per
>    `08-security-observability-ops.md`), volume mounts deliberate, restart policy
>    explicit, no `latest` tags.
> 3. **CI workflow safety** — pinned action SHAs (not `@v1`), `permissions:` block
>    scoped down, no secrets in PR-from-fork triggers.
> 4. **Makefile / build script** — idempotent targets, no `sudo`, no destructive
>    defaults, exit codes propagate.
>
> Finding IDs prefixed `IS<n>` (e.g. `IS1`, `IS2`). Same critique file format as
> adversary. "What was done well" section still required.
>
> Return ONLY: `{ "path": "$CRITIQUE_INFRA", "status": "ok|partial|blocked",
> "summary": "exactly 3 lines, ≤ 80 chars each" }`.

**OSS-scout (opt-in only — fire only if explicitly requested or synthesis flagged it):**

Use the **milestone-oss-scout** agent with this prompt:

> You are the OSS-scout for milestone `$MILESTONE_ID`. Identify recent (within 18
> months), actively-maintained OSS that solves a problem this milestone solves, and
> assess whether the chosen approach remains the right one.
>
> Commit range: `$COMMIT_RANGE`. Repo root: `$REPO_ROOT`.
> Output path: `$CRITIQUE_OSS`.
>
> Scope:
> - License compatibility check (apache-2.0 / mit / bsd-3-clause are fine;
>   agpl needs explicit user OK; other licenses need explicit evaluation).
> - Activity check (commits in last 6 months, issue response time, maintainer count).
> - The arXMCP project has a **no-fork** rule — you are scouting for ideas and
>   design pressure, not import targets. State this explicitly in your recommendation.
>
> Finding IDs prefixed `OS<n>`. Same critique file format. "What was done well" still
> required (recognizing when the milestone's approach beats the OSS landscape is a
> finding worth recording).
>
> Return ONLY: `{ "path": "$CRITIQUE_OSS", "status": "ok|partial|blocked",
> "summary": "exactly 3 lines, ≤ 80 chars each" }`.

### Post-dispatch: merge critiques (orchestrator, main session — NOT a sub-agent)

After ALL critics return:

1. Read each critique file that was produced.
2. Write `$CRITIQUE_MERGED` by:
   - Concatenating all "Findings" sections, preserving original IDs (`F<n>`, `IS<n>`,
     `OS<n>`). Do NOT renumber.
   - Combining all "What was done well" bullets verbatim (deduplicate by meaning).
   - Writing a unified executive summary in the orchestrator's voice.
   - Writing a unified "Recommended rectification order" that accounts for
     cross-critic agreement and blast-radius interdependencies.
   - Appending an empty `## Rectification status` footer.

3. Run dedupe:
   ```bash
   python3 $SCRIPTS/dedupe-findings.py $CRITIQUE_MERGED
   ```
   This inserts a `## Cross-critic agreement` section. Findings flagged by ≥ 2
   critics within 5 lines of the same file get highest rectification priority.

4. Count findings.

   **Important — macOS BSD grep quirk:** `grep -c` prints `0` and exits non-zero on
   zero matches. Pairing it with `|| echo 0` produces a doubled value (`"0\n0"`),
   which corrupts the JSON in `--set` below. Use `|| true` (no-op suppress) instead
   so the captured value is just what grep already printed:

   ```bash
   CRITICAL=$(grep -c "Severity:\*\* CRITICAL" $CRITIQUE_MERGED 2>/dev/null || true)
   HIGH=$(grep -c "Severity:\*\* HIGH" $CRITIQUE_MERGED 2>/dev/null || true)
   MEDIUM=$(grep -c "Severity:\*\* MEDIUM" $CRITIQUE_MERGED 2>/dev/null || true)
   LOW=$(grep -c "Severity:\*\* LOW" $CRITIQUE_MERGED 2>/dev/null || true)
   # Defensive fallback in case grep was missing or produced empty output
   CRITICAL=${CRITICAL:-0}; HIGH=${HIGH:-0}; MEDIUM=${MEDIUM:-0}; LOW=${LOW:-0}
   ```

   Alternative (awk — handles the zero case natively, no shell quirks):

   ```bash
   CRITICAL=$(awk '/Severity:\*\* CRITICAL/{c++} END{print c+0}' $CRITIQUE_MERGED)
   ```

5. Persist state:
   ```bash
   python3 $SCRIPTS/checkpoint.py $MILESTONE_ID \
     --set 'critique_path="'$CRITIQUE_MERGED'"' --repo-root $REPO_ROOT
   python3 $SCRIPTS/checkpoint.py $MILESTONE_ID \
     --set 'critics_run=[{"critic":"adversary","output_path":"'$CRITIQUE_ADVERSARY'","summary":"..."}]' \
     --repo-root $REPO_ROOT
   python3 $SCRIPTS/checkpoint.py $MILESTONE_ID \
     --set 'critique_finding_counts={"critical":'$CRITICAL',"high":'$HIGH',"medium":'$MEDIUM',"low":'$LOW'}' \
     --repo-root $REPO_ROOT
   python3 $SCRIPTS/checkpoint.py $MILESTONE_ID critique-complete --repo-root $REPO_ROOT
   ```

---

## Phase 4: Rectify

### Precondition
`state.phase` is `critique-complete` or `rectify-running`.

**THIS PHASE RUNS IN THE MAIN ORCHESTRATOR SESSION ONLY.**
Do NOT dispatch a sub-agent for Phase 4 unless the user explicitly requests
delegation — and even then, the sub-agent must NOT be the same one that did Phase 2.
Self-rectification misses ~70% of real findings.

### Transition to rectify-running
```bash
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID rectify-running --repo-root $REPO_ROOT
```

### Read the merged critique
Read `$CRITIQUE_MERGED` in full.

### Re-verify gate (load-bearing — do NOT skip)

For every CRITICAL and HIGH finding:
1. Read the cited `file:line ± 30 lines`.
2. Compare the finding's "What" claim to what's actually in that region.
3. If the region no longer matches the claim → mark `invalidated`, record in
   `state.invalidated_findings`. Skip this finding.
4. If it still matches → proceed to fix.

Record every invalidation. If ≥ 40% of a single critic's CRITICAL + HIGH findings
invalidate, that critic's prompt is broken. Note the rate explicitly in the rect
commit body. (40% is a calibration heuristic — tune from real runs.)

### Fix loop

**Fix CRITICAL + HIGH always.** Fix MEDIUM only if cheap (≤ 30 LOC, small test
surface). Defer LOW findings.

For each fix:
- Inner loop cap: 3 attempts per finding. If still failing after 3, record under
  "escalations" in the critique footer and move on.
- Add a regression guard for every CRITICAL + HIGH fix (test, assertion, or
  snapshot). The finding must not reappear silently.

**Outer loop cap: 3 project-check iterations.** Beyond 3 failing check runs,
surface the problem to the user rather than continuing to spin.

Project check (same detect order as Phase 2):
```bash
if grep -qE '^(test|check):' $REPO_ROOT/Makefile 2>/dev/null; then
    make -C $REPO_ROOT test
else
    cd $REPO_ROOT && ruff check . && \
      /Users/chris.dare/Library/Python/3.9/bin/uv run python -m pytest -q \
        --tb=no -p no:warnings
fi
```

### Write the rect commit

Single rect commit. Subject format: `rect($MILESTONE_ID): close F1, H2, IS3, ...`
listing every fixed finding by ID. Body must include:
- Per-finding bullet: `F1 — fixed in path/file.py; regression: tests/test_file.py::test_bar`
- Deferred findings: `L1 — deferred (reason: out of scope; tracked at ...)`
- Invalidated findings: `M2 — invalidated by re-verify (cited region no longer matches)`
- If any critic's invalidation rate ≥ 40%, note it: `Adversary: N% invalidation rate; prompt needs tuning`

Commit discipline: conventional commits, GPG signed, never `--no-verify`, HEREDOC
to survive apostrophes and special characters:

```bash
git -C $REPO_ROOT commit -F - <<'COMMIT_EOF'
rect($MILESTONE_ID): close F1, H2, ...

- F1 — fixed in server/foo.py:42; regression: tests/test_foo.py::test_bar
- F2 — invalidated by re-verify (file:line no longer matches)
- L1 — deferred (style; tracked in follow-up)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
COMMIT_EOF
```

### Update the critique file's rectification status footer

Use Edit on `$CRITIQUE_MERGED` — append one bullet per finding under
`## Rectification status`:
- `- F1 — fixed in <sha> (regression guard: tests/test_foo.py::test_bar)`
- `- F2 — invalidated by re-verify (cited file:line no longer matches)`
- `- L1 — deferred (reason: style; tracked at <ref>)`

### Persist rectification state
```bash
RECT_SHA=$(git -C $REPO_ROOT rev-parse HEAD)
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID \
  --set 'rectification_commit="'$RECT_SHA'"' --repo-root $REPO_ROOT
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID \
  --set 'fixed_findings=["F1","H2",...]' --repo-root $REPO_ROOT
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID \
  --set 'deferred_findings=["L1",...]' --repo-root $REPO_ROOT
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID \
  --set 'invalidated_findings=["M2",...]' --repo-root $REPO_ROOT
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID \
  --set 'regression_tests_added=["tests/test_foo.py",...]' --repo-root $REPO_ROOT
```

### External-write boundary (hard stop)

Read `state.external_writes_required`:
```bash
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID \
  --get external_writes_required --repo-root $REPO_ROOT
```

If non-empty, surface the list to the user **verbatim** before proceeding:

```
External writes required for $MILESTONE_ID:
  1. git_push → origin/main — "land the implementation commit"
  2. gh_issue → github.com/... — "close tracking issue"

Authorize each above? (Each is a separate yes/no.)
```

Authorization is **per-event, not per-pipeline**. One "yes" does not authorize
subsequent writes. Wait for explicit user response for each item.

- On approval for a write: perform it, then set `external_writes_authorized=true`
  and `external_writes_completed=true` after all approved writes complete.
- On user "skip": record `external_writes_authorized=false`,
  `external_writes_completed=false`, and note the user's decision in the commit body.

Types and their gating status (for reference):
| Type | Gated? |
|---|---|
| `git commit` (local) | No — always allowed in Phase 4 |
| `git push origin <branch>` | YES — per-push user authorization |
| `gh issue create` / `gh pr create` | YES |
| `gh pr review --approve` | YES |
| `helm install`, `kubectl apply` | YES |
| Slack / email / external API call | YES |
| Edit a file outside `$REPO_ROOT` | YES |

The pipeline **cannot reach `complete`** while `external_writes_required` is non-empty,
`external_writes_authorized` is false, and the user has not explicitly chosen to skip.

### Final state.json commit and pipeline completion

```bash
python3 $SCRIPTS/checkpoint.py $MILESTONE_ID complete --repo-root $REPO_ROOT
```

Write the final chore commit:
```bash
git -C $REPO_ROOT commit -F - <<'COMMIT_EOF'
chore(notes): finalize $MILESTONE_ID state -> complete

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
COMMIT_EOF
```

Then print the end-of-pipeline summary (see below).

---

## End-of-pipeline summary

After reaching `complete`, print a concise report:

```
milestone: $MILESTONE_ID  →  COMPLETE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
research:   $RESEARCH_MODE — N brief(s)
implement:  $IMPLEMENTATION_PATH — N commit(s), range $COMMIT_RANGE
critique:   N critics — C/H/M/L = $CRITICAL/$HIGH/$MEDIUM/$LOW findings
rectify:    $RECT_SHA — fixed N, deferred N, invalidated N
tests:      N regression tests added
external:   authorized=$EXT_AUTHORIZED  completed=$EXT_COMPLETED
```

---

## Anti-pattern guard table

Stop when you catch yourself doing the left column.

| tempting belief | reality |
|---|---|
| "Skip Phase 1, the milestone is small." | Phase 1 populates `external_writes_required`. Skipping = surprise external writes at the end with no gate. |
| "Dispatch the second researcher in the next turn so I can see the first summary first." | Sequential dispatch defeats parallelism. Both researchers MUST launch in one assistant turn. |
| "The implementer can also write the critique — they understand the code best." | Self-critique misses ~70% of real findings. Phase 3 critics must be fresh sub-agents. |
| "≥ 40% of CRITICAL findings invalidated on re-verify is fine — I'll just fix the rest." | That's a broken critic prompt. Record the rate and note it in the rect commit body. |
| "Bundle the rect commit into the last implementer commit with `--amend`." | Phase 4's commit is a separate, named artifact. Amending hides the rectification record. |
| "I can push now since the user already authorized the milestone." | Authorization is per-event. `git push` is a separate user check, even within one pipeline run. |
| "I'll inflate this finding to CRITICAL to make sure it gets fixed." | Inflate severity once and the calibration table stops working. Use HIGH or fix it inline. |
| "Run a 'summarizer' sub-agent after the critics so I get a clean report." | Meta-orchestrator anti-pattern. Doubles cost, loses nuance. Merge in main session. |
| "Sub-agents can echo their full report back so I have it in context." | They write to a file and return `{path, status, summary}`. The channel stays small; orchestrator reads on demand. |
| "If a hook fails I can just `--no-verify` and move on." | Hook failure is a real failure. Investigate. Never `--no-verify`. |
| "Dispatch Phase 3 critics one-per-turn to monitor progress." | All critics in ONE assistant turn. Monitoring between dispatches serializes the critics. |
| "The 40% threshold is conservative; I'll accept 55%." | The 40% number is a heuristic, not a negotiable default. If you deviate, record the revised threshold in the rect commit. |

---

## Project conventions this command respects

- **Conventional commits** — subject ≤ 50 chars after type prefix. Types in this
  repo: `feat`, `rect`, `chore`, `docs`. Scopes match subsystems: `server`, `ingest`,
  `shim`, `infra`, `tests`, `notes`, `repo`.
- **Three-commit-per-milestone pattern:**
  1. `feat(<scope>): <topic> ($MILESTONE_ID)` — implementation
  2. `rect(<scope>): close N SEVERITY from $MILESTONE_ID critique` — rectification
  3. `chore(notes): finalize $MILESTONE_ID state -> complete` — bookkeeping
- **GPG signing** is enabled (`commit.gpgsign=true`). Never `--no-gpg-sign`.
- **Co-author trailer:** `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`
- **Pre-commit hooks** are honored. Never `--no-verify`. Hook failure = investigate.
- **HEREDOC commits** to survive apostrophes / special characters in commit bodies:
  use `git commit -F - <<'COMMIT_EOF' … COMMIT_EOF` (stdin form).
- **Design constitution** — `.claude/notes/` (enumerate via `ls .claude/notes/*.md`)
  is the authoritative source
  for adversary-critic axes. Cite the note filename in any finding that derives from it.
- **`uv run` for pytest** — project requires Python 3.11+. Use
  `/Users/chris.dare/Library/Python/3.9/bin/uv run python -m pytest` not system pytest.

---

## Supporting infrastructure locations

```
$REPO_ROOT/.claude/
├── agents/
│   ├── milestone-researcher.md       # Phase 1 sub-agent definition
│   ├── milestone-implementer.md      # Phase 2 sub-agent definition
│   ├── milestone-adversary.md        # Phase 3 sub-agent — always fires
│   ├── milestone-infra-safety.md     # Phase 3 sub-agent — conditional
│   └── milestone-oss-scout.md        # Phase 3 sub-agent — opt-in
├── commands/
│   └── milestone-pipeline.md         # this file
└── milestone-pipeline/
    ├── references/
    │   ├── agent-conventions.md       # shared sub-agent context (read by every agent)
    │   ├── agent-prompts.md           # historical sub-agent prompt source (pre-conversion)
    │   ├── critique-format.md         # canonical critique markdown format
    │   ├── phase-critique.md          # Phase 3 detail reference
    │   ├── phase-implement.md         # Phase 2 detail reference
    │   ├── phase-rectify.md           # Phase 4 detail reference
    │   ├── phase-research.md          # Phase 1 detail reference
    │   └── state-schema.md            # state.json schema and transitions
    └── scripts/
        ├── checkpoint.py              # state machine validator + --get/--set
        ├── dedupe-findings.py         # cross-critic agreement detector
        ├── init-state.sh              # idempotent state init
        └── status.sh                  # human-readable state dump

State files (per milestone):
$REPO_ROOT/.claude/notes/milestones/<ID>/
    state.json                         # strict-forward-only machine state
    research-brief-1.md                # researcher-1 output
    research-brief-2.md                # researcher-2 output (standard mode)
    research-synthesis.md              # orchestrator-merged brief
    implementation-summary.md          # implementer output
    critique-adversary.md              # adversary critic output
    critique-infra-safety.md           # infra-safety output (conditional)
    critique-oss-scout.md              # oss-scout output (opt-in)
    critique-merged.md                 # merged + deduped critique
```

## Quick status check

```bash
# Check state of any milestone
python3 $REPO_ROOT/.claude/milestone-pipeline/scripts/status.sh $MILESTONE_ID

# Read a specific field
python3 $REPO_ROOT/.claude/milestone-pipeline/scripts/checkpoint.py $MILESTONE_ID --get phase
```

## Anti-pattern C trade-off (read once, internalize)

This four-phase chain run by an LLM orchestrator is structurally Anti-pattern C
("Sequential orchestrator that paraphrases"). Three mitigations are baked in:

1. **Depth stays at 1** — this command directly dispatches each phase's sub-agents;
   no nested "lifecycle orchestrator" persona.
2. **No paraphrasing summarizer between phases** — sub-agents return
   `{path, status, summary}` only; orchestrator reads artifacts raw at merge time.
3. **User checkpoint at the external-write boundary** in Phase 4.
4. **State persists** so any phase can be resumed without re-paraphrasing from scratch.

This is the documented reason a single orchestrating command is acceptable despite
published guidance against sequential orchestrators.
