# Milestone-pipeline conversion — adversarial critique

## Verdict
SHIP-WITH-FIXES

The conversion gets the canonical-pattern fundamentals correct: `memory: project`,
`model: sonnet|opus`, `tools:`, slash-command `argument-hint:`/`description:`, and the
"subagents cannot spawn subagents" platform constraint are all real per the official
`code.claude.com/docs/en/sub-agents` and `code.claude.com/docs/en/slash-commands` pages.
But there are real defects: token-economy waste in the agent files, one minor
return-contract inconsistency, a stale legacy SKILL.md that contradicts the new contract,
and unresolved stale references in the sibling `roadmap` skill and `settings.local.json`
that the Sonnet-2 agent's "verification clean" claim glossed over.

## Critique-internal rate-the-axes

- Canonical pattern: PASS — `memory: project`, `model: sonnet|opus`, `tools:` (list form),
  `argument-hint`, `description` are all documented frontmatter keys; subagent path
  `.claude/agents/<name>.md` is correct; `.claude/agent-memory/<name>/` is the documented
  project-scope memory directory.
- Return contract: PARTIAL — all five agents converge on `{path, status, summary}`, but
  the legacy `.claude/milestone-pipeline/SKILL.md` (now reachable as a skill via
  `.claude/milestone-pipeline/SKILL.md` discovery rules — see F2) still documents the
  contract as `summary_3_lines`.
- Token budget: FAIL — five agent files at 294-385 lines (1,750 lines total) and a
  872-line slash command body duplicate large amounts of the same content (banned
  patterns, commit conventions, test runner, anti-pattern guards). Each duplication is
  a recurring token cost on every agent invocation.
- Path correctness: PARTIAL — all new agent + command + CLAUDE.md references resolve
  to `.claude/milestone-pipeline/`. But the sibling `.claude/skills/roadmap/SKILL.md`
  + `.claude/skills/roadmap/references/arxmcp-integration.md` (modified in-place per
  `git status`) still mostly point to the new path, while `.claude/notes/handoffs/HANDOFF-pre-E09.md`
  retains old `.claude/skills/milestone-pipeline/` references. `settings.local.json`
  has 4 entries pointing to the old scripts path.
- Loss-in-translation: PASS — the 9-state state machine, anti-pattern guards, ≥40%
  invalidation calibration, HEREDOC commit form, EXPECTED_TOOL_SCHEMA_SHA256 re-pin
  rule, `make test` precondition, push authorization gate, Phase 2 worktree mode,
  Phase 4 user-checkpoint at external-write boundary are all carried forward
  (mostly verbatim in the 872-line command body).
