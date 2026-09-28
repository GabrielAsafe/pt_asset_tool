# Integration Validation — Legacy Authoring Semantic Catalog V2.9

**Data:** 2026-09-28

## Escopo

Integra o mapeamento fornecido `Priston Tale — mapeamento nome visível -> asset interno` à criação/edição ITEM/MONSTER/NPC/MAP, preservando `canonical_id` como identidade de authoring e códigos runtime como campos de formato.

## Contratos testados

- contagens do bundle: 2607 1x1; 1893 items; 383 mobs; 175 NPCs; 53 maps; 54 spawn stages; 230 ambiguidades;
- Ricarten → `map.village_2` → `GameServer/Field/Village-2.ase.{spm,spp,spc}`;
- códigos sITEM duplicados mantêm canonical IDs/paths distintos;
- nomes visíveis ambíguos são sinalizados;
- semantic target binding valida kind/path/code;
- related bindings validam ITEM_REFERENCE/ACTOR/FIXED_NPC e recusam provenance sem vínculo no spec;
- manifest staged preserva target e related semantic bindings;
- UI possui seletores semânticos para target/item/mob/NPC.

## Safety

Nenhum asset é publicado durante seleção ou stage. O bundle continua sob os gates de publish/restore existentes. Esta revisão não altera asset-retention/quarantine nem autoriza delete.
