---
name: kuzu-reopen-guard-nondeterministic-under-refcounting
description: A public-API double-call "reopen" test for the kuzu del-db lock leak passes on pre-fix code under CPython refcounting; assert close() was called instead
metadata:
  type: feedback
---

A regression test that exercises the kuzu 0.11.3 Windows lock-leak fix by calling
an async lib fn (e.g. `cite_neighbors`) TWICE against the same kuzudb_path in one
process does NOT distinguish fixed from `finally: del db` code on CPython.

**Why:** the leak only manifests when a live `kuzu.Connection` (strong ref to the
`Database`, hence the native/Windows lock) OUTLIVES the reopen. In a plain function
the `db`/`conn` locals have no reference cycle, so CPython refcounting frees them at
`return` — the lock releases even under `del db`, and the double-call passes on
reverted code. The deterministic repro needs a retained Connection (a pinned
traceback frame, a generator that yields with `conn` still bound — see
`tests/test_proof_chain.py:116` — or a non-refcounting runtime like PyPy). POSIX
advisory locks tolerate same-process overlap, so the assertion is a no-op there too.

**How to apply:** when a milestone's AC is "add a regression test that asserts no
lock error", flag MEDIUM (test surface) if the test drives the leak through the
public happy path. The deterministic guard is a SPY, not a behavioral reopen: monkeypatch
`kuzu.Database.close` / `kuzu.Connection.close` to set flags/count calls and assert both
ran after the fn returns — that goes red on `del db` on every platform. Same shape as
[[spy-passthrough-vs-binding-forward]] and [[threading-pinned-by-reading-not-assertion]]:
verifying an EFFECT (close was called) beats replaying an environment-dependent SYMPTOM.
Reference idiom lives in commit 6c5ff0d (adhoc-20260712-955c958): nested close, conn
before db, `db is not None` guard ONLY where `kuzu.Database()` is inside the try.
