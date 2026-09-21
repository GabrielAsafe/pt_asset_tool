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


## Consolidação técnica — 2026-09-21

Esta manutenção consolida partículas na UI principal por `pt_asset_tool/particle_service.py`, centraliza diagnóstico de dependências, autodetecta o Real-ESRGAN bundled, mantém enhancement em `app/pt_build/texture_upscale/` como runtime/user data ignorado pelo Git e introduz `READY_TO_DEPLOY.py` para regressão + limpeza segura de caches + snapshot + package verifier + commit Git. A revisão V3.2 corrige o erro de higiene anterior que podia remover `pt_build`/`enhancement`: essas árvores agora são sempre preservadas pelo finalizador.

A certificação física histórica 1.0.0 continua sendo evidência do baseline original. Alterações desta manutenção devem ser avaliadas pela regressão atual e pelos gates físicos no ambiente client/server/Blender antes de qualquer promoção operacional; não se reutiliza evidência histórica como autorização automática para o código modificado.
