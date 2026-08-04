- In small server-rendered surfaces (Jinja2/htmx, no build chain), the highest-yield critique
  technique is grepping every CSS class/attribute a route handler emits (f-string fragments AND
  Jinja templates) against the stylesheet and flagging the ones with zero matching rule — e.g.
  arXMCP's `.status-badge__remediation`, `.discover-*`, `select`/`textarea`, `[data-status]` all had
  markup but no CSS. This is stronger, more concrete evidence than generic "looks unpolished" claims
  and is exactly what a challenger/synthesizer can act on directly. Reusable check:
  `grep` every `class="..."` / `data-*` token used in templates + route handlers, then confirm each
  has a corresponding CSS rule (not just a bare-element selector coincidentally covering it).
