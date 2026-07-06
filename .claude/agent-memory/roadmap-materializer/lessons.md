
## paper-metadata (2026-07-05)
- Arrived with validator already exit 0 — the per-phase validate-after-every-write loop upstream means the Phase-4 gate is a formality when phases were run in one session.
- Reliable link sources in arXMCP: the pattern file an epic mirrors (server/notebooks_store.py), the handler it rewires (server/handlers/paper.py), and the hash-pin test it must not break (tests/test_server_tool_schema.py) — all verified via ls before writing.
- Neither refiner nor materializer scope-bounds sanction writing the generated_by/generations header fields shown in roadmap-example.yaml; skipped them (validator does not require them) — registry should either drop them from the golden example or assign a writer.
