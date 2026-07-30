---
name: security-doc-drift-on-multi-byte-magic-sniff
description: Operator-facing security design docs go stale when the implementer widens a check; grep the doc for byte counts / token lists / marker strings whenever the matching code path changes.
metadata:
  type: feedback
---

Security design docs that pre-date the implementation milestone go stale when the implementer
widens a check.

**Why:** textbook-ingest-m4's `.claude/docs/security-pdf-sandbox.md` was written for "first 4
bytes must be %PDF" + 4 dangerous tokens + `<HTML>` (opening uppercase). m4 shipped "first 5
bytes must be %PDF-" + 7 tokens + `</html>`/`</body>` (closing lowercased). The doc is the
OPERATOR-FACING claim; it must move in lockstep with the impl.

**How to apply:** grep the design doc for any byte counts, token lists, or specific marker
strings whenever a milestone touches the matching code path. Same shape as the
bp1-description-vs-handler-validator-drift class — "doc says X, code does Y" — but on the
threat-model-doc surface rather than the BP1 tool-description surface.

Related: [[claim-drift-verify-against-code]], [[bp1-description-vs-handler-validator-drift]],
[[middleware-cap-vs-handler-cap-read-ordering]].
