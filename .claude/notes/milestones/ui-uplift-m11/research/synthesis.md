# ui-uplift-m11 — research synthesis (UPL-21)

## The count was wrong, and had always been wrong

The milestone title and summary say **four** empty states. There are **three**
`class="empty"` surfaces:

| surface | file |
|---|---|
| notebooks empty row | `index.html` (`#notebooks-empty`) |
| papers empty state | `notebook_detail.html` |
| discover results empty | `server/routes/notebooks.py` fragment |

Checked at the discovery-era commit `0c95720` (2026-08-03): **also three**. So
this is not drift — the discovery miscounted and the roadmap carried it into
the title and summary unchecked. Corrected in the roadmap with that evidence.

Three near-neighbours are NOT empty states and were excluded deliberately:
`"No discovery run yet"` and `"Never indexed"` are `.hint` prose, and
`"No ingest runs yet."` is a status value, not a collection with nothing in it.

## AC#1's control half does not fit two of the three

> "states a cause and offers one actual control, **not a pointer to a form
> elsewhere on the page**"

| empty state | where its action lives | control? |
|---|---|---|
| papers | behind the `<details>` **m12 created** | **yes** — a pointer is what AC#1 forbids, and m12 forced one |
| notebooks | Create form directly above, visible | a duplicate of an adjacent control (BAN-9) |
| discover results | Discover button directly above; the useful action is editing the TOPIC, another block | duplicate or pointer |

Narrowed by owner decision and recorded in the roadmap AC, not only at the
sites. The index refusal is **time-limited**: when UPL-1 v1 moves the Create
form below the table, the copy becomes wrong and the control half has to land
there for the same reason it landed on the papers table.

## An unfiled bug in the surface m11 owns

Nothing removed the papers empty state. Add a paper by any of the three paths
(Add-by-URL, Upload, Discover→Add) and the row appends to `#papers-tbody` while
`"No papers yet."` stays on screen **above a populated table**. The index dodges
this with a per-form JS hook (`getElementById('notebooks-empty')?.remove()`)
wired to ONE form; three paths here would need three hooks and a fourth would
silently not get one.

Fixed structurally: the empty state moved INSIDE the tbody as `#papers-empty`
and is cleared by `#papers-empty:has(~ tr) { display: none }` — no JS, covers
every add path including ones not written yet. `:has()` is already load-bearing
in this stylesheet (m8's `table:has(tbody:empty) thead th`).

## The cost the control half actually carries

Adding a real control to the papers empty state means a SECOND form posting
`/ui/api/notebooks/{slug}/papers`. Three independent guards objected —
`test_ui_htmx_json_contract` (exactly one form per endpoint), `test_ui_m3`
(total htmx form count), `test_ui_m12` (`hx-ext` count) — plus my own m12 M13
guard forbidding any form in the papers section.

Each was reconciled deliberately rather than blanket-updated:

- **M13's guard** relaxed to the POPULATED case, which is what BAN-9 was about.
  In the empty state there is no table to duplicate beside and no other
  reachable control. This is the M9 lesson applied to m12's own guard — the
  blanket form would have pinned m11 out of its own acceptance criterion.
- **M6's nesting guard** now resolves inside the disclosure rather than taking
  whichever form comes first in document order.
- **The JSON contract helper** stopped asserting "exactly one form per
  endpoint" and now checks EVERY match independently — strictly stronger, and
  it stops one compliant form covering a non-compliant sibling.
- **The app.css cap** went 680 → 720 in lockstep across the three sibling
  tests, with the reason recorded in the raise history.

## AC#3 — the icon question

The source pattern leads with an icon. Adopted **without** it: the console
ships zero icons, the frame treats that as an asset (BAN-3), and the roadmap's
`wont` list requires the product's first icon to be an explicit escalated
decision rather than something an empty state drifts into.
