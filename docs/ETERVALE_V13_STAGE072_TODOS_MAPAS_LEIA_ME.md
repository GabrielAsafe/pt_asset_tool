# Etervale V13 — validação de todos os mapas Stage0.72

**Pré-requisito:** V12 instalada e aprovada. Patch incremental **aditivo**: não substitui o código da V12, nem altera o jogo.

## Instalação

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V13_STAGE072_TODOS_MAPAS_2026-11-10.zip" -d .
python3 patches/aplicar_etervale_v13_stage072_batch.py --project-root "$PWD" --dry-run
python3 patches/aplicar_etervale_v13_stage072_batch.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_stage072_all_maps_v13.py
```

## Executar — nível 1, todos os Stage, sem Blender

```bash
python3 app/pt_stage072_batch_audit.py
```

Não precisa de terminar o lote SMD Preview para realizar esta auditoria estática, embora continue a consumir CPU e disco de leitura. O output permanece sob `app/pt_build/etervale/stage072_all_maps/`.

O script mostra `[X/N]` com o estado de cada mapa e grava `stage_0_summary.json`, `stage_0_maps.csv` e `stage_0_checkpoint.jsonl`. Resultados são preservados e retomados na segunda execução. Use `--limit 3` para testar uma amostra antes do catálogo inteiro.

## Executar — nível 2, Blender headless (depois do lote SMD)

```bash
python3 app/pt_stage072_batch_audit.py --blender --timeout 360
```

Executa um mapa por vez, gera `.blend` em área temporária, verifica o transporte de vértices/UVs/luzes e o proxy de eixos V12 sem guardar alterações no Stage original. Esta fase pode ocupar bastante espaço em `pt_build` e demorar, por isso é recomendável esperar pelo fim do job SMD.

**Este processo não abre automaticamente centenas de Texture Paint UI**, nem certifica visualmente o resultado no motor. O relatório separa `paint_policy` estática, Blender headless e provas visuais pendentes.

## Resultados para analisar

Partilhe o bloco final JSON com `stage_files_discovered`, `counts`, `paint_counts`, `blender_counts`, `known_missing_total`, `missing_total`, `case_collision_total` e, se houver problemas, as linhas pertinentes de `stage_0_maps.csv`. Exit code `3` significa revisão necessária, não interrupção do processo.

Documentação: `docs/etervale/V13_STAGE072_TODOS_MAPAS_AUDITORIA.md`.
