# Release 1.0 Readiness — FINAL

Date: 2026-09-14  
Version: **1.0.0**

## Decision

**PT Asset Tool 1.0 is certified for release.**

The final physical automatic gate is PASS with zero automatic blockers. Strict target-content problems remain separate diagnostics; they are not converted into tool capability failures or silently repaired.

## Release boundary

In scope: asset census, dependency/reachability evidence, safe recovery, donor lineage/hashes, staging, atomic replace/rollback primitives, case/permission checks, Model0.62/Stage0.72 formats, INX/SMB animation, materials, textures/codecs, T5 asset/effect/audio diagnostics, PRELOAD vs ACTIVATION, UI/tool behavior, package/snapshot certification and documentation.

Out of scope/nonblocking: legacy gameplay/runtime Tier 1–4 behavior, Mixed Physique physical certification, and target-content completeness.

## Production safety

Release 1.0 is shipped **safety-locked**. `production_authorized`, `client_write_authorized` and `server_write_authorized` remain false. `WRITER_PROMOTION_AND_PUBLISH_RESTORE` is an explicit operational gate for a later production action, not a reason to mislabel the certified tool package as RC.

## Final package criteria

1. physical `release-1-auto --resume`: automatic PASS / zero automatic blockers;
2. `VERIFY_PACKAGE.sh`: PASS after version bump;
3. fresh-install/registry bootstrap regression: PASS;
4. clean archive excludes `app/pt_build`, generated registry/certifications, caches, historical backups and machine-local configuration;
5. extracted clean archive passes `VERIFY_PACKAGE.sh`;
6. SHA-256 release checksum emitted beside the archive.

See `RELEASE_1_CERTIFICATION.md` for evidence and `KNOWN_LIMITATIONS_1_0.md` for nonblocking content limitations.
