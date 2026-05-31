## 2026-05-31 — onboarding-uplift-m4 — mcp-types-callable-result-return

When a handler (or bootstrap-envelope helper) needs to return a real
MCP-wire `isError=True`, return `mcp.types.CallToolResult(isError=True, ...)`
directly. Returning a plain dict causes FastMCP's `convert_result` to
wrap it in TextContent and hard-code `isError=False`. Use `TYPE_CHECKING`
block + `from __future__ import annotations` for the return type annotation
when the import lives inside the function body (PLC0415 guard).

## 2026-05-31 — onboarding-uplift-m4 — global-cache-test-isolation

`server.cache` has a module-level `_cache_instance` singleton. Tests that
verify "cache is NOT set on failure" must call `cache_mod.reset_cache_for_tests()`
before the test AND restore in a `finally` block. The helper
`_patch_late_bind_heavy_io` in test_bootstrap_mode.py stubs `set_cache` as
a no-op; for failure-path tests you need a variant that does NOT stub
`set_cache` so the real global is observable.

## 2026-05-31 — onboarding-uplift-m4 — worktree-vs-main-untracked-files

Git worktrees do not inherit untracked files from the main tree. Untracked
milestone note files (e.g. .claude/notes/milestones/onboarding-uplift-m4/)
that exist in the main working tree are NOT present in a worktree created
from the same branch HEAD. Create them explicitly in the worktree when the
rectifier needs to append to critique files or create new notes artifacts.
