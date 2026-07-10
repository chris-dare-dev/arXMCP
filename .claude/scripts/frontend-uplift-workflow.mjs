// frontend-uplift-workflow.mjs — Workflow-tool port (2026-06-14)
// ---------------------------------------------------------------------------
// Workflow-tool port of /frontend-uplift's 4 agent phases. Replaces the
// markdown-orchestrator (the main session driving every dispatch + holding all
// briefs/screenshots) with a deterministic JS control flow. The win is NOT the
// phase-tree display — it is that the fan-out / mode-routing / phase-advance now
// cost ZERO model tokens (plain JS), and the two phases that previously ran IN
// the main session (SYNTHESIZE, PRIORITIZE) are offloaded onto cost-capped
// generic transform agents (pipeline-synthesizer / pipeline-prioritizer).
//
// IMPORTANT — what does NOT move into this workflow (stays in the command Step 0):
//   - Step 0   parse args + the repo's init script + mkdir memory dirs (exec)
//   - Step 0.5 the repo's preflight script — REQUIRED dev-server reachability (exec)
//   - Step 0.6 LIVE-RECON — OPTIONAL Claude-in-Chrome reverse-engineer of exemplar
//              sites, written to discoveries/live-recon.md (needs AskUserQuestion +
//              a browser; a Workflow agent cannot do the browser-selection handshake)
// The Workflow JS has NO exec / browser / AskUserQuestion access, so all three of
// those preconditions remain main-session-only.
//
// NOTE: the init + preflight scripts are NOT part of the registry port — each consuming
// repo supplies its own stack-specific copies under .claude/scripts/frontend-uplift/,
// and their names differ by stack. Observed on this fleet:
//   init:      init-uplift.sh              (every repo)
//   preflight: ensure-preview-up.sh        (Next.js / SvelteKit / React-Vite / htmx)
//              ensure-render-up.sh         (PySide6/Qt — algebraic-variety-cross-section)
//              ensure_gui_bootable.py      (PySide6/Qt — chaotic-systems-dynamics)
// The command resolves and execs them; this workflow never touches the filesystem.
//
// SCREENSHOTS + LIVE-RECON handoff to SYNTHESIZE: the visual-scout drives the live
// preview itself (granted under both harness aliases: Claude_Browser current /
// Claude_Preview legacy) and writes PNGs into
// `${NOTES}/screenshots`; the optional live-recon (main session) writes
// `${NOTES}/discoveries/live-recon.md`. Neither is a scout BRIEF — so they are
// passed to the synthesizer as INPUT_PATHS (the screenshots DIR + the live-recon
// file), and the synthesizer prompt explicitly tells it to Read the PNGs (Read
// renders images) and live-recon.md if present. That is the image-context path the
// spec requires: the synthesizer reads the screenshots itself.
//
// Integration: /frontend-uplift still does Step 0 / 0.5 / 0.6 inline, then calls:
//   Workflow({ scriptPath: ".claude/scripts/frontend-uplift-workflow.mjs",
//              args: { id, brief, mode } })
// and after it returns, presents the final report + the gated /milestone-pipeline |
// /roadmap | /spike OFFER (which MUST stay in the main session — a workflow cannot
// prompt the user).
// ---------------------------------------------------------------------------

export const meta = {
  name: 'frontend-uplift',
  description: 'Frontend-modernization fan-out: parallel surface-aware scouts (art-direction/visual/library/inspiration/experiential/current-state-critic) -> thesis-framed synthesis -> 11-axis frontend challenge (incl. distinctiveness/anti-template) -> RICE-light prioritization. Read-only; produces a ranked modernization-candidate report opening with a design frame (visual thesis + direction). Stops before any /milestone-pipeline handoff (gated in the main session).',
  phases: [
    { title: 'Discover',   detail: 'two waves (round 3 — evidence before direction): wave 1 = visual-scout + current-state-critic (screenshots + manifest + gap audit); wave 2 = art-direction/library/inspiration/experiential FED that evidence -> briefs' },
    { title: 'Synthesize', detail: 'adopt the art-direction frame (thesis + direction + BAN list), then merge briefs + screenshots + live-recon -> [MOT-N]/[EXP-N] candidate catalog (sonnet high, offloaded from main session)' },
    { title: 'Challenge',  detail: '11-axis frontend checklist (token discipline, surface-aware motion AP, WCAG, bundle, RSC, distinctiveness/anti-template) per candidate (opus-max via frontmatter)' },
    { title: 'Prioritize', detail: 'portfolio lanes (a11y-debt mandatory / signature / foundations / workflow / polish) with RICE-light WITHIN lanes + challenger penalties -> final report (sonnet medium)' },
  ],
}

