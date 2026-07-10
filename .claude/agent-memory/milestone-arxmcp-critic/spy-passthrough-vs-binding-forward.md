---
name: spy-passthrough-vs-binding-forward
description: A monkeypatch spy that wraps a native-binding call proves the kwarg was PASSED, not that the binding FORWARDED it to the Rust/C layer — the exact silent-drop class the pin exists to defend
metadata:
  type: feedback
---

When a milestone pins a native-binding option (LanceDB `storage_options`,
any pyo3/Rust-backed kwarg) and the regression test is a monkeypatch spy
that wraps the real call and asserts `captured["kwarg"] == EXPECTED`, the
spy proves the value reached the Python entrypoint — NOT that the binding
forwarded it to the Rust/C layer.

**Why:** notebook-ops-hardening-m2 pinned
`storage_options={"new_table_data_storage_version": "stable"}` precisely
BECAUSE the bare `data_storage_version=` kwarg is accepted in the lancedb
0.30.2 Python signature but silently dropped before Rust (FM-F in that
synthesis). The spy test
(tests/test_notebook_durability.py:237-254) wraps the real
`db.create_table` and asserts the kwarg was passed — so it would STILL
PASS against a future lancedb that silently drops the NEW key the same
way. The read-back test ("table reads back") doesn't help either when the
unpinned default already equals the pinned value ("stable" today): a
fully-dropped option still writes a readable table.

**How to apply:** On any "pin a native-binding option" milestone, after
confirming the spy exists, ask: does ANY test assert the OBSERVABLE
on-disk / runtime EFFECT of the option (the actual format version, the
actual durability behavior), not just that the call received the kwarg?
If no — that is a MEDIUM (latent regression-detection gap), not HIGH:
the source guard + a benign-default read-back bound the blast radius, and
the option does work in the pinned version (verify the installed version
in uv.lock matches the synthesis's claim). The fix is one assertion on
the effect (format-version probe, ideally via a stable API, else an
opt-in trailer read behind a marker), not a rewrite. Counterpart to the
"verify-descope-by-tracing-input-contract" reflex: here the WORK was done
right, the TEST just can't catch the one failure mode it exists for.
