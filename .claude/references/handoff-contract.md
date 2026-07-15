---
project: claude-registry
type: reference
status: active
authorship: agent-generated
tags:
- project/claude-registry
- type/reference
- authorship/agent-generated
- type/handoff
---

# Handoff contract — continuation + review session handoffs

The single source of truth for session-handoff documents in the Personal Projects fleet:
filename grammar, frontmatter schema, and both body templates. The `/handoff` skill authors
against this contract. Provider-neutral — works identically from Claude Code, Codex, or OpenCode.

This is the fleet re-derivation of the platform registry's handoff contract, rebased onto the
`roadmap/1` substrate (`plans/<slug>/roadmap.yaml`). No cloud-provider-specific reviewer, no
central-workspace `plans/` — each repo owns its own `plans/<slug>/`.

## 1. The two kinds

| Kind | Audience | Purpose | Filename suffix |
|---|---|---|---|
| **continuation** | The next builder session (any provider) | Resume exactly where this session stopped: state table, RESUME-HERE step, gates, environment reconnect notes | `-continuation.md` |
| **review** | A high-effort reviewer session — a **Fable 5** or **Opus** session at high effort | Independent principal-engineer audit of everything shipped across the session's milestones: correctness, safety, honesty of "done" claims, coding practices, program direction | `-session-review.md` |

Generate **both** at the end of any session that shipped milestone-scale work (commits landed
across ≥1 milestone); generate only a continuation for mid-stream or light sessions. The two
documents cross-link via the `companion:` key and a body link. A review handoff without a
companion continuation is a smell — the reviewer finds problems; the next builder needs somewhere
to resume from.

## 2. Storage + filename grammar

- **Location:** `plans/<slug>/` in the consuming repo — co-located with that program's
  `roadmap.yaml`. `<slug>` is the roadmap slug (`schema: roadmap/1` → `slug:`).
- **Filename:** `HANDOFF-<YYYY-MM-DD>-<slug>[-<detail>]-<continuation|session-review>.md`
  - `<detail>` is optional scope info (e.g. `-e5m2`); keep the suffix literal.
- Handoffs are program artifacts that live beside the roadmap (like the roadmap itself). Whether
  to commit them is the user's call — do not push them without confirmation.
- **One session, one date, one slug → at most one continuation + one review.** Supersede by
  writing a newer-dated pair, never by editing history.

## 3. Frontmatter schema

Keys marked (R) are review-only, (C) continuation-only. Everything else applies to both. The
first block (`project`/`type`/`status`/`authorship`/`tags`) is the fleet house frontmatter the
Obsidian vault tooling claims on (`type: handoff` → the Handoffs base); the handoff-specific keys
below it are machine-readable hooks for resume/review.

```yaml
---
project: <roadmap-slug>          # == roadmap.yaml slug; Bases group by this
type: handoff                    # EXACTLY this — the Handoffs base filters note.type == "handoff"
status: complete                 # the handoff doc itself is finished when written
authorship: agent-generated
handoff_kind: continuation       # continuation | review — must match the filename suffix
date: 2026-07-13                 # == the date in the filename
companion: <other-handoff-filename.md>   # the paired handoff; omit only if none exists
roadmap: plans/<slug>/roadmap.yaml       # repo-relative path to the roadmap
resume_target: fable             # (C, optional) fable | opus | any
reviewer_target: fable           # (R) fable | opus — the high-effort reviewer session
review_status: requested         # (R) requested | in-review | verdict-received | closed
milestones_covered:              # (R) roadmap milestone ids covered by this review
  - <slug>-m1
  - <slug>-m3
tags:
  - project/<slug>
  - type/handoff
  - authorship/agent-generated
  - handoff/<continuation|review>
  - review/requested             # (R)
aliases:
  - "<slug> — <kind> handoff (<date>)"
---
```

**Legacy values to avoid:** `type: session-handoff` or a `handoff-kind:` (hyphen) key make the
handoff invisible to the vault Handoffs base — never use them.

**Secrets rule:** handoffs regularly carry reconnect context (tokens, profiles, endpoints). Refer
to secrets **by store path / env-var name only** — never a literal value.

## 4. Body template — continuation

