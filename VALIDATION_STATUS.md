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


## Manutenção read-only de retenção — 2026-09-27 / V2.5

A camada de retenção agora cobre calls legacy de efeito que resolvem nomes lógicos para
assets físicos e agrupa subgrafos root-unreachable para revisão. Não adiciona writer,
quarantine ou delete. A certificação histórica 1.0 permanece baseline; esta revisão exige
testes/regressão/snapshot atuais antes de empacotamento.


## Asset Quarantine V2.6 — 2026-09-27

- Q0 plan/apply/restore/stale-plan: PASS.
- Asset retention/effect/census focused suite: 41 passed.
- UI/integration focused suite: 33 passed, 5 skipped.
- RUN_REGRESSION_FOCUSED: 40 passed, 1 skipped; PASS.
- Delete continua não autorizado; Q1 continua review-only.


## Asset Quarantine V2.8 — 2026-09-27

- Q1 manual apply-component: exact component + separate confirmation only.
- Eligibility independent from score: band A, <=10 members, zero protected/entity/positive evidence/external edges, documented invalid required.
- Plan captures member bytes/SHA-256 only for strict eligible components; apply revalidates retention + physical hashes.
- Restore remains transactional; delete remains unauthorized.
- Focused suite: 47 passed. Regression: 40 passed, 1 skipped. Snapshot: 716 files PASS. `VERIFY_PACKAGE=PASS`.
- Current gates are recorded in `docs/validation/INTEGRATION_ASSET_QUARANTINE_Q1_MANUAL_V28_2026-09-27.md`.

## Legacy Authoring Semantic Catalog V2.9 — 2026-09-28

- Catálogo versionado de nome visível → canonical_id/path integrado a ITEM/MONSTER/NPC/MAP.
- Ricarten → village-2 e Map → Stage/Spawn → SPM/SPP/SPC cobertos por teste.
- Códigos sITEM reutilizados não são colapsados; canonical_id é a identidade primária de authoring.
- Ambiguidades permanecem explícitas.
- Related refs de drop/shop/SPM/SPC são validadas contra o spec e preservadas no manifest.
- Não altera quarantine/delete; publish/restore continuam sob os gates existentes.
- Legacy targeted suite: 64 passed, 1 skipped. UI semantic subset: 35 passed.
- RUN_REGRESSION_FOCUSED: 40 passed, 1 skipped; PASS.
