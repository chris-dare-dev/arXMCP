---
handoff_kind: continuation
date: 2026-08-06
companion: HANDOFF-2026-08-06-ui-uplift-session-review.md
roadmap: plans/ui-uplift/roadmap.yaml
resume_target: any
tags:
- handoff/continuation
aliases:
- "ui-uplift — continuation handoff (2026-08-06)"
---

# CONTINUATION HANDOFF — ui-uplift (2026-08-06)

> Supersedes [[HANDOFF-2026-08-05-ui-uplift-continuation]]. That pair is still accurate for the
> work it covers; this one carries everything after it, including a REVERT and two closed issues.
> Companion review handoff: [[HANDOFF-2026-08-06-ui-uplift-session-review]].

## 1. Current state (as of this handoff)

`origin/main` = **`e8f149d`**, working tree clean, 0 unpushed.

| Milestone | State | Note |
|---|---|---|
| m1–m10, m12, m13 | **done** | m12 and m13 fully rectified, gates exit 0 |
| **m11** | **UNSTARTED — reverted** | shipped as `3338b43`, critiqued DO-NOT-SHIP, reverted at `a2f7cad` |
| m14–m23 | planned | m14 is next by the roadmap's own ordering |

Issues: [`#382`](https://github.com/chris-dare-dev/arXMCP/issues/382) CLOSED (round 2),
[`#383`](https://github.com/chris-dare-dev/arXMCP/issues/383) CLOSED (`d53e284`).

Full suite: **the documented 8 environment-bound failures, no new ones** (5 latexml sandbox
needing `bwrap`, 1 sandbox-wiring, 1 `WindowsPath`-on-macOS, 1 kuzu-dir state). `ruff check .`
clean. `roadmap-validate.py` OK.

## 2. RESUME HERE — a manual browser pass over `/ui/`

**DONE 2026-08-06. Every item below was executed against the running server; nothing here is
outstanding.** Kept as the record of what was checked and how, because one item found a defect
and one of my own interim findings turned out to be a measurement artifact.

**USE A MutationObserver, OR CAPTURE AT DISPATCH — NEVER `setTimeout` THEN READ.** Three times in
one session a `setTimeout`-and-read showed an error block empty when it was not, and one of those
nearly got written up as "the #383 fix does not work". This is the single most useful thing on
this page for anyone re-verifying htmx behaviour.

`make` is not on PATH here — start it through the preview pane instead (recipe in §6), or:

```bash
/Users/chris.dare/Library/Python/3.9/bin/uv run --directory ~/Personal/SourceCode/arXMCP \
  python -m server.main    # then http://127.0.0.1:7733/ui/
```

Check, in order:

1. **Error surfaces now work at all.** Trigger a 4xx on any form (rename to an invalid value,
   paste a malformed arXiv URL). Before `d53e284` **no error had ever appeared** — all twelve
   `hx-on` handlers bound events htmx never dispatched. This is the single highest-value check
   in the list, because it is the first time these paths have run.
2. **Forms reset on success**, and the index's `#notebooks-empty` row disappears when the first
   notebook is created — same root cause, never worked before.
3. ~~**m13's empty error blocks**~~ — **DONE 2026-08-06** (`e8f149d`). Measured on the running
   server: all six report `display:block`, height 0px, padding 0px, transparent background while
   empty. m13 finding **M2** is closed and that milestone's gate now exits 0 with 0 deferred.
4. ~~**m13's ingest poll**~~ — **MECHANISM VERIFIED.** Across real poll cycles `#ingest-live` is
   the same node with zero mutations while `#ingest-status` is replaced. That is the structural
   precondition for silence on an unchanged re-render. **The audible half still needs a screen
   reader** — it is the only remaining unverified claim in the programme.
5. ~~**m10's abstract disclosure**~~ — **VERIFIED against 25 live arXiv candidates.** Summary 114
   chars, body 880, `summary === body` is **false** (the defect m10 fixed), ends with an ellipsis,
   and is a genuine prefix of the body rather than a paraphrase.
6. **Narrow viewport — FOUND A DEFECT, filed as arXMCP#399.** 323px of horizontal overflow at
   375px: the absolute LanceDB path in `dl.meta dd` has no break opportunity. Pre-existing,
   m8-era, outside every milestone's scope. `.table-wrap` works and simply does not cover the
   masthead.

## 3. Definition of done for the in-flight milestone

There is no in-flight milestone. m11 is unstarted with a full critique already on file.

## 4. Remaining epics / milestones

**m11 (`ui-uplift-m11`) — re-do from scratch, do NOT resume from the reverted branch.**

Read `.claude/notes/milestones/ui-uplift-m11/critique/` first — 27 findings, two independent
CRITICALs, verdict DO-NOT-SHIP. The research synthesis in that directory is still valid and is
worth more than the code that was reverted. Three things it establishes:

- **The count is three, not four.** The roadmap title/summary were corrected and that correction
  SURVIVED the revert on its own evidence (checked at the discovery-era commit `0c95720`).
- **The papers empty state has an un-cleared bug.** Nothing removes it when a paper is added by
  any of the three paths. The reverted branch fixed this with
  `#papers-empty:has(~ tr) { display: none }`; that idea is sound and independent of everything
  that went wrong, and it does not depend on `hx-on` at all.
- **AC#1's control half needs re-deciding, not re-implementing.** The narrowing that shipped
  rested on "the papers empty state is the one case with no other reachable control." **That is
  false** — the Manage disclosure renders `open` whenever `latest_run` is not `success`, i.e. on
  exactly every first-run notebook, which is exactly when the empty state shows. Both Add forms
  are visible together, so BAN-9's duplicate-CTA objection applies. The AC narrowing was reverted
  with the code; the count correction was not.

**m14 (`ui-uplift-m14`)** — native `<dialog>` destructive confirm. Independent of m11.

## 5. Cross-cutting follow-ups (landmines you'll trip on)

- **`hx-on` syntax.** `::` ALREADY means `htmx:`. Write `hx-on::after-request`, never
  `hx-on::htmx:after-request`. `tests/test_ui_hx_on_event_names.py` enforces this by deriving
  htmx's normaliser AND its event vocabulary from the vendored bundle; it fails on the doubled
  prefix with the cause named. Do not hand-list events there — the derivation is the point.
- **Guards that assert presence do not assert behaviour.** This is the session's recurring
  defect and it appeared five separate times (m8's exemption dict, six of m12's findings, m6's
  allow-listed "historical" numbers, m7's false CSS claim, and #383). Before writing a guard,
  ask what mutation should make it fail, then inject that mutation and confirm it does.
- **First-match guards.** Several tests locate "the add-paper form" with `matches[0]` or the
  first DOM hit. Adding a second form for the same endpoint silently redirects five of them —
  this is m11's CRITICAL C1. If you add a form, grep for guards that resolve by first match.
- **m12's HARD CONSTRAINT is enforced now.** No swap may target the Manage `<details>` or any
  ancestor of it, or the server-rendered `open` snaps back every 2s.
  `TestStructuralInvariantsHoldInTheRenderedTree` fails loudly on the wrong shape.
- **The `.claude/notes/milestones/.lock`** is gitignored runtime state and goes stale when a
  session dies. Clear with
  `bash .claude/scripts/milestone-pipeline-init-state.sh <id> --release-lock`.
- **Roadmap anchors are `path#<literal>`, not line numbers.** `tests/test_roadmap_links_resolve.py`
  is strict for `plans/ui-uplift` (every anchor resolves, no line anchors) and a ratchet for the
  other eleven roadmaps (46 unresolved anchors, 3 dependency inversions — lower, never raise).

## 6. Environment / resume notes (how to reconnect)

- `make` is **not** on PATH on this box, and `python`/`python3` do not resolve the project venv.
  Use `/Users/chris.dare/Library/Python/3.9/bin/uv run --extra dev python -m pytest …`.
  Plain `uv run` without `--extra dev` intermittently loses `pytest`.
- **Discovery needs `contact_email` in the OPERATOR-SETTINGS DB, not an env var.**
  `get_contact_email()` reads `get_setting("contact_email")` from `var/arxmcp/cache/notebooks.db`;
  `server/config.py` never mentions `ARXMCP_CONTACT_EMAIL`. Two docs are wrong about this: the
  502 message suggests `export ARXMCP_CONTACT_EMAIL=…` (that path does nothing) and CLAUDE.md §9
  says the server REJECTS the var (no such check exists). Without it, Discover 502s by design —
  the arXiv TOS §3 politeness contract refusing to make an unattributed call.
- **A Lean toolchain IS available** and was used to verify #382 against real Lean:
  `~/.elan/bin/elan run leanprover/lean4:v4.29.0 lean <file>`. There is no default toolchain, so
  the `elan run <toolchain>` form is required. `ARXMCP_LAKE_PATH` / `ARXMCP_LEAN_REPL_DIR` are unset.
- **A browser harness DOES exist, and this handoff originally said it did not.** The correction
  matters more than the recipe: the in-app preview pane renders `file://` URLs as static
  snapshots, and I generalised that one failure into "no browser is available" — which then
  justified deferring m13's M2 and left four milestones' visual claims as derivation. It was
  wrong. Point the pane at a REAL SERVER and everything works:

  ```
  # .claude/launch.json in the workspace root (/Users/chris.dare/Personal/SourceCode/)
  # — NOT arXMCP/.claude/launch.json; preview_start resolves names from the primary
  # working directory, so an entry in the repo's own file is not found.
  {"name": "arxmcp-ui",
   "runtimeExecutable": "/Users/chris.dare/Library/Python/3.9/bin/uv",
   "runtimeArgs": ["run", "--directory", "/Users/chris.dare/Personal/SourceCode/arXMCP",
                   "python", "-c", "<sets ARXMCP_BOOTSTRAP_MODE=1, pops "
                   "ARXMCP_CONTACT_EMAIL, runs server.main>"],
   "port": 7733}
  ```

  Then `preview_start {name: "arxmcp-ui"}` and navigate to `http://127.0.0.1:7733/ui/`.
  `screenshot`, `read_page`, `javascript_tool` and `read_network_requests` all work against it.

- **Sample htmx results with a MutationObserver, not a timeout.** Two reads of `#create-error`
  came back empty after a real 409 and nearly got written up as "the #383 fix does not work";
  both were races against the request. The observer caught the actual write.
- Contrast maths: `tests/_ui_color.py` (`contrast_ratio`, `alpha_over`, `load_tokens`,
  `resolve_color`). Regenerate the artifact with `python -m tests.test_ui_contrast --update`.

## 7. Key values you'll need (copy-paste reference)

```
origin/main                 d53e284
m11 revert                  a2f7cad   (reverts 3338b43)
m11 critique                .claude/notes/milestones/ui-uplift-m11/critique/{adversary,frontend}.md
#382 round-2 fix            99c856b
#383 fix + guard            d53e284
gate a milestone            uv run python .claude/scripts/milestone-pipeline-findings.py gate <id>
roadmap validate            uv run python .claude/scripts/roadmap-validate.py plans/ui-uplift/roadmap.yaml
release a stale lock        bash .claude/scripts/milestone-pipeline-init-state.sh <id> --release-lock
```
