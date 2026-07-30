---
name: middleware-cap-vs-handler-cap-read-ordering
description: When a body-size middleware ceiling is raised but the per-kind cap stays at the route handler, verify the handler check fires BEFORE await file.read()/request.body() — else the full body is buffered first.
metadata:
  type: feedback
---

When a milestone raises a `RequestBodySizeLimitMiddleware.prefix_caps` ceiling while keeping a
per-kind cap enforced at the route handler, verify the handler check fires BEFORE
`await file.read()` / `await request.body()`.

**Why:** textbook-ingest-m4's D3 synthesis claimed "magic-byte sniff fires at 5 bytes for
non-PDF bodies, so the 200 MB middleware envelope is safe" — false. The pre-flight runs AFTER
`file.read()`, which already buffered the full 200 MB. Memory pressure regresses by the ratio
of new-to-old middleware cap (20× in m4: 10 MB → 200 MB). Flag HIGH even on a loopback-only
threat model, because the cost-benefit analysis that justified the raise is built on a wrong
premise — the synthesis was actively wrong, not merely a silent limitation, so the "documented
limitation" pattern does not save it.

**How to apply:** on any body-cap change, trace from the middleware ceiling to the handler and
confirm an explicit Content-Length / streaming check precedes the first full read. Fix path:
move the per-kind cap upstream into a scope-aware `prefix_caps` middleware, or add a
Content-Length check at the very top of the handler BEFORE `file.read()`.

Related: [[claim-drift-verify-against-code]], [[security-doc-drift-on-multi-byte-magic-sniff]].
