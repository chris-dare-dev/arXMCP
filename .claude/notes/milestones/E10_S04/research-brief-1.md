# E10_S04 Research Brief 1 — LaTeXML Version Drift Detector

Researcher: Agent 1 (parallel)
Date: 2026-05-14
Milestone: E10_S04

---

## 1. In-codebase context

### 1.1 Doc-layout rule — LOAD-BEARING DECISION

CLAUDE.md §1 states:

> `docs/` — ONLY user-facing documentation referenced by the root `README.md`. Today: just `docs/install.md`.
> `.claude/` — All other Markdown agents create — design notes, roadmap, milestones, agent-internal references, scans, gate specs.
> When you create a new Markdown file, default to `.claude/` unless the content is BOTH operator-facing AND linked from the root README.

The brief proposes two docs:
- `docs/ops/latexml-drift-runbook.md`
- `docs/ops/cron-jobs.md`

**Assessment:** A drift-runbook is operator-facing (humans run it after alert fires), but only if we plan to link it from the root README. Currently README links only `docs/install.md`. The drift runbook is NOT the kind of user-facing content the README should link — it is an operational procedure for a specific subsystem, not installation instructions. The cron-jobs doc is even more internal — it is a registry of automated tasks, not user-facing.

**Recommendation (binding):** Both docs go under `.claude/docs/ops/` — not `docs/ops/`. The `docs/` tree must remain restricted to `install.md` per the 2026-05-10 consolidation. The implementer should not create `docs/ops/` at all. Use `.claude/docs/ops/latexml-drift-runbook.md` and `.claude/docs/ops/cron-jobs.md`.

### 1.2 LaTeXML invocation — `tools/arxiv_fetch.py::parse_with_latexml`

Confirmed from source:

```python
cmd = [
    "latexmlc",
    str(main_tex.name),
    f"--dest={out_html}",
    "--format=html5",
]
proc = subprocess.run(
    cmd,
    cwd=main_tex.parent,
    capture_output=True,
    text=True,
    timeout=timeout,   # LATEXML_TIMEOUT_SECONDS = 300
)
```

Key facts:
- `shutil.which("latexmlc")` guard: raises `RuntimeError` with install hint if not on PATH.
- `timeout=300` seconds (the module constant `LATEXML_TIMEOUT_SECONDS`).
- `subprocess.run(..., capture_output=True, text=True)` — no `shell=True`, argv form.
- `cwd=main_tex.parent` so `\input{}` relative paths resolve.
- Output is HTML5 at `out_dir/index.html`; success requires exit_code==0 AND file_size>1024 AND `"<math"` appears in output.

The drift detector reuses this exact pattern but is checking `.tex` fixture files (not full arXiv downloads), so no `fetch_eprint` is needed — just `parse_with_latexml` over fixture `.tex` files.

### 1.3 `server/metrics.py` — naming convention

Confirmed from source:
- Prometheus client: `prometheus_client` (Counter, Gauge).
- Namespace pattern: `arxmcp_<subsystem>_<metric>_total` for counters.
- Examples: `arxmcp_cache_lookups_total`, `arxmcp_retrieval_cap_rejections_total`.
- No top-level `NAMESPACE` string — the prefix is embedded in each metric name literal.

The brief's proposed counter `arxmcp_latexml_drift_detected_total` matches the convention exactly. Naming is correct.

A `reset_cache_metrics_for_tests` function exists — the implementer must add a parallel `reset_drift_metrics_for_tests()` function following the same pattern.

### 1.4 `ops/` directory — does it exist?

No `ops/` directory exists at the project root today. The Makefile creates `var/arxmcp/ops/parser-failures/` (gitignored data dir, not the same). The brief proposes `ops/cron/latexml-drift-check.sh` and `ops/latexml-version.txt` — these are NEW top-level paths. The implementer must `mkdir -p ops/cron/`.

### 1.5 `tests/fixtures/` pattern

Confirmed: `tests/fixtures/` contains subdirectories per feature: `chunker/`, `equations/`, `extract_equations/`, `preamble/`. The pattern is consistent. The brief's proposed `tests/fixtures/latexml-drift/` follows this convention.

The `tests/fixtures/equations/` dir contains hand-crafted `.mathml` files (e.g. `int_01_fxdx.mathml`, `sum_0_inf_an.mathml`). These are raw MathML snippets, not full LaTeXML HTML output. The drift fixtures will need to store what `latexmlc` actually produces from each `.tex` file — which is a full HTML5 document. The comparison is against the `<math>` element content extracted from that HTML, not the full document. Implementer must clarify: compare full HTML output OR extracted MathML strings only.

**Recommendation:** Compare extracted MathML strings (content of each `<math>` element), not full HTML. Full HTML includes timestamps, version strings in comments, and other volatile metadata. MathML content is what the TED index actually uses.

### 1.6 `ingest/index_equations.py` — `--rerender-all` flag

