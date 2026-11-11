# Migração V5 — Item 2 (provas na UI) e Item 3 (inventário legado)

**Estado:** implementados na ferramenta e testados localmente em checkout reconstruído dos patches até V4. Execução final no checkout do usuário ainda necessária.

## Item 2 — Corrigir evidências desatualizadas

O `ui-board` V2 mantém oito cartões e não escolhe cegamente o JSON de `content_compat` com `mtime` maior. Se existir um `p0_closure` aprovado, ele abre a prova exata em `native_four_domain_import_proof` e revalida formato, status, quatro domínios alterados e ausência de escrita nos assets. **Uma falha posterior à certificação não é escondida:** a UI marca `REVIEW_NEWER_FAILURE` e conserva referência à prova antiga. Se não houver fechamento, exibe a tentativa mais recente sem inferir sucesso.

O cartão `release` diferencia publicação real de teste isolado. O novo `p0-release-selftest` exercita autorização SHA, aplicação, rollback, recusa de segundo rollback e de alterações externas, num diretório temporário do Asset Tool, criado e apagado automaticamente. **Não usa dados do jogo e não executa WorldImport ou validação nativa da receita.** `PASS_ISOLATED_RELEASE_ROLLBACK_NOT_PRODUCTION` atesta exclusivamente a mecânica de release/rollback. Este status não é publicação em produção.

O HTML `/etervale-readiness` exibe a proveniência, a escolha e as advertências, em texto seguro. Não cria ações de publicação.

## Item 3 — Auditoria exaustiva dos arquivos Python instalados

`legacy-migration-audit` faz inventário de todos os módulos `.py` empacotados em `app/pt_asset_tool`, guarda hashes SHA-256, classificação, presença de literais históricos, funções com potenciais operações de escrita e validação sintática por AST. Também verifica se os roots efetivamente configurados resolvem para `<Etervale-git>/assets` e `<Etervale-git>/assets/GameServer`, sem alterar a configuração, e registra nomes de comandos e rotas UI para a futura fase de testes ponta a ponta.

### Evidência local da base V4 reconstruída + V5

- **378 módulos Python** examinados; **0** falhas de sintaxe.
- **18** módulos da ponte explícita Etervale, **5** de roteamento/configuração.
- **107** módulos históricos contidos em `legacy_data_tools`, `legacy_apps` ou `legacy_runtime` — **não são readers nativos**.
- **13** módulos ativos de migração/autoria/deploy legados precisam revisão funcional antes de considerá-los portados.
- **235** módulos compartilhados/genéricos que **não recebem** certificação runtime só por compilar.
- **233 caminhos de comandos CLI** registrados e **107 referências distintas a rotas `/api/`** inventariadas; não foram executados individualmente.

Os 13 módulos sinalizados incluem `canonical_authoring`, `legacy_authoring`, `asset_compiler`, `asset_bundle_deploy`, `workspace_bundle_deploy`, `asset_quarantine`, `asset_retention`, `donor_recovery_explorer`, `general_asset_recovery`, `legacy_management_audit`, `legacy_management_contracts`, `summit_asset_migration_audit` e `summit_canonical`.

### Política de compatibilidade

1. Formatos Summit (`.scfg`, `.smap`, `.sres` etc.) continuam em ferramentas históricas e **não são considerados packs nativos Etervale**.
2. Módulos com operações de escrita/deploy históricos **não são aprovados** para publicar no checkout Etervale apenas por constarem no inventário.
3. Os novos fluxos nativos continuam exigindo provas C# / WorldImport, manifestos e aprovação explícita para publicação.
4. A auditoria da V5 **não é validação completa de UI ou execução individual de 233 comandos**. Essas provas serão a próxima etapa.

## Executar após instalar

```bash
cd "$HOME/Transferências/pt_asset_tool"
python3 app/pt_asset.py etervale p0-release-selftest
python3 app/pt_asset.py etervale legacy-migration-audit
python3 app/pt_asset.py etervale ui-board
```

Relatórios ficam em:

- `app/pt_build/etervale/p0_release_selftest/`
- `app/pt_build/etervale/migration_audit/` — relatório, inventário `.modules.json` e `.modules.csv`, superfície `.surfaces.json`.

Se o Etervale não estiver configurado, execute `python3 app/pt_asset.py config set-etervale-root "$HOME/Transferências/Etervale-git"` antes de rodar o audit. Uma raiz incompatível ou errada faz a ferramenta exigir revisão, **não** marcar PASS.

## Próximas fases — mantidas separadas

**Validação de toda a UI:** usar `surfaces.json` para inventário de navegação, GET/POST, formulários, ações bloqueadas e teste de publicação/restore exclusivamente com fixtures descartáveis; classificar cada tela quanto a sua compatibilidade nativa. Nenhuma tela recebe status aprovado por padrão.

**Integração posterior com Content JSON:** analisar os schemas reais, estabelecer uma autoridade única de IDs, aliases e referências, começar com adaptação somente leitura e uma comparação de catálogo, depois permitir criação de candidatos sob WorldImport. Não implementar a publicação do JSON sem contrato e provas específicas.
