# Research synthesis — desktop-distribution-m6

Mode: `--single`. Brief: `research/brief-1.md` (37 KB, implementation-ready).
Brief source: `legacy-prose plans/desktop-distribution-roadmap.md` (6 ACs).
Base: m5 shipped at `origin/main` `9adcf31`.

## 1. Design decisions this brief SETTLED

- **Fault injection rides a namespaced `launch.extensions` key**, not a new
  wire field. The M3 contract already permits compatible additions only under
  `extensions` with namespaced top-level keys, so this needs no contract
  version bump and no fixture-digest churn beyond the new vectors. The key is
  read ONLY by the test-only `fixture-sidecar`; the production
  `desktop_child.py` never looks at it.
- **The fault matrix drives the REAL supervisor** (`lifecycle.rs` / `main.rs`)
  against the fixture. So the code under test is production supervisor logic;
  only the fault-injecting counterparty is a fixture.
- **The 30-cycle stress and the loopback regression extend the existing
  fixture-only `test_desktop_contract.py` harness**, not the Tauri/real-child
  path — keeping the 30 iterations fast, as AC5's fixture scoping intends.
- **Consolidation worth noting:** the mandatory real-server fault case and the
  "supervisor crash" fault-matrix bullet are the SAME scenario — bare stdin
  EOF with no shutdown frame — and `server/desktop_child.py` ALREADY implements
  that cleanup path. That bullet therefore needs **zero new production code**;
  it is a previously-untested assertion over shipped behavior.

## 2. Scope

| Area | Est. LOC |
|---|---:|
| Fault-injection extension plumbing (supervisor) | 20–40 |
| Fault behaviors (fixture-sidecar, 5 arms) | 100–160 |
| Test-only bound-timeout override | 10–15 |
| Rust redaction primitive (conditional) | 0 or 40–70 |
| Cross-language redaction fixture | 30–60 |
| Fault-matrix tests (6 scenarios) | 220–320 |
| 30-cycle stress + PID/orphan/listener audit | 90–140 |
| Socket-level loopback regression | 60–100 |
| Real-server EOF fault case | 70–110 |
| Doc updates (non-claims, marker doc, fault matrix) | 20–40 |
| **Total** | **~620–1,050** |

Character differs from m4/m5: **test-and-fixture-heavy, not
new-runtime-surface-heavy.** `server/desktop_child.py` gets zero new lines;
the supervisor's non-test-only production changes are extensions threading
plus one env override.

**`--allow-large-diff` authorized by the owner for m6 on 2026-08-08**, in
advance and per-milestone (m5's grant did not carry over). Recorded in
`state.json`.

## 3. The two Spike-3 non-claims stay non-claims

A parent already dead cannot kill a wedged child; a descendant that calls
`setsid()` escapes ordinary process-group cleanup. Brief §2 specifies how the
tests and docs record these as known limits rather than letting a passing
fault matrix imply universal cleanup. This is a correctness-of-claims
requirement, not a nicety — `apps/desktop/README.md` is the doc an agent is
pointed at.

## 4. Evidence discipline (the AC4/AC5 traps)

- 30 cycles must yield **30 DISTINCT PIDs**, not one reused process.
- Orphan and listener audits must assert their OWN probe success. A failed or
  partial `ps`/`lsof` is an evidence failure, never clean absence.
- Loopback must be asserted at socket level against the LIVE bound port, plus
  a probe proving nothing listens on the LAN interface / `0.0.0.0` — not by
  comparing a parsed wire field.
- Deadlines bounded but not aggressive: m3 had to raise 200 ms → 2 s under
  load, and m5's child suite already runs 29.5 s.

## 5. Rust/Python redaction parity

Parity must be proven by a SHARED cross-language fixture
(`contract-fixtures/redaction-vectors.jsonl`) consumed by both languages —
not two independent implementations that can drift. Same discipline the M3
contract fixtures already establish.

## 6. Affected files

New: `apps/desktop/crates/supervisor/src/redact.rs` (conditional),
`apps/desktop/contract-fixtures/redaction-vectors.jsonl`.
Modified: `apps/desktop/crates/supervisor/src/{main,lifecycle}.rs`,
`apps/desktop/crates/fixture-sidecar/{Cargo.toml,src/main.rs}`,
`tests/test_desktop_contract.py`, `tests/test_desktop_child.py`,
`apps/desktop/README.md`, `CLAUDE.md`.
Explicitly NOT modified: `server/desktop_child.py`, `server/config.py`,
`server/main.py`, `server/middleware.py`, `server/tools.py`.

## 7. Open questions

1. Whether the Rust redaction primitive is needed at all depends on whether a
   raw-capture diagnostic is added (brief §4) — decide at implementation.
2. Whether the fixture-digest `fixtures.sha256` update is intentional and
   passes independently in both languages (it must).

## external_writes_required

- `git push origin main` (per-event authorization; `CLAUDE.md` §4.4).
- **m6 closes issue #397** — `Fixes #397` rides the final commit. m5's
  synthesis deliberately deferred this.
- No GitLab/MR/infra surface: entirely in-repo.

## Estimated diff size + file count (Phase-2 gate input)

**~620–1,050 LOC across ~9–11 files.** May exceed the 800-LOC abort;
`--allow-large-diff` is pre-authorized and recorded.