// ---- inputs ----------------------------------------------------------------
// Be robust to how the Workflow runtime delivers `args`: object, JSON string, or absent.
const _args = (typeof args === 'string') ? (args.trim() ? JSON.parse(args) : {}) : (args || {})
const { id, brief = '', mode = 'standard', url = 'http://localhost:5173',
        surface = 'auto', pages = '', targets = '', project = '' } = _args
if (!id) throw new Error('frontend-uplift-workflow requires args.id (kebab-case scope slug)')
// project (round-3 8a): the FRONTEND PROJECT under audit. The Gen-2 CWD contract can place this
// workflow's CWD at a checkout that is NOT the app under audit — without an explicit root, scouts'
// `find .` audited the wrong package.json. Forwarded into every scout prompt.
// url defaults to localhost:5173 only when the key is ABSENT; the command passes the
// already-defaulted --url value. Injected into the visual-scout dispatch prompt below
// (visual-scout drives the live preview — the other scouts don't, so they don't get it).
// surface/pages/targets forwarding (critique R-3): the command parses --surface/--pages/
// --targets and init.sh persists them, but the old port dropped them here — scouts fell back
// to inference/auto-discovery/canonical exemplars while the docs promised otherwise. Every
// scout now receives SURFACE; the visual-scout receives PAGES; experiential + art-direction
// receive TARGETS. Absent keys default to the exact pre-fix behavior.

const NOTES       = `.claude/notes/frontend-uplifts/${id}`
const DISCOVERIES = `${NOTES}/discoveries`           // briefs subdir is `discoveries`, NOT `briefs`
const SCREENSHOTS = `${NOTES}/screenshots`
const LIVE_RECON  = `${DISCOVERIES}/live-recon.md`   // optional, written by the main session in Step 0.6
const ARTIFACTS   = `${NOTES}/artifacts`

// ---- scout roster + mode selection -----------------------------------------
// art-direction-scout is in EVERY mode (lean included) — it produces the run's design frame
// (thesis + 3 divergent directions + BAN list + surface map, per frontend-design-language.md);
// dropping it re-creates the cookie-cutter failure this pipeline exists to prevent.
const ALL_SCOUTS = [
  { role: 'art-direction-scout',  agentType: 'frontend-uplift-art-direction-scout' },
  { role: 'visual-scout',         agentType: 'frontend-uplift-visual-scout' },
  { role: 'library-scout',        agentType: 'frontend-uplift-library-scout' },
  { role: 'inspiration-scout',    agentType: 'frontend-uplift-inspiration-scout' },
  { role: 'experiential-scout',   agentType: 'frontend-uplift-experiential-scout' },
  { role: 'current-state-critic', agentType: 'frontend-uplift-current-state-critic' },
]

// standard = all 6; lean = 4 (art-direction + visual + library + current-state-critic);
// experiential = 5 (art-direction + visual + experiential + library + current-state-critic; drops inspiration);
// deep = all 6 + one-tier override on current-state-critic.
const LEAN_ROLES         = new Set(['art-direction-scout', 'visual-scout', 'library-scout', 'current-state-critic'])
const EXPERIENTIAL_ROLES = new Set(['art-direction-scout', 'visual-scout', 'experiential-scout', 'library-scout', 'current-state-critic'])
const scouts =
  mode === 'lean'         ? ALL_SCOUTS.filter(s => LEAN_ROLES.has(s.role)) :
  mode === 'experiential' ? ALL_SCOUTS.filter(s => EXPERIENTIAL_ROLES.has(s.role)) :
  ALL_SCOUTS // standard + deep

