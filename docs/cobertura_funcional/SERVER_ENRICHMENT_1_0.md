# PT Asset Tool R14 1.0.0 — Manual Server / Asset Enrichment

## Princípio

O PT Asset Tool usa o server para descobrir bundles e relações; não transforma a raiz do server em workspace gravável.

## Gates

```bash
python3 pt_asset.py --client-root CLIENT --server-root SERVER validate server-environment-auto
python3 pt_asset.py --client-root CLIENT --server-root SERVER validate server-design-auto
```

O segundo consolida environment + Monster/NPC + Field + OpenItem censuses.

## Censos

- `audit server-inventory`: árvore e lifecycle;
- `audit server-bundles`: Monster/NPC definitions e logical model/INX resolution;
- `audit server-fields`: SPM/SPP/SPC companions e stage basename candidates;
- `audit server-items`: OpenItem, CODE identity, ZHOON e duplicate-code conflicts.

## Asset Enrichment v9 Fix136

- `audit enrichment-plan`: plan via vendor, manifest em pt_build;
- `audit enrichment-graph`: dependency graph client/server;
- GUI: aba Servidor/Enrichment, explorador de bundles e summaries.

## Source contracts

- `audit source-contracts`: evidência C/C++ para sound maps, class gates e relações de formato;
- `audit player-class-contracts`: grafo de cobertura das classes, UI/audio/effect/animation/runtime migration e dependências `.part`.

## General Asset Census / T5

- `audit general-asset-census`: reachability client/server, donor gaps separados de runtime need;
- `audit t5-assets`: readiness T5 com current asset calls e CLOSED same-lineage bundles;
- `audit t5-effects`: alias de compatibilidade do audit T5.

PRELOAD de partícula não é ACTIVATION. O relatório T5 canónico é `t5_asset_readiness.json`; o filename histórico de effect é apenas compatibilidade.

## Field Metadata Editor

A GUI cria drafts SPM/SPP/SPC sob `pt_build`; veja `FIELD_METADATA_EDITOR.md` e `FORMATS_WRITERS_1_0.md`.

## Lifecycle excluído de autoria

Persistência, logs, anti-cheat/segurança e estado runtime não são assets por terem extensões ou strings parecidas. A classificação de lifecycle tem precedência sobre heurísticas de nome/extensão.
