# Summit Content Workbench V2

A V2 trabalha em cima do `catalog.sqlite3` gerado pela V1 e transforma o inventário bruto em um catálogo de conteúdo comparável e editável com segurança.

## Objetivos

- normalizar Monsters, NPCs, Items, Quests e Maps;
- decodificar SCFG usando o próprio mapa semântico preservado no canonical;
- comparar SourceCode, cliente, Servidor e futuros donors;
- manter provenance por versão;
- criar relações entidade -> modelo/textura/drop/spawn/map;
- detectar famílias de assets presentes fisicamente mas sem entidade ativa;
- cruzar a runtime asset probe com o inventário;
- preparar balanceamento via overrides, sem editar donor diretamente.

## Instalação

Na raiz do repo:

```bash
bash INSTALL_V2.sh .
```

Instala:

```text
SourceCode/tools/content_workbench/summit_content_workbench_v2.py
SourceCode/tools/content_workbench/README_V2.md
```

## Build usando o catálogo V1 existente

```bash
python3 SourceCode/tools/content_workbench/summit_content_workbench_v2.py \
  build \
  --catalog .summit_content_catalog/catalog.sqlite3 \
  --out .summit_content_workbench_v2
```

Principais saídas:

```text
.summit_content_workbench_v2/
├── workbench_v2.sqlite3
├── overview_v2.json
├── directive_token_map.json
├── entity_master.csv
├── entity_versions.csv
├── balance_matrix.csv
├── field_conflicts.csv
├── unmatched_versions.csv
├── content_graph.csv
├── runtime_asset_health.csv
├── runtime_failures_v2.csv
├── asset_references.csv
├── file_coverage.csv
├── asset_families.csv
├── orphan_asset_families.csv
└── index_v2.html
```

## Pesquisa

```bash
python3 SourceCode/tools/content_workbench/summit_content_workbench_v2.py \
  search --db .summit_content_workbench_v2 eragon
```

```bash
python3 SourceCode/tools/content_workbench/summit_content_workbench_v2.py \
  search --db .summit_content_workbench_v2 "Arqueira das Cinzas" --type monster
```

## Ver uma entidade

```bash
python3 SourceCode/tools/content_workbench/summit_content_workbench_v2.py \
  show --db .summit_content_workbench_v2 monster.100_arqueira_das_cinzas
```

## Comparar todas as versões

```bash
python3 SourceCode/tools/content_workbench/summit_content_workbench_v2.py \
  diff --db .summit_content_workbench_v2 monster.100_arqueira_das_cinzas
```

Use `--all` para mostrar também campos iguais.

## Famílias de assets

Todo diretório `char/monster/<família>` e `char/npc/<família>` vira uma família.

Listar conteúdo fisicamente presente mas sem entidade ativa:

```bash
python3 SourceCode/tools/content_workbench/summit_content_workbench_v2.py \
  families \
  --db .summit_content_workbench_v2 \
  --status ORPHAN_NO_ENTITY \
  --limit 500
```

Procurar Eragon:

```bash
python3 SourceCode/tools/content_workbench/summit_content_workbench_v2.py \
  families \
  --db .summit_content_workbench_v2 \
  eragon \
  --type monster
```

## Interface local

```bash
python3 SourceCode/tools/content_workbench/summit_content_workbench_v2.py \
  serve \
  --db .summit_content_workbench_v2 \
  --host 127.0.0.1 \
  --port 8765
```

Abra:

```text
http://127.0.0.1:8765/
```

A interface oferece:

- lista de entidades;
- versões SourceCode/cliente/Servidor/donor;
- relações de assets;
- famílias órfãs;
- failures da probe;
- conflitos de campos;
- balance overrides.

## Balance overrides

Overrides são gravados separadamente. Eles NÃO alteram donor nem canonical automaticamente.

Exemplo:

```bash
python3 SourceCode/tools/content_workbench/summit_content_workbench_v2.py \
  override \
  --file .summit_content_workbench_v2/balance_overrides.json \
  set \
  --type monster \
  --id monster.100_arqueira_das_cinzas \
  --field life \
  --value 20000 \
  --reason "teste de balanceamento"
```

Ver:

```bash
python3 SourceCode/tools/content_workbench/summit_content_workbench_v2.py \
  override \
  --file .summit_content_workbench_v2/balance_overrides.json \
  list
```

## Donors

A V2 consome qualquer donor já indexado pela V1. Portanto, para acrescentar donors, gere novamente o catálogo V1 com `--donor NAME=PATH` e depois rode `build` da V2.

A regra é:

```text
DONOR = evidence somente leitura
CANONICAL = estado escolhido do Summit
OVERRIDE = mudança deliberada de balance/design
```

Nenhum donor deve ser editado in-place.

## Próxima fase

A V3 natural é o compiler/editor:

1. importar uma versão donor selecionada para canonical;
2. aplicar `balance_overrides.json`;
3. validar schemas;
4. preview de diff;
5. rebuild dos packs;
6. deploy cliente/servidor;
7. rollback automático;
8. auditoria runtime pós-build.
