# Research synthesis — desktop-distribution-m7

Mode: `--deep` (explore + adversarial; the general/external lens was covered by
the committed e4 blocker research). Briefs: `research/brief-1.md` (explore),
`research/brief-3.md` (adversarial).
Brief source: `legacy-prose plans/desktop-distribution-roadmap.md` (6 ACs).

## 1. Cross-agent agreement

- **`server/desktop_child.py` has NO `multiprocessing` import and no
  `freeze_support()` call** (both agents grep-confirmed; `:335-389`). AC3 is
  greenfield implementation, not verification of existing behaviour. This is
  the single biggest correction to the milestone's implied scope.
- **PyInstaller must NOT enter `pyproject.toml`/`uv.lock`.** The repo already
  has a live precedent for exactly this shape: `pyproject.toml:325-333`
  installs MinerU into a separate venv (`~/venvs/mineru`) and reaches it via
  `ARXMCP_MINERU_BIN`, deliberately keeping a heavy tool out of the locked
  runtime set. PyInstaller pinned by SHA-256 in its own build venv follows
  that precedent, and avoids perturbing `wheel-check`'s 191-entry expectation.
  Accepted cost: the build is then not reproducible from the lockfile alone.
- **Two ACs rest on unmeasured assumptions** — AC1's determinism exception set
  and AC5's `.pyc` `co_filename` leakage. No `.spec` exists to build from, so
  neither has ever been observed. Phase 2 must treat both as open discovery,
  not settled fact.

## 2. AC1 determinism — the verdict

**As written, AC1 is not honest.** "Byte-identical, exceptions documented"
degrades into an open-ended exception list, because PyInstaller embeds
timestamps, build paths and archive ordering. An AC that ends as
"byte-identical except for the forty things that differ" proves nothing and
is worse than never claiming determinism.

**Proposed replacement (adversarial brief):** a **closed, size-pinned
exception set** with its own regression — the exceptions are enumerated
explicitly, their count is asserted, and the test fails if a new one appears.
That converts an unbounded escape hatch into a tripwire: drift becomes a
failure rather than a footnote.

This is an acceptance-criterion change and is the owner's call, not mine.

## 3. Two hazards found in the repo itself

- **A hollow-test precedent for AC3 already exists.**
  `tests/test_desktop_sidecar_spike.py:83-90` mocks `freeze_support` and
  asserts it was called — proving the mock, not the behaviour. AC3 must spawn
  a real subprocess and observe that no duplicate top-level process appears;
  copying the neighbouring pattern would satisfy the letter and miss the point.
- **The untracked `build/` directory collides with PyInstaller's default
  `--workpath`.** A separate session is changing `.gitignore` for that exact
  directory right now. m7 must set an explicit workpath rather than inherit
  the default, or the two will interfere.

Also flagged: m6's critique (`findings.json:240`) already recorded and fixed
"expensive desktop test running unmarked in default `make test`". m7 risks
repeating it — a 759 MB, ~74 s build must not land in a default gate
unguarded.

## 4. Scope

Midpoint estimate **~700 LOC**, straddling the 800-LOC soft abort once AC3 is
counted as greenfield rather than verification. Build cost is the other axis:
AC1 requires TWO consecutive builds of a 759 MB / 5,530-file artifact at
~74 s each, against a `desktop-conformance` currently ~50 s and a `make test`
at ~315 s.

## 5. Affected files

New: a PyInstaller `.spec`, `hook-latex2mathml.py`, a build/sanitize/scan
driver, `make desktop-package`, tests.
Modified: `server/desktop_child.py` (`freeze_support`), `Makefile`.
Open question: whether production code belongs in `tools/desktop_sidecar_spike.py`
— it is explicitly `_spike`-named and is the only committed precedent.
Explicitly NOT modified: `pyproject.toml`/`uv.lock` dependency sets,
`.gitignore` (owned by a concurrent session), `server/**` beyond the entry point.

## external_writes_required

- `git push origin main` (per-event authorization).

## Estimated diff size + file count (Phase-2 gate input)

**~700 LOC (midpoint) across ~7–9 files** — straddles the 800-LOC abort.
Owner decision required before Phase 2.