The brief's runbook step 2 says `python -m ingest.index_equations --rerender-all`. This flag does NOT exist. From reading `ingest/index_equations.py`, the module walks rows with `mathml_tree_json IS NULL` — it is a tree-JSON indexer for already-extracted MathML, NOT a MathML re-renderer.

The brief conflates two separate operations:
- Re-rendering raw TeX → MathML (the LaTeXML step — done by `ingest/extract_equations.py`)
- Rebuilding the `mathml_tree_pickle` column (the ZSS tree step — done by `ingest/index_equations.py`)

The correct runbook step 2 is:
1. Run `python -m ingest.extract_equations` for all papers (re-renders TeX to MathML via `latexmlc`).
2. Run `python -m ingest.index_equations` (rebuilds tree JSON from the new MathML).

Neither module has a `--rerender-all` flag. The implementer must update the runbook to use the existing modules correctly, NOT add a spurious `--rerender-all` flag to `index_equations.py`.

### 1.7 `docs/install.md` — LaTeXML system dep

LaTeXML is NOT referenced in `docs/install.md` currently. The drift detector requires `latexmlc` on PATH for the cron job and for opt-in integration tests. Since the cron job is ops-only (not a user-facing MCP feature), `docs/install.md` does NOT need updating. The runbook itself (`.claude/docs/ops/latexml-drift-runbook.md`) documents the `latexmlc` requirement.

### 1.8 Makefile — cron/ops targets

The Makefile has NO cron or ops targets today. The implementer may add a `make drift-check` target as a convenience alias for `python -m ops.drift_check`, but this is optional. The brief does not specify a Makefile target.

### 1.9 Cron script structure

No existing cron scripts in the project. The brief proposes `ops/cron/latexml-drift-check.sh`. A bash wrapper around `python -m ops.drift_check` is the cleanest pattern — the Python module holds the logic, the shell script sets up the environment (virtualenv activation, cwd, env vars) and invokes Python.

---

## 2. Prior decisions and lessons

### 2.1 Equations table is EMPTY in the seed corpus

From E10_S03b research synthesis (Finding 4):

> "Of the 50 seed papers, only 2 have raw TeX, and BOTH failed LaTeXML conversion. The seeded corpus does NOT have usable HTML to extract equations from today."

This is a critical constraint for E10_S04: the brief says the drift detector "compares the MathML output byte-for-byte against the stored values in the `equations` table." That comparison path is unreachable at v1 because the equations table is empty.

**The implementer must use checked-in fixture HTML/MathML files as the baseline, NOT the live equations table.** The 5 fixture `.tex` files are rendered once (pinned to the current LaTeXML version), the MathML output is checked in to `tests/fixtures/latexml-drift/`, and future runs diff against these checked-in files. The equations table is irrelevant for drift detection at v1.

### 2.2 The 5 fixture files — drop tikz-cd

The brief proposes: simple fractions, multi-line aligned environments, tikz-cd commutative diagrams, summation, integral.

**tikz-cd is a problem.** LaTeXML's tikz-cd support has historically been partial. E09_S03 research brief 2 confirms "LaTeXML 0.8.8" is the current version. tikz-cd renders as a fallback SVG or fails entirely depending on the package version. This produces noisy, unreliable fixture output and would generate false-positive drift alerts every time the tikz rendering pipeline changes (which is separate from MathML changes).

**Recommendation:** Drop tikz-cd. Replace with `\begin{pmatrix}` matrix notation. This covers a different complexity axis (multi-row, multi-column structures) without the tikz-cd brittleness. Resulting 5 fixture types:
1. Simple fraction: `\frac{a}{b}`
2. Integral: `\int_0^\infty f(x)\,dx`
3. Summation: `\sum_{n=0}^{\infty} a_n`
4. Multi-line aligned: `\begin{align} a &= b \\ c &= d \end{align}`
5. Matrix: `\begin{pmatrix} a & b \\ c & d \end{pmatrix}`

### 2.3 `latexmlc` runtime cost

Single-fixture cost is ~2-5 seconds; 5 fixtures = ~10-25 seconds. This is acceptable for daily cron but too slow for the default pytest run.

**Recommendation:** Introduce a `requires_latexmlc` pytest marker (mirrors the existing `requires_model` marker pattern in the codebase). The integration test that runs `latexmlc` against real fixtures carries this marker and is skipped by default. The cron job runs `python -m ops.drift_check` directly, not `pytest`.

### 2.4 Prometheus counter naming

The proposed `arxmcp_latexml_drift_detected_total` matches the existing project convention (`arxmcp_<subsystem>_<action>_total`). No conflict.

### 2.5 No new pyproject.toml deps

All deps required for the drift detector exist: `subprocess` (stdlib), `pathlib` (stdlib), `logging` (stdlib), `prometheus_client` (already a dep). No additions needed.

### 2.6 HEREDOC commits, GPG signing, `uv run pytest`

Standard landmines apply (CLAUDE.md §8.7, §8.3, §8.8). Use:
- `git commit -F - <<'COMMIT_EOF'` for commit messages with apostrophes.
- GPG signing is enforced; never `--no-gpg-sign`.
- `/Users/chris.dare/Library/Python/3.9/bin/uv run python -m pytest` (not system pytest).
- `assert` is banned — use `if ... raise RuntimeError(...)`.

