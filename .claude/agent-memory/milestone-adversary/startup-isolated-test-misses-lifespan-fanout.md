---
name: startup-isolated-test-misses-lifespan-fanout
description: "AC test that exercises Resources.startup in isolation misses lifespan post-startup callees (refresh_metrics, set_resources, mcp register) that may NPE on a new nullable field — HIGH/CRITICAL"
metadata:
  type: feedback
---

When a milestone introduces a new nullable field on `Resources`
(e.g. `corpus_info: CorpusVersionInfo | None` in onboarding-uplift-m4
bootstrap mode), the AC test almost always exercises ONLY
`asyncio.run(Resources.startup(cfg))` in isolation and asserts the
field-is-None semantics. This MISSES the chain of unconditional
`resources.<nullable>.<attr>` reads in lifespan-post-startup callees:

- `server/main.py:444` calls `refresh_metrics_from_singleton_state(resources)`
  which reads `corpus_info.version` and `.chunk_count` UNCONDITIONALLY
  (server/health.py:523,532).
- `set_resources(resources)` publishes the singleton — usually safe.
- `/metrics` scrape middleware calls `refresh_metrics_from_singleton_state`
  again on every Prometheus scrape (server/main.py:781) — repeats the
  AttributeError forever.

The headline AC ("`make up` boots cleanly") is the thing the milestone
PROMISES. The test that proves it requires `TestClient(create_app())`
+ a `/metrics` GET, NOT just `asyncio.run(Resources.startup(cfg))`.

**Why:** the implementer-summary checkbox is verified by an
INSUFFICIENT test. Reviewer notation `[x] AC1` looks satisfied but the
runtime crash is reachable on the first request.

**How to apply:** any milestone that makes a `Resources` field
nullable on a new code path — grep for `resources\.<that_field>\.`
and `corpus_info\.` across the WHOLE server tree (not just handlers).
Each call site outside the orchestrator stub-check is a candidate
crash. The two recurring sites are `server/health.py` (readyz, status,
refresh_metrics_from_singleton_state) and any place a `/metrics`-style
middleware reads from the resources singleton.

The fix is BOTH:
1. None-guard each reader site.
2. Add a `test_lifespan_succeeds_with_<new_state>` smoke test that
   uses TestClient(create_app()) + the env var set + `/healthz`,
   `/readyz`, `/metrics`, AND one tool call. Not a unit test of the
   startup function.

Related: textbook-ingest-m4 D3 "documented limitation pattern won't
save this one — the synthesis was actively wrong, not silent." Same
shape: a synthesis claim that "the test covers it" was technically
true (the unit test passed) but operationally false (the lifespan
crashed before the unit-tested code ran).

See also [[bp1-description-vs-handler-validator-drift]] for the
sibling-pattern where a synthesis claim is true at one boundary
(description) but false at another (handler validator). Both are
"contract verified on one surface, broken on the surface that matters
in production."
