# Housekeeping — 05/09/2026

## Estrutura operacional

A instalação ativa do utilizador é tratada como:

```text
/home/gabriel/Transferências/current/app
```

Pacotes RC testados são arquivados externamente em `asset_tool_armazem/`; pastas RC extraídas são temporárias.

## Limpeza interna desta revisão

A raiz `app/` foi reduzida à superfície operacional corrente.

Movidos para `app/history/`:

- `rc_tools/` — runners/verifiers RC6 antigos;
- `writer_backups/` — backups `pre_rc*` dos writers;
- `hotfixes/` — diffs/notas hotfix históricas.

Mantidos na raiz:

- runner/verifier RC6.5.5 corrente, porque contém a evidência static mais recente;
- `RUN_RELEASE_FAST.sh` e `RUN_RC6_POSTRUN.sh`;
- tools Effects/Particles atuais;
- analyzers/triage v3 atuais.

`pt_build` foi preservado integralmente por conter cache, checkpoints e evidência física.

Caches Python (`__pycache__`/`.pyc`) fora de `pt_build` foram removidos do snapshot distribuível.

## Vendor

- ativo: `vendor/summit_asset_enrichment_v9/` (`v9-fix136`);
- histórico: `vendor/summit_asset_enrichment_v6/`.

O adapter escolhe v9 primeiro e mantém fallback v6 para compatibilidade de snapshots/testes.

## Limpeza da raiz do snapshot

Material histórico que antes ficava no top-level foi consolidado em `history/`:

- `history/package_docs/`;
- `history/gptfiles/`;
- `history/legacy_reference/`.

A raiz final fica restrita a status/readiness/verifier + `app`, `docs`, `evidence`, `history` e `vendor`.
