# P0 — Patch único de fechamento para PT Asset Tool ↔ Etervale

**Data:** 9 de novembro de 2026. **Versão:** V3. **Compatibilidade:** patch P0/P1 de 09/11 + patch Native Content V2 instalados, ambos já confirmados no ambiente do usuário.

## Instalação

Coloque `ETERVALE_P0_FECHAMENTO_V3_2026-11-09.zip` em `~/Transferências/` e execute:

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_P0_FECHAMENTO_V3_2026-11-09.zip" -d .
python3 patches/aplicar_p0_fechamento_etervale.py --project-root "$PWD" --dry-run
```

Se **não** houver `LOCAL_FILE_CONFLICT`, execute:

```bash
python3 patches/aplicar_p0_fechamento_etervale.py --project-root "$PWD"
python3 -m pytest -q \
  app/dev_tests/test_etervale_p0_*.py \
  app/dev_tests/test_etervale_p1_*.py \
  app/dev_tests/test_etervale_native_pipeline.py \
  app/dev_tests/test_etervale_unified_bridge.py \
  app/dev_tests/test_etervale_texture_audit_bridge.py \
  app/dev_tests/test_data_type_migration_etervale.py
```

O instalador verifica SHA-256 de arquivos modificados, realiza backup sob `patches/_backups/`, bloqueia conflitos e suporta reaplicação. **Não** modifique arquivos do Etervale durante a instalação.

## Próximas provas exigidas no checkout real

```bash
python3 app/pt_asset.py etervale p0-binary-probe --asset 'Field/Ricarten/village-2.smd' --execute --build
python3 app/pt_asset.py etervale p0-binary-probe --asset 'char/monster/Acero/Acero.smd' --execute
python3 app/pt_asset.py etervale p0-binary-probe --asset 'char/monster/Acero/Acero.smb' --execute
python3 app/pt_asset.py etervale p0-binary-probe --asset 'char/monster/Acero/Acero.inx' --execute
python3 app/pt_asset.py etervale p0-content-probe --auto --execute --build
python3 app/pt_asset.py etervale p0-closure-audit
python3 app/pt_asset.py etervale ui-board
```

**Importante:** o comando `p0-content-probe --auto` não publica nada. Faz quatro alterações temporárias nos arquivos de trabalho e duas importações em SQLite isolado. Se não encontrar uma amostra segura de algum domínio, interrompe; há um modo manual descrito em `docs/etervale/P0_FECHAMENTO_UNIFICADO_V3.md`.

## Entrega

- Writer cirúrgico SMD Stage 0.72 / Model 0.62 sobre arquivos reais, preservando estrutura, geometria, UVs, Physique, colisão e bytes opacos.
- Probes SMB/INX sobre keyframes/movimentos existentes, sem alterar regiões desconhecidas.
- Comando `p0-binary-edit` para modificações intencionais de propriedades existentes, sempre em staging.
- Resolução de aliases como `*DELAY` → `*출현간격`, mantendo grafia real de cada arquivo.
- `p0-content-probe` para Item, Monster, NPC e Field com comparação semântica pelo `WorldImport` real.
- `p0-release-plan`, `p0-release-apply`, `p0-release-rollback`: plano de publicação manual, prova obrigatória, SHA de autorização, backups e rollback protegido contra alterações externas.
- `p0-closure-audit` e dois cartões P0 adicionais na UI.

**75 testes Python passaram no ambiente de montagem**, incluindo os 61 anteriores. As operações cirúrgicas também foram exercitadas contra os packs de Acero, Arcuda e Ricarten enviados pelo usuário. A nova verificação **C# do candidato editado** depende da execução dos comandos acima no checkout do usuário.

## O que o patch não certifica

Não demonstra reprodução visual no cliente, escrita arbitrária de geometria/rig, formatos Summit como arquivos nativos do Etervale nem o ciclo de novas identidades de monstro/NPC sem atualização do registro JSON embutido no `WorldImport`. **Probes automáticos não são publicáveis.** O fechamento formal dos P0 do *escopo de autoria suportado* fica condicionado ao resultado real `p0-closure-audit`.
