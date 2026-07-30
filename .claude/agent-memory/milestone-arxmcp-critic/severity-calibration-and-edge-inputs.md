---
name: severity-calibration-and-edge-inputs
description: Calibration reflexes — verify descopes by tracing the input contract; bytes-preserved vs dropped decides math-fidelity severity; recurring edge-input traps; deferred-without-tracking; env-artifact triage; k3s RO-rootfs.
metadata:
  type: feedback
---

Calibration discipline and recurring edge cases. The meta-lesson: **trace the consequence
class before assigning severity** — a wrong-looking construct that preserves bytes / hits a
benign branch is MEDIUM, not HIGH.

- **verify-descope-by-tracing-input-contract** (textbook-ingest-m8): when a milestone
  DESCOPES a feature as "structurally inapplicable," trace the actual INPUT CONTRACT, don't
  take the synthesis at its word. m8 descoped preamble inheritance ("MinerU sees no author
  macros"); verified CORRECT by reading `textbook_parser.py:351-357` (input is a rendered PDF
  via `-p <pdf_path>`) + `preamble.py:313-358` (`extract_preamble` is `.tex`-source-only). The
  right move on a descope is to confirm the skipped work is genuinely impossible given the real
  data flow, then mark CLEAN with file:line — an over-eager "this skipped work!" HIGH is wrong.
  Counter-balances the deferred-without-tracking reflex.
- **naive-dollar-parity-preserves-bytes-but-misgroups** (textbook-markdown-chunker-m1, MEDIUM):
  a hand-rolled `count("$")`/`count("$$")` math-span parity is wrong for `\$`, `$` in code
  fences, inline-code. Probe live: bytes PRESERVED → chunk MIS-GROUPING / runaway-merge =
  MEDIUM; bytes DROPPED/CORRUPTED = HIGH math fidelity. Here body_text stayed verbatim → MEDIUM.
  Recommend capping merge-run length so one stray `$` can't swallow the document tail.
- **strip-quote-empty-phrase** (notebook-paper-discovery-m2, MEDIUM): a sanitizer that does
  `value.strip()` then wraps in `field:"..."` produces a degenerate `field:""` on
  whitespace-only input. Guard belongs in the sanitizer (return None + skip clause). Test the
  whitespace-only keyword path.
- **dedup-set-versioned-id-mismatch** (notebook-paper-discovery-m3, MEDIUM): a dedup set from a
  junction table that can hold versioned IDs (`2604.26204v3` via URL-paste) fails membership
  against a feed parser that strips `vN` → paper re-proposed. Normalize BOTH sides. Tests that
  seed via `store.add_paper()` directly don't exercise the route-path versioning.
- **deferred-without-tracking** (textbook-ingest-m5, HIGH): a synthesis/summary that punts work
  to a "separate follow-up issue" must actually file it. `gh issue list --repo
  chris-dare-dev/arXMCP` — prior pipelines filed #1-#6, so the expectation is "tracked," not
  hand-waved. HIGH when the synthesis literally promised tracking.
- **parsed-path-leak-vs-m9-redact-precedent** (textbook-ingest-m6, HIGH): a tracker storing an
  on-disk path that surfaces in an operator-facing JSON/HTML field must follow the m9 redaction
  precedent (`ingest_tracker.py::redact_paths` scrubs to var/arxmcp/). m6 stored
  `str(output_html_path)` verbatim — an absolute `/Users/.../` path leaking home/username —
  despite a comment claiming it relativizes.
- **latex-wrapper-end-document-injection** (textbook-ingest-m6, MEDIUM): a "wrap markdown as
  LaTeX" renderer with a hard-coded `\end{document}` loses content when the body contains a
  literal `\end{document}` (LaTeXML stops at the first; only "index.html exists" is checked).
  Also verify a documented cross-restart 409 fallback (`has_running_parse`) is actually CALLED
  by the route, not just implemented at the store layer (dead code + TOCTOU otherwise).
- **k3s-readonly-rootfs-first-exercise** (k3s-rancher-deploy-m1, MEDIUM): first application of
  `readOnlyRootFilesystem:true` leaves the RO posture unexercised (Compose rarely set
  `--read-only`). Implementers redirect only HF_HOME and miss other HOME-cache writers: MinerU
  `~/.cache/mineru`, fontconfig, matplotlib `~/.config/matplotlib`, torch hub → hard
  `OSError [Errno 30]` crash. Grep `~/.cache|HOME|XDG_` in server+ingest. Fix = writable
  emptyDir at ~/.cache or XDG_CACHE_HOME/MPLCONFIGDIR env. Also: `FastMCP("name",...)` uses
  FastMCP's DEFAULT host 127.0.0.1, NOT ARXMCP_BIND_HOST — so a 0.0.0.0 bind does NOT disable
  the /mcp TransportSecurity Host/Origin defense; verify at the FastMCP construction before
  flagging "bind 0.0.0.0 kills inner defense."
- **windows-workstation-test-failure-triage**: on this Windows box, ingest/store/server test
  "failures" are usually pre-existing ENV artifacts, not milestone defects — ModuleNotFoundError
  lancedb/prometheus_client (optional deps), cp1252 UnicodeDecodeError from `read_text()` without
  `encoding=`, subprocess `\U` path-escape SyntaxError. Grep the failure for these before
  attributing to the milestone; run the milestone's own narrow tests in isolation for real signal.

Related: [[claim-drift-verify-against-code]], [[middleware-cap-vs-handler-cap-read-ordering]].