---

## 3. External sources — LaTeXML version determinism

### 3.1 LaTeXML version output

`latexmlc --version` (or `LaTeXML --version`) prints the version string embedded in the HTML comment footer: `"converted on <date> by LaTeXML (version 0.8.8)"`. The drift detector should capture `latexmlc --version` output and log it alongside any drift alerts.

### 3.2 MathML output stability across versions

LaTeXML's MathML output is NOT byte-stable across minor versions. Version 0.8.7 → 0.8.8 changes include namespace attribute ordering, whitespace normalization, and `<mrow>` insertion/removal. These changes are real and intentional — they reflect improved MathML conformance. The brief's claim that "byte-for-byte change" is realistic is correct.

### 3.3 MathML canonicalization — byte-for-byte vs. lenient

Options:
- **Byte-for-byte:** strict, any whitespace or attribute-order change triggers alert. False-positive risk is low if comparison is on extracted `<math>` element content only (not full HTML).
- **Canonicalized:** strip whitespace, sort attributes. Hides real drift if the canonicalizer is too aggressive (e.g. attribute reordering masks a semantic change).

**Recommendation:** Byte-for-byte at v1 on extracted MathML strings. Justification: the TED index compares MathML tree structure — any change to the MathML string is semantically relevant. The operator inspects the diff on first fire; if whitespace-only changes prove to be noisy, canonicalization can be added in v2. At v1, the conservative choice is correct.

### 3.4 `subprocess.run` security

The existing `parse_with_latexml` uses argv form (no `shell=True`), enforces `timeout=300`, and sets `cwd=main_tex.parent`. The drift detector reuses this exact pattern. No new security concerns.

---

## Open questions (implementer must resolve)

1. **Doc placement:** `docs/ops/latexml-drift-runbook.md` or `.claude/docs/ops/latexml-drift-runbook.md`?
   **Recommendation: `.claude/docs/ops/`** — the runbook is NOT linked from the root README and is agent/operator-internal. Per CLAUDE.md: "default to `.claude/` unless the content is BOTH operator-facing AND linked from the root README." Do not create `docs/ops/`.

2. **Drift detector baseline:** hand-checked-in MathML files or live equations table?
   **Recommendation: hand-checked-in files.** The equations table is empty in the seed corpus; the table-comparison path is unreachable at v1.

3. **Comparison granularity:** byte-for-byte or canonicalized MathML?
   **Recommendation: byte-for-byte** on extracted MathML strings (not full HTML). The full HTML contains volatile metadata (timestamps, version strings in comments). Extract `<math>` element content, compare those strings.

4. **5 fixture papers — drop tikz-cd?**
   **Recommendation: YES — drop tikz-cd.** Replace with `\begin{pmatrix}` matrix notation. tikz-cd has partial/buggy LaTeXML support and would generate noise.

5. **Cron job script type:** bash wrapper around `python -m ops.drift_check` vs. pure bash?
   **Recommendation: bash wrapper calling Python.** The diff logic, Prometheus increment, and logging are cleaner in Python and easier to unit-test with mocks. The shell script is a thin entry point: activate venv, set env vars, invoke `python -m ops.drift_check`.

6. **Python entry point location:** `ops/drift_check.py` vs. `ingest/check_latexml_drift.py` vs. `server/ops/drift_check.py`?
   **Recommendation: `ops/drift_check.py`.** Consistent with the `ops/cron/` location. The drift detector is an ops concern, not ingest or server. Creating a top-level `ops/` module keeps the concern boundary clean.

7. **Test strategy:** integration tests (slow, real `latexmlc`) vs. mock-based (fast, no LaTeXML)?
   **Recommendation: BOTH.** Fast mock-based tests in the default suite (verify diff logic, counter increment, error logging without invoking `latexmlc`). One integration test marked `requires_latexmlc` that runs the actual cron script against real fixtures. The `requires_latexmlc` marker follows the existing `requires_model` pattern in `tests/conftest.py`.

---

## External writes required

Local file writes only:
- `ops/` (new top-level directory)
- `ops/drift_check.py` (new Python module — entry point)
- `ops/cron/latexml-drift-check.sh` (new bash wrapper)
- `ops/latexml-version.txt` (text file — pinned version, or gitignored/created at runtime)
- `tests/fixtures/latexml-drift/` (new fixture subdirectory)
- `tests/fixtures/latexml-drift/*.tex` (5 hand-crafted fixture files)
- `tests/fixtures/latexml-drift/*.expected.mathml` (5 expected MathML output files, pinned)
- `.claude/docs/ops/latexml-drift-runbook.md` (NOT `docs/ops/`)
- `.claude/docs/ops/cron-jobs.md` (NOT `docs/ops/`)
- `server/metrics.py` (add `LATEXML_DRIFT_DETECTED_COUNTER`)

No external network writes. No changes to pyproject.toml.
