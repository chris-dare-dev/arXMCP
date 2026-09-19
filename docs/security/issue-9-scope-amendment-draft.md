# Issue #9 scope amendment — DRAFT (LOCAL ONLY, NOT POSTED)

**Status:** local draft awaiting owner review. Per the Stage-2 operational
rules ("no GitHub writes; issue edits are drafted as local files only"),
this text has **not** been posted to `chris-dare-dev/arXMCP#9`. When
approved, paste it as a comment on #9 (or edit the issue body's scope
list) — the text below is written to be paste-ready.

**Author:** Stage-2 slice `arx-ws0` (WS-0 item d), 2026-07-04.
**Grounding:** Stage-1 finding 230 (live tracker ground truth: #9 is open,
dormant since 2026-05-29, its scope frozen at the m3-era surface) and the
Stage-2 orchestrator decision record (closure #2: WS-0 amends #9's scope;
WS-A/WS-B milestones carry a security-review checklist gate before
integration).

---

## Proposed comment text for #9

### Scope amendment (Stage-2 build-out, 2026-07)

This issue's audit scope was frozen on 2026-05-29 at the then-current
surface (`server/routes/ui.py`, `server/routes/notebooks.py`,
`frontend/templates/`, `server/middleware.py`). The Stage-2 build-out
adds operator-plane surfaces this audit must also cover — auditing only
the 2026-05 list would green-light a console that no longer matches
reality. Scope is amended to add:

**Workstream A (server/API):**

1. **`/api/v1` JSON operator API** — the versioned JSON-only router
   aliasing the `/ui/api` notebook routes (pagination, `format_version`,
   no `HX-Request` HTML|JSON unions). Same mutating verbs as the htmx
   surface (create/delete/rename/upload/ingest) on a second prefix:
   CSRF posture, Sec-Fetch-Site carve-outs, and Origin/Host validation
   must be re-checked for the new prefix.
2. **SSE endpoint** (multiplexed topics: logs / requests / sessions /
   ingest) — slow-consumer memory bounds (per-client queue caps,
   drop-oldest), event-payload redaction (must sit **after**
   `RedactionFilter`), and cross-origin readability under the loopback
   posture.
3. **Capability configuration layer** — `CapabilityMiddleware` (pure
   ASGI), bearer-token → profile resolution, `operator_settings`-backed
   profiles (runtime-mutable), structured denial envelopes. Token
   handling: env-supplied (`--token-env`), SHA-256-only persistence, no
   token in logs/audit rows/config files. Note the deliberate D5
   invariant: **no `tools/list` filtering** — verify denial is
   call-time-only and the BP1 bytes never vary by profile.
4. **Append-only `tool_calls` audit store** (SQLite/JSONL, ring-bounded)
   — sanitize-filter coverage for logged query text, ring eviction
   correctness, and no PII/path leakage in audit rows.
5. **Observability read-APIs** — request-event ring buffer, log tail
   (snapshot + SSE), session-registry snapshot: all read-only
   projections; verify redaction ordering (R2) and that the registry
   stays module-private.
6. **Upload path changes** — streamed-to-disk uploads replacing the
   200 MB in-RAM buffer: re-run the polyglot/zip-bomb questions (open
   question 2) against the new chunked reader; partial-file cleanup on
   abort.
7. **Fetch-ladder expansion** — `arxiv.org/html/<id>` acceptance
   (`_HOST_PATH_PREFIX` extension) and the native→ar5iv→local-LaTeXML
   ladder; closes the #2 redirect-host-validation family in the same
   code review (see below).
8. **Build-time OpenAPI dump** — `openapi.json` generated offline;
   verify runtime `openapi_url` stays `None` (Threat-4) and the dump
   ships no server-internal paths.

**Workstream B (frontend):**

9. **`/app` static SPA mount** (Vite build output served by the same
   FastAPI process; ADR-0001) — CSP for `/app` must be **stricter** than
   `/ui/` (`script-src 'self'`, no `unsafe-inline`); no runtime Node
   process; all assets self-hosted (loopback-only network invariant);
   lockfile/supply-chain review of the build-time dependency graph.
10. **Typed API client + SSE consumers in the SPA** — token storage
    (if any) stays out of `localStorage`/query strings; error envelopes
    rendered without HTML injection (stored-XSS question 5 extends to
    every new render path, including KaTeX output containers).
11. **Graph read endpoint** (`/api/v1/.../graph/neighbors`) — parameter
    validation mirrors the MCP handler's F2 path-validation contract;
    `graph_status` degradation must not leak filesystem paths.

**Unchanged:** the original scope list (ui.py routes, notebooks.py
mutating surface, templates, middleware constants) remains in force; the
"current defenses" baseline and the audit's shape ("its own E-series
milestone") are unchanged.

### The 5 open questions become a standing checklist

The issue's five open questions are adopted verbatim as the Stage-2
security checklist, applied to **every** WS-A/WS-B milestone before
integration (not only at the final audit):

1. CSRF-without-tokens sufficiency (now also for `/api/v1` + SSE).
2. Upload polyglot / zip-bomb completeness (now for the streamed path).
3. Preview path-traversal completeness (note: the containment check was
   ported to `Path.is_relative_to` for Windows correctness in Stage-2 —
   re-review that specific change).
4. CSP `unsafe-inline` scope (goal state: `/app` has none; `/ui/`
   legacy allowance documented or removed).
5. Stored-XSS on operator-authored fields (extended to SPA render
   paths and audit-log viewers).

### Sequencing note

Per the Stage-2 decision record: this amendment is the WS-0 deliverable;
each WS-A/WS-B capability milestone carries a security-review checklist
gate before integration; the full audit remains its own E-series-sized
milestone (per the CAND-13 scout designation). Issue #2 (redirect-host
validation) is scheduled to close inside the WS-A fetch-ladder milestone
— same code family, near-zero marginal cost.

---

## Local appendix (not part of the paste-ready text)

- Surfaces list derived from: `workstreams.md` §WS-A/§WS-B,
  `acceptance-criteria.md` AC-0.4 (the enumerated minimum: `/api/v1`,
  SSE, capability config, `/app` static mount, log/request endpoints —
  all covered above), `target-architecture.md`, finding 230 §2.3.
- AC-0.4's GitHub-comment criterion is intentionally NOT met by this
  file alone (no-GitHub-writes rule supersedes); the acceptance test for
  WS-0 is the existence + completeness of this draft.