// --mode deep bumps current-state-critic one tier (to opus).
// Everything else inherits its stamped frontmatter — pass no override.
const scoutModel = (role) => (mode === 'deep' && role === 'current-state-critic') ? 'opus' : undefined

// ---- Phase 1: DISCOVER — TWO WAVES (round 3: evidence before direction) ----
// The art-direction scout used to run blind, in parallel with the evidence producers, then
// author the frame the synthesizer "adopts". Wave 1 now captures the evidence (screenshots +
// manifest + inward gap audit); wave 2 (direction + outward lenses) receives it explicitly.
phase('Discover')
log(`DISCOVER: two-wave dispatch, ${scouts.length} scouts total (mode=${mode}) for "${id}"`)

const SCOUT_RETURN = {
  type: 'object', additionalProperties: false,
  required: ['role', 'brief_path', 'candidate_count', 'dominant_theme', 'top_candidate'],
  properties: {
    role:            { type: 'string' },
    brief_path:      { type: 'string' },
    candidate_count: { type: 'integer' },
    dominant_theme:  { type: 'string' },
    top_candidate:   { type: 'string' },
    // visual-scout only (R-1 + round-3): PNGs actually captured, plus the manifest that makes
    // them enumerable — Read-only downstream agents CANNOT list a directory.
    screenshot_count: { type: 'integer' },
    manifest_path:    { type: 'string' },
  },
}

const PROJECT_LINE = `PROJECT_ROOT = ${project || '(NOT SET — the orchestrator omitted --project. Do NOT audit the checkout you are running from (it may not be the app under audit); locate the intended frontend project from BRIEF context and STATE the path you chose in your TL;DR)'}  — the frontend project under audit; scope ALL package.json/src reads here, never the CWD (round-3 8a)`
const MANIFEST = `${DISCOVERIES}/visual-manifest.json`

function scoutPrompt(s, extraLines) {
  return [
    `You are dispatched as the ${s.role} for frontend-uplift run "${id}".`,
    ``,
    `ID = ${id}`,
    `BRIEF = ${brief || '(no explicit brief — infer scope from the app nav + your source registry)'}`,
    PROJECT_LINE,
    `BRIEF_PATH = ${DISCOVERIES}/${s.role}-brief.md`,
    `SURFACE = ${surface}  (state.surface_type — gates the experiential lens; every candidate carries its S-1/S-1m/S-2 tag)`,
    ...extraLines,
    ``,
    `Follow your agent definition end-to-end: read your memory + canonical prompt, survey`,
    `under the phase-1 surface-aware hard rules, WRITE your structured brief to BRIEF_PATH,`,
    `append your lessons memory, then return the structured summary.`,
  ].join('\n')
}

const scoutOpts = (s) => ({
  agentType: s.agentType,
  label: `discover:${s.role}`,
  phase: 'Discover',
  schema: SCOUT_RETURN,
  model: scoutModel(s.role),       // undefined for all but deep-mode current-state-critic
  // No worktree: scouts write to disjoint per-role paths — no parallel-write race (pattern-v2 §4).
})

const WAVE1_ROLES = new Set(['visual-scout', 'current-state-critic'])
const wave1 = scouts.filter(s => WAVE1_ROLES.has(s.role))
const wave2 = scouts.filter(s => !WAVE1_ROLES.has(s.role))

