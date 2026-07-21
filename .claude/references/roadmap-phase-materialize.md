# Phase 4 — MATERIALIZE

**Goal:** final-validate `plans/<slug>/roadmap.yaml`, populate links, flip
the roadmap live, and hand off to `/milestone-pipeline` — by offer, never by
invocation. GitHub materialization under `--github` is orchestrator-owned
(§4).

**Writes:** `links:` blocks and `status: active` in roadmap.yaml. Advances
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

### 4. GitHub materialization (`--github` only — orchestrator-owned)

`roadmap-to-github.py` is the single roadmap-to-GitHub path. The
ORCHESTRATOR runs it after the materializer returns — the phase agent has no
`--github` behavior and never runs `gh`. Sequence:

1. Resolve the repo: `gh repo view --json nameWithOwner -q .nameWithOwner`,
   falling back to parsing `git remote get-url origin`.
2. Run the converter dry-run (the default mode — it mutates nothing):

   ```bash
   python .claude/scripts/roadmap-to-github.py --repo <owner/repo> \
     --roadmap plans/<slug>/roadmap.yaml
   ```

3. Surface the printed plan — the dry-run IS the review surface — and ask:
   "Create these in `<owner/repo>`? [y/N]".
4. Only on explicit `y`: re-run with `--apply` (plus `--project N` to add
   items to Mission Control). Each `--apply` is a user-gated write,
   authorized per run.
5. Then `python .claude/scripts/roadmap-project-fields.py --owner <owner>
   --project <N> --roadmap plans/<slug>/roadmap.yaml --apply` — annotate-class
   field updates on the issues just created.
6. A successful apply also writes `plans/<slug>/github/issue-map.json` (the
   canonical id -> issue record) and prints the exact
   `--issues "<item-id>=<url> ..."` re-dispatch string. Re-dispatch the
   materializer with it to backfill `links.issue` — the normal path after
   every successful apply (links-only edit). For large roadmaps read the
   pairs from issue-map.json directly.

On anything but `y`, exit cleanly — nothing was mutated. The converter is
idempotent (hidden `<!-- roadmap-gh: <slug>/<id> -->` marker per issue), so
a re-run skips items that already exist. Legacy `plans/<slug>/github/<item-id>.md`
body files in consumer repos are inert historical artifacts — deleted
opportunistically, never synced. The directory's one live artifact is
`issue-map.json`, converter-owned, regenerated on every successful `--apply`.

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
| `--github` passed | orchestrator runs `roadmap-to-github.py` (§4) — dry-run review; `--apply` per-run gated |
| End of phase | **Offer** the pipeline handoff; anything but `y` exits cleanly |

## Hard rules

- **Validator must pass before anything else in this phase.**
- **No `gh` write verbs from the materializer *agent* (or any leaf
  agent).** Structure materialization is the orchestrator invoking
  `roadmap-to-github.py`; dry-run default; `--apply` only on explicit
  per-run user authorization.
- **No fabricated links.** Every `links.code` path verified to exist.
- **`status: active` at complete** — `complete` describes the authoring
  pipeline, not the roadmap's life.
- **Source code is off-limits** — this phase writes only roadmap.yaml
  fields.
