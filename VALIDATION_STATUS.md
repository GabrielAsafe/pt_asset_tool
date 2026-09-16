# Validation Status — 2026-09-14

## Overall

**PT ASSET TOOL 1.0.0: CERTIFIED / SAFETY LOCKED**

The final physical `release-1-auto --resume` evidence has `automatic_gate_status=PASS`, no automatic blockers, and runtime/game acceptance is not a PT Asset Tool 1.0 gate. Package/snapshot verification is required again after the version finalization and on the clean extracted archive.

## Operational safety

- production authorization: false by default
- client write authorization: false by default
- server write authorization: false by default
- certification changed client/server: no
- writer promotion + publish/restore: explicit operational action

## Target-content diagnostics

Missing/invalid target textures remain documented in `docs/release/KNOWN_LIMITATIONS_1_0.md`. They are not hidden and do not widen recovery authority.

## Fresh-install maintenance — 2026-09-16

Post-certification package maintenance separates immutable source/reference data from machine-local runtime state. Client-derived registry data, certifications, local configuration, caches and development evidence now live under `app/pt_build/` and are generated per installation. Historical backup trees/intermediate handoffs were removed from the distributed package while final Release 1 certification evidence remains bundled. See `docs/validation/PATCH_2026-09-16_FRESH_INSTALL_STATE.md`.