log(`DISCOVER wave 1 (evidence): ${wave1.map(s => s.role).join(', ')}`)
const wave1Results = await parallel(wave1.map(s => () =>
  agent(
    scoutPrompt(s, [
      `SCREENSHOTS_DIR = ${SCREENSHOTS}  (visual-scout: write your PNG evidence here; you drive the live preview yourself via your granted preview tools)`,
      ...(s.role === 'visual-scout' ? [
        `PREVIEW_URL = ${url}  (point preview_start at THIS exact URL — do NOT default to localhost:5173. Tool naming: current harness exposes mcp__Claude_Browser__preview_*, older builds mcp__Claude_Preview__preview_* — you are granted BOTH; use whichever resolves. If NEITHER resolves you cannot screenshot: say so in your TL;DR and return screenshot_count: 0 — never silently degrade.)`,
        `PAGES = ${pages || '(empty — auto-discover from the app nav)'}`,
        `VISUAL_MANIFEST = ${MANIFEST}  (WRITE this file: a JSON array of {"file","route","state","theme","viewport","console_errors"} for EVERY PNG you capture. Read-only downstream agents cannot list a directory — this manifest is the ONLY way they find your evidence. Return manifest_path + screenshot_count in your structured return.)`,
      ] : []),
    ]),
    scoutOpts(s)
  )
))

// ---- wave-1 evidence digest (R-1 loud degradation + round-3 manifest) ------
const w1 = wave1Results.filter(Boolean)
const vsResult = w1.find(b => typeof b.role === 'string' && b.role.toLowerCase().includes('visual'))
const cscResult = w1.find(b => typeof b.role === 'string' && b.role.toLowerCase().includes('critic'))
const screenshotCount = vsResult ? (vsResult.screenshot_count ?? 0) : 0
const manifestPath = (vsResult && vsResult.manifest_path) ? vsResult.manifest_path : MANIFEST
const evidenceStatus = screenshotCount > 0
  ? `SCREENSHOT EVIDENCE: ${screenshotCount} PNG(s); manifest at ${manifestPath} — Read the manifest, then Read each listed PNG path (Read renders images). This is primary evidence.`
  : `EVIDENCE STATUS: NO-SCREENSHOT RUN (degraded). The visual lens is code-inferred (~ tier, design-language §14). Do NOT describe any judgment as screenshot-verified; dark-parity (axis 6) and mobile (axis 8) checks must be marked ~ inferred. State this degradation in your TL;DR.`
log(screenshotCount > 0 ? `DISCOVER wave 1: ${screenshotCount} screenshots captured (manifest ${manifestPath})` : 'DISCOVER wave 1: NO screenshots captured — run degrades loudly (R-1)')

log(`DISCOVER wave 2 (direction + outward, fed wave-1 evidence): ${wave2.map(s => s.role).join(', ')}`)
const wave2Results = await parallel(wave2.map(s => () =>
  agent(
    scoutPrompt(s, [
      `${evidenceStatus}`,
      `VISUAL_MANIFEST = ${manifestPath}  (Read it FIRST if present — evidence paths + route/state/theme/viewport per capture)`,
      ...(cscResult ? [`CURRENT_STATE_BRIEF = ${cscResult.brief_path}  (Read it — the inward gap audit; ground your direction/candidates in what IS, not what you imagine)`] : []),
      ...(s.role === 'experiential-scout' || s.role === 'art-direction-scout' ? [
        `TARGETS = ${targets || '(empty — use the canonical exemplars: source-registry §6 / design-language §4)'}`,
        `LIVE_RECON_PATH = ${LIVE_RECON}  (read this if it exists — the main session may have reverse-engineered exemplar/reference sites live)`,
      ] : []),
    ]),
    scoutOpts(s)
  )
))

const briefs = [...w1, ...wave2Results.filter(Boolean)]
if (briefs.length === 0) throw new Error('DISCOVER: all scouts failed — aborting before synthesis')
// Frame degradation is LOUD (round-3 8b): the art-direction scout is non-droppable by roster,
// but a failed return must not silently downgrade the run to a provisional frame.
const adResult = briefs.find(b => typeof b.role === 'string' && b.role.toLowerCase().includes('art'))
const frameStatus = adResult
  ? `FRAME: art-direction brief at ${adResult.brief_path} — adopt it (phase-2 Step 2a.5).`
  : `FRAME DEGRADED: the art-direction scout FAILED — build a provisional frame from design-language §8/§9, say so loudly in the TL;DR, and the report header must carry this degradation.`
