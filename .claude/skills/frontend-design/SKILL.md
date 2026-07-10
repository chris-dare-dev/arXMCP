---
name: frontend-design
description: "Art-direction-first workflow for BUILDING or RESTYLING frontend surfaces — produces a visual thesis + 3 divergent directions + a design-language contract BEFORE any code, then implements against the anti-cookie-cutter ban list and self-scores the result. Use when the user says 'design this page/app', 'make this look premium/sleek/modern/not generic', 'restyle X', 'this looks like every AI dashboard', or before any net-new UI surface. NOT for discovery-scale audits producing a ranked report (use /frontend-uplift) and NOT for pure logic/bug work with no visual intent."
allowed-tools: Read, Grep, Glob, Bash, Edit, Write, WebFetch, WebSearch, Agent, AskUserQuestion
type: skill
status: active
tags:
  - type/skill
  - status/active

---

# Frontend Design — thesis before pixels

You are about to do **design work**, not component assembly. The failure mode this skill exists to
prevent: technically clean UIs that ship as the generic AI-generated dashboard — dark navy shell,
neon accents, sidebar + equal card grid, icon tiles, Inter + Lucide + shadcn defaults untouched
(the desktop-app equivalent: an untouched Qt/Fusion default palette, gray group boxes, stock
widgets nobody restyled). Correct ≠ directed. This workflow forces an art-direction decision first,
then holds the implementation to it.

## Arguments

