# Security: PDF subprocess sandbox profile (textbook-ingest e2)

**Spike output:** textbook-ingest-spike-2 from
`plans/textbook-ingest-roadmap.md` Phase 3. Drafted **before** the e2
implementation milestone so the threat surface and mitigation
discipline are settled before any operator-supplied PDF reaches a
subprocess.

**Scope:** the textbook-ingest pipeline's PDF-handling subprocess
calls — primarily `mineru` (parser per pdf-ingest-2026 CAND-1; **B1
shipped MinerU 3.2.0** with `[pipeline,mlx]` extras, validated by smoke
test on Milne SVI 2026-05-27) but also the **m6 LaTeXML re-render pass**
(`latexmlc` invoked by `ingest/textbook_renderer.py` via the existing
`tools/arxiv_fetch.py::parse_with_latexml` helper) and any future
ColPali / pdfid / VLM helpers under the same trust boundary. Older
revisions of this doc referenced "MinerU 2.5"; the 3.2.0 pin
supersedes — the architectural change (MinerU 3.x spawns an internal
FastAPI server subprocess) is annotated where load-bearing.

**m6 latexmlc peer-subprocess (textbook-ingest-m6).** After MinerU
emits markdown, the m6 renderer wraps it as a minimal LaTeX document
(`\documentclass{article}\usepackage{amsmath,amssymb}\begin{document}…
\end{document}`) and invokes `latexmlc --format=html5` via the existing
`parse_with_latexml` helper — which inherits the E13_S03 LaTeXML
sandbox profile (sandbox-exec on macOS, bwrap on Linux) AND the
process-group kill discipline (`start_new_session=True` + `os.killpg`
on `TimeoutExpired`). Markdown prose constructs (``## headers``,
``**emphasis**``, ``[links](urls)``) render as literal characters in
the HTML output — best-effort; the math (`$..$` / `$$..$$`) renders
correctly as MathML. The retrieval substrate consumes math, not prose
layout, so prose-render imperfection is invisible at the chunker
boundary.

**Threat tier:** Peer of Threat 3 (LaTeXML sandbox) and the
parser-fidelity-eval-m1 CDM sandbox
(`.claude/docs/security-cdm-sandbox.md`). PDFs are a strictly LARGER
attack surface than LaTeX source — operator-supplied textbook PDFs
are typically third-party-published binaries whose provenance arXMCP
cannot vouch for, vs LaTeX source which is at least author-traceable
on arXiv.

---

## Threat surface

PDF parsing is Turing-complete-adjacent (PDF allows embedded
JavaScript, embedded fonts that decompress, polyglot constructions,
and stream filters that can chain to arbitrary depth). MinerU's
upstream code path runs PyMuPDF / Pillow / a vision-transformer
inference loop — every layer is a potential attack surface against
adversarial inputs.