if (!adResult) log('DISCOVER: FRAME DEGRADED — art-direction scout returned nothing (provisional frame downstream)')
const rawCandidates = briefs.reduce((n, b) => n + (b.candidate_count || 0), 0)
log(`DISCOVER: ${briefs.length}/${scouts.length} scouts returned; ${rawCandidates} raw candidates`)

// ---- Phase 2: SYNTHESIZE (offloaded; reads briefs + screenshots + live-recon) --
phase('Synthesize')
const synthesisPath = `${ARTIFACTS}/synthesis.md`
const synthesis = await agent(
  [
    `Dispatched as the SYNTHESIZER (pipeline-synthesizer) for frontend-uplift run "${id}".`,
    ``,
    `PIPELINE = frontend-uplift`,
    `PHASE2_REF = frontend-uplift-phase-2`,
    `EXTRA_REFS = frontend-uplift-motion-vocabulary,frontend-uplift-experiential-motion,frontend-design-language`,
    `SYNTHESIS_PATH = ${synthesisPath}`,
    `CANDIDATES_JSON = `,   // empty — no scorer for this pipeline (RICE by hand in Phase 4)
    ``,
    `BRIEF_PATHS (read every one END-TO-END):`,
    ...briefs.map(b => `  - ${b.brief_path}`),
    ``,
    `${evidenceStatus}`,
    `${frameStatus}`,
    ``,
    `INPUT_PATHS (read these too — they are NOT scout briefs but they ARE primary evidence):`,
    `  - ${manifestPath}  (the visual manifest — Read it, then Read each listed PNG path; you cannot list directories, the manifest is your index. Skip silently if absent — the run is then NO-SCREENSHOT.)`,
    `  - ${LIVE_RECON}  (the optional live-recon notes from the main session's Claude-in-Chrome exemplar teardown — Read it if it exists; skip silently if absent)`,
    ``,
    `FRAME RULE (phase-2 Step 2a.5): the art-direction-scout brief carries the run's design frame`,
    `(visual thesis + 3 divergent directions + BAN list + surface map + cookie-cutter scores).`,
    `ADOPT it as the synthesis' opening section, re-confirm its current-state score against the`,
    `screenshot PNGs, and place EVERY candidate relative to the frame ([DIRECTION-DEFINING] /`,
    `compatible / [polish]; frame-conflicting -> parking lot with the BAN-N cited). If that brief is`,
    `missing, synthesize a provisional frame from frontend-design-language §8/§9 — never emit a`,
    `frameless catalog.`,
    ``,
    `Follow your agent definition: Read the phase-2 protocol at .claude/references/frontend-uplift/`,
    `phase-synthesize.md plus the EXTRA_REFS (Read them directly — this fleet has no`,
    `get_reference MCP tool; the canon lives in .claude/references/),`,
    `read every brief AND the screenshot PNGs AND live-recon.md, build the frame-anchored unified`,
    `[MOT-N]/[EXP-N] candidate catalog (surface-tagged), WRITE ${synthesisPath}, then return the`,
    `structured result.`,
  ].join('\n'),
  {
    agentType: 'pipeline-synthesizer',   // tool-capped (Read/Write) — Read renders the PNGs
    label: 'synthesize',
    phase: 'Synthesize',
    // model + effort inherited from frontmatter (sonnet high)
    schema: {
      type: 'object', additionalProperties: false,
      required: ['synthesis_path', 'candidate_count', 'candidates'],
      properties: {
        synthesis_path:  { type: 'string' },
        candidate_count: { type: 'integer' },
        candidates: {
          type: 'array',
          items: {
            type: 'object', additionalProperties: false,
            required: ['name', 'size', 'source_briefs'],
            properties: {
              name:          { type: 'string' },
              // XS included (round-3 8c): scouts + RICE effort use XS; the old enum rejected it.
              size:          { type: 'string', enum: ['XS', 'S', 'M', 'L', 'XL'] },
              source_briefs: { type: 'array', items: { type: 'string' } },
            },
          },
        },
      },
    },
  }
)
if (!synthesis) throw new Error('SYNTHESIZE: agent returned null — aborting')
log(`SYNTHESIZE: ${synthesis.candidate_count} candidates -> ${synthesis.synthesis_path}`)

