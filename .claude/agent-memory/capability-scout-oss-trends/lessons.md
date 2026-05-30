# capability-scout-oss-trends — lessons

<!-- Append one generalizable lesson per line as scout runs surface them.
     Format: `YYYY-MM-DD [<scout-id>] <lesson>`. Append only; do not delete. -->
2026-05-28 [2026q2-notebook-ux-storage-ops] All three major S3-compatible self-hosted object stores (MinIO, Garage, SeaweedFS) are AGPL-3.0 or over-engineered for single-workstation use; Litestream (Apache-2.0, WAL streaming) is the correct durability pattern for SQLite-backed local-first apps — no object store required.
2026-05-28 [2026q2-notebook-ux-storage-ops] MinIO stopped publishing community Docker images to Docker Hub and Quay on 2025-10-23; any infra recipe citing `minio/minio:latest` from Docker Hub is broken as of that date.
2026-05-28 [2026q2-notebook-ux-storage-ops] The base docker-compose.yml (deferred since E06) is the structural blocker for all sidecar patterns (Litestream, Gatus, Phoenix base stack); the phoenix-compose.yml convention (loopback binding, SHA digest pins, cap_drop ALL, restart: "no", init: true) is the established project template to follow.
2026-05-28 [2026q2-notebook-ux-storage-ops] Litestream ships on a steady cadence (v0.5.11 Apr 2026); the v0.5 LTX format (Oct 2025) is NOT backward-compatible with v0.3.x WAL replicas — flag when upgrading existing deployments.
