# Etervale V5 — Fechamento dos itens 2 e 3 (UI + auditoria de módulos)

Patch incremental **sobre a V4** do PT Asset Tool, já instalada e testada (105/105). Não altera arquivos da source Etervale, C#, GameServer, textures ou database.

## Conteúdo

- Correção do `ui-board`: mostra o relatório de conteúdo provado no fechamento P0, prioriza evidência concreta, e não oculta novas falhas surgidas depois dele.
- Novo `p0-release-selftest`: seis verificações em árvore descartável; escreve evidência `ISOLATED_SELFTEST_ONLY` separada de qualquer publicação real.
- Novo `legacy-migration-audit`: inventário AST + hashes SHA de todos os módulos Python, verificação de roots, CSV/JSON por arquivo e lista de comandos/rotas para testes de UI subsequentes.
- HTML de prontidão apresenta origem/limitações da prova e evita dar a um selftest o aspecto de publicação em produção.
- Guia detalhado e roteiro da etapa seguinte de UI.

**Não confundir:** inventário de todos os módulos com validação funcional completa de todos eles. A V5 identificou 13 módulos ativos com comportamento legado que ainda exigem revisão em operações reais. Não inclui adaptação de Content JSON, modernização gráfica, teste de runtime, publicação do jogo ou correção de `tem_wall04.bmp`.

## Instalar

Coloque `ETERVALE_V5_MIGRACAO_EVIDENCIAS_2026-11-10.zip` em `~/Transferências/`. Execute:

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V5_MIGRACAO_EVIDENCIAS_2026-11-10.zip" -d .
python3 patches/aplicar_etervale_v5.py --project-root "$PWD" --dry-run
```

Se não surgir `LOCAL_FILE_CONFLICT`:

```bash
python3 patches/aplicar_etervale_v5.py --project-root "$PWD"
python3 -m pytest -q \
  app/dev_tests/test_etervale_p0_*.py \
  app/dev_tests/test_etervale_p1_*.py \
  app/dev_tests/test_etervale_native_pipeline.py \
  app/dev_tests/test_etervale_unified_bridge.py \
  app/dev_tests/test_etervale_texture_audit_bridge.py \
  app/dev_tests/test_data_type_migration_etervale.py \
  app/dev_tests/test_etervale_v5_migration_evidence.py
```

Nos artefatos reconstruídos e testados localmente, **114 testes passaram**. No checkout do usuário o número poderá variar. A instalação é idempotente, cria backup dos 3 arquivos modificados e recusa conflitos por hash.

## Gerar provas reais do ambiente instalado

```bash
python3 app/pt_asset.py etervale p0-release-selftest
python3 app/pt_asset.py etervale legacy-migration-audit
python3 app/pt_asset.py etervale ui-board
```

Pré-requisito do auditor de configuração: `ETERVALE_UNIFIED_V1` deve estar configurado. Se necessário:

```bash
python3 app/pt_asset.py config set-etervale-root "$HOME/Transferências/Etervale-git"
```

O selftest não toca o jogo. `legacy-migration-audit` só lê código/configuração e escreve relatórios privados. O `ui-board` só lê relatórios.

## Resultados esperados

- `p0-release-selftest`: `PASS_ISOLATED_RELEASE_ROLLBACK_NOT_PRODUCTION`, `check_count: 6`.
- `legacy-migration-audit`: `AUDIT_COMPLETED_WITH_EXPLICIT_LEGACY_BOUNDARIES`, raiz `PASS_UNIFIED_ASSET_ROOT_ROUTING`, `syntax_errors: []`. Ainda há módulos históricos a rever; isso é esperado.
- `ui-board`: o cartão `content` mostra a prova aprovada **vinculada ao fechamento P0**, exceto se houver tentativa mais recente que falhou. O cartão `release` mostrará prova **isolada**, não produção.

Se o item `content` permanecer incorreto, envie os resumos de `p0-closure-audit` e `ui-board` antes de eliminar/alterar qualquer relatório.

A revisão **total da UI** é a próxima etapa, e a ligação ao **Content JSON** é futura e separada.
