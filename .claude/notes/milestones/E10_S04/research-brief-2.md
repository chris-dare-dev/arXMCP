# E10_S04 Research Brief 2 — Empirical LaTeXML Behavior & Ops Trace

**Researcher:** Agent 2 (empirical / ops-scenario angle)
**Date:** 2026-05-14
**Milestone:** E10_S04 — LaTeXML version drift detector

---

## 1. Empirical LaTeXML Behavior (Live Results)

All runs performed with `latexmlc (LaTeXML version 0.8.8)` installed at
`/opt/homebrew/bin/latexmlc`.

### 1.1 Version string

```
latexmlc --VERSION
# latexmlc (LaTeXML version 0.8.8)
# (note: --version is not a valid flag; use --VERSION)
```

### 1.2 `\frac{a}{b}` — MathML structure (confirmed)

```xml
<math alttext="\frac{a}{b}" class="ltx_Math" display="block" id="S0.E1.m1">
  <mfrac><mi>a</mi><mi>b</mi></mfrac>
</math>
```

LaTeXML produces exactly `<mfrac><mi>a</mi><mi>b</mi></mfrac>`. No
`<mrow>` wrapper, no namespace attributes on the `<mfrac>` element.

### 1.3 `\begin{align}` — multiple `<math>` per row

An `align` block with two labeled rows produces **4 separate inline
`<math>` elements**, one per column cell per row (left-hand side + right-hand
side, each a separate element). None has `display="block"`. The extractor in
`ingest/extract_equations.py` handles this correctly via the align-group
stitching path (`find_all("math")` on each `<tbody>`).

Concretely: `x = y + z \\ a = b + c` → 4 `<math>` elements:
- `<math alttext="\displaystyle x">...<mi>x</mi>...</math>`
- `<math alttext="\displaystyle =y+z">...<mrow>...</mrow>...</math>`
- (same pattern for row 2)

### 1.4 `tikz-cd` — SVG fallback, NOT `<math>`

LaTeXML renders `tikz-cd` as an `<svg>` element using the
`ltx_picture ltx_markedasmath` class. The labels inside the diagram
(node identifiers like `A`, `B`, `C`, `D`) are rendered as nested
`<math display="inline">` elements embedded within `<foreignObject>` in
the SVG. The morphism arrows (`\arrow[r, "f"]`) have no MathML
representation; the labels `f`, `g` etc. are also inside `<foreignObject>`.

