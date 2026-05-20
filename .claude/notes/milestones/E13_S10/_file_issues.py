"""E13_S10 — one-shot helper to file the six gap-candidate issues
via `gh issue create`. Runs once after `gh auth login`; emits a
JSON map `{tag: url}` on stdout that the orchestrator uses to
replace `(TODO file issue: ...)` placeholders in
``.claude/docs/security-threat-model-coverage.md`` with proper
`[#NNN — title](URL)` markdown links.

Not part of the runtime test suite. Living under the milestone's
notes dir keeps it in the audit trail.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

# Full path to gh.exe (winget install does not update PATH in
# already-running shells; this script defaults to the standard
# install location and falls back to a PATH lookup).
_GH_DEFAULT = Path(r"C:\Program Files\GitHub CLI\gh.exe")
GH_BIN = str(_GH_DEFAULT) if _GH_DEFAULT.is_file() else "gh"

REPO = "chris-dare-dev/arXMCP"

# Reuse the same gap definitions as the URL-generator helper.
# Keeping the two helpers in sync is a manual editor's job; the
# audit doc's "Gap-issue triage" table is the source of truth.
GAPS = [
    {
        "tag": "G1",
        "severity": "MEDIUM",
        "title": "Threat 4: extend 256 KB byte cap to remaining tool handlers",
        "body": (
            "Source: `.claude/docs/security-threat-model-coverage.md` (E13_S10 audit), Threat 4 row.\n\n"
            "The 256 KB byte cap on inline tool-result content is enforced today only by `get_chunk` "
            "and `get_definitions`. The other return-chunk tools - `search_papers`, `find_equation`, "
            "`find_lemma_by_name`, `get_paper`, and `cite_neighbors` - do NOT enforce the cap, "
            "leaving a partial-coverage gap against Threat 4 from "
            "`.claude/notes/08-security-observability-ops.md`.\n\n"
            "**Tasks:**\n"
            "- [ ] Extend byte-cap enforcement to `search_papers`\n"
            "- [ ] Extend byte-cap enforcement to `find_equation`\n"
            "- [ ] Extend byte-cap enforcement to `find_lemma_by_name`\n"
            "- [ ] Extend byte-cap enforcement to `get_paper`\n"
            "- [ ] Extend byte-cap enforcement to `cite_neighbors`\n"
            "- [ ] Add regression tests in `tests/security/test_resource_exhaustion.py`\n"
            "- [ ] Update `.claude/docs/security-threat-model-coverage.md` Threat 4 row\n\n"
            "**Severity:** MEDIUM (real coverage gap, not a documented deferral)."
        ),
        "labels": ["area:security", "tier:5"],
    },
    {
        "tag": "G2",
        "severity": "MEDIUM",
        "title": "Threat 7: add redirect-host validation to graph_ingest + inspire_ingest",
        "body": (
            "Source: `.claude/docs/security-threat-model-coverage.md` (E13_S10 audit), Threat 7 row.\n\n"
            "`ingest/ar5iv_fetch.py` and `ingest/oai_delta.py` both validate the post-fetch "
            "`response.url.startswith(...)` against their expected host. `ingest/graph_ingest.py` "
            "(OpenAlex) and `ingest/inspire_ingest.py` (INSPIRE-HEP) do NOT perform the same check, "
            "leaving a redirect-host TOCTOU surface where a poisoned upstream could send a 30x to "
            "an attacker-controlled host and we would silently follow.\n\n"
            "**Tasks:**\n"
            "- [ ] Add `response.url.startswith(<expected_host>)` guard to `ingest/graph_ingest.py`\n"
            "- [ ] Same for `ingest/inspire_ingest.py`\n"
            "- [ ] Add regression tests in `tests/security/test_source_ingest.py` mirroring "
            "`tests/test_oai_delta.py::TestFetchPageRedirectPin`\n"
            "- [ ] Update `.claude/docs/security-threat-7-audit.md` Known gaps section to mark closed\n\n"
            "**Severity:** MEDIUM. Mitigated in practice by `urllib.request` TLS verification (the "
            "attacker would need a valid cert for the rebinding host), but the layered defense is "
            "missing."
        ),
        "labels": ["area:security", "tier:5"],
    },
    {
        "tag": "G3",
        "severity": "LOW",
        "title": "Threat 3: ship production LaTeXML sandbox (sandbox-exec / seccomp / landlock / Docker)",
        "body": (
            "Source: `.claude/docs/security-threat-model-coverage.md` (E13_S10 audit), Threat 3 row.\n\n"
            "The threat model in `.claude/notes/08-security-observability-ops.md` Threat 3 documents "
            "four production sandbox layers (sandbox-exec on macOS; seccomp + landlock on Linux; "
            "`--read-only` + `--security-opt no-new-privileges` in Docker; dedicated UID). v1 ships "
            "only subprocess isolation + 5-minute timeout + filesystem-write whitelist. The deferred "
            "layers are documented and intended for the E11/E14 operational tracks.\n\n"
            "**Tasks:**\n"
            "- [ ] Decide on the canonical sandbox layer per platform (macOS / Linux / Docker)\n"
            "- [ ] Add the chosen layer to `ingest/ar5iv_fetch.py` or the LaTeXML subprocess entrypoint\n"
            "- [ ] Add hostile-fixture regression tests under `tests/security/test_latexml_sandbox.py`\n"
            "- [ ] Close in `.claude/docs/security-threat-3-audit.md`\n\n"
            "**Severity:** LOW. Not a current production exposure (the subprocess is invoked only "
            "during ingest, not at request time) but tracked here for forward-completeness. Likely "
            "belongs to the E14 operational/observability epic."
        ),
        "labels": ["area:security", "tier:5"],
    },
    {
        "tag": "G4",
        "severity": "LOW",
        "title": "Threat 6: bump BGE_M3_COMMIT_SHA to a safetensors-bearing revision",
        "body": (
            "Source: `.claude/docs/security-threat-model-coverage.md` (E13_S10 audit), Threat 6 row; "
            "also `.claude/docs/security-threat-6-audit.md` `The embedder .bin gap` section.\n\n"
            "The pinned `BGE_M3_COMMIT_SHA = '5617a9f61b028005a4858fdac845db406aefb181'` in "
            "`ingest/embedder.py` ships `pytorch_model.bin` only - no `model.safetensors`. As a "
            "result, `use_safetensors=True` cannot be enforced at the embedder load site today; the "
            "reranker IS fully safetensors-enforced. The SHA pin is integrity-preserving against "
            "revision-pointer attacks even with `.bin`, so this is partial-coverage deferral rather "
            "than an open exposure.\n\n"
            "**Tasks:**\n"
            "- [ ] Check `https://huggingface.co/BAAI/bge-m3/commits/main` for a commit that ships "
            "`model.safetensors`\n"
            "- [ ] If found: bump `BGE_M3_COMMIT_SHA` in `ingest/embedder.py`, add "
            "`use_safetensors=True` + post-load `.bin` snapshot check to the embedder load path, "
            "and run an MVCC re-encode of `var/arxmcp/corpus/embeddings/`\n"
            "- [ ] Update `.claude/docs/security-threat-6-audit.md` compliance matrix\n\n"
            "**Severity:** LOW. SHA pin is the load-bearing protection; safetensors enforcement is "
            "defense-in-depth."
        ),
        "labels": ["area:security", "tier:5"],
    },
    {
        "tag": "G5",
        "severity": "LOW",
        "title": "Threat 7: implement ARXMCP_PIN_ARXIV_CA SSL-context wiring + refresh procedure",
        "body": (
            "Source: `.claude/docs/security-threat-model-coverage.md` (E13_S10 audit), Threat 7 row; "
            "also `.claude/docs/security-threat-7-audit.md` CA pinning section.\n\n"
            "The `ARXMCP_PIN_ARXIV_CA: bool = False` Config field in `server/config.py` is "
            "forward-compat plumbing today - the field is read but no code consumes it. The actual "
            "SSL-context wiring against a pinned arxiv.org CA bundle is deferred until the CA "
            "rotation cadence is settled so a fixed pin doesn't create operational toil that "
            "exceeds the security benefit at Tier-5.\n\n"
            "**Tasks:**\n"
            "- [ ] Document the arxiv.org CA rotation cadence (live cert inspection + history check)\n"
            "- [ ] Implement an `ssl.SSLContext` consumer that loads a pinned CA bundle when the "
            "flag is set\n"
            "- [ ] Define an operator-refresh procedure (Makefile target or audit-doc runbook)\n"
            "- [ ] Add the INFO startup log line the audit doc currently disclaims as `no current "
            "behavior`\n"
            "- [ ] Regression test in `tests/security/test_source_ingest.py`\n\n"
            "**Severity:** LOW. System trust store + safe-by-default urllib is the production "
            "posture; CA pinning is defense-in-depth."
        ),
        "labels": ["area:security", "tier:5"],
    },
    {
        "tag": "G6",
        "severity": "LOW",
        "title": "Threat 2: evaluate flipping ARXMCP_SANITIZE_RETRIEVED_CONTENT default to on",
        "body": (
            "Source: `.claude/docs/security-threat-model-coverage.md` (E13_S10 audit), Threat 2 row; "
            "also `.claude/docs/security-threat-2-audit.md`.\n\n"
            "The retrieved-content sanitizer at `server/observability/sanitize.py` strips literal "
            "patterns (`<|system|>`, `[INST]`, `Ignore previous instructions`) from returned chunks. "
            "It is OFF by default; the operator enables it via `ARXMCP_SANITIZE_RETRIEVED_CONTENT=1`. "
            "This is a deliberate design trade-off - flipping the default to on without "
            "false-positive data risks mangling legitimate paper content (e.g., a survey paper that "
            "quotes prompt-injection patterns as study material).\n\n"
            "**Tasks:**\n"
            "- [ ] Run the sanitizer (in dry-run / shadow mode) over the current 50-paper math.AG "
            "seed corpus and count false positives\n"
            "- [ ] Run over the full 200K corpus once E11 ingest completes\n"
            "- [ ] If false-positive rate is acceptable (< 0.1% of chunks): flip default to on; "
            "document the rationale in `.claude/docs/security-threat-2-audit.md`\n"
            "- [ ] Add regression test in `tests/security/test_delimiters.py`\n\n"
            "**Severity:** LOW. Sanitizer is opt-in by design; flipping the default requires "
            "false-positive data first."
        ),
        "labels": ["area:security", "tier:5"],
    },
]


def file_one(gap: dict) -> str:
    """File one issue via `gh issue create`. Returns the issue URL
    that gh prints on stdout. Raises on non-zero exit so a partial
    failure does not silently corrupt the result map."""
    # Write the body to a temp file so newlines + backticks survive
    # the shell. `gh` reads --body-file natively.
    body_text = gap["body"]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", encoding="utf-8", delete=False,
    ) as tf:
        tf.write(body_text)
        body_path = tf.name

    try:
        cmd = [
            GH_BIN,
            "issue", "create",
            "--repo", REPO,
            "--title", gap["title"],
            "--body-file", body_path,
        ]
        for label in gap["labels"]:
            cmd.extend(["--label", label])
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            # Surface labels-not-found gracefully — gh prints a
            # `could not add label: X not found` warning and exits
            # non-zero. Retry without labels if that's the only
            # failure mode.
            if "not found" in result.stderr.lower():
                cmd_no_labels = [
                    c for i, c in enumerate(cmd)
                    if not (cmd[i - 1] == "--label" if i > 0 else False)
                    and c != "--label"
                ]
                result = subprocess.run(
                    cmd_no_labels, capture_output=True, text=True, check=False,
                )
        if result.returncode != 0:
            raise RuntimeError(
                f"gh issue create failed for {gap['tag']}: "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
        # gh prints the URL on stdout, e.g.
        # "https://github.com/chris-dare-dev/arXMCP/issues/42"
        url = result.stdout.strip().splitlines()[-1].strip()
        return url
    finally:
        Path(body_path).unlink(missing_ok=True)


def main() -> None:
    result: dict[str, str] = {}
    for gap in GAPS:
        print(f"[filing] {gap['tag']} — {gap['title']}", file=sys.stderr, flush=True)
        url = file_one(gap)
        result[gap["tag"]] = url
        print(f"  -> {url}", file=sys.stderr, flush=True)
    # Emit the result map on stdout for the orchestrator.
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
