# PT Asset Tool R14 1.0.0 — Certification

<!-- PT_HISTORICAL_RELEASE_CONTEXT_2026-09-25 -->

> **Contexto histórico:** este documento preserva evidência/claims da Release 1.0 na data indicada. Para validar o checkout atual, use `docs/engenharia/VALIDACAO_TESTES_DESENVOLVIMENTO.md` e não trate contagens/flags históricas como resultado de uma execução nova.

Certification date: 2026-09-14

## Final gate

- `automatic_gate_status`: **PASS**
- automatic blockers: **0**
- release gate status before packaging: **BLOCKED_EXTERNAL**
- external operational gate(s): **WRITER_PROMOTION_AND_PUBLISH_RESTORE**
- runtime game acceptance pending: **False**
- client modified by certification: **False**

`BLOCKED_EXTERNAL`, when present, means the production write/publish path remains safety-locked. It does not mean an automatic parser/writer capability failed.

## Key physical evidence

- Model0.62 material corpus: `PASS`, assets `3144`, failures `0`.
- Material writer pass domains: `EFFECT, MAP, MONSTER, NPC, PLAYER, WEAPON_ITEM`.
- Model0.62 texture audit: strict `FAIL`, audit `PASS`.
- Proprietary texture codec capability: `PASS`.
- Proprietary target-content status: `FAIL`.

## Release claim

Version 1.0.0 claims certification of the PT Asset Tool scope only. It does not claim that every Summit target asset is present/valid, and it does not silently authorize production writes.
