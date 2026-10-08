> **V2.11 authority notice (2026-10-01):** This V2.9 catalog is retained as historical/display-alias evidence. In canonical mode, entity existence and authoring authority come from `Summit Content/canonical/**`; see `SUMMIT_CANONICAL_SOURCE_V211.md` for the historical authority transition and `../en/topics/SUMMIT_CANONICAL_EXTENDED_DOMAINS_V212.md` for the current map/dynamic-field contract.

# Catálogo semântico de authoring — V2.9

**Data:** 2026-09-28  
**Status:** integrado ao Management Legacy / Legacy Authoring.

## Contrato

Fonte empacotada: `app/pt_asset_tool/contracts/priston_asset_name_map_v1.json`. O contrato preserva `display_name`, `internal_name`, `canonical_id`, paths/arquivos associados, confidence, método e ambiguidades.

Contagens declaradas pela fonte: 1.893 itens, 383 mobs, 175 NPCs, 53 mapas, 54 stages/spawns, 779 textos e 230 nomes visíveis ambíguos; o subconjunto 1x1 contém 2.607 nomes únicos.

## Política de identidade

```text
canonical_id  = identidade primária de authoring
runtime code  = campo runtime quando exigido pelo formato
display_name  = rótulo humano, nunca chave única implícita
```

Um mesmo código sITEM pode representar mais de uma definição física/canônica. A UI, portanto, seleciona ITEM por `canonical_id` e só depois preenche o `code`. Nomes ambíguos são marcados e não são colapsados.

## Integração por domínio

- **ITEM**: nome visível → canonical_id → OpenItem/path + code + linked asset.
- **MONSTER**: nome visível → Monster INF + ModelFile/level; drops podem receber itens via catálogo.
- **NPC**: nome visível → NPC definition + ModelFile; shop pode receber itens via catálogo.
- **MAP/SPM/SPP/SPC**: nome do mapa → field/stage/spawn → paths físicos de `GameServer/Field`. Ricarten resolve para `village-2`.
- **SPM**: seletor relacionado de mob insere actor usando nome runtime/visível e registra provenance canônica.
- **SPC**: seletor relacionado de NPC preenche `name`, `model_ini` e `server_npc` e registra provenance canônica.

## Safety

O catálogo não autoriza writes por si só. O fluxo continua `Inspect → Spec → Stage → Manifest → Publish → Verify → Restore`. `semantic_ref` e `semantic_related_refs` são validados no backend; path/kind/code incompatíveis ou referências relacionadas que não aparecem no spec bloqueiam o stage.