- Bugs: PARTIAL — see F5 (slash command bash `grep -c` count parsing returns "0" with
  trailing text on macOS), F6 (kuzu version drift in milestone-adversary), F7
  (researcher prompt says read 11 design notes but agent file says "11 files plus
  prompts-bp-discipline.md" — count mismatch with current `.claude/notes/`).
- Parallel dispatch: PASS — the slash command repeats the "ALL IN ONE ASSISTANT TURN"
  discipline three separate times (researchers, implementers, critics) with bold/caps
  emphasis.
- Sub-agent isolation: PASS — every agent file explicitly states "You CANNOT spawn
  sub-agents" in §0/§1; the slash command repeats the constraint in its preamble.
- Agent memory: PARTIAL — `memory: project` IS a documented frontmatter key (per the
  official subagents docs frontmatter reference table) and the project-scope path
  IS `.claude/agent-memory/<name>/`. BUT the agent files instruct manual read/write
  of `.claude/agent-memory/<name>/lessons.md` while the harness actually auto-loads
  `MEMORY.md` (first 200 lines / 25KB) into the system prompt at startup. The agents
  are NOT using the harness's actual mechanism.
- CLAUDE.md update: PASS — §4.2 renamed to "Use the `/milestone-pipeline` command"
  (line 95), directory layout reflects new structure (lines 287-300), task recipe at
  line 420 uses the slash command, related-links section (lines 501-503) points to
  new paths.

## Findings

### F1 — HIGH — Agent memory uses wrong filename (`lessons.md` vs harness's `MEMORY.md`)

**Where:** all five `.claude/agents/*.md` files — milestone-researcher.md:65,
milestone-implementer.md:67, milestone-adversary.md:71-72,
milestone-infra-safety.md:79-80, milestone-oss-scout.md:84-85; plus the corresponding
"Memory: record new lessons" sections that write to the same filename.

**What:** Every agent reads/writes `.claude/agent-memory/<name>/lessons.md`. Per the
official subagents docs (frontmatter reference + "Enable persistent memory" section),
when `memory: project` is set, the harness automatically injects "the first 200 lines or
25KB of `MEMORY.md` in the memory directory, whichever comes first" into the subagent's
system prompt. Read/Write/Edit tools are auto-enabled. The agents have invented a
different filename (`lessons.md`) that the harness does NOT auto-load. Result:
load-bearing knowledge accumulated by past runs sits in `lessons.md` while the
auto-injected slot is empty — the persistence works, but the read on the next invocation
requires the agent to explicitly Read the file, which only happens if the markdown body
remembers to instruct it. The bodies DO instruct an explicit read, but they then ignore
that the harness is also injecting (an empty) `MEMORY.md`. This is a near-miss: the
feature mostly functions but is fighting the harness rather than using it.

**Why this matters:** When `memory: project` is in frontmatter and the agent files
explicitly mention `.claude/agent-memory/<name>/lessons.md`, a future maintainer reading
the official docs will be confused why `MEMORY.md` is empty and `lessons.md` is the real
data store. The agents should either (a) use `MEMORY.md` as the canonical file (matching
harness auto-injection) and rely on the harness to load it OR (b) explicitly note in the
markdown that this project chose not to use auto-injection and uses `lessons.md` instead.

**Suggested fix:** Rename `lessons.md` → `MEMORY.md` in all five agent files. Drop the
explicit "Read .claude/agent-memory/<name>/lessons.md" instruction (the first 200
lines/25KB are auto-injected). Keep the explicit Append-On-Success instruction for the
agent to add new patterns. Pin in each agent file: `## Memory (auto-injected by harness)`
heading so the read is documented as automatic.

**Regression guard:** add an integration test (or doc-test) that asserts the project
agents reference `MEMORY.md` (not `lessons.md`) — a regex grep over `.claude/agents/*.md`
for the canonical filename.

### F2 — HIGH — Legacy `.claude/milestone-pipeline/SKILL.md` will be discovered as a skill at `/milestone-pipeline`

**Where:** `.claude/milestone-pipeline/SKILL.md` (full file, especially lines 1-4 and
the frontmatter at lines 2-4).

**What:** The SKILL.md was kept as a "legacy reference" but its frontmatter still
declares `name: milestone-pipeline` and a `description:`. Per the official Claude Code
skills docs, skill discovery walks the project tree, and per the docs: "if a skill and
a command share the same name, the skill takes precedence." However the discovery path
for skills is `.claude/skills/<name>/SKILL.md`, NOT `.claude/<name>/SKILL.md`, so the
legacy file at `.claude/milestone-pipeline/SKILL.md` will likely NOT be auto-discovered
as a skill — verify this before treating as critical. **If it IS discovered (because
Claude Code also walks `.claude/` more broadly or because `.claude/milestone-pipeline/`
matches some other directory convention), it would shadow the slash command and the
canonical orchestrator would silently not fire.** Either way, the file is misleading:
its body documents the OLD `{path, status, summary_3_lines}` return contract (line 104,
147, 204) which contradicts the new agents' `{path, status, summary}` contract.

**Why this matters:** A future agent reading `.claude/milestone-pipeline/SKILL.md` for
reference will encounter the old `summary_3_lines` contract and may instruct sub-agents
to return that field, breaking the orchestrator's parsing. Worse, if Claude Code's
discovery walks `.claude/` and treats anything named `SKILL.md` as a skill, this could
auto-register a stale skill name.

**Suggested fix:** EITHER (a) move the file to `.claude/milestone-pipeline/LEGACY.md`
(no SKILL.md filename, no frontmatter) so it cannot be mistaken for a skill, OR (b)
delete it entirely (the slash command body has fully absorbed its content), OR (c) keep
the file but update lines 104, 147, 204 to say `{path, status, summary}` matching the
new contract.

**Regression guard:** add a test that scans `.claude/` for any file named `SKILL.md`
or any `.claude/agents/*.md` and asserts the union returns no contract drift between
`summary` vs `summary_3_lines`.

### F3 — HIGH — `tools:` frontmatter uses YAML list form; docs example uses comma-separated

**Where:** all five `.claude/agents/*.md` files — milestone-researcher.md:6-12,
milestone-implementer.md:6-12, milestone-adversary.md:6-12, milestone-infra-safety.md:6-10,
milestone-oss-scout.md:6-12.

**What:** Every agent file declares `tools:` as a YAML list (`tools:\n  - Read\n  - Grep
...`). The official subagents docs show the syntax as `tools: Read, Grep, Glob, Bash`
(comma-separated string on a single line). The docs do NOT show the multi-line YAML
list form. The `--agents` CLI JSON example does show `"tools": ["Read", "Grep", ...]`
(JSON array). Whether the YAML-list form is parsed correctly by Claude Code is unclear
from the docs.

**Why this matters:** If the harness parses only comma-separated strings, the YAML-list
form will silently fail (the agent will inherit ALL tools from the main conversation
rather than the restricted set the file declares). Specifically, `milestone-researcher`
is meant to be read-only (no Edit, no Write) but if the `tools:` list isn't parsed, it
gets full tool access and could accidentally write code during research. The skill-md
docs DO document both forms ("Accepts a space-separated string or a YAML list") but
the subagents docs only show the comma-separated form. This is ambiguity at the
contract level.

**Suggested fix:** EITHER (a) convert all five agents to use the comma-separated form
that the official docs show explicitly: `tools: Read, Grep, Glob, Bash, WebFetch,
WebSearch` — this is the safest interpretation; OR (b) verify empirically by spawning
each agent and checking that Edit/Write are actually denied to milestone-researcher
before shipping. The comma-separated form is the safe call.

**Regression guard:** spawn each agent with a no-op task and verify it cannot Edit a
file (for the read-only agents). Even cheaper: ASCII test that compares the agent
frontmatter against a fixture of the comma-separated form.

### F4 — MEDIUM — Massive content duplication across five agent files (token waste)

**Where:** `.claude/agents/milestone-*.md` (all five). Specific examples:

- Commit conventions section appears in milestone-implementer.md:175-211 (37 lines) AND
  is partially duplicated in milestone-researcher.md:206-212 AND the slash command at
  lines 789-800. Roughly 60+ lines of overlap.
- Banned-pattern checklist appears verbatim in milestone-researcher.md:186-219 (33 lines),
  milestone-implementer.md:246-277 (31 lines), milestone-adversary.md:230-242 (12 lines),
  and the slash command lines 467-471. ~80 lines of overlap.
- "Anti-pattern guards" tables appear in milestone-researcher.md:223-237 (14 lines),
  milestone-implementer.md:301-313 (12 lines), milestone-adversary.md:313-324 (11 lines),
  milestone-infra-safety.md:300-309 (9 lines), milestone-oss-scout.md:277-287 (10 lines),
  and slash command lines 766-783 (18 lines). ~74 lines of largely-redundant tables.
- "Memory: record new lessons" boilerplate (~17 lines per agent × 5 = ~85 lines).
- Each agent's §1 ("Who you are and what success looks like") + §3/4 ("Memory: read
  lessons at start") + §11/12 ("Reference files") add another 30-50 lines of
  near-identical scaffolding per agent.

Total estimated duplication: 350-450 lines that could live in a single shared
`.claude/agents/_common.md` referenced via the per-agent body, OR in the existing
`.claude/milestone-pipeline/references/agent-prompts.md` which was the original
single-source-of-truth.

**What:** Every time any agent is spawned, the harness loads its full 294-385-line body.
With five agents and ~400 lines of duplicate content across them, the cumulative cost
across a single milestone-pipeline run (2 researchers + 1 implementer + 1-3 critics =
4-6 agent spawns) is roughly 1,500-2,400 redundant tokens loaded per run.

**Why this matters:** The original SKILL.md plus `agent-prompts.md` was the
single-source-of-truth pattern. The conversion exploded that into five copies. Token
cost compounds: each agent dispatch loads the full body into a fresh context window.

**Suggested fix:** Move common content (commit conventions, banned patterns, test
runner, project conventions, memory protocol) into
`.claude/milestone-pipeline/references/agent-conventions.md` (which already exists as a
similar role). Each agent file shrinks to ~150 lines: agent-specific protocol +
references to the shared file. The agent files DO already reference
`.claude/milestone-pipeline/references/*` at their bottom, so the pattern is in place —
it's just not used aggressively enough.

**Regression guard:** add a doc-test that asserts no two agent files share more than
~50 lines of identical content (excluding YAML frontmatter and shared section headers).

### F5 — MEDIUM — Slash command's `grep -c` finding-counts are fragile on macOS

**Where:** `.claude/commands/milestone-pipeline.md:566-569`.

**What:** The command runs:
```bash
CRITICAL=$(grep -c "Severity:\*\* CRITICAL" $CRITIQUE_MERGED || echo 0)
```
On macOS BSD grep with `-c`, if there are zero matches, `grep` exits non-zero AND prints
`0`. The `|| echo 0` then appends ANOTHER `0` — the captured string becomes `0\n0` (or
`0 0`). Downstream the value is interpolated into a JSON object via
`'critique_finding_counts={"critical":'$CRITICAL',...}'` which produces malformed JSON
like `{"critical":0\n0,...}` and `checkpoint.py --set` rejects it as invalid JSON
(falling back to "literal string" per the parse_set_assignment function on line 167 —
which is itself a different latent bug, since `--set` will accept the invalid value as
a string and silently corrupt state.json).

**Why this matters:** The state.json finding counts may end up corrupted to a string
("0\n0") instead of an integer (0) when there are zero CRITICAL findings. Downstream
consumers (`status.sh`, the end-of-pipeline report) expect integers.

**Suggested fix:** Use `grep -c ... || true` and trust grep's natural output:
```bash
CRITICAL=$(grep -c "Severity:\*\* CRITICAL" $CRITIQUE_MERGED || true)
CRITICAL=${CRITICAL:-0}
```
Or use `awk` which doesn't have the zero-match-non-zero-exit quirk.

**Regression guard:** add a test that runs the pipeline with a critique containing 0
CRITICALs and verifies state.json's `critique_finding_counts.critical` is integer 0,
not string "0\n0".

### F6 — MEDIUM — Stale Kùzu version drift mention in milestone-adversary

**Where:** `.claude/agents/milestone-adversary.md:240` (banned-pattern checklist row).

**What:** The checklist says: `kuzu==<version other than 0.11.3>` in pyproject.toml | HIGH
| Version must be pinned exactly`. The pin IS exactly 0.11.3 per CLAUDE.md §8 row 2.
However, the same agent's banned-pattern table at line 241 also says
`Path using kuzudb/ instead of kuzu/ | MEDIUM | Documented drift; correct path is kuzu/`.
Both are correct per CLAUDE.md but the project-wide test for `kuzu==0.11.3` would also
catch any version bump including planned future upgrades — making this a higher-noise
rule than intended. The agent's calibration table says HIGH for version drift; but the
project may upgrade Kùzu in the future (E11+) and the adversary will keep flagging it.

**Why this matters:** The HIGH-severity ban on `kuzu` version drift will become a
false positive the moment the project intentionally upgrades. The rule should be
phrased as: "if `kuzu` version is changed and CLAUDE.md §8 row 2 has not been updated
in the same commit, flag HIGH."

**Suggested fix:** Reword the row in milestone-adversary.md:240 to gate on
CLAUDE.md §8 row 2 not being co-updated, rather than on absolute version.

### F7 — MEDIUM — Researcher counts `.claude/notes/` files differently in different sections

**Where:** `.claude/agents/milestone-researcher.md:75-91` (says "11 numbered files plus
prompts-bp-discipline.md"); slash command at line 130 says "11 files"; legacy SKILL.md
line 54 says "11 files" but the CLAUDE.md directory layout at lines 309-326 lists "10
numbered notes + HANDOFF + milestones/".

**What:** `.claude/notes/` has files 01..10 (10 numbered design notes) plus
`prompts-bp-discipline.md`, `HANDOFF.md`, `README.md`, plus the `milestones/` and
`handoffs/` and `scans/` subdirs. The "11 files" count in the researcher prompt is
plausible if you count 01..10 + prompts-bp-discipline.md = 11. But the CLAUDE.md
directory layout says "10 numbered notes" which is also correct. The drift here is that
nobody recounts when a new note is added.

**Why this matters:** Low-grade source-of-truth drift. Doesn't break anything today but
the next researcher will spend cycles deciding whether to also read README.md and
HANDOFF.md (which they probably should for the README index but not necessarily for
HANDOFF). The prompts at lines 75-91 are detailed enough that the discrepancy is
swallowed in practice — but it's still a calibration issue.

**Suggested fix:** Replace hard counts with `git ls-files .claude/notes/*.md` — let the
agent enumerate at runtime. Or phrase as "all numbered design notes plus
prompts-bp-discipline.md (currently ~10-11 files)."

### F8 — MEDIUM — `settings.local.json` has 4 stale Bash permissions pointing to old script path

**Where:** `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/settings.local.json:6-9`.

**What:** Four entries in `permissions.allow` reference
`.claude/skills/milestone-pipeline/scripts/...`:
- `init-state.sh E01_S01-S03 --brief-from /tmp/arxmcp-E01_S01-S03-brief.md`
- `checkpoint.py E01_S01-S03 research-running`
- `checkpoint.py E01_S01-S03 --set 'research_mode="standard"'`
- `init-state.sh E09_S01`

The new scripts live at `.claude/milestone-pipeline/scripts/...`. The Sonnet-2 agent
claimed these are "harmless" — that's WRONG. These specific entries were granted
permission for a specific path; the new path needs new permissions. On the next
milestone-pipeline run, the harness will prompt the user every single time a script
under the new path runs (because there is no matching allow rule for the new path).

**Why this matters:** Adds friction to every pipeline run. The user will see permission
prompts they thought were already granted. Not silent breakage, but it IS broken.

**Suggested fix:** Update `.claude/settings.local.json` lines 6-9 to use the new path,
OR add fresh entries with both old and new for one transition cycle. Better: switch the
entries from exact-string matches to prefix patterns like
`Bash(.claude/milestone-pipeline/scripts/*)` so future minor command variations don't
re-trigger prompts.

### F9 — LOW — Stale path references in handoff archive and worktrees

**Where:** `.claude/notes/handoffs/HANDOFF-pre-E09.md` (multiple lines 48, 66-68, 647)
and various `.claude/worktrees/*/` files (settings, HANDOFF, CLAUDE.md, etc.).

**What:** Six+ references to `.claude/skills/milestone-pipeline/...` remain in archived
handoff files and worktree-local copies. These are intentionally archived snapshots so
updating them rewrites history — generally a LOW finding. But the worktree-local files
are live work-in-progress, not archives, and the path is now stale there too.

**Why this matters:** Worktrees may be re-merged in the future, bringing stale paths
back into the live tree.

**Suggested fix:** Leave `.claude/notes/handoffs/HANDOFF-pre-E09.md` alone (it's an
intentional snapshot — add an editor's note at the top redirecting readers to the new
path). For `.claude/worktrees/*/`, if any worktree is still active, sweep its files.
If not, the worktrees should be retired.

### F10 — LOW — `--single` mode dispatches with prompt that says "researcher-1 of 2"

**Where:** `.claude/commands/milestone-pipeline.md:227-229`.

**What:** Single mode says "Same as standard researcher-1 prompt above, dispatched
alone. Brief to `$BRIEF_PATH_1`." The standard researcher-1 prompt at line 114-115
begins: "You are researcher-1 of 2 running in parallel for milestone `$MILESTONE_ID`...
Your peer is running concurrently — do NOT coordinate." In single mode there IS no peer.
The agent will read this and be confused (or invent context for the missing peer).

**Why this matters:** Tiny edge case but the prompt is technically lying to the
sub-agent. Cheap fix.

**Suggested fix:** Add an explicit single-mode prompt template, or have the slash
command body branch the "researcher-1 of 2" intro line to "You are the sole researcher
for milestone `$MILESTONE_ID`" when `RESEARCH_MODE=single`.

### F11 — LOW — `--repo-root` flag isn't a Bash arg, it's invocation arg parsing

**Where:** `.claude/commands/milestone-pipeline.md:14-35`.

**What:** The command claims to accept `--repo-root /path` as one of `$ARGUMENTS`. Per
the official slash-commands docs, `$ARGUMENTS` is "all arguments passed when invoking
the skill" as a single string. The command body never explicitly parses it — the
"Set defaults" block at line 31 says "Detect with `git rev-parse --show-toplevel` if not
provided" but doesn't show the parsing logic. A literal `/milestone-pipeline E10_S01
--repo-root /tmp/foo` would put `E10_S01 --repo-root /tmp/foo` into `$ARGUMENTS` and the
command body would need to grep that out itself. That logic is implicit.

**Why this matters:** Users who pass `--repo-root` may get silently-ignored behavior
because the parsing isn't spelled out.

**Suggested fix:** Add an explicit "parsing" code block near line 31 that shows how
to extract `--repo-root` from `$ARGUMENTS`. Or remove the flag from `argument-hint` and
document `REPO_ROOT` env var as the only override.

## What was done well

- **Canonical pattern verified correctly.** The user's reported pattern (`memory: project`,
  `model: sonnet|opus`, `tools:`, agent files in `.claude/agents/`, slash command in
  `.claude/commands/`) matches the official docs verbatim. Not hallucinated.
- **Parallel-dispatch discipline preserved aggressively.** The "ALL IN ONE ASSISTANT
  TURN" rule is repeated three times in the slash command body (researchers, implementers,
  critics) with bold/caps emphasis. The anti-pattern guard table at line 766 reinforces it.
- **Subagent-isolation constraint is everywhere.** All five agent files state explicitly
  "You CANNOT spawn sub-agents" in §0 or §1. The platform constraint is correctly
  surfaced to each agent.
- **Return contract is consistent across agents.** All five agents converge on `{path,
  status, summary}` with status enum `ok|partial|blocked`. The 3-line summary semantics
  (line 1 = headline, line 2 = top risk/finding, line 3 = counts) is consistent.
- **Load-bearing constraints carried forward verbatim.** The 9-state machine, ≥40%
  invalidation calibration, HEREDOC commits, EXPECTED_TOOL_SCHEMA_SHA256 re-pin
  discipline, push-authorization gate, `make test` precondition all survived the
  conversion intact.
- **Phase-4 self-rectification discipline preserved.** The slash command's Phase 4
  section (line 587) explicitly says "Do NOT dispatch a sub-agent for Phase 4 unless
  the user explicitly requests delegation — and even then, the sub-agent must NOT be
  the same one that did Phase 2."
- **Severity-calibration table is in every critic file.** Adversary, infra-safety, and
  oss-scout each have their own table. The "inflate severity once and the table breaks"
  warning is reproduced consistently.
- **Slash-command frontmatter is minimal and correct.** Only `description` and
  `argument-hint` — both are documented frontmatter keys per the slash-commands docs.

## Suggested rectification order

1. F1 (memory filename) — touches all 5 agents, breaks the harness's auto-injection
   contract, easy to fix mechanically.
2. F2 (legacy SKILL.md drift) — single file, but the return-contract drift it
   documents could mislead the next agent.
3. F3 (tools: YAML list vs comma-separated) — verify empirically by spawning each agent
   and confirming tool restrictions are enforced; if not, convert to comma-separated.
4. F4 (token-budget duplication) — large but mechanical refactor; move common content
   to `agent-conventions.md` and shrink each agent file to ~150 lines.
5. F8 (settings.local.json stale entries) — 4-line fix.
6. F5 (grep -c finding counts) — small bash fix in slash command.
7. F6, F7, F9, F10, F11 — fold into a sweep.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