| Vector | Risk | Mitigation in e2 |
|---|---|---|
| Embedded JavaScript in PDF | RCE on viewers; behavior change on parsers that evaluate JS | **Pre-flight pdfid check** at upload time: reject any PDF with `/JS` or `/JavaScript` entries. Mirrors the m6 m8 upload's magic-byte sniff pattern. PyMuPDF inside MinerU does NOT execute JS but other downstream pipelines might; defense-in-depth |
| Polyglot file (PDF + ZIP, PDF + HTML, PDF + JAR) | Bypass downstream content-type checks; confusion attacks | **Strict magic-byte sniff** at upload: first 5 bytes must be `%PDF-` per ISO 32000-1:2008 §7.5.2. **Reject** any file whose first 5 bytes match `%PDF-` AND whose final 1 KB also contains a polyglot tail marker — `PK\x05\x06` (ZIP end-of-central-directory), `</html>`, or `</body>` (lowercase; case-insensitive match) — per the canonical implementation at `server/routes/notebooks.py::_POLYGLOT_TAIL_MARKERS` |
| Decompression bombs in stream filters (`/FlateDecode`, `/LZWDecode`) | CPU/memory exhaustion | **`subprocess.Popen` hard memory cap** via `RLIMIT_AS` (POSIX) — mirrors the Lean REPL m3 mitigation pattern. 4 GB virtual memory ceiling; MinerU's nominal working set is ~2-3 GB on M2-class hardware. Plus 30-min wall timeout |
| Embedded fonts that map glyphs to unicode confusables | Information confusion (glyph forgery) | Out of scope for the runtime sandbox — this is a math-fidelity concern, not a security concern. The CDM eval gate (parser-fidelity-eval-m1) catches glyph-substitution at the math-content layer. Document in the `parser_used` chunk-column comment that operators should treat textbook chunks with caution for high-stakes claims |
| Object-graph cycles / deeply nested xref tables | Stack overflow in parser | MinerU's upstream uses PyMuPDF which has a recursion guard; defense-in-depth via the per-subprocess wall timeout |
| Network egress from PDF parser (embedded URL fetches) | Data exfiltration; tracking | **No network** — subprocess started without inherited env vars beyond a whitelist; no `HTTP_PROXY` / `HTTPS_PROXY` inherited; explicit DNS-resolver-free environment. MinerU 3.2.0 with `-b pipeline -m auto` runs ONNX inference from `~/.cache/mineru/` with no external network calls observed in the B1 smoke test; the internal `LocalAPIServer` (see §Implementation architectural caveat) binds loopback only |
| Filesystem traversal via `/EmbeddedFile` or font references | Arbitrary read; arbitrary write | Subprocess `cwd` set to a per-invocation tmpdir under `var/arxmcp/notebooks/<slug>/parsed/<paper_id>/` with NO access to the broader `var/arxmcp/` tree. The notebook-scoped layout (m6) is already the blast-radius boundary; PDF parsing inherits it |
| Resource exhaustion via huge PDFs (500+ MB) | DoS | **Upload cap** is 200 MB per textbook notebook (raised from the 10 MB m8 cap; see m6 ar5iv upload route). Beyond 200 MB, the upload route returns HTTP 413 before MinerU is invoked |
| Page-count exhaustion (PDF with millions of objects, low byte cost) | DoS bypass of the byte cap | **Pre-flight pdfid check**: reject any PDF with `>5000` declared pages. Bourbaki volumes top out around 500 pages; 5000 is a 10× safety margin |
| Polyglot deflated payload (PDF/A with `\write18`-style escape via embedded shell) | RCE on MinerU host | Subprocess discipline (below) — process group kill on timeout; no shell escape pathway available because MinerU is invoked via direct `subprocess.Popen` args, not `shell=True` |

**Mitigation delivery (load-bearing).** Three layers of defense, all
deliberately stacked because PDF parsing is too risky for any single
layer to be load-bearing alone:

1. **Pre-flight gate** at the upload route — magic-byte + pdfid +
   page-count + size checks BEFORE MinerU ever sees the bytes.
2. **Subprocess sandbox** at the parser invocation — RLIMIT_AS,
   process-group kill, no inherited env, cwd-confined tmpdir.
3. **Per-notebook blast radius** — even if a PDF parser is exploited,
   the damage is bounded to one notebook's `var/arxmcp/notebooks/<slug>/`
   subtree. The shared arXiv corpus and other notebooks are not
   reachable from the subprocess.

The pre-flight gate is necessary because some attacks (resource
exhaustion via page count) are cheap to detect at the byte level but
expensive to catch inside MinerU's processing loop.

---

## Implementation: subprocess discipline (pdflatex/cdm-sandbox parallel)

Mirrors `tools/cdm_eval.py::render_latex_to_image` (parser-fidelity-
eval-m1 pattern) plus the Lean REPL m3 `RLIMIT_AS` cap. The shape
below is **prescriptive for e2** — it documents the exact discipline
the implementer must follow. Canonical implementation lives at
`ingest/textbook_parser.py` (shipped in textbook-ingest-m5). When the
two diverge, the implementation wins and this doc updates in lockstep
(m4 F2 anti-pattern: stale docstring is a HIGH-severity finding).

