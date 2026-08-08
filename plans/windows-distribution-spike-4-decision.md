# Windows distribution support-floor decision

Status: **UNCERTAIN — candidate boundary selected; support promotion pending**
Decision date: 2026-08-08
Roadmap: `plans/windows-distribution/roadmap.yaml`
Tracking issue: https://github.com/chris-dare-dev/arXMCP/issues/413

## Decision

Target Windows 11 25H2 x64 with CPython 3.12 as the first release candidate. Keep the first Windows release x64-only. Do not describe any Windows tuple as supported until the frozen distribution passes the complete executable gate on a distinct reverted or factory-clean Windows 11 25H2 x64 host.

Native Windows ARM64 is not release-ready at the current lock. `torch==2.11.0` and `lancedb==0.30.2` have neither Windows ARM64 wheels nor locked source distributions, and eight additional native packages lack locked ARM64 wheels and would require unproved source-build paths.

## Candidate dispositions

| Tuple | First-release disposition | Reason |
|---|---|---|
| Windows 11 24H2 x64 | Unsupported | Home/Pro servicing ends 2026-10-13, before the 2026-11-20 beta horizon. |
| Windows 11 24H2 ARM64 | Unsupported | Same lifecycle exclusion, no native clean-host sample, and unresolved ARM64 closure. |
| Windows 11 25H2 x64 | Candidate; not yet supported | Locked x64 dependencies and current-host build evidence exist, but no distinct clean-host executable pass exists. |
| Windows 11 25H2 ARM64 | Unsupported | No native host evidence; two hard lock blockers and eight further native dependency gaps. |
| Windows 11 26H1 ARM64 | Unsupported | New-device-only release requiring eligible native hardware; no exact executable evidence and unresolved ARM64 closure. |

There is no Windows 11 26H1 x64 candidate. Microsoft scopes 26H1 to select new devices, with initial devices based on Qualcomm Snapdragon X2 hardware.

## Evidence

- All five candidate rows have explicit eligibility dispositions; zero rows are labeled supported without clean-host evidence.
- Three Microsoft lifecycle/release sources were archived with retrieval timestamps and SHA-256 hashes.
- The exact `uv.lock` yielded 24 Windows-native package records: x64 artifacts are available for the selected CPython 3.12 direction; ten packages lack ARM64 wheels, including two hard gaps without locked source distributions.
- The present developer host is evidence class `current-host/build`, explicitly not a clean-host sample.
- No distinct clean-host or native ARM64 host was available. Contract, offline-model, ambient-runtime, manifest, native-load, and shutdown gates therefore remain unmeasured.
- The deterministic spike result was `UNCERTAIN` (two of three criteria passed), and the independent review verdict was `ACCEPT`.

Canonical local evidence: `.claude/notes/spikes/windows-distribution-spike-4/`.

## Promotion gate

Promote Windows 11 25H2 x64 from candidate to supported only after one distinct clean-host run demonstrates all of the following with raw logs and exact exit codes:

1. Detached transfer manifest validates before and after execution from an effectively read-only application location.
2. No ambient Python, Git, repository, model cache, or prior application state contributes to the run.
3. The shared desktop v1 contract fixtures pass byte-for-byte.
4. The frozen runtime serves `/readyz` and `/ui/`, completes one MCP request, and discovers the pinned model offline.
5. Native imports and DLL loading complete without gaps, and bounded graceful shutdown succeeds.

Until that gate passes, release messaging must say **Windows 11 25H2 x64 candidate**, not **Windows supported**.
