---
name: evidence-without-browser-tools
description: How to produce a fully-evidenced visual-scout brief when browser-preview tools are withheld and only Bash/Read/Grep/Glob/Write are granted
metadata:
  type: feedback
---

When the visual-scout's tool grant excludes ToolSearch/preview_*/Claude_in_Chrome
(Bash, Read, Grep, Glob, Write only), do NOT burn turns trying to discover that —
the dispatching orchestrator states this plainly in the task prompt when it applies.
Instead:

1. Read the orchestrator-captured `discover/visual-manifest.md` first, end to end —
   it carries live-measured DOM geometry, computed styles, tap-target dimensions,
   and htmx/motion inventories at tier `✓ measured`, gathered from an actual
   rendered session even when no PNG could be captured (e.g. "Browser pane not
   displayed, page not compositing frames").
2. Read the actual template/CSS source directly (arXMCP's whole `/ui/` stylesheet
   is one ~370-line file — cheap to read end-to-end) and cross-verify every
   manifest claim against `grep` on the source. Watch for one trap: naive
   `grep -c "aria-live"` (or similar) on a Jinja2 template overcounts, because the
   milestone-history comments (`{# ... #}`) frequently restate attribute names in
   prose ("m1 UPL-3: aria-live="polite" so screen readers..."). Filter those lines
   out (or match only real HTML attribute syntax) before trusting a count against
   the manifest's live-DOM number.
3. Use `curl` against the live server (it's already running per the task's
   preflight) to confirm route status codes, fetch raw fragment HTML (e.g.
   `/ui/status-badge`), and time requests for the "no 4xx/5xx, no >1500ms" network
   check — sub-10ms local responses confirm no slow-request findings are needed.
4. State the evidence-tier gap plainly in the brief's opening section (no PNGs,
   here's why, here's what stands in for them) rather than writing screenshot
   captions from geometry alone — this satisfies the "no screenshot → no finding"
   rule without inventing subjective visual impressions the geometry can't support.

This combination (manifest + source grep + curl) was sufficient to write a fully
evidenced CRITICAL/HIGH/MEDIUM/LOW brief with zero screenshots for
`2026q3-ui-uplift`. See also [[preview-route-needs-uploaded-paper]].
