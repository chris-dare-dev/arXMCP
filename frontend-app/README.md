# frontend-app — arXMCP operator console SPA (WS-B)

Vite + React 19 + TypeScript operator frontend, statically served by the
existing FastAPI process at `/app` (see `server/spa.py`). Node/Vite is
**build-time only** — no Node process exists at runtime (Stage-2 D1 ADR).

- Design language: "Technical Editorial" — normative spec at
  `_pipeline/stage-1-discovery/synthesis/design-system-brief.md` (pipeline
  workspace, outside this repo). Token sheet: `src/styles/tokens.css`.
- Anti-pattern gates: `tests/test_design_gates.py` (repo pytest suite) runs
  against the **compiled** CSS in `dist/` — build before running it.
- Typed API client: generated from the repo-root `openapi.json` (IF-1 dump)
  via `npm run gen:api` (commits `src/api/schema.d.ts`).
- No external design-system artifacts are vendored; every component under
  `src/` is authored here.

## Commands

```sh
npm ci                 # reproducible install from package-lock.json
npm run build          # tsc + vite build -> dist/ (committed)
npm test               # vitest (client + token unit tests)
npm run e2e            # playwright: axe gate, visual baselines, CSP, spike
npm run gen:api        # regenerate src/api/schema.d.ts from ../openapi.json
```

`dist/` is committed so the Python server (and the pytest design gates) never
need a Node toolchain at runtime. Rebuild + re-commit `dist/` whenever
`src/` changes.
