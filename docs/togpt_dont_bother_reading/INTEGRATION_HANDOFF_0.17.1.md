# Guia de integração — Asset Contracts e Superset Aggregator

Release: 0.17.1

## Objetivo

Este documento descreve como incorporar a evolução 0.14.x–0.17.x noutra árvore da aplicação sem duplicar lógica ou perder as garantias de segurança.

## 1. Módulos que formam o núcleo novo

### Source / evidence

```text
pt_asset_tool/source_catalog.py
pt_asset_tool/source_evidence.py
pt_asset_tool/source_contract_census.py
```

### Contracts

```text
pt_asset_tool/contract_graph.py
pt_asset_tool/skill_contract_census.py
pt_asset_tool/player_class_motion_contract.py
```

### Aggregation

```text
pt_asset_tool/aggregation.py
pt_asset_tool/superset_aggregation.py
```

### Entry points

```text
pt_asset_tool/cli.py
pt_asset_tool/ui_app.py
pt_asset_tool/ui_static/index.html
pt_asset_tool/ui_static/app.js
```

Não mover regras de negócio para `app.js`. UI deve apenas configurar/disparar e renderizar resultados.

## 2. Fluxo de chamada recomendado

```text
CLI / HTTP / GUI
      |
      v
source roots + donor config
      |
      v
source evidence / contracts
      |
      v
resolver
      |
      v
aggregation plan
      |
      v
staging materializer
      |
      v
validation + reports bundle
```

## 3. Configuração local

`app/pt_asset_app_config.json` é estado do utilizador e não deve ser distribuído dentro da FULL release.

Config fields usados pela feature:

- source root Summit;
- reference source root EU;
- donor clients;
- donor servers;
- client/server roots existentes da aplicação.

A integração deve preservar config entre updates.

## 4. CLI que não deve quebrar

```bash
python3 pt_asset.py audit source-contracts
python3 pt_asset.py audit player-class-contracts
python3 pt_asset.py aggregate player-classes
python3 pt_asset.py aggregate client-superset
python3 pt_asset.py aggregate server-superset
python3 pt_asset.py aggregate summit-superset
```

## 5. HTTP/GUI

A versão integrada expõe contract configuration/analyze via `/api/contracts` e `/api/contracts/analyze`.

Ação `aggregate_summit` deve chamar o mesmo `build_summit_superset()` usado pelo CLI. Não criar um segundo implementation path.

## 6. Outputs estáveis

### Player classes

```text
pt_build/aggregate/player_classes/all/
```

### Client

```text
pt_build/aggregate/client_superset/all/
```

### Server

```text
pt_build/aggregate/server_superset/all/
```

### Combined

```text
pt_build/aggregate/summit/all/
  manifest.json
  validation.json
  reports_bundle.zip
```

`reports_bundle.zip` é o artefacto preferido para suporte/review. Não incluir overlays enormes quando apenas relatórios são necessários.

## 7. Compatibilidade de dados

Não mudar nomes de ações/estados sem migration explícita, porque UI e relatórios dependem deles.

Em particular preservar:

- `KEEP_TARGET`;
- `RECOVER`;
- `RECOVER_DEDUPED`;
- `RECOVER_PREFERRED_VARIANT`;
- `OPTIONAL_MISSING`;
- `CORE_READY_STAGING_WITH_OPTIONAL_GAPS`;
- `CURRENT_REGISTRY_INCOMPATIBLE_WITH_REFERENCE_INX_INDICES`;
- `RUNTIME_DISABLED_BY_MAX_JOBNUM`.

## 8. Separação client/server/source

Nunca reutilizar o mesmo root semanticamente para lados diferentes. Os source IDs devem manter role explícito.

Server normalizations conhecidas:

```text
PT_EU: game-server/ -> namespace game server
ExMachina: GameServer/OpenItem - Copia/ -> GameServer/OpenItem/
```

`login-server/` continua reference-only até provider específico.

## 9. Hash cache

O cache de SHA-256 deve permanecer fora do package:

```text
~/.cache/pt_asset_tool/asset_hashes.sqlite3
```

Cache deve invalidar por metadata suficiente antes de reutilizar hash.

## 10. Como adicionar um novo provider

Exemplo Item:

1. parser produz entidades e evidências;
2. criar/garantir nós no `ContractGraph`;
3. criar edges com `relation`, `evidence`, `confidence`, `required`;
4. resolver logical paths;
5. deixar o aggregation planner consumir os assets alcançáveis;
6. adicionar validation específica, se necessária;
7. acrescentar UI somente depois do backend funcionar.

Não codificar Item-specific copy policy no `superset_aggregation.py` se a regra puder ser expressa pelo contract provider.

## 11. Como integrar geração futura

Gerador deve ser provider separado do resolver de donor. Uma ausência só vira `GENERATABLE` quando:

- existe generator registrado;
- inputs resolvidos;
- writer certificado;
- pós-validação disponível.

O gerador escreve em staging, nunca target.

## 12. Testes mínimos após integração

1. `./VERIFY_PACKAGE.sh`;
2. parser CLI contém os seis comandos de contracts/aggregate;
3. source contracts em fixtures;
4. player class contracts;
5. SkillCodeList binding fixture;
6. aggregation planner KEEP/RECOVER/VARIANT/OPTIONAL;
7. path traversal reject;
8. SHA pós-copy;
9. server runtime state exclusion;
10. GUI JS syntax;
11. run físico `aggregate summit-superset`;
12. confirmar `target_client_modified=false` e `target_server_modified=false`.

## 13. Ordem de integração recomendada

Se a app destino divergiu da FULL:

1. copiar módulos backend novos;
2. resolver imports/CLI;
3. integrar config;
4. integrar endpoints;
5. integrar HTML/JS;
6. copiar docs;
7. executar testes;
8. executar run físico staging-only;
9. comparar `reports_bundle.zip` com baseline anterior.

## 14. Baseline físico conhecido

O player-class aggregate 0.16.0 produziu:

```text
2080 planned
1669 keep target
255 recover
44 recover preferred variant
112 optional missing
0 core unresolved
299 materialized recoveries
88 archived variants
runtime_ready=false
```

Não hard-code estes números; use apenas como regressão histórica para o mesmo corpus.
