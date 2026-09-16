# Estado corrente — 05/09/2026

## Identidade do snapshot

- Aplicação/overlay: **0.13.0**.
- Core legado mantido: `pt_asset_core_v0_8_9.py` / `pt_asset_tool.__version__ = 0.8.9`.
- Instalação operacional esperada: `/home/gabriel/Transferências/current/app`.
- `client_write_authorized=false`.
- `server_write_authorized=false`.
- `production_authorized=false`.

## Asset Enrichment

O vendor ativo é `vendor/summit_asset_enrichment_v9/`, manifesto `v9-fix136`.
O vendor legado v6 foi removido da distribuição ativa; o adapter/UI aceitam apenas `vendor/summit_asset_enrichment_v9/`. Evidência histórica sobre v6 permanece somente nos diretórios de histórico/documentação histórica.

A aba **Servidor / Asset Enrichment** continua a expor análise, migration plan e dependency graph sem executar `apply`/`install-apply` do vendor.

## Field metadata: SPM / SPP / SPC

A aplicação 0.13 integra uma superfície de autoria **somente em staging**:

- **SPM** — texto de spawn/atores. O draft preserva encoding e estilo de newline detectados.
- **SPP** — layout Summit canónico de 200 registros × 12 bytes (`state`, `x`, `z`). A UI faz edição estruturada de registros.
- **SPC** — 100 × 504 bytes. A UI permite somente **clone-patch** de um record `ADD_NPC` conhecido para um slot não ativo. Autoria binária sintética do zero permanece bloqueada.

Todos os drafts ficam em `app/pt_build/server_field_editor/`. Não existe endpoint de publish para `GameServer/Field`.

Um merchant não é definido integralmente pelo SPC: o SPC contém placement/ligação do NPC fixo; shop/quest/comportamento permanecem na definição server-side correspondente.

## Effects / Particles

A stack `.part` atual inclui parser/semantic profile, draft transacional, diff/verify e preview Blender.
O preview visual é explicitamente **`BLENDER_PREVIEW_APPROXIMATE`**: `.part`/draft → plano semântico → `.blend` + PNG em `pt_build`.
Ele não é certificação de fidelidade runtime Summit.

## Evidência física recente

### Motion semantic

A correção de orçamento partilhado por contexto está fisicamente instalada. Os sete contexts PLAYER patológicos deixaram o padrão ~120 s INX + ~120 s SMB (~240 s total) e passaram a encerrar por volta de 120 s por contexto.
Isso fecha o problema operacional de timeout duplicado, mas não transforma os contexts semanticamente inválidos em PASS.

### Static writer

A cadeia de diagnóstico avançou:

1. erro original `float(tuple)`;
2. RC6.1.2 expôs coleções `list[N]` de `tuple[3]`;
3. RC6.5 adicionou uma redução por consenso apenas quando todos os vetores são equivalentes;
4. a prova física RC6.5.5 recuperou **13/13 failures `PT_RC6_5_MULTI_VEC3_DIVERGENT`**, zero `float(tuple)` e zero `PT_RC6_1_VEC3_NORMALIZE_FAIL`.

Conclusão: `eqn[vi]` representa múltiplos normais de corner/loop e não deve ser flatten/averaged globalmente. O próximo fix do writer precisa selecionar o normal topológico correto por face/corner/loop, preservando hard edges/smoothing.

## Release 1.0

Este snapshot **não é Release 1.0**. Continuam obrigatórios, entre outros:

- Model0.62 physical corpus sem required failures;
- rigid context census resolvido/fail-closed;
- rigid/static Blender representatives certificados;
- animation pose-space sem required failures;
- texture presence/corpus blockers fechados ou corretamente classificados;
- Mixed-Physique físico autêntico;
- runtime/game acceptance;
- promoção de writers depois da prova runtime;
- publish/restore/rollback físico;
- só depois habilitação controlada de escrita.
