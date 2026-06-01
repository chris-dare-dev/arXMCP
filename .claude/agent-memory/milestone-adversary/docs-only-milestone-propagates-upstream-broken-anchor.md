---
name: docs-only-milestone-propagates-upstream-broken-anchor
description: docs-only runbook milestones often add NEW references to an EXISTING broken cross-ref anchor; the upstream alerts.yml already had the broken link, but the new runbook propagates it 3× more
metadata:
  type: feedback
---

When a docs-only milestone authors a new runbook that points at an
existing alert's pre-existing `runbook_url` anchor (e.g.
`failure-modes.md#degraded-modes`), GREP THE TARGET FILE for the
literal anchor. The anchor often does NOT exist (no matching H2/H3)
even though the upstream `infra/prometheus/alerts.yml` already uses
it — the bug is hidden at the alert layer because runbook_url just
opens the page (Prometheus doesn't validate anchors). The runbook
authoring milestone is the one that exposes it: an operator landing
via the runbook's three NEW internal links gets the same
non-jump behavior that the alert's `runbook_url` already had, but
now in three more places.

**Why:** corpus-integrity-completion-m2 created a real runbook
behind `corpus-drift-runbook.md` (m1 wrote a placeholder). The new
runbook's "out of scope" callout, S3 routing, and "See also"
section all link `failure-modes.md#degraded-modes` — that anchor
doesn't exist (no `## Degraded modes` H2 in failure-modes.md).
`alerts.yml:58` had the same broken anchor pre-existing, but only
the runbook authoring made the operator's experience worse by
adding 3 new dead-anchor jump targets.

**How to apply:** On any milestone that touches `docs/ops/*.md` or
`infra/prometheus/alerts.yml`, take every `(file.md#anchor)`
reference in the diff and verify the anchor exists in the target
file via `grep -i "^## \|^### " <target>` against GitHub's
slugification rule (lowercase, spaces → `-`, drop punctuation). If
the anchor doesn't resolve, flag HIGH — broken operator cross-refs
at 2 a.m. are the symmetric counterpart to F3-class "stale code
comment" findings. See also [[regression-guard-pins-names-not-shape]]
for the related "pin shape AND content" pattern.