```markdown
# CONTINUATION HANDOFF — <slug> (<date>)

> **Audience:** a fresh <resume_target> session picking up <slug>. The companion review handoff
> ([[<companion>]]) covers *what shipped and why* — THIS doc says **exactly where to resume and
> what's left**. Roadmap: `plans/<slug>/roadmap.yaml`.
>
> **Program goal:** <one sentence — the roadmap's goal.objective>.

## 1. Current state (as of this handoff)

| Milestone | Status |
|---|---|
| <slug>-mN — name | ✅ SHIPPED / ⬜ ← RESUME HERE / ⬜ next |

<One line per load-bearing live fact: what runs where right now, what is committed vs unpushed.>

## 2. RESUME HERE — <the exact next milestone/step>

**Goal:** <one sentence>.
<The facts already decided. The exact commands/diffs to run, gates included ("X is a GATED
external write / push — present and confirm before doing it").>

## 3. Definition of done for the in-flight milestone

<Closure checklist: critique pass clean, acceptance criteria met, roadmap progress journal
appended (plans/<slug>/progress/*.jsonl), memory/notes updated.>

## 4. Remaining epics / milestones

<Per epic: one short paragraph — scope, the gate to advance, carry-forward gotchas.>

## 5. Cross-cutting follow-ups (landmines you'll trip on)

<Numbered. Things NOT in this program that will bite a fresh session.>

## 6. Environment / resume notes (how to reconnect)

<Toolchains, venvs, service endpoints, tokens (by location, never value), pipeline state paths,
`/milestone-pipeline --resume` invocations, worktree state.>

## 7. Key values you'll need (copy-paste reference)

    <key>: <value>        # paths, ids, pins, command names — NO secrets

*Full review of what shipped: [[<companion>]].*
```

## 5. Body template — review

```markdown
# HANDOFF (REVIEW) — <slug> session, <date>

> **Audience:** a high-effort <reviewer_target> review session. **Goal:** independently scrutinize
> everything shipped this session — correctness, safety, whether the "done" claims are honest, the
> coding practices, and the program direction — against the diffs (and live state where
> applicable). This is a REVIEW handoff (find problems); the companion continuation handoff
> ([[<companion>]]) is for the next builder. Roadmap: `plans/<slug>/roadmap.yaml`.

## 0. TL;DR — what this session did

| # | Work | Repo(s) | Key SHAs (branch) | State |
|---|---|---|---|---|
| 1 | <milestone / work item> | <repo> | <shas> | SHIPPED / LIVE / DORMANT |

<One paragraph: the session narrative, and which items are live-behavior changes vs dormant
(flag-off / not-yet-activated) mechanisms.>

## 1..N. <One section per work item>

<What was done and why. Design decisions with their rationale. Files + SHAs.>

### What to SCRUTINIZE
<The specific claims the reviewer should try to break — per item. MANDATORY for every work item.
A review handoff that doesn't tell the reviewer where the bodies might be buried is marketing,
not a review request.>

## N+1. Cross-cutting durable gotchas + decisions

<Numbered — everything a reviewer needs to avoid false positives (known-accepted tradeoffs,
platform invariants, push-order constraints, suppressions).>

## N+2. Verification evidence (as of handoff)

<Tests/CI/live-verify status per repo, including anything still in flight. Be honest about what
was NOT verified vs what was claimed.>

## N+3. How to review (repro + response contract)

- **Diff access:** for each repo — path, branch, SHA range (`git log --oneline <from>..<to>`).
- **Review axes:** (1) correctness/safety of each change; (2) honesty of the done-claims against
  evidence; (3) coding practices (idioms, tests, blast radius); (4) program direction — is the
  roadmap's next step still right given what shipped?
- **Calibrate the verdict to the milestone's state:** a dormant/flag-off mechanism is judged on
  "safe to activate later + honestly labeled", NOT on "not yet activated".
- **Response format:** per-finding — severity (CRITICAL/HIGH/MED/LOW), the claim it refutes,
  evidence (file:line / command output), suggested disposition. End with an overall verdict:
  SHIP / SHIP-WITH-FIXES / NO-GO, scoped per milestone.
```

## 6. Notes

- **The roadmap is not edited by a handoff.** In this fleet `roadmap.yaml` has one class of
  writer — the roadmap phase agents (plan structure) — and execution progress is journal appends
  under `plans/<slug>/progress/*.jsonl`. A handoff *describes* state; it never mutates the roadmap
  or a journal. (The platform registry's review-checkpoint-into-roadmap step is deliberately NOT
  ported for that reason.)
- **Vault surfacing is automatic where present.** On a machine with the Obsidian vault above the
  repos, a detached hook stamps frontmatter and links the handoff into the Handoffs base from the
  `type: handoff` frontmatter — the skill's only job is to emit the correct frontmatter (§3).
  Machines without the vault still get a well-formed markdown handoff.
- Not for durable lessons/preferences (that's memory) and not for advancing a milestone (that's
  `/milestone-pipeline`). Handoffs are session-boundary artifacts.