```python
import resource  # Linux-only — see _RLIMIT_AS_PLATFORM below
import subprocess
import signal
import os
import sys
import contextlib

#: Virtual-memory ceiling for the MinerU subprocess. 4 GB is ~2x the
#: nominal working set on a 500-page textbook (measured offline);
#: leaves room for transformer attention spikes without admitting
#: decompression-bomb scenarios. LINUX ONLY — see macOS gap below.
_MINERU_RLIMIT_AS_BYTES = 4 * 1024 * 1024 * 1024  # 4 GB

#: Wall-clock cap. 30 min covers Bourbaki-grade textbooks on
#: M2-class hardware (~1-3 pages/sec). Configurable via
#: ``ARXMCP_MINERU_TIMEOUT_S`` env var (range [60, 3600]).
_DEFAULT_TIMEOUT_S = 30 * 60

#: Platform on which RLIMIT_AS is enforceable. Verified live test on
#: Darwin 25.4.0 / Apple M4 Max (textbook-ingest-m5 research-brief-2):
#: ``setrlimit(RLIMIT_AS, (4GB, 4GB))`` raises ``ValueError`` because
#: the macOS kernel keeps the hard limit at RLIM_INFINITY and refuses
#: lowering. On Darwin the wall timeout is the ONLY memory backstop;
#: see CLAUDE.md §8.
_RLIMIT_AS_PLATFORM = "linux"

if sys.platform == _RLIMIT_AS_PLATFORM:
    def _set_mineru_rlimits() -> None:
        """preexec_fn for subprocess.Popen. Caps virtual memory."""
        resource.setrlimit(
            resource.RLIMIT_AS,
            (_MINERU_RLIMIT_AS_BYTES, _MINERU_RLIMIT_AS_BYTES),
        )
else:
    _set_mineru_rlimits = None  # WARN at import time

def _scrub_subprocess_env(output_dir: Path) -> dict[str, str]:
    """Return a minimal env for the MinerU subprocess.

    Strips proxies, AWS / GCP / Azure / HuggingFace credentials.
    Whitelists ONLY the variables MinerU genuinely needs (PATH for
    binary lookup; HOME for ~/.cache lookup of bundled ONNX models;
    LANG / LC_ALL for locale). ``TMPDIR`` is explicitly OVERRIDDEN to
    ``str(output_dir)`` rather than inherited, preventing cross-
    notebook scratch contamination (textbook-ingest-m5 research-
    synthesis §D4 — failure-mode FM-8).
    """
    keep = ("PATH", "HOME", "LANG", "LC_ALL")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["TMPDIR"] = str(output_dir)
    return env

def run_mineru_sandboxed(pdf_path: Path, output_dir: Path) -> MinerUResult:
    """Run MinerU 3.2.0 on a PDF with the e2 sandbox profile.

    All three defense layers active:
    - RLIMIT_AS 4 GB cap via preexec_fn (LINUX ONLY)
    - 30-min default wall timeout + process-group kill on expiry
    - cwd-confined tmpdir + TMPDIR override (no access outside output_dir)
    - scrubbed env (no proxies, no credentials)
    - no shell escape (Popen args, not shell=True)
    """
    sandbox_env = _scrub_subprocess_env(output_dir)
    cmd = [
        mineru_bin, "-p", str(pdf_path), "-o", str(output_dir),
        "-b", "pipeline", "-m", "auto",  # 3.x defaults to hybrid-auto-engine
    ]
    spawn_kwargs = {}
    if _set_mineru_rlimits is not None:
        spawn_kwargs["preexec_fn"] = _set_mineru_rlimits
    proc = subprocess.Popen(
        cmd,
        cwd=output_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env=sandbox_env,
        **spawn_kwargs,
    )
    try:
        stdout, stderr = proc.communicate(timeout=_DEFAULT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError, OSError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.communicate(timeout=5)  # drain PIPEs; avoid deadlock
        raise
    if proc.returncode != 0:
        raise RuntimeError(
            f"mineru exited {proc.returncode} on {pdf_path.name}: "
            f"{stderr[-500:]}"
        )
    # MinerU 3.x output tree: output_dir/<stem>/auto/<stem>.md
    return MinerUResult(...)
```

