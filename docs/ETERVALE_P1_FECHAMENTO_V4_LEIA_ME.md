# PT Asset Tool → Etervale: fechamento P1 V4

Atualização incremental e reversível sobre a instalação **P0 V3 + hotfix V3.1** já validada. Não modifica `Etervale-git`, C# readers nem assets de produção.

## Pacote

- 5 arquivos novos: `etervale_p1_full.py`, `etervale_p1_closure.py`, bateria de testes e dois guias de P1.
- 3 arquivos modificados: registro de subcomandos, evidências da UI e teste de domínios da UI.
- Instalador com SHA-256, dry-run, backup e reaplicação segura; alteração local divergente = `LOCAL_FILE_CONFLICT`.

## 1. Instalar

Copie `ETERVALE_P1_FECHAMENTO_V4_2026-11-09.zip` para `~/Transferências/`:

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_P1_FECHAMENTO_V4_2026-11-09.zip" -d .
python3 patches/aplicar_p1_fechamento_etervale_v4.py --project-root "$PWD" --dry-run
```

Se não houver conflitos:

```bash
python3 patches/aplicar_p1_fechamento_etervale_v4.py --project-root "$PWD"
python3 -m pytest -q \
  app/dev_tests/test_etervale_p0_*.py \
  app/dev_tests/test_etervale_p1_*.py \
  app/dev_tests/test_etervale_native_pipeline.py \
  app/dev_tests/test_etervale_unified_bridge.py \
  app/dev_tests/test_etervale_texture_audit_bridge.py \
  app/dev_tests/test_data_type_migration_etervale.py
```

Em teste local com esta base de arquivos, **105 testes** passaram. O número no seu checkout poderá variar caso tenha novos testes instalados.

## 2. Executar os gates P1 reais

```bash
python3 app/pt_asset.py etervale p1-full-audit --execute --build --world-import
python3 app/pt_asset.py etervale p1-closure-audit
python3 app/pt_asset.py etervale ui-board
```

Os padrões incluem Ricarten Stage, Acero/Arcuda Model/SMB/INX/TGA os três arquivos `Field/Dcave.ase` e uma amostra `.part` descoberta automaticamente (ou `--effect` explícito). `--world-import` cria **SQLite descartável em `app/pt_build/`**, não escreve no banco de produção. O importador C# recebe a pasta `assets` real **para leitura**, ao contrário dos probes anteriores com diretório de assets vazio.

O output terminal é resumido; toda a evidência JSON fica em `app/pt_build/etervale/p1_full/` e `p1_closure/`.

## 3. Critérios, bloqueios e limites

- `P1_AUTOMATED_GATES_PASSED_RUNTIME_PENDING` indica conclusão **das verificações automatizadas** na amostra, não aprovação da experiência visual em jogo.
- `P1_REVIEW_DEPENDENCIES` indica referências não resolvidas. A ausência conhecida `tem_wall04.bmp` poderá permanecer; não será ocultada. Para reconhecer uma falta sem tratá-la como corrigida, use `--known-missing tem_wall04.bmp`. O fechamento P1/03 continua **REVIEW_REQUIRED** enquanto faltar um arquivo.
- O formato do material antigo pode ter estágios extras que não estão no renderer. Não inclui atualização de PBR/Blender nem mudança de parser C#.
- É obrigatório testar visualmente colisão, blend, textura alpha, animações, efeitos e performance antes de declarar runtime/qualidade final aprovados. Veja `docs/etervale/P1_RUNTIME_CHECKLIST_V4.md`.

## 4. Regressão e restauração

O instalador cria `patches/_backups/etervale-p1-v4-<timestamp>/` com os três originais modificados e `install_manifest.json`. A reaplicação do mesmo pacote não altera nada. Se surgir `LOCAL_FILE_CONFLICT`, não force `unzip` por cima das alterações locais: encaminhe os hashes/arquivos modificados para gerar patch de merge.

Resultados devem ser enviados com o resumo de `p1-full-audit`, `p1-closure-audit` e `ui-board`, sem logs de `WorldImport` repetidos no terminal.
