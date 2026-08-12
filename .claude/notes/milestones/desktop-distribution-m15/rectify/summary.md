# Rectify summary — desktop-distribution-m15

Critique: `.claude/notes/milestones/desktop-distribution-m15/critique/dedup.md`
(merged ids from three critics). Commit range rectified against:
`525de97..b8c0a1c`. Dispositions written through
`milestone-pipeline-findings.py set` (the sole status writer);
`findings.py gate` exits 0 with no open findings.

**27 findings: C1 H3 M16 L7. 20 fixed, 7 deferred, 0 invalidated
(invalidation rate 0%).**

## The finding that matters most is a repeat

**C1/H2/H3 are one defect found by all three critics: `DESKTOP_BUNDLE_GATE`
was missing from `tests/conftest.py::_DESKTOP_GATE_ENV`, so the zero-skip
guard never armed for `make desktop-bundle-check`.** The adversary graded it
CRITICAL rather than HIGH for the right reason — **it is m6's H3 verbatim**.
That guard was already found unarmed once in this epic and fixed; m15
reintroduced it for a new gate.

Why it recurs is now recorded in the code rather than in milestone notes: the
Makefile's `-m "<token> or not <token>"` expression is a tautology for ANY
token, so a new gate *looks* wired — its tests run, the session exits 0 —
while the half that turns a skip into a failure was never connected, and
nothing in either file mentions the other. The fix therefore ships with a
DERIVED guard, `test_every_desktop_gate_env_var_is_registered_in_conftest`,
which reads the `DESKTOP_*_GATE` set out of the Makefile and requires each to
appear in the tuple. Verified against its RED state by simulating the pre-fix
conftest: it reports exactly `DESKTOP_BUNDLE_GATE` missing.

Consequence worth stating plainly: **the "62 passed, zero skips" figure the
implementation dispatch reported was half-unearned.** The 62 was real; the
"zero skips" was never enforced. It happened to be true. This is also the one
number the orchestrator had flagged as not independently re-run — the critics
found that the gate would not have told the truth about it even if it had
been.

## H1 — an acceptance criterion claimed more than its evidence

AC3 said the artifact "launches by double-click on a clean supported Mac and
reaches a ready server and a rendered window". The gate drives
`--print-child-plan`, which resolves the payload and exits without loading
models or starting a server. The limitation was disclosed — in an
implementation note, not in the criterion it failed to meet.

That is the same shape as m10's AC1 fixture substitution, which is the thing
m15 was written to retire. The AC is now narrowed to what is measured, and
the full launch proof is recorded as `desktop-distribution-m11`'s stated
obligation, with the reason it is not in m15's gate: it needs the real frozen
child to load BGE-M3 and the reranker (~4.6 GB from the external HF cache),
which would make bundle assembly depend on model weights.

## What the critics attacked and CLEARED

Recorded because a clean result from an adversarial pass is evidence, and
because three of these were the orchestrator's own suspicions:

- The outer seal genuinely **does** cover nested payload Mach-O bytes,
  framework-shaped ones included — established by live `codesign` experiment,
  not by reading the code.
- `resolve_inside()` is genuinely byte-unchanged, so m10's symlinked-root fix
  is preserved by construction rather than re-derivation.
- Bundle-over-sibling precedence is genuinely tested in both languages.

M1 was still filed against the first of those — the property held, but the
gate never *measured* it. That distinction is the correct one and the fix
adds the measurement.

## Dispositions

| id | sev | disposition | one-line |
|----|-----|-------------|----------|
| C1, H2, H3 | CRIT/HIGH | fixed | gate env var registered + Makefile-derived guard, RED-verified |
| H1 | HIGH | fixed | AC3 narrowed to what is measured; full launch proof assigned to m11 |
| M1 | MED | fixed | seal coverage measured by mutating a payload byte in a copy |
| M2, M8, M15 | MED | fixed | stale `assembly-report.json` unlinked before assembly can fail |
| M3, M7 | MED | fixed | scanner: weak cues dropped, cue must precede claim, 6 patterns + 8 corpus entries added |
| M4 | MED | fixed | m8's weights-free guard re-run over the whole assembled `.app` |
| M5 | MED | fixed | both declared floors and the census measured off the artifact |
| M6, M10 | MED | fixed | same-run positive control on the quarantine negative |
| M9 | MED | fixed | win32 guard on the ungated symlink test |
| M11 | MED | fixed | unsealed `.app` actually removed, making three documents' claim true |
| M12 | MED | fixed | `tauri build` env scrubbed of 12 signing variables |
| M13 | MED | fixed | version-pin vs hash-pin difference stated against the PyInstaller precedent |
| M14 | MED | fixed | clean path reclaims the `.app` and the Rust release profile |
| M16 | MED | fixed | m7's pristine manifest captured before signing |
| L1–L7 | LOW | deferred | owner decision; reasons recorded per finding |

## Two fixes chosen against the easier option

- **M11** offered "delete the bundle" or "reword the three documents". The
  documents were reworded down in the critic's proposal; the behavior was
  changed instead, because "assembly never leaves an unsealed `.app`" is the
  claim worth having and it was one `rmtree` away from being true.
- **M3/M7** could have been closed by adding the missed phrasings alone. The
  positional rule (a cue disclaims only what FOLLOWS it) is the structural
  half — without it, the next phrasing nobody has written down yet gets the
  same free pass.

## What remains open, by decision

- **Notarization.** ADR Decision 3, unchanged: needs a build-and-submit trial
  under the Developer ID certificate e4 is blocked on. A locally valid seal is
  not evidence about it, and the scanner now fails on any document that says
  otherwise.
- **Gatekeeper path translocation.** Unverified; a quarantined ad-hoc-signed
  bundle does not launch at all, so translocation cannot be induced here. The
  negative is asserted — now with a same-run positive control — so the gap
  stays visible inside a green run.
- **The PyInstaller executables' `minos` 11.0 vs the declared 14.0 floor.**
  Measured and pinned, deliberately not reconciled: raising it means
  rebuilding the CPython bootloader, with its own hash-pinning consequences.
  The artifact carries two declared floors and the documents now say so.

## Gate results (orchestrator-measured, serialized, after rectification)

| gate | result |
|---|---|
| `make test` | exit 0 — **5202 passed**, 120 skipped, 1 xfailed, 0 failed |
| `make desktop-conformance` | exit 0 — cargo 27+8, fmt/clippy clean, pytest 42+30+33+24 = **129 passed, zero skips** |
| `make desktop-bundle-check` | exit 0 — **72 passed, zero skips** (full rebuild + reassembly) |

The bundle gate was re-run to completion by the orchestrator this time, not
taken from the implementer's report — and it is the first run in which its
zero-skip claim is enforced rather than merely stated.