`start_new_session=True` puts MinerU in its own process group. On
timeout, `os.killpg` reaps the entire group — necessary because
MinerU spawns helper subprocesses (PyMuPDF, ONNX inference workers)
that outlive a bare `proc.kill()`.

The `preexec_fn` runs in the child between `fork()` and `exec()` so
the limits are inherited by the entire process tree. Anything MinerU
spawns afterward (e.g. its ONNX worker pool) is also capped.

**MinerU 3.x architectural caveat (load-bearing).** MinerU 3.x CLI
launches an internal `LocalAPIServer` (FastAPI/uvicorn) for the actual
parsing work; the outer `mineru` process is a thin CLI client. The
internal server is spawned with its OWN `start_new_session=True`
(confirmed at `mineru/cli/api_client.py:153`), creating a grandchild
in a different process group. `os.killpg` on the outer CLI's pgid
does NOT reap the grandchild FastAPI server. The gap is **accepted**
because the grandchild listens on loopback only with no external
network — worst case is an orphan uvicorn holding GPU memory until
idle-timeout reaps it. See §"What this milestone explicitly does NOT
do" below.

---

## Pre-flight gate at the upload route

Lands at `server/routes/notebooks.py` upload-paper handler for
`kind="textbook"` notebooks. Before any bytes reach disk:

```python
def _is_pdf_bytes(head: bytes) -> bool:
    """Magic-byte sniff. PDF files start with ``%PDF-`` per ISO 32000."""
    return len(head) >= 5 and head[:5] == b"%PDF-"

def _pdf_has_javascript(pdf_path: Path) -> bool:
    """Vendored pdfid (no external dep). Detects /JS, /JavaScript,
    /OpenAction, /AA (additional actions) entries.

    See tools/security/pdfid.py for the vendored implementation
    (pdf-ingest-2026 CAND-2). NOT a full PDF parser — string-grep
    over the PDF bytes for the entries we care about. Defense-in-
    depth before MinerU's PyMuPDF layer sees the file.
    """
    ...

def _pdf_polyglot_check(pdf_bytes: bytes) -> None:
    """Reject polyglot files. The first 5 bytes must be %PDF-; the
    final 1 KB (lowercased for case-insensitive matching) must not
    contain a ZIP central-directory marker or HTML closing tag.

    Raises HTTPException(415) on detection.
    """
    if not _is_pdf_bytes(pdf_bytes[:5]):
        raise HTTPException(status_code=415, detail="not a PDF")
    tail = pdf_bytes[-1024:].lower()
    for marker in (b"PK\x05\x06", b"</html>", b"</body>"):
        if marker.lower() in tail:
            raise HTTPException(
                status_code=415,
                detail=f"polyglot detected (tail contains {marker!r})",
            )

def _pdf_page_count(pdf_path: Path) -> int:
    """Lightweight pre-MinerU page-count probe. Uses PyMuPDF's
    metadata-only mode (does NOT decode page content)."""
    ...
```

**Caps enforced before MinerU is invoked:**

