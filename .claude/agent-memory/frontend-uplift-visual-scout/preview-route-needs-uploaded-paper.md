---
name: preview-route-needs-uploaded-paper
description: arXMCP's ar5iv preview route only resolves for papers added via upload, not URL-paste — affects preflight seeding for the visual-scout's 4th default route
metadata:
  type: project
---

`GET /ui/notebooks/{slug}/papers/{paper_id}/preview` (the design system's 3rd
canonical route, S-2 "document-view" class) only serves content for papers whose
`has_preview` flag is true, which requires the paper to have been added via the
**"Upload ar5iv HTML" form** (`POST /ui/api/notebooks/{slug}/papers/upload`).
Papers added via **"Add paper by URL"** (`POST /ui/api/notebooks/{slug}/papers`,
body `{"arxiv_url": ...}`) do NOT store on-disk ar5iv HTML — `has_preview` stays
false and the preview route correctly 404s (`{"detail":"no preview available"}`).

**Why:** confirmed live on 2026-08-03 against a 6-paper `uplift-demo` notebook
seeded entirely via URL-paste (per the standard `POST /ui/api/notebooks` +
`POST .../papers` preflight recipe) — every paper 404'd on preview. Checked every
other notebook in the deployment (`bridgeland-stability*`, `fourier-duality*`,
`my-notebook`) and found none with a working preview link either.

**How to apply:** if a future visual-scout run needs to actually walk the preview
route (not just confirm the 404 is well-formed), the preflight seeding recipe
needs a THIRD step beyond create-notebook + add-paper-by-URL: an upload call with
a real ar5iv HTML fixture file, e.g. `POST
/ui/api/notebooks/{slug}/papers/upload` (multipart, fields `paper_id` + `file`).
Absent that, treat the preview route as un-walkable-this-run and say so in the
brief's evidence-tier section — a 404 on an un-uploaded paper is CORRECT
behavior, not a broken-page CRITICAL finding. See also
[[evidence-without-browser-tools]].
