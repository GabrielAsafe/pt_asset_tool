# Asset Retention Root Reachability V2.4 — integração 2026-09-27

## Objetivo

Separar ContractGraph linkage de runtime-root reachability sem enfraquecer as
garantias fail-closed do PT Asset Tool.

## Mudança semântica

Antes, qualquer edge incoming/outgoing promovia um asset genérico para
`PROTECTED_GRAPH_LINKED`. Isso impedia distinguir um componente realmente
alcançado pelo runtime de um subgrafo morto cujos próprios arquivos apenas se
referenciam entre si.

Agora:

- `strong_paths` continuam sendo a única origem de runtime roots;
- closure dirigida a partir de strong roots produz `root_reachable=true`;
- assets genéricos com edge, mas sem root, usam
  `REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE`;
- manifest/source/catalog continuam evidência positiva, sem serem convertidos
  implicitamente em runtime roots;
- Monster/NPC continua fail-closed por bundle/catalog e não herda a relaxação
  aplicada a assets genéricos;
- `deletion_authorized=false` permanece invariável.

## Novos campos

`pt_build/asset_retention/assets.tsv`:

- `graph_linked`
- `root_reachable`
- `root_distance`
- `root_source_count`
- `root_sources`
- `root_source_evidence`
- `incoming_edge_sources`
- `outgoing_edge_targets`
- `incoming_edge_details`
- `outgoing_edge_details`

## Consulta CLI curta

```bash
python3 pt_asset.py audit asset-retention-query \
  --path 'Effect/AssaEffect/MonsterFury/m_fury.tga'
```

A consulta usa o relatório persistido e não reroda o General Census.

## Validação executada

```text
asset retention + cooked evidence + general census: 32 passed
UI/static/server focused: 7 passed, 5 skipped (environment gates)
node --check app/pt_asset_tool/ui_static/app.js: PASS
python py_compile modified Python modules: PASS
```

## Compatibilidade

- nenhuma permissão de writer foi ampliada;
- nenhum delete/quarantine automático foi introduzido;
- `ORPHAN_CANDIDATE` continua revisão, nunca autorização;
- consumidores antigos que usam `path/state/reason/evidence` no TSV continuam
  recebendo esses campos; a revisão só acrescenta colunas;
- a classificação Monster/NPC continua conservadora.