// ---- Phase 3: CHALLENGE (adversary; opus-max via its frontmatter) ----------
phase('Challenge')
const challengePath = `${ARTIFACTS}/challenge.md`
const challenge = await agent(
  [
    `You are the CHALLENGER for frontend-uplift run "${id}".`,
    ``,
    `ID = ${id}`,
    `SYNTHESIS_PATH = ${synthesis.synthesis_path}`,
    `CHALLENGE_PATH = ${challengePath}`,
    PROJECT_LINE,
    ``,
    `${evidenceStatus}`,
    ``,
    `VISUAL_MANIFEST = ${manifestPath}  (Read it, then Read each listed PNG path — you cannot list directories)`,
    ``,
    `Follow your agent definition: walk the 11-axis frontend checklist (token discipline, state`,
    `coverage, surface-aware motion anti-patterns, bundle budget, React 19+RSC compat, dark/light`,
    `parity, WCAG 2.2 AA, mobile, perf, license, distinctiveness/anti-template per`,
    `frontend-design-language BAN-1..15 + the §10 cookie-cutter rubric — incl. the run-level check`,
    `that the synthesis opens with an adopted design frame) against EACH candidate, emit`,
    `BLOCKER/MAJOR/MINOR/NONE per axis (calibrated — 30-60% PASS is healthy; inflation makes the`,
    `report unactionable), WRITE ${challengePath}, then return the finding counts.`,
  ].join('\n'),
  {
    agentType: 'frontend-uplift-challenger',
    label: 'challenge',
    phase: 'Challenge',
    // inherit frontmatter (opus max) — no override
    schema: {
      // severity names are BLOCKER/MAJOR/MINOR/NONE; integer keys stay stable for the
      // prioritizer (critical=BLOCKER, high=MAJOR, medium=MINOR, low=NONE/PASS — phase-3).
      // verdict added per critique R-7: the agent contract always returned it but the old
      // schema (additionalProperties:false) silently discarded it; BLOCKED (synthesis
      // missing / <3 candidates) is representable as verdict=BLOCKED + challenge_path="".
      type: 'object', additionalProperties: false,
      required: ['challenge_path', 'verdict', 'critical', 'high', 'medium', 'low'],
      properties: {
        challenge_path: { type: 'string' },
        verdict:        { type: 'string', enum: ['SHIP', 'DO-NOT-SHIP', 'MIXED', 'BLOCKED'] },
        critical:       { type: 'integer' },
        high:           { type: 'integer' },
        medium:         { type: 'integer' },
        low:            { type: 'integer' },
      },
    },
  }
)
if (!challenge) throw new Error('CHALLENGE: agent returned null — aborting')
if (challenge.verdict === 'BLOCKED') {
  // Deterministic gate (the milestone-template pattern, scaled to a non-shipping pipeline):
  // a BLOCKED challenge means Phase 2 output was unusable — never rank on top of it.
  throw new Error('CHALLENGE: BLOCKED — synthesis missing or < 3 candidates; re-run Phase 2 (resume) instead of ranking an unusable catalog')
}
log(`CHALLENGE: verdict=${challenge.verdict} — ${challenge.critical} BLOCKER / ${challenge.high} MAJOR / ${challenge.medium} MINOR / ${challenge.low} PASS`)

