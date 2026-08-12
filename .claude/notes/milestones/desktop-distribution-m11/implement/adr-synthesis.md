# Implement synthesis (scoped first half — ADR only) — desktop-distribution-m11

**Scope of this dispatch:** one decision record. No Rust, no Python, no dependency, no
pointer artifact, no first-run UI, no test or Makefile change. The implementation is a
separate dispatch after owner review.

**Artifact:** `.claude/docs/adr-desktop-data-root-selection.md` (Status: **Proposed**,
owner approval PENDING — deliberately not self-accepted).

## The decisions settled

**Decision 1 — pointer persistence.** A single UTF-8 JSON file at
`<platform_data_root()>/data-root.json` (`~/Library/Application Support/arXMCP/` on macOS,
`%LOCALAPPDATA%\arXMCP\` on Windows, `$XDG_DATA_HOME/arXMCP/` on Linux), derived by the
**same two functions m10 already pinned to each other** — `_platform_data_root`
(`server/application_paths.py:81-89`) and `platform_data_root` (`main.rs:210-233`).

The load-bearing reframing: the criterion is **not** "outside the data root" but *the
pointer's location is a pure function of the environment, never of its own content*. Under
that criterion the chosen location is correct even though it sits inside the **default**
root when the operator keeps the default. Reusing the existing function pair means the new
parity surface is ordering and parse rules only — no second pair of path functions to drift.

Insertion points, both measured at `ea06449`, not inferred:
- Python: behind the **existing** `platform_default: Callable[[], Path]` parameter
  (`:120`, used at `:141`), inside the `installed`-mode branch only. So `ARXMCP_DATA_DIR`
  and an explicit `root=` still win, and **source mode is byte-identical** — no existing
  test changes behavior. The Python delta is a new resolver, not a new seam.
- Rust: in `self_authored_plan`, ahead of `platform_data_root(lookup)` at `:518` — still
  inside `load_plan()` (`:667`), still before `tauri::Builder::default()` (`:716`).

Three-way read rule, identical in both languages: **absent** → first run, take the default
and prompt (the only silent fallback); **present but unreadable/unparseable/non-absolute** →
refuse loudly, naming the pointer's path; **present, target missing** → report, never
re-default (AC6). The refuse-rather-than-fall-back argument is written out: a corrupt
pointer is *evidence a choice was made*, and defaulting past it starts a second empty corpus
while the real one sits on another volume — data divergence, quieter than data loss.

Sandbox note recorded as required: zero `entitlement`/`app-sandbox` matches under
`apps/desktop/**` (re-measured), so security-scoped bookmarks are the wrong mechanism — and
**adopting sandboxing later invalidates Decision 1's sufficiency and must re-open this ADR
before it lands**.

**Decision 2 — picker presentation.** `main()`'s startup ordering is **not** restructured in
m11; the picker is a native dialog invoked before `load_plan()` with no `tauri::App`.
Restructure-vs-dependency was weighed on the ordering's real cost: single-instance lock
placement, the barrier-env hook, the plan duality and `test_hide_window`'s smoke gating all
sit downstream of the resolution point, and m6's fault matrix and m10's self-authored-launch
module were hardened against *that* ordering — so restructuring invalidates a premise rather
than adding code.

**Deliberately, the ADR names no crate.** brief-2's `rfd` claim has **no URL and no hash** in
the evidence base — only a measured absence from the repo (I confirmed: zero `rfd` matches
under `apps/desktop/**/*.{toml,rs}`). It is logged as ledger row **E7 — NOT ESTABLISHED**.
The ADR fixes the *shape* (pre-`load_plan()`, no `App`, `=`-pinned like all 8 existing direct
pins) and hands the implementation four obligations: verify no-`App` invocability against the
crate's own docs, verify the macOS main-thread modal requirement (unverified here), review
the Linux backend commitment (GTK vs XDG portal — materially different, no runner), then pin
or **escalate** to R6.

**Decision 3 — free-space honesty.** The measurement is reported as a **lower bound** and the
refusal says so; either AC4 arm (headroom + `shutil.disk_usage`, or a purgeable-excluding
platform call) satisfies it. Adopting the native call explicitly does **not** license dropping
the phrasing — brief-2 found no source claiming any call guarantees a write will succeed.

## Also recorded, because the implementation needs them bounded

- **Cross-language parity obligation** — its own section, with three named rows the
  implementation owes (location parity across the existing env matrix; three-way-rule outcome
  class parity; precedence parity), and the explicit statement that without them m10's
  guarantee narrows to "only the default path is proven to agree" **with every gate still
  green**. m10's one deliberate divergence (Python `Path.home()` fallback vs Rust refusal) is
  inherited unchanged and must not widen.
- **"What this ADR deliberately does NOT decide"** — 8 items: JSON schema keys, the crate,
  the free-space mechanism, the free-space number, the adoption-detection predicate, message
  wording, test/marker/Makefile layout, and whether m11 also takes m15's inherited launch
  proof (AC9's ~4.6 GB `requires_bundled_model` cost — a scope call for the owner, not a
  mechanism decision).
- **"How this ADR gets amended"** — per-decision revisit triggers, written so a
  measurement-contradicts-decision escalation (m15's Decision 2 → 2a) is the expected path
  rather than an exception. Supersede in place, retain the killed text unedited.

## Rejected alternatives, with evidence

R1 `OperatorSettingsStore` (circular, measured) · R2 security-scoped bookmarks (solves App
Sandbox's problem; none exists) · R3 `CFPreferences`/`NSUserDefaults` — **the strongest
loser**, vendor-documented for exactly this, real advantages recorded, lost on Rust-side FFI
and on being macOS-only, which would owe the parity obligation over *two* implementations ·
R4 env var alone · R5 launch-plan-seed JSON · R6 restructure + `tauri-plugin-dialog` (rejected
*for m11*, recorded as the named revisit path, orthogonal to Decision 1) · R7 `/ui/` console
(measured: root is fixed before it can render).

## Evidence discipline

Ledger has 8 rows with per-row status. E1/E2/E3/E6 documented-vendor; E4 community-measured
single author; E5 community corroboration of mechanism not magnitude; E6 flagged single case,
not a census; **E7 not established at all**; E8 measured at `ea06449` by re-reading the repo
rather than quoting the briefs. An explicit "NOT established by anything above" paragraph
names three things (no guaranteed-write byte count; `rfd` in particular; the modal
main-thread precondition) and Decisions 2 and 3 are written so none is assumed.

## What I deliberately left open

Everything in the 8-item "does NOT decide" list, and the owner acceptance itself. I did not
prototype, add a dependency, or touch source — per the dispatch's scope bound.

## What the implementation dispatch now needs to do

1. Get owner acceptance recorded in the ADR's approval section first.
2. Verify-then-pin the picker crate (E7's gap) **or** escalate to R6. Do not pin on "it works
   on this box".
3. Build the pointer: JSON schema, atomic write, absolute-path normalization ahead of write,
   the three-way read in both languages at the two named insertion points.
4. Ship the three parity rows **in the same diff** as the override read. This is the item
   most likely to be silently skipped with all gates green.
5. Free-space gate with lower-bound phrasing; adoption detection over existing primitives
   (`NotebooksStore`, `_safe_read_corpus_version`, corpus-version / kuzu markers).
6. Re-run the m1 traversal suite and the m2 write-containment regression against
   operator-chosen roots (Unicode, whitespace).
7. Settle AC9 scope (inherited launch proof) with the owner before sizing.
8. Set `allow_large_diff` at init — research re-rated this `L` (~1,200 LOC / ~14 files);
   retrofitting it produced an H2 finding in both m8 and m10.

## Files touched

- `.claude/docs/adr-desktop-data-root-selection.md` — the decision record (new).
- `.claude/notes/milestones/desktop-distribution-m11/implement/adr-synthesis.md` — this file.
- `.claude/agent-memory/milestone-implementer/lessons.md` — one appended line.

## Branching note

CLAUDE.md §4.1 says all work lands on `main`. **Mechanically unavailable from this worktree:**
`git checkout main` is refused while the shared checkout holds it (the confirmed m7/m10
lesson). The commit landed on the worktree branch `worktree-agent-a6d6deef0f41e9533` at base
`ea06449`, for the orchestrator to fast-forward. §4.4 honored: no push.

## external_writes_required

- `git push origin main` — inherited from the research synthesis; **not performed** (§4.4,
  and outside this agent's scope bounds).

## Test deltas

None. ADR-only diff; no test file added or changed.

## Check gate results

- `tests/test_desktop_notarization_claims.py` + `tests/test_desktop_support_floor.py`:
  **PASS** (exit 0, 54 passed / 2 skipped). This is the gate that matters here —
  `test_desktop_notarization_claims.py:164` puts `.claude/docs/**.md` in its scan set, so the
  new ADR **is** covered by it. (m9's `test_desktop_support_floor.py` scanner does **not**
  cover `.claude/docs/`; it was run because it is the sibling prose guard, not because it
  guards this file.)
- `ruff check .`: **SKIP** — no `.py` file touched.
- Full `make test`: **SKIP** — ADR-only diff touches no code path; the two prose guards above
  are the ones whose scan sets include the changed file.
- `git status --porcelain` after commit: clean.
