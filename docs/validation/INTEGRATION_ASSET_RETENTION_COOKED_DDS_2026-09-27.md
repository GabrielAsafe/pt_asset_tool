# Integration validation — Asset Retention + Cooked DDS — 2026-09-27

## Escopo

Integração read-only no PT Asset Tool + extensão do Summit DDS cooker para failure metadata persistente/retry seletivo.

## Recursos existentes reutilizados

- `app/data/reference/entity_catalog/monster_npc_entities_v1.json` — o ficheiro fornecido para a integração é byte-a-byte igual ao recurso já empacotado; não foi criada cópia.
- `app/data/ui_catalog/ui_tree_summary_v1.json` — idem; permanece evidência agregada por path/folder e não prova uso runtime individual.
- ContractGraph / dependency graph, General Asset Census, source evidence, client manifest evidence e os censos server continuam sendo as autoridades existentes consumidas pela nova projeção.

## Invariantes introduzidas

- ausência em grep/source nunca autoriza remoção;
- qualquer ContractGraph edge protege;
- strong root protege closure transitiva;
- `char/monster/<entity>` e `char/npc/<entity>` presentes no catálogo físico ficam protegidos como bundle mesmo quando o parser ainda não expôs todos os edges internos;
- um bundle ligado por qualquer membro também protege siblings;
- manifest/source/review evidence protege;
- `ORPHAN_CANDIDATE` mantém `deletion_authorized=false`;
- falha no DDS cooker nunca torna o source removível.

## Cooker V2

`SUMMIT_TEXTURE_COOK_MANIFEST_V2` persiste failures em `entries`/`failures` e gera `cooked/failed.json`. Failure rows registram stage, classe normalizada, exception, source size/mtime/SHA-256 e 32 bytes iniciais do header.

O parser `--retry-log` foi exercitado contra o log fornecido nesta conversa e extraiu exatamente **145** sources: **134 TGA + 11 BMP**. Classificação do log: **107 UNRECOGNIZED_LEGACY_IMAGE_ENCODING**, **26 IMPLAUSIBLE_IMAGE_DIMENSIONS**, **10 TRUNCATED_INPUT**, **1 HEADER_TOO_SHORT**, **1 UNSUPPORTED_BMP_HEADER**. O retry real dos bytes do client precisa ocorrer na instalação do utilizador, pois o client físico não foi anexado nesta execução.

## Gates executadas

```text
DOC_AUDIT files=40 errors=0
pytest targeted integration: 46 passed, 5 skipped
node --check app/pt_asset_tool/ui_static/app.js: PASS
python py_compile integration modules: PASS
```

`RUN_REGRESSION_FOCUSED.sh`: **40 passed, 1 skipped**, `REGRESSION_FOCUSED=PASS`.

`VERIFY_PACKAGE.sh`: **PASS** após regeneração controlada do snapshot; vendor `v9-fix136`, runtime state excluído/untracked. O gate completo que depende do client/server/Blender real não foi rerodado nesta execução.
