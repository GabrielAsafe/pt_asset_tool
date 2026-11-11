# V21.1 — Hotfix do pincel semântico no Blender 5.2

Corrige `PT_SEMANTIC=FAIL reason=NameError:name 'StringProperty' is not defined` na V21.

## Instalar

Com o ZIP de distribuição descarregado em `~/Transferências/`:

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V21_1_STAGE072_SEMANTIC_PROPS_2026-11-10.zip" -d .
python3 patches/aplicar_etervale_v21_1_semantic.py --project-root "$PWD" --dry-run
python3 patches/aplicar_etervale_v21_1_semantic.py --project-root "$PWD"
python3 -m pytest -q \
  app/dev_tests/test_etervale_stage072_semantic_v21.py \
  app/dev_tests/test_etervale_stage072_semantic_blender_props_v21_1.py
```

Não aplicar se aparecer `SOURCE_FILE_CONFLICT`: nesse caso envia o relatório; não usar `--force` nem substituir o script inteiro à mão.

## Reabrir o mapa piloto

```bash
python3 app/pt_stage072_semantic_paint.py --map Field/forest/fore-1.smd
```

O terminal deve apresentar `PT_SEMANTIC=READY` (não `PT_SEMANTIC=FAIL`). No Blender: `N` → `Etervale` → `Classificação V21`. Marca uma copa e fecha o Blender. As marcações ficam em `app/pt_build/etervale/stage072_semantic_v21/maps/`.

## Impacto

1 ficheiro existente modificado, 1 novo teste e 1 nova documentação. O patch faz backup do ficheiro modificado, é idempotente e exige SHA exato da V21. Sem alterações aos SMD/UVs/cliente Etervale/geração de previews.

Testes offline não substituem a execução real do Blender 5.2.
