---
name: dark-mode-token-redeclaration-vs-hardcoded-color-literals
description: dark-mode @media block redeclaring :root tokens does NOT fix hardcoded color literals scattered through the CSS — audit ALL #hex literals for the inverse-scheme contrast
metadata:
  type: feedback
---

When a milestone introduces `@media (prefers-color-scheme: dark) { :root { ... } }`
to redeclare CSS custom properties, the SHIPPABLE risk is NOT the tokens
(those flip cleanly) but every HARDCODED color literal that bypasses the
token system. In ui-attractive-polish-m3 the dark block redeclared 7
color tokens, but the file still contained:

1. **`input[type="text"] { background: #fff }`** at app.css:70 with no
   explicit `color:` declaration → in dark mode inherits `color: var(--fg)`
   = `#e8e8e8` (light) on hardcoded `#fff` background → 1.22:1 contrast,
   typed text invisible. THIS is the load-bearing HIGH finding adversary
   must catch — affects EVERY operator data-entry surface.

2. **Tertiary-text hardcoded greys** (`#444`, `#555`, `#666`, `#777`,
   `#888`) for subtitle / hint / note / empty / display-name / dt / footer
   → 1.5-2.5:1 contrast in dark mode. MEDIUM (some descoped acceptably,
   but the descope CSS comment didn't enumerate them).

3. **Missing `color-scheme: light dark` declaration** on `:root` — the
   W3C signal that tells browsers to render UA-default form controls /
   scrollbars / `<select>` dropdowns in dark mode. Compounds with item 1
   because browsers can't auto-darken form internals without the signal.

**How to apply:** On any UPL dark-mode milestone, grep the CSS file for
`#[0-9a-fA-F]{3,6}` AFTER the dark `@media` block. Every literal hex
that appears OUTSIDE the dark block's `:root { ... }` body is a candidate
contrast failure. Compute WCAG luminance ratios for each against
`--bg #0d1117` (or whatever the dark `--bg` is) — anything below 4.5:1
is a small-text fail and below 3:1 is a non-text fail.

**Why:** The dark @media block redeclaration ONLY rebinds tokens, not
literals. The descope CSS comment in m3 enumerated `.status-badge--*`
and `th { #f0f0f0 }` but missed the inputs and 7 tertiary-grey rules.
Acceptance-criteria language "WCAG AA pass" is misleading when scoped
only to token-token combinations; it must include token-vs-literal and
literal-vs-literal combinations too.

**Calibration:** Input-background a11y collapse = HIGH (visible to
every operator). Tertiary-grey scattering = MEDIUM (degraded but not
blocking). Missing `color-scheme:` = MEDIUM (standards-compliance
signal + compounds the HIGH).

Related: [[bp1-description-vs-handler-validator-drift]] — same shape
in a different surface (doc says X, code does Y; one surface fixed,
sibling surfaces stale).