- File size: ≤ 200 MB middleware envelope on `/ui/api/notebooks`
  (`server/main.py::prefix_caps`). textbook-ingest-m4 enforces a
  tighter 10 MB cap for `notebook_kind="arxiv"` notebooks in the
  route handler (HTTP 413), since the middleware can't see the
  notebook record. **Memory-pressure caveat:** the m4 handler reads
  the full body via ``await file.read()`` BEFORE the per-kind cap
  fires, so a 200 MB body uploaded to an arxiv-kind notebook IS
  buffered fully in memory before the handler rejects with 413.
  This is acceptable under the loopback-only deployment model
  (CLAUDE.md "Must run locally in Docker"); operators concerned
  with memory-pressure DoS in a future networked deployment should
  fold the per-kind cap into the middleware (e.g. a prefix_caps
  callable that resolves the cap from request scope).
- Magic bytes: first 5 bytes must be `%PDF-` per ISO 32000-1:2008
  §7.5.2 (case-sensitive; header at offset 0; canonical
  implementation at
  `server/routes/notebooks.py::_is_pdf_bytes`).
- No polyglot tail markers in the final 1 KB (lowercased for
  case-insensitive matching): `PK\x05\x06` (ZIP EOCD), `</html>`,
  `</body>`. ZIP-CD-relocated-via-comment-padding is a documented
  limitation backstopped by m5's MinerU sandbox.
- No PDF JS / auto-action tokens. textbook-ingest-m4 ships a
  7-token detection set (NOT 4): `/JS`, `/JavaScript`, `/OpenAction`,
  `/AA`, `/Launch`, `/SubmitForm`, `/ImportData`. Canonical list at
  `tools/security/pdfid.py::DANGEROUS_PDF_NAMES`.
- Page count: ≤ 5000 declared in any `/Count <int>` PDF token.
  Adversarial `/Count`-with-intervening-PDF-comment is a documented
  limitation (see `_PDF_COUNT_RE` docstring); m5's wall-clock
  timeout is the runtime backstop.

These are independent checks; ANY failure rejects with HTTP 415 or
413 before MinerU sees the file. The full body IS buffered into
memory before the rejection fires (memory-pressure caveat above).

---

## What this milestone explicitly does NOT do

(Same disclaimers as the CDM sandbox doc, scaled up for the larger
threat surface.)

- **Does NOT implement `sandbox-exec` profiles on macOS.** The
  RLIMIT_AS + process-group kill + scrubbed-env + cwd-confinement
  combination is defense-in-depth at the subprocess layer.
  Adding `sandbox-exec` for every MinerU invocation would slow
  textbook ingest noticeably (~5-10s per PDF) without a measurable
  threat-model gain at this milestone's scope, since the per-
  notebook layout already bounds the blast radius.

  **Un-park trigger for adding `sandbox-exec`**: a documented incident
  where a MinerU subprocess exfiltrated data via a font-handling
  child process or via ONNX-runtime initialization.

