# Lessons — frontend-uplift-inspiration-scout (arXMCP)

- **Don't edit `.claude/references/frontend-uplift-{motion-vocabulary,source-registry}.md`
  directly to append a new `MOT-N` token or source row, even though their own "How to evolve"
  sections invite it.** Both files are hash-tracked in `.claude/.registry-manifest.json` (synced
  registry files) — a scout-time edit risks a hash mismatch with the upstream sync mechanism.
  Instead, propose the new token/source in the brief body (name it, define it, cite the source)
  and note explicitly that it was NOT written to canon — mirror the source-registry §7 pattern
  where new REF-N entries are "minted only by human promotion," not scout-authored inline.
- **arXMCP's `/ui/` has no Tailwind and no shadcn** — it's a single hand-rolled ~371-line
  `app.css` whose dark-mode branch is a documented GitHub-Primer clone. When a user brief assumes
  Tailwind/shadcn genericness, correct the premise up front: the actual cause is "8 tokens, no
  scale, one repeated card silhouette," and the highest-leverage borrows are Primer's OWN further
  components (ActionList, Blankslate, State label) since arXMCP already half-adopted that
  palette — extending an already-adopted vocabulary reads as more coherent than importing a new
  one, and needs zero new design tokens.
- **NotebookLM's "Discover sources" feature (topic → annotated candidates → one-click import) is
  the closest public domain analogue to arXMCP's own "Discover papers" card** — worth checking
  first in any future arXMCP frontend-uplift run touching that surface; it validates the
  recommend-with-reason shape is legible to researchers specifically, not just SaaS operators.