// ---- Phase 4: PRIORITIZE (offloaded -> opus agent writes the final report) ---
// No scorer for this pipeline: RICE-light is computed BY HAND per phase-4 ref (SCORER_CMD empty).
phase('Prioritize')
const reportPath = `${ARTIFACTS}/final-report.md`
const ranked = await agent(
  [
    `Dispatched as the PRIORITIZER (pipeline-prioritizer) for frontend-uplift run "${id}".`,
    ``,
    `PIPELINE = frontend-uplift`,
    `PHASE4_REF = frontend-uplift-phase-4`,
    `SYNTHESIS_PATH = ${synthesis.synthesis_path}`,
    `CHALLENGE_PATH = ${challenge.challenge_path}`,
    `CHALLENGE_COUNTS (verbatim from the challenger's structured return — carry these into the`,
    `report header EXACTLY; do NOT re-tally or restate different numbers — critique R-2):`,
    `  BLOCKER=${challenge.critical} MAJOR=${challenge.high} MINOR=${challenge.medium} PASS=${challenge.low} verdict=${challenge.verdict}`,
    `${evidenceStatus}`,
    `REPORT_PATH = ${reportPath}`,
    `CANDIDATES_JSON = `,   // empty — no scorer
    `RANKED_JSON = `,       // empty — no scorer
    `SCORER_CMD = `,        // empty — compute RICE-light BY HAND per phase-4 ref; do NOT run Bash
    ``,
    `Follow your agent definition: Read the phase-4 protocol at`,
    `.claude/references/frontend-uplift/phase-prioritize.md (Read it directly). PORTFOLIO LANES`,
    `(round 3 — RICE is only valid WITHIN a lane; a x1.3 bonus cannot beat a 32x effort ratio, so`,
    `cross-lane ranking mathematically buries structural design under XS polish): assign every`,
    `candidate to ONE lane — signature-direction ([DIRECTION-DEFINING]) / foundations`,
    `([FOUNDATIONAL]) / a11y-safety-debt (WCAG/AP findings — MANDATORY lane, listed first, never`,
    `ranked away) / workflow / polish — then compute RICE BY HAND within each lane and rank`,
    `within lanes only. Carry the adopted design frame into the report header, WRITE ${reportPath},`,
    `return the ranked list (lane-ordered: a11y-safety first, then signature-direction,`,
    `foundations, workflow, polish). Do NOT embed any auto-invocation of /milestone-pipeline,`,
    `/roadmap, or /spike — the handoff OFFER is the main session's job.`,
  ].join('\n'),
  {
    agentType: 'pipeline-prioritizer',   // tool-capped (Read/Write/Bash); Bash only for SCORER_CMD (empty here)
    label: 'prioritize',
    phase: 'Prioritize',
    // model + effort inherited from frontmatter (sonnet medium)
    schema: {
      type: 'object', additionalProperties: false,
      required: ['final_report_path', 'ranked'],
      properties: {
        final_report_path: { type: 'string' },
        ranked: {
          type: 'array',
          items: {
            type: 'object', additionalProperties: false,
            required: ['name', 'rice', 'verdict'],
            properties: {
              name:    { type: 'string' },
              rice:    { type: 'number' },
              verdict: { type: 'string' },
            },
          },
        },
      },
    },
  }
)
if (!ranked) throw new Error('PRIORITIZE: agent returned null — aborting')
log(`PRIORITIZE: ${ranked.ranked.length} ranked -> top: ${ranked.ranked[0] ? ranked.ranked[0].name : '(none)'}`)

// ---- Return to the main session (which presents the report + gated handoff) --
return {
  id,
  mode,
  surface,
  project,
  scouts_returned: briefs.length,
  raw_candidates: rawCandidates,
  screenshot_count: screenshotCount,          // 0 = degraded NO-SCREENSHOT run (say so when presenting)
  visual_manifest: manifestPath,
  frame_degraded: !adResult,                  // true = provisional frame (art-direction scout failed)
  synthesis_path: synthesis.synthesis_path,
  candidate_count: synthesis.candidate_count,
  challenge_path: challenge.challenge_path,
  challenge_verdict: challenge.verdict,
  challenge_counts: { critical: challenge.critical, high: challenge.high, medium: challenge.medium, low: challenge.low },
  final_report_path: ranked.final_report_path,
  ranked: ranked.ranked,
}