- **Does NOT implement seccomp/landlock on Linux.** Same reasoning.
  E13_S03's design for LaTeXML calls for these in production-grade
  Linux deployments; textbook ingest is a development-time path
  with operator-curated PDFs, not a production-server hot path.
  Re-evaluate if the parser ever runs against operator-supplied PDFs
  at scale (e.g. an autoformalizer's automated textbook fetch).

- **Does NOT run MinerU as a separate UID.** Same reasoning. The
  textbook ingest subprocess runs as the operator's user; the
  per-notebook tmpdir confinement bounds the damage to one
  notebook's subtree.

- **Does NOT validate font glyph-to-unicode mappings.** That is a
  math-fidelity concern. The parser-fidelity-eval-m1 CDM gate
  catches glyph substitution at the math-content layer. The
  `parser_used` chunk-column tag (textbook-ingest-m2) lets consumers
  de-prioritize Marker/MinerU-sourced chunks for high-stakes
  claims.

- **Does NOT defend against malicious LANGUAGE in the PDF content
  (i.e., adversarial Bourbaki).** Threat 2 (indirect prompt
  injection) covers the chunk-level wrapping (`<retrieved_chunk>`
  delimiters); the e5 milestone extends `truncated_for_license`
  enforcement for non-OA chunks. Neither is in scope for the
  subprocess sandbox.

- **Does NOT reap MinerU 3.x's grandchild FastAPI server on
  timeout.** Documented in §Implementation. The grandchild is
  loopback-only with no external network; worst case is an orphaned
  uvicorn process holding GPU/MLX memory until idle-timeout reaps
  it. Sealing this gap would require either `psutil.children(
  recursive=True)` (introduces a hard dependency) or switching to
  Python 3.11+'s `Popen(process_group=0)` paired with a manual
  grandchild walk — neither change passes the cost/benefit threshold
  given the loopback-only blast radius. Re-evaluate if MinerU adds a
  network-egress backend.

- **Does NOT enforce RLIMIT_AS on macOS.** Verified by live test
  (Darwin 25.4.0, Apple M4 Max): `resource.setrlimit(RLIMIT_AS,
  (4GB, 4GB))` raises `ValueError: current limit exceeds maximum
  limit` because the Darwin kernel keeps the hard limit at
  RLIM_INFINITY and refuses lowering at the process level. The
  `_set_mineru_rlimits` preexec_fn is gated on `sys.platform ==
  "linux"`; on Darwin the function is `None` and a WARN log fires at
  module import. **On macOS the 30-min wall timeout is the only
  memory backstop.** Production deployments per
  [`docs/install.md`](../../docs/install.md) are Linux containers
  (where the cap IS enforced); macOS hits this gap only in developer
  workflows where the threat is qualitatively lower (operator-
  supplied PDFs, not adversarial inbound traffic). Sealing the
  Darwin path would require either `sandbox-exec` profiles (slow,
  out of scope per §earlier-omission) or `ulimit -v` from a shell
  wrapper (adds a fork hop without strong correctness gains over the
  wall timeout). CLAUDE.md §8 documents the landmine.

These omissions are deliberate, documented, and conservative. If the
textbook ingest later runs in a context with elevated risk (an
operator-facing service vs. a `pytest` integration test or single-
operator workflow), this doc gets an addendum and the missing layers
land in a new milestone.

---

## Failure modes covered by tests (e2 will land these)

- `mineru` not on PATH → test skips (per a `requires_mineru` marker
  to land with e2; analogous to `requires_pdflatex` from parser-
  fidelity-eval-m1).
- PDF >200 MB → upload route returns HTTP 413 (pre-flight; MinerU
  never invoked).
- PDF with `/JS` entry → upload route returns HTTP 415.
- PDF with polyglot tail (ZIP central directory in last 1 KB) →
  upload route returns HTTP 415.
- PDF with >5000 pages declared → upload route returns HTTP 415.
- Non-PDF magic bytes → upload route returns HTTP 415.
- MinerU subprocess exceeds RLIMIT_AS → `Popen` exits with OOM-kill
  signal; `RuntimeError` raised with stderr tail.
- MinerU subprocess exceeds wall timeout → process group reaped;
  `subprocess.TimeoutExpired` propagates.
- MinerU subprocess returns nonzero → `RuntimeError` with `stderr[:500]`.
- Decompression bomb in stream filter → caught by RLIMIT_AS
  (consumed memory exceeds cap; OOM-kill).

---

## Spike validation status

This document is the e2 implementer's contract. The synthesis from
`plans/textbook-ingest-roadmap.md` records this as `[MUST]` assumption
#2: *"Subprocess sandbox profile for MinerU under Threat 3 is
sufficient to mitigate PDF-bomb / embedded-JS / polyglot attack
surface for operator-supplied PDFs."*

**Sandbox-profile design: validated by precedent.** Three peer
sandboxes share the discipline:
- `tools/arxiv_fetch.py::parse_with_latexml` (E13_S03 LaTeXML)
- `tools/cdm_eval.py::render_latex_to_image` (parser-fidelity-eval-m1)
- `server/handlers/lean_verify.py` (verification-feedback-m3 RLIMIT_AS)

All three have shipped without incident. The PDF-sandbox profile is
their direct descendant, scaled up to address the strictly-larger PDF
attack surface via the pre-flight gate addition.

**Threat-coverage gap NOT closed by this design:** font-glyph
confusion attacks (a malicious PDF could render the formula
`a = b + c` such that the rendered `b` is actually a Cyrillic
homoglyph). MinerU's character-recognition is byte-level; downstream
consumers should treat textbook chunks with `parser_used="mineru+latexml"`
as second-tier evidence per the parser-fidelity-eval-m1 CDM ranking.
This is documented behavior, not a security flaw.

---

## Cross-references

- E13_S03 LaTeXML sandbox precedent — pattern lifted verbatim
- `.claude/notes/08-security-observability-ops.md` Threat 3 — peer
  threat with the same mitigation discipline
- `.claude/docs/security-cdm-sandbox.md` — parser-fidelity-eval-m1
  CDM gate sandbox (closest existing peer)
- `tools/arxiv_fetch.py::parse_with_latexml` — LaTeXML subprocess
  discipline this doc generalizes
- `tools/cdm_eval.py::_run_subprocess_with_pgkill` — process-group
  kill helper (reusable across e2)
- pdf-ingest-2026 CAND-2 (pdfid carve-out) — vendoring discipline for
  the pre-flight JavaScript-detection check
- pdf-ingest-2026 CAND-7+14 (CDM gate + 20-page textbook fixture) —
  the eval lane this sandbox feeds into
- textbook-ingest e2 (MinerU sandbox milestone) — the milestone this
  spike output unblocks
- textbook-ingest e5 (PDF threat hardening) — the follow-up
  milestone that closes Threat 3.5 (polyglot) + Threat 8 (embedded
  JS) at the design-constitution level and lands the
  `truncated_for_license` snippet enforcement

---

## Resolved questions (textbook-ingest-m5 closed these)

1. **MinerU version pin.** ✅ Resolved by B1: MinerU **3.2.0** with
   `[pipeline,mlx]` extras, validated by direct-API smoke test on
   Milne SVI (3 pages, 33 s, M4 Max + MLX). The 2.5 → 3.x bump brought
   the internal-API-server architecture documented in §Implementation.

2. **Pre-flight `pdfid` vendoring location.** ✅ Resolved by
   textbook-ingest-m4: shipped at `tools/security/pdfid.py` (NOT
   `server/security/`). 7 dangerous tokens detected; canonical list
   at `tools/security/pdfid.py::DANGEROUS_PDF_NAMES`.

3. **Wall-timeout default.** ✅ Resolved: 30 min default,
   configurable via `ARXMCP_MINERU_TIMEOUT_S` (range [60, 3600],
   parsed at module load with explicit RuntimeError on out-of-range
   per the no-silent-clamp AC).

4. **OOM behavior on macOS.** ✅ Resolved (NEGATIVE finding):
   `resource.setrlimit(RLIMIT_AS, ...)` raises `ValueError` on
   Darwin — verified live test on Apple M4 Max. The RLIMIT_AS cap is
   **non-functional on macOS** because the kernel keeps the hard
   limit at RLIM_INFINITY. The implementation gates `preexec_fn` on
   `sys.platform == "linux"`; macOS gets a WARN log at import and
   relies on the 30-min wall timeout as the only memory backstop.
   See §"What this milestone explicitly does NOT do" for the
   accepted-gap rationale.

## Outstanding follow-up (out of m5 scope)

- **`server/lean_repl.py` audit.** The Lean REPL m3 RLIMIT_AS
  precedent uses `sys.platform != "win32"` as the guard — passing
  on Darwin where setrlimit will fail in the child. This is likely
  a latent bug analogous to the one m5 found and fixed. File a
  GitHub issue at `chris-dare-dev/arXMCP` for audit; not in m5 scope
  because Lean REPL is a separate subsystem.