- `$ARGUMENTS` — free-form scope: a surface ("the Security tab"), an app ("the settings-window
  login"), or a brief ("make the getting-started page feel like waabi.ai"). Empty = infer scope
  from the conversation; if genuinely ambiguous, ask ONE question.

## Step 0 — Load the canon, then the repo thesis (MANDATORY, before any opinion)

First read **in full** the product-neutral canon: `.claude/references/frontend-design-language.md`.

That file is canonical for: the anti-reference (§1), the six mandated deliverables (§2), surface
classes (§3), the REF-1..9 reference library (§4), the BAN-1..15 ban list (§5), the S-2
premium-instrument spec (§6), the S-1 experiential spec (§7), the direction seeds + divergence
axes (§8), the cookie-cutter rubric (§10), the four questions (§11), the font kits (§12), and the
**evidence tiers + band→outcome map (§14 — the ship gate's semantics)**. It is product-NEUTRAL:
it ships no house thesis. Do not restate it from memory — read it; it evolves.

Then read the **repo-local house-thesis overlay** under `.claude/references/frontend-uplift/`
(look for `<repo>-design-system.md`, else `design-system.md`). That overlay carries THIS product's
thesis, its anti-references, and its surface map — the product-specific half the canon deliberately
omits. **If the repo has no such overlay, STOP and offer to author one** (Steps 0–2 produce exactly
its contents) — never invent a house thesis silently.

For motion specifics also consult `.claude/references/frontend-uplift-motion-vocabulary.md`
(`MOT-*`, surface model §0) and `.claude/references/frontend-uplift-experiential-motion.md`
(`EXP-*`, recipes) as needed. For library / font / exemplar **currency**,
`.claude/references/frontend-uplift-source-registry.md` §0 owns the freshness protocol and the
mandatory live-search triggers T1–T4 (consumed in Step 2.5 below).

## Step 1 — Ground in the current state

- Identify the frontend project + stack and its token surface: for a web app (Next.js / SvelteKit /
  React-Vite), `package.json`, Tailwind config, token/theme files, component dirs; for a PySide6/Qt
  desktop app, the `.qss` stylesheets, `QPalette` setup, and `.ui`/resource files; for a Jinja2+htmx
  server-rendered console, the templates + CSS.
- If the surface can be run (dev server, or the desktop app itself), screenshot the surfaces in
  scope (preview tools) — primary evidence.
- **Score the current state** with the §10 cookie-cutter rubric. State the score and which BAN-N
  tells are present. (A score ≥6 means the problem is direction, not polish — say so.)

## Step 2 — Produce the six deliverables (design-language §2)

1. **Visual thesis** — one sentence, product-specific (§2 swap-test). Start from the repo-local
   house-thesis overlay (Step 0) unless the user overrides it; if you just authored the overlay,
   this IS its thesis line.
2. **Three divergent directions** — seed from §8 (D-A Precision Instrument / D-B Editorial Cockpit /
   D-C Cinematic Threshold) but make them THIS product's; each with concept, applies/must-not-apply,
   5 traits, 5 bans, risk notes.
3. **Negative references** — the BAN-N tokens this work removes; link current screenshots as
   anti-references where captured.
4. **Surface map** — every route/view/window in scope tagged S-1 / S-1m / S-2.
5. **Design-language contract** — the chosen direction as tokens BEFORE code: type kit (§12,
   self-hosted or bundled), scale, spacing rhythm, material + accent + semantic colors (OKLCH),
   border/elevation method, icon treatment, data-viz rules, motion budget per surface, voice rules.
6. **Cookie-cutter score, projected** — what the end state should score (target ≤2).

**Divergence is a hard requirement (canon §8):** the three directions must differ on ≥4 axes
(navigation model · silhouette · typography posture · geometry · material/depth · color
temperature · density · interaction grammar) — retyping or recoloring one shell is one
direction, not three. Consider the §8 product mental-model seeds (Sovereign Ledger /
Operational Cartography / Causal Flight Recorder), not just D-A/B/C.

**Program scope: render before choosing (round 3 — exploration needs pixels).** Produce a
same-content **grayscale composition plate** per direction: one self-contained HTML file per
direction under `<repo>/.claude/notes/frontend-designs/<slug>/plates/`, real labels and data
from the actual surface (never lorem ipsum), no color (HTML is only the plate *medium* — it
studies composition even when the target ships as a Qt window or an htmx partial), plus a 375px
mobile variant of the recommended one where the surface has a small form factor. Screenshot the
plates when a preview server is available. If the plates could be mistaken for each other, they
are not divergent — redo them. Small single-surface restyles may substitute a tight structural
sketch per direction (regions + hierarchy in words), but say so explicitly.

**Interactive session:** present the thesis + three directions (plates attached, recommended
one first) via AskUserQuestion and let the user pick before production code. **Autonomous
run:** pick the strongest defensible direction, state it and why in one paragraph, proceed.

Keep the deliverables concise — for a single-surface restyle this is ~half a page, not a document.
Persist them: small scope → a comment block in the PR/commit body or the conversation; program scope
→ `<project>/docs/design-direction-<slug>.md` so later sessions inherit the thesis (and fold the
chosen thesis back into the repo overlay under `.claude/references/frontend-uplift/`). **Persistence
is gated, not optional** — the Step 4 scorecard carries a `Persisted:` field and the gate script
refuses `(pending)` and refuses `commit-body` on program scope.

## Step 2.5 — Currency check (before implementing the contract)

The canon and registry are dated snapshots (each section carries a `Last-verified` stamp).
Read **`.claude/references/frontend-uplift-source-registry.md` §0** and apply its triggers **T1–T4**
— live research is MANDATORY when one fires, skipped entirely otherwise (a restyle that only
recomposes existing tokens does zero web calls). The trigger definitions live ONLY in §0 —
in brief: T1 off-registry exemplar/framework named · T2 new dependency (library/font not in the
target project's manifest — `package.json`, `pyproject.toml`, etc.) · T3 stale stamp on a section
you rely on · T4 entry contradicts observed reality. Whoever verifies, updates the stamp (§0).

## Step 3 — Implement against the contract

- Tokens first: encode the contract as design tokens before components — CSS variables / Tailwind
  theme on web; a `.qss` + `QPalette` token layer for PySide6/Qt; CSS custom properties for the
  Jinja2+htmx console. Every color/duration/space in code references a token.
- Restyle structurally, not cosmetically: kill BAN-2/3/5/13 patterns by *recomposing* (lede module,
  editorial sections, authored chrome) — recoloring a card grid is still a card grid.
- Surface dialect discipline: S-2 gets §6 (instrument language — no spectacle); S-1/S-1m may get §7
  (one cinematic idea, fully executed, with fallbacks). Never let threshold craft leak into the
  working UI.
- The standing locks still bind on the surfaces they apply to: WCAG 2.2 AA, `prefers-reduced-motion`,
  and dark/light parity everywhere; bundle budget, RSC compatibility, and self-hosted fonts (no
  runtime font CDN) on web; startup-render budget and bundled (never network-fetched) fonts on
  desktop.

## Step 4 — Score, independent-score, gate, prove

The old shape ("re-score yourself, ≥3 = not done") was a self-graded prose gate — the implementer
scoring its own work with no artifact and no enforcement (critique R-4). The gate is now a script
and the second scorer is not you.

```bash
SC_DIR="<repo-root>/.claude/notes/frontend-designs/<slug>"   # run-scoped, local-only (gitignore .claude/notes/ — never committed)
mkdir -p "$SC_DIR"
python3 .claude/scripts/frontend-design-check.py template --slug <slug> > "$SC_DIR/scorecard.md"
```

1. **Self-score** the implemented result into the v2 scorecard — BOTH halves: the 13
   anti-pattern tells (1/0/UNSCORABLE) AND the 8 Directed Quality dimensions (0–4; §14 — task
   clarity, priority fidelity, decision integrity, composition, typography, semantic depth,
   interaction/state craft, product signature). Every row gets ONE evidence artifact with its
   §14 tier. **Capture live evidence** (preview tools): before/after screenshots at 1440/768/
   375px on web (or the default window + one constrained/resized state on desktop), every
   supported theme, and the loading/empty/error/selected/stale states you touched — a section
   with no `✓ live` artifact is UNVERIFIED and will not gate without an audited waiver.
2. **Independent score** — dispatch ONE fresh-context subagent (general-purpose; NOT you, no
   access to this conversation's contract or rationale) scoped to the changed surface only.
   Give it verbatim: the 13 §10 tells + the 8 §14 quality dimensions, the tier notation, the
   surface pointer (routes + files + the captured screenshots), and the return shape (both
   tables + totals + least-confident note). Paste its tables into the scorecard's Independent
   sections unchanged. If the session genuinely cannot dispatch agents, use the gate's audited
   waiver — never silently skip.
3. **Run the gate** (this, not prose, is "done" — ship rule per §14: anti ≤2 AND quality mean
   ≥3.0 AND no dimension <2 AND clarity/decision-integrity/signature each ≥3, both scorers):

```bash
python3 .claude/scripts/frontend-design-check.py check "$SC_DIR/scorecard.md" --repo-root <repo-root>
# Run diff-scan BEFORE committing the implementation (it scans ADDED lines vs --base,
# default HEAD — after a commit that diff is empty and the scan is vacuous; it warns on a
# 0-line scan, and you then pass --base <ref-before-the-work>). 'design-ok:' waives a
# deliberate literal.
python3 .claude/scripts/frontend-design-check.py diff-scan --repo-root <repo-root>
```

   Exit 3 (anti ≥3 or a quality threshold missed) → return to the contract and recompose;
   don't ship "improved but generic" — or clean-but-empty (a low anti score alone proves
   nothing; §10 note). Exit 4 (missing independent / Δ too large / UNVERIFIED-no-live) →
   arbitrate the disagreeing rows from their evidence (interactive: show the user both columns;
   autonomous: adopt the independent verdicts and say so), or capture the missing live
   evidence. Exit 5/6 → fix tokens / persistence. Re-run until PASS.
4. Answer the four questions (§11 Q1–Q4) for the shipped result. If Q4 has no honest answer, it
   was polish — say so rather than overclaiming.
5. Report: thesis chosen, before → after anti scores AND quality means (self AND independent),
   BAN-N removed, REF-N adapted, screenshots as proof, gate output verbatim. A self-scored
   "achieved" number without the independent column is not a claim — don't make it.

## Hard rules

- **No PRODUCTION code before direction selection.** Even a "quick restyle" gets deliverables
  1, 4, 5 in compact form — and program scope renders grayscale plates BEFORE choosing
  (exploration needs pixels; the old "no pixels before thesis" applied to production code,
  not to direction plates).
- **Never present one direction.** One option is a default wearing a costume; three divergent
  directions is the minimum honest search.
- **The rubric is the gate, and the gate is a script.** Current score, projected score, achieved
  score — all stated; the achieved score is a per-tell evidence scorecard (self + independent)
  that `frontend-design-check.py check` must PASS before "done" is claimed. The implementer never
  solely grades its own work.
- **Templates are the floor, not the identity.** shadcn/Radix (or stock Qt widgets, or htmx
  partials) stay as structural primitives; the visible language must answer Q4.
- **This skill ships code; `/frontend-uplift` never does.** For a multi-surface ranked audit or
  program-scale discovery, offer `/frontend-uplift <id>` instead of stretching this workflow.
- Design-review-only requests (user asks "why does this look generic?") get Steps 0–1 + the §10
  score + a direction sketch — no code until asked.

## Relationship to the other frontend tooling

| Need | Use |
|---|---|
| Ship a designed surface / restyle now, in-session | **this skill** |
| Ranked discovery report across an app ("where could it be better?") | `/frontend-uplift <id>` (its art-direction-scout consumes the same design-language reference) |
| Build a scoped milestone from an approved candidate | `/milestone-pipeline <id>` (its frontend-ux critic cites the same BAN/REF tokens) |

All three doors grade with the same §10 rubric and the same §14 band→outcome map + evidence
tiers (design-language §14 is the one home; the per-door bars and their one deliberate asymmetry
are stated there, not here).
