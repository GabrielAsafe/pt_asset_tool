# Roadmap pós-0.17.1 — Summit Asset Contract Platform

## P0 — Runtime Assassin/Shaman

- job migration planner;
- registry/SkillCodeList migration planner;
- handler closure client/server;
- packet/persistence audit;
- runtime acceptance matrix.

Saída desejada:

```text
pt_asset plan migrate-player-class Assassin
pt_asset plan migrate-player-class Shaman
```

Primeiro read-only; writes somente depois de validação.

## P1 — Item Contract Provider

Objetivo: transformar item code em closure client/server verificável.

```text
OpenItem -> catalog -> DorpItem -> model -> textures -> icon
         -> drops -> shops -> quests -> restrictions
```

Entregáveis:

- item graph;
- item completeness report;
- item aggregation by code/family;
- orphan confidence classification.

## P1 — Field Contract Provider

Objetivo:

```text
Field -> client map/model/textures/UI -> server SPP/SPM/SPC -> spawns/NPC
```

Determinar required/optional por conteúdo/runtime.

## P1 — Skill closure das 10 classes

Generalizar o nível profundo hoje concentrado em Assassin/Shaman:

- 10-class skill catalog;
- direct/delegated handler tracing;
- class audio + skill audio;
- `.part` closure;
- motion/registry binding;
- UI icons/timers.

As oito classes funcionais servem como gold/control corpus.

## P2 — Generation Registry

Registrar capacidades de geração por asset type:

```text
logical output
inputs
writer
writer version
confidence
post-write validators
runtime acceptance requirement
```

Meta: asset ausente possa ser classificado em `GENERATABLE`, não apenas `MISSING_UNKNOWN`.

## P2 — Publish transaction

Adicionar camada separada de staging:

- preflight;
- target backup manifest;
- atomic copy/replace;
- post-hash;
- post-contract audit;
- rollback.

Nenhuma promoção antes de runtime acceptance básico.

## P2 — Master SQLite Catalog

Unificar inventário, provenance, evidence, entities, edges, builds e conflicts.

## P3 — UI operacional

- entity explorer;
- completeness matrix;
- graph drill-down;
- variant diff;
- generation candidates;
- staging/apply/rollback lifecycle;
- historical validation runs.

## Métricas de sucesso

- `core_unresolved_count` por entity type;
- número de `MISSING_UNKNOWN`;
- número de `GENERATABLE` certificados;
- conflitos sem decisão;
- runtime acceptance PASS;
- percentagem de assets com provenance completa;
- número de regras baseadas em source/runtime vs heurística.
