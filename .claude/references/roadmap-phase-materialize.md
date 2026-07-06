# Phase 4 — MATERIALIZE

**Goal:** final-validate `plans/<slug>/roadmap.yaml`, populate links, flip
the roadmap live, optionally emit GitHub issue bodies, and hand off to
`/milestone-pipeline` — by offer, never by invocation.

**Writes:** `links:` blocks and `status: active` in roadmap.yaml; body files
under `plans/<slug>/github/` when `--github`. Advances
`phase: sequenced → complete`.

## Step-by-step

### 1. Final validation gate

```bash
python .claude/scripts/roadmap-validate.py plans/<slug>/roadmap.yaml --json
```

Non-zero exit = STOP. Surface the error list; the upstream phase content
gets fixed first (gate-required). No partial roadmaps ship.

### 2. Populate links

Add `links:` only where a verifiable reference exists:

| key | contents | verification |
|---|---|---|
| `code` | repo paths an item will touch or extend | path confirmed via Glob/Grep — never guessed |
| `note` | Obsidian `[[wikilinks]]` / note paths (design notes, spike findings) | named note is real or explicitly "to be created by spike" |
| `url` | external references carried from `goal.evidence` | copied, not invented |
| `issue` | EXISTING tracker URLs only | issues created later are backfilled via the `--issues` re-dispatch |

Sparse and true beats dense and guessed.

### 3. Flip status

Surgical edit `status: draft` → `status: active`. Semantics: **phase
`complete` means the authoring pipeline is finished; the roadmap itself
stays `active`** while the work runs. `done` / `superseded` are set by hand
much later. Future plan changes go through the Regeneration protocol
(carry ids, tombstone drops) — not a fresh file.

### 4. GitHub issue bodies (`--github` only)

Emit one file per now-lane milestone, plus each parent epic once, to
`plans/<slug>/github/<item-id>.md`:

```markdown
# {title}

**Roadmap:** plans/<slug>/roadmap.yaml · **Item:** `<item-id>` · **Epic:** `<parent-epic-id>`
**Lane:** now · **Target:** {target_start} → {target_end}

## Summary
{summary / epic context}

## Acceptance
- [ ] {each acceptance string, verbatim}

## Depends on
- `{dep-id}` — {dep title}
```

**Bodies only.** The pipeline never runs `gh issue create` — the
orchestrator resolves the repo (`gh repo view --json nameWithOwner`), asks
the user "create N issues in <owner/repo>? [y/N]", and only on explicit `y`
creates them one at a time from these files. Conventional-commit style
titles are fine but not required; labels are the orchestrator's call.

### 5. Advance + handoff

```bash
python .claude/scripts/roadmap-init.py <slug> --advance complete
```

Re-validate after advancing. Then compose the offer (the orchestrator
surfaces it verbatim):

```
Roadmap complete: plans/<slug>/roadmap.yaml

Now-lane milestones:
1. <slug>-m1 — {title} (epic <slug>-e1)
2. <slug>-m2 — {title} (epic <slug>-e2)

Run /milestone-pipeline <slug>-m1 to start? [y/N]
```

List now-lane milestones in dependency order. NEVER auto-invoke —
slash-command-to-slash-command chaining removes the user gate; the user is
the orchestration layer.

### 6. What happens after (context, not action)

Execution progress is journal appends to `plans/<slug>/progress/agent.jsonl`
written by the milestone pipeline. Neither the materializer nor `/roadmap`
ever writes that file, and roadmap.yaml item `status:` never tracks
execution — the vault compiler folds plan ⊕ progress into the rendered
views. One writer per file.

## Auto-advance vs gate

| Condition | Action |
|---|---|
| Validator exit 0 | proceed |
| Validator exit non-zero | **STOP** — `gate-required` with the violations |
| `--github` passed | emit bodies; creation is orchestrator-gated per run |
| End of phase | **Offer** the pipeline handoff; anything but `y` exits cleanly |

## Hard rules

- **Validator must pass before anything else in this phase.**
- **No `gh` write verbs, ever, from the materializer.**
- **No fabricated links.** Every `links.code` path verified to exist.
- **`status: active` at complete** — `complete` describes the authoring
  pipeline, not the roadmap's life.
- **Source code is off-limits** — this phase writes only roadmap.yaml
  fields and `plans/<slug>/github/` bodies.