**Critical consequence for the drift detector:** a `tikz-cd` equation
does NOT produce a top-level `<math display="block">` element. The
`_extract_equation_atom` path in `extract_equations.py` will return
`None` for a `tikz-cd`-only equation table (the `<math>` finder fails).
The drift detector's `tikz-cd` fixture will exercise a code path
that the main extractor SKIPS. This is the correct behavior for
an ops tool (we WANT to detect that tikz-cd's SVG format changed), but
the fixture's "expected MathML" is actually expected SVG — the brief
is imprecise here.

**Recommendation:** include the tikz-cd fixture but store expected output
as `<fixture>.expected.svg` not `.expected.mathml`. Or, accept that the
drift check for tikz-cd compares the entire `<math id="...pic1...">` SVG
wrapper; the extractor stores this as `mathml` anyway (it just happens to
be an SVG-containing element).

### 1.5 `\sum_{n=0}^\infty a_n` — `<munderover>`, NOT `<msubsup>`

```xml
<mrow>
  <munderover>
    <mo movablelimits="false">∑</mo>
    <mrow><mi>n</mi><mo>=</mo><mn>0</mn></mrow>
    <mi mathvariant="normal">∞</mi>
  </munderover>
  <msub><mi>a</mi><mi>n</mi></msub>
</mrow>
```

LaTeXML uses `<munderover>` for display-style sum limits.
`<msubsup>` would appear for inline-mode `\sum`. The fixture should use
`\begin{equation}\sum_{n=0}^\infty a_n\end{equation}` to lock in the
`<munderover>` form, not inline `$\sum$`.

Similarly, `\int_0^\infty` uses `<msubsup>` (NOT `<munderover>`) — the
asymmetry is real and version-sensitive. Pin the fixture using `equation`
environment.

### 1.6 CRITICAL: Byte stability across runs of the same version

**Raw HTML output is NOT byte-stable.** Two consecutive `latexmlc` runs
on the same `.tex` input produce output that differs at two locations:

1. An HTML comment: `<!--Generated on Thu May 14 19:55:29 2026...-->`
2. A visible div: `<div class="ltx_page_logo">Generated  on Thu May 14 19:55:29...`

Both differences are in the timestamp. `--nocomments` does NOT suppress
the `<div class="ltx_page_logo">` element; it only suppresses XML comments.

**However:** the extracted `<math>` elements ARE byte-stable. Two runs
compared via `BeautifulSoup.find_all("math")` → `str()` produce an
identical list. The drift detector MUST extract `<math>` elements from
the HTML output, not diff the raw HTML files.

This is exactly what `extract_equations.py::_serialize_mathml(tag)` does —
it calls `str(tag)` on the BeautifulSoup `<math>` element. The same
extraction logic should be reused in the drift detector for consistency.

---

## 2. End-to-End Ops Scenario Trace

**Day 0:** Operator pulls `latexml:0.8.9` container image. Records in
`var/arxmcp/ops/latexml-version.txt`.

**Day 1, 02:00 UTC:** Daily cron fires `ops/cron/latexml-drift-check.sh`.

For each of 5 fixtures (`frac`, `align`, `sum`, `integral`, `tikzcd`):
1. Run `latexmlc --format=html5 <fixture>.tex` → `/tmp/arxmcp-drift/<name>.html`
2. Parse HTML with BeautifulSoup, extract all `<math>` elements via
   `find_all("math")`, join into canonical string.
3. Read `tests/fixtures/latexml-drift/<name>.expected.mathml`.
4. Pretty-print both sides (xml.dom.minidom or lxml) and compare.
5. On diff: `echo "ERROR: drift in <name>" >&2`, write sentinel file
   `var/arxmcp/ops/drift-detected.flag`, exit non-zero.

**Operator sees:** cron mailer / systemd-timer failure / monitoring alert.
Reads `docs/ops/latexml-drift-runbook.md`.

**KEY DEPENDENCY surfaced:** After running `--rerender-all` and
re-running `pytest tests/test_equation_index.py` (per runbook), the
operator MUST also regenerate the fixture expected MathML. Otherwise the
next daily cron will keep alerting on the old expected MathML. The runbook
must include: `ops/cron/latexml-drift-check.sh --update-fixtures` (or
`python ops/regenerate_latexml_fixtures.py`) as step 5 after reindex.

This is analogous to `pytest --update-tool-schema-hash` from E06_S02.

---

## 3. Fixture Management: `tests/fixtures/latexml-drift/` vs `ops/`

**Keep `tests/fixtures/latexml-drift/` per the brief.** Rationale:

- The pytest fast-path mock test (`@pytest.mark.unit`) reads the same
  `.expected.mathml` files to verify the drift check logic without
  invoking `latexmlc`. This makes the fixture files dual-purpose.
- `tests/fixtures/` already contains golden fixtures for the chunker
  (see `.claude/docs/chunker-fixtures.md`). The pattern is established.
- A docstring at the top of each fixture should document the dual role.

**File format:** `<name>.tex` (input) + `<name>.expected.mathml` (baseline).
The `.expected.mathml` file contains the extracted `<math>` element(s),
pretty-printed (one element per file for simple equations, multiple joined
by `\n` for multi-row align). NOT the full LaTeXML HTML output.

---

## 4. Prometheus Counter Exposure Path

`server/metrics.py` is the **live server process** registry. The drift
detector is a **separate cron process**. Cross-process Prometheus
coordination is non-trivial. Options:

**Option A — Sentinel file (recommended for v1):** The cron script writes
`var/arxmcp/ops/drift-detected.flag` when drift is found, deletes it after
operator clears via `--clear-flag`. The server's `/metrics` scrape-time
hook reads this file and reports the counter. This reuses the pattern
already used by `var/arxmcp/ops/parser-failures/` (which exists per
`make bootstrap`).

**Option B — Prometheus textfile collector:** Requires node_exporter
running with `--collector.textfile.directory`. Not warranted at v1; this
is E14 (observability/ops) scope.

**Option C (opinionated scope-narrowing):** Do not expose via Prometheus
at v1. Log to stderr/syslog only. The brief's AC says "the counter
increments when drift is detected" — a unit test can verify an in-process
counter by patching the flag-write with a mock that checks counter
increment. Production counter exposure via Prometheus is deferred to E14
alongside the full OTel/metrics refactor.

**Recommendation: Option C + sentinel file.** Log ERROR to stderr (cron
mailer catches it), write sentinel file for operator visibility, add the
`arxmcp_latexml_drift_detected_total` counter to `server/metrics.py` but
wire it only to the sentinel-file reader at `/metrics` scrape time. The
AC's "counter increments" is verified by a unit test that patches the
file write; production Prometheus exposure is real but deferred to E14
integration. This keeps the server boundary clean: the server process never
invokes `latexmlc`.

---

## 5. Doc Placement Decision

The brief specifies `docs/ops/latexml-drift-runbook.md`. CLAUDE.md §1 is
unambiguous:

> `docs/` | ONLY user-facing documentation referenced by the root README.md.
> Today: just `docs/install.md`.

A LaTeXML drift runbook is **operator-facing** (an operator reads it when
the cron alert fires). It is NOT referenced from the root README.md today.
Both researchers must converge on one of:

1. **`.claude/docs/latexml-drift-runbook.md`** — strictly correct per
   CLAUDE.md but breaks the brief's specified deliverable path.
2. **`docs/ops/latexml-drift-runbook.md`** — matches the brief; requires
   creating `docs/ops/` subdir AND adding a README.md link to it from
   the root README to satisfy the doc-layout rule.

**Recommendation: option 2 — `docs/ops/latexml-drift-runbook.md`.** The
brief is explicit. The `docs/` restriction is "ONLY user-facing referenced
by root README" — add a minimal "Operations" section to README.md linking
`docs/ops/latexml-drift-runbook.md`. This is the correct long-term
position for operator runbooks anyway (E14 will add more). The brief's
`docs/ops/cron-jobs.md` companion document confirms this intent.

---

## Open Questions — Different Angles from Peer

**1. Pretty-print MathML vs byte-for-byte raw HTML diff?**

Recommendation: **pretty-print extracted `<math>` elements** (NOT raw
HTML diff). Rationale: raw HTML is non-stable across runs due to timestamp
injection (empirically verified). Extracted `<math>` IS byte-stable, but
pretty-printing before comparison improves error messages on drift ("at
`<mfrac>` line 3, expected `<mi>a</mi>` got `<mn>a</nn>`" is readable).
Pretty-printing is a minimal canonicalization (whitespace normalization
only); it does NOT mask attribute reordering — if LaTeXML changes
attribute order between versions, the diff still surfaces it.

Counter-argument your peer may raise: "pretty-printing is canonicalization
and could mask real changes." Surface this tension explicitly in the
implementation comments.

**2. Prometheus counter exposure: sentinel file / textfile / in-process / log-only?**

Recommendation: **sentinel file + in-process counter wired to scrape-time
reader**, with full Prometheus exposure deferred to E14. See §4 above.

**3. tikz-cd fixture: include or skip?**

Recommendation: **include**. LaTeXML's tikz-cd SVG output is the most
likely to change across versions (it's PGF-level rendering, not core
MathML). The fixture exercises a genuine drift risk. Rename the expected
file `tikzcd.expected.svg` or `tikzcd.expected.html` to reflect the actual
content type, and add a comment explaining the extractor skips this in
normal operation.

**4. `tests/fixtures/latexml-drift/` path — accept or move to `ops/`?**

Recommendation: **accept the brief's location**. Dual-purpose: pytest unit
tests + cron reference data. Add a `README.md` (the only `.md` allowed in a
subdir per CLAUDE.md) explaining the dual role.

**5. Runbook location?**

Recommendation: **`docs/ops/latexml-drift-runbook.md`** with a root
README.md link added. See §5 above.

**6. `latexmlc` timeout per fixture?**

The production ingest uses 300s (5 minutes) for full papers. Drift-detector
fixtures are minimal standalone `.tex` files (< 20 lines each). Live test:
`frac.tex` converted in < 1 second. Recommendation: **15 seconds**.
This is tight enough to detect hangs (which would themselves indicate a
LaTeXML regression) and generous relative to observed 0.3s actual runtime.
The brief suggests "~10s total for 5 fixtures" — 15s per fixture is
correct for individual timeout, leaving the shell script under 75s total
wall time on a slow CI node.

**7. `--update-fixtures` flag for regenerating expected MathML?**

The operator workflow requires regenerating fixture expected MathML after a
LaTeXML upgrade. Implement as:

```bash
ops/cron/latexml-drift-check.sh --update-fixtures
```

This re-runs `latexmlc` on all 5 `.tex` files and overwrites the
`.expected.mathml` files in `tests/fixtures/latexml-drift/`. The operator
runs this after confirming the new LaTeXML version is intentional, then
commits the updated fixtures. Analogous to `pytest --update-tool-schema-hash`.

---

## External Writes Required

None beyond local file writes within the arXMCP repository:
- `ops/cron/latexml-drift-check.sh` (new file)
- `ops/cron/` directory (new)
- `tests/fixtures/latexml-drift/*.tex` + `*.expected.mathml` (5 pairs, new)
- `docs/ops/latexml-drift-runbook.md` (new file)
- `docs/ops/` directory (new)
- `server/metrics.py` (add counter + sentinel-file reader hook)
- `README.md` (add minimal "Operations" section linking the runbook)
- `Makefile` bootstrap target (add `var/arxmcp/ops/` subdir for sentinel file,
  already partially done: `var/arxmcp/ops/parser-failures` exists)

No network calls, no external APIs, no PyPI packages beyond what is already
in `pyproject.toml` (BeautifulSoup, defusedxml, prometheus_client all
present).
